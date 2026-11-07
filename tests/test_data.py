import json
import sqlite3
from datetime import date, datetime

import pytest

from clear import backup, db
from clear.info import SCHEMA_VERSION
from clear.config import AppConfig, load_config, save_config
from clear.models import Bill, LivingCost
from clear.paths import default_data_dir, find_legacy_databases, find_root, unique_path
from clear.periods import Period
from clear.repo import ClosePlan, Repository

from conftest import TODAY, make_legacy_36, make_legacy_minimal, make_legacy_old, make_v40

NOV = Period(2026, 11)


# ---- migration (F18) ------------------------------------------------------------------
def test_classify(tmp_path):
    legacy = make_legacy_36(tmp_path / "a.db")
    assert db.classify(legacy) == "legacy"
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert db.classify(empty) == "new"
    other = tmp_path / "other.db"
    c = sqlite3.connect(other)
    c.execute("CREATE TABLE t (x)")
    c.close()
    assert db.classify(other) == "foreign"
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not a database at all" * 100)
    with pytest.raises(db.NotADatabaseError):
        db.classify(junk)


def test_migrate_36_file(tmp_path):
    path = make_legacy_36(tmp_path / "Jun.db", last_reset=(2026, 8))
    repo, report = Repository.open(path, TODAY)
    assert report.legacy and report.migrated
    assert report.open_period == "2026-08" and report.last_closed == "2026-07"
    assert report.converted_bill_payments == 1 and report.converted_living_payments == 1
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION

    bills = {b.bill_name: b for b in repo.bills()}
    # the paid tick of August became a payment with interest: 500,000 -> 486,250
    assert bills["Loan A"].amount == 486250
    assert bills["Loan A"].cmp_period == "2026-08"
    assert [b.bill_name for b in repo.bills()][0] == "Card B"  # sort order kept
    pays = repo.payments(Period(2026, 8))
    assert {(p.target_type, p.interest, p.principal) for p in pays} >= {("bill", 6250, 13750)}

    state = repo.load_state(TODAY)
    assert state.last_closed == Period(2026, 7)
    assert state.due_close_periods() == [Period(2026, 8), Period(2026, 9), Period(2026, 10)]
    assert state.profile.cumulative_savings == 120000
    assert state.cards[0].managed_in_bills is True
    rent = [lc for lc in state.living if lc.name == "Rent"][0]
    assert rent.created_date == date(2025, 9, 3) and rent.last_updated == date(2026, 1, 1)


def test_migrate_older_layout_adds_columns(tmp_path):
    path = make_legacy_old(tmp_path / "cny.db")
    repo, report = Repository.open(path, TODAY)
    assert any("living_costs.description" in c for c in report.changes)
    assert any("credit_cards.shopping_credit_amount" in c for c in report.changes)
    bills = repo.bills()
    assert bills[0].currency == "CNY" and bills[0].amount == 23456.78
    assert bills[0].sort_order == bills[0].id
    assert repo.living()[0].description == ""
    assert repo.profile().monthly_income_currency == "CNY"
    assert repo.profile().simulation_months == 23
    assert repo.last_closed() == Period(2026, 4)


def test_migrate_minimal_layout(tmp_path):
    path = make_legacy_minimal(tmp_path / "old.db")
    repo, report = Repository.open(path, TODAY)
    b = repo.bills()[0]
    assert b.bill_type == "other_loan" and b.currency == "JPY" and b.monthly_due_day == 31
    assert repo.last_closed() == Period(2026, 10)  # no month state in the file: start this month


def test_migrate_is_idempotent(tmp_path):
    path = make_legacy_36(tmp_path / "a.db")
    Repository.open(path, TODAY)
    before = [b.amount for b in Repository(path).bills()]
    _repo, report = Repository.open(path, TODAY)
    assert not report.migrated
    assert [b.amount for b in Repository(path).bills()] == before


def test_upgrade_from_40(tmp_path):
    path = make_v40(tmp_path / "v40.db")
    assert db.classify(path) == "older"
    repo, report = Repository.open(path, TODAY)
    assert report.migrated and report.from_version == 1 and not report.legacy
    assert {"create holdings", "create trades", "add bills.auto_debit", "add credit_cards.fee_month"} \
        <= set(report.changes)
    assert db.classify(path) == "current"
    # loans are taken from the bank; money borrowed from people is paid by hand
    assert {b.bill_name: b.auto_debit for b in repo.bills()} == {"Loan A": True, "Family": False}
    # 4.0's "fee paid" becomes "paid this year"; a free card stays free
    cards = {c.name: c for c in repo.cards()}
    assert cards["Gold"].fee_paid_period == "2026" and cards["Basic"].fee_paid_period == ""
    assert cards["Free"].fee_paid_period == ""
    assert repo.last_closed() == Period(2026, 10)
    assert repo.holdings() == [] and repo.net_worth_history() == []
    _repo, again = Repository.open(path, TODAY)
    assert not again.migrated


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "future.db"
    Repository.create(path, TODAY)
    c = sqlite3.connect(path)
    c.execute("PRAGMA user_version = 99")
    c.close()
    with pytest.raises(db.NewerSchemaError):
        Repository.open(path, TODAY)


# ---- repository ------------------------------------------------------------------------------
def new_repo(tmp_path) -> Repository:
    return Repository.create(tmp_path / "new.db", TODAY)


def test_create_and_crud(tmp_path):
    repo = new_repo(tmp_path)
    assert repo.last_closed() == Period(2026, 10)
    a = repo.add_bill(Bill(bill_name="A", amount=1000, monthly_payment=100))
    b = repo.add_bill(Bill(bill_name="B", amount=2000, monthly_payment=100))
    repo.reorder_bills([b.id, a.id])
    assert [x.bill_name for x in repo.bills()] == ["B", "A"]
    a.amount = 900
    repo.update_bill(a)
    assert {x.bill_name: x.amount for x in repo.bills()}["A"] == 900
    repo.delete_bill(b.id)
    assert [x.bill_name for x in repo.bills()] == ["A"]
    lc = repo.add_living(LivingCost(name="Gas", amount=5000))
    lc.amount = 5500
    repo.update_living(lc)
    assert repo.living()[0].amount == 5500


def test_payment_record_and_undo_restore_balance(tmp_path):
    repo = new_repo(tmp_path)
    bill = repo.add_bill(Bill(bill_name="L", amount=500000, interest_rate=15, monthly_payment=20000))
    p1 = repo.record_bill_payment(bill.id, NOV, date(2026, 11, 27), 20000)
    assert (p1.interest, p1.principal, p1.balance_after) == (6250, 13750, 486250)
    p2 = repo.record_bill_payment(bill.id, NOV, date(2026, 11, 28), 50000)  # extra payment: no 2nd interest
    assert p2.interest == 0 and p2.balance_after == 436250
    assert repo.undo_last_payment("bill", bill.id, NOV)
    assert repo.bills()[0].amount == 486250
    assert repo.undo_last_payment("bill", bill.id, NOV)
    assert repo.bills()[0].amount == 500000
    assert not repo.undo_last_payment("bill", bill.id, NOV)


def test_payment_with_given_interest_ends_at_the_edited_balance(tmp_path):
    """B2: a balance edited by hand after a debit is saved as that payment, not subtracted twice."""
    repo = new_repo(tmp_path)
    bill = repo.add_bill(Bill(bill_name="L", amount=650000, interest_rate=14, monthly_payment=25000,
                              monthly_due_day=2))
    p = repo.record_bill_payment(bill.id, NOV, date(2026, 11, 2), 25000, 25000 - 17417)
    assert (p.interest, p.principal, p.balance_after) == (7583, 17417, 632583)
    assert repo.bills()[0].amount == 632583
    assert repo.undo_last_payment("bill", bill.id, NOV) and repo.bills()[0].amount == 650000


def test_overpayment_clamps_and_undoes_exactly(tmp_path):
    repo = new_repo(tmp_path)
    bill = repo.add_bill(Bill(bill_type="shopping credit", bill_name="C", amount=30000))
    p = repo.record_bill_payment(bill.id, NOV, date(2026, 11, 10), 35000)
    assert p.balance_after == 0
    repo.undo_last_payment("bill", bill.id, NOV)
    assert repo.bills()[0].amount == 30000


def test_close_month_records_and_accrues(tmp_path):
    repo = new_repo(tmp_path)
    oct_ = Period(2026, 10)
    paid = repo.add_bill(Bill(bill_name="Paid", amount=500000, interest_rate=15, monthly_payment=20000))
    unpaid = repo.add_bill(Bill(bill_name="Unpaid", amount=300000, interest_rate=12, monthly_payment=10000))
    rent = repo.add_living(LivingCost(name="Rent", amount=80000))
    prof = repo.profile()
    prof.cumulative_savings, prof.other_income, prof.other_income_type = 1000, 5000, "bonus"
    repo.save_profile(prof)
    with sqlite3.connect(repo.path) as c:
        c.execute("UPDATE meta SET value='2026-09' WHERE key='last_closed_period'")
    plan = ClosePlan(oct_, bill_payments=[(paid.id, 20000, date(2026, 10, 27))], accrue_bill_ids=[unpaid.id],
                     living_payments=[(rent.id, 80000, date(2026, 10, 27))], savings_after=42000)
    summary = repo.close_month(plan, backup_file="x.db")
    assert summary["payments"] == 1 and summary["accruals"] == 1 and summary["living"] == 1
    amounts = {b.bill_name: b.amount for b in repo.bills()}
    assert amounts == {"Paid": 486250, "Unpaid": 303000}
    prof = repo.profile()
    assert prof.cumulative_savings == 42000 and prof.other_income == 0 and prof.other_income_type == ""
    assert repo.last_closed() == oct_
    assert repo.latest_close()["backup_file"] == "x.db"


def test_skip_close(tmp_path):
    repo = new_repo(tmp_path)
    with sqlite3.connect(repo.path) as c:
        c.execute("UPDATE meta SET value='2026-07' WHERE key='last_closed_period'")
    assert repo.skip_close(Period(2026, 10)) == 3
    assert repo.last_closed() == Period(2026, 10)


# ---- backups (F15) ---------------------------------------------------------------------------
def test_backup_list_prune_restore(tmp_path):
    repo = new_repo(tmp_path)
    root = tmp_path / "backups"
    repo.add_bill(Bill(bill_name="A", amount=1))
    first = backup.make_backup(repo.path, root, "manual", now=datetime(2026, 11, 1, 9, 0, 0))
    for i in range(5):
        backup.make_backup(repo.path, root, "startup", keep=3, now=datetime(2026, 11, 2, 9, 0, i))
    items = backup.list_backups(repo.path, root)
    assert len(items) == 3 and all(i.reason == "startup" for i in items)
    assert not first.exists()  # pruned (oldest)
    snap = backup.make_backup(repo.path, root, "manual")
    repo.add_bill(Bill(bill_name="B", amount=2))
    backup.restore(snap, repo.path, root)
    assert [b.bill_name for b in repo.bills()] == ["A"]
    assert backup.has_backup_today(repo.path, root, "manual")


# ---- config and paths ---------------------------------------------------------------------------
def test_config_roundtrip_and_broken(tmp_path):
    path = tmp_path / "config.json"
    cfg = load_config(path)
    assert cfg.language == "ja" and cfg.theme == "system"
    cfg.language, cfg.display_currency = "en", "CNY"
    save_config(cfg, path)
    again = load_config(path)
    assert again.language == "en" and again.display_currency == "CNY"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path) == AppConfig() or load_config(path).language == "ja"


def test_config_from_40_moves_saved_columns(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "language": "ja",
        "hidden_columns": {"bills": [13], "cards": [11, 14], "living": [8, 9], "plan": [5]},
        "column_widths": {"cards": [110, 150, 60, 100, 100, 100, 60, 84, 126, 126, 90, 90, 56, 112, 96],
                          "plan": [150, 101, 102, 103, 104, 105, 106, 107]}}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.columns_version == 3
    assert cfg.hidden("cards") == {13}             # fee status merged into the fee column; "updated" 14 -> 13
    assert cfg.hidden("plan") == {6}               # savings 5 -> 6 (contributions and investments added)
    assert cfg.hidden("invest") == {11, 12, 13} and cfg.hidden("bills") == {13}
    cards, plan = cfg.column_widths["cards"], cfg.column_widths["plan"]
    assert len(cards) == 14 and cards[10] == 210 and cards[11:] == [56, 112, 96]
    assert plan == [150, 101, 102, 103, 0, 104, 105, 0, 106, 0, 107]   # 4.1.2: savings - debt before net worth
    save_config(cfg, path)
    assert load_config(path).hidden("cards") == {13}  # moved once only


def test_config_from_41_moves_the_net_worth_column(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"columns_version": 2, "hidden_columns": {"plan": [3, 9], "invest": [11]}}),
                    encoding="utf-8")
    cfg = load_config(path)
    assert cfg.columns_version == 3
    assert cfg.hidden("plan") == {3, 10}           # net worth 9 -> 10
    assert cfg.hidden("invest") == {11}            # other tables are left alone
    save_config(cfg, path)
    assert load_config(path).hidden("plan") == {3, 10}


def test_paths(tmp_path):
    root = tmp_path / "マイドライブ" / "App Development"
    app = root / "2026" / "Oct" / "Personal" / "CLEAR" / "Ver4" / "4.0.0"
    app.mkdir(parents=True)
    assert find_root(app) == root
    assert default_data_dir(app) == root / "AppData" / "CLEAR"
    old = root / "2026" / "June" / "Personal" / "Payback Management" / "Ver3"
    for ver, name in (("ver3.5/ver3.5.9", "a.db"), ("ver3.6/ver3.6.0", "a.db"), ("ver3.6/ver3.6.0", "b.db")):
        folder = old / ver / "save"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"x")
    found = find_legacy_databases(app)
    assert sorted(p.name for p in found) == ["a.db", "b.db"]
    (root / "AppData").mkdir()
    (root / "AppData" / "x.db").write_bytes(b"")
    assert unique_path(root / "AppData", "x.db").name == "x (2).db"

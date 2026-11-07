"""4.1.2: this month's payment or the next one, the first payment month, saving under a new name,
and savings minus debt in the plan.

Synthetic data only. "Today" is Saturday 7 November 2026; the 2nd of the month is a Monday.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from clear import db, engine
from clear.engine import PeriodPaid, State
from clear.models import Bill, Holding, LivingCost, Profile
from clear.money import fmt_number
from clear.periods import Period
from clear.repo import Repository
from conftest import make_v41

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

RATES = {"USD": 1.0, "JPY": 150.0, "CNY": 7.0, "SGD": 1.3}
TODAY = date(2026, 11, 7)
NOV, DEC, JAN = Period(2026, 11), Period(2026, 12), Period(2027, 1)
NOV_2, DEC_2 = date(2026, 11, 2), date(2026, 12, 2)


def card_bill(**kw) -> Bill:
    base = dict(id=1, bill_name="Card bill", bill_type="shopping credit", amount=50000, monthly_due_day=2,
                currency="JPY", auto_debit=True)
    base.update(kw)
    return Bill(**base)


def loan(**kw) -> Bill:
    base = dict(id=2, bill_name="Loan", bill_type="card_loan", amount=650000, interest_rate=14.0,
                monthly_payment=25000, monthly_due_day=2, currency="JPY", auto_debit=True)
    base.update(kw)
    return Bill(**base)


def power(**kw) -> LivingCost:
    base = dict(id=3, name="Power", category="Utilities", amount=12000, monthly_due_day=2,
                payment_method="Auto Debit", currency="JPY")
    base.update(kw)
    return LivingCost(**base)


def state(**kw) -> State:
    base = dict(profile=Profile(cumulative_savings=100000, monthly_income=300000, payday=25), today=TODAY,
                last_closed=Period(2026, 10))
    base.update(kw)
    return State(**base)


# ---- engine: nothing is due before the first payment month --------------------------------------------
def test_a_debt_that_starts_next_month_is_not_due_now():
    b = card_bill(start_period="2026-12")
    st = state(bills=[b])
    assert engine.month_items(st, RATES, "JPY") == []
    assert engine.pending_debits(st, RATES, "JPY") == []
    assert "pending_debit" not in {a.code for a in engine.home_summary(st, RATES, "JPY").alerts}
    assert engine.planned_amount(b, NOV) == 0 and engine.planned_amount(b, DEC) == 50000
    info = engine.payoff_info(b, NOV)
    assert (info.status, info.period, info.months) == ("ok", DEC, 2)
    rows = engine.simulate(st, 3, RATES, "JPY")
    assert [r.debt_payment for r in rows] == [0, 50000, 0] and [r.debt for r in rows] == [50000, 0, 0]
    assert engine.close_items([b], [], NOV, []) == []                 # not part of November's close
    assert [i.planned for i in engine.close_items([b], [], DEC, [])] == [50000]
    assert engine.next_period(b, NOV, False) == DEC


def test_interest_waits_for_the_first_payment():
    b = loan(start_period="2027-01")
    rows = engine.project_bill(b, NOV, 3)
    assert [(r.payment, r.interest, r.balance) for r in rows[:2]] == [(0, 0, 650000), (0, 0, 650000)]
    assert (rows[2].payment, rows[2].interest, rows[2].principal) == (25000, 7583, 17417)
    info = engine.payoff_info(b, NOV)
    assert info.status == "ok" and info.months == engine.payoff_info(loan(), NOV).months + 2


def test_a_payment_recorded_before_the_first_month_still_shows():
    b = card_bill(start_period="2026-12")
    st = state(bills=[b], paid_bills={1: PeriodPaid(amount=50000, principal=50000, count=1, last_date=TODAY)})
    items = engine.month_items(st, RATES, "JPY")
    assert len(items) == 1 and items[0].paid and items[0].amount == 50000


def test_living_costs_start_in_their_first_month():
    st = state(living=[power(start_period="2026-12"),
                       power(id=4, name="Phone", payment_method="Credit Card", amount=4800, start_period="2026-12")])
    assert engine.month_items(st, RATES, "JPY") == []
    assert engine.close_items([], st.living, NOV, []) == []
    rows = engine.simulate(st, 3, RATES, "JPY")
    # power is debited from December; the phone is charged in December and paid with January's card bill
    assert [r.living for r in rows] == [0, 12000, 16800]


def test_next_period():
    assert engine.next_period(loan(), NOV, False) == NOV
    assert engine.next_period(loan(), NOV, True) == DEC
    assert engine.next_period(loan(start_period="2027-01"), NOV, True) == JAN
    assert engine.started(loan(start_period="2026-11"), NOV) and not engine.started(loan(start_period="2026-12"), NOV)
    assert engine.started(loan(start_period="x"), NOV)                  # an unreadable month is no limit


# ---- data file ------------------------------------------------------------------------------------------
def test_a_41_file_is_upgraded_with_empty_first_months(tmp_path):
    path = make_v41(tmp_path / "v41.db")
    assert db.classify(path) == "older"
    repo, report = Repository.open(path, TODAY)
    assert report.migrated and report.from_version == 2
    assert {"add bills.start_period", "add living_costs.start_period"} <= set(report.changes)
    assert all(b.start_period == "" for b in repo.bills()) and repo.living()[0].start_period == ""
    b = repo.bills()[0]
    b.start_period = "2026-12"
    repo.update_bill(b)
    assert repo.bills()[0].start_period == "2026-12"
    assert db.classify(path) == "current"


def test_settle_a_card_bill_then_keep_the_next_statement(tmp_path):
    repo = Repository.create(tmp_path / "x.db", TODAY)
    bill = repo.add_bill(card_bill(id=None, amount=30000))
    edited = Bill(**{**bill.__dict__, "amount": 50000})
    pay = repo.settle_and_update_bill(edited, NOV, NOV_2, 30000, None, keep_balance=False)
    assert (pay.principal, pay.balance_after) == (30000, 0)
    st = repo.load_state(TODAY)
    assert st.bills[0].amount == 50000 and st.paid_bills[bill.id].amount == 30000
    assert engine.pending_debits(st, RATES, "JPY") == []
    assert engine.payoff_info(st.bills[0], NOV, st.paid_bills[bill.id]).period == DEC
    # undoing November's payment puts it back on top of the next statement
    assert repo.undo_last_payment("bill", bill.id, NOV) and repo.bills()[0].amount == 80000


def test_settle_living_cost_then_save_the_new_amount(tmp_path):
    repo = Repository.create(tmp_path / "x.db", TODAY)
    lc = repo.add_living(power(id=None))
    edited = LivingCost(**{**lc.__dict__, "amount": 9500})
    repo.settle_and_update_living(edited, NOV, NOV_2, 12000, "JPY")
    st = repo.load_state(TODAY)
    assert st.living[0].amount == 9500 and st.paid_living[lc.id].amount == 12000
    assert engine.pending_debits(st, RATES, "JPY") == []


# ---- the window and the store ------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def store(tmp_path, monkeypatch, app):
    monkeypatch.setenv("CLEAR_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CLEAR_TODAY", TODAY.isoformat())
    from clear import i18n, theme
    from clear.config import AppConfig
    from clear.store import Store

    i18n.set_language("ja")
    theme.apply(app, "light")
    cfg = AppConfig(data_dir=str(tmp_path / "data"), welcome_done=True)
    s = Store(cfg, tmp_path / "cfg" / "config.json")
    assert s.ensure_data_dir()
    s.create_db("Household")
    return s


def by_name(store, name):
    return next(b for b in store.state().bills if b.bill_name == name)


def test_settle_keeps_or_lands_on_the_balance(store):
    store.add_bill(loan(id=None))
    old = by_name(store, "Loan")
    store.settle_and_update_bill(Bill(**{**old.__dict__, "bill_name": "Loan"}), old, NOV_2, 25000)
    st = store.state()
    assert by_name(store, "Loan").amount == 632583                    # unchanged: the balance after the payment
    assert (st.paid_bills[old.id].interest, st.paid_bills[old.id].principal) == (7583, 17417)

    store.add_bill(loan(id=None, bill_name="Loan 2"))
    old = by_name(store, "Loan 2")
    store.settle_and_update_bill(Bill(**{**old.__dict__, "amount": 632600}), old, NOV_2, 25000)
    paid = store.state().paid_bills[old.id]
    assert by_name(store, "Loan 2").amount == 632600                  # lowered: taken as the balance after it
    assert (paid.interest, paid.principal) == (7600, 17400)

    store.add_bill(card_bill(id=None, amount=30000))
    old = by_name(store, "Card bill")
    store.settle_and_update_bill(Bill(**{**old.__dict__, "amount": 50000}), old, NOV_2, 30000)
    assert by_name(store, "Card bill").amount == 50000                # the next statement as entered
    assert store.pending_debits() == []


def test_save_as_copies_the_data_and_switches(store):
    store.add_bill(loan(id=None))
    original = store.db_path
    before = original.read_bytes()
    copy = store.save_as("Household 2026-11-07")
    assert copy.name == "Household 2026-11-07.db" and copy.parent == store.data_dir
    assert store.db_path == copy and store.cfg.last_db == copy.name
    assert [b.bill_name for b in store.state().bills] == ["Loan"]
    assert original.read_bytes() == before                            # the original file is left as it is
    store.add_bill(card_bill(id=None))
    assert [b.bill_name for b in Repository(original).bills()] == ["Loan"]
    with pytest.raises(FileExistsError):
        store.save_as("Household 2026-11-07.db")
    other = store.save_as("Trial", switch=False)
    assert store.db_path == copy and other.exists()
    assert sorted(p.name for p in store.list_db_files()) == ["Household 2026-11-07.db", "Household.db", "Trial.db"]


def test_file_names():
    from clear.dialogs import file_name_problem
    assert file_name_problem("Household 2026-11-07") == ""
    assert file_name_problem("家計 (試算).db") == ""
    assert file_name_problem("  ") == "file.err.empty" and file_name_problem(".db") == "file.err.empty"
    assert file_name_problem("a/b") == "file.err.chars" and file_name_problem('x"y') == "file.err.chars"
    assert file_name_problem("CON") == "file.err.reserved" and file_name_problem("lpt1.db") == "file.err.reserved"


def test_save_as_dialog(store, app):
    from clear.dialogs import SaveAsDialog

    dlg = SaveAsDialog(None, store.db_path, store.data_dir, TODAY)
    assert dlg.name.text() == "Household 2026-11-07" and dlg.switch.isChecked()
    assert dlg.validate()
    dlg.name.setText("Household")
    assert not dlg.validate() and dlg.error.text() == "同じ名前のファイルがあります"
    dlg.name.setText("a:b")
    assert not dlg.validate()
    dlg.name.setText("Trial")
    assert dlg.values() == ("Trial.db", True)
    dlg.close()


# ---- dialogs ---------------------------------------------------------------------------------------------
def test_bill_dialog_after_the_payment_date(app):
    from clear.dialogs import BillDialog

    dlg = BillDialog(None, loan(), NOV, "JPY", today=TODAY)
    assert dlg.apply_from is not None and dlg.first is None
    assert dlg.from_next and dlg.settle() == (NOV_2, 25000)           # automatic debit: done by default
    assert "2026年12月" in dlg.one_off_label.text()
    assert "11/2の引き落とし" in dlg.apply_from.hint.text() and "12/2" in dlg.apply_from.next_btn.text()
    dlg.one_off.setValue(60000)
    assert dlg.result_bill().cmp_period == "2026-12"                   # a one-off for the next payment
    dlg.apply_from.now_btn.setChecked(True)
    assert dlg.settle() is None and dlg.result_bill().cmp_period == "2026-11"
    assert "2026年11月" in dlg.one_off_label.text()
    dlg.close()

    by_hand = BillDialog(None, loan(auto_debit=False), NOV, "JPY", today=TODAY)
    assert not by_hand.from_next and by_hand.settle() is None          # paid by hand: nothing assumed
    by_hand.close()

    paid = BillDialog(None, loan(), NOV, "JPY", today=TODAY, paid=True)
    assert paid.apply_from is None and "2026年12月" in paid.one_off_label.text()
    paid.close()

    later = BillDialog(None, loan(monthly_due_day=27), NOV, "JPY", today=TODAY)
    assert later.apply_from is None and "2026年11月" in later.one_off_label.text()
    later.close()

    empty = BillDialog(None, card_bill(amount=0), NOV, "JPY", today=TODAY)
    empty.balance.setValue(50000)                                      # next month's statement
    assert empty.settle() is None and empty.result_bill().start_period == "2026-12"
    assert "支払いはなし" in empty.apply_from.hint.text()
    empty.close()


def test_new_debt_after_its_payment_day_starts_next_month(app):
    from clear.dialogs import BillDialog

    dlg = BillDialog(None, None, NOV, "JPY", today=TODAY)
    assert dlg.apply_from is None and dlg.first is not None
    dlg.due.setValue(2)
    assert dlg.first.period() == DEC and dlg.result_bill().start_period == "2026-12"
    assert "12/2（来月）" in dlg.first.currentText()
    dlg.due.setValue(27)
    assert dlg.first.period() == NOV
    dlg.first.touched = True                                           # chosen by hand: kept
    dlg.first.set_period(JAN)
    dlg.due.setValue(2)
    assert dlg.first.period() == JAN and dlg.first.currentText().startswith("1/4")   # 2 Jan is a bank holiday
    dlg.close()

    waiting = BillDialog(None, card_bill(start_period="2026-12"), NOV, "JPY", today=TODAY)
    assert waiting.apply_from is None and waiting.first.period() == DEC
    waiting.close()


def test_living_dialog_after_the_payment_date(app):
    from clear.dialogs import LivingDialog

    dlg = LivingDialog(None, power(), "JPY", today=TODAY)
    assert dlg.from_next and dlg.settle() == (NOV_2, 12000)
    dlg.amount.setValue(9500)
    assert dlg.result_living().amount == 9500
    dlg.close()
    card = LivingDialog(None, power(payment_method="Credit Card"), "JPY", today=TODAY)
    assert card.apply_from is None and card.settle() is None
    card.close()
    new = LivingDialog(None, None, "JPY", today=TODAY)
    new.due.setValue(2)
    assert new.result_living().start_period == "2026-12"
    new.close()


def test_editing_after_the_debit_records_it_and_applies_next_time(store, app, monkeypatch):
    """The reported case: a card bill debited on the 2nd, next month's statement entered on the 7th."""
    from PyQt6.QtWidgets import QDialog

    from clear import main_window
    from clear.dialogs import BillDialog
    from clear.main_window import MainWindow

    store.add_bill(card_bill(id=None, amount=30000))
    store.add_living(power(id=None))
    win = MainWindow(store)
    assert {it.name for it in store.pending_debits()} == {"Card bill", "Power"}

    def enter_next_statement(dlg):
        dlg.balance.setValue(50000)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BillDialog, "exec", enter_next_statement)
    notes: list[str] = []
    monkeypatch.setattr(main_window.MainWindow, "notify", lambda _self, text, is_error=False: notes.append(text))
    win.edit_bill(by_name(store, "Card bill"))
    st = store.state()
    bill = by_name(store, "Card bill")
    assert bill.amount == 50000 and st.paid_bills[bill.id].amount == 30000
    assert notes and "11/2" in notes[-1] and "次回から" in notes[-1]
    assert {it.name for it in store.pending_debits()} == {"Power"}

    # the debts table shows the next debit instead of "to record"
    win.navigate(1)
    page = win.pages[1]
    row = next(r for r in range(page.bills.rowCount()) if page.bills.item(r, 0).text() == "Card bill")
    assert "次は12/2" in page.bills.item(row, 9).text()
    assert "50,000" in page.bills.item(row, 9).toolTip()

    # a new debt for next month only: nothing to record this month
    def add_next_month(dlg):
        dlg.name.setText("Next card bill")
        dlg.type.setCurrentIndex(dlg.type.findData("shopping credit"))
        dlg.balance.setValue(20000)
        dlg.due.setValue(2)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BillDialog, "exec", add_next_month)
    win.add_bill()
    assert by_name(store, "Next card bill").start_period == "2026-12"
    assert {it.name for it in store.pending_debits()} == {"Power"}
    win.refresh()
    row = next(r for r in range(page.bills.rowCount()) if page.bills.item(r, 0).text() == "Next card bill")
    assert page.bills.item(row, 10).text() == "12月から" and page.bills.item(row, 8).text() == "—"
    win.close()


def test_plan_shows_savings_minus_debt(store, app):
    from clear.main_window import MainWindow
    from clear.page_plan import CASH_NET, WORTH

    store.add_bill(loan(id=None))
    win = MainWindow(store)
    win.navigate(4)
    plan = win.pages[4]
    tbl = plan.table
    assert tbl.horizontalHeaderItem(CASH_NET).text() == "貯蓄−負債"
    assert tbl.horizontalHeaderItem(WORTH).text() == "純資産"
    assert tbl.isColumnHidden(CASH_NET)                               # no investments: it equals net worth
    store.add_holding(Holding(kind="manual", name="Fund", quantity=1, manual_price=400000, currency="JPY"))
    win.refresh()
    assert not tbl.isColumnHidden(CASH_NET)
    rows = engine.simulate(store.state(), store.state().profile.simulation_months, store.rates, store.currency)
    first = rows[0]
    assert first.cash_net == first.savings - first.debt and first.net_worth - first.cash_net == first.invest
    assert tbl.item(0, CASH_NET).text() == fmt_number(first.cash_net, "JPY")
    win.close()


def test_savings_minus_debt_leaves_out_the_investments():
    st = state(bills=[loan()], holdings=[Holding(id=1, kind="manual", name="Fund", quantity=1, manual_price=5000,
                                                 currency="JPY")])
    rows = engine.simulate(st, 3, RATES, "JPY")
    assert all(r.cash_net == pytest.approx(r.savings - r.debt) for r in rows)
    assert all(r.net_worth - r.cash_net == pytest.approx(r.invest) for r in rows)

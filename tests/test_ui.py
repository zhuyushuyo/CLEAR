"""Headless UI checks: every page builds, the month-end close works end to end, every text key exists."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pytest

from clear.models import Bill, CreditCard, Holding, Price
from conftest import make_legacy_36, make_v40

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "clear"


def test_every_text_key_exists_in_both_languages():
    from clear import i18n
    from clear.models import (ACCOUNTS, BILL_TYPES, CATEGORY_KEYS, CONTRIB_METHODS, HOLDING_KINDS, METAL_UNITS,
                              METALS, PAYMENT_METHODS, PRICE_SOURCES, TRADE_KINDS)

    used = set()
    for path in SRC.glob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["']([a-z_][\w.\- ]*)["']""", path.read_text(encoding="utf-8")))
    dynamic = {f"alert.{c}" for c in ("close_due", "underwater", "overdue", "due_soon", "due_today",
                                      "negative_month", "card_util", "no_plan", "rates_stale", "pending_debit",
                                      "fee_unpaid", "fee_no_month", "prices_missing", "prices_stale", "nisa_over")}
    dynamic |= {f"bt.{c}" for c in BILL_TYPES} | {f"cat.{c}" for c in CATEGORY_KEYS}
    dynamic |= {f"pm.{c}" for c in PAYMENT_METHODS} | {f"theme.{c}" for c in ("system", "light", "dark")}
    dynamic |= {f"cols.t.{c}" for c in ("bills", "cards", "living", "plan", "invest")}
    dynamic |= {f"reason.{c}" for c in ("startup", "close", "manual", "import", "restore", "undo-close", "upgrade")}
    dynamic |= {f"kind.{c}" for c in HOLDING_KINDS} | {f"acct.{c}" for c in ACCOUNTS}
    dynamic |= {f"metal.{c}" for c in METALS} | {f"src.{c}" for c in PRICE_SOURCES}
    dynamic |= {f"unit.{c}" for c in METAL_UNITS} | {f"unit1.{c}" for c in METAL_UNITS}
    dynamic |= {f"trade.{c}" for c in TRADE_KINDS} | {f"trade.m.{c}" for c in ("buy", "sell")}
    dynamic |= {f"cmethod.{c}" for c in CONTRIB_METHODS} | {f"invest.alloc.{c}" for c in ("kind", "account", "currency")}
    dynamic |= {f"nisa.frame.{c}" for c in ("nisa_tsumitate", "nisa_growth", "lifetime", "lifetime_growth")}
    dynamic |= {f"home.trend.{c}" for c in ("debt", "savings", "invest")}
    missing = sorted(k for k in used | dynamic if k not in i18n.S)
    assert not missing, missing
    for key, (ja, en) in i18n.S.items():
        assert ja and en, key
        assert set(re.findall(r"{(\w+)}", ja)) == set(re.findall(r"{(\w+)}", en)), key


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def env(tmp_path, monkeypatch, app):
    monkeypatch.setenv("CLEAR_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("CLEAR_TODAY", "2026-11-06")
    from clear import i18n, theme
    from clear.config import AppConfig
    from clear.store import Store

    i18n.set_language("ja")
    theme.apply(app, "light")
    root = tmp_path / "App Development"
    save = root / "2026" / "June" / "Personal" / "Payback Management" / "Ver3" / "ver3.6" / "ver3.6.0" / "save"
    save.mkdir(parents=True)
    legacy = make_legacy_36(save / "Household.db", last_reset=(2026, 10))
    cfg = AppConfig(data_dir=str(root / "AppData" / "CLEAR"), welcome_done=True)
    store = Store(cfg, tmp_path / "cfg" / "config.json")
    assert store.ensure_data_dir()
    return store, legacy


def test_import_keeps_the_original(env):
    store, legacy = env
    before = legacy.read_bytes()
    dest, report = store.import_legacy(legacy)
    assert legacy.read_bytes() == before            # the 3.x file is untouched
    assert dest.parent == store.data_dir and report.legacy
    assert store.due_close_periods()[0].month == 10
    assert store.backups() and store.backups()[0].reason == "import"


def test_pages_dialogs_and_close(env, app):
    from clear.close_wizard import MonthCloseDialog
    from clear.dialogs import BillDialog, CardDialog, ColumnsDialog, LivingDialog, PaymentDialog
    from clear.main_window import MainWindow
    from clear.periods import Period

    store, legacy = env
    store.import_legacy(legacy)
    win = MainWindow(store)
    win.show()
    for i in range(len(win.pages)):
        win.navigate(i)
        app.processEvents()
    assert win.banner.isVisible()

    st = store.state()
    for dlg in (BillDialog(win, st.bills[0], st.current, "JPY"), BillDialog(win, None, st.current, "JPY"),
                LivingDialog(win, st.living[0], "JPY"), CardDialog(win, st.cards[0], "JPY", date(2026, 11, 6)),
                PaymentDialog(win, st.bills[0], st.current, date(2026, 11, 6), False), ColumnsDialog(win, {})):
        dlg.show()
        app.processEvents()
        dlg.close()

    # month-end close of October through the wizard
    before = {b.bill_name: b.amount for b in store.state().bills}
    wiz = MonthCloseDialog(win, store, Period(2026, 10), Period(2026, 10))
    wiz.show()
    wiz._go(1)
    wiz._go(2)
    plan = wiz._plan()
    wiz.close()
    store.close_month(plan)
    history = store.net_worth_history()                # P1: the month-end net worth is kept
    assert [pt.period for pt in history] == ["2026-10"] and history[0].debts > 0
    after = {b.bill_name: b.amount for b in store.state().bills}
    assert after["Loan A"] == before["Loan A"]         # already recorded at import: not paid twice
    assert after["Rev C"] == 300500                    # 4,000 paid against 4,500 interest: balance grows
    assert after["Card B"] == 0                        # lump sum paid in full
    assert after["Family"] == 100000                   # no plan, no interest: unchanged
    assert store.due_close_periods() == []
    win.refresh()
    # the close banner is gone; what is left is the reminder to record November's automatic debits
    pending = store.pending_debits()
    assert pending and all(it.kind in ("bill", "living") and it.days < 0 for it in pending)
    assert win.banner.isVisible() and "自動引き落とし" in win.banner.text.text()
    assert store.record_debits([(it, it.amount) for it in pending]) == len(pending)
    win.refresh()
    assert not win.banner.isVisible()

    # undo the close restores the balances
    assert store.undo_last_close() == "2026-10"
    assert {b.bill_name: b.amount for b in store.state().bills} == before
    assert store.net_worth_history() == []

    # language and theme switch rebuild the window without errors
    win.set_language("en")
    win.set_theme("dark")
    for i in range(len(win.pages)):
        win.navigate(i)
        app.processEvents()
    win.close()


def test_window_import_and_data_folder_change(env, app, monkeypatch, tmp_path):
    from clear import main_window
    from clear.main_window import MainWindow

    store, legacy = env
    shown: list[str] = []
    monkeypatch.setattr(main_window, "info", lambda _w, text, _title=None: shown.append(text))
    monkeypatch.setattr(main_window, "error", lambda _w, text: shown.append("ERROR " + text))
    monkeypatch.setattr(main_window, "ask", lambda *_a, **_k: True)
    win = MainWindow(store)
    win.open_path(legacy)            # a 3.x file is never opened in place: it is imported
    assert store.db_path.parent == store.data_dir
    assert shown and "Household.db" in shown[-1] and not shown[-1].startswith("ERROR")

    new_dir = tmp_path / "elsewhere"
    store.set_data_dir(new_dir, copy_files=True)
    assert store.db_path.parent == new_dir and store.db_path.exists()
    assert store.cfg.last_db == store.db_path.name
    win.close()


def test_money_spin_shows_its_value(app):
    """Regression: a style sheet + hidden buttons collapsed the text field to 1 px in Qt 6."""
    from clear import theme
    from clear.widgets import MoneySpin

    theme.apply(app, "light")
    spin = MoneySpin("JPY")
    spin.setValue(300000)
    spin.resize(240, 34)
    spin.show()
    app.processEvents()
    assert spin.text() == "300,000"
    assert spin.lineEdit().width() > 100
    spin.close()


def test_opening_a_40_file_backs_it_up_first(env):
    store, _legacy = env
    path = make_v40(store.data_dir / "v40.db")
    report = store.open_db(path)
    assert report.migrated and report.from_version == 1
    assert "upgrade" in {b.reason for b in store.backups()}
    assert {b.bill_name: b.auto_debit for b in store.state().bills} == {"Loan A": True, "Family": False}


def test_edited_balance_is_saved_as_the_payment(env):
    """B2: lowering a balance by hand after a debit records that payment once."""
    store, legacy = env
    store.import_legacy(legacy)
    bill = next(b for b in store.state().bills if b.bill_name == "Loan A")
    old = bill.amount
    edited = Bill(**{**bill.__dict__, "amount": old - 15000})
    store.update_bill_with_payment(edited, old, date(2026, 11, 6), 20000)
    st = store.state()
    assert next(b for b in st.bills if b.id == bill.id).amount == old - 15000
    paid = st.paid_bills[bill.id]
    assert (paid.amount, paid.interest, paid.principal) == (20000, 5000, 15000)


def test_card_dialog_pins_a_40_fee_mark_to_its_cycle(env, app):
    from clear import engine
    from clear.dialogs import CardDialog

    card = CreditCard(id=9, issuer="Card Co", name="Gold", annual_fee=11000, fee_paid_period="2026",
                      created_date=date(2025, 1, 10))
    dlg = CardDialog(None, card, "JPY", date(2026, 11, 6))
    assert dlg.fee_paid.isChecked()                    # 4.0: "paid this year"
    dlg.fee_month.setCurrentIndex(dlg.fee_month.findData(12))
    out = dlg.result_card()
    assert out.fee_month == 12 and out.fee_paid_period == "2025-12"
    assert engine.fee_status(out, date(2026, 11, 6)).state == "paid"
    assert engine.fee_status(out, date(2026, 12, 10)).state == "due"   # the next bill is not paid yet
    dlg.close()


def test_investments_page_dialogs_and_contributions(env, app, monkeypatch):
    from clear import main_window
    from clear.dialogs import DebitDialog
    from clear.dialogs_invest import HoldingDialog, InvestSettingsDialog, TradeDialog
    from clear.main_window import MainWindow
    from clear.page_invest import InvestPage

    store, legacy = env
    store.import_legacy(legacy)
    shown: list[str] = []
    monkeypatch.setattr(main_window, "info", lambda _w, text, _title=None: shown.append(text))
    voo = store.add_holding(Holding(kind="stock", symbol="VOO", name="S&P 500 ETF", account="nisa_growth",
                                    quantity=12, avg_cost=420, currency="USD", quote_currency="USD",
                                    contrib_amount=30000, contrib_currency="JPY", contrib_day=10))
    gold = store.add_holding(Holding(kind="metal", symbol="gold", name="Gold", unit="g", quantity=100,
                                     avg_cost=9800, currency="JPY", adjust_pct=3.0))
    fund = store.add_holding(Holding(kind="manual", name="Index fund", account="nisa_tsumitate", quantity=1,
                                     avg_cost=1_000_000, manual_price=1_200_000, currency="JPY",
                                     price_source="manual", contrib_amount=50000, contrib_day=27,
                                     contrib_method="card"))
    new = store.add_holding(Holding(kind="stock", symbol="NEW1", name="No price yet", quantity=1, avg_cost=10,
                                    currency="USD", contrib_amount=10000, contrib_currency="JPY", contrib_day=10))
    stamp = "2026-11-06T09:00:00"
    store.repo.save_prices([Price("yahoo", "VOO", 560.0, "USD", 557.0, stamp),
                            Price("yahoo", "GC=F", 2650.0, "USD", 2640.0, stamp)])
    store._touch(saved=False)

    win = MainWindow(store)
    win.show()
    page = next(p for p in win.pages if isinstance(p, InvestPage))
    win.navigate(win.pages.index(page))
    app.processEvents()
    assert page.table.rowCount() == 4 and page.nisa_card.isVisible()
    assert all(bar.rows for bar in page.alloc_bars.values())
    page.tabs.setCurrentIndex(3)                       # precious metals only
    assert page.table.rowCount() == 1

    # a contribution buys at the latest price; without a price nothing is written
    win.toggle_paid("contrib", voo.id, True, voo.label, 0)
    tr = store.repo.trades(voo.id)
    assert len(tr) == 1 and tr[0].is_contrib and tr[0].quantity == pytest.approx(200 / 560, abs=1e-4)
    win.toggle_paid("contrib", new.id, True, new.label, 0)
    assert store.repo.trades(new.id) == [] and shown
    win.toggle_paid("contrib", fund.id, True, fund.label, 0)
    assert next(h for h in store.state().holdings if h.id == fund.id).manual_price == 1_250_000
    win.toggle_paid("contrib", voo.id, False, voo.label, 0)
    assert store.repo.trades(voo.id) == []

    for h in (None, voo, gold, fund):
        dlg = HoldingDialog(win, store, h, "JPY")
        dlg.show()
        app.processEvents()
        if h is not None:
            out = dlg.result_holding()
            assert (out.kind, out.symbol, out.account, out.currency) == (h.kind, h.symbol, h.account, h.currency)
        dlg.close()
    gold_out = HoldingDialog(win, store, gold, "JPY").result_holding()
    assert gold_out.unit == "g" and gold_out.adjust_pct == 3.0
    trade = TradeDialog(win, voo, date(2026, 11, 6), 560.0)
    trade.show()
    app.processEvents()
    assert trade.values()["kind"] == "buy"
    trade.close()
    settings = InvestSettingsDialog(win, store.returns(), True, "")
    assert set(settings.values()[0]) == {"stock", "crypto", "metal", "manual"}
    debits = DebitDialog(win, store.pending_debits())
    assert [it for it, _amount in debits.chosen()] == store.pending_debits()
    win.navigate(0)
    app.processEvents()
    win.close()

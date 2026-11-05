"""Headless UI checks: every page builds, the month-end close works end to end, every text key exists."""

from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

import pytest

from conftest import make_legacy_36

QtWidgets = pytest.importorskip("PyQt6.QtWidgets")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

SRC = Path(__file__).resolve().parent.parent / "clear"


def test_every_text_key_exists_in_both_languages():
    from clear import i18n
    from clear.models import BILL_TYPES, CATEGORY_KEYS, PAYMENT_METHODS

    used = set()
    for path in SRC.glob("*.py"):
        used |= set(re.findall(r"""\bt\(\s*["']([a-z_][\w.\- ]*)["']""", path.read_text(encoding="utf-8")))
    dynamic = {f"alert.{c}" for c in ("close_due", "underwater", "overdue", "due_soon", "due_today",
                                      "negative_month", "card_util", "no_plan", "rates_stale")}
    dynamic |= {f"bt.{c}" for c in BILL_TYPES} | {f"cat.{c}" for c in CATEGORY_KEYS}
    dynamic |= {f"pm.{c}" for c in PAYMENT_METHODS} | {f"theme.{c}" for c in ("system", "light", "dark")}
    dynamic |= {f"cols.t.{c}" for c in ("bills", "cards", "living", "plan")}
    dynamic |= {f"reason.{c}" for c in ("startup", "close", "manual", "import", "restore", "undo-close")}
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
                LivingDialog(win, st.living[0], "JPY"), CardDialog(win, st.cards[0], "JPY"),
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
    after = {b.bill_name: b.amount for b in store.state().bills}
    assert after["Loan A"] == before["Loan A"]         # already recorded at import: not paid twice
    assert after["Rev C"] == 300500                    # 4,000 paid against 4,500 interest: balance grows
    assert after["Card B"] == 0                        # lump sum paid in full
    assert after["Family"] == 100000                   # no plan, no interest: unchanged
    assert store.due_close_periods() == []
    win.refresh()
    assert not win.banner.isVisible()

    # undo the close restores the balances
    assert store.undo_last_close() == "2026-10"
    assert {b.bill_name: b.amount for b in store.state().bills} == before

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

"""Main window: builds the shell from a page registry (O2) and owns every user action."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QMainWindow,
                             QStackedWidget, QVBoxLayout, QWidget)

from . import db, engine, i18n, invest, paths, theme
from .close_wizard import MonthCloseDialog
from .dialogs import DELETE, TABLE_COLUMNS, BillDialog, CardDialog, ColumnsDialog, DebitDialog, LivingDialog, \
    PaymentDialog, SaveAsDialog, file_name_problem
from .dialogs_invest import HoldingDialog, InvestSettingsDialog, TradeDialog
from .i18n import fmt_date, fmt_datetime, fmt_md, fmt_period, join_names, money, t
from .info import APP_NAME, APP_VERSION
from .money import unit
from .page_data import DataPage
from .page_debts import DebtsPage
from .page_home import HomePage
from .page_invest import InvestPage
from .page_monthly import MonthlyPage
from .page_plan import PlanPage
from .periods import Period
from .shell import Header, Sidebar
from .store import LegacyFileError, NoDatabaseError, Store
from .welcome import WelcomeDialog
from .widgets import Banner, ask, ask3, error, info

log = logging.getLogger(__name__)

PAGES = (HomePage, DebtsPage, MonthlyPage, InvestPage, PlanPage, DataPage)


class MainWindow(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setMinimumSize(1100, 720)
        geo = store.cfg.window or {}
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        default_w = min(1560, avail.width() - 40) if avail else 1440
        default_h = min(940, avail.height() - 40) if avail else 880
        self.resize(int(geo.get("w", default_w)), int(geo.get("h", default_h)))
        if "x" in geo and "y" in geo:
            self.move(int(geo["x"]), int(geo["y"]))
        self.index = 0
        self._build()
        store.changed.connect(self.refresh)
        store.view_changed.connect(self.refresh)
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_theme_changed)
        except AttributeError:  # Qt < 6.5
            pass
        for page in range(len(PAGES)):
            QShortcut(QKeySequence(f"Ctrl+{page + 1}"), self, activated=lambda p=page: self.navigate(p))
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=self.save_as)

    # ---- layout -----------------------------------------------------------------------------------------
    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("Root")
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.pages = [cls(self.store, self) for cls in PAGES]
        self.sidebar = Sidebar(self.pages)
        self.sidebar.navigate.connect(self.navigate)
        lay.addWidget(self.sidebar)
        content = QWidget()
        content.setObjectName("Content")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.header = Header(self.store)
        self.header.currencyChanged.connect(self.store.set_currency)
        self.header.fileChosen.connect(self._file_chosen)
        self.header.closeRequested.connect(self.start_close)
        col.addWidget(self.header)
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(24, 14, 24, 0)
        self.banner = Banner()
        hl.addWidget(self.banner)
        col.addWidget(holder)
        self.banner_holder = holder
        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        for p in self.pages:
            self.stack.addWidget(p)
        col.addWidget(self.stack, 1)
        lay.addWidget(content, 1)
        old = self.centralWidget()
        self.setCentralWidget(root)
        if old is not None:
            old.deleteLater()
        self.statusBar().setSizeGripEnabled(False)
        self.navigate(self.index)

    def navigate(self, index: int) -> None:
        self.index = max(0, min(len(self.pages) - 1, index))
        self.stack.setCurrentIndex(self.index)
        self.sidebar.set_current(self.index)
        self.refresh()

    def refresh(self) -> None:
        page = self.pages[self.index]
        self.header.title.setText(page.title)
        self.header.refresh()
        self._update_banner()
        try:
            page.refresh()
        except Exception:  # never leave the window half-drawn
            log.exception("refresh failed on %s", page.key)
            raise

    def _update_banner(self) -> None:
        store = self.store
        if not store.has_db:
            self.banner.show_message(t("banner.no_db"), t("banner.no_db_action"), self.open_file_dialog, "info")
        else:
            due = store.due_close_periods()
            debits = store.pending_debits() if not due else []
            if not due and debits:
                dates = join_names([fmt_md(d, weekday=False) for d in sorted({it.due for it in debits})])
                self.banner.show_message(t("banner.debits", n=len(debits), dates=dates), t("banner.debits_action"),
                                         self.review_debits)
            elif not due:
                self.banner.hide()
            elif len(due) == 1:
                self.banner.show_message(t("banner.close_due", period=fmt_period(due[0])),
                                         t("banner.close_start"), self.start_close)
            else:
                self.banner.show_message(t("banner.close_due_many", first=fmt_period(due[0]),
                                           last=fmt_period(due[-1]), n=len(due)),
                                         t("banner.close_start"), self.start_close)
        self.banner_holder.setVisible(self.banner.isVisibleTo(self.banner_holder))

    # ---- helpers ------------------------------------------------------------------------------------------
    def notify(self, text: str, is_error: bool = False) -> None:
        if is_error:
            error(self, text)
        else:
            self.statusBar().showMessage(text, 6000)

    def guard(self, fn) -> bool:
        try:
            fn()
            return True
        except NoDatabaseError:
            self.notify(t("err.no_db"))
        except Exception as exc:
            log.exception("action failed")
            error(self, t("err.unexpected", error=exc))
        return False

    def open_folder(self, path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def save_widths(self, key: str, widths: list) -> None:
        self.store.cfg.column_widths[key] = widths
        self.store.save_config()

    # ---- start-up -------------------------------------------------------------------------------------------
    def startup(self) -> None:
        store = self.store
        if not store.ensure_data_dir():
            error(self, t("err.data_dir", path=paths.display_path(store.data_dir)))
            self.change_data_dir()
        if not store.cfg.welcome_done:
            self.run_welcome()
        else:
            last = store.last_db_path()
            if last is not None and last.exists():
                self.open_path(last, quiet=True)
        store.auto_update_rates()
        if store.cfg.auto_refresh_prices:
            store.refresh_market(quiet=True)
        self.refresh()
        QTimer.singleShot(0, self.maybe_prompt_debits)

    # ---- automatic debits (B2) ------------------------------------------------------------------------------
    def maybe_prompt_debits(self, force: bool = False) -> None:
        store = self.store
        if not store.has_db or store.due_close_periods():
            return
        items = store.pending_debits()
        if not items:
            if force:
                self.refresh()
            return
        today = store.today().isoformat()
        if not force and store.cfg.debit_prompt_date == today:
            return
        store.cfg.debit_prompt_date = today
        store.save_config()
        dlg = DebitDialog(self, items)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rows = dlg.chosen()
            result: list = []
            if rows and self.guard(lambda: result.append(store.record_debits(rows))):
                self.notify(t("debit.done", n=result[0] if result else 0))

    def review_debits(self) -> None:
        self.maybe_prompt_debits(force=True)

    def run_welcome(self) -> None:
        store = self.store
        dlg = WelcomeDialog(self, store.data_dir, paths.find_legacy_databases())
        accepted = dlg.exec() == QDialog.DialogCode.Accepted
        store.cfg.welcome_done = True
        store.save_config()
        if not accepted:
            return
        if dlg.data_dir != store.data_dir:
            try:
                store.set_data_dir(dlg.data_dir, copy_files=False)
            except OSError:
                error(self, t("err.data_dir", path=paths.display_path(dlg.data_dir)))
        imported = self._import_files(dlg.selected_imports())
        name = dlg.new_file_name()
        if name:
            self.guard(lambda: self._create(name, open_it=not imported))

    def _import_files(self, files: list[Path]) -> list:
        results, problems = [], []
        for src in files:
            try:
                dest, report = self.store.import_legacy(src, open_it=not results)
                results.append((dest, report))
            except Exception as exc:
                log.exception("import failed: %s", src)
                problems.append(t("import.failed", name=src.name, error=exc))
        if results:
            lines = []
            converted = 0
            for dest, rep in results:
                p = Period.try_parse(rep.open_period)
                lines.append(t("import.line", name=dest.name, bills=rep.bills, living=rep.living, cards=rep.cards,
                               period=fmt_period(p) if p else rep.open_period or "—"))
                converted += rep.converted_bill_payments + rep.converted_living_payments
            if converted:
                lines.append(t("import.converted", n=converted))
            lines.append(t("import.originals"))
            due = self.store.due_close_periods()
            if due:
                lines.append(t("import.close_hint", period=fmt_period(due[0])))
            info(self, "\n\n".join(lines + problems), t("import.done_title"))
        elif problems:
            error(self, "\n".join(problems))
        self.refresh()
        return results

    # ---- files ------------------------------------------------------------------------------------------------
    def _file_chosen(self, value: str) -> None:
        if value:
            self.open_path(Path(value))
        else:
            self.open_file_dialog()
            self.header.refresh()

    def open_path(self, path: Path, quiet: bool = False) -> None:
        try:
            report = self.store.open_db(path)
            if report.migrated and report.from_version >= 1:
                self.notify(t("import.upgraded", name=path.name))
        except LegacyFileError:
            if ask(self, t("import.legacy_q", name=path.name)):
                self._import_files([path])
        except db.NewerSchemaError:
            error(self, t("err.newer"))
        except db.NotADatabaseError:
            error(self, t("err.not_db"))
        except Exception as exc:
            log.exception("open failed: %s", path)
            if not quiet:
                error(self, t("err.open", error=exc))
        self.refresh()

    def open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("data.file.open"), str(self.store.data_dir),
                                              t("dlg.db_filter"))
        if path:
            self.open_path(Path(path))

    def new_file(self) -> None:
        name, ok = QInputDialog.getText(self, t("data.file.new"), t("data.file.new_name_q"), text="CLEAR")
        if ok and name.strip():
            self.guard(lambda: self._create(name, open_it=True))

    def _create(self, name: str, open_it: bool) -> None:
        problem = file_name_problem(name)
        if problem:
            error(self, t(problem))
            return
        if self.store.db_file_for(name).exists():
            error(self, t("data.file.exists"))
            return
        self.store.create_db(name, open_it=open_it)

    def save_as(self) -> None:
        """Save the open data under a new name (4.1.2)."""
        if not self._need_db():
            return
        dlg = SaveAsDialog(self, self.store.db_path, self.store.data_dir, self.store.today())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, switch = dlg.values()
        saved: list = []
        if self.guard(lambda: saved.append(self.store.save_as(name, switch))):
            self.notify(t("saveas.done_switch" if switch else "saveas.done", name=saved[0].name))

    def import_dialog(self) -> None:
        found = paths.find_legacy_databases()
        start = str(found[0].parent) if found else str(paths.find_root() or Path.home())
        files, _ = QFileDialog.getOpenFileNames(self, t("data.file.import"), start, t("dlg.db_filter"))
        if files:
            self._import_files([Path(f) for f in files])

    def change_data_dir(self) -> None:
        store = self.store
        folder = QFileDialog.getExistingDirectory(self, t("dlg.choose_folder"), str(store.data_dir))
        if not folder:
            return
        count = len(list(store.data_dir.glob("*.db"))) if store.data_dir.is_dir() else 0
        choice = ask3(self, t("data.location.copy_q", n=count), t("data.location.copy"),
                      t("data.location.no_copy")) if count else 2
        if choice == 0:
            return
        try:
            store.set_data_dir(Path(folder), copy_files=choice == 1)
            self.notify(t("data.location.changed"))
        except OSError:
            error(self, t("err.data_dir", path=paths.display_path(folder)))

    # ---- backups --------------------------------------------------------------------------------------------------
    def backup_now(self) -> None:
        if self.guard(self.store.make_backup):
            self.notify(t("data.backup.done"))
            self.refresh()

    def restore_backup(self, path: Path) -> None:
        from . import backup as backup_mod
        parsed = backup_mod.parse_name(Path(path))
        when = fmt_datetime(parsed[0]) if parsed else Path(path).name
        if ask(self, t("data.backup.restore_q", when=when), danger=True):
            if self.guard(lambda: self.store.restore_backup(Path(path))):
                self.notify(t("data.backup.restored", when=when))

    # ---- month-end close ------------------------------------------------------------------------------------------
    def start_close(self) -> None:
        due = self.store.due_close_periods()
        if not due:
            return
        dlg = MonthCloseDialog(self, self.store, due[0], due[-1])
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if dlg.skip_mode:
            if self.guard(lambda: self.store.skip_close(due[-1])):
                self.notify(t("close.done", period=fmt_period(due[-1])))
            return
        if not self.guard(lambda: self.store.close_month(dlg.result_plan)):
            return
        self.notify(t("close.done", period=fmt_period(due[0])))
        remaining = self.store.due_close_periods()
        if remaining and ask(self, t("close.more_q", period=fmt_period(remaining[0]))):
            QTimer.singleShot(0, self.start_close)
        elif not remaining:
            QTimer.singleShot(0, self.maybe_prompt_debits)

    def undo_close(self) -> None:
        last = self.store.latest_close()
        if not last:
            return
        period = Period.try_parse(last["period"])
        if not ask(self, t("data.close.undo_q", period=fmt_period(period)), danger=True):
            return
        result: list = []
        if self.guard(lambda: result.append(self.store.undo_last_close())):
            if result and result[0]:
                self.notify(t("data.close.undone", period=fmt_period(period)))
            else:
                error(self, t("data.close.undo_missing"))

    # ---- debts ------------------------------------------------------------------------------------------------------
    def _need_db(self) -> bool:
        if not self.store.has_db:
            self.notify(t("err.no_db"))
            return False
        return True

    def add_bill(self) -> None:
        if not self._need_db():
            return
        dlg = BillDialog(self, None, self.store.state().current, self.store.currency, today=self.store.today())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.guard(lambda: self.store.add_bill(dlg.result_bill()))

    def edit_bill(self, bill) -> None:
        st = self.store.state()
        paid_now = st.paid_bills.get(bill.id)
        dlg = BillDialog(self, bill, st.current, self.store.currency, today=self.store.today(),
                         paid=bool(paid_now and paid_now.paid))
        result = dlg.exec()
        if result == DELETE:
            self.delete_bill(bill)
            return
        if result != QDialog.DialogCode.Accepted:
            return
        new = dlg.result_bill()
        settle = dlg.settle()
        if settle is not None:
            # 4.1.2: this month's payment went out as it was; the edit is for the next one
            due, amount = settle
            if self.guard(lambda: self.store.settle_and_update_bill(new, bill, due, amount)):
                self.notify(t("when.recorded", name=bill.label, date=fmt_md(due, weekday=False),
                              amount=money(amount, bill.currency)))
            return
        if dlg.from_next:  # nothing was due this month: the edit starts with the next payment
            self.guard(lambda: self.store.update_bill(new))
            return
        old_balance = bill.amount
        drop = old_balance - new.amount
        if new.currency == bill.currency and drop >= unit(bill.currency):
            # B2: a lower balance usually means a payment went out; record it as one so the
            # month is not shown as unpaid and nothing is subtracted twice later.
            choice = ask3(self, t("bill.balance_drop_q", drop=money(drop, bill.currency),
                                  old=money(old_balance, bill.currency), new=money(new.amount, bill.currency)),
                          t("bill.balance_drop_pay"), t("bill.balance_drop_fix"))
            if choice == 0:
                return
            if choice == 1:
                paid = st.paid_bills.get(bill.id)
                pay = PaymentDialog(self, bill, st.current, self.store.today(), bool(paid and paid.paid),
                                    new_balance=new.amount)
                if pay.exec() != QDialog.DialogCode.Accepted:
                    return
                d, amount, _interest, note = pay.values()
                self.guard(lambda: self.store.update_bill_with_payment(new, old_balance, d, amount, note))
                return
        self.guard(lambda: self.store.update_bill(new))

    def delete_bill(self, bill) -> None:
        if ask(self, t("debts.confirm_delete", name=bill.label), t("common.delete"), danger=True):
            self.guard(lambda: self.store.delete_bill(bill.id))

    def record_payment(self, bill) -> None:
        st = self.store.state()
        paid = st.paid_bills.get(bill.id)
        dlg = PaymentDialog(self, bill, st.current, self.store.today(), bool(paid and paid.paid))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            d, amount, interest, note = dlg.values()
            self.guard(lambda: self.store.record_bill_payment(bill.id, d, amount, interest, note))
        else:
            self.refresh()  # put a ticked box back

    def toggle_paid(self, kind: str, target_id: int, checked: bool, name: str, paid_amount: float) -> None:
        st = self.store.state()
        if kind == "bill":
            bill = next((b for b in st.bills if b.id == target_id), None)
            if bill is None:
                return
            if checked:
                self.record_payment(bill)
            elif ask(self, t("pay.undo_q", name=bill.label, amount=money(paid_amount, bill.currency)),
                     t("pay.undo")):
                self.guard(lambda: self.store.undo_payment("bill", bill.id))
            else:
                self.refresh()
        elif kind == "living":
            lc = next((x for x in st.living if x.id == target_id), None)
            if lc is None:
                return
            if checked:
                self.guard(lambda: self.store.record_living_payment(lc))
            else:
                self.guard(lambda: self.store.undo_payment("living", lc.id))
        elif kind == "fee":
            card = next((c for c in st.cards if c.id == target_id), None)
            if card is None:
                return
            if checked:
                self.guard(lambda: self.store.set_fee_paid(card.id, True))
            elif ask(self, t("cards.fee_undo_q", name=card.label)):
                self.guard(lambda: self.store.set_fee_paid(card.id, False))
            else:
                self.refresh()
        elif kind == "contrib":
            h = next((x for x in st.holdings if x.id == target_id), None)
            if h is None:
                return
            if checked:
                due = engine.due_date(st.current, h.contrib_day)
                when = due if due <= self.store.today() else self.store.today()
                result: list = []
                if self.guard(lambda: result.append(self.store.record_contribution(h, when))):
                    buy = result[0]
                    if h.kind != "manual" and buy.quantity <= 0:
                        self.refresh()                    # nothing was written: the tick goes back
                        if buy.price > 0:
                            info(self, t("invest.contrib_too_small", name=h.label,
                                         price=money(buy.price, h.currency)))
                        else:
                            info(self, t("invest.contrib_no_price"))
                    else:
                        self.notify(t("invest.contrib_done", name=h.label))
            else:
                self.guard(lambda: self.store.undo_contribution(h.id))

    # ---- living costs and cards -----------------------------------------------------------------------------
    def add_living(self) -> None:
        if not self._need_db():
            return
        dlg = LivingDialog(self, None, self.store.currency, today=self.store.today())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.guard(lambda: self.store.add_living(dlg.result_living()))

    def edit_living(self, lc) -> None:
        paid_now = self.store.state().paid_living.get(lc.id)
        dlg = LivingDialog(self, lc, self.store.currency, today=self.store.today(),
                           paid=bool(paid_now and paid_now.paid))
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            new = dlg.result_living()
            settle = dlg.settle()
            if settle is None:
                self.guard(lambda: self.store.update_living(new))
                return
            due, amount = settle
            if self.guard(lambda: self.store.settle_and_update_living(new, lc, due, amount)):
                self.notify(t("when.recorded", name=lc.label, date=fmt_md(due, weekday=False),
                              amount=money(amount, lc.currency)))
        elif result == DELETE:
            self.delete_living(lc)

    def delete_living(self, lc) -> None:
        if ask(self, t("living.confirm_delete", name=lc.label), t("common.delete"), danger=True):
            self.guard(lambda: self.store.delete_living(lc.id))

    def add_card(self) -> None:
        if not self._need_db():
            return
        dlg = CardDialog(self, None, self.store.currency, self.store.today())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.guard(lambda: self.store.add_card(dlg.result_card()))

    def toggle_fee(self, card) -> None:
        """B1: mark the card's annual fee paid for the current cycle, or back to unpaid."""
        status = engine.fee_status(card, self.store.today())
        if status.state == "free":
            self.notify(t("cards.fee_free"))
        elif status.state == "paid":
            if ask(self, t("cards.fee_undo_q", name=card.label)):
                self.guard(lambda: self.store.set_fee_paid(card.id, False))
        elif self.guard(lambda: self.store.set_fee_paid(card.id, True)):
            self.notify(t("cards.fee_marked", name=card.label))

    def edit_card(self, card) -> None:
        dlg = CardDialog(self, card, self.store.currency, self.store.today())
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            self.guard(lambda: self.store.update_card(dlg.result_card()))
        elif result == DELETE:
            self.delete_card(card)

    def delete_card(self, card) -> None:
        if ask(self, t("cards.confirm_delete", name=card.label), t("common.delete"), danger=True):
            self.guard(lambda: self.store.delete_card(card.id))

    # ---- investments ----------------------------------------------------------------------------------------------
    def add_holding(self) -> None:
        if not self._need_db():
            return
        dlg = HoldingDialog(self, self.store, None, self.store.currency)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            if self.guard(lambda: self.store.add_holding(dlg.result_holding())):
                self.store.refresh_market(force=True, quiet=True)

    def edit_holding(self, h) -> None:
        dlg = HoldingDialog(self, self.store, h, self.store.currency)
        result = dlg.exec()
        if result == QDialog.DialogCode.Accepted:
            new = dlg.result_holding()
            if self.guard(lambda: self.store.update_holding(new)) and invest.quote_ref(new) != invest.quote_ref(h):
                self.store.refresh_market(force=True, quiet=True)
        elif result == DELETE:
            self.delete_holding(h)

    def delete_holding(self, h) -> None:
        if ask(self, t("invest.confirm_delete", name=h.label), t("common.delete"), danger=True):
            self.guard(lambda: self.store.delete_holding(h.id))

    def record_trade(self, h) -> None:
        st = self.store.state()
        hv = invest.value_holding(h, st.prices, self.store.rates, h.currency)
        dlg = TradeDialog(self, h, self.store.today(), hv.unit_price)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            kind, when = v.pop("kind"), v.pop("trade_date")
            self.guard(lambda: self.store.record_trade(h.id, kind, when, **v))

    def undo_trade(self, h) -> None:
        last = self.store.repo.last_trade(h.id) if self.store.repo else None
        if last is None:
            self.notify(t("invest.undo_none"))
            return
        key = f"trade.m.{last.kind}" if h.kind == "manual" and last.kind in ("buy", "sell") else f"trade.{last.kind}"
        if ask(self, t("invest.undo_q", name=h.label, when=fmt_date(last.trade_date), kind=t(key),
                       amount=money(last.amount, last.currency)), t("pay.undo")):
            self.guard(lambda: self.store.undo_last_trade(h.id))

    def invest_settings(self) -> None:
        if not self._need_db():
            return
        cfg = self.store.cfg
        dlg = InvestSettingsDialog(self, self.store.returns(), cfg.auto_refresh_prices, cfg.coingecko_key)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            returns, auto, key = dlg.values()
            cfg.auto_refresh_prices, cfg.coingecko_key = auto, key
            self.store.save_config()
            if self.guard(lambda: self.store.save_returns(returns)):
                self.notify(t("iset.saved"))

    # ---- display ------------------------------------------------------------------------------------------------
    def choose_columns(self) -> None:
        cfg = self.store.cfg
        hidden = {k: sorted(cfg.hidden(k)) for k in TABLE_COLUMNS}
        dlg = ColumnsDialog(self, hidden)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg.hidden_columns = dlg.result_hidden()
            self.store.save_config()
            self.refresh()

    def set_theme(self, code: str) -> None:
        if code == self.store.cfg.theme:
            return
        self.store.cfg.theme = code
        self.store.save_config()
        theme.apply(QApplication.instance(), code)
        self._build()

    def set_language(self, code: str) -> None:
        if code == self.store.cfg.language:
            return
        self.store.cfg.language = code
        self.store.save_config()
        i18n.set_language(code)
        self._build()

    def _system_theme_changed(self, *_args) -> None:
        if self.store.cfg.theme == "system":
            theme.apply(QApplication.instance(), "system")
            self._build()

    def closeEvent(self, event) -> None:
        if not self.isMaximized():
            self.store.cfg.window = {"w": self.width(), "h": self.height(), "x": self.x(), "y": self.y()}
        self.store.save_config()
        self.store.wait_for_rates(1500)
        super().closeEvent(event)

"""Month-end close (F2): confirm last month's payments, add interest to unpaid debts,
carry savings over. Nothing changes until the user presses "Close month"; a backup is
taken first and the close can be undone from Data & settings."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QFormLayout, QHBoxLayout,
                             QHeaderView, QRadioButton, QStackedWidget, QTableWidget, QVBoxLayout, QWidget)

from . import engine, invest, theme
from .i18n import bill_type_label, category_label, fmt_period, label_of, money, t
from .money import convert, round_money
from .periods import Period
from .repo import ClosePlan, ContribBuy
from .store import Store
from .widgets import RIGHT, MoneySpin, button, check_item, divider, item, label


class MonthCloseDialog(QDialog):
    def __init__(self, parent: QWidget | None, store: Store, period: Period, until: Period):
        super().__init__(parent)
        self.store = store
        self.period = period
        self.until = until
        self.setWindowTitle(t("close.title", period=fmt_period(period)))
        self.setMinimumSize(860, 600)
        repo = store.repo
        state = store.state()
        self.profile = state.profile
        self.rates = store.rates
        self.holdings = {h.id: h for h in state.holdings}
        self.prices = state.prices
        self.trades = repo.trades(period=period)
        self.items = engine.close_items(state.bills, state.living, period, repo.payments(period), state.cards,
                                        state.holdings, self.trades)
        self.skip_mode = False
        self.result_plan: ClosePlan | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(12)
        outer.addWidget(label(t("close.title", period=fmt_period(period)), "DialogTitle"))
        self.steps = label("", "Muted")
        outer.addWidget(self.steps)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)
        self.stack.addWidget(self._page_items())
        self.stack.addWidget(self._page_savings())
        self.stack.addWidget(self._page_confirm())

        row = QHBoxLayout()
        row.addWidget(button(t("common.cancel"), slot=self.reject))
        row.addStretch(1)
        self.back_btn = button(t("common.back"), slot=self._back)
        self.next_btn = button(t("common.next"), "primary", slot=self._next)
        row.addWidget(self.back_btn)
        row.addWidget(self.next_btn)
        outer.addLayout(row)
        self._go(0)

    # ---- page 1: items --------------------------------------------------------------------------------
    def _page_items(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.mode_record = QRadioButton(t("close.mode.record"))
        self.mode_skip = QRadioButton(t("close.mode.skip", until=fmt_period(self.until)))
        group = QButtonGroup(page)
        group.addButton(self.mode_record)
        group.addButton(self.mode_skip)
        self.mode_record.setChecked(True)
        lay.addWidget(self.mode_record)
        lay.addWidget(label(t("close.mode.record_hint"), "Hint", wrap=True))
        lay.addWidget(self.mode_skip)
        lay.addWidget(label(t("close.mode.skip_hint"), "Hint", wrap=True))
        lay.addWidget(divider())
        self.items_hint = label(t("close.items.hint"), "Hint", wrap=True)
        lay.addWidget(self.items_hint)

        headers = ["", t("close.col.item"), t("close.col.kind"), t("close.col.planned"), t("close.col.amount"),
                   t("close.col.note")]
        tbl = QTableWidget(len(self.items), len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.verticalHeader().setVisible(False)
        tbl.verticalHeader().setDefaultSectionSize(38)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setShowGrid(False)
        tbl.setAlternatingRowColors(True)
        head = tbl.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setStretchLastSection(True)
        tbl.setColumnWidth(0, 36)
        tbl.setColumnWidth(1, 210)
        tbl.setColumnWidth(2, 150)
        tbl.setColumnWidth(3, 120)
        tbl.setColumnWidth(4, 150)
        self.spins: dict[int, MoneySpin] = {}
        tbl.blockSignals(True)
        for r, it in enumerate(self.items):
            kind = self._kind_text(it)
            if it.is_recorded:
                tbl.setItem(r, 0, check_item(True, r, enabled=False))
                tbl.setItem(r, 4, item(money(it.recorded.amount, it.currency), RIGHT))
                tbl.setItem(r, 5, item(t("close.recorded"), tone="good"))
            elif it.kind == "fee":  # the fee is on the card bill: only paid or not
                tbl.setItem(r, 0, check_item(True, r))
                tbl.setItem(r, 4, item(money(it.planned, it.currency), RIGHT))
                tbl.setItem(r, 5, item(""))
            else:
                default_pay = it.planned > 0
                tbl.setItem(r, 0, check_item(default_pay, r))
                spin = MoneySpin(it.currency)
                spin.setValue(it.planned)
                spin.setMinimumWidth(120)
                spin.valueChanged.connect(self._refresh_notes)
                self.spins[r] = spin
                tbl.setCellWidget(r, 4, spin)
                tbl.setItem(r, 5, item(""))
            tbl.setItem(r, 1, item(it.name))
            tbl.setItem(r, 2, item(kind, tone="text_muted"))
            tbl.setItem(r, 3, item(money(it.planned, it.currency), RIGHT, tone="text_muted"))
        tbl.blockSignals(False)
        tbl.itemChanged.connect(lambda _i: self._refresh_notes())
        self.table = tbl
        lay.addWidget(tbl, 1)
        self.mode_record.toggled.connect(self._mode_changed)
        self._refresh_notes()
        return page

    @staticmethod
    def _kind_text(it: engine.CloseItem) -> str:
        if it.kind == "bill":
            return bill_type_label(it.sub)
        if it.kind == "fee":
            return t("close.kind.fee")
        if it.kind == "contrib":
            return t("close.kind.contrib", kind=label_of("kind", it.sub))
        return category_label(it.sub)

    def _unit_price(self, holding_id: int) -> float | None:
        h = self.holdings.get(holding_id)
        if h is None or h.kind == "manual":
            return None
        return invest.value_holding(h, self.prices, self.rates, h.currency).unit_price

    def _units(self, h, amount: float) -> float:
        """Units a contribution of `amount` (in its own currency) buys at the latest price."""
        price = self._unit_price(h.id) or 0.0
        value = round_money(convert(amount, h.contrib_currency, h.currency, self.rates), h.currency)
        return invest.units_for(h.kind, value, price)

    def _checked(self, row: int) -> bool:
        it = self.table.item(row, 0)
        return bool(it and it.checkState() == Qt.CheckState.Checked)

    def _refresh_notes(self) -> None:
        self.table.blockSignals(True)
        for r, it in enumerate(self.items):
            if it.is_recorded:
                continue
            spin = self.spins.get(r)
            if spin is not None:
                spin.setEnabled(self._checked(r))
            note = self.table.item(r, 5)
            if it.kind == "fee":
                text, tone = (t("close.fee_card"), "text_muted") if self._checked(r) else (t("common.unpaid"),
                                                                                          "text_muted")
            elif it.kind == "contrib" and self._checked(r):
                h = self.holdings.get(it.target_id)
                if it.is_card:
                    text, tone = t("close.contrib_card"), "text_muted"
                elif h is not None and h.kind != "manual" and not self._unit_price(it.target_id):
                    text, tone = t("close.no_price"), "warning"
                elif h is not None and h.kind != "manual" and spin is not None and not self._units(h, spin.value()):
                    text, tone = t("close.too_small"), "warning"
                else:
                    text, tone = "", None
            elif self._checked(r):
                text, tone = "", None
            elif it.kind == "bill" and it.interest_if_unpaid > 0:
                text, tone = t("close.accrue", interest=money(it.interest_if_unpaid, it.currency)), "warning"
            elif it.kind == "bill":
                text, tone = t("close.carry"), "text_muted"
            elif it.is_card:
                text, tone = t("close.card_living"), "text_muted"
            else:
                text, tone = t("common.unpaid"), "text_muted"
            note.setText(text)
            note.setForeground(QColor(getattr(theme.current(), tone or "text")))
        self.table.blockSignals(False)

    def _mode_changed(self) -> None:
        record = self.mode_record.isChecked()
        self.table.setEnabled(record)
        self.items_hint.setEnabled(record)
        self._go(0)

    # ---- page 2: savings ------------------------------------------------------------------------------------
    def _page_savings(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        lay.addWidget(label(t("close.savings.title", period=fmt_period(self.period)), "SectionTitle"))
        form = QFormLayout()
        form.setHorizontalSpacing(24)
        form.setVerticalSpacing(8)
        self.s_start = label("", None)
        self.s_income = label("", None)
        self.s_out = label("", None)
        self.s_calc = label("", None)
        for w in (self.s_start, self.s_income, self.s_out, self.s_calc):
            w.setAlignment(RIGHT)
            w.setMinimumWidth(180)
        form.addRow(t("close.savings.start"), self.s_start)
        form.addRow(t("close.savings.income"), self.s_income)
        form.addRow(t("close.savings.out"), self.s_out)
        form.addRow(divider())
        form.addRow(t("close.savings.calc"), self.s_calc)
        lay.addLayout(form)
        lay.addWidget(divider())
        cur = self.profile.cumulative_savings_currency
        self.s_actual = MoneySpin(cur, allow_negative=True)
        self.s_actual.setMaximumWidth(220)
        row = QHBoxLayout()
        row.addWidget(label(t("close.savings.actual"), "SectionTitle"))
        row.addWidget(self.s_actual)
        row.addWidget(label(cur, "Muted"))
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(label(t("close.savings.actual_hint"), "Hint", wrap=True))
        self.reset_other = QCheckBox(t("close.savings.reset_other", what=self.profile.other_income_type or "—",
                                       amount=money(self.profile.other_income, self.profile.other_income_currency))
                                     .replace("&", "&&"))
        self.reset_other.setChecked(True)
        self.reset_other.setVisible(self.profile.other_income > 0)
        lay.addWidget(self.reset_other)
        lay.addStretch(1)
        self._savings_touched = False
        self.s_actual.valueChanged.connect(lambda _v: setattr(self, "_savings_touched", True))
        return page

    def _choices(self) -> list[engine.CloseChoice]:
        out = []
        for r, it in enumerate(self.items):
            if it.is_recorded:
                out.append(engine.CloseChoice(it, True, it.recorded.amount, it.due))
            else:
                spin = self.spins.get(r)
                out.append(engine.CloseChoice(it, self._checked(r), spin.value() if spin else 0.0, it.due))
        return out

    def _fill_savings(self) -> None:
        start, income, outflow, suggested = engine.close_savings(self.profile, self._choices(), self.rates,
                                                                 self.trades, list(self.holdings.values()))
        cur = self.profile.cumulative_savings_currency
        self.s_start.setText(money(start, cur))
        self.s_income.setText(money(income, cur))
        self.s_out.setText(money(outflow, cur))
        self.s_calc.setText(money(suggested, cur))
        if not self._savings_touched:
            self.s_actual.blockSignals(True)
            self.s_actual.setValue(suggested)
            self.s_actual.blockSignals(False)

    # ---- page 3: confirm ----------------------------------------------------------------------------------------
    def _page_confirm(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.summary = label("", None, wrap=True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.summary)
        lay.addWidget(divider())
        note = label(t("close.confirm.backup"), "Hint", wrap=True)
        lay.addWidget(note)
        lay.addStretch(1)
        return page

    def _plan(self) -> ClosePlan:
        plan = ClosePlan(self.period)
        for ch in self._choices():
            it = ch.item
            if it.is_recorded:
                continue
            if it.kind == "bill":
                if ch.pay and ch.amount > 0:
                    plan.bill_payments.append((it.target_id, ch.amount, it.due))
                elif not ch.pay and it.interest_if_unpaid > 0:
                    plan.accrue_bill_ids.append(it.target_id)
            elif it.kind == "fee":
                if ch.pay:
                    plan.fee_paid_card_ids.append(it.target_id)
            elif it.kind == "contrib":
                h = self.holdings.get(it.target_id)
                if ch.pay and ch.amount > 0 and h is not None:
                    amount = round_money(convert(ch.amount, h.contrib_currency, h.currency, self.rates), h.currency)
                    price = self._unit_price(h.id) or 0.0
                    qty = invest.units_for(h.kind, amount, price)
                    if h.kind == "manual" or qty > 0:   # without a price the units are unknown: not written
                        plan.contrib_buys.append(ContribBuy(h.id, amount, qty, price, it.due,
                                                            h.contrib_method == "bank"))
            elif ch.pay and ch.amount > 0:
                plan.living_payments.append((it.target_id, ch.amount, it.due))
        plan.savings_after = self.s_actual.value()
        plan.reset_other_income = self.reset_other.isChecked() and self.profile.other_income > 0
        return plan

    def _fill_confirm(self) -> None:
        target = self.store.currency
        if self.mode_skip.isChecked():
            n = self.period.months_until(self.until) + 1
            self.summary.setText(t("close.confirm.skip", first=fmt_period(self.period),
                                   until=fmt_period(self.until), n=n))
            return
        plan = self._plan()
        by_id = {(it.kind, it.target_id): it for it in self.items}
        pay_total = sum(convert(a, by_id[("bill", i)].currency, target, self.rates) for i, a, _d in plan.bill_payments)
        acc_total = sum(convert(by_id[("bill", i)].interest_if_unpaid, by_id[("bill", i)].currency, target,
                                self.rates) for i in plan.accrue_bill_ids)
        cur = self.profile.cumulative_savings_currency
        lines = [
            t("close.confirm.payments", n=len(plan.bill_payments), amount=money(pay_total, target)),
            t("close.confirm.accruals", n=len(plan.accrue_bill_ids), amount=money(acc_total, target)),
            t("close.confirm.living", n=len(plan.living_payments)),
        ]
        if plan.fee_paid_card_ids:
            lines.append(t("close.confirm.fees", n=len(plan.fee_paid_card_ids)))
        if plan.contrib_buys:
            total = sum(convert(b.amount, self.holdings[b.holding_id].currency, target, self.rates)
                        for b in plan.contrib_buys)
            lines.append(t("close.confirm.contribs", n=len(plan.contrib_buys), amount=money(total, target)))
        lines += [
            t("close.confirm.savings", before=money(self.profile.cumulative_savings, cur),
              after=money(plan.savings_after, cur)),
        ]
        self.summary.setText("\n\n".join(lines))

    # ---- navigation -----------------------------------------------------------------------------------------------
    def _go(self, index: int) -> None:
        skip = self.mode_skip.isChecked()
        if skip and index == 1:
            index = 2
        self.stack.setCurrentIndex(index)
        if index == 1:
            self._fill_savings()
        if index == 2:
            self._fill_confirm()
        names = [t("close.step1"), t("close.step2"), t("close.step3")]
        accent = theme.current().accent
        parts = []
        for i, n in enumerate(names):
            if skip and i == 1:
                continue
            text = f"{len(parts) + 1}. {n}"
            parts.append(f'<b style="color:{accent}">{text}</b>' if i == index else text)
        self.steps.setText("&nbsp;&nbsp;›&nbsp;&nbsp;".join(parts))
        self.back_btn.setVisible(index > 0)
        self.next_btn.setText(t("close.do") if index == 2 else t("common.next"))

    def _back(self) -> None:
        i = self.stack.currentIndex()
        self._go(0 if (i == 2 and self.mode_skip.isChecked()) else max(0, i - 1))

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i < 2:
            self._go(i + 1)
            return
        self.skip_mode = self.mode_skip.isChecked()
        self.result_plan = None if self.skip_mode else self._plan()
        self.accept()

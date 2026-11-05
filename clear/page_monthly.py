"""Monthly: income & savings (top) and the living-cost list with a paid tick (R6)."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QLineEdit, QVBoxLayout

from .dialogs import DEFAULT_WIDTHS, TABLE_COLUMNS
from .i18n import category_label, due_text, fmt_date, method_label, money, t
from .money import convert, fmt_number
from .shell import Page
from .widgets import (CENTER, RIGHT, Card, CurrencyCombo, DataTable, DayCombo, MoneySpin, button, check_item,
                      item, label, set_tone)

PAID_COL = 7


class MonthlyPage(Page):
    key = "monthly"
    title_key = "nav.monthly"
    icon_name = "fa5s.calendar-check"
    scrollable = False

    def __init__(self, store, window):
        super().__init__(store, window)

        # -- income & savings
        card = Card(t("monthly.income.title"), t("monthly.income.sub"))
        self.save_btn = button(t("common.save"), "primary", "fa5s.save", self._save)
        self.status = label("", "Hint")
        card.actions.addWidget(self.status)
        card.actions.addWidget(self.save_btn)
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(6)
        for col in range(3):
            grid.setColumnStretch(col, 1)

        def money_field(allow_negative: bool = False):
            spin = MoneySpin(allow_negative=allow_negative)
            combo = CurrencyCombo()
            box = QHBoxLayout()
            box.setSpacing(8)
            box.addWidget(spin, 1)
            box.addWidget(combo)
            combo.currentTextChanged.connect(spin.set_currency)
            spin.valueChanged.connect(self._dirty)
            combo.currentTextChanged.connect(self._dirty)
            return spin, combo, box

        def place(row: int, col: int, title: str, field, hint: str = "") -> None:
            grid.addWidget(label(title, "SectionTitle"), row * 3, col)
            if isinstance(field, QHBoxLayout) or isinstance(field, QVBoxLayout):
                grid.addLayout(field, row * 3 + 1, col)
            else:
                grid.addWidget(field, row * 3 + 1, col)
            grid.addWidget(label(hint, "Hint", wrap=True), row * 3 + 2, col)

        self.savings, self.savings_cur, box = money_field(True)
        place(0, 0, t("monthly.f.savings"), box, t("monthly.f.savings_hint"))
        self.income, self.income_cur, box = money_field()
        place(0, 1, t("monthly.f.income"), box)
        self.other, self.other_cur, box = money_field()
        self.other_type = QLineEdit()
        self.other_type.setPlaceholderText(t("monthly.f.other_type"))
        self.other_type.setMaximumWidth(150)
        self.other_type.textChanged.connect(self._dirty)
        box.insertWidget(0, self.other_type)
        place(0, 2, t("monthly.f.other"), box)
        self.expected, self.expected_cur, box = money_field()
        place(1, 0, t("monthly.f.expected"), box)
        self.extra, self.extra_cur, box = money_field()
        place(1, 1, t("monthly.f.extra"), box)
        self.payday = DayCombo()
        self.payday.currentIndexChanged.connect(self._dirty)
        day_box = QHBoxLayout()
        day_box.addWidget(self.payday)
        day_box.addStretch(1)
        place(1, 2, t("monthly.f.payday"), day_box)
        card.body.addLayout(grid)
        self.body.addWidget(card)

        # -- living costs
        lc_card = Card(t("monthly.living.title"), t("monthly.living.sub"))
        lc_card.actions.addWidget(button(t("monthly.add_living"), "primary", "fa5s.plus", window.add_living))
        lc_card.actions.addWidget(button(t("common.edit"), None, "fa5s.pen", self._edit))
        lc_card.actions.addWidget(button(t("common.delete"), "danger", "fa5s.trash-alt", self._delete))
        self.table = DataTable("living", [t(k) for k in TABLE_COLUMNS["living"]])
        self.table.right_align((3,))
        self.table.itemDoubleClicked.connect(lambda it: self._edit() if it.column() != PAID_COL else None)
        self.table.itemChanged.connect(self._ticked)
        self.table.widthsChanged.connect(window.save_widths)
        lc_card.body.addWidget(self.table, 1)
        self.footer = label("", "Muted", wrap=True)
        lc_card.body.addWidget(self.footer)
        self.body.addWidget(lc_card, 1)
        self._loading = False
        self._ids: list[int] = []

    # ---- refresh ------------------------------------------------------------------------------------------
    def refresh(self) -> None:
        st = self.store.state()
        p = st.profile
        self._loading = True
        for spin, combo, value, cur in (
                (self.savings, self.savings_cur, p.cumulative_savings, p.cumulative_savings_currency),
                (self.income, self.income_cur, p.monthly_income, p.monthly_income_currency),
                (self.other, self.other_cur, p.other_income, p.other_income_currency),
                (self.expected, self.expected_cur, p.expected_income, p.expected_income_currency),
                (self.extra, self.extra_cur, p.extra_income, p.extra_income_currency)):
            combo.setCurrentText(cur)
            spin.set_currency(cur)
            spin.setValue(value)
        self.other_type.setText(p.other_income_type)
        self.payday.setValue(p.payday)
        self._loading = False
        self.status.setText("")
        set_tone(self.status, None)
        self.save_btn.setEnabled(self.store.has_db)

        cfg = self.store.cfg
        self.table.apply_layout(cfg.hidden("living"), cfg.column_widths.get("living"), DEFAULT_WIDTHS["living"])
        target, rates = self.store.currency, self.store.rates
        tbl = self.table
        tbl.blockSignals(True)
        try:
            tbl.setRowCount(len(st.living))
            self._ids = [lc.id for lc in st.living]
            cash = card = 0.0
            for r, lc in enumerate(st.living):
                v = convert(lc.amount, lc.currency, target, rates)
                if lc.is_card:
                    card += v
                else:
                    cash += v
                paid = st.paid_living.get(lc.id)
                due = st.current.day(lc.monthly_due_day)
                days = (due - st.today).days
                tbl.setItem(r, 0, item(category_label(lc.category), data=lc.id, tone="text_muted"))
                tbl.setItem(r, 1, item(lc.name, data=lc.id, bold=True))
                tbl.setItem(r, 2, item(lc.description, tone="text_muted"))
                tbl.setItem(r, 3, item(fmt_number(lc.amount, lc.currency), RIGHT))
                tbl.setItem(r, 4, item(lc.currency, CENTER, tone="text_muted"))
                tbl.setItem(r, 5, item(method_label(lc.payment_method)))
                if paid and paid.paid:
                    tbl.setItem(r, 6, item(t("due.cell_day", day=lc.monthly_due_day), tone="text_muted"))
                else:
                    tone = "critical" if days < 0 and not lc.is_card else "warning" if 0 <= days <= 3 else None
                    tbl.setItem(r, 6, item(t("due.cell", day=lc.monthly_due_day, rel=due_text(days)), tone=tone))
                tbl.setItem(r, PAID_COL, check_item(bool(paid and paid.paid), r, enabled=self.store.has_db))
                tbl.setItem(r, 8, item(fmt_date(lc.created_date), tone="text_muted"))
                tbl.setItem(r, 9, item(fmt_date(lc.last_updated), tone="text_muted"))
        finally:
            tbl.blockSignals(False)
        self.footer.setText(t("living.footer", cur=target, total=money(cash + card, target),
                              cash=money(cash, target), card=money(card, target)))

    def _dirty(self, *_args) -> None:
        if not self._loading:
            self.status.setText(t("monthly.unsaved"))
            set_tone(self.status, "warning")

    def _save(self) -> None:
        p = self.store.state().profile.copy()
        p.cumulative_savings, p.cumulative_savings_currency = self.savings.value(), self.savings_cur.currentText()
        p.monthly_income, p.monthly_income_currency = self.income.value(), self.income_cur.currentText()
        p.other_income, p.other_income_currency = self.other.value(), self.other_cur.currentText()
        p.other_income_type = self.other_type.text().strip()
        p.expected_income, p.expected_income_currency = self.expected.value(), self.expected_cur.currentText()
        p.extra_income, p.extra_income_currency = self.extra.value(), self.extra_cur.currentText()
        p.payday = self.payday.value()
        if self.win.guard(lambda: self.store.save_profile(p)):
            self.status.setText(t("monthly.saved"))
            set_tone(self.status, "good")

    def _selected(self):
        lc_id = self.table.selected_data(1)
        return next((x for x in self.store.state().living if x.id == lc_id), None)

    def _edit(self) -> None:
        lc = self._selected()
        if lc is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.edit_living(lc)

    def _delete(self) -> None:
        lc = self._selected()
        if lc is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.delete_living(lc)

    def _ticked(self, cell) -> None:
        if cell.column() != PAID_COL:
            return
        row = cell.data(Qt.ItemDataRole.UserRole)
        if row is None or row >= len(self._ids):
            return
        lc_id = self._ids[row]
        checked = cell.checkState() == Qt.CheckState.Checked
        QTimer.singleShot(0, lambda: self.win.toggle_paid("living", lc_id, checked, "", 0.0))

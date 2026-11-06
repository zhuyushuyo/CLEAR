"""Plan: month-by-month cash-flow outlook in the display currency (R5: the currency is shown)."""

from __future__ import annotations

from PyQt6.QtWidgets import QComboBox, QHeaderView

from . import engine
from .dialogs import TABLE_COLUMNS
from .i18n import fmt_period, money, t
from .money import convert, fmt_number
from .shell import Page
from .widgets import RIGHT, Card, DataTable, item, label


class PlanPage(Page):
    key = "plan"
    title_key = "nav.plan"
    icon_name = "fa5s.chart-line"
    scrollable = False

    def __init__(self, store, window):
        super().__init__(store, window)
        self.card = Card(t("plan.title"))
        self.months = QComboBox()
        for n in range(1, 25):
            self.months.addItem(t("plan.months_n", n=n), n)
        self.months.setFixedWidth(110)
        self.months.currentIndexChanged.connect(self._months_changed)
        self.card.actions.addWidget(label(t("plan.months"), "Muted"))
        self.card.actions.addWidget(self.months)
        self.table = DataTable("plan", [t(k) for k in TABLE_COLUMNS["plan"]])
        head = self.table.horizontalHeader()
        head.setMinimumSectionSize(104)
        head.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, self.table.columnCount()):
            self.table.horizontalHeaderItem(col).setTextAlignment(RIGHT)
        self.card.body.addWidget(self.table, 1)
        self.notes = label("", "Hint", wrap=True)
        self.card.body.addWidget(self.notes)
        self.body.addWidget(self.card, 1)

    def refresh(self) -> None:
        st = self.store.state()
        cur, rates = self.store.currency, self.store.rates
        n = st.profile.simulation_months
        self.months.blockSignals(True)
        self.months.setCurrentIndex(max(0, min(23, n - 1)))
        self.months.blockSignals(False)
        self.card.set_subtitle(t("plan.sub", cur=cur))
        hidden = set(self.store.cfg.hidden("plan"))
        if not st.holdings:  # no investments: the two investment columns would only show zeros
            hidden |= {4, 7}
        self.table.apply_layout(hidden, None)
        rows = engine.simulate(st, n, rates, cur) if self.store.has_db else []
        tbl = self.table
        tbl.setRowCount(len(rows))
        for r, row in enumerate(rows):
            month = t("plan.this_month", period=fmt_period(row.period)) if r == 0 else fmt_period(row.period)
            tbl.setItem(r, 0, item(month, bold=r == 0))
            tbl.setItem(r, 1, item(fmt_number(row.income, cur), RIGHT, tone="good" if row.income else None))
            tbl.setItem(r, 2, item(fmt_number(row.debt_payment, cur), RIGHT))
            tbl.setItem(r, 3, item(fmt_number(row.living, cur), RIGHT))
            tbl.setItem(r, 4, item(fmt_number(row.contrib, cur), RIGHT))
            tbl.setItem(r, 5, item(fmt_number(row.net, cur), RIGHT, tone="critical" if row.net < 0 else "good",
                                   bold=True))
            tbl.setItem(r, 6, item(fmt_number(row.savings, cur), RIGHT, tone="critical" if row.savings < 0 else None))
            tbl.setItem(r, 7, item(fmt_number(row.invest, cur), RIGHT))
            tbl.setItem(r, 8, item(fmt_number(row.debt, cur), RIGHT, tone="text_muted"))
            tbl.setItem(r, 9, item(fmt_number(row.net_worth, cur), RIGHT,
                                   tone="critical" if row.net_worth < 0 else "accent", bold=True))
        notes = [t("plan.note_card_living")]
        if st.holdings:
            r_ = {k: f"{float(v):g}" for k, v in st.returns.items()}
            notes.append(t("plan.note_invest", stock=r_.get("stock", "0"), crypto=r_.get("crypto", "0"),
                           metal=r_.get("metal", "0"), manual=r_.get("manual", "0")))
        if any(c.annual_fee > 0 and c.fee_month for c in st.cards):
            notes.append(t("plan.note_fees"))
        outside = sum(convert(c.used_amount, c.currency, cur, rates) for c in st.cards
                      if not c.managed_in_bills and c.used_amount > 0)
        if outside > 0:
            notes.append(t("plan.note_cards", amount=money(outside, cur)))
        self.notes.setText("  ".join(notes))

    def _months_changed(self) -> None:
        if not self.store.has_db:
            return
        p = self.store.state().profile.copy()
        p.simulation_months = int(self.months.currentData())
        self.win.guard(lambda: self.store.save_profile(p))

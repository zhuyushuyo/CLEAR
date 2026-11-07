"""Plan: month-by-month cash-flow outlook in the display currency (R5: the currency is shown)."""

from __future__ import annotations

from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import QComboBox, QHeaderView

from . import engine
from .dialogs import TABLE_COLUMNS
from .i18n import fmt_period, money, t
from .money import convert, fmt_number
from .shell import Page
from .widgets import RIGHT, Card, DataTable, item, label

CASH_NET, WORTH = 9, 10   # savings minus debt (without investments), net worth
CELL_PADDING = 8          # left and right padding of cells and headings in the style sheet (theme.py)


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
        head.setMinimumSectionSize(104)   # until the first refresh measures the texts
        head.setStretchLastSection(False)  # every column stretches: the last one gets no extra minimum
        head.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for col in range(1, self.table.columnCount()):
            self.table.horizontalHeaderItem(col).setTextAlignment(RIGHT)
        self.table.horizontalHeaderItem(CASH_NET).setToolTip(t("plan.col.cash_net_tip"))
        self.table.horizontalHeaderItem(WORTH).setToolTip(t("plan.col.worth_tip"))
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
        if not st.holdings:  # no investments: zeros, and savings minus debt would equal net worth
            hidden |= {4, 7, CASH_NET}
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
            tbl.setItem(r, CASH_NET, item(fmt_number(row.cash_net, cur), RIGHT,
                                          tone="critical" if row.cash_net < 0 else None))
            tbl.setItem(r, WORTH, item(fmt_number(row.net_worth, cur), RIGHT,
                                       tone="critical" if row.net_worth < 0 else "accent", bold=True))
        self._fit_columns()
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

    def _fit_columns(self) -> None:
        """The columns share the width equally, but none gets narrower than its widest text: the
        table scrolls sideways before a figure or a heading is cut off."""
        tbl = self.table
        head = tbl.horizontalHeader()
        head_font = QFont(tbl.font())   # as the style sheet draws headings: 12 px, semi-bold
        head_font.setPixelSize(12)
        head_font.setWeight(QFont.Weight.DemiBold)
        head_fm = QFontMetrics(head_font)
        pad = 2 * CELL_PADDING + 4
        need = 0
        for col in range(1, tbl.columnCount()):
            if tbl.isColumnHidden(col):
                continue
            need = max(need, head_fm.horizontalAdvance(tbl.horizontalHeaderItem(col).text()) + pad)
            for row in range(tbl.rowCount()):
                it = tbl.item(row, col)
                if it is not None:
                    need = max(need, QFontMetrics(it.font()).horizontalAdvance(it.text()) + pad)
        head.setMinimumSectionSize(max(72, need))

    def _months_changed(self) -> None:
        if not self.store.has_db:
            return
        p = self.store.state().profile.copy()
        p.simulation_months = int(self.months.currentData())
        self.win.guard(lambda: self.store.save_profile(p))

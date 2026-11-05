"""Home (U3): the four numbers that matter, this month's checklist, warnings and the outlook."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QVBoxLayout,
                             QWidget)

from . import engine, theme
from .chart import BreakdownBars, TrendChart
from .i18n import bill_type_label, category_label, due_text, fmt_md, fmt_period, money, t
from .shell import Page
from .widgets import RIGHT, Card, KpiCard, check_item, icon, item, label

ALERT_ICONS = {"critical": ("fa5s.exclamation-circle", "critical"),
               "warning": ("fa5s.exclamation-triangle", "warning"),
               "info": ("fa5s.info-circle", "accent")}


def alert_text(a: engine.Alert) -> str:
    p = dict(a.params)
    cur = p.pop("currency", "JPY")
    for k in ("amount", "interest", "payment"):
        if k in p:
            p[k] = money(p[k], cur)
    if "period" in p:
        p["period"] = fmt_period(p["period"])
    if a.code == "due_soon" and p.get("days") == 0:
        return t("alert.due_today", **p)
    return t(f"alert.{a.code}", **p)


class HomePage(Page):
    key = "home"
    title_key = "nav.home"
    icon_name = "fa5s.home"

    def __init__(self, store, window):
        super().__init__(store, window)
        kpis = QHBoxLayout()
        kpis.setSpacing(14)
        self.k_debt = KpiCard(t("home.kpi.debt"), "fa5s.balance-scale")
        self.k_month = KpiCard(t("home.kpi.month"), "fa5s.calendar-alt")
        self.k_left = KpiCard(t("home.kpi.left"), "fa5s.wallet")
        self.k_payoff = KpiCard(t("home.kpi.payoff"), "fa5s.flag-checkered")
        for k in (self.k_debt, self.k_month, self.k_left, self.k_payoff):
            kpis.addWidget(k)
        self.body.addLayout(kpis)

        mid = QHBoxLayout()
        mid.setSpacing(14)
        self.month_card = Card(t("home.month.title"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["", t("home.month.col.date"), t("home.month.col.item"),
                                              t("home.month.col.kind"), t("home.month.col.amount"),
                                              t("home.month.col.status")])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col, w in ((0, 34), (1, 116), (3, 136), (4, 120), (5, 96)):
            self.table.setColumnWidth(col, w)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeaderItem(4).setTextAlignment(RIGHT)
        self.table.itemChanged.connect(self._item_changed)
        self.month_card.body.addWidget(self.table)
        mid.addWidget(self.month_card, 3)

        right = QVBoxLayout()
        right.setSpacing(14)
        self.alert_card = Card(t("home.alerts.title"))
        self.alert_box = QVBoxLayout()
        self.alert_box.setSpacing(8)
        self.alert_card.body.addLayout(self.alert_box)
        self.alert_card.body.addStretch(1)
        right.addWidget(self.alert_card, 1)
        self.breakdown_card = Card(t("home.breakdown.title"))
        self.breakdown = BreakdownBars()
        self.breakdown_card.body.addWidget(self.breakdown)
        right.addWidget(self.breakdown_card)
        mid.addLayout(right, 2)
        self.body.addLayout(mid)

        self.trend_card = Card(t("home.trend.title"))
        self.chart = TrendChart()
        self.trend_card.body.addWidget(self.chart)
        self.body.addWidget(self.trend_card)
        self.body.addStretch(1)
        self._rows: list[engine.DueItem] = []

    # ---- refresh ----------------------------------------------------------------------------------
    def refresh(self) -> None:
        store = self.store
        st = store.state()
        cur = store.currency
        s = engine.home_summary(st, store.rates, cur, rates_age_days=store.rates_age_days())

        if s.card_count:
            debt_sub = t("home.kpi.debt_sub_cards", n=s.bill_count, cards=money(s.cards_debt, cur))
        else:
            debt_sub = t("home.kpi.debt_sub", n=s.bill_count)
        self.k_debt.set(money(s.total_debt, cur), debt_sub)
        self.k_month.set(money(s.month_total, cur),
                         t("home.kpi.month_sub", paid=money(s.month_paid, cur), left=money(s.month_remaining, cur)))
        self.k_left.set(money(s.month_end, cur),
                        t("home.kpi.left_sub", s=money(s.savings_start, cur), i=money(s.income, cur),
                          o=money(s.outflow, cur)),
                        "critical" if s.month_end < 0 else "good" if s.month_end > 0 else None)
        po = s.payoff
        if po.status == "ok":
            self.k_payoff.set(fmt_period(po.period),
                              t("home.kpi.payoff_sub", n=po.months, interest=money(po.remaining_interest, cur)))
        elif po.status == "never":
            self.k_payoff.set(t("home.kpi.payoff_never"), t("home.kpi.payoff_never_sub", n=len(po.never)),
                              "critical")
        elif po.status == "no_plan":
            self.k_payoff.set(t("home.kpi.payoff_noplan"), t("home.kpi.payoff_noplan_sub", n=len(po.no_plan)),
                              "warning")
        else:
            self.k_payoff.set(t("home.kpi.payoff_none"), "", "good")

        self.month_card.set_subtitle(t("home.month.sub", period=fmt_period(st.current)))
        self._fill_table(s.items)
        self._fill_alerts(s.alerts)
        names = [(bill_type_label(code), v) for code, v in s.breakdown]
        self.breakdown.set_rows(names, cur)
        if po.status == "ok":
            self.trend_card.set_subtitle(t("home.trend.sub_ok", period=fmt_period(po.period), n=po.months))
        elif po.status == "never":
            self.trend_card.set_subtitle(t("home.trend.sub_never"))
        else:
            self.trend_card.set_subtitle(t("home.trend.sub_none") if not s.bill_count else "")
        self.chart.set_data([r.period for r in s.trend], [r.debt for r in s.trend], [r.savings for r in s.trend],
                            po.period if po.status == "ok" else None, cur)

    def _fill_table(self, rows: list[engine.DueItem]) -> None:
        tbl = self.table
        tbl.blockSignals(True)
        try:
            self._rows = rows
            tbl.setRowCount(max(1, len(rows)))
            if not rows:
                tbl.setSpan(0, 0, 1, 6)
                tbl.setItem(0, 0, item(t("home.month.empty"), Qt.AlignmentFlag.AlignCenter, tone="text_muted"))
                return
            tbl.clearSpans()
            for r, it in enumerate(rows):
                if it.kind == "income":
                    tbl.setItem(r, 0, item(""))
                    tbl.setItem(r, 1, item(fmt_md(it.due), tone="text_muted"))
                    tbl.setItem(r, 2, item(t("home.month.payday"), bold=True))
                    tbl.setItem(r, 3, item(t("home.month.income"), tone="text_muted"))
                    tbl.setItem(r, 4, item("+" + money(it.amount, it.currency), RIGHT, tone="good"))
                    tbl.setItem(r, 5, item(""))
                    continue
                tbl.setItem(r, 0, check_item(it.paid, r))
                tbl.setItem(r, 1, item(fmt_md(it.due), tone="text_muted"))
                tbl.setItem(r, 2, item(it.name))
                kind = bill_type_label(it.sub) if it.kind == "bill" else category_label(it.sub)
                tbl.setItem(r, 3, item(kind, tone="text_muted"))
                amount = it.paid_amount if it.paid else it.amount
                tbl.setItem(r, 4, item(money(amount, it.currency), RIGHT))
                if it.paid:
                    status, tone = t("common.paid"), "good"
                elif it.days < 0:
                    status, tone = due_text(it.days), "critical"
                elif it.days <= 3:
                    status, tone = due_text(it.days), "warning"
                else:
                    status, tone = due_text(it.days), "text_muted"
                tbl.setItem(r, 5, item(status, tone=tone))
        finally:
            tbl.blockSignals(False)
            # the page scrolls, so the table shows every row instead of scrolling inside
            head_h = tbl.horizontalHeader().sizeHint().height()
            tbl.setFixedHeight(head_h + tbl.rowCount() * tbl.verticalHeader().defaultSectionSize() + 4)

    def _fill_alerts(self, alerts: list[engine.Alert]) -> None:
        while self.alert_box.count():
            w = self.alert_box.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        tk = theme.current()
        if not alerts:
            alerts_ = [("fa5s.check-circle", "good", t("home.alerts.none"))]
        else:
            alerts_ = [(*ALERT_ICONS[a.level], alert_text(a)) for a in alerts[:7]]
        for icon_name, tone, text in alerts_:
            row = QHBoxLayout()
            row.setSpacing(8)
            ic = QLabel()
            ic.setPixmap(icon(icon_name, getattr(tk, tone)).pixmap(15, 15))
            ic.setAlignment(Qt.AlignmentFlag.AlignTop)
            ic.setContentsMargins(0, 2, 0, 0)
            row.addWidget(ic)
            row.addWidget(label(text, wrap=True), 1)
            row.setContentsMargins(0, 0, 0, 0)
            holder = QWidget()
            holder.setLayout(row)
            self.alert_box.addWidget(holder)

    # ---- ticking an item -----------------------------------------------------------------------------
    def _item_changed(self, cell) -> None:
        if cell.column() != 0 or not self._rows:
            return
        row = cell.data(Qt.ItemDataRole.UserRole)
        if row is None or row >= len(self._rows):
            return
        it = self._rows[row]
        checked = cell.checkState() == Qt.CheckState.Checked
        # Defer: the table must not be rebuilt inside its own signal (R13).
        QTimer.singleShot(0, lambda: self.win.toggle_paid(it.kind, it.target_id, checked, it.name, it.paid_amount))

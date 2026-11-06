"""Debts & cards: one page, two tabs (U1). Each debt shows its payoff month and interest left (F4)."""

from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QTabWidget, QVBoxLayout, QWidget

from . import engine
from .dialogs import DEFAULT_WIDTHS, TABLE_COLUMNS
from .i18n import bill_type_label, due_text, fmt_date, fmt_md, fmt_period, money, month_name, t
from .money import convert, fmt_number
from .periods import Period
from .shell import Page
from .widgets import CENTER, RIGHT, DataTable, ReorderTable, button, item, label


class DebtsPage(Page):
    key = "debts"
    title_key = "nav.debts"
    icon_name = "fa5s.file-invoice-dollar"
    scrollable = False

    def __init__(self, store, window):
        super().__init__(store, window)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.body.addWidget(self.tabs, 1)

        # -- debts tab
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(10)
        bar = QHBoxLayout()
        bar.addWidget(button(t("debts.add_bill"), "primary", "fa5s.plus", window.add_bill))
        bar.addWidget(button(t("common.edit"), None, "fa5s.pen", self._edit_bill))
        bar.addWidget(button(t("debts.record"), None, "fa5s.check", self._record))
        bar.addWidget(button(t("common.delete"), "danger", "fa5s.trash-alt", self._delete_bill))
        bar.addStretch(1)
        bar.addWidget(label(t("debts.drag_hint"), "Faint"))
        lay.addLayout(bar)
        self.bills = ReorderTable("bills", [t(k) for k in TABLE_COLUMNS["bills"]])
        self.bills.right_align((4, 6, 7, 8, 12))
        self.bills.itemDoubleClicked.connect(lambda _i: self._edit_bill())
        self.bills.rowMoved.connect(self._moved)
        self.bills.widthsChanged.connect(window.save_widths)
        lay.addWidget(self.bills, 1)
        self.bills_footer = label("", "Muted", wrap=True)
        lay.addWidget(self.bills_footer)
        self.tabs.addTab(w, t("debts.tab.bills"))

        # -- cards tab
        w2 = QWidget()
        lay2 = QVBoxLayout(w2)
        lay2.setContentsMargins(0, 12, 0, 0)
        lay2.setSpacing(10)
        bar2 = QHBoxLayout()
        bar2.addWidget(button(t("debts.add_card"), "primary", "fa5s.plus", window.add_card))
        bar2.addWidget(button(t("common.edit"), None, "fa5s.pen", self._edit_card))
        bar2.addWidget(button(t("cards.fee_toggle"), None, "fa5s.check", self._toggle_fee))
        bar2.addWidget(button(t("common.delete"), "danger", "fa5s.trash-alt", self._delete_card))
        bar2.addStretch(1)
        lay2.addLayout(bar2)
        self.cards = DataTable("cards", [t(k) for k in TABLE_COLUMNS["cards"]])
        self.cards.right_align((3, 4, 5, 6, 7, 8, 9))
        self.cards.itemDoubleClicked.connect(lambda _i: self._edit_card())
        self.cards.widthsChanged.connect(window.save_widths)
        lay2.addWidget(self.cards, 1)
        self.cards_footer = label("", "Muted", wrap=True)
        lay2.addWidget(self.cards_footer)
        self.tabs.addTab(w2, t("debts.tab.cards"))
        self._bill_ids: list[int] = []

    # ---- refresh ---------------------------------------------------------------------------------
    def refresh(self) -> None:
        st = self.store.state()
        cfg = self.store.cfg
        self.bills.apply_layout(cfg.hidden("bills"), cfg.column_widths.get("bills"), DEFAULT_WIDTHS["bills"])
        self.cards.apply_layout(cfg.hidden("cards"), cfg.column_widths.get("cards"), DEFAULT_WIDTHS["cards"])
        self._fill_bills(st)
        self._fill_cards(st)

    def _fill_bills(self, st: engine.State) -> None:
        target, rates = self.store.currency, self.store.rates
        cur_period = st.current
        tbl = self.bills
        tbl.setRowCount(len(st.bills))
        self._bill_ids = [b.id for b in st.bills]
        tot_bal = tot_month = tot_monthly = 0.0
        payoffs = engine.bill_payoffs(st)
        for r, b in enumerate(st.bills):
            paid = st.paid_bills.get(b.id)
            this_month = paid.amount if paid and paid.paid else engine.planned_amount(b, cur_period)
            info = payoffs[b.id]
            tot_bal += convert(b.amount, b.currency, target, rates)
            tot_month += convert(this_month, b.currency, target, rates)
            if b.amount > 0 and not b.is_lump_sum:
                tot_monthly += convert(b.monthly_payment, b.currency, target, rates)
            due = engine.due_date(cur_period, b.monthly_due_day)
            nominal = cur_period.day(b.monthly_due_day)
            days = (due - st.today).days
            underwater = engine.is_underwater(b)
            tbl.setItem(r, 0, item(b.label, data=b.id, bold=True))
            tbl.setItem(r, 1, item(bill_type_label(b.bill_type), tone="text_muted"))
            tbl.setItem(r, 2, item(b.lender_name))
            tbl.setItem(r, 3, item(b.borrower_name))
            tbl.setItem(r, 4, item(fmt_number(b.amount, b.currency), RIGHT, bold=True))
            tbl.setItem(r, 5, item(b.currency, CENTER, tone="text_muted"))
            tbl.setItem(r, 6, item(f"{b.interest_rate:g}%" if b.has_interest else "—", RIGHT))
            monthly = "—" if b.is_lump_sum else fmt_number(b.monthly_payment, b.currency)
            tbl.setItem(r, 7, item(monthly, RIGHT, tone="critical" if underwater else None,
                                   tooltip=alert_tip(b) if underwater else None))
            tbl.setItem(r, 8, item(fmt_number(this_month, b.currency), RIGHT))
            if paid and paid.paid:
                tbl.setItem(r, 9, item(t("due.cell_day", day=b.monthly_due_day), tone="text_muted"))
                tbl.setItem(r, 10, item("✓ " + t("common.paid"), tone="good"))
            elif b.amount <= 0:
                tbl.setItem(r, 9, item(t("due.cell_day", day=b.monthly_due_day), tone="text_muted"))
                tbl.setItem(r, 10, item("—", tone="text_faint"))
            elif days < 0 and b.auto_debit:
                tbl.setItem(r, 9, item(t("due.cell_pending", day=b.monthly_due_day), tone="warning",
                                       tooltip=t("due.pending_tip")))
                tbl.setItem(r, 10, item(t("common.pending"), tone="warning", tooltip=t("due.pending_tip")))
            else:
                tone = "critical" if days < 0 else "warning" if days <= 3 else None
                if due != nominal:
                    text = t("due.cell_moved", day=b.monthly_due_day, moved=fmt_md(due, weekday=False), rel=due_text(days))
                    tip = t("due.moved_tip", nominal=fmt_md(nominal), due=fmt_md(due))
                else:
                    text, tip = t("due.cell", day=b.monthly_due_day, rel=due_text(days)), None
                tbl.setItem(r, 9, item(text, tone=tone, tooltip=tip))
                tbl.setItem(r, 10, item(t("common.unpaid"), tone="critical" if days < 0 else "text_muted"))
            if info.status == "ok":
                tbl.setItem(r, 11, item(fmt_period(info.period)))
                tbl.setItem(r, 12, item(fmt_number(info.remaining_interest, b.currency), RIGHT))
            elif info.status == "never":
                tbl.setItem(r, 11, item(t("debts.payoff_never"), tone="critical", tooltip=alert_tip(b)))
                tbl.setItem(r, 12, item("∞", RIGHT, tone="critical"))
            elif info.status == "no_plan":
                tbl.setItem(r, 11, item(t("debts.payoff_noplan"), tone="warning"))
                tbl.setItem(r, 12, item("—", RIGHT, tone="text_faint"))
            else:
                tbl.setItem(r, 11, item(t("debts.payoff_done"), tone="good"))
                tbl.setItem(r, 12, item("—", RIGHT, tone="text_faint"))
            tbl.setItem(r, 13, item(fmt_date(b.created_date), tone="text_muted"))
        self.bills_footer.setText(t("debts.footer", cur=target, balance=money(tot_bal, target),
                                    month=money(tot_month, target), monthly=money(tot_monthly, target)))

    def _fill_cards(self, st: engine.State) -> None:
        target, rates = self.store.currency, self.store.rates
        tbl = self.cards
        tbl.setRowCount(len(st.cards))
        tl = tu = ta = fees = 0.0
        unpaid = 0
        for r, c in enumerate(st.cards):
            tl += convert(c.credit_limit, c.currency, target, rates)
            tu += convert(c.used_amount, c.currency, target, rates)
            ta += convert(c.available, c.currency, target, rates)
            u = c.utilization
            tbl.setItem(r, 0, item(c.issuer))
            tbl.setItem(r, 1, item(c.name or c.issuer, data=c.id, bold=True))
            tbl.setItem(r, 2, item(str(c.due_day), CENTER))
            tbl.setItem(r, 3, item(fmt_number(c.credit_limit, c.currency), RIGHT))
            tbl.setItem(r, 4, item(fmt_number(c.used_amount, c.currency), RIGHT, bold=True))
            tbl.setItem(r, 5, item(fmt_number(c.available, c.currency), RIGHT,
                                   tone="critical" if c.available < 0 else "good"))
            tbl.setItem(r, 6, item("—" if u is None else f"{u:.0%}", RIGHT,
                                   tone="critical" if u is not None and u >= 0.8 else None))
            tbl.setItem(r, 7, item(fmt_number(c.shopping_credit_amount, c.currency), RIGHT))
            tbl.setItem(r, 8, item(fmt_number(c.shopping_revolving_amount, c.currency), RIGHT))
            tbl.setItem(r, 9, item(fmt_number(c.cash_revolving_amount, c.currency), RIGHT))
            text, tone = fee_text(c, st)
            if c.annual_fee > 0:
                fees += convert(c.annual_fee, c.currency, target, rates)
                if engine.fee_status(c, st.today).state == "due":
                    unpaid += 1
            tbl.setItem(r, 10, item(text, tone=tone))
            tbl.setItem(r, 11, item(c.currency, CENTER, tone="text_muted"))
            tbl.setItem(r, 12, item("✓" if c.managed_in_bills else "—", CENTER,
                                    tone="good" if c.managed_in_bills else "text_faint"))
            tbl.setItem(r, 13, item(fmt_date(c.last_updated), tone="text_muted"))
        footer = t("cards.footer", cur=target, limit=money(tl, target), used=money(tu, target),
                   avail=money(ta, target))
        if fees > 0:
            footer += "  ・" + t("cards.footer_fee", total=money(fees, target), n=unpaid)
        self.cards_footer.setText(footer)

    # ---- actions -----------------------------------------------------------------------------------------
    def _selected_bill(self):
        bill_id = self.bills.selected_data(0)
        return next((b for b in self.store.state().bills if b.id == bill_id), None)

    def _selected_card(self):
        card_id = self.cards.selected_data(1)
        return next((c for c in self.store.state().cards if c.id == card_id), None)

    def _edit_bill(self) -> None:
        b = self._selected_bill()
        if b is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.edit_bill(b)

    def _record(self) -> None:
        b = self._selected_bill()
        if b is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.record_payment(b)

    def _delete_bill(self) -> None:
        b = self._selected_bill()
        if b is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.delete_bill(b)

    def _edit_card(self) -> None:
        c = self._selected_card()
        if c is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.edit_card(c)

    def _toggle_fee(self) -> None:
        c = self._selected_card()
        if c is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.toggle_fee(c)

    def _delete_card(self) -> None:
        c = self._selected_card()
        if c is None:
            self.win.notify(t("common.select_row"))
            return
        self.win.delete_card(c)

    def _moved(self, src: int, dst: int) -> None:
        ids = list(self._bill_ids)
        if not (0 <= src < len(ids)):
            return
        moved = ids.pop(src)
        ids.insert(dst, moved)
        self.store.reorder_bills(ids)
        self.bills.selectRow(dst)


def fee_text(card, st) -> tuple[str, str | None]:
    """The annual-fee cell (B1): amount, status and the month it is (or was) billed."""
    fs = engine.fee_status(card, st.today)
    amount = fmt_number(card.annual_fee, card.currency)
    if fs.state == "free":
        return t("fee.free"), "text_faint"
    if fs.state == "paid":
        marker = Period.try_parse(fs.paid_label)
        when = fmt_period(marker) if marker else t("fee.year", year=fs.paid_label[:4])
        return t("fee.paid", amount=amount, when=when), "good"
    if fs.state == "due":
        this_month = fs.cycle == st.current
        when = month_name(fs.cycle.month) if this_month else fmt_period(fs.cycle)
        return t("fee.due", amount=amount, when=when), "warning" if this_month else "critical"
    if fs.state == "upcoming":
        return t("fee.next", amount=amount, when=fmt_period(fs.next_bill)), "text_muted"
    return t("fee.no_month", amount=amount), "warning"


def alert_tip(b) -> str:
    return t("alert.underwater", name=b.label, payment=money(b.monthly_payment, b.currency),
             interest=money(engine.monthly_interest(b), b.currency))

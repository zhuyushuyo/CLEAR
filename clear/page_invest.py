"""Investments (I1-I6, P2): four numbers, the allocation, NISA limits and the holdings list."""

from __future__ import annotations

from PyQt6.QtWidgets import QGridLayout, QHBoxLayout, QTabBar, QVBoxLayout

from . import engine, invest, market
from .chart import AllocationBar, UsageBar
from .dialogs import DEFAULT_WIDTHS, TABLE_COLUMNS
from .i18n import fmt_datetime, join_names, label_of, lang, money, t
from .models import HOLDING_KINDS
from .shell import Page
from .widgets import CENTER, RIGHT, Card, DataTable, KpiCard, button, item, label, set_tone

KIND_COLORS = {"stock": "cat1", "crypto": "cat2", "metal": "cat3", "manual": "cat4"}
ACCOUNT_COLORS = {"taxable": "cat1", "nisa_tsumitate": "cat4", "nisa_growth": "cat5", "ideco": "cat3",
                  "exchange": "cat2", "other": "text_muted"}
CYCLE = ("cat1", "cat2", "cat3", "cat4", "cat5", "text_muted")
TABS = ("all",) + HOLDING_KINDS


def fmt_qty(h, qty: float) -> str:
    if h.kind == "manual":
        return "—"
    text = invest.quantity_text(h.kind, qty)
    return f"{text} {h.unit}" if h.kind == "metal" else text


def signed(value: float, currency: str) -> str:
    text = money(value, currency)
    return f"+{text}" if value > 0 else text


class InvestPage(Page):
    key = "invest"
    title_key = "nav.invest"
    icon_name = "fa5s.chart-pie"

    def __init__(self, store, window):
        super().__init__(store, window)
        bar = QHBoxLayout()
        bar.addWidget(button(t("invest.add"), "primary", "fa5s.plus", window.add_holding))
        bar.addWidget(button(t("common.edit"), None, "fa5s.pen", self._edit))
        bar.addWidget(button(t("invest.trade"), None, "fa5s.exchange-alt", self._trade))
        undo = button(t("invest.undo"), None, "fa5s.undo", self._undo)
        undo.setToolTip(t("invest.undo_tip"))
        bar.addWidget(undo)
        bar.addWidget(button(t("common.delete"), "danger", "fa5s.trash-alt", self._delete))
        bar.addStretch(1)
        self.refresh_btn = button(t("invest.refresh"), None, "fa5s.sync-alt", self._refresh_prices)
        self.refresh_btn.setToolTip(t("invest.refresh_tip"))
        bar.addWidget(self.refresh_btn)
        bar.addWidget(button(t("invest.settings"), None, "fa5s.sliders-h", window.invest_settings))
        self.body.addLayout(bar)
        self.status = label("", "Hint", wrap=True)
        self.body.addWidget(self.status)

        kpis = QHBoxLayout()
        kpis.setSpacing(14)
        self.k_value = KpiCard(t("invest.kpi.value"), "fa5s.coins")
        self.k_gain = KpiCard(t("invest.kpi.gain"), "fa5s.chart-line")
        self.k_day = KpiCard(t("invest.kpi.day"), "fa5s.clock")
        self.k_contrib = KpiCard(t("invest.kpi.contrib"), "fa5s.piggy-bank")
        for k in (self.k_value, self.k_gain, self.k_day, self.k_contrib):
            kpis.addWidget(k, 1)
        self.body.addLayout(kpis)

        mid = QHBoxLayout()
        mid.setSpacing(14)
        self.alloc_card = Card(t("invest.alloc.title"))
        self.alloc_card.body.setSpacing(12)
        self.alloc_bars = {code: AllocationBar(t(f"invest.alloc.{code}")) for code in ("kind", "account", "currency")}
        for w in self.alloc_bars.values():
            self.alloc_card.body.addWidget(w)
        self.alloc_card.body.addStretch(1)
        mid.addWidget(self.alloc_card, 3)
        self.nisa_card = Card(t("invest.nisa.title", year=""), t("invest.nisa.sub"))
        self.nisa_bars = {
            "nisa_tsumitate": UsageBar(t("invest.nisa.tsumitate")),
            "nisa_growth": UsageBar(t("invest.nisa.growth")),
            "lifetime": UsageBar(t("invest.nisa.lifetime")),
            "lifetime_growth": UsageBar(t("invest.nisa.lifetime_growth")),
        }
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(6)
        for i, w in enumerate(self.nisa_bars.values()):
            grid.addWidget(w, i // 2, i % 2)
        self.nisa_card.body.addLayout(grid)
        self.nisa_card.body.addStretch(1)
        mid.addWidget(self.nisa_card, 2)
        self.body.addLayout(mid)

        lower = QVBoxLayout()
        lower.setSpacing(8)
        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.addTab(t("invest.tab.all"))
        for kind in HOLDING_KINDS:
            self.tabs.addTab(label_of("kind", kind).replace("&", "&&"))  # "&" alone would be a mnemonic
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        lower.addWidget(self.tabs)
        self.table = DataTable("invest", [t(k) for k in TABLE_COLUMNS["invest"]])
        self.table.setMinimumHeight(250)   # the page scrolls instead of squeezing the list
        self.table.right_align((3, 4, 5, 6, 7, 8, 9, 10))
        self.table.itemDoubleClicked.connect(lambda _i: self._edit())
        self.table.widthsChanged.connect(window.save_widths)
        lower.addWidget(self.table, 1)
        self.empty = label(t("invest.empty"), "Hint")
        lower.addWidget(self.empty)
        self.footer = label("", "Muted", wrap=True)
        lower.addWidget(self.footer)
        self.body.addLayout(lower, 1)
        self._ids: list[int] = []
        store.market_status.connect(self._market_done)

    # ---- refresh ---------------------------------------------------------------------------------------
    def refresh(self) -> None:
        store = self.store
        st = store.state()
        cur, rates = store.currency, store.rates
        folio = invest.summarize(st.holdings, st.prices, rates, cur)

        self.k_value.set(money(folio.value, cur), t("invest.kpi.value_sub", n=len(st.holdings)))
        if folio.cost > 0:
            pct = folio.gain_pct or 0.0
            self.k_gain.set(signed(folio.gain, cur), f"{t('invest.kpi.gain_sub', cost=money(folio.cost, cur))} "
                            f"・{pct:+.1%}", "good" if folio.gain > 0 else "critical" if folio.gain < 0 else None)
        else:
            self.k_gain.set("—", "")
        if folio.has_day_change:
            d = folio.day_change
            self.k_day.set(signed(d, cur), t("invest.kpi.day_sub"), "good" if d > 0 else "critical" if d < 0 else None)
        else:
            self.k_day.set("—", t("invest.kpi.day_sub"))
        items = [i for i in engine.month_items(st, rates, cur) if i.kind == "contrib"]
        done = sum(i.amount_target for i in items if i.paid)
        left = sum(i.amount_target for i in items if not i.paid)
        self.k_contrib.set(money(done + left, cur), t("invest.kpi.contrib_sub", done=money(done, cur),
                                                      left=money(left, cur)))

        self._fill_alloc(folio)
        uses_nisa = invest.uses_nisa(st.holdings)
        self.nisa_card.setVisible(uses_nisa)
        if uses_nisa:
            usage = invest.nisa_usage(st.holdings, st.trades_year, st.today.year, rates)
            self.nisa_card.title_label.setText(t("invest.nisa.title", year=st.today.year))
            self.nisa_bars["nisa_tsumitate"].set_values(usage.year_used.get("nisa_tsumitate", 0.0),
                                                        invest.NISA_YEAR_LIMIT["nisa_tsumitate"])
            self.nisa_bars["nisa_growth"].set_values(usage.year_used.get("nisa_growth", 0.0),
                                                     invest.NISA_YEAR_LIMIT["nisa_growth"])
            self.nisa_bars["lifetime"].set_values(usage.lifetime_used, invest.NISA_LIFETIME)
            self.nisa_bars["lifetime_growth"].set_values(usage.lifetime_growth, invest.NISA_LIFETIME_GROWTH)

        self._fill_status(st, folio)
        cfg = store.cfg
        self.table.apply_layout(cfg.hidden("invest"), cfg.column_widths.get("invest"), DEFAULT_WIDTHS["invest"])
        self._fill_table(folio, cur)

    def _fill_alloc(self, folio: invest.PortfolioSummary) -> None:
        cur = self.store.currency
        self.alloc_bars["kind"].set_rows(
            [(label_of("kind", k), folio.by_kind.get(k, 0.0), KIND_COLORS[k]) for k in HOLDING_KINDS], cur)
        accounts = sorted(folio.by_account.items(), key=lambda kv: -kv[1])
        self.alloc_bars["account"].set_rows(
            [(label_of("acct", k), v, ACCOUNT_COLORS.get(k, "text_muted")) for k, v in accounts], cur)
        currencies = sorted(folio.by_currency.items(), key=lambda kv: -kv[1])
        self.alloc_bars["currency"].set_rows(
            [(k, v, CYCLE[i % len(CYCLE)]) for i, (k, v) in enumerate(currencies)], cur)

    def _fill_status(self, st, folio) -> None:
        busy = self.store.market_busy
        self.refresh_btn.setEnabled(not busy and self.store.has_db)
        self.refresh_btn.setText(t("invest.refreshing") if busy else t("invest.refresh"))
        last = self.store.last_market
        if last is not None and not last.ok and folio.missing:
            self.status.setText(t("invest.status_failed", reason=self.failure_text(last, one_line=True)))
            set_tone(self.status, "warning")
            return
        set_tone(self.status, None)
        when = folio.last_fetch
        if when is None:
            self.status.setText(t("invest.never") if st.holdings else "")
            return
        sources = sorted({hv.source for hv in folio.rows if hv.source and hv.source != "manual"})
        self.status.setText(t("invest.updated", when=fmt_datetime(when),
                              sources=join_names([label_of("src", s) for s in sources])))

    def _fill_table(self, folio: invest.PortfolioSummary, cur: str) -> None:
        tab = TABS[max(0, self.tabs.currentIndex())]
        rows = [hv for hv in folio.rows if tab == "all" or hv.holding.kind == tab]
        tbl = self.table
        tbl.setRowCount(len(rows))
        self._ids = [hv.holding.id for hv in rows]
        for r, hv in enumerate(rows):
            h = hv.holding
            hc = h.currency
            tbl.setItem(r, 0, item(h.label, data=h.id, bold=True, tooltip=h.symbol or None))
            kind = label_of("metal", h.symbol) if h.kind == "metal" else label_of("kind", h.kind)
            tbl.setItem(r, 1, item(kind, tone="text_muted"))
            tbl.setItem(r, 2, item(label_of("acct", h.account), tone="text_muted"))
            tbl.setItem(r, 3, item(fmt_qty(h, h.quantity), RIGHT))
            show_unit = h.kind != "manual"
            tbl.setItem(r, 4, item(money(h.avg_cost, hc) if show_unit and h.avg_cost > 0 else "—", RIGHT,
                                   tone=None if h.avg_cost > 0 else "text_faint"))
            if hv.unit_price is not None and show_unit:
                tbl.setItem(r, 5, item(money(hv.unit_price, hc), RIGHT))
            elif not show_unit:
                tbl.setItem(r, 5, item("—", RIGHT, tone="text_faint"))
            else:
                key = "invest.price_no_fx" if hv.status == "no_fx" else "invest.price_missing"
                tbl.setItem(r, 5, item(t(key), RIGHT, tone="warning"))
            if hv.value_t is not None:
                tbl.setItem(r, 6, item(money(hv.value_t, cur), RIGHT, bold=True))
            else:
                tbl.setItem(r, 6, item("—", RIGHT, tone="text_faint"))
            if hv.gain_t is not None:
                tone = "good" if hv.gain_t > 0 else "critical" if hv.gain_t < 0 else None
                tbl.setItem(r, 7, item(signed(hv.gain_t, cur), RIGHT, tone=tone))
                tbl.setItem(r, 8, item(f"{hv.gain_pct:+.1%}", RIGHT, tone=tone))
            else:
                tbl.setItem(r, 7, item("—", RIGHT, tone="text_faint"))
                tbl.setItem(r, 8, item("—", RIGHT, tone="text_faint"))
            if hv.day_change_t is not None:
                d = hv.day_change_t
                tbl.setItem(r, 9, item(signed(d, cur), RIGHT, tone="good" if d > 0 else "critical" if d < 0 else None))
            else:
                tbl.setItem(r, 9, item("—", RIGHT, tone="text_faint"))
            if h.has_contribution:
                text = t("invest.contrib_cell", amount=money(h.contrib_amount, h.contrib_currency), day=h.contrib_day)
                tbl.setItem(r, 10, item(text, RIGHT))
            else:
                tbl.setItem(r, 10, item("—", RIGHT, tone="text_faint"))
            tbl.setItem(r, 11, item(hc, CENTER, tone="text_muted"))
            src = label_of("src", hv.source or "manual")
            if h.symbol and h.kind in ("stock", "crypto"):
                src = f"{src} · {h.symbol}"
            tbl.setItem(r, 12, item(src, tone="text_muted"))
            when = fmt_datetime(hv.fetched_at) if hv.fetched_at else "—"
            tbl.setItem(r, 13, item(when, tone="warning" if hv.status == "stale" else "text_muted"))
        self.empty.setVisible(not folio.rows)
        gain = signed(folio.gain, cur) if folio.cost > 0 else "—"
        self.footer.setText(t("invest.footer", cur=cur, value=money(folio.value, cur),
                              cost=money(folio.cost, cur), gain=gain))

    # ---- actions ------------------------------------------------------------------------------------------
    def _selected(self):
        hid = self.table.selected_data(0)
        return next((h for h in self.store.state().holdings if h.id == hid), None)

    def _need_selection(self):
        h = self._selected()
        if h is None:
            self.win.notify(t("common.select_row"))
        return h

    def _edit(self) -> None:
        h = self._need_selection()
        if h is not None:
            self.win.edit_holding(h)

    def _trade(self) -> None:
        h = self._need_selection()
        if h is not None:
            self.win.record_trade(h)

    def _undo(self) -> None:
        h = self._need_selection()
        if h is not None:
            self.win.undo_trade(h)

    def _delete(self) -> None:
        h = self._need_selection()
        if h is not None:
            self.win.delete_holding(h)

    def _refresh_prices(self) -> None:
        if self.store.refresh_market(force=True, quiet=False):
            self.refresh_btn.setEnabled(False)
            self.refresh_btn.setText(t("invest.refreshing"))
        elif not self.store.market_busy:
            self.win.notify(t("invest.fetch_nothing"))

    def failure_text(self, result: market.MarketResult, one_line: bool = False) -> str:
        """Why prices are missing, in words a person can act on."""
        lines = []
        for e in result.errors:
            key = {"rate_limit": "market.err.rate_limit", "connection": "market.err.connection"}.get(
                e.kind, "market.err.other")
            lines.append(t(key, source=e.source, detail=e.detail))
        if result.missing:
            codes = set(result.missing)
            names = []
            for h in self.store.state().holdings:
                ref = invest.quote_ref(h)
                code = ref[1].split("@")[0] if ref else ""
                if code in codes:
                    names.append(f"{h.label}（{code}）" if lang() == "ja" else f"{h.label} ({code})")
            # with a source down the codes are probably fine; otherwise the sources did not know them
            key = "market.err.missing" if result.errors else "market.err.unknown_codes"
            lines.append(t(key, names=join_names(names or sorted(codes))))
        return ("  " if one_line else "\n").join(lines)

    def _market_done(self, result: market.MarketResult, quiet: bool) -> None:
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText(t("invest.refresh"))
        if not self.isVisible():
            return
        if result.ok:
            if not quiet:
                self.win.notify(t("invest.fetched"))
            return
        text = t("invest.fetch_failed", error=self.failure_text(result))
        if quiet:
            self.win.notify(text.replace("\n", " "))
        else:
            self.win.notify(text, is_error=True)

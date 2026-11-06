"""Investment forms (I1, I4, I5, I6): holdings with code search, trades, settings."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QWidget

from . import invest, market
from .dialogs import FormDialog
from .i18n import label_of, money, t
from .models import ACCOUNTS, CONTRIB_METHODS, HOLDING_KINDS, METAL_UNITS, METALS, TRADE_KINDS, Holding
from .money import CURRENCIES, decimals, fmt_number, round_money
from .store import TaskWorker
from .widgets import CurrencyCombo, DateField, DayCombo, MoneySpin, button, label, repolish

# Exchange suffix -> currency, used when a code is typed without looking it up.
SUFFIX_CURRENCY = {
    ".T": "JPY", ".SS": "CNY", ".SZ": "CNY", ".SI": "SGD", ".HK": "HKD", ".L": "GBp", ".DE": "EUR", ".F": "EUR",
    ".PA": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR", ".TO": "CAD", ".AX": "AUD", ".KS": "KRW", ".TW": "TWD",
}


def guess_quote_currency(symbol: str) -> str:
    sym = symbol.strip().upper()
    if not sym:
        return ""
    if sym.endswith("=F"):
        return "USD"
    for suffix, cur in SUFFIX_CURRENCY.items():
        if sym.endswith(suffix.upper()):
            return cur
    return "" if "." in sym else "USD"


def qty_spin(kind: str) -> MoneySpin:
    spin = MoneySpin("USD")
    spin.setDecimals(invest.QTY_DECIMALS.get(kind, 4))
    spin.setSingleStep(1)
    return spin


def combo(prefix: str, codes, current: str) -> QComboBox:
    box = QComboBox()
    for code in codes:
        box.addItem(label_of(prefix, code), code)
    box.setCurrentIndex(max(0, box.findData(current)))
    return box


# ---------------------------------------------------------------------------------------------------
class HoldingDialog(FormDialog):
    def __init__(self, parent: QWidget | None, store, holding: Holding | None, default_currency: str):
        super().__init__(t("hold.title_edit" if holding else "hold.title_add"), parent,
                         deletable=holding is not None)
        self.setMinimumWidth(600)
        self.store = store
        self.src = holding
        today = store.today()
        h = holding or Holding(currency=default_currency, contrib_currency=default_currency, created_date=today)
        self._worker = None
        self._quote_currency = h.quote_currency

        self.kind = combo("kind", HOLDING_KINDS, h.kind)
        self.kind.setEnabled(holding is None)  # trades depend on the kind
        self.symbol = QLineEdit(h.symbol if h.kind in ("stock", "crypto") else "")
        self.search_btn = button(t("hold.f.search"), None, "fa5s.search", self._search)
        sym_row = QHBoxLayout()
        sym_row.setSpacing(8)
        sym_row.addWidget(self.symbol, 1)
        sym_row.addWidget(self.search_btn)
        self.results = QListWidget()
        self.results.setMaximumHeight(150)
        self.results.hide()
        self.results.itemClicked.connect(self._picked)
        self.quote_info = label("", "Hint")
        self.name = QLineEdit(h.name)
        self.metal = combo("metal", METALS, h.symbol if h.kind == "metal" else "gold")
        self.unit = combo("unit", METAL_UNITS, h.unit or "g")
        self.source = QComboBox()
        self.account = combo("acct", ACCOUNTS, h.account)
        self.qty = qty_spin(h.kind)
        self.qty.setValue(h.quantity)
        self.currency = CurrencyCombo(h.currency)
        self.avg = MoneySpin(h.currency)
        self.avg.setValue(h.avg_cost)
        self.manual_price = MoneySpin(h.currency)
        self.manual_price.setValue(h.manual_price)
        self.adjust = MoneySpin("USD", allow_negative=True)
        self.adjust.setRange(-50, 200)
        self.adjust.setDecimals(2)
        self.adjust.setValue(h.adjust_pct)
        self.adjust.setMaximumWidth(140)
        self.contrib = MoneySpin(h.contrib_currency)
        self.contrib.setValue(h.contrib_amount)
        self.contrib_cur = CurrencyCombo(h.contrib_currency)
        self.contrib_day = DayCombo()
        self.contrib_day.setValue(h.contrib_day)
        self.contrib_method = combo("cmethod", CONTRIB_METHODS, h.contrib_method)
        contrib_row = QHBoxLayout()
        contrib_row.setSpacing(8)
        contrib_row.addWidget(self.contrib, 1)
        contrib_row.addWidget(self.contrib_cur)
        contrib_row.addWidget(label(t("hold.f.contrib_day"), "Muted"))
        contrib_row.addWidget(self.contrib_day)
        contrib_row.addWidget(self.contrib_method)
        self.note = QLineEdit(h.note)
        cur_row = QHBoxLayout()
        cur_row.setSpacing(8)
        cur_row.addWidget(self.currency)
        cur_row.addWidget(self.quote_info, 1)

        self.row(t("hold.f.kind"), self.kind)
        self.row(t("hold.f.symbol"), sym_row)
        self._fields[id(self.symbol)] = sym_row
        self.form.addRow("", self.results)
        self.row(t("hold.f.metal"), self.metal)
        self.row(t("hold.f.name"), self.name)
        self.row(t("hold.f.quote"), self.source)
        self.row(t("hold.f.account"), self.account)
        self.row(t("hold.f.currency"), cur_row)
        self._fields[id(self.currency)] = cur_row
        self.row(t("hold.f.unit"), self.unit)
        self.row(t("hold.f.quantity"), self.qty)
        self.avg_hint = label("", "Hint", wrap=True)
        self.row(t("hold.f.avg_cost"), self.avg)
        self.form.addRow("", self.avg_hint)
        self.price_label = label("", None)
        self.form.addRow(self.price_label, self.manual_price)
        self._fields[id(self.manual_price)] = self.manual_price
        self.row(t("hold.f.adjust"), self.adjust, t("hold.f.adjust_hint"))
        self.row(t("hold.f.contrib"), contrib_row)
        self._fields[id(self.contrib)] = contrib_row
        self.row(t("hold.f.note"), self.note)

        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.source.currentIndexChanged.connect(self._sync)
        self.currency.currentTextChanged.connect(self._currency_changed)
        self.contrib_cur.currentTextChanged.connect(self.contrib.set_currency)
        self.metal.currentIndexChanged.connect(self._metal_changed)
        self.unit.currentIndexChanged.connect(self._sync)
        self.symbol.editingFinished.connect(self._symbol_typed)
        for w in (self.qty, self.avg, self.manual_price, self.adjust):
            w.valueChanged.connect(self._update_preview)
        self._fill_sources(h.price_source)
        self._sync()
        (self.symbol if h.kind in ("stock", "crypto") else self.name).setFocus()

    # ---- state ------------------------------------------------------------------------------------------
    def _kind(self) -> str:
        return self.kind.currentData()

    def _source(self) -> str:
        return self.source.currentData() or "manual"

    def _fill_sources(self, current: str | None = None) -> None:
        kind = self._kind()
        options = {"stock": ("yahoo", "manual"), "crypto": ("coingecko", "bitflyer", "manual"),
                   "metal": ("yahoo", "manual"), "manual": ("manual",)}[kind]
        self.source.blockSignals(True)
        self.source.clear()
        for code in options:
            self.source.addItem(label_of("src", code), code)
        idx = self.source.findData(current) if current else -1
        self.source.setCurrentIndex(max(0, idx))
        self.source.blockSignals(False)

    def _kind_changed(self) -> None:
        kind = self._kind()
        self._fill_sources()
        self.qty.setDecimals(invest.QTY_DECIMALS.get(kind, 4))
        self.results.hide()
        if kind == "metal" and not self.name.text().strip():
            self.name.setText(label_of("metal", self.metal.currentData()))
        if kind in ("crypto", "metal") and self.src is None:
            self.currency.setCurrentText("JPY")
        self._sync()

    def _metal_changed(self) -> None:
        names = {label_of("metal", m) for m in METALS}
        if not self.name.text().strip() or self.name.text().strip() in names:
            self.name.setText(label_of("metal", self.metal.currentData()))
        self._sync()

    def _currency_changed(self, cur: str) -> None:
        for w in (self.avg, self.manual_price):
            w.set_currency(cur)
        self._sync()

    def _unit_word(self) -> str:
        kind = self._kind()
        if kind == "metal":
            return t(f"unit1.{self.unit.currentData()}")   # singular: "per gram"
        return t("unit.share") if kind == "stock" else t("unit.coin")

    def _sync(self) -> None:
        kind, source = self._kind(), self._source()
        manual_kind = kind == "manual"
        self.set_row_visible(self.symbol, kind in ("stock", "crypto"))
        self.results.setVisible(self.results.isVisible() and kind in ("stock", "crypto"))
        self.set_row_visible(self.metal, kind == "metal")
        self.set_row_visible(self.unit, kind == "metal")
        self.set_row_visible(self.adjust, kind == "metal" and source != "manual")
        self.set_row_visible(self.source, not manual_kind)
        self.set_row_visible(self.qty, not manual_kind)
        self.set_row_visible(self.manual_price, manual_kind or source == "manual")
        self.symbol.setPlaceholderText(t("hold.f.symbol_ph_crypto" if kind == "crypto" else "hold.f.symbol_ph_stock"))
        self.search_btn.setEnabled(kind in ("stock", "crypto") and source != "bitflyer")
        unit = self._unit_word()
        self._set_label(self.avg, t("hold.f.cost_total") if manual_kind else t("hold.f.avg_cost"))
        self.avg_hint.setText("" if manual_kind else t("hold.f.avg_cost_hint", unit=unit))
        self.avg_hint.setVisible(not manual_kind)
        self.price_label.setText(t("hold.f.value") if manual_kind else t("hold.f.manual_price", unit=unit))
        if kind == "crypto" and source == "bitflyer":
            self.currency.setCurrentText("JPY")
            self.currency.setEnabled(False)
            self.quote_info.setText(t("hold.bitflyer_hint"))
        else:
            self.currency.setEnabled(True)
            quote = self._quote()
            self.quote_info.setText(t("hold.quote_info", cur=quote) if quote and kind == "stock"
                                    and source == "yahoo" else "")
        self._update_preview()

    def _set_label(self, widget: QWidget, text: str) -> None:
        field = self._fields.get(id(widget), widget)
        lbl = self.form.labelForField(field)
        if lbl is not None:
            lbl.setText(text)

    def _quote(self) -> str:
        if self._kind() == "metal":
            return "USD"
        if self._kind() == "crypto":
            return "JPY" if self._source() == "bitflyer" else self.currency.currentText()
        return self._quote_currency or guess_quote_currency(self.symbol.text())

    # ---- search ------------------------------------------------------------------------------------------
    def _symbol_typed(self) -> None:
        if self._kind() == "stock":
            self._quote_currency = ""
            self._sync()

    def _search(self) -> None:
        query = self.symbol.text().strip() or self.name.text().strip()
        if not query or (self._worker is not None and self._worker.isRunning()):
            return
        kind = self._kind()
        if kind == "stock" and not market.yfinance_available():
            self._show_results([], t("hold.no_yf_search"))
            return
        key = self.store.cfg.coingecko_key.strip()
        fn = (lambda: market.search_yahoo(query)) if kind == "stock" else (lambda: market.search_coingecko(query, key))
        self.search_btn.setEnabled(False)
        self.search_btn.setText(t("hold.f.searching"))
        self._worker = TaskWorker(fn, self)
        self._worker.ok.connect(lambda rows: self._show_results(rows))
        self._worker.failed.connect(lambda msg: self._show_results([], t("hold.lookup_failed", error=msg)))
        self._worker.start()

    def _show_results(self, rows: list[dict], message: str = "") -> None:
        self.search_btn.setEnabled(True)
        self.search_btn.setText(t("hold.f.search"))
        self.results.clear()
        if not rows:
            self.results.addItem(QListWidgetItem(message or t("hold.search_empty")))
        for r in rows:
            text = f"{r['symbol']}  —  {r['name']}"
            if r.get("exchange"):
                text += f"  ({r['exchange']})"
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, r)
            self.results.addItem(it)
        self.results.show()

    def _picked(self, it: QListWidgetItem) -> None:
        r = it.data(Qt.ItemDataRole.UserRole)
        if not r:
            return
        self.symbol.setText(r["symbol"])
        if not self.name.text().strip() or self.src is None:
            self.name.setText(r["name"].split(" (")[0] if self._kind() == "crypto" else r["name"])
        self.results.hide()
        if self._kind() == "stock" and market.yfinance_available():
            sym = r["symbol"]
            self._quote_currency = guess_quote_currency(sym)
            worker = TaskWorker(lambda: market.yahoo_lookup(sym), self)
            worker.ok.connect(self._looked_up)
            worker.failed.connect(lambda _m: self._sync())
            self._worker = worker
            worker.start()
        self._sync()

    def _looked_up(self, info: dict) -> None:
        cur = info.get("currency") or ""
        if cur:
            self._quote_currency = cur
            code, _div = market.normalize_currency(cur)
            if self.src is None and code in CURRENCIES:
                self.currency.setCurrentText(code)
        self._sync()

    # ---- result ------------------------------------------------------------------------------------------
    def result_holding(self) -> Holding:
        today = self.store.today()
        h = Holding(**self.src.__dict__) if self.src else Holding(created_date=today)
        kind, source = self._kind(), self._source()
        h.kind = kind
        h.currency = self.currency.currentText()
        h.account = self.account.currentData()
        h.name = self.name.text().strip()
        h.note = self.note.text().strip()
        h.contrib_amount = round_money(self.contrib.value(), self.contrib_cur.currentText())
        h.contrib_currency = self.contrib_cur.currentText()
        h.contrib_day = self.contrib_day.value()
        h.contrib_method = self.contrib_method.currentData()
        h.last_updated = today
        if kind == "manual":
            h.symbol, h.unit, h.price_source, h.quote_currency = "", "", "manual", ""
            h.quantity = 1.0
            h.manual_price = self.manual_price.value()
            h.avg_cost = self.avg.value()
            h.adjust_pct = 0.0
            return h
        h.price_source = source
        h.quantity = self.qty.value()
        h.avg_cost = self.avg.value()
        h.manual_price = self.manual_price.value() if source == "manual" else 0.0
        if kind == "metal":
            h.symbol = self.metal.currentData()
            h.unit = self.unit.currentData()
            h.quote_currency = "USD"
            h.adjust_pct = self.adjust.value()
            if not h.name:
                h.name = label_of("metal", h.symbol)
        else:
            h.unit, h.adjust_pct = "", 0.0
            h.symbol = self.symbol.text().strip()
            if kind == "crypto":
                h.symbol = h.symbol.lower() if source == "coingecko" else h.symbol.upper()
                h.quote_currency = "JPY" if source == "bitflyer" else h.currency
            else:
                h.quote_currency = self._quote() if source == "yahoo" else ""
        return h

    def _update_preview(self) -> None:
        try:
            h = self.result_holding()
        except Exception:
            return
        st = self.store.state()
        hv = invest.value_holding(h, st.prices, self.store.rates, h.currency)
        cost = money(hv.cost, h.currency)
        if hv.value is not None:
            self.preview.setText(t("hold.preview", value=money(hv.value, h.currency), cost=cost))
        else:
            self.preview.setText(t("hold.preview_later"))
        self.preview.setProperty("tone", "")
        repolish(self.preview)

    def validate(self) -> bool:
        self.clear_errors(self.symbol, self.name)
        kind, source = self._kind(), self._source()
        if kind in ("stock", "crypto") and source != "manual" and not self.symbol.text().strip():
            self.fail(t("hold.err.symbol"), self.symbol)
            return False
        if kind == "crypto" and source == "bitflyer" and \
                self.symbol.text().strip().upper() not in market.BITFLYER_PRODUCTS:
            self.fail(t("hold.bitflyer_hint"), self.symbol)
            return False
        if kind in ("manual",) or (kind in ("stock", "crypto") and source == "manual"):
            if not self.name.text().strip() and not self.symbol.text().strip():
                self.fail(t("hold.err.name"), self.name)
                return False
        if kind == "stock" and source == "yahoo" and not self._quote():
            self.fail(t("hold.err.quote"), self.symbol)
            return False
        return True


# ---------------------------------------------------------------------------------------------------
class TradeDialog(FormDialog):
    """Record a buy, a sale, a dividend or a fee for one holding (I4)."""

    def __init__(self, parent: QWidget | None, holding: Holding, today: date, unit_price: float | None):
        super().__init__(t("trade.title", name=holding.label), parent, ok_text=t("trade.ok"))
        self.h = holding
        manual = holding.kind == "manual"
        self.kind = QComboBox()
        for code in TRADE_KINDS:
            key = f"trade.m.{code}" if manual and code in ("buy", "sell") else f"trade.{code}"
            self.kind.addItem(t(key), code)
        self.date = DateField(today)
        self.qty = qty_spin(holding.kind)
        self.price = MoneySpin(holding.currency)
        if unit_price:
            self.price.setValue(round(unit_price, max(2, decimals(holding.currency))))
        self.fee = MoneySpin(holding.currency)
        self.amount = MoneySpin(holding.currency)
        self.cash = QCheckBox(t("trade.f.cash"))
        self.cash.setChecked(True)
        self.note = QLineEdit()
        self.row(t("trade.f.kind"), self.kind)
        self.row(t("trade.f.date"), self.date)
        self.row(t("trade.f.qty"), self.qty)
        self.row(t("trade.f.price"), self.price)
        self.row(t("trade.f.fee"), self.fee)
        self.row(t("trade.f.amount"), self.amount)
        self.row("", self.cash)
        self.row(t("trade.f.note"), self.note)
        self.kind.currentIndexChanged.connect(self._sync)
        for w in (self.qty, self.price, self.fee, self.amount):
            w.valueChanged.connect(self._update_preview)
        self._sync()

    def _code(self) -> str:
        return self.kind.currentData()

    def _uses_amount(self) -> bool:
        return self.h.kind == "manual" or self._code() in ("dividend", "fee")

    def _sync(self) -> None:
        amount_only = self._uses_amount()
        self.set_row_visible(self.qty, not amount_only)
        self.set_row_visible(self.price, not amount_only)
        self.set_row_visible(self.fee, not amount_only)
        self.set_row_visible(self.amount, amount_only)
        self._update_preview()

    def values(self) -> dict:
        kw = dict(cash_effect=self.cash.isChecked(), note=self.note.text().strip())
        if self._uses_amount():
            kw.update(amount=self.amount.value())
        else:
            kw.update(quantity=self.qty.value(), price=self.price.value(), fee=self.fee.value())
        return {"kind": self._code(), "trade_date": self.date.value(), **kw}

    def _update_preview(self) -> None:
        h, code, cur = self.h, self._code(), self.h.currency
        if self._uses_amount():
            text = t("trade.preview.cash", kind=self.kind.currentText(), amount=money(self.amount.value(), cur))
        else:
            res = invest.apply_trade(h.quantity, h.avg_cost, code, self.qty.value(), self.price.value(),
                                     self.fee.value())
            q = invest.QTY_DECIMALS.get(h.kind, 4)
            qb, qa = f"{h.quantity:,.{q}f}".rstrip("0").rstrip("."), f"{res.qty_after:,.{q}f}".rstrip("0").rstrip(".")
            if code == "buy":
                text = t("trade.preview.buy", amount=money(res.amount, cur), qb=qb, qa=qa,
                         ab=fmt_number(h.avg_cost, cur), aa=fmt_number(res.avg_after, cur))
            else:
                text = t("trade.preview.sell", amount=money(res.amount, cur), realized=money(res.realized, cur),
                         qb=qb, qa=qa)
        self.preview.setText(text)

    def validate(self) -> bool:
        self.clear_errors(self.qty, self.amount)
        code = self._code()
        if self._uses_amount():
            if self.amount.value() <= 0:
                self.fail(t("trade.err.amount"), self.amount)
                return False
            return True
        if self.qty.value() <= 0:
            self.fail(t("trade.err.qty"), self.qty)
            return False
        if code == "sell" and self.qty.value() > self.h.quantity + 1e-12:
            self.fail(t("trade.err.sell_more", qty=f"{self.h.quantity:g}"), self.qty)
            return False
        return True


# ---------------------------------------------------------------------------------------------------
class InvestSettingsDialog(FormDialog):
    """Expected returns for the plan (I6), start-up refresh and the optional CoinGecko key."""

    def __init__(self, parent: QWidget | None, returns: dict[str, float], auto: bool, cg_key: str):
        super().__init__(t("iset.title"), parent)
        self.form.addRow(label(t("iset.returns"), "SectionTitle"))
        self.spins: dict[str, MoneySpin] = {}
        for kind in HOLDING_KINDS:
            spin = MoneySpin("USD", allow_negative=True)
            spin.setRange(-50, 50)
            spin.setDecimals(1)
            spin.setSingleStep(0.5)
            spin.setValue(float(returns.get(kind, 0.0)))
            spin.setMaximumWidth(140)
            self.spins[kind] = spin
            self.row(label_of("kind", kind), spin)
        self.form.addRow(label(t("iset.returns_hint"), "Hint", wrap=True))
        self.auto = QCheckBox(t("iset.auto"))
        self.auto.setChecked(auto)
        self.row("", self.auto)
        self.key = QLineEdit(cg_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.row(t("iset.cg_key"), self.key, t("iset.cg_hint"))

    def values(self) -> tuple[dict[str, float], bool, str]:
        return ({k: s.value() for k, s in self.spins.items()}, self.auto.isChecked(), self.key.text().strip())

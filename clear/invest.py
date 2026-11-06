"""Investments (I1-I6, P2): valuation, trades, NISA limits. Pure Python, no Qt, no database.

Every holding keeps its own currency (the currency of its cost). Prices are quoted by
their source in the quote currency (USD per troy ounce for metals, JPY for Tokyo
shares, …) and converted with the app's rates (units per 1 USD).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .models import NISA_ACCOUNTS, Holding, Price, Trade, price_key
from .money import convert, round_money

TROY_OUNCE_G = 31.1034768
METAL_TICKERS = {"gold": "GC=F", "silver": "SI=F", "platinum": "PL=F", "palladium": "PA=F"}
OUNCES_PER_UNIT = {"oz": 1.0, "g": 1.0 / TROY_OUNCE_G, "kg": 1000.0 / TROY_OUNCE_G}
QTY_DECIMALS = {"stock": 0, "crypto": 8, "metal": 4, "manual": 0}   # shares are whole numbers
SHOW_DECIMALS = {"stock": 4, "crypto": 8, "metal": 4, "manual": 0}  # enough for any quantity already held

# Yahoo Finance exchange suffix -> currency of the quote.
SUFFIX_CURRENCY = {
    ".T": "JPY", ".SS": "CNY", ".SZ": "CNY", ".SI": "SGD", ".HK": "HKD", ".L": "GBp", ".DE": "EUR", ".F": "EUR",
    ".PA": "EUR", ".AS": "EUR", ".MI": "EUR", ".MC": "EUR", ".TO": "CAD", ".AX": "AUD", ".KS": "KRW", ".TW": "TWD",
}
TSE_CODE = re.compile(r"^\d[0-9A-Z]\d[0-9A-Z]$")   # Tokyo Stock Exchange codes: 7203, 130A

# Tickers people type for crypto-assets -> CoinGecko ids.
CRYPTO_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "SOL": "solana", "ADA": "cardano", "DOGE": "dogecoin",
    "LTC": "litecoin", "DOT": "polkadot", "XLM": "stellar", "LINK": "chainlink", "AVAX": "avalanche-2",
    "TRX": "tron", "BNB": "binancecoin", "BCH": "bitcoin-cash", "ETC": "ethereum-classic", "ATOM": "cosmos",
    "SHIB": "shiba-inu", "MONA": "monacoin", "USDT": "tether", "USDC": "usd-coin", "TON": "the-open-network",
    "NEAR": "near", "UNI": "uniswap", "XTZ": "tezos", "XEM": "nem", "XYM": "symbol", "IOST": "iostoken",
    "ENJ": "enjincoin", "QTUM": "qtum", "BAT": "basic-attention-token", "SAND": "the-sandbox",
    "MANA": "decentraland", "APT": "aptos", "SUI": "sui", "ARB": "arbitrum", "OP": "optimism",
    "POL": "polygon-ecosystem-token", "FIL": "filecoin", "ALGO": "algorand", "HBAR": "hedera-hashgraph",
}
COIN_TICKERS = {coin: ticker for ticker, coin in CRYPTO_IDS.items()}


def yahoo_symbol(symbol: str) -> str:
    """Yahoo's form of a share code: upper case, and a Tokyo code (7203, 130A) gets ".T"."""
    s = (symbol or "").strip().upper()
    return f"{s}.T" if TSE_CODE.match(s) else s


def quote_currency_for(symbol: str, known: str = "") -> str:
    """Currency of a Yahoo quote: from the exchange suffix, else what a lookup said, else USD for a plain
    US ticker ("" when it cannot be told)."""
    sym = yahoo_symbol(symbol)
    for suffix, cur in SUFFIX_CURRENCY.items():
        if sym.endswith(suffix.upper()):
            return cur
    if known:
        return known
    if not sym:
        return ""
    if sym.endswith("=F"):
        return "USD"
    return "USD" if "." not in sym and not sym.startswith("^") else ""


def coingecko_id(symbol: str) -> str:
    """CoinGecko's id for what was typed: "BTC" or "btc" -> "bitcoin"; an id is kept as it is."""
    s = (symbol or "").strip()
    return CRYPTO_IDS.get(s.upper(), s.lower())


def bitflyer_product(symbol: str) -> str:
    """bitFlyer's product code: "btc" -> "BTC_JPY"."""
    s = (symbol or "").strip().upper()
    return s if "_" in s or not s else f"{s}_JPY"


def quantity_text(kind: str, quantity: float) -> str:
    """A quantity without trailing zeros: 100, 0.052, 120.5."""
    places = SHOW_DECIMALS.get(kind, 4)
    text = f"{quantity:,.{places}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"

# NISA (from 2024): yearly limits per frame and the lifetime limit (book value), in yen.
NISA_YEAR_LIMIT = {"nisa_tsumitate": 1_200_000, "nisa_growth": 2_400_000}
NISA_LIFETIME = 18_000_000
NISA_LIFETIME_GROWTH = 12_000_000

STALE_DAYS = 7
DEFAULT_RETURNS = {"stock": 0.0, "crypto": 0.0, "metal": 0.0, "manual": 0.0}


def quote_ref(h: Holding) -> tuple[str, str] | None:
    """(source, symbol) of the price used for the holding, or None when it is valued by hand."""
    if h.is_manual:
        return None
    if h.kind == "metal":
        ticker = METAL_TICKERS.get(h.symbol)
        return ("yahoo", ticker) if ticker else None
    if not h.symbol:
        return None
    if h.price_source == "coingecko":
        return ("coingecko", f"{coingecko_id(h.symbol)}@{h.currency.lower()}")
    if h.price_source == "bitflyer":
        return ("bitflyer", bitflyer_product(h.symbol))
    return ("yahoo", yahoo_symbol(h.symbol))


def parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def has_rate(currency: str, rates: dict) -> bool:
    try:
        return currency == "USD" or float(rates.get(currency, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def unit_price(h: Holding, price: Price | None, rates: dict) -> tuple[float | None, float | None, str]:
    """(price per holding unit in the holding currency, previous close likewise, status)."""
    if h.is_manual:
        return (h.manual_price if h.manual_price > 0 else None), None, "manual"
    if price is None or price.price <= 0:
        return None, None, "missing"
    if not has_rate(price.currency, rates) or not has_rate(h.currency, rates):
        return None, None, "no_fx"
    factor = OUNCES_PER_UNIT.get(h.unit or "g", 1.0) if h.kind == "metal" else 1.0
    adjust = 1.0 + (h.adjust_pct / 100.0 if h.kind == "metal" else 0.0)

    def cv(v: float) -> float:
        return convert(v * factor * adjust, price.currency, h.currency, rates)

    prev = cv(price.prev_close) if price.prev_close and price.prev_close > 0 else None
    return cv(price.price), prev, "ok"


@dataclass
class HoldingValue:
    holding: Holding
    unit_price: float | None = None      # per unit, holding currency
    prev_price: float | None = None
    value: float | None = None           # holding currency
    cost: float = 0.0
    gain: float | None = None
    gain_pct: float | None = None
    day_change: float | None = None
    value_t: float | None = None         # display currency
    cost_t: float = 0.0
    gain_t: float | None = None
    day_change_t: float | None = None
    status: str = "missing"              # ok | stale | missing | no_fx | manual
    fetched_at: datetime | None = None
    source: str = ""


def value_holding(h: Holding, prices: dict[str, Price], rates: dict, target: str,
                  now: datetime | None = None) -> HoldingValue:
    now = now or datetime.now()
    ref = quote_ref(h)
    price = prices.get(price_key(*ref)) if ref else None
    up, prev, status = unit_price(h, price, rates)
    hv = HoldingValue(h, up, prev, status=status, source=ref[0] if ref else "manual")
    qty = h.quantity if h.kind != "manual" else 1.0
    hv.cost = qty * h.avg_cost if h.kind != "manual" else h.avg_cost
    hv.cost_t = convert(hv.cost, h.currency, target, rates)
    if price is not None:
        hv.fetched_at = parse_time(price.fetched_at)
    if up is None:
        return hv
    hv.value = qty * up
    hv.value_t = convert(hv.value, h.currency, target, rates)
    if hv.cost > 0:
        hv.gain = hv.value - hv.cost
        hv.gain_pct = hv.gain / hv.cost
        hv.gain_t = hv.value_t - hv.cost_t
    if prev is not None:
        hv.day_change = qty * (up - prev)
        hv.day_change_t = convert(hv.day_change, h.currency, target, rates)
    if status == "ok" and hv.fetched_at is not None and (now - hv.fetched_at).days >= STALE_DAYS:
        hv.status = "stale"
    return hv


@dataclass
class PortfolioSummary:
    rows: list[HoldingValue] = field(default_factory=list)
    value: float = 0.0                   # display currency, holdings with a value
    cost: float = 0.0                    # cost of the holdings with a value and a cost
    gain: float = 0.0
    day_change: float = 0.0
    has_day_change: bool = False
    by_kind: dict[str, float] = field(default_factory=dict)
    by_account: dict[str, float] = field(default_factory=dict)
    by_currency: dict[str, float] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)   # holdings without a usable price
    stale: list[str] = field(default_factory=list)
    contrib_month: float = 0.0           # planned monthly contributions, display currency
    last_fetch: datetime | None = None

    @property
    def gain_pct(self) -> float | None:
        return self.gain / self.cost if self.cost > 0 else None


def summarize(holdings: list[Holding], prices: dict[str, Price], rates: dict, target: str,
              now: datetime | None = None) -> PortfolioSummary:
    s = PortfolioSummary()
    for h in holdings:
        hv = value_holding(h, prices, rates, target, now)
        s.rows.append(hv)
        if h.has_contribution:
            s.contrib_month += convert(h.contrib_amount, h.contrib_currency, target, rates)
        if hv.fetched_at is not None and (s.last_fetch is None or hv.fetched_at > s.last_fetch):
            s.last_fetch = hv.fetched_at
        if hv.value_t is None:
            if h.quantity > 0 or h.kind == "manual":
                s.missing.append(h.label)
            continue
        if hv.status == "stale":
            s.stale.append(h.label)
        s.value += hv.value_t
        if hv.gain_t is not None:
            s.cost += hv.cost_t
            s.gain += hv.gain_t
        if hv.day_change_t is not None:
            s.day_change += hv.day_change_t
            s.has_day_change = True
        s.by_kind[h.kind] = s.by_kind.get(h.kind, 0.0) + hv.value_t
        s.by_account[h.account] = s.by_account.get(h.account, 0.0) + hv.value_t
        s.by_currency[h.currency] = s.by_currency.get(h.currency, 0.0) + hv.value_t
    return s


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------
@dataclass
class TradeResult:
    qty_after: float
    avg_after: float
    realized: float
    amount: float


def apply_trade(qty: float, avg: float, kind: str, quantity: float = 0.0, price: float = 0.0,
                fee: float = 0.0, amount: float = 0.0) -> TradeResult:
    """New quantity and average cost after a trade (moving average, fees go into the cost)."""
    fee = max(0.0, fee)
    if kind == "buy":
        q = max(0.0, quantity)
        cash = q * price + fee
        new_qty = qty + q
        new_avg = (qty * avg + cash) / new_qty if new_qty > 0 else 0.0
        return TradeResult(new_qty, new_avg, 0.0, cash)
    if kind == "sell":
        q = max(0.0, min(quantity, qty))
        cash = q * price - fee
        realized = q * (price - avg) - fee
        new_qty = qty - q
        return TradeResult(new_qty, avg if new_qty > 1e-12 else 0.0, realized, cash)
    # dividend / fee: the position does not change
    return TradeResult(qty, avg, 0.0, max(0.0, amount))


def round_qty(kind: str, quantity: float) -> float:
    return round(float(quantity), QTY_DECIMALS.get(kind, 8))


def units_for(kind: str, amount: float, price: float) -> float:
    """What an amount buys at a price, rounded down to what can be held (whole shares)."""
    if price <= 0 or amount <= 0:
        return 0.0
    factor = 10 ** QTY_DECIMALS.get(kind, 8)
    return math.floor(amount / price * factor + 1e-9) / factor


# ---------------------------------------------------------------------------
# NISA (P2)
# ---------------------------------------------------------------------------
@dataclass
class NisaUsage:
    year: int
    year_used: dict[str, float] = field(default_factory=dict)     # frame -> yen bought this year
    lifetime_used: float = 0.0                                      # book value of NISA holdings
    lifetime_growth: float = 0.0

    def year_left(self, frame: str) -> float:
        return NISA_YEAR_LIMIT[frame] - self.year_used.get(frame, 0.0)

    @property
    def over(self) -> list[str]:
        out = [f for f, limit in NISA_YEAR_LIMIT.items() if self.year_used.get(f, 0.0) > limit + 0.5]
        if self.lifetime_used > NISA_LIFETIME + 0.5:
            out.append("lifetime")
        if self.lifetime_growth > NISA_LIFETIME_GROWTH + 0.5:
            out.append("lifetime_growth")
        return out


def nisa_usage(holdings: list[Holding], trades: list[Trade], year: int, rates: dict) -> NisaUsage:
    u = NisaUsage(year)
    for tr in trades:
        if tr.kind != "buy" or tr.account not in NISA_ACCOUNTS or tr.trade_date is None or tr.trade_date.year != year:
            continue
        spent = tr.quantity * tr.price if tr.quantity > 0 and tr.price > 0 else tr.amount - tr.fee
        u.year_used[tr.account] = u.year_used.get(tr.account, 0.0) + convert(spent, tr.currency, "JPY", rates)
    for h in holdings:
        if not h.is_nisa:
            continue
        cost = h.avg_cost if h.kind == "manual" else h.quantity * h.avg_cost
        book = convert(cost, h.currency, "JPY", rates)
        u.lifetime_used += book
        if h.account == "nisa_growth":
            u.lifetime_growth += book
    return u


def uses_nisa(holdings: list[Holding]) -> bool:
    return any(h.is_nisa for h in holdings)


# ---------------------------------------------------------------------------
# Contributions (I5)
# ---------------------------------------------------------------------------
def contribution_in_holding_currency(h: Holding, rates: dict) -> float:
    return round_money(convert(h.contrib_amount, h.contrib_currency, h.currency, rates), h.currency)


def contribution_due(h: Holding, period, today: date) -> date:
    return period.day(h.contrib_day)

"""Market prices and exchange rates (I2), fetched for free.

* Shares, ETFs, precious metals (New York futures) and exchange rates: Yahoo Finance
  through the ``yfinance`` library (optional dependency; personal use only).
* Crypto-assets: CoinGecko (no key needed; a free "Demo" key gives steadier limits).
* Crypto-assets at a Japanese exchange (optional): bitFlyer's public API.

All symbols are fetched in one go and every source is wrapped on its own, so one
failure never hides the prices that did arrive. Nothing here touches Qt; the Store
runs ``refresh`` in a worker thread and keeps the last good values.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from datetime import datetime

from .info import APP_NAME, APP_VERSION
from .models import Price

log = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3"
BITFLYER_URL = "https://api.bitflyer.com/v1"
BITFLYER_PRODUCTS = ("BTC_JPY", "ETH_JPY", "XRP_JPY", "XLM_JPY", "MONA_JPY")
TIMEOUT = 10.0
MIN_INTERVAL_MINUTES = 15
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"

# Quotes in a currency's sub-unit (pence, cents, agorot) -> (currency, divisor)
SUB_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def now_text() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def yfinance_available() -> bool:
    """True when yfinance is installed (checked without importing it: pandas is slow to load)."""
    try:
        return importlib.util.find_spec("yfinance") is not None
    except (ImportError, ValueError):
        return False


def normalize_currency(currency: str | None) -> tuple[str, float]:
    """(ISO currency, divisor) for a currency code as Yahoo reports it."""
    code = (currency or "").strip()
    if code in SUB_UNITS:
        return SUB_UNITS[code]
    return code.upper(), 1.0


# ---------------------------------------------------------------------------
# Request / result
# ---------------------------------------------------------------------------
@dataclass
class MarketRequest:
    yahoo: dict[str, str] = field(default_factory=dict)          # ticker -> quote currency
    fx: list[str] = field(default_factory=list)                  # currencies to get per 1 USD
    coingecko: dict[str, set[str]] = field(default_factory=dict)  # vs currency (lower case) -> coin ids
    bitflyer: list[str] = field(default_factory=list)            # product codes
    coingecko_key: str = ""

    @property
    def empty(self) -> bool:
        return not (self.yahoo or self.fx or self.coingecko or self.bitflyer)


@dataclass
class MarketResult:
    prices: list[Price] = field(default_factory=list)
    fx: dict[str, float] = field(default_factory=dict)           # units per 1 USD
    errors: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)             # symbols asked for but not returned
    fetched_at: str = ""


# ---------------------------------------------------------------------------
# Yahoo Finance (yfinance)
# ---------------------------------------------------------------------------
def _closes(df, symbols: list[str]) -> dict[str, list[float]]:
    """Closing prices per ticker from a ``yfinance.download`` frame (any column layout)."""
    out: dict[str, list[float]] = {}
    if df is None or getattr(df, "empty", True):
        return out
    cols = df.columns
    if getattr(cols, "nlevels", 1) > 1:
        level0 = set(cols.get_level_values(0))
        if "Close" in level0:
            close = df["Close"]
        else:
            close = df.xs("Close", axis=1, level=1)
        for sym in symbols:
            if sym in close.columns:
                vals = [float(v) for v in close[sym].tolist() if v == v and v is not None]
                if vals:
                    out[sym] = vals
    elif "Close" in cols and len(symbols) == 1:
        vals = [float(v) for v in df["Close"].tolist() if v == v and v is not None]
        if vals:
            out[symbols[0]] = vals
    return out


def fetch_yahoo(symbols: list[str], timeout: float = TIMEOUT, downloader=None) -> dict[str, tuple[float, float | None]]:
    """Last price and previous close per ticker. Tickers without data are left out."""
    symbols = sorted({s for s in symbols if s})
    if not symbols:
        return {}
    if downloader is None:
        import yfinance as yf
        downloader = yf.download
    df = downloader(symbols, period="5d", interval="1d", group_by="column", auto_adjust=False,
                    progress=False, threads=True, timeout=timeout)
    out: dict[str, tuple[float, float | None]] = {}
    for sym, vals in _closes(df, symbols).items():
        last = vals[-1]
        prev = vals[-2] if len(vals) >= 2 else None
        if last > 0:
            out[sym] = (last, prev)
    return out


def search_yahoo(query: str, limit: int = 8, timeout: float = TIMEOUT) -> list[dict]:
    """Candidates for a code or a name: [{symbol, name, exchange, kind}]."""
    import yfinance as yf

    res = yf.Search(query, max_results=limit, news_count=0, lists_count=0, include_cb=False, recommended=0,
                    timeout=timeout, raise_errors=False)
    out = []
    for q in (getattr(res, "quotes", None) or [])[:limit]:
        sym = q.get("symbol")
        if not sym:
            continue
        out.append({"symbol": sym, "name": q.get("shortname") or q.get("longname") or sym,
                    "exchange": q.get("exchDisp") or q.get("exchange") or "",
                    "kind": q.get("typeDisp") or q.get("quoteType") or ""})
    return out


def yahoo_lookup(symbol: str) -> dict:
    """Currency and last price of one ticker: {symbol, currency, price}."""
    import yfinance as yf

    fi = yf.Ticker(symbol).fast_info
    currency = fi.currency
    try:
        price = fi.last_price
    except Exception:  # the currency is what matters; the price comes with the next refresh
        price = None
    code, div = normalize_currency(currency)
    return {"symbol": symbol, "currency": code, "price": (float(price) / div) if price else None}


# ---------------------------------------------------------------------------
# CoinGecko
# ---------------------------------------------------------------------------
def _session():
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _cg_headers(api_key: str) -> dict:
    return {"x-cg-demo-api-key": api_key} if api_key else {}


def fetch_coingecko(by_vs: dict[str, set[str]], api_key: str = "", timeout: float = TIMEOUT,
                    session=None) -> dict[tuple[str, str], tuple[float, float | None]]:
    """(coin id, vs currency) -> (price, previous price 24 h ago)."""
    ids = sorted({i for coins in by_vs.values() for i in coins if i})
    vs = sorted({v.lower() for v in by_vs if v})
    if not ids or not vs:
        return {}
    s = session or _session()
    resp = s.get(f"{COINGECKO_URL}/simple/price", timeout=timeout, headers=_cg_headers(api_key),
                 params={"ids": ",".join(ids), "vs_currencies": ",".join(vs), "include_24hr_change": "true"})
    resp.raise_for_status()
    data = resp.json() or {}
    out: dict[tuple[str, str], tuple[float, float | None]] = {}
    for coin, values in data.items():
        if not isinstance(values, dict):
            continue
        for v in vs:
            price = values.get(v)
            if not price:
                continue
            change = values.get(f"{v}_24h_change")
            prev = float(price) / (1 + float(change) / 100.0) if change not in (None, -100) else None
            out[(coin, v)] = (float(price), prev)
    return out


def search_coingecko(query: str, api_key: str = "", timeout: float = TIMEOUT, session=None) -> list[dict]:
    s = session or _session()
    resp = s.get(f"{COINGECKO_URL}/search", timeout=timeout, headers=_cg_headers(api_key), params={"query": query})
    resp.raise_for_status()
    coins = (resp.json() or {}).get("coins") or []
    return [{"symbol": c.get("id"), "name": f"{c.get('name')} ({str(c.get('symbol') or '').upper()})",
             "exchange": "CoinGecko", "kind": "crypto"} for c in coins[:8] if c.get("id")]


# ---------------------------------------------------------------------------
# bitFlyer
# ---------------------------------------------------------------------------
def fetch_bitflyer(products: list[str], timeout: float = TIMEOUT, session=None) -> dict[str, float]:
    s = session or _session()
    out: dict[str, float] = {}
    for code in sorted({p.upper() for p in products if p}):
        resp = s.get(f"{BITFLYER_URL}/getticker", timeout=timeout, params={"product_code": code})
        resp.raise_for_status()
        ltp = (resp.json() or {}).get("ltp")
        if ltp:
            out[code] = float(ltp)
    return out


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------
def refresh(req: MarketRequest, timeout: float = TIMEOUT) -> MarketResult:
    res = MarketResult(fetched_at=now_text())
    stamp = res.fetched_at

    fx_tickers = {f"{cur}=X": cur for cur in req.fx if cur and cur != "USD"}
    yahoo_syms = list(req.yahoo) + list(fx_tickers)
    if yahoo_syms:
        if not yfinance_available():
            res.errors.append("yfinance")
            res.missing.extend(req.yahoo)
        else:
            try:
                quotes = fetch_yahoo(yahoo_syms, timeout)
            except Exception as exc:
                log.warning("Yahoo Finance failed: %s", exc)
                res.errors.append(f"Yahoo Finance: {exc}")
                quotes = {}
            for sym, cur in req.yahoo.items():
                if sym not in quotes:
                    res.missing.append(sym)
                    continue
                last, prev = quotes[sym]
                code, div = normalize_currency(cur)
                res.prices.append(Price("yahoo", sym, last / div, code, (prev / div) if prev else None, stamp))
            for ticker, cur in fx_tickers.items():
                if ticker in quotes and quotes[ticker][0] > 0:
                    res.fx[cur] = quotes[ticker][0]

    if req.coingecko:
        try:
            quotes = fetch_coingecko(req.coingecko, req.coingecko_key, timeout)
        except Exception as exc:
            log.warning("CoinGecko failed: %s", exc)
            res.errors.append(f"CoinGecko: {exc}")
            quotes = {}
        for vs, coins in req.coingecko.items():
            for coin in coins:
                q = quotes.get((coin, vs.lower()))
                if q is None:
                    res.missing.append(coin)
                    continue
                res.prices.append(Price("coingecko", f"{coin}@{vs.lower()}", q[0], vs.upper(), q[1], stamp))

    if req.bitflyer:
        try:
            quotes_bf = fetch_bitflyer(req.bitflyer, timeout)
        except Exception as exc:
            log.warning("bitFlyer failed: %s", exc)
            res.errors.append(f"bitFlyer: {exc}")
            quotes_bf = {}
        for code in req.bitflyer:
            if code.upper() in quotes_bf:
                res.prices.append(Price("bitflyer", code.upper(), quotes_bf[code.upper()], "JPY", None, stamp))
            else:
                res.missing.append(code)
    return res

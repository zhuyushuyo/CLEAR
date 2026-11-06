"""Market prices and exchange rates (I2), fetched for free, with fallbacks.

Each kind of price has a chain of sources. What the first source does not return is
asked of the next one, so one failing service never leaves the prices empty:

* Shares, ETFs, precious metals (New York futures) and exchange rates
  1. yfinance (Yahoo Finance), when it is installed
  2. Yahoo Finance's public chart API, called directly (works without yfinance)
  3. exchange rates only: ExchangeRate-API
* Crypto-assets
  1. CoinGecko (no key needed; a free "Demo" key gives steadier limits)
  2. Coinbase's public spot price (main coins)
  3. bitFlyer's public ticker (main coins, in yen)

Only codes are sent (tickers, coin ids, currencies), never balances. Nothing here
touches Qt; the Store runs ``refresh`` in a worker thread and keeps the last good values.
"""

from __future__ import annotations

import importlib.util
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote as url_quote

from .info import APP_NAME, APP_VERSION
from .invest import COIN_TICKERS
from .models import Price

log = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3"
COINBASE_URL = "https://api.coinbase.com/v2/prices/{pair}/spot"
BITFLYER_URL = "https://api.bitflyer.com/v1"
BITFLYER_PRODUCTS = ("BTC_JPY", "ETH_JPY", "XRP_JPY", "XLM_JPY", "MONA_JPY")
YAHOO_CHART_URLS = ("https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                    "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}")
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
TIMEOUT = 10.0
MIN_INTERVAL_MINUTES = 15
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
BROWSER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
                 "Chrome/131.0.0.0 Safari/537.36")

# Quotes in a currency's sub-unit (pence, cents, agorot) -> (currency, divisor)
SUB_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


class RateLimited(Exception):
    """The service answered "too many requests"."""


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
class SourceError:
    source: str               # "Yahoo Finance", "CoinGecko", …
    kind: str                 # "rate_limit" | "connection" | "error"
    detail: str = ""


@dataclass
class MarketResult:
    prices: list[Price] = field(default_factory=list)
    fx: dict[str, float] = field(default_factory=dict)           # units per 1 USD
    errors: list[SourceError] = field(default_factory=list)      # sources that failed and left gaps
    missing: list[str] = field(default_factory=list)             # codes no source returned
    used: list[str] = field(default_factory=list)                # sources that answered
    fx_source: str = ""                                          # "yahoo" or "auto" (ExchangeRate-API)
    fetched_at: str = ""

    @property
    def ok(self) -> bool:
        return not self.missing and not self.errors


def classify(source: str, exc: BaseException) -> SourceError:
    """Turn an exception into something a person can act on."""
    name, text = type(exc).__name__, str(exc)
    low = text.lower()
    if isinstance(exc, RateLimited) or "ratelimit" in name.lower() or "429" in text or "too many requests" in low:
        return SourceError(source, "rate_limit")
    if any(k in name for k in ("Timeout", "ConnectionError", "ProxyError", "SSLError")) or any(
            k in low for k in ("timed out", "failed to establish", "name resolution", "nodename nor servname",
                               "connection refused", "network is unreachable", "could not resolve")):
        return SourceError(source, "connection", text[:160])
    return SourceError(source, "error", text[:160])


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _session():
    import requests

    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _browser_session():
    """Yahoo answers browsers more readily: curl_cffi (installed with yfinance) imitates one,
    plain requests with a browser's name otherwise."""
    try:
        from curl_cffi import requests as cffi_requests  # type: ignore

        return cffi_requests.Session(impersonate="chrome")
    except Exception:
        s = _session()
        s.headers["User-Agent"] = BROWSER_AGENT
        return s


# ---------------------------------------------------------------------------
# Yahoo Finance: yfinance, then the chart API directly
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
    """Last price and previous close per ticker through yfinance. Tickers without data are left out."""
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


def parse_chart(data: dict) -> tuple[float, float | None, str, str] | None:
    """(last price, previous close, currency, name) from a chart API answer; None without a price."""
    result = ((data or {}).get("chart") or {}).get("result") or []
    if not result:
        return None
    first = result[0] or {}
    meta = first.get("meta") or {}
    quotes = ((first.get("indicators") or {}).get("quote") or [{}])[0] or {}
    closes = [float(c) for c in (quotes.get("close") or []) if c is not None]
    last = meta.get("regularMarketPrice") or (closes[-1] if closes else None)
    if not last or float(last) <= 0:
        return None
    prev = closes[-2] if len(closes) >= 2 else None
    name = meta.get("longName") or meta.get("shortName") or ""
    return float(last), prev, str(meta.get("currency") or ""), str(name)


def _chart(s, symbol: str, timeout: float) -> dict | None:
    """One chart API answer (None for an unknown code). Raises RateLimited on 429."""
    for url in YAHOO_CHART_URLS:
        resp = s.get(url.format(symbol=url_quote(symbol, safe="")), params={"range": "5d", "interval": "1d"},
                     timeout=timeout)
        if resp.status_code == 429:
            raise RateLimited("Yahoo Finance")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 500:
            continue  # the other host may answer
        resp.raise_for_status()
        return resp.json()
    return None


def fetch_yahoo_chart(symbols: list[str], timeout: float = TIMEOUT, session=None,
                      pause: float = 0.3) -> dict[str, tuple[float, float | None, str]]:
    """(last, previous close, currency) per ticker from Yahoo's chart API, without yfinance."""
    s = session or _browser_session()
    out: dict[str, tuple[float, float | None, str]] = {}
    for i, sym in enumerate(sorted({x for x in symbols if x})):
        if i and pause:
            time.sleep(pause)  # well under Yahoo's burst limit
        parsed = parse_chart(_chart(s, sym, timeout) or {})
        if parsed is not None:
            out[sym] = parsed[:3]
    return out


def search_yahoo(query: str, limit: int = 8, timeout: float = TIMEOUT, session=None) -> list[dict]:
    """Candidates for a code or a name: [{symbol, name, exchange, kind}] (yfinance, else Yahoo directly)."""
    quotes = None
    if session is None and yfinance_available():
        try:
            import yfinance as yf

            res = yf.Search(query, max_results=limit, news_count=0, lists_count=0, include_cb=False, recommended=0,
                            timeout=timeout, raise_errors=False)
            quotes = getattr(res, "quotes", None)
        except Exception as exc:
            log.info("yfinance search failed, asking Yahoo directly: %s", exc)
    if not quotes:
        s = session or _browser_session()
        resp = s.get(YAHOO_SEARCH_URL, timeout=timeout,
                     params={"q": query, "quotesCount": limit, "newsCount": 0, "listsCount": 0})
        if resp.status_code == 429:
            raise RateLimited("Yahoo Finance")
        resp.raise_for_status()
        quotes = (resp.json() or {}).get("quotes") or []
    out = []
    for q in quotes[:limit]:
        sym = q.get("symbol")
        if not sym:
            continue
        out.append({"symbol": sym, "name": q.get("shortname") or q.get("longname") or sym,
                    "exchange": q.get("exchDisp") or q.get("exchange") or "",
                    "kind": q.get("typeDisp") or q.get("quoteType") or ""})
    return out


def yahoo_lookup(symbol: str, timeout: float = TIMEOUT, session=None) -> dict:
    """Currency and last price of one ticker: {symbol, currency, price, name}."""
    if session is None and yfinance_available():
        try:
            import yfinance as yf

            fi = yf.Ticker(symbol).fast_info
            currency = fi.currency
            try:
                price = fi.last_price
            except Exception:  # the currency is what matters; the price comes with the next refresh
                price = None
            if currency:
                code, div = normalize_currency(currency)
                return {"symbol": symbol, "currency": code, "price": (float(price) / div) if price else None,
                        "name": ""}
        except Exception as exc:
            log.info("yfinance lookup failed, asking Yahoo directly: %s", exc)
    parsed = parse_chart(_chart(session or _browser_session(), symbol, timeout) or {})
    if parsed is None:
        raise LookupError(symbol)
    last, _prev, currency, name = parsed
    code, div = normalize_currency(currency)
    return {"symbol": symbol, "currency": code, "price": last / div, "name": name}


# ---------------------------------------------------------------------------
# Crypto-assets: CoinGecko, then Coinbase, then bitFlyer
# ---------------------------------------------------------------------------
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
    if resp.status_code == 429:
        raise RateLimited("CoinGecko")
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
    if resp.status_code == 429:
        raise RateLimited("CoinGecko")
    resp.raise_for_status()
    coins = (resp.json() or {}).get("coins") or []
    return [{"symbol": c.get("id"), "name": f"{c.get('name')} ({str(c.get('symbol') or '').upper()})",
             "exchange": "CoinGecko", "kind": "crypto"} for c in coins[:8] if c.get("id")]


def fetch_coinbase(wanted: dict[str, set[str]], timeout: float = TIMEOUT, session=None,
                   pause: float = 0.2) -> dict[tuple[str, str], float]:
    """(coin id, vs currency) -> spot price, for the coins Coinbase lists (no key needed)."""
    s = session or _session()
    out: dict[tuple[str, str], float] = {}
    first = True
    for vs, coins in sorted(wanted.items()):
        for coin in sorted(coins):
            ticker = COIN_TICKERS.get(coin)
            if not ticker:
                continue
            if not first and pause:
                time.sleep(pause)
            first = False
            resp = s.get(COINBASE_URL.format(pair=f"{ticker}-{vs.upper()}"), timeout=timeout)
            if resp.status_code == 429:
                raise RateLimited("Coinbase")
            if resp.status_code != 200:
                continue
            amount = float(((resp.json() or {}).get("data") or {}).get("amount") or 0)
            if amount > 0:
                out[(coin, vs.lower())] = amount
    return out


def fetch_bitflyer(products: list[str], timeout: float = TIMEOUT, session=None) -> dict[str, float]:
    s = session or _session()
    out: dict[str, float] = {}
    for code in sorted({p.upper() for p in products if p}):
        resp = s.get(f"{BITFLYER_URL}/getticker", timeout=timeout, params={"product_code": code})
        if resp.status_code == 429:
            raise RateLimited("bitFlyer")
        resp.raise_for_status()
        ltp = (resp.json() or {}).get("ltp")
        if ltp:
            out[code] = float(ltp)
    return out


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------
def _yahoo_prices(req: MarketRequest, res: MarketResult, timeout: float) -> None:
    fx_tickers = {f"{cur}=X": cur for cur in req.fx if cur and cur != "USD"}
    wanted = list(req.yahoo) + list(fx_tickers)
    if not wanted:
        return
    quotes: dict[str, tuple[float, float | None, str]] = {}
    first_error: SourceError | None = None
    if yfinance_available():
        try:
            got = fetch_yahoo(wanted, timeout)
            quotes.update({sym: (last, prev, "") for sym, (last, prev) in got.items()})
            if got:
                res.used.append("yfinance")
        except Exception as exc:
            log.warning("yfinance failed: %s", exc)
            first_error = classify("Yahoo Finance", exc)
    rest = [sym for sym in wanted if sym not in quotes]
    if rest:
        try:
            got_chart = fetch_yahoo_chart(rest, timeout)
            quotes.update(got_chart)
            if got_chart:
                res.used.append("yahoo-chart")
        except Exception as exc:
            log.warning("Yahoo chart API failed: %s", exc)
            res.errors.append(classify("Yahoo Finance", exc))
        else:
            if first_error is not None and any(s in req.yahoo for s in rest if s not in quotes):
                res.errors.append(first_error)
    stamp = res.fetched_at
    for sym, cur in req.yahoo.items():
        q = quotes.get(sym)
        if q is None:
            res.missing.append(sym)
            continue
        last, prev, reported = q
        code, div = normalize_currency(reported or cur)
        res.prices.append(Price("yahoo", sym, last / div, code, (prev / div) if prev else None, stamp))
    for ticker, cur in fx_tickers.items():
        q = quotes.get(ticker)
        if q is not None and q[0] > 0:
            res.fx[cur] = q[0]
            res.fx_source = "yahoo"


def _fx_fallback(req: MarketRequest, res: MarketResult, timeout: float) -> None:
    missing = [c for c in req.fx if c and c != "USD" and c not in res.fx]
    if not missing:
        return
    from . import rates

    try:
        table = rates.fetch_table(timeout)
    except Exception as exc:
        log.warning("ExchangeRate-API failed: %s", exc)
        res.errors.append(classify("ExchangeRate-API", exc))
        return
    found = {c: table[c] for c in missing if table.get(c)}
    res.fx.update(found)
    if found:
        res.used.append("exchangerate-api")
        res.fx_source = res.fx_source or "auto"


def _crypto_prices(req: MarketRequest, res: MarketResult, timeout: float) -> None:
    stamp = res.fetched_at
    if req.coingecko:
        quotes: dict[tuple[str, str], tuple[float, float | None]] = {}
        try:
            quotes = fetch_coingecko(req.coingecko, req.coingecko_key, timeout)
            if quotes:
                res.used.append("coingecko")
        except Exception as exc:
            log.warning("CoinGecko failed: %s", exc)
            gecko_error = classify("CoinGecko", exc)
        else:
            gecko_error = None
        rest = {vs.lower(): {c for c in coins if (c, vs.lower()) not in quotes} for vs, coins in req.coingecko.items()}
        rest = {vs: coins for vs, coins in rest.items() if coins}
        if rest:
            try:
                spot = fetch_coinbase(rest, timeout)
                quotes.update({k: (v, None) for k, v in spot.items()})
                if spot:
                    res.used.append("coinbase")
            except Exception as exc:
                log.warning("Coinbase failed: %s", exc)
        products: dict[str, str] = {}             # bitFlyer product -> coin id, for yen prices still missing
        for coin in rest.get("jpy", set()):
            code = f"{COIN_TICKERS.get(coin, '')}_JPY"
            if (coin, "jpy") not in quotes and code in BITFLYER_PRODUCTS:
                products[code] = coin
        if products:
            try:
                ltp = fetch_bitflyer(list(products), timeout)
                quotes.update({(products[code], "jpy"): (price, None) for code, price in ltp.items()})
                if ltp:
                    res.used.append("bitflyer")
            except Exception as exc:
                log.warning("bitFlyer failed: %s", exc)
        for vs, coins in req.coingecko.items():
            for coin in coins:
                q = quotes.get((coin, vs.lower()))
                if q is None:
                    res.missing.append(coin)
                    continue
                res.prices.append(Price("coingecko", f"{coin}@{vs.lower()}", q[0], vs.upper(), q[1], stamp))
        if gecko_error is not None and any(c in res.missing for coins in req.coingecko.values() for c in coins):
            res.errors.append(gecko_error)
    if req.bitflyer:
        try:
            quotes_bf = fetch_bitflyer(req.bitflyer, timeout)
        except Exception as exc:
            log.warning("bitFlyer failed: %s", exc)
            res.errors.append(classify("bitFlyer", exc))
            quotes_bf = {}
        for code in req.bitflyer:
            if code.upper() in quotes_bf:
                res.prices.append(Price("bitflyer", code.upper(), quotes_bf[code.upper()], "JPY", None, stamp))
            else:
                res.missing.append(code)


def refresh(req: MarketRequest, timeout: float = TIMEOUT) -> MarketResult:
    res = MarketResult(fetched_at=now_text())
    _yahoo_prices(req, res, timeout)
    _fx_fallback(req, res, timeout)
    _crypto_prices(req, res, timeout)
    log.info("market sources used: %s", ", ".join(res.used) or "none")
    return res

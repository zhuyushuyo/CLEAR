"""Currencies: rounding, conversion and display formatting."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CURRENCIES = ("JPY", "USD", "CNY", "SGD")

# Units of each currency per 1 USD. Used only until the first successful update.
DEFAULT_RATES = {"USD": 1.0, "JPY": 150.0, "CNY": 7.1, "SGD": 1.3}

_SYMBOL_EN = {"JPY": "¥", "USD": "$", "CNY": "CN¥", "SGD": "S$"}
_PREFIX_JA = {"USD": "$", "SGD": "S$"}
_SUFFIX_JA = {"JPY": "円", "CNY": "元"}


def decimals(currency: str) -> int:
    return 0 if currency == "JPY" else 2


def unit(currency: str) -> float:
    """Smallest amount we keep for the currency (1 yen, 0.01 otherwise)."""
    return 1.0 if decimals(currency) == 0 else 0.01


def to_float(value: object, default: float = 0.0) -> float:
    """Parse numbers coming from the database or from user text ("1,234", None, "")."""
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("，", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def round_money(value: object, currency: str) -> float:
    """Round half-up to the currency's precision (yen: whole numbers)."""
    try:
        d = Decimal(str(to_float(value)))
    except (InvalidOperation, ValueError):
        return 0.0
    q = Decimal(1) if decimals(currency) == 0 else Decimal("0.01")
    result = float(d.quantize(q, rounding=ROUND_HALF_UP))
    return 0.0 if result == 0 else result  # avoid -0.0


def rate_of(currency: str, rates: dict | None) -> float:
    value = to_float((rates or {}).get(currency), 0.0)
    if value <= 0:
        value = DEFAULT_RATES.get(currency, 1.0)
    return value


def convert(amount: object, src: str, dst: str, rates: dict | None) -> float:
    """Convert using rates expressed as units per 1 USD."""
    value = to_float(amount)
    if value == 0 or src == dst:
        return value
    return value / rate_of(src, rates) * rate_of(dst, rates)


def fmt_number(value: object, currency: str) -> str:
    v = round_money(value, currency)
    if decimals(currency) == 0:
        return f"{int(v):,}"
    return f"{v:,.2f}"


def fmt_money(value: object, currency: str, lang: str = "ja") -> str:
    v = round_money(value, currency)
    body = fmt_number(abs(v), currency)
    if lang == "ja":
        if currency in _SUFFIX_JA:
            text = f"{body}{_SUFFIX_JA[currency]}"
        elif currency in _PREFIX_JA:
            text = f"{_PREFIX_JA[currency]}{body}"
        else:
            text = f"{body} {currency}"
    else:
        text = f"{_SYMBOL_EN[currency]}{body}" if currency in _SYMBOL_EN else f"{body} {currency}"
    return f"-{text}" if v < 0 else text


def fmt_compact(value: float, currency: str, lang: str = "ja") -> str:
    """Short axis labels: 1.2億 / 350万 (ja) or 1.2M / 350k (en)."""
    v = float(value)
    sign = "-" if v < 0 else ""
    a = abs(v)
    if lang == "ja":
        if a >= 1e8:
            return f"{sign}{a / 1e8:.1f}億".replace(".0億", "億")
        if a >= 1e4:
            n = a / 1e4
            return f"{sign}{n:,.0f}万" if n >= 10 else f"{sign}{n:.1f}万".replace(".0万", "万")
        return f"{sign}{a:,.0f}"
    if a >= 1e6:
        return f"{sign}{a / 1e6:.1f}M".replace(".0M", "M")
    if a >= 1e3:
        return f"{sign}{a / 1e3:,.0f}k"
    return f"{sign}{a:,.0f}"

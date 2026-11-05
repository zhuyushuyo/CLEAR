"""Exchange rates (F14): fetched at most once a day, with a timeout, never blocking the UI."""

from __future__ import annotations

from datetime import datetime

from .info import APP_NAME, APP_VERSION
from .money import CURRENCIES

API_URL = "https://api.exchangerate-api.com/v4/latest/USD"
TIMEOUT = 8.0
STALE_DAYS = 7


def fetch_rates(timeout: float = TIMEOUT) -> dict[str, float]:
    """Units of each supported currency per 1 USD. Raises on any network/format problem."""
    import requests  # imported lazily: only needed when updating

    resp = requests.get(API_URL, timeout=timeout, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("rates") or {}
    out = {"USD": 1.0}
    for cur in CURRENCIES:
        if cur == "USD":
            continue
        value = float(raw.get(cur, 0) or 0)
        if value <= 0:
            raise ValueError(f"rate for {cur} missing")
        out[cur] = value
    return out


def parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def age_days(updated_at: datetime | None, now: datetime | None = None) -> int | None:
    if updated_at is None:
        return None
    return max(0, ((now or datetime.now()).date() - updated_at.date()).days)


def due_for_update(updated_at: datetime | None, now: datetime | None = None) -> bool:
    return updated_at is None or updated_at.date() != (now or datetime.now()).date()

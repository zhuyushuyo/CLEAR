"""Japanese bank business days (F12).

Banks are closed on weekends, national holidays and from 31 December to 3 January.
A payment due on a closed day is taken on the next business day; a salary due on a
closed day is usually paid on the business day before.

National holidays come from the optional ``jpholiday`` package. Without it only
weekends and the New Year bank holidays are known.
"""

from __future__ import annotations

from datetime import date, timedelta

try:  # optional dependency
    import jpholiday  # type: ignore
except Exception:  # pragma: no cover - depends on the environment
    jpholiday = None

_DAY = timedelta(days=1)


def has_holiday_calendar() -> bool:
    return jpholiday is not None


def is_bank_holiday(d: date) -> bool:
    if d.weekday() >= 5:
        return True
    if (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3):
        return True
    if jpholiday is not None:
        try:
            return bool(jpholiday.is_holiday(d))
        except Exception:  # pragma: no cover - defensive
            return False
    return False


def next_business_day(d: date) -> date:
    """The day itself when banks are open, otherwise the next day they are."""
    for _ in range(14):
        if not is_bank_holiday(d):
            return d
        d += _DAY
    return d


def prev_business_day(d: date) -> date:
    for _ in range(14):
        if not is_bank_holiday(d):
            return d
        d -= _DAY
    return d

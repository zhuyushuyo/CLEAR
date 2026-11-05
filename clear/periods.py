"""Calendar months ("periods") used for billing, ledgers and month-end close."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, order=True)
class Period:
    """A calendar month, e.g. Period(2026, 11). Ordered chronologically."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if not 1 <= int(self.month) <= 12:
            raise ValueError(f"month out of range: {self.month}")
        if not 1900 <= int(self.year) <= 9999:
            raise ValueError(f"year out of range: {self.year}")

    # ---- construction -------------------------------------------------
    @classmethod
    def from_date(cls, d: date) -> "Period":
        return cls(d.year, d.month)

    @classmethod
    def parse(cls, text: str) -> "Period":
        parts = str(text).strip().replace("/", "-").split("-")
        if len(parts) < 2:
            raise ValueError(f"not a period: {text!r}")
        return cls(int(parts[0]), int(parts[1]))

    @classmethod
    def try_parse(cls, text: object) -> "Period | None":
        if text is None:
            return None
        try:
            return cls.parse(str(text))
        except (ValueError, TypeError):
            return None

    # ---- arithmetic ---------------------------------------------------
    def add(self, months: int) -> "Period":
        index = self.year * 12 + (self.month - 1) + int(months)
        return Period(index // 12, index % 12 + 1)

    def months_until(self, other: "Period") -> int:
        """Number of months from self to other (other - self)."""
        return (other.year - self.year) * 12 + (other.month - self.month)

    # ---- days -----------------------------------------------------------
    @property
    def days_in_month(self) -> int:
        return calendar.monthrange(self.year, self.month)[1]

    def day(self, day: int | None) -> date:
        """The given day of this month, clamped to the month length (31 -> 30 in Nov)."""
        try:
            d = int(day or 1)
        except (TypeError, ValueError):
            d = 1
        d = max(1, min(d, self.days_in_month))
        return date(self.year, self.month, d)

    @property
    def first_day(self) -> date:
        return date(self.year, self.month, 1)

    @property
    def last_day(self) -> date:
        return date(self.year, self.month, self.days_in_month)

    def __str__(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

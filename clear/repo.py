"""Repository: every read/write of one CLEAR database file."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import db, engine
from .models import Bill, CreditCard, LivingCost, Payment, Profile
from .money import round_money
from .periods import Period


@dataclass
class ClosePlan:
    """What the month-end close should write for `period`."""

    period: Period
    bill_payments: list[tuple[int, float, date]] = field(default_factory=list)   # (bill id, amount, date)
    accrue_bill_ids: list[int] = field(default_factory=list)
    living_payments: list[tuple[int, float, date]] = field(default_factory=list)
    savings_after: float | None = None
    reset_other_income: bool = True


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # ---- opening ----------------------------------------------------------------
    @classmethod
    def create(cls, path: str | Path, today: date | None = None) -> "Repository":
        path = Path(path)
        if path.exists():
            raise FileExistsError(str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
        db.create_new(path, today)
        return cls(path)

    @classmethod
    def open(cls, path: str | Path, today: date | None = None) -> tuple["Repository", db.MigrationReport]:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(str(path))
        kind = db.classify(path)
        if kind == "newer":
            raise db.NewerSchemaError(str(path))
        if kind == "foreign":
            raise db.NotADatabaseError(str(path))
        report = db.migrate(path, today)
        return cls(path), report

    def _conn(self) -> sqlite3.Connection:
        return db.connect(self.path)

    # ---- reading ----------------------------------------------------------------
    def bills(self) -> list[Bill]:
        with closing(self._conn()) as c:
            return [db.row_to_bill(r) for r in c.execute("SELECT * FROM bills ORDER BY sort_order, id")]

    def living(self) -> list[LivingCost]:
        with closing(self._conn()) as c:
            rows = c.execute("SELECT * FROM living_costs ORDER BY category COLLATE NOCASE, name, id")
            return [db.row_to_living(r) for r in rows]

    def cards(self) -> list[CreditCard]:
        with closing(self._conn()) as c:
            return [db.row_to_card(r) for r in c.execute("SELECT * FROM credit_cards ORDER BY id")]

    def profile(self) -> Profile:
        with closing(self._conn()) as c:
            return db.load_profile(c)

    def payments(self, period: Period | None = None) -> list[Payment]:
        with closing(self._conn()) as c:
            if period is None:
                rows = c.execute("SELECT * FROM payments ORDER BY id")
            else:
                rows = c.execute("SELECT * FROM payments WHERE period=? ORDER BY id", (str(period),))
            return [db.row_to_payment(r) for r in rows]

    def last_closed(self) -> Period | None:
        with closing(self._conn()) as c:
            return Period.try_parse(db.get_meta(c, "last_closed_period"))

    def meta(self, key: str, default: str = "") -> str:
        with closing(self._conn()) as c:
            return db.get_meta(c, key, default)

    def load_state(self, today: date) -> engine.State:
        current = Period.from_date(today)
        with closing(self._conn()) as c:
            bills = [db.row_to_bill(r) for r in c.execute("SELECT * FROM bills ORDER BY sort_order, id")]
            living = [db.row_to_living(r) for r in
                      c.execute("SELECT * FROM living_costs ORDER BY category COLLATE NOCASE, name, id")]
            cards = [db.row_to_card(r) for r in c.execute("SELECT * FROM credit_cards ORDER BY id")]
            profile = db.load_profile(c)
            last_closed = Period.try_parse(db.get_meta(c, "last_closed_period"))
            pays = [db.row_to_payment(r) for r in
                    c.execute("SELECT * FROM payments WHERE period=? ORDER BY id", (str(current),))]
        return engine.State(
            bills=bills, living=living, cards=cards, profile=profile, today=today,
            last_closed=last_closed if last_closed is not None else current.add(-1),
            paid_bills=engine.aggregate_payments(pays, "bill"),
            paid_living=engine.aggregate_payments(pays, "living"),
        )

    # ---- bills ----------------------------------------------------------------------
    def add_bill(self, bill: Bill) -> Bill:
        with closing(self._conn()) as c, db.tx(c):
            if not bill.sort_order:
                bill.sort_order = (c.execute("SELECT COALESCE(MAX(sort_order), 0) FROM bills").fetchone()[0] or 0) + 1
            cur = c.execute(f"INSERT INTO bills ({', '.join(db.BILL_COLUMNS)}) VALUES "
                            f"({', '.join('?' for _ in db.BILL_COLUMNS)})", db.bill_values(bill))
            bill.id = cur.lastrowid
        return bill

    def update_bill(self, bill: Bill) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.execute(f"UPDATE bills SET {', '.join(x + '=?' for x in db.BILL_COLUMNS)} WHERE id=?",
                      (*db.bill_values(bill), bill.id))

    def delete_bill(self, bill_id: int) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.execute("DELETE FROM payments WHERE target_type='bill' AND target_id=?", (bill_id,))
            c.execute("DELETE FROM bills WHERE id=?", (bill_id,))

    def reorder_bills(self, ordered_ids: list[int]) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.executemany("UPDATE bills SET sort_order=? WHERE id=?",
                          [(i + 1, bid) for i, bid in enumerate(ordered_ids)])

    # ---- living costs -----------------------------------------------------------------
    def add_living(self, lc: LivingCost) -> LivingCost:
        with closing(self._conn()) as c, db.tx(c):
            cur = c.execute(f"INSERT INTO living_costs ({', '.join(db.LIVING_COLUMNS)}) VALUES "
                            f"({', '.join('?' for _ in db.LIVING_COLUMNS)})", db.living_values(lc))
            lc.id = cur.lastrowid
        return lc

    def update_living(self, lc: LivingCost) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.execute(f"UPDATE living_costs SET {', '.join(x + '=?' for x in db.LIVING_COLUMNS)} WHERE id=?",
                      (*db.living_values(lc), lc.id))

    def delete_living(self, lc_id: int) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.execute("DELETE FROM payments WHERE target_type='living' AND target_id=?", (lc_id,))
            c.execute("DELETE FROM living_costs WHERE id=?", (lc_id,))

    # ---- cards ------------------------------------------------------------------------
    def add_card(self, card: CreditCard) -> CreditCard:
        with closing(self._conn()) as c, db.tx(c):
            cur = c.execute(f"INSERT INTO credit_cards ({', '.join(db.CARD_COLUMNS)}) VALUES "
                            f"({', '.join('?' for _ in db.CARD_COLUMNS)})", db.card_values(card))
            card.id = cur.lastrowid
        return card

    def update_card(self, card: CreditCard) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.execute(f"UPDATE credit_cards SET {', '.join(x + '=?' for x in db.CARD_COLUMNS)} WHERE id=?",
                      (*db.card_values(card), card.id))

    def delete_card(self, card_id: int) -> None:
        with closing(self._conn()) as c, db.tx(c):
            c.execute("DELETE FROM credit_cards WHERE id=?", (card_id,))

    # ---- profile ------------------------------------------------------------------------
    def save_profile(self, profile: Profile) -> None:
        with closing(self._conn()) as c, db.tx(c):
            db.save_profile(c, profile)

    # ---- ledger -----------------------------------------------------------------------------
    def record_bill_payment(self, bill_id: int, period: Period, paid_date: date, amount: float,
                            interest: float | None = None, note: str = "") -> Payment:
        with closing(self._conn()) as c, db.tx(c):
            return db.insert_bill_payment(c, bill_id, period, paid_date, amount, interest, note)

    def record_living_payment(self, lc_id: int, period: Period, paid_date: date, amount: float,
                              currency: str, note: str = "") -> None:
        with closing(self._conn()) as c, db.tx(c):
            db.insert_living_payment(c, lc_id, period, paid_date, amount, currency, note)

    def undo_last_payment(self, target_type: str, target_id: int, period: Period) -> bool:
        """Remove the latest payment of the month for the item and restore the balance."""
        with closing(self._conn()) as c, db.tx(c):
            row = c.execute("SELECT * FROM payments WHERE target_type=? AND target_id=? AND period=? "
                            "AND kind='payment' ORDER BY id DESC LIMIT 1",
                            (target_type, target_id, str(period))).fetchone()
            if row is None:
                return False
            pay = db.row_to_payment(row)
            if target_type == "bill" and pay.balance_before is not None and pay.balance_after is not None:
                bill = db.fetch_bill(c, target_id)
                restored = round_money(bill.amount + (pay.balance_before - pay.balance_after), bill.currency)
                c.execute("UPDATE bills SET amount=? WHERE id=?", (restored, target_id))
            c.execute("DELETE FROM payments WHERE id=?", (pay.id,))
            return True

    # ---- month-end close -----------------------------------------------------------------------
    def close_month(self, plan: ClosePlan, backup_file: str = "") -> dict:
        summary = {"payments": 0, "accruals": 0, "living": 0, "savings_before": None, "savings_after": None}
        with closing(self._conn()) as c, db.tx(c):
            for bill_id, amount, paid_date in plan.bill_payments:
                if amount > 0:
                    db.insert_bill_payment(c, bill_id, plan.period, paid_date, amount, note="close")
                    summary["payments"] += 1
            for bill_id in plan.accrue_bill_ids:
                if not db.bill_has_payment(c, bill_id, plan.period) and db.insert_accrual(
                        c, bill_id, plan.period, note="close: unpaid"):
                    summary["accruals"] += 1
            for lc_id, amount, paid_date in plan.living_payments:
                row = c.execute("SELECT currency FROM living_costs WHERE id=?", (lc_id,)).fetchone()
                if row is not None:
                    db.insert_living_payment(c, lc_id, plan.period, paid_date, amount, row[0] or "JPY", "close")
                    summary["living"] += 1
            profile = db.load_profile(c)
            summary["savings_before"] = profile.cumulative_savings
            if plan.savings_after is not None:
                profile.cumulative_savings = plan.savings_after
            if plan.reset_other_income:
                profile.other_income = 0.0
                profile.other_income_type = ""
            summary["savings_after"] = profile.cumulative_savings
            db.save_profile(c, profile)
            db.set_meta(c, last_closed_period=str(plan.period))
            c.execute("INSERT OR REPLACE INTO month_closes (period, closed_at, backup_file, summary) VALUES (?,?,?,?)",
                      (str(plan.period), db.now_text(), backup_file, json.dumps(summary)))
        return summary

    def skip_close(self, until: Period, backup_file: str = "") -> int:
        """Mark every month up to `until` as closed without changing any amount."""
        with closing(self._conn()) as c, db.tx(c):
            last = Period.try_parse(db.get_meta(c, "last_closed_period")) or until
            count = 0
            p = last.add(1)
            while p <= until:
                c.execute("INSERT OR REPLACE INTO month_closes (period, closed_at, backup_file, summary) "
                          "VALUES (?,?,?,?)", (str(p), db.now_text(), backup_file, json.dumps({"skipped": True})))
                count += 1
                p = p.add(1)
            db.set_meta(c, last_closed_period=str(until))
        return count

    def latest_close(self) -> dict | None:
        with closing(self._conn()) as c:
            row = c.execute("SELECT * FROM month_closes ORDER BY period DESC LIMIT 1").fetchone()
            if row is None:
                return None
            return {"period": row["period"], "closed_at": row["closed_at"], "backup_file": row["backup_file"],
                    "summary": json.loads(row["summary"] or "{}")}

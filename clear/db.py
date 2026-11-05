"""SQLite layout, migrations (F18) and low-level row helpers.

Files from Payback Management 3.x have ``PRAGMA user_version = 0`` and may lack
columns that were added over time; ``migrate`` brings any of them to the current
layout inside a single transaction. Connections are opened per operation and
closed right away, so Google Drive can sync the file while the app is idle.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from . import engine
from .info import APP_VERSION, SCHEMA_VERSION
from .models import Bill, CreditCard, LivingCost, Payment, Profile
from .money import CURRENCIES, round_money, to_float
from .periods import Period

log = logging.getLogger(__name__)

LEGACY_TABLES = {"bills", "living_costs", "savings", "credit_cards"}

SCHEMA: dict[str, list[tuple[str, str]]] = {
    "bills": [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("bill_type", "TEXT"), ("bill_name", "TEXT"), ("borrower_name", "TEXT"), ("lender_name", "TEXT"),
        ("amount", "REAL DEFAULT 0"), ("currency", "TEXT DEFAULT 'JPY'"), ("interest_rate", "REAL DEFAULT 0"),
        ("monthly_payment", "REAL DEFAULT 0"), ("monthly_due_day", "INTEGER DEFAULT 27"),
        ("current_month_payment", "REAL DEFAULT 0"), ("paid_this_month", "INTEGER DEFAULT 0"),
        ("created_date", "TEXT"), ("sort_order", "INTEGER"),
        ("cmp_period", "TEXT DEFAULT ''"), ("note", "TEXT DEFAULT ''"),
    ],
    "living_costs": [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("category", "TEXT DEFAULT ''"), ("name", "TEXT DEFAULT ''"), ("amount", "REAL DEFAULT 0"),
        ("currency", "TEXT DEFAULT 'JPY'"), ("monthly_due_day", "INTEGER DEFAULT 1"),
        ("paid_this_month", "INTEGER DEFAULT 0"), ("created_date", "TEXT"),
        ("payment_method", "TEXT DEFAULT 'Cash'"), ("description", "TEXT DEFAULT ''"), ("last_updated", "TEXT"),
    ],
    "credit_cards": [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("issuer", "TEXT DEFAULT ''"), ("name", "TEXT DEFAULT ''"), ("due_day", "INTEGER DEFAULT 27"),
        ("annual_fee", "REAL DEFAULT 0"), ("paid_annual_fee", "INTEGER DEFAULT 0"),
        ("credit_limit", "REAL DEFAULT 0"), ("currency", "TEXT DEFAULT 'JPY'"),
        ("used_amount", "REAL DEFAULT 0"), ("shopping_revolving_amount", "REAL DEFAULT 0"),
        ("cash_revolving_amount", "REAL DEFAULT 0"), ("shopping_credit_amount", "REAL DEFAULT 0"),
        ("created_date", "TEXT"), ("last_updated", "TEXT"), ("managed_in_bills", "INTEGER DEFAULT 1"),
    ],
    "savings": [("key", "TEXT PRIMARY KEY"), ("value", "TEXT")],
    "meta": [("key", "TEXT PRIMARY KEY"), ("value", "TEXT")],
    "payments": [
        ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
        ("target_type", "TEXT NOT NULL"), ("target_id", "INTEGER NOT NULL"), ("period", "TEXT NOT NULL"),
        ("paid_date", "TEXT"), ("amount", "REAL DEFAULT 0"), ("currency", "TEXT"),
        ("interest", "REAL DEFAULT 0"), ("principal", "REAL DEFAULT 0"),
        ("balance_before", "REAL"), ("balance_after", "REAL"),
        ("kind", "TEXT DEFAULT 'payment'"), ("note", "TEXT DEFAULT ''"), ("created_at", "TEXT"),
    ],
    "month_closes": [
        ("period", "TEXT PRIMARY KEY"), ("closed_at", "TEXT"), ("backup_file", "TEXT"), ("summary", "TEXT"),
    ],
}
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_payments_period ON payments(period)",
    "CREATE INDEX IF NOT EXISTS idx_payments_target ON payments(target_type, target_id, period)",
]

# Keys of the `savings` table (names kept from Payback Management 3.x).
PROFILE_KEYS = {
    "cumulative_savings": ("cumulative_savings", float),
    "cumulative_savings_currency": ("cumulative_savings_currency", str),
    "monthly_income": ("monthly_income", float),
    "monthly_income_currency": ("monthly_income_currency", str),
    "other_income": ("current_month_other_income", float),
    "other_income_currency": ("current_month_other_income_currency", str),
    "other_income_type": ("current_month_other_income_type", str),
    "expected_income": ("expected_monthly_income", float),
    "expected_income_currency": ("expected_monthly_income_currency", str),
    "extra_income": ("extra_monthly_income", float),
    "extra_income_currency": ("extra_monthly_income_currency", str),
    "payday": ("income_payment_day", int),
    "simulation_months": ("simulation_months", int),
}


class NewerSchemaError(RuntimeError):
    """The file was written by a newer CLEAR."""


class NotADatabaseError(RuntimeError):
    """The file is not a CLEAR / Payback Management database."""


# ---------------------------------------------------------------------------
# Connections
# ---------------------------------------------------------------------------
def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # explicit BEGIN/COMMIT (same behaviour on Python 3.10–3.14)
    return conn


@contextmanager
def tx(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def tables(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def classify(path: str | Path) -> str:
    """'new' (empty), 'legacy' (Payback Management 3.x), 'current', 'newer' or 'foreign'."""
    conn = connect(path)
    try:
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            names = tables(conn)
        except sqlite3.DatabaseError as exc:
            raise NotADatabaseError(str(exc)) from exc
    finally:
        conn.close()
    if version > SCHEMA_VERSION:
        return "newer"
    if version == SCHEMA_VERSION:
        return "current"
    if not (names - {"sqlite_sequence"}):
        return "new"
    if names & LEGACY_TABLES:
        return "legacy"
    return "foreign"


def ensure_schema(conn: sqlite3.Connection) -> list[str]:
    """Create missing tables/columns. Returns the list of changes (for logging)."""
    changes: list[str] = []
    existing = tables(conn)
    for table, cols in SCHEMA.items():
        if table not in existing:
            body = ", ".join(f"{name} {decl}" for name, decl in cols)
            conn.execute(f"CREATE TABLE {table} ({body})")
            changes.append(f"create {table}")
            continue
        have = columns(conn, table)
        for name, decl in cols:
            if name not in have:
                decl_add = decl.replace("PRIMARY KEY AUTOINCREMENT", "").replace("NOT NULL", "")
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl_add}")
                changes.append(f"add {table}.{name}")
    for stmt in INDEXES:
        conn.execute(stmt)
    return changes


# ---------------------------------------------------------------------------
# Value parsing
# ---------------------------------------------------------------------------
def parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text.lower() == "none":
        return None
    text = text.replace("/", "-")[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_text(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _int(value: object, default: int) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _day(value: object, default: int) -> int:
    return max(1, min(31, _int(value, default)))


def _currency(value: object) -> str:
    text = str(value or "").strip().upper()
    return text if text in CURRENCIES else "JPY"


def _get(row: sqlite3.Row, key: str, default: object = None) -> object:
    return row[key] if key in row.keys() else default


# ---------------------------------------------------------------------------
# Row <-> model
# ---------------------------------------------------------------------------
def row_to_bill(row: sqlite3.Row) -> Bill:
    cur = _currency(_get(row, "currency"))
    return Bill(
        id=row["id"],
        bill_type=str(_get(row, "bill_type") or "other_loan"),
        bill_name=str(_get(row, "bill_name") or ""),
        borrower_name=str(_get(row, "borrower_name") or ""),
        lender_name=str(_get(row, "lender_name") or ""),
        amount=round_money(_get(row, "amount", 0), cur),
        currency=cur,
        interest_rate=max(0.0, to_float(_get(row, "interest_rate", 0))),
        monthly_payment=max(0.0, round_money(_get(row, "monthly_payment", 0), cur)),
        monthly_due_day=_day(_get(row, "monthly_due_day"), 27),
        current_month_payment=max(0.0, round_money(_get(row, "current_month_payment", 0), cur)),
        cmp_period=str(_get(row, "cmp_period") or ""),
        created_date=parse_date(_get(row, "created_date")),
        sort_order=_int(_get(row, "sort_order"), row["id"] or 0),
        note=str(_get(row, "note") or ""),
    )


def row_to_living(row: sqlite3.Row) -> LivingCost:
    cur = _currency(_get(row, "currency"))
    created = parse_date(_get(row, "created_date"))
    method = str(_get(row, "payment_method") or "Cash")
    return LivingCost(
        id=row["id"],
        category=str(_get(row, "category") or ""),
        name=str(_get(row, "name") or ""),
        description=str(_get(row, "description") or ""),
        amount=round_money(_get(row, "amount", 0), cur),
        currency=cur,
        monthly_due_day=_day(_get(row, "monthly_due_day"), 1),
        payment_method="Credit Card" if method == "Credit Card" else "Cash",
        created_date=created,
        last_updated=parse_date(_get(row, "last_updated")) or created,
    )


def row_to_card(row: sqlite3.Row) -> CreditCard:
    cur = _currency(_get(row, "currency"))
    managed = _get(row, "managed_in_bills", 1)
    return CreditCard(
        id=row["id"],
        issuer=str(_get(row, "issuer") or ""),
        name=str(_get(row, "name") or ""),
        due_day=_day(_get(row, "due_day"), 27),
        annual_fee=max(0.0, to_float(_get(row, "annual_fee", 0))),
        paid_annual_fee=bool(_int(_get(row, "paid_annual_fee"), 0)),
        credit_limit=max(0.0, to_float(_get(row, "credit_limit", 0))),
        currency=cur,
        used_amount=max(0.0, to_float(_get(row, "used_amount", 0))),
        shopping_credit_amount=max(0.0, to_float(_get(row, "shopping_credit_amount", 0))),
        shopping_revolving_amount=max(0.0, to_float(_get(row, "shopping_revolving_amount", 0))),
        cash_revolving_amount=max(0.0, to_float(_get(row, "cash_revolving_amount", 0))),
        created_date=parse_date(_get(row, "created_date")),
        last_updated=parse_date(_get(row, "last_updated")),
        managed_in_bills=True if managed is None else bool(_int(managed, 1)),
    )


def row_to_payment(row: sqlite3.Row) -> Payment:
    bb = _get(row, "balance_before")
    ba = _get(row, "balance_after")
    return Payment(
        id=row["id"], target_type=row["target_type"], target_id=row["target_id"], period=row["period"],
        paid_date=parse_date(row["paid_date"]), amount=to_float(row["amount"]),
        currency=_currency(row["currency"]), interest=to_float(row["interest"]),
        principal=to_float(row["principal"]),
        balance_before=None if bb is None else to_float(bb),
        balance_after=None if ba is None else to_float(ba),
        kind=row["kind"] or "payment", note=row["note"] or "", created_at=row["created_at"] or "",
    )


BILL_COLUMNS = ("bill_type", "bill_name", "borrower_name", "lender_name", "amount", "currency",
                "interest_rate", "monthly_payment", "monthly_due_day", "current_month_payment",
                "cmp_period", "created_date", "sort_order", "note")


def bill_values(b: Bill) -> tuple:
    return (b.bill_type, b.bill_name, b.borrower_name, b.lender_name, round_money(b.amount, b.currency),
            b.currency, b.interest_rate, round_money(b.monthly_payment, b.currency), int(b.monthly_due_day),
            round_money(b.current_month_payment, b.currency), b.cmp_period or "",
            date_text(b.created_date), int(b.sort_order or 0), b.note or "")


LIVING_COLUMNS = ("category", "name", "description", "amount", "currency", "monthly_due_day",
                  "payment_method", "created_date", "last_updated")


def living_values(lc: LivingCost) -> tuple:
    return (lc.category, lc.name, lc.description, round_money(lc.amount, lc.currency), lc.currency,
            int(lc.monthly_due_day), lc.payment_method, date_text(lc.created_date), date_text(lc.last_updated))


CARD_COLUMNS = ("issuer", "name", "due_day", "annual_fee", "paid_annual_fee", "credit_limit", "currency",
                "used_amount", "shopping_credit_amount", "shopping_revolving_amount", "cash_revolving_amount",
                "created_date", "last_updated", "managed_in_bills")


def card_values(c: CreditCard) -> tuple:
    return (c.issuer, c.name, int(c.due_day), c.annual_fee, int(c.paid_annual_fee), c.credit_limit, c.currency,
            c.used_amount, c.shopping_credit_amount, c.shopping_revolving_amount, c.cash_revolving_amount,
            date_text(c.created_date), date_text(c.last_updated), int(c.managed_in_bills))


# ---------------------------------------------------------------------------
# Key/value tables
# ---------------------------------------------------------------------------
def kv_get_all(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    return {r[0]: r[1] for r in conn.execute(f"SELECT key, value FROM {table}")}


def kv_set(conn: sqlite3.Connection, table: str, items: dict[str, object]) -> None:
    conn.executemany(f"INSERT OR REPLACE INTO {table} (key, value) VALUES (?, ?)",
                     [(k, "" if v is None else str(v)) for k, v in items.items()])


def load_profile(conn: sqlite3.Connection) -> Profile:
    data = kv_get_all(conn, "savings")
    p = Profile()
    for attr, (key, kind) in PROFILE_KEYS.items():
        if key not in data:
            continue
        raw = data[key]
        if kind is float:
            setattr(p, attr, to_float(raw))
        elif kind is int:
            setattr(p, attr, _int(raw, getattr(p, attr)))
        else:
            setattr(p, attr, _currency(raw) if attr.endswith("_currency") else (raw or ""))
    p.payday = _day(p.payday, 25)
    p.simulation_months = max(1, min(24, p.simulation_months))
    return p


def save_profile(conn: sqlite3.Connection, p: Profile) -> None:
    kv_set(conn, "savings", {key: getattr(p, attr) for attr, (key, _k) in PROFILE_KEYS.items()})


def get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row and row[0] is not None else default


def set_meta(conn: sqlite3.Connection, **items: object) -> None:
    kv_set(conn, "meta", items)


# ---------------------------------------------------------------------------
# Ledger helpers (shared by migration and the repository)
# ---------------------------------------------------------------------------
def now_text() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def fetch_bill(conn: sqlite3.Connection, bill_id: int) -> Bill:
    row = conn.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
    if row is None:
        raise KeyError(f"bill {bill_id} not found")
    return row_to_bill(row)


def bill_has_payment(conn: sqlite3.Connection, bill_id: int, period: Period) -> bool:
    row = conn.execute(
        "SELECT 1 FROM payments WHERE target_type='bill' AND target_id=? AND period=? AND kind='payment' LIMIT 1",
        (bill_id, str(period))).fetchone()
    return row is not None


def insert_bill_payment(conn: sqlite3.Connection, bill_id: int, period: Period, paid_date: date,
                        amount: float, interest: float | None = None, note: str = "") -> Payment:
    """Record a payment: interest is charged once per month (first payment of the month)."""
    bill = fetch_bill(conn, bill_id)
    if interest is None and bill_has_payment(conn, bill_id, period):
        interest = 0.0
    split = engine.split_payment(bill, bill.amount, amount, interest)
    amount = round_money(amount, bill.currency)
    cur = conn.execute(
        "INSERT INTO payments (target_type, target_id, period, paid_date, amount, currency, interest, principal,"
        " balance_before, balance_after, kind, note, created_at) VALUES ('bill',?,?,?,?,?,?,?,?,?,'payment',?,?)",
        (bill_id, str(period), date_text(paid_date), amount, bill.currency, split.interest, split.principal,
         split.balance_before, split.balance_after, note, now_text()))
    conn.execute("UPDATE bills SET amount=? WHERE id=?", (split.balance_after, bill_id))
    return Payment(cur.lastrowid, "bill", bill_id, str(period), paid_date, amount, bill.currency,
                   split.interest, split.principal, split.balance_before, split.balance_after, "payment", note)


def insert_accrual(conn: sqlite3.Connection, bill_id: int, period: Period, note: str = "") -> Payment | None:
    """Add one month of interest to an unpaid interest-bearing balance."""
    bill = fetch_bill(conn, bill_id)
    interest = engine.monthly_interest(bill)
    if interest <= 0:
        return None
    after = round_money(bill.amount + interest, bill.currency)
    cur = conn.execute(
        "INSERT INTO payments (target_type, target_id, period, paid_date, amount, currency, interest, principal,"
        " balance_before, balance_after, kind, note, created_at) VALUES ('bill',?,?,?,0,?,?,?,?,?,'accrual',?,?)",
        (bill_id, str(period), date_text(period.last_day), bill.currency, interest, -interest,
         bill.amount, after, note, now_text()))
    conn.execute("UPDATE bills SET amount=? WHERE id=?", (after, bill_id))
    return Payment(cur.lastrowid, "bill", bill_id, str(period), period.last_day, 0.0, bill.currency,
                   interest, -interest, bill.amount, after, "accrual", note)


def insert_living_payment(conn: sqlite3.Connection, lc_id: int, period: Period, paid_date: date,
                          amount: float, currency: str, note: str = "") -> int:
    cur = conn.execute(
        "INSERT INTO payments (target_type, target_id, period, paid_date, amount, currency, interest, principal,"
        " kind, note, created_at) VALUES ('living',?,?,?,?,?,0,0,'payment',?,?)",
        (lc_id, str(period), date_text(paid_date), round_money(amount, currency), currency, note, now_text()))
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------
@dataclass
class MigrationReport:
    from_version: int = 0
    to_version: int = SCHEMA_VERSION
    legacy: bool = False
    open_period: str = ""
    last_closed: str = ""
    bills: int = 0
    living: int = 0
    cards: int = 0
    converted_bill_payments: int = 0
    converted_living_payments: int = 0
    changes: list[str] = field(default_factory=list)

    @property
    def migrated(self) -> bool:
        return self.from_version < self.to_version


def migrate(path: str | Path, today: date | None = None) -> MigrationReport:
    """Bring a database file to the current layout (no-op when already current)."""
    today = today or date.today()
    conn = connect(path)
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise NewerSchemaError(f"schema {version} > {SCHEMA_VERSION}")
        names = tables(conn) - {"sqlite_sequence"}
        report = MigrationReport(from_version=version, legacy=version == 0 and bool(names & LEGACY_TABLES))
        with tx(conn):
            report.changes = ensure_schema(conn)
            if version < 1:
                _migrate_0_to_1(conn, today, report)
            set_meta(conn, schema_version=SCHEMA_VERSION, app_version=APP_VERSION)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        report.bills = conn.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
        report.living = conn.execute("SELECT COUNT(*) FROM living_costs").fetchone()[0]
        report.cards = conn.execute("SELECT COUNT(*) FROM credit_cards").fetchone()[0]
        report.last_closed = get_meta(conn, "last_closed_period")
    finally:
        conn.close()
    if report.migrated:
        log.info("migrated %s from v%s: %s", Path(path).name, report.from_version, report.changes)
    return report


def _migrate_0_to_1(conn: sqlite3.Connection, today: date, report: MigrationReport) -> None:
    current = Period.from_date(today)

    # 1) normalise rows written by older versions -----------------------------------
    for row in conn.execute("SELECT * FROM bills").fetchall():
        b = row_to_bill(row)
        if b.bill_type not in ("card_loan", "shopping revolving", "cash revolving", "shopping credit",
                               "other_loan", "borrow_from_people"):
            b.bill_type = "other_loan"
        b.sort_order = b.sort_order if _get(row, "sort_order") is not None else b.id
        if b.created_date is None:
            b.created_date = today
        conn.execute(f"UPDATE bills SET {', '.join(c + '=?' for c in BILL_COLUMNS)} WHERE id=?",
                     (*bill_values(b), b.id))
    for row in conn.execute("SELECT * FROM living_costs").fetchall():
        lc = row_to_living(row)
        lc.created_date = lc.created_date or today
        lc.last_updated = lc.last_updated or lc.created_date
        conn.execute(f"UPDATE living_costs SET {', '.join(c + '=?' for c in LIVING_COLUMNS)} WHERE id=?",
                     (*living_values(lc), lc.id))
    for row in conn.execute("SELECT * FROM credit_cards").fetchall():
        c = row_to_card(row)
        conn.execute(f"UPDATE credit_cards SET {', '.join(x + '=?' for x in CARD_COLUMNS)} WHERE id=?",
                     (*card_values(c), c.id))

    # 2) month state: 3.x kept "last_reset_year/month" = the month that was still open
    data = kv_get_all(conn, "savings")
    year = _int(data.get("last_reset_year"), 0)
    month = _int(data.get("last_reset_month"), 0)
    open_period = current
    if report.legacy and year > 0 and 1 <= month <= 12:
        open_period = min(Period(year, month), current)
    report.open_period = str(open_period)
    last_closed = open_period.add(-1)
    report.last_closed = str(last_closed)

    # 3) the one-off "current month payment" belonged to that open month
    conn.execute("UPDATE bills SET cmp_period=? WHERE current_month_payment > 0 AND "
                 "(cmp_period IS NULL OR cmp_period='')", (str(open_period),))

    # 4) "paid this month" ticks become ledger lines for the open month
    for row in conn.execute("SELECT * FROM bills WHERE paid_this_month=1").fetchall():
        b = row_to_bill(row)
        amount = engine.planned_amount(b, open_period)
        if amount > 0:
            insert_bill_payment(conn, b.id, open_period, open_period.day(b.monthly_due_day), amount,
                                note="3.x: paid this month")
            report.converted_bill_payments += 1
    for row in conn.execute("SELECT * FROM living_costs WHERE paid_this_month=1").fetchall():
        lc = row_to_living(row)
        insert_living_payment(conn, lc.id, open_period, open_period.day(lc.monthly_due_day), lc.amount,
                              lc.currency, note="3.x: paid this month")
        report.converted_living_payments += 1
    conn.execute("UPDATE bills SET paid_this_month=0")
    conn.execute("UPDATE living_costs SET paid_this_month=0")

    set_meta(conn, last_closed_period=str(last_closed),
             migrated_from="Payback Management 3.x" if report.legacy else "",
             migrated_at=now_text(), created_at=get_meta(conn, "created_at") or now_text())
    if report.legacy:
        report.changes.append(json.dumps({"open_period": str(open_period)}))


def create_new(path: str | Path, today: date | None = None) -> None:
    today = today or date.today()
    conn = connect(path)
    try:
        with tx(conn):
            ensure_schema(conn)
            save_profile(conn, Profile())
            set_meta(conn, schema_version=SCHEMA_VERSION, app_version=APP_VERSION, created_at=now_text(),
                     last_closed_period=str(Period.from_date(today).add(-1)))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    finally:
        conn.close()

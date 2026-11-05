"""Shared fixtures: synthetic databases shaped like the files written by Payback Management 3.x.

No real personal data is used anywhere in the tests.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TODAY = date(2026, 11, 6)


def _savings(conn: sqlite3.Connection, items: dict) -> None:
    conn.execute("CREATE TABLE savings (key TEXT PRIMARY KEY, value TEXT)")
    conn.executemany("INSERT INTO savings VALUES (?, ?)", [(k, str(v)) for k, v in items.items()])


def make_legacy_36(path: Path, last_reset=(2026, 8)) -> Path:
    """Layout written by ver3.6.0 (all columns present)."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE bills (id INTEGER PRIMARY KEY AUTOINCREMENT, bill_type TEXT, bill_name TEXT,
        borrower_name TEXT, lender_name TEXT, amount REAL, currency TEXT, interest_rate REAL, monthly_payment REAL,
        monthly_due_day INTEGER, current_month_payment REAL, paid_this_month INTEGER DEFAULT 0, created_date TEXT,
        sort_order INTEGER)""")
    rows = [
        ("card_loan", "Loan A", "Yu", "Bank A", 500000, "JPY", 15.0, 20000, 27, 20000, 1, "2025-06-01", 2),
        ("shopping credit", "Card B", "Yu", "Card Co", 48000, "JPY", 0.0, 0, 10, 0, 0, "2025-06-02", 1),
        ("cash revolving", "Rev C", "Yu", "Card Co", 300000, "JPY", 18.0, 4000, 5, 4000, 0, "2025-06-03", 3),
        ("borrow_from_people", "Family", "Yu", "Mother", 100000, "JPY", 0.0, 0, 1, 0, 0, "2025-06-04", 4),
    ]
    conn.executemany("""INSERT INTO bills (bill_type, bill_name, borrower_name, lender_name, amount, currency,
        interest_rate, monthly_payment, monthly_due_day, current_month_payment, paid_this_month, created_date,
        sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    conn.execute("""CREATE TABLE living_costs (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, name TEXT,
        amount REAL, currency TEXT, monthly_due_day INTEGER, paid_this_month INTEGER DEFAULT 0,
        created_date DATETIME, payment_method TEXT DEFAULT "Cash", description TEXT DEFAULT "", last_updated TEXT)""")
    conn.executemany("""INSERT INTO living_costs (category, name, amount, currency, monthly_due_day,
        paid_this_month, created_date, payment_method, description, last_updated) VALUES (?,?,?,?,?,?,?,?,?,?)""", [
        ("Rent/Mortgage", "Rent", 80000, "JPY", 27, 1, "2025-09-03 00:00:00", "Cash", "", "2026-01-01"),
        ("Subscriptions", "Music", 1080, "JPY", 15, 0, "2025-09-03 00:00:00", "Credit Card", "", None),
    ])
    conn.execute("""CREATE TABLE credit_cards (id INTEGER PRIMARY KEY AUTOINCREMENT, issuer TEXT, name TEXT,
        due_day INTEGER, annual_fee REAL, paid_annual_fee INTEGER, credit_limit REAL, currency TEXT,
        used_amount REAL DEFAULT 0.0, shopping_revolving_amount REAL DEFAULT 0.0,
        cash_revolving_amount REAL DEFAULT 0.0, shopping_credit_amount REAL DEFAULT 0.0, created_date TEXT,
        last_updated TEXT)""")
    conn.execute("""INSERT INTO credit_cards (issuer, name, due_day, annual_fee, paid_annual_fee, credit_limit,
        currency, used_amount) VALUES ('Card Co', 'Gold', 10, 11000, 0, 500000, 'JPY', 348000)""")
    _savings(conn, {
        "monthly_income": 300000, "monthly_income_currency": "JPY", "cumulative_savings": 120000,
        "cumulative_savings_currency": "JPY", "expected_monthly_income": 300000,
        "expected_monthly_income_currency": "JPY", "extra_monthly_income": 0, "extra_monthly_income_currency": "JPY",
        "income_payment_day": 25, "current_month_other_income": 0, "current_month_other_income_currency": "JPY",
        "current_month_other_income_type": "", "last_reset_year": last_reset[0], "last_reset_month": last_reset[1],
        "simulation_months": 12,
    })
    conn.commit()
    conn.close()
    return path


def make_legacy_old(path: Path) -> Path:
    """Older layout: no description/last_updated, no shopping_credit_amount, *_jpy keys, CNY data."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE bills (id INTEGER PRIMARY KEY AUTOINCREMENT, bill_type TEXT, bill_name TEXT,
        borrower_name TEXT, lender_name TEXT, amount REAL, currency TEXT, interest_rate REAL, monthly_payment REAL,
        monthly_due_day INTEGER, current_month_payment REAL, paid_this_month INTEGER DEFAULT 0,
        created_date DATETIME, sort_order INTEGER)""")
    conn.executemany("""INSERT INTO bills (bill_type, bill_name, borrower_name, lender_name, amount, currency,
        interest_rate, monthly_payment, monthly_due_day, current_month_payment, paid_this_month, created_date,
        sort_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", [
        ("shopping revolving", "测试账单", "Yu", "银行甲", 23456.78, "CNY", 18.0, 1500, 8, 1500, 0, "2026-02-11", None),
        ("cash revolving", "Broken bill", "Yu", "银行乙", 50000.0, "CNY", 18.0, 1000, 25, 1000, 0, "2026-03-01", 2),
    ])
    conn.execute("""CREATE TABLE living_costs (id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT, name TEXT,
        amount REAL, currency TEXT, monthly_due_day INTEGER, paid_this_month INTEGER DEFAULT 0,
        created_date DATETIME, payment_method TEXT DEFAULT "Cash")""")
    conn.execute("""INSERT INTO living_costs (category, name, amount, currency, monthly_due_day, created_date)
        VALUES ('Communication', 'Phone', 6500, 'JPY', 3, '2025-09-03 00:00:00')""")
    conn.execute("""CREATE TABLE credit_cards (id INTEGER PRIMARY KEY AUTOINCREMENT, issuer TEXT, name TEXT,
        due_day INTEGER, annual_fee REAL, paid_annual_fee INTEGER, credit_limit REAL, currency TEXT,
        used_amount REAL DEFAULT 0.0, shopping_revolving_amount REAL DEFAULT 0.0,
        cash_revolving_amount REAL DEFAULT 0.0, created_date TEXT, last_updated TEXT)""")
    conn.execute("""INSERT INTO credit_cards (issuer, name, due_day, annual_fee, paid_annual_fee, credit_limit,
        currency, used_amount) VALUES ('银行甲', '白金卡', 8, 0, 0, 50000, 'CNY', 23456.78)""")
    _savings(conn, {
        "monthly_income_jpy": 0.0, "cumulative_savings_jpy": 0.0, "simulation_months": 23,
        "monthly_income": 5000.0, "monthly_income_currency": "CNY", "last_reset_year": 2026, "last_reset_month": 5,
        "income_payment_day": 15, "expected_monthly_income": 5000.0, "expected_monthly_income_currency": "CNY",
    })
    conn.commit()
    conn.close()
    return path


def make_legacy_minimal(path: Path) -> Path:
    """Very old layout: few bill columns and a column later dropped from the code."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE bills (id INTEGER PRIMARY KEY AUTOINCREMENT, bill_type TEXT, amount REAL,
        currency TEXT, interest_rate REAL, monthly_payment REAL, monthly_due_day INTEGER, lender_name TEXT,
        borrower_name TEXT, bill_name TEXT, payment_month_offset INTEGER)""")
    conn.execute("""INSERT INTO bills (bill_type, amount, currency, interest_rate, monthly_payment,
        monthly_due_day, lender_name, borrower_name, bill_name) VALUES
        ('mystery', 10000, NULL, NULL, 2000, 40, 'X', 'Y', NULL)""")
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def today() -> date:
    return TODAY

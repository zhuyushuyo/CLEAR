"""4.1: bank business days (F12), the yearly annual-fee status (B1 / F6) and automatic debits (B2).

Synthetic data only.
"""

from datetime import date

import pytest

from clear import engine, jpcal
from clear.engine import PeriodPaid, State
from clear.models import Bill, CreditCard, LivingCost, Profile
from clear.periods import Period

RATES = {"USD": 1.0, "JPY": 150.0, "CNY": 7.0, "SGD": 1.3}
TODAY = date(2026, 11, 6)
NOV = Period(2026, 11)


def loan(**kw) -> Bill:
    base = dict(id=1, bill_name="Loan", bill_type="card_loan", amount=650000, interest_rate=14.0,
                monthly_payment=25000, monthly_due_day=2, currency="JPY")
    base.update(kw)
    return Bill(**base)


def card(**kw) -> CreditCard:
    base = dict(id=1, issuer="Card Co", name="Gold", due_day=27, annual_fee=11000, created_date=date(2025, 1, 10))
    base.update(kw)
    return CreditCard(**base)


def state(**kw) -> State:
    base = dict(profile=Profile(cumulative_savings=100000, monthly_income=300000, payday=25), today=TODAY,
                last_closed=Period(2026, 10))
    base.update(kw)
    return State(**base)


# ---- business days ------------------------------------------------------------------------
def test_weekends_and_new_year_are_closed():
    assert jpcal.next_business_day(date(2026, 11, 1)) == date(2026, 11, 2)      # Sunday -> Monday
    assert jpcal.prev_business_day(date(2026, 11, 1)) == date(2026, 10, 30)     # Sunday -> Friday
    assert jpcal.is_bank_holiday(date(2026, 12, 31)) and jpcal.is_bank_holiday(date(2027, 1, 3))
    assert jpcal.next_business_day(date(2026, 12, 31)) == date(2027, 1, 4)
    assert jpcal.next_business_day(date(2026, 11, 2)) == date(2026, 11, 2)      # open: unchanged


@pytest.mark.skipif(not jpcal.has_holiday_calendar(), reason="jpholiday is not installed")
def test_national_holidays():
    assert jpcal.is_bank_holiday(date(2026, 11, 3))                              # Culture Day (Tuesday)
    assert jpcal.next_business_day(date(2026, 9, 19)) == date(2026, 9, 24)      # weekend + Silver Week


def test_due_and_pay_dates():
    assert engine.due_date(NOV, 1) == date(2026, 11, 2)
    assert engine.due_date(Period(2026, 2), 31) == date(2026, 3, 2)              # 28th is a Saturday
    assert engine.pay_date(Period(2026, 10), 25) == date(2026, 10, 23)          # salary: day before
    assert engine.due_date(NOV, 27) == date(2026, 11, 27)


# ---- annual fee: one year per cycle (B1 / F6) ------------------------------------------------
@pytest.mark.parametrize("kw, today, expected", [
    (dict(annual_fee=0), TODAY, "free"),
    (dict(fee_month=11), TODAY, "due"),                                         # billed this month, unpaid
    (dict(fee_month=3, fee_paid_period="2026-03"), TODAY, "paid"),
    (dict(fee_month=3, fee_paid_period="2025-03"), TODAY, "due"),               # last year's payment: reset
    (dict(fee_month=12, fee_paid_period="2026-11"), TODAY, "paid"),             # paid the month before the bill
    (dict(fee_month=12, fee_paid_period="2026-11"), date(2026, 12, 10), "paid"),
    (dict(fee_month=12, fee_paid_period="2026-11"), date(2027, 12, 1), "due"),
    (dict(fee_month=12, created_date=date(2026, 5, 1)), TODAY, "upcoming"),     # first bill still to come
    (dict(fee_month=0), TODAY, "no_month"),
    (dict(fee_month=0, fee_paid_period="2026"), TODAY, "paid"),                 # 4.0 data: this year only
    (dict(fee_month=0, fee_paid_period="2025"), TODAY, "no_month"),
    (dict(fee_month=3, fee_paid_period="2026"), TODAY, "paid"),
])
def test_fee_status(kw, today, expected):
    assert engine.fee_status(card(**kw), today).state == expected


def test_fee_cycle_and_month():
    assert engine.fee_cycle(11, TODAY) == NOV
    assert engine.fee_cycle(12, TODAY) == Period(2025, 12)
    st = engine.fee_status(card(fee_month=3, fee_paid_period="2026-03"), TODAY)
    assert st.cycle == Period(2026, 3) and st.next_bill == Period(2027, 3)
    assert engine.fee_in_month(card(fee_month=11), NOV)
    assert not engine.fee_in_month(card(fee_month=11, annual_fee=0), NOV)
    assert not engine.fee_in_month(card(fee_month=0), NOV)


def test_fee_is_a_month_item_paid_with_the_card_bill():
    items = engine.month_items(state(cards=[card(fee_month=11)]), RATES, "JPY")
    fee = next(i for i in items if i.kind == "fee")
    assert fee.due == date(2026, 11, 27) and fee.amount == 11000
    assert not fee.counted and not fee.paid and not fee.overdue
    s = engine.home_summary(state(cards=[card(fee_month=11)]), RATES, "JPY")
    assert s.month_total == 0                                                    # not in this month's cash
    paid = engine.month_items(state(cards=[card(fee_month=11, fee_paid_period="2026-11")]), RATES, "JPY")
    assert next(i for i in paid if i.kind == "fee").paid


def test_fee_alerts():
    codes = {a.code for a in engine.home_summary(
        state(cards=[card(id=1, fee_month=3, fee_paid_period="2025-03"), card(id=2, fee_month=0)]),
        RATES, "JPY").alerts}
    assert {"fee_unpaid", "fee_no_month"} <= codes


# ---- automatic debits are "to record", never "overdue" (B2) ------------------------------------
def test_auto_debit_past_its_day_is_pending_not_overdue():
    st = state(bills=[loan(), loan(id=2, bill_name="Mother", bill_type="borrow_from_people", interest_rate=0,
                                   monthly_payment=10000, monthly_due_day=1, auto_debit=False)],
               today=date(2026, 11, 4))
    items = {i.name: i for i in engine.month_items(st, RATES, "JPY")}
    debit, by_hand = items["Loan"], items["Mother"]
    assert debit.due == date(2026, 11, 2) and debit.days == -2
    assert debit.pending and not debit.overdue
    assert by_hand.overdue and not by_hand.pending
    assert by_hand.moved and by_hand.nominal == date(2026, 11, 1)                # Sunday -> Monday
    alerts = {a.code: a for a in engine.home_summary(st, RATES, "JPY").alerts}
    assert alerts["pending_debit"].level == "warning" and alerts["pending_debit"].params["name"] == "Loan"
    assert alerts["overdue"].params["name"] == "Mother"
    assert [i.name for i in engine.pending_debits(st, RATES, "JPY")] == ["Loan"]


def test_recorded_debit_is_no_longer_pending():
    st = state(bills=[loan()], today=date(2026, 11, 4),
               paid_bills={1: PeriodPaid(amount=25000, interest=7583, principal=17417, count=1,
                                         last_date=date(2026, 11, 2))})
    assert engine.pending_debits(st, RATES, "JPY") == []
    assert "pending_debit" not in {a.code for a in engine.home_summary(st, RATES, "JPY").alerts}


def test_living_costs_follow_their_payment_method():
    st = state(living=[LivingCost(id=1, name="Power", amount=12000, monthly_due_day=3, payment_method="Auto Debit"),
                       LivingCost(id=2, name="Food", amount=45000, monthly_due_day=3, payment_method="Cash"),
                       LivingCost(id=3, name="Phone", amount=4800, monthly_due_day=3,
                                  payment_method="Credit Card")])
    items = {i.name: i for i in engine.month_items(st, RATES, "JPY")}
    assert items["Power"].pending and items["Food"].overdue
    assert "Phone" not in items                                                  # in next month's card bill

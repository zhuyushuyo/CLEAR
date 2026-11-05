from datetime import date

from clear import engine
from clear.engine import PeriodPaid, State
from clear.models import Bill, CreditCard, LivingCost, Profile
from clear.money import convert, fmt_compact, fmt_money, round_money
from clear.periods import Period

NOV = Period(2026, 11)
RATES = {"USD": 1.0, "JPY": 150.0, "CNY": 7.0, "SGD": 1.3}


def loan(**kw) -> Bill:
    base = dict(id=1, bill_type="card_loan", bill_name="Loan", amount=500000, currency="JPY",
                interest_rate=15.0, monthly_payment=20000, monthly_due_day=27)
    base.update(kw)
    return Bill(**base)


# ---- periods / money -------------------------------------------------------------
def test_period_arithmetic():
    assert NOV.add(2) == Period(2027, 1)
    assert NOV.add(-11) == Period(2025, 12)
    assert Period(2026, 1).months_until(Period(2027, 3)) == 14
    assert Period(2026, 2).day(31) == date(2026, 2, 28)
    assert Period.parse("2026-04") == Period(2026, 4)
    assert Period.try_parse("garbage") is None
    assert str(Period(2026, 4)) == "2026-04"


def test_money_rounding_and_format():
    assert round_money(1234.5, "JPY") == 1235
    assert round_money(10.005, "USD") == 10.01
    assert round_money(-0.4, "JPY") == 0.0
    assert fmt_money(1234567, "JPY", "ja") == "1,234,567円"
    assert fmt_money(1234.5, "CNY", "ja") == "1,234.50元"
    assert fmt_money(-50, "USD", "en") == "-$50.00"
    assert fmt_money(99, "SGD", "en") == "S$99.00"
    assert fmt_compact(3_500_000, "JPY", "ja") == "350万"
    assert fmt_compact(250_000_000, "JPY", "ja") == "2.5億"
    assert fmt_compact(3_500_000, "USD", "en") == "3.5M"


def test_convert_uses_usd_base():
    assert convert(150, "JPY", "USD", RATES) == 1.0
    assert round(convert(7, "CNY", "JPY", RATES), 6) == 150.0
    assert convert(5, "JPY", "JPY", RATES) == 5


# ---- R1: interest is part of every month ------------------------------------------
def test_recorded_payments_include_interest_r1():
    """12 monthly payments of 20,000 on 500,000 at 15%: the balance must match the true amortisation."""
    b = loan()
    balance = b.amount
    for _ in range(12):
        split = engine.split_payment(b, balance, 20000)
        balance = split.balance_after
        b.amount = balance
    expected = 500000.0
    for _ in range(12):
        expected = round(expected * (1 + 0.15 / 12)) - 20000
    assert abs(balance - expected) <= 12  # yen rounding over 12 months
    assert balance > 320000  # 3.6.0 showed 260,000 here


def test_projection_matches_payoff_info():
    b = loan()
    info = engine.payoff_info(b, NOV)
    assert info.status == "ok"
    rows = engine.project_bill(b, NOV, info.months + 1)
    assert rows[info.months - 1].balance == 0
    assert rows[info.months - 2].balance > 0
    assert info.period == NOV.add(info.months - 1)
    assert info.remaining_interest == round(sum(r.interest for r in rows))


def test_underwater_detected_r3():
    b = loan(amount=300000, interest_rate=18.0, monthly_payment=4000)
    assert engine.monthly_interest(b) == 4500
    assert engine.is_underwater(b)
    assert engine.payoff_info(b, NOV).status == "never"


def test_lump_sum_is_full_balance_everywhere_r4():
    b = loan(bill_type="shopping credit", amount=48000, interest_rate=0, monthly_payment=0)
    assert engine.planned_amount(b, NOV) == 48000
    rows = engine.project_bill(b, NOV, 3)
    assert [r.payment for r in rows] == [48000, 0, 0]
    state = State(bills=[b], today=date(2026, 11, 6))
    summary = engine.home_summary(state, RATES, "JPY")
    assert summary.month_total == 48000
    assert engine.simulate(state, 2, RATES, "JPY")[0].debt_payment == 48000


def test_one_off_payment_only_for_its_month():
    b = loan(current_month_payment=50000, cmp_period=str(NOV))
    assert engine.planned_amount(b, NOV) == 50000
    assert engine.planned_amount(b, NOV.add(1)) == 20000


def test_recorded_month_is_not_paid_twice():
    b = loan(amount=486250)  # after this month's payment was recorded
    paid = PeriodPaid(amount=20000, interest=6250, principal=13750, count=1)
    rows = engine.project_bill(b, NOV, 2, paid)
    assert rows[0].recorded and rows[0].payment == 20000 and rows[0].balance == 486250
    assert rows[1].interest == round(486250 * 0.15 / 12)


def test_no_plan_and_none():
    assert engine.payoff_info(loan(monthly_payment=0), NOV).status == "no_plan"
    assert engine.payoff_info(loan(amount=0), NOV).status == "none"


# ---- household -------------------------------------------------------------------------
def make_state(**kw) -> State:
    prof = Profile(cumulative_savings=100000, monthly_income=300000, expected_income=280000, payday=25)
    base = dict(
        bills=[loan(), loan(id=2, bill_name="Card", bill_type="shopping credit", amount=30000, interest_rate=0,
                            monthly_payment=0, monthly_due_day=10)],
        living=[LivingCost(id=1, name="Rent", amount=80000, monthly_due_day=27),
                LivingCost(id=2, name="Music", amount=1000, payment_method="Credit Card")],
        cards=[CreditCard(id=1, name="Gold", used_amount=50000, credit_limit=100000, managed_in_bills=False)],
        profile=prof, today=date(2026, 11, 6), last_closed=Period(2026, 10),
    )
    base.update(kw)
    return State(**base)


def test_simulation_months_use_the_right_income_and_living_costs():
    rows = engine.simulate(make_state(), 3, RATES, "JPY")
    m1, m2 = rows[0], rows[1]
    assert m1.income == 300000 and m2.income == 280000
    assert m1.living == 80000          # card living costs are in next month's card bill
    assert m2.living == 81000
    assert m1.debt_payment == 20000 + 30000
    assert m1.savings == 100000 + 300000 - 50000 - 80000


def test_home_summary_totals_and_cards():
    s = engine.home_summary(make_state(), RATES, "JPY")
    assert s.bills_debt == 530000
    assert s.cards_debt == 50000 and s.total_debt == 580000
    assert s.month_total == 20000 + 30000 + 80000
    assert s.month_end == 100000 + 300000 - s.month_total
    assert s.payoff.status == "ok"
    kinds = [i.kind for i in s.items]
    assert "income" in kinds and kinds.count("living") == 1


def test_managed_card_is_not_counted_twice():
    st = make_state(cards=[CreditCard(id=1, used_amount=50000, managed_in_bills=True)])
    assert engine.home_summary(st, RATES, "JPY").cards_debt == 0


def test_alerts():
    st = make_state(
        bills=[loan(amount=300000, interest_rate=18.0, monthly_payment=4000, monthly_due_day=3),
               loan(id=2, bill_name="Soon", monthly_due_day=8)],
        cards=[CreditCard(id=1, name="Gold", used_amount=90000, credit_limit=100000)],
        today=date(2026, 11, 6))
    codes = {a.code for a in engine.home_summary(st, RATES, "JPY", rates_age_days=10).alerts}
    assert {"underwater", "overdue", "due_soon", "rates_stale", "card_util"} <= codes


def test_due_close_periods():
    st = make_state(last_closed=Period(2026, 8))
    assert st.due_close_periods() == [Period(2026, 9), Period(2026, 10)]
    assert make_state().due_close_periods() == []


def test_close_items_and_savings():
    st = make_state()
    oct_ = Period(2026, 10)
    items = engine.close_items(st.bills, st.living, oct_, [])
    choices = [engine.CloseChoice(i, True, i.planned, i.due) for i in items]
    start, income, outflow, suggested = engine.close_savings(st.profile, choices, RATES)
    assert outflow == 20000 + 30000 + 80000  # the card-paid living cost is excluded
    assert suggested == start + income - outflow

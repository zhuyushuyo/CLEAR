"""Pure calculations (no Qt, no database).

Money model
-----------
* ``Bill.amount`` is the balance *now*. It only changes through the ledger:
  a recorded payment is split into interest + principal, and the principal is
  subtracted; a month closed without a payment adds that month's interest.
* Interest for a month = balance x annual rate / 12, charged once per month
  (on the first payment of the month, or at month-end close when unpaid).
* "Shopping credit" (lump sum) bills are paid in full on their due date, no interest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .models import Bill, CreditCard, LivingCost, Payment, Profile
from .money import convert, round_money, unit
from .periods import Period

MAX_MONTHS = 600  # 50 years: anything longer is treated as "cannot be repaid"


# ---------------------------------------------------------------------------
# Ledger aggregation
# ---------------------------------------------------------------------------
@dataclass
class PeriodPaid:
    """What was recorded for one item in one month."""

    amount: float = 0.0
    interest: float = 0.0
    principal: float = 0.0
    count: int = 0
    last_date: date | None = None

    @property
    def paid(self) -> bool:
        return self.count > 0


def aggregate_payments(payments: list[Payment], target_type: str) -> dict[int, PeriodPaid]:
    out: dict[int, PeriodPaid] = {}
    for p in payments:
        if p.target_type != target_type or p.kind != "payment":
            continue
        agg = out.setdefault(p.target_id, PeriodPaid())
        agg.amount += p.amount
        agg.interest += p.interest
        agg.principal += p.principal
        agg.count += 1
        if p.paid_date and (agg.last_date is None or p.paid_date > agg.last_date):
            agg.last_date = p.paid_date
    return out


# ---------------------------------------------------------------------------
# State given to every calculation
# ---------------------------------------------------------------------------
@dataclass
class State:
    bills: list[Bill] = field(default_factory=list)
    living: list[LivingCost] = field(default_factory=list)
    cards: list[CreditCard] = field(default_factory=list)
    profile: Profile = field(default_factory=Profile)
    today: date = field(default_factory=date.today)
    last_closed: Period | None = None
    paid_bills: dict[int, PeriodPaid] = field(default_factory=dict)    # current month
    paid_living: dict[int, PeriodPaid] = field(default_factory=dict)   # current month

    @property
    def current(self) -> Period:
        return Period.from_date(self.today)

    def due_close_periods(self) -> list[Period]:
        """Past months that have not been closed yet (oldest first)."""
        if self.last_closed is None:
            return []
        out = []
        p = self.last_closed.add(1)
        while p < self.current:
            out.append(p)
            p = p.add(1)
        return out


# ---------------------------------------------------------------------------
# Single bill
# ---------------------------------------------------------------------------
def monthly_interest(bill: Bill, balance: float | None = None) -> float:
    bal = bill.amount if balance is None else balance
    if not bill.has_interest or bal <= 0:
        return 0.0
    return round_money(bal * bill.monthly_rate, bill.currency)


def planned_amount(bill: Bill, period: Period, balance: float | None = None) -> float:
    """What is planned to be paid in `period` when nothing has been recorded yet."""
    bal = bill.amount if balance is None else balance
    if bal <= 0:
        return 0.0
    if bill.is_lump_sum:
        return round_money(bal, bill.currency)
    base = bill.monthly_payment
    if bill.cmp_period == str(period) and bill.current_month_payment > 0:
        base = bill.current_month_payment
    if base <= 0:
        return 0.0
    return round_money(min(base, bal + monthly_interest(bill, bal)), bill.currency)


def is_underwater(bill: Bill) -> bool:
    """True when the monthly payment does not even cover the interest (R3)."""
    if bill.amount <= 0 or not bill.has_interest or bill.monthly_payment <= 0:
        return False
    return bill.monthly_payment <= monthly_interest(bill)


@dataclass
class Split:
    interest: float
    principal: float
    balance_before: float
    balance_after: float


def split_payment(bill: Bill, balance: float, amount: float, interest: float | None = None) -> Split:
    """Split a payment into interest and principal and give the new balance."""
    cur = bill.currency
    bal = round_money(balance, cur)
    if interest is None:
        interest = monthly_interest(bill, bal)
    interest = max(0.0, round_money(interest, cur))
    amount = round_money(amount, cur)
    principal = round_money(amount - interest, cur)
    after = round_money(bal - principal, cur)
    if after < unit(cur):
        after = 0.0
    return Split(interest=interest, principal=principal, balance_before=bal, balance_after=after)


@dataclass
class ScheduleRow:
    period: Period
    payment: float
    interest: float
    principal: float
    balance: float          # balance after this month
    recorded: bool = False  # True when taken from the ledger


def project_bill(bill: Bill, start: Period, months: int, paid: PeriodPaid | None = None) -> list[ScheduleRow]:
    """Month-by-month schedule from `start`. A month already recorded is taken as is."""
    cur = bill.currency
    bal = max(0.0, round_money(bill.amount, cur))
    rows: list[ScheduleRow] = []
    for k in range(max(0, int(months))):
        p = start.add(k)
        if k == 0 and paid is not None and paid.paid:
            rows.append(ScheduleRow(p, paid.amount, paid.interest, paid.principal, bal, True))
            continue
        if bal <= 0:
            rows.append(ScheduleRow(p, 0.0, 0.0, 0.0, 0.0))
            continue
        if bill.is_lump_sum:
            rows.append(ScheduleRow(p, bal, 0.0, bal, 0.0))
            bal = 0.0
            continue
        interest = monthly_interest(bill, bal)
        pay = planned_amount(bill, p, bal)
        principal = round_money(pay - interest, cur)
        bal = round_money(bal - principal, cur)
        if bal < unit(cur):
            bal = 0.0
        rows.append(ScheduleRow(p, pay, interest, principal, bal))
    return rows


@dataclass
class PayoffInfo:
    status: str                 # "none" (no balance) | "ok" | "never" (interest >= payment) | "no_plan"
    period: Period | None = None
    months: int = 0             # months from `start` until the last payment (1 = this month)
    remaining_interest: float = 0.0
    interest_now: float = 0.0


def payoff_info(bill: Bill, start: Period, paid: PeriodPaid | None = None) -> PayoffInfo:
    cur = bill.currency
    bal = round_money(bill.amount, cur)
    if bal <= 0:
        return PayoffInfo("none")
    interest_now = monthly_interest(bill, bal)
    already = paid is not None and paid.paid
    if bill.is_lump_sum:
        p = start.add(1) if already else start
        return PayoffInfo("ok", p, 2 if already else 1, 0.0, 0.0)
    if bill.monthly_payment <= 0:
        return PayoffInfo("no_plan", interest_now=interest_now)
    if bill.has_interest and bill.monthly_payment <= interest_now:
        return PayoffInfo("never", interest_now=interest_now)
    total_interest = 0.0
    k = 1 if already else 0
    p = start.add(k)
    b = bal
    while k < MAX_MONTHS:
        interest = monthly_interest(bill, b)
        pay = planned_amount(bill, p, b)
        if pay <= 0:
            return PayoffInfo("no_plan", interest_now=interest_now)
        b = round_money(b - (pay - interest), cur)
        total_interest += interest
        if b < unit(cur):
            return PayoffInfo("ok", p, k + 1, round_money(total_interest, cur), interest_now)
        k += 1
        p = p.add(1)
    return PayoffInfo("never", interest_now=interest_now, remaining_interest=round_money(total_interest, cur))


# ---------------------------------------------------------------------------
# Whole household
# ---------------------------------------------------------------------------
@dataclass
class SimRow:
    period: Period
    income: float
    debt_payment: float
    living: float
    net: float
    savings: float
    debt: float

    @property
    def net_worth(self) -> float:
        return self.savings - self.debt


def simulate(state: State, months: int, rates: dict, target: str) -> list[SimRow]:
    """Cash-flow projection in the display currency.

    Month 1 uses this month's income and, for debts, what was recorded (or is still
    planned). Living costs paid by card are paid through next month's card bill,
    so they count from month 2 on (this month's card bill is entered as a debt).
    """
    prof = state.profile
    months = max(1, int(months))

    def cv(value: float, cur: str) -> float:
        return convert(value, cur, target, rates)

    savings = cv(prof.cumulative_savings, prof.cumulative_savings_currency)
    schedules = [
        (b, project_bill(b, state.current, months, state.paid_bills.get(b.id))) for b in state.bills
    ]
    cash_living = sum(cv(lc.amount, lc.currency) for lc in state.living if not lc.is_card)
    card_living = sum(cv(lc.amount, lc.currency) for lc in state.living if lc.is_card)

    rows: list[SimRow] = []
    for k in range(months):
        p = state.current.add(k)
        if k == 0:
            income = cv(prof.monthly_income, prof.monthly_income_currency) + cv(
                prof.other_income, prof.other_income_currency)
            living = cash_living
        else:
            income = cv(prof.expected_income, prof.expected_income_currency) + cv(
                prof.extra_income, prof.extra_income_currency)
            living = cash_living + card_living
        debt_payment = sum(cv(s[k].payment, b.currency) for b, s in schedules)
        debt = sum(cv(s[k].balance, b.currency) for b, s in schedules)
        net = income - debt_payment - living
        savings += net
        rows.append(SimRow(p, income, debt_payment, living, net, savings, debt))
    return rows


@dataclass
class DueItem:
    kind: str                 # "bill" | "living" | "income"
    target_id: int | None
    name: str
    sub: str                  # bill type / category code (translated by the UI)
    due: date
    amount: float             # in the item's own currency
    currency: str
    amount_target: float      # in the display currency
    paid: bool = False
    paid_amount: float = 0.0
    days: int = 0             # days until due (negative = overdue)

    @property
    def overdue(self) -> bool:
        return self.kind != "income" and not self.paid and self.days < 0


@dataclass
class Alert:
    level: str                # "critical" | "warning" | "info"
    code: str
    params: dict = field(default_factory=dict)


@dataclass
class PayoffSummary:
    status: str = "none"      # "none" | "ok" | "never" | "no_plan"
    period: Period | None = None
    months: int = 0
    remaining_interest: float = 0.0
    never: list[str] = field(default_factory=list)
    no_plan: list[str] = field(default_factory=list)


@dataclass
class HomeSummary:
    total_debt: float = 0.0
    bills_debt: float = 0.0
    cards_debt: float = 0.0
    bill_count: int = 0
    card_count: int = 0
    month_total: float = 0.0
    month_paid: float = 0.0
    savings_start: float = 0.0
    income: float = 0.0
    outflow: float = 0.0
    month_end: float = 0.0
    payoff: PayoffSummary = field(default_factory=PayoffSummary)
    items: list[DueItem] = field(default_factory=list)
    breakdown: list[tuple[str, float]] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    trend: list[SimRow] = field(default_factory=list)

    @property
    def month_remaining(self) -> float:
        return self.month_total - self.month_paid


def bill_payoffs(state: State) -> dict[int, PayoffInfo]:
    return {b.id: payoff_info(b, state.current, state.paid_bills.get(b.id)) for b in state.bills}


def summarize_payoff(state: State, rates: dict, target: str,
                     infos: dict[int, PayoffInfo] | None = None) -> PayoffSummary:
    infos = infos if infos is not None else bill_payoffs(state)
    out = PayoffSummary()
    ok: list[PayoffInfo] = []
    for b in state.bills:
        info = infos.get(b.id)
        if info is None or info.status == "none":
            continue
        if info.status == "never":
            out.never.append(b.label)
        elif info.status == "no_plan":
            out.no_plan.append(b.label)
        else:
            ok.append(info)
            out.remaining_interest += convert(info.remaining_interest, b.currency, target, rates)
    if ok:
        last = max(ok, key=lambda i: (i.period or state.current))
        out.period, out.months = last.period, last.months
    if out.never:
        out.status = "never"
    elif ok:
        out.status = "ok"
    elif out.no_plan:
        out.status = "no_plan"
    return out


def home_summary(state: State, rates: dict, target: str, *, rates_age_days: int | None = None,
                 due_soon_days: int = 3) -> HomeSummary:
    s = HomeSummary()
    cur = state.current
    today = state.today

    def cv(value: float, c: str) -> float:
        return convert(value, c, target, rates)

    # --- debts -------------------------------------------------------------
    breakdown: dict[str, float] = {}
    for b in state.bills:
        if b.amount > 0:
            s.bill_count += 1
            v = cv(b.amount, b.currency)
            s.bills_debt += v
            breakdown[b.bill_type] = breakdown.get(b.bill_type, 0.0) + v
    for c in state.cards:
        if not c.managed_in_bills and c.used_amount > 0:
            s.card_count += 1
            s.cards_debt += cv(c.used_amount, c.currency)
    if s.cards_debt > 0:
        breakdown["__cards__"] = s.cards_debt
    s.total_debt = s.bills_debt + s.cards_debt
    s.breakdown = sorted(breakdown.items(), key=lambda kv: -kv[1])

    # --- this month's checklist ------------------------------------------------
    for b in state.bills:
        paid = state.paid_bills.get(b.id)
        if b.amount <= 0 and not (paid and paid.paid):
            continue
        due = cur.day(b.monthly_due_day)
        planned = planned_amount(b, cur)
        amount = paid.amount if paid and paid.paid else planned
        if amount <= 0 and not (paid and paid.paid):
            continue
        s.items.append(DueItem("bill", b.id, b.label, b.bill_type, due, amount, b.currency,
                               cv(amount, b.currency), bool(paid and paid.paid),
                               paid.amount if paid else 0.0, (due - today).days))
    for lc in state.living:
        if lc.is_card or lc.amount <= 0:
            continue
        paid = state.paid_living.get(lc.id)
        due = cur.day(lc.monthly_due_day)
        amount = paid.amount if paid and paid.paid else lc.amount
        s.items.append(DueItem("living", lc.id, lc.label, lc.category, due, amount, lc.currency,
                               cv(amount, lc.currency), bool(paid and paid.paid),
                               paid.amount if paid else 0.0, (due - today).days))
    for it in s.items:
        s.month_total += it.amount_target
        if it.paid:
            s.month_paid += it.amount_target
    prof = state.profile
    income = cv(prof.monthly_income, prof.monthly_income_currency) + cv(
        prof.other_income, prof.other_income_currency)
    if income > 0:
        s.items.append(DueItem("income", None, "", "", cur.day(prof.payday), income, target, income,
                               days=(cur.day(prof.payday) - today).days))
    s.items.sort(key=lambda i: (i.due, 0 if i.kind == "income" else 1, i.name))

    s.savings_start = cv(prof.cumulative_savings, prof.cumulative_savings_currency)
    s.income = income
    s.outflow = s.month_total
    s.month_end = s.savings_start + s.income - s.outflow

    # --- payoff and trend ------------------------------------------------------
    infos = bill_payoffs(state)
    s.payoff = summarize_payoff(state, rates, target, infos)
    if s.payoff.status == "ok":
        horizon = min(60, max(12, s.payoff.months + 2))
    else:
        horizon = 36
    s.trend = simulate(state, horizon, rates, target) if (state.bills or state.living or income) else []

    # --- alerts ------------------------------------------------------------------
    alerts: list[Alert] = []
    for p in state.due_close_periods()[:1]:
        alerts.append(Alert("info", "close_due", {"period": p}))
    for b in state.bills:
        if is_underwater(b):
            alerts.append(Alert("critical", "underwater", {
                "name": b.label, "interest": monthly_interest(b), "payment": b.monthly_payment,
                "currency": b.currency}))
    for it in s.items:
        if it.kind == "income" or it.paid:
            continue
        if it.days < 0:
            alerts.append(Alert("critical", "overdue", {
                "name": it.name, "days": -it.days, "amount": it.amount, "currency": it.currency}))
        elif it.days <= due_soon_days:
            alerts.append(Alert("warning", "due_soon", {
                "name": it.name, "days": it.days, "amount": it.amount, "currency": it.currency}))
    if s.month_end < 0 and (s.items or income):
        alerts.append(Alert("warning", "negative_month", {"amount": s.month_end, "currency": target}))
    for c in state.cards:
        u = c.utilization
        if u is not None and u >= 0.8:
            alerts.append(Alert("warning", "card_util", {"name": c.label, "pct": round(u * 100)}))
    for name in s.payoff.no_plan:
        alerts.append(Alert("info", "no_plan", {"name": name}))
    if rates_age_days is not None and rates_age_days > 7:
        alerts.append(Alert("warning", "rates_stale", {"days": rates_age_days}))
    order = {"critical": 0, "warning": 1, "info": 2}
    s.alerts = sorted(alerts, key=lambda a: order.get(a.level, 3))
    return s


# ---------------------------------------------------------------------------
# Month-end close
# ---------------------------------------------------------------------------
@dataclass
class CloseItem:
    kind: str                 # "bill" | "living"
    target_id: int
    name: str
    sub: str
    currency: str
    planned: float
    recorded: PeriodPaid | None
    due: date
    interest_if_unpaid: float = 0.0
    is_card: bool = False     # living cost paid by card

    @property
    def is_recorded(self) -> bool:
        return self.recorded is not None and self.recorded.paid


def close_items(bills: list[Bill], living: list[LivingCost], period: Period,
                payments: list[Payment]) -> list[CloseItem]:
    paid_b = aggregate_payments(payments, "bill")
    paid_l = aggregate_payments(payments, "living")
    items: list[CloseItem] = []
    for b in bills:
        rec = paid_b.get(b.id)
        if b.amount <= 0 and not (rec and rec.paid):
            continue
        items.append(CloseItem("bill", b.id, b.label, b.bill_type, b.currency,
                               planned_amount(b, period), rec, period.day(b.monthly_due_day),
                               monthly_interest(b)))
    for lc in living:
        rec = paid_l.get(lc.id)
        items.append(CloseItem("living", lc.id, lc.label, lc.category, lc.currency,
                               round_money(lc.amount, lc.currency), rec, period.day(lc.monthly_due_day),
                               0.0, lc.is_card))
    return items


@dataclass
class CloseChoice:
    """The user's decision for one CloseItem."""

    item: CloseItem
    pay: bool
    amount: float
    paid_date: date


def close_savings(profile: Profile, choices: list[CloseChoice], rates: dict) -> tuple[float, float, float, float]:
    """(savings at start, income, cash outflow, suggested savings) in the savings currency."""
    target = profile.cumulative_savings_currency
    start = profile.cumulative_savings
    income = convert(profile.monthly_income, profile.monthly_income_currency, target, rates) + convert(
        profile.other_income, profile.other_income_currency, target, rates)
    outflow = 0.0
    for ch in choices:
        it = ch.item
        if it.kind == "living" and it.is_card:
            continue  # paid through the card bill
        if it.is_recorded:
            outflow += convert(it.recorded.amount, it.currency, target, rates)
        elif ch.pay:
            outflow += convert(ch.amount, it.currency, target, rates)
    suggested = round_money(start + income - outflow, target)
    return start, income, outflow, suggested

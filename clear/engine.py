"""Pure calculations (no Qt, no database).

Money model
-----------
* ``Bill.amount`` is the balance *now*. It only changes through the ledger:
  a recorded payment is split into interest + principal, and the principal is
  subtracted; a month closed without a payment adds that month's interest.
* Interest for a month = balance x annual rate / 12, charged once per month
  (on the first payment of the month, or at month-end close when unpaid).
* "Shopping credit" (lump sum) bills are paid in full on their due date, no interest.
* Due dates falling on a bank holiday move to the next business day (F12).
* "Overdue" is only said of items paid by hand; an automatic debit past its date is
  "waiting to be recorded" (B2).
* A debt or living cost can start later (``start_period``, 4.1.2): before its first
  payment month nothing is due, no interest is added and it is not part of a close.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import invest
from .jpcal import next_business_day, prev_business_day
from .models import Bill, CreditCard, Holding, LivingCost, Payment, Price, Profile, Trade
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
    holdings: list[Holding] = field(default_factory=list)
    prices: dict[str, Price] = field(default_factory=dict)
    returns: dict[str, float] = field(default_factory=lambda: dict(invest.DEFAULT_RETURNS))
    trades_month: list[Trade] = field(default_factory=list)            # current month
    trades_year: list[Trade] = field(default_factory=list)             # current calendar year

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
# Calendar (F12)
# ---------------------------------------------------------------------------
def due_date(period: Period, day: int) -> date:
    """Payment date in `period`: the day (clamped to the month) moved to the next bank business day."""
    return next_business_day(period.day(day))


def pay_date(period: Period, day: int) -> date:
    """Salary date: moved to the business day before when banks are closed."""
    return prev_business_day(period.day(day))


# ---------------------------------------------------------------------------
# Annual card fee (B1)
# ---------------------------------------------------------------------------
@dataclass
class FeeStatus:
    state: str                    # free | paid | due | upcoming | no_month
    cycle: Period | None = None   # the billing month of the current yearly cycle
    next_bill: Period | None = None
    paid_label: str = ""          # "YYYY-MM" or "YYYY" as recorded

    @property
    def due_now(self) -> bool:
        return self.state == "due"


def _paid_marker(card: CreditCard) -> Period | int | None:
    text = (card.fee_paid_period or "").strip()
    if not text:
        return None
    p = Period.try_parse(text)
    if p is not None:
        return p
    try:
        return int(text[:4])
    except ValueError:
        return None


def fee_cycle(fee_month: int, today: date) -> Period:
    """The last billing month on or before today."""
    return Period(today.year, fee_month) if fee_month <= today.month else Period(today.year - 1, fee_month)


def fee_status(card: CreditCard, today: date) -> FeeStatus:
    if card.annual_fee <= 0:
        return FeeStatus("free")
    marker = _paid_marker(card)
    label = card.fee_paid_period or ""
    if not card.fee_month:
        year = marker.year if isinstance(marker, Period) else marker
        return FeeStatus("paid" if year == today.year else "no_month", paid_label=label)
    cycle = fee_cycle(card.fee_month, today)
    paid_p = Period(marker, card.fee_month) if isinstance(marker, int) else marker
    if paid_p is not None and paid_p >= cycle.add(-1):
        return FeeStatus("paid", cycle, cycle.add(12), label)
    created = Period.from_date(card.created_date) if card.created_date else None
    if created is not None and created > cycle:
        return FeeStatus("upcoming", cycle, cycle.add(12), label)
    return FeeStatus("due", cycle, cycle.add(12), label)


def fee_in_month(card: CreditCard, period: Period) -> bool:
    return card.annual_fee > 0 and bool(card.fee_month) and period.month == card.fee_month


# ---------------------------------------------------------------------------
# First payment month (4.1.2)
# ---------------------------------------------------------------------------
def start_of(item: Bill | LivingCost) -> Period | None:
    """The month of the first payment of a debt or living cost (None: no limit)."""
    text = getattr(item, "start_period", "") or ""
    return Period.try_parse(text) if text else None


def started(item: Bill | LivingCost, period: Period) -> bool:
    """True when a payment can be due in `period` (it is not before the first payment month)."""
    start = start_of(item)
    return start is None or period >= start


def next_period(item: Bill | LivingCost, current: Period, paid: bool) -> Period:
    """The month of the next payment still to come: this month, the next one once this
    month is paid, or the first payment month when that is later."""
    p = current.add(1) if paid else current
    start = start_of(item)
    return start if start is not None and start > p else p


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
    if bal <= 0 or not started(bill, period):
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
        if not started(bill, p):  # before the first payment: nothing paid, no interest added
            rows.append(ScheduleRow(p, 0.0, 0.0, 0.0, bal))
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
    k = 1 if already else 0
    first = start_of(bill)
    if first is not None and start.add(k) < first:
        k = start.months_until(first)
    if bill.is_lump_sum:
        return PayoffInfo("ok", start.add(k), k + 1, 0.0, 0.0)
    if bill.monthly_payment <= 0:
        return PayoffInfo("no_plan", interest_now=interest_now)
    if bill.has_interest and bill.monthly_payment <= interest_now:
        return PayoffInfo("never", interest_now=interest_now)
    total_interest = 0.0
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
    living: float                 # living costs (+ card annual fees in their billing month)
    net: float
    savings: float
    debt: float
    contrib: float = 0.0          # monthly contributions paid this month
    invest: float = 0.0           # value of the investments at the end of the month
    trade_cash: float = 0.0       # month 1: cash from other trades (sales, dividends - purchases)

    @property
    def net_worth(self) -> float:
        return self.savings + self.invest - self.debt

    @property
    def cash_net(self) -> float:
        """Savings minus debt: net worth without the investments (4.1.2)."""
        return self.savings - self.debt


def contributions_done(trades: list[Trade]) -> dict[int, float]:
    """Holding id -> amount (holding currency) already contributed in these trades."""
    out: dict[int, float] = {}
    for tr in trades:
        if tr.is_contrib and tr.kind == "buy":
            out[tr.holding_id] = out.get(tr.holding_id, 0.0) + tr.amount
    return out


def trade_flows(trades: list[Trade], holdings: list[Holding], rates: dict, target: str,
                include_contrib: bool = False) -> tuple[float, float]:
    """(cash in, cash out) of the trades, in `target`. Contribution trades are left out unless asked."""
    cur = {h.id: h.currency for h in holdings}
    cash_in = cash_out = 0.0
    for tr in trades:
        if not tr.cash_effect or (tr.is_contrib and not include_contrib):
            continue
        v = convert(abs(tr.cash), cur.get(tr.holding_id, tr.currency), target, rates)
        if tr.cash >= 0:
            cash_in += v
        else:
            cash_out += v
    return cash_in, cash_out


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

    def living_in(k: int, p: Period) -> float:
        """Living costs paid in month k; by card they are paid with the next month's card bill."""
        total = 0.0
        for lc in state.living:
            if lc.is_card:
                if k == 0 or not started(lc, p.add(-1)):
                    continue
            elif not started(lc, p):
                continue
            total += cv(lc.amount, lc.currency)
        return total

    # investments: value by kind, growing at the expected yearly return, plus contributions
    folio = invest.summarize(state.holdings, state.prices, rates, target)
    value_by_kind = dict(folio.by_kind)
    done = contributions_done(state.trades_month)
    contrib_by_kind: dict[str, float] = {}
    first_cash = first_invest = 0.0
    for h in state.holdings:
        if not h.has_contribution:
            continue
        amount = cv(h.contrib_amount, h.contrib_currency)
        contrib_by_kind[h.kind] = contrib_by_kind.get(h.kind, 0.0) + amount
        executed = h.id in done
        if executed:
            if h.contrib_method == "bank":
                first_cash += convert(done[h.id], h.currency, target, rates)
        else:
            first_invest += amount
            if h.contrib_method == "bank":
                first_cash += amount
    contrib_total = sum(contrib_by_kind.values())
    trade_in, trade_out = trade_flows(state.trades_month, state.holdings, rates, target)

    rows: list[SimRow] = []
    for k in range(months):
        p = state.current.add(k)
        fees = 0.0
        if k == 0:
            income = cv(prof.monthly_income, prof.monthly_income_currency) + cv(
                prof.other_income, prof.other_income_currency)
            living = living_in(0, p)
            contrib = first_cash
            trade_cash = trade_in - trade_out
            invest_total = sum(value_by_kind.values()) + first_invest
            for h in state.holdings:  # this month's pending contributions join their kind
                if h.has_contribution and h.id not in done:
                    value_by_kind[h.kind] = value_by_kind.get(h.kind, 0.0) + cv(h.contrib_amount, h.contrib_currency)
        else:
            income = cv(prof.expected_income, prof.expected_income_currency) + cv(
                prof.extra_income, prof.extra_income_currency)
            fees = sum(cv(c.annual_fee, c.currency) for c in state.cards if fee_in_month(c, p))
            living = living_in(k, p) + fees
            contrib = contrib_total
            trade_cash = 0.0
            for kind in set(value_by_kind) | set(contrib_by_kind):
                r = float(state.returns.get(kind, 0.0) or 0.0) / 100.0 / 12.0
                value_by_kind[kind] = value_by_kind.get(kind, 0.0) * (1.0 + r) + contrib_by_kind.get(kind, 0.0)
            invest_total = sum(value_by_kind.values())
        debt_payment = sum(cv(s[k].payment, b.currency) for b, s in schedules)
        debt = sum(cv(s[k].balance, b.currency) for b, s in schedules)
        net = income - debt_payment - living - contrib + trade_cash
        savings += net
        rows.append(SimRow(p, income, debt_payment, living, net, savings, debt, contrib, invest_total, trade_cash))
    return rows


@dataclass
class DueItem:
    kind: str                 # "bill" | "living" | "income" | "fee" | "contrib"
    target_id: int | None
    name: str
    sub: str                  # bill type / category code / holding kind (translated by the UI)
    due: date                 # moved to the next business day when banks are closed
    amount: float             # in the item's own currency
    currency: str
    amount_target: float      # in the display currency
    paid: bool = False
    paid_amount: float = 0.0
    days: int = 0             # days until due (negative = past)
    nominal: date | None = None   # the date before the business-day move
    auto_debit: bool = False  # taken from the bank account automatically
    counted: bool = True      # part of this month's cash outflow (False: paid with next month's card bill)

    @property
    def overdue(self) -> bool:
        """Past its date, unrecorded and paid by hand."""
        return self.kind not in ("income", "fee", "contrib") and not self.paid and self.days < 0 \
            and not self.auto_debit

    @property
    def pending(self) -> bool:
        """An automatic payment past its date that has not been recorded yet."""
        return self.kind != "income" and not self.paid and self.days < 0 and not self.overdue

    @property
    def moved(self) -> bool:
        return self.nominal is not None and self.nominal != self.due


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
    invest_value: float = 0.0
    net_worth: float = 0.0        # end of this month (estimate): savings + investments - debts
    net_worth_parts: tuple[float, float, float] = (0.0, 0.0, 0.0)   # savings, investments, debts
    portfolio: invest.PortfolioSummary | None = None
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


def month_items(state: State, rates: dict, target: str) -> list[DueItem]:
    """This month's payments (debts, living costs, annual fees, contributions), unsorted."""
    cur = state.current
    today = state.today

    def cv(value: float, c: str) -> float:
        return convert(value, c, target, rates)

    items: list[DueItem] = []
    for b in state.bills:
        paid = state.paid_bills.get(b.id)
        is_paid = bool(paid and paid.paid)
        if not is_paid and (b.amount <= 0 or not started(b, cur)):
            continue
        amount = paid.amount if is_paid else planned_amount(b, cur)
        if amount <= 0 and not is_paid:
            continue
        due = due_date(cur, b.monthly_due_day)
        items.append(DueItem("bill", b.id, b.label, b.bill_type, due, amount, b.currency, cv(amount, b.currency),
                             is_paid, paid.amount if paid else 0.0, (due - today).days,
                             cur.day(b.monthly_due_day), b.auto_debit))
    for lc in state.living:
        if lc.is_card or lc.amount <= 0:
            continue
        paid = state.paid_living.get(lc.id)
        is_paid = bool(paid and paid.paid)
        if not is_paid and not started(lc, cur):
            continue
        due = due_date(cur, lc.monthly_due_day)
        amount = paid.amount if is_paid else lc.amount
        items.append(DueItem("living", lc.id, lc.label, lc.category, due, amount, lc.currency,
                             cv(amount, lc.currency), is_paid, paid.amount if paid else 0.0, (due - today).days,
                             cur.day(lc.monthly_due_day), lc.auto_debit))
    for c in state.cards:
        if not fee_in_month(c, cur):
            continue
        fs = fee_status(c, today)
        if fs.state not in ("due", "paid") or fs.cycle != cur:
            continue
        due = due_date(cur, c.due_day)
        items.append(DueItem("fee", c.id, c.label, "fee", due, c.annual_fee, c.currency, cv(c.annual_fee, c.currency),
                             fs.state == "paid", c.annual_fee if fs.state == "paid" else 0.0, (due - today).days,
                             cur.day(c.due_day), True, counted=False))
    done = contributions_done(state.trades_month)
    for h in state.holdings:
        if not h.has_contribution:
            continue
        due = due_date(cur, h.contrib_day)
        is_done = h.id in done
        paid_amount = done.get(h.id, 0.0)
        amount = h.contrib_amount
        items.append(DueItem("contrib", h.id, h.label, h.kind, due, amount, h.contrib_currency,
                             cv(amount, h.contrib_currency), is_done,
                             convert(paid_amount, h.currency, h.contrib_currency, rates) if is_done else 0.0,
                             (due - today).days, cur.day(h.contrib_day), True, counted=h.contrib_method == "bank"))
    return items


def pending_debits(state: State, rates: dict, target: str) -> list[DueItem]:
    """Automatic debts and living costs past their date this month that are not recorded yet."""
    return [it for it in month_items(state, rates, target)
            if it.kind in ("bill", "living") and it.pending and it.amount > 0]


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
    s.items = month_items(state, rates, target)
    for it in s.items:
        if not it.counted:
            continue
        s.month_total += it.amount_target
        if it.paid:
            s.month_paid += it.amount_target
    prof = state.profile
    income = cv(prof.monthly_income, prof.monthly_income_currency) + cv(
        prof.other_income, prof.other_income_currency)
    if income > 0:
        pd = pay_date(cur, prof.payday)
        s.items.append(DueItem("income", None, "", "", pd, income, target, income, days=(pd - today).days,
                               nominal=cur.day(prof.payday)))
    s.items.sort(key=lambda i: (i.due, 0 if i.kind == "income" else 1, i.name))

    trade_in, trade_out = trade_flows(state.trades_month, state.holdings, rates, target)
    s.savings_start = cv(prof.cumulative_savings, prof.cumulative_savings_currency)
    s.income = income + trade_in
    s.outflow = s.month_total + trade_out
    s.month_end = s.savings_start + s.income - s.outflow

    # --- investments -------------------------------------------------------------
    s.portfolio = invest.summarize(state.holdings, state.prices, rates, target)
    s.invest_value = s.portfolio.value

    # --- payoff and trend ------------------------------------------------------
    infos = bill_payoffs(state)
    s.payoff = summarize_payoff(state, rates, target, infos)
    if s.payoff.status == "ok":
        horizon = min(60, max(12, s.payoff.months + 2))
    else:
        horizon = 36
    has_data = state.bills or state.living or income or state.holdings
    s.trend = simulate(state, horizon, rates, target) if has_data else []
    if s.trend:
        first = s.trend[0]
        s.net_worth = first.net_worth
        s.net_worth_parts = (first.savings, first.invest, first.debt)
    else:
        s.net_worth = s.month_end + s.invest_value - s.total_debt
        s.net_worth_parts = (s.month_end, s.invest_value, s.total_debt)

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
        params = {"name": it.name, "amount": it.amount, "currency": it.currency}
        if it.overdue:
            alerts.append(Alert("critical", "overdue", {**params, "days": -it.days}))
        elif it.pending and it.kind in ("bill", "living"):
            alerts.append(Alert("warning", "pending_debit", {**params, "date": it.due}))
        elif 0 <= it.days <= due_soon_days and it.kind in ("bill", "living"):
            alerts.append(Alert("warning", "due_soon", {**params, "days": it.days}))
    for c in state.cards:
        fs = fee_status(c, today)
        if fs.state == "due" and fs.cycle is not None and fs.cycle < cur:
            alerts.append(Alert("warning", "fee_unpaid", {"name": c.label, "period": fs.cycle,
                                                          "amount": c.annual_fee, "currency": c.currency}))
        elif fs.state == "no_month":
            alerts.append(Alert("info", "fee_no_month", {"name": c.label}))
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
    folio = s.portfolio
    if folio.missing:
        alerts.append(Alert("warning", "prices_missing", {"n": len(folio.missing), "names": folio.missing[:3]}))
    if folio.stale:
        alerts.append(Alert("warning", "prices_stale", {"n": len(folio.stale), "days": invest.STALE_DAYS}))
    if invest.uses_nisa(state.holdings):
        usage = invest.nisa_usage(state.holdings, state.trades_year, today.year, rates)
        for frame in usage.over:
            alerts.append(Alert("warning", "nisa_over", {"frame": frame}))
    order = {"critical": 0, "warning": 1, "info": 2}
    s.alerts = sorted(alerts, key=lambda a: order.get(a.level, 3))
    return s


# ---------------------------------------------------------------------------
# Month-end close
# ---------------------------------------------------------------------------
@dataclass
class CloseItem:
    kind: str                 # "bill" | "living" | "fee" | "contrib"
    target_id: int
    name: str
    sub: str
    currency: str
    planned: float
    recorded: PeriodPaid | None
    due: date
    interest_if_unpaid: float = 0.0
    is_card: bool = False     # paid through the card bill (card living cost, card fee, card contribution)

    @property
    def is_recorded(self) -> bool:
        return self.recorded is not None and self.recorded.paid


def close_items(bills: list[Bill], living: list[LivingCost], period: Period, payments: list[Payment],
                cards: list[CreditCard] | None = None, holdings: list[Holding] | None = None,
                trades: list[Trade] | None = None) -> list[CloseItem]:
    paid_b = aggregate_payments(payments, "bill")
    paid_l = aggregate_payments(payments, "living")
    items: list[CloseItem] = []
    for b in bills:
        rec = paid_b.get(b.id)
        if not (rec and rec.paid) and (b.amount <= 0 or not started(b, period)):
            continue
        items.append(CloseItem("bill", b.id, b.label, b.bill_type, b.currency,
                               planned_amount(b, period), rec, due_date(period, b.monthly_due_day),
                               monthly_interest(b)))
    for lc in living:
        rec = paid_l.get(lc.id)
        if not (rec and rec.paid) and not started(lc, period):
            continue
        items.append(CloseItem("living", lc.id, lc.label, lc.category, lc.currency,
                               round_money(lc.amount, lc.currency), rec, due_date(period, lc.monthly_due_day),
                               0.0, lc.is_card))
    for c in cards or []:
        if not fee_in_month(c, period):
            continue
        fs = fee_status(c, period.last_day)
        rec = PeriodPaid(c.annual_fee, count=1) if fs.state == "paid" else None
        items.append(CloseItem("fee", c.id, c.label, "fee", c.currency, c.annual_fee, rec,
                               due_date(period, c.due_day), 0.0, True))
    done = contributions_done(trades or [])
    for h in holdings or []:
        if not h.has_contribution:
            continue
        rec = PeriodPaid(done[h.id], count=1) if h.id in done else None
        items.append(CloseItem("contrib", h.id, h.label, h.kind, h.contrib_currency, h.contrib_amount, rec,
                               due_date(period, h.contrib_day), 0.0, h.contrib_method == "card"))
    return items


@dataclass
class CloseChoice:
    """The user's decision for one CloseItem."""

    item: CloseItem
    pay: bool
    amount: float
    paid_date: date


def close_savings(profile: Profile, choices: list[CloseChoice], rates: dict, trades: list[Trade] | None = None,
                  holdings: list[Holding] | None = None) -> tuple[float, float, float, float]:
    """(savings at start, income, cash outflow, suggested savings) in the savings currency.

    Investment trades of the month count as cash in or out; contributions still to be
    recorded count when ticked (and paid from the bank)."""
    target = profile.cumulative_savings_currency
    start = profile.cumulative_savings
    income = convert(profile.monthly_income, profile.monthly_income_currency, target, rates) + convert(
        profile.other_income, profile.other_income_currency, target, rates)
    outflow = 0.0
    for ch in choices:
        it = ch.item
        if it.is_card or it.kind == "fee":
            continue  # paid through the card bill
        if it.kind == "contrib":
            if not it.is_recorded and ch.pay:
                outflow += convert(ch.amount, it.currency, target, rates)
            continue  # recorded contributions are in `trades`
        if it.is_recorded:
            outflow += convert(it.recorded.amount, it.currency, target, rates)
        elif ch.pay:
            outflow += convert(ch.amount, it.currency, target, rates)
    cash_in, cash_out = trade_flows(trades or [], holdings or [], rates, target, include_contrib=True)
    income += cash_in
    outflow += cash_out
    suggested = round_money(start + income - outflow, target)
    return start, income, outflow, suggested

"""Plain data objects. Field names follow the database columns of Payback Management 3.x
so that old files keep working without renaming anything."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# ---- debts ------------------------------------------------------------------
# Codes are stored in the database exactly as Payback Management 3.x wrote them.
BILL_TYPES = (
    "card_loan",
    "shopping revolving",
    "cash revolving",
    "shopping credit",
    "other_loan",
    "borrow_from_people",
)
LUMP_SUM_TYPES = frozenset({"shopping credit"})          # paid in full on the next due date
NO_INTEREST_TYPES = frozenset({"shopping credit", "borrow_from_people"})  # no interest field in the form
PLAN_OPTIONAL_TYPES = frozenset({"borrow_from_people"})  # a monthly payment may be left at 0

# ---- living costs -------------------------------------------------------------
PAYMENT_METHODS = ("Cash", "Credit Card")
CATEGORY_KEYS = (
    "Rent/Mortgage", "Utilities", "Food/Groceries", "Transportation", "Communication",
    "Subscriptions", "Insurance", "Healthcare", "Childcare", "Education", "Entertainment",
    "Clothing", "Personal Care", "Household Supplies", "Pet Care", "Car - Monthly Parking",
    "Car - Gasoline/Fuel", "Car - Maintenance/Taxes", "Car - Insurance", "Car - Loan Payment",
    "Miscellaneous",
)


@dataclass
class Bill:
    """A debt that is paid back monthly (loan, revolving balance, card bill, …)."""

    id: int | None = None
    bill_type: str = "card_loan"
    bill_name: str = ""
    borrower_name: str = ""
    lender_name: str = ""
    amount: float = 0.0               # outstanding balance right now
    currency: str = "JPY"
    interest_rate: float = 0.0        # annual %
    monthly_payment: float = 0.0      # regular planned payment
    monthly_due_day: int = 27
    current_month_payment: float = 0.0  # one-off amount for `cmp_period` only
    cmp_period: str = ""              # "YYYY-MM" the one-off amount applies to
    created_date: date | None = None
    sort_order: int = 0
    note: str = ""

    @property
    def is_lump_sum(self) -> bool:
        return self.bill_type in LUMP_SUM_TYPES

    @property
    def has_interest(self) -> bool:
        return not self.is_lump_sum and self.interest_rate > 0

    @property
    def monthly_rate(self) -> float:
        return self.interest_rate / 100.0 / 12.0 if self.has_interest else 0.0

    @property
    def label(self) -> str:
        return self.bill_name or self.lender_name or self.bill_type


@dataclass
class LivingCost:
    id: int | None = None
    category: str = ""
    name: str = ""
    description: str = ""
    amount: float = 0.0
    currency: str = "JPY"
    monthly_due_day: int = 1
    payment_method: str = "Cash"      # "Cash" (cash/bank) or "Credit Card"
    created_date: date | None = None
    last_updated: date | None = None

    @property
    def is_card(self) -> bool:
        return self.payment_method == "Credit Card"

    @property
    def label(self) -> str:
        return self.name or self.category


@dataclass
class CreditCard:
    id: int | None = None
    issuer: str = ""
    name: str = ""
    due_day: int = 27
    annual_fee: float = 0.0
    paid_annual_fee: bool = False
    credit_limit: float = 0.0
    currency: str = "JPY"
    used_amount: float = 0.0
    shopping_credit_amount: float = 0.0
    shopping_revolving_amount: float = 0.0
    cash_revolving_amount: float = 0.0
    created_date: date | None = None
    last_updated: date | None = None
    # True when the same debt is already entered as bills (then it is not added
    # to the total debt a second time).
    managed_in_bills: bool = True

    @property
    def available(self) -> float:
        return self.credit_limit - self.used_amount

    @property
    def utilization(self) -> float | None:
        return self.used_amount / self.credit_limit if self.credit_limit > 0 else None

    @property
    def label(self) -> str:
        return " ".join(x for x in (self.issuer, self.name) if x) or "—"


@dataclass
class Payment:
    """One ledger line: a recorded payment, or interest added for an unpaid month."""

    id: int | None = None
    target_type: str = "bill"         # "bill" | "living"
    target_id: int = 0
    period: str = ""                  # "YYYY-MM"
    paid_date: date | None = None
    amount: float = 0.0
    currency: str = "JPY"
    interest: float = 0.0
    principal: float = 0.0
    balance_before: float | None = None
    balance_after: float | None = None
    kind: str = "payment"             # "payment" | "accrual"
    note: str = ""
    created_at: str = ""


@dataclass
class Profile:
    """Income and savings (stored in the key/value table `savings`)."""

    cumulative_savings: float = 0.0           # savings at the end of the last closed month
    cumulative_savings_currency: str = "JPY"
    monthly_income: float = 0.0               # this month's income
    monthly_income_currency: str = "JPY"
    other_income: float = 0.0                 # extra income this month (bonus, …)
    other_income_currency: str = "JPY"
    other_income_type: str = ""
    expected_income: float = 0.0              # income expected from next month on
    expected_income_currency: str = "JPY"
    extra_income: float = 0.0                 # additional monthly income expected
    extra_income_currency: str = "JPY"
    payday: int = 25
    simulation_months: int = 12

    def copy(self) -> "Profile":
        return Profile(**self.__dict__)


@dataclass
class Totals:
    """Amounts per currency (used for table footers)."""

    by_currency: dict = field(default_factory=dict)

    def add(self, currency: str, value: float) -> None:
        self.by_currency[currency] = self.by_currency.get(currency, 0.0) + float(value)

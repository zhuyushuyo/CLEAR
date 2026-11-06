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
# "Cash" = paid by hand (cash, bank transfer), "Auto Debit" = taken from the bank account
# automatically on the due date, "Credit Card" = paid through next month's card bill.
PAYMENT_METHODS = ("Cash", "Auto Debit", "Credit Card")
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
    auto_debit: bool = True           # taken from the bank account automatically on the due date

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
    payment_method: str = "Cash"      # see PAYMENT_METHODS
    created_date: date | None = None
    last_updated: date | None = None

    @property
    def is_card(self) -> bool:
        return self.payment_method == "Credit Card"

    @property
    def auto_debit(self) -> bool:
        return self.payment_method == "Auto Debit"

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
    fee_month: int = 0                # month the annual fee is billed (1-12, 0 = not set)
    fee_paid_period: str = ""         # "YYYY-MM" when the fee was last paid ("YYYY" when only the year is known)

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


# ---- investments (4.1) ------------------------------------------------------------
HOLDING_KINDS = ("stock", "crypto", "metal", "manual")
ACCOUNTS = ("taxable", "nisa_tsumitate", "nisa_growth", "ideco", "exchange", "other")
NISA_ACCOUNTS = frozenset({"nisa_tsumitate", "nisa_growth"})
METALS = ("gold", "silver", "platinum", "palladium")
METAL_UNITS = ("g", "oz", "kg")
PRICE_SOURCES = ("yahoo", "coingecko", "bitflyer", "manual")
TRADE_KINDS = ("buy", "sell", "dividend", "fee")
CONTRIB_METHODS = ("bank", "card")


@dataclass
class Holding:
    """One position: a stock/ETF, a coin, a metal or a hand-valued asset."""

    id: int | None = None
    kind: str = "stock"               # see HOLDING_KINDS
    symbol: str = ""                  # Yahoo ticker, CoinGecko id, bitFlyer product or metal code
    name: str = ""
    account: str = "taxable"          # see ACCOUNTS
    quantity: float = 0.0             # shares, coins, grams/ounces/kilograms (1 for hand-valued assets)
    unit: str = ""                    # metals: g | oz | kg
    avg_cost: float = 0.0             # average cost per unit, in `currency`
    currency: str = "JPY"             # currency of the cost and of the values shown for this holding
    price_source: str = "yahoo"       # see PRICE_SOURCES
    quote_currency: str = ""          # currency the source quotes in (USD for metals, JPY for 7203.T, …)
    manual_price: float = 0.0         # per unit in `currency` (hand-valued assets: the whole value)
    adjust_pct: float = 0.0           # metals: premium (+) or discount (-) on the international price, %
    contrib_amount: float = 0.0       # monthly contribution (積立), in `contrib_currency`
    contrib_currency: str = "JPY"
    contrib_day: int = 27
    contrib_method: str = "bank"      # bank (paid this month) | card (paid with next month's card bill)
    note: str = ""
    sort_order: int = 0
    created_date: date | None = None
    last_updated: date | None = None

    @property
    def label(self) -> str:
        return self.name or self.symbol or "—"

    @property
    def is_manual(self) -> bool:
        return self.kind == "manual" or self.price_source == "manual"

    @property
    def has_contribution(self) -> bool:
        return self.contrib_amount > 0

    @property
    def is_nisa(self) -> bool:
        return self.account in NISA_ACCOUNTS


@dataclass
class Trade:
    """One investment event. `amount` is the cash moved, in the holding's currency."""

    id: int | None = None
    holding_id: int = 0
    trade_date: date | None = None
    kind: str = "buy"                 # see TRADE_KINDS
    quantity: float = 0.0
    price: float = 0.0                # per unit, in the holding's currency
    fee: float = 0.0
    amount: float = 0.0               # buy: paid (incl. fee) · sell: received (after fee) · dividend/fee: cash
    currency: str = "JPY"
    qty_before: float = 0.0
    qty_after: float = 0.0
    avg_before: float = 0.0
    avg_after: float = 0.0
    realized: float = 0.0             # sell: profit or loss against the average cost
    value_before: float | None = None  # hand-valued assets: value before / after the trade
    value_after: float | None = None
    period: str = ""                  # "YYYY-MM"
    is_contrib: bool = False          # made by a monthly contribution
    cash_effect: bool = True          # paid from / paid into savings this month
    account: str = ""                 # holding's account at the time (for NISA limits)
    note: str = ""
    created_at: str = ""

    @property
    def cash(self) -> float:
        """Signed effect on savings in the holding's currency (out < 0 < in)."""
        if not self.cash_effect:
            return 0.0
        if self.kind in ("buy", "fee"):
            return -self.amount
        return self.amount


@dataclass
class Price:
    """The last price fetched for one symbol."""

    source: str
    symbol: str
    price: float
    currency: str
    prev_close: float | None = None
    fetched_at: str = ""

    @property
    def key(self) -> str:
        return price_key(self.source, self.symbol)


def price_key(source: str, symbol: str) -> str:
    return f"{source}:{symbol}"


@dataclass
class NetWorthPoint:
    """Net worth recorded at a month-end close (P1)."""

    period: str
    currency: str
    savings: float
    investments: float
    debts: float
    net_worth: float
    projected_next: float | None = None
    recorded_at: str = ""
    rates: dict = field(default_factory=dict)


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

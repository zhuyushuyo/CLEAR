"""Input forms (U6): validated fields, only the fields that apply, a live preview."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
                             QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QTableWidget,
                             QVBoxLayout, QWidget)

from . import engine
from .config import DEFAULT_HIDDEN
from .i18n import (bill_type_label, category_from_label, category_label, fmt_date, fmt_md, fmt_period,
                   method_label, money, month_name, t)
from .models import (BILL_TYPES, CATEGORY_KEYS, LUMP_SUM_TYPES, NO_INTEREST_TYPES, PAYMENT_METHODS,
                     PLAN_OPTIONAL_TYPES, Bill, CreditCard, LivingCost)
from .money import round_money
from .periods import Period
from .widgets import (RIGHT, CurrencyCombo, DateField, DayCombo, MoneySpin, button, check_item, item, label,
                      repolish)

DELETE = 2  # QDialog result code for "delete"


class PreviewLabel(QLabel):
    """The hint line at the foot of a form: hidden while it has nothing to say."""

    def __init__(self):
        super().__init__("")
        self.setObjectName("Hint")
        self.setWordWrap(True)
        self.hide()

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        super().setText(text)
        self.setVisible(bool(text))


class FormDialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None, deletable: bool = False, ok_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(520)
        self._fields: dict[int, object] = {}
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 18)
        outer.setSpacing(14)
        outer.addWidget(label(title, "DialogTitle"))
        self.form = QFormLayout()
        self.form.setHorizontalSpacing(16)
        self.form.setVerticalSpacing(10)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        outer.addLayout(self.form)
        self.preview = PreviewLabel()
        outer.addWidget(self.preview)
        self.error = label("", "Error", wrap=True)
        self.error.hide()
        outer.addWidget(self.error)
        row = QHBoxLayout()
        if deletable:
            row.addWidget(button(t("common.delete"), "danger", "fa5s.trash-alt", lambda: self.done(DELETE)))
        row.addStretch(1)
        row.addWidget(button(t("common.cancel"), slot=self.reject))
        self.ok_btn = button(ok_text or t("common.save"), "primary", slot=self._try_accept)
        self.ok_btn.setDefault(True)
        row.addWidget(self.ok_btn)
        outer.addLayout(row)

    def row(self, text: str, widget, hint: str = ""):
        field = widget
        if hint:
            box = QVBoxLayout()
            box.setSpacing(2)
            if isinstance(widget, QWidget):
                box.addWidget(widget)
            else:
                box.addLayout(widget)
            box.addWidget(label(hint, "Hint", wrap=True))
            field = box
        self.form.addRow(text.replace("&", "&&"), field)  # the row label gets a buddy: "&" would be a mnemonic
        if isinstance(widget, QWidget):
            self._fields[id(widget)] = field
        return field

    def set_row_visible(self, widget: QWidget, visible: bool) -> None:
        self.form.setRowVisible(self._fields.get(id(widget), widget), visible)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.fit_height()

    def fit_height(self) -> None:
        """Make room for wrapped text that would be cut off. Qt's minimum size counts a wrapped label as one
        line, and a new window is capped at two thirds of the screen height, so a long hint could lose its
        last line on a small screen. Each such label gets the height it needs as its minimum."""
        lay = self.layout()
        if lay is None:
            return
        for _ in range(3):
            lay.activate()
            cut = [(lbl, lbl.heightForWidth(lbl.width())) for lbl in self.findChildren(QLabel)
                   if lbl.isVisible() and lbl.wordWrap() and lbl.text()]
            cut = [(lbl, need) for lbl, need in cut if need > lbl.height()]
            if not cut:
                return
            for lbl, need in cut:
                lbl.setMinimumHeight(need)
            lay.activate()
            self.resize(self.width(), max(self.height(), lay.totalMinimumSize().height()))

    def fail(self, message: str, widget: QWidget | None = None) -> None:
        self.error.setText(message)
        self.error.show()
        self.fit_height()
        if widget is not None:
            widget.setProperty("invalid", True)
            repolish(widget)
            widget.setFocus()

    def clear_errors(self, *widgets: QWidget) -> None:
        self.error.hide()
        for w in widgets:
            w.setProperty("invalid", False)
            repolish(w)

    def validate(self) -> bool:
        return True

    def _try_accept(self) -> None:
        if self.validate():
            self.accept()


def money_row(spin: MoneySpin, combo: CurrencyCombo) -> QHBoxLayout:
    box = QHBoxLayout()
    box.setSpacing(8)
    box.addWidget(spin, 1)
    box.addWidget(combo)
    return box


# ---------------------------------------------------------------------------------------------------
class BillDialog(FormDialog):
    def __init__(self, parent: QWidget | None, bill: Bill | None, current: Period, default_currency: str):
        super().__init__(t("bill.title_edit" if bill else "bill.title_add"), parent, deletable=bill is not None)
        self.current = current
        self.src = bill
        b = bill or Bill(currency=default_currency, created_date=date.today())
        self.name = QLineEdit(b.bill_name)
        self.name.setPlaceholderText(t("bill.f.name_ph"))
        self.type = QComboBox()
        for code in BILL_TYPES:
            self.type.addItem(bill_type_label(code), code)
        self.type.setCurrentIndex(max(0, self.type.findData(b.bill_type)))
        self.lender = QLineEdit(b.lender_name)
        self.borrower = QLineEdit(b.borrower_name)
        self.currency = CurrencyCombo(b.currency)
        self.balance = MoneySpin(b.currency)
        self.balance.setValue(b.amount)
        self.rate = MoneySpin("USD")
        self.rate.setRange(0, 100)
        self.rate.setValue(b.interest_rate)
        self.rate.setMinimumWidth(100)
        self.monthly = MoneySpin(b.currency)
        self.monthly.setValue(b.monthly_payment)
        self.one_off = MoneySpin(b.currency)
        self.one_off.setValue(b.current_month_payment if b.cmp_period == str(current) else 0)
        self.due = DayCombo()
        self.due.setValue(b.monthly_due_day)
        self.auto_debit = QCheckBox(t("bill.f.auto_debit"))
        self.auto_debit.setChecked(b.auto_debit if bill else b.bill_type not in PLAN_OPTIONAL_TYPES)
        self.created = DateField(b.created_date or date.today())

        self.row(t("bill.f.name"), self.name)
        self.row(t("bill.f.type"), self.type)
        self.row(t("bill.f.lender"), self.lender)
        self.row(t("bill.f.borrower"), self.borrower)
        self.row(t("bill.f.balance"), money_row(self.balance, self.currency))
        self.row(t("bill.f.rate"), self.rate)
        self.row(t("bill.f.monthly"), self.monthly)
        self.row(t("bill.f.this_month") + f"\n({fmt_period(current)})", self.one_off, t("bill.f.this_month_hint"))
        self.row(t("bill.f.due_day"), self.due)
        self.row("", self.auto_debit, t("bill.f.auto_debit_hint"))
        self.row(t("bill.f.created"), self.created)
        self.type_hint = label("", "Hint", wrap=True)
        self.form.addRow("", self.type_hint)

        self.type.currentIndexChanged.connect(self._sync)
        self.currency.currentTextChanged.connect(self._currency_changed)
        for w in (self.balance, self.rate, self.monthly, self.one_off):
            w.valueChanged.connect(self._update_preview)
        self.due.currentIndexChanged.connect(self._update_preview)
        self._sync()
        self.name.setFocus()

    def _currency_changed(self, cur: str) -> None:
        for w in (self.balance, self.monthly, self.one_off):
            w.set_currency(cur)
        self._update_preview()

    def _code(self) -> str:
        return self.type.currentData()

    def _sync(self) -> None:
        code = self._code()
        if self.src is None:  # a new debt: money from people is usually paid by hand
            self.auto_debit.setChecked(code not in PLAN_OPTIONAL_TYPES)
        lump = code in LUMP_SUM_TYPES
        self.set_row_visible(self.rate, code not in NO_INTEREST_TYPES)
        self.set_row_visible(self.monthly, not lump)
        self.set_row_visible(self.one_off, not lump)
        hint = t("bill.lump_hint") if lump else t("bill.people_hint") if code in PLAN_OPTIONAL_TYPES else ""
        self.type_hint.setText(hint)
        self.type_hint.setVisible(bool(hint))
        self._update_preview()

    def result_bill(self) -> Bill:
        code = self._code()
        cur = self.currency.currentText()
        b = Bill(**self.src.__dict__) if self.src else Bill()
        b.bill_name = self.name.text().strip()
        b.bill_type = code
        b.lender_name = self.lender.text().strip()
        b.borrower_name = self.borrower.text().strip()
        b.currency = cur
        b.amount = round_money(self.balance.value(), cur)
        b.interest_rate = 0.0 if code in NO_INTEREST_TYPES else self.rate.value()
        b.monthly_payment = 0.0 if code in LUMP_SUM_TYPES else round_money(self.monthly.value(), cur)
        one_off = 0.0 if code in LUMP_SUM_TYPES else round_money(self.one_off.value(), cur)
        if one_off > 0:
            b.current_month_payment, b.cmp_period = one_off, str(self.current)
        elif b.cmp_period == str(self.current):
            b.current_month_payment, b.cmp_period = 0.0, ""
        b.monthly_due_day = self.due.value()
        b.auto_debit = self.auto_debit.isChecked()
        b.created_date = self.created.value()
        return b

    def _update_preview(self) -> None:
        b = self.result_bill()
        info = engine.payoff_info(b, self.current)
        if info.status == "ok":
            text = t("bill.preview.ok", period=fmt_period(info.period), n=info.months,
                     interest=money(info.remaining_interest, b.currency))
            tone = None
        elif info.status == "never":
            text, tone = t("bill.preview.never", interest=money(info.interest_now, b.currency)), "critical"
        elif info.status == "no_plan":
            text, tone = t("bill.preview.noplan"), "warning"
        else:
            text, tone = t("bill.preview.none"), None
        self.preview.setText(text)
        self.preview.setProperty("tone", tone or "")
        repolish(self.preview)

    def validate(self) -> bool:
        self.clear_errors(self.name, self.monthly)
        if not self.name.text().strip() and not self.lender.text().strip():
            self.fail(t("bill.err.name"), self.name)
            return False
        code = self._code()
        if (code not in LUMP_SUM_TYPES and code not in PLAN_OPTIONAL_TYPES and self.balance.value() > 0
                and self.monthly.value() <= 0):
            self.fail(t("bill.err.monthly"), self.monthly)
            return False
        return True


# ---------------------------------------------------------------------------------------------------
class LivingDialog(FormDialog):
    def __init__(self, parent: QWidget | None, lc: LivingCost | None, default_currency: str):
        super().__init__(t("living.title_edit" if lc else "living.title_add"), parent, deletable=lc is not None)
        self.src = lc
        x = lc or LivingCost(currency=default_currency, category="Food/Groceries")
        self.category = QComboBox()
        self.category.setEditable(True)
        for key in CATEGORY_KEYS:
            self.category.addItem(category_label(key), key)
        idx = self.category.findData(x.category)
        if idx >= 0:
            self.category.setCurrentIndex(idx)
        else:
            self.category.setEditText(x.category)
        self.name = QLineEdit(x.name)
        self.name.setPlaceholderText(t("living.f.name_ph"))
        self.detail = QLineEdit(x.description)
        self.currency = CurrencyCombo(x.currency)
        self.amount = MoneySpin(x.currency)
        self.amount.setValue(x.amount)
        self.due = DayCombo()
        self.due.setValue(x.monthly_due_day)
        self.method = QComboBox()
        for code in PAYMENT_METHODS:
            self.method.addItem(method_label(code), code)
        self.method.setCurrentIndex(max(0, self.method.findData(x.payment_method)))
        self.row(t("living.f.category"), self.category)
        self.row(t("living.f.name"), self.name)
        self.row(t("living.f.detail"), self.detail)
        self.row(t("living.f.amount"), money_row(self.amount, self.currency))
        self.row(t("living.f.due_day"), self.due)
        self.row(t("living.f.method"), self.method)
        if lc is not None:
            self.preview.setText(t("living.f.dates", created=fmt_date(lc.created_date),
                                   updated=fmt_date(lc.last_updated)))
        self.currency.currentTextChanged.connect(self.amount.set_currency)
        self.name.setFocus()

    def result_living(self) -> LivingCost:
        x = LivingCost(**self.src.__dict__) if self.src else LivingCost(created_date=date.today())
        x.category = category_from_label(self.category.currentText())
        x.name = self.name.text().strip()
        x.description = self.detail.text().strip()
        x.currency = self.currency.currentText()
        x.amount = round_money(self.amount.value(), x.currency)
        x.monthly_due_day = self.due.value()
        x.payment_method = self.method.currentData()
        x.last_updated = date.today()  # R14: the edited date is set automatically
        return x

    def validate(self) -> bool:
        self.clear_errors(self.name, self.amount)
        if not self.name.text().strip():
            self.fail(t("living.err.name"), self.name)
            return False
        if self.amount.value() <= 0:
            self.fail(t("living.err.amount"), self.amount)
            return False
        return True


# ---------------------------------------------------------------------------------------------------
class CardDialog(FormDialog):
    def __init__(self, parent: QWidget | None, card: CreditCard | None, default_currency: str,
                 today: date | None = None):
        super().__init__(t("card.title_edit" if card else "card.title_add"), parent, deletable=card is not None)
        self.src = card
        self.today = today or date.today()
        c = card or CreditCard(currency=default_currency, created_date=date.today())
        self.issuer = QLineEdit(c.issuer)
        self.issuer.setPlaceholderText(t("card.f.issuer_ph"))
        self.name = QLineEdit(c.name)
        self.due = DayCombo()
        self.due.setValue(c.due_day)
        self.currency = CurrencyCombo(c.currency)
        self.limit = MoneySpin(c.currency)
        self.limit.setValue(c.credit_limit)
        self.lump = MoneySpin(c.currency)
        self.lump.setValue(c.shopping_credit_amount)
        self.shop = MoneySpin(c.currency)
        self.shop.setValue(c.shopping_revolving_amount)
        self.cash = MoneySpin(c.currency)
        self.cash.setValue(c.cash_revolving_amount)
        self.used = MoneySpin(c.currency)
        self.used.setValue(c.used_amount)
        parts = c.shopping_credit_amount + c.shopping_revolving_amount + c.cash_revolving_amount
        self.auto = QCheckBox(t("card.f.used_auto"))
        self.auto.setChecked(card is None or abs(parts - c.used_amount) < 0.005)
        self.fee = MoneySpin(c.currency)
        self.fee.setValue(c.annual_fee)
        self.fee_month = QComboBox()
        self.fee_month.addItem(t("card.f.fee_month_none"), 0)
        for m in range(1, 13):
            self.fee_month.addItem(month_name(m), m)
        self.fee_month.setCurrentIndex(max(0, self.fee_month.findData(c.fee_month or 0)))
        self.fee_month.setMaximumWidth(140)
        self.fee_paid = QCheckBox(t("card.f.fee_paid"))
        self._was_paid = engine.fee_status(c, self.today).state == "paid" if card else False
        self.fee_paid.setChecked(self._was_paid)
        self.managed = QCheckBox(t("card.f.managed"))
        self.managed.setChecked(c.managed_in_bills)
        used_box = QVBoxLayout()
        used_box.setSpacing(4)
        used_box.addWidget(self.used)
        used_box.addWidget(self.auto)
        self.row(t("card.f.issuer"), self.issuer)
        self.row(t("card.f.name"), self.name)
        self.row(t("card.f.due_day"), self.due)
        self.row(t("card.f.limit"), money_row(self.limit, self.currency))
        self.row(t("card.f.lump"), self.lump)
        self.row(t("card.f.shop_rev"), self.shop)
        self.row(t("card.f.cash_rev"), self.cash)
        self.row(t("card.f.used"), used_box)
        self.row(t("card.f.fee"), self.fee)
        self.row(t("card.f.fee_month"), self.fee_month)
        self.row("", self.fee_paid, t("card.f.fee_hint"))
        self.row("", self.managed, t("card.f.managed_hint"))
        for w in (self.lump, self.shop, self.cash):
            w.valueChanged.connect(self._sum)
        self.auto.toggled.connect(self._sum)
        self.fee.valueChanged.connect(self._fee_changed)
        self._fee_changed(c.annual_fee)
        self.currency.currentTextChanged.connect(self._currency_changed)
        self._sum()
        self.name.setFocus()

    def _currency_changed(self, cur: str) -> None:
        for w in (self.limit, self.lump, self.shop, self.cash, self.used, self.fee):
            w.set_currency(cur)

    def _fee_changed(self, value: float) -> None:
        self.fee_paid.setEnabled(value > 0)
        self.fee_month.setEnabled(value > 0)

    def _sum(self) -> None:
        self.used.setEnabled(not self.auto.isChecked())
        if self.auto.isChecked():
            self.used.setValue(self.lump.value() + self.shop.value() + self.cash.value())

    def result_card(self) -> CreditCard:
        c = CreditCard(**self.src.__dict__) if self.src else CreditCard(created_date=date.today())
        c.issuer = self.issuer.text().strip()
        c.name = self.name.text().strip()
        c.due_day = self.due.value()
        c.currency = self.currency.currentText()
        c.credit_limit = self.limit.value()
        c.shopping_credit_amount = self.lump.value()
        c.shopping_revolving_amount = self.shop.value()
        c.cash_revolving_amount = self.cash.value()
        c.used_amount = self.used.value()
        c.annual_fee = self.fee.value()
        c.fee_month = int(self.fee_month.currentData() or 0)
        paid = self.fee_paid.isChecked() and c.annual_fee > 0
        if not paid:
            c.fee_paid_period = ""
        elif not (self._was_paid and engine.fee_status(c, self.today).state == "paid"):
            c.fee_paid_period = str(Period.from_date(self.today))
        elif c.fee_month and Period.try_parse(c.fee_paid_period or "") is None:
            # 4.0 only knew "paid this year": now that the billing month is known, it means this cycle
            c.fee_paid_period = str(engine.fee_cycle(c.fee_month, self.today))
        c.paid_annual_fee = paid
        c.managed_in_bills = self.managed.isChecked()
        c.last_updated = date.today()
        return c

    def validate(self) -> bool:
        self.clear_errors(self.name)
        if not self.name.text().strip() and not self.issuer.text().strip():
            self.fail(t("card.err.name"), self.name)
            return False
        return True


# ---------------------------------------------------------------------------------------------------
class PaymentDialog(FormDialog):
    """Record a payment for a debt: amount, interest part, and the balance afterwards."""

    def __init__(self, parent: QWidget | None, bill: Bill, current: Period, today: date,
                 interest_already_charged: bool, new_balance: float | None = None):
        super().__init__(t("pay.title", name=bill.label), parent, ok_text=t("pay.ok"))
        self.bill = bill
        self.new_balance = new_balance
        self.drop = max(0.0, bill.amount - new_balance) if new_balance is not None else 0.0
        cur = bill.currency
        planned = engine.planned_amount(bill, current)
        if new_balance is not None:
            info = t("pay.from_balance", old=money(bill.amount, cur), new=money(new_balance, cur),
                     drop=money(self.drop, cur))
        else:
            info = t("pay.info", balance=money(bill.amount, cur), rate=f"{bill.interest_rate:g}",
                     planned=money(planned, cur))
        self.form.addRow(label(info, "Muted", wrap=True))
        self.paid_on = DateField(today)
        self.amount = MoneySpin(cur)
        self.amount.setValue(planned if planned > 0 else bill.amount)
        self.interest = MoneySpin(cur)
        self.interest.setValue(0.0 if interest_already_charged else engine.monthly_interest(bill))
        self.note = QLineEdit()
        self.row(t("pay.f.date"), self.paid_on)
        self.row(t("pay.f.amount"), self.amount)
        self.row(t("pay.f.interest"), self.interest,
                 t("pay.interest_once") if interest_already_charged and bill.has_interest else "")
        self.set_row_visible(self.interest, bill.has_interest)
        if new_balance is not None:  # the interest is what the payment covers beyond the drop
            self.interest.setEnabled(False)
            self.set_row_visible(self.interest, True)
            self.amount.setValue(max(planned, self.drop))
        self.row(t("pay.f.note"), self.note)
        self.amount.valueChanged.connect(self._update)
        self.interest.valueChanged.connect(self._update)
        self._update()
        self.amount.setFocus()
        self.amount.selectAll()

    def _update(self) -> None:
        if self.new_balance is not None:
            self.interest.blockSignals(True)
            self.interest.setValue(max(0.0, self.amount.value() - self.drop))
            self.interest.blockSignals(False)
        split = engine.split_payment(self.bill, self.bill.amount, self.amount.value(), self.interest.value())
        cur = self.bill.currency
        text = t("pay.preview", principal=money(split.principal, cur), after=money(split.balance_after, cur))
        tone = None
        if split.principal < 0:
            text += "\n" + t("pay.warn_under", diff=money(-split.principal, cur))
            tone = "critical"
        self.preview.setText(text)
        self.preview.setProperty("tone", tone or "")
        repolish(self.preview)

    def values(self) -> tuple[date, float, float | None, str]:
        interest = self.interest.value() if (self.bill.has_interest or self.new_balance is not None) else 0.0
        return self.paid_on.value(), self.amount.value(), interest, self.note.text().strip()

    def validate(self) -> bool:
        self.clear_errors(self.amount)
        if self.new_balance is not None and self.amount.value() + 1e-9 < self.drop:
            self.fail(t("pay.err.below_drop", drop=money(self.drop, self.bill.currency)), self.amount)
            return False
        return True


# ---------------------------------------------------------------------------------------------------
TABLE_COLUMNS = {
    "bills": ("debts.col.name", "debts.col.type", "debts.col.lender", "debts.col.borrower", "debts.col.balance",
              "debts.col.currency", "debts.col.rate", "debts.col.monthly", "debts.col.this_month",
              "debts.col.due_day", "debts.col.status", "debts.col.payoff", "debts.col.interest_left",
              "debts.col.created"),
    "cards": ("cards.col.issuer", "cards.col.name", "cards.col.due_day", "cards.col.limit", "cards.col.used",
              "cards.col.available", "cards.col.util", "cards.col.lump", "cards.col.shop_rev", "cards.col.cash_rev",
              "cards.col.fee", "cards.col.currency", "cards.col.managed", "cards.col.updated"),
    "living": ("living.col.category", "living.col.name", "living.col.detail", "living.col.amount",
               "living.col.currency", "living.col.method", "living.col.due_day", "living.col.paid",
               "living.col.created", "living.col.updated"),
    "plan": ("plan.col.month", "plan.col.income", "plan.col.debt", "plan.col.living", "plan.col.contrib",
             "plan.col.net", "plan.col.savings", "plan.col.invest", "plan.col.balance", "plan.col.worth"),
    "invest": ("invest.col.name", "invest.col.kind", "invest.col.account", "invest.col.qty", "invest.col.cost",
               "invest.col.price", "invest.col.value", "invest.col.gain", "invest.col.gain_pct", "invest.col.day",
               "invest.col.contrib", "invest.col.currency", "invest.col.source", "invest.col.updated"),
}
DEFAULT_WIDTHS = {
    "bills": [156, 136, 112, 70, 104, 54, 58, 92, 98, 132, 82, 104, 92, 96],
    "cards": [110, 150, 60, 100, 100, 100, 60, 84, 126, 126, 230, 56, 112, 96],
    "living": [140, 150, 170, 100, 56, 140, 132, 64, 96, 96],
    "plan": [],
    "invest": [170, 112, 150, 84, 104, 104, 116, 104, 76, 96, 130, 56, 150, 120],
}
ALWAYS_VISIBLE = {"bills": {0}, "cards": {1}, "living": {1}, "plan": {0}, "invest": {0}}


class ColumnsDialog(QDialog):
    """Choose visible columns for every table (R8: works for all tables, not just one)."""

    def __init__(self, parent: QWidget | None, hidden: dict[str, list[int]]):
        super().__init__(parent)
        self.setWindowTitle(t("cols.title"))
        self.setMinimumSize(460, 480)
        self.hidden = {k: set(v) for k, v in hidden.items()}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(t("cols.title"), "DialogTitle"))
        self.table = QComboBox()
        for key in TABLE_COLUMNS:
            self.table.addItem(t(f"cols.t.{key}"), key)
        lay.addWidget(self.table)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(button(t("cols.reset"), slot=self._reset))
        row.addStretch(1)
        row.addWidget(button(t("common.cancel"), slot=self.reject))
        row.addWidget(button(t("common.save"), "primary", slot=self.accept))
        lay.addLayout(row)
        self.table.currentIndexChanged.connect(self._load)
        self.list.itemChanged.connect(self._changed)
        self._load()

    def _key(self) -> str:
        return self.table.currentData()

    def _load(self) -> None:
        key = self._key()
        self.list.blockSignals(True)
        self.list.clear()
        hidden = self.hidden.setdefault(key, set(DEFAULT_HIDDEN.get(key, [])))
        for i, name in enumerate(TABLE_COLUMNS[key]):
            it = QListWidgetItem(t(name))
            it.setData(Qt.ItemDataRole.UserRole, i)
            if i in ALWAYS_VISIBLE.get(key, set()):
                it.setFlags(Qt.ItemFlag.ItemIsUserCheckable)  # shown, not changeable
                it.setCheckState(Qt.CheckState.Checked)
            else:
                it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                it.setCheckState(Qt.CheckState.Unchecked if i in hidden else Qt.CheckState.Checked)
            self.list.addItem(it)
        self.list.blockSignals(False)

    def _changed(self, it: QListWidgetItem) -> None:
        i = it.data(Qt.ItemDataRole.UserRole)
        hidden = self.hidden.setdefault(self._key(), set())
        if it.checkState() == Qt.CheckState.Checked:
            hidden.discard(i)
        else:
            hidden.add(i)

    def _reset(self) -> None:
        self.hidden[self._key()] = set(DEFAULT_HIDDEN.get(self._key(), []))
        self._load()

    def result_hidden(self) -> dict[str, list[int]]:
        return {k: sorted(v) for k, v in self.hidden.items()}


# ---------------------------------------------------------------------------------------------------
class DebitDialog(QDialog):
    """B2: automatic debits past their date, recorded in one go after a quick check."""

    def __init__(self, parent: QWidget | None, items: list[engine.DueItem]):
        super().__init__(parent)
        self.setWindowTitle(t("debit.title"))
        self.setMinimumSize(640, 360)
        self.items = items
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 18)
        lay.setSpacing(12)
        lay.addWidget(label(t("debit.title"), "DialogTitle"))
        lay.addWidget(label(t("debit.intro"), "Hint", wrap=True))
        headers = ["", t("home.month.col.date"), t("home.month.col.item"), t("home.month.col.kind"),
                   t("home.month.col.amount")]
        tbl = QTableWidget(len(items), len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.verticalHeader().setVisible(False)
        tbl.verticalHeader().setDefaultSectionSize(38)
        tbl.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        tbl.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tbl.setShowGrid(False)
        tbl.setAlternatingRowColors(True)
        head = tbl.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for col, w in ((0, 36), (1, 110), (3, 150), (4, 150)):
            tbl.setColumnWidth(col, w)
        tbl.horizontalHeaderItem(4).setTextAlignment(RIGHT)
        self.spins: list[MoneySpin] = []
        for r, it in enumerate(items):
            tbl.setItem(r, 0, check_item(True, r))
            tbl.setItem(r, 1, item(fmt_md(it.due), tone="text_muted"))
            tbl.setItem(r, 2, item(it.name))
            kind = bill_type_label(it.sub) if it.kind == "bill" else category_label(it.sub)
            tbl.setItem(r, 3, item(kind, tone="text_muted"))
            spin = MoneySpin(it.currency)
            spin.setValue(it.amount)
            spin.setMinimumWidth(120)
            self.spins.append(spin)
            tbl.setCellWidget(r, 4, spin)
        self.table = tbl
        lay.addWidget(tbl, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button(t("debit.later"), slot=self.reject))
        ok = button(t("debit.record"), "primary", "fa5s.check", self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)

    def chosen(self) -> list[tuple[engine.DueItem, float]]:
        out = []
        for r, it in enumerate(self.items):
            cell = self.table.item(r, 0)
            if cell is not None and cell.checkState() == Qt.CheckState.Checked:
                out.append((it, self.spins[r].value()))
        return out

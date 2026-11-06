"""Reusable widgets. Colours come from the theme (object names / properties), never inline."""

from __future__ import annotations

from datetime import date

from PyQt6.QtCore import QDate, QLocale, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDoubleSpinBox, QFrame, QHBoxLayout,
                             QHeaderView, QLabel, QMessageBox, QPushButton, QSizePolicy, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme
from .i18n import t
from .money import CURRENCIES, decimals

try:  # qtawesome is optional: the app still works without icons
    import qtawesome as qta
except Exception:  # pragma: no cover
    qta = None

RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter


def icon(name: str, color: str | None = None) -> QIcon:
    if qta is None:
        return QIcon()
    try:
        return qta.icon(name, color=color or theme.current().text_muted)
    except Exception:
        return QIcon()


def repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def set_tone(widget: QWidget, tone: str | None) -> None:
    widget.setProperty("tone", tone or "")
    repolish(widget)


def label(text: str = "", name: str | None = None, wrap: bool = False, tone: str | None = None) -> QLabel:
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    if wrap:
        lbl.setWordWrap(True)
    if tone:
        lbl.setProperty("tone", tone)
    return lbl


def button(text: str, kind: str | None = None, icon_name: str | None = None, slot=None) -> QPushButton:
    btn = QPushButton(text.replace("&", "&&"))  # a single & would become a keyboard mnemonic
    if kind:
        btn.setProperty("kind", kind)
    if icon_name:
        color = theme.current().on_accent if kind == "primary" else (
            theme.current().critical if kind == "danger" else theme.current().text_muted)
        btn.setIcon(icon(icon_name, color))
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


class Card(QFrame):
    """A white panel with a title row and a body layout."""

    def __init__(self, title: str = "", subtitle: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 16, 18, 18)
        outer.setSpacing(12)
        self.title_label = label(title, "CardTitle")
        self.sub_label = label(subtitle, "CardSub", wrap=True)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        if title or subtitle:
            head = QHBoxLayout()
            head.setSpacing(12)
            texts = QVBoxLayout()
            texts.setSpacing(2)
            texts.addWidget(self.title_label)
            texts.addWidget(self.sub_label)
            self.sub_label.setVisible(bool(subtitle))
            head.addLayout(texts, 1)
            head.addLayout(self.actions)
            outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)

    def set_subtitle(self, text: str) -> None:
        self.sub_label.setText(text)
        self.sub_label.setVisible(bool(text))


class KpiCard(QFrame):
    """A titled number. The number's font shrinks (25 → 16 px) when the card is narrow, so a row of
    cards never forces the page wider than the window."""

    MAX_PX, MIN_PX = 25, 16

    def __init__(self, title: str, icon_name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setMinimumHeight(132)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.title = label(title, "KpiLabel")
        head.addWidget(self.title, 1)
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icon(icon_name, theme.current().text_faint).pixmap(16, 16))
            head.addWidget(ic)
        lay.addLayout(head)
        self.value = label("—", "KpiValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.value.setMinimumWidth(1)
        self._px = self.MAX_PX
        lay.addWidget(self.value)
        self.sub = label("", "KpiSub", wrap=True)
        lay.addWidget(self.sub)
        lay.addStretch(1)

    def set(self, value: str, sub: str = "", tone: str | None = None) -> None:
        self.value.setText(value)
        self.sub.setText(sub)
        set_tone(self.value, tone)
        self._fit()

    def _fit(self) -> None:
        room = self.value.width() if self.value.width() > 10 else self.width() - 36
        if room <= 10:
            return
        font = QFont(self.value.font())
        px = self.MAX_PX
        while px > self.MIN_PX:
            font.setPixelSize(px)
            if QFontMetrics(font).horizontalAdvance(self.value.text()) <= room:
                break
            px -= 1
        if px != self._px:
            self._px = px
            self.value.setStyleSheet(f"font-size: {px}px;" if px != self.MAX_PX else "")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()


class Banner(QFrame):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Banner")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 10)
        lay.setSpacing(10)
        self.icon = QLabel()
        lay.addWidget(self.icon)
        self.text = label("", "BannerText", wrap=True)
        lay.addWidget(self.text, 1)
        self.action = button("", "primary")
        lay.addWidget(self.action)
        self._slot = None
        self.action.clicked.connect(self._run)
        self.hide()

    def _run(self) -> None:
        if self._slot:
            self._slot()

    def show_message(self, text: str, action_text: str = "", slot=None, tone: str = "warning") -> None:
        t_ = theme.current()
        color = {"info": t_.accent, "critical": t_.critical}.get(tone, t_.warning)
        name = "fa5s.info-circle" if tone == "info" else "fa5s.exclamation-circle"
        self.icon.setPixmap(icon(name, color).pixmap(18, 18))
        self.setProperty("tone", tone)
        repolish(self)
        self.text.setText(text)
        self.action.setText(action_text)
        self.action.setVisible(bool(action_text))
        self._slot = slot
        self.show()


class MoneySpin(QDoubleSpinBox):
    """Amount input with thousands separators; decimals follow the currency (R9 / U6)."""

    def __init__(self, currency: str = "JPY", allow_negative: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setLocale(QLocale(QLocale.Language.English, QLocale.Country.UnitedStates))
        # The step buttons are hidden by the style sheet (property "money"). Using NoButtons
        # together with a style sheet collapses the text field to 1 px in Qt 6.
        self.setProperty("money", True)
        self.setGroupSeparatorShown(True)
        self.setAlignment(RIGHT)
        self.setAccelerated(True)
        self.setKeyboardTracking(True)
        self.setRange(-1e12 if allow_negative else 0.0, 1e12)
        self.setMinimumWidth(150)
        self.set_currency(currency)

    def set_currency(self, currency: str) -> None:
        value = self.value()
        self.setDecimals(decimals(currency))
        self.setSingleStep(1000 if decimals(currency) == 0 else 10)
        self.setValue(value)

    def wheelEvent(self, event) -> None:  # no accidental changes while scrolling a form
        event.ignore()


class DayCombo(QComboBox):
    """Day of month 1–31 (avoids spin-box arrows, and never turns 31 into 1)."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        for d in range(1, 32):
            self.addItem(str(d), d)
        self.setMaximumWidth(90)

    def value(self) -> int:
        return int(self.currentData() or 1)

    def setValue(self, day: int) -> None:
        self.setCurrentIndex(max(1, min(31, int(day or 1))) - 1)


class CurrencyCombo(QComboBox):
    def __init__(self, value: str = "JPY", parent: QWidget | None = None):
        super().__init__(parent)
        self.addItems(CURRENCIES)
        self.setCurrentText(value if value in CURRENCIES else "JPY")
        self.setMaximumWidth(90)


class DateField(QDateEdit):
    def __init__(self, value: date | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCalendarPopup(True)
        self.setDisplayFormat("yyyy-MM-dd")
        self.set_date(value or date.today())

    def set_date(self, d: date) -> None:
        self.setDate(QDate(d.year, d.month, d.day))

    def value(self) -> date:
        q = self.date()
        return date(q.year(), q.month(), q.day())


def item(text: str = "", align=LEFT, data=None, tone: str | None = None, bold: bool = False,
         tooltip: str | None = None) -> QTableWidgetItem:
    it = QTableWidgetItem(text)
    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled)
    it.setTextAlignment(align)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    if tone:
        it.setForeground(QColor(getattr(theme.current(), tone)))
    if bold:
        f = QFont()
        f.setWeight(QFont.Weight.DemiBold)
        it.setFont(f)
    if tooltip:
        it.setToolTip(tooltip)
    return it


def check_item(checked: bool, data=None, enabled: bool = True) -> QTableWidgetItem:
    it = QTableWidgetItem()
    flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
    if enabled:
        flags |= Qt.ItemFlag.ItemIsEnabled
    it.setFlags(flags)
    it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    if data is not None:
        it.setData(Qt.ItemDataRole.UserRole, data)
    return it


class DataTable(QTableWidget):
    """Read-only table with hideable columns and remembered widths (R8)."""

    widthsChanged = pyqtSignal(str, list)

    def __init__(self, key: str, headers: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.key = key
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        head = self.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        head.setStretchLastSection(True)
        head.setDefaultAlignment(LEFT)
        head.setHighlightSections(False)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._emit_widths)
        head.sectionResized.connect(lambda *_: self._save_timer.start())
        self._applying = False

    def apply_layout(self, hidden: set[int], widths: list[int] | None, defaults: list[int] | None = None) -> None:
        self._applying = True
        for col in range(self.columnCount()):
            self.setColumnHidden(col, col in hidden)
        for source in (defaults, widths):  # saved widths win over the defaults
            for col, w in enumerate((source or [])[: self.columnCount()]):
                if w and w > 20:
                    self.setColumnWidth(col, int(w))
        self._applying = False

    def right_align(self, columns) -> None:
        for col in columns:
            head = self.horizontalHeaderItem(col)
            if head is not None:
                head.setTextAlignment(RIGHT)

    def _emit_widths(self) -> None:
        if not self._applying:
            self.widthsChanged.emit(self.key, [self.columnWidth(c) for c in range(self.columnCount())])

    def selected_data(self, column: int = 0):
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        if not rows:
            return None
        it = self.item(rows[0].row(), column)
        return it.data(Qt.ItemDataRole.UserRole) if it else None


class ReorderTable(DataTable):
    """Rows can be dragged to a new position; the page stores the new order."""

    rowMoved = pyqtSignal(int, int)

    def __init__(self, key: str, headers: list[str], parent: QWidget | None = None):
        super().__init__(key, headers, parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropOverwriteMode(False)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.source() is not self:
            event.ignore()
            return
        rows = self.selectionModel().selectedRows()
        if not rows:
            event.ignore()
            return
        src = rows[0].row()
        pos = event.position().toPoint()
        idx = self.indexAt(pos)
        if not idx.isValid():
            dst = self.rowCount() - 1
        else:
            rect = self.visualRect(idx)
            dst = idx.row() + (1 if pos.y() > rect.center().y() else 0)
            if src < dst:
                dst -= 1
        dst = max(0, min(dst, self.rowCount() - 1))
        # Copy action: Qt must not delete the source row itself; the page redraws the table.
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        if dst != src:
            QTimer.singleShot(0, lambda: self.rowMoved.emit(src, dst))


# ---- message boxes with translated buttons -------------------------------------------------------
def ask(parent: QWidget, text: str, yes: str | None = None, no: str | None = None,
        danger: bool = False, title: str | None = None) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title or t("common.confirm"))
    box.setIcon(QMessageBox.Icon.Warning if danger else QMessageBox.Icon.Question)
    box.setText(text)
    ok = box.addButton(yes or t("common.ok"), QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(no or t("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    if danger:
        ok.setProperty("kind", "danger")
    box.setDefaultButton(cancel if danger else ok)
    box.exec()
    return box.clickedButton() is ok


def ask3(parent: QWidget, text: str, first: str, second: str) -> int:
    """Returns 1 (first), 2 (second) or 0 (cancel)."""
    box = QMessageBox(parent)
    box.setWindowTitle(t("common.confirm"))
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(text)
    b1 = box.addButton(first, QMessageBox.ButtonRole.AcceptRole)
    b2 = box.addButton(second, QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(t("common.cancel"), QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(b1)
    box.exec()
    clicked = box.clickedButton()
    return 1 if clicked is b1 else 2 if clicked is b2 else 0


def info(parent: QWidget, text: str, title: str | None = None) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(title or t("common.done"))
    box.setIcon(QMessageBox.Icon.Information)
    box.setText(text)
    box.addButton(t("common.ok"), QMessageBox.ButtonRole.AcceptRole)
    box.exec()


def error(parent: QWidget, text: str) -> None:
    box = QMessageBox(parent)
    box.setWindowTitle(t("common.error"))
    box.setIcon(QMessageBox.Icon.Critical)
    box.setText(text)
    box.addButton(t("common.ok"), QMessageBox.ButtonRole.AcceptRole)
    box.exec()

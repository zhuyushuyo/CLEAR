"""Window chrome: the page base class, the sidebar and the common header (U1 / U2)."""

from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QVBoxLayout, QWidget)

from . import paths, theme
from .i18n import fmt_date, fmt_period, t
from .info import APP_NAME, APP_VERSION
from .money import CURRENCIES
from .widgets import button, icon, label


class Page(QWidget):
    key = ""
    title_key = ""
    icon_name = ""
    scrollable = True

    def __init__(self, store, window):
        super().__init__()
        self.store = store
        self.win = window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        container = QWidget()
        container.setObjectName("PageBody")
        self.body = QVBoxLayout(container)
        self.body.setContentsMargins(24, 20, 24, 24)
        self.body.setSpacing(16)
        if self.scrollable:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(container)
            outer.addWidget(scroll)
        else:
            outer.addWidget(container)

    @property
    def title(self) -> str:
        return t(self.title_key)

    def refresh(self) -> None:  # pragma: no cover - overridden
        pass


class Sidebar(QWidget):
    navigate = pyqtSignal(int)

    def __init__(self, pages: list[Page]):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(214)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 22, 14, 16)
        lay.setSpacing(4)
        brand = QHBoxLayout()
        brand.setSpacing(9)
        logo_file = paths.asset("icon.png")
        if logo_file.exists():
            logo = QLabel()
            logo.setObjectName("Logo")
            logo.setPixmap(QIcon(str(logo_file)).pixmap(26, 26))
            brand.addWidget(logo)
        brand.addWidget(label(APP_NAME, "Brand"))
        brand.addStretch(1)
        lay.addLayout(brand)
        lay.addWidget(label(t("brand.sub"), "BrandSub"))
        lay.addSpacing(18)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[QPushButton] = []
        tk = theme.current()
        for i, page in enumerate(pages):
            btn = QPushButton(f"  {page.title}".replace("&", "&&"))
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIconSize(QSize(16, 16))
            btn.setProperty("icon_name", page.icon_name)
            btn.setIcon(icon(page.icon_name, tk.text_muted))
            btn.clicked.connect(lambda _c=False, k=i: self.navigate.emit(k))
            self.group.addButton(btn, i)
            self.buttons.append(btn)
            lay.addWidget(btn)
        lay.addStretch(1)
        lay.addWidget(label(f"v{APP_VERSION}", "Version"))

    def set_current(self, index: int) -> None:
        tk = theme.current()
        for i, btn in enumerate(self.buttons):
            btn.setChecked(i == index)
            btn.setIcon(icon(btn.property("icon_name"), tk.nav_active_text if i == index else tk.text_muted))


class Header(QWidget):
    currencyChanged = pyqtSignal(str)
    fileChosen = pyqtSignal(str)      # path, or "" for "open another file…"
    closeRequested = pyqtSignal()

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.setObjectName("Header")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(62)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 10, 20, 10)
        lay.setSpacing(10)
        self.title = label("", "PageTitle")
        lay.addWidget(self.title)
        lay.addStretch(1)
        lay.addWidget(label(t("header.currency"), "Muted"))
        self.currency = QComboBox()
        self.currency.addItems(CURRENCIES)
        self.currency.setFixedWidth(84)
        self.currency.currentTextChanged.connect(self.currencyChanged.emit)
        lay.addWidget(self.currency)
        lay.addSpacing(6)
        self.file = QComboBox()
        self.file.setMinimumWidth(220)
        self.file.setMaximumWidth(320)
        self.file.activated.connect(self._file_activated)
        lay.addWidget(self.file)
        self.saved = label("", "Faint")
        lay.addWidget(self.saved)
        self.close_btn = button(t("header.close"), icon_name="fa5s.calendar-check",
                                slot=lambda: self.closeRequested.emit())
        lay.addWidget(self.close_btn)

    def _file_activated(self, index: int) -> None:
        value = self.file.itemData(index)
        if value is None:
            return
        current = str(self.store.db_path) if self.store.db_path else ""
        if value != current:
            self.fileChosen.emit(value)

    def refresh(self) -> None:
        store = self.store
        self.currency.blockSignals(True)
        self.currency.setCurrentText(store.currency)
        self.currency.blockSignals(False)

        self.file.blockSignals(True)
        self.file.clear()
        current = str(store.db_path) if store.db_path else ""
        tk = theme.current()
        for p in store.list_db_files():
            self.file.addItem(icon("fa5s.database", tk.text_muted), paths.display_path(p.stem), str(p))
        if not current:
            self.file.insertItem(0, t("header.no_file"), current)
        self.file.addItem(t("header.open_other"), "")
        idx = self.file.findData(current)
        self.file.setCurrentIndex(max(0, idx))
        self.file.setToolTip(paths.display_path(current) if current else "")
        self.file.blockSignals(False)

        self.saved.setText(t("header.saved", time=f"{store.last_saved:%H:%M}") if store.last_saved else "")
        due = store.due_close_periods()
        self.close_btn.setEnabled(bool(due))
        self.close_btn.setProperty("kind", "primary" if due else "")
        self.close_btn.setIcon(icon("fa5s.calendar-check", tk.on_accent if due else tk.text_faint))
        self.close_btn.style().unpolish(self.close_btn)
        self.close_btn.style().polish(self.close_btn)
        if due:
            self.close_btn.setToolTip(t("header.close_tip_due", period=fmt_period(due[0])))
        else:
            nxt = store.state().current.add(1).first_day
            self.close_btn.setToolTip(t("header.close_tip_none", date=fmt_date(nxt)))

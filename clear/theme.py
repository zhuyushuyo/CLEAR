"""Colour tokens and the global style sheet (U4).

Every colour used anywhere in the app comes from one ``Tokens`` object, so the
light and dark themes cannot drift apart. "system" follows the OS setting.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QGuiApplication, QPalette


@dataclass(frozen=True)
class Tokens:
    name: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    border_strong: str
    text: str
    text_muted: str
    text_faint: str
    accent: str
    accent_hover: str
    accent_soft: str
    on_accent: str
    good: str
    good_soft: str
    warning: str
    warning_soft: str
    critical: str
    critical_soft: str
    sidebar: str
    nav_hover: str
    nav_active: str
    nav_active_text: str
    grid: str
    axis: str
    muted: str
    table_alt: str
    header: str
    selection: str
    selection_text: str
    # categorical colours (investment kinds) and the investment line of the outlook chart
    cat1: str = "#2F6BE6"
    cat2: str = "#E07B39"
    cat3: str = "#B8922E"
    cat4: str = "#2A9D8F"
    cat5: str = "#8E6AC8"
    invest: str = "#7B5CC4"

    def qcolor(self, name: str, alpha: int | None = None) -> QColor:
        c = QColor(getattr(self, name))
        if alpha is not None:
            c.setAlpha(alpha)
        return c


LIGHT = Tokens(
    name="light", bg="#F4F5F7", surface="#FFFFFF", surface_alt="#F8F9FB", border="#E3E6EB",
    border_strong="#CBD1D9", text="#1C2026", text_muted="#5B6471", text_faint="#8A93A0",
    accent="#2F6BE6", accent_hover="#2357C4", accent_soft="#E9F0FD", on_accent="#FFFFFF",
    good="#1E8449", good_soft="#E6F4EC", warning="#A66508", warning_soft="#FCF3E2",
    critical="#C2352E", critical_soft="#FBEBEA", sidebar="#FFFFFF", nav_hover="#F1F3F6",
    nav_active="#E9F0FD", nav_active_text="#2357C4", grid="#ECEFF2", axis="#C6CCD4", muted="#A3ABB5",
    table_alt="#FAFBFC", header="#F6F7F9", selection="#DCE7FC", selection_text="#1C2026",
    cat1="#2F6BE6", cat2="#E07B39", cat3="#B8922E", cat4="#2A9D8F", cat5="#8E6AC8", invest="#7B5CC4",
)

DARK = Tokens(
    name="dark", bg="#111316", surface="#1A1D21", surface_alt="#1F2329", border="#2B3036",
    border_strong="#3A4048", text="#E6E8EB", text_muted="#A2AAB4", text_faint="#77808B",
    accent="#5C8EF0", accent_hover="#7AA3F4", accent_soft="#1D2A42", on_accent="#FFFFFF",
    good="#4FBF83", good_soft="#15291E", warning="#E1A73E", warning_soft="#2E2510",
    critical="#EE7070", critical_soft="#361C1C", sidebar="#15181B", nav_hover="#1F2329",
    nav_active="#1D2A42", nav_active_text="#9BB9F7", grid="#252A30", axis="#3A4048", muted="#6D7681",
    table_alt="#1D2025", header="#1F2329", selection="#25406E", selection_text="#FFFFFF",
    cat1="#5C8EF0", cat2="#F0A060", cat3="#D9B54A", cat4="#4FC1B2", cat5="#A98BE0", invest="#A98BE0",
)

_current: Tokens = LIGHT


def current() -> Tokens:
    return _current


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:  # Qt < 6.5
        app = QGuiApplication.instance()
        return bool(app) and app.palette().color(QPalette.ColorRole.Window).lightness() < 128


def resolve(setting: str) -> Tokens:
    if setting == "dark":
        return DARK
    if setting == "light":
        return LIGHT
    return DARK if system_is_dark() else LIGHT


def apply(app, setting: str) -> Tokens:
    global _current
    _current = resolve(setting)
    app.setPalette(palette(_current))
    app.setStyleSheet(stylesheet(_current, _check_image(_current.on_accent)))
    return _current


def _check_image(color: str) -> str | None:
    """A small check-mark PNG for ticked boxes (drawn once, kept in the config folder)."""
    from PyQt6.QtCore import QPointF
    from PyQt6.QtGui import QImage, QPainter, QPainterPath, QPen

    from .paths import config_dir

    try:
        folder = config_dir() / "cache"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"check-{color.lstrip('#')}.png"
        if not path.exists():
            img = QImage(32, 32, QImage.Format.Format_ARGB32)
            img.fill(0)
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pen = QPen(QColor(color), 4.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            tick = QPainterPath(QPointF(8, 16.5))
            tick.lineTo(QPointF(13.5, 22))
            tick.lineTo(QPointF(24, 10))
            p.drawPath(tick)
            p.end()
            img.save(str(path), "PNG")
        return path.as_posix()
    except Exception:  # read-only home folder etc.: boxes still show the filled state
        return None


def palette(t: Tokens) -> QPalette:
    p = QPalette()
    R = QPalette.ColorRole
    pairs = {
        R.Window: t.bg, R.WindowText: t.text, R.Base: t.surface, R.AlternateBase: t.table_alt,
        R.Text: t.text, R.Button: t.surface, R.ButtonText: t.text, R.Highlight: t.accent,
        R.HighlightedText: t.on_accent, R.ToolTipBase: t.surface, R.ToolTipText: t.text,
        R.PlaceholderText: t.text_faint, R.Link: t.accent, R.BrightText: t.critical,
        R.Light: t.surface, R.Midlight: t.surface_alt, R.Mid: t.border, R.Dark: t.border_strong,
        R.Shadow: "#000000",
    }
    for role, color in pairs.items():
        p.setColor(role, QColor(color))
    for role in (R.Text, R.ButtonText, R.WindowText):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(t.text_faint))
    return p


def stylesheet(t: Tokens, check: str | None = None) -> str:
    tick = f'image: url("{check}");' if check else ""
    indicators = f"""
QCheckBox::indicator, QTableView::indicator, QListView::indicator {{ width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid {t.axis}; background: {t.surface}; }}
QCheckBox::indicator:hover, QTableView::indicator:hover, QListView::indicator:hover {{ border: 1px solid {t.accent}; }}
QCheckBox::indicator:checked, QTableView::indicator:checked, QListView::indicator:checked {{ background: {t.accent};
    border: 1px solid {t.accent}; {tick} }}
QCheckBox::indicator:disabled, QTableView::indicator:disabled, QListView::indicator:disabled {{
    background: {t.surface_alt}; border: 1px solid {t.border}; }}
QCheckBox::indicator:checked:disabled, QTableView::indicator:checked:disabled,
QListView::indicator:checked:disabled {{ background: {t.muted}; border: 1px solid {t.muted}; {tick} }}
QRadioButton::indicator {{ width: 15px; height: 15px; border-radius: 8px; border: 1px solid {t.axis};
    background: {t.surface}; }}
QRadioButton::indicator:hover {{ border: 1px solid {t.accent}; }}
QRadioButton::indicator:checked {{ border: 1px solid {t.accent}; background: qradialgradient(cx:0.5, cy:0.5,
    radius:0.5, fx:0.5, fy:0.5, stop:0 {t.on_accent}, stop:0.32 {t.on_accent}, stop:0.42 {t.accent}, stop:1 {t.accent}); }}
"""
    return indicators + f"""
QWidget {{ font-size: 13px; }}
QMainWindow, QDialog {{ background: {t.bg}; }}
QWidget#Root, QWidget#Content, QWidget#PageBody, QStackedWidget#Pages {{ background: {t.bg}; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QLabel {{ background: transparent; color: {t.text}; }}

QWidget#Sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
QLabel#Brand {{ font-size: 21px; font-weight: 700; color: {t.text}; letter-spacing: 2px; }}
QLabel#BrandSub {{ font-size: 11px; color: {t.text_faint}; }}
QPushButton#Nav {{ text-align: left; padding: 9px 12px; border: none; border-radius: 8px;
    color: {t.text_muted}; background: transparent; font-size: 14px; }}
QPushButton#Nav:hover {{ background: {t.nav_hover}; color: {t.text}; }}
QPushButton#Nav:checked {{ background: {t.nav_active}; color: {t.nav_active_text}; font-weight: 600; }}
QLabel#Version {{ color: {t.text_faint}; font-size: 11px; }}

QWidget#Header {{ background: {t.bg}; border-bottom: 1px solid {t.border}; }}
QLabel#PageTitle {{ font-size: 20px; font-weight: 600; color: {t.text}; }}
QLabel#Muted {{ color: {t.text_muted}; }}
QLabel#Faint {{ color: {t.text_faint}; font-size: 12px; }}
QLabel#Hint {{ color: {t.text_muted}; font-size: 12px; }}
QLabel#Error {{ color: {t.critical}; font-size: 12px; }}
QLabel#DialogTitle {{ font-size: 17px; font-weight: 600; }}
QLabel#SectionTitle {{ font-size: 13px; font-weight: 600; color: {t.text}; }}
QLabel[tone="good"] {{ color: {t.good}; }}
QLabel[tone="warning"] {{ color: {t.warning}; }}
QLabel[tone="critical"] {{ color: {t.critical}; }}
QLabel[tone="accent"] {{ color: {t.accent}; }}
QLabel[tone="muted"] {{ color: {t.text_muted}; }}

QFrame#Card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 12px; }}
QLabel#CardTitle {{ font-size: 14px; font-weight: 600; color: {t.text}; }}
QLabel#CardSub {{ font-size: 12px; color: {t.text_muted}; }}
QLabel#KpiLabel {{ font-size: 12px; color: {t.text_muted}; font-weight: 600; }}
QLabel#KpiValue {{ font-size: 25px; font-weight: 600; color: {t.text}; }}
QLabel#KpiSub {{ font-size: 12px; color: {t.text_muted}; }}
QLabel#KpiValue[tone="good"] {{ color: {t.good}; }}
QLabel#KpiValue[tone="critical"] {{ color: {t.critical}; }}
QLabel#KpiValue[tone="warning"] {{ color: {t.warning}; }}
QFrame#Divider {{ background: {t.border}; border: none; min-height: 1px; max-height: 1px; }}

QFrame#Banner {{ background: {t.warning_soft}; border: 1px solid {t.warning}; border-radius: 10px; }}
QFrame#Banner[tone="info"] {{ background: {t.accent_soft}; border: 1px solid {t.accent}; }}
QFrame#Banner[tone="critical"] {{ background: {t.critical_soft}; border: 1px solid {t.critical}; }}
QLabel#BannerText {{ color: {t.text}; }}
QFrame#AlertRow {{ background: transparent; border: none; }}

QPushButton {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong};
    border-radius: 7px; padding: 6px 14px; }}
QPushButton:hover {{ background: {t.surface_alt}; border-color: {t.axis}; }}
QPushButton:pressed {{ background: {t.border}; }}
QPushButton:disabled {{ color: {t.text_faint}; border-color: {t.border}; background: {t.surface}; }}
QPushButton[kind="primary"] {{ background: {t.accent}; color: {t.on_accent}; border: 1px solid {t.accent};
    font-weight: 600; }}
QPushButton[kind="primary"]:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton[kind="primary"]:disabled {{ background: {t.border}; border-color: {t.border}; color: {t.text_faint}; }}
QPushButton[kind="danger"] {{ color: {t.critical}; }}
QPushButton[kind="danger"]:hover {{ background: {t.critical_soft}; border-color: {t.critical}; }}
QPushButton[kind="ghost"] {{ background: transparent; border: none; color: {t.accent}; padding: 4px 6px; }}
QPushButton[kind="ghost"]:hover {{ text-decoration: underline; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: 6px;
    padding: 4px 8px; min-height: 22px; selection-background-color: {t.accent}; selection-color: {t.on_accent}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus,
QPlainTextEdit:focus {{ border: 1px solid {t.accent}; }}
QLineEdit:disabled, QComboBox:disabled, QDoubleSpinBox:disabled {{ color: {t.text_faint}; background: {t.surface_alt}; }}
QDoubleSpinBox[money="true"] {{ padding-right: 8px; }}
QDoubleSpinBox[money="true"]::up-button, QDoubleSpinBox[money="true"]::down-button {{ width: 0px; border: none;
    background: transparent; }}
QDoubleSpinBox[money="true"]::up-arrow, QDoubleSpinBox[money="true"]::down-arrow {{ width: 0px; height: 0px;
    image: none; }}
QLineEdit[invalid="true"], QDoubleSpinBox[invalid="true"], QComboBox[invalid="true"] {{ border: 1px solid {t.critical}; }}
QComboBox QAbstractItemView {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong};
    selection-background-color: {t.selection}; selection-color: {t.selection_text}; outline: none; }}

QTableWidget, QTableView, QListWidget {{ background: {t.surface}; alternate-background-color: {t.table_alt};
    color: {t.text}; border: 1px solid {t.border}; border-radius: 10px; gridline-color: {t.grid};
    selection-background-color: {t.selection}; selection-color: {t.selection_text}; outline: none; }}
QTableWidget::item, QTableView::item {{ padding: 2px 8px; border: none; }}
QListWidget::item {{ padding: 6px 8px; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {t.header}; color: {t.text_muted}; border: none;
    border-bottom: 1px solid {t.border}; padding: 7px 8px; font-weight: 600; font-size: 12px; }}
QTableCornerButton::section {{ background: {t.header}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ background: transparent; color: {t.text_muted}; padding: 8px 18px; border: none;
    border-bottom: 2px solid transparent; font-size: 14px; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom: 2px solid {t.accent}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {t.text}; }}

QCheckBox, QRadioButton {{ spacing: 8px; color: {t.text}; background: transparent; }}
QStatusBar {{ background: {t.bg}; color: {t.text_muted}; border-top: 1px solid {t.border}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong}; padding: 6px; }}
QMenu {{ background: {t.surface}; color: {t.text}; border: 1px solid {t.border_strong}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t.selection}; color: {t.selection_text}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {t.border_strong}; border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {t.border_strong}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""

"""Small hand-painted charts (no extra dependency, theme-aware)."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from . import theme
from .i18n import fmt_month_short, fmt_period, lang, money, t
from .money import fmt_compact
from .periods import Period


def _nice_step(span: float, target_ticks: int = 4) -> float:
    if span <= 0:
        return 1.0
    raw = span / target_ticks
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


class TrendChart(QWidget):
    """Debt balance (area), savings and investments (lines) month by month, payoff month marked."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.periods: list[Period] = []
        self.debt: list[float] = []
        self.savings: list[float] = []
        self.invest: list[float] = []
        self.payoff: Period | None = None
        self.currency = "JPY"
        self.hover: int | None = None

    def set_data(self, periods, debt, savings, payoff, currency, invest=None) -> None:
        self.periods, self.debt, self.savings = list(periods), list(debt), list(savings)
        inv = list(invest or [])
        self.invest = inv if any(abs(v) > 0 for v in inv) else []
        self.payoff, self.currency = payoff, currency
        self.hover = None
        self.update()

    # ---- geometry ---------------------------------------------------------------------------
    def _frame(self) -> QRectF:
        return QRectF(64, 34, max(10, self.width() - 64 - 18), max(10, self.height() - 34 - 30))

    def _scale(self):
        values = self.debt + self.savings + self.invest + [0.0]
        lo, hi = min(values), max(values)
        if hi == lo:
            hi = lo + 1
        step = _nice_step(hi - lo)
        lo = math.floor(lo / step) * step
        hi = math.ceil(hi * 1.04 / step) * step
        return lo, hi, step

    def _x(self, i: int, frame: QRectF) -> float:
        n = max(1, len(self.periods) - 1)
        return frame.left() + frame.width() * i / n

    def _y(self, v: float, frame: QRectF, lo: float, hi: float) -> float:
        return frame.bottom() - (v - lo) / (hi - lo) * frame.height()

    # ---- painting ----------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        tk = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = QFont(self.font())
        base.setPixelSize(11)
        p.setFont(base)
        fm = QFontMetrics(base)
        if len(self.periods) < 2:
            p.setPen(tk.qcolor("text_muted"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("home.trend.empty"))
            return
        frame = self._frame()
        lo, hi, step = self._scale()

        # grid + y labels
        v = lo
        while v <= hi + step / 2:
            y = self._y(v, frame, lo, hi)
            p.setPen(QPen(tk.qcolor("axis" if abs(v) < 1e-9 else "grid"), 1))
            p.drawLine(QPointF(frame.left(), y), QPointF(frame.right(), y))
            p.setPen(tk.qcolor("text_faint"))
            p.drawText(QRectF(0, y - 8, frame.left() - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fmt_compact(v, self.currency, lang()))
            v += step

        # x labels: about 8 labels whatever the length
        n = len(self.periods)
        every = max(1, math.ceil(n / 8))
        p.setPen(tk.qcolor("text_faint"))
        for i, per in enumerate(self.periods):
            if i % every and i != n - 1:
                continue
            x = self._x(i, frame)
            text = fmt_month_short(per, with_year=(n > 13 or i == 0 or per.month == 1))
            w = fm.horizontalAdvance(text) + 8
            left = min(max(x - w / 2, 0.0), self.width() - w)  # keep the end labels inside the widget
            p.drawText(QRectF(left, frame.bottom() + 6, w, 16), Qt.AlignmentFlag.AlignCenter, text)

        # debt area + line
        pts = [QPointF(self._x(i, frame), self._y(d, frame, lo, hi)) for i, d in enumerate(self.debt)]
        zero_y = self._y(max(lo, 0.0), frame, lo, hi)
        area = QPainterPath(QPointF(pts[0].x(), zero_y))
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(QPointF(pts[-1].x(), zero_y))
        area.closeSubpath()
        p.fillPath(area, tk.qcolor("accent", 34))
        line = QPainterPath(pts[0])
        for pt in pts[1:]:
            line.lineTo(pt)
        p.setPen(QPen(tk.qcolor("accent"), 2.2))
        p.drawPath(line)

        # savings line
        spts = [QPointF(self._x(i, frame), self._y(s, frame, lo, hi)) for i, s in enumerate(self.savings)]
        sline = QPainterPath(spts[0])
        for pt in spts[1:]:
            sline.lineTo(pt)
        p.setPen(QPen(tk.qcolor("good"), 2.0))
        p.drawPath(sline)

        # investments line
        ipts = []
        if self.invest:
            ipts = [QPointF(self._x(i, frame), self._y(v, frame, lo, hi)) for i, v in enumerate(self.invest)]
            iline = QPainterPath(ipts[0])
            for pt in ipts[1:]:
                iline.lineTo(pt)
            p.setPen(QPen(tk.qcolor("invest"), 2.0))
            p.drawPath(iline)

        # payoff marker
        if self.payoff is not None and self.payoff in self.periods:
            i = self.periods.index(self.payoff)
            x = self._x(i, frame)
            pen = QPen(tk.qcolor("accent"), 1.2)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(x, frame.top() + 14), QPointF(x, frame.bottom()))
            text = f"{t('home.trend.payoff')} {fmt_period(self.payoff)}"
            w = fm.horizontalAdvance(text) + 10
            left = min(max(x - w / 2, frame.left()), frame.right() - w)
            bold = QFont(base)
            bold.setWeight(QFont.Weight.DemiBold)
            p.setFont(bold)
            p.setPen(tk.qcolor("accent"))
            p.drawText(QRectF(left, frame.top() - 4, w, 16), Qt.AlignmentFlag.AlignCenter, text)
            p.setFont(base)

        # legend (top-left)
        lx = frame.left()
        legend = [("home.trend.debt", "accent"), ("home.trend.savings", "good")]
        if self.invest:
            legend.append(("home.trend.invest", "invest"))
        for key, color in legend:
            p.setPen(QPen(tk.qcolor(color), 3))
            p.drawLine(QPointF(lx, 12), QPointF(lx + 14, 12))
            p.setPen(tk.qcolor("text_muted"))
            text = t(key)
            p.drawText(QRectF(lx + 20, 4, fm.horizontalAdvance(text) + 6, 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
            lx += 20 + fm.horizontalAdvance(text) + 22

        # hover read-out
        if self.hover is not None and 0 <= self.hover < n:
            i = self.hover
            x = self._x(i, frame)
            p.setPen(QPen(tk.qcolor("axis"), 1))
            p.drawLine(QPointF(x, frame.top()), QPointF(x, frame.bottom()))
            marks = [(pts[i], "accent"), (spts[i], "good")] + ([(ipts[i], "invest")] if ipts else [])
            for pt, color in marks:
                p.setPen(QPen(tk.qcolor("surface"), 2))
                p.setBrush(tk.qcolor(color))
                p.drawEllipse(pt, 4.5, 4.5)
            lines = [fmt_period(self.periods[i]),
                     f"{t('home.trend.debt')}  {money(self.debt[i], self.currency)}",
                     f"{t('home.trend.savings')}  {money(self.savings[i], self.currency)}"]
            if ipts:
                lines.append(f"{t('home.trend.invest')}  {money(self.invest[i], self.currency)}")
            w = max(fm.horizontalAdvance(s) for s in lines) + 20
            h = 16 * len(lines) + 12
            bx = x + 12 if x + 12 + w < frame.right() else x - 12 - w
            by = frame.top() + 8
            p.setPen(QPen(tk.qcolor("border_strong"), 1))
            p.setBrush(tk.qcolor("surface"))
            p.drawRoundedRect(QRectF(bx, by, w, h), 6, 6)
            p.setPen(tk.qcolor("text"))
            for k, s in enumerate(lines):
                p.drawText(QRectF(bx + 10, by + 6 + 16 * k, w - 14, 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, s)
        p.end()

    def mouseMoveEvent(self, event) -> None:
        if len(self.periods) < 2:
            return
        frame = self._frame()
        x = event.position().x()
        n = len(self.periods)
        i = round((x - frame.left()) / max(1.0, frame.width()) * (n - 1))
        i = max(0, min(n - 1, i))
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, _event) -> None:
        self.hover = None
        self.update()


class BreakdownBars(QWidget):
    """Horizontal bars: label, bar, amount and share."""

    ROW = 30

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.rows: list[tuple[str, float]] = []
        self.currency = "JPY"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_rows(self, rows: list[tuple[str, float]], currency: str) -> None:
        self.rows, self.currency = rows, currency
        self.setFixedHeight(max(1, len(rows)) * self.ROW + 4)
        self.update()

    def paintEvent(self, _event) -> None:
        tk = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetrics(f)
        if not self.rows:
            p.setPen(tk.qcolor("text_muted"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       t("home.breakdown.empty"))
            return
        total = sum(v for _, v in self.rows) or 1.0
        top = max(v for _, v in self.rows) or 1.0
        label_w = min(150, max(fm.horizontalAdvance(name) for name, _ in self.rows) + 12)
        value_w = max(fm.horizontalAdvance(f"{money(v, self.currency)}  100%") for _, v in self.rows) + 8
        bar_w = max(20, self.width() - label_w - value_w - 8)
        for k, (name, v) in enumerate(self.rows):
            y = k * self.ROW + 2
            p.setPen(tk.qcolor("text"))
            p.drawText(QRectF(0, y, label_w - 8, self.ROW - 6),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, label_w - 8))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tk.qcolor("grid"))
            p.drawRoundedRect(QRectF(label_w, y + 8, bar_w, 10), 5, 5)
            p.setBrush(tk.qcolor("accent", 255 if k == 0 else 150))
            p.drawRoundedRect(QRectF(label_w, y + 8, max(6.0, bar_w * v / top), 10), 5, 5)
            p.setPen(tk.qcolor("text_muted"))
            p.drawText(QRectF(label_w + bar_w + 8, y, value_w, self.ROW - 6),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       f"{money(v, self.currency)}  {v / total:.0%}")
        p.end()


class AllocationBar(QWidget):
    """One stacked bar of parts of a whole with a legend underneath (I3), under an optional caption.
    The legend wraps onto more lines when narrow; the height follows before anything is painted."""

    LINE = 18

    def __init__(self, title: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.rows: list[tuple[str, float, str]] = []   # (label, value, colour token)
        self.currency = "JPY"
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._top = 20.0 if title else 0.0
        self.setFixedHeight(self._height())

    def set_rows(self, rows: list[tuple[str, float, str]], currency: str) -> None:
        self.rows = [r for r in rows if r[1] > 0]
        self.currency = currency
        self.setFixedHeight(self._height())
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        h = self._height()
        if h != self.height():
            self.setFixedHeight(h)

    def _font(self) -> QFont:
        f = QFont(self.font())
        f.setPixelSize(12)
        return f

    def _legend(self, width: float) -> list[tuple[float, float, str, str, float]]:
        """(x, y, text, colour, text width) per entry."""
        total = sum(v for _, v, _c in self.rows)
        fm = QFontMetrics(self._font())
        out = []
        lx, ly = 0.0, self._top + 16
        for name, v, color in self.rows:
            text = f"{name}  {money(v, self.currency)}  {v / total:.0%}" if total > 0 else name
            w = fm.horizontalAdvance(text) + 30
            if lx + w > width and lx > 0:
                lx, ly = 0.0, ly + self.LINE
            out.append((lx, ly, text, color, w))
            lx += w
        return out

    def _height(self) -> int:
        legend = self._legend(max(10, self.width()))
        last = legend[-1][1] if legend else self._top + 16
        return int(last + self.LINE + 2)

    def paintEvent(self, _event) -> None:
        tk = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._font())
        if self.title:
            p.setPen(tk.qcolor("text"))
            p.drawText(QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       self.title)
        total = sum(v for _, v, _c in self.rows)
        bar = QRectF(0, self._top, max(10, self.width() - 2), 10)
        if total <= 0:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tk.qcolor("grid"))
            p.drawRoundedRect(bar, 5, 5)
            p.setPen(tk.qcolor("text_muted"))
            p.drawText(QRectF(0, self._top + 16, self.width(), 16),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t("invest.alloc.empty"))
            p.end()
            return
        clip = QPainterPath()
        clip.addRoundedRect(bar, 5, 5)
        p.setClipPath(clip)
        x = bar.left()
        for k, (_name, v, color) in enumerate(self.rows):
            w = bar.width() * v / total if k < len(self.rows) - 1 else bar.right() - x
            p.fillRect(QRectF(x, bar.top(), w, bar.height()), tk.qcolor(color))
            x += w
        p.setClipping(False)
        for lx, ly, text, color, w in self._legend(self.width()):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(tk.qcolor(color))
            p.drawRoundedRect(QRectF(lx, ly + 3, 10, 10), 3, 3)
            p.setPen(tk.qcolor("text_muted"))
            p.drawText(QRectF(lx + 16, ly, w, 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        p.end()


class UsageBar(QWidget):
    """A limit and how much of it is used (NISA frames, P2): title, bar, then the numbers."""

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.title = title
        self.used = 0.0
        self.limit = 1.0
        self.currency = "JPY"
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_values(self, used: float, limit: float, currency: str = "JPY") -> None:
        self.used, self.limit, self.currency = used, max(1.0, limit), currency
        self.setToolTip(t("invest.nisa.usage", used=money(used, currency), limit=money(limit, currency),
                          left=money(max(0.0, limit - used), currency)))
        self.update()

    def paintEvent(self, _event) -> None:
        tk = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont(self.font())
        f.setPixelSize(12)
        p.setFont(f)
        fm = QFontMetrics(f)
        over = self.used > self.limit + 0.5
        p.setPen(tk.qcolor("text"))
        p.drawText(QRectF(0, 0, self.width(), 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.title, Qt.TextElideMode.ElideRight, self.width()))
        bar = QRectF(0, 21, self.width(), 8)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(tk.qcolor("grid"))
        p.drawRoundedRect(bar, 4, 4)
        share = min(1.0, self.used / self.limit)
        if share > 0:
            p.setBrush(tk.qcolor("critical" if over else "accent"))
            p.drawRoundedRect(QRectF(0, 21, max(6.0, bar.width() * share), 8), 4, 4)
        small = QFont(f)
        small.setPixelSize(11)
        p.setFont(small)
        p.setPen(tk.qcolor("critical" if over else "text_muted"))
        lg = lang()
        parts = dict(used=fmt_compact(self.used, self.currency, lg), limit=fmt_compact(self.limit, self.currency, lg),
                     left=fmt_compact(max(0.0, self.limit - self.used), self.currency, lg))
        sfm = QFontMetrics(small)
        text = t("invest.nisa.usage", **parts)
        if sfm.horizontalAdvance(text) > self.width():
            text = t("invest.nisa.usage_short", **parts)
        p.drawText(QRectF(0, 34, self.width(), 16), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   sfm.elidedText(text, Qt.TextElideMode.ElideRight, self.width()))
        p.end()


class HistoryChart(QWidget):
    """Net worth recorded at each month-end close (P1), with the outlook made a month before."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.periods: list[Period] = []
        self.values: list[float] = []
        self.projected: list[float | None] = []   # outlook for this month, made at the previous close
        self.currency = "JPY"
        self.hover: int | None = None

    def set_data(self, periods, values, projected, currency) -> None:
        self.periods, self.values, self.projected = list(periods), list(values), list(projected)
        self.currency = currency
        self.hover = None
        self.update()

    def _frame(self) -> QRectF:
        return QRectF(64, 12, max(10, self.width() - 64 - 18), max(10, self.height() - 12 - 28))

    def _x(self, i: int, frame: QRectF) -> float:
        n = len(self.periods)
        if n <= 1:
            return frame.center().x()
        return frame.left() + frame.width() * i / (n - 1)

    def paintEvent(self, _event) -> None:
        tk = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        base = QFont(self.font())
        base.setPixelSize(11)
        p.setFont(base)
        fm = QFontMetrics(base)
        if not self.periods:
            p.setPen(tk.qcolor("text_muted"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, t("home.history.empty"))
            p.end()
            return
        frame = self._frame()
        values = self.values + [v for v in self.projected if v is not None] + [0.0]
        lo, hi = min(values), max(values)
        if hi == lo:
            hi = lo + 1
        step = _nice_step(hi - lo, 3)
        lo = math.floor(lo / step) * step
        hi = math.ceil(hi * 1.04 / step) * step

        def y(v: float) -> float:
            return frame.bottom() - (v - lo) / (hi - lo) * frame.height()

        v = lo
        while v <= hi + step / 2:
            yy = y(v)
            p.setPen(QPen(tk.qcolor("axis" if abs(v) < 1e-9 else "grid"), 1))
            p.drawLine(QPointF(frame.left(), yy), QPointF(frame.right(), yy))
            p.setPen(tk.qcolor("text_faint"))
            p.drawText(QRectF(0, yy - 8, frame.left() - 8, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       fmt_compact(v, self.currency, lang()))
            v += step
        n = len(self.periods)
        every = max(1, math.ceil(n / 8))
        p.setPen(tk.qcolor("text_faint"))
        for i, per in enumerate(self.periods):
            if i % every and i != n - 1:
                continue
            x = self._x(i, frame)
            text = fmt_month_short(per, with_year=(i == 0 or per.month == 1))
            w = fm.horizontalAdvance(text) + 8
            left = min(max(x - w / 2, 0.0), self.width() - w)
            p.drawText(QRectF(left, frame.bottom() + 6, w, 16), Qt.AlignmentFlag.AlignCenter, text)
        pts = [QPointF(self._x(i, frame), y(val)) for i, val in enumerate(self.values)]
        if len(pts) > 1:
            path = QPainterPath(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            p.setPen(QPen(tk.qcolor("accent"), 2.2))
            p.drawPath(path)
        for i, pt in enumerate(pts):
            proj = self.projected[i] if i < len(self.projected) else None
            if proj is not None:
                pen = QPen(tk.qcolor("text_faint"), 1.4)
                p.setPen(pen)
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawEllipse(QPointF(pt.x(), y(proj)), 4.0, 4.0)
            p.setPen(QPen(tk.qcolor("surface"), 2))
            p.setBrush(tk.qcolor("accent"))
            p.drawEllipse(pt, 4.5, 4.5)
        if self.hover is not None and 0 <= self.hover < n:
            i = self.hover
            lines = [fmt_period(self.periods[i]), f"{t('home.history.actual')}  {money(self.values[i], self.currency)}"]
            proj = self.projected[i] if i < len(self.projected) else None
            if proj is not None:
                lines.append(f"{t('home.history.projected')}  {money(proj, self.currency)}")
            w = max(fm.horizontalAdvance(s_) for s_ in lines) + 20
            h = 16 * len(lines) + 12
            x = self._x(i, frame)
            bx = x + 12 if x + 12 + w < frame.right() else x - 12 - w
            p.setPen(QPen(tk.qcolor("border_strong"), 1))
            p.setBrush(tk.qcolor("surface"))
            p.drawRoundedRect(QRectF(bx, frame.top(), w, h), 6, 6)
            p.setPen(tk.qcolor("text"))
            for k, s_ in enumerate(lines):
                p.drawText(QRectF(bx + 10, frame.top() + 6 + 16 * k, w - 14, 16),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, s_)
        p.end()

    def mouseMoveEvent(self, event) -> None:
        if not self.periods:
            return
        frame = self._frame()
        n = len(self.periods)
        if n == 1:
            i = 0
        else:
            i = round((event.position().x() - frame.left()) / max(1.0, frame.width()) * (n - 1))
        i = max(0, min(n - 1, i))
        if i != self.hover:
            self.hover = i
            self.update()

    def leaveEvent(self, _event) -> None:
        self.hover = None
        self.update()

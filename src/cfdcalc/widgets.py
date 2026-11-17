"""Animated widgets: progress ring, indicator tiles, result panel. Fixed sizes, so updates never resize the window.

Animations (QPropertyAnimation / QVariantAnimation) only interpolate what is drawn; values shown are always real.
"""
from __future__ import annotations

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from .analysis import BUY, ERROR, NO_DATA, SELL, WAIT, Result

ACCENT = "#3b82f6"
VERDICT_COLORS = {BUY: "#22c55e", SELL: "#ef4444", WAIT: "#f59e0b", NO_DATA: "#64748b", ERROR: "#a855f7",
                  "START": ACCENT}
STATE_COLORS = {"bull": "#22c55e", "bear": "#ef4444", "neutral": "#64748b", "block": "#f59e0b", "na": "#334155",
                "off": "#252c3b", "error": "#a855f7"}
SHORT = {"Aktuální data": "Data", "Shoda indikátorů": "Shoda", "Volatilita (ATR)": "Volatilita",
         "Prostor k cíli": "Prostor", "Ekonomické zprávy": "Zprávy", "Časový limit": "Čas", "RSI extrém": "RSI extrém"}
FILTER_ICONS = {"ok": ("✓", "#22c55e"), "fail": ("✗", "#ef4444"), "na": ("–", "#64748b")}


def _anim(target, prop: bytes, ms: int) -> QPropertyAnimation:
    a = QPropertyAnimation(target, prop, target)
    a.setDuration(ms)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    return a


class Gauge(QWidget):
    """Ring with the REAL share of finished analysis steps. A rotating segment only signals "waiting" (network),
    it never stands for a percentage."""
    clicked = Signal()

    def __init__(self, size: int = 164):
        super().__init__()
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pct, self._color, self._spin = 0.0, QColor(ACCENT), 0.0
        self.title, self.sub, self.busy = "START", "spustit analýzu", False
        self._pct_anim = _anim(self, b"pct", 380)
        self._color_anim = _anim(self, b"color", 450)
        self._spinner = QVariantAnimation(self, startValue=0.0, endValue=360.0, duration=1100, loopCount=-1)
        self._spinner.valueChanged.connect(self._on_spin)

    def _get_pct(self) -> float:
        return self._pct

    def _set_pct(self, v: float):
        self._pct = v
        self.update()

    def _get_color(self) -> QColor:
        return self._color

    def _set_color(self, c: QColor):
        self._color = QColor(c)
        self.update()

    pct = Property(float, _get_pct, _set_pct)
    color = Property(QColor, _get_color, _set_color)

    def _on_spin(self, v):
        self._spin = float(v)
        self.update()

    @property
    def target(self) -> float:
        """The percentage the ring is heading to (the real value; the drawn one may still be animating)."""
        return float(self._pct_anim.endValue()) if self._pct_anim.state() else self._pct

    def show_state(self, pct: float, title: str, sub: str, color: str = ACCENT, busy: bool = False):
        for anim, end in ((self._pct_anim, float(pct)), (self._color_anim, QColor(color))):
            anim.stop()
            anim.setStartValue(self._pct if anim is self._pct_anim else self._color)
            anim.setEndValue(end)
            anim.start()
        if (self.title, self.sub) != (title, sub):
            self.title, self.sub = title, sub
            self.setToolTip(sub)
        self.busy = busy
        if busy and self._spinner.state() != QVariantAnimation.State.Running:
            self._spinner.start()
        elif not busy:
            self._spinner.stop()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.isEnabled() and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 13
        r = QRectF(self.rect()).adjusted(w, w, -w, -w)
        p.setPen(QPen(QColor("#232a3a"), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawEllipse(r)
        if self._pct > 0.2:
            p.setPen(QPen(self._color, w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, -int(self._pct * 360 / 100 * 16))
        if self.busy:
            c = QColor("#93c5fd")
            c.setAlpha(170)
            p.setPen(QPen(c, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(r.adjusted(-w + 3, -w + 3, w - 3, w - 3), int((90 - self._spin) * 16), -50 * 16)
        p.setPen(self._color if self.title in VERDICT_COLORS or self.title == "NO DATA" else QColor("#e5e7eb"))
        size = 23 if len(self.title) <= 5 else 17
        p.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -14, 0, -14), Qt.AlignmentFlag.AlignCenter, self.title)
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(r.adjusted(10, 40, -10, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.sub)


class Tile(QWidget):
    """Indicator tile: title, value, role in the decision; the accent colour fades between states."""

    def __init__(self, title: str):
        super().__init__()
        self.setFixedHeight(40)
        self._accent, self._bg = QColor(STATE_COLORS["na"]), QColor("#1a2030")
        self._anim = _anim(self, b"accent", 420)
        self.title, self.value, self.stance = QLabel(title), QLabel("–"), QLabel("")
        self.title.setStyleSheet("font-weight: 600; background: transparent;")
        self.value.setStyleSheet("color: #94a3b8; background: transparent; font-size: 11px;")
        self.stance.setStyleSheet("color: #94a3b8; background: transparent; font-size: 10px;")
        self.stance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.title, 1)
        top.addWidget(self.stance)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 3, 8, 3)
        lay.setSpacing(0)
        lay.addLayout(top)
        lay.addWidget(self.value)
        self._shown: tuple = ()

    def _get_accent(self) -> QColor:
        return self._accent

    def _set_accent(self, c: QColor):
        self._accent = QColor(c)
        self.update()

    accent = Property(QColor, _get_accent, _set_accent)

    def set(self, state: str, value: str, note: str, stance: str = ""):
        if (state, value, note, stance) == self._shown:
            return  # nothing changed: no repaint, no animation
        self._shown = (state, value, note, stance)
        self.value.setText(value)
        self.stance.setText(stance)
        self.setToolTip(note)
        self._anim.stop()
        self._anim.setStartValue(self._accent)
        self._anim.setEndValue(QColor(STATE_COLORS.get(state, STATE_COLORS["na"])))
        self._anim.start()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
        p.fillPath(path, self._bg)
        p.setClipPath(path)
        p.fillRect(0, 0, 4, self.height(), self._accent)


class ResultPanel(QFrame):
    """Fixed-size result card with two pages: summary and "Detail analýzy" (scrollable)."""

    def __init__(self, width: int, height: int):
        super().__init__(objectName="result")
        self.setFixedSize(width, height)
        self._color = QColor(VERDICT_COLORS["START"])
        self._anim = _anim(self, b"vcolor", 450)
        self.pages = QStackedWidget()
        summary, detail = QWidget(), QWidget()
        self.pages.addWidget(summary)
        self.pages.addWidget(detail)

        self.verdict = QLabel("–", alignment=Qt.AlignmentFlag.AlignCenter)
        self.reason = QLabel("Stiskněte START.", wordWrap=True, alignment=Qt.AlignmentFlag.AlignCenter)
        self.reason.setFixedHeight(34)
        self.counts = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter, objectName="muted")
        self.filters = QGridLayout()
        self.filters.setHorizontalSpacing(6)
        self.filters.setVerticalSpacing(0)
        self._filter_labels = []
        for n in range(12):
            lab = QLabel("", objectName="muted")
            lab.setFixedHeight(15)
            self._filter_labels.append(lab)
            self.filters.addWidget(lab, n // 3, n % 3)
        self.levels = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        self.levels.setFixedHeight(48)
        self.levels.setStyleSheet("background: transparent; font-family: Consolas, monospace;")
        self.stamp = QLabel("", objectName="muted", wordWrap=True)
        self.stamp.setFixedHeight(28)
        self.detail_btn = QPushButton("Detail analýzy ▸")
        self.detail_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.detail_btn.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        sl = QVBoxLayout(summary)
        sl.setContentsMargins(10, 6, 10, 6)
        sl.setSpacing(3)
        for w in (self.verdict, self.reason, self.counts):
            sl.addWidget(w)
        sl.addLayout(self.filters)
        sl.addWidget(self.levels)
        bottom = QHBoxLayout()
        bottom.addWidget(self.stamp, 1)
        bottom.addWidget(self.detail_btn, 0, Qt.AlignmentFlag.AlignBottom)
        sl.addLayout(bottom)

        self.detail = QTextBrowser()
        self.detail.setStyleSheet("background: transparent; border: none; font-size: 11px;")
        self.detail.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        back = QPushButton("◂ Zpět")
        back.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(8, 6, 8, 6)
        dl.addWidget(self.detail, 1)
        dl.addWidget(back, 0, Qt.AlignmentFlag.AlignRight)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.pages)
        self._paint_verdict()

    def _get_vcolor(self) -> QColor:
        return self._color

    def _set_vcolor(self, c: QColor):
        self._color = QColor(c)
        self._paint_verdict()

    vcolor = Property(QColor, _get_vcolor, _set_vcolor)

    def _paint_verdict(self, size: int = 24):
        self.verdict.setStyleSheet(f"font-size: {size}px; font-weight: 800; background: transparent; "
                                   f"color: {self._color.name()};")

    def fade_to(self, color: str):
        self._anim.stop()
        self._anim.setStartValue(self._color)
        self._anim.setEndValue(QColor(color))
        self._anim.start()

    def show_filters(self, filters: list[tuple[str, str, str]]):
        for n, lab in enumerate(self._filter_labels):
            if n < len(filters):
                name, status, detail = filters[n]
                icon, color = FILTER_ICONS.get(status, FILTER_ICONS["na"])
                lab.setText(f"<span style='color:{color}'>{icon}</span> {SHORT.get(name, name)}")
                lab.setToolTip(detail)
            else:
                lab.setText("")
                lab.setToolTip("")

    def show_result(self, r: Result, title: str, levels: str, stamp: str, detail_html: str):
        self.verdict.setText(title)
        self.fade_to(VERDICT_COLORS.get(r.verdict, ACCENT))
        why = r.summary or (r.reasons[0] if r.reasons else "")
        self.reason.setText(why[:1].upper() + why[1:])
        self.reason.setToolTip("\n".join(r.reasons))
        c = r.counts
        if c:
            names = (("pro", "proti") if r.direction else ("býčí", "medvědí"))
            self.counts.setText(f"{names[0].capitalize()} {c['pro']} · {names[1]} {c['proti']} · neutrální "
                                f"{c['neutrální']} · nedostupné {c['nedostupné']} · nepoužito {c['nepoužito']}")
        else:
            self.counts.setText("")
        self.show_filters(r.filters)
        self.levels.setText(levels)
        self.stamp.setText(stamp)
        self.detail.setHtml(detail_html)

    def clear(self, text: str = "…"):
        self.verdict.setText(text)
        self.fade_to(ACCENT)
        self.reason.setText("")
        self.counts.setText("")
        self.show_filters([])
        self.levels.setText("")
        self.detail.setHtml("")
        self.pages.setCurrentIndex(0)

    def mark_historical(self, note: str):
        if not self.verdict.text().startswith("HISTORICKÝ"):
            self.verdict.setText(f"HISTORICKÝ · {self.verdict.text()}")
        self.fade_to("#475569")
        self.levels.setStyleSheet("background: transparent; font-family: Consolas, monospace; color: #64748b;")
        self.reason.setText(note)

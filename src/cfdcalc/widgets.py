"""Animated widgets: progress ring, indicator tiles, result panel. Fixed sizes, so updates never resize the window.

Animations (QPropertyAnimation / QVariantAnimation) only interpolate what is drawn; values shown are always real.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import (Property, QEasingCurve, QPropertyAnimation, QRectF, Qt, QVariantAnimation, Signal)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTextBrowser,
                               QVBoxLayout, QWidget)

from .analysis import BUY, ERROR, NO_DATA, SELL, WAIT

GREEN, RED, YELLOW, SLATE = "#22c55e", "#ef4444", "#facc15", "#64748b"
ACCENT = "#60a5fa"
WATCH = "WATCH"
VERDICT_COLORS = {BUY: GREEN, SELL: RED, WAIT: YELLOW, WATCH: YELLOW, NO_DATA: SLATE, ERROR: RED, "START": ACCENT}
# every state is readable without colour: an icon and a word
ICONS = {BUY: "▲", SELL: "▼", WAIT: "■", WATCH: "◆", NO_DATA: "○", ERROR: "⚠", "BULLISH": "▲", "BEARISH": "▼",
         "NEUTRAL": "●"}
BIAS_COLORS = {"BULLISH": GREEN, "BEARISH": RED, "NEUTRAL": "#94a3b8"}
STATE_COLORS = {"bull": GREEN, "bear": RED, "neutral": SLATE, "block": YELLOW, "na": "#334155", "off": "#252c3b",
                "error": RED}
SHORT = {"Aktuální data": "Data", "Shoda indikátorů": "Shoda", "Volatilita (ATR)": "Volatilita",
         "Prostor k cíli": "Prostor", "Ekonomické zprávy": "Zprávy", "Časový limit": "Čas", "RSI extrém": "RSI extrém"}
FILTER_ICONS = {"ok": ("✓", GREEN), "fail": ("✗", RED), "na": ("–", SLATE)}
REDUCED_MOTION = False          # set from Settings / the system preference (ui.py)


def system_reduced_motion() -> bool:
    """Windows "Show animations in Windows" off -> True. Other systems: False."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        on = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0)   # SPI_GETCLIENTAREAANIMATION
        return not on.value
    except (OSError, AttributeError):
        return False


def tint(color: str, alpha: int) -> str:
    c = QColor(color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {alpha})"


def _anim(target, prop: bytes, ms: int) -> QPropertyAnimation:
    a = QPropertyAnimation(target, prop, target)
    a.setDuration(ms)
    a.setEasingCurve(QEasingCurve.Type.OutCubic)
    a.setProperty("base_ms", ms)
    return a


def _go(anim: QPropertyAnimation, start, end):
    """Start an animation; with reduced motion it jumps straight to the end value."""
    anim.stop()
    if REDUCED_MOTION:      # no interpolation at all: the final value is drawn at once
        anim.targetObject().setProperty(bytes(anim.propertyName()).decode(), end)
        return
    anim.setDuration(int(anim.property("base_ms") or 300))
    anim.setStartValue(start)
    anim.setEndValue(end)
    anim.start()


class Gauge(QWidget):
    """Ring with the REAL share of finished analysis steps. A rotating segment only signals "waiting" (network),
    it never stands for a percentage."""
    clicked = Signal()

    def __init__(self, size: int = 128):
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
        running = self._pct_anim.state() == QPropertyAnimation.State.Running
        return float(self._pct_anim.endValue()) if running else self._pct

    def show_state(self, pct: float, title: str, sub: str, color: str = ACCENT, busy: bool = False):
        _go(self._pct_anim, self._pct, float(pct))
        _go(self._color_anim, self._color, QColor(color))
        if (self.title, self.sub) != (title, sub):
            self.title, self.sub = title, sub
            self.setToolTip(sub)
        self.busy = busy
        if busy and not REDUCED_MOTION and self._spinner.state() != QVariantAnimation.State.Running:
            self._spinner.start()
        elif not busy or REDUCED_MOTION:
            self._spinner.stop()
        self.update()

    def mouseReleaseEvent(self, e):
        if self.isEnabled() and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = 11
        r = QRectF(self.rect()).adjusted(w, w, -w, -w)
        p.setPen(QPen(QColor("#232a3a"), w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawEllipse(r)
        if self._pct > 0.2:
            # a technical error is drawn dashed, so it never looks like a (red) SELL
            style = Qt.PenStyle.DashLine if self.title == ERROR else Qt.PenStyle.SolidLine
            p.setPen(QPen(self._color, w, style, Qt.PenCapStyle.FlatCap if self.title == ERROR else
                          Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, -int(self._pct * 360 / 100 * 16))
        if self.busy:
            c = QColor("#93c5fd")
            c.setAlpha(170)
            p.setPen(QPen(c, 3, Qt.PenStyle.SolidLine if not REDUCED_MOTION else Qt.PenStyle.DotLine,
                          Qt.PenCapStyle.RoundCap))
            if REDUCED_MOTION:
                p.drawEllipse(r.adjusted(-w + 3, -w + 3, w - 3, w - 3))
            else:
                p.drawArc(r.adjusted(-w + 3, -w + 3, w - 3, w - 3), int((90 - self._spin) * 16), -50 * 16)
        known = self.title in VERDICT_COLORS
        p.setPen(self._color if known else QColor("#e5e7eb"))
        icon = ICONS.get(self.title, "")
        if icon:
            p.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            p.drawText(r.adjusted(0, -34, 0, -34), Qt.AlignmentFlag.AlignCenter, icon)
        size = 20 if len(self.title) <= 4 else 17 if len(self.title) <= 5 else 14
        p.setFont(QFont("Segoe UI", size, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, self.title)
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Segoe UI", 8))
        p.drawText(r.adjusted(10, 40, -10, 0), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.sub)


class Tile(QWidget):
    """Indicator tile: title, value, role in the decision; the accent colour fades between states."""

    def __init__(self, title: str):
        super().__init__()
        self.setFixedHeight(34)
        self._accent, self._bg = QColor(STATE_COLORS["na"]), QColor("#1a2030")
        self._anim = _anim(self, b"accent", 420)
        self.title, self.value, self.stance = QLabel(title), QLabel("–"), QLabel("")
        self.title.setStyleSheet("font-weight: 600; background: transparent; font-size: 11px;")
        self.value.setStyleSheet("color: #94a3b8; background: transparent; font-size: 10px;")
        self.stance.setStyleSheet("color: #94a3b8; background: transparent; font-size: 10px;")
        self.stance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.title, 1)
        top.addWidget(self.stance)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(11, 2, 8, 2)
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
        color = STATE_COLORS.get(state, STATE_COLORS["na"])
        word = {"error": "⚠ ERROR", "block": f"⚠ {stance}" if stance else "⚠"}.get(state, stance)
        self.stance.setText(word)
        self.stance.setStyleSheet(f"color: {color if state in ('bull', 'bear', 'block', 'error') else '#94a3b8'};"
                                  " background: transparent; font-size: 10px; font-weight: 600;")
        self.setToolTip(note)
        _go(self._anim, self._accent, QColor(color))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 9, 9)
        bg = QColor(self._accent)
        bg.setAlpha(22 if self._shown and self._shown[0] in ("bull", "bear", "block", "error") else 0)
        p.fillPath(path, self._bg)
        p.fillPath(path, bg)
        p.setClipPath(path)
        p.fillRect(0, 0, 4, self.height(), self._accent)


NEUTRAL = "NEUTRAL"
DIRECTION_COLORS = {BUY: GREEN, SELL: RED, NEUTRAL: YELLOW, NO_DATA: SLATE, ERROR: RED}
ICONS[NEUTRAL] = "◆"


class RatioBar(QWidget):
    """BUY vs SELL weight of the arguments, green | red, with the shares written on it (readable without colour)."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(18)
        self.buy: float | None = None

    def set_share(self, buy: float | None):
        if buy != self.buy:
            self.buy = buy
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        p.setClipPath(path)
        if self.buy is None:
            p.fillRect(r, QColor("#232a3a"))
            text_l, text_r = "BUY –", "– SELL"
        else:
            split = r.left() + r.width() * self.buy
            green, red = QColor(GREEN), QColor(RED)
            green.setAlpha(190)
            red.setAlpha(190)
            p.fillRect(QRectF(r.left(), r.top(), split - r.left(), r.height()), green)
            p.fillRect(QRectF(split, r.top(), r.right() - split, r.height()), red)
            text_l, text_r = f"BUY {self.buy:.0%}", f"{1 - self.buy:.0%} SELL"
        p.setClipping(False)
        p.setPen(QColor("#f8fafc"))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        p.drawText(r.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text_l)
        p.drawText(r.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text_r)


class ResultPanel(QFrame):
    """Fixed-size result card: summary, "Detail analýzy" and extra pages (Risk).

    Summary (v2.6): instrument · BUY/SELL ratio · MARKET DIRECTION (big) with its strength · trend and data quality ·
    TRADE CONFIRMATION chip (+ WATCH) · why the entry is (not) confirmed, or SL/TP of a confirmed entry · the three
    strongest reasons · data state and time. A technical ERROR gets a dashed border and the word ERROR."""

    def __init__(self, width: int, height: int):
        super().__init__(objectName="result")
        self.setFixedSize(width, height)
        self._color = QColor(VERDICT_COLORS["START"])
        self._dashed = False
        self._anim = _anim(self, b"vcolor", 450)
        self.pages = QStackedWidget(objectName="pages")
        summary, detail = QWidget(objectName="page"), QWidget(objectName="page")
        self.pages.addWidget(summary)
        self.pages.addWidget(detail)

        self.instrument = QLabel("", objectName="muted")
        self.instrument.setFixedHeight(15)
        self.ratio = RatioBar()
        self.icon = QLabel("", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.verdict = QLabel("–", alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.strength = QLabel("", alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for w in (self.icon, self.verdict, self.strength):
            w.setFixedHeight(30)
        self.strength.setStyleSheet("font-size: 13px; font-weight: 700; color: #e5e7eb; background: transparent;")
        self.trend = QLabel("", objectName="muted")
        self.trend.setFixedHeight(15)
        self.entry = QLabel("", objectName="pill")
        self.entry.setFixedHeight(22)
        self.opportunity = QLabel("", objectName="pill")
        self.opportunity.setFixedHeight(22)
        self.reason = QLabel("Stiskněte START.", wordWrap=True, objectName="reason")
        self.reason.setFixedHeight(29)
        self.reason.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.waiting = QLabel("", wordWrap=True, objectName="waiting")
        self.waiting.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.levels = QLabel("", alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._levels_style(False)
        self.reasons = QLabel("", wordWrap=True, objectName="muted")
        self.reasons.setFixedHeight(58)
        self.reasons.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.stamp = QLabel("", objectName="muted", wordWrap=True)
        self.stamp.setFixedHeight(28)
        self.detail_btn = QPushButton("Detail ▸")
        self.detail_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        self.detail_btn.clicked.connect(lambda: self.pages.setCurrentIndex(1))

        sl = QVBoxLayout(summary)
        sl.setContentsMargins(12, 8, 12, 6)
        sl.setSpacing(3)
        sl.addWidget(self.instrument)
        sl.addWidget(self.ratio)
        big = QHBoxLayout()
        big.setSpacing(6)
        big.addWidget(self.icon)
        big.addWidget(self.verdict, 1)
        big.addWidget(self.strength)
        sl.addLayout(big)
        sl.addWidget(self.trend)
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(self.entry, 1)
        chips.addWidget(self.opportunity)
        sl.addLayout(chips)
        sl.addWidget(self.reason)
        self.lower = QStackedWidget(objectName="pages")      # why not confirmed, or SL/TP of a confirmed entry
        self.lower.setFixedHeight(42)
        self.lower.addWidget(self.waiting)
        self.lower.addWidget(self.levels)
        sl.addWidget(self.lower)
        sl.addWidget(self.reasons)
        self.bottom = QHBoxLayout()
        self.bottom.addWidget(self.stamp, 1)
        self.bottom.addWidget(self.detail_btn, 0, Qt.AlignmentFlag.AlignBottom)
        sl.addLayout(self.bottom)

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
        self._chip(self.entry, "OBCHODNÍ VSTUP –", SLATE)
        self.opportunity.hide()

    def add_page(self, page: QWidget, button: str, back: QPushButton) -> QPushButton:
        """Extra page reachable from the summary (v2.4: RISK MANAGEMENT)."""
        index = self.pages.addWidget(page)
        btn = QPushButton(button)
        btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
        btn.clicked.connect(lambda: self.pages.setCurrentIndex(index))
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.bottom.insertWidget(1, btn, 0, Qt.AlignmentFlag.AlignBottom)
        return btn

    # ---- colour of the card (animated) ----
    def _get_vcolor(self) -> QColor:
        return self._color

    def _set_vcolor(self, c: QColor):
        self._color = QColor(c)
        self._paint_verdict()
        self.update()

    vcolor = Property(QColor, _get_vcolor, _set_vcolor)

    def _paint_verdict(self):
        color = self._color.name()
        size = 26 if len(self.verdict.text()) <= 8 else 16
        self.verdict.setStyleSheet(f"font-size: {size}px; font-weight: 800; background: transparent; color: {color};")
        self.icon.setStyleSheet(f"font-size: 20px; font-weight: 800; background: transparent; color: {color};")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.fillPath(path, QColor("#161b27"))
        glow = QColor(self._color)
        glow.setAlpha(20)
        p.fillPath(path, glow)
        edge = QColor(self._color)
        edge.setAlpha(110)
        p.setPen(QPen(edge, 1.2, Qt.PenStyle.DashLine if self._dashed else Qt.PenStyle.SolidLine))
        p.drawPath(path)

    def fade_to(self, color: str, dashed: bool = False):
        self._dashed = dashed
        _go(self._anim, self._color, QColor(color))

    def _levels_style(self, muted: bool):
        self.levels.setStyleSheet("background: transparent; font-family: Consolas, monospace; font-size: 12px;"
                                  + (" color: #64748b;" if muted else ""))

    @staticmethod
    def _chip(label: QLabel, text: str, color: str, tip: str = ""):
        label.setText(text)
        label.setToolTip(tip)
        label.setStyleSheet(f"background: {tint(color, 34)}; color: {color}; border: 1px solid {tint(color, 90)};"
                            " border-radius: 11px; padding: 0 8px; font-weight: 700; font-size: 11px;")

    # ---- content ----
    def display(self, v: dict):
        """v: the view built by ui.view() - every text shown here comes from the analysis result."""
        self.instrument.setText(v["instrument"])
        self.ratio.set_share(v["buy_share"])
        self.verdict.setText(v["title"])
        self.icon.setText(ICONS.get(v["side"], ""))
        self.strength.setText(v["strength"])
        self.fade_to(DIRECTION_COLORS.get(v["side"], ACCENT), dashed=v["side"] == ERROR)
        self.trend.setText(v["trend"])
        text, color, tip = v["entry"]
        if v["opportunity"]:                     # room for the WATCH pill: shorter entry text
            text = text.replace("OBCHODNÍ VSTUP", "VSTUP")
            self._chip(self.opportunity, *v["opportunity"])
        self.opportunity.setVisible(bool(v["opportunity"]))
        self._chip(self.entry, text, color, tip)
        self.reason.setText(v["reason"])
        self.reason.setToolTip(v["reason_tip"])
        self.waiting.setText(v["waiting"])
        self.waiting.setStyleSheet(f"color: {v['waiting_tone']}; font-size: 11px; background: transparent;")
        self.levels.setText(v["levels"])
        self._levels_style(False)
        self.lower.setCurrentIndex(1 if v["levels"] else 0)
        self.reasons.setText(v["reasons"])
        self.stamp.setText(v["stamp"])
        self.detail.setHtml(v["detail"])

    def clear(self, text: str = "…"):
        self.verdict.setText(text)
        self.icon.setText("")
        self.strength.setText("")
        self.ratio.set_share(None)
        self.fade_to(ACCENT)
        self._paint_verdict()
        self.trend.setText("")
        self.reason.setText("")
        self.waiting.setText("")
        self.reasons.setText("")
        self._chip(self.entry, "OBCHODNÍ VSTUP –", SLATE)
        self.opportunity.hide()
        self.levels.setText("")
        self.lower.setCurrentIndex(0)
        self.detail.setHtml("")
        self.pages.setCurrentIndex(0)

    def mark_stale(self, note: str):
        """A previous result shown while new data load: never presented as current."""
        self.fade_to("#475569")
        self.stamp.setText(note)

    def mark_historical(self, note: str):
        if not self.verdict.text().startswith("HISTORICKÝ"):
            self.verdict.setText(f"HISTORICKÝ · {self.verdict.text()}")
        self.icon.setText("")
        self.strength.setText("")
        self.fade_to("#475569")
        self._levels_style(True)
        self.reason.setText(note)
        self.waiting.setText("Výsledek už neplatí – pro nový instrument spusťte analýzu.")
        self.lower.setCurrentIndex(0)

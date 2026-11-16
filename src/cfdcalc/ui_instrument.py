"""Instrument bar: AUTO/RUČNĚ mode, Trading 212 status, search, favourites/recent, one-shot read, region setup.

It decides WHICH instrument is confirmed (tracker.Tracker); MainWindow only analyses that one. All OCR and
window access runs in a worker thread; the UI thread never blocks on it.
"""
from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QCompleter, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QVBoxLayout, QWidget)

from . import auto, window
from .instruments import BY_SYMBOL, CATALOG, Instrument, labels
from .recognize import match
from .tracker import Tracker

AUTO, MANUAL = "auto", "manual"
CHIPS = 5
STATUS_COLORS = {auto.OK: "#22c55e", auto.NO_WINDOW: "#ef4444", auto.UNSUPPORTED: "#64748b"}


def describe(inst: Instrument) -> str:
    return inst.name if inst.name == inst.symbol else f"{inst.name} ({inst.symbol})"


class ReadTask(QThread):
    """One AUTO reading in a worker thread (OCR takes 0.2-1 s; the first call loads the model)."""
    done = Signal(object)

    def __init__(self, fn: Callable[[], auto.Reading]):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn())
        except Exception as e:  # noqa: BLE001 - any failure is a reading without information
            self.done.emit(auto.Reading(auto.UNREADABLE, f"Rozpoznání selhalo: {type(e).__name__}: {e}"))


class RegionPicker(QWidget):
    """Full-desktop translucent overlay; drag a rectangle around the instrument name inside Trading 212.
    Emits the rectangle in physical screen pixels (Win32 cursor position, exact at any DPI)."""
    picked = Signal(object)

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(QGuiApplication.primaryScreen().virtualGeometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.start = self.end = None
        self._p0 = None

    def _physical(self, e) -> tuple[int, int]:
        if window.SUPPORTED:
            return window.cursor_pos()
        g = self.mapToGlobal(e.position().toPoint())
        return g.x(), g.y()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90))
        p.setPen(QColor("#ffffff"))
        p.drawText(40, 40, "Označte myší název instrumentu v okně Trading 212 (Esc = zrušit)")
        if self.start and self.end:
            from PySide6.QtCore import QRect
            r = QRect(self.start, self.end).normalized()
            p.fillRect(r, QColor(59, 130, 246, 60))
            p.setPen(QPen(QColor("#3b82f6"), 2))
            p.drawRect(r)

    def mousePressEvent(self, e):
        self.start = self.end = e.position().toPoint()
        self._p0 = self._physical(e)

    def mouseMoveEvent(self, e):
        self.end = e.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, e):
        (x0, y0), (x1, y1) = self._p0, self._physical(e)
        self.close()
        rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        if rect[2] > 10 and rect[3] > 8:
            self.picked.emit(rect)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close()


class InstrumentBar(QWidget):
    changed = Signal(object)   # confirmed Instrument or None

    def __init__(self, settings: QSettings, reader: Callable | None = None, backend=window):
        super().__init__()
        self.s = settings
        self.backend = backend
        self.reader = reader or (lambda region: auto.read(region, backend))
        self.tracker = Tracker(stable=2)
        self.reading: auto.Reading | None = None
        self._task: ReadTask | None = None
        self._busy = False  # set/cleared in the UI thread only; QThread.isRunning() can lag behind `finished`
        self._queued: list[tuple[int, Callable | None]] = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)

        self.name = QLabel("–")
        self.name.setStyleSheet("font-size: 15px; font-weight: 600; background: transparent;")
        self.name.setToolTip("Potvrzený instrument – analyzuje se jen tento")
        self.fav = QPushButton("☆", checkable=True, toolTip="Přidat do oblíbených")
        self.fav.clicked.connect(self.toggle_favourite)
        self.auto_btn = QPushButton("AUTO", checkable=True, toolTip="Rozpoznávat instrument z Trading 212")
        self.manual_btn = QPushButton("RUČNĚ", checkable=True, toolTip="Instrument volíte sami")
        group = QButtonGroup(self)
        for b in (self.auto_btn, self.manual_btn):
            group.addButton(b)
        self.auto_btn.clicked.connect(lambda: self.set_mode(AUTO))
        self.manual_btn.clicked.connect(lambda: self.set_mode(MANUAL))
        self.load_btn = QPushButton("⟳", toolTip="Načíst instrument z Trading 212 (jednorázově)")
        self.load_btn.clicked.connect(lambda: self.read_once())
        self.area_btn = QPushButton("▭", toolTip="Nastavit oblast s názvem instrumentu v okně Trading 212")
        self.area_btn.clicked.connect(self.pick_region)
        self.status = QLabel("", objectName="muted", wordWrap=True)
        self.search = QLineEdit(placeholderText="Hledat instrument (název, ticker)…")
        self._entries = {f"{a} – {describe(i)}" if a not in (i.name, i.symbol) else describe(i): i
                         for i in CATALOG for a in labels(i)}
        completer = QCompleter(sorted(self._entries), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.activated.connect(self._picked_entry)
        self.search.setCompleter(completer)
        self.search.returnPressed.connect(self._search_enter)

        top = QHBoxLayout()
        top.setSpacing(4)
        top.addWidget(self.name, 1)
        top.addWidget(self.fav)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(4)
        for b in (self.auto_btn, self.manual_btn, self.load_btn, self.area_btn):
            self.buttons.addWidget(b)
        for b in (self.fav, self.load_btn, self.area_btn):
            b.setFixedWidth(34)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(4)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(5)
        lay.addLayout(top)
        lay.addLayout(self.buttons)
        lay.addWidget(self.status)
        lay.addWidget(self.search)
        lay.addLayout(self.chips)

        if self.mode() == MANUAL and self.s.value("symbol", "") in BY_SYMBOL:
            self.tracker.set_manual(BY_SYMBOL[self.s.value("symbol")])
        self.set_mode(self.mode(), initial=True)

    # ---- settings ----
    def mode(self) -> str:
        return self.s.value("mode", AUTO)

    def watching(self) -> bool:
        return self.s.value("watch", True, type=bool)

    def interval_ms(self) -> int:
        return int(1000 * min(3.0, max(2.0, float(self.s.value("watch_interval", 2.5)))))

    def region(self) -> window.Region | None:
        v = self.s.value("t212_region")
        try:
            return window.Region(*map(float, v)) if v else None
        except (TypeError, ValueError):
            return None

    def _list(self, key: str) -> list[str]:
        v = self.s.value(key, [])
        v = [v] if isinstance(v, str) else list(v or [])
        return [x for x in v if x in BY_SYMBOL]

    # ---- mode, timer ----
    def set_mode(self, mode: str, initial: bool = False):
        self.s.setValue("mode", mode)
        self.auto_btn.setChecked(mode == AUTO)
        self.manual_btn.setChecked(mode == MANUAL)
        self.apply_settings()
        if mode == AUTO and not initial:
            self.read_once()
        self._show()

    def apply_settings(self):
        if self.mode() == AUTO and self.watching():
            self.timer.start(self.interval_ms())
        else:
            self.timer.stop()

    def tick(self):
        if not self._busy:  # never queue up readings
            self._read(stable=None)

    # ---- readings ----
    def read_once(self, then: Callable[[auto.Reading], None] | None = None):
        """One immediate reading (a single confident result is enough to confirm)."""
        self._read(stable=1, then=then)

    def _read(self, stable: int | None, then=None):
        if self._busy:
            self._queued.append((stable, then))
            return
        self._busy = True
        region = self.region()
        self._task = ReadTask(lambda: self.reader(region))
        self._task.done.connect(lambda r, st=stable, cb=then: self._on_reading(r, st, cb))
        self._task.finished.connect(self._next)
        self._task.start()

    def _next(self):
        self._busy = False
        if self._queued:
            stable, then = self._queued.pop(0)
            self._read(stable, then)

    def _on_reading(self, reading: auto.Reading, stable: int | None, then):
        self.reading = reading
        if self.mode() == AUTO or stable == 1:
            if self.tracker.feed(reading, stable):
                self._emit()
        self._show()
        if then:
            then(reading)

    def wait_idle(self, ms: int = 15000):
        """Tests and shutdown: wait for the reading worker while still processing UI events (a window of
        this process being captured must be able to answer PrintWindow)."""
        deadline = time.monotonic() + ms / 1000
        while (self._busy or self._queued) and time.monotonic() < deadline:
            if self._task:
                self._task.wait(20)
            QGuiApplication.processEvents()

    # ---- manual choice ----
    def choose(self, first: tuple[Instrument, ...] = (), note: str = "", ocr_text: str = "") -> Instrument | None:
        items = list(dict.fromkeys(first)) + [i for i in CATALOG if i not in first]
        names = [f"{describe(i)}, {i.kind}" for i in items]
        label, ok = QInputDialog.getItem(self, "Výběr instrumentu", note or "Instrument:", names, 0, False)
        if not ok:
            return None
        inst = items[names.index(label)]
        if self.tracker.set_manual(inst, ocr_text):
            self._emit()
        self._show()
        return inst

    def set_manual(self, inst: Instrument):
        """Search, chips, tests: an explicit choice switches to RUČNĚ so AUTO cannot override it."""
        self.s.setValue("mode", MANUAL)
        self.auto_btn.setChecked(False)
        self.manual_btn.setChecked(True)
        self.apply_settings()
        if self.tracker.set_manual(inst):
            self._emit()
        self._show()

    def _picked_entry(self, text: str):
        if text in self._entries:
            self.set_manual(self._entries[text])
            QTimer.singleShot(0, self.search.clear)

    def _search_enter(self):
        text = self.search.text().strip()
        if not text:
            return
        if text in self._entries:
            return self._picked_entry(text)
        rec = match([text])
        if rec.confident:
            self.set_manual(rec.best)
            self.search.clear()
        elif self.choose(rec.candidates, f"„{text}“ – vyberte instrument:"):
            self.set_manual(self.tracker.confirmed)
            self.search.clear()

    # ---- START gate ----
    def confirm_for_start(self, go: Callable[[Instrument], None]):
        """Call go(inst) only with an unambiguous, currently confirmed instrument."""
        if self.mode() == MANUAL:
            inst = self.tracker.confirmed or self.choose(note="Instrument není vybrán. Vyberte ho:")
            if inst:
                go(inst)
            return
        self.read_once(then=lambda r: self._start_after(r, go))

    def _start_after(self, reading: auto.Reading, go):
        target = self.tracker.interpret(reading)
        if isinstance(target, Instrument) and target == self.tracker.confirmed:
            go(target)
            return
        rec = reading.recognition
        why = reading.message or (rec.reason if rec else "") or "instrument nelze určit"
        first = rec.candidates if rec and rec.candidates else tuple(x for x in (self.tracker.confirmed,) if x)
        ocr_text = rec.text if rec and reading.status == auto.OK else ""
        inst = self.choose(first, f"Instrument nelze bezpečně určit: {why}\nVyberte instrument, který vidíte "
                                  f"v Trading 212:", ocr_text)
        if inst:
            go(inst)

    # ---- region ----
    def pick_region(self):
        if not self.backend.SUPPORTED:
            QMessageBox.information(self, "Oblast", "Nastavení oblasti v okně Trading 212 funguje jen ve Windows.")
            return
        if not self.backend.list_t212():
            QMessageBox.warning(self, "Oblast", "Okno Trading 212 nenalezeno. Otevřete ho (v prohlížeči jako "
                                              "aktivní záložku) a zkuste to znovu.")
            return
        self._picker = RegionPicker()
        self._picker.picked.connect(self.save_region)
        self._picker.show()

    def save_region(self, rect: tuple[int, int, int, int]) -> bool:
        wins = self.backend.list_t212()
        win = self.backend.pick(wins, self.backend.foreground()) if wins else None
        region = window.to_region(rect, win) if win else None
        if region is None:
            QMessageBox.warning(self, "Oblast", "Označená oblast neleží v okně Trading 212. Zkuste to znovu.")
            return False
        self.s.setValue("t212_region", [region.x, region.y, region.w, region.h])
        self.read_once()
        return True

    # ---- favourites / recent ----
    def remember(self, inst: Instrument):
        recent = [inst.symbol] + [x for x in self._list("recent") if x != inst.symbol]
        self.s.setValue("recent", recent[:8])
        self._show()

    def toggle_favourite(self):
        inst = self.tracker.confirmed
        if not inst:
            self.fav.setChecked(False)
            return
        favs = [x for x in self._list("favorites") if x != inst.symbol]
        if self.fav.isChecked():
            favs.insert(0, inst.symbol)
        self.s.setValue("favorites", favs)
        self._show()

    def _chips(self):
        while self.chips.count():
            w = self.chips.takeAt(0).widget()
            if w:
                w.deleteLater()
        favs = self._list("favorites")
        shown = list(dict.fromkeys(favs + self._list("recent")))[:CHIPS]
        for sym in shown:
            inst = BY_SYMBOL[sym]
            b = QPushButton(("★ " if sym in favs else "") + sym, toolTip=describe(inst))
            b.setStyleSheet("padding: 2px 6px; font-size: 11px;")
            b.clicked.connect(lambda _=False, i=inst: self.set_manual(i))
            self.chips.addWidget(b)
        self.chips.addStretch(1)

    # ---- display ----
    def _emit(self):
        inst = self.tracker.confirmed
        if inst:
            self.s.setValue("symbol", inst.symbol)
        self.changed.emit(inst)

    def _status(self) -> tuple[str, str]:
        if self.mode() == MANUAL:
            return "Režim RUČNĚ – Trading 212 se nesleduje.", "#64748b"
        r = self.reading
        if r is None:
            return "AUTO: čekám na první čtení Trading 212…", "#64748b"
        if r.status != auto.OK:
            return r.message, STATUS_COLORS.get(r.status, "#f59e0b")
        rec = r.recognition
        title = f"Trading 212 připojeno ({r.win.title[:40]})" if r.win else "Trading 212 připojeno"
        target = self.tracker.interpret(r)
        if isinstance(target, Instrument):
            pending = "" if target == self.tracker.confirmed else " – ověřuji změnu…"
            return f"{title} · vidím {target.name}{pending}", "#22c55e"
        return f"{title} · {rec.reason}. Klikněte ⟳ nebo zvolte ručně.", "#f59e0b"

    def _show(self):
        inst = self.tracker.confirmed
        self.name.setText(describe(inst) if inst else "Instrument neurčen")
        self.fav.setChecked(bool(inst) and inst.symbol in self._list("favorites"))
        self.fav.setText("★" if self.fav.isChecked() else "☆")
        text, color = self._status()
        self.status.setText(f"<span style='color:{color}'>●</span> {text}")
        self._chips()

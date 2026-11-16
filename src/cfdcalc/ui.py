"""PySide6 window. The app only shows analysis; it has no code path that sends orders anywhere."""
from __future__ import annotations

import os
import sys
from datetime import datetime, time, timezone
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThread, QTime, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from . import __version__
from .analysis import BUY, MODULES, SELL, TITLES, WAIT, Result, Settings, run_analysis
from .backtest import journal_add, journal_read, journal_verify, run_backtest
from .calendar import Calendar
from .data import DataError, SyntheticData, TwelveData
from .instruments import BY_SYMBOL, Instrument
from .ui_instrument import InstrumentBar

APP = "CFD Signal Calculator"
COLORS = {"bull": "#22c55e", "bear": "#ef4444", "neutral": "#64748b", "block": "#f59e0b", "na": "#334155"}
VERDICT_COLORS = {BUY: "#22c55e", SELL: "#ef4444", WAIT: "#f59e0b"}
UNMAPPED = ("{name}: Twelve Data pod symbolem {symbol} neuvádí tento instrument (mapování neověřeno), "
            "proto se neanalyzuje")
STYLE = """
QWidget { background: #11151d; color: #e5e7eb; font-family: 'Segoe UI', sans-serif; font-size: 12px; }
QPushButton { background: #1e2533; border: 1px solid #2b3446; border-radius: 8px; padding: 6px 10px; }
QPushButton:hover { background: #273046; }
QPushButton:disabled { color: #6b7280; }
QPushButton:checked { background: #1d4ed8; border-color: #3b82f6; font-weight: 600; }
QLineEdit, QSpinBox, QTimeEdit { background: #1a2030; border: 1px solid #2b3446; border-radius: 6px; padding: 4px; }
QFrame#tile { background: #1a2030; border-radius: 10px; }
QFrame#result { background: #161b27; border-radius: 12px; }
QLabel#muted { color: #94a3b8; font-size: 11px; background: transparent; }
QProgressBar { background: #1a2030; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #3b82f6; border-radius: 6px; }
"""


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


class Task(QThread):
    """Runs fn(progress) off the UI thread; any exception becomes `failed` (the UI then shows WAIT)."""
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.done.emit(self.fn(lambda a, b, s="": self.progress.emit(a, b, s)))
        except Exception as e:  # noqa: BLE001 - surfaced to the user, never swallowed
            self.failed.emit(f"{type(e).__name__}: {e}")


class Gauge(QWidget):
    clicked = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedSize(210, 210)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Spustit analýzu")
        self.pct, self.title, self.sub, self.color = 0, "START", "spustit analýzu", QColor("#3b82f6")

    def show_state(self, pct: int, title: str, sub: str, color: str = "#3b82f6"):
        self.pct, self.title, self.sub, self.color = pct, title, sub, QColor(color)
        self.update()

    def mouseReleaseEvent(self, e):
        if self.isEnabled() and e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(14, 14, -14, -14)
        p.setPen(QPen(QColor("#232a3a"), 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawEllipse(r)
        if self.pct:
            p.setPen(QPen(self.color, 14, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(r, 90 * 16, -int(self.pct * 360 / 100 * 16))
        p.setPen(self.color if self.title in VERDICT_COLORS else QColor("#e5e7eb"))
        p.setFont(QFont("Segoe UI", 30, QFont.Weight.Bold))
        p.drawText(r.adjusted(0, -20, 0, -20), Qt.AlignmentFlag.AlignCenter, self.title)
        p.setPen(QColor("#94a3b8"))
        p.setFont(QFont("Segoe UI", 10))
        p.drawText(r.adjusted(0, 50, 0, 0), Qt.AlignmentFlag.AlignCenter, self.sub)


class Tile(QFrame):
    def __init__(self, key: str):
        super().__init__(objectName="tile")
        self.title, self.value = QLabel(TITLES[key]), QLabel("–")
        self.title.setStyleSheet("font-weight: 600; background: transparent;")
        self.value.setStyleSheet("color: #94a3b8; background: transparent; font-size: 11px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(1)
        lay.addWidget(self.title)
        lay.addWidget(self.value)
        self.set("na", "–", "")

    def set(self, state: str, value: str, note: str):
        self.value.setText(value)
        self.setToolTip(note)
        self.setStyleSheet(f"QFrame#tile {{ border-left: 4px solid {COLORS[state]}; }}")


class SettingsDialog(QDialog):
    def __init__(self, s: QSettings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nastavení")
        self.s = s
        self.key = QLineEdit(s.value("api_key", ""), echoMode=QLineEdit.EchoMode.Password)
        self.cutoff = QTimeEdit(QTime.fromString(s.value("cutoff", "21:00"), "HH:mm"))
        self.left = QSpinBox(minimum=0, maximum=600, value=int(s.value("min_left", 60)))
        self.demo = QCheckBox("Offline demo (syntetická data, ne trh)")
        self.demo.setChecked(s.value("demo", False, type=bool))
        self.watch = QCheckBox("V režimu AUTO průběžně sledovat Trading 212")
        self.watch.setChecked(s.value("watch", True, type=bool))
        self.interval = QDoubleSpinBox(minimum=2.0, maximum=3.0, singleStep=0.5, suffix=" s",
                                       value=float(s.value("watch_interval", 2.5)))
        form = QFormLayout(self)
        form.addRow("Twelve Data API klíč", self.key)
        form.addRow("Večerní limit (místní čas)", self.cutoff)
        form.addRow("Min. minut do limitu", self.left)
        form.addRow(self.demo)
        form.addRow(self.watch)
        form.addRow("Interval sledování", self.interval)
        note = QLabel(f"Klíč se ukládá nešifrovaně do {s.fileName()}.\n"
                      "Alternativa: proměnná prostředí TWELVEDATA_API_KEY.", objectName="muted")
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def save(self):
        self.s.setValue("api_key", self.key.text().strip())
        self.s.setValue("cutoff", self.cutoff.time().toString("HH:mm"))
        self.s.setValue("min_left", self.left.value())
        self.s.setValue("demo", self.demo.isChecked())
        self.s.setValue("watch", self.watch.isChecked())
        self.s.setValue("watch_interval", self.interval.value())
        self.accept()


class TextDialog(QDialog):
    """Progress bar + text output + optional action button (backtest, journal)."""

    def __init__(self, title: str, action: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 420)
        self.bar, self.text, self.btn = QProgressBar(), QPlainTextEdit(readOnly=True), QPushButton(action)
        lay = QVBoxLayout(self)
        for w in (self.bar, self.text, self.btn):
            lay.addWidget(w)


class MainWindow(QWidget):
    def __init__(self, reader=None):
        super().__init__()
        self.s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "CFDSignalCalculator", "app")
        self.task: Task | None = None
        self.analysed: Instrument | None = None     # instrument of the running / last analysis
        self.shown: Instrument | None = None        # instrument of the result on screen (None = no result)
        self.setWindowTitle(APP)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self.bar = InstrumentBar(self.s, reader)
        self.bar.changed.connect(self.on_instrument_changed)
        gear = QPushButton("⚙", toolTip="Nastavení")
        gear.setFixedWidth(34)
        gear.clicked.connect(self.settings)
        self.bar.buttons.addWidget(gear)

        self.banner = QLabel("DEMO – syntetická data, nejde o tržní signál")
        self.banner.setStyleSheet("background: #7c2d12; color: #fed7aa; border-radius: 6px; padding: 4px;")
        self.banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gauge = Gauge()
        self.gauge.clicked.connect(self.start)
        self.step = QLabel("Připraveno", objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)

        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles = {k: Tile(k) for k in MODULES}
        for n, k in enumerate(MODULES):
            grid.addWidget(self.tiles[k], n // 2, n % 2)

        res = QFrame(objectName="result")
        res.setFixedWidth(332)
        rl = QVBoxLayout(res)
        self.verdict = QLabel("–", alignment=Qt.AlignmentFlag.AlignCenter)
        self.verdict.setStyleSheet("font-size: 26px; font-weight: 800; background: transparent;")
        self.levels = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        self.levels.setStyleSheet("background: transparent; font-family: Consolas, monospace;")
        self.explain = QLabel("Stiskněte START.", wordWrap=True)
        self.explain.setStyleSheet("background: transparent;")
        self.stamp = QLabel("", objectName="muted", wordWrap=True)
        for w in (self.verdict, self.levels, self.explain, self.stamp):
            rl.addWidget(w)

        self.spread = QLineEdit()
        self.spread.setToolTip("Aktuální spread z Trading 212 (rozdíl BUY − SELL) v cenových jednotkách")
        self.spread.editingFinished.connect(self.save_spread)
        sp = QHBoxLayout()
        sp.addWidget(QLabel("Spread z T212:"))
        sp.addWidget(self.spread, 1)
        bt, jr = QPushButton("Backtest"), QPushButton("Demo deník")
        bt.clicked.connect(self.backtest)
        jr.clicked.connect(self.journal)
        bottom = QHBoxLayout()
        bottom.addWidget(bt)
        bottom.addWidget(jr)

        lay = QVBoxLayout(self)
        lay.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)  # calculator-like: window follows content
        lay.setContentsMargins(14, 12, 14, 12)
        lay.addWidget(self.bar)
        lay.addWidget(self.banner)
        lay.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.step)
        lay.addLayout(grid)
        lay.addWidget(res)
        lay.addLayout(sp)
        lay.addLayout(bottom)
        lay.addWidget(QLabel(f"v{__version__} · pouze analýza, žádné zadávání obchodů", objectName="muted",
                             alignment=Qt.AlignmentFlag.AlignCenter))
        self.refresh_header()

    # ---- settings helpers ----
    def cfg(self) -> Settings:
        hh, mm = map(int, self.s.value("cutoff", "21:00").split(":"))
        return Settings(cutoff=time(hh, mm), min_minutes_left=int(self.s.value("min_left", 60)))

    def demo(self) -> bool:
        return self.s.value("demo", False, type=bool)

    def provider(self):
        if self.demo():
            return SyntheticData()
        return TwelveData(os.environ.get("TWELVEDATA_API_KEY") or self.s.value("api_key", ""))

    def spread_of(self, inst: Instrument) -> float:
        try:
            return float(self.s.value(f"spread/{inst.symbol}", inst.spread))
        except (TypeError, ValueError):
            return 0.0

    def save_spread(self):
        if self.inst:
            try:
                value = float(self.spread.text().replace(",", "."))
            except ValueError:
                value = 0.0  # invalid input -> analysis reports "spread není zadán"
            self.s.setValue(f"spread/{self.inst.symbol}", value)

    @property
    def inst(self) -> Instrument | None:
        """The confirmed instrument (the only one that may be analysed)."""
        return self.bar.tracker.confirmed

    def set_instrument(self, inst: Instrument):
        self.bar.set_manual(inst)

    def settings(self):
        if SettingsDialog(self.s, self).exec():
            self.bar.apply_settings()
            self.refresh_header()

    def refresh_header(self):
        self.spread.setText(f"{self.spread_of(self.inst):g}" if self.inst else "")
        self.banner.setVisible(self.demo())

    def on_instrument_changed(self, inst: Instrument | None):
        self.refresh_header()
        if self.shown and inst != self.shown:
            self.mark_historical()
        if not (self.task and self.task.isRunning()):
            self.gauge.show_state(0, "START", "spustit analýzu" if inst else "vyberte instrument")

    def mark_historical(self):
        """The instrument changed: the result on screen no longer applies to what Trading 212 shows."""
        grey = "font-size: 18px; font-weight: 800; background: transparent; color: #64748b;"
        self.verdict.setText(f"HISTORICKÝ · {self.verdict.text().removeprefix('HISTORICKÝ · ')}")
        self.verdict.setStyleSheet(grey)
        self.levels.setStyleSheet("background: transparent; font-family: Consolas, monospace; color: #64748b;")
        for t in self.tiles.values():  # the indicator colours belonged to the old instrument
            t.setStyleSheet(f"QFrame#tile {{ border-left: 4px solid {COLORS['na']}; }}")
        note = f"Instrument se změnil – signál platí jen pro {self.shown.name} ({self.shown.symbol}) a je historický."
        if not self.explain.text().startswith("Instrument se změnil"):
            self.explain.setText(note + "\n" + self.explain.text())

    # ---- analysis ----
    def start(self):
        if self.task and self.task.isRunning():
            return
        self.save_spread()
        self.bar.confirm_for_start(self.begin)

    def begin(self, inst: Instrument):
        if self.task and self.task.isRunning() or inst != self.inst:
            return
        try:
            provider = self.provider()
        except DataError as e:
            QMessageBox.warning(self, APP, str(e))
            return
        self.refresh_header()
        spread, cfg = self.spread_of(inst), self.cfg()
        calendar = _NoNews() if self.demo() else Calendar(data_dir() / "calendar.json")
        for t in self.tiles.values():
            t.set("na", "…", "")
        self.analysed, self.shown = inst, None
        self.bar.remember(inst)
        if not inst.td_verified:
            self.started = datetime.now(timezone.utc)
            self.on_result(Result(reasons=[UNMAPPED.format(name=inst.name, symbol=inst.symbol)], aborted=True))
            return
        self.verdict.setText("…")
        self.levels.setText("")
        self.explain.setText("")
        self.gauge.setEnabled(False)
        self.gauge.show_state(0, "0 %", "analýza")
        now = datetime.now(timezone.utc)
        self.started = now
        self.task = Task(lambda p: run_analysis(inst, provider, calendar, spread, now, cfg, p))
        self.task.progress.connect(self.on_progress)
        self.task.done.connect(self.on_result)
        self.task.failed.connect(lambda msg: self.on_result(Result(reasons=[f"chyba analýzy: {msg}"], aborted=True)))
        self.task.start()

    def on_progress(self, done: int, total: int, label: str):
        pct = round(100 * done / total)
        self.gauge.show_state(pct, f"{pct} %", "analýza")
        self.step.setText(f"{done}/{total} · {label}")

    def on_result(self, r: Result):
        inst = self.analysed
        self.shown = inst
        self.gauge.setEnabled(True)
        pct = round(100 * r.completed / r.total) if r.total else 0
        self.gauge.show_state(pct, r.verdict, "přerušeno – klikněte znovu" if r.aborted else "hotovo · znovu",
                              VERDICT_COLORS[r.verdict])
        self.verdict.setText(("DEMO " if self.demo() else "") + r.verdict)
        self.verdict.setStyleSheet(f"font-size: 26px; font-weight: 800; background: transparent; "
                                   f"color: {VERDICT_COLORS[r.verdict]};")
        self.levels.setStyleSheet("background: transparent; font-family: Consolas, monospace;")
        for k, t in self.tiles.items():
            m = r.modules.get(k)
            t.set(m.state, m.value, m.note) if m else t.set("na", "–", "nevyhodnoceno")
        why = "; ".join(r.reasons)
        self.explain.setText(("Trend 1h: " + r.trend + ". " if r.modules else "") + why[:1].upper() + why[1:] + ".")
        data = (f"data do {r.data_time:%H:%M} UTC ({r.data_time.astimezone():%H:%M} místního)" if r.data_time
                else "data nejsou")
        self.stamp.setText(f"Analýza {self.started.astimezone():%H:%M:%S} · {inst.symbol} · {data}")
        if r.verdict in (BUY, SELL):
            e = float(r.entry)
            dist = lambda x: f"{abs(float(x) - e):g} / {abs(float(x) - e) / e:.2%}"  # noqa: E731
            self.levels.setText(f"Vstup {r.entry}\nSL {r.sl}  (−{dist(r.sl)})\nTP {r.tp}  (+{dist(r.tp)})")
            self.explain.setText(self.explain.text() + "\nCeny CFD v T212 se mohou lišit od Twelve Data – "
                                                       "přeneste vzdálenosti SL/TP. Obchod zadáváte sami.")
        if inst != self.inst:  # the instrument changed while the analysis was running
            self.mark_historical()
            return
        if r.verdict in (BUY, SELL) and not self.demo():
            journal_add(data_dir() / "journal.csv", inst.symbol, r.verdict, r.data_time, r.entry, r.sl, r.tp)

    # ---- backtest + demo journal ----
    def backtest(self):
        if not self.inst and not self.bar.choose(note="Instrument není vybrán. Vyberte ho:"):
            return
        try:
            provider = self.provider()
        except DataError as e:
            QMessageBox.warning(self, APP, str(e))
            return
        inst, spread, cfg = self.inst, self.spread_of(self.inst), self.cfg()
        if not inst.td_verified:
            QMessageBox.information(self, APP, UNMAPPED.format(name=inst.name, symbol=inst.symbol))
            return
        dlg = TextDialog(f"Backtest – {inst.name}", "Spustit", self)
        dlg.text.setPlainText("Stejná pravidla jako živá analýza na posledních až 5000 svíčkách 5m (3 API dotazy).\n"
                              "Bez historického filtru zpráv; vstup za close + spread; SL a TP v jedné svíčce = SL.\n"
                              "Krátká historie není statistický důkaz ziskovosti.")

        def run():
            dlg.btn.setEnabled(False)
            dlg._task = Task(lambda p: run_backtest(inst, provider, spread, cfg, lambda a, b: p(a, b)))
            dlg._task.progress.connect(lambda a, b, _: (dlg.bar.setMaximum(max(b, 1)), dlg.bar.setValue(a)))
            dlg._task.done.connect(lambda rep: dlg.text.setPlainText(
                rep.summary() + "\n\n" + "\n".join(
                    f"{t.time:%d.%m. %H:%M}  {t.direction:4}  {t.how:14} {'' if t.r is None else f'{t.r:+.2f} R'}"
                    for t in rep.trades[-200:])))
            dlg._task.failed.connect(lambda m: dlg.text.setPlainText(f"Backtest selhal: {m}"))
            dlg._task.finished.connect(lambda: dlg.btn.setEnabled(True))
            dlg._task.start()

        dlg.btn.clicked.connect(run)
        dlg.exec()

    def journal(self):
        path = data_dir() / "journal.csv"
        dlg = TextDialog("Demo deník signálů", "Ověřit výsledky podle dat", self)
        dlg.bar.hide()

        def show(rows):
            lines = [f"{r['time_utc'][:16]}  {r['symbol']:8} {r['direction']:4} vstup {r['entry']} SL {r['sl']} "
                     f"TP {r['tp']}  {r['result_r'] or '?'} {r['how']}" for r in rows]
            done = [float(r["result_r"]) for r in rows if r["result_r"]]
            head = (f"Vyhodnoceno {len(done)} z {len(rows)} signálů, součet {sum(done):+.2f} R\n\n" if done
                    else "Zatím žádný vyhodnocený signál. Každý BUY/SELL se sem zapisuje automaticky.\n\n")
            dlg.text.setPlainText(head + "\n".join(lines))

        def verify():
            try:
                provider = self.provider()
            except DataError as e:
                dlg.text.setPlainText(str(e))
                return
            dlg.btn.setEnabled(False)
            spread = lambda sym: self.spread_of(BY_SYMBOL[sym]) if sym in BY_SYMBOL else 0.0  # noqa: E731
            dlg._task = Task(lambda _: journal_verify(path, provider, spread, datetime.now(timezone.utc), self.cfg()))
            dlg._task.done.connect(show)
            dlg._task.failed.connect(lambda m: dlg.text.setPlainText(f"Ověření selhalo: {m}"))
            dlg._task.finished.connect(lambda: dlg.btn.setEnabled(True))
            dlg._task.start()

        show(journal_read(path))
        dlg.btn.clicked.connect(verify)
        dlg.exec()


class _NoNews:
    """Offline demo only: an empty calendar (the live mode uses the real one and fails closed)."""

    def events(self):
        return []


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

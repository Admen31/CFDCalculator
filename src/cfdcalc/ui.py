"""PySide6 window. The app only shows analysis; it has no code path that sends orders anywhere.

Responsiveness: OCR, network and model loading run in worker threads; the window has a fixed size (no layout
jumps); widgets repaint only when their content changes; animations interpolate real values only.
"""
from __future__ import annotations

import html
import os
import sys
import threading
from datetime import datetime, time, timezone
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThread, QTime, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from . import __version__, widgets
from . import strategies as st
from .analysis import BUY, ERROR, MODULES, NO_DATA, PROFILES, SELL, TITLES, Result, Settings, run_analysis
from .backtest import HISTORY, journal_add, journal_read, journal_verify
from .engine import Costs, Market
from .report import research_text
from .validation import research
from .availability import Availability, state_text
from .calendar import Calendar
from .data import CachedProvider, DataError, SyntheticData, TwelveData
from .instruments import BY_SYMBOL, Instrument
from .ui_instrument import AUTO, InstrumentBar
from .widgets import ACCENT, BIAS_COLORS, GREEN, RED, SLATE, VERDICT_COLORS, YELLOW, Gauge, ResultPanel, Tile

APP = "CFD Signal Calculator"
WIDTH = 380
ANALYSIS_TIMEOUT_MS = 75_000    # 3 requests x 15 s + calendar 15 s + margin; then the analysis is abandoned
STYLE = """
QWidget { background: #11151d; color: #e5e7eb; font-family: 'Segoe UI', sans-serif; font-size: 12px; }
QPushButton { background: #1e2533; border: 1px solid #2b3446; border-radius: 8px; padding: 6px 10px; }
QPushButton:hover { background: #273046; }
QPushButton:disabled { color: #6b7280; }
QPushButton:checked { background: #1d4ed8; border-color: #3b82f6; font-weight: 600; }
QLineEdit, QSpinBox, QTimeEdit, QDoubleSpinBox { background: #1a2030; border: 1px solid #2b3446; border-radius: 6px;
  padding: 4px; }
QFrame#result { background: transparent; }
QWidget#page, QStackedWidget#pages { background: transparent; }
QLabel#muted { color: #94a3b8; font-size: 11px; background: transparent; }
QLabel#caption { color: #64748b; font-size: 9px; font-weight: 700; letter-spacing: 1px; background: transparent; }
QLabel#reason { color: #e5e7eb; font-size: 11px; background: transparent; }
QLabel#waiting { color: #fde68a; font-size: 11px; background: transparent; }
QProgressBar { background: #1a2030; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #3b82f6; border-radius: 6px; }
QTextBrowser { color: #cbd5e1; }
"""
UNMAPPED = ("{name}: Twelve Data pod symbolem {symbol} neuvádí tento instrument (mapování neověřeno), "
            "proto se neanalyzuje")
NEXT_STEP = {"Instrument": "čekám na Twelve Data (5 min)…", "Data 5min ověřena": "čekám na Twelve Data (15 min)…",
             "Data 15min ověřena": "čekám na Twelve Data (1 h)…", "Data 1h ověřena": "načítám kalendář zpráv…"}


def data_dir() -> Path:
    return Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))


class Task(QThread):
    """Runs fn(progress) off the UI thread; any exception becomes `failed` (the UI then shows ERROR)."""
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


class SettingsDialog(QDialog):
    def __init__(self, s: QSettings, parent=None, probe=None, probe_label: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Nastavení")
        self.s = s
        self.key = QLineEdit(s.value("api_key", ""), echoMode=QLineEdit.EchoMode.Password)
        self.cutoffs = {k: QTimeEdit(QTime.fromString(s.value(f"cutoff/{k}", f"{p.cutoff:%H:%M}"), "HH:mm"))
                        for k, p in PROFILES.items()}
        self.left = QSpinBox(minimum=0, maximum=600, value=int(s.value("min_left", 60)))
        self.demo = QCheckBox("Offline demo (syntetická data, ne trh)")
        self.demo.setChecked(s.value("demo", False, type=bool))
        self.watch = QCheckBox("V režimu AUTO průběžně sledovat Trading 212")
        self.watch.setChecked(s.value("watch", True, type=bool))
        self.interval = QDoubleSpinBox(minimum=2.0, maximum=3.0, singleStep=0.5, suffix=" s",
                                       value=float(s.value("watch_interval", 2.5)))
        self.motion = QCheckBox("Omezit animace (výchozí podle nastavení Windows)")
        self.motion.setChecked(s.value("reduced_motion", widgets.system_reduced_motion(), type=bool))
        self.rate = QSpinBox(minimum=1, maximum=600, value=int(s.value("td_per_minute", 8)), suffix=" dotazů/min")
        self.rate.setToolTip("Limit vašeho tarifu Twelve Data (Basic/zdarma: 8 za minutu). Aplikace ho nepřekročí.")
        form = QFormLayout(self)
        form.addRow("Twelve Data API klíč", self.key)
        for k, edit in self.cutoffs.items():
            form.addRow(f"Večerní limit – {PROFILES[k].name}", edit)
        form.addRow("Min. minut do limitu", self.left)
        form.addRow(self.demo)
        form.addRow(self.watch)
        form.addRow("Interval sledování", self.interval)
        form.addRow(self.motion)
        form.addRow("Limit Twelve Data", self.rate)
        note = QLabel(f"Klíč se ukládá nešifrovaně do {s.fileName()}.\n"
                      "Alternativa: proměnná prostředí TWELVEDATA_API_KEY.", objectName="muted")
        form.addRow(note)
        if probe:
            check = QPushButton(f"Ověřit dostupnost dat – {probe_label}")
            check.setToolTip("Katalog symbolů a 2 svíčky pro 5min/15min/1h u Twelve Data (4–5 dotazů)")
            check.clicked.connect(probe)
            form.addRow(check)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def save(self):
        self.s.setValue("api_key", self.key.text().strip())
        for k, edit in self.cutoffs.items():
            self.s.setValue(f"cutoff/{k}", edit.time().toString("HH:mm"))
        self.s.setValue("min_left", self.left.value())
        self.s.setValue("demo", self.demo.isChecked())
        self.s.setValue("watch", self.watch.isChecked())
        self.s.setValue("watch_interval", self.interval.value())
        self.s.setValue("reduced_motion", self.motion.isChecked())
        self.s.setValue("td_per_minute", self.rate.value())
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
        self._retired: list[QThread] = []           # cancelled / timed-out workers, kept until they finish
        self._gen = 0                                # analysis generation: late results of old runs are ignored
        self._cancel = threading.Event()
        self.analysed: Instrument | None = None     # instrument of the running / last analysis
        self.shown: Instrument | None = None        # instrument of the result on screen (None = no result)
        self.started = datetime.now(timezone.utc)
        self._cache: tuple[tuple, CachedProvider] | None = None   # session candle cache (per API key + limit)
        widgets.REDUCED_MOTION = self.s.value("reduced_motion", widgets.system_reduced_motion(), type=bool)
        self.setWindowTitle(APP)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint)

        self.bar = InstrumentBar(self.s, reader)
        self.bar.changed.connect(self.on_instrument_changed)
        gear = QPushButton("⚙", toolTip="Nastavení")
        gear.setFixedWidth(34)
        gear.clicked.connect(self.settings)
        self.bar.buttons.addWidget(gear)

        self.gauge = Gauge()
        self.gauge.clicked.connect(self.start)
        self.step = QLabel("Připraveno", objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)
        self.step.setFixedHeight(16)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles = {k: Tile(TITLES[k]) for k in MODULES}
        for n, k in enumerate(MODULES):
            grid.addWidget(self.tiles[k], n // 2, n % 2)
        self.result = ResultPanel(WIDTH - 28, 290)

        self.spread = QLineEdit()
        self.spread.setToolTip("Aktuální spread z Trading 212 (rozdíl BUY − SELL) v cenových jednotkách")
        self.spread.editingFinished.connect(self.save_spread)
        sp = QHBoxLayout()
        sp.addWidget(QLabel("Spread z T212:"))
        sp.addWidget(self.spread, 1)
        bt, jr = QPushButton("Backtest"), QPushButton("Demo deník")
        bt.clicked.connect(self.backtest)
        jr.clicked.connect(self.journal)
        sp.addWidget(bt)
        sp.addWidget(jr)
        self.footer = QLabel("", objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 6)
        lay.setSpacing(4)
        lay.addWidget(self.bar)
        lay.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.step)
        lay.addLayout(grid)
        lay.addWidget(self.result)
        lay.addLayout(sp)
        lay.addWidget(self.footer)
        self.refresh_header()
        self.setFixedWidth(WIDTH)
        self.adjustSize()
        self.setFixedSize(self.size())                 # never resizes afterwards: no visible jumping
        if self.bar.mode() == AUTO:
            QTimer.singleShot(300, self.bar.warmup)    # OCR model loads after the window is visible

    # ---- settings helpers ----
    def cfg(self) -> Settings:
        cutoffs = []
        for k, prof in PROFILES.items():
            hh, mm = map(int, str(self.s.value(f"cutoff/{k}", f"{prof.cutoff:%H:%M}")).split(":"))
            cutoffs.append((k, time(hh, mm)))
        return Settings(min_minutes_left=int(self.s.value("min_left", 60)), cutoffs=tuple(cutoffs))

    def demo(self) -> bool:
        return self.s.value("demo", False, type=bool)

    def provider(self):
        """Demo: synthetic data. Live: one Twelve Data client with a candle cache for the whole session (the per-
        minute limit and the cache survive between analyses; a new key or limit starts a fresh client)."""
        if self.demo():
            return SyntheticData()
        key = os.environ.get("TWELVEDATA_API_KEY") or self.s.value("api_key", "")
        ident = (key, int(self.s.value("td_per_minute", 8)))
        if not self._cache or self._cache[0] != ident:
            self._cache = (ident, CachedProvider(TwelveData(key, per_minute=ident[1])))
        return self._cache[1]

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
        inst = self.inst
        probe = self.probe_data if inst and not self.demo() else None
        if SettingsDialog(self.s, self, probe, f"{inst.name} ({inst.symbol})" if inst else "").exec():
            widgets.REDUCED_MOTION = self.s.value("reduced_motion", False, type=bool)
            self.bar.apply_settings()
            self.refresh_header()

    def refresh_header(self):
        text = f"{self.spread_of(self.inst):g}" if self.inst else ""
        if self.spread.text() != text:
            self.spread.setText(text)
        demo = " · <span style='color:#fb923c'>DEMO – syntetická data</span>" if self.demo() else ""
        self.footer.setText(f"v{__version__} · jen analýza, žádné obchody{demo}")

    # ---- instrument changes ----
    def running(self) -> bool:
        return bool(self.task and self.task.isRunning())

    def on_instrument_changed(self, inst: Instrument | None):
        self.refresh_header()
        if self.shown and inst != self.shown:
            self.mark_historical()
        if not self.running():
            self.gauge.show_state(0, "START", "spustit analýzu" if inst else "vyberte instrument", ACCENT)
            if inst and not self.demo():   # local record only - no network request on recognition
                state, text = self.availability().summary(TwelveData.name, inst.symbol)
                self.step.setText(text if state != "neověřeno" else "Data Twelve Data: zatím neověřena")
                self.step.setToolTip(text)

    def mark_historical(self):
        """The instrument changed: the result on screen no longer applies to what Trading 212 shows."""
        old = self.shown
        self.result.mark_historical(f"Instrument se změnil – signál platil jen pro {old.name} ({old.symbol}) "
                                    f"a je historický.")
        for t in self.tiles.values():
            t.set("na", t.value.text(), t.toolTip(), "historické")

    # ---- analysis ----
    def start(self):
        if self.running():
            self.cancel("Analýza zrušena.")
            return
        self.save_spread()
        if self.bar.mode() == AUTO:
            self.step.setText("Čtu instrument z Trading 212…")
        self.bar.confirm_for_start(self.begin)

    def begin(self, inst: Instrument):
        if self.running() or inst != self.inst:
            return
        try:
            provider = self.provider()
        except DataError as e:
            self.step.setText("")
            QMessageBox.warning(self, APP, str(e))
            return
        self.refresh_header()
        spread, cfg = self.spread_of(inst), self.cfg()
        calendar = _NoNews() if self.demo() else Calendar(data_dir() / "calendar.json")
        self.analysed, self.shown = inst, None
        self.bar.remember(inst)
        self.result.clear()
        self._gen += 1
        gen, self._cancel = self._gen, threading.Event()
        cancel = self._cancel
        self.gauge.show_state(0, "0 %", NEXT_STEP["Instrument"], ACCENT, busy=True)
        self.gauge.setToolTip("Kliknutím analýzu zrušíte")
        now = datetime.now(timezone.utc)
        self.started = now
        self.task = Task(lambda p: run_analysis(inst, provider, calendar, spread, now, cfg, p, cancel.is_set))
        self.task.progress.connect(lambda d, t, label, g=gen: self.on_progress(d, t, label, g))
        self.task.done.connect(lambda r, g=gen: self.on_result(r, g))
        self.task.failed.connect(lambda msg, g=gen: self.on_result(
            Result(verdict=ERROR, reasons=[f"technická chyba analýzy: {msg}"], summary=f"technická chyba: {msg}",
                   aborted=True), g))
        self.task.start()
        QTimer.singleShot(ANALYSIS_TIMEOUT_MS, lambda g=gen: self._timeout(g))

    def _timeout(self, gen: int):
        if gen == self._gen and self.running():
            self.cancel("Analýza překročila časový limit (pomalá síť nebo Twelve Data neodpovídá).")

    def cancel(self, why: str):
        """Abandon the running analysis at once; the worker stops after its current request and is ignored."""
        self._cancel.set()
        self._gen += 1
        if self.task:
            self._retired.append(self.task)
            self.task.finished.connect(lambda t=self.task: self._retired.remove(t) if t in self._retired else None)
        self.task = None
        self.analysed = None
        self.gauge.show_state(0, "START", "zrušeno – klikněte znovu", ACCENT)
        self.result.clear("ZRUŠENO")
        self.result.reason.setText(why)
        self.step.setText(why)

    def on_progress(self, done: int, total: int, label: str, gen: int):
        if gen != self._gen:
            return
        pct = 100 * done / total
        key = next((k for k in NEXT_STEP if label.startswith(k)), None)
        waiting = NEXT_STEP.get(key) if key else None
        self.gauge.show_state(pct, f"{round(pct)} %", waiting or "vyhodnocuji…", ACCENT, busy=bool(waiting))
        self.step.setText(f"{done}/{total} · {label}")

    def on_result(self, r: Result, gen: int = -1):
        if gen not in (-1, self._gen):
            return  # result of a cancelled or superseded run
        inst = self.analysed
        if inst is None:
            return
        self.shown = inst
        self.gauge.setToolTip("Spustit analýzu")
        pct = 100 * r.completed / r.total if r.total else 0
        color = VERDICT_COLORS.get(r.verdict, ACCENT)
        sub = {NO_DATA: "nedostatek dat · znovu", ERROR: "technická chyba · znovu"}.get(
            r.verdict, "ukončeno · znovu" if r.aborted else "hotovo · znovu")
        self.gauge.show_state(pct, r.verdict, sub, color)
        took = sum(r.timings.values())
        self.step.setText((f"{r.completed}/{r.total} kroků" if r.total else "")
                          + (f" · {took / 1000:.1f} s" if took else ""))
        for k, t in self.tiles.items():
            m = r.modules.get(k)
            t.set(m.state, m.value, m.note, m.stance) if m else t.set("na", "–", "nevyhodnoceno", "")
        levels = ""
        if r.is_signal:
            e = float(r.entry)
            dist = lambda x: f"{abs(float(x) - e):g} / {abs(float(x) - e) / e:.2%}"  # noqa: E731
            rr = abs(float(r.tp) - e) / abs(e - float(r.sl)) if float(r.sl) != e else 0
            levels = (f"Vstup {r.entry}   R:R 1:{rr:.1f}\nSL {r.sl}  (−{dist(r.sl)})\n"
                      f"TP {r.tp}  (+{dist(r.tp)})")
        data = (f"data do {r.data_time:%H:%M} UTC ({r.data_time.astimezone():%H:%M} místního)" if r.data_time
                else "bez dat")
        stamp = f"{data} · analýza {self.started.astimezone():%H:%M:%S}"
        title = ("DEMO " if self.demo() and r.verdict in (BUY, SELL) else "") + r.verdict
        v = view(r)
        self.result.show_result(r, title, levels, stamp, detail_html(r, inst, self.bar.last_ocr_ms),
                                instrument=f"{inst.name} ({inst.symbol}) · {r.profile or PROFILES[inst.kind].name}",
                                **v)
        if inst != self.inst:  # the instrument changed while the analysis was running
            self.mark_historical()
            return
        if not self.demo():
            av = self.availability()
            for source, symbol, interval, state, detail in r.sources:
                av.record(source, symbol, interval, state, detail)
        if r.is_signal and not self.demo():
            journal_add(data_dir() / "journal.csv", inst.symbol, r.verdict, r.data_time, r.entry, r.sl, r.tp)

    def availability(self) -> Availability:
        return Availability(data_dir() / "availability.json")

    def probe_data(self):
        """Manual availability check of the current instrument at Twelve Data (worker thread, 4-5 requests)."""
        inst = self.inst
        try:
            td = self.provider().provider     # the same client: probe requests count towards the same limit
        except DataError as e:
            QMessageBox.warning(self, APP, str(e))
            return
        dlg = TextDialog(f"Dostupnost dat – {inst.name} ({inst.symbol})", "Ověřit znovu", self)
        dlg.bar.setRange(0, 0)
        av = self.availability()

        def show(rows):
            dlg.bar.setRange(0, 1)
            dlg.bar.setValue(1)
            for check, _status, detail, kind in rows:
                if check.startswith("Svíčky "):
                    av.record(TwelveData.name, inst.symbol, check.split()[1], kind, detail)
            icon = {"ok": "✓", "fail": "✗", "info": "i"}
            lines = [f"Zdroj: Twelve Data · symbol {inst.symbol} · {datetime.now().astimezone():%d.%m.%Y %H:%M}", ""]
            lines += [f"{icon.get(st, '?')} {check}: {detail}" for check, st, detail, _ in rows]
            lines += ["", "Souhrn: " + av.summary(TwelveData.name, inst.symbol)[1],
                      "Text neobsahuje API klíč – můžete ho zkopírovat a poslat k analýze."]
            dlg.text.setPlainText("\n".join(lines))

        def run():
            dlg.btn.setEnabled(False)
            dlg.text.setPlainText("Ověřuji katalog symbolů a svíčky 5min/15min/1h…")
            dlg._task = Task(lambda _: td.probe(inst.symbol))
            dlg._task.done.connect(show)
            dlg._task.failed.connect(lambda m: dlg.text.setPlainText(f"Ověření selhalo: {td.redact(m)}"))
            dlg._task.finished.connect(lambda: dlg.btn.setEnabled(True))
            dlg._task.start()

        dlg.btn.clicked.connect(run)
        run()
        dlg.exec()
        if getattr(dlg, "_task", None):
            dlg._task.wait(60000)

    # ---- shutdown ----
    def closeEvent(self, e):
        """Stop timers, cancel work and let worker threads end (bounded) before the window goes away."""
        self.hide()
        self.bar.shutdown()
        if self.running():
            self.cancel("Ukončování…")
        deadline = datetime.now(timezone.utc).timestamp() + 20
        for t in list(self._retired):
            while t.isRunning() and datetime.now(timezone.utc).timestamp() < deadline:
                t.wait(50)
                QApplication.processEvents()
        e.accept()

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
        dlg = TextDialog(f"Backtest – {inst.name}: v2.1 vs. v2.0 vs. náhodné vstupy", "Spustit backtest", self)
        dlg.text.setPlainText(
            "Výzkumný backtest v2.2 na datech Twelve Data (až 5000 svíček 5m, 3 API dotazy).\n"
            "Vstup na otevření následující svíčky, BUY za ask / SELL za bid (váš spread), skluz 0,1× spreadu,\n"
            "mezera přes SL = horší cena, SL a TP v jedné svíčce = SL, nucené ukončení na časovém limitu.\n"
            "Vývoj 50 % / validace 25 % / závěrečný test 25 %, citlivost parametrů jen na vývoji a validaci.\n"
            "Bez historického filtru zpráv. Krátká historie není statistický důkaz ziskovosti.\n"
            "Delší historii a přesné bid/ask ceny počítá skript scripts/research.py (viz README).")

        def run():
            dlg.btn.setEnabled(False)

            def job(p):
                bars = [provider.bars(inst.symbol, i, HISTORY) for i in ("5min", "15min", "1h")]
                steps = iter(range(1, 100))
                return research(Market(inst, *bars), Costs(spread_floor=spread, slippage=0.1 * spread), cfg,
                                lambda msg: p(next(steps, 99), 9, msg))
            dlg._task = Task(job)
            dlg._task.progress.connect(lambda a, b, msg: (dlg.bar.setMaximum(b), dlg.bar.setValue(min(a, b)),
                                                          dlg.bar.setFormat(msg)))
            dlg._task.done.connect(lambda res: dlg.text.setPlainText(research_text(res)))
            dlg._task.failed.connect(lambda m: dlg.text.setPlainText(f"Backtest selhal: {m}"))
            dlg._task.finished.connect(lambda: dlg.btn.setEnabled(True))
            dlg._task.start()

        dlg.btn.clicked.connect(run)
        dlg.exec()
        if getattr(dlg, "_task", None):
            dlg._task.wait(30000)

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


def detail_html(r: Result, inst: Instrument, ocr_ms: float | None = None) -> str:
    """"Detail analýzy": every reason, every indicator with its role and every safety filter (wrapped lines)."""
    esc = html.escape
    icons = {"ok": "✓", "fail": "✗", "na": "–"}
    c = r.counts
    counts = (f"pro {c['pro']} · proti {c['proti']} · neutrální {c['neutrální']} · nedostupné {c['nedostupné']}"
              f" · nepoužito {c['nepoužito']}" if c else "–")
    parts = [f"<p><b>{esc(r.verdict)}</b> – {esc(inst.name)} ({esc(inst.symbol)}), profil "
             f"{esc(r.profile or PROFILES[inst.kind].name)}, trend 1h: {esc(r.trend)}"
             + (f", strategie {esc(r.strategy)}" if r.strategy else "") + "</p><p><b>Důvody</b><br>"
             + "<br>".join(f"• {esc(x)}" for x in r.reasons) + "</p>", detail_extra(r, ocr_ms),
             f"<p><b>Indikátory</b> ({esc(counts)})<br>"
             + "<br>".join(f"<b>{esc(TITLES[k])}</b> – {esc(m.stance or m.state)} · {esc(m.value)}<br>"
                           f"&nbsp;&nbsp;{esc(m.note)}" for k, m in r.modules.items()) + "</p>",
             "<p><b>Bezpečnostní filtry</b><br>"
             + ("<br>".join(f"{icons.get(st, '?')} <b>{esc(name)}</b>: {esc(detail)}" for name, st, detail in r.filters)
                or "nehodnoceno") + "</p>",
             "<p><b>Zdroje dat</b><br>"
             + ("<br>".join(f"Zdroj dat: {esc(src)} | Symbol: {esc(sym)} | Interval: {esc(iv)} | Stav: "
                            f"{esc(state_text(state))}" + ("" if state == "OK" else f"<br>&nbsp;&nbsp;{esc(detail)}")
                            for src, sym, iv, state, detail in r.sources) or "data nebyla stažena") + "</p>"]
    return "".join(parts)


OPP_TEXT = {"watch": "◆ WATCH", "trigger": "◆ SETUP SPLNĚN", "invalid": "✕ ZANIKLO"}


def view(r: Result) -> dict:
    """What the summary card says besides the verdict: strategy line, "čeká se na", bias and opportunity pills."""
    out = {"strategy": "", "waiting": "", "bias": None, "opportunity": None}
    if r.bias:
        out["bias"] = (r.bias.direction, "Směr trhu (není pokyn k obchodu): "
                       + (f"{r.bias.strength}, " if r.bias.strength else "") + "; ".join(r.bias.parts)
                       + f"\n{st.BIAS_NOTE}")
    o = r.opportunity
    if r.verdict in (BUY, SELL):
        validated = r.strategy != st.NAMES["v21"]
        out["strategy"] = (f"Strategie: {r.strategy} · {r.verdict}"
                           + (" · ověřená strategie" if validated else " · pravidla v2.1"))
    elif o:
        side = {"BUY": "BUY", "SELL": "SELL"}.get(o.direction or "", "?")
        out["strategy"] = f"Strategie: {o.name} · potenciálně {side}" + ("" if o.validated else " · výzkum")
    else:
        out["strategy"] = "Strategie: žádné aktivní nastavení"
    if o:
        rr = f", R:R 1:{o.rr:.1f}" if o.rr else ""
        tip = (f"{o.name}: {o.detail}" + (f" ({o.risk_note})" if o.risk_note else "")
               + f"\nOvěření: {st.RESEARCH_NOTE.get(o.key, '')}")
        if o.state == "watch":
            out["opportunity"] = (OPP_TEXT["watch"], YELLOW, tip)
        elif o.state == "trigger" and r.verdict in (BUY, SELL) and o.validated:
            out["opportunity"] = (f"✓ POTVRZENO {o.direction}", GREEN if o.direction == BUY else RED, tip + rr)
        elif o.state == "trigger":
            out["opportunity"] = (OPP_TEXT["trigger"] + (" · BLOK" if o.blocked else " · VÝZKUM"), YELLOW, tip + rr)
        else:
            out["opportunity"] = (OPP_TEXT["invalid"], SLATE, tip)
    if r.verdict in (BUY, SELL):
        out["waiting"] = ""
    elif r.verdict in (NO_DATA, ERROR):
        out["waiting"] = "Čeká se na: platná a aktuální data" if r.verdict == NO_DATA else \
            "Technická chyba – analýzu spusťte znovu, detail uvádí příčinu."
    elif o and o.state == "watch":
        out["waiting"] = "Čeká se na: " + "; ".join(o.missing)
    elif o and o.state == "trigger":
        out["waiting"] = ("Nastavení splněno, ale " + o.risk_note) if o.blocked else (
            "Nastavení splněno – výzkumná strategie, NENÍ potvrzený signál (v testu po nákladech ztrátová).")
    elif o and o.state == "invalid":
        out["waiting"] = f"Nastavení zaniklo: {o.detail}"
    else:
        failed = [name for name, status, _ in r.filters if status == "fail"]
        out["waiting"] = ("Čeká se na: " + ("jasný trend 1h" if "Trend 1h" in failed else
                                            ", ".join(failed[:3]).lower() if failed else "vhodné nastavení trhu"))
    return out


def detail_extra(r: Result, ocr_ms: float | None) -> str:
    """v2.3 sections of "Detail analýzy": bias, every setup, measured durations."""
    esc = html.escape
    parts = []
    if r.bias:
        b = r.bias
        parts.append(f"<p><b>Market bias: <span style='color:{BIAS_COLORS[b.direction]}'>{esc(b.direction)}</span>"
                     f"</b> (skóre {b.score:+d}{', ' + esc(b.strength) if b.strength else ''}) – popis směru, "
                     "ne pokyn k obchodu<br>" + "<br>".join(f"• {esc(x)}" for x in b.parts)
                     + f"<br><i>{esc(st.BIAS_NOTE)}</i></p>")
    if r.setups:
        rows = []
        for s in r.setups:
            state = {"none": "nic", "watch": "WATCH", "trigger": "splněno", "invalid": "zaniklo"}[s.state]
            status = "ověřená" if s.validated else "výzkum"
            line = f"<b>{esc(s.name)}</b> ({status}) – {state}" + (f", {esc(s.direction)}" if s.direction else "")
            line += f"<br>&nbsp;&nbsp;{esc(s.detail)}"
            if s.missing:
                line += "<br>&nbsp;&nbsp;chybí: " + esc("; ".join(s.missing))
            if s.entry is not None and s.sl is not None and s.tp is not None:
                line += (f"<br>&nbsp;&nbsp;vstup {s.entry:.6g} · SL {s.sl:.6g} · TP {s.tp:.6g} · R:R 1:{s.rr:.1f}")
            if s.risk_note:
                line += f"<br>&nbsp;&nbsp;{esc(s.risk_note)}"
            line += f"<br>&nbsp;&nbsp;<i>Ověření: {esc(st.RESEARCH_NOTE.get(s.key, ''))}</i>"
            rows.append(line)
        parts.append("<p><b>Obchodní nastavení</b><br>" + "<br>".join(rows) + "</p>")
    times = dict(r.timings)
    if ocr_ms is not None:
        times = {"OCR Trading 212": ocr_ms} | times
    if times:
        parts.append("<p><b>Měření</b><br>" + " · ".join(f"{esc(k)} {v:.0f} ms" for k, v in times.items()) + "</p>")
    return "".join(parts)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.show()                       # the window appears at once; OCR model and data load in the background
    code = app.exec()
    if any(t.isRunning() for t in w.findChildren(QThread)) or w._retired:
        os._exit(code)             # a worker still blocked in a network call must not crash interpreter shutdown
    sys.exit(code)

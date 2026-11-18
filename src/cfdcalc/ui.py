"""PySide6 window. The app only shows analysis; it has no code path that sends orders anywhere.

Responsiveness: OCR, network and model loading run in worker threads; the window has a fixed size (no layout
jumps); widgets repaint only when their content changes; animations interpolate real values only.
"""
from __future__ import annotations

import html
import os
import sys
import threading
import time as clock
from datetime import datetime, time, timezone
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt, QThread, QTime, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QStackedWidget, QTabWidget, QTextBrowser,
                               QTimeEdit, QVBoxLayout, QWidget)

from . import __version__, m15, widgets
from . import strategies as st
from .analysis import BUY, ERROR, MODULES, NO_DATA, PROFILES, SELL, TITLES, Result, Settings, run_analysis
from .backtest import HISTORY, journal_add, journal_read, journal_verify
from .engine import Costs, Market
from .report import research_text
from .validation import research
from .availability import Availability, state_text
from .calendar import Calendar
from .data import CachedProvider, Coinbase, DataError, SyntheticData, TwelveData
from .instruments import COINBASE, PLANS, TWELVE
from .ui_markets import MarketsDialog, load_custom
from .instruments import BY_SYMBOL, Instrument
from . import risk
from .ui_instrument import AUTO, InstrumentBar
from .ui_risk import PortfolioPage, RiskPage, manual_fx, plan_from_m15
from .widgets import (ACCENT, BIAS_COLORS, DIRECTION_COLORS, GREEN, RED, SLATE, YELLOW, Gauge, ResultPanel,
                      Tile, tint)

APP = "CFD Signal Calculator"
WIDTH = 380
REFRESH_MS = 60_000             # periodic refresh of the shown result (the candle cache keeps it cheap)
ANALYSIS_TIMEOUT_MS = 75_000    # 3 requests x 15 s + calendar 15 s + margin; then the analysis is abandoned
M15_TIMEOUT_MS = 25_000         # v2.8 main button: one 15min request (15 s timeout) + a fallback source
BACKGROUND_MS = 15_000          # v2.8: check every 15 s whether a new 15m bar closed (then ONE request)
CALENDAR_MS = 3_600_000         # economic calendar reloaded hourly in the background
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
QPushButton#big { font-size: 46px; font-weight: 800; border-radius: 22px; }
QLabel#level { font-size: 22px; font-weight: 700; font-family: Consolas, 'Segoe UI', monospace; background: transparent;
  color: #e5e7eb; padding-left: 8px; }
QPushButton#nav { padding: 2px 10px; font-size: 11px; }
QLabel#value { color: #e5e7eb; font-size: 10px; font-weight: 600; background: transparent; }
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
        self.refresh = QCheckBox("Průběžně obnovovat výsledek (každou minutu, z cache svíček)")
        self.refresh.setChecked(s.value("auto_refresh", False, type=bool))
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
        form.addRow(self.refresh)
        form.addRow(self.motion)
        form.addRow("Limit Twelve Data", self.rate)
        self.plan = QComboBox()
        self.plan.addItems(PLANS)
        self.plan.setCurrentText(str(s.value("td_plan", "Basic")))
        self.plan.setToolTip("Váš tarif Twelve Data. Instrumenty vyšších tarifů se nestahují (žádné zbytečné dotazy "
                             "a chyby) a použije se ověřený referenční zdroj, pokud existuje.")
        form.addRow("Tarif Twelve Data", self.plan)
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
        self.s.setValue("auto_refresh", self.refresh.isChecked())
        self.s.setValue("td_per_minute", self.rate.value())
        self.s.setValue("td_plan", self.plan.currentText())
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

        self.custom_problems = load_custom(self.s)    # user's instruments must exist before recognition starts
        self.bar = InstrumentBar(self.s, reader)
        self.bar.changed.connect(self.on_instrument_changed)
        gear = QPushButton("⚙", toolTip="Nastavení")
        gear.setFixedWidth(34)
        gear.clicked.connect(self.settings)
        self.bar.buttons.addWidget(gear)

        self.gauge = Gauge()
        self.gauge.clicked.connect(self.start)
        self.step = QLabel("Připraveno", objectName="muted", alignment=Qt.AlignmentFlag.AlignLeft |
                           Qt.AlignmentFlag.AlignVCenter)
        self.go = QPushButton("▶ START")
        self.go.setToolTip("Spustit / obnovit analýzu (totéž jako klik do kruhu)")
        self.go.setStyleSheet("padding: 2px 10px; font-weight: 700;")
        self.go.clicked.connect(self.start)
        self.latencies: list[float] = []         # main START click -> M15 result shown, seconds (this session)
        self.hist_latencies: list[float] = []    # historical mode (details page) START -> result
        self._t_hist: float | None = None
        self._t_click: float | None = None
        self.last_results: dict[str, tuple] = {}  # symbol -> (view, shown at, data time): instant previous result
        self.last_levels: dict = {}               # symbol -> analysis.Levels of the last result
        self._refresh = QTimer(self, singleShot=True)
        self._refresh.timeout.connect(self._auto_refresh)
        self.step.setFixedHeight(16)
        grid = QGridLayout()
        grid.setSpacing(6)
        self.tiles = {k: Tile(TITLES[k]) for k in MODULES}
        for n, k in enumerate(MODULES):
            grid.addWidget(self.tiles[k], n // 2, n % 2)
        self.result = ResultPanel(WIDTH - 28, 302)
        self.fx_cache: dict[tuple[str, str], risk.Fx] = {}      # rates fetched from Twelve Data this session
        self._fx_failed: dict[tuple[str, str], datetime] = {}
        self._levels = ""
        self.risk_page = RiskPage(self.s, self.spread_of, self.fx_for)
        self.risk_page.summary.connect(self.on_risk_summary)
        self.risk_page.needs_fx.connect(self.fetch_fx)
        self.portfolio = PortfolioPage(self.s, self.risk_page)
        # ---- v2.8 M15 signal of the main screen (the historical multi-timeframe analysis never touches it) ----
        self.m15 = m15.Service(m15.Feed(lambda: self.providers(), lambda: datetime.now(timezone.utc)))
        self.m15_task: Task | None = None
        self.m15_bg: Task | None = None
        self._m15_gen = 0
        self.m15_last: dict[str, m15.Signal] = {}     # symbol -> last M15 signal (never shown for another symbol)
        self.shown_m15: Instrument | None = None     # instrument of the M15 result on the main screen
        self.latency_kinds: list[str] = []           # "cache" | "síť" for every entry of self.latencies
        self._bg = QTimer(self)
        self._bg.timeout.connect(self.background)
        self._cal = QTimer(self)
        self._cal.timeout.connect(self.load_calendar)

        self.spread = QLineEdit()
        self.spread.setToolTip("Aktuální spread z Trading 212 (rozdíl BUY − SELL) v cenových jednotkách")
        self.spread.editingFinished.connect(self.save_spread)
        sp = QHBoxLayout()
        sp.addWidget(QLabel("Spread z T212:"))
        sp.addWidget(self.spread, 1)
        bt, jr, mk = QPushButton("Backtest"), QPushButton("Deník"), QPushButton("Trhy")
        mk.setToolTip("Dostupnost tržních dat pro všechny instrumenty, přidání instrumentu")
        mk.clicked.connect(self.markets)
        bt.clicked.connect(self.backtest)
        jr.clicked.connect(self.journal)
        sp.addWidget(bt)
        sp.addWidget(jr)
        sp.addWidget(mk)
        self.footer = QLabel("", objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)

        # ---- main screen (v2.6.1): one big START / BUY / SELL button and VSTUP, TP, SL - nothing else ----
        self.big = QPushButton("START", objectName="big")
        self.big.setFixedHeight(170)
        self.big.setCursor(Qt.CursorShape.PointingHandCursor)
        self.big.clicked.connect(self.analyze)
        self.entry_lbl, self.tp_lbl, self.sl_lbl, self.pos_lbl = (QLabel("", objectName="level") for _ in range(4))
        self.info = QLabel("", objectName="muted", alignment=Qt.AlignmentFlag.AlignCenter)
        self.info.setFixedHeight(16)
        self.to_details = QPushButton("Podrobnosti ▸", objectName="nav")
        self.to_details.setToolTip("Důvody signálu M15, dostupnost dat, diagnostika, historický režim, spread, "
                                   "backtest, deník, trhy")
        self.to_portfolio = QPushButton("Portfolio a riziko ▸", objectName="nav")
        self.to_portfolio.setToolTip("Hodnota portfolia, měna, riziko na obchod, specifikace CFD, velikost pozice")
        main = QWidget(objectName="page")
        ml = QVBoxLayout(main)
        ml.setContentsMargins(6, 16, 6, 6)
        ml.setSpacing(8)
        ml.addStretch(1)
        ml.addWidget(self.big)
        ml.addSpacing(14)
        for lab in (self.entry_lbl, self.tp_lbl, self.sl_lbl, self.pos_lbl):
            ml.addWidget(lab)
        ml.addSpacing(6)
        ml.addWidget(self.info)
        ml.addStretch(2)
        nav = QHBoxLayout()
        nav.addWidget(self.to_portfolio)
        nav.addStretch(1)
        nav.addWidget(self.to_details)
        ml.addLayout(nav)
        # ---- details page: everything that was on the main screen before ----
        details = QWidget(objectName="page")
        dl = QVBoxLayout(details)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        back = QPushButton("◂ Zpět", objectName="nav")
        self.m15_text = QTextBrowser()
        self.m15_text.setStyleSheet("background: transparent; border: none; font-size: 11px;")
        self.m15_text.setHtml("<p>Klikněte START na hlavní obrazovce.</p>")
        hist = QWidget(objectName="page")
        hl = QVBoxLayout(hist)
        hl.setContentsMargins(0, 4, 0, 0)
        hl.setSpacing(4)
        hl.addWidget(self.gauge, alignment=Qt.AlignmentFlag.AlignHCenter)
        steprow = QHBoxLayout()
        steprow.addWidget(self.step, 1)
        steprow.addWidget(self.go)
        hl.addLayout(steprow)
        hl.addLayout(grid)
        hl.addWidget(self.result)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.m15_text, "Signál M15")
        self.tabs.addTab(hist, "Historický režim 5m/15m/1h")
        self.tabs.setTabToolTip(1, "Starší vícetimeframová analýza (v2.1–v2.6). Hlavní obrazovku NEOVLIVŇUJE.")
        dl.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        dl.addWidget(self.tabs, 1)
        dl.addLayout(sp)
        dl.addWidget(self.footer)
        self.pages = QStackedWidget(objectName="pages")
        self.pages.addWidget(main)
        self.pages.addWidget(details)
        self.pages.addWidget(self.portfolio)
        self.to_details.clicked.connect(lambda: self.pages.setCurrentIndex(1))
        self.to_portfolio.clicked.connect(lambda: self.pages.setCurrentIndex(2))
        back.clicked.connect(lambda: self.pages.setCurrentIndex(0))
        self.risk_page.back.setText("◂ Hlavní obrazovka")
        self.risk_page.back.clicked.connect(lambda: self.pages.setCurrentIndex(0))

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 6)
        lay.setSpacing(4)
        lay.addWidget(self.bar)
        lay.addWidget(self.pages, 1)
        self.show_main(START, None)
        self.refresh_header()
        self.risk_page.load(self.inst, None)
        self.setFixedWidth(WIDTH)
        self.adjustSize()
        self.setFixedSize(self.size())                 # never resizes afterwards: no visible jumping
        if self.bar.mode() == AUTO:
            QTimer.singleShot(300, self.bar.warmup)    # OCR model loads after the window is visible
        self._bg.start(BACKGROUND_MS)
        self._cal.start(CALENDAR_MS)
        QTimer.singleShot(500, self.load_calendar)
        QTimer.singleShot(800, self.background)        # first 15m data of the confirmed instrument

    # ---- settings helpers ----
    def cfg(self) -> Settings:
        cutoffs = []
        for k, prof in PROFILES.items():
            hh, mm = map(int, str(self.s.value(f"cutoff/{k}", f"{prof.cutoff:%H:%M}")).split(":"))
            cutoffs.append((k, time(hh, mm)))
        return Settings(min_minutes_left=int(self.s.value("min_left", 60)), cutoffs=tuple(cutoffs),
                        td_plan=str(self.s.value("td_plan", "Basic")))

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

    def providers(self):
        """Every data source of the live mode: {provider: cached client}; demo: the synthetic source."""
        td = self.provider()
        if isinstance(td, SyntheticData):
            return td
        if not getattr(self, "_coinbase", None):
            self._coinbase = CachedProvider(Coinbase())
        return {TWELVE: td, COINBASE: self._coinbase}

    def markets(self):
        try:
            td = self.provider()
            search = td.provider.search if isinstance(td, CachedProvider) else None
            usage = td.provider.usage() if isinstance(td, CachedProvider) else "demo – bez API"
        except DataError:
            search, usage = None, "bez API klíče – přidávání instrumentů není dostupné"
        note = ("\nPřeskočené vlastní instrumenty: " + "; ".join(self.custom_problems)) if self.custom_problems else ""
        dlg = MarketsDialog(self.s, str(self.s.value("td_plan", "Basic")), self.availability(), usage + note, search,
                            self)
        dlg.exec()
        self.bar.refresh_catalog()

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
            self.risk_page.recompute()

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
        if inst != self.shown_m15:                   # v2.8: old prices and position are dropped at once
            self.shown_m15 = None
            self.show_main(START, None)
            self.info.setText("" if inst else "Instrument nerozpoznán – vyberte ho ručně (hledání nahoře)")
            self.m15_text.setHtml("<p>Klikněte START na hlavní obrazovce.</p>")
            QTimer.singleShot(0, self.background)    # first data of the new instrument in the background
        if self.shown and inst != self.shown:
            self.mark_historical()
        elif inst != self.risk_page.inst:
            self.risk_page.load(inst, None)
        if not self.running():
            self.gauge.show_state(0, "START", "spustit analýzu" if inst else "vyberte instrument", ACCENT)
            if inst and not self.demo():   # local record only - no network request on recognition
                state, text = self.availability().summary(TwelveData.name, inst.symbol)
                self.step.setText(text if state != "neověřeno" else "Data Twelve Data: zatím neověřena")
                self.step.setToolTip(text)

    def mark_historical(self):
        """The instrument changed: the result on screen no longer applies to what Trading 212 shows."""
        old = self.shown
        self._refresh.stop()
        self.risk_page.load(self.inst, None)     # an old signal is never sized for the new instrument
        self.result.mark_historical(f"Instrument se změnil – signál platil jen pro {old.name} ({old.symbol}) "
                                    f"a je historický.")
        for t in self.tiles.values():
            t.set("na", t.value.text(), t.toolTip(), "historické")

    # ---- main screen ----
    def analyze(self):
        """The big button (v2.8): M15 analysis. START, or a repeat from a shown BUY / SELL / NEUTRAL / NO DATA /
        ERROR. A click while one runs is ignored (no duplicate, no cancel); the timeout ends a hung request."""
        if self.m15_busy():
            return
        self._t_click = clock.perf_counter()
        self.save_spread()
        if self.bar.mode() == AUTO:
            self.info.setText("Čtu instrument z Trading 212…")
        self.bar.confirm_for_start(self.m15_begin)

    def m15_busy(self) -> bool:
        return bool(self.m15_task and self.m15_task.isRunning())

    def m15_begin(self, inst: Instrument):
        if self.m15_busy() or inst != self.inst:
            return
        self.bar.remember(inst)
        spread, cfg = self.spread_of(inst), self.cfg()
        sig = self.m15.analyze_cached(inst, spread, cfg)
        if sig is not None:                          # nothing new can be obtained: answer at once
            self._m15_gen += 1
            self.on_m15(sig, inst, self._m15_gen)
            return
        prev = self.m15_last.get(inst.symbol) if self.shown_m15 == inst else None
        self.show_main("ANALYZUJI…", prev if prev and prev.levels_ok else None, dim=True)
        self.info.setText("Načítám M15 data…")
        self._m15_gen += 1
        gen = self._m15_gen
        task = Task(lambda _: self.m15.analyze(inst, spread, cfg))
        task.done.connect(lambda r, g=gen, i=inst: self.on_m15(r, i, g))
        task.failed.connect(lambda msg, g=gen, i=inst: self.on_m15(
            m15.Signal(symbol=i.symbol, summary=f"technická chyba: {msg}", note="technická chyba"), i, g, error=True))
        self.m15_task = task
        task.start()
        QTimer.singleShot(M15_TIMEOUT_MS, lambda g=gen: self._m15_timeout(g))

    def _m15_timeout(self, gen: int):
        if gen != self._m15_gen or not self.m15_busy():
            return
        task, self.m15_task = self.m15_task, None
        self._retire(task)
        self._m15_gen += 1                                       # its late result is ignored
        self._t_click = None
        self.show_main(NO_DATA, None)
        self.info.setText(f"Poskytovatel dat neodpověděl do {M15_TIMEOUT_MS // 1000} s – klikněte znovu")

    def _retire(self, task: QThread):
        """Keep a worker referenced until it has really finished (a QThread must never be destroyed running)."""
        self._retired.append(task)
        task.finished.connect(lambda t=task: self._retired.remove(t) if t in self._retired else None)
        if task.isFinished():
            self._retired.remove(task)

    def on_m15(self, sig: m15.Signal, inst: Instrument, gen: int, error: bool = False):
        if gen != self._m15_gen:
            return                                               # superseded or timed out
        if self.m15_task is not None:
            self._retire(self.m15_task)
            self.m15_task = None
        self.m15_last[inst.symbol] = sig
        if inst != self.inst:                                    # the instrument changed meanwhile: not shown
            return
        latency = (clock.perf_counter() - self._t_click) if self._t_click else None
        if latency is not None:
            self.latencies.append(latency)
            self.latency_kinds.append("cache" if sig.from_cache else "síť")
            self._t_click = None
        self.shown_m15 = inst
        state = ERROR if error else sig.side
        self.show_main(state, sig if sig.levels_ok else None)
        plan, note = plan_from_m15(sig)
        self.risk_page.load_plan(inst, plan, note)               # POZICE follows via on_risk_summary
        self.info.setText(m15_info(sig, state, latency))
        self.info.setToolTip(sig.summary)
        self.m15_text.setHtml(m15_detail_html(sig, inst, self.m15.report(inst, self.cfg(), self.has_key(),
                                                                          self.usage()), latency,
                                              self.bar.last_ocr_ms, self.latencies, self.latency_kinds))
        if sig.levels_ok and not self.demo() and not sig.from_cache:
            journal_add(data_dir() / "journal.csv", inst.symbol, sig.side, sig.data_time, sig.entry, sig.sl, sig.tp)

    def has_key(self) -> bool:
        return bool(os.environ.get("TWELVEDATA_API_KEY") or self.s.value("api_key", ""))

    def usage(self) -> str:
        try:
            td = self.provider()
            return td.provider.usage() if isinstance(td, CachedProvider) else "demo – bez API"
        except DataError:
            return ""

    def background(self):
        """v2.8: keep the 15m series of the confirmed instrument current - ONE request only when a new 15m bar has
        closed (or nothing is cached yet). Never while a click is being answered, never twice at once."""
        inst = self.inst
        if inst is None or self.m15_busy() or (self.m15_bg and self.m15_bg.isRunning()) or not self.isVisible() \
                or not self.s.value("m15_background", True, type=bool):
            return
        cfg = self.cfg()
        feed = self.m15.feed
        if feed.need(feed.cached(inst, cfg.td_plan), feed.clock(), False) is None:
            return
        task = Task(lambda _: feed.get(inst, cfg.td_plan, want_price=False))
        if self.m15_bg is not None:
            self._retire(self.m15_bg)
        self.m15_bg = task
        task.start()

    def load_calendar(self):
        """Economic calendar in the background (file cache 1 h); the M15 entry check needs it."""
        if self.demo():
            self.m15.set_events([])
            return
        cal = Calendar(data_dir() / "calendar.json")
        task = Task(lambda _: cal.events())
        task.done.connect(lambda ev: self.m15.set_events(ev))
        task.failed.connect(lambda msg: self.m15.set_events(None, f"kalendář zpráv nedostupný ({msg[:60]})"))
        self._retire(task)
        task.start()

    def position_text(self) -> str:
        """POZICE of the main screen from the v2.4 risk calculation (RiskPage), in CFD quantity units."""
        sig = self.m15_last.get(self.shown_m15.symbol) if self.shown_m15 else None
        out = self.risk_page.last
        if sig is None or not sig.levels_ok or out is None or self.risk_page.inst != self.shown_m15:
            return "–"
        if out.qty is not None:
            return f"{risk.fmt_qty(out.qty)} ks" + ("" if out.state == risk.OK else " (orientačně)")
        if out.state == risk.LIMIT:
            return out.headline
        return "NELZE SPOČÍTAT"

    def show_main(self, state: str, levels, dim: bool = False):
        """state: START | ANALYZUJI… | BUY | SELL | NEUTRAL | NO DATA | ERROR; levels: object with entry/tp/sl or
        None (an M15 signal only when its entry is confirmed)."""
        color = {BUY: GREEN, SELL: RED, NEUTRAL: YELLOW, NO_DATA: SLATE, ERROR: RED}.get(state, ACCENT)
        dashed = "dashed" if state == ERROR else "solid"
        self.big.setText(state)
        size = 46 if len(state) <= 7 else 34
        self.big.setStyleSheet(f"QPushButton#big {{ font-size: {size}px; background: {tint(color, 46)}; "
                               f"color: {color}; "
                               f"border: 2px {dashed} {color}; }} QPushButton#big:hover {{ background: "
                               f"{tint(color, 70)}; }}")
        values = [getattr(levels, k, None) if levels else None for k in ("entry", "tp", "sl")]
        for lab, name, v in zip((self.entry_lbl, self.tp_lbl, self.sl_lbl), ("VSTUP", "TP", "SL"), values,
                                strict=True):
            lab.setText(f"{name}: {v if v is not None else '–'}")
            lab.setStyleSheet("color: #64748b;" if dim else "")
        self.pos_lbl.setText(f"POZICE: {self.position_text() if levels is not None and not dim else '–'}")
        self.pos_lbl.setStyleSheet("color: #64748b;" if dim else "")
        tip = ""
        if levels and levels.entry is not None:
            when = levels.price_time.astimezone() if levels.price_time else None
            tip = (f"Aktuální cena získaná {when:%H:%M:%S}" if levels.live and when else
                   f"Cena poslední uzavřené 15m svíčky ({when:%H:%M})" if when else "") + f". {levels.note}"
        elif levels:
            tip = levels.note
        self.entry_lbl.setToolTip(tip)
        self.big.setToolTip("Kliknutím spustíte novou analýzu" if state != "ANALYZUJI…" else "Probíhá analýza…")

    # ---- analysis ----
    def start(self):
        if self.running():
            self.cancel("Analýza zrušena.")
            return
        self._refresh.stop()
        self._t_hist = clock.perf_counter()
        self.go.setText("■ ZRUŠIT")
        self.save_spread()
        if self.bar.mode() == AUTO:
            self.step.setText("Čtu instrument z Trading 212…")
        self.bar.confirm_for_start(self.begin)

    def begin(self, inst: Instrument):
        if self.running() or inst != self.inst:
            return
        try:
            provider = self.providers()
        except DataError as e:
            self.step.setText("")
            QMessageBox.warning(self, APP, str(e))
            return
        self.refresh_header()
        spread, cfg = self.spread_of(inst), self.cfg()
        calendar = _NoNews() if self.demo() else Calendar(data_dir() / "calendar.json")
        self.analysed, self.shown = inst, None
        self.bar.remember(inst)
        self._levels = ""
        cached = self.last_results.get(inst.symbol)
        if cached:          # instant answer: the previous result, clearly marked, while fresh data load
            v, when, data_time = cached
            self.result.display(v)
            age = f"data do {data_time.astimezone():%H:%M}" if data_time else "bez dat"
            self.result.mark_stale(f"PŘEDCHOZÍ VÝSLEDEK z {when.astimezone():%H:%M:%S} ({age}) – aktualizuji data…")
        else:
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

    def _auto_refresh(self):
        """Periodic refresh of the shown instrument (cache keeps API use low); never while busy or after a change."""
        if not self.running() and self.shown and self.shown == self.inst and self.isVisible():
            self.start()

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
        self.go.setText("▶ START")
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
        side = main_side(r)
        pct = 100 * r.completed / r.total if r.total else 0
        if r.market and side in (BUY, SELL, NEUTRAL):
            pct, sub = r.market.strength, f"převaha {r.market.strength}/100"
        else:
            sub = {NO_DATA: "nedostatek dat", ERROR: "technická chyba"}.get(side, "hotovo")
        self.gauge.show_state(pct, side, sub, DIRECTION_COLORS.get(side, ACCENT))
        self.go.setText("⟳ REFRESH")
        latency = (clock.perf_counter() - self._t_hist) if self._t_hist else None
        if latency is not None:
            self.hist_latencies.append(latency)
            self._t_hist = None
        took = sum(r.timings.values())
        self.step.setText((f"{r.completed}/{r.total} kroků" if r.total else "")
                          + (f" · výsledek za {latency:.2f} s" if latency is not None else
                             f" · {took / 1000:.1f} s" if took else ""))
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
        src = next((s_[0] for s_ in r.sources if s_[3] == "OK"), "")
        data = (f"AKTUÁLNÍ data do {r.data_time:%H:%M} UTC ({r.data_time.astimezone():%H:%M} místního)"
                if r.data_time else "bez platných dat")
        demo = " · DEMO (syntetická data)" if self.demo() else ""
        stamp = f"{data}{' · ' + src if src else ''}{demo} · analýza {self.started.astimezone():%H:%M:%S}"
        v = view(r, inst, levels=levels, stamp=stamp, detail=detail_html(r, inst, self.bar.last_ocr_ms))
        self.result.display(v)
        self.last_results[inst.symbol] = (v, datetime.now(timezone.utc), r.data_time)
        self.last_levels[inst.symbol] = r.levels
        if self.s.value("auto_refresh", False, type=bool) and side != ERROR and inst == self.inst:
            self._refresh.start(REFRESH_MS)
        self._levels = levels
        if inst != self.inst:  # the instrument changed while the analysis was running
            self.mark_historical()
            return
        if not self.demo():
            av = self.availability()
            for source, symbol, interval, state, detail in r.sources:
                av.record(source, symbol, interval, state, detail)
        if r.is_signal and not self.demo():
            journal_add(data_dir() / "journal.csv", inst.symbol, r.verdict, r.data_time, r.entry, r.sl, r.tp)

    # ---- risk management ----
    def on_risk_summary(self, _line: str = ""):
        """v2.8: the risk page recomputed (account, spec, FX rate arrived): refresh POZICE on the main screen."""
        if self.shown_m15 is not None and not self.m15_busy():
            sig = self.m15_last.get(self.shown_m15.symbol)
            self.pos_lbl.setText(f"POZICE: {self.position_text() if sig and sig.levels_ok else '–'}")

    def fx_for(self, quote: str, acc: str) -> risk.Fx | None:
        """Rate quote -> account currency: the same currency, a fresh Twelve Data rate, or the user's manual rate.
        Returns the best one available (size() then decides whether it is recent enough)."""
        now = datetime.now(timezone.utc)
        if quote == acc:
            return risk.Fx(risk.Decimal(1), now, "stejná měna")
        fetched, manual = self.fx_cache.get((quote, acc)), manual_fx(self.s, quote, acc)
        if fetched and now - fetched.time <= risk.MAX_FX_AGE:
            return fetched
        if manual and now - manual.time <= risk.MAX_MANUAL_FX_AGE:
            return manual
        return fetched or manual

    def fetch_fx(self, quote: str, acc: str):
        """Fetch a missing rate in the background (live mode only, one request, retried at most every 5 min)."""
        pair, now = (quote, acc), datetime.now(timezone.utc)
        failed = self._fx_failed.get(pair)
        if self.demo() or pair in self._fx_failed and failed and (now - failed).total_seconds() < 300:
            return
        try:
            td = self.provider().provider
        except (DataError, AttributeError):
            return
        self._fx_failed[pair] = now          # also marks "in progress"; cleared on success
        task = Task(lambda _: td.exchange_rate(quote, acc))

        def done(res):
            rate, when = res
            self.fx_cache[pair] = risk.Fx(rate, when, "Twelve Data")
            self._fx_failed.pop(pair, None)
            self.risk_page.recompute()
        task.done.connect(done)
        task.failed.connect(lambda msg: self.step.setText(f"Kurz {quote}→{acc}: {td.redact(msg)[:80]}"))
        self._retired.append(task)
        task.finished.connect(lambda t=task: self._retired.remove(t) if t in self._retired else None)
        task.start()

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
        self._bg.stop()
        self._cal.stop()
        self.bar.shutdown()
        for t in (self.m15_task, self.m15_bg):
            if t and t.isRunning():
                self._retired.append(t)
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


def m15_info(sig: m15.Signal, state: str, latency: float | None) -> str:
    """One muted line under the main values: what the shown result is based on (time of data and price)."""
    if state == ERROR:
        return "Technická chyba – klikněte znovu (detail v Podrobnostech)"
    parts = []
    if sig.data_time:
        parts.append(f"M15 svíčka {sig.data_time.astimezone():%H:%M}")
    if sig.price_time and sig.live:
        parts.append(f"cena {sig.price_time.astimezone():%H:%M:%S}")
    if sig.side in (BUY, SELL) and not sig.levels_ok:
        parts.append("jen směr – vstup nepotvrzen")
    elif sig.side in (NO_DATA, NEUTRAL) and sig.note:
        parts.append(sig.note[:60])
    if sig.reference:
        parts.append("REFERENČNÍ data")
    if latency is not None:
        parts.append(f"{latency:.2f} s" + (" z cache" if sig.from_cache else ""))
    return " · ".join(parts)


def m15_detail_html(sig: m15.Signal, inst: Instrument, report: list[str], latency: float | None,
                    ocr_ms: float | None, latencies: list[float], kinds: list[str]) -> str:
    """Detail page of the M15 signal: decision, votes, entry checks, data diagnostics, timings."""
    e = html.escape
    rows = [f"<h3>{e(inst.name)} ({e(inst.symbol)}) – {e(sig.side)}"
            f"{' · POTVRZENÝ VSTUP' if sig.levels_ok else ''}</h3>",
            f"<p><b>{e(sig.summary)}</b></p>"]
    if sig.side in (BUY, SELL) and not sig.levels_ok:
        rows.append("<p>BUY/SELL zde označuje <b>převažující směr trhu na M15</b>. Vstup nesplňuje podmínky, proto "
                    "aplikace nezobrazuje VSTUP, TP, SL ani pozici – <b>nejde o obchodní pokyn</b>.</p>")
    if sig.reference:
        rows.append(f"<p style='color:#fb923c'><b>REFERENČNÍ TRŽNÍ DATA</b> – "
                    f"{e(sig.reference)}. Cena jiného produktu není cena CFD v Trading 212.</p>")
    if sig.levels_ok:
        rr = abs(sig.tp - sig.entry) / abs(sig.entry - sig.sl)
        rows.append(f"<p>VSTUP {sig.entry} · SL {sig.sl} ({m15.SL_ATR:g}× ATR14 M15) · TP {sig.tp} "
                    f"(R:R 1:{rr:.1f}). Podkladová cena se může lišit od ceny CFD v Trading 212 – zkontrolujte "
                    "vstup v platformě.</p>")
    if sig.factors:
        rows.append(f"<p><b>Směr z uzavřených 15m svíček</b> – skóre {sig.score:+.2f} (hranice ±{m15.THRESHOLD}), "
                    f"dostupnost indikátorů {sig.quality:.0%}</p><table>")
        for f in sig.factors:
            v = {1: "BUY", -1: "SELL", 0: "neutrální", None: "nedostupné"}[f.vote]
            rows.append(f"<tr><td>{e(f.name)}</td><td>{v}</td><td>váha {f.weight:g}</td><td>{e(f.detail)}</td></tr>")
        rows.append("</table>")
    if sig.checks:
        rows.append("<p><b>Podmínky vstupu</b></p><table>")
        for name, ok, detail in sig.checks:
            rows.append(f"<tr><td>{'✓' if ok else '✗'}</td><td>{e(name)}</td><td>{e(detail)}</td></tr>")
        rows.append("</table>")
    v = sig.values
    if v:
        def f(x):
            return "–" if x is None else f"{x:.6g}"
        rows.append(f"<p><b>Indikátory M15</b>: EMA20 {f(v.get('ema20'))}, EMA50 {f(v.get('ema50'))}, "
                    f"EMA200 {f(v.get('ema200'))}, RSI14 {f(v.get('rsi'))}, MACD {f(v.get('macd'))} / signál "
                    f"{f(v.get('macd_signal'))}, ATR14 {f(v.get('atr'))}</p>")
    data = [f"Zdroj: {e(sig.source or '–')}", f"uzavřených svíček M15: {sig.bars}"]
    if sig.data_time:
        data.append(f"poslední uzavřená svíčka do {sig.data_time.astimezone():%d.%m. %H:%M}")
    if sig.price_time:
        data.append(f"cena {'z aktuální svíčky' if sig.live else 'z uzavřené svíčky'} "
                    f"{sig.price_time.astimezone():%H:%M:%S}")
    if sig.fetched:
        data.append(f"staženo {sig.fetched.astimezone():%H:%M:%S}" + (" (z cache, bez dotazu)" if sig.from_cache
                                                                       else ""))
    rows.append("<p><b>Data</b>: " + " · ".join(data) + "</p>")
    for err in sig.errors:
        rows.append(f"<p style='color:#fca5a5'>{e(err)}</p>")
    rows.append("<p><b>Diagnostika dat</b></p><ul>" + "".join(f"<li>{e(x)}</li>" for x in report) + "</ul>")
    t = sig.timings
    timing = [f"data {t.get('data', 0):.0f} ms", f"výpočet {t.get('výpočet', 0):.1f} ms"]
    if latency is not None:
        timing.insert(0, f"klik → výsledek {latency * 1000:.0f} ms")
    if ocr_ms is not None:
        timing.append(f"čtení Trading 212 {ocr_ms:.0f} ms")
    rows.append("<p><b>Měření</b>: " + " · ".join(timing) + "</p>")
    for kind in ("cache", "síť"):
        xs = sorted(x for x, k in zip(latencies, kinds, strict=False) if k == kind)
        if xs:
            p95 = xs[max(0, int(round(0.95 * len(xs))) - 1)]
            rows.append(f"<p>Odezva v této relaci ({kind}): medián {xs[len(xs) // 2] * 1000:.0f} ms, p95 "
                        f"{p95 * 1000:.0f} ms, n={len(xs)}</p>")
    rows.append("<p style='color:#94a3b8'>Jen analýza – aplikace neodesílá žádné pokyny. Při skluzu nebo gapu může "
                "být ztráta vyšší než plánovaná.</p>")
    return "".join(rows)


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
NEUTRAL = "NEUTRAL"
START = "START"


def main_side(r: Result) -> str:
    """The big answer: MARKET DIRECTION (BUY / SELL / NEUTRAL), or NO DATA / ERROR when it cannot be determined."""
    if r.verdict == ERROR and not r.market:
        return ERROR
    if r.market and r.market.side in (BUY, SELL, NEUTRAL, NO_DATA, ERROR):
        return r.market.side
    return r.verdict if r.verdict in (BUY, SELL, NO_DATA, ERROR) else NEUTRAL


def view(r: Result, inst: Instrument | None = None, *, levels: str = "", stamp: str = "", detail: str = "") -> dict:
    """Everything the summary card shows, derived from the result only (no invented numbers)."""
    m, o, side = r.market, r.opportunity, main_side(r)
    out = {"side": side, "title": side, "levels": levels, "stamp": stamp, "detail": detail, "opportunity": None,
           "instrument": f"{inst.name} ({inst.symbol}) · {r.profile or PROFILES[inst.kind].name}" if inst else "",
           "buy_share": m.buy_share if m and side in (BUY, SELL, NEUTRAL) else None}
    directional = side in (BUY, SELL, NEUTRAL)
    out["strength"] = f"převaha {m.strength}/100" if m and directional else ""
    out["trend"] = (f"TREND: {m.trend} · kvalita dat {m.quality:.0%}" + (" · REFERENČNÍ DATA" if r.reference else "")
                    if m and directional else "")
    if r.is_signal:
        out["entry"] = (f"✓ OBCHODNÍ VSTUP: POTVRZEN {r.verdict}", GREEN if r.verdict == BUY else RED,
                        f"pravidla {r.strategy or st.NAMES['v21']}, všechny bezpečnostní filtry prošly")
    elif r.reference:
        out["entry"] = ("OBCHODNÍ VSTUP: NELZE (referenční data)", SLATE, r.reference)
    elif r.verdict == ERROR:
        out["entry"] = ("⚠ OBCHODNÍ VSTUP: ERROR", RED, r.summary)
    elif r.verdict == NO_DATA:
        out["entry"] = ("○ OBCHODNÍ VSTUP: NO DATA", SLATE, r.summary)
    else:
        out["entry"] = ("■ OBCHODNÍ VSTUP: ČEKÁ NA POTVRZENÍ", YELLOW, r.summary)
    why = (m.reason if m and directional else r.summary) or ""
    out["reason"] = f"<b>Důvod:</b> {html.escape(why[:1].upper() + why[1:], quote=False)}"
    out["reason_tip"] = "\n".join(([m.reason] if m else []) + r.reasons)
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
    # why the TRADE CONFIRMATION is not given (never hides the direction)
    if r.is_signal:
        waiting = ""
    elif r.reference:
        waiting = "Vstup se z referenčních dat nepotvrzuje (cena jiného produktu než CFD)."
    elif r.verdict == ERROR:
        waiting = "Technická chyba – analýzu spusťte znovu, detail uvádí příčinu."
    elif r.verdict == NO_DATA:
        waiting = "Vstup nelze potvrdit: " + (r.summary if directional else "chybí platná a aktuální data")
    elif o and o.state == "watch":
        waiting = f"Vstup nepotvrzen ({r.summary}). {o.name} (výzkum) čeká na: " + "; ".join(o.missing)
    elif o and o.state == "trigger":
        waiting = ("Nastavení splněno, ale " + o.risk_note) if o.blocked else (
            f"{o.name}: nastavení splněno – výzkumná strategie, NENÍ potvrzený signál (v testu po nákladech "
            f"ztrátová). Vstup nepotvrzen: {r.summary}")
    else:
        waiting = f"Vstup nepotvrzen: {r.summary}"
    out["waiting"] = waiting
    out["waiting_tone"] = {ERROR: "#fca5a5", NO_DATA: "#cbd5e1"}.get(r.verdict, "#fde68a")
    if m and directional:
        out["reasons"] = "<b>Hlavní důvody:</b><br>" + "<br>".join(f"• {html.escape(f.text)}" for f in m.top)
    elif m and m.missing:
        out["reasons"] = "<b>Chybí:</b> " + html.escape("; ".join(m.missing[:3]))
    else:
        out["reasons"] = ""
    return out


def detail_extra(r: Result, ocr_ms: float | None) -> str:
    """v2.3 sections of "Detail analýzy": bias, every setup, measured durations."""
    esc = html.escape
    parts = []
    m = r.market
    if m:
        from .direction import THRESHOLD
        vote = {1: "▲ BUY", -1: "▼ SELL", 0: "● 0"}
        parts.append(f"<p><b>MARKET DIRECTION: {esc(m.side)}</b> – skóre {m.score:+.3f}, převaha {m.strength}/100 "
                     f"(práh {round(THRESHOLD * 100)}), kvalita dat {m.quality:.0%}. Převaha je míra shody indikátorů, "
                     "ne pravděpodobnost výhry.<br>" + esc(m.reason) + "<br>"
                     + "<br>".join(f"{vote[f.vote]} · váha {f.weight:g} · {esc(f.text)}" for f in m.factors)
                     + (f"<br><i>Chybí: {esc('; '.join(m.missing))}</i>" if m.missing else "") + "</p>")
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

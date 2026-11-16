"""v2 UI flows with a simulated Trading 212 reader (offscreen Qt, any OS)."""
import os
import threading
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtWidgets import QApplication  # noqa: E402

from cfdcalc import auto  # noqa: E402
from cfdcalc.analysis import BUY, Result  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402
from cfdcalc.recognize import match  # noqa: E402
from cfdcalc.window import Win  # noqa: E402

W = Win(7, "Trading 212", 0, 0, 1200, 800)


class Reader:
    """Plays the role of auto.read(): what Trading 212 currently shows."""

    def __init__(self, *lines, status=auto.OK, message=""):
        self.set(*lines, status=status, message=message)
        self.calls = 0

    def set(self, *lines, status=auto.OK, message=""):
        self.lines, self.status, self.message = list(lines), status, message

    def __call__(self, region):
        self.calls += 1
        if self.status != auto.OK:
            return auto.Reading(self.status, self.message)
        return auto.Reading(auto.OK, "", W, match(self.lines))


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make(app, tmp_path, monkeypatch):
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(tmp_path))
    from cfdcalc import ui
    monkeypatch.setattr(ui, "data_dir", lambda: tmp_path)

    def build(reader, demo=True):
        s = QtCore.QSettings(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope,
                             "CFDSignalCalculator", "app")
        s.setValue("demo", demo)
        s.setValue("watch", False)   # the tests drive the ticks themselves
        s.setValue("mode", "auto")
        s.setValue("api_key", "test-key")
        s.sync()
        return ui.MainWindow(reader=reader)
    return build


def settle(app, w):
    w.bar.wait_idle()
    if w.task:
        w.task.wait(10000)
    for _ in range(30):
        app.processEvents()


def ticks(app, w, n=2):
    """AUTO readings only (does not wait for a running analysis)."""
    for _ in range(n):
        w.bar.tick()
        w.bar.wait_idle()
        for _ in range(30):
            app.processEvents()


def test_auto_recognises_without_marking_the_screen_again(app, make):
    reader = Reader("NVIDIA", "182.40")
    w = make(reader)
    ticks(app, w)
    assert w.inst.symbol == "NVDA" and "NVDA" in w.bar.name.text()
    assert "vidím NVIDIA" in w.bar.status.text()
    reader.set("EUR/USD", "1.0845")      # user switches Trading 212 to another instrument
    ticks(app, w, 1)
    assert w.inst.symbol == "NVDA" and "ověřuji změnu" in w.bar.status.text()   # one reading is not enough
    ticks(app, w, 1)
    assert w.inst.symbol == "EUR/USD"


def test_start_analyses_the_confirmed_instrument_then_change_makes_it_historical(app, make):
    reader = Reader("Tesla")
    w = make(reader)
    w.start()
    settle(app, w)
    assert w.analysed.symbol == "TSLA" and w.gauge.pct == 100
    assert "TSLA" in w.stamp.text() and "Analýza" in w.stamp.text()
    assert not w.verdict.text().startswith("HISTORICKÝ")
    reader.set("Apple")
    ticks(app, w)
    assert w.inst.symbol == "AAPL" and w.verdict.text().startswith("HISTORICKÝ")
    assert "platí jen pro Tesla" in w.explain.text() and w.gauge.title == "START"


def test_change_during_analysis_gives_historical_result_and_no_journal(app, make, monkeypatch, tmp_path):
    from cfdcalc import ui
    gate = threading.Event()

    def slow(inst, provider, calendar, spread, now, cfg, progress):
        gate.wait(10)
        return Result(verdict=BUY, reasons=["test"], entry=Decimal("100"), sl=Decimal("99"), tp=Decimal("102"),
                      data_time=now, completed=20, total=20)
    monkeypatch.setattr(ui, "run_analysis", slow)
    monkeypatch.setattr(ui, "Calendar", lambda path: ui._NoNews())
    reader = Reader("Gold")
    w = make(reader, demo=False)
    w.start()
    w.bar.wait_idle()
    app.processEvents()
    assert w.task.isRunning() and w.analysed.symbol == "XAU/USD"
    reader.set("Silver")
    ticks(app, w)                        # Trading 212 now shows Silver while Gold is being analysed
    gate.set()
    settle(app, w)
    assert w.verdict.text().startswith("HISTORICKÝ") and "Gold" in w.explain.text()
    assert not (tmp_path / "journal.csv").exists()


@pytest.mark.parametrize("reading, why", [
    (dict(lines=("NVIDIA", "Apple")), "více instrumentů"),
    (dict(lines=("Rolls-Royce",)), "neodpovídá"),
    (dict(lines=(), status=auto.NO_WINDOW, message="Okno Trading 212 nenalezeno."), "nenalezeno"),
    (dict(lines=(), status=auto.UNREADABLE, message="Obsah okna nelze bezpečně přečíst."), "nelze"),
])
def test_start_without_a_sure_instrument_asks_and_never_analyses_on_its_own(app, make, monkeypatch, reading, why):
    reader = Reader(*reading["lines"], status=reading.get("status", auto.OK), message=reading.get("message", ""))
    w = make(reader)
    asked = []
    monkeypatch.setattr(w.bar, "choose", lambda first=(), note="", ocr_text="": asked.append((first, note)))
    w.start()
    settle(app, w)
    assert asked and why in asked[0][1] and w.task is None   # user cancelled -> no analysis
    if reading["lines"] == ("NVIDIA", "Apple"):
        assert {i.symbol for i in asked[0][0]} >= {"NVDA", "AAPL"}


def test_start_after_user_confirms_candidate(app, make, monkeypatch):
    reader = Reader("US 50O")              # OCR typo: low confidence
    w = make(reader)
    monkeypatch.setattr(w.bar, "choose", lambda first=(), note="", ocr_text="": (
        w.bar.tracker.set_manual(first[0], ocr_text), w.bar._emit(), first[0])[-1])
    w.start()
    settle(app, w)
    assert w.analysed.symbol == "SPX"
    ticks(app, w)                           # the same uncertain text keeps meaning SPX
    assert w.inst.symbol == "SPX"


def test_manual_search_switches_to_manual_and_auto_cannot_override(app, make):
    reader = Reader("NVIDIA")
    w = make(reader)
    w.bar.search.setText("tsla")
    w.bar._search_enter()
    assert w.inst.symbol == "TSLA" and w.bar.mode() == "manual"
    ticks(app, w)
    assert w.inst.symbol == "TSLA"           # readings in RUČNĚ mode never change the choice
    calls = reader.calls
    w.start()
    settle(app, w)
    assert w.analysed.symbol == "TSLA" and reader.calls == calls   # START in RUČNĚ does not read T212


def test_favourites_and_recent(app, make):
    w = make(Reader())
    w.set_instrument(BY_SYMBOL["EUR/USD"])
    w.bar.fav.setChecked(True)
    w.bar.toggle_favourite()
    w.set_instrument(BY_SYMBOL["NVDA"])
    w.bar.remember(BY_SYMBOL["NVDA"])
    chips = [w.bar.chips.itemAt(i).widget().text() for i in range(w.bar.chips.count())
             if w.bar.chips.itemAt(i).widget()]
    assert chips[:2] == ["★ EUR/USD", "NVDA"]


def test_one_shot_load_works_in_manual_mode(app, make):
    reader = Reader("Germany 40")
    w = make(reader)
    w.bar.set_mode("manual")
    w.bar.read_once()
    settle(app, w)
    assert w.inst.symbol == "DAX"


def test_unchanged_instrument_result_is_current_and_journaled(app, make, monkeypatch, tmp_path):
    from cfdcalc import ui
    monkeypatch.setattr(ui, "run_analysis", lambda inst, *a: Result(
        verdict=BUY, reasons=["test"], entry=Decimal("100"), sl=Decimal("99"), tp=Decimal("102"),
        data_time=a[3], completed=20, total=20))
    monkeypatch.setattr(ui, "Calendar", lambda path: ui._NoNews())
    w = make(Reader("Gold"), demo=False)
    w.start()
    settle(app, w)
    assert w.verdict.text() == "BUY" and "XAU/USD" in (tmp_path / "journal.csv").read_text()


def test_reading_requested_while_busy_is_never_lost(app, make):
    """START during a running AUTO reading must still get its own reading and callback."""
    reader = Reader("Tesla")
    w = make(reader)
    got = []
    w.bar.tick()                                   # a timer reading is running...
    w.bar.read_once(then=lambda r: got.append(r))  # ...and START asks for another one
    for _ in range(3):
        w.bar.read_once(then=lambda r: got.append(r))
    w.bar.wait_idle()
    assert len(got) == 4 and reader.calls == 5 and not w.bar._busy and not w.bar._queued

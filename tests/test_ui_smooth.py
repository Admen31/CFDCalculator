"""v2.1 UI: cancel/timeout, rapid instrument switching, NO DATA/ERROR display, fixed layout, low repaint churn."""
import os
import threading
import time
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_ui_auto import Reader, settle, ticks  # noqa: E402

from cfdcalc import auto  # noqa: E402
from cfdcalc.analysis import BUY, ERROR, NO_DATA, Result  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def make(app, tmp_path, monkeypatch):
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(tmp_path))
    from cfdcalc import ui
    monkeypatch.setattr(ui, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(ui, "Calendar", lambda path: ui._NoNews())

    def build(reader, demo=False):
        s = QtCore.QSettings(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope,
                             "CFDSignalCalculator", "app")
        s.setValue("demo", demo)
        s.setValue("watch", False)
        s.setValue("mode", "auto")
        s.setValue("api_key", "test-key")
        s.sync()
        w = ui.MainWindow(reader=reader)
        w.show()
        return w
    return build


def gated(monkeypatch, verdict=BUY, **extra):
    """Replace run_analysis with one that waits for the returned gate (simulates a slow network)."""
    from cfdcalc import ui
    gate, calls = threading.Event(), []

    def slow(inst, provider, calendar, spread, now, cfg, progress, cancelled):
        calls.append(inst.symbol)
        progress(1, 20, f"Instrument {inst.name}")
        gate.wait(10)
        signal = verdict == BUY
        return Result(verdict=verdict, reasons=extra.get("reasons", ["test"]), summary="test",
                      entry=Decimal("100") if signal else None, sl=Decimal("99") if signal else None,
                      tp=Decimal("102") if signal else None, data_time=now, completed=20, total=20)
    monkeypatch.setattr(ui, "run_analysis", slow)
    return gate, calls


def pump(app, ms=150):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def test_waiting_for_api_shows_activity_but_only_real_percent(app, make, monkeypatch):
    gate, _ = gated(monkeypatch)
    w = make(Reader("Gold"))
    w.start()
    w.bar.wait_idle()
    pump(app)
    assert w.running() and w.gauge.busy and w.gauge.target == 5.0          # 1 of 20 real steps
    assert "čekám na Twelve Data" in w.gauge.sub
    gate.set()
    settle(app, w)
    assert not w.gauge.busy and w.gauge.target == 100


def test_click_cancels_and_late_result_is_ignored(app, make, monkeypatch, tmp_path):
    gate, _ = gated(monkeypatch)
    w = make(Reader("Gold"))
    w.start()
    w.bar.wait_idle()
    pump(app)
    assert w.running()
    w.gauge.clicked.emit()                                    # second click = cancel
    assert not w.running() and w.gauge.title == "START" and w.result.verdict.text() == "ZRUŠENO"
    gate.set()                                                # the worker finishes later with a BUY ...
    for t in list(w._retired):
        t.wait(5000)
    pump(app, 300)
    assert w.result.verdict.text() == "ZRUŠENO" and not (tmp_path / "journal.csv").exists()   # ... ignored


def test_analysis_timeout_cancels(app, make, monkeypatch):
    from cfdcalc import ui
    monkeypatch.setattr(ui, "ANALYSIS_TIMEOUT_MS", 200)
    gate, _ = gated(monkeypatch)
    w = make(Reader("Gold"))
    w.start()
    w.bar.wait_idle()
    pump(app, 500)
    assert not w.running() and "časový limit" in w.result.reason.text()
    gate.set()
    for t in list(w._retired):
        t.wait(5000)


def test_rapid_switching_during_analysis_never_shows_old_signal_as_current(app, make, monkeypatch, tmp_path):
    gate, calls = gated(monkeypatch)
    reader = Reader("Gold")
    w = make(reader)
    w.start()
    w.bar.wait_idle()
    pump(app)
    for name in ("Silver", "EUR/USD", "NVIDIA", "Silver"):     # quick switches in Trading 212
        reader.set(name)
        ticks(app, w, 2)
    gate.set()
    settle(app, w)
    assert calls == ["XAU/USD"] and w.inst.symbol == "XAG/USD"
    assert w.result.verdict.text().startswith("HISTORICKÝ") and "Gold" in w.result.reason.text()
    assert w.result.levels.styleSheet().endswith("color: #64748b;")
    assert not (tmp_path / "journal.csv").exists()
    w.start()                                                  # a new START analyses the current instrument
    settle(app, w)
    assert calls == ["XAU/USD", "XAG/USD"] and not w.result.verdict.text().startswith("HISTORICKÝ")


@pytest.mark.parametrize("verdict", [NO_DATA, ERROR])
def test_no_data_and_error_never_show_levels_or_journal(app, make, monkeypatch, tmp_path, verdict):
    gate, _ = gated(monkeypatch, verdict=verdict, reasons=["5min: zastaralá data"])
    gate.set()
    w = make(Reader("Gold"))
    w.start()
    settle(app, w)
    assert w.result.verdict.text() == verdict and w.result.levels.text() == "" and w.gauge.title == verdict
    assert not (tmp_path / "journal.csv").exists()


def test_window_size_never_changes(app, make, monkeypatch):
    gate, _ = gated(monkeypatch)
    reader = Reader("Gold")
    w = make(reader)
    size = w.size()
    gate.set()
    w.start()
    settle(app, w)
    for lines in (("NVIDIA", "Apple"), ("Rolls-Royce plc " * 8,), ("EUR/USD",)):
        reader.set(*lines)
        ticks(app, w, 2)
    w.result.detail_btn.click()
    pump(app)
    assert w.size() == size and w.minimumSize() == w.maximumSize() == size


def test_unchanged_readings_do_not_rebuild_or_repaint(app, make):
    reader = Reader("Gold")
    w = make(reader)
    w.bar.remember(BY_SYMBOL["EUR/USD"])
    ticks(app, w, 2)
    chips = [w.bar.chips.itemAt(i).widget() for i in range(w.bar.chips.count())]
    status = w.bar.status.text()
    ticks(app, w, 3)
    assert [w.bar.chips.itemAt(i).widget() for i in range(w.bar.chips.count())] == chips   # same widgets
    assert w.bar.status.text() == status
    tile = w.tiles["rsi"]
    tile.set("bull", "55", "x", "pro")
    anim = tile._anim
    anim.stop()
    tile.set("bull", "55", "x", "pro")                        # identical update: no new animation
    assert anim.state() == anim.State.Stopped


def test_hung_reading_does_not_block_start(app, make, monkeypatch):
    from cfdcalc import ui_instrument
    monkeypatch.setattr(ui_instrument, "READ_TIMEOUT_MS", 300)
    release = threading.Event()

    def hung(region):
        release.wait(5)
        return auto.Reading(auto.OK, "", None, None)
    w = make(hung)
    asked = []
    monkeypatch.setattr(w.bar, "choose", lambda first=(), note="", ocr_text="": asked.append(note))
    w.start()
    pump(app, 700)
    assert asked and "příliš dlouho" in asked[0] and not w.running()
    release.set()
    w.bar.wait_idle()


def test_close_waits_for_workers(app, make, monkeypatch):
    gate, _ = gated(monkeypatch)
    w = make(Reader("Gold"))
    w.start()
    w.bar.wait_idle()
    pump(app)
    task = w.task
    threading.Timer(0.3, gate.set).start()
    w.close()
    assert not task.isRunning() and not w.bar._busy

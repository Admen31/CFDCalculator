"""v2.6.1: the minimal main screen and the repeatable big START / BUY / SELL button (deterministic test data)."""
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLabel, QPushButton  # noqa: E402
from test_ui_auto import Reader, settle  # noqa: E402
from test_ui_smooth import app, gated, make  # noqa: E402,F401

from cfdcalc.data import DataError, synthetic_bars  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402

BASE = {"XAU/USD": 2000.0, "EUR/USD": 1.1}


class Script:
    """Market whose direction the test chooses before each click: up, down, or a failing API."""

    def __init__(self, now):
        self.now, self.mode, self.calls, self.lock = now, "up", 0, threading.Lock()

    def bars(self, symbol, interval, n, **kw):
        with self.lock:
            self.calls += 1
        if self.mode == "fail":
            raise DataError(f"{symbol}: Twelve Data neposkytla data pro interval {interval}. HTTP 500.", "server")
        minutes = {"5min": 5, "15min": 15, "1h": 60}[interval]
        base = BASE[symbol]
        drift = (0.003 if self.mode == "up" else -0.003) * base / 100
        return synthetic_bars(self.now, minutes, n, drift=drift, noise=0.0002 * base, seed=minutes, base=base)


@pytest.fixture
def live(app, make, monkeypatch):  # noqa: F811
    from datetime import datetime

    from conftest import T0

    from cfdcalc import ui

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T0
    monkeypatch.setattr(ui, "datetime", Clock)
    script = Script(T0)
    w = make(Reader("Gold"))
    w.providers = lambda: script
    w.bar.set_mode("manual")
    w.set_instrument(BY_SYMBOL["XAU/USD"])
    return w, script


def click(app, w, timeout=5.0):  # noqa: F811
    n = len(w.latencies)
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    end = time.monotonic() + timeout
    while len(w.latencies) == n and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.003)
    settle(app, w)
    return w.big.text(), [lab.text().split(": ", 1)[1] for lab in (w.entry_lbl, w.tp_lbl, w.sl_lbl)]


def num(x):
    return float(x)


def test_main_screen_shows_only_the_button_and_three_values(app, live):  # noqa: F811
    w, _ = live
    page = w.pages.currentWidget()
    labels = [x.text() for x in page.findChildren(QLabel) if x.isVisibleTo(page)]
    buttons = [x.text() for x in page.findChildren(QPushButton) if x.isVisibleTo(page)]
    assert labels == ["VSTUP: –", "TP: –", "SL: –"] and w.big.text() == "START"
    assert buttons == ["START", "Podrobnosti ▸"]                     # navigation to the details page only
    assert not w.gauge.isVisibleTo(w) and not w.result.isVisibleTo(w)


def test_start_buy_click_sell_click_buy_recomputes_every_time(app, live):  # noqa: F811
    w, script = live
    seen = []
    for mode, want in (("up", "BUY"), ("down", "SELL"), ("up", "BUY")):
        script.mode = mode
        before = script.calls
        state, (entry, tp, sl) = click(app, w)
        assert state == want and script.calls - before == 3            # new data on every click
        e, t, s_ = num(entry), num(tp), num(sl)
        assert (s_ < e < t) if want == "BUY" else (t < e < s_)       # SL/TP on the right side
        seen.append((state, entry, tp, sl))
    assert seen[0][1:] != seen[1][1:] and not w.running() and not w._retired
    assert len(w.latencies) == 3


def test_api_error_then_repeat_succeeds(app, live):  # noqa: F811
    w, script = live
    script.mode = "fail"
    state, values = click(app, w)
    assert state == "NO DATA" and values == ["–", "–", "–"] and not w.running()
    script.mode = "up"
    state, values = click(app, w)
    assert state == "BUY" and "–" not in values


def test_instrument_change_never_shows_old_prices(app, live):  # noqa: F811
    w, script = live
    state, gold = click(app, w)
    assert state == "BUY" and num(gold[0]) > 1000
    w.set_instrument(BY_SYMBOL["EUR/USD"])
    w.on_instrument_changed(w.inst)
    app.processEvents()
    assert w.big.text() == "START" and [lab.text() for lab in (w.entry_lbl, w.tp_lbl, w.sl_lbl)] == \
        ["VSTUP: –", "TP: –", "SL: –"]
    state, eur = click(app, w)
    assert w.analysed.symbol == "EUR/USD" and state == "BUY" and num(eur[0]) < 2       # EUR/USD prices only


def test_clicks_during_an_analysis_never_start_a_second_one(app, make, monkeypatch):  # noqa: F811
    gate, calls = gated(monkeypatch, "BUY")
    w = make(Reader("Gold"))
    w.bar.set_mode("manual")
    w.set_instrument(BY_SYMBOL["XAU/USD"])
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    for _ in range(3):                                              # impatient clicks while it runs
        QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
        app.processEvents()
    assert calls == ["XAU/USD"] and w.big.text() == "ANALYZUJI…" and w.running()
    gate.set()
    settle(app, w)
    assert w.big.text() == "BUY"
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)              # and the shown BUY starts the next one
    settle(app, w)
    assert calls == ["XAU/USD", "XAU/USD"] and w.big.text() == "BUY"


def test_timeout_then_repeat(app, make, monkeypatch):  # noqa: F811
    gate, calls = gated(monkeypatch, "BUY")
    w = make(Reader("Gold"))
    w.bar.set_mode("manual")
    w.set_instrument(BY_SYMBOL["XAU/USD"])
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    app.processEvents()
    w._timeout(w._gen)                                              # the 75 s watchdog fires
    assert w.big.text() == "START" and not w.running()
    gate.set()                                                      # the abandoned worker ends, its result ignored
    settle(app, w)
    for t in list(w._retired):
        t.wait(5000)
    app.processEvents()
    assert w.big.text() == "START" and not w._retired
    QTest.mouseClick(w.big, Qt.MouseButton.LeftButton)
    settle(app, w)
    assert len(calls) == 2 and w.big.text() == "BUY"

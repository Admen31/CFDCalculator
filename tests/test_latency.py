"""v2.6: measured response START click -> result on screen (mocked Twelve Data with 300 ms per request).

Prints median and p95 for a cache miss (new candles needed) and a cache hit (candles already in the session cache).
Real network latency depends on the user's connection and plan; this measures the application's own overhead
plus the parallel requests.
"""
import os
import statistics
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from test_data_errors import KEY, bars_json, install  # noqa: E402
from test_ui_auto import Reader  # noqa: E402
from test_ui_smooth import app, make  # noqa: E402,F401

API_DELAY = 0.3


def p95(xs):
    return sorted(xs)[max(0, int(round(0.95 * len(xs))) - 1)]


def run_once(app, w, timeout=10.0):  # noqa: F811
    n = len(w.latencies)
    w.start()
    end = time.monotonic() + timeout
    while len(w.latencies) == n and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)
    assert len(w.latencies) > n, "no result"
    return w.latencies[-1]


def test_start_to_result_latency(app, make, monkeypatch):  # noqa: F811
    from datetime import datetime

    from conftest import T0

    from cfdcalc import ui

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return T0
    monkeypatch.setattr(ui, "datetime", Clock)
    calls = []

    def slow(p):
        calls.append(p["symbol"])
        time.sleep(API_DELAY)
        return bars_json(p["symbol"], 300)
    install(monkeypatch, slow)
    w = make(Reader("EUR/USD"))
    w.s.setValue("api_key", KEY)
    w.s.setValue("mode", "manual")
    w.s.setValue("auto_refresh", False)
    w.s.setValue("td_per_minute", 600)
    from cfdcalc.instruments import BY_SYMBOL
    w.set_instrument(BY_SYMBOL["EUR/USD"])
    miss, hit = [], []
    for _ in range(8):
        w._cache = None                       # a fresh client: all three timeframes must be downloaded
        miss.append(run_once(app, w))
        n = len(calls)
        hit.append(run_once(app, w))          # same instrument again: served from the candle cache
        assert len(calls) - n <= 3
    summary = (f"LATENCY cache miss: median {statistics.median(miss) * 1000:.0f} ms, p95 {p95(miss) * 1000:.0f} ms; "
               f"cache hit: median {statistics.median(hit) * 1000:.0f} ms, p95 {p95(hit) * 1000:.0f} ms "
               f"(API {API_DELAY * 1000:.0f} ms per request, 3 requests in parallel)")
    print("\n" + summary)
    assert statistics.median(miss) < 3 * API_DELAY + 1.5     # parallel, not 3 x sequential + slack
    assert statistics.median(hit) < statistics.median(miss)

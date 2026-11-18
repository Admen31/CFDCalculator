"""v2.8: measured response START click -> M15 result on screen.

The real Twelve Data client parses mocked HTTP answers that take API_DELAY seconds (network + provider). Three
situations are measured, median and p95 printed (the CI log keeps them):
  * cache    - repeated click, no new 15m bar and the price is younger than 60 s: no request at all
  * price    - the price is older than 60 s: ONE small request (newest bars, merged)
  * full     - nothing cached (new instrument / first click): ONE request of the whole 15min window
Real network latency depends on the user's connection and the provider; this measures the application itself plus
one request of the given duration. Nothing here is a guaranteed response time during a provider outage.
"""
import os
import statistics
import time
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtCore")
from test_data_errors import KEY, install  # noqa: E402
from test_m15 import CONFIRMED_BUY, walk  # noqa: E402
from test_ui_auto import Reader  # noqa: E402
from test_ui_smooth import app, make  # noqa: E402,F401

API_DELAY = 0.3


def p95(xs):
    return sorted(xs)[max(0, int(round(0.95 * len(xs))) - 1)]


def run_once(app, w, timeout=10.0):  # noqa: F811
    n = len(w.latencies)
    w.analyze()
    end = time.monotonic() + timeout
    while len(w.latencies) == n and time.monotonic() < end:
        app.processEvents()
        time.sleep(0.002)
    assert len(w.latencies) > n, "no result"
    return w.latencies[-1], w.big.text()


def test_start_to_result_latency_m15(app, make, monkeypatch):  # noqa: F811
    from datetime import datetime

    from conftest import T0

    from cfdcalc import ui, ui_risk

    class Clock(datetime):
        t = T0

        @classmethod
        def now(cls, tz=None):
            return cls.t
    monkeypatch.setattr(ui, "datetime", Clock)
    monkeypatch.setattr(ui_risk, "datetime", Clock)
    calls = []

    def slow(p):
        calls.append((p["symbol"], p["interval"], int(p["outputsize"])))
        time.sleep(API_DELAY)
        bars = walk(Clock.t, seed=CONFIRMED_BUY)[-int(p["outputsize"]):]
        return {"status": "ok", "meta": {"symbol": p["symbol"], "interval": p["interval"]},
                "values": [{"datetime": f"{b.t.replace(tzinfo=None):%Y-%m-%d %H:%M:%S}", "open": repr(b.o),
                            "high": repr(b.h), "low": repr(b.l), "close": repr(b.c)} for b in bars]}
    install(monkeypatch, slow)
    w = make(Reader("EUR/USD"))
    w.s.setValue("api_key", KEY)
    w.s.setValue("mode", "manual")
    w.s.setValue("td_per_minute", 600)
    from cfdcalc.instruments import BY_SYMBOL
    w.set_instrument(BY_SYMBOL["EUR/USD"])
    w.m15.set_events([])
    full, price, cache, states = [], [], [], set()
    for _ in range(8):
        w.m15.feed.clear()                                    # nothing cached: the whole 15min window
        t, s = run_once(app, w)
        full.append(t)
        states.add(s)
        for _ in range(3):                                    # repeated clicks: served from the cache
            t, s = run_once(app, w)
            cache.append(t)
        Clock.t = Clock.t + timedelta(seconds=61)             # the price got old: one small request
        t, s = run_once(app, w)
        price.append(t)
        Clock.t = T0
    assert {c[1] for c in calls} == {"15min"}                 # M15 only, never 5min / 1h
    assert len(calls) == 16                                   # 8 full + 8 price requests, none for the cache
    summary = "LATENCY M15 " + "; ".join(
        f"{name}: median {statistics.median(xs) * 1000:.0f} ms, p95 {p95(xs) * 1000:.0f} ms (n={len(xs)})"
        for name, xs in (("cache (0 requests)", cache), ("price (1 small request)", price),
                         ("full (1 request)", full))) + f"; API {API_DELAY * 1000:.0f} ms per request"
    print("\n" + summary)
    assert states <= {"BUY", "SELL", "NEUTRAL", "NO DATA"}
    assert statistics.median(cache) < 0.5 and p95(cache) < 1.0     # target: under 1 s from a fresh cache
    assert statistics.median(full) < API_DELAY + 1.5 and statistics.median(price) < API_DELAY + 1.5

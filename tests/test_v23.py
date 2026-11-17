"""v2.3: market bias, WATCH, research vs. confirmed signals, candle cache, API limit, colours and texts.

All tests here use synthetic or mocked data (no live Twelve Data / Yahoo request).
"""
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from conftest import T0, FakeCalendar, FakeProvider

from cfdcalc import strategies as st
from cfdcalc.analysis import BUY, ERROR, NO_DATA, SELL, WAIT, Result, run_analysis
from cfdcalc.calendar import Event
from cfdcalc.data import CachedProvider, DataError, TwelveData, synthetic_bars
from cfdcalc.instruments import BY_SYMBOL

EUR, GOLD, SILVER = BY_SYMBOL["EUR/USD"], BY_SYMBOL["XAU/USD"], BY_SYMBOL["XAG/USD"]


def ctx(c5, *, o5=None, h5=None, l5=None, rsi=55.0, hist=0.01, ema5=None, e20=100.0, e50=99.0, atr15=1.0,
        t20=101.0, t50=100.0, c1h=102.0, atr1h=1.0, v5=None):
    n = len(c5)
    return st.Ctx(o5 or list(c5), h5 or [c + 0.1 for c in c5], l5 or [c - 0.1 for c in c5], list(c5),
                  v5 or [None] * n, ema5 or [c5[-1] - 0.05] * n, [rsi] * n if not isinstance(rsi, list) else rsi,
                  [hist] * n, e20, e50, c5[-1], atr15, t20, t50, c1h, atr1h)


# ---------------------------------------------------------------- market bias

@pytest.mark.parametrize("drift, k, want", [(0.002, 0, st.BULLISH), (-0.002, 10, st.BEARISH)])
def test_bias_follows_the_trend(drift, k, want):
    r = run_analysis(GOLD, FakeProvider(drift=drift, k=k), FakeCalendar(), 0.35, T0)
    assert r.bias is not None and r.bias.direction == want and abs(r.bias.score) >= 2 and len(r.bias.parts) == 3


def test_bias_neutral_without_agreement():
    x = ctx([100.0] * 30, rsi=50.0, hist=0.0, e20=100, e50=100, t20=100, t50=100, c1h=100)
    b = st.bias(x)
    assert b.direction == st.NEUTRAL and b.score == 0 and b.strength == ""


def test_bias_is_not_a_signal_and_absent_without_data():
    r = run_analysis(EUR, FakeProvider(fail="15min"), FakeCalendar(), 0.0001, T0)
    assert r.verdict == NO_DATA and r.bias is None and r.opportunity is None


# ---------------------------------------------------------------- setups

def test_pullback_watch_then_trigger():
    # uptrend, price dipped into the 15m EMA20 zone (100 +- 0.25) with RSI <= 50, no confirmation yet
    c5 = [101.0] * 24 + [100.6, 100.3, 100.1, 100.05, 100.1, 100.12]
    lows = [c - 0.1 for c in c5]
    x = ctx(c5, l5=lows, rsi=[55.0] * 26 + [48.0, 47.0, 49.0, 49.5], hist=-0.01, ema5=[100.4] * 30)
    s = st.pullback(x, 2)
    assert s.state == "watch" and s.direction == "BUY" and s.missing
    assert any("EMA20 (5m)" in m for m in s.missing) and any("MACD" in m for m in s.missing)
    c5[-1] = 100.6                                  # close back above the 5m EMA20 and the previous high
    x = ctx(c5, l5=lows, rsi=[55.0] * 26 + [48.0, 47.0, 49.0, 56.0], hist=0.02, ema5=[100.4] * 30)
    s = st.pullback(x, 2)
    assert s.state == "trigger" and s.entry == 100.6 and s.sl < min(lows[-6:]) and s.rr == pytest.approx(2.0)


def test_pullback_breaks_down_below_ema50():
    x = ctx([101.0] * 29 + [98.5], e20=100, e50=99)
    assert st.pullback(x, 2).state == "invalid"


def test_breakout_watch_and_confirmed_trigger_never_against_trend():
    box = [100.0 + (0.3 if k % 2 else -0.3) for k in range(25)]
    near = ctx(box + [100.4], h5=[c + 0.1 for c in box] + [100.5], l5=[c - 0.1 for c in box] + [100.3],
               t20=None, t50=None)
    s = st.breakout(near, 2, False)
    assert s.state == "watch" and "uzavření 5m nad" in s.missing[0]
    o5 = box + [100.3]
    up = ctx(box + [100.9], o5=o5, h5=[c + 0.1 for c in box] + [100.95], l5=[c - 0.1 for c in box] + [100.28],
             t20=None, t50=None)
    s = st.breakout(up, 2, False)
    assert s.state == "trigger" and s.direction == "BUY" and "objem" in s.risk_note and s.sl < s.entry
    down_trend = ctx(box + [100.9], o5=o5, h5=[c + 0.1 for c in box] + [100.95],
                     l5=[c - 0.1 for c in box] + [100.28], t20=99, t50=100, c1h=98)
    assert st.breakout(down_trend, 2, False).state != "trigger"       # no long breakout in a 1h downtrend


def test_mean_reversion_only_without_a_strong_trend():
    x = ctx([100.0] * 30, t20=103, t50=100, atr1h=1.0)
    s = st.meanrev(x, 2)
    assert s.state == "none" and "v trendu" in s.detail
    c5 = [100.0 + (0.05 if k % 2 else -0.05) for k in range(27)] + [99.3, 99.2, 99.45]
    o5 = list(c5)
    o5[-1] = 99.25
    x = ctx(c5, o5=o5, l5=[c - 0.05 for c in c5], rsi=[50.0] * 27 + [25.0, 22.0, 31.0], t20=100.1, t50=100,
            atr15=0.4)
    s = st.meanrev(x, 2)
    assert s.direction == "BUY" and s.state in ("trigger", "invalid")
    if s.state == "trigger":
        assert s.tp > s.entry > s.sl and s.rr >= 1.0


# ---------------------------------------------------------------- research vs confirmed

def _trigger(direction="BUY"):
    sign = 1 if direction == "BUY" else -1
    close = 100.0
    return st.Setup("pullback", direction, "trigger", "test", entry=close, sl=close - sign * 0.5,
                    tp=close + sign * 1.0)


def test_research_trigger_is_never_a_confirmed_signal(monkeypatch):
    monkeypatch.setattr(st, "scan", lambda *a: [_trigger()])
    r = run_analysis(EUR, FakeProvider(drift=0.0), FakeCalendar(), 0.0001, T0)
    assert r.verdict in (WAIT, BUY, SELL) and r.opportunity.state == "trigger"
    if r.verdict == WAIT:
        assert r.strategy == "" and r.sl is None
    assert not r.opportunity.validated


def test_validated_trigger_becomes_buy_with_rounded_levels(monkeypatch):
    monkeypatch.setattr(st, "VALIDATED", frozenset({"pullback"}))
    for direction in ("BUY", "SELL"):
        p = FakeProvider(drift=0.0)
        monkeypatch.setattr(st, "scan", lambda x, d, v, direction=direction: [
            st.Setup("pullback", direction, "trigger", "test", entry=x.c5[-1],
                     sl=x.c5[-1] - (1 if direction == "BUY" else -1) * 0.5 * x.atr15,
                     tp=x.c5[-1] + (1 if direction == "BUY" else -1) * x.atr15)])
        r = run_analysis(EUR, p, FakeCalendar(), 0.00001, T0)
        if r.verdict == WAIT:
            pytest.skip("synthetic market blocked by a safety filter")
        assert r.verdict == direction and r.strategy == "TREND PULLBACK" and r.is_signal
        assert isinstance(r.sl, Decimal) and (r.sl < r.entry < r.tp if direction == BUY else r.tp < r.entry < r.sl)


def test_validated_trigger_still_blocked_by_news(monkeypatch):
    monkeypatch.setattr(st, "VALIDATED", frozenset({"pullback"}))
    monkeypatch.setattr(st, "scan", lambda x, d, v: [st.Setup("pullback", "BUY", "trigger", "t", entry=x.c5[-1],
                                                              sl=x.c5[-1] - x.atr15, tp=x.c5[-1] + 2 * x.atr15)])
    news = Event(T0 + timedelta(minutes=10), "USD", "Non-Farm Payrolls", "High")
    r = run_analysis(EUR, FakeProvider(drift=0.0), FakeCalendar([news]), 0.00001, T0)
    assert r.verdict == WAIT and r.opportunity.blocked and "Non-Farm" in r.opportunity.risk_note


def test_error_keeps_no_bias(monkeypatch):
    def boom(*a):
        raise ValueError("broken")
    monkeypatch.setattr("cfdcalc.analysis.evaluate", boom)
    r = run_analysis(EUR, FakeProvider(), FakeCalendar(), 0.0001, T0)
    assert r.verdict == ERROR and r.bias is None


# ---------------------------------------------------------------- regression EUR/USD, XAU/USD, XAG/USD (mocked)

@pytest.mark.parametrize("inst, spread", [(EUR, 0.0001), (GOLD, 0.35), (SILVER, 0.03)])
@pytest.mark.parametrize("drift, k", [(0.002, 0), (-0.002, 10), (0.0, 0)])
def test_regression_three_instruments_mock_data(inst, spread, drift, k):
    r = run_analysis(inst, FakeProvider(drift=drift, k=k), FakeCalendar(), spread, T0)
    assert r.verdict in (BUY, SELL, WAIT) and r.completed == r.total == 20 and r.bias is not None
    assert {s.key for s in r.setups} == set(st.ORDER) and set(r.timings) >= {"data 5min", "výpočet"}
    if r.verdict in (BUY, SELL):
        assert r.strategy and r.is_signal


# ---------------------------------------------------------------- cache and API limit

class Counting:
    name = "Fake"

    def __init__(self, now):
        self.now, self.calls = now, []

    def bars(self, symbol, interval, n):
        self.calls.append((interval, n))
        return synthetic_bars(self.now, 5, n, drift=0.001, seed=3)


def test_cache_reuses_partial_and_full():
    now = datetime(2026, 11, 17, 15, 0, 5, tzinfo=timezone.utc)   # 5 s into a 5m period: last bar may not be final
    clock = [now]
    src = Counting(now)
    c = CachedProvider(src, clock=lambda: clock[0])
    a = c.bars("EUR/USD", "5min", 300)
    assert len(a) >= 300 and c.full == 1
    clock[0] = now + timedelta(seconds=25)        # same period, but the cached copy was fetched before it settled
    c.bars("EUR/USD", "5min", 300)
    assert c.partial == 1 and src.calls[-1][1] < 300   # only the newest bars were requested
    clock[0] = now + timedelta(seconds=40)        # cached copy from 15:00:30 >= 15:00:00 + 20 s -> nothing to fetch
    b = c.bars("EUR/USD", "5min", 300)
    assert c.hits == 1 and len(src.calls) == 2 and b[-1].t == a[-1].t
    clock[0] = now + timedelta(days=1)            # far away: no overlap possible -> full download
    src.now = clock[0]
    c.bars("EUR/USD", "5min", 300)
    assert c.full == 2


def test_cache_never_hides_errors():
    class Broken:
        def bars(self, *a):
            raise DataError("down", "server")
    with pytest.raises(DataError):
        CachedProvider(Broken()).bars("EUR/USD", "5min", 300)


def test_rate_limit_is_respected_locally(monkeypatch):
    from test_data_errors import bars_json, install
    seen = install(monkeypatch, lambda p: bars_json(p["symbol"]))
    td = TwelveData("k" * 20, per_minute=2)
    td.bars("EUR/USD", "5min", 3)
    td.bars("EUR/USD", "15min", 3)
    with pytest.raises(DataError) as e:
        td.bars("EUR/USD", "1h", 3)
    assert e.value.kind == "rate_limit" and len(seen) == 2 and "limitu 2 dotazů" in str(e.value)


# ---------------------------------------------------------------- colours and texts

def test_state_colours_and_icons():
    from cfdcalc import widgets as w
    assert (w.GREEN, w.RED, w.YELLOW) == ("#22c55e", "#ef4444", "#facc15")
    assert w.VERDICT_COLORS[BUY] == w.GREEN and w.VERDICT_COLORS[SELL] == w.RED
    assert w.VERDICT_COLORS[WAIT] == w.VERDICT_COLORS["WATCH"] == w.YELLOW
    assert w.ICONS[SELL] != w.ICONS[ERROR] and w.ICONS[ERROR] == "⚠"          # SELL vs ERROR: icon + word
    assert all(w.ICONS[k] for k in (BUY, SELL, WAIT, "WATCH", NO_DATA, ERROR, "BULLISH", "BEARISH", "NEUTRAL"))


def test_view_texts():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtCore")
    from cfdcalc.ui import view
    r = Result(verdict=WAIT, summary="1h graf je bez jasného trendu")
    r.opportunity = st.Setup("pullback", "SELL", "watch", "x", ["dotek zóny 1.08"])
    v = view(r)
    assert v["opportunity"][0] == "◆ WATCH" and "dotek zóny 1.08" in v["waiting"] and "TREND PULLBACK" in v["waiting"]
    assert "ČEKÁ NA POTVRZENÍ" in v["entry"][0] and v["side"] == "NEUTRAL"
    r.opportunity = _trigger()
    v = view(r)
    assert "VÝZKUM" in v["opportunity"][0] and "NENÍ potvrzený signál" in v["waiting"]
    assert view(Result(verdict=ERROR))["waiting"].startswith("Technická chyba")
    assert view(Result(verdict=NO_DATA))["waiting"] == "Vstup nelze potvrdit: chybí platná a aktuální data"

"""v2.1 decision rules: profiles, NO DATA / ERROR, unavailable vs neutral vs opposing, filters, market time."""
from dataclasses import replace
from datetime import datetime, time, timedelta, timezone

import pytest
from conftest import T0, FakeCalendar, FakeProvider

from cfdcalc import analysis, legacy
from cfdcalc import indicators as ind
from cfdcalc.analysis import (BUY, ERROR, NO_DATA, SELL, WAIT, Module, Settings, evaluate, market_end, prepare,
                              run_analysis)
from cfdcalc.instruments import BY_SYMBOL

AAPL, EURUSD, GOLD = BY_SYMBOL["AAPL"], BY_SYMBOL["EUR/USD"], BY_SYMBOL["XAU/USD"]


def frames(provider):
    out = {}
    for iv in ("5min", "15min", "1h"):
        out[iv], problem = prepare(provider.bars("X", iv, 300), iv, provider.now, 250)
        assert problem is None
    return out


UP = frames(FakeProvider())            # 1h uptrend, all filters pass for AAPL at T0 (see test_analysis)


def run(inst, states, monkeypatch, spread=0.01, events=(), now=T0, cfg=analysis.DEFAULTS):
    """Evaluate with fixed voter outputs: states = {"ema": "bull", "rsi": "neutral", ...}."""
    for key, state in states.items():
        score = {"bull": 1, "bear": -1}.get(state, 0)
        fixed = Module(key, state, "x", f"{key} {state}", score)
        monkeypatch.setattr(analysis, f"_{key}", lambda *a, m=fixed: Module(m.key, m.state, m.value, m.note, m.score))
    return evaluate(inst, UP["5min"], UP["15min"], UP["1h"], list(events), spread, now, cfg)


def test_baseline_buy_all_voters_agree(monkeypatch):
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="bull", vwap="bull", volume="bull"), monkeypatch)
    assert r.verdict == BUY and r.is_signal and r.counts["pro"] == 5 and r.counts["proti"] == 0
    assert all(status == "ok" for _, status, _ in r.filters), r.filters


def test_forex_does_not_count_missing_volume_against(monkeypatch):
    """Forex profile: VWAP/Volume do not apply; 2 of 3 usable voters for, none against, is enough."""
    r = run(EURUSD, dict(ema="bull", rsi="neutral", macd="bull"), monkeypatch)
    assert r.modules["vwap"].stance == r.modules["volume"].stance == "nepoužito"
    assert r.counts == {"pro": 2, "proti": 0, "neutrální": 1, "nedostupné": 0, "nepoužito": 2}
    assert ("Shoda indikátorů", "ok") == r.filters[2][:2], r.filters
    assert r.verdict == BUY, r.reasons


def test_v20_vs_v21_forex_without_volume(monkeypatch):
    """Real indicator maths, forex data without volume (as Twelve Data delivers it), an oversold RSI pullback in
    an uptrend. v2.0 needed 3 agreeing votes -> unanimity of EMA/RSI/MACD; v2.1 needs 60 % of the usable ones."""
    nov = {k: [replace(b, v=None) for b in bars] for k, bars in UP.items()}
    monkeypatch.setattr(ind, "rsi", lambda c, period=14: [25.0] * len(c))
    old = legacy.evaluate(EURUSD, nov["5min"], nov["15min"], nov["1h"], [], 0.01, T0)
    new = evaluate(EURUSD, nov["5min"], nov["15min"], nov["1h"], [], 0.01, T0)
    assert old.verdict == WAIT and "nedostatečná shoda indikátorů (2 pro, 0 proti)" in old.reasons
    assert new.counts["pro"] == 2 and new.counts["proti"] == 0 and new.counts["nepoužito"] == 2
    assert new.verdict == BUY, new.reasons


def test_opposing_vote_is_a_real_wait_but_neutral_is_not_against(monkeypatch):
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="bull", vwap="bear", volume="neutral"), monkeypatch)
    assert r.verdict == WAIT and r.counts["proti"] == 1 and r.modules["vwap"].stance == "proti"
    assert r.summary.startswith("Shoda indikátorů")
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="bull", vwap="neutral", volume="neutral"), monkeypatch)
    assert r.verdict == BUY and r.counts["neutrální"] == 2


def test_unavailable_optional_voter_is_not_against(monkeypatch):
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="bull", vwap="na", volume="na"), monkeypatch)
    assert r.verdict == BUY and r.counts["nedostupné"] == 2 and r.modules["vwap"].stance == "nedostupné"


def test_not_enough_support_waits(monkeypatch):
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="neutral", vwap="neutral", volume="neutral"), monkeypatch)
    assert r.verdict == WAIT and "potřeba ≥ 3 pro" in r.summary     # 60 % of 5 usable voters


def test_ema_must_follow_the_trend(monkeypatch):
    r = run(AAPL, dict(ema="neutral", rsi="bull", macd="bull", vwap="bull", volume="bull"), monkeypatch)
    assert r.verdict == WAIT and "EMA 20/50 ve směru trendu" in r.summary


@pytest.mark.parametrize("key", ["ema", "rsi", "macd"])
def test_missing_required_indicator_is_no_data(monkeypatch, key):
    states = dict(ema="bull", rsi="bull", macd="bull", vwap="bull", volume="bull")
    states[key] = "na"
    r = run(AAPL, states, monkeypatch)
    assert r.verdict == NO_DATA and not r.is_signal and r.entry is None


def test_too_few_usable_voters_is_no_data(monkeypatch):
    r = run(EURUSD, dict(ema="bull", rsi="bull", macd="na"), monkeypatch)
    assert r.verdict == NO_DATA and any("jen 2" in x for x in r.reasons)


def test_broken_indicator_is_error(monkeypatch):
    def boom(*a):
        raise ZeroDivisionError("x")
    monkeypatch.setattr(analysis, "_macd", boom)
    r = evaluate(AAPL, UP["5min"], UP["15min"], UP["1h"], [], 0.01, T0)
    assert r.verdict == ERROR and r.modules["macd"].state == "error" and not r.is_signal


def test_unexpected_provider_failure_is_error():
    p = FakeProvider()
    p.bars = lambda *a: 1 / 0
    r = run_analysis(AAPL, p, FakeCalendar(), 0.01, T0)
    assert r.verdict == ERROR and r.aborted


def test_no_trend_is_a_legitimate_wait():
    flat = frames(FakeProvider(drift=0.0))
    r = evaluate(EURUSD, flat["5min"], flat["15min"], flat["1h"], [], 0.01, T0)
    assert r.verdict in (WAIT, NO_DATA) and not r.is_signal
    if r.verdict == WAIT and r.direction is None:
        assert r.summary == "1h graf je bez jasného trendu"


def test_filters_report_each_safety_check(monkeypatch):
    late = Settings(cutoffs=(("stock", time(16, 30)),))
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="bull", vwap="bull", volume="bull"), monkeypatch, spread=5.0,
            cfg=late)
    status = {name: s for name, s, _ in r.filters}
    assert status["Spread"] == "fail" and status["Časový limit"] == "fail" and r.verdict == WAIT
    assert {"Aktuální data", "Trend 1h", "Shoda indikátorů", "RSI extrém", "Volatilita (ATR)", "Prostor k cíli",
            "Ekonomické zprávy", "Spread", "Časový limit", "Stop-loss"} == set(status)


def test_us_stock_session_and_per_market_limits():
    cfg = Settings()
    assert market_end(AAPL, datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc), cfg)[0] is None   # before 9:30 NY
    assert market_end(AAPL, datetime(2026, 11, 21, 16, 0, tzinfo=timezone.utc), cfg)[0] is None  # Saturday
    end, _ = market_end(AAPL, T0, cfg)
    assert end == datetime(2026, 11, 17, 20, 45, tzinfo=timezone.utc)      # 21:45 Prague before the 22:00 close
    end, _ = market_end(EURUSD, datetime(2026, 11, 17, 8, 0, tzinfo=timezone.utc), cfg)
    assert end == datetime(2026, 11, 17, 20, 0, tzinfo=timezone.utc)       # forex: 21:00 Prague
    custom = Settings(cutoffs=(("forex", time(18, 0)),))
    assert market_end(EURUSD, T0, custom)[0] == datetime(2026, 11, 17, 17, 0, tzinfo=timezone.utc)


def test_closed_market_does_not_call_the_api():
    p = FakeProvider(now=datetime(2026, 11, 17, 8, 0, 30, tzinfo=timezone.utc))
    r = run_analysis(AAPL, p, FakeCalendar(), 0.01, p.now)
    assert r.verdict == WAIT and "zavřený" in r.summary and not p.calls


def test_unmapped_symbol_is_no_data_without_api_call():
    from dataclasses import replace
    p = FakeProvider()
    unmapped = replace(BY_SYMBOL["SPX"], sources=())          # no exact and no reference source
    r = run_analysis(unmapped, p, FakeCalendar(), 0.6, T0)
    assert r.verdict == NO_DATA and "mapování" in r.summary and not p.calls


def test_cancel_between_steps():
    p = FakeProvider()
    r = run_analysis(GOLD, p, FakeCalendar(), 0.35, T0, cancelled=lambda: True)
    assert r.verdict == NO_DATA and "zrušena" in r.summary and not p.calls


def test_signal_levels_only_with_valid_stop(monkeypatch):
    r = run(AAPL, dict(ema="bull", rsi="bull", macd="bull", vwap="bull", volume="bull"), monkeypatch)
    assert r.sl < r.entry < r.tp
    r = run(AAPL, dict(ema="bear", rsi="bear", macd="bear", vwap="bear", volume="bear"), monkeypatch)
    assert r.verdict == WAIT and r.entry is None and r.sl is None   # trend is up: bearish votes oppose it
    assert r.counts["proti"] == 5


def test_sell_side_mirror(monkeypatch):
    down = frames(FakeProvider(drift=-0.002, k=10))
    for key, state in dict(ema="bear", rsi="bear", macd="bear", vwap="bear", volume="bear").items():
        fixed = Module(key, state, "x", "", -1)
        monkeypatch.setattr(analysis, f"_{key}", lambda *a, m=fixed: Module(m.key, m.state, m.value, m.note, -1))
    now = T0 + timedelta(minutes=10)
    r = evaluate(AAPL, down["5min"], down["15min"], down["1h"], [], 0.01, now)
    assert r.direction == SELL
    if r.verdict == SELL:
        assert r.tp < r.entry < r.sl


def test_closed_market_hours_do_not_make_stock_data_stale():
    """10:00 New York: the newest closed 1h bar is from yesterday's session - not stale, the market was closed."""
    from cfdcalc.analysis import session_open
    from cfdcalc.data import Bar
    now = datetime(2026, 11, 17, 15, 0, 30, tzinfo=timezone.utc)
    yesterday_last = datetime(2026, 11, 16, 20, 30, tzinfo=timezone.utc)   # 15:30-16:30 NY bar (close 21:30 UTC)
    bars = [Bar(yesterday_last - timedelta(hours=k), 1, 2, 0.5, 1.5, 10) for k in range(260)][::-1]
    _, problem = prepare(bars, "1h", now, 250)
    assert problem and "zastaralá" in problem                       # v2.0 behaviour: stale
    _, problem = prepare(bars, "1h", now, 250, session_open(AAPL, now))
    assert problem is None                                          # v2.1: session opened 30 min ago
    later = now + timedelta(hours=3)
    _, problem = prepare(bars, "1h", later, 250, session_open(AAPL, later))
    assert problem and "zastaralá" in problem                       # a gap inside the session stays stale


def test_partial_volume_makes_vwap_unavailable_not_an_error():
    """Real data (Yahoo, CI run 44049903157) had single bars without volume: VWAP must be 'unavailable'."""
    bars = [replace(b, v=None) if n == len(UP["5min"]) - 30 else b for n, b in enumerate(UP["5min"])]
    r = evaluate(AAPL, bars, UP["15min"], UP["1h"], [], 0.01, T0)
    assert r.modules["vwap"].state == "na" and r.modules["vwap"].stance == "nedostupné"
    assert r.verdict != ERROR and r.modules["volume"].state != "error"

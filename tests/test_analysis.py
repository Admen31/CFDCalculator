from datetime import time, timedelta
from decimal import Decimal

from conftest import T0, FakeCalendar, FakeProvider

from cfdcalc.analysis import BUY, NO_DATA, SELL, WAIT, Settings, run_analysis
from cfdcalc.calendar import Event
from cfdcalc.data import Bar, prepare, synthetic_bars
from cfdcalc.instruments import BY_SYMBOL

AAPL = BY_SYMBOL["AAPL"]


def analyse(provider, calendar=None, spread=0.01, cfg=None, progress=None):
    calls = []
    cal = FakeCalendar() if calendar is None else calendar
    r = run_analysis(AAPL, provider, cal, spread, provider.now, cfg or Settings(),
                     progress or (lambda *a: calls.append(a)))
    return r, calls


def test_buy_with_levels_rounded_away_from_price():
    r, calls = analyse(FakeProvider())
    assert r.verdict == BUY, r.reasons
    assert r.sl < r.entry < r.tp
    assert all(isinstance(x, Decimal) and x.as_tuple().exponent == -2 for x in (r.entry, r.sl, r.tp))
    assert float(r.entry) - float(r.sl) >= r.sl_dist - 0.01  # rounding never tightens the stop
    assert r.data_time == T0.replace(second=0)  # 15:00 = close of the 14:55 bar
    # progress = real finished steps, strictly increasing to 100 %
    done = [c[0] for c in calls]
    assert done == list(range(1, calls[0][1] + 1)) and r.completed == r.total == calls[0][1]


def test_sell_mirror():
    r, _ = analyse(FakeProvider(drift=-0.002, k=10))
    assert r.verdict == SELL, r.reasons
    assert r.tp < r.entry < r.sl


def test_stale_data_is_no_data():
    stale = FakeProvider()  # provider still returns bars ending at T0, the clock is 30 min later
    stale.bars = lambda s, i, n: FakeProvider().bars(s, i, n)
    stale.now = T0 + timedelta(minutes=30)
    r, calls = analyse(stale)
    assert r.verdict == NO_DATA and r.aborted and "zastaralá" in r.reasons[0] and not r.is_signal
    assert r.completed < r.total and not r.modules


def test_api_error_is_no_data():
    r, _ = analyse(FakeProvider(fail="1h"))
    assert r.verdict == NO_DATA and r.aborted and "plan" in r.reasons[0]


def test_calendar_down_is_no_data_never_a_signal():
    r, _ = analyse(FakeProvider(), calendar=FakeCalendar(fail=True))
    assert r.verdict == NO_DATA and r.modules["news"].state == "na" and r.entry is None
    assert any("kalendář" in x for x in r.reasons)


def test_high_impact_news_blocks():
    ev = Event(T0 + timedelta(minutes=20), "USD", "Non-Farm Payrolls", "High")
    r, _ = analyse(FakeProvider(), calendar=FakeCalendar([ev]))
    assert r.verdict == WAIT and "Payrolls" in r.modules["news"].note
    other = Event(T0 + timedelta(minutes=20), "JPY", "BoJ", "High")
    assert analyse(FakeProvider(), calendar=FakeCalendar([other]))[0].verdict == BUY


def test_spread_and_evening_limit():
    assert analyse(FakeProvider(), spread=5.0)[0].verdict == WAIT
    assert analyse(FakeProvider(), spread=0)[0].verdict == WAIT
    late = Settings(cutoffs=(("stock", time(16, 30)),))  # 16:30 Prague = 15:30 UTC, only 30 min left
    r, _ = analyse(FakeProvider(), cfg=late)
    assert r.verdict == WAIT and any("Časový limit" in x for x in r.reasons)


def test_prepare_drops_forming_bar_and_rejects_bad_candles():
    bars = synthetic_bars(T0, 5, 300)
    ok, problem = prepare(bars, "5min", T0, 250)
    assert problem is None and len(ok) == 250 and ok[-1].t + timedelta(minutes=5) <= T0
    bad = bars[:-2] + [Bar(bars[-2].t, 10, 9, 8, 10, 1)] + bars[-1:]  # high below close
    assert "neplatná" in prepare(bad, "5min", T0, 250)[1]
    assert "málo" in prepare(bars[:100], "5min", T0, 250)[1]

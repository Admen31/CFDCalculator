"""v2.8: M15 signal and the 15min data feed (pure logic, no Qt, no network)."""
import random
import threading
import time
from datetime import timedelta
from decimal import Decimal

from conftest import T0

from cfdcalc import m15
from cfdcalc.data import Bar, DataError
from cfdcalc.instruments import BY_SYMBOL, CATALOG

EUR, GOLD, SILVER = BY_SYMBOL["EUR/USD"], BY_SYMBOL["XAU/USD"], BY_SYMBOL["XAG/USD"]
BTC = BY_SYMBOL["BTC/USD"]
CONFIRMED_BUY, CONFIRMED_SELL, DIRECTION_ONLY = 44, 14, 3     # seeds of walk() (see test_seeds_are_what_they_say)


def walk(now, n=400, seed=1, drift=0.0, vol=0.0008, base=1.1, minutes=15):
    """Deterministic random walk of 15m bars; the last bar is the one forming at `now`."""
    rnd = random.Random(seed)
    step = timedelta(minutes=minutes)
    start = m15.period_start(now) - step * (n - 1)
    out, p = [], base
    for i in range(n):
        o = p
        c = o * (1 + drift + rnd.gauss(0, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        out.append(Bar(start + step * i, o, h, lo, c, None))
        p = c
    return out


def sig(seed, inst=EUR, spread=0.00008, now=T0, events=(), **kw):
    return m15.evaluate(inst, walk(now, seed=seed), now, spread, now, events=list(events), **kw)


def test_seeds_are_what_they_say():
    b, s, d = sig(CONFIRMED_BUY), sig(CONFIRMED_SELL), sig(DIRECTION_ONLY)
    assert (b.side, b.confirmed) == ("BUY", True)
    assert (s.side, s.confirmed) == ("SELL", True)
    assert d.side in ("BUY", "SELL") and not d.confirmed


def test_confirmed_levels_are_decimal_on_the_right_side_and_2r():
    for seed, side in ((CONFIRMED_BUY, "BUY"), (CONFIRMED_SELL, "SELL")):
        r = sig(seed)
        assert r.levels_ok and all(isinstance(x, Decimal) for x in (r.entry, r.sl, r.tp))
        assert (r.sl < r.entry < r.tp) if side == "BUY" else (r.tp < r.entry < r.sl)
        assert abs(abs(r.tp - r.entry) / abs(r.entry - r.sl) - 2) < Decimal("0.01")
        assert r.entry.as_tuple().exponent == -EUR.decimals
        assert r.live and r.price_time == T0                     # newest price = the forming bar of the request


def test_direction_only_never_has_levels():
    r = sig(DIRECTION_ONLY)
    assert r.entry is r.sl is r.tp is None and "ne obchodní pokyn" in r.note
    assert "nesplněna podmínka" in r.summary


def test_only_15m_bars_are_used_and_direction_ignores_the_forming_bar():
    bars = walk(T0, seed=CONFIRMED_BUY)
    a = m15.evaluate(EUR, bars, T0, 0.00008, T0, events=[])
    moved = bars[:-1] + [Bar(bars[-1].t, bars[-1].o, bars[-1].h * 1.01, bars[-1].l * 0.95, bars[-1].l * 0.96, None)]
    b = m15.evaluate(EUR, moved, T0, 0.00008, T0, events=[])
    assert a.factors == b.factors and a.score == b.score     # direction from CLOSED bars only
    assert a.data_time == m15.period_start(T0)                # close of the last closed 15m bar


def test_same_data_same_result():
    assert sig(CONFIRMED_BUY).entry == sig(CONFIRMED_BUY).entry and sig(5).side == sig(5).side


def test_no_data_cases():
    few = m15.evaluate(EUR, walk(T0, n=100), T0, 0.00008, T0, events=[])
    assert few.side == "NO DATA" and "málo" in few.summary
    stale_now = T0 + timedelta(hours=2)
    stale = m15.evaluate(EUR, walk(T0), stale_now, 0.00008, stale_now, events=[])
    assert stale.side == "NO DATA" and "zastaralá" in stale.summary
    bad = walk(T0)
    bad[-50] = Bar(bad[-50].t, float("nan"), 1, 1, 1, None)
    assert m15.evaluate(EUR, bad, T0, 0.00008, T0, events=[]).side == "NO DATA"
    saturday = T0 + timedelta(days=4)
    closed = m15.evaluate(EUR, walk(saturday), saturday, 0.00008, saturday, events=[])
    assert closed.side == "NO DATA" and "zavřen" in closed.summary


def test_entry_checks_block_levels():
    no_spread = sig(CONFIRMED_BUY, spread=0)
    assert not no_spread.confirmed and "spread" in no_spread.summary
    no_calendar = m15.evaluate(EUR, walk(T0, seed=CONFIRMED_BUY), T0, 0.00008, T0, events=None)
    assert not no_calendar.confirmed and "kalendář" in no_calendar.summary
    from cfdcalc.calendar import Event
    news = Event(T0 + timedelta(minutes=20), "USD", "Non-Farm Payrolls", "High")
    assert not sig(CONFIRMED_BUY, events=[news]).confirmed
    ref = m15.evaluate(EUR, walk(T0, seed=CONFIRMED_BUY), T0, 0.00008, T0, events=[], reference="ETF")
    assert ref.side == "BUY" and not ref.confirmed and ref.entry is None


def test_old_price_is_not_live():
    r = m15.evaluate(EUR, walk(T0, seed=CONFIRMED_BUY), T0 + timedelta(seconds=90), 0.00008, T0, events=[])
    assert not r.live and r.price_time == r.data_time


# ---------------------------------------------------------------- feed


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class Provider:
    name = "Twelve Data"
    pins_exchange = True

    def __init__(self, clock, seed=CONFIRMED_BUY, fail=None, delay=0.0):
        self.clock, self.seed, self.fail, self.delay = clock, seed, fail, delay
        self.calls, self.lock = [], threading.Lock()

    def bars(self, symbol, interval, n, exchange=None):
        with self.lock:
            self.calls.append((symbol, interval, n))
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise DataError(f"{symbol}: Twelve Data neposkytla data. Překročen limit dotazů API.", self.fail)
        return walk(self.clock(), seed=self.seed)[-n:]


def test_one_request_per_click_and_only_15min():
    clock = Clock(T0)
    p = Provider(clock)
    svc = m15.Service(m15.Feed(lambda: p, clock))
    svc.set_events([])
    r = svc.analyze(EUR, 0.00008)
    assert [c[1] for c in p.calls] == ["15min"] and r.side == "BUY" and not r.from_cache
    clock.t = T0 + timedelta(seconds=20)
    again = svc.analyze(EUR, 0.00008)                          # repeated click within the price TTL
    assert len(p.calls) == 1 and again.from_cache and again.entry == r.entry and again.fetched == r.fetched
    clock.t = T0 + timedelta(seconds=75)                      # price older than 60 s: one small request
    svc.analyze(EUR, 0.00008)
    assert len(p.calls) == 2 and p.calls[-1][2] < 10


def test_new_bar_triggers_a_request_even_without_wanting_a_price():
    clock = Clock(T0)
    p = Provider(clock)
    feed = m15.Feed(lambda: p, clock)
    feed.get(EUR)
    clock.t = T0 + timedelta(seconds=30)
    assert feed.need(feed.cached(EUR), clock.t, False) is None
    clock.t = m15.period_start(T0) + m15.STEP + timedelta(seconds=25)
    assert feed.need(feed.cached(EUR), clock.t, False) == "bar"
    feed.get(EUR, want_price=False)
    assert len(p.calls) == 2


def test_concurrent_callers_share_one_download():
    clock = Clock(T0)
    p = Provider(clock, delay=0.2)
    svc = m15.Service(m15.Feed(lambda: p, clock))
    out = []
    ts = [threading.Thread(target=lambda: out.append(svc.analyze(EUR, 0.00008))) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(p.calls) == 1 and len({r.side for r in out}) == 1


def test_errors_are_reported_with_their_cause():
    clock = Clock(T0)
    p = Provider(clock, fail="rate_limit")
    svc = m15.Service(m15.Feed(lambda: p, clock))
    r = svc.analyze(EUR, 0.00008)
    assert r.side == "NO DATA" and "limit" in r.summary
    report = "\n".join(svc.report(EUR, m15.DEFAULTS, has_key=True))
    assert "Překročen limit dotazů API" in report and "počkej minutu" in report


def test_plan_gating_without_a_request():
    clock = Clock(T0)
    p = Provider(clock)
    cfg = m15.Settings(td_plan="Basic")
    r = m15.Service(m15.Feed(lambda: p, clock)).analyze(BY_SYMBOL["XBR/USD"], 0.03, cfg)
    assert r.side == "NO DATA" and "tarif Twelve Data Grow" in r.summary and p.calls == []
    # silver: exact source needs Grow, the SLV reference is on Basic -> direction only, never levels
    s = m15.Service(m15.Feed(lambda: p, clock))
    s.set_events([])
    silver = s.analyze(SILVER, 0.03, cfg)
    assert p.calls[-1][0] == "SLV" and silver.reference and silver.entry is None


def test_crypto_uses_coinbase_first_and_falls_back_to_twelve_data():
    clock = Clock(T0)
    cb, td = Provider(clock, fail="server"), Provider(clock)
    cb.name = "Coinbase Exchange"
    svc = m15.Service(m15.Feed(lambda: {"coinbase": cb, "twelvedata": td}, clock))
    r = svc.analyze(BTC, 1.0)
    assert cb.calls and td.calls and r.source.startswith("Twelve Data") and r.side != "NO DATA"


def test_unknown_key_and_missing_provider():
    clock = Clock(T0)
    r = m15.Service(m15.Feed(lambda: {}, clock)).analyze(EUR, 0.00008)
    assert r.side == "NO DATA" and "poskytovatel není nastaven" in r.summary


def test_catalog_instruments_all_have_15min_capable_sources():
    for inst in CATALOG:
        for src in m15.sources_of(inst):
            assert src.provider in ("twelvedata", "coinbase")

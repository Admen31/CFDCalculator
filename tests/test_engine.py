"""Deterministic tests of the v2.2 execution model, metrics and validation protocol (hand-computed expectations)."""
from datetime import datetime, time, timedelta, timezone
from itertools import pairwise
from decimal import Decimal

import pytest

from cfdcalc.analysis import BUY, SELL, WAIT, Result, Settings
from cfdcalc.data import Bar, synthetic_bars
from cfdcalc.engine import Costs, Market, RandomEntries, run
from cfdcalc.instruments import BY_SYMBOL
from cfdcalc.validation import bootstrap, folds, metrics, periods

T = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)     # Tuesday, forex trades until 20:00 UTC
EUR = BY_SYMBOL["EUR/USD"]
SIG = 330                                                     # signal bar index
COSTS = Costs(spread_floor=0.2, slippage=0.05)


def flat(n=400, minutes=5):
    return synthetic_bars(T, minutes, n, drift=0.0, noise=0.0)   # o=h=l=c=100


class Once:
    """Strategy stub: one signal at a fixed decision time, WAIT otherwise."""

    def __init__(self, at, verdict, sl, tp, also=()):
        self.at, self.verdict, self.sl, self.tp, self.also = at, verdict, Decimal(str(sl)), Decimal(str(tp)), also

    def __call__(self, inst, s5, s15, s1, events, spread, now, cfg, params):
        if now == self.at or now in self.also:
            return Result(verdict=self.verdict, entry=Decimal("100"), sl=self.sl, tp=self.tp, reasons=["x"])
        return Result(verdict=WAIT, reasons=["stub"])


def market(tail: list[tuple], bid_ask_spread: float | None = None, drop_next=False):
    """Flat history; bars after the signal bar replaced by `tail` = [(o, h, l, c), ...] (mid prices)."""
    m5 = flat()
    for k, (o, h, lo, c) in enumerate(tail, start=SIG + 1):
        m5[k] = Bar(m5[k].t, o, h, lo, c, None)
    if drop_next:
        del m5[SIG + 1]
    bid = ask = None
    if bid_ask_spread is not None:
        d = bid_ask_spread / 2
        bid = [Bar(b.t, b.o - d, b.h - d, b.l - d, b.c - d, None) for b in m5]
        ask = [Bar(b.t, b.o + d, b.h + d, b.l + d, b.c + d, None) for b in m5]
    return Market(EUR, m5, flat(300, 15), flat(300, 60), bid, ask)


def signal_time(m):
    return m.mid5[SIG].t + timedelta(minutes=5)


def one(tail, verdict=BUY, sl=99, tp=102, costs=COSTS, **kw):
    m = market(tail, **kw)
    r = run(m, Once(signal_time(m), verdict, sl, tp), "test", costs, end=m.mid5[SIG + 20].t)
    return r


def test_buy_take_profit_next_bar_entry_at_ask():
    r = one([(100, 100.5, 99.8, 100.2), (100.2, 102.2, 100.1, 102)])
    t = r.trades[0]
    assert t.entry_time == T - timedelta(minutes=5 * (400 - SIG - 1))       # next bar's open, not the signal close
    assert t.entry == pytest.approx(100.15)                                 # mid 100 + half spread 0.1 + slip 0.05
    assert t.risk == pytest.approx(1.15) and t.how == "TP" and t.exit == 102
    assert t.net_r == pytest.approx((102 - 100.15) / 1.15)
    assert t.spread_r == pytest.approx(0.2 / 1.15) and t.slippage_r == pytest.approx(0.05 / 1.15)
    assert t.gross_r == pytest.approx((102.1 - 100) / 1.15)                 # mid to mid
    assert t.gross_r == pytest.approx(t.net_r + t.spread_r + t.slippage_r + t.other_r)


def test_sl_and_tp_in_one_bar_counts_as_sl():
    t = one([(100, 100.2, 99.9, 100), (100, 103, 98.5, 101)]).trades[0]
    assert t.how == "SL" and t.exit == pytest.approx(98.95)                 # SL 99 - slippage
    assert t.net_r == pytest.approx((98.95 - 100.15) / 1.15)


def test_gap_through_stop_fills_at_the_worse_open():
    t = one([(100, 100.2, 99.9, 100), (98.5, 98.6, 98.0, 98.2)]).trades[0]
    assert t.how == "SL (mezera)" and t.exit == pytest.approx(98.4 - 0.05)  # bid open 98.4 minus slippage
    assert t.net_r < -1.5                                                   # a gap loses more than 1 R


def test_forced_exit_charges_the_spread_exactly_once():
    m = market([])
    entry_at = m.mid5[SIG + 1].t
    cfg = Settings(cutoffs=(("forex", (entry_at + timedelta(minutes=15, hours=1)).time()),))  # Prague = UTC+1
    r = run(m, Once(signal_time(m), BUY, 99, 102), "test", COSTS, cfg, end=m.mid5[SIG + 20].t)
    t = r.trades[0]
    assert t.how == "časový limit" and t.exit == pytest.approx(99.9 - 0.05)
    assert t.gross_r == pytest.approx(0.0, abs=1e-12)                       # price did not move
    assert t.net_r == pytest.approx(-(0.2 + 0.1) / 1.15)                    # one full spread + two slippages


@pytest.mark.parametrize("quoted, entry", [(0.02, 100.15), (0.4, 100.25)])
def test_real_quotes_are_widened_to_the_trading212_floor(quoted, entry):
    t = one([(100, 100.5, 99.8, 100.2), (100.2, 102.4, 100.1, 102)], bid_ask_spread=quoted).trades[0]
    assert t.entry == pytest.approx(entry)


def test_sell_mirror():
    t = one([(100, 100.2, 99.7, 99.8), (99.8, 99.9, 97.8, 98)], verdict=SELL, sl=101, tp=98).trades[0]
    assert t.entry == pytest.approx(99.85) and t.how == "TP"                # bid 99.9 - slippage
    assert t.net_r == pytest.approx((99.85 - 98) / 1.15)


def test_rejections_are_logged_with_reasons():
    m = market([(100, 100.1, 99.95, 100)] * 4 + [(100, 102.5, 100, 102.2)])   # TP on the 5th bar
    at = signal_time(m)
    r = run(m, Once(at, BUY, 99, 102, also=(at + timedelta(minutes=10),)), "test", COSTS, end=m.mid5[SIG + 12].t)
    assert len(r.trades) == 1 and r.rejected[0][2] == "pozice je otevřená"
    m = market([(100, 100.1, 99.95, 100)] * 30)                               # never reaches SL/TP before data end
    r = run(m, Once(signal_time(m), BUY, 99, 102), "test", COSTS, end=m.mid5[SIG + 12].t)
    assert not r.trades and r.rejected[0][2] == "konec dat před uzavřením pozice"   # no invented exit
    r = one([], drop_next=True)
    assert not r.trades and r.rejected[0][2] == "chybí následující svíčka pro vstup"
    r = one([(100, 100.1, 99.9, 100)], sl=100.2, tp=102)
    assert not r.trades and r.rejected[0][2] == "vstupní cena je už za stop-lossem"


def test_closed_us_market_rejects_entry():
    nvda = BY_SYMBOL["NVDA"]
    m = market([])
    m = Market(nvda, m.mid5, m.mid15, m.mid1h)     # 12:00 UTC = 7:00 New York: market closed
    r = run(m, Once(signal_time(m), BUY, 99, 102), "test", COSTS, end=m.mid5[SIG + 5].t)
    assert not r.trades


def test_cost_decomposition_holds_for_random_trades():
    m5 = synthetic_bars(T, 5, 1500, drift=0.0, amp=0.3, noise=0.05, seed=3)
    m = Market(EUR, m5, synthetic_bars(T, 15, 600, amp=0.3, noise=0.05, seed=4),
               synthetic_bars(T, 60, 400, amp=0.3, noise=0.05, seed=5))
    r = run(m, RandomEntries(0.05, 1), "náhodný", Costs(0.02, 0.005), Settings(cutoffs=(("forex", time(23, 59)),)))
    assert len(r.trades) > 5
    for t in r.trades:
        assert t.gross_r == pytest.approx(t.net_r + t.spread_r + t.slippage_r + t.other_r)
        assert t.spread_r > 0 and t.exit_time > t.entry_time > t.signal_time - timedelta(minutes=1)
    for a, b in pairwise(r.trades):
        assert b.entry_time >= a.exit_time                          # never two positions at once


def test_metrics_by_hand():
    st = metrics([1, -1, -1, 2, -1])
    assert st["n"] == 5 and st["win"] == 0.4 and st["pf"] == 1.0 and st["exp"] == 0 and st["median"] == -1
    assert st["total"] == 0 and st["dd"] == 2 and st["streak"] == 2
    assert metrics([])["n"] == 0 and metrics([0.5, 0.5])["pf"] is None


def test_bootstrap_is_reproducible_and_sensible():
    rs = [1.0, -1.0] * 50 + [2.0] * 10
    a, b = bootstrap(rs), bootstrap(rs)
    assert a == b and a["lo"] < sum(rs) / len(rs) < a["hi"]
    assert bootstrap([-1.0] * 40)["p"] == 1.0


def test_chronological_split_and_folds():
    ts = [T + timedelta(minutes=5 * k) for k in range(1000)]
    p = periods(ts)
    assert p.dev_end == ts[500] and p.val_end == ts[750] and p.part(ts[499]) == "vývoj"
    assert p.part(ts[600]) == "validace" and p.part(ts[999]) == "test"
    f = folds(p)
    assert len(f) == 6 and f[0][0] == ts[0] and f[-1][1] == ts[-1]

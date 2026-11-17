from datetime import datetime, timedelta, timezone
from itertools import pairwise

from conftest import T0, FakeProvider

from cfdcalc.analysis import BUY, SELL, Settings
from cfdcalc.backtest import Trade, journal_add, journal_read, journal_verify, run_backtest, simulate
from cfdcalc.data import Bar
from cfdcalc.instruments import BY_SYMBOL


def bar(t, o, h, lo, c):
    return Bar(t, o, h, lo, c, 1.0)


def test_simulate_sl_wins_ties_and_spread_costs():
    t = T0
    both = [bar(t, 100, 103, 98, 100)]  # touches SL 99 and TP 102 in one bar
    tr = simulate(Trade(t, BUY, 100, 99, 102), both, spread=0.1, cfg=Settings())
    assert tr.how == "SL" and abs(tr.r - (-1.1)) < 1e-9
    tp = [bar(t, 100, 100.5, 99.5, 100), bar(t + timedelta(minutes=5), 100, 102.2, 100, 102)]
    tr = simulate(Trade(t, BUY, 100, 99, 102), tp, spread=0.0, cfg=Settings())
    assert tr.how == "TP" and tr.r == 2.0
    tr = simulate(Trade(t, SELL, 100, 101, 98), [bar(t, 100, 100.2, 97.9, 98)], spread=0.0, cfg=Settings())
    assert tr.how == "TP" and tr.r == 2.0


def test_simulate_closes_at_evening_cutoff():
    t = datetime(2026, 11, 17, 19, 50, tzinfo=timezone.utc)  # cut-off 21:00 Prague = 20:00 UTC
    bars = [bar(t + timedelta(minutes=5 * i), 100, 100.4, 99.6, 100.5) for i in range(5)]
    tr = simulate(Trade(t, BUY, 100, 99, 102), bars, spread=0.0, cfg=Settings())
    assert tr.how == "večerní limit" and tr.r == 0.5 and tr.exit_time == datetime(2026, 11, 17, 20, 0,
                                                                                    tzinfo=timezone.utc)


def test_backtest_runs_live_rules_without_lookahead():
    p = FakeProvider()
    p.now = T0 + timedelta(hours=12)  # history ends at 20:00 UTC
    rep = run_backtest(BY_SYMBOL["AAPL"], p, spread=0.01)
    assert rep.trades, rep.summary()
    for t in rep.trades:  # never two positions at once
        assert t.r is None or t.exit_time > t.time
    for a, b in pairwise(rep.trades):
        assert b.time >= a.exit_time
    assert "Obchodů" in rep.summary()


def test_journal_roundtrip_and_verify(tmp_path):
    path = tmp_path / "j.csv"
    p = FakeProvider()
    p.now = T0 + timedelta(hours=10)
    when = T0 + timedelta(hours=2)
    journal_add(path, "AAPL", BUY, when, "100.00", "99.00", "102.00")
    journal_add(path, "AAPL", BUY, T0 - timedelta(days=400), "1", "0.5", "2")  # older than history
    assert len(journal_read(path)) == 2
    rows = journal_verify(path, p, lambda s: 0.0, p.now)
    assert rows[1]["how"] == "mimo dostupnou historii"
    assert rows[0]["how"] in ("SL", "TP", "večerní limit") and rows[0]["result_r"]
    assert journal_read(path)[0]["result_r"] == rows[0]["result_r"]  # persisted



def test_no_look_ahead_and_split():
    """Altering bars after time X must not change any decision taken before X; the split is chronological."""
    from dataclasses import replace

    from cfdcalc.backtest import backtest_bars, compare
    p = FakeProvider()
    p.now = T0 + timedelta(days=3)
    m5, m15, h1 = (p.bars("X", iv, 1500) for iv in ("5min", "15min", "1h"))
    cut = m5[1100].t
    shock = lambda bars: [replace(b, o=b.o * 1.3, h=b.h * 1.3, l=b.l * 1.3, c=b.c * 1.3) if b.t >= cut else b  # noqa: E731
                          for b in bars]
    inst = BY_SYMBOL["EUR/USD"]
    for rules in ("v2.0", "v2.1"):
        a = backtest_bars(inst, m5, m15, h1, 0.01, rules=rules)
        b = backtest_bars(inst, shock(m5), shock(m15), shock(h1), 0.01, rules=rules)
        before = [o for o in a.outcomes if o[0] <= cut]
        assert before and before == [o for o in b.outcomes if o[0] <= cut]
    res = compare(inst, m5, m15, h1, 0.01)
    for rules in ("v2.0", "v2.1"):
        r = res[rules]
        dev, test = r["parts"]["vývoj"], r["parts"]["test"]
        assert sum(dev["verdicts"].values()) + sum(test["verdicts"].values()) == sum(r["verdicts"].values())
        assert all(t.time < r["split_at"] for t in r["report"].closed[:dev["spread"]["trades"]])
        net, spr = test["net"], test["spread"]
        if spr["trades"]:
            assert net["total"] < spr["total"] <= test["gross"]["total"]   # costs only ever reduce results

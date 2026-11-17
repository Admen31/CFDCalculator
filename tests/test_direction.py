"""v2.6 MARKET DIRECTION: weighted vote, partial data, real agreement and disagreement (synthetic data)."""

from conftest import T0

from cfdcalc.data import Bar, synthetic_bars
from cfdcalc.direction import BUY, NEUTRAL, NO_DATA, SELL, THRESHOLD, direction


def frames(drift, noise=0.02, volume=False, seed=1):
    return [synthetic_bars(T0, m, 300, drift=drift, noise=noise, seed=seed + m, volume=volume)
            for m in (5, 15, 60)]


def test_clear_uptrend_and_downtrend():
    up = direction(*frames(0.003))
    down = direction(*frames(-0.003))
    assert up.side == BUY and down.side == SELL and up.strength >= 50 and down.strength >= 50
    assert up.trend == "ROSTOUCÍ" and down.trend == "KLESAJÍCÍ" and up.buy_share >= 0.75 > 0.25 >= down.buy_share
    assert len(up.top) == 3 and all(f.vote == 1 for f in up.top) and up.quality == 1.0


def test_one_disagreeing_factor_does_not_flip_or_block():
    m5, m15, h1 = frames(0.003)
    # last 5m bars dip: short-term factors disagree, higher timeframes still up
    tail = [Bar(b.t, b.o - 0.4, b.h - 0.4, b.l - 0.4, b.c - 0.4, b.v) for b in m5[-3:]]
    d = direction(m5[:-3] + tail, m15, h1)
    assert d.side == BUY and d.n_sell >= 1 and d.score < direction(m5, m15, h1).score


def test_flat_market_is_neutral_with_a_reason():
    d = direction(*frames(0.0, noise=0.05, seed=7))
    assert d.side in (NEUTRAL, BUY, SELL)
    if d.side == NEUTRAL:
        assert "pod prahem" in d.reason and d.strength < THRESHOLD * 100


def test_partial_data_lowers_quality_but_still_decides():
    m5, m15, _ = frames(0.003)
    d = direction(m5, m15, None)
    assert d.side == BUY and d.quality < 1.0 and "(15m)" in d.trend and any("1h" in m for m in d.missing)


def test_minimum_data_or_no_data():
    m5, m15, h1 = frames(0.003)
    assert direction(None, m15, h1).side == NO_DATA
    assert direction(m5, None, None).side == NO_DATA and "15m i 1h" in direction(m5, None, None).reason
    assert direction(m5[:30], m15, h1).side == NO_DATA


def test_volume_factors_only_with_real_volume():
    with_vol = direction(*frames(0.003, volume=True))
    without = direction(*frames(0.003, volume=False))
    names = {f.name for f in with_vol.factors}
    assert "objem 5m" in names and "objem 5m" not in {f.name for f in without.factors}
    assert without.quality == 1.0           # no volume source: not counted as missing


def test_score_is_the_weighted_vote():
    d = direction(*frames(0.003))
    total = sum(f.weight for f in d.factors)
    assert abs(d.score - sum(f.signed for f in d.factors) / total) < 1e-3
    assert abs(d.buy_weight + d.sell_weight - sum(f.weight for f in d.factors if f.vote)) < 1e-9

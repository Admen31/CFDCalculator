from cfdcalc import indicators as ind


def test_ema_seed_and_constant():
    assert ind.ema([1, 2, 3], 3)[-1] == 2
    assert ind.ema([5.0] * 30, 10)[-1] == 5.0
    assert ind.ema([1, 2], 3) == [None, None]


def test_rsi_extremes():
    assert ind.rsi([float(i) for i in range(1, 40)])[-1] == 100.0
    assert ind.rsi([float(i) for i in range(40, 1, -1)])[-1] == 0.0
    assert ind.rsi([1.0] * 10)[-1] is None  # warm-up


def test_macd_sign_follows_acceleration():
    up = [100 + i * i * 0.01 for i in range(80)]
    assert ind.macd(up)[2][-1] > 0
    assert ind.macd([100 - i * i * 0.01 for i in range(80)])[2][-1] < 0


def test_atr_constant_range():
    h, lo, c = [11.0] * 30, [9.0] * 30, [10.0] * 30
    assert abs(ind.atr(h, lo, c)[-1] - 2.0) < 1e-12


def test_vwap_and_pivots():
    assert ind.vwap([10, 20], [1, 3]) == 17.5
    assert ind.vwap([10], [0]) is None
    res, sup = ind.pivots([1, 2, 3, 9, 3, 2, 1], [5, 4, 3, 1, 3, 4, 5])
    assert res == [9] and sup == [1]

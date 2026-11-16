"""Technical indicators (float maths for signal generation only; levels become Decimal in analysis).

Lists are aligned with the input, warm-up values are None. ema/wilder mirror capitalbot.strategies.indicators;
copied so the desktop app does not depend on the server bot package.
"""
from __future__ import annotations


def ema(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def wilder(values: list[float], period: int, start: int = 0) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if len(values) - start < period:
        return out
    prev = sum(values[start:start + period]) / period
    out[start + period - 1] = prev
    for i in range(start + period, len(values)):
        prev = (prev * (period - 1) + values[i]) / period
        out[i] = prev
    return out


def rsi(c: list[float], period: int = 14) -> list[float | None]:
    diffs = [0.0] + [c[i] - c[i - 1] for i in range(1, len(c))]
    up = wilder([max(d, 0.0) for d in diffs], period, 1)
    down = wilder([max(-d, 0.0) for d in diffs], period, 1)
    return [None if u is None else 100.0 if d == 0 else 100 - 100 / (1 + u / d) for u, d in zip(up, down, strict=True)]


def macd(c: list[float], fast: int = 12, slow: int = 26, sig: int = 9) -> tuple[list, list, list]:
    f, s = ema(c, fast), ema(c, slow)
    line = [None if a is None or b is None else a - b for a, b in zip(f, s, strict=True)]
    first = next((i for i, v in enumerate(line) if v is not None), len(line))
    signal = [None] * first + ema([v for v in line[first:]], sig)
    hist = [None if a is None or b is None else a - b for a, b in zip(line, signal, strict=True)]
    return line, signal, hist


def atr(h: list[float], lo: list[float], c: list[float], period: int = 14) -> list[float | None]:
    tr = [h[0] - lo[0]] + [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]
    return wilder(tr, period, 1)


def vwap(typical: list[float], volume: list[float]) -> float | None:
    total = sum(volume)
    return None if total <= 0 else sum(p * v for p, v in zip(typical, volume, strict=True)) / total


def pivots(h: list[float], lo: list[float], k: int = 3) -> tuple[list[float], list[float]]:
    """Swing highs (resistance candidates) and swing lows (support candidates), k bars on each side."""
    res = [h[i] for i in range(k, len(h) - k) if h[i] == max(h[i - k:i + k + 1])]
    sup = [lo[i] for i in range(k, len(lo) - k) if lo[i] == min(lo[i - k:i + k + 1])]
    return res, sup

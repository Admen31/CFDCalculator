"""v2.6 MARKET DIRECTION: which side prevails right now - BUY, SELL or NEUTRAL - from a transparent weighted vote.

Every available factor votes +1 (up), -1 (down) or 0 with a fixed weight; one disagreeing factor only lowers the
score, it never turns the answer into WAIT. score = sum(w * vote) / sum(w) over the factors that could be computed,
so it lies in [-1, 1]; "převaha" (strength) = |score| x 100. It is an agreement score of the indicators, NOT a
probability of a winning trade.

Weights were fixed before any test (longer timeframes weigh more). THRESHOLD is a fixed descriptive boundary; the lab
(scripts/strategy_lab.py, README "v2.6") checks every threshold out of sample and reports that none has an edge.
Missing factors lower the data quality; below MIN_QUALITY, or without 5m data plus one higher timeframe, the answer
is NO DATA. Uses CLOSED bars only (the caller validates freshness).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import indicators as ind

BUY, SELL, NEUTRAL, NO_DATA = "BUY", "SELL", "NEUTRAL", "NO DATA"
# |score| needed for BUY/SELL. Fixed in advance as a descriptive boundary ("převaha >= 25/100"): on the 2026 lab sample
# no threshold predicted the next move better than 50 % on the development part, so none was chosen for prediction.
THRESHOLD = 0.25
MIN_QUALITY = 0.5           # share of the applicable weight that must be available
TF_WEIGHT = {"5m": 0.75, "15m": 1.0, "1h": 1.5}


@dataclass
class Factor:
    name: str
    weight: float
    vote: int                 # +1 up, -1 down, 0 neither
    text: str

    @property
    def signed(self) -> float:
        return self.weight * self.vote


@dataclass
class Direction:
    side: str = NO_DATA
    score: float = 0.0               # -1 .. +1
    strength: int = 0                # |score| x 100
    buy_weight: float = 0.0
    sell_weight: float = 0.0
    n_buy: int = 0
    n_sell: int = 0
    n_neutral: int = 0
    quality: float = 0.0             # available / applicable weight, 0..1
    trend: str = "–"                 # ROSTOUCÍ / KLESAJÍCÍ / BEZ TRENDU (from the highest timeframe available)
    factors: list[Factor] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reason: str = ""                 # why NEUTRAL / NO DATA, or the summary of a BUY/SELL

    @property
    def top(self) -> list[Factor]:
        """The three strongest arguments for the result (for NEUTRAL: the strongest on either side)."""
        sign = 1 if self.side == BUY else -1 if self.side == SELL else 0
        pool = [f for f in self.factors if (f.vote == sign if sign else f.vote != 0)]
        return sorted(pool, key=lambda f: -f.weight)[:3]

    @property
    def buy_share(self) -> float:
        total = self.buy_weight + self.sell_weight
        return self.buy_weight / total if total else 0.5


def _sign(x: float | None, dead: float = 0.0) -> int | None:
    if x is None:
        return None
    return 1 if x > dead else -1 if x < -dead else 0


def _tf(bars, label: str, out: list, missing: list) -> int | None:
    """EMA20 vs EMA50, EMA20 slope and price vs EMA20 on one timeframe. Returns the EMA20/50 vote."""
    w = TF_WEIGHT[label]
    if not bars or len(bars) < 60:
        missing.append(f"{label}: málo svíček pro EMA")
        return None
    c = [b.c for b in bars]
    e20, e50 = ind.ema(c, 20), ind.ema(c, 50)
    cross = _sign(e20[-1] - e50[-1])
    slope = _sign(e20[-1] - e20[-4])
    above = _sign(c[-1] - e20[-1])
    word = {1: "nad", -1: "pod", 0: "na"}
    out.append(Factor(f"EMA20/50 {label}", w, cross, f"{label}: EMA20 {word[cross]} EMA50"))
    out.append(Factor(f"sklon EMA20 {label}", 0.5 * w, slope,
                      f"{label}: EMA20 {'roste' if slope > 0 else 'klesá' if slope < 0 else 'stojí'}"))
    out.append(Factor(f"cena vs EMA20 {label}", 0.5 * w, above, f"{label}: cena {word[above]} EMA20"))
    return cross


def _structure(bars, out: list, missing: list):
    """Higher highs + higher lows (up) / lower highs + lower lows (down) from 15m swing points."""
    if not bars or len(bars) < 40:
        missing.append("15m: málo svíček pro strukturu")
        return
    hs, ls = ind.pivots([b.h for b in bars[-120:-3]], [b.l for b in bars[-120:-3]])
    if len(hs) < 2 or len(ls) < 2:
        out.append(Factor("struktura 15m", 1.0, 0, "15m: struktura maxim/minim nečitelná"))
        return
    up, down = hs[-1] > hs[-2] and ls[-1] > ls[-2], hs[-1] < hs[-2] and ls[-1] < ls[-2]
    vote = 1 if up else -1 if down else 0
    out.append(Factor("struktura 15m", 1.0, vote, {1: "15m: vyšší maxima i minima", -1: "15m: nižší maxima i minima",
                                                    0: "15m: smíšená maxima/minima"}[vote]))


def direction(m5, m15, h1, threshold: float = THRESHOLD) -> Direction:
    d = Direction()
    f, missing = d.factors, d.missing
    if not m5 or len(m5) < 60:
        d.reason = "chybí platná data 5m – směr nelze určit"
        d.missing.append("5m: málo svíček")
        return d
    if (not m15 or len(m15) < 60) and (not h1 or len(h1) < 60):
        d.reason = "chybí vyšší časový rámec (15m i 1h) – směr nelze spolehlivě určit"
        return d
    applicable = 0.0
    trend = {}
    for bars, label in ((m5, "5m"), (m15, "15m"), (h1, "1h")):
        applicable += 2 * TF_WEIGHT[label]
        trend[label] = _tf(bars, label, f, missing)
    c5 = [b.c for b in m5]
    rsi = ind.rsi(c5)
    hist5 = ind.macd(c5)[2]
    if rsi[-1] is not None and rsi[-4] is not None:
        v = 1 if rsi[-1] > 55 else -1 if rsi[-1] < 45 else 0
        f.append(Factor("RSI 5m", 0.5, v, f"5m: RSI {rsi[-1]:.0f}"))
        s = _sign(rsi[-1] - rsi[-4])
        f.append(Factor("směr RSI 5m", 0.25, s, f"5m: RSI {'roste' if s > 0 else 'klesá' if s < 0 else 'stojí'}"))
    else:
        missing.append("RSI 5m")
    applicable += 0.75
    if hist5[-1] is not None and hist5[-2] is not None:
        s = _sign(hist5[-1])
        f.append(Factor("MACD 5m", 0.5, s, f"5m: MACD {'nad' if s > 0 else 'pod' if s < 0 else 'na'} signální linii"))
        m = _sign(hist5[-1] - hist5[-2])
        f.append(Factor("momentum MACD 5m", 0.25, m, f"5m: momentum {'sílí' if m > 0 else 'slábne' if m < 0 else '0'}"))
    else:
        missing.append("MACD 5m")
    applicable += 0.75
    if m15 and len(m15) >= 40:
        h15 = ind.macd([b.c for b in m15])[2]
        if h15[-1] is not None:
            s = _sign(h15[-1])
            f.append(Factor("MACD 15m", 0.75, s, f"15m: MACD {'nad' if s > 0 else 'pod' if s < 0 else 'na'} "
                                                  "signální linii"))
    else:
        missing.append("MACD 15m")
    applicable += 0.75
    _structure(m15, f, missing)
    applicable += 1.0
    vols = [b.v for b in m5[-21:]]
    if all(v is not None for v in vols) and sum(vols) > 0:          # volume factors apply only with real volume
        applicable += 1.0
        today = [b for b in m5 if b.t.date() == m5[-1].t.date()]
        vw = ind.vwap([(b.h + b.l + b.c) / 3 for b in today], [b.v for b in today]) \
            if all(b.v is not None for b in today) else None
        if vw is not None:
            s = _sign(c5[-1] - vw)
            f.append(Factor("VWAP 5m", 0.5, s, f"5m: cena {'nad' if s > 0 else 'pod' if s < 0 else 'na'} VWAP"))
        else:
            missing.append("VWAP 5m")
        avg = sum(vols[:-1]) / 20
        body = _sign(m5[-1].c - m5[-1].o)
        strong = avg > 0 and vols[-1] >= 1.2 * avg
        f.append(Factor("objem 5m", 0.5, body if strong else 0,
                        f"5m: {'nadprůměrný' if strong else 'běžný'} objem"
                        + ({1: " na rostoucí svíčce", -1: " na klesající svíčce", 0: ""}[body] if strong else "")))
    available = sum(x.weight for x in f)
    d.quality = round(available / applicable, 2) if applicable else 0.0
    d.buy_weight = sum(x.weight for x in f if x.vote > 0)
    d.sell_weight = sum(x.weight for x in f if x.vote < 0)
    d.n_buy = sum(1 for x in f if x.vote > 0)
    d.n_sell = sum(1 for x in f if x.vote < 0)
    d.n_neutral = sum(1 for x in f if x.vote == 0)
    top_tf = "1h" if trend.get("1h") is not None else "15m"
    t = trend.get(top_tf)
    d.trend = {1: "ROSTOUCÍ", -1: "KLESAJÍCÍ", 0: "BEZ TRENDU", None: "–"}[t] + ("" if top_tf == "1h" else " (15m)")
    if d.quality < MIN_QUALITY:
        d.reason = f"k dispozici jen {d.quality:.0%} vah indikátorů – směr nelze spolehlivě určit"
        return d
    d.score = round(sum(x.signed for x in f) / available, 3)
    d.strength = round(abs(d.score) * 100)
    if d.score >= threshold:
        d.side = BUY
    elif d.score <= -threshold:
        d.side = SELL
    else:
        d.side = NEUTRAL
    if d.side == NEUTRAL:
        d.reason = (f"převaha {d.strength}/100 je pod prahem {round(threshold * 100)} – růstové a poklesové "
                    f"argumenty jsou vyrovnané ({d.buy_weight:.2f} : {d.sell_weight:.2f})")
    else:
        d.reason = (f"{d.side}: převaha {d.strength}/100, váha argumentů {d.buy_weight:.2f} pro BUY a "
                    f"{d.sell_weight:.2f} pro SELL")
    return d

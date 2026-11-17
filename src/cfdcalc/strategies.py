"""v2.3: market bias and three rule-based setups (trend pullback, breakout, mean reversion).

Pure functions on CLOSED bars only (the same windows as the live analysis), no clock, no network.

  * MARKET BIAS  - BULLISH / BEARISH / NEUTRAL: a description of the prevailing direction, never an instruction.
  * Setup state  - "none"    nothing to follow
                   "watch"   the setup is forming; `missing` says exactly what has to happen
                   "trigger" every entry rule of the strategy is met (entry, SL, TP, R:R are computed)
                   "invalid" the setup existed but has broken down, or its stop/target would make no sense
  * A trigger becomes a CONFIRMED BUY/SELL only for strategies listed in VALIDATED, i.e. strategies that passed the
    pre-registered out-of-sample test (scripts/strategy_lab.py). Other strategies stay in research mode: the app
    shows their triggers as "setup splněn – výzkum", never as a trading signal.

All parameters are fixed here, chosen before any test (no fitting on the evaluated data).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import pstdev

from . import indicators as ind

BULLISH, BEARISH, NEUTRAL = "BULLISH", "BEARISH", "NEUTRAL"
PULLBACK, BREAKOUT, MEANREV = "pullback", "breakout", "meanrev"
NAMES = {PULLBACK: "TREND PULLBACK", BREAKOUT: "BREAKOUT", MEANREV: "MEAN REVERSION", "v21": "SHODA TRENDU (v2.1)"}
ORDER = (PULLBACK, BREAKOUT, MEANREV)

# Strategies whose triggers are allowed to be shown as confirmed BUY/SELL. Filled only from a passed
# out-of-sample test (README "v2.3 – výsledky"); empty = every new strategy is research only.
VALIDATED: frozenset[str] = frozenset()

# Result of the out-of-sample test (scripts/strategy_lab.py, Yahoo 25.08.-17.11.2026, 10 instruments, after costs;
# docs/v23-laborator-2026-11-17.md). Shown next to every setup so a WATCH is never mistaken for a proven edge.
RESEARCH_NOTE = {
    PULLBACK: "neověřeno – závěrečný test 192 obchodů, ⌀ −0,07 R po nákladech, 0/6 kladných úseků",
    BREAKOUT: "neověřeno – závěrečný test 100 obchodů, ⌀ −0,05 R po nákladech, 2/6 kladných úseků",
    MEANREV: "neověřeno – závěrečný test 45 obchodů, ⌀ −0,35 R po nákladech, 0/6 kladných úseků",
    "v21": "pravidla v2.1 – závěrečný test 118 obchodů, ⌀ +0,04 R, 95% interval −0,20 … +0,29 R (bez důkazu výhody)",
}
BIAS_NOTE = ("bias je popis, ne předpověď: ex post byla cena o hodinu později ve směru biasu v 48 % případů "
             "(10 instrumentů, 25.08.–17.11.2026)")

TP_R = 2.0                 # target for pullback and breakout (R multiples)
MIN_SL_ATR, MAX_SL_ATR = 0.5, 2.5    # sensible stop distance, in ATR(15m)
MAX_SPREAD_OF_SL = 0.15


@dataclass
class Bias:
    direction: str = NEUTRAL
    score: int = 0            # -4 .. +4
    strength: str = ""        # silný / střední / slabý
    parts: list[str] = field(default_factory=list)


@dataclass
class Setup:
    key: str
    direction: str | None = None        # BUY / SELL
    state: str = "none"                 # none | watch | trigger | invalid
    detail: str = ""                    # what the strategy sees now
    missing: list[str] = field(default_factory=list)    # what must still happen (watch)
    entry: float | None = None
    sl: float | None = None
    tp: float | None = None
    risk_note: str = ""
    blocked: bool = False               # triggered, but a safety filter forbids acting on it

    @property
    def name(self) -> str:
        return NAMES[self.key]

    @property
    def rr(self) -> float | None:
        if None in (self.entry, self.sl, self.tp) or self.entry == self.sl:
            return None
        return abs(self.tp - self.entry) / abs(self.entry - self.sl)

    @property
    def validated(self) -> bool:
        return self.key in VALIDATED


@dataclass
class Ctx:
    """Indicator values shared by bias and setups (computed once per decision)."""
    o5: list[float]
    h5: list[float]
    l5: list[float]
    c5: list[float]
    v5: list[float | None]
    ema20_5: list[float | None]
    rsi5: list[float | None]
    hist5: list[float | None]
    e20_15: float | None
    e50_15: float | None
    c15: float
    atr15: float | None
    t20: float | None
    t50: float | None
    c1h: float
    atr1h: float | None

    @property
    def trend(self) -> str | None:
        if self.t20 is None or self.t50 is None:
            return None
        if self.t20 > self.t50 and self.c1h > self.t50:
            return "BUY"
        if self.t20 < self.t50 and self.c1h < self.t50:
            return "SELL"
        return None

    @property
    def trend_strength(self) -> float | None:
        """|EMA20 - EMA50| on 1h in 1h ATRs (>= 1 = clear trend, < 0.5 = range)."""
        if None in (self.t20, self.t50) or not self.atr1h:
            return None
        return abs(self.t20 - self.t50) / self.atr1h


def context(s5, s15, s1) -> Ctx:
    c5, c15, c1 = [b.c for b in s5], [b.c for b in s15], [b.c for b in s1]
    return Ctx([b.o for b in s5], [b.h for b in s5], [b.l for b in s5], c5, [b.v for b in s5],
               ind.ema(c5, 20), ind.rsi(c5), ind.macd(c5)[2],
               ind.ema(c15, 20)[-1], ind.ema(c15, 50)[-1], c15[-1],
               ind.atr([b.h for b in s15], [b.l for b in s15], c15)[-1],
               ind.ema(c1, 20)[-1], ind.ema(c1, 50)[-1], c1[-1],
               ind.atr([b.h for b in s1], [b.l for b in s1], c1)[-1])


def _sign(direction: str) -> int:
    return 1 if direction == "BUY" else -1


def _f(x: float | None, d: int) -> str:
    return "–" if x is None else f"{x:.{d}f}"


# ---------------------------------------------------------------- market bias

def bias(x: Ctx) -> Bias:
    """1h trend (weight 2) + 15m EMA structure (1) + 5m momentum (1). BULLISH needs >= +2 with the 1h part not
    against it; BEARISH mirrored; anything else is NEUTRAL."""
    b = Bias()
    one = {"BUY": 2, "SELL": -2, None: 0}[x.trend]
    b.parts.append({2: "1h: EMA20 nad EMA50, cena nad EMA50", -2: "1h: EMA20 pod EMA50, cena pod EMA50",
                    0: "1h: bez jasného trendu"}[one])
    mid = 0
    if x.e20_15 is not None and x.e50_15 is not None:
        if x.e20_15 > x.e50_15 and x.c15 > x.e20_15:
            mid = 1
        elif x.e20_15 < x.e50_15 and x.c15 < x.e20_15:
            mid = -1
    b.parts.append({1: "15m: rostoucí struktura EMA", -1: "15m: klesající struktura EMA",
                    0: "15m: EMA bez jasné struktury"}[mid])
    mom = 0
    r, h = x.rsi5[-1], x.hist5[-1]
    if r is not None and h is not None:
        mom = 1 if (r > 50 and h > 0) else -1 if (r < 50 and h < 0) else 0
    b.parts.append({1: "5m: momentum nahoru (RSI > 50, MACD > signál)",
                    -1: "5m: momentum dolů (RSI < 50, MACD < signál)", 0: "5m: momentum smíšené"}[mom])
    b.score = one + mid + mom
    if b.score >= 2 and one >= 0:
        b.direction = BULLISH
    elif b.score <= -2 and one <= 0:
        b.direction = BEARISH
    b.strength = {4: "silný", 3: "střední", 2: "slabý"}.get(abs(b.score), "") if b.direction != NEUTRAL else ""
    return b


# ---------------------------------------------------------------- setups

def _stop(s: Setup, x: Ctx, extreme: float, tp_r: float | None, target: float | None = None) -> Setup:
    """Entry at the last close, stop beyond `extreme` (+0.2 ATR), target tp_r x risk or a fixed level."""
    sign = _sign(s.direction)
    entry = x.c5[-1]
    sl = extreme - sign * 0.2 * x.atr15
    dist = (entry - sl) * sign
    if not (MIN_SL_ATR * x.atr15 <= dist <= MAX_SL_ATR * x.atr15):
        s.state = "invalid"
        s.detail += f"; stop-loss by byl {dist / x.atr15:.1f}× ATR (povoleno {MIN_SL_ATR}–{MAX_SL_ATR}×)"
        return s
    s.entry, s.sl = entry, sl
    s.tp = entry + sign * tp_r * dist if target is None else target
    return s


def pullback(x: Ctx, d: int) -> Setup:
    """Trend (1h and 15m agree) -> price returns to the 15m EMA20 zone -> 5m close back with the trend
    (close beyond the 5m EMA20 and the previous bar's extreme, MACD histogram on the trend side)."""
    s = Setup(PULLBACK)
    t = x.trend
    if t is None or None in (x.e20_15, x.e50_15, x.atr15, x.ema20_5[-1], x.hist5[-1], x.rsi5[-1]):
        s.detail = "1h bez trendu – pullback se nehledá" if t is None else "málo dat"
        return s
    sign = _sign(t)
    s.direction = t
    if sign * (x.e20_15 - x.e50_15) <= 0:
        s.detail = "15m EMA20/50 nepotvrzuje trend 1h"
        s.state = "none"
        return s
    c = x.c5[-1]
    if sign * (c - x.e50_15) < 0:
        s.state, s.detail = "invalid", f"cena za EMA50 (15m) {_f(x.e50_15, d)} – trend narušen, setup zanikl"
        return s
    zone_lo, zone_hi = x.e20_15 - 0.25 * x.atr15, x.e20_15 + 0.25 * x.atr15
    recent = x.l5[-6:] if sign > 0 else x.h5[-6:]
    rsis = [r for r in x.rsi5[-6:] if r is not None]
    # a real pullback: momentum dipped against the trend (5m RSI crossed 50) while price reached the zone
    dipped = bool(rsis) and ((min(rsis) <= 50) if sign > 0 else (max(rsis) >= 50))
    touched = dipped and ((min(recent) <= zone_hi) if sign > 0 else (max(recent) >= zone_lo))
    zone = f"{_f(zone_lo, d)}–{_f(zone_hi, d)}"
    if not touched:
        gap = (min(recent) - zone_hi) if sign > 0 else (zone_lo - max(recent))
        falling_back = sign * (c - x.c5[-4]) < 0          # price is moving back towards the zone
        if 0 < gap <= 1.0 * x.atr15 and falling_back:
            s.state, s.detail = "watch", f"cena se vrací k EMA20 (15m), vstupní zóna {zone}"
            s.missing = [f"dotek vstupní zóny {zone}", "potom uzavření 5m svíčky zpět ve směru trendu"]
        elif gap > 0:
            s.detail = f"cena je daleko od vstupní zóny {zone} ({gap / x.atr15:.1f}× ATR)"
        else:
            s.detail = f"trend bez korekce – cena u zóny {zone}, ale momentum se nevrátilo"
        return s
    prev = x.h5[-2] if sign > 0 else x.l5[-2]
    need = []
    if sign * (c - x.ema20_5[-1]) <= 0:
        need.append(f"uzavření 5m {'nad' if sign > 0 else 'pod'} EMA20 (5m) {_f(x.ema20_5[-1], d)}")
    if sign * (c - prev) <= 0:
        need.append(f"uzavření 5m {'nad' if sign > 0 else 'pod'} {'maximem' if sign > 0 else 'minimem'} "
                    f"předchozí svíčky {_f(prev, d)}")
    if sign * x.hist5[-1] <= 0:
        need.append(f"MACD histogram {'nad' if sign > 0 else 'pod'} nulou (nyní {_f(x.hist5[-1], d + 1)})")
    if (x.rsi5[-1] >= 70) if sign > 0 else (x.rsi5[-1] <= 30):
        need.append("RSI mimo extrém")
    if need:
        s.state, s.detail, s.missing = "watch", f"cena je ve vstupní zóně {zone}, čeká se na potvrzení", need
        return s
    s.state, s.detail = "trigger", f"návrat do zóny {zone} a potvrzené pokračování trendu"
    return _stop(s, x, min(recent) if sign > 0 else max(recent), TP_R)


def breakout(x: Ctx, d: int, has_volume: bool) -> Setup:
    """2h consolidation (box of the previous 24 bars <= 2 ATR15) -> 5m close beyond the box by 0.1 ATR with a
    strong body (and above-average volume where volume exists). Never against the 1h trend."""
    s = Setup(BREAKOUT)
    if x.atr15 is None or len(x.c5) < 26:
        s.detail = "málo dat"
        return s
    hi, lo = max(x.h5[-25:-1]), min(x.l5[-25:-1])
    width = hi - lo
    if width > 2.0 * x.atr15:
        s.detail = f"bez konsolidace (rozpětí 2 h {width / x.atr15:.1f}× ATR, limit 2,0×)"
        return s
    c, o, h, low = x.c5[-1], x.o5[-1], x.h5[-1], x.l5[-1]
    box = f"{_f(lo, d)}–{_f(hi, d)}"
    allowed = [k for k in ("BUY", "SELL") if x.trend in (None, k)]
    for k in allowed:
        sign = _sign(k)
        edge = hi if sign > 0 else lo
        level = edge + sign * 0.1 * x.atr15
        if sign * (c - level) > 0:
            s.direction = k
            body_ok = abs(c - o) >= 0.5 * (h - low) and sign * (c - o) > 0
            vols = [v for v in x.v5[-21:] if v is not None]
            vol_ok = None
            if has_volume and len(vols) == 21 and sum(vols[:-1]) > 0:
                vol_ok = vols[-1] >= 1.2 * sum(vols[:-1]) / 20
            if not body_ok or vol_ok is False:
                s.state = "watch"
                s.detail = f"průraz {('nad' if sign > 0 else 'pod')} pásmo {box} bez potvrzení"
                s.missing = ["silné tělo svíčky ve směru průrazu"] if not body_ok else []
                s.missing += ["nadprůměrný objem (≥ 1,2× průměru)"] if vol_ok is False else []
                s.risk_note = "riziko falešného průrazu"
                return s
            s.state, s.detail = "trigger", f"potvrzený průraz konsolidace {box}"
            s.risk_note = "" if vol_ok else "bez objemových dat – vyšší riziko falešného průrazu"
            return _stop(s, x, (hi + lo) / 2, TP_R)
    near = [k for k in allowed if abs((hi if k == "BUY" else lo) - c) <= 0.3 * width]
    if near:
        k = near[0] if len(near) == 1 or x.trend is None else x.trend
        s.direction = k
        level = (hi + 0.1 * x.atr15) if k == "BUY" else (lo - 0.1 * x.atr15)
        s.state, s.detail = "watch", f"konsolidace {box}, cena u {'horní' if k == 'BUY' else 'dolní'} hrany"
        s.missing = [f"uzavření 5m {'nad' if k == 'BUY' else 'pod'} {_f(level, d)} se silným tělem svíčky"]
        return s
    s.detail = f"konsolidace {box}, cena uprostřed pásma"
    return s


def meanrev(x: Ctx, d: int) -> Setup:
    """Only without a strong 1h trend (EMA gap < 0.5 ATR1h): a 5m close outside Bollinger(20, 2) with RSI beyond
    30/70 in the last 3 bars, then a reversal bar back inside. Target = the 20-bar mean, needs R:R >= 1."""
    s = Setup(MEANREV)
    strength = x.trend_strength
    if strength is None or x.atr15 is None or len(x.c5) < 24 or x.rsi5[-1] is None:
        s.detail = "málo dat"
        return s
    if strength >= 0.5:
        s.detail = f"trh je v trendu (síla {strength:.1f}) – mean reversion se nepoužívá"
        return s
    last20 = x.c5[-20:]
    mid, sd = sum(last20) / 20, pstdev(last20)
    if sd <= 0:
        s.detail = "nulová volatilita"
        return s
    upper, lower = mid + 2 * sd, mid - 2 * sd
    c, o = x.c5[-1], x.o5[-1]
    for k, sign in (("BUY", 1), ("SELL", -1)):
        band = lower if sign > 0 else upper
        stretched = any(sign * (x.c5[-1 - j] - band_j) < 0 and r is not None and (r < 30 if sign > 0 else r > 70)
                        for j, band_j, r in _bands(x, sign))
        outside_now = sign * (c - band) < 0
        if not stretched and not outside_now:
            continue
        s.direction = k
        if stretched and not outside_now and sign * (c - o) > 0:
            s.detail = f"návrat do Bollingerova pásma po přepnutí (RSI {x.rsi5[-1]:.0f})"
            s.state = "trigger"
            extreme = min(x.l5[-4:]) if sign > 0 else max(x.h5[-4:])
            _stop(s, x, extreme, 0, target=mid)
            if s.state == "trigger" and (sign * (s.tp - s.entry) <= 0 or (s.rr or 0) < 1.0):
                rr = s.rr if sign * (s.tp - s.entry) > 0 else 0.0
                s.state, s.detail = "invalid", f"poměr zisk/riziko {rr:.2f} < 1 – obchod nedává smysl"
            return s
        s.state = "watch"
        s.detail = f"cena {'pod dolním' if sign > 0 else 'nad horním'} Bollingerovým pásmem {_f(band, d)}"
        s.missing = ([] if stretched else [f"RSI {'pod 30' if sign > 0 else 'nad 70'} (nyní {x.rsi5[-1]:.0f})"])
        s.missing.append(f"uzavření 5m {'rostoucí' if sign > 0 else 'klesající'} svíčky zpět "
                         f"{'nad' if sign > 0 else 'pod'} {_f(band, d)}")
        return s
    s.detail = "cena uvnitř Bollingerova pásma"
    return s


def _bands(x: Ctx, sign: int):
    """(offset, band, rsi) for the last 3 closed bars, each with the band of its own 20-bar window."""
    for j in range(3):
        w = x.c5[-20 - j:len(x.c5) - j]
        m, sd = sum(w) / 20, pstdev(w)
        yield j, (m - 2 * sd) if sign > 0 else (m + 2 * sd), x.rsi5[-1 - j]


def scan(x: Ctx, decimals: int, has_volume: bool) -> list[Setup]:
    out = []
    for key, fn in ((PULLBACK, lambda: pullback(x, decimals)), (BREAKOUT, lambda: breakout(x, decimals, has_volume)),
                    (MEANREV, lambda: meanrev(x, decimals))):
        try:
            out.append(fn())
        except (ValueError, ZeroDivisionError, TypeError) as e:
            out.append(Setup(key, state="none", detail=f"nelze vyhodnotit: {type(e).__name__}"))
    return out


def best(setups: list[Setup]) -> Setup | None:
    """The setup to show first: validated trigger > research trigger > watch > invalid."""
    rank = {"trigger": 3, "watch": 2, "invalid": 1}
    cands = [s for s in setups if s.state in rank]
    if not cands:
        return None
    return max(cands, key=lambda s: (rank[s.state] + (2 if s.validated and s.state == "trigger" else 0),
                                     -ORDER.index(s.key)))


# ---------------------------------------------------------------- safety (same filters as the live analysis)

def safety(s: Setup, spread: float, minutes_left: float, min_left: int, blocking_news: list, regime: float | None
           ) -> list[str]:
    """Reasons that forbid acting on a triggered setup (empty = all filters pass)."""
    out = []
    dist = abs(s.entry - s.sl) if s.entry is not None and s.sl is not None else None
    if not dist or not math.isfinite(dist):
        out.append("stop-loss nelze stanovit")
    elif spread <= 0 or spread > MAX_SPREAD_OF_SL * dist:
        out.append(f"spread {spread:g} je vůči stop-lossu příliš velký" if spread > 0 else "spread není zadán")
    if minutes_left < min_left:
        out.append(f"do konce obchodování zbývá {max(minutes_left, 0):.0f} min")
    if blocking_news:
        out.append(f"důležitá zpráva: {blocking_news[0].title}")
    if regime is not None and not (0.5 <= regime <= 2.5):
        out.append(f"volatilita mimo normu ({regime:.2f}× průměru)")
    return out


def atr_regime(s5) -> float | None:
    a5 = ind.atr([b.h for b in s5], [b.l for b in s5], [b.c for b in s5])
    recent = [x for x in a5[-50:] if x is not None]
    return a5[-1] / (sum(recent) / len(recent)) if a5[-1] and recent else None


# ---------------------------------------------------------------- research backtest adapters (engine.run)

def backtest_strategy(key: str):
    """engine.run strategy: BUY/SELL exactly when the live app would show this setup as triggered and every safety
    filter passes; the levels are the setup's own (Decimal-rounded like the live levels)."""
    def run(inst, s5, s15, s1, events, spread, now, cfg, params):
        from decimal import ROUND_HALF_EVEN

        from .analysis import BUY, SELL, WAIT, Result, _q, market_end, news_window
        r = Result(verdict=WAIT, reasons=[])
        end, why = market_end(inst, now, cfg)
        if end is None:
            r.reasons = [f"zavřeno: {why}"]
            return r
        x = context(s5, s15, s1)
        if x.atr15 is None:
            r.reasons = ["málo dat"]
            return r
        has_volume = all(b.v is not None for b in s5[-21:]) and sum(b.v for b in s5[-21:]) > 0
        s = {PULLBACK: lambda: pullback(x, inst.decimals), BREAKOUT: lambda: breakout(x, inst.decimals, has_volume),
             MEANREV: lambda: meanrev(x, inst.decimals)}[key]()
        if s.state != "trigger":
            r.reasons = [f"{s.state}: {s.detail.split(' (')[0][:40]}"]
            return r
        blocking = news_window(events or [], inst.currencies, now, cfg, end)[0]
        left = (end - now).total_seconds() / 60
        bad = safety(s, spread, left, cfg.min_minutes_left, blocking, atr_regime(s5))
        if bad:
            r.reasons = [f"filtr: {bad[0][:40]}"]
            return r
        r.verdict = BUY if s.direction == "BUY" else SELL
        r.entry = _q(s.entry, inst.decimals, ROUND_HALF_EVEN)
        r.sl = _q(s.sl, inst.decimals, ROUND_HALF_EVEN)
        r.tp = _q(s.tp, inst.decimals, ROUND_HALF_EVEN)
        r.reasons = [s.detail]
        return r
    run.__name__ = key
    return run


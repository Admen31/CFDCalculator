"""Research backtest engine (v2.2). Uses the live signal functions; models execution conservatively.

Decision: at the close of 5m bar i the strategy sees only bars closed by then (same windows as the live app).
Execution (default):
  * entry at the OPEN of the next 5m bar, BUY at ask, SELL at bid (from bid/ask candles when available,
    otherwise mid +/- half of the modelled spread);
  * the modelled spread is never below the instrument's Trading 212 floor (catalogue spread): a narrower quoted
    spread is widened by the difference;
  * a long position is closed on the BID side, a short on the ASK side - the spread is paid exactly once
    (half at entry, half at exit relative to mid);
  * slippage (adverse) on market fills: entry, stop-loss, forced exit; take-profit fills at its level;
  * a bar that OPENS beyond the stop (gap) fills at that worse open price; SL and TP in one bar -> SL;
  * forced exit at the market's evening limit (or exchange close), entries only while the market trades;
  * one position at a time; every BUY/SELL that is not executed is logged with its reason;
  * financing only if a position is held over the 22:00 UTC rollover (never happens with the evening limit).
R = result / risk, risk = |entry fill - stop|. The decomposition gross = net + spread + slippage + commission +
financing holds exactly for every trade.
"""
from __future__ import annotations

import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

from . import indicators as ind
from . import legacy
from .analysis import (BASE, BUY, DEFAULTS, NEED, NO_DATA, SELL, WAIT, Params, Settings, evaluate, market_end,
                       session_open)
from .data import Bar, prepare
from .instruments import Instrument

FIVE = timedelta(minutes=5)
_PRAGUE = ZoneInfo("Europe/Prague")


@dataclass(frozen=True)
class Costs:
    spread_floor: float              # minimum spread in price units (Trading 212 typical spread)
    slippage: float = 0.0            # adverse price units per market fill
    commission: float = 0.0          # price units per round trip (Trading 212 CFD: 0)
    financing_annual: float = 0.0    # fraction of entry price per year, charged per rollover night


@dataclass
class Market:
    """All bars of one instrument. mid* drive the signals; bid5/ask5 (same times, if available) drive fills."""
    inst: Instrument
    mid5: list[Bar]
    mid15: list[Bar]
    mid1h: list[Bar]
    bid5: list[Bar] | None = None
    ask5: list[Bar] | None = None
    severe: list[datetime] = field(default_factory=list)       # quality exclusions (times)
    events: Callable[[datetime], list] | None = None            # point-in-time calendar lookup
    news_covered: Callable[[datetime], bool] = lambda t: False  # True where the calendar is complete


@dataclass
class Trade:
    strategy: str
    signal_time: datetime
    entry_time: datetime
    direction: str
    entry: float          # fill price
    sl: float
    tp: float
    risk: float
    exit_time: datetime | None = None
    exit: float | None = None
    how: str = ""
    net_r: float | None = None
    gross_r: float | None = None     # without spread, slippage, commission, financing
    spread_r: float = 0.0
    slippage_r: float = 0.0
    other_r: float = 0.0             # commission + financing
    regime: str = ""
    volatility: str = ""
    hour: int = 0                    # entry hour, local (Europe/Prague)
    news_tested: bool = False


@dataclass
class Run:
    strategy: str
    params: Params
    trades: list[Trade] = field(default_factory=list)
    rejected: list[tuple[datetime, str, str]] = field(default_factory=list)     # (time, direction, reason)
    outcomes: list[tuple[datetime, str, str]] = field(default_factory=list)     # (decision time, verdict, reason)


# ---------------------------------------------------------------- strategies (all return a Result-like object)

def v21(inst, s5, s15, s1, events, spread, now, cfg, params):
    return evaluate(inst, s5, s15, s1, events, spread, now, cfg, params=params)


def v20(inst, s5, s15, s1, events, spread, now, cfg, params):
    return legacy.evaluate(inst, s5, s15, s1, events, spread, now, cfg)


class RandomEntries:
    """Benchmark: random direction at random bars with the same SL/TP construction (ATR15) and the same
    execution, sessions and costs. Expected result ~ minus costs; seeded for reproducibility."""

    def __init__(self, rate: float, seed: int):
        self.rate, self.rng = rate, random.Random(seed)

    def __call__(self, inst, s5, s15, s1, events, spread, now, cfg, params):
        from .analysis import Result, _q
        r = Result(verdict=WAIT, reasons=["náhodný model: bez vstupu"])
        if self.rng.random() >= self.rate or market_end(inst, now, cfg)[0] is None:
            return r
        a15 = ind.atr([b.h for b in s15], [b.l for b in s15], [b.c for b in s15])[-1]
        if not a15:
            return r
        d = BUY if self.rng.random() < 0.5 else SELL
        close, dist = s5[-1].c, params.sl_atr * a15
        sign = 1 if d == BUY else -1
        r.verdict, r.entry = d, _q(close, inst.decimals, "ROUND_HALF_EVEN")
        r.sl = _q(close - sign * dist, inst.decimals, "ROUND_HALF_EVEN")
        r.tp = _q(close + sign * params.tp_r * dist, inst.decimals, "ROUND_HALF_EVEN")
        return r


# ---------------------------------------------------------------- engine

def _reason_key(text: str) -> str:
    head = text.split(":")[0] if ":" in text[:40] else text
    for word in ("nedostatečná shoda", "do večerního limitu", "spread", "1h graf", "rezistence", "support",
                 "překoupeno", "přeprodáno", "trh spí", "extrémní volatilita", "EMA 20/50 nesouhlasí", "zavřen"):
        if word in text:
            return word
    return head[:40]


def _regime(s15: list[Bar], s1: list[Bar]) -> tuple[str, str]:
    """Trend vs range from the 1h EMA20-EMA50 gap in 1h ATRs; volatility from ATR15 vs its recent median."""
    c1 = [b.c for b in s1]
    e20, e50 = ind.ema(c1, 20)[-1], ind.ema(c1, 50)[-1]
    a1 = ind.atr([b.h for b in s1], [b.l for b in s1], c1)[-1]
    trend = "trend" if e20 and e50 and a1 and abs(e20 - e50) > a1 else "bez trendu"
    a15 = [x for x in ind.atr([b.h for b in s15], [b.l for b in s15], [b.c for b in s15])[-100:] if x]
    vol = "střední"
    if a15:
        ref = sorted(a15)[len(a15) // 2]
        vol = "nízká" if a15[-1] < 0.8 * ref else "vysoká" if a15[-1] > 1.25 * ref else "střední"
    return trend, vol


@dataclass
class Window:
    """What a strategy may see at decision time `now` (close of 5m bar i): validated closed bars only."""
    i: int
    now: datetime
    s5: list[Bar]
    s15: list[Bar]
    s1: list[Bar]
    problem: str | None
    spread: float
    events: list
    tested: bool


def windows(m: Market, costs: Costs, start: datetime | None = None, end: datetime | None = None,
            progress: Callable[[int, int], None] = lambda *_: None):
    """Walk the 5m bars and yield one Window per decision time (shared by run() and the WAIT diagnostics)."""
    inst = m.inst
    t5, t15, t1 = [b.t for b in m.mid5], [b.t for b in m.mid15], [b.t for b in m.mid1h]
    bid = {b.t: b for b in m.bid5} if m.bid5 else None
    ask = {b.t: b for b in m.ask5} if m.ask5 else None
    severe = m.severe
    lo = max(NEED - 1, bisect_left(t5, start) if start else 0)
    hi = bisect_left(t5, end) if end else len(m.mid5) - 1
    hi = min(hi, len(m.mid5) - 1)            # the last bar has no next bar to enter on
    n = max(hi - lo, 1)
    for k, i in enumerate(range(lo, hi)):
        if k % 500 == 0:
            progress(k, n)
        now = t5[i] + FIVE
        opened = session_open(inst, now)
        s5, p5 = prepare(m.mid5[i - NEED + 1:i + 1], "5min", now, NEED, opened)
        j15 = bisect_right(t15, now - timedelta(minutes=15))
        s15, p15 = prepare(m.mid15[max(0, j15 - NEED):j15], "15min", now, NEED, opened)
        j1 = bisect_right(t1, now - timedelta(hours=1))
        s1, p1 = prepare(m.mid1h[max(0, j1 - NEED):j1], "1h", now, NEED, opened)
        problem = p5 or p15 or p1
        if not problem and severe:
            first = min(s5[0].t, s15[0].t, s1[0].t)
            q = bisect_left(severe, first)
            if q < len(severe) and severe[q] <= now:
                problem = f"kvalita dat: problém {severe[q]:%Y-%m-%d %H:%M} v okně"
        spread = costs.spread_floor
        if bid is not None and t5[i] in bid and t5[i] in ask:
            spread = max(costs.spread_floor, ask[t5[i]].c - bid[t5[i]].c)
        tested = m.news_covered(now)
        events = m.events(now) if (m.events and tested and not problem) else []
        yield Window(i, now, s5, s15, s1, problem, spread, events, tested)
    progress(n, n)


def quotes(m: Market) -> tuple[dict | None, dict | None]:
    return ({b.t: b for b in m.bid5} if m.bid5 else None), ({b.t: b for b in m.ask5} if m.ask5 else None)


def run(m: Market, strategy: Callable, name: str, costs: Costs, cfg: Settings = DEFAULTS,
        params: Params = BASE, start: datetime | None = None, end: datetime | None = None,
        progress: Callable[[int, int], None] = lambda *_: None) -> Run:
    out = Run(name, params)
    inst = m.inst
    bid, ask = quotes(m)
    busy_until: datetime | None = None
    for w in windows(m, costs, start, end, progress):
        now = w.now
        if w.problem:
            out.outcomes.append((now, NO_DATA, w.problem.split(" – ")[0]))
            continue
        r = strategy(inst, w.s5, w.s15, w.s1, w.events, w.spread, now, cfg, params)
        out.outcomes.append((now, r.verdict, "" if r.verdict in (BUY, SELL) else _reason_key(r.reasons[0] if
                                                                                          r.reasons else "")))
        if r.verdict not in (BUY, SELL) or r.sl is None or r.tp is None:
            continue
        if busy_until and now < busy_until:
            out.rejected.append((now, r.verdict, "pozice je otevřená"))
            continue
        trade = _execute(m, w.i, r, now, costs, cfg, name, bid, ask)
        if isinstance(trade, str):
            out.rejected.append((now, r.verdict, trade))
            continue
        trade.regime, trade.volatility = _regime(w.s15, w.s1)
        trade.news_tested = w.tested
        out.trades.append(trade)
        busy_until = trade.exit_time or datetime.max.replace(tzinfo=timezone.utc)
    return out


def _side_bar(m: Market, k: int, side: str, bid, ask, half: float) -> Bar:
    """Bid or ask version of 5m bar k: real quotes when available (widened to the Trading 212 spread floor),
    otherwise mid +/- the modelled half spread."""
    mb = m.mid5[k]
    if bid is not None and mb.t in bid and mb.t in ask:
        b, a = bid[mb.t], ask[mb.t]
        extra = max(0.0, half - (a.c - b.c) / 2)
        src, d = (b, -extra) if side == "bid" else (a, extra)
        return Bar(mb.t, src.o + d, src.h + d, src.l + d, src.c + d, None)
    d = half if side == "ask" else -half
    return Bar(mb.t, mb.o + d, mb.h + d, mb.l + d, mb.c + d, None)


def _execute(m: Market, i: int, r, now: datetime, costs: Costs, cfg: Settings, name: str, bid, ask):
    """Fill on the next bar's open and walk forward until SL / TP / time limit. Returns a Trade or the reason
    why the signal could not be executed."""
    inst = m.inst
    if i + 1 >= len(m.mid5) or m.mid5[i + 1].t != now:
        return "chybí následující svíčka pro vstup"
    end, why = market_end(inst, now, cfg)
    if end is None:
        return f"trh zavřený při vstupu ({why})"
    if now + FIVE >= end:
        return "vstup až po časovém limitu"
    half = costs.spread_floor / 2
    sign = 1 if r.verdict == BUY else -1
    sl, tp = float(r.sl), float(r.tp)
    eb = _side_bar(m, i + 1, "ask" if sign > 0 else "bid", bid, ask, half)
    entry = eb.o + sign * costs.slippage
    risk = (entry - sl) * sign
    if risk <= 0:
        return "vstupní cena je už za stop-lossem"
    t = Trade(name, now, m.mid5[i + 1].t, r.verdict, entry, sl, tp, risk)
    t.hour = m.mid5[i + 1].t.astimezone(_PRAGUE).hour
    spread_paid = abs(eb.o - m.mid5[i + 1].o)            # half spread at entry, relative to mid
    exit_side = "bid" if sign > 0 else "ask"
    fill = None
    for k in range(i + 1, len(m.mid5)):
        mb = m.mid5[k]
        xb = _side_bar(m, k, exit_side, bid, ask, half)
        if k > i + 1:                                    # a bar that opens beyond a level (gap)
            if (xb.o <= sl) if sign > 0 else (xb.o >= sl):
                fill = (xb.o - sign * costs.slippage, "SL (mezera)", costs.slippage, abs(mb.o - xb.o), mb.t)
            elif (xb.o >= tp) if sign > 0 else (xb.o <= tp):
                fill = (tp, "TP", 0.0, abs(mb.o - xb.o), mb.t)
            if fill:
                break
        hit_sl = xb.l <= sl if sign > 0 else xb.h >= sl
        hit_tp = xb.h >= tp if sign > 0 else xb.l <= tp
        bar_end = mb.t + FIVE
        if hit_sl:                                       # SL first when both are inside one bar (conservative)
            fill = (sl - sign * costs.slippage, "SL", costs.slippage, abs(mb.c - xb.c), bar_end)
        elif hit_tp:
            fill = (tp, "TP", 0.0, abs(mb.c - xb.c), bar_end)
        elif bar_end >= end:
            fill = (xb.c - sign * costs.slippage, "časový limit", costs.slippage, abs(mb.c - xb.c), bar_end)
        if fill:
            break
    if fill is None:
        return "konec dat před uzavřením pozice"
    exit_price, how, exit_slip, exit_half, exit_time = fill
    financing = costs.financing_annual / 360 * entry * _rollovers(t.entry_time, exit_time)
    t.exit, t.how, t.exit_time = exit_price, how, exit_time
    t.net_r = (sign * (exit_price - entry) - costs.commission - financing) / risk
    t.spread_r = (spread_paid + exit_half) / risk
    t.slippage_r = (costs.slippage + exit_slip) / risk
    t.other_r = (costs.commission + financing) / risk
    t.gross_r = t.net_r + t.spread_r + t.slippage_r + t.other_r
    return t


def _rollovers(a: datetime, b: datetime | None) -> int:
    if b is None:
        return 0
    n, day = 0, a.replace(hour=22, minute=0, second=0, microsecond=0)
    if day <= a:
        day += timedelta(days=1)
    while day < b:
        n += 1
        day += timedelta(days=1)
    return n



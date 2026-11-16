"""Signal analysis. Pure functions: no Qt, no clock, no network (those are injected).

Rules (deliberately simple and explainable):
  * Trend: 1h EMA20 vs EMA50 and close vs EMA50 must point one way.
  * Voters on 5m/15m: EMA 20/50, RSI, MACD, VWAP, Volume. BUY/SELL needs >= 3 agreeing votes,
    none against, and EMA 20/50 agreeing with the 1h trend.
  * Gates (any one -> WAIT): RSI extreme, ATR regime, room to support/resistance, economic news,
    spread vs stop distance, time left before the evening cut-off.
  * SL = 1.5 x ATR(15m), TP = 2R. Levels are Decimal, SL rounded away from price, TP towards entry.
Missing or stale core data never produces BUY/SELL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from . import indicators as ind
from .calendar import Calendar, CalendarError, Event
from .data import Bar, DataError, Provider, prepare
from .instruments import Instrument

FETCH = 300      # bars requested per timeframe
NEED = 250       # closed bars analysed per timeframe (same window in live and backtest)
SL_ATR = 1.5
TP_R = 2.0
MAX_SPREAD_OF_SL = 0.15

BUY, SELL, WAIT = "BUY", "SELL", "WAIT"
MODULES = ("ema", "rsi", "macd", "vwap", "volume", "atr", "sr", "news")
TITLES = {"ema": "EMA 20/50", "rsi": "RSI", "macd": "MACD", "vwap": "VWAP", "volume": "Volume", "atr": "ATR",
          "sr": "Support/Resistance", "news": "Fundamenty"}


@dataclass(frozen=True)
class Settings:
    cutoff: time = time(21, 0)        # evening limit, local time
    tz: str = "Europe/Prague"
    min_minutes_left: int = 60
    news_before_min: int = 60         # block this long before a high-impact event...
    news_after_min: int = 30          # ...and this long after it


DEFAULTS = Settings()


@dataclass
class Module:
    key: str
    state: str = "na"                 # bull | bear | neutral | block | na
    value: str = "–"
    note: str = ""
    score: int = 0                    # +1 bull vote, -1 bear vote, 0 none
    blocks: frozenset = frozenset()   # directions this module forbids


@dataclass
class Result:
    verdict: str = WAIT
    reasons: list[str] = field(default_factory=list)
    modules: dict[str, Module] = field(default_factory=dict)
    trend: str = "–"
    data_time: datetime | None = None   # close time of the last 5m bar used
    entry: Decimal | None = None
    sl: Decimal | None = None
    tp: Decimal | None = None
    sl_dist: float | None = None
    completed: int = 0
    total: int = 0
    aborted: bool = False


def _q(x: float, decimals: int, rounding: str) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-decimals), rounding=rounding)


def _fmt(x: float | None, d: int) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def cutoff_utc(now: datetime, cfg: Settings) -> datetime:
    local = now.astimezone(ZoneInfo(cfg.tz))
    return datetime.combine(local.date(), cfg.cutoff, ZoneInfo(cfg.tz)).astimezone(timezone.utc)


def news_window(events: list[Event], currencies: tuple[str, ...], now: datetime, cfg: Settings):
    """(blocking high-impact events, later high-impact events today) for the given currencies."""
    high = [e for e in events if e.impact.lower() == "high" and e.currency in currencies]
    lo, hi = now - timedelta(minutes=cfg.news_after_min), now + timedelta(minutes=cfg.news_before_min)
    blocking = [e for e in high if lo <= e.time <= hi]
    later = [e for e in high if hi < e.time <= cutoff_utc(now, cfg)]
    return blocking, later


def evaluate(inst: Instrument, m5: list[Bar], m15: list[Bar], h1: list[Bar], events: list[Event] | None,
             spread: float, now: datetime, cfg: Settings = DEFAULTS,
             tick: Callable[[str], None] = lambda _: None) -> Result:
    """Decide on validated CLOSED bars. `events=None` means the calendar is unavailable (fail closed).
    Calls tick() after each of the 12 steps."""
    d = inst.decimals
    r = Result(data_time=m5[-1].t + timedelta(minutes=5))
    mods = r.modules
    c5 = [b.c for b in m5]
    c15 = [b.c for b in m15]
    close = c5[-1]

    # 1 EMA 20/50: direction of 15m structure, 5m close confirms
    m = Module("ema")
    e20, e50, f5 = ind.ema(c15, 20)[-1], ind.ema(c15, 50)[-1], ind.ema(c5, 20)[-1]
    m.value = f"15m {_fmt(e20, d)} / {_fmt(e50, d)}"
    if None in (e20, e50, f5):
        m.state, m.blocks, m.note = "na", frozenset({BUY, SELL}), "málo dat pro EMA"
    elif e20 > e50 and close > f5:
        m.state, m.score, m.note = "bull", 1, "EMA20 nad EMA50 (15m), cena nad EMA20 (5m)"
    elif e20 < e50 and close < f5:
        m.state, m.score, m.note = "bear", -1, "EMA20 pod EMA50 (15m), cena pod EMA20 (5m)"
    else:
        m.state, m.note = "neutral", "EMA bez shody 15m a 5m"
    mods["ema"] = m
    tick("EMA 20/50")

    # 2 RSI(14) 5m
    m = Module("rsi")
    v = ind.rsi(c5)[-1]
    m.value = _fmt(v, 1)
    if v is None:
        m.state, m.blocks, m.note = "na", frozenset({BUY, SELL}), "málo dat pro RSI"
    elif v >= 70:
        m.state, m.blocks, m.note = "block", frozenset({BUY}), "překoupeno – nekupovat"
    elif v <= 30:
        m.state, m.blocks, m.note = "block", frozenset({SELL}), "přeprodáno – neprodávat"
    elif v > 50:
        m.state, m.score, m.note = "bull", 1, "momentum nad 50"
    elif v < 50:
        m.state, m.score, m.note = "bear", -1, "momentum pod 50"
    else:
        m.state = "neutral"
    mods["rsi"] = m
    tick("RSI")

    # 3 MACD(12,26,9) 5m
    m = Module("macd")
    _, _, hist = ind.macd(c5)
    v = hist[-1]
    m.value = _fmt(v, d)
    if v is None:
        m.state, m.blocks, m.note = "na", frozenset({BUY, SELL}), "málo dat pro MACD"
    else:
        m.state, m.score = ("bull", 1) if v > 0 else ("bear", -1) if v < 0 else ("neutral", 0)
        m.note = "MACD nad signální linií" if v > 0 else "MACD pod signální linií" if v < 0 else ""
    mods["macd"] = m
    tick("MACD")

    # 4 VWAP (UTC day session, 5m) and 5 Volume - only when the provider has volume
    today = [b for b in m5 if b.t.date() == m5[-1].t.date()]
    has_vol = all(b.v is not None for b in m5[-21:]) and sum(b.v for b in m5[-21:]) > 0
    m = Module("vwap")
    vw = ind.vwap([(b.h + b.l + b.c) / 3 for b in today], [b.v for b in today]) if has_vol else None
    if vw is None:
        m.note = "zdroj nemá objemy – modul nehlasuje"
    else:
        m.value = _fmt(vw, d)
        m.state, m.score = ("bull", 1) if close > vw else ("bear", -1) if close < vw else ("neutral", 0)
        m.note = "cena nad VWAP" if close > vw else "cena pod VWAP"
    mods["vwap"] = m
    tick("VWAP")

    m = Module("volume")
    if not has_vol:
        m.note = "zdroj nemá objemy – modul nehlasuje"
    else:
        avg = sum(b.v for b in m5[-21:-1]) / 20
        ratio = m5[-1].v / avg if avg else 0.0
        m.value = f"{ratio:.2f}× průměru"
        up, down = m5[-1].c > m5[-1].o, m5[-1].c < m5[-1].o
        if ratio >= 1.0 and up:
            m.state, m.score, m.note = "bull", 1, "nadprůměrný objem na rostoucí svíčce"
        elif ratio >= 1.0 and down:
            m.state, m.score, m.note = "bear", -1, "nadprůměrný objem na klesající svíčce"
        else:
            m.state, m.note = "neutral", "objem nepotvrzuje"
    mods["volume"] = m
    tick("Volume")

    # 6 ATR: 15m ATR sizes the stop; 5m ATR regime vs its 50-bar mean
    m = Module("atr")
    a15 = ind.atr([b.h for b in m15], [b.l for b in m15], c15)[-1]
    a5 = ind.atr([b.h for b in m5], [b.l for b in m5], c5)
    recent = [x for x in a5[-50:] if x is not None]
    regime = a5[-1] / (sum(recent) / len(recent)) if a5[-1] and recent else None
    m.value = f"15m {_fmt(a15, d)}"
    if a15 is None or regime is None or a15 <= 0:
        m.state, m.blocks, m.note = "na", frozenset({BUY, SELL}), "ATR nelze spočítat"
    elif regime < 0.5:
        m.state, m.blocks, m.note = "block", frozenset({BUY, SELL}), f"trh spí (ATR 5m {regime:.2f}× průměru)"
    elif regime > 2.5:
        m.state, m.blocks, m.note = "block", frozenset({BUY, SELL}), f"extrémní volatilita ({regime:.2f}×)"
    else:
        m.state, m.note = "neutral", f"volatilita v normě ({regime:.2f}× průměru)"
    mods["atr"] = m
    tick("ATR")
    sl_dist = SL_ATR * a15 if a15 else None

    # 7 Support/Resistance from 15m swings: need 2R of room towards the target
    m = Module("sr")
    res, sup = ind.pivots([b.h for b in m15[:-3]], [b.l for b in m15[:-3]])
    above = min((x for x in res if x > close), default=None)
    below = max((x for x in sup if x < close), default=None)
    m.value = f"S {_fmt(below, d)} | R {_fmt(above, d)}"
    m.state = "neutral"
    blocks, notes = set(), []
    if sl_dist:
        if above is not None and above - close < TP_R * sl_dist:
            blocks.add(BUY)
            notes.append("rezistence blíž než cíl – BUY nemá prostor")
        if below is not None and close - below < TP_R * sl_dist:
            blocks.add(SELL)
            notes.append("support blíž než cíl – SELL nemá prostor")
    m.blocks, m.note = frozenset(blocks), "; ".join(notes) or "dost prostoru k cíli"
    if blocks:
        m.state = "block"
    mods["sr"] = m
    tick("Support/Resistance")

    # 8 Fundamentals: high-impact news window, fail closed
    m = Module("news")
    if events is None:
        m.state, m.blocks, m.value, m.note = "block", frozenset({BUY, SELL}), "bez dat", "kalendář nedostupný"
    else:
        blocking, later = news_window(events, inst.currencies, now, cfg)
        if blocking:
            e = blocking[0]
            m.state, m.blocks = "block", frozenset({BUY, SELL})
            m.value, m.note = f"{e.currency} {e.time:%H:%M} UTC", f"důležitá zpráva: {e.title}"
        else:
            m.state, m.value = "neutral", "klid"
            m.note = ("později dnes: " + ", ".join(f"{e.currency} {e.title} {e.time:%H:%M} UTC" for e in later[:3])
                      if later else "žádná důležitá zpráva v okně")
    mods["news"] = m
    tick("Fundamentální události")

    # 1h trend confirmation
    ch = [b.c for b in h1]
    t20, t50 = ind.ema(ch, 20)[-1], ind.ema(ch, 50)[-1]
    trend = None
    if t20 is not None and t50 is not None:
        trend = BUY if t20 > t50 and ch[-1] > t50 else SELL if t20 < t50 and ch[-1] < t50 else None
    r.trend = {BUY: "rostoucí", SELL: "klesající", None: "bez trendu"}[trend]
    tick("Trend 1h")

    # spread check
    spread_ok = bool(sl_dist) and spread > 0 and spread <= MAX_SPREAD_OF_SL * sl_dist
    tick("Spread")

    # evening limit
    left = (cutoff_utc(now, cfg) - now).total_seconds() / 60
    time_ok = left >= cfg.min_minutes_left
    tick("Limit do večera")

    # decision
    reasons = r.reasons
    if trend is None:
        reasons.append("1h graf nepotvrzuje trend")
    direction = trend
    if direction:
        sign = 1 if direction == BUY else -1
        votes = [x.score * sign for x in mods.values() if x.score]
        agree, oppose = votes.count(1), votes.count(-1)
        if mods["ema"].score != sign:
            reasons.append("EMA 20/50 nesouhlasí s trendem 1h")
        if agree < 3 or oppose:
            reasons.append(f"nedostatečná shoda indikátorů ({agree} pro, {oppose} proti)")
        for x in mods.values():
            if direction in x.blocks:
                reasons.append(f"{TITLES[x.key]}: {x.note}")
    else:
        reasons += [f"{TITLES[x.key]}: {x.note}" for x in mods.values() if x.blocks >= {BUY, SELL}]
    if not spread_ok:
        reasons.append(f"spread {spread:g} je příliš velký vůči stop-lossu" if sl_dist and spread > 0
                       else "spread není zadán nebo nelze ověřit")
    if not time_ok:
        reasons.append(f"do večerního limitu {cfg.cutoff:%H:%M} zbývá {max(left, 0):.0f} min "
                       f"(min. {cfg.min_minutes_left})")
    if direction and not reasons:
        r.verdict, r.sl_dist = direction, sl_dist
        r.entry = _q(close, d, ROUND_HALF_EVEN)
        if direction == BUY:
            r.sl, r.tp = _q(close - sl_dist, d, ROUND_FLOOR), _q(close + TP_R * sl_dist, d, ROUND_FLOOR)
        else:
            r.sl, r.tp = _q(close + sl_dist, d, ROUND_CEILING), _q(close - TP_R * sl_dist, d, ROUND_CEILING)
        reasons.append("souhlasných indikátorů: "
                       f"{sum(1 for x in mods.values() if x.score == sign)}, žádný filtr neblokuje")
    tick("Rozhodnutí")
    return r


EVALUATE_STEPS = 12


def run_analysis(inst: Instrument, provider: Provider, calendar: Calendar | None, spread: float, now: datetime,
                 cfg: Settings = DEFAULTS, progress: Callable[[int, int, str], None] = lambda *_: None) -> Result:
    """Fetch + validate + evaluate. progress(done, total, label) is called after every finished step."""
    total = 1 + 3 * 2 + 1 + EVALUATE_STEPS
    done = 0

    def step(label: str) -> None:
        nonlocal done
        done += 1
        progress(done, total, label)

    def abort(reason: str) -> Result:
        return Result(verdict=WAIT, reasons=[reason, "analýza přerušena – signál se z neúplných dat negeneruje"],
                      completed=done, total=total, aborted=True)

    step(f"Instrument {inst.name}")
    frames = {}
    for interval in ("5min", "15min", "1h"):
        try:
            raw = provider.bars(inst.symbol, interval, FETCH)
        except DataError as e:
            return abort(str(e))
        step(f"Data {interval} stažena")
        bars, problem = prepare(raw, interval, now, NEED)
        if problem:
            return abort(problem)
        frames[interval] = bars
        step(f"Data {interval} ověřena")
    events = None
    if calendar is not None:
        try:
            events = calendar.events()
        except CalendarError:
            events = None  # evaluate() fails closed on None
    step("Kalendář zpráv")
    r = evaluate(inst, frames["5min"], frames["15min"], frames["1h"], events, spread, now, cfg, tick=step)
    r.completed, r.total = done, total
    return r

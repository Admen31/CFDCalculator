"""Signal analysis v2.1. Pure functions: no Qt, no clock, no network (those are injected).

Outcomes
  * BUY / SELL  - the instrument's profile indicators agree with the 1h trend and every safety filter passes.
  * WAIT        - a legitimate "no trade": no trend, indicators disagree, or a safety filter blocks.
  * NO DATA     - not enough reliable information (missing/stale prices, calendar unavailable, required
                  indicator unavailable, symbol not mapped). Never a trading signal.
  * ERROR       - technical failure (unexpected exception, broken indicator).

Rules
  * Trend: 1h EMA20 vs EMA50 and close vs EMA50 must point one way.
  * Voters (5m/15m): EMA 20/50, RSI, MACD and, where the data source has volume, VWAP and Volume. Each market
    profile lists the voters that apply to it; a voter that does not apply or is unavailable never counts as a
    vote against. BUY/SELL needs EMA 20/50 for the trend, at least max(2, 60 % of the usable voters) for it
    and none against.
  * Safety filters (any one -> WAIT): RSI extreme, ATR regime, room to support/resistance, economic news,
    spread vs stop distance, market time limit (per profile), valid stop-loss.
  * SL = 1.5 x ATR(15m), TP = 2R. Levels are Decimal, SL rounded away from price, TP towards entry.
Indicator calculations are unchanged from v2.0 (the v2.0 decision rules are frozen in legacy.py).
"""
from __future__ import annotations

import math
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

BUY, SELL, WAIT, NO_DATA, ERROR = "BUY", "SELL", "WAIT", "NO DATA", "ERROR"
MODULES = ("ema", "rsi", "macd", "vwap", "volume", "atr", "sr", "news")
VOTERS = ("ema", "rsi", "macd", "vwap", "volume")
TITLES = {"ema": "EMA 20/50", "rsi": "RSI", "macd": "MACD", "vwap": "VWAP", "volume": "Volume", "atr": "ATR",
          "sr": "Support/Resistance", "news": "Fundamenty"}


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    voters: tuple[str, ...]                          # voting indicators that apply to this market
    cutoff: time                                      # default evening limit, local time (Settings can override)
    session: tuple[str, time, time] | None = None     # exchange time zone, open, close; None = 24 h on weekdays
    min_share: float = 0.6                            # share of usable voters that must agree


PROFILES = {
    # US stocks: regular session 9:30-16:00 New York; evening limit 15 min before the 22:00 Prague close
    "stock": Profile("stock", "Akcie CFD", VOTERS, time(21, 45), ("America/New_York", time(9, 30), time(16, 0))),
    "index": Profile("index", "Indexy", VOTERS, time(21, 45)),
    # spot FX and metals/energy from Twelve Data carry no volume: VWAP and Volume do not apply
    "forex": Profile("forex", "Forex", ("ema", "rsi", "macd"), time(21, 0)),
    "commodity": Profile("commodity", "Komodity", ("ema", "rsi", "macd"), time(21, 0)),
}


@dataclass(frozen=True)
class Settings:
    cutoff: time = time(21, 0)        # v2.0 global evening limit (used by legacy.py)
    tz: str = "Europe/Prague"
    min_minutes_left: int = 60
    news_before_min: int = 60         # block this long before a high-impact event...
    news_after_min: int = 30          # ...and this long after it
    cutoffs: tuple[tuple[str, time], ...] = ()   # per-market evening limits, e.g. (("stock", time(21, 45)),)

    def cutoff_for(self, kind: str) -> time:
        return dict(self.cutoffs).get(kind, PROFILES[kind].cutoff)


DEFAULTS = Settings()


@dataclass
class Module:
    key: str
    state: str = "na"                 # bull | bear | neutral | block | na (unavailable) | off (not used) | error
    value: str = "–"
    note: str = ""
    score: int = 0                    # +1 bull vote, -1 bear vote, 0 none
    blocks: frozenset = frozenset()   # directions this module forbids
    stance: str = ""                  # role in the decision: pro / proti / neutrální / nedostupné / nepoužito / ...


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
    summary: str = ""                   # the one decisive reason
    profile: str = ""
    direction: str | None = None        # trend direction the indicators were judged against
    counts: dict[str, int] = field(default_factory=dict)   # pro / proti / neutrální / nedostupné / nepoužito
    filters: list[tuple[str, str, str]] = field(default_factory=list)   # (filter, ok|fail|na, detail)

    @property
    def is_signal(self) -> bool:
        return self.verdict in (BUY, SELL) and self.sl is not None and self.tp is not None


def _q(x: float, decimals: int, rounding: str) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-decimals), rounding=rounding)


def _fmt(x: float | None, d: int) -> str:
    return "–" if x is None else f"{x:.{d}f}"


def cutoff_utc(now: datetime, cfg: Settings, cutoff: time | None = None) -> datetime:
    local = now.astimezone(ZoneInfo(cfg.tz))
    return datetime.combine(local.date(), cutoff or cfg.cutoff, ZoneInfo(cfg.tz)).astimezone(timezone.utc)


def market_end(inst: Instrument, now: datetime, cfg: Settings) -> tuple[datetime | None, str]:
    """End of today's trading window for the instrument (evening limit, or the exchange close if earlier).
    None with a reason when the market is closed now."""
    prof = PROFILES[inst.kind]
    end = cutoff_utc(now, cfg, cfg.cutoff_for(inst.kind))
    if prof.session:
        tz, open_, close = prof.session
        local = now.astimezone(ZoneInfo(tz))
        if local.weekday() >= 5:
            return None, "burza je o víkendu zavřená"
        start = datetime.combine(local.date(), open_, ZoneInfo(tz)).astimezone(timezone.utc)
        stop = datetime.combine(local.date(), close, ZoneInfo(tz)).astimezone(timezone.utc)
        if now < start:
            return None, f"burza otevírá v {start.astimezone(ZoneInfo(cfg.tz)):%H:%M}"
        if now >= stop:
            return None, "burza je dnes už zavřená"
        end = min(end, stop)
    return end, ""


def session_open(inst: Instrument, now: datetime) -> datetime | None:
    """Start of today's exchange session (UTC) for markets with trading hours, else None."""
    prof = PROFILES[inst.kind]
    if not prof.session:
        return None
    tz, open_, _ = prof.session
    return datetime.combine(now.astimezone(ZoneInfo(tz)).date(), open_, ZoneInfo(tz)).astimezone(timezone.utc)


def news_window(events: list[Event], currencies: tuple[str, ...], now: datetime, cfg: Settings, end: datetime):
    """(blocking high-impact events, later high-impact events before `end`) for the given currencies."""
    high = [e for e in events if e.impact.lower() == "high" and e.currency in currencies]
    lo, hi = now - timedelta(minutes=cfg.news_after_min), now + timedelta(minutes=cfg.news_before_min)
    return [e for e in high if lo <= e.time <= hi], [e for e in high if hi < e.time <= end]


# ---------------------------------------------------------------- indicator modules (same maths as v2.0)

def _ema(c5, c15, d) -> Module:
    m = Module("ema")
    e20, e50, f5 = ind.ema(c15, 20)[-1], ind.ema(c15, 50)[-1], ind.ema(c5, 20)[-1]
    m.value = f"15m {_fmt(e20, d)} / {_fmt(e50, d)}"
    close = c5[-1]
    if None in (e20, e50, f5):
        m.state, m.note = "na", "málo dat pro EMA"
    elif e20 > e50 and close > f5:
        m.state, m.score, m.note = "bull", 1, "EMA20 nad EMA50 (15m), cena nad EMA20 (5m)"
    elif e20 < e50 and close < f5:
        m.state, m.score, m.note = "bear", -1, "EMA20 pod EMA50 (15m), cena pod EMA20 (5m)"
    else:
        m.state, m.note = "neutral", "EMA bez shody 15m a 5m"
    return m


def _rsi(c5, d) -> Module:
    m = Module("rsi")
    v = ind.rsi(c5)[-1]
    m.value = _fmt(v, 1)
    if v is None:
        m.state, m.note = "na", "málo dat pro RSI"
    elif v >= 70:
        m.state, m.blocks, m.note = "block", frozenset({BUY}), "překoupeno – nekupovat"
    elif v <= 30:
        m.state, m.blocks, m.note = "block", frozenset({SELL}), "přeprodáno – neprodávat"
    elif v > 50:
        m.state, m.score, m.note = "bull", 1, "momentum nad 50"
    elif v < 50:
        m.state, m.score, m.note = "bear", -1, "momentum pod 50"
    else:
        m.state, m.note = "neutral", "RSI přesně 50"
    return m


def _macd(c5, d) -> Module:
    m = Module("macd")
    v = ind.macd(c5)[2][-1]
    m.value = _fmt(v, d)
    if v is None:
        m.state, m.note = "na", "málo dat pro MACD"
    else:
        m.state, m.score = ("bull", 1) if v > 0 else ("bear", -1) if v < 0 else ("neutral", 0)
        m.note = ("MACD nad signální linií" if v > 0 else "MACD pod signální linií" if v < 0
                  else "MACD na signální linii")
    return m


def _has_volume(m5) -> bool:
    return all(b.v is not None for b in m5[-21:]) and sum(b.v for b in m5[-21:]) > 0


def _vwap(m5, d) -> Module:
    m = Module("vwap")
    if not _has_volume(m5):
        m.note = "zdroj dat nemá objemy – indikátor nedostupný (nepočítá se jako hlas proti)"
        return m
    today = [b for b in m5 if b.t.date() == m5[-1].t.date()]
    if any(b.v is None for b in today):
        m.note = "dnešní objemy nejsou úplné – VWAP nedostupný (nepočítá se jako hlas proti)"
        return m
    vw = ind.vwap([(b.h + b.l + b.c) / 3 for b in today], [b.v for b in today])
    close = m5[-1].c
    if vw is None:
        m.note = "dnes zatím bez objemu"
        return m
    m.value = _fmt(vw, d)
    m.state, m.score = ("bull", 1) if close > vw else ("bear", -1) if close < vw else ("neutral", 0)
    m.note = "cena nad VWAP" if close > vw else "cena pod VWAP" if close < vw else "cena na VWAP"
    return m


def _volume(m5, d) -> Module:
    m = Module("volume")
    if not _has_volume(m5):
        m.note = "zdroj dat nemá objemy – indikátor nedostupný (nepočítá se jako hlas proti)"
        return m
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
    return m


def _atr(m5, m15, d) -> tuple[Module, float | None]:
    m = Module("atr")
    c5, c15 = [b.c for b in m5], [b.c for b in m15]
    a15 = ind.atr([b.h for b in m15], [b.l for b in m15], c15)[-1]
    a5 = ind.atr([b.h for b in m5], [b.l for b in m5], c5)
    recent = [x for x in a5[-50:] if x is not None]
    regime = a5[-1] / (sum(recent) / len(recent)) if a5[-1] and recent else None
    m.value = f"15m {_fmt(a15, d)}"
    if a15 is None or regime is None or a15 <= 0:
        m.state, m.note = "na", "ATR nelze spočítat"
        return m, None
    if regime < 0.5:
        m.state, m.blocks, m.note = "block", frozenset({BUY, SELL}), f"trh spí (ATR 5m {regime:.2f}× průměru)"
    elif regime > 2.5:
        m.state, m.blocks, m.note = "block", frozenset({BUY, SELL}), f"extrémní volatilita ({regime:.2f}×)"
    else:
        m.state, m.note = "neutral", f"volatilita v normě ({regime:.2f}× průměru)"
    return m, a15


def _sr(m15, close, sl_dist, d) -> Module:
    m = Module("sr")
    res, sup = ind.pivots([b.h for b in m15[:-3]], [b.l for b in m15[:-3]])
    above = min((x for x in res if x > close), default=None)
    below = max((x for x in sup if x < close), default=None)
    m.value = f"S {_fmt(below, d)} | R {_fmt(above, d)}"
    if not sl_dist:
        m.state, m.note = "na", "bez ATR nelze posoudit prostor k cíli"
        return m
    blocks, notes = set(), []
    if above is not None and above - close < TP_R * sl_dist:
        blocks.add(BUY)
        notes.append("rezistence blíž než cíl – BUY nemá prostor")
    if below is not None and close - below < TP_R * sl_dist:
        blocks.add(SELL)
        notes.append("support blíž než cíl – SELL nemá prostor")
    m.state = "block" if blocks else "neutral"
    m.blocks, m.note = frozenset(blocks), "; ".join(notes) or "dost prostoru k cíli"
    return m


def _news(events, inst, now, cfg, end) -> Module:
    m = Module("news")
    if events is None:
        m.value, m.note = "bez dat", "kalendář ekonomických zpráv nedostupný"
        return m
    blocking, later = news_window(events, inst.currencies, now, cfg, end or now)
    if blocking:
        e = blocking[0]
        m.state, m.blocks = "block", frozenset({BUY, SELL})
        m.value, m.note = f"{e.currency} {e.time:%H:%M} UTC", f"důležitá zpráva: {e.title}"
    else:
        m.state, m.value = "neutral", "klid"
        m.note = ("později dnes: " + ", ".join(f"{e.currency} {e.title} {e.time:%H:%M} UTC" for e in later[:3])
                  if later else "žádná důležitá zpráva v okně")
    return m


def _safe(key: str, fn, *args):
    """One broken indicator becomes an ERROR module instead of crashing the analysis."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 - reported as a technical error in the result
        m = Module(key, "error", "chyba", f"technická chyba: {type(e).__name__}: {e}")
        return (m, None) if key == "atr" else m


# ---------------------------------------------------------------- decision

def evaluate(inst: Instrument, m5: list[Bar], m15: list[Bar], h1: list[Bar], events: list[Event] | None,
             spread: float, now: datetime, cfg: Settings = DEFAULTS,
             tick: Callable[[str], None] = lambda _: None) -> Result:
    """Decide on validated CLOSED bars. `events=None` means the calendar is unavailable (-> NO DATA).
    Calls tick() after each of the 12 steps."""
    prof = PROFILES[inst.kind]
    d = inst.decimals
    r = Result(data_time=m5[-1].t + timedelta(minutes=5), profile=prof.name)
    mods = r.modules
    c5, c15 = [b.c for b in m5], [b.c for b in m15]
    close = c5[-1]
    end, closed_reason = market_end(inst, now, cfg)

    for key, fn, args, label in (("ema", _ema, (c5, c15, d), "EMA 20/50"), ("rsi", _rsi, (c5, d), "RSI"),
                                 ("macd", _macd, (c5, d), "MACD"), ("vwap", _vwap, (m5, d), "VWAP"),
                                 ("volume", _volume, (m5, d), "Volume")):
        if key in prof.voters:
            mods[key] = _safe(key, fn, *args)
        else:
            mods[key] = Module(key, "off", "–", f"v profilu {prof.name} se nepoužívá (zdroj nemá objemy)")
        tick(label)
    mods["atr"], a15 = _safe("atr", _atr, m5, m15, d)
    tick("ATR")
    sl_dist = SL_ATR * a15 if a15 else None
    mods["sr"] = _safe("sr", _sr, m15, close, sl_dist, d)
    tick("Support/Resistance")
    mods["news"] = _safe("news", _news, events, inst, now, cfg, end)
    tick("Fundamentální události")

    ch = [b.c for b in h1]
    try:
        t20, t50 = ind.ema(ch, 20)[-1], ind.ema(ch, 50)[-1]
        trend_err = None
    except Exception as e:  # noqa: BLE001
        t20 = t50 = None
        trend_err = f"{type(e).__name__}: {e}"
    trend = None
    if t20 is not None and t50 is not None:
        trend = BUY if t20 > t50 and ch[-1] > t50 else SELL if t20 < t50 and ch[-1] < t50 else None
    r.trend = {BUY: "rostoucí", SELL: "klesající", None: "bez trendu"}[trend]
    tick("Trend 1h")

    # ---- can we decide at all?  errors -> ERROR, missing required information -> NO DATA
    required = [k for k in ("ema", "rsi", "macd", "atr", "news")]
    errors = [f"{TITLES[k]}: {mods[k].note}" for k in MODULES if mods[k].state == "error"]
    if trend_err:
        errors.append(f"Trend 1h: technická chyba {trend_err}")
    missing = [f"{TITLES[k]}: {mods[k].note}" for k in required if mods[k].state == "na"]
    if t20 is None or t50 is None:
        missing.append("Trend 1h: málo hodinových dat")
    usable = [k for k in prof.voters if mods[k].state in ("bull", "bear", "neutral", "block")]
    if len(usable) < 3:
        missing.append(f"použitelné jsou jen {len(usable)} hlasující indikátory (potřeba aspoň 3)")
    left = (end - now).total_seconds() / 60 if end else 0.0
    tick("Spread")
    tick("Časový limit")

    direction = trend
    r.direction = direction
    sign = 1 if direction == BUY else -1 if direction == SELL else 0
    pro = [k for k in usable if sign and mods[k].score == sign]
    proti = [k for k in usable if sign and mods[k].score == -sign]
    neutral = [k for k in usable if k not in pro and k not in proti]
    if not sign:  # no direction: report the raw bull/bear split
        pro = [k for k in usable if mods[k].score == 1]
        proti = [k for k in usable if mods[k].score == -1]
        neutral = [k for k in usable if mods[k].score == 0]
    na = [k for k in prof.voters if mods[k].state in ("na", "error")]
    off = [k for k in VOTERS if mods[k].state == "off"]
    r.counts = {"pro": len(pro), "proti": len(proti), "neutrální": len(neutral), "nedostupné": len(na),
                "nepoužito": len(off)}
    for k in VOTERS:
        m = mods[k]
        m.stance = ("nepoužito" if m.state == "off" else "chyba" if m.state == "error" else
                    "nedostupné" if m.state == "na" else
                    ("pro" if k in pro else "proti" if k in proti else "neutrální") if sign else
                    ("býčí" if k in pro else "medvědí" if k in proti else "neutrální"))
    for k in ("atr", "sr", "news"):
        m = mods[k]
        m.stance = ("chyba" if m.state == "error" else "nedostupné" if m.state == "na" else
                    "blokuje" if (direction in m.blocks if direction else m.blocks >= {BUY, SELL}) else "OK")

    need = max(2, math.ceil(prof.min_share * len(usable)))
    f = r.filters
    f.append(("Aktuální data", "ok", f"poslední uzavřená svíčka 5m {r.data_time:%d.%m. %H:%M} UTC"))
    f.append(("Trend 1h", "ok" if trend else "fail" if t20 is not None else "na", f"trend {r.trend}"))
    if sign:
        agree_ok = len(pro) >= need and not proti and "ema" in pro
        why = (f"{len(pro)} pro, {len(proti)} proti, {len(neutral)} neutrální; potřeba ≥ {need} pro, 0 proti"
               + ("" if "ema" in pro else " a EMA 20/50 ve směru trendu"))
        f.append(("Shoda indikátorů", "ok" if agree_ok else "fail", why))
        for key, name in (("rsi", "RSI extrém"), ("atr", "Volatilita (ATR)"), ("sr", "Prostor k cíli"),
                          ("news", "Ekonomické zprávy")):
            m = mods[key]
            status = "na" if m.state in ("na", "error") else "fail" if direction in m.blocks else "ok"
            f.append((name, status, m.note))
    else:
        f.append(("Shoda indikátorů", "na", f"bez směru trendu ({len(pro)} býčí, {len(proti)} medvědí)"))
        for name in ("RSI extrém", "Volatilita (ATR)", "Prostor k cíli", "Ekonomické zprávy"):
            f.append((name, "na", "nehodnoceno – chybí směr trendu"))
    spread_ok = bool(sl_dist) and spread > 0 and spread <= MAX_SPREAD_OF_SL * sl_dist
    f.append(("Spread", "ok" if spread_ok else "na" if not sl_dist else "fail",
              f"spread {spread:g} vs. max {MAX_SPREAD_OF_SL:.0%} stop-lossu" if spread > 0
              else "spread není zadán"))
    time_ok = end is not None and left >= cfg.min_minutes_left
    time_detail = (closed_reason if end is None else
                   f"do konce obchodování ({end.astimezone(ZoneInfo(cfg.tz)):%H:%M}) zbývá {max(left, 0):.0f} min,"
                   f" potřeba {cfg.min_minutes_left}")
    f.append(("Časový limit", "ok" if time_ok else "fail", time_detail))
    sl_ok = bool(sl_dist) and math.isfinite(sl_dist) and sl_dist > 0
    f.append(("Stop-loss", "ok" if sl_ok else "na", f"SL = {SL_ATR} × ATR 15m" if sl_ok else "nelze spočítat"))
    tick("Rozhodnutí")

    if errors:
        r.verdict, r.reasons = ERROR, errors
    elif missing:
        r.verdict, r.reasons = NO_DATA, missing
    elif not direction:
        r.verdict, r.reasons = WAIT, ["1h graf je bez jasného trendu"]
    else:
        failed = [f"{name}: {detail}" for name, status, detail in f if status != "ok"]
        if failed:
            r.verdict, r.reasons = WAIT, failed
        else:
            r.verdict, r.sl_dist = direction, sl_dist
            r.entry = _q(close, d, ROUND_HALF_EVEN)
            if direction == BUY:
                r.sl, r.tp = _q(close - sl_dist, d, ROUND_FLOOR), _q(close + TP_R * sl_dist, d, ROUND_FLOOR)
            else:
                r.sl, r.tp = _q(close + sl_dist, d, ROUND_CEILING), _q(close - TP_R * sl_dist, d, ROUND_CEILING)
            r.reasons = [f"trend 1h {r.trend}, {len(pro)} z {len(usable)} použitelných indikátorů pro, 0 proti, "
                         f"všechny bezpečnostní filtry prošly"]
    r.summary = r.reasons[0]
    return r


EVALUATE_STEPS = 12


def run_analysis(inst: Instrument, provider: Provider, calendar: Calendar | None, spread: float, now: datetime,
                 cfg: Settings = DEFAULTS, progress: Callable[[int, int, str], None] = lambda *_: None,
                 cancelled: Callable[[], bool] = lambda: False) -> Result:
    """Fetch + validate + evaluate. progress(done, total, label) is called after every finished step;
    `cancelled()` is checked between steps (a running HTTP request finishes or times out first)."""
    total = 1 + 3 * 2 + 1 + EVALUATE_STEPS
    done = 0
    prof = PROFILES[inst.kind]

    def step(label: str) -> None:
        nonlocal done
        done += 1
        progress(done, total, label)

    def stop(verdict: str, reason: str) -> Result:
        extra = "signál se z neúplných dat negeneruje" if verdict != WAIT else "bez analýzy, API se nevolalo"
        return Result(verdict=verdict, reasons=[reason, extra], summary=reason, completed=done, total=total,
                      aborted=True, profile=prof.name)

    step(f"Instrument {inst.name}")
    if not inst.td_verified:
        return stop(NO_DATA, f"{inst.name}: Twelve Data pod symbolem {inst.symbol} neuvádí tento instrument "
                             f"(mapování neověřeno)")
    end, closed_reason = market_end(inst, now, cfg)
    if end is None:
        return stop(WAIT, f"trh je zavřený – {closed_reason}")
    frames = {}
    for interval in ("5min", "15min", "1h"):
        if cancelled():
            return stop(NO_DATA, "analýza zrušena")
        try:
            raw = provider.bars(inst.symbol, interval, FETCH)
        except DataError as e:
            return stop(NO_DATA, str(e))
        except Exception as e:  # noqa: BLE001 - unexpected failure is a technical error, never a signal
            return stop(ERROR, f"technická chyba při stahování {interval}: {type(e).__name__}: {e}")
        step(f"Data {interval} stažena")
        bars, problem = prepare(raw, interval, now, NEED, session_open(inst, now))
        if problem:
            return stop(NO_DATA, problem)
        frames[interval] = bars
        step(f"Data {interval} ověřena")
    if cancelled():
        return stop(NO_DATA, "analýza zrušena")
    events = None
    if calendar is not None:
        try:
            events = calendar.events()
        except CalendarError:
            events = None  # evaluate() reports NO DATA
    step("Kalendář zpráv")
    try:
        r = evaluate(inst, frames["5min"], frames["15min"], frames["1h"], events, spread, now, cfg, tick=step)
    except Exception as e:  # noqa: BLE001
        return stop(ERROR, f"technická chyba vyhodnocení: {type(e).__name__}: {e}")
    r.completed, r.total = done, total
    return r

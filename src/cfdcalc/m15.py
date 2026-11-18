"""v2.8 M15 signal: ONE timeframe (15 minutes), ONE data request, no 5m / 1h confirmation.

Pure logic (no Qt). The window runs it in worker threads.

Direction (BUY / SELL / NEUTRAL / NO DATA)
  Computed ONLY from CLOSED 15-minute bars, so it changes at most once per 15 minutes. Weighted votes:
    close vs EMA 200 (1.5), EMA 20 vs EMA 50 (1.0), slope of EMA 50 over 8 bars (0.75), MACD histogram (1.0),
    RSI 14 above 55 / below 45 (0.75), swing structure HH+HL / LH+LL (1.0).
  score = sum(vote x weight) / sum(weight of the available votes); |score| >= 0.35 -> BUY / SELL, else NEUTRAL.
  Less than 60 % of the weight available, invalid / stale / too few bars, or a closed market -> NO DATA.
  Direction is a description of the market, never an order.

Trade levels (VSTUP / TP / SL) are shown ONLY for a confirmed entry. All checks must pass:
    trend (close vs EMA 200 and EMA 20 vs EMA 50 agree with the side), RSI not extreme (BUY <= 70, SELL >= 30),
    price not stretched (|price - EMA 20| <= 1 x ATR), room to the nearest swing level >= 1R, spread entered and
    <= 15 % of the SL distance, ATR >= 3 ticks, enough time to the market's evening limit, no high-impact news,
    exact (not reference) data.
  VSTUP = the newest price from the last request (the forming 15m bar), SL = VSTUP -/+ 1.5 x ATR14(M15),
  TP = 2R. Decimal, SL rounded away from the price, TP towards it.

Data (Feed)
  One 15min series per instrument and source. A request is made only when (a) nothing is cached, (b) a new 15m bar
  has closed since the last request, or (c) the entry price is older than PRICE_TTL and the caller wants a fresh
  price (a click). Later requests ask only for the newest bars and merge them. One lock per series: two callers
  never download the same thing at once; the second one uses the first one's result.
"""
from __future__ import annotations

import math
import threading
import time as clock
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_EVEN, Decimal
from typing import Callable

from . import indicators as ind
from .analysis import DEFAULTS, Settings, market_end, news_window, session_open
from .data import KIND_TEXT, NEXT_STEP, Bar, CachedProvider, DataError, prepare
from .instruments import PLANS, TWELVE, Instrument, Source, plan_ok
from .instruments import sources as sources_of

INTERVAL = "15min"
STEP = timedelta(minutes=15)
FETCH = 400                       # bars of a full download (one request; EMA 200 needs a long warm-up)
NEED = 260                        # closed bars required (Coinbase returns at most 300 per request)
PRICE_TTL = timedelta(seconds=60)  # a click within this time reuses the last price: same result, no request
SETTLE = timedelta(seconds=20)    # a bar is treated as final this long after it closed (provider delay)
SL_ATR, TP_R = 1.5, 2.0
MAX_SPREAD_OF_SL = 0.15
THRESHOLD, MIN_QUALITY = 0.35, 0.6
RSI_HIGH, RSI_LOW = 70.0, 30.0
MAX_STRETCH_ATR = 1.0
MIN_ROOM_R = 1.0

BUY, SELL, NEUTRAL, NO_DATA = "BUY", "SELL", "NEUTRAL", "NO DATA"
WEIGHTS = {"ema200": 1.5, "ema_stack": 1.0, "slope": 0.75, "macd": 1.0, "rsi": 0.75, "structure": 1.0}
NAMES = {"ema200": "Cena vs EMA 200", "ema_stack": "EMA 20 vs EMA 50", "slope": "Sklon EMA 50 (8 svíček)",
         "macd": "MACD histogram", "rsi": "RSI 14", "structure": "Struktura swingů"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def period_start(now: datetime) -> datetime:
    """Open time of the 15m bar that is forming at `now`."""
    s = STEP.total_seconds()
    return datetime.fromtimestamp(now.timestamp() // s * s, timezone.utc)


# ---------------------------------------------------------------- indicators + direction (closed bars only)

@dataclass(frozen=True)
class Factor:
    key: str
    vote: int | None          # +1 bull, -1 bear, 0 neutral, None unavailable
    weight: float
    detail: str

    @property
    def name(self) -> str:
        return NAMES[self.key]


def _sign(x: float, dead: float = 0.0) -> int:
    return 0 if abs(x) <= dead else (1 if x > 0 else -1)


def compute(bars: list[Bar]) -> dict:
    """Indicator values at the last closed bar (all from 15m bars). None = not computable."""
    c = [b.c for b in bars]
    h = [b.h for b in bars]
    lo = [b.l for b in bars]
    e20, e50, e200 = ind.ema(c, 20), ind.ema(c, 50), ind.ema(c, 200)
    line, signal, hist = ind.macd(c)
    rsi = ind.rsi(c)
    atr = ind.atr(h, lo, c)
    tail = bars[-120:]
    res, sup = ind.pivots([b.h for b in tail], [b.l for b in tail], 3)
    return {"close": c[-1], "ema20": e20[-1], "ema50": e50[-1], "ema200": e200[-1],
            "ema50_prev": e50[-9] if len(e50) >= 9 else None, "rsi": rsi[-1], "macd": line[-1],
            "macd_signal": signal[-1], "hist": hist[-1], "atr": atr[-1], "highs": res, "lows": sup}


def factors(x: dict) -> list[Factor]:
    atr = x["atr"]
    out = []

    def add(key, vote, detail):
        out.append(Factor(key, vote, WEIGHTS[key], detail))

    ok = atr is not None and math.isfinite(atr) and atr > 0
    if ok and x["ema200"] is not None:
        add("ema200", _sign(x["close"] - x["ema200"], 0.1 * atr), f"cena {x['close']:.6g}, EMA200 {x['ema200']:.6g}")
    else:
        add("ema200", None, "EMA 200 nelze spočítat")
    if ok and x["ema20"] is not None and x["ema50"] is not None:
        add("ema_stack", _sign(x["ema20"] - x["ema50"], 0.05 * atr), f"EMA20 {x['ema20']:.6g}, EMA50 {x['ema50']:.6g}")
    else:
        add("ema_stack", None, "EMA 20/50 nelze spočítat")
    if ok and x["ema50"] is not None and x["ema50_prev"] is not None:
        d = x["ema50"] - x["ema50_prev"]
        add("slope", _sign(d, 0.1 * atr), f"změna EMA50 {d:+.6g} za 8 svíček")
    else:
        add("slope", None, "sklon EMA 50 nelze spočítat")
    if x["hist"] is not None:
        add("macd", _sign(x["hist"]), f"histogram {x['hist']:+.6g}")
    else:
        add("macd", None, "MACD nelze spočítat")
    if x["rsi"] is not None:
        r = x["rsi"]
        add("rsi", 1 if r > 55 else -1 if r < 45 else 0, f"RSI {r:.1f}")
    else:
        add("rsi", None, "RSI nelze spočítat")
    hi, lw = x["highs"], x["lows"]
    if len(hi) >= 2 and len(lw) >= 2:
        up = hi[-1] > hi[-2] and lw[-1] > lw[-2]
        down = hi[-1] < hi[-2] and lw[-1] < lw[-2]
        add("structure", 1 if up else -1 if down else 0,
            "vyšší maxima i minima" if up else "nižší maxima i minima" if down else "smíšená struktura")
    else:
        add("structure", None, "málo swingů")
    return out


def direction(fs: list[Factor], threshold: float = THRESHOLD) -> tuple[str, float, float]:
    """(side, score -1..1, quality 0..1) from the votes."""
    total = sum(f.weight for f in fs)
    avail = [f for f in fs if f.vote is not None]
    w = sum(f.weight for f in avail)
    quality = w / total if total else 0.0
    if quality < MIN_QUALITY or w == 0:
        return NO_DATA, 0.0, quality
    score = sum(f.vote * f.weight for f in avail) / w
    return (BUY if score >= threshold else SELL if score <= -threshold else NEUTRAL), score, quality


# ---------------------------------------------------------------- the signal

@dataclass
class Signal:
    side: str = NO_DATA
    confirmed: bool = False
    entry: Decimal | None = None
    tp: Decimal | None = None
    sl: Decimal | None = None
    price: float | None = None
    price_time: datetime | None = None     # when the price was obtained (request time) or close of the bar
    live: bool = False                     # price from the forming bar of the last request
    data_time: datetime | None = None      # close time of the last closed 15m bar used
    fetched: datetime | None = None
    score: float = 0.0
    quality: float = 0.0
    factors: list[Factor] = field(default_factory=list)
    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    values: dict = field(default_factory=dict)
    summary: str = ""                      # the decisive reason, one line
    note: str = ""                         # why there are no levels
    source: str = ""
    symbol: str = ""
    reference: str = ""                    # reference product used (direction only)
    bars: int = 0
    from_cache: bool = False               # no request was needed for this result
    errors: list[str] = field(default_factory=list)
    timings: dict = field(default_factory=dict)

    @property
    def levels_ok(self) -> bool:
        return self.confirmed and None not in (self.entry, self.tp, self.sl)


def _q(x: float, d: int, rounding) -> Decimal:
    return Decimal(repr(x)).quantize(Decimal(1).scaleb(-d), rounding=rounding)


def evaluate(inst: Instrument, bars: list[Bar], now: datetime, spread: float, fetched: datetime | None = None,
             cfg: Settings = DEFAULTS, events=None, reference: str = "", threshold: float = THRESHOLD) -> Signal:
    """M15 signal from one 15min series (it may end with the still forming bar). `events` = economic calendar
    (None = unavailable -> no confirmed entry). `fetched` = when the series was downloaded."""
    sig = Signal(fetched=fetched, reference=reference, symbol=inst.symbol)
    fetched = fetched or now
    end, closed_reason = market_end(inst, now, cfg)
    if end is None:
        sig.summary = sig.note = f"trh je zavřený – {closed_reason}"
        return sig
    final = min(now, fetched)                       # a bar is closed only if it was final when downloaded
    closed = [b for b in bars if b.t + STEP <= final]
    forming = bars[-1] if bars and bars[-1].t + STEP > final else None
    good, problem = prepare(closed, INTERVAL, now, NEED, session_open(inst, now))
    sig.bars = len(closed)
    if problem:
        sig.summary = sig.note = problem
        return sig
    sig.data_time = good[-1].t + STEP
    x = compute(good)
    sig.values = {k: v for k, v in x.items() if k not in ("highs", "lows")}
    sig.factors = factors(x)
    sig.side, sig.score, sig.quality = direction(sig.factors, threshold)
    # entry price: the newest one from the request, unless it is old
    if forming is not None and now - fetched <= PRICE_TTL and math.isfinite(forming.c) and forming.c > 0:
        sig.price, sig.price_time, sig.live = forming.c, fetched, True
    else:
        sig.price, sig.price_time = good[-1].c, sig.data_time
    if sig.side == NO_DATA:
        sig.summary = sig.note = f"indikátory M15 nelze spolehlivě spočítat (dostupnost {sig.quality:.0%})"
        return sig
    if sig.side == NEUTRAL:
        sig.summary = f"převaha směru je slabá (skóre {sig.score:+.2f}, hranice ±{threshold:.2f})"
        sig.note = "bez převažujícího směru – vstup, TP a SL se neurčují"
        return sig
    _confirm(sig, inst, x, now, end, spread, cfg, events)
    return sig


def _confirm(sig: Signal, inst: Instrument, x: dict, now: datetime, end: datetime, spread: float, cfg: Settings,
             events):
    side, sign = sig.side, (1 if sig.side == BUY else -1)
    price, atr, d = sig.price, x["atr"], inst.decimals
    tick = 10 ** -d
    dist = SL_ATR * atr
    votes = {f.key: f.vote for f in sig.factors}
    checks = sig.checks
    checks.append(("trend M15", votes.get("ema200") == sign and votes.get("ema_stack") == sign,
                   "cena vůči EMA 200 i EMA 20/50 ve směru" if votes.get("ema200") == sign
                   and votes.get("ema_stack") == sign else "EMA 200 nebo EMA 20/50 nesouhlasí se směrem"))
    r = x["rsi"]
    checks.append(("RSI není extrémní", r <= RSI_HIGH if side == BUY else r >= RSI_LOW, f"RSI {r:.1f}"))
    stretch = abs(price - x["ema20"]) / atr
    checks.append(("cena není daleko od EMA 20", stretch <= MAX_STRETCH_ATR, f"{stretch:.2f} × ATR"))
    if side == BUY:
        level = min((h for h in x["highs"] if h > price), default=None)
    else:
        level = max((lo for lo in x["lows"] if lo < price), default=None)
    room = None if level is None else abs(level - price) / dist
    checks.append(("prostor k nejbližšímu swingu", room is None or room >= MIN_ROOM_R,
                   "žádný swing v cestě" if room is None else f"{room:.2f} R ({level:.{d}f})"))
    checks.append(("volatilita (ATR) nad tickem", dist >= 3 * tick, f"ATR14 {atr:.{d + 1}f}"))
    if spread is None or spread <= 0:
        checks.append(("spread zadán", False, "zadejte spread z Trading 212 (Podrobnosti)"))
    else:
        checks.append(("spread vůči SL", spread <= MAX_SPREAD_OF_SL * dist,
                       f"spread {spread:g} = {spread / dist:.0%} vzdálenosti SL"))
    left = (end - now).total_seconds() / 60
    checks.append(("čas do večerního limitu", left >= cfg.min_minutes_left,
                   f"{left:.0f} min (minimum {cfg.min_minutes_left})"))
    if events is None:
        checks.append(("ekonomický kalendář", False, "kalendář zpráv nedostupný – vstup nelze potvrdit"))
    else:
        block, _later = news_window(events, inst.currencies, now, cfg, end)
        checks.append(("ekonomický kalendář", not block, "bez důležitých zpráv" if not block else
                       "zpráva " + ", ".join(f"{e.currency} {e.title} {e.time.astimezone():%H:%M}" for e in block[:2])))
    checks.append(("přesná data instrumentu", not sig.reference,
                   "přesný zdroj" if not sig.reference else f"referenční data ({sig.reference})"))
    failed = [c for c in checks if not c[1]]
    if failed:
        sig.summary = (f"{side} převažuje, vstup ale není potvrzen – nesplněna podmínka „{failed[0][0]}“ "
                       f"({failed[0][2]})")
        sig.note = "převažující směr, ne obchodní pokyn – vstup nesplňuje podmínky"
        return
    entry = _q(price, d, ROUND_HALF_EVEN)
    e = float(entry)
    if side == BUY:
        sl, tp = _q(e - dist, d, ROUND_FLOOR), _q(e + TP_R * dist, d, ROUND_FLOOR)
    else:
        sl, tp = _q(e + dist, d, ROUND_CEILING), _q(e - TP_R * dist, d, ROUND_CEILING)
    if sl <= 0 or tp <= 0 or sign * (entry - sl) <= 0 or sign * (tp - entry) <= 0:
        sig.summary = sig.note = "TP/SL by byly neplatné"
        return
    sig.entry, sig.sl, sig.tp, sig.confirmed = entry, sl, tp, True
    sig.summary = f"{side}: potvrzený vstup M15 (skóre {sig.score:+.2f}), SL {SL_ATR:g}× ATR, TP {TP_R:g}R"


# ---------------------------------------------------------------- data: one 15min series per instrument

@dataclass
class Series:
    bars: list[Bar]
    fetched: datetime
    source: Source
    provider: str


@dataclass
class Snapshot:
    series: Series | None
    network: bool = False                 # a request was made for this snapshot
    errors: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)


def _unwrap(p):
    return p.provider if isinstance(p, CachedProvider) else p


class Feed:
    """Cache of one 15min series per instrument (per source). Thread safe; see the module docstring."""

    def __init__(self, providers: Callable[[], object], clock_fn: Callable[[], datetime] = utcnow,
                 price_ttl: timedelta = PRICE_TTL):
        self._providers, self.clock, self.price_ttl = providers, clock_fn, price_ttl
        self._series: dict[tuple, Series] = {}
        self._locks: dict[tuple, threading.Lock] = {}
        self._lock = threading.Lock()
        self.requests = 0
        self.last_error: dict[str, tuple[str, str, datetime]] = {}    # symbol -> (kind, message, when)
        self.provider_error = ""

    def clear(self):
        with self._lock:
            self._series.clear()

    def _provider(self, src: Source):
        try:
            p = self._providers()
        except DataError as e:             # e.g. no Twelve Data key: that provider is unavailable, say why
            self.provider_error = str(e)
            return None
        p = p if hasattr(p, "bars") else (p or {}).get(src.provider)
        return _unwrap(p) if p is not None else None

    @staticmethod
    def _key(src: Source) -> tuple:
        return (src.provider, src.symbol, src.exchange or "")

    def cached(self, inst: Instrument, plan: str = "Ultra") -> Series | None:
        for src in sources_of(inst):
            if plan_ok(src, plan):
                s = self._series.get(self._key(src))
                if s:
                    return s
        return None

    def need(self, s: Series | None, now: datetime, want_price: bool) -> str | None:
        """What a request would bring: "full" (nothing cached), "bar" (a new bar closed), "price" (old price)."""
        if s is None or len(s.bars) < NEED:
            return "full"
        start = period_start(now)
        if now >= start + SETTLE and s.fetched < start + SETTLE:
            return "bar"
        if want_price and now - s.fetched > self.price_ttl:
            return "price"
        return None

    def get(self, inst: Instrument, plan: str = "Ultra", want_price: bool = True) -> Snapshot:
        """The instrument's 15min series: from the cache when nothing new can be obtained, else ONE request per
        source tried (exact sources first, then references)."""
        out = Snapshot(None)
        candidates = sources_of(inst)
        if not candidates:
            out.errors.append(f"{inst.name}: symbol není namapován na ověřený zdroj dat")
            out.kinds.append("unmapped")
            return out
        allowed = [s for s in candidates if plan_ok(s, plan)]
        for src in candidates:
            if src not in allowed:
                out.errors.append(f"{src.symbol}: vyžaduje tarif Twelve Data {src.plan} (nastaveno {plan}) – "
                                  "bez dotazu")
                out.kinds.append("plan")
        for src in allowed:
            self.provider_error = ""
            prov = self._provider(src)
            if prov is None:
                out.errors.append(self.provider_error or f"{src.provider}: poskytovatel není nastaven")
                out.kinds.append("auth" if self.provider_error else "unmapped")
                continue
            key = self._key(src)
            with self._lock:
                lock = self._locks.setdefault(key, threading.Lock())
            with lock:                         # one download per series at a time; others wait and reuse it
                now = self.clock()
                s = self._series.get(key)
                need = self.need(s, now, want_price)
                if need is None:
                    out.series = s
                    return out
                try:
                    s = self._download(prov, src, s, need, now)
                except DataError as e:
                    out.errors.append(str(e))
                    out.kinds.append(getattr(e, "kind", "unknown"))
                    self.last_error[inst.symbol] = (getattr(e, "kind", "unknown"), str(e), now)
                    continue
                self._series[key] = s
                self.last_error.pop(inst.symbol, None)
                out.series, out.network = s, True
                return out
        return out

    def _download(self, prov, src: Source, s: Series | None, need: str, now: datetime) -> Series:
        kw = {"exchange": src.exchange} if src.exchange and getattr(prov, "pins_exchange", False) else {}
        name = getattr(prov, "name", src.provider)
        with self._lock:
            self.requests += 1
        if need != "full" and s is not None:
            missing = int((now - s.bars[-1].t) / STEP) + 3
            if missing < NEED // 2:
                fresh = prov.bars(src.symbol, INTERVAL, max(missing, 3), **kw)
                if fresh and fresh[0].t <= s.bars[-1].t:          # overlap: merge, newer values win
                    merged = {b.t: b for b in s.bars}
                    merged.update({b.t: b for b in fresh})
                    bars = sorted(merged.values(), key=lambda b: b.t)[-FETCH:]
                    return Series(bars, now, src, name)
                with self._lock:
                    self.requests += 1
        bars = prov.bars(src.symbol, INTERVAL, FETCH, **kw)
        return Series(sorted(bars, key=lambda b: b.t), now, src, name)


# ---------------------------------------------------------------- service used by the window

class Service:
    """Click -> signal. Serves the cached series when nothing new can be obtained (well under a second), otherwise
    one request. Indicators of a series are computed once (memo by the last closed bar)."""

    def __init__(self, feed: Feed):
        self.feed = feed
        self.events = None                     # economic calendar (list) once loaded; None = unavailable
        self.events_error = "kalendář zpráv zatím nenačten"

    def set_events(self, events, error: str = ""):
        self.events, self.events_error = events, error

    def fresh(self, inst: Instrument, plan: str) -> bool:
        """True when a click needs no request (result available at once)."""
        return self.feed.need(self.feed.cached(inst, plan), self.feed.clock(), True) is None

    def analyze_cached(self, inst: Instrument, spread: float, cfg: Settings = DEFAULTS) -> Signal | None:
        """The signal from the cache WITHOUT waiting for any lock or request (UI thread); None if a request is
        needed first."""
        t0 = clock.perf_counter()
        s = self.feed.cached(inst, cfg.td_plan)
        now = self.feed.clock()
        if self.feed.need(s, now, True) is not None:
            return None
        sig = self._evaluate(inst, s, now, spread, cfg)
        sig.from_cache = True
        sig.timings = {"data": 0.0, "výpočet": 1000 * (clock.perf_counter() - t0)}
        return sig

    def _evaluate(self, inst, s: Series, now, spread, cfg) -> Signal:
        ref = "" if s.source.exact else (s.source.label or s.source.symbol)
        sig = evaluate(inst, s.bars, now, spread, s.fetched, cfg, self.events, ref)
        sig.source = f"{s.provider} · {s.source.symbol}" + (f" ({s.source.exchange})" if s.source.exchange else "")
        if self.events is None and sig.side in (BUY, SELL):
            sig.checks = [(n, ok, (self.events_error if n == "ekonomický kalendář" else d))
                          for n, ok, d in sig.checks]
        return sig

    def analyze(self, inst: Instrument, spread: float, cfg: Settings = DEFAULTS, want_price: bool = True) -> Signal:
        t0 = clock.perf_counter()
        snap = self.feed.get(inst, cfg.td_plan, want_price)
        t1 = clock.perf_counter()
        now = self.feed.clock()
        if snap.series is None:
            sig = Signal(symbol=inst.symbol)
            why = snap.errors[-1] if snap.errors else "žádný zdroj dat není k dispozici"
            if snap.kinds and all(k == "plan" for k in snap.kinds):
                need = min((s.plan for s in sources_of(inst) if s.provider == TWELVE), key=PLANS.index,
                           default="vyšší")
                why = (f"{inst.name}: data pro {inst.symbol} vyžadují tarif Twelve Data {need} (nastaveno "
                       f"{cfg.td_plan}) a jiný ověřený zdroj není. Řešení: vyšší tarif, nebo jiný instrument.")
            sig.summary = sig.note = why
            sig.errors = list(snap.errors)
            sig.timings = {"data": 1000 * (t1 - t0)}
            return sig
        sig = self._evaluate(inst, snap.series, now, spread, cfg)
        sig.from_cache = not snap.network
        sig.errors = list(snap.errors)
        sig.timings = {"data": 1000 * (t1 - t0), "výpočet": 1000 * (clock.perf_counter() - t1)}
        return sig

    def report(self, inst: Instrument, cfg: Settings, has_key: bool, usage: str = "") -> list[str]:
        """Data diagnostics of the instrument for the detail page (no network)."""
        now = self.feed.clock()
        lines = [f"Klíč Twelve Data: {'nastaven' if has_key else 'CHYBÍ – Twelve Data nelze použít (⚙ Nastavení)'}",
                 f"Nastavený tarif Twelve Data: {cfg.td_plan}" + (f" · {usage}" if usage else "")]
        srcs = sources_of(inst)
        if not srcs:
            lines.append("Mapování: instrument nemá ověřený zdroj dat – analýza není možná.")
        for src in srcs:
            what = "přesný zdroj" if src.exact else f"REFERENČNÍ zdroj ({src.label}) – jen směr, bez VSTUP/TP/SL"
            plan = (f"potřebný tarif {src.plan}" + ("" if plan_ok(src, cfg.td_plan) else " – NEDOSTUPNÝ v nastaveném "
                                                    "tarifu, bez dotazu")) if src.provider == TWELVE else "bez klíče"
            lines.append(f"Zdroj {src.provider}: {src.symbol}{' / ' + src.exchange if src.exchange else ''} · {what}"
                         f" · {plan} · interval 15min podporován")
        s = self.feed.cached(inst, cfg.td_plan)
        if s:
            last = s.bars[-1]
            lines.append(f"Cache: {len(s.bars)} svíček M15 z {s.provider}, poslední {last.t:%d.%m. %H:%M} UTC, "
                         f"staženo před {(now - s.fetched).total_seconds():.0f} s")
        else:
            lines.append("Cache: zatím žádná data M15")
        err = self.feed.last_error.get(inst.symbol)
        if err:
            kind, msg, when = err
            lines.append(f"Poslední chyba ({when.astimezone():%H:%M:%S}): {KIND_TEXT.get(kind, kind)}. {msg}")
            if kind in NEXT_STEP and NEXT_STEP[kind] not in msg:
                lines.append(f"Další krok: {NEXT_STEP[kind]}")
        lines.append(f"Kalendář zpráv: {'načten' if self.events is not None else self.events_error}")
        lines.append(f"Požadavky M15 v této relaci: {self.feed.requests}")
        return lines

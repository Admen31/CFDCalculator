"""Market data: Twelve Data REST client, offline synthetic data and candle validation."""
from __future__ import annotations

import json
import math
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from itertools import pairwise
from typing import Callable, Protocol

INTERVALS = {"5min": 5, "15min": 15, "1h": 60}
GRACE = timedelta(minutes=3)  # tolerated delay of the provider after a bar closes


@dataclass(frozen=True)
class Bar:
    t: datetime          # bar OPEN time, UTC
    o: float
    h: float
    l: float  # noqa: E741
    c: float
    v: float | None      # None = provider has no volume (typically forex)


class DataError(Exception):
    """A data problem that prevents analysis. `kind` says what kind of problem it is (never a trading signal):
    not_found, plan, auth, rate_limit, server, connection, timeout, invalid, no_data, unmapped, request, unknown.
    `confirmed` is False when the cause is only guessed from an HTTP status without an explaining response."""

    def __init__(self, message: str, kind: str = "unknown", *, source: str = "", symbol: str = "",
                 interval: str = "", status: int | None = None, provider_message: str = "", confirmed: bool = True):
        super().__init__(message)
        self.kind, self.source, self.symbol, self.interval = kind, source, symbol, interval
        self.status, self.provider_message, self.confirmed = status, provider_message, confirmed


KIND_TEXT = {
    "not_found": "Poskytovatel symbol nenašel",
    "plan": "Instrument není dostupný v aktuálním tarifu API",
    "auth": "API klíč byl odmítnut",
    "rate_limit": "Překročen limit dotazů API",
    "server": "Výpadek na straně poskytovatele",
    "connection": "Chyba připojení",
    "timeout": "Poskytovatel neodpověděl včas (timeout)",
    "invalid": "Neplatná odpověď poskytovatele",
    "no_data": "Poskytovatel nevrátil dostatek historických dat",
    "request": "Poskytovatel odmítl parametry požadavku",
    "unknown": "Příčinu poskytovatel neupřesnil",
}
NEXT_STEP = {
    "not_found": "ověř zápis symbolu (Nastavení → Ověřit dostupnost dat).",
    "plan": "ověř, zda tarif Twelve Data zahrnuje tento instrument a interval.",
    "auth": "zkontroluj API klíč v Nastavení.",
    "rate_limit": "počkej minutu (bezplatný tarif: 8 dotazů/min, 800/den) a spusť znovu.",
    "server": "zkus to znovu za několik minut.",
    "connection": "zkontroluj připojení k internetu.",
    "timeout": "zkus to znovu; při pomalé síti může dotaz trvat déle.",
    "invalid": "spusť Ověřit dostupnost dat a výsledek pošli k analýze.",
    "no_data": "trh může být zavřený nebo symbol nemá data v tomto intervalu.",
    "request": "spusť Ověřit dostupnost dat a výsledek pošli k analýze.",
    "unknown": "ověř dostupnost symbolu a oprávnění API tarifu (Nastavení → Ověřit dostupnost dat).",
}
_PLAN_WORDS = ("plan", "upgrade", "subscription", "pricing", "available starting", "grow", "pro plan")


def classify(status: int | None, body) -> tuple[str, bool, str]:
    """(kind, confirmed, provider message) from an HTTP status and the parsed JSON body (if any).
    The kind is only `confirmed` when the provider's own message supports it."""
    msg = str(body.get("message", "")) if isinstance(body, dict) else ""
    code = body.get("code") if isinstance(body, dict) and isinstance(body.get("code"), int) else status
    m = msg.lower()
    if code == 429 or "api credits" in m or "rate limit" in m:
        return "rate_limit", bool(msg) or code == 429, msg
    if code == 401 or "api key" in m or "apikey" in m:
        return "auth", "key" in m or code == 401, msg
    if any(w in m for w in _PLAN_WORDS):
        return "plan", True, msg
    if code == 403:
        return "plan", False, msg
    if code == 404 or "not found" in m:
        if "symbol" in m and any(w in m for w in ("not found", "invalid", "missing", "specify")):
            return "not_found", True, msg
        if "no data" in m or "data is not available" in m:
            return "no_data", True, msg
        return "unknown", False, msg
    if code == 400:
        return "request", bool(msg), msg
    if code is not None and code >= 500:
        return "server", True, msg
    return "unknown", False, msg


class Provider(Protocol):
    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]: ...


def _num(x) -> float | None:
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


class TwelveData:
    """GET /time_series. The key goes in the Authorization header so it never appears in URLs or logs;
    every message shown to the user is passed through redact()."""

    BASE = "https://api.twelvedata.com"
    name = "Twelve Data"

    MAX_WAIT = 10.0     # seconds a request may wait for a free slot of the per-minute limit

    def __init__(self, api_key: str, timeout: float = 15.0, per_minute: int = 8):
        if not api_key:
            raise DataError("Chybí API klíč Twelve Data (Nastavení).", "auth", source=self.name)
        self._key, self._timeout = api_key, timeout
        self.per_minute = per_minute          # free plan: 8 requests per minute
        self._sent: deque[float] = deque()
        self._lock = threading.Lock()
        self.requests = 0

    def _throttle(self, symbol: str, interval: str):
        """Keep under the plan's per-minute limit: wait briefly for a free slot, otherwise fail with rate_limit
        before Twelve Data has to refuse (and count) the request."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._sent and now - self._sent[0] >= 60:
                    self._sent.popleft()
                if len(self._sent) < self.per_minute:
                    self._sent.append(now)
                    self.requests += 1
                    return
                wait = 60 - (now - self._sent[0])
            if wait > self.MAX_WAIT:
                raise self._error("rate_limit", True, symbol, interval, None,
                                  f"místní ochrana limitu {self.per_minute} dotazů za minutu – volno za {wait:.0f} s")
            time.sleep(wait + 0.05)

    def redact(self, text: str) -> str:
        """Remove the API key (and anything that looks like an apikey parameter) and control characters."""
        text = text.replace(self._key, "***") if self._key else text
        text = re.sub(r"(?i)(apikey[=: ]+)[^&\s\"']+", r"\1***", text)
        text = "".join(ch for ch in text if ch.isprintable())
        return text[:240]

    def _error(self, kind: str, confirmed: bool, symbol: str, interval: str, status: int | None, msg: str):
        from .instruments import BY_SYMBOL
        inst = BY_SYMBOL.get(symbol)
        who = f"{inst.name} ({symbol})" if inst else symbol
        msg = self.redact(msg)
        where = f" pro interval {interval}" if interval else ""
        parts = [f"{who}: Twelve Data neposkytla data{where}."]
        if status:
            parts.append(f"HTTP {status}.")
        parts.append(KIND_TEXT[kind] + ("." if confirmed else " (příčina nepotvrzena odpovědí poskytovatele)."))
        if msg:
            parts.append(f"Odpověď poskytovatele: „{msg}“.")
        parts.append(f"Další krok: {NEXT_STEP[kind]}")
        return DataError(" ".join(parts), kind, source=self.name, symbol=symbol, interval=interval, status=status,
                         provider_message=msg, confirmed=confirmed)

    def _get(self, path: str, params: dict, symbol: str = "", interval: str = "") -> dict:
        self._throttle(symbol, interval)
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"apikey {self._key}",
                                                   "User-Agent": "cfd-signal-calculator"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:  # nosec B310 - fixed https base URL
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8", "replace"))
            except (ValueError, OSError):
                body = None
            kind, confirmed, msg = classify(e.code, body)
            raise self._error(kind, confirmed, symbol, interval, e.code, msg) from None
        except (TimeoutError, socket.timeout):
            raise self._error("timeout", True, symbol, interval, None, "") from None
        except urllib.error.URLError as e:
            kind = "timeout" if isinstance(e.reason, (TimeoutError, socket.timeout)) else "connection"
            raise self._error(kind, True, symbol, interval, None, type(e.reason).__name__) from None
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise self._error("invalid", True, symbol, interval, 200, "odpověď není JSON") from None
        if not isinstance(body, dict):
            raise self._error("invalid", True, symbol, interval, 200, "odpověď není objekt JSON")
        if body.get("status") == "error":
            kind, confirmed, msg = classify(None, body)
            raise self._error(kind, confirmed, symbol, interval, body.get("code") if isinstance(body.get("code"),
                                                                                                int) else 200, msg)
        return body

    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]:
        from .instruments import BY_SYMBOL
        inst = BY_SYMBOL.get(symbol)
        if inst and not inst.td_verified:
            raise DataError(f"symbol {symbol} nemá ověřené mapování na Twelve Data", "unmapped", source=self.name,
                            symbol=symbol, interval=interval)
        params = {"symbol": symbol, "interval": interval, "outputsize": n, "timezone": "UTC", "order": "asc"}
        if inst and inst.exchange:
            params["exchange"] = inst.exchange
        body = self._get("time_series", params, symbol, interval)
        meta = body.get("meta") or {}
        got = str(meta.get("exchange", "")).upper()
        if inst and inst.exchange and got and got != inst.exchange:
            raise DataError(f"Twelve Data vrátila {symbol} z burzy {got}, očekávána {inst.exchange}", "invalid",
                            source=self.name, symbol=symbol, interval=interval)
        returned = str(meta.get("symbol", "")).upper()
        if returned and returned != symbol.upper():   # never accept a different instrument than requested
            raise self._error("invalid", True, symbol, interval, 200, f"vrácen jiný symbol: {returned}")
        out = []
        for v in body.get("values") or []:
            o, h, lo, c = (_num(v.get(k)) for k in ("open", "high", "low", "close"))
            try:
                t = datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
            except (KeyError, ValueError, TypeError):
                raise self._error("invalid", True, symbol, interval, 200,
                                  f"neplatný čas svíčky {str(v.get('datetime'))[:30]}") from None
            if None in (o, h, lo, c):
                raise self._error("invalid", True, symbol, interval, 200, f"chybí cena ve svíčce {v.get('datetime')}")
            out.append(Bar(t, o, h, lo, c, _num(v.get("volume"))))
        if not out:
            raise self._error("no_data", True, symbol, interval, 200, "0 svíček")
        out.sort(key=lambda b: b.t)
        return out

    def exchange_rate(self, base: str, quote: str) -> tuple[Decimal, datetime]:
        """1 `base` in `quote` (e.g. USD -> CZK) from GET /exchange_rate; tries the inverse pair when the direct one is
        not listed. Returns (rate, quote time UTC). Never guesses: any doubt raises DataError."""
        errors = []
        for pair, invert in ((f"{base}/{quote}", False), (f"{quote}/{base}", True)):
            try:
                body = self._get("exchange_rate", {"symbol": pair}, pair)
            except DataError as e:
                errors.append(e)
                if e.kind not in ("not_found", "request", "unknown"):
                    raise
                continue
            got = str(body.get("symbol", "")).upper()
            try:
                rate = Decimal(str(body["rate"]))
                when = datetime.fromtimestamp(int(body["timestamp"]), timezone.utc)
            except (KeyError, ValueError, TypeError, ArithmeticError):
                raise self._error("invalid", True, pair, "", 200, "kurz bez hodnoty nebo času") from None
            if got != pair or not rate.is_finite() or rate <= 0:
                raise self._error("invalid", True, pair, "", 200, f"neplatný kurz {got} {rate}")
            return (1 / rate if invert else rate), when
        raise errors[-1]

    def probe(self, symbol: str, intervals=("5min", "15min", "1h")) -> list[tuple[str, str, str, str]]:
        """Availability check for one symbol: catalogue listing + a 2-bar request per interval + plan usage.
        Returns (check, status ok|fail|info, detail, kind: OK or DataError.kind). Stops at a rate limit.
        Run it in a worker thread."""
        out: list[tuple[str, str, str, str]] = []
        try:
            rows = self._get("symbol_search", {"symbol": symbol, "outputsize": 30}, symbol).get("data") or []
            exact = [r for r in rows if str(r.get("symbol", "")).upper() == symbol.upper()]
            out.append(("Katalog symbolů", "ok" if exact else "fail", "; ".join(
                f"{r.get('instrument_name')} [{r.get('instrument_type')}, {r.get('exchange') or '-'}]"
                for r in exact[:3]) or "symbol v katalogu nenalezen", "OK" if exact else "not_found"))
        except DataError as e:
            out.append(("Katalog symbolů", "fail", str(e), e.kind))
        for interval in intervals:
            try:
                bars = self.bars(symbol, interval, 2)
                out.append((f"Svíčky {interval}", "ok", f"poslední {bars[-1].t:%Y-%m-%d %H:%M} UTC", "OK"))
            except DataError as e:
                out.append((f"Svíčky {interval}", "fail", str(e), e.kind))
                if e.kind == "rate_limit":
                    break
        try:
            u = self._get("api_usage", {})
            out.append(("Tarif API", "info", f"tarif {u.get('plan_category', '?')}, využití "
                                             f"{u.get('current_usage', '?')}/{u.get('plan_limit', '?')} za minutu",
                        ""))
        except DataError as e:
            out.append(("Tarif API", "info", f"nezjištěno ({KIND_TEXT[e.kind].lower()})", ""))
        return out


class CachedProvider:
    """Session cache per (symbol, interval) in front of a provider.

    * no request at all while nothing new can have closed: the series was fetched at least SETTLE after the start
      of the current bar period (so the last bar that can be closed now was already final when it was fetched);
    * otherwise only the newest bars are requested and merged by time (newer values win); without an overlap with
      the cached series the full window is downloaded again;
    * errors are never hidden behind cached data (the analysis then reports NO DATA, as without the cache).
    Freshness is still checked by prepare() on every analysis."""

    SETTLE = timedelta(seconds=20)

    def __init__(self, provider, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.provider, self._clock = provider, clock
        self.name = getattr(provider, "name", "zdroj dat")
        self._store: dict[tuple[str, str], tuple[list[Bar], datetime]] = {}
        self._lock = threading.Lock()
        self.hits = self.partial = self.full = 0

    def clear(self):
        with self._lock:
            self._store.clear()

    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]:
        step = timedelta(minutes=INTERVALS[interval])
        now = self._clock()
        period = datetime.fromtimestamp(now.timestamp() // step.total_seconds() * step.total_seconds(), timezone.utc)
        with self._lock:
            cached = self._store.get((symbol, interval))
        if cached and len(cached[0]) >= n:
            bars, fetched = cached
            if fetched >= period + self.SETTLE:
                with self._lock:
                    self.hits += 1
                return list(bars[-n:])
            missing = int((now - bars[-1].t) / step) + 2
            if missing < n // 2:
                fresh = self.provider.bars(symbol, interval, max(missing, 5))
                if fresh and fresh[0].t <= bars[-1].t:
                    merged = {b.t: b for b in bars}
                    merged.update({b.t: b for b in fresh})
                    out = sorted(merged.values(), key=lambda b: b.t)[-max(n, len(bars)):]
                    with self._lock:
                        self._store[(symbol, interval)] = (out, now)
                        self.partial += 1
                    return out[-n:]
        fresh = self.provider.bars(symbol, interval, n)
        with self._lock:
            self._store[(symbol, interval)] = (list(fresh), now)
            self.full += 1
        return list(fresh)


def synthetic_bars(now: datetime, minutes: int, n: int, drift: float = 0.0, amp: float = 0.0,
                   noise: float = 0.0, seed: int = 1, base: float = 100.0, volume: bool = True) -> list[Bar]:
    """Deterministic price path c(t) = base + drift*(t-now) + amp*sin(t/45) + noise (t in minutes), per bar.

    All timeframes built from the same (drift, amp) describe the same market, so 5m/15m/1h agree.
    """
    rnd = random.Random(seed)
    step = timedelta(minutes=minutes)
    end = now.replace(second=0, microsecond=0)
    end -= timedelta(minutes=end.minute % minutes) if minutes < 60 else timedelta(minutes=end.minute)
    start = end - step * n          # last bar opens at `end` and is still forming
    m_now = (now - datetime(2020, 1, 1, tzinfo=timezone.utc)).total_seconds() / 60
    price = lambda m: base + drift * (m - m_now) + amp * math.sin(m / 45)  # noqa: E731 - ~base at `now`
    out, m0 = [], (start - datetime(2020, 1, 1, tzinfo=timezone.utc)).total_seconds() / 60
    for i in range(n + 1):
        m = m0 + i * minutes
        o, c = price(m), price(m + minutes) + rnd.uniform(-noise, noise)
        wick = abs(drift) * minutes * 0.3 + noise
        out.append(Bar(start + i * step, o, max(o, c) + wick, min(o, c) - wick, c,
                       1000 + rnd.uniform(0, 200) if volume else None))
    return out


class SyntheticData:
    """Offline demo provider: a trend whose direction depends on the symbol, scaled to its typical spread."""
    name = "Offline demo (syntetická data)"

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.clock = clock

    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]:
        from .instruments import BY_SYMBOL
        seed = sum(map(ord, symbol))
        f = BY_SYMBOL[symbol].spread / 0.01 if symbol in BY_SYMBOL else 1.0
        drift = 0.002 * f * (1 if seed % 2 else -1)
        return synthetic_bars(self.clock(), INTERVALS[interval], n, drift=drift, amp=0.1 * f, noise=0.05 * f,
                              seed=seed + INTERVALS[interval], base=100 * f, volume="/" not in symbol)


def prepare(bars: list[Bar], interval: str, now: datetime, need: int,
            opened: datetime | None = None) -> tuple[list[Bar], str | None]:
    """Keep closed bars only and validate them. Returns (bars, problem); a problem means: do not trade.
    `opened` = start of today's exchange session: time while the market was closed does not age the data."""
    step = timedelta(minutes=INTERVALS[interval])
    closed = [b for b in bars if b.t + step <= now]
    if len(closed) < need:
        return closed, f"{interval}: málo uzavřených svíček ({len(closed)}/{need})"
    for a, b in pairwise(closed):
        if b.t <= a.t:
            return closed, f"{interval}: neseřazená nebo duplicitní data"
    for b in closed[-need:]:
        vals = (b.o, b.h, b.l, b.c)
        if not all(math.isfinite(x) and x > 0 for x in vals) or b.h < max(b.o, b.c) or b.l > min(b.o, b.c):
            return closed, f"{interval}: neplatná svíčka {b.t:%d.%m. %H:%M} UTC"
    last_close = closed[-1].t + step
    if now - max(last_close, opened or last_close) > step + GRACE:
        return closed, f"{interval}: zastaralá data – poslední uzavřená svíčka {last_close:%d.%m. %H:%M} UTC"
    return closed[-need:], None

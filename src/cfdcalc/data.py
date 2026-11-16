"""Market data: Twelve Data REST client, offline synthetic data and candle validation."""
from __future__ import annotations

import json
import math
import random
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    pass


class Provider(Protocol):
    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]: ...


def _num(x) -> float | None:
    try:
        return None if x in (None, "") else float(x)
    except (TypeError, ValueError):
        return None


class TwelveData:
    """GET /time_series. The key goes in the Authorization header so it never appears in URLs or logs."""

    BASE = "https://api.twelvedata.com"

    def __init__(self, api_key: str, timeout: float = 15.0):
        if not api_key:
            raise DataError("Chybí API klíč Twelve Data (Nastavení).")
        self._key, self._timeout = api_key, timeout

    def _get(self, path: str, params: dict) -> dict:
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"apikey {self._key}",
                                                   "User-Agent": "cfd-signal-calculator"})
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as r:  # nosec B310 - fixed https base URL
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise DataError(f"Twelve Data HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            raise DataError(f"Twelve Data nedostupné: {type(e).__name__}") from None
        if not isinstance(body, dict) or body.get("status") == "error":
            msg = body.get("message", "neznámá chyba") if isinstance(body, dict) else "neplatná odpověď"
            raise DataError(f"Twelve Data: {msg}")
        return body

    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]:
        body = self._get("time_series", {"symbol": symbol, "interval": interval, "outputsize": n,
                                         "timezone": "UTC", "order": "asc"})
        out = []
        for v in body.get("values") or []:
            o, h, lo, c = (_num(v.get(k)) for k in ("open", "high", "low", "close"))
            try:
                t = datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
            except (KeyError, ValueError):
                raise DataError("Twelve Data: neplatný čas svíčky") from None
            if None in (o, h, lo, c):
                raise DataError(f"Twelve Data: chybí cena ve svíčce {v.get('datetime')}")
            out.append(Bar(t, o, h, lo, c, _num(v.get("volume"))))
        out.sort(key=lambda b: b.t)
        return out


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

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.clock = clock

    def bars(self, symbol: str, interval: str, n: int) -> list[Bar]:
        from .instruments import BY_SYMBOL
        seed = sum(map(ord, symbol))
        f = BY_SYMBOL[symbol].spread / 0.01 if symbol in BY_SYMBOL else 1.0
        drift = 0.002 * f * (1 if seed % 2 else -1)
        return synthetic_bars(self.clock(), INTERVALS[interval], n, drift=drift, amp=0.1 * f, noise=0.05 * f,
                              seed=seed + INTERVALS[interval], base=100 * f, volume="/" not in symbol)


def prepare(bars: list[Bar], interval: str, now: datetime, need: int) -> tuple[list[Bar], str | None]:
    """Keep closed bars only and validate them. Returns (bars, problem); a problem means: do not trade."""
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
    if now - last_close > step + GRACE:
        return closed, f"{interval}: zastaralá data – poslední uzavřená svíčka {last_close:%d.%m. %H:%M} UTC"
    return closed[-need:], None

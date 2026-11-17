"""Historical data providers. Read-only GET requests, rate limited, cached on disk, bounded retries.

* Dukascopy public datafeed: 1-minute BID and ASK candles (LZMA "bi5" files, one per day and side). Free historical
  data for personal analysis; the files are cached locally and never committed. Minutes without any tick come as
  flat zero-volume candles and are DROPPED (they are not prices anybody traded at).
* Yahoo Finance chart API: 5m/15m for the last 60 days, 1h for ~2 years. Exchange prices (stocks), futures
  (GC=F, CL=F) or FX quotes; side of the FX quote is not documented -> stored as "last".
* Twelve Data time_series with start/end paging, respecting the free plan (8 requests/min, 800/day).
Every fetcher returns bars plus the metadata the store needs; nothing fills or interpolates missing data.
"""
from __future__ import annotations

import hashlib
import json
import lzma
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..data import INTERVALS, Bar

UA = "cfd-signal-calculator-research (personal analysis)"


class SourceError(Exception):
    pass


class Http:
    """GET with a minimum spacing between requests, an on-disk cache and at most `retries` retries
    (only on 429 / 5xx / timeouts; GET is idempotent)."""

    def __init__(self, cache: Path | None, min_interval: float = 0.2, retries: int = 3, timeout: float = 30,
                 backoff: float = 1.0):
        self.cache, self.min_interval, self.retries, self.timeout = cache, min_interval, retries, timeout
        self.backoff = backoff          # waits backoff * 2**attempt seconds (max 120 s) before a retry
        self._last = 0.0
        self.requests = 0

    def get(self, url: str, headers: dict | None = None, cache: bool = True, missing_ok: bool = False) -> bytes:
        path = self.cache / hashlib.sha256(url.encode()).hexdigest()[:32] if self.cache and cache else None
        if path and path.exists():
            return path.read_bytes()
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.requests += 1
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
                with urllib.request.urlopen(req, timeout=self.timeout) as r:  # nosec B310 - fixed https hosts
                    body = r.read()
                break
            except urllib.error.HTTPError as e:
                if e.code == 404 and missing_ok:
                    body = b""
                    break
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise SourceError(f"HTTP {e.code} pro {urllib.parse.urlsplit(url).netloc}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt == self.retries:
                    raise SourceError(f"síť nedostupná: {type(e).__name__}") from None
            time.sleep(min(120.0, self.backoff * 2 ** attempt))
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return body


@dataclass(frozen=True)
class Fetched:
    bars: list[Bar]
    meta: dict          # kind, side, interval, provider_symbol, exchange, adjusted, volume_kind, licence, notes


# ---------------------------------------------------------------- aggregation

def aggregate(bars: list[Bar], interval: str) -> list[Bar]:
    """Combine finer bars into `interval` bars aligned to the UTC grid (only observed bars are used)."""
    step = INTERVALS[interval] * 60
    out: list[Bar] = []
    cur = None
    for b in bars:
        key = int(b.t.timestamp()) // step * step
        if cur and cur[0] == key:
            _, o, h, lo, c, v = cur
            cur = (key, o, max(h, b.h), min(lo, b.l), b.c, None if v is None or b.v is None else v + b.v)
        else:
            if cur:
                out.append(Bar(datetime.fromtimestamp(cur[0], timezone.utc), *cur[1:]))
            cur = (key, b.o, b.h, b.l, b.c, b.v)
    if cur:
        out.append(Bar(datetime.fromtimestamp(cur[0], timezone.utc), *cur[1:]))
    return out


def mid(bid: list[Bar], ask: list[Bar]) -> list[Bar]:
    """Mid bars where both sides exist at the same time (o/h/l/c averaged field by field)."""
    asks = {b.t: b for b in ask}
    out = []
    for b in bid:
        a = asks.get(b.t)
        if a:
            out.append(Bar(b.t, (b.o + a.o) / 2, (b.h + a.h) / 2, (b.l + a.l) / 2, (b.c + a.c) / 2,
                           None if b.v is None or a.v is None else (b.v + a.v) / 2))
    return out


# ---------------------------------------------------------------- Dukascopy

DUKA_URL = "https://datafeed.dukascopy.com/datafeed/{sym}/{y}/{m:02d}/{d:02d}/{side}_candles_min_1.bi5"
# provider symbol, price divisor (point), product kind - verified at import against Yahoo price levels
DUKASCOPY = {
    "EUR/USD": ("EURUSD", 1e5, "spot"), "GBP/USD": ("GBPUSD", 1e5, "spot"), "USD/JPY": ("USDJPY", 1e3, "spot"),
    "XAU/USD": ("XAUUSD", 1e3, "spot"), "XAG/USD": ("XAGUSD", 1e3, "spot"),
    "WTI/USD": ("LIGHTCMDUSD", 1e3, "cfd"),
    "AAPL": ("AAPLUSUSD", 1e3, "cfd"), "NVDA": ("NVDAUSUSD", 1e3, "cfd"), "MSFT": ("MSFTUSUSD", 1e3, "cfd"),
    "TSLA": ("TSLAUSUSD", 1e3, "cfd"),
}
RECORD = struct.Struct(">IIIIIf")   # seconds from day start, open, close, low, high, volume


def parse_bi5(raw: bytes, day: datetime, point: float) -> list[Bar]:
    """Decode one Dukascopy day file of 1-minute candles. Zero-volume (no tick) minutes are dropped.
    Raises SourceError when the content does not look like valid candles (fail closed, never guess)."""
    if not raw:
        return []
    try:
        data = lzma.decompress(raw, format=lzma.FORMAT_AUTO)
    except lzma.LZMAError:
        try:
            data = lzma.decompress(raw, format=lzma.FORMAT_ALONE)
        except lzma.LZMAError as e:
            raise SourceError(f"neplatný soubor bi5 ({e})") from None
    if len(data) % RECORD.size:
        raise SourceError("neočekávaná délka záznamů bi5")
    out, bad = [], 0
    for i in range(0, len(data), RECORD.size):
        t, o, c, lo, h, v = RECORD.unpack_from(data, i)
        if v <= 0:
            continue
        o, c, lo, h = o / point, c / point, lo / point, h / point
        if not (lo <= min(o, c) <= max(o, c) <= h) or lo <= 0 or t >= 86400:
            bad += 1
            continue
        out.append(Bar(day + timedelta(seconds=t), o, h, lo, c, v))
    if bad > max(2, 0.001 * (len(data) // RECORD.size)):
        raise SourceError(f"{bad} neplatných svíček v souboru {day:%Y-%m-%d} – formát neodpovídá, data nepoužita")
    return out


def dukascopy(symbol: str, start: datetime, end: datetime, http: Http,
              deadline: float | None = None) -> dict[str, list[Bar]]:
    """1-minute bid and ask bars for [start, end). Weekends are skipped (no trading). `deadline` (time.monotonic)
    stops the import; files already downloaded stay in the cache, so the next run resumes where this one stopped."""
    if symbol not in DUKASCOPY:
        raise SourceError(f"{symbol}: u Dukascopy není mapování")
    sym, point, _ = DUKASCOPY[symbol]
    out = {"bid": [], "ask": []}
    day = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    while day < end:
        if deadline is not None and time.monotonic() > deadline:
            raise SourceError(f"{symbol}: časový rozpočet importu vyčerpán u {day:%Y-%m-%d} – pokračuje příští běh")
        if day.weekday() != 5:  # Saturday has no data; Sunday evening already trades
            for side in ("BID", "ASK"):
                url = DUKA_URL.format(sym=sym, y=day.year, m=day.month - 1, d=day.day, side=side)
                today = day.date() == datetime.now(timezone.utc).date()
                raw = http.get(url, cache=not today, missing_ok=True)
                out[side.lower()] += parse_bi5(raw, day, point)
        day += timedelta(days=1)
    return out


# ---------------------------------------------------------------- Yahoo Finance

YAHOO = {"AAPL": ("AAPL", "stock"), "NVDA": ("NVDA", "stock"), "MSFT": ("MSFT", "stock"), "TSLA": ("TSLA", "stock"),
         "EUR/USD": ("EURUSD=X", "spot"), "GBP/USD": ("GBPUSD=X", "spot"), "USD/JPY": ("JPY=X", "spot"),
         "XAU/USD": ("GC=F", "futures"), "WTI/USD": ("CL=F", "futures")}


def yahoo(symbol: str, interval: str, http: Http) -> Fetched:
    ysym, kind = YAHOO[symbol]
    yint, rng = {"5min": ("5m", "60d"), "15min": ("15m", "60d"), "1h": ("60m", "730d")}[interval]
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ysym)}?"
           + urllib.parse.urlencode({"interval": yint, "range": rng, "includePrePost": "false"}))
    body = json.loads(http.get(url, headers={"User-Agent": "Mozilla/5.0"}, cache=False))
    res = body["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, lo, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c):
            continue  # a bar Yahoo did not price is missing, not zero
        bars.append(Bar(datetime.fromtimestamp(ts, timezone.utc), o, h, lo, c,
                        float(v) if v is not None and kind == "stock" else None))
    meta = {"kind": kind, "side": "last", "provider_symbol": ysym, "interval": interval,
            "exchange": res.get("meta", {}).get("exchangeName", ""),
            "adjusted": "no" if kind == "stock" else "unknown",
            "volume_kind": "exchange" if kind == "stock" else "none",
            "licence": "Yahoo Finance – jen osobní analýza, data se nepublikují",
            "notes": "strana kotace FX neuvedena" if kind == "spot" else ""}
    return Fetched(bars, meta)


# ---------------------------------------------------------------- Twelve Data (user's key)

def twelvedata(symbol: str, interval: str, start: datetime, end: datetime, api_key: str, http: Http,
               daily_cap: int = 800) -> Fetched:
    """Page backwards from `end` with outputsize=5000 until `start` or until the plan gives no more data.
    Free plan: at most 8 requests per minute -> Http(min_interval=7.6) recommended."""
    from ..instruments import BY_SYMBOL
    inst = BY_SYMBOL[symbol]
    bars: dict[datetime, Bar] = {}
    cursor = end
    while cursor > start:
        if http.requests >= daily_cap:
            raise SourceError("denní limit dotazů Twelve Data vyčerpán – import pokračuje zítra")
        params = {"symbol": symbol, "interval": interval, "outputsize": 5000, "timezone": "UTC", "order": "asc",
                  "end_date": cursor.strftime("%Y-%m-%d %H:%M:%S"), "start_date": start.strftime("%Y-%m-%d %H:%M:%S")}
        if inst.exchange:
            params["exchange"] = inst.exchange
        url = "https://api.twelvedata.com/time_series?" + urllib.parse.urlencode(params)
        body = json.loads(http.get(url, headers={"Authorization": f"apikey {api_key}"}, cache=False))
        if body.get("status") == "error":
            raise SourceError(f"Twelve Data: {body.get('message')}")
        page = []
        for v in body.get("values") or []:
            t = datetime.fromisoformat(v["datetime"]).replace(tzinfo=timezone.utc)
            vol = float(v["volume"]) if v.get("volume") not in (None, "") else None
            page.append(Bar(t, float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"]), vol))
        if not page:
            break
        bars.update({b.t: b for b in page})
        oldest = min(b.t for b in page)
        if oldest >= cursor:
            break
        cursor = oldest
    kind = {"forex": "spot", "commodity": "spot", "stock": "stock", "index": "cfd"}[inst.kind]
    meta = {"kind": kind, "side": "last", "provider_symbol": symbol, "interval": interval,
            "exchange": inst.exchange, "adjusted": "unknown",
            "volume_kind": "exchange" if inst.kind == "stock" else "none",
            "licence": "Twelve Data – podle tarifu uživatele", "notes": "strana kotace neuvedena"}
    return Fetched(sorted(bars.values(), key=lambda b: b.t), meta)

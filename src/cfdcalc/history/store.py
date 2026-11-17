"""SQLite store for historical candles with provenance, quality findings and an economic calendar.

Design rules
* Every series records where it came from: source, provider symbol, product kind (spot / stock / futures / cfd),
  price side (bid / ask / mid / last), exchange, whether prices are adjusted, download time and a licence note.
  Different products are never merged into one series.
* All timestamps are UTC epoch seconds of the bar OPEN.
* Nothing is invented: a missing bar stays missing; quality problems are recorded, not "repaired".
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..data import Bar

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,            -- dukascopy | yahoo | twelvedata | csv
    symbol TEXT NOT NULL,            -- app catalogue symbol, e.g. EUR/USD
    provider_symbol TEXT NOT NULL,   -- symbol at the provider, e.g. EURUSD
    kind TEXT NOT NULL,              -- spot | stock | futures | cfd
    side TEXT NOT NULL,              -- bid | ask | mid | last
    interval TEXT NOT NULL,          -- 1min | 5min | 15min | 1h
    exchange TEXT NOT NULL DEFAULT '',
    timezone TEXT NOT NULL DEFAULT 'UTC',
    adjusted TEXT NOT NULL DEFAULT 'unknown',   -- yes | no | unknown (splits/dividends)
    volume_kind TEXT NOT NULL DEFAULT 'none',   -- exchange | tick | broker | none
    downloaded_at TEXT NOT NULL,
    licence TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE (source, provider_symbol, side, interval)
);
CREATE TABLE IF NOT EXISTS bars (
    series_id INTEGER NOT NULL REFERENCES series(id),
    t INTEGER NOT NULL,
    o REAL NOT NULL, h REAL NOT NULL, l REAL NOT NULL, c REAL NOT NULL,
    v REAL,
    PRIMARY KEY (series_id, t)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS quality (
    series_id INTEGER NOT NULL REFERENCES series(id),
    t INTEGER NOT NULL,
    problem TEXT NOT NULL,           -- gap | duplicate | misaligned | invalid_ohlc | crossed | jump | split
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS quality_series ON quality(series_id, t);
CREATE TABLE IF NOT EXISTS events (
    source TEXT NOT NULL,
    event_id TEXT NOT NULL,
    release_utc INTEGER NOT NULL,     -- original release time
    known_since_utc INTEGER,          -- when the schedule was public (NULL = unknown)
    scheduled INTEGER NOT NULL,       -- 1 scheduled release, 0 unscheduled / surprise
    currency TEXT NOT NULL,
    title TEXT NOT NULL,
    impact TEXT NOT NULL,             -- High | Medium | Low
    PRIMARY KEY (source, event_id)
);
CREATE TABLE IF NOT EXISTS event_coverage (
    source TEXT NOT NULL,
    currency TEXT NOT NULL,
    start_utc INTEGER NOT NULL,
    end_utc INTEGER NOT NULL
);
"""


@dataclass(frozen=True)
class Series:
    id: int
    source: str
    symbol: str
    provider_symbol: str
    kind: str
    side: str
    interval: str
    exchange: str = ""
    adjusted: str = "unknown"
    volume_kind: str = "none"
    downloaded_at: str = ""
    licence: str = ""
    notes: str = ""


def _ts(t: datetime) -> int:
    return int(t.replace(tzinfo=t.tzinfo or timezone.utc).timestamp())


class Store:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.close()

    # ---- series
    def series(self, source: str, symbol: str, provider_symbol: str, kind: str, side: str, interval: str,
               **meta) -> Series:
        """Get or create a series; metadata of an existing series is updated (e.g. download time)."""
        assert kind in ("spot", "stock", "futures", "cfd") and side in ("bid", "ask", "mid", "last")
        meta.setdefault("downloaded_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        cols = ("exchange", "adjusted", "volume_kind", "downloaded_at", "licence", "notes")
        vals = {k: str(meta.get(k, "")) for k in cols}
        vals["adjusted"] = vals["adjusted"] or "unknown"
        vals["volume_kind"] = vals["volume_kind"] or "none"
        self.db.execute(
            "INSERT INTO series (source, symbol, provider_symbol, kind, side, interval, exchange, adjusted, "
            "volume_kind, downloaded_at, licence, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source, provider_symbol, side, interval) DO UPDATE SET downloaded_at=excluded.downloaded_at",
            (source, symbol, provider_symbol, kind, side, interval, *(vals[k] for k in cols)))
        self.db.commit()
        return self.find(source, provider_symbol, side, interval)

    def find(self, source: str, provider_symbol: str, side: str, interval: str) -> Series | None:
        row = self.db.execute(
            "SELECT id, source, symbol, provider_symbol, kind, side, interval, exchange, adjusted, volume_kind, "
            "downloaded_at, licence, notes FROM series WHERE source=? AND provider_symbol=? AND side=? AND "
            "interval=?", (source, provider_symbol, side, interval)).fetchone()
        return Series(*row) if row else None

    def all_series(self) -> list[Series]:
        return [Series(*r) for r in self.db.execute(
            "SELECT id, source, symbol, provider_symbol, kind, side, interval, exchange, adjusted, volume_kind, "
            "downloaded_at, licence, notes FROM series ORDER BY symbol, source, interval, side")]

    # ---- bars
    def put_bars(self, s: Series, bars: list[Bar]) -> int:
        """Insert bars; an existing bar (same time) is kept: re-imports never silently rewrite history."""
        rows = [(s.id, _ts(b.t), b.o, b.h, b.l, b.c, b.v) for b in bars]
        cur = self.db.executemany("INSERT OR IGNORE INTO bars VALUES (?,?,?,?,?,?,?)", rows)
        self.db.commit()
        return cur.rowcount

    def bars(self, s: Series, start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
        q, args = "SELECT t, o, h, l, c, v FROM bars WHERE series_id=?", [s.id]
        if start:
            q, args = q + " AND t >= ?", args + [_ts(start)]
        if end:
            q, args = q + " AND t < ?", args + [_ts(end)]
        return [Bar(datetime.fromtimestamp(t, timezone.utc), o, h, lo, c, v)
                for t, o, h, lo, c, v in self.db.execute(q + " ORDER BY t", args)]

    def span(self, s: Series) -> tuple[datetime | None, datetime | None, int]:
        a, b, n = self.db.execute("SELECT MIN(t), MAX(t), COUNT(*) FROM bars WHERE series_id=?", (s.id,)).fetchone()
        conv = lambda x: datetime.fromtimestamp(x, timezone.utc) if x is not None else None  # noqa: E731
        return conv(a), conv(b), n

    def digest(self, s: Series) -> str:
        """SHA-256 of the stored bars: identifies exactly which data a report was computed from."""
        h = hashlib.sha256()
        for row in self.db.execute("SELECT t, o, h, l, c, v FROM bars WHERE series_id=? ORDER BY t", (s.id,)):
            h.update(repr(row).encode())
        return h.hexdigest()[:16]

    # ---- quality
    def put_quality(self, s: Series, findings: list[tuple[datetime, str, str]]):
        self.db.execute("DELETE FROM quality WHERE series_id=?", (s.id,))
        self.db.executemany("INSERT INTO quality VALUES (?,?,?,?)",
                            [(s.id, _ts(t), problem, detail) for t, problem, detail in findings])
        self.db.commit()

    def quality(self, s: Series) -> list[tuple[datetime, str, str]]:
        return [(datetime.fromtimestamp(t, timezone.utc), p, d) for t, p, d in self.db.execute(
            "SELECT t, problem, detail FROM quality WHERE series_id=? ORDER BY t", (s.id,))]

    # ---- economic calendar (point-in-time)
    def put_events(self, source: str, events: list[dict], coverage: list[tuple[str, datetime, datetime]]):
        """events: dicts with event_id, release (datetime), known_since (datetime|None), scheduled, currency, title,
        impact. coverage: (currency, start, end) periods the source covers COMPLETELY - outside them the news
        filter counts as untested."""
        self.db.executemany(
            "INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)",
            [(source, e["event_id"], _ts(e["release"]), _ts(e["known_since"]) if e.get("known_since") else None,
              int(bool(e.get("scheduled", True))), e["currency"], e["title"], e["impact"]) for e in events])
        self.db.executemany("INSERT INTO event_coverage VALUES (?,?,?,?)",
                            [(source, ccy, _ts(a), _ts(b)) for ccy, a, b in coverage])
        self.db.commit()

    def covered(self, currency: str, start: datetime, end: datetime) -> bool:
        """True if some source declares complete coverage of [start, end) for the currency."""
        row = self.db.execute("SELECT 1 FROM event_coverage WHERE currency=? AND start_utc<=? AND end_utc>=?",
                              (currency, _ts(start), _ts(end))).fetchone()
        return row is not None

    def events_known_at(self, currencies: tuple[str, ...], at: datetime, horizon_s: int = 86400):
        """High-impact events around `at` whose schedule was already public at `at` (no hindsight)."""
        from ..calendar import Event
        q = ("SELECT release_utc, currency, title, impact FROM events WHERE currency IN (%s) AND release_utc "
             "BETWEEN ? AND ? AND (known_since_utc IS NULL AND scheduled=1 OR known_since_utc <= ?)"
             % ",".join("?" * len(currencies)))
        t = _ts(at)
        return [Event(datetime.fromtimestamp(r, timezone.utc), c, title, imp)
                for r, c, title, imp in self.db.execute(q, (*currencies, t - horizon_s, t + horizon_s, t))]

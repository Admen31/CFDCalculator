"""Economic calendar (Forex Factory weekly JSON feed, free, no key). Fails CLOSED: no data -> no signal.

The feed is unofficial and rate limited, so it is cached on disk for an hour.
"""
from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
TTL_S = 3600
MAX_STALE_S = 6 * 3600  # an older cache is not trusted...
WEEK_STALE_S = 24 * 3600  # ...unless it is this week's schedule that still covers today (the feed is weekly)


@dataclass(frozen=True)
class Event:
    time: datetime    # UTC
    currency: str
    title: str
    impact: str       # High | Medium | Low | Holiday


class CalendarError(Exception):
    pass


def parse(raw: list) -> list[Event]:
    out = []
    for e in raw:
        try:
            t = datetime.fromisoformat(e["date"]).astimezone(timezone.utc)
            out.append(Event(t, str(e["country"]).upper(), str(e["title"]), str(e.get("impact", ""))))
        except (KeyError, TypeError, ValueError):
            continue  # shortcut: undated items are skipped; switch to an official source if that matters
    return out


class Calendar:
    def __init__(self, cache: Path, fetch=None):
        self.cache = cache
        self._fetch = fetch or self._download

    @staticmethod
    def _download() -> list:
        req = urllib.request.Request(FEED, headers={"User-Agent": "cfd-signal-calculator"})
        with urllib.request.urlopen(req, timeout=15) as r:  # nosec B310 - fixed https URL
            return json.loads(r.read().decode("utf-8"))

    def _covers_today(self) -> bool:
        try:
            times = [e.time for e in parse(json.loads(self.cache.read_text(encoding="utf-8")))]
        except (OSError, ValueError):
            return False
        now = datetime.now(timezone.utc)
        return bool(times) and min(times).date() <= now.date() <= max(times).date()

    def events(self) -> list[Event]:
        age = time.time() - self.cache.stat().st_mtime if self.cache.exists() else None
        if age is None or age > TTL_S:
            try:
                raw = self._fetch()
                if not isinstance(raw, list):
                    raise ValueError("unexpected feed format")
                self.cache.parent.mkdir(parents=True, exist_ok=True)
                self.cache.write_text(json.dumps(raw), encoding="utf-8")
                return parse(raw)
            except Exception as e:  # noqa: BLE001 - any failure falls back to a fresh-enough cache or fails closed
                if age is None or age > WEEK_STALE_S or (age > MAX_STALE_S and not self._covers_today()):
                    raise CalendarError(f"kalendář zpráv nedostupný ({type(e).__name__}); feed Forex Factory "
                                        "neodpověděl a uložená kopie je stará") from None
        return parse(json.loads(self.cache.read_text(encoding="utf-8")))

"""Local record of which symbols and intervals a data source actually delivered (no extra API requests).

Filled from every analysis and from the manual availability check. Successes are trusted for 7 days, failures for
1 day; transient failures (rate limit, server outage, connection, timeout) never mark a symbol unavailable.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import KIND_TEXT

TRANSIENT = ("rate_limit", "server", "connection", "timeout")
PERSISTENT = ("not_found", "plan", "invalid", "request", "unknown", "unmapped")
TTL_OK, TTL_FAIL = timedelta(days=7), timedelta(days=1)
INTERVALS = ("5min", "15min", "1h")


def state_text(state: str) -> str:
    """Czech label of a recorded state: OK, or the kind of data problem."""
    if state == "OK":
        return "dostupné"
    if state == "no_data":
        return "nedostatečná data"
    return "nedostupné – " + KIND_TEXT.get(state, state).lower()


class Availability:
    def __init__(self, path: Path):
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def record(self, source: str, symbol: str, interval: str, state: str, detail: str, when: datetime | None = None):
        when = when or datetime.now(timezone.utc)
        self.data.setdefault(f"{source}|{symbol}", {})[interval] = {"state": state, "detail": detail[:300],
                                                                     "when": when.isoformat()}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass  # the record is a convenience; failing to save it must never break the analysis

    def summary(self, source: str, symbol: str, now: datetime | None = None) -> tuple[str, str]:
        """("ověřeno" | "nedostupné" | "neověřeno", explanation)."""
        now = now or datetime.now(timezone.utc)
        rows = self.data.get(f"{source}|{symbol}", {})
        fresh = {}
        for interval, row in rows.items():
            age = now - datetime.fromisoformat(row["when"])
            if age <= (TTL_OK if row["state"] == "OK" else TTL_FAIL):
                fresh[interval] = row
        bad = {i: r for i, r in fresh.items() if r["state"] in PERSISTENT}
        if bad:
            i, r = next(iter(bad.items()))
            when = datetime.fromisoformat(r["when"]).astimezone()
            return "nedostupné", f"{source}: {symbol} {i} – {state_text(r['state'])} (zjištěno {when:%d.%m. %H:%M})"
        if all(fresh.get(i, {}).get("state") == "OK" for i in INTERVALS):
            when = max(datetime.fromisoformat(fresh[i]["when"]) for i in INTERVALS).astimezone()
            return "ověřeno", f"{source}: {symbol} – data 5min/15min/1h ověřena {when:%d.%m. %H:%M}"
        return "neověřeno", f"{source}: {symbol} – dostupnost dat zatím neověřena"

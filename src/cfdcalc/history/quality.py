"""Data quality checks. Findings are recorded and the affected windows are excluded from analysis -
nothing is repaired or interpolated.

problem kinds: duplicate, misaligned, invalid_ohlc, gap (missing bars while the market trades), jump (price move
far beyond normal bar ranges), split (overnight stock gap close to a split ratio), crossed (ask below bid).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from ..data import INTERVALS, Bar

SEVERE = ("duplicate", "misaligned", "invalid_ohlc", "jump", "split", "crossed")
NY = ZoneInfo("America/New_York")
SPLIT_RATIOS = (2, 3, 4, 5, 10, 20, 1 / 2, 1 / 3, 1 / 4, 1 / 5, 1 / 10)


def _expected_gap(a: datetime, b: datetime, kind: str) -> bool:
    """True when no bars between a and b is normal (market closed)."""
    if kind == "stock":
        return a.astimezone(NY).date() != b.astimezone(NY).date()      # overnight / weekend / holiday
    # 24h markets: weekend (Fri ~21:00 UTC -> Sun ~21:00 UTC) and the daily ~1 h settlement break of
    # metals/energy around 21:00-23:00 UTC; holidays show up as gaps and are reported, not hidden
    if a.weekday() == 4 and b.weekday() in (6, 0) and (b - a) < timedelta(days=3):
        return True
    return (b - a) <= timedelta(hours=2, minutes=5) and 20 <= a.hour <= 23


def check(bars: list[Bar], interval: str, kind: str, jump_factor: float = 12.0) -> list[tuple[datetime, str, str]]:
    step = timedelta(minutes=INTERVALS[interval])
    out: list[tuple[datetime, str, str]] = []
    if not bars:
        return out
    offset = int(bars[0].t.timestamp()) % int(step.total_seconds())
    ranges: list[float] = []
    for i, b in enumerate(bars):
        if not (b.l <= min(b.o, b.c) and max(b.o, b.c) <= b.h and b.l > 0):
            out.append((b.t, "invalid_ohlc", f"o={b.o} h={b.h} l={b.l} c={b.c}"))
        if int(b.t.timestamp()) % int(step.total_seconds()) != offset:
            out.append((b.t, "misaligned", f"čas {b.t:%H:%M} mimo mřížku {interval}"))
        if i:
            p = bars[i - 1]
            dt = b.t - p.t
            if dt <= timedelta(0):
                out.append((b.t, "duplicate", "stejný nebo dřívější čas než předchozí svíčka"))
                continue
            if dt > step and not _expected_gap(p.t, b.t, kind):
                out.append((p.t + step, "gap", f"chybí {int(dt / step) - 1} svíček do {b.t:%Y-%m-%d %H:%M}"))
            move = abs(b.o - p.c)
            ref = median(ranges[-50:]) if len(ranges) >= 20 else None
            overnight = kind == "stock" and p.t.astimezone(NY).date() != b.t.astimezone(NY).date()
            if overnight and p.c > 0:
                ratio = b.o / p.c
                if abs(ratio - 1) > 0.25 and any(abs(ratio * r - 1) < 0.08 for r in SPLIT_RATIOS):
                    out.append((b.t, "split", f"poměr {ratio:.3f} – pravděpodobný split, data neupravená"))
            elif ref and move > jump_factor * ref and move / p.c > 0.002:
                out.append((b.t, "jump", f"skok {move:g} = {move / ref:.0f}× mediánu rozpětí"))
        ranges.append(b.h - b.l)
    return out


def check_pair(bid: list[Bar], ask: list[Bar]) -> list[tuple[datetime, str, str]]:
    asks = {b.t: b for b in ask}
    return [(b.t, "crossed", f"ask {asks[b.t].c} < bid {b.c}") for b in bid
            if b.t in asks and (asks[b.t].c < b.c or asks[b.t].o < b.o)]


def severe_times(findings) -> list[datetime]:
    return sorted(t for t, problem, _ in findings if problem in SEVERE)

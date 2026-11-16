"""Historical test of the exact live rule set (analysis.evaluate) and the demo signal journal.

Backtest limits (shown to the user): no historical news filter, fills at bar close plus spread, if SL and TP
are both inside one bar the SL counts (pessimistic), open trades are closed at the evening cut-off.
"""
from __future__ import annotations

import csv
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .analysis import BUY, DEFAULTS, NEED, SELL, Settings, cutoff_utc, evaluate
from .data import Bar, Provider, prepare
from .instruments import Instrument

HISTORY = 5000  # Twelve Data maximum outputsize


@dataclass
class Trade:
    time: datetime
    direction: str
    entry: float
    sl: float
    tp: float
    exit_time: datetime | None = None
    r: float | None = None      # result in R (risk units), spread included
    how: str = "otevřeno"


def simulate(trade: Trade, after: list[Bar], spread: float, cfg: Settings) -> Trade:
    """Walk 5m bars after the entry; SL first when both levels are touched in one bar."""
    risk = abs(trade.entry - trade.sl)
    sign = 1 if trade.direction == BUY else -1
    cost = spread / risk
    limit = cutoff_utc(trade.time, cfg)
    for b in after:
        end = b.t + timedelta(minutes=5)
        hit_sl = b.l <= trade.sl if sign > 0 else b.h >= trade.sl
        hit_tp = b.h >= trade.tp if sign > 0 else b.l <= trade.tp
        if hit_sl or hit_tp:
            trade.exit_time, trade.how = end, "SL" if hit_sl else "TP"
            trade.r = (-1.0 if hit_sl else abs(trade.tp - trade.entry) / risk) - cost
            return trade
        if end >= limit:
            trade.exit_time, trade.how = end, "večerní limit"
            trade.r = sign * (b.c - trade.entry) / risk - cost
            return trade
    return trade


@dataclass
class Report:
    trades: list[Trade]
    bars: int
    start: datetime | None
    end: datetime | None

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if t.r is not None]

    def summary(self) -> str:
        c = self.closed
        if not c:
            return f"Žádný uzavřený obchod na {self.bars} svíčkách 5m."
        wins = [t.r for t in c if t.r > 0]
        losses = [-t.r for t in c if t.r <= 0]
        equity = peak = dd = 0.0
        for t in c:
            equity += t.r
            peak = max(peak, equity)
            dd = max(dd, peak - equity)
        pf = f"{sum(wins) / sum(losses):.2f}" if losses and sum(losses) else "– (žádná ztráta)"
        return (f"Období: {self.start:%d.%m.%Y %H:%M} – {self.end:%d.%m.%Y %H:%M} UTC ({self.bars} svíček 5m)\n"
                f"Obchodů: {len(c)}  |  úspěšnost: {100 * len(wins) / len(c):.0f} %\n"
                f"Celkem: {equity:+.2f} R  |  průměr: {equity / len(c):+.2f} R  |  profit factor: {pf}\n"
                f"Max. propad: {dd:.2f} R")


def run_backtest(inst: Instrument, provider: Provider, spread: float, cfg: Settings = DEFAULTS,
                 progress: Callable[[int, int], None] = lambda *_: None,
                 cancelled: Callable[[], bool] = lambda: False) -> Report:
    m5, m15, h1 = (provider.bars(inst.symbol, i, HISTORY) for i in ("5min", "15min", "1h"))
    t15, t1 = [b.t for b in m15], [b.t for b in h1]
    trades: list[Trade] = []
    busy_until: datetime | None = None
    first = NEED + 1
    n = len(m5) - 1 - first
    for k, i in enumerate(range(first, len(m5) - 1)):  # the newest bar may still be forming
        if cancelled():
            break
        if k % 50 == 0:
            progress(k, n)
        now = m5[i].t + timedelta(minutes=5)
        if busy_until and now < busy_until:
            continue  # one position at a time
        # bars that had closed by `now` (a bar is closed when open + interval <= now)
        s5, p5 = prepare(m5[i - NEED + 1:i + 1], "5min", now, NEED)
        j15 = bisect_right(t15, now - timedelta(minutes=15))
        s15, p15 = prepare(m15[max(0, j15 - NEED):j15], "15min", now, NEED)
        j1 = bisect_right(t1, now - timedelta(hours=1))
        s1, p1 = prepare(h1[max(0, j1 - NEED):j1], "1h", now, NEED)
        if p5 or p15 or p1:
            continue
        r = evaluate(inst, s5, s15, s1, [], spread, now, cfg)  # shortcut: no historical news filter
        if r.verdict not in (BUY, SELL):
            continue
        t = simulate(Trade(now, r.verdict, float(r.entry), float(r.sl), float(r.tp)), m5[i + 1:], spread, cfg)
        trades.append(t)
        busy_until = t.exit_time or datetime.max.replace(tzinfo=timezone.utc)
    progress(n, n)
    return Report(trades, len(m5), m5[0].t if m5 else None, m5[-1].t if m5 else None)


# ---- demo journal (paper trading): every BUY/SELL from the live analysis is recorded and verified later ----

FIELDS = ("time_utc", "symbol", "direction", "entry", "sl", "tp", "result_r", "how")


def journal_add(path: Path, symbol: str, direction: str, when: datetime, entry, sl, tp) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(FIELDS)
        w.writerow((when.isoformat(), symbol, direction, entry, sl, tp, "", ""))


def journal_read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def journal_verify(path: Path, provider: Provider, spread_of: Callable[[str], float], now: datetime,
                   cfg: Settings = DEFAULTS) -> list[dict]:
    """Resolve open journal rows with the 5m history that followed each signal, then rewrite the file."""
    rows = journal_read(path)
    cache: dict[str, list[Bar]] = {}
    for row in rows:
        if row["result_r"]:
            continue
        if row["symbol"] not in cache:
            cache[row["symbol"]] = [b for b in provider.bars(row["symbol"], "5min", HISTORY)
                                    if b.t + timedelta(minutes=5) <= now]
        bars = cache[row["symbol"]]
        when = datetime.fromisoformat(row["time_utc"])
        if not bars or bars[0].t > when:
            row["how"] = "mimo dostupnou historii"
            continue
        t = simulate(Trade(when, row["direction"], float(row["entry"]), float(row["sl"]), float(row["tp"])),
                     [b for b in bars if b.t >= when], spread_of(row["symbol"]), cfg)
        row["how"] = t.how
        if t.r is not None:
            row["result_r"] = f"{t.r:+.2f}"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows

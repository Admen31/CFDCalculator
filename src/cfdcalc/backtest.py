"""Historical test of the live rule set (analysis.evaluate), comparison with the frozen v2.0 rules (legacy.py),
and the demo signal journal.

Backtest limits (shown to the user): no historical news filter, fills at bar close, spread (and an optional modelled
extra cost) charged once per trade, if SL and TP are both inside one bar the SL counts (pessimistic), open trades
are closed at the market's evening limit. Signals only use bars closed at the decision time (no look-ahead).
"""
from __future__ import annotations

import csv
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import legacy
from .analysis import BUY, DEFAULTS, NEED, NO_DATA, SELL, WAIT, Settings, cutoff_utc, evaluate, market_end, session_open
from .data import Bar, Provider, prepare
from .instruments import Instrument

HISTORY = 5000  # Twelve Data maximum outputsize
VERDICTS = (BUY, SELL, WAIT, NO_DATA, "ERROR")


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
    gross_r: float | None = None   # result in R before any cost
    risk: float = 0.0              # |entry - SL| in price units


def simulate(trade: Trade, after: list[Bar], spread: float, cfg: Settings, limit: datetime | None = None) -> Trade:
    """Walk 5m bars after the entry; SL first when both levels are touched in one bar. `limit` = forced exit time
    (default: the v2.0 global evening cut-off)."""
    risk = abs(trade.entry - trade.sl)
    trade.risk = risk
    sign = 1 if trade.direction == BUY else -1
    cost = spread / risk
    limit = limit or cutoff_utc(trade.time, cfg)
    for b in after:
        end = b.t + timedelta(minutes=5)
        hit_sl = b.l <= trade.sl if sign > 0 else b.h >= trade.sl
        hit_tp = b.h >= trade.tp if sign > 0 else b.l <= trade.tp
        if hit_sl or hit_tp:
            trade.exit_time, trade.how = end, "SL" if hit_sl else "TP"
            trade.gross_r = -1.0 if hit_sl else abs(trade.tp - trade.entry) / risk
            trade.r = trade.gross_r - cost
            return trade
        if end >= limit:
            trade.exit_time, trade.how = end, "večerní limit"
            trade.gross_r = sign * (b.c - trade.entry) / risk
            trade.r = trade.gross_r - cost
            return trade
    return trade


def stats(results: list[float]) -> dict:
    """Trades, win rate, total/average R, profit factor and max drawdown (in R) of a sequence of results."""
    if not results:
        return {"trades": 0, "win": None, "total": 0.0, "avg": None, "pf": None, "dd": 0.0}
    wins, losses = [x for x in results if x > 0], [-x for x in results if x <= 0]
    equity = peak = dd = 0.0
    for x in results:
        equity += x
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else None
    return {"trades": len(results), "win": len(wins) / len(results), "total": equity, "avg": equity / len(results),
            "pf": pf, "dd": dd}


@dataclass
class Report:
    trades: list[Trade]
    bars: int
    start: datetime | None
    end: datetime | None
    verdicts: Counter = field(default_factory=Counter)   # outcome of every evaluated 5m bar
    reasons: Counter = field(default_factory=Counter)    # first reason of every WAIT / NO DATA
    outcomes: list[tuple[datetime, str]] = field(default_factory=list)  # (decision time, verdict) per bar

    @property
    def closed(self) -> list[Trade]:
        return [t for t in self.trades if t.r is not None]

    def summary(self) -> str:
        c = self.closed
        counts = "  ".join(f"{v} {self.verdicts.get(v, 0)}" for v in VERDICTS if self.verdicts.get(v))
        head = f"Vyhodnoceno svíček: {sum(self.verdicts.values())}  ({counts})\n" if self.verdicts else ""
        if not c:
            return head + f"Žádný uzavřený obchod na {self.bars} svíčkách 5m."
        st = stats([t.r for t in c])
        pf = f"{st['pf']:.2f}" if st["pf"] is not None else "– (žádná ztráta)"
        return (head + f"Období: {self.start:%d.%m.%Y %H:%M} – {self.end:%d.%m.%Y %H:%M} UTC ({self.bars} svíček 5m)\n"
                f"Obchodů: {len(c)}  |  úspěšnost: {100 * st['win']:.0f} %\n"
                f"Celkem: {st['total']:+.2f} R  |  průměr: {st['avg']:+.2f} R  |  profit factor: {pf}\n"
                f"Max. propad: {st['dd']:.2f} R")


def backtest_bars(inst: Instrument, m5: list[Bar], m15: list[Bar], h1: list[Bar], spread: float,
                  cfg: Settings = DEFAULTS, rules: str = "v2.1", progress: Callable[[int, int], None] = lambda *_: None,
                  cancelled: Callable[[], bool] = lambda: False) -> Report:
    """Evaluate every closed 5m bar with `rules` ("v2.1" = analysis.evaluate, "v2.0" = legacy.evaluate);
    open a trade on BUY/SELL when no trade is open. No historical news filter (events=[])."""
    decide = evaluate if rules == "v2.1" else legacy.evaluate
    t15, t1 = [b.t for b in m15], [b.t for b in h1]
    rep = Report([], len(m5), m5[0].t if m5 else None, m5[-1].t if m5 else None)
    busy_until: datetime | None = None
    first = NEED + 1
    n = max(len(m5) - 1 - first, 0)
    for k, i in enumerate(range(first, len(m5) - 1)):  # the newest bar may still be forming
        if cancelled():
            break
        if k % 50 == 0:
            progress(k, n)
        now = m5[i].t + timedelta(minutes=5)
        # only bars closed by `now` (a bar is closed when open + interval <= now): no look-ahead
        opened = session_open(inst, now) if rules == "v2.1" else None   # v2.1: closed hours do not age data
        s5, p5 = prepare(m5[i - NEED + 1:i + 1], "5min", now, NEED, opened)
        j15 = bisect_right(t15, now - timedelta(minutes=15))
        s15, p15 = prepare(m15[max(0, j15 - NEED):j15], "15min", now, NEED, opened)
        j1 = bisect_right(t1, now - timedelta(hours=1))
        s1, p1 = prepare(h1[max(0, j1 - NEED):j1], "1h", now, NEED, opened)
        if p5 or p15 or p1:
            rep.verdicts[NO_DATA] += 1
            rep.outcomes.append((now, NO_DATA))
            rep.reasons[(p5 or p15 or p1).split(" – ")[0]] += 1
            continue
        r = decide(inst, s5, s15, s1, [], spread, now, cfg)  # shortcut: no historical news filter
        rep.verdicts[r.verdict] += 1
        rep.outcomes.append((now, r.verdict))
        if r.verdict not in (BUY, SELL):
            rep.reasons[_reason_key(r.reasons[0] if r.reasons else "")] += 1
            continue
        if busy_until and now < busy_until:
            continue  # one position at a time
        limit = market_end(inst, now, cfg)[0] if rules == "v2.1" else cutoff_utc(now, cfg)
        t = simulate(Trade(now, r.verdict, float(r.entry), float(r.sl), float(r.tp)), m5[i + 1:], spread, cfg,
                     limit)
        rep.trades.append(t)
        busy_until = t.exit_time or datetime.max.replace(tzinfo=timezone.utc)
    progress(n, n)
    return rep


def _reason_key(text: str) -> str:
    """Group reasons by their kind (drop the numbers) for the WAIT diagnostics."""
    head = text.split(":")[0] if ":" in text[:40] else text
    for word in ("nedostatečná shoda", "do večerního limitu", "spread", "1h graf", "rezistence", "support",
                 "překoupeno", "přeprodáno", "trh spí", "extrémní volatilita", "EMA 20/50 nesouhlasí"):
        if word in text:
            return word
    return head[:40]


def run_backtest(inst: Instrument, provider: Provider, spread: float, cfg: Settings = DEFAULTS,
                 progress: Callable[[int, int], None] = lambda *_: None,
                 cancelled: Callable[[], bool] = lambda: False, rules: str = "v2.1") -> Report:
    m5, m15, h1 = (provider.bars(inst.symbol, i, HISTORY) for i in ("5min", "15min", "1h"))
    return backtest_bars(inst, m5, m15, h1, spread, cfg, rules, progress, cancelled)


def compare(inst: Instrument, m5: list[Bar], m15: list[Bar], h1: list[Bar], spread: float, extra_cost: float = 0.5,
            split: float = 0.6, cfg: Settings = DEFAULTS, progress: Callable[[int, int], None] = lambda *_: None,
            cancelled: Callable[[], bool] = lambda: False) -> dict:
    """v2.0 vs v2.1 on the same bars. The evaluated period is split by time: the first `split` share is the
    development part, the rest the later test part (rules are fixed in code, nothing is fitted on the data).
    Costs: spread once per trade; `extra_cost` = modelled slippage/commission as a multiple of the spread."""
    out = {}
    for n, rules in enumerate(("v2.0", "v2.1")):
        rep = backtest_bars(inst, m5, m15, h1, spread, cfg, rules,
                            lambda a, b, n=n: progress(n * b + a, 2 * b), cancelled)
        cut = rep.outcomes[int(len(rep.outcomes) * split)][0] if rep.outcomes else None
        parts = {}
        for part, keep in (("vývoj", lambda t, c=cut: c is None or t < c),
                           ("test", lambda t, c=cut: c is not None and t >= c)):
            trades = [t for t in rep.closed if keep(t.time)]
            verdicts = Counter(v for when, v in rep.outcomes if keep(when))
            parts[part] = {
                "gross": stats([t.gross_r for t in trades]),
                "spread": stats([t.r for t in trades]),
                "net": stats([t.r - extra_cost * spread / t.risk for t in trades]),
                "verdicts": verdicts,
            }
        out[rules] = {"report": rep, "split_at": cut, "parts": parts, "verdicts": rep.verdicts, "reasons": rep.reasons}
    return out


def fmt_stats(st: dict) -> str:
    if not st["trades"]:
        return "0 obchodů"
    pf = f"{st['pf']:.2f}" if st["pf"] is not None else "–"
    return (f"{st['trades']} obch., {100 * st['win']:.0f} % zisk., PF {pf}, ⌀ {st['avg']:+.2f} R, "
            f"Σ {st['total']:+.1f} R, max. pokles {st['dd']:.1f} R")


def comparison_text(res: dict, extra_cost: float = 0.5) -> str:
    """Plain-text report of compare() for the app's backtest dialog."""
    out = []
    for rules in ("v2.0", "v2.1"):
        r = res[rules]
        v = r["verdicts"]
        out.append(f"=== Pravidla {rules} {'(původní)' if rules == 'v2.0' else '(nová)'} ===")
        out.append("Svíčky: " + ", ".join(f"{k} {v.get(k, 0)}" for k in VERDICTS))
        for part in ("vývoj", "test"):
            p = r["parts"][part]
            out.append(f"  {part:5}  bez nákladů: {fmt_stats(p['gross'])}")
            out.append(f"         se spreadem: {fmt_stats(p['spread'])}")
            out.append(f"         spread + {extra_cost:g}× spread náklady: {fmt_stats(p['net'])}")
        top = sorted(r["reasons"].items(), key=lambda x: -x[1])[:5]
        out.append("  nejčastější důvody WAIT/NO DATA: " + "; ".join(f"{k} ({n}×)" for k, n in top))
        out.append("")
    return "\n".join(out)


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

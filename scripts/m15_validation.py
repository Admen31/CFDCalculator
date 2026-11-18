"""Historical check of the v2.8 M15 strategy (the exact live code: cfdcalc.m15.evaluate) on real 15m prices.

Usage:
  python scripts/m15_validation.py [--out m15-validation.md] [--synthetic]

Data: Yahoo Finance public 15m chart data (last ~60 days) - exchange / spot / futures prices, NOT Trading 212 CFD
prices (gold = COMEX futures GC=F). --synthetic runs offline on random walks (only checks the script itself).

Method (fixed before looking at results; nothing is fitted to this data):
  * every closed 15m bar is a decision point; the strategy sees only bars closed at that time (window of 400 bars,
    as the app downloads) - no look-ahead. No historical news filter (the live app blocks around news).
  * direction (BUY / SELL / NEUTRAL / NO DATA) is counted at every decision point while the market is open;
    "directional accuracy" = share of BUY (SELL) whose close 4 bars (1 h) later is higher (lower).
  * a CONFIRMED entry opens a simulated trade at the decision close: the spread is paid at entry, SL = 1.5 x ATR,
    TP = 2R, intraday only (closed at the market's evening limit or after 32 bars = 8 h). SL and TP inside the same
    bar count as SL (pessimistic). One trade per instrument at a time.
  * results in R (1R = |entry - SL|): gross, after spread, after spread + extra costs (0.5 x spread slippage).
  * time split 60 / 40: development part and a later out-of-sample part (the rules were not changed between them).
A short sample is NOT proof of anything; the report says so.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc import m15  # noqa: E402
from cfdcalc.analysis import DEFAULTS, market_end  # noqa: E402
from cfdcalc.data import Bar  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402

UNIVERSE = [("EUR/USD", "EURUSD=X"), ("GBP/USD", "GBPUSD=X"), ("USD/JPY", "JPY=X"), ("XAU/USD", "GC=F"),
            ("WTI/USD", "CL=F"), ("AAPL", "AAPL"), ("NVDA", "NVDA"), ("MSFT", "MSFT"), ("TSLA", "TSLA"),
            ("SPY", "SPY")]
SPREAD = {"EUR/USD": 0.00008, "GBP/USD": 0.00012, "USD/JPY": 0.012, "XAU/USD": 0.35, "WTI/USD": 0.03}
STOCK_SPREAD = 0.0003            # US stocks / ETF: 0.03 % of the price (assumption, T212 spreads vary)
EXTRA = 0.5                      # extra costs (slippage) as a multiple of the spread
WINDOW = 400
HORIZON = 4                      # bars for directional accuracy (1 h)
MAX_HOLD = 32                    # bars (8 h)


def yahoo(symbol: str) -> list[Bar]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?"
           + urllib.parse.urlencode({"interval": "15m", "range": "60d", "includePrePost": "false"}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; cfd-signal-calculator)"})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 - fixed https host
        res = json.loads(r.read().decode("utf-8"))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, lo, c = (q[k][i] for k in ("open", "high", "low", "close"))
        if None in (o, h, lo, c) or min(o, h, lo, c) <= 0:
            continue
        t = datetime.fromtimestamp(ts, timezone.utc)
        if t.minute % 15:                      # only bars on the 15m grid
            continue
        out.append(Bar(t, o, max(h, o, c), min(lo, o, c), c, None))
    out.sort(key=lambda b: b.t)
    dedup = {b.t: b for b in out}
    return [dedup[t] for t in sorted(dedup)]


def synthetic(seed: int) -> list[Bar]:
    rnd = random.Random(seed)
    t = datetime(2026, 9, 1, tzinfo=timezone.utc)
    p, out = 1.1, []
    while len(out) < 4000:
        if t.weekday() < 5:
            o = p
            c = o * (1 + rnd.gauss(0, 0.0008))
            out.append(Bar(t, o, max(o, c) * (1 + abs(rnd.gauss(0, 0.0004))),
                           min(o, c) * (1 - abs(rnd.gauss(0, 0.0004))), c, None))
            p = c
        t += timedelta(minutes=15)
    return out


@dataclass
class Stats:
    counts: dict = field(default_factory=lambda: {"BUY": 0, "SELL": 0, "NEUTRAL": 0, "NO DATA": 0})
    confirmed: int = 0
    dir_hits: int = 0
    dir_n: int = 0
    trades: list = field(default_factory=list)    # (gross R, after spread R, net R, outcome, plan)
    conditional: int = 0
    unfilled: int = 0

    def add(self, other: "Stats"):
        for k, v in other.counts.items():
            self.counts[k] += v
        self.confirmed += other.confirmed
        self.dir_hits += other.dir_hits
        self.dir_n += other.dir_n
        self.trades += other.trades
        self.conditional += other.conditional
        self.unfilled += other.unfilled


def simulate(sym: str, bars: list[Bar]) -> tuple[Stats, Stats, str]:
    inst = BY_SYMBOL[sym]
    split = bars[int(len(bars) * 0.6)].t if len(bars) > WINDOW else bars[-1].t
    parts = (Stats(), Stats())
    busy_until = -1
    t0 = time.monotonic()
    for i in range(WINDOW, len(bars) - 1):
        b = bars[i]
        now = b.t + m15.STEP + timedelta(seconds=1)
        if market_end(inst, now, DEFAULTS)[0] is None:
            continue
        price = b.c
        spread = SPREAD.get(sym, STOCK_SPREAD * price)
        sig = m15.evaluate(inst, bars[i - WINDOW + 1:i + 1], now, spread, now, DEFAULTS, events=[])
        st = parts[0] if b.t < split else parts[1]
        st.counts[sig.side] += 1
        if sig.side in ("BUY", "SELL") and i + HORIZON < len(bars):
            fut = bars[i + HORIZON].c
            if fut != price:
                st.dir_n += 1
                st.dir_hits += (fut > price) == (sig.side == "BUY")
        if not sig.levels_ok:
            continue
        if sig.confirmed:
            st.confirmed += 1
        else:
            st.conditional += 1
        if i <= busy_until:
            continue
        sign = 1 if sig.side == "BUY" else -1
        entry, sl, tp = float(sig.entry), float(sig.sl), float(sig.tp)
        start = i
        if not sig.confirmed:                     # stop / limit order valid for the next 4 bars (1 h)
            fill = None
            for k in range(i + 1, min(len(bars), i + 1 + HORIZON)):
                x = bars[k]
                if sig.entry_kind == m15.STOP_ENTRY:
                    hit = x.h >= entry if sign > 0 else x.l <= entry
                    px = max(entry, x.o) if sign > 0 else min(entry, x.o)       # a gap fills worse
                else:
                    hit = x.l <= entry if sign > 0 else x.h >= entry
                    px = entry
                if hit:
                    fill = (k, px)
                    break
            if fill is None:
                st.unfilled += 1
                continue
            start, entry = fill[0] - 1, fill[1]
            # the bar of the fill itself may already reach the SL (pessimistic: checked below from the fill bar)
        risk = abs(float(sig.entry) - sl)
        end, _ = market_end(inst, bars[start].t + m15.STEP, DEFAULTS)
        exit_px, outcome, j = None, "time", start
        for j in range(start + 1, min(len(bars), start + 1 + MAX_HOLD)):
            x = bars[j]
            if end is None or x.t + m15.STEP > end:
                exit_px, outcome = x.o, "večer"
                break
            hit_sl = (x.l <= sl) if sign == 1 else (x.h >= sl)
            hit_tp = (x.h >= tp) if sign == 1 else (x.l <= tp)
            if hit_sl:
                exit_px, outcome = sl, "SL"
                break
            if hit_tp:
                exit_px, outcome = tp, "TP"
                break
        if exit_px is None:
            exit_px = bars[j].c
        busy_until = j
        gross = sign * (exit_px - entry) / risk
        after_spread = gross - spread / risk
        net = after_spread - EXTRA * spread / risk
        st.trades.append((gross, after_spread, net, outcome, "potvrzený" if sig.confirmed else "podmíněný"))
    note = f"{len(bars)} svíček {bars[0].t:%d.%m.}–{bars[-1].t:%d.%m.%Y}, výpočet {time.monotonic() - t0:.0f} s"
    return parts[0], parts[1], note


def summary(st: Stats, plan: str | None = None) -> dict:
    n = sum(st.counts.values())
    tr = [t for t in st.trades if plan is None or t[4] == plan]
    out = {"decisions": n, **st.counts, "confirmed": st.confirmed, "conditional": st.conditional,
           "unfilled": st.unfilled,
           "dir_acc": (st.dir_hits / st.dir_n) if st.dir_n else None, "dir_n": st.dir_n, "trades": len(tr)}
    for k, name in ((0, "gross"), (1, "spread"), (2, "net")):
        rs = [t[k] for t in tr]
        wins, losses = [r for r in rs if r > 0], [r for r in rs if r <= 0]
        eq, peak, dd = 0.0, 0.0, 0.0
        for r in rs:
            eq += r
            peak = max(peak, eq)
            dd = max(dd, peak - eq)
        out[name] = {"sum": sum(rs), "avg": sum(rs) / len(rs) if rs else None,
                     "win": len(wins) / len(rs) if rs else None,
                     "avg_win": sum(wins) / len(wins) if wins else None,
                     "avg_loss": sum(losses) / len(losses) if losses else None,
                     "pf": (sum(wins) / -sum(losses)) if losses and sum(losses) < 0 else None, "dd": dd}
    out["tp"] = sum(1 for t in tr if t[3] == "TP")
    out["sl"] = sum(1 for t in tr if t[3] == "SL")
    return out


def f(x, pct=False, d=2):
    if x is None:
        return "–"
    return f"{x:.0%}" if pct else f"{x:.{d}f}"


def table(rows: list[tuple[str, str, dict]]) -> list[str]:
    out = ["| instrument | část | BUY | SELL | NEUTRAL | NO DATA | potvrzené vstupy | směrová přesnost (1 h) | "
           "obchody | TP / SL | výhry (po nákladech) | Ø zisk R | Ø ztráta R | PF hrubě | PF po spreadu | "
           "PF po nákladech | součet R po nákladech | max DD R |",
           "|" + "---|" * 18]
    out[0] = out[0].replace("| potvrzené vstupy |", "| plány potvrzené / podmíněné (nevyplněné) |")
    for name, part, s in rows:
        n = s["net"]
        out.append(f"| {name} | {part} | {s['BUY']} | {s['SELL']} | {s['NEUTRAL']} | {s['NO DATA']} | "
                   f"{s['confirmed']} / {s['conditional']} ({s['unfilled']}) | {f(s['dir_acc'], True)} "
                   f"(n={s['dir_n']}) | {s['trades']} | "
                   f"{s['tp']} / {s['sl']} | {f(n['win'], True)} | {f(n['avg_win'])} | {f(n['avg_loss'])} | "
                   f"{f(s['gross']['pf'])} | {f(s['spread']['pf'])} | {f(n['pf'])} | {f(n['sum'], d=1)} | "
                   f"{f(n['dd'], d=1)} |")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="m15-validation.md")
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    rows, total = [], (Stats(), Stats())
    notes = []
    universe = [(s, None) for s in ("EUR/USD", "XAU/USD")] if a.synthetic else UNIVERSE
    for k, (sym, ysym) in enumerate(universe):
        try:
            bars = synthetic(k) if a.synthetic else yahoo(ysym)
        except Exception as e:  # noqa: BLE001 - a missing instrument is reported, the rest still runs
            notes.append(f"* {sym}: data nedostupná ({type(e).__name__}: {e})")
            continue
        if len(bars) < WINDOW + 50:
            notes.append(f"* {sym}: málo dat ({len(bars)} svíček)")
            continue
        dev, test, note = simulate(sym, bars)
        notes.append(f"* {sym} ({ysym or 'syntetická data'}): {note}")
        total[0].add(dev)
        total[1].add(test)
        rows += [(sym, "vývoj 60 %", summary(dev)), (sym, "test 40 %", summary(test))]
        print(f"{sym}: hotovo ({note})", flush=True)
    rows += [("CELKEM", "vývoj 60 %", summary(total[0])), ("CELKEM", "test 40 % (out-of-sample)", summary(total[1]))]
    for plan in ("potvrzený", "podmíněný"):
        rows += [(f"CELKEM jen {plan}", "vývoj 60 %", summary(total[0], plan)),
                 (f"CELKEM jen {plan}", "test 40 % (out-of-sample)", summary(total[1], plan))]
    src = "syntetická data (kontrola skriptu)" if a.synthetic else "Yahoo Finance 15m, posledních ~60 dní"
    lines = [f"# Historické ověření M15 strategie v2.8 ({src}, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)",
             "",
             "Pravidla jsou pevně v kódu (`cfdcalc.m15`), na těchto datech se nic neladilo. Rozhodnutí v každé "
             "uzavřené 15m svíčce jen z dat, která byla v tu chvíli uzavřená. Bez historického filtru zpráv. "
             "Plán v2.9: POTVRZENÝ = vstup na close rozhodovací svíčky; PODMÍNĚNÝ = stop / limit pokyn platný 4 "
             "svíčky (1 h), vyplní se jen při skutečném dotyku hladiny (gap = horší cena). SL za M15 swingem v "
             "rozmezí 1–3× ATR, TP 2R, jen intradenně, SL i TP v jedné svíčce = SL. Spread placen při vstupu, "
             "náklady navíc 0,5× spread. Data nejsou ceny CFD Trading 212.",
             "", *table(rows), "", "Data:", *notes, "",
             "**Krátký vzorek – výsledky jsou orientační, nejsou důkazem ziskovosti ani její absence.**"]
    text = "\n".join(lines)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(text)


if __name__ == "__main__":
    main()

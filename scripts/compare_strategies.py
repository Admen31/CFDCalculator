"""Compare the frozen v2.0 rules with the v2.1 rules on real historical prices.

Usage:
  python scripts/compare_strategies.py [--source yahoo|twelvedata] [--out comparison.md]

Data: Yahoo Finance public chart data by default (5m/15m: last 60 days, 1h: 1 year). These are exchange/spot or
futures prices, not Trading 212 CFD prices (gold = COMEX futures GC=F, WTI = CL=F). With --source twelvedata and
TWELVEDATA_API_KEY the app's own data source is used (up to 5000 bars per timeframe).
No historical news filter. Each signal uses only bars closed at its decision time. The rules are fixed in code
(no parameter is fitted on this data); the period is split 60/40 into a development part and a later test part.
Short samples are NOT proof of profitability - the report says so.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc.backtest import VERDICTS, compare, stats  # noqa: E402
from cfdcalc.backtest import fmt_stats as fmt  # noqa: E402
from cfdcalc.data import Bar, TwelveData  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402

# app symbol -> Yahoo symbol (proxy where Yahoo has no spot data)
UNIVERSE = [("AAPL", "AAPL"), ("NVDA", "NVDA"), ("MSFT", "MSFT"), ("TSLA", "TSLA"),
            ("EUR/USD", "EURUSD=X"), ("GBP/USD", "GBPUSD=X"), ("USD/JPY", "JPY=X"),
            ("XAU/USD", "GC=F"), ("WTI/USD", "CL=F")]
EXTRA_COST = 0.5   # modelled slippage/commission per trade as a multiple of the spread


def yahoo(symbol: str, interval: str, rng: str, volume: bool) -> list[Bar]:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?"
           + urllib.parse.urlencode({"interval": interval, "range": rng, "includePrePost": "false"}))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; cfd-signal-calculator)"})
    with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310 - fixed https host
        res = json.loads(r.read().decode("utf-8"))["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        o, h, lo, c, v = (q[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, lo, c) or min(o, h, lo, c) <= 0:
            continue
        h, lo = max(h, o, c), min(lo, o, c)
        # a single missing volume becomes 0 (the frozen v2.0 rules cannot handle a partial None)
        out.append(Bar(datetime.fromtimestamp(ts, timezone.utc), o, h, lo, c, float(v or 0) if volume else None))
    return out


def load(source: str, sym: str, ysym: str):
    inst = BY_SYMBOL[sym]
    if source == "twelvedata":
        td = TwelveData(os.environ["TWELVEDATA_API_KEY"])
        frames = [td.bars(sym, iv, 5000) for iv in ("5min", "15min", "1h")]
        time.sleep(8)   # free plan: 8 requests per minute
        return frames
    vol = inst.kind in ("stock", "index")   # Twelve Data has no volume for spot FX/metals: keep the comparison fair
    return [yahoo(ysym, "5m", "60d", vol), yahoo(ysym, "15m", "60d", vol), yahoo(ysym, "60m", "1y", vol)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=("yahoo", "twelvedata"), default="yahoo")
    ap.add_argument("--out", default="comparison.md")
    ap.add_argument("--only", nargs="*")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    lines = [f"# Porovnání pravidel v2.0 a v2.1 ({args.source}, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)",
             "", "Bez historického filtru zpráv. Rozdělení času 60 % vývoj / 40 % test. Náklady: spread 1× za obchod, "
             f"modelované náklady navíc {EXTRA_COST:g}× spread. Krátké období – výsledky jsou orientační, "
             "ne důkaz ziskovosti.", ""]
    totals = {r: {p: {"gross": [], "spread": [], "net": []} for p in ("vývoj", "test")} for r in ("v2.0", "v2.1")}
    verdict_totals = {r: {v: 0 for v in VERDICTS} for r in ("v2.0", "v2.1")}
    reason_totals = {r: {} for r in ("v2.0", "v2.1")}
    ok = 0
    for sym, ysym in UNIVERSE:
        if args.only and sym not in args.only:
            continue
        inst = BY_SYMBOL[sym]
        try:
            m5, m15, h1 = load(args.source, sym, ysym)
        except Exception as e:  # noqa: BLE001 - report and continue
            lines += [f"## {inst.name} ({sym}) – data nedostupná: {type(e).__name__}: {e}", ""]
            print(f"{sym}: data error {e}", flush=True)
            continue
        if len(m5) < 400:
            lines += [f"## {inst.name} ({sym}) – málo dat ({len(m5)} svíček 5m)", ""]
            continue
        ok += 1
        t0 = time.monotonic()
        try:
            res = compare(inst, m5, m15, h1, inst.spread, EXTRA_COST)
        except Exception as e:  # noqa: BLE001 - one instrument must not stop the whole comparison
            lines += [f"## {inst.name} ({sym}) – chyba výpočtu: {type(e).__name__}: {e}", ""]
            print(f"{sym}: compare error {type(e).__name__}: {e}", flush=True)
            ok -= 1
            continue
        print(f"{sym}: {len(m5)} bars 5m, {time.monotonic() - t0:.0f} s", flush=True)
        src = f"{ysym} (Yahoo)" if args.source == "yahoo" else "Twelve Data"
        lines += [f"## {inst.name} ({sym}, data {src}, {m5[0].t:%d.%m.} – {m5[-1].t:%d.%m.%Y}, spread {inst.spread:g})",
                  "",
                  "| pravidla | část | BUY | SELL | WAIT | NO DATA | bez nákladů | se spreadem | spread + náklady |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for rules in ("v2.0", "v2.1"):
            for part in ("vývoj", "test"):
                p = res[rules]["parts"][part]
                v = p["verdicts"]
                lines.append(f"| {rules} | {part} | {v.get('BUY', 0)} | {v.get('SELL', 0)} | {v.get('WAIT', 0)} | "
                             f"{v.get('NO DATA', 0) + v.get('ERROR', 0)} | {fmt(p['gross'])} | {fmt(p['spread'])} | "
                             f"{fmt(p['net'])} |")
                rep = res[rules]["report"]
                cut = res[rules]["split_at"]
                trades = [t for t in rep.closed if (t.time < cut) == (part == "vývoj")]
                totals[rules][part]["gross"] += [t.gross_r for t in trades]
                totals[rules][part]["spread"] += [t.r for t in trades]
                totals[rules][part]["net"] += [t.r - EXTRA_COST * inst.spread / t.risk for t in trades]
            for v, n in res[rules]["verdicts"].items():
                verdict_totals[rules][v] = verdict_totals[rules].get(v, 0) + n
            for why, n in res[rules]["reasons"].items():
                reason_totals[rules][why] = reason_totals[rules].get(why, 0) + n
        lines.append("")
    if not ok:
        lines += ["**Žádná historická data se nepodařilo načíst – porovnání NEOVĚŘENO.**"]
        print("\n".join(lines))
        open(args.out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        return 1
    lines += ["## Souhrn všech instrumentů", "", "| pravidla | část | bez nákladů | se spreadem | spread + náklady |",
              "|---|---|---|---|---|"]
    for rules in ("v2.0", "v2.1"):
        for part in ("vývoj", "test"):
            t = totals[rules][part]
            lines.append(f"| {rules} | {part} | {fmt(stats(t['gross']))} | {fmt(stats(t['spread']))} | "
                         f"{fmt(stats(t['net']))} |")
    lines += ["", "## Výsledky vyhodnocení všech svíček", "", "| pravidla | " + " | ".join(VERDICTS) + " |",
              "|---|" + "---|" * len(VERDICTS)]
    for rules in ("v2.0", "v2.1"):
        lines.append(f"| {rules} | " + " | ".join(str(verdict_totals[rules].get(v, 0)) for v in VERDICTS) + " |")
    lines += ["", "## Nejčastější důvody WAIT / NO DATA", ""]
    for rules in ("v2.0", "v2.1"):
        lines.append(f"**{rules}:** " + "; ".join(f"{why} ({n}×)" for why, n in
                                                 sorted(reason_totals[rules].items(), key=lambda x: -x[1])[:8]))
        lines.append("")
    text = "\n".join(lines) + "\n"
    print(text)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

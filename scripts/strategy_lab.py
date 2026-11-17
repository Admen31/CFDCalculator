"""v2.3 strategy lab: WAIT diagnostics of the v2.1 rules and an out-of-sample test of the three v2.3 strategies.

Usage:  python scripts/strategy_lab.py [--out lab] [--only EUR/USD XAU/USD] [--workers 4]
Data:   Yahoo Finance public chart data (5m/15m: last 60 days, 1h: up to 2 years). Spot FX, US stocks and FUTURES
        as proxies for gold (GC=F), silver (SI=F) and oil (CL=F) - not Trading 212 CFD prices. Research only:
        the application itself never substitutes an instrument.
Costs:  Trading 212 catalogue spread (paid once per trade), slippage 0.1x spread per market fill, entry on the next
        bar's open, SL first when SL and TP fall in one bar (engine.py).
Protocol (fixed before the run): parameters fixed in strategies.py, chronological split 50/25/25 per instrument,
        6 walk-forward segments, bootstrap 95 % interval, Bonferroni x4, promotion rule validation.PROMOTION.
No historical news calendar: the news filter is NOT tested.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc import diagnostics  # noqa: E402
from cfdcalc.engine import Costs, Market  # noqa: E402
from cfdcalc.history import sources  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402
from cfdcalc.strategies import NAMES  # noqa: E402
from cfdcalc.validation import (HORIZONS, PARTS, PROMOTION, STRATEGY_KEYS, THRESHOLDS, direction_rows,  # noqa: E402
                                direction_study, metrics, promotion, strategy_study)

UNIVERSE = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "XAG/USD", "WTI/USD", "AAPL", "NVDA", "MSFT", "TSLA"]


def log(msg: str):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def clean(bars):
    """Yahoo occasionally reports a high/low inside the open/close; widen it (counted in the report)."""
    out, fixed = [], 0
    for b in bars:
        if min(b.o, b.h, b.l, b.c) <= 0:
            continue
        h, lo = max(b.h, b.o, b.c), min(b.l, b.o, b.c)
        fixed += (h, lo) != (b.h, b.l)
        out.append(replace(b, h=h, l=lo))
    return out, fixed


def costs_for(symbol: str) -> Costs:
    floor = BY_SYMBOL[symbol].spread
    return Costs(spread_floor=floor, slippage=0.1 * floor)


def work(job):
    symbol, frames = job
    m = Market(BY_SYMBOL[symbol], *frames)
    t0 = time.monotonic()
    diag = diagnostics.diagnose(m, costs_for(symbol))
    study = strategy_study(m, costs_for(symbol))
    rows = direction_rows(m, costs_for(symbol))
    return symbol, diag, study, rows, time.monotonic() - t0


def m(x) -> str:
    if not x or not x["n"]:
        return "0 obchodů"
    pf = "–" if x["pf"] is None else f"{x['pf']:.2f}"
    return (f"{x['n']} obch., {100 * x['win']:.0f} % zisk., PF {pf}, ⌀ {x['exp']:+.3f} R, Σ {x['total']:+.1f} R, "
            f"max. pokles {x['dd']:.1f} R")


def pct(x) -> str:
    return "–" if x is None else f"{100 * x:.1f} %"


def direction_section(d: dict, causes: dict, n_inst: int) -> list[str]:
    t = d["chosen"]
    out = ["", "## 6. v2.6 MARKET DIRECTION – historické ověření", "",
           f"Pravidlo výběru prahu (stanoveno předem): {d['rule']} **Zvolený práh: {t:.2f}** "
           f"(= převaha {round(100 * t)}/100). Směr používá stejnou funkci jako aplikace; budoucí pohyb ceny "
           "slouží jen k hodnocení. Instrumenty: " + str(n_inst) + ".", "",
           "### Rozložení výsledků před a po (stejný vzorek)", "",
           "| část | vrstva | BUY | SELL | NEUTRAL | WAIT | NO DATA | ERROR |", "|---|---|---|---|---|---|---|---|"]
    for part, layers in d["dist"].items():
        for name, c in layers.items():
            n = sum(c.values()) or 1
            out.append(f"| {part} | {name} | " + " | ".join(
                f"{100 * c.get(k, 0) / n:.1f} %" for k in ("BUY", "SELL", "NEUTRAL", "WAIT", "NO DATA", "ERROR"))
                + " |")
    out += ["", "Příčiny NO DATA (okno dat): " + "; ".join(f"{k} {v}×" for k, v in
                                                          sorted(causes.items(), key=lambda kv: -kv[1])[:8]), "",
            "### Kvalita směru podle prahu (podíl správného směru = cena se pohnula naznačeným směrem)", "",
            "| práh | část | pokrytí BUY/SELL | 5 m | 15 m | 1 h | 1 h po spreadu | "
            "⌀ pohyb 1 h v ATR (hrubě / po spreadu) |",
            "|---|---|---|---|---|---|---|---|"]
    for th in THRESHOLDS:
        for part in PARTS:
            g = d["grid"][th][part]
            out.append(f"| {th:.2f}{' ✓' if th == t else ''} | {part} | {pct(g['1h']['coverage'])} | "
                       + " | ".join(pct(g[h]["hit"]) for h in HORIZONS)
                       + f" | {pct(g['1h']['net_hit'])} | "
                       + (f"{g['1h']['edge']:+.3f} / {g['1h']['edge_net']:+.3f}" if g['1h']['edge'] is not None
                          else "–") + " |")
    test = d["grid"][t]["test"]
    out += ["", "### Nedotčený test (zvolený práh)", ""]
    for h in HORIZONS:
        lo, hi = d["test_ci"][h]
        mom = d["momentum_test"][h]
        out.append(f"* horizont {h}: správný směr {pct(test[h]['hit'])} z {test[h]['calls']} signálů "
                   f"(95% interval po dnech {pct(lo)} – {pct(hi)}); naivní momentum (směr poslední hodiny) "
                   f"{pct(mom['hit'])}")
    out.append("* citlivost na náklady (horizont 1 h, ⌀ pohyb v ATR po odečtení násobku spreadu): " + "; ".join(
        f"{c:g}× spread {m['edge_net']:+.3f}" for c, m in d["cost_test"].items() if m["edge_net"] is not None))
    out.append("* Výkonnost potvrzených vstupů (vrstva TRADE CONFIRMATION, plné náklady): viz řádek v2.1 v kapitole 2 "
               "– od v2.6 se vstup proti MARKET DIRECTION nepotvrdí.")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="lab")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    http = sources.Http(None, min_interval=1.0)
    jobs, data_rows = [], []
    for symbol in [s for s in UNIVERSE if not args.only or s in args.only]:
        try:
            frames, fixed = [], 0
            for interval in ("5min", "15min", "1h"):
                bars, f = clean(sources.yahoo(symbol, interval, http).bars)
                frames.append(bars)
                fixed += f
        except Exception as e:  # noqa: BLE001 - one instrument must not stop the others
            log(f"{symbol}: data nedostupná – {type(e).__name__}: {e}")
            data_rows.append(f"| {symbol} | {sources.YAHOO[symbol][0]} | data nedostupná: {type(e).__name__} | | | |")
            continue
        m5 = frames[0]
        data_rows.append(f"| {symbol} | {sources.YAHOO[symbol][0]} ({sources.YAHOO[symbol][1]}) | {len(m5)} | "
                         f"{m5[0].t:%d.%m.%Y} – {m5[-1].t:%d.%m.%Y} | {BY_SYMBOL[symbol].spread:g} | {fixed} |")
        jobs.append((symbol, frames))
        log(f"{symbol}: {len(m5)} svíček 5m")
    if not jobs:
        log("Žádná data – laboratoř NEPROVEDENA.")
        return 1
    diags, studies, drows, causes = [], [], [], {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for symbol, diag, study, rows, sec in pool.map(work, jobs):
            log(f"{symbol}: hotovo za {sec:.0f} s")
            diags.append(diag)
            studies.append(study)
            drows += rows["rows"]
            for k, v in rows["causes"].items():
                causes[k] = causes.get(k, 0) + v
    prom = promotion(studies)
    lines = [f"# v2.3 – diagnostika WAIT a test strategií ({datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC)", "",
             "Data Yahoo Finance (veřejná, ne ceny Trading 212; zlato/stříbro/ropa = futures jako výzkumná náhrada). "
             "Náklady: spread z katalogu T212 jednou za obchod + skluz 0,1× spreadu na tržních plněních. "
             "Bez historického kalendáře – filtr zpráv NETESTOVÁN. Parametry pevné, rozdělení 50/25/25, 6 úseků.",
             "", "| instrument | zdroj | svíček 5m | období | spread | opravených svíček |",
             "|---|---|---|---|---|---|",
             *data_rows, "", "## 1. Proč v2.1 tak často vrací WAIT", "", diagnostics.markdown(diags), "",
             "## 2. Strategie – souhrnně přes instrumenty", "",
             f"Pravidlo pro ověření (stanoveno předem): {PROMOTION}.",
             "", "| strategie | vývoj | validace | závěrečný test | 95% interval ⌀ R (test) | p × 4 | kladné úseky |"
             " stav |", "|---|---|---|---|---|---|---|---|"]
    for key in ("v2.1",) + STRATEGY_KEYS + ("náhodný",):
        o = prom[key]
        dev = [t.net_r for s in studies for t in s["runs"][key].trades if s["periods"].part(t.signal_time) == "vývoj"]
        ci = o["ci"]
        interval = "–" if ci["lo"] is None else f"{ci['lo']:+.3f} … {ci['hi']:+.3f}"
        p = "–" if o["p_adjusted"] is None else f"{o['p_adjusted']:.3f}"
        state = ("OVĚŘENO" if o.get("validated") else "VÝZKUM") if key in STRATEGY_KEYS else "srovnání"
        lines.append(f"| {NAMES.get(key, key)} | {m(metrics(dev))} | {m(o['validation'])} | {m(o['test'])} | "
                     f"{interval} | {p} | {o['folds_positive']}/6 | {state} |")
    lines.append("")
    for key in STRATEGY_KEYS:
        lines.append(f"**{NAMES[key]}** – kontroly: " + "; ".join(
            f"{'✓' if ok else '✗'} {name}" for name, ok in prom[key]["checks"].items()))
        lines.append("")
    lines += ["## 3. Závěrečný test podle instrumentů", "",
              "| instrument | " + " | ".join(NAMES.get(k, k) for k in ("v2.1",) + STRATEGY_KEYS) + " |",
              "|---|" + "---|" * (1 + len(STRATEGY_KEYS))]
    for s in studies:
        lines.append(f"| {s['symbol']} | " + " | ".join(m(s["parts"][k]["test"]["net"])
                                                         for k in ("v2.1",) + STRATEGY_KEYS) + " |")
    lines += ["", "## 4. Podle tržního režimu (celé období, všechny instrumenty)", ""]
    for key in ("v2.1",) + STRATEGY_KEYS:
        groups = {}
        for s in studies:
            for t in s["runs"][key].trades:
                groups.setdefault(f"{t.regime} / volatilita {t.volatility}", []).append(t.net_r)
        lines.append(f"**{NAMES.get(key, key)}**: " + "; ".join(f"{g}: {m(metrics(rs))}"
                                                               for g, rs in sorted(groups.items())))
        lines.append("")
    lines += ["## 5. Stabilita – walk-forward úseky (souhrnně)", "",
              "| strategie | " + " | ".join(f"úsek {n + 1}" for n in range(6)) + " |", "|---|" + "---|" * 6]
    for key in ("v2.1",) + STRATEGY_KEYS + ("náhodný",):
        lines.append(f"| {NAMES.get(key, key)} | " + " | ".join(
            "–" if not f["n"] else f"{f['n']} / {f['exp']:+.2f} R" for f in prom[key]["folds"]) + " |")
    lines += direction_section(direction_study(drows), causes, len(jobs))
    text = "\n".join(lines) + "\n"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "lab.md").write_text(text, encoding="utf-8")
    (out / "direction.json").write_text(json.dumps({"threshold_rule": "viz lab.md kapitola 6"}), encoding="utf-8")
    (out / "promotion.json").write_text(json.dumps(
        {k: {"validated": prom[k].get("validated", False), "checks": prom[k].get("checks", {}),
             "test_n": prom[k]["test"]["n"], "test_exp": prom[k]["test"]["exp"]} for k in prom},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(text, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

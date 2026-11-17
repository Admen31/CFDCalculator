"""v2.2 research run: import historical data, check its quality, validate the strategy, write CSV + HTML report.

Usage (Windows or Linux):
  python scripts/research.py --months 12 --out research/report
Options: --symbols EUR/USD XAU/USD ... --db research/history.sqlite --cache research/cache --workers 4
         --skip-import (use the existing database) --calendar events.csv
calendar CSV columns: event_id,release_utc,known_since_utc,scheduled,currency,title,impact
                      plus coverage lines in a second file given with --calendar-coverage (currency,start_utc,end_utc)
The database and the raw cache stay local (gitignored); only the report is published.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc.engine import Costs  # noqa: E402
from cfdcalc.history import importer, sources  # noqa: E402
from cfdcalc.history.store import Store  # noqa: E402
from cfdcalc.instruments import BY_SYMBOL  # noqa: E402
from cfdcalc.report import write_csv, write_html  # noqa: E402
from cfdcalc.validation import SEED, research  # noqa: E402

DUKA = ["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "WTI/USD", "AAPL", "NVDA", "MSFT", "TSLA"]
YAHOO_STOCKS = ["AAPL", "NVDA", "MSFT", "TSLA"]


def log(msg: str):
    print(f"[{datetime.now(timezone.utc):%H:%M:%S}] {msg}", flush=True)


def costs_for(symbol: str) -> Costs:
    floor = BY_SYMBOL[symbol].spread           # typical Trading 212 spread from the catalogue
    return Costs(spread_floor=floor, slippage=0.1 * floor)


def do_import(args) -> list[tuple[str, str]]:
    """Returns the (symbol, source) pairs that have verified data."""
    st = Store(args.db)
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=31 * args.months)
    ok: list[tuple[str, str]] = []

    def duka(symbol):
        http = sources.Http(Path(args.cache) / "dukascopy", min_interval=0.15)
        t0 = time.monotonic()
        summary = importer.import_dukascopy(Store(args.db), symbol, start, end, http)
        return symbol, summary, http.requests, time.monotonic() - t0

    symbols = [s for s in args.symbols if s in sources.DUKASCOPY]
    with ThreadPoolExecutor(max_workers=3) as pool:
        for fut in [pool.submit(duka, s) for s in symbols]:
            try:
                symbol, summary, req, secs = fut.result()
                log(f"Dukascopy {symbol}: {summary} ({req} dotazů, {secs:.0f} s)")
                ok.append((symbol, "dukascopy"))
            except Exception as e:  # noqa: BLE001 - one provider failure must not stop the others
                log(f"Dukascopy chyba: {type(e).__name__}: {e}")
    http = sources.Http(None, min_interval=1.0)
    yahoo_1h = {}
    for symbol in sorted({s for s in args.symbols if s in sources.YAHOO}):
        try:
            if symbol in YAHOO_STOCKS:
                log(f"Yahoo {symbol}: {importer.import_yahoo(st, symbol, http)}")
                ok.append((symbol, "yahoo"))
            yahoo_1h[symbol] = sources.yahoo(symbol, "1h", http).bars
        except Exception as e:  # noqa: BLE001
            log(f"Yahoo {symbol} chyba: {type(e).__name__}: {e}")
    verified = []
    for symbol, source in ok:
        if source == "dukascopy":
            problem = importer.verify_level(st, symbol, sources.DUKASCOPY[symbol][0], yahoo_1h.get(symbol, []),
                                            tolerance=0.05)
            if problem and not problem.startswith("nelze ověřit"):
                log(f"{symbol}/dukascopy VYŘAZENO: {problem}")
                continue
            log(f"{symbol}/dukascopy ověření cenové hladiny: {problem or 'OK (do 5 % od Yahoo)'}")
        verified.append((symbol, source))
    return verified


def analyse(job):
    db, symbol, source, calendar = job
    st = Store(db)
    m = importer.market(st, symbol, source)
    if calendar:
        importer.attach_calendar(m, st, BY_SYMBOL[symbol].currencies)
    t0 = time.monotonic()
    res = research(m, costs_for(symbol))
    res["source"] = source
    res["seconds"] = time.monotonic() - t0
    return res


def provenance(db: str) -> list[dict]:
    st = Store(db)
    rows = []
    for s in st.all_series():
        if s.interval != "5min":
            continue
        a, b, n = st.span(s)
        q = st.quality(s)
        rows.append({"symbol": s.symbol, "source": s.source, "provider_symbol": s.provider_symbol, "kind": s.kind,
                     "side": s.side, "interval": s.interval, "start": f"{a:%Y-%m-%d}" if a else "",
                     "end": f"{b:%Y-%m-%d}" if b else "", "bars": n,
                     "severe": sum(1 for _, p, _ in q if p != "gap"), "gaps": sum(1 for _, p, _ in q if p == "gap"),
                     "digest": st.digest(s), "adjusted": s.adjusted, "volume": s.volume_kind,
                     "downloaded": s.downloaded_at, "licence": s.licence, "notes": s.notes})
    return rows


def load_calendar(db: str, events_csv: str, coverage_csv: str | None) -> str:
    st = Store(db)
    with open(events_csv, encoding="utf-8") as f:
        events = [{"event_id": r["event_id"], "release": datetime.fromisoformat(r["release_utc"]),
                   "known_since": datetime.fromisoformat(r["known_since_utc"]) if r.get("known_since_utc") else None,
                   "scheduled": r.get("scheduled", "1") in ("1", "true", "True"), "currency": r["currency"],
                   "title": r["title"], "impact": r["impact"]} for r in csv.DictReader(f)]
    coverage = []
    if coverage_csv:
        with open(coverage_csv, encoding="utf-8") as f:
            coverage = [(r["currency"], datetime.fromisoformat(r["start_utc"]), datetime.fromisoformat(r["end_utc"]))
                        for r in csv.DictReader(f)]
    st.put_events("csv", events, coverage)
    return f"historický kalendář z {events_csv}: {len(events)} událostí, pokrytí {len(coverage)} úseků"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--symbols", nargs="*", default=DUKA)
    ap.add_argument("--db", default="research/history.sqlite")
    ap.add_argument("--cache", default="research/cache")
    ap.add_argument("--out", default="research/report")
    ap.add_argument("--workers", type=int, default=os.cpu_count() or 2)
    ap.add_argument("--skip-import", action="store_true")
    ap.add_argument("--calendar")
    ap.add_argument("--calendar-coverage")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    news = "historický kalendář nebyl k dispozici – filtr zpráv NETESTOVÁN"
    if args.calendar:
        news = load_calendar(args.db, args.calendar, args.calendar_coverage)
    if args.skip_import:
        jobs = [(s.symbol, s.source) for s in Store(args.db).all_series() if s.interval == "5min" and
                s.side in ("mid", "last")]
    else:
        jobs = do_import(args)
    if not jobs:
        log("Žádná ověřená data – výzkum NEPROVEDEN.")
        return 1
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(analyse, (args.db, s, src, bool(args.calendar))): (s, src) for s, src in jobs}
        for fut, (s, src) in futs.items():
            try:
                r = fut.result()
                log(f"{s}/{src}: hotovo za {r['seconds']:.0f} s; test v2.1 {r['final']['metrics']['n']} obchodů, "
                    f"⌀ {r['final']['metrics']['exp']} R, interval {r['final']['ci']}")
                results.append(r)
            except Exception as e:  # noqa: BLE001
                log(f"{s}/{src} analýza selhala: {type(e).__name__}: {e}")
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                check=False).stdout.strip()
    except OSError:
        commit = "?"
    prov = provenance(args.db)
    out = Path(args.out)
    write_csv(results, prov, out)
    path = write_html(results, prov, {"commit": commit, "seed": SEED, "news": news}, out)
    log(f"Report: {path}")
    for r in results:
        f = r["final"]
        log(f"SOUHRN {r['symbol']}/{r['source']}: test n={f['metrics']['n']} exp={f['metrics']['exp']} "
            f"ci={f['ci']} p_adj={f['p_adjusted']} edge={f['edge']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

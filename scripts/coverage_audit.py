"""v2.5 coverage audit: identity and plan of every catalogue / candidate instrument at Twelve Data, plus Coinbase.

Uses only PUBLIC endpoints (no API key, nothing secret is sent or printed):
  * Twelve Data GET /symbol_search?symbol=...&show_plan=true -> name, exchange, MIC, currency, type, country, access
  * Coinbase Exchange GET /products/{BTC-USD}/candles?granularity=300|900|3600 -> candles available without a key
Usage:  python scripts/coverage_audit.py [--out audit]      (writes audit/audit.json and audit/audit.md)
A symbol listed here is NOT yet proof that your Twelve Data plan returns candles for it; the access field says
which plan it needs (when Twelve Data reports it).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc.instruments import CATALOG, COINBASE, TWELVE, sources  # noqa: E402

UA = {"User-Agent": "cfd-signal-calculator-audit"}
# every Twelve Data source of the catalogue is checked: (category, symbol, pinned exchange, plan the catalogue declares)
ITEMS = [(f"{i.kind}{' (ref)' if not src.exact else ''}", src.symbol, src.exchange, src.plan)
         for i in CATALOG for src in sources(i) if src.provider == TWELVE]
ITEMS = list(dict.fromkeys(ITEMS))
COINBASE_PRODUCTS = [src.symbol.replace("/", "-") for i in CATALOG for src in sources(i) if src.provider == COINBASE]


def get(url: str):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310 - fixed https hosts
            return r.status, dict(r.headers), json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8", "replace"))
        except (ValueError, OSError):
            body = None
        return e.code, dict(e.headers or {}), body
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return None, {}, {"error": type(e).__name__}


def search(symbol: str, exchange: str) -> dict:
    q = {"symbol": symbol.split("/")[0] if exchange else symbol, "outputsize": 30, "show_plan": "true"}
    status, headers, body = get("https://api.twelvedata.com/symbol_search?" + urllib.parse.urlencode(q))
    rows = (body or {}).get("data") or [] if isinstance(body, dict) else []
    exact = [r for r in rows if str(r.get("symbol", "")).upper() == symbol.upper()
             and (not exchange or exchange.upper() in (str(r.get("exchange", "")).upper(),
                                                         str(r.get("mic_code", "")).upper()))]
    keep = ("symbol", "instrument_name", "exchange", "mic_code", "currency", "instrument_type", "country", "access")
    return {"status": status, "match": [{k: r.get(k) for k in keep} for r in exact[:4]],
            "credit_headers": {k: v for k, v in headers.items() if "credit" in k.lower()}}


def coinbase(product: str) -> dict:
    out = {}
    for g in (300, 900, 3600):
        status, _, body = get(f"https://api.exchange.coinbase.com/products/{product}/candles?granularity={g}")
        out[g] = (status, len(body) if isinstance(body, list) else str(body)[:80])
        time.sleep(0.4)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="audit")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    res = {"twelvedata": {}, "coinbase": {}}
    lines = ["| kategorie | symbol | výsledek | název | burza / MIC | měna | typ | tarif TD (katalog) |",
             "|---|---|---|---|---|---|---|---|"]
    bad = 0
    for cat, sym, ex, plan in ITEMS:
        r = search(sym, ex)
        res["twelvedata"][f"{sym}@{ex}"] = {"category": cat, **r}
        m = r["match"][0] if r["match"] else {}
        got = (m.get("access") or {}).get("plan", "?")
        ok = bool(m) and got == plan
        bad += not ok
        lines.append(f"| {cat} | {sym}{' (' + ex + ')' if ex else ''} | {'OK' if ok else 'NESOUHLASÍ'} | "
                     f"{m.get('instrument_name', '–')} | {m.get('exchange', '–')} / {m.get('mic_code', '–')} | "
                     f"{m.get('currency', '–')} | {m.get('instrument_type', '–')} | {got} ({plan}) |")
        print(lines[-1], flush=True)
        time.sleep(1.1)        # polite: public endpoint, no key
    print(f"AUDIT: {len(ITEMS) - bad}/{len(ITEMS)} zdrojů Twelve Data odpovídá katalogu (symbol, burza, tarif)")
    for sym in COINBASE_PRODUCTS:
        res["coinbase"][sym] = coinbase(sym)
        print(f"Coinbase {sym}: {res['coinbase'][sym]}", flush=True)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "audit.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    hdrs = {k: v["credit_headers"] for k, v in res["twelvedata"].items() if v["credit_headers"]}
    print("credit headers seen:", json.dumps(dict(list(hdrs.items())[:3]), ensure_ascii=False))
    print("AUDIT-JSON-BEGIN")
    print(json.dumps(res, ensure_ascii=False))
    print("AUDIT-JSON-END")
    return 0


if __name__ == "__main__":
    sys.exit(main())

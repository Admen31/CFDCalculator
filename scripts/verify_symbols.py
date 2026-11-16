"""Check every catalogue symbol against Twelve Data's public symbol search (reference data, no trading).

Usage: python scripts/verify_symbols.py   (optional TWELVEDATA_API_KEY env var is sent as a header)
Prints, per instrument, what Twelve Data lists under that symbol, and exits 1 when a symbol is missing or
looks like a different instrument type. Informational in CI (network/plan dependent).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc.instruments import CATALOG  # noqa: E402

EXPECTED = {"forex": ("physical currency",), "commodity": ("physical currency", "commodit"),
            "index": ("index",), "stock": ("common stock", "stock")}


def search(symbol: str) -> list[dict]:
    url = "https://api.twelvedata.com/symbol_search?" + urllib.parse.urlencode({"symbol": symbol, "outputsize": 30})
    headers = {"User-Agent": "cfd-signal-calculator-verify"}
    if os.environ.get("TWELVEDATA_API_KEY"):
        headers["Authorization"] = f"apikey {os.environ['TWELVEDATA_API_KEY']}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:  # nosec B310
        body = json.loads(r.read().decode("utf-8"))
    return body.get("data") or []


def main() -> int:
    bad = 0
    for inst in CATALOG:
        try:
            rows = [x for x in search(inst.symbol) if x.get("symbol", "").upper() == inst.symbol.upper()]
        except Exception as e:  # noqa: BLE001 - report and continue
            print(f"?? {inst.symbol:9} {inst.name:22} chyba dotazu: {type(e).__name__}: {e}")
            bad += 1
            continue
        types = {str(x.get("instrument_type", "")).lower() for x in rows}
        ok = any(any(e in t for e in EXPECTED[inst.kind]) for t in types)
        names = "; ".join(sorted({f"{x.get('instrument_name')} [{x.get('instrument_type')}, "
                                  f"{x.get('exchange')}, {x.get('country')}]" for x in rows})[:4])
        print(f"{'OK' if ok else '!!'} {inst.symbol:9} {inst.name:22} {names or 'NENALEZENO'}")
        bad += not ok
        time.sleep(0.4)
    print(f"\n{len(CATALOG) - bad}/{len(CATALOG)} symbolů odpovídá očekávanému typu.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

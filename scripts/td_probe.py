"""Twelve Data diagnostics for a symbol (default: XAG/USD, XAU/USD, EUR/USD). Never prints the API key.

  python scripts/td_probe.py                      # public checks only (no key needed)
  set TWELVEDATA_API_KEY=...  &  python scripts/td_probe.py XAG/USD
Public part: the symbol catalogue (symbol_search) and the format of a real error response (time_series without
key). With TWELVEDATA_API_KEY: availability of 5min/15min/1h per symbol and the plan category (5 requests per
symbol; free plan allows 8 per minute, so the script waits between symbols).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from cfdcalc.data import DataError, TwelveData, classify  # noqa: E402


def public(path: str, params: dict):
    url = f"https://api.twelvedata.com/{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "cfd-signal-calculator-diagnostics"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:  # nosec B310 - fixed https host
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", "replace"))
        except ValueError:
            return e.code, None


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    symbols = sys.argv[1:] or ["XAG/USD", "XAU/USD", "EUR/USD"]
    print("== Veřejný katalog symbolů (bez klíče) ==")
    for sym in symbols:
        try:
            status, body = public("symbol_search", {"symbol": sym, "outputsize": 30})
            rows = [r for r in (body or {}).get("data", []) if str(r.get("symbol", "")).upper() == sym.upper()]
            print(f"{sym}: HTTP {status}; " + ("; ".join(f"{r.get('instrument_name')} [{r.get('instrument_type')}, "
                                                        f"{r.get('exchange') or '-'}]" for r in rows[:3]) or
                                               "v katalogu NENALEZEN"))
        except Exception as e:  # noqa: BLE001 - diagnostics continue
            print(f"{sym}: katalog nedostupný ({type(e).__name__})")
    print("\n== Formát chybové odpovědi time_series bez klíče (ověření parseru) ==")
    try:
        status, body = public("time_series", {"symbol": symbols[0], "interval": "5min", "outputsize": 2})
        kind, confirmed, msg = classify(status, body)
        code = body.get("code") if isinstance(body, dict) else None
        print(f"HTTP {status}, code v JSON: {code}, status: {(body or {}).get('status')}, "
              f"klasifikace: {kind} (potvrzeno: {confirmed}); zpráva: {msg[:160]}")
    except Exception as e:  # noqa: BLE001
        print(f"nedostupné ({type(e).__name__})")
    key = os.environ.get("TWELVEDATA_API_KEY", "").strip()
    if not key:
        print("\nTWELVEDATA_API_KEY není nastaven – kontrola dat s klíčem PŘESKOČENA (nic nebylo ověřeno s tarifem).")
        return 0
    td = TwelveData(key)
    for n, sym in enumerate(symbols):
        if n:
            time.sleep(40)          # stay well below 8 requests per minute
        print(f"\n== {sym} s API klíčem ==")
        try:
            for check, status, detail, kind in td.probe(sym):
                print(f"{'OK  ' if status == 'ok' else 'CHYBA' if status == 'fail' else 'info'} {check}: "
                      f"{td.redact(detail)} [{kind}]")
        except DataError as e:
            print(f"CHYBA {td.redact(str(e))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

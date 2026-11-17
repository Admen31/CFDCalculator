"""v2.2.1: Twelve Data error diagnostics, API-key protection, no instrument substitution, availability record."""
import io
import json
import socket
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from conftest import T0, FakeCalendar

from cfdcalc import data
from cfdcalc.analysis import NO_DATA, run_analysis
from cfdcalc.availability import Availability, state_text
from cfdcalc.data import DataError, TwelveData, classify
from cfdcalc.instruments import BY_SYMBOL

KEY = "sk_live_1234567890abcdef"
SILVER = BY_SYMBOL["XAG/USD"]


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, body=None, raw=None):
    payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
    return urllib.error.HTTPError("https://api.twelvedata.com/time_series", code, "err", {}, io.BytesIO(payload))


def install(monkeypatch, behaviour):
    """behaviour(params) -> dict (JSON 200) | Exception to raise. Records every request."""
    seen = []

    def urlopen(req, timeout):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        params = {k: v[0] for k, v in q.items()}
        seen.append((req.full_url, dict(req.header_items()), params))
        out = behaviour(params)
        if isinstance(out, BaseException):
            raise out
        return Resp(out if isinstance(out, bytes) else json.dumps(out).encode())
    monkeypatch.setattr(data.urllib.request, "urlopen", urlopen)
    return seen


def bars_json(symbol, n=3):
    """n closed 5m bars ending at T0 (fresh for the analysis clock)."""
    t = T0.replace(second=0, tzinfo=None) - timedelta(minutes=5 * n)
    return {"status": "ok", "meta": {"symbol": symbol, "interval": "5min"},
            "values": [{"datetime": f"{t + timedelta(minutes=5 * k):%Y-%m-%d %H:%M:%S}", "open": "30.1",
                        "high": "30.2", "low": "30.0", "close": "30.15"} for k in range(n)]}


def fail_with(monkeypatch, exc):
    install(monkeypatch, lambda p: exc)
    with pytest.raises(DataError) as e:
        TwelveData(KEY).bars("XAG/USD", "5min", 300)
    return e.value


def test_404_with_provider_message_is_symbol_not_found(monkeypatch):
    msg = "**symbol** not found: XAG/USD. Please specify it correctly according to API documentation."
    e = fail_with(monkeypatch, http_error(404, {"code": 404, "message": msg, "status": "error"}))
    text = str(e)
    assert e.kind == "not_found" and e.confirmed and e.status == 404 and e.interval == "5min"
    assert text.startswith("Silver (XAG/USD): Twelve Data neposkytla data pro interval 5min. HTTP 404.")
    assert "Poskytovatel symbol nenašel" in text and "symbol** not found" in text and "Další krok" in text


def test_404_without_explanation_is_not_guessed(monkeypatch):
    e = fail_with(monkeypatch, http_error(404, raw=b"<html>Not Found</html>"))
    assert e.kind == "unknown" and not e.confirmed and "HTTP 404" in str(e)
    assert "příčina nepotvrzena odpovědí poskytovatele" in str(e)
    assert "oprávnění API tarifu" in str(e)                     # the suggested next step


def test_404_no_data_for_interval(monkeypatch):
    e = fail_with(monkeypatch, http_error(404, {"code": 404, "status": "error",
                                                "message": "No data is available on the specified dates."}))
    assert e.kind == "no_data" and e.confirmed


@pytest.mark.parametrize("code, message, kind, confirmed", [
    (401, "**apikey** parameter is incorrect or not specified.", "auth", True),
    (403, "This symbol is available starting with the Grow plan. Consider upgrading.", "plan", True),
    (403, "", "plan", False),
    (429, "You have run out of API credits for the current minute.", "rate_limit", True),
    (500, "Internal server error", "server", True),
    (503, "", "server", True),
    (400, "**interval** parameter is invalid", "request", True),
])
def test_http_statuses(monkeypatch, code, message, kind, confirmed):
    body = {"code": code, "message": message, "status": "error"} if message else None
    e = fail_with(monkeypatch, http_error(code, body))
    assert (e.kind, e.confirmed, e.status) == (kind, confirmed, code)


def test_error_reported_in_a_200_response(monkeypatch):
    install(monkeypatch, lambda p: {"code": 403, "status": "error",
                                    "message": "This symbol is available starting with Pro plan."})
    with pytest.raises(DataError) as e:
        TwelveData(KEY).bars("XAG/USD", "15min", 300)
    assert e.value.kind == "plan" and e.value.status == 403 and "interval 15min" in str(e.value)


@pytest.mark.parametrize("exc, kind", [
    (TimeoutError("timed out"), "timeout"),
    (socket.timeout("timed out"), "timeout"),
    (urllib.error.URLError(socket.timeout("timed out")), "timeout"),
    (urllib.error.URLError(OSError("Name or service not known")), "connection"),
])
def test_timeouts_and_connection_errors(monkeypatch, exc, kind):
    assert fail_with(monkeypatch, exc).kind == kind


@pytest.mark.parametrize("payload, kind, words", [
    (b"not json at all", "invalid", "není JSON"),
    ({"status": "ok", "meta": {"symbol": "XAG/USD"}, "values": []}, "no_data", "0 svíček"),
    ({"status": "ok", "meta": {"symbol": "XAG/USD"}, "values": [{"datetime": "17.11.2026 10:00", "open": "1",
                                                                "high": "1", "low": "1", "close": "1"}]},
     "invalid", "neplatný čas"),
    ({"status": "ok", "meta": {"symbol": "XAG/USD"}, "values": [{"datetime": "2026-11-17 10:00:00", "open": "1",
                                                                "high": "", "low": "1", "close": "1"}]},
     "invalid", "chybí cena"),
])
def test_missing_candles_invalid_timestamps_and_bad_payloads(monkeypatch, payload, kind, words):
    install(monkeypatch, lambda p: payload)
    with pytest.raises(DataError) as e:
        TwelveData(KEY).bars("XAG/USD", "5min", 300)
    assert e.value.kind == kind and words in str(e.value)


def test_api_key_never_appears_in_messages(monkeypatch):
    echoed = f"Invalid request for apikey={KEY}&symbol=XAG/USD (key {KEY})"
    e = fail_with(monkeypatch, http_error(400, {"code": 400, "message": echoed, "status": "error"}))
    assert KEY not in str(e) and KEY not in e.provider_message and "apikey=***" in str(e)
    seen = install(monkeypatch, lambda p: bars_json("XAG/USD"))
    TwelveData(KEY).bars("XAG/USD", "5min", 300)
    url, headers, _ = seen[0]
    assert KEY not in url and headers.get("Authorization") == f"apikey {KEY}"   # key only in the header


def test_silver_is_never_substituted(monkeypatch):
    seen = install(monkeypatch, lambda p: bars_json(p["symbol"]))
    TwelveData(KEY).bars("XAG/USD", "1h", 300)
    params = seen[0][2]
    assert params["symbol"] == "XAG/USD" and "exchange" not in params and params["interval"] == "1h"
    assert params == {"symbol": "XAG/USD", "interval": "1h", "outputsize": "300", "timezone": "UTC",
                      "order": "asc"}
    install(monkeypatch, lambda p: bars_json("SI=F"))              # provider answers with another product
    with pytest.raises(DataError, match="vrácen jiný symbol: SI=F"):
        TwelveData(KEY).bars("XAG/USD", "5min", 300)
    assert SILVER.symbol == "XAG/USD" and SILVER.kind == "commodity" and "Silver" in SILVER.aliases


def test_analysis_reports_interval_and_source_and_stops_cleanly(monkeypatch):
    calls = []

    def behaviour(p):
        calls.append(p["symbol"])
        if p["interval"] == "15min":
            return http_error(404, {"code": 404, "status": "error", "message": "**symbol** not found: XAG/USD"})
        return bars_json(p["symbol"], 300)
    install(monkeypatch, behaviour)
    r = run_analysis(SILVER, TwelveData(KEY), FakeCalendar(), 0.03, T0)
    # silver: 5min ok, 15min fails; then the labelled reference ETF is tried (fails the same way here)
    assert r.verdict == NO_DATA and r.completed == 5 and set(calls) == {"XAG/USD", "SLV"}   # 5m + 1h still read
    assert [(s[0], s[1], s[2], s[3]) for s in r.sources][:2] == [("Twelve Data", "XAG/USD", "5min", "OK"),
                                                                 ("Twelve Data", "XAG/USD", "15min", "not_found")]
    assert "XAG/USD" in r.summary and "zdrojů: 2" in r.summary
    # v2.6: 5m + 1h of ONE source are enough for the market direction (lower quality), never for a trade
    assert r.market and r.market.side in ("BUY", "SELL", "NEUTRAL", "NO DATA") and r.market.quality < 1
    assert "interval 15min" in r.summary and "HTTP 404" in r.summary and KEY not in r.summary


def test_classify_does_not_trust_status_alone():
    assert classify(404, None) == ("unknown", False, "")
    assert classify(403, {"message": ""})[:2] == ("plan", False)
    assert classify(200, {"code": 429, "message": "run out of API credits"})[0] == "rate_limit"


def test_availability_record_and_summary(tmp_path):
    av = Availability(tmp_path / "a.json")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
    assert av.summary("Twelve Data", "XAG/USD", now)[0] == "neověřeno"
    for iv in ("5min", "15min", "1h"):
        av.record("Twelve Data", "XAU/USD", iv, "OK", "ok", now)
    assert av.summary("Twelve Data", "XAU/USD", now)[0] == "ověřeno"
    av.record("Twelve Data", "XAG/USD", "5min", "not_found", "HTTP 404", now)
    state, text = Availability(tmp_path / "a.json").summary("Twelve Data", "XAG/USD", now)   # persisted
    assert state == "nedostupné" and "XAG/USD 5min" in text
    assert Availability(tmp_path / "a.json").summary("Twelve Data", "XAG/USD", now + timedelta(days=2))[0] \
        == "neověřeno"                                                       # failures expire after a day
    av.record("Twelve Data", "EUR/USD", "5min", "rate_limit", "429", now)
    assert av.summary("Twelve Data", "EUR/USD", now)[0] == "neověřeno"    # transient: not "unavailable"
    assert state_text("not_found").startswith("nedostupné") and state_text("OK") == "dostupné"


def test_probe_reports_each_interval_without_key(monkeypatch):
    def behaviour(p):
        if "interval" not in p and "outputsize" in p:     # symbol_search
            return {"data": [{"symbol": "XAG/USD", "instrument_name": "Silver Spot / US Dollar",
                              "instrument_type": "Precious Metal", "exchange": ""}]}
        if "interval" not in p:                            # api_usage
            return {"current_usage": 3, "plan_limit": 8, "plan_category": "basic"}
        if p["interval"] == "5min":
            return http_error(404, {"code": 404, "status": "error", "message": "**symbol** not found"})
        return bars_json("XAG/USD")
    install(monkeypatch, behaviour)
    rows = TwelveData(KEY).probe("XAG/USD")
    kinds = {check: kind for check, _, _, kind in rows}
    assert kinds["Katalog symbolů"] == "OK" and kinds["Svíčky 5min"] == "not_found"
    assert kinds["Svíčky 15min"] == kinds["Svíčky 1h"] == "OK"
    assert "basic" in rows[-1][2] and all(KEY not in detail for _, _, detail, _ in rows)

"""v2.5: multi-provider sources, plan-aware requests, API limits, identity checks, directory instruments.

All provider responses are mocked here (no network); live checks run in CI (scripts/coverage_audit.py).
"""
import io
import json
import urllib.error
import urllib.parse
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from conftest import T0, FakeCalendar, FakeProvider
from test_data_errors import KEY, Resp, bars_json, install

from cfdcalc import data
from cfdcalc.analysis import BUY, NO_DATA, SELL, WAIT, Settings, market_end, run_analysis
from cfdcalc.data import CachedProvider, Coinbase, DataError, TwelveData, synthetic_bars
from cfdcalc.instruments import BY_SYMBOL, CATALOG, COINBASE, TWELVE, from_directory, plan_ok, sources

BTC, SILVER, SPX, EUR = BY_SYMBOL["BTC/USD"], BY_SYMBOL["XAG/USD"], BY_SYMBOL["SPX"], BY_SYMBOL["EUR/USD"]


def candles(now, minutes, n=350):
    """Coinbase rows [time, low, high, open, close, volume], newest first."""
    out = []
    for k in range(n):
        t = now.replace(second=0, microsecond=0) - timedelta(minutes=minutes * (k + 1))
        t = t - timedelta(minutes=t.minute % minutes)
        p = 60000 + k
        out.append([int(t.timestamp()), p - 5, p + 5, p - 1, p + 1, 1.5])
    return out


def coinbase_net(monkeypatch, behaviour):
    seen = []

    def urlopen(req, timeout):
        seen.append(req.full_url)
        out = behaviour(req.full_url)
        if isinstance(out, BaseException):
            raise out
        return Resp(json.dumps(out).encode())
    monkeypatch.setattr(data.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    return seen


# ---------------------------------------------------------------- catalogue and identity

def test_catalogue_coverage_by_category():
    kinds = {}
    for i in CATALOG:
        kinds[i.kind] = kinds.get(i.kind, 0) + 1
    assert len(CATALOG) >= 160 and kinds["forex"] >= 40 and kinds["crypto"] >= 12 and kinds["etf"] >= 18
    assert kinds["stock"] >= 80 and kinds["index"] >= 6
    basic = [i for i in CATALOG if any(s.exact and plan_ok(s, "Basic") for s in sources(i))]
    assert len(basic) >= 140                       # fully analysable on the free plan (exact source, Basic)


def test_plan_filter_and_reference_order():
    assert [s.symbol for s in sources(SILVER)] == ["XAG/USD", "SLV"] and not sources(SILVER)[1].exact
    assert not plan_ok(sources(SILVER)[0], "Basic") and plan_ok(sources(SILVER)[0], "Grow")
    assert plan_ok(sources(BTC)[0], "Basic") and sources(BTC)[0].provider == COINBASE


@pytest.mark.parametrize("row, error", [
    ({"symbol": "RHM", "exchange": "XETR", "mic_code": "XETR", "currency": "EUR", "instrument_type": "Common Stock",
      "plan": "Grow"}, None),
    ({"symbol": "XYZ", "exchange": "TSE", "mic_code": "XTKS", "currency": "JPY", "instrument_type": "Common Stock"},
     "obchodní hodiny"),
    ({"symbol": "ABC", "exchange": "NYSE", "mic_code": "XNYS", "currency": "", "instrument_type": "Common Stock"},
     "identita"),
    ({"symbol": "NVDA", "exchange": "NASDAQ", "mic_code": "XNGS", "currency": "USD",
      "instrument_type": "Common Stock"}, "už v katalogu"),
    ({"symbol": "QQQX", "exchange": "NASDAQ", "mic_code": "XNGS", "currency": "USD", "instrument_type": "Warrant"},
     "není podporován"),
])
def test_directory_instruments_need_a_verifiable_identity(row, error):
    if error:
        with pytest.raises(ValueError, match=error):
            from_directory(row)
        return
    inst = from_directory(row, "Rheinmetall")
    assert inst.custom and inst.exchange == "XETR" and inst.currency == "EUR" and inst.session[0] == "Europe/Berlin"
    assert inst.sources[0].plan == "Grow" and inst.name == "Rheinmetall" and inst.spread == 0.0


def test_identity_checks_on_every_response(monkeypatch):
    install(monkeypatch, lambda p: dict(bars_json(p["symbol"]), meta={"symbol": "SAP", "exchange": "XETR",
                                                                       "currency": "USD"}))
    with pytest.raises(DataError, match="v měně USD"):
        TwelveData(KEY).bars("SAP", "5min", 3)                       # catalogue says EUR
    install(monkeypatch, lambda p: dict(bars_json(p["symbol"]), meta={"symbol": "SPY", "exchange": "BCBA"}))
    with pytest.raises(DataError, match="z burzy BCBA"):
        TwelveData(KEY).bars("SPY", "5min", 3, exchange="NYSE")


def test_reference_listing_bypasses_only_with_an_explicit_exchange(monkeypatch):
    seen = install(monkeypatch, lambda p: dict(bars_json(p["symbol"]), meta={"symbol": "DAX", "exchange": "NASDAQ"}))
    with pytest.raises(DataError) as e:
        TwelveData(KEY).bars("DAX", "5min", 3)                       # the Germany 40 CFD key is unmapped
    assert e.value.kind == "unmapped" and not seen
    TwelveData(KEY).bars("DAX", "5min", 3, exchange="NASDAQ")        # the verified ETF listing
    assert seen[-1][2]["exchange"] == "NASDAQ"


# ---------------------------------------------------------------- Coinbase

def test_coinbase_parses_sorts_and_classifies(monkeypatch):
    now = datetime(2026, 11, 17, 15, 2, tzinfo=timezone.utc)
    seen = coinbase_net(monkeypatch, lambda url: candles(now, 5))
    bars = Coinbase().bars("BTC/USD", "5min", 300)
    assert len(bars) == 300 and bars[0].t < bars[-1].t and bars[-1].v == 1.5
    assert "products/BTC-USD/candles?granularity=300" in seen[0]
    coinbase_net(monkeypatch, lambda url: urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(
        b'{"message": "NotFound"}')))
    with pytest.raises(DataError) as e:
        Coinbase().bars("FOO/USD", "1h", 300)
    assert e.value.kind == "not_found" and "Coinbase Exchange" in str(e.value)
    coinbase_net(monkeypatch, lambda url: [[1, "x"]])
    with pytest.raises(DataError, match="neplatná svíčka"):
        Coinbase().bars("BTC/USD", "15min", 300)


def test_crypto_uses_coinbase_and_falls_back_to_twelve_data():
    class Down:
        name = "Coinbase Exchange"

        def bars(self, *a, **k):
            raise DataError("down", "server", source="Coinbase Exchange")
    td = FakeProvider()
    r = run_analysis(BTC, {COINBASE: Down(), TWELVE: td}, FakeCalendar(), 1.0, T0)
    assert r.verdict in (BUY, SELL, WAIT) and td.calls and not r.reference          # exact data from source 2
    assert [s[0] for s in r.sources][:1] == ["Coinbase Exchange"] and r.completed == r.total


def test_sources_are_never_mixed_between_timeframes():
    class Half(FakeProvider):
        name = "Half"

        def bars(self, symbol, interval, n, **kw):
            if interval == "1h":
                raise DataError("no 1h", "no_data")
            return super().bars(symbol, interval, n)
    second = FakeProvider()
    r = run_analysis(BTC, {COINBASE: Half(), TWELVE: second}, FakeCalendar(), 1.0, T0)
    assert sorted(second.calls) == ["15min", "1h", "5min"]     # all three again from the second source
    assert r.completed == r.total


# ---------------------------------------------------------------- plan, reference, closures

def test_plan_skips_without_request_and_reports_it():
    p = FakeProvider()
    only = replace(SILVER, sources=SILVER.sources[:1])               # no reference
    r = run_analysis(only, p, FakeCalendar(), 0.03, T0, Settings(td_plan="Basic"))
    assert r.verdict == NO_DATA and not p.calls and "vyžadují tarif Grow" in r.summary
    assert r.sources[0][3] == "plan"


def test_reference_data_give_direction_only():
    r = run_analysis(SPX, FakeProvider(drift=0.002), FakeCalendar(), 0.6, T0, Settings(td_plan="Basic"))
    assert r.reference and r.entry is None and r.sl is None and not r.is_signal
    assert r.reasons[0].startswith("REFERENČNÍ TRŽNÍ DATA – NEMUSÍ ODPOVÍDAT CENĚ TRADING 212 CFD.")
    assert ("Spread", "ref") in [(n, st) for n, st, _ in r.filters]


def test_weekend_closes_forex_but_not_crypto():
    sat = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
    assert market_end(EUR, sat, Settings())[0] is None and "víkend" in market_end(EUR, sat, Settings())[1]
    assert market_end(BTC, sat, Settings())[0] is not None
    p = FakeProvider()
    r = run_analysis(EUR, p, FakeCalendar(), 0.0001, sat)
    assert r.verdict == WAIT and "zavřený" in r.summary and not p.calls


# ---------------------------------------------------------------- API limits and cache

def test_retry_after_blocks_further_requests(monkeypatch):
    calls = install(monkeypatch, lambda p: urllib.error.HTTPError(
        "u", 429, "busy", {"Retry-After": "30"}, io.BytesIO(json.dumps(
            {"code": 429, "status": "error", "message": "You have run out of API credits"}).encode())))
    td = TwelveData(KEY)
    with pytest.raises(DataError) as e:
        td.bars("EUR/USD", "5min", 3)
    assert e.value.kind == "rate_limit"
    with pytest.raises(DataError, match="Retry-After"):
        td.bars("EUR/USD", "15min", 3)
    assert len(calls) == 1 and "pauza" in td.usage()                 # the second request never left the app


def test_daily_cap_and_credit_headers(monkeypatch):
    class WithHeaders(Resp):
        headers = {"api-credits-used": "3", "api-credits-left": "5"}
    seen = []

    def urlopen(req, timeout):
        seen.append(req.full_url)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)
        return WithHeaders(json.dumps(bars_json(q["symbol"][0])).encode())
    monkeypatch.setattr(data.urllib.request, "urlopen", urlopen)
    td = TwelveData(KEY, per_minute=100)
    td.per_day = 2
    td.bars("EUR/USD", "5min", 3)
    td.bars("EUR/USD", "15min", 3)
    with pytest.raises(DataError, match="denního limitu 2"):
        td.bars("EUR/USD", "1h", 3)
    assert len(seen) == 2 and "api-credits-left 5" in td.usage() and "dnes 2/2" in td.usage()


def test_cache_keeps_listings_apart():
    now = datetime(2026, 11, 17, 15, 0, 30, tzinfo=timezone.utc)

    class P:
        calls = []

        def bars(self, symbol, interval, n, exchange=""):
            self.calls.append(exchange)
            return synthetic_bars(now, 5, n, seed=len(exchange))
    p = P()
    c = CachedProvider(p, clock=lambda: now)
    c.bars("DAX", "5min", 300, exchange="NASDAQ")
    c.bars("DAX", "5min", 300, exchange="XETR")
    assert p.calls == ["NASDAQ", "XETR"]


# ---------------------------------------------------------------- availability page rows

def test_market_rows(tmp_path):
    from cfdcalc.availability import Availability
    from cfdcalc.ui_markets import row_for
    av = Availability(tmp_path / "a.json")
    assert row_for(BY_SYMBOL["NVDA"], "Basic", av)[-1].startswith("ano")
    row = row_for(SILVER, "Basic", av)
    assert row[-1].startswith("jen směr") and "SLV" in row[7]
    only = replace(SILVER, sources=SILVER.sources[:1])
    assert row_for(only, "Basic", av)[-1] == "ne – vyžaduje tarif Grow (nastaven Basic)"
    assert row_for(BTC, "Basic", av)[2].startswith("Coinbase Exchange + Twelve Data")
    av.record("Twelve Data", "NVDA", "5min", "not_found", "HTTP 404")
    assert row_for(BY_SYMBOL["NVDA"], "Basic", av)[-1].startswith("ne –")

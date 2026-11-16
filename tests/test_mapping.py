"""Twelve Data mapping: unverified symbols never reach the API, stocks are pinned to their exchange."""
import io
import json

import pytest

from cfdcalc import data
from cfdcalc.data import DataError, TwelveData
from cfdcalc.instruments import BY_SYMBOL, CATALOG


def test_catalogue_mapping_rules():
    for sym in ("SPX", "NDX", "DJI", "DAX", "FTSE", "NG/USD"):   # Twelve Data lists ETFs/other firms or nothing
        assert not BY_SYMBOL[sym].td_verified
    for inst in CATALOG:
        if inst.kind == "stock":
            assert inst.exchange in ("NASDAQ", "NYSE") and inst.td_verified, inst
        if inst.kind == "forex" or inst.symbol in ("XAU/USD", "XAG/USD", "WTI/USD", "XBR/USD"):
            assert inst.td_verified and not inst.exchange


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(seen, meta_exchange="NYSE"):
    def urlopen(req, timeout):
        seen.append(req.full_url)
        body = {"status": "ok", "meta": {"symbol": "BA", "exchange": meta_exchange},
                "values": [{"datetime": "2026-11-17 10:00:00", "open": "1", "high": "2", "low": "0.5",
                            "close": "1.5", "volume": "10"}]}
        return Resp(json.dumps(body).encode())
    return urlopen


def test_stock_request_pins_exchange_and_checks_response(monkeypatch):
    seen = []
    monkeypatch.setattr(data.urllib.request, "urlopen", fake_urlopen(seen))
    bars = TwelveData("k").bars("BA", "5min", 10)
    assert len(bars) == 1 and "exchange=NYSE" in seen[0] and "symbol=BA" in seen[0]
    monkeypatch.setattr(data.urllib.request, "urlopen", fake_urlopen(seen, meta_exchange="SET"))  # Bangkok Airways
    with pytest.raises(DataError, match="burzy SET"):
        TwelveData("k").bars("BA", "5min", 10)


def test_unverified_symbol_never_calls_the_api(monkeypatch):
    seen = []
    monkeypatch.setattr(data.urllib.request, "urlopen", fake_urlopen(seen))
    with pytest.raises(DataError, match="nemá ověřené mapování"):
        TwelveData("k").bars("SPX", "5min", 10)
    assert not seen


def test_forex_request_has_no_exchange(monkeypatch):
    seen = []
    monkeypatch.setattr(data.urllib.request, "urlopen", fake_urlopen(seen, meta_exchange=""))
    TwelveData("k").bars("EUR/USD", "5min", 10)
    assert "exchange" not in seen[0]

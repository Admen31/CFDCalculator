import os
import time
from datetime import datetime, timedelta, timezone

import pytest

from cfdcalc.calendar import Calendar, CalendarError, parse
from cfdcalc.recognize import match


@pytest.mark.parametrize("lines, symbol", [
    (["EUR/USD", "1.08452", "-0.12%"], "EUR/USD"),
    (["Brent Oil"], "XBR/USD"),
    (["Oil"], "WTI/USD"),
    (["US 500", "6012.4"], "SPX"),
    (["Germany 40"], "DAX"),
    (["Apple"], "AAPL"),
    (["Gold", "2650.12"], "XAU/USD"),
    (["EURUSD"], "EUR/USD"),
])
def test_match_confident(lines, symbol):
    r = match(lines)
    assert r.confident and r.best.symbol == symbol, r


@pytest.mark.parametrize("lines", [["Portfolio", "History"], [], ["EUR/USD", "GBP/USD"]])
def test_match_uncertain_offers_manual_choice(lines):
    r = match(lines)
    assert not r.confident and r.best is None


def test_ocr_typo_still_suggested():
    r = match(["EUR/U5D"])
    assert r.candidates[0].symbol == "EUR/USD"


FEED = [
    {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-11-06T08:30:00-05:00", "impact": "High"},
    {"title": "broken", "country": "EUR", "date": "not a date", "impact": "High"},
]


def test_parse_converts_to_utc_and_skips_garbage():
    ev = parse(FEED)
    assert len(ev) == 1 and ev[0].time == datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc)


def test_calendar_caches_and_fails_closed(tmp_path):
    cache = tmp_path / "cal.json"
    calls = []
    cal = Calendar(cache, fetch=lambda: calls.append(1) or FEED)
    assert len(cal.events()) == 1 and len(cal.events()) == 1 and calls == [1]  # second read from cache

    def down():
        raise OSError("offline")
    old = time.time() - 2 * 3600
    os.utime(cache, (old, old))
    assert len(Calendar(cache, fetch=down).events()) == 1          # 2 h old cache still trusted
    old = time.time() - 7 * 3600
    os.utime(cache, (old, old))
    with pytest.raises(CalendarError):
        Calendar(cache, fetch=down).events()                         # too old -> fail closed
    with pytest.raises(CalendarError):
        Calendar(tmp_path / "none.json", fetch=lambda: {"bad": 1}).events()



def test_weekly_cache_is_trusted_for_a_day_only_while_it_covers_today(tmp_path):
    cache = tmp_path / "cal.json"
    now = datetime.now(timezone.utc)
    week = [{"title": "CPI", "country": "USD", "date": (now - timedelta(days=1)).isoformat(), "impact": "High"},
            {"title": "NFP", "country": "USD", "date": (now + timedelta(days=1)).isoformat(), "impact": "High"}]
    Calendar(cache, fetch=lambda: week).events()

    def down():
        raise OSError("429")
    old = time.time() - 20 * 3600
    os.utime(cache, (old, old))
    assert len(Calendar(cache, fetch=down).events()) == 2            # 20 h, but this week's schedule
    old = time.time() - 25 * 3600
    os.utime(cache, (old, old))
    with pytest.raises(CalendarError, match="stará"):
        Calendar(cache, fetch=down).events()

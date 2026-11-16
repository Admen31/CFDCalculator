import socket
from datetime import datetime, timedelta, timezone

import pytest

from cfdcalc.data import synthetic_bars

T0 = datetime(2026, 11, 17, 8, 0, 30, tzinfo=timezone.utc)  # Tuesday, well before the evening cut-off
FRAMES = (("5min", 5), ("15min", 15), ("1h", 60))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def deny(*a, **k):
        raise RuntimeError("network access in tests")
    monkeypatch.setattr(socket, "create_connection", deny)


class FakeProvider:
    """Synthetic market: drift>0 trends up. k shifts time and seed (k=0 up -> BUY, k=10 down -> SELL)."""

    def __init__(self, drift=0.002, k=0, now=None, fail=None):
        self.drift, self.k, self.fail = drift, k, fail
        self.now = now or T0 + timedelta(minutes=k)
        self.calls = []

    def bars(self, symbol, interval, n):
        self.calls.append(interval)
        if self.fail == interval:
            from cfdcalc.data import DataError
            raise DataError("Twelve Data: symbol not available on your plan")
        m = dict(FRAMES)[interval]
        return synthetic_bars(self.now, m, n, drift=self.drift, noise=0.05,
                              seed=m + self.k)


class FakeCalendar:
    def __init__(self, events=(), fail=False):
        self._events, self.fail = list(events), fail

    def events(self):
        if self.fail:
            from cfdcalc.calendar import CalendarError
            raise CalendarError("down")
        return self._events

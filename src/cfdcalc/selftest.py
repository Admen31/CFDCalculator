"""v2.9 self-test of the PACKAGED application on a real Windows desktop:

    "CFD Signal Calculator.exe" --selftest <out-dir>          scenarios A-H + J, writes report.json + screenshots
    "CFD Signal Calculator.exe" --selftest-verify <out-dir>   scenario I: a NEW process reads the saved settings

What is REAL: the packaged EXE, its Qt GUI on the Windows desktop, Win32 window search and capture of another
window, the bundled offline OCR (RapidOCR / onnxruntime), the M15 analysis, the trade plan, the v2.4 risk
calculation, QSettings + DPAPI storage and repeated clicks.
What is SIMULATED (and reported as such): the "Trading 212" window is a picture drawn by this test (tabs Silver,
NVIDIA, Gold, EUR/USD; NOT the real Trading 212), and the M15 prices are deterministic test data (no API key,
no network). Nothing here verifies the live Trading 212 or the live Twelve Data account.
"""
from __future__ import annotations

import json
import random
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from . import m15
from .data import Bar

TABS = ["Silver", "NVIDIA", "Gold", "EUR/USD"]
SEEDS = {"confirmed_sell": 99, "confirmed_buy": 44, "conditional_sell": 0}
SELFTEST_KEY = "selftest-key-0000"


def walk(now: datetime, n: int = 400, seed: int = 1, base: float = 1.1, vol: float = 0.0008) -> list[Bar]:
    """Deterministic 15m random walk; the last bar is the one forming at `now` (same as tests/test_m15.walk)."""
    rnd = random.Random(seed)
    step = timedelta(minutes=15)
    start = m15.period_start(now) - step * (n - 1)
    out, p = [], base
    for i in range(n):
        o = p
        c = o * (1 + rnd.gauss(0, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, vol / 2)))
        lo = min(o, c) * (1 - abs(rnd.gauss(0, vol / 2)))
        out.append(Bar(start + step * i, o, h, lo, c, None))
        p = c
    return out


def market_time() -> datetime:
    """A Tuesday 15:00:30 UTC (markets open, far from the evening limit), independent of when CI runs."""
    d = datetime.now(timezone.utc).replace(hour=15, minute=0, second=30, microsecond=0)
    while d.weekday() != 1:
        d += timedelta(days=1)
    return d


class Provider:
    """Deterministic 15min data (test data, not the market)."""
    name = "Twelve Data (selftest data)"
    pins_exchange = True

    def __init__(self, clock):
        self.clock, self.seed, self.short, self.calls, self.intervals = clock, SEEDS["confirmed_sell"], False, 0, []

    def bars(self, symbol, interval, n, exchange=None):
        self.calls += 1
        self.intervals.append(interval)
        base = 2000.0 if symbol == "XAU/USD" else 1.1
        bars = walk(self.clock.t, seed=self.seed, base=base)
        return (bars[-100:] if self.short else bars)[-n:]


def draw(active: str, w: int = 1000, h: int = 640):
    """Representative Trading 212 web screen as a QPixmap (real desktop fonts)."""
    from PySide6.QtCore import QRect, Qt
    from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
    pm = QPixmap(w, h)
    pm.fill(QColor("#101319"))
    p = QPainter(pm)

    def text(x, y, t, size, color="#e6e6e6", bold=False):
        f = QFont("Segoe UI")
        f.setPixelSize(size)
        f.setBold(bold)
        p.setFont(f)
        p.setPen(QColor(color))
        p.drawText(QRect(x, y, 400, int(size * 1.6)), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, t)

    p.fillRect(0, 0, w, 48, QColor("#161a22"))
    x = 250
    for t in TABS:
        if t == active:
            p.fillRect(x - 14, 6, 132, 38, QColor("#2e3a52"))
        text(x, 12, t, 15, "#ffffff" if t == active else "#c9ced6")
        x += 150
    text(16, 58, "Watchlist", 12, "#8b93a1")
    for i, (n, px) in enumerate([("Silver", "51.84"), ("NVIDIA", "182.40"), ("Gold", "4,083.45"),
                                 ("EUR/USD", "1.15242"), ("GBP/USD", "1.31842")]):
        text(16, 90 + 36 * i, n, 13)
        text(150, 90 + 36 * i, px, 13, "#8b93a1")
    p.fillRect(260, 140, 120, 56, QColor("#3b1d22"))
    p.fillRect(392, 140, 120, 56, QColor("#16341f"))
    eur = "EUR" in active
    text(272, 144, "SELL", 13, "#f87171", True)
    text(272, 164, "1.15234" if eur else "4,083.10", 16, "#f87171", True)
    text(404, 144, "BUY", 13, "#4ade80", True)
    text(404, 164, "1.15242" if eur else "4,083.45", 16, "#4ade80", True)
    p.end()
    return pm


def pump(app, ms: int):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def run(out: Path) -> int:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication, QLabel

    from . import apikey, risk, ui, ui_risk
    out.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(out / "settings"))
    ui.data_dir = lambda: out
    report: dict = {"real": ["packaged EXE", "Qt GUI on the Windows desktop", "Win32 window search + capture",
                             "bundled OCR (RapidOCR/onnxruntime)", "M15 analysis + trade plan", "risk.size",
                             "QSettings + DPAPI"],
                    "simulated": ["Trading 212 window = drawn picture (not the real Trading 212)",
                                  "M15 prices = deterministic test data (no API, no network)"],
                    "scenarios": {}, "screens": []}

    def res(name, ok, detail):
        report["scenarios"][name] = {"result": "PASS" if ok else "FAIL", "detail": detail}

    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(ui.STYLE)

    class Clock(datetime):
        t = market_time()

        @classmethod
        def now(cls, tz=None):
            return cls.t
    ui.datetime = Clock
    ui_risk.datetime = Clock

    class NoNews:                            # the live calendar is not part of this test (deterministic result)
        def __init__(self, *_a):
            pass

        def events(self):
            return []
    ui.Calendar = NoNews
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "CFDSignalCalculator", "app")
    s.clear()
    for k, v in (("mode", "auto"), ("watch", False), ("m15_background", False), ("demo", False),
                 ("account/equity", "100000"), ("account/currency", "CZK"), ("account/risk_pct", "2"),
                 ("account/reserve_pct", "0"), ("spec/EUR_USD/contract", "1"), ("spec/EUR_USD/min_qty", "1"),
                 ("spec/EUR_USD/step", "1"), ("spec/XAU_USD/contract", "1"), ("spec/XAU_USD/min_qty", "0.01"),
                 ("spec/XAU_USD/step", "0.01"), ("fx/USDCZK/rate", "21"),
                 ("fx/USDCZK/time", (Clock.t - timedelta(hours=1)).isoformat())):
        s.setValue(k, v)
    apikey.save(s, SELFTEST_KEY)
    s.sync()

    t212 = QLabel()
    t212.setWindowTitle("EUR/USD | Trading 212 (selftest)")
    t212.setPixmap(draw("EUR/USD"))
    t212.setFixedSize(1000, 640)
    t212.move(0, 0)
    t212.show()
    pump(app, 800)
    prov = Provider(Clock)
    w = ui.MainWindow()
    w.providers = lambda: prov
    w.m15.set_events([])
    w._cal.stop()
    dialogs = []
    w.bar.choose = lambda *a, **k: dialogs.append(k.get("note") or (a[1] if len(a) > 1 else "?")) or None
    w.move(620, 10)                         # the calculator overlaps Trading 212, as in real use
    w.show()
    pump(app, 800)
    lat = []

    def click(timeout=90.0):
        n = len(w.latencies)
        t0 = time.perf_counter()
        w.analyze()
        end = time.monotonic() + timeout
        stall = 0.0
        while len(w.latencies) == n and time.monotonic() < end:
            a = time.perf_counter()
            app.processEvents()
            stall = max(stall, time.perf_counter() - a)
            if not dialogs:
                time.sleep(0.005)
            else:
                break
        pump(app, 300)
        lat.append(time.perf_counter() - t0)
        return w.big.text(), [x.text() for x in (w.entry_lbl, w.tp_lbl, w.sl_lbl, w.pos_lbl)], stall

    def shot(name):
        p = out / f"{name}.png"
        w.grab().save(str(p))
        report["screens"].append(p.name)

    try:
        w.bar.warmup()
        w.bar.wait_idle()
        t212.grab().save(str(out / "t212_tabs_eurusd_active.png"))
        report["screens"].append("t212_tabs_eurusd_active.png")
        # A: AUTO, several tabs, EUR/USD active -> EUR/USD without any dialog
        state, vals, stall = click()
        a_ok = not dialogs and w.inst is not None and w.inst.symbol == "EUR/USD"
        res("A_auto_eurusd_among_tabs", a_ok, f"instrument={w.inst and w.inst.symbol}, dialogs={dialogs}, "
            f"via={w.bar.reading and w.bar.reading.recognition and w.bar.reading.recognition.via}, "
            f"ocr_ms={w.bar.last_ocr_ms}")
        # C: SELL with a confirmed plan and a position
        sig = w.m15_last.get("EUR/USD")
        out_r = w.risk_page.last
        levels = sig is not None and sig.levels_ok
        e, tp, sl = (sig.entry, sig.tp, sig.sl) if levels else (None, None, None)
        c_ok = (state == "SELL" and levels and sig.plan == m15.CONFIRMED and tp < e < sl and out_r is not None
                and out_r.qty is not None and "–" not in "".join(vals))
        shot("C_sell_plan")
        res("C_sell_with_plan", c_ok, f"{state} {vals} plan={sig and sig.plan}")
        # G: 2 % risk of 100 000 CZK
        g_ok = bool(out_r and out_r.qty is not None and out_r.loss_sl <= Decimal("2000"))
        res("G_risk_2_percent", g_ok, f"qty={out_r and out_r.qty}, loss_sl={out_r and out_r.loss_sl} CZK, "
            f"notional={out_r and out_r.notional} CZK, budget={out_r and out_r.budget}")
        # H: repeated clicks (cache, then a newer price), never frozen, button always clickable
        h = []
        for dt in (20, 61, 61):
            Clock.t = Clock.t + timedelta(seconds=dt)
            st, vv, stall = click()
            h.append((st, vv[0], round(stall * 1000)))
        h_ok = all(x[0] == "SELL" for x in h) and w.big.isEnabled() and max(x[2] for x in h) < 1500 and \
            set(prov.intervals) == {"15min"}
        res("H_repeated_clicks", h_ok, f"{h}; requests={prov.calls}, intervals={sorted(set(prov.intervals))}")
        # D: BUY with a confirmed plan
        prov.seed = SEEDS["confirmed_buy"]
        w.m15.feed.clear()
        st, vv, _ = click()
        sig = w.m15_last.get("EUR/USD")
        d_ok = st == "BUY" and sig.plan == m15.CONFIRMED and sig.sl < sig.entry < sig.tp and "–" not in "".join(vv)
        shot("D_buy_plan")
        res("D_buy_with_plan", d_ok, f"{st} {vv}")
        # E: conditional plan, clearly marked
        prov.seed = SEEDS["conditional_sell"]
        w.m15.feed.clear()
        st, vv, _ = click()
        sig = w.m15_last.get("EUR/USD")
        e_ok = sig.plan == m15.CONDITIONAL and "podmíněný" in vv[0] and not sig.confirmed and bool(sig.trigger)
        shot("E_conditional_plan")
        res("E_conditional_plan", e_ok, f"{st} {vv} trigger={sig.trigger}")
        # F: not enough M15 data
        prov.short = True
        w.m15.feed.clear()
        st, vv, _ = click()
        f_ok = st == "NO DATA" and all(v.endswith("–") for v in vv)
        res("F_insufficient_data", f_ok, f"{st} {vv}")
        prov.short, prov.seed = False, SEEDS["confirmed_sell"]
        # B: the user switches to Gold in "Trading 212"
        t212.setPixmap(draw("Gold"))
        t212.setWindowTitle("Gold | Trading 212 (selftest)")
        pump(app, 600)
        w.m15.feed.clear()
        st, vv, _ = click()
        sig = w.m15_last.get("XAU/USD")
        b_ok = (not dialogs and w.inst is not None and w.inst.symbol == "XAU/USD" and w.shown_m15 is not None
                and w.shown_m15.symbol == "XAU/USD"
                and (sig is None or not sig.levels_ok or float(sig.entry) > 1000))
        shot("B_switched_to_gold")
        res("B_switch_to_gold", b_ok, f"instrument={w.inst and w.inst.symbol} {st} {vv} dialogs={dialogs}")
        # J: everything above ran inside the packaged application
        res("J_packaged_exe", getattr(sys, "frozen", False), f"frozen={getattr(sys, 'frozen', False)}")
        report["latency_s"] = [round(x, 3) for x in lat]
        report["sizing_example"] = {"account": "100 000 CZK, risk 2 %", "fx": "1 USD = 21 CZK (test value)"}
        persist = {"equity": s.value("account/equity"), "risk": s.value("account/risk_pct"),
                   "key_encrypted": bool(s.value(apikey.ENCRYPTED, "")), "settings": s.fileName()}
        report["persist_written"] = persist
        _ = risk
    except Exception:  # noqa: BLE001 - the report must say what broke
        report["error"] = traceback.format_exc()
    finally:
        shot("final")
        t212.close()
        w.close()
        pump(app, 300)
    ok = "error" not in report and all(v["result"] == "PASS" for v in report["scenarios"].values())
    report["result"] = "PASS" if ok else "FAIL"
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1


def verify(out: Path) -> int:
    """Scenario I: a NEW process (as after closing the app / unpacking a new version) reads the settings."""
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication

    from . import apikey
    from .ui_risk import load_account
    QApplication.instance() or QApplication(sys.argv)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(out / "settings"))
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "CFDSignalCalculator", "app")
    acc = load_account(s)
    key = apikey.load(s)
    ok = acc.equity == Decimal("100000") and acc.currency == "CZK" and acc.risk_pct == Decimal("2") and \
        key == SELFTEST_KEY and not s.value(apikey.PLAIN, "")
    rep = {"result": "PASS" if ok else "FAIL", "equity": str(acc.equity), "currency": acc.currency,
           "risk_pct": str(acc.risk_pct), "key_restored": key == SELFTEST_KEY,
           "key_stored_encrypted": bool(s.value(apikey.ENCRYPTED, "")), "plain_key_present": bool(s.value(
               apikey.PLAIN, "")), "settings": s.fileName()}
    (out / "persist.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if ok else 1

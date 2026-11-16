"""End-to-end on a real Windows desktop: real Win32 window search, real capture, real OCR, real Qt UI.

A stand-in window titled "... Trading 212 ..." shows an instrument name the way Trading 212 does. The region
is set once; afterwards the instrument is recognised again after moving/resizing the window and changing the
instrument, without marking the screen again. Runs only with CFD_E2E=1 on Windows (CI step without the
offscreen Qt platform); screenshots go to CFD_E2E_OUT for inspection.
"""
import os
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not (sys.platform == "win32" and os.environ.get("CFD_E2E") == "1"),
                                reason="needs a real Windows desktop (CFD_E2E=1)")

OUT = Path(os.environ.get("CFD_E2E_OUT", "e2e-out"))


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication
    OUT.mkdir(parents=True, exist_ok=True)
    return QApplication.instance() or QApplication([])


T0 = time.monotonic()


def mark(what):
    print(f"[{time.monotonic() - T0:7.1f} s] {what}", flush=True)


def pump(app, ms=600):
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


class FakeT212:
    """A window that looks like the Trading 212 instrument header (dark, instrument name top-left)."""

    def __init__(self, app, text, title="NVDA | Trading 212 (e2e)", pos=(120, 120), size=(820, 480)):
        from PySide6.QtWidgets import QLabel, QWidget
        self.app = app
        self.w = QWidget()
        self.w.setWindowTitle(title)
        self.w.setStyleSheet("background: #1b1f27;")
        self.label = QLabel(text, self.w)
        self.label.setStyleSheet("color: #e6e6e6; font-size: 24px; font-weight: 600; font-family: 'Segoe UI';")
        self.label.move(30, 40)
        self.label.resize(320, 44)
        other = QLabel("Portfolio   History   Watchlist", self.w)
        other.setStyleSheet("color: #9aa3b2; font-size: 14px;")
        other.move(420, 48)
        other.resize(360, 30)
        self.w.move(*pos)
        self.w.resize(*size)
        self.w.show()
        self.w.raise_()
        pump(app, 900)

    def set(self, text):
        self.label.setText(text)
        pump(self.app, 500)

    def label_rect(self, pad=10):
        """The label area in physical screen pixels (what a user would drag around once)."""
        from PySide6.QtCore import QPoint
        g = self.label.mapToGlobal(QPoint(0, 0))
        scr = self.label.screen()
        geo, dpr = scr.geometry(), scr.devicePixelRatio()
        x = geo.x() + (g.x() - geo.x()) * dpr
        y = geo.y() + (g.y() - geo.y()) * dpr
        return (round(x - pad), round(y - pad), round(self.label.width() * dpr + 2 * pad),
                round(self.label.height() * dpr + 2 * pad))

    def close(self):
        self.w.close()
        pump(self.app, 500)


def save(name, rgb):
    from PIL import Image
    Image.fromarray(rgb).save(OUT / f"{name}.png")


def test_real_window_capture_and_recognition(app):
    from cfdcalc import auto, window
    t212 = FakeT212(app, "NVIDIA")
    try:
        wins = window.list_t212()
        assert any("Trading 212 (e2e)" in w.title for w in wins), [w.title for w in wins]
        win = next(w for w in wins if "(e2e)" in w.title)
        print("window", win, "dpi", win.dpi)
        region = window.to_region(t212.label_rect(), win)
        assert region is not None

        r = auto.read(region)
        save("1_nvidia", window.capture(win, window.to_screen(region, win)))
        assert r.status == auto.OK and r.recognition.confident and r.recognition.best.symbol == "NVDA", r

        t212.w.move(420, 260)              # moved and resized: the same stored region still works
        t212.w.resize(1000, 560)
        pump(app, 700)
        r = auto.read(region)
        assert r.status == auto.OK and r.recognition.best.symbol == "NVDA", r

        t212.set("EUR/USD")                # instrument changed in "Trading 212"
        r = auto.read(region)
        win = window.refresh(win)
        save("2_eurusd", window.capture(win, window.to_screen(region, win)))
        assert r.status == auto.OK and r.recognition.best.symbol == "EUR/USD", r

        t212.set("Gold   Silver")          # two instruments in the region: ambiguous, never confirmed
        r = auto.read(region)
        assert r.status == auto.OK and not r.recognition.confident, r

        t212.set("Germany 40")
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget
        cover = QWidget(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        cover.setStyleSheet("background: #ff00ff;")
        x, y, w, h = window.to_screen(region, window.refresh(win))
        dpr = t212.label.screen().devicePixelRatio()
        cover.setGeometry(round(x / dpr) - 20, round(y / dpr) - 20, round(w / dpr) + 40, round(h / dpr) + 40)
        cover.show()
        pump(app, 700)
        r = auto.read(region)              # covered (like the always-on-top calculator): content or refusal
        print("covered window reading:", r.status, r.message, r.recognition and r.recognition.text)
        assert (r.status == auto.OK and r.recognition.best.symbol == "DAX") or r.status == auto.UNREADABLE, r
        cover.close()
        pump(app, 400)

        t212.w.showMinimized()
        pump(app, 900)
        calls = []
        r = auto.read(region, ocr=lambda rgb: calls.append(1) or [])
        assert r.status == auto.MINIMIZED and not calls, r
    finally:
        t212.close()
    r = auto.read(region)
    assert r.status in (auto.NO_WINDOW,) or all("(e2e)" not in w.title for w in window.list_t212()), r


def test_app_recognises_switches_and_marks_old_signal_historical(app, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings

    from cfdcalc import ui, window
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    monkeypatch.setattr(ui, "data_dir", lambda: tmp_path)
    s = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, "CFDSignalCalculator", "app")
    s.setValue("demo", True)
    s.setValue("mode", "auto")
    s.setValue("watch", False)
    s.sync()
    app.setStyleSheet(ui.STYLE)
    t212 = FakeT212(app, "Tesla", title="Tesla | Trading 212 (e2e)")
    w = ui.MainWindow()
    w.move(1000, 80)                       # the calculator stays on top next to / over Trading 212
    w.show()
    pump(app, 600)
    try:
        mark("app shown")
        assert w.bar.save_region(t212.label_rect())   # set the region ONCE
        w.bar.wait_idle()
        pump(app, 300)
        assert w.inst and w.inst.symbol == "TSLA", w.bar.status.text()
        mark("region set, TSLA recognised")

        w.start()                          # START: re-reads Trading 212, analyses only the confirmed one
        w.bar.wait_idle()
        pump(app, 300)
        mark("START read done")
        w.task.wait(20000)
        pump(app, 400)
        mark("analysis done")
        assert w.analysed.symbol == "TSLA" and w.gauge.pct == 100
        w.grab().save(str(OUT / "3_app_tesla.png"))

        t212.w.move(200, 300)              # move the browser window and switch the instrument
        t212.set("Apple")
        for _ in range(2):
            w.bar.tick()
            w.bar.wait_idle()
            pump(app, 200)
        mark("two AUTO readings done")
        assert w.inst.symbol == "AAPL", w.bar.status.text()
        assert w.verdict.text().startswith("HISTORICKÝ")
        w.grab().save(str(OUT / "4_app_switched_to_apple.png"))
        print("status:", w.bar.status.text())
    finally:
        w.close()
        t212.close()
    assert window.SUPPORTED

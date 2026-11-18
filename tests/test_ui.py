"""Headless UI smoke test (offscreen Qt) + OCR on a rendered image. Skipped when Qt/OCR are not installed."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path, monkeypatch):
    QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, QtCore.QSettings.Scope.UserScope, str(tmp_path))
    from cfdcalc import ui
    monkeypatch.setattr(ui, "data_dir", lambda: tmp_path)
    w = ui.MainWindow()
    w.s.setValue("demo", True)
    w.s.setValue("auto_recognize", False)
    w.set_instrument(ui.BY_SYMBOL["XAU/USD"])
    return w


def finish(app, w):
    w.task.wait(10000)
    for _ in range(50):
        app.processEvents()


def test_start_runs_real_steps_to_a_verdict(app, window, tmp_path):
    window.start()
    finish(app, window)
    # v2.6: the big answer is the MARKET DIRECTION; after the result the ring shows its strength (0-100)
    title = window.gauge.title
    assert title in ("BUY", "SELL", "NEUTRAL") and window.result.verdict.text() == title
    shown = window.last_results["XAU/USD"][0]
    assert window.gauge.target == int(shown["strength"].split()[1].split("/")[0])
    assert "VSTUP" in window.result.entry.text() and window.hist_latencies      # shortened when a WATCH pill shows
    stamp = window.result.stamp.text()
    head = window.result.instrument.text()
    assert "analýza" in stamp and "data do" in stamp and "DEMO" in stamp and "XAU/USD" in head and "Komodity" in head
    assert all(t.value.text() not in ("…", "") for t in window.tiles.values())
    assert not (tmp_path / "journal.csv").exists()  # synthetic demo signals never enter the journal


def test_missing_api_key_never_analyses(app, window, monkeypatch):
    monkeypatch.delenv("TWELVEDATA_API_KEY", raising=False)
    from cfdcalc import ui
    shown = []
    monkeypatch.setattr(ui.QMessageBox, "warning", lambda *a: shown.append(a[2]))
    window.s.setValue("demo", False)
    window.s.setValue("api_key", "")
    window.start()
    assert window.task is None and "API klíč" in shown[0]


def test_ocr_reads_rendered_instrument_name():
    # Real OCR, no mocks. Text is drawn with Pillow's bundled TrueType font (Pillow comes with RapidOCR):
    # the offscreen Qt platform on Windows has no fonts and would draw empty boxes.
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont

    from cfdcalc.recognize import match, ocr_lines
    img = Image.new("RGB", (360, 60), "#1b1f27")
    ImageDraw.Draw(img).text((10, 14), "Germany 40   19 850.2", fill="#e6e6e6", font=ImageFont.load_default(size=26))
    lines = ocr_lines(np.asarray(img))
    r = match(lines)
    assert r.confident and r.best.symbol == "DAX", (lines, r)

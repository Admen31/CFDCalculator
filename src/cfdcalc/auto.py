"""AUTO mode: one reading of the instrument currently shown in Trading 212.

Runs in a worker thread (never in the UI thread). Window access is injected (`backend`) so the logic is
testable without Windows. No OCR runs unless the window exists, is not minimised and the region is readable.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import window
from .recognize import Recognition, match, ocr_lines

OK, UNSUPPORTED, NO_WINDOW, MINIMIZED, NO_REGION, UNREADABLE = (
    "ok", "unsupported", "no_window", "minimized", "no_region", "unreadable")


@dataclass(frozen=True)
class Reading:
    status: str
    message: str = ""
    win: window.Win | None = None
    recognition: Recognition | None = None


def read(region: window.Region | None, backend=window, ocr=ocr_lines) -> Reading:
    if not backend.SUPPORTED:
        return Reading(UNSUPPORTED, "Automatické rozpoznání funguje jen ve Windows.")
    wins = backend.list_t212()
    if not wins:
        return Reading(NO_WINDOW, "Okno Trading 212 nenalezeno. Otevřete Trading 212 (v prohlížeči jako aktivní "
                                  "záložku).")
    win = backend.pick(wins, backend.foreground())
    if win.minimized:
        return Reading(MINIMIZED, "Okno Trading 212 je minimalizované.", win)
    if region is None:
        return Reading(NO_REGION, "Nastavte jednou oblast s názvem instrumentu (tlačítko ▭).", win)
    rect = window.to_screen(region, win)
    if rect is None:
        return Reading(UNREADABLE, "Okno Trading 212 je menší než při nastavení oblasti – zvětšete ho, "
                                   "nebo oblast nastavte znovu.", win)
    try:
        rgb = backend.capture(win, rect)
    except window.CaptureError as e:
        return Reading(UNREADABLE, f"Obsah okna nelze bezpečně přečíst: {e}.", win)
    if window.blank(rgb):
        return Reading(OK, "", win, match([]))  # nothing written in the region: no OCR needed
    if rgb.shape[0] < 60:  # small UI text reads better enlarged
        rgb = np.repeat(np.repeat(rgb, 2, axis=0), 2, axis=1)
    return Reading(OK, "", win, match(ocr(rgb)))

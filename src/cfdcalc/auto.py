"""AUTO mode: one reading of the instrument currently shown in Trading 212.

Runs in a worker thread (never in the UI thread). Window access is injected (`backend`) so the logic is
testable without Windows. No OCR runs unless the window exists and is not minimised.

v2.9: several instruments in the region (tabs) -> the visually active one (recognize.locate hierarchy).
v2.8: the user's region (▭) is read first. When there is no region, or the region does not show a recognisable
instrument (Trading 212 moved its layout after a resize, a price is in the region, ...), the WHOLE window is read
and the instrument written in the largest font is taken (recognize.locate) - never a guess between two names.
The whole-window reading is limited to one per LOCATE_EVERY seconds while watching; a one-shot reading (START, ⟳)
always may do it.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import window
import time

from .recognize import Recognition, locate, match, ocr_boxes, ocr_lines

OK, UNSUPPORTED, NO_WINDOW, MINIMIZED, NO_REGION, UNREADABLE = (
    "ok", "unsupported", "no_window", "minimized", "no_region", "unreadable")


@dataclass(frozen=True)
class Reading:
    status: str
    message: str = ""
    win: window.Win | None = None
    recognition: Recognition | None = None


LOCATE_EVERY = 10.0
_last_locate = [0.0]


def read(region: window.Region | None, backend=window, ocr=ocr_lines, boxes=ocr_boxes, force_locate: bool = True,
         clock=time.monotonic) -> Reading:
    if not backend.SUPPORTED:
        return Reading(UNSUPPORTED, "Automatické rozpoznání funguje jen ve Windows.")
    wins = backend.list_t212()
    if not wins:
        return Reading(NO_WINDOW, "Okno Trading 212 nenalezeno. Otevřete Trading 212 (v prohlížeči jako aktivní "
                                  "záložku).")
    win = backend.pick(wins, backend.foreground())
    if win.minimized:
        return Reading(MINIMIZED, "Okno Trading 212 je minimalizované.", win)
    first: Reading | None = None
    if region is not None:
        rect = window.to_screen(region, win)
        if rect is None:
            first = Reading(UNREADABLE, "Okno Trading 212 je menší než při nastavení oblasti – zvětšete ho, "
                                        "nebo oblast nastavte znovu.", win)
        else:
            try:
                rgb = backend.capture(win, rect)
            except window.CaptureError as e:
                first = Reading(UNREADABLE, f"Obsah okna nelze bezpečně přečíst: {e}.", win)
            else:
                if window.blank(rgb):
                    rec = match([])           # nothing written in the region: no OCR needed
                else:
                    if rgb.shape[0] < 60:     # small UI text reads better enlarged
                        rgb = np.repeat(np.repeat(rgb, 2, axis=0), 2, axis=1)
                    rec = match(ocr(rgb))
                    if not rec.confident and rec.competing:   # tabs in the region: which one is active?
                        geo = locate(boxes(rgb))
                        if geo.confident:
                            rec = Recognition(geo.best, geo.score, geo.candidates, geo.text, (), geo.top,
                                              f"oblast · {geo.via}")
                first = Reading(OK, "", win, rec)
                if rec.confident:
                    return first
    # fallback: the whole window, the instrument in the largest font
    now = clock()
    if not force_locate and now - _last_locate[0] < LOCATE_EVERY:
        return first or Reading(NO_REGION, "Instrument nerozpoznán – hledám název v celém okně Trading 212 "
                                           "(nebo nastavte oblast ▭).", win)
    _last_locate[0] = now
    try:
        rgb = backend.capture(win, (win.left, win.top, win.width, win.height))
    except window.CaptureError as e:
        return first or Reading(UNREADABLE, f"Obsah okna nelze bezpečně přečíst: {e}.", win)
    if window.blank(rgb):
        return first or Reading(OK, "", win, match([]))
    rec = locate(boxes(rgb))
    if rec.confident or first is None or first.status != OK:
        return Reading(OK, "", win, rec)
    return first

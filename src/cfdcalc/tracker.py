"""Which instrument is confirmed for analysis.

* Manual choice confirms immediately.
* AUTO readings confirm a change only after `stable` identical confident readings in a row (one-shot reads
  use stable=1), so a single OCR glitch never switches the instrument.
* A readable Trading 212 region that confidently shows nothing we know (or something ambiguous) drops the
  confirmation: the app then waits for the user instead of analysing the previous instrument.
* No information (window missing, minimised, unreadable, empty region) keeps the confirmation; the UI shows
  the window status, and START in AUTO mode always reads Trading 212 again first.
* When the user confirms an uncertain reading, the same OCR text keeps meaning that instrument.
"""
from __future__ import annotations

from .auto import OK, Reading
from .instruments import Instrument


class Tracker:
    def __init__(self, stable: int = 2):
        self.stable = stable
        self.confirmed: Instrument | None = None
        self.source = ""                 # "auto" | "manual"
        self._taught: dict[str, Instrument] = {}
        self._last: object = None
        self._count = 0

    def set_manual(self, inst: Instrument, ocr_text: str = "") -> bool:
        """User's choice. With ocr_text, that exact OCR reading is remembered as this instrument."""
        if ocr_text:
            self._taught[ocr_text] = inst
        self._last, self._count = None, 0
        changed = inst != self.confirmed
        self.confirmed, self.source = inst, "manual"
        return changed

    def interpret(self, reading: Reading) -> Instrument | None | str:
        """Instrument the reading points to, None for "something else/unknown", "skip" for no information."""
        rec = reading.recognition
        if reading.status != OK or rec is None or not rec.text.strip():
            return "skip"
        if rec.confident:
            return rec.best
        return self._taught.get(rec.text)

    def feed(self, reading: Reading, stable: int | None = None) -> bool:
        """Process an AUTO reading. Returns True when the confirmed instrument changed (also to None)."""
        target = self.interpret(reading)
        if target == "skip":
            self._last, self._count = None, 0
            return False
        if target is self._last or target == self._last:
            self._count += 1
        else:
            self._last, self._count = target, 1
        if self._count < (stable or self.stable) or target == self.confirmed:
            return False
        self.confirmed, self.source = target, "auto"
        return True

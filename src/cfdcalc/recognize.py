"""Instrument recognition: OCR text from a screen region -> best catalogue match with a confidence.

The screen capture lives in the UI (Qt handles multi-monitor and DPI scaling); this module gets an RGB array.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .instruments import CATALOG, Instrument

CONFIDENT = 0.85   # below this, or with a close runner-up, the user picks manually
MARGIN = 0.08

_ocr = None


def ocr_lines(rgb) -> list[str]:
    """Text lines in an RGB numpy array (RapidOCR, offline). Loaded lazily: first call takes ~1 s."""
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    result, _ = _ocr(rgb)
    return [line[1] for line in result or []]


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z0-9&]", "", s.upper())


def _score(alias: str, text: str) -> float:
    if not alias or not text:
        return 0.0
    if alias == text:
        return 1.0
    if len(alias) >= 3 and alias in text:
        return 0.88 + 0.1 * len(alias) / len(text)   # longer covered alias wins ("BRENTOIL" over "OIL")
    return 0.9 * SequenceMatcher(None, alias, text).ratio()


@dataclass(frozen=True)
class Recognition:
    best: Instrument | None
    score: float
    candidates: tuple[Instrument, ...]
    text: str

    @property
    def confident(self) -> bool:
        return self.best is not None and self.score >= CONFIDENT


def match(lines: list[str], catalog: tuple[Instrument, ...] = CATALOG) -> Recognition:
    texts = [_norm(x) for x in lines] + [_norm(" ".join(lines))]
    tokens = {_norm(w) for x in lines for w in x.split()}

    def score(alias: str) -> float:
        words = [_norm(w) for w in alias.split()]
        split = len(words) > 1 and all(w in tokens for w in words)  # OCR split "Germany 40" into separate boxes
        return max([0.95 * split] + [_score(_norm(alias), t) for t in texts])

    scored = sorted(((max(score(a) for a in (i.name, *i.aliases)), i) for i in catalog), key=lambda x: -x[0])
    (s1, i1), (s2, _) = scored[0], scored[1]
    candidates = tuple(i for s, i in scored[:6] if s > 0.4)
    best = i1 if s1 - s2 >= MARGIN or s1 == 1.0 and s2 < 1.0 else None
    return Recognition(best, s1 if best else 0.0, candidates, " | ".join(lines))

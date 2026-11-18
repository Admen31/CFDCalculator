"""v2.9: storage of the Twelve Data API key.

* Settings live in %APPDATA%\\CFDSignalCalculator\\app.ini (QSettings, user scope). The path does NOT depend on
  where the EXE is, so a new version unpacked to another folder finds the same settings (and the same key).
* On Windows the key is encrypted with DPAPI (CryptProtectData, current user): only the same Windows user on the
  same computer can decrypt it. A plain key of older versions ("api_key") is migrated on first load.
* Elsewhere (tests, Linux) DPAPI does not exist: the key is kept as before, marked as not encrypted.
* The environment variable TWELVEDATA_API_KEY has priority and is never written anywhere.
* The key is never logged: error texts of the data layer are redacted (data.TwelveData._redact).
"""
from __future__ import annotations

import base64
import ctypes
import os
import sys

ENV = "TWELVEDATA_API_KEY"
PLAIN, ENCRYPTED = "api_key", "api_key_dpapi"
_ENTROPY = b"CFDSignalCalculator/api-key/v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _call(fn, data: bytes) -> bytes:
    out, entropy = _Blob(), _blob(_ENTROPY)
    if not fn(ctypes.byref(_blob(data)), None, ctypes.byref(entropy), None, None, 0x1, ctypes.byref(out)):
        raise OSError("DPAPI selhalo")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def protect(text: str) -> str:
    return base64.b64encode(_call(ctypes.windll.crypt32.CryptProtectData, text.encode("utf-8"))).decode("ascii")


def unprotect(token: str) -> str:
    return _call(ctypes.windll.crypt32.CryptUnprotectData, base64.b64decode(token)).decode("utf-8")


def load(s) -> str:
    """The key: environment variable, else the encrypted value, else a plain key of an older version (migrated to
    the encrypted form when possible). '' when there is none."""
    env = os.environ.get(ENV, "").strip()
    if env:
        return env
    token = str(s.value(ENCRYPTED, "") or "")
    if token and available():
        try:
            return unprotect(token)
        except (OSError, ValueError):
            return ""
    plain = str(s.value(PLAIN, "") or "").strip()
    if plain and available():
        save(s, plain)                      # migrate the plain key of v2.8 and older
    return plain


def save(s, key: str):
    key = key.strip()
    if not key:
        s.remove(ENCRYPTED)
        s.remove(PLAIN)
    elif available():
        s.setValue(ENCRYPTED, protect(key))
        s.remove(PLAIN)
    else:
        s.setValue(PLAIN, key)
    s.sync()


def where(s) -> str:
    """Human description of where the key is."""
    if os.environ.get(ENV, "").strip():
        return f"z proměnné prostředí {ENV}"
    if s.value(ENCRYPTED, ""):
        return f"šifrovaně (Windows DPAPI, jen pro tohoto uživatele) v {s.fileName()}"
    if s.value(PLAIN, ""):
        return f"NEŠIFROVANĚ v {s.fileName()}"
    return f"nenalezen – {s.fileName()} klíč neobsahuje"


def masked(key: str) -> str:
    return "" if not key else (key[:2] + "…" + key[-2:] if len(key) > 6 else "…")

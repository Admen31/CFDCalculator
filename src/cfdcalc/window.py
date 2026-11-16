"""Trading 212 window tracking and region capture on Windows (ctypes only, no extra dependency).

* The window is found by its title ("Trading 212" - the desktop app, or the ACTIVE browser tab, whose title
  is the browser window title). Nothing is read from Trading 212 except pixels of the chosen region.
* The instrument region is stored relative to the window's top-left corner in 96-DPI units, so it follows
  the window when it moves, and stays right at 100/125/150 % scaling and on other monitors.
* Capture: PrintWindow renders the window into memory even when another window (e.g. this always-on-top
  calculator) covers it; only the region is kept. If that yields nothing, the region is copied from the
  screen ONLY when no other window covers it. Minimised or unreadable window -> CaptureError, no OCR.
All coordinates here are physical pixels (Qt makes the process per-monitor DPI aware).
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

import numpy as np

SUPPORTED = sys.platform == "win32"
TITLE = re.compile(r"trading\s*212", re.IGNORECASE)


class CaptureError(Exception):
    pass


@dataclass(frozen=True)
class Win:
    hwnd: int
    title: str
    left: int      # visible frame bounds, physical pixels
    top: int
    width: int
    height: int
    dpi: int = 96
    minimized: bool = False

    @property
    def scale(self) -> float:
        return self.dpi / 96


@dataclass(frozen=True)
class Region:
    """Instrument-name area relative to the window's top-left corner, in 96-DPI (100 %) units."""
    x: float
    y: float
    w: float
    h: float


def to_region(rect: tuple[int, int, int, int], win: Win) -> Region | None:
    """Screen rectangle (physical px) -> window-relative region. Clipped to the window; None if outside."""
    x, y, w, h = rect
    x0, y0 = max(x, win.left), max(y, win.top)
    x1, y1 = min(x + w, win.left + win.width), min(y + h, win.top + win.height)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    s = win.scale
    return Region((x0 - win.left) / s, (y0 - win.top) / s, (x1 - x0) / s, (y1 - y0) / s)


def to_screen(region: Region, win: Win) -> tuple[int, int, int, int] | None:
    """Window-relative region -> screen rectangle (physical px); None when the window is now too small."""
    s = win.scale
    x, y = win.left + round(region.x * s), win.top + round(region.y * s)
    w, h = round(region.w * s), round(region.h * s)
    if x + w > win.left + win.width or y + h > win.top + win.height:
        return None
    return x, y, w, h


def pick(wins: list[Win], foreground: int = 0) -> Win:
    """The foreground Trading 212 window if any, else the topmost one (EnumWindows returns z-order)."""
    return next((w for w in wins if w.hwnd == foreground), wins[0])


def blank(img: np.ndarray) -> bool:
    """A capture with (almost) one colour: black from a failed capture, or a region without any text."""
    return img.size == 0 or float(img[..., :3].std()) < 2.0


# ---------------------------------------------------------------- Win32 (only imported on Windows)

if SUPPORTED:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _dwm = ctypes.WinDLL("dwmapi")
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    for _f in ("IsWindowVisible", "IsIconic", "IsWindow"):
        getattr(_user32, _f).argtypes = [wintypes.HWND]
    _get_dpi = getattr(_user32, "GetDpiForWindow", None)  # Windows 10 1607+; older systems are treated as 100 %
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.WindowFromPoint.argtypes = [wintypes.POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                                 ctypes.c_void_p, wintypes.UINT]
    try:  # per-monitor v2 DPI awareness; Qt already sets it in the app, this covers bare scripts/tests
        _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass

    class _BIH(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]


def _frame(hwnd: int) -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    # DWMWA_EXTENDED_FRAME_BOUNDS = 9: the visible frame without the invisible resize borders
    if _dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        _user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def _info(hwnd: int, title: str) -> Win:
    left, top, width, height = _frame(hwnd)
    dpi = (_get_dpi(hwnd) if _get_dpi else 0) or 96
    return Win(hwnd, title, left, top, width, height, dpi, bool(_user32.IsIconic(hwnd)))


def list_t212() -> list[Win]:
    """Visible top-level windows whose title contains "Trading 212", topmost first."""
    found: list[Win] = []

    def cb(hwnd, _):
        if _user32.IsWindowVisible(hwnd):
            n = _user32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                _user32.GetWindowTextW(hwnd, buf, n + 1)
                if TITLE.search(buf.value):
                    found.append(_info(hwnd, buf.value))
        return True

    _user32.EnumWindows(_WNDENUMPROC(cb), 0)
    return found


def foreground() -> int:
    return _user32.GetForegroundWindow() or 0


def refresh(win: Win) -> Win | None:
    """Current position/state of a known window, None if it was closed."""
    return _info(win.hwnd, win.title) if _user32.IsWindow(win.hwnd) else None


def cursor_pos() -> tuple[int, int]:
    p = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def uncovered(win: Win, rect: tuple[int, int, int, int]) -> bool:
    """True when the window itself is visible at the corners and centre of the rectangle."""
    x, y, w, h = rect
    points = [(x + 2, y + 2), (x + w - 3, y + 2), (x + 2, y + h - 3), (x + w - 3, y + h - 3), (x + w // 2, y + h // 2)]
    return all(_user32.GetAncestor(_user32.WindowFromPoint(wintypes.POINT(px, py)), 2) == win.hwnd
               for px, py in points)  # GA_ROOT = 2


def _bits(dc, bmp, w: int, h: int) -> np.ndarray:
    bih = _BIH(ctypes.sizeof(_BIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)  # negative height = top-down rows
    buf = (ctypes.c_ubyte * (w * h * 4))()
    if not _gdi32.GetDIBits(dc, bmp, 0, h, buf, ctypes.byref(bih), 0):
        raise CaptureError("čtení snímku selhalo")
    return np.frombuffer(buf, np.uint8).reshape(h, w, 4)[..., 2::-1].copy()  # BGRA -> RGB


def _render(hwnd: int, src_dc, w: int, h: int, blit) -> np.ndarray:
    mem = _gdi32.CreateCompatibleDC(src_dc)
    bmp = _gdi32.CreateCompatibleBitmap(src_dc, w, h)
    old = _gdi32.SelectObject(mem, bmp)
    try:
        if not blit(mem):
            raise CaptureError("snímání okna selhalo")
        return _bits(mem, bmp, w, h)
    finally:
        _gdi32.SelectObject(mem, old)
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(mem)


def capture(win: Win, rect: tuple[int, int, int, int]) -> np.ndarray:
    """RGB pixels of `rect` (physical screen px) belonging to `win`. Raises CaptureError when unsafe."""
    if not _user32.IsWindow(win.hwnd):
        raise CaptureError("okno Trading 212 bylo zavřeno")
    if _user32.IsIconic(win.hwnd):
        raise CaptureError("okno Trading 212 je minimalizované")
    x, y, w, h = rect
    wr = wintypes.RECT()
    _user32.GetWindowRect(win.hwnd, ctypes.byref(wr))
    ww, wh = wr.right - wr.left, wr.bottom - wr.top
    screen = _user32.GetDC(0)
    try:
        # PW_RENDERFULLCONTENT = 2: also GPU-rendered content (browsers); window is rendered into memory only
        full = _render(win.hwnd, screen, ww, wh, lambda mem: _user32.PrintWindow(win.hwnd, mem, 2))
        img = full[y - wr.top:y - wr.top + h, x - wr.left:x - wr.left + w]
        if img.shape[:2] == (h, w) and not blank(img):
            return img
        if not uncovered(win, rect):
            raise CaptureError("obsah okna nelze získat a oblast je zakrytá jiným oknem")
        # SRCCOPY | CAPTUREBLT: copy just this rectangle from the screen
        return _render(win.hwnd, screen, w, h, lambda mem: _gdi32.BitBlt(mem, 0, 0, w, h, screen, x, y, 0x40CC0020))
    finally:
        _user32.ReleaseDC(0, screen)

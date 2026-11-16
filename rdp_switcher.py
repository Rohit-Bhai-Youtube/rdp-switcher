"""
rdp_switcher.py — iOS-style glossy PILL notch (flush to top-left) for RDP switching.

Windows only. Python 3.8+, stdlib only (tkinter + ctypes). No pip install needed.

  pythonw rdp_switcher.py          # run silently
  python  rdp_switcher.py --list   # print detected RDP windows and exit

Design / performance notes:
  * Canvas is drawn ONCE per state change (at destination size) and placed with
    place(), so the animation only resizes the window + Win32 region. Nothing is
    redrawn per frame -> no stutter / freeze.
  * True capsule via CreateRoundRectRgn(radius = height/2), flush at y=0.
  * Each pill button shows "RDP n" AND the full IP on a second line.
  * 3-stop gradient, specular hairlines, glow dot, per-button jewel tints,
    active-RDP underline, hover glow, circular refresh/close buttons.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import base64
import json
import math
import os
import re
import struct
import sys
import time
import tkinter as tk
import zlib
from collections import namedtuple
from tkinter import messagebox

# ------------------------------------------------------------------ config --
FULL_WIDTH_BAR = False          # True = old full-width square top bar
ISLAND_ANCHOR = "left"          # "left" | "center" | "right"
ISLAND_MARGIN_X = 20
ISLAND_MARGIN_Y = 0             # 0 = flush / chipka with the top edge
ISLAND_COLLAPSED_W = 152
ISLAND_COLLAPSED_H = 24
ISLAND_EXPANDED_H = 66
ISLAND_MIN_W = 540
ISLAND_MAX_W = 0                # 0 = auto / adapts to monitor width; or set positive int to cap
ISLAND_PAD_X = 12
ARROW_W = 28                    # width of pagination arrows when RDP count > visible slots

# "My PC" = go back to your OWN PC. Default: minimize ONLY the RDP windows,
# so your local windows stay visible (that's the "main PC window" coming back).
# Set MYPC_MODE="all" for classic Show Desktop (minimize EVERY window).
MYPC_ENABLED = True
MYPC_MODE = "rdp"               # "rdp" | "all"
MYPC_PILL_W = 84
MYPC_HOTKEY = True              # Ctrl+Alt+0
MYPC_LABEL = "My PC"
MYPC_SUB_RDP = "Back to PC"
MYPC_SUB_ALL = "Show desktop"
MYPC_ACTIVATE_LOCAL = True      # bring the top local window to the foreground
ACTION_LOG = True               # append clicks to rdp_switcher_actions.log

# "Close All" = instantly close ALL RDP windows, no Yes/No confirmation
CLOSEALL_ENABLED = True
CLOSEALL_PILL_W = 90
CLOSEALL_LABEL = "Close All"
CLOSEALL_SUB = "All RDP"
CLOSEALL_TINT = "#6B2B3A"       # warning rose so it isn't clicked by accident
CLOSEALL_FOLLOWUP_MS = 300      # grace before force-killing stragglers/dialogs
# "Exit" = cleanly terminate the entire tool immediately
EXIT_ENABLED = True
EXIT_PILL_W = 76
EXIT_LABEL = "Exit"
EXIT_SUB = "Close App"
EXIT_TINT = "#2E0F18"           # Sharp ruby obsidian glass
EXIT_BORDER = "#6B2032"
EXIT_DOT = "#FF3366"
CLOSEALL_DOT = "#FF6B81"        # Soft rose accent for Close All
ISLAND_ON_ALL_MONITORS = False
HOVER_PAD = 18
TOP_EDGE_HOT = True
TOP_HOT_ZONE = 22
HIDE_DELAY = 0                  # cursor hate hi band (koi grace nahi)
INSTANT_HIDE = False            # False = collapse bhi expand jaisi smooth animation
REFRESH_MS = 1200               # less frequent = less work on the UI thread
POLL_MS = 40                    # snappier hover/leave detection
# Color key gives genuinely TRANSPARENT corners (child HWNDs ignore
# SetWindowRgn). The square black edge was the DWM shadow of the layered
# window - now removed on the REAL top-level HWND (tool-window style +
# disabled NC rendering), not on the TkChild that winfo_id() returns.
TRANSPARENT_KEY = "#FF00FF"
ANIM_STEPS = 10
ANIM_MS = 16

GRIP_HEIGHT = 3                 # legacy full-width mode
BAR_HEIGHT = 36
HOT_ZONE = 14

# iOS-ish palette ------------------------------------------------------------
GRAD_TOP = (22, 28, 42)
GRAD_MID = (12, 16, 26)
GRAD_BOT = (6, 8, 14)
RIM_1 = "#2C3A52"
RIM_2 = "#1E2738"
RIM_BOT = "#0E1420"
RIM_SIDE = "#1E2738"            # subtle matching glass contour
RIM_W = 1                       # island outline thickness
BTN_CORNER_R = 12               # chip corner radius -> straight top/bottom edges
BTN_RIM_DARKEN = 0.50           # DARK border (mix toward near-black)
BTN_BORDER_PX = 3               # button border thickness
ACCENT = "#5EAEFF"
ACTIVE_UNDERLINE = "#00D2FF"    # vibrant glowing electric cyan
FG = "#FFFFFF"                  # crisp pure white
SUB = "#B0C4DE"                 # cool silver slate for IP subtitle
MUTED = "#6B7C9E"
SEP = "#222D42"

BTN_PALETTE = [
    "#1D3B66",  # Deep Sapphire
    "#124B4C",  # Emerald Teal
    "#3B265E",  # Royal Amethyst
    "#4E361E",  # Warm Bronze
    "#15425C",  # Ocean Cobalt
    "#45224A",  # Velvet Plum
    "#1D4B34",  # Forest Jade
    "#4E2135",  # Ruby Wine
]
FONT = ("Segoe UI", 9)
FONT_BOLD = ("Segoe UI", 9, "bold")
FONT_TINY = ("Segoe UI", 7)
FONT_IP = ("Segoe UI", 8, "bold")

RDP_PROCESSES = {"mstsc.exe", "msrdc.exe"}
RDP_CLASSES = {"TscShellContainerClass", "TscShellWindowClass"}
NON_RDP_PROCESSES = {
    "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
    "code.exe", "devenv.exe", "notepad.exe", "notepad++.exe", "explorer.exe",
    "cmd.exe", "powershell.exe", "windowsterminal.exe", "slack.exe", "discord.exe",
    "teams.exe", "word.exe", "excel.exe", "acrobat.exe", "acrord32.exe"
}
TITLE_KEYWORDS = ("remote desktop",)
MAXIMIZE_ON_SWITCH = True
ENABLE_HOTKEYS = True
SORT_MODE = "hwnd"              # "hwnd" | "title"


def app_dir():
    """Folder next to the EXE when frozen, else next to the .py source."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def load_config():
    """Optional rdp_switcher_config.json next to the EXE overrides defaults.

    Lets you tweak the tool on ANY pc without Python / rebuilding.
    """
    p = os.path.join(app_dir(), "rdp_switcher_config.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        g = globals()
        for k, v in data.items():
            if k.isupper() and k in g and not k.startswith("_"):
                if isinstance(g[k], set) and isinstance(v, (list, tuple)):
                    g[k] = set(str(x).lower() for x in v)
                elif k == "ISLAND_MAX_W" and isinstance(v, str) and v.lower() == "auto":
                    g[k] = 0
                else:
                    g[k] = v
    except Exception:
        pass


load_config()
# ----------------------------------------------------------------------------

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

HWND = wintypes.HWND
HWND_TOP = HWND(0)
HWND_TOPMOST = HWND(-1)
HWND_NOTOPMOST = HWND(-2)

SW_SHOW = 5
SW_RESTORE = 9
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
GW_OWNER = 4
GA_ROOT = 2                     # GetAncestor: real top-level HWND
VK_MENU = 0x12
VK_CONTROL = 0x11
KEYEVENTF_KEYUP = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, HWND, wintypes.LPARAM)
MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL, ctypes.c_void_p, ctypes.c_void_p,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

# ---- Win32 prototypes ------------------------------------------------------
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
user32.EnumWindows.restype = wintypes.BOOL
user32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                       MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
for name in ("IsWindow", "IsWindowVisible", "IsIconic",
             "BringWindowToTop", "SetForegroundWindow"):
    getattr(user32, name).argtypes = [HWND]
    getattr(user32, name).restype = wintypes.BOOL
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.GetForegroundWindow.restype = HWND
user32.GetWindow.argtypes = [HWND, wintypes.UINT]
user32.GetWindow.restype = HWND
user32.GetAncestor.argtypes = [HWND, wintypes.UINT]
user32.GetAncestor.restype = HWND
user32.GetWindowTextW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int
user32.GetClassNameW.argtypes = [HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SetWindowPos.restype = wintypes.BOOL
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD,
                                     wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE,
                               wintypes.DWORD, ctypes.c_size_t]
user32.PostMessageW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM,
                                wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.GetWindowLongW.argtypes = [HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_uint32
user32.SetWindowLongW.argtypes = [HWND, ctypes.c_int, ctypes.c_uint32]
user32.SetWindowLongW.restype = ctypes.c_uint32
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateRoundRectRgn.restype = ctypes.c_void_p
user32.SetWindowRgn.argtypes = [HWND, ctypes.c_void_p, wintypes.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int
try:
    user32.SwitchToThisWindow.argtypes = [HWND, wintypes.BOOL]
except AttributeError:
    pass

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateProcess.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

Rdp = namedtuple("Rdp", "hwnd title cls proc rect ip")
_PROC_CACHE = {}

# ---- helpers ---------------------------------------------------------------
def _text(hwnd, func, size=512):
    buf = ctypes.create_unicode_buffer(size)
    n = func(hwnd, buf, size)
    return buf.value if n > 0 else ""


def proc_name(pid):
    now = time.monotonic()
    hit = _PROC_CACHE.get(pid)
    if hit and now - hit[1] < 10.0:
        return hit[0]
    name = ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
        finally:
            kernel32.CloseHandle(h)
    _PROC_CACHE[pid] = (name, now)
    if len(_PROC_CACHE) > 300:
        stale = [p for p, (_, t) in _PROC_CACHE.items() if now - t > 30.0]
        for p in stale:
            _PROC_CACHE.pop(p, None)
    return name


def ip_of(title):
    m = re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", title)
    if m:
        return m.group(0)
    head = title.split(" - ")[0].strip()
    if head.lower() in ("remote desktop connection", "remote desktop"):
        return "Connecting..."
    return head[:15] if head else "RDP"


def list_rdp_windows():
    """All visible top-level RDP windows (INCLUDING minimized ones)."""
    out = []

    def cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        w, h = r.right - r.left, r.bottom - r.top
        # minimized windows report a tiny 160x28 icon rect -> skip size filter
        if not user32.IsIconic(hwnd) and (w < 200 or h < 150):
            return True
        cls = _text(hwnd, user32.GetClassNameW, 256)
        title = _text(hwnd, user32.GetWindowTextW, 512)
        low = title.lower()
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        pname = proc_name(pid.value)

        # Exclude non-RDP applications (browsers, IDEs, text editors)
        # to prevent false positives when browser tabs or docs have "remote desktop" in title
        if pname in NON_RDP_PROCESSES:
            return True

        is_rdp = (pname in RDP_PROCESSES or cls in RDP_CLASSES)
        if not is_rdp and any(k in low for k in TITLE_KEYWORDS) and cls not in SKIP_CLASSES:
            is_rdp = True

        if not is_rdp:
            return True

        out.append(Rdp(int(hwnd), title.strip() or "(untitled)", cls,
                       pname or "?", (r.left, r.top, r.right, r.bottom),
                       ip_of(title)))
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


# ---- Desktop / close-all helpers -------------------------------------------
# Shell / overlay windows that must NOT be minimized when showing the desktop.
SKIP_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "SystemTray_Main", "TrayNotifyWnd", "NotifyIconOverflowWindow",
    "Xaml_WindowedPopupClass", "Windows.UI.Core.CoreWindow",
    "TopLevelWindowForOverflowXamlIsland", "Microsoft.UI.Content.PopupWindow",
    "EdgeUiInputTopWndClass", "TkTopLevel",
}
WS_EX_TOOLWINDOW = 0x00000080
WM_CLOSE = 0x0010
PROCESS_TERMINATE = 0x0001


def log_action(text):
    if not ACTION_LOG:
        return
    try:
        p = os.path.join(app_dir(), "rdp_switcher_actions.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%H:%M:%S"), text))
    except Exception:
        pass


def minimize_rdp_windows():
    """Minimize ONLY RDP windows -> local PC windows stay visible."""
    n = 0
    for w in list_rdp_windows():
        hwnd = HWND(w.hwnd)
        if not user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_MINIMIZE)
            n += 1
    return n


def top_local_window(exclude_hwnds=()):
    """First (top-most in z-order) normal LOCAL app window, or 0."""
    skip = set(int(h) for h in exclude_hwnds)
    found = [0]

    def cb(hwnd, _lparam):
        if found[0]:
            return True
        h = int(hwnd)
        if h in skip or not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        cls = _text(hwnd, user32.GetClassNameW, 128)
        if (cls in SKIP_CLASSES or cls.startswith("Windhawk.") or
                cls == "TkTopLevel" or cls in RDP_CLASSES):
            return True
        if not _text(hwnd, user32.GetWindowTextW, 256):
            return True
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if (r.right - r.left) < 200 or (r.bottom - r.top) < 150:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if proc_name(pid.value) in RDP_PROCESSES:
            return True
        found[0] = h
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return found[0]


def minimize_all_windows(exclude_hwnds=()):
    """Show desktop: minimize every real app window, keep our island visible."""
    skip = set(int(h) for h in exclude_hwnds)
    count = [0]

    def cb(hwnd, _lparam):
        h = int(hwnd)
        if h in skip or not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True
        if user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        cls = _text(hwnd, user32.GetClassNameW, 128)
        if cls in SKIP_CLASSES or cls.startswith("Windhawk."):
            return True
        if not _text(hwnd, user32.GetWindowTextW, 256):
            return True
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        if (r.right - r.left) < 200 or (r.bottom - r.top) < 150:
            return True
        user32.ShowWindow(hwnd, SW_MINIMIZE)
        count[0] += 1
        return True

    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return count[0]


def post_close(hwnd):
    return user32.PostMessageW(HWND(int(hwnd)), WM_CLOSE, 0, 0)


def process_alive(pid):
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    kernel32.CloseHandle(h)
    return True


def terminate_pid(pid):
    """Force-close stragglers. Only ever kills mstsc.exe / msrdc.exe."""
    h = kernel32.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        name = ""
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            name = os.path.basename(buf.value).lower()
        if name not in RDP_PROCESSES:       # never touch an unrelated process
            return False
        return bool(kernel32.TerminateProcess(h, 1))
    finally:
        kernel32.CloseHandle(h)


def list_monitors():
    rects = []

    def cb(_hmon, _hdc, lprc, _lp):
        r = lprc.contents
        rects.append((r.left, r.top, r.right, r.bottom))
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    if not rects:
        rects = [(0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))]
    return rects


def cursor_pos():
    p = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def kill_dwm_shadow(hwnd):
    """Remove the SQUARE DWM shadow of the layered color-key window.

    A layered window draws a rectangular drop shadow around its bounds even
    though its corners are transparent -> black square corners. Tool-window
    style + disabled NC rendering removes it.
    """
    try:
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                              style | WS_EX_TOOLWINDOW)
    except Exception:
        pass
    try:
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [HWND, wintypes.DWORD,
                                              ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = ctypes.c_long
        policy = ctypes.c_int(1)      # DWMNCRP_DISABLED
        dwm.DwmSetWindowAttribute(hwnd, 2, ctypes.byref(policy), 4)
    except Exception:
        pass


def widget_handle(widget):
    """Tk's winfo_id() can return bytes on some builds - normalise to int."""
    v = widget.winfo_id()
    if isinstance(v, bytes):
        v = int.from_bytes(v[:8], byteorder="little", signed=False)
    return int(v)


def owned_hwnd(widget):
    return HWND(widget_handle(widget))


def top_hwnd(widget):
    """REAL top-level HWND.

    Tk's winfo_id() for a toplevel returns an inner TkChild HWND whose parent
    is the actual TkTopLevel window. SetWindowRgn / ex-styles must be applied
    to that top-level, otherwise nothing is clipped.
    """
    inner = owned_hwnd(widget)
    root = user32.GetAncestor(inner, GA_ROOT)
    return int(root or widget_handle(widget))


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hexcol(rgb):
    return "#%02X%02X%02X" % tuple(int(clamp(c, 0, 255)) for c in rgb)


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def lighten(hex_color, amount):
    h = hex_color.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return hexcol(mix(rgb, (255, 255, 255), amount))


def darken(hex_color, amount):
    h = hex_color.lstrip("#")
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return hexcol(mix(rgb, (3, 5, 10), amount))


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _png_chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def rgba_png(w, h, rgba):
    raw = b"".join(b"\x00" + rgba[y * w * 4:(y + 1) * w * 4]
                   for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" +
            _png_chunk(b"IHDR",
                       struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
            _png_chunk(b"IDAT", zlib.compress(raw, 9)) +
            _png_chunk(b"IEND", b""))


def sd_round_rect(px, py, cx, cy, hw, hh, r):
    """Signed distance to a rounded rectangle (negative = inside)."""
    qx = abs(px - cx) - (hw - r)
    qy = abs(py - cy) - (hh - r)
    return (min(max(qx, qy), 0.0) +
            math.hypot(max(qx, 0.0), max(qy, 0.0)) - r)


_SHAPE_CACHE = {}


def chip_shape(w, h, r, p):
    """Per-pixel AA coverage, computed ONCE per geometry (all tints share it)."""
    key = (int(w), int(h), int(r), int(p))
    hit = _SHAPE_CACHE.get(key)
    if hit is not None:
        return hit
    W, H = int(w) + 2 * p, int(h) + 2 * p
    cx, cy = W / 2.0, H / 2.0
    rows = []
    for y in range(H):
        for x in range(W):
            d_out = sd_round_rect(x + 0.5, y + 0.5, cx, cy,
                                  W / 2.0, H / 2.0, r + p)
            a_out = 0.5 - d_out
            if a_out <= 0.0:
                rows.append((0.0, 0.0))
                continue
            if a_out > 1.0:
                a_out = 1.0
            d_in = sd_round_rect(x + 0.5, y + 0.5, cx, cy,
                                 W / 2.0 - p, H / 2.0 - p, r)
            a_in = min(1.0, max(0.0, 0.5 - d_in))
            rows.append((a_out, a_in))
    _SHAPE_CACHE[key] = (W, H, rows)
    return _SHAPE_CACHE[key]


def activate(hwnd, maximize=True):
    """Restore (if minimized), optionally maximize, and bring to foreground."""
    hwnd = int(hwnd)
    if not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    user32.ShowWindow(hwnd, SW_MAXIMIZE if maximize else SW_SHOW)

    cur = kernel32.GetCurrentThreadId()
    fg = user32.GetForegroundWindow()
    if fg:
        other = user32.GetWindowThreadProcessId(fg, None)
        if other and other != cur:
            user32.AttachThreadInput(cur, other, True)
            try:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
                user32.SetWindowPos(hwnd, HWND_TOP, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
            finally:
                user32.AttachThreadInput(cur, other, False)

    user32.SetForegroundWindow(hwnd)
    if user32.GetForegroundWindow() != hwnd:
        user32.keybd_event(VK_MENU, 0, 0, 0)
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    if user32.GetForegroundWindow() != hwnd:
        switch = getattr(user32, "SwitchToThisWindow", None)
        if switch:
            switch(hwnd, True)
    if user32.GetForegroundWindow() != hwnd:
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)

    for _ in range(12):
        if user32.GetForegroundWindow() == hwnd:
            return True
        time.sleep(0.03)
    return user32.GetForegroundWindow() == hwnd


# ---- UI --------------------------------------------------------------------
class Bar:
    """Canvas-drawn capsule. Draw once per state; animate only geometry."""

    BTN_W, BTN_H, BTN_GAP = 90, 44, 11

    def __init__(self, app, rect, is_root=False):
        self.app = app
        self.rect = rect
        self.left, self.top, self.right, self.bottom = rect
        self.mon_w = self.right - self.left

        self.entries = []
        self.active_hwnd = 0
        self.scroll_offset = 0
        self.visible_slots = 0
        self._photos = {}           # AA chip images, per Bar/Tk interpreter
        self.canvas_w, self.canvas_h = 0, 0
        self.shown = False
        self.target = False
        self.anim_job = None
        self.expanded_w = ISLAND_MIN_W
        self.cur_w, self.cur_h = self._collapsed_size()
        self.cur_rect = (0, 0, 0, 0)

        self.win = app.root if is_root else tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT_KEY)
        self.win.configure(bg=TRANSPARENT_KEY)
        self.win.resizable(False, False)

        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT_KEY, bd=0,
                                highlightthickness=0)
        self.canvas.place(x=0, y=0)
        self.canvas.bind("<Button-3>", app.menu_event)
        self.win.bind("<Button-3>", app.menu_event)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        self.win.bind("<MouseWheel>", self.on_mousewheel)

        self.win.update_idletasks()          # only once: make winfo_id() valid
        self.hwnd_top = top_hwnd(self.win)   # the REAL TkTopLevel HWND
        self._place((self.cur_w, self.cur_h))
        self._make_noactivate()
        kill_dwm_shadow(HWND(self.hwnd_top))
        self.draw(self.cur_w, self.cur_h)
        self.prewarm_chips()        # generate AA images at startup, not on hover

    # -- geometry -----------------------------------------------------------
    def _collapsed_size(self):
        if FULL_WIDTH_BAR:
            return self.mon_w, GRIP_HEIGHT
        return ISLAND_COLLAPSED_W, ISLAND_COLLAPSED_H

    def _expanded_size(self):
        if FULL_WIDTH_BAR:
            return self.mon_w, BAR_HEIGHT
        return self.expanded_w, ISLAND_EXPANDED_H

    def _x_for(self, w):
        if FULL_WIDTH_BAR:
            return self.left
        if ISLAND_ANCHOR == "center":
            return self.left + (self.mon_w - w) // 2
        if ISLAND_ANCHOR == "right":
            return self.right - ISLAND_MARGIN_X - w
        return self.left + ISLAND_MARGIN_X

    def _y_for(self):
        return self.top if FULL_WIDTH_BAR else self.top + ISLAND_MARGIN_Y

    def _place(self, size):
        """Cheap: geometry + region only. NO update_idletasks, NO redraw."""
        w, h = size
        self.cur_w, self.cur_h = w, h
        x, y = self._x_for(w), self._y_for()
        self.cur_rect = (x, y, w, h)
        self.win.geometry("%dx%d%+d%+d" % (w, h, x, y))
        # In a frozen (PyInstaller) build Tk sometimes drops the +x offset.
        # Pin the REAL top-level HWND with Win32 so MARGIN_X/ANCHOR always hold.
        try:
            user32.SetWindowPos(HWND(self.hwnd_top), HWND_TOPMOST,
                                int(x), int(y), int(w), int(h),
                                SWP_NOACTIVATE | SWP_SHOWWINDOW)
        except Exception:
            pass
        self._shape(w, h)

    def _shape(self, w, h):
        """Corner transparency and mouse hit-testing are handled natively
        by DWM through TRANSPARENT_KEY, completely eliminating 1-bit staircase
        jagged region edges."""
        try:
            targets = [HWND(self.hwnd_top), owned_hwnd(self.win),
                       HWND(widget_handle(self.canvas))]
            for t in targets:
                user32.SetWindowRgn(t, None, True)
        except Exception:
            pass

    def _make_noactivate(self):
        try:
            h = HWND(self.hwnd_top)
            style = user32.GetWindowLongW(h, GWL_EXSTYLE)
            user32.SetWindowLongW(h, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        except Exception:
            pass

    def raise_bar(self):
        try:
            user32.SetWindowPos(HWND(self.hwnd_top), HWND_TOPMOST, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW |
                                SWP_NOACTIVATE)
        except Exception:
            pass

    # -- animated show / hide (symmetric) -----------------------------------
    def set_shown(self, want):
        if self.target == want:
            return
        self.target = want
        if self.anim_job:
            try:
                self.win.after_cancel(self.anim_job)
            except Exception:
                pass
            self.anim_job = None
        self._from = (self.cur_w, self.cur_h)
        self._to = self._expanded_size() if want else self._collapsed_size()

        if want:
            # expand: draw the full island once, then reveal it by growing
            self.shown = True
            self.draw(self._to[0], self._to[1])
        else:
            # collapse: keep the full island drawn while it shrinks (mirror
            # of expand), then swap to the tiny notch on the last frame.
            self.shown = True
            if INSTANT_HIDE:
                self.shown = False
                self.draw(self._to[0], self._to[1])
                self._place(self._to)
                self.raise_bar()
                return
        self._anim_step(0)

    def _anim_step(self, i):
        n = ANIM_STEPS
        t = (i + 1) / n
        e = 1 - (1 - t) ** 3                    # ease-out cubic, both ways
        w = int(self._from[0] + (self._to[0] - self._from[0]) * e)
        h = int(self._from[1] + (self._to[1] - self._from[1]) * e)
        self._place((w, h))
        # morph the capsule background to this frame (cheap, tagged 'bg')
        self._background(self.canvas_w, self.canvas_h, w, h)
        if i + 1 < n:
            self.anim_job = self.win.after(ANIM_MS,
                                          lambda: self._anim_step(i + 1))
        else:
            self.anim_job = None
            self._place(self._to)
            if not self.target:
                self.shown = False
                self.draw(self._to[0], self._to[1])   # final notch
            else:
                self._background(self.canvas_w, self.canvas_h,
                                 self._to[0], self._to[1])
            self.raise_bar()

    # -- scrolling for unlimited RDP support --------------------------------
    def on_mousewheel(self, ev):
        if not self.shown:
            return
        if ev.delta > 0:
            self.scroll_left()
        elif ev.delta < 0:
            self.scroll_right()

    def scroll_left(self, step=1):
        if self.scroll_offset > 0:
            self.scroll_offset = max(0, self.scroll_offset - step)
            self.draw(self.cur_w, self.cur_h)

    def scroll_right(self, step=1):
        max_offset = max(0, len(self.entries) - self.visible_slots)
        if self.scroll_offset < max_offset:
            self.scroll_offset = min(max_offset, self.scroll_offset + step)
            self.draw(self.cur_w, self.cur_h)

    def scroll_to_index(self, idx):
        if not self.entries or self.visible_slots <= 0:
            return
        max_offset = max(0, len(self.entries) - self.visible_slots)
        if idx < self.scroll_offset:
            self.scroll_offset = clamp(idx, 0, max_offset)
            self.draw(self.cur_w, self.cur_h)
        elif idx >= self.scroll_offset + self.visible_slots:
            self.scroll_offset = clamp(idx - self.visible_slots + 1, 0, max_offset)
            self.draw(self.cur_w, self.cur_h)

    # -- drawing (called once per state change) -----------------------------
    def prewarm_chips(self):
        combos = []
        if MYPC_ENABLED:
            combos.append((MYPC_PILL_W, "#245A46"))
        if CLOSEALL_ENABLED:
            combos.append((CLOSEALL_PILL_W, CLOSEALL_TINT))
        if EXIT_ENABLED:
            combos.append((EXIT_PILL_W, EXIT_TINT))
        combos.append((ARROW_W, "#1B2A4A"))
        for base in BTN_PALETTE:
            combos.append((self.BTN_W, base))
        for w, base in combos:
            border = darken(base, BTN_RIM_DARKEN)
            self.chip_photo(w, self.BTN_H, base, border, False)
            self.chip_photo(w, self.BTN_H, base, border, True)

    def chip_photo(self, w, h, fill, border, hover=False):
        """Anti-aliased rounded-rect chip via signed-distance-field + PNG alpha.

        One smooth image instead of 6 jagged Tk primitives -> crisp 'full HD'
        edges, dark uniform border, inner top gloss, hover variant.
        """
        key = (int(w), int(h), fill, border, bool(hover))
        if key in self._photos:
            return self._photos[key]
        p = BTN_BORDER_PX
        W, H, rows = chip_shape(w, h, BTN_CORNER_R, p)
        fr = hex_rgb(lighten(fill, 0.20) if hover else fill)
        br = hex_rgb(border)
        buf = bytearray()                       # pure RGBA; rgba_png adds
        idx = 0                                 # the per-row filter bytes
        for y in range(H):
            for x in range(W):
                a_out, a_in = rows[idx]
                idx += 1
                if a_out <= 0.0:
                    buf += b"\x00\x00\x00\x00"
                    continue
                col = tuple(br[i] + (fr[i] - br[i]) * a_in for i in range(3))
                buf += bytes((int(col[0]), int(col[1]), int(col[2]),
                              int(a_out * 255)))
        photo = tk.PhotoImage(
            master=self.win,
            data=base64.b64encode(rgba_png(W, H, bytes(buf))).decode())
        self._photos[key] = photo
        return photo

    def chip(self, x1, y1, x2, y2, fill, tags, border):
        """Place one AA chip image and wire its hover swap."""
        w, h = x2 - x1, y2 - y1
        base = self.chip_photo(w, h, fill, border, False)
        hov = self.chip_photo(w, h, fill, border, True)
        c = self.canvas
        c.create_image(int(x1 - BTN_BORDER_PX), int(y1 - BTN_BORDER_PX),
                       image=base, anchor="nw", tags=tags)
        c.tag_bind(tags[0], "<Enter>",
                   lambda _ev: c.itemconfig(tags[1], image=hov))
        c.tag_bind(tags[0], "<Leave>",
                   lambda _ev: c.itemconfig(tags[1], image=base))

    def _background(self, cw, ch, w, h):
        """Capsule background; tagged 'bg' so animation can morph it per frame."""
        c = self.canvas
        c.delete("bg")
        c.create_rectangle(0, 0, cw, ch, fill=TRANSPARENT_KEY, outline="",
                           tags=("bg",))
        r = h / 2.0
        for yy in range(int(h)):
            t = yy / float(max(1, h - 1))
            if t < 0.22:
                col = mix(GRAD_TOP, GRAD_MID, t / 0.22)
            else:
                col = mix(GRAD_MID, GRAD_BOT, (t - 0.22) / 0.78)
            d = min(yy, h - 1 - yy)
            inset = r - (max(0.0, r * r - (r - d) ** 2)) ** 0.5
            c.create_rectangle(inset, yy, w - inset, yy + 1,
                               fill=hexcol(col), outline="", tags=("bg",))
        # Subtle 1px specular highlight at top & soft shadow hairline at bottom
        c.create_line(r, 0, w - r, 0, fill=RIM_1, width=1, tags=("bg",))
        c.create_line(r, h - 1, w - r, h - 1, fill=RIM_BOT, width=1, tags=("bg",))
        c.tag_lower("bg")        # keep morphing background BEHIND the chips

    def _glow_dot(self, cx, cy):
        c = self.canvas
        c.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="#1B3A6B",
                      outline="")
        c.create_oval(cx - 4, cy - 4, cx + 4, cy + 4, fill=ACCENT,
                      outline="")

    def draw(self, w, h):
        c = self.canvas
        c.delete("all")
        # Keep the canvas as large as BOTH the current and the destination size.
        # On collapse the window is still big for a few frames; a small canvas
        # would leave a black flash. Region clipping hides the extra area.
        cw, ch = max(w, self.cur_w), max(h, self.cur_h)
        self.canvas_w, self.canvas_h = cw, ch
        c.place(x=0, y=0, width=cw, height=ch)
        self._background(cw, ch, w, h)
        n = len(self.entries)

        if not self.shown:
            self._glow_dot(20, h / 2)
            c.create_text(34, h / 2, anchor="w",
                          text=("%d RDP" % n) if n else "no RDP",
                          fill=FG, font=FONT_BOLD)
            c.create_text(w - 14, h / 2, anchor="e", text="\u203a",
                          fill=SUB, font=FONT_BOLD)
            return

        # --- expanded iOS island ---
        x = ISLAND_PAD_X
        self._glow_dot(x + 4, h / 2)
        x += 16
        if n > self.visible_slots and self.visible_slots > 0:
            c.create_text(x, h / 2 - 8, anchor="w", text="RDP %d" % n,
                          fill=ACCENT, font=FONT_BOLD)
            disp_end = min(n, self.scroll_offset + self.visible_slots)
            c.create_text(x, h / 2 + 8, anchor="w",
                          text="%d-%d" % (self.scroll_offset + 1, disp_end),
                          fill=SUB, font=FONT_TINY)
        else:
            c.create_text(x, h / 2, anchor="w", text="RDP %d" % n,
                          fill=ACCENT, font=FONT_BOLD)
        x += 48

        # right edge: Close All and Exit pills
        rx = w - ISLAND_PAD_X
        if EXIT_ENABLED:
            ex2 = rx
            ex1 = ex2 - EXIT_PILL_W
            next_rx = ex1 - self.BTN_GAP
        else:
            ex1 = ex2 = rx
            next_rx = rx

        if CLOSEALL_ENABLED:
            ca2 = next_rx
            ca1 = ca2 - CLOSEALL_PILL_W
            sep_x = ca1 - 10
            limit_x = ca1 - 18
        else:
            ca1 = ca2 = next_rx
            sep_x = next_rx - 10
            limit_x = next_rx - 18
        by1, by2 = (h - self.BTN_H) / 2.0, (h + self.BTN_H) / 2.0

        def action_pill(x1, width, base, badge, label, sub, hit, pill, cmd):
            x2 = x1 + width
            self.chip(x1, by1, x2, by2, base, (hit, pill),
                      darken(base, BTN_RIM_DARKEN))
            c.create_text((x1 + x2) / 2.0, h / 2 - 9,
                          text=label, fill=FG, font=FONT_BOLD, tags=(hit,))
            c.create_text((x1 + x2) / 2.0, h / 2 + 9,
                          text=sub, fill=SUB, font=FONT_IP, tags=(hit,))
            c.tag_bind(hit, "<Button-1>", lambda _ev, f=cmd: f())
            return x2 + self.BTN_GAP

        # --- "My PC" = SHOW DESKTOP (minimize all), first pill ---
        if MYPC_ENABLED:
            pc_sub = (MYPC_SUB_RDP if MYPC_MODE == "rdp" else MYPC_SUB_ALL)
            x = action_pill(x, MYPC_PILL_W, "#245A46", "#8FE0B8",
                            MYPC_LABEL, pc_sub, "hitPC", "pillPC",
                            self.app.show_desktop)
            # separator between My PC and the RDP list
            c.create_line(x + 1, 14, x + 1, h - 14, fill=SEP)
            x += 8

        # --- Middle RDP items (Unlimited RDP support with paging & wheel) ---
        rdp_avail_w = limit_x - x
        slot_w = self.BTN_W + self.BTN_GAP
        direct_slots = max(1, int((rdp_avail_w + self.BTN_GAP) // slot_w))

        if not n:
            self.visible_slots = 0
            self.scroll_offset = 0
            mid_x = (x + limit_x) / 2.0
            c.create_text(mid_x, h / 2, anchor="center",
                          text="No Active RDP Sessions",
                          fill="#7B8DA8", font=FONT_BOLD)
        elif n <= direct_slots:
            # All RDPs fit on screen directly without scroll arrows
            self.visible_slots = n
            self.scroll_offset = 0
            for i in range(1, n + 1):
                e = self.entries[i - 1]
                bx1 = x
                bx2 = bx1 + self.BTN_W
                base = BTN_PALETTE[(i - 1) % len(BTN_PALETTE)]
                hit, pill = "hit%d" % i, "pill%d" % i
                self.chip(bx1, by1, bx2, by2, base, (hit, pill),
                          darken(base, BTN_RIM_DARKEN))
                c.create_text((bx1 + bx2) / 2, h / 2 - 9,
                              text="RDP %d" % i, fill=FG,
                              font=FONT_BOLD, tags=(hit,))
                c.create_text((bx1 + bx2) / 2, h / 2 + 9,
                              text=e.ip, fill=SUB, font=FONT_IP, tags=(hit,))
                ul_state = "normal" if e.hwnd == self.active_hwnd else "hidden"
                c.create_line(bx1 + 14, by2 - 3, bx2 - 14, by2 - 3,
                              fill=ACTIVE_UNDERLINE, width=2,
                              state=ul_state, tags=("ul%d" % i,))
                c.tag_bind(hit, "<Button-1>",
                           lambda _ev, hwnd=e.hwnd: self.app.pick(hwnd))
                x = bx2 + self.BTN_GAP
        else:
            # Unlimited RDPs: Show Left & Right pagination arrows
            arrow_w = ARROW_W
            btn_space = rdp_avail_w - 2 * (arrow_w + self.BTN_GAP)
            self.visible_slots = max(1, int((btn_space + self.BTN_GAP) // slot_w))
            max_offset = max(0, n - self.visible_slots)
            self.scroll_offset = clamp(self.scroll_offset, 0, max_offset)

            # Left Arrow
            can_left = self.scroll_offset > 0
            lax1 = x
            lax2 = lax1 + arrow_w
            base_arr = "#1B2A4A"
            hit_l, pill_l = "hitArrL", "pillArrL"
            self.chip(lax1, by1, lax2, by2, base_arr, (hit_l, pill_l),
                      darken(base_arr, BTN_RIM_DARKEN))
            arr_fg_l = FG if can_left else "#4B5A7A"
            c.create_text((lax1 + lax2) / 2, h / 2, text="\u25c0",
                          fill=arr_fg_l, font=FONT_BOLD, tags=(hit_l,))
            if can_left:
                c.tag_bind(hit_l, "<Button-1>", lambda _ev: self.scroll_left())
            x = lax2 + self.BTN_GAP

            # Visible RDP Pills
            start_idx = self.scroll_offset
            end_idx = min(n, start_idx + self.visible_slots)
            for idx in range(start_idx, end_idx):
                i = idx + 1
                e = self.entries[idx]
                bx1 = x
                bx2 = bx1 + self.BTN_W
                base = BTN_PALETTE[(i - 1) % len(BTN_PALETTE)]
                hit, pill = "hit%d" % i, "pill%d" % i
                self.chip(bx1, by1, bx2, by2, base, (hit, pill),
                          darken(base, BTN_RIM_DARKEN))
                c.create_text((bx1 + bx2) / 2, h / 2 - 9,
                              text="RDP %d" % i, fill=FG,
                              font=FONT_BOLD, tags=(hit,))
                c.create_text((bx1 + bx2) / 2, h / 2 + 9,
                              text=e.ip, fill=SUB, font=FONT_IP, tags=(hit,))
                ul_state = "normal" if e.hwnd == self.active_hwnd else "hidden"
                c.create_line(bx1 + 14, by2 - 3, bx2 - 14, by2 - 3,
                              fill=ACTIVE_UNDERLINE, width=2,
                              state=ul_state, tags=("ul%d" % i,))
                c.tag_bind(hit, "<Button-1>",
                           lambda _ev, hwnd=e.hwnd: self.app.pick(hwnd))
                x = bx2 + self.BTN_GAP

            # Right Arrow
            can_right = self.scroll_offset < max_offset
            rax1 = limit_x - arrow_w
            rax2 = limit_x
            hit_r, pill_r = "hitArrR", "pillArrR"
            self.chip(rax1, by1, rax2, by2, base_arr, (hit_r, pill_r),
                      darken(base_arr, BTN_RIM_DARKEN))
            arr_fg_r = FG if can_right else "#4B5A7A"
            c.create_text((rax1 + rax2) / 2, h / 2, text="\u25b6",
                          fill=arr_fg_r, font=FONT_BOLD, tags=(hit_r,))
            if can_right:
                c.tag_bind(hit_r, "<Button-1>", lambda _ev: self.scroll_right())

        # --- "Close All" & "Exit" pills at far right ---
        if CLOSEALL_ENABLED:
            c.create_line(sep_x, 14, sep_x, h - 14, fill=SEP)
            action_pill(ca1, CLOSEALL_PILL_W, CLOSEALL_TINT, CLOSEALL_DOT,
                        CLOSEALL_LABEL, CLOSEALL_SUB, "hitCA", "pillCA",
                        self.app.close_all)
        if EXIT_ENABLED:
            action_pill(ex1, EXIT_PILL_W, EXIT_TINT, EXIT_DOT,
                        EXIT_LABEL, EXIT_SUB, "hitExit", "pillExit",
                        self.app.quit)

    # -- data ----------------------------------------------------------------
    def calc_width(self, n):
        if FULL_WIDTH_BAR:
            return self.mon_w
        raw = 2 * ISLAND_PAD_X + 16 + 48          # pad + glow dot + "RDP n"
        if MYPC_ENABLED:
            raw += MYPC_PILL_W + self.BTN_GAP + 8   # + separator gap
        raw += max(220, n * (self.BTN_W + self.BTN_GAP))    # RDP pills or clean empty state
        if CLOSEALL_ENABLED:
            raw += 18 + CLOSEALL_PILL_W           # separator gap + Close All pill
        if EXIT_ENABLED:
            raw += self.BTN_GAP + EXIT_PILL_W     # Exit pill next to Close All
        max_allowed = self.mon_w - 2 * ISLAND_MARGIN_X
        if ISLAND_MAX_W and ISLAND_MAX_W > 0:
            max_allowed = min(ISLAND_MAX_W, max_allowed)
        return int(clamp(raw, ISLAND_MIN_W, max_allowed))

    def rebuild(self, entries, active_hwnd=0):
        self.entries = entries
        self.active_hwnd = active_hwnd
        self.expanded_w = self.calc_width(len(entries))
        if self.visible_slots > 0 and len(entries) > 0:
            max_offset = max(0, len(entries) - self.visible_slots)
            self.scroll_offset = clamp(self.scroll_offset, 0, max_offset)
        else:
            self.scroll_offset = 0
        dest = self._expanded_size() if self.shown else self._collapsed_size()
        if self.shown and not self.anim_job:
            self._place(dest)               # keep window in sync if width changed
        self.draw(dest[0], dest[1])

    def set_active(self, hwnd):
        """Toggle underline items only - no canvas rebuild -> no stutter."""
        if hwnd == self.active_hwnd:
            return
        self.active_hwnd = hwnd
        act_idx = -1
        for idx, e in enumerate(self.entries):
            if e.hwnd == hwnd:
                act_idx = idx
                break
        if act_idx != -1 and len(self.entries) > self.visible_slots and self.visible_slots > 0:
            if act_idx < self.scroll_offset or act_idx >= self.scroll_offset + self.visible_slots:
                self.scroll_to_index(act_idx)
                return
        for i, e in enumerate(self.entries, 1):
            try:
                self.canvas.itemconfig(
                    "ul%d" % i,
                    state="normal" if e.hwnd == hwnd else "hidden")
            except Exception:
                pass


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.geometry("1x1+0+0")
        self.root.attributes("-topmost", True)
        self.root.configure(bg=TRANSPARENT_KEY)

        self.monitors = list_monitors()
        targets = self.monitors if ISLAND_ON_ALL_MONITORS else self.monitors[:1]
        self.bars = [Bar(self, targets[0], is_root=True)]
        for r in targets[1:]:
            self.bars.append(Bar(self, r))

        self.order = []
        self.signature = None
        self.entries = []
        self.held_digits = set()
        self.held_zero = False
        self.held_next = False
        self.held_prev = False
        self.close_pids = set()
        self.close_tries = 0
        self.last_hot = 0.0
        self.last_refresh = 0.0
        self.last_raise = 0.0

        self.refresh()
        self.root.after(POLL_MS, self.tick)

    def refresh(self):
        self.last_refresh = time.monotonic()

        # Display Resolution & Monitor Plug-n-Play Detection
        cur_monitors = list_monitors()
        if cur_monitors != self.monitors:
            log_action("Resolution/Monitors changed: %s -> %s" % (self.monitors, cur_monitors))
            self.monitors = cur_monitors
            targets = self.monitors if ISLAND_ON_ALL_MONITORS else self.monitors[:1]
            for idx, target in enumerate(targets):
                if idx < len(self.bars):
                    b = self.bars[idx]
                    b.rect = target
                    b.left, b.top, b.right, b.bottom = target
                    b.mon_w = target[2] - target[0]
                    b.expanded_w = b.calc_width(len(self.entries))
                    dest = b._expanded_size() if b.shown else b._collapsed_size()
                    b._place(dest)
                    b.draw(dest[0], dest[1])

        found = {w.hwnd: w for w in list_rdp_windows()}
        self.order = [h for h in self.order if h in found]
        known = set(self.order)
        fresh = [h for h in found if h not in known]
        if SORT_MODE == "title":
            fresh.sort(key=lambda h: (found[h].title.lower(), h))
        else:
            fresh.sort()
        for h in fresh:
            self.order.append(h)
            known.add(h)
        active = int(user32.GetForegroundWindow() or 0)
        sig = tuple((h, found[h].title, found[h].ip) for h in self.order)
        if sig != self.signature:
            self.signature = sig
            self.entries = [found[h] for h in self.order]
            for b in self.bars:
                b.rebuild(self.entries, active)
        for b in self.bars:
            b.set_active(active)

    def force_refresh(self):
        self.last_refresh = 0.0
        self.refresh()

    def pick(self, hwnd):
        log_action("RDP click hwnd=%s" % hwnd)
        activate(hwnd)
        self.root.after(200, self.raise_bars)

    def cycle_rdp(self, direction):
        if not self.entries:
            return
        active_hwnd = int(user32.GetForegroundWindow() or 0)
        cur_idx = -1
        for idx, e in enumerate(self.entries):
            if e.hwnd == active_hwnd:
                cur_idx = idx
                break
        if cur_idx == -1:
            next_idx = 0 if direction > 0 else len(self.entries) - 1
        else:
            next_idx = (cur_idx + direction) % len(self.entries)
        target = self.entries[next_idx]
        log_action("Cycle RDP %d -> %d hwnd=%s" % (cur_idx + 1, next_idx + 1, target.hwnd))
        self.pick(target.hwnd)

    def show_desktop(self):
        """My PC: default minimizes ONLY RDPs so local PC windows reappear."""
        log_action("My PC click (mode=%s)" % MYPC_MODE)
        own = [b.hwnd_top for b in self.bars]
        if MYPC_MODE == "all":
            minimize_all_windows(own)
        else:
            minimize_rdp_windows()
            if MYPC_ACTIVATE_LOCAL:
                local = top_local_window(own)
                if local:
                    log_action("activating local hwnd=%s" % local)
                    activate(local, maximize=False)
        self.root.after(200, self.raise_bars)

    def close_all(self):
        """Close ALL RDP windows instantly, with NO Yes/No confirmation."""
        log_action("Close All click (%d RDP)" % len(self.entries))
        pids = set()
        for e in list_rdp_windows():
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(HWND(e.hwnd), ctypes.byref(pid))
            if pid.value:
                pids.add(pid.value)
            post_close(e.hwnd)               # graceful close first (instant)
        self.close_pids = pids
        self.close_tries = 0
        if pids:
            # stragglers / "disconnect?" dialogs are force-killed, never shown
            self.root.after(CLOSEALL_FOLLOWUP_MS, self._close_followup)
        self.root.after(200, self.raise_bars)
        self.root.after(400, self.force_refresh)

    def _close_followup(self):
        self.close_tries += 1
        alive = [p for p in self.close_pids if process_alive(p)]
        for p in alive:
            terminate_pid(p)                # kills any confirmation dialog too
        if alive and self.close_tries < 3:
            self.root.after(CLOSEALL_FOLLOWUP_MS, self._close_followup)
        else:
            self.close_pids = set()
            self.force_refresh()

    def raise_bars(self):
        for b in self.bars:
            b.raise_bar()

    def set_shown(self, want):
        changed = False
        for b in self.bars:
            if b.target != want:
                changed = True
                b.set_shown(want)
        if changed or want:
            # Fullscreen RDP Topmost Lock: keep island on top of fullscreen sessions
            self.raise_bars()

    def menu_event(self, ev):
        m = tk.Menu(self.root, tearoff=0, bg="#121826", fg=FG,
                    activebackground="#33507F", bd=0)
        m.add_command(label="Refresh list", command=self.force_refresh)
        m.add_command(label="Show detected windows", command=self.dump)
        if self.entries:
            m.add_separator()
            rdp_m = tk.Menu(m, tearoff=0, bg="#121826", fg=FG,
                            activebackground="#33507F", bd=0)
            if len(self.entries) <= 15:
                for i, e in enumerate(self.entries, 1):
                    lbl = "RDP %d  (%s)" % (i, e.ip)
                    rdp_m.add_command(label=lbl,
                                      command=lambda h=e.hwnd: self.pick(h))
            else:
                chunk_sz = 10
                for s_idx in range(0, len(self.entries), chunk_sz):
                    e_idx = min(s_idx + chunk_sz, len(self.entries))
                    sub_lbl = "RDP %d - %d" % (s_idx + 1, e_idx)
                    sub_m = tk.Menu(rdp_m, tearoff=0, bg="#121826", fg=FG,
                                    activebackground="#33507F", bd=0)
                    for i in range(s_idx, e_idx):
                        e = self.entries[i]
                        lbl = "RDP %d  (%s)" % (i + 1, e.ip)
                        sub_m.add_command(label=lbl,
                                          command=lambda h=e.hwnd: self.pick(h))
                    rdp_m.add_cascade(label=sub_lbl, menu=sub_m)
            m.add_cascade(label="Switch to RDP", menu=rdp_m)
        m.add_separator()
        m.add_command(label="Exit", command=self.quit)
        try:
            m.tk_popup(ev.x_root, ev.y_root)
        finally:
            m.grab_release()

    def dump(self):
        lines = []
        if MYPC_ENABLED:
            lines.append("My PC      Show desktop (minimize all windows)")
        if CLOSEALL_ENABLED:
            lines.append("Close All  %d RDP window(s) - instant, no confirmation"
                         % len(self.entries))
        lines.append("")
        if not self.entries:
            lines.append("Koi RDP window nahi mili.")
        else:
            for i, e in enumerate(self.entries, 1):
                lines.append("RDP %d  %s  hwnd=%s  [%s]  %s" %
                             (i, e.ip, e.hwnd, e.proc, e.title[:45]))
        if len(self.entries) > 15:
            self._show_scrollable_dump("\n".join(lines), len(self.entries))
        else:
            messagebox.showinfo("RDP Switcher", "\n".join(lines))

    def _show_scrollable_dump(self, text, count):
        top = tk.Toplevel(self.root)
        top.title("Detected RDP Windows (%d)" % count)
        top.geometry("640x460")
        top.configure(bg="#121826")
        top.attributes("-topmost", True)

        txt_frame = tk.Frame(top, bg="#121826")
        txt_frame.pack(fill="both", expand=True, padx=12, pady=12)

        txt = tk.Text(txt_frame, bg="#0E131F", fg=FG, font=("Consolas", 9),
                      bd=0, padx=8, pady=8, highlightthickness=0)
        sb = tk.Scrollbar(txt_frame, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        txt.pack(side="left", fill="both", expand=True)

        txt.insert("1.0", text)
        txt.configure(state="disabled")

        btn_frame = tk.Frame(top, bg="#121826")
        btn_frame.pack(side="bottom", fill="x", padx=12, pady=(0, 10))
        close_btn = tk.Button(btn_frame, text="Close", command=top.destroy,
                              bg="#24406B", fg=FG, bd=0, padx=16, pady=4)
        close_btn.pack(side="right")

    def poll_hotkeys(self):
        if not ENABLE_HOTKEYS:
            return
        ctrl = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        alt = bool(user32.GetAsyncKeyState(VK_MENU) & 0x8000)
        if not (ctrl and alt):
            self.held_digits.clear()
            self.held_zero = False
            self.held_next = False
            self.held_prev = False
            return
        if MYPC_ENABLED and MYPC_HOTKEY:
            zero = bool(user32.GetAsyncKeyState(0x30) & 0x8000)
            if zero and not self.held_zero:
                self.show_desktop()
            self.held_zero = zero

        for i in range(1, 10):
            down = bool(user32.GetAsyncKeyState(0x30 + i) & 0x8000)
            if down:
                if i not in self.held_digits and i <= len(self.entries):
                    self.pick(self.entries[i - 1].hwnd)
                self.held_digits.add(i)
            else:
                self.held_digits.discard(i)

        if self.entries:
            down_next = bool((user32.GetAsyncKeyState(0x27) & 0x8000) or
                             (user32.GetAsyncKeyState(0x28) & 0x8000) or
                             (user32.GetAsyncKeyState(0x22) & 0x8000))
            if down_next:
                if not self.held_next:
                    self.cycle_rdp(1)
                self.held_next = True
            else:
                self.held_next = False

            down_prev = bool((user32.GetAsyncKeyState(0x25) & 0x8000) or
                             (user32.GetAsyncKeyState(0x26) & 0x8000) or
                             (user32.GetAsyncKeyState(0x21) & 0x8000))
            if down_prev:
                if not self.held_prev:
                    self.cycle_rdp(-1)
                self.held_prev = True
            else:
                self.held_prev = False

    def tick(self):
        try:
            self.poll_hotkeys()
            now = time.monotonic()
            x, y = cursor_pos()

            hot = False
            for b in self.bars:
                if FULL_WIDTH_BAR:
                    l, t, r, _ = b.rect
                    limit = t + (BAR_HEIGHT if b.shown else HOT_ZONE)
                    if l <= x < r and t - 10 <= y <= limit:
                        hot = True
                else:
                    ix, iy, iw, ih = b.cur_rect
                    if (ix - HOVER_PAD <= x <= ix + iw + HOVER_PAD and
                            iy - HOVER_PAD <= y <= iy + ih + HOVER_PAD):
                        hot = True
                    if TOP_EDGE_HOT and (b.left <= x <= ix + iw + 40) and \
                            (b.top <= y <= b.top + TOP_HOT_ZONE):
                        hot = True
                if hot:
                    break

            if hot:
                self.last_hot = now
                self.set_shown(True)
                # Fullscreen RDP Topmost Lock: keeps the notch firmly above full-screen mstsc
                if now - self.last_raise >= 0.35:
                    self.last_raise = now
                    self.raise_bars()
            elif any(b.shown for b in self.bars) and now - self.last_hot > HIDE_DELAY:
                self.set_shown(False)

            animating = any(b.anim_job for b in self.bars)
            if not animating and now - self.last_refresh >= REFRESH_MS / 1000.0:
                self.refresh()
            if not animating and now - self.last_raise >= 2.0:
                self.last_raise = now
                self.raise_bars()
        except Exception as e:
            log_action(f"tick error: {e}")

        self.root.after(POLL_MS, self.tick)

    def quit(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


def check_single_instance(name="Global\\RDP_Switcher_Exclusive_Mutex"):
    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183
    mutex = kernel32.CreateMutexW(None, False, name)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def main():
    if "--list" in sys.argv:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        wins = sorted(list_rdp_windows(), key=lambda w: w.hwnd)
        if not wins:
            print("No RDP windows found.")
        for i, w in enumerate(wins, 1):
            print("RDP %d  %s  hwnd=%s  proc=%s  class=%s  title=%r"
                  % (i, w.ip, w.hwnd, w.proc, w.cls, w.title))
        return
    mutex = check_single_instance()
    if not mutex:
        sys.exit(0)
    try:
        App().run()
    except Exception as e:
        log_action(f"App fatal error: {e}")


if __name__ == "__main__":
    main()

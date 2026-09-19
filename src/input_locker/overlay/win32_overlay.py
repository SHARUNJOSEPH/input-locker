"""Pure Win32 semi-transparent non-activating glass overlay.

Zero-dependency implementation interacting directly with Windows Desktop Window
Manager (DWM). Spans all physical displays across the virtual desktop and guarantees
zero focus disruption (0 WM_ACTIVATE / WM_KILLFOCUS messages).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import threading
import time
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# Extended Window Styles
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

# Combined non-activating overlay extended style mask (0x080800A8)
OVERLAY_EX_STYLE = (
    WS_EX_NOACTIVATE
    | WS_EX_TRANSPARENT
    | WS_EX_LAYERED
    | WS_EX_TOOLWINDOW
    | WS_EX_TOPMOST
)

# Standard Window Styles
WS_POPUP = 0x80000000
WS_CLIPSIBLINGS = 0x04000000

# SetWindowPos flags
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOREDRAW = 0x0008
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080

# Layered Window Attributes
LWA_COLORKEY = 0x00000001
LWA_ALPHA = 0x00000002

# System Metrics
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# Window Messages
WM_DESTROY = 0x0002
WM_PAINT = 0x000F
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_ERASEBKGND = 0x0014
WM_NCHITTEST = 0x0084
HTTRANSPARENT = -1

LRESULT = ctypes.c_int64
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
UINT = wintypes.UINT
HWND = wintypes.HWND
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_gdi32 = ctypes.windll.gdi32

# Configure ctypes prototypes with 64-bit safety
_kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
_kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

_kernel32.GetCurrentThreadId.restype = wintypes.DWORD
_kernel32.GetCurrentThreadId.argtypes = []

_gdi32.GetStockObject.restype = wintypes.HGDIOBJ
_gdi32.GetStockObject.argtypes = [ctypes.c_int]

_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

_user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
_user32.DefWindowProcW.restype = LRESULT

_user32.CreateWindowExW.restype = HWND
_user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]

_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    HWND, HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT
]

_user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
_user32.SetLayeredWindowAttributes.argtypes = [
    HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD
]

_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [HWND]

_user32.DestroyWindow.restype = wintypes.BOOL
_user32.DestroyWindow.argtypes = [HWND]

_user32.GetDC.restype = wintypes.HDC
_user32.GetDC.argtypes = [HWND]

_user32.ReleaseDC.restype = ctypes.c_int
_user32.ReleaseDC.argtypes = [HWND, wintypes.HDC]

_user32.BeginPaint.restype = wintypes.HDC
_user32.BeginPaint.argtypes = [HWND, ctypes.c_void_p]

_user32.EndPaint.restype = wintypes.BOOL
_user32.EndPaint.argtypes = [HWND, ctypes.c_void_p]

_user32.FillRect.restype = ctypes.c_int
_user32.FillRect.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH]

_user32.InvalidateRect.restype = wintypes.BOOL
_user32.InvalidateRect.argtypes = [HWND, ctypes.c_void_p, wintypes.BOOL]


class RECT(ctypes.Structure):
    """Win32 RECT structure."""
    _fields_ = [
        ("left",   ctypes.c_long),
        ("top",    ctypes.c_long),
        ("right",  ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


# PAINTSTRUCT is 64 bytes on 64-bit Windows
class PAINTSTRUCT(ctypes.Structure):
    """Win32 PAINTSTRUCT structure for BeginPaint/EndPaint."""
    _fields_ = [
        ("hdc",         wintypes.HDC),
        ("fErase",      wintypes.BOOL),
        ("rcPaint",     RECT),
        ("fRestore",    wintypes.BOOL),
        ("fIncUpdate",  wintypes.BOOL),
        ("rgbReserved", ctypes.c_byte * 32),
    ]

_user32.PostMessageW.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]

_user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]


def _global_overlay_wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    """Persistent module-level window procedure that is never garbage-collected."""
    if msg == WM_NCHITTEST:
        # Hit-test transparency: pass all mouse clicks to underlying windows
        return HTTRANSPARENT
    elif msg == WM_PAINT:
        # BeginPaint/EndPaint required to clear the dirty region; fill with BLACK_BRUSH
        ps = PAINTSTRUCT()
        hdc = _user32.BeginPaint(hwnd, ctypes.byref(ps))
        if hdc:
            _user32.FillRect(hdc, ctypes.byref(ps.rcPaint), _gdi32.GetStockObject(4))  # BLACK_BRUSH
            _user32.EndPaint(hwnd, ctypes.byref(ps))
        return 0
    elif msg == WM_CLOSE:
        _user32.DestroyWindow(hwnd)
        return 0
    elif msg == WM_DESTROY:
        _user32.PostQuitMessage(0)
        return 0
    # WM_ERASEBKGND falls through to DefWindowProcW which uses the registered BLACK_BRUSH.
    return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)


# Keep a persistent global reference to the WNDPROC callback to prevent GC access violations
GLOBAL_OVERLAY_WNDPROC_CB = WNDPROC(_global_overlay_wndproc)


HCURSOR = getattr(wintypes, "HCURSOR", getattr(wintypes, "HICON", wintypes.HANDLE))


class WNDCLASSW(ctypes.Structure):
    """Win32 WNDCLASSW structure."""
    _fields_ = [
        ("style", UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


_user32.RegisterClassW.restype = wintypes.ATOM
_user32.RegisterClassW.argtypes = [ctypes.c_void_p]


class Win32Overlay:
    """High-performance, non-activating full-screen semi-transparent Win32 overlay.

    Spans all physical monitors via virtual screen coordinates and renders a
    semi-transparent glass plane. Bypasses the Windows input queue via WS_EX_NOACTIVATE
    and SWP_NOACTIVATE to ensure 0 WM_ACTIVATE or WM_KILLFOCUS messages reach
    active background AV rendering engines.
    """

    _class_registered = False
    _class_lock = threading.Lock()
    _class_name = "InputLocker_Win32OverlayClass_V3"

    def __init__(
        self,
        alpha: int = 120,
        color_rgb: int = 0x000000,
        auto_prewarm: bool = True,
    ) -> None:
        """Initialize Win32Overlay.

        Args:
            alpha: Transparency level (0=completely transparent, 255=opaque). Default 120 (~47%).
            color_rgb: Background tint color as 0xRRGGBB. Default black (0x000000).
            auto_prewarm: Whether to pre-create the hidden window immediately.
        """
        self.alpha = max(0, min(255, alpha))
        self.color_rgb = color_rgb
        self._hwnd: Optional[int] = None
        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._ready_event = threading.Event()
        self._stop_event = threading.Event()
        self._state_lock = threading.Lock()
        self._is_visible: bool = False

        if auto_prewarm:
            self.prewarm()

    def _register_class_if_needed(self, hinstance: int) -> None:
        """Registers the Win32 window class once per process using the global callback."""
        with Win32Overlay._class_lock:
            if not Win32Overlay._class_registered:
                wc = WNDCLASSW()
                wc.style = 0
                wc.lpfnWndProc = GLOBAL_OVERLAY_WNDPROC_CB
                wc.cbClsExtra = 0
                wc.cbWndExtra = 0
                wc.hInstance = hinstance
                wc.hIcon = 0
                wc.hCursor = 0
                # Use solid black brush
                wc.hbrBackground = _gdi32.GetStockObject(4)  # BLACK_BRUSH
                wc.lpszMenuName = None
                wc.lpszClassName = Win32Overlay._class_name

                res = _user32.RegisterClassW(ctypes.byref(wc))
                if res != 0 or _kernel32.GetLastError() == 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    Win32Overlay._class_registered = True
                else:
                    logger.error(f"Failed to register Win32Overlay class: {_kernel32.GetLastError()}")

    def _get_virtual_desktop_bounds(self) -> Tuple[int, int, int, int]:
        """Queries primary screen metrics covering ONLY the main physical display."""
        # 0 = SM_CXSCREEN, 1 = SM_CYSCREEN (primary monitor only)
        vw = _user32.GetSystemMetrics(0)
        vh = _user32.GetSystemMetrics(1)
        return (0, 0, vw, vh)

    def _worker_thread(self) -> None:
        """Dedicated UI thread creating the window and pumping messages."""
        self._thread_id = _kernel32.GetCurrentThreadId()
        hinstance = _kernel32.GetModuleHandleW(None)
        self._register_class_if_needed(hinstance)

        vx, vy, vw, vh = self._get_virtual_desktop_bounds()

        # Create window in hidden state with non-activating styles
        hwnd = _user32.CreateWindowExW(
            OVERLAY_EX_STYLE,
            Win32Overlay._class_name,
            "InputLocker_OverlayWindow",
            WS_POPUP | WS_CLIPSIBLINGS,
            vx, vy, vw, vh,
            0, 0, hinstance, 0
        )

        if not hwnd:
            logger.error(f"CreateWindowExW failed: error code {_kernel32.GetLastError()}")
            self._ready_event.set()
            return

        self._hwnd = hwnd

        # Set transparency (alpha blending)
        _user32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, LWA_ALPHA)

        # Pre-fill the GDI surface with solid black in this thread.
        # This guarantees DWM has painted content to composite at LWA_ALPHA
        # even before the first WM_ERASEBKGND/WM_PAINT arrives from the message queue.
        hdc = _user32.GetDC(hwnd)
        if hdc:
            rc = RECT(0, 0, vw, vh)
            _user32.FillRect(hdc, ctypes.byref(rc), _gdi32.GetStockObject(4))  # BLACK_BRUSH
            _user32.ReleaseDC(hwnd, hdc)

        self._ready_event.set()

        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            while _user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                if msg.message == WM_QUIT:
                    self._stop_event.set()
                    break
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.001)  # 1 ms — more responsive to cross-thread WM_PAINT

    def prewarm(self) -> None:
        """Pre-creates the overlay window in hidden state to eliminate show latency."""
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                if self._hwnd is None:
                    self._ready_event.wait(timeout=3.0)
                return

            self._stop_event.clear()
            self._ready_event.clear()
            self._thread = threading.Thread(target=self._worker_thread, daemon=True, name="Win32OverlayUIThread")
            self._thread.start()

            if not self._ready_event.wait(timeout=3.0):
                logger.error("Win32Overlay thread initialization timed out")

    def show(self) -> bool:
        """Displays the full-screen semi-transparent overlay without stealing focus.

        Uses SWP_NOACTIVATE | SWP_SHOWWINDOW with HWND_TOPMOST to ensure zero
        focus loss in background applications.

        Returns:
            bool: True if overlay was successfully displayed.
        """
        with self._state_lock:
            if not self._hwnd or not self._thread or not self._thread.is_alive():
                self.prewarm()

            if not self._hwnd:
                return False

            vx, vy, vw, vh = self._get_virtual_desktop_bounds()

            # Set position to virtual desktop and show without activation
            success = bool(_user32.SetWindowPos(
                self._hwnd,
                HWND_TOPMOST,
                vx, vy, vw, vh,
                SWP_NOACTIVATE | SWP_SHOWWINDOW
            ))

            # Force immediate repaint so the black brush fills the layered surface
            if success:
                _user32.InvalidateRect(self._hwnd, None, True)
                _user32.UpdateWindow(self._hwnd)

            self._is_visible = success
            logger.debug(f"Win32Overlay shown across virtual desktop ({vx}, {vy}, {vw}, {vh}): {success}")
            return success

    def hide(self) -> bool:
        """Hides the overlay window without triggering any focus recalculation.

        Uses SWP_HIDEWINDOW | SWP_NOACTIVATE.

        Returns:
            bool: True if overlay was successfully hidden.
        """
        with self._state_lock:
            if not self._hwnd:
                self._is_visible = False
                return True

            success = bool(_user32.SetWindowPos(
                self._hwnd,
                0,
                0, 0, 0, 0,
                SWP_HIDEWINDOW | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
            ))

            self._is_visible = False
            logger.debug(f"Win32Overlay hidden: {success}")
            return success

    def is_visible(self) -> bool:
        """Returns whether the overlay window is currently visible."""
        if not self._hwnd:
            return False
        return bool(_user32.IsWindowVisible(self._hwnd))

    def get_geometry(self) -> Tuple[int, int, int, int]:
        """Returns the current geometry of the virtual desktop as (x, y, width, height)."""
        return self._get_virtual_desktop_bounds()

    def get_ex_style(self) -> int:
        """Returns the Win32 extended style flags of the overlay window."""
        if not self._hwnd:
            return 0
        GWL_EXSTYLE = -20
        return int(_user32.GetWindowLongPtrW(self._hwnd, GWL_EXSTYLE))

    def set_alpha(self, alpha: int) -> bool:
        """Dynamically adjusts the transparency alpha value (0-255)."""
        self.alpha = max(0, min(255, alpha))
        if self._hwnd:
            return bool(_user32.SetLayeredWindowAttributes(self._hwnd, 0, self.alpha, LWA_ALPHA))
        return False

    @property
    def hwnd(self) -> Optional[int]:
        """Returns the HWND of the overlay window."""
        return self._hwnd

    def close(self) -> None:
        """Closes and destroys the overlay window and terminates the worker thread."""
        with self._state_lock:
            self._stop_event.set()
            if self._hwnd:
                _user32.PostMessageW(self._hwnd, WM_CLOSE, 0, 0)
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=3.0)
            self._hwnd = None
            self._thread = None
            self._is_visible = False

    def __enter__(self) -> Win32Overlay:
        self.prewarm()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

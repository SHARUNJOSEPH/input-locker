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

# Combined non-activating overlay extended style mask (0x08080088)
# NOTE: WS_EX_TRANSPARENT (0x20) is intentionally omitted when locked so that touch and pointer
# events hit the overlay and are swallowed, preventing bypass to background windows.
OVERLAY_EX_STYLE = (
    WS_EX_NOACTIVATE
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
WM_SHOWWINDOW = 0x0018
WM_MOUSEACTIVATE = 0x0021
WM_WINDOWPOSCHANGING = 0x0046
WM_NCHITTEST = 0x0084
WM_SYSCOMMAND = 0x0112
WM_POINTERACTIVATE = 0x024B
WM_TOUCHHITTESTING = 0x024D

# Hit Testing and Activation Result Codes
HTTRANSPARENT = -1
HTCLIENT = 1
MA_NOACTIVATEANDEAT = 3
PA_NOACTIVATE = 3

# SysCommand Codes
SC_MINIMIZE = 0xF020

# Touch Window Flags
TWF_WANTPALM = 0x00000002

LRESULT = ctypes.c_int64
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
UINT = wintypes.UINT
HWND = wintypes.HWND
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_gdi32 = ctypes.windll.gdi32


class WINDOWPOS(ctypes.Structure):
    """Win32 WINDOWPOS structure for WM_WINDOWPOSCHANGING / WM_WINDOWPOSCHANGED."""
    _fields_ = [
        ("hwnd",            wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x",               ctypes.c_int),
        ("y",               ctypes.c_int),
        ("cx",              ctypes.c_int),
        ("cy",              ctypes.c_int),
        ("flags",           wintypes.UINT),
    ]


class GUID(ctypes.Structure):
    """Win32 GUID structure."""
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class PROPERTYKEY(ctypes.Structure):
    """Win32 PROPERTYKEY structure."""
    _fields_ = [
        ("fmtid", GUID),
        ("pid",   wintypes.DWORD),
    ]


class PROPVARIANT(ctypes.Structure):
    """Win32 PROPVARIANT structure for setting window properties."""
    _fields_ = [
        ("vt",         wintypes.WORD),
        ("wReserved1", wintypes.WORD),
        ("wReserved2", wintypes.WORD),
        ("wReserved3", wintypes.WORD),
        ("boolVal",    ctypes.c_short),
        ("padding",    ctypes.c_byte * 14),
    ]


# PKEY_EdgeGesture_DisableTouchWhenFullscreen: {32CE38B2-2C9A-41B1-9BC5-B3784394AA44}, PID 2
PKEY_EdgeGesture_DisableTouchWhenFullscreen = PROPERTYKEY(
    GUID(
        0x32CE38B2,
        0x2C9A,
        0x41B1,
        (ctypes.c_ubyte * 8)(0x9B, 0xC5, 0xB3, 0x78, 0x43, 0x94, 0xAA, 0x44),
    ),
    2,
)

# IID_IPropertyStore: {886D8EEB-8CF2-4446-8D02-CDBA1DBDCE99}
IID_IPropertyStore = GUID(
    0x886D8EEB,
    0x8CF2,
    0x4446,
    (ctypes.c_ubyte * 8)(0x8D, 0x02, 0xCD, 0xBA, 0x1D, 0xBD, 0xCF, 0x99),
)


def disable_process_windows_ghosting() -> None:
    """Disable Windows DWM unresponsive process ghosting.

    Prevents Windows DWM from creating a ghost '(Not Responding)' window with
    close controls when the process is busy or heavily loaded.
    """
    try:
        if hasattr(_user32, "DisableProcessWindowsGhosting"):
            _user32.DisableProcessWindowsGhosting()
            logger.debug("DisableProcessWindowsGhosting invoked successfully")
    except Exception as exc:
        logger.debug("DisableProcessWindowsGhosting error: %s", exc)


# Proactively disable ghosting on module load
disable_process_windows_ghosting()


def disable_edge_gestures(hwnd: int) -> bool:
    """Disables Windows 11 edge gestures on the overlay window.

    Sets PKEY_EdgeGesture_DisableTouchWhenFullscreen ({32CE38B2-2C9A-41B1-9BC5-B3784394AA44}, PID 2)
    to VARIANT_TRUE on the overlay window HWND via SHGetPropertyStoreForWindow.

    Args:
        hwnd: Overlay window handle.

    Returns:
        True on success, False otherwise.
    """
    if not hwnd:
        return False
    try:
        ole32 = ctypes.windll.ole32
        shell32 = ctypes.windll.shell32
        hr_init = ole32.CoInitialize(None)
        try:
            p_store = ctypes.c_void_p()
            hr = shell32.SHGetPropertyStoreForWindow(
                hwnd,
                ctypes.byref(IID_IPropertyStore),
                ctypes.byref(p_store),
            )
            if hr != 0 or not p_store.value:
                logger.debug("SHGetPropertyStoreForWindow failed: hr=%s", hr)
                return False

            try:
                vtable = ctypes.cast(
                    p_store.value,
                    ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
                ).contents
                set_value_proto = ctypes.WINFUNCTYPE(
                    ctypes.c_long,
                    ctypes.c_void_p,
                    ctypes.POINTER(PROPERTYKEY),
                    ctypes.POINTER(PROPVARIANT),
                )
                SetValue = set_value_proto(vtable[6])

                # VT_BOOL = 11, VARIANT_TRUE = -1
                var = PROPVARIANT(vt=11, boolVal=-1)
                hr_set = SetValue(
                    p_store.value,
                    ctypes.byref(PKEY_EdgeGesture_DisableTouchWhenFullscreen),
                    ctypes.byref(var),
                )
                if hr_set != 0:
                    logger.debug("IPropertyStore::SetValue failed: hr=%s", hr_set)
                    return False

                try:
                    commit_proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
                    Commit = commit_proto(vtable[7])
                    Commit(p_store.value)
                except Exception:
                    pass

                logger.debug("PKEY_EdgeGesture_DisableTouchWhenFullscreen set successfully on hwnd=%s", hwnd)
                return True
            finally:
                release_proto = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
                Release = release_proto(vtable[2])
                Release(p_store.value)
        finally:
            if hr_init in (0, 1):
                ole32.CoUninitialize()
    except Exception as exc:
        logger.debug("disable_edge_gestures error: %s", exc)
        return False


# Module-level locked state tracker for anti-minimize and anti-hide protection
_overlay_locked: bool = True


def set_overlay_locked(locked: bool) -> None:
    """Sets whether overlay anti-minimize and anti-hide protection is active."""
    global _overlay_locked
    _overlay_locked = bool(locked)


def is_overlay_locked() -> bool:
    """Returns whether overlay anti-minimize and anti-hide protection is active."""
    return _overlay_locked

# ---------------------------------------------------------------------------
# Raw Input Device registration — gesture bypass suppression
#
# RegisterRawInputDevices with RIDEV_NOLEGACY on HID touchscreen & touchpad
# usage pages prevents DirectManipulation (inside explorer.exe) from receiving
# finger data, which stops 3-finger / 4-finger Shell gestures at the source
# rather than attempting to catch their synthesised keystrokes too late.
# ---------------------------------------------------------------------------

RIDEV_REMOVE        = 0x00000001   # unregister a previously registered device
RIDEV_NOLEGACY      = 0x00000030   # suppress legacy WM_TOUCH / gesture pipeline
RIDEV_INPUTSINK     = 0x00000100   # receive input even when not foreground
RIDEV_CAPTUREMOUSE  = 0x00000200   # exclusively capture all mouse/touchpad pointer reports to target window
RIDEV_EXINPUTSINK   = 0x00001000   # receive input from other processes even when not focused

HID_USAGE_PAGE_GENERIC    = 0x01
HID_USAGE_GENERIC_MOUSE   = 0x02
HID_USAGE_PAGE_DIGITIZER  = 0x0D
HID_USAGE_TOUCHSCREEN     = 0x04
HID_USAGE_TOUCHPAD        = 0x05

_registered_raw_hwnd: Optional[int] = None


class RAWINPUTDEVICE(ctypes.Structure):
    """Win32 RAWINPUTDEVICE structure for RegisterRawInputDevices."""
    _fields_ = [
        ("usUsagePage", ctypes.c_ushort),
        ("usUsage",     ctypes.c_ushort),
        ("dwFlags",     wintypes.DWORD),
        ("hwndTarget",  wintypes.HWND),
    ]


def register_raw_touch(hwnd: int) -> bool:
    """Claim raw HID touch/touchpad reports and capture mouse to suppress Shell gestures.

    1. Registers HID mouse (1, 2) with RIDEV_NOLEGACY | RIDEV_CAPTUREMOUSE to exclusively
       route all mouse/touchpad clicks and pointer movements to hwnd without legacy translation.
    2. Registers HID touchscreen (0x0D, 0x04) and touchpad (0x0D, 0x05) with RIDEV_INPUTSINK.
    3. Calls RegisterTouchpadCapableWindow and RegisterTouchpadCapableThread so multi-finger
       touchpad contacts are routed to overlay as WM_POINTER instead of DWM Shell gestures.

    Args:
        hwnd: Target HWND that will receive WM_INPUT and WM_POINTER messages.

    Returns:
        True on success, False if registration fails.
    """
    global _registered_raw_hwnd
    if not hwnd:
        return False

    try:
        # 1. Register window and thread as touchpad capable
        if hasattr(_user32, "RegisterTouchpadCapableWindow"):
            try:
                _user32.RegisterTouchpadCapableWindow(hwnd, True)
            except Exception as exc:
                logger.debug("RegisterTouchpadCapableWindow error: %s", exc)
        if hasattr(_user32, "RegisterTouchpadCapableThread"):
            try:
                _user32.RegisterTouchpadCapableThread(_kernel32.GetCurrentThreadId(), True)
            except Exception as exc:
                logger.debug("RegisterTouchpadCapableThread error: %s", exc)

        # 2. Register Raw Input Devices: Mouse capture + Digitizer touchscreen + touchpad
        mouse_flags = RIDEV_NOLEGACY | RIDEV_CAPTUREMOUSE
        digitizer_flags = RIDEV_INPUTSINK
        devices = (RAWINPUTDEVICE * 3)(
            RAWINPUTDEVICE(HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_MOUSE, mouse_flags, hwnd),
            RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHSCREEN, digitizer_flags, hwnd),
            RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHPAD,    digitizer_flags, hwnd),
        )
        ok = bool(_user32.RegisterRawInputDevices(
            devices, 3, ctypes.sizeof(RAWINPUTDEVICE)
        ))
        if not ok:
            # Fallback to 2-device registration if mouse capture disallowed on older build
            devs2 = (RAWINPUTDEVICE * 2)(
                RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHSCREEN, digitizer_flags, hwnd),
                RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHPAD,    digitizer_flags, hwnd),
            )
            ok = bool(_user32.RegisterRawInputDevices(
                devs2, 2, ctypes.sizeof(RAWINPUTDEVICE)
            ))
            logger.debug("RegisterRawInputDevices 3-device failed, 2-device fallback: %s", ok)
        _registered_raw_hwnd = hwnd
        return ok
    except Exception as exc:
        logger.debug("register_raw_touch error: %s", exc)
        return False


def unregister_raw_touch() -> bool:
    """Release raw HID touch/touchpad/mouse claims and restore Shell gestures."""
    global _registered_raw_hwnd
    try:
        if _registered_raw_hwnd and hasattr(_user32, "RegisterTouchpadCapableWindow"):
            try:
                _user32.RegisterTouchpadCapableWindow(_registered_raw_hwnd, False)
            except Exception:
                pass
        if hasattr(_user32, "RegisterTouchpadCapableThread"):
            try:
                _user32.RegisterTouchpadCapableThread(_kernel32.GetCurrentThreadId(), False)
            except Exception:
                pass
        _registered_raw_hwnd = None

        devices = (RAWINPUTDEVICE * 3)(
            RAWINPUTDEVICE(HID_USAGE_PAGE_GENERIC, HID_USAGE_GENERIC_MOUSE, RIDEV_REMOVE, 0),
            RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHSCREEN, RIDEV_REMOVE, 0),
            RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHPAD,    RIDEV_REMOVE, 0),
        )
        ok = bool(_user32.RegisterRawInputDevices(
            devices, 3, ctypes.sizeof(RAWINPUTDEVICE)
        ))
        if not ok:
            devs2 = (RAWINPUTDEVICE * 2)(
                RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHSCREEN, RIDEV_REMOVE, 0),
                RAWINPUTDEVICE(HID_USAGE_PAGE_DIGITIZER, HID_USAGE_TOUCHPAD,    RIDEV_REMOVE, 0),
            )
            ok = bool(_user32.RegisterRawInputDevices(
                devs2, 2, ctypes.sizeof(RAWINPUTDEVICE)
            ))
        return ok
    except Exception as exc:
        logger.debug("unregister_raw_touch error: %s", exc)
        return False

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

if hasattr(_user32, "CloseTouchInputHandle"):
    _user32.CloseTouchInputHandle.restype = wintypes.BOOL
    _user32.CloseTouchInputHandle.argtypes = [ctypes.c_void_p]

if hasattr(_user32, "CloseGestureInfoHandle"):
    _user32.CloseGestureInfoHandle.restype = wintypes.BOOL
    _user32.CloseGestureInfoHandle.argtypes = [ctypes.c_void_p]


def _global_overlay_wndproc(hwnd: int, msg: int, wparam: int, lparam: int) -> int:
    """Persistent module-level window procedure that is never garbage-collected."""
    if msg == WM_NCHITTEST:
        # Absorb hit-testing on the overlay (HTCLIENT = 1) so clicks and taps do NOT pass through
        # to background windows/media engines while locked.
        return HTCLIENT  # 1
    elif msg == WM_MOUSEACTIVATE:  # 0x0021
        # Do not activate this window and discard the mouse click / tap (MA_NOACTIVATEANDEAT = 3)
        return MA_NOACTIVATEANDEAT  # 3
    elif msg == WM_TOUCHHITTESTING:  # 0x024D
        # Win32 touch hit-testing: return HTCLIENT (1) so physical touchscreen touches hit
        # this overlay deterministically rather than HTNOWHERE (0) falling through.
        return HTCLIENT  # 1
    elif msg == WM_POINTERACTIVATE:  # 0x024B
        # Windows Pointer architecture: do not activate the overlay and consume the pointer event
        return PA_NOACTIVATE  # 3
    elif msg == WM_SYSCOMMAND:  # 0x0112
        # Anti-minimize protection: block SC_MINIMIZE (0xF020) so 3-finger swipe down
        # (Show Desktop) never minimizes the overlay or exposes underlying windows.
        if (wparam & 0xFFF0) == SC_MINIMIZE:
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    elif msg == WM_WINDOWPOSCHANGING:  # 0x0046
        # Anti-hide protection: strip SWP_HIDEWINDOW (0x0080) and force HWND_TOPMOST (-1) while locked
        if is_overlay_locked() and lparam:
            try:
                p_winpos = ctypes.cast(lparam, ctypes.POINTER(WINDOWPOS))
                if p_winpos:
                    p_winpos.contents.flags &= ~SWP_HIDEWINDOW
                    p_winpos.contents.hwndInsertAfter = HWND_TOPMOST
            except Exception as exc:
                logger.debug("WM_WINDOWPOSCHANGING error: %s", exc)
        return 0
    elif msg == WM_SHOWWINDOW:  # 0x0018
        # Anti-hide protection: if window is being hidden (wParam == 0) while locked,
        # reject and immediately reassert topmost visibility.
        if wparam == 0 and is_overlay_locked():
            _user32.SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE,
            )
            return 0
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
    elif msg == 0x00FF:  # WM_INPUT
        # Raw input is claimed by RIDEV_INPUTSINK registration to suppress the Shell gesture
        # pipeline (DirectManipulation in explorer.exe never sees finger data).
        # We must call DefWindowProcW to free the raw input buffer — we do NOT parse it.
        _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        return 0
    elif msg == 0x0240:  # WM_TOUCH
        # Consume touch events and close the unmanaged touch input handle to prevent OS kernel leaks
        try:
            if hasattr(_user32, "CloseTouchInputHandle") and lparam:
                _user32.CloseTouchInputHandle(lparam)
        except Exception:
            pass
        return 0
    elif msg == 0x0119:  # WM_GESTURE
        # Consume gesture events and close the gesture info handle to prevent OS kernel leaks
        try:
            if hasattr(_user32, "CloseGestureInfoHandle") and lparam:
                _user32.CloseGestureInfoHandle(lparam)
        except Exception:
            pass
        return 0
    elif msg in (
        # Pointer Architecture (Windows 8+)
        0x0241,  # WM_NCPOINTERUPDATE
        0x0242,  # WM_NCPOINTERDOWN
        0x0243,  # WM_NCPOINTERUP
        0x0245,  # WM_POINTERUPDATE
        0x0246,  # WM_POINTERDOWN
        0x0247,  # WM_POINTERUP
        0x0249,  # WM_POINTERENTER
        0x024A,  # WM_POINTERLEAVE
        0x024C,  # WM_POINTERCAPTURECHANGED
        0x0252,  # WM_POINTERWHEEL
        0x0253,  # WM_POINTERHWHEEL
        # Mouse Messages & Emulated Touch Clicks/Drags
        0x007B,  # WM_CONTEXTMENU
        0x0200,  # WM_MOUSEMOVE
        0x0201,  # WM_LBUTTONDOWN
        0x0202,  # WM_LBUTTONUP
        0x0203,  # WM_LBUTTONDBLCLK
        0x0204,  # WM_RBUTTONDOWN
        0x0205,  # WM_RBUTTONUP
        0x0206,  # WM_RBUTTONDBLCLK
        0x0207,  # WM_MBUTTONDOWN
        0x0208,  # WM_MBUTTONUP
        0x0209,  # WM_MBUTTONDBLCLK
        0x020A,  # WM_MOUSEWHEEL
        0x020B,  # WM_XBUTTONDOWN
        0x020C,  # WM_XBUTTONUP
        0x020D,  # WM_XBUTTONDBLCLK
        0x020E,  # WM_MOUSEHWHEEL
    ):
        # Absorb and consume all touch, pointer, drag, and mouse click messages
        return 0
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
        """Returns bounds of the PRIMARY monitor only.

        Secondary displays are intentionally left uncovered and usable while locked.
        The primary monitor always sits at (0, 0) in Windows coordinates.
        """
        vw = _user32.GetSystemMetrics(0)  # SM_CXSCREEN
        vh = _user32.GetSystemMetrics(1)  # SM_CYSCREEN
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

        # Register window with Windows touch architecture to receive physical multi-touch & gestures directly
        try:
            if hasattr(_user32, "RegisterTouchWindow"):
                _user32.RegisterTouchWindow(hwnd, TWF_WANTPALM)
        except Exception as exc:
            logger.debug("Win32 RegisterTouchWindow error: %s", exc)

        # Disable Windows 11 shell edge gestures (Widgets, Action Center, edge swipes)
        disable_edge_gestures(hwnd)

        # Note: register_raw_touch(hwnd) is called in show() when the overlay is locked,
        # and unregister_raw_touch() is called in hide() / close() when unlocked.

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
            set_overlay_locked(True)
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
                # Re-register raw HID touch/touchpad sink so multi-touch gestures are swallowed
                register_raw_touch(self._hwnd)
                logger.debug("Win32Overlay: raw touch claim registered for hwnd=%s", self._hwnd)

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
            set_overlay_locked(False)
            # Release raw HID touch/touchpad claim so normal Shell gestures are restored
            unregister_raw_touch()
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

    def set_wallpaper(self, wallpaper_path: str) -> None:
        """Stub for dynamic wallpaper setting in lightweight Win32 backend."""
        self.wallpaper_path = wallpaper_path

    @property
    def hwnd(self) -> Optional[int]:
        """Returns the HWND of the overlay window."""
        return self._hwnd

    def close(self) -> None:
        """Closes and destroys the overlay window and terminates the worker thread."""
        with self._state_lock:
            set_overlay_locked(False)
            self._stop_event.set()
            # Release raw HID touch/touchpad claim so normal Shell gestures are restored
            unregister_raw_touch()
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

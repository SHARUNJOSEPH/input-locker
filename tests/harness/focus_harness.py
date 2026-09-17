"""Companion Win32 focus and input verification harness.

Creates an authentic top-level Win32 window in a background thread and logs all
window activation, focus, and input messages. Used to verify zero focus disruption
to live AV rendering engines (Resolume, WATCHOUT, DAWs) and to audit input delivery.
"""

import ctypes
from ctypes import wintypes
import time
import threading
from typing import List, Dict, Any, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

LRESULT = ctypes.c_int64
WPARAM = wintypes.WPARAM
LPARAM = wintypes.LPARAM
UINT = wintypes.UINT
HWND = wintypes.HWND

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, UINT, WPARAM, LPARAM)
_ACTIVE_WNDPROCS = []

user32.GetForegroundWindow.restype = HWND
user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
user32.AllowSetForegroundWindow.restype = wintypes.BOOL
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
user32.UnregisterClassW.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [HWND]
user32.DestroyWindow.restype = wintypes.BOOL

user32.DefWindowProcW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), HWND, UINT, UINT, UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostMessageW.argtypes = [HWND, UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.PostQuitMessage.restype = None
user32.SetForegroundWindow.argtypes = [HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetActiveWindow.argtypes = [HWND]
user32.SetActiveWindow.restype = HWND
user32.SetFocus.argtypes = [HWND]
user32.SetFocus.restype = HWND
user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
user32.AttachThreadInput.restype = wintypes.BOOL
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.RegisterClassW.argtypes = [ctypes.c_void_p]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.restype = HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
    wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID
]
user32.BringWindowToTop.argtypes = [HWND]
user32.BringWindowToTop.restype = wintypes.BOOL


class CompanionFocusHarness:
    """Simulates an external AV staging engine (e.g. Resolume / WATCHOUT / DAW).
    
    Creates a native Win32 window and captures all focus, activation, and input messages.
    """
    WM_ACTIVATE = 0x0006
    WM_SETFOCUS = 0x0007
    WM_KILLFOCUS = 0x0008
    WM_NCACTIVATE = 0x0086
    WM_ACTIVATEAPP = 0x001C
    WM_CLOSE = 0x0010
    WM_DESTROY = 0x0002
    
    # Input messages
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_CHAR = 0x0102
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_MOUSEMOVE = 0x0200
    WM_LBUTTONDOWN = 0x0201
    WM_LBUTTONUP = 0x0202
    WM_RBUTTONDOWN = 0x0204
    WM_RBUTTONUP = 0x0205
    WM_MBUTTONDOWN = 0x0207
    WM_MBUTTONUP = 0x0208
    WM_MOUSEWHEEL = 0x020A

    def __init__(self, title: str = "Staging Engine Simulation (Resolume)"):
        self.title = title
        self.hwnd: Optional[int] = None
        self.events: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.ready_event = threading.Event()
        self._wndproc_cb = None
        self._is_active = False
        self._is_focused = False

    def _wndproc(self, hwnd: HWND, msg: int, wparam: WPARAM, lparam: LPARAM) -> int:
        ts = time.perf_counter()
        
        # Focus & Activation auditing
        if msg == self.WM_ACTIVATE:
            wa_type = wparam & 0xFFFF
            wa_name = {0: "WA_INACTIVE", 1: "WA_ACTIVE", 2: "WA_CLICKACTIVE"}.get(wa_type, str(wa_type))
            self._is_active = (wa_type != 0)
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "focus",
                    "message": "WM_ACTIVATE",
                    "type": wa_name,
                    "active": self._is_active,
                    "wparam": wparam,
                })
        elif msg == self.WM_SETFOCUS:
            self._is_focused = True
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "focus",
                    "message": "WM_SETFOCUS",
                    "focused": True,
                })
        elif msg == self.WM_KILLFOCUS:
            self._is_focused = False
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "focus",
                    "message": "WM_KILLFOCUS",
                    "focused": False,
                })
        elif msg == self.WM_NCACTIVATE:
            is_active = bool(wparam)
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "focus",
                    "message": "WM_NCACTIVATE",
                    "active": is_active,
                })
        elif msg == self.WM_ACTIVATEAPP:
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "focus",
                    "message": "WM_ACTIVATEAPP",
                    "active": bool(wparam),
                })
        # Input auditing
        elif msg in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "keyboard",
                    "message": "WM_KEYDOWN" if msg == self.WM_KEYDOWN else "WM_SYSKEYDOWN",
                    "vk": wparam,
                })
        elif msg in (self.WM_KEYUP, self.WM_SYSKEYUP):
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "keyboard",
                    "message": "WM_KEYUP" if msg == self.WM_KEYUP else "WM_SYSKEYUP",
                    "vk": wparam,
                })
        elif msg == self.WM_CHAR:
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "keyboard",
                    "message": "WM_CHAR",
                    "char": chr(wparam) if 0 <= wparam <= 0x10FFFF else "",
                    "code": wparam,
                })
        elif msg in (self.WM_LBUTTONDOWN, self.WM_RBUTTONDOWN, self.WM_MBUTTONDOWN):
            btn_name = {
                self.WM_LBUTTONDOWN: "left",
                self.WM_RBUTTONDOWN: "right",
                self.WM_MBUTTONDOWN: "middle",
            }[msg]
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "mouse",
                    "message": "MOUSEDOWN",
                    "button": btn_name,
                    "x": lparam & 0xFFFF,
                    "y": (lparam >> 16) & 0xFFFF,
                })
        elif msg in (self.WM_LBUTTONUP, self.WM_RBUTTONUP, self.WM_MBUTTONUP):
            btn_name = {
                self.WM_LBUTTONUP: "left",
                self.WM_RBUTTONUP: "right",
                self.WM_MBUTTONUP: "middle",
            }[msg]
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "mouse",
                    "message": "MOUSEUP",
                    "button": btn_name,
                    "x": lparam & 0xFFFF,
                    "y": (lparam >> 16) & 0xFFFF,
                })
        elif msg == self.WM_MOUSEMOVE:
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "mouse",
                    "message": "WM_MOUSEMOVE",
                    "x": lparam & 0xFFFF,
                    "y": (lparam >> 16) & 0xFFFF,
                })
        elif msg == self.WM_MOUSEWHEEL:
            delta = ctypes.c_short((wparam >> 16) & 0xFFFF).value
            with self._lock:
                self.events.append({
                    "timestamp": ts,
                    "category": "mouse",
                    "message": "WM_MOUSEWHEEL",
                    "delta": delta,
                })
        elif msg == self.WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        # Attach thread to active desktop
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            user32.SetThreadDesktop(h_input)

        self._wndproc_cb = WNDPROC(self._wndproc)

        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ('style', UINT),
                ('lpfnWndProc', WNDPROC),
                ('cbClsExtra', ctypes.c_int),
                ('cbWndExtra', ctypes.c_int),
                ('hInstance', wintypes.HINSTANCE),
                ('hIcon', wintypes.HICON),
                ('hCursor', wintypes.HCURSOR),
                ('hbrBackground', wintypes.HBRUSH),
                ('lpszMenuName', wintypes.LPCWSTR),
                ('lpszClassName', wintypes.LPCWSTR),
            ]

        import uuid
        hinstance = kernel32.GetModuleHandleW(None)
        self._class_name = f"FocusHarness_{uuid.uuid4().hex}"
        _ACTIVE_WNDPROCS.append(self._wndproc_cb)

        wc = WNDCLASSW()
        wc.style = 0x0003  # CS_HREDRAW | CS_VREDRAW
        wc.lpfnWndProc = self._wndproc_cb
        wc.hInstance = hinstance
        wc.lpszClassName = self._class_name
        user32.RegisterClassW(ctypes.byref(wc))

        WS_OVERLAPPEDWINDOW = 0x00CF0000
        WS_VISIBLE = 0x10000000
        self.hwnd = user32.CreateWindowExW(
            0, self._class_name, self.title,
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            100, 100, 640, 480,
            0, 0, hinstance, 0
        )
        user32.ShowWindow(self.hwnd, 1)  # SW_SHOWNORMAL
        user32.SetForegroundWindow(self.hwnd)
        user32.SetActiveWindow(self.hwnd)
        user32.SetFocus(self.hwnd)
        self.running = True
        self.ready_event.set()

        msg = wintypes.MSG()
        while self.running:
            while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):
                if msg.message == 0x0012:  # WM_QUIT
                    self.running = False
                    break
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            time.sleep(0.005)

    def start(self, timeout: float = 3.0):
        """Starts the companion harness window thread and waits for initialization."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self.ready_event.wait(timeout=timeout):
            raise TimeoutError("CompanionFocusHarness failed to initialize within timeout.")
        time.sleep(0.1)  # Allow initial focus messages to settle

    def stop(self):
        """Stops the message pump and closes the window."""
        self.running = False
        if self.hwnd:
            user32.PostMessageW(self.hwnd, self.WM_CLOSE, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if hasattr(self, "_class_name") and self._class_name:
            hinst = kernel32.GetModuleHandleW(None)
            user32.UnregisterClassW(self._class_name, hinst)
        if hasattr(self, "_wndproc_cb") and self._wndproc_cb in _ACTIVE_WNDPROCS:
            try:
                _ACTIVE_WNDPROCS.remove(self._wndproc_cb)
            except ValueError:
                pass

    def clear(self):
        """Clears all accumulated event records."""
        with self._lock:
            self.events.clear()

    def bring_to_foreground(self):
        """Forces the companion window to the foreground and active focus."""
        if not self.hwnd:
            return

        h_input = user32.OpenInputDesktop(0, False, 0x01FF)
        if h_input:
            user32.SetThreadDesktop(h_input)

        cur_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(self.hwnd, None)

        # Attach to the current foreground window thread to satisfy Windows foreground lock
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0

        attached_fg = False
        attached_target = False
        try:
            if fg_thread and fg_thread != cur_thread:
                user32.AttachThreadInput(cur_thread, fg_thread, True)
                attached_fg = True

            if target_thread and target_thread != cur_thread:
                user32.AttachThreadInput(cur_thread, target_thread, True)
                attached_target = True

            user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
            user32.BringWindowToTop(self.hwnd)
            user32.SetForegroundWindow(self.hwnd)
            user32.SetActiveWindow(self.hwnd)
            user32.SetFocus(self.hwnd)
        finally:
            if attached_fg:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            if attached_target:
                user32.AttachThreadInput(cur_thread, target_thread, False)

        time.sleep(0.05)

    def get_focus_loss_events(self) -> List[Dict[str, Any]]:
        """Returns all logged events indicating focus or activation loss."""
        with self._lock:
            return [
                e for e in self.events
                if e.get("message") == "WM_KILLFOCUS"
                or (e.get("message") == "WM_ACTIVATE" and e.get("type") == "WA_INACTIVE")
                or (e.get("message") == "WM_NCACTIVATE" and not e.get("active"))
                or (e.get("message") == "WM_ACTIVATEAPP" and not e.get("active"))
            ]

    def assert_zero_focus_disruption(self):
        """Asserts that exactly 0 focus-loss messages were received by the background window."""
        losses = self.get_focus_loss_events()
        assert len(losses) == 0, (
            f"Focus disruption detected on background window! Disruption events: {losses}"
        )

    def get_received_input_events(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns input events (keyboard or mouse) received by this window."""
        with self._lock:
            if category:
                return [e for e in self.events if e.get("category") == category]
            return [e for e in self.events if e.get("category") in ("keyboard", "mouse")]

    def assert_zero_input_received(self, category: Optional[str] = None):
        """Asserts that no input leaked through to this background window."""
        received = self.get_received_input_events(category)
        assert len(received) == 0, (
            f"Input leaked to background window! Received {len(received)} events: {received[:5]}"
        )

    def assert_zero_keydown_received(self):
        """Asserts that no WM_KEYDOWN, WM_SYSKEYDOWN, or WM_CHAR leaked to this window."""
        with self._lock:
            keydowns = [
                e for e in self.events
                if e.get("category") == "keyboard"
                and e.get("message") in ("WM_KEYDOWN", "WM_SYSKEYDOWN", "WM_CHAR")
            ]
            assert len(keydowns) == 0, f"Keydown leaked to background window! {keydowns}"

    def assert_input_received(self, min_count: int = 1, category: Optional[str] = None):
        """Asserts that this window successfully received at least min_count input events."""
        received = self.get_received_input_events(category)
        assert len(received) >= min_count, (
            f"Expected at least {min_count} events in {category or 'any'}, but only received {len(received)}"
        )

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def is_focused(self) -> bool:
        return self._is_focused


FocusHarness = CompanionFocusHarness

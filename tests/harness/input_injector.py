"""Win32 SendInput synthetic event injector with desktop attachment.

Features:
- Rigorous 40-byte 64-bit Windows INPUT union layout
- OpenInputDesktop() / SetThreadDesktop() attachment on injection threads
- Comprehensive synthetic keyboard injection (keys, combos, text, unicode)
- Synthetic mouse injection (clicks, relative/absolute moves, drag, wheel)
- Win32 cursor interrogation (GetCursorPos, ClipCursor, GetClipCursor)
"""

import ctypes
from ctypes import wintypes
import time
from typing import List, Tuple, Optional

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---------------------------------------------------------------------------
# Win32 INPUT Structures & Alignment Verification
# ---------------------------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_XDOWN = 0x0080
MOUSEEVENTF_XUP = 0x0100
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000
MOUSEEVENTF_ABSOLUTE = 0x8000

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ('dx', wintypes.LONG),
        ('dy', wintypes.LONG),
        ('mouseData', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ('wVk', wintypes.WORD),
        ('wScan', wintypes.WORD),
        ('dwFlags', wintypes.DWORD),
        ('time', wintypes.DWORD),
        ('dwExtraInfo', ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ('uMsg', wintypes.DWORD),
        ('wParamL', wintypes.WORD),
        ('wParamH', wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ('mi', MOUSEINPUT),
        ('ki', KEYBDINPUT),
        ('hi', HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ('type', wintypes.DWORD),
        ('u', INPUT_UNION),
    ]


# Validate 64-bit 40-byte strict layout
assert ctypes.sizeof(INPUT) == 40, (
    f"INPUT struct size mismatch: expected 40 bytes on 64-bit Windows, got {ctypes.sizeof(INPUT)}"
)

user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT


class RECT(ctypes.Structure):
    _fields_ = [
        ('left', wintypes.LONG),
        ('top', wintypes.LONG),
        ('right', wintypes.LONG),
        ('bottom', wintypes.LONG),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ('x', wintypes.LONG),
        ('y', wintypes.LONG),
    ]


user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = wintypes.BOOL

user32.ClipCursor.argtypes = [ctypes.POINTER(RECT)]
user32.ClipCursor.restype = wintypes.BOOL

user32.GetClipCursor.argtypes = [ctypes.POINTER(RECT)]
user32.GetClipCursor.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# Input Injector Implementation
class InputInjector:
    """Win32 SendInput wrapper with desktop attachment and AV staging test utilities."""

    # Flags
    KEYEVENTF_KEYDOWN = KEYEVENTF_KEYDOWN
    KEYEVENTF_EXTENDEDKEY = KEYEVENTF_EXTENDEDKEY
    KEYEVENTF_KEYUP = KEYEVENTF_KEYUP
    KEYEVENTF_UNICODE = KEYEVENTF_UNICODE
    KEYEVENTF_SCANCODE = KEYEVENTF_SCANCODE

    # Virtual Keys
    VK_LBUTTON = 0x01
    VK_RBUTTON = 0x02
    VK_MBUTTON = 0x04
    VK_BACK = 0x08
    VK_TAB = 0x09
    VK_RETURN = 0x0D
    VK_SHIFT = 0x10
    VK_CONTROL = 0x11
    VK_MENU = 0x12  # Alt
    VK_ESCAPE = 0x1B
    VK_SPACE = 0x20
    VK_PRIOR = 0x21  # PgUp
    VK_NEXT = 0x22   # PgDn
    VK_END = 0x23
    VK_HOME = 0x24
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    VK_DELETE = 0x2E
    VK_LWIN = 0x5B
    VK_RWIN = 0x5C
    VK_F1 = 0x70
    VK_F2 = 0x71
    VK_F3 = 0x72
    VK_F4 = 0x73
    VK_F5 = 0x74
    VK_F6 = 0x75
    VK_F7 = 0x76
    VK_F8 = 0x77
    VK_F9 = 0x78
    VK_F10 = 0x79
    VK_F11 = 0x7A
    VK_F12 = 0x7B
    VK_LSHIFT = 0xA0
    VK_RSHIFT = 0xA1
    VK_LCONTROL = 0xA2
    VK_RCONTROL = 0xA3
    VK_LMENU = 0xA4
    VK_RMENU = 0xA5
    VK_U = 0x55

    @classmethod
    def ensure_desktop_attached(cls) -> bool:
        """Attaches the current calling thread to the active interactive input desktop."""
        h_input = user32.OpenInputDesktop(0, False, 0x01FF)  # MAXIMUM_ALLOWED
        if h_input:
            success = bool(user32.SetThreadDesktop(h_input))
            return success
        return False

    @classmethod
    def send_inputs(cls, inputs: List[INPUT]) -> int:
        """Dispatches an array of synthetic INPUT structures to Windows User32."""
        cls.ensure_desktop_attached()
        n = len(inputs)
        if n == 0:
            return 0
        arr = (INPUT * n)(*inputs)
        sent = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
        return sent

    # -----------------------------------------------------------------------
    # Keyboard Injection
    # -----------------------------------------------------------------------

    @classmethod
    def make_key_input(cls, vk: int, flags: int = KEYEVENTF_KEYDOWN, scan: int = 0) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.u.ki.wVk = vk
        inp.u.ki.wScan = scan
        inp.u.ki.dwFlags = flags
        inp.u.ki.time = 0
        inp.u.ki.dwExtraInfo = None
        return inp

    @classmethod
    def key_down(cls, vk: int, extended: bool = False) -> int:
        flags = KEYEVENTF_KEYDOWN
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        return cls.send_inputs([cls.make_key_input(vk, flags)])

    @classmethod
    def key_up(cls, vk: int, extended: bool = False) -> int:
        flags = KEYEVENTF_KEYUP
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        return cls.send_inputs([cls.make_key_input(vk, flags)])

    @classmethod
    def press_key(cls, vk: int, duration_s: float = 0.01, extended: bool = False) -> int:
        cls.key_down(vk, extended=extended)
        if duration_s > 0:
            time.sleep(duration_s)
        cls.key_up(vk, extended=extended)
        return 2

    @classmethod
    def press_f11(cls, duration_s: float = 0.01) -> int:
        """Sends F11 (lock hotkey)."""
        return cls.press_key(cls.VK_F11, duration_s=duration_s)

    @classmethod
    def press_unlock_combo(cls, duration_s: float = 0.01) -> int:
        """Sends the full unlock combo: Ctrl + Alt + Shift + U in sequence."""
        # Key down sequence
        inputs_down = [
            cls.make_key_input(cls.VK_CONTROL, KEYEVENTF_KEYDOWN),
            cls.make_key_input(cls.VK_MENU, KEYEVENTF_KEYDOWN),
            cls.make_key_input(cls.VK_SHIFT, KEYEVENTF_KEYDOWN),
            cls.make_key_input(cls.VK_U, KEYEVENTF_KEYDOWN),
        ]
        cls.send_inputs(inputs_down)
        if duration_s > 0:
            time.sleep(duration_s)
        # Key up sequence (reverse order)
        inputs_up = [
            cls.make_key_input(cls.VK_U, KEYEVENTF_KEYUP),
            cls.make_key_input(cls.VK_SHIFT, KEYEVENTF_KEYUP),
            cls.make_key_input(cls.VK_MENU, KEYEVENTF_KEYUP),
            cls.make_key_input(cls.VK_CONTROL, KEYEVENTF_KEYUP),
        ]
        cls.send_inputs(inputs_up)
        return 8

    @classmethod
    def press_partial_combo(
        cls,
        omit_ctrl: bool = False,
        omit_alt: bool = False,
        omit_shift: bool = False,
        key_vk: int = 0x55,
        duration_s: float = 0.01,
    ) -> int:
        """Sends a partial or altered unlock combination for boundary verification."""
        downs = []
        ups = []
        if not omit_ctrl:
            downs.append(cls.make_key_input(cls.VK_CONTROL, KEYEVENTF_KEYDOWN))
            ups.append(cls.make_key_input(cls.VK_CONTROL, KEYEVENTF_KEYUP))
        if not omit_alt:
            downs.append(cls.make_key_input(cls.VK_MENU, KEYEVENTF_KEYDOWN))
            ups.append(cls.make_key_input(cls.VK_MENU, KEYEVENTF_KEYUP))
        if not omit_shift:
            downs.append(cls.make_key_input(cls.VK_SHIFT, KEYEVENTF_KEYDOWN))
            ups.append(cls.make_key_input(cls.VK_SHIFT, KEYEVENTF_KEYUP))
        
        downs.append(cls.make_key_input(key_vk, KEYEVENTF_KEYDOWN))
        ups.append(cls.make_key_input(key_vk, KEYEVENTF_KEYUP))

        cls.send_inputs(downs)
        if duration_s > 0:
            time.sleep(duration_s)
        ups.reverse()
        cls.send_inputs(ups)
        return len(downs) + len(ups)

    @classmethod
    def send_keys(cls, vk_list: List[int], delay_between_s: float = 0.005) -> int:
        """Presses each virtual key in sequence."""
        total = 0
        for vk in vk_list:
            total += cls.press_key(vk, duration_s=0.005)
            if delay_between_s > 0:
                time.sleep(delay_between_s)
        return total

    @classmethod
    def type_text(cls, text: str, delay_between_s: float = 0.005) -> int:
        """Sends unicode characters using KEYEVENTF_UNICODE."""
        inputs = []
        for ch in text:
            code = ord(ch)
            inp_down = INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down.u.ki.wVk = 0
            inp_down.u.ki.wScan = code
            inp_down.u.ki.dwFlags = KEYEVENTF_UNICODE
            
            inp_up = INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up.u.ki.wVk = 0
            inp_up.u.ki.wScan = code
            inp_up.u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            
            inputs.extend([inp_down, inp_up])
        return cls.send_inputs(inputs)

    # -----------------------------------------------------------------------
    # Mouse Injection
    # -----------------------------------------------------------------------

    @classmethod
    def make_mouse_input(
        cls,
        flags: int,
        dx: int = 0,
        dy: int = 0,
        data: int = 0,
    ) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.u.mi.dx = dx
        inp.u.mi.dy = dy
        inp.u.mi.mouseData = data
        inp.u.mi.dwFlags = flags
        inp.u.mi.time = 0
        inp.u.mi.dwExtraInfo = None
        return inp

    @classmethod
    def mouse_click(cls, button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> int:
        """Sends down + up mouse click at current or target coordinates."""
        if x is not None and y is not None:
            cls.mouse_move_absolute(x, y)
            time.sleep(0.005)

        down_flag, up_flag = {
            "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
            "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
        }[button.lower()]

        inputs = [
            cls.make_mouse_input(down_flag),
            cls.make_mouse_input(up_flag),
        ]
        return cls.send_inputs(inputs)

    @classmethod
    def mouse_double_click(cls, button: str = "left", x: Optional[int] = None, y: Optional[int] = None) -> int:
        res1 = cls.mouse_click(button, x, y)
        time.sleep(0.05)
        res2 = cls.mouse_click(button, x, y)
        return res1 + res2

    @classmethod
    def mouse_move_relative(cls, dx: int, dy: int) -> int:
        """Generates relative mouse motion."""
        inp = cls.make_mouse_input(MOUSEEVENTF_MOVE, dx=dx, dy=dy)
        return cls.send_inputs([inp])

    @classmethod
    def mouse_move_absolute(cls, x: int, y: int) -> int:
        """Generates absolute mouse move across virtual screen coordinates."""
        v_left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
        v_top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
        v_width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1920
        v_height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1080

        norm_x = int(((x - v_left) * 65535) / v_width)
        norm_y = int(((y - v_top) * 65535) / v_height)

        flags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | 0x4000  # MOUSEEVENTF_VIRTUALDESK
        inp = cls.make_mouse_input(flags, dx=norm_x, dy=norm_y)
        return cls.send_inputs([inp])

    @classmethod
    def mouse_wheel(cls, delta: int = 120, horizontal: bool = False) -> int:
        """Sends vertical or horizontal scroll wheel delta."""
        flag = MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL
        inp = cls.make_mouse_input(flag, data=delta)
        return cls.send_inputs([inp])

    @classmethod
    def mouse_drag(
        cls,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        steps: int = 10,
        button: str = "left",
    ) -> int:
        """Simulates dragging the mouse while button is held."""
        cls.mouse_move_absolute(start_x, start_y)
        time.sleep(0.01)
        down_flag, up_flag = {
            "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
            "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
        }[button.lower()]

        cls.send_inputs([cls.make_mouse_input(down_flag)])
        total = 1

        for s in range(1, steps + 1):
            cur_x = int(start_x + (end_x - start_x) * (s / steps))
            cur_y = int(start_y + (end_y - start_y) * (s / steps))
            cls.mouse_move_absolute(cur_x, cur_y)
            time.sleep(0.005)
            total += 1

        cls.send_inputs([cls.make_mouse_input(up_flag)])
        total += 1
        return total

    # -----------------------------------------------------------------------
    # Cursor Query & Confinement Utilities
    # -----------------------------------------------------------------------

    @classmethod
    def get_cursor_pos(cls) -> Tuple[int, int]:
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)

    @classmethod
    def set_cursor_pos(cls, x: int, y: int) -> bool:
        return bool(user32.SetCursorPos(x, y))

    @classmethod
    def get_clip_cursor(cls) -> Tuple[int, int, int, int]:
        r = RECT()
        user32.GetClipCursor(ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    @classmethod
    def clip_cursor(cls, rect: Optional[Tuple[int, int, int, int]] = None) -> bool:
        if rect is None:
            return bool(user32.ClipCursor(None))
        r = RECT(rect[0], rect[1], rect[2], rect[3])
        return bool(user32.ClipCursor(ctypes.byref(r)))

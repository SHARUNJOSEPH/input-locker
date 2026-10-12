"""Hotkey parsing and binding system for Input Locker.

Supports parsing human-readable key combinations (e.g., 'F11', 'Ctrl+F12',
'Ctrl+Alt+Shift+U') into deterministic Virtual Key (VK) codes and modifier sets
for low-level Win32 hook evaluation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Collection, Dict, List, Optional, Set

try:
    import ctypes
    user32 = ctypes.windll.user32
except Exception:
    user32 = None

# Virtual Key Codes
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt

VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_LWIN = 0x5B
VK_RWIN = 0x5C

CTRL_KEYS = {VK_CONTROL, VK_LCONTROL, VK_RCONTROL}
ALT_KEYS = {VK_MENU, VK_LMENU, VK_RMENU}
SHIFT_KEYS = {VK_SHIFT, VK_LSHIFT, VK_RSHIFT}
WIN_KEYS = {VK_LWIN, VK_RWIN}

# Named Key Mapping to VK Code
_NAMED_KEYS: Dict[str, int] = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "CLEAR": 0x0C,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESCAPE": 0x1B,
    "ESC": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PGUP": 0x21,
    "PAGEDOWN": 0x22,
    "PGDN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PRINTSCREEN": 0x2C,
    "INSERT": 0x2D,
    "INS": 0x2D,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "SCROLLLOCK": 0x91,
}

# Add Function Keys F1 - F24
for i in range(1, 25):
    _NAMED_KEYS[f"F{i}"] = 0x6F + i

# Add 0-9
for i in range(10):
    _NAMED_KEYS[str(i)] = 0x30 + i

# Add A-Z
for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _NAMED_KEYS[c] = ord(c)


@dataclass(frozen=True)
class HotkeyBinding:
    """Represents a validated key combination.

    ``vk == 0`` means modifiers-only (e.g. Ctrl+Alt+Shift): match when all
    required modifiers are held and the trigger key is one of those modifiers.
    """
    vk: int
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    win: bool = False
    raw_str: str = ""

    @property
    def modifiers_only(self) -> bool:
        return self.vk == 0

    def matches(self, trigger_vk: int, active_keys: Set[int]) -> bool:
        """Check if incoming key and currently held keys satisfy this binding.

        Supports order-independent activation: triggers if trigger_vk is either the base
        key or any of the required modifier keys, provided all required keys are currently held
        in active_keys. Modifiers-only bindings (vk==0) fire on the last required modifier down.
        """
        combo_keys: Set[int] = set()
        if self.vk:
            combo_keys.add(self.vk)
        if self.ctrl:
            combo_keys.update(CTRL_KEYS)
        if self.alt:
            combo_keys.update(ALT_KEYS)
        if self.shift:
            combo_keys.update(SHIFT_KEYS)
        if self.win:
            combo_keys.update(WIN_KEYS)

        # The current event's key must belong to this combination
        if trigger_vk not in combo_keys:
            return False

        # Base key must be pressed (skip for modifiers-only bindings)
        if self.vk and trigger_vk != self.vk and self.vk not in active_keys:
            return False

        has_ctrl = bool(active_keys & CTRL_KEYS)
        has_alt = bool(active_keys & ALT_KEYS)
        has_shift = bool(active_keys & SHIFT_KEYS)
        has_win = bool(active_keys & WIN_KEYS)

        return (
            has_ctrl == self.ctrl
            and has_alt == self.alt
            and has_shift == self.shift
            and has_win == self.win
        )

    def format(self) -> str:
        """Return standardized human-readable string (e.g. 'Ctrl+Alt+Shift+U')."""
        parts = []
        if self.ctrl:
            parts.append("Ctrl")
        if self.alt:
            parts.append("Alt")
        if self.shift:
            parts.append("Shift")
        if self.win:
            parts.append("Win")

        if self.vk:
            key_name = None
            for name, code in _NAMED_KEYS.items():
                if code == self.vk and (name.startswith("F") or len(name) == 1):
                    key_name = name
                    break
            if not key_name:
                for name, code in _NAMED_KEYS.items():
                    if code == self.vk:
                        key_name = name
                        break
            parts.append(key_name or f"0x{self.vk:02X}")
        return "+".join(parts)


def parse_hotkey(hotkey_str: str) -> HotkeyBinding:
    """Parse a hotkey string into a validated HotkeyBinding.

    Examples:
        'F11' -> HotkeyBinding(vk=0x7A)
        'Ctrl+F12' -> HotkeyBinding(vk=0x7B, ctrl=True)
        'Ctrl + Alt + Shift + U' -> HotkeyBinding(vk=0x55, ctrl=True, alt=True, shift=True)
        'Ctrl+Alt+Shift' -> HotkeyBinding(vk=0, ctrl=True, alt=True, shift=True)  # modifiers-only

    Raises:
        ValueError: If string syntax is invalid or base key cannot be resolved.
    """
    if not hotkey_str or not hotkey_str.strip():
        raise ValueError("Hotkey string cannot be empty")

    raw_tokens = [t.strip().upper() for part in hotkey_str.replace("-", "+").split("+") for t in part.split() if t.strip()]
    tokens: List[str] = []
    for tok in raw_tokens:
        if tok not in ("CTRL", "CONTROL", "ALT", "MENU", "SHIFT", "WIN", "WINDOWS", "SUPER") and tok not in _NAMED_KEYS and not tok.startswith("0X"):
            matched_mod = False
            for mod_prefix in ("CONTROL", "WINDOWS", "SHIFT", "SUPER", "CTRL", "MENU", "ALT", "WIN"):
                if tok.startswith(mod_prefix):
                    rest = tok[len(mod_prefix):]
                    if rest in _NAMED_KEYS or rest.startswith("0X"):
                        tokens.append(mod_prefix)
                        tokens.append(rest)
                        matched_mod = True
                        break
            if not matched_mod:
                tokens.append(tok)
        else:
            tokens.append(tok)
    if not tokens:
        raise ValueError(f"No keys found in '{hotkey_str}'")

    ctrl = False
    alt = False
    shift = False
    win = False
    base_key_token: Optional[str] = None

    for t in tokens:
        if t in ("CTRL", "CONTROL"):
            ctrl = True
        elif t in ("ALT", "MENU"):
            alt = True
        elif t == "SHIFT":
            shift = True
        elif t in ("WIN", "WINDOWS", "SUPER"):
            win = True
        else:
            if base_key_token is not None:
                raise ValueError(
                    f"Multiple base keys specified in '{hotkey_str}' ('{base_key_token}' and '{t}')"
                )
            base_key_token = t

    if base_key_token is None:
        # Modifiers-only: require at least two modifiers to avoid accidental single-key unlocks
        modifier_count = sum((ctrl, alt, shift, win))
        if modifier_count < 2:
            raise ValueError(
                f"Modifiers-only hotkey '{hotkey_str}' needs at least two modifiers "
                "(e.g. Ctrl+Alt+Shift)"
            )
        vk = 0
    elif base_key_token not in _NAMED_KEYS:
        # Check if it's hex 0x..
        if base_key_token.startswith("0X"):
            try:
                vk = int(base_key_token, 16)
            except ValueError:
                raise ValueError(f"Unknown key '{base_key_token}' in '{hotkey_str}'")
        else:
            raise ValueError(f"Unknown key '{base_key_token}' in '{hotkey_str}'")
    else:
        vk = _NAMED_KEYS[base_key_token]

    return HotkeyBinding(
        vk=vk,
        ctrl=ctrl,
        alt=alt,
        shift=shift,
        win=win,
        raw_str=hotkey_str.strip(),
    )


# Standard Presets for Settings UI
LOCK_HOTKEY_PRESETS: List[str] = [
    "F11",
    "F9",
    "F10",
    "F12",
    "Ctrl+F11",
    "Ctrl+F12",
    "Ctrl+Alt+L",
]

UNLOCK_HOTKEY_PRESETS: List[str] = [
    "Ctrl+Alt+Shift",
    "Ctrl+Alt+Shift+U",
    "Ctrl+Alt+Shift+L",
    "Ctrl+Alt+Shift+K",
    "Ctrl+Alt+Shift+F12",
]

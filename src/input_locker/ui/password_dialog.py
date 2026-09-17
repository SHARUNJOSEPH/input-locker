"""Dark-themed, topmost password prompt dialog for the unlock sequence.

Creates an independent, guaranteed topmost window that displays above the
lock overlay. Forces immediate OS foreground keyboard focus and confines mouse.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import tkinter as tk
from typing import Callable, Optional

logger = logging.getLogger(__name__)

BG     = "#0F172A"
CARD   = "#1E293B"
BORDER = "#334155"
TEXT   = "#F1F5F9"
MUTED  = "#94A3B8"
ACCENT = "#0EA5E9"
AHOVER = "#38BDF8"


def _force_window_focus(hwnd: int) -> None:
    """Bypasses Windows foreground lock timeout to grant keyboard focus immediately."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Disable foreground lock timeout (SPI_SETFOREGROUNDLOCKTIMEOUT = 0x2001)
        user32.SystemParametersInfoW(0x2001, 0, None, 0)

        fg_hwnd = user32.GetForegroundWindow()
        cur_tid = kernel32.GetCurrentThreadId()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)

        if fg_tid != 0 and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.AttachThreadInput(cur_tid, fg_tid, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)

        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)
    except Exception as exc:
        logger.debug("Focus force exception: %s", exc)


def show_password_dialog(
    title: str = "Input Locker — Unlock",
    prompt: str = "Enter your unlock password:",
    expected_password: str = "",
    verify_fn: Optional[Callable[[str], bool]] = None,
    timeout: int = 60,
    on_ready: Optional[Callable[[int, int, int, int], None]] = None,
) -> Optional[str]:
    """Show a topmost modal password entry dialog and return the entered string."""
    result: dict = {"value": None}
    done = threading.Event()

    def _run() -> None:
        try:
            root = tk.Tk()
            root.withdraw()
            root.title(title)
            root.resizable(False, False)
            root.configure(bg=BG)

            # Center window on screen
            W, H = 420, 230
            sx = root.winfo_screenwidth()
            sy = root.winfo_screenheight()
            pos_x = (sx - W) // 2
            pos_y = (sy - H) // 2
            root.geometry(f"{W}x{H}+{pos_x}+{pos_y}")

            # Topmost
            root.attributes("-topmost", True)

            # Auto-timeout
            if timeout > 0:
                root.after(timeout * 1000, root.destroy)

            # Window icon & logo
            from input_locker.config import get_assets_dir
            assets_dir = get_assets_dir()
            ico_path = assets_dir / "app_icon.ico"
            if not ico_path.is_file():
                ico_path = assets_dir / "icon.ico"
            logo_path = assets_dir / "logo.png"

            if ico_path.is_file():
                try:
                    root.iconbitmap(str(ico_path))
                except Exception:
                    pass

            # Header
            hdr = tk.Frame(root, bg=BG)
            hdr.pack(fill="x", padx=24, pady=(20, 4))

            hdr_row = tk.Frame(hdr, bg=BG)
            hdr_row.pack(fill="x")

            _logo_ref = []
            if logo_path.is_file():
                try:
                    from PIL import Image, ImageTk
                    lim = Image.open(str(logo_path)).convert("RGBA").resize((38, 38), Image.LANCZOS)
                    lph = ImageTk.PhotoImage(lim)
                    _logo_ref.append(lph)
                    tk.Label(hdr_row, image=lph, bg=BG).pack(side="left", padx=(0, 10))
                except Exception:
                    pass

            text_col = tk.Frame(hdr_row, bg=BG)
            text_col.pack(side="left", fill="x", expand=True)
            tk.Label(
                text_col, text="Input Locker — Unlock", bg=BG, fg=TEXT,
                font=("Segoe UI", 13, "bold"),
            ).pack(anchor="w")
            tk.Label(
                text_col, text=prompt, bg=BG, fg=MUTED,
                font=("Segoe UI", 10),
            ).pack(anchor="w", pady=(1, 0))

            # Entry
            pw_frame = tk.Frame(root, bg=BG)
            pw_frame.pack(fill="x", padx=24, pady=12)

            pw_entry = tk.Entry(
                pw_frame, bg=CARD, fg=TEXT, insertbackground=TEXT,
                relief="flat", highlightthickness=1,
                highlightbackground=BORDER, highlightcolor=ACCENT,
                show="•", font=("Segoe UI", 12),
            )
            pw_entry.pack(fill="x", ipady=5)

            # Error label
            err_lbl = tk.Label(root, text="", bg=BG, fg="#EF4444", font=("Segoe UI", 9))
            err_lbl.pack(padx=24, anchor="w")

            def _submit(event=None):
                val = pw_entry.get()
                is_valid = True
                if verify_fn is not None:
                    is_valid = verify_fn(val)
                elif expected_password:
                    is_valid = (val == expected_password)

                if not is_valid:
                    err_lbl.config(text="⚠  Incorrect password. Please try again.")
                    pw_entry.delete(0, tk.END)
                    pw_entry.focus_set()
                    return
                result["value"] = val
                root.destroy()

            def _cancel(event=None):
                result["value"] = None
                root.destroy()

            pw_entry.bind("<Return>", _submit)
            pw_entry.bind("<Escape>", _cancel)

            # Buttons
            btn_row = tk.Frame(root, bg=BG)
            btn_row.pack(fill="x", padx=24, pady=(8, 16))

            cancel_btn = tk.Button(
                btn_row, text="Cancel", command=_cancel,
                bg=CARD, fg=TEXT, activebackground=BORDER, activeforeground=TEXT,
                relief="flat", padx=14, pady=6, font=("Segoe UI", 10),
                cursor="hand2",
            )
            cancel_btn.pack(side="left")

            unlock_btn = tk.Button(
                btn_row, text="  Unlock  ", command=_submit,
                bg=ACCENT, fg=TEXT, activebackground=AHOVER, activeforeground=TEXT,
                relief="flat", padx=16, pady=6, font=("Segoe UI", 10, "bold"),
                cursor="hand2",
            )
            unlock_btn.pack(side="right")

            root.protocol("WM_DELETE_WINDOW", _cancel)

            # Reveal and enforce focus
            root.update_idletasks()
            root.deiconify()
            root.lift()

            user32 = ctypes.windll.user32
            root_hwnd = user32.GetAncestor(root.winfo_id(), 2) or root.winfo_id()

            def _apply_focus():
                _force_window_focus(root_hwnd)
                pw_entry.focus_force()
                pw_entry.focus_set()

            _apply_focus()
            root.after(50, _apply_focus)
            root.after(150, _apply_focus)

            # Notify caller of dialog bounds so mouse can be confined to it
            if on_ready:
                try:
                    on_ready(pos_x, pos_y, W, H)
                except Exception as exc:
                    logger.debug("on_ready callback error: %s", exc)

            root.mainloop()
        except Exception as exc:
            logger.error("Password dialog error: %s", exc)
        finally:
            done.set()

    t = threading.Thread(target=_run, daemon=True, name="PasswordDialogThread")
    t.start()
    done.wait(timeout=timeout + 5)
    return result["value"]

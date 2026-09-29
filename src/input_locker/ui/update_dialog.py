"""Resolume-style In-App Software Update Dialog for Input Locker.

Provides an Apple/Resolume-inspired dark modal window with:
- Live version comparison badge (Current ➔ Available)
- Dynamic release highlights & changelog viewer
- Real-time in-app background download progress tracking (percent & transferred bytes)
- One-click 'Install & Restart' detached updater execution
- Microsoft Store container auto-detection & compliance messaging
"""
from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
import webbrowser
from typing import Any, Dict, List, Optional

from input_locker import __version__
from input_locker.core.i18n import t
from input_locker.updater import (
    check_for_updates_async,
    download_update_async,
    get_effective_version,
    install_update_and_restart,
    is_newer_version,
    is_windows_store,
)

logger = logging.getLogger(__name__)

# Dark theme palette matching Input Locker & PDF Presenter
BG_MODAL       = "#0B0F19"
HEADER_BG      = "#121A2D"
CARD_BG        = "#141C2E"
CARD_BORDER    = "#233047"
TEXT_PRIMARY   = "#F8FAFC"
TEXT_MUTED     = "#94A3B8"
TEXT_SUBTLE    = "#64748B"
ACCENT_BLUE    = "#0284C7"
ACCENT_HOVER   = "#0369A1"
PRIMARY_PURPLE = "#6366F1"
EMERALD_GREEN  = "#10B981"
EMERALD_TEXT   = "#34D399"
PROGRESS_BG    = "#1E293B"
PROGRESS_FILL  = "#38BDF8"
PROGRESS_DONE  = "#10B981"
DANGER_TEXT    = "#F87171"


class SoftwareUpdateDialog:
    """Resolume-style dedicated modal update dialog for Input Locker."""

    def __init__(
        self,
        parent: Optional[tk.Misc] = None,
        update_info: Optional[Dict[str, Any]] = None,
        auto_check: bool = False,
        repo_or_url: str = "",
    ) -> None:
        self.parent = parent
        self.repo_or_url = repo_or_url
        self.update_info = update_info
        self.current_version = get_effective_version()
        self.latest_version = (update_info.get("latest_version") or self.current_version) if update_info else self.current_version
        self.downloaded_path: Optional[str] = None
        self.is_downloading = False
        self._cancel_event = None

        # Build Toplevel window
        self.top = tk.Toplevel(parent) if parent else tk.Tk()
        self.top.title("Input Locker — Software Update")
        self.top.configure(bg=BG_MODAL)
        self.top.resizable(False, False)
        if parent:
            self.top.transient(parent)
            self.top.grab_set()

        self._build_ui()
        self._center_window(520, 560)

        if auto_check and not self.update_info:
            self._start_update_check()
        elif self.update_info:
            self._render_update_state()

    def _center_window(self, width: int, height: int) -> None:
        self.top.update_idletasks()
        if self.parent:
            x = self.parent.winfo_x() + (self.parent.winfo_width() - width) // 2
            y = self.parent.winfo_y() + (self.parent.winfo_height() - height) // 2
        else:
            x = (self.top.winfo_screenwidth() - width) // 2
            y = (self.top.winfo_screenheight() - height) // 2
        self.top.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
        self.top.lift()
        self.top.attributes("-topmost", True)
        self.top.after(200, lambda: self.top.attributes("-topmost", False) if self.top.winfo_exists() else None)

    def _build_ui(self) -> None:
        # ── 1. Header Bar ─────────────────────────────────────────────────────
        header_frame = tk.Frame(self.top, bg=HEADER_BG, bd=0, highlightthickness=0)
        header_frame.pack(fill="x", side="top")

        hdr_inner = tk.Frame(header_frame, bg=HEADER_BG)
        hdr_inner.pack(fill="x", padx=18, pady=14)

        title_box = tk.Frame(hdr_inner, bg=HEADER_BG)
        title_box.pack(side="left")

        tk.Label(
            title_box, text="🚀", font=("Segoe UI Emoji", 16),
            bg=HEADER_BG, fg=TEXT_PRIMARY,
        ).pack(side="left", padx=(0, 10))

        tk.Label(
            title_box, text="Input Locker Update",
            font=("Segoe UI", 13, "bold"), bg=HEADER_BG, fg=TEXT_PRIMARY,
        ).pack(side="left")

        close_btn = tk.Button(
            hdr_inner, text="✕", font=("Segoe UI", 11),
            bg=HEADER_BG, fg=TEXT_MUTED, activebackground=HEADER_BG, activeforeground=TEXT_PRIMARY,
            relief="flat", bd=0, cursor="hand2", command=self._on_close,
        )
        close_btn.pack(side="right")

        # Subtle separator
        sep = tk.Frame(self.top, bg=CARD_BORDER, height=1)
        sep.pack(fill="x")

        # ── 2. Content Body ───────────────────────────────────────────────────
        self.content_frame = tk.Frame(self.top, bg=BG_MODAL)
        self.content_frame.pack(fill="both", expand=True, padx=22, pady=(16, 12))

        # Version Comparison Pill
        self.pill_frame = tk.Frame(
            self.content_frame, bg=CARD_BG, bd=1, relief="solid",
            highlightthickness=1, highlightbackground=CARD_BORDER,
        )
        self.pill_frame.pack(fill="x", pady=(0, 14))

        pill_inner = tk.Frame(self.pill_frame, bg=CARD_BG)
        pill_inner.pack(fill="x", padx=16, pady=12)

        # Current Version Box
        cur_box = tk.Frame(pill_inner, bg=CARD_BG)
        cur_box.pack(side="left", expand=True)
        tk.Label(
            cur_box, text="CURRENT VERSION", font=("Segoe UI", 8, "bold"),
            bg=CARD_BG, fg=TEXT_MUTED,
        ).pack()
        self.lbl_cur_ver = tk.Label(
            cur_box, text=f"v{self.current_version}", font=("Segoe UI", 13, "bold"),
            bg=CARD_BG, fg=TEXT_PRIMARY,
        )
        self.lbl_cur_ver.pack(pady=(2, 0))

        # Arrow
        tk.Label(
            pill_inner, text="➔", font=("Segoe UI", 15, "bold"),
            bg=CARD_BG, fg=PRIMARY_PURPLE,
        ).pack(side="left", padx=12)

        # Available Version Box
        new_box = tk.Frame(pill_inner, bg=CARD_BG)
        new_box.pack(side="right", expand=True)
        self.lbl_new_title = tk.Label(
            new_box, text="AVAILABLE UPDATE", font=("Segoe UI", 8, "bold"),
            bg=CARD_BG, fg=EMERALD_TEXT,
        )
        self.lbl_new_title.pack()
        self.lbl_new_ver = tk.Label(
            new_box, text=f"v{self.latest_version}", font=("Segoe UI", 13, "bold"),
            bg=CARD_BG, fg=EMERALD_TEXT,
        )
        self.lbl_new_ver.pack(pady=(2, 0))

        # Subtitle / Pitch Summary
        self.lbl_summary = tk.Label(
            self.content_frame,
            text="Checking for available updates...",
            font=("Segoe UI", 9), bg=BG_MODAL, fg=TEXT_MUTED,
            wraplength=470, justify="center",
        )
        self.lbl_summary.pack(pady=(0, 12))

        # ── 3. Highlights & Changelog Box ────────────────────────────────────
        self.highlights_card = tk.Frame(
            self.content_frame, bg="#0F172A", bd=1, relief="solid",
            highlightthickness=1, highlightbackground=CARD_BORDER,
        )
        self.highlights_card.pack(fill="x", pady=(0, 14), ipadx=10, ipady=8)

        hl_header = tk.Frame(self.highlights_card, bg="#0F172A")
        hl_header.pack(fill="x", padx=10, pady=(4, 6))

        tk.Label(
            hl_header, text="✨  WHAT'S NEW IN THIS RELEASE:",
            font=("Segoe UI", 8, "bold"), bg="#0F172A", fg="#818CF8",
        ).pack(anchor="w")

        self.hl_list_frame = tk.Frame(self.highlights_card, bg="#0F172A")
        self.hl_list_frame.pack(fill="x", padx=14, pady=(0, 4))

        # ── 4. Download Progress Section (Revealed on Download) ───────────────
        self.progress_card = tk.Frame(
            self.content_frame, bg=CARD_BG, bd=1, relief="solid",
            highlightthickness=1, highlightbackground="#0284C7",
        )
        # hidden until download starts

        prog_inner = tk.Frame(self.progress_card, bg=CARD_BG)
        prog_inner.pack(fill="x", padx=12, pady=10)

        prog_hdr = tk.Frame(prog_inner, bg=CARD_BG)
        prog_hdr.pack(fill="x", pady=(0, 6))

        self.lbl_prog_status = tk.Label(
            prog_hdr, text="Downloading update in background...",
            font=("Segoe UI", 9, "bold"), bg=CARD_BG, fg="#38BDF8",
        )
        self.lbl_prog_status.pack(side="left")

        self.lbl_prog_pct = tk.Label(
            prog_hdr, text="0%",
            font=("Consolas", 10, "bold"), bg=CARD_BG, fg=TEXT_PRIMARY,
        )
        self.lbl_prog_pct.pack(side="right")

        # Smooth Canvas Progress Bar
        self.bar_canvas = tk.Canvas(
            prog_inner, bg=PROGRESS_BG, height=8, bd=0, highlightthickness=0,
        )
        self.bar_canvas.pack(fill="x", pady=(0, 6))
        self.bar_fill = self.bar_canvas.create_rectangle(0, 0, 0, 8, fill=PROGRESS_FILL, width=0)

        self.lbl_prog_bytes = tk.Label(
            prog_inner, text="Connecting...",
            font=("Segoe UI", 8), bg=CARD_BG, fg=TEXT_MUTED,
        )
        self.lbl_prog_bytes.pack(anchor="w")

        # ── 5. Action Buttons Footer ──────────────────────────────────────────
        footer_sep = tk.Frame(self.top, bg=CARD_BORDER, height=1)
        footer_sep.pack(fill="x", side="bottom")

        btn_row = tk.Frame(self.top, bg=BG_MODAL)
        btn_row.pack(fill="x", side="bottom", padx=22, pady=14)

        self.btn_dismiss = tk.Button(
            btn_row, text="Close", font=("Segoe UI", 9),
            bg="#1E293B", fg=TEXT_PRIMARY, activebackground="#334155", activeforeground=TEXT_PRIMARY,
            relief="flat", bd=0, padx=14, pady=6, cursor="hand2", command=self._on_close,
        )
        self.btn_dismiss.pack(side="right", padx=(8, 0))

        self.btn_download = tk.Button(
            btn_row, text="⬇️ Download Update", font=("Segoe UI", 9, "bold"),
            bg=ACCENT_BLUE, fg="#FFFFFF", activebackground=ACCENT_HOVER, activeforeground="#FFFFFF",
            relief="flat", bd=0, padx=16, pady=6, cursor="hand2", command=self._on_download_click,
        )
        self.btn_download.pack(side="right", padx=(8, 0))

        self.btn_install = tk.Button(
            btn_row, text="⚡ Install & Restart", font=("Segoe UI", 9, "bold"),
            bg="#059669", fg="#FFFFFF", activebackground=EMERALD_GREEN, activeforeground="#FFFFFF",
            relief="flat", bd=0, padx=16, pady=6, cursor="hand2", command=self._on_install_click,
        )
        # hidden until downloaded

        self.btn_open_browser = tk.Button(
            btn_row, text="🌐 Releases Page", font=("Segoe UI", 8),
            bg="#141C2E", fg=TEXT_MUTED, activebackground="#1E293B", activeforeground=TEXT_PRIMARY,
            relief="flat", bd=1, padx=10, pady=5, cursor="hand2",
            command=self._on_open_browser,
        )
        self.btn_open_browser.pack(side="left")

    def _start_update_check(self) -> None:
        self.lbl_summary.config(text="Contacting update server for the latest release...")
        self.btn_download.config(text="Checking...", state="disabled")
        self.btn_dismiss.config(text="Cancel")

        def _on_check_done(info: Optional[Dict[str, Any]]) -> None:
            def _apply():
                self.btn_download.config(state="normal")
                self.update_info = info
                self._render_update_state()
            if self.top.winfo_exists():
                self.top.after(0, _apply)

        check_for_updates_async(callback=_on_check_done, repo_or_url=self.repo_or_url)

    def _render_update_state(self) -> None:
        info = self.update_info
        if not info:
            self.lbl_summary.config(text="Could not reach update server. Please check your internet connection.", fg=DANGER_TEXT)
            self.btn_download.config(text="🔄 Retry Check", command=self._start_update_check)
            self.btn_dismiss.config(text="Close")
            return

        is_store = info.get("is_store", False) or is_windows_store()
        has_update = info.get("has_update", False)
        latest_ver = info.get("latest_version") or self.current_version
        clean_latest = latest_ver.lstrip("v")
        clean_cur = self.current_version.lstrip("v")

        self.lbl_cur_ver.config(text=f"v{self.current_version}")
        self.lbl_new_ver.config(text=f"v{clean_latest}")

        # Populate Highlights Box
        for w in self.hl_list_frame.winfo_children():
            w.destroy()

        highlights = info.get("highlights") or [
            "Order-independent hotkey matching across all modifiers.",
            "Visual unlock instruction banner on lock screen overlay.",
            "Emergency 4x Escape rapid failsafe unlock.",
            "Real-time low-latency AV staging performance improvements."
        ]

        for item in highlights:
            bullet_row = tk.Frame(self.hl_list_frame, bg="#0F172A")
            bullet_row.pack(fill="x", pady=2)
            tk.Label(
                bullet_row, text="•", font=("Segoe UI", 10, "bold"),
                bg="#0F172A", fg=PRIMARY_PURPLE,
            ).pack(side="left", anchor="n", padx=(0, 6))
            tk.Label(
                bullet_row, text=item, font=("Segoe UI", 8),
                bg="#0F172A", fg=TEXT_PRIMARY, wraplength=430, justify="left",
            ).pack(side="left", fill="x", expand=True)

        if is_store:
            self.lbl_new_title.config(text="STORE EDITION", fg=EMERALD_TEXT)
            self.lbl_new_ver.config(text="Managed", fg=EMERALD_TEXT)
            self.lbl_summary.config(
                text="✓ You are using the verified Microsoft Store edition.\nUpdates install automatically in the background.",
                fg=EMERALD_TEXT,
            )
            self.btn_download.pack_forget()
            self.btn_dismiss.config(text="Close")
            return

        if has_update:
            self.lbl_new_title.config(text="AVAILABLE UPDATE", fg=EMERALD_TEXT)
            self.lbl_new_ver.config(text=f"v{clean_latest}", fg=EMERALD_TEXT)
            self.lbl_summary.config(
                text=f"🎉 A new version of Input Locker (v{clean_latest}) is available!\nUpgrade now for latest features and stability improvements.",
                fg=TEXT_PRIMARY,
            )
            self.btn_download.config(text="⬇️ Download Update", command=self._on_download_click)
            self.btn_dismiss.config(text="Remind Me Later")
        else:
            # Current version is latest or higher preview build
            is_ahead = is_newer_version(self.current_version, clean_latest)
            if is_ahead:
                self.lbl_new_title.config(text="LATEST RELEASE", fg=TEXT_MUTED)
                self.lbl_new_ver.config(text=f"v{clean_latest}", fg=TEXT_MUTED)
                self.lbl_summary.config(
                    text=f"✓ You are running a newer preview build (v{self.current_version}).\nLatest public release is v{clean_latest}.",
                    fg=EMERALD_TEXT,
                )
            else:
                self.lbl_new_title.config(text="UP TO DATE", fg=EMERALD_TEXT)
                self.lbl_new_ver.config(text=f"v{self.current_version}", fg=EMERALD_TEXT)
                self.lbl_summary.config(
                    text=f"✓ You are already running the latest version (v{self.current_version}).\nNo update is needed!",
                    fg=EMERALD_TEXT,
                )

            self.btn_download.pack_forget()
            self.btn_dismiss.config(text="Close")

    def _on_download_click(self) -> None:
        if self.is_downloading or not self.update_info:
            return

        download_url = self.update_info.get("direct_download_url") or self.update_info.get("release_url")
        if not download_url:
            # Fallback to browser if no direct download asset
            webbrowser.open(self.update_info.get("html_url") or self.update_info.get("release_url"))
            return

        self.is_downloading = True
        self.btn_download.config(text="Downloading...", state="disabled")
        self.btn_dismiss.config(text="Cancel", command=self._cancel_download)

        # Show Progress Section
        self.progress_card.pack(fill="x", pady=(0, 14), before=self.highlights_card)
        self.lbl_prog_status.config(text="Connecting to update server...", fg="#38BDF8")
        self.lbl_prog_pct.config(text="0%")
        self.lbl_prog_bytes.config(text="Initializing download stream...")

        def _on_progress(p: Dict[str, Any]) -> None:
            def _ui():
                pct = p.get("percent", 0)
                rx_mb = f"{p.get('received_bytes', 0) / (1024 * 1024):.1f}"
                tot_mb = f"{p.get('total_bytes', 0) / (1024 * 1024):.1f}" if p.get("total_bytes", 0) > 0 else "?"
                self.lbl_prog_pct.config(text=f"{pct}%")
                self.lbl_prog_bytes.config(text=f"{rx_mb} MB / {tot_mb} MB")

                canvas_w = self.bar_canvas.winfo_width() or 460
                fill_w = int(canvas_w * (pct / 100.0))
                self.bar_canvas.coords(self.bar_fill, 0, 0, fill_w, 8)

                if pct >= 99:
                    self.lbl_prog_status.config(text="Verifying update package...", fg="#38BDF8")
                else:
                    self.lbl_prog_status.config(text="Downloading update in background...", fg="#38BDF8")

            if self.top.winfo_exists():
                self.top.after(0, _ui)

        def _on_complete(file_path: str) -> None:
            def _ui():
                self.is_downloading = False
                self.downloaded_path = file_path
                self.lbl_prog_pct.config(text="100%")
                canvas_w = self.bar_canvas.winfo_width() or 460
                self.bar_canvas.coords(self.bar_fill, 0, 0, canvas_w, 8)
                self.bar_canvas.itemconfig(self.bar_fill, fill=PROGRESS_DONE)

                self.lbl_prog_status.config(text="✓ Update downloaded successfully!", fg=EMERALD_TEXT)
                self.lbl_summary.config(text="✓ Update package ready to install! Click 'Install & Restart' to apply now.", fg=EMERALD_TEXT)

                self.btn_download.pack_forget()
                self.btn_install.pack(side="right", padx=(8, 0))
                self.btn_dismiss.config(text="Install Later", command=self._on_close)

            if self.top.winfo_exists():
                self.top.after(0, _ui)

        def _on_error(err_msg: str) -> None:
            def _ui():
                self.is_downloading = False
                self.lbl_prog_status.config(text=f"Download failed: {err_msg}", fg=DANGER_TEXT)
                self.lbl_prog_bytes.config(text="Please check internet connection or download manually.")
                self.btn_download.config(text="🔄 Retry Download", state="normal", command=self._on_download_click)
                self.btn_dismiss.config(text="Close", command=self._on_close)

            if self.top.winfo_exists():
                self.top.after(0, _ui)

        import threading
        self._cancel_event = threading.Event()
        download_update_async(
            download_url=download_url,
            on_progress=_on_progress,
            on_complete=_on_complete,
            on_error=_on_error,
            cancel_event=self._cancel_event,
        )

    def _cancel_download(self) -> None:
        if self._cancel_event:
            self._cancel_event.set()
        self.is_downloading = False
        self.progress_card.pack_forget()
        self.btn_download.config(text="⬇️ Download Update", state="normal", command=self._on_download_click)
        self.btn_dismiss.config(text="Remind Me Later", command=self._on_close)

    def _on_install_click(self) -> None:
        if not self.downloaded_path:
            return
        self.btn_install.config(text="⚡ Launching Installer...", state="disabled")
        self.lbl_prog_status.config(text="Launching installer... Input Locker will restart automatically.")
        install_update_and_restart(self.downloaded_path)

    def _on_open_browser(self) -> None:
        url = (
            (self.update_info and self.update_info.get("html_url"))
            or (self.update_info and self.update_info.get("release_url"))
            or "https://github.com/SHARUNJOSEPH/input-locker/releases"
        )
        webbrowser.open(url)

    def _on_close(self) -> None:
        if self.is_downloading:
            self._cancel_download()
        if self.parent:
            self.top.grab_release()
        self.top.destroy()


def show_software_update_dialog(
    parent: Optional[tk.Misc] = None,
    update_info: Optional[Dict[str, Any]] = None,
    auto_check: bool = False,
    repo_or_url: str = "",
) -> SoftwareUpdateDialog:
    """Convenience helper to instantiate and display the software update modal."""
    return SoftwareUpdateDialog(
        parent=parent,
        update_info=update_info,
        auto_check=auto_check,
        repo_or_url=repo_or_url,
    )

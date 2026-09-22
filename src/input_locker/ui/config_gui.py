"""Apple-inspired dark-themed settings dialog and About modal for Input Locker.

Uses tkinter (no PyQt6 dependency) to avoid QApplication threading conflicts
with the background overlay. Pillow provides thumbnails and anti-aliased avatars.
"""
from __future__ import annotations

import logging
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional, Tuple

from input_locker import __version__
from input_locker.config import LockerConfig, get_assets_dir, get_config_path
from input_locker.core.i18n import SUPPORTED_LANGUAGES, set_locale, t
from input_locker.hooks.hotkey import parse_hotkey
from input_locker.updater import check_for_updates_async

logger = logging.getLogger(__name__)

# ── Apple-inspired Dark Palette ──────────────────────────────────────────────
BG             = "#0B0F19"   # macOS / iOS deep dark canvas
CARD_BG        = "#141C2E"   # Inset grouped card surface
CARD_BORDER    = "#233047"   # Grouped card border
CARD_HEADER    = "#64748B"   # Uppercase section title
INPUT_BG       = "#0D1322"   # Inset input field background
INPUT_BORDER   = "#27374F"   # Inset input field border
INPUT_FOCUS    = "#0A84FF"   # Apple vibrant blue focus ring
TEXT_PRIMARY   = "#F8FAFC"   # Primary text (crisp white)
TEXT_MUTED     = "#94A3B8"   # Secondary / subtitle text
TEXT_SUBTLE    = "#64748B"   # Tertiary hints

# Buttons & Badges
ACCENT_BLUE    = "#0A84FF"   # Apple primary action blue
ACCENT_HOVER   = "#0071E3"   # Hover state for primary blue
ACCENT_ACTIVE  = "#005BB5"   # Active/pressed state

BTN_SEC_BG     = "#1E293B"   # Secondary button background
BTN_SEC_BD     = "#334155"   # Secondary button border
BTN_SEC_HOVER  = "#27354F"   # Secondary button hover

DANGER_BG      = "#38191E"   # Remove / clear button background
DANGER_BD      = "#5C262C"   # Remove button border
DANGER_TEXT    = "#F87171"   # Remove button text
DANGER_HOVER   = "#4D1D23"   # Remove button hover

SUCCESS_BG     = "#064E3B"   # Password protected badge background
SUCCESS_BD     = "#059669"   # Password protected badge border
SUCCESS_TEXT   = "#34D399"   # Password protected badge text

BANNER_BG      = "#1E3A8A"   # Update banner background
BANNER_BD      = "#3B82F6"   # Update banner border

CREATOR_LINKEDIN = "https://www.linkedin.com/in/joseph-sharun/"
CREATOR_GITHUB   = "https://github.com/SHARUNJOSEPH"
APP_GITHUB       = "https://github.com/SHARUNJOSEPH/input-locker"
APP_RELEASES     = "https://github.com/SHARUNJOSEPH/input-locker/releases"
APP_ISSUES       = "https://github.com/SHARUNJOSEPH/input-locker/issues"


def _make_avatar_image(size: int = 44, master: Optional[tk.Misc] = None) -> "Optional[tk.PhotoImage]":
    """Generate a crisp circular gradient avatar with initials 'JS' using Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageTk
        scale = 4
        s = size * scale
        img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Gradient: indigo #6366F1 (99, 102, 241) to cyan #06B6D4 (6, 182, 212)
        for y in range(s):
            t = y / s
            r = int(99 * (1 - t) + 6 * t)
            g = int(102 * (1 - t) + 182 * t)
            b = int(241 * (1 - t) + 212 * t)
            draw.line([(0, y), (s, y)], fill=(r, g, b, 255))

        # Circular mask
        mask = Image.new("L", (s, s), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, s, s), fill=255)

        # Draw "JS" text
        font = None
        font_size = int(17 * scale)
        for font_name in ("segoeuib.ttf", "arialbd.ttf", "segoeui.ttf", "arial.ttf"):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), "JS", font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = (s - tw) // 2 - bbox[0]
        ty = (s - th) // 2 - bbox[1]
        draw.text((tx, ty), "JS", fill=(255, 255, 255, 255), font=font)

        out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        out.paste(img, (0, 0), mask)
        out = out.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(out, master=master)
    except Exception as exc:
        logger.debug("Failed to generate avatar image: %s", exc)
        return None


def _make_thumbnail(path: str, w: int = 470, h: int = 100, master: Optional[tk.Misc] = None):
    """Return a PhotoImage thumbnail with subtle lock emblem, or None on failure."""
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert("RGB")
        ratio = max(w / img.width, h / img.height)
        nw, nh = int(img.width * ratio), int(img.height * ratio)
        img = img.resize((nw, nh), Image.LANCZOS)
        x, y = (nw - w) // 2, (nh - h) // 2
        img = img.crop((x, y, x + w, y + h))

        # Add subtle dark vignette/scrim overlay
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 60))
        img = Image.alpha_composite(img.convert("RGBA"), overlay)
        return ImageTk.PhotoImage(img, master=master)
    except Exception:
        return None


def show_about_dialog(parent: Optional[tk.Tk | tk.Toplevel] = None) -> None:
    """Show the Apple-inspired About modal matching the creator portfolio."""
    top = tk.Toplevel(parent)
    top.title(t("about_title"))
    top.resizable(False, False)
    top.configure(bg=BG)
    top.transient(parent)
    top.grab_set()

    _refs: list = []

    # Icon
    assets_dir = get_assets_dir()
    ico_path = assets_dir / "app_icon.ico"
    if not ico_path.is_file():
        ico_path = assets_dir / "icon.ico"
    logo_path = assets_dir / "logo.png"
    if ico_path.is_file():
        try:
            top.iconbitmap(str(ico_path))
        except Exception:
            pass

    if logo_path.is_file():
        try:
            from PIL import Image, ImageTk
            _about_ico = ImageTk.PhotoImage(Image.open(str(logo_path)).convert("RGBA"), master=top)
            _refs.append(_about_ico)
            top.wm_iconphoto(True, _about_ico)
        except Exception:
            pass

    # Scrollable content frame
    outer = tk.Frame(top, bg=BG)
    outer.pack(fill="both", expand=True)

    canvas_scroll = tk.Canvas(outer, bg=BG, bd=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas_scroll.yview)
    canvas_scroll.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas_scroll.pack(side="left", fill="both", expand=True)

    content = tk.Frame(canvas_scroll, bg=BG)
    content_window = canvas_scroll.create_window((0, 0), window=content, anchor="nw")

    def _on_content_configure(e):
        canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))
        canvas_scroll.itemconfig(content_window, width=canvas_scroll.winfo_width())

    def _on_canvas_configure(e):
        canvas_scroll.itemconfig(content_window, width=e.width)

    content.bind("<Configure>", _on_content_configure)
    canvas_scroll.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(e):
        canvas_scroll.yview_scroll(int(-1 * (e.delta / 120)), "units")

    canvas_scroll.bind_all("<MouseWheel>", _on_mousewheel)
    top.bind("<Destroy>", lambda e: canvas_scroll.unbind_all("<MouseWheel>"))

    # Padding frame
    pad = tk.Frame(content, bg=BG)
    pad.pack(fill="both", expand=True, padx=26, pady=22)

    # ── Top App Identity ──────────────────────────────────────────────────
    if logo_path.is_file():
        try:
            from PIL import Image, ImageTk
            lim = Image.open(str(logo_path)).convert("RGBA").resize((56, 56), Image.LANCZOS)
            lph = ImageTk.PhotoImage(lim, master=top)
            _refs.append(lph)
            tk.Label(pad, image=lph, bg=BG).pack(pady=(0, 6))
        except Exception:
            tk.Label(pad, text="🔒", font=("Segoe UI Emoji", 36), bg=BG, fg=TEXT_PRIMARY).pack(pady=(0, 6))
    else:
        tk.Label(pad, text="🔒", font=("Segoe UI Emoji", 36), bg=BG, fg=TEXT_PRIMARY).pack(pady=(0, 6))

    tk.Label(
        pad, text="Input Locker",
        bg=BG, fg=TEXT_PRIMARY,
        font=("Segoe UI", 20, "bold"),
    ).pack(pady=(0, 4))

    tk.Label(
        pad, text=t("app_tagline"),
        bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 10),
    ).pack(pady=(0, 8))

    # Badges row
    badge_row = tk.Frame(pad, bg=BG)
    badge_row.pack(pady=(0, 10))

    for text, bg_c, fg_c in [
        (t("version_tag", version=__version__), "#1E1B4B", "#818CF8"),
        (t("open_source"),                     SUCCESS_BG, SUCCESS_TEXT),
        (t("mit_license"),                     "#0C4A6E",  "#38BDF8"),
        (t("windows_tag"),                     "#1C3553",  "#93C5FD"),
    ]:
        tk.Label(
            badge_row, text=text,
            bg=bg_c, fg=fg_c, font=("Segoe UI", 8, "bold"),
            padx=8, pady=3, bd=1, relief="solid",
        ).pack(side="left", padx=3)

    # Description
    desc_txt = t("app_desc")
    tk.Label(
        pad, text=desc_txt,
        bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
        wraplength=430, justify="center",
    ).pack(pady=(0, 16))

    # ── App Repository Links ──────────────────────────────────────────────
    repo_card = tk.Frame(
        pad, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    repo_card.pack(fill="x", pady=(0, 12), ipady=6, ipadx=10)

    tk.Label(
        repo_card, text=t("about_project_repo"),
        bg=CARD_BG, fg=CARD_HEADER, font=("Segoe UI", 8, "bold"),
    ).pack(anchor="w", padx=12, pady=(6, 6))

    repo_btn_row = tk.Frame(repo_card, bg=CARD_BG)
    repo_btn_row.pack(fill="x", padx=12, pady=(0, 8))

    def _link_btn(parent, text, url, bg_col="#21262D", fg_col="#FFFFFF", ab_col="#30363D"):
        return tk.Button(
            parent, text=text, command=lambda: webbrowser.open(url),
            bg=bg_col, fg=fg_col, activebackground=ab_col, activeforeground="#FFFFFF",
            relief="flat", bd=1, padx=10, pady=5, font=("Segoe UI", 9, "bold"), cursor="hand2",
        )

    _link_btn(repo_btn_row, "⭐  GitHub Repo",    APP_GITHUB,   "#21262D", "#FFFFFF", "#30363D").pack(side="left", padx=(0, 6))
    _link_btn(repo_btn_row, "📦  Releases",       APP_RELEASES, "#0C4A6E", "#BAE6FD", "#075985").pack(side="left", padx=(0, 6))
    _link_btn(repo_btn_row, "🐛  Report an Issue",APP_ISSUES,   DANGER_BG, DANGER_TEXT, DANGER_HOVER).pack(side="left")

    # ── Created & Maintained By Card ──────────────────────────────────────
    creator_card = tk.Frame(
        pad, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    creator_card.pack(fill="x", pady=(0, 12), ipady=8, ipadx=10)

    tk.Label(
        creator_card, text=t("about_created_by"),
        bg=CARD_BG, fg=CARD_HEADER, font=("Segoe UI", 8, "bold"),
    ).pack(anchor="w", padx=12, pady=(6, 8))

    cr_row = tk.Frame(creator_card, bg=CARD_BG)
    cr_row.pack(fill="x", padx=12, pady=(0, 6))

    av_ph = _make_avatar_image(44, master=top)
    if av_ph:
        _refs.append(av_ph)
        tk.Label(cr_row, image=av_ph, bg=CARD_BG).pack(side="left", padx=(0, 10))
    else:
        tk.Label(cr_row, text="JS", bg="#6366F1", fg="#FFFFFF", font=("Segoe UI", 12, "bold"),
                 width=3, height=1, relief="flat").pack(side="left", padx=(0, 10))

    det_f = tk.Frame(cr_row, bg=CARD_BG)
    det_f.pack(side="left", fill="both", expand=True)
    tk.Label(det_f, text="Joseph Sharun", bg=CARD_BG, fg=TEXT_PRIMARY,
             font=("Segoe UI", 12, "bold")).pack(anchor="w")
    tk.Label(det_f, text="Software Engineer & AV Tech Creator", bg=CARD_BG, fg=TEXT_MUTED,
             font=("Segoe UI", 9)).pack(anchor="w", pady=(1, 0))
    tk.Label(det_f, text="Chennai, India  🇮🇳", bg=CARD_BG, fg=TEXT_SUBTLE,
             font=("Segoe UI", 8)).pack(anchor="w", pady=(2, 0))

    btn_links = tk.Frame(cr_row, bg=CARD_BG)
    btn_links.pack(side="right", padx=(8, 0))
    _link_btn(btn_links, "🔗 LinkedIn", CREATOR_LINKEDIN, "#0A66C2", "#FFFFFF", "#084E96").pack(side="left", padx=3)
    _link_btn(btn_links, "🐙 GitHub",  CREATOR_GITHUB,   "#21262D", "#FFFFFF", "#30363D").pack(side="left", padx=3)

    # ── Version & Updates Row ─────────────────────────────────────────────
    up_card = tk.Frame(
        pad, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    up_card.pack(fill="x", pady=(0, 12), ipady=8, ipadx=10)

    up_row = tk.Frame(up_card, bg=CARD_BG)
    up_row.pack(fill="x", padx=12)

    up_info = tk.Frame(up_row, bg=CARD_BG)
    up_info.pack(side="left", fill="both", expand=True)
    tk.Label(
        up_info, text=t("about_updates_title"),
        bg=CARD_BG, fg=TEXT_PRIMARY, font=("Segoe UI", 10, "bold"),
    ).pack(anchor="w")
    up_sub = tk.Label(
        up_info, text=t("about_current_build", version=__version__),
        bg=CARD_BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
    )
    up_sub.pack(anchor="w", pady=(2, 0))

    def _check_modal():
        up_btn.config(text=t("btn_checking"), state="disabled")
        def _cb(info):
            def _ui():
                up_btn.config(text=t("btn_check_updates"), state="normal")
                if info and info.get("available"):
                    up_sub.config(text=t("about_update_avail", version=info.get('latest_version')), fg="#38BDF8")
                    if messagebox.askyesno(
                        "Update Available",
                        f"Input Locker {info.get('latest_version')} is available.\n\nOpen release download page?",
                        parent=top,
                    ):
                        webbrowser.open(info.get("release_url", APP_RELEASES))
                else:
                    up_sub.config(text=f"v{__version__} — {t('about_up_to_date', version=__version__)}", fg=SUCCESS_TEXT)
                    messagebox.showinfo("Up to Date", t("about_up_to_date", version=__version__), parent=top)
            if top.winfo_exists():
                top.after(0, _ui)
        check_for_updates_async(callback=_cb)

    up_btn = tk.Button(
        up_row, text=t("btn_check_updates"), command=_check_modal,
        bg="#312E81", fg="#C7D2FE", activebackground="#3730A3", activeforeground="#FFFFFF",
        relief="flat", bd=1, padx=10, pady=4, font=("Segoe UI", 9, "bold"), cursor="hand2",
    )
    up_btn.pack(side="right")

    # ── What's New / Changelog ────────────────────────────────────────────
    cl_card = tk.Frame(
        pad, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    cl_card.pack(fill="x", pady=(0, 12), ipady=6, ipadx=10)

    tk.Label(
        cl_card, text=t("about_whats_new"),
        bg=CARD_BG, fg=CARD_HEADER, font=("Segoe UI", 8, "bold"),
    ).pack(anchor="w", padx=12, pady=(6, 4))

    for icon, headline in [
        ("🌐", "v0.2.0 — Multi-Language Support (English, Spanish, French, German, Japanese, Chinese, Hindi)"),
        ("🎵", "v0.2.0 — Audio Feedback Cues on lock & unlock transitions"),
        ("⌨️", "v0.2.0 — Customizable Lock & Unlock Hotkeys in Settings"),
        ("🖥️", "v0.2.0 — Multi-Monitor virtual screen coverage fix"),
        ("🛡️", "v0.1.0 — Windows Key blocker during locked state"),
        ("🌐", "v0.1.0 — Network Show Control (OSC UDP / JSON TCP)"),
        ("📦", "v0.1.0 — Published on Microsoft Store & winget"),
    ]:
        cl_row = tk.Frame(cl_card, bg=CARD_BG)
        cl_row.pack(fill="x", padx=12, pady=2)
        tk.Label(cl_row, text=icon, font=("Segoe UI Emoji", 10), bg=CARD_BG).pack(side="left", padx=(0, 8))
        tk.Label(cl_row, text=headline, bg=CARD_BG, fg=TEXT_MUTED, font=("Segoe UI", 9), anchor="w").pack(side="left")

    tk.Button(
        cl_card, text="View Full Changelog on GitHub →",
        command=lambda: webbrowser.open(APP_RELEASES),
        bg=CARD_BG, fg="#38BDF8", activebackground=CARD_BG, activeforeground="#7DD3FC",
        relief="flat", bd=0, font=("Segoe UI", 8, "bold"), cursor="hand2",
    ).pack(anchor="w", padx=12, pady=(6, 8))

    # ── System Information ────────────────────────────────────────────────
    import sys as _sys, platform as _platform
    try:
        _cfg_path = str(get_config_path())
    except Exception:
        _cfg_path = "N/A"

    sys_card = tk.Frame(
        pad, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    sys_card.pack(fill="x", pady=(0, 12), ipady=6, ipadx=10)

    tk.Label(
        sys_card, text=t("about_system_info"),
        bg=CARD_BG, fg=CARD_HEADER, font=("Segoe UI", 8, "bold"),
    ).pack(anchor="w", padx=12, pady=(6, 4))

    for label, value in [
        ("App Version",  f"v{__version__}"),
        ("Python",       f"{_sys.version.split()[0]}  ({_sys.implementation.name})"),
        ("Platform",     _platform.platform(terse=True)),
        ("Architecture", _platform.machine()),
        ("Config File",  _cfg_path),
    ]:
        si_row = tk.Frame(sys_card, bg=CARD_BG)
        si_row.pack(fill="x", padx=12, pady=1)
        tk.Label(si_row, text=label, bg=CARD_BG, fg=TEXT_MUTED, font=("Segoe UI", 9), width=14, anchor="w").pack(side="left")
        tk.Label(si_row, text=value, bg=CARD_BG, fg=TEXT_PRIMARY, font=("Segoe UI", 9), anchor="w").pack(side="left", fill="x")

    # ── Open Source Notice ────────────────────────────────────────────────
    tk.Label(
        pad,
        text=t("about_open_source_msg"),
        bg=BG, fg=TEXT_SUBTLE, font=("Segoe UI", 8),
        justify="center",
    ).pack(pady=(2, 10))

    # ── Footer ────────────────────────────────────────────────────────────
    ft_row = tk.Frame(pad, bg=BG)
    ft_row.pack(fill="x")
    tk.Label(
        ft_row, text="© 2026 Joseph Sharun • MIT License",
        bg=BG, fg=TEXT_SUBTLE, font=("Segoe UI", 8),
    ).pack(side="left")
    tk.Button(
        ft_row, text=t("btn_close"), command=top.destroy,
        bg=BTN_SEC_BG, fg=TEXT_PRIMARY, activebackground=BTN_SEC_HOVER, activeforeground=TEXT_PRIMARY,
        relief="flat", bd=1, padx=14, pady=4, font=("Segoe UI", 9), cursor="hand2",
    ).pack(side="right")

    top.update_idletasks()
    w, h = 510, 680
    if parent:
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
    else:
        x = (top.winfo_screenwidth() - w) // 2
        y = (top.winfo_screenheight() - h) // 2
    top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")


def show_tutorial_dialog(parent: Optional[tk.Tk | tk.Toplevel] = None, on_finish=None) -> None:
    """Show an Apple-inspired onboarding tutorial guide for new users."""
    top = tk.Toplevel(parent)
    top.title(t("tut_title"))
    top.resizable(False, False)
    top.configure(bg=BG)
    top.transient(parent)
    top.grab_set()

    _refs: list = []

    assets_dir = get_assets_dir()
    ico_path = assets_dir / "app_icon.ico"
    if not ico_path.is_file():
        ico_path = assets_dir / "icon.ico"
    logo_path = assets_dir / "logo.png"
    if ico_path.is_file():
        try:
            top.iconbitmap(str(ico_path))
        except Exception:
            pass

    if logo_path.is_file():
        try:
            from PIL import Image, ImageTk
            _tut_ico = ImageTk.PhotoImage(Image.open(str(logo_path)).convert("RGBA"), master=top)
            _refs.append(_tut_ico)
            top.wm_iconphoto(True, _tut_ico)
        except Exception:
            pass

    content = tk.Frame(top, bg=BG)
    content.pack(fill="both", expand=True, padx=22, pady=18)

    # ── Header ────────────────────────────────────────────────────────────
    hdr = tk.Frame(content, bg=BG)
    hdr.pack(fill="x", pady=(0, 14))

    if logo_path.is_file():
        try:
            from PIL import Image, ImageTk
            lim = Image.open(str(logo_path)).convert("RGBA").resize((44, 44), Image.LANCZOS)
            lph = ImageTk.PhotoImage(lim, master=top)
            _refs.append(lph)
            tk.Label(hdr, image=lph, bg=BG).pack(side="left", padx=(0, 10))
        except Exception:
            tk.Label(hdr, text="💡", font=("Segoe UI Emoji", 24), bg=BG).pack(side="left", padx=(0, 10))
    else:
        tk.Label(hdr, text="💡", font=("Segoe UI Emoji", 24), bg=BG).pack(side="left", padx=(0, 10))

    ht_frame = tk.Frame(hdr, bg=BG)
    ht_frame.pack(side="left", fill="both", expand=True)

    tk.Label(
        ht_frame, text=t("tut_welcome"),
        bg=BG, fg=TEXT_PRIMARY, font=("Segoe UI", 15, "bold"),
    ).pack(anchor="w")

    tk.Label(
        ht_frame, text=t("tut_subtitle"),
        bg=BG, fg=TEXT_MUTED, font=("Segoe UI", 9),
    ).pack(anchor="w", pady=(1, 0))

    # Helper for step cards
    def make_step(parent_f, icon_str, title_str, badge_str, desc_str, highlight=False):
        bd_col = "#0284C7" if highlight else CARD_BORDER
        bg_col = "#0F1A2E" if highlight else CARD_BG
        card = tk.Frame(
            parent_f, bg=bg_col, bd=1, relief="solid",
            highlightthickness=1, highlightbackground=bd_col,
        )
        card.pack(fill="x", pady=(0, 9), ipady=5, ipadx=8)

        row = tk.Frame(card, bg=bg_col)
        row.pack(fill="x", padx=10, pady=(3, 1))

        tk.Label(row, text=icon_str, font=("Segoe UI Emoji", 13), bg=bg_col).pack(side="left", padx=(0, 8))

        t_f = tk.Frame(row, bg=bg_col)
        t_f.pack(side="left", fill="both", expand=True)
        tk.Label(t_f, text=title_str, bg=bg_col, fg=TEXT_PRIMARY, font=("Segoe UI", 10, "bold")).pack(side="left")

        if badge_str:
            b_bg = "#0C4A6E" if highlight else "#1E293B"
            b_fg = "#38BDF8" if highlight else "#94A3B8"
            b_bd = "#0284C7" if highlight else "#334155"
            tk.Label(
                row, text=badge_str, bg=b_bg, fg=b_fg, font=("Segoe UI", 8, "bold"),
                padx=6, pady=2, bd=1, relief="solid",
            ).pack(side="right")

        tk.Label(
            card, text=desc_str, bg=bg_col, fg=TEXT_MUTED, font=("Segoe UI", 9),
            wraplength=450, justify="left",
        ).pack(anchor="w", padx=34, pady=(1, 4))

    make_step(
        content,
        icon_str="🔒",
        title_str=t("tut_step1_title"),
        badge_str=t("tut_step1_badge", hotkey="F11"),
        desc_str=t("tut_step1_desc", hotkey="F11"),
    )

    make_step(
        content,
        icon_str="🔑",
        title_str=t("tut_step2_title"),
        badge_str=t("tut_step2_badge", hotkey="Ctrl + Alt + Shift + U"),
        desc_str=t("tut_step2_desc", hotkey="Ctrl + Alt + Shift + U"),
        highlight=True,
    )

    make_step(
        content,
        icon_str="🛡️",
        title_str=t("tut_step3_title"),
        badge_str=t("tut_step3_badge"),
        desc_str=t("tut_step3_desc"),
    )

    make_step(
        content,
        icon_str="⚙️",
        title_str=t("tut_step4_title"),
        badge_str=t("tut_step4_badge"),
        desc_str=t("tut_step4_desc"),
    )

    # ── Bottom Action Button ──────────────────────────────────────────────
    def _finish():
        if on_finish:
            on_finish()
        top.grab_release()
        top.destroy()

    btn_row = tk.Frame(content, bg=BG)
    btn_row.pack(fill="x", pady=(6, 0))

    tk.Button(
        btn_row, text=t("tut_btn_got_it"), command=_finish,
        bg=ACCENT_BLUE, fg=TEXT_PRIMARY, activebackground=ACCENT_HOVER, activeforeground=TEXT_PRIMARY,
        relief="flat", bd=0, padx=16, pady=7, font=("Segoe UI", 10, "bold"), cursor="hand2",
    ).pack(side="right")

    top.update_idletasks()
    w, h = 530, 520
    if parent:
        x = parent.winfo_x() + (parent.winfo_width() - w) // 2
        y = parent.winfo_y() + (parent.winfo_height() - h) // 2
    else:
        x = (top.winfo_screenwidth() - w) // 2
        y = (top.winfo_screenheight() - h) // 2
    top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")


def show_config_dialog(
    config=None,
    on_save=None,
    on_lock=None,
    on_hide=None,
    standalone: bool = True,
) -> Any:
    """Show the Apple-inspired settings dialog.

    In standalone mode (default), runs modally and returns (config, should_launch).
    In companion mode (standalone=False), returns a SettingsController with show/hide/request_show.
    """
    cfg = config or LockerConfig()

    result: dict = {"config": None, "launch": False}
    _thumb_ref: list = []          # prevent PhotoImage GC

    # ── root ─────────────────────────────────────────────────────────────
    root = tk.Tk()
    root.withdraw()                # hide while building to prevent white flash
    root.title(f"{t('app_name')} — Settings")
    root.resizable(True, True)     # Responsive & resizable
    root.minsize(580, 500)
    root.configure(bg=BG)

    # ── helper factories ──────────────────────────────────────────────────
    def lbl(parent, text, *, muted=False, subtle=False, size=10, bold=False, **kw):
        color = TEXT_SUBTLE if subtle else (TEXT_MUTED if muted else TEXT_PRIMARY)
        return tk.Label(
            parent, text=text,
            bg=parent["bg"], fg=color,
            font=("Segoe UI", size, "bold" if bold else "normal"),
            **kw,
        )

    def entry(parent, *, show="", **kw):
        return tk.Entry(
            parent,
            bg=INPUT_BG, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
            relief="flat", bd=0,
            highlightthickness=1,
            highlightbackground=INPUT_BORDER,
            highlightcolor=INPUT_FOCUS,
            show=show,
            font=("Segoe UI", 10),
            **kw,
        )

    def btn(parent, text, cmd, *, primary=False, danger=False, **kw):
        bg_col = ACCENT_BLUE if primary else (DANGER_BG if danger else BTN_SEC_BG)
        fg_col = TEXT_PRIMARY if not danger else DANGER_TEXT
        active_bg = ACCENT_HOVER if primary else (DANGER_HOVER if danger else BTN_SEC_HOVER)
        bd_col = ACCENT_BLUE if primary else (DANGER_BD if danger else BTN_SEC_BD)

        return tk.Button(
            parent, text=text, command=cmd,
            bg=bg_col, fg=fg_col,
            activebackground=active_bg,
            activeforeground=TEXT_PRIMARY,
            relief="flat", bd=1,
            highlightthickness=0,
            padx=12, pady=6,
            font=("Segoe UI", 9, "bold" if primary else "normal"),
            cursor="hand2",
            **kw,
        )

    # ── window icon & assets ──────────────────────────────────────────────
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

    if logo_path.is_file():
        try:
            from PIL import Image, ImageTk
            _ico_img = Image.open(str(logo_path)).convert("RGBA")
            _tk_ico = ImageTk.PhotoImage(_ico_img, master=root)
            _thumb_ref.append(_tk_ico)
            root.wm_iconphoto(True, _tk_ico)
        except Exception as exc:
            logger.debug("Failed to set wm_iconphoto: %s", exc)

    # ── header bar (permanently docked to top) ────────────────────────────
    header = tk.Frame(root, bg=BG)
    header.pack(side="top", fill="x", padx=18, pady=(14, 10))

    hdr_row = tk.Frame(header, bg=BG)
    hdr_row.pack(fill="x")

    if logo_path.is_file():
        try:
            from PIL import Image, ImageTk
            lim = Image.open(str(logo_path)).convert("RGBA").resize((40, 40), Image.LANCZOS)
            lph = ImageTk.PhotoImage(lim, master=root)
            _thumb_ref.append(lph)
            logo_lbl = tk.Label(hdr_row, image=lph, bg=BG)
            logo_lbl.pack(side="left", padx=(0, 10))
        except Exception:
            tk.Label(hdr_row, text="🔒", font=("Segoe UI Emoji", 20), bg=BG).pack(side="left", padx=(0, 10))
    else:
        tk.Label(hdr_row, text="🔒", font=("Segoe UI Emoji", 20), bg=BG).pack(side="left", padx=(0, 10))

    titles_frame = tk.Frame(hdr_row, bg=BG)
    titles_frame.pack(side="left", fill="x", expand=True)

    t_row = tk.Frame(titles_frame, bg=BG)
    t_row.pack(anchor="w")
    lbl(t_row, "Input Locker", size=15, bold=True).pack(side="left")
    tk.Label(
        t_row, text=f"v{__version__}",
        bg="#1E1B4B", fg="#818CF8", font=("Segoe UI", 8, "bold"),
        padx=6, pady=1, bd=1, relief="solid",
    ).pack(side="left", padx=(8, 0))

    tagline_lbl = lbl(titles_frame, t("app_tagline"), muted=True, size=9)
    tagline_lbl.pack(anchor="w", pady=(1, 0))

    # Top right header action buttons
    top_btns = tk.Frame(hdr_row, bg=BG)
    top_btns.pack(side="right")

    def _open_about():
        show_about_dialog(parent=root)

    def _open_tutorial():
        show_tutorial_dialog(parent=root)

    def manual_check_updates():
        check_btn.config(text=t("btn_checking"), state="disabled")
        def _on_manual_result(info: Optional[dict]):
            def _ui():
                check_btn.config(text=t("btn_check_updates"), state="normal")
                if info and info.get("available"):
                    on_update_found(info)
                else:
                    messagebox.showinfo(
                        "Update Status",
                        f"Input Locker v{__version__} is up to date.\nNo newer version found.",
                        parent=root,
                    )
            if root.winfo_exists():
                root.after(0, _ui)

        check_for_updates_async(
            callback=_on_manual_result,
            repo_or_url=getattr(cfg, "update_repo", ""),
        )

    # Header buttons: primary Lock button is prominently visible at the top right!
    header_lock_btn = btn(top_btns, t("btn_lock_now_header"), lambda: save_and_lock(), primary=True)
    header_lock_btn.pack(side="right", padx=(8, 0))

    check_btn = btn(top_btns, t("btn_check_updates"), manual_check_updates)
    check_btn.pack(side="right", padx=(4, 0))

    about_btn = btn(top_btns, t("btn_about"), _open_about)
    about_btn.pack(side="right", padx=(4, 0))

    guide_btn = btn(top_btns, t("btn_guide"), _open_tutorial)
    guide_btn.pack(side="right")

    # ── Action Button Bar (permanently docked to bottom) ──────────────────
    btn_row = tk.Frame(root, bg=BG)
    btn_row.pack(side="bottom", fill="x", padx=18, pady=(10, 14))

    cancel_btn = btn(btn_row, t("btn_cancel"), lambda: cancel())
    cancel_btn.pack(side="left")

    initial_lk = getattr(cfg, 'lock_hotkey', 'F11')
    run_bg_btn = btn(btn_row, t("btn_run_background", hotkey=initial_lk), lambda: run_in_background())
    run_bg_btn.pack(side="left", padx=8)

    bottom_lock_btn = btn(btn_row, f"  {t('btn_lock_now')}  ", lambda: save_and_lock(), primary=True)
    bottom_lock_btn.pack(side="right")

    # ── Scrollable Card Viewport (fills all middle space) ─────────────────
    scroll_container = tk.Frame(root, bg=BG)
    scroll_container.pack(side="top", fill="both", expand=True, padx=8, pady=0)

    canvas_scroll = tk.Canvas(scroll_container, bg=BG, bd=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(scroll_container, orient="vertical", command=canvas_scroll.yview)
    canvas_scroll.configure(yscrollcommand=scrollbar.set)

    scrollbar.pack(side="right", fill="y")
    canvas_scroll.pack(side="left", fill="both", expand=True)

    content = tk.Frame(canvas_scroll, bg=BG)
    content_window = canvas_scroll.create_window((0, 0), window=content, anchor="nw")

    def _on_content_configure(e):
        canvas_scroll.configure(scrollregion=canvas_scroll.bbox("all"))

    def _on_canvas_configure(e):
        canvas_scroll.itemconfig(content_window, width=e.width)

    content.bind("<Configure>", _on_content_configure)
    canvas_scroll.bind("<Configure>", _on_canvas_configure)

    def _on_mousewheel(e):
        try:
            if root.winfo_exists() and canvas_scroll.winfo_exists():
                canvas_scroll.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass

    canvas_scroll.bind_all("<MouseWheel>", _on_mousewheel)

    def _on_destroy(e):
        if e.widget == root:
            try:
                canvas_scroll.unbind_all("<MouseWheel>")
            except Exception:
                pass

    root.bind("<Destroy>", _on_destroy)

    # ── update banner ─────────────────────────────────────────────────────
    update_banner = tk.Frame(
        content, bg=BANNER_BG, bd=1, relief="solid", highlightthickness=1,
        highlightbackground=BANNER_BD,
    )

    def on_update_found(info: Optional[dict]) -> None:
        if not info or not root.winfo_exists():
            return
        ver = info.get("latest_version", "")
        url = info.get("release_url", "https://github.com/SHARUNJOSEPH/input-locker/releases/latest")

        for child in update_banner.winfo_children():
            child.destroy()

        b_lbl = tk.Label(
            update_banner,
            text=f"📢 Update Available: {ver}! A newer release is ready.",
            bg=BANNER_BG, fg="#E0F2FE", font=("Segoe UI", 9, "bold"),
        )
        b_lbl.pack(side="left", padx=(12, 8), pady=7)

        def open_url():
            webbrowser.open(url)

        dl_btn = tk.Button(
            update_banner, text="Download", command=open_url,
            bg="#2563EB", fg="#FFFFFF", activebackground="#3B82F6",
            relief="flat", bd=0, padx=10, pady=3,
            font=("Segoe UI", 9, "bold"), cursor="hand2",
        )
        dl_btn.pack(side="left", padx=4, pady=7)

        close_btn = tk.Button(
            update_banner, text="✕", command=lambda: update_banner.pack_forget(),
            bg=BANNER_BG, fg="#93C5FD", activebackground=BANNER_BG,
            relief="flat", bd=0, padx=6, pady=3,
            font=("Segoe UI", 9), cursor="hand2",
        )
        close_btn.pack(side="right", padx=(0, 8), pady=7)

        update_banner.pack(fill="x", padx=10, pady=(0, 10), before=guide_card)

    # ── In-App Quick Shortcut & Unlock Guide ───────────────────────────
    guide_card = tk.Frame(
        content, bg="#0E172A", bd=1, relief="solid",
        highlightthickness=1, highlightbackground="#1E3A8A",
    )
    guide_card.pack(fill="x", padx=10, pady=(0, 10), ipady=5, ipadx=8)

    g_row = tk.Frame(guide_card, bg="#0E172A")
    g_row.pack(fill="x", padx=8, pady=(4, 2))

    guide_unlock_title_lbl = tk.Label(
        g_row, text=t("guide_how_to_unlock"),
        bg="#0E172A", fg="#38BDF8", font=("Segoe UI", 9, "bold"),
    )
    guide_unlock_title_lbl.pack(side="left")

    unlock_guide_lbl = tk.Label(
        g_row, text=getattr(cfg, "unlock_hotkey", "Ctrl+Alt+Shift+U"),
        bg="#1E293B", fg="#F8FAFC", font=("Segoe UI", 9, "bold"),
        padx=7, pady=2, bd=1, relief="solid", highlightbackground="#0284C7",
    )
    unlock_guide_lbl.pack(side="left", padx=(8, 14))

    guide_lock_title_lbl = tk.Label(
        g_row, text=t("guide_how_to_lock"),
        bg="#0E172A", fg="#94A3B8", font=("Segoe UI", 9, "bold"),
    )
    guide_lock_title_lbl.pack(side="left")

    lock_guide_lbl = tk.Label(
        g_row, text=getattr(cfg, "lock_hotkey", "F11"),
        bg="#1E293B", fg="#F8FAFC", font=("Segoe UI", 9, "bold"),
        padx=7, pady=2, bd=1, relief="solid",
    )
    lock_guide_lbl.pack(side="left", padx=(6, 0))

    initial_unlock = getattr(cfg, "unlock_hotkey", "Ctrl + Alt + Shift + U")
    guide_sub_lbl = tk.Label(
        guide_card,
        text=t("guide_unlock_instruction", hotkey=initial_unlock),
        bg="#0E172A", fg=TEXT_MUTED, font=("Segoe UI", 8),
    )
    guide_sub_lbl.pack(anchor="w", padx=8, pady=(1, 3))

    # ── Card 1: Wallpaper Section ─────────────────────────────────────────
    wp_card = tk.Frame(
        content, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    wp_card.pack(fill="x", padx=10, pady=(0, 10), ipady=6, ipadx=6)

    wp_hdr = tk.Frame(wp_card, bg=CARD_BG)
    wp_hdr.pack(fill="x", padx=10, pady=(6, 4))
    wp_title_lbl = lbl(wp_hdr, t("card_wallpaper_title"), bold=True, size=8, subtle=True)
    wp_title_lbl.pack(side="left")
    wp_subtitle_lbl = lbl(wp_hdr, t("card_wallpaper_subtitle"), muted=True, size=8)
    wp_subtitle_lbl.pack(side="right")

    wp_row = tk.Frame(wp_card, bg=CARD_BG)
    wp_row.pack(fill="x", padx=10, pady=(2, 6))

    wp_var = tk.StringVar(value=cfg.wallpaper or "")
    wp_entry = entry(wp_row, textvariable=wp_var)
    wp_entry.pack(side="left", fill="x", expand=True, ipady=4)

    def browse():
        path = filedialog.askopenfilename(
            parent=root, title="Select Wallpaper Image",
            initialdir=str(Path.home() / "Pictures"),
            filetypes=[
                ("Images", "*.jpg *.jpeg *.png *.bmp *.webp *.gif"),
                ("All files", "*.*"),
            ],
        )
        if path:
            wp_var.set(path)

    def clear_wallpaper():
        wp_var.set("")

    btn_browse = btn(wp_row, t("btn_browse"), browse)
    btn_browse.pack(side="left", padx=(8, 0))

    btn_clear = btn(wp_row, t("btn_remove"), clear_wallpaper, danger=True)
    btn_clear.pack(side="left", padx=(6, 0))

    # Preview canvas
    canvas = tk.Canvas(
        wp_card, bg=INPUT_BG, bd=0,
        highlightthickness=1, highlightbackground=INPUT_BORDER,
        width=470, height=95,
    )
    canvas.pack(padx=10, pady=(2, 4))

    def refresh_thumb(*_):
        canvas.delete("all")
        path = wp_var.get().strip()
        if path and Path(path).is_file():
            ph = _make_thumbnail(path, w=470, h=95, master=root)
            if ph:
                _thumb_ref.append(ph)
                canvas.create_image(0, 0, anchor="nw", image=ph)
                # Subtle center badge indicator
                canvas.create_rectangle(165, 34, 305, 62, fill="#000000", outline="#38BDF8", width=1)
                canvas.create_text(235, 48, text=t("wp_badge_active"), fill="#F8FAFC",
                                   font=("Segoe UI", 9, "bold"))
                return

        # Apple-style Dark Glass blur state representation
        canvas.create_rectangle(0, 0, 470, 95, fill="#0D1322", outline="")
        canvas.create_oval(215, 18, 255, 58, fill="#1E293B", outline="#334155")
        canvas.create_text(235, 38, text="🔒", fill="#FFFFFF", font=("Segoe UI Emoji", 14))
        canvas.create_text(235, 72, text=t("wp_badge_glass"),
                           fill=TEXT_MUTED, font=("Segoe UI", 9))

    wp_var.trace_add("write", refresh_thumb)
    refresh_thumb()

    # ── Card 2: Security & Credentials Section ────────────────────────────
    pw_card = tk.Frame(
        content, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    pw_card.pack(fill="x", padx=10, pady=(0, 10), ipady=6, ipadx=6)

    pw_hdr = tk.Frame(pw_card, bg=CARD_BG)
    pw_hdr.pack(fill="x", padx=10, pady=(6, 4))
    pw_title_lbl = lbl(pw_hdr, t("card_security_title"), bold=True, size=8, subtle=True)
    pw_title_lbl.pack(side="left")

    has_saved_pw = bool(cfg.password or cfg.password_hash)
    pw_cleared = [False]

    status_pill = tk.Label(
        pw_hdr,
        text=t("badge_password_protected") if has_saved_pw else t("badge_no_password"),
        bg=SUCCESS_BG if has_saved_pw else "#1E293B",
        fg=SUCCESS_TEXT if has_saved_pw else TEXT_MUTED,
        font=("Segoe UI", 8, "bold"),
        padx=6, pady=1, bd=1, relief="solid",
    )
    status_pill.pack(side="right")

    # Password input row
    pw_entry_lbl = lbl(pw_card, t("label_unlock_password") + (" (Leave blank to keep saved)" if cfg.password_hash else ""), muted=True, size=9)
    pw_entry_lbl.pack(anchor="w", padx=10, pady=(4, 2))

    pw_row_entry = tk.Frame(pw_card, bg=CARD_BG)
    pw_row_entry.pack(fill="x", padx=10)

    pw_e = entry(pw_row_entry, show="\u2022")
    pw_e.pack(side="left", fill="x", expand=True, ipady=4)
    
    if cfg.password:
        pw_e.insert(0, cfg.password)

    def do_clear_password():
        pw_cleared[0] = True
        pw_e.delete(0, tk.END)
        pw2_e.delete(0, tk.END)
        status_pill.config(
            text=t("badge_password_removed"),
            bg="#374151", fg="#F59E0B",
        )

    btn_remove_pw = None
    if has_saved_pw:
        btn_remove_pw = btn(pw_row_entry, t("btn_remove_password"), do_clear_password, danger=True)
        btn_remove_pw.pack(side="left", padx=(8, 0))

    # Confirm row
    pw_confirm_lbl = lbl(pw_card, t("label_confirm_password") + (" (Leave blank to keep saved)" if cfg.password_hash else ""), muted=True, size=9)
    pw_confirm_lbl.pack(anchor="w", padx=10, pady=(6, 2))
    pw2_e = entry(pw_card, show="\u2022")
    pw2_e.pack(fill="x", padx=10, ipady=4)
    if cfg.password:
        pw2_e.insert(0, cfg.password)

    err_lbl = tk.Label(pw_card, text="", bg=CARD_BG, fg=DANGER_TEXT, font=("Segoe UI", 8))
    err_lbl.pack(anchor="w", padx=10, pady=(2, 0))

    pw_hint_lbl = lbl(pw_card, t("hint_unlock_flow"), subtle=True, size=8)
    pw_hint_lbl.pack(anchor="w", padx=10, pady=(2, 4))

    # ── Card 3: Hotkeys & Audio Feedback Section ──────────────────────────
    hk_card = tk.Frame(
        content, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    hk_card.pack(fill="x", padx=10, pady=(0, 10), ipady=5, ipadx=6)

    hk_hdr = tk.Frame(hk_card, bg=CARD_BG)
    hk_hdr.pack(fill="x", padx=10, pady=(4, 4))
    hk_title_lbl = lbl(hk_hdr, t("card_shortcuts_title"), bold=True, size=8, subtle=True)
    hk_title_lbl.pack(side="left")
    hk_subtitle_lbl = lbl(hk_hdr, t("card_shortcuts_subtitle"), muted=True, size=8)
    hk_subtitle_lbl.pack(side="right")

    # Lock hotkey row
    hk_row1 = tk.Frame(hk_card, bg=CARD_BG)
    hk_row1.pack(fill="x", padx=10, pady=(2, 3))
    hk_lock_lbl = lbl(hk_row1, t("label_lock_trigger"), muted=True, size=9)
    hk_lock_lbl.pack(side="left", padx=(0, 8))

    lock_hk_var = tk.StringVar(value=getattr(cfg, "lock_hotkey", "F11"))
    lock_hk_entry = entry(hk_row1, textvariable=lock_hk_var, width=12)
    lock_hk_entry.pack(side="left", ipady=2)

    def set_lock_preset(p: str):
        lock_hk_var.set(p)

    for preset in ("F11", "F9", "F10", "F12", "Ctrl+F12"):
        btn(hk_row1, preset, lambda p=preset: set_lock_preset(p)).pack(side="left", padx=2)

    # Unlock hotkey row
    hk_row2 = tk.Frame(hk_card, bg=CARD_BG)
    hk_row2.pack(fill="x", padx=10, pady=(3, 3))
    hk_unlock_lbl = lbl(hk_row2, t("label_unlock_combo"), muted=True, size=9)
    hk_unlock_lbl.pack(side="left", padx=(0, 6))

    unlock_hk_var = tk.StringVar(value=getattr(cfg, "unlock_hotkey", "Ctrl+Alt+Shift+U"))
    unlock_hk_entry = entry(hk_row2, textvariable=unlock_hk_var, width=20)
    unlock_hk_entry.pack(side="left", ipady=2)

    def set_unlock_preset(p: str):
        unlock_hk_var.set(p)

    for preset in ("Ctrl+Alt+Shift+U", "Ctrl+Alt+Shift+L", "Ctrl+Alt+Shift+K"):
        btn(hk_row2, preset.split("+")[-1], lambda p=preset: set_unlock_preset(p)).pack(side="left", padx=2)

    def update_guide_badges(*_):
        lk = lock_hk_var.get().strip() or "F11"
        ulk = unlock_hk_var.get().strip() or "Ctrl+Alt+Shift+U"
        lock_guide_lbl.config(text=lk)
        unlock_guide_lbl.config(text=ulk)
        guide_sub_lbl.config(text=t("guide_unlock_instruction", hotkey=ulk))
        run_bg_btn.config(text=t("btn_run_background", hotkey=lk))

    lock_hk_var.trace_add("write", update_guide_badges)
    unlock_hk_var.trace_add("write", update_guide_badges)

    # Audio Feedback Row
    audio_row = tk.Frame(hk_card, bg=CARD_BG)
    audio_row.pack(fill="x", padx=10, pady=(5, 3))

    audio_feedback_var = tk.BooleanVar(value=getattr(cfg, "audio_feedback", False))
    audio_chk = tk.Checkbutton(
        audio_row,
        text=t("chk_audio_feedback"),
        variable=audio_feedback_var,
        bg=CARD_BG, fg=TEXT_PRIMARY, selectcolor=INPUT_BG,
        activebackground=CARD_BG, activeforeground=TEXT_PRIMARY,
        font=("Segoe UI", 9),
    )
    audio_chk.pack(anchor="w")
    audio_hint_lbl = lbl(audio_row, t("hint_audio_feedback"), subtle=True, size=8)
    audio_hint_lbl.pack(anchor="w", padx=24, pady=(1, 2))

    # ── Card 4: Preferences & Localization ───────────────────────────────
    pref_card = tk.Frame(
        content, bg=CARD_BG, bd=1, relief="solid",
        highlightthickness=1, highlightbackground=CARD_BORDER,
    )
    pref_card.pack(fill="x", padx=10, pady=(0, 10), ipady=6, ipadx=6)

    pref_hdr = tk.Frame(pref_card, bg=CARD_BG)
    pref_hdr.pack(fill="x", padx=10, pady=(4, 6))
    pref_title_lbl = lbl(pref_hdr, t("card_preferences_title"), bold=True, size=8, subtle=True)
    pref_title_lbl.pack(side="left")

    lang_row = tk.Frame(pref_card, bg=CARD_BG)
    lang_row.pack(fill="x", padx=10, pady=(2, 6))
    pref_lang_lbl = lbl(lang_row, t("label_language"), muted=True, size=9)
    pref_lang_lbl.pack(side="left", padx=(0, 10))

    lang_display_names = {
        "auto": "🌐 Auto-Detect (System OS)",
        **SUPPORTED_LANGUAGES,
    }

    current_lang_code = getattr(cfg, "language", "auto")
    if current_lang_code not in lang_display_names:
        current_lang_code = "auto"

    current_lang_var = tk.StringVar(value=current_lang_code)
    current_display_var = tk.StringVar(value=lang_display_names.get(current_lang_code, "🌐 Auto-Detect (System OS)"))

    lang_mb = tk.Menubutton(
        lang_row,
        textvariable=current_display_var,
        bg=INPUT_BG, fg=TEXT_PRIMARY,
        activebackground=INPUT_BORDER, activeforeground=TEXT_PRIMARY,
        relief="flat", bd=1,
        highlightthickness=1, highlightbackground=INPUT_BORDER,
        padx=12, pady=4,
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
    )
    lang_menu = tk.Menu(
        lang_mb, tearoff=0,
        bg=CARD_BG, fg=TEXT_PRIMARY,
        activebackground=ACCENT_BLUE, activeforeground=TEXT_PRIMARY,
        font=("Segoe UI", 9),
    )
    lang_mb["menu"] = lang_menu

    def on_select_lang(code: str):
        current_lang_var.set(code)
        current_display_var.set(lang_display_names.get(code, code))
        set_locale(code)
        cfg.language = code
        try:
            cfg.save()
        except Exception as exc:
            logger.debug("Failed to auto-save language preference: %s", exc)
        refresh_ui_language()

    for code, display in lang_display_names.items():
        lang_menu.add_command(label=display, command=lambda c=code: on_select_lang(c))

    lang_mb.pack(side="left")

    chk_row = tk.Frame(pref_card, bg=CARD_BG)
    chk_row.pack(fill="x", padx=10, pady=(4, 2))

    check_updates_var = tk.BooleanVar(value=getattr(cfg, "check_updates", True))
    chk = tk.Checkbutton(
        chk_row,
        text=t("chk_auto_updates"),
        variable=check_updates_var,
        bg=CARD_BG, fg=TEXT_MUTED, selectcolor=INPUT_BG, activebackground=CARD_BG, activeforeground=TEXT_PRIMARY,
        font=("Segoe UI", 8),
    )
    chk.pack(anchor="w")

    # ── Dynamic Multi-Language UI Refresh ─────────────────────────────────
    def refresh_ui_language():
        root.title(f"{t('app_name')} — Settings")
        tagline_lbl.config(text=t("app_tagline"))
        header_lock_btn.config(text=t("btn_lock_now_header"))
        check_btn.config(text=t("btn_check_updates"))
        about_btn.config(text=t("btn_about"))
        guide_btn.config(text=t("btn_guide"))

        guide_unlock_title_lbl.config(text=t("guide_how_to_unlock"))
        guide_lock_title_lbl.config(text=t("guide_how_to_lock"))
        guide_sub_lbl.config(text=t("guide_unlock_instruction", hotkey=unlock_hk_var.get().strip() or "Ctrl+Alt+Shift+U"))

        wp_title_lbl.config(text=t("card_wallpaper_title"))
        wp_subtitle_lbl.config(text=t("card_wallpaper_subtitle"))
        btn_browse.config(text=t("btn_browse"))
        btn_clear.config(text=t("btn_remove"))

        pw_title_lbl.config(text=t("card_security_title"))
        pw_entry_lbl.config(text=t("label_unlock_password"))
        pw_confirm_lbl.config(text=t("label_confirm_password"))
        pw_hint_lbl.config(text=t("hint_unlock_flow"))
        if btn_remove_pw and btn_remove_pw.winfo_exists():
            btn_remove_pw.config(text=t("btn_remove_password"))

        hk_title_lbl.config(text=t("card_shortcuts_title"))
        hk_subtitle_lbl.config(text=t("card_shortcuts_subtitle"))
        hk_lock_lbl.config(text=t("label_lock_trigger"))
        hk_unlock_lbl.config(text=t("label_unlock_combo"))
        audio_chk.config(text=t("chk_audio_feedback"))
        audio_hint_lbl.config(text=t("hint_audio_feedback"))

        pref_title_lbl.config(text=t("card_preferences_title"))
        pref_lang_lbl.config(text=t("label_language"))
        chk.config(text=t("chk_auto_updates"))

        cancel_btn.config(text=t("btn_cancel"))
        run_bg_btn.config(text=t("btn_run_background", hotkey=lock_hk_var.get().strip() or "F11"))
        bottom_lock_btn.config(text=f"  {t('btn_lock_now')}  ")

        has_pw = bool(pw_e.get() or cfg.password or cfg.password_hash) and not pw_cleared[0]
        status_pill.config(
            text=t("badge_password_protected") if has_pw else t("badge_no_password"),
            bg=SUCCESS_BG if has_pw else "#1E293B",
            fg=SUCCESS_TEXT if has_pw else TEXT_MUTED,
        )
        refresh_thumb()

    # ── Validation & Config Building ──────────────────────────────────────
    def validate() -> bool:
        pw, pw2 = pw_e.get(), pw2_e.get()
        wp = wp_var.get().strip()
        if pw != pw2:
            err_lbl.config(text=t("err_password_mismatch"))
            return False
        if wp and not Path(wp).is_file():
            messagebox.showerror("Invalid Wallpaper", t("err_invalid_wallpaper", path=wp), parent=root)
            return False

        lk = lock_hk_var.get().strip()
        ulk = unlock_hk_var.get().strip()
        try:
            parse_hotkey(lk)
        except Exception as exc:
            messagebox.showerror("Invalid Lock Hotkey", t("err_invalid_lock_hotkey", hotkey=lk, error=str(exc)), parent=root)
            return False
        try:
            parse_hotkey(ulk)
        except Exception as exc:
            messagebox.showerror("Invalid Unlock Hotkey", t("err_invalid_unlock_hotkey", hotkey=ulk, error=str(exc)), parent=root)
            return False

        err_lbl.config(text="")
        return True

    def build_config(lock_on_launch: bool) -> LockerConfig:
        new_cfg = LockerConfig(
            wallpaper=wp_var.get().strip(),
            lock_on_launch=lock_on_launch,
            check_updates=check_updates_var.get(),
            update_repo=getattr(cfg, "update_repo", ""),
            first_run=getattr(cfg, "first_run", False),
            audio_feedback=audio_feedback_var.get(),
            lock_hotkey=lock_hk_var.get().strip(),
            unlock_hotkey=unlock_hk_var.get().strip(),
            language=current_lang_var.get(),
        )
        if pw_cleared[0]:
            new_cfg.password = ""
            new_cfg.password_hash = ""
            new_cfg.password_salt = ""
        elif pw_e.get():
            new_cfg.set_password(pw_e.get())
        else:
            new_cfg.password = cfg.password
            new_cfg.password_hash = cfg.password_hash
            new_cfg.password_salt = cfg.password_salt
        return new_cfg

    def _force_restore_mouse(event=None):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            user32.ClipCursor(None)
            while user32.ShowCursor(True) < 0:
                pass
            IDC_ARROW = 32512
            h_cur = user32.LoadCursorW(None, IDC_ARROW)
            if h_cur:
                user32.SetCursor(h_cur)
        except Exception:
            pass

    def show_window():
        try:
            logger.info("show_window called! root.winfo_exists=%s", root.winfo_exists())
            if root.winfo_exists():
                _force_restore_mouse()
                root.config(cursor="arrow")
                root.deiconify()
                root.state("normal")
                root.lift()
                root.attributes("-topmost", True)
                root.after(150, lambda: root.attributes("-topmost", False) if root.winfo_exists() else None)
                root.focus_force()
                root.after(50, _force_restore_mouse)
                logger.info("show_window completed: deiconify & focus applied.")
        except Exception as exc:
            logger.warning("Error in show_window: %s", exc)

    def hide_window():
        try:
            if root.winfo_exists():
                root.withdraw()
        except Exception:
            pass

    def request_show():
        try:
            logger.info("request_show called! root.winfo_exists=%s", root.winfo_exists())
            if root.winfo_exists():
                root.after(0, show_window)
        except Exception as exc:
            logger.warning("Error in request_show: %s", exc)

    def request_hide():
        try:
            if root.winfo_exists():
                root.after(0, hide_window)
        except Exception:
            pass

    def destroy_window():
        try:
            if root.winfo_exists():
                root.destroy()
        except Exception:
            pass

    def save_and_lock():
        if not validate():
            return
        new_cfg = build_config(lock_on_launch=True)
        new_cfg.save()
        result["config"] = new_cfg
        result["launch"] = True
        if standalone:
            root.destroy()
        else:
            hide_window()
            if on_lock:
                on_lock(new_cfg)

    def run_in_background():
        if not validate():
            return
        new_cfg = build_config(lock_on_launch=False)
        new_cfg.save()
        result["config"] = new_cfg
        result["launch"] = True
        if standalone:
            root.destroy()
        else:
            hide_window()
            if on_save:
                on_save(new_cfg)
            if on_hide:
                on_hide()

    def cancel():
        if standalone:
            try:
                current_cfg = build_config(lock_on_launch=cfg.lock_on_launch)
                current_cfg.save()
            except Exception:
                pass
            root.destroy()
        else:
            hide_window()
            if on_hide:
                on_hide()

    root.protocol("WM_DELETE_WINDOW", cancel)

    # ── Background Update Check ───────────────────────────────────────────
    if check_updates_var.get():
        check_for_updates_async(
            callback=lambda info: root.after(0, lambda: on_update_found(info)),
            repo_or_url=getattr(cfg, "update_repo", ""),
        )

    # ── Reveal Window ─────────────────────────────────────────────────────
    _force_restore_mouse()
    root.config(cursor="arrow")
    root.bind("<Enter>", _force_restore_mouse, add="+")
    root.bind("<FocusIn>", _force_restore_mouse, add="+")
    root.update_idletasks()
    W = 620
    sx = root.winfo_screenwidth()
    sy = root.winfo_screenheight()
    H = min(760, max(540, sy - 90))
    root.geometry(f"{W}x{H}+{(sx - W)//2}+{(sy - H)//2}")
    root.update()
    root.deiconify()
    root.lift()
    root.attributes("-topmost", True)
    root.after(200, lambda: root.attributes("-topmost", False) if root.winfo_exists() else None)
    root.focus_force()
    root.after(50, _force_restore_mouse)

    # ── Auto-show tutorial for first-run users ────────────────────────────
    if getattr(cfg, "first_run", True):
        def _on_tut_done():
            cfg.first_run = False
            try:
                cfg.save()
            except Exception:
                pass
        root.after(250, lambda: show_tutorial_dialog(parent=root, on_finish=_on_tut_done) if root.winfo_exists() else None)

    class SettingsController:
        def __init__(self):
            self.root = root
            self.show = show_window
            self.hide = hide_window
            self.request_show = request_show
            self.request_hide = request_hide
            self.destroy = destroy_window
            self.mainloop = root.mainloop

    ctrl = SettingsController()

    if standalone:
        root.mainloop()
        return result["config"], result["launch"]
    return ctrl

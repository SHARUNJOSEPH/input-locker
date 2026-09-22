"""PyQt6 non-activating semi-transparent glass overlay.

Renders an elegant, hardware-accelerated frosted glass backdrop with a central
AV staging status badge across all physical displays. Uses WA_ShowWithoutActivating
and WindowDoesNotAcceptFocus to guarantee zero focus loss to background engines.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import sys
import threading
import time
from typing import List, Optional, Tuple

try:
    from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot
    from PyQt6.QtGui import QFont, QColor
    from PyQt6.QtWidgets import (
        QApplication,
        QFrame,
        QHBoxLayout,
        QLabel,
        QVBoxLayout,
        QWidget,
    )
    PYQT6_AVAILABLE = True
except ImportError:
    PYQT6_AVAILABLE = False

logger = logging.getLogger(__name__)


class _ScreenOverlayWidget(QWidget):
    """Semi-transparent glass overlay widget for a single physical display."""

    def __init__(
        self,
        screen,
        badge_title: str = "INPUT LOCKER ACTIVE",
        badge_subtitle: str = "Background media engines running • Input swallowed",
        wallpaper_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setScreen(screen)
        self.setGeometry(screen.geometry())

        # Crucial non-activating and transparent window flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.Tool
        )

        # Crucial widget attributes for zero focus disruption & pass-through
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        # Cursor over overlay: default to standard arrow; BlankCursor only when shown
        self.setCursor(Qt.CursorShape.ArrowCursor)

        # Load wallpaper pixmap (if path valid)
        self._wallpaper_pixmap: Optional[object] = None
        if wallpaper_path:
            from pathlib import Path as _Path
            if _Path(wallpaper_path).is_file():
                from PyQt6.QtGui import QPixmap
                px = QPixmap(wallpaper_path)
                self._wallpaper_pixmap = px if not px.isNull() else None

        self._init_ui()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """Paint wallpaper if present; fall back to dark frosted glass background."""
        from PyQt6.QtGui import QPainter, QColor
        painter = QPainter(self)

        # 1. ALWAYS fill 100% of the screen rectangle with a deep dark glass backdrop
        painter.fillRect(self.rect(), QColor(10, 15, 26, 235))

        # 2. If wallpaper image is provided, draw it covering the entire screen edge-to-edge
        if self._wallpaper_pixmap is not None:
            scaled = self._wallpaper_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            sx = max(0, (scaled.width()  - self.width())  // 2)
            sy = max(0, (scaled.height() - self.height()) // 2)
            painter.drawPixmap(0, 0, scaled, sx, sy, self.width(), self.height())

        painter.end()

    def _init_ui(self) -> None:
        # Fullscreen semi-transparent dark glass container
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        if self._wallpaper_pixmap is not None:
            self.setStyleSheet("background-color: transparent;")
        else:
            self.setStyleSheet("background-color: rgba(10, 15, 26, 175);")

        # Always render the central lock symbol badge overlay
        badge = QFrame(self)
        badge.setStyleSheet(
            """
            QFrame {
                background-color: rgba(15, 23, 42, 220);
                border: 1px solid rgba(56, 189, 248, 0.4);
                border-radius: 24px;
            }
            """
        )
        badge_layout = QVBoxLayout(badge)
        badge_layout.setContentsMargins(48, 36, 48, 36)
        badge_layout.setSpacing(12)
        badge_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        icon_label = QLabel("🔒", badge)
        icon_label.setStyleSheet("font-size: 56px; background: transparent;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_layout.addWidget(icon_label)

        title_label = QLabel("SYSTEM LOCKED", badge)
        title_label.setStyleSheet(
            """
            QLabel {
                font-family: 'Segoe UI', sans-serif;
                font-size: 16px;
                font-weight: 700;
                color: #F8FAFC;
                letter-spacing: 2px;
                background: transparent;
            }
            """
        )
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge_layout.addWidget(title_label)

        root_layout.addWidget(badge)


_user32 = ctypes.windll.user32
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.UINT
]

HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080


class _OverlayBridge(QObject):
    """Thread-safe signal/slot bridge controlling PyQt6 overlay widgets."""

    sig_show = pyqtSignal()
    sig_hide = pyqtSignal()
    sig_close = pyqtSignal()

    def __init__(self, widgets: List[_ScreenOverlayWidget]) -> None:
        super().__init__()
        self.widgets = widgets
        self._is_visible = False
        self.sig_show.connect(self._handle_show)
        self.sig_hide.connect(self._handle_hide)
        self.sig_close.connect(self._handle_close)

    @pyqtSlot()
    def _handle_show(self) -> None:
        vw = _user32.GetSystemMetrics(0)  # SM_CXSCREEN
        vh = _user32.GetSystemMetrics(1)  # SM_CYSCREEN
        for w in self.widgets:
            w.setGeometry(0, 0, vw, vh)
            w.setCursor(Qt.CursorShape.BlankCursor)
            w.show()
            hwnd = int(w.winId())
            _user32.SetWindowPos(
                hwnd, HWND_TOPMOST,
                0, 0, vw, vh,
                SWP_NOACTIVATE | SWP_SHOWWINDOW
            )
        self._is_visible = True

    @pyqtSlot()
    def _handle_hide(self) -> None:
        for w in self.widgets:
            hwnd = int(w.winId())
            _user32.SetWindowPos(
                hwnd, 0,
                0, 0, 0, 0,
                SWP_HIDEWINDOW | SWP_NOACTIVATE | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
            )
            w.hide()
            w.setCursor(Qt.CursorShape.ArrowCursor)
        self._is_visible = False

    @pyqtSlot()
    def _handle_close(self) -> None:
        for w in self.widgets:
            w.close()
        self._is_visible = False
        app = QApplication.instance()
        if app:
            app.quit()


class PyQtOverlay:
    """Multi-monitor non-activating semi-transparent overlay powered by PyQt6.

    Supports zero focus loss, rich AV staging status badge, multi-display geometry,
    and thread-safe control from any thread.
    """

    def __init__(
        self,
        auto_prewarm: bool = True,
        badge_title: str = "INPUT LOCKER ACTIVE",
        badge_subtitle: str = "Background media engines running • Input swallowed",
        wallpaper_path: str = "",
    ) -> None:
        if not PYQT6_AVAILABLE:
            raise RuntimeError("PyQt6 is not installed in the current Python environment")

        self.badge_title    = badge_title
        self.badge_subtitle = badge_subtitle
        self.wallpaper_path = wallpaper_path

        self._widgets: List[_ScreenOverlayWidget] = []
        self._bridge: Optional[_OverlayBridge] = None
        self._thread: Optional[threading.Thread] = None
        self._ready_event = threading.Event()
        self._state_lock = threading.Lock()
        self._is_visible: bool = False

        if auto_prewarm:
            self.prewarm()

    def _worker_thread(self) -> None:
        """Background thread hosting QApplication and overlay widgets."""
        app = QApplication.instance()
        owns_app = False
        if app is None:
            app = QApplication(sys.argv)
            owns_app = True

        self._widgets.clear()
        # Main / primary display ONLY — leaving secondary displays (AV / projector / LED) uncovered
        target_screen = app.primaryScreen()
        if target_screen is None:
            screens = app.screens()
            if screens:
                target_screen = screens[0]

        if target_screen is not None:
            w = _ScreenOverlayWidget(
                screen=target_screen,
                wallpaper_path=self.wallpaper_path,
            )
            w.hide()
            self._widgets.append(w)

        self._bridge = _OverlayBridge(self._widgets)
        self._ready_event.set()

        if owns_app:
            app.exec()

    def prewarm(self) -> None:
        """Pre-creates the overlay widgets on a background UI thread in hidden state."""
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                if not self._bridge:
                    self._ready_event.wait(timeout=4.0)
                return

            self._ready_event.clear()
            self._thread = threading.Thread(
                target=self._worker_thread,
                daemon=True,
                name="PyQtOverlayThread",
            )
            self._thread.start()

            if not self._ready_event.wait(timeout=4.0):
                logger.error("PyQtOverlay worker thread initialization timed out")

    def show(self) -> bool:
        """Displays the overlay across all displays without stealing focus.

        Returns:
            bool: True if show signal was dispatched.
        """
        with self._state_lock:
            if not self._bridge or not self._thread or not self._thread.is_alive():
                self.prewarm()

            if not self._bridge:
                return False

            self._bridge.sig_show.emit()
            self._is_visible = True
            logger.debug("PyQtOverlay show signal emitted")
            return True

    def hide(self) -> bool:
        """Hides the overlay across all displays without causing focus recalculation.

        Returns:
            bool: True if hide signal was dispatched.
        """
        with self._state_lock:
            if not self._bridge:
                self._is_visible = False
                return True

            self._bridge.sig_hide.emit()
            self._is_visible = False
            logger.debug("PyQtOverlay hide signal emitted")
            return True

    def is_visible(self) -> bool:
        """Returns whether the overlay is currently marked visible."""
        return self._is_visible

    def get_geometry(self) -> Tuple[int, int, int, int]:
        """Returns the bounding box encompassing all screens as (x, y, width, height)."""
        if not self._widgets:
            try:
                user32 = ctypes.windll.user32
                vx = int(user32.GetSystemMetrics(76))  # SM_XVIRTUALSCREEN
                vy = int(user32.GetSystemMetrics(77))  # SM_YVIRTUALSCREEN
                vw = int(user32.GetSystemMetrics(78))  # SM_CXVIRTUALSCREEN
                vh = int(user32.GetSystemMetrics(79))  # SM_CYVIRTUALSCREEN
                if vw > 0 and vh > 0:
                    return (vx, vy, vw, vh)
            except Exception:
                pass
            return (0, 0, 1920, 1080)

        min_x = min(w.x() for w in self._widgets)
        min_y = min(w.y() for w in self._widgets)
        max_r = max(w.x() + w.width() for w in self._widgets)
        max_b = max(w.y() + w.height() for w in self._widgets)
        return (min_x, min_y, max_r - min_x, max_b - min_y)

    def close(self) -> None:
        """Destroys the overlay widgets and terminates the Qt thread."""
        with self._state_lock:
            if self._bridge:
                self._bridge.sig_close.emit()
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2.0)
            self._widgets.clear()
            self._bridge = None
            self._thread = None
            self._is_visible = False

    def __enter__(self) -> PyQtOverlay:
        self.prewarm()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

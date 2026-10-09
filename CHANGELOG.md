# Changelog

All notable changes to the **Input Locker** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.10] - 2026-10-09

### Added
- **Install-time elevated touchpad helper**: Inno Setup registers on-demand scheduled task `\InputLocker\InputLockerTouchpadHelper` (RunLevel Highest). After install, Input Locker starts the helper via `schtasks /Run` with **no UAC on launch**. Uninstall removes the task. Helpers live under `installer/helpers/` (including a one-shot `register_touchpad_task_once.bat` / `deploy_no_uac.ps1` for existing installs).

### Fixed
- **Lock overlay latency**: Overlay now shows before Precision Touchpad PnP device disable. Registry gesture cut stays synchronous; device disable runs asynchronously. Startup warms the touchpad device ID cache. Removes the ~9s blank gap before the lock screen appeared.
- **Portable / source fallback**: If the scheduled task is missing, helper start still falls back to a one-shot RunAs (UAC once per session) instead of failing silently.

## [0.2.9] - 2026-10-09

### Added
- **Precision Touchpad Hardware Guard**: New `TouchpadGuard` disables user-scoped PTP multi-finger gesture toggles (3-/4-/5-finger slide & tap) via HKCU registry + `WM_SETTINGCHANGE` while locked, with atexit fail-safe restore.
- **Task View Watchdog**: Narrow-class dismisser for `XamlExplorerHostIslandWindow` / `MultitaskingViewFrame` so residual 3-finger swipe-up cannot expose staging apps.
- **Raw Touch / Edge-Gesture Hardening**: Stronger overlay raw-input registration, edge-gesture property suppression, and anti-hide protection while locked.

### Fixed
- **Single-Owner Touchpad Lifecycle**: `LockerController` now exclusively owns cut/restore; `OverlayManager` no longer double-toggles PTP state.
- **Watchdog Focus Safety**: Dropped broad `ApplicationFrameWindow` / empty-title `CoreWindow` matching that could disrupt UWP staging apps or password entry.
- **Injected Escape Passthrough**: Injected `VK_ESCAPE` used to dismiss Task View is no longer swallowed by the keyboard hook.

## [0.2.8] - 2026-10-07

### Added
- **Precision Touchpad & Multi-Finger Gesture Suppression**: Intercepts and swallows 3-finger and 4-finger touchpad gestures (Win+Tab, Alt+Tab, Ctrl+Win+Arrows, Win+D, Win+A, Win+S, Win+Arrows) during lock state and password entry mode.
- **Physical Touchscreen Tap & Drag Absorption**: Registers overlay window with Windows touch architecture (`RegisterTouchWindow`), captures pointer and touch events, and eliminates event pass-through to underlying background windows.
- **Resilient In-App Updater**: Added smooth 302 HTTP redirect resolution for direct GitHub release asset downloads, robust 10.0s network timeout, and clear user-facing error reporting with fallback to browser releases page.

### Fixed
- **Overlay Hit Testing & Zero Focus Disruption**: Removed `WS_EX_TRANSPARENT` style while retaining `WS_EX_NOACTIVATE`, returning `HTCLIENT` and `MA_NOACTIVATEANDEAT` to consume clicks and taps without stealing focus from active AV staging engines.

---

## [0.2.7] - 2026-10-01

### Added
- **Anonymous Install & Open Analytics**: Integrated privacy-first Aptabase telemetry to distinguish Microsoft Store vs GitHub installations with zero PII.
- **Store Packaging Update**: Bumped MSIX package identity to 0.2.7.0 for Microsoft Store certification.

### Fixed
- **Settings & Dynamic Wallpaper Persistence**: Resolved settings persistence bug and added explicit "Save Changes" button.

---

## [0.2.6] - 2026-10-01

### Added
- **Explicit "Save Changes" Button**: Added a prominent "Save Changes" button with green toast notification feedback to the Settings UI across all 7 supported languages.
- **Dynamic Wallpaper Switching**: Added thread-safe `set_wallpaper` pipeline through `PyQtOverlay`, `OverlayBridge`, and `OverlayManager` to apply lock screen wallpaper updates immediately without restarting the app.
- **Dynamic Settings Sync Unit Tests**: Added comprehensive test suite (`tests/unit/test_settings_sync.py`) validating wallpaper and password hot-reloading.

### Fixed
- **Settings & Wallpaper Persistence**: Fixed bug where wallpaper changes in Settings did not update the live lock screen overlay or save across sessions.
- **Password Persistence**: Resolved password update flow ensuring hashes and salts are written and retained correctly.
- **Dialog Auto-Save**: Settings automatically save on dialog close in companion mode, and reload fresh state upon re-opening.

---

## [0.2.5] - 2026-09-29

### Added
- **Microsoft Store Identity Alignment**: Synchronized AppxManifest with official Microsoft Store Publisher and Package Family Name.
- **Packaging Pipeline Enhancements**: MSIX bundling and multi-monitor overlay hardening.

---

## [0.2.4] - 2026-09-22

### Added
- **Companion Background Architecture**:
  - Re-architected the Settings GUI to use a persistent lifecycle (`standalone=False` mode).
  - Closing the Settings window via "X" or "Run in Background" minimizes to the system tray (`withdraw()`) without terminating the process.
  - Re-opening from the system tray icon (single/double click) or launching the desktop/start menu shortcut instantly restores the existing instance (`deiconify()`).
- **One-Click Local Launcher**: Added `Run-InputLocker.bat` for seamless local testing via Python GUI mode (`pythonw.exe`), bypassing Smart App Control false positives on dev builds.

### Fixed
- **Win32 64-bit IPC Single-Instance Signaling**:
  - Added explicit ctypes `argtypes` and `restypes` for all 64-bit Win32 handles (`CreateMutexW`, `CreateEventW`, `OpenEventW`, `SetEvent`, `WaitForSingleObject`, `CloseHandle`).
  - Resolved `ERROR_INVALID_NAME` (Win32 Error 123) pointer truncation when secondary instances notify the running background instance.
- **Mouse Cursor Disappearing on Restore**:
  - Resolved cursor invisibility when hovering over the restored Settings window.
  - Added unconditional Win32 `ClipCursor(None)` release and restored the thread cursor display counter (`while ShowCursor(True) < 0: pass`).
  - Explicitly loaded and applied the Windows standard arrow cursor (`IDC_ARROW = 32512`) via `SetCursor` on window restore, `<Enter>`, and `<FocusIn>` events.
  - Updated PyQt6 overlay widgets to default to standard arrow cursor when hidden and only switch to `BlankCursor` when actively locked and visible.
- **Settings & Password Persistence UX**:
  - Resolved bound-method conditional check (`if not controller.is_locked()`) preventing Settings from opening.
  - Ensured entered password hashes and customized hotkeys remain intact and properly displayed when re-entering Settings.

---

## [0.2.3] - 2026-09-22

### Added
- **Microsoft Store MSIX Packaging**: Complete packaging specification and assets for Windows Store distribution.
- **Enhanced Update Checker**: Asynchronous release checking against GitHub releases with in-app notification.

---

## [0.2.2] - 2026-09-20

### Added
- **Multi-language Localization**: Support for English, German, French, Spanish, and Japanese.
- **Winget Package Manifests**: Official package manifests submitted to Windows Package Manager repository.

---

## [0.2.1] - 2026-09-19

### Fixed
- **Settings Reopening**: Fixed window focus detection with Win32 class matching.
- **Password UI Indicator**: Masked asterisks indication for active password protection.

---

## [0.2.0] - 2026-09-17

### Added
- **Multi-Monitor Semi-Transparent Glass Overlay**: Hardware-accelerated PyQt6 overlay rendering across primary and secondary displays.
- **OSC UDP & JSON TCP Remote Control**: Network show control listener for professional AV staging integration.
- **Audio Feedback**: Subtle auditory confirmations for state transitions.

---

## [0.1.0] - 2026-09-09

### Added
- **Core Input Locker Engine**: Low-level Windows OS keyboard and mouse hook interception via `pynput`.
- **Atomic State Machine**: Sub-millisecond transition latency between LOCKED and UNLOCKED states.

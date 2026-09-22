# Changelog

All notable changes to the **Input Locker** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

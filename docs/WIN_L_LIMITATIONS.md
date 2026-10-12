# Win+L (Lock Workstation) Limitations

**Project:** Input Locker  
**Related:** [CAD_LIMITATIONS.md](CAD_LIMITATIONS.md) (Ctrl+Alt+Delete / SAS)

---

## Summary

`Win+L` switches to the Windows **Secure Desktop** (lock screen). Like
`Ctrl+Alt+Delete`, this path is owned by the OS. User-mode software — including
Input Locker’s low-level keyboard hooks — **cannot reliably prevent** it on
modern Windows 11, even when `DisableLockWorkstation` is set and verified.

Input Locker still:

1. Writes `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\DisableLockWorkstation = 1`
   via the elevated helper (verified read-back) while locked.
2. Neutralizes Win+L in the hook when possible (KEYUP injection).
3. **Recovers** cursor + touchpad + overlay when the user returns from the
   Windows lock screen so Input Locker is never left in a stranded state.

If Win+L still opens the Windows lock screen after the policy is verified, that
is an OS boundary — not an application bug. Staging practice: treat Win+L like
CAD (physical keyboard cover / operator discipline), and use tray
**Recover Mouse / Touchpad** if anything feels wrong after returning.

---

## Why the policy is not enough *until the next sign-in*

- `DisableLockWorkstation` is documented to remove Lock from Ctrl+Alt+Del and
  (historically) disable Win+L. On current Windows 11 builds it is often
  **ignored for Win+L until the next interactive logon**.
- **Confirmed 2026-10-12 on this project’s test PC:** with HKLM verified=1 in the
  same session, Win+L still opened Secure Desktop. After the elevated helper wrote
  HKLM=1 and the user **signed out and back in**, Win+L was blocked.
- HKCU writes are **Access Denied** on some machines (this project’s test PC).
- Helper must write the **64-bit** HKLM view and **read back** the value;
  earlier builds acked success while `$ErrorActionPreference = SilentlyContinue`
  hid failed writes.

### Installer implication

The Inno Setup installer sets
`HKLM\\...\\DisableLockWorkstation = 1` at install (and clears it on uninstall)
so the **first logon after install** already has Win+L blocked. While Input
Locker is installed the value stays `1` — lock/unlock no longer toggle it
(mid-session toggles do not affect Win+L until the next sign-in anyway).

---

## Operational mitigations for AV staging

1. Prefer a dedicated show keyboard without a Win key, or a key cover.
2. Keep Input Locker’s elevated helper registered so touchpad restore and
   policy writes work without UAC on every launch.
3. After any accidental Win+L: unlock Windows, then if needed use tray
   **Recover Mouse / Touchpad** (or unlock Input Locker normally).
4. Do not expect a user-mode locker to replace Windows session lock policy for
   security — that is not its job. Its job is staging input isolation with
   fail-safe recovery.

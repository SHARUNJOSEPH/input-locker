# Windows OS Security Boundaries & Ctrl+Alt+Delete (SAS) Limitations

**Project:** Windows AV Staging Input Locker  
**Target Environment:** Live Event Production & Media Server Staging (Resolume, WATCHOUT, Disguise, grandMA, DAWs)  
**Classification:** Technical Architecture & Operational Guide  

---

## 1. Executive Summary

The Windows AV Staging Input Locker is engineered to intercept and swallow 100% of global keyboard and mouse events during its **Locked** state using user-mode low-level Windows hooks (`WH_KEYBOARD_LL` and `WH_MOUSE_LL`). This prevents accidental or malicious tampering during live shows, rehearsals, and staging while rendering engines remain visible through a non-activating glass overlay.

However, an immutable operating system constraint exists within the Windows NT kernel architecture: **the key combination `Ctrl + Alt + Delete` cannot be intercepted, swallowed, or disabled by any user-mode software or hook**. 

This document explains the technical reasons for this constraint, details Windows desktop and kernel isolation boundaries, catalogs the interceptability of all major Windows system shortcuts, and provides actionable physical and administrative mitigations for live AV staging environments.

---

## 2. The Secure Attention Sequence (SAS) Architecture

### 2.1 What is SAS?
In the Windows operating system, `Ctrl + Alt + Delete` is formally designated as the **Secure Attention Sequence (SAS)**. It is a hardware-signaled sequence designed to guarantee that the user is communicating directly with the trusted operating system kernel, rather than an untrusted user-space program.

### 2.2 Kernel-Level Interception Pipeline
When keys are pressed on a physical or virtual keyboard, the input pipeline operates as follows:

```
[ Physical / USB Keyboard ]
             │
             ▼
   [ kbdclass.sys (Kernel Driver) ]
             │
             ▼
   [ win32k.sys / win32kbase.sys ] ─── Is SAS (Ctrl+Alt+Delete)?
             │                                     │
             │ NO                                  │ YES
             ▼                                     ▼
   [ WH_KEYBOARD_LL Hook Chain ]        [ Kernel SAS Handler ]
   (Input Locker Hook resides here)                │
             │                                     ▼
             ▼                          [ Winlogon.exe / LogonUI ]
   [ Target Application Queue ]          (Switches Desktop to Winlogon)
```

1. **Driver Level:** The keyboard hardware generates scan codes received by the kernel-mode port driver (`i8042prt.sys` or `kbdhid.sys`) and passed to the keyboard class driver (`kbdclass.sys`).
2. **Win32k Evaluation:** The kernel subsystem (`win32k.sys`) parses raw keystrokes. Before any user-mode hooks (`WH_KEYBOARD_LL`) are invoked, the kernel checks whether the keystrokes match `Ctrl + Alt + Delete`.
3. **Bypass of Hook Chain:** If SAS is detected, the kernel **immediately bypasses the entire user-mode hook chain**. No notification is sent to `WH_KEYBOARD_LL`.
4. **Winlogon Dispatch:** The kernel signals the Remote Procedure Call (RPC) channel dedicated to `Winlogon.exe` (running as `NT AUTHORITY\SYSTEM`), prompting an immediate desktop switch.

### 2.3 Threat Model & Security Rationale
Microsoft introduced SAS in Windows NT to defeat **Trojan Horse credential harvesting attacks**:
- Without kernel-level SAS guarantees, malicious software could display a fake Windows login dialog, prompt the user for credentials, and capture their password.
- Because only the genuine Windows kernel can respond to `Ctrl + Alt + Delete`, users are trained that pressing `Ctrl + Alt + Delete` ensures a legitimate, untampered Windows Security / Logon screen.
- Microsoft has deliberately refused to provide user-mode APIs to suppress SAS, treating any attempt to intercept SAS from user space as an adversarial security violation.

---

## 3. Desktop Isolation Boundaries (`WinSta0`)

Windows separates interactive graphical sessions using a hierarchy of Window Stations and Desktops:

```
Window Station: WinSta0 (Interactive)
├── Desktop: Default       <-- Media Servers (Resolume, WATCHOUT) & Input Locker Overlay
├── Desktop: Winlogon      <-- Windows Security, Ctrl+Alt+Del, UAC Secure Desktop
└── Desktop: Screensaver   <-- Legacy Windows screensaver
```

### 3.1 The `Default` Desktop
The `Default` desktop is where standard user applications run, including staging software (Resolume Arena, Dataton WATCHOUT, Disguise d3, grandMA onPC), digital audio workstations (Ableton Live, Pro Tools), and the Input Locker utility. Low-level hooks installed by the Input Locker operate within `Default`.

### 3.2 The `Winlogon` Desktop
When SAS (`Ctrl + Alt + Delete`) is triggered:
1. The Windows kernel switches the active display surface and input focus to the secure `Winlogon` desktop.
2. The `Default` desktop is suspended from receiving input.
3. Windows renders the Windows Security menu (`Lock`, `Switch user`, `Sign out`, `Task Manager`).
4. Any hooks installed on the `Default` desktop (including the Input Locker) become completely inactive while the system is on the `Winlogon` desktop.

### 3.3 User Interface Privilege Isolation (UIPI)
Windows enforces User Interface Privilege Isolation (UIPI) based on Mandatory Integrity Levels (Low, Medium, High, System):
- A process running at `Medium Integrity` (standard user) cannot intercept input directed to an application running at `High Integrity` (elevated Administrator).
- **Staging Requirement:** In professional AV environments, media servers and control tools are often executed with Administrator privileges. Therefore, the **Input Locker utility must also be launched as Administrator (High Integrity Level)** to ensure its hooks intercept all keyboard and mouse messages across all applications.

---

## 4. System Shortcuts Interceptability Matrix

While `Ctrl + Alt + Delete` cannot be intercepted in user mode, **the Input Locker successfully intercepts and swallows all other major Windows system shortcuts** during the Locked state:

| Shortcut | Function | Interceptable by Input Locker? | Swallowing Mechanics / Behavior |
|:---|:---|:---:|:---|
| **Ctrl + Alt + Delete** | Secure Attention Sequence (SAS) | **NO** | Kernel intercepts directly; switches to `Winlogon` desktop. Requires staging mitigation. |
| **Win + L** | Lock Workstation | **NO (Partial)** | Dispatched at shell level; can be suppressed via Group Policy / Registry. |
| **Alt + Tab** | Task Switcher | **YES** | Intercepted on `VK_MENU` + `VK_TAB`; swallowed before shell switcher appears. |
| **Alt + Esc** | Cycle Windows Directly | **YES** | Intercepted on `VK_MENU` + `VK_ESCAPE`; swallowed completely. |
| **Ctrl + Esc** | Open Start Menu | **YES** | Intercepted on `VK_CONTROL` + `VK_ESCAPE`; swallowed before Start menu opens. |
| **Ctrl + Shift + Esc** | Direct Task Manager Launch | **YES** | Intercepted on `VK_CONTROL` + `VK_SHIFT` + `VK_ESCAPE`; swallowed completely. |
| **Windows Key (`VK_LWIN`, `VK_RWIN`)** | Start Menu & Win+ Hotkeys | **YES** | Intercepted on Windows keycodes (`0x5B`, `0x5C`); swallowed completely. |
| **Alt + F4** | Close Active Window | **YES** | Intercepted on `VK_MENU` + `VK_F4`; swallowed; protects background rendering app from exit. |
| **F11** | Fullscreen Toggle / Lock Hotkey | **YES** | Swallowed in UNLOCKED state to protect media player, and swallowed in LOCKED state. |
| **Mouse Clicks & Movement** | Cursor Interaction | **YES** | Swallowed via `WH_MOUSE_LL` while cursor is confined to `(0, 0)` and hidden. |

---

## 5. AV Staging & Production Mitigations

In mission-critical live event staging (arena tours, corporate broadcasts, theatrical productions), an unexpected desktop switch or operator keystroke can take down LED video walls or front-of-house projection. 

Because `Ctrl + Alt + Delete` is enforced at the kernel level, production systems must implement layered defense mitigations.

### 5.1 Physical Security Mitigations (Recommended for Staging)

1. **Hardware Keyboard Disconnect / KVM Lockout:**
   - Use USB keyboard switches or KVMs with physical disable buttons at front-of-house (FOH) consoles. Once a show is live, disconnect or switch off the physical keyboard.
2. **Physical Keycap Covers / Lockout Blocks:**
   - In rack-mounted production servers, install physical key switch lockouts or 3D-printed acrylic covers over the `Delete`, `Escape`, and `Windows` keys.
3. **Dedicated Show-Control Hardware:**
   - Interface show commands exclusively via network protocols (OSC or TCP JSON via the Input Locker's remote control server) using Stream Decks, Companion, or grandMA macro buttons, keeping standard QWERTY keyboards locked inside the server flight case.

### 5.2 Operating System Policies (Windows Enterprise / Pro / IoT)

For dedicated media server appliances (WATCHOUT, Disguise, Resolume nodes), Windows provides administrative configurations to neutralize SAS:

#### Mitigation A: Windows Kiosk Mode / Assigned Access
Windows 10/11 Enterprise and IoT Enterprise support **Assigned Access**:
- Configures the operating system to run a single dedicated media server application without the standard Windows shell (`explorer.exe`).
- Under Assigned Access, the `Ctrl + Alt + Delete` screen is replaced with an administrative lock screen or suppressed entirely.

#### Mitigation B: Group Policy & Registry Tweaks

1. **Disable Task Manager via Registry:**
   Prevents users from accessing Task Manager even if `Winlogon` is reached:
   ```reg
   Windows Registry Editor Version 5.00

   [HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\System]
   "DisableTaskMgr"=dword:00000001
   ```

2. **Disable Lock Workstation (`Win + L`):**
   Prevents workstation locking from accidental `Win + L` presses:
   ```reg
   Windows Registry Editor Version 5.00

   [HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\System]
   "DisableLockWorkstation"=dword:00000001
   ```

3. **Disable Change Password & Sign Out:**
   Removes disruptive options from the Windows Security screen:
   ```reg
   Windows Registry Editor Version 5.00

   [HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\System]
   "DisableChangePassword"=dword:00000001

   [HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Policies\Explorer]
   "NoLogoff"=dword:00000001
   ```

4. **Group Policy Editor Configuration (`gpedit.msc`):**
   - Navigate to: `User Configuration -> Administrative Templates -> System -> Ctrl+Alt+Del Options`
   - Set **Remove Task Manager** to **Enabled**.
   - Set **Remove Lock Computer** to **Enabled**.
   - Set **Remove Change Password** to **Enabled**.
   - Set **Remove Logoff** to **Enabled**.

When all four policies are enabled, pressing `Ctrl + Alt + Delete` presents only a "Cancel" button, preventing any state modification to the playback computer.

---

## 6. Summary for AV Systems Engineers

| Category | Finding / Strategy |
|:---|:---|
| **Fundamental Limitation** | `Ctrl + Alt + Delete` is handled exclusively by `win32k.sys` and `Winlogon.exe`. No user-mode hook can intercept or suppress it. |
| **Input Locker Role** | Intercepts 100% of all standard keys, modifier combos, function keys (including `F11`), `Alt+Tab`, `Alt+F4`, `Ctrl+Shift+Esc`, and all mouse movement/clicks. |
| **Required Execution Level** | Must run as **Administrator** to prevent UIPI bypass from elevated media servers. |
| **Recommended Staging Posture** | Combine the Input Locker with physical keyboard covers or KVM lockout, and apply `DisableTaskMgr` and `DisableLockWorkstation` policies on dedicated staging servers. |

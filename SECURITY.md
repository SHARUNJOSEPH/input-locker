# Security Policy

## Supported Versions
Only the latest released version of Input Locker receives active security updates and vulnerability patches.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Security Architecture & Threat Model

Input Locker is designed specifically for live AV production environments (concerts, broadcast, theatre, corporate keynotes), where reliability, deterministic input suppression, and non-disruption of high-priority rendering processes (Watchout, Resolume, Notch, Unreal Engine, DAWs) are paramount.

### 1. Credential Security (NIST SP 800-63B & OWASP Compliant)
- **Zero Plaintext Storage**: Unlock passwords are never stored in plaintext on disk or in system registries.
- **Cryptographic Hashing**: Passwords are hashed using salted PBKDF2-HMAC-SHA256 with 100,000 iterations and a 16-byte cryptographically secure pseudorandom salt (secrets.token_hex(16)).
- **Constant-Time Verification**: Password candidate comparisons utilize secrets.compare_digest to prevent side-channel timing attacks.
- **In-Memory Masking**: The unlock dialog enforces bullet-masked input (•) and destroys in-memory references upon dialog dismissal.

### 2. OS-Level Hook Isolation & Boundary Controls
- **Low-Level Hooks**: Operates through WH_KEYBOARD_LL and WH_MOUSE_LL hooks via Win32 SetWindowsHookEx.
- **Restricted Keyboard Pass-Through**: When the password entry dialog is active, standard text characters route only to the topmost password input, while system task-switching primitives (Alt+Tab, Win Key, Alt+Esc, Ctrl+Esc, Ctrl+Shift+Esc) remain swallowed to prevent unauthorized background access.
- **Cursor Confinement**: During locked state, mouse movement is clamped to (0, 0) with ClipCursor. During password entry, mouse cursor confinement is dynamically resized strictly to the bounding box of the password dialog, preventing background click injection.
- **OS Hard Boundaries**: Ctrl+Alt+Delete and secure desktop elevation (UAC) are guarded at the Windows kernel security boundary (Winlogon / SAS). See docs/CAD_LIMITATIONS.md for full mitigation and kiosk hardening policies.

### 3. Network Remote Control Security
- **Local Loopback / Private Staging Subnets**: The OSC (UDP) and JSON (TCP) remote control listeners bind by default to internal AV network interfaces.
- **Sanitized Payload Handling**: Remote command parsers strictly reject unformatted or oversized payloads.

## Reporting a Vulnerability

If you discover a security vulnerability or bypass:
1. Do **NOT** file a public issue on GitHub.
2. Submit a report with detailed reproduction steps, Windows build number, and hardware configuration to the project maintainers.
3. You will receive an initial response within 48 hours, and critical security patches will be issued as hotfixes.

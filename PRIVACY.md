# Privacy Policy & Telemetry Commitment

**Effective Date**: September 2026  
**Applicability**: All releases of Input Locker

## Enterprise Zero-Telemetry Guarantee

Input Locker is built from the ground up to respect user confidentiality, operational security, and production privacy in mission-critical staging environments.

### 1. No Telemetry or Analytics
- **Zero Analytics**: Input Locker does **not** collect, store, or transmit telemetry, usage analytics, crash metrics, or diagnostic data.
- **Zero Identification**: No device IDs, MAC addresses, machine names, or user identities are gathered or logged.
- **No Keystroke Logging**: Keystrokes are intercepted exclusively in memory to evaluate the unlock hotkey or password entry. No keystrokes are ever logged, cached to disk, or transmitted over any network socket.

### 2. Offline-First & Network Behavior
- **100% Offline Capable**: Input Locker does not require an active internet connection to execute any core feature (input suppression, wallpaper rendering, cursor locking, password verification).
- **Update Checks**: If automatic update checking is enabled, the application contacts the public GitHub Releases endpoint via standard HTTPS GET. The only information sent is the standard User-Agent header (InputLocker/<version>). No personal, network, or hardware identifiers are transmitted. If the host machine is disconnected or offline, update checks terminate immediately and silently without retrying or delaying app performance.
- **Show Control Ports**: Optional OSC (UDP) and TCP command interfaces operate entirely within the local staging subnet or loopback interface (127.0.0.1). No outbound external calls are made.

### 3. Local Data Storage
- Configuration and settings are stored locally on the user machine in %APPDATA%\InputLocker\config.json.
- Unlock passwords are stored exclusively as non-reversible salted cryptographic hashes (PBKDF2-HMAC-SHA256).
- All configuration data remains strictly on the local filesystem and is never synchronized to cloud servers by Input Locker.

### 4. Enterprise & AV Show Compliance
Input Locker complies with strict data sovereignty and enterprise isolation requirements typical of live entertainment, government presentations, medical AV systems, and defense industry staging environments.

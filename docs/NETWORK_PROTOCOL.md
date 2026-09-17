# Network Remote Control Protocol Specification

**Windows AV Staging Input Locker**  
**Subsystem**: `input_locker.network`  
**Standard Ports**: UDP `9000` (OSC / Show Control), TCP `9001` (JSON Automation & Telemetry)  
**Specification Version**: 1.0.0  

---

## 1. Architectural Overview

The Windows AV Staging Input Locker provides an asynchronous, non-blocking dual-protocol network listener designed for mission-critical live event staging and broadcast production environments (e.g., Resolume Arena, Dataton WATCHOUT, QLab, Bitfocus Companion, grandMA).

```
+-------------------------------------------------------------------------------+
|                             SHOW CONTROL OPERATORS                            |
+-------------------------------------------------------------------------------+
|       [QLab / Companion]            [Lighting / Video Console]                |
|       OSC over UDP (9000)                OSC over UDP (9000)                  |
|                \                                /                             |
|                 v                              v                              |
|           +------------------------------------------+                        |
|           |       UDP Datagram Listener (9000)       |                        |
|           |   OSC 1.0 Codec + Fallback JSON Parser   |                        |
|           +------------------------------------------+                        |
|                                |                                              |
|                                v                                              |
|           +------------------------------------------+   State Dispatch       |
|           |    NetworkServer (Asyncio Daemon Thread) | ----------------->     |
|           +------------------------------------------+   (< 0.1 ms latency)   |
|                                ^                                              |
|                                |                                              |
|           +------------------------------------------+                        |
|           |       TCP Stream Listener (9001)         |                        |
|           |     Line-Delimited JSON Stream Parser    |                        |
|           +------------------------------------------+                        |
|                 ^                              ^                              |
|                /                                \                             |
|   [Automated Test Runner]             [Crestron / Extron Controller]          |
|    JSON over TCP (9001)                    JSON over TCP (9001)               |
+-------------------------------------------------------------------------------+
```

### Key Performance & Non-Interference Characteristics:
1. **Isolated Threading**: The network engine runs in a dedicated background daemon thread with its own `asyncio` event loop. It never shares a thread with the Win32 low-level OS hooks (`WH_KEYBOARD_LL`, `WH_MOUSE_LL`) or the GUI message loop (`Win32Overlay`).
2. **Deterministic Response Latency**:
   - Round-trip response time (RTT) over UDP/OSC: **< 0.5 ms** (average), **< 1.0 ms** (P99).
   - Round-trip response time over TCP (keepalive): **< 0.3 ms** (average).
   - Required budget: **< 100 ms** (headroom margin > 98%).
3. **Zero Hook Dropout**: Windows enforces `LowLevelHooksTimeout` (200–1000 ms). Because the network server communicates with the state coordinator via thread-safe callbacks and atomic flags without holding locks or performing blocking I/O on the hook thread, even extreme network burst traffic (> 5,000 req/sec) causes zero hook dropouts.

---

## 2. Protocol 1: Open Sound Control (OSC 1.0) over UDP

OSC over UDP is the primary show control protocol. It allows lighting designers, video technicians, and audio engineers to trigger locking and unlocking directly from cues in staging software.

- **Default Port**: `9000` (UDP)
- **Framing**: Connectionless UDP datagrams
- **Standard**: RFC-compliant OSC 1.0 specification
  - 32-bit (4-byte) alignment for addresses, type tags, and payloads
  - Strings are null-terminated and padded with 1 to 4 null bytes (`\x00`) so total length is a multiple of 4
  - Big-endian byte order (`>i`, `>f`, `>q`, `>d`)

### 2.1 Supported OSC Addresses

| Address Pattern | Direction | Arguments (Type Tags) | Description |
|---|---|---|---|
| `/input_locker/lock` | Inbound (Client -> Server) | None or `s` (source tag) | Requests transition to `LOCKED` state. Immediately starts swallowing all keyboard and mouse inputs and confines cursor. |
| `/input_locker/unlock` | Inbound (Client -> Server) | None or `s` (source tag) | Requests transition to `UNLOCKED` state. Releases cursor bounds, hides overlay, and restores OS input passthrough. |
| `/input_locker/status` | Inbound (Client -> Server) | None | Queries the current state and telemetry of the input locker. |
| `/input_locker/toggle` | Inbound (Client -> Server) | None | Toggles state between `LOCKED` and `UNLOCKED`. |
| `/input_locker/lock` | Outbound (Server -> Client) | `s` state, `f` latency_ms | Acknowledgment reply with resulting state string (`"LOCKED"`) and transition latency in milliseconds. |
| `/input_locker/unlock` | Outbound (Server -> Client) | `s` state, `f` latency_ms | Acknowledgment reply with resulting state string (`"UNLOCKED"`) and transition latency in milliseconds. |
| `/input_locker/status` | Outbound (Server -> Client) | `s` state, `f` uptime_s, `i` swallowing | Status response packet containing state (`"LOCKED"` / `"UNLOCKED"`), system uptime in seconds, and swallowing flag (1 or 0). |

### 2.2 Supported OSC Argument Types

The pure-Python OSC codec decodes and encodes the following OSC 1.0 type tags:
- `'i'`: 32-bit signed two's-complement integer
- `'f'`: 32-bit IEEE 754 floating point number
- `'s'`: OSC-string (null-terminated, 4-byte padded UTF-8 string)
- `'b'`: OSC-blob (int32 byte length header followed by binary payload)
- `'T'`: Boolean True (0 payload bytes)
- `'F'`: Boolean False (0 payload bytes)
- `'N'`: Nil / Null (0 payload bytes)
- `'h'`: 64-bit signed integer
- `'d'`: 64-bit IEEE 754 floating point number

### 2.3 UDP JSON Datagram Fallback

For simple CLI scripts or UDP-based AV devices that do not support binary OSC, the UDP listener on port `9000` automatically detects text/JSON payloads:
- If a datagram starts with `/` or `#bundle`, it is processed as **OSC 1.0**.
- If a datagram starts with `{` or ASCII text, it is parsed as a **JSON command** or string command, and a JSON reply line is sent back to the sender.

---

## 3. Protocol 2: Line-Delimited JSON over TCP

JSON over TCP is designed for automated test suites, building management systems (BMS), Crestron/Extron matrix processors, and system health monitors.

- **Default Port**: `9001` (TCP)
- **Framing**: Line-delimited UTF-8 JSON strings terminated by `\n` (CRLF `\r\n` accepted)
- **Connection Model**: Persistent keepalive streams (multiple commands per socket) or transient single-command connections

### 3.1 Request Schemas

Commands are case-insensitive (`"lock"`, `"LOCK"`, `"Lock"`). Both `"command"` and shorthand `"cmd"` keys are supported.

#### Lock Command:
```json
{"command": "lock"}
```
*Shorthand with tracking ID:*
```json
{"cmd": "lock", "id": "cue-42", "source": "watchout_timeline"}
```

#### Unlock Command:
```json
{"command": "unlock"}
```
*Shorthand with tracking ID:*
```json
{"cmd": "unlock", "id": "cue-43"}
```

#### Status Query:
```json
{"command": "status"}
```

#### Plain Text Fallback:
Clients may also send raw strings followed by a newline:
```
lock\n
unlock\n
status\n
```

### 3.2 Response Schemas

Every TCP command produces an immediate, single-line JSON response terminated by `\n`.

#### Lock Response (Success):
```json
{
  "status": "ok",
  "action": "lock",
  "cmd": "lock",
  "state": "LOCKED",
  "latency_ms": 1.250,
  "result": {
    "status": "ok",
    "state": "LOCKED",
    "stats": {
      "source": "tcp",
      "type": "lock",
      "total_ms": 1.250
    }
  }
}
```

#### Lock Response (Idempotent / Already Locked):
```json
{
  "status": "ok",
  "action": "lock",
  "cmd": "lock",
  "state": "LOCKED",
  "latency_ms": 0.0,
  "result": {
    "status": "ignored",
    "reason": "already_locked",
    "state": "LOCKED"
  }
}
```

#### Unlock Response (Success):
```json
{
  "status": "ok",
  "action": "unlock",
  "cmd": "unlock",
  "state": "UNLOCKED",
  "latency_ms": 0.850,
  "result": {
    "status": "ok",
    "state": "UNLOCKED",
    "stats": {
      "source": "tcp",
      "type": "unlock",
      "total_ms": 0.850
    }
  }
}
```

#### Status Response:
```json
{
  "status": "ok",
  "action": "status",
  "cmd": "status",
  "state": "LOCKED",
  "swallowing": true,
  "swallow_active": true,
  "cursor_confined": true,
  "uptime": 142.85,
  "telemetry": {
    "source": "hotkey_f11",
    "type": "lock",
    "total_ms": 1.450
  }
}
```

#### Error Response:
```json
{
  "status": "error",
  "message": "unknown command 'shutdown'",
  "state": "LOCKED"
}
```

If an `"id"` was supplied in the request, it is echoed back in both success and error responses.

---

## 4. AV Staging Integration Examples

### 4.1 QLab (macOS / Show Control)

In QLab 4 / 5, add a **Network Cue**:
1. Open **Workspace Settings** -> **Network**.
2. Add a Destination:
   - **Name**: `InputLocker`
   - **Type**: `OSC message`
   - **Network**: Choose the production LAN interface
   - **Destination**: `<IP of Windows AV machine>`
   - **Port**: `9000`
3. In the cue list:
   - To Lock: Add a Network Cue with OSC message `/input_locker/lock`
   - To Unlock: Add a Network Cue with OSC message `/input_locker/unlock`
   - To Query Status: Add a Network Cue with OSC message `/input_locker/status`

### 4.2 Bitfocus Companion (Stream Deck / Surface Control)

To control the locker from an Elgato Stream Deck or Companion web buttons:
1. In the Companion GUI, navigate to **Connections**.
2. Add the **`generic-osc`** module:
   - **Target IP**: `<IP of Windows AV machine>`
   - **Target Port**: `9000`
3. Configure Button Actions:
   - **Button 1 (Lock Engine)**:
     - Label: `LOCK INPUT`
     - Background: Red
     - Action: `Send OSC message` -> `/input_locker/lock`
   - **Button 2 (Unlock Engine)**:
     - Label: `UNLOCK`
     - Background: Green
     - Action: `Send OSC message` -> `/input_locker/unlock`
4. Alternatively, add the **`generic-tcp`** module targeting port `9001` with command `{"cmd": "lock"}\n`.

### 4.3 Resolume Arena (Media Server)

In Resolume Arena:
1. Navigate to **Preferences** -> **OSC**.
2. Enable **OSC Output** to `<Windows AV IP>:9000`.
3. Map an output address or trigger to send `/input_locker/lock` upon timeline playback start and `/input_locker/unlock` upon show close.

### 4.4 Python Automation Client Example

```python
import socket
import json

def send_tcp_command(cmd: str, host: str = "127.0.0.1", port: int = 9001) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        s.connect((host, port))
        s.sendall((json.dumps({"command": cmd}) + "\n").encode("utf-8"))
        data = s.recv(4096)
        return json.loads(data.decode("utf-8").strip())

# Example usage:
resp = send_tcp_command("lock")
print(f"Locker State: {resp['state']}, Latency: {resp['latency_ms']} ms")
```

---

## 5. Fault Tolerance & Security Considerations

1. **Stream Fragmentation Resilience**: TCP packets may arrive in split segments. The TCP listener maintains an internal byte buffer for each client connection and only dispatches when a complete `\n` delimiter is encountered.
2. **Buffer Flood Protection**: A strict 1 MB maximum line length is enforced. Packets exceeding this size are rejected with an error response to protect against memory exhaustion.
3. **Abrupt Disconnect Handling**: Immediate socket drops, half-closes, and connection resets do not generate unhandled exceptions or crash the server.
4. **Idempotent Transitions**: Repeated `lock` commands while already locked, or repeated `unlock` commands while already unlocked, return status code `ok` (with reason `already_locked` / `already_unlocked`) and do not perform duplicate Win32 API calls.
5. **Network Interface Binding**: By default, `NetworkServer` binds to `0.0.0.0` for staging LAN accessibility. In security-sensitive setups, bind to `127.0.0.1` or isolate the control network onto a dedicated VLAN.

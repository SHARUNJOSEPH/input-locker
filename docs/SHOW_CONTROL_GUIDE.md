# 🎛️ Input Locker: AV Show Control & Staging Integration Guide

Welcome to the definitive integration guide for controlling **Input Locker** in mission-critical live event, broadcast, and staging environments.

Input Locker allows front-of-house (FOH) engineers, broadcast operators, and show callers to freeze and isolate physical human interface devices (keyboards, trackballs, mice) without stopping or unfocusing media servers, DAWs, or visualization software.

---

## Table of Contents
1. [Architecture & Show Network Topology](#1-architecture--show-network-topology)
2. [OSC (Open Sound Control) Protocol Reference](#2-osc-open-sound-control-protocol-reference)
3. [TCP JSON Line-Delimited API Reference](#3-tcp-json-line-delimited-api-reference)
4. [Bitfocus Companion Integration (Stream Deck)](#4-bitfocus-companion-integration-stream-deck)
5. [Figure 53 QLab Integration](#5-figure-53-qlab-integration)
6. [Resolume Arena & Media Server Cueing](#6-resolume-arena--media-server-cueing)
7. [TouchDesigner & Custom Show Control](#7-touchdesigner--custom-show-control)
8. [Production Staging Best Practices](#8-production-staging-best-practices)

---

## 1. Architecture & Show Network Topology

Input Locker runs an asynchronous, non-blocking background dual-protocol listener that executes in sub-millisecond latencies (< 1 ms round-trip).

```
 ┌─────────────────────────────────────────────────────────┐
 │                Staging / Control Network                │
 └────────────────────────────┬────────────────────────────┘
                              │
         ┌────────────────────┼────────────────────┐
         │ (UDP 9000: OSC)    │ (TCP 9001: JSON)   │ (UDP/TCP)
         ▼                    ▼                    ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Bitfocus         │ │ Figure 53        │ │ Resolume Arena   │
│ Companion        │ │ QLab             │ │ or TouchDesigner │
└────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              ▼
        ┌───────────────────────────────────────────┐
        │  Windows Media Server / Workstation       │
        │  Input Locker Service (Dual Listener)     │
        │  • Low-level OS hook suppression          │
        │  • Non-activating glass overlay           │
        │  • Background rendering continues 60+ FPS │
        └───────────────────────────────────────────┘
```

### Network Binding Modes
- **Local Loopback Only (Default)**: Bounds exclusively to `127.0.0.1`. Recommended when QLab, Companion, or trigger scripts run on the same Windows host.
- **LAN / Staging Network Mode (`--bind-all`)**:
  Launch Input Locker with `--bind-all` (or check "Accept Remote Show Control" in settings) to bind to `0.0.0.0`, allowing remote consoles on the AV production VLAN to issue lock/unlock commands.

```powershell
# Launch with LAN remote show control enabled on custom ports
InputLocker.exe --bind-all --osc-port 9000 --tcp-port 9001
```

---

## 2. OSC (Open Sound Control) Protocol Reference

Input Locker implements strict **OSC 1.0** compliance over UDP. All packet strings, type tags, and payloads follow standard 32-bit (4-byte) boundary alignment.

- **Default Port**: `9000` (UDP)
- **Supported Encodings**: Atomic types (`s` string, `i` int32, `f` float32) and OSC Bundles (`#bundle`).

### Command Address Map

| OSC Address | Arguments | Behavior | Response Datagram |
| :--- | :--- | :--- | :--- |
| `/input_locker/lock` | *(None or optional float)* | Transitions to **LOCKED** state. Locks keyboard, traps & hides cursor, reveals pass-through glass overlay. | `/input_locker/lock "LOCKED" <latency_ms>` |
| `/input_locker/unlock` | *(None or optional float)* | Transitions to **UNLOCKED** state. Restores native OS mouse/keyboard input without focus loss. | `/input_locker/unlock "UNLOCKED" <latency_ms>` |
| `/input_locker/toggle` | *(None)* | Toggles between LOCKED and UNLOCKED states. | `/input_locker/toggle "<NEW_STATE>"` |
| `/input_locker/status` | *(None)* | Queries current operational health and state without modifying state. | `/input_locker/status "<STATE>" <is_swallowing:bool> <uptime_sec:float>` |

---

## 3. TCP JSON Line-Delimited API Reference

For automation scripts (Python, Node.js, PowerShell, Crestron, Extron, or Q-SYS), Input Locker provides a persistent line-delimited TCP socket.

- **Default Port**: `9001` (TCP)
- **Framing**: UTF-8 JSON object terminated by newline `\n`.

### Available Commands

#### 1. Lock Command
**Request:**
```json
{"command": "lock"}
```
*(Shorthand string also accepted: `"LOCK\n"`)*

**Response:**
```json
{"status": "ok", "state": "LOCKED", "latency_ms": 0.85, "timestamp": 1789803000.12}
```

#### 2. Unlock Command
**Request:**
```json
{"command": "unlock"}
```
*(Shorthand string also accepted: `"UNLOCK\n"`)*

**Response:**
```json
{"status": "ok", "state": "UNLOCKED", "latency_ms": 0.62, "timestamp": 1789803005.44}
```

#### 3. Status Query
**Request:**
```json
{"command": "status"}
```
*(Shorthand string also accepted: `"STATUS\n"`)*

**Response:**
```json
{
  "status": "ok",
  "state": "UNLOCKED",
  "is_locked": false,
  "is_swallowing": false,
  "uptime_seconds": 3840.15,
  "version": "0.1.0"
}
```

---

## 4. Bitfocus Companion Integration (Stream Deck)

Bitfocus Companion paired with an Elgato Stream Deck is the industry standard for front-of-house AV control.

### Method 1: Instant Import via Template Page
We provide a ready-to-import Companion page in [`integrations/companion/input_locker_companion_page.json`](../integrations/companion/input_locker_companion_page.json).
1. Open Bitfocus Companion Admin GUI (`http://localhost:8000`).
2. Go to **Pages** > **Import / Export**.
3. Choose **Import Page** and select `input_locker_companion_page.json`.

---

### Method 2: Manual Setup (Step-by-Step)

#### Step 1: Add the Generic OSC Connection
1. In Companion, navigate to **Connections**.
2. Search for and add **`Generic OSC`**.
3. Label it: `InputLocker`.
4. Configure Target Settings:
   - **Target IP**: IP address of the media server (or `127.0.0.1` if running locally).
   - **Target Port**: `9000`.

#### Step 2: Configure the "LOCK" Button
- **Button Text**: `INPUT\nLOCK\n🔒`
- **Text Size**: `14`
- **Background Color**: Dark Red (`#8B0000`)
- **Text Color**: White (`#FFFFFF`)
- **Press Action**:
  - Add action: `osc: Send message without arguments`
  - OSC Path: `/input_locker/lock`

#### Step 3: Configure the "UNLOCK" Button
- **Button Text**: `INPUT\nUNLOCK\n🔓`
- **Text Size**: `14`
- **Background Color**: Dark Green (`#006400`)
- **Text Color**: White (`#FFFFFF`)
- **Press Action**:
  - Add action: `osc: Send message without arguments`
  - OSC Path: `/input_locker/unlock`

#### Step 4: Configure a "TOGGLE" Latching Button
- **Button Text**: `LOCK\nTOGGLE`
- **Background Color**: Dark Gray (`#2A2A2A`)
- **Press Action**:
  - Add action: `osc: Send message without arguments`
  - OSC Path: `/input_locker/toggle`

---

## 5. Figure 53 QLab Integration

QLab controls theatre, corporate events, and live concert cues. Integrating Input Locker ensures stage technicians cannot accidentally bump keyboards during critical show sequences.

### Step 1: Set Up QLab OSC Network Patch
1. Open your QLab Workspace.
2. Open **Workspace Settings** (`Cmd + ,`) > **Network**.
3. In **Patch 1** (or next available patch):
   - **Name**: `Input Locker Host`
   - **Type**: `Address`
   - **Network**: Desired network interface (e.g. `Ethernet 1`)
   - **Destination**: IP of the Windows machine running Input Locker (e.g. `192.168.10.50`)
   - **Port**: `9000`

### Step 2: Create the "Pre-Show Lock" Cue
1. Insert a **Network Cue** into your main Cue List.
2. Label the cue: `LOCK WORKSTATION INPUTS`.
3. In the cue's **Settings** tab:
   - **Destination**: `Patch 1 (Input Locker Host)`
   - **Type**: `OSC message`
   - **OSC Message**: `/input_locker/lock`
4. Set pre-wait or trigger this cue right before "House Lights Down".

### Step 3: Create the "Post-Show Unlock" Cue
1. Insert a **Network Cue** at the end of the show or on a dedicated emergency safety list.
2. Label the cue: `UNLOCK WORKSTATION INPUTS`.
3. In the cue's **Settings** tab:
   - **Destination**: `Patch 1 (Input Locker Host)`
   - **Type**: `OSC message`
   - **OSC Message**: `/input_locker/unlock`

---

## 6. Resolume Arena & Media Server Cueing

Resolume Arena can broadcast OSC directly upon column launch or clip activation.

1. In Resolume, navigate to **Preferences** > **OSC**.
2. Under **OSC Output**, check **Enabled**.
3. Set **Output IP**: `127.0.0.1` (or media server IP).
4. Set **Output Port**: `9000`.
5. Map an OSC clip or deck trigger action to output address `/input_locker/lock`.

---

## 7. TouchDesigner & Custom Show Control

TouchDesigner operators can trigger locks using a simple `OSC Out CHOP` or Python script:

```python
# TouchDesigner Python scriptDAT example
osc_out = op('oscout1')
# Lock the machine
osc_out.sendOSC('/input_locker/lock', [])

# Or query status
osc_out.sendOSC('/input_locker/status', [])
```

---

## 8. Production Staging Best Practices

1. **Dedicated Show Control VLAN**: Always segregate OSC/UDP traffic from public or guest Wi-Fi to eliminate spurious UDP packet floods.
2. **Password Pinning for Manual Override**: Configure a strong password in `Input Locker Settings` (`Ctrl + Shift + P`). If network connectivity is severed during a show, operators can still manually unlock using `Ctrl + Alt + Shift + U` and entering the password.
3. **Lock on Launch for Fixed Kiosks**: If running an unattended interactive museum exhibit or lobby kiosk, enable `--lock-on-launch` in your Windows Startup shortcut.
4. **Heartbeat Monitoring**: Send `/input_locker/status` every 5 seconds from Companion or monitoring scripts. If no reply is received within 2 seconds, raise an alert on your control surface.

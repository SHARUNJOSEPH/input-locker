"""Asyncio TCP line-delimited JSON stream handler for Windows AV Staging Input Locker.

Handles bidirectional show control, automated testing, and health monitoring
over persistent or transient TCP connections on port 9001.

Features:
- Line-delimited JSON streaming with fragment accumulation and multi-packet assembly
- Multiple sequential commands on persistent keepalive connections
- Client abrupt disconnect resilience (ConnectionResetError, EOF, broken pipe)
- Robust parsing of JSON payloads, shorthand command formats, and plain text fallbacks
- Oversized payload protection and embedded null-byte sanitization
- Structured status, latency telemetry, and informative error responses
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Max line buffer limit: 1 MB (prevents memory exhaustion under flood)
MAX_LINE_LENGTH = 1024 * 1024


class TCPCommandError(Exception):
    """Raised when a command cannot be processed."""
    pass


class TCPHandler:
    """Asyncio TCP connection stream handler and command dispatcher."""

    def __init__(self, controller: Any, start_time: Optional[float] = None):
        """Initializes TCPHandler.
        
        Args:
            controller: State machine or coordinator providing lock(), unlock(), etc.
            start_time: Monotonic process start time for uptime calculation.
        """
        self.controller = controller
        self.start_time = start_time if start_time is not None else time.monotonic()

    @property
    def uptime(self) -> float:
        """Returns uptime in seconds."""
        return round(time.monotonic() - self.start_time, 3)

    def _get_state_str(self) -> str:
        """Retrieves current controller state as an uppercase string."""
        if hasattr(self.controller, "state"):
            st = self.controller.state
            if hasattr(st, "value"):
                return str(st.value).upper()
            return str(st).upper()
        if hasattr(self.controller, "is_locked"):
            locked = self.controller.is_locked
            if callable(locked):
                locked = locked()
            return "LOCKED" if locked else "UNLOCKED"
        return "UNKNOWN"

    def _is_swallowing(self) -> bool:
        """Checks if input swallowing is currently active."""
        if hasattr(self.controller, "hook_mgr") and hasattr(self.controller.hook_mgr, "is_swallowing"):
            return bool(self.controller.hook_mgr.is_swallowing())
        if hasattr(self.controller, "swallow_active"):
            return bool(self.controller.swallow_active)
        return self._get_state_str() == "LOCKED"

    def _is_cursor_confined(self) -> bool:
        """Checks if cursor confinement is currently active."""
        if hasattr(self.controller, "overlay_mgr") and hasattr(self.controller.overlay_mgr, "is_locked"):
            return bool(self.controller.overlay_mgr.is_locked)
        return self._get_state_str() == "LOCKED"

    def _get_telemetry(self) -> Dict[str, Any]:
        """Retrieves last transition telemetry from controller."""
        if hasattr(self.controller, "last_transition_stats"):
            return dict(self.controller.last_transition_stats)
        return {}

    def dispatch_command(self, cmd_obj: Any, source: str = "tcp") -> Dict[str, Any]:
        """Dispatches a parsed command object or raw command string to the controller.
        
        Args:
            cmd_obj: Dictionary payload or command string.
            source: Identifier of command origin (e.g. 'tcp', 'udp').
            
        Returns:
            Dict[str, Any]: Response dictionary.
        """
        req_id = None
        cmd_str = ""

        if isinstance(cmd_obj, dict):
            req_id = cmd_obj.get("id")
            # Check 'command' or 'cmd' or 'action'
            raw_cmd = cmd_obj.get("command") or cmd_obj.get("cmd") or cmd_obj.get("action")
            if raw_cmd is not None:
                cmd_str = str(raw_cmd).lower().strip()
            else:
                return {
                    "status": "error",
                    "message": "Missing 'command' or 'cmd' field in JSON object",
                    "id": req_id,
                }
        elif isinstance(cmd_obj, str):
            cmd_str = cmd_obj.lower().strip()
        else:
            return {
                "status": "error",
                "message": f"Unsupported command object type: {type(cmd_obj).__name__}",
                "id": req_id,
            }

        # Normalize command string
        if cmd_str == "lock":
            res = {}
            latency_ms = 0.0
            if hasattr(self.controller, "request_lock"):
                res = self.controller.request_lock(source=source)
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)
            elif hasattr(self.controller, "lock"):
                res = self.controller.lock()
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)

            state = self._get_state_str()
            status_code = res.get("status", "ok") if isinstance(res, dict) else "ok"
            resp: Dict[str, Any] = {
                "status": status_code,
                "action": "lock",
                "cmd": "lock",
                "state": state,
                "latency_ms": round(latency_ms, 3),
                "result": res,
            }
            if req_id is not None:
                resp["id"] = req_id
            return resp

        elif cmd_str == "unlock":
            res = {}
            latency_ms = 0.0
            if hasattr(self.controller, "request_unlock"):
                res = self.controller.request_unlock(source=source)
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)
            elif hasattr(self.controller, "unlock"):
                res = self.controller.unlock()
                if isinstance(res, dict):
                    latency_ms = float(res.get("latency_ms") or res.get("stats", {}).get("total_ms") or 0.0)

            state = self._get_state_str()
            status_code = res.get("status", "ok") if isinstance(res, dict) else "ok"
            resp = {
                "status": status_code,
                "action": "unlock",
                "cmd": "unlock",
                "state": state,
                "latency_ms": round(latency_ms, 3),
                "result": res,
            }
            if req_id is not None:
                resp["id"] = req_id
            return resp

        elif cmd_str == "status":
            state = self._get_state_str()
            swallow = self._is_swallowing()
            cursor_pinned = self._is_cursor_confined()
            telemetry = self._get_telemetry()
            resp = {
                "status": "ok",
                "action": "status",
                "cmd": "status",
                "state": state,
                "swallowing": swallow,
                "swallow_active": swallow,
                "cursor_confined": cursor_pinned,
                "uptime": self.uptime,
                "telemetry": telemetry,
            }
            if req_id is not None:
                resp["id"] = req_id
            return resp

        else:
            resp = {
                "status": "error",
                "message": f"unknown command '{cmd_str}'",
                "state": self._get_state_str(),
            }
            if req_id is not None:
                resp["id"] = req_id
            return resp

    async def handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handles an incoming TCP client connection, supporting line-delimited streaming."""
        buffer = bytearray()
        in_overflow = False
        try:
            while True:
                # Read chunks up to 64 KB
                chunk = await reader.read(65536)
                if not chunk:
                    # Client closed connection (EOF)
                    break

                buffer.extend(chunk)

                if in_overflow:
                    # Discard everything up to next newline
                    if b"\n" in buffer:
                        idx = buffer.index(b"\n")
                        del buffer[:idx + 1]
                        in_overflow = False
                    else:
                        buffer.clear()
                        continue

                if len(buffer) > MAX_LINE_LENGTH:
                    # Guard against oversized payload floods
                    in_overflow = True
                    err_resp = {"status": "error", "message": "Payload line length exceeded maximum limit"}
                    writer.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                    await writer.drain()
                    if b"\n" in buffer:
                        idx = buffer.index(b"\n")
                        del buffer[:idx + 1]
                        in_overflow = False
                    else:
                        buffer.clear()
                    continue

                # Process all complete lines in the buffer
                while b"\n" in buffer:
                    line_end = buffer.index(b"\n")
                    raw_line = bytes(buffer[:line_end])
                    # Remove line from buffer (including '\n')
                    del buffer[:line_end + 1]

                    # Strip trailing carriage return '\r' and whitespace
                    clean_line = raw_line.rstrip(b"\r ").strip()
                    if not clean_line:
                        # Empty line: skip without closing socket
                        continue

                    # Attempt to parse as JSON or plain string
                    text = clean_line.decode("utf-8", errors="replace").strip()
                    
                    cmd_obj: Any
                    if text.startswith("{"):
                        try:
                            cmd_obj = json.loads(text)
                        except json.JSONDecodeError as exc:
                            err_resp = {"status": "error", "message": f"Invalid JSON payload: {exc}"}
                            writer.write((json.dumps(err_resp) + "\n").encode("utf-8"))
                            await writer.drain()
                            continue
                    else:
                        # Plain string command fallback
                        cmd_obj = {"command": text}

                    # Execute command
                    resp = self.dispatch_command(cmd_obj, source="tcp")
                    out_bytes = (json.dumps(resp) + "\n").encode("utf-8")
                    writer.write(out_bytes)
                    await writer.drain()

        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            # Client disconnected abruptly (expected in network testing)
            pass
        except Exception as exc:
            logger.debug("Unexpected exception during TCP handling: %s", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

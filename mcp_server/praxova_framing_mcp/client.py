"""Synchronous JSON-RPC client for the Praxova Framing in-Blender bridge.

Each MCP tool call opens a fresh BridgeClient, makes one RPC, and closes.
Stateless and robust to bridge restarts.
"""

from __future__ import annotations

import json
import socket
from typing import Any


class BridgeUnavailableError(RuntimeError):
    """Bridge socket is unreachable: Blender not running, or bridge not started."""


class BridgeRPCError(RuntimeError):
    """Bridge returned a JSON-RPC error response.

    The original code/message/data are preserved as attributes so callers
    can map specific bridge-side errors to MCP error responses with
    actionable detail (e.g. valid lengths for a wrong length_ft).
    """

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        full = message
        if data:
            full = f"{message} (data: {data})"
        super().__init__(full)
        self.code = code
        self.message = message
        self.data = data


class BridgeClient:
    """One short-lived TCP connection to the Praxova Framing bridge.

    Use as a context manager. Not thread-safe; open one per call/thread.

    Wire protocol matches server/bridge.py: newline-delimited JSON-RPC 2.0,
    one request and one response per line, UTF-8.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9876,
        connect_timeout: float = 5.0,
        read_timeout: float = 60.0,
    ) -> None:
        try:
            self.sock = socket.create_connection(
                (host, port), timeout=connect_timeout,
            )
        except OSError as e:
            raise BridgeUnavailableError(
                f"Could not connect to {host}:{port}: {e}"
            ) from e
        self.sock.settimeout(read_timeout)
        self._buf = b""
        self._next_id = 0

    def __enter__(self) -> "BridgeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass

    def call(self, method: str, params: dict | None = None) -> Any:
        """Send one request, block until the matching response arrives."""
        self._next_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        try:
            self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))
        except OSError as e:
            raise BridgeUnavailableError(f"Send failed: {e}") from e

        # Read until we get a complete line. The bridge always sends
        # exactly one response line per request, so this terminates as
        # soon as we see a newline.
        while b"\n" not in self._buf:
            try:
                chunk = self.sock.recv(4096)
            except OSError as e:
                raise BridgeUnavailableError(f"Recv failed: {e}") from e
            if not chunk:
                raise BridgeUnavailableError(
                    "Bridge closed connection unexpectedly"
                )
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)

        try:
            resp = json.loads(line.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise BridgeUnavailableError(
                f"Bridge sent invalid response: {e}"
            ) from e

        if "error" in resp:
            err = resp["error"]
            raise BridgeRPCError(
                code=err.get("code", -32603),
                message=err.get("message", "Unknown error"),
                data=err.get("data"),
            )
        return resp.get("result")

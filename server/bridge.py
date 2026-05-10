"""TCP JSON-RPC bridge running inside Blender.

A background listener thread accepts connections from the external MCP
server process; per-connection threads parse newline-delimited JSON-RPC 2.0
requests and dispatch each one onto Blender's main thread via
bpy.app.timers.register so that all bpy mutation is single-threaded.

This module owns the socket, the threads, and the wire protocol. Method
implementations live in handlers.py - the bridge is purely transport.

Wire protocol
-------------
- TCP, default 127.0.0.1:9876.
- Request:  {"jsonrpc":"2.0","method":"...","params":{...},"id":<any>}\n
- Response: {"jsonrpc":"2.0","id":<same>,"result":{...}}\n
            {"jsonrpc":"2.0","id":<same>,"error":{"code":N,"message":"..."}}\n
- One JSON object per line. UTF-8.

Threading
---------
N+2 threads when running:
  - Blender main thread (runs all bpy work via timer callbacks).
  - 1 listener thread (blocks on accept()).
  - 1 connection thread per active client connection.

All bpy access happens on the main thread. Connection threads block on a
queue.Queue waiting for the timer callback to publish a result.
"""

from __future__ import annotations

import json
import queue
import socket
import threading
import traceback
from typing import Any, Callable

import bpy

from . import handlers


# ---------------------------------------------------------------------------
# JSON-RPC error codes
# ---------------------------------------------------------------------------

# Standard JSON-RPC 2.0 codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# App-defined codes must live in [-32000, -32099]. See handlers.py for the
# specific app codes and their meanings.


class RPCError(Exception):
    """Raised by handlers to surface a structured JSON-RPC error response."""

    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


# ---------------------------------------------------------------------------
# Module-level bridge state
# ---------------------------------------------------------------------------

class _BridgeState:
    """Runtime state for the bridge. Module-level singleton.

    Kept off the Scene PropertyGroup intentionally: bridge running-state is
    transient process state and must NOT persist with the .blend file.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.running: bool = False
        self.host: str = "127.0.0.1"
        self.port: int = 0
        self.listen_sock: socket.socket | None = None
        self.listen_thread: threading.Thread | None = None
        self.connections: list[socket.socket] = []


_state = _BridgeState()


def is_running() -> bool:
    return _state.running


def get_port() -> int:
    return _state.port


def get_host() -> str:
    return _state.host


# ---------------------------------------------------------------------------
# Main-thread dispatch
# ---------------------------------------------------------------------------

# Cap on any single handler invocation. Handlers are scene mutations and
# should be near-instant; if one wedges (modal popup, deadlock) we don't
# want connection threads to leak forever.
HANDLER_TIMEOUT_S = 30.0


def _run_on_main_thread(fn: Callable[[], Any]) -> Any:
    """Schedule fn on Blender's main thread, block until it returns.

    Re-raises whatever the handler raised. Maps a wall-clock timeout to a
    -32603 internal error.
    """
    result_q: queue.Queue = queue.Queue(maxsize=1)

    def _timer_cb():
        try:
            result_q.put(("ok", fn()))
        except RPCError as e:
            result_q.put(("rpc_err", e))
        except Exception as e:  # noqa: BLE001 - we want everything
            result_q.put(("err", e, traceback.format_exc()))
        return None  # don't repeat

    bpy.app.timers.register(_timer_cb, first_interval=0.0)

    try:
        item = result_q.get(timeout=HANDLER_TIMEOUT_S)
    except queue.Empty:
        raise RPCError(
            INTERNAL_ERROR,
            f"Handler did not complete within {HANDLER_TIMEOUT_S:g}s",
        )

    kind = item[0]
    if kind == "ok":
        return item[1]
    if kind == "rpc_err":
        raise item[1]
    # Unhandled exception inside the handler.
    _, exc, tb = item
    raise RPCError(
        INTERNAL_ERROR,
        f"{type(exc).__name__}: {exc}",
        data={"traceback": tb},
    )


# ---------------------------------------------------------------------------
# JSON-RPC framing
# ---------------------------------------------------------------------------

def _make_response(request_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _make_error(request_id: Any, code: int, message: str, data: Any = None) -> dict:
    err: dict = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": err}


def _process_request(raw: str) -> dict:
    """Parse one JSON-RPC request line and return the response dict."""
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as e:
        return _make_error(None, PARSE_ERROR, f"Invalid JSON: {e}")

    if not isinstance(msg, dict):
        return _make_error(None, INVALID_REQUEST, "Request must be a JSON object")

    request_id = msg.get("id")

    if msg.get("jsonrpc") != "2.0":
        return _make_error(
            request_id, INVALID_REQUEST,
            'Missing or wrong "jsonrpc": expected "2.0"',
        )

    method = msg.get("method")
    if not isinstance(method, str):
        return _make_error(request_id, INVALID_REQUEST, '"method" must be a string')

    params = msg.get("params", {})
    if not isinstance(params, dict):
        return _make_error(request_id, INVALID_PARAMS, '"params" must be an object')

    handler = handlers.METHODS.get(method)
    if handler is None:
        return _make_error(
            request_id, METHOD_NOT_FOUND,
            f"Unknown method: {method!r}",
            data={"available_methods": sorted(handlers.METHODS.keys())},
        )

    try:
        result = _run_on_main_thread(lambda: handler(params))
    except RPCError as e:
        return _make_error(request_id, e.code, e.message, e.data)

    return _make_response(request_id, result)


# ---------------------------------------------------------------------------
# Connection handling
# ---------------------------------------------------------------------------

def _serve_connection(conn: socket.socket, addr) -> None:
    """Read newline-delimited JSON-RPC requests, write responses, until EOF."""
    conn.settimeout(None)
    buf = b""

    with _state.lock:
        _state.connections.append(conn)

    try:
        with conn:
            while True:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        text = line.decode("utf-8")
                        resp = _process_request(text)
                    except UnicodeDecodeError:
                        resp = _make_error(None, PARSE_ERROR, "Request must be UTF-8")
                    payload = (json.dumps(resp) + "\n").encode("utf-8")
                    try:
                        conn.sendall(payload)
                    except OSError:
                        return
    finally:
        with _state.lock:
            if conn in _state.connections:
                _state.connections.remove(conn)


def _accept_loop(listen_sock: socket.socket) -> None:
    """Listener-thread entry point. Accept connections until the socket closes."""
    while _state.running:
        try:
            conn, addr = listen_sock.accept()
        except OSError:
            # stop() closed the listening socket. Normal shutdown.
            break
        # One thread per connection. All handlers serialize through the
        # main-thread timer regardless, so concurrent connections cannot
        # race on bpy state - they just queue up at the dispatch boundary.
        threading.Thread(
            target=_serve_connection,
            args=(conn, addr),
            name=f"praxova-bridge-conn-{addr[0]}:{addr[1]}",
            daemon=True,
        ).start()


# ---------------------------------------------------------------------------
# Public start/stop API
# ---------------------------------------------------------------------------

class BridgeAlreadyRunning(RuntimeError):
    pass


def start(host: str = "127.0.0.1", port: int = 9876) -> tuple[str, int]:
    """Start the bridge listener. Returns (host, actual_port).

    Raises BridgeAlreadyRunning if already up. Raises OSError if bind fails.
    """
    with _state.lock:
        if _state.running:
            raise BridgeAlreadyRunning(
                f"Bridge already running on {_state.host}:{_state.port}"
            )

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # SO_REUSEADDR so a quick restart isn't blocked by TIME_WAIT.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(8)
        except OSError:
            sock.close()
            raise

        actual_host, actual_port = sock.getsockname()
        _state.listen_sock = sock
        _state.host = actual_host
        _state.port = actual_port
        _state.running = True

        t = threading.Thread(
            target=_accept_loop,
            args=(sock,),
            name="praxova-bridge-listener",
            daemon=True,
        )
        _state.listen_thread = t
        t.start()

    return actual_host, actual_port


def stop() -> None:
    """Stop the bridge. Idempotent.

    Closes the listening socket (which causes accept() to raise and the
    listener thread to exit), then closes any in-flight client connections.
    """
    with _state.lock:
        if not _state.running:
            return
        _state.running = False
        sock = _state.listen_sock
        _state.listen_sock = None
        connections = list(_state.connections)
        _state.connections.clear()
        _state.host = "127.0.0.1"
        _state.port = 0

    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass

    for conn in connections:
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            conn.close()
        except OSError:
            pass

    # Don't join the listener thread: it's a daemon that exits as soon as
    # accept() unblocks. Joining could deadlock if stop() were ever invoked
    # from inside a handler (which it shouldn't be, but defensiveness here
    # is cheap).
    _state.listen_thread = None

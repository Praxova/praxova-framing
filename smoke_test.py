"""Smoke-test client for the Praxova Framing bridge.

Run from any Python (NOT inside Blender). Assumes the bridge is running
on 127.0.0.1:9876 with a fresh empty scene.

    python smoke_test.py
    python smoke_test.py --port 9876

Exits non-zero on any unexpected response.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any


class BridgeClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 9876,
                 timeout: float = 30.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        self._next_id = 0

    def close(self) -> None:
        self.sock.close()

    def call(self, method: str, params: dict | None = None) -> Any:
        self._next_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id,
            "method": method,
            "params": params or {},
        }
        self.sock.sendall((json.dumps(req) + "\n").encode("utf-8"))

        while b"\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("Bridge closed connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        resp = json.loads(line.decode("utf-8"))
        if "error" in resp:
            raise RuntimeError(f"RPC error: {resp['error']}")
        return resp["result"]


def run(host: str, port: int) -> int:
    print(f"Connecting to bridge at {host}:{port}...")
    cli = BridgeClient(host, port)

    try:
        print("\n[1] ping")
        r = cli.call("ping")
        print(f"  -> {r}")
        assert r["ok"] is True

        print("\n[2] get_scene_info")
        r = cli.call("get_scene_info")
        print(f"  -> {r}")
        before_count = r["object_count"]

        print("\n[3] list_materials (truncated)")
        r = cli.call("list_materials")
        print(f"  -> lumber types: {sorted(r['lumber_types'].keys())}")
        print(f"  -> sheet sizes: {sorted(r['sheet_sizes'].keys())}")

        print("\n[4] add_lumber 2x4 x8 vertical at origin")
        r = cli.call("add_lumber", {
            "nominal": "2x4",
            "length_ft": 8,
            "orientation": "VERTICAL",
            "location_m": [0.0, 0.0, 0.0],
        })
        print(f"  -> {r}")
        first_stud = r["name"]
        assert r["category"] == "LUMBER"
        assert r["label"] == "2x4x8 V"

        print("\n[5] duplicate_oc 4x at 16\" right")
        r = cli.call("duplicate_oc", {
            "target_name": first_stud,
            "spacing_in": 16.0,
            "count": 4,
            "direction": "RIGHT",
        })
        print(f"  -> {r}")
        assert len(r["new_objects"]) == 4

        print("\n[6] add_sheet 1/2\" PLY 4x8 horizontal at z=2.5m")
        r = cli.call("add_sheet", {
            "material": "PLYWOOD",
            "thickness": "1/2",
            "size": "4x8",
            "orientation": "HORIZONTAL",
            "location_m": [0.0, 0.0, 2.5],
        })
        print(f"  -> {r}")
        assert r["category"] == "SHEET"

        print("\n[7] list_objects (praxova only)")
        r = cli.call("list_objects")
        print(f"  -> {r['count']} tagged objects")
        assert r["count"] == 6  # 1 stud + 4 dupes + 1 sheet

        print("\n[8] generate_cutlist")
        r = cli.call("generate_cutlist")
        print("  -> cutlist body:")
        for line in r["text"].splitlines():
            print(f"     {line}")

        print("\n[9] error path: unknown lumber")
        try:
            cli.call("add_lumber", {"nominal": "2x5", "length_ft": 8})
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")

        print("\n[10] error path: bad method")
        try:
            cli.call("does_not_exist")
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")

        print("\nAll checks passed.")
        return 0
    finally:
        cli.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    args = ap.parse_args()
    try:
        return run(args.host, args.port)
    except AssertionError as e:
        print(f"ASSERTION FAILED: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

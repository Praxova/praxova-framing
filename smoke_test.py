"""Smoke-test client for the Praxova Framing bridge.

Run from any Python (NOT inside Blender). Assumes the bridge is running
on 127.0.0.1:9876 with a fresh empty scene.

    python smoke_test.py
    python smoke_test.py --port 9876

Exits non-zero on any unexpected response.

Covers the full v0.3.4 RPC surface end-to-end: ping (with addon_version
and method_count assertions), scene info, material catalog, lumber /
sheet / panel placement, on-center duplication, edge-to-edge fill,
cut-list generation (verifying all three sections appear), and three
error paths including the LUMBER refusal for duplicate_e2e.
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
        # v0.3.4: ping reports addon_version and method_count. Strict
        # assertion here catches version drift between the addon and
        # the test - exactly when a stale build is loaded in Blender.
        assert r["addon_version"] == "0.3.4", (
            f"expected addon_version 0.3.4, got {r['addon_version']!r}"
        )
        assert r["method_count"] == 11, (
            f"expected 11 methods, got {r['method_count']}"
        )

        print("\n[2] get_scene_info")
        r = cli.call("get_scene_info")
        print(f"  -> {r}")

        print("\n[3] list_materials (truncated)")
        r = cli.call("list_materials")
        print(f"  -> lumber types: {sorted(r['lumber_types'].keys())}")
        print(f"  -> sheet sizes:  {sorted(r['sheet_sizes'].keys())}")
        print(f"  -> panel sizes:  {sorted(r['panel_sizes'].keys())}")
        # v0.3.2: panel keys should be present.
        assert "panel_sizes" in r, "list_materials missing panel_sizes"
        assert "panel_materials" in r, "list_materials missing panel_materials"
        assert "36x8" in r["panel_sizes"]

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

        print("\n[7] add_panel 36\" Metal x 8 vertical at y=2m")
        r = cli.call("add_panel", {
            "material": "METAL",
            "size": "36x8",
            "orientation": "VERTICAL",
            "location_m": [0.0, 2.0, 0.0],
        })
        print(f"  -> {r}")
        panel_name = r["name"]
        assert r["category"] == "PANEL"
        assert r["label"] == '36" Metal x 8 V'
        # _serialize_object should now expose panel-specific fields, not the
        # empty sheet_* fields it used to leak in pre-v0.3.2 builds.
        assert r.get("panel_material") == "METAL"
        assert r.get("panel_size_key") == "36x8"
        assert "sheet_material" not in r, (
            "panel object leaked sheet_material - _serialize_object regressed"
        )

        print("\n[8] duplicate_e2e 3x forward on the metal panel")
        # v0.3.4: bridge parity for the Fill operator. Spacing is the
        # source's own width (36" for this panel) - no spacing_in
        # parameter, by design.
        r = cli.call("duplicate_e2e", {
            "target_name": panel_name,
            "count": 3,
            "direction": "FORWARD",
        })
        print(f"  -> {r}")
        assert r["source"] == panel_name
        assert r["width_in"] == 36.0, (
            f"expected width_in 36.0 for 36\" panel, got {r['width_in']}"
        )
        assert r["count"] == 3
        assert r["direction"] == "FORWARD"
        assert len(r["new_objects"]) == 3

        print("\n[9] list_objects (praxova only)")
        r = cli.call("list_objects")
        print(f"  -> {r['count']} tagged objects")
        # 1 stud + 4 OC dupes + 1 sheet + 1 panel + 3 fill dupes = 10
        assert r["count"] == 10

        print("\n[10] generate_cutlist")
        r = cli.call("generate_cutlist")
        print("  -> cutlist body:")
        for line in r["text"].splitlines():
            print(f"     {line}")
        # All three sections should appear when all three categories
        # are populated.
        assert "LUMBER" in r["text"]
        assert "SHEETS" in r["text"]
        assert "PANELS" in r["text"]
        # The fill operator should have brought the panel count from 1 to 4.
        # Format from ops_cutlist: "  <qty>  x  <label>" with the label
        # at the end. Look for the count line for the panel label.
        panel_line = next(
            (line for line in r["text"].splitlines()
             if '36" Metal x 8 V' in line),
            None,
        )
        assert panel_line is not None, "panel line missing from cut list"
        assert " 4 " in panel_line or "4  x" in panel_line, (
            f"expected 4 panels in cut list, got line: {panel_line!r}"
        )

        print("\n[11] error path: unknown lumber")
        try:
            cli.call("add_lumber", {"nominal": "2x5", "length_ft": 8})
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")

        print("\n[12] error path: duplicate_e2e on lumber (should refuse)")
        # The LUMBER refusal is enforced in the bridge handler so the
        # error carries a clean INVALID_PARAMS code instead of the
        # operator's APP_OPERATOR_FAILED.
        try:
            cli.call("duplicate_e2e", {
                "target_name": first_stud,
                "count": 2,
            })
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")
            err_text = str(e)
            assert "-32602" in err_text or "INVALID_PARAMS" in err_text, (
                f"expected INVALID_PARAMS code, got: {err_text!r}"
            )
            assert "lumber" in err_text.lower(), (
                f"expected error to mention lumber, got: {err_text!r}"
            )

        print("\n[13] error path: bad method")
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

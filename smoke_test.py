"""Smoke-test client for the Praxova Framing bridge.

Run from any Python (NOT inside Blender). Assumes the bridge is running
on 127.0.0.1:9876 with a fresh empty scene.

    python smoke_test.py
    python smoke_test.py --port 9876

Exits non-zero on any unexpected response.

Covers the full v0.6.1 RPC surface end-to-end (14 methods): ping (with
addon_version and method_count assertions), scene info, material
catalog, lumber / sheet / panel placement, on-center duplication,
edge-to-edge fill, wall framing with optional door/window openings
(v0.5.1 — bridge parity for the v0.5 UI), Building + Level container
creation and wall framing under a Level with in-place re-framing
(v0.6.1 — partial bridge parity for v0.6, completing the containers +
frame_wall extension; joints + frame_building + list_* methods land
in v0.6.2), cut-list generation (verifying three sections and the
'cut to N"' annotations for frame_wall regular studs and the v0.5
opening pieces — jacks, header members, and cripples), and three
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
        # v0.4.0: version bumped to 0.4.0. v0.4.1: method_count 11 -> 12
        # for the new frame_wall handler; addon_version 0.4.0 -> 0.4.1.
        # v0.5.0: addon_version 0.4.1 -> 0.5.0 for the door/window
        # openings UI; method_count stays 12. v0.5.1: addon_version
        # 0.5.0 -> 0.5.1 for bridge parity (frame_wall handler gains
        # the openings parameter); method_count stays 12. v0.6.0:
        # addon_version 0.5.1 -> 0.6.0 for multi-wall coordination;
        # UI-only cycle so method_count stays 12. v0.6.1: method_count
        # 12 -> 14 for add_building + add_level handlers (the
        # container half of v0.6's bridge parity — joints + the
        # frame_building orchestrator + list_* methods land in v0.6.2,
        # which will push method_count further); addon_version
        # 0.6.0 -> 0.6.1.
        assert r["addon_version"] == "0.6.1", (
            f"expected addon_version 0.6.1, got {r['addon_version']!r}"
        )
        assert r["method_count"] == 14, (
            f"expected 14 methods, got {r['method_count']}"
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

        print("\n[9] frame_wall 48\"x96\" 2x4 at 24 OC (defaults for plates)")
        # v0.4.1: bridge parity for the v0.4 frame_wall operator. Small
        # test wall (48" x 96") at 24 OC keeps the math easy to verify:
        # 3 stud positions at left-edge x = 0.0, 23.25, 46.5 (centers
        # at 0.75, 24, 47.25), stud length 91.5" (96 - 3*1.5 plate stack),
        # both plates and studs cut from 8' (96") 2x4 stock.
        r = cli.call("frame_wall", {
            "length_in": 48.0,
            "height_in": 96.0,
            "nominal": "2x4",
            "spacing_oc_in": 24.0,
            # default top_plate_count=2, bottom_plate_count=1
        })
        print(f"  -> {r}")
        assert r["wall_name"].startswith("Wall_"), (
            f"wall name should match Wall_NN, got {r['wall_name']!r}"
        )
        assert r["nominal"] == "2x4"
        assert r["n_studs"] == 3, (
            f"48\" wall at 24 OC should produce 3 studs, got {r['n_studs']}"
        )
        assert r["n_plates"] == 3, (
            f"2 top + 1 bottom = 3 plates, got {r['n_plates']}"
        )
        assert r["stud_length_in"] == 91.5, (
            f"stud_length_in should be 91.5 (96 - 4.5 plate stack), got {r['stud_length_in']}"
        )
        assert r["stud_stock_in"] == 96.0, (
            f"smallest 2x4 stock fitting 91.5 is 8' = 96\", got {r['stud_stock_in']}"
        )
        assert r["plate_stock_in"] == 96.0, (
            f"smallest 2x4 stock fitting 48 is 8' = 96\", got {r['plate_stock_in']}"
        )
        # new_objects: 1 Empty parent + 3 studs + 3 plates = 7 names.
        # The Empty itself is included because the before/after diff
        # over scene.objects catches every new scene member.
        assert len(r["new_objects"]) == 7, (
            f"expected 7 new objects (1 Empty + 3 studs + 3 plates), "
            f"got {len(r['new_objects'])}: {r['new_objects']}"
        )

        print("\n[10] frame_wall 96\"x96\" 2x4 at 16 OC with one door")
        # v0.5.1: bridge parity for the v0.5 opening flow. Test wall is
        # 96"x96" 2x4 at 16 OC with a centered-ish 38"x82" RO door at
        # x_offset=29. Math (compute by hand, all values pin against
        # regressions):
        #   - stud thickness t = 1.5
        #   - king bracket: outer [26.0, 70.0], inner [27.5, 68.5]
        #   - jack length = 82 - 1.5 (bottom plate top) = 80.5
        #   - header length = 38 + 2 * 1 * 1.5 = 41.0
        #   - header cripple zone z = (85.5, 93.0), length 7.5 (>= 1.5 min)
        #   - raw OC stud x lefts: 0, 15.25, 31.25, 47.25, 63.25, 79.25, 94.5
        #   - filter: studs whose [x, x+1.5] overlaps king bracket [26, 70]
        #     drops 31.25, 47.25, 63.25 (three of them); keeps 0, 15.25,
        #     79.25, 94.5 (four)
        #   - header cripples at OC positions inside inner range
        #     [27.5, 68.5]: 31.25, 47.25, 63.25 — count 3
        #   - jack_count auto from recommend_jack_count(38) -> 1 (RO < 72")
        #   - header_nominal default -> wall nominal "2x4"
        r = cli.call("frame_wall", {
            "length_in": 96.0,
            "height_in": 96.0,
            "nominal": "2x4",
            "spacing_oc_in": 16.0,
            "openings": [
                {
                    "type": "door",
                    "x_offset_in": 29.0,
                    "ro_width_in": 38.0,
                    "ro_height_in": 82.0,
                },
            ],
        })
        print(f"  -> {r}")
        assert r["wall_name"].startswith("Wall_"), (
            f"wall name should match Wall_NN, got {r['wall_name']!r}"
        )
        assert r["n_studs"] == 4, (
            f"96\" wall at 16 OC with door at x=29 should leave 4 "
            f"regular studs after king-bracket filtering, got {r['n_studs']}"
        )
        assert r["n_plates"] == 3, (
            f"2 top + 1 bottom = 3 plates, got {r['n_plates']}"
        )
        assert r["n_openings"] == 1, (
            f"expected n_openings=1, got {r['n_openings']}"
        )
        assert len(r["openings_summary"]) == 1, (
            f"expected 1 openings_summary entry, got {len(r['openings_summary'])}"
        )
        s = r["openings_summary"][0]
        assert s["type"] == "door", (
            f"opening type should echo lowercase 'door', got {s['type']!r}"
        )
        assert s["jack_count"] == 1, (
            f"jack_count auto-derive: recommend_jack_count(38) -> 1 "
            f"(RO < 72\"), got {s['jack_count']}"
        )
        assert s["header_nominal"] == "2x4", (
            f"header_nominal should default to wall nominal '2x4', "
            f"got {s['header_nominal']!r}"
        )
        assert s["jack_length_in"] == 80.5, (
            f"jack_length = ro_height - bottom_plate_count*t = 82 - 1.5 "
            f"= 80.5, got {s['jack_length_in']}"
        )
        assert s["header_length_in"] == 41.0, (
            f"header_length = ro_width + 2*jack_count*t = 38 + 2*1*1.5 "
            f"= 41.0, got {s['header_length_in']}"
        )
        assert s["n_header_cripples"] == 3, (
            f"3 OC positions (31.25, 47.25, 63.25) fall inside king "
            f"inner range [27.5, 68.5], got {s['n_header_cripples']}"
        )
        assert s["n_sill_cripples"] == 0, (
            f"door has no rough sill so no sill cripples, "
            f"got {s['n_sill_cripples']}"
        )
        # new_objects: 1 Empty + 4 regular studs + 3 plates + 2 kings
        # + 2 jacks + 2 header members + 1 header spacer (untagged but
        # still a scene object) + 3 header cripples = 18.
        assert len(r["new_objects"]) == 18, (
            f"expected 18 new objects (1 Empty + 4 regular studs + 3 "
            f"plates + 2 kings + 2 jacks + 2 headers + 1 spacer + 3 "
            f"cripples), got {len(r['new_objects'])}: {r['new_objects']}"
        )

        print("\n[11] add_building name='TestBuilding'")
        # v0.6.1: container bridge parity. add_building creates the
        # Building Empty plus a default Level child in one call. Both
        # become the scene's active Building / active Level.
        r = cli.call("add_building", {"name": "TestBuilding"})
        print(f"  -> {r}")
        assert r["building_name"] == "TestBuilding", (
            f"expected building_name 'TestBuilding', "
            f"got {r['building_name']!r}"
        )
        building_name = r["building_name"]
        level_01_name = r["level_name"]
        assert isinstance(level_01_name, str) and level_01_name, (
            f"expected non-empty level_name string, got {level_01_name!r}"
        )
        assert r["level_index"] == 0, (
            f"default Level should have level_index=0, got {r['level_index']}"
        )

        print("\n[12] add_level building='TestBuilding'")
        # Adds a second Level under the same Building. level_index
        # auto-increments to one higher than the default Level's 0.
        r = cli.call("add_level", {"building": building_name})
        print(f"  -> {r}")
        level_02_name = r["level_name"]
        assert isinstance(level_02_name, str) and level_02_name, (
            f"expected non-empty level_name string, got {level_02_name!r}"
        )
        assert r["level_index"] == 1, (
            f"second Level should have level_index=1, got {r['level_index']}"
        )
        assert r["building"] == building_name, (
            f"echoed building should match, got {r['building']!r}"
        )

        print(f"\n[13] frame_wall under {level_02_name} at 90 deg rotation")
        # v0.6.1: CREATE path with level + rotation_deg_z. The new wall
        # Empty is parented under level_02_name and rotated 90 degrees
        # around Z. spacing_oc_in left at the default 16; for a 48"
        # wall at 16 OC with 2x4 studs (1.5" thick) stud_positions
        # produces 4 left-edge x-coords: 0.0, 15.25, 31.25, 46.5 —
        # NOTE: this differs from the cycle brief's "n_studs == 3"
        # claim. The brief either intended spacing_oc_in=24 (which
        # would give 3 studs like step [9]) or miscounted; we follow
        # the actual math here. The list_objects total at [15] still
        # works out to 47 either way because [14]'s rebuild adjusts
        # the lumber count compensatingly.
        r = cli.call("frame_wall", {
            "length_in": 48.0,
            "height_in": 96.0,
            "nominal": "2x4",
            "level": level_02_name,
            "rotation_deg_z": 90.0,
        })
        print(f"  -> {r}")
        wall_03_name = r["wall_name"]
        assert isinstance(wall_03_name, str) and wall_03_name, (
            f"expected non-empty wall_name string, got {wall_03_name!r}"
        )
        assert r["n_studs"] == 4, (
            f"48\" wall at 16 OC default should produce 4 studs "
            f"(stud_positions(48,16,1.5)=[0.0,15.25,31.25,46.5]), "
            f"got {r['n_studs']}"
        )
        assert r["n_plates"] == 3, (
            f"2 top + 1 bottom = 3 plates, got {r['n_plates']}"
        )
        assert r["level_name"] == level_02_name, (
            f"wall should report level_name={level_02_name!r}, "
            f"got {r['level_name']!r}"
        )
        assert abs(r["rotation_deg_z"] - 90.0) < 1e-6, (
            f"rotation_deg_z should be 90.0, got {r['rotation_deg_z']}"
        )
        assert r["wall_target_used"] is False, (
            f"CREATE call should have wall_target_used=False, "
            f"got {r['wall_target_used']}"
        )

        print(f"\n[14] frame_wall wall_target={wall_03_name} length_in=72")
        # v0.6.1: REBUILD path. wall_target picks in-place mode; only
        # length_in is provided. height_in, nominal, spacing_oc_in,
        # plate counts, openings, level, AND rotation are all
        # preserved. The Empty name persists (joint references and
        # transforms survive).
        r = cli.call("frame_wall", {
            "wall_target": wall_03_name,
            "length_in": 72.0,
        })
        print(f"  -> {r}")
        assert r["wall_name"] == wall_03_name, (
            f"REBUILD must preserve Empty name {wall_03_name!r}, "
            f"got {r['wall_name']!r}"
        )
        assert r["length_in"] == 72.0, (
            f"length_in should be echoed as 72.0, got {r['length_in']}"
        )
        assert r["n_studs"] == 6, (
            f"72\" wall at preserved 16 OC should produce 6 studs "
            f"(stud_positions(72,16,1.5) = 6 positions), got {r['n_studs']}"
        )
        assert r["wall_target_used"] is True, (
            f"REBUILD call should have wall_target_used=True, "
            f"got {r['wall_target_used']}"
        )
        assert r["level_name"] == level_02_name, (
            f"REBUILD should preserve level_name={level_02_name!r}, "
            f"got {r['level_name']!r}"
        )
        assert abs(r["rotation_deg_z"] - 90.0) < 1e-6, (
            f"REBUILD with no rotation_deg_z param should preserve "
            f"existing 90 deg rotation, got {r['rotation_deg_z']}"
        )

        print("\n[15] list_objects (praxova only)")
        r = cli.call("list_objects")
        print(f"  -> {r['count']} praxova objects")
        # v0.6.1 changed _is_praxova_managed to include is_wall /
        # is_level / is_building Empties in addition to v0.4's
        # is_lumber. So previously-invisible wall Empties from [9]
        # and [10] now count.
        # Pre-v0.6.1 / v0.5.1 baseline: 32 lumber pieces (1 stud +
        #   4 OC dupes + 1 sheet + 1 panel + 3 fill dupes + 6 from
        #   [9] frame_wall + 16 from [10] frame_wall-with-door).
        # +2 for the [9] and [10] Wall Empties = 34.
        # [11] add_building: +1 Building +1 default Level = 36.
        # [12] add_level: +1 Level = 37.
        # [13] frame_wall: +1 Wall + 4 studs + 3 plates = +8 -> 45.
        # [14] rebuild [13] from 48"->72": Empty preserved, 4 studs
        #   + 3 plates removed, 6 studs + 3 plates added: net +2 ->
        #   47. (The cycle brief's arithmetic landed on 47 too with
        #   different per-step numbers because [13]+[14] net out to
        #   +10 either way.)
        assert r["count"] == 47, (
            f"expected 47 praxova objects after v0.6.1 steps, "
            f"got {r['count']}"
        )

        print("\n[16] generate_cutlist")
        r = cli.call("generate_cutlist")
        print("  -> cutlist body:")
        for line in r["text"].splitlines():
            print(f"     {line}")
        # All three sections should appear when all three categories
        # are populated. v0.4.0 split LUMBER into two subsections
        # ("LUMBER - CUT LIST" and "LUMBER - ORDER SUMMARY"); the
        # substring "LUMBER" still appears in both, so this assertion
        # passes unchanged.
        assert "LUMBER" in r["text"]
        assert "SHEETS" in r["text"]
        assert "PANELS" in r["text"]
        # v0.4.1: the frame_wall studs (cut 91.5" from 96" stock) should
        # appear in the CUT LIST subsection with the "cut to N\""
        # annotation. Pins the stock-vs-cut distinction in place against
        # future regressions to the cutlist rendering.
        assert "cut to 91.5" in r["text"], (
            "expected 'cut to 91.5\"' annotation for frame_wall studs in "
            "the LUMBER - CUT LIST subsection"
        )
        # v0.5.1: the opening pieces add three more cut-length annotations
        # to the CUT LIST subsection — jacks at 80.5", header members at
        # 41" (integer, so '41' not '41.0' per _format_inches' trailing-
        # zero strip), and header cripples at 7.5".
        assert "cut to 80.5" in r["text"], (
            "expected 'cut to 80.5\"' annotation for jack studs"
        )
        assert "cut to 41" in r["text"], (
            "expected 'cut to 41\"' annotation for header members "
            "(_format_inches strips trailing zeros from 41.0)"
        )
        assert "cut to 7.5" in r["text"], (
            "expected 'cut to 7.5\"' annotation for header cripples"
        )
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

        print("\n[17] error path: unknown lumber")
        try:
            cli.call("add_lumber", {"nominal": "2x5", "length_ft": 8})
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")

        print("\n[18] error path: duplicate_e2e on lumber (should refuse)")
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

        print("\n[19] error path: bad method")
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

"""Smoke-test client for the Praxova Framing bridge.

Run from any Python (NOT inside Blender). Assumes the bridge is running
on 127.0.0.1:9876 with a fresh empty scene.

    python smoke_test.py
    python smoke_test.py --port 9876

Exits non-zero on any unexpected response.

Covers the full v0.6.25 RPC surface end-to-end (18 methods — unchanged
from v0.6.2; v0.6.25 was a bug-fix + cosmetic cycle, no bridge schema
changes): ping (with addon_version and method_count assertions), scene
info, material catalog, lumber / sheet / panel placement, on-center
duplication, edge-to-edge fill, wall framing with optional door/window
openings (v0.5.1 — bridge parity for the v0.5 UI), Building + Level
container creation and wall framing under a Level with in-place
re-framing (v0.6.1 — containers + frame_wall extension + list_objects
extension), the joint lifecycle + frame_building orchestrator +
list_joints_in_level query (v0.6.2 — completes v0.6 bridge parity), a
v0.6.25 regression-coverage step that adds a joint with explicit
extending_wall="B" and asserts the corner filler lands on wall_b (the
v0.6.0 bug fixed in v0.6.25 had this ignored — filler always on
wall_a), cut-list generation (verifying three sections and the
'cut to N"' annotations for frame_wall regular studs and the v0.5
opening pieces — jacks, header members, and cripples), and three
error paths including the LUMBER refusal for duplicate_e2e plus the
v0.6.2 rotation+joints refusal.
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
        # container half of v0.6's bridge parity); addon_version
        # 0.6.0 -> 0.6.1. v0.6.2: method_count 14 -> 18 for
        # add_joint + remove_joint + frame_building +
        # list_joints_in_level (the joint half — completes v0.6
        # bridge parity); addon_version 0.6.1 -> 0.6.2. v0.6.25:
        # bug fix + cosmetic cycle (extending_wall finally honored;
        # ft display + carpenter readout; custom imperial icon);
        # method_count stays 18 (no bridge schema changes);
        # addon_version 0.6.2 -> 0.6.25.
        assert r["addon_version"] == "0.6.25", (
            f"expected addon_version 0.6.25, got {r['addon_version']!r}"
        )
        assert r["method_count"] == 18, (
            f"expected 18 methods, got {r['method_count']}"
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
        # 1e-4 tolerance: Blender's rotation_euler stores as float32,
        # so the radians -> degrees round-trip drops a few sig figs.
        # Observed drift on a clean call is ~2.5e-6 deg; 1e-4 leaves
        # headroom while still catching obviously-wrong values.
        assert abs(r["rotation_deg_z"] - 90.0) < 1e-4, (
            f"rotation_deg_z should be ~90.0, got {r['rotation_deg_z']}"
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
        # Same 1e-4 float32-round-trip tolerance as step [13].
        assert abs(r["rotation_deg_z"] - 90.0) < 1e-4, (
            f"REBUILD with no rotation_deg_z param should preserve "
            f"existing ~90 deg rotation, got {r['rotation_deg_z']}"
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

        print("\n[17] add_building (auto-named) for v0.6.2 joint flow")
        # v0.6.2: standalone Building + Level for the joint + frame_
        # building sequence. The v0.6.1 TestBuilding stays untouched
        # so its walls don't interfere; this one gets a fresh Level
        # for the two-wall L corner test.
        r = cli.call("add_building", {})
        print(f"  -> {r}")
        v6_building_name = r["building_name"]
        v6_level_name = r["level_name"]
        assert isinstance(v6_building_name, str) and v6_building_name, (
            f"expected non-empty building_name, got {v6_building_name!r}"
        )
        assert isinstance(v6_level_name, str) and v6_level_name, (
            f"expected non-empty level_name, got {v6_level_name!r}"
        )
        assert r["level_index"] == 0, (
            f"default Level should have level_index=0, got {r['level_index']}"
        )

        print(f"\n[18] frame_wall level={v6_level_name} (wall_a at origin)")
        # 96" 2x4 wall at default 16 OC:
        # stud_positions(96, 16, 1.5) = [0.0, 15.25, 31.25, 47.25,
        # 63.25, 79.25, 94.5] = 7 studs. Plus 1 bottom + 2 top
        # plates = 3 plates.
        r = cli.call("frame_wall", {
            "level": v6_level_name,
            "length_in": 96.0,
            "height_in": 96.0,
            "nominal": "2x4",
        })
        print(f"  -> wall_name={r['wall_name']}, n_studs={r['n_studs']}, "
              f"n_plates={r['n_plates']}")
        wall_a_name = r["wall_name"]
        assert r["n_studs"] == 7, (
            f"96\" wall at 16 OC should produce 7 studs, got {r['n_studs']}"
        )
        assert r["n_plates"] == 3, (
            f"2 top + 1 bottom = 3 plates, got {r['n_plates']}"
        )
        assert r["level_name"] == v6_level_name, (
            f"wall should be under {v6_level_name!r}, "
            f"got level_name={r['level_name']!r}"
        )

        print(f"\n[19] frame_wall level={v6_level_name} rotated 90 deg "
              "at +96 in along X (wall_b)")
        # 2.4384 m = 96 inches exactly (96 * 0.0254). Place wall_b's
        # START at wall_a's END, then rotate wall_b 90 deg so it
        # juts in +Y from there — the canonical L corner.
        # rotation_deg_z echo uses the same 1e-3 tolerance the v0.6.1
        # smoke test established for float32 round-trip (radians ->
        # store -> degrees yields ~2.5e-6 error).
        r = cli.call("frame_wall", {
            "level": v6_level_name,
            "length_in": 96.0,
            "height_in": 96.0,
            "nominal": "2x4",
            "rotation_deg_z": 90.0,
            "location_m": [2.4384, 0.0, 0.0],
        })
        print(f"  -> wall_name={r['wall_name']}, "
              f"rotation_deg_z={r['rotation_deg_z']}")
        wall_b_name = r["wall_name"]
        assert wall_b_name != wall_a_name, (
            f"second wall should have a distinct name; "
            f"got wall_a={wall_a_name!r}, wall_b={wall_b_name!r}"
        )
        assert abs(r["rotation_deg_z"] - 90.0) < 1e-3, (
            f"rotation_deg_z should be ~90.0 (1e-3 epsilon for float32 "
            f"round-trip), got {r['rotation_deg_z']}"
        )
        assert r["level_name"] == v6_level_name, (
            f"wall should be under {v6_level_name!r}, "
            f"got level_name={r['level_name']!r}"
        )

        print(f"\n[20] add_joint {wall_a_name}.END -> {wall_b_name}.START "
              "(default joint_type / corner_style / extending_wall)")
        # All optional fields left as defaults — exercises the
        # default-fill code path in _parse_joint. The corner_style
        # AUTO + extending_wall AUTO resolution happens at
        # frame_building time, not add_joint time, so the response
        # echoes them literally as "AUTO".
        r = cli.call("add_joint", {
            "level_name": v6_level_name,
            "joint": {
                "wall_a_name": wall_a_name,
                "wall_b_name": wall_b_name,
                "wall_a_end": "END",
                "wall_b_end": "START",
            },
        })
        print(f"  -> {r}")
        assert r["joint_index"] == 0, (
            f"first joint should have joint_index=0, "
            f"got {r['joint_index']}"
        )
        joint = r["joint"]
        assert joint["joint_type"] == "L_CORNER", (
            f"default joint_type should be 'L_CORNER', "
            f"got {joint['joint_type']!r}"
        )
        assert joint["corner_style"] == "AUTO", (
            f"default corner_style should be 'AUTO', "
            f"got {joint['corner_style']!r}"
        )
        assert joint["extending_wall"] == "AUTO", (
            f"default extending_wall should be 'AUTO', "
            f"got {joint['extending_wall']!r}"
        )

        print(f"\n[21] frame_building level_name={v6_level_name}")
        # Re-frames both walls in the Level with joint context.
        # Expected per-wall summary: both walls touch joint 0
        # (joint_indices_touching=[0]); exactly ONE wall has
        # n_corner_fillers=1 (the MAIN wall — wall_a here, since it
        # was passed as wall_a_name in [20] and MAIN/ABUTTING is set
        # by that assignment, not by extending_wall resolution).
        # The other has n_corner_fillers=0. Don't pin WHICH entry is
        # which — level.children iteration order isn't guaranteed.
        r = cli.call("frame_building", {"level_name": v6_level_name})
        print(f"  -> n_walls_framed={r['n_walls_framed']}, "
              f"n_joints_resolved={r['n_joints_resolved']}")
        assert r["n_walls_framed"] == 2, (
            f"expected n_walls_framed=2, got {r['n_walls_framed']}"
        )
        assert r["n_joints_resolved"] == 1, (
            f"expected n_joints_resolved=1, got {r['n_joints_resolved']}"
        )
        assert len(r["walls_framed"]) == 2, (
            f"expected 2 walls_framed entries, "
            f"got {len(r['walls_framed'])}"
        )
        for entry in r["walls_framed"]:
            assert entry["joint_indices_touching"] == [0], (
                f"wall {entry['wall_name']!r} should touch joint 0, "
                f"got joint_indices_touching={entry['joint_indices_touching']}"
            )
        filler_counts = sorted(
            e["n_corner_fillers"] for e in r["walls_framed"]
        )
        assert filler_counts == [0, 1], (
            f"expected exactly one wall with n_corner_fillers=1 and one "
            f"with 0 (sorted [0, 1]), got {filler_counts}"
        )

        print(f"\n[22] list_joints_in_level level_name={v6_level_name}")
        # Full joint detail — fills the gap v0.6.1's list_objects
        # LEVEL category left (joints_count only).
        r = cli.call("list_joints_in_level",
                     {"level_name": v6_level_name})
        print(f"  -> n_joints={r['n_joints']}, "
              f"joints[0]={r['joints'][0]}")
        assert r["n_joints"] == 1, (
            f"expected n_joints=1, got {r['n_joints']}"
        )
        j0 = r["joints"][0]
        assert j0["joint_type"] == "L_CORNER", (
            f"joints[0].joint_type should be 'L_CORNER', "
            f"got {j0['joint_type']!r}"
        )
        assert j0["wall_a_name"] == wall_a_name, (
            f"joints[0].wall_a_name should echo {wall_a_name!r}, "
            f"got {j0['wall_a_name']!r}"
        )
        assert j0["wall_b_name"] == wall_b_name, (
            f"joints[0].wall_b_name should echo {wall_b_name!r}, "
            f"got {j0['wall_b_name']!r}"
        )
        assert j0["wall_a_end"] == "END", (
            f"joints[0].wall_a_end should be 'END', "
            f"got {j0['wall_a_end']!r}"
        )
        assert j0["wall_b_end"] == "START", (
            f"joints[0].wall_b_end should be 'START', "
            f"got {j0['wall_b_end']!r}"
        )

        print(f"\n[23] frame_wall wall_target={wall_a_name} "
              "rotation_deg_z=180 (should refuse — joint touches wall_a)")
        # Exercises the v0.6.1-specced rotation+joints refusal that
        # couldn't be tested until v0.6.2 add_joint shipped. The
        # error message includes the substring "joint" (lowercase)
        # per the handler's INVALID_PARAMS message.
        try:
            cli.call("frame_wall", {
                "wall_target": wall_a_name,
                "rotation_deg_z": 180.0,
            })
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")
            err_text = str(e)
            assert "-32602" in err_text or "INVALID_PARAMS" in err_text, (
                f"expected INVALID_PARAMS code, got: {err_text!r}"
            )
            assert "joint" in err_text.lower(), (
                f"expected error to mention 'joint', got: {err_text!r}"
            )
        else:
            raise AssertionError(
                "frame_wall(wall_target=..., rotation_deg_z=180) on a "
                "wall touched by a joint should have raised INVALID_PARAMS"
            )

        print(f"\n[24] remove_joint level_name={v6_level_name} joint_index=0")
        # The "undo handle" pattern — remove_joint returns the full
        # joint spec, which add_joint could consume verbatim to put
        # the joint back. Verify the echo carries every wire field.
        r = cli.call("remove_joint", {
            "level_name": v6_level_name,
            "joint_index": 0,
        })
        print(f"  -> {r}")
        assert r["joint_index"] == 0, (
            f"expected joint_index=0 echo, got {r['joint_index']}"
        )
        removed = r["removed"]
        assert removed["joint_type"] == "L_CORNER", (
            f"removed.joint_type should be 'L_CORNER', "
            f"got {removed['joint_type']!r}"
        )
        assert removed["wall_a_name"] == wall_a_name, (
            f"removed.wall_a_name should echo {wall_a_name!r}, "
            f"got {removed['wall_a_name']!r}"
        )
        assert removed["wall_b_name"] == wall_b_name, (
            f"removed.wall_b_name should echo {wall_b_name!r}, "
            f"got {removed['wall_b_name']!r}"
        )

        print(f"\n[25] frame_wall wall_target={wall_a_name} "
              "rotation_deg_z=180 (joint gone, should succeed)")
        # Now that joint 0 is removed, the v0.6.1 rotation+joints
        # refusal no longer fires. wall_a should rotate to 180 deg.
        r = cli.call("frame_wall", {
            "wall_target": wall_a_name,
            "rotation_deg_z": 180.0,
        })
        print(f"  -> wall_target_used={r['wall_target_used']}, "
              f"rotation_deg_z={r['rotation_deg_z']}")
        assert r["wall_target_used"] is True, (
            f"wall_target= should switch to REBUILD mode, "
            f"got wall_target_used={r['wall_target_used']}"
        )
        assert abs(r["rotation_deg_z"] - 180.0) < 1e-3, (
            f"rotation_deg_z should be ~180.0 (1e-3 epsilon for float32 "
            f"round-trip), got {r['rotation_deg_z']}"
        )

        print("\n[26] add_joint with explicit extending_wall='B' "
              "(v0.6.25 fix regression coverage)")
        # v0.6.25 Item 1 fix coverage: explicit extending_wall='B'
        # should make wall_b MAIN, so the corner filler stud lands
        # under wall_b. v0.6.0/0.6.2 had this ignored — filler
        # always on wall_a regardless of extending_wall — because
        # compute_wall_joint_context hardcoded role='MAIN' for
        # the wall_a slot. The fix wires resolve_extending_wall
        # into role assignment; this step exercises the new path
        # end-to-end via the bridge.
        r = cli.call("add_joint", {
            "level_name": v6_level_name,
            "joint": {
                "wall_a_name": wall_a_name,
                "wall_b_name": wall_b_name,
                "wall_a_end": "END",
                "wall_b_end": "START",
                "extending_wall": "B",
            },
        })
        print(f"  -> {r}")
        assert r["joint_index"] == 0, (
            f"first joint after removal should be index 0, got {r['joint_index']}"
        )
        assert r["joint"]["extending_wall"] == "B", (
            f"explicit extending_wall='B' should echo back as 'B', "
            f"got {r['joint']['extending_wall']!r}"
        )

        print("\n[27] frame_building → corner filler lands on wall_b "
              "(not wall_a)")
        r = cli.call("frame_building", {"level_name": v6_level_name})
        print(f"  -> walls_framed={r['walls_framed']}")
        assert r["n_walls_framed"] == 2, (
            f"expected n_walls_framed=2, got {r['n_walls_framed']}"
        )
        wall_a_entry = next(
            (e for e in r["walls_framed"] if e["wall_name"] == wall_a_name),
            None,
        )
        wall_b_entry = next(
            (e for e in r["walls_framed"] if e["wall_name"] == wall_b_name),
            None,
        )
        assert wall_a_entry is not None and wall_b_entry is not None, (
            f"expected both wall_a={wall_a_name!r} and wall_b="
            f"{wall_b_name!r} in walls_framed, got "
            f"{[e['wall_name'] for e in r['walls_framed']]}"
        )
        # The v0.6.25 fix assertion: explicit extending_wall='B' makes
        # wall_b MAIN, so filler under wall_b not wall_a.
        assert wall_b_entry["n_corner_fillers"] == 1, (
            f"v0.6.25 fix coverage: explicit extending_wall='B' "
            f"should put the corner filler on wall_b "
            f"({wall_b_name!r}). Got "
            f"n_corner_fillers={wall_b_entry['n_corner_fillers']} "
            "instead — v0.6.0 bug is back."
        )
        assert wall_a_entry["n_corner_fillers"] == 0, (
            f"wall_a ({wall_a_name!r}) should be ABUTTING (no filler) "
            f"when extending_wall='B'. Got "
            f"n_corner_fillers={wall_a_entry['n_corner_fillers']}."
        )

        print("\n[28] list_objects → verify cap-plate lap geometry (v0.6.30)")
        # v0.6.30 cap-plate lap fix: cap is the INVERSE of the lower
        # top plate at each joint end. With step [26]'s joint
        # (extending_wall='B' → wall_b is MAIN, wall_a is ABUTTING)
        # and 2x4 walls (paired_t = 3.5"):
        #
        #   wall_a (ABUTTING at END, FREE at START):
        #     lower top: 92.5" (= 96 - 3.5, shortened at END), x_start=0
        #     cap:       99.5" (= 96 + 3.5, extends past END to lap
        #                onto wall_b's lower top), x_start=0
        #
        #   wall_b (MAIN at START, FREE at END):
        #     lower top: 96"   (full, MAIN keeps continuity)
        #     cap:       92.5" (= 96 - 3.5, pulled INBOARD at START
        #                to leave room for wall_a's cap to lap onto
        #                wall_b's lower top), x_start=3.5" (0.0889 m)
        #
        # Before v0.6.30 the cap was identical to the lower top — both
        # 92.5" with x_start=0 on each end. wall_a's cap at 99.5"
        # (extending past the wall edge) is the regression sentinel:
        # if v0.6.0's butt-joint cap geometry comes back, wall_a's
        # cap drops to 92.5" and this step fails loudly.
        r = cli.call("list_objects")
        by_name = {o["name"]: o for o in r["objects"]}

        wall_a_lower = by_name.get(f"{wall_a_name}_TopPlate_01")
        wall_a_cap = by_name.get(f"{wall_a_name}_TopPlate_02")
        wall_b_lower = by_name.get(f"{wall_b_name}_TopPlate_01")
        wall_b_cap = by_name.get(f"{wall_b_name}_TopPlate_02")
        for name, obj in [
            (f"{wall_a_name}_TopPlate_01", wall_a_lower),
            (f"{wall_a_name}_TopPlate_02", wall_a_cap),
            (f"{wall_b_name}_TopPlate_01", wall_b_lower),
            (f"{wall_b_name}_TopPlate_02", wall_b_cap),
        ]:
            assert obj is not None, (
                f"expected {name!r} in scene after frame_building, "
                f"but list_objects didn't return it"
            )

        # wall_a (ABUTTING at END, FREE at START)
        assert abs(wall_a_lower["length_in"] - 92.5) < 1e-3, (
            f"wall_a lower top plate: expected 92.5\" (= 96 - 3.5 "
            f"ABUTTING at END), got {wall_a_lower['length_in']}"
        )
        assert abs(wall_a_lower["location_m"][0] - 0.0) < 1e-3, (
            f"wall_a lower top plate x_start should be 0.0, got "
            f"{wall_a_lower['location_m'][0]}"
        )
        assert abs(wall_a_cap["length_in"] - 99.5) < 1e-3, (
            f"v0.6.30 lap fix sentinel: wall_a cap should extend past "
            f"its wall edge by 3.5\" at the ABUTTING end (= 96 + 3.5 "
            f"= 99.5\"). Got {wall_a_cap['length_in']}. If this is "
            f"92.5\" the lap isn't happening — v0.6.0 butt-joint "
            f"geometry is back."
        )
        assert abs(wall_a_cap["location_m"][0] - 0.0) < 1e-3, (
            f"wall_a cap x_start should be 0.0 (FREE start), got "
            f"{wall_a_cap['location_m'][0]}"
        )

        # wall_b (MAIN at START, FREE at END)
        assert abs(wall_b_lower["length_in"] - 96.0) < 1e-3, (
            f"wall_b lower top plate: expected 96.0\" (MAIN keeps "
            f"full continuity), got {wall_b_lower['length_in']}"
        )
        assert abs(wall_b_lower["location_m"][0] - 0.0) < 1e-3, (
            f"wall_b lower top plate x_start should be 0.0, got "
            f"{wall_b_lower['location_m'][0]}"
        )
        assert abs(wall_b_cap["length_in"] - 92.5) < 1e-3, (
            f"v0.6.30 lap fix: wall_b cap should be shortened inboard "
            f"by 3.5\" at the MAIN end (= 96 - 3.5 = 92.5\"). Got "
            f"{wall_b_cap['length_in']}."
        )
        # 3.5" = 3.5 * 0.0254 = 0.0889 m. 1e-3 m tolerance (~1mm).
        assert abs(wall_b_cap["location_m"][0] - 0.0889) < 1e-3, (
            f"v0.6.30 lap fix: wall_b cap x_start should be 3.5\" "
            f"inboard (0.0889 m) at the MAIN end, got "
            f"{wall_b_cap['location_m'][0]}"
        )
        print("  -> cap lap geometry verified: wall_a cap extends "
              "3.5\" past its END to lap onto wall_b's lower top "
              "plate; wall_b cap pulled 3.5\" inboard at its START "
              "to make room for wall_a's cap")

        print("\n[29] error path: unknown lumber")
        try:
            cli.call("add_lumber", {"nominal": "2x5", "length_ft": 8})
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")

        print("\n[30] error path: duplicate_e2e on lumber (should refuse)")
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

        print("\n[31] error path: bad method")
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

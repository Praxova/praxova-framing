"""Smoke-test client for the Praxova Framing bridge.

Run from any Python (NOT inside Blender). Assumes the bridge is running
on 127.0.0.1:9876 with a fresh empty scene.

    python smoke_test.py
    python smoke_test.py --port 9876

Exits non-zero on any unexpected response.

Covers the full v0.6.60 RPC surface end-to-end (18 methods — unchanged
from v0.6.2; v0.6.25 through v0.6.50 were bug-fix / UI-only cycles
with no bridge schema changes, v0.6.51 added T-joint bridge surface
inside existing handlers, and v0.6.60 is operator-only (CALIFORNIA +
LADDER_BLOCKING corner styles) with bridge parity deferred to
v0.6.61; still 18 methods): ping (with addon_version and method_count
assertions), scene
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
        # addon_version 0.6.2 -> 0.6.25. v0.6.30: cap-plate lap
        # geometry fix at L-joint corners (caps were butt joints
        # before; now lap mechanically per IRC R602.3.2); method
        # count stays 18; addon_version 0.6.25 -> 0.6.30. v0.6.31:
        # cap-plate ABUTTING-end correction (don't extend past wall
        # edge; lap happens inside the abutting wall's own footprint
        # at y in [0, paired_t]); method count stays 18;
        # addon_version 0.6.30 -> 0.6.31. v0.6.40: in-line plate
        # splices (UI/operator only); method_count stays 18.
        # addon_version 0.6.31 -> 0.6.40. v0.6.41: bridge parity for
        # the splice path — response shape gains splice_summary
        # (frame_wall + per-wall in frame_building.walls_framed),
        # SpliceError surfaces as INVALID_PARAMS via pre-flight, and
        # new smoke steps [32]/[33]/[34] exercise the splice path
        # end-to-end. method_count stays 18 — splice is folded into
        # the existing frame_wall / frame_building schema, no new
        # methods. addon_version 0.6.40 -> 0.6.41. v0.6.50: T joints
        # (joint_type='T_JOINT' on PraxovaJoint, new
        # wall_a_position_in FloatProperty, T_BACKING_STUDS corner
        # style). Through-wall cap notched at the joint position;
        # abutting-wall cap extended OUTBOARD into the notch (IRC
        # R602.3.2 T-joint lap). Two backing studs on the through
        # wall flanking the abutting wall's footprint. UI-only
        # cycle — bridge wire format doesn't yet accept
        # joint_type='T_JOINT', so no new smoke steps this cycle.
        # method_count stays 18; addon_version 0.6.41 -> 0.6.50.
        # v0.6.51: addon_version 0.6.50 -> 0.6.51 for T-joint bridge
        # parity (T_JOINT in wire format, wall_a_position_in field,
        # T_BACKING_STUDS corner style, n_backing_studs in
        # walls_framed, splice planner T-aware including notch-vs-
        # splice distinction). method_count stays 18 — T-joint
        # support extends existing handlers, no new RPCs. New smoke
        # steps [35]-[41] cover the bridge surface end-to-end:
        # schema, list round-trip, frame_building with backing
        # studs, splice + T integration, frame_wall REBUILD T-self,
        # three negatives (THREE_STUD+T_JOINT,
        # T_BACKING_STUDS+L_CORNER at add_joint time; position-
        # bounds violation at frame_building time).
        # v0.6.60: addon_version 0.6.51 -> 0.6.60 for CALIFORNIA +
        # LADDER_BLOCKING L-corner styles (operator-only this cycle;
        # bridge parity is v0.6.61). PraxovaJoint.corner_style and
        # PraxovaBuildingProps.default_corner_style each gain two
        # new values; templates.l_corner_geometry becomes a
        # dispatcher branching on corner_style; new
        # CornerBacker_Joint<NN> and LadderBlock_Joint<NN>_<n>
        # placements in frame_wall.execute. validate_joints gains
        # an AUTO-aware LADDER_BLOCKING wall-height pre-flight via
        # the new building_default_corner_style kwarg. No new smoke
        # steps — bridge wire format doesn't accept the new styles
        # until v0.6.61. method_count stays 18 (no new RPCs).
        assert r["addon_version"] == "0.6.60", (
            f"expected addon_version 0.6.60, got {r['addon_version']!r}"
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
        # v0.6.41: plate_stock_in replaced by splice_summary. A 48"
        # wall is well under the 192" max stock, so no plate gets
        # spliced — every plate is a single piece (no splices).
        assert "plate_stock_in" not in r, (
            f"plate_stock_in should be removed in v0.6.41, got {r.get('plate_stock_in')!r}"
        )
        assert r["splice_summary"]["n_splices"] == 0, (
            f"48\" wall should produce 0 splices, got "
            f"{r['splice_summary']['n_splices']}"
        )
        assert r["splice_summary"]["bottom"]["pieces"] == 1, (
            f"48\" wall bottom plate should be 1 piece, got "
            f"{r['splice_summary']['bottom']['pieces']}"
        )
        assert r["splice_summary"]["bottom"]["splice_xs"] == [], (
            f"48\" wall bottom plate splice_xs should be empty, got "
            f"{r['splice_summary']['bottom']['splice_xs']}"
        )
        assert r["splice_summary"]["lower_top"]["pieces"] == 1
        assert r["splice_summary"]["lower_top"]["splice_xs"] == []
        assert r["splice_summary"]["cap"]["pieces"] == 1
        assert r["splice_summary"]["cap"]["splice_xs"] == []
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
        # v0.6.41: 96" wall is well under the 192" max stock, no
        # splices expected even with the door cutting through it.
        assert r["splice_summary"]["n_splices"] == 0, (
            f"96\" wall should produce 0 splices, got "
            f"{r['splice_summary']['n_splices']}"
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
        # v0.6.41: 48" wall, no openings, no joints — no splices.
        assert r["splice_summary"]["n_splices"] == 0, (
            f"48\" wall should produce 0 splices, got "
            f"{r['splice_summary']['n_splices']}"
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
        # v0.6.41: 72" wall after REBUILD, no openings, no joints —
        # no splices. Confirms splice_summary is computed for
        # REBUILD calls the same as CREATE.
        assert r["splice_summary"]["n_splices"] == 0, (
            f"72\" REBUILD wall should produce 0 splices, got "
            f"{r['splice_summary']['n_splices']}"
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
        # v0.6.41: walls_framed entries now carry splice_summary.
        # Both walls in this Level are 96" — well under the 192"
        # max stock — so neither has splices. Verify the field
        # exists and reports 0 splices per wall.
        assert "splice_summary" in wall_a_entry, (
            f"v0.6.41 walls_framed entry should include "
            f"splice_summary, got keys: {sorted(wall_a_entry)}"
        )
        assert wall_a_entry["splice_summary"]["n_splices"] == 0, (
            f"wall_a (96\" 2x4) should have 0 splices, got "
            f"{wall_a_entry['splice_summary']['n_splices']}"
        )
        assert wall_b_entry["splice_summary"]["n_splices"] == 0, (
            f"wall_b (96\" 2x4) should have 0 splices, got "
            f"{wall_b_entry['splice_summary']['n_splices']}"
        )

        print("\n[28] list_objects → verify cap-plate lap geometry (v0.6.31)")
        # v0.6.30 / v0.6.31 cap-plate lap geometry: cap and lower top
        # are mirror images across the MAIN/ABUTTING axis. Neither
        # plate extends past the wall's nominal footprint — the lap
        # happens INSIDE the corner cell at y in [0, paired_t] of
        # the abutting wall's own footprint (which is exactly where
        # the main wall's lower top plate sits in world space). With
        # step [26]'s joint (extending_wall='B' -> wall_b MAIN,
        # wall_a ABUTTING) and 2x4 walls (paired_t = 3.5"):
        #
        #   wall_a (ABUTTING at END, FREE at START):
        #     lower top: 92.5" (= 96 - 3.5, shortened at END), x_start=0
        #     cap:       96.0" (full length; ABUTTING reaches wall
        #                edge — the lap happens inside this wall's
        #                own [0, paired_t] strip at the END corner
        #                cell), x_start=0
        #
        #   wall_b (MAIN at START, FREE at END):
        #     lower top: 96"   (full, MAIN keeps continuity)
        #     cap:       92.5" (= 96 - 3.5, pulled INBOARD at START
        #                to leave room for wall_a's cap to lap onto
        #                wall_b's lower top), x_start=3.5" (0.0889 m)
        #
        # v0.6.30 had wall_a's cap at 99.5" (extending past the wall
        # edge by 3.5") — geometrically wrong. v0.6.31 corrects to
        # 96.0" at the wall edge. Two regression sentinels: 99.5
        # indicates v0.6.30 over-extension regression; 92.5 (matching
        # the lower top length) indicates v0.6.0's butt-joint
        # geometry is back.
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
        assert abs(wall_a_cap["length_in"] - 96.0) < 1e-3, (
            f"v0.6.31 lap geometry: wall_a cap reaches the wall edge "
            f"at the ABUTTING end (no extension past). Expected 96.0\" "
            f"(full wall length), got {wall_a_cap['length_in']}. "
            f"Sentinels: 99.5\" -> v0.6.30 over-extension regression; "
            f"92.5\" -> v0.6.0 butt-joint geometry is back."
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
        print("  -> cap lap geometry verified: wall_a cap reaches its "
              "ABUTTING wall edge (96\", no extension past — v0.6.31 "
              "correction); wall_b cap pulled 3.5\" inboard at its "
              "MAIN start to make room for wall_a's cap to lap into "
              "the corner cell at y in [0, 3.5\"]")

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

        # ==============================================================
        # v0.6.41 splice path coverage ([32]–[34]).
        # ==============================================================
        # v0.6.40 introduced in-line plate splices in the operator; the
        # smoke test side was deferred to v0.6.41 because it exercises
        # the bridge's response shape (splice_summary) and the splice
        # pre-flight that turns SpliceError into INVALID_PARAMS. The
        # three steps below cover: standalone 2x6 splice with the cap
        # offset rule firing ([32]), standalone 2x4 splice at a
        # different length to confirm the planner generalizes ([33]),
        # and a joint-aware splice via frame_building's per-wall
        # splice_summary in walls_framed ([34]).
        #
        # All splice positions are computed by hand from the v0.6.40
        # plan_plate_splice_pieces algorithm: greedy largest-stud-
        # center ≤ ideal_max (192" = 16') with the 24" cap-vs-lower-
        # top offset rule excluding centers within [splice - 24,
        # splice + 24]. Eligible centers are OC stud centers (and
        # joint filler centers when present); jacks and cripples are
        # excluded as they don't provide a continuous load path.

        print("\n[32] frame_wall 24' x 9' 2x6 — splice path (no joint)")
        # 288" (24') 2x6 wall, 108" tall, default 16 OC, 1 bottom +
        # 2 top plates. No openings, no joints. With max_stock = 192"
        # and stud thickness 1.5", stud_positions yields 19 OC studs
        # with centers at 0.75, 16, 32, 48, ..., 272, 287.25.
        # Splices:
        #   BOTTOM (range 0..288): largest center ≤ 192 is 192.0
        #     -> pieces [(0, 192), (192, 288)]; splice_xs = [192.0]
        #   LOWER_TOP (range 0..288): same -> splice_xs = [192.0]
        #   CAP (range 0..288): lower_top splice excludes centers in
        #     [168, 216] -> 176/192/208 all excluded; largest center
        #     ≤ 192 outside that band is 160.0
        #     -> pieces [(0, 160), (160, 288)]; splice_xs = [160.0]
        # n_splices = 1*1 (1 bottom plate) + 1*1 (top_plate_count-1
        # lower top plates) + 1 cap = 3.
        r = cli.call("frame_wall", {
            "length_in": 288.0,
            "height_in": 108.0,
            "nominal": "2x6",
            "spacing_oc_in": 16.0,
        })
        print(f"  -> splice_summary={r['splice_summary']}")
        ss = r["splice_summary"]
        assert ss["n_splices"] == 3, (
            f"expected n_splices=3 (1 bot + 1 lower_top + 1 cap), "
            f"got {ss['n_splices']}"
        )
        assert ss["bottom"]["pieces"] == 2, (
            f"bottom should be spliced into 2 pieces, got "
            f"{ss['bottom']['pieces']}"
        )
        assert ss["bottom"]["splice_xs"] == [192.0], (
            f"bottom splice should land at x=192.0 (largest center "
            f"≤ 192), got {ss['bottom']['splice_xs']}"
        )
        assert ss["lower_top"]["pieces"] == 2
        assert ss["lower_top"]["splice_xs"] == [192.0], (
            f"lower_top splice should land at x=192.0, got "
            f"{ss['lower_top']['splice_xs']}"
        )
        assert ss["cap"]["pieces"] == 2
        assert ss["cap"]["splice_xs"] == [160.0], (
            f"cap splice should land at x=160.0 (IRC R602.3.2 24\" "
            f"offset from lower_top@192 forces the planner inboard "
            f"to the next eligible center), got {ss['cap']['splice_xs']}"
        )
        # Spliced plates carry the v0.6.40 _pN suffix on their Object
        # names. Each plate role contributes 2 pieces, so 6 plate-
        # piece objects total. Verify a couple of representative
        # names appear in new_objects.
        spliced_names = [
            n for n in r["new_objects"]
            if n.endswith("_p1") or n.endswith("_p2")
        ]
        assert len(spliced_names) == 6, (
            f"expected 6 spliced plate piece names (3 plate roles × "
            f"2 pieces), got {len(spliced_names)}: {spliced_names}"
        )

        print("\n[33] frame_wall 20' x 9' 2x4 — splice path, shorter wall")
        # 240" (20') 2x4 wall, 108" tall, default 16 OC. Same algorithm
        # as [32] but the second cap piece is shorter (80" vs 128")
        # because the wall is shorter. Pins the planner generalizes
        # across nominals + lengths.
        #   BOTTOM (range 0..240): splice at 192 (same as [32])
        #     -> second piece 48"
        #   LOWER_TOP: splice at 192 -> second piece 48"
        #   CAP (range 0..240): excluded [168, 216], splice at 160
        #     -> second piece 80"
        r = cli.call("frame_wall", {
            "length_in": 240.0,
            "height_in": 108.0,
            "nominal": "2x4",
            "spacing_oc_in": 16.0,
        })
        print(f"  -> splice_summary={r['splice_summary']}")
        ss = r["splice_summary"]
        assert ss["n_splices"] == 3, (
            f"20' 2x4 expected n_splices=3, got {ss['n_splices']}"
        )
        assert ss["bottom"]["splice_xs"] == [192.0]
        assert ss["lower_top"]["splice_xs"] == [192.0]
        assert ss["cap"]["splice_xs"] == [160.0], (
            f"cap splice should still land at 160 (24\" offset rule), "
            f"got {ss['cap']['splice_xs']}"
        )

        print("\n[34] frame_building with one wall needing splices")
        # 24' 2x6 wall_a + 96" 2x6 wall_b, joined at wall_a END ->
        # wall_b START, extending_wall=AUTO (longer wall is MAIN).
        # Verifies per-wall splice_summary in the frame_building
        # walls_framed array.
        #
        # wall_a (MAIN at END), paired_t = 5.5" (2x6):
        #   plate_effective_range:
        #     BOTTOM:    (0, 288)        — MAIN keeps lower full
        #     LOWER_TOP: (0, 288)        — same
        #     CAP:       (0, 282.5)      — MAIN cap pulled inboard
        #                                  by paired_t at joint end
        #   Filler stud center at 281.0 + 0.75 = 281.75 (one extra
        #   eligible center beyond the standalone case).
        #   Splices: BOTTOM/LOWER_TOP same as [32] (splice at 192).
        #   CAP range 0..282.5: largest center ≤ 192 outside [168,216]
        #     is 160 -> splice_xs = [160.0]; second cap piece is
        #     282.5 - 160 = 122.5".
        #
        # wall_b (ABUTTING at START), paired_t = 5.5", length 96":
        #   plate ranges: BOTTOM/LOWER_TOP (5.5, 96), CAP (0, 96).
        #   All under 192" -> no splices.
        r = cli.call("add_building", {"name": "SpliceTestBldg"})
        splice_bldg = r["building_name"]
        splice_level = r["level_name"]

        r = cli.call("frame_wall", {
            "length_in": 288.0,
            "height_in": 108.0,
            "nominal": "2x6",
            "spacing_oc_in": 16.0,
            "level": splice_level,
        })
        splice_wall_a = r["wall_name"]

        r = cli.call("frame_wall", {
            "length_in": 96.0,
            "height_in": 108.0,
            "nominal": "2x6",
            "spacing_oc_in": 16.0,
            "level": splice_level,
        })
        splice_wall_b = r["wall_name"]

        cli.call("add_joint", {
            "level_name": splice_level,
            "joint": {
                "wall_a_name": splice_wall_a,
                "wall_b_name": splice_wall_b,
                "wall_a_end": "END",
                "wall_b_end": "START",
            },
        })

        r = cli.call("frame_building", {"level_name": splice_level})
        print(f"  -> walls_framed={r['walls_framed']}")
        wa = next(
            e for e in r["walls_framed"] if e["wall_name"] == splice_wall_a
        )
        wb = next(
            e for e in r["walls_framed"] if e["wall_name"] == splice_wall_b
        )
        assert wa["splice_summary"]["n_splices"] == 3, (
            f"wall_a (288\" 2x6 MAIN) should have 3 splices, got "
            f"{wa['splice_summary']['n_splices']}"
        )
        assert wa["splice_summary"]["bottom"]["splice_xs"] == [192.0]
        assert wa["splice_summary"]["lower_top"]["splice_xs"] == [192.0]
        assert wa["splice_summary"]["cap"]["splice_xs"] == [160.0], (
            f"wall_a cap splice should land at 160 even with cap "
            f"range shortened to (0, 282.5) by MAIN-at-END joint "
            f"context, got {wa['splice_summary']['cap']['splice_xs']}"
        )
        assert wb["splice_summary"]["n_splices"] == 0, (
            f"wall_b (96\" 2x6 ABUTTING) should have 0 splices, got "
            f"{wb['splice_summary']['n_splices']}"
        )

        # ==============================================================
        # v0.6.51 T-joint bridge path coverage ([35]-[41]).
        # ==============================================================
        # v0.6.50 introduced T joints in the operator; the bridge wire
        # format didn't yet accept joint_type='T_JOINT'. v0.6.51 closes
        # that gap. The seven steps below cover:
        #
        #   [35] add_joint with joint_type='T_JOINT' — basic wire-
        #        format acceptance + response echo.
        #   [36] list_joints_in_level — round-trip of all fields
        #        including wall_a_position_in (always emitted, 0.0
        #        for L_CORNER, real value for T_JOINT).
        #   [37] frame_building — T-aware splice pre-flight + the
        #        new n_backing_studs field on walls_framed entries.
        #        Verifies that wall_a's cap is multi-piece (3) from
        #        the T-joint notch + a real splice in the longer
        #        sub-range; that the splice_xs adjacency filter
        #        excludes the notch boundary (80) but includes the
        #        real splice (272); and that n_splices uses the new
        #        len(pieces) - plate_ranges_count[role] formula.
        #        Wall_b's cap is single-piece even though extended
        #        outboard to 99.5" — fits in 192" stock.
        #   [38] frame_wall REBUILD on T_wall_a — verifies the same
        #        T-awareness on the single-wall endpoint as on the
        #        orchestrator's walls_framed entry.
        #   [39] Negative: corner_style='THREE_STUD' with
        #        joint_type='T_JOINT' → INVALID_PARAMS at add_joint
        #        time (Commit 1 combo check).
        #   [40] Negative: corner_style='T_BACKING_STUDS' with
        #        joint_type='L_CORNER' → INVALID_PARAMS, same
        #        combo check.
        #   [41] Negative: wall_a_position_in below the lower bound
        #        (st_a). add_joint succeeds (bridge doesn't read
        #        wall_a length); frame_building fails via
        #        validate_joints with a message identifying
        #        wall_a_position_in. The bad joint is removed after
        #        to keep the Level frameable.
        #
        # All pinned values for [37] / [38] are computed by hand from
        # the v0.6.51 algorithm:
        #
        #   T_wall_a (288" x 108" 2x4 at 16 OC, no openings) is the
        #   THROUGH wall in a T joint at position 80.0 with
        #   wall_b_end='START'. wt_b = 3.5 (2x4 wall thickness),
        #   st_a = 1.5 (2x4 stud thickness).
        #
        #   Backing studs on wall_a (per t_joint_geometry_for_wall_a):
        #     LEFT  backing left-edge = 80 - 1.5 = 78.5
        #     RIGHT backing left-edge = 80 + 3.5 = 83.5
        #     Backing intervals: [78.5, 80.0] and [83.5, 85.0].
        #
        #   Raw OC stud left-edges from templates.stud_positions(288,
        #   16, 1.5): [0, 15.25, 31.25, 47.25, 63.25, 79.25, 95.25,
        #   111.25, 127.25, 143.25, 159.25, 175.25, 191.25, 207.25,
        #   223.25, 239.25, 255.25, 271.25, 286.5] — 19 positions.
        #
        #   filter_studs_around_intervals against backing intervals:
        #   only stud at x=79.25 collides (footprint [79.25, 80.75]
        #   overlaps LEFT [78.5, 80.0] — half-open test passes both
        #   conditions). Operator places 18 OC stud Objects.
        #
        #   n_studs in walls_framed counts placed Objects by name
        #   prefix ({wall_name}_Stud_NN convention) so it matches
        #   the actual scene state — n_studs=18. (Pre-v0.6.51 the
        #   bridge derived n_studs via a pre-flight that only
        #   applied filter_studs_around_openings, missing the
        #   v0.6.50 backing-stud filter; that bug surfaced during
        #   smoke-test commit 6 and was fixed by switching to
        #   Object-name counting.)
        #
        #   Eligible splice anchors (collect_full_height_stud_centers
        #   with backing_stud_left_xs=[78.5, 83.5]):
        #     OC centers + backing centers, sorted, in inches:
        #     0.75, 16, 32, 48, 64, 79.25, 84.25, 96, 112, 128, 144,
        #     160, 176, 192, 208, 224, 240, 256, 272, 287.25.
        #
        #   Plate ranges:
        #     BOTTOM:    [(0, 288)]              — no end joints.
        #     LOWER_TOP: [(0, 288)]              — no end joints.
        #     CAP:       [(0, 80), (83.5, 288)]  — notch at [80,
        #                                          83.5] (= position,
        #                                          position + wt_b).
        #     plate_ranges_count: BOTTOM=1, LOWER_TOP=1, CAP=2.
        #
        #   Splice planning (max_stock_in=192" for 2x4):
        #     BOTTOM (0..288): greedy stops at largest center ≤ 192
        #       = 192 → pieces [(0, 192), (192, 288)],
        #       splice_xs = [192.0].
        #     LOWER_TOP: identical → splice_xs = [192.0].
        #     CAP, sub-range 1 (0..80): 80 ≤ 192 → [(0, 80)], no
        #       splice.
        #     CAP, sub-range 2 (83.5..288): L_eff=204.5 > 192;
        #       ideal_max=275.5. Centers in (83.5, 275.5]: [84.25,
        #       96, 112, 128, 144, 160, 176, 192, 208, 224, 240,
        #       256, 272]. Exclude lower-top splice 192 ± 24
        #       (filters 176, 192, 208). Max candidate = 272 →
        #       pieces [(83.5, 272), (272, 288)].
        #     Combined cap_pieces: [(0, 80), (83.5, 272), (272, 288)]
        #       — 3 pieces.
        #
        #   splice_xs adjacency check (Commit 2 follow-up):
        #     BOTTOM/LOWER_TOP: pieces adjacent → splice_xs=[192.0].
        #     CAP: piece[0].end=80 vs piece[1].start=83.5 — NOT
        #       isclose (3.5" gap) → 80 SKIPPED. piece[1].end=272
        #       vs piece[2].start=272 — isclose → 272 INCLUDED.
        #       cap_splice_xs=[272.0], NOT [80.0, 272.0].
        #
        #   n_splices = len(pieces) - plate_ranges_count[role], per
        #   role, then aggregated:
        #     bot_splices       = 2 - 1 = 1
        #     lt_splices        = 2 - 1 = 1
        #     cap_splices       = 3 - 2 = 1  ← the notch boundary
        #                                      does NOT count
        #     n_splices = 1 * bottom_plate_count (1)
        #               + 1 * (top_plate_count - 1) = 1
        #               + 1 (cap)
        #               = 3.
        #
        #   T_wall_b (96" x 108" 2x4 at 16 OC, no openings, ABUTTING
        #   at START of a T joint with paired_t = wt_a = 3.5):
        #     Raw OC studs: [0, 15.25, 31.25, 47.25, 63.25, 79.25,
        #     94.5] — 7 positions, no filter applies (no backing
        #     studs on wall_b's own side).
        #     Plate ranges: BOTTOM/LOWER_TOP [(0, 96)] (T_JOINT
        #     ABUTTING + non-cap: wall edge, no shortening); CAP
        #     [(-3.5, 96)] (extended OUTBOARD by paired_t).
        #     All ranges ≤ 192" → no splices.
        #     n_splices = 0.
        #
        # ==============================================================
        # Setup: dedicated Building + Level + walls for T-joint tests.
        # Isolated from the L-corner state built up across [20]-[34].
        # ==============================================================
        print(
            "\n[35]-[41] T-joint bridge path coverage — setup: "
            "Building + Level + walls"
        )
        r = cli.call("add_building", {"name": "TJoint_Test_Building"})
        tjoint_level = r["level_name"]

        r = cli.call("frame_wall", {
            "length_in": 288.0,
            "height_in": 108.0,
            "nominal": "2x4",
            "spacing_oc_in": 16.0,
            "level": tjoint_level,
        })
        t_wall_a = r["wall_name"]

        r = cli.call("frame_wall", {
            "length_in": 96.0,
            "height_in": 108.0,
            "nominal": "2x4",
            "spacing_oc_in": 16.0,
            "level": tjoint_level,
        })
        t_wall_b = r["wall_name"]

        r = cli.call("frame_wall", {
            "length_in": 96.0,
            "height_in": 108.0,
            "nominal": "2x4",
            "spacing_oc_in": 16.0,
            "level": tjoint_level,
        })
        t_wall_c = r["wall_name"]

        print(
            f"  -> setup: level={tjoint_level!r}, "
            f"through={t_wall_a!r}, abutting={t_wall_b!r}, "
            f"unused={t_wall_c!r}"
        )

        # --------------------------------------------------------------
        print(
            "\n[35] add_joint: T_JOINT through={a} -> abutting={b} "
            "at pos=80.0".format(a=t_wall_a, b=t_wall_b)
        )
        r = cli.call("add_joint", {
            "level_name": tjoint_level,
            "joint": {
                "joint_type": "T_JOINT",
                "wall_a_name": t_wall_a,
                "wall_b_name": t_wall_b,
                "wall_a_end": "END",       # required, ignored for T
                "wall_b_end": "START",
                "wall_a_position_in": 80.0,
            },
        })
        print(f"  -> joint_index={r['joint_index']}, joint={r['joint']}")
        assert r["joint_index"] == 0, (
            f"first joint should be index 0, got {r['joint_index']}"
        )
        assert r["joint"]["joint_type"] == "T_JOINT"
        assert r["joint"]["wall_a_position_in"] == 80.0, (
            f"wall_a_position_in should echo 80.0, got "
            f"{r['joint']['wall_a_position_in']!r}"
        )
        assert r["joint"]["corner_style"] == "AUTO", (
            f"default corner_style should be AUTO, got "
            f"{r['joint']['corner_style']!r}"
        )
        # extending_wall is emitted even though it's ignored for
        # T_JOINT — schema regularity per Commit 1.
        assert r["joint"]["extending_wall"] == "AUTO"

        # --------------------------------------------------------------
        print("\n[36] list_joints_in_level round-trip")
        r = cli.call("list_joints_in_level", {"level_name": tjoint_level})
        print(f"  -> n_joints={r['n_joints']}")
        assert r["n_joints"] == 1
        j = r["joints"][0]
        # Round-trip parity: every wire field _parse_joint accepts
        # comes back from _joint_to_wire with the same value. T-
        # specific fields (joint_type, wall_a_position_in) must
        # survive the round-trip in full.
        assert j["joint_type"] == "T_JOINT", (
            f"joint_type should round-trip as T_JOINT, got "
            f"{j['joint_type']!r}"
        )
        assert j["wall_a_name"] == t_wall_a
        assert j["wall_b_name"] == t_wall_b
        assert j["wall_a_end"] == "END"
        assert j["wall_b_end"] == "START"
        assert j["wall_a_position_in"] == 80.0, (
            f"wall_a_position_in should round-trip 80.0, got "
            f"{j['wall_a_position_in']!r}"
        )
        assert j["corner_style"] == "AUTO"
        assert j["extending_wall"] == "AUTO"

        # --------------------------------------------------------------
        print(
            "\n[37] frame_building — T-aware splice + n_backing_studs"
        )
        r = cli.call("frame_building", {"level_name": tjoint_level})
        print(
            f"  -> n_walls_framed={r['n_walls_framed']}, "
            f"n_joints_resolved={r['n_joints_resolved']}"
        )
        # Three walls were created at setup, but one (T_wall_c) is
        # unused — n_walls_framed counts everything in the Level
        # because frame_building iterates wall.children regardless
        # of joint participation.
        assert r["n_walls_framed"] == 3, (
            f"expected n_walls_framed=3 (a + b + unused c), got "
            f"{r['n_walls_framed']}"
        )
        assert r["n_joints_resolved"] == 1
        wa = next(
            e for e in r["walls_framed"] if e["wall_name"] == t_wall_a
        )
        wb = next(
            e for e in r["walls_framed"] if e["wall_name"] == t_wall_b
        )
        # ---- T_wall_a (the THROUGH wall) ----
        assert wa["n_studs"] == 18, (
            f"wall_a should have 18 OC studs after backing-stud "
            f"filter (19 raw - 1 at x=79.25 filtered against LEFT "
            f"backing interval [78.5, 80.0]), got {wa['n_studs']}"
        )
        assert wa["n_corner_fillers"] == 0, (
            f"wall_a has no L corners — n_corner_fillers should be "
            f"0, got {wa['n_corner_fillers']}"
        )
        assert wa["n_backing_studs"] == 2, (
            f"wall_a is the through wall in one T joint — should "
            f"have exactly 2 backing studs (LEFT + RIGHT flanking "
            f"wall_b's footprint), got {wa['n_backing_studs']}"
        )
        assert wa["joint_indices_touching"] == [0]
        ss = wa["splice_summary"]
        assert ss["n_splices"] == 3, (
            f"wall_a should have 3 splices (1 bottom + 1 lower-top + "
            f"1 cap in sub-range 2 at x=272; the 80/83.5 notch is "
            f"NOT a splice), got {ss['n_splices']}"
        )
        assert ss["bottom"]["pieces"] == 2
        assert ss["bottom"]["splice_xs"] == [192.0], (
            f"wall_a bottom splice should land at 192 (largest "
            f"eligible center ≤ ideal_max with no exclusion), got "
            f"{ss['bottom']['splice_xs']}"
        )
        assert ss["lower_top"]["pieces"] == 2
        assert ss["lower_top"]["splice_xs"] == [192.0]
        assert ss["cap"]["pieces"] == 3, (
            f"wall_a cap should be 3 pieces — 1 in sub-range 1 "
            f"[0, 80] + 2 in sub-range 2 [83.5, 288] split at 272, "
            f"got {ss['cap']['pieces']}"
        )
        # CRITICAL: the notch boundary (80 or 83.5) MUST NOT appear
        # in splice_xs. The adjacency-aware filter in
        # _splice_xs_from_pieces (Commit 2 follow-up) excludes it.
        # A regression that returns [80.0, 272.0] or [83.5, 272.0]
        # would indicate the adjacency filter broke; a regression
        # that returns [80.0] alone would indicate the splice
        # planner saw the cap as a single range.
        assert ss["cap"]["splice_xs"] == [272.0], (
            f"wall_a cap splice should be [272.0] — the only TRUE "
            f"splice (sub-range 2 [83.5, 288] split at 272). "
            f"Regressions: [80.0, 272.0] = adjacency filter broke; "
            f"[80.0] = splice planner saw cap as single range. "
            f"Got {ss['cap']['splice_xs']}"
        )
        # ---- T_wall_b (the ABUTTING wall) ----
        assert wb["n_studs"] == 7, (
            f"wall_b is 96\" at 16 OC with no openings — should have "
            f"7 OC studs (no backing-stud filter applies; backing "
            f"studs sit on wall_a, not wall_b), got {wb['n_studs']}"
        )
        assert wb["n_corner_fillers"] == 0
        assert wb["n_backing_studs"] == 0, (
            f"wall_b is the abutting wall — backing studs sit on "
            f"the through wall (wall_a). wall_b's n_backing_studs "
            f"should be 0, got {wb['n_backing_studs']}"
        )
        assert wb["joint_indices_touching"] == [0]
        assert wb["splice_summary"]["n_splices"] == 0, (
            f"wall_b (96\" + 3.5\" outboard cap extension = 99.5\" "
            f"effective cap, well under 192\" max stock) should "
            f"have 0 splices, got {wb['splice_summary']['n_splices']}"
        )

        # --------------------------------------------------------------
        print(
            "\n[38] frame_wall REBUILD on T_wall_a — single-wall "
            "splice_summary T-awareness"
        )
        # REBUILD mode reads the wall's parent Level for joint
        # context, so the splice_summary on the single-wall endpoint
        # must match the walls_framed entry from [37]. Verifies the
        # frame_wall REBUILD path uses the same _predict_wall_splice_
        # plans pipeline that frame_building uses.
        r = cli.call("frame_wall", {"wall_target": t_wall_a})
        ss = r["splice_summary"]
        assert ss["n_splices"] == 3, (
            f"REBUILD splice_summary should match [37]'s wall_a "
            f"entry (n_splices=3), got {ss['n_splices']}"
        )
        assert ss["cap"]["pieces"] == 3
        assert ss["cap"]["splice_xs"] == [272.0], (
            f"REBUILD cap.splice_xs should be [272.0] (same as "
            f"[37]'s walls_framed entry — single source of truth "
            f"via _predict_wall_splice_plans), got "
            f"{ss['cap']['splice_xs']}"
        )
        assert ss["bottom"]["splice_xs"] == [192.0]
        assert ss["lower_top"]["splice_xs"] == [192.0]

        # --------------------------------------------------------------
        print(
            "\n[39] negative: add_joint T_JOINT + corner_style="
            "THREE_STUD (combo mismatch)"
        )
        try:
            cli.call("add_joint", {
                "level_name": tjoint_level,
                "joint": {
                    "joint_type": "T_JOINT",
                    "wall_a_name": t_wall_a,
                    "wall_b_name": t_wall_c,
                    "wall_a_end": "END",
                    "wall_b_end": "START",
                    "wall_a_position_in": 144.0,
                    "corner_style": "THREE_STUD",
                },
            })
            raise AssertionError(
                "expected INVALID_PARAMS for T_JOINT + THREE_STUD "
                "combo, but add_joint succeeded"
            )
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")
            err_text = str(e)
            assert "-32602" in err_text or "INVALID_PARAMS" in err_text, (
                f"expected INVALID_PARAMS code, got: {err_text!r}"
            )
            # Error message verbatim per Commit 1's _parse_joint
            # combo check — mirrors templates.validate_joints.
            assert "THREE_STUD" in err_text and "L_CORNER" in err_text, (
                f"expected error mentioning THREE_STUD and L_CORNER, "
                f"got: {err_text!r}"
            )
        # Joint count must stay at 1 — the rejected add_joint should
        # NOT have mutated scene state.
        r = cli.call("list_joints_in_level", {"level_name": tjoint_level})
        assert r["n_joints"] == 1, (
            f"failed add_joint should not mutate joint count; "
            f"expected 1, got {r['n_joints']}"
        )

        # --------------------------------------------------------------
        print(
            "\n[40] negative: add_joint L_CORNER + corner_style="
            "T_BACKING_STUDS (combo mismatch)"
        )
        try:
            cli.call("add_joint", {
                "level_name": tjoint_level,
                "joint": {
                    "joint_type": "L_CORNER",
                    "wall_a_name": t_wall_a,
                    "wall_b_name": t_wall_c,
                    "wall_a_end": "START",
                    "wall_b_end": "END",
                    "corner_style": "T_BACKING_STUDS",
                },
            })
            raise AssertionError(
                "expected INVALID_PARAMS for L_CORNER + "
                "T_BACKING_STUDS combo, but add_joint succeeded"
            )
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")
            err_text = str(e)
            assert "-32602" in err_text or "INVALID_PARAMS" in err_text
            assert "T_BACKING_STUDS" in err_text and "T_JOINT" in err_text, (
                f"expected error mentioning T_BACKING_STUDS and "
                f"T_JOINT, got: {err_text!r}"
            )
        r = cli.call("list_joints_in_level", {"level_name": tjoint_level})
        assert r["n_joints"] == 1, (
            f"failed add_joint should not mutate joint count; "
            f"expected 1, got {r['n_joints']}"
        )

        # --------------------------------------------------------------
        print(
            "\n[41] negative: T_JOINT position below st_a — passes "
            "add_joint, fails frame_building via validate_joints"
        )
        # position=1.0 is below the lower bound st_a=1.5 (2x4 stud
        # thickness). add_joint SHOULD succeed at the bridge layer
        # (the bridge doesn't read wall_a's length at parse time —
        # position bounds need both walls' nominals and wall_a's
        # length, which lives in validate_joints' pre-flight).
        # frame_building SHOULD reject with INVALID_PARAMS naming
        # wall_a_position_in.
        r = cli.call("add_joint", {
            "level_name": tjoint_level,
            "joint": {
                "joint_type": "T_JOINT",
                "wall_a_name": t_wall_a,
                "wall_b_name": t_wall_c,
                "wall_a_end": "END",
                "wall_b_end": "START",
                "wall_a_position_in": 1.0,
            },
        })
        bad_joint_index = r["joint_index"]
        print(
            f"  -> add_joint succeeded (joint_index={bad_joint_index}, "
            f"position=1.0)"
        )
        assert bad_joint_index == 1, (
            f"second joint should be index 1, got {bad_joint_index}"
        )
        try:
            cli.call("frame_building", {"level_name": tjoint_level})
            raise AssertionError(
                "expected INVALID_PARAMS for position=1.0 < st_a=1.5, "
                "but frame_building succeeded"
            )
        except RuntimeError as e:
            print(f"  -> got expected error: {e}")
            err_text = str(e)
            assert "-32602" in err_text or "INVALID_PARAMS" in err_text
            assert "wall_a_position_in" in err_text, (
                f"expected error mentioning wall_a_position_in, "
                f"got: {err_text!r}"
            )
        # Clean up the bad joint to leave the Level frameable.
        r = cli.call("remove_joint", {
            "level_name": tjoint_level,
            "joint_index": bad_joint_index,
        })
        print(f"  -> removed bad joint at index {bad_joint_index}")
        r = cli.call("list_joints_in_level", {"level_name": tjoint_level})
        assert r["n_joints"] == 1, (
            f"after cleanup, only the original T joint should "
            f"remain; expected 1, got {r['n_joints']}"
        )

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

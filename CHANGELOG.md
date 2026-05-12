# Changelog

All notable changes to Praxova Framing are documented here. The project follows [Semantic Versioning](https://semver.org/) with the convention that pre-1.0 versions (0.x) are considered beta — APIs and data model may change between minor versions.

## [0.4.0] — 2026-05-12

### Added
- **"Frame a Wall" composite operator** (`praxova.frame_wall`). The first composition operator in the add-on — everything before this placed or duplicated a single tagged piece. Reads scene-level parameters (length, height, stud size, OC spacing, top + bottom plate counts) and creates a new Empty parent at world origin with N studs and M plates parented underneath. Stud layout follows standard sheathing-aligned convention: end studs flush with wall ends, intermediate studs at OC measured from `x=0`, the final bay tight when wall length isn't a multiple of spacing — preserves 4'/8' sheathing seam alignment. v0.4 scope is a single isolated wall with plain end studs; corner stud treatments (three-stud, California corner) and door/window openings are deferred to later cycles.
- **N-panel "Wall Framing" section** between Fill Edge-to-Edge and Cut List. Property inputs for all six wall parameters, a live preview line that mirrors the operator's validation chain (`Preview: 7 studs x 91.5", 3 plates x 96"` for valid inputs; `Height too short for 4.5" plate stack` or `Length < 3" needed for end studs` for invalid), and a `Frame Wall` button. The preview calls `templates.stud_positions` on every redraw so the count reflects the actual operator behavior including tight-final-bay handling, not a simplified estimate.
- **Stock vs. cut length distinction on lumber tags.** New `stock_length_in` FloatProperty alongside `length_in`. A `frame_wall` stud at 91.5" cut from 8' stock stores `length_in=91.5, stock_length_in=96.0`. `length_in` remains the placement/geometry dimension; `stock_length_in` is what you actually purchase. `add_lumber` sets both to the same value since it places stock as-is, with no cut.
- **Cut list two-subsection LUMBER output.** The LUMBER section now renders as:

  ```
  LUMBER — CUT LIST
        3  x  2x4x8 H
        8  x  2x4x8 V  → cut to 91.5"

  LUMBER — ORDER SUMMARY
       11  x  2x4x8  (3 H, 8 V)
  ```

  CUT LIST is per-piece detail for the saw; ORDER SUMMARY aggregates by stock SKU across orientations — what you actually take to the lumberyard. Pieces where `length_in == stock_length_in` (no cut) appear in CUT LIST without the `→ cut to N"` annotation. SHEETS and PANELS sections are unchanged; neither has a cut-from-stock concept in v0.4.
- **`templates.next_wall_name(existing_names)`** — pure helper picking the lowest unused `Wall_NN` name. Fills gaps when walls are deleted and re-created (`Wall_01` and `Wall_03` present → returns `Wall_02`), matching human expectation better than `max(N) + 1`.
- **`templates.stud_positions(length_in, spacing_oc_in, stud_thickness_in)`** — pure helper returning left-edge x-coordinates following sheathing-aligned framing convention. A 96" wall at 16 OC with 1.5" thick studs returns 7 stud positions with centers at 0.75, 16, 32, 48, 64, 80, 95.25.
- **`templates.select_stock_length_in(nominal, cut_length_in)`** — pure helper returning the smallest `LENGTHS_BY_TYPE[nominal]` stock that fits a cut. Raises `ValueError` for unknown nominal or for cuts longer than any available stock (e.g. a 200" 2x4 cut — max 2x4 stock is 16 ft = 192").
- **Six new fields on `PraxovaSceneProps`** for the wall framing UI: `wall_length_in`, `wall_height_in`, `wall_nominal`, `wall_spacing_oc_in`, `wall_top_plate_count`, `wall_bottom_plate_count`. The `wall_nominal` enum items derive from `templates.LUMBER_TYPES` at class definition time so the dropdown stays in sync with the catalog.

### Changed
- **`PraxovaLumberProps.length_in`** is now `FloatProperty` (was `IntProperty`). Required for fractional inch values like 91.5" from `frame_wall` studs. Existing v0.3.x objects with integer values read back as floats with no data loss — Blender's property system stores values in a generic property bag, and int→float widening is implicit. Going the other direction (float→int) would lose precision; that's why we widened rather than narrowed.
- **`stock_length_in` defaults to 0.0 for v0.3.x-era objects** that pre-date the field. The cut list's `_effective_stock_length_in` helper treats 0 as "no explicit stock, treat as equal to `length_in` (no cut)", matching v0.3.x behavior where `add_lumber` always placed stock as-is. Backward-compat by design rather than by data migration.
- **Smoke test `addon_version` pin** "0.3.4" → "0.4.0". Method count stays at 11 — the `frame_wall` MCP tool lands in v0.4.1 per the "UI in vN, bridge parity in vN+1" cadence.
- **README** Status line updated, new "Frame a Wall" bullet in *What it does*, `stock_length_in` added to the data-model table with the updated `length_in` description (cut vs stock), cut-list section documents the two-subsection LUMBER format, roadmap marks v0.4 done and adds an explicit v0.4.1 bridge-parity entry.

### Architecture notes
- **Composite operator separation of concerns.** `ops_frame.py` is a new module distinct from `ops_add.py` (single-piece placement) and `ops_duplicate.py` / `ops_fill.py` (single-axis arrays). The naming convention is `ops_<verb>.py` — add, duplicate, fill, frame, cutlist, units. Future cycles will add door/window openings and corner stud treatments in the same module.
- **Pure-function helpers in `templates.py`.** The three new helpers have no `bpy.` references, so the math is reasonable about without Blender in the loop. They live in a new "Composite framing helpers (v0.4)" section between mesh construction and the v0.1 backward-compat aliases. Future composite operators will add their helpers in the same section. Promotion to a separate `helpers.py` module is deferred until that section earns its own file.
- **Empty parent at world origin, children placed in world coordinates.** The wall Empty lands at `(0, 0, 0)` and each plate/stud is created with its world-coordinate `location` set explicitly. Then `child.parent = empty` happens after placement. Because the parent is at origin, the child's local location equals its world location — no `matrix_parent_inverse` fiddling required. The user transforms the Empty afterward to position the wall in the larger model; children follow.
- **Mesh namespace partitioned by operator.** `add_lumber` meshes use `praxova_mesh_<label>` (e.g. `praxova_mesh_2x4x8_V`); `frame_wall` meshes use `praxova_mesh_wall_<role>_<nominal>_<length_in>` (e.g. `praxova_mesh_wall_stud_2x4_91.5`). No collisions even when dimensions coincide. Two `frame_wall` calls with identical parameters share meshes naturally.
- **`frame_wall` MCP tool deferred to v0.4.1** per the "UI parity in vN, bridge parity in vN+1" cadence established starting v0.3.2. v0.4.0 is strictly UI; v0.4.1 will add the bridge handler, the FastMCP tool, and the smoke-test extension that exercises it, bringing method count 11 → 12.

## [0.3.4] — 2026-05-11

### Added
- **Bridge `duplicate_e2e` MCP tool.** Completes bridge parity for the v0.3.3 Fill operator. Required: `count` (1-500). Optional: `direction` (FORWARD/BACK, default FORWARD), `target_name`. **No spacing parameter** — spacing is automatically the source's own width, matching the UI's behavior exactly. LLM agents that need custom-spaced arrays continue to use `duplicate_oc`. Brings the bridge surface to eleven methods: `ping`, `list_materials`, `list_objects`, `get_scene_info`, `add_lumber`, `add_sheet`, `add_panel`, `duplicate_oc`, `duplicate_e2e`, `generate_cutlist`, `set_imperial_units`.
- **Smoke test `duplicate_e2e` step.** New `[8]` step fills 3 panels forward from the metal panel, asserting `source`, `width_in == 36.0`, `count`, `direction`, and `len(new_objects) == 3`. Subsequent step numbers shift; `[9] list_objects` count assertion goes from 7 to 10; `[10] generate_cutlist` now also verifies the metal panel appears with count 4 in the cut-list body (confirming fill duplicates carry their cut-list tags through `obj.copy()` and group correctly).
- **Smoke test LUMBER-refusal guard.** New `[12]` step calls `duplicate_e2e` on a lumber object and asserts the response is `-32602 INVALID_PARAMS` with a "lumber" mention in the message. Pins the bridge-side LUMBER refusal in place against future refactors.
- **Smoke test version pin.** `[1] ping` now asserts `addon_version == "0.3.4"` and `method_count == 11`. Catches stale Blender builds loaded against the test — the most common cause of confusing smoke-test failures.

### Changed
- **`mcp_server` package version** 0.3.2 → 0.3.4 (skipping 0.3.3 since that was a UI-only cycle with no MCP-side changes; manifest and Python package versions are now back in sync).
- **Bridge `ping`** reports `addon_version: "0.3.4"` (was `"0.3.2"`).
- **Module docstrings** of `mcp_server/server.py` and `smoke_test.py` updated to mention fill alongside the existing capabilities.
- **README** MCP-bridge usage line lists all eleven tools (`duplicate_e2e` added); roadmap marks v0.3.4 done.

### Architecture notes
- Bridge validation pattern for `duplicate_e2e` mirrors `duplicate_oc`'s: required `count` bound-checked (1-500), optional `direction` and `target_name`, target resolved either by name or via the active object with appropriate `APP_NO_ACTIVE_OBJECT` / `APP_OBJECT_NOT_FOUND` error codes. The LUMBER refusal happens in the bridge handler rather than letting the operator's `report()` bubble up as `APP_OPERATOR_FAILED` — clean error codes are more useful to LLM agents than generic operator-failed messages.
- The response includes `width_in`, the actual spacing used. Useful for the client to verify (especially in tests) what the operator decided to do, since the source's own width isn't directly visible from the parameters.
- This release completes the v0.3.x "feature in vN, bridge parity in vN+1" cycle that began with v0.3.1 (UI: panels) → v0.3.2 (bridge: `add_panel`) → v0.3.3 (UI: fill) → v0.3.4 (bridge: `duplicate_e2e`). v0.4 starts a new feature cycle.

## [0.3.3] — 2026-05-10

### Added
- **Fill Edge-to-Edge operator** (`praxova.duplicate_e2e`) for sheets and panels. Duplicates the active source object N times along its local +Y or -Y axis at edge-to-edge spacing (the source's own width). Use to sheathe a wall or cover a roof in one click. Refuses LUMBER active objects with a message pointing back to the OC duplicator.
- **N-panel "Fill Edge-to-Edge" section** directly under "On-Center Duplicate". Two preset distance rows (8'/12'/16' and 20'/24'/32'), an auto-computing `Fill Length` field, a manually-editable `Fill Count` override, a Forward/Back direction toggle, and a `Fill` button. Status line confirms the source and exact width when a compatible active object is selected; shows a "Select a sheet or panel" hint otherwise.
- **`templates.fill_axis_width_in(obj)`** — cross-category helper returning the local-Y width in inches for a sheet or panel. Single source of truth used by both the Fill operator and the `fill_span_in` update callback. Returns 0.0 for LUMBER and for unknown size keys, letting callers decide how to handle.
- **`PraxovaSceneProps.fill_count`, `fill_span_in`, `fill_direction`** — three new scene fields backing the UI. The `fill_span_in` update callback (`_on_fill_span_change`) recomputes `fill_count = ceil(span / width)` from the active object's width using the helper above, so clicking a preset atomically sets both span and count.
- **`PRAXOVA_OT_set_fill_span`** internal operator powering the preset buttons (mirrors `PRAXOVA_OT_set_spacing`'s role for the OC duplicator).

### Architecture notes
- Operator mirrors `praxova.duplicate_oc`'s pattern: world-space step from `obj.matrix_world.to_3x3().col[1]` so rotated sources (e.g. roof panels tilted onto a slope) fill along their own width direction rather than along world-Y. Linked-mesh copies via `obj.copy()` — same memory and cut-list semantics as OC Duplicate.
- LUMBER refusal is enforced at three layers: `fill_axis_width_in` returns 0.0 for LUMBER, the operator refuses with a redirect to OC Duplicate, and the UI's "Select a sheet or panel" hint front-loads the obvious case. The hint doesn't disable inputs — users can pre-stage values before selecting a source, mirroring how OC Duplicate behaves.
- Bridge MCP tool intentionally deferred to v0.3.4. v0.3.2 established the "UI parity in vN, bridge parity in vN+1" cycle; v0.3.3 sticks to that.
- The new `templates.fill_axis_width_in` lives in its own "Tag helpers (cross-category)" section between the panel data and mesh construction. Future tag-reading helpers (e.g. for a future export pipeline) have an obvious home there.
- `mcp_server` package version unchanged at 0.3.2 (no MCP-side changes this cycle).

## [0.3.2] — 2026-05-10

### Added
- **Bridge `add_panel` MCP tool.** Mirrors `add_sheet` semantics with `material`, `size`, `orientation`, and optional `location_m` parameters. Brings the bridge surface to ten methods: `ping`, `list_materials`, `list_objects`, `get_scene_info`, `add_lumber`, `add_sheet`, `add_panel`, `duplicate_oc`, `generate_cutlist`, `set_imperial_units`.
- **Bridge `list_materials` panel data.** New `panel_sizes` (size key → coverage width and length in inches) and `panel_materials` (list of `{material, label, profile_height_in}`) keys, exposing the v0.3.1 panel catalog so an LLM agent can discover panel options at runtime.
- **Smoke test `add_panel` step.** `smoke_test.py` now exercises panel placement, asserts the cut-list output contains LUMBER + SHEETS + PANELS sections when all three are present, and guards against the pre-v0.3.2 `_serialize_object` regression by checking that `panel_material` and `panel_size_key` are returned (and `sheet_material` is not) for panel objects. Total numbered checks: 11.
- **README "Working with linked-mesh duplicates"** section explains the rotation/Apply tradeoff with linked mesh data and when to use *Make Single User → Object & Data*.
- **README "Metal panels — generic profile"** section documents the per-material 0.75" profile placeholder and the deferred ribbed-geometry roadmap.
- **Roadmap entry: v0.3.3 — Fill operator** for sheets and panels, lays edge-to-edge across a span using the sheet's *width* (local Y) as spacing. Distinct from the OC duplicator, which uses center-to-center spacing along local X for studs.

### Changed
- **MCP `add_lumber` Literal extended to all v0.3.1 sizes.** The `nominal` parameter type now accepts `1x2`, `2x3`, `4x4`, and `4x6` in addition to the original six. The bridge handler already accepted these via `templates.LUMBER_TYPES`, but the MCP tool's type signature was rejecting them client-side before any network call. v0.3.1 carryover bug — now in sync.
- **Bridge `_serialize_object` fixed for the PANEL category.** Previously, the function had a `LUMBER` branch followed by a bare `else` that hard-coded sheet-specific fields. Panel objects (added in v0.3.1) silently fell through and returned with empty `sheet_material` / `sheet_thickness_callout` / `sheet_size_key` strings. Now three explicit branches; panel objects expose `panel_material` and `panel_size_key`.
- **Bridge `ping`** reports `addon_version: "0.3.2"` (was `"0.3.0"`).
- **`mcp_server` package version** 0.3.0 → 0.3.2 (skipping 0.3.1, since no separate `mcp_server` release was made for it; manifest and Python package versions are now back in sync).
- **README sections** updated for the v0.3.1 reality (full lumber list, panels, two-row OC presets, three-section cut list, PANEL data model fields).

### Architecture notes
- Panel validation in the bridge handler mirrors sheet validation: required `material` checked against `templates.PANEL_MATERIAL_PROFILE`, required `size` checked against `templates.PANEL_SIZES`, optional `orientation` defaulting to `VERTICAL`, optional `location_m` reusing the shared `_location_param` helper.
- Profile height is **not** a bridge parameter. The per-material default in `PANEL_MATERIAL_PROFILE` (0.75" for `METAL`) is the source of truth. A `profile_height_override` parameter could be added later if a use case appears, but the design intent is that LLM agents shouldn't need to think about rib geometry to place panels correctly.

## [0.3.1] — 2026-05-10

### Added
- **Lumber:** four new dimensional sizes.
  - **1x2** furring strip (0.75" × 1.5"), 8' length.
  - **2x3** interior partition / blocking (1.5" × 2.5"), 8/10/12' lengths.
  - **4x4** post (3.5" × 3.5"), 8/10/12/14/16' lengths.
  - **4x6** mid-weight beam / header (3.5" × 5.5"), 8/10/12/14/16/20' lengths.
- **Panels:** new third material category alongside Lumber and Sheets. 36"-wide metal roofing/siding panels at 8'/12'/16'. Modeled as a flat slab with a 0.75" generic profile placeholder; a future patch will replace the slab with a proper corrugation generator.
- **OC presets** 8' and 10' for timber/post framing, in a second preset row labeled in feet (existing 12"/16"/19.2"/24" presets unchanged, on the first row).

### Changed
- Cut list now has three sections: LUMBER, SHEETS, PANELS. The grand-total breakdown shows category subtotals whenever 2 or more categories have items (previously only LUMBER+SHEETS).
- Add-menu lumber order is now small-to-large by cross-section (1x2 first, 6x6 last) so the dropdown reads naturally.
- Active-object info panel branches on three categories with explicit `elif` chains; previously a sheet branch fell out of an `else`.

### Architecture notes
- The `category` enum on `PraxovaLumberProps` widens from `LUMBER/SHEET` to `LUMBER/SHEET/PANEL`. Enum widening is backward-compatible: existing v0.3.0 .blend files load unchanged.
- New tag fields `panel_material` (enum) and `panel_size_key` (string) on `PraxovaLumberProps`. They follow the same denormalized cut-list-label pattern as lumber and sheets.
- Panel cut-list label format `'36" Metal x 8 V'` is built by `templates.panel_cutlist_label()` and stored on each Object. Changing the format later affects new objects only; existing scene objects keep their stored labels until a future "refresh labels" pass walks them — that pass will ship alongside the corrugation generator.
- The MCP bridge does **not** yet expose an `add_panel` tool. UI parity confirmed first; bridge tool lands in v0.3.2.

## [0.3.0] — 2026-05-10

### Added
- **MCP bridge.** A localhost JSON-RPC bridge inside Blender (`server/`) and a separate FastMCP server process (`mcp_server/`) so an LLM client like Claude Desktop can drive the existing operators. Eight tools exposed: `add_lumber`, `add_sheet`, `duplicate_oc`, `generate_cutlist`, `set_imperial_units`, `list_materials`, `list_objects`, `get_scene_info`.
- **Bridge operators.** `praxova.start_bridge` and `praxova.stop_bridge` to control the listener.
- **N-panel "MCP Bridge" subsection** with port input, running-state indicator, and start/stop button.
- **Scene property** `bridge_port` (default 9876) for the user to configure the bridge listen port.
- `smoke_test.py` at the repo root: a stdlib-only client that exercises the bridge end-to-end without the MCP layer. Useful for diagnosing protocol issues independently of any MCP client.
- `mcp_server/` Python package (`praxova-framing-mcp` console script) with its own README covering install via `uv tool install` or `pipx install` and Claude Desktop configuration.

### Architecture notes
- The bridge runs a background listener thread inside Blender; each client connection spawns its own thread, but all bpy mutation is dispatched through `bpy.app.timers.register` onto Blender's main thread so concurrent connections cannot race on bpy state.
- The MCP server process opens one short-lived TCP connection per tool call: stateless and robust to bridge restarts. Latency over loopback is sub-millisecond.
- Wire protocol: newline-delimited JSON-RPC 2.0. Error codes follow the standard (-32700, -32600, -32601, -32602, -32603) with app-defined codes in the -32000..-32099 range for empty cut list, missing active object, missing target object, and operator-cancelled outcomes.
- Bridge running-state is module-level transient process state, intentionally NOT a Scene PropertyGroup field — saving and reopening a .blend cannot lie about whether the bridge is up.

### Changed
- `unregister()` now stops the bridge before tearing down the module, so the listener thread doesn't keep a stale module reference after a Blender Reload Scripts.

## [0.2.0] — 2026-05-07

### Added
- **6x6 lumber** with stock lengths 8'/10'/12'/14'/16'/20'.
- **Sheet goods** — plywood and OSB at 1/2" and 3/4" call-outs, 4x8 size, vertical and horizontal orientations.
- Cut list now also writes to a `<blendfile>_cutlist.txt` file alongside the saved `.blend`, in addition to the in-Blender Text datablock.
- Cut list output is split into LUMBER and SHEETS sections with subtotals plus a grand total.
- Active-object info panel now handles sheets, showing call-out, actual thickness, size, and orientation.
- New `category` field on the per-object PropertyGroup (`'LUMBER'` or `'SHEET'`).
- New sheet-specific PropertyGroup fields: `sheet_material`, `sheet_thickness_callout`, `sheet_size_key`.

### Changed
- Renamed `templates.make_lumber_mesh` → `templates.make_box_mesh` (alias preserved for backward compat).
- Renamed `templates.cutlist_label` → `templates.lumber_cutlist_label` (alias preserved for backward compat).

### Standards encoded
- Sheet thickness actuals follow APA PS 1 (plywood) and APA PS 2 (OSB):
  - 1/2" plywood = 15/32" (0.469")
  - 1/2" OSB = 7/16" (0.438")
  - 3/4" plywood = 23/32" (0.719")
  - 3/4" OSB = 23/32" (0.719")

## [0.1.0] — 2026-05-07

### Added
- Lumber templates: 2x4, 2x6, 2x8, 2x10, 2x12 in 8'/10'/12'/14'/16' lengths (2x10 and 2x12 from 10').
- Vertical and horizontal orientations for each template.
- Add-menu integration: 3D View Add → Praxova Lumber → per-size submenus.
- Tagging via registered PropertyGroup (Blender 5.0+ recommended pattern, replaces deprecated dict-style custom properties for add-on use).
- Linked-data mesh sharing across instances of the same template (memory-efficient, doesn't break tagging).
- On-center spacing duplicator with preset buttons (12", 16", 19.2", 24"), custom spacing, count, and Right/Left direction toggle.
- Cut list generator that walks the scene, groups by label, and writes to a Blender Text datablock.
- N-panel UI on the "Praxova" tab including a one-shot "Set Scene to Imperial" helper.
- Blender 5.x extension manifest (`blender_manifest.toml`).

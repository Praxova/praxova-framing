# Changelog

All notable changes to Praxova Framing are documented here. The project follows [Semantic Versioning](https://semver.org/) with the convention that pre-1.0 versions (0.x) are considered beta — APIs and data model may change between minor versions.

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

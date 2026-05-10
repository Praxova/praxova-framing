# Changelog

All notable changes to Praxova Framing are documented here. The project follows [Semantic Versioning](https://semver.org/) with the convention that pre-1.0 versions (0.x) are considered beta — APIs and data model may change between minor versions.

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

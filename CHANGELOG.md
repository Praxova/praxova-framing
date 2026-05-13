# Changelog

All notable changes to Praxova Framing are documented here. The project follows [Semantic Versioning](https://semver.org/) with the convention that pre-1.0 versions (0.x) are considered beta — APIs and data model may change between minor versions.

## [0.5.1] — 2026-05-12

### Added
- **Bridge `frame_wall` openings parameter.** The handler in `server/handlers.py` now accepts an optional `openings` list, each entry a dict with `type` (lowercase `"door"`/`"window"`), `x_offset_in`, `ro_width_in`, `ro_height_in`, and optional `sill_height_in` (required for windows, defaults 0 for doors), `header_nominal` (defaults to wall nominal), and `jack_count` (defaults via `templates.recommend_jack_count`: 2 for openings ≥72", else 1). Mirrors the v0.5 UI's `PraxovaWallOpening` PropertyGroup exactly. Bridge surface stays at twelve methods — `frame_wall` is being extended, not added.
- **Bridge `frame_wall` opening pre-validation.** New `_parse_openings` helper validates each opening dict's shape (required fields, types, choice membership) with 1-based opening indices in error messages (e.g. `"Opening 2: missing required \"ro_width_in\""`). Cross-field rules (within wall, pairwise overlap, header fits under top plates, sill clears bottom plate) run through `templates.validate_openings` — the same validator the v0.5 UI's live preview uses, so an LLM agent and a human in Blender get identical failure modes for the same inputs.
- **Bridge `frame_wall` return shape additions.** Two always-present fields: `n_openings` (0 when openings omitted) and `openings_summary` (empty list when none). `openings_summary` carries one dict per opening with the actual values used after default-fill — `type`, `jack_count`, `header_nominal`, `jack_length_in`, `header_length_in`, `n_header_cripples`, `n_sill_cripples`. Computed by calling `templates.opening_framing_layout` for each opening after the operator runs, so the dict reflects exactly the geometry that was placed (single source of truth for both placement and reporting). `n_studs` semantics adjusted: it now means "regular OC studs after filtering around king brackets" — kings, jacks, and cripples are counted separately via `openings_summary`. With no openings, `n_studs` matches v0.4.1 exactly.
- **FastMCP `frame_wall` tool openings parameter.** The MCP tool function gains a `openings: list[dict] | None = None` parameter, passed through to the bridge unchanged. Tool docstring grew from ~80 lines to ~160 lines: a dedicated `openings` section documents every field (required/optional, type, semantics, default-fill), two worked examples (single door, door + window), the new `n_openings` / `openings_summary` return shape, and a pointer at README "Header sizing" for the load-aware caveat on `header_nominal`. Module docstring updated to mention door/window openings alongside the existing capabilities.
- **Smoke test step [10] exercising the new openings flow.** Frames a 96"×96" 2x4 wall at 16" OC with a single 38"×82" RO door at x_offset=29 — chosen so the king-bracket math lands on round inches. Pins: `n_studs == 4` (raw OC of 7, with 3 dropped for king-bracket overlap), `n_openings == 1`, `openings_summary[0]` has `jack_count=1` (auto-derived), `header_nominal="2x4"` (default), `jack_length_in=80.5`, `header_length_in=41.0`, `n_header_cripples=3`, `n_sill_cripples=0`, and `len(new_objects) == 18`. The renumbered `[12] generate_cutlist` step adds three new "cut to N\"" annotation assertions — `"cut to 80.5"` (jacks), `"cut to 41"` (header members; integer per `_format_inches`' trailing-zero strip on 41.0), and `"cut to 7.5"` (header cripples) — pinning the v0.5 piece types in the cut-list rendering. Renumbered `[11] list_objects` count assertion goes 16 → 32 (16 existing + 16 new tagged pieces; the untagged 1/2" plywood spacer doesn't count). Subsequent error-path steps shift to `[13]`/`[14]`/`[15]`. Total numbered steps: 14 → 15.

### Changed
- **`mcp_server` package version** 0.4.1 → 0.5.1 (skipping 0.5.0, which was a UI-only cycle with no MCP-side changes; the git tag on `main` is the canonical record of cycle correspondence). Project description also updated to mention "door/window openings" alongside the existing wall-framing capability.
- **Smoke test `addon_version` pin** "0.5.0" → "0.5.1". Method count stays at 12. Module docstring updated to mention "v0.5.1 RPC surface (12 methods)" and "wall framing with optional door/window openings".
- **README** Status line updated to v0.5.1; MCP bridge usage section now mentions that `frame_wall` accepts an optional `openings` array. Roadmap v0.5.1 marked done.

### Architecture notes
- **`UI in vN, bridge parity in vN+1` cadence held.** v0.5 shipped door/window openings as a UI-only cycle (operator extension, properties, UIList, helpers); v0.5.1 adds the bridge handler's `openings` parameter, the FastMCP tool's `openings` parameter, and the smoke-test step that exercises them end-to-end. Same pattern as v0.3.1→v0.3.2 (panels), v0.3.3→v0.3.4 (fill), and v0.4→v0.4.1 (`frame_wall`).
- **`templates.validate_openings` is the single source of truth for cross-field validation.** The v0.5 UI's live preview, the v0.5 operator's pre-flight check, and the v0.5.1 bridge handler all call it with the same arguments and surface the same `"Opening N ..."` messages. Per-opening dict-shape validation (required fields, types, choice membership) is bridge-specific — those checks have no UI analog because Blender PropertyGroup bounds already enforce shape — but the cross-field rules are shared.
- **`openings_summary` computed from `opening_framing_layout`, not the operator's child objects.** Like `n_studs` in v0.4.1, the post-operator summary is derived from the same pure-function geometry the operator used, not from filtering child names or counting tagged pieces. The naming convention is `King_Op00_L`/`Jack_Op00_L_01`/etc. today, but could change; the function call won't. Cripple counts match the operator's placement logic — OC stud positions whose full thickness fits inside the king-bracket inner range `[king_left_x + t, king_right_x - t]`.
- **n_studs semantic change is opt-in.** Calls with no `openings` parameter (or `openings=[]`) get the v0.4.1 behavior — `n_studs` equals the raw OC count. Calls with openings get the filtered count, with the difference counted via `openings_summary`. No backward-compat shim needed in the bridge return shape; just two new always-present fields (`n_openings`, `openings_summary`) that default to 0 / `[]`.
- **Spacer is invisible to the cut list AND to the smoke test's list_objects assertion.** The 1/2" plywood spacer between header members is the only untagged scene member the operator creates (the design's "sheathing scrap" convention). The smoke test's `[11] list_objects` count assertion (32) reflects this: every other new opening piece contributes a tagged Object, but the spacer doesn't. The Empty parent is untagged too.

## [0.5.0] — 2026-05-12

### Added
- **Door and window openings on `frame_wall`** — the operator now reads a list of openings from the scene and places king studs, jacks, a (2) 2x + 1/2" plywood spacer header build-up, optional rough sills (windows), and optional cripples above the header and below the rough sill. Regular OC studs that would collide with any king bracket are dropped via `templates.filter_studs_around_openings`. Plates remain continuous through door openings — the "framed-but-not-cut" state, since framers cut the bottom plate at door swings after the wall is stood up. Header members get the opening's `header_nominal` (defaulting to wall nominal); header Y-stackup is hardcoded to the residential 1.5 + 0.5 + 1.5 = 3.5" flush to the y=0 face regardless of wall depth.
- **`PraxovaWallOpening` PropertyGroup** with seven fields: `opening_type` (DOOR/WINDOW), `x_offset_in`, `ro_width_in`, `ro_height_in`, `sill_height_in` (windows only; pinned to 0 for doors regardless of field value), `header_nominal`, and `jack_count`. Plus `wall_openings` (CollectionProperty) and `wall_openings_active` (IntProperty) on `PraxovaSceneProps`. Registration order in `__init__.py` puts `PraxovaWallOpening` before `PraxovaSceneProps` so the latter's `CollectionProperty(type=PraxovaWallOpening)` resolves.
- **Five pure helper functions in `templates.py`** (new "Opening helpers (v0.5)" section): `recommend_jack_count(ro_width_in)` — IRC R602.7 convention (2 jacks per side for openings ≥72", else 1); `opening_framing_layout(opening, wall_nominal, wall_height_in, top_plate_count, bottom_plate_count)` — returns king/jack x-coords, header range, member length, spacer y range, optional rough sill range, king/jack cut lengths, and top/bottom cripple zones; `filter_studs_around_openings(...)` — standard interval-overlap test to drop colliding OC studs; `validate_openings(...)` — runs the four cross-field checks (within wall, no pairwise overlap, header fits under top plates, sill clears bottom plates) and returns `(False, "Opening N ...")` on the first failure with 1-based indices; `redistribute_openings_evenly(...)` — sets each opening's `x_offset_in = (wall_length × (i+1) / (n+1)) - (ro_width / 2)`.
- **N-panel "Openings" sub-section** within Wall Framing. Sub-box containing a `PRAXOVA_UL_openings` UIList on the left, a per-row operator column on the right (Add Door / Add Window / Remove / Distribute), and a detail panel below for the active opening's fields. `sill_height_in` is only visible for windows.
- **Four new UI operators**: `praxova.add_door` (38"×82" RO defaults), `praxova.add_window` (36"×48" RO at 36" sill), `praxova.remove_opening`, and `praxova.distribute_openings`. The add operators set defaults including `jack_count` from `recommend_jack_count`, call `redistribute_openings_evenly` to nudge all openings to even spacing, then advance the active index to the new row.
- **Live preview with opening-aware validation.** When openings exist, the preview line first runs `validate_openings` and shows the specific failure message (with the offending opening's 1-based index) on failure. On success, the format becomes `Preview: N studs + M openings, P plates × L"`, where N is the post-filter regular stud count — computed via the same `stud_positions → opening_framing_layout → filter_studs_around_openings` chain the operator uses, so the count reflects exactly what `Frame Wall` will produce.
- **README "Header sizing" section** between *Metal panels — generic profile* and *Geometry orientation*. Documents that `header_nominal` defaults to wall nominal (a geometric default, not a structural one), provides a rough starting-point table by RO width for load-bearing exterior walls, and points readers at IRC R602.7 and an engineer for spans outside the prescriptive tables.

### Changed
- **Class registration order in `__init__.py`.** `PraxovaWallOpening` slotted between `PraxovaLumberProps` and `PraxovaSceneProps`. The new UIList class and four new opening operators added to `static_classes` ahead of `PRAXOVA_PT_main_panel`.
- **Lumber-type enum items refactored to a module-level callback.** Previously the inline list comprehension in `PraxovaSceneProps.wall_nominal` was the only source; now `_LUMBER_TYPE_ITEMS` plus `_lumber_type_items_callback` at module scope in `properties.py` feeds both `wall_nominal` and the new `PraxovaWallOpening.header_nominal`. The list is held at module scope so the strings stay alive across callbacks (the documented `bpy.props` GC pitfall).
- **`smoke_test.py` `addon_version` pin** "0.4.1" → "0.5.0". Method count stays at 12 — bridge parity for openings (extending the `frame_wall` MCP tool to accept an `openings` array and exercising it in the smoke test) is deferred to v0.5.1 per the "UI in vN, bridge parity in vN+1" cadence. Module docstring updated to mention the v0.5.0 RPC surface.
- **`README` Status line** "Beta (v0.4.1)" → "Beta (v0.5.0)"; *What it does* Frame a Wall bullet now mentions door and window openings; Roadmap marks v0.5 done and adds an explicit v0.5.1 entry for bridge parity.

### Architecture notes
- **"UI in vN, bridge parity in vN+1" cadence held.** v0.5 ships UI parity for openings — operator extension, properties, UIList, helper functions — without touching `mcp_server/`. v0.5.1 will add the `openings` array parameter to the `frame_wall` MCP tool plus the smoke test extension that exercises it, matching v0.3.1→v0.3.2, v0.3.3→v0.3.4, and v0.4→v0.4.1.
- **Pure-function helpers below the operator.** All five new `templates.py` helpers are pure Python — no `bpy.*` calls, only attribute access on the duck-typed PropertyGroup. The math is reasonable about without Blender in the loop, same as the v0.4 composite framing helpers. `redistribute_openings_evenly` mutates the opening fields but still touches no bpy functions.
- **Mesh namespace partitioned by role.** The `praxova_mesh_wall_<role>_<nominal>_<length>` pattern extends naturally to the new pieces: `stud` (shared by kings + regular studs — same cross-section + length), `jack`, `header` (keyed off `header_nominal`, not the wall's), `header_spacer` (untagged scrap, no nominal in the mesh name), `rough_sill`, `header_cripple`, and `sill_cripple`. Two `frame_wall` runs with identical openings share meshes naturally.
- **Header spacer is the only untagged piece.** It gets a mesh, a parent assignment, and a name, but no `praxova_lumber.is_lumber = True` — invisible to the cut list. Real builds source the 1/2" plywood from sheathing offcuts so no order line is appropriate.
- **Object naming for opening pieces.** Per the design table verbatim: `King_Op<MM>_L`, `Jack_Op<MM>_L_<idx>`, `Header_Op<MM>_<idx>`, `HeaderSpacer_Op<MM>`, `Sill_Op<MM>`, `HeaderCripple_Op<MM>_<idx>`, `SillCripple_Op<MM>_<idx>`. `<MM>` is the 0-based opening index zero-padded to 2 digits. Regular studs and plates keep their v0.4 `Wall_NN_…` names.
- **The five v0.5 commits.** (1) `PraxovaWallOpening` + scene fields + registration order. (2) Five opening helpers in `templates.py`. (3) `ops_frame.execute()` extended with the 8-step opening flow. (4) UIList + four operators + panel sub-section + preview update. (5) This release commit — manifest + `__version__` + CHANGELOG + README.

## [0.4.1] — 2026-05-12

### Added
- **Bridge `frame_wall` MCP tool.** Completes bridge parity for the v0.4 composite operator. Required: `length_in` (number > 0) and `height_in` (number > 0). Optional: `nominal` (default `"2x4"`), `spacing_oc_in` (default 16.0), `top_plate_count` (default 2, range 1–4), `bottom_plate_count` (default 1, range 1–4), `location_m` (default world origin). Returns the new Empty parent's name, echoes of all inputs with defaults filled in, `n_studs` (from `stud_positions`), `n_plates` (= top + bottom), `stud_length_in`, `stud_stock_in`, and `plate_stock_in` (for material ordering), plus `new_objects` (sorted list of Empty + all child names). Brings the bridge surface to twelve methods: `ping`, `list_materials`, `list_objects`, `get_scene_info`, `add_lumber`, `add_sheet`, `add_panel`, `duplicate_oc`, `duplicate_e2e`, `frame_wall`, `generate_cutlist`, `set_imperial_units`.
- **Bridge `frame_wall` pre-validation.** Same cross-field validation as the operator (nominal in `LUMBER_TYPES`, `length_in >= 2 * thickness_in`, stud length positive after the plate stack, both stud and plate stock fit `LENGTHS_BY_TYPE[nominal]`) so impossible geometry surfaces as a clean `-32602 INVALID_PARAMS` error rather than the operator's `-32004 APP_OPERATOR_FAILED`. The operator's internal validation remains as defense in depth.
- **Smoke test `frame_wall` step.** New `[9]` step frames a 48" × 96" 2x4 wall at 24" OC with default plate counts, asserting `wall_name`, `n_studs == 3`, `n_plates == 3`, `stud_length_in == 91.5`, both stock fields equal 96.0, and `len(new_objects) == 7` (1 Empty + 3 studs + 3 plates). Subsequent step numbers shift; `[10] list_objects` count assertion goes from 10 to 16. `[11] generate_cutlist` adds an assertion that `"cut to 91.5"` appears in the body, pinning the v0.4 stock-vs-cut annotation in the LUMBER — CUT LIST subsection against future regressions.
- **`__version__` constant in `__init__.py`.** Single source of truth for the Python side. Imported by `server/handlers.py` so `ping()` no longer carries its own copy. PEP 8 §2 placement: after the module docstring, before any other imports except `__future__`.

### Changed
- **`mcp_server` package version** 0.3.4 → 0.4.1 (skipping 0.4.0, which was a UI-only cycle with no MCP-side changes; the git tag on `main` is the canonical record of cycle correspondence). Project description also updated to mention "wall framing" alongside the existing capabilities.
- **Smoke test `addon_version` pin** "0.4.0" → "0.4.1". Method count 11 → 12. Module docstring updated to "v0.4.1 RPC surface (12 methods)".
- **`server/handlers.py:ping()`** imports `__version__` from `__init__.py` instead of returning a hardcoded string. Resolves the late-cycle bug pattern from v0.4.0 (the bridge said `"0.3.4"` while the manifest said `"0.4.0"` — a UI-only cycle hadn't bumped the hardcoded copy). With this commit, the only two places that hold the version number are `blender_manifest.toml` (canonical for Blender's extension loader) and `__init__.py`'s `__version__` (canonical for Python code), and they must always move together. The `ping()` docstring updated accordingly.
- **README** Status line updated to v0.4.1; MCP bridge tool list now includes `frame_wall`; the "currently UI-only" caveat removed; roadmap v0.4.1 marked done.

### Architecture notes
- **`UI in vN, bridge parity in vN+1` cadence held.** v0.4 shipped `frame_wall` as a UI-only operator; v0.4.1 adds the bridge handler, the FastMCP tool, and the smoke-test step that exercises it end-to-end. Same pattern as v0.3.1→v0.3.2 (panels) and v0.3.3→v0.3.4 (fill).
- **Composite-operator bridge return shape.** Beyond the input echoes, the response includes derived fields the LLM would otherwise have to compute itself (or query for): `n_studs` (from the same `stud_positions` algorithm the operator uses), `n_plates`, `stud_length_in` (height minus the plate stack), `stud_stock_in` and `plate_stock_in` (smallest-stock-that-fits via `select_stock_length_in`). For an LLM agent that's about to recommend a material order, having both cut and stock dimensions in the response means no follow-up round-trip.
- **Empty-parent placement after the operator runs.** The `frame_wall` operator creates the Empty at world origin; the bridge handler repositions it via `empty.location = location_m` *after* the operator runs, with all children already parented. Children's world positions follow the Empty without per-child updates — Blender's parent-child transform inheritance does the work.
- **Computed stud count rather than child-name filtering.** The handler returns `n_studs = len(templates.stud_positions(...))`, computed directly from the same pure function the operator uses, rather than counting child Objects whose names contain `"Stud"`. The naming convention is `praxova_mesh_wall_stud_<nominal>_<length_in>` today but could change; the function call won't.

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

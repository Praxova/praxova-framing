# Praxova Framing

A Blender add-on for fast construction framing in 3D — lumber, sheet, and panel templates with one-click on-center duplication, edge-to-edge fill for sheets and panels, a single-shot "frame a wall" composite operator (v0.4), cut-list export with cut/order summaries, and (v0.3) an MCP bridge so an LLM agent like Claude Desktop can drive the same operators.

**Status:** Beta (v0.5.0). Pre-1.0 — APIs and the per-object data model may change between minor versions.

## What it does

- **Tagged templates** for dimensional lumber (1x2 / 2x3 / 2x4 / 2x6 / 2x8 / 2x10 / 2x12 / 4x4 / 4x6 / 6x6), sheet goods (plywood and OSB at 1/2" and 3/4" performance categories, 4x8 size), and metal roofing/siding panels (36" coverage width at 8' / 12' / 16' lengths). Geometry is *actual* dimensions; cut-list labels use *nominal* / call-out sizes.
- **On-center duplicator** with two preset rows: stud/joist spacing in inches (12" / 16" / 19.2" / 24") and post/timber spacing in feet (8' / 10'). Plus count and Right/Left direction. Steps along the source's local X axis — the lumber thin axis for stud-spacing workflows. Each duplicate is a separate Object (so the cut list is correct), but they share mesh data (so it's memory-efficient).
- **Fill Edge-to-Edge duplicator** for sheets and panels. Steps along the source's local Y axis at edge-to-edge spacing — the source's own width. Six preset spans (8'/12'/16'/20'/24'/32') auto-compute count from the active object's width. Use to sheathe a wall or cover a roof in one click. Refuses lumber active objects with a pointer back to the OC duplicator.
- **Frame a Wall** (v0.4, openings added in v0.5) — single composite operator that places top plates, bottom plates, and studs for a wall, parented to a new Empty for one-handle transform. Sheathing-aligned stud layout: end studs flush with wall ends, intermediate studs at on-center spacing measured from `x=0`, final bay tight when length isn't a multiple of spacing. v0.5 adds optional door and window openings to the same operator: an "Openings" UIList in the N-panel drives king studs, jacks, a (2) 2x + 1/2" plywood spacer header build-up, optional rough sills (windows), and cripples above the header / below the sill. Regular OC studs that would collide with a king bracket are dropped automatically. Single isolated wall in v0.5 — corner stud treatments come in later cycles.
- **Cut list** generator that walks the scene, counts tagged objects by label, and writes to both an in-Blender Text datablock and a `.txt` file next to your `.blend`. Three sections: LUMBER, SHEETS, PANELS. LUMBER renders two subsections (v0.4+): CUT LIST (per-piece with cut-from-stock annotations) and ORDER SUMMARY (aggregated by stock SKU across orientations).
- **Add-menu integration** — `Add → Praxova Lumber → ...` for lumber, sheets, and panels, in vertical and horizontal orientations.
- **MCP bridge** (v0.3) — an in-Blender JSON-RPC bridge plus a separate-process MCP server (`mcp_server/`) so an LLM agent can drive every operator above through a chat interface.

## Install

1. Edit → Preferences → Get Extensions → top-right dropdown → **Install from Disk…**
2. Pick the addon zip (clone this repo and zip the directory contents at the root, with `blender_manifest.toml` at zip root).
3. Enable it if not enabled automatically.

The N-panel tab "Praxova" should appear in the 3D Viewport (press `N` to open).

**Targets:** Blender 4.2+ (uses the new extensions system). Tested on Blender 5.1.

For LLM-driven framing via MCP, also see [`mcp_server/README.md`](mcp_server/README.md).

## Sheet thickness — actuals vs. call-outs

Sheet goods are sold by **Performance Category** (the call-out), which doesn't match literal thickness:

| Call-out | Plywood actual | OSB actual |
|----------|----------------|------------|
| 1/2"     | 15/32" (0.469") | 7/16" (0.438") |
| 3/4"     | 23/32" (0.719") | 23/32" (0.719") |

Per APA PS 1 (plywood) and APA PS 2 (OSB). Geometry uses the actual; cut-list label uses the call-out so material orders match. Override `SHEET_THICKNESS_ACTUAL` in `templates.py` if your supplier uses different stock.

## Metal panels — generic profile

Real metal-panel rib geometry varies widely by manufacturer and profile (5V crimp ~0.5", AG/corrugated ~0.75", R-panel ~1.25", standing seam 1.5–3"). v0.3 models all metal panels as flat slabs with a generic 0.75" profile placeholder, defined per-material in `templates.PANEL_MATERIAL_PROFILE`. Panel layout (coverage width, length, count) is what matters for ordering and on-roof placement; the rib geometry is cosmetic. A future version will replace the slab with a proper corrugation generator.

## Header sizing

The `frame_wall` operator's per-opening `header_nominal` defaults to the wall's `nominal` size — a 2x4 wall gets a 2x4 header, a 2x6 wall gets a 2x6 header. **This default is geometric, not structural.** Real residential headers are sized by the span and the load above (roof, second floor, snow, etc.), and the same opening can need a much heavier header on a load-bearing wall than on a non-bearing partition.

Use the per-opening `header_nominal` override to upsize for real spans and loads. As a rough starting point (NOT a substitute for code review or an engineer):

| RO width | Typical residential header (load-bearing exterior) |
|----------|-----------------------------------------------------|
| ≤ 4'     | (2) 2x6 |
| 4' – 6'  | (2) 2x8 |
| 6' – 7'  | (2) 2x10 |
| 7' – 9'  | (2) 2x12 |

See IRC R602.7 for the prescriptive header tables, your jurisdiction's adopted code for amendments, and an engineer for anything outside the prescriptive tables. The add-on does not validate header sizing against load — it places exactly what you specify.

## Geometry orientation

Same convention for all materials:

| Orientation | X | Y | Z | Long axis |
|-------------|---|---|---|-----------|
| Vertical    | thickness / profile | width | length | +Z |
| Horizontal  | length | width | thickness / profile | +X |

Origin at min corner (0, 0, 0). Click the 3D cursor where you want the bottom-front-left corner of the piece.

For `frame_wall` (v0.4): the bottom-front-left corner of the framed wall lands at world `(0, 0, 0)`, with the wall length along +X, thickness along +Y, height along +Z. The wall Empty is at origin; the user transforms it afterward to position the wall in the larger model.

## Working with linked-mesh duplicates

Each Praxova template (a `2x4x8 V`, a `36" Metal x 12 V`, etc.) is built once as a single mesh datablock. Every subsequent placement — via the on-center duplicator, the edge-to-edge fill duplicator, Shift-D, or a re-add of the same template — creates a new **Object** that *links* to the same **Mesh**. Two instances. One mesh. This keeps memory low and editing fast (change the mesh once and every instance updates).

The tradeoff: applying a transform via *Object → Apply → Rotation/Scale* bakes that transform into the mesh, so doing it on one instance affects every linked instance. Blender catches this and prompts "Make Single User?". The right answer depends on what you want:

- **Most workflows**: don't apply rotation/scale at all. Object-level transforms render identically and don't affect other instances. The cut list ignores transforms — it counts by `cutlist_label` stored on each Object's tag, not by mesh identity.
- **You really do need it baked in** (e.g., exporting to a tool that ignores Blender object transforms, or running a boolean on one piece): with that one piece selected, *Object → Relations → Make Single User → **Object & Data*** (shortcut: `U` → Object & Data). That copy gets its own mesh; everything else stays linked. Cut-list count is unaffected.

## Data model

Each placed piece carries a `praxova_lumber` PropertyGroup with:

```
is_lumber:                bool    # "is Praxova-managed"
category:                 'LUMBER' | 'SHEET' | 'PANEL'
nominal_size:             "2x4", "4x6", ...           (lumber only)
length_in:                96.0, 91.5, ...             (lumber only - final cut length)
stock_length_in:          96.0, 120.0, ...            (lumber only - purchased stock, v0.4+)
sheet_material:           'PLYWOOD' | 'OSB'           (sheet only)
sheet_thickness_callout:  "1/2", "3/4"                (sheet only)
sheet_size_key:           "4x8"                       (sheet only)
panel_material:           'METAL'                     (panel only)
panel_size_key:           "36x8" / "36x12" / "36x16"  (panel only)
orientation:              'VERTICAL' | 'HORIZONTAL'
cutlist_label:            "2x4x8 V" / "1/2\" PLY 4x8 V" / "36\" Metal x 8 V"
```

For v0.4+, `length_in` is the final cut dimension (e.g., 91.5" for a stud in an 8' wall with a single bottom plate and two top plates) and `stock_length_in` is the purchased stock the piece was cut from (96" / 8'). For pieces placed via `add_lumber` the two are equal — no cut. For pieces from `frame_wall` they can differ, and the cut-list ORDER SUMMARY aggregates by `stock_length_in` while the CUT LIST shows the `length_in` cut detail.

Filter for cut-list construction or external scripts:

```python
[obj for obj in bpy.data.objects if obj.praxova_lumber.is_lumber]
```

## Cut list

N-panel → **Cut List → Generate Cut List**. Output goes to:

1. A Blender Text datablock named **"Praxova Cut List"** — to view, split an editor area, change its type to Text Editor, and pick "Praxova Cut List" from the data picker.
2. A **`<blendfile>_cutlist.txt`** file alongside the .blend (only if the .blend has been saved). Status bar message shows the exact path.

Output is split into LUMBER, SHEETS, and PANELS sections, with subtotals when more than one category is present, plus a grand total.

The LUMBER section (v0.4+) renders two subsections:

```
LUMBER — CUT LIST
      3  x  2x4x8 H
      8  x  2x4x8 V  → cut to 91.5"

LUMBER — ORDER SUMMARY
     11  x  2x4x8  (3 H, 8 V)
```

**CUT LIST** is per-piece detail for the saw — each stock label appears once per distinct cut length, with a `→ cut to N"` annotation when the cut is shorter than the stock (i.e., produced by `frame_wall` or another composite operator). **ORDER SUMMARY** aggregates by stock SKU (nominal + stock length in feet) across orientations, with an orientation parenthetical for traceability — what you actually take to the lumberyard.

SHEETS and PANELS sections retain the single-section format from v0.3.x; neither has a cut-from-stock concept in v0.4.

## MCP bridge (v0.3)

Drive the add-on from an LLM agent. Two-process architecture:

```
┌──────────────────┐    stdio MCP    ┌────────────────────┐    TCP JSON-RPC    ┌─────────────────────┐
│  Claude Desktop  │────────────────▶│  praxova-framing-  │───────────────────▶│  Blender 5.x        │
│                  │                 │  mcp (Python pkg)  │   127.0.0.1:9876   │  (bridge thread)    │
└──────────────────┘                 └────────────────────┘                    └─────────────────────┘
```

The in-Blender bridge listens on localhost only. All `bpy` mutation is serialized onto Blender's main thread via `bpy.app.timers`, so concurrent client connections cannot race on bpy state. See [`mcp_server/README.md`](mcp_server/README.md) for install and Claude Desktop configuration.

To use:

1. N-panel → **MCP Bridge** → **Start Bridge** in Blender.
2. From the MCP client, call any of: `add_lumber`, `add_sheet`, `add_panel`, `duplicate_oc`, `duplicate_e2e`, `frame_wall`, `generate_cutlist`, `set_imperial_units`, `list_materials`, `list_objects`, `get_scene_info`.

For protocol-level testing without an LLM client, run `smoke_test.py` from the repo root with the bridge running.

## Roadmap

- ✅ **v0.3** — MCP server in front of the operators.
- ✅ **v0.3.1** — Lumber additions (1x2 / 2x3 / 4x4 / 4x6), 36" metal roofing/siding panels (PANEL category), 8' / 10' OC presets for post-framing.
- ✅ **v0.3.2** — Bridge parity for panels (`add_panel` MCP tool); smoke-test coverage for panels; `add_lumber` MCP Literal extended to include the v0.3.1 lumber additions; `_serialize_object` fixed for the PANEL category.
- ✅ **v0.3.3** — Fill Edge-to-Edge operator (`duplicate_e2e`) for sheets and panels; N-panel "Fill Edge-to-Edge" section with preset spans, auto-computed count, and Forward/Back direction.
- ✅ **v0.3.4** — Bridge parity for the Fill operator (`duplicate_e2e` MCP tool); smoke-test coverage for fill including a LUMBER-refusal guard; bridge surface now eleven methods.
- ✅ **v0.4** — "Frame a Wall" composite operator (plates + studs + Empty parent in one shot). Sheathing-aligned stud layout, stock vs. cut length distinction on lumber tags, two-subsection LUMBER cut list (CUT LIST + ORDER SUMMARY).
- ✅ **v0.4.1** — Bridge parity for `frame_wall` (12th MCP method); pre-validation surfacing impossible geometry as clean `INVALID_PARAMS`; smoke-test extension exercising the new tool end-to-end; `__version__` constant in `__init__.py` so the bridge `ping()` no longer carries its own hardcoded version string.
- ✅ **v0.5** — Door / window openings on `frame_wall`: `PraxovaWallOpening` PropertyGroup, N-panel UIList with Add Door / Add Window / Remove / Distribute, opening-aware live preview, five pure helper functions in `templates.py` (`recommend_jack_count`, `opening_framing_layout`, `filter_studs_around_openings`, `validate_openings`, `redistribute_openings_evenly`), kings + jacks + (2) 2x + 1/2" plywood spacer headers + optional rough sills + header / sill cripples placed by the operator. README "Header sizing" section documents the geometric-default-not-structural `header_nominal`.
- **v0.5.1** — Bridge parity for `frame_wall` openings. Extend the `frame_wall` MCP tool to accept an `openings` array parameter that maps to the same `PraxovaWallOpening` field set; pre-validation surfacing per-opening errors as `INVALID_PARAMS`; smoke-test extension framing a wall with a door and a window via the bridge and asserting the new piece types (jacks, headers, sills, cripples) appear in the cut list.
- **Later** — Corner stud treatments (three-stud corners, California corners); additional sheet sizes (4x10, 4x12), 5/8" sheet thickness, addon preferences for thickness overrides, ribbed-profile metal panel geometry to replace the v0.3 flat-slab placeholder.

## License

GPL-2.0-or-later. See `LICENSE`. (Required for Blender add-ons that use the `bpy` API. The MCP server in `mcp_server/` is licensed to match.)

## Author

Alton Lord — Praxova ([praxova.ai](https://praxova.ai))

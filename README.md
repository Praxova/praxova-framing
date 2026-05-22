# Praxova Framing

A Blender add-on for fast construction framing in 3D — lumber, sheet, and panel templates with one-click on-center duplication, edge-to-edge fill for sheets and panels, a single-shot "frame a wall" composite operator (v0.4), cut-list export with cut/order summaries, and (v0.3) an MCP bridge so an LLM agent like Claude Desktop can drive the same operators.

**Status:** Beta (v0.6.51). Pre-1.0 — APIs and the per-object data model may change between minor versions.

## What it does

- **Tagged templates** for dimensional lumber (1x2 / 2x3 / 2x4 / 2x6 / 2x8 / 2x10 / 2x12 / 4x4 / 4x6 / 6x6), sheet goods (plywood and OSB at 1/2" and 3/4" performance categories, 4x8 size), and metal roofing/siding panels (36" coverage width at 8' / 12' / 16' lengths). Geometry is *actual* dimensions; cut-list labels use *nominal* / call-out sizes.
- **On-center duplicator** with two preset rows: stud/joist spacing in inches (12" / 16" / 19.2" / 24") and post/timber spacing in feet (8' / 10'). Plus count and Right/Left direction. Steps along the source's local X axis — the lumber thin axis for stud-spacing workflows. Each duplicate is a separate Object (so the cut list is correct), but they share mesh data (so it's memory-efficient).
- **Fill Edge-to-Edge duplicator** for sheets and panels. Steps along the source's local Y axis at edge-to-edge spacing — the source's own width. Six preset spans (8'/12'/16'/20'/24'/32') auto-compute count from the active object's width. Use to sheathe a wall or cover a roof in one click. Refuses lumber active objects with a pointer back to the OC duplicator.
- **Frame a Wall** (v0.4, openings added in v0.5) — single composite operator that places top plates, bottom plates, and studs for a wall, parented to an Empty for one-handle transform. Sheathing-aligned stud layout: end studs flush with wall ends, intermediate studs at on-center spacing measured from `x=0`, final bay tight when length isn't a multiple of spacing. v0.5 adds optional door and window openings: an "Openings" UIList in the N-panel drives king studs, jacks, a (2) 2x + 1/2" plywood spacer header build-up, optional rough sills (windows), and cripples above the header / below the sill. v0.6 makes the operator context-sensitive — clicking Frame Wall with a wall Empty active re-frames it in place (preserving the Empty so joint references survive), and walls created with a Level active land as children of that Level for multi-wall coordination.
- **Multi-wall coordination** (v0.6, v0.6.50) — Building → Level → Wall hierarchy with L corner and T joints between walls. A new Building tab in the N-panel hosts container creation, joint management via a UIList, and a Frame Building button that re-frames every wall in the active Level with corner geometry applied. **L joints**: cap plates lap per IRC R602.3.2, abutting walls' plates shorten by the main wall's stud thickness, three-stud corners get the interior filler stud automatically. **T joints** (v0.6.50): the through wall's cap is notched at the joint position; the abutting wall's cap extends into the notch, sitting on the through wall's lower top plate; two backing studs on the through wall flank the abutting wall's footprint for drywall nailing.
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

## In-line plate splices

When a wall's plates exceed the longest available stock, Praxova Framing automatically splits each plate into pieces that butt-join over a full-height stud. This is the standard residential approach to walls longer than 16'. The smoke-test target case is a 24' wall.

**Max stock** caps at **16' (192")** across all nominals. The conservative residential default; per-nominal stock ceilings floor it shorter where applicable (1x2 caps at 8'). The lookup function `templates.max_stock_length_in(nominal)` returns `min(MAX_STOCK_LENGTH_IN, max(LENGTHS_BY_TYPE[nominal]) * 12.0)`. Per-nominal max stock tables and user-settable stock are deferred — a one-function patch when needed.

**Eligible splice anchors.** Splices land on stud centers. Full-height studs eligible to anchor a splice:

- End studs and surviving OC studs (those that survived the opening-region filter)
- King studs at each opening (full-height by construction)
- Interior corner filler studs from THREE_STUD MAIN joint ends

Jacks (under the header) and cripples (above the header or below a sill) are NOT eligible — neither provides a continuous load path from the bottom plate to the cap.

**IRC R602.3.2 offset rule.** A cap plate splice must offset ≥24" from the nearest lower top plate splice. Enforced as a HARD constraint: if no eligible stud satisfies the offset, the operator reports an error identifying the failing range and the offset constraint, and cancels rather than placing a non-compliant splice. The user adjusts wall length, stud layout, or opening positions so a valid splice exists.

**Stud snapping.** When the ideal splice position (`current_start + max_stock`) doesn't land on a stud, the planner shifts INBOARD to the largest eligible stud at or before the ideal — matching field practice (accept a slightly short first piece rather than retrofit an extra stud just to splice over). For a 24' 2x6 wall on 16" OC the lower top plate splices cleanly at x=192 (the OC stud center there); the cap plate has to back off to x=160 because the studs at x=176 and x=192 are inside the 24" exclusion zone around the lower top splice.

**Naming convention.** Spliced plate pieces get a `_pN` suffix:

```
Wall_01_BottomPlate_01_p1
Wall_01_BottomPlate_01_p2
Wall_01_TopPlate_01_p1
Wall_01_TopPlate_01_p2
Wall_01_TopPlate_02_p1
Wall_01_TopPlate_02_p2
```

Walls that don't need splicing keep the existing single-piece names (`Wall_01_BottomPlate_01`, etc.) — backward-compatible with everything from v0.4.

**Cut list integration** is automatic. Each spliced piece carries its own `length_in` (the cut) and `stock_length_in` (selected from the standard stock sizes 8'/10'/12'/14'/16' via `templates.select_stock_length_in`). The CUT LIST subsection shows per-piece detail with `→ cut to N"` annotations; the ORDER SUMMARY aggregates by stock SKU across orientations — a 24' 2x6 wall with bottom + lower top spliced at x=192 and cap spliced at x=160 produces three different stock sizes (16', 14', 12', 8') for the same wall's plate run, all enumerated in order.

### What's not in v0.6.40

- **Stud splicing.** Walls taller than the longest available stock for the chosen nominal still fail with the existing stud-stock validation error. Adding stud splice per IRC R602.6 is deferred.
- **Bridge parity.** The MCP bridge handler's `frame_wall` response shape doesn't include splice information yet — that's v0.6.41 along with `SpliceError` → `INVALID_PARAMS` routing and the smoke steps that exercise the splice path through the bridge.

## Multi-wall coordination

v0.6 adds a Building → Level → Wall container hierarchy and L corner joints. The single-wall workflow from v0.5 is preserved — you don't need a Building to frame one wall — but for anything larger than a single isolated wall, the Building tab gives you joint-aware framing in one click.

### The hierarchy

- **Building** (CUBE Empty) — a structure. Holds one or more Levels.
- **Level** (SINGLE_ARROW Empty) — one story. Parented under a Building. Walls in the same Level can be joined at corners; the Level's `joints` collection is where those joints live.
- **Wall** (PLAIN_AXES Empty) — the existing v0.5 frame_wall output, with its own `PraxovaWallProps` PropertyGroup carrying length / height / nominal / OC / openings. Parented under a Level when created with the Level active.

### The N-panel tabs

Two side-by-side panels under the Praxova category:

- **Wall Framing** (the v0.5 tab, renamed) — edits the active wall's params if a wall Empty is selected, otherwise edits scene scratch (which becomes the new wall's params on the next Frame Wall click). Context indicator at the top of the section tells you which.
- **Building** (new in v0.6) — three nested sections:
  - **Building**: active Building dropdown + Add Building button + default corner style (for v0.6, three-stud only).
  - **Level**: active Level dropdown + Add Level button + level index / height + a read-only list of walls in this Level + Frame Building button.
  - **Joints**: UIList of joints + Add/Remove buttons + active joint detail panel. Fields vary by joint_type: L_CORNER shows wall_a/end, wall_b/end, corner_style, extending_wall + a Resolved MAIN readout; T_JOINT shows Through Wall (A), wall_a_position_in (with carpenter-format readout), Abutting Wall (B)/end, corner_style. Live validation surfaces the same first-failure message Frame Building would report.

### Joints and the three-stud corner

An L corner joint connects Wall A's `END` (x=wall_length_in) to Wall B's `START` (x=0), or any other end combination. The joint's `extending_wall` field determines which wall is **main** — the main wall's plates run full length across the corner, an interior filler stud lands inboard from its end stud (drywall backing for the abutting wall's inside face), and its end stud stays flush with the corner. The other wall is **abutting** — its bottom plate, lower top plate, and end stud all shorten by the main wall's wall thickness so it lands flush with the main wall's interior face.

`extending_wall=AUTO` (default) picks the **longer** wall as main — matches the residential convention that longer walls form the outside and shorter walls butt in. Equal-length walls tie-break to wall_a. `extending_wall="A"` or `"B"` overrides explicitly. The Building tab's joint detail panel shows the resolved main as a live `→ Resolved MAIN: <wall_name>` readout below the dropdown so you can see which wall is currently main without re-deriving it mentally. (v0.6.25 fixed a v0.6.0 bug where explicit "A" / "B" was stored but ignored at frame time — the filler always landed on wall_a.)

#### Cap plate lap (v0.6.30, corrected v0.6.31)

The cap plate (topmost top plate) and the lower top plate are mirror images across the MAIN/ABUTTING role at each joint end — that's what creates the mechanical lap inside the corner cell. At a MAIN end the cap is shortened INBOARD by the paired wall's wall thickness (leaving room for the abutting wall's cap to land on top of the main wall's lower top plate). At an ABUTTING end the cap reaches the wall edge (offset 0); the lap happens INSIDE the abutting wall's own footprint at `y ∈ [0, paired_t]`, which is exactly where the main wall's lower top plate sits in world space. Neither plate physically extends past the wall's nominal footprint. Per IRC R602.3.2.

Before v0.6.30 caps were geometrically identical to lower top plates, so corners were butt joints with no tie. v0.6.30 introduced the lap geometry. v0.6.31 then corrected the ABUTTING-end behavior — v0.6.30 had the cap extending `paired_t` past the wall edge, conflating the wall's nominal edge with the lower top plate's actual edge at an ABUTTING end (which is `paired_t` inboard from the wall edge). The lap still works because it happens inside the building footprint, not outside it.

### T joints (v0.6.50)

A T joint connects a through wall (`wall_a`) to an abutting wall (`wall_b`) mid-span. The through wall's plates continue past the joint; the abutting wall's plates butt against the through wall's interior face. The joint stores `wall_a_position_in` (the wall_a-local x where wall_b's near edge lands) alongside the usual `wall_a` / `wall_b` PointerProperty refs. `wall_a_end` and `extending_wall` are ignored — T joints don't have an end on wall_a, and the through/abutting topology is fixed by joint slot (no MAIN/ABUTTING resolution).

#### Backing studs (T_BACKING_STUDS corner style)

Two backing studs land on wall_a at the joint position, flanking wall_b's end-stud footprint. They provide drywall nailing for wall_b's interior face return on both sides — the standard residential T-joint detail. Together with wall_b's own end stud at the joint, that's three studs at the corner cell (mirrors THREE_STUD's stud count for L corners). Backing studs share wall_a's cross-section and length, so they're full-height, and they're eligible splice anchors for wall_a's plates per the v0.6.40 splice planner — T joints compose with splice geometry naturally.

OC stud filtering: any of wall_a's regular OC studs whose footprint would overlap a backing stud is dropped (same interval-overlap pattern v0.5 uses to filter OC studs around opening kings).

#### Cap plate notch + extension

The through wall's cap plate is interrupted at the joint position by a `wt_b`-wide gap (`wt_b` = wall_b's wall thickness, 3.5" for 2x4 wall_b). The abutting wall's cap plate extends past its nominal end by `wt_a` (= wall_a's wall thickness) and lands in the notch, sitting on top of wall_a's lower top plate. Standard IRC R602.3.2 T-joint lap detail.

The notch makes wall_a's cap multi-piece; each sub-range goes through the v0.6.40 splice planner independently (the bottom plate and lower top plate continue through the joint without modification — only the cap is notched). The 24" cap-vs-lower-top splice offset rule applies per cap sub-range. Wall_b's cap is single-piece but extended; if `wall_b_length + wt_a` exceeds the longest available stock, the splice planner kicks in for that piece.

#### Validation

T joint position must satisfy `st_a ≤ position ≤ wall_a_length - wt_b - st_a` so the backing studs fit. `corner_style='THREE_STUD'` with `'T_JOINT'` is rejected (and vice versa for `'T_BACKING_STUDS'` with `'L_CORNER'`). The Building tab's live validation indicator surfaces these errors with the same "Joint N: ..." first-failure format as L-corner errors; `frame_building`'s pre-flight runs the same validator. Cross-feature overlap checks (T-joint backing studs vs opening kings, vs L-corner end studs, vs other T joints on the same wall) are deferred — downstream collisions surface as bracket/stock-fit errors or visually in the viewport.

#### Workflow

After creating two walls under a Level (per the L-joint workflow below), add a joint via the Joints UIList. Change `joint_type` to "T Joint" in the detail panel — the field set switches: `wall_a_position_in` (with carpenter-format `= N' M"` readout) replaces `wall_a_end`, and `extending_wall` + the Resolved MAIN readout disappear. Pick wall_a (the through wall), set the position along wall_a's length, pick wall_b (the abutting wall) and which end of wall_b connects, leave `corner_style` on AUTO (resolves to T_BACKING_STUDS). Click Frame Building. The through wall picks up its two backing studs and a notched cap; the abutting wall picks up its extended cap.

#### Bridge (v0.6.51)

`add_joint` accepts `joint_type='T_JOINT'` with a required `wall_a_position_in` field; `list_joints_in_level` round-trips the full T-joint shape including `wall_a_position_in`. The joint_type / corner_style combo rules (`T_JOINT` requires `T_BACKING_STUDS` or `AUTO`; `L_CORNER` requires `THREE_STUD` or `AUTO`) are pre-checked at `add_joint` time — INVALID_PARAMS surfaces before the LLM commits to a frame_building call. Position bounds are checked later at frame_building time via validate_joints (the bridge doesn't read wall_a's length at parse time). `frame_building`'s per-wall summary gains `n_backing_studs` alongside `n_corner_fillers` so callers can verify T-joint geometry placement without a follow-up list_objects query. `frame_wall` / `frame_building` `splice_summary` handles T-through walls correctly — `n_splices` is notch-aware (cap-plate notches don't count as splices) and `splice_xs` filters out notch boundaries.

### Workflow

1. Building tab → **Add Building** — creates `Building_01` + `Level_01`. The active Level is set to the new Level.
2. Wall Framing tab → set scalar params for the first wall → **Frame Wall**. The new wall lands as a child of `Level_01`.
3. Move the wall in the viewport (G key, R key), then repeat to add more walls under the same Level.
4. Building tab → Joints section → **Add Joint** → pick walls A and B in the joint detail panel, pick their ends, leave corner_style and extending_wall on AUTO (or override).
5. Building tab → **Frame Building** — re-frames every wall in the Level with joint context applied. Three-stud corners appear, cap plates lap, and the cut list now includes `CornerFiller_Joint<NN>` pieces.

Editing an existing wall is straightforward: select the wall Empty in the viewport, the Wall Framing tab now shows that wall's params, change any field (length, height, openings, etc.), click Frame Wall. The wall's children get deleted and rebuilt; the Empty itself is preserved so joint references stay intact. After editing, click Frame Building once more to re-apply joint geometry across the affected walls (v0.6 does not auto-trigger this).

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
2. From the MCP client, call any of: `add_lumber`, `add_sheet`, `add_panel`, `duplicate_oc`, `duplicate_e2e`, `add_building`, `add_level`, `add_joint`, `remove_joint`, `frame_wall`, `frame_building`, `generate_cutlist`, `set_imperial_units`, `list_materials`, `list_objects`, `list_joints_in_level`, `get_scene_info`.

As of v0.5.1, `frame_wall` accepts an optional `openings` array — a list of door and window opening dicts mirroring the in-Blender Openings UIList. Each dict carries `type` (`"door"` or `"window"`), `x_offset_in`, `ro_width_in`, `ro_height_in`, optional `sill_height_in` (required for windows), optional `header_nominal` (defaults to wall nominal), and optional `jack_count` (defaults to 2 for openings ≥72", else 1). The response gains `n_openings` plus an `openings_summary` with per-opening jack length, header length, and cripple counts. See the FastMCP tool docstring in `mcp_server/praxova_framing_mcp/server.py` for the full schema and worked examples.

As of v0.6.1, the bridge handles the v0.6 Building/Level/Wall hierarchy. Call `add_building` to create a Building Empty plus a default Level child in one shot; call `add_level` to add another Level under an existing Building. `frame_wall` gains three new optional params: `level` (name of a Level Empty — the new wall lands as a child of it), `wall_target` (name of an existing wall to re-frame in place; switches the tool to REBUILD mode where each provided param writes through to the wall's stored props and each omitted param preserves the existing value), and `rotation_deg_z` (Z rotation in degrees applied to the wall Empty — refused in REBUILD mode if joints reference this wall, with a message telling the user to clear the joint in Blender first). `list_objects` now reports the new BUILDING, LEVEL, and WALL categories alongside the existing LUMBER, SHEET, PANEL — a WALL entry carries its full `PraxovaWallProps` (including `openings` in the v0.5.1 wire format), so an LLM can `list_objects → modify → frame_wall(wall_target=..., openings=...)` round-trip cleanly.

v0.6.2 completes v0.6's bridge parity with the joint surface. `add_joint` appends a joint to a Level by writing directly to the joints CollectionProperty (one step, all fields up front — no UI two-step). `remove_joint` returns the full removed joint spec as an "undo handle" so a misclick is one `add_joint` call away from reversal. `frame_building` orchestrates the same multi-wall re-frame the Building tab's button drives, with a per-wall summary in the response (`n_studs`, `n_corner_fillers`, `joint_indices_touching`) focused on joint coordination rather than per-wall opening detail. `list_joints_in_level` fills the joint detail gap v0.6.1's `list_objects` deliberately left — per-joint dicts in the same wire format `add_joint` accepts, so a list → mutate → add_joint round-trip works without translation. Bridge surface is now 18 methods.

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
- ✅ **v0.5.1** — Bridge parity for `frame_wall` openings: the bridge handler and FastMCP tool accept an `openings` array mirroring the v0.5 `PraxovaWallOpening` field set; per-opening dict validation surfaces shape errors as `INVALID_PARAMS` with 1-based indices; cross-field rules reuse `templates.validate_openings` so the bridge and the in-Blender preview share one validator; return shape gains `n_openings` and `openings_summary` (per-opening jack length, header length, header/sill cripple counts); smoke-test step `[10]` frames a wall with a centered 38"×82" door and pins the OC stud filter (4 survivors), cripple count (3), and the `"cut to 80.5"` / `"cut to 41"` / `"cut to 7.5"` annotations in the cut list. Method count stays 12 — `frame_wall` is extended, not added.
- ✅ **v0.6** — Multi-wall coordination. Building → Level → Wall container hierarchy with per-wall `PraxovaWallProps` storage; L corner joints with three-stud corner style (interior filler stud + cap plate lap per IRC R602.3.2); in-place wall re-framing that preserves joint `PointerProperty` references; `frame_building` orchestrator that re-frames every wall in the active Level with joint context applied; multi-tab N-panel (Wall Framing tab made context-sensitive + new Building tab with joints UIList + active joint detail). Five pure joint helpers in `templates.py` (`compute_wall_joint_context`, `resolve_extending_wall`, `resolve_corner_style`, `l_corner_geometry`, `validate_joints`) shared between the orchestrator's pre-flight check and the Building tab's live validation indicator. Method count stays 12 — UI-only cycle; bridge parity coming in v0.6.1.
- ✅ **v0.6.1** — Partial bridge parity for v0.6: container creators (`add_building`, `add_level`) and `frame_wall` extended with `level` (parent under a Level on CREATE), `wall_target` (REBUILD in place with write-through scalar / openings semantics), and `rotation_deg_z` (with a joints-touching refusal in REBUILD mode). `list_objects` extended to enumerate the v0.6 hierarchy Empties (BUILDING, LEVEL, WALL categories) with full per-category fields including round-trippable opening dicts on WALL. Bridge surface grows 12 → 14 methods; smoke test grows 15 → 19 steps. mcp_server package version 0.5.1 → 0.6.1 (skipping 0.6.0).
- ✅ **v0.6.40** — In-line plate splices. Walls with plates exceeding the longest available stock are split into multiple cut pieces that butt-join over a full-height stud (end studs, OC studs, kings, and corner fillers all eligible; jacks and cripples excluded). Cap plate splices offset ≥24" from lower top plate splices per IRC R602.3.2, enforced as a HARD constraint via a structured `SpliceError` → operator error reporting. Stud-snapping: when the ideal splice position lacks a stud, the planner shifts INBOARD to the largest qualifying stud (matches field practice — accept a slightly short first piece rather than retrofit). New helpers in `templates.py`: constants `MAX_STOCK_LENGTH_IN` (192") and `TOP_PLATE_SPLICE_OFFSET_MIN_IN` (24"); `max_stock_length_in(nominal)` floored at per-nominal stock ceiling; the `SpliceError` exception (module top); `plate_effective_range(plate_role, wall_length_in, role_at_start, role_at_end, paired_t_at_start, paired_t_at_end)` as the canonical plate range helper (supersedes `lower_plate_end_offset` and `cap_plate_end_offset`, both removed); `plan_plate_splice_pieces` (the splice algorithm); `collect_full_height_stud_centers` (eligible anchor collector). `l_corner_geometry` narrowed to stud-only; `compute_wall_joint_context` drops the `is_extending` field (redundant with `role == 'MAIN'`). Spliced plate piece names get a `_pN` suffix; walls without splices keep single-piece naming for backward compatibility. Method count stays 18 — bridge parity comes in v0.6.41; mcp_server package unchanged at 0.6.25.
- ✅ **v0.6.31** — Cap-plate ABUTTING-end correction. v0.6.30's helper returned `+paired_t` at ABUTTING ends, extending the cap past the wall's nominal footprint — that conflated the wall's edge with the lower top plate's actual edge (which is `paired_t` inboard at ABUTTING). v0.6.31 returns 0 at ABUTTING ends; the lap still works because it happens INSIDE the abutting wall's own `[0, paired_t]` footprint strip where the main wall's lower top plate sits. MAIN behavior unchanged. Smoke step `[28]` updated: wall_a cap drops from 99.5" → 96.0". Method count stays 18; mcp_server package unchanged at 0.6.25.
- ✅ **v0.6.30** — Cap-plate lap geometry fix. L-joint corners were butt joints before — cap plate geometry was identical to the lower top plate at each joint end, so corners had no mechanical tie. v0.6.30 makes the cap the INVERSE of the lower top: pulled INBOARD at MAIN ends to leave room, EXTENDED OUTBOARD at ABUTTING ends to lap onto the main wall's lower top plate at the corner cell. Standard residential lap per IRC R602.3.2. Includes a dedicated cap stock-fit check + clear error pointing at the v0.7 splice deferral for the ABUTTING-at-both-ends + max-stock edge case. Two pure helpers (`lower_plate_end_offset`, `cap_plate_end_offset`) in `templates.py` with deliberately inverse sign conventions documented at module level. Smoke test grows 30 → 31 steps with cap-geometry assertions. Method count stays 18; mcp_server package unchanged at 0.6.25 — pure geometry fix on the operator side.
- ✅ **v0.6.25** — Bug fix + cosmetic cycle. **Fixed**: `extending_wall` finally honored at frame time (v0.6.0 bug where explicit "A"/"B" was ignored and the corner filler always landed on `wall_a`); `resolve_extending_wall` is now the single source of truth for MAIN-vs-ABUTTING role assignment. AUTO semantics flipped to "longer wall is MAIN" (residential convention; ties to wall_a). **Added**: Wall Length and Fill Length fields display in decimal feet with a live `= 12' 4.0"` carpenter-format readout; custom imperial-unit icon replaces the generic gear; live `→ Resolved MAIN: <wall_name>` readout in the joint detail panel. **Changed**: Wall A/B labels softened (the main/abutting role is no longer slot-derived). Method count stays 18 — no bridge schema changes; mcp_server package 0.6.2 → 0.6.25.
- ✅ **v0.6.2** — Completes v0.6 bridge parity with the joint surface: `add_joint`, `remove_joint`, `frame_building` orchestrator, and `list_joints_in_level` (the dedicated joint-detail query that fills the gap v0.6.1's `list_objects` LEVEL category deliberately left at count-only). `add_joint` / `remove_joint` write directly to the joints `CollectionProperty` (no `bpy.ops` round-trip — mirrors v0.5.1's `frame_wall` openings pattern); `remove_joint` returns the full joint spec as an undo handle. `frame_building` runs the same `validate_joints` pre-flight the Building tab's live indicator uses and returns a per-wall summary focused on joint coordination (`joint_indices_touching`, `n_corner_fillers`). A pre-work commit also fixes a v0.6.0 ui.py NoneType race surfaced during v0.6.1 smoke testing — `context.active_object` cached once per draw, threaded through `_get_wall_source(context, active=)` so two reads can't straddle Blender's mid-draw context update. Smoke test grows 19 → 28 steps; bridge surface 14 → 18 methods; mcp_server package version 0.6.1 → 0.6.2. The `list_buildings` / `list_levels_in_building` / `list_walls_in_level` convenience methods stay deferred to v0.7+ — `list_objects` with category filtering already covers structural discovery.
- ✅ **v0.6.41** — Bridge parity for v0.6.40. The `frame_wall` response shape gains `splice_summary` — `{n_splices, bottom, lower_top, cap}` where each per-plate dict carries `{pieces, splice_xs}`. The `splice_xs` lists are the per-plate butt-joint x-coords in wall-local coordinates, so a caller can verify the IRC R602.3.2 24" cap-vs-lower-top offset held; `n_splices` aggregates across stack-level instances (bottom * bottom_plate_count + lower_top * (top_plate_count - 1) + cap). The v0.4.1 `plate_stock_in` field is removed — each spliced piece has its own stock now, so a single plate_stock_in number doesn't represent what was placed. `SpliceError` surfaces as `INVALID_PARAMS` with `"{wall_name}: ..."` prefix and the failing range + offset constraint inline, via a `_predict_wall_splice_plans` helper that mirrors the operator's pipeline (stud_positions → end-stud overrides → opening filter → eligible centers → plate_effective_range → plan_plate_splice_pieces × 3). `frame_building` extends its pre-flight to call the same helper per wall — a SpliceError surfaces BEFORE the orchestrator runs, identifying which wall needs adjustment. Each `walls_framed` entry now carries the same `splice_summary` field. Three new smoke steps exercise the splice path end-to-end: `[32]` a 24' 2x6 standalone (cap offset rule binding — cap splices at x=160 vs lower top at x=192), `[33]` a 20' 2x4 standalone (different nominal, second cap piece is 80" vs 128"), `[34]` a 24' 2x6 as wall_a in an L with a 96" 2x6 wall_b under AUTO extending (cap range reduced to 282.5" by MAIN-at-END joint geometry; splice planner consumes the reduced range and still lands the cap splice at x=160). Method count stays 18 — `frame_wall` and `frame_building` are extended, not added; mcp_server package 0.6.25 → 0.6.41.
- ✅ **v0.6.50** — T joints. New joint_type `T_JOINT` on PraxovaJoint alongside `L_CORNER`; new `wall_a_position_in` FloatProperty for mid-wall joint placement; new corner_style `T_BACKING_STUDS`. Through wall's cap plate notched at the joint position (gap = wall_b's wall thickness); abutting wall's cap extended OUTBOARD by wall_a's wall thickness into the notch, landing on wall_a's lower top plate (IRC R602.3.2 T-joint lap). Two backing studs on the through wall flanking wall_b's end-stud footprint provide drywall nailing on both sides; backing studs are eligible splice anchors for wall_a's plates per v0.6.40. OC studs that would overlap a backing stud are dropped (same pattern as opening king filtering). New pure helpers in `templates.py`: `t_joint_geometry_for_wall_a`, `filter_studs_around_intervals`; `plate_effective_range` → `plate_effective_ranges` (list-returning, with optional `joint_type_at_*` kwargs and `mid_joints` param for cap-notch partitioning); `compute_wall_joint_context` gains `'mid_joints'` key; `resolve_corner_style` is joint-type-aware; `validate_joints` extended with T-joint position bounds and joint_type/corner_style compatibility checks; `collect_full_height_stud_centers` gains `backing_stud_left_xs` kwarg. UI joint detail panel gains joint_type-conditional draws (T_JOINT hides `wall_a_end` + `extending_wall` + Resolved MAIN readout; shows `wall_a_position_in` with carpenter-format readout). UIList row gains `@<pos>"` for T joints. Method count stays 18 — UI-only cycle; bridge parity for T joints lands in v0.6.51.
- ✅ **v0.6.51** — Bridge parity for v0.6.50. `add_joint` / `list_joints_in_level` accept `joint_type='T_JOINT'` with the new `wall_a_position_in` field; joint_type / corner_style combo rules pre-checked at parse time (THREE_STUD+T_JOINT and T_BACKING_STUDS+L_CORNER reject with INVALID_PARAMS); position bounds deferred to `frame_building`'s `validate_joints` pre-flight (the bridge doesn't read wall_a's length at parse time). `_predict_wall_splice_plans` is T-aware: backing studs become eligible splice anchors via the v0.6.50 `collect_full_height_stud_centers` extension; OC studs are filtered around backing-stud footprints via `filter_studs_around_intervals`; cap notches partition CAP into sub-ranges via `plate_effective_ranges`'s `mid_joints` kwarg. `n_splices` is notch-aware (`len(pieces) - plate_ranges_count[role]` per role; backward-compatible byte-for-byte on every L-corner-only or no-joint wall). New `_splice_xs_from_pieces` adjacency-aware extractor keeps notch boundaries out of `splice_xs` (Commit 2 follow-up). `walls_framed` entries gain `n_backing_studs` so callers can verify T-joint geometry placement without a follow-up `list_objects`. FastMCP tool docs widened with a "Worked examples" section in `add_joint` showing L_CORNER and T_JOINT call patterns side by side. Smoke test grows 34 → 41 steps; mcp_server package 0.6.41 → 0.6.51. Method count stays 18 — T-joint support extends existing handlers, no new RPCs.
- **v0.6.60** — California corner + ladder-blocking corner styles. Extending `PraxovaJoint.corner_style` enum with two more options. Existing THREE_STUD joints keep working — additive change.
- **v0.6.61** — Bridge parity for v0.6.60 (new corner styles exposed through the wire format).
- **v0.7.0** — Trusses (roof framing).
- **v0.7.1** — Bridge parity for v0.7.0.
- **v0.8.0** — Corrugation generator (real metal panel rib geometry, replacing the v0.3 flat-slab placeholder).
- **v0.8.1** — Bridge parity for v0.8.0.
- **v0.9+** — Multi-story (multiple active Levels per Building).

## License

GPL-2.0-or-later. See `LICENSE`. (Required for Blender add-ons that use the `bpy` API. The MCP server in `mcp_server/` is licensed to match.)

## Author

Alton Lord — Praxova ([praxova.ai](https://praxova.ai))

# Praxova Framing v0.7 Design — Site-Built Trusses (Roof Framing)

## Overview

v0.7 introduces roof framing via site-built trusses. Bearing walls in a Level
are tied together by a `Roof` container, which generates Fink trusses spaced
on-center along the bearing wall length. Each truss is a fully modeled assembly
of tagged lumber pieces (top chords, bottom chord, webs, optional heel blocks)
that flows into the existing cut list.

**v0.7.0** lands the operator-side feature: Fink truss only, one Roof per
Level, single-piece chord members. **v0.7.1** lands MCP bridge parity. Larger
spans, additional truss types, gable-end trusses with rake walls, and Gambrel
roofs land in later sub-cycles.

**Cycle plan:**
- **v0.7.0** (this cycle): Fink truss only, single Roof per Level, bearing-wall
  PointerProperty pair, single-piece chords, energy heel support, cut-angle
  metadata on `praxova_lumber`, new ANGLED orientation
- **v0.7.1**: Bridge parity for v0.7.0
- **v0.7.50**: King-post, queen-post, scissor, attic, mono-pitch truss styles;
  multi-piece chord support (lapped or spliced bottom chord for spans > 16')
- **v0.7.51**: Bridge parity for v0.7.50
- **v0.7.60**: Gable-end trusses + rake wall (sloped top plate) support
- **v0.7.61**: Bridge parity for v0.7.60
- **v0.7.70**: Gambrel roof (top chord + knee wall + second-floor ceiling joist
  composite — likely a Roof variant rather than a truss type)
- **v0.7.71**: Bridge parity for v0.7.70
- **v0.8.0**: Corrugation generator (deferred from v0.6 roadmap)
- **v0.9+**: Multi-story

## Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Site-built vs pre-engineered | Site-built (board-level modeling) | Plays to existing tagged-lumber + cut-list strengths; matches farmhouse workflow. Pre-engineered "order N of design X" representation deferred |
| Truss types in v0.7.0 | Fink only | Residential workhorse; additional types deferred to v0.7.50 with the truss-type enum already extensible |
| Fink web geometry | TPI/SBCA simple-symmetric (4 distinct web members) | Two long diagonals from bottom-chord panel points up to peak, two verticals from panel points up to top chord. Industry-standard W pattern |
| Container hierarchy | Roof Empty under Level, alongside Walls | One place to store roof-wide attributes (pitch, ridge orientation, eave overhang); matches the way joints live on a Level rather than on individual walls |
| Span derivation | Computed from bearing-wall PointerProperty pair | Wall-roof coupling; move a wall and the roof picks it up on next Frame Roof. Mirrors the v0.6 joint PointerProperty pattern |
| Bearing wall convention | Any two parallel walls in the Level | Convention-agnostic — works for standard (eave-bearing) and edge-cases like the chicken-coop (gable-bearing) layout identically. "Eave" vs "gable" is not encoded in field names |
| Truss member nominals | EnumProperty per chord/web matching existing `LUMBER_TYPES` | Consistent with the rest of the codebase; user-configurable defaults (2x6 top/bottom chord, 2x4 web) |
| Pitch representation | EnumProperty of standard residential pitches (3/12 to 12/12) + CUSTOM with `pitch_rise_in` FloatProperty (run fixed at 12") | Matches carpenter mental model (rise/run); CUSTOM escape valve for non-standard pitches |
| Eave vs rake naming | `eave_overhang_in` (not `overhang_in`) | Explicit naming so v0.7.60 can add `rake_overhang_in` without rename. Setting `eave_overhang_in = 0` produces a Monopoly-box roof on the bearing-wall sides |
| Heel detail | `heel_height_in` FloatProperty, 0 = standard heel, > 0 = energy heel with vertical heel block | Modern energy code commonly requires R-49+ over the wall, which needs raised heels. Cheap to support from v0.7.0 |
| Maximum span (v0.7.0) | Single-piece chord ceiling = `MAX_STOCK_LENGTH_IN` (192", 16') | Multi-piece bottom chord (splice / lap) deferred to v0.7.50. Validation rejects spans that would require longer chords |
| Roof Empty origin | World (0, 0, 0); Roof Empty position is decorative | Trusses' world positions are mechanically tied to bearing walls — `frame_roof` rebuilds geometry from bearing walls each call. Mirrors how Wall Empties became position-via-user but children-via-`frame_wall` |
| `frame_roof` semantics | Delete-and-regenerate all Truss children | No per-truss state exists in v0.7.0; mirrors how `frame_building` re-runs every wall through `reframe_wall_in_place` |
| Exterior-face derivation | Computed: face whose normal points away from the other bearing wall's centerline | Pure geometry, no user input; works for both eave-bearing and gable-bearing layouts |
| Truss placement | Sheathing-aligned along bearing wall length: end trusses flush with bearing wall ends, intermediate trusses at OC spacing from x=0, final bay tight | Mirrors v0.5 stud layout one-to-one — same logic, applied along the bearing wall axis |
| Per-truss PropertyGroup | `PraxovaTrussProps` with only `is_truss: BoolProperty` marker | Avoids data-model migration when v0.7.50 adds per-truss variation (scissor, room-in-attic). Matches `PraxovaWallProps.is_wall` / `PraxovaRoofProps.is_roof` marker pattern |
| `active_roof` on scene props | Not added in v0.7.0 | One Roof per Level — found by walking `active_level.children`. If v0.7.50+ ever wants multiple roofs per Level, add `active_roof` then |
| Cut angles on lumber tag | New `cut_angle_start_deg` / `cut_angle_end_deg` fields on `praxova_lumber`, default 0.0 (square) | Generally useful (rafters, skirt boards, fascia all benefit). Backward-compatible — existing pieces default to 0/0 |
| New orientation value | `ANGLED` added alongside `VERTICAL` / `HORIZONTAL` | Top chords and webs are neither vertical nor horizontal; bottom chord stays HORIZONTAL. Cut-list label suffix: `2x6x14 A` |
| Cut list integration | LUMBER section continues as today; angled pieces show angle annotations inline; no separate TRUSSES section | ORDER SUMMARY rolls up by stock SKU correctly; one coherent cut-list document |
| UI placement | New "Roof Framing" N-panel tab alongside Wall Framing and Building | Building tab already dense; Roof has enough fields (bearing wall pickers, pitch, heel, overhang, chord nominals, OC) to deserve its own tab |
| Bridge parity scope | All Roof creation, configuration, and `frame_roof` deferred to v0.7.1 | Matches the v0.6 cadence — UI/operator first, bridge parity in the next sub-cycle |

## Data Model

### `PraxovaRoofProps` PropertyGroup (NEW)

Attached as `PointerProperty` to every Object (active only when
`is_roof = True`). Stores all design parameters for the Roof.

```python
class PraxovaRoofProps(bpy.types.PropertyGroup):
    is_roof: BoolProperty(default=False)            # marker
    
    # Truss type and geometry
    truss_type: EnumProperty(
        items=[('FINK', "Fink", "Standard W-web Fink truss")],
        # v0.7.50 adds: KING_POST, QUEEN_POST, SCISSOR, ATTIC, MONO_PITCH
        default='FINK',
    )
    
    # Bearing walls (drive span)
    bearing_wall_a: PointerProperty(type=bpy.types.Object)
    bearing_wall_b: PointerProperty(type=bpy.types.Object)
    
    # Pitch
    pitch: EnumProperty(
        items=[
            ('P_3_12',  "3/12",  ""),
            ('P_4_12',  "4/12",  ""),
            ('P_5_12',  "5/12",  ""),
            ('P_6_12',  "6/12",  ""),
            ('P_7_12',  "7/12",  ""),
            ('P_8_12',  "8/12",  ""),
            ('P_9_12',  "9/12",  ""),
            ('P_10_12', "10/12", ""),
            ('P_12_12', "12/12", ""),
            ('CUSTOM',  "Custom", "Use pitch_rise_in (run fixed at 12)"),
        ],
        default='P_6_12',
    )
    pitch_rise_in: FloatProperty(
        default=6.0, min=1.0, max=24.0,
        description="Rise in inches (run is 12). Used only when pitch == CUSTOM.",
    )
    
    # Eave detail
    eave_overhang_in: FloatProperty(
        default=12.0, min=0.0, max=48.0,
        description="Horizontal projection of the top chord past the bearing wall's exterior face. 0 = Monopoly-style flush eave.",
    )
    heel_height_in: FloatProperty(
        default=0.0, min=0.0, max=24.0,
        description="Vertical heel block height. 0 = standard heel (top chord meets bottom chord directly at the bearing point).",
    )
    
    # Member nominals
    top_chord_nominal: EnumProperty(items=_LUMBER_TYPE_ITEMS, default='2x6')
    bottom_chord_nominal: EnumProperty(items=_LUMBER_TYPE_ITEMS, default='2x6')
    web_nominal: EnumProperty(items=_LUMBER_TYPE_ITEMS, default='2x4')
    
    # Spacing
    oc_spacing_in: EnumProperty(
        items=[
            ('12',   "12\"",   "12 inches"),
            ('16',   "16\"",   "16 inches"),
            ('19.2', "19.2\"", "19.2 inches"),
            ('24',   "24\"",   "24 inches (typical for trusses)"),
        ],
        default='24',
    )
```

`_LUMBER_TYPE_ITEMS` is the existing module-level constant in `properties.py`
(derived once from `templates.LUMBER_TYPES`). Already used by
`PraxovaWallProps.wall_nominal` and `PraxovaWallOpening.header_nominal`;
v0.7.0 reuses it for the three new chord/web fields without modification.

### `PraxovaTrussProps` PropertyGroup (NEW)

Attached as `PointerProperty` to every Object. Marker only in v0.7.0; expanded
in v0.7.50.

```python
class PraxovaTrussProps(bpy.types.PropertyGroup):
    is_truss: BoolProperty(default=False)
    # v0.7.50 adds per-truss variation fields
```

### Extension to `PraxovaLumberProps` PropertyGroup

```python
class PraxovaLumberProps(bpy.types.PropertyGroup):
    # ... existing fields unchanged ...
    
    # NEW in v0.7.0
    cut_angle_start_deg: FloatProperty(
        default=0.0,
        description="Cut angle at the 'start' (x=0) end of the member, in degrees from square. 0 = square (perpendicular to long axis).",
    )
    cut_angle_end_deg: FloatProperty(
        default=0.0,
        description="Cut angle at the 'end' (x=length_in) end of the member, in degrees from square.",
    )
```

Existing lumber/sheet/panel pieces continue to use 0.0/0.0 (square cuts).
Backward-compatible.

### Extension to `orientation` enum

```python
orientation: EnumProperty(
    items=[
        ('VERTICAL',   "Vertical",   ""),
        ('HORIZONTAL', "Horizontal", ""),
        ('ANGLED',     "Angled",     "Member rotated to an arbitrary slope (truss top chord, web)"),
    ],
)
```

Cut-list label suffix: existing `V`/`H`, new `A` for ANGLED. Bottom chord stays
HORIZONTAL; top chords and diagonal webs are ANGLED; vertical webs (the Fink
center verticals) are VERTICAL.

### Registration Order

Order matters: PropertyGroups must register before any PropertyGroup that
references them (via `CollectionProperty` or `PointerProperty`).
`PraxovaWallOpening` registers before `PraxovaWallProps` (referenced as
`CollectionProperty(type=PraxovaWallOpening)`); `PraxovaJoint` registers
before `PraxovaLevelProps`. The two new v0.7 PropertyGroups slot in between
`PraxovaBuildingProps` and `PraxovaSceneProps`:

```
PraxovaLumberProps        (existing, extended with cut angles + ANGLED)
PraxovaWallOpening        (existing)
PraxovaWallProps          (existing v0.6; uses PraxovaWallOpening)
PraxovaJoint              (existing v0.6)
PraxovaLevelProps         (existing v0.6; uses PraxovaJoint)
PraxovaBuildingProps      (existing v0.6)
PraxovaTrussProps         (NEW; marker only)
PraxovaRoofProps          (NEW; uses PointerProperty(Object) — built-in)
PraxovaSceneProps         (existing)
```

## New Operators

```python
PRAXOVA_OT_add_roof       # Create Roof Empty under active Level
PRAXOVA_OT_frame_roof     # Orchestrator: delete-and-regenerate all trusses
```

`add_roof`: creates a new Empty with `PraxovaRoofProps.is_roof = True`. Parented
under the active Level. Refuses if a Roof already exists in this Level (one per
Level in v0.7.0). Sets default field values.

`frame_roof`: the orchestrator. See "frame_roof Orchestrator" below.

No per-truss operators in v0.7.0 — trusses are created and destroyed by
`frame_roof` only.

## Truss Geometry — Detail

### Cut angle convention

All truss member geometry is computed **centerline-to-centerline** in the
truss-local frame. Each member's "axis" is a line segment between two joint
points (e.g., heel-to-peak for a top chord, panel-point-to-peak for a
diagonal web). Cut lengths reported in the cut list are these centerline
lengths.

Cut angles are reported as **magnitudes from a square (perpendicular) cut**,
always non-negative. The geometric orientation of each cut (which side of the
square it leans) is determined by the member's role in the truss and is
handled by the mesh-building code; the cut-angle field on the lumber tag is
the saw-setting magnitude that a carpenter would dial in.

**Unified cut-angle formula** for a member meeting a chord at one end:

```
cut_angle_from_square = 90° - angle_between_member_axis_and_chord_axis
```

where `angle_between_member_axis_and_chord_axis` is the angle (0° to 90°)
between the member's centerline direction and the joining chord's centerline
direction at the intersection point.

This formula reproduces every special case correctly:
- A web perpendicular to a chord → 0° (square cut)
- A web parallel to a chord → 90° (degenerate — no real cut)
- A vertical web meeting a sloped top chord at pitch angle θ → θ (the cut
  angle equals the pitch angle)
- A plumb cut on a sloped chord (eave or peak) → θ (since the "joining
  surface" is vertical, the angle between the chord axis and a vertical
  reference is 90° − θ, so cut angle = 90° − (90° − θ) = θ)

The formulas worked out per member are listed alongside each member's
geometry below.

### Setup

A Roof references two parallel bearing walls (`bearing_wall_a`,
`bearing_wall_b`). Each is a wall Empty with world transform and the standard
`PraxovaWallProps` set.

For each bearing wall, compute its world-space face planes from its world
transform and `PraxovaWallProps.wall_length_in` / wall thickness (derived from
`wall_nominal`) / `wall_height_in`. The wall has six faces; the two of interest
are the two faces parallel to the wall's local X-Z plane (the "front" face at
local y=0 and the "back" face at local y=wall_thickness).

**Exterior face determination** (pure geometry, no user input):

```
For wall_a:
    a_front_center = world(wall_a, (length/2, 0, height/2))
    a_back_center  = world(wall_a, (length/2, thickness, height/2))
    b_centerline_point = world(wall_b, (length/2, thickness/2, height/2))
    
    d_front = distance(a_front_center, b_centerline_point)
    d_back  = distance(a_back_center,  b_centerline_point)
    
    a_exterior_face = the face whose center is FURTHER from b's centerline.
    a_interior_face = the closer face.
```

Same for wall_b.

### Truss-local frame

Each truss is a planar assembly. In its own truss-local frame:

- **Truss-local X**: along the span, 0 ≤ x ≤ S. Origin at wall_a's exterior
  face.
- **Truss-local Y**: aligned with the ridge axis (the direction the bearing
  walls run). Member thickness sits along Y. All planar truss geometry is at
  y = 0 to y = member_thickness depending on the piece.
- **Truss-local Z**: up. Z = 0 at the top of the bearing wall's cap plate
  (where the bottom chord rests).

### Span and key heights

```
S = perpendicular_distance(wall_a_exterior_face, wall_b_exterior_face)

pitch_ratio = rise / 12.0   # e.g., 0.5 for 6/12

peak_height = (S / 2) * pitch_ratio + heel_height_in
```

`S` is computed in world space from the bearing walls' world-space exterior
face planes. v0.7.0 validates that the two bearing walls are parallel and
aligned (same length, ends matching in the perpendicular cross-section).

### Bottom chord

- Centerline: from `(0, 0, 0)` to `(S, 0, 0)` in the truss frame
- **Cut length** = `S`
- **cut_angle_start_deg** = `0.0`
- **cut_angle_end_deg** = `0.0`
- Orientation: HORIZONTAL
- Object name: `Truss_NN_BottomChord`

The bottom chord does not bird's-mouth or otherwise notch at the heel; it's a
straight piece. v0.7.0 rejects `S > MAX_STOCK_LENGTH_IN` (192", 16') so the
chord is always single-piece. Multi-piece bottom chord deferred to v0.7.50.

### Top chord (per side — left "L" and right "R")

The top chord runs from the eave end (past the bearing wall by
`eave_overhang_in`) up the slope to the peak.

Let `θ = atan(pitch_ratio)` be the pitch angle from horizontal (degrees).

For the **left** top chord:

- Eave-end centerline: `(-e, 0, h - e × pitch_ratio)`
- Peak-end centerline: `(S/2, 0, h + (S/2) × pitch_ratio)` = `(S/2, 0, peak_height)`
- **Cut length** (centerline-to-centerline along the slope):

  ```
  horizontal_run = (S / 2) + e
  cut_length = horizontal_run × sec(θ) = horizontal_run / cos(θ)
              = horizontal_run × sqrt(1 + pitch_ratio²)
  ```

- **cut_angle_start_deg** (eave end) = `θ` (plumb cut — vertical cut plane on
  a sloped member; angle from square equals pitch angle)
- **cut_angle_end_deg** (peak end) = `θ` (plumb cut — both top chords meet at
  the peak with matching plumb cuts that butt against each other)
- Orientation: ANGLED
- Object name: `Truss_NN_TopChord_L`

The **right** top chord is mirrored about the `x = S/2` plane. Same cut
length and cut angles; opposite slope direction.

Object name: `Truss_NN_TopChord_R`.

### Webs (Fink — TPI/SBCA simple-symmetric)

Panel points on the bottom chord at `x = S/3` and `x = 2S/3`. Four web members
per truss.

Let `peak_height = h + (S/2) × pitch_ratio`.

Define the diagonal-web angle from horizontal:

```
φ_diag = atan(peak_height / (S/6))
```

(For a 12' span, 6/12 pitch, h=0: `φ_diag = atan(36/24) = atan(1.5) ≈ 56.31°`.
The diagonal web is always steeper than the top chord by construction —
its rise equals the full `peak_height` over a run of just `S/6`, versus the
top chord's rise of `peak_height − h` over a run of `S/2`.)

**Web 1 — left vertical** (Object name `Truss_NN_Web_1`):

- Bottom centerline: `(S/3, 0, 0)` (panel point on bottom chord)
- Top centerline: `(S/3, 0, h + (S/3) × pitch_ratio)`
- **Cut length** = `h + (S/3) × pitch_ratio`
- **cut_angle_start_deg** (bottom, at bottom chord) = `0.0`
  — vertical web meeting horizontal chord: angle between them = 90° → cut
  angle = 90° − 90° = 0° (square)
- **cut_angle_end_deg** (top, at top chord underside) = `θ`
  — vertical web meeting chord at pitch θ: angle between them = 90° − θ →
  cut angle = 90° − (90° − θ) = θ
- Orientation: VERTICAL

**Web 2 — left diagonal** (Object name `Truss_NN_Web_2`):

- Bottom centerline: `(S/3, 0, 0)` (panel point on bottom chord)
- Top centerline: `(S/2, 0, peak_height)` (peak)
- **Cut length** = `sqrt((S/6)² + peak_height²)`
- **cut_angle_start_deg** (bottom, at bottom chord) = `90° − φ_diag`
  — diagonal web at φ_diag meeting horizontal chord: angle between them =
  φ_diag → cut angle = 90° − φ_diag
- **cut_angle_end_deg** (top, at top chord underside at the peak) =
  `90° − (φ_diag − θ)`
  — both members go up-right; angle between them = φ_diag − θ → cut angle
  = 90° − (φ_diag − θ)
- Orientation: ANGLED

For the worked example (S=144, pitch 6/12, h=0):
- φ_diag = 56.31°, θ = 26.57°
- cut_angle_start = 33.69°, cut_angle_end = 60.26°
- Cut length = √(24² + 36²) ≈ 43.27"

**Web 3 — right diagonal** (Object name `Truss_NN_Web_3`):

Mirror of Web 2 about `x = S/2`. Same cut length, same cut-angle magnitudes,
opposite slope direction.

**Web 4 — right vertical** (Object name `Truss_NN_Web_4`):

Mirror of Web 1 about `x = S/2`. Same cut length, same cut angles.

The implementation in `templates.py:truss_member_lengths_and_angles` computes
every member's centerline endpoints, cut lengths, cut angles, and orientation
from the Roof's design parameters. The formulas above are the canonical math;
the helper is the canonical implementation.

### Heel blocks (only when `heel_height_in > 0`)

Two vertical pieces at the heels, each running from the cap plate up to the
top chord centerline:

- `Truss_NN_HeelBlock_L`: centerline from `(0, 0, 0)` to `(0, 0, h)`
- `Truss_NN_HeelBlock_R`: centerline from `(S, 0, 0)` to `(S, 0, h)`

Member specs:
- Cross-section: same as `top_chord_nominal`
- **Cut length** = `h`
- **cut_angle_start_deg** = `0.0`
- **cut_angle_end_deg** = `0.0`
- Orientation: VERTICAL

Both cuts are square. The top chord's bottom face passes over the heel block
at the chord's centerline-x = 0 (and analogously at x = S). The centerline
math treats the heel block top centerline as coincident with the top chord
centerline at that x; the small physical interference between the heel
block's top corners and the top chord's sloped bottom face is below cut-list
resolution and is left for the mesh build to handle visually.

If `h == 0`, no heel blocks are created; the top chord and bottom chord
centerlines meet at the heel directly.

### Mesh naming

Each truss member's mesh datablock name encodes enough variation that
geometrically distinct pieces don't collide, enabling linked-mesh reuse across
trusses with the same design:

- Top chord: `praxova_mesh_truss_top_chord_<nominal>_<length_in>_<pitch>`
- Bottom chord: `praxova_mesh_truss_bottom_chord_<nominal>_<length_in>`
- Web: `praxova_mesh_truss_web_<nominal>_<length_in>_<angle_start>_<angle_end>`
- Heel block: `praxova_mesh_truss_heel_block_<nominal>_<length_in>`

Since all trusses in a single Roof share identical geometry in v0.7.0, every
truss reuses the same set of meshes — N trusses × 6 to 8 members each, but
typically only 4 to 6 distinct mesh datablocks total per Roof.

### Truss positioning along the ridge axis

Mirrors the v0.5 sheathing-aligned stud layout, applied along the bearing wall
length axis:

- First truss: outer face flush with the bearing wall's start (the gable wall
  end at x = 0 on the bearing wall's local frame)
- Last truss: outer face flush with the bearing wall's end (x = bearing_wall_length)
- Intermediate trusses: centerlines at OC spacing measured from x = 0
- Final bay: tight when bearing_wall_length is not a multiple of OC

Truss count: `ceil((bearing_wall_length - st_top) / oc_spacing) + 1`.

Each truss `Truss_NN` Empty is placed at:
- Ridge-axis position: as computed above
- Span-axis position: 0 (truss origin at wall_a's exterior face)
- Vertical position: top of cap plate

with world rotation matching the bearing walls' X-axis direction.

### Cap plate Z elevation

The bottom chord rests on top of the bearing walls' cap plates. The cap plate
top is at `wall_height_in` above the wall's base plane (the existing v0.6 wall
convention). So the truss's Z = 0 plane (where the bottom chord's bottom face
sits) lies at world Z = bearing_wall_a.location.z + wall_height_in.

v0.7.0 validates that both bearing walls have the same `wall_height_in`. If
they don't, the operator reports an error.

## `frame_roof` Orchestrator

```python
def execute(self, context):
    sp = context.scene.praxova_framing
    level = sp.active_level

    # 1. Pre-validation: Level set
    if level is None or not level.praxova_level.is_level:
        self.report({'ERROR'}, "No active Level. Use the Building tab to select one.")
        return {'CANCELLED'}

    # 2. Find the Roof under this Level (one per Level in v0.7.0)
    roof = next(
        (c for c in level.children
         if getattr(c, 'praxova_roof', None) is not None
         and c.praxova_roof.is_roof),
        None,
    )
    if roof is None:
        self.report({'ERROR'}, "Active Level has no Roof. Use the Roof Framing tab to add one.")
        return {'CANCELLED'}

    rp = roof.praxova_roof

    # 3. Validate Roof (bearing walls set / parallel / same height /
    #    span within single-piece bottom-chord limit / pitch sane)
    valid, msg = templates.validate_roof(rp, level)
    if not valid:
        self.report({'ERROR'}, msg)
        return {'CANCELLED'}

    # 4. Compute geometry once (all trusses in a Roof share the design).
    #    The Commit-1 helpers return plain dicts and may raise ValueError
    #    on degenerate geometry or an unknown truss_type.
    try:
        layout = templates.compute_truss_layout(rp)
        member_specs = templates.truss_member_lengths_and_angles(rp, layout)
        placements = templates.compute_truss_placements(rp, layout)
    except ValueError as e:
        self.report({'ERROR'}, str(e))
        return {'CANCELLED'}

    # 5. Delete existing Truss children of this Roof (delete-and-
    #    regenerate; no per-truss edit semantics in v0.7.0).
    for child in list(roof.children):
        if (getattr(child, 'praxova_truss', None) is not None
                and child.praxova_truss.is_truss):
            _delete_object_tree(child)

    # 6. Roof world transform must be current before we read it for the
    #    matrix_parent_inverse placement idiom.
    context.view_layer.update()
    roof_inv = roof.matrix_world.inverted()

    # 7. Create each truss Empty + build its members.
    for placement in placements:
        truss_empty = _make_truss_empty(
            context,
            name=f"Truss_{placement['truss_index']:02d}",
            parent=roof,
            parent_inverse=roof_inv,
            world_location=placement['world_location'],     # inches
            world_rotation=placement['world_rotation_euler'], # radians
        )
        _build_truss_members(context, truss_empty, member_specs)

    # 8. Report + select the Roof.
    _set_active_only(context, roof)
    self.report(
        {'INFO'},
        f"Framed {len(placements)} {rp.truss_type} truss"
        f"{'es' if len(placements) != 1 else ''} "
        f"(span {layout['span_in']:.1f}\", pitch {_format_pitch(rp)})",
    )
    return {'FINISHED'}
```

Key dict keys (from Commit 1): `layout['span_in']`,
`placement['truss_index']`, `placement['world_location']` (inches, 3-tuple),
`placement['world_rotation_euler']` (radians, 3-tuple), and each member spec
carries `'length_in'`, `'cut_angle_start_deg'`, `'cut_angle_end_deg'`,
`'orientation'`, `'nominal'`, `'object_name_suffix'`, `'truss_local_origin'`
(inches, 3-tuple), `'truss_local_axis_direction'` (unit 3-tuple).

## New Helpers in `templates.py`

New section: `# Truss helpers (v0.7)`.

### `resolve_pitch_ratio(roof_props) -> float`

Pure function. Returns rise/run as a float. Resolves the enum to its numeric
value, or returns `roof_props.pitch_rise_in / 12.0` for CUSTOM.

### `compute_bearing_wall_geometry(wall_obj) -> dict`

Returns a dict with:
- `'length_in'`, `'height_in'`, `'thickness_in'`, `'nominal'`
- `'world_centerline_start'`, `'world_centerline_end'` (the two endpoints of
  the wall's length axis, measured along the centerline, as 3-tuples of
  floats in world coords)
- `'world_x_axis'`, `'world_y_axis'`, `'world_z_axis'` (the wall's local axes
  expressed as world-space unit vectors, derived from the wall's world
  rotation; useful for face-plane derivation downstream)

Reads world transform off `wall_obj` — the one v0.7.0 helper in `templates.py`
that touches `bpy` data, kept read-only.

### `compute_truss_layout(roof_props) -> dict`

Pure function. Returns a dict with:
- `'span_in'`: float (computed exterior-face to exterior-face)
- `'pitch_ratio'`: float
- `'pitch_angle_deg'`: float (= `degrees(atan(pitch_ratio))`)
- `'peak_height_in'`: float (above cap plate, including heel_height_in)
- `'truss_count'`: int
- `'truss_positions_in'`: list of floats (positions along the ridge axis,
  measured from `bearing_wall_a.world_centerline_start`)
- `'ridge_axis_direction'`: 3-tuple unit vector (matches bearing walls' +X
  axis direction in world coords)
- `'span_axis_direction'`: 3-tuple unit vector (perpendicular, from wall_a
  exterior face toward wall_b exterior face, in world coords)
- `'world_origin'`: 3-tuple, the world-space point that becomes truss-local
  (0, 0, 0) for the first truss — at wall_a's exterior face, at the start
  of the bearing wall length axis, at cap plate top elevation

Calls `compute_bearing_wall_geometry` for each wall, derives exterior faces
by the "face whose normal points away from the other wall's centerline" rule.

### `truss_member_lengths_and_angles(roof_props, truss_layout) -> dict`

Pure function. Returns:

```python
{
    'bottom_chord': {
        'length_in': S,
        'cut_angle_start_deg': 0.0,
        'cut_angle_end_deg': 0.0,
        'orientation': 'HORIZONTAL',
        'nominal': roof_props.bottom_chord_nominal,
        'truss_local_origin': (0.0, 0.0, 0.0),
        'truss_local_rotation_deg': 0.0,
    },
    'top_chord_l': {...},   # ANGLED, plumb cuts both ends
    'top_chord_r': {...},
    'web_1': {...},   # VERTICAL
    'web_2': {...},   # ANGLED
    'web_3': {...},   # ANGLED
    'web_4': {...},   # VERTICAL
    'heel_block_l': {...} | None,   # None if heel_height == 0
    'heel_block_r': {...} | None,
}
```

Dispatched by `roof_props.truss_type` (only FINK in v0.7.0; v0.7.50 adds more
keys to the dispatch table).

### `compute_truss_placements(roof_props, truss_layout) -> list[dict]`

Pure function. Returns N placement dicts, one per truss, each with:
- `'truss_index'`: int (1-based, used for Truss_NN naming)
- `'world_location'`: 3-tuple, the world-space location of the Truss_NN Empty
- `'world_rotation_euler'`: 3-tuple of radians (Z-rotation matches the bearing
  walls' Z-rotation so each truss's local X axis aligns with the span axis)

The placement's `world_location` is derived from
`truss_layout['world_origin']` shifted along `ridge_axis_direction` by
`truss_positions_in[i]`.

### `validate_roof(roof_props, level_obj) -> (bool, str)`

Pure function. Returns `(True, "")` on success or `(False, error_message)` on
first failure. Checks in order:

1. `bearing_wall_a` and `bearing_wall_b` both set and not None
2. Both walls in `level_obj.children` and have `is_wall == True`
3. `bearing_wall_a != bearing_wall_b`
4. Both walls parallel (Z rotations differ by 0 or 180° within 0.5° tolerance)
5. Both walls' lengths equal within 0.125" tolerance
6. Both walls' heights equal within 0.125" tolerance
7. Bearing walls aligned: their X-axes are parallel translates (perpendicular
   distance from each end of wall_a's X-axis to wall_b's X-axis line equal
   within tolerance)
8. Computed span > 0 and ≤ `MAX_STOCK_LENGTH_IN` (bottom chord single-piece
   constraint for v0.7.0)
9. Computed span ≥ `2 × (eave_overhang_in + 6.0)` — sanity bound, prevents
   degenerate geometry
10. Pitch valid: enum value resolved successfully, or `pitch_rise_in` in
    [1.0, 24.0] for CUSTOM
11. `eave_overhang_in ≥ 0` (enforced by FloatProperty min, but re-checked)
12. `heel_height_in ≥ 0`

Error message format: `"Roof: <specific message>"`.

## UI Structure

### N-panel layout

```
N-panel "Praxova" category:
├── PRAXOVA_PT_wall_framing    (existing v0.5/v0.6)
├── PRAXOVA_PT_building        (existing v0.6)
└── PRAXOVA_PT_roof_framing    (NEW v0.7)
```

### Roof Framing tab

```
Roof Framing tab:
├── Context indicator:
│   - "No Level active" (no active Level)
│   - "Editing Roof in <Level name>" (Roof exists in active Level)
│   - "Active Level has no Roof" (+ [Add Roof] button)
│
├── Roof configuration (only shown if Roof exists):
│   ├── Truss type (FINK only in v0.7.0)
│   ├── Bearing walls:
│   │   ├── Bearing Wall A picker (PointerProperty)
│   │   └── Bearing Wall B picker (PointerProperty)
│   ├── Computed span readout (carpenter-format `= N' M.M"`)
│   ├── Pitch dropdown (3/12 through 12/12 + CUSTOM)
│   ├── pitch_rise_in field (only shown when pitch == CUSTOM)
│   ├── Eave overhang (with carpenter-format readout)
│   ├── Heel height (with carpenter-format readout)
│   ├── Member nominals:
│   │   ├── Top chord nominal
│   │   ├── Bottom chord nominal
│   │   └── Web nominal
│   ├── OC spacing
│   ├── Live preview: truss count, peak height, top chord slope length
│   ├── Validation indicator (live; shows error if any)
│   └── [Frame Roof] button
```

The bearing wall pickers are plain `PointerProperty(Object)` dropdowns
(`row.prop(rp, "bearing_wall_a", text="")`), matching the joint detail
panel's `wall_a` / `wall_b` pickers — they accept any Object, and
`validate_roof` (surfaced live below the fields and again at Frame Roof
time) rejects non-wall / non-parallel / mismatched picks. No property-level
`poll` filter is used (consistent with the rest of the add-on, and it keeps
this an `ui.py`-only commit). The "Computed span readout" updates live as the
user picks bearing walls or moves them in the viewport.

## Validation Rules

For `add_roof`:

1. Active Level set and `is_level == True`
2. Active Level has no existing Roof child (one Roof per Level in v0.7.0)

Error message format: `"Roof: <specific message>"`.

For `frame_roof`:

1. Active Level set
2. Roof child exists in active Level
3. All checks from `validate_roof` (see above)

## Workflows

### Frame a roof on a rectangular building

1. (Prerequisite) Building, Level, four walls, and joints set up per v0.6
   workflow. Walls positioned in the viewport to form a rectangle.
2. Roof Framing tab → **Add Roof** (the button appears when active Level has
   no Roof yet)
3. In the Roof config section, pick **Bearing Wall A** and **Bearing Wall B**
   (the two parallel walls the trusses will bear on)
4. Set pitch (e.g., 6/12), eave overhang (e.g., 12"), heel height (0 for
   standard, 12-16" for energy heel)
5. Confirm member nominals (defaults: 2x6 top/bottom chord, 2x4 web)
6. Confirm OC spacing (default 24")
7. The live validation indicator should be green and the live preview should
   show the truss count and peak height
8. Click **Frame Roof** — the orchestrator creates N trusses parented under
   the Roof Empty, each with its top chords, bottom chord, webs, and (if
   applicable) heel blocks

### Editing a roof

1. Open the Roof Framing tab. The active Level's Roof is shown.
2. Change any field (pitch, overhang, member nominals, OC spacing, etc.).
3. Click **Frame Roof** — existing trusses are deleted and regenerated with
   the new design parameters.

### Editing a bearing wall

1. Select the wall Empty in the viewport.
2. Wall Framing tab → change length / height / position.
3. Click **Frame Wall**. The wall regenerates.
4. Open Roof Framing tab → click **Frame Roof**. The roof regenerates against
   the wall's new geometry. v0.7.0 does not auto-trigger this.

### Monopoly-style (flush eave) roof

Same as the standard workflow, with `eave_overhang_in = 0`. The top chords
terminate at the bearing wall's exterior face — no overhang, no fascia detail.

### Bearing on gable walls (chicken-coop case)

Same as the standard workflow. The user picks the two short walls of the
rectangle as `bearing_wall_a` and `bearing_wall_b`. The orientation is purely
data-driven from which walls are picked.

## Out of Scope (deferred to later cycles)

- Truss types other than Fink (king-post, queen-post, scissor, attic,
  mono-pitch, gable-end) — v0.7.50
- Multi-piece chord members (spliced or lapped bottom chord for spans > 16') —
  v0.7.50
- Multiple Roofs per Level (e.g., hip roof corners, dormers, gambrel where the
  side-roof and main-roof are separate Roofs) — v0.7.50+
- Gable-end trusses (vertical studs in place of webs, for sheathing) — v0.7.60
- Gable wall rake support (sloped top plate, varying-height studs in the gable
  wall) — v0.7.60
- Rake overhang (`rake_overhang_in` on the Roof) — v0.7.60
- Gambrel roof (double-pitch top chord with knee-wall integration) — v0.7.70
- Ridge beam / stick-framed rafters (alternative to trusses for site-built
  roofs) — possibly v0.8+
- Hip rafters and hip jacks — possibly v0.8+
- Roof sheathing (deferred; will use existing `duplicate_e2e` operator on the
  top-chord plane)
- Auto-trigger of `frame_roof` when a bearing wall is edited — v0.7+ likely
- Pre-engineered truss representation ("order N of design X" without modeling
  individual pieces) — possibly v0.8+
- Engineering-grade truss analysis (load paths, member sizing) — out of scope
  permanently; this is a design / takeoff tool, not an engineering tool

## Cycle Structure

Five commits, in order.

### Commit 1: `templates.py` — truss geometry helpers

File: `templates.py`

New section header: `# Truss helpers (v0.7)`. Adds:

- `resolve_pitch_ratio(roof_props) -> float`
- `compute_bearing_wall_geometry(wall_obj) -> dict`
- `compute_truss_layout(roof_props) -> dict`
- `truss_member_lengths_and_angles(roof_props, truss_layout) -> dict`
- `compute_truss_placements(roof_props, truss_layout) -> list[dict]`
- `validate_roof(roof_props, level_obj) -> tuple[bool, str]`

All helpers return plain dicts and tuples, matching the existing
`templates.py` convention (`compute_wall_joint_context`, `validate_joints`,
`l_corner_geometry`, etc. — no `@dataclass` usage anywhere in the project).

All functions are pure except `compute_bearing_wall_geometry`, which reads
(but never writes) world transform data off a wall Object via the standard
Blender `obj.matrix_world` / `obj.praxova_wall` API.

### Commit 2: Data model — `PraxovaRoofProps` / `PraxovaTrussProps` + lumber-tag extensions

Files: `properties.py`, `__init__.py`

- Add `PraxovaRoofProps` and `PraxovaTrussProps` PropertyGroups
- Attach as PointerProperty on Object type:
  `bpy.types.Object.praxova_roof = PointerProperty(...)`,
  `bpy.types.Object.praxova_truss = PointerProperty(...)`
- Extend `PraxovaLumberProps` with `cut_angle_start_deg` and
  `cut_angle_end_deg`
- Extend the `orientation` EnumProperty with `'ANGLED'`
- Update class registration order in `__init__.py`

No UI yet for the Roof; only programmatic creation paths exist after this
commit. Existing v0.6 walls / sheets / panels continue to work unchanged
(orientation enum extension is backward-compatible; cut angles default to 0).

### Commit 3: `PRAXOVA_OT_add_roof` + `PRAXOVA_OT_frame_roof`

File: `ops_frame.py`

- `PRAXOVA_OT_add_roof` operator: validates that active Level exists and has
  no Roof; creates a new Empty parented under the active Level; sets
  `praxova_roof.is_roof = True` and applies default field values
- `PRAXOVA_OT_frame_roof` operator: the orchestrator (see "frame_roof
  Orchestrator" above). Calls into `templates.compute_truss_layout`,
  `templates.truss_member_lengths_and_angles`,
  `templates.compute_truss_placements` to drive geometry creation
- Internal helper `_build_truss_children(truss_empty, member_specs)` that
  creates the lumber Objects parented under the truss Empty, sets each
  Object's `praxova_lumber` tag including the new cut-angle fields and
  ANGLED orientation where applicable

### Commit 4: UI — `PRAXOVA_PT_roof_framing` panel

File: `ui.py`

- Add `PRAXOVA_PT_roof_framing` panel under the "Praxova" N-panel category
- Add bearing wall pickers as plain `PointerProperty(Object)` dropdowns
  (no property-level `poll` — matches the joint `wall_a` / `wall_b`
  pattern; `validate_roof` provides the live feedback instead)
- Add the live computed-span readout, pitch dropdown with CUSTOM branch, live
  preview (truss count, peak height, top chord slope length), live validation
  indicator, and Frame Roof button
- Register the new panel class in `__init__.py`

### Commit 5: End-of-cycle — manifest + version + smoke + CHANGELOG + README

Files: `blender_manifest.toml`, `__init__.py`, `smoke_test.py`, `CHANGELOG.md`,
`README.md`

- `blender_manifest.toml`: `0.6.61` → `0.7.0`
- `__init__.py`: `__version__ = "0.7.0"`
- `smoke_test.py`: `addon_version` assertion `"0.6.61"` → `"0.7.0"`. Method
  count stays `18` (no bridge changes — bridge parity lands in v0.7.1). Add a
  few new smoke steps exercising a basic Fink truss roof (e.g., 12' span,
  6/12 pitch, 0 heel, 12" overhang, 2x6 chords, 2x4 webs) and verifying truss
  count, member counts per truss, cut-angle metadata on top chord and web
  pieces, and ANGLED orientation labels in the cut list
- `CHANGELOG.md`: new `[0.7.0]` entry at top
- `README.md`:
  - Status line: `Beta (v0.6.61)` → `Beta (v0.7.0)`
  - New section "Roof Framing (v0.7.0)" — Roof container, bearing-wall pair,
    Fink truss geometry, energy heel, cut-angle metadata, ANGLED orientation
  - Update roadmap: ✅ v0.7.0, update v0.7.1 entry (bridge parity), add
    v0.7.50 / v0.7.60 / v0.7.70 entries

## End-of-Cycle Validation

1. Pull v0.7 branch
2. Reload add-on in Blender
3. Run `python smoke_test.py` — expect "All checks passed" with `addon_version
   "0.7.0"` and `method_count 18`
4. Manual tests:
   - Create a Building + Level + four walls + L joints per v0.6 workflow,
     positioned to form a 12' × 16' rectangle
   - Open Roof Framing tab; click **Add Roof**; verify Roof Empty appears
     under the Level
   - Pick the two 16' walls as bearing walls; verify the computed span readout
     shows 12'-0" (the perpendicular distance between them)
   - Set pitch 6/12, eave overhang 12", heel 0, default member nominals,
     24" OC
   - Live preview should show 9 trusses (16' / 24" = 8 bays + 1 = 9 trusses)
   - Click **Frame Roof**; verify 9 truss Empties under the Roof Empty, each
     with 2 top chords + 1 bottom chord + 4 webs + 0 heel blocks = 7 pieces
   - Verify in the viewport: trusses spaced at 24" OC along the 16' axis, end
     trusses flush with the wall ends, peak at the centerline
   - Open the cut list; verify the new ANGLED entries with the `A`
     orientation suffix and the cut-angle annotations
   - Change pitch to 12/12, click Frame Roof; verify trusses regenerate with
     a steeper peak
   - Change heel_height_in to 16, click Frame Roof; verify heel blocks appear
     at each truss's heels
   - Change eave_overhang_in to 0, click Frame Roof; verify Monopoly-style
     flush eave (top chords terminate at bearing wall exterior face)
   - Pick the two 12' walls instead of the 16' walls; verify the roof
     re-orients (trusses now span 16' along the perpendicular axis and are
     spaced along the 12' axis); confirms convention-agnostic bearing-wall
     handling
   - Move a bearing wall in the viewport; click Frame Roof; verify the roof
     follows the wall's new position

## Open implementation notes

The cut-angle math, cut-length convention (centerline-to-centerline), and
heel block geometry are now fully specified above. A few items are left to
the implementation:

1. **Cut-angle sign convention** is fixed: `cut_angle_start_deg` and
   `cut_angle_end_deg` are **non-negative magnitudes** (saw-setting values).
   The geometric orientation of each cut — which side of square the cut
   leans — is determined by the member's role in the truss and is handled
   by the mesh-building code. The cut-list output displays the magnitude
   (e.g., `"2x6 × 93.9" (26.6° both ends)"`); a carpenter reading the cut
   list sets the saw to the magnitude and uses the cut-list role label
   (top chord, web) to infer the cut orientation.

2. **Mesh datablock reuse across different Roofs in different Levels** is
   automatic: the mesh naming convention (nominal + length + cut angles, or
   nominal + length + pitch for the top chord) is design-keyed, so
   identically-configured Roofs in different Levels share mesh datablocks
   naturally. No special handling needed.

3. **Member axis orientation in Blender mesh frame**: for each member, the
   mesh is built with the member's long axis along the local mesh +X
   direction (length axis), cross-section in the local Y-Z plane. The truss
   Empty's children are then rotated into truss-local position. The mesh
   itself is shared across all instances of the same design (linked-mesh),
   and the rotation/translation is per-Object. Standard Praxova pattern.

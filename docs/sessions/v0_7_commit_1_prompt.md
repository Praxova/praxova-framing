# Claude Code prompt — v0.7.0 Commit 1: `templates.py` truss helpers

## Context

Adding the first commit of the v0.7.0 cycle (site-built Fink trusses). This
commit adds pure geometry helpers to `templates.py` only. No PropertyGroups,
no operators, no UI, no bridge changes. Those land in Commits 2–5.

Full architectural specification: **`docs/v0.7_design.md`**. The cut-angle
math and member geometry formulas in that doc are canonical — `templates.py`
implements exactly what's in the doc, no more, no less.

Working branch: feature branch off `main` (Alton has already created it).

## Scope

**File to edit**: `templates.py` (the only file touched in this commit).

**File NOT to touch**: `properties.py`, `ops_frame.py`, `ui.py`,
`server/handlers.py`, anything under `mcp_server/`, `smoke_test.py`,
`blender_manifest.toml`, `__init__.py`, `CHANGELOG.md`, `README.md`.
Those are later commits.

**New section to add** (append at the end of the file, after the existing
splice-helpers section that ends around line 1969):

```
# ===========================================================================
# Truss helpers (v0.7)
# ===========================================================================
```

Match the existing section-delimiter style (line of `=` between two `# ===`
lines with the title on the middle line).

## Helpers to implement, in order

All return plain dicts and tuples — match the codebase convention. No
`@dataclass`, no `NamedTuple`. The existing `compute_wall_joint_context`,
`l_corner_geometry`, `validate_joints`, etc. are the templates to mirror for
docstring style and return shape.

### 1. `resolve_pitch_ratio(roof_props) -> float`

Pure. Resolves the EnumProperty pitch + CUSTOM `pitch_rise_in` to a single
rise/run float.

- For `pitch == 'P_N_12'`: return `N / 12.0` (parse N out of the enum key)
- For `pitch == 'CUSTOM'`: return `roof_props.pitch_rise_in / 12.0`
- Defense-in-depth: `ValueError` for unrecognized enum keys (mirrors the
  pattern in `resolve_corner_style`)

### 2. `compute_bearing_wall_geometry(wall_obj) -> dict`

The one helper in v0.7.0 that touches `bpy` data (read-only). Reads
`wall_obj.matrix_world`, `wall_obj.praxova_wall.wall_length_in`,
`wall_obj.praxova_wall.wall_height_in`, and the wall's thickness derived from
`templates.LUMBER_TYPES[wall_obj.praxova_wall.wall_nominal][1]`.

Returns a dict with the keys listed in the design doc's
`compute_bearing_wall_geometry` section. The world-space axis vectors come
from the upper-left 3×3 of `matrix_world` (the wall's local X, Y, Z axes
expressed in world coords). Centerline endpoints come from transforming
`(0, thickness/2, height/2)` and `(length, thickness/2, height/2)` by
`matrix_world`.

### 3. `compute_truss_layout(roof_props) -> dict`

Pure (calls #2, which reads-only). Implements span / pitch / peak height /
truss count / position math per the design doc's `compute_truss_layout`
section. Returns the dict shape specified there.

**Exterior face derivation**: for each bearing wall, compute the centerpoint
of its `y=0` face and the centerpoint of its `y=wall_thickness` face in world
coords (using the world axes from the bearing wall geometry dict).
The exterior face is the one whose centerpoint is **further** from the
paired wall's centerline (which can be approximated as the midpoint of the
paired wall's `world_centerline_start` / `world_centerline_end`).

**Span**: the perpendicular distance between wall_a's exterior face center
and wall_b's exterior face center, measured along the span axis (the
direction from wall_a exterior face toward wall_b exterior face).

**Truss count and positions**: mirror `templates.stud_positions` exactly,
applied along the bearing wall length axis with `oc_spacing_in` from the
roof props. Use `templates.stud_positions` directly if its signature fits;
otherwise factor out a shared helper or duplicate the logic (your call — the
goal is single source of truth where possible).

**Resolve `oc_spacing_in`**: the EnumProperty stores string keys like `'12'`,
`'16'`, `'19.2'`, `'24'`. Convert to float via `float(roof_props.oc_spacing_in)`.

### 4. `truss_member_lengths_and_angles(roof_props, truss_layout) -> dict`

**This is the most math-heavy helper. Implement strictly per
`docs/v0.7_design.md` § "Truss Geometry — Detail" and § "Cut angle
convention".** The doc lists explicit formulas for every member; transcribe
them. Reproduced here for convenience:

Let `S = truss_layout['span_in']`, `pitch_ratio = truss_layout['pitch_ratio']`,
`θ = truss_layout['pitch_angle_deg']`, `h = roof_props.heel_height_in`,
`e = roof_props.eave_overhang_in`,
`peak_height = h + (S/2) * pitch_ratio`,
`φ_diag = degrees(atan(peak_height / (S/6)))`.

Returned dict has these keys (each value is a sub-dict with the per-member
spec — see structure in the design doc's `truss_member_lengths_and_angles`
section):

| Key | Cut length | start_deg | end_deg | Orientation | Object name |
|---|---|---|---|---|---|
| `'bottom_chord'` | `S` | 0 | 0 | HORIZONTAL | `Truss_NN_BottomChord` |
| `'top_chord_l'` | `(S/2 + e) / cos(radians(θ))` | θ | θ | ANGLED | `Truss_NN_TopChord_L` |
| `'top_chord_r'` | same as L | θ | θ | ANGLED | `Truss_NN_TopChord_R` |
| `'web_1'` (L vert) | `h + (S/3) * pitch_ratio` | 0 | θ | VERTICAL | `Truss_NN_Web_1` |
| `'web_2'` (L diag) | `sqrt((S/6)² + peak_height²)` | 90 − φ_diag | 90 − (φ_diag − θ) | ANGLED | `Truss_NN_Web_2` |
| `'web_3'` (R diag) | same as web_2 | 90 − φ_diag | 90 − (φ_diag − θ) | ANGLED | `Truss_NN_Web_3` |
| `'web_4'` (R vert) | same as web_1 | 0 | θ | VERTICAL | `Truss_NN_Web_4` |
| `'heel_block_l'` | `h` if h > 0 else None | 0 | 0 | VERTICAL | `Truss_NN_HeelBlock_L` |
| `'heel_block_r'` | `h` if h > 0 else None | 0 | 0 | VERTICAL | `Truss_NN_HeelBlock_R` |

Heel block keys: present in the returned dict regardless, but their value
is `None` when `h == 0` (so the operator in Commit 3 can iterate the dict
uniformly).

Each member sub-dict carries: `'length_in'`, `'cut_angle_start_deg'`,
`'cut_angle_end_deg'`, `'orientation'`, `'nominal'`, `'object_name_suffix'`
(e.g., `'BottomChord'`, `'TopChord_L'`, `'Web_2'`, `'HeelBlock_L'`),
`'truss_local_origin'` (3-tuple), `'truss_local_axis_direction'` (3-tuple
unit vector along the member's length axis in truss-local coords).

Cut angles are non-negative magnitudes in degrees. If a computed angle
exceeds 89.9° (degenerate geometry — should never happen with the validation
in #6), raise `ValueError` with a descriptive message.

Dispatch on `roof_props.truss_type` (only `'FINK'` in v0.7.0; raise
`ValueError` on unrecognized types so v0.7.50 additions surface cleanly).

### 5. `compute_truss_placements(roof_props, truss_layout) -> list[dict]`

Pure. For each truss position in `truss_layout['truss_positions_in']`,
compute the world location and world rotation for that truss's Empty.

`world_location = truss_layout['world_origin'] + position *
truss_layout['ridge_axis_direction']` (vector addition; treat 3-tuples as
small vectors and use `templates.INCH` for the meters conversion only when
the value will actually be written to a Blender object — keep all internal
math in inches).

`world_rotation_euler`: the Z-rotation needed so the truss's local X axis
aligns with `truss_layout['span_axis_direction']`. Derive from
`atan2(span_axis_direction[1], span_axis_direction[0])` (the angle of the
span axis in the world XY plane). The truss has zero X and Y rotation —
it's a planar assembly standing upright.

### 6. `validate_roof(roof_props, level_obj) -> tuple[bool, str]`

Mirror `validate_joints`'s structure: returns `(True, "")` on success or
`(False, "Roof: <specific message>")` on first failure. Run checks in the
order listed in the design doc's `validate_roof` section (12 checks).

Tolerances:
- Parallel walls: Z rotation difference within 0.5° (or 180° ± 0.5°)
- Length / height equality: 0.125" (matches v0.6's wall-pairing tolerance
  convention)
- Bearing-wall alignment: 0.125" perpendicular distance between each end's
  projection onto the paired wall's X-axis line

For each failure, write the message so the user can diagnose without
opening the doc — include the offending values (e.g.,
`f"Roof: bearing walls have different heights ({a:.2f}\" vs {b:.2f}\")"`).

For check 8 (`MAX_STOCK_LENGTH_IN`), reference the existing constant —
don't redefine it. The message should mention that multi-piece bottom
chord is deferred to v0.7.50.

## Conventions to match

- **Section delimiters**: `# ============...===` lines around `# Title`.
- **Type hints everywhere**, on every signature.
- **Docstrings**: triple-quoted, multi-paragraph for the meaty helpers,
  modeled on `compute_wall_joint_context` / `validate_joints` /
  `l_corner_geometry`. Include rationale and the formula for the math-heavy
  helpers (transcribe the design-doc formulas into the docstrings).
- **No `@dataclass`, no `NamedTuple`**. Plain dicts and tuples.
- **Math**: use `math.radians`, `math.degrees`, `math.atan`, `math.atan2`,
  `math.cos`, `math.sin`, `math.sqrt`. Add `import math` near the top with
  the other imports if it isn't already there.
- **Constants**: reuse `INCH`, `LUMBER_TYPES`, `MAX_STOCK_LENGTH_IN`,
  `lumber_cutlist_label` from elsewhere in `templates.py`. Don't redefine.
- **Imports**: keep all new imports at the top of the file with the
  existing ones (don't add inline imports).
- **Tolerance constants**: define small named tolerances at the top of
  the truss section if you use them more than once (e.g.
  `_PARALLEL_TOLERANCE_DEG = 0.5`, `_LENGTH_TOLERANCE_IN = 0.125`).

## Things explicitly out of scope for this commit

- Do **not** add `PraxovaRoofProps` or `PraxovaTrussProps` — those land in
  Commit 2.
- Do **not** extend `PraxovaLumberTag` with cut angles — Commit 2.
- Do **not** add the `ANGLED` orientation enum value to anything in
  `properties.py` — Commit 2.
- Do **not** write any operators — Commit 3.
- Do **not** write any UI code — Commit 4.
- Do **not** bump the version — Commit 5.

The helpers in this commit will reference `roof_props.pitch`,
`roof_props.heel_height_in`, etc. as if the PropertyGroup existed.
That's fine — those references will resolve correctly once Commit 2 adds
the PropertyGroup. The helpers must be importable and syntactically valid
in isolation, but functional testing waits for Commit 3 (when an operator
exists to call them).

## Verification steps

After completing the changes:

1. **Syntax check**: `python -c "import ast; ast.parse(open('templates.py').read())"`
   — must succeed cleanly.

2. **Line count delta**: `wc -l templates.py` — expect roughly +400 to +600
   lines for the new section. If it's outside that band, double-check
   nothing got duplicated and nothing got missed.

3. **Section header sweep**: `grep -c "^# ===" templates.py` — count of
   `===` delimiter lines should be exactly 2 more than before (one new
   section, two delimiter lines).

4. **No stale references**: `grep -n "NOMINAL_ITEMS\|@dataclass\|TrussLayout\|BearingWallGeometry\|TrussPlacement" templates.py`
   — should return zero matches. The design doc once used these names; the
   final implementation uses dicts.

5. **Function name sweep**: `grep -n "^def " templates.py | tail -20` —
   should show the six new helpers at the end, in this order:
   `resolve_pitch_ratio`, `compute_bearing_wall_geometry`,
   `compute_truss_layout`, `truss_member_lengths_and_angles`,
   `compute_truss_placements`, `validate_roof`.

6. **Import sweep**: `grep -n "^import\|^from" templates.py | head -10` —
   confirm `import math` is present (or already was).

7. **Constant references**: `grep -n "MAX_STOCK_LENGTH_IN\|LUMBER_TYPES\|INCH" templates.py | wc -l`
   — the new section should reference these by name, not redefine them.
   Expect at least 3 references in the new section.

8. **Worked-example spot check** (paste into a Python REPL):

   ```python
   import math
   S = 144.0
   pitch_ratio = 0.5  # 6/12
   theta = math.degrees(math.atan(pitch_ratio))
   h = 0.0
   e = 12.0
   peak_height = h + (S / 2) * pitch_ratio
   phi_diag = math.degrees(math.atan(peak_height / (S / 6)))
   
   # Expected from the design doc:
   assert abs(theta - 26.565) < 0.01
   assert abs(peak_height - 36.0) < 0.001
   assert abs(phi_diag - 56.310) < 0.01
   
   # Top chord cut length:
   top_len = (S / 2 + e) / math.cos(math.radians(theta))
   assert abs(top_len - 93.915) < 0.01
   
   # Web 2 cut length:
   web2_len = math.sqrt((S / 6) ** 2 + peak_height ** 2)
   assert abs(web2_len - 43.267) < 0.01
   
   # Web 2 cut angles:
   web2_start = 90 - phi_diag
   web2_end = 90 - (phi_diag - theta)
   assert abs(web2_start - 33.690) < 0.01
   assert abs(web2_end - 60.255) < 0.01
   
   print("Worked example OK")
   ```

   If the implementation's `truss_member_lengths_and_angles` is called with
   matching inputs, every cut length and angle should agree with these
   reference values within 0.01.

Report results in the standard audit format: green checkmarks for each
verification step, and any deviations called out with line numbers.

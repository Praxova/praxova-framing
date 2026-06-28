# Claude Code prompt — v0.7.1 Commit 1: `frame_roof` bridge handler

## Context

Commit 1 of the v0.7.1 cycle (roof / truss bridge parity). This commit adds the
`frame_roof` JSON-RPC handler to `server/handlers.py` — the bridge equivalent
of the v0.7.0 roof-framing operators. It follows the **`frame_wall`
CREATE/REBUILD pattern**: one method that creates-and-frames when the Level has
no Roof, or reconfigures-and-reframes (omit-preserves) when it already has one.

After this commit:
- `frame_roof` is callable over the bridge (CREATE + REBUILD modes).
- `method_count` (reported by `ping`) goes 18 → 19.
- No FastMCP wrapper yet (Commit 2), no smoke steps yet (Commit 3), no version
  bump yet (Commit 4).

Full specification: **`docs/v0.7.1_design.md`**, especially §§ "RPC Method —
`frame_roof`", "Helper — `_parse_roof_config`", "Config write / snapshot /
restore helpers", and "METHODS registry". Implement the handler exactly as the
behavior pseudocode there describes.

## Scope

**File to edit**: `server/handlers.py` only.

**Files NOT to touch**: `mcp_server/` (Commit 2), `smoke_test.py` (Commit 3),
`blender_manifest.toml` / `__init__.py` / `CHANGELOG.md` / `README.md`
(Commit 4), and everything outside `server/` (`templates.py`, `properties.py`,
`ops_frame.py`, `ui.py`, `ops_cutlist.py` are all final — the bridge calls into
them but changes none of them).

## Conventions confirmed from the existing file

These are verified against the current `handlers.py` — match them exactly:

- **Error codes** (module constants near the top): `APP_OBJECT_NOT_FOUND =
  -32002`, `APP_OPERATOR_FAILED = -32004`. Generic JSON-RPC codes come from the
  `bridge` module: `bridge.INVALID_PARAMS`, `bridge.INTERNAL_ERROR`. Raise via
  `raise bridge.RPCError(<code>, <message>)`.
- **`_require(params, key, type_, *, choices=())`** — exists; raises
  `INVALID_PARAMS` for missing key, wrong type, or value not in `choices`.
  Returns the value. Use it for every field in `_parse_roof_config` (each is
  known-present because we guard with `key in params` first).
- **`_optional(params, key, type_, default=None, *, choices=())`** — exists;
  returns `default` when the key is absent or `None`.
- **Nominal validation**: the established idiom is inline
  `choices=tuple(templates.LUMBER_TYPES)` (see `add_lumber` / `frame_wall`).
  There is NO `_NOMINAL_CHOICES` constant — use `tuple(templates.LUMBER_TYPES)`
  inline for the three nominal fields (the design doc's `_NOMINAL_CHOICES`
  placeholder maps to this).
- **No shared numeric-range helper exists.** `add_level` does its range check
  inline: `if isinstance(level_height_in, bool) or level_height_in <= 0:`. The
  `_location_param` helper rejects bool with
  `isinstance(c, (int, float)) and not isinstance(c, bool)`. Follow this idiom
  for the three roof range checks — either a small handler-local
  `_reject_bool_and_range(value, lo, hi, field)` helper (preferred, since it's
  used three times) or inline. If you add the helper, place it near the other
  small param helpers (`_type_label`, `_location_param`).
- **`_check_op_result(result, op_name)`** — exists; raises if the operator
  result isn't `{'FINISHED'}`. Call after every `bpy.ops.praxova.*` invoke.
- **`_resolve_level(level_name)`** — exists; resolves a Level Empty by name with
  the standard not-found error shape.
- **`_resolve_wall_in_level(name, level, field)`** — exists; resolves a wall
  name to a wall Empty parented under `level`, with the three failure shapes
  (not in scene / not a Praxova wall / wrong Level), all `INVALID_PARAMS`, the
  message naming both the bad value and the Level. Reuse verbatim for the two
  bearing walls.
- **Scene-pointer pattern**: `add_level` sets `sp.active_building = building`
  before invoking its operator (so the operator parents correctly). `frame_roof`
  sets `sp.active_level = level` before invoking `add_roof` (CREATE) and again
  before `frame_roof` (both modes) — `sp = bpy.context.scene.praxova_framing`.
- **`handlers.py` keeps `server/` free of UI-layer imports** — the comment in
  `frame_building` notes it inlines the walls-in-level walk "rather than
  imported from ui.py". So **do NOT import `_roof_in_level` from `ui.py`** —
  define a handler-local `_roof_in_level` (see below).

## Work items

### 1. Module-level constants (pitch map + choices)

Near the other module-level choice tuples / constants in `handlers.py` (e.g.
where `_JOINT_*_CHOICES` live), add the pitch maps:

```python
# v0.7.1: roof pitch wire-format <-> PraxovaRoofProps enum-key mapping.
# The wire accepts carpenter strings ("6/12"); the PropertyGroup stores
# P_N_12 / CUSTOM enum keys. Map both directions in one place.
_PITCH_STR_TO_KEY = {
    "3/12": "P_3_12", "4/12": "P_4_12", "5/12": "P_5_12",
    "6/12": "P_6_12", "7/12": "P_7_12", "8/12": "P_8_12",
    "9/12": "P_9_12", "10/12": "P_10_12", "12/12": "P_12_12",
    "CUSTOM": "CUSTOM",
}
_PITCH_KEY_TO_STR = {v: k for k, v in _PITCH_STR_TO_KEY.items()}
_PITCH_WIRE_CHOICES = tuple(_PITCH_STR_TO_KEY.keys())
```

(No nominal-choices constant — use `tuple(templates.LUMBER_TYPES)` inline.)

### 2. Handler-local helpers

Add these near the other resolution/parse helpers (e.g. after
`_resolve_wall_in_level` / `_parse_joint`), BEFORE the `frame_roof` handler that
uses them.

**`_roof_in_level(level)`** — the same walk the operators and UI use, inlined
here to keep `server/` import-clean:

```python
def _roof_in_level(level: bpy.types.Object):
    """Return the single Roof Empty under `level`, or None.

    One Roof per Level (v0.7.0/.1). Mirrors the walk frame_roof /
    add_roof / the Roof Framing panel use (is_roof == True among the
    Level's children). Inlined rather than imported from ui.py to keep
    server/ free of UI-layer dependencies (same rationale as
    frame_building's inlined walls-in-level walk).
    """
    return next(
        (c for c in level.children
         if getattr(c, 'praxova_roof', None) is not None
         and c.praxova_roof.is_roof),
        None,
    )
```

**`_reject_bool_and_range(value, lo, hi, field)`** — small numeric guard (only
if you choose the helper over inlining):

```python
def _reject_bool_and_range(value, lo: float, hi: float, field: str) -> None:
    """Reject bool (an int subclass) and out-of-range numerics for a roof
    param. INVALID_PARAMS with the field name and the accepted range."""
    if isinstance(value, bool) or not (lo <= value <= hi):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'"{field}" must be a number in [{lo}, {hi}]',
        )
```

**`_parse_roof_config(params, level)`** — exactly as in the design doc's
"Helper — `_parse_roof_config`" section. Returns ONLY the keys explicitly
present in `params` (guard each with `key in params`), normalized:
`pitch` → `pitch_key` (via `_PITCH_STR_TO_KEY`), bearing-wall names → `wall_a`
/ `wall_b` Object refs (via `_resolve_wall_in_level`) plus `wall_a_name` /
`wall_b_name`, the three range-checked floats, the three nominals (validated
against `tuple(templates.LUMBER_TYPES)`), `truss_type`, `oc_spacing_in`. Raises
on any param-level error BEFORE the handler mutates scene state.

**`_write_roof_config(rp, parsed)`**, **`_snapshot_roof_config(rp)`**,
**`_restore_roof_config(rp, snap)`**, **`_roof_config_to_wire(rp)`** — exactly
as in the design doc's "Config write / snapshot / restore helpers" and
"Response config-echo builder" sections. `_write_roof_config` writes only the
keys present in `parsed` (omit-preserves). `_snapshot`/`_restore` capture and
reassign all 11 design fields (bearing walls as Object refs).
`_roof_config_to_wire` maps the pitch enum key back to the carpenter string
(`_PITCH_KEY_TO_STR`) and bearing-wall refs back to names (or `None`).

### 3. The `frame_roof` handler

Implement exactly the behavior pseudocode in the design doc's "RPC Method —
`frame_roof`" section. Structure:

```python
def frame_roof(params: dict) -> dict:
    """Create-and-frame or reconfigure-and-reframe a Level's Roof.

    ... (full docstring — see below for required content) ...
    """
    level_name = _require(params, "level_name", str)
    level = _resolve_level(level_name)

    existing = _roof_in_level(level)
    created = existing is None

    # Param-level validation + normalization BEFORE any scene mutation.
    parsed = _parse_roof_config(params, level)

    scene = bpy.context.scene
    sp = scene.praxova_framing

    if created:
        # CREATE: name-collision guard, create the Empty via the operator,
        # write config, validate; roll back (delete the Empty) on failure.
        if "name" in params and params["name"] in bpy.data.objects:
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'name {params["name"]!r} already exists in the scene',
            )
        sp.active_level = level
        result = bpy.ops.praxova.add_roof('EXEC_DEFAULT')
        _check_op_result(result, "praxova.add_roof")

        roof = _roof_in_level(level)
        if roof is None:
            raise bridge.RPCError(
                bridge.INTERNAL_ERROR,
                "add_roof finished but produced no Roof under the Level",
            )
        if "name" in params:
            roof.name = params["name"]

        _write_roof_config(roof.praxova_roof, parsed)
        ok, msg = templates.validate_roof(roof.praxova_roof, level)
        if not ok:
            # CREATE atomicity: no stranded Roof. The Empty has no
            # children yet (frame_roof hasn't run), so a plain remove
            # suffices.
            bpy.data.objects.remove(roof, do_unlink=True)
            raise bridge.RPCError(bridge.INVALID_PARAMS, msg)
    else:
        # REBUILD: snapshot, write provided config, validate; restore on
        # failure so a failed REBUILD leaves the Roof unchanged.
        roof = existing
        snapshot = _snapshot_roof_config(roof.praxova_roof)
        _write_roof_config(roof.praxova_roof, parsed)
        ok, msg = templates.validate_roof(roof.praxova_roof, level)
        if not ok:
            _restore_roof_config(roof.praxova_roof, snapshot)
            raise bridge.RPCError(bridge.INVALID_PARAMS, msg)

    # Generate (delete-and-regenerate trusses).
    sp.active_level = level
    result = bpy.ops.praxova.frame_roof('EXEC_DEFAULT')
    _check_op_result(result, "praxova.frame_roof")

    # Post-op: re-fetch trusses + report the canonical layout.
    rp = roof.praxova_roof
    trusses = [
        c for c in roof.children
        if getattr(c, 'praxova_truss', None) is not None
        and c.praxova_truss.is_truss
    ]
    layout = templates.compute_truss_layout(rp)

    trusses_framed = []
    for truss in trusses:
        n_top = sum(1 for c in truss.children
                    if c.name.startswith(f"{truss.name}_TopChord_"))
        n_bot = sum(1 for c in truss.children
                    if c.name.startswith(f"{truss.name}_BottomChord"))
        n_web = sum(1 for c in truss.children
                    if c.name.startswith(f"{truss.name}_Web_"))
        n_heel = sum(1 for c in truss.children
                     if c.name.startswith(f"{truss.name}_HeelBlock_"))
        trusses_framed.append({
            "truss_name": truss.name,
            "n_top_chords": n_top,
            "n_bottom_chords": n_bot,
            "n_webs": n_web,
            "n_heel_blocks": n_heel,
            "n_members": n_top + n_bot + n_web + n_heel,
        })

    config = _roof_config_to_wire(rp)
    return {
        "roof_name": roof.name,
        "level_name": level.name,
        "created": created,
        "truss_count": len(trusses),
        "span_in": layout["span_in"],
        "pitch": config["pitch"],
        "peak_height_in": layout["peak_height_in"],
        "bearing_wall_a_name": config["bearing_wall_a_name"],
        "bearing_wall_b_name": config["bearing_wall_b_name"],
        "config": config,
        "trusses_framed": trusses_framed,
    }
```

Sorting the `trusses` list is optional; if `roof.children` order isn't stable,
sort by `truss.name` so `trusses_framed` is deterministic (a natural sort on
the `Truss_NN` suffix, or a simple `sorted(trusses, key=lambda t: t.name)` —
the zero-padded `NN` makes lexical sort correct for up to 99 trusses).

Note: `compute_truss_layout` reads `rp.bearing_wall_a/.b.matrix_world`. It runs
post-op, so the walls' transforms are current. If a stale-transform concern
arises, `bpy.context.view_layer.update()` before the layout read is the
defensive fix (the operator already ran, so transforms should be fresh — add
the update only if testing shows a need).

### 4. Handler docstring

The `frame_roof` docstring should follow the depth of `add_building` /
`frame_building` / `frame_wall`. Cover: the CREATE/REBUILD modes and how
they're picked (Level has a Roof or not), omit-preserves on REBUILD, the
required params (`level_name`) and optional design params with their CREATE
defaults, the bearing-wall requirement (validate_roof rejects unset), the
pitch-string mapping, the `validate_roof` errors the caller may see, the
CREATE-atomicity / REBUILD-rollback behavior, and the full Returns shape
(`created`, roof-wide geometry, `config` echo, `trusses_framed`). A "Known
footgun" note like `add_joint`'s (bearing-wall names are Object-name strings —
a wall rename invalidates a cached name) fits the house style.

### 5. METHODS registry

Add `frame_roof` to the `METHODS` dict after `frame_building`:

```python
    "frame_building": frame_building,
    # v0.7.1: roof / truss bridge parity (CREATE/REBUILD, mirrors frame_wall).
    "frame_roof": frame_roof,
    "generate_cutlist": generate_cutlist,
    "set_imperial_units": set_imperial_units,
```

`len(METHODS)` becomes 19, so `ping`'s `method_count` reports 19 with no other
change.

## Things explicitly out of scope

- **No FastMCP wrapper.** `mcp_server/` is Commit 2.
- **No smoke steps.** `smoke_test.py` is Commit 3 (and the `method_count`
  assertion there still says 18 until Commit 3 — don't touch it).
- **No version bump.** Manifest / `__init__` / CHANGELOG / README are Commit 4.
- **No `add_roof` / `remove_roof` / `configure_roof` handler.** Only
  `frame_roof`. CREATE mode invokes the `add_roof` *operator* internally; it is
  not exposed as an RPC method.
- **No changes to `templates.py` or any operator.** The handler calls
  `templates.validate_roof` / `templates.compute_truss_layout` and the
  `add_roof` / `frame_roof` operators as-is.

## Verification steps

1. **Syntax check**:
   ```bash
   python -c "import ast; ast.parse(open('server/handlers.py').read())"
   ```

2. **Method count is 19** (static check of the registry):
   ```bash
   python - <<'PY'
   import ast
   src = open('server/handlers.py').read()
   tree = ast.parse(src)
   for node in ast.walk(tree):
       if isinstance(node, ast.Assign):
           for t in node.targets:
               if isinstance(t, ast.Name) and t.id == "METHODS":
                   if isinstance(node.value, ast.Dict):
                       print("METHODS entries:", len(node.value.keys))
   PY
   ```
   Expect `METHODS entries: 19`.

3. **`frame_roof` registered**:
   ```bash
   grep -n '"frame_roof": frame_roof' server/handlers.py
   ```
   One match, after `"frame_building": frame_building`.

4. **Handler + helpers present, helpers before the handler**:
   ```bash
   grep -n "^def frame_roof\|^def _parse_roof_config\|^def _roof_in_level\|^def _write_roof_config\|^def _snapshot_roof_config\|^def _restore_roof_config\|^def _roof_config_to_wire" server/handlers.py
   ```
   All present; each helper's line number precedes `frame_roof`'s.

5. **Pitch constants present**:
   ```bash
   grep -n "_PITCH_STR_TO_KEY\|_PITCH_KEY_TO_STR\|_PITCH_WIRE_CHOICES" server/handlers.py
   ```
   All three defined (the dict, its inverse, the wire-choices tuple).

6. **No UI import leaked in**:
   ```bash
   grep -n "import ui\|from ui\|ui\._roof_in_level\|from .* import.*_roof_in_level" server/handlers.py
   ```
   Zero matches — `_roof_in_level` is defined locally, not imported from `ui`.

7. **Nominal validation uses the inline idiom**:
   ```bash
   grep -n "tuple(templates.LUMBER_TYPES)" server/handlers.py
   ```
   Should appear for the three roof nominals (plus the pre-existing
   `add_lumber` / `frame_wall` uses).

8. **Diff scope**:
   ```bash
   git diff --name-only
   ```
   Exactly `server/handlers.py` (+ `docs/v0.7.1_design.md` if re-saved).
   Nothing else.

9. **Live bridge test** (the runtime proof — needs the add-on reloaded and the
   bridge started in Blender, then a raw JSON-RPC client or the smoke-test
   harness's `call` helper):

   Set up a 12' × 16' rectangle under a test Level via the bridge
   (`add_building` → `frame_wall` × 4 positioned into a rectangle → joints →
   `frame_building`), then:

   a. **CREATE happy path** — `frame_roof` with `level_name`, the two 16' walls
      as `bearing_wall_a_name` / `bearing_wall_b_name`, `pitch="6/12"`,
      `eave_overhang_in=12`, `heel_height_in=0`. Expect `created: true`,
      `truss_count: 9`, `span_in ≈ 144.0`, `pitch: "6/12"`,
      `config.pitch: "6/12"`, `len(trusses_framed) == 9`, each entry
      `n_top_chords: 2, n_bottom_chords: 1, n_webs: 4, n_heel_blocks: 0,
      n_members: 7`.

   b. **REBUILD energy heel** — `frame_roof` with the same `level_name` and ONLY
      `heel_height_in=16`. Expect `created: false`, `config.pitch: "6/12"`
      (preserved), `config.heel_height_in: 16.0`, each `trusses_framed` entry
      `n_heel_blocks: 2, n_members: 9`. Confirms omit-preserves on REBUILD.

   c. **REBUILD Monopoly** — `frame_roof`, same Level, ONLY `eave_overhang_in=0`.
      Expect `created: false`, `config.eave_overhang_in: 0.0`,
      `config.heel_height_in: 16.0` (heel from (b) preserved — cumulative
      omit-preserves).

   d. **REBUILD custom pitch** — `frame_roof`, same Level, `pitch="CUSTOM"`,
      `pitch_rise_in=7.5`. Expect `config.pitch: "CUSTOM"`,
      `config.pitch_rise_in: 7.5`.

   e. **CREATE bad bearing wall** — on a FRESH test Level, `frame_roof` with
      `bearing_wall_a_name` = a non-wall (e.g. the Building Empty) or a wall
      from a different Level. Expect INVALID_PARAMS from `_resolve_wall_in_level`,
      and NO Roof created (the error fires in `_parse_roof_config` before the
      `add_roof` operator runs).

   f. **CREATE validate negative** — on a fresh test Level, `frame_roof` with NO
      bearing-wall params. Expect INVALID_PARAMS with the verbatim `"Roof: ..."`
      bearing-wall message. Then re-call `frame_roof` on the SAME Level WITH
      good bearing walls and confirm `created: true` — proving the failed
      CREATE left no stranded Roof (atomicity).

   g. **Parity spot-check** — confirm the trusses created via the bridge match
      what the Roof Framing panel produces for the same config (same count,
      same member counts, same span/peak).

Report results in the standard audit format. Items 9a–9g are the runtime proof
(a paste of the relevant JSON-RPC responses is the expected evidence); 1–8 are
static.

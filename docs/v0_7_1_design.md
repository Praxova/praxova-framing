# Praxova Framing v0.7.1 Design — Roof / Truss Bridge Parity

## Overview

v0.7.1 brings the MCP bridge to parity with v0.7.0's roof framing. A single new
JSON-RPC method — `frame_roof` — lets an external LLM create, configure, and
generate a Roof's trusses through the same single-source-of-truth validator the
UI uses. `frame_roof` follows the **exact `frame_wall` pattern**: two modes
(CREATE / REBUILD) picked automatically, with omit-preserves semantics on
REBUILD. The FastMCP layer gains one typed tool wrapper, the method count goes
18 → 19, and the truss smoke steps that were impossible in v0.7.0 (no bridge
surface for roofs) become writable end-to-end.

This is a standard bridge-parity sub-cycle: UI/operator shipped in v0.7.0,
bridge parity in v0.7.1, matching the cadence of v0.5.1 / v0.6.1 / v0.6.41 /
v0.6.51 / v0.6.61. No operator, geometry, data-model, or cut-list behavior
changes — v0.7.1 is bridge + smoke + version + docs only.

### Why one method (and why it mirrors `frame_wall`)

The wall bridge surface has no `add_wall` — `frame_wall` does everything:

- **CREATE** (`wall_target` omitted) → build a new wall from the passed spec.
- **REBUILD** (`wall_target` set) → re-frame that wall in place; the Empty is
  preserved, children deleted and rebuilt, and **every config field omitted
  preserves the existing value** (partial update).

So a wall is reconfigured by calling `frame_wall` again with the changed
fields; there is no `remove_wall` and no separate configure step. `frame_roof`
adopts the identical model. The only structural difference: a Level holds at
most one Roof, so the **Level itself is the discriminator** — no `roof_target`
param is needed. If the Level has no Roof, `frame_roof` is CREATE; if it has
one, `frame_roof` is REBUILD. This is cleaner than walls (where multiple walls
per Level force an explicit `wall_target`), and it means reconfiguration,
replacement, and "destroy and start over" all collapse into "call `frame_roof`
again," exactly as with walls.

The `add_roof` **operator** still exists (the UI's two-step "Add Roof → fill the
panel → Frame Roof" flow needs it); `frame_roof`'s CREATE mode invokes that
operator internally to create the Empty. The bridge simply doesn't expose
`add_roof` as a standalone method — the same way the bridge exposes `frame_wall`
with no separate wall-creation method.

**Cycle plan (4 commits):**
- **Commit 1**: `server/handlers.py` — the `frame_roof` handler (CREATE /
  REBUILD), `_parse_roof_config` helper + config write/snapshot/restore
  helpers + pitch-map constants, METHODS registry 18 → 19.
- **Commit 2**: `mcp_server/praxova_framing_mcp/server.py` — the `frame_roof`
  FastMCP typed tool wrapper + package version 0.6.61 → 0.7.1.
- **Commit 3**: `smoke_test.py` — new truss steps (CREATE + REBUILD now
  reachable via the bridge), `method_count` 18 → 19. `addon_version` assertion
  stays pinned at `"0.7.0"` (the bridge reports the add-on `__version__`, which
  doesn't move until Commit 4 — they're coupled).
- **Commit 4**: end-of-cycle — `blender_manifest.toml` + `__init__.py` version
  → 0.7.1, the smoke test's `addon_version` assertion 0.7.0 → 0.7.1 (coupled to
  the `__version__` bump — moves in the same commit), CHANGELOG, README.

**Where this sits on the broader roadmap:**
- v0.7.0 ✅ — Fink truss, site-built, operator/UI/cut-list
- **v0.7.1 (this cycle)** — roof/truss bridge parity
- v0.7.50 — more truss types (king-post, queen-post, scissor, attic, mono-
  pitch) + multi-piece chords for spans > 16'
- v0.7.51 — bridge parity for v0.7.50
- v0.7.60 — gable-end trusses + rake walls
- v0.7.61 — bridge parity
- v0.7.70 — Gambrel
- v0.7.71 — bridge parity

## Architectural Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Number of RPC methods | One: `frame_roof` (method count 18 → 19) | Mirrors `frame_wall`, which carries the full spec and does CREATE-or-REBUILD with no separate `add_wall`. The config rides on the geometry-building call |
| CREATE / REBUILD discriminator | Implicit: whether the Level already has a Roof | A Level holds one Roof, so `level_name` uniquely identifies it — no `roof_target` param needed (unlike `frame_wall`, where multiple walls force an explicit `wall_target`) |
| Omit-preserves on REBUILD | Omitted fields preserve current `PraxovaRoofProps` values; only explicitly-passed fields are written | Exact `frame_wall` REBUILD behavior ("omit = preserve current"). Reconfigure = `frame_roof` with just the changed field |
| Defaults on CREATE | Omitted fields take the `PraxovaRoofProps` defaults (the freshly-created Empty already carries them) | Exact `frame_wall` CREATE behavior ("omit = CREATE default"). Falls out naturally — the handler writes only provided fields onto a default-initialized Roof |
| Reconfigure / remove | No `configure_roof`, no `remove_roof` RPC | `frame_roof` REBUILD handles reconfiguration and replacement; "destroy" has no current caller. Mirrors walls (no `remove_wall`). Consistency over surface area |
| `add_roof` on the bridge | Not exposed as a method; the `add_roof` operator is invoked internally by `frame_roof` CREATE | The bridge has no `add_wall` either. The UI keeps its `add_roof` operator for the two-step panel flow |
| CREATE-mode atomicity | On geometric-validation failure, delete the just-created Roof Empty and raise | CREATE either yields a framed Roof or no Roof — no stranded empty container |
| REBUILD-mode atomicity | Snapshot config before writing; on validation failure, restore the snapshot and raise | Failed REBUILD leaves the Roof exactly as it was (config and geometry), matching `frame_wall`'s "validation failure → wall unchanged" |
| `frame_roof` response shape | Roof-wide geometry fields + a literal `trusses_framed` list (one entry per truss, parallel to `frame_building`'s `walls_framed`) + `created` bool + full `config` echo | Consistency with the existing orchestrator response. An LLM that reads `walls_framed` reads `trusses_framed` identically; `created` parallels `frame_wall`'s `wall_target_used` |
| Per-truss entry fields | Object-name-prefix counts: `n_top_chords`, `n_bottom_chords`, `n_webs`, `n_heel_blocks`, `n_members` | Same `startswith`-counting pattern `frame_building` uses; counts the actual post-op scene state, tolerant of `.001` suffixes |
| Validation surfacing | `frame_roof` pre-flights `templates.validate_roof` (after writing config) and raises `RPCError(INVALID_PARAMS, msg)` with the verbatim `"Roof: ..."` message | Single source of truth — bridge, UI live indicator, and operator surface identical text. Pre-flight gives the precise message rather than a generic CANCELLED |
| Bearing-wall name resolution | Reuse `_resolve_wall_in_level(name, level, field)` | Already enforces the bearing-wall constraint (Praxova wall parented under this Level). Wire fields `bearing_wall_a_name` / `bearing_wall_b_name` follow the `wall_a_name` convention |
| Pitch on the wire | Accept carpenter strings (`"3/12"` … `"12/12"`, `"CUSTOM"`); map to the `P_N_12` enum key in `_parse_roof_config` | `P_6_12` keys are ugly to expose. The FastMCP `Literal` advertises the friendly forms; the trivial map lives in one place |
| `mcp_server` package version | 0.6.61 → 0.7.1 | Tracks the bridge surface. v0.7.0 left it at 0.6.61 (no bridge changes that cycle) |
| `__version__` / manifest | 0.7.0 → 0.7.1 | Standard cycle bump |
| Smoke `method_count` | 18 → 19 | One new RPC |

## RPC Method — `frame_roof`

### Wire format (params)

```
level_name (str, REQUIRED)
    Name of the Praxova Level Empty whose Roof to create+frame (CREATE)
    or reconfigure+reframe (REBUILD). Resolved via _resolve_level.

name (str, OPTIONAL — CREATE only)
    Override the auto-generated Roof_NN name when creating. Must not
    collide with any existing scene object. Ignored in REBUILD mode (the
    Roof already has a name; renaming via this path is out of scope).

bearing_wall_a_name (str, OPTIONAL)
bearing_wall_b_name (str, OPTIONAL)
    Object names of the two parallel bearing walls, resolved via
    _resolve_wall_in_level against `level_name`. CREATE: omitted leaves
    them unset, which fails validate_roof ("bearing walls must be set") —
    so in practice CREATE supplies both. REBUILD: omitted preserves the
    current bearing walls; supply one or both to change them.

truss_type (str, OPTIONAL)
    Only "FINK" in v0.7.0/.1. CREATE default "FINK"; REBUILD omit =
    preserve. Single-value Literal; the handler validates so v0.7.50
    additions surface cleanly.

pitch (str, OPTIONAL)
    Carpenter string: "3/12", "4/12", "5/12", "6/12", "7/12", "8/12",
    "9/12", "10/12", "12/12", or "CUSTOM". Mapped to the P_N_12 / CUSTOM
    enum key in _parse_roof_config. CREATE default "6/12"; REBUILD omit =
    preserve.

pitch_rise_in (number, OPTIONAL)
    Rise in inches per 12" run; used only when the effective pitch is
    "CUSTOM". Range 1.0–24.0. CREATE default 6.0; REBUILD omit = preserve.

eave_overhang_in (number, OPTIONAL)
    Top-chord projection past the bearing wall's exterior face. 0 =
    Monopoly-style flush eave. Range 0.0–48.0. CREATE default 12.0;
    REBUILD omit = preserve.

heel_height_in (number, OPTIONAL)
    Heel block height. 0 = standard heel; >0 = energy heel. Range
    0.0–24.0. CREATE default 0.0; REBUILD omit = preserve.

top_chord_nominal (str, OPTIONAL)
bottom_chord_nominal (str, OPTIONAL)
web_nominal (str, OPTIONAL)
    Dimensional lumber nominals, validated against the LUMBER_TYPES keys
    (same set add_lumber accepts). CREATE defaults 2x6 / 2x6 / 2x4;
    REBUILD omit = preserve.

oc_spacing_in (str, OPTIONAL)
    On-center truss spacing. One of "12", "16", "19.2", "24" (the
    EnumProperty keys — already friendly, no mapping). CREATE default
    "24"; REBUILD omit = preserve.
```

**Omit-preserves note.** The handler writes only the fields explicitly present
in `params`. On CREATE the Roof is freshly created with `PraxovaRoofProps`
defaults, so omitted fields naturally read as the CREATE defaults above. On
REBUILD the existing Roof carries its current values, so omitted fields are
preserved. This dual behavior falls out of "write only what was passed" — no
mode-specific default logic is required (see `_parse_roof_config`).

### Behavior

```
1.  level = _resolve_level(level_name)
2.  existing = _roof_in_level(level)         # None => CREATE, else REBUILD
3.  created = existing is None
4.  parsed = _parse_roof_config(params, level)
        # validates ranges/choices, resolves bearing-wall names to Object
        # refs, maps pitch string -> enum key. Returns ONLY the fields
        # explicitly present in params (plus their normalized values).
        # Param-level errors (bad pitch string, out-of-range heel,
        # non-wall bearing wall, wall in wrong Level) raise here, BEFORE
        # any scene mutation.

    # ---- CREATE ----
5a. if created:
        if "name" in params and params["name"] in bpy.data.objects:
            raise INVALID_PARAMS (name collision)
        sp.active_level = level
        bpy.ops.praxova.add_roof('EXEC_DEFAULT'); _check_op_result(...)
        roof = _roof_in_level(level)
        if roof is None: raise INTERNAL_ERROR
        if "name" in params: roof.name = params["name"]
        _write_roof_config(roof.praxova_roof, parsed)     # provided fields
        ok, msg = templates.validate_roof(roof.praxova_roof, level)
        if not ok:
            bpy.data.objects.remove(roof, do_unlink=True)
            # roof has no children yet (frame_roof hasn't run) — a plain
            # remove is enough; no recursive delete needed here.
            raise INVALID_PARAMS(msg)

    # ---- REBUILD ----
5b. else:
        roof = existing
        snapshot = _snapshot_roof_config(roof.praxova_roof)   # all fields
        _write_roof_config(roof.praxova_roof, parsed)         # provided fields
        ok, msg = templates.validate_roof(roof.praxova_roof, level)
        if not ok:
            _restore_roof_config(roof.praxova_roof, snapshot)
            raise INVALID_PARAMS(msg)

6.  sp.active_level = level
7.  bpy.ops.praxova.frame_roof('EXEC_DEFAULT'); _check_op_result(...)
8.  trusses = [c for c in roof.children if c.praxova_truss.is_truss]
9.  layout = templates.compute_truss_layout(roof.praxova_roof)   # read-only
10. return response (roof-wide geometry + trusses_framed + created + config)
```

`_write_roof_config(rp, parsed)`, `_snapshot_roof_config(rp)`, and
`_restore_roof_config(rp, snapshot)` are small handler-local helpers (see
below). The snapshot/restore pair gives REBUILD its "validation failure leaves
the Roof unchanged" guarantee; the CREATE delete gives CREATE its atomicity.

### Returns

```
roof_name (str)           — name of the Roof Empty (new or existing)
level_name (str)          — echo
created (bool)            — True if a new Roof was created (CREATE),
                            False if an existing one was reframed (REBUILD).
                            Parallels frame_wall's wall_target_used.
truss_count (int)         — number of trusses framed (len of post-op refetch)
span_in (float)           — computed exterior-face-to-exterior-face span
pitch (str)               — resolved carpenter string (e.g. "6/12")
peak_height_in (float)    — peak height above cap plate (incl. heel)
bearing_wall_a_name (str) — resolved bearing wall A name (or null if unset)
bearing_wall_b_name (str) — resolved bearing wall B name (or null if unset)
config (dict)             — full EFFECTIVE config after the write, defaults +
                            preserved values made explicit:
    truss_type, bearing_wall_a_name, bearing_wall_b_name, pitch
    (carpenter string), pitch_rise_in, eave_overhang_in, heel_height_in,
    top_chord_nominal, bottom_chord_nominal, web_nominal, oc_spacing_in
trusses_framed (list)     — one entry per truss, parallel to
                            frame_building.walls_framed:
    truss_name (str)         — Object name (Truss_NN)
    n_top_chords (int)       — 2 for Fink (Object-name prefix count)
    n_bottom_chords (int)    — 1
    n_webs (int)             — 4 for Fink
    n_heel_blocks (int)      — 0 (standard heel) or 2 (energy heel)
    n_members (int)          — total (7 or 9 for Fink)
```

The `config` echo reflects the **effective** config (what's on the Roof after
the write), so a REBUILD that passed only `heel_height_in=16` returns the full
config with the preserved `pitch`, nominals, etc. made explicit — the LLM sees
exactly what the Roof now is. `config.pitch` and the top-level `pitch` are the
carpenter string (round-tripped from the enum key via `_PITCH_KEY_TO_STR`).
`span_in` / `peak_height_in` come from the single `compute_truss_layout(rp)`
read in step 9 (the canonical layout), not recomputed from the scene.

### Per-truss count derivation

Object-name-prefix counting under each Truss Empty, matching `frame_building`:

```python
n_top_chords = sum(
    1 for c in truss.children
    if c.name.startswith(f"{truss.name}_TopChord_")
)
n_bottom_chords = sum(
    1 for c in truss.children
    if c.name.startswith(f"{truss.name}_BottomChord")
)
n_webs = sum(
    1 for c in truss.children
    if c.name.startswith(f"{truss.name}_Web_")
)
n_heel_blocks = sum(
    1 for c in truss.children
    if c.name.startswith(f"{truss.name}_HeelBlock_")
)
n_members = n_top_chords + n_bottom_chords + n_webs + n_heel_blocks
```

The `{truss.name}_` prefix scopes the count to that truss's own members (member
names are `Truss_NN_TopChord_L` etc. from v0.7.0 Commit 3). `.001`-suffix
tolerance comes free from `startswith` on the role substring.

## Helper — `_parse_roof_config(params, level)`

Mirrors `_parse_joint` structurally, but returns **only the fields explicitly
present in `params`** (the omit-preserves contract — the handler writes exactly
these and leaves the rest alone). Validates ranges/choices, resolves
bearing-wall names to Object refs, maps the pitch string to the enum key.

```python
def _parse_roof_config(params: dict, level: bpy.types.Object) -> dict:
    """Validate + normalize the roof design params present in `params`.

    Returns a dict containing ONLY the keys explicitly supplied by the
    caller, each normalized to its PraxovaRoofProps storage form (pitch
    as the P_N_12 / CUSTOM enum key under 'pitch_key'; bearing walls as
    resolved Object refs under 'wall_a' / 'wall_b'). Omitted params are
    absent from the result — the handler writes only what's present, which
    yields CREATE-defaults on a fresh Roof and preserve-on-omit on REBUILD
    with no mode-specific branching here.

    Param-level errors (unknown pitch string, out-of-range number,
    non-wall or wrong-Level bearing wall, bad nominal/oc value) raise
    RPCError(INVALID_PARAMS, ...) with the same shapes the rest of the
    bridge uses, BEFORE the caller mutates any scene state.

    'present' is tested with `key in params` so that a legitimately-zero
    numeric (e.g. heel_height_in=0, eave_overhang_in=0) is distinguished
    from an omitted field. Reject bool for numeric fields (Python bool is
    an int subclass — same guard add_level uses for level_height_in).
    """
    out: dict = {}

    if "truss_type" in params:
        out["truss_type"] = _require(
            params, "truss_type", str, choices=("FINK",),
        )

    if "bearing_wall_a_name" in params:
        a_name = _require(params, "bearing_wall_a_name", str)
        out["wall_a"] = _resolve_wall_in_level(
            a_name, level, "bearing_wall_a_name",
        )
        out["wall_a_name"] = a_name
    if "bearing_wall_b_name" in params:
        b_name = _require(params, "bearing_wall_b_name", str)
        out["wall_b"] = _resolve_wall_in_level(
            b_name, level, "bearing_wall_b_name",
        )
        out["wall_b_name"] = b_name

    if "pitch" in params:
        pitch_str = _require(
            params, "pitch", str, choices=_PITCH_WIRE_CHOICES,
        )
        out["pitch_key"] = _PITCH_STR_TO_KEY[pitch_str]

    if "pitch_rise_in" in params:
        v = _require(params, "pitch_rise_in", (int, float))
        _reject_bool_and_range(v, 1.0, 24.0, "pitch_rise_in")
        out["pitch_rise_in"] = float(v)

    if "eave_overhang_in" in params:
        v = _require(params, "eave_overhang_in", (int, float))
        _reject_bool_and_range(v, 0.0, 48.0, "eave_overhang_in")
        out["eave_overhang_in"] = float(v)

    if "heel_height_in" in params:
        v = _require(params, "heel_height_in", (int, float))
        _reject_bool_and_range(v, 0.0, 24.0, "heel_height_in")
        out["heel_height_in"] = float(v)

    for key in ("top_chord_nominal", "bottom_chord_nominal", "web_nominal"):
        if key in params:
            out[key] = _require(params, key, str, choices=_NOMINAL_CHOICES)

    if "oc_spacing_in" in params:
        out["oc_spacing_in"] = _require(
            params, "oc_spacing_in", str,
            choices=("12", "16", "19.2", "24"),
        )

    return out
```

`_require(params, key, type, *, choices=...)` already exists and raises
INVALID_PARAMS on type/choice violations — reuse it (here every field is known
present, so `_require` not `_optional`). `_reject_bool_and_range` is a tiny
handler-local guard if no equivalent exists (check `handlers.py`; `add_level`'s
`isinstance(x, bool) or x <= 0` is the inline precedent — either factor a small
helper or inline the three checks to match the file's idiom).

Supporting module-level constants near the other choice tuples in `handlers.py`:

```python
_PITCH_STR_TO_KEY = {
    "3/12": "P_3_12", "4/12": "P_4_12", "5/12": "P_5_12",
    "6/12": "P_6_12", "7/12": "P_7_12", "8/12": "P_8_12",
    "9/12": "P_9_12", "10/12": "P_10_12", "12/12": "P_12_12",
    "CUSTOM": "CUSTOM",
}
_PITCH_KEY_TO_STR = {v: k for k, v in _PITCH_STR_TO_KEY.items()}
_PITCH_WIRE_CHOICES = tuple(_PITCH_STR_TO_KEY.keys())
# _NOMINAL_CHOICES: reuse whatever constant add_lumber's nominal validation
# already references (derived from templates.LUMBER_TYPES keys); don't
# redefine the nominal set.
```

### Config write / snapshot / restore helpers

```python
# Maps parsed-dict keys to PraxovaRoofProps attribute names. pitch_key
# writes to the `pitch` enum; wall_a / wall_b write the PointerProperties.
def _write_roof_config(rp, parsed: dict) -> None:
    if "truss_type" in parsed:           rp.truss_type = parsed["truss_type"]
    if "wall_a" in parsed:               rp.bearing_wall_a = parsed["wall_a"]
    if "wall_b" in parsed:               rp.bearing_wall_b = parsed["wall_b"]
    if "pitch_key" in parsed:            rp.pitch = parsed["pitch_key"]
    if "pitch_rise_in" in parsed:        rp.pitch_rise_in = parsed["pitch_rise_in"]
    if "eave_overhang_in" in parsed:     rp.eave_overhang_in = parsed["eave_overhang_in"]
    if "heel_height_in" in parsed:       rp.heel_height_in = parsed["heel_height_in"]
    if "top_chord_nominal" in parsed:    rp.top_chord_nominal = parsed["top_chord_nominal"]
    if "bottom_chord_nominal" in parsed: rp.bottom_chord_nominal = parsed["bottom_chord_nominal"]
    if "web_nominal" in parsed:          rp.web_nominal = parsed["web_nominal"]
    if "oc_spacing_in" in parsed:        rp.oc_spacing_in = parsed["oc_spacing_in"]


def _snapshot_roof_config(rp) -> dict:
    """Capture all design fields for REBUILD rollback. PointerProperties
    captured as direct Object refs (restorable by assignment)."""
    return {
        "truss_type": rp.truss_type,
        "bearing_wall_a": rp.bearing_wall_a,
        "bearing_wall_b": rp.bearing_wall_b,
        "pitch": rp.pitch,
        "pitch_rise_in": rp.pitch_rise_in,
        "eave_overhang_in": rp.eave_overhang_in,
        "heel_height_in": rp.heel_height_in,
        "top_chord_nominal": rp.top_chord_nominal,
        "bottom_chord_nominal": rp.bottom_chord_nominal,
        "web_nominal": rp.web_nominal,
        "oc_spacing_in": rp.oc_spacing_in,
    }


def _restore_roof_config(rp, snap: dict) -> None:
    rp.truss_type = snap["truss_type"]
    rp.bearing_wall_a = snap["bearing_wall_a"]
    rp.bearing_wall_b = snap["bearing_wall_b"]
    rp.pitch = snap["pitch"]
    rp.pitch_rise_in = snap["pitch_rise_in"]
    rp.eave_overhang_in = snap["eave_overhang_in"]
    rp.heel_height_in = snap["heel_height_in"]
    rp.top_chord_nominal = snap["top_chord_nominal"]
    rp.bottom_chord_nominal = snap["bottom_chord_nominal"]
    rp.web_nominal = snap["web_nominal"]
    rp.oc_spacing_in = snap["oc_spacing_in"]
```

### Response config-echo builder

A small helper reads the effective config off the Roof for the response's
`config` field and the top-level echoes (mapping the `pitch` enum key back to
the carpenter string via `_PITCH_KEY_TO_STR`, and bearing-wall refs back to
names, or `None` when unset):

```python
def _roof_config_to_wire(rp) -> dict:
    return {
        "truss_type": rp.truss_type,
        "bearing_wall_a_name": rp.bearing_wall_a.name if rp.bearing_wall_a else None,
        "bearing_wall_b_name": rp.bearing_wall_b.name if rp.bearing_wall_b else None,
        "pitch": _PITCH_KEY_TO_STR[rp.pitch],
        "pitch_rise_in": rp.pitch_rise_in,
        "eave_overhang_in": rp.eave_overhang_in,
        "heel_height_in": rp.heel_height_in,
        "top_chord_nominal": rp.top_chord_nominal,
        "bottom_chord_nominal": rp.bottom_chord_nominal,
        "web_nominal": rp.web_nominal,
        "oc_spacing_in": rp.oc_spacing_in,
    }
```

## METHODS registry

Add the one handler to the `METHODS` dict at the bottom of `handlers.py`,
grouped with a `# v0.7.1: roof / truss bridge parity` comment, after
`frame_building` (keeping the framing orchestrators together):

```python
    "frame_building": frame_building,
    # v0.7.1: roof / truss bridge parity (CREATE/REBUILD, mirrors frame_wall).
    "frame_roof": frame_roof,
    "generate_cutlist": generate_cutlist,
    "set_imperial_units": set_imperial_units,
```

`method_count` (reported by `ping` via `len(METHODS)`) goes 18 → 19
automatically.

## FastMCP Tool Wrapper (Commit 2)

One `@mcp.tool()` function in `mcp_server/praxova_framing_mcp/server.py`,
modeled on `frame_wall` (the natural template — same CREATE/REBUILD framing)
and `frame_building`. Typed signature with `Literal` for the enum params;
thorough docstring.

```python
@mcp.tool()
def frame_roof(
    level_name: str,
    name: str | None = None,
    bearing_wall_a_name: str | None = None,
    bearing_wall_b_name: str | None = None,
    truss_type: Literal["FINK"] = "FINK",
    pitch: Literal[
        "3/12", "4/12", "5/12", "6/12", "7/12",
        "8/12", "9/12", "10/12", "12/12", "CUSTOM",
    ] = "6/12",
    pitch_rise_in: float = 6.0,
    eave_overhang_in: float = 12.0,
    heel_height_in: float = 0.0,
    top_chord_nominal: str = "2x6",
    bottom_chord_nominal: str = "2x6",
    web_nominal: str = "2x4",
    oc_spacing_in: Literal["12", "16", "19.2", "24"] = "24",
) -> dict:
    """Create-and-frame or reconfigure-and-reframe a Level's Roof.

    Two modes, picked automatically by whether the Level already has a
    Roof (one Roof per Level) — the same CREATE/REBUILD model as
    frame_wall:

      CREATE (the Level has no Roof yet): a new Roof is created under the
        Level and framed. Supply both bearing walls (two parallel,
        equal-length, equal-height walls under this Level) plus any design
        params; omitted params take their defaults (Fink, 6/12, 12" eave,
        0 heel, 2x6 chords, 2x4 web, 24" OC).

      REBUILD (the Level already has a Roof): the existing Roof is
        reconfigured with whatever params you pass and reframed in place.
        Omitted params PRESERVE the Roof's current values — so to change
        just the heel, call frame_roof(level_name=..., heel_height_in=16)
        and everything else is kept. This is how you reconfigure or
        replace a roof; there is no separate remove step (mirrors how
        frame_wall rebuilds a wall in place).

    ... (rest of docstring: the v0.7.0 Fink/site-built model; pitch is the
    carpenter string, CUSTOM uses pitch_rise_in; Monopoly eave via
    eave_overhang_in=0; energy heel via heel_height_in>0; convention-
    agnostic bearing walls (eave- or gable-bearing). The validate_roof
    errors the caller may see: bearing walls unset / not parallel /
    different heights / span over the single-piece bottom-chord limit
    (16'). The response: created bool, roof-wide geometry, the config
    echo (full effective config incl. preserved fields), and the
    trusses_framed list parallel to frame_building's walls_framed.) ...

    Args:
        level_name: Name of the Praxova Level Empty. CREATE makes the
            Roof here; REBUILD finds the existing one here.
        name: CREATE-only override for the auto Roof_NN name. Ignored on
            REBUILD.
        bearing_wall_a_name, bearing_wall_b_name: Object names of the two
            parallel bearing walls (Praxova walls under this Level).
            Required in practice for CREATE (validate_roof rejects unset);
            on REBUILD, omit to keep the current pair.
        truss_type: "FINK" (only value in v0.7.x).
        pitch: Carpenter rise/run string, or "CUSTOM" (then pitch_rise_in
            applies).
        pitch_rise_in: Rise per 12" run when pitch is "CUSTOM" (1–24).
        eave_overhang_in: Eave projection; 0 = flush/Monopoly (0–48).
        heel_height_in: Heel block height; 0 = standard, >0 = energy heel
            (0–24).
        top_chord_nominal, bottom_chord_nominal, web_nominal: Lumber
            nominals.
        oc_spacing_in: Truss on-center spacing.

    Returns:
        roof_name, level_name, created (bool), truss_count, span_in,
        pitch, peak_height_in, bearing_wall_a_name, bearing_wall_b_name,
        config (full effective config), trusses_framed (per-truss list).
    """
    params: dict = {
        "level_name": level_name,
        "truss_type": truss_type,
        "pitch": pitch,
        "pitch_rise_in": pitch_rise_in,
        "eave_overhang_in": eave_overhang_in,
        "heel_height_in": heel_height_in,
        "top_chord_nominal": top_chord_nominal,
        "bottom_chord_nominal": bottom_chord_nominal,
        "web_nominal": web_nominal,
        "oc_spacing_in": oc_spacing_in,
    }
    if name is not None:
        params["name"] = name
    if bearing_wall_a_name is not None:
        params["bearing_wall_a_name"] = bearing_wall_a_name
    if bearing_wall_b_name is not None:
        params["bearing_wall_b_name"] = bearing_wall_b_name
    return _call("frame_roof", params)
```

> **Omit-preserves caveat for the FastMCP layer.** The typed wrapper has
> non-None defaults for the design params (`pitch="6/12"`, etc.), so it always
> forwards them — meaning a REBUILD through the FastMCP tool re-asserts those
> defaults rather than preserving prior values for params the caller left at
> their default. The handler's omit-preserves still fully applies to the
> truly-optional `name` / `bearing_wall_*` params (sent only when not None),
> and applies to ALL params for a raw JSON-RPC caller. **Match `frame_wall`'s
> FastMCP wrapper convention exactly** — check how it handles scalar
> preserve-on-omit (typed defaults always sent, vs `None` sentinels forwarding
> only non-None) and mirror it for `frame_roof`, documenting the same nuance in
> the docstring. This is the one place to verify against the wall precedent
> rather than assume.

### FastMCP docstring / version updates beyond the new tool

- Module-level docstring: if it enumerates the tool surface or method count,
  bump the count and add roof/truss to the capability summary.
- `mcp_server` package/distribution version (in `pyproject.toml` and/or the
  package `__init__`): 0.6.61 → 0.7.1. The separate MCP-protocol `__version__`
  (currently "0.3.0") does NOT change — only the package version bumps
  (confirmed distinct in v0.7.0's audit).

## Smoke Test (Commit 3)

`smoke_test.py` is the external RPC client. With the roof surface now exposed,
the truss steps deferred from v0.7.0 become writable, and the CREATE/REBUILD
model means a single Roof can be exercised through several reconfigurations —
mirroring the existing `frame_wall` REBUILD steps in the suite.

### Version assertions

- `addon_version`: **stays pinned at `"0.7.0"`** in Commit 3. The bridge's
  `addon_version` comes from the add-on package `__version__`
  (`server/handlers.py` does `from .. import __version__`), which doesn't move
  until Commit 4 bumps `__init__.py` + `blender_manifest.toml`. Commit 2's
  `mcp_server` package bump is a separate version the bridge never reports. So
  the smoke assertion must match the still-0.7.0 add-on here, and moves to
  "0.7.1" atomically with the `__version__` bump in Commit 4.
- `method_count`: `18` → `19` (assertion + message).
- Module docstring "Covers the full v0.7.0 RPC surface (18 methods ...)" →
  "v0.7.1 ... (19 methods ...)".
- One new history-comment line in the running block (note the `addon_version`
  bump is flagged as deferred to Commit 4, since it can't move until the add-on
  `__version__` does — Commit 4 finalizes this wording to past tense):
  ```
  # v0.7.1 (in progress): method_count 18 -> 19 (frame_roof, a single
  # CREATE/REBUILD method mirroring frame_wall). addon_version STAYS
  # 0.7.0 here — the bridge reports the add-on __version__, which bumps
  # to 0.7.1 atomically with __init__.py + the manifest in Commit 4.
  # New steps exercise frame_roof CREATE (full config + carpenter-string
  # pitch mapping), REBUILD omit-preserves reconfigure (heel + eave +
  # pitch changed one at a time, created=False, prior fields preserved),
  # the validate_roof negatives (unset bearing walls, bad bearing-wall
  # pick — with CREATE rollback verified), and the A-suffix / cut-angle
  # annotations in generate_cutlist now that trusses are bridge-reachable.
  ```

### New smoke steps (sketch)

Build on a rectangle the smoke test frames (or a dedicated `Roof_Test_*`
Level). All scene content comes through the bridge — the bearing walls must be
two parallel, equal-length, equal-height walls from `frame_wall` calls.

1. **`frame_roof` CREATE happy path** — on a test Level with a rectangle, call
   `frame_roof` with both bearing walls (the two parallel walls), 6/12, 12"
   eave, 0 heel, default nominals, 24" OC. Assert: `created is True`,
   `roof_name` present, `truss_count` (9 for a 16' bearing-wall length at 24"
   OC), `span_in ≈ 144.0`, `pitch == "6/12"`, `config.pitch == "6/12"`,
   bearing-wall names echoed, `len(trusses_framed) == truss_count`, each entry
   `n_top_chords == 2`, `n_bottom_chords == 1`, `n_webs == 4`,
   `n_heel_blocks == 0`, `n_members == 7`.
2. **`frame_roof` REBUILD energy heel** — call `frame_roof` on the SAME Level
   passing only `heel_height_in=16`. Assert: `created is False`,
   `config.pitch == "6/12"` (preserved), `config.heel_height_in == 16.0`, each
   `trusses_framed` entry now `n_heel_blocks == 2`, `n_members == 9`. This is
   the omit-preserves REBUILD that the single-method design enables — no second
   Level needed (the v0.7.1-design improvement over the two-method draft).
3. **`frame_roof` REBUILD Monopoly eave** — same Level, only `eave_overhang_in=0`.
   Assert `created is False`, `config.eave_overhang_in == 0.0`,
   `config.heel_height_in == 16.0` (the heel from step 2 is preserved — proves
   cumulative omit-preserves).
4. **`frame_roof` REBUILD custom pitch round-trip** — same Level,
   `pitch="CUSTOM"`, `pitch_rise_in=7.5`. Assert `created is False`,
   `config.pitch == "CUSTOM"`, `config.pitch_rise_in == 7.5`.
5. **`frame_roof` CREATE bad bearing wall** — on a FRESH test Level, call
   `frame_roof` with `bearing_wall_a_name` naming a non-wall or out-of-Level
   Object. Assert INVALID_PARAMS from `_resolve_wall_in_level`. (No Roof should
   be created — the error fires in `_parse_roof_config` before the add_roof
   operator runs.)
6. **`frame_roof` CREATE validate negative (unset bearing walls)** — on a fresh
   test Level, call `frame_roof` with NO bearing-wall params. Assert
   INVALID_PARAMS with the verbatim `"Roof: ..."` bearing-wall message. Per the
   CREATE-atomicity rule, the just-created Roof Empty is deleted on this
   failure — optionally assert (by re-calling `frame_roof` with good walls on
   the same Level and checking `created is True`) that no stranded Roof remains.
7. **Cut-list integration** — after a successful frame (step 1's roof, or any),
   call `generate_cutlist`; assert the `text` contains an `A`-suffixed lumber
   label and a cut-angle annotation (the degree sign, or a known angle
   substring like the 6/12 top chord's `26.6`). The truss cut-list assertion
   that couldn't exist in v0.7.0.

Step count grows by ~7. Each new step prints its `[NN]` header in the existing
style and asserts with descriptive messages.

## Version + Docs (Commit 4)

- `blender_manifest.toml`: `0.7.0` → `0.7.1`.
- `__init__.py` (add-on root): `__version__ = "0.7.1"`.
- `smoke_test.py`: the `addon_version` assertion `"0.7.0"` → `"0.7.1"` (coupled
  to the `__version__` bump — the bridge reports the add-on `__version__`, so
  the assertion must move in the same commit that bumps it), and finalize the
  Commit-3 in-progress notes (history comment + module docstring) to past
  tense. `method_count` stays `19` (moved in Commit 3). No new smoke steps.
- `CHANGELOG.md`: new `## [0.7.1]` entry at top. Lead paragraph: roof/truss
  bridge parity via a single `frame_roof` RPC with `frame_wall`-style
  CREATE/REBUILD + omit-preserves, 18 → 19 methods, no operator/geometry/cut-
  list behavior change. `### Added`: the `frame_roof` handler (CREATE/REBUILD
  modes, the wire format, the response shape), `_parse_roof_config` +
  `_write/_snapshot/_restore_roof_config` + `_roof_config_to_wire` + the
  pitch-string map, the FastMCP `frame_roof` tool, the new smoke steps.
  `### Changed`: `mcp_server` pkg 0.6.61 → 0.7.1 (Commit 2), manifest +
  `__version__` bumps, smoke `addon_version` 0.7.0 → 0.7.1 + `method_count`
  18 → 19. `### Bridge`: method count 18 → 19 (the first roof/truss RPC); note
  that reconfiguration is `frame_roof` REBUILD (no `configure_roof` /
  `remove_roof`, mirroring walls).
- `README.md`: flip the "Bridge (vX.Y.Z)" subsection heading to v0.7.1; add a
  paragraph describing the `frame_roof` RPC (CREATE/REBUILD, omit-preserves,
  carpenter-string pitch, validate_roof pre-flight, the `trusses_framed`
  response), explicitly noting reconfiguration is a REBUILD call (same as
  `frame_wall`). Update the roadmap line for v0.7.1 → done.

## End-of-Cycle Validation

1. Pull the v0.7.1 branch; reload the add-on; start the MCP bridge.
2. `python smoke_test.py` against the running bridge → "All checks passed",
   `addon_version "0.7.1"`, `method_count 19`. The new roof/truss steps
   (CREATE happy, REBUILD heel/eave/pitch reconfigure, CREATE negatives,
   cut-list integration) all pass.
3. Manual bridge spot-check (optional): `frame_roof` CREATE on a Level with a
   rectangle, then `frame_roof` REBUILD with a changed field, and confirm the
   `trusses_framed` list, `created` flag, and `config` echo match what the UI
   produces for the same Roof (parity check — bridge-driven and UI-driven
   framing of the same scene yield identical trusses; a REBUILD with a single
   changed field matches editing that one field in the Roof Framing panel and
   clicking Frame Roof).
4. Confirm the FastMCP `frame_roof` tool appears in the MCP client's tool list
   with the `Literal` pitch / OC enums advertised, and round-trips through the
   bridge.

## Out of Scope (deferred)

- **`configure_roof` / `remove_roof`** — not needed: `frame_roof` REBUILD
  reconfigures and replaces in place, and "destroy a Roof" has no current
  caller. Mirrors walls (no `remove_wall`). If a pure-destroy RPC is ever
  wanted, it lands with the multi-roof work (v0.7.50+).
- **Multiple Roofs per Level** on the bridge — follows the operator-side
  multi-roof support (v0.7.50+). Note: the implicit CREATE/REBUILD
  discriminator (one Roof per Level) is what makes the single-method design
  clean; multi-roof would reintroduce an explicit `roof_target` param, exactly
  as walls have `wall_target`.
- **Renaming an existing Roof via `frame_roof`** — `name` is CREATE-only;
  REBUILD ignores it.
- **Truss-type / roof-shape RPCs** beyond Fink — arrive with v0.7.51 (bridge
  parity for v0.7.50's new truss types).
- **Any operator / geometry / data-model / cut-list change** — v0.7.1 is bridge
  + smoke + version + docs only.

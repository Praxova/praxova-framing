"""JSON-RPC method implementations for the Praxova Framing bridge.

Every function in this module is invoked on Blender's main thread (scheduled
by bridge._run_on_main_thread) so they may freely use bpy.* without any
threading concerns.

Each handler accepts a single dict of params and returns a JSON-serialisable
result, or raises bridge.RPCError for client-visible errors. Anything else
that escapes is wrapped as INTERNAL_ERROR by the bridge.

The METHODS dict at the bottom of this module is the canonical RPC surface.
"""

from __future__ import annotations

import math
from typing import Any

import bpy
from mathutils import Vector

from . import bridge
from .. import templates
from .. import __version__
from ..ops_cutlist import TEXT_DATABLOCK_NAME, _disk_path_for_current_blend


# ---------------------------------------------------------------------------
# App-defined error codes (must be in [-32000, -32099])
# ---------------------------------------------------------------------------

APP_NO_ACTIVE_OBJECT = -32001
APP_OBJECT_NOT_FOUND = -32002
APP_EMPTY_CUTLIST = -32003
APP_OPERATOR_FAILED = -32004


# ---------------------------------------------------------------------------
# Param validation helpers
# ---------------------------------------------------------------------------

def _require(params: dict, key: str, type_, *, choices: tuple = ()) -> Any:
    if key not in params:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'Missing required parameter "{key}"',
        )
    val = params[key]
    if not isinstance(val, type_):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'Parameter "{key}" must be {_type_label(type_)}, '
            f'got {type(val).__name__}',
        )
    if choices and val not in choices:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'Parameter "{key}" must be one of {sorted(choices)}, got {val!r}',
        )
    return val


def _optional(params: dict, key: str, type_, default=None,
              *, choices: tuple = ()):
    if key not in params or params[key] is None:
        return default
    val = params[key]
    if not isinstance(val, type_):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'Parameter "{key}" must be {_type_label(type_)}, '
            f'got {type(val).__name__}',
        )
    if choices and val not in choices:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'Parameter "{key}" must be one of {sorted(choices)}, got {val!r}',
        )
    return val


def _type_label(type_) -> str:
    if isinstance(type_, tuple):
        return " or ".join(t.__name__ for t in type_)
    return type_.__name__


def _location_param(params: dict) -> Vector | None:
    """Validate optional 'location_m' = [x, y, z] world-space meters."""
    if "location_m" not in params or params["location_m"] is None:
        return None
    loc = params["location_m"]
    if (not isinstance(loc, (list, tuple))
            or len(loc) != 3
            or not all(isinstance(c, (int, float)) and not isinstance(c, bool)
                       for c in loc)):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            '"location_m" must be a 3-element [x, y, z] list of numbers in meters',
        )
    return Vector((float(loc[0]), float(loc[1]), float(loc[2])))


# ---------------------------------------------------------------------------
# Wall opening param validation (v0.5.1)
# ---------------------------------------------------------------------------

def _opening_number(op_dict: dict, idx: int, field: str, *,
                    required: bool, allow_zero: bool) -> float | None:
    """Pull a numeric field out of one opening dict with consistent error
    messaging. idx is 1-based for client-facing messages. allow_zero=True
    means >= 0 is permitted; False means strictly > 0.
    """
    val = op_dict.get(field)
    if val is None:
        if required:
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'Opening {idx}: missing required "{field}"',
            )
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'Opening {idx}: "{field}" must be a number, '
            f'got {type(val).__name__}',
        )
    if allow_zero:
        if val < 0:
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'Opening {idx}: "{field}" must be >= 0',
            )
    else:
        if val <= 0:
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'Opening {idx}: "{field}" must be > 0',
            )
    return float(val)


def _parse_openings(raw, wall_nominal: str) -> list[dict]:
    """Validate and normalize the wire-format openings list.

    Returns a list of dicts with all defaults filled in and the wire-format
    lowercase "door"/"window" translated to internal 'DOOR'/'WINDOW' for
    PraxovaWallOpening.opening_type. 1-based opening indices in error
    messages match what the UI's live preview shows.

    The cross-field rules (within wall, no overlap, fits under top plates,
    sill clears bottom plate) are NOT checked here — those run after the
    CollectionProperty is populated, via templates.validate_openings, so
    the bridge and the UI share one validator.
    """
    if not isinstance(raw, list):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'"openings" must be a list of opening dicts, '
            f'got {type(raw).__name__}',
        )
    out: list[dict] = []
    for i, op in enumerate(raw, start=1):
        if not isinstance(op, dict):
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f"Opening {i}: must be a dict, got {type(op).__name__}",
            )

        t = op.get("type")
        if not isinstance(t, str) or t not in ("door", "window"):
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'Opening {i}: "type" must be "door" or "window"',
            )

        x_offset_in = _opening_number(
            op, i, "x_offset_in", required=True, allow_zero=True,
        )
        ro_width_in = _opening_number(
            op, i, "ro_width_in", required=True, allow_zero=False,
        )
        ro_height_in = _opening_number(
            op, i, "ro_height_in", required=True, allow_zero=False,
        )

        # sill_height_in is required for windows, optional (default 0)
        # for doors per the design doc — doors sit on the bottom plate.
        if t == "window":
            sill_height_in = _opening_number(
                op, i, "sill_height_in", required=True, allow_zero=True,
            )
        else:
            sh = _opening_number(
                op, i, "sill_height_in", required=False, allow_zero=True,
            )
            sill_height_in = 0.0 if sh is None else sh

        # header_nominal defaults to wall_nominal (the spec's
        # "geometric default, not structural" rule).
        header_nominal = op.get("header_nominal")
        if header_nominal is None:
            header_nominal = wall_nominal
        elif (not isinstance(header_nominal, str)
                or header_nominal not in templates.LUMBER_TYPES):
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'Opening {i}: "header_nominal" must be one of '
                f'{sorted(templates.LUMBER_TYPES)}',
            )

        # jack_count defaults via recommend_jack_count (2 for ≥72" RO).
        jack_count = op.get("jack_count")
        if jack_count is None:
            jack_count = templates.recommend_jack_count(ro_width_in)
        elif (isinstance(jack_count, bool)
                or not isinstance(jack_count, int)
                or jack_count not in (1, 2, 3)):
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                f'Opening {i}: "jack_count" must be 1, 2, or 3',
            )

        out.append({
            "opening_type": "DOOR" if t == "door" else "WINDOW",
            "type_lower": t,
            "x_offset_in": x_offset_in,
            "ro_width_in": ro_width_in,
            "ro_height_in": ro_height_in,
            "sill_height_in": sill_height_in,
            "header_nominal": header_nominal,
            "jack_count": jack_count,
        })
    return out


# ---------------------------------------------------------------------------
# Object serialization
# ---------------------------------------------------------------------------

def _is_praxova_managed(obj: bpy.types.Object) -> bool:
    """True if obj carries any v0.4 / v0.6 Praxova role discriminator.

    v0.4 walls had only praxova_lumber.is_lumber to check. v0.6 added
    Building / Level / Wall Empties, each with its own PropertyGroup
    + is_* flag, so the bridge's praxova_only filter has to look at
    all four to enumerate the full hierarchy.
    """
    lumber_tag = getattr(obj, 'praxova_lumber', None)
    if lumber_tag is not None and lumber_tag.is_lumber:
        return True
    wall_tag = getattr(obj, 'praxova_wall', None)
    if wall_tag is not None and wall_tag.is_wall:
        return True
    level_tag = getattr(obj, 'praxova_level', None)
    if level_tag is not None and level_tag.is_level:
        return True
    building_tag = getattr(obj, 'praxova_building', None)
    if building_tag is not None and building_tag.is_building:
        return True
    return False


def _serialize_opening(op) -> dict:
    """Render one PraxovaWallOpening as a v0.5.1 wire-format dict.

    Inverse of the bridge's _parse_openings — so a wall returned by
    list_objects can be round-tripped back into frame_wall(
    wall_target=..., openings=...) without translation.
    """
    return {
        "type": op.opening_type.lower(),
        "x_offset_in": float(op.x_offset_in),
        "ro_width_in": float(op.ro_width_in),
        "ro_height_in": float(op.ro_height_in),
        "sill_height_in": float(op.sill_height_in),
        "header_nominal": op.header_nominal,
        "jack_count": int(op.jack_count),
    }


def _serialize_building(obj: bpy.types.Object) -> dict:
    """Building Empty -> dict with contained Level names + count."""
    bp = obj.praxova_building
    levels = [
        c for c in obj.children
        if getattr(c, 'praxova_level', None) is not None
        and c.praxova_level.is_level
    ]
    levels.sort(key=lambda lv: lv.praxova_level.level_index)
    return {
        "name": obj.name,
        "category": "BUILDING",
        "location_m": list(obj.location),
        "default_corner_style": bp.default_corner_style,
        "contained_level_names": [lv.name for lv in levels],
        "level_count": len(levels),
    }


def _serialize_level(obj: bpy.types.Object) -> dict:
    """Level Empty -> dict with parent Building + contained walls + joint count."""
    lp = obj.praxova_level
    parent = obj.parent
    parent_building = (
        parent.name
        if (parent is not None
            and getattr(parent, 'praxova_building', None) is not None
            and parent.praxova_building.is_building)
        else None
    )
    walls = [
        c for c in obj.children
        if getattr(c, 'praxova_wall', None) is not None
        and c.praxova_wall.is_wall
    ]
    walls.sort(key=lambda w: w.name)
    return {
        "name": obj.name,
        "category": "LEVEL",
        "level_index": int(lp.level_index),
        "level_height_in": float(lp.level_height_in),
        "parent_building": parent_building,
        "contained_wall_names": [w.name for w in walls],
        "wall_count": len(walls),
        "joints_count": len(lp.joints),
    }


def _serialize_wall(obj: bpy.types.Object) -> dict:
    """Wall Empty -> dict with PraxovaWallProps fields + openings."""
    wp = obj.praxova_wall
    parent = obj.parent
    parent_level = (
        parent.name
        if (parent is not None
            and getattr(parent, 'praxova_level', None) is not None
            and parent.praxova_level.is_level)
        else None
    )
    return {
        "name": obj.name,
        "category": "WALL",
        "location_m": list(obj.location),
        "rotation_deg_z": math.degrees(obj.rotation_euler[2]),
        "parent_level": parent_level,
        "length_in": float(wp.wall_length_in),
        "height_in": float(wp.wall_height_in),
        "nominal": wp.wall_nominal,
        "spacing_oc_in": float(wp.wall_spacing_oc_in),
        "top_plate_count": int(wp.wall_top_plate_count),
        "bottom_plate_count": int(wp.wall_bottom_plate_count),
        "openings": [_serialize_opening(op) for op in wp.wall_openings],
    }


def _serialize_material(obj: bpy.types.Object) -> dict:
    """v0.4 lumber/sheet/panel serialization. Branches on tag.category.

    Until v0.3.2 the LUMBER branch was followed by a bare else that
    hard-coded sheet fields — so PANEL objects (added in v0.3.1) were
    silently serializing with empty sheet_* fields. Now each category
    gets its own branch.
    """
    tag = obj.praxova_lumber
    out: dict = {
        "name": obj.name,
        "category": tag.category,
        "label": tag.cutlist_label,
        "orientation": tag.orientation,
        "location_m": list(obj.location),
        "dimensions_m": list(obj.dimensions),
    }
    if tag.category == 'LUMBER':
        out["nominal_size"] = tag.nominal_size
        out["length_in"] = tag.length_in
    elif tag.category == 'SHEET':
        out["sheet_material"] = tag.sheet_material
        out["sheet_thickness_callout"] = tag.sheet_thickness_callout
        out["sheet_size_key"] = tag.sheet_size_key
    elif tag.category == 'PANEL':
        out["panel_material"] = tag.panel_material
        out["panel_size_key"] = tag.panel_size_key
    return out


def _serialize_object(obj: bpy.types.Object) -> dict:
    """Render a Praxova-managed object as a JSON-friendly dict.

    Dispatches on role discriminators in priority order: wall, level,
    building, then v0.4 material (LUMBER/SHEET/PANEL via tag.category).
    Callers should have checked _is_praxova_managed first — this
    function assumes the object is Praxova-managed in some way and
    falls through to the material branch if no v0.6 discriminator
    matches.
    """
    wall_tag = getattr(obj, 'praxova_wall', None)
    if wall_tag is not None and wall_tag.is_wall:
        return _serialize_wall(obj)
    level_tag = getattr(obj, 'praxova_level', None)
    if level_tag is not None and level_tag.is_level:
        return _serialize_level(obj)
    building_tag = getattr(obj, 'praxova_building', None)
    if building_tag is not None and building_tag.is_building:
        return _serialize_building(obj)
    return _serialize_material(obj)


def _check_op_result(result: set, op_name: str) -> None:
    """Translate a bpy.ops result set into an RPCError if it didn't FINISH."""
    if 'FINISHED' in result:
        return
    if 'CANCELLED' in result:
        raise bridge.RPCError(
            APP_OPERATOR_FAILED,
            f"Operator {op_name} was cancelled",
            data={"result": sorted(result)},
        )
    raise bridge.RPCError(
        bridge.INTERNAL_ERROR,
        f"Operator {op_name} returned unexpected result: {sorted(result)}",
    )


# ===========================================================================
# Read-only context tools
# ===========================================================================

def list_materials(params: dict) -> dict:
    """Enumerate every material the add-on can place. Read-only."""
    return {
        "lumber_types": {
            nominal: {
                "actual_thickness_in": cross[0],
                "actual_width_in": cross[1],
                "lengths_ft": templates.LENGTHS_BY_TYPE.get(nominal, []),
            }
            for nominal, cross in templates.LUMBER_TYPES.items()
        },
        "sheet_sizes": {
            key: {"width_in": w, "length_in": ln}
            for key, (w, ln) in templates.SHEET_SIZES.items()
        },
        "sheet_thicknesses": [
            {
                "material": mat,
                "thickness_callout": cal,
                "actual_in": actual,
            }
            for (mat, cal), actual in templates.SHEET_THICKNESS_ACTUAL.items()
        ],
        "panel_sizes": {
            key: {"coverage_width_in": w, "length_in": ln}
            for key, (w, ln) in templates.PANEL_SIZES.items()
        },
        "panel_materials": [
            {
                "material": mat,
                "label": templates.PANEL_MATERIAL_LABELS.get(mat, mat),
                "profile_height_in": profile,
            }
            for mat, profile in templates.PANEL_MATERIAL_PROFILE.items()
        ],
        "orientations": ["VERTICAL", "HORIZONTAL"],
    }


def list_objects(params: dict) -> dict:
    """List scene objects. Defaults to Praxova-managed only.

    v0.6.1: "Praxova-managed" includes the v0.4 lumber/sheet/panel
    pieces AND the v0.6 hierarchy Empties (Building, Level, Wall).
    Each is reported via its own category — see _serialize_object.
    Pass praxova_only=False to include every scene Object.
    """
    praxova_only = _optional(params, "praxova_only", bool, default=True)
    objs: list[dict] = []
    for obj in bpy.context.scene.objects:
        is_praxova = _is_praxova_managed(obj)
        if praxova_only and not is_praxova:
            continue
        if is_praxova:
            objs.append(_serialize_object(obj))
        else:
            objs.append({
                "name": obj.name,
                "category": None,
                "location_m": list(obj.location),
                "dimensions_m": list(obj.dimensions),
            })
    return {"count": len(objs), "objects": objs}


def get_scene_info(params: dict) -> dict:
    """Cursor location, units, active object, save state."""
    scene = bpy.context.scene
    cursor = scene.cursor.location
    active = bpy.context.view_layer.objects.active
    return {
        "blend_filepath": bpy.data.filepath or None,
        "scene_name": scene.name,
        "unit_system": scene.unit_settings.system,
        "length_unit": scene.unit_settings.length_unit,
        "cursor_location_m": [cursor.x, cursor.y, cursor.z],
        "active_object_name": active.name if active else None,
        "object_count": len(scene.objects),
    }


# ===========================================================================
# Material placement
# ===========================================================================

def add_lumber(params: dict) -> dict:
    """Place a tagged lumber piece. See README for parameter semantics."""
    nominal = _require(
        params, "nominal", str, choices=tuple(templates.LUMBER_TYPES),
    )
    length_ft = _require(params, "length_ft", int)
    if length_ft < 1 or length_ft > 24:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "length_ft must be between 1 and 24",
        )
    valid_lengths = templates.LENGTHS_BY_TYPE.get(nominal, [])
    if valid_lengths and length_ft not in valid_lengths:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"length_ft={length_ft} not standard for {nominal}; "
            f"valid: {valid_lengths}",
            data={"nominal": nominal, "valid_lengths_ft": valid_lengths},
        )
    orientation = _optional(
        params, "orientation", str, default="VERTICAL",
        choices=("VERTICAL", "HORIZONTAL"),
    )
    location = _location_param(params)

    result = bpy.ops.praxova.add_lumber(
        'EXEC_DEFAULT',
        nominal=nominal,
        length_ft=length_ft,
        orientation=orientation,
    )
    _check_op_result(result, "praxova.add_lumber")

    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise bridge.RPCError(
            bridge.INTERNAL_ERROR,
            "add_lumber finished but produced no active object",
        )

    if location is not None:
        obj.location = location

    return _serialize_object(obj)


def add_sheet(params: dict) -> dict:
    """Place a tagged sheet good. See README for parameter semantics."""
    material = _require(params, "material", str, choices=("PLYWOOD", "OSB"))
    thickness = _require(params, "thickness", str, choices=("1/2", "3/4"))
    size = _require(
        params, "size", str, choices=tuple(templates.SHEET_SIZES),
    )
    orientation = _optional(
        params, "orientation", str, default="VERTICAL",
        choices=("VERTICAL", "HORIZONTAL"),
    )
    if (material, thickness) not in templates.SHEET_THICKNESS_ACTUAL:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f'No actual thickness defined for {material} {thickness}"',
        )
    location = _location_param(params)

    result = bpy.ops.praxova.add_sheet(
        'EXEC_DEFAULT',
        material=material,
        thickness=thickness,
        size=size,
        orientation=orientation,
    )
    _check_op_result(result, "praxova.add_sheet")

    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise bridge.RPCError(
            bridge.INTERNAL_ERROR,
            "add_sheet finished but produced no active object",
        )

    if location is not None:
        obj.location = location

    return _serialize_object(obj)


def add_panel(params: dict) -> dict:
    """Place a tagged metal roofing/siding panel.

    Mirrors add_sheet's contract. Required: 'material', 'size'.
    Optional: 'orientation' (default VERTICAL), 'location_m'.

    Profile height is intentionally NOT a bridge parameter in v0.3.2 -
    the per-material default in templates.PANEL_MATERIAL_PROFILE is
    the source of truth (currently 0.75" for METAL). A profile_height
    override could be added later if a use case appears, but for now
    LLM agents shouldn't have to think about rib geometry.
    """
    material = _require(
        params, "material", str,
        choices=tuple(templates.PANEL_MATERIAL_PROFILE),
    )
    size = _require(
        params, "size", str, choices=tuple(templates.PANEL_SIZES),
    )
    orientation = _optional(
        params, "orientation", str, default="VERTICAL",
        choices=("VERTICAL", "HORIZONTAL"),
    )
    location = _location_param(params)

    result = bpy.ops.praxova.add_panel(
        'EXEC_DEFAULT',
        material=material,
        size=size,
        orientation=orientation,
    )
    _check_op_result(result, "praxova.add_panel")

    obj = bpy.context.view_layer.objects.active
    if obj is None:
        raise bridge.RPCError(
            bridge.INTERNAL_ERROR,
            "add_panel finished but produced no active object",
        )

    if location is not None:
        obj.location = location

    return _serialize_object(obj)


# ===========================================================================
# Duplication
# ===========================================================================

def duplicate_oc(params: dict) -> dict:
    """Duplicate `target_name` (or active object) on-center along its local X."""
    spacing_in = _require(params, "spacing_in", (int, float))
    if isinstance(spacing_in, bool) or spacing_in <= 0:
        raise bridge.RPCError(bridge.INVALID_PARAMS, "spacing_in must be > 0")
    count = _require(params, "count", int)
    if count < 1 or count > 500:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "count must be between 1 and 500",
        )
    direction = _optional(
        params, "direction", str, default="RIGHT",
        choices=("LEFT", "RIGHT"),
    )
    target_name = _optional(params, "target_name", str, default=None)

    scene = bpy.context.scene

    # Resolve target object.
    if target_name is not None:
        target = scene.objects.get(target_name)
        if target is None:
            raise bridge.RPCError(
                APP_OBJECT_NOT_FOUND,
                f"No object named {target_name!r} in scene",
            )
        for o in bpy.context.selected_objects:
            o.select_set(False)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
    else:
        target = bpy.context.view_layer.objects.active
        if target is None:
            raise bridge.RPCError(
                APP_NO_ACTIVE_OBJECT,
                "No active object to duplicate. "
                "Pass 'target_name' or select an object in Blender first.",
            )

    # Configure scene-level operator inputs.
    sp = scene.praxova_framing
    sp.spacing_in = float(spacing_in)
    sp.count = count
    sp.direction = direction

    # Snapshot existing names so we can identify exactly the new ones - more
    # robust than reading selected_objects after the operator.
    before = {o.name for o in scene.objects}
    result = bpy.ops.praxova.duplicate_oc('EXEC_DEFAULT')
    _check_op_result(result, "praxova.duplicate_oc")
    after = {o.name for o in scene.objects}
    new_names = sorted(after - before)

    return {
        "source": target.name,
        "spacing_in": float(spacing_in),
        "count": count,
        "direction": direction,
        "new_objects": new_names,
    }


def duplicate_e2e(params: dict) -> dict:
    """Duplicate `target_name` (or active) edge-to-edge along its local Y.

    Mirrors duplicate_oc's contract but with no spacing parameter - spacing
    is automatically the source's own width (48" for a 4x8 sheet, 36" for
    a metal panel). Same constraint that the UI Fill operator has, and
    intentionally so: keeping the bridge tool and the UI tool in lockstep
    means an LLM agent and a human will get the same result for the same
    inputs. For custom-spaced arrays, use duplicate_oc.

    Refuses LUMBER targets with INVALID_PARAMS - lumber's local-Y is its
    cross-section width (3.5" for a 2x4), not a meaningful fill spacing.
    Validating here gives the LLM a clean error code, rather than waiting
    for the operator to fail and surfacing as APP_OPERATOR_FAILED.
    """
    count = _require(params, "count", int)
    if count < 1 or count > 500:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "count must be between 1 and 500",
        )
    direction = _optional(
        params, "direction", str, default="FORWARD",
        choices=("FORWARD", "BACK"),
    )
    target_name = _optional(params, "target_name", str, default=None)

    scene = bpy.context.scene

    # Resolve target object.
    if target_name is not None:
        target = scene.objects.get(target_name)
        if target is None:
            raise bridge.RPCError(
                APP_OBJECT_NOT_FOUND,
                f"No object named {target_name!r} in scene",
            )
        for o in bpy.context.selected_objects:
            o.select_set(False)
        target.select_set(True)
        bpy.context.view_layer.objects.active = target
    else:
        target = bpy.context.view_layer.objects.active
        if target is None:
            raise bridge.RPCError(
                APP_NO_ACTIVE_OBJECT,
                "No active object to fill. "
                "Pass 'target_name' or select a sheet or panel in Blender first.",
            )

    # Validate target is SHEET or PANEL. Clean error code here is more
    # useful to LLM agents than the operator's generic APP_OPERATOR_FAILED.
    tag = getattr(target, "praxova_lumber", None)
    if tag is None or not tag.is_lumber:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"Target {target.name!r} is not a Praxova-tagged piece. "
            f"Add a sheet or panel first via add_sheet or add_panel.",
        )
    if tag.category not in {'SHEET', 'PANEL'}:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"Fill works on sheets and panels, not {tag.category.lower()}. "
            f"For lumber arrays, use duplicate_oc with explicit spacing.",
        )

    # Capture the width before the operator runs - the operator uses it
    # but doesn't return it, and callers (especially LLM agents) often
    # want to verify what spacing was actually applied.
    width_in = templates.fill_axis_width_in(target)

    # Configure scene-level operator inputs. (No spacing field; the
    # operator derives it from the active object's width.)
    sp = scene.praxova_framing
    sp.fill_count = count
    sp.fill_direction = direction

    before = {o.name for o in scene.objects}
    result = bpy.ops.praxova.duplicate_e2e('EXEC_DEFAULT')
    _check_op_result(result, "praxova.duplicate_e2e")
    after = {o.name for o in scene.objects}
    new_names = sorted(after - before)

    return {
        "source": target.name,
        "width_in": width_in,
        "count": count,
        "direction": direction,
        "new_objects": new_names,
    }


# ===========================================================================
# Building / Level containers (v0.6.1 bridge parity for v0.6 hierarchy)
# ===========================================================================

def add_building(params: dict) -> dict:
    """Create a Building Empty with a default Level child under it.

    The Building Empty is a grouping container; the default Level is
    where walls land when frame_wall is called with level=<this Level's
    name>. Both new Empties are set as the scene's active Building /
    active Level, matching the UI operator's behavior.

    Optional:
        name (str): override the auto-generated Building_NN name. Must
            not collide with any existing scene object.
        location_m ([x, y, z] meters): position the Building Empty in
            world space. Children (the default Level + future walls)
            follow via parent-child transform inheritance.
        default_corner_style (str): only "THREE_STUD" valid in v0.6;
            v0.7 will add "CALIFORNIA" and "LADDER_BLOCKING". The
            param is exposed now for forward-compat — passing
            "THREE_STUD" (or omitting it) gets you the v0.6 behavior.

    Returns:
        building_name: name of the new Building Empty
        level_name: name of the auto-created default Level child
        level_index: always 0 for the default Level
        location_m: echo of the Building's world location
        default_corner_style: echo of the resolved style
    """
    requested_name = _optional(params, "name", str, default=None)
    if (requested_name is not None
            and requested_name in bpy.data.objects):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"name {requested_name!r} already exists in the scene",
        )
    location = _location_param(params)
    default_corner_style = _optional(
        params, "default_corner_style", str, default="THREE_STUD",
        choices=("THREE_STUD",),
    )

    scene = bpy.context.scene
    sp = scene.praxova_framing

    result = bpy.ops.praxova.add_building('EXEC_DEFAULT')
    _check_op_result(result, "praxova.add_building")

    building = sp.active_building
    level = sp.active_level
    if building is None or level is None:
        raise bridge.RPCError(
            bridge.INTERNAL_ERROR,
            "add_building finished but produced no active Building/Level",
        )

    if requested_name is not None:
        building.name = requested_name
    if location is not None:
        building.location = location
    building.praxova_building.default_corner_style = default_corner_style

    return {
        "building_name": building.name,
        "level_name": level.name,
        "level_index": level.praxova_level.level_index,
        "location_m": list(building.location),
        "default_corner_style": (
            building.praxova_building.default_corner_style
        ),
    }


def add_level(params: dict) -> dict:
    """Add a new Level under an existing Building.

    Required:
        building (str): name of the Building Empty to add the Level
            under. Must be a Praxova-managed Building (is_building=True
            on its praxova_building PropertyGroup).

    Optional:
        name (str): override the auto-generated Level_NN name. Must
            not collide with any existing scene object.
        level_height_in (number): floor-to-floor reference height for
            this Level. Defaults to the value on PraxovaLevelProps,
            which the UI uses as the standard residential 8' (96").

    Returns:
        level_name: name of the new Level Empty
        level_index: auto-assigned (one higher than the highest
            existing Level under this Building, starting at 0)
        building: echo of the input
        level_height_in: echo of the resolved value
    """
    building_name = _require(params, "building", str)
    requested_name = _optional(params, "name", str, default=None)
    if (requested_name is not None
            and requested_name in bpy.data.objects):
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"name {requested_name!r} already exists in the scene",
        )

    building = bpy.data.objects.get(building_name)
    if (building is None
            or getattr(building, 'praxova_building', None) is None
            or not building.praxova_building.is_building):
        raise bridge.RPCError(
            APP_OBJECT_NOT_FOUND,
            f"No Praxova Building named {building_name!r} in scene",
        )

    level_height_in = _optional(
        params, "level_height_in", (int, float), default=None,
    )
    if level_height_in is not None:
        if isinstance(level_height_in, bool) or level_height_in <= 0:
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                "level_height_in must be > 0",
            )
        level_height_in = float(level_height_in)

    scene = bpy.context.scene
    sp = scene.praxova_framing

    # The UI op reads sp.active_building. Briefly point it at the
    # requested Building so the op parents the new Level there; v0.6
    # already updates sp.active_level after creation so we don't need
    # to track that ourselves.
    sp.active_building = building

    result = bpy.ops.praxova.add_level('EXEC_DEFAULT')
    _check_op_result(result, "praxova.add_level")

    level = sp.active_level
    if level is None or level.parent is not building:
        raise bridge.RPCError(
            bridge.INTERNAL_ERROR,
            "add_level finished but no new Level was attached to "
            f"{building_name!r}",
        )

    if requested_name is not None:
        level.name = requested_name
    if level_height_in is not None:
        level.praxova_level.level_height_in = level_height_in

    return {
        "level_name": level.name,
        "level_index": level.praxova_level.level_index,
        "building": building.name,
        "level_height_in": level.praxova_level.level_height_in,
    }


# ===========================================================================
# Composite framing (v0.4.1 bridge parity for v0.4 frame_wall operator)
# ===========================================================================

def frame_wall(params: dict) -> dict:
    """Frame a wall — CREATE a new one or REBUILD an existing one in place.

    Two modes, picked by whether `wall_target` is set:

    CREATE (wall_target is None, default):
        Build a new wall Empty + children at world origin (or under a
        Level Empty via `level`). `length_in` and `height_in` are
        REQUIRED. Other scalars take their v0.4.1 defaults
        ("2x4"/16/2/1). The Empty is named by the v0.4 next_wall_name
        helper (Wall_NN).

    REBUILD (wall_target set):
        Re-frame an existing wall in place. The wall Empty itself is
        preserved (name, transform, joint references all survive);
        only its children get deleted and rebuilt. Each scalar param
        you provide is WRITTEN THROUGH to the wall's PraxovaWallProps;
        each one you omit preserves the existing value. So you can
        change just the length without re-passing height, nominal,
        etc. `openings` follows the same rule — provide a list and the
        wall's openings are fully replaced, omit it and they're
        preserved verbatim.

    Required when wall_target is None:
        length_in (number > 0): wall length along +X in inches.
        height_in (number > 0): wall height in inches.

    Optional in both modes:
        nominal (str): stud size from LUMBER_TYPES. CREATE default
            "2x4"; REBUILD default = the wall's current value.
        spacing_oc_in (number > 0): on-center stud spacing. CREATE
            default 16.0; REBUILD default = current.
        top_plate_count (int 1-4): CREATE default 2; REBUILD default
            = current.
        bottom_plate_count (int 1-4): CREATE default 1; REBUILD
            default = current.
        location_m ([x, y, z] meters): set the Empty's world location.
            In REBUILD mode, omitted means preserve current location.
        openings (list of opening dicts): see v0.5.1 docstring for the
            full opening dict shape. REBUILD with omitted = preserve;
            REBUILD with [] = clear; CREATE with omitted = no openings.

    v0.6.1 additions:
        level (str): name of a Praxova Level Empty (is_level=True). In
            CREATE mode, the new wall is parented under this Level. In
            REBUILD mode, if it differs from the wall's current parent
            the wall is re-parented (joints in the OLD Level still
            reference the wall — clean them up via the Joints UIList).
        wall_target (str): name of a Praxova wall Empty (is_wall=True)
            to re-frame in place. Mutually picks REBUILD over CREATE.
        rotation_deg_z (number): Z-axis rotation in degrees applied to
            the wall Empty. CREATE: 0 if omitted. REBUILD: preserves
            current rotation if omitted. **JOINTS LOCK ROTATION**: in
            REBUILD mode, if `rotation_deg_z` differs from the wall's
            current rotation AND the wall's parent Level has any joint
            referencing this wall, the call is refused with
            INVALID_PARAMS. Remove the joint via the Joints UIList in
            Blender before rotating, then re-add it after re-framing.

    Validation order: argument resolution (level / wall_target /
    rotation), then mode-specific scalar reads with their respective
    defaults, then the shared cross-field validation (length/thickness,
    stud length > 0, stock fits, openings within wall, etc.).

    Returns (in addition to the v0.5.1 fields wall_name, n_studs,
    n_plates, stud_length_in, stud_stock_in, plate_stock_in,
    n_openings, openings_summary, new_objects, plus the input echoes):
        wall_target_used (bool): True for REBUILD, False for CREATE.
        level_name (str | None): the wall's parent Level Empty name,
            None for top-level walls.
        rotation_deg_z (float): the wall Empty's Z rotation in degrees
            after the call.
    """
    # ------------------------------------------------------------------
    # Phase 1: meta-args resolution (level / wall_target / rotation)
    # ------------------------------------------------------------------
    scene = bpy.context.scene
    sp = scene.praxova_framing

    level_name = _optional(params, "level", str, default=None)
    level_obj = None
    if level_name is not None:
        level_obj = bpy.data.objects.get(level_name)
        if (level_obj is None
                or getattr(level_obj, 'praxova_level', None) is None
                or not level_obj.praxova_level.is_level):
            raise bridge.RPCError(
                APP_OBJECT_NOT_FOUND,
                f"No Praxova Level named {level_name!r} in scene",
            )

    wall_target_name = _optional(params, "wall_target", str, default=None)
    wall_target_obj = None
    if wall_target_name is not None:
        wall_target_obj = bpy.data.objects.get(wall_target_name)
        if (wall_target_obj is None
                or getattr(wall_target_obj, 'praxova_wall', None) is None
                or not wall_target_obj.praxova_wall.is_wall):
            raise bridge.RPCError(
                APP_OBJECT_NOT_FOUND,
                f"No Praxova wall named {wall_target_name!r} in scene",
            )

    rotation_deg_z_param = _optional(
        params, "rotation_deg_z", (int, float), default=None,
    )
    if rotation_deg_z_param is not None:
        if isinstance(rotation_deg_z_param, bool):
            raise bridge.RPCError(
                bridge.INVALID_PARAMS,
                'Parameter "rotation_deg_z" must be a number, got bool',
            )
        rotation_deg_z_param = float(rotation_deg_z_param)

    location = _location_param(params)
    is_rebuild = wall_target_obj is not None

    # ------------------------------------------------------------------
    # Phase 2: scalar param resolution (mode-specific defaults)
    # ------------------------------------------------------------------
    if is_rebuild:
        wp = wall_target_obj.praxova_wall
        length_in = _optional(
            params, "length_in", (int, float),
            default=float(wp.wall_length_in),
        )
        height_in = _optional(
            params, "height_in", (int, float),
            default=float(wp.wall_height_in),
        )
        nominal = _optional(
            params, "nominal", str, default=wp.wall_nominal,
            choices=tuple(templates.LUMBER_TYPES),
        )
        spacing_oc_in = _optional(
            params, "spacing_oc_in", (int, float),
            default=float(wp.wall_spacing_oc_in),
        )
        top_plate_count = _optional(
            params, "top_plate_count", int,
            default=int(wp.wall_top_plate_count),
        )
        bottom_plate_count = _optional(
            params, "bottom_plate_count", int,
            default=int(wp.wall_bottom_plate_count),
        )
    else:
        # CREATE: length_in and height_in are required.
        length_in = _require(params, "length_in", (int, float))
        height_in = _require(params, "height_in", (int, float))
        nominal = _optional(
            params, "nominal", str, default="2x4",
            choices=tuple(templates.LUMBER_TYPES),
        )
        spacing_oc_in = _optional(
            params, "spacing_oc_in", (int, float), default=16.0,
        )
        top_plate_count = _optional(
            params, "top_plate_count", int, default=2,
        )
        bottom_plate_count = _optional(
            params, "bottom_plate_count", int, default=1,
        )

    if isinstance(length_in, bool) or length_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "length_in must be > 0",
        )
    length_in = float(length_in)

    if isinstance(height_in, bool) or height_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "height_in must be > 0",
        )
    height_in = float(height_in)

    if isinstance(spacing_oc_in, bool) or spacing_oc_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "spacing_oc_in must be > 0",
        )
    spacing_oc_in = float(spacing_oc_in)

    if top_plate_count < 1 or top_plate_count > 4:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            "top_plate_count must be between 1 and 4",
        )
    if bottom_plate_count < 1 or bottom_plate_count > 4:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            "bottom_plate_count must be between 1 and 4",
        )

    # ------------------------------------------------------------------
    # Phase 3: shared scalar cross-field validation
    # ------------------------------------------------------------------
    thickness_in, _width_in = templates.LUMBER_TYPES[nominal]

    if length_in < 2 * thickness_in:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"length_in={length_in:g} too short for two end studs of "
            f"{thickness_in:g}\" thickness ({nominal})",
        )

    plate_total_in = (top_plate_count + bottom_plate_count) * thickness_in
    stud_length_in = height_in - plate_total_in
    if stud_length_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            f"height_in={height_in:g} too short for "
            f"{top_plate_count + bottom_plate_count} plates of "
            f"{thickness_in:g}\" thickness ({plate_total_in:g}\" total)",
        )

    try:
        plate_stock_in = templates.select_stock_length_in(nominal, length_in)
        stud_stock_in = templates.select_stock_length_in(
            nominal, stud_length_in,
        )
    except ValueError as e:
        raise bridge.RPCError(bridge.INVALID_PARAMS, str(e))

    # ------------------------------------------------------------------
    # Phase 4: openings parse (per-dict validation, default-fill)
    # ------------------------------------------------------------------
    # CREATE mode: missing/None => empty list (no openings on the new wall).
    # REBUILD mode: missing/None => sentinel "preserve existing" (no
    # touch of wp.wall_openings); a provided list (including []) is a
    # full replacement.
    raw_openings = _optional(params, "openings", list, default=None)
    if raw_openings is not None:
        parsed_openings = _parse_openings(raw_openings, nominal)
        openings_provided = True
    elif is_rebuild:
        parsed_openings = []  # placeholder; we'll read from wp below
        openings_provided = False
    else:
        parsed_openings = []
        openings_provided = True  # CREATE always writes (empty list)

    # ------------------------------------------------------------------
    # Phase 5 (REBUILD only): joint check for rotation
    # ------------------------------------------------------------------
    # Refuse rotation if joints reference this wall in its current
    # parent Level. Done BEFORE write-through so a refusal leaves the
    # wall untouched. Level change is a separate concern — joints in
    # the OLD Level become orphaned references but that's a v0.6 data
    # invariant the user manages, not something v0.6.1 prevents.
    rotation_changed_in_rebuild = False
    if is_rebuild and rotation_deg_z_param is not None:
        new_rot_rad = math.radians(rotation_deg_z_param)
        current_rot_rad = wall_target_obj.rotation_euler[2]
        rotation_changed_in_rebuild = not math.isclose(
            new_rot_rad, current_rot_rad,
            rel_tol=1e-6, abs_tol=1e-9,
        )
        if rotation_changed_in_rebuild:
            current_parent = wall_target_obj.parent
            if (current_parent is not None
                    and getattr(current_parent, 'praxova_level', None) is not None
                    and current_parent.praxova_level.is_level):
                for joint in current_parent.praxova_level.joints:
                    if (joint.wall_a == wall_target_obj
                            or joint.wall_b == wall_target_obj):
                        raise bridge.RPCError(
                            bridge.INVALID_PARAMS,
                            f"Cannot rotate {wall_target_obj.name}: "
                            "joint(s) reference this wall. Remove the "
                            "joint via the Joints UIList in Blender "
                            "before rotating, then re-add after "
                            "re-framing.",
                        )

    # ------------------------------------------------------------------
    # Phase 6: write-through to the chosen target's props
    # ------------------------------------------------------------------
    if is_rebuild:
        wp.wall_length_in = length_in
        wp.wall_height_in = height_in
        wp.wall_nominal = nominal
        wp.wall_spacing_oc_in = spacing_oc_in
        wp.wall_top_plate_count = top_plate_count
        wp.wall_bottom_plate_count = bottom_plate_count
        if openings_provided:
            wp.wall_openings.clear()
            for parsed in parsed_openings:
                item = wp.wall_openings.add()
                item.opening_type = parsed["opening_type"]
                item.x_offset_in = parsed["x_offset_in"]
                item.ro_width_in = parsed["ro_width_in"]
                item.ro_height_in = parsed["ro_height_in"]
                item.sill_height_in = parsed["sill_height_in"]
                item.header_nominal = parsed["header_nominal"]
                item.jack_count = parsed["jack_count"]
        target_openings = list(wp.wall_openings)
    else:
        sp.wall_length_in = length_in
        sp.wall_height_in = height_in
        sp.wall_nominal = nominal
        sp.wall_spacing_oc_in = spacing_oc_in
        sp.wall_top_plate_count = top_plate_count
        sp.wall_bottom_plate_count = bottom_plate_count
        sp.wall_openings.clear()
        for parsed in parsed_openings:
            item = sp.wall_openings.add()
            item.opening_type = parsed["opening_type"]
            item.x_offset_in = parsed["x_offset_in"]
            item.ro_width_in = parsed["ro_width_in"]
            item.ro_height_in = parsed["ro_height_in"]
            item.sill_height_in = parsed["sill_height_in"]
            item.header_nominal = parsed["header_nominal"]
            item.jack_count = parsed["jack_count"]
        target_openings = list(sp.wall_openings)

    # Cross-field opening validation — same source of truth the UI
    # uses. Runs against whatever's now on the target (post-writethrough
    # for both modes), so REBUILD with omitted openings validates the
    # preserved set against the (possibly new) scalars.
    if target_openings:
        ok, msg = templates.validate_openings(
            target_openings,
            length_in, height_in, nominal,
            top_plate_count, bottom_plate_count,
        )
        if not ok:
            raise bridge.RPCError(bridge.INVALID_PARAMS, msg)

    # ------------------------------------------------------------------
    # Phase 7 (REBUILD only): re-parent if level differs
    # ------------------------------------------------------------------
    if is_rebuild and level_obj is not None and wall_target_obj.parent is not level_obj:
        wall_target_obj.parent = level_obj

    # ------------------------------------------------------------------
    # Phase 8: set active object for the op's mode detection
    # ------------------------------------------------------------------
    # The op picks its mode from context.view_layer.objects.active:
    #   wall Empty (is_wall=True)  -> REBUILD in place
    #   Level Empty (is_level=True) -> CREATE under the Level
    #   anything else / None       -> CREATE at top level
    # Be explicit to override whatever the user had selected before.
    for o in bpy.context.selected_objects:
        o.select_set(False)
    if is_rebuild:
        wall_target_obj.select_set(True)
        bpy.context.view_layer.objects.active = wall_target_obj
    elif level_obj is not None:
        level_obj.select_set(True)
        bpy.context.view_layer.objects.active = level_obj
        sp.active_level = level_obj
    else:
        bpy.context.view_layer.objects.active = None

    # ------------------------------------------------------------------
    # Phase 9: run the op
    # ------------------------------------------------------------------
    before = {o.name for o in scene.objects}
    result = bpy.ops.praxova.frame_wall('EXEC_DEFAULT')
    _check_op_result(result, "praxova.frame_wall")
    after = {o.name for o in scene.objects}
    new_names = sorted(after - before)

    # ------------------------------------------------------------------
    # Phase 10: locate the wall Empty (preserved for REBUILD, just
    # created for CREATE) and apply rotation / location overrides
    # ------------------------------------------------------------------
    if is_rebuild:
        empty = wall_target_obj
    else:
        empty = bpy.context.view_layer.objects.active
        if empty is None or getattr(empty, 'praxova_wall', None) is None:
            raise bridge.RPCError(
                bridge.INTERNAL_ERROR,
                "frame_wall finished but produced no active wall Empty",
            )

    if rotation_deg_z_param is not None:
        empty.rotation_euler[2] = math.radians(rotation_deg_z_param)
    elif not is_rebuild:
        # CREATE with no explicit rotation = 0 (matches the v0.5.1
        # behavior — newly-created wall Empties are unrotated).
        empty.rotation_euler[2] = 0.0
    if location is not None:
        empty.location = location

    # ------------------------------------------------------------------
    # Phase 11: compute return values from the wall's final state
    # ------------------------------------------------------------------
    raw_stud_xs = templates.stud_positions(
        length_in, spacing_oc_in, thickness_in,
    )
    if target_openings:
        opening_layouts = [
            templates.opening_framing_layout(
                item, nominal, height_in,
                top_plate_count, bottom_plate_count,
            )
            for item in target_openings
        ]
        filtered_stud_xs = templates.filter_studs_around_openings(
            raw_stud_xs, thickness_in, target_openings, opening_layouts,
        )
        n_studs = len(filtered_stud_xs)
    else:
        opening_layouts = []
        n_studs = len(raw_stud_xs)
    n_plates = top_plate_count + bottom_plate_count

    openings_summary: list[dict] = []
    for item, layout in zip(target_openings, opening_layouts):
        k_left_in = layout["king_left_x"] + thickness_in
        k_right_in = layout["king_right_x"] - thickness_in
        cripples_at_oc = sum(
            1 for x in raw_stud_xs
            if x >= k_left_in and x + thickness_in <= k_right_in
        )
        top_zone = layout["cripple_top_zone"]
        n_header_cripples = cripples_at_oc if top_zone[0] is not None else 0
        if item.opening_type == "WINDOW":
            bot_zone = layout["cripple_bottom_zone"]
            n_sill_cripples = (
                cripples_at_oc if bot_zone[0] is not None else 0
            )
        else:
            n_sill_cripples = 0
        openings_summary.append({
            "type": item.opening_type.lower(),
            "jack_count": int(item.jack_count),
            "header_nominal": item.header_nominal,
            "jack_length_in": layout["jack_length_in"],
            "header_length_in": layout["header_member_length_in"],
            "n_header_cripples": n_header_cripples,
            "n_sill_cripples": n_sill_cripples,
        })

    # Level / rotation report fields — derived from the wall Empty's
    # actual final state so REBUILD with preserve also reports correctly.
    parent_now = empty.parent
    level_name_out: str | None = None
    if (parent_now is not None
            and getattr(parent_now, 'praxova_level', None) is not None
            and parent_now.praxova_level.is_level):
        level_name_out = parent_now.name
    rotation_deg_z_out = math.degrees(empty.rotation_euler[2])

    return {
        "wall_name": empty.name,
        "length_in": length_in,
        "height_in": height_in,
        "nominal": nominal,
        "spacing_oc_in": spacing_oc_in,
        "top_plate_count": top_plate_count,
        "bottom_plate_count": bottom_plate_count,
        "n_studs": n_studs,
        "n_plates": n_plates,
        "stud_length_in": stud_length_in,
        "stud_stock_in": stud_stock_in,
        "plate_stock_in": plate_stock_in,
        "n_openings": len(target_openings),
        "openings_summary": openings_summary,
        "new_objects": new_names,
        # v0.6.1 additions:
        "wall_target_used": is_rebuild,
        "level_name": level_name_out,
        "rotation_deg_z": rotation_deg_z_out,
    }


# ===========================================================================
# Cut list
# ===========================================================================

def generate_cutlist(params: dict) -> dict:
    """Walk the scene, write the cut-list Text datablock + .txt sidecar."""
    result = bpy.ops.praxova.generate_cutlist('EXEC_DEFAULT')
    if 'CANCELLED' in result:
        # The operator cancels specifically when there's nothing tagged.
        raise bridge.RPCError(
            APP_EMPTY_CUTLIST,
            "No tagged Praxova material found in scene",
        )
    _check_op_result(result, "praxova.generate_cutlist")

    text_db = bpy.data.texts.get(TEXT_DATABLOCK_NAME)
    body = text_db.as_string() if text_db else ""
    return {
        "text": body,
        "text_datablock": TEXT_DATABLOCK_NAME,
        "disk_path": _disk_path_for_current_blend(),
    }


# ===========================================================================
# Units
# ===========================================================================

def set_imperial_units(params: dict) -> dict:
    """Switch the scene to imperial units."""
    result = bpy.ops.praxova.set_imperial_units('EXEC_DEFAULT')
    _check_op_result(result, "praxova.set_imperial_units")
    scene = bpy.context.scene
    return {
        "unit_system": scene.unit_settings.system,
        "length_unit": scene.unit_settings.length_unit,
    }


# ===========================================================================
# Bridge meta
# ===========================================================================

def ping(params: dict) -> dict:
    """Liveness probe. Useful for the MCP server to verify connectivity.

    The reported addon_version is imported from the package's __version__
    constant in __init__.py, bumped on every release including UI-only
    cycles. blender_manifest.toml is the canonical version for Blender's
    extension loader (read at install time, not by Python); __version__
    in __init__.py is the canonical version for Python code. The two must
    be bumped together each release but Python callers have a single
    source of truth - the late-cycle bug from v0.4.0 (bridge hardcoded
    its own "0.3.4" while the manifest moved to "0.4.0") can't recur.
    """
    return {
        "ok": True,
        "addon_version": __version__,
        "method_count": len(METHODS),
    }


# ===========================================================================
# Method registry — canonical RPC surface
# ===========================================================================

METHODS = {
    "ping": ping,
    "list_materials": list_materials,
    "list_objects": list_objects,
    "get_scene_info": get_scene_info,
    "add_lumber": add_lumber,
    "add_sheet": add_sheet,
    "add_panel": add_panel,
    "duplicate_oc": duplicate_oc,
    "duplicate_e2e": duplicate_e2e,
    # v0.6.1: containers for the multi-wall hierarchy. Joint methods
    # and frame_building land in v0.6.2.
    "add_building": add_building,
    "add_level": add_level,
    "frame_wall": frame_wall,
    "generate_cutlist": generate_cutlist,
    "set_imperial_units": set_imperial_units,
}

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

from typing import Any

import bpy
from mathutils import Vector

from . import bridge
from .. import templates
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
# Object serialization
# ---------------------------------------------------------------------------

def _serialize_object(obj: bpy.types.Object) -> dict:
    """Render a Praxova-tagged object as a JSON-friendly dict.

    Branches on tag.category. Until v0.3.2 the LUMBER branch was followed
    by a bare else that hard-coded sheet fields - so PANEL objects (added
    in v0.3.1) were silently serializing with empty sheet_* fields. Now
    each category gets its own branch.
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
    """List scene objects. Defaults to Praxova-tagged only."""
    praxova_only = _optional(params, "praxova_only", bool, default=True)
    objs: list[dict] = []
    for obj in bpy.context.scene.objects:
        tag = getattr(obj, "praxova_lumber", None)
        is_praxova = tag is not None and tag.is_lumber
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
    """Liveness probe. Useful for the MCP server to verify connectivity."""
    return {
        "ok": True,
        "addon_version": "0.3.2",
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
    "generate_cutlist": generate_cutlist,
    "set_imperial_units": set_imperial_units,
}

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
# Composite framing (v0.4.1 bridge parity for v0.4 frame_wall operator)
# ===========================================================================

def frame_wall(params: dict) -> dict:
    """Frame a single wall - plates + studs + Empty parent.

    Required:
        length_in (number > 0): wall length along +X in inches.
        height_in (number > 0): wall height (floor to top of top plate)
            in inches.
    Optional:
        nominal (str, default "2x4"): stud size from LUMBER_TYPES.
        spacing_oc_in (number > 0, default 16.0): on-center stud spacing
            in inches (typically 16 for residential, 24 for some commercial).
        top_plate_count (int 1-4, default 2): 2 for load-bearing (US
            residential standard), 1 for non-load-bearing partition.
        bottom_plate_count (int 1-4, default 1): typically 1.
        location_m (3-element [x,y,z] list, default [0, 0, 0]): world
            location for the new wall Empty parent. Children's local
            positions stay wall-relative.

    Returns:
        wall_name (the new Empty), echoes of all input params, n_studs
        (computed from length / spacing / thickness), n_plates
        (top + bottom), stud_length_in (cut length after the plate stack),
        stud_stock_in (smallest stock the studs are cut from),
        plate_stock_in (same for plates), new_objects (sorted Empty + all
        child names).

    Pre-validates the same cross-field constraints the operator does
    (known nominal, length >= 2*thickness, stud length positive, stock
    fits within LENGTHS_BY_TYPE) so the LLM gets clean INVALID_PARAMS
    error codes rather than the operator's generic APP_OPERATOR_FAILED.
    The operator's internal validation is still defense in depth.
    """
    # --- Required ---
    length_in = _require(params, "length_in", (int, float))
    if isinstance(length_in, bool) or length_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "length_in must be > 0",
        )
    length_in = float(length_in)

    height_in = _require(params, "height_in", (int, float))
    if isinstance(height_in, bool) or height_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "height_in must be > 0",
        )
    height_in = float(height_in)

    # --- Optional ---
    nominal = _optional(
        params, "nominal", str, default="2x4",
        choices=tuple(templates.LUMBER_TYPES),
    )

    spacing_oc_in = _optional(
        params, "spacing_oc_in", (int, float), default=16.0,
    )
    if isinstance(spacing_oc_in, bool) or spacing_oc_in <= 0:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS, "spacing_oc_in must be > 0",
        )
    spacing_oc_in = float(spacing_oc_in)

    top_plate_count = _optional(
        params, "top_plate_count", int, default=2,
    )
    if top_plate_count < 1 or top_plate_count > 4:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            "top_plate_count must be between 1 and 4",
        )

    bottom_plate_count = _optional(
        params, "bottom_plate_count", int, default=1,
    )
    if bottom_plate_count < 1 or bottom_plate_count > 4:
        raise bridge.RPCError(
            bridge.INVALID_PARAMS,
            "bottom_plate_count must be between 1 and 4",
        )

    location = _location_param(params)

    # --- Cross-field validation (mirrors ops_frame.py) ---
    # Pre-validating here means INVALID_PARAMS instead of
    # APP_OPERATOR_FAILED when the wall is geometrically impossible -
    # cleaner error codes for the LLM. Operator still validates as
    # defense in depth.
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

    # --- Configure scene PropertyGroup and call the operator ---
    scene = bpy.context.scene
    sp = scene.praxova_framing
    sp.wall_length_in = length_in
    sp.wall_height_in = height_in
    sp.wall_nominal = nominal
    sp.wall_spacing_oc_in = spacing_oc_in
    sp.wall_top_plate_count = top_plate_count
    sp.wall_bottom_plate_count = bottom_plate_count

    before = {o.name for o in scene.objects}
    result = bpy.ops.praxova.frame_wall('EXEC_DEFAULT')
    _check_op_result(result, "praxova.frame_wall")
    after = {o.name for o in scene.objects}
    new_names = sorted(after - before)

    # The operator sets the new Empty as the active object. Reposition
    # it if location_m was passed; children stay parented so they follow
    # the Empty without needing per-child updates.
    empty = bpy.context.view_layer.objects.active
    if empty is None:
        raise bridge.RPCError(
            bridge.INTERNAL_ERROR,
            "frame_wall finished but produced no active object",
        )
    if location is not None:
        empty.location = location

    # Stud count is deterministic from inputs - compute via
    # stud_positions rather than filtering child names by substring,
    # which would be fragile if the naming convention changes.
    n_studs = len(
        templates.stud_positions(length_in, spacing_oc_in, thickness_in),
    )
    n_plates = top_plate_count + bottom_plate_count

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
    "frame_wall": frame_wall,
    "generate_cutlist": generate_cutlist,
    "set_imperial_units": set_imperial_units,
}

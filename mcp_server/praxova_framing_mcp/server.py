"""Praxova Framing MCP server.

Exposes the in-Blender bridge as a set of MCP tools so an LLM client (Claude
Desktop, etc.) can place lumber, place sheets, place metal panels, duplicate
on-center, fill edge-to-edge, frame a wall with optional door and window
openings (v0.5.1), organize walls into Buildings and Levels with multi-wall
re-framing in place (v0.6.1 — joints + frame_building land in v0.6.2), and
generate cut lists in a live Blender session.

Configuration (env vars, read at startup):
    PRAXOVA_BRIDGE_HOST     default: 127.0.0.1
    PRAXOVA_BRIDGE_PORT     default: 9876

Each tool opens a fresh TCP connection to the bridge - stateless, robust to
bridge restarts. Latency over loopback is sub-millisecond, so the per-call
connection cost is irrelevant.
"""

from __future__ import annotations

import os
from typing import Literal

from mcp.server.fastmcp import FastMCP

from .client import BridgeClient, BridgeRPCError, BridgeUnavailableError


mcp = FastMCP("praxova-framing")


# ---------------------------------------------------------------------------
# Bridge plumbing
# ---------------------------------------------------------------------------

def _bridge_endpoint() -> tuple[str, int]:
    host = os.environ.get("PRAXOVA_BRIDGE_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("PRAXOVA_BRIDGE_PORT", "9876"))
    except ValueError as e:
        raise RuntimeError(
            f"PRAXOVA_BRIDGE_PORT is not a valid integer: "
            f"{os.environ.get('PRAXOVA_BRIDGE_PORT')!r}"
        ) from e
    return host, port


def _call(method: str, params: dict | None = None):
    """Send one JSON-RPC request, surface failures as informative errors.

    BridgeUnavailableError -> a clear "start the bridge" message, since
    that's the most common cause of trouble during real use.

    BridgeRPCError -> propagated; its str() already contains the bridge-
    side error message and any data payload (e.g. valid_lengths_ft) so
    the LLM agent has enough to self-correct.
    """
    host, port = _bridge_endpoint()
    try:
        with BridgeClient(host, port) as cli:
            return cli.call(method, params)
    except BridgeUnavailableError as e:
        raise RuntimeError(
            f"Praxova Framing MCP bridge unavailable at {host}:{port}. "
            f"In Blender, click 'Start MCP Bridge' in the Praxova N-panel "
            f"(or run bpy.ops.praxova.start_bridge() in the Python console). "
            f"Underlying error: {e}"
        ) from e
    # BridgeRPCError intentionally propagates unwrapped.


# ===========================================================================
# Read-only context tools
# ===========================================================================

@mcp.tool()
def list_materials() -> dict:
    """List every material the add-on can place.

    Call this BEFORE add_lumber, add_sheet, or add_panel to discover valid
    options. Returns lumber types with their actual cross-sections and
    standard stock lengths, sheet sizes and (material, thickness)
    combinations with their actual thicknesses (these differ from the
    call-out per APA Performance Category standards), and metal panel
    sizes plus per-material profile height placeholders.

    Returns:
        lumber_types: dict mapping nominal (e.g. "2x4") to
            {actual_thickness_in, actual_width_in, lengths_ft}
        sheet_sizes: dict mapping size key (e.g. "4x8") to
            {width_in, length_in}
        sheet_thicknesses: list of {material, thickness_callout, actual_in}
        panel_sizes: dict mapping size key (e.g. "36x8") to
            {coverage_width_in, length_in}
        panel_materials: list of {material, label, profile_height_in}.
            profile_height_in is a generic placeholder (rib geometry
            varies widely by manufacturer); see README "Metal panels"
            section.
        orientations: list of valid orientation strings
    """
    return _call("list_materials")


@mcp.tool()
def list_objects(praxova_only: bool = True) -> dict:
    """List objects in the current Blender scene.

    Defaults to Praxova-managed pieces (v0.4 lumber/sheets/panels plus
    v0.6 Building/Level/Wall hierarchy Empties). Pass
    praxova_only=False to include every Object in the scene.

    Each entry's shape depends on its `category`:

      LUMBER, SHEET, PANEL (v0.4): name, category, label, orientation,
        location_m, dimensions_m, plus category-specific fields —
        nominal_size + length_in for LUMBER; sheet_material +
        sheet_thickness_callout + sheet_size_key for SHEET;
        panel_material + panel_size_key for PANEL.

      BUILDING (v0.6.1): name, category, location_m,
        default_corner_style, contained_level_names (sorted by
        level_index), level_count.

      LEVEL (v0.6.1): name, category, level_index, level_height_in,
        parent_building (name or None), contained_wall_names (sorted),
        wall_count, joints_count (full joint serialization is v0.6.2).

      WALL (v0.6.1): name, category, location_m, rotation_deg_z,
        parent_level (name or None), length_in, height_in, nominal,
        spacing_oc_in, top_plate_count, bottom_plate_count, openings
        (list of opening dicts in v0.5.1 wire format — so a wall
        returned here can be round-tripped back into frame_wall via
        wall_target= + openings=).

    Returns:
        count: number of objects in the result
        objects: list of object descriptions
    """
    return _call("list_objects", {"praxova_only": praxova_only})


@mcp.tool()
def get_scene_info() -> dict:
    """Get current Blender scene state.

    Returns the .blend file path (None if unsaved), the active unit
    system, the 3D cursor location, the active object name, and total
    object count. Useful for deciding whether to set imperial units, or
    to check where new pieces will be placed when location_m is omitted.

    Returns:
        blend_filepath: str or None
        scene_name: str
        unit_system: str (typically "IMPERIAL" or "METRIC")
        length_unit: str (e.g. "INCHES", "FEET", "METERS")
        cursor_location_m: [x, y, z] in meters (world space)
        active_object_name: str or None
        object_count: int
    """
    return _call("get_scene_info")


# ===========================================================================
# Material placement
# ===========================================================================

@mcp.tool()
def add_lumber(
    nominal: Literal[
        "1x2", "2x3", "2x4", "2x6", "2x8", "2x10", "2x12",
        "4x4", "4x6", "6x6",
    ],
    length_ft: int,
    orientation: Literal["VERTICAL", "HORIZONTAL"] = "VERTICAL",
    location_m: list[float] | None = None,
) -> dict:
    """Place one tagged dimensional lumber piece in the scene.

    Args:
        nominal: Nominal cross-section call-out. Geometry uses the
            actual planed dimensions (e.g. a "2x4" is actually 1.5"x3.5"),
            but the cut-list label uses the call-out so material orders
            match. See list_materials for available types and stock
            lengths. v0.3.1 added 1x2 (furring), 2x3 (interior partition),
            4x4 (post), and 4x6 (mid-weight beam) to the original
            2x4..2x12 + 6x6 set.
        length_ft: Length in feet. Must be a standard stock length for
            the chosen nominal - call list_materials first if uncertain.
            Common: 8, 10, 12, 14, 16. 4x6 and 6x6 also stock 20.
            1x2 is 8' only.
        orientation: VERTICAL = long axis along +Z (a stud);
            HORIZONTAL = long axis along +X (a plate, joist, header).
        location_m: Optional [x, y, z] in meters, world-space, of the
            min-corner origin. If omitted, the piece is placed at
            Blender's 3D cursor (preserves the human-driven workflow).

    Returns the placed object's metadata. The 'name' field is what to
    pass to duplicate_oc as target_name to spread an array of pieces.
    """
    params: dict = {
        "nominal": nominal,
        "length_ft": length_ft,
        "orientation": orientation,
    }
    if location_m is not None:
        params["location_m"] = location_m
    return _call("add_lumber", params)


@mcp.tool()
def add_sheet(
    material: Literal["PLYWOOD", "OSB"],
    thickness: Literal["1/2", "3/4"],
    size: Literal["4x8"] = "4x8",
    orientation: Literal["VERTICAL", "HORIZONTAL"] = "VERTICAL",
    location_m: list[float] | None = None,
) -> dict:
    """Place one tagged sheet good (plywood or OSB) in the scene.

    Args:
        material: PLYWOOD or OSB. Both come at 1/2" and 3/4" call-outs.
        thickness: APA Performance Category call-out, NOT actual thickness.
            1/2" plywood is 15/32" actual; 1/2" OSB is 7/16" actual;
            3/4" both are 23/32" actual. The cut-list label uses the
            call-out (matches material orders); geometry uses the actual.
        size: Sheet dimensions. Currently only 4x8 is supported.
        orientation: VERTICAL = standing up (long axis +Z, e.g. wall
            sheathing); HORIZONTAL = lying flat (long axis +X, e.g.
            subfloor or roof decking).
        location_m: Optional [x, y, z] world-space meters. If omitted,
            uses Blender's 3D cursor.

    Returns the placed object's metadata.
    """
    params: dict = {
        "material": material,
        "thickness": thickness,
        "size": size,
        "orientation": orientation,
    }
    if location_m is not None:
        params["location_m"] = location_m
    return _call("add_sheet", params)


@mcp.tool()
def add_panel(
    material: Literal["METAL"] = "METAL",
    size: Literal["36x8", "36x12", "36x16"] = "36x8",
    orientation: Literal["VERTICAL", "HORIZONTAL"] = "VERTICAL",
    location_m: list[float] | None = None,
) -> dict:
    """Place one tagged metal roofing or siding panel in the scene.

    Args:
        material: Currently only METAL. Real metal-panel rib geometry
            varies widely by manufacturer and profile (5V crimp ~0.5",
            AG/corrugated ~0.75", R-panel ~1.25", standing seam 1.5-3");
            v0.3 models all panels as flat slabs with a 0.75" generic
            profile placeholder. Layout (coverage width, length, count)
            is what matters for ordering and on-roof placement; rib
            geometry is cosmetic and will get its own generator later.
        size: Panel size as 'WIDTH_in x LENGTH_ft'. "36x8" = 36" wide
            (on-roof coverage width after side-seam overlap) by 8 feet
            long. Available: 36x8, 36x12, 36x16. Default 36x8.
        orientation: VERTICAL = standing tall (long axis +Z, e.g. wall
            siding panel); HORIZONTAL = lying flat (long axis +X). Most
            roof and wall installs are VERTICAL. Default VERTICAL.
        location_m: Optional [x, y, z] world-space meters at the
            min-corner origin. If omitted, uses Blender's 3D cursor.

    Returns the placed object's metadata.
    """
    params: dict = {
        "material": material,
        "size": size,
        "orientation": orientation,
    }
    if location_m is not None:
        params["location_m"] = location_m
    return _call("add_panel", params)


# ===========================================================================
# Duplication
# ===========================================================================

@mcp.tool()
def duplicate_oc(
    spacing_in: float,
    count: int,
    direction: Literal["LEFT", "RIGHT"] = "RIGHT",
    target_name: str | None = None,
) -> dict:
    """Duplicate an object on-center along its local X axis.

    For a vertical stud in default orientation, local X is the 1.5"
    thin axis - so this is the standard wall-spacing motion (16" OC,
    24" OC, etc). Each duplicate is its own Object (so the cut list
    is correct) but shares mesh data with the source for memory
    efficiency. Object-level tags are copied automatically.

    Args:
        spacing_in: On-center spacing in inches (e.g. 12.0, 16.0, 19.2,
            24.0). Common values: 12 (close stud), 16 (standard wall),
            19.2 (engineered floor truss), 24 (advanced framing). For
            timber/post framing pass the foot-equivalent in inches:
            96 = 8', 120 = 10'.
        count: Number of new pieces to create (1-500).
        direction: RIGHT = +local X; LEFT = -local X. Default RIGHT.
        target_name: Object to duplicate. Pass the 'name' returned by
            add_lumber/add_sheet/add_panel for deterministic chains.
            If omitted, uses Blender's currently active object.

    Returns a description of the duplication including the names of
    each new object.
    """
    params: dict = {
        "spacing_in": spacing_in,
        "count": count,
        "direction": direction,
    }
    if target_name is not None:
        params["target_name"] = target_name
    return _call("duplicate_oc", params)


@mcp.tool()
def duplicate_e2e(
    count: int,
    direction: Literal["FORWARD", "BACK"] = "FORWARD",
    target_name: str | None = None,
) -> dict:
    """Duplicate a sheet or panel edge-to-edge along its local Y axis.

    The Fill operator. Pick a source sheet or panel, get N copies marching
    along its local +Y (Forward) or -Y (Back) at edge-to-edge spacing.
    Use to sheathe a wall or cover a roof in one call.

    Spacing is automatic - it's the source's own width, retrieved from
    the tag (48" for a 4x8 sheet, 36" for a metal panel). If you need a
    specific span instead of a count, do `count = ceil(span_in / width)`
    where width comes from list_materials (sheet_sizes.width_in or
    panel_sizes.coverage_width_in). For custom-spaced arrays where the
    step isn't the source's own width (e.g. studs at 16" OC), use
    duplicate_oc with explicit spacing instead.

    Lumber is refused with INVALID_PARAMS: a 2x4's local-Y is 3.5" (its
    cross-section width), which isn't a meaningful fill spacing. The
    error message redirects to duplicate_oc.

    Args:
        count: Number of new pieces to create (1-500).
        direction: FORWARD = +local Y; BACK = -local Y. Default FORWARD.
        target_name: Source to duplicate. Pass the 'name' returned by
            add_sheet or add_panel. If omitted, uses Blender's currently
            active object - which must still be a sheet or panel.

    Returns:
        source: name of the source object
        width_in: the spacing that was actually used (so you can verify)
        count: matches input
        direction: matches input
        new_objects: sorted list of new object names
    """
    params: dict = {
        "count": count,
        "direction": direction,
    }
    if target_name is not None:
        params["target_name"] = target_name
    return _call("duplicate_e2e", params)


# ===========================================================================
# Building / Level containers (v0.6.1)
# ===========================================================================

@mcp.tool()
def add_building(
    name: str | None = None,
    location_m: list[float] | None = None,
    default_corner_style: Literal["THREE_STUD"] = "THREE_STUD",
) -> dict:
    """Create a Building Empty with a default Level child under it.

    The Building Empty is a grouping container with no geometry of its
    own. Walls land under a Level Empty (one is auto-created on the
    first add_building call; add more with add_level), so the typical
    flow is:

        add_building() -> {"building_name": "Building_01",
                           "level_name": "Level_01", ...}
        frame_wall(level="Level_01", length_in=120, height_in=96, ...)

    Args:
        name: Override the auto-generated Building_NN name. Must not
            collide with any existing scene object. Defaults to
            auto-numbered (Building_01, Building_02, ...).
        location_m: Optional [x, y, z] world-space meters for the
            Building Empty. The default Level + future child walls
            inherit this transform.
        default_corner_style: Default corner style used at L joints in
            this Building when the joint's own corner_style is AUTO.
            Only "THREE_STUD" is valid in v0.6.1 — v0.7 will add
            CALIFORNIA and LADDER_BLOCKING. The param is exposed now
            for forward-compat; passing "THREE_STUD" (or omitting it)
            gets you the v0.6 behavior.

    Returns:
        building_name: name of the new Building Empty
        level_name: name of the auto-created default Level child
        level_index: always 0 for the default Level
        location_m: echo of the Building's world location
        default_corner_style: echo of the resolved style
    """
    params: dict = {
        "default_corner_style": default_corner_style,
    }
    if name is not None:
        params["name"] = name
    if location_m is not None:
        params["location_m"] = location_m
    return _call("add_building", params)


@mcp.tool()
def add_level(
    building: str,
    name: str | None = None,
    level_height_in: float | None = None,
) -> dict:
    """Add a new Level under an existing Building.

    Levels are children of a Building; walls created via
    frame_wall(level=<this Level's name>, ...) land as children of the
    Level so they share the Building's transform and can be joined at
    corners. v0.6 only frames one Level at a time; multi-story support
    (multiple Levels actively framed in one orchestrator call) is
    v0.8+.

    Args:
        building: Name of the Building Empty to add the Level under.
            Must already exist and be a Praxova-managed Building
            (is_building=True). Create one via add_building first.
        name: Override the auto-generated Level_NN name. Must not
            collide with any existing scene object. Defaults to
            auto-numbered within this Building's children.
        level_height_in: Floor-to-floor reference height in inches.
            Defaults to the standard residential 8' (96"). Affects no
            geometry directly in v0.6 — it's metadata the framing
            heuristics in later cycles will use.

    Returns:
        level_name: name of the new Level Empty
        level_index: auto-assigned (one higher than the highest
            existing Level under this Building, starting at 0)
        building: echo of the input
        level_height_in: echo of the resolved value (defaults from
            the PraxovaLevelProps default when omitted)

    Raises APP_OBJECT_NOT_FOUND (-32004) when `building` doesn't
    resolve to a Praxova Building Empty in the scene. Raises
    INVALID_PARAMS (-32602) when `name` collides with an existing
    object or when `level_height_in` is non-positive.
    """
    params: dict = {"building": building}
    if name is not None:
        params["name"] = name
    if level_height_in is not None:
        params["level_height_in"] = level_height_in
    return _call("add_level", params)


# ===========================================================================
# Joint lifecycle (v0.6.2)
# ===========================================================================

@mcp.tool()
def add_joint(level_name: str, joint: dict) -> dict:
    """Append a new joint to a Praxova Level's joints collection.

    A joint connects two walls in the same Level at an L corner; the
    MAIN wall keeps plate continuity through the corner while the
    ABUTTING wall's plates are shortened by the main wall's wall
    thickness. frame_building reads these joints and re-frames every
    wall in the Level with the corner geometry applied.

    Args:
        level_name: Name of the Praxova Level Empty (created via
            add_building or add_level). Resolved against
            bpy.context.scene.objects; APP_OBJECT_NOT_FOUND (-32004)
            if missing, INVALID_PARAMS (-32602) if the named object
            isn't a Praxova Level.

        joint: dict carrying the wire-format joint spec:

            {
              "joint_type":      "L_CORNER",          # OPTIONAL,
                                                      #   default
                                                      #   "L_CORNER"
                                                      #   (only valid
                                                      #   in v0.6.x)
              "wall_a_name":     "Wall_01",           # REQUIRED;
                                                      #   MAIN wall
              "wall_b_name":     "Wall_02",           # REQUIRED;
                                                      #   ABUTTING wall
              "wall_a_end":      "END" | "START",     # REQUIRED
              "wall_b_end":      "END" | "START",     # REQUIRED
              "corner_style":    "AUTO" | "THREE_STUD",
                                                      # OPTIONAL,
                                                      #   default
                                                      #   "AUTO"
              "extending_wall":  "AUTO" | "A" | "B",  # OPTIONAL,
                                                      #   default
                                                      #   "AUTO"
                                                      #   (shorter
                                                      #   wall extends;
                                                      #   ties to A)
            }

          wall_a_name / wall_b_name must resolve to Praxova-managed
          wall Empties parented under `level_name` — cross-Level
          joints are out of scope. INVALID_PARAMS otherwise, with
          the message naming both the bad value AND the Level it
          was checked against so the LLM knows which param to fix.

    Returns:
        level_name: echo
        joint_index: 0-based index of the new joint in the Level's
            joints collection. Pass to remove_joint or use as the
            wire key for round-tripping via list_joints_in_level.
        joint: full filled spec — all six wire fields above with
            defaults made explicit, plus joint_index. Identical
            shape to list_joints_in_level entries.

    Known footgun — wall name brittleness:
        wall_a_name / wall_b_name are Object name strings, not
        stable PropertyGroup IDs. Renaming a wall in Blender
        invalidates any joint spec the LLM previously cached (the
        PointerProperty on the existing PraxovaJoint will follow
        the rename, but a fresh add_joint call with the old name
        will hit INVALID_PARAMS). Same brittleness as target_name
        in duplicate_oc / duplicate_e2e. Workaround: call
        list_joints_in_level to refresh the canonical names before
        further joint mutation.

    Implementation note: the bridge writes directly to
    level.praxova_level.joints (CollectionProperty.add + field
    assignment) rather than invoking bpy.ops.praxova.add_joint, so
    every field is set in one step. The UI op stays unchanged for
    human-driven "click + then fill fields" flows.
    """
    return _call("add_joint", {
        "level_name": level_name,
        "joint": joint,
    })


@mcp.tool()
def remove_joint(level_name: str, joint_index: int) -> dict:
    """Remove one joint from a Praxova Level by 0-based index.

    Returns the full pre-removal joint spec as an undo handle. If a
    caller deleted the wrong joint, calling add_joint with the
    `removed` dict from the response immediately puts it back — no
    scene-state caching required client-side.

    Args:
        level_name: Name of the Praxova Level Empty. Same resolution
            rules as add_joint (APP_OBJECT_NOT_FOUND if missing,
            INVALID_PARAMS if not a Praxova Level).
        joint_index: 0-based index into level.praxova_level.joints.
            Out of range -> INVALID_PARAMS with the current joint
            count in the message.

    Returns:
        level_name: echo
        joint_index: echo
        removed: the joint's full wire spec captured BEFORE removal:
            joint_index, joint_type, wall_a_name, wall_b_name,
            wall_a_end, wall_b_end, corner_style, extending_wall.
            Same shape add_joint accepts on the way in (minus the
            joint_index, which is reassigned on re-add).

    The Level's `joints_active` index is clamped to the new bounds
    after removal, matching the UI op (max(0, min(joints_active,
    len(joints) - 1))).
    """
    return _call("remove_joint", {
        "level_name": level_name,
        "joint_index": joint_index,
    })


# ===========================================================================
# Composite framing
# ===========================================================================

@mcp.tool()
def frame_wall(
    length_in: float | None = None,
    height_in: float | None = None,
    nominal: Literal[
        "1x2", "2x3", "2x4", "2x6", "2x8", "2x10", "2x12",
        "4x4", "4x6", "6x6",
    ] = "2x4",
    spacing_oc_in: float = 16.0,
    top_plate_count: int = 2,
    bottom_plate_count: int = 1,
    location_m: list[float] | None = None,
    openings: list[dict] | None = None,
    level: str | None = None,
    wall_target: str | None = None,
    rotation_deg_z: float | None = None,
) -> dict:
    """Frame a wall — CREATE a new one or REBUILD an existing one in place.

    Builds top plates, bottom plates, and studs for a single isolated
    wall, parented to a new Empty for one-handle transform. Sheathing-
    aligned stud layout: end studs flush with wall ends, intermediate
    studs at on-center spacing measured from x=0, the final bay tight
    when length isn't a multiple of spacing — preserves 4'/8' sheathing
    seam alignment.

    v0.5.1 adds the optional `openings` parameter — a list of door and
    window opening dicts. Each opening produces king studs, jack studs,
    a (2) 2x lumber + 1/2" plywood spacer header build-up, an optional
    rough sill (windows), and cripples above the header and below the
    rough sill. Regular OC studs that would collide with any king
    bracket are dropped automatically (so n_studs reports the survivors,
    not the raw OC count).

    Geometry conventions:
        +X = wall length, +Y = wall thickness, +Z = wall height.
        The Empty parent lands at world (0, 0, 0) by default; pass
        location_m to place it elsewhere. Children stay parented and
        follow the Empty - no per-child updates needed.

    Stock vs cut length: every cut piece is sourced from the smallest
    stock that fits. For an 8' wall with 1 bottom + 2 top plates of 2x4,
    studs are 91.5" cut from 96" (8 ft) stock. The returned
    stud_stock_in and plate_stock_in tell you what to order from the
    lumberyard. Jack, header, and cripple stock sizes follow the same
    rule and surface in the cut list.

    Args:
        length_in: Wall length along +X in inches. Must be > 0 and at
            least 2 × stud thickness so end studs don't overlap.
        height_in: Wall height (floor to top of top plate) in inches.
            Must leave room for at least some stud after the plate
            stack: height_in > (top_plate_count + bottom_plate_count)
            × thickness.
        nominal: Stud size from LUMBER_TYPES. All studs, kings, jacks,
            and cripples use this nominal; plates too. Default 2x4
            (US residential standard).
        spacing_oc_in: On-center stud spacing in inches. Default 16.0
            (residential standard). 24" is also common (commercial,
            advanced framing).
        top_plate_count: Number of top plates. Default 2 (US residential
            load-bearing standard); 1 for a non-load-bearing partition
            wall. Range 1-4.
        bottom_plate_count: Number of bottom plates. Default 1
            (standard). Range 1-4.
        location_m: Optional [x, y, z] world-space meters for the Empty
            parent. If omitted, the Empty lands at world origin and you
            transform it in Blender (or via a separate API call)
            afterward.
        openings: Optional list of door and window opening dicts. Each:

            {
              "type":            "door" | "window",      # REQUIRED
              "x_offset_in":     number >= 0,            # REQUIRED
              "ro_width_in":     number > 0,             # REQUIRED
              "ro_height_in":    number > 0,             # REQUIRED
              "sill_height_in":  number >= 0,            # REQUIRED for window,
                                                          #   optional for door
                                                          #   (default 0.0)
              "header_nominal":  "2x4" | "2x6" | ...,    # OPTIONAL; defaults
                                                          #   to wall `nominal`
              "jack_count":      1 | 2 | 3,              # OPTIONAL; defaults
                                                          #   to 2 if RO ≥ 72"
                                                          #   else 1
            }

            Field semantics:
              - type: "door" or "window" — lowercase on the wire.
              - x_offset_in: wall-left to RO-left in inches.
              - ro_width_in, ro_height_in: rough opening size in inches.
                ro_height_in is clear from rough sill top (or bottom plate
                top for doors) to header bottom.
              - sill_height_in: z-coord of the rough sill top measured
                from bottom of bottom plate. Required for windows; for
                doors any provided value is ignored (doors sit on the
                bottom plate).
              - header_nominal: defaults to the wall `nominal` — this
                default is GEOMETRIC, not structural. For real load spans
                see README "Header sizing" and IRC R602.7.
              - jack_count: 1 or 2 per side is conventional; defaults to
                2 for RO ≥ 72" per IRC R602.7 typical loading.

            Examples:

            Single 36"×80" door centered in a 96" wall:
              openings=[{
                "type": "door",
                "x_offset_in": 30.0,
                "ro_width_in": 36.0,
                "ro_height_in": 80.0,
              }]

            Door + window in the same wall (jack_count auto-derived,
            header_nominal defaults to "2x4"):
              openings=[
                {"type": "door",  "x_offset_in": 12.0,
                 "ro_width_in": 36.0, "ro_height_in": 82.0},
                {"type": "window", "x_offset_in": 60.0,
                 "ro_width_in": 36.0, "ro_height_in": 48.0,
                 "sill_height_in": 36.0},
              ]

            Validation: each opening dict is checked for required fields,
            types, and choice membership with 1-based opening indices in
            error messages ("Opening 2: ..."). Cross-field rules (within
            wall, no pairwise overlap, header fits under top plates,
            window sill clears bottom plate) run against the same
            validator the in-Blender N-panel preview uses, so an LLM
            agent and a human see identical failure modes.

    Returns:
        wall_name: name of the new Empty parent (e.g. "Wall_03")
        length_in, height_in, nominal, spacing_oc_in, top_plate_count,
            bottom_plate_count: echoes of input with defaults filled in
        n_studs: REGULAR OC stud count AFTER filtering around any king
            brackets. With openings, kings/jacks/cripples are counted
            separately in openings_summary below. With no openings, this
            matches the raw OC count.
        n_plates: top_plate_count + bottom_plate_count
        stud_length_in: cut length of each regular stud (height - plate
            stack)
        stud_stock_in, plate_stock_in: purchased stock the studs and
            plates are cut from (smallest standard length that fits)
        n_openings: always present (0 when openings omitted)
        openings_summary: always present (empty list when none). One dict
            per opening with the ACTUAL values used after default-fill:

              {
                "type":              "door" | "window",
                "jack_count":        int,
                "header_nominal":    str,
                "jack_length_in":    float,
                "header_length_in":  float,
                "n_header_cripples": int,  # 0 if cripple zone too short
                "n_sill_cripples":   int,  # 0 for doors
              }

        new_objects: sorted list of every new object name — the Empty,
            all plates, all regular studs, plus per-opening kings, jacks,
            two header members, the untagged 1/2" plywood spacer, an
            optional rough sill (windows), and any header / sill
            cripples.

    Raises INVALID_PARAMS (-32602) for impossible geometry: wall too
    short for two end studs, wall too short for the plate stack,
    stud/plate length exceeding any available stock for the chosen
    nominal, per-opening dict shape errors (with 1-based index), or
    cross-field opening errors (overlap, off-wall, header too tall,
    sill in plate).

    Building hierarchy and re-framing (v0.6.1):

      level: Name of a Praxova Level Empty (created via add_level
        and/or add_building). In CREATE mode the new wall is parented
        under this Level so it can later be joined with sibling walls
        in the same Level. In REBUILD mode, if `level` differs from
        the wall's current parent the wall is re-parented; joints in
        the OLD Level still reference the wall, so clean them up in
        Blender before re-parenting if that matters.

      wall_target: Name of a Praxova wall Empty (is_wall=True). When
        set, switches the tool to REBUILD mode: the wall's children
        are deleted and rebuilt, but the Empty itself (and its name,
        joint references, transform unless overridden) is preserved.
        Each scalar param you provide WRITES THROUGH to the wall's
        stored props; each one you omit preserves the existing value.
        length_in and height_in become OPTIONAL in this mode — omit
        them to keep the wall's current dimensions, supply them to
        change. Same for openings (omit = preserve, [] = clear,
        provided list = replace).

      rotation_deg_z: Z-axis rotation in degrees applied to the wall
        Empty. CREATE: 0 if omitted. REBUILD: preserves the wall's
        current rotation if omitted. **JOINTS LOCK ROTATION**: in
        REBUILD mode, if rotation_deg_z differs from the wall's
        current rotation AND the wall's parent Level has any joint
        referencing this wall, the call is REFUSED with
        INVALID_PARAMS. Remove the joint via the Joints UIList in
        Blender first, rotate, then re-add the joint and run
        frame_building (v0.6.2).

    The return shape gains three v0.6.1 fields alongside the existing
    ones: wall_target_used (bool — True if REBUILD), level_name (str
    or None — the wall's parent Level name), and rotation_deg_z (the
    wall Empty's final Z rotation in degrees).

    Worked example — build a wall under a Level, then edit it in place:

      add_building(name="HouseA")
      # -> {"building_name": "HouseA", "level_name": "Level_01", ...}
      frame_wall(level="Level_01", length_in=120, height_in=96,
                 nominal="2x4")
      # -> {"wall_name": "Wall_01", "level_name": "Level_01", ...,
      #     "wall_target_used": false}
      frame_wall(wall_target="Wall_01", length_in=144)
      # -> rebuilds Wall_01 in place at 144" length; height/nominal/
      #    openings preserved. {"wall_target_used": true,
      #    "wall_name": "Wall_01", "length_in": 144.0, ...}
    """
    params: dict = {
        "nominal": nominal,
        "spacing_oc_in": spacing_oc_in,
        "top_plate_count": top_plate_count,
        "bottom_plate_count": bottom_plate_count,
    }
    if length_in is not None:
        params["length_in"] = length_in
    if height_in is not None:
        params["height_in"] = height_in
    if location_m is not None:
        params["location_m"] = location_m
    if openings is not None:
        params["openings"] = openings
    if level is not None:
        params["level"] = level
    if wall_target is not None:
        params["wall_target"] = wall_target
    if rotation_deg_z is not None:
        params["rotation_deg_z"] = rotation_deg_z
    return _call("frame_wall", params)


# ===========================================================================
# Cut list
# ===========================================================================

@mcp.tool()
def generate_cutlist() -> dict:
    """Walk the scene, count tagged pieces by label, write the cut list.

    Output goes to two places:
      - Always: a Blender Text datablock named 'Praxova Cut List'
        (visible by switching an editor area to Text Editor).
      - If the .blend has been saved: a sidecar
        '<blendfile>_cutlist.txt' next to the .blend file.

    The body has up to three sections - LUMBER, SHEETS, PANELS - each
    listed alphabetically by canonical label, with subtotals when more
    than one section is populated, plus a grand total. As of v0.4 the
    LUMBER section renders as two subsections: CUT LIST (per-piece with
    a 'cut to N"' annotation when a piece is shorter than its stock) and
    ORDER SUMMARY (aggregated by stock SKU across orientations, with an
    orientation parenthetical for traceability) - what you take to the
    lumberyard.

    Errors with code -32003 if no Praxova-tagged material exists in the
    scene (place lumber, sheets, or panels first).

    Returns:
        text: full cut-list body as a string
        text_datablock: the in-Blender Text datablock name
        disk_path: path to the sidecar .txt, or None if the .blend
            hasn't been saved yet
    """
    return _call("generate_cutlist")


# ===========================================================================
# Units
# ===========================================================================

@mcp.tool()
def set_imperial_units() -> dict:
    """Switch the Blender scene to imperial (inches) units.

    Idempotent - safe to call when units are already imperial. Useful
    at the start of a fresh framing session. Use get_scene_info first
    if you want to skip this when already configured.

    Returns:
        unit_system: confirmed unit system after the change
        length_unit: confirmed length unit
    """
    return _call("set_imperial_units")

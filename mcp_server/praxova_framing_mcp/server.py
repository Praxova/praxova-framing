"""Praxova Framing MCP server.

Exposes the in-Blender bridge as a set of MCP tools so an LLM client (Claude
Desktop, etc.) can place lumber, place sheets, duplicate on-center, and
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

    Call this BEFORE add_lumber or add_sheet to discover valid options.
    Returns lumber types with their actual cross-sections and standard
    stock lengths, sheet sizes, and the valid (material, thickness)
    combinations with their actual thicknesses (these differ from the
    call-out per APA Performance Category standards).

    Returns:
        lumber_types: dict mapping nominal (e.g. "2x4") to
            {actual_thickness_in, actual_width_in, lengths_ft}
        sheet_sizes: dict mapping size key (e.g. "4x8") to
            {width_in, length_in}
        sheet_thicknesses: list of {material, thickness_callout, actual_in}
        orientations: list of valid orientation strings
    """
    return _call("list_materials")


@mcp.tool()
def list_objects(praxova_only: bool = True) -> dict:
    """List objects in the current Blender scene.

    Defaults to only Praxova-tagged pieces (lumber and sheets); pass
    praxova_only=False to include everything in the scene.

    Each Praxova object includes 'name' (use as target_name for
    duplicate_oc), 'category' ('LUMBER' or 'SHEET'), 'label', 'orientation',
    'location_m', 'dimensions_m', and category-specific fields like
    nominal_size for lumber or sheet_material for sheets.

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
    nominal: Literal["2x4", "2x6", "2x8", "2x10", "2x12", "6x6"],
    length_ft: int,
    orientation: Literal["VERTICAL", "HORIZONTAL"] = "VERTICAL",
    location_m: list[float] | None = None,
) -> dict:
    """Place one tagged dimensional lumber piece in the scene.

    Args:
        nominal: Nominal cross-section call-out. Geometry uses the
            actual planed dimensions (e.g. a "2x4" is actually 1.5"x3.5"),
            but the cut-list label uses the call-out so material orders
            match. See list_materials for available types.
        length_ft: Length in feet. Must be a standard stock length for
            the chosen nominal - call list_materials first if uncertain.
            Common: 8, 10, 12, 14, 16. 6x6 also stocks 20.
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
            19.2 (engineered floor truss), 24 (advanced framing).
        count: Number of new pieces to create (1-500).
        direction: RIGHT = +local X; LEFT = -local X. Default RIGHT.
        target_name: Object to duplicate. Pass the 'name' returned by
            add_lumber for deterministic chains. If omitted, uses
            Blender's currently active object.

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

    Errors with code -32003 if no Praxova-tagged material exists in the
    scene (place lumber or sheets first).

    Returns:
        text: full cut-list body as a string (LUMBER section, SHEETS
            section, grand total)
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

"""
Praxova Framing - construction modeling helper for Blender.

Provides tagged lumber templates (1x2 through 6x6), sheet goods (plywood
and OSB at 1/2" and 3/4"), metal roofing/siding panels (36" x 8/12/16 ft),
an on-center spacing duplicator, an edge-to-edge fill duplicator for
sheets and panels (v0.3.3), a 'frame a wall' composite operator (v0.4),
a cut-list generator, and (v0.3) a localhost JSON-RPC bridge so an
external MCP server can drive the same operators from an LLM agent.
"""

# PEP 8: module-level dunders go after the docstring and before any imports
# (except __future__). This is the canonical version for Python code -
# imported by server/handlers.py's ping() so the bridge doesn't carry its
# own copy. blender_manifest.toml is the canonical version for Blender's
# extension loader; the two must be bumped together each release.
__version__ = "0.6.60"

import os

import bpy
import bpy.utils.previews

from . import (
    properties,
    ops_add,
    ops_duplicate,
    ops_fill,
    ops_frame,
    ops_cutlist,
    ops_units,
    ui,
)
from . import server as _server  # v0.3: in-Blender MCP bridge


_registered_classes: list = []

# v0.6.25: custom-icon storage. bpy.utils.previews collections are
# the standard way to load PNGs as toolbar icons; their icon_id ints
# go to layout.operator(..., icon_value=<id>). Loaded in
# register_icons() before any panel draws, freed in unregister_icons()
# during module teardown.
_preview_collections: dict = {}


def register_icons():
    """Load custom icons from resources/ into a preview collection."""
    pcoll = bpy.utils.previews.new()
    icons_dir = os.path.join(os.path.dirname(__file__), "resources")
    pcoll.load(
        "imperial_unit",
        os.path.join(icons_dir, "imperial-unit.png"),
        'IMAGE',
    )
    _preview_collections["praxova"] = pcoll


def unregister_icons():
    """Release every preview collection. Safe to call at any teardown
    point — clears the module-level dict so a re-register starts
    clean."""
    for pcoll in _preview_collections.values():
        bpy.utils.previews.remove(pcoll)
    _preview_collections.clear()


def get_icon_id(name: str) -> int:
    """Return the icon_id for a previously-loaded custom icon, or 0
    if the named icon isn't loaded yet. UI callers fall back to a
    built-in icon when get_icon_id returns 0 — covers the brief
    window between module import and register_icons() running."""
    pcoll = _preview_collections.get("praxova")
    if pcoll is None:
        return 0
    return pcoll[name].icon_id


def register():
    global _registered_classes

    # v0.6.25: load custom icons FIRST so panel draws (which can
    # fire as soon as classes register) already have access via
    # get_icon_id.
    register_icons()

    static_classes = [
        # Property groups MUST register before anything that references them.
        # PraxovaWallOpening must register before PraxovaWallProps (v0.6) and
        # PraxovaSceneProps (v0.5) because both reference it via CollectionProperty.
        # PraxovaJoint registers before PraxovaLevelProps because Level holds
        # a CollectionProperty(type=PraxovaJoint). Both Building and Level
        # register before PraxovaSceneProps because the scene PointerProperty
        # fields (active_building, active_level) reference Object — those
        # accept any Object, but registering the concrete groups first keeps
        # the type registry consistent.
        properties.PraxovaLumberProps,
        properties.PraxovaWallOpening,
        properties.PraxovaWallProps,
        properties.PraxovaJoint,
        properties.PraxovaLevelProps,
        properties.PraxovaBuildingProps,
        properties.PraxovaSceneProps,
        # Operators.
        ops_add.PRAXOVA_OT_add_lumber,
        ops_add.PRAXOVA_OT_add_sheet,
        ops_add.PRAXOVA_OT_add_panel,
        ops_duplicate.PRAXOVA_OT_set_spacing,
        ops_duplicate.PRAXOVA_OT_duplicate_oc,
        # v0.3.3: Fill (edge-to-edge) operators.
        ops_fill.PRAXOVA_OT_set_fill_span,
        ops_fill.PRAXOVA_OT_duplicate_e2e,
        # v0.4: Composite framing operators.
        ops_frame.PRAXOVA_OT_frame_wall,
        # v0.6: Building / Level container operators, joint management,
        # and the multi-wall framing orchestrator.
        ops_frame.PRAXOVA_OT_add_building,
        ops_frame.PRAXOVA_OT_add_level,
        ops_frame.PRAXOVA_OT_add_joint,
        ops_frame.PRAXOVA_OT_remove_joint,
        ops_frame.PRAXOVA_OT_frame_building,
        ops_cutlist.PRAXOVA_OT_generate_cutlist,
        ops_units.PRAXOVA_OT_set_imperial_units,
        # v0.3: MCP bridge operators.
        _server.PRAXOVA_OT_start_bridge,
        _server.PRAXOVA_OT_stop_bridge,
        # v0.5: Wall opening operators + UIList. The four add/remove/
        # distribute operators and the UIList class must be registered
        # before the Wall Framing panel because the panel's draw()
        # references them by bl_idname (Blender resolves at draw time,
        # but registering ahead of the panel keeps the listing tidy).
        ui.PRAXOVA_OT_add_door,
        ui.PRAXOVA_OT_add_window,
        ui.PRAXOVA_OT_remove_opening,
        ui.PRAXOVA_OT_distribute_openings,
        ui.PRAXOVA_UL_openings,
        # v0.6: Joints UIList, registered before the Building panel for
        # the same reason.
        ui.PRAXOVA_UL_joints,
        # UI - parent submenu, sheets submenu, panels submenu, then the
        # two N-panel panels: Wall Framing (v0.5 single-wall, renamed
        # in v0.6 — class is PRAXOVA_PT_wall_framing, bl_idname stays
        # "PRAXOVA_PT_main_panel" so existing .blends keep panel state)
        # and Building (v0.6 multi-wall coordination).
        ui.PRAXOVA_MT_add_lumber_submenu,
        ui.PRAXOVA_MT_sheets_submenu,
        ui.PRAXOVA_MT_panels_submenu,
        ui.PRAXOVA_PT_wall_framing,
        ui.PRAXOVA_PT_building,
        # v0.6: MCP Bridge moved to its own panel — global add-on
        # capability, always visible regardless of Building/Level state.
        ui.PRAXOVA_PT_mcp_bridge,
    ]

    # Per-size submenus generated from the lumber type table so adding a new
    # nominal size is a one-row data change, not a UI rewrite.
    size_menus = ui.create_size_menu_classes()

    _registered_classes = static_classes + size_menus

    for cls in _registered_classes:
        bpy.utils.register_class(cls)

    # Attach our PropertyGroups to the relevant ID types.
    bpy.types.Object.praxova_lumber = bpy.props.PointerProperty(
        type=properties.PraxovaLumberProps,
    )
    # v0.6: every Object carries praxova_wall, praxova_level, and
    # praxova_building pointers. The respective is_* discriminator on each
    # group distinguishes Praxova-managed containers from arbitrary
    # Objects (an Object with all three is_* flags False is just a normal
    # scene Object that happens to carry the unused pointers, the
    # standard Blender pattern for PointerProperty attached to ID types).
    bpy.types.Object.praxova_wall = bpy.props.PointerProperty(
        type=properties.PraxovaWallProps,
    )
    bpy.types.Object.praxova_level = bpy.props.PointerProperty(
        type=properties.PraxovaLevelProps,
    )
    bpy.types.Object.praxova_building = bpy.props.PointerProperty(
        type=properties.PraxovaBuildingProps,
    )
    bpy.types.Scene.praxova_framing = bpy.props.PointerProperty(
        type=properties.PraxovaSceneProps,
    )

    # Hook our submenu into the 3D Viewport's Add menu.
    bpy.types.VIEW3D_MT_add.append(ui.add_to_add_menu)


def unregister():
    # v0.3: ensure the bridge is stopped before tearing the module down,
    # otherwise the listener thread keeps a stale reference to a defunct
    # version of the module after a reload.
    _server.bridge.stop()

    bpy.types.VIEW3D_MT_add.remove(ui.add_to_add_menu)

    del bpy.types.Object.praxova_lumber
    del bpy.types.Object.praxova_wall
    del bpy.types.Object.praxova_level
    del bpy.types.Object.praxova_building
    del bpy.types.Scene.praxova_framing

    for cls in reversed(_registered_classes):
        bpy.utils.unregister_class(cls)
    _registered_classes.clear()

    # v0.6.25: free custom-icon preview collections LAST so any
    # in-flight panel draw triggered by class unregistration can
    # still resolve icon_ids without crashing.
    unregister_icons()

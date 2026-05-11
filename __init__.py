"""
Praxova Framing - construction modeling helper for Blender.

Provides tagged lumber templates (1x2 through 6x6), sheet goods (plywood
and OSB at 1/2" and 3/4"), metal roofing/siding panels (36" x 8/12/16 ft),
an on-center spacing duplicator, an edge-to-edge fill duplicator for
sheets and panels (v0.3.3), a cut-list generator, and (v0.3) a localhost
JSON-RPC bridge so an external MCP server can drive the same operators
from an LLM agent.
"""

import bpy

from . import (
    properties,
    ops_add,
    ops_duplicate,
    ops_fill,
    ops_cutlist,
    ops_units,
    ui,
)
from . import server as _server  # v0.3: in-Blender MCP bridge


_registered_classes: list = []


def register():
    global _registered_classes

    static_classes = [
        # Property groups MUST register before anything that references them.
        properties.PraxovaLumberProps,
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
        ops_cutlist.PRAXOVA_OT_generate_cutlist,
        ops_units.PRAXOVA_OT_set_imperial_units,
        # v0.3: MCP bridge operators.
        _server.PRAXOVA_OT_start_bridge,
        _server.PRAXOVA_OT_stop_bridge,
        # UI - parent submenu, sheets submenu, panels submenu, main panel.
        ui.PRAXOVA_MT_add_lumber_submenu,
        ui.PRAXOVA_MT_sheets_submenu,
        ui.PRAXOVA_MT_panels_submenu,
        ui.PRAXOVA_PT_main_panel,
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
    del bpy.types.Scene.praxova_framing

    for cls in reversed(_registered_classes):
        bpy.utils.unregister_class(cls)
    _registered_classes.clear()

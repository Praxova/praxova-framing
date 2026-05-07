"""
Praxova Framing - construction modeling helper for Blender.

Provides tagged lumber templates (2x4 through 2x12, 6x6) and sheet goods
(plywood and OSB at 1/2" and 3/4"), an on-center spacing duplicator, and a
cut-list generator. All placed material is tagged via a registered
PropertyGroup, so duplicates inherit the tag automatically and the cut list
is a simple Counter over scene objects.
"""

import bpy

from . import properties, ops_add, ops_duplicate, ops_cutlist, ops_units, ui


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
        ops_duplicate.PRAXOVA_OT_set_spacing,
        ops_duplicate.PRAXOVA_OT_duplicate_oc,
        ops_cutlist.PRAXOVA_OT_generate_cutlist,
        ops_units.PRAXOVA_OT_set_imperial_units,
        # UI - parent submenu, sheets submenu, main panel.
        ui.PRAXOVA_MT_add_lumber_submenu,
        ui.PRAXOVA_MT_sheets_submenu,
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
    bpy.types.VIEW3D_MT_add.remove(ui.add_to_add_menu)

    del bpy.types.Object.praxova_lumber
    del bpy.types.Scene.praxova_framing

    for cls in reversed(_registered_classes):
        bpy.utils.unregister_class(cls)
    _registered_classes.clear()

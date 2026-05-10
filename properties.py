"""PropertyGroups for object tagging and scene-level UI state.

In Blender 5.0+ the legacy dict-style custom properties (obj["foo"] = ...) are
deprecated for add-on use. The proper pattern is to register a PropertyGroup
and attach it via PointerProperty - which is what this module does.
"""

import bpy
from bpy.props import (
    BoolProperty,
    StringProperty,
    IntProperty,
    FloatProperty,
    EnumProperty,
)


class PraxovaLumberProps(bpy.types.PropertyGroup):
    """Per-object tag identifying a Praxova-managed material.

    Attached to bpy.types.Object via PointerProperty in __init__.register().
    Survives obj.copy() automatically, so duplicates remain tagged for
    cut-list generation without any extra bookkeeping.

    The class name is kept as 'PraxovaLumberProps' for backward compatibility
    with v0.1 scene data, but it now covers both lumber and sheet goods via
    the 'category' enum.
    """

    is_lumber: BoolProperty(  # noqa: F821
        name="Is Praxova Material",
        description="Marks this object as Praxova-managed material",
        default=False,
    )
    category: EnumProperty(  # noqa: F821
        name="Category",
        description="Material category",
        items=[
            ('LUMBER', "Lumber", "Dimensional lumber or post"),
            ('SHEET',  "Sheet",  "Sheet good (plywood, OSB)"),
        ],
        default='LUMBER',
    )

    # --- Lumber-specific fields (used when category == 'LUMBER') ---
    nominal_size: StringProperty(  # noqa: F821
        name="Nominal Size",
        description='Nominal cross-section, e.g. "2x4" or "6x6"',
        default="",
    )
    length_in: IntProperty(  # noqa: F821
        name="Length (inches)",
        description="Length of this lumber piece in inches",
        default=0,
    )

    # --- Sheet-specific fields (used when category == 'SHEET') ---
    sheet_material: EnumProperty(  # noqa: F821
        name="Sheet Material",
        items=[
            ('PLYWOOD', "Plywood", ""),
            ('OSB',     "OSB",     ""),
        ],
        default='PLYWOOD',
    )
    sheet_thickness_callout: StringProperty(  # noqa: F821
        name="Thickness Call-out",
        description='Nominal thickness call-out, e.g. "1/2" or "3/4"',
        default="",
    )
    sheet_size_key: StringProperty(  # noqa: F821
        name="Sheet Size",
        description='Sheet size key, e.g. "4x8"',
        default="",
    )

    # --- Common fields ---
    orientation: EnumProperty(  # noqa: F821
        name="Orientation",
        description="Long-axis orientation",
        items=[
            ('VERTICAL',   "Vertical",   "Long axis along Z (stud / standing sheet)"),
            ('HORIZONTAL', "Horizontal", "Long axis along X (plate / flat sheet)"),
        ],
        default='VERTICAL',
    )
    cutlist_label: StringProperty(  # noqa: F821
        name="Cut List Label",
        description="Denormalized label used for grouping in the cut list",
        default="",
    )


class PraxovaSceneProps(bpy.types.PropertyGroup):
    """Scene-level UI state for the N-panel."""

    spacing_in: FloatProperty(  # noqa: F821
        name="Spacing (in)",
        description="On-center spacing in inches",
        default=16.0,
        min=0.001,
        soft_max=48.0,
        precision=2,
    )
    count: IntProperty(  # noqa: F821
        name="Count",
        description="Number of duplicates to create",
        default=5,
        min=1,
        max=500,
    )
    direction: EnumProperty(  # noqa: F821
        name="Direction",
        description="Duplicate along positive (right) or negative (left) local X",
        items=[
            ('RIGHT', "Right", "Duplicate along +local X"),
            ('LEFT',  "Left",  "Duplicate along -local X"),
        ],
        default='RIGHT',
    )

    # --- v0.3: MCP bridge ---
    # The bridge running-state is intentionally NOT a PropertyGroup field;
    # it's transient process state and lives in server/bridge.py. Only the
    # user-configured port lives here, since it's a UI input.
    bridge_port: IntProperty(  # noqa: F821
        name="Bridge Port",
        description="TCP port for the local MCP bridge (127.0.0.1 only)",
        default=9876,
        min=1024,
        max=65535,
    )

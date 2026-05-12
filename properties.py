"""PropertyGroups for object tagging and scene-level UI state.

In Blender 5.0+ the legacy dict-style custom properties (obj["foo"] = ...) are
deprecated for add-on use. The proper pattern is to register a PropertyGroup
and attach it via PointerProperty - which is what this module does.
"""

from math import ceil

import bpy
from bpy.props import (
    BoolProperty,
    StringProperty,
    IntProperty,
    FloatProperty,
    EnumProperty,
)

from . import templates


# ---------------------------------------------------------------------------
# Update callbacks
# ---------------------------------------------------------------------------

def _on_fill_span_change(self, context):
    """Auto-compute fill_count = ceil(fill_span_in / width) for the active obj.

    Runs whenever fill_span_in changes (preset button press, manual edit).
    Silent no-op when no Praxova SHEET or PANEL is active - the user is
    free to type a span first and select the source after, in which case
    they'll need to nudge the span to re-fire this callback.

    Writes via the dict-style assignment (`self["fill_count"] = ...`) rather
    than attribute assignment to avoid going through Blender's property
    setter machinery, which can interact poorly with UI redraws when the
    callback chain gets long.
    """
    obj = context.active_object
    if obj is None:
        return
    width_in = templates.fill_axis_width_in(obj)
    if width_in <= 0:
        return
    # IntProperty bounds clamp - protects against absurd typed spans.
    self["fill_count"] = int(max(1, min(500, ceil(self.fill_span_in / width_in))))


# ---------------------------------------------------------------------------
# Object tag
# ---------------------------------------------------------------------------

class PraxovaLumberProps(bpy.types.PropertyGroup):
    """Per-object tag identifying a Praxova-managed material.

    Attached to bpy.types.Object via PointerProperty in __init__.register().
    Survives obj.copy() automatically, so duplicates remain tagged for
    cut-list generation without any extra bookkeeping.

    The class name is kept as 'PraxovaLumberProps' for backward compatibility
    with v0.1 scene data, but it now covers lumber, sheet goods, and panels
    via the 'category' enum.
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
            ('PANEL',  "Panel",  "Panel (metal roofing or siding)"),
        ],
        default='LUMBER',
    )

    # --- Lumber-specific fields (used when category == 'LUMBER') ---
    nominal_size: StringProperty(  # noqa: F821
        name="Nominal Size",
        description='Nominal cross-section, e.g. "2x4" or "6x6"',
        default="",
    )
    length_in: FloatProperty(  # noqa: F821
        name="Length (inches)",
        description=(
            "Final cut length of this lumber piece in inches. For pieces "
            "used at full stock length (e.g. via add_lumber) this equals "
            "stock_length_in. For pieces cut down by a composite operator "
            "(e.g. studs from frame_wall) this is the cut dimension."
        ),
        default=0.0,
        precision=4,
    )
    stock_length_in: FloatProperty(  # noqa: F821
        name="Stock Length (inches)",
        description=(
            "Length of the purchased stock this piece is cut from, in "
            "inches. Drives the cut list's ORDER SUMMARY aggregation. "
            "Defaults to 0.0 for v0.3.x-era objects that pre-date this "
            "field; the cut list treats 0 as 'no explicit stock, treat as "
            "equal to length_in (no cut)'."
        ),
        default=0.0,
        precision=4,
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

    # --- Panel-specific fields (used when category == 'PANEL') ---
    panel_material: EnumProperty(  # noqa: F821
        name="Panel Material",
        items=[
            ('METAL', "Metal", "Metal roofing or siding panel"),
        ],
        default='METAL',
    )
    panel_size_key: StringProperty(  # noqa: F821
        name="Panel Size",
        description='Panel size key, e.g. "36x8" (coverage width in inches x length in feet)',
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


# ---------------------------------------------------------------------------
# Scene state
# ---------------------------------------------------------------------------

class PraxovaSceneProps(bpy.types.PropertyGroup):
    """Scene-level UI state for the N-panel."""

    # --- OC duplicator (existing) ---
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

    # --- Fill / edge-to-edge duplicator (v0.3.3) ---
    # fill_span_in is a UI helper; its update callback recomputes fill_count
    # from the active object's width. The operator uses fill_count directly,
    # so editing fill_count is the authoritative override.
    fill_span_in: FloatProperty(  # noqa: F821
        name="Fill Length (in)",
        description="Target span to cover. Auto-computes Fill Count from "
                    "the active object's width. Edit Fill Count after to "
                    "override the auto-computed value.",
        default=192.0,  # 16 ft - common wall span
        min=1.0,
        soft_max=1200.0,  # 100 ft soft cap
        precision=2,
        update=_on_fill_span_change,
    )
    fill_count: IntProperty(  # noqa: F821
        name="Fill Count",
        description="Number of edge-to-edge duplicates to create",
        default=4,  # 16ft / 48" = 4 for a 4x8 sheet
        min=1,
        max=500,
    )
    fill_direction: EnumProperty(  # noqa: F821
        name="Fill Direction",
        description="Duplicate edge-to-edge along +local Y (forward) or -local Y (back)",
        items=[
            ('FORWARD', "Forward", "Duplicate along +local Y"),
            ('BACK',    "Back",    "Duplicate along -local Y"),
        ],
        default='FORWARD',
    )

    # --- Wall framing (v0.4) ---
    # Drives the frame_wall composite operator. Geometry convention: the
    # bottom-front-left corner of the framed wall lands at world origin
    # (an Empty parent at that position); the user transforms the parent
    # afterward to place the wall in the larger model. Cross-field
    # validation (height must leave room for at least some stud given the
    # plate stack) lives in the operator's execute(), not here, because
    # PropertyGroup bounds can't reference other fields.
    wall_length_in: FloatProperty(  # noqa: F821
        name="Wall Length (in)",
        description="Wall length along +X in inches",
        default=96.0,  # 8 ft
        min=12.0,
        soft_max=1200.0,  # 100 ft soft cap
        precision=2,
    )
    wall_height_in: FloatProperty(  # noqa: F821
        name="Wall Height (in)",
        description="Wall height (floor to top of top plate) in inches",
        default=96.0,  # 8 ft
        min=12.0,
        soft_max=240.0,  # 20 ft soft cap (high-ceiling great room)
        precision=2,
    )
    # wall_nominal items are derived from templates.LUMBER_TYPES at class
    # definition time, so the dropdown stays in sync with the catalog. The
    # dict's small-to-large insertion order is preserved (Python 3.7+),
    # matching the existing Add menu order.
    wall_nominal: EnumProperty(  # noqa: F821
        name="Stud Size",
        description="Dimensional lumber size used for studs and plates",
        items=[
            (nominal, nominal, f"{nominal} dimensional lumber")
            for nominal in templates.LUMBER_TYPES
        ],
        default='2x4',
    )
    wall_spacing_oc_in: FloatProperty(  # noqa: F821
        name="Stud Spacing OC (in)",
        description="On-center stud spacing in inches (typically 16 or 24)",
        default=16.0,
        min=0.001,
        soft_max=48.0,
        precision=2,
    )
    wall_top_plate_count: IntProperty(  # noqa: F821
        name="Top Plate Count",
        description="Number of top plates (2 for load-bearing, 1 for partition)",
        default=2,
        min=1,
        max=4,
    )
    wall_bottom_plate_count: IntProperty(  # noqa: F821
        name="Bottom Plate Count",
        description="Number of bottom plates (typically 1)",
        default=1,
        min=1,
        max=4,
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

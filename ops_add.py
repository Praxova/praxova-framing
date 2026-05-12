"""Operators: add a tagged lumber piece, sheet good, or panel at the 3D cursor."""

import bpy
from bpy.props import StringProperty, IntProperty, EnumProperty

from . import templates


def _select_only(context, obj):
    """Deselect everything, then select obj and make it active."""
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


# ===========================================================================
# Lumber
# ===========================================================================

class PRAXOVA_OT_add_lumber(bpy.types.Operator):
    """Add a Praxova-tagged lumber piece of the specified size and orientation.

    Geometry convention:
        VERTICAL  -> long axis = +Z. Dimensions: (thickness, width, length).
        HORIZONTAL-> long axis = +X. Dimensions: (length, width, thickness).
    Origin is at the (0, 0, 0) min corner of the bounding box.

    Mesh datablocks are shared across all instances of the same template
    (linked data). Each Object still owns its own custom properties, so
    sharing meshes does not break cut-list tagging.

    Stock vs cut semantics (v0.4):
        add_lumber places a piece of purchased stock as-is, with no cut, so
        stock_length_in == length_in. Composite operators that cut pieces
        down from longer stock (e.g. frame_wall) set these differently;
        the cut list's two-section output uses both fields.
    """

    bl_idname = "praxova.add_lumber"
    bl_label = "Add Lumber"
    bl_description = "Add a tagged lumber piece at the 3D cursor"
    bl_options = {'REGISTER', 'UNDO'}

    nominal: StringProperty(  # noqa: F821
        name="Nominal Size",
        default="2x4",
    )
    length_ft: IntProperty(  # noqa: F821
        name="Length (ft)",
        default=8,
        min=1,
        max=24,
    )
    orientation: EnumProperty(  # noqa: F821
        name="Orientation",
        items=[
            ('VERTICAL',   "Vertical",   "Long axis along Z"),
            ('HORIZONTAL', "Horizontal", "Long axis along X"),
        ],
        default='VERTICAL',
    )

    def execute(self, context):
        if self.nominal not in templates.LUMBER_TYPES:
            self.report({'ERROR'}, f"Unknown lumber type: {self.nominal}")
            return {'CANCELLED'}

        thickness, width = templates.LUMBER_TYPES[self.nominal]  # inches
        length_in = self.length_ft * 12

        if self.orientation == 'VERTICAL':
            dims_in = (thickness, width, length_in)
        else:
            dims_in = (length_in, width, thickness)

        label = templates.lumber_cutlist_label(
            self.nominal, self.length_ft, self.orientation,
        )
        mesh_name = f"praxova_mesh_{label.replace(' ', '_')}"

        mesh = bpy.data.meshes.get(mesh_name)
        if mesh is None:
            mesh = templates.make_box_mesh(mesh_name, dims_in)

        obj = bpy.data.objects.new(label, mesh)
        obj.location = context.scene.cursor.location

        tag = obj.praxova_lumber
        tag.is_lumber = True
        tag.category = 'LUMBER'
        tag.nominal_size = self.nominal
        tag.length_in = float(length_in)
        # add_lumber places stock as-is: no cut, so stock equals cut length.
        # Set explicitly rather than relying on the cut list's v0.3.x
        # fallback (stock_length_in == 0 -> treat as length_in).
        tag.stock_length_in = float(length_in)
        tag.orientation = self.orientation
        tag.cutlist_label = label

        context.collection.objects.link(obj)
        _select_only(context, obj)
        return {'FINISHED'}


# ===========================================================================
# Sheet goods
# ===========================================================================

class PRAXOVA_OT_add_sheet(bpy.types.Operator):
    """Add a Praxova-tagged sheet good (plywood or OSB).

    Geometry convention (matches lumber):
        VERTICAL  -> long axis = +Z. (thickness, width, length).
                     A 4x8 sheet stands tall: X=thickness, Y=48", Z=96".
        HORIZONTAL-> long axis = +X. (length, width, thickness).
                     A 4x8 sheet lies flat: X=96", Y=48", Z=thickness.

    Actual thickness comes from templates.SHEET_THICKNESS_ACTUAL, which
    encodes the APA Performance Category standard (1/2" plywood = 15/32",
    1/2" OSB = 7/16", 3/4" both = 23/32"). The cut-list label uses the
    call-out, not the actual, so it matches material orders.
    """

    bl_idname = "praxova.add_sheet"
    bl_label = "Add Sheet"
    bl_description = "Add a tagged sheet good (plywood or OSB) at the 3D cursor"
    bl_options = {'REGISTER', 'UNDO'}

    material: EnumProperty(  # noqa: F821
        name="Material",
        items=[
            ('PLYWOOD', "Plywood", ""),
            ('OSB',     "OSB",     ""),
        ],
        default='PLYWOOD',
    )
    thickness: EnumProperty(  # noqa: F821
        name="Thickness",
        items=[
            ('1/2', '1/2"', 'Half-inch performance category'),
            ('3/4', '3/4"', 'Three-quarter-inch performance category'),
        ],
        default='1/2',
    )
    size: EnumProperty(  # noqa: F821
        name="Size",
        items=[
            ('4x8', "4x8 ft (48\" x 96\")", ""),
        ],
        default='4x8',
    )
    orientation: EnumProperty(  # noqa: F821
        name="Orientation",
        items=[
            ('VERTICAL',   "Vertical",   "Standing: long axis along Z"),
            ('HORIZONTAL', "Horizontal", "Flat: long axis along X"),
        ],
        default='VERTICAL',
    )

    def execute(self, context):
        if self.size not in templates.SHEET_SIZES:
            self.report({'ERROR'}, f"Unknown sheet size: {self.size}")
            return {'CANCELLED'}

        actual_key = (self.material, self.thickness)
        if actual_key not in templates.SHEET_THICKNESS_ACTUAL:
            self.report({'ERROR'},
                        f"No actual thickness defined for {self.material} {self.thickness}\"")
            return {'CANCELLED'}

        width_in, length_in = templates.SHEET_SIZES[self.size]
        thickness_in = templates.SHEET_THICKNESS_ACTUAL[actual_key]

        if self.orientation == 'VERTICAL':
            # Standing sheet: X=thickness, Y=width(48"), Z=length(96")
            dims_in = (thickness_in, width_in, length_in)
        else:
            # Flat sheet: X=length(96"), Y=width(48"), Z=thickness
            dims_in = (length_in, width_in, thickness_in)

        label = templates.sheet_cutlist_label(
            self.material, self.thickness, self.size, self.orientation,
        )
        # Mesh name: stable across instances so they share data.
        # Slashes and quotes can't appear in datablock names; use a safe form.
        safe = (label.replace('/', '_').replace('"', '').replace(' ', '_'))
        mesh_name = f"praxova_mesh_{safe}"

        mesh = bpy.data.meshes.get(mesh_name)
        if mesh is None:
            mesh = templates.make_box_mesh(mesh_name, dims_in)

        # Object name can't contain quotes either, but / is fine.
        obj_name = label.replace('"', '')
        obj = bpy.data.objects.new(obj_name, mesh)
        obj.location = context.scene.cursor.location

        tag = obj.praxova_lumber
        tag.is_lumber = True
        tag.category = 'SHEET'
        tag.sheet_material = self.material
        tag.sheet_thickness_callout = self.thickness
        tag.sheet_size_key = self.size
        tag.orientation = self.orientation
        tag.cutlist_label = label

        context.collection.objects.link(obj)
        _select_only(context, obj)
        return {'FINISHED'}


# ===========================================================================
# Panels (metal roofing / siding)
# ===========================================================================

class PRAXOVA_OT_add_panel(bpy.types.Operator):
    """Add a Praxova-tagged panel (metal roofing or siding).

    Geometry convention (matches lumber and sheets):
        VERTICAL  -> long axis = +Z. (profile_height, width, length).
                     A 36" x 8' panel stands tall: X=0.75", Y=36", Z=96".
        HORIZONTAL-> long axis = +X. (length, width, profile_height).

    Profile height comes from templates.PANEL_MATERIAL_PROFILE - a single
    generic placeholder per material in v0.3.1. A future patch will replace
    make_box_mesh here with a proper corrugation generator without changing
    this operator's interface.
    """

    bl_idname = "praxova.add_panel"
    bl_label = "Add Panel"
    bl_description = "Add a tagged metal roofing/siding panel at the 3D cursor"
    bl_options = {'REGISTER', 'UNDO'}

    material: EnumProperty(  # noqa: F821
        name="Material",
        items=[
            ('METAL', "Metal", "Metal roofing or siding panel"),
        ],
        default='METAL',
    )
    size: EnumProperty(  # noqa: F821
        name="Size",
        items=[
            ('36x8',  "36\" x 8'",  "36-inch wide, 8 feet long"),
            ('36x12', "36\" x 12'", "36-inch wide, 12 feet long"),
            ('36x16', "36\" x 16'", "36-inch wide, 16 feet long"),
        ],
        default='36x8',
    )
    orientation: EnumProperty(  # noqa: F821
        name="Orientation",
        items=[
            ('VERTICAL',   "Vertical",   "Standing: long axis along Z"),
            ('HORIZONTAL', "Horizontal", "Flat: long axis along X"),
        ],
        default='VERTICAL',
    )

    def execute(self, context):
        if self.size not in templates.PANEL_SIZES:
            self.report({'ERROR'}, f"Unknown panel size: {self.size}")
            return {'CANCELLED'}

        if self.material not in templates.PANEL_MATERIAL_PROFILE:
            self.report({'ERROR'}, f"Unknown panel material: {self.material}")
            return {'CANCELLED'}

        width_in, length_in = templates.PANEL_SIZES[self.size]
        profile_h_in = templates.PANEL_MATERIAL_PROFILE[self.material]

        if self.orientation == 'VERTICAL':
            # Standing panel: X=profile_height, Y=coverage_width, Z=length
            dims_in = (profile_h_in, width_in, length_in)
        else:
            # Flat panel: X=length, Y=coverage_width, Z=profile_height
            dims_in = (length_in, width_in, profile_h_in)

        label = templates.panel_cutlist_label(
            self.material, self.size, self.orientation,
        )
        safe = label.replace('"', '').replace(' ', '_')
        mesh_name = f"praxova_mesh_{safe}"

        mesh = bpy.data.meshes.get(mesh_name)
        if mesh is None:
            mesh = templates.make_box_mesh(mesh_name, dims_in)

        obj_name = label.replace('"', '')
        obj = bpy.data.objects.new(obj_name, mesh)
        obj.location = context.scene.cursor.location

        tag = obj.praxova_lumber
        tag.is_lumber = True
        tag.category = 'PANEL'
        tag.panel_material = self.material
        tag.panel_size_key = self.size
        tag.orientation = self.orientation
        tag.cutlist_label = label

        context.collection.objects.link(obj)
        _select_only(context, obj)
        return {'FINISHED'}

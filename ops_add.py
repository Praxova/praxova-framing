"""Operators: add a tagged lumber piece or sheet good at the 3D cursor."""

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
        tag.length_in = length_in
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

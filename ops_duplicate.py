"""Operators: on-center spacing duplication."""

import bpy
from bpy.props import FloatProperty
from mathutils import Vector  # noqa: F401  -- used in type hints

from . import templates


class PRAXOVA_OT_set_spacing(bpy.types.Operator):
    """Internal helper: apply a preset spacing value (used by preset buttons)."""

    bl_idname = "praxova.set_spacing"
    bl_label = "Set Spacing"
    bl_options = {'INTERNAL', 'UNDO'}

    spacing: FloatProperty(default=16.0)  # noqa: F821

    def execute(self, context):
        context.scene.praxova_framing.spacing_in = self.spacing
        return {'FINISHED'}


class PRAXOVA_OT_duplicate_oc(bpy.types.Operator):
    """Duplicate the active object on-center along its local X axis.

    Each duplicate is a new Object that shares the source's mesh data
    (linked); object-level custom properties are copied via obj.copy(), so
    every duplicate carries the same cut-list tag automatically.

    Direction is taken from the active object's local +X (Right) or -X (Left)
    axis expressed in world space. For a vertical stud in the default
    orientation, local X is the 1.5" thin axis - exactly the wall-spacing
    direction.
    """

    bl_idname = "praxova.duplicate_oc"
    bl_label = "Duplicate On Center"
    bl_description = (
        "Duplicate the active object N times along its local X axis at the "
        "specified on-center spacing"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({'ERROR'}, "No active object")
            return {'CANCELLED'}

        scn = context.scene.praxova_framing
        spacing_m = scn.spacing_in * templates.INCH
        count = scn.count
        sign = 1.0 if scn.direction == 'RIGHT' else -1.0

        # Local X axis of the source object expressed in world space.
        local_x_world = obj.matrix_world.to_3x3().col[0].normalized()
        step = local_x_world * (spacing_m * sign)

        new_objs = []
        for i in range(1, count + 1):
            dup = obj.copy()  # shallow: shares mesh data, copies object props
            dup.location = obj.location + step * i
            context.collection.objects.link(dup)
            new_objs.append(dup)

        # Select the new pieces, leave the last as active.
        for o in context.selected_objects:
            o.select_set(False)
        for o in new_objs:
            o.select_set(True)
        if new_objs:
            context.view_layer.objects.active = new_objs[-1]

        self.report(
            {'INFO'},
            f"Duplicated {count}x at {scn.spacing_in:g}\" OC ({scn.direction.lower()})",
        )
        return {'FINISHED'}

"""Operator: convenience to set scene units to imperial / inches."""

import bpy


class PRAXOVA_OT_set_imperial_units(bpy.types.Operator):
    """Set scene units to imperial / inches for construction work."""

    bl_idname = "praxova.set_imperial_units"
    bl_label = "Set Scene to Imperial"
    bl_description = "Configure scene units: Imperial system, length in inches"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        us = context.scene.unit_settings
        us.system = 'IMPERIAL'
        us.length_unit = 'INCHES'
        self.report({'INFO'}, "Scene units set to imperial / inches")
        return {'FINISHED'}

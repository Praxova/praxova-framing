"""Operators: edge-to-edge duplication for sheets and panels (Fill).

The Fill operator is the natural complement to ops_duplicate.duplicate_oc:
where OC steps along local X (the lumber thin axis, for stud-spacing
workflows), Fill steps along local Y (the sheet/panel width axis, for
sheathing-a-wall workflows).

Both share the linked-mesh-copy pattern: obj.copy() produces a new Object
that references the same Mesh datablock, so memory stays low and the cut
list still counts correctly (count is by tag, not by mesh).
"""

import bpy
from bpy.props import FloatProperty

from . import templates


class PRAXOVA_OT_set_fill_span(bpy.types.Operator):
    """Internal helper: apply a preset Fill Length (used by preset buttons).

    Setting fill_span_in fires its update callback in PraxovaSceneProps,
    which recomputes fill_count from the active object's width. So
    clicking a preset button atomically sets both span and count.
    """

    bl_idname = "praxova.set_fill_span"
    bl_label = "Set Fill Length"
    bl_options = {'INTERNAL', 'UNDO'}

    span: FloatProperty(default=192.0)  # noqa: F821

    def execute(self, context):
        context.scene.praxova_framing.fill_span_in = self.span
        return {'FINISHED'}


class PRAXOVA_OT_duplicate_e2e(bpy.types.Operator):
    """Duplicate the active sheet or panel edge-to-edge along its local Y.

    Mirrors duplicate_oc's pattern but with two key differences:
    - Direction is local +Y / -Y (the sheet/panel width axis), not local X.
    - Spacing equals the source's own width (from templates.fill_axis_width_in),
      so duplicates land flush against each other - "edge-to-edge".

    Requires active object's category to be SHEET or PANEL. LUMBER objects
    are refused with a message pointing to the OC duplicator, because
    lumber's local-Y is its cross-section width (3.5" for a 2x4) - almost
    never a meaningful fill spacing for typical workflows.

    Each duplicate is its own Object that shares the source's Mesh datablock
    (linked-data copy via obj.copy()); object-level tag is copied
    automatically, so the cut list counts every instance.

    Rotation-respecting: the world-space step is computed from the source's
    matrix_world, so duplicates stay parallel to a tilted source (e.g. roof
    panels rotated onto a slope).
    """

    bl_idname = "praxova.duplicate_e2e"
    bl_label = "Duplicate Edge-to-Edge"
    bl_description = (
        "Duplicate the active sheet or panel N times edge-to-edge along its "
        "local Y axis. Spacing equals the source's width. Use to sheathe a "
        "wall or cover a roof in one click"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            self.report({'ERROR'}, "No active object")
            return {'CANCELLED'}

        tag = obj.praxova_lumber
        if not tag.is_lumber:
            self.report(
                {'ERROR'},
                "Active object is not a Praxova-tagged piece. "
                "Add a sheet or panel first.",
            )
            return {'CANCELLED'}

        if tag.category not in {'SHEET', 'PANEL'}:
            self.report(
                {'ERROR'},
                f"Fill works on sheets and panels. For lumber, use the "
                f"On-Center Duplicate above (got category: {tag.category}).",
            )
            return {'CANCELLED'}

        width_in = templates.fill_axis_width_in(obj)
        if width_in <= 0:
            unknown_key = tag.sheet_size_key or tag.panel_size_key or '(none)'
            self.report(
                {'ERROR'},
                f"Cannot determine fill width for active object "
                f"(unknown size key '{unknown_key}'). Re-add the piece via "
                f"the Add menu.",
            )
            return {'CANCELLED'}

        scn = context.scene.praxova_framing
        count = scn.fill_count
        sign = 1.0 if scn.fill_direction == 'FORWARD' else -1.0

        # Local Y axis of the source expressed in world space. matrix_world
        # carries any rotation the user has applied at the object level, so
        # a tilted source still fills along its own width direction.
        local_y_world = obj.matrix_world.to_3x3().col[1].normalized()
        step = local_y_world * (width_in * templates.INCH * sign)

        new_objs = []
        for i in range(1, count + 1):
            dup = obj.copy()  # shallow: shares mesh data, copies object props
            dup.location = obj.location + step * i
            context.collection.objects.link(dup)
            new_objs.append(dup)

        # Select the new pieces, leave the last as active. Matches
        # duplicate_oc's selection behavior so the two operators feel
        # interchangeable to the user.
        for o in context.selected_objects:
            o.select_set(False)
        for o in new_objs:
            o.select_set(True)
        if new_objs:
            context.view_layer.objects.active = new_objs[-1]

        self.report(
            {'INFO'},
            f"Filled {count}x at {width_in:g}\" edge-to-edge "
            f"({scn.fill_direction.lower()})",
        )
        return {'FINISHED'}

"""Operator: frame a single wall - plates + studs + Empty parent (v0.4).

The first composite operator in the add-on. Reads parameters from the
scene-level PropertyGroup (driven by both the N-panel UI and, in v0.4.1,
the MCP bridge) and builds plates + studs at world origin, parented to
a new Empty.

Geometry conventions (single isolated wall, v0.4):
    +X: wall length
    +Y: wall thickness (perpendicular to wall face)
    +Z: wall height (floor to top of top plate)
The bottom-front-left corner of the framed wall lands at world (0, 0, 0).

Stud layout follows standard sheathing-aligned framing convention: end
studs flush with the wall ends, intermediate studs at on-center spacing
measured from x=0, the final bay tight when wall length isn't a multiple
of on-center spacing. This preserves 4'/8' sheathing seam alignment.

Not in v0.4 (deferred):
    - Corner stud treatments (three-stud, California corner, etc.)
    - Door/window openings (king studs, jacks, headers, cripples)
    - Direction/rotation parameter (user transforms the Empty afterward)
"""

import bpy

from . import templates


def _fmt_inches(val: float) -> str:
    """Format an inch dimension for inclusion in a mesh name.

    Strips trailing zeros so 96.0 -> '96' and 91.5 -> '91.5'. Used to
    build mesh names that change only when the actual dimension changes,
    so two walls with the same stud length share the stud mesh.
    """
    if val == int(val):
        return str(int(val))
    return f"{val:.3f}".rstrip("0").rstrip(".")


def _make_framing_object(
    context,
    mesh,
    name: str,
    location_m: tuple[float, float, float],
    *,
    nominal: str,
    length_in: float,
    stock_in: float,
    orientation: str,
    label: str,
):
    """Create one tagged plate or stud object and link it into the scene.

    Centralises the tagging boilerplate so the operator body stays
    focused on the layout math. Sets stock_length_in explicitly (rather
    than relying on the cut-list's v0.3.x fallback) so the object is
    unambiguous about its purchased-stock identity from day one.
    """
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location_m

    tag = obj.praxova_lumber
    tag.is_lumber = True
    tag.category = 'LUMBER'
    tag.nominal_size = nominal
    tag.length_in = float(length_in)
    tag.stock_length_in = float(stock_in)
    tag.orientation = orientation
    tag.cutlist_label = label

    context.collection.objects.link(obj)
    return obj


class PRAXOVA_OT_frame_wall(bpy.types.Operator):
    """Frame a single wall - plates and studs parented to a new Empty.

    Reads wall_* fields from scene.praxova_framing, creates a new Empty
    named via templates.next_wall_name() at world origin, and places
    bottom plates, studs, and top plates as children of the Empty. The
    Empty becomes the active object so the user can immediately
    transform the wall as a unit.

    Validates cross-field constraints that the PropertyGroup bounds can't
    enforce:
        - Wall height must leave room for at least some stud after the
          plate stack: height_in > (top_plates + bottom_plates) * thickness.
        - Wall length must be at least 2 * stud_thickness (so end studs
          don't overlap).
        - Stock length must exist for both wall length (plates) and stud
          length (studs) within the nominal's available stock list.
    Each validation failure reports a specific error and CANCELLED.
    """

    bl_idname = "praxova.frame_wall"
    bl_label = "Frame Wall"
    bl_description = (
        "Frame a single wall (plates + studs) at world origin, parented "
        "to a new Empty for one-handle transform. Reads parameters from "
        "the Wall Framing section of the N-panel."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sp = context.scene.praxova_framing
        length_in: float = float(sp.wall_length_in)
        height_in: float = float(sp.wall_height_in)
        nominal: str = sp.wall_nominal
        spacing_oc_in: float = float(sp.wall_spacing_oc_in)
        top_plate_count: int = sp.wall_top_plate_count
        bottom_plate_count: int = sp.wall_bottom_plate_count

        # ------------------------------------------------------------------
        # Validation
        # ------------------------------------------------------------------
        if nominal not in templates.LUMBER_TYPES:
            self.report({'ERROR'}, f"Unknown stud size: {nominal}")
            return {'CANCELLED'}
        thickness_in, width_in = templates.LUMBER_TYPES[nominal]

        if length_in < 2 * thickness_in:
            # PropertyGroup min is 12" which already enforces this for
            # any reasonable lumber type, but the MCP bridge in v0.4.1 can
            # bypass UI bounds, so revalidate here as defence in depth.
            self.report(
                {'ERROR'},
                f"Wall length {length_in:g}\" too short for two end studs "
                f"of {thickness_in:g}\" thickness.",
            )
            return {'CANCELLED'}

        if spacing_oc_in <= 0:
            self.report({'ERROR'}, "Stud spacing must be positive.")
            return {'CANCELLED'}

        plate_total_in = (top_plate_count + bottom_plate_count) * thickness_in
        stud_length_in = height_in - plate_total_in
        if stud_length_in <= 0:
            self.report(
                {'ERROR'},
                f"Wall height {height_in:g}\" too short for "
                f"{top_plate_count + bottom_plate_count} plates of "
                f"{thickness_in:g}\" thickness ({plate_total_in:g}\" total). "
                "Increase wall height or reduce plate count.",
            )
            return {'CANCELLED'}

        # Stock selection. Plates take the full wall length; studs are
        # cut down from the smallest stock that fits stud_length_in.
        try:
            plate_stock_in = templates.select_stock_length_in(nominal, length_in)
            stud_stock_in = templates.select_stock_length_in(nominal, stud_length_in)
        except ValueError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # ------------------------------------------------------------------
        # Derived values
        # ------------------------------------------------------------------
        stud_xs_in = templates.stud_positions(
            length_in, spacing_oc_in, thickness_in,
        )
        wall_name = templates.next_wall_name(
            {obj.name for obj in context.scene.objects},
        )

        plate_stock_ft = int(round(plate_stock_in / 12))
        stud_stock_ft = int(round(stud_stock_in / 12))
        plate_label = templates.lumber_cutlist_label(
            nominal, plate_stock_ft, 'HORIZONTAL',
        )
        stud_label = templates.lumber_cutlist_label(
            nominal, stud_stock_ft, 'VERTICAL',
        )

        # ------------------------------------------------------------------
        # Mesh creation (with reuse)
        # ------------------------------------------------------------------
        # The 'wall_' prefix on mesh names partitions frame_wall's mesh
        # namespace away from add_lumber's (which uses
        # 'praxova_mesh_<label>'). Two walls with identical dimensions
        # share meshes naturally; same goes for plates and studs across
        # walls of the same configuration.
        plate_dims_in = (length_in, width_in, thickness_in)  # HORIZONTAL
        stud_dims_in = (thickness_in, width_in, stud_length_in)  # VERTICAL
        plate_mesh_name = (
            f"praxova_mesh_wall_plate_{nominal}_{_fmt_inches(length_in)}"
        )
        stud_mesh_name = (
            f"praxova_mesh_wall_stud_{nominal}_{_fmt_inches(stud_length_in)}"
        )

        plate_mesh = bpy.data.meshes.get(plate_mesh_name)
        if plate_mesh is None:
            plate_mesh = templates.make_box_mesh(plate_mesh_name, plate_dims_in)
        stud_mesh = bpy.data.meshes.get(stud_mesh_name)
        if stud_mesh is None:
            stud_mesh = templates.make_box_mesh(stud_mesh_name, stud_dims_in)

        # ------------------------------------------------------------------
        # Empty parent
        # ------------------------------------------------------------------
        empty = bpy.data.objects.new(wall_name, None)
        empty.empty_display_type = 'PLAIN_AXES'
        empty.empty_display_size = 0.5  # 0.5m - visible but not overwhelming
        empty.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(empty)

        # ------------------------------------------------------------------
        # Children: bottom plates, studs, top plates
        # ------------------------------------------------------------------
        children: list = []
        INCH = templates.INCH

        # Bottom plates stacked from z=0 upward.
        for i in range(bottom_plate_count):
            z_m = i * thickness_in * INCH
            obj = _make_framing_object(
                context, plate_mesh,
                f"{wall_name}_BottomPlate_{i + 1:02d}",
                (0.0, 0.0, z_m),
                nominal=nominal,
                length_in=length_in,
                stock_in=plate_stock_in,
                orientation='HORIZONTAL',
                label=plate_label,
            )
            children.append(obj)

        # Studs span between top of bottom plates and bottom of top plates.
        z_stud_base_m = bottom_plate_count * thickness_in * INCH
        for i, x_in in enumerate(stud_xs_in):
            obj = _make_framing_object(
                context, stud_mesh,
                f"{wall_name}_Stud_{i + 1:02d}",
                (x_in * INCH, 0.0, z_stud_base_m),
                nominal=nominal,
                length_in=stud_length_in,
                stock_in=stud_stock_in,
                orientation='VERTICAL',
                label=stud_label,
            )
            children.append(obj)

        # Top plates stacked from (height - top_count * thickness) up.
        z_top_base_m = (height_in - top_plate_count * thickness_in) * INCH
        for i in range(top_plate_count):
            z_m = z_top_base_m + i * thickness_in * INCH
            obj = _make_framing_object(
                context, plate_mesh,
                f"{wall_name}_TopPlate_{i + 1:02d}",
                (0.0, 0.0, z_m),
                nominal=nominal,
                length_in=length_in,
                stock_in=plate_stock_in,
                orientation='HORIZONTAL',
                label=plate_label,
            )
            children.append(obj)

        # ------------------------------------------------------------------
        # Parent everything to the Empty
        # ------------------------------------------------------------------
        # Empty is at world origin so children's local locations equal
        # their world locations - no matrix_parent_inverse fiddling needed.
        for child in children:
            child.parent = empty

        # ------------------------------------------------------------------
        # Selection state: Empty becomes the active object
        # ------------------------------------------------------------------
        for o in context.selected_objects:
            o.select_set(False)
        empty.select_set(True)
        context.view_layer.objects.active = empty

        # ------------------------------------------------------------------
        # Report
        # ------------------------------------------------------------------
        n_studs = len(stud_xs_in)
        n_plates = top_plate_count + bottom_plate_count
        self.report(
            {'INFO'},
            f"Framed {wall_name}: {n_studs} studs "
            f"({nominal} x {_fmt_inches(stud_length_in)}\") + "
            f"{n_plates} plates ({nominal} x {_fmt_inches(length_in)}\").",
        )
        return {'FINISHED'}

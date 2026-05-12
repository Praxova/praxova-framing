"""Operator: frame a single wall - plates + studs + openings (v0.4 / v0.5).

The first composite operator in the add-on. Reads parameters from the
scene-level PropertyGroup (driven by both the N-panel UI and, in v0.4.1,
the MCP bridge) and builds plates + studs at world origin, parented to
a new Empty.

v0.5 extends the operator to honor a list of door and window openings
on the wall (PraxovaSceneProps.wall_openings). When present, the
operator validates them, computes per-opening framing geometry via
templates.opening_framing_layout, places king studs, jack studs, a (2)
2x + 1/2" plywood spacer header build-up, optional rough sill (windows),
and optional cripples above the header / below the rough sill. Regular
OC studs that would collide with any king bracket are filtered out via
templates.filter_studs_around_openings.

Geometry conventions (single isolated wall, v0.4):
    +X: wall length
    +Y: wall thickness (perpendicular to wall face)
    +Z: wall height (floor to top of top plate)
The bottom-front-left corner of the framed wall lands at world (0, 0, 0).

Stud layout follows standard sheathing-aligned framing convention: end
studs flush with the wall ends, intermediate studs at on-center spacing
measured from x=0, the final bay tight when wall length isn't a multiple
of on-center spacing. This preserves 4'/8' sheathing seam alignment.

Not in v0.5 (deferred):
    - Corner stud treatments (three-stud, California corner, etc.)
    - Direction/rotation parameter (user transforms the Empty afterward)
    - Headers other than (2) 2x + 1/2" plywood spacer
    - "Trimmer at door swing" or double-bottom-plate-at-door cut
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


def _make_untagged_object(
    context,
    mesh,
    name: str,
    location_m: tuple[float, float, float],
):
    """Create an Object with mesh but without the praxova_lumber tag set.

    Used by the v0.5 opening flow for the 1/2" plywood header spacer.
    Real-world residential framing sources the spacer from sheathing
    offcuts, so it's not material the cut list should order — leaving
    is_lumber=False keeps it invisible to ops_cutlist.
    """
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location_m
    context.collection.objects.link(obj)
    return obj


def _get_or_make_mesh(name: str, dims_inches: tuple[float, float, float]):
    """Return an existing mesh by name, or create one with given dims."""
    mesh = bpy.data.meshes.get(name)
    if mesh is None:
        mesh = templates.make_box_mesh(name, dims_inches)
    return mesh


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
        # v0.5: snapshot the openings collection. Each entry is a
        # PraxovaWallOpening with the seven fields the helpers expect.
        openings = list(sp.wall_openings)

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

        # v0.5: opening validation. Run after scalar validation so the
        # opening checks (which depend on wall_length_in, etc.) can
        # assume the wall params are themselves sane.
        if openings:
            ok, msg = templates.validate_openings(
                openings, length_in, height_in, nominal,
                top_plate_count, bottom_plate_count,
            )
            if not ok:
                self.report({'ERROR'}, msg)
                return {'CANCELLED'}

        # ------------------------------------------------------------------
        # Derived values
        # ------------------------------------------------------------------
        # Raw OC layout, then v0.5 filtered layout after per-opening
        # geometry is known. Regular studs that collide with any opening's
        # king bracket get dropped; the survivors are placed at the
        # bottom of the children section below.
        raw_stud_xs_in = templates.stud_positions(
            length_in, spacing_oc_in, thickness_in,
        )
        opening_layouts = [
            templates.opening_framing_layout(
                op, nominal, height_in, top_plate_count, bottom_plate_count,
            )
            for op in openings
        ]
        stud_xs_in = templates.filter_studs_around_openings(
            raw_stud_xs_in, thickness_in, openings, opening_layouts,
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

        z_stud_base_m = bottom_plate_count * thickness_in * INCH

        # v0.5: opening pieces. For each opening, place 2 king studs, the
        # jacks, 2 header members, the (untagged) plywood spacer, an
        # optional rough sill (windows), and optional header and sill
        # cripples. Kings share the regular wall-stud mesh (identical
        # cross-section and length, just used in a different role).
        for op_idx, (op, layout) in enumerate(zip(openings, opening_layouts)):
            op_tag = f"Op{op_idx:02d}"
            header_nominal = op.header_nominal
            try:
                header_stock_in = templates.select_stock_length_in(
                    header_nominal, layout['header_member_length_in'],
                )
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            header_stock_ft = int(round(header_stock_in / 12))
            header_label = templates.lumber_cutlist_label(
                header_nominal, header_stock_ft, 'HORIZONTAL',
            )
            header_member_thickness_y = templates.LUMBER_TYPES[header_nominal][0]
            header_member_z_height = templates.LUMBER_TYPES[header_nominal][1]
            jack_length_in = layout['jack_length_in']
            king_length_in = layout['king_length_in']

            # ---- 2 king studs (share mesh + label with regular studs) ----
            for side, x_in in (('L', layout['king_left_x']),
                               ('R', layout['king_right_x'] - thickness_in)):
                obj = _make_framing_object(
                    context, stud_mesh,
                    f"King_{op_tag}_{side}",
                    (x_in * INCH, 0.0, z_stud_base_m),
                    nominal=nominal,
                    length_in=king_length_in,
                    stock_in=stud_stock_in,
                    orientation='VERTICAL',
                    label=stud_label,
                )
                children.append(obj)

            # ---- Jack studs (jack_count per side) ----
            try:
                jack_stock_in = templates.select_stock_length_in(
                    nominal, jack_length_in,
                )
            except ValueError as e:
                self.report({'ERROR'}, str(e))
                return {'CANCELLED'}
            jack_stock_ft = int(round(jack_stock_in / 12))
            jack_label = templates.lumber_cutlist_label(
                nominal, jack_stock_ft, 'VERTICAL',
            )
            jack_mesh_name = (
                f"praxova_mesh_wall_jack_{nominal}_"
                f"{_fmt_inches(jack_length_in)}"
            )
            jack_mesh = _get_or_make_mesh(
                jack_mesh_name, (thickness_in, width_in, jack_length_in),
            )
            for side, jack_xs in (('L', layout['jack_left_xs']),
                                  ('R', layout['jack_right_xs'])):
                for i, x_in in enumerate(jack_xs):
                    obj = _make_framing_object(
                        context, jack_mesh,
                        f"Jack_{op_tag}_{side}_{i + 1:02d}",
                        (x_in * INCH, 0.0, z_stud_base_m),
                        nominal=nominal,
                        length_in=jack_length_in,
                        stock_in=jack_stock_in,
                        orientation='VERTICAL',
                        label=jack_label,
                    )
                    children.append(obj)

            # ---- 2 header members + 1 untagged plywood spacer ----
            header_mesh_name = (
                f"praxova_mesh_wall_header_{header_nominal}_"
                f"{_fmt_inches(layout['header_member_length_in'])}"
            )
            header_mesh = _get_or_make_mesh(
                header_mesh_name,
                (
                    layout['header_member_length_in'],
                    header_member_thickness_y,
                    header_member_z_height,
                ),
            )
            # Front member at y=0; back member at y=spacer_y_end so the two
            # members flank the 1/2" plywood spacer between them.
            header_y_offsets = (0.0, layout['spacer_y_end'])
            for i, y_in in enumerate(header_y_offsets):
                obj = _make_framing_object(
                    context, header_mesh,
                    f"Header_{op_tag}_{i + 1:02d}",
                    (
                        layout['header_x_start'] * INCH,
                        y_in * INCH,
                        layout['header_z_bottom'] * INCH,
                    ),
                    nominal=header_nominal,
                    length_in=layout['header_member_length_in'],
                    stock_in=header_stock_in,
                    orientation='HORIZONTAL',
                    label=header_label,
                )
                children.append(obj)

            spacer_thickness_y = (
                layout['spacer_y_end'] - layout['spacer_y_start']
            )
            spacer_mesh_name = (
                f"praxova_mesh_wall_header_spacer_"
                f"{_fmt_inches(layout['header_member_length_in'])}"
            )
            spacer_mesh = _get_or_make_mesh(
                spacer_mesh_name,
                (
                    layout['header_member_length_in'],
                    spacer_thickness_y,
                    header_member_z_height,
                ),
            )
            spacer = _make_untagged_object(
                context, spacer_mesh,
                f"HeaderSpacer_{op_tag}",
                (
                    layout['header_x_start'] * INCH,
                    layout['spacer_y_start'] * INCH,
                    layout['header_z_bottom'] * INCH,
                ),
            )
            children.append(spacer)

            # ---- Rough sill (windows only) ----
            if op.opening_type == 'WINDOW':
                try:
                    sill_stock_in = templates.select_stock_length_in(
                        nominal, op.ro_width_in,
                    )
                except ValueError as e:
                    self.report({'ERROR'}, str(e))
                    return {'CANCELLED'}
                sill_stock_ft = int(round(sill_stock_in / 12))
                sill_label = templates.lumber_cutlist_label(
                    nominal, sill_stock_ft, 'HORIZONTAL',
                )
                sill_mesh_name = (
                    f"praxova_mesh_wall_rough_sill_{nominal}_"
                    f"{_fmt_inches(op.ro_width_in)}"
                )
                sill_mesh = _get_or_make_mesh(
                    sill_mesh_name,
                    (float(op.ro_width_in), width_in, thickness_in),
                )
                obj = _make_framing_object(
                    context, sill_mesh,
                    f"Sill_{op_tag}",
                    (
                        layout['rough_sill_x_start'] * INCH,
                        0.0,
                        layout['rough_sill_z_bottom'] * INCH,
                    ),
                    nominal=nominal,
                    length_in=float(op.ro_width_in),
                    stock_in=sill_stock_in,
                    orientation='HORIZONTAL',
                    label=sill_label,
                )
                children.append(obj)

            # ---- Header cripples (above header, below top plates) ----
            # Cripples land at OC stud positions that fall fully between
            # the king inner edges, i.e. the same x positions a regular
            # stud would have used had the opening not been there. Same
            # raw OC layout the filter consumed; cripple z is above the
            # header.
            top_zone_bottom, top_zone_top = layout['cripple_top_zone']
            if top_zone_bottom is not None:
                header_cripple_length_in = top_zone_top - top_zone_bottom
                cripple_mesh_name = (
                    f"praxova_mesh_wall_header_cripple_{nominal}_"
                    f"{_fmt_inches(header_cripple_length_in)}"
                )
                cripple_mesh = _get_or_make_mesh(
                    cripple_mesh_name,
                    (thickness_in, width_in, header_cripple_length_in),
                )
                try:
                    cripple_stock_in = templates.select_stock_length_in(
                        nominal, header_cripple_length_in,
                    )
                except ValueError as e:
                    self.report({'ERROR'}, str(e))
                    return {'CANCELLED'}
                cripple_stock_ft = int(round(cripple_stock_in / 12))
                cripple_label = templates.lumber_cutlist_label(
                    nominal, cripple_stock_ft, 'VERTICAL',
                )
                k_left_in = layout['king_left_x'] + thickness_in
                k_right_in = layout['king_right_x'] - thickness_in
                cripple_idx = 0
                for x_in in raw_stud_xs_in:
                    # OC stud fully inside king-bracket inner range:
                    # left edge ≥ left-king inner edge AND right edge
                    # ≤ right-king inner edge. Excludes positions that
                    # would touch or overlap a king.
                    if x_in >= k_left_in and x_in + thickness_in <= k_right_in:
                        cripple_idx += 1
                        obj = _make_framing_object(
                            context, cripple_mesh,
                            f"HeaderCripple_{op_tag}_{cripple_idx:02d}",
                            (x_in * INCH, 0.0, top_zone_bottom * INCH),
                            nominal=nominal,
                            length_in=header_cripple_length_in,
                            stock_in=cripple_stock_in,
                            orientation='VERTICAL',
                            label=cripple_label,
                        )
                        children.append(obj)

            # ---- Sill cripples (windows only, below rough sill) ----
            if op.opening_type == 'WINDOW':
                bot_zone_bottom, bot_zone_top = layout['cripple_bottom_zone']
                if bot_zone_bottom is not None:
                    sill_cripple_length_in = bot_zone_top - bot_zone_bottom
                    sc_mesh_name = (
                        f"praxova_mesh_wall_sill_cripple_{nominal}_"
                        f"{_fmt_inches(sill_cripple_length_in)}"
                    )
                    sc_mesh = _get_or_make_mesh(
                        sc_mesh_name,
                        (thickness_in, width_in, sill_cripple_length_in),
                    )
                    try:
                        sc_stock_in = templates.select_stock_length_in(
                            nominal, sill_cripple_length_in,
                        )
                    except ValueError as e:
                        self.report({'ERROR'}, str(e))
                        return {'CANCELLED'}
                    sc_stock_ft = int(round(sc_stock_in / 12))
                    sc_label = templates.lumber_cutlist_label(
                        nominal, sc_stock_ft, 'VERTICAL',
                    )
                    k_left_in = layout['king_left_x'] + thickness_in
                    k_right_in = layout['king_right_x'] - thickness_in
                    sc_idx = 0
                    for x_in in raw_stud_xs_in:
                        if (x_in >= k_left_in
                                and x_in + thickness_in <= k_right_in):
                            sc_idx += 1
                            obj = _make_framing_object(
                                context, sc_mesh,
                                f"SillCripple_{op_tag}_{sc_idx:02d}",
                                (x_in * INCH, 0.0, bot_zone_bottom * INCH),
                                nominal=nominal,
                                length_in=sill_cripple_length_in,
                                stock_in=sc_stock_in,
                                orientation='VERTICAL',
                                label=sc_label,
                            )
                            children.append(obj)

        # Regular OC studs (filtered to skip positions that collide with
        # any opening's king bracket). Same mesh and label the kings used
        # above — same cross-section and length, just different role.
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
        n_openings = len(openings)
        opening_suffix = (
            f" + {n_openings} opening{'s' if n_openings != 1 else ''}"
            if n_openings
            else ""
        )
        self.report(
            {'INFO'},
            f"Framed {wall_name}: {n_studs} studs "
            f"({nominal} x {_fmt_inches(stud_length_in)}\") + "
            f"{n_plates} plates ({nominal} x {_fmt_inches(length_in)}\")"
            f"{opening_suffix}.",
        )
        return {'FINISHED'}

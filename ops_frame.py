"""Composite framing operators: frame_wall + v0.6 Building / Level containers.

PRAXOVA_OT_frame_wall (v0.4, extended v0.5 + v0.6) is the original
composite operator — it places plates, OC studs, and v0.5 opening pieces
(king studs, jacks, header build-up, rough sills, cripples) parented to
a wall Empty. v0.6 made it context-sensitive: when the active object is
a Praxova wall Empty, the operator re-frames it in place using the
wall's own PraxovaWallProps; otherwise it creates a new wall from scene
scratch.

v0.6 adds container-creation operators in this module:
    PRAXOVA_OT_add_building — create a Building Empty plus a default Level
    PRAXOVA_OT_add_level    — add another Level under the active Building
plus joint management (add_joint, remove_joint) and the frame_building
multi-wall orchestrator.

Geometry conventions (single isolated wall, v0.4):
    +X: wall length
    +Y: wall thickness (perpendicular to wall face)
    +Z: wall height (floor to top of top plate)
The bottom-front-left corner of the framed wall lands at world (0, 0, 0).

Stud layout follows standard sheathing-aligned framing convention: end
studs flush with the wall ends, intermediate studs at on-center spacing
measured from x=0, the final bay tight when wall length isn't a multiple
of on-center spacing. This preserves 4'/8' sheathing seam alignment.

Not yet shipped:
    - In-line splice joint_type (joining two walls end-to-end as one wall;
      distinct from v0.6.40's plate splicing along a single wall, which
      already ships)
    - Multi-Level framing in one pass (v0.8+)
    - Direction/rotation parameter for frame_wall (user transforms the
      Empty afterward)
    - Headers other than (2) 2x + 1/2" plywood spacer
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


# ---------------------------------------------------------------------------
# v0.6 joint resolution
# ---------------------------------------------------------------------------

# Per-end stud-related modifications. v0.6.40 narrowed this dict to
# stud overrides and filler positions only — the per-end plate offsets
# (bottom_off / lower_top_off / cap_off / cap_signed_offset) moved out
# to the per-plate plate_ranges dict returned alongside, computed via
# templates.plate_effective_ranges (v0.6.50 list-returning rename of
# the v0.6.40 plate_effective_range). The split mirrors the conceptual
# divide: plates are per-plate (both ends combined into a range), and
# studs are per-end (one filler per joint, one stud override per joint).
_EMPTY_END_MODS = {
    'end_stud_override': None,
    'filler_x': None,
    'joint_index': 0,
}


def _resolve_joint_context(active, is_existing_wall, length_in, thickness_in):
    """Read joints on the active wall's parent Level (if any) and turn
    them into per-end modifications + per-plate effective ranges.

    Only existing walls under a Level can have joints touching them.
    New walls (top-level or just-parented to a Level by frame_wall)
    aren't referenced by any Joint yet, so this returns empty context +
    no-op mods/ranges for them — and the rest of execute() stays on
    the v0.5 path.

    Returns:
        joint_context: dict per templates.compute_wall_joint_context
        level_joints: list of joints from the parent Level (or empty)
        mods: dict with 'START' and 'END' entries, each carrying
            end_stud_override / filler_x / joint_index for that end.
            joint_index is the 1-based index in the Level's joints
            collection (0 if no joint touches that end).
        plate_ranges: dict with 'BOTTOM', 'LOWER_TOP', 'CAP' keys.
            Each value is a list of (start_x, end_x) tuples in
            wall-local coordinates from
            templates.plate_effective_ranges; single-element list for
            L-corner-only walls or walls without joints. Multi-range
            results land when the cap is notched by T joints (this
            wall is wall_a in one or more T joints) or extended by
            T joints (this wall is wall_b in a T_JOINT at one end).
            For a wall with no joints, all three are [(0, length_in)].
    """
    empty_ctx = {'START': None, 'END': None, 'mid_joints': []}
    mods = {
        'START': dict(_EMPTY_END_MODS),
        'END':   dict(_EMPTY_END_MODS),
    }
    no_joint_ranges = {
        'BOTTOM':    [(0.0, length_in)],
        'LOWER_TOP': [(0.0, length_in)],
        'CAP':       [(0.0, length_in)],
    }

    if not is_existing_wall:
        return empty_ctx, [], mods, no_joint_ranges

    parent = active.parent
    if (parent is None
            or getattr(parent, 'praxova_level', None) is None
            or not parent.praxova_level.is_level):
        return empty_ctx, [], mods, no_joint_ranges

    level = parent
    level_joints = list(level.praxova_level.joints)

    building_default = 'THREE_STUD'
    grand = level.parent
    if (grand is not None
            and getattr(grand, 'praxova_building', None) is not None
            and grand.praxova_building.is_building):
        building_default = grand.praxova_building.default_corner_style

    joint_context = templates.compute_wall_joint_context(
        active, level_joints, building_default,
    )

    # Map joint -> 1-based index within the Level for naming filler studs
    # per the design's CornerFiller_Joint<NN> convention.
    joint_index_by_end = {'START': 0, 'END': 0}
    for j_idx, j in enumerate(level_joints, start=1):
        if j.wall_a is None or j.wall_b is None:
            continue
        if j.wall_a == active:
            joint_index_by_end[j.wall_a_end] = j_idx
        elif j.wall_b == active:
            joint_index_by_end[j.wall_b_end] = j_idx

    # Walk both ends, populating the stud-related mods and capturing
    # paired_t per end for the plate-range computation below.
    paired_t_by_end: dict[str, float] = {'START': 0.0, 'END': 0.0}
    for end in ('START', 'END'):
        ctx = joint_context[end]
        if ctx is None:
            continue
        # The paired wall's WALL thickness (LUMBER_TYPES[...][1], the
        # depth from interior to exterior face — 3.5" for 2x4) drives
        # corner geometry, NOT its stud thickness ([0]). This wall's
        # OWN stud thickness (thickness_in, set in execute() as
        # LUMBER_TYPES[nominal][0]) is what the END-side overrides
        # need to offset by the stud's own x-extent.
        paired_wall = ctx['paired_wall']
        paired_nominal = paired_wall.praxova_wall.wall_nominal
        wt_other = templates.LUMBER_TYPES[paired_nominal][1]
        paired_t_by_end[end] = wt_other

        geom = templates.l_corner_geometry(
            st_self=thickness_in,
            wt_other=wt_other,
            role=ctx['role'],
            end=end,
            wall_length_in=length_in,
        )
        mods[end] = {
            'end_stud_override': geom['end_stud_x_override'],
            'filler_x': geom['filler_stud_x'],
            'joint_index': joint_index_by_end[end],
        }

    # v0.6.50: per-plate effective ranges via the canonical list-
    # returning helper. Each plate's range list encodes the v0.6.31
    # lap geometry: bottom and lower top shorten at L-corner ABUTTING
    # ends (paired wall takes up that corner cell); cap shortens at
    # L-corner MAIN ends (leaving room for the abutting wall's cap to
    # lap onto the main's lower top); L-corner ABUTTING cap and FREE
    # ends reach the wall edge. The list-of-tuples shape carries
    # multi-range output for two T-joint cases:
    #   - this wall is wall_a (through wall) in one or more T joints:
    #     the cap is partitioned into sub-ranges between the notches.
    #   - this wall is wall_b (abutting wall) in a T_JOINT at one end:
    #     the cap range extends OUTBOARD past the wall_length_in edge
    #     by paired_t (negative start or end > length).
    role_at_start = (
        joint_context['START']['role'] if joint_context['START'] else None
    )
    role_at_end = (
        joint_context['END']['role'] if joint_context['END'] else None
    )
    # Translate joint_context['mid_joints'] into the {position_in,
    # paired_wt} dicts that plate_effective_ranges consumes for cap-
    # notch partitioning. paired_wt is the abutting wall's WALL
    # thickness (LUMBER_TYPES[..][1], 3.5" for 2x4) — the wt_B vs
    # st_B distinction from the v0.6.50 design: wall_b's footprint
    # on wall_a's length axis is its wall thickness, because wall_b
    # is rotated 90° relative to wall_a so wall_b's local-Y maps to
    # wall_a's local-X.
    mid_joints_for_ranges = [
        {
            'position_in': mj['position_in'],
            'paired_wt': templates.LUMBER_TYPES[
                mj['paired_wall'].praxova_wall.wall_nominal
            ][1],
        }
        for mj in joint_context['mid_joints']
    ]
    plate_ranges = {
        plate_role: templates.plate_effective_ranges(
            plate_role,
            length_in,
            role_at_start=role_at_start,
            role_at_end=role_at_end,
            paired_t_at_start=paired_t_by_end['START'],
            paired_t_at_end=paired_t_by_end['END'],
            joint_type_at_start=(
                joint_context['START']['joint_type']
                if joint_context['START'] else None
            ),
            joint_type_at_end=(
                joint_context['END']['joint_type']
                if joint_context['END'] else None
            ),
            mid_joints=mid_joints_for_ranges,
        )
        for plate_role in ('BOTTOM', 'LOWER_TOP', 'CAP')
    }

    return joint_context, level_joints, mods, plate_ranges


class PRAXOVA_OT_frame_wall(bpy.types.Operator):
    """Frame a single wall - plates and studs parented to an Empty.

    Two modes, picked from the active object (v0.6):

    1. Active object is a Praxova-managed wall Empty (its
       praxova_wall.is_wall == True): regenerate in place. The Empty's
       existing children are deleted; new children are built from the
       wall's own PraxovaWallProps. The Empty itself is preserved, so
       PointerProperty references to it (e.g. from joints in a Level)
       survive the re-framing.

    2. Active object is anything else (or nothing): create a new wall
       Empty at world origin, copy the scene-level scratch params
       (PraxovaSceneProps.wall_*) and openings onto the new wall's
       PraxovaWallProps, then build children.

    Validates cross-field constraints that PropertyGroup bounds can't
    enforce:
        - Wall height must leave room for at least some stud after the
          plate stack: height_in > (top_plates + bottom_plates) * thickness.
        - Wall length must be at least 2 * stud_thickness (so end studs
          don't overlap).
        - Stock length must exist for both wall length (plates) and stud
          length (studs) within the nominal's available stock list.
    v0.5 openings get the same cross-field validation via
    templates.validate_openings. Each failure reports a specific error
    and CANCELLED.
    """

    bl_idname = "praxova.frame_wall"
    bl_label = "Frame Wall"
    bl_description = (
        "Frame a wall. If a Praxova wall Empty is active, re-frame it "
        "in place (children deleted, Empty preserved). Otherwise create "
        "a new wall Empty at world origin from the scene scratch params."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sp = context.scene.praxova_framing

        # v0.6: source for wall params is either the active wall's own
        # PraxovaWallProps (in-place re-frame mode) or the scene scratch
        # (new wall mode). Both have the same wall_* / wall_openings
        # shape — the rest of execute() reads from `source` and stays
        # mode-agnostic.
        active = context.active_object
        is_existing_wall = (
            active is not None
            and getattr(active, 'praxova_wall', None) is not None
            and active.praxova_wall.is_wall
        )
        # v0.6: a Level Empty as active means "create a new wall as a
        # child of this Level". Walls created this way inherit the
        # Level's transform and become eligible for joints with their
        # siblings via the Level's joints collection.
        is_level_active = (
            not is_existing_wall
            and active is not None
            and getattr(active, 'praxova_level', None) is not None
            and active.praxova_level.is_level
        )
        source = active.praxova_wall if is_existing_wall else sp

        length_in: float = float(source.wall_length_in)
        height_in: float = float(source.wall_height_in)
        nominal: str = source.wall_nominal
        spacing_oc_in: float = float(source.wall_spacing_oc_in)
        top_plate_count: int = source.wall_top_plate_count
        bottom_plate_count: int = source.wall_bottom_plate_count
        # v0.5: snapshot the openings collection. Each entry is a
        # PraxovaWallOpening with the seven fields the helpers expect.
        openings = list(source.wall_openings)

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

        # Stud stock selection. Studs are cut down from the smallest
        # stock that fits stud_length_in. Plate stock is no longer
        # selected up-front (v0.6.40): the splice planner returns one
        # or more cut pieces per plate, each with its own length and
        # its own stock via select_stock_length_in inside the placement
        # loop. A wall too tall for any single stud (stud_length_in
        # exceeds the nominal's longest stock) still fails here — stud
        # splicing isn't a v0.6.40 feature.
        try:
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
        # v0.6: joint context + per-end wall modifications
        # ------------------------------------------------------------------
        # Only existing walls under a Level can have joints touching them
        # (a brand-new wall, even one parented to the Level by frame_wall
        # below, isn't referenced by any Joint yet). For everyone else
        # the context is empty, mods carry no stud overrides, and
        # plate_ranges defaults to (0, length_in) on all three plates —
        # the rest of execute() behaves identically to v0.5.
        joint_context, level_joints, mods, plate_ranges = (
            _resolve_joint_context(
                active, is_existing_wall, length_in, thickness_in,
            )
        )

        # ------------------------------------------------------------------
        # v0.6.50: T-joint backing stud derivation
        # ------------------------------------------------------------------
        # For each T joint where this wall is wall_a (the through wall),
        # compute the two backing-stud positions and capture the joint
        # index for naming. Backing studs flank wall_b's end-stud
        # footprint on wall_a's interior face, providing drywall nailing
        # for wall_b's interior face return on both sides. Empty list
        # for L-corner-only walls and walls with no T-joint mid contexts.
        # Order is per-joint-then-L/R; since joint_context['mid_joints']
        # is already sorted by position_in (ascending along wall_a), the
        # resulting backing_studs list is also monotonic in x, which
        # keeps TBacker_Joint<NN>_L/_R naming stable across reframes.
        backing_studs: list[dict] = []
        for mj in joint_context['mid_joints']:
            paired_nominal = mj['paired_wall'].praxova_wall.wall_nominal
            wt_b = templates.LUMBER_TYPES[paired_nominal][1]
            geom = templates.t_joint_geometry_for_wall_a(
                position_in=mj['position_in'],
                st_a=thickness_in,
                wt_b=wt_b,
            )
            left_x, right_x = geom['backing_stud_xs']
            backing_studs.append({
                'x': left_x,  'side': 'L', 'joint_index': mj['joint_index'],
            })
            backing_studs.append({
                'x': right_x, 'side': 'R', 'joint_index': mj['joint_index'],
            })
        backing_stud_xs = [b['x'] for b in backing_studs]

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
        # v0.6: apply ABUTTING-wall end-stud overrides before the opening
        # filter. The override moves the end stud inboard by the paired
        # wall's stud thickness so it lands flush with the shortened
        # plates. MAIN walls don't override (their end stud is unchanged
        # from v0.5).
        if mods['START']['end_stud_override'] is not None:
            raw_stud_xs_in[0] = mods['START']['end_stud_override']
        if mods['END']['end_stud_override'] is not None:
            raw_stud_xs_in[-1] = mods['END']['end_stud_override']
        opening_layouts = [
            templates.opening_framing_layout(
                op, nominal, height_in, top_plate_count, bottom_plate_count,
            )
            for op in openings
        ]
        stud_xs_in = templates.filter_studs_around_openings(
            raw_stud_xs_in, thickness_in, openings, opening_layouts,
        )
        # v0.6.50: drop OC studs whose footprint overlaps any T-joint
        # backing-stud position on this wall. Applied AFTER
        # filter_studs_around_openings so a single OC stud colliding
        # with both a king bracket and a backing stud is dropped by
        # whichever filter sees it first (idempotent composition).
        if backing_studs:
            backing_intervals = [
                (b['x'], b['x'] + thickness_in) for b in backing_studs
            ]
            stud_xs_in = templates.filter_studs_around_intervals(
                stud_xs_in, thickness_in, backing_intervals,
            )
        # v0.6: wall_name comes from the existing Empty (in-place mode) or
        # the next-unused Wall_NN slot (new mode). Child names are derived
        # via f"{wall_name}_BottomPlate_NN" etc., so picking the right name
        # here keeps child naming stable across the two modes.
        if is_existing_wall:
            wall_name = active.name
        else:
            wall_name = templates.next_wall_name(
                {obj.name for obj in context.scene.objects},
            )

        # Stud label (uniform across all studs in the wall — they
        # share length and stock). Plate label is computed per piece
        # inside the placement loops below (v0.6.40), since splice
        # pieces can have different stock sizes.
        stud_stock_ft = int(round(stud_stock_in / 12))
        stud_label = templates.lumber_cutlist_label(
            nominal, stud_stock_ft, 'VERTICAL',
        )

        # ------------------------------------------------------------------
        # v0.6.40: plate splice planning
        # ------------------------------------------------------------------
        # Plates exceeding max stock are split into pieces that butt-join
        # over a full-height stud (end stud, OC stud, king, or interior
        # corner filler — collected via collect_full_height_stud_centers,
        # which knows the operator's stud / king / filler taxonomy and
        # excludes jacks + cripples). The cap plate offsets ≥24" from
        # the lower-top splice positions per IRC R602.3.2; the planner
        # enforces this as a hard constraint and raises SpliceError if
        # no eligible stud can satisfy the offset, surfacing it as a
        # clean operator error.
        max_stock_in = templates.max_stock_length_in(nominal)
        filler_left_xs = [
            x for x in (mods['START']['filler_x'], mods['END']['filler_x'])
            if x is not None
        ]
        eligible_stud_centers = templates.collect_full_height_stud_centers(
            oc_stud_left_xs=stud_xs_in,
            opening_layouts=opening_layouts,
            stud_thickness_in=thickness_in,
            backing_stud_left_xs=backing_stud_xs,
        )
        try:
            # v0.6.50: plate_ranges values are now LISTS of disjoint
            # (start_x, end_x) ranges. Each range goes through the
            # splice planner independently and the results are
            # concatenated. For L-corner-only walls every list has
            # exactly one element so the flattened pieces lists
            # match v0.6.41 behavior. The multi-range case arrives
            # when the cap is notched by T joints (commit 3).
            bot_pieces = []
            for r_start, r_end in plate_ranges['BOTTOM']:
                bot_pieces.extend(templates.plan_plate_splice_pieces(
                    r_start, r_end, eligible_stud_centers, max_stock_in,
                ))
            lower_top_pieces = []
            for r_start, r_end in plate_ranges['LOWER_TOP']:
                lower_top_pieces.extend(templates.plan_plate_splice_pieces(
                    r_start, r_end, eligible_stud_centers, max_stock_in,
                ))
            # Cap splices must offset >=24" from lower-top splices.
            # Since lower top is never multi-range in v0.6.50 (T joints
            # only notch the cap), lower_top_pieces[:-1] picks genuine
            # internal splice points within a single contiguous range.
            lower_top_splice_xs = tuple(
                end for start, end in lower_top_pieces[:-1]
            )
            cap_pieces = []
            for r_start, r_end in plate_ranges['CAP']:
                cap_pieces.extend(templates.plan_plate_splice_pieces(
                    r_start, r_end, eligible_stud_centers, max_stock_in,
                    excluded_splice_xs=lower_top_splice_xs,
                ))
        except templates.SpliceError as e:
            self.report({'ERROR'}, f"{wall_name}: {e}")
            return {'CANCELLED'}

        # ------------------------------------------------------------------
        # Mesh creation (with reuse)
        # ------------------------------------------------------------------
        # The 'wall_' prefix on mesh names partitions frame_wall's mesh
        # namespace away from add_lumber's (which uses
        # 'praxova_mesh_<label>'). Two walls with identical dimensions
        # share meshes naturally; same goes for plates and studs across
        # walls of the same configuration.
        #
        # v0.6: plate mesh is no longer created up-front — plates at a
        # joint end can be shorter than wall length, so meshes are
        # looked-up-or-created per plate inside the placement loop below
        # (each unique length gets its own mesh, all keyed by
        # praxova_mesh_wall_plate_<nominal>_<length>). Studs are still
        # uniform length within a wall, so the stud mesh stays shared;
        # filler studs use the same mesh.
        stud_dims_in = (thickness_in, width_in, stud_length_in)  # VERTICAL
        stud_mesh_name = (
            f"praxova_mesh_wall_stud_{nominal}_{_fmt_inches(stud_length_in)}"
        )
        stud_mesh = bpy.data.meshes.get(stud_mesh_name)
        if stud_mesh is None:
            stud_mesh = templates.make_box_mesh(stud_mesh_name, stud_dims_in)

        # ------------------------------------------------------------------
        # Empty parent (v0.6: existing wall or new)
        # ------------------------------------------------------------------
        # In-place mode: re-use the active wall Empty. Delete its existing
        # children so the new build starts clean. The Empty itself is
        # preserved — its name, transform, parent, and any PointerProperty
        # references to it (e.g. from v0.6 joints) all stay valid.
        #
        # New mode: create a fresh Empty at world origin and copy the
        # scene scratch params (length / height / nominal / openings) onto
        # its PraxovaWallProps, then mark it with is_wall=True so future
        # invocations recognize it as a Praxova-managed wall.
        if is_existing_wall:
            empty = active
            for child in list(empty.children):
                bpy.data.objects.remove(child, do_unlink=True)
        else:
            empty = bpy.data.objects.new(wall_name, None)
            empty.empty_display_type = 'PLAIN_AXES'
            empty.empty_display_size = 0.5  # 0.5m - visible but not overwhelming
            empty.location = (0.0, 0.0, 0.0)
            context.collection.objects.link(empty)
            # v0.6: if a Level was the active object, parent the new wall
            # to it so joints in that Level can reference the wall via
            # PointerProperty pickers in commit 6's UI. Otherwise the
            # wall stays at top level (v0.5 single-wall workflow).
            if is_level_active:
                empty.parent = active
            wp = empty.praxova_wall
            wp.is_wall = True
            wp.wall_length_in = sp.wall_length_in
            wp.wall_height_in = sp.wall_height_in
            wp.wall_nominal = sp.wall_nominal
            wp.wall_spacing_oc_in = sp.wall_spacing_oc_in
            wp.wall_top_plate_count = sp.wall_top_plate_count
            wp.wall_bottom_plate_count = sp.wall_bottom_plate_count
            for src in sp.wall_openings:
                dst = wp.wall_openings.add()
                dst.opening_type = src.opening_type
                dst.x_offset_in = src.x_offset_in
                dst.ro_width_in = src.ro_width_in
                dst.ro_height_in = src.ro_height_in
                dst.sill_height_in = src.sill_height_in
                dst.header_nominal = src.header_nominal
                dst.jack_count = src.jack_count
            wp.wall_openings_active = sp.wall_openings_active

        # ------------------------------------------------------------------
        # Children: bottom plates, studs, top plates
        # ------------------------------------------------------------------
        children: list = []
        INCH = templates.INCH

        # Bottom plates stacked from z=0 upward.
        # v0.6: a joint at either end can shorten the bottom plate by
        # the paired wall's wall thickness (ABUTTING walls only — MAIN
        # walls keep bottom + lower top plates at full length).
        # v0.6.40: range comes from plate_effective_ranges via
        # _resolve_joint_context, and the plate may be split into
        # multiple cut pieces by the splice planner (above). For walls
        # that don't need splicing, bot_pieces is a single-element
        # list and the inner loop runs once — the no-splice case is
        # naming-preserving so smoke tests that look up
        # f"{wall_name}_BottomPlate_NN" by name still pass.
        n_bot_pieces = len(bot_pieces)
        for i in range(bottom_plate_count):
            z_m = i * thickness_in * INCH
            for piece_idx, (px_start, px_end) in enumerate(bot_pieces, start=1):
                piece_length_in = px_end - px_start
                piece_stock_in = templates.select_stock_length_in(
                    nominal, piece_length_in,
                )
                piece_stock_ft = int(round(piece_stock_in / 12))
                piece_label = templates.lumber_cutlist_label(
                    nominal, piece_stock_ft, 'HORIZONTAL',
                )
                piece_mesh_name = (
                    f"praxova_mesh_wall_plate_{nominal}_"
                    f"{_fmt_inches(piece_length_in)}"
                )
                piece_mesh = _get_or_make_mesh(
                    piece_mesh_name,
                    (piece_length_in, width_in, thickness_in),
                )
                piece_suffix = "" if n_bot_pieces == 1 else f"_p{piece_idx}"
                obj = _make_framing_object(
                    context, piece_mesh,
                    f"{wall_name}_BottomPlate_{i + 1:02d}{piece_suffix}",
                    (px_start * INCH, 0.0, z_m),
                    nominal=nominal,
                    length_in=piece_length_in,
                    stock_in=piece_stock_in,
                    orientation='HORIZONTAL',
                    label=piece_label,
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

        # v0.6: corner filler studs for MAIN-role joints. One per
        # joint, parented under this (the main) wall's Empty. Same mesh
        # as the regular studs (identical cross-section + length, just a
        # different role at the corner). ABUTTING walls don't produce a
        # filler — only MAIN does, per the design's THREE_STUD spec.
        for end in ('START', 'END'):
            filler_x_in = mods[end]['filler_x']
            if filler_x_in is None:
                continue
            joint_idx = mods[end]['joint_index']
            obj = _make_framing_object(
                context, stud_mesh,
                f"CornerFiller_Joint{joint_idx:02d}",
                (filler_x_in * INCH, 0.0, z_stud_base_m),
                nominal=nominal,
                length_in=stud_length_in,
                stock_in=stud_stock_in,
                orientation='VERTICAL',
                label=stud_label,
            )
            children.append(obj)

        # v0.6.50: T-joint backing studs (this wall is wall_a / the
        # through wall). Two studs per joint flanking wall_b's end-stud
        # footprint on wall_a's interior face; both share the regular
        # wall-stud mesh (identical cross-section + length, different
        # role at the joint). Object names follow the design's
        # TBacker_Joint<NN>_<side> convention, parallel to v0.6's
        # CornerFiller_Joint<NN>. The cut list counts these as
        # additional studs in the wall (sharing stud_label), so they
        # aggregate naturally into the ORDER SUMMARY's stud count.
        for backing in backing_studs:
            obj = _make_framing_object(
                context, stud_mesh,
                f"TBacker_Joint{backing['joint_index']:02d}_{backing['side']}",
                (backing['x'] * INCH, 0.0, z_stud_base_m),
                nominal=nominal,
                length_in=stud_length_in,
                stock_in=stud_stock_in,
                orientation='VERTICAL',
                label=stud_label,
            )
            children.append(obj)

        # Top plates stacked from (height - top_count * thickness) up.
        # v0.6: lower top plate(s) shorten at ABUTTING ends (matching
        # the bottom plate). v0.6.30/31: cap plate inverts — pulled
        # INBOARD at MAIN ends to leave room for the abutting wall's
        # cap to lap onto the main's lower top at the corner cell, and
        # reaches the wall edge at ABUTTING ends (the lap happens
        # INSIDE the abutting wall's own [0, paired_t] strip in world
        # space). v0.6.40: ranges come from plate_effective_ranges;
        # each plate may be split into multiple cut pieces by the
        # splice planner (above). Lower top and cap can have different
        # piece counts — they're planned independently, with the cap's
        # plan offset ≥24" from the lower top's splice xs per IRC
        # R602.3.2.
        z_top_base_m = (height_in - top_plate_count * thickness_in) * INCH
        n_lower_pieces = len(lower_top_pieces)
        n_cap_pieces = len(cap_pieces)
        for i in range(top_plate_count):
            is_cap = (i == top_plate_count - 1)
            z_m = z_top_base_m + i * thickness_in * INCH
            pieces = cap_pieces if is_cap else lower_top_pieces
            n_pieces = n_cap_pieces if is_cap else n_lower_pieces
            for piece_idx, (px_start, px_end) in enumerate(pieces, start=1):
                piece_length_in = px_end - px_start
                piece_stock_in = templates.select_stock_length_in(
                    nominal, piece_length_in,
                )
                piece_stock_ft = int(round(piece_stock_in / 12))
                piece_label = templates.lumber_cutlist_label(
                    nominal, piece_stock_ft, 'HORIZONTAL',
                )
                piece_mesh_name = (
                    f"praxova_mesh_wall_plate_{nominal}_"
                    f"{_fmt_inches(piece_length_in)}"
                )
                piece_mesh = _get_or_make_mesh(
                    piece_mesh_name,
                    (piece_length_in, width_in, thickness_in),
                )
                piece_suffix = "" if n_pieces == 1 else f"_p{piece_idx}"
                obj = _make_framing_object(
                    context, piece_mesh,
                    f"{wall_name}_TopPlate_{i + 1:02d}{piece_suffix}",
                    (px_start * INCH, 0.0, z_m),
                    nominal=nominal,
                    length_in=piece_length_in,
                    stock_in=piece_stock_in,
                    orientation='HORIZONTAL',
                    label=piece_label,
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
        # v0.6.40: splice info. Total piece count exceeds plate stack
        # count when any plate was spliced. n_splices is the count of
        # splice joints (butt joints between pieces of the same plate
        # role within a single contiguous range), per stack level.
        # Surface it so the user notices the splice without having to
        # inspect the cut list.
        #
        # v0.6.50: per plate role, splices_per_role = total pieces -
        # number of sub-ranges. For single-range plates (always true
        # for BOTTOM and LOWER_TOP; true for CAP on L-corner-only and
        # no-joint walls) this reduces to len(pieces) - 1, matching
        # v0.6.41. For multi-range CAP (T-joint notches on wall_a),
        # the notch boundaries between sub-ranges are NOT splices —
        # they're structural gaps where wall_b's cap lands on wall_a's
        # lower top. Subtracting len(plate_ranges['CAP']) excludes
        # those notch boundaries from the splice count.
        n_splices = (
            bottom_plate_count * (len(bot_pieces) - len(plate_ranges['BOTTOM']))
            + (top_plate_count - 1) * (len(lower_top_pieces) - len(plate_ranges['LOWER_TOP']))
            + (len(cap_pieces) - len(plate_ranges['CAP']))
        )
        splice_suffix = (
            f" ({n_splices} plate splice{'s' if n_splices != 1 else ''})"
            if n_splices
            else ""
        )
        self.report(
            {'INFO'},
            f"Framed {wall_name}: {n_studs} studs "
            f"({nominal} x {_fmt_inches(stud_length_in)}\") + "
            f"{n_plates} plates ({nominal} x {_fmt_inches(length_in)}\")"
            f"{splice_suffix}{opening_suffix}.",
        )
        return {'FINISHED'}


# ===========================================================================
# Building / Level container operators (v0.6)
# ===========================================================================

import re  # noqa: E402  (local to v0.6 helpers; module already imports bpy)


_BUILDING_NAME_PATTERN = re.compile(r'^Building_(\d+)$')
_LEVEL_NAME_PATTERN = re.compile(r'^Level_(\d+)$')


def _next_indexed_name(existing_names, pattern: re.Pattern, prefix: str) -> str:
    """Pick the lowest unused N for f"{prefix}_NN" given existing names.

    Gap-filling: if Building_01 and Building_03 exist, returns
    Building_02. Mirrors templates.next_wall_name's behavior so all
    auto-numbered Praxova Empties share the same naming UX.
    """
    used: set[int] = set()
    for name in existing_names:
        m = pattern.match(name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"{prefix}_{n:02d}"


def _next_building_name(context) -> str:
    return _next_indexed_name(
        {o.name for o in context.scene.objects},
        _BUILDING_NAME_PATTERN,
        "Building",
    )


def _next_level_name(building) -> str:
    """Next Level_NN within a Building's children only.

    Levels are scoped to their Building so two Buildings can each have
    their own Level_01, Level_02, ... rather than sharing a global pool.
    """
    return _next_indexed_name(
        {child.name for child in building.children},
        _LEVEL_NAME_PATTERN,
        "Level",
    )


def _set_active_only(context, obj):
    """Deselect everything, then select + activate `obj`. Mirrors the
    selection pattern used at the end of frame_wall."""
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


class PRAXOVA_OT_add_building(bpy.types.Operator):
    """Create a new Building Empty with a default Level under it.

    The Building Empty hosts no geometry of its own — it's a grouping
    container. Walls created via Frame Wall while a Level is active
    are parented to that Level (so they inherit the Building's
    transform), and joints between those walls live on the Level's
    PraxovaLevelProps.joints CollectionProperty.

    Visual distinction: Building uses CUBE display, Level uses
    SINGLE_ARROW (up), wall Empties keep their v0.5 PLAIN_AXES — three
    different glyphs in the viewport for the three roles in the
    hierarchy.

    After creation, the scene's active_building and active_level both
    point at the new objects, and the Building Empty becomes the active
    object. The next Frame Wall click (with the user having selected
    the Level afterward) creates the first wall.
    """

    bl_idname = "praxova.add_building"
    bl_label = "Add Building"
    bl_description = (
        "Create a new Building Empty with a default Level under it. "
        "Sets the scene's active Building and active Level pointers."
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sp = context.scene.praxova_framing

        building_name = _next_building_name(context)
        building = bpy.data.objects.new(building_name, None)
        building.empty_display_type = 'CUBE'
        building.empty_display_size = 1.0
        building.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(building)
        building.praxova_building.is_building = True
        # default_corner_style stays at 'THREE_STUD' (only v0.6 option).

        level_name = _next_level_name(building)
        level = bpy.data.objects.new(level_name, None)
        level.empty_display_type = 'SINGLE_ARROW'
        level.empty_display_size = 0.75
        level.location = (0.0, 0.0, 0.0)
        context.collection.objects.link(level)
        level.parent = building
        level.praxova_level.is_level = True
        level.praxova_level.level_index = 0
        # level_height_in stays at 96.0 default.

        sp.active_building = building
        sp.active_level = level

        _set_active_only(context, building)

        self.report(
            {'INFO'},
            f"Created {building_name} + {level_name} (active)",
        )
        return {'FINISHED'}


class PRAXOVA_OT_add_level(bpy.types.Operator):
    """Add a new Level under the scene's active Building.

    level_index is auto-assigned to one higher than the highest existing
    level_index in this Building's children — so the new Level slots in
    above the previous top. v0.6 only frames one Level at a time, but
    the data structure supports multi-story for v0.8+.
    """

    bl_idname = "praxova.add_level"
    bl_label = "Add Level"
    bl_description = "Add a new Level under the active Building"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sp = context.scene.praxova_framing
        return (
            sp.active_building is not None
            and getattr(sp.active_building, 'praxova_building', None) is not None
            and sp.active_building.praxova_building.is_building
        )

    def execute(self, context):
        sp = context.scene.praxova_framing
        building = sp.active_building

        existing_indices = [
            child.praxova_level.level_index
            for child in building.children
            if (getattr(child, 'praxova_level', None) is not None
                and child.praxova_level.is_level)
        ]
        next_index = (max(existing_indices) + 1) if existing_indices else 0

        level_name = _next_level_name(building)
        level = bpy.data.objects.new(level_name, None)
        level.empty_display_type = 'SINGLE_ARROW'
        level.empty_display_size = 0.75
        level.location = (0.0, 0.0, float(next_index) * 0.1)
        context.collection.objects.link(level)
        level.parent = building
        level.praxova_level.is_level = True
        level.praxova_level.level_index = next_index

        sp.active_level = level
        _set_active_only(context, level)

        self.report(
            {'INFO'},
            f"Created {level_name} (index {next_index}) under {building.name}",
        )
        return {'FINISHED'}


# ===========================================================================
# Joint management operators (v0.6)
# ===========================================================================

class PRAXOVA_OT_add_joint(bpy.types.Operator):
    """Append a new joint to the active Level's joints collection.

    Default joint type is L_CORNER (only v0.6 type). wall_a and wall_b
    start unset — the user picks them in the Building tab's joint
    detail panel (commit 6). frame_building validates that both are set
    before re-framing.
    """

    bl_idname = "praxova.add_joint"
    bl_label = "Add Joint"
    bl_description = "Append a new joint to the active Level"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sp = context.scene.praxova_framing
        return (
            sp.active_level is not None
            and getattr(sp.active_level, 'praxova_level', None) is not None
            and sp.active_level.praxova_level.is_level
        )

    def execute(self, context):
        sp = context.scene.praxova_framing
        level = sp.active_level
        joints = level.praxova_level.joints
        joints.add()
        # All fields take PropertyGroup defaults: joint_type='L_CORNER',
        # wall_a/wall_b unset, wall_a_end='END', wall_b_end='START',
        # corner_style='AUTO', extending_wall='AUTO'. The user fills
        # wall_a/wall_b in the Building tab.
        level.praxova_level.joints_active = len(joints) - 1
        return {'FINISHED'}


class PRAXOVA_OT_remove_joint(bpy.types.Operator):
    """Remove the active joint from the active Level."""

    bl_idname = "praxova.remove_joint"
    bl_label = "Remove Joint"
    bl_description = "Remove the active joint from the active Level"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sp = context.scene.praxova_framing
        return (
            sp.active_level is not None
            and getattr(sp.active_level, 'praxova_level', None) is not None
            and sp.active_level.praxova_level.is_level
            and len(sp.active_level.praxova_level.joints) > 0
        )

    def execute(self, context):
        sp = context.scene.praxova_framing
        level = sp.active_level
        idx = level.praxova_level.joints_active
        level.praxova_level.joints.remove(idx)
        level.praxova_level.joints_active = max(
            0, min(idx, len(level.praxova_level.joints) - 1),
        )
        return {'FINISHED'}


# ===========================================================================
# Frame Building orchestrator (v0.6)
# ===========================================================================

class PRAXOVA_OT_frame_building(bpy.types.Operator):
    """Re-frame every wall in the active Level with joint context applied.

    The orchestrator for v0.6's multi-wall workflow. Iterates the
    active Level's wall children, sets each one as the active object,
    then invokes praxova.frame_wall — which detects in-place mode +
    Level parent + joints and re-frames the wall with the appropriate
    plate/stud/filler modifications. Single source of truth for the
    joint-aware framing math: frame_wall does the work, frame_building
    just coordinates the sweep.

    Validation runs once up front (active Level set, at least one wall,
    joints pass templates.validate_joints) so a bad joint surfaces as
    a single clean error rather than per-wall noise.
    """

    bl_idname = "praxova.frame_building"
    bl_label = "Frame Building"
    bl_description = (
        "Re-frame every wall in the active Level, applying joint "
        "context (corner geometry, plate shortening, filler studs)."
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        sp = context.scene.praxova_framing
        return (
            sp.active_level is not None
            and getattr(sp.active_level, 'praxova_level', None) is not None
            and sp.active_level.praxova_level.is_level
        )

    def execute(self, context):
        sp = context.scene.praxova_framing
        level = sp.active_level

        if level is None or not level.praxova_level.is_level:
            self.report(
                {'ERROR'},
                "No active Level. Use the Building tab to select one.",
            )
            return {'CANCELLED'}

        # Collect this Level's wall children (Empties with is_wall=True).
        # Object iteration order on level.children is stable for a given
        # Blender session, so re-framing is deterministic.
        walls = [
            child for child in level.children
            if getattr(child, 'praxova_wall', None) is not None
            and child.praxova_wall.is_wall
        ]
        if not walls:
            self.report({'WARNING'}, "Active Level has no walls.")
            return {'CANCELLED'}

        # Joint validation runs once for the whole list. validate_joints
        # already returns "Joint N: ..." with 1-based indices that match
        # what the UI shows in the Building tab.
        ok, msg = templates.validate_joints(
            level.praxova_level.joints, walls,
        )
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        # For each wall: make it the active object, then invoke
        # frame_wall in EXEC_DEFAULT mode. frame_wall sees the wall is a
        # Praxova-managed wall under a Level with joints and applies
        # the per-end modifications via _resolve_joint_context.
        framed_count = 0
        for wall in walls:
            for o in context.selected_objects:
                o.select_set(False)
            wall.select_set(True)
            context.view_layer.objects.active = wall
            result = bpy.ops.praxova.frame_wall('EXEC_DEFAULT')
            if 'FINISHED' not in result:
                self.report(
                    {'ERROR'},
                    f"frame_wall failed for {wall.name}: {sorted(result)}",
                )
                return {'CANCELLED'}
            framed_count += 1

        # Final selection: the Level Empty, so the user can immediately
        # add more joints or run frame_building again. Matches the
        # selection convention the other v0.6 container operators use.
        _set_active_only(context, level)

        n_joints = len(level.praxova_level.joints)
        self.report(
            {'INFO'},
            f"Framed {framed_count} wall"
            f"{'s' if framed_count != 1 else ''} "
            f"with {n_joints} joint{'s' if n_joints != 1 else ''}",
        )
        return {'FINISHED'}

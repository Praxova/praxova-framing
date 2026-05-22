"""Lumber, sheet-good, and panel dimension data and mesh construction."""

import re

import bpy


# Conversion factor: meters per inch. Blender stores all lengths in meters
# internally regardless of the scene's display units.
INCH = 0.0254


# Module-level exception. Lives at the top rather than next to its single
# raise site (plan_plate_splice_pieces, v0.6.40) so it's discoverable from
# any importer that catches it — chiefly the frame_wall operator and the
# MCP bridge handler, neither of which import the splice helpers section
# directly.
class SpliceError(Exception):
    """A plate's effective range exceeds max stock but no full-height
    stud is positioned to support a code-compliant in-line splice.

    Caught by frame_wall (v0.6.40+) and surfaced via
    self.report({'ERROR'}, ...); caught by the MCP bridge handler and
    converted to INVALID_PARAMS. The message is user-facing — it
    identifies the failing plate range and whether the
    cap-vs-lower-top 24" offset rule (IRC R602.3.2) was binding.
    """


# ===========================================================================
# Lumber
# ===========================================================================

# Actual cross-section dimensions in inches: (thickness, width).
# Nominal sizes (e.g. "2x4") are rough-sawn callouts; planed dimensional
# lumber is smaller. Source: US softwood lumber standards.
#
# Order matters: this dict is iterated to build the Add menu, so listing
# small-to-large keeps the menu sorted by cross-section.
LUMBER_TYPES: dict[str, tuple[float, float]] = {
    "1x2":  (0.75, 1.5),    # furring strip
    "2x3":  (1.5, 2.5),     # interior partition / blocking
    "2x4":  (1.5, 3.5),
    "2x6":  (1.5, 5.5),
    "2x8":  (1.5, 7.25),
    "2x10": (1.5, 9.25),
    "2x12": (1.5, 11.25),
    "4x4":  (3.5, 3.5),     # post
    "4x6":  (3.5, 5.5),     # mid-weight beam / header
    "6x6":  (5.5, 5.5),     # post / heavy timber
}


# Available stock lengths in feet for each nominal size.
LENGTHS_BY_TYPE: dict[str, list[int]] = {
    "1x2":  [8],
    "2x3":  [8, 10, 12],
    "2x4":  [8, 10, 12, 14, 16],
    "2x6":  [8, 10, 12, 14, 16],
    "2x8":  [8, 10, 12, 14, 16],
    "2x10": [10, 12, 14, 16],
    "2x12": [10, 12, 14, 16],
    "4x4":  [8, 10, 12, 14, 16],
    "4x6":  [8, 10, 12, 14, 16, 20],
    "6x6":  [8, 10, 12, 14, 16, 20],
}


# v0.6.60: corner-style sets for joint-type compatibility checks.
# AUTO is intentionally absent — it's resolved upstream by
# resolve_corner_style before any code touches these sets.
# Single source of truth: resolve_corner_style, l_corner_geometry
# (the dispatcher), and validate_joints all reference these.
L_CORNER_STYLES = frozenset({'THREE_STUD', 'CALIFORNIA', 'LADDER_BLOCKING'})
T_JOINT_STYLES  = frozenset({'T_BACKING_STUDS'})


def lumber_cutlist_label(nominal: str, length_ft: int, orientation: str) -> str:
    """Build the canonical lumber cutlist label, e.g. '2x4x8 V'."""
    suffix = "V" if orientation == 'VERTICAL' else "H"
    return f"{nominal}x{length_ft} {suffix}"


# ===========================================================================
# Sheet goods (plywood, OSB)
# ===========================================================================

# Standard sheet sizes in inches: (width, length).
# Default 4x8 sheet is 48" x 96".
SHEET_SIZES: dict[str, tuple[int, int]] = {
    "4x8": (48, 96),
    # Future: "4x10": (48, 120), "4x12": (48, 144), etc.
}


# Sheet thickness call-outs and their actual thicknesses in inches.
#
# Reference standards:
#   - Plywood:  APA PS 1 / Performance Rated Panels (PRP-108)
#   - OSB:      APA PS 2 / Performance Rated Panels (PRP-108)
#
# A "1/2 inch" sheet is a Performance Category, not a literal dimension.
# Plywood and OSB at the same call-out can have different actual thicknesses;
# at 1/2" the spread is largest (15/32" plywood vs. 7/16" OSB sheathing).
# At 3/4" both materials converge on 23/32".
#
# Override these constants if your local supplier uses different stock.
SHEET_THICKNESS_ACTUAL: dict[tuple[str, str], float] = {
    ("PLYWOOD", "1/2"): 15.0 / 32.0,   # 0.46875"
    ("PLYWOOD", "3/4"): 23.0 / 32.0,   # 0.71875"
    ("OSB",     "1/2"):  7.0 / 16.0,   # 0.4375"   (most common sheathing)
    ("OSB",     "3/4"): 23.0 / 32.0,   # 0.71875"
}


SHEET_MATERIAL_LABELS: dict[str, str] = {
    "PLYWOOD": "Plywood",
    "OSB":     "OSB",
}


def sheet_cutlist_label(
    material: str,
    thickness_callout: str,
    size_key: str,
    orientation: str,
) -> str:
    """Build the canonical sheet cutlist label, e.g. '1/2" PLY 4x8 V'."""
    mat_short = "PLY" if material == "PLYWOOD" else "OSB"
    suffix = "V" if orientation == 'VERTICAL' else "H"
    return f'{thickness_callout}" {mat_short} {size_key} {suffix}'


# ===========================================================================
# Panels (metal roofing / siding)
# ===========================================================================

# Standard panel sizes: (coverage_width_inches, length_inches).
# The 36" is the on-roof coverage width *after* side-seam overlap, which is
# the dimension that matters for layout. The size key is '<width_in>x<length_ft>'
# - e.g. "36x8" is a 36"-wide panel that's 8 feet long.
PANEL_SIZES: dict[str, tuple[float, float]] = {
    "36x8":  (36.0,  96.0),
    "36x12": (36.0, 144.0),
    "36x16": (36.0, 192.0),
}


# Generic profile height per material. Real metal-panel rib geometry varies
# widely by manufacturer and profile:
#   5V crimp        ~0.5"
#   AG / corrugated ~0.75"
#   R-panel         ~1.25"
#   Standing seam   1.5"-3"
#
# v0.3.1 models panels as flat slabs of this thickness - enough visible
# presence in the viewport to avoid z-fight against sheathing, without
# committing to a specific manufacturer's rib pattern. A future patch will
# replace the slab with a proper corrugation generator and provide a
# scene-walking "refresh labels" pass to update existing tagged objects.
PANEL_MATERIAL_PROFILE: dict[str, float] = {
    "METAL": 0.75,
}


PANEL_MATERIAL_LABELS: dict[str, str] = {
    "METAL": "Metal",
}


def panel_cutlist_label(
    material: str,
    size_key: str,
    orientation: str,
) -> str:
    """Build the canonical panel cutlist label, e.g. '36" Metal x 8 V'.

    Format: '<width>" <Material> x <length_ft> <V|H>'.
    Width is in inches with a quote suffix; length is in feet (no suffix,
    matching the lumber convention where '2x4x8' implies the trailing 8
    is feet). V/H suffix is the orientation, matching lumber and sheets.
    """
    width_str, length_ft_str = size_key.split('x')
    mat_label = PANEL_MATERIAL_LABELS[material]
    suffix = "V" if orientation == 'VERTICAL' else "H"
    return f'{width_str}" {mat_label} x {length_ft_str} {suffix}'


# ===========================================================================
# Tag helpers (cross-category)
# ===========================================================================

def fill_axis_width_in(obj) -> float:
    """Return the local-Y (fill axis) width in inches for a sheet or panel.

    The Fill (Duplicate Edge-to-Edge) operator places copies along local +Y
    using this dimension as the step size. The same value also drives the
    fill-span -> count conversion in the N-panel's update callback.

    Defensive against tags that point to retired or unknown size keys:
    returns 0.0 in that case. Returns 0.0 for objects that aren't Praxova
    SHEETs or PANELs - lumber is intentionally not supported here (its
    local-Y is the cross-section width, not a meaningful fill spacing).
    """
    tag = getattr(obj, "praxova_lumber", None)
    if tag is None or not tag.is_lumber:
        return 0.0
    if tag.category == 'SHEET':
        size = SHEET_SIZES.get(tag.sheet_size_key)
        return float(size[0]) if size else 0.0
    if tag.category == 'PANEL':
        size = PANEL_SIZES.get(tag.panel_size_key)
        return float(size[0]) if size else 0.0
    return 0.0


# ===========================================================================
# Mesh construction
# ===========================================================================

def make_box_mesh(
    name: str,
    dims_inches: tuple[float, float, float],
) -> bpy.types.Mesh:
    """Build a box mesh with min corner at the origin.

    Args:
        name: Name for the new mesh datablock.
        dims_inches: (x, y, z) dimensions in inches.

    Returns:
        A new bpy.types.Mesh datablock owned by bpy.data.meshes.
    """
    x, y, z = (d * INCH for d in dims_inches)

    # Eight corners. Min corner at origin, max at (x, y, z).
    verts = [
        (0, 0, 0), (x, 0, 0), (x, y, 0), (0, y, 0),  # 0..3: bottom (z=0)
        (0, 0, z), (x, 0, z), (x, y, z), (0, y, z),  # 4..7: top    (z=Z)
    ]
    # Quads ordered CCW when viewed from outside, so face normals point out.
    faces = [
        (0, 3, 2, 1),  # -Z bottom
        (4, 5, 6, 7),  # +Z top
        (0, 1, 5, 4),  # -Y front
        (1, 2, 6, 5),  # +X right
        (2, 3, 7, 6),  # +Y back
        (3, 0, 4, 7),  # -X left
    ]

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    return mesh


# ===========================================================================
# Composite framing helpers (v0.4)
# ===========================================================================

# Pure functions consumed by ops_frame.PRAXOVA_OT_frame_wall. They're kept
# pure (no bpy. references) so the math can be reasoned about without
# Blender in the loop. The operator handles the bpy. plumbing - mesh
# construction, tagging, parenting, scene linking.

_WALL_NAME_PATTERN = re.compile(r'^Wall_(\d+)$')


def next_wall_name(existing_names) -> str:
    """Return the next available 'Wall_NN' name not in existing_names.

    Picks the lowest unused positive integer N and formats as 'Wall_NN'
    with two-digit zero-padding for N < 100. Fills gaps: if Wall_01 and
    Wall_03 exist, returns 'Wall_02'. Gap-filling matches what a human
    expects when walls are deleted and re-created; the alternative of
    always picking max(N)+1 leaves growing holes in the numbering.

    Args:
        existing_names: iterable of strings, typically
            {obj.name for obj in bpy.context.scene.objects}.

    Returns:
        A string like 'Wall_01' or 'Wall_42'. For N >= 100, the leading
        zero pad is dropped naturally by Python's :02d format spec
        (e.g. 'Wall_100' rather than 'Wall_00').
    """
    used: set[int] = set()
    for name in existing_names:
        m = _WALL_NAME_PATTERN.match(name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"Wall_{n:02d}"


def stud_positions(
    length_in: float,
    spacing_oc_in: float,
    stud_thickness_in: float,
) -> list[float]:
    """Return x-coordinates of the LEFT EDGE of each stud in a wall.

    Standard sheathing-aligned convention:
      - End studs are flush with the wall ends: left end stud at x=0
        (right edge at stud_thickness), right end stud at
        x=(length - stud_thickness) (right edge at length).
      - Intermediate studs are at on-center spacing measured from x=0:
        centers at spacing, 2*spacing, 3*spacing, ...
      - An intermediate stud is included only if its right edge is
        strictly less than the right end stud's left edge. The final
        bay before the right end stud is allowed to be tight (narrower
        than spacing_oc); this is normal for wall lengths that aren't
        a multiple of spacing_oc and preserves 4'/8' sheathing seams.

    The function does not validate that length_in >= 2 * stud_thickness_in
    or that any of the inputs are positive - the caller is responsible
    for sane bounds. For absurd inputs (e.g. length < stud_thickness)
    the returned list will contain coincident or negative-position
    entries, which the caller should detect upstream.

    Args:
        length_in: wall length in inches.
        spacing_oc_in: on-center stud spacing in inches.
        stud_thickness_in: stud cross-section thickness along the wall
            length axis (e.g. 1.5 for a 2x4).

    Returns:
        List of float x-coordinates, sorted ascending. Always contains
        at least 2 entries (the two end studs).

    Examples:
        96" wall, 16 OC, 1.5" thick studs -> 7 studs:
            [0.0, 15.25, 31.25, 47.25, 63.25, 79.25, 94.5]
        (left-edge positions; centers are at 0.75, 16, 32, 48, 64, 80, 95.25)
    """
    half_t = stud_thickness_in / 2.0
    right_end_left_edge = length_in - stud_thickness_in

    positions: list[float] = [0.0]
    c = spacing_oc_in  # center of the next intermediate stud
    while c + half_t < right_end_left_edge:
        positions.append(c - half_t)
        c += spacing_oc_in
    positions.append(right_end_left_edge)
    return positions


def select_stock_length_in(nominal: str, cut_length_in: float) -> float:
    """Return the smallest stock length in inches that fits cut_length_in.

    Picks from LENGTHS_BY_TYPE[nominal] (feet) and converts to inches.
    Used by frame_wall to determine the purchased stock for each cut piece.

    Args:
        nominal: lumber size key (must be in LUMBER_TYPES / LENGTHS_BY_TYPE).
        cut_length_in: required cut length in inches.

    Returns:
        Smallest stock length in inches that is >= cut_length_in. For a
        91.5" cut of 2x4, returns 96.0 (8 ft). For a 108" cut of 2x4,
        returns 120.0 (10 ft).

    Raises:
        ValueError: if the nominal is unknown or no available stock length
            is long enough to accommodate the cut.
    """
    available_ft = LENGTHS_BY_TYPE.get(nominal)
    if not available_ft:
        raise ValueError(f"Unknown or empty stock list for nominal {nominal!r}")
    available_in = sorted(ft * 12 for ft in available_ft)
    for stock_in in available_in:
        if stock_in >= cut_length_in:
            return float(stock_in)
    raise ValueError(
        f"No stock length for {nominal} fits a cut of {cut_length_in}\". "
        f"Available stock (ft): {sorted(available_ft)}."
    )


# ===========================================================================
# Opening helpers (v0.5)
# ===========================================================================

# Pure functions consumed by ops_frame.PRAXOVA_OT_frame_wall when the
# scene has one or more wall openings. Same separation-of-concerns as the
# v0.4 composite helpers above: no bpy. references, so the math can be
# reasoned about (and unit-tested) without Blender in the loop. The
# operator does the bpy. plumbing — mesh construction, tagging, parenting.
#
# Geometry conventions (single wall, origin at z=0 = bottom of wall, x=0
# = wall left edge, y=0 = wall front face):
#   - Plate / stud / rough-sill thickness is LUMBER_TYPES[wall_nominal][0]
#     (1.5" for 2x walls — the design's implicit target).
#   - Header laid on edge: vertical extent = LUMBER_TYPES[header_nominal][1]
#     (the wider cross-section dim — 3.5" for 2x4, 5.5" for 2x6, etc.).
#   - Header Y stackup hardcoded to 1.5 + 0.5 + 1.5 = 3.5" flush to y=0
#     regardless of wall depth, matching the design's "(2) 2x + 1/2" ply
#     spacer" residential convention. For deeper walls the gap is on +Y.

# Spacer plywood thickness in inches. 1/2" plywood scrap from sheathing
# offcuts is the residential framing convention for header build-up.
_HEADER_SPACER_THICKNESS_IN = 0.5

# Minimum cripple length below which the zone is suppressed entirely
# (avoids placing absurdly short pieces).
_MIN_CRIPPLE_LENGTH_IN = 1.5


def recommend_jack_count(ro_width_in: float) -> int:
    """Jack stud count per side for a rough opening.

    Returns 2 for openings >= 72" (6'), else 1. IRC R602.7 convention for
    typical 2x4/2x6 walls with conventional loading. The frame_wall
    operator uses this as the default when a new opening is added; the
    user can override per-opening via the UIList.
    """
    return 2 if ro_width_in >= 72.0 else 1


def opening_framing_layout(
    opening,
    wall_nominal: str,
    wall_height_in: float,
    top_plate_count: int,
    bottom_plate_count: int,
) -> dict:
    """Compute all x/z coordinates and cut lengths for one opening.

    Pure geometry: takes an opening descriptor (anything with the seven
    PraxovaWallOpening fields — opening_type, x_offset_in, ro_width_in,
    ro_height_in, sill_height_in, header_nominal, jack_count) plus the
    wall's scalar parameters, and returns a dict with everything the
    operator needs to place king studs, jacks, header members, header
    spacer, optional rough sill, and optional cripples.

    The returned dict's key set matches the design doc's "Opening
    framing layout" table. For doors (opening_type == 'DOOR'),
    rough_sill_* and cripple_bottom_zone tuple entries are None. For
    cripple zones whose vertical length falls below the minimum
    (_MIN_CRIPPLE_LENGTH_IN), the corresponding tuple is (None, None).

    Args:
        opening: duck-typed opening with seven PraxovaWallOpening fields.
        wall_nominal: lumber size key for the wall (e.g. "2x4").
        wall_height_in: total wall height in inches (floor to top of
            top plate stack).
        top_plate_count: number of top plates.
        bottom_plate_count: number of bottom plates.

    Returns:
        Dict per the design doc's geometry table. All lengths and coords
        are in inches.
    """
    t = LUMBER_TYPES[wall_nominal][0]
    header_member_z_height = LUMBER_TYPES[opening.header_nominal][1]

    opening_type = opening.opening_type
    x_offset = float(opening.x_offset_in)
    ro_width = float(opening.ro_width_in)
    ro_height = float(opening.ro_height_in)
    jack_count = int(opening.jack_count)
    # sill_height is wall-relative; for doors it's pinned to 0 regardless
    # of the field value (the design says it's ignored for doors).
    sill_height = (
        float(opening.sill_height_in) if opening_type == 'WINDOW' else 0.0
    )

    # --- Z coords (origin at wall bottom) ---
    z_bottom_of_top_plates = wall_height_in - top_plate_count * t
    z_top_of_bottom_plates = bottom_plate_count * t
    z_header_bottom = sill_height + ro_height
    z_header_top = z_header_bottom + header_member_z_height

    if opening_type == 'WINDOW':
        z_rough_sill_top = sill_height
        z_rough_sill_bottom = sill_height - t
        rough_sill_x_start = x_offset
        rough_sill_x_end = x_offset + ro_width
    else:
        z_rough_sill_top = None
        z_rough_sill_bottom = None
        rough_sill_x_start = None
        rough_sill_x_end = None

    # --- X coords (left to right): king | jacks | RO | jacks | king ---
    king_left_x = x_offset - jack_count * t - t
    jack_left_xs = [x_offset - i * t for i in range(1, jack_count + 1)]
    jack_right_xs = [
        x_offset + ro_width + i * t for i in range(0, jack_count)
    ]
    king_right_x = x_offset + ro_width + jack_count * t + t

    # Header sits on the jacks: spans outer left jack left edge to outer
    # right jack right edge.
    header_x_start = x_offset - jack_count * t
    header_x_end = x_offset + ro_width + jack_count * t
    header_member_length_in = header_x_end - header_x_start

    # Header Y stackup: member 1 at y=[0, 1.5], spacer at y=[1.5, 2.0],
    # member 2 at y=[2.0, 3.5]. Hardcoded per the design.
    spacer_y_start = t  # for 2x walls this is 1.5
    spacer_y_end = spacer_y_start + _HEADER_SPACER_THICKNESS_IN

    # --- Cripple zones ---
    top_zone_length = z_bottom_of_top_plates - z_header_top
    if top_zone_length >= _MIN_CRIPPLE_LENGTH_IN:
        cripple_top_zone = (z_header_top, z_bottom_of_top_plates)
    else:
        cripple_top_zone = (None, None)

    if opening_type == 'WINDOW':
        bottom_zone_length = z_rough_sill_bottom - z_top_of_bottom_plates
        if bottom_zone_length >= _MIN_CRIPPLE_LENGTH_IN:
            cripple_bottom_zone = (z_top_of_bottom_plates, z_rough_sill_bottom)
        else:
            cripple_bottom_zone = (None, None)
    else:
        cripple_bottom_zone = (None, None)

    # --- Cut lengths ---
    # Kings span between top of bottom plates and bottom of top plates,
    # same as regular wall studs (shared mesh).
    king_length_in = wall_height_in - (top_plate_count + bottom_plate_count) * t
    # Jacks reach from top of bottom plates up to header bottom.
    jack_length_in = z_header_bottom - z_top_of_bottom_plates

    return {
        'king_left_x': king_left_x,
        'king_right_x': king_right_x,
        'jack_left_xs': jack_left_xs,
        'jack_right_xs': jack_right_xs,
        'header_x_start': header_x_start,
        'header_x_end': header_x_end,
        'header_z_top': z_header_top,
        'header_z_bottom': z_header_bottom,
        'header_member_length_in': header_member_length_in,
        'spacer_y_start': spacer_y_start,
        'spacer_y_end': spacer_y_end,
        'rough_sill_x_start': rough_sill_x_start,
        'rough_sill_x_end': rough_sill_x_end,
        'rough_sill_z_top': z_rough_sill_top,
        'rough_sill_z_bottom': z_rough_sill_bottom,
        'king_length_in': king_length_in,
        'jack_length_in': jack_length_in,
        'cripple_top_zone': cripple_top_zone,
        'cripple_bottom_zone': cripple_bottom_zone,
    }


def filter_studs_around_openings(
    stud_positions: list[float],
    nominal_thickness_in: float,
    openings,
    layout_per_opening: list[dict],
) -> list[float]:
    """Drop regular OC stud positions that collide with any king bracket.

    A stud at left-edge x of thickness t collides with an opening's king
    bracket [king_left_x, king_right_x] when the standard interval-
    overlap test passes: (x + t > king_left_x) AND (x < king_right_x).
    Returns the subset of stud_positions that don't collide with any
    opening's king bracket.

    The openings argument is accepted for interface parity with
    validate_openings (call sites typically pass the same list) but
    everything needed for the collision check is in layout_per_opening.

    Args:
        stud_positions: left-edge x-coords of regular OC studs.
        nominal_thickness_in: stud thickness (e.g. 1.5 for 2x4).
        openings: opening descriptors (parallel to layout_per_opening).
        layout_per_opening: list of dicts from opening_framing_layout,
            one per opening, in the same order as openings.

    Returns:
        Subset of stud_positions, in input order, that do not overlap
        any opening's king bracket range.
    """
    del openings  # interface parity; unused inside this function
    out: list[float] = []
    for x in stud_positions:
        x_right = x + nominal_thickness_in
        collides = False
        for layout in layout_per_opening:
            if (
                x_right > layout['king_left_x']
                and x < layout['king_right_x']
            ):
                collides = True
                break
        if not collides:
            out.append(x)
    return out


def filter_studs_around_intervals(
    stud_xs: list[float],
    stud_thickness_in: float,
    blocking_intervals: list[tuple[float, float]],
) -> list[float]:
    """Drop stud positions whose [x, x+t] footprint overlaps any blocking interval.

    Generalization of filter_studs_around_openings — takes raw
    (start_x, end_x) intervals rather than opening layout dicts.
    Used by frame_wall (v0.6.50) to filter OC studs around T-joint
    backing-stud footprints; could later be reused as a building
    block for refactoring filter_studs_around_openings if the
    two filters' shapes converge further.

    Args:
        stud_xs: left-edge x-coords of studs to filter.
        stud_thickness_in: stud x-extent.
        blocking_intervals: list of (start_x, end_x) intervals. A
            stud is dropped if its [x, x+t] overlaps ANY interval
            (standard half-open interval overlap test: x + t >
            start AND x < end).

    Returns:
        Subset of stud_xs, in input order, that don't overlap any
        blocking interval. Empty blocking_intervals returns stud_xs
        unchanged.
    """
    if not blocking_intervals:
        return list(stud_xs)
    out: list[float] = []
    for x in stud_xs:
        x_right = x + stud_thickness_in
        collides = False
        for b_start, b_end in blocking_intervals:
            if x_right > b_start and x < b_end:
                collides = True
                break
        if not collides:
            out.append(x)
    return out


def validate_openings(
    openings,
    wall_length_in: float,
    wall_height_in: float,
    wall_nominal: str,
    top_plate_count: int,
    bottom_plate_count: int,
) -> tuple[bool, str]:
    """Cross-check the opening list against the wall's scalar params.

    Returns (True, "") on success, or (False, error_message) on the
    first failure. Error messages use 1-based opening indices ("Opening 2
    overlaps Opening 1") matching the design doc and what the UI shows
    in the live preview line.

    Checks in order:
      1. Each opening's king bracket is within [0, wall_length_in].
      2. No two king brackets overlap (pairwise interval test).
      3. Each opening's header top fits under the top plate stack.
      4. For windows: rough sill bottom clears the bottom plate stack.
    """
    t = LUMBER_TYPES[wall_nominal][0]
    z_top_plates_bottom = wall_height_in - top_plate_count * t
    z_bottom_plates_top = bottom_plate_count * t

    # Pre-compute per-opening king brackets so checks 1 and 2 can reuse them.
    brackets: list[tuple[float, float]] = []
    for op in openings:
        jc = int(op.jack_count)
        x_off = float(op.x_offset_in)
        ro_w = float(op.ro_width_in)
        kl = x_off - jc * t - t
        kr = x_off + ro_w + jc * t + t
        brackets.append((kl, kr))

    # 1. Each opening within the wall.
    for i, (kl, kr) in enumerate(brackets):
        if kl < 0 or kr > wall_length_in:
            return (False, f"Opening {i + 1} extends past wall edge")

    # 2. No two king brackets overlap. Pairwise i<j; report higher index
    #    as overlapping the lower.
    n = len(brackets)
    for i in range(n):
        kl_i, kr_i = brackets[i]
        for j in range(i + 1, n):
            kl_j, kr_j = brackets[j]
            if kr_j > kl_i and kl_j < kr_i:
                return (
                    False,
                    f"Opening {j + 1} overlaps Opening {i + 1}",
                )

    # 3. Header top fits under top plates.
    for i, op in enumerate(openings):
        sill = (
            float(op.sill_height_in) if op.opening_type == 'WINDOW' else 0.0
        )
        z_header_bottom = sill + float(op.ro_height_in)
        z_header_top = z_header_bottom + LUMBER_TYPES[op.header_nominal][1]
        if z_header_top > z_top_plates_bottom:
            return (
                False,
                f"Opening {i + 1} too tall to fit under top plates",
            )

    # 4. Windows: rough sill bottom clears the bottom plate stack.
    for i, op in enumerate(openings):
        if op.opening_type != 'WINDOW':
            continue
        if float(op.sill_height_in) - t < z_bottom_plates_top:
            return (
                False,
                f"Opening {i + 1} rough sill overlaps bottom plate stack",
            )

    return (True, "")


def redistribute_openings_evenly(openings, wall_length_in: float) -> None:
    """Reposition all openings to evenly-spaced layout.

    Sets opening.x_offset_in = (wall_length × (i+1) / (n+1)) - (ro_width / 2)
    for each opening i in 0..n-1 (where n = number of openings). Used by
    add_door, add_window, and the explicit Distribute Evenly button.
    Mutates the CollectionProperty in place. Not pure: writes to the
    opening fields. Still has no bpy. calls — touches PropertyGroup
    attributes only, like opening_framing_layout above.
    """
    n = len(openings)
    if n == 0:
        return
    for i, opening in enumerate(openings):
        center_x = wall_length_in * (i + 1) / (n + 1)
        opening.x_offset_in = max(0.0, center_x - opening.ro_width_in / 2.0)


# ===========================================================================
# Joint helpers (v0.6)
# ===========================================================================

# Pure functions consumed by the v0.6 joint-aware frame_wall and the
# frame_building orchestrator. No bpy.ops, no scene mutation — just
# attribute access on the duck-typed Joint / Wall PropertyGroups (the
# same "pure" sense as the v0.5 opening helpers). reframe_wall_in_place
# lives in ops_frame.py since it does scene mutation.
#
# Terminology (v0.6.25 onward):
#   MAIN wall      the one whose lower plates run full length through
#                  the corner, gets the interior corner filler stud,
#                  and keeps its end stud flush with the wall end.
#                  Determined by resolve_extending_wall — NOT by
#                  wall_a/wall_b assignment in the joint.
#   ABUTTING wall  the other wall in the joint. Its lower plates are
#                  shortened by MAIN's wall thickness at the joint end
#                  and its end stud is moved inboard so it lands flush
#                  with the shortened plates.
#   "extending"    synonym for MAIN under the v0.6.25 semantics. The
#                  is_extending flag carried on context entries through
#                  v0.6.31 was redundant with role=='MAIN' and was
#                  removed in v0.6.40 along with the per-end plate
#                  offset helpers it served.


def resolve_extending_wall(joint, wall_a, wall_b) -> str:
    """Pick which wall is the MAIN wall for this joint.

    Returns 'A' (wall_a is MAIN) or 'B' (wall_b is MAIN). This is the
    single source of truth — both compute_wall_joint_context (during
    framing) and the Building tab's live resolved-MAIN readout call
    in here and branch on the result.

    Semantics:
      'A' or 'B' (explicit): honored verbatim. v0.6.0 stored these
        but ignored them at frame time — fixed here in v0.6.25.
      'AUTO': picks the LONGER wall. Matches the residential
        convention that longer walls form the outside and shorter
        walls butt in. Equal-length walls tie-break to wall_a (the
        user has already declared which is wall_a).

    Args:
        joint: the PraxovaJoint PropertyGroup item.
        wall_a, wall_b: Object refs to the two walls in the joint
            (joint.wall_a, joint.wall_b — passed in explicitly so the
            caller can reuse the lookups for other purposes without
            this function re-reading the PointerProperty).
    """
    explicit = joint.extending_wall
    if explicit == 'A':
        return 'A'
    if explicit == 'B':
        return 'B'
    # AUTO: LONGER wall is MAIN (residential convention).
    wall_a_length = wall_a.praxova_wall.wall_length_in
    wall_b_length = wall_b.praxova_wall.wall_length_in
    if wall_a_length > wall_b_length:
        return 'A'
    if wall_b_length > wall_a_length:
        return 'B'
    return 'A'  # tie-break to wall_a


def resolve_corner_style(joint, building_default: str) -> str:
    """Resolve a joint's corner_style based on joint_type.

    Semantics:
      AUTO + L_CORNER → building_default (one of THREE_STUD,
        CALIFORNIA, or LADDER_BLOCKING per PraxovaBuildingProps's
        default_corner_style; v0.6.60 widened this from THREE_STUD-only).
      AUTO + T_JOINT  → 'T_BACKING_STUDS' (unconditional in v0.6.5x —
        only T-joint style available; the Building's
        default_corner_style stays L-only, with a sibling
        default_t_style field deferred until a second T-joint style
        ships).
      Explicit values (THREE_STUD / CALIFORNIA / LADDER_BLOCKING /
        T_BACKING_STUDS) honored verbatim — validate_joints rejects
        type/style mismatches up front so this function doesn't have
        to defend against them.
    """
    if joint.corner_style != 'AUTO':
        return joint.corner_style
    if joint.joint_type == 'T_JOINT':
        return 'T_BACKING_STUDS'
    return building_default


# v0.6.50: canonical multi-range plate-range helper.
#
# Returns the list of disjoint (start_x, end_x) ranges for a plate
# after joint modifications at both ends + interior T-joint cap
# notches, in the wall's local frame (x = 0 at the wall's START
# edge, x = wall_length_in at the END edge). One element per
# contiguous piece; for plates without interior notches (every L-
# corner-only wall and every wall without joints) the list has
# exactly one element, so the v0.6.41 single-tuple contract is a
# proper subset of the new shape.
#
# The list-of-ranges return is what makes cap notching by T joints
# tractable: each disjoint range goes through plan_plate_splice_pieces
# independently; the splice planner doesn't need to know T joints
# exist, just gets called once per range. Bottom and lower top
# plates ignore mid_joints and stay single-range — they're continuous
# through T joints by design.
#
# Per-end behavior depends on (role, joint_type, plate_role):
#
#   role        joint_type   plate_role         start/end_x behavior
#   --------    ----------   ----------------   --------------------
#   MAIN        L_CORNER     BOTTOM, LOWER_TOP  wall edge
#   MAIN        L_CORNER     CAP                shortened INBOARD by paired_t
#   ABUTTING    L_CORNER     BOTTOM, LOWER_TOP  shortened INBOARD by paired_t
#   ABUTTING    L_CORNER     CAP                wall edge (lap inside)
#   ABUTTING    T_JOINT      BOTTOM, LOWER_TOP  wall edge (no shortening —
#                                               wall_b butts against wall_a)
#   ABUTTING    T_JOINT      CAP                extended OUTBOARD by paired_t
#                                               (wall_b's cap laps onto
#                                               wall_a's lower top plate)
#   MAIN        T_JOINT      —                  not applicable (T joints
#                                               have a fixed through/abutting
#                                               topology; through wall is
#                                               wall_a, not assigned a role
#                                               at its ends by joints)
#   None        n/a          any                wall edge (no joint at end)
#
# OUTBOARD extensions yield negative start_x (joint at START) or
# end_x > wall_length_in (joint at END). Intentional — the operator's
# placement loop handles negative-start meshes naturally (mesh length =
# end - start, position = (start, ...)); wall_b's cap object lands with
# its origin past the wall Empty's footprint by paired_t.
#
# Both role_at_* params accept 'MAIN', 'ABUTTING', or None (no joint at
# that end). paired_t_at_* is the paired wall's wall thickness
# (LUMBER_TYPES[paired_nominal][1]) — ignored when the corresponding
# role is None, so the caller can pass 0.0 there. joint_type_at_* is
# 'L_CORNER' | 'T_JOINT' | None; when None alongside a non-None role,
# behavior defaults to L_CORNER (the only v0.6.41 joint_type — keeps
# pre-migration callers behaving identically).


def plate_effective_ranges(
    plate_role: str,
    wall_length_in: float,
    *,
    role_at_start: str | None,
    role_at_end: str | None,
    paired_t_at_start: float,
    paired_t_at_end: float,
    joint_type_at_start: str | None = None,
    joint_type_at_end: str | None = None,
    mid_joints: list[dict] | None = None,
) -> list[tuple[float, float]]:
    """Return the list of disjoint (start_x, end_x) ranges for a plate.

    Single source of truth for plate geometry after joint modifications
    at both ends + interior T-joint cap notches. Returns one tuple per
    contiguous piece in wall-local coordinates; for plates without
    interior notches the list has exactly one element.

    See module-level comment above for the full per-end behavior
    table by (role, joint_type, plate_role).

    Interior notches (cap plate only, when this wall is wall_a in T
    joints): each mid_joint entry defines a notch from `position_in`
    to `position_in + paired_wt`. The cap range is partitioned into
    sub-ranges between consecutive notches. mid_joints must be sorted
    by position_in. Bottom and lower top plates ignore mid_joints —
    they're continuous through T joints by design.

    Args:
        plate_role: 'BOTTOM' | 'LOWER_TOP' | 'CAP'.
        wall_length_in: this wall's length in inches.
        role_at_start, role_at_end: 'MAIN' | 'ABUTTING' | None.
        paired_t_at_start, paired_t_at_end: paired wall's wall
            thickness at each end (LUMBER_TYPES[paired_nominal][1]).
            Ignored when the corresponding role is None.
        joint_type_at_start, joint_type_at_end: 'L_CORNER' |
            'T_JOINT' | None. Required when the corresponding role
            is non-None — controls the per-end behavior table above.
            Default None for v0.6.41 callers that haven't migrated;
            in that case the function treats it as 'L_CORNER' (the
            only v0.6.41 joint_type) for backward-compat.
        mid_joints: list of T-joint contexts where this wall is the
            through wall. Each entry must carry 'position_in' (float)
            and 'paired_wt' (float, the paired wall's wall thickness
            for the notch width). Empty / None means no notches.
            Only affects plate_role == 'CAP'.

    Returns:
        List of (start_x, end_x) tuples in wall-local inches, sorted
        ascending and disjoint. Always at least one element. Each
        tuple satisfies start_x < end_x.

    Raises:
        ValueError: if plate_role isn't valid; or if mid_joints isn't
            sorted by position_in; or if a notch falls outside the
            base range computed from end mods.
    """
    if plate_role not in ('BOTTOM', 'LOWER_TOP', 'CAP'):
        raise ValueError(
            f"plate_role must be 'BOTTOM', 'LOWER_TOP', or 'CAP'; "
            f"got {plate_role!r}"
        )

    # Backward-compat: None joint_type alongside a non-None role
    # means L_CORNER (the only v0.6.41 joint_type).
    jt_start = joint_type_at_start
    if role_at_start is not None and jt_start is None:
        jt_start = 'L_CORNER'
    jt_end = joint_type_at_end
    if role_at_end is not None and jt_end is None:
        jt_end = 'L_CORNER'

    # ---- Base range from end modifications ----
    start_x = 0.0
    end_x = wall_length_in

    # START end
    if jt_start == 'L_CORNER':
        if role_at_start == 'ABUTTING' and plate_role in ('BOTTOM', 'LOWER_TOP'):
            start_x = paired_t_at_start
        elif role_at_start == 'MAIN' and plate_role == 'CAP':
            start_x = paired_t_at_start
    elif jt_start == 'T_JOINT':
        # T_JOINT only ever has role 'ABUTTING' on the end-context dict.
        # Bottom and lower top: wall edge (no shortening). Cap: outboard
        # extension by paired_t.
        if role_at_start == 'ABUTTING' and plate_role == 'CAP':
            start_x = -paired_t_at_start

    # END end (mirror)
    if jt_end == 'L_CORNER':
        if role_at_end == 'ABUTTING' and plate_role in ('BOTTOM', 'LOWER_TOP'):
            end_x = wall_length_in - paired_t_at_end
        elif role_at_end == 'MAIN' and plate_role == 'CAP':
            end_x = wall_length_in - paired_t_at_end
    elif jt_end == 'T_JOINT':
        if role_at_end == 'ABUTTING' and plate_role == 'CAP':
            end_x = wall_length_in + paired_t_at_end

    # ---- Single-range fast paths ----
    if plate_role != 'CAP' or not mid_joints:
        return [(start_x, end_x)]

    # ---- Cap with mid_joints: partition by notches ----
    # Verify mid_joints is sorted by position_in. Cheap check; the
    # only authoritative caller (compute_wall_joint_context) sorts
    # explicitly, but defensive checks here keep the helper honest
    # if anyone else builds the list by hand.
    prev_pos = float('-inf')
    for mj in mid_joints:
        if mj['position_in'] < prev_pos:
            raise ValueError(
                "mid_joints must be sorted by position_in ascending"
            )
        prev_pos = mj['position_in']

    ranges: list[tuple[float, float]] = []
    cur_x = start_x
    for mj in mid_joints:
        n_start = mj['position_in']
        n_end = n_start + mj['paired_wt']
        if n_start < cur_x or n_end > end_x:
            raise ValueError(
                f"T-joint cap notch [{n_start:g}, {n_end:g}] falls "
                f"outside the cap range [{start_x:g}, {end_x:g}] "
                f"(possibly overlapping a previous notch or extending "
                f"past wall_length_in)"
            )
        if n_start > cur_x:
            ranges.append((cur_x, n_start))
        cur_x = n_end
    if cur_x < end_x:
        ranges.append((cur_x, end_x))

    # Defensive: skip any zero-width sub-range. Shouldn't happen
    # given the sorted+disjoint contract above, but cheap to guard.
    ranges = [(s, e) for (s, e) in ranges if e > s]
    if not ranges:
        # Pathological all-notch case: every byte of the cap range
        # was consumed by notches. Return a single empty-ish range
        # at start_x so downstream code doesn't break on an empty
        # list. (Real walls won't hit this — backing studs occupy
        # st_a between notches, so notches can't tile the whole cap.)
        ranges = [(start_x, start_x)]
    return ranges


def compute_wall_joint_context(
    wall_obj,
    joints,
    building_default_corner_style: str,
) -> dict:
    """For each end of `wall_obj`, find the joint touching it; also
    collect T joints where `wall_obj` is the through wall (wall_a).

    Returns a dict with three keys:

        'START': end-context dict | None
        'END':   end-context dict | None
        'mid_joints': list[dict]  — T joints where wall_obj is wall_a
                                    (the through wall), sorted by
                                    position_in ascending. Empty list
                                    when wall_obj is not the through
                                    wall in any T joint.

    Each per-end context dict carries:

        joint_type:        'L_CORNER' | 'T_JOINT'
        role:              'MAIN' | 'ABUTTING'  (for T_JOINT this is
                           always 'ABUTTING' — T joints have a fixed
                           through/abutting topology, not resolved
                           via extending_wall)
        paired_wall:       Object (the other wall in the joint)
        paired_wall_end:   'START' | 'END' (which end of the paired wall)
        corner_style:      resolved style (no more AUTO)

    Callers dispatch on joint_type to distinguish L_CORNER ABUTTING
    (cap stays at wall edge, lap inside) from T_JOINT ABUTTING (cap
    extends outboard, laps onto wall_a's lower top plate).

    Each mid_joints entry carries:

        joint_type:        'T_JOINT' (only one mid-joint type in v0.6.50)
        joint_index:       1-based index in the Level's joints
                           collection, used for naming
                           TBacker_Joint<NN>_L/_R objects in commit 3
                           (matches the L-corner CornerFiller_Joint<NN>
                           convention).
        position_in:       wall_a-local x at wall_b's near edge
                           (joint.wall_a_position_in).
        paired_wall:       Object (= joint.wall_b).
        paired_wall_end:   'START' | 'END' — which end of wall_b
                           connects to wall_a.
        corner_style:      resolved style (e.g. 'T_BACKING_STUDS').

    Caller is expected to have validated `joints` via validate_joints
    first; this function silently skips joints with unset wall_a / wall_b
    so it doesn't blow up on partial state during interactive editing.

    v0.6.40 removed the 'is_extending' field from end-context dicts —
    it was redundant with role under the v0.6.25 "MAIN == extending"
    semantics, and the only consumer (l_corner_geometry's
    cap_plate_offset branch) is gone now that plate ranges flow
    through plate_effective_ranges.

    v0.6.50 adds the 'mid_joints' key and T_JOINT support: T_JOINT
    abutting walls populate the per-end dict (role hardcoded to
    'ABUTTING'); T_JOINT through walls accumulate into mid_joints.
    """
    context: dict = {'START': None, 'END': None, 'mid_joints': []}
    for j_idx, joint in enumerate(joints, start=1):
        if joint.wall_a is None or joint.wall_b is None:
            continue

        # Identify wall_obj's slot in the joint (a or b) and its
        # paired wall — independent of role.
        if wall_obj == joint.wall_a:
            this_slot = 'A'
            this_end = joint.wall_a_end
            paired_wall = joint.wall_b
            paired_wall_end = joint.wall_b_end
        elif wall_obj == joint.wall_b:
            this_slot = 'B'
            this_end = joint.wall_b_end
            paired_wall = joint.wall_a
            paired_wall_end = joint.wall_a_end
        else:
            continue

        if joint.joint_type == 'T_JOINT':
            # T joints have a fixed topology: wall_a is the through
            # wall, wall_b is the abutting wall. No extending_wall
            # resolution; role is determined by slot.
            if this_slot == 'A':
                # wall_obj is the through wall — record as a mid_joint
                # entry. The per-end dict at this_end is NOT touched
                # because a T joint doesn't bind wall_a's end.
                context['mid_joints'].append({
                    'joint_type': 'T_JOINT',
                    'joint_index': j_idx,
                    'position_in': joint.wall_a_position_in,
                    'paired_wall': paired_wall,
                    'paired_wall_end': paired_wall_end,
                    'corner_style': resolve_corner_style(
                        joint, building_default_corner_style,
                    ),
                })
            else:
                # wall_obj is the abutting wall — record per-end.
                # role is unconditionally ABUTTING for T joints.
                context[this_end] = {
                    'joint_type': 'T_JOINT',
                    'role': 'ABUTTING',
                    'paired_wall': paired_wall,
                    'paired_wall_end': paired_wall_end,
                    'corner_style': resolve_corner_style(
                        joint, building_default_corner_style,
                    ),
                }
            continue

        # L_CORNER branch (v0.6.25): role follows resolve_extending_wall,
        # not slot. The MAIN wall is the one whose plates run continuous
        # through the corner (gets the filler stud); the ABUTTING wall
        # has its plates shortened. v0.6.0 hardcoded MAIN to wall_a;
        # that caused explicit extending_wall='A'/'B' to be ignored and
        # AUTO never to pick by length.
        extending = resolve_extending_wall(
            joint, joint.wall_a, joint.wall_b,
        )
        role = 'MAIN' if extending == this_slot else 'ABUTTING'

        context[this_end] = {
            'joint_type': 'L_CORNER',
            'role': role,
            'paired_wall': paired_wall,
            'paired_wall_end': paired_wall_end,
            'corner_style': resolve_corner_style(
                joint, building_default_corner_style,
            ),
        }

    # Stable order: sort mid_joints by position_in ascending. Downstream
    # naming and visual diff stability both rely on this.
    context['mid_joints'].sort(key=lambda mj: mj['position_in'])
    return context


def l_corner_three_stud_main_geometry(
    st_self: float,
    wt_other: float,
    end: str,
    wall_length_in: float,
) -> dict:
    """THREE_STUD MAIN-role geometry: one interior filler stud.

    The filler stud is the v0.6 default L-corner detail — a third
    full-height stud one wt_other inboard from the wall end, with
    its interior face flush with the paired wall's interior face.
    Combined with the wall's own end stud and the paired wall's
    end stud, this gives the canonical three-stud corner post.

    AUTO is resolved upstream by resolve_corner_style; this helper
    receives 'THREE_STUD' explicitly.

    Args:
        st_self: this wall's stud thickness
            (LUMBER_TYPES[nominal][0], 1.5 for 2x4). The filler
            stud's OWN x-extent.
        wt_other: the paired wall's wall thickness
            (LUMBER_TYPES[paired_nominal][1], 3.5 for 2x4).
        end: 'START' (joint at x=0) or 'END' (joint at wall_length_in).
        wall_length_in: this wall's length.

    Returns:
        {'filler_stud_x': float} — left-edge x-coord of the filler.
    """
    if end == 'END':
        filler_x = wall_length_in - wt_other - st_self
    else:  # 'START'
        filler_x = wt_other
    return {'filler_stud_x': filler_x}


def l_corner_california_main_geometry(
    st_self: float,
    wt_self: float | None,
    wt_other: float,
    end: str,
    wall_length_in: float,
) -> dict:
    """CALIFORNIA MAIN-role geometry: one 2x backer laid flat.

    Drop-in replacement for THREE_STUD's filler stud. The backer is
    2x stock (1.5" narrow face) rotated 90° so its broad face runs
    along the wall length — wider in X (wt_self), shallower in Y
    (1.5"). Interior face flush with MAIN's interior face; near-Y
    face sits at wt_self - 1.5 (deep into the cavity).

    Energy-efficient alternative to THREE_STUD: less wood at the
    corner, more insulation cavity, same drywall-nailing surface.

    AUTO is resolved upstream by resolve_corner_style; this helper
    receives 'CALIFORNIA' explicitly. The dispatcher's wt_self
    kwarg flows here as a required argument.

    Args:
        st_self: this wall's stud thickness (1.5 for 2x4). Accepted
            for signature symmetry with the THREE_STUD helper;
            unused in California's geometry math.
        wt_self: this wall's wall thickness
            (LUMBER_TYPES[nominal][1], 3.5 for 2x4). Backer x-extent
            + y-offset reference. REQUIRED — None raises ValueError.
        wt_other: the paired wall's wall thickness. Same anchor as
            THREE_STUD's filler.
        end: 'START' or 'END'.
        wall_length_in: this wall's length.

    Returns:
        {'backer': {left_edge_x, y_offset, x_extent, y_extent}}.

    Raises:
        ValueError: if wt_self is None.
    """
    del st_self  # accepted for signature symmetry; unused
    if wt_self is None:
        raise ValueError(
            "CALIFORNIA corner style requires wt_self (the MAIN "
            "wall's wall thickness) — the dispatcher passes it via "
            "the wt_self kwarg on l_corner_geometry."
        )
    if end == 'END':
        left_edge_x = wall_length_in - wt_other - wt_self
    else:  # 'START'
        left_edge_x = wt_other
    return {
        'backer': {
            'left_edge_x': left_edge_x,
            'y_offset':    wt_self - 1.5,
            'x_extent':    wt_self,
            'y_extent':    1.5,
        },
    }


def l_corner_ladder_blocking_main_geometry(
    st_self: float,
    wt_self: float | None,
    wt_other: float,
    end: str,
    wall_length_in: float,
    stud_cavity_bottom_z: float | None,
    stud_cavity_top_z: float | None,
) -> dict:
    """LADDER_BLOCKING MAIN-role geometry: three horizontal blocks.

    No vertical filler stud. Instead, three horizontal 2x blocks
    stacked at staggered Z heights provide drywall nailing while
    maximizing insulation cavity. Same X anchor as THREE_STUD's
    filler. Block long axis along wall depth (Y); broad face
    vertical so drywall can nail to the upper face.

    Z layout (assuming cavity >= 24 + 2 * wt_self):
        z_center_bottom = stud_cavity_bottom_z + 12
        z_center_top    = stud_cavity_top_z    - 12
        z_center_mid    = (z_center_bottom + z_center_top) / 2

    For 96" 2x4 walls with 1 bot + 2 top plates:
        cavity_bottom = 1.5, cavity_top = 93
        z_centers = [13.5, 47.25, 81.0]

    AUTO is resolved upstream by resolve_corner_style; this helper
    receives 'LADDER_BLOCKING' explicitly. The dispatcher's
    wt_self / stud_cavity_bottom_z / stud_cavity_top_z kwargs flow
    here as required arguments.

    Args:
        st_self: this wall's stud thickness (1.5 for 2x4). Block
            x-extent (narrow stud face along wall length).
        wt_self: this wall's wall thickness (3.5 for 2x4). Block
            y-extent (spans full wall depth) and z-extent (broad
            face vertical). REQUIRED — None raises ValueError.
        wt_other: the paired wall's wall thickness. Same anchor as
            THREE_STUD's filler.
        end: 'START' or 'END'.
        wall_length_in: this wall's length.
        stud_cavity_bottom_z: top of bottom plate stack in wall-
            local Z. Lowest block center sits 12" above this.
            REQUIRED — None raises ValueError.
        stud_cavity_top_z: bottom of lower top plate in wall-local
            Z. Highest block center sits 12" below this. REQUIRED.

    Returns:
        {'ladder_blocks': {left_edge_x, z_centers (bottom-to-top),
                           x_extent, y_extent, z_extent}}.

    Raises:
        ValueError: if any required kwarg is None, or if the
            computed block z_centers overlap or escape the cavity
            (defense-in-depth; validate_joints catches the size
            mismatch upstream).
    """
    if (wt_self is None
            or stud_cavity_bottom_z is None
            or stud_cavity_top_z is None):
        raise ValueError(
            "LADDER_BLOCKING corner style requires wt_self, "
            "stud_cavity_bottom_z, and stud_cavity_top_z — the "
            "dispatcher passes them via the corresponding kwargs "
            "on l_corner_geometry."
        )
    if end == 'END':
        left_edge_x = wall_length_in - wt_other - st_self
    else:  # 'START'
        left_edge_x = wt_other
    z_center_bottom = stud_cavity_bottom_z + 12.0
    z_center_top    = stud_cavity_top_z    - 12.0
    z_center_mid    = (z_center_bottom + z_center_top) / 2.0

    # Defense-in-depth: validate_joints catches the size mismatch
    # upstream, but a caller who builds a joint without going
    # through validate_joints would get a confusing geometry
    # outcome instead of a clear error.
    if z_center_top - z_center_bottom < 2.0 * wt_self:
        raise ValueError(
            f"LADDER_BLOCKING cavity too short for three blocks: "
            f"z_center_top - z_center_bottom = "
            f"{z_center_top - z_center_bottom:g}\" < 2 * wt_self = "
            f"{2.0 * wt_self:g}\". Need stud cavity height "
            f">={24.0 + 2.0 * wt_self:g}\" for "
            f"{wt_self:g}\"-tall blocks."
        )
    half_h = wt_self / 2.0
    if (z_center_bottom - half_h < stud_cavity_bottom_z
            or z_center_top + half_h > stud_cavity_top_z):
        raise ValueError(
            f"LADDER_BLOCKING block extends past cavity bounds — "
            f"cavity [{stud_cavity_bottom_z:g}, "
            f"{stud_cavity_top_z:g}], blocks span "
            f"[{z_center_bottom - half_h:g}, "
            f"{z_center_top + half_h:g}]"
        )

    return {
        'ladder_blocks': {
            'left_edge_x': left_edge_x,
            'z_centers':   [z_center_bottom, z_center_mid, z_center_top],
            'x_extent':    st_self,
            'y_extent':    wt_self,
            'z_extent':    wt_self,
        },
    }


def l_corner_geometry(
    st_self: float,
    wt_other: float,
    role: str,
    end: str,
    wall_length_in: float,
    *,
    corner_style: str = 'THREE_STUD',
    wt_self: float | None = None,
    stud_cavity_bottom_z: float | None = None,
    stud_cavity_top_z: float | None = None,
) -> dict:
    """Per-end stud-related geometry for ONE wall at ONE end of an L joint.

    Dispatcher. ABUTTING-role handling (end stud moves inboard by
    wt_other to land flush with shortened plates) is identical
    across all three L-corner styles and lives in the dispatcher
    body. MAIN-role handling dispatches to a per-style helper:

        THREE_STUD       → l_corner_three_stud_main_geometry
        CALIFORNIA       → l_corner_california_main_geometry
        LADDER_BLOCKING  → l_corner_ladder_blocking_main_geometry

    The corner_style kwarg defaults to 'THREE_STUD', so callers
    that haven't migrated to the v0.6.60 API keep working without
    change — that's the backward-compatibility hook that lets
    Commit 2 ship templates-side without breaking the operator.
    The new kwargs are keyword-only (`*` boundary) so existing
    positional callers keep working unchanged.

    AUTO is resolved upstream by resolve_corner_style; this
    function only accepts the three concrete L-corner styles per
    L_CORNER_STYLES. T-joint styles (T_BACKING_STUDS) are not
    valid here — the caller dispatched wrong.

    Two calls cover a wall with joints at both ends; the operator
    combines the START and END results when laying out studs. For
    a wall with no joint at a given end, the caller skips this
    function and uses v0.5 defaults.

    Args:
        st_self: this wall's stud thickness (LUMBER_TYPES[nominal][0],
            1.5 for 2x4). The stud's OWN x-extent.
        wt_other: the paired wall's wall thickness
            (LUMBER_TYPES[paired_nominal][1], 3.5 for 2x4).
        role: 'MAIN' or 'ABUTTING'.
        end: 'START' or 'END'.
        wall_length_in: this wall's length.
        corner_style: 'THREE_STUD' (default), 'CALIFORNIA', or
            'LADDER_BLOCKING'. Anything else raises ValueError.
        wt_self: this wall's wall thickness
            (LUMBER_TYPES[nominal][1]). REQUIRED for CALIFORNIA
            and LADDER_BLOCKING; ignored for THREE_STUD.
        stud_cavity_bottom_z: top of the wall's bottom plate stack
            in wall-local Z (= bottom_plate_count * st_self).
            REQUIRED for LADDER_BLOCKING.
        stud_cavity_top_z: bottom of the wall's lower top plate in
            wall-local Z (= wall_height_in - top_plate_count * st_self).
            REQUIRED for LADDER_BLOCKING.

    Returns:
        Uniform-shape dict — superset of all styles' MAIN-role
        outputs plus the ABUTTING-role end-stud override:
            end_stud_x_override (float | None): set only for ABUTTING.
            filler_stud_x       (float | None): set only for THREE_STUD MAIN.
            backer              (dict  | None): set only for CALIFORNIA MAIN.
            ladder_blocks       (dict  | None): set only for LADDER_BLOCKING MAIN.

    Raises:
        ValueError: if corner_style isn't in L_CORNER_STYLES, or
            if a per-style helper's required kwarg is None.
    """
    if corner_style not in L_CORNER_STYLES:
        raise ValueError(
            f"l_corner_geometry: corner_style must be one of "
            f"{sorted(L_CORNER_STYLES)}, got {corner_style!r}"
        )

    out: dict = {
        'end_stud_x_override': None,
        'filler_stud_x':       None,
        'backer':              None,
        'ladder_blocks':       None,
    }

    if role == 'ABUTTING':
        # End stud repositioned to land flush with the shortened
        # plates. On END side the stud's own width (st_self) shifts
        # the LEFT edge inboard from the right edge that aligns
        # with plate end. Identical across all L-corner styles.
        if end == 'END':
            out['end_stud_x_override'] = wall_length_in - wt_other - st_self
        else:  # 'START'
            out['end_stud_x_override'] = wt_other
        return out

    # MAIN: dispatch on corner_style.
    if corner_style == 'THREE_STUD':
        out.update(l_corner_three_stud_main_geometry(
            st_self=st_self,
            wt_other=wt_other,
            end=end,
            wall_length_in=wall_length_in,
        ))
    elif corner_style == 'CALIFORNIA':
        out.update(l_corner_california_main_geometry(
            st_self=st_self,
            wt_self=wt_self,
            wt_other=wt_other,
            end=end,
            wall_length_in=wall_length_in,
        ))
    elif corner_style == 'LADDER_BLOCKING':
        out.update(l_corner_ladder_blocking_main_geometry(
            st_self=st_self,
            wt_self=wt_self,
            wt_other=wt_other,
            end=end,
            wall_length_in=wall_length_in,
            stud_cavity_bottom_z=stud_cavity_bottom_z,
            stud_cavity_top_z=stud_cavity_top_z,
        ))
    return out


def t_joint_geometry_for_wall_a(
    position_in: float,
    st_a: float,
    wt_b: float,
) -> dict:
    """Per-T-joint geometry pieces for ONE T joint, viewed from the
    through wall (wall_a).

    Single source of truth for the wall_a-side geometry of a T joint:
    where the two backing studs land along wall_a's length, and where
    the cap-plate notch lives. The operator uses both — backing stud
    placement uses backing_stud_xs as left-edge x-coords; the cap-
    plate effective ranges consume cap_notch_range to partition the
    cap into sub-ranges.

    Backing studs: two studs flank wall_b's end-stud footprint on
    wall_a's interior face. Their right and left faces respectively
    are flush with wall_b's left and right edges, providing drywall
    nailing for wall_b's interior face return on both sides.

      LEFT  backing stud: left edge at (position - st_a),
                          right edge at position  (flush w/ wall_b L)
      RIGHT backing stud: left edge at (position + wt_b),
                          right edge at (position + wt_b + st_a)
                          (left flush w/ wall_b R)

    Cap notch: wall_a's cap plate is interrupted at (position,
    position + wt_b) — the wt_b-wide gap where wall_b's extended
    cap plate lands on top of wall_a's lower top plate. Per IRC
    R602.3.2.

    Args:
        position_in: wall_a-local x at wall_b's near (left) face.
        st_a: wall_a's stud thickness (LUMBER_TYPES[wall_a_nominal][0],
            1.5" for 2x4) — backing stud x-extent.
        wt_b: wall_b's wall thickness (LUMBER_TYPES[wall_b_nominal][1],
            3.5" for 2x4) — width of wall_b's footprint on wall_a +
            cap notch width.

    Returns:
        Dict with:
            backing_stud_xs:  tuple[float, float] — left-edge x of the
                left and right backing studs respectively.
            cap_notch_range: tuple[float, float] — (start_x, end_x)
                of the cap notch.
    """
    return {
        'backing_stud_xs': (position_in - st_a, position_in + wt_b),
        'cap_notch_range': (position_in, position_in + wt_b),
    }


def validate_joints(joints, walls_in_level) -> tuple[bool, str]:
    """Cross-check the joints list against the Level's walls.

    Returns (True, "") on success or (False, "Joint N: ...") on the
    first failure. Checks in order:

      1. Each joint has wall_a AND wall_b set (no None pointers).
      2. Both walls are members of walls_in_level (i.e. children of
         the Level being framed).
      3. wall_a != wall_b (no self-joint).
      4. No two joints reference the same (wall, end) — a wall can have
         at most one joint per end. T_JOINT joints don't bind wall_a's
         end (the joint is at a position along the wall, not at an
         end), so only wall_b's end is checked for T joints.
      5. corner_style and joint_type are compatible (v0.6.60 uses
         L_CORNER_STYLES / T_JOINT_STYLES set membership): L-corner
         styles (THREE_STUD, CALIFORNIA, LADDER_BLOCKING) only valid
         with L_CORNER; T-joint styles (T_BACKING_STUDS) only valid
         with T_JOINT. AUTO is always valid (resolved at frame time
         via resolve_corner_style).
      6. T_JOINT wall_a_position_in is within [st_a, wall_a_length -
         wt_b - st_a] so backing studs and wall_b's footprint fit
         within wall_a's length axis. Other geometry conflicts
         (overlapping openings, other joints, end-stud cells of
         L-corner joints at wall_a's ends) are intentionally NOT
         checked here in v0.6.50 — they surface later as splice /
         placement errors or visually in the viewport.
      7. LADDER_BLOCKING (explicit, v0.6.60): the MAIN wall's stud
         cavity must be tall enough for three blocks at 12"/12"/
         midpoint with each block's z-extent = MAIN's wt_self.
         Required: stud_cavity_height >= 24 + 2 * wt_self_MAIN.
         For 2x4 MAIN: cavity >= 31". For 2x6 MAIN: cavity >= 35".
         AUTO joints whose Building default resolves to
         LADDER_BLOCKING are NOT pre-checked here — they surface
         at frame time via l_corner_ladder_blocking_main_geometry's
         defense-in-depth ValueError.
    """
    wall_set = set(walls_in_level)

    for i, joint in enumerate(joints, start=1):
        if joint.wall_a is None or joint.wall_b is None:
            return (False, f"Joint {i}: wall_a and wall_b must both be set")
        if joint.wall_a not in wall_set or joint.wall_b not in wall_set:
            return (False, f"Joint {i}: both walls must be in this Level")
        if joint.wall_a == joint.wall_b:
            return (False, f"Joint {i}: wall_a and wall_b must be different walls")

        # Compatibility check (5). v0.6.60: set-based, single source
        # of truth via L_CORNER_STYLES / T_JOINT_STYLES. AUTO is
        # unconditionally valid (resolved at frame time).
        if joint.corner_style != 'AUTO':
            if (joint.joint_type == 'L_CORNER'
                    and joint.corner_style in T_JOINT_STYLES):
                return (
                    False,
                    f"Joint {i}: corner_style "
                    f"{joint.corner_style!r} is T-joint-only and "
                    f"can't be used with L_CORNER",
                )
            if (joint.joint_type == 'T_JOINT'
                    and joint.corner_style in L_CORNER_STYLES):
                return (
                    False,
                    f"Joint {i}: corner_style "
                    f"{joint.corner_style!r} is L-corner-only and "
                    f"can't be used with T_JOINT",
                )

        # T_JOINT position bounds (6).
        if joint.joint_type == 'T_JOINT':
            st_a = LUMBER_TYPES[joint.wall_a.praxova_wall.wall_nominal][0]
            wt_b = LUMBER_TYPES[joint.wall_b.praxova_wall.wall_nominal][1]
            wall_a_length = joint.wall_a.praxova_wall.wall_length_in
            pos = joint.wall_a_position_in
            min_pos = st_a
            max_pos = wall_a_length - wt_b - st_a
            if pos < min_pos or pos > max_pos:
                return (
                    False,
                    f"Joint {i}: wall_a_position_in={pos:g}\" must be in "
                    f"[{min_pos:g}, {max_pos:g}] so backing studs and "
                    f"wall_b's footprint fit within wall_a "
                    f"({joint.wall_a.name!r}, length {wall_a_length:g}\")",
                )

        # LADDER_BLOCKING wall-height pre-flight (7). Only fires for
        # explicit LADDER_BLOCKING + L_CORNER. AUTO joints that
        # would resolve to LADDER_BLOCKING via the Building default
        # are caught at frame time by the helper's defense-in-depth
        # ValueError. Identifying the MAIN wall requires
        # resolve_extending_wall (defined above in this module).
        if (joint.joint_type == 'L_CORNER'
                and joint.corner_style == 'LADDER_BLOCKING'):
            main = (
                joint.wall_a
                if resolve_extending_wall(
                    joint, joint.wall_a, joint.wall_b,
                ) == 'A'
                else joint.wall_b
            )
            mp = main.praxova_wall
            main_st = LUMBER_TYPES[mp.wall_nominal][0]
            main_wt = LUMBER_TYPES[mp.wall_nominal][1]
            stud_cavity_height = (
                float(mp.wall_height_in)
                - (int(mp.wall_top_plate_count)
                   + int(mp.wall_bottom_plate_count))
                * main_st
            )
            min_cavity_height = 24.0 + 2.0 * main_wt
            if stud_cavity_height < min_cavity_height:
                return (
                    False,
                    f"Joint {i}: LADDER_BLOCKING requires the MAIN "
                    f"wall ({main.name!r}) to have stud cavity "
                    f"height >={min_cavity_height:g}\" (24\" between "
                    f"top and bottom block centers + {main_wt:g}\" "
                    f"of block stack on each end). Current cavity "
                    f"is {stud_cavity_height:g}\".",
                )

    used: dict[tuple[str, str], int] = {}
    for i, joint in enumerate(joints, start=1):
        # T joints don't bind wall_a's end (the joint is at a position
        # along the wall, not at an end). wall_b's end IS at the joint
        # regardless of joint_type, so it's always checked.
        ends_to_check = [(joint.wall_b, joint.wall_b_end)]
        if joint.joint_type == 'L_CORNER':
            ends_to_check.append((joint.wall_a, joint.wall_a_end))
        for wall, end in ends_to_check:
            key = (wall.name, end)
            if key in used:
                return (
                    False,
                    f"Joint {i}: {wall.name}'s {end} end is already "
                    f"used by Joint {used[key]}",
                )
            used[key] = i

    return (True, "")


# ===========================================================================
# In-line plate splice helpers (v0.6.40)
# ===========================================================================
#
# When a wall's plate length exceeds the longest available stock, the
# plate is split into multiple pieces that butt-join over a full-height
# stud (end stud, OC stud, king, or interior corner filler — NOT a jack
# or cripple, which don't provide a continuous load path to the cap).
#
# Per IRC R602.3.2, a cap plate splice must be offset at least 24" from
# any lower top plate splice. Enforced as a HARD constraint: if no valid
# stud satisfies the offset, plan_plate_splice_pieces raises SpliceError
# rather than falling back to a non-compliant splice. The user adjusts
# wall length or stud layout so a valid splice exists.
#
# Stud-snapping: when the ideal splice position (cur + max_stock) lacks
# a stud, the planner shifts INBOARD to the largest stud at or before
# the ideal — i.e., the first piece is allowed to be shorter than max
# stock so the splice lands on real framing. This matches what a
# carpenter does in the field: accept a slightly short first piece
# rather than retrofit an extra stud just to splice over.
#
# v0.6.40 caps max stock at 16' (192") across all nominals. Per-nominal
# max stock tables and user-settable stock are deferred — the
# max_stock_length_in() function indirection is in place to make those
# additions a one-function patch.
#
# SpliceError is defined at module top (above the Lumber section) so
# importers that catch it don't need to reach into this section.


# Common max stock for residential lumber. 2x4 / 2x6 / 2x8 / 2x10 / 2x12
# all top out here in typical big-box and yard inventories. 4x and 6x
# stock is sometimes available in 20', but rarely for someone building
# to residential code without a stamped supplier — capping at 16' is the
# conservative default.
MAX_STOCK_LENGTH_IN: float = 192.0

# IRC R602.3.2: minimum offset between a cap plate splice and the
# nearest lower top plate splice. Enforced as a hard constraint by
# plan_plate_splice_pieces.
TOP_PLATE_SPLICE_OFFSET_MIN_IN: float = 24.0


def max_stock_length_in(nominal: str) -> float:
    """Return the maximum stock length in inches for the given nominal.

    Function indirection (rather than a bare constant lookup at call
    sites) so future per-nominal tables or user-settable stock can be
    added without changing every caller.

    v0.6.40 returns min(MAX_STOCK_LENGTH_IN, max(LENGTHS_BY_TYPE[nominal])).
    The min() floors at the per-nominal stock ceiling so nominals with
    shorter max stock than 16' (e.g. 1x2 caps at 8') don't get a
    splice plan that produces pieces beyond their available stock.
    For nominals whose available stock exceeds 16' (4x and 6x stock
    sometimes goes to 20'), MAX_STOCK_LENGTH_IN wins — capping at the
    conservative residential default per the v0.6.40 design.

    Args:
        nominal: lumber size key (e.g. '2x4'). Must be in LUMBER_TYPES.

    Returns:
        Maximum stock length in inches that the splice planner will
        assume is available for this nominal.

    Raises:
        ValueError: if `nominal` isn't in LUMBER_TYPES — surfaces typos
            and stale tags rather than silently returning a default,
            matching select_stock_length_in's posture above.
    """
    if nominal not in LUMBER_TYPES:
        raise ValueError(f"Unknown nominal {nominal!r}")
    per_nominal_max_in = max(LENGTHS_BY_TYPE[nominal]) * 12.0
    return min(MAX_STOCK_LENGTH_IN, per_nominal_max_in)


def plan_plate_splice_pieces(
    plate_start_x: float,
    plate_end_x: float,
    stud_centers_eligible: list[float],
    max_stock_in: float,
    excluded_splice_xs: tuple[float, ...] = (),
    offset_min_in: float = TOP_PLATE_SPLICE_OFFSET_MIN_IN,
) -> list[tuple[float, float]]:
    """Plan how to cut a plate into pieces that each fit within max stock.

    Returns a list of (start_x, end_x) tuples in plate-local coordinates,
    one per cut piece. For plates that fit in max stock the result is a
    single-element list [(plate_start_x, plate_end_x)].

    Splice algorithm: walk left to right, greedily placing each splice
    at the LARGEST eligible stud center at or before
    (current_start + max_stock). This minimizes the number of splices
    and matches field practice — get the most lumber out of each stock
    piece. When excluded_splice_xs is non-empty (the cap-plate case),
    stud centers within offset_min_in of any excluded position are
    filtered out before picking the largest — this enforces the IRC
    R602.3.2 24" offset rule against the lower top plate's splices.

    Args:
        plate_start_x: left edge of the plate in wall-local coords.
        plate_end_x: right edge of the plate in wall-local coords.
            Must be > plate_start_x.
        stud_centers_eligible: sorted unique list of x-coords of
            full-height stud centers, in wall-local coords. Use
            collect_full_height_stud_centers to build this from an
            operator's stud / king / filler positions.
        max_stock_in: maximum piece length in inches.
            Use max_stock_length_in(nominal).
        excluded_splice_xs: x-coords of splices in another plate that
            this plate must not splice within offset_min_in of. Used
            for the cap plate (pass lower top splices here); leave
            empty for the lower top and bottom plates.
        offset_min_in: minimum distance from any excluded splice.
            Default TOP_PLATE_SPLICE_OFFSET_MIN_IN (24").

    Returns:
        List of (start_x, end_x) tuples, in order. Each piece's length
        (end_x - start_x) is in (0, max_stock_in].

    Raises:
        SpliceError: if any required splice can't be placed — either no
            stud center falls in the valid range, or all stud centers
            in the range are excluded by the offset rule. The message
            identifies the failing range and whether the offset rule
            was binding.
    """
    L_eff = plate_end_x - plate_start_x
    if L_eff <= max_stock_in:
        return [(plate_start_x, plate_end_x)]

    pieces: list[tuple[float, float]] = []
    cur = plate_start_x

    while plate_end_x - cur > max_stock_in:
        ideal_max = cur + max_stock_in
        # Studs strictly past cur (no zero-length piece) and at or
        # before the ideal max (so the piece fits in max stock).
        in_range = [
            sc for sc in stud_centers_eligible
            if cur < sc <= ideal_max
        ]
        if excluded_splice_xs:
            candidates = [
                sc for sc in in_range
                if all(
                    abs(sc - ex) >= offset_min_in
                    for ex in excluded_splice_xs
                )
            ]
        else:
            candidates = in_range

        if not candidates:
            if excluded_splice_xs and in_range:
                excluded_str = ", ".join(
                    f"{x:.2f}\"" for x in excluded_splice_xs
                )
                offset_note = (
                    f" while keeping >={offset_min_in:g}\" from lower "
                    f"top plate splice(s) at {excluded_str}"
                )
            else:
                offset_note = ""
            raise SpliceError(
                f"No eligible stud between x={cur:.2f}\" and "
                f"x={ideal_max:.2f}\" to support a plate splice"
                f"{offset_note}. Adjust wall length, stud layout, or "
                f"opening positions so a full-height stud lands in "
                f"this range."
            )

        splice_x = max(candidates)
        pieces.append((cur, splice_x))
        cur = splice_x

    pieces.append((cur, plate_end_x))
    return pieces


def collect_full_height_stud_centers(
    oc_stud_left_xs: list[float],
    opening_layouts: list[dict],
    stud_thickness_in: float,
    *,
    backing_stud_left_xs: list[float] | tuple[float, ...] = (),
) -> list[float]:
    """Build the sorted unique list of full-height stud centers.

    "Full-height" = end-to-end vertical load path from bottom plate to
    cap plate, eligible to anchor an in-line plate splice. Includes:

      - End studs and surviving OC studs (already in oc_stud_left_xs
        after end_stud_override + filter_studs_around_openings)
      - King studs from each opening (full-height by construction)
      - T-joint backing studs on the through wall (wall_a) — two per
        T joint, flanking wall_b's footprint; both run full height

    Excludes jacks (don't reach the top plates) and cripples (don't
    reach both plate stacks).

    v0.6.60: corner-filler / California backer studs on MAIN-role
    L-corner joints are NO LONGER eligible splice anchors. The
    filler/backer sits 1.5"-3.5" inboard from the end stud in the
    same corner cell — redundant with the end stud for splice
    purposes (they're so close together that any splice landing on
    the filler could land on the end stud with the same offset
    behavior). Removing it makes corner_style a pure backing
    concern: THREE_STUD, CALIFORNIA, and LADDER_BLOCKING all see
    the same splice anchor set, so swapping styles can't change
    splice positions. T-joint backing studs remain eligible — they
    sit at interior wall positions and aren't redundant with
    anything.

    Args:
        oc_stud_left_xs: left-edge x-coords of every regular OC stud
            (and end studs, with any joint end-stud overrides applied).
            Same list the operator places as `{wall_name}_Stud_NN`.
        opening_layouts: list of dicts from opening_framing_layout,
            one per opening on this wall.
        stud_thickness_in: stud cross-section thickness along wall
            length (LUMBER_TYPES[nominal][0]).
        backing_stud_left_xs: left-edge x-coords of T-joint backing
            studs on this wall (only populated when this wall is
            wall_a in one or more T joints). Empty by default.

    Returns:
        Sorted unique list of stud center x-coords. The caller passes
        this to plan_plate_splice_pieces as stud_centers_eligible.
    """
    half_t = stud_thickness_in / 2.0
    centers: set[float] = set()

    for x in oc_stud_left_xs:
        centers.add(x + half_t)

    for layout in opening_layouts:
        # Left king's left edge is king_left_x; center is +half_t.
        centers.add(layout['king_left_x'] + half_t)
        # Right king's RIGHT edge is king_right_x; its left edge sits
        # at king_right_x - stud_thickness, center at -half_t from
        # king_right_x.
        centers.add(layout['king_right_x'] - half_t)

    for x in backing_stud_left_xs:
        centers.add(x + half_t)

    return sorted(centers)


# Backward-compatibility aliases for v0.1 callers.
make_lumber_mesh = make_box_mesh
cutlist_label = lumber_cutlist_label

"""Lumber, sheet-good, and panel dimension data and mesh construction."""

import re

import bpy


# Conversion factor: meters per inch. Blender stores all lengths in meters
# internally regardless of the scene's display units.
INCH = 0.0254


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
# Terminology (per design doc):
#   MAIN wall (wall_a)     keeps plate continuity at the joint end
#   ABUTTING wall (wall_b) has its plates shortened by MAIN's stud
#                          thickness at the joint end
#   "extending wall"       the one whose cap plate runs full length and
#                          overlaps the other's lower top plate at the
#                          corner (IRC R602.3.2 calls for lapping)


def resolve_extending_wall(joint, wall_a_length: float, wall_b_length: float) -> str:
    """Pick which wall's cap plate extends across the corner.

    Returns 'A' or 'B'. For AUTO, the shorter wall extends — longer walls
    are harder to splice so we protect their continuity. Ties go to A
    (the main wall) on the principle that the user has already declared
    which is which.
    """
    explicit = joint.extending_wall
    if explicit == 'A':
        return 'A'
    if explicit == 'B':
        return 'B'
    # AUTO: shorter wall extends.
    if wall_a_length < wall_b_length:
        return 'A'
    if wall_a_length > wall_b_length:
        return 'B'
    return 'A'  # tie-break to main


def resolve_corner_style(joint, building_default: str) -> str:
    """Resolve a joint's corner_style, substituting the Building's default
    when the joint says AUTO. For v0.6 this always returns 'THREE_STUD'
    (only style available), but the indirection through Building default
    is what v0.7 will hang California / ladder-blocking styles on.
    """
    if joint.corner_style == 'AUTO':
        return building_default
    return joint.corner_style


def compute_wall_joint_context(
    wall_obj,
    joints,
    building_default_corner_style: str,
) -> dict:
    """For each end of `wall_obj`, find the joint touching it (if any).

    Returns a dict with 'START' and 'END' keys. Each value is either None
    (no joint at that end) or a dict with:

        joint_type:        'L_CORNER' (only v0.6 type)
        role:              'MAIN' | 'ABUTTING'
        paired_wall:       Object (the other wall in the joint)
        paired_wall_end:   'START' | 'END' (which end of the paired wall)
        corner_style:      resolved style (no more AUTO)
        is_extending:      bool — True if THIS wall's cap plate extends
                           across the corner at THIS end

    Caller is expected to have validated `joints` via validate_joints
    first; this function silently skips joints with unset wall_a / wall_b
    so it doesn't blow up on partial state during interactive editing.
    A wall with two joints at the same end (which validate_joints
    catches) would overwrite — but should be a validation failure
    long before this function is called from frame_wall.
    """
    context = {'START': None, 'END': None}
    for joint in joints:
        if joint.wall_a is None or joint.wall_b is None:
            continue
        if wall_obj == joint.wall_a:
            role = 'MAIN'
            this_end = joint.wall_a_end
            paired_wall = joint.wall_b
            paired_wall_end = joint.wall_b_end
        elif wall_obj == joint.wall_b:
            role = 'ABUTTING'
            this_end = joint.wall_b_end
            paired_wall = joint.wall_a
            paired_wall_end = joint.wall_a_end
        else:
            continue

        wall_a_length = joint.wall_a.praxova_wall.wall_length_in
        wall_b_length = joint.wall_b.praxova_wall.wall_length_in
        extending = resolve_extending_wall(
            joint, wall_a_length, wall_b_length,
        )
        is_extending = (
            (role == 'MAIN' and extending == 'A')
            or (role == 'ABUTTING' and extending == 'B')
        )

        context[this_end] = {
            'joint_type': joint.joint_type,
            'role': role,
            'paired_wall': paired_wall,
            'paired_wall_end': paired_wall_end,
            'corner_style': resolve_corner_style(
                joint, building_default_corner_style,
            ),
            'is_extending': is_extending,
        }
    return context


def l_corner_geometry(
    t_self: float,
    t_other: float,
    role: str,
    end: str,
    is_extending: bool,
    wall_length_in: float,
) -> dict:
    """Per-piece offsets for ONE wall at ONE end of an L joint.

    Two calls cover a wall with joints at both ends; the operator
    combines the START and END offsets when laying out plates and
    studs. For a wall with no joint at a given end, the caller skips
    this function and uses v0.5 defaults.

    Args:
        t_self: this wall's stud thickness (LUMBER_TYPES[nominal][0]).
        t_other: the paired wall's stud thickness.
        role: 'MAIN' or 'ABUTTING'.
        end: 'START' (joint at x=0) or 'END' (joint at x=wall_length_in).
        is_extending: True if this wall's cap plate runs full-length
            across the corner; False if the cap plate is shortened by
            t_other at this end.
        wall_length_in: this wall's length in inches.

    Returns:
        bottom_plate_offset (in): cut off this much from the joint
            end of the bottom plate. 0 for MAIN, t_other for ABUTTING.
        lower_top_plate_offset (in): same shape as bottom plate.
        cap_plate_offset (in): 0 if this wall extends, else t_other.
        end_stud_x_override (float | None): left-edge x-coord to use for
            this wall's end stud at the joint end. None means use v0.5
            default (flush with the wall end). ABUTTING walls move
            their end stud inward by t_other; MAIN walls don't change.
        filler_stud_x (float | None): left-edge x-coord of the interior
            corner filler stud. Only MAIN walls produce one (per design
            doc — abutting walls don't). For 'END' the filler sits at
            (length - t_self - t_other); for 'START' at t_other.
    """
    out = {
        'bottom_plate_offset': 0.0,
        'lower_top_plate_offset': 0.0,
        'cap_plate_offset': 0.0,
        'end_stud_x_override': None,
        'filler_stud_x': None,
    }

    cap_offset = 0.0 if is_extending else t_other

    if role == 'MAIN':
        # Plates run full length at the joint end (bottom + lower top).
        # Cap plate shortened only if MAIN does NOT extend.
        out['cap_plate_offset'] = cap_offset
        # Filler stud one t_other inboard from the end stud (interior
        # face aligned with where the abutting wall's interior face
        # will land in world space).
        if end == 'END':
            out['filler_stud_x'] = wall_length_in - t_self - t_other
        else:  # 'START'
            out['filler_stud_x'] = t_other
    else:  # 'ABUTTING'
        # Plates shortened by t_other at the joint end (bottom + lower
        # top). Cap follows is_extending.
        out['bottom_plate_offset'] = t_other
        out['lower_top_plate_offset'] = t_other
        out['cap_plate_offset'] = cap_offset
        # End stud repositioned to land flush with the shortened plates.
        if end == 'END':
            out['end_stud_x_override'] = wall_length_in - t_other - t_self
        else:  # 'START'
            out['end_stud_x_override'] = t_other

    return out


def validate_joints(joints, walls_in_level) -> tuple[bool, str]:
    """Cross-check the joints list against the Level's walls.

    Returns (True, "") on success or (False, "Joint N: ...") on the
    first failure. Checks in order:

      1. Each joint has wall_a AND wall_b set (no None pointers).
      2. Both walls are members of walls_in_level (i.e. children of
         the Level being framed).
      3. wall_a != wall_b (no self-joint).
      4. No two joints reference the same (wall, end) — a wall can have
         at most one joint per end.
    """
    wall_set = set(walls_in_level)

    for i, joint in enumerate(joints, start=1):
        if joint.wall_a is None or joint.wall_b is None:
            return (False, f"Joint {i}: wall_a and wall_b must both be set")
        if joint.wall_a not in wall_set or joint.wall_b not in wall_set:
            return (False, f"Joint {i}: both walls must be in this Level")
        if joint.wall_a == joint.wall_b:
            return (False, f"Joint {i}: wall_a and wall_b must be different walls")

    used: dict[tuple[str, str], int] = {}
    for i, joint in enumerate(joints, start=1):
        for wall, end in (
            (joint.wall_a, joint.wall_a_end),
            (joint.wall_b, joint.wall_b_end),
        ):
            key = (wall.name, end)
            if key in used:
                return (
                    False,
                    f"Joint {i}: {wall.name}'s {end} end is already "
                    f"used by Joint {used[key]}",
                )
            used[key] = i

    return (True, "")


# Backward-compatibility aliases for v0.1 callers.
make_lumber_mesh = make_box_mesh
cutlist_label = lumber_cutlist_label

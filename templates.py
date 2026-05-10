"""Lumber, sheet-good, and panel dimension data and mesh construction."""

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


# Backward-compatibility aliases for v0.1 callers.
make_lumber_mesh = make_box_mesh
cutlist_label = lumber_cutlist_label

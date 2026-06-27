"""Operator: generate a cut list of all tagged Praxova material in the scene.

Output goes to two places:
    1. A Blender Text datablock named 'Praxova Cut List' (always).
    2. A .txt file alongside the .blend file (only if .blend has been saved).

The disk file is named '<blendfile_basename>_cutlist.txt' and lives in the
same directory as the .blend.

LUMBER OUTPUT FORMAT (v0.4):
    LUMBER \u2014 CUT LIST
    ----------------------
       3  x  2x4x8 H
       8  x  2x4x8 V  \u2192 cut to 91.5"

    LUMBER \u2014 ORDER SUMMARY
    ---------------------------
      11  x  2x4x8  (3 H, 8 V)

The CUT LIST shows per-piece detail with a '-> cut to N"' annotation when
the final cut length is shorter than the purchased stock. The ORDER SUMMARY
aggregates by stock SKU (nominal + stock length in feet) across orientations
with an orientation parenthetical for traceability - what you actually
take to the lumberyard.

SHEET and PANEL sections retain the v0.3.x single-section format. Neither
has a cut-from-stock concept in v0.4.
"""

import os
from collections import Counter
from datetime import datetime

import bpy


TEXT_DATABLOCK_NAME = "Praxova Cut List"


# ---------------------------------------------------------------------------
# Tag helpers
# ---------------------------------------------------------------------------

def _effective_stock_length_in(tag) -> float:
    """Return stock length, falling back to length_in when not explicitly set.

    The stock_length_in field was added in v0.4. Objects tagged by v0.3.x
    builds of the add-on don't have it - it reads back as 0.0 (FloatProperty
    default). For those, stock equals the cut length (no cut), which matches
    v0.3.x behavior where add_lumber always placed stock as-is.
    """
    if tag.stock_length_in > 0:
        return tag.stock_length_in
    return float(tag.length_in)


def _format_inches(val: float) -> str:
    """Format an inch dimension without trailing zeros.

    91.5 -> '91.5', 96.0 -> '96', 91.625 -> '91.625'.
    Three decimals is enough for common framing fractions (.0625, .125,
    .375, .5, .625, .75, .875).
    """
    if val == int(val):
        return str(int(val))
    return f"{val:.3f}".rstrip("0").rstrip(".")


# ---------------------------------------------------------------------------
# Sort keys
# ---------------------------------------------------------------------------

def _lumber_sort_key(label: str):
    """Sort lumber labels by nominal size, then length, then orientation."""
    try:
        size_len, orient = label.rsplit(' ', 1)
    except ValueError:
        return (label, 0, "")
    parts = size_len.split('x')
    try:
        length = int(parts[-1])
        nominal = 'x'.join(parts[:-1])
    except ValueError:
        return (size_len, 0, orient)
    return (nominal, length, orient)


def _sheet_sort_key(label: str):
    """Sort sheet labels by thickness, then material, then size, then orient.

    Label format: '<thickness>" <MAT> <size> <orient>', e.g. '1/2" PLY 4x8 V'.
    """
    parts = label.split()
    if len(parts) != 4:
        return (label,)
    thickness_str, material, size, orient = parts
    # Convert "1/2" to a sortable float.
    thickness_val = 0.0
    try:
        num = thickness_str.rstrip('"')
        if '/' in num:
            a, b = num.split('/')
            thickness_val = float(a) / float(b)
        else:
            thickness_val = float(num)
    except (ValueError, ZeroDivisionError):
        pass
    return (thickness_val, material, size, orient)


def _panel_sort_key(label: str):
    """Sort panel labels by material, then width, then length, then orient.

    Label format: '<width>" <Material> x <length> <orient>',
    e.g. '36" Metal x 8 V'.
    """
    parts = label.split()
    if len(parts) != 5:
        return (label,)
    width_str, material, _x, length_str, orient = parts
    try:
        width = float(width_str.rstrip('"'))
        length = int(length_str)
    except ValueError:
        return (label,)
    return (material, width, length, orient)


def _format_section(title: str, counter: Counter, sort_key) -> tuple[list[str], int]:
    """Render a single-list cut-list section (header + entries).

    Used for SHEETS and PANELS. LUMBER uses _format_lumber_sections
    instead because it renders two subsections (cut list + order summary).
    """
    if not counter:
        return [], 0
    lines = [title, "-" * len(title)]
    total = 0
    for label in sorted(counter, key=sort_key):
        qty = counter[label]
        total += qty
        lines.append(f"  {qty:4d}  x  {label}")
    return lines, total


# ---------------------------------------------------------------------------
# Lumber two-section rendering (v0.4)
# ---------------------------------------------------------------------------

def _format_lumber_sections(pieces: list[dict]) -> tuple[list[str], int]:
    """Render the LUMBER \u2014 CUT LIST and LUMBER \u2014 ORDER SUMMARY subsections.

    Args:
        pieces: list of per-piece dicts with keys:
            label                - stock cutlist label, e.g. "2x4x8 V"
            nominal              - e.g. "2x4"
            cut_in               - float, final cut length in inches
            stock_in             - float, purchased stock length in inches
            orient_short         - "V" / "H" / "A" (v0.7: A = ANGLED)
            cut_angle_start_deg  - float, degrees from square at x=0
                                   end (v0.7; 0.0 for square wall stock)
            cut_angle_end_deg    - float, degrees from square at the
                                   far end (v0.7; 0.0 for square stock)

    Returns:
        (lines, total_piece_count). Total is the number of physical pieces;
        it equals the sum of either subsection's counts since they describe
        the same pieces grouped differently.
    """
    if not pieces:
        return [], 0

    # Cut list aggregation: key = (label, cut_in, stock_in, a_start, a_end).
    # Two pieces with identical stock label AND identical cut length AND
    # identical cut angles collapse into one row; any one of those differ
    # and the pieces appear as separate rows — which is what you want at
    # the saw (a 91.5" square stud and a 91.5" 26.6°/26.6° top chord are
    # different cuts on the miter saw, even though both are 91.5" 2x4x8
    # pieces). v0.7 added the two angle components; wall pieces carry
    # 0.0 / 0.0, so non-truss aggregation is byte-for-byte unchanged.
    cut_counter: dict[
        tuple[str, float, float, float, float], int
    ] = {}

    # Order aggregation: key = (nominal_sort_tuple, stock_ft).
    # Value = {orient_short: count}. Numeric nominal tuple so '2x10' sorts
    # after '2x4' instead of alphabetically.
    order_data: dict[tuple[tuple[int, int], int], dict[str, int]] = {}

    for p in pieces:
        cut_key = (
            p['label'], p['cut_in'], p['stock_in'],
            p['cut_angle_start_deg'], p['cut_angle_end_deg'],
        )
        cut_counter[cut_key] = cut_counter.get(cut_key, 0) + 1

        try:
            a, b = p['nominal'].split('x')
            nominal_tuple: tuple[int, int] = (int(a), int(b))
        except (ValueError, IndexError):
            nominal_tuple = (999, 999)
        stock_ft = int(round(p['stock_in'] / 12))
        order_key = (nominal_tuple, stock_ft)
        bucket = order_data.setdefault(order_key, {})
        bucket[p['orient_short']] = bucket.get(p['orient_short'], 0) + 1

    lines: list[str] = []

    # --- Subsection 1: CUT LIST ---
    cut_title = "LUMBER \u2014 CUT LIST"
    lines.append(cut_title)
    lines.append("-" * len(cut_title))

    total = 0
    cut_sorted = sorted(
        cut_counter.items(),
        key=lambda kv: _lumber_sort_key(kv[0][0]) + (kv[0][1],),
    )
    for (label, cut_in, stock_in, a_start, a_end), qty in cut_sorted:
        total += qty
        # Epsilon comparison: floats stored on a FloatProperty can pick up
        # tiny rounding error. 0.01" is well below any practical cut
        # precision so it doesn't suppress real cuts.
        if cut_in < stock_in - 0.01:
            display = f'{label}  \u2192 cut to {_format_inches(cut_in)}"'
        else:
            display = label
        # v0.7: angle annotation for truss members (and any future piece
        # whose ends aren't square). Format: (start\u00b0 / end\u00b0). _format_
        # inches strips trailing zeros, so 26.6 stays 26.6 and 45.0 -> 45.
        # Square-ended pieces (wall stock, square heel blocks, square
        # bottom chords) carry 0.0 / 0.0 and skip the annotation entirely.
        if a_start != 0.0 or a_end != 0.0:
            display += (
                f"  ({_format_inches(a_start)}\u00b0"
                f" / {_format_inches(a_end)}\u00b0)"
            )
        lines.append(f"  {qty:4d}  x  {display}")

    # --- Subsection 2: ORDER SUMMARY ---
    lines.append("")
    order_title = "LUMBER \u2014 ORDER SUMMARY"
    lines.append(order_title)
    lines.append("-" * len(order_title))

    for (nominal_tuple, stock_ft), orients in sorted(order_data.items()):
        nominal_str = f"{nominal_tuple[0]}x{nominal_tuple[1]}"
        sku = f"{nominal_str}x{stock_ft}"
        total_sku = sum(orients.values())
        if len(orients) > 1:
            # Sort V before H for consistent reading order.
            ordered_orients = sorted(
                orients.keys(), key=lambda o: (o != 'V', o),
            )
            breakdown = ", ".join(
                f"{orients[o]} {o}" for o in ordered_orients
            )
            lines.append(f"  {total_sku:4d}  x  {sku}  ({breakdown})")
        else:
            lines.append(f"  {total_sku:4d}  x  {sku}")

    return lines, total


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def _build_report() -> tuple[str, int, dict[str, int]]:
    """Walk the scene and assemble the cut-list report text.

    Returns:
        (full_text, grand_total, totals_by_category).
    """
    lumber_pieces: list[dict] = []
    sheet_counter: Counter = Counter()
    panel_counter: Counter = Counter()

    for obj in bpy.context.scene.objects:
        tag = getattr(obj, "praxova_lumber", None)
        if tag is None or not tag.is_lumber:
            continue
        if tag.category == 'SHEET':
            sheet_counter[tag.cutlist_label] += 1
        elif tag.category == 'PANEL':
            panel_counter[tag.cutlist_label] += 1
        else:
            cut_in = round(float(tag.length_in), 4)
            stock_in = round(_effective_stock_length_in(tag), 4)
            lumber_pieces.append({
                'label': tag.cutlist_label,
                'nominal': tag.nominal_size,
                'cut_in': cut_in,
                'stock_in': stock_in,
                # v0.7: ANGLED -> 'A' alongside VERTICAL -> 'V', else 'H'.
                # Mirrors templates.lumber_cutlist_label's suffix dict so
                # the orientation glyph matches the cutlist_label suffix.
                'orient_short': {
                    'VERTICAL': 'V', 'ANGLED': 'A',
                }.get(tag.orientation, 'H'),
                # v0.7: cut-angle metadata for the CUT LIST annotation.
                # Wall studs/plates default to 0.0 / 0.0 (FloatProperty
                # defaults from PraxovaLumberProps), so non-truss pieces
                # render unchanged.
                'cut_angle_start_deg': round(
                    float(tag.cut_angle_start_deg), 1,
                ),
                'cut_angle_end_deg': round(
                    float(tag.cut_angle_end_deg), 1,
                ),
            })

    filename = bpy.path.basename(bpy.data.filepath) or "(unsaved)"
    timestamp = datetime.now().isoformat(timespec='seconds')

    lines = [
        "PRAXOVA CUT LIST",
        "=" * 50,
        f"File:      {filename}",
        f"Generated: {timestamp}",
        "",
    ]

    lumber_lines, lumber_total = _format_lumber_sections(lumber_pieces)
    sheet_lines, sheet_total = _format_section(
        "SHEETS", sheet_counter, _sheet_sort_key,
    )
    panel_lines, panel_total = _format_section(
        "PANELS", panel_counter, _panel_sort_key,
    )

    if lumber_lines:
        lines.extend(lumber_lines)
        lines.append("")
    if sheet_lines:
        lines.extend(sheet_lines)
        lines.append("")
    if panel_lines:
        lines.extend(panel_lines)
        lines.append("")

    grand_total = lumber_total + sheet_total + panel_total
    lines.append("=" * 50)
    lines.append(f"GRAND TOTAL: {grand_total} pieces")

    # Show category subtotals whenever 2 or more categories have items.
    subtotals = [
        ("Lumber", lumber_total),
        ("Sheets", sheet_total),
        ("Panels", panel_total),
    ]
    nonzero = [(name, n) for name, n in subtotals if n > 0]
    if len(nonzero) >= 2:
        for name, n in nonzero:
            lines.append(f"  {name}: {n}")

    return ("\n".join(lines),
            grand_total,
            {'LUMBER': lumber_total, 'SHEET': sheet_total, 'PANEL': panel_total})


def _disk_path_for_current_blend() -> str | None:
    """Return the disk path for the cut-list .txt next to the .blend, or None."""
    if not bpy.data.filepath:
        return None
    blend_dir = os.path.dirname(bpy.data.filepath)
    blend_name = os.path.splitext(os.path.basename(bpy.data.filepath))[0]
    return os.path.join(blend_dir, f"{blend_name}_cutlist.txt")


class PRAXOVA_OT_generate_cutlist(bpy.types.Operator):
    """Walk the scene, count tagged material by label, write a cut list.

    Always writes to a Blender Text datablock; also writes to a .txt file
    alongside the .blend if the file has been saved.
    """

    bl_idname = "praxova.generate_cutlist"
    bl_label = "Generate Cut List"
    bl_description = (
        "Generate a cut list of all tagged Praxova material. "
        "Writes to a Text datablock and (if the .blend is saved) to a "
        ".txt file next to the .blend"
    )
    bl_options = {'REGISTER'}

    def execute(self, context):
        text_body, grand_total, by_cat = _build_report()

        if grand_total == 0:
            self.report({'WARNING'}, "No tagged Praxova material found in scene")
            return {'CANCELLED'}

        # 1. Always: write to Text datablock.
        text = bpy.data.texts.get(TEXT_DATABLOCK_NAME)
        if text is None:
            text = bpy.data.texts.new(TEXT_DATABLOCK_NAME)
        text.clear()
        text.write(text_body)

        # 2. If .blend is saved: also write to disk.
        disk_path = _disk_path_for_current_blend()
        disk_status = ""
        if disk_path is not None:
            try:
                with open(disk_path, 'w', encoding='utf-8') as fh:
                    fh.write(text_body)
                disk_status = f", saved to {disk_path}"
            except OSError as e:
                disk_status = f" (disk write failed: {e})"
        else:
            disk_status = " (save the .blend to also write to disk)"

        self.report(
            {'INFO'},
            f"Cut list: {grand_total} pieces -> Text '{TEXT_DATABLOCK_NAME}'{disk_status}",
        )
        return {'FINISHED'}

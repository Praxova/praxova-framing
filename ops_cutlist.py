"""Operator: generate a cut list of all tagged Praxova material in the scene.

Output goes to two places:
    1. A Blender Text datablock named 'Praxova Cut List' (always).
    2. A .txt file alongside the .blend file (only if .blend has been saved).

The disk file is named '<blendfile_basename>_cutlist.txt' and lives in the
same directory as the .blend.
"""

import os
from collections import Counter
from datetime import datetime

import bpy


TEXT_DATABLOCK_NAME = "Praxova Cut List"


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
    """Render a cut-list section (header + entries) and return its total."""
    if not counter:
        return [], 0
    lines = [title, "-" * len(title)]
    total = 0
    for label in sorted(counter, key=sort_key):
        qty = counter[label]
        total += qty
        lines.append(f"  {qty:4d}  x  {label}")
    return lines, total


def _build_report() -> tuple[str, int, dict[str, int]]:
    """Walk the scene and assemble the cut-list report text.

    Returns:
        (full_text, grand_total, totals_by_category).
    """
    lumber_counter: Counter = Counter()
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
            lumber_counter[tag.cutlist_label] += 1

    filename = bpy.path.basename(bpy.data.filepath) or "(unsaved)"
    timestamp = datetime.now().isoformat(timespec='seconds')

    lines = [
        "PRAXOVA CUT LIST",
        "=" * 50,
        f"File:      {filename}",
        f"Generated: {timestamp}",
        "",
    ]

    lumber_lines, lumber_total = _format_section(
        "LUMBER", lumber_counter, _lumber_sort_key,
    )
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

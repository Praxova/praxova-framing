"""Menus and N-panel for Praxova Framing."""

import bpy

from . import templates
from . import server as _server  # v0.3: bridge state for the MCP Bridge subpanel


# ===========================================================================
# Add menu - top-level submenu and per-size submenus
# ===========================================================================

class PRAXOVA_MT_add_lumber_submenu(bpy.types.Menu):
    """Top-level Praxova submenu under the 3D View Add menu.

    Lists per-size submenus for lumber, then the Sheets and Panels submenus.
    """

    bl_idname = "PRAXOVA_MT_add_lumber_submenu"
    bl_label = "Praxova Lumber"

    def draw(self, context):
        layout = self.layout
        for nominal in templates.LUMBER_TYPES:
            safe = nominal.replace('x', '_')
            layout.menu(f"PRAXOVA_MT_lumber_{safe}", text=nominal)
        layout.separator()
        layout.menu(PRAXOVA_MT_sheets_submenu.bl_idname, text="Sheets")
        layout.menu(PRAXOVA_MT_panels_submenu.bl_idname, text="Panels")


class PRAXOVA_MT_sheets_submenu(bpy.types.Menu):
    """Sheet goods submenu: plywood and OSB at 1/2" and 3/4", V and H."""

    bl_idname = "PRAXOVA_MT_sheets_submenu"
    bl_label = "Sheets"

    def draw(self, context):
        layout = self.layout

        row = layout.row()

        # --- Vertical column ---
        col = row.column()
        col.label(text="Vertical", icon='EMPTY_SINGLE_ARROW')
        for material, thickness in _sheet_combinations():
            mat_label = templates.SHEET_MATERIAL_LABELS[material]
            op = col.operator(
                "praxova.add_sheet",
                text=f'{thickness}" {mat_label} 4x8',
            )
            op.material = material
            op.thickness = thickness
            op.size = '4x8'
            op.orientation = 'VERTICAL'

        # --- Horizontal column ---
        col = row.column()
        col.label(text="Horizontal", icon='EMPTY_ARROWS')
        for material, thickness in _sheet_combinations():
            mat_label = templates.SHEET_MATERIAL_LABELS[material]
            op = col.operator(
                "praxova.add_sheet",
                text=f'{thickness}" {mat_label} 4x8',
            )
            op.material = material
            op.thickness = thickness
            op.size = '4x8'
            op.orientation = 'HORIZONTAL'


class PRAXOVA_MT_panels_submenu(bpy.types.Menu):
    """Panel submenu: metal roofing/siding panels, V and H."""

    bl_idname = "PRAXOVA_MT_panels_submenu"
    bl_label = "Panels"

    def draw(self, context):
        layout = self.layout

        row = layout.row()

        # --- Vertical column ---
        col = row.column()
        col.label(text="Vertical", icon='EMPTY_SINGLE_ARROW')
        for material, size_key in _panel_combinations():
            mat_label = templates.PANEL_MATERIAL_LABELS[material]
            width_str, length_str = size_key.split('x')
            display = f'{mat_label} {width_str}" x {length_str}\''
            op = col.operator("praxova.add_panel", text=display)
            op.material = material
            op.size = size_key
            op.orientation = 'VERTICAL'

        # --- Horizontal column ---
        col = row.column()
        col.label(text="Horizontal", icon='EMPTY_ARROWS')
        for material, size_key in _panel_combinations():
            mat_label = templates.PANEL_MATERIAL_LABELS[material]
            width_str, length_str = size_key.split('x')
            display = f'{mat_label} {width_str}" x {length_str}\''
            op = col.operator("praxova.add_panel", text=display)
            op.material = material
            op.size = size_key
            op.orientation = 'HORIZONTAL'


def _sheet_combinations() -> list[tuple[str, str]]:
    """Stable ordering of (material, thickness_callout) for menu display."""
    out = []
    for material in ("PLYWOOD", "OSB"):
        for thickness in ("1/2", "3/4"):
            if (material, thickness) in templates.SHEET_THICKNESS_ACTUAL:
                out.append((material, thickness))
    return out


def _panel_combinations() -> list[tuple[str, str]]:
    """Stable ordering of (material, size_key) for panel menu display."""
    out = []
    for material in ("METAL",):
        for size_key in templates.PANEL_SIZES:
            out.append((material, size_key))
    return out


def create_size_menu_classes() -> list[type]:
    """Generate one Menu class per lumber size.

    Each class lists every available length in two columns: Vertical and
    Horizontal. Returned classes are registered alongside the static UI
    classes in __init__.register().
    """
    classes: list[type] = []

    for nominal in templates.LUMBER_TYPES:
        safe = nominal.replace('x', '_')
        idname = f"PRAXOVA_MT_lumber_{safe}"

        def _make_draw(nom: str):
            def draw(self, context):
                layout = self.layout
                lengths = templates.LENGTHS_BY_TYPE.get(nom, [])

                row = layout.row()

                col = row.column()
                col.label(text="Vertical", icon='EMPTY_SINGLE_ARROW')
                for L in lengths:
                    op = col.operator(
                        "praxova.add_lumber",
                        text=f"{nom} x {L}'",
                    )
                    op.nominal = nom
                    op.length_ft = L
                    op.orientation = 'VERTICAL'

                col = row.column()
                col.label(text="Horizontal", icon='EMPTY_ARROWS')
                for L in lengths:
                    op = col.operator(
                        "praxova.add_lumber",
                        text=f"{nom} x {L}'",
                    )
                    op.nominal = nom
                    op.length_ft = L
                    op.orientation = 'HORIZONTAL'
            return draw

        cls = type(
            idname,
            (bpy.types.Menu,),
            {
                "bl_idname": idname,
                "bl_label": nominal,
                "draw": _make_draw(nominal),
            },
        )
        classes.append(cls)

    return classes


def add_to_add_menu(self, context):
    """Append our submenu to the 3D Viewport's Add menu."""
    self.layout.separator()
    self.layout.menu(
        PRAXOVA_MT_add_lumber_submenu.bl_idname,
        icon='MESH_CUBE',
    )


# ===========================================================================
# N-panel
# ===========================================================================

# OC spacing presets. (display_label, value_in_inches).
# Stud/joist spacing in inches on row 1; post spacing in feet on row 2.
# The underlying field is always inches, so 8' stores as 96.0.
_OC_PRESETS_INCHES: tuple[tuple[str, float], ...] = (
    ('12"',   12.0),
    ('16"',   16.0),
    ('19.2"', 19.2),
    ('24"',   24.0),
)
_OC_PRESETS_FEET: tuple[tuple[str, float], ...] = (
    ("8'",  96.0),
    ("10'", 120.0),
)

# Fill preset spans in feet (stored as inches). Used by the v0.3.3 Fill
# Edge-to-Edge duplicator. Six entries laid out in two rows of three so
# the buttons don't get cramped at the N-panel's default width.
_FILL_PRESETS_FEET: tuple[tuple[str, float], ...] = (
    ("8'",  96.0),
    ("12'", 144.0),
    ("16'", 192.0),
    ("20'", 240.0),
    ("24'", 288.0),
    ("32'", 384.0),
)


class PRAXOVA_PT_main_panel(bpy.types.Panel):
    """Main Praxova Framing panel in the 3D View N-panel ('Praxova' tab)."""

    bl_idname = "PRAXOVA_PT_main_panel"
    bl_label = "Praxova Framing"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Praxova"

    def draw(self, context):
        layout = self.layout
        scn = context.scene.praxova_framing

        # --- Scene units check ---
        units = context.scene.unit_settings
        if units.system != 'IMPERIAL' or units.length_unit != 'INCHES':
            box = layout.box()
            box.label(text="Scene not set to imperial", icon='ERROR')
            box.operator("praxova.set_imperial_units", icon='SETTINGS')

        # --- OC duplication ---
        box = layout.box()
        box.label(text="On-Center Duplicate", icon='MOD_ARRAY')

        # Row 1: stud/joist spacing in inches.
        row = box.row(align=True)
        for label, spacing_in in _OC_PRESETS_INCHES:
            op = row.operator("praxova.set_spacing", text=label)
            op.spacing = spacing_in

        # Row 2: post/timber spacing in feet (stored as inches).
        row = box.row(align=True)
        for label, spacing_in in _OC_PRESETS_FEET:
            op = row.operator("praxova.set_spacing", text=label)
            op.spacing = spacing_in

        box.prop(scn, "spacing_in")
        box.prop(scn, "count")

        row = box.row(align=True)
        row.prop(scn, "direction", expand=True)

        box.operator("praxova.duplicate_oc", icon='MOD_ARRAY')

        # --- Fill (edge-to-edge, v0.3.3) ---
        # Sister section to OC Duplicate above, but stepping along local Y
        # by the source's own width. Sheets and panels only - lumber is
        # refused by the operator with a pointer back to OC Duplicate.
        box = layout.box()
        box.label(text="Fill Edge-to-Edge", icon='SEQ_STRIP_DUPLICATE')

        # Status line - confirms what the operator will fill from, plus the
        # exact width that the spacing will use. When nothing compatible is
        # active, a hint replaces it (the operator will still error out on
        # click; this hint just front-loads the obvious case).
        active = context.active_object
        fillable = (
            active is not None
            and active.praxova_lumber.is_lumber
            and active.praxova_lumber.category in {'SHEET', 'PANEL'}
        )
        if fillable:
            width_in = templates.fill_axis_width_in(active)
            box.label(
                text=f"Source: {active.praxova_lumber.cutlist_label}  ({width_in:g}\" wide)",
                icon='OBJECT_DATA',
            )
        else:
            box.label(text="Select a sheet or panel", icon='INFO')

        # Preset distance buttons (two rows of three).
        # Clicking a preset fires praxova.set_fill_span which writes the
        # value into fill_span_in. That field's update callback then
        # recomputes fill_count from the active object's width.
        row = box.row(align=True)
        for label, span_in in _FILL_PRESETS_FEET[:3]:
            op = row.operator("praxova.set_fill_span", text=label)
            op.span = span_in
        row = box.row(align=True)
        for label, span_in in _FILL_PRESETS_FEET[3:]:
            op = row.operator("praxova.set_fill_span", text=label)
            op.span = span_in

        box.prop(scn, "fill_span_in")
        box.prop(scn, "fill_count")

        row = box.row(align=True)
        row.prop(scn, "fill_direction", expand=True)

        # Fill button reuses MOD_ARRAY for visual parity with OC's button
        # since both are array-style operations.
        box.operator("praxova.duplicate_e2e", icon='MOD_ARRAY', text="Fill")

        # --- Cut list ---
        box = layout.box()
        box.label(text="Cut List", icon='TEXT')
        box.operator("praxova.generate_cutlist", icon='FILE_TEXT')
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="Output: Text datablock", icon='DOT')
        col.label(text="\"Praxova Cut List\" + .txt", icon='BLANK1')
        col.label(text="next to .blend (if saved)", icon='BLANK1')

        # --- v0.3: MCP Bridge ---
        # Lets an external MCP server (mcp_server/) connect and drive the
        # operators above from an LLM agent. Localhost-only.
        box = layout.box()
        box.label(text="MCP Bridge", icon='URL')
        running = _server.bridge.is_running()

        # Port input - greyed out while running so the user sees that
        # changing it won't take effect until restart.
        row = box.row(align=True)
        row.enabled = not running
        row.prop(scn, "bridge_port", text="Port")

        if running:
            box.label(
                text=f"Listening on 127.0.0.1:{_server.bridge.get_port()}",
                icon='RADIOBUT_ON',
            )
            box.operator("praxova.stop_bridge", icon='PAUSE', text="Stop Bridge")
        else:
            box.label(text="Stopped", icon='RADIOBUT_OFF')
            box.operator("praxova.start_bridge", icon='PLAY', text="Start Bridge")

        # --- Active object info ---
        obj = context.active_object
        if obj is not None and obj.praxova_lumber.is_lumber:
            box = layout.box()
            box.label(text="Active Material", icon='INFO')
            tag = obj.praxova_lumber
            col = box.column(align=True)

            if tag.category == 'LUMBER':
                col.label(text=f"Type:        {tag.nominal_size}")
                if tag.length_in:
                    col.label(
                        text=f"Length:      {tag.length_in}\" ({tag.length_in // 12}')",
                    )
            elif tag.category == 'SHEET':
                mat = templates.SHEET_MATERIAL_LABELS.get(
                    tag.sheet_material, tag.sheet_material,
                )
                col.label(text=f"Material:    {tag.sheet_thickness_callout}\" {mat}")
                col.label(text=f"Size:        {tag.sheet_size_key}")
                actual = templates.SHEET_THICKNESS_ACTUAL.get(
                    (tag.sheet_material, tag.sheet_thickness_callout),
                )
                if actual is not None:
                    col.label(text=f"Actual:      {actual:.4f}\" thick")
            elif tag.category == 'PANEL':
                mat = templates.PANEL_MATERIAL_LABELS.get(
                    tag.panel_material, tag.panel_material,
                )
                col.label(text=f"Material:    {mat}")
                col.label(text=f"Size:        {tag.panel_size_key}")
                profile = templates.PANEL_MATERIAL_PROFILE.get(tag.panel_material)
                if profile is not None:
                    col.label(
                        text=f"Profile:     {profile:.3f}\" (generic placeholder)",
                    )

            col.label(text=f"Orientation: {tag.orientation.title()}")
            col.label(text=f"Label:       {tag.cutlist_label}")

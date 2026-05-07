"""Menus and N-panel for Praxova Framing."""

import bpy

from . import templates


# ===========================================================================
# Add menu - top-level submenu and per-size submenus
# ===========================================================================

class PRAXOVA_MT_add_lumber_submenu(bpy.types.Menu):
    """Top-level Praxova submenu under the 3D View Add menu.

    Lists per-size submenus for lumber, then the Sheets submenu.
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


def _sheet_combinations() -> list[tuple[str, str]]:
    """Stable ordering of (material, thickness_callout) for menu display."""
    out = []
    for material in ("PLYWOOD", "OSB"):
        for thickness in ("1/2", "3/4"):
            if (material, thickness) in templates.SHEET_THICKNESS_ACTUAL:
                out.append((material, thickness))
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

        row = box.row(align=True)
        for preset in (12.0, 16.0, 19.2, 24.0):
            op = row.operator("praxova.set_spacing", text=f'{preset:g}"')
            op.spacing = preset

        box.prop(scn, "spacing_in")
        box.prop(scn, "count")

        row = box.row(align=True)
        row.prop(scn, "direction", expand=True)

        box.operator("praxova.duplicate_oc", icon='MOD_ARRAY')

        # --- Cut list ---
        box = layout.box()
        box.label(text="Cut List", icon='TEXT')
        box.operator("praxova.generate_cutlist", icon='FILE_TEXT')
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="Output: Text datablock", icon='DOT')
        col.label(text="\"Praxova Cut List\" + .txt", icon='BLANK1')
        col.label(text="next to .blend (if saved)", icon='BLANK1')

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
            else:  # SHEET
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

            col.label(text=f"Orientation: {tag.orientation.title()}")
            col.label(text=f"Label:       {tag.cutlist_label}")

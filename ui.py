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
# Wall framing source resolution (v0.6)
# ===========================================================================

def _get_wall_source(context):
    """Return the PropertyGroup the Wall Framing tab should edit right now.

    v0.6 introduced per-wall PraxovaWallProps storage. When the active
    object is a Praxova-managed wall Empty (praxova_wall.is_wall == True),
    the tab edits that wall's own props — changes take effect on the
    next Frame Wall (which re-frames in place). Otherwise the tab edits
    the scene-level scratch on PraxovaSceneProps, and the next Frame
    Wall creates a new wall Empty from those values.

    Both PropertyGroups carry the same wall_*  and wall_openings field
    shape, so callers can read uniformly off the returned `source`.
    """
    active = context.active_object
    if (active is not None
            and getattr(active, 'praxova_wall', None) is not None
            and active.praxova_wall.is_wall):
        return active.praxova_wall
    return context.scene.praxova_framing


# ===========================================================================
# Openings UIList + operators (v0.5)
# ===========================================================================

class PRAXOVA_UL_openings(bpy.types.UIList):
    """UIList row renderer for PraxovaSceneProps.wall_openings.

    Each row shows the opening type (Door/Win), x-offset, and rough-
    opening WxH at a glance. The Add Door / Add Window buttons next to
    the list create new rows; the icons next to each row come from
    here via item.opening_type.
    """

    def draw_item(self, context, layout, data, item, icon,
                  active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            type_short = "Door" if item.opening_type == 'DOOR' else "Win"
            icon_id = (
                'MESH_PLANE' if item.opening_type == 'DOOR'
                else 'OUTLINER_OB_LATTICE'
            )
            layout.label(
                text=(
                    f"{type_short}  x={item.x_offset_in:.1f}\"  "
                    f"{item.ro_width_in:.0f}×{item.ro_height_in:.0f}\""
                ),
                icon=icon_id,
            )
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="D" if item.opening_type == 'DOOR' else "W")


class PRAXOVA_OT_add_door(bpy.types.Operator):
    """Append a door opening with standard 38" x 82" RO defaults."""

    bl_idname = "praxova.add_door"
    bl_label = "Add Door"
    bl_description = "Append a door opening with standard 38\" x 82\" RO defaults"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # v0.6: target the active wall's openings if a wall is active,
        # else scratch on the scene. Both PropertyGroups expose the same
        # wall_openings / wall_openings_active fields.
        target = _get_wall_source(context)
        new = target.wall_openings.add()
        new.opening_type = 'DOOR'
        new.ro_width_in = 38.0
        new.ro_height_in = 82.0
        new.sill_height_in = 0.0
        new.header_nominal = target.wall_nominal
        new.jack_count = templates.recommend_jack_count(38.0)
        templates.redistribute_openings_evenly(
            target.wall_openings, target.wall_length_in,
        )
        target.wall_openings_active = len(target.wall_openings) - 1
        return {'FINISHED'}


class PRAXOVA_OT_add_window(bpy.types.Operator):
    """Append a window opening with standard 36" x 48" RO and 36" sill."""

    bl_idname = "praxova.add_window"
    bl_label = "Add Window"
    bl_description = (
        "Append a window opening with standard 36\" x 48\" RO at 36\" sill"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # v0.6: target the active wall's openings if a wall is active,
        # else scratch on the scene.
        target = _get_wall_source(context)
        new = target.wall_openings.add()
        new.opening_type = 'WINDOW'
        new.ro_width_in = 36.0
        new.ro_height_in = 48.0
        new.sill_height_in = 36.0
        new.header_nominal = target.wall_nominal
        new.jack_count = templates.recommend_jack_count(36.0)
        templates.redistribute_openings_evenly(
            target.wall_openings, target.wall_length_in,
        )
        target.wall_openings_active = len(target.wall_openings) - 1
        return {'FINISHED'}


class PRAXOVA_OT_remove_opening(bpy.types.Operator):
    """Remove the active opening from the list."""

    bl_idname = "praxova.remove_opening"
    bl_label = "Remove Opening"
    bl_description = "Remove the active opening from the list"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        # v0.6: poll based on the current edit target (active wall or scratch).
        return len(_get_wall_source(context).wall_openings) > 0

    def execute(self, context):
        target = _get_wall_source(context)
        idx = target.wall_openings_active
        target.wall_openings.remove(idx)
        target.wall_openings_active = max(
            0, min(idx, len(target.wall_openings) - 1),
        )
        return {'FINISHED'}


class PRAXOVA_OT_distribute_openings(bpy.types.Operator):
    """Reset all opening x-offsets to evenly-spaced layout."""

    bl_idname = "praxova.distribute_openings"
    bl_label = "Distribute Evenly"
    bl_description = "Reset all opening x-offsets to evenly-spaced layout"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(_get_wall_source(context).wall_openings) > 0

    def execute(self, context):
        target = _get_wall_source(context)
        templates.redistribute_openings_evenly(
            target.wall_openings, target.wall_length_in,
        )
        return {'FINISHED'}


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

        # --- Wall framing (v0.4 / v0.5 / v0.6) ---
        # Composite operator: places plates and studs (and v0.5 opening
        # pieces) parented to an Empty. v0.6 makes the tab context-
        # sensitive — when a Praxova wall Empty is active, the tab edits
        # that wall's own PraxovaWallProps (so its values persist across
        # Blender sessions and Frame Wall re-frames it in place); when
        # nothing relevant is active, the tab edits the scene-level
        # scratch on PraxovaSceneProps (Frame Wall then creates a new
        # wall from those values). The `source` resolver returns whichever
        # is correct for the current selection.
        box = layout.box()
        box.label(text="Wall Framing", icon='MOD_BUILD')

        source = _get_wall_source(context)
        active_obj = context.active_object
        is_active_wall = source is not scn
        if is_active_wall:
            box.label(
                text=f"Editing wall: {active_obj.name}",
                icon='OBJECT_DATA',
            )
        else:
            box.label(
                text="Editing scratch (creates new wall on Frame Wall)",
                icon='OBJECT_DATAMODE',
            )

        box.prop(source, "wall_length_in")
        box.prop(source, "wall_height_in")
        box.prop(source, "wall_nominal")
        box.prop(source, "wall_spacing_oc_in")
        box.prop(source, "wall_top_plate_count")
        box.prop(source, "wall_bottom_plate_count")

        # --- Openings sub-section (v0.5; v0.6 source-aware) ---
        # Sub-box inside the Wall Framing box: UIList of openings on the
        # left, per-row Add Door / Add Window / Remove / Distribute
        # column on the right, and a detail panel below for the active
        # opening's fields. The collection bound to template_list and
        # the active-opening readout both follow `source`, so editing an
        # active wall's openings doesn't mutate scene scratch (and
        # vice-versa).
        openings_box = box.box()
        openings_box.label(text="Openings:", icon='MOD_BOOLEAN')

        row = openings_box.row()
        row.template_list(
            "PRAXOVA_UL_openings", "",
            source, "wall_openings",
            source, "wall_openings_active",
            rows=3,
        )
        col = row.column(align=True)
        col.operator("praxova.add_door", text="", icon='MESH_PLANE')
        col.operator("praxova.add_window", text="", icon='OUTLINER_OB_LATTICE')
        col.operator("praxova.remove_opening", text="", icon='REMOVE')
        col.separator()
        col.operator("praxova.distribute_openings", text="", icon='MOD_ARRAY')

        if len(source.wall_openings) > 0:
            active_op = source.wall_openings[source.wall_openings_active]
            detail = openings_box.column(align=True)
            detail.prop(active_op, "opening_type")
            detail.prop(active_op, "x_offset_in")
            detail.prop(active_op, "ro_width_in")
            detail.prop(active_op, "ro_height_in")
            if active_op.opening_type == 'WINDOW':
                detail.prop(active_op, "sill_height_in")
            detail.prop(active_op, "header_nominal")
            detail.prop(active_op, "jack_count")

        # --- Live preview ---
        nominal = source.wall_nominal
        if nominal in templates.LUMBER_TYPES:
            plate_thickness_in = templates.LUMBER_TYPES[nominal][0]
            plate_stack_in = (
                source.wall_top_plate_count + source.wall_bottom_plate_count
            ) * plate_thickness_in
            stud_length_in = source.wall_height_in - plate_stack_in

            preview_col = box.column(align=True)
            preview_col.scale_y = 0.8

            if stud_length_in <= 0:
                preview_col.label(
                    text=f"Height too short for "
                         f"{plate_stack_in:g}\" plate stack",
                    icon='ERROR',
                )
            elif source.wall_length_in < 2 * plate_thickness_in:
                preview_col.label(
                    text=f"Length < {2 * plate_thickness_in:g}\" "
                         "needed for end studs",
                    icon='ERROR',
                )
            elif len(source.wall_openings) > 0:
                # v0.5: with openings, validate first so the user sees
                # the specific failing opening before any count summary.
                openings = list(source.wall_openings)
                ok, msg = templates.validate_openings(
                    openings,
                    source.wall_length_in, source.wall_height_in, nominal,
                    source.wall_top_plate_count, source.wall_bottom_plate_count,
                )
                if not ok:
                    preview_col.label(text=msg, icon='ERROR')
                else:
                    raw_xs = templates.stud_positions(
                        source.wall_length_in,
                        source.wall_spacing_oc_in,
                        plate_thickness_in,
                    )
                    layouts = [
                        templates.opening_framing_layout(
                            op, nominal, source.wall_height_in,
                            source.wall_top_plate_count,
                            source.wall_bottom_plate_count,
                        )
                        for op in openings
                    ]
                    filtered_xs = templates.filter_studs_around_openings(
                        raw_xs, plate_thickness_in, openings, layouts,
                    )
                    n_plates = (
                        source.wall_top_plate_count
                        + source.wall_bottom_plate_count
                    )
                    preview_col.label(
                        text=(
                            f"Preview: {len(filtered_xs)} studs + "
                            f"{len(openings)} opening"
                            f"{'s' if len(openings) != 1 else ''}, "
                            f"{n_plates} plates × "
                            f"{source.wall_length_in:g}\""
                        ),
                        icon='INFO',
                    )
            else:
                stud_xs = templates.stud_positions(
                    source.wall_length_in,
                    source.wall_spacing_oc_in,
                    plate_thickness_in,
                )
                n_studs = len(stud_xs)
                n_plates = (
                    source.wall_top_plate_count + source.wall_bottom_plate_count
                )
                preview_col.label(
                    text=f"Preview: {n_studs} studs x "
                         f"{stud_length_in:g}\", "
                         f"{n_plates} plates x "
                         f"{source.wall_length_in:g}\"",
                    icon='INFO',
                )

        box.operator("praxova.frame_wall", icon='MOD_BUILD')

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

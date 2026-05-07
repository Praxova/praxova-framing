# Praxova Framing

A Blender add-on for fast construction framing in 3D — lumber and sheet templates with one-click on-center duplication and cut-list export.

**Status:** Beta (v0.2.0). Pre-1.0 — APIs and the per-object data model may change between minor versions.

## What it does

- **Tagged templates** for dimensional lumber (2x4 / 2x6 / 2x8 / 2x10 / 2x12 / 6x6) and sheet goods (plywood and OSB at 1/2" and 3/4" performance categories, 4x8 size). Geometry is *actual* dimensions; cut-list labels use *nominal* / call-out sizes.
- **On-center duplicator** with preset spacing (12" / 16" / 19.2" / 24"), count, and Right/Left direction. Each duplicate is a separate Object (so the cut list is correct), but they share mesh data (so it's memory-efficient).
- **Cut list** generator that walks the scene, counts tagged objects by label, and writes to both an in-Blender Text datablock and a `.txt` file next to your `.blend`.
- **Add-menu integration** — `Add → Praxova Lumber → ...` for both lumber and sheets, in vertical and horizontal orientations.

## Install

1. Edit → Preferences → Get Extensions → top-right dropdown → **Install from Disk…**
2. Pick the addon zip (clone this repo and zip the directory contents at the root, with `blender_manifest.toml` at zip root).
3. Enable it if not enabled automatically.

The N-panel tab "Praxova" should appear in the 3D Viewport (press `N` to open).

**Targets:** Blender 4.2+ (uses the new extensions system). Tested on Blender 5.1.

## Sheet thickness — actuals vs. call-outs

Sheet goods are sold by **Performance Category** (the call-out), which doesn't match literal thickness:

| Call-out | Plywood actual | OSB actual |
|----------|----------------|------------|
| 1/2"     | 15/32" (0.469") | 7/16" (0.438") |
| 3/4"     | 23/32" (0.719") | 23/32" (0.719") |

Per APA PS 1 (plywood) and APA PS 2 (OSB). Geometry uses the actual; cut-list label uses the call-out so material orders match. Override `SHEET_THICKNESS_ACTUAL` in `templates.py` if your supplier uses different stock.

## Geometry orientation

Same convention for all materials:

| Orientation | X | Y | Z | Long axis |
|-------------|---|---|---|-----------|
| Vertical    | thickness | width | length | +Z |
| Horizontal  | length | width | thickness | +X |

Origin at min corner (0, 0, 0). Click the 3D cursor where you want the bottom-front-left corner of the piece.

## Data model

Each placed piece carries a `praxova_lumber` PropertyGroup with:

```
is_lumber:                bool    # "is Praxova-managed"
category:                 'LUMBER' | 'SHEET'
nominal_size:             "2x4", "6x6", ...        (lumber only)
length_in:                96, 120, ...             (lumber only)
sheet_material:           'PLYWOOD' | 'OSB'        (sheet only)
sheet_thickness_callout:  "1/2", "3/4"             (sheet only)
sheet_size_key:           "4x8"                    (sheet only)
orientation:              'VERTICAL' | 'HORIZONTAL'
cutlist_label:            "2x4x8 V" or "1/2\" PLY 4x8 V"
```

Filter for cut-list construction or external scripts:

```python
[obj for obj in bpy.data.objects if obj.praxova_lumber.is_lumber]
```

## Cut list

N-panel → **Cut List → Generate Cut List**. Output goes to:

1. A Blender Text datablock named **"Praxova Cut List"** — to view, split an editor area, change its type to Text Editor, and pick "Praxova Cut List" from the data picker.
2. A **`<blendfile>_cutlist.txt`** file alongside the .blend (only if the .blend has been saved). Status bar message shows the exact path.

## Roadmap

- v0.3 — MCP server in front of the operators (drive framing from agents)
- v0.4 — "Frame a wall" composite operator (plates + studs + corners in one shot)
- v0.5 — Door / window openings (king studs, jacks, headers, cripples)
- Later — additional sheet sizes (4x10, 4x12), 5/8" thickness, addon preferences for thickness overrides, post-frame-friendly OC presets (8'/10' for timber framing)

## License

GPL-2.0-or-later. See `LICENSE`. (Required for Blender add-ons that use the `bpy` API.)

## Author

Alton Lord — Praxova ([praxova.ai](https://praxova.ai))

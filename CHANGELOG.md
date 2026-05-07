# Changelog

All notable changes to Praxova Framing are documented here. The project follows [Semantic Versioning](https://semver.org/) with the convention that pre-1.0 versions (0.x) are considered beta — APIs and data model may change between minor versions.

## [0.2.0] — 2026-05-07

### Added
- **6x6 lumber** with stock lengths 8'/10'/12'/14'/16'/20'.
- **Sheet goods** — plywood and OSB at 1/2" and 3/4" call-outs, 4x8 size, vertical and horizontal orientations.
- Cut list now also writes to a `<blendfile>_cutlist.txt` file alongside the saved `.blend`, in addition to the in-Blender Text datablock.
- Cut list output is split into LUMBER and SHEETS sections with subtotals plus a grand total.
- Active-object info panel now handles sheets, showing call-out, actual thickness, size, and orientation.
- New `category` field on the per-object PropertyGroup (`'LUMBER'` or `'SHEET'`).
- New sheet-specific PropertyGroup fields: `sheet_material`, `sheet_thickness_callout`, `sheet_size_key`.

### Changed
- Renamed `templates.make_lumber_mesh` → `templates.make_box_mesh` (alias preserved for backward compat).
- Renamed `templates.cutlist_label` → `templates.lumber_cutlist_label` (alias preserved for backward compat).

### Standards encoded
- Sheet thickness actuals follow APA PS 1 (plywood) and APA PS 2 (OSB):
  - 1/2" plywood = 15/32" (0.469")
  - 1/2" OSB = 7/16" (0.438")
  - 3/4" plywood = 23/32" (0.719")
  - 3/4" OSB = 23/32" (0.719")

## [0.1.0] — 2026-05-07

### Added
- Lumber templates: 2x4, 2x6, 2x8, 2x10, 2x12 in 8'/10'/12'/14'/16' lengths (2x10 and 2x12 from 10').
- Vertical and horizontal orientations for each template.
- Add-menu integration: 3D View Add → Praxova Lumber → per-size submenus.
- Tagging via registered PropertyGroup (Blender 5.0+ recommended pattern, replaces deprecated dict-style custom properties for add-on use).
- Linked-data mesh sharing across instances of the same template (memory-efficient, doesn't break tagging).
- On-center spacing duplicator with preset buttons (12", 16", 19.2", 24"), custom spacing, count, and Right/Left direction toggle.
- Cut list generator that walks the scene, groups by label, and writes to a Blender Text datablock.
- N-panel UI on the "Praxova" tab including a one-shot "Set Scene to Imperial" helper.
- Blender 5.x extension manifest (`blender_manifest.toml`).

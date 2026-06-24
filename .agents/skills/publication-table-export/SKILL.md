---
name: publication-table-export
description: Create FPVS Toolbox publication-ready table assets from small tabular data. Use when a user asks to generate manuscript, poster, supplement, Great Tables-style, table-only, PNG, or SVG tables that should follow toolbox typography/colors and be saved under a project root in `9 - Tables`.
---

# Publication Table Export

## Purpose

Create table-only publication assets that match FPVS Toolbox figure styling and save them under a project root in `9 - Tables`.

Use the bundled script for final assets:

```powershell
.\.venv1\Scripts\python.exe .agents\skills\publication-table-export\scripts\export_publication_table.py `
  --project-root "C:\Path\To\FPVS Project" `
  --input ".codex-tmp\table.csv" `
  --output-name "semantic_categories_harmonics"
```

## Workflow

1. Identify the project root.
   - Use the active FPVS project root when available.
   - If the user only gives manuscript values, ask only if the project root is genuinely unknown.
   - The script creates `<project root>\9 - Tables` and never writes final assets elsewhere.

2. Build a small source table.
   - Prefer source workbook values over prose.
   - Keep rows in manuscript reading order.
   - Preserve p-value text exactly when formatting matters, such as `< 0.001`.
   - Use CSV or TSV. Use one header row.

3. Export table-only assets.
   - Do not embed table number, title, caption, description, source note, or methods text unless explicitly requested.
   - Generate both SVG and 600-DPI PNG by default.
   - Keep SVG text as vector text.
   - Use preview HTML only for inspection; the final publication assets are the PNG/SVG.

4. Verify outputs.
   - Confirm files exist under `<project root>\9 - Tables`.
   - Confirm PNG dimensions and DPI metadata.
   - Confirm SVG does not contain embedded caption/title text.
   - Run the path audit when adding or changing path behavior:

```powershell
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```

## Styling Contract

- Use `Main_App.gui.typography` and `Main_App.gui.style_tokens`.
- Body cells use `figure_tick`; column headers use `figure_axis_label`.
- Header row uses `SURFACE_ALT_BG`; body rows use white with subtle alternating `SURFACE_ALT_BG` stripes.
- Borders use `BORDER_COLOR` and `BORDER_SOFT_COLOR`; text uses `TEXT_PRIMARY`.
- Use 600 DPI PNG unless the user requests another value.
- Use 6.5 inches for broad tables. Use a narrower explicit width for compact tables.

## Script Notes

- `--project-root` is required and must resolve to an existing directory.
- `--output-name` is sanitized to a filename stem.
- `--columns` optionally selects/reorders columns from the source file.
- `--labels-json` optionally maps source column names to display labels.
- `--width-in` controls total table width.
- `--font-scale` scales the shared typography roles for dense or large tables.

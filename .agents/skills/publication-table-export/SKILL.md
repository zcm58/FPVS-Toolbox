---
name: publication-table-export
description: Create FPVS Toolbox publication-ready table assets from small tabular data. Use when a user asks to generate manuscript, poster, supplement, Great Tables-style, table-only, PNG, or SVG tables that should follow the GUI-neutral publication-table style and be saved under a project root in `9 - Tables`.
---

# Publication Table Export

## Purpose

Create table-only publication assets that match the FPVS Toolbox publication-table style and save them under a project root in `9 - Tables`.

Use the bundled script for final assets:

Command examples use the preferred `.venv1` interpreter. Substitute
`.venv\Scripts\python.exe` when `.venv1` is absent.

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

- Use the GUI-neutral `Main_App.exports.table_style` contract. Publication
  table assets must not import `Main_App.gui.typography` or
  `Main_App.gui.style_tokens`.
- Body and header roles preserve the established table typography through
  `table_font_size_px(...)` and `table_font_weight(...)`.
- Header and alternating rows use the shared table surface colors; borders and
  text use the shared table border/text colors.
- Use 600 DPI PNG unless the user requests another value.
- Use 6.5 inches for broad tables. Use a narrower explicit width for compact tables.

## Script Notes

- `--project-root` is required and must resolve to an existing directory.
- `--output-name` is sanitized to a filename stem.
- `--columns` optionally selects/reorders columns from the source file.
- `--labels-json` optionally maps source column names to display labels.
- `--width-in` controls total table width.
- `--font-scale` scales the shared typography roles for dense or large tables.

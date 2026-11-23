---
name: publication-table-export
description: Export small FPVS Toolbox manuscript, poster, or supplement tables as styled SVG and PNG assets under the project root in 9 - Tables.
---

# Publication Table Export

Use the active FPVS project root, or the existing project directory
supplied by the user. The helper takes the root explicitly and publishes
under its local `9 - Tables` directory.
[Project I/O](../../../docs/agent/architecture/project-io.md)

## Prepare and export

Use a small UTF-8 CSV or TSV with one header row and rows in reading
order. Prefer verified source values. Preserve units, missing data,
inequalities such as `< 0.001`, and meaningful numeric precision. Keep
table numbers, titles, captions, and methods outside the assets by default.

Run the exporter with the [repo interpreter](../../../docs/agent/guides/development.md).

```console
python .agents/skills/publication-table-export/scripts/export_publication_table.py --project-root "<project-root>" --input "<table.csv>" --output-name "<table-stem>"
```

- Use `--delimiter tab` for TSV. Select or reorder fields with
  `--columns` and specify display headers with `--labels-json`.
- Default assets are SVG with editable text and 600-DPI PNG, with HTML for
  preview. The exporter sanitizes the stem. Choose a new stem when existing
  assets should remain.
- Set `--width-in` for the intended minimum width. The default is 4.25
  inches, and content can expand the table. Inspect readability at the
  intended placement before adjusting `--font-scale` or the width.
- Keep typography, striping, and colors with `Main_App.exports.table_style`.
  [Figure generation standard](../../../docs/agent/quality/figure-generation.md#retained-toolbox-profiles)

## Verify the assets

Confirm the SVG and PNG resolve under `9 - Tables`. Check the table
against the source for row and column order, displayed values, and clipped
labels. Verify the PNG dimensions and DPI and the SVG text. Deliver the
SVG and PNG with the HTML only when it is useful as a preview.

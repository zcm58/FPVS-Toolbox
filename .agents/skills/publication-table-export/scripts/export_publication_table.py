"""Export FPVS publication-style table assets to a project's 9 - Tables folder."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[4]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Main_App.gui.style_tokens import (  # noqa: E402
    BORDER_COLOR,
    BORDER_SOFT_COLOR,
    SURFACE_ALT_BG,
    SURFACE_BG,
    TEXT_PRIMARY,
)
from Main_App.gui.typography import css_font_family, css_font_size, css_font_weight  # noqa: E402


TABLES_DIR_NAME = "9 - Tables"
DEFAULT_DPI = 600
SVG_PX_PER_IN = 96
DEFAULT_WIDTH_IN = 4.25
HEADER_HEIGHT_PX = 34
ROW_HEIGHT_PX = 30
MIN_COLUMN_WIDTH_PX = 92


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        raise SystemExit(f"Project root does not exist or is not a directory: {project_root}")

    source_path = args.input.resolve()
    rows = _read_rows(source_path, delimiter=args.delimiter)
    if not rows:
        raise SystemExit(f"Input table has no rows: {source_path}")

    source_columns = list(rows[0].keys())
    columns = _requested_columns(args.columns, source_columns)
    labels = _display_labels(args.labels_json, columns)
    table_rows = [[str(row.get(column, "")) for column in columns] for row in rows]

    output_dir = project_root / TABLES_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = _sanitize_stem(args.output_name)
    svg_path = output_dir / f"{output_stem}.svg"
    png_path = output_dir / f"{output_stem}.png"
    html_path = output_dir / f"{output_stem}.html"

    geometry = _geometry(labels, table_rows, args.width_in, args.font_scale)
    svg_text = _build_svg(labels, table_rows, geometry, font_scale=args.font_scale)
    svg_path.write_text(svg_text, encoding="utf-8")
    _write_png(png_path, labels, table_rows, geometry, dpi=args.dpi, font_scale=args.font_scale)
    html_path.write_text(_build_html(svg_text), encoding="utf-8")

    print(svg_path)
    print(png_path)
    print(html_path)
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True, help="FPVS project root that will receive 9 - Tables.")
    parser.add_argument("--input", type=Path, required=True, help="CSV/TSV source table with a header row.")
    parser.add_argument("--output-name", required=True, help="Filename stem for exported table assets.")
    parser.add_argument("--columns", help="Comma-separated source columns to select and order.")
    parser.add_argument("--labels-json", help='JSON object mapping source column names to display labels, e.g. {"z":"Z score"}.')
    parser.add_argument("--delimiter", default=",", help="Input delimiter. Use \"tab\" for TSV.")
    parser.add_argument("--width-in", type=float, default=DEFAULT_WIDTH_IN, help="Total table width in inches.")
    parser.add_argument("--dpi", type=int, default=DEFAULT_DPI, help="PNG DPI metadata and raster scale.")
    parser.add_argument("--font-scale", type=float, default=1.0, help="Multiplier for shared toolbox typography sizes.")
    return parser.parse_args(argv)


def _read_rows(path: Path, *, delimiter: str) -> list[dict[str, str]]:
    if delimiter.lower() == "tab":
        delimiter = "\t"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if not reader.fieldnames:
            raise SystemExit(f"Input table has no header row: {path}")
        return [dict(row) for row in reader]


def _requested_columns(columns_arg: str | None, source_columns: list[str]) -> list[str]:
    columns = [column.strip() for column in columns_arg.split(",")] if columns_arg else source_columns
    columns = [column for column in columns if column]
    missing = [column for column in columns if column not in source_columns]
    if missing:
        raise SystemExit(f"Requested columns not found in input: {', '.join(missing)}")
    return columns


def _display_labels(labels_json: str | None, columns: list[str]) -> list[str]:
    if not labels_json:
        return columns
    try:
        raw_labels = json.loads(labels_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"--labels-json is not valid JSON: {exc}") from exc
    if not isinstance(raw_labels, dict):
        raise SystemExit("--labels-json must be a JSON object.")
    return [str(raw_labels.get(column, column)) for column in columns]


def _sanitize_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    if not stem:
        raise SystemExit("--output-name must contain at least one filename-safe character.")
    return stem


def _geometry(labels: list[str], rows: list[list[str]], width_in: float, font_scale: float) -> tuple[int, list[int]]:
    if width_in <= 0:
        raise SystemExit("--width-in must be positive.")
    target_width = round(width_in * SVG_PX_PER_IN)
    header_font = _load_font("figure_axis_label", bold=True, scale=font_scale)
    body_font = _load_font("figure_tick", bold=False, scale=font_scale)
    desired_widths = []
    for index, label in enumerate(labels):
        values = [row[index] for row in rows]
        header_width = _text_width(label, header_font)
        body_width = max((_text_width(value, body_font) for value in values), default=0)
        desired_widths.append(max(MIN_COLUMN_WIDTH_PX, header_width, body_width) + 22)

    desired_total = sum(desired_widths)
    if desired_total >= target_width:
        width = desired_total
        col_widths = desired_widths
    else:
        extra = target_width - desired_total
        weights = [max(1, value) for value in desired_widths]
        total_weight = sum(weights)
        col_widths = [
            value + round(extra * (weight / total_weight))
            for value, weight in zip(desired_widths, weights, strict=True)
        ]
        width = sum(col_widths)
    return width, col_widths


def _table_height(row_count: int) -> int:
    return HEADER_HEIGHT_PX + row_count * ROW_HEIGHT_PX


def _build_svg(
    labels: list[str],
    rows: list[list[str]],
    geometry: tuple[int, list[int]],
    *,
    font_scale: float,
) -> str:
    width, col_widths = geometry
    height = _table_height(len(rows))
    x_positions = _x_positions(col_widths)
    header_px = _scaled_css_px("figure_axis_label", font_scale)
    body_px = _scaled_css_px("figure_tick", font_scale)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width / SVG_PX_PER_IN:.4f}in" '
        f'height="{height / SVG_PX_PER_IN:.4f}in" viewBox="0 0 {width} {height}" role="img">',
        "<style>",
        (
            "text { font-family: "
            f"{css_font_family()}; fill: {TEXT_PRIMARY}; dominant-baseline: middle; text-anchor: middle; }}"
        ),
        f".header {{ font-size: {header_px}px; font-weight: {css_font_weight('figure_axis_label')}; }}",
        f".body {{ font-size: {body_px}px; font-weight: {css_font_weight('figure_tick')}; }}",
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{SURFACE_BG}"/>',
        f'<rect x="0" y="0" width="{width}" height="{HEADER_HEIGHT_PX}" fill="{SURFACE_ALT_BG}"/>',
    ]

    for row_index in range(len(rows)):
        y = HEADER_HEIGHT_PX + row_index * ROW_HEIGHT_PX
        fill = SURFACE_ALT_BG if row_index % 2 else SURFACE_BG
        lines.append(f'<rect x="0" y="{y}" width="{width}" height="{ROW_HEIGHT_PX}" fill="{fill}"/>')

    lines.extend(_svg_grid_lines(width, height, x_positions, len(rows)))
    lines.extend(_svg_text_row(labels, x_positions, HEADER_HEIGHT_PX / 2, "header"))
    for row_index, row in enumerate(rows):
        y = HEADER_HEIGHT_PX + row_index * ROW_HEIGHT_PX + ROW_HEIGHT_PX / 2
        lines.extend(_svg_text_row(row, x_positions, y, "body"))

    lines.append("</svg>")
    return "\n".join(lines)


def _svg_grid_lines(width: int, height: int, x_positions: list[int], row_count: int) -> list[str]:
    lines = []
    for x in x_positions:
        lines.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" stroke="{BORDER_SOFT_COLOR}" stroke-width="1"/>')
    for y in [0, HEADER_HEIGHT_PX, height]:
        lines.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="{BORDER_COLOR}" stroke-width="1"/>')
    for row_index in range(1, row_count):
        y = HEADER_HEIGHT_PX + row_index * ROW_HEIGHT_PX
        lines.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="{BORDER_SOFT_COLOR}" stroke-width="1"/>')
    return lines


def _svg_text_row(values: list[str], x_positions: list[int], y: float, css_class: str) -> list[str]:
    lines = []
    for col_index, value in enumerate(values):
        x = x_positions[col_index] + (x_positions[col_index + 1] - x_positions[col_index]) / 2
        lines.append(f'<text class="{css_class}" x="{x}" y="{y}">{escape(value)}</text>')
    return lines


def _write_png(
    path: Path,
    labels: list[str],
    rows: list[list[str]],
    geometry: tuple[int, list[int]],
    *,
    dpi: int,
    font_scale: float,
) -> None:
    width_css, col_widths_css = geometry
    height_css = _table_height(len(rows))
    scale = dpi / SVG_PX_PER_IN
    width = round(width_css * scale)
    height = round(height_css * scale)
    col_widths = [round(col_width * scale) for col_width in col_widths_css]
    header_height = round(HEADER_HEIGHT_PX * scale)
    row_height = round(ROW_HEIGHT_PX * scale)

    image = Image.new("RGB", (width, height), _hex_to_rgb(SURFACE_BG))
    draw = ImageDraw.Draw(image)
    header_font = _load_font("figure_axis_label", bold=True, scale=scale * font_scale)
    body_font = _load_font("figure_tick", bold=False, scale=scale * font_scale)

    _draw_backgrounds(draw, width, header_height, row_height, len(rows))
    x_positions = _x_positions(col_widths)
    _draw_grid(draw, width, height, header_height, row_height, x_positions, len(rows), scale)
    _draw_centered_row(draw, labels, x_positions, header_height / 2, header_font)
    for row_index, row in enumerate(rows):
        y = header_height + row_index * row_height + row_height / 2
        _draw_centered_row(draw, row, x_positions, y, body_font)

    image.save(path, dpi=(dpi, dpi))


def _build_html(svg_text: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Publication Table Preview</title>
  <style>
    body {{
      background: {SURFACE_BG};
      color: {TEXT_PRIMARY};
      font-family: {css_font_family()};
      margin: 0;
      padding: 0;
    }}
  </style>
</head>
<body>
{svg_text}
</body>
</html>
"""


def _x_positions(col_widths: list[int]) -> list[int]:
    positions = [0]
    for width in col_widths:
        positions.append(positions[-1] + width)
    return positions


def _draw_backgrounds(draw: ImageDraw.ImageDraw, width: int, header_height: int, row_height: int, row_count: int) -> None:
    draw.rectangle((0, 0, width, header_height), fill=_hex_to_rgb(SURFACE_ALT_BG))
    for row_index in range(row_count):
        if row_index % 2:
            y0 = header_height + row_index * row_height
            draw.rectangle((0, y0, width, y0 + row_height), fill=_hex_to_rgb(SURFACE_ALT_BG))


def _draw_grid(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    header_height: int,
    row_height: int,
    x_positions: list[int],
    row_count: int,
    scale: float,
) -> None:
    border_width = max(1, round(scale))
    for x in x_positions:
        draw.line((x, 0, x, height), fill=_hex_to_rgb(BORDER_SOFT_COLOR), width=border_width)
    for y in (0, header_height, height - 1):
        draw.line((0, y, width, y), fill=_hex_to_rgb(BORDER_COLOR), width=border_width)
    for row_index in range(1, row_count):
        y = header_height + row_index * row_height
        draw.line((0, y, width, y), fill=_hex_to_rgb(BORDER_SOFT_COLOR), width=border_width)


def _draw_centered_row(
    draw: ImageDraw.ImageDraw,
    values: list[str],
    x_positions: list[int],
    center_y: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    fill = _hex_to_rgb(TEXT_PRIMARY)
    for col_index, value in enumerate(values):
        bbox = draw.textbbox((0, 0), value, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        left = x_positions[col_index]
        right = x_positions[col_index + 1]
        x = left + (right - left - text_width) / 2
        y = center_y - text_height / 2 - bbox[1]
        draw.text((x, y), value, font=font, fill=fill)


def _text_width(value: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    left, _top, right, _bottom = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), value, font=font)
    return right - left


def _load_font(role: str, *, bold: bool, scale: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(1, round(_role_px(role) * scale))
    font_root = Path("C:/Windows/Fonts")
    names = ("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        path = font_root / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default(size=size)


def _scaled_css_px(role: str, font_scale: float) -> int:
    return max(1, round(_role_px(role) * font_scale))


def _role_px(role: str) -> int:
    return int(css_font_size(role).rstrip("px"))


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


if __name__ == "__main__":
    raise SystemExit(main())

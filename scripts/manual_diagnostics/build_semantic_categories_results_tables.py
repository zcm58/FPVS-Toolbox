"""Build Great Tables summaries for the Semantic Categories manuscript results."""

from __future__ import annotations

import sys
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
from great_tables import GT
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Main_App.gui.style_tokens import (  # noqa: E402
    BORDER_COLOR,
    BORDER_SOFT_COLOR,
    SURFACE_ALT_BG,
    SURFACE_BG,
    TEXT_MUTED,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
)
from Main_App.gui.typography import css_font_family, css_font_size, css_font_weight  # noqa: E402

DEFAULT_OUTPUT = ROOT / ".codex-tmp" / "semantic_categories_results_summary.html"
HARMONIC_OUTPUT = ROOT / ".codex-tmp" / "semantic_categories_harmonics_table.html"
PUBLICATION_HARMONIC_HTML = ROOT / ".codex-tmp" / "semantic_categories_harmonics_publication_table.html"
PUBLICATION_HARMONIC_SVG = ROOT / ".codex-tmp" / "semantic_categories_harmonics_publication_table.svg"
PUBLICATION_HARMONIC_PNG = ROOT / ".codex-tmp" / "semantic_categories_harmonics_publication_table.png"
PUBLICATION_DPI = 600
SVG_PX_PER_IN = 96
PUBLICATION_COLUMN_WIDTHS_IN = (1.45, 1.15, 1.25)
PUBLICATION_HEADER_HEIGHT_PX = 34
PUBLICATION_ROW_HEIGHT_PX = 30


def harmonic_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"harmonic_hz": 1.2, "z": 1.81, "p_reported": "0.035"},
            {"harmonic_hz": 2.4, "z": 2.83, "p_reported": "0.002"},
            {"harmonic_hz": 3.6, "z": 11.16, "p_reported": "< 0.001"},
            {"harmonic_hz": 4.8, "z": 6.99, "p_reported": "< 0.001"},
            {"harmonic_hz": 7.2, "z": 10.56, "p_reported": "< 0.001"},
            {"harmonic_hz": 14.4, "z": 5.98, "p_reported": "< 0.001"},
            {"harmonic_hz": 16.8, "z": 1.87, "p_reported": "0.031"},
            {"harmonic_hz": 19.2, "z": 3.04, "p_reported": "0.001"},
            {"harmonic_hz": 27.6, "z": 2.02, "p_reported": "0.022"},
            {"harmonic_hz": 37.2, "z": 1.72, "p_reported": "0.042"},
        ]
    )


def roi_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "condition": "Semantic response",
                "roi": "Left OT",
                "mean_bca_uv": 0.440,
                "sd_uv": 0.270,
                "test": "t test",
                "statistic": "t(26) = 8.50",
                "p_reported": "< .001",
                "dz": 1.64,
                "note": "",
            },
            {
                "condition": "Semantic response",
                "roi": "Right OT",
                "mean_bca_uv": 0.667,
                "sd_uv": 0.333,
                "test": "t test",
                "statistic": "t(26) = 10.40",
                "p_reported": "< .001",
                "dz": 2.00,
                "note": "Largest semantic amplitude.",
            },
            {
                "condition": "Semantic response",
                "roi": "Central",
                "mean_bca_uv": 0.240,
                "sd_uv": 0.180,
                "test": "t test",
                "statistic": "t(26) = 6.77",
                "p_reported": "< .001",
                "dz": 1.30,
                "note": "",
            },
            {
                "condition": "Color response",
                "roi": "Left OT",
                "mean_bca_uv": 0.410,
                "sd_uv": 0.330,
                "test": "t test",
                "statistic": "t(26) = 6.41",
                "p_reported": "< .001",
                "dz": 1.23,
                "note": "",
            },
            {
                "condition": "Color response",
                "roi": "Right OT",
                "mean_bca_uv": 0.442,
                "sd_uv": 0.524,
                "test": "Wilcoxon",
                "statistic": "",
                "p_reported": "< .001",
                "dz": None,
                "note": "Selected after Shapiro-Wilk normality check failed.",
            },
            {
                "condition": "Color response",
                "roi": "Central",
                "mean_bca_uv": 0.160,
                "sd_uv": 0.180,
                "test": "t test",
                "statistic": "t(26) = 4.55",
                "p_reported": "< .001",
                "dz": 0.88,
                "note": "",
            },
        ]
    )


def contrast_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "condition": "Semantic response",
                "contrast": "Right OT - Left OT",
                "mean_difference_uv": 0.228,
                "test": "t test",
                "statistic": "t(26) = 4.04",
                "p_reported": ".001",
                "dz": 0.78,
                "interpretation": "Right OT larger than Left OT.",
            },
            {
                "condition": "Color response",
                "contrast": "Right OT - Left OT",
                "mean_difference_uv": 0.034,
                "test": "Wilcoxon",
                "statistic": "",
                "p_reported": ".470",
                "dz": None,
                "interpretation": "Not significant.",
            },
        ]
    )


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))


def _windows_font_path(*names: str) -> Path | None:
    font_root = Path("C:/Windows/Fonts")
    for name in names:
        path = font_root / name
        if path.exists():
            return path
    return None


def _load_pillow_font(*, css_px: int, bold: bool, scale: float) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(1, round(css_px * scale))
    if bold:
        font_path = _windows_font_path("seguisb.ttf", "segoeuib.ttf", "arialbd.ttf")
    else:
        font_path = _windows_font_path("segoeui.ttf", "arial.ttf")
    if font_path is None:
        return ImageFont.load_default(size=size)
    return ImageFont.truetype(str(font_path), size=size)


def _publication_table_geometry() -> tuple[int, int, list[int]]:
    col_widths = [round(width * SVG_PX_PER_IN) for width in PUBLICATION_COLUMN_WIDTHS_IN]
    width = sum(col_widths)
    height = PUBLICATION_HEADER_HEIGHT_PX + len(harmonic_rows()) * PUBLICATION_ROW_HEIGHT_PX
    return width, height, col_widths


def _toolbox_table(table: GT, *, width: str = "4.25in") -> GT:
    return (
        table.tab_options(
            container_width=width,
            container_padding_x="0",
            container_padding_y="8px",
            table_width="100%",
            table_font_names=["Segoe UI", "Arial", "sans-serif"],
            table_font_size=css_font_size("figure_tick"),
            table_font_color=TEXT_PRIMARY,
            table_background_color=SURFACE_BG,
            table_border_top_style="solid",
            table_border_top_width="1px",
            table_border_top_color=BORDER_COLOR,
            table_border_bottom_style="solid",
            table_border_bottom_width="1px",
            table_border_bottom_color=BORDER_COLOR,
            heading_align="left",
            heading_title_font_size=css_font_size("figure_title"),
            heading_title_font_weight=css_font_weight("figure_title"),
            heading_subtitle_font_size=css_font_size("figure_note"),
            heading_subtitle_font_weight=css_font_weight("figure_note"),
            heading_padding="4px",
            heading_border_bottom_style="solid",
            heading_border_bottom_width="1px",
            heading_border_bottom_color=BORDER_SOFT_COLOR,
            column_labels_background_color=SURFACE_ALT_BG,
            column_labels_font_size=css_font_size("figure_axis_label"),
            column_labels_font_weight=css_font_weight("figure_axis_label"),
            column_labels_padding="7px",
            column_labels_border_top_style="none",
            column_labels_border_bottom_style="solid",
            column_labels_border_bottom_width="1px",
            column_labels_border_bottom_color=BORDER_COLOR,
            data_row_padding="6px",
            data_row_padding_horizontal="10px",
            table_body_hlines_style="solid",
            table_body_hlines_width="1px",
            table_body_hlines_color=BORDER_SOFT_COLOR,
            source_notes_font_size=css_font_size("figure_note"),
            source_notes_padding="8px",
            source_notes_border_bottom_style="none",
            row_striping_background_color=SURFACE_ALT_BG,
        )
        .opt_css(
            css=f"""
            .gt_heading .gt_subtitle {{
                color: {TEXT_SECONDARY};
            }}
            .gt_sourcenote {{
                color: {TEXT_MUTED};
            }}
            """
        )
        .opt_row_striping()
    )


def harmonic_gt_table(*, include_title: bool = True, include_note: bool = True) -> GT:
    table = (
        GT(harmonic_rows())
        .cols_label(
            harmonic_hz="Harmonic (Hz)",
            z="Z score",
            p_reported="p-value",
        )
        .cols_align(align="center", columns=["harmonic_hz", "z", "p_reported"])
        .cols_width(
            harmonic_hz="1.45in",
            z="1.15in",
            p_reported="1.25in",
        )
        .fmt_number(columns=["harmonic_hz"], decimals=1)
        .fmt_number(columns=["z"], decimals=2)
    )
    if include_title:
        table = table.tab_header(
            title="Group-level significant oddball harmonics",
            subtitle="Grand-average harmonic selection used for summed BCA ROI responses.",
        )
    if include_note:
        table = table.tab_source_note(
            "p-values are Holm-corrected; all listed harmonics were included in summed BCA."
        )
    return _toolbox_table(table)


def harmonic_table() -> str:
    return harmonic_gt_table().as_raw_html()


def publication_harmonic_table() -> str:
    return harmonic_gt_table(include_title=False, include_note=False).as_raw_html()


def roi_table() -> str:
    table = (
        GT(roi_rows())
        .tab_header(
            title="Summed BCA response by condition and ROI",
            subtitle="BCA summed across the ten significant oddball harmonics.",
        )
        .tab_stub(rowname_col="roi", groupname_col="condition")
        .cols_label(
            mean_bca_uv="Mean BCA (uV)",
            sd_uv="SD (uV)",
            test="Selected test",
            statistic="Statistic",
            p_reported="p",
            dz="dz",
            note="Note",
        )
        .tab_spanner(label="BCA summary", columns=["mean_bca_uv", "sd_uv"])
        .tab_spanner(label="Inference", columns=["test", "statistic", "p_reported", "dz"])
        .fmt_number(columns=["mean_bca_uv", "sd_uv"], decimals=3)
        .fmt_number(columns=["dz"], decimals=2)
        .sub_missing(missing_text="")
        .tab_source_note("All ROI one-sample tests are reported after Holm correction.")
    )
    return _toolbox_table(table, width="6.5in").as_raw_html()


def contrast_table() -> str:
    table = (
        GT(contrast_rows())
        .tab_header(
            title="Right OT lateralization contrasts",
            subtitle="Within-condition Right OT minus Left OT comparisons.",
        )
        .tab_stub(rowname_col="contrast", groupname_col="condition")
        .cols_label(
            mean_difference_uv="Mean difference (uV)",
            test="Selected test",
            statistic="Statistic",
            p_reported="p",
            dz="dz",
            interpretation="Interpretation",
        )
        .fmt_number(columns=["mean_difference_uv"], decimals=3)
        .fmt_number(columns=["dz"], decimals=2)
        .sub_missing(missing_text="")
        .tab_source_note("The semantic condition shows Right OT lateralization; the color condition does not.")
    )
    return _toolbox_table(table, width="6.5in").as_raw_html()


def build_html(*, title: str, lede: str, tables: list[str]) -> str:
    rendered_tables = "\n".join(tables)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{
      background: {SURFACE_BG};
      color: {TEXT_PRIMARY};
      font-family: {css_font_family()};
      line-height: 1.45;
      margin: 32px auto;
      max-width: 1180px;
      padding: 0 24px 48px;
    }}
    h1 {{
      font-size: {css_font_size("figure_title")};
      font-weight: {css_font_weight("figure_title")};
      margin-bottom: 8px;
    }}
    .lede {{
      color: {TEXT_SECONDARY};
      font-size: {css_font_size("figure_tick")};
      margin-bottom: 24px;
      max-width: 920px;
    }}
    .gt_table {{
      margin-bottom: 28px;
    }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="lede">
    {lede}
  </p>
  {rendered_tables}
</body>
</html>
"""


def build_table_only_html(table: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Semantic Categories Harmonic Publication Table</title>
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
  {table}
</body>
</html>
"""


def build_publication_harmonic_svg() -> str:
    width, height, col_widths = _publication_table_geometry()
    headers = ["Harmonic (Hz)", "Z score", "p-value"]
    rows = [
        [f"{row.harmonic_hz:.1f}", f"{row.z:.2f}", row.p_reported]
        for row in harmonic_rows().itertuples(index=False)
    ]
    x_positions = [0]
    for col_width in col_widths:
        x_positions.append(x_positions[-1] + col_width)

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width / SVG_PX_PER_IN:.4f}in" '
        f'height="{height / SVG_PX_PER_IN:.4f}in" viewBox="0 0 {width} {height}" role="img">',
        "<style>",
        (
            "text { font-family: "
            f"{css_font_family()}; fill: {TEXT_PRIMARY}; dominant-baseline: middle; text-anchor: middle; }}"
        ),
        f".header {{ font-size: {css_font_size('figure_axis_label')}; font-weight: {css_font_weight('figure_axis_label')}; }}",
        f".body {{ font-size: {css_font_size('figure_tick')}; font-weight: {css_font_weight('figure_tick')}; }}",
        "</style>",
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="{SURFACE_BG}"/>',
        f'<rect x="0" y="0" width="{width}" height="{PUBLICATION_HEADER_HEIGHT_PX}" fill="{SURFACE_ALT_BG}"/>',
    ]

    for row_index in range(len(rows)):
        y = PUBLICATION_HEADER_HEIGHT_PX + row_index * PUBLICATION_ROW_HEIGHT_PX
        fill = SURFACE_ALT_BG if row_index % 2 else SURFACE_BG
        lines.append(f'<rect x="0" y="{y}" width="{width}" height="{PUBLICATION_ROW_HEIGHT_PX}" fill="{fill}"/>')

    for x in x_positions:
        lines.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" stroke="{BORDER_SOFT_COLOR}" stroke-width="1"/>')
    for y in [0, PUBLICATION_HEADER_HEIGHT_PX, height]:
        lines.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="{BORDER_COLOR}" stroke-width="1"/>')
    for row_index in range(1, len(rows)):
        y = PUBLICATION_HEADER_HEIGHT_PX + row_index * PUBLICATION_ROW_HEIGHT_PX
        lines.append(f'<line x1="0" y1="{y}" x2="{width}" y2="{y}" stroke="{BORDER_SOFT_COLOR}" stroke-width="1"/>')

    header_y = PUBLICATION_HEADER_HEIGHT_PX / 2
    for col_index, header in enumerate(headers):
        x = x_positions[col_index] + col_widths[col_index] / 2
        lines.append(f'<text class="header" x="{x}" y="{header_y}">{escape(header)}</text>')

    for row_index, row in enumerate(rows):
        y = PUBLICATION_HEADER_HEIGHT_PX + row_index * PUBLICATION_ROW_HEIGHT_PX + PUBLICATION_ROW_HEIGHT_PX / 2
        for col_index, value in enumerate(row):
            x = x_positions[col_index] + col_widths[col_index] / 2
            lines.append(f'<text class="body" x="{x}" y="{y}">{escape(str(value))}</text>')

    lines.append("</svg>")
    return "\n".join(lines)


def write_publication_harmonic_png(path: Path) -> None:
    width_css, height_css, col_widths_css = _publication_table_geometry()
    scale = PUBLICATION_DPI / SVG_PX_PER_IN
    width = round(width_css * scale)
    height = round(height_css * scale)
    col_widths = [round(col_width * scale) for col_width in col_widths_css]
    header_height = round(PUBLICATION_HEADER_HEIGHT_PX * scale)
    row_height = round(PUBLICATION_ROW_HEIGHT_PX * scale)

    image = Image.new("RGB", (width, height), _hex_to_rgb(SURFACE_BG))
    draw = ImageDraw.Draw(image)
    header_font = _load_pillow_font(
        css_px=int(css_font_size("figure_axis_label").rstrip("px")),
        bold=True,
        scale=scale,
    )
    body_font = _load_pillow_font(
        css_px=int(css_font_size("figure_tick").rstrip("px")),
        bold=False,
        scale=scale,
    )

    border = _hex_to_rgb(BORDER_COLOR)
    soft_border = _hex_to_rgb(BORDER_SOFT_COLOR)
    alt_bg = _hex_to_rgb(SURFACE_ALT_BG)
    text_color = _hex_to_rgb(TEXT_PRIMARY)

    draw.rectangle((0, 0, width, header_height), fill=alt_bg)
    rows = [
        [f"{row.harmonic_hz:.1f}", f"{row.z:.2f}", row.p_reported]
        for row in harmonic_rows().itertuples(index=False)
    ]
    for row_index in range(len(rows)):
        if row_index % 2:
            y0 = header_height + row_index * row_height
            draw.rectangle((0, y0, width, y0 + row_height), fill=alt_bg)

    x_positions = [0]
    for col_width in col_widths:
        x_positions.append(x_positions[-1] + col_width)
    for x in x_positions:
        draw.line((x, 0, x, height), fill=soft_border, width=max(1, round(scale)))
    for y in (0, header_height, height - 1):
        draw.line((0, y, width, y), fill=border, width=max(1, round(scale)))
    for row_index in range(1, len(rows)):
        y = header_height + row_index * row_height
        draw.line((0, y, width, y), fill=soft_border, width=max(1, round(scale)))

    headers = ["Harmonic (Hz)", "Z score", "p-value"]
    _draw_centered_row(draw, headers, x_positions, header_height / 2, header_font, text_color)
    for row_index, row in enumerate(rows):
        y = header_height + row_index * row_height + row_height / 2
        _draw_centered_row(draw, row, x_positions, y, body_font, text_color)

    image.save(path, dpi=(PUBLICATION_DPI, PUBLICATION_DPI))


def _draw_centered_row(
    draw: ImageDraw.ImageDraw,
    values: list[str],
    x_positions: list[int],
    center_y: float,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> None:
    for col_index, value in enumerate(values):
        text = str(value)
        left = x_positions[col_index]
        right = x_positions[col_index + 1]
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = left + (right - left - text_width) / 2
        y = center_y - text_height / 2 - bbox[1]
        draw.text((x, y), text, font=font, fill=fill)


def main() -> None:
    DEFAULT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    summary_html = build_html(
        title="Semantic Categories Results Summary",
        lede=(
            "Great Tables summary generated from the manuscript results text supplied by the user. "
            "BCA values are in microvolts and are summed across the significant oddball harmonics."
        ),
        tables=[harmonic_table(), roi_table(), contrast_table()],
    )
    harmonic_html = build_html(
        title="Semantic Categories Harmonic Summary",
        lede=(
            "Publication-style Great Tables version of the group-level significant oddball harmonics table, "
            "using FPVS Toolbox figure typography roles."
        ),
        tables=[harmonic_table()],
    )
    DEFAULT_OUTPUT.write_text(summary_html, encoding="utf-8")
    HARMONIC_OUTPUT.write_text(harmonic_html, encoding="utf-8")
    PUBLICATION_HARMONIC_HTML.write_text(
        build_table_only_html(publication_harmonic_table()),
        encoding="utf-8",
    )
    PUBLICATION_HARMONIC_SVG.write_text(build_publication_harmonic_svg(), encoding="utf-8")
    write_publication_harmonic_png(PUBLICATION_HARMONIC_PNG)
    print(DEFAULT_OUTPUT)
    print(HARMONIC_OUTPUT)
    print(PUBLICATION_HARMONIC_HTML)
    print(PUBLICATION_HARMONIC_SVG)
    print(PUBLICATION_HARMONIC_PNG)


if __name__ == "__main__":
    main()

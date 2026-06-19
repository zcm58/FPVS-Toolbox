from __future__ import annotations

from pathlib import Path
import re

import pytest
from matplotlib.figure import Figure
from PIL import Image

from Main_App.gui.typography import APP_FONT_FAMILY, FONT_ROLES
from Tools.Sequence_Figure.renderer import (
    SequenceFigureSpec,
    _IMAGE_SIZE_UNITS,
    _ODDBALL_FRAME_LINE_WIDTH_PT,
    _RATE_LABEL_FONT_SIZE_PT,
    _TIMING_LINE_WIDTH_PT,
    _rate_label_kwargs,
    render_sequence_figure,
)


def _make_image(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _image_paths(tmp_path: Path, size: tuple[int, int] = (1200, 1200)) -> tuple[Path, ...]:
    colors = [
        (180, 50, 50),
        (50, 150, 70),
        (60, 90, 180),
        (210, 170, 40),
        (150, 70, 170),
    ]
    return tuple(
        _make_image(tmp_path / f"slot_{index}.png", size, color)
        for index, color in enumerate(colors, start=1)
    )


def test_render_sequence_figure_exports_png_pdf_and_svg(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            basename="color-condition-sequence",
            png_dpi=72,
            figure_size_in=(4.0, 2.25),
        )
    )

    assert result.png_path.exists()
    assert result.pdf_path.exists()
    assert result.svg_path is not None
    assert result.svg_path.exists()

    with Image.open(result.png_path) as image:
        assert image.size == (288, 162)


def test_render_sequence_figure_uses_requested_dpi_for_all_export_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_calls: list[tuple[str, int | None]] = []

    def savefig_spy(
        _figure: Figure,
        path: Path,
        *_args: object,
        **kwargs: object,
    ) -> None:
        save_calls.append((Path(path).suffix, kwargs.get("dpi")))
        Path(path).write_bytes(b"")

    monkeypatch.setattr(Figure, "savefig", savefig_spy)

    render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            basename="dpi-all-formats",
            png_dpi=600,
        )
    )

    assert save_calls == [(".png", 600), (".pdf", 600), (".svg", 600)]


def test_render_sequence_figure_warns_for_low_resolution_sources(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path, size=(64, 64)),
            output_dir=tmp_path,
            basename="low-res",
            png_dpi=600,
        )
    )

    assert len(result.warnings) == 5
    assert all("recommended" in warning for warning in result.warnings)


def test_render_sequence_figure_accepts_1024px_sources_without_warning(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path, size=(1024, 1024)),
            output_dir=tmp_path,
            basename="acceptable-source-size",
            png_dpi=600,
        )
    )

    assert result.warnings == ()


def test_render_sequence_figure_svg_uses_segmented_low_state_lines(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            basename="segmented-lines",
            png_dpi=72,
            figure_size_in=(4.0, 2.25),
        )
    )

    svg_text = result.svg_path.read_text(encoding="utf-8") if result.svg_path else ""
    base_line_paths = _line_paths(svg_text, "#202020")
    oddball_line_paths = _line_paths(svg_text, "#ff0000")

    assert len(base_line_paths) == 21
    assert len(oddball_line_paths) == 5
    assert _horizontal_y_counts(oddball_line_paths) == [1, 2]


def test_render_sequence_figure_rate_labels_do_not_overlap_timing_lines(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            basename="label-spacing",
            png_dpi=72,
            figure_size_in=(4.0, 2.25),
        )
    )

    svg_text = result.svg_path.read_text(encoding="utf-8") if result.svg_path else ""
    base_lines = _line_coordinates(svg_text, "#202020")
    oddball_lines = _line_coordinates(svg_text, "#ff0000")
    base_line_max_x = max(max(xs) for xs, _ys in base_lines)
    oddball_line_max_x = max(max(xs) for xs, _ys in oddball_lines)
    base_label_x, base_label_y = _label_anchor(svg_text, "F = 6 Hz")
    oddball_label_x, oddball_label_y = _label_anchor(svg_text, "f = 1.2 Hz")

    assert base_label_x > base_line_max_x
    assert oddball_label_x > oddball_line_max_x
    assert base_label_x == pytest.approx(oddball_label_x)
    assert _is_within_final_peak(base_lines, base_label_y)
    assert _is_within_final_peak(oddball_lines, oddball_label_y)


def test_render_sequence_figure_oddball_rate_uses_ppt_reference_red(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            basename="oddball-red",
            png_dpi=72,
            figure_size_in=(4.0, 2.25),
        )
    )

    svg_text = result.svg_path.read_text(encoding="utf-8").lower() if result.svg_path else ""

    assert len(_line_paths(svg_text, "#ff0000")) == 5
    assert re.search(r"<!--\s*f = 1\.2 hz\s*-->.*?fill: #ff0000", svg_text, re.S)


def test_rate_label_font_uses_toolbox_figure_title_role() -> None:
    kwargs = _rate_label_kwargs("#202020")
    role = FONT_ROLES["figure_title"]
    axis_role = FONT_ROLES["figure_axis_label"]

    assert role.point_size > axis_role.point_size
    assert kwargs["fontsize"] == _RATE_LABEL_FONT_SIZE_PT
    assert kwargs["fontsize"] > role.point_size
    assert kwargs["fontweight"] == role.css_weight
    assert kwargs["fontfamily"] == APP_FONT_FAMILY


def test_render_sequence_figure_uses_publication_schematic_sizing() -> None:
    assert _IMAGE_SIZE_UNITS == pytest.approx(2.28)
    assert _TIMING_LINE_WIDTH_PT == pytest.approx(2.6)
    assert _ODDBALL_FRAME_LINE_WIDTH_PT == pytest.approx(2.4)
    assert _RATE_LABEL_FONT_SIZE_PT == 16


def test_render_sequence_figure_requires_five_images(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly 5"):
        render_sequence_figure(
            SequenceFigureSpec(
                image_paths=_image_paths(tmp_path)[:4],
                output_dir=tmp_path,
            )
        )


def test_render_sequence_figure_rejects_missing_output_folder(tmp_path: Path) -> None:
    missing_output = tmp_path / "missing"

    with pytest.raises(ValueError, match="existing output folder"):
        render_sequence_figure(
            SequenceFigureSpec(
                image_paths=_image_paths(tmp_path),
                output_dir=missing_output,
            )
        )

    assert not missing_output.exists()


def _line_paths(svg_text: str, color: str) -> list[str]:
    return re.findall(
        rf'<path d="[^"]+"[^>]*stroke: {re.escape(color)}[^>]*>',
        svg_text,
        re.S | re.IGNORECASE,
    )


def _horizontal_y_counts(paths: list[str]) -> list[int]:
    counts: dict[float, int] = {}
    for path in paths:
        d_match = re.search(r'<path d="([^"]+)"', path)
        assert d_match is not None
        values = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", d_match.group(1))]
        xs = values[0::2]
        ys = values[1::2]
        if len(set(round(y, 6) for y in ys)) == 1 and len(set(round(x, 6) for x in xs)) > 1:
            y = round(ys[0], 6)
            counts[y] = counts.get(y, 0) + 1
    return sorted(counts.values())


def _line_coordinates(svg_text: str, color: str) -> list[tuple[list[float], list[float]]]:
    lines: list[tuple[list[float], list[float]]] = []
    for path_match in re.finditer(
        rf'<path d="([^"]+)"[^>]*stroke: {re.escape(color)}[^>]*>',
        svg_text,
        re.S | re.IGNORECASE,
    ):
        values = [float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", path_match.group(1))]
        xs = values[0::2]
        ys = values[1::2]
        lines.append((xs, ys))
    return lines


def _is_within_final_peak(lines: list[tuple[list[float], list[float]]], label_y: float) -> bool:
    vertical_lines = [
        (xs[0], min(ys), max(ys))
        for xs, ys in lines
        if len(set(round(x, 6) for x in xs)) == 1 and len(set(round(y, 6) for y in ys)) > 1
    ]
    assert vertical_lines
    _x, top_y, bottom_y = max(vertical_lines, key=lambda item: item[0])
    return top_y < label_y < bottom_y


def _label_anchor(svg_text: str, label: str) -> tuple[float, float]:
    pattern = rf"<!--\s*{re.escape(label)}\s*-->.*?translate\(([0-9.]+)\s+([0-9.]+)\)"
    match = re.search(pattern, svg_text, re.S)
    assert match is not None
    return float(match.group(1)), float(match.group(2))

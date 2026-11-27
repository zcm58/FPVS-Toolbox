from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
from threading import Barrier
from typing import IO, Any

import pytest
from matplotlib.figure import Figure
from PIL import Image

from Main_App.exports.figure_style import FIGURE_FONT_FAMILY, FIGURE_TEXT_SIZE_PT, figure_text_kwargs
from Tools.Sequence_Figure.renderer import (
    DEFAULT_CONDITION_COUNT,
    MAX_CONDITION_LABEL_LENGTH,
    SequenceFigureSpec,
    _IMAGE_SIZE_UNITS,
    _ODDBALL_FRAME_LINE_WIDTH_PT,
    _RATE_LABEL_FONT_SIZE_PT,
    _TIMING_LINE_WIDTH_PT,
    _build_figure,
    _load_slot_images,
    _rate_label_kwargs,
    render_sequence_figure,
)


def _make_image(path: Path, size: tuple[int, int], color: tuple[int, int, int]) -> Path:
    Image.new("RGB", size, color).save(path)
    return path


def _image_paths(tmp_path: Path, size: tuple[int, int] = (1200, 1200)) -> tuple[Path, ...]:
    tmp_path.mkdir(parents=True, exist_ok=True)
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


def test_export_keeps_source_images_and_existing_output_sets(tmp_path: Path) -> None:
    paths = _image_paths(tmp_path, size=(40, 40))
    source = paths[0]
    original = source.read_bytes()
    existing = tmp_path / f"{source.stem} (2).pdf"
    existing.write_bytes(b"previous PDF")

    result = render_sequence_figure(SequenceFigureSpec(
        image_paths=paths, output_dir=tmp_path, basename=source.stem, png_dpi=36,
    ))

    assert source.read_bytes() == original
    assert existing.read_bytes() == b"previous PDF"
    assert {path.stem for path in result.output_paths} == {f"{source.stem} (3)"}
    assert all(path.is_file() for path in result.output_paths)


def test_windows_device_name_produces_portable_output_files(tmp_path: Path) -> None:
    paths = _image_paths(tmp_path, size=(40, 40))
    result = render_sequence_figure(SequenceFigureSpec(
        image_paths=paths, output_dir=tmp_path, basename="nul.study", png_dpi=36,
        export_svg=False,
    ))
    assert {path.name for path in result.output_paths} == {"_nul.study.png", "_nul.study.pdf"}
    assert all(path.stat().st_size > 0 for path in result.output_paths)


def test_simultaneous_exports_reserve_separate_complete_sets(tmp_path: Path, monkeypatch) -> None:
    from Tools.Sequence_Figure import renderer

    rendezvous = Barrier(2)
    open_path = Path.open

    def competing_open(path, mode="r", *args, **kwargs):
        if path.name == "shared.png" and mode == "xb":
            rendezvous.wait(timeout=5)
        return open_path(path, mode, *args, **kwargs)

    def save_marker(_figure, stream, *, format, **_options):
        assert all(Path(stream.name).with_suffix(suffix).exists() for suffix in (".png", ".pdf", ".svg"))
        stream.write(format if format == "svg" else format.encode())

    spec = SequenceFigureSpec(
        image_paths=_image_paths(tmp_path / "stimuli", size=(8, 8)), output_dir=tmp_path, basename="shared",
    )
    monkeypatch.setattr(renderer, "_build_figure", lambda *_args: Figure())
    monkeypatch.setattr(Figure, "savefig", save_marker)
    monkeypatch.setattr(Path, "open", competing_open)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(render_sequence_figure, (spec, spec)))

    assert {result.png_path.stem for result in results} == {"shared", "shared (2)"}
    for result in results:
        for path in result.output_paths:
            assert path.stem == result.png_path.stem
            assert path.read_text() == path.suffix[1:]


def test_late_pdf_collision_releases_only_own_reservations(tmp_path: Path, monkeypatch) -> None:
    spec = SequenceFigureSpec(
        image_paths=_image_paths(tmp_path / "stimuli", size=(8, 8)),
        output_dir=tmp_path, basename="shared", png_dpi=36,
    )
    open_path = Path.open
    competing_pdf = tmp_path / "shared.pdf"

    def competing_open(path, mode="r", *args, **kwargs):
        if path == competing_pdf and mode == "xb":
            with open_path(path, "xb") as stream:
                stream.write(b"another writer")
        return open_path(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", competing_open)
    result = render_sequence_figure(spec)
    assert competing_pdf.read_bytes() == b"another writer"
    assert not (tmp_path / "shared.png").exists()
    assert not (tmp_path / "shared.svg").exists()
    assert {path.stem for path in result.output_paths} == {"shared (2)"}


def test_failed_export_removes_incomplete_formats(tmp_path: Path, monkeypatch) -> None:
    paths = _image_paths(tmp_path / "images", size=(40, 40))
    original_save = Figure.savefig

    def fail_second_format(figure, destination, **kwargs):
        if kwargs["format"] == "pdf":
            raise OSError("PDF output unavailable")
        original_save(figure, destination, **kwargs)

    monkeypatch.setattr(Figure, "savefig", fail_second_format)
    with pytest.raises(OSError, match="PDF output unavailable"):
        render_sequence_figure(SequenceFigureSpec(
            image_paths=paths, output_dir=tmp_path, basename="figure", png_dpi=36,
        ))
    assert list(tmp_path.glob("figure.*")) == []


def test_render_sequence_figure_uses_requested_dpi_for_all_export_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_calls: list[tuple[str, int | None]] = []

    def savefig_spy(
        _figure: Figure,
        stream: IO[Any],
        *_args: object,
        **kwargs: object,
    ) -> None:
        save_calls.append((Path(stream.name).suffix, kwargs.get("dpi")))

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


def test_render_sequence_figure_applies_transparency_to_pdf_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save_calls: list[tuple[str, object, object]] = []

    def savefig_spy(
        _figure: Figure,
        stream: IO[Any],
        *_args: object,
        **kwargs: object,
    ) -> None:
        save_calls.append(
            (Path(stream.name).suffix, kwargs.get("facecolor"), kwargs.get("transparent"))
        )

    monkeypatch.setattr(Figure, "savefig", savefig_spy)

    render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            transparent_pdf=True,
        )
    )

    assert save_calls == [
        (".png", "white", False),
        (".pdf", "none", True),
        (".svg", "white", False),
    ]


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
    base_line_paths = _line_paths(svg_text, "#3e6b89", stroke_width="2.6")
    oddball_line_paths = _line_paths(svg_text, "#ff0000", stroke_width="2.6")

    assert len(base_line_paths) == 41
    assert len(oddball_line_paths) == 9
    assert _horizontal_y_counts(oddball_line_paths) == [2, 3]


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
    base_lines = _line_coordinates(svg_text, "#3e6b89")
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

    assert len(_line_paths(svg_text, "#ff0000", stroke_width="2.6")) == 9
    assert re.search(r"<!--\s*f = 1\.2 hz\s*-->.*?fill: #ff0000", svg_text, re.S)


def test_rate_label_font_uses_publication_figure_annotation_role() -> None:
    kwargs = _rate_label_kwargs("#202020")
    role_kwargs = figure_text_kwargs("annotation")

    assert kwargs["fontsize"] == _RATE_LABEL_FONT_SIZE_PT
    assert kwargs["fontsize"] > FIGURE_TEXT_SIZE_PT
    assert kwargs["fontweight"] == role_kwargs["fontweight"]
    assert kwargs["fontfamily"] == FIGURE_FONT_FAMILY


def test_render_sequence_figure_uses_publication_schematic_sizing() -> None:
    assert _IMAGE_SIZE_UNITS == pytest.approx(0.92)
    assert _TIMING_LINE_WIDTH_PT == pytest.approx(2.6)
    assert _ODDBALL_FRAME_LINE_WIDTH_PT == pytest.approx(2.4)
    assert _RATE_LABEL_FONT_SIZE_PT == 16


def test_render_sequence_figure_accepts_default_three_condition_grid(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=tuple(
                _image_paths(tmp_path / f"condition_{condition}")
                for condition in range(1, DEFAULT_CONDITION_COUNT + 1)
            ),
            output_dir=tmp_path,
            basename="three-conditions",
            png_dpi=72,
            figure_size_in=(4.0, 2.25),
        )
    )

    assert result.png_path.exists()


def test_render_sequence_figure_uses_custom_condition_labels(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=tuple(
                _image_paths(tmp_path / f"condition_{condition}") for condition in range(1, 4)
            ),
            output_dir=tmp_path,
            basename="custom-labels",
            condition_labels=("Faces", "Objects", "Scenes"),
            png_dpi=72,
        )
    )

    svg_text = result.svg_path.read_text(encoding="utf-8") if result.svg_path else ""

    assert all(f"<!-- {label} -->" in svg_text for label in ("Faces", "Objects", "Scenes"))


def test_render_sequence_figure_grayscale_style_does_not_rely_on_color(tmp_path: Path) -> None:
    result = render_sequence_figure(
        SequenceFigureSpec(
            image_paths=_image_paths(tmp_path),
            output_dir=tmp_path,
            basename="grayscale-safe",
            grayscale_safe=True,
            png_dpi=72,
            figure_size_in=(4.0, 2.25),
        )
    )

    svg_text = result.svg_path.read_text(encoding="utf-8").lower() if result.svg_path else ""
    base_paths = _line_paths(svg_text, "#202020", stroke_width="2.6")
    oddball_paths = _line_paths(svg_text, "#666666", stroke_width="2.6")

    assert base_paths
    assert oddball_paths
    assert all("stroke-dasharray" not in path for path in base_paths)
    assert all("stroke-dasharray" in path for path in oddball_paths)


def test_render_sequence_figure_rejects_unsafe_condition_labels(tmp_path: Path) -> None:
    image_paths = _image_paths(tmp_path)

    with pytest.raises(ValueError, match="one condition label"):
        render_sequence_figure(
            SequenceFigureSpec(
                image_paths=image_paths,
                output_dir=tmp_path,
                condition_labels=("First", "Second"),
            )
        )

    with pytest.raises(ValueError, match="characters or fewer"):
        render_sequence_figure(
            SequenceFigureSpec(
                image_paths=image_paths,
                output_dir=tmp_path,
                condition_labels=("X" * (MAX_CONDITION_LABEL_LENGTH + 1),),
            )
        )


def test_render_sequence_figure_rejects_more_than_four_conditions(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at most 4 conditions"):
        render_sequence_figure(
            SequenceFigureSpec(
                image_paths=tuple(
                    _image_paths(tmp_path / f"condition_{condition}") for condition in range(1, 6)
                ),
                output_dir=tmp_path,
            )
        )


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_each_supported_condition_count_repeats_five_images_twice(tmp_path, count) -> None:
    paths = _image_paths(tmp_path, size=(64, 64))
    spec = SequenceFigureSpec(image_paths=(paths,) * count, output_dir=tmp_path)
    images, _warnings = _load_slot_images(spec)
    figure = _build_figure(spec, images)
    try:
        assert len(figure.axes[0].images) == count * 10
        labels = [text.get_text() for text in figure.axes[0].texts]
        assert all(f"Condition {index}" in labels for index in range(1, count + 1))
    finally:
        from matplotlib import pyplot as plt
        plt.close(figure)


def test_maximum_length_condition_labels_stay_inside_default_figure(tmp_path) -> None:
    paths = _image_paths(tmp_path, size=(64, 64))
    spec = SequenceFigureSpec(
        image_paths=(paths,) * 4,
        output_dir=tmp_path,
        condition_labels=("W" * MAX_CONDITION_LABEL_LENGTH,) * 4,
    )
    images, _warnings = _load_slot_images(spec)
    figure = _build_figure(spec, images)
    try:
        figure.canvas.draw()
        labels = figure.axes[0].texts[:4]
        assert len(labels) == 4
        for label in labels:
            bounds = label.get_window_extent(figure.canvas.get_renderer())
            assert bounds.x0 >= 0
            assert bounds.x1 <= figure.bbox.width
            assert bounds.y0 >= 0
            assert bounds.y1 <= figure.bbox.height
    finally:
        from matplotlib import pyplot as plt
        plt.close(figure)


@pytest.mark.parametrize("labels", [(" ",), ("\t",)])
def test_blank_condition_labels_are_rejected(tmp_path, labels) -> None:
    with pytest.raises(ValueError, match="cannot be blank"):
        render_sequence_figure(SequenceFigureSpec(
            image_paths=_image_paths(tmp_path), output_dir=tmp_path, condition_labels=labels,
        ))


def test_empty_condition_set_is_rejected_before_writing(tmp_path) -> None:
    with pytest.raises(ValueError, match="at least one"):
        render_sequence_figure(SequenceFigureSpec(image_paths=(), output_dir=tmp_path))
    assert not list(tmp_path.iterdir())


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


def _line_paths(svg_text: str, color: str, *, stroke_width: str | None = None) -> list[str]:
    stroke_filter = "" if stroke_width is None else rf"(?=[^>]*stroke-width: {stroke_width})"
    return re.findall(
        rf'<path d="[^"]+"{stroke_filter}[^>]*stroke: {re.escape(color)}[^>]*>',
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

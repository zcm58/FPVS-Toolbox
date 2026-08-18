"""Non-Qt direct figure rendering contract checks."""

from __future__ import annotations

from pathlib import Path
import re

import pytest
from matplotlib.collections import PathCollection
from PIL import Image

from Main_App.exports.figure_style import (
    FIGURE_JOURNAL_TEXT_WIDTH_IN,
    FIGURE_STANDARD_LANDSCAPE_HEIGHT_IN,
)
from Tools.Plot_Generator.rendering import PlotRenderingMixin, _safe_figure_stem


class _RenderHarness(PlotRenderingMixin):
    condition = "Faces"
    condition_b = "Objects"
    title = ""
    xlabel = "Frequency (Hz)"
    ylabel = "SNR"
    x_min = 1.0
    x_max = 2.0
    y_min = 0.0
    y_max = 5.0
    stem_color = "red"
    stem_color_b = "blue"
    use_matlab_style = False
    selected_groups: list[str] = []
    group_roi_sample_sizes: dict[str, dict[str, int]] = {}
    legend_condition_a = None
    legend_condition_b = None
    legend_a_peaks = None
    legend_b_peaks = None
    roi_sample_sizes = {"Occipital": 2}
    overlay_roi_sample_sizes = {
        "Faces": {"Occipital": 2},
        "Objects": {"Occipital": 3},
    }

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.saved: list[Path] = []

    def _cancellation_checkpoint(self) -> bool:
        return False

    def _visible_oddball_frequencies(self, _freqs):
        return []

    def _resolve_legend_label(self, custom, default):
        return custom or default

    def _emit(self, *_args, **_kwargs) -> None:
        return None

    def _mark_timing(self, *_args, **_kwargs) -> None:
        return None

    def _record_figure_pair(self, *, png_path, pdf_path):
        self.saved.extend((png_path, pdf_path))


def test_single_and_overlay_figures_use_shared_width_and_show_participant_n(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dimensions: list[tuple[float, float]] = []
    legends: list[list[str]] = []

    def capture_save(figure, _path, *_args, **_kwargs) -> None:
        dimensions.append(tuple(float(value) for value in figure.get_size_inches()))
        legends.append(figure.axes[0].get_legend_handles_labels()[1])

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture_save)
    harness = _RenderHarness(tmp_path)

    harness._plot([1.0, 2.0], {"Occipital": [1.5, 2.5]})
    harness._plot_overlay(
        [1.0, 2.0],
        {"Occipital": [1.5, 2.5]},
        {"Occipital": [1.2, 2.2]},
    )

    assert dimensions
    assert all(
        size
        == pytest.approx(
            (
                FIGURE_JOURNAL_TEXT_WIDTH_IN,
                FIGURE_STANDARD_LANDSCAPE_HEIGHT_IN,
            )
        )
        for size in dimensions
    )
    assert legends[0][0] == "Faces (n=2)"
    assert "Faces (n=2)" in legends[2]
    assert "Objects (n=3)" in legends[2]


def test_real_png_and_pdf_exports_keep_exact_publication_dimensions(
    tmp_path: Path,
) -> None:
    harness = _RenderHarness(tmp_path)

    harness._plot([1.0, 2.0], {"Occipital": [1.5, 2.5]})

    png_path = tmp_path / "Faces - Occipital.png"
    pdf_path = tmp_path / "Faces - Occipital.pdf"
    with Image.open(png_path) as image:
        assert image.size == (3900, 2160)
    match = re.search(
        rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]",
        pdf_path.read_bytes(),
    )
    assert match is not None
    assert float(match.group(1)) == pytest.approx(468.0)
    assert float(match.group(2)) == pytest.approx(259.2)


def test_png_uses_fast_lossless_compression_without_changing_pdf_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, dict[str, object]]] = []

    def capture_save(_figure, path, *_args, **kwargs) -> None:
        calls.append((Path(path), kwargs))

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture_save)
    harness = _RenderHarness(tmp_path)

    harness._plot([1.0, 2.0], {"Occipital": [1.5, 2.5]})

    png_kwargs = next(kwargs for path, kwargs in calls if path.suffix == ".png")
    pdf_kwargs = next(kwargs for path, kwargs in calls if path.suffix == ".pdf")
    assert png_kwargs["pil_kwargs"] == {"compress_level": 1}
    assert "pil_kwargs" not in pdf_kwargs


def test_oddball_markers_are_batched_per_curve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = []

    def capture_save(figure, _path, *_args, **_kwargs) -> None:
        if figure not in figures:
            figures.append(figure)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture_save)
    harness = _RenderHarness(tmp_path)
    harness._visible_oddball_frequencies = lambda _freqs: [1.0, 2.0]

    harness._plot([1.0, 2.0], {"Occipital": [1.5, 2.5]})
    harness._plot_overlay(
        [1.0, 2.0],
        {"Occipital": [1.5, 2.5]},
        {"Occipital": [1.2, 2.2]},
    )

    single_markers = [
        item
        for item in figures[0].axes[0].collections
        if isinstance(item, PathCollection)
    ]
    overlay_markers = [
        item
        for item in figures[1].axes[0].collections
        if isinstance(item, PathCollection)
    ]
    assert len(single_markers) == 1
    assert len(single_markers[0].get_offsets()) == 2
    assert len(overlay_markers) == 2
    assert all(len(item.get_offsets()) == 2 for item in overlay_markers)


def test_sanitized_figure_stem_collisions_get_unique_hashed_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "matplotlib.figure.Figure.savefig",
        lambda *_args, **_kwargs: None,
    )
    harness = _RenderHarness(tmp_path)

    harness._plot(
        [1.0, 2.0],
        {
            "Occipital/A": [1.5, 2.5],
            r"Occipital\A": [1.2, 2.2],
        },
    )

    png_names = [path.name for path in harness.saved if path.suffix == ".png"]
    assert png_names[0] == "Faces - Occipital_A.png"
    assert re.fullmatch(
        r"Faces - Occipital_A__[0-9a-f]{12}\.png",
        png_names[1],
    )
    assert len(set(png_names)) == 2


def test_long_figure_stems_are_bounded_with_a_deterministic_hash() -> None:
    title = "Very Long Condition " * 30

    first = _safe_figure_stem(base_title=title, roi="Occipital")
    second = _safe_figure_stem(base_title=title, roi="Occipital")

    assert first == second
    assert len(first) <= 96
    assert re.search(r"__[0-9a-f]{12}$", first)
    assert _safe_figure_stem(
        base_title="Faces",
        roi="Occipital",
    ) == "Faces - Occipital"

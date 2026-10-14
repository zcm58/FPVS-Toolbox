"""Non-Qt direct figure rendering contract checks."""

from __future__ import annotations

from pathlib import Path
import re

import pytest
import numpy as np
from matplotlib.collections import LineCollection, PathCollection
from PIL import Image

from Main_App.exports.figure_style import (
    FIGURE_JOURNAL_TEXT_WIDTH_IN,
    FIGURE_STANDARD_LANDSCAPE_HEIGHT_IN,
)
from Tools.Plot_Generator.rendering import PlotRenderingMixin, _safe_figure_stem
from Tools.Plot_Generator.session_aggregation import (
    SessionSNRAggregation,
    SessionSNRCell,
)
from Tools.Plot_Generator.session_rendering import SessionPlotRenderingMixin
from Tools.Plot_Generator.spectrum_style import SCHEMATIC_HEIGHT_IN


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
    _analysis_base_freq = 6.0
    _analysis_oddball_freq = 1.2
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


class _SessionRenderHarness(SessionPlotRenderingMixin):
    title = "Faces"
    xlabel = "Frequency (Hz)"
    ylabel = "SNR"
    x_min = 1.0
    x_max = 2.0
    y_min = 0.0
    y_max = 5.0
    stem_color = "red"
    stem_color_b = "blue"
    use_matlab_style = False
    _analysis_base_freq = 6.0
    _analysis_oddball_freq = 1.2

    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.saved: list[Path] = []

    def _cancellation_checkpoint(self) -> bool:
        return False

    def _visible_oddball_frequencies(self, _freqs):
        return []

    def _mark_timing(self, *_args, **_kwargs) -> None:
        return None

    def _record_figure_pair(self, *, png_path, pdf_path) -> None:
        self.saved.extend((png_path, pdf_path))

    def _emit(self, *_args, **_kwargs) -> None:
        return None


def _session_cell(
    *,
    group_id: str,
    group_label: str,
    session_id: str,
    session_label: str,
    visit_index: int,
    values: tuple[float, float],
) -> SessionSNRCell:
    return SessionSNRCell(
        condition="Faces",
        group_id=group_id,
        group_label=group_label,
        session_id=session_id,
        session_label=session_label,
        visit_index=visit_index,
        roi="Occipital",
        plotted_values=values,
        participant_n_by_frequency=(2, 2),
        participant_ids=("P01", "P02"),
        recording_ids=(f"P01_{session_id}", f"P02_{session_id}"),
    )


def test_session_figure_stacks_normal_width_group_panels_without_differences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    figures = []

    def capture_save(figure, _path, *_args, **_kwargs) -> None:
        Path(_path).write_bytes(b"rendered figure")
        if figure not in figures:
            figures.append(figure)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture_save)
    aggregation = SessionSNRAggregation(
        condition="Faces",
        frequency_count=2,
        group_ids=("birth_control", "control"),
        session_ids=("luteal", "follicular"),
        cells=(
            _session_cell(
                group_id="birth_control",
                group_label="BC Group",
                session_id="luteal",
                session_label="Luteal Phase",
                visit_index=1,
                values=(1.5, 2.0),
            ),
            _session_cell(
                group_id="birth_control",
                group_label="BC Group",
                session_id="follicular",
                session_label="Follicular Phase",
                visit_index=2,
                values=(1.7, 2.2),
            ),
            _session_cell(
                group_id="control",
                group_label="Control Group",
                session_id="luteal",
                session_label="Luteal Phase",
                visit_index=1,
                values=(1.4, 1.8),
            ),
            _session_cell(
                group_id="control",
                group_label="Control Group",
                session_id="follicular",
                session_label="Follicular Phase",
                visit_index=2,
                values=(1.6, 2.1),
            ),
        ),
        paired_differences=(),
        reference_session_id="luteal",
        comparison_session_id="follicular",
    )
    harness = _SessionRenderHarness(tmp_path)

    harness._plot_session_comparison([1.0, 2.0], aggregation)

    assert len(figures) == 1
    figure = figures[0]
    assert tuple(figure.get_size_inches()) == pytest.approx(
        (
            FIGURE_JOURNAL_TEXT_WIDTH_IN,
            FIGURE_STANDARD_LANDSCAPE_HEIGHT_IN * 2 + SCHEMATIC_HEIGHT_IN,
        )
    )
    assert len(figure.axes) == 3
    assert figure.axes[-1].get_label() == "stimulation_schematic"
    assert figure._suptitle is None
    spectra = figure.axes[:2]
    upper, lower = spectra
    assert [axis.get_title() for axis in spectra] == [
        "BC Group",
        "Control Group",
    ]
    assert upper.get_position().y0 > lower.get_position().y0
    assert upper.get_position().x0 == pytest.approx(lower.get_position().x0)
    assert upper.get_position().width == pytest.approx(lower.get_position().width)
    assert all(axis.get_xlabel() == "Frequency (Hz)" for axis in spectra)
    assert all(axis.get_ylabel() == "SNR" for axis in spectra)
    assert all(
        axis.get_legend_handles_labels()[1]
        == [
            "Luteal Phase (Visit 1, n=2)",
            "Follicular Phase (Visit 2, n=2)",
        ]
        for axis in spectra
    )
    figure_text = " ".join(
        [text.get_text() for text in figure.texts]
        + [axis.get_ylabel() for axis in figure.axes]
        + [
            label
            for axis in figure.axes
            for label in axis.get_legend_handles_labels()[1]
        ]
    ).casefold()
    assert "difference" not in figure_text
    assert [path.name for path in harness.saved] == [
        "Faces - Occipital_session_comparison.png",
        "Faces - Occipital_session_comparison.pdf",
    ]


def test_single_and_overlay_figures_use_shared_width_and_show_participant_n(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dimensions: list[tuple[float, float]] = []
    legends: list[list[str]] = []

    def capture_save(figure, _path, *_args, **_kwargs) -> None:
        Path(_path).write_bytes(b"rendered figure")
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
    assert all(width == FIGURE_JOURNAL_TEXT_WIDTH_IN for width, _height in dimensions)
    assert all(height > FIGURE_STANDARD_LANDSCAPE_HEIGHT_IN + SCHEMATIC_HEIGHT_IN for _width, height in dimensions)
    assert legends[0][0] == "Faces (n=2)"
    assert "Faces (n=2)" in legends[2]
    assert "Objects (n=3)" in legends[2]


def test_real_png_and_pdf_exports_keep_exact_publication_dimensions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from matplotlib.figure import Figure
    savefig = Figure.savefig
    sizes = []

    def capture_real_save(figure, path, **kwargs):
        sizes.append(tuple(figure.get_size_inches()))
        return savefig(figure, path, **kwargs)

    monkeypatch.setattr(Figure, "savefig", capture_real_save)
    harness = _RenderHarness(tmp_path)

    harness._plot([1.0, 2.0], {"Occipital": [1.5, 2.5]})

    png_path = tmp_path / "Faces - Occipital.png"
    pdf_path = tmp_path / "Faces - Occipital.pdf"
    with Image.open(png_path) as image:
        assert image.size == (3900, int(sizes[0][1] * 600))
        assert image.info["dpi"] == pytest.approx((600, 600), abs=0.01)
    match = re.search(
        rb"/MediaBox\s*\[\s*0\s+0\s+([0-9.]+)\s+([0-9.]+)\s*\]",
        pdf_path.read_bytes(),
    )
    assert match is not None
    assert float(match.group(1)) == pytest.approx(468.0)
    assert float(match.group(2)) == pytest.approx(sizes[0][1] * 72)


def test_png_uses_fast_lossless_compression_without_changing_pdf_options(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[Path, dict[str, object]]] = []

    def capture_save(_figure, path, *_args, **kwargs) -> None:
        Path(path).write_bytes(b"rendered figure")
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
        Path(_path).write_bytes(b"rendered figure")
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
        lambda _figure, path, **_kwargs: Path(path).write_bytes(b"rendered figure"),
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


@pytest.mark.parametrize("oddball_rate", [0.6, 1.2, 1.5])
def test_frozen_rates_drive_harmonic_labels_and_timing_without_changing_values(tmp_path, monkeypatch, oddball_rate):
    figures = []

    def capture_save(figure, path, **_kwargs):
        Path(path).write_bytes(b"rendered figure")
        if figure not in figures:
            figures.append(figure)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", capture_save)
    harness = _RenderHarness(tmp_path)
    base_rate = 5 * oddball_rate
    harness.x_min, harness.x_max = 0, 2 * base_rate + oddball_rate / 3
    harness._analysis_base_freq, harness._analysis_oddball_freq = base_rate, oddball_rate
    harness._visible_oddball_frequencies = lambda _grid: [oddball_rate * harmonic for harmonic in (1, 2, 3, 4, 6, 7, 8, 9)]
    frequencies = np.linspace(0, 2 * base_rate, 151)
    values = np.ones_like(frequencies)
    values[75], values[150] = 4.0, 3.0
    original = values.copy()
    harness._plot(frequencies.tolist(), {"Occipital": values.tolist()})

    figure = figures[0]
    ax, key = figure.axes
    assert [tick.get_text() for tick in ax.get_xticklabels()] == [
        f"{oddball_rate * harmonic:g}" for harmonic in range(1, 11)
    ]
    np.testing.assert_allclose(ax.get_xticks(), oddball_rate * np.arange(1, 11))
    np.testing.assert_array_equal(ax.lines[0].get_xdata(), frequencies)
    np.testing.assert_array_equal(ax.lines[0].get_ydata(), original)
    assert ax.lines[0].get_linewidth() == 0.8
    segments = next(item for item in ax.collections if isinstance(item, LineCollection)).get_segments()
    assert len(segments) == 2
    for segment in segments:
        for x, y in segment:
            assert y == original[int(np.abs(frequencies - x).argmin())]
    labels = [text.get_text() for text in key.texts]
    assert labels.count("O") == 2
    assert labels.count("S") == 8
    assert f"Base response ({base_rate:g} Hz)" in labels
    assert f"Oddball response ({oddball_rate:g} Hz)" in labels
    assert figure._suptitle is None and ax.get_title() == ""
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    for text in key.texts:
        bbox = text.get_window_extent(renderer)
        assert 0 <= bbox.x0 <= bbox.x1 <= figure.bbox.x1
        assert 0 <= bbox.y0 <= bbox.y1 <= figure.bbox.y1
    assert figure.legends[0].get_window_extent(renderer).y0 > key.get_tightbbox(renderer).y1


def test_nonintegral_protocol_does_not_invent_every_nth_stimulus(tmp_path, monkeypatch):
    from Tools.Plot_Generator.rendering import plt
    from Tools.Plot_Generator.spectrum_style import add_stimulation_schematic

    harness = _RenderHarness(tmp_path)
    harness._analysis_base_freq, harness._analysis_oddball_freq = 7.0, 2.0
    figure, ax = plt.subplots()
    ax.plot([1, 2], [1, 2])
    figure.tight_layout()
    old_size = ax.get_window_extent().height / figure.dpi
    add_stimulation_schematic(figure, harness)
    key = figure.axes[-1]
    assert not key.lines
    assert not any(text.get_text() in {"S", "O"} for text in key.texts)
    assert any(text.get_text() == "Base: 7 Hz; Oddball: 2 Hz" for text in key.texts)
    assert ax.get_window_extent().height / figure.dpi == pytest.approx(old_size)
    plt.close(figure)


def test_new_plot_colors_preserve_user_saved_preferences(tmp_path):
    from Tools.Plot_Generator.plot_settings import PlotSettingsManager

    manager = PlotSettingsManager(tmp_path / "plot.ini")
    assert manager.get_stem_color() == "#3210e8"
    assert manager.get_second_color() == "#d62728"
    manager.set_stem_color("green")
    manager.set_second_color("purple")
    manager.save()
    restored = PlotSettingsManager(manager.ini_path)
    assert restored.get_stem_color() == "green"
    assert restored.get_second_color() == "purple"

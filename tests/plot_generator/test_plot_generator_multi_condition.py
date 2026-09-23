"""Widget-free collection and publication contracts for 2–5 SNR conditions."""

from pathlib import Path

import matplotlib.colors
import numpy as np
import pandas as pd
import pytest
from matplotlib.collections import PathCollection

from Main_App.exports.figure_style import FIGURE_STANDARD_LANDSCAPE_SIZE_IN
from Main_App.processing.roi_settings import ALL_ROIS_OPTION
from Tools.Plot_Generator.export_plan import inspect_destinations
from Tools.Plot_Generator.render_naming import condition_overlay_title
from Tools.Plot_Generator.worker import _Worker


CONDITIONS = ("Faces", "Objects", "Animals", "Scenes", "Patterns")
FREQUENCIES = [1.0, 1.2, 2.4]


def _worker(tmp_path, monkeypatch, count=5, **overrides):
    monkeypatch.setattr(_Worker, "_read_analysis_float", lambda self, option, fallback: fallback)
    kwargs = dict(
        folder=str(tmp_path), condition=CONDITIONS[0], condition_b=CONDITIONS[1],
        extra_conditions=CONDITIONS[2:count], overlay=True,
        roi_map={"Occipital": ["Oz"]}, selected_roi="Occipital", title="",
        xlabel="Frequency (Hz)", ylabel="SNR", x_min=1.0, x_max=2.4,
        y_min=0.0, y_max=10.0, out_dir=str(tmp_path / "plots"),
        oddballs=[1.2, 2.4], spectral_qc_enabled=False,
    )
    kwargs.update(overrides)
    return _Worker(**kwargs)


def _capture_figures(monkeypatch):
    figures = []

    def save(figure, path, **kwargs):
        assert kwargs["dpi"] == 600
        Path(path).write_bytes(b"rendered figure")
        if figure not in figures:
            figures.append(figure)

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", save)
    return figures


def _stub_collection(worker, monkeypatch, values=None):
    calls = []
    monkeypatch.setattr(worker, "_list_excel_files", lambda condition: [Path(condition + ".xlsx")])

    def collect(condition, **kwargs):
        calls.append((condition, kwargs))
        if values and condition in values:
            return values[condition]
        return FREQUENCIES, {"P01": {"Occipital": [2.0, 3.0, 4.0]}}

    monkeypatch.setattr(worker, "_collect_data", collect)
    return calls


@pytest.mark.parametrize("count", [3, 5])
def test_overlay_reads_each_condition_and_preserves_values_and_support(tmp_path, monkeypatch, count):
    worker = _worker(tmp_path, monkeypatch, count)
    figures = _capture_figures(monkeypatch)
    progress = []
    worker.progress.connect(lambda message, processed, total: progress.append((processed, total)))
    for index, condition in enumerate(CONDITIONS[:count]):
        folder = tmp_path / condition
        folder.mkdir()
        for participant, offset in (("P01", 0), ("P02", 2)):
            data = pd.DataFrame({
                "Electrode": ["Oz"],
                **{f"{frequency:.4f}_Hz": [index + offset + point]
                   for point, frequency in enumerate(FREQUENCIES, start=1)},
            })
            data.to_excel(folder / f"{participant}_{condition}_Results.xlsx", sheet_name="FullSNR", index=False)

    worker._run()

    assert not worker.failed_items
    assert (count * 2, count * 2) in progress
    curves = worker._pending_source_curves["Occipital"]
    assert [curve.condition for curve in curves] == list(CONDITIONS[:count])
    for index, curve in enumerate(curves):
        assert curve.plotted_values == (index + 2, index + 3, index + 4)
        assert curve.participant_ids == ("P01", "P02")
        assert curve.participant_n_by_frequency == (2, 2, 2)
    assert len(worker._input_workbook_rows) == count * 2
    assert all(row["status"] == "included" for row in worker._input_workbook_rows.values())
    assert len(figures) == 1
    assert len(worker.generated_paths) == 2
    for path in map(Path, worker.generated_paths):
        assert path.exists()
        assert path.stem == condition_overlay_title(CONDITIONS[:count]) + " - Occipital"
    ax = figures[0].axes[0]
    for index, line in enumerate(ax.lines[:count]):
        np.testing.assert_allclose(line.get_xdata(), FREQUENCIES)
        np.testing.assert_allclose(line.get_ydata(), curves[index].plotted_values)
    assert len({matplotlib.colors.to_rgba(line.get_color()) for line in ax.lines[:count]}) == count
    markers = [item for item in ax.collections if isinstance(item, PathCollection)]
    assert len(markers) == count
    assert len({item.get_paths()[0].vertices.tobytes() for item in markers}) == count


@pytest.mark.parametrize("count", [3, 5])
@pytest.mark.parametrize("bad_grid", [[1.0, 1.2001, 2.4], [1.0, 1.2], []])
def test_extra_condition_grid_failure_prevents_any_figure(tmp_path, monkeypatch, count, bad_grid):
    worker = _worker(tmp_path, monkeypatch, count)
    last = CONDITIONS[count - 1]
    calls = _stub_collection(worker, monkeypatch, {last: (bad_grid, {"P01": {"Occipital": [2.0]}})})
    monkeypatch.setattr(worker, "_plot_overlay", lambda *args, **kwargs: pytest.fail("Invalid data cannot render"))
    worker._run()
    assert [call[0] for call in calls] == list(CONDITIONS[:count])
    assert worker.failed_items
    assert worker.generated_paths == []
    assert worker._pending_source_curves == {}
    assert not (tmp_path / "plots").exists()


def test_missing_extra_condition_roi_is_reported_without_partial_overlay(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    _stub_collection(worker, monkeypatch, {"Patterns": (FREQUENCIES, {"P01": {"Occipital": [np.nan] * 3}})})
    worker._run()
    assert worker.generated_paths == []
    assert worker.warning_items[0]["item"] == "Patterns:Occipital"
    assert "every selected condition" in worker.failed_items[0]["error"]


def test_shared_roi_keeps_all_five_curves_while_incomplete_roi_is_skipped(tmp_path, monkeypatch):
    worker = _worker(
        tmp_path, monkeypatch, selected_roi=ALL_ROIS_OPTION,
        roi_map={"Occipital": ["Oz"], "Central": ["Cz"]},
    )
    data = {
        condition: (FREQUENCIES, {"P01": {
            "Occipital": [2, 3, 4],
            **({"Central": [3, 4, 5]} if condition != "Scenes" else {}),
        }})
        for condition in CONDITIONS
    }
    _stub_collection(worker, monkeypatch, data)
    _capture_figures(monkeypatch)
    worker._run()
    assert worker.failed_items == []
    assert list(worker._pending_source_curves) == ["Occipital"]
    assert len(worker._pending_source_curves["Occipital"]) == 5
    assert len(worker.generated_paths) == 2
    assert all(Path(path).stem.endswith(" - Occipital") for path in worker.generated_paths)
    assert worker.warning_items == [{
        "code": "overlay_roi_unavailable", "item": "Scenes:Central",
        "message": "Condition overlay omitted ROI 'Central' because 'Scenes' has no usable participant data.",
    }]


def test_cancellation_during_extra_collection_stops_later_conditions(tmp_path, monkeypatch):
    worker = _worker(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(worker, "_list_excel_files", lambda condition: [Path(condition)])

    def collect(condition, **kwargs):
        calls.append(condition)
        if condition == "Animals":
            worker.stop()
        return FREQUENCIES, {"P01": {"Occipital": [2, 3, 4]}}

    monkeypatch.setattr(worker, "_collect_data", collect)
    worker._run()
    assert calls == list(CONDITIONS[:3])
    assert worker.generated_paths == []


@pytest.mark.parametrize("extras", [("Faces",), ("",), ("C", "D", "E", "F")])
def test_overlay_rejects_duplicate_empty_or_more_than_five_conditions(tmp_path, monkeypatch, extras):
    worker = _worker(tmp_path, monkeypatch, extra_conditions=extras)
    monkeypatch.setattr(worker, "_list_excel_files", lambda condition: pytest.fail("Reject before reading"))
    with pytest.raises(ValueError, match="two and five different"):
        worker._run()


@pytest.mark.parametrize("count", [3, 5])
def test_large_legend_is_below_axes_and_fits_full_size_text(tmp_path, monkeypatch, count):
    long_label = "A lengthy named experimental condition with important descriptive detail " * 2
    worker = _worker(
        tmp_path, monkeypatch, count,
        legend_custom_enabled=True, legend_condition_a=long_label,
        legend_condition_b="B" * 170,
        legend_a_peaks="Preserved custom A peaks", legend_b_peaks="Preserved custom B peaks",
        legend_extra_conditions=tuple(f"Extra {index} {long_label}" for index in range(count - 2)),
        legend_extra_peaks=tuple(f"Custom peaks {index}" for index in range(count - 2)),
    )
    _stub_collection(worker, monkeypatch)
    figures = _capture_figures(monkeypatch)
    worker._run()
    figure = figures[0]
    figure.canvas.draw()
    renderer = figure.canvas.get_renderer()
    ax = figure.axes[0]
    legend = figure.legends[0]
    bbox = legend.get_window_extent(renderer)
    assert bbox.y1 < ax.get_tightbbox(renderer).y0
    assert bbox.x0 >= figure.bbox.x0
    assert bbox.x1 <= figure.bbox.x1
    assert bbox.y0 >= figure.bbox.y0
    assert len(legend.texts) == 2 * count
    for text in legend.texts:
        assert text.get_fontsize() == 10
        assert text.get_fontfamily() == ["Arial"]
        assert text.get_window_extent(renderer).x1 <= figure.bbox.x1
    all_labels = [" ".join(text.get_text().split()) for text in legend.texts]
    assert "Preserved custom A peaks" in all_labels
    assert "Preserved custom B peaks" in all_labels
    assert any("Custom peaks 0" == label for label in all_labels)
    assert figure.get_size_inches()[0] == FIGURE_STANDARD_LANDSCAPE_SIZE_IN[0]
    assert figure.get_size_inches()[1] > FIGURE_STANDARD_LANDSCAPE_SIZE_IN[1]
    # A legend must not shrink the publication data area to make room for text.
    from Tools.Plot_Generator.rendering import plt
    reference, reference_ax = plt.subplots(figsize=FIGURE_STANDARD_LANDSCAPE_SIZE_IN)
    reference_ax.set(xlim=(1, 2.4), ylim=(0, 10), xlabel="Frequency (Hz)", ylabel="SNR")
    reference_ax.set_xticks([1, 2])
    reference.tight_layout()
    assert ax.get_window_extent(renderer).height / figure.dpi == pytest.approx(
        reference_ax.get_window_extent().height / reference.dpi, abs=0.01
    )
    plt.close(reference)


def test_long_five_condition_names_match_approved_export_pair(tmp_path, monkeypatch):
    names = tuple(f"Condition {index}: " + "long descriptive label " * 7 for index in range(5))
    worker = _worker(tmp_path, monkeypatch, condition=names[0], condition_b=names[1], extra_conditions=names[2:])
    choices = inspect_destinations(str(worker.out_dir), [(condition_overlay_title(names), "Occipital", "")])
    worker._figure_export_plan = choices.keep_both
    _stub_collection(worker, monkeypatch)
    _capture_figures(monkeypatch)
    worker._run()
    assert [Path(path) for path in worker.generated_paths] == list(choices.keep_both[0].paths)
    assert len(choices.keep_both[0].png_path.stem) <= 96

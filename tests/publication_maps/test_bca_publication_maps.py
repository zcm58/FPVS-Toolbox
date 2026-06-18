from __future__ import annotations

from pathlib import Path

from matplotlib.colors import to_hex
import numpy as np
import pandas as pd
from PIL import Image
import pytest

from Main_App.exports.figure_style import (
    FIGURE_FONT_FAMILY,
    FIGURE_PANEL_LABEL_SIZE_PT,
    FIGURE_TEXT_SIZE_PT,
    figure_text_kwargs,
)
from Tools.Stats.analysis import dv_policy_group_significant as group_policy
from Tools.Publication_Maps.colormaps import SCALP_COLORMAP_STOPS
from Tools.Publication_Maps.excel_inputs import discover_conditions
from Tools.Publication_Maps.metrics import build_publication_map_result
from Tools.Publication_Maps.models import (
    ColorBounds,
    DEFAULT_Z_SCORE_THRESHOLD,
    GRAND_AVERAGE_SHEET,
    LONG_VALUES_SHEET,
    PARAMETERS_SHEET,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps.rendering import (
    COMBINED_PAIRED_MAP_FIGSIZE,
    COMBINED_PAIRED_THREE_ROW_MAP_FIGSIZE,
    JOURNAL_TEXT_WIDTH_IN,
    _combined_paired_layout_rects,
    _metric_limits,
    colorbar_label_for_metric,
    colormap_for_metric,
    export_source_workbook,
    render_publication_figures,
)
from Tools.Publication_Maps.worker import PublicationMapsWorker


def test_discovers_condition_workbooks_and_skips_excel_lock_files(tmp_path: Path) -> None:
    root = tmp_path / "1 - Excel Data Files"
    cond = root / "Faces"
    cond.mkdir(parents=True)
    (cond / "P01_Faces_Results.xlsx").touch()
    (cond / "~$P02_Faces_Results.xlsx").touch()

    conditions = discover_conditions(root)

    assert [condition.name for condition in conditions] == ["Faces"]
    assert [path.name for path in conditions[0].files] == ["P01_Faces_Results.xlsx"]


def test_bca_maps_use_stats_group_significant_selection_and_sum_per_electrode(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1", "S2"))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=8.4,
        project_root=project_root,
    )

    result = build_publication_map_result(request)

    assert result.selected_harmonics_hz == pytest.approx((1.2, 3.6, 7.2))
    assert result.selection_metadata["harmonic_policy"] == "group_level_significant_harmonics"
    o1 = result.grand_average_values[
        (result.grand_average_values["condition"] == "Faces")
        & (result.grand_average_values["electrode"] == "O1")
    ].iloc[0]
    assert o1["aggregate_value"] == pytest.approx(3.0)
    assert o1["valid_subject_count"] == 2
    assert o1["render_value"] == pytest.approx(3.0)
    assert set(result.long_values["source_column"]) == {
        "1.2000_Hz",
        "3.6000_Hz",
        "7.2000_Hz",
    }


def test_snr_maps_use_stats_significant_selection_and_mean_per_electrode(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1", "S2"))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=8.4,
        project_root=project_root,
        metrics=(PublicationMetric.SNR,),
    )

    result = build_publication_map_result(request)

    assert result.selected_harmonics_hz == pytest.approx((1.2, 3.6, 7.2))
    assert set(result.long_values["metric"]) == {PublicationMetric.SNR.value}
    assert set(result.long_values["source_sheet"]) == {"SNR"}
    assert set(result.long_values["source_column"]) == {
        "1.2000_Hz",
        "3.6000_Hz",
        "7.2000_Hz",
    }
    o1 = result.grand_average_values[
        (result.grand_average_values["condition"] == "Faces")
        & (result.grand_average_values["electrode"] == "O1")
        & (result.grand_average_values["metric"] == PublicationMetric.SNR.value)
    ].iloc[0]
    assert o1["aggregate_value"] == pytest.approx(1.35)
    assert o1["render_value"] == pytest.approx(1.35)
    assert o1["valid_subject_count"] == 2
    assert o1["map_label"] == "SNR significant-harmonic mean"


def test_z_score_maps_use_stats_significant_selection_and_combined_z_per_electrode(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1", "S2"))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=8.4,
        project_root=project_root,
        metrics=(PublicationMetric.Z_SCORE,),
    )

    result = build_publication_map_result(request)

    assert result.selected_harmonics_hz == pytest.approx((1.2, 3.6, 7.2))
    assert set(result.long_values["metric"]) == {PublicationMetric.Z_SCORE.value}
    assert set(result.long_values["source_sheet"]) == {"Z Score"}
    o1 = result.grand_average_values[
        (result.grand_average_values["condition"] == "Faces")
        & (result.grand_average_values["electrode"] == "O1")
        & (result.grand_average_values["metric"] == PublicationMetric.Z_SCORE.value)
    ].iloc[0]
    assert o1["aggregate_value"] == pytest.approx(6.5 / np.sqrt(3.0))
    assert o1["render_value"] == pytest.approx(6.5 / np.sqrt(3.0))
    assert o1["valid_subject_count"] == 2
    assert o1["map_label"] == "Z-score significant-harmonic sum"


def test_snr_maps_report_missing_exact_selected_columns(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    workbook = excel_root / "Faces" / "S1_Faces_Results.xlsx"
    _drop_sheet_column(workbook, sheet_name="SNR", column="3.6000_Hz")
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
        metrics=(PublicationMetric.SNR,),
    )

    result = build_publication_map_result(request)

    diagnostic = next(
        diag
        for diag in result.diagnostics
        if diag.message == "Missing exact selected SNR harmonic columns."
    )
    assert diagnostic.workbook == workbook.name
    assert "3.6000_Hz" in diagnostic.detail
    assert result.long_values.empty
    assert result.grand_average_values.empty


def test_bca_maps_can_reuse_saved_stats_harmonic_cache(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
    )

    first = build_publication_map_result(request)
    group_policy.clear_group_significant_selection_cache()
    second = build_publication_map_result(request)

    assert first.selected_harmonics_hz == pytest.approx((1.2, 3.6))
    assert second.selected_harmonics_hz == pytest.approx((1.2, 3.6))
    assert second.selection_metadata["selection_cache_source"] == "saved_project_metadata"


def test_exports_source_workbook_and_nonblank_figures(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    output_root = project_root / "4 - Scalp Maps"
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=output_root,
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
    )
    result = build_publication_map_result(request)

    workbook_path = export_source_workbook(result, request)
    figures = render_publication_figures(result, request)

    assert workbook_path.exists()
    assert workbook_path.stat().st_size > 0
    assert figures
    assert all(path.exists() and path.stat().st_size > 0 for path in figures)
    pdf = next(path for path in figures if path.suffix == ".pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert not list(output_root.rglob("*.svg"))
    png = next(path for path in figures if path.suffix == ".png")
    with Image.open(png) as image:
        assert image.width == int(JOURNAL_TEXT_WIDTH_IN * request.png_dpi)


def test_source_workbook_includes_bca_and_snr_when_both_selected(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    output_root = project_root / "4 - Scalp Maps"
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=output_root,
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
        metrics=(PublicationMetric.BCA, PublicationMetric.SNR),
        color_bounds={
            PublicationMetric.BCA: ColorBounds(auto_scale=False, vmin=0.0, vmax=0.4),
            PublicationMetric.SNR: ColorBounds(auto_scale=False, vmin=1.0, vmax=1.5),
        },
    )
    result = build_publication_map_result(request)

    workbook_path = export_source_workbook(result, request)

    long_values = pd.read_excel(workbook_path, sheet_name=LONG_VALUES_SHEET)
    grand_values = pd.read_excel(workbook_path, sheet_name=GRAND_AVERAGE_SHEET)
    params = pd.read_excel(workbook_path, sheet_name=PARAMETERS_SHEET)
    params_by_key = dict(zip(params["key"], params["value"]))
    assert set(long_values["metric"]) == {
        PublicationMetric.BCA.value,
        PublicationMetric.SNR.value,
    }
    assert set(long_values["source_sheet"]) == {"BCA (uV)", "SNR"}
    assert set(grand_values["metric"]) == {
        PublicationMetric.BCA.value,
        PublicationMetric.SNR.value,
    }
    assert params_by_key["metrics"] == "bca; snr"
    assert params_by_key["bca_range_max"] == pytest.approx(0.4)
    assert params_by_key["snr_range_min"] == pytest.approx(1.0)
    assert params_by_key["snr_range_max"] == pytest.approx(1.5)


def test_source_workbook_includes_z_score_threshold_when_selected(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    output_root = project_root / "4 - Scalp Maps"
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=output_root,
        conditions=("Faces",),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
        metrics=(PublicationMetric.Z_SCORE,),
        color_bounds={
            PublicationMetric.Z_SCORE: ColorBounds(vmin=DEFAULT_Z_SCORE_THRESHOLD),
        },
    )
    result = build_publication_map_result(request)

    workbook_path = export_source_workbook(result, request)

    long_values = pd.read_excel(workbook_path, sheet_name=LONG_VALUES_SHEET)
    grand_values = pd.read_excel(workbook_path, sheet_name=GRAND_AVERAGE_SHEET)
    params = pd.read_excel(workbook_path, sheet_name=PARAMETERS_SHEET)
    params_by_key = dict(zip(params["key"], params["value"]))
    assert set(long_values["metric"]) == {PublicationMetric.Z_SCORE.value}
    assert set(long_values["source_sheet"]) == {"Z Score"}
    assert set(grand_values["metric"]) == {PublicationMetric.Z_SCORE.value}
    assert params_by_key["metrics"] == PublicationMetric.Z_SCORE.value
    assert bool(params_by_key["z_score_auto_scale"])
    assert params_by_key["z_score_range_min"] == pytest.approx(DEFAULT_Z_SCORE_THRESHOLD)


def test_exports_combined_paired_condition_figure_when_bca_and_snr_selected(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project_workbooks(
        tmp_path,
        subjects=("S1",),
        conditions=("Faces", "Objects", "Places"),
    )
    output_root = project_root / "4 - Scalp Maps"
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=output_root,
        conditions=("Faces", "Objects", "Places"),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
        metrics=(PublicationMetric.BCA, PublicationMetric.SNR),
        export_paired_figures=True,
        paired_conditions=("Objects", "Faces"),
    )
    result = build_publication_map_result(request)

    figures = render_publication_figures(result, request)

    paired = [path for path in figures if "_and_" in path.stem]
    assert {path.suffix for path in paired} == {".png", ".pdf"}
    assert {path.stem for path in paired} == {"Objects_and_Faces_bca_snr_paired"}
    paired_png = next(path for path in paired if path.suffix == ".png")
    with Image.open(paired_png) as image:
        assert image.width == int(JOURNAL_TEXT_WIDTH_IN * request.png_dpi)
        assert image.height == int(COMBINED_PAIRED_MAP_FIGSIZE[1] * request.png_dpi)


def test_exports_combined_paired_condition_figure_with_z_score_third_row(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project_workbooks(
        tmp_path,
        subjects=("S1",),
        conditions=("Faces", "Objects"),
    )
    output_root = project_root / "4 - Scalp Maps"
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=output_root,
        conditions=("Faces", "Objects"),
        base_frequency_hz=6.0,
        max_frequency_hz=3.6,
        project_root=project_root,
        metrics=(
            PublicationMetric.BCA,
            PublicationMetric.SNR,
            PublicationMetric.Z_SCORE,
        ),
        color_bounds={
            PublicationMetric.Z_SCORE: ColorBounds(vmin=DEFAULT_Z_SCORE_THRESHOLD),
        },
        export_paired_figures=True,
        paired_conditions=("Objects", "Faces"),
    )
    result = build_publication_map_result(request)

    figures = render_publication_figures(result, request)

    paired = [path for path in figures if "_and_" in path.stem]
    assert {path.suffix for path in paired} == {".png", ".pdf"}
    assert {path.stem for path in paired} == {
        "Objects_and_Faces_bca_snr_z_score_paired"
    }
    paired_png = next(path for path in paired if path.suffix == ".png")
    with Image.open(paired_png) as image:
        assert image.width == int(JOURNAL_TEXT_WIDTH_IN * request.png_dpi)
        assert image.height == int(
            COMBINED_PAIRED_THREE_ROW_MAP_FIGSIZE[1] * request.png_dpi
        )


def test_combined_paired_layout_balances_outer_spacing() -> None:
    layout = _combined_paired_layout_rects()
    bca_row = layout[PublicationMetric.BCA]
    snr_row = layout[PublicationMetric.SNR]

    assert bca_row["first"][0] == snr_row["first"][0]
    assert bca_row["second"][0] == snr_row["second"][0]
    assert bca_row["colorbar"][0] == snr_row["colorbar"][0]
    assert bca_row["first"][0] == pytest.approx(0.07)
    assert bca_row["second"][0] == pytest.approx(0.49)
    assert bca_row["second"][0] > bca_row["first"][0] + bca_row["first"][2]
    assert bca_row["colorbar"][0] > bca_row["second"][0] + bca_row["second"][2]
    assert 1.0 - (bca_row["colorbar"][0] + bca_row["colorbar"][2]) >= 0.10


def test_combined_paired_layout_supports_z_score_third_row() -> None:
    layout = _combined_paired_layout_rects(
        metrics=(
            PublicationMetric.BCA,
            PublicationMetric.SNR,
            PublicationMetric.Z_SCORE,
        )
    )
    bca_row = layout[PublicationMetric.BCA]
    snr_row = layout[PublicationMetric.SNR]
    z_row = layout[PublicationMetric.Z_SCORE]

    assert bca_row["first"][0] == snr_row["first"][0] == z_row["first"][0]
    assert bca_row["second"][0] == snr_row["second"][0] == z_row["second"][0]
    assert bca_row["colorbar"][0] == snr_row["colorbar"][0] == z_row["colorbar"][0]
    assert bca_row["first"][1] > snr_row["first"][1] > z_row["first"][1]
    assert snr_row["first"][1] > z_row["first"][1] + z_row["first"][3]


def test_bca_colormap_defaults_and_custom_endpoints() -> None:
    default_cmap = colormap_for_metric(PublicationMetric.BCA, ColorBounds())

    assert default_cmap.name == "FpvsDetailedScalpSequentialCustom"
    assert to_hex(default_cmap(0.0)).lower() == "#2166ac"
    assert to_hex(default_cmap(1.0)).lower() == "#b2182b"
    assert SCALP_COLORMAP_STOPS == (
        (0.0, "#2166ac"),
        (0.25, "#67a9cf"),
        (0.4, "#1a9850"),
        (0.6, "#fee08b"),
        (0.8, "#fdae61"),
        (1.0, "#b2182b"),
    )

    custom_cmap = colormap_for_metric(
        PublicationMetric.BCA,
        ColorBounds(low_color="#000000", high_color="#ffffff"),
    )

    assert to_hex(custom_cmap(0.0)).lower() == "#000000"
    assert to_hex(custom_cmap(1.0)).lower() == "#ffffff"


def test_snr_uses_detailed_scalp_colormap() -> None:
    snr_cmap = colormap_for_metric(PublicationMetric.SNR, ColorBounds())

    assert snr_cmap.name == "FpvsDetailedScalpSequentialCustom"
    assert to_hex(snr_cmap(0.0)).lower() == "#2166ac"
    assert to_hex(snr_cmap(1.0)).lower() == "#b2182b"


def test_z_score_colormap_uses_white_below_threshold() -> None:
    z_cmap = colormap_for_metric(PublicationMetric.Z_SCORE, ColorBounds())

    assert z_cmap.name == "FpvsDetailedScalpSequentialCustom"
    assert to_hex(z_cmap(-0.1)).lower() == "#ffffff"
    assert to_hex(z_cmap(0.0)).lower() == "#2166ac"
    assert to_hex(z_cmap(1.0)).lower() == "#b2182b"


def test_bca_metric_limits_auto_or_fixed() -> None:
    data = np.asarray([0.0, 0.25, 0.75])

    assert _metric_limits(data, metric=PublicationMetric.BCA, bounds=ColorBounds()) == (
        0.0,
        0.75,
    )
    assert _metric_limits(
        data,
        metric=PublicationMetric.BCA,
        bounds=ColorBounds(auto_scale=False, vmin=0.0, vmax=0.4),
    ) == (0.0, 0.4)


def test_snr_metric_limits_auto_or_fixed() -> None:
    data = np.asarray([1.1, 1.25, 1.4])

    assert _metric_limits(data, metric=PublicationMetric.SNR, bounds=ColorBounds()) == (
        1.1,
        1.4,
    )
    assert _metric_limits(
        data,
        metric=PublicationMetric.SNR,
        bounds=ColorBounds(auto_scale=False, vmin=1.0, vmax=1.5),
    ) == (1.0, 1.5)


def test_z_score_metric_limits_use_threshold_and_auto_upper_limit() -> None:
    data = np.asarray([0.5, 1.7, 3.2])

    assert _metric_limits(
        data,
        metric=PublicationMetric.Z_SCORE,
        bounds=ColorBounds(vmin=DEFAULT_Z_SCORE_THRESHOLD),
    ) == (DEFAULT_Z_SCORE_THRESHOLD, 3.2)
    assert _metric_limits(
        np.asarray([0.2, 0.5]),
        metric=PublicationMetric.Z_SCORE,
        bounds=ColorBounds(vmin=DEFAULT_Z_SCORE_THRESHOLD),
    ) == (
        DEFAULT_Z_SCORE_THRESHOLD,
        DEFAULT_Z_SCORE_THRESHOLD + 1.0,
    )


def test_bca_colorbar_label_and_fonts_use_shared_figure_typography() -> None:
    axis_font = figure_text_kwargs("axis_label")
    condition_font = figure_text_kwargs("condition_label")
    panel_font = figure_text_kwargs("panel_label")

    assert colorbar_label_for_metric(PublicationMetric.BCA) == (
        "Baseline-corrected amplitude (µV)"
    )
    assert colorbar_label_for_metric(PublicationMetric.SNR) == "Signal to Noise Ratio"
    assert colorbar_label_for_metric(PublicationMetric.Z_SCORE) == "Z Score"
    assert axis_font["fontfamily"] == FIGURE_FONT_FAMILY
    assert axis_font["fontsize"] == FIGURE_TEXT_SIZE_PT
    assert condition_font["fontsize"] == FIGURE_TEXT_SIZE_PT
    assert panel_font["fontsize"] == FIGURE_PANEL_LABEL_SIZE_PT
    assert panel_font["fontweight"] == "bold"


def test_worker_emits_progress_messages_and_finished_without_widgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
    )
    result = PublicationMapResult(
        long_values=pd.DataFrame(),
        grand_average_values=pd.DataFrame(),
    )
    calls: list[str] = []

    def fake_build(seen_request: PublicationMapRequest) -> PublicationMapResult:
        assert seen_request is request
        calls.append("build")
        return result

    def fake_export(
        seen_result: PublicationMapResult,
        seen_request: PublicationMapRequest,
    ) -> Path:
        assert seen_result is result
        assert seen_request is request
        calls.append("export")
        return seen_request.output_root / "Publication_Scalp_Maps_Source_Data.xlsx"

    def fake_render(
        seen_result: PublicationMapResult,
        seen_request: PublicationMapRequest,
    ) -> list[Path]:
        assert seen_result is result
        assert seen_request is request
        calls.append("render")
        return [seen_request.output_root / "Faces_bca_BCA_significant-harmonic_sum.pdf"]

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fake_build,
    )
    monkeypatch.setattr("Tools.Publication_Maps.worker.export_source_workbook", fake_export)
    monkeypatch.setattr("Tools.Publication_Maps.worker.render_publication_figures", fake_render)

    worker = PublicationMapsWorker(request)
    progress: list[int] = []
    messages: list[str] = []
    errors: list[str] = []
    finished: list[object] = []
    worker.progress.connect(progress.append)
    worker.message.connect(messages.append)
    worker.error.connect(errors.append)
    worker.finished.connect(finished.append)

    worker.run()

    assert calls == ["build", "export", "render"]
    assert progress == [5, 55, 70, 100]
    assert messages == [
        "Reading workbooks...",
        "Writing source-data workbook...",
        "Rendering scalp maps...",
        "Complete.",
    ]
    assert errors == []
    assert len(finished) == 1
    assert finished[0] is result


def _write_project_workbooks(
    tmp_path: Path,
    *,
    subjects: tuple[str, ...],
    conditions: tuple[str, ...] = ("Faces",),
) -> tuple[Path, Path]:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        (
            "{\n"
            '  "schema_version": "2.1.0",\n'
            '  "subfolders": {"excel": "1 - Excel Data Files"}\n'
            "}\n"
        ),
        encoding="utf-8",
    )
    for condition_idx, condition in enumerate(conditions, start=1):
        condition_root = excel_root / condition
        condition_root.mkdir(parents=True)
        for subject_idx, subject in enumerate(subjects, start=1):
            _write_group_policy_workbook(
                condition_root / f"{subject}_{condition}_Results.xlsx",
                scale=subject_idx + condition_idx - 1,
            )
    return project_root, excel_root


def _write_group_policy_workbook(
    path: Path,
    *,
    scale: int,
    frequency_step: float = 0.3,
    peak_targets: set[float] | None = None,
) -> None:
    if peak_targets is None:
        peak_targets = {1.2, 3.6, 7.2}
    frequency_values = [
        round(frequency_step * idx, 4)
        for idx in range(0, int(round(10.2 / frequency_step)) + 1)
    ]
    fft_values = []
    for idx, freq in enumerate(frequency_values):
        base_noise = 1.2 if idx % 2 == 0 else 0.8
        if any(abs(freq - target) <= frequency_step / 2 for target in peak_targets):
            base_noise = 20.0
        fft_values.append(base_noise)
    full_fft = pd.DataFrame(
        {
            f"{freq:.4f}_Hz": [value, value, value]
            for freq, value in zip(frequency_values, fft_values)
        },
        index=["O1", "O2", "FZ"],
    )
    full_fft.index.name = "Electrode"

    bca = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5 * scale],
            "2.4000_Hz": [100.0, 100.0, 100.0],
            "3.6000_Hz": [0.5, 0.5, 0.1],
            "4.8000_Hz": [100.0, 100.0, 100.0],
            "6.0000_Hz": [100.0, 100.0, 100.0],
            "7.2000_Hz": [1.0, 1.0, 0.1],
        },
        index=["O1", "O2", "FZ"],
    )
    bca.index.name = "Electrode"
    snr = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 + 0.1 * scale, 1.2 + 0.1 * scale, 1.4 + 0.1 * scale],
            "2.4000_Hz": [9.0, 9.0, 9.0],
            "3.6000_Hz": [1.2 + 0.1 * scale, 1.4 + 0.1 * scale, 1.6 + 0.1 * scale],
            "4.8000_Hz": [9.0, 9.0, 9.0],
            "6.0000_Hz": [9.0, 9.0, 9.0],
            "7.2000_Hz": [1.4 + 0.1 * scale, 1.6 + 0.1 * scale, 1.8 + 0.1 * scale],
        },
        index=["O1", "O2", "FZ"],
    )
    snr.index.name = "Electrode"
    z_score = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5 * scale],
            "2.4000_Hz": [9.0, 9.0, 9.0],
            "3.6000_Hz": [2.0, 1.0, 0.5],
            "4.8000_Hz": [9.0, 9.0, 9.0],
            "6.0000_Hz": [9.0, 9.0, 9.0],
            "7.2000_Hz": [3.0, 2.0, 1.0],
        },
        index=["O1", "O2", "FZ"],
    )
    z_score.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)")
        snr.to_excel(writer, sheet_name="SNR")
        z_score.to_excel(writer, sheet_name="Z Score")
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")


def _drop_sheet_column(path: Path, *, sheet_name: str, column: str) -> None:
    sheets = pd.read_excel(path, sheet_name=None)
    sheets[sheet_name] = sheets[sheet_name].drop(columns=[column])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for current_sheet_name, sheet in sheets.items():
            sheet.to_excel(writer, sheet_name=current_sheet_name, index=False)

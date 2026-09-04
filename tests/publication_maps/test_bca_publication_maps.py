from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import matplotlib.pyplot as plt
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
from Main_App.processing import full_fft_provenance, harmonic_selection_qc
from Main_App.projects.project import Project
from Tools.Publication_Maps import metrics as publication_map_metrics
from Tools.Stats.analysis import dv_policy_group_significant as group_policy
from Tools.Publication_Maps.colormaps import SCALP_COLORMAP_STOPS
from Tools.Publication_Maps.excel_inputs import discover_conditions
from Tools.Publication_Maps.generation_outcome import PublicationMapsOutcomeStatus
from Tools.Publication_Maps.metrics import build_publication_map_result
from Tools.Publication_Maps.models import (
    ColorBounds,
    DEFAULT_Z_SCORE_THRESHOLD,
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
    PublicationMetric,
)
from Tools.Publication_Maps.rendering import (
    COMBINED_PAIRED_MAP_FIGSIZE,
    COMBINED_PAIRED_THREE_ROW_MAP_FIGSIZE,
    JOURNAL_TEXT_WIDTH_IN,
    MULTI_GROUP_LAYOUT_STYLE,
    PAIRED_CONDITION_LAYOUT_STYLE,
    SINGLE_GROUP_LAYOUT_STYLE,
    _colorbar_text_kwargs,
    _combined_paired_layout_rects,
    _metric_limits,
    _render_paired_topomap,
    _paired_condition_title_kwargs,
    _style_colorbar,
    colorbar_label_for_metric,
    colormap_for_metric,
    render_publication_figures,
)
from Tools.Publication_Maps.scalp_io import InsufficientSensorCoverageError
from Tools.Publication_Maps.worker import PublicationMapsWorker
from Tools.Stats.analysis.canonical_harmonics import CanonicalHarmonicSelectionError


@pytest.fixture(autouse=True)
def _stable_processing_harmonic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_base_frequency_hz", lambda: 6.0)
    monkeypatch.setattr(harmonic_selection_qc, "_analysis_bca_upper_limit_hz", lambda: 8.4)
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        lambda _root, *, dataset_index=None: {},
    )
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_full_fft_provenance",
        lambda _root, *, dataset_index=None: object(),
    )


def test_ordinary_figure_layout_families_have_independent_frozen_styles() -> None:
    assert SINGLE_GROUP_LAYOUT_STYLE is not PAIRED_CONDITION_LAYOUT_STYLE
    assert PAIRED_CONDITION_LAYOUT_STYLE is not MULTI_GROUP_LAYOUT_STYLE
    assert SINGLE_GROUP_LAYOUT_STYLE.single_map_figsize == (6.5, 5.6)
    assert PAIRED_CONDITION_LAYOUT_STYLE.paired_map_figsize == (6.5, 3.4)
    assert MULTI_GROUP_LAYOUT_STYLE.paired_map_figsize == (6.5, 3.4)

    revised_paired = replace(
        PAIRED_CONDITION_LAYOUT_STYLE,
        paired_map_figsize=(6.5, 4.0),
    )

    assert revised_paired.paired_map_figsize == (6.5, 4.0)
    assert MULTI_GROUP_LAYOUT_STYLE.paired_map_figsize == (6.5, 3.4)
    with pytest.raises(FrozenInstanceError):
        PAIRED_CONDITION_LAYOUT_STYLE.paired_map_figsize = (6.5, 4.0)


def test_discovers_condition_workbooks_and_skips_excel_lock_files(tmp_path: Path) -> None:
    root = tmp_path / "1 - Excel Data Files"
    cond = root / "Faces"
    cond.mkdir(parents=True)
    (cond / "P01_Faces_Results.xlsx").touch()
    (cond / "~$P02_Faces_Results.xlsx").touch()
    (cond / "._P03_Faces_Results.xlsx").touch()

    conditions = discover_conditions(root)

    assert [condition.name for condition in conditions] == ["Faces"]
    assert [path.name for path in conditions[0].files] == ["P01_Faces_Results.xlsx"]


def test_paired_render_closes_figure_when_sensor_coverage_is_insufficient(
    tmp_path: Path,
) -> None:
    values = pd.DataFrame({"electrode": ["O1"], "render_value": [1.0]})
    open_figures = set(plt.get_fignums())

    with pytest.raises(InsufficientSensorCoverageError):
        _render_paired_topomap(
            values,
            values,
            metric=PublicationMetric.BCA,
            first_title="First",
            second_title="Second",
            output_path=tmp_path / "paired.png",
            bounds=ColorBounds(),
            dpi=600,
            cancel_check=None,
        )

    assert set(plt.get_fignums()) == open_figures


def test_bca_maps_use_stats_group_significant_selection_and_sum_per_electrode(
    tmp_path: Path,
) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1", "S2"))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
    )

    result = build_publication_map_result(request)

    assert result.selected_harmonics_hz == pytest.approx((1.2, 2.4, 3.6, 4.8, 7.2))
    assert result.selection_metadata["harmonic_policy"] == "group_level_significant_harmonics"
    assert result.selection_metadata["detected_significant_harmonics_hz"] == pytest.approx(
        (1.2, 3.6, 7.2)
    )
    o1 = result.grand_average_values[
        (result.grand_average_values["condition"] == "Faces")
        & (result.grand_average_values["electrode"] == "O1")
    ].iloc[0]
    assert o1["aggregate_value"] == pytest.approx(203.0)
    assert o1["valid_subject_count"] == 2
    assert o1["render_value"] == pytest.approx(203.0)
    assert set(result.long_values["source_column"]) == {
        "1.2000_Hz",
        "2.4000_Hz",
        "3.6000_Hz",
        "4.8000_Hz",
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
        project_root=project_root,
        metrics=(PublicationMetric.SNR,),
    )

    result = build_publication_map_result(request)

    assert result.selected_harmonics_hz == pytest.approx((1.2, 2.4, 3.6, 4.8, 7.2))
    assert set(result.long_values["metric"]) == {PublicationMetric.SNR.value}
    assert set(result.long_values["source_sheet"]) == {"SNR"}
    assert set(result.long_values["source_column"]) == {
        "1.2000_Hz",
        "2.4000_Hz",
        "3.6000_Hz",
        "4.8000_Hz",
        "7.2000_Hz",
    }
    o1 = result.grand_average_values[
        (result.grand_average_values["condition"] == "Faces")
        & (result.grand_average_values["electrode"] == "O1")
        & (result.grand_average_values["metric"] == PublicationMetric.SNR.value)
    ].iloc[0]
    assert o1["aggregate_value"] == pytest.approx(4.41)
    assert o1["render_value"] == pytest.approx(4.41)
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
        project_root=project_root,
        metrics=(PublicationMetric.Z_SCORE,),
    )

    result = build_publication_map_result(request)

    assert result.selected_harmonics_hz == pytest.approx((1.2, 2.4, 3.6, 4.8, 7.2))
    assert set(result.long_values["metric"]) == {PublicationMetric.Z_SCORE.value}
    assert set(result.long_values["source_sheet"]) == {"Z Score"}
    o1 = result.grand_average_values[
        (result.grand_average_values["condition"] == "Faces")
        & (result.grand_average_values["electrode"] == "O1")
        & (result.grand_average_values["metric"] == PublicationMetric.Z_SCORE.value)
    ].iloc[0]
    assert o1["aggregate_value"] == pytest.approx(24.5 / np.sqrt(5.0))
    assert o1["render_value"] == pytest.approx(24.5 / np.sqrt(5.0))
    assert o1["valid_subject_count"] == 2
    assert o1["map_label"] == "Z-score significant-harmonic sum"


def test_snr_maps_report_missing_exact_selected_columns(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    workbook = excel_root / "Faces" / "S1_Faces_Results.xlsx"
    _drop_sheet_column(workbook, sheet_name="SNR", column="3.6000_Hz")
    harmonic_selection_qc.run_processing_harmonic_selection_qc(Project.load(project_root))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
        metrics=(PublicationMetric.SNR,),
    )

    with pytest.raises(
        PublicationMapInputError,
        match=r"Missing exact selected SNR harmonic columns.*3\.6000_Hz",
    ):
        build_publication_map_result(request)


def test_bca_maps_use_saved_processing_harmonic_cache(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
    )

    first = build_publication_map_result(request)
    group_policy.clear_group_significant_selection_cache()
    second = build_publication_map_result(request)

    assert first.selected_harmonics_hz == pytest.approx((1.2, 2.4, 3.6, 4.8, 7.2))
    assert second.selected_harmonics_hz == pytest.approx((1.2, 2.4, 3.6, 4.8, 7.2))
    assert second.selection_metadata["selection_cache_source"] == "saved_processing_metadata"


def test_bca_maps_require_processing_time_harmonic_selection(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(
        tmp_path,
        subjects=("S1",),
        persist_harmonics=False,
    )
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
    )

    with pytest.raises(
        CanonicalHarmonicSelectionError,
        match="No current processing-time harmonic selection",
    ):
        build_publication_map_result(request)


def test_worker_exports_only_nonblank_png_and_pdf_figures(tmp_path: Path) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    output_root = project_root / "4 - Scalp Maps"
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=output_root,
        conditions=("Faces",),
        project_root=project_root,
    )
    worker = PublicationMapsWorker(request)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert len(finished) == 1
    assert finished[0].status is PublicationMapsOutcomeStatus.SUCCESS
    figures = finished[0].results[0].figure_paths
    assert figures
    assert all(path.exists() and path.stat().st_size > 0 for path in figures)
    assert {path.suffix for path in figures} == {".pdf", ".png"}
    assert not list(output_root.rglob("*.xlsx"))
    pdf = next(path for path in figures if path.suffix == ".pdf")
    assert pdf.read_bytes().startswith(b"%PDF")
    assert not list(output_root.rglob("*.svg"))
    png = next(path for path in figures if path.suffix == ".png")
    with Image.open(png) as image:
        assert image.width == int(JOURNAL_TEXT_WIDTH_IN * request.png_dpi)


def test_fast_metric_reader_preserves_publication_map_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, excel_root = _write_project_workbooks(
        tmp_path,
        subjects=("S1", "S2"),
        conditions=("Faces", "Objects"),
    )
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces", "Objects"),
        project_root=project_root,
        metrics=(
            PublicationMetric.BCA,
            PublicationMetric.SNR,
            PublicationMetric.Z_SCORE,
        ),
        color_bounds={
            PublicationMetric.Z_SCORE: ColorBounds(vmin=DEFAULT_Z_SCORE_THRESHOLD),
        },
    )

    fast = build_publication_map_result(request)

    def pandas_reference_reader(
        excel_path: Path,
        *,
        sheet_name: str,
        required_columns: list[str],
    ) -> pd.DataFrame:
        return pd.read_excel(
            excel_path,
            sheet_name=sheet_name,
            usecols=list(required_columns),
        )

    monkeypatch.setattr(
        publication_map_metrics,
        "read_metric_sheet_selected_columns",
        pandas_reference_reader,
    )
    reference = build_publication_map_result(request)

    pd.testing.assert_frame_equal(
        fast.long_values,
        reference.long_values,
        check_dtype=False,
    )
    pd.testing.assert_frame_equal(
        fast.grand_average_values,
        reference.grand_average_values,
        check_dtype=False,
    )


def test_metric_collection_reads_only_selected_harmonic_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
        metrics=(
            PublicationMetric.BCA,
            PublicationMetric.SNR,
            PublicationMetric.Z_SCORE,
        ),
    )
    real_reader = publication_map_metrics.read_metric_sheet_selected_columns
    seen_columns: list[tuple[str, ...]] = []

    def tracking_reader(
        excel_path: Path,
        *,
        sheet_name: str,
        required_columns: list[str],
    ) -> pd.DataFrame:
        _ = sheet_name
        seen_columns.append(tuple(required_columns))
        return real_reader(
            excel_path,
            sheet_name=sheet_name,
            required_columns=required_columns,
        )

    monkeypatch.setattr(
        publication_map_metrics,
        "read_metric_sheet_selected_columns",
        tracking_reader,
    )

    result = build_publication_map_result(request)

    assert not any(diag.level == "error" for diag in result.diagnostics)
    assert seen_columns == [
        ("Electrode", "1.2000_Hz", "2.4000_Hz", "3.6000_Hz", "4.8000_Hz", "7.2000_Hz"),
        ("Electrode", "1.2000_Hz", "2.4000_Hz", "3.6000_Hz", "4.8000_Hz", "7.2000_Hz"),
        ("Electrode", "1.2000_Hz", "2.4000_Hz", "3.6000_Hz", "4.8000_Hz", "7.2000_Hz"),
    ]


def test_metric_collection_does_not_use_pandas_excel_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root, excel_root = _write_project_workbooks(tmp_path, subjects=("S1",))
    request = PublicationMapRequest(
        input_root=excel_root,
        output_root=project_root / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=project_root,
        metrics=(PublicationMetric.BCA,),
    )

    def fail_read_excel(*_args, **_kwargs):
        raise AssertionError("Publication Maps metric collection should use the XML reader")

    monkeypatch.setattr(pd, "read_excel", fail_read_excel)

    result = build_publication_map_result(request)

    assert result.long_values["metric"].unique().tolist() == [PublicationMetric.BCA.value]
    assert not any(diag.level == "error" for diag in result.diagnostics)


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
        project_root=project_root,
        metrics=(PublicationMetric.BCA, PublicationMetric.SNR),
        export_paired_figures=True,
        paired_conditions=("Objects", "Faces"),
    )
    result = build_publication_map_result(request)

    figures = render_publication_figures(result, request)

    paired = [path for path in figures if "_and_" in path.stem]
    assert len(figures) == 2
    assert figures == paired
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
    assert len(figures) == 2
    assert figures == paired
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


def test_paired_headers_and_colorbar_label_are_bold_but_ticks_are_not() -> None:
    header_font = _paired_condition_title_kwargs()
    legend_font = _colorbar_text_kwargs()

    assert header_font["fontfamily"] == FIGURE_FONT_FAMILY
    assert header_font["fontsize"] == FIGURE_PANEL_LABEL_SIZE_PT
    assert header_font["fontweight"] == "bold"
    assert legend_font["fontfamily"] == FIGURE_FONT_FAMILY
    assert legend_font["fontsize"] == FIGURE_TEXT_SIZE_PT
    assert legend_font["fontweight"] == "bold"

    fig, ax = plt.subplots()
    try:
        image = ax.imshow(np.asarray([[0.0, 1.0], [1.0, 0.0]]))
        cbar = fig.colorbar(image, ax=ax)

        _style_colorbar(cbar, metric=PublicationMetric.SNR)

        assert cbar.ax.yaxis.label.get_fontweight() == "bold"
        assert all(
            tick_label.get_fontweight() == "normal"
            for tick_label in cbar.ax.get_yticklabels()
            if tick_label.get_text()
        )
    finally:
        plt.close(fig)


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

    def fake_build(
        seen_request: PublicationMapRequest,
        *,
        cancel_check,
    ) -> PublicationMapResult:
        assert seen_request is request
        cancel_check()
        calls.append("build")
        return result

    def fake_render(
        seen_result: PublicationMapResult,
        seen_request: PublicationMapRequest,
        *,
        cancel_check,
        transaction,
    ) -> list[Path]:
        assert seen_result is result
        assert seen_request is request
        assert transaction is not None
        cancel_check()
        calls.append("render")
        return [seen_request.output_root / "Faces_bca_BCA_significant-harmonic_sum.pdf"]

    def fake_verify(seen_workbooks, *, cancel_check) -> None:
        assert seen_workbooks == result.included_workbooks
        cancel_check()
        calls.append("verify")

    class FakeTransaction:
        def __init__(self, seen_request: PublicationMapRequest) -> None:
            assert seen_request is request

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def ensure_request_target(self, seen_request: PublicationMapRequest) -> None:
            assert seen_request is request

        def commit(self, *, cancel_check) -> None:
            cancel_check()
            calls.append("commit")

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fake_build,
    )
    monkeypatch.setattr("Tools.Publication_Maps.worker.render_publication_figures", fake_render)
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.verify_publication_workbooks_unchanged",
        fake_verify,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.PublicationArtifactTransaction",
        FakeTransaction,
    )

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

    assert calls == ["build", "render", "verify", "commit"]
    assert progress == [5, 55, 95, 100]
    assert messages == [
        "[Ungrouped dataset] Reading indexed workbooks...",
        "[Ungrouped dataset] Rendering scalp maps...",
        "[Ungrouped dataset] Figure output staged.",
        "Publishing the complete Scalp Maps figure set...",
    ]
    assert errors == []
    assert len(finished) == 1
    assert finished[0].status is PublicationMapsOutcomeStatus.SUCCESS
    assert finished[0].results == (result,)


def test_worker_rejects_distinct_groups_sharing_an_output_directory(
    tmp_path: Path,
) -> None:
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
        group_id="control",
        group_label="Control",
        group_folder="Shared",
    )

    with pytest.raises(ValueError, match="unique output directories"):
        PublicationMapsWorker(
            (
                request,
                replace(
                    request,
                    group_id="clinical",
                    group_label="Clinical",
                ),
            )
        )


def test_worker_commit_wins_when_cancel_arrives_after_publication(
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
    worker_holder: list[PublicationMapsWorker] = []

    def fake_build(_request, *, cancel_check):
        cancel_check()
        return result

    def fake_render(_result, _request, *, cancel_check, transaction):
        cancel_check()
        assert transaction is not None
        return [request.output_root / "Faces.pdf"]

    class CommitThenCancelTransaction:
        def __init__(self, _request) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def ensure_request_target(self, _request) -> None:
            return None

        def commit(self, *, cancel_check) -> None:
            cancel_check()
            worker_holder[0].cancel()

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fake_build,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.render_publication_figures",
        fake_render,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.PublicationArtifactTransaction",
        CommitThenCancelTransaction,
    )

    worker = PublicationMapsWorker(request)
    worker_holder.append(worker)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert len(finished) == 1
    assert finished[0].status is PublicationMapsOutcomeStatus.SUCCESS
    assert finished[0].results == (result,)


def test_worker_does_not_publish_when_no_figure_is_renderable(
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

    def fake_build(_request, *, cancel_check):
        cancel_check()
        return result

    def fake_render(_result, _request, *, cancel_check, transaction):
        cancel_check()
        assert transaction is not None
        calls.append("render")
        return []

    class FakeTransaction:
        def __init__(self, _request) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, *_args) -> None:
            assert exc_type is PublicationMapInputError
            calls.append("abort")

        def ensure_request_target(self, _request) -> None:
            return None

        def commit(self, **_kwargs) -> None:
            pytest.fail("A figureless transaction must not be committed.")

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fake_build,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.render_publication_figures",
        fake_render,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.PublicationArtifactTransaction",
        FakeTransaction,
    )
    worker = PublicationMapsWorker(request)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert calls == ["render", "abort"]
    assert len(finished) == 1
    assert finished[0].status is PublicationMapsOutcomeStatus.ERROR
    assert "No renderable scalp-map figures" in finished[0].message


def test_worker_emits_distinct_cancelled_outcome_before_work(tmp_path: Path) -> None:
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
    )
    worker = PublicationMapsWorker(request)
    finished: list[object] = []
    errors: list[str] = []
    worker.finished.connect(finished.append)
    worker.error.connect(errors.append)

    worker.cancel()
    worker.run()

    assert len(finished) == 1
    assert finished[0].status is PublicationMapsOutcomeStatus.CANCELLED
    assert finished[0].results == ()
    assert errors == []


@pytest.mark.parametrize(
    ("worker_error", "expected_status"),
    [
        (
            PublicationMapInputError("Requested workbook is corrupt."),
            PublicationMapsOutcomeStatus.ERROR,
        ),
        (
            CanonicalHarmonicSelectionError(
                "Saved harmonic selection is stale.",
                reason="missing_processing_selection",
            ),
            PublicationMapsOutcomeStatus.POST_PROCESSING_REQUIRED,
        ),
    ],
)
def test_worker_distinguishes_error_from_post_processing_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    worker_error: Exception,
    expected_status: PublicationMapsOutcomeStatus,
) -> None:
    request = PublicationMapRequest(
        input_root=tmp_path / "1 - Excel Data Files",
        output_root=tmp_path / "4 - Scalp Maps",
        conditions=("Faces",),
        project_root=tmp_path,
    )

    class FakeTransaction:
        def __init__(self, _request) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def ensure_request_target(self, _request) -> None:
            return None

    def fail_build(_request, *, cancel_check):
        cancel_check()
        raise worker_error

    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.PublicationArtifactTransaction",
        FakeTransaction,
    )
    monkeypatch.setattr(
        "Tools.Publication_Maps.worker.build_publication_map_result",
        fail_build,
    )
    worker = PublicationMapsWorker(request)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert len(finished) == 1
    assert finished[0].status is expected_status
    assert finished[0].message == str(worker_error)
    if expected_status is PublicationMapsOutcomeStatus.POST_PROCESSING_REQUIRED:
        assert finished[0].project_root == str(tmp_path.resolve(strict=False))


def _write_project_workbooks(
    tmp_path: Path,
    *,
    subjects: tuple[str, ...],
    conditions: tuple[str, ...] = ("Faces",),
    persist_harmonics: bool = True,
) -> tuple[Path, Path]:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {
                    condition: index for index, condition in enumerate(conditions, start=1)
                },
                "participants": {subject: {} for subject in subjects},
                "preprocessing": {},
            },
            indent=2,
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
    if persist_harmonics:
        harmonic_selection_qc.run_processing_harmonic_selection_qc(Project.load(project_root))
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
            f"{freq:.4f}_Hz": [value, value, value, value]
            for freq, value in zip(frequency_values, fft_values)
        },
        index=["O1", "O2", "FZ", "F3"],
    )
    full_fft.index.name = "Electrode"

    bca = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5 * scale, 0.25 * scale],
            "2.4000_Hz": [100.0, 100.0, 100.0, 100.0],
            "3.6000_Hz": [0.5, 0.5, 0.1, 0.1],
            "4.8000_Hz": [100.0, 100.0, 100.0, 100.0],
            "6.0000_Hz": [100.0, 100.0, 100.0, 100.0],
            "7.2000_Hz": [1.0, 1.0, 0.1, 0.1],
        },
        index=["O1", "O2", "FZ", "F3"],
    )
    bca.index.name = "Electrode"
    snr = pd.DataFrame(
        {
            "1.2000_Hz": [
                1.0 + 0.1 * scale,
                1.2 + 0.1 * scale,
                1.4 + 0.1 * scale,
                1.1 + 0.1 * scale,
            ],
            "2.4000_Hz": [9.0, 9.0, 9.0, 9.0],
            "3.6000_Hz": [
                1.2 + 0.1 * scale,
                1.4 + 0.1 * scale,
                1.6 + 0.1 * scale,
                1.3 + 0.1 * scale,
            ],
            "4.8000_Hz": [9.0, 9.0, 9.0, 9.0],
            "6.0000_Hz": [9.0, 9.0, 9.0, 9.0],
            "7.2000_Hz": [
                1.4 + 0.1 * scale,
                1.6 + 0.1 * scale,
                1.8 + 0.1 * scale,
                1.5 + 0.1 * scale,
            ],
        },
        index=["O1", "O2", "FZ", "F3"],
    )
    snr.index.name = "Electrode"
    z_score = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5 * scale, 0.25 * scale],
            "2.4000_Hz": [9.0, 9.0, 9.0, 9.0],
            "3.6000_Hz": [2.0, 1.0, 0.5, 0.25],
            "4.8000_Hz": [9.0, 9.0, 9.0, 9.0],
            "6.0000_Hz": [9.0, 9.0, 9.0, 9.0],
            "7.2000_Hz": [3.0, 2.0, 1.0, 0.5],
        },
        index=["O1", "O2", "FZ", "F3"],
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

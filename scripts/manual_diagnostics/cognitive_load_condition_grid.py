"""Render a signed, six-panel cognitive-load Summed BCA scalp-map figure.

Rows follow the three analyzed tasks; columns are no load and cognitive load.
Native Scalp Maps services own source validation, exact-harmonic summation,
participant averaging, and BioSemi64 geometry. Maps show all 64 scalp channels;
row p values are uncorrected paired ROI tests. Occipital is O1, Oz, and O2;
an optional separately analyzed Frontal endpoint adds a second labeled test.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import sys

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.ticker import MaxNLocator
import numpy as np
from PIL import Image

from cognitive_load_plot import file_hash, read_inputs

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

LOGGER = logging.getLogger(__name__)
VERSION = "cognitive_load_signed_condition_grid_v1"
TASK_LABELS = {
    "Semantic Categories": "Semantic\ncategories",
    "Recognition Memory": "Recognition\nmemory",
    "Angry Facial Expressions": "Angry facial\nexpressions",
}
FIGURE_SIZE_IN = (6.5, 7.0)


def render(analysis_directory: Path, frontal_analysis_directory: Path | None = None,
           output_directory: Path | None = None) -> Path:
    analysis = analysis_directory.expanduser().resolve(strict=True)
    results, plan, pairs, source_hashes = read_inputs(analysis)
    if results["endpoint"] != "Occipital":
        raise ValueError("This figure requires the new Occipital analysis; whole-scalp p values cannot be used.")
    roi_definitions = [row for row in plan["roi_snapshot"]["rois"] if row["name"] == "Occipital"]
    if (len(roi_definitions) != 1 or len(roi_definitions[0]["electrodes"]) != 3
            or set(roi_definitions[0]["electrodes"]) != {"O1", "Oz", "O2"}):
        raise ValueError("The frozen Occipital endpoint must contain exactly O1, Oz, and O2.")
    root = next(parent for parent in analysis.parents if (parent / "project.json").is_file())
    frontal_results, frontal_hashes, frontal_analysis = None, {}, None
    frontal_electrodes = []
    if frontal_analysis_directory is not None:
        frontal_analysis = frontal_analysis_directory.expanduser().resolve(strict=True)
        if not frontal_analysis.is_relative_to(root):
            raise ValueError("The Frontal analysis must belong to the same project.")
        frontal_results, frontal_plan, frontal_pairs, frontal_hashes = read_inputs(frontal_analysis)
        if frontal_results["endpoint"] != "Frontal":
            raise ValueError("The second analysis must use the exact frozen Frontal ROI.")
        for key in ("contrasts", "participants", "harmonics_hz", "roi_snapshot", "release_receipt"):
            if frontal_plan[key] != plan[key]:
                raise ValueError(f"ROI analyses have different frozen {key}.")
        if frontal_plan["harmonic_metadata"]["selection_fingerprint"] != plan["harmonic_metadata"]["selection_fingerprint"]:
            raise ValueError("ROI analyses use different harmonic selections.")
        expected_pairs = {task: {row["participant_id"] for row in rows} for task, rows in pairs}
        other_pairs = {task: {row["participant_id"] for row in rows} for task, rows in frontal_pairs}
        if other_pairs != expected_pairs:
            raise ValueError("ROI analyses have different paired participants.")
        definitions = [row for row in frontal_plan["roi_snapshot"]["rois"] if row["name"] == "Frontal"]
        if len(definitions) != 1 or not definitions[0]["electrodes"]:
            raise ValueError("A complete frozen Frontal electrode definition is required.")
        frontal_electrodes = definitions[0]["electrodes"]
    config = (root / plan["config_home"]).resolve(strict=True)
    if not config.is_relative_to(root):
        raise ValueError("Analysis configuration is outside its project root.")
    os.environ["FPVS_CONFIG_HOME"] = str(config)

    from Main_App.exports.figure_style import (
        FIGURE_EXPORT_DPI,
        FIGURE_FONT_FAMILY,
        FIGURE_OUTPUT_FORMATS,
        figure_text_kwargs,
        matplotlib_figure_rcparams,
    )
    from Main_App.projects import load_project_dataset_index
    from Tools.Publication_Maps.metrics import build_publication_map_result, verify_publication_workbooks_unchanged
    from Tools.Publication_Maps.models import ColorBounds, PublicationMapRequest, PublicationMetric
    from Tools.Publication_Maps.rendering import _draw_topomap

    index = load_project_dataset_index(root)
    if index.is_multi_group or index.is_repeated_session:
        raise ValueError("This study-specific figure requires one group and one recording per participant.")
    conditions = tuple(condition for contrast in plan["contrasts"]
                       for condition in (contrast["no_load"], contrast["load"]))
    if len(conditions) != 6 or len(set(conditions)) != 6:
        raise ValueError("Exactly six distinct canonical conditions are required.")
    output = (output_directory.expanduser().resolve() if output_directory else analysis / "condition_grid")
    if not output.is_relative_to(root):
        raise ValueError("The figure output must remain inside the active project.")
    if output.exists():
        raise FileExistsError(f"Figure destination already exists: {output}")
    request = PublicationMapRequest(
        input_root=index.excel_root, output_root=output, project_root=root,
        conditions=conditions, metrics=(PublicationMetric.BCA,), group_id=next(iter(index.groups), None),
    )
    mapped = build_publication_map_result(request)
    np.testing.assert_array_equal(mapped.selected_harmonics_hz, plan["harmonics_hz"])
    if mapped.selection_metadata.get("selection_fingerprint") != plan["harmonic_metadata"]["selection_fingerprint"]:
        raise ValueError("Scalp maps and paired tests have different canonical harmonic selections.")
    grand = mapped.grand_average_values.copy()
    grand = grand.loc[grand["metric"].eq("bca") & grand["is_montage_electrode"]].copy()
    if len(grand) != 384 or grand.duplicated(["condition", "electrode"]).any():
        raise ValueError("The six maps require one unique grand mean for each of 64 scalp electrodes.")
    expected_cohorts = {task: {row["participant_id"] for row in task_pairs} for task, task_pairs in pairs}
    for contrast in plan["contrasts"]:
        expected = expected_cohorts[contrast["task"]]
        for condition in (contrast["no_load"], contrast["load"]):
            observed = {entry.subject_id for entry in mapped.included_workbooks if entry.condition == condition}
            cells = grand.loc[grand["condition"].eq(condition)]
            if observed != expected or len(cells) != 64 or not cells["valid_subject_count"].eq(len(expected)).all():
                raise ValueError(f"Map cohort or complete sensor coverage differs from paired analysis: {condition}.")
    signed = grand["aggregate_value"].to_numpy(dtype=float)
    if not np.isfinite(signed).all():
        raise ValueError("Signed grand-average sensor values must all be finite.")
    # Native BCA defaults clip the display at zero. The requested signed figure
    # passes unchanged aggregate values and an explicit symmetric display scale.
    grand["render_value"] = grand["aggregate_value"]
    limit = float(np.max(np.abs(signed)))
    if limit == 0:
        raise ValueError("All six maps are exactly zero; a data-derived signed color scale is undefined.")
    limits = (-limit, limit)
    bounds = ColorBounds(auto_scale=False, vmin=limits[0], vmax=limits[1])
    font_path = findfont(FontProperties(family=FIGURE_FONT_FAMILY, weight="bold"), fallback_to_default=False)
    style = matplotlib_figure_rcparams()
    style.update({"font.weight": "bold", "axes.labelweight": "bold", "axes.titleweight": "bold"})
    text_style = {**figure_text_kwargs("annotation"), "fontweight": "bold"}
    comparisons = {row["task"]: row for row in results["comparisons"]}
    frontal_comparisons = ({row["task"]: row for row in frontal_results["comparisons"]}
                          if frontal_results is not None else {})
    output.mkdir(exist_ok=False)
    files = {}
    with mpl.rc_context(style):
        figure = Figure(figsize=FIGURE_SIZE_IN, dpi=FIGURE_EXPORT_DPI)
        FigureCanvasAgg(figure)
        for x, title in ((0.3675, "No load"), (0.6625, "Load")):
            figure.text(x, 0.96, title, ha="center", va="center", **text_style)
        image = None
        for row_index, contrast in enumerate(plan["contrasts"]):
            bottom = (0.68, 0.385, 0.09)[row_index]
            center = bottom + 0.1175
            task = contrast["task"]
            p_value = float(comparisons[task]["p_raw"])
            figure.text(0.025, center + (0.045 if frontal_results else 0.028), TASK_LABELS.get(task, task),
                        ha="left", va="center", linespacing=1.25, **text_style)
            figure.text(0.025, center - 0.043, f"Occipital p = {p_value:.3f}" if frontal_results else f"p = {p_value:.3f}",
                        ha="left", va="center", **text_style)
            if frontal_results:
                frontal_p = float(frontal_comparisons[task]["p_raw"])
                figure.text(0.025, center - 0.078, f"Frontal p = {frontal_p:.3f}",
                            ha="left", va="center", **text_style)
            for column, condition in enumerate((contrast["no_load"], contrast["load"])):
                axis = figure.add_axes([(0.24, 0.535)[column], bottom, 0.255, 0.235])
                cells = grand.loc[grand["condition"].eq(condition)]
                image, missing = _draw_topomap(
                    cells, ax=axis, metric=PublicationMetric.BCA,
                    cmap=mpl.colormaps["RdBu_r"], bounds=bounds, vlim_override=limits,
                )
                if missing:
                    raise ValueError(f"Missing map sensors despite complete released coverage: {condition}.")
                axis.set_axis_off()
        color_axis = figure.add_axes([0.845, 0.205, 0.022, 0.57])
        colorbar = figure.colorbar(image, cax=color_axis)
        colorbar.locator = MaxNLocator(nbins=5, symmetric=True)
        colorbar.update_ticks()
        colorbar.set_label("Summed baseline-corrected amplitude (µV)", **text_style)
        colorbar.ax.tick_params(labelsize=10, width=0.7, length=3)
        for tick in colorbar.ax.get_yticklabels():
            tick.set_fontfamily(FIGURE_FONT_FAMILY)
            tick.set_fontweight("bold")
            tick.set_fontsize(10)
        sample_sizes = sorted({len(cohort) for cohort in expected_cohorts.values()})
        n_label = str(sample_sizes[0]) if len(sample_sizes) == 1 else ", ".join(map(str, sample_sizes))
        if frontal_results:
            figure.text(0.5, 0.043, f"Paired ROI p values, uncorrected; n = {n_label}",
                        ha="center", va="center", **text_style)
            figure.text(0.5, 0.018, "Occipital: O1, Oz, O2 | Frontal: " + ", ".join(frontal_electrodes),
                        ha="center", va="center", **text_style)
        else:
            figure.text(0.5, 0.025, f"Paired occipital ROI p values (O1, Oz, O2), uncorrected; n = {n_label}",
                        ha="center", va="center", **text_style)
        for extension in FIGURE_OUTPUT_FORMATS:
            path = output / f"cognitive_load_signed_scalp_grid.{extension}"
            figure.savefig(path, format=extension, dpi=FIGURE_EXPORT_DPI, facecolor="white")
            files[path.name] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
        figure.clear()
    png = output / "cognitive_load_signed_scalp_grid.png"
    with Image.open(png) as raster:
        pixels, dpi = raster.size, raster.info.get("dpi")
    if pixels != tuple(int(value * FIGURE_EXPORT_DPI) for value in FIGURE_SIZE_IN):
        raise AssertionError("The PNG dimensions differ from its intended physical size.")
    if dpi is None or not np.allclose(dpi, FIGURE_EXPORT_DPI, atol=0.02, rtol=0):
        raise AssertionError("The PNG does not contain 600-dpi resolution metadata.")
    verify_publication_workbooks_unchanged(mapped.included_workbooks)
    for name, digest in source_hashes.items():
        if file_hash(analysis / name) != digest:
            raise RuntimeError(f"Analysis source changed during rendering: {name}.")
    for name, digest in frontal_hashes.items():
        if file_hash(frontal_analysis / name) != digest:
            raise RuntimeError(f"Frontal analysis source changed during rendering: {name}.")
    csv = output / "signed_grand_average_sensor_values.csv"
    grand.to_csv(csv, index=False)
    files[csv.name] = {"sha256": file_hash(csv), "bytes": csv.stat().st_size}
    source_csv = output / "participant_harmonic_sensor_values.csv"
    mapped.long_values.to_csv(source_csv, index=False)
    files[source_csv.name] = {"sha256": file_hash(source_csv), "bytes": source_csv.stat().st_size}
    receipt = {
        "version": VERSION, "created_utc": datetime.now(UTC).isoformat(),
        "source_hashes": source_hashes, "script_sha256": file_hash(Path(__file__)),
        "domain_selection_note": results.get("domain_selection_note", ""),
        "harmonics_hz": mapped.selected_harmonics_hz,
        "selection_fingerprint": mapped.selection_metadata.get("selection_fingerprint"),
        "figure_size_inches": FIGURE_SIZE_IN, "png_pixels": pixels, "png_dpi": dpi,
        "font_family": FIGURE_FONT_FAMILY, "font_weight": "bold", "font_size_pt": 10,
        "resolved_font": Path(font_path).name, "common_signed_limits_uv": limits,
        "aggregation": "Native Scalp Maps: exact canonical BCA sum within participant/electrode, then participant mean",
        "display": "Unchanged signed grand means; symmetric RdBu_r scale shared by all six panels; native scalp interpolation",
        "inference": "Uncorrected two-sided paired ROI tests; no electrode-wise or spatial inference",
        "inference_endpoint": "Occipital", "inference_electrodes": ["O1", "Oz", "O2"],
        "frontal_analysis": str(frontal_analysis) if frontal_analysis else None,
        "frontal_source_hashes": frontal_hashes, "frontal_electrodes": frontal_electrodes,
        "map_electrode_scope": "All 64 canonical BioSemi64 scalp electrodes",
        "row_tests": [{"task": task, "n": int(row["N_Pairs"]), "p_uncorrected": row["p_raw"],
                       "p_holm": row["p_adjusted"]} for task, row in comparisons.items()],
        "frontal_row_tests": [{"task": task, "n": int(row["N_Pairs"]), "p_uncorrected": row["p_raw"],
                               "p_holm": row["p_adjusted"]} for task, row in frontal_comparisons.items()],
        "qc_provenance": mapped.qc_provenance,
        "diagnostics": [diagnostic.to_row() for diagnostic in mapped.diagnostics],
        "interpolation_note": "Processing-repaired electrodes, including C4 where released, remain included; no further EEG repair is performed.",
        "files": files,
    }
    (output / "figure_provenance.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    LOGGER.info("Signed six-panel scalp figure saved to %s", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", required=True, type=Path)
    parser.add_argument("--frontal-analysis-dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        render(args.analysis_dir, args.frontal_analysis_dir, args.output_dir)
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError):
        LOGGER.exception("Signed scalp grid did not complete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

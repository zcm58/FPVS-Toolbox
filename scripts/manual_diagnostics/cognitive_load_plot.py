"""Render three task panels from a completed cognitive-load paired analysis.

Only finite, eligible participant pairs recorded in results.json are plotted.
Matching Arial PDF/600-dpi PNG files and a checksum receipt are saved beside
the analysis. The renderer performs no additional inference or data selection.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
import sys

import matplotlib as mpl
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.ticker import MaxNLocator
import numpy as np
from PIL import Image

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Main_App.exports.figure_style import (  # noqa: E402
    FIGURE_EXPORT_DPI,
    FIGURE_FONT_FAMILY,
    FIGURE_JOURNAL_TEXT_WIDTH_IN,
    FIGURE_OUTPUT_FORMATS,
    apply_axis_text_style,
    figure_text_kwargs,
    matplotlib_figure_rcparams,
)

LOGGER = logging.getLogger(__name__)
VERSION = "cognitive_load_paired_figure_v1"
TASK_LABELS = {
    "Semantic Categories": "Semantic\ncategories",
    "Recognition Memory": "Recognition\nmemory",
    "Angry Facial Expressions": "Angry facial\nexpressions",
}
FIGURE_SIZE_IN = (FIGURE_JOURNAL_TEXT_WIDTH_IN, 3.2)


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_inputs(analysis: Path) -> tuple[dict, dict, list[tuple[str, list[dict]]], dict]:
    if not any((parent / "project.json").is_file() for parent in analysis.parents):
        raise ValueError("The analysis directory must be inside a Toolbox project root.")
    result_path, plan_path = analysis / "results.json", analysis / "analysis_plan.json"
    hashes = {path.name: file_hash(path) for path in (result_path, plan_path)}
    results = json.loads(result_path.read_text(encoding="utf-8"))
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if (results.get("status") != "completed" or results.get("crosscheck_passed") is not True
            or results.get("holm_crosscheck") != "passed"):
        raise ValueError("Figure input must be a completed, cross-checked paired analysis.")
    if results.get("analysis_plan_sha256") != hashes["analysis_plan.json"]:
        raise ValueError("The analysis plan differs from the completed result's checksum.")
    if results.get("endpoint") != plan.get("endpoint"):
        raise ValueError("Result and plan endpoints disagree.")
    tasks = [row["task"] for row in plan["contrasts"]]
    if len(tasks) != 3 or len(set(tasks)) != 3:
        raise ValueError("Exactly three distinct task panels are required.")
    comparisons = {row["task"]: row for row in results["comparisons"]}
    if len(comparisons) != 3 or set(comparisons) != set(tasks):
        raise ValueError("Result comparisons differ from the declared three tasks.")
    panels = []
    for task in tasks:
        pairs = [row for row in results["participant_pairs"]
                 if row["task"] == task and row.get("included_pair") is True]
        identifiers = [row["participant_id"] for row in pairs]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"Duplicate plotted participant in {task!r}.")
        expected = comparisons[task]
        if len(pairs) != int(expected["N_Pairs"]) or set(identifiers) != set(expected["included_participants"]):
            raise ValueError(f"Plotted pairs disagree with the analyzed cohort for {task!r}.")
        for row in pairs:
            if row.get("load_excluded") is not False or row.get("no_load_excluded") is not False:
                raise ValueError(f"An included pair carries a Toolbox exclusion in {task!r}.")
            if not np.isfinite([row["no_load_uv"], row["load_uv"]]).all():
                raise ValueError(f"A plotted pair is nonfinite in {task!r}.")
        panels.append((task, pairs))
    if not any(pairs for _, pairs in panels):
        raise ValueError("No eligible finite participant pairs are available to plot.")
    return results, plan, panels, hashes


def render(analysis_directory: Path) -> Path:
    analysis = analysis_directory.expanduser().resolve(strict=True)
    results, plan, panels, source_hashes = read_inputs(analysis)
    # Missing Arial is explicit; a silently substituted font would violate the figure contract.
    font_path = findfont(FontProperties(family=FIGURE_FONT_FAMILY), fallback_to_default=False)
    output = analysis / "figure"
    output.mkdir(exist_ok=False)
    base = output / "cognitive_load_paired"
    values = np.asarray([row[field] for _, pairs in panels for row in pairs
                         for field in ("no_load_uv", "load_uv")], dtype=float)
    low, high = min(0.0, float(values.min())), max(0.0, float(values.max()))
    span = high - low or 0.1
    limits = (low - 0.08 * span, high + 0.22 * span)
    files = {}
    with mpl.rc_context(matplotlib_figure_rcparams()):
        figure = Figure(figsize=FIGURE_SIZE_IN, dpi=FIGURE_EXPORT_DPI)
        FigureCanvasAgg(figure)
        axes = figure.subplots(1, 3, sharey=True)
        figure.subplots_adjust(left=0.11, right=0.99, bottom=0.18, top=0.77, wspace=0.2)
        for index, (axis, (task, pairs)) in enumerate(zip(axes, panels, strict=True)):
            for row in pairs:
                axis.plot([0, 1], [row["no_load_uv"], row["load_uv"]],
                          color="#456C80", marker="o", markersize=4, linewidth=0.9, alpha=0.85)
            axis.set(xlim=(-0.2, 1.2), ylim=limits, xticks=[0, 1], xticklabels=["No load", "Load"])
            axis.set_title(TASK_LABELS.get(task, task), pad=10, **figure_text_kwargs("condition_label"))
            axis.text(-0.13, 1.13, "ABC"[index], transform=axis.transAxes,
                      **figure_text_kwargs("panel_label"))
            axis.text(0.5, 0.96, f"n = {len(pairs)}", transform=axis.transAxes,
                      ha="center", va="top", **figure_text_kwargs("annotation"))
            axis.spines[["top", "right"]].set_visible(False)
            axis.spines[["left", "bottom"]].set_linewidth(0.7)
            axis.tick_params(width=0.7, length=3)
            axis.set_axisbelow(True)
            axis.grid(axis="y", color="#D9DFE2", linewidth=0.5)
            axis.yaxis.set_major_locator(MaxNLocator(nbins=5))
            apply_axis_text_style(axis)
        axes[0].set_ylabel("Summed BCA (µV)", **figure_text_kwargs("axis_label"))
        for extension in FIGURE_OUTPUT_FORMATS:
            path = base.with_suffix(f".{extension}")
            figure.savefig(path, format=extension, dpi=FIGURE_EXPORT_DPI, facecolor="white")
            files[path.name] = {"sha256": file_hash(path), "bytes": path.stat().st_size}
        figure.clear()
    with Image.open(base.with_suffix(".png")) as raster:
        expected_pixels = tuple(int(inches * FIGURE_EXPORT_DPI) for inches in FIGURE_SIZE_IN)
        if raster.size != expected_pixels:
            raise AssertionError(f"Unexpected PNG dimensions: {raster.size!r}.")
        png_dpi = raster.info.get("dpi")
        if png_dpi is None or not np.allclose(png_dpi, FIGURE_EXPORT_DPI, atol=0.02, rtol=0):
            raise AssertionError(f"Unexpected PNG DPI: {png_dpi!r}.")
    for name, digest in source_hashes.items():
        if file_hash(analysis / name) != digest:
            raise RuntimeError(f"Source {name} changed while rendering.")
    receipt = {
        "version": VERSION, "created_utc": datetime.now(UTC).isoformat(),
        "endpoint": results["endpoint"], "source_hashes": source_hashes,
        "domain_selection_note": results.get("domain_selection_note", ""),
        "source_export_sha256": plan["export_sha256"], "script_sha256": file_hash(Path(__file__)),
        "figure_size_inches": FIGURE_SIZE_IN, "png_pixels": expected_pixels, "png_dpi": png_dpi,
        "font_family": FIGURE_FONT_FAMILY, "resolved_font": Path(font_path).name,
        "common_y_limits_uv": limits, "condition_order": ["No load", "Load"],
        "plotted_pairs": [{"task": task, "n": len(pairs), "participants": pairs} for task, pairs in panels],
        "transformations": "None; plotted values are the eligible pairs in results.json",
        "files": files,
    }
    (output / "figure_provenance.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    LOGGER.info("Paired figure saved to %s", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis-dir", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        render(args.analysis_dir)
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError):
        LOGGER.exception("Paired figure did not complete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

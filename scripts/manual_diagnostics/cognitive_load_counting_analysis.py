"""Audit endpoint-based counting progress in the three cognitive-load sessions.

Only counting-report baseline/load_report rows are used; duplicated load_start
events are not observations. Estimates describe net endpoint progress, never
the number of actual correct subtractions. Studio sources remain unchanged.
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
import numpy as np
import pandas as pd
from PIL import Image

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Main_App.exports.figure_style import (  # noqa: E402
    FIGURE_EXPORT_DPI, FIGURE_FONT_FAMILY, FIGURE_OUTPUT_FORMATS,
    apply_axis_text_style, figure_text_kwargs, matplotlib_figure_rcparams,
)
from Main_App.projects import STATS_SUBFOLDER_NAME  # noqa: E402

LOGGER = logging.getLogger(__name__)
PARTICIPANTS = ("P1", "P2", "P3")
TASKS = {1: "Semantic Categories", 3: "Recognition Memory", 5: "Angry Facial Expressions"}
VERSION = "cognitive_load_counting_endpoint_audit_v1"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def collect(studio: Path) -> tuple[list[dict], dict[str, str]]:
    records, hashes = [], {}
    for participant in PARTICIPANTS:
        session = studio / "runs" / f"{participant}_session01"
        for response_path in sorted(session.glob("run-*/task_responses.jsonl")):
            spec_path = response_path.parent / "runspec.json"
            for path in (response_path, spec_path):
                hashes[str(path)] = digest(path)
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            condition = spec["condition"]
            for number, line in enumerate(response_path.read_text(encoding="utf-8").splitlines(), start=1):
                raw = json.loads(line)
                counting = raw.get("backward_counting") or {}
                role = counting.get("role")
                if raw.get("step_id") != "counting-report" or role not in {"baseline", "load_report"}:
                    continue
                code = int(condition["trigger_code"])
                if code not in TASKS or condition["name"] != f"{TASKS[code]} - Cognitive Load":
                    raise ValueError(f"Unexpected counting-report condition in {spec_path}.")
                start, endpoint, step = counting["start_number"], counting["endpoint"], counting["subtraction_step"]
                planned, observed = float(counting["interval_seconds"]), float(counting["observed_interval_seconds"])
                if any(not isinstance(value, int) for value in (start, endpoint, step)) or step != 13:
                    raise ValueError("This audited experiment requires integer endpoints and subtraction step 13.")
                if planned != (30.0 if role == "baseline" else 90.0) or not np.isfinite(observed) or observed <= 0:
                    raise ValueError("Unexpected planned or observed interval duration.")
                delta = start - endpoint
                implied_steps, remainder = delta / step, delta % step
                rate = implied_steps / planned
                checks = {
                    "estimated_steps": bool(np.isclose(implied_steps, counting["estimated_steps"], rtol=1e-12)),
                    "steps_per_second": bool(np.isclose(rate, counting["steps_per_second"], rtol=1e-12)),
                    "subtraction_remainder": remainder == counting["subtraction_remainder"],
                }
                if not all(checks.values()) or counting["duration_basis"] != "planned":
                    raise AssertionError("Recalculated endpoint progress differs from native stored estimates.")
                records.append({
                    "participant_id": participant, "modifier_id": raw["modifier"]["modifier_id"],
                    "role": role, "task": TASKS[code], "condition_name": condition["name"], "trigger_code": code,
                    "run_id": spec["run_id"], "source_path": str(response_path), "source_line": number,
                    "source_sha256": hashes[str(response_path)], "runspec_path": str(spec_path),
                    "runspec_sha256": hashes[str(spec_path)], "start_number": start, "endpoint": endpoint,
                    "subtraction_step": step, "planned_seconds": planned, "observed_seconds": observed,
                    "net_number_decrease": delta, "net_implied_steps": implied_steps,
                    "net_progress_rate_planned_per_second": rate,
                    "net_progress_rate_observed_per_second": implied_steps / observed,
                    "integer_remainder": remainder, "nonzero_remainder": remainder != 0,
                    "negative_net_progress": delta < 0, "interval_completed": counting["interval_completed"],
                    "valid": raw["valid"], "correct": raw["correct"], "score": raw["score"],
                    "timed_out": raw["timed_out"], "aborted": raw["aborted"],
                    "native_comparison_checks": checks, "raw_response": raw,
                })
    if len(records) != 12 or sum(row["role"] == "baseline" for row in records) != 3:
        raise ValueError("Expected exactly three baseline reports and nine load reports.")
    return records, hashes


def compare(records: list[dict]) -> list[dict]:
    baselines = {}
    for row in records:
        if row["role"] == "baseline":
            key = (row["participant_id"], row["modifier_id"])
            if key in baselines:
                raise ValueError(f"Ambiguous baseline for {key!r}.")
            baselines[key] = row
    comparisons = []
    for report in records:
        if report["role"] != "load_report":
            continue
        baseline = baselines[(report["participant_id"], report["modifier_id"])]
        baseline_rate = baseline["net_progress_rate_planned_per_second"]
        if baseline_rate <= 0:
            raise ValueError("A positive baseline net-progress rate is required for a ratio.")
        ratio = report["net_progress_rate_planned_per_second"] / baseline_rate
        observed_ratio = report["net_progress_rate_observed_per_second"] / baseline["net_progress_rate_observed_per_second"]
        native = report["raw_response"]["backward_counting"]
        np.testing.assert_allclose([baseline_rate, ratio],
                                   [native["baseline_steps_per_second"], native["baseline_rate_ratio"]],
                                   rtol=1e-12, atol=1e-14)
        flags_ok = all(row["valid"] is True and row["interval_completed"] is True
                       and row["timed_out"] is False and row["aborted"] is False for row in (report, baseline))
        interpretable = flags_ok and not report["negative_net_progress"]
        comparisons.append({
            **{key: value for key, value in report.items() if key not in {"raw_response", "native_comparison_checks"}},
            "baseline_source_path": baseline["source_path"], "baseline_source_line": baseline["source_line"],
            "baseline_start_number": baseline["start_number"], "baseline_endpoint": baseline["endpoint"],
            "baseline_planned_seconds": baseline["planned_seconds"], "baseline_observed_seconds": baseline["observed_seconds"],
            "baseline_net_implied_steps": baseline["net_implied_steps"], "baseline_net_progress_rate": baseline_rate,
            "baseline_integer_remainder": baseline["integer_remainder"],
            "percent_of_own_baseline_planned": 100 * ratio,
            "percent_of_own_baseline_observed_sensitivity": 100 * observed_ratio,
            "expected_90s_endpoint_at_baseline_net_rate": report["start_number"] - baseline_rate * 90 * report["subtraction_step"],
            "expected_endpoint_actual_duration_sensitivity": report["start_number"]
            - baseline["net_progress_rate_observed_per_second"] * report["observed_seconds"] * report["subtraction_step"],
            "native_baseline_ratio_check": True, "interpretable_net_progress": interpretable,
            "interpretation": ("Approximate net endpoint progress; actual correct subtractions unknown"
                               if interpretable else "Non-interpretable: endpoint increased or response/interval was incomplete"),
        })
    if len({(row["participant_id"], row["task"]) for row in comparisons}) != 9:
        raise ValueError("Expected exactly one load report per participant and task.")
    return sorted(comparisons, key=lambda row: (row["participant_id"], row["trigger_code"]))


def chart(rows: list[dict], output: Path) -> dict:
    findfont(FontProperties(family=FIGURE_FONT_FAMILY), fallback_to_default=False)
    size = (6.5, 3.3)
    plotted = [row["percent_of_own_baseline_planned"] for row in rows if row["interpretable_net_progress"]]
    ceiling = max(120, max(plotted) * 1.18)
    with mpl.rc_context(matplotlib_figure_rcparams()):
        figure = Figure(figsize=size, dpi=FIGURE_EXPORT_DPI)
        FigureCanvasAgg(figure)
        axes = figure.subplots(1, 3, sharey=True)
        figure.subplots_adjust(left=0.13, right=0.99, bottom=0.27, top=0.83, wspace=0.24)
        for axis, participant in zip(axes, PARTICIPANTS, strict=True):
            axis.axhline(100, color="#7A7A7A", linestyle="--", linewidth=0.8)
            for task_index, code in enumerate(TASKS):
                row = next(row for row in rows if row["participant_id"] == participant and row["trigger_code"] == code)
                if row["interpretable_net_progress"]:
                    value = row["percent_of_own_baseline_planned"]
                    axis.scatter(task_index, value, color="#225D79", s=28, zorder=3)
                    axis.annotate(f"{value:.1f}%", (task_index, value), xytext=(0, 7), textcoords="offset points",
                                  ha="center", **figure_text_kwargs("annotation"))
                else:
                    axis.text(task_index, 0.06, "Not\ninterpretable", transform=axis.get_xaxis_transform(),
                              ha="center", va="bottom", **figure_text_kwargs("small"))
            axis.set(xlim=(-0.45, 2.45), ylim=(0, ceiling), xticks=[0, 1, 2],
                     xticklabels=["Semantic", "Memory", "Faces"])
            axis.set_title(participant, **figure_text_kwargs("panel_label"))
            axis.spines[["top", "right"]].set_visible(False)
            apply_axis_text_style(axis)
            for tick in axis.get_xticklabels():
                tick.set_rotation(30)
                tick.set_horizontalalignment("right")
        axes[0].set_ylabel("Net progress rate\n(% of own baseline)", **figure_text_kwargs("axis_label"))
        for extension in FIGURE_OUTPUT_FORMATS:
            figure.savefig(output / f"counting_net_progress.{extension}", dpi=FIGURE_EXPORT_DPI, facecolor="white")
        figure.clear()
    with Image.open(output / "counting_net_progress.png") as raster:
        pixels, dpi = raster.size, raster.info.get("dpi")
    if pixels != tuple(int(inches * FIGURE_EXPORT_DPI) for inches in size) or not np.allclose(dpi, 600, atol=0.02):
        raise AssertionError("Counting chart physical dimensions or DPI are incorrect.")
    return {"size_inches": size, "png_pixels": pixels, "png_dpi": dpi,
            "excluded_from_plot": [{"participant_id": row["participant_id"], "task": row["task"]}
                                   for row in rows if not row["interpretable_net_progress"]]}


def run(studio_root: Path, project_root: Path) -> Path:
    studio, root = studio_root.expanduser().resolve(strict=True), project_root.expanduser().resolve(strict=True)
    if not (root / "project.json").is_file():
        raise ValueError("--project-root must contain the processed Toolbox project manifest.")
    records, hashes = collect(studio)
    comparisons = compare(records)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = root / STATS_SUBFOLDER_NAME / "Cognitive Load Counting" / stamp
    output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(comparisons).to_csv(output / "load_vs_baseline.csv", index=False)
    flat = [{**{key: value for key, value in row.items() if key not in {"raw_response", "native_comparison_checks"}},
             "raw_response_json": json.dumps(row["raw_response"], ensure_ascii=False),
             "native_checks_json": json.dumps(row["native_comparison_checks"])} for row in records]
    pd.DataFrame(flat).to_csv(output / "counting_reports_all12.csv", index=False)
    figure_receipt = chart(comparisons, output)
    for name, original in hashes.items():
        if digest(Path(name)) != original:
            raise RuntimeError(f"Studio source changed during analysis: {name}")
    evidence = {
        "version": VERSION, "created_utc": stamp, "status": "completed", "source_hashes": hashes,
        "script_sha256": digest(Path(__file__)), "reports": records, "load_vs_baseline": comparisons,
        "checks": {"report_count": len(records), "baseline_count": 3, "load_report_count": len(comparisons),
                   "native_estimates_and_ratios_match": True,
                   "nonzero_remainder_count": sum(row["nonzero_remainder"] for row in records),
                   "negative_net_progress_count": sum(row["negative_net_progress"] for row in records)},
        "definitions": {"net_implied_steps": "(start_number - endpoint) / subtraction_step",
                        "planned_rate": "net_implied_steps / interval_seconds",
                        "percent_baseline": "100 * own load planned_rate / own baseline planned_rate",
                        "observed_sensitivity": "Use each interval's observed seconds in both rates",
                        "expected_endpoint": "load start - own baseline net rate * 90 seconds * subtraction step"},
        "limitations": [
            "All estimates describe net endpoint progress, not actual correct subtractions or error rates.",
            "Nonzero remainders are inconsistent with an error-free fixed-step sequence; endpoint records cannot locate or count errors.",
            "Response valid=true and interval_completed=true do not establish arithmetic accuracy; native correct fields are null.",
            "P3 angry-face endpoint increases from 391 to 394 and is non-interpretable as backward-counting performance; its negative arithmetic estimate remains in the tables.",
            "A very low baseline net-progress rate, particularly P3, makes percentage ratios sensitive to endpoint errors.",
            "No additional hypothesis tests or causal claims are made.",
        ],
        "figure": figure_receipt,
        "output_hashes": {path.name: digest(path) for path in output.iterdir() if path.is_file()},
    }
    write_json(output / "results.json", evidence)
    LOGGER.info("Counting endpoint evidence saved to %s", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studio-project-root", required=True, type=Path)
    parser.add_argument("--project-root", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("fontTools.subset").setLevel(logging.WARNING)
    try:
        run(args.studio_project_root, args.project_root)
    except (OSError, RuntimeError, ValueError, KeyError, AssertionError):
        LOGGER.exception("Counting endpoint analysis did not complete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

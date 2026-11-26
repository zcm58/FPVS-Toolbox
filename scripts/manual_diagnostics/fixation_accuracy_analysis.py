"""Compare fixation-target hit rates between cognitive-load conditions.

The outcome is hits / presented targets, with false alarms retained separately.
Three exploratory participant-paired t tests share one Holm family independent
of the EEG analyses. Trials are not pooled as independent participants.
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
from scipy import stats

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from Main_App.exports.figure_style import (  # noqa: E402
    FIGURE_EXPORT_DPI, FIGURE_FONT_FAMILY, FIGURE_OUTPUT_FORMATS,
    apply_axis_text_style, figure_legend_kwargs, figure_text_kwargs, matplotlib_figure_rcparams,
)
from Main_App.projects import STATS_SUBFOLDER_NAME  # noqa: E402
from Tools.Stats.analysis.inference_contracts import FamilySpec  # noqa: E402
from Tools.Stats.analysis.multiple_comparisons import apply_family_correction  # noqa: E402
from Tools.Stats.analysis.posthoc_tests import run_posthoc_pairwise_tests  # noqa: E402

LOGGER = logging.getLogger(__name__)
PARTICIPANTS = ("P1", "P2", "P3")
TASKS = ("Semantic Categories", "Recognition Memory", "Angry Facial Expressions")
VERSION = "cognitive_load_fixation_hit_rate_v1"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clean_json(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def collect(studio: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    rows, hashes = [], {}
    for participant in PARTICIPANTS:
        for path in sorted((studio / "runs" / f"{participant}_session01").glob("run-*/run_summary.json")):
            spec_path = path.parent / "runspec.json"
            for source in (path, spec_path):
                hashes[str(source)] = digest(source)
            summary = json.loads(path.read_text(encoding="utf-8"))
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            code = int(spec["condition"]["trigger_code"])
            if code not in range(1, 7):
                raise ValueError(f"Unexpected trigger code: {code}.")
            task, load = TASKS[(code - 1) // 2], code % 2 == 1
            condition = "Load" if load else "No load"
            expected_name = f"{task} - {'Cognitive Load' if load else 'No Load'}"
            if spec["condition"]["name"] != expected_name or summary["condition_name"] != expected_name:
                raise ValueError(f"Native condition-name/code disagreement in {path}.")
            if str(summary["participant_number"]) != participant[1:]:
                raise ValueError(f"Participant identity disagrees with selected session: {path}.")
            native = summary["fixation_task_summary"]
            targets, hits, misses, false_alarms = (int(native[key]) for key in
                                                 ("total_targets", "hit_count", "miss_count", "false_alarm_count"))
            onsets, responses, presses = (summary[key] for key in
                                          ("fixation_target_onsets", "fixation_responses", "response_log"))
            if len({row["event_index"] for row in onsets}) != len(onsets):
                raise ValueError("Duplicate target indices require explicit review.")
            if len({row["event_index"] for row in responses}) != len(responses):
                raise ValueError("Duplicate scored fixation-target indices require explicit review.")
            if len({row["response_index"] for row in presses}) != len(presses):
                raise ValueError("Duplicate press indices require explicit review.")
            checked = (len(onsets), sum(row["outcome"] == "hit" for row in responses),
                       sum(row["outcome"] == "miss" for row in responses),
                       sum(row["outcome"] == "false_alarm" for row in presses))
            if checked != (targets, hits, misses, false_alarms) or hits + misses != targets or targets <= 0:
                raise AssertionError(f"Native fixation counts disagree with trial records: {path}.")
            percent = 100 * hits / targets
            np.testing.assert_allclose(percent, native["accuracy_percent"], rtol=1e-12, atol=1e-12)
            complete = (summary["aborted"] is False and summary["task_flow_completed"] is True
                        and summary["task_flow_aborted"] is False)
            if not complete:
                raise ValueError(f"Incomplete run requires explicit analysis scope: {path}.")
            rows.append({
                "participant_id": participant, "task": task, "condition": condition,
                "condition_name": expected_name, "trigger_code": code, "run_id": spec["run_id"],
                "hits": hits, "targets": targets, "misses": misses, "false_alarms": false_alarms,
                "hit_rate_percent": percent, "mean_hit_rt_ms": native.get("mean_rt_ms"),
                "completed": complete, "source_path": str(path), "source_sha256": hashes[str(path)],
                "runspec_path": str(spec_path), "runspec_sha256": hashes[str(spec_path)],
                "native_summary": native, "count_crosscheck_passed": True,
                "timing_qc_violation": bool(summary.get("runtime_metadata", {}).get("timing_qc_strict_violation")),
            })
    frame = pd.DataFrame(rows)
    if len(frame) != 18 or frame.duplicated(["participant_id", "task", "condition"]).any():
        raise ValueError("Exactly one observation per participant, task, and load condition is required.")
    return frame.sort_values(["participant_id", "trigger_code"]).reset_index(drop=True), hashes


def analyze(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    comparisons, differences = [], []
    for task in TASKS:
        subset = frame.loc[frame["task"].eq(task)].copy()
        ordered = pd.concat([subset.loc[subset["condition"].eq(condition)] for condition in ("Load", "No load")])
        _, result = run_posthoc_pairwise_tests(
            ordered, "hit_rate_percent", "condition", "participant_id", correction="none",
            followup_provenance="exploratory_manual",
        )
        row = result.iloc[0].to_dict()
        paired = subset.pivot(index="participant_id", columns="condition", values="hit_rate_percent").reindex(PARTICIPANTS)
        load, no_load = paired["Load"].to_numpy(), paired["No load"].to_numpy()
        delta = load - no_load
        independent = stats.ttest_rel(load, no_load, alternative="two-sided")
        if row["inference_status"] == "estimated":
            np.testing.assert_allclose([row["t_statistic"], row["p_raw"], row["mean_diff"], row["cohens_dz"]],
                                       [independent.statistic, independent.pvalue, delta.mean(), delta.mean() / delta.std(ddof=1)],
                                       rtol=1e-12, atol=1e-12)
            width = stats.t.ppf(0.975, 2) * delta.std(ddof=1) / np.sqrt(3)
            np.testing.assert_allclose([row["ci95_low"], row["ci95_high"]],
                                       [delta.mean() - width, delta.mean() + width], rtol=1e-12, atol=1e-12)
        row.update({"task": task, "mean_load_percent": float(load.mean()),
                    "mean_no_load_percent": float(no_load.mean()), "units": "percentage points",
                    "false_alarms_load": int(subset.loc[subset["condition"].eq("Load"), "false_alarms"].sum()),
                    "false_alarms_no_load": int(subset.loc[subset["condition"].eq("No load"), "false_alarms"].sum())})
        comparisons.append(row)
        differences.extend({"participant_id": pid, "task": task, "load_percent": float(load[i]),
                            "no_load_percent": float(no_load[i]), "load_minus_no_load_pp": float(delta[i])}
                           for i, pid in enumerate(PARTICIPANTS))
    raw = pd.DataFrame(comparisons)
    finite = np.isfinite(raw["p_raw"])
    adjusted_input = raw.copy()
    adjusted_input["p_raw"] = raw["p_raw"].fillna(1.0)
    corrected = apply_family_correction(adjusted_input, FamilySpec(
        "fixation_three_task_hit_rate_contrasts", "Three fixation hit-rate load contrasts, separate from EEG", method="holm"))
    order = np.argsort(adjusted_input["p_raw"].to_numpy(), kind="stable")
    expected = np.empty(3)
    expected[order] = np.minimum(1, np.maximum.accumulate(adjusted_input["p_raw"].to_numpy()[order] * [3, 2, 1]))
    np.testing.assert_allclose(corrected["p_adjusted"], expected, rtol=1e-12, atol=1e-12)
    corrected["p_raw"] = raw["p_raw"]
    corrected.loc[~finite, "p_adjusted"] = np.nan
    corrected.loc[~finite, "reject_adjusted"] = False
    corrected["Significant"] = corrected["reject_adjusted"]
    return corrected, differences


def chart(frame: pd.DataFrame, results: pd.DataFrame, output: Path) -> dict:
    findfont(FontProperties(family=FIGURE_FONT_FAMILY), fallback_to_default=False)
    styles = (("#225D79", "o"), ("#B76A16", "s"), ("#8661A1", "^"))
    style = matplotlib_figure_rcparams()
    style.update({"font.weight": "bold", "axes.labelweight": "bold", "axes.titleweight": "bold"})
    with mpl.rc_context(style):
        figure = Figure(figsize=(6.5, 3.4), dpi=FIGURE_EXPORT_DPI)
        FigureCanvasAgg(figure)
        axes = figure.subplots(1, 3, sharey=True)
        figure.subplots_adjust(left=0.105, right=0.99, bottom=0.32, top=0.77, wspace=0.23)
        for axis, task, title in zip(axes, TASKS, ("Semantic\ncategories", "Recognition\nmemory", "Angry facial\nexpressions"), strict=True):
            for i, (participant, (color, marker)) in enumerate(zip(PARTICIPANTS, styles, strict=True)):
                values = frame.loc[frame["task"].eq(task) & frame["participant_id"].eq(participant)].set_index("condition")
                offset = (i - 1) * 0.06
                axis.plot(np.array([0, 1]) + offset, values.loc[["No load", "Load"], "hit_rate_percent"],
                          color=color, marker=marker, markersize=4, linewidth=0.9, label=participant)
            axis.set(xlim=(-0.23, 1.23), ylim=(-3, 103), xticks=[0, 1], xticklabels=["No load", "Load"],
                     yticks=[0, 25, 50, 75, 100])
            axis.set_title(title, **{**figure_text_kwargs("condition_label"), "fontweight": "bold"})
            test = results.loc[results["task"].eq(task)].iloc[0]
            axis.text(0.5, -0.30, f"n = 3\np (uncorrected) = {test['p_raw']:.3f}", transform=axis.transAxes,
                      ha="center", va="top", **{**figure_text_kwargs("annotation"), "fontweight": "bold"})
            axis.spines[["top", "right"]].set_visible(False)
            apply_axis_text_style(axis)
            for tick in [*axis.get_xticklabels(), *axis.get_yticklabels()]:
                tick.set_fontweight("bold")
        axes[0].set_ylabel("Fixation-target hit rate (%)", **{**figure_text_kwargs("axis_label"), "fontweight": "bold"})
        handles, labels = axes[0].get_legend_handles_labels()
        legend_style = figure_legend_kwargs()
        legend_style["prop"]["weight"] = "bold"
        figure.legend(handles, labels, loc="lower center", ncol=3, frameon=False, **legend_style)
        for extension in FIGURE_OUTPUT_FORMATS:
            figure.savefig(output / f"fixation_hit_rate_paired.{extension}", dpi=FIGURE_EXPORT_DPI, facecolor="white")
        figure.clear()
    with Image.open(output / "fixation_hit_rate_paired.png") as raster:
        size, dpi = raster.size, raster.info.get("dpi")
    if size != (3900, 2040) or not np.allclose(dpi, 600, atol=0.02):
        raise AssertionError("Incorrect fixation figure size or DPI.")
    return {"pixels": size, "dpi": dpi, "font": "Arial", "horizontal_display_offsets": [-0.06, 0, 0.06],
            "vertical_values": "Exact participant hit percentages; no jitter or transformation"}


def run(studio_root: Path, project_root: Path) -> Path:
    studio, root = studio_root.expanduser().resolve(strict=True), project_root.expanduser().resolve(strict=True)
    if not (root / "project.json").is_file():
        raise ValueError("The output root must own the processed Toolbox project manifest.")
    frame, sources = collect(studio)
    results, pairs = analyze(frame)
    output = root / STATS_SUBFOLDER_NAME / "Cognitive Load Fixation" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output.mkdir(parents=True, exist_ok=False)
    frame.drop(columns="native_summary").to_csv(output / "participant_condition_counts.csv", index=False)
    results.to_csv(output / "paired_comparisons.csv", index=False)
    pd.DataFrame(pairs).to_csv(output / "participant_pairs.csv", index=False)
    figure = chart(frame, results, output)
    for name, original in sources.items():
        if digest(Path(name)) != original:
            raise RuntimeError(f"Source changed during fixation analysis: {name}.")
    evidence = {"version": VERSION, "status": "completed", "source_hashes": sources,
                "script_sha256": digest(Path(__file__)), "definition": "100 * hits / presented targets; false alarms separate",
                "comparison_direction": "Load minus no load, percentage points", "participant_weighting": "Equal participant weights",
                "crosscheck_passed": True, "participant_condition_rows": frame.to_dict(orient="records"),
                "comparisons": results.to_dict(orient="records"), "participant_pairs": pairs, "figure": figure,
                "limitations": ["Exploratory paired t tests with only three participants, discrete bounded rates, and substantial ceiling effects.",
                                "Individual t confidence intervals are unadjusted and may extend beyond possible percentage-point values.",
                                "One separate Holm family covers the three fixation tests; it is not combined with the EEG family.",
                                "Hit rate is not overall response accuracy: false alarms have no specified non-target denominator and are reported as counts.",
                                "P3 semantic-load zero hits are retained as observed performance; they do not establish whether the participant looked away or prioritized counting."],
                "output_hashes": {path.name: digest(path) for path in output.iterdir() if path.is_file()}}
    (output / "results.json").write_text(json.dumps(clean_json(evidence), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                                         encoding="utf-8")
    verification = {"status": "passed", "source_count_checks": 18, "paired_scipy_checks": 3,
                    "holm_numpy_check": True, "source_hashes_unchanged": True,
                    "results_sha256": digest(output / "results.json"), "figure": figure}
    (output / "verification.json").write_text(json.dumps(verification, indent=2) + "\n", encoding="utf-8")
    current = output.parent / "current.json"
    pending = current.with_suffix(".json.tmp")
    pending.write_text(json.dumps({"analysis_directory": output.relative_to(root).as_posix(),
                                  "results_sha256": digest(output / "results.json"),
                                  "verification_sha256": digest(output / "verification.json")}, indent=2) + "\n",
                       encoding="utf-8")
    pending.replace(current)
    LOGGER.info("Fixation hit-rate analysis saved to %s", output)
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
        LOGGER.exception("Fixation analysis did not complete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Compare cognitive load with no load using released Toolbox Summed BCA.

This study-specific paired analysis does not change Standard FPVS Screening,
processing settings, reviewed exclusions, or the published harmonic selection.
Each invocation analyzes one endpoint and writes a new project-local evidence
directory. The default endpoint is the user-defined Occipital ROI (O1, Oz, O2).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import scipy
from scipy import stats

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

LOGGER = logging.getLogger(__name__)
VERSION = "cognitive_load_paired_analysis_v1"
TASKS = ("Semantic Categories", "Recognition Memory", "Angry Facial Expressions")
DEFAULT_CONTRASTS = tuple((task, f"{task} - Cognitive Load", f"{task} - No Load") for task in TASKS)
FAMILY = {
    "family_id": "cognitive_load_three_task_contrasts",
    "family_label": "Load minus no load across three tasks at one endpoint",
    "method": "holm",
    "alpha": 0.05,
}


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def json_safe(value: object) -> object:
    """Preserve missing results as JSON null rather than nonstandard NaN."""
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(json_safe(value), indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8")


def truth_value(value: object) -> bool:
    text = str(value).strip().casefold()
    if text in {"yes", "true", "1"}:
        return True
    if text in {"no", "false", "0", ""}:
        return False
    raise ValueError(f"Unrecognized canonical exclusion flag: {value!r}.")


def validate_contrasts(contrasts: list[tuple[str, str, str]], conditions: set[str]) -> None:
    if len(contrasts) != 3 or len({row[0] for row in contrasts}) != 3:
        raise ValueError("Declare exactly three uniquely named task contrasts.")
    selected = [condition for _, load, no_load in contrasts for condition in (load, no_load)]
    if len(set(selected)) != 6:
        raise ValueError("The three contrasts must name six distinct canonical conditions.")
    missing = set(selected) - conditions
    if missing:
        raise ValueError(f"Unknown canonical conditions: {sorted(missing)!r}.")


def endpoint_frame(workbook: Path, endpoint: str) -> pd.DataFrame:
    from Main_App.exports.analysis_ready_workbook import ROI_LONG_SHEET, WHOLE_SCALP_SHEET

    sheet = WHOLE_SCALP_SHEET if endpoint == "whole_scalp" else ROI_LONG_SHEET
    source = pd.read_excel(workbook, sheet_name=sheet, keep_default_na=False, dtype={"PID": str})
    if endpoint != "whole_scalp":
        source = source.loc[source["ROI"].eq(endpoint)].copy()
        if source.empty:
            raise ValueError(f"Endpoint {endpoint!r} is not a frozen ROI in the canonical export.")
    value_column = "Whole Scalp Signed Mean Summed BCA" if endpoint == "whole_scalp" else "Raw Summed BCA"
    required = {"PID", "Condition", value_column, "Current Toolbox Exclusion", "QC Flag", "QC Notes"}
    if missing := required - set(source.columns):
        raise ValueError(f"Canonical endpoint sheet lacks {sorted(missing)!r}.")
    if source.duplicated(["PID", "Condition"]).any():
        raise ValueError("Duplicate participant-condition endpoint rows; paired merge would be ambiguous.")
    source["value_uv"] = pd.to_numeric(source[value_column], errors="coerce")
    source["excluded"] = source["Current Toolbox Exclusion"].map(truth_value)
    source["available"] = ~source["excluded"] & np.isfinite(source["value_uv"])
    return source


def independent_check(load: np.ndarray, no_load: np.ndarray, row: pd.Series) -> dict[str, object]:
    """Check toolbox estimates against NumPy formulas and SciPy paired inference."""
    difference = load - no_load
    n = len(difference)
    if int(row["N_Pairs"]) != n:
        raise AssertionError("Toolbox pair count disagrees with validated participant pairs.")
    if n:
        np.testing.assert_allclose(row["mean_diff"], difference.mean(), rtol=1e-12, atol=1e-14)
    if row["inference_status"] != "estimated":
        return {"status": "not_estimable", "code": row["status_code"], "pair_count_checked": True}
    mean, sd = float(difference.mean()), float(difference.std(ddof=1))
    se = sd / np.sqrt(n)
    t_value = mean / se
    half_width = float(stats.t.ppf(0.975, n - 1) * se)
    expected = [mean, sd, t_value, n - 1, 2 * stats.t.sf(abs(t_value), n - 1),
                mean - half_width, mean + half_width, mean / sd]
    columns = ["mean_diff", "sd_diff", "t_statistic", "df", "p_raw", "ci95_low", "ci95_high", "cohens_dz"]
    np.testing.assert_allclose(row[columns].to_numpy(dtype=float), expected, rtol=1e-11, atol=1e-13)
    paired = stats.ttest_rel(load, no_load, alternative="two-sided")
    np.testing.assert_allclose([row["t_statistic"], row["p_raw"]],
                               [paired.statistic, paired.pvalue], rtol=1e-11, atol=1e-13)
    return {"status": "passed", "pair_count_checked": True,
            "numpy_t": t_value, "numpy_p": expected[4], "scipy_paired_p": float(paired.pvalue)}


def compare_tasks(source: pd.DataFrame, participants: list[str],
                  contrasts: list[tuple[str, str, str]]) -> tuple[pd.DataFrame, list[dict], list[dict]]:
    from Tools.Stats.analysis.inference_contracts import FamilySpec
    from Tools.Stats.analysis.multiple_comparisons import apply_family_correction
    from Tools.Stats.analysis.posthoc_tests import run_posthoc_pairwise_tests

    source_by_key = source.set_index(["PID", "Condition"])
    records, coverage, checks = [], [], []
    for task, load_condition, no_load_condition in contrasts:
        pairs = []
        for participant in participants:
            entry = {"task": task, "participant_id": participant,
                     "load_condition": load_condition, "no_load_condition": no_load_condition}
            unavailable = []
            for label, condition in (("load", load_condition), ("no_load", no_load_condition)):
                key = (participant, condition)
                if key not in source_by_key.index:
                    entry.update({f"{label}_uv": None, f"{label}_excluded": None,
                                  f"{label}_qc_notes": "No released endpoint row."})
                    unavailable.append(f"{label}: missing endpoint")
                    continue
                observation = source_by_key.loc[key]
                entry.update({f"{label}_uv": float(observation["value_uv"]),
                              f"{label}_excluded": bool(observation["excluded"]),
                              f"{label}_qc_flag": observation["QC Flag"],
                              f"{label}_qc_notes": observation["QC Notes"]})
                if not observation["available"]:
                    unavailable.append(f"{label}: " + ("toolbox exclusion" if observation["excluded"]
                                                       else "nonfinite endpoint"))
            entry["included_pair"] = not unavailable
            entry["unavailable_reasons"] = unavailable
            entry["difference_load_minus_no_load_uv"] = None
            if not unavailable:
                entry["difference_load_minus_no_load_uv"] = entry["load_uv"] - entry["no_load_uv"]
                pairs.append(entry)
            coverage.append(entry)
        load = np.asarray([entry["load_uv"] for entry in pairs], dtype=float)
        no_load = np.asarray([entry["no_load_uv"] for entry in pairs], dtype=float)
        # Both factor levels remain present even when no pair is estimable.
        paired_long = pd.DataFrame([
            {"PID": participant, "Condition": condition,
             "value": values[index] if pairs else np.nan}
            for condition, values in ((load_condition, load), (no_load_condition, no_load))
            for index, participant in enumerate([entry["participant_id"] for entry in pairs] or participants)
        ])
        _, result = run_posthoc_pairwise_tests(
            paired_long, dv_col="value", factor_col="Condition", subject_col="PID",
            correction="none", followup_provenance="planned",
        )
        if len(result) != 1:
            raise AssertionError("Expected exactly one toolbox paired contrast per task.")
        row = result.iloc[0].copy()
        checks.append({"task": task, **independent_check(load, no_load, row)})
        record = row.to_dict()
        record.update({"task": task, "mean_load_uv": float(load.mean()) if len(load) else np.nan,
                       "mean_no_load_uv": float(no_load.mean()) if len(no_load) else np.nan,
                       "sd_load_uv": float(load.std(ddof=1)) if len(load) >= 2 else np.nan,
                       "sd_no_load_uv": float(no_load.std(ddof=1)) if len(load) >= 2 else np.nan,
                       "included_participants": [entry["participant_id"] for entry in pairs],
                       "missing_pair_count": len(participants) - len(pairs)})
        records.append(record)
    results = pd.DataFrame(records)
    # Retain every declared test in the family, including non-estimable contrasts.
    raw_p = results["p_raw"].copy()
    estimated = np.isfinite(raw_p.to_numpy(dtype=float))
    results["p_raw"] = raw_p.fillna(1.0)
    corrected = apply_family_correction(results, FamilySpec(**FAMILY))
    probability = results["p_raw"].to_numpy(dtype=float)
    order = np.argsort(probability, kind="stable")
    independently_adjusted = np.empty_like(probability)
    independently_adjusted[order] = np.minimum(
        1.0, np.maximum.accumulate(probability[order] * np.arange(len(probability), 0, -1)))
    np.testing.assert_allclose(corrected["p_adjusted"], independently_adjusted, rtol=1e-12, atol=1e-14)
    corrected["p_raw"] = raw_p
    corrected.loc[~estimated, "p_adjusted"] = np.nan
    corrected.loc[~estimated, "reject_adjusted"] = False
    corrected["Significant"] = corrected["reject_adjusted"]
    corrected["p_value"] = corrected["p_raw"]
    corrected["ci_scope"] = "Unadjusted individual 95% mean-difference interval"
    return corrected, coverage, checks


def run(project_root: Path, endpoint: str, contrasts: list[tuple[str, str, str]],
        output_directory: Path | None = None, *, domain_selection_note: str = "",
        config_home: Path | None = None) -> Path:
    root = project_root.expanduser().resolve(strict=True)
    configuration = config_home or root / ".fpvs_processing" / "headless_config"
    configuration = (root / configuration).resolve() if not configuration.is_absolute() else configuration.resolve()
    if not configuration.is_relative_to(root) or not configuration.is_dir():
        raise ValueError("Use the existing project-local headless configuration from processing/finalization.")
    os.environ["FPVS_CONFIG_HOME"] = str(configuration)
    # Import application services only after isolating their settings to this project.
    from Main_App.exports.analysis_ready_workbook import write_analysis_ready_workbook
    from Main_App.processing.canonical_harmonics import load_project_processing_harmonics
    from Main_App.processing.processing_ledger import ledger_path
    from Main_App.processing.roi_coverage import require_project_final_release
    from Main_App.projects import STATS_SUBFOLDER_NAME, load_project_dataset_index
    from Main_App.projects.condition_trigger_maps import project_conditions
    from Tools.Stats.analysis.inference_contracts import FamilySpec

    index = load_project_dataset_index(root)
    if index.project_root != root or index.manifest is None:
        raise ValueError("--project-root must be the canonical manifest-owning project root.")
    if index.is_repeated_session or index.is_multi_group:
        raise ValueError("This runner requires one group and one recording per participant.")
    # Manifest conditions remain declared even if every observation is unavailable.
    conditions = {condition.label for condition in project_conditions(index.manifest)}
    validate_contrasts(contrasts, conditions)
    participants = sorted(index.participants or index.participant_ids, key=str.casefold)
    if not participants:
        raise ValueError("The project has no canonical participants.")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    output = output_directory or Path(STATS_SUBFOLDER_NAME) / "Cognitive Load Paired Analysis" / stamp
    output = (root / output).resolve() if not output.is_absolute() else output.resolve()
    if output == root or not output.is_relative_to(root):
        raise ValueError("Analysis output must be a new directory inside the active project root.")
    if output.exists():
        raise FileExistsError(f"Analysis output already exists: {output}")
    immutable_files = (root / "project.json", ledger_path(root))
    initial_hashes = {path.relative_to(root).as_posix(): file_hash(path) for path in immutable_files}
    _, final_coverage, release = require_project_final_release(root)
    if endpoint != "whole_scalp" and endpoint not in final_coverage.roi_snapshot.as_mapping():
        raise ValueError(f"Endpoint {endpoint!r} is not an exact frozen ROI name.")
    canonical = load_project_processing_harmonics(project_root=root, log_func=LOGGER.info)
    exported = write_analysis_ready_workbook(root, log_callback=LOGGER.info)
    workbook_hash = file_hash(exported.path)
    source = endpoint_frame(exported.path, endpoint)
    plan = {
        "version": VERSION, "created_utc": stamp, "endpoint": endpoint,
        "dependent_variable": "Raw summed baseline-corrected amplitude, microvolts",
        "whole_scalp_definition": "Signed mean of the canonical complete scalp summed-BCA values",
        "contrast_direction": "cognitive load minus no load", "alternative": "two-sided",
        "contrasts": [{"task": task, "load": load, "no_load": no_load} for task, load, no_load in contrasts],
        "participants": participants, "family": {**FamilySpec(**FAMILY).to_dict(), "declared_size": len(contrasts)},
        "config_home": configuration.relative_to(root).as_posix(),
        "domain_selection_note": domain_selection_note.strip(),
        "missingness": "Complete pairs per task; no imputation or cross-task complete-case deletion",
        "nonestimable_family_policy": "Retain declared tests as p=1 for Holm; report unavailable results as null",
        "release_receipt": release.to_payload(), "roi_snapshot": final_coverage.roi_snapshot.to_payload(),
        "harmonics_hz": canonical.selected_harmonics_hz, "harmonic_fingerprint": canonical.fingerprint,
        "harmonic_metadata": canonical.metadata, "input_hashes": initial_hashes,
        "export_workbook": exported.path.relative_to(root).as_posix(), "export_sha256": workbook_hash,
        "script_sha256": file_hash(Path(__file__)),
        "versions": {"python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
                     "pandas": pd.__version__},
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "analysis_plan.json", plan)
    results, coverage, checks = compare_tasks(source, participants, contrasts)
    for path in immutable_files:
        if file_hash(path) != initial_hashes[path.relative_to(root).as_posix()]:
            raise RuntimeError(f"Project input changed during analysis: {path.name}.")
    if file_hash(exported.path) != workbook_hash:
        raise RuntimeError("Canonical analysis-ready workbook changed during analysis.")
    # Revalidate source artifacts after inference, rather than relying only on the export hash.
    require_project_final_release(root)
    current = load_project_processing_harmonics(project_root=root, log_func=LOGGER.info)
    if current.fingerprint != canonical.fingerprint:
        raise RuntimeError("Canonical harmonic identity changed during analysis.")
    results.to_csv(output / "paired_comparisons.csv", index=False)
    pd.DataFrame(coverage).to_csv(output / "participant_pairs.csv", index=False)
    source.to_csv(output / "canonical_endpoint_rows.csv", index=False)
    evidence = {
        "version": VERSION, "endpoint": endpoint, "status": "completed",
        "domain_selection_note": domain_selection_note.strip(),
        "analysis_plan_sha256": file_hash(output / "analysis_plan.json"),
        "crosscheck_passed": True, "crosschecks": checks, "holm_crosscheck": "passed",
        "comparisons": results.to_dict(orient="records"), "participant_pairs": coverage,
        "missing_pairs": [row for row in coverage if not row["included_pair"]],
        "qc_exclusions": source.loc[source["excluded"]].to_dict(orient="records"),
        "source_endpoint_rows": source.to_dict(orient="records"),
        "limitations": [
            "Small-sample paired t inference relies on the paired-difference distribution; diagnostics do not select tests.",
            (domain_selection_note.strip() or
             ("Harmonics selected adaptively from this dataset have same-sample exploratory provenance."
              if canonical.exploratory else "Harmonic-selection provenance is retained in the analysis plan.")),
            "Confidence intervals are individual, unadjusted 95% intervals; task p-values share one Holm family.",
            "A nonsignificant contrast does not establish equivalence or absence of a load effect.",
        ],
    }
    write_json(output / "results.json", evidence)
    LOGGER.info("Paired evidence saved to %s", output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--endpoint", default="Occipital",
                        help="Occipital (default: O1, Oz, O2), whole_scalp, or one exact frozen ROI name; no additional ROIs are tested")
    parser.add_argument("--contrast", nargs=3, action="append", metavar=("TASK", "LOAD", "NO_LOAD"),
                        help="Repeat exactly three times to override the study's canonical condition names")
    parser.add_argument("--output-dir", type=Path, help="New project-local directory; defaults to a timestamped Stats folder")
    parser.add_argument("--config-home", type=Path, help="Existing project-local configuration used for processing")
    parser.add_argument("--domain-selection-note", default="",
                        help="Actual selection provenance, including any exploratory choice after inspecting these data")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(args.project_root, args.endpoint, [tuple(row) for row in (args.contrast or DEFAULT_CONTRASTS)],
            args.output_dir, domain_selection_note=args.domain_selection_note, config_home=args.config_home)
    except (OSError, RuntimeError, ValueError, AssertionError):
        LOGGER.exception("Paired analysis did not complete")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

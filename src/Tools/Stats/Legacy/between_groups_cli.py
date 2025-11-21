"""CLI entrypoint for running the between-group stats pipeline out-of-process.

The CLI consumes a JSON job specification (path passed as argv[1]) and executes
the full between-group pipeline in-process:

    1) Mixed RM-ANOVA between groups
    2) Between-group mixed-effects model
    3) Between-group contrasts
    4) Harmonic check

Progress markers are written to stdout in the form ``STAGE_START:<STEP>`` and
``STAGE_DONE:<STEP>`` so that the caller can surface UI updates. A summary JSON
is written to the path provided in the job spec under ``output.summary_json``.

Exit codes:
    0 - Success
    non-zero - Failure; a concise error is written to stderr
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from Tools.Stats.Legacy.blas_limits import single_threaded_blas
from Tools.Stats.Legacy.group_contrasts import compute_group_contrasts
from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.cross_phase_lmm_core import (
    build_cross_phase_long_df,
    run_cross_phase_lmm,
)
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.mixed_group_anova import run_mixed_group_anova
from Tools.Stats.Legacy.stats_analysis import (
    prepare_all_subject_summed_bca_data,
    run_harmonic_check as legacy_run_harmonic_check,
    set_rois,
)
from Tools.Stats.Legacy.stats_export import _auto_format_and_write_excel


# ------------------------------ utilities -------------------------------


def _print(msg: str) -> None:
    print(msg, flush=True)


def _stage_marker(event: str, step: str) -> None:
    _print(f"STAGE_{event}:{step}")


def _df_to_dict(df: Optional[pd.DataFrame]) -> Optional[dict]:
    if df is None:
        return None
    return {"columns": list(df.columns), "data": df.to_dict(orient="records")}


def _long_format_from_bca(
    all_subject_bca_data: Dict[str, Dict[str, Dict[str, float]]],
    subject_groups: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    rows = []
    groups = subject_groups or {}
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    rows.append(
                        {
                            "subject": pid,
                            "condition": cond_name,
                            "roi": roi_name,
                            "value": value,
                            "group": groups.get(pid),
                        }
                    )
    return pd.DataFrame(rows)


# ------------------------------ dataclasses ------------------------------


@dataclass
class HarmonicOptions:
    metric: str
    mean_value_threshold: float
    base_freq: float
    correction_method: str = "holm"
    tail: str = "greater"
    max_freq: Optional[float] = None
    min_subjects: int = 3
    oddball_every_n: int = 5
    limit_n_harmonics: Optional[int] = None
    do_wilcoxon_sensitivity: bool = True


@dataclass
class JobSpec:
    subjects: List[str]
    conditions: List[str]
    subject_data: Dict[str, Dict[str, str]]
    subject_groups: Dict[str, str | None]
    roi_map: Dict[str, List[str]]
    base_freq: float
    alpha: float
    harmonic_options: HarmonicOptions
    output_summary: Path

    @staticmethod
    def load(path: Path) -> "JobSpec":
        data = json.loads(Path(path).read_text())
        harmonic_raw = data.get("harmonic_options", {})
        harm = HarmonicOptions(
            metric=harmonic_raw.get("metric", "Z Score"),
            mean_value_threshold=float(harmonic_raw.get("mean_value_threshold", 0.0)),
            base_freq=float(harmonic_raw.get("base_freq", data.get("base_freq", 6.0))),
            correction_method=harmonic_raw.get("correction_method", "holm"),
            tail=harmonic_raw.get("tail", "greater"),
            max_freq=harmonic_raw.get("max_freq"),
            min_subjects=int(harmonic_raw.get("min_subjects", 3)),
            oddball_every_n=int(harmonic_raw.get("oddball_every_n", 5)),
            limit_n_harmonics=harmonic_raw.get("limit_n_harmonics"),
            do_wilcoxon_sensitivity=bool(
                harmonic_raw.get("do_wilcoxon_sensitivity", True)
            ),
        )

        return JobSpec(
            subjects=list(data["subjects"]),
            conditions=list(data["conditions"]),
            subject_data=data["subject_data"],
            subject_groups=data.get("subject_groups", {}),
            roi_map=data.get("roi_map", {}),
            base_freq=float(data.get("base_freq", 6.0)),
            alpha=float(data.get("alpha", 0.05)),
            harmonic_options=harm,
            output_summary=Path(data["output"]["summary_json"]),
        )


# --------------------------- pipeline helpers ---------------------------


def _run_mixed_anova(df_long: pd.DataFrame) -> pd.DataFrame:
    return run_mixed_group_anova(
        df_long,
        dv_col="value",
        subject_col="subject",
        within_cols=["condition", "roi"],
        between_col="group",
    )


def _run_mixed_model(df_long: pd.DataFrame) -> pd.DataFrame:
    return run_mixed_effects_model(
        data=df_long,
        dv_col="value",
        group_col="subject",
        fixed_effects=["group * condition * roi"],
    )


def _run_group_contrasts(df_long: pd.DataFrame) -> pd.DataFrame:
    return compute_group_contrasts(
        df_long,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )


def _run_harmonic(spec: JobSpec, log_func: Callable[[str], None]):
    opts = spec.harmonic_options
    return legacy_run_harmonic_check(
        subject_data=spec.subject_data,
        subjects=spec.subjects,
        conditions=spec.conditions,
        selected_metric=opts.metric,
        mean_value_threshold=opts.mean_value_threshold,
        base_freq=opts.base_freq,
        log_func=log_func,
        max_freq=opts.max_freq,
        correction_method=opts.correction_method,
        tail=opts.tail,
        min_subjects=opts.min_subjects,
        do_wilcoxon_sensitivity=opts.do_wilcoxon_sensitivity,
        oddball_every_n=opts.oddball_every_n,
        limit_n_harmonics=opts.limit_n_harmonics,
        rois=spec.roi_map,
    )


# ------------------------------ main runner -----------------------------


def run_between_groups_pipeline(spec: JobSpec) -> dict:
    set_rois(spec.roi_map)

    _stage_marker("START", "BETWEEN_GROUP_ANOVA")
    _print("Preparing summed BCA data for between-group pipeline…")
    with single_threaded_blas():
        bca_data = prepare_all_subject_summed_bca_data(
            subjects=spec.subjects,
            conditions=spec.conditions,
            subject_data=spec.subject_data,
            base_freq=spec.base_freq,
            log_func=_print,
        )
    if not bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(bca_data, spec.subject_groups)
    df_long = df_long.dropna(subset=["group"])
    if df_long.empty or df_long["group"].nunique() < 2:
        raise RuntimeError("Between-group analysis requires at least two populated groups.")

    df_long["group"] = df_long["group"].astype(str)

    results: dict[str, Any] = {"steps": {}}

    with single_threaded_blas():
        _print("Running between-group RM-ANOVA…")
        anova_df = _run_mixed_anova(df_long)
    _stage_marker("DONE", "BETWEEN_GROUP_ANOVA")
    results["steps"]["BETWEEN_GROUP_ANOVA"] = {
        "anova_df_results": _df_to_dict(anova_df)
    }

    _stage_marker("START", "BETWEEN_GROUP_MIXED_MODEL")
    with single_threaded_blas():
        _print("Running between-group mixed-effects model…")
        mixed_df = _run_mixed_model(df_long)
    _stage_marker("DONE", "BETWEEN_GROUP_MIXED_MODEL")
    mixed_text = "============================================================\n"
    mixed_text += "       Between-Group Mixed-Effects Model Results\n"
    mixed_text += "       Analysis conducted on: Summed BCA Data\n"
    mixed_text += "============================================================\n\n"
    if mixed_df is not None and not mixed_df.empty:
        mixed_text += "--------------------------------------------\n"
        mixed_text += "                 FIXED EFFECTS TABLE\n"
        mixed_text += "--------------------------------------------\n"
        mixed_text += mixed_df.to_string(index=False) + "\n"
        mixed_text += generate_lme_summary(mixed_df, alpha=spec.alpha)
    else:
        mixed_text += "Mixed effects model returned no rows.\n"
    results["steps"]["BETWEEN_GROUP_MIXED_MODEL"] = {
        "mixed_results_df": _df_to_dict(mixed_df),
        "output_text": mixed_text,
    }

    _stage_marker("START", "GROUP_CONTRASTS")
    with single_threaded_blas():
        _print("Computing between-group contrasts…")
        contrasts_df = _run_group_contrasts(df_long)
    _stage_marker("DONE", "GROUP_CONTRASTS")
    results["steps"]["GROUP_CONTRASTS"] = {
        "results_df": _df_to_dict(contrasts_df),
        "output_text": "",
    }

    _stage_marker("START", "HARMONIC_CHECK")
    harmonic_text, harmonic_findings = _run_harmonic(spec, _print)
    _stage_marker("DONE", "HARMONIC_CHECK")
    results["steps"]["HARMONIC_CHECK"] = {
        "output_text": harmonic_text,
        "findings": harmonic_findings,
    }

    return results


def run_pipeline(spec: JobSpec) -> dict:
    """Backward-compatible alias for the between-group pipeline."""

    return run_between_groups_pipeline(spec)


def run_cross_phase_lmm_pipeline(spec: dict) -> int:
    """
    CLI entrypoint for generic cross-phase LMM.

    Uses cross_phase_lmm_core.build_cross_phase_long_df / run_cross_phase_lmm.
    Returns 0 on success, non-zero on failure.
    """

    logger = logging.getLogger("cross_phase_lmm")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    summary_path: Path | None = None

    try:
        # spec["phase_projects"] = {phase_label: {subjects, conditions, subject_data, group_map}}
        phase_projects = spec.get("phase_projects")
        if not isinstance(phase_projects, dict) or len(phase_projects) < 2:
            raise ValueError("Cross-phase LMM requires at least two phase projects.")

        phase_labels: Tuple[str, ...] = tuple(phase_projects.keys())
        roi_map = spec.get("roi_map", {})
        base_freq = float(spec.get("base_freq", 6.0))
        set_rois(roi_map)

        phase_data: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
        phase_group_maps: Dict[str, Dict[str, str]] = {}

        for phase_label, project_spec in phase_projects.items():
            try:
                subjects = project_spec["subjects"]
                conditions = project_spec["conditions"]
                subject_data = project_spec["subject_data"]
            except KeyError as exc:  # pragma: no cover - defensive
                raise ValueError(f"Missing required key for phase '{phase_label}': {exc}") from exc

            logger.info("Preparing summed BCA data for phase '%s'…", phase_label)
            with single_threaded_blas():
                bca_data = prepare_all_subject_summed_bca_data(
                    subjects=subjects,
                    conditions=conditions,
                    subject_data=subject_data,
                    base_freq=base_freq,
                    rois=roi_map,
                    log_func=logger.info,
                )
            phase_data[phase_label] = bca_data
            phase_group_maps[phase_label] = project_spec.get("group_map", {})

        df_long = build_cross_phase_long_df(phase_data, phase_group_maps, phase_labels)
        subject_count = int(df_long["subject"].nunique()) if not df_long.empty else 0
        logger.info("Prepared cross-phase dataset with %d subjects.", subject_count)
        logger.info("Running cross-phase LMM with factors: group, phase, condition, roi")

        results = run_cross_phase_lmm(
            df_long,
            focal_condition=spec.get("focal_condition"),
            focal_roi=spec.get("focal_roi"),
            logger=logger,
        )

        effects_of_interest = results.get("effects_of_interest") or {}
        for contrast in effects_of_interest.get("contrasts", []) or []:
            label = contrast.get("label", "")
            p_value = contrast.get("p")
            logger.info("Effect of interest '%s' p-value: %s", label, p_value)

        output_spec = spec.get("output", {})
        if "summary_json" not in output_spec or "excel_report" not in output_spec:
            raise ValueError("Cross-phase LMM output paths must be provided.")

        summary_path = Path(output_spec["summary_json"])
        excel_path = Path(output_spec["excel_report"])
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        excel_path.parent.mkdir(parents=True, exist_ok=True)

        summary_path.write_text(json.dumps(results, indent=2))

        fixed_effects_df = pd.DataFrame(results.get("fixed_effects") or [])
        if fixed_effects_df.empty:
            fixed_effects_df = pd.DataFrame(
                columns=["effect", "estimate", "se", "stat", "p"]
            )

        with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
            _auto_format_and_write_excel(
                writer, fixed_effects_df, "Fixed Effects", logger.info
            )

            if effects_of_interest:
                contrasts_df = pd.DataFrame(effects_of_interest.get("contrasts") or [])
                if contrasts_df.empty:
                    contrasts_df = pd.DataFrame(
                        columns=["label", "estimate", "se", "stat", "p"]
                    )
                _auto_format_and_write_excel(
                    writer, contrasts_df, "Effects of Interest", logger.info
                )

        logger.info("Cross-phase LMM analysis complete.")
        return 0
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Cross-phase LMM failed: {exc}\n")
        if summary_path is not None:
            try:
                summary_path.parent.mkdir(parents=True, exist_ok=True)
                summary_path.write_text(json.dumps({"error": str(exc)}, indent=2))
            except Exception:  # noqa: BLE001
                pass
        return 1


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Between-group stats pipeline")
    parser.add_argument("job_spec", help="Path to JSON job specification")
    args = parser.parse_args(argv)

    job_path = Path(args.job_spec)
    try:
        raw_spec = json.loads(job_path.read_text())
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"Failed to read job spec: {exc}\n")
        return 2

    mode = raw_spec.get("mode", "between_groups") if isinstance(raw_spec, dict) else "between_groups"

    if mode == "between_groups":
        try:
            spec = JobSpec.load(job_path)
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"Failed to read job spec: {exc}\n")
            return 2

        try:
            results = run_between_groups_pipeline(spec)
            summary_payload = {
                "steps": results.get("steps", {}),
            }
            spec.output_summary.parent.mkdir(parents=True, exist_ok=True)
            spec.output_summary.write_text(json.dumps(summary_payload, indent=2))
            return 0
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"{exc}\n")
            return 1

    if mode == "cross_phase_lmm":
        return run_cross_phase_lmm_pipeline(raw_spec)

    sys.stderr.write(f"Unknown stats mode: {mode}\n")
    return 2


if __name__ == "__main__":  # pragma: no cover - CLI entrypoint
    raise SystemExit(main())

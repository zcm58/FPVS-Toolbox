"""Cross-phase Lela Mode analysis helpers (PySide6 path).

This module re-implements the cross-phase linear mixed model (LMM) pipeline
used by Lela Mode without relying on the legacy CLI. It operates entirely
within the PySide6 Stats tooling so that behaviour changes remain scoped here.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from Tools.Stats.Legacy.cross_phase_lmm_core import (
    _build_contrast,
    _build_fixed_effects_table,
    _run_backup_2x2,
    build_cross_phase_long_df,
)
from Tools.Stats.Legacy.stats_analysis import prepare_all_subject_summed_bca_data
from Tools.Stats.Legacy.between_groups_cli import _auto_format_and_write_excel
from Tools.Stats.Legacy.blas_limits import single_threaded_blas


logger = logging.getLogger(__name__)


def _condition_intersection_with_order(
    phase_specs: Dict[str, dict],
) -> tuple[list[str], dict[str, set[str]]]:
    """Return the ordered intersection of conditions across phases.

    Also returns a mapping of phase → conditions that are missing from the
    intersection (i.e., present in that phase only).
    """

    ordered_conditions: list[str] = []
    common_conditions: set[str] | None = None
    all_conditions_per_phase: dict[str, set[str]] = {}

    for label, spec in phase_specs.items():
        conditions = spec.get("conditions") or []
        all_conditions_per_phase[label] = set(conditions)
        if not ordered_conditions:
            ordered_conditions = list(conditions)
        condition_set = set(conditions)
        common_conditions = (
            condition_set if common_conditions is None else common_conditions & condition_set
        )

    if not common_conditions:
        return [], {label: set() for label in phase_specs}

    missing_by_phase: dict[str, set[str]] = {}
    for phase_label, cond_set in all_conditions_per_phase.items():
        missing_by_phase[phase_label] = cond_set - common_conditions

    return [cond for cond in ordered_conditions if cond in common_conditions], missing_by_phase


def _subset_df_for_condition(
    df_long: pd.DataFrame, *, condition: str, roi: str
) -> pd.DataFrame:
    """Handle the subset df for condition step for the Stats PySide6 workflow."""
    df = df_long[df_long["condition"] == condition]
    df = df[df["roi"] == roi]
    return df.copy()


def _run_roi_condition_lmm(
    df: pd.DataFrame,
    *,
    roi: str,
    condition: str,
    phase_labels: Sequence[str],
    message_cb=None,
) -> dict:
    """Handle the run roi condition lmm step for the Stats PySide6 workflow."""
    meta_warnings: list[str] = []
    backup_rows: list[dict] = []

    if df.empty:
        raise ValueError("No data remaining for ROI/condition after filtering.")

    df = df.replace({"group": {None: ""}})
    df = df.dropna(subset=["bca", "subject", "group", "phase"])
    df = df[np.isfinite(df["bca"].to_numpy())]

    if df.empty:
        raise ValueError("No data remaining after cleaning and focal filters.")

    model_formula = "bca ~ group * phase"

    try:
        import statsmodels.formula.api as smf  # type: ignore
    except ImportError as e:  # pragma: no cover - dependency guard
        raise ImportError("statsmodels is required. Install via `pip install statsmodels`.") from e

    result_obj = None
    backup_2x2 = None
    with single_threaded_blas():
        try:
            model = smf.mixedlm(model_formula, df, groups=df["subject"])
            result_obj = model.fit(reml=True, method="lbfgs", maxiter=1000, full_output=True)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Cross-phase MixedLM failed for ROI '%s', condition '%s': %s",
                roi,
                condition,
                exc,
            )
            if message_cb:
                message_cb(
                    f"Cross-phase MixedLM failed for ROI '{roi}', condition '{condition}': {exc}; using backup 2x2."
                )
            meta_warnings.append(f"MixedLM failed to converge: {exc}")
            backup_2x2 = _run_backup_2x2(df.rename(columns={"bca": "value"}), logger)

    fixed_effects = (
        _build_fixed_effects_table(result_obj) if result_obj is not None else None
    )

    contrasts = []
    if result_obj is not None:
        try:
            groups = sorted(df["group"].unique().tolist())
            phases = tuple(phase_labels) if len(phase_labels) >= 2 else tuple(df["phase"].unique())
            if len(phases) < 2:
                raise ValueError("Need at least two phases to compute contrasts.")

            contrasts = _build_contrast(
                "group * phase",
                result_obj.model.exog_names,
                groups,
                (phases[0], phases[1]),
                condition,
                roi,
                result_obj,
                logger,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to compute contrasts for ROI '%s', condition '%s': %s",
                roi,
                condition,
                exc,
            )
            meta_warnings.append(f"Failed to compute contrasts: {exc}")

    if result_obj is None or not getattr(result_obj, "converged", False):
        if "MixedLM failed to converge" not in meta_warnings:
            meta_warnings.append("MixedLM did not converge.")
        if backup_2x2 is None:
            backup_2x2 = _run_backup_2x2(df.rename(columns={"bca": "value"}), logger)
        if message_cb:
            message_cb(
                f"Cross-phase MixedLM did not converge for ROI '{roi}', condition '{condition}'; backup 2x2 results recorded."
            )

    if result_obj is None and backup_2x2 is None:
        backup_2x2 = _run_backup_2x2(df.rename(columns={"bca": "value"}), logger)

    def _append_backup_rows(backup: dict | None) -> None:
        """Handle the append backup rows step for the Stats PySide6 workflow."""
        if not backup:
            return
        tests = backup.get("tests") or []
        for test in tests:
            effect = test.get("type")
            if effect == "between_group_at_phase":
                effect_label = "group"
            elif effect == "within_group_phase_diff":
                effect_label = "phase"
            elif effect == "interaction_diff_of_diffs":
                effect_label = "group_x_phase"
            else:
                effect_label = str(effect) if effect is not None else None

            if not effect_label:
                continue

            estimate = test.get("estimate")
            if estimate is None or not np.isfinite(float(estimate)):
                estimate = test.get("diff_delta", test.get("diff", float("nan")))
            se_val = test.get("se")
            stat_val = float(test.get("t", float("nan")))
            if (
                (se_val is None or not np.isfinite(float(se_val)))
                and np.isfinite(float(estimate))
                and np.isfinite(stat_val)
                and stat_val != 0
            ):
                se_val = float(estimate) / stat_val

            row: dict = {
                "roi": roi,
                "condition": condition,
                "effect": effect_label,
                "estimate": float(estimate) if estimate is not None else float("nan"),
                "se": float(se_val) if se_val is not None else float("nan"),
                "stat": stat_val,
                "p": float(test.get("p", float("nan"))),
            }
            if "df" in test:
                row["df"] = test.get("df")
            backup_rows.append(row)

    _append_backup_rows(backup_2x2)

    meta = {
        "n_subjects": int(df["subject"].nunique()),
        "phase_labels": sorted(df["phase"].unique().tolist()),
        "roi_included": True,
        "warnings": meta_warnings,
        "backup_2x2_used": bool(backup_rows),
    }

    return {
        "fixed_effects": fixed_effects or [],
        "contrasts": contrasts,
        "backup_rows": backup_rows,
        "meta": meta,
    }


def _format_results_excel(results: dict, excel_path: Path) -> None:
    """Handle the format results excel step for the Stats PySide6 workflow."""
    fixed_effects_df = pd.DataFrame(results.get("fixed_effects") or [])
    if fixed_effects_df.empty:
        fixed_effects_df = pd.DataFrame(
            columns=["roi", "condition", "effect", "estimate", "se", "stat", "p"]
        )
    else:
        fixed_effects_df = fixed_effects_df.reindex(
            columns=["roi", "condition", "effect", "estimate", "se", "stat", "p"],
        )

    contrasts_df = pd.DataFrame(results.get("effects_of_interest", {}).get("contrasts") or [])
    if contrasts_df.empty:
        contrasts_df = pd.DataFrame(
            columns=["roi", "condition", "label", "estimate", "se", "stat", "p"]
        )
    else:
        contrasts_df = contrasts_df.reindex(
            columns=["roi", "condition", "label", "estimate", "se", "stat", "p"],
        )

    backup_rows_df = pd.DataFrame(results.get("backup_2x2_results") or [])
    if backup_rows_df.empty:
        backup_rows_df = pd.DataFrame(
            columns=["roi", "condition", "effect", "estimate", "se", "stat", "p", "df"]
        )
    else:
        backup_rows_df = backup_rows_df.reindex(
            columns=["roi", "condition", "effect", "estimate", "se", "stat", "p", "df"],
        )

    with pd.ExcelWriter(excel_path, engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(writer, fixed_effects_df, "Fixed Effects", logger.info)
        _auto_format_and_write_excel(writer, contrasts_df, "Contrasts", logger.info)
        _auto_format_and_write_excel(writer, backup_rows_df, "Backup 2x2", logger.info)


def run_cross_phase_lmm_job(progress_cb, message_cb, *, job_spec_path: str):
    """Run the cross-phase LMM job described by ``job_spec_path``.

    Mirrors the legacy CLI behaviour but iterates over every ROI × condition.
    """

    job_path = Path(job_spec_path)
    if not job_path.is_file():
        raise FileNotFoundError(f"Job spec not found: {job_spec_path}")

    spec = json.loads(job_path.read_text())
    if spec.get("mode") != "cross_phase_lmm":
        raise ValueError("Invalid job spec for cross-phase LMM.")

    output_spec = spec.get("output", {})
    if "summary_json" not in output_spec or "excel_report" not in output_spec:
        raise ValueError("Cross-phase LMM output paths must be provided.")

    summary_path = Path(output_spec["summary_json"])
    excel_path = Path(output_spec["excel_report"])

    phase_projects = spec.get("phase_projects")
    if not isinstance(phase_projects, dict) or len(phase_projects) < 2:
        raise ValueError("Cross-phase LMM requires at least two phase projects.")

    roi_map = spec.get("roi_map", {})
    base_freq = float(spec.get("base_freq", 6.0))

    phase_data: Dict[str, Dict[str, Dict[str, Dict[str, float]]]] = {}
    phase_group_maps: Dict[str, Dict[str, str]] = {}
    phase_code_map: Dict[str, str] = {}

    phase_labels: list[str] = list(phase_projects.keys())
    conditions_to_analyze, missing_by_phase = _condition_intersection_with_order(
        phase_projects
    )

    for phase_label, project_spec in phase_projects.items():
        subjects = project_spec.get("subjects") or []
        conditions = project_spec.get("conditions") or []
        subject_data = project_spec.get("subject_data") or {}
        group_map = project_spec.get("group_map") or project_spec.get("subject_groups") or {}
        phase_code = (project_spec.get("phase_code") or "").strip()
        if phase_code:
            phase_code_map[phase_label] = phase_code
        group_levels_in_phase = sorted(
            {str(val).strip().upper() for val in group_map.values() if str(val).strip()}
        )
        logger.info(
            "lela_phase_group_summary",
            extra={"phase_label": phase_label, "phase_code": phase_code or None, "group_codes": group_levels_in_phase},
        )

        message_cb(
            f"Preparing summed BCA data for phase '{phase_label}' ({len(subjects)} subjects, {len(conditions)} conditions)…"
        )

        with single_threaded_blas():
            bca_data = prepare_all_subject_summed_bca_data(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                rois=roi_map,
                log_func=logger.info,
            )

        if bca_data is None:
            raise ValueError(
                f"Lela Mode aborted: summed BCA data unavailable for phase '{phase_label}'. Please verify the scanned files for this project."
            )
        phase_data[phase_label] = bca_data
        phase_group_maps[phase_label] = group_map

    for phase_label, missing in missing_by_phase.items():
        if missing:
            message_cb(
                f"[Between] Lela Mode: phase '{phase_label}' has conditions not present in all phases and will be skipped: {sorted(missing)}"
            )

    if not conditions_to_analyze:
        raise ValueError("No shared conditions found across phases for Lela Mode.")

    df_long = build_cross_phase_long_df(
        phase_data,
        phase_group_maps,
        tuple(phase_labels),
        phase_label_to_code=phase_code_map,
    )
    df_long = df_long.rename(columns={"value": "bca"})

    group_levels = [g for g in sorted(df_long["group"].dropna().unique().tolist()) if str(g).strip()]
    phase_levels = [p for p in sorted(df_long["phase"].dropna().unique().tolist()) if str(p).strip()]
    logger.info(
        "lela_phase_levels",
        extra={"group_levels": group_levels, "phase_levels": phase_levels, "phase_codes": phase_code_map},
    )
    message_cb(
        "[Between] Lela Mode: group codes "
        f"{group_levels if group_levels else '[]'}, "
        f"phase codes {phase_levels if phase_levels else '[]'}"
    )

    if len(group_levels) != 2 or len(phase_levels) != 2:
        raise ValueError(
            "Cross-phase LMM requires exactly 2 groups and 2 phases after merging datasets; "
            f"found groups={group_levels}, phases={phase_levels}."
        )

    if conditions_to_analyze:
        df_long = df_long[df_long["condition"].isin(conditions_to_analyze)]

    available_conditions: list[str] = []
    for condition in conditions_to_analyze:
        cond_df = df_long[df_long["condition"] == condition]
        if cond_df.empty:
            message_cb(
                f"[Between] Lela Mode: condition '{condition}' has no subjects with both phases; skipping."
            )
            continue
        available_conditions.append(condition)

    subject_count = int(df_long["subject"].nunique()) if not df_long.empty else 0
    if subject_count == 0 or not available_conditions:
        raise ValueError("Cross-phase LMM requires at least one subject after phase intersection.")
    message_cb(f"Prepared cross-phase dataset with {subject_count} subjects.")
    message_cb("Running cross-phase LMM with factors: group, phase")

    roi_order: list[str] = []
    df_roi_levels = sorted(df_long["roi"].unique().tolist())
    if isinstance(roi_map, dict) and roi_map:
        for name in roi_map.keys():
            if name in df_roi_levels:
                roi_order.append(name)
    if not roi_order:
        roi_order = df_roi_levels

    fixed_rows: list[dict] = []
    contrast_rows: list[dict] = []
    backup_rows: list[dict] = []
    per_roi_meta: dict[str, dict] = {}
    aggregated_warnings: list[str] = []

    total_runs = 0
    successful_runs = 0

    for roi_name in roi_order:
        roi_meta_warnings: list[str] = []
        backup_used = False
        for condition in available_conditions:
            message_cb(
                f"Running cross-phase LMM for ROI '{roi_name}', condition '{condition}'"
            )
            total_runs += 1
            try:
                df_subset = _subset_df_for_condition(
                    df_long, condition=condition, roi=roi_name
                )
                results = _run_roi_condition_lmm(
                    df_subset,
                    roi=roi_name,
                    condition=condition,
                    phase_labels=phase_labels,
                    message_cb=message_cb,
                )
            except Exception as exc:  # noqa: BLE001
                message_cb(
                    f"Cross-phase MixedLM failed for ROI '{roi_name}', condition '{condition}': {exc}"
                )
                aggregated_warnings.append(f"{roi_name}/{condition}: {exc}")
                roi_meta_warnings.append(str(exc))
                backup_rows.extend(
                    [
                        {
                            "roi": roi_name,
                            "condition": condition,
                            "effect": "error",
                            "estimate": float("nan"),
                            "se": float("nan"),
                            "stat": float("nan"),
                            "p": float("nan"),
                        }
                    ]
                )
                backup_used = True
                continue

            successful_runs += 1
            for row in results.get("fixed_effects", []):
                row_with_meta = dict(row)
                row_with_meta.setdefault("roi", roi_name)
                row_with_meta.setdefault("condition", condition)
                fixed_rows.append(row_with_meta)

            for contrast in results.get("contrasts", []):
                contrast_with_meta = dict(contrast)
                contrast_with_meta.setdefault("roi", roi_name)
                contrast_with_meta.setdefault("condition", condition)
                contrast_rows.append(contrast_with_meta)

            for backup_row in results.get("backup_rows", []):
                backup_rows.append(backup_row)
            if results.get("meta", {}).get("backup_2x2_used"):
                backup_used = True

            warning_list: Iterable[str] = results.get("meta", {}).get("warnings", []) or []
            for warning in warning_list:
                aggregated_warnings.append(f"{roi_name}/{condition}: {warning}")
                roi_meta_warnings.append(warning)

        per_roi_meta[roi_name] = {
            "warnings": roi_meta_warnings,
            "backup_2x2_used": backup_used,
        }

    combined_meta = {
        "n_subjects": subject_count,
        "phase_labels": sorted(df_long["phase"].unique().tolist()),
        "roi_included": True,
        "warnings": aggregated_warnings,
        "per_roi": per_roi_meta,
        "backup_2x2_used": any(meta.get("backup_2x2_used") for meta in per_roi_meta.values()),
    }

    if total_runs > 0 and successful_runs == 0:
        message_cb(
            "Cross-phase MixedLM failed for all ROI/condition pairs; aborting without writing results."
        )
        raise RuntimeError(
            "Cross-phase MixedLM failed for all ROI/condition pairs; see logs for details."
        )

    results_payload = {
        "fixed_effects": fixed_rows,
        "effects_of_interest": {
            "focal_condition": "ALL",
            "focal_rois": roi_order,
            "conditions": available_conditions,
            "contrasts": contrast_rows,
        },
        "backup_2x2_results": backup_rows,
        "meta": combined_meta,
    }

    summary_path.parent.mkdir(parents=True, exist_ok=True)
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    summary_path.write_text(json.dumps(results_payload, indent=2))
    _format_results_excel(results_payload, excel_path)

    if combined_meta.get("backup_2x2_used"):
        message_cb(
            "MixedLM did not converge for at least one ROI/condition; backup 2x2 results are available in the 'Backup 2x2' sheet."
        )

    message_cb("Cross-phase LMM analysis complete.")
    return {"result": "ok"}

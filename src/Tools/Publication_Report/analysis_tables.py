"""Publication-report source tables derived from processed workbooks."""

from __future__ import annotations

from collections.abc import Callable
from itertools import combinations
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Publication_Maps.excel_inputs import ELECTRODE_COLUMN, find_frequency_column
from Tools.Publication_Maps.scalp_io import biosemi64_names_upper, normalize_electrode_name
from Tools.Publication_Report.discovery import WorkbookEntry
from Tools.Publication_Report.models import (
    BASE_RATE_SUMMARY_SHEET,
    COMPARISON_AGREEMENT_SHEET,
    CONDITION_COMPARISONS_SHEET,
    CONDITION_PAIRS_BY_ROI_SHEET,
    ELECTRODE_Z_SCORES_SHEET,
    GROUP_ELECTRODE_SIGNIFICANCE_SHEET,
    HARMONIC_SELECTION_SHEET,
    INDIVIDUAL_DETECTABILITY_SHEET,
    INDIVIDUAL_DETECTABILITY_COUNTS_SHEET,
    PLANNED_LATERALIZATION_SHEET,
    ROI_HARMONIC_SUMMARY_SHEET,
    ROI_HARMONIC_VALUES_SHEET,
    ROI_RESPONSE_SUMMARY_SHEET,
    STATS_POSTHOC_SHEET,
    STATS_RM_ANOVA_SHEET,
    STATS_WORKFLOW_SUMMARY_SHEET,
    PublicationReportRequest,
    ReportRoi,
    Z_SCORE_REPORT_SHEET,
)
from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    GROUP_SIGNIFICANT_POLICY_NAME,
)
from Tools.Stats.workers import stats_workers

BCA_SHEET = "BCA (uV)"
SNR_SHEET = "SNR"
Z_SHEET = "Z Score"
FFT_AMPLITUDE_SHEET = "FFT Amplitude (uV)"
FULL_FFT_AMPLITUDE_SHEET = "FullFFT Amplitude (uV)"
FULL_SNR_SHEET = "FullSNR"

P_ALPHA = 0.05
WHOLE_SCALP_ROI = "Whole scalp"


def build_analysis_frames(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    included_subjects: tuple[str, ...],
    selected_conditions: tuple[str, ...],
    warnings: list[str],
) -> dict[str, pd.DataFrame]:
    """Build additive manuscript-source tables from selected workbooks."""

    included = {subject.upper() for subject in included_subjects}
    included_workbooks = [
        entry for entry in workbooks if entry.subject_id.upper() in included
    ]
    selected_harmonics, selection_frame = _harmonic_selection_frame(
        request=request,
        workbooks=included_workbooks,
        selected_conditions=selected_conditions,
        warnings=warnings,
    )
    roi_value_frame = _roi_harmonic_values(
        request=request,
        workbooks=included_workbooks,
        selected_harmonics=selected_harmonics,
        warnings=warnings,
    )
    roi_harmonic_summary = _roi_harmonic_summary(roi_value_frame, request.z_thresholds)
    roi_response_summary, response_values = _roi_response_summary(
        roi_value_frame,
        selected_harmonics=selected_harmonics,
    )
    stats_rm_anova, stats_posthoc, stats_workflow_summary = _stats_rm_anova_workflow(
        request=request,
        workbooks=included_workbooks,
        included_subjects=included_subjects,
        selected_conditions=selected_conditions,
        warnings=warnings,
    )
    condition_comparisons = _condition_comparisons_from_stats(stats_rm_anova)
    condition_pairs = _condition_pairs_by_roi(response_values)
    agreement = _comparison_agreement(stats_posthoc, condition_pairs)
    planned_lateralization = _planned_lateralization_contrasts(response_values)
    individual_detectability, electrode_z_scores = _individual_detectability_frame(
        request=request,
        workbooks=included_workbooks,
        selected_harmonics=selected_harmonics,
        warnings=warnings,
    )
    individual_detectability_counts = _individual_detectability_counts(individual_detectability)
    group_electrode_significance = _group_electrode_significance(
        electrode_z_scores,
        request.z_thresholds,
    )
    base_rate_summary = _base_rate_summary(
        request=request,
        workbooks=included_workbooks,
        selected_conditions=selected_conditions,
        warnings=warnings,
    )
    z_score_report = _z_score_report(
        harmonic_selection=selection_frame,
        roi_harmonic_summary=roi_harmonic_summary,
        base_rate_summary=base_rate_summary,
    )
    return {
        HARMONIC_SELECTION_SHEET: selection_frame,
        ROI_HARMONIC_VALUES_SHEET: roi_value_frame,
        ROI_HARMONIC_SUMMARY_SHEET: roi_harmonic_summary,
        ROI_RESPONSE_SUMMARY_SHEET: roi_response_summary,
        CONDITION_COMPARISONS_SHEET: condition_comparisons,
        STATS_RM_ANOVA_SHEET: stats_rm_anova,
        STATS_POSTHOC_SHEET: stats_posthoc,
        STATS_WORKFLOW_SUMMARY_SHEET: stats_workflow_summary,
        CONDITION_PAIRS_BY_ROI_SHEET: condition_pairs,
        COMPARISON_AGREEMENT_SHEET: agreement,
        PLANNED_LATERALIZATION_SHEET: planned_lateralization,
        ELECTRODE_Z_SCORES_SHEET: electrode_z_scores,
        GROUP_ELECTRODE_SIGNIFICANCE_SHEET: group_electrode_significance,
        INDIVIDUAL_DETECTABILITY_SHEET: individual_detectability,
        INDIVIDUAL_DETECTABILITY_COUNTS_SHEET: individual_detectability_counts,
        Z_SCORE_REPORT_SHEET: z_score_report,
        BASE_RATE_SUMMARY_SHEET: base_rate_summary,
    }


def _harmonic_selection_frame(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    selected_conditions: tuple[str, ...],
    warnings: list[str],
) -> tuple[tuple[float, ...], pd.DataFrame]:
    columns = [
        "harmonic_index",
        "target_frequency_hz",
        "matched_frequency_hz",
        "matched_column",
        "z_score",
        "selected",
        "excluded_base_rate",
        "exclusion_reason",
        "warning",
    ]
    if not workbooks:
        return (), pd.DataFrame(columns=columns)
    subject_data: dict[str, dict[str, str]] = {}
    for workbook in workbooks:
        subject_data.setdefault(workbook.subject_id, {})[workbook.condition] = str(workbook.path)
    subjects = sorted(subject_data)
    rois = {"All scalp electrodes": sorted(biosemi64_names_upper())}

    def log_func(message: str) -> None:
        if "warning" in message.lower() or "error" in message.lower():
            warnings.append(message)

    try:
        selection = build_group_significant_harmonic_selection(
            subjects=subjects,
            conditions=list(selected_conditions),
            subject_data=subject_data,
            base_frequency_hz=float(request.base_frequency_hz),
            rois=rois,
            log_func=log_func,
            settings=DVPolicySettings(),
            max_freq=float(request.bca_upper_limit_hz),
            project_root=request.project_root,
        )
    except Exception as exc:
        warnings.append(
            "Could not compute Stats-selected group harmonics for the report: "
            f"{exc}"
        )
        return (), pd.DataFrame(columns=columns)

    rows = [
        {
            "harmonic_index": row.harmonic_index,
            "target_frequency_hz": row.target_frequency_hz,
            "matched_frequency_hz": row.matched_frequency_hz,
            "matched_column": row.matched_column,
            "z_score": row.z_score,
            "selected": row.selected,
            "excluded_base_rate": row.excluded_base_rate,
            "exclusion_reason": row.exclusion_reason,
            "warning": row.warning,
        }
        for row in selection.rows
    ]
    selected = tuple(round(float(value), 4) for value in selection.selected_harmonics_hz)
    return selected, pd.DataFrame(rows, columns=columns)


def _roi_harmonic_values(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    selected_harmonics: tuple[float, ...],
    warnings: list[str],
) -> pd.DataFrame:
    columns = [
        "condition",
        "subject_id",
        "roi",
        "roi_role",
        "harmonic_hz",
        "metric",
        "source_sheet",
        "source_column",
        "value",
        "valid_electrode_count",
        "missing_electrodes",
        "workbook_path",
    ]
    if not selected_harmonics:
        return pd.DataFrame(columns=columns)
    rois = tuple(roi for roi in request.rois if roi.selected)
    if not rois:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for workbook in workbooks:
        for metric, sheet_name in (
            ("BCA_uV", BCA_SHEET),
            ("SNR", SNR_SHEET),
            ("Z", Z_SHEET),
        ):
            frame = _read_sheet(workbook.path, sheet_name, warnings)
            if frame is None:
                continue
            for harmonic in selected_harmonics:
                column = find_frequency_column(frame.columns, harmonic)
                if column is None:
                    warnings.append(
                        f"Missing {sheet_name} column for {harmonic:g} Hz in "
                        f"{workbook.path.name}."
                    )
                    continue
                for roi in rois:
                    value, count, missing = _roi_mean(frame, roi, column.column_name)
                    rows.append(
                        {
                            "condition": workbook.condition,
                            "subject_id": workbook.subject_id,
                            "roi": roi.name,
                            "roi_role": roi.role,
                            "harmonic_hz": round(float(harmonic), 4),
                            "metric": metric,
                            "source_sheet": sheet_name,
                            "source_column": column.column_name,
                            "value": value,
                            "valid_electrode_count": count,
                            "missing_electrodes": ", ".join(missing),
                            "workbook_path": str(workbook.path),
                        }
                    )
    return pd.DataFrame(rows, columns=columns)


def _roi_harmonic_summary(
    values: pd.DataFrame,
    z_thresholds: tuple[float, ...],
) -> pd.DataFrame:
    columns = [
        "condition",
        "roi",
        "roi_role",
        "harmonic_hz",
        "metric",
        "n",
        "mean",
        "sd",
        "sem",
        "median",
        "min",
        "max",
        "z_one_tailed_p",
        *[f"z_gt_{threshold:g}" for threshold in z_thresholds],
    ]
    if values.empty:
        return pd.DataFrame(columns=columns)
    frame = values.copy()
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    rows: list[dict[str, object]] = []
    grouped = frame.groupby(["condition", "roi", "roi_role", "harmonic_hz", "metric"], dropna=False)
    for keys, group in grouped:
        condition, roi, role, harmonic, metric = keys
        numeric = _finite_array(group["value"])
        mean_value = float(np.mean(numeric)) if len(numeric) else np.nan
        row = {
            "condition": condition,
            "roi": roi,
            "roi_role": role,
            "harmonic_hz": harmonic,
            "metric": metric,
            "n": int(len(numeric)),
            "mean": mean_value,
            "sd": _sd(numeric),
            "sem": _sem(numeric),
            "median": float(np.median(numeric)) if len(numeric) else np.nan,
            "min": float(np.min(numeric)) if len(numeric) else np.nan,
            "max": float(np.max(numeric)) if len(numeric) else np.nan,
            "z_one_tailed_p": _z_p_value(mean_value) if metric == "Z" else np.nan,
        }
        for threshold in z_thresholds:
            row[f"z_gt_{threshold:g}"] = bool(metric == "Z" and mean_value > threshold)
        rows.append(row)
    return pd.DataFrame(rows, columns=columns)


def _roi_response_summary(
    roi_values: pd.DataFrame,
    *,
    selected_harmonics: tuple[float, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    response_columns = [
        "condition",
        "subject_id",
        "roi",
        "roi_role",
        "selected_harmonics_hz",
        "summed_bca_uv",
    ]
    summary_columns = [
        "condition",
        "roi",
        "roi_role",
        "selected_harmonics_hz",
        "n",
        "mean_summed_bca_uv",
        "sd_summed_bca_uv",
        "median_summed_bca_uv",
        "min_summed_bca_uv",
        "max_summed_bca_uv",
        "t_statistic",
        "df",
        "p_value_two_tailed",
        "cohens_dz",
    ]
    if roi_values.empty or not selected_harmonics:
        return pd.DataFrame(columns=summary_columns), pd.DataFrame(columns=response_columns)
    bca = roi_values.loc[roi_values["metric"] == "BCA_uV"].copy()
    if bca.empty:
        return pd.DataFrame(columns=summary_columns), pd.DataFrame(columns=response_columns)
    bca["value"] = pd.to_numeric(bca["value"], errors="coerce")
    response = (
        bca.groupby(["condition", "subject_id", "roi", "roi_role"], dropna=False)["value"]
        .sum(min_count=1)
        .reset_index(name="summed_bca_uv")
    )
    response["selected_harmonics_hz"] = ", ".join(f"{freq:g}" for freq in selected_harmonics)
    response = response[response_columns]

    rows: list[dict[str, object]] = []
    for keys, group in response.groupby(["condition", "roi", "roi_role"], dropna=False):
        condition, roi, role = keys
        numeric = _finite_array(group["summed_bca_uv"])
        t_stat, p_value = _one_sample_t(numeric)
        rows.append(
            {
                "condition": condition,
                "roi": roi,
                "roi_role": role,
                "selected_harmonics_hz": ", ".join(f"{freq:g}" for freq in selected_harmonics),
                "n": int(len(numeric)),
                "mean_summed_bca_uv": float(np.mean(numeric)) if len(numeric) else np.nan,
                "sd_summed_bca_uv": _sd(numeric),
                "median_summed_bca_uv": float(np.median(numeric)) if len(numeric) else np.nan,
                "min_summed_bca_uv": float(np.min(numeric)) if len(numeric) else np.nan,
                "max_summed_bca_uv": float(np.max(numeric)) if len(numeric) else np.nan,
                "t_statistic": t_stat,
                "df": int(len(numeric) - 1) if len(numeric) >= 2 else np.nan,
                "p_value_two_tailed": p_value,
                "cohens_dz": _cohens_dz(numeric),
            }
        )
    return pd.DataFrame(rows, columns=summary_columns), response


def _stats_rm_anova_workflow(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    included_subjects: tuple[str, ...],
    selected_conditions: tuple[str, ...],
    warnings: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Run the existing Stats RM-ANOVA and interaction-posthoc workflow."""

    summary_rows: list[dict[str, object]] = []
    subject_data = _stats_subject_data(workbooks)
    subjects = [subject for subject in included_subjects if subject in subject_data]
    rois = _stats_rois(request)
    if len(subjects) < 2 or len(selected_conditions) < 2 or not rois:
        note = "Stats RM-ANOVA requires at least two participants, two conditions, and one ROI."
        return (
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame([{"step": "stats_rm_anova_workflow", "status": "skipped", "note": note}]),
        )

    messages: list[str] = []

    def progress(_value: int) -> None:
        return None

    def message(message_text: str) -> None:
        messages.append(str(message_text))

    common_kwargs = {
        "subjects": subjects,
        "conditions": list(selected_conditions),
        "conditions_all": list(selected_conditions),
        "subject_data": subject_data,
        "base_freq": float(request.base_frequency_hz),
        "alpha": P_ALPHA,
        "rois": rois,
        "rois_all": rois,
        "dv_policy": {"name": GROUP_SIGNIFICANT_POLICY_NAME},
        "outlier_exclusion_enabled": True,
        "outlier_abs_limit": 50.0,
        "manual_excluded_pids": [],
        "max_freq": float(request.bca_upper_limit_hz),
        "project_root": str(request.project_root),
    }

    anova_df = pd.DataFrame()
    posthoc_df = pd.DataFrame()
    anova_status = "not_run"
    posthoc_status = "not_run"
    try:
        anova_payload = stats_workers.run_rm_anova(
            progress,
            message,
            **{key: value for key, value in common_kwargs.items() if key != "alpha"},
        )
        candidate = anova_payload.get("anova_df_results") if isinstance(anova_payload, dict) else None
        if isinstance(candidate, pd.DataFrame):
            anova_df = candidate.copy()
            _copy_attrs(candidate, anova_df)
        anova_status = "complete"
        run_report = anova_payload.get("run_report") if isinstance(anova_payload, dict) else None
        _append_run_report_summary(summary_rows, "rm_anova", run_report)
    except Exception as exc:
        anova_status = "failed"
        warnings.append(f"Stats RM-ANOVA workflow failed: {exc}")

    try:
        posthoc_payload = stats_workers.run_posthoc(
            progress,
            message,
            direction="both",
            **common_kwargs,
        )
        candidate = posthoc_payload.get("results_df") if isinstance(posthoc_payload, dict) else None
        if isinstance(candidate, pd.DataFrame):
            posthoc_df = candidate.copy()
            _copy_attrs(candidate, posthoc_df)
        posthoc_status = "complete"
        run_report = posthoc_payload.get("run_report") if isinstance(posthoc_payload, dict) else None
        _append_run_report_summary(summary_rows, "posthoc", run_report)
    except Exception as exc:
        posthoc_status = "failed"
        warnings.append(f"Stats posthoc workflow failed: {exc}")

    summary_rows.extend(
        [
            {
                "step": "rm_anova",
                "status": anova_status,
                "note": _attrs_note(anova_df),
            },
            {
                "step": "interaction_posthoc",
                "status": posthoc_status,
                "note": "BH-FDR posthocs from Tools.Stats.analysis.posthoc_tests.",
            },
            {
                "step": "stats_messages",
                "status": "info",
                "note": "\n".join(messages[-25:]),
            },
        ]
    )
    return anova_df, posthoc_df, pd.DataFrame(summary_rows)


def _condition_comparisons_from_stats(stats_rm_anova: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "source",
        "effect",
        "f_statistic",
        "df_num",
        "df_den",
        "p_value",
        "p_value_gg",
        "p_value_hf",
        "partial_eta_squared",
        "significant_uncorrected",
        "significant_gg",
        "significant_hf",
    ]
    if stats_rm_anova.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for _index, row in stats_rm_anova.iterrows():
        p_value = _row_value(row, "Pr > F")
        p_gg = _row_value(row, "Pr > F (GG)")
        p_hf = _row_value(row, "Pr > F (HF)")
        rows.append(
            {
                "source": "Stats RM-ANOVA",
                "effect": _row_value(row, "Effect"),
                "f_statistic": _row_value(row, "F Value"),
                "df_num": _row_value(row, "Num DF"),
                "df_den": _row_value(row, "Den DF"),
                "p_value": p_value,
                "p_value_gg": p_gg,
                "p_value_hf": p_hf,
                "partial_eta_squared": _row_value(row, "partial eta squared"),
                "significant_uncorrected": _p_is_sig(p_value),
                "significant_gg": _p_is_sig(p_gg),
                "significant_hf": _p_is_sig(p_hf),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _condition_pairs_by_roi(response_values: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "roi",
        "condition_a",
        "condition_b",
        "n_complete",
        "mean_a",
        "mean_b",
        "mean_difference_a_minus_b",
        "t_statistic",
        "df",
        "p_value_two_tailed",
        "cohens_dz",
        "direction",
    ]
    if response_values.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for roi, group in response_values.groupby("roi", dropna=False):
        wide = group.pivot_table(
            index="subject_id",
            columns="condition",
            values="summed_bca_uv",
            aggfunc="mean",
        )
        for condition_a, condition_b in combinations(sorted(wide.columns), 2):
            paired = wide[[condition_a, condition_b]].dropna(axis=0, how="any")
            a = _finite_array(paired[condition_a])
            b = _finite_array(paired[condition_b])
            if len(a) != len(b) or len(a) < 2:
                t_stat = p_value = dz = np.nan
                direction = "insufficient_complete_pairs"
            else:
                result = stats.ttest_rel(a, b, nan_policy="omit")
                t_stat = float(result.statistic)
                p_value = float(result.pvalue)
                diff = a - b
                dz = _cohens_dz(diff)
                direction = _direction(float(np.mean(diff)))
            rows.append(
                {
                    "roi": roi,
                    "condition_a": condition_a,
                    "condition_b": condition_b,
                    "n_complete": int(len(a)),
                    "mean_a": float(np.mean(a)) if len(a) else np.nan,
                    "mean_b": float(np.mean(b)) if len(b) else np.nan,
                    "mean_difference_a_minus_b": (
                        float(np.mean(a - b)) if len(a) == len(b) and len(a) else np.nan
                    ),
                    "t_statistic": t_stat,
                    "df": int(len(a) - 1) if len(a) >= 2 else np.nan,
                    "p_value_two_tailed": p_value,
                    "cohens_dz": dz,
                    "direction": direction,
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _planned_lateralization_contrasts(response_values: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "planned_family",
        "contrast_type",
        "condition",
        "condition_a",
        "condition_b",
        "left_roi",
        "right_roi",
        "n_complete",
        "mean_left_uv",
        "mean_right_uv",
        "mean_right_minus_left_uv",
        "mean_right_minus_left_condition_a_uv",
        "mean_right_minus_left_condition_b_uv",
        "mean_difference_of_lateralization_uv",
        "t_statistic",
        "df",
        "p_value_two_tailed",
        "p_bonferroni_planned_family",
        "p_holm_planned_family",
        "p_bh_planned_family",
        "cohens_dz",
        "direction",
        "interpretation_note",
    ]
    if response_values.empty:
        return pd.DataFrame(columns=columns)

    frame = response_values.copy()
    left_roi = _find_named_level(frame["roi"], _left_ot_roi_match)
    right_roi = _find_named_level(frame["roi"], _right_ot_roi_match)
    semantic_condition = _find_named_level(frame["condition"], _semantic_condition_match)
    color_condition = _find_color_condition(frame["condition"])
    if not left_roi or not right_roi or not semantic_condition or not color_condition:
        return pd.DataFrame(columns=columns)

    family = "planned_semantic_color_lot_rot_lateralization"
    rows: list[dict[str, object]] = []
    lateralization_rows = [
        _single_condition_lateralization_row(
            frame,
            planned_family=family,
            condition=semantic_condition,
            left_roi=left_roi,
            right_roi=right_roi,
            note=(
                "Planned semantic LOT-ROT lateralization contrast; not included "
                "in the full exploratory posthoc FDR family."
            ),
        ),
        _single_condition_lateralization_row(
            frame,
            planned_family=family,
            condition=color_condition,
            left_roi=left_roi,
            right_roi=right_roi,
            note=(
                "Planned low-level color LOT-ROT comparator contrast; corrected "
                "only with the semantic lateralization contrast."
            ),
        ),
    ]
    valid_family_p = [row["p_value_two_tailed"] for row in lateralization_rows]
    bonferroni, holm, bh = _adjust_p_values(valid_family_p)
    for index, row in enumerate(lateralization_rows):
        row["p_bonferroni_planned_family"] = bonferroni[index]
        row["p_holm_planned_family"] = holm[index]
        row["p_bh_planned_family"] = bh[index]
        rows.append(row)

    rows.append(
        _lateralization_difference_row(
            frame,
            planned_family=family,
            condition_a=semantic_condition,
            condition_b=color_condition,
            left_roi=left_roi,
            right_roi=right_roi,
        )
    )
    return pd.DataFrame(rows, columns=columns)


def _single_condition_lateralization_row(
    response_values: pd.DataFrame,
    *,
    planned_family: str,
    condition: str,
    left_roi: str,
    right_roi: str,
    note: str,
) -> dict[str, object]:
    wide = _condition_roi_wide(response_values, condition=condition)
    paired = wide[[left_roi, right_roi]].dropna(axis=0, how="any") if {left_roi, right_roi} <= set(wide.columns) else pd.DataFrame()
    left = _finite_array(paired[left_roi]) if left_roi in paired else np.array([], dtype=float)
    right = _finite_array(paired[right_roi]) if right_roi in paired else np.array([], dtype=float)
    diff = right - left if len(left) == len(right) else np.array([], dtype=float)
    t_stat, p_value = _one_sample_t(diff)
    mean_diff = float(np.mean(diff)) if len(diff) else np.nan
    return {
        "planned_family": planned_family,
        "contrast_type": "condition_lateralization",
        "condition": condition,
        "condition_a": "",
        "condition_b": "",
        "left_roi": left_roi,
        "right_roi": right_roi,
        "n_complete": int(len(diff)),
        "mean_left_uv": float(np.mean(left)) if len(left) else np.nan,
        "mean_right_uv": float(np.mean(right)) if len(right) else np.nan,
        "mean_right_minus_left_uv": mean_diff,
        "mean_right_minus_left_condition_a_uv": np.nan,
        "mean_right_minus_left_condition_b_uv": np.nan,
        "mean_difference_of_lateralization_uv": np.nan,
        "t_statistic": t_stat,
        "df": int(len(diff) - 1) if len(diff) >= 2 else np.nan,
        "p_value_two_tailed": p_value,
        "p_bonferroni_planned_family": np.nan,
        "p_holm_planned_family": np.nan,
        "p_bh_planned_family": np.nan,
        "cohens_dz": _cohens_dz(diff),
        "direction": _right_left_direction(mean_diff),
        "interpretation_note": note,
    }


def _lateralization_difference_row(
    response_values: pd.DataFrame,
    *,
    planned_family: str,
    condition_a: str,
    condition_b: str,
    left_roi: str,
    right_roi: str,
) -> dict[str, object]:
    wide = response_values.pivot_table(
        index="subject_id",
        columns=["condition", "roi"],
        values="summed_bca_uv",
        aggfunc="mean",
    )
    required = [
        (condition_a, left_roi),
        (condition_a, right_roi),
        (condition_b, left_roi),
        (condition_b, right_roi),
    ]
    missing = [column for column in required if column not in wide.columns]
    if missing:
        diff_a = diff_b = contrast = np.array([], dtype=float)
    else:
        paired = wide[required].dropna(axis=0, how="any")
        diff_a = _finite_array(paired[(condition_a, right_roi)] - paired[(condition_a, left_roi)])
        diff_b = _finite_array(paired[(condition_b, right_roi)] - paired[(condition_b, left_roi)])
        contrast = diff_a - diff_b if len(diff_a) == len(diff_b) else np.array([], dtype=float)
    t_stat, p_value = _one_sample_t(contrast)
    mean_contrast = float(np.mean(contrast)) if len(contrast) else np.nan
    return {
        "planned_family": planned_family,
        "contrast_type": "lateralization_difference",
        "condition": "",
        "condition_a": condition_a,
        "condition_b": condition_b,
        "left_roi": left_roi,
        "right_roi": right_roi,
        "n_complete": int(len(contrast)),
        "mean_left_uv": np.nan,
        "mean_right_uv": np.nan,
        "mean_right_minus_left_uv": np.nan,
        "mean_right_minus_left_condition_a_uv": float(np.mean(diff_a)) if len(diff_a) else np.nan,
        "mean_right_minus_left_condition_b_uv": float(np.mean(diff_b)) if len(diff_b) else np.nan,
        "mean_difference_of_lateralization_uv": mean_contrast,
        "t_statistic": t_stat,
        "df": int(len(contrast) - 1) if len(contrast) >= 2 else np.nan,
        "p_value_two_tailed": p_value,
        "p_bonferroni_planned_family": np.nan,
        "p_holm_planned_family": np.nan,
        "p_bh_planned_family": np.nan,
        "cohens_dz": _cohens_dz(contrast),
        "direction": _lateralization_difference_direction(mean_contrast, condition_a, condition_b),
        "interpretation_note": (
            "Direct interaction-style planned contrast testing whether the "
            f"{right_roi} minus {left_roi} asymmetry differs between "
            f"{condition_a} and {condition_b}."
        ),
    }


def _condition_roi_wide(response_values: pd.DataFrame, *, condition: str) -> pd.DataFrame:
    subset = response_values.loc[response_values["condition"].astype(str) == condition]
    if subset.empty:
        return pd.DataFrame()
    return subset.pivot_table(
        index="subject_id",
        columns="roi",
        values="summed_bca_uv",
        aggfunc="mean",
    )


def _find_named_level(values: pd.Series, matcher: Callable[[str], bool]) -> str | None:
    unique_values = [str(value) for value in values.dropna().unique()]
    for value in unique_values:
        if matcher(value):
            return value
    return None


def _find_color_condition(values: pd.Series) -> str | None:
    unique_values = [str(value) for value in values.dropna().unique()]
    exact_priority = ("color response 1", "color response")
    keyed = {_label_key(value): value for value in unique_values}
    for key in exact_priority:
        if key in keyed:
            return keyed[key]
    return _find_named_level(values, _color_condition_match)


def _left_ot_roi_match(value: str) -> bool:
    key = _label_key(value)
    return key in {"lot", "left ot", "left occipito temporal"}


def _right_ot_roi_match(value: str) -> bool:
    key = _label_key(value)
    return key in {"rot", "right ot", "right occipito temporal"}


def _semantic_condition_match(value: str) -> bool:
    return "semantic" in _label_key(value)


def _color_condition_match(value: str) -> bool:
    key = _label_key(value)
    return "color" in key and not key.endswith(" 2")


def _label_key(value: str) -> str:
    return " ".join(str(value).strip().casefold().replace("_", " ").replace("-", " ").split())


def _right_left_direction(mean_diff: float) -> str:
    if not np.isfinite(mean_diff) or mean_diff == 0:
        return "no_direction"
    return "right_greater_than_left" if mean_diff > 0 else "left_greater_than_right"


def _lateralization_difference_direction(
    mean_diff: float,
    condition_a: str,
    condition_b: str,
) -> str:
    if not np.isfinite(mean_diff) or mean_diff == 0:
        return "no_direction"
    return (
        f"{condition_a}_asymmetry_greater"
        if mean_diff > 0
        else f"{condition_b}_asymmetry_greater"
    )


def _adjust_p_values(p_values: list[object]) -> tuple[list[float], list[float], list[float]]:
    numeric = np.array([_coerce_float(value) for value in p_values], dtype=float)
    valid_indices = [index for index, value in enumerate(numeric) if np.isfinite(value)]
    m = len(valid_indices)
    bonferroni = [np.nan] * len(numeric)
    holm = [np.nan] * len(numeric)
    bh = [np.nan] * len(numeric)
    if m == 0:
        return bonferroni, holm, bh

    for index in valid_indices:
        bonferroni[index] = float(min(numeric[index] * m, 1.0))

    ordered = sorted(valid_indices, key=lambda index: numeric[index])
    previous = 0.0
    for rank, index in enumerate(ordered):
        adjusted = min((m - rank) * numeric[index], 1.0)
        previous = max(previous, adjusted)
        holm[index] = float(previous)

    previous = 1.0
    for rank_from_end, index in enumerate(reversed(ordered), start=1):
        rank = m - rank_from_end + 1
        adjusted = min(numeric[index] * m / rank, previous, 1.0)
        previous = adjusted
        bh[index] = float(adjusted)
    return bonferroni, holm, bh


def _comparison_agreement(
    stats_posthoc: pd.DataFrame,
    condition_pairs: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "roi",
        "condition_a",
        "condition_b",
        "stats_posthoc_significant_fdr",
        "direct_pair_significant_uncorrected",
        "stats_posthoc_mean_diff",
        "direct_pair_mean_diff",
        "same_direction",
        "agreement",
        "note",
    ]
    if stats_posthoc.empty or condition_pairs.empty:
        return pd.DataFrame(columns=columns)
    if "Direction" not in stats_posthoc.columns:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    stats_rows = stats_posthoc.loc[
        stats_posthoc["Direction"].astype(str) == "condition_within_roi"
    ]
    for _index, row in stats_rows.iterrows():
        roi = str(_row_value(row, "ROI"))
        condition_a = str(_row_value(row, "Level_A"))
        condition_b = str(_row_value(row, "Level_B"))
        direct = condition_pairs.loc[
            (condition_pairs["roi"].astype(str) == roi)
            & (condition_pairs["condition_a"].astype(str) == condition_a)
            & (condition_pairs["condition_b"].astype(str) == condition_b)
        ]
        if direct.empty:
            direct = condition_pairs.loc[
                (condition_pairs["roi"].astype(str) == roi)
                & (condition_pairs["condition_a"].astype(str) == condition_b)
                & (condition_pairs["condition_b"].astype(str) == condition_a)
            ]
        direct_row = direct.iloc[0] if not direct.empty else None
        stats_sig = _bool_flag(_row_value(row, "Significant"))
        direct_p = direct_row.get("p_value_two_tailed", np.nan) if direct_row is not None else np.nan
        direct_sig = _p_is_sig(direct_p)
        stats_diff = _coerce_float(_row_value(row, "mean_diff"))
        direct_diff = (
            _coerce_float(direct_row.get("mean_difference_a_minus_b"))
            if direct_row is not None
            else np.nan
        )
        same_direction = _same_direction(stats_diff, direct_diff)
        agreement = bool(stats_sig == direct_sig and same_direction)
        rows.append(
            {
                "roi": roi,
                "condition_a": condition_a,
                "condition_b": condition_b,
                "stats_posthoc_significant_fdr": stats_sig,
                "direct_pair_significant_uncorrected": direct_sig,
                "stats_posthoc_mean_diff": stats_diff,
                "direct_pair_mean_diff": direct_diff,
                "same_direction": same_direction,
                "agreement": agreement,
                "note": (
                    "Stats posthoc and direct ROI-wise pair check agree."
                    if agreement
                    else "Stats posthoc and direct ROI-wise pair check differ or were incomplete."
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _individual_detectability_frame(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    selected_harmonics: tuple[float, ...],
    warnings: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    columns = [
        "condition",
        "subject_id",
        "roi",
        "electrode_scope",
        "selected_harmonics_hz",
        "tested_electrode_count",
        "mean_combined_z_all_electrodes",
        "fdr_alpha",
        "fdr_significant_electrode_count",
        "fdr_significant_electrodes",
        "mean_combined_z_fdr_significant",
        *[f"uncorrected_z_gt_{threshold:g}_count" for threshold in request.z_thresholds],
        "workbook_path",
    ]
    electrode_columns = [
        "condition",
        "subject_id",
        "roi",
        "electrode",
        "selected_harmonics_hz",
        "combined_z",
        "p_one_tailed",
        "fdr_q",
        "fdr_significant",
        *[f"z_gt_{threshold:g}" for threshold in request.z_thresholds],
        "workbook_path",
    ]
    if not selected_harmonics:
        return pd.DataFrame(columns=columns), pd.DataFrame(columns=electrode_columns)
    report_rois = tuple(roi for roi in request.rois if roi.selected)
    rows: list[dict[str, object]] = []
    electrode_rows: list[dict[str, object]] = []
    for workbook in workbooks:
        frame = _read_sheet(workbook.path, Z_SHEET, warnings)
        if frame is None:
            continue
        combined = _combined_z_by_electrode(frame, selected_harmonics, warnings, workbook.path)
        if combined.empty:
            continue
        combined["p_one_tailed"] = combined["combined_z"].map(_z_p_value)
        combined["fdr_q"] = _bh_fdr(combined["p_one_tailed"].to_numpy(dtype=float))
        combined["fdr_significant"] = combined["fdr_q"] <= P_ALPHA
        for roi in (ReportRoi(WHOLE_SCALP_ROI, tuple(combined["electrode"]), "detectability"), *report_rois):
            subset = _combined_subset(combined, roi)
            if subset.empty:
                continue
            for electrode_row in subset.itertuples(index=False):
                base_row = {
                    "condition": workbook.condition,
                    "subject_id": workbook.subject_id,
                    "roi": roi.name,
                    "electrode": getattr(electrode_row, "electrode"),
                    "selected_harmonics_hz": ", ".join(f"{freq:g}" for freq in selected_harmonics),
                    "combined_z": getattr(electrode_row, "combined_z"),
                    "p_one_tailed": getattr(electrode_row, "p_one_tailed"),
                    "fdr_q": getattr(electrode_row, "fdr_q"),
                    "fdr_significant": getattr(electrode_row, "fdr_significant"),
                    "workbook_path": str(workbook.path),
                }
                for threshold in request.z_thresholds:
                    base_row[f"z_gt_{threshold:g}"] = bool(
                        getattr(electrode_row, "combined_z") > threshold
                    )
                electrode_rows.append(base_row)
            sig = subset.loc[subset["fdr_significant"]]
            row = {
                "condition": workbook.condition,
                "subject_id": workbook.subject_id,
                "roi": roi.name,
                "electrode_scope": "all-workbook-electrodes" if roi.name == WHOLE_SCALP_ROI else "roi",
                "selected_harmonics_hz": ", ".join(f"{freq:g}" for freq in selected_harmonics),
                "tested_electrode_count": int(len(subset)),
                "mean_combined_z_all_electrodes": float(subset["combined_z"].mean()),
                "fdr_alpha": P_ALPHA,
                "fdr_significant_electrode_count": int(len(sig)),
                "fdr_significant_electrodes": ", ".join(sig["electrode"].astype(str)),
                "mean_combined_z_fdr_significant": (
                    float(sig["combined_z"].mean()) if not sig.empty else np.nan
                ),
                "workbook_path": str(workbook.path),
            }
            for threshold in request.z_thresholds:
                row[f"uncorrected_z_gt_{threshold:g}_count"] = int(
                    (subset["combined_z"] > threshold).sum()
                )
            rows.append(row)
    return pd.DataFrame(rows, columns=columns), pd.DataFrame(electrode_rows, columns=electrode_columns)


def _individual_detectability_counts(individual: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "condition",
        "roi",
        "participant_count",
        "participants_with_fdr_significant_electrodes",
        "percent_with_fdr_significant_electrodes",
        "mean_fdr_significant_electrode_count",
        "sd_fdr_significant_electrode_count",
        "max_fdr_significant_electrode_count",
    ]
    if individual.empty:
        return pd.DataFrame(columns=columns)
    frame = individual.copy()
    for column in (
        "fdr_significant_electrode_count",
        "mean_combined_z_all_electrodes",
        "mean_combined_z_fdr_significant",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(["condition", "roi"], dropna=False):
        condition, roi = keys
        counts = _finite_array(group["fdr_significant_electrode_count"])
        participant_count = int(group["subject_id"].nunique())
        participants_with = int((counts > 0).sum())
        rows.append(
            {
                "condition": condition,
                "roi": roi,
                "participant_count": participant_count,
                "participants_with_fdr_significant_electrodes": participants_with,
                "percent_with_fdr_significant_electrodes": (
                    participants_with / participant_count if participant_count else np.nan
                ),
                "mean_fdr_significant_electrode_count": (
                    float(np.mean(counts)) if len(counts) else np.nan
                ),
                "sd_fdr_significant_electrode_count": _sd(counts),
                "max_fdr_significant_electrode_count": (
                    float(np.max(counts)) if len(counts) else np.nan
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _group_electrode_significance(
    electrode_z_scores: pd.DataFrame,
    z_thresholds: tuple[float, ...],
) -> pd.DataFrame:
    columns = [
        "condition",
        "roi",
        "threshold_method",
        "participant_count",
        "tested_electrode_count",
        "participants_with_significant_electrodes",
        "mean_significant_electrode_count",
        "sd_significant_electrode_count",
        "median_significant_electrode_count",
        "max_significant_electrode_count",
        "electrodes_significant_in_any_participant_count",
        "electrodes_significant_in_any_participant",
        "expected_by_chance_per_participant",
    ]
    if electrode_z_scores.empty:
        return pd.DataFrame(columns=columns)
    frame = electrode_z_scores.copy()
    rows: list[dict[str, object]] = []
    threshold_specs = [("fdr_q<=0.05", "fdr_significant", np.nan)]
    threshold_specs.extend(
        (f"z>{threshold:g}", f"z_gt_{threshold:g}", _z_p_value(float(threshold)))
        for threshold in z_thresholds
    )
    for keys, group in frame.groupby(["condition", "roi"], dropna=False):
        condition, roi = keys
        participant_count = int(group["subject_id"].nunique())
        tested_count = int(group["electrode"].nunique())
        for method, column, p_threshold in threshold_specs:
            if column not in group.columns:
                continue
            sig = group.loc[group[column].fillna(False).astype(bool)]
            counts = (
                sig.groupby("subject_id")["electrode"].nunique()
                .reindex(sorted(group["subject_id"].unique()), fill_value=0)
                .to_numpy(dtype=float)
            )
            any_electrodes = sorted(sig["electrode"].dropna().astype(str).unique())
            rows.append(
                {
                    "condition": condition,
                    "roi": roi,
                    "threshold_method": method,
                    "participant_count": participant_count,
                    "tested_electrode_count": tested_count,
                    "participants_with_significant_electrodes": int((counts > 0).sum()),
                    "mean_significant_electrode_count": (
                        float(np.mean(counts)) if len(counts) else np.nan
                    ),
                    "sd_significant_electrode_count": _sd(counts),
                    "median_significant_electrode_count": (
                        float(np.median(counts)) if len(counts) else np.nan
                    ),
                    "max_significant_electrode_count": (
                        float(np.max(counts)) if len(counts) else np.nan
                    ),
                    "electrodes_significant_in_any_participant_count": len(any_electrodes),
                    "electrodes_significant_in_any_participant": ", ".join(any_electrodes),
                    "expected_by_chance_per_participant": (
                        tested_count * p_threshold if np.isfinite(p_threshold) else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _base_rate_summary(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    selected_conditions: tuple[str, ...],
    warnings: list[str],
) -> pd.DataFrame:
    columns = [
        "condition",
        "roi",
        "base_harmonic_hz",
        "metric",
        "source_sheet",
        "n",
        "mean",
        "sd",
        "sem",
        "median",
        "z_one_tailed_p",
        "significant_z_gt_1_64",
    ]
    roi = request.base_rate_roi
    if roi is None or not roi.selected:
        return pd.DataFrame(columns=columns)
    harmonics = _base_rate_harmonics(request.base_frequency_hz, request.bca_upper_limit_hz)
    if not harmonics:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []
    for condition in selected_conditions:
        condition_workbooks = [entry for entry in workbooks if entry.condition == condition]
        for metric, sheet_candidates in (
            ("FFT_amplitude_uV", (FFT_AMPLITUDE_SHEET, FULL_FFT_AMPLITUDE_SHEET)),
            ("SNR", (SNR_SHEET, FULL_SNR_SHEET)),
            ("Z", (Z_SHEET,)),
        ):
            for harmonic in harmonics:
                values: list[float] = []
                source_sheet_used = ""
                for workbook in condition_workbooks:
                    frame, source_sheet = _read_first_available_sheet(
                        workbook.path,
                        sheet_candidates,
                        warnings,
                    )
                    if frame is None:
                        continue
                    source_sheet_used = source_sheet
                    column = find_frequency_column(frame.columns, harmonic)
                    if column is None:
                        continue
                    value, _count, _missing = _roi_mean(frame, roi, column.column_name)
                    if np.isfinite(value):
                        values.append(value)
                numeric = np.asarray(values, dtype=float)
                mean_value = float(np.mean(numeric)) if len(numeric) else np.nan
                rows.append(
                    {
                        "condition": condition,
                        "roi": roi.name,
                        "base_harmonic_hz": round(float(harmonic), 4),
                        "metric": metric,
                        "source_sheet": source_sheet_used,
                        "n": int(len(numeric)),
                        "mean": mean_value,
                        "sd": _sd(numeric),
                        "sem": _sem(numeric),
                        "median": float(np.median(numeric)) if len(numeric) else np.nan,
                        "z_one_tailed_p": _z_p_value(mean_value) if metric == "Z" else np.nan,
                        "significant_z_gt_1_64": bool(metric == "Z" and mean_value > 1.64),
                    }
                )
    return pd.DataFrame(rows, columns=columns)


def _z_score_report(
    *,
    harmonic_selection: pd.DataFrame,
    roi_harmonic_summary: pd.DataFrame,
    base_rate_summary: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "z_source",
        "condition",
        "roi",
        "frequency_hz",
        "harmonic_index",
        "z_score",
        "p_one_tailed",
        "selected",
        "threshold_notes",
    ]
    rows: list[dict[str, object]] = []
    if not harmonic_selection.empty:
        for _index, row in harmonic_selection.iterrows():
            z_score = _coerce_float(_row_value(row, "z_score"))
            rows.append(
                {
                    "z_source": "Stats group harmonic selection",
                    "condition": "all selected conditions",
                    "roi": "all scalp electrodes",
                    "frequency_hz": _row_value(row, "target_frequency_hz"),
                    "harmonic_index": _row_value(row, "harmonic_index"),
                    "z_score": z_score,
                    "p_one_tailed": _z_p_value(z_score),
                    "selected": _bool_flag(_row_value(row, "selected")),
                    "threshold_notes": _row_value(row, "exclusion_reason"),
                }
            )
    if not roi_harmonic_summary.empty:
        z_rows = roi_harmonic_summary.loc[roi_harmonic_summary["metric"] == "Z"]
        for _index, row in z_rows.iterrows():
            z_score = _coerce_float(_row_value(row, "mean"))
            threshold_cols = [
                column
                for column in z_rows.columns
                if str(column).startswith("z_gt_") and _bool_flag(_row_value(row, column))
            ]
            rows.append(
                {
                    "z_source": "ROI harmonic mean Z",
                    "condition": _row_value(row, "condition"),
                    "roi": _row_value(row, "roi"),
                    "frequency_hz": _row_value(row, "harmonic_hz"),
                    "harmonic_index": np.nan,
                    "z_score": z_score,
                    "p_one_tailed": _row_value(row, "z_one_tailed_p"),
                    "selected": True,
                    "threshold_notes": "; ".join(threshold_cols),
                }
            )
    if not base_rate_summary.empty:
        z_rows = base_rate_summary.loc[base_rate_summary["metric"] == "Z"]
        for _index, row in z_rows.iterrows():
            z_score = _coerce_float(_row_value(row, "mean"))
            significant = _bool_flag(_row_value(row, "significant_z_gt_1_64"))
            rows.append(
                {
                    "z_source": "Base-rate ROI mean Z",
                    "condition": _row_value(row, "condition"),
                    "roi": _row_value(row, "roi"),
                    "frequency_hz": _row_value(row, "base_harmonic_hz"),
                    "harmonic_index": np.nan,
                    "z_score": z_score,
                    "p_one_tailed": _row_value(row, "z_one_tailed_p"),
                    "selected": significant,
                    "threshold_notes": "z_gt_1.64" if significant else "",
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _read_sheet(path: Path, sheet_name: str, warnings: list[str]) -> pd.DataFrame | None:
    try:
        frame = pd.read_excel(path, sheet_name=sheet_name)
    except Exception as exc:
        warnings.append(f"Could not read {sheet_name} from {path.name}: {exc}")
        return None
    if ELECTRODE_COLUMN not in frame.columns:
        warnings.append(f"Missing {ELECTRODE_COLUMN} column in {sheet_name} for {path.name}.")
        return None
    return frame


def _read_first_available_sheet(
    path: Path,
    sheet_names: tuple[str, ...],
    warnings: list[str],
) -> tuple[pd.DataFrame | None, str]:
    for sheet_name in sheet_names:
        try:
            frame = pd.read_excel(path, sheet_name=sheet_name)
        except Exception:
            continue
        if ELECTRODE_COLUMN in frame.columns:
            return frame, sheet_name
    warnings.append(
        f"Could not read any of {', '.join(sheet_names)} with an {ELECTRODE_COLUMN} "
        f"column from {path.name}."
    )
    return None, ""


def _roi_mean(frame: pd.DataFrame, roi: ReportRoi, column_name: str) -> tuple[float, int, tuple[str, ...]]:
    electrodes = {normalize_electrode_name(electrode) for electrode in roi.electrodes}
    source = frame.copy()
    source["_normalized_electrode"] = source[ELECTRODE_COLUMN].map(normalize_electrode_name)
    subset = source.loc[source["_normalized_electrode"].isin(electrodes)]
    present = set(subset["_normalized_electrode"].astype(str))
    missing = tuple(sorted(electrode for electrode in electrodes if electrode not in present))
    values = pd.to_numeric(subset[column_name], errors="coerce")
    numeric = _finite_array(values)
    return (
        float(np.mean(numeric)) if len(numeric) else np.nan,
        int(len(numeric)),
        missing,
    )


def _combined_z_by_electrode(
    frame: pd.DataFrame,
    selected_harmonics: tuple[float, ...],
    warnings: list[str],
    path: Path,
) -> pd.DataFrame:
    columns = []
    for harmonic in selected_harmonics:
        column = find_frequency_column(frame.columns, harmonic)
        if column is None:
            warnings.append(f"Missing Z Score column for {harmonic:g} Hz in {path.name}.")
            continue
        columns.append(column.column_name)
    if not columns:
        return pd.DataFrame(columns=["electrode", "combined_z"])
    z_values = frame[columns].apply(pd.to_numeric, errors="coerce")
    combined = z_values.sum(axis=1, min_count=1) / sqrt(len(columns))
    return pd.DataFrame(
        {
            "electrode": frame[ELECTRODE_COLUMN].map(normalize_electrode_name),
            "combined_z": combined,
        }
    ).dropna(subset=["combined_z"])


def _combined_subset(combined: pd.DataFrame, roi: ReportRoi) -> pd.DataFrame:
    if roi.name == WHOLE_SCALP_ROI:
        return combined
    electrodes = {normalize_electrode_name(electrode) for electrode in roi.electrodes}
    return combined.loc[combined["electrode"].isin(electrodes)]


def _base_rate_harmonics(base_hz: float, upper_hz: float) -> tuple[float, ...]:
    base = float(base_hz)
    upper = float(upper_hz)
    if base <= 0 or upper < base:
        return ()
    count = int(np.floor(upper / base))
    return tuple(round(base * index, 4) for index in range(1, count + 1))


def _bh_fdr(p_values: np.ndarray) -> np.ndarray:
    p = np.asarray(p_values, dtype=float)
    q = np.full_like(p, np.nan, dtype=float)
    finite_mask = np.isfinite(p)
    finite = p[finite_mask]
    if len(finite) == 0:
        return q
    order = np.argsort(finite)
    ranked = finite[order]
    n = len(ranked)
    adjusted = ranked * n / np.arange(1, n + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    adjusted = np.clip(adjusted, 0.0, 1.0)
    restored = np.empty_like(adjusted)
    restored[order] = adjusted
    q[finite_mask] = restored
    return q


def _finite_array(values: pd.Series | np.ndarray) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="coerce")
    array = np.asarray(numeric, dtype=float)
    return array[np.isfinite(array)]


def _sd(values: np.ndarray) -> float:
    return float(np.std(values, ddof=1)) if len(values) >= 2 else np.nan


def _sem(values: np.ndarray) -> float:
    return float(stats.sem(values, nan_policy="omit")) if len(values) >= 2 else np.nan


def _one_sample_t(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 2:
        return np.nan, np.nan
    result = stats.ttest_1samp(values, popmean=0.0, nan_policy="omit")
    return float(result.statistic), float(result.pvalue)


def _cohens_dz(values: np.ndarray) -> float:
    if len(values) < 2:
        return np.nan
    sd = np.std(values, ddof=1)
    if not np.isfinite(sd) or sd == 0:
        return np.nan
    return float(np.mean(values) / sd)


def _z_p_value(z_value: float) -> float:
    if not np.isfinite(z_value):
        return np.nan
    return float(stats.norm.sf(z_value))


def _direction(diff: float) -> str:
    if not np.isfinite(diff) or diff == 0:
        return "no_direction"
    return "condition_a_greater" if diff > 0 else "condition_b_greater"


def _series_mean(values: pd.Series) -> float:
    numeric = _finite_array(values)
    return float(np.mean(numeric)) if len(numeric) else np.nan


def _stats_subject_data(workbooks: list[WorkbookEntry]) -> dict[str, dict[str, str]]:
    subject_data: dict[str, dict[str, str]] = {}
    for workbook in workbooks:
        subject_data.setdefault(workbook.subject_id, {})[workbook.condition] = str(workbook.path)
    return subject_data


def _stats_rois(request: PublicationReportRequest) -> dict[str, list[str]]:
    return {
        roi.name: [normalize_electrode_name(electrode) for electrode in roi.electrodes]
        for roi in request.rois
        if roi.selected
    }


def _copy_attrs(source: pd.DataFrame, target: pd.DataFrame) -> None:
    try:
        target.attrs.update(dict(source.attrs))
    except Exception:
        return


def _append_run_report_summary(
    rows: list[dict[str, object]],
    step: str,
    run_report: object,
) -> None:
    if run_report is None:
        return
    rows.append(
        {
            "step": f"{step}_participant_set",
            "status": "info",
            "note": (
                f"final_modeled={len(getattr(run_report, 'final_modeled_pids', []) or [])}; "
                f"manual_excluded={len(getattr(run_report, 'manual_excluded_pids', []) or [])}; "
                f"required_exclusions={len(getattr(run_report, 'required_exclusions', []) or [])}"
            ),
        }
    )


def _attrs_note(frame: pd.DataFrame) -> str:
    if frame.empty:
        return ""
    attrs = frame.attrs
    backend = attrs.get("rm_anova_backend", "")
    correction = attrs.get("rm_anova_correction_outputs_available", "")
    return f"backend={backend}; correction_outputs_available={correction}"


def _row_value(row: object, name: str) -> object:
    if isinstance(row, pd.Series):
        return row.get(name, np.nan)
    normalized = name.replace(" ", "_").replace(">", "_").replace("(", "_").replace(")", "_")
    normalized = normalized.replace("/", "_").replace("-", "_")
    if hasattr(row, normalized):
        return getattr(row, normalized)
    if hasattr(row, name):
        return getattr(row, name)
    try:
        fields = getattr(row, "_fields", ())
        values = tuple(row)
        mapping = dict(zip(fields, values))
        return mapping.get(normalized, mapping.get(name, np.nan))
    except Exception:
        return np.nan


def _coerce_float(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return np.nan
    return numeric if np.isfinite(numeric) else np.nan


def _p_is_sig(value: object, *, alpha: float = P_ALPHA) -> bool:
    numeric = _coerce_float(value)
    return bool(np.isfinite(numeric) and numeric < alpha)


def _same_direction(first: float, second: float) -> bool:
    if not np.isfinite(first) or not np.isfinite(second):
        return False
    if first == 0 or second == 0:
        return first == second
    return bool(np.sign(first) == np.sign(second))


def _bool_flag(value: object) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "significant"}
    return bool(value)

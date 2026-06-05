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
from Tools.Individual_Detectability.core import (
    SHEET_FULLFFT,
    build_fullfft_harmonic_plan,
    electrode_summed_z_from_fullfft_frame,
    roi_summed_z_from_fullfft_frame,
)
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
    INDIVIDUAL_ELECTRODE_FDR_SHEET,
    INDIVIDUAL_ELECTRODE_SUMMED_Z_SHEET,
    INDIVIDUAL_ROI_SUMMED_Z_SHEET,
    NORMALITY_CHECKS_SHEET,
    OLD_VS_NEW_DETECTABILITY_COMPARISON_SHEET,
    PARAMETRIC_VS_NONPARAMETRIC_TESTS_SHEET,
    PLANNED_LATERALIZATION_SHEET,
    PLANNED_ROI_COMPARISONS_HOLM_SHEET,
    ROI_HARMONIC_SUMMARY_SHEET,
    ROI_HARMONIC_VALUES_SHEET,
    ROI_RESPONSE_SUMMARY_SHEET,
    SEMANTIC_COLOR_RATIO_SUMMARY_SHEET,
    SEMANTIC_COLOR_RATIO_VALUES_SHEET,
    STATISTICAL_TEST_DECISIONS_SHEET,
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
from Tools.Publication_Report.statistical_tests import (
    bonferroni_adjust,
    holm_adjust,
    one_sample_against_zero,
    paired_difference_test,
)

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
    semantic_color_ratio_values, semantic_color_ratio_summary = _semantic_color_ratio_frames(response_values)
    stats_rm_anova, stats_posthoc, stats_workflow_summary = _stats_rm_anova_workflow(
        request=request,
        workbooks=included_workbooks,
        included_subjects=included_subjects,
        selected_conditions=selected_conditions,
        warnings=warnings,
    )
    condition_comparisons = _condition_comparisons_from_stats(stats_rm_anova)
    condition_pairs = _condition_pairs_by_roi(response_values)
    roi_response_summary = _apply_holm_to_frame(
        roi_response_summary,
        family="planned_condition_roi_response_vs_zero",
    )
    condition_pairs = _apply_holm_to_frame(
        condition_pairs,
        family="planned_condition_pairs_by_roi",
    )
    agreement = _comparison_agreement(stats_posthoc, condition_pairs)
    planned_lateralization = _planned_lateralization_contrasts(response_values)
    normality_checks, parametric_vs_nonparametric, planned_roi_holm, test_decisions = _statistical_test_exports(
        roi_response_summary=roi_response_summary,
        condition_pairs=condition_pairs,
        planned_lateralization=planned_lateralization,
    )
    (
        individual_roi_summed_z,
        individual_electrode_summed_z,
        individual_electrode_fdr,
        legacy_comparison,
    ) = _individual_detectability_frames(
        request=request,
        workbooks=included_workbooks,
        selected_harmonics=selected_harmonics,
        warnings=warnings,
    )
    individual_detectability_counts = _individual_detectability_counts(
        individual_roi_summed_z,
        individual_electrode_fdr,
    )
    group_electrode_significance = _group_electrode_significance(
        individual_electrode_fdr,
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
        SEMANTIC_COLOR_RATIO_VALUES_SHEET: semantic_color_ratio_values,
        SEMANTIC_COLOR_RATIO_SUMMARY_SHEET: semantic_color_ratio_summary,
        CONDITION_COMPARISONS_SHEET: condition_comparisons,
        STATS_RM_ANOVA_SHEET: stats_rm_anova,
        STATS_POSTHOC_SHEET: stats_posthoc,
        STATS_WORKFLOW_SUMMARY_SHEET: stats_workflow_summary,
        CONDITION_PAIRS_BY_ROI_SHEET: condition_pairs,
        COMPARISON_AGREEMENT_SHEET: agreement,
        PLANNED_LATERALIZATION_SHEET: planned_lateralization,
        NORMALITY_CHECKS_SHEET: normality_checks,
        PARAMETRIC_VS_NONPARAMETRIC_TESTS_SHEET: parametric_vs_nonparametric,
        PLANNED_ROI_COMPARISONS_HOLM_SHEET: planned_roi_holm,
        STATISTICAL_TEST_DECISIONS_SHEET: test_decisions,
        INDIVIDUAL_ROI_SUMMED_Z_SHEET: individual_roi_summed_z,
        INDIVIDUAL_ELECTRODE_SUMMED_Z_SHEET: individual_electrode_summed_z,
        INDIVIDUAL_ELECTRODE_FDR_SHEET: individual_electrode_fdr,
        OLD_VS_NEW_DETECTABILITY_COMPARISON_SHEET: legacy_comparison,
        ELECTRODE_Z_SCORES_SHEET: individual_electrode_fdr,
        GROUP_ELECTRODE_SIGNIFICANCE_SHEET: group_electrode_significance,
        INDIVIDUAL_DETECTABILITY_SHEET: individual_roi_summed_z,
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
        "normality_statistic",
        "normality_p",
        "normality_met",
        "parametric_test",
        "parametric_statistic",
        "parametric_p",
        "nonparametric_test",
        "nonparametric_statistic",
        "nonparametric_p",
        "selected_test",
        "selected_p",
        "decision_reason",
        "planned_family",
        "p_bonferroni_planned_family",
        "p_holm_planned_family",
        "significant_holm",
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
        diagnostics = one_sample_against_zero(numeric)
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
                "t_statistic": diagnostics.parametric_statistic,
                "df": diagnostics.df,
                "p_value_two_tailed": diagnostics.parametric_p,
                **diagnostics.as_columns(),
                "planned_family": "planned_condition_roi_response_vs_zero",
                "p_bonferroni_planned_family": np.nan,
                "p_holm_planned_family": np.nan,
                "significant_holm": False,
                "cohens_dz": _cohens_dz(numeric),
            }
        )
    return pd.DataFrame(rows, columns=summary_columns), response


def _semantic_color_ratio_frames(response_values: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    value_columns = [
        "subject_id",
        "roi",
        "roi_role",
        "selected_harmonics_hz",
        "semantic_condition",
        "color_condition",
        "semantic_summed_bca_uv",
        "color_summed_bca_uv",
        "semantic_color_ratio",
        "ratio_valid",
        "invalid_reason",
        "roi_median_ratio",
        "deviation_from_roi_median",
        "absolute_deviation_from_roi_median",
        "percent_deviation_from_roi_median",
        "stability_band",
    ]
    summary_columns = [
        "roi",
        "roi_role",
        "selected_harmonics_hz",
        "semantic_condition",
        "color_condition",
        "n_participants",
        "n_valid_ratios",
        "n_invalid_denominator",
        "min_ratio",
        "max_ratio",
        "mean_ratio",
        "median_ratio",
        "sd_ratio",
        "trimmed_n",
        "trimmed_min_ratio",
        "trimmed_max_ratio",
        "trimmed_mean_ratio",
        "trimmed_median_ratio",
        "trimmed_sd_ratio",
        "iqr_ratio",
        "mad_from_median",
        "coefficient_of_variation",
        "trimmed_mean_shift_abs",
        "trimmed_mean_shift_percent",
        "percent_within_10pct_of_median",
        "percent_within_20pct_of_median",
        "stability_note",
        "min_max_exclusion_rule",
    ]
    if response_values.empty:
        return pd.DataFrame(columns=value_columns), pd.DataFrame(columns=summary_columns)

    semantic_condition = _find_named_level(response_values["condition"], _semantic_condition_match)
    color_condition = _find_color_condition(response_values["condition"])
    if not semantic_condition or not color_condition:
        return pd.DataFrame(columns=value_columns), pd.DataFrame(columns=summary_columns)

    rows: list[dict[str, object]] = []
    for roi, group in response_values.groupby("roi", dropna=False):
        wide = group.pivot_table(
            index="subject_id",
            columns="condition",
            values="summed_bca_uv",
            aggfunc="mean",
        )
        if semantic_condition not in wide.columns or color_condition not in wide.columns:
            continue
        meta = (
            group.drop_duplicates(subset=["subject_id"])
            .set_index("subject_id")[["roi_role", "selected_harmonics_hz"]]
        )
        for subject_id, pair in wide[[semantic_condition, color_condition]].iterrows():
            semantic_value = _coerce_float(pair[semantic_condition])
            color_value = _coerce_float(pair[color_condition])
            ratio, ratio_valid, invalid_reason = _safe_semantic_color_ratio(
                semantic_value,
                color_value,
            )
            rows.append(
                {
                    "subject_id": str(subject_id),
                    "roi": roi,
                    "roi_role": _row_value(meta.loc[subject_id], "roi_role", "") if subject_id in meta.index else "",
                    "selected_harmonics_hz": (
                        _row_value(meta.loc[subject_id], "selected_harmonics_hz", "")
                        if subject_id in meta.index
                        else ""
                    ),
                    "semantic_condition": semantic_condition,
                    "color_condition": color_condition,
                    "semantic_summed_bca_uv": semantic_value,
                    "color_summed_bca_uv": color_value,
                    "semantic_color_ratio": ratio,
                    "ratio_valid": ratio_valid,
                    "invalid_reason": invalid_reason,
                    "roi_median_ratio": np.nan,
                    "deviation_from_roi_median": np.nan,
                    "absolute_deviation_from_roi_median": np.nan,
                    "percent_deviation_from_roi_median": np.nan,
                    "stability_band": "not_evaluable",
                }
            )

    values = pd.DataFrame(rows, columns=value_columns)
    if values.empty:
        return values, pd.DataFrame(columns=summary_columns)

    summary_rows: list[dict[str, object]] = []
    for roi, group in values.groupby("roi", dropna=False):
        ratio_values = _finite_array(group.loc[group["ratio_valid"].fillna(False).astype(bool), "semantic_color_ratio"])
        summary = _ratio_distribution_summary(ratio_values)
        median_ratio = summary["median_ratio"]
        valid_mask = (
            values["roi"].astype(str).eq(str(roi))
            & values["ratio_valid"].fillna(False).astype(bool)
            & np.isfinite(pd.to_numeric(values["semantic_color_ratio"], errors="coerce"))
        )
        values.loc[valid_mask, "roi_median_ratio"] = median_ratio
        values.loc[valid_mask, "deviation_from_roi_median"] = (
            pd.to_numeric(values.loc[valid_mask, "semantic_color_ratio"], errors="coerce") - median_ratio
        )
        values.loc[valid_mask, "absolute_deviation_from_roi_median"] = values.loc[
            valid_mask,
            "deviation_from_roi_median",
        ].abs()
        if np.isfinite(median_ratio) and median_ratio != 0:
            values.loc[valid_mask, "percent_deviation_from_roi_median"] = (
                values.loc[valid_mask, "absolute_deviation_from_roi_median"] / abs(median_ratio)
            )
        values.loc[valid_mask, "stability_band"] = values.loc[
            valid_mask,
            "percent_deviation_from_roi_median",
        ].map(_ratio_stability_band)

        first = group.iloc[0]
        summary_rows.append(
            {
                "roi": roi,
                "roi_role": first.get("roi_role", ""),
                "selected_harmonics_hz": first.get("selected_harmonics_hz", ""),
                "semantic_condition": semantic_condition,
                "color_condition": color_condition,
                "n_participants": int(len(group)),
                "n_valid_ratios": int(len(ratio_values)),
                "n_invalid_denominator": int((~group["ratio_valid"].fillna(False).astype(bool)).sum()),
                **summary,
                "stability_note": _ratio_stability_note(summary),
                "min_max_exclusion_rule": "Drop the single minimum and single maximum valid ratio per ROI.",
            }
        )
    return values[value_columns], pd.DataFrame(summary_rows, columns=summary_columns)


def _safe_semantic_color_ratio(
    semantic_value: float,
    color_value: float,
) -> tuple[float, bool, str]:
    if not np.isfinite(semantic_value):
        return np.nan, False, "missing_or_nonfinite_semantic_value"
    if not np.isfinite(color_value):
        return np.nan, False, "missing_or_nonfinite_color_value"
    if np.isclose(color_value, 0.0):
        return np.nan, False, "zero_color_denominator"
    return float(semantic_value / color_value), True, ""


def _ratio_distribution_summary(values: np.ndarray) -> dict[str, object]:
    trimmed = _drop_single_min_max(values)
    mean_ratio = float(np.mean(values)) if len(values) else np.nan
    trimmed_mean = float(np.mean(trimmed)) if len(trimmed) else np.nan
    if np.isfinite(mean_ratio) and mean_ratio != 0 and np.isfinite(trimmed_mean):
        trimmed_shift_percent = float(abs(trimmed_mean - mean_ratio) / abs(mean_ratio))
    else:
        trimmed_shift_percent = np.nan
    return {
        "min_ratio": float(np.min(values)) if len(values) else np.nan,
        "max_ratio": float(np.max(values)) if len(values) else np.nan,
        "mean_ratio": mean_ratio,
        "median_ratio": float(np.median(values)) if len(values) else np.nan,
        "sd_ratio": _sd(values),
        "trimmed_n": int(len(trimmed)),
        "trimmed_min_ratio": float(np.min(trimmed)) if len(trimmed) else np.nan,
        "trimmed_max_ratio": float(np.max(trimmed)) if len(trimmed) else np.nan,
        "trimmed_mean_ratio": trimmed_mean,
        "trimmed_median_ratio": float(np.median(trimmed)) if len(trimmed) else np.nan,
        "trimmed_sd_ratio": _sd(trimmed),
        "iqr_ratio": _iqr(values),
        "mad_from_median": _mad_from_median(values),
        "coefficient_of_variation": _coefficient_of_variation(values),
        "trimmed_mean_shift_abs": (
            float(abs(trimmed_mean - mean_ratio))
            if np.isfinite(trimmed_mean) and np.isfinite(mean_ratio)
            else np.nan
        ),
        "trimmed_mean_shift_percent": trimmed_shift_percent,
        "percent_within_10pct_of_median": _percent_within_median(values, proportion=0.10),
        "percent_within_20pct_of_median": _percent_within_median(values, proportion=0.20),
    }


def _drop_single_min_max(values: np.ndarray) -> np.ndarray:
    numeric = _finite_array(values)
    if len(numeric) <= 2:
        return np.array([], dtype=float)
    ordered = np.sort(numeric)
    return ordered[1:-1]


def _iqr(values: np.ndarray) -> float:
    numeric = _finite_array(values)
    if len(numeric) < 2:
        return np.nan
    return float(np.percentile(numeric, 75) - np.percentile(numeric, 25))


def _mad_from_median(values: np.ndarray) -> float:
    numeric = _finite_array(values)
    if len(numeric) == 0:
        return np.nan
    median = float(np.median(numeric))
    return float(np.median(np.abs(numeric - median)))


def _coefficient_of_variation(values: np.ndarray) -> float:
    numeric = _finite_array(values)
    if len(numeric) < 2:
        return np.nan
    mean_value = float(np.mean(numeric))
    if mean_value == 0 or not np.isfinite(mean_value):
        return np.nan
    return float(np.std(numeric, ddof=1) / abs(mean_value))


def _percent_within_median(values: np.ndarray, *, proportion: float) -> float:
    numeric = _finite_array(values)
    if len(numeric) == 0:
        return np.nan
    median = float(np.median(numeric))
    if median == 0 or not np.isfinite(median):
        return np.nan
    return float(np.mean(np.abs(numeric - median) <= abs(median) * proportion))


def _ratio_stability_band(value: object) -> str:
    numeric = _coerce_float(value)
    if not np.isfinite(numeric):
        return "not_evaluable"
    if numeric <= 0.10:
        return "within_10pct_of_roi_median"
    if numeric <= 0.20:
        return "within_20pct_of_roi_median"
    return "outside_20pct_of_roi_median"


def _ratio_stability_note(summary: dict[str, object]) -> str:
    n = int(summary.get("trimmed_n", 0) or 0)
    pct20 = _coerce_float(summary.get("percent_within_20pct_of_median"))
    cv = _coerce_float(summary.get("coefficient_of_variation"))
    trimmed_shift = _coerce_float(summary.get("trimmed_mean_shift_percent"))
    if n < 3:
        return "insufficient_valid_ratios_for_stability"
    if np.isfinite(pct20) and pct20 >= 0.80 and np.isfinite(cv) and cv <= 0.25:
        return "high_stability_across_participants"
    if (
        np.isfinite(pct20)
        and pct20 >= 0.60
        and np.isfinite(trimmed_shift)
        and trimmed_shift <= 0.20
    ):
        return "moderate_stability_across_participants"
    return "variable_ratio_across_participants"


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
                "note": (
                    "Exploratory posthoc rows from Tools.Stats.analysis.posthoc_tests; "
                    "planned manuscript ROI comparisons are corrected with Holm."
                ),
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
        "normality_statistic",
        "normality_p",
        "normality_met",
        "parametric_test",
        "parametric_statistic",
        "parametric_p",
        "nonparametric_test",
        "nonparametric_statistic",
        "nonparametric_p",
        "selected_test",
        "selected_p",
        "decision_reason",
        "planned_family",
        "p_bonferroni_planned_family",
        "p_holm_planned_family",
        "significant_holm",
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
            a, b, diff, diagnostics = paired_difference_test(
                paired[condition_a],
                paired[condition_b],
            )
            if len(diff) < 2:
                dz = np.nan
                direction = "insufficient_complete_pairs"
            else:
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
                    "t_statistic": diagnostics.parametric_statistic,
                    "df": diagnostics.df,
                    "p_value_two_tailed": diagnostics.parametric_p,
                    **diagnostics.as_columns(),
                    "planned_family": "planned_condition_pairs_by_roi",
                    "p_bonferroni_planned_family": np.nan,
                    "p_holm_planned_family": np.nan,
                    "significant_holm": False,
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
        "normality_statistic",
        "normality_p",
        "normality_met",
        "parametric_test",
        "parametric_statistic",
        "parametric_p",
        "nonparametric_test",
        "nonparametric_statistic",
        "nonparametric_p",
        "selected_test",
        "selected_p",
        "decision_reason",
        "p_bonferroni_planned_family",
        "p_holm_planned_family",
        "significant_holm",
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
    rows: list[dict[str, object]] = [
        _single_condition_lateralization_row(
            frame,
            planned_family=family,
            condition=semantic_condition,
            left_roi=left_roi,
            right_roi=right_roi,
            note=(
                "Planned semantic LOT-ROT lateralization contrast; not included "
                "in the exploratory Stats posthoc source table."
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
        _lateralization_difference_row(
            frame,
            planned_family=family,
            condition_a=semantic_condition,
            condition_b=color_condition,
            left_roi=left_roi,
            right_roi=right_roi,
        ),
    ]
    selected_p = [row["selected_p"] for row in rows]
    bonferroni = bonferroni_adjust(selected_p)
    holm = holm_adjust(selected_p)
    for index, row in enumerate(rows):
        row["p_bonferroni_planned_family"] = bonferroni[index]
        row["p_holm_planned_family"] = holm[index]
        row["significant_holm"] = _p_is_sig(holm[index])
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
    paired = (
        wide[[left_roi, right_roi]].dropna(axis=0, how="any")
        if {left_roi, right_roi} <= set(wide.columns)
        else pd.DataFrame()
    )
    right, left, diff, diagnostics = paired_difference_test(
        paired[right_roi] if right_roi in paired else pd.Series(dtype=float),
        paired[left_roi] if left_roi in paired else pd.Series(dtype=float),
    )
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
        "t_statistic": diagnostics.parametric_statistic,
        "df": diagnostics.df,
        "p_value_two_tailed": diagnostics.parametric_p,
        **diagnostics.as_columns(),
        "p_bonferroni_planned_family": np.nan,
        "p_holm_planned_family": np.nan,
        "significant_holm": False,
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
    diagnostics = one_sample_against_zero(contrast)
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
        "t_statistic": diagnostics.parametric_statistic,
        "df": diagnostics.df,
        "p_value_two_tailed": diagnostics.parametric_p,
        **diagnostics.as_columns(),
        "p_bonferroni_planned_family": np.nan,
        "p_holm_planned_family": np.nan,
        "significant_holm": False,
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


def _apply_holm_to_frame(
    frame: pd.DataFrame,
    *,
    family: str,
) -> pd.DataFrame:
    if frame.empty:
        return frame
    target = frame.copy()
    if "planned_family" not in target.columns:
        target["planned_family"] = family
    else:
        target["planned_family"] = target["planned_family"].fillna(family).replace("", family)
    p_source = "selected_p" if "selected_p" in target.columns else "p_value_two_tailed"
    p_values = target[p_source].tolist() if p_source in target.columns else []
    target["p_bonferroni_planned_family"] = bonferroni_adjust(p_values)
    target["p_holm_planned_family"] = holm_adjust(p_values)
    target["significant_holm"] = target["p_holm_planned_family"].map(_p_is_sig)
    return target


def _statistical_test_exports(
    *,
    roi_response_summary: pd.DataFrame,
    condition_pairs: pd.DataFrame,
    planned_lateralization: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    entries: list[dict[str, object]] = []
    entries.extend(_roi_response_test_entries(roi_response_summary))
    entries.extend(_condition_pair_test_entries(condition_pairs))
    entries.extend(_planned_lateralization_test_entries(planned_lateralization))
    normality = pd.DataFrame(entries, columns=_normality_columns())
    parametric_vs_nonparametric = pd.DataFrame(entries, columns=_parametric_vs_nonparametric_columns())
    planned_holm = pd.DataFrame(entries, columns=_planned_holm_columns())
    decisions = pd.DataFrame(entries, columns=_decision_columns())
    return normality, parametric_vs_nonparametric, planned_holm, decisions


def _roi_response_test_entries(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    for _index, row in frame.iterrows():
        condition = str(_row_value(row, "condition"))
        roi = str(_row_value(row, "roi"))
        rows.append(
            _test_export_entry(
                row,
                comparison_id=f"{condition} / {roi} summed BCA vs zero",
                comparison_type="one_sample_vs_zero",
                condition=condition,
                roi=roi,
                mean_effect_uv=_row_value(row, "mean_summed_bca_uv"),
                planned_family="planned_condition_roi_response_vs_zero",
            )
        )
    return rows


def _condition_pair_test_entries(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    for _index, row in frame.iterrows():
        roi = str(_row_value(row, "roi"))
        condition_a = str(_row_value(row, "condition_a"))
        condition_b = str(_row_value(row, "condition_b"))
        rows.append(
            _test_export_entry(
                row,
                comparison_id=f"{roi}: {condition_a} minus {condition_b}",
                comparison_type="paired_condition_difference",
                condition="",
                condition_a=condition_a,
                condition_b=condition_b,
                roi=roi,
                mean_effect_uv=_row_value(row, "mean_difference_a_minus_b"),
                planned_family="planned_condition_pairs_by_roi",
            )
        )
    return rows


def _planned_lateralization_test_entries(frame: pd.DataFrame) -> list[dict[str, object]]:
    if frame.empty:
        return []
    rows: list[dict[str, object]] = []
    for _index, row in frame.iterrows():
        contrast_type = str(_row_value(row, "contrast_type"))
        left_roi = str(_row_value(row, "left_roi"))
        right_roi = str(_row_value(row, "right_roi"))
        roi = f"{right_roi} minus {left_roi}"
        if contrast_type == "lateralization_difference":
            condition_a = str(_row_value(row, "condition_a"))
            condition_b = str(_row_value(row, "condition_b"))
            comparison_id = f"({roi}) {condition_a} minus {condition_b}"
            mean_effect_uv = _row_value(row, "mean_difference_of_lateralization_uv")
            condition = ""
        else:
            condition = str(_row_value(row, "condition"))
            condition_a = ""
            condition_b = ""
            comparison_id = f"{condition}: {roi}"
            mean_effect_uv = _row_value(row, "mean_right_minus_left_uv")
        rows.append(
            _test_export_entry(
                row,
                comparison_id=comparison_id,
                comparison_type=contrast_type,
                condition=condition,
                condition_a=condition_a,
                condition_b=condition_b,
                roi=roi,
                mean_effect_uv=mean_effect_uv,
                planned_family=str(_row_value(row, "planned_family")),
            )
        )
    return rows


def _test_export_entry(
    row: pd.Series,
    *,
    comparison_id: str,
    comparison_type: str,
    condition: str,
    roi: str,
    mean_effect_uv: object,
    planned_family: str,
    condition_a: str = "",
    condition_b: str = "",
) -> dict[str, object]:
    selected_p = _row_value(row, "selected_p")
    holm_p = _row_value(row, "p_holm_planned_family")
    return {
        "planned_family": planned_family,
        "comparison_id": comparison_id,
        "comparison_type": comparison_type,
        "condition": condition,
        "condition_a": condition_a,
        "condition_b": condition_b,
        "roi": roi,
        "n": _row_value(row, "n", _row_value(row, "n_complete")),
        "mean_effect_uv": mean_effect_uv,
        "normality_statistic": _row_value(row, "normality_statistic"),
        "normality_p": _row_value(row, "normality_p"),
        "normality_met": _row_value(row, "normality_met"),
        "normality_alpha": P_ALPHA,
        "parametric_test": _row_value(row, "parametric_test"),
        "parametric_statistic": _row_value(row, "parametric_statistic"),
        "parametric_df": _row_value(row, "df"),
        "parametric_p": _row_value(row, "parametric_p"),
        "nonparametric_test": _row_value(row, "nonparametric_test"),
        "nonparametric_statistic": _row_value(row, "nonparametric_statistic"),
        "nonparametric_p": _row_value(row, "nonparametric_p"),
        "selected_test": _row_value(row, "selected_test"),
        "selected_p": selected_p,
        "decision_reason": _row_value(row, "decision_reason"),
        "correction_method": "Holm",
        "p_bonferroni_planned_family": _row_value(row, "p_bonferroni_planned_family"),
        "p_holm_planned_family": holm_p,
        "significant_holm": _p_is_sig(holm_p),
        "significant_uncorrected_selected": _p_is_sig(selected_p),
    }


def _normality_columns() -> list[str]:
    return [
        "planned_family",
        "comparison_id",
        "comparison_type",
        "condition",
        "condition_a",
        "condition_b",
        "roi",
        "n",
        "normality_statistic",
        "normality_p",
        "normality_met",
        "normality_alpha",
        "decision_reason",
    ]


def _parametric_vs_nonparametric_columns() -> list[str]:
    return [
        "planned_family",
        "comparison_id",
        "comparison_type",
        "condition",
        "condition_a",
        "condition_b",
        "roi",
        "n",
        "mean_effect_uv",
        "parametric_test",
        "parametric_statistic",
        "parametric_df",
        "parametric_p",
        "nonparametric_test",
        "nonparametric_statistic",
        "nonparametric_p",
        "selected_test",
        "selected_p",
        "decision_reason",
    ]


def _planned_holm_columns() -> list[str]:
    return [
        "planned_family",
        "comparison_id",
        "comparison_type",
        "condition",
        "condition_a",
        "condition_b",
        "roi",
        "n",
        "mean_effect_uv",
        "selected_test",
        "selected_p",
        "correction_method",
        "p_bonferroni_planned_family",
        "p_holm_planned_family",
        "significant_holm",
        "parametric_p",
        "nonparametric_p",
        "decision_reason",
    ]


def _decision_columns() -> list[str]:
    return [
        "planned_family",
        "comparison_id",
        "comparison_type",
        "selected_test",
        "selected_p",
        "p_holm_planned_family",
        "significant_holm",
        "normality_p",
        "normality_met",
        "decision_reason",
    ]


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


def _individual_detectability_frames(
    *,
    request: PublicationReportRequest,
    workbooks: list[WorkbookEntry],
    selected_harmonics: tuple[float, ...],
    warnings: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    roi_columns = [
        "participant_id",
        "condition",
        "roi",
        "harmonic_list",
        "n_harmonics",
        "z_sum",
        "p_one_tailed",
        "p_fdr_bh",
        "significant_z164",
        "significant_z232",
        "significant_z310",
        "significant_fdr_q05",
        "valid_electrode_count",
        "missing_electrodes",
        "signal_sum_uv",
        "noise_mean_uv",
        "noise_std_uv",
        "candidate_noise_count",
        "used_noise_count",
        "method",
        "workbook_path",
    ]
    electrode_columns = [
        "participant_id",
        "condition",
        "electrode",
        "roi",
        "harmonic_list",
        "n_harmonics",
        "z_sum",
        "p_one_tailed",
        "p_fdr_bh",
        "significant_z164",
        "significant_z232",
        "significant_z310",
        "significant_fdr_q05",
        "signal_sum_uv",
        "noise_mean_uv",
        "noise_std_uv",
        "candidate_noise_count",
        "used_noise_count",
        "method",
        "workbook_path",
    ]
    comparison_columns = [
        "participant_id",
        "condition",
        "electrode",
        "harmonic_list",
        "n_harmonics",
        "z_sum",
        "p_one_tailed",
        "Legacy_Stouffer_z",
        "Legacy_Stouffer_p_one_tailed",
        "Legacy_Stouffer_delta_z",
        "method",
        "workbook_path",
    ]
    if not selected_harmonics:
        return (
            pd.DataFrame(columns=roi_columns),
            pd.DataFrame(columns=electrode_columns),
            pd.DataFrame(columns=electrode_columns),
            pd.DataFrame(columns=comparison_columns),
        )

    harmonic_list = ", ".join(f"{freq:g}" for freq in selected_harmonics)
    report_rois = tuple(roi for roi in request.rois if roi.selected)
    roi_rows: list[dict[str, object]] = []
    electrode_rows: list[dict[str, object]] = []
    comparison_rows: list[dict[str, object]] = []

    for workbook in workbooks:
        fullfft = _read_sheet(workbook.path, SHEET_FULLFFT, warnings)
        if fullfft is None:
            continue
        try:
            plan = build_fullfft_harmonic_plan(fullfft.columns, selected_harmonics)
        except ValueError as exc:
            warnings.append(f"{workbook.path.name}: {exc}")
            continue

        electrode_summed = electrode_summed_z_from_fullfft_frame(fullfft, plan)
        if electrode_summed.empty:
            continue
        electrode_summed["electrode"] = electrode_summed["electrode"].map(normalize_electrode_name)
        electrode_summed["p_fdr_bh"] = _bh_fdr(electrode_summed["p_one_tailed"].to_numpy(dtype=float))
        electrode_summed["significant_fdr_q05"] = electrode_summed["p_fdr_bh"] <= P_ALPHA
        for threshold, suffix in ((1.64, "164"), (2.32, "232"), (3.10, "310")):
            electrode_summed[f"significant_z{suffix}"] = electrode_summed["z_sum"] > threshold

        roi_names_by_electrode = _roi_names_by_electrode(report_rois)
        for row in electrode_summed.itertuples(index=False):
            electrode = getattr(row, "electrode")
            electrode_rows.append(
                {
                    "participant_id": workbook.subject_id,
                    "condition": workbook.condition,
                    "electrode": electrode,
                    "roi": ", ".join(roi_names_by_electrode.get(electrode, ())),
                    "harmonic_list": harmonic_list,
                    "n_harmonics": len(plan.harmonic_list),
                    "z_sum": getattr(row, "z_sum"),
                    "p_one_tailed": getattr(row, "p_one_tailed"),
                    "p_fdr_bh": getattr(row, "p_fdr_bh"),
                    "significant_z164": getattr(row, "significant_z164"),
                    "significant_z232": getattr(row, "significant_z232"),
                    "significant_z310": getattr(row, "significant_z310"),
                    "significant_fdr_q05": getattr(row, "significant_fdr_q05"),
                    "signal_sum_uv": getattr(row, "signal_sum_uv"),
                    "noise_mean_uv": getattr(row, "noise_mean_uv"),
                    "noise_std_uv": getattr(row, "noise_std_uv"),
                    "candidate_noise_count": getattr(row, "candidate_noise_count"),
                    "used_noise_count": getattr(row, "used_noise_count"),
                    "method": "Summed-harmonic Z from participant FullFFT amplitude",
                    "workbook_path": str(workbook.path),
                }
            )

        for roi in report_rois:
            result = roi_summed_z_from_fullfft_frame(fullfft, plan, roi.electrodes)
            z_sum = _coerce_float(result.get("z_sum"))
            roi_rows.append(
                {
                    "participant_id": workbook.subject_id,
                    "condition": workbook.condition,
                    "roi": roi.name,
                    "harmonic_list": harmonic_list,
                    "n_harmonics": len(plan.harmonic_list),
                    "z_sum": z_sum,
                    "p_one_tailed": result.get("p_one_tailed"),
                    "p_fdr_bh": np.nan,
                    "significant_z164": bool(np.isfinite(z_sum) and z_sum > 1.64),
                    "significant_z232": bool(np.isfinite(z_sum) and z_sum > 2.32),
                    "significant_z310": bool(np.isfinite(z_sum) and z_sum > 3.10),
                    "significant_fdr_q05": np.nan,
                    "valid_electrode_count": result.get("valid_electrode_count"),
                    "missing_electrodes": result.get("missing_electrodes"),
                    "signal_sum_uv": result.get("signal_sum_uv"),
                    "noise_mean_uv": result.get("noise_mean_uv"),
                    "noise_std_uv": result.get("noise_std_uv"),
                    "candidate_noise_count": result.get("candidate_noise_count"),
                    "used_noise_count": result.get("used_noise_count"),
                    "method": "ROI-averaged FullFFT amplitude, then summed-harmonic Z",
                    "workbook_path": str(workbook.path),
                }
            )

        comparison_rows.extend(
            _legacy_stouffer_comparison(
                workbook=workbook,
                selected_harmonics=selected_harmonics,
                new_electrode_frame=electrode_summed,
                warnings=warnings,
            )
        )

    electrode_frame = pd.DataFrame(electrode_rows, columns=electrode_columns)
    return (
        pd.DataFrame(roi_rows, columns=roi_columns),
        electrode_frame,
        electrode_frame.copy(),
        pd.DataFrame(comparison_rows, columns=comparison_columns),
    )


def _roi_names_by_electrode(rois: tuple[ReportRoi, ...]) -> dict[str, tuple[str, ...]]:
    names: dict[str, list[str]] = {}
    for roi in rois:
        for electrode in roi.electrodes:
            names.setdefault(normalize_electrode_name(electrode), []).append(roi.name)
    return {electrode: tuple(values) for electrode, values in names.items()}


def _legacy_stouffer_comparison(
    *,
    workbook: WorkbookEntry,
    selected_harmonics: tuple[float, ...],
    new_electrode_frame: pd.DataFrame,
    warnings: list[str],
) -> list[dict[str, object]]:
    z_frame = _read_sheet(workbook.path, Z_SHEET, warnings)
    if z_frame is None:
        return []
    legacy = _combined_z_by_electrode(z_frame, selected_harmonics, warnings, workbook.path)
    if legacy.empty:
        return []
    legacy = legacy.rename(columns={"combined_z": "Legacy_Stouffer_z"})
    legacy["Legacy_Stouffer_p_one_tailed"] = legacy["Legacy_Stouffer_z"].map(_z_p_value)
    merged = new_electrode_frame.merge(legacy, on="electrode", how="inner")
    rows: list[dict[str, object]] = []
    harmonic_list = ", ".join(f"{freq:g}" for freq in selected_harmonics)
    for row in merged.itertuples(index=False):
        z_sum = getattr(row, "z_sum")
        legacy_z = getattr(row, "Legacy_Stouffer_z")
        rows.append(
            {
                "participant_id": workbook.subject_id,
                "condition": workbook.condition,
                "electrode": getattr(row, "electrode"),
                "harmonic_list": harmonic_list,
                "n_harmonics": len(selected_harmonics),
                "z_sum": z_sum,
                "p_one_tailed": getattr(row, "p_one_tailed"),
                "Legacy_Stouffer_z": legacy_z,
                "Legacy_Stouffer_p_one_tailed": getattr(row, "Legacy_Stouffer_p_one_tailed"),
                "Legacy_Stouffer_delta_z": (
                    float(z_sum) - float(legacy_z)
                    if np.isfinite(z_sum) and np.isfinite(legacy_z)
                    else np.nan
                ),
                "method": "Legacy_Stouffer comparison only; not used for publication detectability",
                "workbook_path": str(workbook.path),
            }
        )
    return rows


def _individual_detectability_counts(roi_summed_z: pd.DataFrame, electrode_fdr: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "condition",
        "roi",
        "threshold_method",
        "participant_count",
        "participants_detectable",
        "percent_detectable",
        "mean_significant_electrode_count",
        "sd_significant_electrode_count",
        "max_significant_electrode_count",
        "method",
    ]
    if roi_summed_z.empty and electrode_fdr.empty:
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, object]] = []

    if not roi_summed_z.empty:
        roi_frame = roi_summed_z.copy()
        for method, column in (
            ("roi_summed_z>1.64_uncorrected", "significant_z164"),
            ("roi_summed_z>2.32_uncorrected", "significant_z232"),
            ("roi_summed_z>3.10_uncorrected", "significant_z310"),
        ):
            for keys, group in roi_frame.groupby(["condition", "roi"], dropna=False):
                condition, roi = keys
                participant_count = int(group["participant_id"].nunique())
                detectable = int(group[column].fillna(False).astype(bool).sum())
                rows.append(
                    {
                        "condition": condition,
                        "roi": roi,
                        "threshold_method": method,
                        "participant_count": participant_count,
                        "participants_detectable": detectable,
                        "percent_detectable": (
                            detectable / participant_count if participant_count else np.nan
                        ),
                        "mean_significant_electrode_count": np.nan,
                        "sd_significant_electrode_count": np.nan,
                        "max_significant_electrode_count": np.nan,
                        "method": "ROI-averaged summed-harmonic Z",
                    }
                )

    if not electrode_fdr.empty:
        electrode_frame = _electrode_frame_with_roi_rows(electrode_fdr)
        for keys, group in electrode_frame.groupby(["condition", "roi"], dropna=False):
            condition, roi = keys
            participant_ids = sorted(group["participant_id"].dropna().astype(str).unique())
            sig = group.loc[group["significant_fdr_q05"].fillna(False).astype(bool)]
            counts = (
                sig.groupby("participant_id")["electrode"].nunique()
                .reindex(participant_ids, fill_value=0)
                .to_numpy(dtype=float)
            )
            participant_count = len(participant_ids)
            detectable = int((counts > 0).sum())
            rows.append(
                {
                    "condition": condition,
                    "roi": roi,
                    "threshold_method": "electrode_fdr_q<=0.05",
                    "participant_count": participant_count,
                    "participants_detectable": detectable,
                    "percent_detectable": (
                        detectable / participant_count if participant_count else np.nan
                    ),
                    "mean_significant_electrode_count": (
                        float(np.mean(counts)) if len(counts) else np.nan
                    ),
                    "sd_significant_electrode_count": _sd(counts),
                    "max_significant_electrode_count": (
                        float(np.max(counts)) if len(counts) else np.nan
                    ),
                    "method": "Electrode-level summed-harmonic Z with BH-FDR",
                }
            )
    return pd.DataFrame(rows, columns=columns)


def _electrode_frame_with_roi_rows(electrode_frame: pd.DataFrame) -> pd.DataFrame:
    if electrode_frame.empty:
        return electrode_frame.copy()
    rows: list[dict[str, object]] = []
    for row in electrode_frame.to_dict(orient="records"):
        whole = dict(row)
        whole["roi"] = WHOLE_SCALP_ROI
        rows.append(whole)
        roi_text = str(row.get("roi") or "").strip()
        if not roi_text:
            continue
        for roi_name in [part.strip() for part in roi_text.split(",") if part.strip()]:
            roi_row = dict(row)
            roi_row["roi"] = roi_name
            rows.append(roi_row)
    return pd.DataFrame(rows)


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
    frame = _electrode_frame_with_roi_rows(electrode_z_scores)
    rows: list[dict[str, object]] = []
    threshold_specs = [("fdr_q<=0.05", "significant_fdr_q05", np.nan)]
    for threshold in z_thresholds:
        suffix = {1.64: "164", 2.32: "232", 3.1: "310"}.get(
            round(float(threshold), 2),
            str(float(threshold)).replace(".", ""),
        )
        threshold_specs.append(
            (
                f"z>{threshold:g}_uncorrected",
                f"significant_z{suffix}",
                _z_p_value(float(threshold)),
            )
        )
    for keys, group in frame.groupby(["condition", "roi"], dropna=False):
        condition, roi = keys
        participant_count = int(group["participant_id"].nunique())
        tested_count = int(group["electrode"].nunique())
        for method, column, p_threshold in threshold_specs:
            if column not in group.columns:
                continue
            sig = group.loc[group[column].fillna(False).astype(bool)]
            counts = (
                sig.groupby("participant_id")["electrode"].nunique()
                .reindex(sorted(group["participant_id"].unique()), fill_value=0)
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


def _row_value(row: object, name: str, default: object = np.nan) -> object:
    if isinstance(row, pd.Series):
        return row.get(name, default)
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
        return mapping.get(normalized, mapping.get(name, default))
    except Exception:
        return default


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

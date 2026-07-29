"""Baseline-versus-zero one-sample tests for Condition x ROI cells."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    AnalysisRunSpec,
    CorrectionMethod,
    FamilySpec,
    HarmonicProvenance,
)
from Tools.Stats.analysis.multiple_comparisons import apply_family_correction
from Tools.Stats.reporting.stats_export import _auto_format_and_write_excel


def _one_sample_ttest(
    values: np.ndarray,
    *,
    alternative: Alternative,
) -> tuple[float, float]:
    """Return t-statistic and p-value with a SciPy compatibility fallback."""

    try:
        result = stats.ttest_1samp(
            values,
            popmean=0.0,
            alternative=alternative.scipy_value,
        )
        return float(result.statistic), float(result.pvalue)
    except TypeError:
        t_stat, p_two_sided = stats.ttest_1samp(values, popmean=0.0)
        if alternative is Alternative.TWO_SIDED:
            return float(t_stat), float(p_two_sided)
        if alternative is Alternative.GREATER:
            p_one_sided = (
                p_two_sided / 2.0
                if t_stat > 0
                else 1.0 - (p_two_sided / 2.0)
            )
        else:
            p_one_sided = (
                p_two_sided / 2.0
                if t_stat < 0
                else 1.0 - (p_two_sided / 2.0)
            )
        return float(t_stat), float(p_one_sided)


def _find_response_family(run_spec: AnalysisRunSpec) -> FamilySpec | None:
    """Return the run's declared complete-core response family, if present."""

    for spec in run_spec.families:
        if spec.family_id.casefold() == "response_core_cells":
            return spec
    return None


def _resolve_contract(
    *,
    alpha: float,
    alternative: str | Alternative,
    correction: str | CorrectionMethod,
    family_spec: FamilySpec | None,
    run_spec: AnalysisRunSpec | None,
    harmonic_provenance: HarmonicProvenance | str | None,
) -> tuple[Alternative, FamilySpec, HarmonicProvenance, str, str]:
    """Resolve legacy arguments and optional Phase-1 inference contracts."""

    if run_spec is not None and not isinstance(run_spec, AnalysisRunSpec):
        raise TypeError("run_spec must be an AnalysisRunSpec.")
    if family_spec is not None and not isinstance(family_spec, FamilySpec):
        raise TypeError("family_spec must be a FamilySpec.")

    effective_alternative = (
        run_spec.response_alternative
        if run_spec is not None
        else Alternative.coerce(alternative)
    )
    declared_response_family = (
        None if run_spec is None else _find_response_family(run_spec)
    )
    if family_spec is not None:
        effective_family = family_spec
    elif declared_response_family is not None:
        effective_family = declared_response_family
    else:
        default_method = CorrectionMethod.coerce(correction)
        if run_spec is not None and run_spec.profile is AnalysisProfile.CONFIRMATORY:
            default_method = CorrectionMethod.HOLM
        effective_family = FamilySpec(
            family_id="response_core_cells",
            family_label="Complete-core Condition x ROI response-versus-zero tests",
            method=default_method,
            alpha=run_spec.alpha if run_spec is not None else alpha,
        )

    if run_spec is not None:
        provenance = run_spec.harmonic_provenance
        if harmonic_provenance is not None:
            explicit_provenance = HarmonicProvenance.coerce(harmonic_provenance)
            if explicit_provenance is not provenance:
                raise ValueError(
                    "harmonic_provenance conflicts with run_spec.harmonic_provenance."
                )
        inference_status = run_spec.response_inference_status
        profile = run_spec.profile.value
    else:
        provenance = (
            HarmonicProvenance.UNKNOWN
            if harmonic_provenance is None
            else HarmonicProvenance.coerce(harmonic_provenance)
        )
        if provenance is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE:
            inference_status = "exploratory_post_selection"
        elif provenance is HarmonicProvenance.INDEPENDENTLY_SELECTED:
            inference_status = "confirmatory_eligible_not_declared"
        else:
            inference_status = "provenance_unverified"
        profile = "legacy_unspecified"

    return (
        effective_alternative,
        effective_family,
        provenance,
        inference_status,
        profile,
    )


def _append_note(row: dict[str, object], note: str) -> None:
    """Append a stable semicolon-delimited diagnostic note."""

    current = str(row.get("note", "") or "")
    row["note"] = f"{current};{note}" if current else note


def _within_roi_family(base: FamilySpec, roi: object) -> FamilySpec:
    """Return an explicitly named legacy within-ROI subfamily."""

    roi_label = str(roi)
    return replace(
        base,
        family_id=f"{base.family_id}.within_roi.{roi_label}",
        family_label=f"{base.family_label} within ROI {roi_label}",
    )


def run_baseline_vs_zero_tests(
    data: pd.DataFrame,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    alpha: float = 0.05,
    alternative: str | Alternative = "greater",
    correction: str | CorrectionMethod = "fdr_bh",
    correction_scope: str = "global",
    *,
    family_spec: FamilySpec | None = None,
    run_spec: AnalysisRunSpec | None = None,
    harmonic_provenance: HarmonicProvenance | str | None = None,
) -> tuple[str, pd.DataFrame]:
    """Run one-sample t-tests versus zero for each Condition x ROI cell."""

    if correction_scope not in {"global", "within_roi"}:
        raise ValueError("correction_scope must be 'global' or 'within_roi'.")
    (
        effective_alternative,
        effective_family,
        provenance,
        inference_status,
        analysis_profile,
    ) = _resolve_contract(
        alpha=alpha,
        alternative=alternative,
        correction=correction,
        family_spec=family_spec,
        run_spec=run_spec,
        harmonic_provenance=harmonic_provenance,
    )

    required_cols = [dv_col, subject_col, condition_col, roi_col]
    missing_cols = [col for col in required_cols if col not in data.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    key_counts = (
        data.groupby([subject_col, condition_col, roi_col], dropna=False)
        .size()
        .reset_index(name="count")
    )
    dupes = key_counts[key_counts["count"] > 1]
    if not dupes.empty:
        lines = [
            f"({row[subject_col]!r}, {row[condition_col]!r}, "
            f"{row[roi_col]!r}) -> {int(row['count'])}"
            for _, row in dupes.head(10).iterrows()
        ]
        raise ValueError(
            "Duplicate rows detected for participant-level keys; expected one row per "
            f"({subject_col}, {condition_col}, {roi_col}). Examples: "
            + "; ".join(lines)
        )

    rows: list[dict[str, object]] = []
    grouped = data.groupby([condition_col, roi_col], dropna=False, sort=True)
    for (condition, roi), sub_df in grouped:
        numeric = pd.to_numeric(sub_df[dv_col], errors="coerce")
        numeric_values = numeric.to_numpy(dtype=float, na_value=np.nan)
        finite_mask = np.isfinite(numeric_values)
        values = numeric_values[finite_mask]
        n = int(values.size)
        n_nonfinite = int((~finite_mask).sum())
        mean = float(np.mean(values)) if n else np.nan
        sd = float(np.std(values, ddof=1)) if n >= 2 else np.nan

        row: dict[str, object] = {
            "condition": condition,
            "roi": roi,
            "N": n,
            "n_nonfinite": n_nonfinite,
            "mean": mean,
            "sd": sd,
            "t": np.nan,
            "df": np.nan,
            "p_raw": np.nan,
            "cohens_d": np.nan,
            "cohens_dz": np.nan,
            "ci_mean_low": np.nan,
            "ci_mean_high": np.nan,
            "alternative": effective_alternative.value,
            "harmonic_provenance": provenance.value,
            "inference_status": inference_status,
            "analysis_profile": analysis_profile,
            "note": "",
        }
        if n_nonfinite:
            _append_note(row, "nonfinite_or_nonnumeric_values_dropped")

        if n < 3:
            _append_note(row, "insufficient_n")
            rows.append(row)
            continue
        if not np.isfinite(sd) or sd <= 0.0:
            _append_note(row, "zero_variance")
            rows.append(row)
            continue

        t_stat, p_raw = _one_sample_ttest(
            values,
            alternative=effective_alternative,
        )
        if not np.isfinite(t_stat) or not np.isfinite(p_raw):
            _append_note(row, "non_estimable_test")
            rows.append(row)
            continue

        row["t"] = t_stat
        row["df"] = float(n - 1)
        row["p_raw"] = p_raw
        effect_size = mean / sd
        row["cohens_d"] = effect_size
        row["cohens_dz"] = effect_size
        se = sd / np.sqrt(n)
        ci_low, ci_high = stats.t.interval(
            1 - effective_family.alpha,
            df=n - 1,
            loc=mean,
            scale=se,
        )
        if np.isfinite(ci_low) and np.isfinite(ci_high):
            row["ci_mean_low"] = float(ci_low)
            row["ci_mean_high"] = float(ci_high)
        else:
            _append_note(row, "invalid_confidence_interval")
        rows.append(row)

    raw_columns = [
        "condition",
        "roi",
        "N",
        "n_nonfinite",
        "mean",
        "sd",
        "t",
        "df",
        "p_raw",
        "cohens_d",
        "cohens_dz",
        "ci_mean_low",
        "ci_mean_high",
        "alternative",
        "harmonic_provenance",
        "inference_status",
        "analysis_profile",
        "note",
    ]
    results_df = pd.DataFrame(rows, columns=raw_columns)

    if correction_scope == "global" or results_df.empty:
        results_df = apply_family_correction(
            results_df,
            effective_family,
            p_col="p_raw",
        )
    else:
        parts: list[pd.DataFrame] = []
        for roi, roi_df in results_df.groupby("roi", dropna=False, sort=False):
            parts.append(
                apply_family_correction(
                    roi_df,
                    _within_roi_family(effective_family, roi),
                    p_col="p_raw",
                )
            )
        results_df = pd.concat(parts, axis=0).sort_index(kind="stable")

    # Backward-compatible result aliases. New code should use the generic fields.
    results_df["p_corr"] = results_df["p_adjusted"]
    results_df["reject"] = results_df["reject_adjusted"]

    results_df = results_df[
        [
            "condition",
            "roi",
            "N",
            "n_nonfinite",
            "mean",
            "sd",
            "t",
            "df",
            "p_raw",
            "p_corr",
            "reject",
            "cohens_d",
            "cohens_dz",
            "ci_mean_low",
            "ci_mean_high",
            "family_id",
            "family_label",
            "family_size",
            "adjustment_method",
            "alpha",
            "p_adjusted",
            "reject_adjusted",
            "alternative",
            "harmonic_provenance",
            "inference_status",
            "analysis_profile",
            "note",
        ]
    ]

    significant = results_df[results_df["reject_adjusted"].fillna(False)]
    significant_lines = [
        (
            f"{idx}. {row['condition']} in {row['roi']}: "
            f"mean={row['mean']:.6g}, corrected p={row['p_adjusted']:.6g}"
        )
        for idx, (_, row) in enumerate(significant.iterrows(), start=1)
        if pd.notna(row["p_adjusted"])
    ]
    significant_text = (
        "\n".join(significant_lines)
        if significant_lines
        else "No condition/ROI cells were significant after correction."
    )

    log_text = (
        "Baseline vs Zero tests completed.\n"
        f"Test settings: alpha={effective_family.alpha}; "
        f"alternative={effective_alternative.value}; "
        f"correction={effective_family.method.value}; "
        f"scope={correction_scope}.\n"
        f"Inference status: {inference_status}; "
        f"harmonic provenance={provenance.value}.\n"
        f"Summary: {len(results_df)} condition/ROI cells tested; "
        f"{int(results_df['p_raw'].notna().sum())} valid p-values; "
        f"{int(results_df['reject_adjusted'].fillna(False).sum())} "
        "significant after correction.\n"
        "Corrected significant findings:\n"
        f"{significant_text}"
    )
    return log_text, results_df


def _first_result_value(
    results_df: pd.DataFrame,
    column: str,
    default: object,
) -> object:
    """Return the first non-missing result value for export metadata."""

    if column not in results_df.columns:
        return default
    values = results_df[column].dropna()
    return values.iloc[0] if not values.empty else default


def _correction_export_labels(method_value: object) -> tuple[str, str, str]:
    """Return short, descriptive, and p-column labels for a correction method."""

    try:
        method = CorrectionMethod.coerce(method_value)  # type: ignore[arg-type]
    except ValueError:
        raw = str(method_value)
        return raw, raw, f"p (adjusted: {raw})"
    if method is CorrectionMethod.BH_FDR:
        return (
            "BH-FDR",
            "fdr_bh (Benjamini-Hochberg false-discovery rate)",
            "p (BH-FDR corrected)",
        )
    if method is CorrectionMethod.HOLM:
        return (
            "Holm",
            "holm (Holm familywise-error rate)",
            "p (adjusted: Holm)",
        )
    return (
        "None",
        "none (no multiplicity adjustment)",
        "p (unadjusted)",
    )


def export_baseline_vs_zero_results_to_excel(
    payload: dict[str, object],
    save_path: str | Path,
    log_func: Callable[[str], None],
) -> bool:
    """Write baseline-versus-zero results and explicit metadata."""

    if not isinstance(payload, dict):
        raise ValueError("Baseline-vs-zero export payload must be a dictionary.")
    results_df = payload.get("results_df")
    if not isinstance(results_df, pd.DataFrame):
        raise ValueError(
            "Baseline-vs-zero export payload missing 'results_df' DataFrame."
        )

    metadata_obj = payload.get("metadata")
    metadata: dict[str, object] = (
        metadata_obj if isinstance(metadata_obj, dict) else {}
    )
    correction_method_raw = metadata.get(
        "correction",
        _first_result_value(results_df, "adjustment_method", "fdr_bh"),
    )
    correction_scope = str(metadata.get("correction_scope", "global"))
    (
        correction_method_short,
        correction_method_label,
        adjusted_p_column_label,
    ) = _correction_export_labels(correction_method_raw)
    correction_scope_definition = (
        "Across all Condition x ROI cells with finite raw p-values."
        if correction_scope == "global"
        else (
            "Within each ROI across condition cells, using finite raw "
            "p-values only."
        )
    )

    export_df = results_df.copy()
    if "p_raw" in export_df.columns:
        export_df = export_df.rename(columns={"p_raw": "p (raw)"})
    if "p_adjusted" in export_df.columns:
        export_df = export_df.rename(
            columns={"p_adjusted": adjusted_p_column_label}
        )
    elif "p_corr" in export_df.columns:
        export_df = export_df.rename(columns={"p_corr": adjusted_p_column_label})
    export_df["correction_method"] = correction_method_short
    export_df["correction_scope"] = correction_scope

    n_by_cell = (
        export_df.loc[:, ["condition", "roi", "N"]]
        if {"condition", "roi", "N"}.issubset(export_df.columns)
        else pd.DataFrame(columns=["condition", "roi", "N"])
    )
    summary_rows = [
        {"field": "timestamp", "value": datetime.now().isoformat(timespec="seconds")},
        {"field": "dv_col", "value": metadata.get("dv_col", "value")},
        {
            "field": "alpha",
            "value": metadata.get(
                "alpha",
                _first_result_value(results_df, "alpha", 0.05),
            ),
        },
        {
            "field": "alternative",
            "value": metadata.get(
                "alternative",
                _first_result_value(results_df, "alternative", "greater"),
            ),
        },
        {"field": "correction", "value": str(correction_method_raw)},
        {"field": "correction_method", "value": correction_method_label},
        {"field": "correction_scope", "value": correction_scope},
        {
            "field": "correction_scope_definition",
            "value": correction_scope_definition,
        },
        {"field": "corrected_p_value_column", "value": "p_adjusted"},
        {
            "field": "corrected_p_value_column_in_sheet",
            "value": adjusted_p_column_label,
        },
        {
            "field": "family_id",
            "value": _first_result_value(results_df, "family_id", ""),
        },
        {
            "field": "family_label",
            "value": _first_result_value(results_df, "family_label", ""),
        },
        {
            "field": "family_size",
            "value": _first_result_value(results_df, "family_size", 0),
        },
        {
            "field": "harmonic_provenance",
            "value": metadata.get(
                "harmonic_provenance",
                _first_result_value(results_df, "harmonic_provenance", "unknown"),
            ),
        },
        {
            "field": "inference_status",
            "value": metadata.get(
                "inference_status",
                _first_result_value(
                    results_df,
                    "inference_status",
                    "provenance_unverified",
                ),
            ),
        },
        {
            "field": "analysis_profile",
            "value": metadata.get(
                "analysis_profile",
                _first_result_value(
                    results_df,
                    "analysis_profile",
                    "legacy_unspecified",
                ),
            ),
        },
        {
            "field": "total_unique_subjects",
            "value": metadata.get("total_unique_subjects", np.nan),
        },
    ]
    for field in (
        "dv_policy_name",
        "harmonic_policy",
        "harmonic_policy_label",
        "selected_harmonics_hz",
        "snr_used_for_statistics",
        "applied_uniformly_across_participants",
        "applied_uniformly_across_conditions",
        "applied_uniformly_across_rois",
    ):
        if field in metadata:
            summary_rows.append({"field": field, "value": metadata.get(field)})
    metadata_df = pd.concat(
        [
            pd.DataFrame(summary_rows),
            pd.DataFrame(
                [
                    {
                        "field": "n_by_condition_roi",
                        "value": "",
                        "condition": row["condition"],
                        "roi": row["roi"],
                        "N": row["N"],
                    }
                    for _, row in n_by_cell.iterrows()
                ]
            ),
        ],
        ignore_index=True,
    )

    save_path = Path(save_path)
    with pd.ExcelWriter(save_path, engine="xlsxwriter") as writer:
        _auto_format_and_write_excel(
            writer,
            export_df,
            "Baseline_vs_Zero",
            log_func,
        )
        _auto_format_and_write_excel(writer, metadata_df, "Metadata", log_func)
    return True

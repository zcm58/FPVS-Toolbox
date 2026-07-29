"""Post-hoc and planned-contrast analyses for Summed BCA data.

The public functions retain their established return shape and compatibility
columns.  New inference columns make the correction family, adjustment method,
and reason for each follow-up explicit.
"""

from __future__ import annotations

from itertools import combinations
import re
from typing import Iterable, Literal, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Stats.analysis.diagnostics import build_shapiro_diagnostic
from Tools.Stats.analysis.inference_contracts import (
    CorrectionMethod,
    FamilySpec,
    FollowupProvenance,
)
from Tools.Stats.analysis.multiple_comparisons import apply_family_correction


Direction = Literal["condition_within_roi", "roi_within_condition", "both"]
FamilyScope = Literal["direction", "stratum"]


def _effectively_zero_sd(sd: float, values: np.ndarray) -> bool:
    """Return whether spread is zero within floating-point precision."""

    if sd == 0.0:
        return True
    finite = np.asarray(values, dtype=float)
    scale = float(np.max(np.abs(finite))) if finite.size else 0.0
    if scale == 0.0:
        return True
    return bool(sd <= np.finfo(float).eps * scale * 8.0)


def _paired_effect_size_and_ci(
    diff: np.ndarray,
    alpha: float = 0.05,
) -> Tuple[float, float, float]:
    """Return finite-safe ``(dz, ci_low, ci_high)`` for paired differences.

    Exact zero differences have ``dz=0`` and a point interval at zero.  A
    constant non-zero difference has no finite standardized effect, while its
    mean-difference interval remains the corresponding point interval.
    """

    values = pd.to_numeric(pd.Series(np.asarray(diff).reshape(-1)), errors="coerce")
    values = values[np.isfinite(values.to_numpy(dtype=float))].to_numpy(dtype=float)
    if values.size < 3:
        return np.nan, np.nan, np.nan
    mean = float(np.mean(values))
    sd = float(np.std(values, ddof=1))
    if not np.isfinite(sd):
        return np.nan, np.nan, np.nan
    if _effectively_zero_sd(sd, values):
        dz = 0.0 if mean == 0.0 else np.nan
        return dz, mean, mean
    dz = float(mean / sd)
    se = float(sd / np.sqrt(values.size))
    ci_low, ci_high = stats.t.interval(
        1 - alpha,
        df=values.size - 1,
        loc=mean,
        scale=se,
    )
    if not np.isfinite(ci_low) or not np.isfinite(ci_high) or ci_low > ci_high:
        return dz, np.nan, np.nan
    return dz, float(ci_low), float(ci_high)


def _difference_statistics(
    diff: object,
    *,
    alpha: float,
    alternative: Literal["two-sided", "greater"] = "two-sided",
) -> dict[str, object]:
    """Return one explicit inferential row for paired differences."""

    numeric = pd.to_numeric(pd.Series(diff), errors="coerce")
    finite = numeric[np.isfinite(numeric.to_numpy(dtype=float))].to_numpy(dtype=float)
    n = int(finite.size)
    mean = float(np.mean(finite)) if n else np.nan
    sd = float(np.std(finite, ddof=1)) if n >= 2 else np.nan
    dz, ci_low, ci_high = _paired_effect_size_and_ci(finite, alpha=alpha)
    shapiro = build_shapiro_diagnostic(finite, alpha=alpha)

    result: dict[str, object] = {
        "N_Pairs": n,
        "mean_diff": mean,
        "sd_diff": sd,
        "t_statistic": np.nan,
        "df": float(n - 1) if n else np.nan,
        "p_raw": np.nan,
        "ci95_low": ci_low,
        "ci95_high": ci_high,
        "cohens_dz": dz,
        "inference_status": "not_estimable",
        "status_code": "insufficient_pairs",
        "shapiro_W_diff": shapiro.statistic,
        "shapiro_p_diff": shapiro.p_raw,
        "shapiro_status": shapiro.status.value,
        "shapiro_code": shapiro.code,
    }
    if n < 3:
        return result
    if not np.isfinite(sd):
        result["status_code"] = "invalid_variance"
        return result
    if _effectively_zero_sd(sd, finite):
        result["status_code"] = (
            "zero_variance_zero_difference"
            if mean == 0.0
            else "zero_variance_nonzero_difference"
        )
        return result

    test = stats.ttest_1samp(finite, popmean=0.0, alternative=alternative)
    t_stat = float(test.statistic)
    p_raw = float(test.pvalue)
    if not np.isfinite(t_stat) or not np.isfinite(p_raw):
        result["status_code"] = "invalid_test_result"
        return result
    result.update(
        {
            "t_statistic": t_stat,
            "p_raw": p_raw,
            "inference_status": "estimated",
            "status_code": "ok",
        }
    )
    return result


def _raw_pairwise_results(
    data: pd.DataFrame,
    *,
    dv_col: str,
    factor_col: str,
    subject_col: str,
    alpha: float,
) -> pd.DataFrame:
    """Build unadjusted paired comparisons for one supplied data slice."""

    levels = list(data[factor_col].dropna().unique())
    rows: list[dict[str, object]] = []
    for level_a, level_b in combinations(levels, 2):
        df_a = data[data[factor_col] == level_a][[subject_col, dv_col]]
        df_b = data[data[factor_col] == level_b][[subject_col, dv_col]]
        merged = pd.merge(df_a, df_b, on=subject_col, suffixes=("_a", "_b"))
        value_a = pd.to_numeric(merged[f"{dv_col}_a"], errors="coerce")
        value_b = pd.to_numeric(merged[f"{dv_col}_b"], errors="coerce")
        finite_mask = np.isfinite(value_a.to_numpy(dtype=float)) & np.isfinite(
            value_b.to_numpy(dtype=float)
        )
        diff = (
            value_a.loc[finite_mask].to_numpy(dtype=float)
            - value_b.loc[finite_mask].to_numpy(dtype=float)
        )
        row = {
            "Level_A": level_a,
            "Level_B": level_b,
            "N_Rows_Merged": int(len(merged)),
        }
        row.update(_difference_statistics(diff, alpha=alpha))
        rows.append(row)
    return pd.DataFrame.from_records(rows)


def _family_spec(
    *,
    family_id: str,
    family_label: str,
    correction: CorrectionMethod | str,
    alpha: float,
) -> FamilySpec:
    return FamilySpec(
        family_id=family_id,
        family_label=family_label,
        method=CorrectionMethod.coerce(correction),
        alpha=alpha,
    )


def _add_compatibility_columns(
    results: pd.DataFrame,
    *,
    method: CorrectionMethod,
    include_p_corr: bool = False,
) -> pd.DataFrame:
    """Add established aliases without mislabelling non-BH adjustments."""

    out = results.copy()
    out["p_value"] = pd.to_numeric(out.get("p_raw"), errors="coerce")
    out["Significant"] = out.get("reject_adjusted", False)
    out["Significant"] = out["Significant"].fillna(False).astype(bool)
    if method is CorrectionMethod.BH_FDR:
        out["p_fdr_bh"] = pd.to_numeric(out.get("p_adjusted"), errors="coerce")
    elif "p_fdr_bh" in out.columns:
        out = out.drop(columns=["p_fdr_bh"])
    if include_p_corr:
        out["p_corr"] = pd.to_numeric(out.get("p_adjusted"), errors="coerce")
    return out


def _coerce_provenance(
    value: FollowupProvenance | str,
) -> FollowupProvenance:
    return FollowupProvenance.coerce(value)  # type: ignore[return-value]


def _format_pairwise_log(
    results: pd.DataFrame,
    *,
    factor_col: str,
    family: FamilySpec,
) -> str:
    lines = [
        "============================================================",
        "              Post-hoc Pairwise Comparisons",
        "============================================================",
        f"Factor analyzed: '{factor_col}'",
        f"Correction family: {family.family_label} ({family.family_id})",
        f"Correction method: {family.method.value}",
        f"Significance level: alpha = {family.alpha}",
        "",
    ]
    for _, row in results.iterrows():
        lines.append(f"--- {row['Level_A']} vs {row['Level_B']} ---")
        if row.get("inference_status") != "estimated":
            lines.append(f"  Not estimable: {row.get('status_code', 'unknown')}.\n")
            continue
        lines.append(f"  t({int(row['df'])}) = {float(row['t_statistic']):.3f}")
        lines.append(
            f"  Raw p-value = {float(row['p_raw']):.4f}  |  "
            f"Adjusted p ({family.method.value}) = {float(row['p_adjusted']):.4f}"
        )
        lines.append(
            f"  Mean diff (A-B) = {float(row['mean_diff']):.4f}  "
            f"95% CI [{float(row['ci95_low']):.4f}, {float(row['ci95_high']):.4f}]  "
            f"Cohen's dz = {float(row['cohens_dz']):.3f}"
        )
        if np.isfinite(float(row.get("shapiro_p_diff", np.nan))):
            lines.append(
                "  Normality of paired differences "
                f"(Shapiro raw p) = {float(row['shapiro_p_diff']):.3f} (diagnostic only)"
            )
        lines.append(
            "  "
            + (
                "FINDING: SIGNIFICANT AFTER CORRECTION.\n"
                if bool(row["reject_adjusted"])
                else "Finding: Not significant after correction.\n"
            )
        )
    lines.append("============================================================")
    return "\n".join(lines)


def run_posthoc_pairwise_tests(
    data: pd.DataFrame,
    dv_col: str,
    factor_col: str,
    subject_col: str,
    correction: str = "fdr_bh",
    alpha: float = 0.05,
    followup_provenance: FollowupProvenance | str = FollowupProvenance.EXPLORATORY_MANUAL,
    family_id: str | None = None,
    family_label: str | None = None,
):
    """Run paired comparisons across all levels of one within-subject factor.

    The supplied data define one correction family.  Existing callers retain
    BH-FDR by default, while new callers can name the family explicitly.
    """

    required = (factor_col, dv_col, subject_col)
    missing = [column for column in required if column not in data.columns]
    if missing:
        return (
            "Required column(s) missing. Cannot run post-hoc tests: "
            + ", ".join(repr(column) for column in missing),
            pd.DataFrame(),
        )
    levels = list(data[factor_col].dropna().unique())
    if len(levels) < 2:
        return "Not enough levels for pairwise comparisons.", pd.DataFrame()

    provenance = _coerce_provenance(followup_provenance)
    family = _family_spec(
        family_id=family_id or f"posthoc_{factor_col}",
        family_label=family_label or f"All pairwise comparisons for {factor_col}",
        correction=correction,
        alpha=alpha,
    )
    raw = _raw_pairwise_results(
        data,
        dv_col=dv_col,
        factor_col=factor_col,
        subject_col=subject_col,
        alpha=alpha,
    )
    raw["followup_provenance"] = provenance.value
    results = apply_family_correction(raw, family, p_col="p_raw")
    results = _add_compatibility_columns(results, method=family.method)
    results.attrs.update(
        {
            "family_scope": "supplied_data",
            "followup_provenance": provenance.value,
        }
    )
    return _format_pairwise_log(results, factor_col=factor_col, family=family), results


def _requested_directions(direction: Direction) -> tuple[str, ...]:
    if direction == "both":
        return ("condition_within_roi", "roi_within_condition")
    if direction in {"condition_within_roi", "roi_within_condition"}:
        return (direction,)
    raise ValueError(
        "direction must be 'condition_within_roi', 'roi_within_condition', or 'both'"
    )


def _normalized_omnibus_result(
    *,
    omnibus_p_value: object | None,
    omnibus_significant: object | None,
    alpha: float,
) -> tuple[float | None, bool | None]:
    p_value: float | None = None
    if omnibus_p_value is not None:
        try:
            candidate = float(omnibus_p_value)
        except (TypeError, ValueError, OverflowError):
            candidate = np.nan
        if np.isfinite(candidate) and 0.0 <= candidate <= 1.0:
            p_value = candidate

    significant: bool | None = None
    if isinstance(omnibus_significant, (bool, np.bool_)):
        significant = bool(omnibus_significant)
    elif omnibus_significant is not None:
        raise ValueError("omnibus_significant must be True, False, or None")
    if significant is None and p_value is not None:
        significant = bool(p_value < alpha)
    if (
        significant is not None
        and p_value is not None
        and significant != bool(p_value < alpha)
    ):
        raise ValueError("omnibus_significant conflicts with omnibus_p_value at the supplied alpha")
    return p_value, significant


def _family_identity(direction: str) -> tuple[str, str]:
    if direction == "condition_within_roi":
        return (
            "interaction_condition_within_roi",
            "Condition comparisons across all ROI strata",
        )
    return (
        "interaction_roi_within_condition",
        "ROI comparisons across all condition strata",
    )


def _safe_family_token(value: object) -> str:
    token = re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")
    return token or "unnamed"


def _not_run_interaction_results(
    *,
    directions: Sequence[str],
    reason: str,
    provenance: FollowupProvenance,
    correction: CorrectionMethod,
    alpha: float,
    omnibus_p_value: float | None,
    omnibus_significant: bool | None,
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for requested_direction in directions:
        family_id, family_label = _family_identity(requested_direction)
        factor = "condition" if requested_direction == "condition_within_roi" else "roi"
        row = pd.DataFrame(
            [
                {
                    "Level_A": None,
                    "Level_B": None,
                    "N_Pairs": 0,
                    "t_statistic": np.nan,
                    "df": np.nan,
                    "p_raw": np.nan,
                    "mean_diff": np.nan,
                    "ci95_low": np.nan,
                    "ci95_high": np.nan,
                    "cohens_dz": np.nan,
                    "shapiro_p_diff": np.nan,
                    "inference_status": "not_run",
                    "status_code": reason,
                    "Direction": requested_direction,
                    "Stratum": np.nan,
                    "FactorAnalyzed": factor,
                    "Slice": np.nan,
                    "Factor": factor,
                    "ROI": np.nan,
                    "Condition": np.nan,
                    "followup_provenance": provenance.value,
                    "omnibus_p_value": omnibus_p_value,
                    "omnibus_significant": omnibus_significant,
                    "omnibus_gate_applied": True,
                }
            ]
        )
        family = _family_spec(
            family_id=family_id,
            family_label=family_label,
            correction=correction,
            alpha=alpha,
        )
        pieces.append(apply_family_correction(row, family, p_col="p_raw"))
    result = pd.concat(pieces, ignore_index=True)
    return _add_compatibility_columns(result, method=correction)


def _apply_interaction_families(
    raw_results: pd.DataFrame,
    *,
    correction: CorrectionMethod,
    alpha: float,
    family_scope: FamilyScope,
) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    raw = raw_results.copy()
    raw["_original_order"] = np.arange(len(raw), dtype=int)

    if family_scope == "direction":
        family_keys = [
            (direction, None)
            for direction in raw["Direction"].dropna().astype(str).drop_duplicates()
        ]
    elif family_scope == "stratum":
        family_keys = list(
            raw[["Direction", "Stratum"]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
    else:
        raise ValueError("family_scope must be 'direction' or 'stratum'")

    for direction, stratum in family_keys:
        mask = raw["Direction"].astype(str).eq(str(direction))
        if family_scope == "stratum":
            mask &= raw["Stratum"].eq(stratum)
        family_id, family_label = _family_identity(str(direction))
        if family_scope == "stratum":
            token = _safe_family_token(stratum)
            family_id = f"{family_id}_{token}"
            family_label = f"{family_label} within {stratum}"
        family = _family_spec(
            family_id=family_id,
            family_label=family_label,
            correction=correction,
            alpha=alpha,
        )
        pieces.append(apply_family_correction(raw.loc[mask], family, p_col="p_raw"))

    if not pieces:
        return raw.drop(columns=["_original_order"])
    corrected = pd.concat(pieces, axis=0)
    corrected = corrected.sort_values("_original_order", kind="stable")
    return corrected.drop(columns=["_original_order"]).reset_index(drop=True)


def _interaction_report(results: pd.DataFrame, *, directions: Sequence[str]) -> str:
    summary = [
        "============================================================",
        "        SUMMARY OF SIGNIFICANT FINDINGS",
        "============================================================",
    ]
    labels = {
        "condition_within_roi": "Simple effects: Condition within ROI",
        "roi_within_condition": "Simple effects: ROI within Condition",
    }
    for direction in directions:
        summary.extend([labels[direction], "------------------------------------------------------------"])
        subset = results[results["Direction"] == direction]
        significant = subset[subset["reject_adjusted"].fillna(False).astype(bool)]
        if significant.empty:
            summary.append("No significant differences found after the declared correction.")
        else:
            for _, row in significant.iterrows():
                context_name = "ROI" if direction == "condition_within_roi" else "Condition"
                summary.append(
                    f"{context_name} {row['Stratum']}: {row['Level_A']} vs {row['Level_B']} "
                    f"(t={float(row['t_statistic']):.3f}, "
                    f"adjusted p={float(row['p_adjusted']):.4f}, "
                    f"dz={float(row['cohens_dz']):.2f})"
                )
        summary.append("")

    detail = [
        "============================================================",
        "         Post-hoc Comparisons: Condition by ROI",
        "============================================================",
    ]
    for direction in directions:
        subset = results[results["Direction"] == direction]
        detail.append(labels[direction])
        for _, row in subset.iterrows():
            if row.get("inference_status") != "estimated":
                detail.append(
                    f"- {row.get('Stratum')}: {row.get('Level_A')} vs {row.get('Level_B')} "
                    f"not estimable ({row.get('status_code')})."
                )
                continue
            detail.append(
                f"- {row['Stratum']}: {row['Level_A']} vs {row['Level_B']}; "
                f"raw p={float(row['p_raw']):.4f}, "
                f"adjusted p={float(row['p_adjusted']):.4f}, "
                f"family={row['family_id']}."
            )
    return "\n".join([*summary, *detail])


def run_interaction_posthocs(
    data: pd.DataFrame,
    dv_col: str,
    roi_col: str,
    condition_col: str,
    subject_col: str,
    correction: str = "fdr_bh",
    alpha: float = 0.05,
    direction: Direction = "both",
    followup_provenance: FollowupProvenance | str = FollowupProvenance.EXPLORATORY_MANUAL,
    omnibus_p_value: float | None = None,
    omnibus_significant: bool | None = None,
    enforce_omnibus_gate: bool = True,
    family_scope: FamilyScope = "direction",
):
    """Run simple-effect post-hocs for a Condition-by-ROI interaction.

    The default ``family_scope='direction'`` corrects one family across every
    stratum contributing to a requested headline.  ``family_scope='stratum'``
    is an explicit compatibility option for the historical per-ROI/per-
    condition correction.

    Existing callers default to ``exploratory_manual`` provenance and continue
    to run.  An ``omnibus_triggered`` follow-up is automatically gated unless
    the interaction was significant; planned and manually requested
    exploratory follow-ups are not gated.
    """

    required = (dv_col, roi_col, condition_col, subject_col)
    missing = [column for column in required if column not in data.columns]
    if missing:
        return (
            "Required column(s) missing. Cannot run interaction post-hocs: "
            + ", ".join(repr(column) for column in missing),
            pd.DataFrame(),
        )
    try:
        directions = _requested_directions(direction)
    except ValueError as exc:
        return str(exc), pd.DataFrame()

    provenance = _coerce_provenance(followup_provenance)
    method = CorrectionMethod.coerce(correction)
    p_omnibus, significant_omnibus = _normalized_omnibus_result(
        omnibus_p_value=omnibus_p_value,
        omnibus_significant=omnibus_significant,
        alpha=alpha,
    )
    gate_reason: str | None = None
    if provenance is FollowupProvenance.OMNIBUS_TRIGGERED and enforce_omnibus_gate:
        if significant_omnibus is None:
            gate_reason = "omnibus_result_unavailable"
        elif not significant_omnibus:
            gate_reason = "omnibus_not_significant"
    if gate_reason is not None:
        gated = _not_run_interaction_results(
            directions=directions,
            reason=gate_reason,
            provenance=provenance,
            correction=method,
            alpha=alpha,
            omnibus_p_value=p_omnibus,
            omnibus_significant=significant_omnibus,
        )
        gated.attrs.update(
            {
                "family_scope": family_scope,
                "followup_provenance": provenance.value,
                "omnibus_gate_applied": True,
                "omnibus_gate_status": gate_reason,
            }
        )
        return (
            "Interaction follow-up tests were not run "
            f"({gate_reason}; provenance={provenance.value}).",
            gated,
        )

    rows: list[pd.DataFrame] = []
    if "condition_within_roi" in directions:
        for roi in list(data[roi_col].dropna().unique()):
            cell = _raw_pairwise_results(
                data[data[roi_col] == roi],
                dv_col=dv_col,
                factor_col=condition_col,
                subject_col=subject_col,
                alpha=alpha,
            )
            if not cell.empty:
                rows.append(
                    cell.assign(
                        Direction="condition_within_roi",
                        Stratum=roi,
                        FactorAnalyzed="condition",
                        Slice=roi,
                        Factor=condition_col,
                        ROI=roi,
                        Condition=np.nan,
                    )
                )
    if "roi_within_condition" in directions:
        for condition in list(data[condition_col].dropna().unique()):
            cell = _raw_pairwise_results(
                data[data[condition_col] == condition],
                dv_col=dv_col,
                factor_col=roi_col,
                subject_col=subject_col,
                alpha=alpha,
            )
            if not cell.empty:
                rows.append(
                    cell.assign(
                        Direction="roi_within_condition",
                        Stratum=condition,
                        FactorAnalyzed="roi",
                        Slice=condition,
                        Factor=roi_col,
                        ROI=np.nan,
                        Condition=condition,
                    )
                )

    if not rows:
        return "No analyzable interaction post-hoc comparisons were available.", pd.DataFrame()
    raw_results = pd.concat(rows, ignore_index=True)
    raw_results["followup_provenance"] = provenance.value
    raw_results["omnibus_p_value"] = p_omnibus
    raw_results["omnibus_significant"] = significant_omnibus
    raw_results["omnibus_gate_applied"] = bool(
        provenance is FollowupProvenance.OMNIBUS_TRIGGERED and enforce_omnibus_gate
    )
    results = _apply_interaction_families(
        raw_results,
        correction=method,
        alpha=alpha,
        family_scope=family_scope,
    )
    results = _add_compatibility_columns(results, method=method)
    results.attrs.update(
        {
            "family_scope": family_scope,
            "followup_provenance": provenance.value,
            "omnibus_gate_applied": bool(
                provenance is FollowupProvenance.OMNIBUS_TRIGGERED
                and enforce_omnibus_gate
            ),
            "omnibus_gate_status": "passed" if provenance is FollowupProvenance.OMNIBUS_TRIGGERED else "not_applicable",
        }
    )
    return _interaction_report(results, directions=directions), results


def run_planned_contrasts_category_vs_color(
    data: pd.DataFrame,
    dv_col: str,
    roi_col: str,
    condition_col: str,
    subject_col: str,
    category_condition: str = "Green Fruit vs Green Veg",
    color_conditions: Iterable[str] = ("Green Veg vs Red Veg", "Red Fruit vs Green Fruit"),
    rois: Optional[Iterable[str]] = None,
    alpha: float = 0.05,
    correction: str = "holm",
    one_tailed_greater: bool = False,
    followup_provenance: FollowupProvenance | str = FollowupProvenance.PLANNED,
):
    """Run the planned Category-minus-average(Color) contrast within each ROI."""

    color_conditions = tuple(color_conditions)
    lines = [
        "============================================================",
        "      Planned Contrast: Category vs Average(Color) by ROI",
        "============================================================",
        f"Category = '{category_condition}' | Colors = {color_conditions}",
    ]
    required = {dv_col, roi_col, condition_col, subject_col}
    if not required.issubset(data.columns):
        lines.append("Required columns missing. Cannot run planned contrasts.")
        return "\n".join(lines), pd.DataFrame()

    provenance = _coerce_provenance(followup_provenance)
    all_rois = list(data[roi_col].dropna().unique()) if rois is None else list(rois)
    rows: list[dict[str, object]] = []
    for roi in all_rois:
        cell = data[data[roi_col] == roi]
        wide = cell.pivot_table(
            index=subject_col,
            columns=condition_col,
            values=dv_col,
            aggfunc="mean",
        )
        needed = [category_condition, *color_conditions]
        if not set(needed).issubset(wide.columns):
            lines.append(f"ROI {roi}: Missing required conditions; skipping.")
            continue
        delta = wide[category_condition] - wide[list(color_conditions)].mean(axis=1)
        statistics = _difference_statistics(
            delta,
            alpha=alpha,
            alternative="greater" if one_tailed_greater else "two-sided",
        )
        rows.append(
            {
                "ROI": roi,
                "N": statistics["N_Pairs"],
                "mean_diff": statistics["mean_diff"],
                "ci95_low": statistics["ci95_low"],
                "ci95_high": statistics["ci95_high"],
                "cohens_dz": statistics["cohens_dz"],
                "t": statistics["t_statistic"],
                "df": statistics["df"],
                "p_raw": statistics["p_raw"],
                "inference_status": statistics["inference_status"],
                "status_code": statistics["status_code"],
                "shapiro_W_diff": statistics["shapiro_W_diff"],
                "shapiro_p_diff": statistics["shapiro_p_diff"],
                "followup_provenance": provenance.value,
            }
        )

    result = pd.DataFrame.from_records(rows)
    if result.empty:
        lines.append("No ROI produced analyzable data for the planned contrast.")
        return "\n".join(lines), result

    family = _family_spec(
        family_id="planned_category_vs_color",
        family_label="Category versus average color contrasts across ROIs",
        correction=correction,
        alpha=alpha,
    )
    result = apply_family_correction(result, family, p_col="p_raw")
    result = _add_compatibility_columns(
        result,
        method=family.method,
        include_p_corr=True,
    )
    for _, row in result.iterrows():
        if row["inference_status"] != "estimated":
            lines.append(f"ROI {row['ROI']}: not estimable ({row['status_code']}).")
            continue
        lines.append(
            f"ROI {row['ROI']}: Category-Color average = {float(row['mean_diff']):.4f} "
            f"[95% CI {float(row['ci95_low']):.4f}, {float(row['ci95_high']):.4f}], "
            f"dz={float(row['cohens_dz']):.2f}, "
            f"t({int(row['df'])})={float(row['t']):.3f}, "
            f"adjusted p={float(row['p_adjusted']):.4f} "
            + ("**SIGNIFICANT**" if bool(row["reject_adjusted"]) else "ns")
        )
    lines.append("============================================================")
    return "\n".join(lines), result


__all__ = [
    "run_interaction_posthocs",
    "run_planned_contrasts_category_vs_color",
    "run_posthoc_pairwise_tests",
]

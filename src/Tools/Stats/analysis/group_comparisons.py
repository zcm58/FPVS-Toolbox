"""Between-group Condition x ROI comparisons for complete-core FPVS data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Stats.analysis.diagnostics import build_group_cell_diagnostics
from Tools.Stats.analysis.inference_contracts import CorrectionMethod, FamilySpec
from Tools.Stats.analysis.multiple_comparisons import apply_family_correction


GROUP_COMPARISON_SCHEMA_VERSION = 1
UNKNOWN_GROUP_VALUES = frozenset({"", "unknown", "unassigned", "none", "nan"})
ALLOWED_ANALYSIS_SCOPES = frozenset({"complete_core", "available_case"})


class GroupComparisonError(ValueError):
    """Raised when canonical group-cell comparisons cannot be defined."""


@dataclass(frozen=True)
class GroupComparisonResult:
    """Explicit cell contrasts, diagnostics, and export metadata."""

    contrasts: pd.DataFrame
    diagnostics: pd.DataFrame
    metadata: pd.DataFrame

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return additive workbook-ready frames."""

        return {
            "Group Cell Contrasts": self.contrasts.copy(),
            "Group Cell Diagnostics": self.diagnostics.copy(),
            "Group Comparison Metadata": self.metadata.copy(),
        }


def _normalized_group(value: object) -> str:
    if value is None or bool(pd.isna(value)):
        return ""
    return str(value).strip()


def _validate_group_assignments(
    data: pd.DataFrame,
    *,
    subject_col: str,
    group_col: str,
) -> tuple[str, ...]:
    normalized = data.loc[:, [subject_col, group_col]].copy()
    normalized[group_col] = normalized[group_col].map(_normalized_group)
    missing = normalized[group_col].str.casefold().isin(UNKNOWN_GROUP_VALUES)
    if bool(missing.any()):
        participants = sorted(
            normalized.loc[missing, subject_col].astype(str).unique().tolist(),
            key=str.casefold,
        )
        raise GroupComparisonError(
            "Canonical group assignment is missing or unknown for: "
            + ", ".join(participants)
        )
    counts = normalized.groupby(subject_col, dropna=False)[group_col].nunique()
    inconsistent = counts[counts > 1]
    if not inconsistent.empty:
        raise GroupComparisonError(
            "Each participant must have one canonical group ID; inconsistent "
            "assignments were found for: "
            + ", ".join(map(str, inconsistent.index.tolist()))
        )
    return tuple(
        sorted(normalized[group_col].unique().tolist(), key=str.casefold)
    )


def _resolve_group_pair(
    groups: Sequence[str],
    group_pair: Sequence[object] | None,
) -> tuple[str, str]:
    if group_pair is None:
        if len(groups) != 2:
            raise GroupComparisonError(
                "Exactly two canonical groups are required unless an explicit "
                "two-group comparison pair is selected."
            )
        return str(groups[0]), str(groups[1])
    if len(group_pair) != 2:
        raise GroupComparisonError("group_pair must contain exactly two group IDs.")
    group_a, group_b = (str(value).strip() for value in group_pair)
    if not group_a or not group_b or group_a.casefold() == group_b.casefold():
        raise GroupComparisonError("group_pair must contain two distinct group IDs.")
    by_key = {str(group).casefold(): str(group) for group in groups}
    missing = [
        group
        for group in (group_a, group_b)
        if group.casefold() not in by_key
    ]
    if missing:
        raise GroupComparisonError(
            "Selected group IDs are not present: " + ", ".join(missing)
        )
    return by_key[group_a.casefold()], by_key[group_b.casefold()]


def _validate_analysis_scope(
    data: pd.DataFrame,
    *,
    analysis_scope: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
) -> str:
    scope = str(analysis_scope).strip().casefold()
    if scope not in ALLOWED_ANALYSIS_SCOPES:
        raise GroupComparisonError(
            "analysis_scope must be 'complete_core' or 'available_case'."
        )
    if scope == "available_case":
        return scope

    observed_pairs = set(
        data[[condition_col, roi_col]].itertuples(index=False, name=None)
    )
    incomplete: list[object] = []
    for participant, rows in data.groupby(subject_col, dropna=False, sort=False):
        participant_pairs = set(
            rows[[condition_col, roi_col]].itertuples(index=False, name=None)
        )
        if participant_pairs != observed_pairs:
            incomplete.append(participant)
    if incomplete:
        examples = ", ".join(map(str, incomplete[:10]))
        raise GroupComparisonError(
            "Complete-core group comparisons require every participant to "
            "contribute every retained Condition x ROI cell. Incomplete "
            f"participants: {examples}"
        )
    return scope


def _hedges_g(
    mean_difference: float,
    *,
    n_a: int,
    n_b: int,
    variance_a: float,
    variance_b: float,
) -> float:
    """Return signed small-sample-corrected standardized mean difference."""

    pooled_df = n_a + n_b - 2
    if pooled_df <= 0:
        return np.nan
    pooled_variance = (
        (n_a - 1) * variance_a + (n_b - 1) * variance_b
    ) / pooled_df
    if not np.isfinite(pooled_variance) or pooled_variance <= 0.0:
        return np.nan
    cohen_d = mean_difference / np.sqrt(pooled_variance)
    correction = 1.0 - (3.0 / (4.0 * pooled_df - 1.0))
    return float(correction * cohen_d)


def _welch_statistics(
    values_a: np.ndarray,
    values_b: np.ndarray,
    *,
    alpha: float,
) -> dict[str, object]:
    n_a = int(values_a.size)
    n_b = int(values_b.size)
    mean_a = float(np.mean(values_a)) if n_a else np.nan
    mean_b = float(np.mean(values_b)) if n_b else np.nan
    sd_a = float(np.std(values_a, ddof=1)) if n_a >= 2 else np.nan
    sd_b = float(np.std(values_b, ddof=1)) if n_b >= 2 else np.nan
    difference = mean_a - mean_b if n_a and n_b else np.nan
    row: dict[str, object] = {
        "n_group_a": n_a,
        "mean_group_a": mean_a,
        "sd_group_a": sd_a,
        "n_group_b": n_b,
        "mean_group_b": mean_b,
        "sd_group_b": sd_b,
        "mean_difference_a_minus_b": difference,
        "welch_t": np.nan,
        "welch_df": np.nan,
        "p_raw": np.nan,
        "ci_difference_low": np.nan,
        "ci_difference_high": np.nan,
        "hedges_g": np.nan,
        "inference_status": "not_estimable",
        "status_code": "insufficient_group_n",
    }
    if n_a < 2 or n_b < 2:
        return row
    variance_a = sd_a**2
    variance_b = sd_b**2
    variance_term_a = variance_a / n_a
    variance_term_b = variance_b / n_b
    standard_error_squared = variance_term_a + variance_term_b
    if not np.isfinite(standard_error_squared) or standard_error_squared <= 0.0:
        row["status_code"] = "zero_or_invalid_standard_error"
        return row
    denominator = (
        (variance_term_a**2) / (n_a - 1)
        + (variance_term_b**2) / (n_b - 1)
    )
    if not np.isfinite(denominator) or denominator <= 0.0:
        row["status_code"] = "invalid_welch_degrees_of_freedom"
        return row
    welch_df = (standard_error_squared**2) / denominator
    standard_error = np.sqrt(standard_error_squared)
    welch_t = difference / standard_error
    p_raw = float(2.0 * stats.t.sf(abs(welch_t), df=welch_df))
    critical = float(stats.t.ppf(1.0 - alpha / 2.0, df=welch_df))
    margin = critical * standard_error
    values = (welch_t, welch_df, p_raw, difference - margin, difference + margin)
    if not all(np.isfinite(value) for value in values):
        row["status_code"] = "invalid_welch_result"
        return row
    row.update(
        {
            "welch_t": float(welch_t),
            "welch_df": float(welch_df),
            "p_raw": p_raw,
            "ci_difference_low": float(difference - margin),
            "ci_difference_high": float(difference + margin),
            "hedges_g": _hedges_g(
                difference,
                n_a=n_a,
                n_b=n_b,
                variance_a=variance_a,
                variance_b=variance_b,
            ),
            "inference_status": "estimated",
            "status_code": "ok",
        }
    )
    return row


def run_group_cell_comparisons(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    group_col: str,
    condition_col: str,
    roi_col: str,
    group_pair: Sequence[object] | None = None,
    family_spec: FamilySpec | None = None,
    correction: CorrectionMethod | str = CorrectionMethod.HOLM,
    alpha: float = 0.05,
    analysis_scope: str = "complete_core",
) -> GroupComparisonResult:
    """Run two-sided Welch comparisons across a declared complete-cell family."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    required = (dv_col, subject_col, group_col, condition_col, roi_col)
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise GroupComparisonError(f"Missing required columns: {missing}")
    if not 0.0 < float(alpha) < 1.0:
        raise GroupComparisonError("alpha must be strictly between 0 and 1.")
    scope = _validate_analysis_scope(
        data,
        analysis_scope=analysis_scope,
        subject_col=subject_col,
        condition_col=condition_col,
        roi_col=roi_col,
    )

    grain_counts = (
        data.groupby(
            [subject_col, condition_col, roi_col],
            dropna=False,
            sort=False,
        )
        .size()
        .reset_index(name="row_count")
    )
    duplicates = grain_counts[grain_counts["row_count"] > 1]
    if not duplicates.empty:
        examples = [
            (
                f"({row[subject_col]!r}, {row[condition_col]!r}, "
                f"{row[roi_col]!r})"
            )
            for _, row in duplicates.head(10).iterrows()
        ]
        raise GroupComparisonError(
            "Duplicate participant x Condition x ROI cells: "
            + ", ".join(examples)
        )

    groups = _validate_group_assignments(
        data,
        subject_col=subject_col,
        group_col=group_col,
    )
    group_a, group_b = _resolve_group_pair(groups, group_pair)
    pair_keys = {group_a.casefold(), group_b.casefold()}
    working = data[
        data[group_col].astype(str).str.strip().str.casefold().isin(pair_keys)
    ].copy()
    working["_numeric_dv"] = pd.to_numeric(working[dv_col], errors="coerce")

    rows: list[dict[str, object]] = []
    grouped = working.groupby(
        [condition_col, roi_col],
        dropna=False,
        sort=True,
    )
    for (condition, roi), cell in grouped:
        group_values: Mapping[str, np.ndarray] = {
            group: cell.loc[
                cell[group_col].astype(str).str.strip().str.casefold()
                == group.casefold(),
                "_numeric_dv",
            ]
            .loc[lambda series: np.isfinite(series.to_numpy(dtype=float))]
            .to_numpy(dtype=float)
            for group in (group_a, group_b)
        }
        row: dict[str, object] = {
            "condition": condition,
            "roi": roi,
            "group_a": group_a,
            "group_b": group_b,
            "contrast": f"{group_a} - {group_b}",
            "alternative": "two_sided",
            "test_method": "Welch independent-samples t-test",
            "effect_size_method": (
                "Hedges g; pooled within-group SD; positive means group_a > group_b"
            ),
        }
        row.update(
            _welch_statistics(
                group_values[group_a],
                group_values[group_b],
                alpha=float(alpha),
            )
        )
        rows.append(row)

    raw = pd.DataFrame(rows)
    if raw.empty:
        raise GroupComparisonError("No Condition x ROI cells were available.")
    family = family_spec or FamilySpec(
        family_id="group_core_cells",
        family_label=(
            f"Complete-core Condition x ROI contrasts: {group_a} versus {group_b}"
        ),
        method=CorrectionMethod.coerce(correction),
        alpha=float(alpha),
    )
    contrasts = apply_family_correction(raw, family, p_col="p_raw")
    diagnostics = build_group_cell_diagnostics(
        working.rename(columns={"_numeric_dv": "_diagnostic_value"}),
        value_col="_diagnostic_value",
        group_cols=(group_col, condition_col, roi_col),
        alpha=float(alpha),
    )
    metadata = pd.DataFrame(
        [
            {
                "group_comparison_schema_version": GROUP_COMPARISON_SCHEMA_VERSION,
                "analysis_scope": scope,
                "group_a": group_a,
                "group_b": group_b,
                "sign_convention": (
                    "mean_difference and Hedges g are group_a minus group_b"
                ),
                "test_method": "two-sided Welch independent-samples t-test",
                "effect_size_method": "small-sample-corrected Hedges g",
                "family_id": family.family_id,
                "family_label": family.family_label,
                "adjustment_method": family.method.value,
                "alpha": family.alpha,
                "n_cells": len(contrasts),
                "n_estimable_cells": int(
                    contrasts["inference_status"].eq("estimated").sum()
                ),
            }
        ]
    )
    return GroupComparisonResult(
        contrasts=contrasts,
        diagnostics=diagnostics,
        metadata=metadata,
    )


__all__ = [
    "ALLOWED_ANALYSIS_SCOPES",
    "GROUP_COMPARISON_SCHEMA_VERSION",
    "GroupComparisonError",
    "GroupComparisonResult",
    "run_group_cell_comparisons",
]

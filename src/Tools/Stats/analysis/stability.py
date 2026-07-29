"""Participant-level leave-one-out stability diagnostics for FPVS cell estimates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats


STABILITY_SCHEMA_VERSION = 1
ALLOWED_ANALYSIS_SCOPES = frozenset({"complete_core", "available_case"})
UNKNOWN_GROUP_VALUES = frozenset(
    {"", "unknown", "unassigned", "none", "nan", "missing"}
)
OMISSION_UNIT = "participant; all Condition x ROI rows removed together"
MULTIPLICITY_NOTE = (
    "No multiplicity claim: raw rejection stability is a descriptive "
    "leave-one-out sensitivity diagnostic."
)


class StabilityAnalysisError(ValueError):
    """Raised when a participant-level stability analysis is not well defined."""


@dataclass(frozen=True)
class LeaveOneOutStabilityResult:
    """Export-ready leave-one-out detail, summary, and methods frames."""

    details: pd.DataFrame
    summaries: pd.DataFrame
    metadata: pd.DataFrame

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return independent workbook-ready frame copies."""

        return {
            "LOO Omission Details": self.details.copy(),
            "LOO Stability Summary": self.summaries.copy(),
            "LOO Stability Metadata": self.metadata.copy(),
        }


@dataclass(frozen=True)
class _PreparedData:
    frame: pd.DataFrame
    participants: tuple[object, ...]
    cells: tuple[tuple[object, object], ...]
    missing_cell_values: int
    analysis_scope: str


def _stable_key(value: object) -> tuple[str, str, str]:
    """Return a deterministic ordering key without changing exported labels."""

    return (
        type(value).__name__.casefold(),
        str(value).casefold(),
        str(value),
    )


def _stable_unique(values: pd.Series) -> tuple[object, ...]:
    unique = values.drop_duplicates().tolist()
    return tuple(sorted(unique, key=_stable_key))


def _coerce_scope(analysis_scope: str) -> str:
    scope = str(analysis_scope).strip().casefold()
    if scope not in ALLOWED_ANALYSIS_SCOPES:
        raise StabilityAnalysisError(
            "analysis_scope must be 'complete_core' or 'available_case'."
        )
    return scope


def _validate_alpha(alpha: float) -> float:
    try:
        numeric = float(alpha)
    except (TypeError, ValueError) as exc:
        raise StabilityAnalysisError(
            "alpha must be a number strictly between 0 and 1."
        ) from exc
    if not 0.0 < numeric < 1.0:
        raise StabilityAnalysisError(
            "alpha must be a number strictly between 0 and 1."
        )
    return numeric


def _prepare_data(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    analysis_scope: str,
) -> _PreparedData:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    required = (dv_col, subject_col, condition_col, roi_col)
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise StabilityAnalysisError(f"Missing required columns: {missing}")
    if data.empty:
        raise StabilityAnalysisError("No rows were available for stability analysis.")

    scope = _coerce_scope(analysis_scope)
    invalid_keys = []
    for column in (subject_col, condition_col, roi_col):
        invalid = data[column].map(
            lambda value: (
                value is None
                or bool(pd.isna(value))
                or isinstance(value, (bool, np.bool_))
                or (isinstance(value, str) and not value.strip())
            )
        )
        if bool(invalid.any()):
            invalid_keys.append(column)
    if invalid_keys:
        raise StabilityAnalysisError(
            "Participant, Condition, and ROI keys must be non-missing, "
            "non-blank identifiers; invalid values occurred in: "
            f"{invalid_keys}"
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
        raise StabilityAnalysisError(
            "Duplicate participant x Condition x ROI cells: "
            + ", ".join(examples)
        )

    working = data.copy()
    invalid_response_type = working[dv_col].map(
        lambda value: isinstance(
            value,
            (bool, np.bool_, complex, np.complexfloating),
        )
    )
    if bool(invalid_response_type.any()):
        raise StabilityAnalysisError(
            "Boolean and complex response values are invalid for stability analysis."
        )
    numeric = pd.to_numeric(working[dv_col], errors="coerce").to_numpy(
        dtype=float,
        na_value=np.nan,
    )
    numeric[~np.isfinite(numeric)] = np.nan
    working["_stability_value"] = numeric
    participants = _stable_unique(working[subject_col])
    observed_cells = working[[condition_col, roi_col]].drop_duplicates()
    cells = tuple(
        sorted(
            observed_cells.itertuples(index=False, name=None),
            key=lambda cell: (_stable_key(cell[0]), _stable_key(cell[1])),
        )
    )
    expected_count = len(participants) * len(cells)
    finite_count = int(np.isfinite(numeric).sum())
    missing_cell_values = expected_count - finite_count

    if scope == "complete_core" and missing_cell_values:
        incomplete: list[object] = []
        expected_cells = set(cells)
        for participant in participants:
            participant_rows = working[working[subject_col].eq(participant)]
            finite_rows = participant_rows[
                np.isfinite(
                    participant_rows["_stability_value"].to_numpy(dtype=float)
                )
            ]
            finite_cells = set(
                finite_rows[[condition_col, roi_col]].itertuples(
                    index=False,
                    name=None,
                )
            )
            if finite_cells != expected_cells:
                incomplete.append(participant)
        examples = ", ".join(map(str, incomplete[:10]))
        raise StabilityAnalysisError(
            "Complete-core leave-one-out analysis requires one finite value "
            "from every participant in every retained Condition x ROI cell. "
            f"Incomplete participants: {examples}"
        )

    return _PreparedData(
        frame=working,
        participants=participants,
        cells=cells,
        missing_cell_values=missing_cell_values,
        analysis_scope=scope,
    )


def _cell_rows(
    frame: pd.DataFrame,
    *,
    condition: object,
    roi: object,
    condition_col: str,
    roi_col: str,
) -> pd.DataFrame:
    return frame[
        frame[condition_col].eq(condition) & frame[roi_col].eq(roi)
    ]


def _finite_values(frame: pd.DataFrame) -> np.ndarray:
    values = frame["_stability_value"].to_numpy(dtype=float)
    return np.sort(values[np.isfinite(values)], kind="stable")


def _one_sample_statistics(
    values: np.ndarray,
    *,
    null_value: float,
    alpha: float,
) -> dict[str, object]:
    n = int(values.size)
    mean = float(np.mean(values)) if n else np.nan
    estimate = mean - null_value if n else np.nan
    result: dict[str, object] = {
        "n": n,
        "sample_mean": mean,
        "estimate": estimate,
        "standard_error": np.nan,
        "test_statistic": np.nan,
        "degrees_of_freedom": np.nan,
        "p_raw": np.nan,
        "reject_raw": pd.NA,
        "inference_status": "not_estimable",
        "status_code": "insufficient_n",
    }
    if n < 2:
        return result
    sample_sd = float(np.std(values, ddof=1))
    if not np.isfinite(sample_sd) or sample_sd <= 0.0:
        result["status_code"] = "zero_or_invalid_variance"
        return result
    standard_error = sample_sd / np.sqrt(n)
    t_statistic = estimate / standard_error
    degrees_of_freedom = float(n - 1)
    p_raw = float(
        2.0 * stats.t.sf(abs(t_statistic), df=degrees_of_freedom)
    )
    if not all(
        np.isfinite(value)
        for value in (standard_error, t_statistic, degrees_of_freedom, p_raw)
    ):
        result["status_code"] = "invalid_test_result"
        return result
    result.update(
        {
            "standard_error": float(standard_error),
            "test_statistic": float(t_statistic),
            "degrees_of_freedom": degrees_of_freedom,
            "p_raw": p_raw,
            "reject_raw": bool(p_raw <= alpha),
            "inference_status": "estimated",
            "status_code": "ok",
        }
    )
    return result


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
    estimate = mean_a - mean_b if n_a and n_b else np.nan
    result: dict[str, object] = {
        "n_group_a": n_a,
        "n_group_b": n_b,
        "mean_group_a": mean_a,
        "mean_group_b": mean_b,
        "estimate": estimate,
        "standard_error": np.nan,
        "test_statistic": np.nan,
        "degrees_of_freedom": np.nan,
        "p_raw": np.nan,
        "reject_raw": pd.NA,
        "inference_status": "not_estimable",
        "status_code": "insufficient_group_n",
    }
    if n_a < 2 or n_b < 2:
        return result
    variance_a = float(np.var(values_a, ddof=1))
    variance_b = float(np.var(values_b, ddof=1))
    term_a = variance_a / n_a
    term_b = variance_b / n_b
    standard_error_squared = term_a + term_b
    if (
        not np.isfinite(standard_error_squared)
        or standard_error_squared <= 0.0
    ):
        result["status_code"] = "zero_or_invalid_standard_error"
        return result
    denominator = (
        (term_a**2) / (n_a - 1)
        + (term_b**2) / (n_b - 1)
    )
    if not np.isfinite(denominator) or denominator <= 0.0:
        result["status_code"] = "invalid_welch_degrees_of_freedom"
        return result
    degrees_of_freedom = (standard_error_squared**2) / denominator
    standard_error = np.sqrt(standard_error_squared)
    test_statistic = estimate / standard_error
    p_raw = float(
        2.0 * stats.t.sf(abs(test_statistic), df=degrees_of_freedom)
    )
    if not all(
        np.isfinite(value)
        for value in (
            standard_error,
            test_statistic,
            degrees_of_freedom,
            p_raw,
        )
    ):
        result["status_code"] = "invalid_welch_result"
        return result
    result.update(
        {
            "standard_error": float(standard_error),
            "test_statistic": float(test_statistic),
            "degrees_of_freedom": float(degrees_of_freedom),
            "p_raw": p_raw,
            "reject_raw": bool(p_raw <= alpha),
            "inference_status": "estimated",
            "status_code": "ok",
        }
    )
    return result


def _sign(value: float) -> int:
    if value > 0.0:
        return 1
    if value < 0.0:
        return -1
    return 0


def _add_shift_ranks(details: pd.DataFrame) -> pd.DataFrame:
    out = details.copy()
    ranks = pd.Series(pd.NA, index=out.index, dtype="Int64")
    for _, indices in out.groupby(
        ["condition", "roi"],
        dropna=False,
        sort=False,
    ).groups.items():
        cell_delta = pd.to_numeric(
            out.loc[indices, "abs_delta_from_full"],
            errors="coerce",
        )
        finite = np.isfinite(cell_delta.to_numpy(dtype=float))
        if bool(finite.any()):
            finite_index = cell_delta.index[finite]
            cell_ranks = cell_delta.loc[finite_index].rank(
                method="min",
                ascending=False,
            )
            ranks.loc[finite_index] = cell_ranks.astype("Int64")
    out["shift_rank"] = ranks
    out["largest_shift_flag"] = ranks.eq(1).fillna(False).astype(bool)
    return out


def _stability_summary_rows(
    *,
    details: pd.DataFrame,
    full_by_cell: dict[tuple[object, object], dict[str, object]],
    prepared: _PreparedData,
    alpha: float,
    analysis_kind: str,
    estimand: str,
    common_fields: dict[str, object],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for condition, roi in prepared.cells:
        cell_details = details[
            details["condition"].eq(condition) & details["roi"].eq(roi)
        ]
        full = full_by_cell[(condition, roi)]
        estimates = pd.to_numeric(
            cell_details["estimate_after_omission"],
            errors="coerce",
        ).to_numpy(dtype=float)
        finite_estimates = estimates[np.isfinite(estimates)]
        full_estimate = float(full["estimate"])
        all_estimates_finite = len(finite_estimates) == len(estimates)
        if np.isfinite(full_estimate) and all_estimates_finite:
            sign_stable: object = bool(
                all(_sign(value) == _sign(full_estimate) for value in estimates)
            )
        else:
            sign_stable = pd.NA

        full_p = float(full["p_raw"])
        omitted_p = pd.to_numeric(
            cell_details["p_raw_after_omission"],
            errors="coerce",
        ).to_numpy(dtype=float)
        p_stability_estimable = bool(
            np.isfinite(full_p) and np.isfinite(omitted_p).all()
        )
        if p_stability_estimable:
            full_reject = bool(full_p <= alpha)
            reject_stable: object = bool(
                np.all((omitted_p <= alpha) == full_reject)
            )
            reject_status = "estimated_raw_sensitivity"
        else:
            full_reject = pd.NA
            reject_stable = pd.NA
            reject_status = "not_estimable"

        full_is_estimated = full["inference_status"] == "estimated"
        omission_estimated = cell_details["inference_status"].eq("estimated")
        if not full_is_estimated:
            stability_status = "not_estimable"
            status_code = f"full_{full['status_code']}"
        elif bool(omission_estimated.all()):
            stability_status = "estimated"
            status_code = "ok"
        else:
            stability_status = "partially_estimable"
            status_code = "some_omission_tests_not_estimable"

        flagged = cell_details.loc[
            cell_details["largest_shift_flag"],
            "omitted_participant",
        ]
        participant_labels = sorted(
            {str(value) for value in flagged.tolist()},
            key=str.casefold,
        )
        missing_in_cell = int(
            len(prepared.participants)
            - _cell_rows(
                prepared.frame,
                condition=condition,
                roi=roi,
                condition_col="_stability_condition",
                roi_col="_stability_roi",
            )["_stability_value"]
            .map(np.isfinite)
            .sum()
        )
        row: dict[str, object] = {
            "analysis_kind": analysis_kind,
            "analysis_scope": prepared.analysis_scope,
            "condition": condition,
            "roi": roi,
            "estimand": estimand,
            "alpha_raw_sensitivity": alpha,
            "full_estimate": full_estimate,
            "full_test_statistic": full["test_statistic"],
            "full_degrees_of_freedom": full["degrees_of_freedom"],
            "full_p_raw": full["p_raw"],
            "full_reject_raw": full_reject,
            "full_inference_status": full["inference_status"],
            "full_status_code": full["status_code"],
            "min_estimate_after_omission": (
                float(np.min(finite_estimates))
                if finite_estimates.size
                else np.nan
            ),
            "max_estimate_after_omission": (
                float(np.max(finite_estimates))
                if finite_estimates.size
                else np.nan
            ),
            "sign_stable": sign_stable,
            "reject_stable_raw": reject_stable,
            "reject_stability_status": reject_status,
            "n_omissions": len(cell_details),
            "n_estimable_omission_tests": int(omission_estimated.sum()),
            "max_abs_delta": pd.to_numeric(
                cell_details["abs_delta_from_full"],
                errors="coerce",
            ).max(),
            "participant_with_largest_estimate_shift": "; ".join(
                participant_labels
            ),
            "missing_cell_values": missing_in_cell,
            "missingness_status": (
                "complete"
                if missing_in_cell == 0
                else "available_case_missing"
            ),
            "stability_status": stability_status,
            "status_code": status_code,
            "formal_hypothesis_correction": False,
            "multiplicity_note": MULTIPLICITY_NOTE,
        }
        row.update(common_fields)
        for key in (
            "n",
            "sample_mean",
            "n_group_a",
            "n_group_b",
            "mean_group_a",
            "mean_group_b",
        ):
            if key in full:
                row[f"full_{key}"] = full[key]
        rows.append(row)
    return pd.DataFrame(rows)


def _metadata_frame(
    *,
    prepared: _PreparedData,
    analysis_kind: str,
    estimand: str,
    test_method: str,
    alpha: float,
    extra: dict[str, object],
) -> pd.DataFrame:
    row: dict[str, object] = {
        "stability_schema_version": STABILITY_SCHEMA_VERSION,
        "analysis_kind": analysis_kind,
        "analysis_scope": prepared.analysis_scope,
        "estimand": estimand,
        "test_method": test_method,
        "alpha_raw_sensitivity": alpha,
        "n_participants": len(prepared.participants),
        "n_cells": len(prepared.cells),
        "n_missing_cell_values": prepared.missing_cell_values,
        "omission_unit": OMISSION_UNIT,
        "delta_definition": "estimate after omission minus full-sample estimate",
        "largest_shift_definition": (
            "participant whose omission caused the largest absolute estimate "
            "shift within a cell; ties share rank 1. This is descriptive and "
            "does not by itself establish problematic influence"
        ),
        "formal_hypothesis_correction": False,
        "multiplicity_note": MULTIPLICITY_NOTE,
    }
    row.update(extra)
    return pd.DataFrame([row])


def run_one_sample_leave_one_out_stability(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    null_value: float = 0.0,
    alpha: float = 0.05,
    analysis_scope: str = "complete_core",
) -> LeaveOneOutStabilityResult:
    """Assess cell mean stability after omitting each participant as one unit."""

    numeric_alpha = _validate_alpha(alpha)
    try:
        numeric_null = float(null_value)
    except (TypeError, ValueError) as exc:
        raise StabilityAnalysisError("null_value must be finite.") from exc
    if not np.isfinite(numeric_null):
        raise StabilityAnalysisError("null_value must be finite.")
    prepared = _prepare_data(
        data,
        dv_col=dv_col,
        subject_col=subject_col,
        condition_col=condition_col,
        roi_col=roi_col,
        analysis_scope=analysis_scope,
    )
    prepared.frame["_stability_condition"] = prepared.frame[condition_col]
    prepared.frame["_stability_roi"] = prepared.frame[roi_col]
    full_by_cell: dict[tuple[object, object], dict[str, object]] = {}
    for condition, roi in prepared.cells:
        full_cell = _cell_rows(
            prepared.frame,
            condition=condition,
            roi=roi,
            condition_col=condition_col,
            roi_col=roi_col,
        )
        full_by_cell[(condition, roi)] = _one_sample_statistics(
            _finite_values(full_cell),
            null_value=numeric_null,
            alpha=numeric_alpha,
        )

    rows: list[dict[str, object]] = []
    for omitted in prepared.participants:
        remaining = prepared.frame[~prepared.frame[subject_col].eq(omitted)]
        omitted_rows = prepared.frame[prepared.frame[subject_col].eq(omitted)]
        for condition, roi in prepared.cells:
            remaining_cell = _cell_rows(
                remaining,
                condition=condition,
                roi=roi,
                condition_col=condition_col,
                roi_col=roi_col,
            )
            omitted_cell = _cell_rows(
                omitted_rows,
                condition=condition,
                roi=roi,
                condition_col=condition_col,
                roi_col=roi_col,
            )
            omitted_stats = _one_sample_statistics(
                _finite_values(remaining_cell),
                null_value=numeric_null,
                alpha=numeric_alpha,
            )
            full = full_by_cell[(condition, roi)]
            delta = float(omitted_stats["estimate"]) - float(full["estimate"])
            rows.append(
                {
                    "analysis_kind": "one_sample_mean",
                    "analysis_scope": prepared.analysis_scope,
                    "condition": condition,
                    "roi": roi,
                    "omitted_participant": omitted,
                    "omitted_group": pd.NA,
                    "omitted_participant_had_finite_value": bool(
                        np.isfinite(
                            omitted_cell["_stability_value"].to_numpy(
                                dtype=float
                            )
                        ).any()
                    ),
                    "estimand": f"cell mean minus {numeric_null:g}",
                    "null_value": numeric_null,
                    "full_estimate": full["estimate"],
                    "estimate_after_omission": omitted_stats["estimate"],
                    "delta_from_full": delta,
                    "abs_delta_from_full": abs(delta),
                    "n_after_omission": omitted_stats["n"],
                    "test_statistic_after_omission": omitted_stats[
                        "test_statistic"
                    ],
                    "degrees_of_freedom_after_omission": omitted_stats[
                        "degrees_of_freedom"
                    ],
                    "p_raw_after_omission": omitted_stats["p_raw"],
                    "reject_raw_after_omission": omitted_stats["reject_raw"],
                    "inference_status": omitted_stats["inference_status"],
                    "status_code": omitted_stats["status_code"],
                    "omission_unit": OMISSION_UNIT,
                    "formal_hypothesis_correction": False,
                }
            )
    details = _add_shift_ranks(pd.DataFrame(rows))
    estimand = f"cell mean minus {numeric_null:g}"
    summaries = _stability_summary_rows(
        details=details,
        full_by_cell=full_by_cell,
        prepared=prepared,
        alpha=numeric_alpha,
        analysis_kind="one_sample_mean",
        estimand=estimand,
        common_fields={"null_value": numeric_null},
    )
    metadata = _metadata_frame(
        prepared=prepared,
        analysis_kind="one_sample_mean",
        estimand=estimand,
        test_method="two-sided one-sample t-test",
        alpha=numeric_alpha,
        extra={"null_value": numeric_null},
    )
    return LeaveOneOutStabilityResult(details, summaries, metadata)


def _validate_groups(
    data: pd.DataFrame,
    *,
    subject_col: str,
    group_col: str,
    group_pair: Sequence[object] | None,
) -> tuple[pd.DataFrame, str, str]:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    missing_columns = [
        column
        for column in (subject_col, group_col)
        if column not in data.columns
    ]
    if missing_columns:
        raise StabilityAnalysisError(
            f"Missing required columns: {missing_columns}"
        )
    if bool(data[group_col].isna().any()):
        raise StabilityAnalysisError(
            "Canonical group assignment is missing or unknown."
        )
    normalized = data.copy()
    normalized["_stability_group"] = data[group_col].astype(str).str.strip()
    unknown = normalized["_stability_group"].str.casefold().isin(
        UNKNOWN_GROUP_VALUES
    )
    if bool(unknown.any()):
        raise StabilityAnalysisError(
            "Canonical group assignment is missing or unknown."
        )
    counts = normalized.groupby(subject_col, dropna=False)[
        "_stability_group"
    ].nunique()
    inconsistent = counts[counts > 1]
    if not inconsistent.empty:
        raise StabilityAnalysisError(
            "Each participant must have one canonical group ID; inconsistent "
            "assignments were found for: "
            + ", ".join(map(str, inconsistent.index.tolist()))
        )
    groups = _stable_unique(normalized["_stability_group"])
    if group_pair is None:
        if len(groups) != 2:
            raise StabilityAnalysisError(
                "Exactly two canonical groups are required unless an explicit "
                "two-group comparison pair is selected."
            )
        group_a, group_b = str(groups[0]), str(groups[1])
    else:
        if len(group_pair) != 2:
            raise StabilityAnalysisError(
                "group_pair must contain exactly two group IDs."
            )
        requested_a, requested_b = (str(value).strip() for value in group_pair)
        if (
            not requested_a
            or not requested_b
            or requested_a.casefold() == requested_b.casefold()
        ):
            raise StabilityAnalysisError(
                "group_pair must contain two distinct group IDs."
            )
        by_key = {str(group).casefold(): str(group) for group in groups}
        missing = [
            value
            for value in (requested_a, requested_b)
            if value.casefold() not in by_key
        ]
        if missing:
            raise StabilityAnalysisError(
                "Selected group IDs are not present: " + ", ".join(missing)
            )
        group_a = by_key[requested_a.casefold()]
        group_b = by_key[requested_b.casefold()]
    pair_keys = {group_a.casefold(), group_b.casefold()}
    selected = normalized[
        normalized["_stability_group"].str.casefold().isin(pair_keys)
    ].copy()
    return selected, group_a, group_b


def run_two_group_leave_one_out_stability(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    group_col: str,
    condition_col: str,
    roi_col: str,
    group_pair: Sequence[object] | None = None,
    alpha: float = 0.05,
    analysis_scope: str = "complete_core",
) -> LeaveOneOutStabilityResult:
    """Assess Welch cell-contrast stability after participant-level omissions."""

    numeric_alpha = _validate_alpha(alpha)
    selected, group_a, group_b = _validate_groups(
        data,
        subject_col=subject_col,
        group_col=group_col,
        group_pair=group_pair,
    )
    prepared = _prepare_data(
        selected,
        dv_col=dv_col,
        subject_col=subject_col,
        condition_col=condition_col,
        roi_col=roi_col,
        analysis_scope=analysis_scope,
    )
    prepared.frame["_stability_condition"] = prepared.frame[condition_col]
    prepared.frame["_stability_roi"] = prepared.frame[roi_col]
    participant_groups = (
        prepared.frame[
            [subject_col, "_stability_group"]
        ]
        .drop_duplicates()
        .set_index(subject_col)["_stability_group"]
        .to_dict()
    )

    def cell_statistics(frame: pd.DataFrame, condition: object, roi: object):
        cell = _cell_rows(
            frame,
            condition=condition,
            roi=roi,
            condition_col=condition_col,
            roi_col=roi_col,
        )
        values_a = _finite_values(
            cell[
                cell["_stability_group"].str.casefold().eq(
                    group_a.casefold()
                )
            ]
        )
        values_b = _finite_values(
            cell[
                cell["_stability_group"].str.casefold().eq(
                    group_b.casefold()
                )
            ]
        )
        return _welch_statistics(
            values_a,
            values_b,
            alpha=numeric_alpha,
        )

    full_by_cell = {
        (condition, roi): cell_statistics(
            prepared.frame,
            condition,
            roi,
        )
        for condition, roi in prepared.cells
    }
    rows: list[dict[str, object]] = []
    for omitted in prepared.participants:
        remaining = prepared.frame[~prepared.frame[subject_col].eq(omitted)]
        omitted_rows = prepared.frame[prepared.frame[subject_col].eq(omitted)]
        for condition, roi in prepared.cells:
            omitted_stats = cell_statistics(remaining, condition, roi)
            omitted_cell = _cell_rows(
                omitted_rows,
                condition=condition,
                roi=roi,
                condition_col=condition_col,
                roi_col=roi_col,
            )
            full = full_by_cell[(condition, roi)]
            delta = float(omitted_stats["estimate"]) - float(full["estimate"])
            rows.append(
                {
                    "analysis_kind": "two_group_welch",
                    "analysis_scope": prepared.analysis_scope,
                    "condition": condition,
                    "roi": roi,
                    "group_a": group_a,
                    "group_b": group_b,
                    "contrast": f"{group_a} - {group_b}",
                    "omitted_participant": omitted,
                    "omitted_group": participant_groups[omitted],
                    "omitted_participant_had_finite_value": bool(
                        np.isfinite(
                            omitted_cell["_stability_value"].to_numpy(
                                dtype=float
                            )
                        ).any()
                    ),
                    "estimand": f"cell mean difference: {group_a} minus {group_b}",
                    "full_estimate": full["estimate"],
                    "estimate_after_omission": omitted_stats["estimate"],
                    "delta_from_full": delta,
                    "abs_delta_from_full": abs(delta),
                    "n_group_a_after_omission": omitted_stats["n_group_a"],
                    "n_group_b_after_omission": omitted_stats["n_group_b"],
                    "test_statistic_after_omission": omitted_stats[
                        "test_statistic"
                    ],
                    "degrees_of_freedom_after_omission": omitted_stats[
                        "degrees_of_freedom"
                    ],
                    "p_raw_after_omission": omitted_stats["p_raw"],
                    "reject_raw_after_omission": omitted_stats["reject_raw"],
                    "inference_status": omitted_stats["inference_status"],
                    "status_code": omitted_stats["status_code"],
                    "omission_unit": OMISSION_UNIT,
                    "formal_hypothesis_correction": False,
                }
            )
    details = _add_shift_ranks(pd.DataFrame(rows))
    estimand = f"cell mean difference: {group_a} minus {group_b}"
    common = {
        "group_a": group_a,
        "group_b": group_b,
        "contrast": f"{group_a} - {group_b}",
    }
    summaries = _stability_summary_rows(
        details=details,
        full_by_cell=full_by_cell,
        prepared=prepared,
        alpha=numeric_alpha,
        analysis_kind="two_group_welch",
        estimand=estimand,
        common_fields=common,
    )
    metadata = _metadata_frame(
        prepared=prepared,
        analysis_kind="two_group_welch",
        estimand=estimand,
        test_method="two-sided Welch independent-samples t-test",
        alpha=numeric_alpha,
        extra={
            **common,
            "sign_convention": "positive means group_a exceeds group_b",
        },
    )
    return LeaveOneOutStabilityResult(details, summaries, metadata)


__all__ = [
    "ALLOWED_ANALYSIS_SCOPES",
    "LeaveOneOutStabilityResult",
    "MULTIPLICITY_NOTE",
    "STABILITY_SCHEMA_VERSION",
    "StabilityAnalysisError",
    "run_one_sample_leave_one_out_stability",
    "run_two_group_leave_one_out_stability",
]

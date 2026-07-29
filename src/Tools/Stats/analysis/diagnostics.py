"""GUI-neutral statistical diagnostic primitives.

Diagnostics in this module describe data and model conditions only.  In
particular, a normality diagnostic never selects, replaces, or suppresses an
inferential test.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests


DIAGNOSTIC_SCHEMA_VERSION = 1
MIN_SHAPIRO_N = 3


class DiagnosticStatus(str, Enum):
    """Machine-readable status for one diagnostic check."""

    ESTIMABLE = "estimable"
    DIAGNOSTIC = "diagnostic"
    NOT_ESTIMABLE = "not_estimable"


@dataclass(frozen=True, slots=True)
class FiniteValueSummary:
    """Finite numeric values plus explicit coercion counts."""

    values: tuple[float, ...]
    n_total: int
    n_finite: int
    n_missing: int
    n_nonfinite: int
    n_invalid: int

    def as_array(self) -> np.ndarray:
        """Return a new float array suitable for numerical routines."""

        return np.asarray(self.values, dtype=float)


@dataclass(frozen=True, slots=True)
class DiagnosticRecord:
    """One serializable diagnostic result.

    ``context`` contains identifiers such as group, condition, ROI, or model.
    It is flattened into columns by :func:`diagnostics_to_frame`.
    """

    check: str
    status: DiagnosticStatus
    code: str
    context: Mapping[str, object] = field(default_factory=dict)
    n_total: int | None = None
    n_finite: int | None = None
    n_missing: int | None = None
    n_nonfinite: int | None = None
    n_invalid: int | None = None
    statistic_name: str | None = None
    statistic: float | None = None
    p_raw: float | None = None
    p_adjusted: float | None = None
    reject_raw: bool | None = None
    reject_adjusted: bool | None = None
    alpha: float | None = None
    adjustment_method: str | None = None
    adjustment_family: str | None = None
    estimate: float | None = None
    ci_low: float | None = None
    ci_high: float | None = None

    def to_row(self) -> dict[str, object]:
        """Return a JSON/Excel-friendly flat row."""

        row: dict[str, object] = {
            "check": self.check,
            "status": self.status.value,
            "code": self.code,
            "n_total": self.n_total,
            "n_finite": self.n_finite,
            "n_missing": self.n_missing,
            "n_nonfinite": self.n_nonfinite,
            "n_invalid": self.n_invalid,
            "statistic_name": self.statistic_name,
            "statistic": self.statistic,
            "p_raw": self.p_raw,
            "p_adjusted": self.p_adjusted,
            "reject_raw": self.reject_raw,
            "reject_adjusted": self.reject_adjusted,
            "alpha": self.alpha,
            "adjustment_method": self.adjustment_method,
            "adjustment_family": self.adjustment_family,
            "estimate": self.estimate,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
        }
        for key, value in self.context.items():
            normalized_key = str(key)
            if normalized_key in row:
                normalized_key = f"context_{normalized_key}"
            row[normalized_key] = _serializable_scalar(value)
        return row


_CORE_FRAME_COLUMNS = (
    "check",
    "status",
    "code",
    "n_total",
    "n_finite",
    "n_missing",
    "n_nonfinite",
    "n_invalid",
    "statistic_name",
    "statistic",
    "p_raw",
    "p_adjusted",
    "reject_raw",
    "reject_adjusted",
    "alpha",
    "adjustment_method",
    "adjustment_family",
    "estimate",
    "ci_low",
    "ci_high",
)


def _iter_values(values: object) -> list[object]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        return [values]
    if np.isscalar(values):
        return [values]
    try:
        return list(values)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return [values]


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, (bool, np.bool_)) else False


def coerce_finite_values(values: object) -> FiniteValueSummary:
    """Safely coerce a scalar or one-dimensional iterable to finite floats.

    Missing, infinite, and invalid values are counted separately rather than
    silently becoming valid observations.  Boolean values are treated as
    invalid to prevent accidental conversion to 0/1.
    """

    raw_values = _iter_values(values)
    finite: list[float] = []
    n_missing = 0
    n_nonfinite = 0
    n_invalid = 0

    for raw in raw_values:
        if _is_missing(raw):
            n_missing += 1
            continue
        if isinstance(raw, (bool, np.bool_, complex, np.complexfloating)):
            n_invalid += 1
            continue
        try:
            numeric = float(raw)
        except (TypeError, ValueError, OverflowError):
            n_invalid += 1
            continue
        if not np.isfinite(numeric):
            n_nonfinite += 1
            continue
        finite.append(numeric)

    return FiniteValueSummary(
        values=tuple(finite),
        n_total=len(raw_values),
        n_finite=len(finite),
        n_missing=n_missing,
        n_nonfinite=n_nonfinite,
        n_invalid=n_invalid,
    )


def _record_counts(summary: FiniteValueSummary) -> dict[str, int]:
    return {
        "n_total": summary.n_total,
        "n_finite": summary.n_finite,
        "n_missing": summary.n_missing,
        "n_nonfinite": summary.n_nonfinite,
        "n_invalid": summary.n_invalid,
    }


def build_data_integrity_diagnostic(
    values: object,
    *,
    context: Mapping[str, object] | None = None,
) -> DiagnosticRecord:
    """Describe finite-value coercion without making an inferential decision."""

    summary = coerce_finite_values(values)
    counts = _record_counts(summary)
    if summary.n_total == 0:
        status = DiagnosticStatus.NOT_ESTIMABLE
        code = "empty_input"
    elif summary.n_finite == 0:
        status = DiagnosticStatus.NOT_ESTIMABLE
        code = "no_finite_values"
    elif summary.n_nonfinite:
        status = DiagnosticStatus.DIAGNOSTIC
        code = "nonfinite_values_excluded"
    elif summary.n_invalid:
        status = DiagnosticStatus.DIAGNOSTIC
        code = "invalid_values_excluded"
    elif summary.n_missing:
        status = DiagnosticStatus.DIAGNOSTIC
        code = "missing_values_excluded"
    else:
        status = DiagnosticStatus.ESTIMABLE
        code = "all_values_finite"
    return DiagnosticRecord(
        check="data_integrity",
        status=status,
        code=code,
        context=dict(context or {}),
        **counts,
    )


def build_sample_size_diagnostic(
    values: object,
    *,
    minimum_n: int = MIN_SHAPIRO_N,
    context: Mapping[str, object] | None = None,
) -> DiagnosticRecord:
    """Return an explicit sample-size prerequisite row."""

    if minimum_n < 1:
        raise ValueError("minimum_n must be at least 1")
    summary = coerce_finite_values(values)
    status = (
        DiagnosticStatus.ESTIMABLE
        if summary.n_finite >= minimum_n
        else DiagnosticStatus.NOT_ESTIMABLE
    )
    return DiagnosticRecord(
        check="sample_size",
        status=status,
        code="sufficient_n" if status is DiagnosticStatus.ESTIMABLE else "tiny_n",
        context=dict(context or {}),
        **_record_counts(summary),
    )


def build_variance_diagnostic(
    values: object,
    *,
    zero_tolerance: float = 0.0,
    context: Mapping[str, object] | None = None,
) -> DiagnosticRecord:
    """Return a variance prerequisite row with zero variance made explicit."""

    if zero_tolerance < 0 or not np.isfinite(zero_tolerance):
        raise ValueError("zero_tolerance must be a finite non-negative number")
    summary = coerce_finite_values(values)
    variance: float | None = None
    if summary.n_finite < 2:
        status = DiagnosticStatus.NOT_ESTIMABLE
        code = "tiny_n"
    else:
        variance = float(np.var(summary.as_array(), ddof=1))
        if not np.isfinite(variance):
            status = DiagnosticStatus.NOT_ESTIMABLE
            code = "invalid_variance"
        elif variance <= zero_tolerance:
            status = DiagnosticStatus.NOT_ESTIMABLE
            code = "zero_variance"
        else:
            status = DiagnosticStatus.ESTIMABLE
            code = "positive_variance"
    return DiagnosticRecord(
        check="variance",
        status=status,
        code=code,
        context=dict(context or {}),
        statistic_name="sample_variance",
        statistic=variance,
        **_record_counts(summary),
    )


def build_shapiro_diagnostic(
    values: object,
    *,
    alpha: float = 0.05,
    minimum_n: int = MIN_SHAPIRO_N,
    zero_tolerance: float = 0.0,
    context: Mapping[str, object] | None = None,
) -> DiagnosticRecord:
    """Compute a report-only Shapiro diagnostic when its prerequisites hold."""

    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")
    if minimum_n < MIN_SHAPIRO_N:
        raise ValueError(f"minimum_n must be at least {MIN_SHAPIRO_N} for Shapiro")
    if zero_tolerance < 0 or not np.isfinite(zero_tolerance):
        raise ValueError("zero_tolerance must be a finite non-negative number")

    summary = coerce_finite_values(values)
    counts = _record_counts(summary)
    if summary.n_finite < minimum_n:
        return DiagnosticRecord(
            check="normality_shapiro",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="tiny_n",
            context=dict(context or {}),
            alpha=alpha,
            **counts,
        )

    finite = summary.as_array()
    variance = float(np.var(finite, ddof=1))
    if not np.isfinite(variance) or variance <= zero_tolerance:
        return DiagnosticRecord(
            check="normality_shapiro",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="zero_variance" if np.isfinite(variance) else "invalid_variance",
            context=dict(context or {}),
            alpha=alpha,
            **counts,
        )

    try:
        result = stats.shapiro(finite)
        statistic = float(result.statistic)
        p_raw = float(result.pvalue)
    except Exception:  # noqa: BLE001 - diagnostic failure becomes a row
        return DiagnosticRecord(
            check="normality_shapiro",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="shapiro_failed",
            context=dict(context or {}),
            alpha=alpha,
            **counts,
        )

    if not np.isfinite(statistic) or not np.isfinite(p_raw):
        return DiagnosticRecord(
            check="normality_shapiro",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="invalid_shapiro_result",
            context=dict(context or {}),
            alpha=alpha,
            **counts,
        )

    rejected = bool(p_raw < alpha)
    return DiagnosticRecord(
        check="normality_shapiro",
        status=DiagnosticStatus.DIAGNOSTIC if rejected else DiagnosticStatus.ESTIMABLE,
        code="normality_flag_raw" if rejected else "computed",
        context=dict(context or {}),
        statistic_name="W",
        statistic=statistic,
        p_raw=p_raw,
        reject_raw=rejected,
        alpha=alpha,
        **counts,
    )


def build_value_diagnostics(
    values: object,
    *,
    alpha: float = 0.05,
    minimum_n: int = MIN_SHAPIRO_N,
    zero_tolerance: float = 0.0,
    context: Mapping[str, object] | None = None,
) -> tuple[DiagnosticRecord, ...]:
    """Build data-integrity, sample-size, variance, and Shapiro rows."""

    return (
        build_data_integrity_diagnostic(values, context=context),
        build_sample_size_diagnostic(values, minimum_n=minimum_n, context=context),
        build_variance_diagnostic(values, zero_tolerance=zero_tolerance, context=context),
        build_shapiro_diagnostic(
            values,
            alpha=alpha,
            minimum_n=minimum_n,
            zero_tolerance=zero_tolerance,
            context=context,
        ),
    )


def adjust_shapiro_family(
    records: Sequence[DiagnosticRecord],
    *,
    method: str,
    family: str,
    alpha: float = 0.05,
) -> tuple[DiagnosticRecord, ...]:
    """Attach family-adjusted Shapiro fields without selecting another test."""

    if not method or not str(method).strip():
        raise ValueError("method must be a non-empty statsmodels correction name")
    if not family or not str(family).strip():
        raise ValueError("family must be a non-empty identifier")
    if not 0 < alpha < 1:
        raise ValueError("alpha must be between 0 and 1")

    shapiro_indices = [idx for idx, row in enumerate(records) if row.check == "normality_shapiro"]
    valid_indices = [
        idx
        for idx in shapiro_indices
        if records[idx].p_raw is not None and np.isfinite(float(records[idx].p_raw))
    ]
    adjusted_by_index: dict[int, tuple[bool, float]] = {}
    if valid_indices:
        p_values = [float(records[idx].p_raw) for idx in valid_indices]
        reject, adjusted, _, _ = multipletests(p_values, alpha=alpha, method=method)
        adjusted_by_index = {
            idx: (bool(rejected), float(p_adjusted))
            for idx, rejected, p_adjusted in zip(valid_indices, reject, adjusted)
        }

    output: list[DiagnosticRecord] = []
    for idx, row in enumerate(records):
        if idx not in shapiro_indices:
            output.append(row)
            continue
        update = adjusted_by_index.get(idx)
        if update is None:
            output.append(
                replace(
                    row,
                    adjustment_method=str(method),
                    adjustment_family=str(family),
                    alpha=alpha,
                )
            )
            continue
        rejected, p_adjusted = update
        output.append(
            replace(
                row,
                status=DiagnosticStatus.DIAGNOSTIC if rejected else DiagnosticStatus.ESTIMABLE,
                code="normality_flag_adjusted" if rejected else "computed",
                p_adjusted=p_adjusted,
                reject_adjusted=rejected,
                adjustment_method=str(method),
                adjustment_family=str(family),
                alpha=alpha,
            )
        )
    return tuple(output)


def build_confidence_interval_diagnostic(
    *,
    ci_low: object,
    ci_high: object,
    estimate: object | None = None,
    context: Mapping[str, object] | None = None,
) -> DiagnosticRecord:
    """Validate a confidence interval and return an explicit diagnostic row."""

    low_summary = coerce_finite_values([ci_low])
    high_summary = coerce_finite_values([ci_high])
    estimate_summary = coerce_finite_values([estimate]) if estimate is not None else None
    low = low_summary.values[0] if low_summary.n_finite == 1 else None
    high = high_summary.values[0] if high_summary.n_finite == 1 else None
    estimate_value = (
        estimate_summary.values[0]
        if estimate_summary is not None and estimate_summary.n_finite == 1
        else None
    )

    if low is None or high is None:
        status = DiagnosticStatus.NOT_ESTIMABLE
        code = "invalid_ci_nonfinite"
    elif low > high:
        status = DiagnosticStatus.NOT_ESTIMABLE
        code = "invalid_ci_order"
    elif estimate is not None and estimate_value is None:
        status = DiagnosticStatus.NOT_ESTIMABLE
        code = "invalid_estimate"
    elif estimate_value is not None and not low <= estimate_value <= high:
        status = DiagnosticStatus.DIAGNOSTIC
        code = "estimate_outside_ci"
    else:
        status = DiagnosticStatus.ESTIMABLE
        code = "valid_ci"

    return DiagnosticRecord(
        check="confidence_interval",
        status=status,
        code=code,
        context=dict(context or {}),
        estimate=estimate_value,
        ci_low=low,
        ci_high=high,
    )


def _coerce_optional_bool(value: object) -> tuple[bool | None, bool]:
    if value is None:
        return None, True
    if isinstance(value, (bool, np.bool_)):
        return bool(value), True
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "1"}:
            return True, True
        if normalized in {"false", "no", "0"}:
            return False, True
    return None, False


def build_model_fit_diagnostics(
    *,
    model_name: str,
    converged: object,
    singular: object | None = None,
    fit_error: object | None = None,
    context: Mapping[str, object] | None = None,
) -> tuple[DiagnosticRecord, ...]:
    """Build explicit convergence/singularity rows for a fitted model."""

    model_context = dict(context or {})
    model_context["model"] = str(model_name)
    fit_error_present = fit_error is not None and (
        not isinstance(fit_error, str) or bool(fit_error.strip())
    )
    if fit_error_present:
        model_context["fit_error"] = _serializable_scalar(fit_error)
        return (
            DiagnosticRecord(
                check="model_fit",
                status=DiagnosticStatus.NOT_ESTIMABLE,
                code="model_fit_failed",
                context=model_context,
            ),
        )

    converged_value, converged_valid = _coerce_optional_bool(converged)
    if not converged_valid:
        convergence = DiagnosticRecord(
            check="model_convergence",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="invalid_convergence_status",
            context=model_context,
        )
    elif converged_value is None:
        convergence = DiagnosticRecord(
            check="model_convergence",
            status=DiagnosticStatus.DIAGNOSTIC,
            code="convergence_unknown",
            context=model_context,
        )
    elif converged_value:
        convergence = DiagnosticRecord(
            check="model_convergence",
            status=DiagnosticStatus.ESTIMABLE,
            code="converged",
            context=model_context,
        )
    else:
        convergence = DiagnosticRecord(
            check="model_convergence",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="model_not_converged",
            context=model_context,
        )

    output = [convergence]
    if singular is not None:
        singular_value, singular_valid = _coerce_optional_bool(singular)
        if not singular_valid or singular_value is None:
            output.append(
                DiagnosticRecord(
                    check="model_singularity",
                    status=DiagnosticStatus.DIAGNOSTIC,
                    code="singularity_unknown",
                    context=model_context,
                )
            )
        elif singular_value:
            output.append(
                DiagnosticRecord(
                    check="model_singularity",
                    status=DiagnosticStatus.DIAGNOSTIC,
                    code="singular_fit",
                    context=model_context,
                )
            )
        else:
            output.append(
                DiagnosticRecord(
                    check="model_singularity",
                    status=DiagnosticStatus.ESTIMABLE,
                    code="non_singular_fit",
                    context=model_context,
                )
            )
    return tuple(output)


def diagnostics_to_frame(
    records: Iterable[DiagnosticRecord],
    *,
    metadata: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Return a flat, serializable diagnostic table."""

    rows = [record.to_row() for record in records]
    context_columns = sorted(
        {
            key
            for row in rows
            for key in row
            if key not in _CORE_FRAME_COLUMNS
        }
    )
    columns = [*_CORE_FRAME_COLUMNS, *context_columns]
    frame = pd.DataFrame(rows)
    if frame.empty:
        frame = pd.DataFrame(columns=columns)
    else:
        frame = frame.reindex(columns=columns)
    explicit_metadata: dict[str, object] = {
        "diagnostic_schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "automatic_test_switching": False,
    }
    if metadata:
        explicit_metadata.update(
            {str(key): _serializable_scalar(value) for key, value in metadata.items()}
        )
    for key, value in explicit_metadata.items():
        frame[key] = value
    # Retain attrs as a compatibility convenience, but never as the only
    # carrier of scientific metadata: attrs are routinely lost by transforms
    # and are not written to Excel.
    frame.attrs.update(explicit_metadata)
    return frame


def build_group_cell_diagnostics(
    data: pd.DataFrame,
    *,
    value_col: str,
    group_cols: Sequence[str] = ("group", "condition", "roi"),
    alpha: float = 0.05,
    minimum_n: int = MIN_SHAPIRO_N,
    zero_tolerance: float = 0.0,
    correction: str | None = None,
    correction_family: str = "group_cell_normality",
) -> pd.DataFrame:
    """Build diagnostics for each observed group/cell combination."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame")
    normalized_group_cols = tuple(str(col) for col in group_cols)
    if not normalized_group_cols:
        raise ValueError("group_cols must contain at least one column")
    if len(set(normalized_group_cols)) != len(normalized_group_cols):
        raise ValueError("group_cols must not contain duplicate column names")
    required = [value_col, *normalized_group_cols]
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    records: list[DiagnosticRecord] = []
    grouper: str | list[str] = (
        normalized_group_cols[0]
        if len(normalized_group_cols) == 1
        else list(normalized_group_cols)
    )
    for keys, cell in data.groupby(grouper, dropna=False, sort=False):
        key_values = (keys,) if len(normalized_group_cols) == 1 else tuple(keys)
        context = {
            column: _serializable_scalar(value)
            for column, value in zip(normalized_group_cols, key_values)
        }
        records.extend(
            build_value_diagnostics(
                cell[value_col],
                alpha=alpha,
                minimum_n=minimum_n,
                zero_tolerance=zero_tolerance,
                context=context,
            )
        )

    adjusted_records: tuple[DiagnosticRecord, ...]
    if correction is not None:
        adjusted_records = adjust_shapiro_family(
            records,
            method=correction,
            family=correction_family,
            alpha=alpha,
        )
    else:
        adjusted_records = tuple(records)

    return diagnostics_to_frame(
        adjusted_records,
        metadata={
            "diagnostic_scope": "group_cell",
            "value_column": value_col,
            "group_columns": ",".join(normalized_group_cols),
            "normality_adjustment_method": correction,
            "normality_adjustment_family": correction_family if correction else None,
            "normality_alpha": alpha,
        },
    )


def build_residual_diagnostics(
    residuals: object,
    *,
    alpha: float = 0.05,
    standardized_threshold: float = 3.0,
    context: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Build report-only residual integrity, variance, normality, and tail checks."""

    if (
        not np.isfinite(float(standardized_threshold))
        or float(standardized_threshold) <= 0.0
    ):
        raise ValueError("standardized_threshold must be finite and positive")
    residual_context = dict(context or {})
    residual_context["diagnostic_target"] = "model_residuals"
    summary = coerce_finite_values(residuals)
    records = [
        replace(
            build_data_integrity_diagnostic(
                residuals,
                context=residual_context,
            ),
            check="residual_data_integrity",
        ),
        replace(
            build_variance_diagnostic(
                residuals,
                context=residual_context,
            ),
            check="residual_variance",
        ),
        replace(
            build_shapiro_diagnostic(
                residuals,
                alpha=alpha,
                context=residual_context,
            ),
            check="residual_normality_shapiro",
        ),
    ]

    values = summary.as_array()
    if values.size < 2:
        tail_record = DiagnosticRecord(
            check="residual_extremes",
            status=DiagnosticStatus.NOT_ESTIMABLE,
            code="tiny_n",
            context={
                **residual_context,
                "standardized_threshold": standardized_threshold,
            },
            n_total=summary.n_total,
            n_finite=summary.n_finite,
        )
    else:
        spread = float(np.std(values, ddof=1))
        if not np.isfinite(spread) or spread <= 0.0:
            tail_record = DiagnosticRecord(
                check="residual_extremes",
                status=DiagnosticStatus.NOT_ESTIMABLE,
                code="zero_variance",
                context={
                    **residual_context,
                    "standardized_threshold": standardized_threshold,
                },
                n_total=summary.n_total,
                n_finite=summary.n_finite,
            )
        else:
            standardized = np.abs((values - float(np.mean(values))) / spread)
            maximum = float(np.max(standardized))
            flagged = int(np.sum(standardized > standardized_threshold))
            tail_record = DiagnosticRecord(
                check="residual_extremes",
                status=(
                    DiagnosticStatus.DIAGNOSTIC
                    if flagged
                    else DiagnosticStatus.ESTIMABLE
                ),
                code="extreme_residuals_present" if flagged else "no_extreme_residuals",
                context={
                    **residual_context,
                    "standardized_threshold": standardized_threshold,
                    "flagged_count": flagged,
                },
                n_total=summary.n_total,
                n_finite=summary.n_finite,
                statistic_name="maximum_absolute_standardized_residual",
                statistic=maximum,
            )
    records.append(tail_record)
    return diagnostics_to_frame(
        records,
        metadata={
            "diagnostic_scope": "model_residuals",
            "normality_role": "diagnostic_only",
            "automatic_test_switching": False,
        },
    )


def build_influence_diagnostics(
    influence_values: Mapping[object, object],
    *,
    threshold: float,
    metric: str = "absolute_leave_one_out_estimate_change",
    context: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Label participant-level influence values against an explicit threshold."""

    if not isinstance(influence_values, Mapping):
        raise TypeError("influence_values must map participant IDs to values")
    if not np.isfinite(float(threshold)) or float(threshold) < 0.0:
        raise ValueError("threshold must be finite and non-negative")
    metric_name = str(metric).strip()
    if not metric_name:
        raise ValueError("metric must be non-empty")

    records: list[DiagnosticRecord] = []
    base_context = dict(context or {})
    base_context["influence_threshold"] = float(threshold)
    for participant, raw_value in influence_values.items():
        participant_context = {
            **base_context,
            "participant_id": _serializable_scalar(participant),
        }
        summary = coerce_finite_values([raw_value])
        if summary.n_finite != 1:
            records.append(
                DiagnosticRecord(
                    check="participant_influence",
                    status=DiagnosticStatus.NOT_ESTIMABLE,
                    code="invalid_influence_value",
                    context=participant_context,
                    n_total=1,
                    n_finite=0,
                    statistic_name=metric_name,
                )
            )
            continue
        value = abs(float(summary.values[0]))
        flagged = value > float(threshold)
        records.append(
            DiagnosticRecord(
                check="participant_influence",
                status=(
                    DiagnosticStatus.DIAGNOSTIC
                    if flagged
                    else DiagnosticStatus.ESTIMABLE
                ),
                code="influential_participant" if flagged else "within_threshold",
                context=participant_context,
                n_total=1,
                n_finite=1,
                statistic_name=metric_name,
                statistic=value,
            )
        )
    return diagnostics_to_frame(
        records,
        metadata={
            "diagnostic_scope": "participant_influence",
            "influence_metric": metric_name,
            "influence_threshold": float(threshold),
            "automatic_exclusion": False,
        },
    )


def _serializable_scalar(value: Any) -> object:
    if value is None:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if _is_missing(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return ",".join(str(_serializable_scalar(item)) for item in value)
    return str(value)


__all__ = [
    "DIAGNOSTIC_SCHEMA_VERSION",
    "MIN_SHAPIRO_N",
    "DiagnosticRecord",
    "DiagnosticStatus",
    "FiniteValueSummary",
    "adjust_shapiro_family",
    "build_confidence_interval_diagnostic",
    "build_data_integrity_diagnostic",
    "build_group_cell_diagnostics",
    "build_influence_diagnostics",
    "build_model_fit_diagnostics",
    "build_residual_diagnostics",
    "build_sample_size_diagnostic",
    "build_shapiro_diagnostic",
    "build_value_diagnostics",
    "build_variance_diagnostic",
    "coerce_finite_values",
    "diagnostics_to_frame",
]

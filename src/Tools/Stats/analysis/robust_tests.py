"""GUI-neutral robust and rank-based statistical sensitivity tests.

These functions are deliberately sensitivity analyses.  They do not inspect
Shapiro-Wilk results and do not replace the primary arithmetic-mean analysis.
Each function returns explicit result and inference-metadata frames suitable
for workbook export.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import warnings
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Stats.analysis.inference_contracts import (
    Alternative,
    AnalysisProfile,
    AnalysisResultMetadata,
    AnalysisRunSpec,
    HarmonicProvenance,
    InferenceRole,
    TestMetadata,
)


ROBUST_TEST_SCHEMA_VERSION = 1
DEFAULT_TRIM_FRACTION = 0.20
MINIMUM_INFERENCE_N = 3
ADAPTIVE_HARMONIC_WARNING = (
    "The harmonic range was selected from this sample. Sensitivity results "
    "therefore inherit post-selection uncertainty: response-versus-zero "
    "p-values are exploratory, and other contrasts are conditional on the "
    "selected harmonic range."
)
SHAPIRO_METHOD_NOTE = "This sensitivity method is prespecified; Shapiro-Wilk diagnostics do not select or replace it."


class RobustTestError(ValueError):
    """Raised when a robust sensitivity-test request is not well formed."""


@dataclass(frozen=True)
class RobustTestResult:
    """One robust-test result and its explicit inference metadata."""

    results: pd.DataFrame
    analysis_metadata: AnalysisResultMetadata

    @property
    def metadata(self) -> pd.DataFrame:
        """Return a copy of the export-ready run metadata frame."""

        return self.analysis_metadata.to_frames()["Run Metadata"].copy()

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return additive workbook-ready result and metadata frames."""

        return {
            "Robust Sensitivity Results": self.results.copy(),
            **{label: frame.copy() for label, frame in self.analysis_metadata.to_frames().items()},
        }


@dataclass(frozen=True)
class _TrimmedComponents:
    """Numerical components for a gamma-trimmed location estimator."""

    n: int
    trimmed_each_tail: int
    effective_n: int
    trimmed_mean: float
    winsorized_variance: float


def _resolve_run_spec(
    *,
    run_spec: AnalysisRunSpec | None,
    harmonic_provenance: HarmonicProvenance | str | None,
    alpha: float,
    alternative: Alternative | str | None = None,
) -> tuple[AnalysisRunSpec, Alternative]:
    if run_spec is not None and not isinstance(run_spec, AnalysisRunSpec):
        raise TypeError("run_spec must be an AnalysisRunSpec.")
    explicit_provenance = None if harmonic_provenance is None else HarmonicProvenance.coerce(harmonic_provenance)
    if run_spec is not None:
        if explicit_provenance is not None and explicit_provenance is not run_spec.harmonic_provenance:
            raise RobustTestError("harmonic_provenance conflicts with run_spec.harmonic_provenance.")
        effective_alternative = (
            run_spec.response_alternative if alternative is None else Alternative.coerce(alternative)
        )
        return (
            replace(
                run_spec,
                alpha=alpha,
                response_alternative=effective_alternative,
            ),
            effective_alternative,
        )

    provenance = explicit_provenance or HarmonicProvenance.UNKNOWN
    effective_alternative = Alternative.TWO_SIDED if alternative is None else Alternative.coerce(alternative)
    return (
        AnalysisRunSpec(
            profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
            harmonic_provenance=provenance,
            alpha=alpha,
            response_alternative=effective_alternative,
        ),
        effective_alternative,
    )


def _coerce_finite_values(values: object) -> tuple[np.ndarray, int, int]:
    try:
        raw = np.asarray(values, dtype=object)
    except (TypeError, ValueError) as exc:
        raise RobustTestError("values must be a one-dimensional sequence.") from exc
    if raw.ndim != 1:
        raise RobustTestError("values must be a one-dimensional sequence.")
    series = pd.Series(raw, dtype=object)
    invalid_scalar_type = series.map(
        lambda value: isinstance(
            value,
            (bool, np.bool_, complex, np.complexfloating),
        )
    )
    numeric = pd.to_numeric(
        series.mask(invalid_scalar_type),
        errors="coerce",
    ).to_numpy(dtype=float)
    finite_mask = np.isfinite(numeric)
    return numeric[finite_mask], int(numeric.size), int((~finite_mask).sum())


def _validate_alpha(alpha: float) -> float:
    try:
        resolved = float(alpha)
    except (TypeError, ValueError) as exc:
        raise RobustTestError("alpha must be strictly between 0 and 1.") from exc
    if not 0.0 < resolved < 1.0:
        raise RobustTestError("alpha must be strictly between 0 and 1.")
    return resolved


def _resolve_alpha(
    alpha: float | None,
    *,
    run_spec: AnalysisRunSpec | None,
) -> float:
    if run_spec is not None and not isinstance(run_spec, AnalysisRunSpec):
        raise TypeError("run_spec must be an AnalysisRunSpec.")
    if alpha is None:
        return float(run_spec.alpha) if run_spec is not None else 0.05
    return _validate_alpha(alpha)


def _validate_trim_fraction(trim_fraction: float) -> float:
    try:
        resolved = float(trim_fraction)
    except (TypeError, ValueError) as exc:
        raise RobustTestError("trim_fraction must be at least zero and less than 0.5.") from exc
    if not 0.0 <= resolved < 0.5:
        raise RobustTestError("trim_fraction must be at least zero and less than 0.5.")
    return resolved


def _is_constant(values: np.ndarray) -> bool:
    return bool(values.size > 0 and np.all(values == values[0]))


def _trimmed_components(
    values: np.ndarray,
    *,
    trim_fraction: float,
) -> _TrimmedComponents:
    ordered = np.sort(values.astype(float, copy=False))
    n = int(ordered.size)
    trimmed_each_tail = int(np.floor(trim_fraction * n))
    effective_n = n - (2 * trimmed_each_tail)
    if effective_n <= 0:
        return _TrimmedComponents(
            n=n,
            trimmed_each_tail=trimmed_each_tail,
            effective_n=effective_n,
            trimmed_mean=np.nan,
            winsorized_variance=np.nan,
        )
    trimmed = ordered[trimmed_each_tail : n - trimmed_each_tail]
    trimmed_mean = float(np.mean(trimmed))
    if effective_n < 2:
        winsorized_variance = np.nan
    else:
        winsorized = ordered.copy()
        if trimmed_each_tail:
            winsorized[:trimmed_each_tail] = ordered[trimmed_each_tail]
            winsorized[n - trimmed_each_tail :] = ordered[n - trimmed_each_tail - 1]
        # Yuen's variance uses h - 1 in the denominator.  Since the
        # winsorized vector retains n entries, NumPy's ddof is 2g + 1.
        winsorized_variance = float(np.var(winsorized, ddof=(2 * trimmed_each_tail) + 1))
    return _TrimmedComponents(
        n=n,
        trimmed_each_tail=trimmed_each_tail,
        effective_n=effective_n,
        trimmed_mean=trimmed_mean,
        winsorized_variance=winsorized_variance,
    )


def _t_probability(
    statistic: float,
    *,
    degrees_of_freedom: float,
    alternative: Alternative,
) -> float:
    if alternative is Alternative.GREATER:
        return float(stats.t.sf(statistic, degrees_of_freedom))
    if alternative is Alternative.LESS:
        return float(stats.t.cdf(statistic, degrees_of_freedom))
    return float(2.0 * stats.t.sf(abs(statistic), degrees_of_freedom))


def _t_confidence_interval(
    estimate: float,
    *,
    standard_error: float,
    degrees_of_freedom: float,
    alpha: float,
    alternative: Alternative,
) -> tuple[float, float, str]:
    if alternative is Alternative.GREATER:
        critical = float(stats.t.ppf(1.0 - alpha, degrees_of_freedom))
        return estimate - (critical * standard_error), np.nan, "one_sided_lower"
    if alternative is Alternative.LESS:
        critical = float(stats.t.ppf(1.0 - alpha, degrees_of_freedom))
        return np.nan, estimate + (critical * standard_error), "one_sided_upper"
    critical = float(stats.t.ppf(1.0 - (alpha / 2.0), degrees_of_freedom))
    margin = critical * standard_error
    return estimate - margin, estimate + margin, "two_sided"


def _interpretation_fields(run_spec: AnalysisRunSpec) -> dict[str, object]:
    harmonic_status = run_spec.response_inference_status
    if run_spec.harmonic_provenance is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE:
        inference_status = "exploratory_post_selection_sensitivity"
    elif run_spec.harmonic_provenance.independently_selected:
        inference_status = "sensitivity_independent_harmonics"
    else:
        inference_status = "sensitivity_harmonic_provenance_unverified"
    return {
        "inference_role": InferenceRole.SENSITIVITY.value,
        "primary_analysis": False,
        "harmonic_provenance": run_spec.harmonic_provenance.value,
        "harmonic_inference_status": harmonic_status,
        "inference_status": inference_status,
        "method_selected_by_shapiro": False,
    }


def _base_result_row(
    *,
    test_id: str,
    test_label: str,
    method: str,
    estimand: str,
    alpha: float,
    alternative: Alternative | None,
    run_spec: AnalysisRunSpec,
) -> dict[str, object]:
    row: dict[str, object] = {
        "robust_test_schema_version": ROBUST_TEST_SCHEMA_VERSION,
        "test_id": test_id,
        "test_label": test_label,
        "method": method,
        "estimand": estimand,
        "alternative": None if alternative is None else alternative.value,
        "alpha": alpha,
        "confidence_level": 1.0 - alpha,
        "estimate": np.nan,
        "statistic": np.nan,
        "degrees_of_freedom": np.nan,
        "standard_error": np.nan,
        "p_raw": np.nan,
        "ci_low": np.nan,
        "ci_high": np.nan,
        "ci_type": "not_available",
        "estimation_status": "not_estimable",
        "status_code": "not_evaluated",
        "estimable": False,
        "note": SHAPIRO_METHOD_NOTE,
    }
    row.update(_interpretation_fields(run_spec))
    return row


def _non_estimable(
    row: dict[str, object],
    *,
    status_code: str,
    note: str,
) -> None:
    row["estimation_status"] = "not_estimable"
    row["status_code"] = status_code
    row["estimable"] = False
    row["note"] = f"{row['note']} {note}"


def _estimated(row: dict[str, object]) -> None:
    row["estimation_status"] = "estimated"
    row["status_code"] = "ok"
    row["estimable"] = True


def _build_result(
    row: dict[str, object],
    *,
    run_spec: AnalysisRunSpec,
    test_metadata: TestMetadata,
) -> RobustTestResult:
    result_frame = pd.DataFrame([row]).replace([np.inf, -np.inf], np.nan)
    warnings_out = (
        (ADAPTIVE_HARMONIC_WARNING,) if run_spec.harmonic_provenance is HarmonicProvenance.SAME_SAMPLE_ADAPTIVE else ()
    )
    metadata = AnalysisResultMetadata(
        run_spec=run_spec,
        tests=(test_metadata,),
        warnings=warnings_out,
    )
    return RobustTestResult(
        results=result_frame,
        analysis_metadata=metadata,
    )


def run_one_sample_trimmed_mean_test(
    values: Sequence[object] | np.ndarray | pd.Series,
    *,
    popmean: float = 0.0,
    trim_fraction: float = DEFAULT_TRIM_FRACTION,
    alpha: float | None = None,
    alternative: Alternative | str | None = None,
    harmonic_provenance: HarmonicProvenance | str | None = None,
    run_spec: AnalysisRunSpec | None = None,
) -> RobustTestResult:
    """Test a gamma-trimmed location against a scalar using winsorized variance."""

    alpha_value = _resolve_alpha(alpha, run_spec=run_spec)
    trim_value = _validate_trim_fraction(trim_fraction)
    try:
        null_value = float(popmean)
    except (TypeError, ValueError) as exc:
        raise RobustTestError("popmean must be finite.") from exc
    if not np.isfinite(null_value):
        raise RobustTestError("popmean must be finite.")
    resolved_run, resolved_alternative = _resolve_run_spec(
        run_spec=run_spec,
        harmonic_provenance=harmonic_provenance,
        alpha=alpha_value,
        alternative=alternative,
    )
    finite, n_input, n_excluded = _coerce_finite_values(values)
    components = _trimmed_components(finite, trim_fraction=trim_value)
    estimand = f"{trim_value:.0%} trimmed population location minus {null_value:g}"
    row = _base_result_row(
        test_id="one_sample_trimmed_mean",
        test_label="One-sample trimmed-mean sensitivity",
        method="one-sample trimmed-mean t-test with winsorized variance",
        estimand=estimand,
        alpha=alpha_value,
        alternative=resolved_alternative,
        run_spec=resolved_run,
    )
    row.update(
        {
            "n_input": n_input,
            "n_finite": int(finite.size),
            "n_excluded_invalid_or_nonfinite": n_excluded,
            "trim_fraction": trim_value,
            "trimmed_each_tail": components.trimmed_each_tail,
            "effective_n": components.effective_n,
            "location_estimate": components.trimmed_mean,
            "null_value": null_value,
            "winsorized_variance": components.winsorized_variance,
        }
    )
    metadata = TestMetadata(
        test_id="one_sample_trimmed_mean",
        test_label="One-sample trimmed-mean sensitivity",
        method="trimmed-mean t-test with winsorized variance",
        estimand=estimand,
        role=InferenceRole.SENSITIVITY,
        scope="one sample",
        alternative=resolved_alternative,
        notes=(SHAPIRO_METHOD_NOTE,),
    )

    if finite.size < MINIMUM_INFERENCE_N:
        _non_estimable(
            row,
            status_code="insufficient_finite_n",
            note=f"At least {MINIMUM_INFERENCE_N} finite observations are required.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if bool(np.all(finite == null_value)):
        _non_estimable(
            row,
            status_code="all_zero_differences",
            note="Every response equals the null value.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if _is_constant(finite):
        _non_estimable(
            row,
            status_code="constant_input",
            note="A constant sample has no estimable winsorized standard error.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if components.effective_n < 2:
        _non_estimable(
            row,
            status_code="insufficient_effective_n_after_trimming",
            note="Too few observations remain after trimming.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    standard_error_squared = components.winsorized_variance / components.effective_n
    if not np.isfinite(standard_error_squared) or standard_error_squared <= 0.0:
        _non_estimable(
            row,
            status_code="zero_or_invalid_winsorized_standard_error",
            note="The winsorized standard error is zero or invalid.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    standard_error = float(np.sqrt(standard_error_squared))
    estimate = float(components.trimmed_mean - null_value)
    degrees_of_freedom = float(components.effective_n - 1)
    statistic = float(estimate / standard_error)
    p_raw = _t_probability(
        statistic,
        degrees_of_freedom=degrees_of_freedom,
        alternative=resolved_alternative,
    )
    ci_low, ci_high, ci_type = _t_confidence_interval(
        estimate,
        standard_error=standard_error,
        degrees_of_freedom=degrees_of_freedom,
        alpha=alpha_value,
        alternative=resolved_alternative,
    )
    numeric_outputs = (
        estimate,
        standard_error,
        degrees_of_freedom,
        statistic,
        p_raw,
    )
    if not all(np.isfinite(value) for value in numeric_outputs):
        _non_estimable(
            row,
            status_code="invalid_numerical_result",
            note="The trimmed-mean calculation produced a non-finite result.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    row.update(
        {
            "estimate": estimate,
            "statistic": statistic,
            "degrees_of_freedom": degrees_of_freedom,
            "standard_error": standard_error,
            "p_raw": p_raw,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "ci_type": ci_type,
        }
    )
    _estimated(row)
    return _build_result(row, run_spec=resolved_run, test_metadata=metadata)


def run_one_sample_wilcoxon_test(
    values: Sequence[object] | np.ndarray | pd.Series,
    *,
    popmedian: float = 0.0,
    alpha: float | None = None,
    alternative: Alternative | str | None = None,
    zero_method: str = "wilcox",
    continuity_correction: bool = False,
    p_value_method: str = "auto",
    harmonic_provenance: HarmonicProvenance | str | None = None,
    run_spec: AnalysisRunSpec | None = None,
) -> RobustTestResult:
    """Run a one-sample Wilcoxon signed-rank sensitivity analysis."""

    alpha_value = _resolve_alpha(alpha, run_spec=run_spec)
    try:
        null_value = float(popmedian)
    except (TypeError, ValueError) as exc:
        raise RobustTestError("popmedian must be finite.") from exc
    if not np.isfinite(null_value):
        raise RobustTestError("popmedian must be finite.")
    zero_method_value = str(zero_method).strip().casefold()
    if zero_method_value not in {"wilcox", "pratt", "zsplit"}:
        raise RobustTestError("zero_method must be 'wilcox', 'pratt', or 'zsplit'.")
    p_method_value = str(p_value_method).strip().casefold()
    if p_method_value not in {"auto", "exact", "approx", "asymptotic"}:
        raise RobustTestError(
            "p_value_method must be 'auto', 'exact', or 'asymptotic' "
            "('approx' is accepted as an alias)."
        )
    resolved_run, resolved_alternative = _resolve_run_spec(
        run_spec=run_spec,
        harmonic_provenance=harmonic_provenance,
        alpha=alpha_value,
        alternative=alternative,
    )
    finite, n_input, n_excluded = _coerce_finite_values(values)
    differences = finite - null_value
    nonzero = differences[differences != 0.0]
    has_zeros = bool(np.any(differences == 0.0))
    absolute_nonzero = np.abs(nonzero)
    has_ties = len(np.unique(absolute_nonzero)) < len(absolute_nonzero)
    scipy_p_method = (
        "asymptotic" if p_method_value == "approx" else p_method_value
    )
    if scipy_p_method == "auto":
        if differences.size > 50:
            effective_p_method = "asymptotic"
            p_value_exact = False
            p_method_note = "SciPy auto selected its asymptotic reference."
        elif not (has_zeros or has_ties):
            effective_p_method = "exact_discrete_reference"
            p_value_exact = True
            p_method_note = "No zero differences or tied absolute ranks were present."
        elif differences.size <= 13:
            effective_p_method = "exact_sign_permutation"
            p_value_exact = True
            p_method_note = (
                "SciPy auto enumerates the sign-permutation distribution for "
                "this small sample with zeros or ties."
            )
        else:
            effective_p_method = "asymptotic"
            p_value_exact = False
            p_method_note = (
                "SciPy auto used its asymptotic reference because zeros or ties "
                "were present in a sample larger than 13."
            )
    elif scipy_p_method == "exact" and (has_zeros or has_ties):
        effective_p_method = "conservative_discrete_reference"
        p_value_exact = False
        p_method_note = (
            "Zeros or tied absolute ranks prevent an exact Wilcoxon "
            "distribution; SciPy uses conservative rounding against its "
            "untied discrete reference."
        )
    elif scipy_p_method == "exact":
        effective_p_method = "exact_discrete_reference"
        p_value_exact = True
        p_method_note = "No zero differences or tied absolute ranks were present."
    else:
        effective_p_method = "asymptotic"
        p_value_exact = False
        p_method_note = "The asymptotic normal reference was requested."
    median_difference = float(np.median(differences)) if differences.size else np.nan
    estimand = f"symmetric distribution location shift relative to {null_value:g}; sample median is descriptive"
    row = _base_result_row(
        test_id="one_sample_wilcoxon",
        test_label="One-sample Wilcoxon signed-rank sensitivity",
        method="Wilcoxon signed-rank test",
        estimand=estimand,
        alpha=alpha_value,
        alternative=resolved_alternative,
        run_spec=resolved_run,
    )
    row.update(
        {
            "n_input": n_input,
            "n_finite": int(finite.size),
            "n_excluded_invalid_or_nonfinite": n_excluded,
            "n_nonzero": int(nonzero.size),
            "null_value": null_value,
            "sample_median_difference": median_difference,
            "zero_method": zero_method_value,
            "continuity_correction": bool(continuity_correction),
            "p_value_method_requested": p_method_value,
            "p_value_method_effective": effective_p_method,
            "p_value_exact": p_value_exact,
            "p_value_method_note": p_method_note,
            "rank_biserial_correlation": np.nan,
        }
    )
    metadata = TestMetadata(
        test_id="one_sample_wilcoxon",
        test_label="One-sample Wilcoxon signed-rank sensitivity",
        method=(
            f"Wilcoxon signed-rank; zero_method={zero_method_value}; "
            f"p_method={effective_p_method}"
        ),
        estimand=estimand,
        role=InferenceRole.SENSITIVITY,
        scope="one sample",
        alternative=resolved_alternative,
        notes=(SHAPIRO_METHOD_NOTE,),
    )

    if finite.size < MINIMUM_INFERENCE_N:
        _non_estimable(
            row,
            status_code="insufficient_finite_n",
            note=f"At least {MINIMUM_INFERENCE_N} finite observations are required.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if nonzero.size < MINIMUM_INFERENCE_N:
        code = "all_zero_differences" if nonzero.size == 0 else "insufficient_nonzero_n"
        _non_estimable(
            row,
            status_code=code,
            note=(f"At least {MINIMUM_INFERENCE_N} non-zero differences are required for this sensitivity."),
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if _is_constant(finite):
        _non_estimable(
            row,
            status_code="constant_input",
            note="A constant sample is not reported as an inferential sensitivity.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            scipy_result = stats.wilcoxon(
                differences,
                zero_method=zero_method_value,
                correction=bool(continuity_correction),
                alternative=resolved_alternative.scipy_value,
                method=scipy_p_method,
            )
        except (TypeError, ValueError, FloatingPointError) as exc:
            _non_estimable(
                row,
                status_code="scipy_wilcoxon_failed",
                note=f"Wilcoxon calculation failed: {type(exc).__name__}: {exc}",
            )
            return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    statistic = float(scipy_result.statistic)
    p_raw = float(scipy_result.pvalue)
    if zero_method_value == "wilcox":
        ranked_differences = nonzero
        ranks = stats.rankdata(np.abs(ranked_differences), method="average")
        positive_rank_sum = float(np.sum(ranks[ranked_differences > 0.0]))
        negative_rank_sum = float(np.sum(ranks[ranked_differences < 0.0]))
    else:
        ranks = stats.rankdata(np.abs(differences), method="average")
        positive_rank_sum = float(np.sum(ranks[differences > 0.0]))
        negative_rank_sum = float(np.sum(ranks[differences < 0.0]))
        if zero_method_value == "zsplit":
            half_zero_ranks = float(np.sum(ranks[differences == 0.0]) / 2.0)
            positive_rank_sum += half_zero_ranks
            negative_rank_sum += half_zero_ranks
    rank_total = positive_rank_sum + negative_rank_sum
    rank_biserial = (positive_rank_sum - negative_rank_sum) / rank_total if rank_total > 0.0 else np.nan
    if not all(np.isfinite(value) for value in (statistic, p_raw, rank_biserial)):
        _non_estimable(
            row,
            status_code="invalid_numerical_result",
            note="The Wilcoxon calculation produced a non-finite result.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    scipy_warnings = "; ".join(str(item.message) for item in caught)
    row.update(
        {
            "estimate": median_difference,
            "statistic": statistic,
            "p_raw": p_raw,
            "rank_biserial_correlation": float(rank_biserial),
            "rank_biserial_definition": (
                f"(positive rank sum - negative rank sum) / total rank sum; "
                f"ranks follow zero_method={zero_method_value}"
            ),
            "scipy_warning": scipy_warnings,
        }
    )
    _estimated(row)
    return _build_result(row, run_spec=resolved_run, test_metadata=metadata)


def run_two_group_trimmed_mean_test(
    group_a_values: Sequence[object] | np.ndarray | pd.Series,
    group_b_values: Sequence[object] | np.ndarray | pd.Series,
    *,
    group_a_label: str = "group_a",
    group_b_label: str = "group_b",
    trim_fraction: float = DEFAULT_TRIM_FRACTION,
    alpha: float | None = None,
    alternative: Alternative | str | None = Alternative.TWO_SIDED,
    harmonic_provenance: HarmonicProvenance | str | None = None,
    run_spec: AnalysisRunSpec | None = None,
) -> RobustTestResult:
    """Run Yuen's unequal-variance comparison of two trimmed group locations."""

    alpha_value = _resolve_alpha(alpha, run_spec=run_spec)
    trim_value = _validate_trim_fraction(trim_fraction)
    label_a = str(group_a_label).strip()
    label_b = str(group_b_label).strip()
    if not label_a or not label_b or label_a.casefold() == label_b.casefold():
        raise RobustTestError("group labels must be non-empty and distinct.")
    resolved_run, resolved_alternative = _resolve_run_spec(
        run_spec=run_spec,
        harmonic_provenance=harmonic_provenance,
        alpha=alpha_value,
        alternative=alternative,
    )
    values_a, n_input_a, n_excluded_a = _coerce_finite_values(group_a_values)
    values_b, n_input_b, n_excluded_b = _coerce_finite_values(group_b_values)
    components_a = _trimmed_components(values_a, trim_fraction=trim_value)
    components_b = _trimmed_components(values_b, trim_fraction=trim_value)
    estimand = f"{trim_value:.0%} trimmed population location difference ({label_a} minus {label_b})"
    row = _base_result_row(
        test_id="two_group_trimmed_mean",
        test_label="Two-group trimmed-mean sensitivity",
        method="Yuen unequal-variance trimmed-mean t-test",
        estimand=estimand,
        alpha=alpha_value,
        alternative=resolved_alternative,
        run_spec=resolved_run,
    )
    row.update(
        {
            "group_a": label_a,
            "group_b": label_b,
            "sign_convention": f"positive means {label_a} > {label_b}",
            "n_input_group_a": n_input_a,
            "n_finite_group_a": int(values_a.size),
            "n_excluded_invalid_or_nonfinite_group_a": n_excluded_a,
            "n_input_group_b": n_input_b,
            "n_finite_group_b": int(values_b.size),
            "n_excluded_invalid_or_nonfinite_group_b": n_excluded_b,
            "trim_fraction": trim_value,
            "trimmed_each_tail_group_a": components_a.trimmed_each_tail,
            "trimmed_each_tail_group_b": components_b.trimmed_each_tail,
            "effective_n_group_a": components_a.effective_n,
            "effective_n_group_b": components_b.effective_n,
            "trimmed_mean_group_a": components_a.trimmed_mean,
            "trimmed_mean_group_b": components_b.trimmed_mean,
            "winsorized_variance_group_a": components_a.winsorized_variance,
            "winsorized_variance_group_b": components_b.winsorized_variance,
        }
    )
    metadata = TestMetadata(
        test_id="two_group_trimmed_mean",
        test_label="Two-group trimmed-mean sensitivity",
        method="Yuen unequal-variance trimmed-mean t-test",
        estimand=estimand,
        role=InferenceRole.SENSITIVITY,
        scope=f"{label_a} versus {label_b}",
        alternative=resolved_alternative,
        notes=(SHAPIRO_METHOD_NOTE, f"Sign is {label_a} minus {label_b}."),
    )

    if values_a.size < MINIMUM_INFERENCE_N or values_b.size < MINIMUM_INFERENCE_N:
        _non_estimable(
            row,
            status_code="insufficient_group_n",
            note=(f"Each group requires at least {MINIMUM_INFERENCE_N} finite observations."),
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if _is_constant(np.concatenate((values_a, values_b))):
        _non_estimable(
            row,
            status_code="constant_input",
            note="The combined input is constant and has no estimable standard error.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if components_a.effective_n < 2 or components_b.effective_n < 2:
        _non_estimable(
            row,
            status_code="insufficient_effective_n_after_trimming",
            note="At least two observations per group must remain after trimming.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    variance_term_a = components_a.winsorized_variance / components_a.effective_n
    variance_term_b = components_b.winsorized_variance / components_b.effective_n
    standard_error_squared = variance_term_a + variance_term_b
    denominator = (variance_term_a**2) / (components_a.effective_n - 1) + (variance_term_b**2) / (
        components_b.effective_n - 1
    )
    if (
        not np.isfinite(standard_error_squared)
        or standard_error_squared <= 0.0
        or not np.isfinite(denominator)
        or denominator <= 0.0
    ):
        _non_estimable(
            row,
            status_code="zero_or_invalid_winsorized_standard_error",
            note="The unequal-variance winsorized standard error is zero or invalid.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    standard_error = float(np.sqrt(standard_error_squared))
    estimate = float(components_a.trimmed_mean - components_b.trimmed_mean)
    degrees_of_freedom = float((standard_error_squared**2) / denominator)
    statistic = float(estimate / standard_error)
    p_raw = _t_probability(
        statistic,
        degrees_of_freedom=degrees_of_freedom,
        alternative=resolved_alternative,
    )
    ci_low, ci_high, ci_type = _t_confidence_interval(
        estimate,
        standard_error=standard_error,
        degrees_of_freedom=degrees_of_freedom,
        alpha=alpha_value,
        alternative=resolved_alternative,
    )
    numeric_outputs = (
        estimate,
        standard_error,
        degrees_of_freedom,
        statistic,
        p_raw,
    )
    if not all(np.isfinite(value) for value in numeric_outputs):
        _non_estimable(
            row,
            status_code="invalid_numerical_result",
            note="The trimmed group comparison produced a non-finite result.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    row.update(
        {
            "estimate": estimate,
            "statistic": statistic,
            "degrees_of_freedom": degrees_of_freedom,
            "standard_error": standard_error,
            "p_raw": p_raw,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "ci_type": ci_type,
        }
    )
    _estimated(row)
    return _build_result(row, run_spec=resolved_run, test_metadata=metadata)


def run_friedman_test(
    data: pd.DataFrame,
    *,
    value_col: str,
    subject_col: str,
    level_col: str,
    levels: Sequence[object] | None = None,
    alpha: float | None = None,
    harmonic_provenance: HarmonicProvenance | str | None = None,
    run_spec: AnalysisRunSpec | None = None,
) -> RobustTestResult:
    """Run a complete-case one-factor Friedman rank sensitivity analysis."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    required = (value_col, subject_col, level_col)
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise RobustTestError(f"Missing required columns: {missing}")
    alpha_value = _resolve_alpha(alpha, run_spec=run_spec)
    resolved_run, _ = _resolve_run_spec(
        run_spec=run_spec,
        harmonic_provenance=harmonic_provenance,
        alpha=alpha_value,
    )
    estimand = "within-participant rank differences across repeated factor levels"
    row = _base_result_row(
        test_id="friedman_one_factor",
        test_label="Friedman one-factor sensitivity",
        method="Friedman repeated-measures rank test",
        estimand=estimand,
        alpha=alpha_value,
        alternative=None,
        run_spec=resolved_run,
    )
    metadata = TestMetadata(
        test_id="friedman_one_factor",
        test_label="Friedman one-factor sensitivity",
        method="Friedman repeated-measures rank test",
        estimand=estimand,
        role=InferenceRole.SENSITIVITY,
        scope=level_col,
        notes=(SHAPIRO_METHOD_NOTE, "Only complete participants are analyzed."),
    )

    selected = data.loc[:, list(required)].copy()
    invalid_identifier = selected[[subject_col, level_col]].apply(
        lambda column: column.map(
            lambda value: (
                value is None
                or bool(pd.isna(value))
                or isinstance(value, (bool, np.bool_))
                or (isinstance(value, str) and not value.strip())
            )
        )
    ).any(axis=1)
    invalid_response_type = selected[value_col].map(
        lambda value: isinstance(
            value,
            (bool, np.bool_, complex, np.complexfloating),
        )
    )
    selected["_numeric_value"] = pd.to_numeric(
        selected[value_col].mask(invalid_response_type),
        errors="coerce",
    )
    selected.loc[
        ~np.isfinite(selected["_numeric_value"].to_numpy(dtype=float)),
        "_numeric_value",
    ] = np.nan
    duplicate_counts = selected.groupby(
        [subject_col, level_col],
        dropna=False,
        sort=False,
    ).size()
    duplicate_cell_count = int((duplicate_counts > 1).sum())
    participant_count_input = int(selected[subject_col].nunique(dropna=True))

    if levels is None:
        resolved_levels = list(pd.unique(selected[level_col].dropna()))
    else:
        resolved_levels = list(levels)
        if len(resolved_levels) != len({str(level).casefold() for level in resolved_levels}):
            raise RobustTestError("levels must contain unique values.")
    row.update(
        {
            "factor": level_col,
            "levels": "; ".join(map(str, resolved_levels)),
            "n_levels": len(resolved_levels),
            "n_participants_input": participant_count_input,
            "n_complete_participants": 0,
            "n_duplicate_subject_level_cells": duplicate_cell_count,
            "n_invalid_identifier_rows": int(invalid_identifier.sum()),
            "n_invalid_response_type_rows": int(invalid_response_type.sum()),
            "kendalls_w": np.nan,
            "complete_case_analysis": True,
            "reference_distribution": "chi-square asymptotic approximation",
            "approximation_reliability_status": "not_evaluated",
            "approximation_caveat": (
                "SciPy documents the chi-square p-value as reliable only for "
                "more than 10 participants and more than 6 repeated levels."
            ),
        }
    )

    if bool(invalid_identifier.any()):
        _non_estimable(
            row,
            status_code="invalid_subject_or_level_identifier",
            note="Participant and repeated-level identifiers must be non-missing and non-blank.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if duplicate_cell_count:
        _non_estimable(
            row,
            status_code="duplicate_subject_level_cells",
            note="Each participant must have exactly one row per repeated level.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if len(resolved_levels) < 3:
        _non_estimable(
            row,
            status_code="insufficient_factor_levels",
            note="Friedman sensitivity requires at least three repeated levels.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    observed_level_keys = {str(level).casefold() for level in selected[level_col].dropna().unique()}
    missing_levels = [level for level in resolved_levels if str(level).casefold() not in observed_level_keys]
    if missing_levels:
        _non_estimable(
            row,
            status_code="requested_levels_missing",
            note="Requested levels are absent: " + ", ".join(map(str, missing_levels)),
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    pivot = selected.pivot(
        index=subject_col,
        columns=level_col,
        values="_numeric_value",
    )
    try:
        pivot = pivot.loc[:, resolved_levels]
    except KeyError:
        by_text = {str(column).casefold(): column for column in pivot.columns.tolist()}
        pivot = pivot.loc[
            :,
            [by_text[str(level).casefold()] for level in resolved_levels],
        ]
    complete = pivot.dropna(axis=0, how="any")
    matrix = complete.to_numpy(dtype=float)
    n_complete = int(matrix.shape[0])
    row["n_complete_participants"] = n_complete
    row["n_incomplete_participants_excluded"] = participant_count_input - n_complete
    row["approximation_reliability_status"] = (
        "meets_scipy_rule_of_thumb"
        if n_complete > 10 and len(resolved_levels) > 6
        else "caution_small_design"
    )
    if n_complete < MINIMUM_INFERENCE_N:
        _non_estimable(
            row,
            status_code="insufficient_complete_participants",
            note=(f"At least {MINIMUM_INFERENCE_N} participants with every level are required."),
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if _is_constant(matrix.reshape(-1)):
        _non_estimable(
            row,
            status_code="constant_input",
            note="All repeated observations are constant.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    if bool(np.all(np.ptp(matrix, axis=1) == 0.0)):
        _non_estimable(
            row,
            status_code="no_within_participant_variation",
            note="No participant varies across the repeated levels.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            scipy_result = stats.friedmanchisquare(*(matrix[:, index] for index in range(matrix.shape[1])))
        except (TypeError, ValueError, FloatingPointError) as exc:
            _non_estimable(
                row,
                status_code="scipy_friedman_failed",
                note=f"Friedman calculation failed: {type(exc).__name__}: {exc}",
            )
            return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    statistic = float(scipy_result.statistic)
    p_raw = float(scipy_result.pvalue)
    degrees_of_freedom = float(matrix.shape[1] - 1)
    kendalls_w = float(statistic / (n_complete * (matrix.shape[1] - 1)))
    if not all(np.isfinite(value) for value in (statistic, p_raw, kendalls_w)):
        _non_estimable(
            row,
            status_code="invalid_numerical_result",
            note="The Friedman calculation produced a non-finite result.",
        )
        return _build_result(row, run_spec=resolved_run, test_metadata=metadata)
    row.update(
        {
            "estimate": kendalls_w,
            "statistic": statistic,
            "degrees_of_freedom": degrees_of_freedom,
            "p_raw": p_raw,
            "kendalls_w": kendalls_w,
            "scipy_warning": "; ".join(str(item.message) for item in caught),
        }
    )
    _estimated(row)
    return _build_result(row, run_spec=resolved_run, test_metadata=metadata)


__all__ = [
    "ADAPTIVE_HARMONIC_WARNING",
    "DEFAULT_TRIM_FRACTION",
    "MINIMUM_INFERENCE_N",
    "ROBUST_TEST_SCHEMA_VERSION",
    "RobustTestError",
    "RobustTestResult",
    "run_friedman_test",
    "run_one_sample_trimmed_mean_test",
    "run_one_sample_wilcoxon_test",
    "run_two_group_trimmed_mean_test",
]

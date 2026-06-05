"""Statistical diagnostics for publication-report manuscript tables."""

from __future__ import annotations

from dataclasses import dataclass
import warnings

import numpy as np
import pandas as pd
from scipy import stats

P_ALPHA = 0.05


@dataclass(frozen=True)
class TestDiagnostics:
    """Parametric, nonparametric, and normality results for one planned test."""

    n: int
    df: float
    normality_statistic: float
    normality_p: float
    normality_met: object
    parametric_test: str
    parametric_statistic: float
    parametric_p: float
    nonparametric_test: str
    nonparametric_statistic: float
    nonparametric_p: float
    selected_test: str
    selected_p: float
    decision_reason: str

    def as_columns(self) -> dict[str, object]:
        """Return export-ready columns shared by report source sheets."""

        return {
            "normality_statistic": self.normality_statistic,
            "normality_p": self.normality_p,
            "normality_met": self.normality_met,
            "parametric_test": self.parametric_test,
            "parametric_statistic": self.parametric_statistic,
            "parametric_p": self.parametric_p,
            "nonparametric_test": self.nonparametric_test,
            "nonparametric_statistic": self.nonparametric_statistic,
            "nonparametric_p": self.nonparametric_p,
            "selected_test": self.selected_test,
            "selected_p": self.selected_p,
            "decision_reason": self.decision_reason,
        }


def one_sample_against_zero(
    values: pd.Series | np.ndarray,
    *,
    alpha: float = P_ALPHA,
) -> TestDiagnostics:
    """Run Shapiro-Wilk, one-sample t, and Wilcoxon signed-rank tests against zero."""

    numeric = finite_array(values)
    n = int(len(numeric))
    normality_statistic, normality_p, normality_met = shapiro_wilk(numeric, alpha=alpha)
    parametric_statistic, parametric_p = _one_sample_t(numeric)
    nonparametric_statistic, nonparametric_p = wilcoxon_signed_rank(numeric)
    selected_test, selected_p, decision_reason = _select_test(
        n=n,
        normality_p=normality_p,
        parametric_p=parametric_p,
        nonparametric_p=nonparametric_p,
        parametric_label="one_sample_t",
        nonparametric_label="wilcoxon_signed_rank",
        alpha=alpha,
    )
    return TestDiagnostics(
        n=n,
        df=float(n - 1) if n >= 2 else np.nan,
        normality_statistic=normality_statistic,
        normality_p=normality_p,
        normality_met=normality_met,
        parametric_test="one_sample_t",
        parametric_statistic=parametric_statistic,
        parametric_p=parametric_p,
        nonparametric_test="wilcoxon_signed_rank",
        nonparametric_statistic=nonparametric_statistic,
        nonparametric_p=nonparametric_p,
        selected_test=selected_test,
        selected_p=selected_p,
        decision_reason=decision_reason,
    )


def paired_difference_test(
    values_a: pd.Series | np.ndarray,
    values_b: pd.Series | np.ndarray,
    *,
    alpha: float = P_ALPHA,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, TestDiagnostics]:
    """Run Shapiro-Wilk, paired t, and Wilcoxon tests on paired a-minus-b differences."""

    a, b = finite_paired_arrays(values_a, values_b)
    diff = a - b if len(a) == len(b) else np.array([], dtype=float)
    n = int(len(diff))
    normality_statistic, normality_p, normality_met = shapiro_wilk(diff, alpha=alpha)
    parametric_statistic, parametric_p = _paired_t(a, b)
    nonparametric_statistic, nonparametric_p = wilcoxon_signed_rank(diff)
    selected_test, selected_p, decision_reason = _select_test(
        n=n,
        normality_p=normality_p,
        parametric_p=parametric_p,
        nonparametric_p=nonparametric_p,
        parametric_label="paired_t",
        nonparametric_label="wilcoxon_signed_rank",
        alpha=alpha,
    )
    return (
        a,
        b,
        diff,
        TestDiagnostics(
            n=n,
            df=float(n - 1) if n >= 2 else np.nan,
            normality_statistic=normality_statistic,
            normality_p=normality_p,
            normality_met=normality_met,
            parametric_test="paired_t",
            parametric_statistic=parametric_statistic,
            parametric_p=parametric_p,
            nonparametric_test="wilcoxon_signed_rank",
            nonparametric_statistic=nonparametric_statistic,
            nonparametric_p=nonparametric_p,
            selected_test=selected_test,
            selected_p=selected_p,
            decision_reason=decision_reason,
        ),
    )


def shapiro_wilk(values: np.ndarray, *, alpha: float = P_ALPHA) -> tuple[float, float, object]:
    """Return Shapiro-Wilk statistic, p-value, and assumption-met flag."""

    numeric = finite_array(values)
    if len(numeric) < 3:
        return np.nan, np.nan, np.nan
    if np.allclose(numeric, numeric[0], equal_nan=False):
        return np.nan, np.nan, np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        warnings.simplefilter("ignore", category=RuntimeWarning)
        result = stats.shapiro(numeric)
    statistic = _finite_float(result.statistic)
    p_value = _finite_float(result.pvalue)
    normality_met: object = bool(p_value >= alpha) if np.isfinite(p_value) else np.nan
    return statistic, p_value, normality_met


def wilcoxon_signed_rank(values: pd.Series | np.ndarray) -> tuple[float, float]:
    """Return Wilcoxon signed-rank statistic and two-tailed p-value against zero."""

    numeric = finite_array(values)
    if len(numeric) == 0:
        return np.nan, np.nan
    if not np.any(np.not_equal(numeric, 0.0)):
        return 0.0, 1.0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=UserWarning)
            warnings.simplefilter("ignore", category=RuntimeWarning)
            result = stats.wilcoxon(
                numeric,
                zero_method="wilcox",
                correction=False,
                alternative="two-sided",
            )
    except ValueError:
        return np.nan, np.nan
    return _finite_float(result.statistic), _finite_float(result.pvalue)


def holm_adjust(p_values: list[object] | np.ndarray) -> list[float]:
    """Return Holm-adjusted p-values, preserving NaN positions."""

    numeric = np.array([_finite_float(value) for value in p_values], dtype=float)
    adjusted = [np.nan] * len(numeric)
    valid_indices = [index for index, value in enumerate(numeric) if np.isfinite(value)]
    if not valid_indices:
        return adjusted

    ordered = sorted(valid_indices, key=lambda index: numeric[index])
    previous = 0.0
    m = len(ordered)
    for rank, index in enumerate(ordered):
        value = min((m - rank) * numeric[index], 1.0)
        previous = max(previous, value)
        adjusted[index] = float(previous)
    return adjusted


def bonferroni_adjust(p_values: list[object] | np.ndarray) -> list[float]:
    """Return Bonferroni-adjusted p-values, preserving NaN positions."""

    numeric = np.array([_finite_float(value) for value in p_values], dtype=float)
    valid_count = int(np.isfinite(numeric).sum())
    adjusted = [np.nan] * len(numeric)
    if valid_count == 0:
        return adjusted
    for index, value in enumerate(numeric):
        if np.isfinite(value):
            adjusted[index] = float(min(value * valid_count, 1.0))
    return adjusted


def finite_array(values: pd.Series | np.ndarray) -> np.ndarray:
    """Return finite numeric values from a pandas or NumPy vector."""

    numeric = pd.to_numeric(values, errors="coerce")
    array = np.asarray(numeric, dtype=float)
    return array[np.isfinite(array)]


def finite_paired_arrays(
    values_a: pd.Series | np.ndarray,
    values_b: pd.Series | np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return finite paired vectors, dropping rows with non-finite values in either vector."""

    a = np.asarray(pd.to_numeric(values_a, errors="coerce"), dtype=float)
    b = np.asarray(pd.to_numeric(values_b, errors="coerce"), dtype=float)
    if len(a) != len(b):
        return np.array([], dtype=float), np.array([], dtype=float)
    finite_mask = np.isfinite(a) & np.isfinite(b)
    return a[finite_mask], b[finite_mask]


def _one_sample_t(values: np.ndarray) -> tuple[float, float]:
    if len(values) < 2:
        return np.nan, np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        result = stats.ttest_1samp(values, popmean=0.0, nan_policy="omit")
    return _finite_float(result.statistic), _finite_float(result.pvalue)


def _paired_t(values_a: np.ndarray, values_b: np.ndarray) -> tuple[float, float]:
    if len(values_a) != len(values_b) or len(values_a) < 2:
        return np.nan, np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        result = stats.ttest_rel(values_a, values_b, nan_policy="omit")
    return _finite_float(result.statistic), _finite_float(result.pvalue)


def _select_test(
    *,
    n: int,
    normality_p: float,
    parametric_p: float,
    nonparametric_p: float,
    parametric_label: str,
    nonparametric_label: str,
    alpha: float,
) -> tuple[str, float, str]:
    if n < 2:
        return "insufficient_data", np.nan, "Fewer than two finite observations were available."
    if np.isfinite(normality_p) and normality_p < alpha and np.isfinite(nonparametric_p):
        return (
            nonparametric_label,
            float(nonparametric_p),
            "Shapiro-Wilk p < .05; Wilcoxon signed-rank selected and t-test retained as sensitivity.",
        )
    if np.isfinite(parametric_p):
        if np.isfinite(normality_p):
            return (
                parametric_label,
                float(parametric_p),
                "Shapiro-Wilk p >= .05; parametric t-test selected and Wilcoxon retained as sensitivity.",
            )
        return (
            parametric_label,
            float(parametric_p),
            "Normality was not testable; parametric t-test selected with Wilcoxon sensitivity result retained.",
        )
    if np.isfinite(nonparametric_p):
        return (
            nonparametric_label,
            float(nonparametric_p),
            "Parametric t-test was unavailable; Wilcoxon signed-rank selected.",
        )
    return "insufficient_data", np.nan, "No finite parametric or nonparametric p-value was available."


def _finite_float(value: object) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return np.nan
    return numeric if np.isfinite(numeric) else np.nan

"""Widget-free sensitivity calculations for common within-participant designs."""

from __future__ import annotations

from dataclasses import dataclass
import math

from pingouin import power_rm_anova
from statsmodels.stats.power import TTestPower


@dataclass(frozen=True)
class SensitivityResult:
    """A minimum detectable standardized effect and its interpretation."""

    analysis_label: str
    effect_metric: str
    effect_size: float
    magnitude: str
    reporting_text: str
    equivalent_eta_squared: float | None = None


def _validate_common(*, sample_size: int, power: float, alpha: float) -> None:
    if sample_size < 3:
        raise ValueError("Sample size must be at least 3.")
    if not math.isfinite(power) or not 0 < power < 1:
        raise ValueError("Desired power must be between 0 and 1.")
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("Alpha must be between 0 and 1.")


def interpret_cohens_d(effect_size: float) -> str:
    """Return a conventional Cohen magnitude label for an absolute d value."""

    value = abs(effect_size)
    if value < 0.20:
        return "Below small"
    if value < 0.50:
        return "Small"
    if value < 0.80:
        return "Medium"
    return "Large"


def interpret_cohens_f(effect_size: float) -> str:
    """Return a conventional Cohen magnitude label for an absolute f value."""

    value = abs(effect_size)
    if value < 0.10:
        return "Below small"
    if value < 0.25:
        return "Small"
    if value < 0.40:
        return "Medium"
    return "Large"


def calculate_paired_ttest_sensitivity(
    *,
    sample_size: int,
    power: float = 0.80,
    alpha: float = 0.05,
    alternative: str = "two-sided",
) -> SensitivityResult:
    """Calculate minimum detectable Cohen's dz for paired/one-sample data."""

    _validate_common(sample_size=sample_size, power=power, alpha=alpha)
    if alternative not in {"two-sided", "larger"}:
        raise ValueError("Alternative must be 'two-sided' or 'larger'.")

    effect_size = float(
        TTestPower().solve_power(
            effect_size=None,
            nobs=sample_size,
            alpha=alpha,
            power=power,
            alternative=alternative,
        )
    )
    if not math.isfinite(effect_size) or effect_size <= 0:
        raise ValueError("A valid detectable effect could not be calculated.")

    sidedness = "two-sided" if alternative == "two-sided" else "one-sided"
    magnitude = interpret_cohens_d(effect_size)
    reporting_text = (
        f"With N = {sample_size}, power = {power:.0%}, alpha = {alpha:g}, and a "
        f"{sidedness} paired/one-sample t-test, the minimum detectable effect is "
        f"Cohen's dz = {effect_size:.2f} ({magnitude.lower()})."
    )
    return SensitivityResult(
        analysis_label="Paired / one-sample t-test",
        effect_metric="Cohen's dz",
        effect_size=effect_size,
        magnitude=magnitude,
        reporting_text=reporting_text,
    )


def calculate_rm_anova_sensitivity(
    *,
    sample_size: int,
    measurements: int = 2,
    power: float = 0.80,
    alpha: float = 0.05,
    correlation: float = 0.50,
    epsilon: float = 1.0,
) -> SensitivityResult:
    """Calculate minimum detectable Cohen's f for balanced one-way RM-ANOVA."""

    _validate_common(sample_size=sample_size, power=power, alpha=alpha)
    if measurements < 2:
        raise ValueError("Repeated measurements must be at least 2.")
    minimum_correlation = -1 / (measurements - 1)
    if not math.isfinite(correlation) or not minimum_correlation < correlation < 1:
        raise ValueError(
            f"Average correlation must be greater than {minimum_correlation:.2f} "
            "and less than 1 for this number of measurements."
        )
    minimum_epsilon = 1 / (measurements - 1)
    if not math.isfinite(epsilon) or not minimum_epsilon <= epsilon <= 1:
        raise ValueError(
            f"Epsilon must be between {minimum_epsilon:.2f} and 1 for this "
            "number of measurements."
        )

    eta_squared = float(
        power_rm_anova(
            eta_squared=None,
            m=measurements,
            n=sample_size,
            power=power,
            alpha=alpha,
            corr=correlation,
            epsilon=epsilon,
        )
    )
    if not math.isfinite(eta_squared) or not 0 < eta_squared < 1:
        raise ValueError("A valid detectable effect could not be calculated.")
    effect_size = math.sqrt(eta_squared / (1 - eta_squared))
    magnitude = interpret_cohens_f(effect_size)
    reporting_text = (
        f"With N = {sample_size}, {measurements} repeated measurements, power = "
        f"{power:.0%}, alpha = {alpha:g}, average correlation = {correlation:.2f}, "
        f"and epsilon = {epsilon:.2f}, the minimum detectable effect is Cohen's "
        f"f = {effect_size:.2f} ({magnitude.lower()}), equivalent to eta-squared "
        f"= {eta_squared:.3f}."
    )
    return SensitivityResult(
        analysis_label="One-way repeated-measures ANOVA",
        effect_metric="Cohen's f",
        effect_size=effect_size,
        magnitude=magnitude,
        reporting_text=reporting_text,
        equivalent_eta_squared=eta_squared,
    )

"""Standalone, input-only statistical sensitivity calculator."""

from .calculator import (
    SensitivityResult,
    calculate_paired_ttest_sensitivity,
    calculate_rm_anova_sensitivity,
    interpret_cohens_d,
    interpret_cohens_f,
)
__all__ = (
    "SensitivityResult",
    "calculate_paired_ttest_sensitivity",
    "calculate_rm_anova_sensitivity",
    "interpret_cohens_d",
    "interpret_cohens_f",
)

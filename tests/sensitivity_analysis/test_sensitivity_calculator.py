from __future__ import annotations

import pytest

from Tools.Sensitivity_Analysis.calculator import (
    calculate_paired_ttest_sensitivity,
    calculate_rm_anova_sensitivity,
    interpret_cohens_d,
    interpret_cohens_f,
)


def test_paired_ttest_matches_reference_solution() -> None:
    result = calculate_paired_ttest_sensitivity(
        sample_size=24,
        power=0.80,
        alpha=0.05,
        alternative="two-sided",
    )

    assert result.effect_metric == "Cohen's dz"
    assert result.effect_size == pytest.approx(0.5971839033)
    assert result.magnitude == "Medium"
    assert result.equivalent_eta_squared is None
    assert "N = 24" in result.reporting_text


def test_rm_anova_returns_f_and_equivalent_eta_squared() -> None:
    result = calculate_rm_anova_sensitivity(
        sample_size=24,
        measurements=2,
        power=0.80,
        alpha=0.05,
        correlation=0.50,
        epsilon=1.0,
    )

    assert result.effect_metric == "Cohen's f"
    assert result.effect_size == pytest.approx(0.2985920501)
    assert result.equivalent_eta_squared == pytest.approx(0.0818589010)
    assert result.magnitude == "Medium"


@pytest.mark.parametrize(
    ("effect_size", "expected"),
    [
        (0.19, "Below small"),
        (0.20, "Small"),
        (0.50, "Medium"),
        (0.80, "Large"),
    ],
)
def test_cohens_d_interpretation_boundaries(
    effect_size: float,
    expected: str,
) -> None:
    assert interpret_cohens_d(effect_size) == expected


@pytest.mark.parametrize(
    ("effect_size", "expected"),
    [
        (0.09, "Below small"),
        (0.10, "Small"),
        (0.25, "Medium"),
        (0.40, "Large"),
    ],
)
def test_cohens_f_interpretation_boundaries(
    effect_size: float,
    expected: str,
) -> None:
    assert interpret_cohens_f(effect_size) == expected


def test_rm_anova_rejects_invalid_design_assumptions() -> None:
    with pytest.raises(ValueError, match="Average correlation"):
        calculate_rm_anova_sensitivity(
            sample_size=24,
            measurements=3,
            correlation=-0.50,
        )

    with pytest.raises(ValueError, match="Epsilon"):
        calculate_rm_anova_sensitivity(
            sample_size=24,
            measurements=4,
            epsilon=0.20,
        )

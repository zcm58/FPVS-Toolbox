from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from Tools.Stats.analysis.inference_contracts import (
    AnalysisProfile,
    AnalysisRunSpec,
    HarmonicProvenance,
)
from Tools.Stats.analysis.robust_tests import (
    ADAPTIVE_HARMONIC_WARNING,
    run_friedman_test,
    run_one_sample_trimmed_mean_test,
    run_one_sample_wilcoxon_test,
    run_two_group_trimmed_mean_test,
)


def _row(result):
    return result.results.iloc[0]


def _manual_trimmed_components(values: np.ndarray, trim: float):
    ordered = np.sort(np.asarray(values, dtype=float))
    n = len(ordered)
    g = int(np.floor(trim * n))
    h = n - (2 * g)
    trimmed_mean = np.mean(ordered[g : n - g])
    winsorized = ordered.copy()
    if g:
        winsorized[:g] = ordered[g]
        winsorized[n - g :] = ordered[n - g - 1]
    winsorized_variance = np.var(winsorized, ddof=(2 * g) + 1)
    return g, h, trimmed_mean, winsorized_variance


def test_one_sample_trimmed_mean_matches_manual_winsorized_formula():
    values = np.array([-8.0, 0.5, 1.0, 1.2, 1.5, 2.0, 2.4, 2.8, 3.0, 30.0])
    result = run_one_sample_trimmed_mean_test(values)
    row = _row(result)

    g, h, trimmed_mean, winsorized_variance = _manual_trimmed_components(values, 0.20)
    se = np.sqrt(winsorized_variance / h)
    statistic = trimmed_mean / se
    p_value = 2.0 * stats.t.sf(abs(statistic), h - 1)
    critical = stats.t.ppf(0.975, h - 1)

    assert row["estimation_status"] == "estimated"
    assert row["trimmed_each_tail"] == g
    assert row["effective_n"] == h
    assert row["location_estimate"] == pytest.approx(trimmed_mean)
    assert row["winsorized_variance"] == pytest.approx(winsorized_variance)
    assert row["standard_error"] == pytest.approx(se)
    assert row["statistic"] == pytest.approx(statistic)
    assert row["p_raw"] == pytest.approx(p_value)
    assert row["ci_low"] == pytest.approx(trimmed_mean - critical * se)
    assert row["ci_high"] == pytest.approx(trimmed_mean + critical * se)


def test_one_sample_wilcoxon_matches_scipy_and_records_rank_metadata():
    values = np.array([-2.0, -0.5, 0.0, 0.4, 1.1, 1.8, 2.6, 3.2])
    expected = stats.wilcoxon(
        values,
        zero_method="wilcox",
        correction=False,
        alternative="two-sided",
        method="auto",
    )

    row = _row(run_one_sample_wilcoxon_test(values))

    assert row["estimation_status"] == "estimated"
    assert row["statistic"] == pytest.approx(expected.statistic)
    assert row["p_raw"] == pytest.approx(expected.pvalue)
    assert row["zero_method"] == "wilcox"
    assert row["p_value_method_requested"] == "auto"
    assert -1.0 <= row["rank_biserial_correlation"] <= 1.0


def test_wilcoxon_rank_biserial_follows_declared_zero_method():
    values = np.array([-2.0, -0.5, 0.0, 0.0, 0.4, 1.1, 1.8, 2.6])

    wilcox = _row(run_one_sample_wilcoxon_test(values, zero_method="wilcox"))
    pratt = _row(run_one_sample_wilcoxon_test(values, zero_method="pratt"))
    zsplit = _row(run_one_sample_wilcoxon_test(values, zero_method="zsplit"))

    nonzero = values[values != 0.0]
    wilcox_ranks = stats.rankdata(np.abs(nonzero))
    wilcox_expected = (
        wilcox_ranks[nonzero > 0.0].sum()
        - wilcox_ranks[nonzero < 0.0].sum()
    ) / wilcox_ranks.sum()
    all_ranks = stats.rankdata(np.abs(values))
    pratt_positive = all_ranks[values > 0.0].sum()
    pratt_negative = all_ranks[values < 0.0].sum()
    pratt_expected = (pratt_positive - pratt_negative) / (
        pratt_positive + pratt_negative
    )
    half_zero = all_ranks[values == 0.0].sum() / 2.0
    zsplit_expected = (pratt_positive - pratt_negative) / (
        pratt_positive + pratt_negative + 2.0 * half_zero
    )
    assert wilcox["rank_biserial_correlation"] == pytest.approx(wilcox_expected)
    assert pratt["rank_biserial_correlation"] == pytest.approx(pratt_expected)
    assert zsplit["rank_biserial_correlation"] == pytest.approx(zsplit_expected)
    assert "zero_method=pratt" in pratt["rank_biserial_definition"]
    assert "zero_method=zsplit" in zsplit["rank_biserial_definition"]


def test_wilcoxon_effective_p_method_does_not_mislabel_tied_exact_request():
    values = np.array([-2.0, -0.5, 0.0, 0.4, 1.1, 1.8, 2.6, 3.2])

    exact = _row(
        run_one_sample_wilcoxon_test(values, p_value_method="exact")
    )
    automatic = _row(run_one_sample_wilcoxon_test(values))
    asymptotic = _row(
        run_one_sample_wilcoxon_test(values, p_value_method="approx")
    )

    assert exact["p_value_method_requested"] == "exact"
    assert exact["p_value_method_effective"] == (
        "conservative_discrete_reference"
    )
    assert not bool(exact["p_value_exact"])
    assert "prevent an exact" in exact["p_value_method_note"]
    assert automatic["p_value_method_effective"] == "exact_sign_permutation"
    assert bool(automatic["p_value_exact"])
    assert asymptotic["p_value_method_effective"] == "asymptotic"
    assert not bool(asymptotic["p_value_exact"])


def test_two_group_trimmed_mean_matches_scipy_yuen_unequal_variance():
    group_a = np.array([-20.0, 0.5, 1.0, 1.2, 1.8, 2.1, 2.7, 3.0, 3.4, 40.0])
    group_b = np.array([-10.0, -1.0, -0.4, 0.1, 0.3, 0.8, 1.0, 1.1, 1.5, 15.0])
    expected = stats.ttest_ind(
        group_a,
        group_b,
        equal_var=False,
        trim=0.20,
        alternative="two-sided",
    )

    row = _row(
        run_two_group_trimmed_mean_test(
            group_a,
            group_b,
            group_a_label="anxious",
            group_b_label="non_anxious",
        )
    )

    assert row["estimation_status"] == "estimated"
    assert row["statistic"] == pytest.approx(expected.statistic)
    assert row["degrees_of_freedom"] == pytest.approx(expected.df)
    assert row["p_raw"] == pytest.approx(expected.pvalue)
    assert row["estimate"] > 0.0
    assert row["sign_convention"] == "positive means anxious > non_anxious"


def test_friedman_matches_scipy_and_exports_kendalls_w():
    matrix = np.array(
        [
            [1.0, 2.0, 4.0],
            [2.0, 3.5, 5.0],
            [1.5, 2.5, 4.2],
            [2.4, 2.1, 3.9],
            [0.8, 1.8, 3.0],
        ]
    )
    data = pd.DataFrame(
        [
            {"participant": f"P{subject}", "condition": level, "response": value}
            for subject, row in enumerate(matrix, start=1)
            for level, value in zip(("A", "B", "C"), row, strict=True)
        ]
    )
    expected = stats.friedmanchisquare(*matrix.T)

    result = run_friedman_test(
        data,
        value_col="response",
        subject_col="participant",
        level_col="condition",
        levels=("A", "B", "C"),
    )
    row = _row(result)

    assert row["estimation_status"] == "estimated"
    assert row["statistic"] == pytest.approx(expected.statistic)
    assert row["p_raw"] == pytest.approx(expected.pvalue)
    assert row["degrees_of_freedom"] == 2
    assert row["kendalls_w"] == pytest.approx(expected.statistic / (5 * 2))
    assert row["n_complete_participants"] == 5
    assert row["approximation_reliability_status"] == "caution_small_design"
    assert "more than 10 participants" in row["approximation_caveat"]


@pytest.mark.parametrize(
    ("runner", "values", "expected_code"),
    [
        (run_one_sample_trimmed_mean_test, [1.0], "insufficient_finite_n"),
        (run_one_sample_trimmed_mean_test, [0.0] * 8, "all_zero_differences"),
        (run_one_sample_wilcoxon_test, [0.0] * 8, "all_zero_differences"),
        (run_one_sample_wilcoxon_test, [0.0, 0.0, 1.0, -1.0], "insufficient_nonzero_n"),
    ],
)
def test_one_sample_edge_cases_are_explicitly_not_estimable(runner, values, expected_code):
    result = runner(values)
    row = _row(result)

    assert row["estimation_status"] == "not_estimable"
    assert row["status_code"] == expected_code
    assert not bool(row["estimable"])
    assert not np.isinf(result.results.select_dtypes("number")).any().any()


def test_two_group_tiny_and_constant_inputs_are_not_estimable():
    tiny = _row(run_two_group_trimmed_mean_test([1.0, 2.0], [2.0, 3.0, 4.0]))
    constant = _row(run_two_group_trimmed_mean_test([1.0] * 8, [1.0] * 8))

    assert tiny["status_code"] == "insufficient_group_n"
    assert constant["status_code"] == "constant_input"
    assert not bool(tiny["estimable"])
    assert not bool(constant["estimable"])


def test_friedman_insufficient_levels_duplicates_and_constant_are_not_estimable():
    two_levels = pd.DataFrame(
        {
            "participant": ["P1", "P1", "P2", "P2", "P3", "P3"],
            "condition": ["A", "B"] * 3,
            "response": [1.0, 2.0, 2.0, 3.0, 3.0, 4.0],
        }
    )
    duplicate = pd.concat(
        [
            pd.DataFrame(
                {
                    "participant": ["P1", "P1", "P1", "P2", "P2", "P2", "P3", "P3", "P3"],
                    "condition": ["A", "B", "C"] * 3,
                    "response": np.arange(9, dtype=float),
                }
            ),
            pd.DataFrame([{"participant": "P1", "condition": "A", "response": 2.0}]),
        ],
        ignore_index=True,
    )
    constant = pd.DataFrame(
        {
            "participant": np.repeat(["P1", "P2", "P3"], 3),
            "condition": ["A", "B", "C"] * 3,
            "response": 1.0,
        }
    )

    assert (
        _row(
            run_friedman_test(
                two_levels,
                value_col="response",
                subject_col="participant",
                level_col="condition",
            )
        )["status_code"]
        == "insufficient_factor_levels"
    )
    assert (
        _row(
            run_friedman_test(
                duplicate,
                value_col="response",
                subject_col="participant",
                level_col="condition",
            )
        )["status_code"]
        == "duplicate_subject_level_cells"
    )
    assert (
        _row(
            run_friedman_test(
                constant,
                value_col="response",
                subject_col="participant",
                level_col="condition",
            )
        )["status_code"]
        == "constant_input"
    )


def test_friedman_invalid_factor_identifiers_are_not_silently_analyzed():
    data = pd.DataFrame(
        {
            "participant": ["P1", "P1", "P1", " ", "P2", "P2", "P3", "P3", "P3"],
            "condition": ["A", "B", "C"] * 3,
            "response": np.arange(9, dtype=float),
        }
    )

    row = _row(
        run_friedman_test(
            data,
            value_col="response",
            subject_col="participant",
            level_col="condition",
        )
    )

    assert row["status_code"] == "invalid_subject_or_level_identifier"
    assert row["n_invalid_identifier_rows"] == 1


def test_adaptive_harmonic_provenance_is_exported_as_exploratory():
    run_spec = AnalysisRunSpec(
        profile=AnalysisProfile.CONFIRMATORY,
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )

    result = run_one_sample_trimmed_mean_test(
        [-2.0, 0.5, 1.0, 1.3, 1.7, 2.4, 5.0],
        run_spec=run_spec,
    )
    row = _row(result)
    frames = result.to_frames()

    assert row["harmonic_provenance"] == "same_sample_adaptive"
    assert row["inference_status"] == "exploratory_post_selection_sensitivity"
    assert not bool(row["method_selected_by_shapiro"])
    assert frames["Warnings"].iloc[0]["warning"] == ADAPTIVE_HARMONIC_WARNING
    assert frames["Test Inventory"].iloc[0]["role"] == "sensitivity"
    assert frames["Run Metadata"].iloc[0]["response_inference_status"] == ("exploratory_post_selection")


def test_run_spec_alpha_is_used_when_test_alpha_is_not_overridden():
    run_spec = AnalysisRunSpec(
        profile=AnalysisProfile.PUBLISHED_STYLE_EXPLORATORY,
        harmonic_provenance=HarmonicProvenance.INDEPENDENTLY_SELECTED,
        alpha=0.01,
    )

    row = _row(
        run_one_sample_trimmed_mean_test(
            [-3.0, 0.2, 0.8, 1.1, 1.5, 1.9, 3.0],
            run_spec=run_spec,
        )
    )

    assert row["alpha"] == pytest.approx(0.01)
    assert row["confidence_level"] == pytest.approx(0.99)


def test_explicit_alpha_and_alternative_match_exported_run_metadata():
    result = run_one_sample_trimmed_mean_test(
        [-3.0, 0.2, 0.8, 1.1, 1.5, 1.9, 3.0],
        alpha=0.01,
        alternative="greater",
    )

    row = _row(result)
    run_metadata = result.to_frames()["Run Metadata"].iloc[0]
    assert row["alpha"] == pytest.approx(0.01)
    assert row["alternative"] == "greater"
    assert run_metadata["alpha"] == pytest.approx(0.01)
    assert run_metadata["response_alternative"] == "greater"


def test_nonfinite_values_are_excluded_and_reported_without_method_switching():
    result = run_one_sample_trimmed_mean_test([-2.0, 0.0, 1.0, 2.0, 4.0, np.nan, np.inf, "bad"])
    row = _row(result)

    assert row["n_input"] == 8
    assert row["n_finite"] == 5
    assert row["n_excluded_invalid_or_nonfinite"] == 3
    assert not bool(row["method_selected_by_shapiro"])
    assert "Shapiro-Wilk diagnostics do not select" in row["note"]


def test_boolean_and_complex_flags_are_not_coerced_to_response_values():
    result = run_one_sample_trimmed_mean_test(
        [True, False, 1.0, 2.0, 3.0, 4.0, 1 + 0j]
    )
    row = _row(result)

    assert row["n_input"] == 7
    assert row["n_finite"] == 4
    assert row["n_excluded_invalid_or_nonfinite"] == 3
    assert row["location_estimate"] == pytest.approx(2.5)


def test_scalar_and_matrix_inputs_are_rejected_instead_of_silently_flattened():
    with pytest.raises(ValueError, match="one-dimensional"):
        run_one_sample_trimmed_mean_test(1.0)
    with pytest.raises(ValueError, match="one-dimensional"):
        run_two_group_trimmed_mean_test([[1.0, 2.0], [3.0, 4.0]], [1, 2, 3])


def test_invalid_run_spec_fails_with_the_declared_type_error() -> None:
    with pytest.raises(TypeError, match="AnalysisRunSpec"):
        run_one_sample_trimmed_mean_test(
            [1.0, 2.0, 3.0],
            run_spec=object(),  # type: ignore[arg-type]
        )

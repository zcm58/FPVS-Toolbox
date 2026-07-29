from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.diagnostics import (
    DiagnosticStatus,
    adjust_shapiro_family,
    build_confidence_interval_diagnostic,
    build_group_cell_diagnostics,
    build_influence_diagnostics,
    build_model_fit_diagnostics,
    build_residual_diagnostics,
    build_shapiro_diagnostic,
    coerce_finite_values,
    diagnostics_to_frame,
)


def test_finite_value_coercion_counts_each_invalid_class() -> None:
    summary = coerce_finite_values(
        [1, "2.5", None, np.nan, np.inf, "-inf", "not-a-number", True, 1 + 0j]
    )

    assert summary.values == (1.0, 2.5)
    assert summary.n_total == 9
    assert summary.n_finite == 2
    assert summary.n_missing == 2
    assert summary.n_nonfinite == 2
    assert summary.n_invalid == 3


def test_shapiro_tiny_n_and_zero_variance_are_not_estimable() -> None:
    tiny = build_shapiro_diagnostic([1.0, 2.0])
    constant = build_shapiro_diagnostic([4.0, 4.0, 4.0, 4.0])

    assert tiny.status is DiagnosticStatus.NOT_ESTIMABLE
    assert tiny.code == "tiny_n"
    assert tiny.p_raw is None
    assert constant.status is DiagnosticStatus.NOT_ESTIMABLE
    assert constant.code == "zero_variance"
    assert constant.p_raw is None


def test_group_cell_builder_keeps_nonfinite_exclusion_as_explicit_row() -> None:
    data = pd.DataFrame(
        {
            "group": ["A"] * 6,
            "condition": ["Face"] * 6,
            "roi": ["Right"] * 6,
            "value": [0.2, 0.4, np.inf, 0.5, 0.7, 0.9],
        }
    )

    result = build_group_cell_diagnostics(
        data,
        value_col="value",
        correction="holm",
    )

    integrity = result[result["check"] == "data_integrity"].iloc[0]
    shapiro = result[result["check"] == "normality_shapiro"].iloc[0]
    assert integrity["status"] == "diagnostic"
    assert integrity["code"] == "nonfinite_values_excluded"
    assert integrity["n_nonfinite"] == 1
    assert shapiro["status"] in {"estimable", "diagnostic"}
    assert np.isfinite(float(shapiro["p_raw"]))
    assert np.isfinite(float(shapiro["p_adjusted"]))
    assert shapiro["adjustment_method"] == "holm"
    assert shapiro["adjustment_family"] == "group_cell_normality"
    assert result["automatic_test_switching"].eq(False).all()
    assert result["diagnostic_schema_version"].eq(1).all()
    assert result.attrs["automatic_test_switching"] is False


def test_shapiro_family_adjustment_preserves_raw_p_and_marks_metadata() -> None:
    records = (
        build_shapiro_diagnostic(
            [-2.0, -1.0, -0.7, -0.2, 0.1, 0.4, 0.8, 1.1],
            context={"condition": "A"},
        ),
        build_shapiro_diagnostic(
            [-3.0, -0.3, -0.2, -0.1, 0.0, 0.1, 0.2, 4.0],
            context={"condition": "B"},
        ),
    )

    adjusted = adjust_shapiro_family(
        records,
        method="holm",
        family="all_condition_cells",
    )

    for before, after in zip(records, adjusted):
        assert after.p_raw == before.p_raw
        assert after.p_adjusted is not None
        assert after.adjustment_method == "holm"
        assert after.adjustment_family == "all_condition_cells"
        assert after.reject_raw == before.reject_raw
        assert after.reject_adjusted in {True, False}


def test_confidence_interval_failures_are_explicit_rows() -> None:
    nonfinite = build_confidence_interval_diagnostic(
        ci_low=np.nan,
        ci_high=1.0,
        estimate=0.5,
    )
    reversed_interval = build_confidence_interval_diagnostic(
        ci_low=2.0,
        ci_high=1.0,
        estimate=1.5,
    )
    outside = build_confidence_interval_diagnostic(
        ci_low=0.0,
        ci_high=1.0,
        estimate=1.5,
    )

    assert (nonfinite.status.value, nonfinite.code) == (
        "not_estimable",
        "invalid_ci_nonfinite",
    )
    assert (reversed_interval.status.value, reversed_interval.code) == (
        "not_estimable",
        "invalid_ci_order",
    )
    assert (outside.status.value, outside.code) == (
        "diagnostic",
        "estimate_outside_ci",
    )


def test_model_fit_statuses_are_explicit_and_serializable() -> None:
    failed = build_model_fit_diagnostics(
        model_name="group_condition_roi",
        converged=False,
        fit_error="optimizer_error",
    )
    invalid = build_model_fit_diagnostics(
        model_name="group_condition_roi",
        converged="maybe",
        singular="unknown",
    )
    singular = build_model_fit_diagnostics(
        model_name="group_condition_roi",
        converged=True,
        singular=True,
    )

    assert len(failed) == 1
    assert failed[0].status is DiagnosticStatus.NOT_ESTIMABLE
    assert failed[0].code == "model_fit_failed"
    assert invalid[0].code == "invalid_convergence_status"
    assert invalid[1].code == "singularity_unknown"
    assert singular[0].code == "converged"
    assert singular[1].code == "singular_fit"

    frame = diagnostics_to_frame([*failed, *invalid, *singular])
    serialized = json.loads(frame.to_json(orient="records"))
    assert len(serialized) == 5
    assert {row["model"] for row in serialized} == {"group_condition_roi"}
    assert frame.attrs["diagnostic_schema_version"] == 1
    assert frame.attrs["automatic_test_switching"] is False


def test_group_cell_frame_has_one_diagnostic_set_per_observed_cell() -> None:
    data = pd.DataFrame(
        {
            "group_id": ["anxious"] * 4 + ["non_anxious"] * 4,
            "condition": ["Angry"] * 8,
            "roi": ["Central"] * 8,
            "value": [0.1, 0.3, 0.2, 0.4, 0.2, 0.5, 0.4, 0.7],
        }
    )

    result = build_group_cell_diagnostics(
        data,
        value_col="value",
        group_cols=("group_id", "condition", "roi"),
    )

    assert len(result) == 8
    assert set(result["check"]) == {
        "data_integrity",
        "sample_size",
        "variance",
        "normality_shapiro",
    }
    assert set(result["group_id"]) == {"anxious", "non_anxious"}
    assert result["group_columns"].eq("group_id,condition,roi").all()
    assert result["normality_adjustment_method"].isna().all()
    assert result.attrs["group_columns"] == "group_id,condition,roi"
    assert result.attrs["normality_adjustment_method"] is None


def test_residual_diagnostics_are_report_only_and_flag_extreme_tails() -> None:
    residuals = [-0.2, -0.1, 0.0, 0.1, 0.15, 0.2, 4.0]
    result = build_residual_diagnostics(
        residuals,
        standardized_threshold=2.0,
        context={"model": "group_condition_roi"},
    )

    extremes = result[result["check"] == "residual_extremes"].iloc[0]
    normality = result[
        result["check"] == "residual_normality_shapiro"
    ].iloc[0]
    assert extremes["status"] == "diagnostic"
    assert extremes["code"] == "extreme_residuals_present"
    assert extremes["flagged_count"] == 1
    assert normality["p_raw"] is not None
    assert result["automatic_test_switching"].eq(False).all()
    assert result["normality_role"].eq("diagnostic_only").all()


def test_residual_and_influence_non_estimability_remain_explicit() -> None:
    constant = build_residual_diagnostics([1.0, 1.0, 1.0])
    influence = build_influence_diagnostics(
        {"P01": 0.1, "P02": 1.5, "P03": np.nan},
        threshold=1.0,
    )

    extremes = constant[constant["check"] == "residual_extremes"].iloc[0]
    by_participant = influence.set_index("participant_id")
    assert extremes["status"] == "not_estimable"
    assert extremes["code"] == "zero_variance"
    assert by_participant.loc["P01", "code"] == "within_threshold"
    assert by_participant.loc["P02", "code"] == "influential_participant"
    assert by_participant.loc["P03", "status"] == "not_estimable"
    assert influence["automatic_exclusion"].eq(False).all()


@pytest.mark.parametrize("threshold", [np.nan, np.inf, 0.0, -1.0])
def test_residual_threshold_must_be_finite_and_positive(threshold: float) -> None:
    with pytest.raises(ValueError, match="finite and positive"):
        build_residual_diagnostics(
            [-1.0, 0.0, 1.0],
            standardized_threshold=threshold,
        )

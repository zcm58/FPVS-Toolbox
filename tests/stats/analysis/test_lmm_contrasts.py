from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest
from statsmodels.formula.api import mixedlm

from Tools.Stats.analysis.lmm_contrasts import (
    CONTRAST_METHOD_LABEL,
    WALD_METHOD_LABEL,
    estimate_condition_within_roi_contrasts,
    estimate_group_cell_contrasts,
    estimate_marginal_group_contrasts,
    estimate_roi_within_condition_contrasts,
)
from Tools.Stats.common.blas_limits import single_threaded_blas


def _single_group_data() -> pd.DataFrame:
    rng = np.random.default_rng(20260729)
    rows: list[dict[str, object]] = []
    for participant_index in range(24):
        participant = f"p{participant_index + 1:02d}"
        participant_effect = float(rng.normal(0.0, 0.9))
        for condition in ("faces", "objects"):
            for roi in ("left", "right"):
                condition_effect = 2.0 if condition == "faces" else 0.0
                roi_effect = 1.0 if roi == "right" else 0.0
                interaction = 3.0 if (condition, roi) == ("faces", "right") else 0.0
                rows.append(
                    {
                        "participant_id": participant,
                        "condition": condition,
                        "roi": roi,
                        "value": (
                            10.0
                            + participant_effect
                            + condition_effect
                            + roi_effect
                            + interaction
                            + float(rng.normal(0.0, 0.08))
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _multi_group_data() -> pd.DataFrame:
    rng = np.random.default_rng(260729)
    rows: list[dict[str, object]] = []
    participant_effects = rng.normal(0.0, 0.75, size=18)
    participant_effects -= participant_effects.mean()
    for group in ("anxious", "control"):
        for participant_index in range(18):
            participant = f"{group}_{participant_index + 1:02d}"
            participant_effect = float(participant_effects[participant_index])
            for condition in ("faces", "objects"):
                for roi in ("left", "right"):
                    group_effect = 0.0
                    if group == "anxious":
                        group_effect = 0.5
                        if condition == "faces":
                            group_effect += 0.8
                        if roi == "right":
                            group_effect += 0.4
                        if (condition, roi) == ("faces", "right"):
                            group_effect += 0.6
                    rows.append(
                        {
                            "participant_id": participant,
                            "group_id": group,
                            "condition": condition,
                            "roi": roi,
                            "value": (
                                8.0
                                + participant_effect
                                + (0.3 if condition == "faces" else 0.0)
                                + (0.2 if roi == "right" else 0.0)
                                + group_effect
                                + float(rng.normal(0.0, 0.08))
                            ),
                        }
                    )
    data = pd.DataFrame(rows)
    missing = (
        (data["participant_id"].eq("anxious_01"))
        & data["condition"].eq("faces")
        & data["roi"].eq("right")
    ) | (
        (data["participant_id"].eq("control_02"))
        & data["condition"].eq("objects")
        & data["roi"].eq("left")
    )
    return data.loc[~missing].reset_index(drop=True)


def _fit(formula: str, data: pd.DataFrame):
    with warnings.catch_warnings(), single_threaded_blas():
        warnings.simplefilter("ignore")
        return mixedlm(
            formula,
            data=data,
            groups=data["participant_id"],
            re_formula="1",
        ).fit(reml=True, method="powell", disp=False)


@pytest.fixture(scope="module")
def single_fit_and_data():
    data = _single_group_data()
    result = _fit(
        "value ~ C(condition, Sum) * C(roi, Sum)",
        data,
    )
    return result, data


@pytest.fixture(scope="module")
def multi_fit_and_data():
    data = _multi_group_data()
    result = _fit(
        "value ~ C(group_id, Sum) * C(condition, Sum) * C(roi, Sum)",
        data,
    )
    return result, data


def test_single_group_simple_contrasts_match_known_fixed_effects(
    single_fit_and_data,
) -> None:
    result, data = single_fit_and_data

    condition = estimate_condition_within_roi_contrasts(result, data).set_index("roi")
    roi = estimate_roi_within_condition_contrasts(
        result,
        data,
        roi_pairs=(("right", "left"),),
    ).set_index("condition")

    assert condition.loc["left", "estimate"] == pytest.approx(2.0, abs=0.08)
    assert condition.loc["right", "estimate"] == pytest.approx(5.0, abs=0.08)
    assert roi.loc["objects", "estimate"] == pytest.approx(1.0, abs=0.08)
    assert roi.loc["faces", "estimate"] == pytest.approx(4.0, abs=0.08)
    assert condition["status"].eq("estimated").all()
    assert roi["status"].eq("estimated").all()


def test_contrasts_report_wald_method_estimand_sign_and_coverage(
    single_fit_and_data,
) -> None:
    result, data = single_fit_and_data

    contrasts = estimate_condition_within_roi_contrasts(result, data)

    assert contrasts["method_label"].eq(CONTRAST_METHOD_LABEL).all()
    assert contrasts["inference_method"].eq(WALD_METHOD_LABEL).all()
    assert contrasts["alternative"].eq("two-sided").all()
    assert contrasts["contrast_sign"].eq("faces - objects").all()
    assert contrasts["estimand"].str.contains("Equal-weight").all()
    assert contrasts["coverage"].str.endswith("no imputation").all()
    assert contrasts["missing_values_imputed"].eq(False).all()
    assert np.isfinite(
        contrasts[
            ["estimate", "std_error", "ci_low", "ci_high", "z_value", "p_raw"]
        ].to_numpy()
    ).all()


def test_single_group_contrasts_retain_available_rows_without_imputation() -> None:
    data = _single_group_data()
    missing = (
        data["participant_id"].eq("p01")
        & data["condition"].eq("faces")
        & data["roi"].eq("right")
    )
    available = data.loc[~missing].reset_index(drop=True)
    result = _fit(
        "value ~ C(condition, Sum) * C(roi, Sum)",
        available,
    )

    contrasts = estimate_condition_within_roi_contrasts(
        result,
        available,
    ).set_index("roi")

    assert len(available) == len(data) - 1
    assert contrasts["status"].eq("estimated").all()
    assert contrasts.loc["right", "n_comparison_participants"] == 23
    assert contrasts.loc["right", "n_reference_participants"] == 24
    assert contrasts["missing_values_imputed"].eq(False).all()


def test_group_cell_contrasts_use_available_rows_without_imputation(
    multi_fit_and_data,
) -> None:
    result, data = multi_fit_and_data

    contrasts = estimate_group_cell_contrasts(
        result,
        data,
        group_a="anxious",
        group_b="control",
    ).set_index(["condition", "roi"])

    expected = {
        ("objects", "left"): 0.5,
        ("objects", "right"): 0.9,
        ("faces", "left"): 1.3,
        ("faces", "right"): 2.3,
    }
    for cell, estimate in expected.items():
        assert contrasts.loc[cell, "estimate"] == pytest.approx(estimate, abs=0.1)
    assert contrasts["status"].eq("estimated").all()
    assert contrasts.loc[("faces", "right"), "n_comparison_participants"] == 17
    assert contrasts.loc[("faces", "right"), "n_reference_participants"] == 18
    assert contrasts.loc[("objects", "left"), "n_reference_participants"] == 17
    assert contrasts["missing_values_imputed"].eq(False).all()


def test_reversing_group_order_flips_estimate_and_ci_not_p_value(
    multi_fit_and_data,
) -> None:
    result, data = multi_fit_and_data
    forward = estimate_group_cell_contrasts(
        result,
        data,
        group_a="anxious",
        group_b="control",
    ).sort_values(["condition", "roi"], ignore_index=True)
    reverse = estimate_group_cell_contrasts(
        result,
        data,
        group_a="control",
        group_b="anxious",
    ).sort_values(["condition", "roi"], ignore_index=True)

    np.testing.assert_allclose(reverse["estimate"], -forward["estimate"])
    np.testing.assert_allclose(reverse["ci_low"], -forward["ci_high"])
    np.testing.assert_allclose(reverse["ci_high"], -forward["ci_low"])
    np.testing.assert_allclose(reverse["p_raw"], forward["p_raw"])
    assert forward["contrast_sign"].eq("anxious - control").all()
    assert reverse["contrast_sign"].eq("control - anxious").all()


def test_marginal_group_contrast_is_equal_weight_average_of_cells(
    multi_fit_and_data,
) -> None:
    result, data = multi_fit_and_data
    cells = estimate_group_cell_contrasts(
        result,
        data,
        group_a="anxious",
        group_b="control",
    )
    by_condition = estimate_marginal_group_contrasts(
        result,
        data,
        group_a="anxious",
        group_b="control",
        by="condition",
    ).set_index("condition")

    for condition, cell_rows in cells.groupby("condition", observed=True):
        assert by_condition.loc[condition, "estimate"] == pytest.approx(
            cell_rows["estimate"].mean()
        )
    assert by_condition["required_cell_count"].eq(4).all()


def test_structurally_empty_group_cell_is_explicitly_nonestimable(
    multi_fit_and_data,
) -> None:
    result, data = multi_fit_and_data
    structurally_empty = data.loc[
        ~(
            data["group_id"].eq("anxious")
            & data["condition"].eq("faces")
            & data["roi"].eq("right")
        )
    ].copy()

    contrasts = estimate_group_cell_contrasts(
        result,
        structurally_empty,
        group_a="anxious",
        group_b="control",
    ).set_index(["condition", "roi"])
    empty = contrasts.loc[("faces", "right")]

    assert empty["status"] == "not_estimable"
    assert not bool(empty["reportable"])
    assert np.isnan(empty["estimate"])
    assert "group_id=anxious" in empty["structurally_missing_cells"]
    assert "structurally non-estimable" in empty["error"]
    assert empty["method_label"] == CONTRAST_METHOD_LABEL
    assert contrasts.drop(index=("faces", "right"))["status"].eq("estimated").all()

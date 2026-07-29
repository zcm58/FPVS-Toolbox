from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.group_comparisons import (
    GroupComparisonError,
    run_group_cell_comparisons,
)


def _frame(
    group_a: list[float],
    group_b: list[float],
    *,
    condition: str = "Faces",
    roi: str = "Occipital",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, value in enumerate(group_a):
        rows.append(
            {
                "participant": f"A{index + 1}",
                "group_id": "anxious",
                "condition": condition,
                "roi": roi,
                "value": value,
            }
        )
    for index, value in enumerate(group_b):
        rows.append(
            {
                "participant": f"N{index + 1}",
                "group_id": "non_anxious",
                "condition": condition,
                "roi": roi,
                "value": value,
            }
        )
    return pd.DataFrame(rows)


def test_welch_values_match_scipy_and_manual_interval() -> None:
    anxious = [1.2, 1.7, 2.1, 2.4, 2.8]
    non_anxious = [0.2, 0.5, 0.7, 1.0, 1.4, 1.9, 2.5]
    result = run_group_cell_comparisons(
        _frame(anxious, non_anxious),
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        group_pair=("anxious", "non_anxious"),
    )
    row = result.contrasts.iloc[0]
    scipy_result = stats.ttest_ind(anxious, non_anxious, equal_var=False)
    var_a = np.var(anxious, ddof=1)
    var_b = np.var(non_anxious, ddof=1)
    se2 = var_a / len(anxious) + var_b / len(non_anxious)
    manual_df = se2**2 / (
        (var_a / len(anxious)) ** 2 / (len(anxious) - 1)
        + (var_b / len(non_anxious)) ** 2 / (len(non_anxious) - 1)
    )

    assert row["welch_t"] == pytest.approx(float(scipy_result.statistic))
    assert row["p_raw"] == pytest.approx(float(scipy_result.pvalue))
    assert row["welch_df"] == pytest.approx(manual_df)
    assert row["mean_difference_a_minus_b"] == pytest.approx(
        np.mean(anxious) - np.mean(non_anxious)
    )
    assert row["ci_difference_low"] < row["mean_difference_a_minus_b"]
    assert row["ci_difference_high"] > row["mean_difference_a_minus_b"]


def test_hedges_g_sign_follows_declared_group_order() -> None:
    data = _frame(
        [2.0, 2.2, 2.4, 2.8],
        [0.2, 0.4, 0.5, 0.8, 1.0],
    )
    forward = run_group_cell_comparisons(
        data,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        group_pair=("anxious", "non_anxious"),
    ).contrasts.iloc[0]
    reverse = run_group_cell_comparisons(
        data,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        group_pair=("non_anxious", "anxious"),
    ).contrasts.iloc[0]

    assert forward["mean_difference_a_minus_b"] > 0
    assert forward["hedges_g"] > 0
    assert reverse["mean_difference_a_minus_b"] == pytest.approx(
        -forward["mean_difference_a_minus_b"]
    )
    assert reverse["hedges_g"] == pytest.approx(-forward["hedges_g"])


def test_global_holm_family_spans_all_condition_roi_cells() -> None:
    pieces = []
    for condition_index, condition in enumerate(("A", "B")):
        for roi_index, roi in enumerate(("R1", "R2")):
            pieces.append(
                _frame(
                    [
                        1.0 + condition_index + roi_index + offset
                        for offset in (0.0, 0.1, 0.3, 0.4)
                    ],
                    [
                        0.2 + condition_index * 0.1 + offset
                        for offset in (0.0, 0.2, 0.5, 0.7, 0.9)
                    ],
                    condition=condition,
                    roi=roi,
                )
            )
    data = pd.concat(pieces, ignore_index=True)
    # Participant IDs are intentionally reused across cells, as in repeated data.
    result = run_group_cell_comparisons(
        data,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        group_pair=("anxious", "non_anxious"),
    )
    contrasts = result.contrasts
    expected = multipletests(contrasts["p_raw"], method="holm")[1]

    assert len(contrasts) == 4
    assert contrasts["family_id"].eq("group_core_cells").all()
    assert contrasts["family_size"].eq(4).all()
    assert contrasts["adjustment_method"].eq("holm").all()
    np.testing.assert_allclose(contrasts["p_adjusted"], expected)


def test_missing_group_assignment_and_duplicate_grain_hard_fail() -> None:
    data = _frame([1.0, 1.2, 1.4], [0.4, 0.6, 0.8])
    missing = data.copy()
    missing.loc[0, "group_id"] = None
    duplicated = pd.concat([data, data.iloc[[0]]], ignore_index=True)

    with pytest.raises(GroupComparisonError, match="missing or unknown"):
        run_group_cell_comparisons(
            missing,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )
    with pytest.raises(GroupComparisonError, match="Duplicate participant"):
        run_group_cell_comparisons(
            duplicated,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )


def test_more_than_two_groups_requires_explicit_pair() -> None:
    data = _frame([1.0, 1.2, 1.4], [0.4, 0.6, 0.8])
    third = pd.DataFrame(
        {
            "participant": ["T1", "T2", "T3"],
            "group_id": ["third"] * 3,
            "condition": ["Faces"] * 3,
            "roi": ["Occipital"] * 3,
            "value": [0.1, 0.3, 0.5],
        }
    )
    data = pd.concat([data, third], ignore_index=True)

    with pytest.raises(GroupComparisonError, match="Exactly two"):
        run_group_cell_comparisons(
            data,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )
    selected = run_group_cell_comparisons(
        data,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        group_pair=("anxious", "third"),
    )
    assert selected.metadata.loc[0, "group_a"] == "anxious"
    assert selected.metadata.loc[0, "group_b"] == "third"


def test_complete_core_is_validated_and_available_case_is_labelled() -> None:
    complete = pd.concat(
        [
            _frame(
                [1.0, 1.2, 1.4],
                [0.4, 0.6, 0.8],
                condition=condition,
            )
            for condition in ("Faces", "Objects")
        ],
        ignore_index=True,
    )
    incomplete = complete[
        ~(
            complete["participant"].eq("A1")
            & complete["condition"].eq("Objects")
        )
    ].copy()

    with pytest.raises(GroupComparisonError, match="Complete-core"):
        run_group_cell_comparisons(
            incomplete,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )

    result = run_group_cell_comparisons(
        incomplete,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        analysis_scope="available_case",
    )
    assert result.metadata.loc[0, "analysis_scope"] == "available_case"


def test_tiny_and_zero_variance_cells_remain_non_estimable_without_infinity() -> None:
    tiny = _frame([1.0], [0.5, 0.7, 0.8])
    constant = _frame([1.0, 1.0, 1.0], [0.0, 0.0, 0.0])

    tiny_row = run_group_cell_comparisons(
        tiny,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
    ).contrasts.iloc[0]
    constant_row = run_group_cell_comparisons(
        constant,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
    ).contrasts.iloc[0]

    assert tiny_row["status_code"] == "insufficient_group_n"
    assert constant_row["status_code"] == "zero_or_invalid_standard_error"
    numeric = pd.DataFrame([tiny_row, constant_row])[
        ["welch_t", "welch_df", "p_raw", "hedges_g"]
    ].to_numpy(dtype=float)
    assert not np.isinf(numeric).any()
    assert not bool(tiny_row["reject_adjusted"])
    assert not bool(constant_row["reject_adjusted"])


def test_result_bundle_contains_explicit_diagnostics_and_metadata_frames() -> None:
    result = run_group_cell_comparisons(
        _frame([1.0, 1.3, 1.7], [0.4, 0.6, 0.9]),
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
    )

    frames = result.to_frames()
    assert set(frames) == {
        "Group Cell Contrasts",
        "Group Cell Diagnostics",
        "Group Comparison Metadata",
    }
    assert not frames["Group Cell Diagnostics"].empty
    assert frames["Group Comparison Metadata"].loc[
        0, "group_comparison_schema_version"
    ] == 1
    assert "group_a minus group_b" in frames["Group Comparison Metadata"].loc[
        0, "sign_convention"
    ]

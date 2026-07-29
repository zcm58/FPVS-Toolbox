from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scipy import stats

from Tools.Stats.analysis.stability import (
    StabilityAnalysisError,
    run_one_sample_leave_one_out_stability,
    run_two_group_leave_one_out_stability,
)


def _one_sample_frame(
    values_by_participant: dict[str, float],
    *,
    conditions: tuple[str, ...] = ("Faces",),
    rois: tuple[str, ...] = ("Occipital",),
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "participant": participant,
                "condition": condition,
                "roi": roi,
                "value": value + condition_index * 0.2 + roi_index * 0.1,
            }
            for participant, value in values_by_participant.items()
            for condition_index, condition in enumerate(conditions)
            for roi_index, roi in enumerate(rois)
        ]
    )


def _group_frame(
    group_a: list[float],
    group_b: list[float],
    *,
    conditions: tuple[str, ...] = ("Faces",),
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for condition_index, condition in enumerate(conditions):
        for index, value in enumerate(group_a):
            rows.append(
                {
                    "participant": f"A{index + 1}",
                    "group_id": "anxious",
                    "condition": condition,
                    "roi": "Occipital",
                    "value": value + condition_index * 0.1,
                }
            )
        for index, value in enumerate(group_b):
            rows.append(
                {
                    "participant": f"N{index + 1}",
                    "group_id": "non_anxious",
                    "condition": condition,
                    "roi": "Occipital",
                    "value": value + condition_index * 0.1,
                }
            )
    return pd.DataFrame(rows)


def test_one_sample_outlier_is_ranked_most_influential() -> None:
    data = _one_sample_frame(
        {"P1": 0.9, "P2": 1.0, "P3": 1.1, "P4": 1.2, "P5": 9.0}
    )

    result = run_one_sample_leave_one_out_stability(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
    )

    details = result.details
    outlier = details[details["omitted_participant"].eq("P5")].iloc[0]
    summary = result.summaries.iloc[0]
    assert bool(outlier["largest_shift_flag"])
    assert outlier["shift_rank"] == 1
    assert summary["participant_with_largest_estimate_shift"] == "P5"
    assert summary["max_abs_delta"] == pytest.approx(
        abs(outlier["delta_from_full"])
    )
    assert summary["min_estimate_after_omission"] < summary["full_estimate"]


def test_stable_positive_cells_have_stable_sign_and_raw_rejection() -> None:
    data = _one_sample_frame(
        {
            "P1": 1.00,
            "P2": 1.05,
            "P3": 0.95,
            "P4": 1.10,
            "P5": 0.90,
            "P6": 1.02,
        },
        conditions=("Faces", "Objects"),
        rois=("Left", "Right"),
    )

    result = run_one_sample_leave_one_out_stability(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
    )

    assert len(result.details) == 6 * 4
    assert result.summaries["sign_stable"].eq(True).all()  # noqa: E712
    assert result.summaries["reject_stable_raw"].eq(True).all()  # noqa: E712
    assert result.summaries["stability_status"].eq("estimated").all()
    assert result.metadata.loc[0, "omission_unit"].startswith("participant")


def test_group_omission_removes_participant_across_all_cells() -> None:
    data = _group_frame(
        [3.0, 3.2, 3.4, 3.6],
        [0.4, 0.6, 0.8, 1.0],
        conditions=("Faces", "Objects"),
    )

    result = run_two_group_leave_one_out_stability(
        data,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
        group_pair=("anxious", "non_anxious"),
    )

    omitted_a1 = result.details[
        result.details["omitted_participant"].eq("A1")
    ]
    assert len(omitted_a1) == 2
    assert omitted_a1["omitted_group"].eq("anxious").all()
    assert omitted_a1["n_group_a_after_omission"].eq(3).all()
    assert omitted_a1["n_group_b_after_omission"].eq(4).all()
    assert result.summaries["full_estimate"].gt(0).all()
    expected = stats.ttest_ind(
        [3.0, 3.2, 3.4, 3.6],
        [0.4, 0.6, 0.8, 1.0],
        equal_var=False,
    )
    faces = result.summaries[
        result.summaries["condition"].eq("Faces")
    ].iloc[0]
    assert faces["full_test_statistic"] == pytest.approx(expected.statistic)
    assert faces["full_p_raw"] == pytest.approx(expected.pvalue)
    assert result.metadata.loc[0, "sign_convention"] == (
        "positive means group_a exceeds group_b"
    )


def test_incomplete_core_blocks_but_explicit_available_case_is_exported() -> None:
    complete = _one_sample_frame(
        {"P1": 1.0, "P2": 1.1, "P3": 1.2, "P4": 1.3},
        conditions=("Faces", "Objects"),
    )
    incomplete = complete[
        ~(
            complete["participant"].eq("P1")
            & complete["condition"].eq("Objects")
        )
    ].copy()

    with pytest.raises(StabilityAnalysisError, match="Complete-core"):
        run_one_sample_leave_one_out_stability(
            incomplete,
            dv_col="value",
            subject_col="participant",
            condition_col="condition",
            roi_col="roi",
        )

    available = run_one_sample_leave_one_out_stability(
        incomplete,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        analysis_scope="available_case",
    )
    objects = available.summaries[
        available.summaries["condition"].eq("Objects")
    ].iloc[0]
    assert available.metadata.loc[0, "analysis_scope"] == "available_case"
    assert available.metadata.loc[0, "n_missing_cell_values"] == 1
    assert objects["missing_cell_values"] == 1
    assert objects["missingness_status"] == "available_case_missing"
    p1 = available.details[
        available.details["omitted_participant"].eq("P1")
        & available.details["condition"].eq("Objects")
    ].iloc[0]
    assert not bool(p1["omitted_participant_had_finite_value"])


def test_output_is_deterministic_across_input_row_order() -> None:
    data = _group_frame(
        [2.0, 2.3, 2.6, 2.9],
        [0.2, 0.5, 0.8, 1.1],
        conditions=("B", "A"),
    )
    kwargs = {
        "dv_col": "value",
        "subject_col": "participant",
        "group_col": "group_id",
        "condition_col": "condition",
        "roi_col": "roi",
    }

    first = run_two_group_leave_one_out_stability(data, **kwargs)
    shuffled = run_two_group_leave_one_out_stability(
        data.sample(frac=1.0, random_state=7),
        **kwargs,
    )

    assert_frame_equal(first.details, shuffled.details)
    assert_frame_equal(first.summaries, shuffled.summaries)
    assert_frame_equal(first.metadata, shuffled.metadata)


def test_tiny_n_and_zero_variance_have_explicit_non_estimable_statuses() -> None:
    tiny = _one_sample_frame({"P1": 1.0})
    zero_variance = _one_sample_frame({"P1": 1.0, "P2": 1.0, "P3": 1.0})

    tiny_result = run_one_sample_leave_one_out_stability(
        tiny,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
    )
    zero_result = run_one_sample_leave_one_out_stability(
        zero_variance,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
    )

    assert tiny_result.summaries.loc[0, "full_status_code"] == "insufficient_n"
    assert tiny_result.summaries.loc[0, "stability_status"] == "not_estimable"
    assert zero_result.summaries.loc[
        0, "full_status_code"
    ] == "zero_or_invalid_variance"
    assert zero_result.details["status_code"].eq(
        "zero_or_invalid_variance"
    ).all()
    assert pd.isna(zero_result.summaries.loc[0, "reject_stable_raw"])
    numeric = zero_result.details[
        ["test_statistic_after_omission", "p_raw_after_omission"]
    ].to_numpy(dtype=float)
    assert not np.isinf(numeric).any()


def test_group_tiny_n_and_zero_standard_error_are_non_estimable() -> None:
    tiny = _group_frame([1.0, 1.2], [0.4, 0.6, 0.8])
    constant = _group_frame([1.0, 1.0, 1.0], [0.0, 0.0, 0.0])

    tiny_result = run_two_group_leave_one_out_stability(
        tiny,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
    )
    constant_result = run_two_group_leave_one_out_stability(
        constant,
        dv_col="value",
        subject_col="participant",
        group_col="group_id",
        condition_col="condition",
        roi_col="roi",
    )

    assert tiny_result.summaries.loc[0, "stability_status"] == (
        "partially_estimable"
    )
    assert tiny_result.details["status_code"].eq("insufficient_group_n").any()
    assert constant_result.summaries.loc[
        0, "full_status_code"
    ] == "zero_or_invalid_standard_error"
    assert constant_result.details["status_code"].eq(
        "zero_or_invalid_standard_error"
    ).all()


def test_duplicate_grain_and_inconsistent_group_assignment_block() -> None:
    data = _group_frame([1.0, 1.2, 1.4], [0.4, 0.6, 0.8])
    duplicate = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    inconsistent = pd.concat(
        [
            data,
            pd.DataFrame(
                [
                    {
                        "participant": "A1",
                        "group_id": "non_anxious",
                        "condition": "Other",
                        "roi": "Occipital",
                        "value": 0.5,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    with pytest.raises(StabilityAnalysisError, match="Duplicate participant"):
        run_two_group_leave_one_out_stability(
            duplicate,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )
    with pytest.raises(StabilityAnalysisError, match="one canonical group"):
        run_two_group_leave_one_out_stability(
            inconsistent,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )


def test_blank_ids_boolean_responses_and_placeholder_groups_are_rejected() -> None:
    base = _group_frame([1.0, 1.2, 1.4], [0.4, 0.6, 0.8])
    blank = base.copy()
    blank.loc[0, "participant"] = " "
    boolean = base.copy()
    boolean["value"] = boolean["value"].astype(object)
    boolean.loc[0, "value"] = True
    placeholder = base.copy()
    placeholder.loc[
        placeholder["participant"].str.startswith("N"),
        "group_id",
    ] = "missing"

    with pytest.raises(StabilityAnalysisError, match="non-blank"):
        run_two_group_leave_one_out_stability(
            blank,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )
    with pytest.raises(StabilityAnalysisError, match="Boolean"):
        run_two_group_leave_one_out_stability(
            boolean,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )
    with pytest.raises(StabilityAnalysisError, match="missing or unknown"):
        run_two_group_leave_one_out_stability(
            placeholder,
            dv_col="value",
            subject_col="participant",
            group_col="group_id",
            condition_col="condition",
            roi_col="roi",
        )


def test_result_frames_state_no_formal_multiplicity_correction() -> None:
    result = run_one_sample_leave_one_out_stability(
        _one_sample_frame({"P1": 0.8, "P2": 1.0, "P3": 1.2}),
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
    )

    frames = result.to_frames()
    assert set(frames) == {
        "LOO Omission Details",
        "LOO Stability Summary",
        "LOO Stability Metadata",
    }
    assert not bool(
        frames["LOO Stability Metadata"].loc[
            0, "formal_hypothesis_correction"
        ]
    )
    assert "No multiplicity claim" in frames["LOO Stability Metadata"].loc[
        0, "multiplicity_note"
    ]
    assert frames["LOO Stability Summary"][
        "formal_hypothesis_correction"
    ].eq(False).all()  # noqa: E712
    assert "does not by itself establish" in frames[
        "LOO Stability Metadata"
    ].loc[0, "largest_shift_definition"]

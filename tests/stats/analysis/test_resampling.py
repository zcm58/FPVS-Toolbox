"""Frozen checks for participant-level resampling sensitivities."""

from __future__ import annotations

from itertools import combinations, product

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.inference_contracts import HarmonicProvenance
from Tools.Stats.analysis.resampling import (
    ResamplingValidationError,
    run_group_label_permutation_max_t,
    run_one_sample_sign_flip_max_t,
)


def _long_one_sample(matrix: np.ndarray) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    cells = (("face", "left"), ("word", "right"))
    for participant_index, values in enumerate(matrix, start=1):
        for (condition, roi), value in zip(cells, values):
            rows.append(
                {
                    "participant": f"P{participant_index:02d}",
                    "condition": condition,
                    "roi": roi,
                    "bca": float(value),
                }
            )
    return pd.DataFrame(rows)


def _one_sample_t(values: np.ndarray) -> np.ndarray:
    return np.mean(values, axis=0) / (
        np.std(values, axis=0, ddof=1) / np.sqrt(values.shape[0])
    )


def _welch_t(values: np.ndarray, group_a_mask: np.ndarray) -> np.ndarray:
    values_a = values[group_a_mask]
    values_b = values[~group_a_mask]
    difference = np.mean(values_a, axis=0) - np.mean(values_b, axis=0)
    standard_error = np.sqrt(
        np.var(values_a, axis=0, ddof=1) / values_a.shape[0]
        + np.var(values_b, axis=0, ddof=1) / values_b.shape[0]
    )
    return difference / standard_error


def test_exact_sign_flip_matches_frozen_joint_row_brute_force() -> None:
    matrix = np.asarray(
        [
            [1.0, 0.5],
            [2.0, 1.5],
            [4.0, -0.5],
            [5.0, 3.0],
        ]
    )
    observed_abs = np.abs(_one_sample_t(matrix))
    null = []
    for signs in product((-1.0, 1.0), repeat=matrix.shape[0]):
        flipped = matrix * np.asarray(signs)[:, np.newaxis]
        null.append(np.abs(_one_sample_t(flipped)))
    null_array = np.asarray(null)
    expected_raw = np.mean(null_array >= observed_abs, axis=0)
    expected_max = np.mean(
        np.max(null_array, axis=1)[:, np.newaxis] >= observed_abs,
        axis=0,
    )

    result = run_one_sample_sign_flip_max_t(
        _long_one_sample(matrix),
        dv_col="bca",
        subject_col="participant",
        n_resamples=999,
        seed=41,
    )

    np.testing.assert_allclose(
        result.results["p_raw_resampling"],
        expected_raw,
    )
    np.testing.assert_allclose(
        result.results["p_adjusted_max_t"],
        expected_max,
    )
    metadata = result.metadata.iloc[0]
    assert metadata["resampling_mode"] == "exact"
    assert metadata["total_unique_transformations"] == 16
    assert metadata["draws_requested"] == 999
    assert metadata["draws_completed"] == 16
    assert "one shared sign per participant" in metadata["null_statistic_definition"]


def test_sign_flip_uses_joint_rows_not_independent_cell_signs() -> None:
    matrix = np.asarray(
        [
            [1.0, 5.0],
            [2.0, -2.0],
            [3.0, 1.0],
        ]
    )
    result = run_one_sample_sign_flip_max_t(
        _long_one_sample(matrix),
        dv_col="bca",
        subject_col="participant",
        exact_enumeration_limit=100,
    )

    metadata = result.metadata.iloc[0]
    assert metadata["total_unique_transformations"] == 2 ** matrix.shape[0]
    assert metadata["draws_completed"] == 2 ** matrix.shape[0]
    assert metadata["family_size"] == matrix.shape[1]


def test_sign_flip_monte_carlo_is_seeded_and_uses_plus_one() -> None:
    matrix = np.asarray(
        [[float(index), float(index % 4) - 1.5] for index in range(1, 13)]
    )
    data = _long_one_sample(matrix)
    kwargs = {
        "dv_col": "bca",
        "subject_col": "participant",
        "n_resamples": 137,
        "seed": 2026,
        "exact_enumeration_limit": 8,
    }

    first = run_one_sample_sign_flip_max_t(data, **kwargs)
    second = run_one_sample_sign_flip_max_t(data, **kwargs)

    pd.testing.assert_frame_equal(first.results, second.results)
    pd.testing.assert_frame_equal(first.metadata, second.metadata)
    metadata = first.metadata.iloc[0]
    assert metadata["resampling_mode"] == "monte_carlo"
    assert metadata["draws_completed"] == 137
    assert "plus-one" in metadata["p_value_count_convention"]
    denominators = first.results.loc[
        first.results["inference_status"].eq("estimated"),
        "p_adjusted_max_t",
    ] * 138
    np.testing.assert_allclose(denominators, np.round(denominators))


def test_monte_carlo_cancellation_is_explicit_and_never_returns_partial_p_values() -> None:
    matrix = np.asarray(
        [[float(index), float(index % 4) - 1.5] for index in range(1, 13)]
    )
    progress: list[tuple[int, int]] = []

    result = run_one_sample_sign_flip_max_t(
        _long_one_sample(matrix),
        dv_col="bca",
        subject_col="participant",
        n_resamples=137,
        seed=2026,
        exact_enumeration_limit=8,
        cancel_check=lambda: len(progress) >= 5,
        progress_callback=lambda completed, planned: progress.append(
            (completed, planned)
        ),
    )

    assert progress == [(draw, 137) for draw in range(1, 6)]
    metadata = result.metadata.iloc[0]
    assert metadata["overall_status"] == "cancelled"
    assert metadata["draws_completed"] == 5
    assert metadata["p_value_count_convention"] == "not_computed_cancelled"
    cancelled_rows = result.results["inference_status"].eq("cancelled")
    assert cancelled_rows.any()
    assert result.results.loc[cancelled_rows, "p_adjusted_max_t"].isna().all()
    assert not result.results.loc[cancelled_rows, "reject_adjusted"].any()


def _long_group(matrix: np.ndarray, groups: list[str]) -> pd.DataFrame:
    data = _long_one_sample(matrix)
    group_by_participant = {
        f"P{index:02d}": group for index, group in enumerate(groups, start=1)
    }
    data["group"] = data["participant"].map(group_by_participant)
    return data


def test_exact_group_permutation_matches_participant_partition_brute_force() -> None:
    matrix = np.asarray(
        [
            [1.0, 3.0],
            [2.0, 4.5],
            [4.0, 2.0],
            [5.0, 7.0],
            [8.0, 5.5],
            [9.0, 9.0],
        ]
    )
    groups = ["anxious"] * 3 + ["non_anxious"] * 3
    observed_mask = np.asarray([True, True, True, False, False, False])
    observed_abs = np.abs(_welch_t(matrix, observed_mask))
    null = []
    for indices in combinations(range(matrix.shape[0]), 3):
        mask = np.zeros(matrix.shape[0], dtype=bool)
        mask[list(indices)] = True
        null.append(np.abs(_welch_t(matrix, mask)))
    null_array = np.asarray(null)
    expected_raw = np.mean(null_array >= observed_abs, axis=0)
    expected_max = np.mean(
        np.max(null_array, axis=1)[:, np.newaxis] >= observed_abs,
        axis=0,
    )

    result = run_group_label_permutation_max_t(
        _long_group(matrix, groups),
        dv_col="bca",
        subject_col="participant",
        group_col="group",
        n_resamples=999,
        seed=7,
    )

    np.testing.assert_allclose(result.results["p_raw_resampling"], expected_raw)
    np.testing.assert_allclose(result.results["p_adjusted_max_t"], expected_max)
    metadata = result.metadata.iloc[0]
    assert metadata["resampling_mode"] == "exact"
    assert metadata["total_unique_transformations"] == 20
    assert metadata["draws_completed"] == 20


def test_group_permutation_moves_one_label_per_participant_across_cells() -> None:
    matrix = np.asarray(
        [
            [1.0, 3.0],
            [2.0, 4.0],
            [3.5, 1.0],
            [6.0, 8.0],
            [7.0, 5.0],
            [9.0, 6.0],
        ]
    )
    data = _long_group(matrix, ["A", "A", "A", "B", "B", "B"])

    result = run_group_label_permutation_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        group_col="group",
    )

    metadata = result.metadata.iloc[0]
    assert metadata["total_unique_transformations"] == 20
    assert "one permuted group label per participant" in metadata[
        "null_statistic_definition"
    ]
    assert metadata["family_size"] == 2


def test_group_monte_carlo_is_deterministic_for_fixed_seed() -> None:
    matrix = np.asarray(
        [[float(index), float(index**2 % 11)] for index in range(1, 13)]
    )
    data = _long_group(matrix, ["A"] * 6 + ["B"] * 6)
    kwargs = {
        "dv_col": "bca",
        "subject_col": "participant",
        "group_col": "group",
        "n_resamples": 103,
        "seed": 88,
        "exact_enumeration_limit": 8,
    }

    first = run_group_label_permutation_max_t(data, **kwargs)
    second = run_group_label_permutation_max_t(data, **kwargs)

    pd.testing.assert_frame_equal(first.results, second.results)
    pd.testing.assert_frame_equal(first.metadata, second.metadata)
    assert first.metadata.iloc[0]["draws_completed"] == 103


def test_group_permutation_cancellation_suppresses_partial_p_values() -> None:
    matrix = np.asarray(
        [[float(index), float(index**2 % 11)] for index in range(1, 13)]
    )
    data = _long_group(matrix, ["A"] * 6 + ["B"] * 6)
    completed = 0

    def progress_callback(_completed: int, _planned: int) -> None:
        nonlocal completed
        completed = _completed

    result = run_group_label_permutation_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        group_col="group",
        n_resamples=103,
        seed=88,
        exact_enumeration_limit=8,
        cancel_check=lambda: completed >= 4,
        progress_callback=progress_callback,
    )

    assert result.metadata.loc[0, "overall_status"] == "cancelled"
    assert result.metadata.loc[0, "draws_completed"] == 4
    cancelled = result.results["inference_status"].eq("cancelled")
    assert cancelled.any()
    assert result.results.loc[cancelled, "p_raw_resampling"].isna().all()
    assert result.results.loc[cancelled, "p_adjusted_max_t"].isna().all()
    assert not result.results.loc[cancelled, "reject_adjusted"].any()


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda frame: frame.drop(index=frame.index[-1]).reset_index(drop=True),
            "incomplete_participant_cell_matrix",
        ),
        (
            lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "duplicate_participant_cell",
        ),
        (
            lambda frame: frame.assign(
                bca=lambda values: values["bca"].mask(values.index == 0, np.inf)
            ),
            "nonfinite_or_invalid_response",
        ),
    ],
)
def test_invalid_matrix_returns_explicit_nonestimable_rows(
    mutator,
    expected_code: str,
) -> None:
    data = _long_one_sample(np.asarray([[1.0, 2.0], [2.0, 3.0], [4.0, 5.0]]))

    result = run_one_sample_sign_flip_max_t(
        mutator(data),
        dv_col="bca",
        subject_col="participant",
    )

    assert result.metadata.iloc[0]["overall_status"] == "not_estimable"
    assert result.metadata.iloc[0]["status_code"] == expected_code
    assert result.metadata.iloc[0]["draws_completed"] == 0
    assert result.results["inference_status"].eq("not_estimable").all()
    assert not np.isinf(
        result.results.select_dtypes(include=[np.number]).to_numpy()
    ).any()


def test_tiny_n_and_zero_variance_are_not_estimable_and_never_infinite() -> None:
    tiny = _long_one_sample(np.asarray([[1.0, 2.0]]))
    constant = _long_one_sample(
        np.asarray([[1.0, 2.0], [1.0, 2.0], [1.0, 2.0]])
    )

    tiny_result = run_one_sample_sign_flip_max_t(
        tiny,
        dv_col="bca",
        subject_col="participant",
    )
    constant_result = run_one_sample_sign_flip_max_t(
        constant,
        dv_col="bca",
        subject_col="participant",
    )

    for result in (tiny_result, constant_result):
        assert result.metadata.iloc[0]["overall_status"] == "not_estimable"
        assert result.results["inference_status"].eq("not_estimable").all()
        assert not np.isinf(
            result.results.select_dtypes(include=[np.number]).to_numpy()
        ).any()


def test_same_sample_selection_stays_exploratory_without_nested_recomputation() -> None:
    data = _long_one_sample(
        np.asarray([[1.0, 2.0], [2.0, 4.0], [4.0, 3.0]])
    )

    ordinary = run_one_sample_sign_flip_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
    )
    nested = run_one_sample_sign_flip_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        harmonic_provenance=HarmonicProvenance.SAME_SAMPLE_ADAPTIVE,
        selection_nesting_attested=True,
    )

    ordinary_metadata = ordinary.metadata.iloc[0]
    assert ordinary_metadata["selection_boundary_status"] == "exploratory_post_selection"
    assert ordinary_metadata["interpretation_role"] == "exploratory_sensitivity"
    assert "remains exploratory" in ordinary_metadata["selection_warning"]
    nested_metadata = nested.metadata.iloc[0]
    assert nested_metadata["selection_boundary_status"] == (
        "exploratory_post_selection"
    )
    assert nested_metadata["interpretation_role"] == "exploratory_sensitivity"
    assert not bool(nested_metadata["selection_nesting_effective"])
    assert "cannot change that boundary" in nested_metadata["selection_warning"]


def test_selected_pair_allows_more_than_two_groups() -> None:
    matrix = np.asarray(
        [
            [1.0, 3.0],
            [2.0, 4.0],
            [5.0, 6.0],
            [7.0, 8.0],
            [10.0, 2.0],
            [11.0, 1.0],
        ]
    )
    data = _long_group(matrix, ["A", "A", "B", "B", "small", "small"])

    unselected = run_group_label_permutation_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        group_col="group",
    )
    selected = run_group_label_permutation_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        group_col="group",
        group_pair=("A", "B"),
    )

    assert unselected.metadata.iloc[0]["status_code"] == "unsupported_group_count"
    assert selected.results[["n_group_a", "n_group_b"]].iloc[0].tolist() == [2, 2]
    assert selected.metadata.iloc[0]["total_unique_transformations"] == 6


def test_unknown_canonical_group_assignment_is_not_permuted() -> None:
    matrix = np.asarray(
        [
            [1.0, 3.0],
            [2.0, 4.0],
            [5.0, 6.0],
            [7.0, 8.0],
        ]
    )
    data = _long_group(matrix, ["A", "A", "unknown", "B"])

    result = run_group_label_permutation_max_t(
        data,
        dv_col="bca",
        subject_col="participant",
        group_col="group",
    )

    assert result.metadata.iloc[0]["status_code"] == "invalid_group_assignment"
    assert result.results["inference_status"].eq("not_estimable").all()


def test_resampling_metadata_states_randomization_assumptions_and_exactness() -> None:
    one_sample = run_one_sample_sign_flip_max_t(
        _long_one_sample(
            np.asarray([[1.0, 2.0], [2.0, 4.0], [4.0, 3.0]])
        ),
        dv_col="bca",
        subject_col="participant",
    ).metadata.iloc[0]
    grouped = run_group_label_permutation_max_t(
        _long_group(
            np.asarray(
                [
                    [1.0, 3.0],
                    [2.0, 4.0],
                    [5.0, 6.0],
                    [7.0, 8.0],
                ]
            ),
            ["A", "A", "B", "B"],
        ),
        dv_col="bca",
        subject_col="participant",
        group_col="group",
    ).metadata.iloc[0]

    assert "jointly sign-symmetric" in one_sample["randomization_assumption"]
    assert "exchangeable" in grouped["randomization_assumption"]
    assert "observational groups" in grouped["randomization_assumption"]
    assert "does not remove" in grouped["exactness_note"]


def test_invalid_configuration_raises_validation_error() -> None:
    data = _long_one_sample(np.asarray([[1.0, 2.0], [2.0, 3.0]]))

    with pytest.raises(ResamplingValidationError, match="positive integer"):
        run_one_sample_sign_flip_max_t(
            data,
            dv_col="bca",
            subject_col="participant",
            n_resamples=0,
        )

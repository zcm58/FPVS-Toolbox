from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis import dv_policy_group_significant as group_policy


def _scalar_finite_column_means(
    frame: pd.DataFrame,
    columns: list[str],
) -> np.ndarray:
    means: list[float] = []
    for column in columns:
        column_values = pd.to_numeric(
            frame.get(column, pd.Series(dtype=float)),
            errors="coerce",
        ).to_numpy(dtype=float)
        finite_values = column_values[np.isfinite(column_values)]
        means.append(
            float(finite_values.mean()) if finite_values.size else np.nan
        )
    return np.asarray(means, dtype=float)


def _call_with_warnings(callable_, *args):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = callable_(*args)
    return result, [
        (item.category, str(item.message))
        for item in caught
    ]


def test_full_fft_column_mean_batch_matches_scalar_bytes() -> None:
    columns = [f"{index / 100:.4f}_Hz" for index in range(500)]
    frame = pd.DataFrame(
        np.abs(
            np.random.default_rng(20260729).normal(
                size=(64, len(columns)),
            )
        ),
        columns=columns,
    )

    expected = _scalar_finite_column_means(frame, columns)
    actual = group_policy._mean_full_fft_columns_exact(frame, columns)

    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize(
    "array_kind",
    [
        "zeros",
        "signed_zeros",
        "nonfinite",
        "float32",
        "object",
        "large",
    ],
)
def test_full_fft_column_mean_fallback_matches_values_and_warnings(
    array_kind: str,
) -> None:
    columns = [f"{index / 10:.4f}_Hz" for index in range(12)]
    values = np.abs(np.random.default_rng(2718).normal(size=(9, len(columns))))
    if array_kind == "zeros":
        values.fill(0.0)
    elif array_kind == "signed_zeros":
        values[0, 0] = -0.0
        values[1, 1] = 0.0
    elif array_kind == "nonfinite":
        values[0, 0] = np.nan
        values[1, 1] = np.inf
    elif array_kind == "float32":
        values = values.astype(np.float32)
    elif array_kind == "object":
        values = values.astype(object)
        values[0, 0] = "1.25"
        values[1, 1] = "not-a-number"
    elif array_kind == "large":
        values.fill(np.finfo(np.float64).max / 2.0)
    frame = pd.DataFrame(values, columns=columns)

    expected, expected_warnings = _call_with_warnings(
        _scalar_finite_column_means,
        frame,
        columns,
    )
    actual, actual_warnings = _call_with_warnings(
        group_policy._mean_full_fft_columns_exact,
        frame,
        columns,
    )

    assert actual_warnings == expected_warnings
    assert actual.dtype == expected.dtype
    assert actual.shape == expected.shape
    assert actual.tobytes() == expected.tobytes()


def test_full_fft_column_mean_preserves_missing_column_fallback() -> None:
    frame = pd.DataFrame({"1.2000_Hz": [1.0, 2.0]})
    columns = ["1.2000_Hz", "2.4000_Hz"]

    expected = _scalar_finite_column_means(frame, columns)
    actual = group_policy._mean_full_fft_columns_exact(frame, columns)

    assert actual.tobytes() == expected.tobytes()


def test_full_fft_column_plan_preserves_required_order_and_mapping() -> None:
    headers: list[object] = [
        "Electrode",
        *[f"{index / 10:.4f}_Hz" for index in range(80)],
    ]
    reference = group_policy._parse_frequency_columns(headers)
    required = [3, 11, 3, 37, 79]
    required_set = set(required)
    reference_by_idx = {
        int(index): (float(frequency), str(column))
        for frequency, column, index in reference
        if int(index) in set(required)
    }
    local_by_column = {
        str(column): float(frequency)
        for frequency, column, _index in reference
    }
    expected_mapping: dict[str, list[tuple[float, str]]] = {}
    for required_index in sorted(required_set):
        reference_item = reference_by_idx.get(int(required_index))
        if reference_item is None:
            continue
        reference_frequency, reference_column = reference_item
        local_frequency = local_by_column.get(reference_column)
        if local_frequency is None:
            continue
        if (
            abs(float(local_frequency) - reference_frequency)
            > group_policy.GROUP_SIGNIFICANT_MATCHING_TOLERANCE_HZ
        ):
            continue
        expected_mapping.setdefault(reference_column, []).append(
            (reference_frequency, reference_column)
        )
    expected_usecols = ["Electrode", *expected_mapping.keys()]

    actual_usecols, actual_mapping = (
        group_policy._plan_workbook_full_fft_usecols_from_header(
            headers,
            reference_frequency_columns=reference,
            required_indices=required,
        )
    )

    assert actual_usecols == expected_usecols
    assert actual_mapping == expected_mapping

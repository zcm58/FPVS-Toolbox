from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

import numpy as np
import pytest

from Main_App.processing.output_integrity import (
    OutputIntegrityError,
    OutputIntegrityReceipt,
    require_finite_computable_bca,
    require_finite_retained_signal,
)


@dataclass(frozen=True)
class _Target:
    frequency_hz: Fraction


@dataclass(frozen=True)
class _Availability:
    target: _Target
    bca_available: bool


def test_finite_retained_signal_produces_fingerprinted_receipt():
    receipt = require_finite_retained_signal(
        np.ones((2, 8), dtype=float),
        electrode_names=("Fp1", "Fp2"),
        recording_id="P01",
        condition_label="Faces",
    )

    payload = receipt.to_payload()
    assert payload["status"] == "passed"
    assert payload["inspected_value_count"] == 16
    assert len(str(payload["fingerprint"])) == 64


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_nonfinite_retained_signal_is_a_structured_technical_failure(invalid):
    signal = np.ones((2, 8), dtype=float)
    signal[1, 3] = invalid

    with pytest.raises(OutputIntegrityError) as exc_info:
        require_finite_retained_signal(
            signal,
            electrode_names=("Fp1", "Fp2"),
            recording_id="P01",
            condition_label="Faces",
        )

    assert exc_info.value.to_payload() == {
        "version": "spectral_output_integrity_v1",
        "status": "failed",
        "stage": "retained_signal",
        "recording_id": "P01",
        "condition_label": "Faces",
        "value_category": "retained_eeg",
        "electrode": "Fp2",
        "frequency_hz": None,
        "value_index": [1, 3],
        "message": str(exc_info.value),
    }


def test_method_unavailable_target_may_remain_nonfinite_but_is_counted():
    receipt = require_finite_computable_bca(
        np.asarray([[1.0, np.nan], [2.0, np.nan]]),
        electrode_names=("Fp1", "Fp2"),
        target_availability=(
            _Availability(_Target(Fraction(6, 5)), True),
            _Availability(_Target(Fraction(12, 5)), False),
        ),
        recording_id="P01",
        condition_label="Faces",
    )

    payload = receipt.to_payload()
    assert payload["inspected_value_count"] == 2
    assert payload["skipped_method_unavailable_target_count"] == 1


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_nonfinite_computable_bca_identifies_exact_cell(invalid):
    values = np.asarray([[1.0, 2.0], [3.0, invalid]])

    with pytest.raises(OutputIntegrityError) as exc_info:
        require_finite_computable_bca(
            values,
            electrode_names=("Fp1", "Oz"),
            target_availability=(
                _Availability(_Target(Fraction(6, 5)), True),
                _Availability(_Target(Fraction(12, 5)), True),
            ),
            recording_id="P01__visit_1",
            condition_label="Faces",
        )

    error = exc_info.value
    assert error.electrode == "Oz"
    assert error.frequency_hz == "12/5"
    assert error.value_index == (1, 1)


def test_bca_identity_shape_mismatch_fails_before_export():
    with pytest.raises(OutputIntegrityError, match="does not match"):
        require_finite_computable_bca(
            np.ones((2, 1)),
            electrode_names=("Fp1", "Fp2"),
            target_availability=(
                _Availability(_Target(Fraction(6, 5)), True),
                _Availability(_Target(Fraction(12, 5)), True),
            ),
            recording_id="P01",
            condition_label="Faces",
        )


@pytest.mark.parametrize("layout", ["c", "fortran", "reversed", "strided", "empty"])
@pytest.mark.parametrize("dtype", [np.float32, np.float64, np.complex128, np.int64, np.bool_])
def test_finite_gate_preserves_reference_first_failure_and_input(layout, dtype):
    values = np.arange(48).reshape(4, 12).astype(dtype)
    if np.issubdtype(dtype, np.inexact):
        values[0, 9] = np.inf
        values[2, 1] = np.nan
        values[3, 8] = -np.inf
        values[0, 0] = -0.0
    if layout == "fortran":
        values = np.asfortranarray(values)
    elif layout == "reversed":
        values = values[::-1, ::-1]
    elif layout == "strided":
        values = values[:, ::2]
    elif layout == "empty":
        values = values[:, :0]
    before = values.tobytes()
    names = tuple(f"E{index}" for index in range(values.shape[0]))
    # Frozen pre-change selection: first invalid coordinate in C order.
    invalid = np.argwhere(~np.isfinite(values))
    kwargs = dict(electrode_names=names, recording_id="P01", condition_label="Faces")
    if invalid.size:
        with pytest.raises(OutputIntegrityError) as error:
            require_finite_retained_signal(values, **kwargs)
        expected = tuple(int(value) for value in invalid[0])
        assert error.value.value_index == expected
        assert error.value.electrode == names[expected[0]]
    else:
        actual = require_finite_retained_signal(values, **kwargs)
        expected = OutputIntegrityReceipt(
            stage="retained_signal", recording_id="P01", condition_label="Faces",
            value_category="retained_eeg", inspected_value_count=values.size,
        )
        assert actual.to_payload() == expected.to_payload()
    assert values.tobytes() == before


@pytest.mark.parametrize("available", [(False, False, False), (True, True, True), (False, True, True)])
def test_bca_gate_preserves_target_major_failure_order_and_skipped_counts(available):
    # First bad cell in C order differs from first bad available target.
    values = np.asarray([[1.0, np.nan, np.inf], [np.nan, 2.0, -np.inf]])
    targets = tuple(_Availability(_Target(Fraction(index + 1)), flag)
                    for index, flag in enumerate(available))
    kwargs = dict(electrode_names=("E0", "E1"), recording_id="P01",
                  condition_label="Faces", target_availability=targets)
    bad = None
    for column, flag in enumerate(available):
        if flag:
            invalid = np.flatnonzero(~np.isfinite(values[:, column]))
            if invalid.size:
                bad = (int(invalid[0]), column)
                break
    if bad is not None:
        with pytest.raises(OutputIntegrityError) as error:
            require_finite_computable_bca(values, **kwargs)
        assert error.value.value_index == bad
        assert error.value.frequency_hz == f"{bad[1] + 1}/1"
    else:
        actual = require_finite_computable_bca(values, **kwargs)
        expected = OutputIntegrityReceipt(
            stage="computable_bca", recording_id="P01", condition_label="Faces",
            value_category="bca", inspected_value_count=2 * sum(available),
            skipped_method_unavailable_target_count=available.count(False),
        )
        assert actual.to_payload() == expected.to_payload()

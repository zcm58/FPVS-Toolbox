"""QC-10 technical integrity checks for active spectral exports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
from typing import Any

import numpy as np


OUTPUT_INTEGRITY_METHOD_VERSION = "spectral_output_integrity_v1"


class OutputIntegrityError(ValueError):
    """A value required for a current spectral result is technically invalid."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        recording_id: str,
        condition_label: str,
        value_category: str,
        electrode: str | None = None,
        frequency_hz: str | None = None,
        value_index: Sequence[int] = (),
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.recording_id = recording_id
        self.condition_label = condition_label
        self.value_category = value_category
        self.electrode = electrode
        self.frequency_hz = frequency_hz
        self.value_index = tuple(int(value) for value in value_index)

    def to_payload(self) -> dict[str, object]:
        return {
            "version": OUTPUT_INTEGRITY_METHOD_VERSION,
            "status": "failed",
            "stage": self.stage,
            "recording_id": self.recording_id,
            "condition_label": self.condition_label,
            "value_category": self.value_category,
            "electrode": self.electrode,
            "frequency_hz": self.frequency_hz,
            "value_index": list(self.value_index),
            "message": str(self),
        }


def _fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frequency_text(value: object) -> str:
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    numerator = getattr(value, "numerator", None)
    denominator = getattr(value, "denominator", None)
    if isinstance(numerator, int) and isinstance(denominator, int):
        return f"{numerator}/{denominator}"
    return str(value)


@dataclass(frozen=True, slots=True)
class OutputIntegrityReceipt:
    """Fingerprintable proof that one required finite-value gate passed."""

    stage: str
    recording_id: str
    condition_label: str
    value_category: str
    inspected_value_count: int
    skipped_method_unavailable_target_count: int = 0
    method_version: str = OUTPUT_INTEGRITY_METHOD_VERSION

    def canonical_payload(self) -> dict[str, object]:
        return {
            "method_version": self.method_version,
            "status": "passed",
            "stage": self.stage,
            "recording_id": self.recording_id,
            "condition_label": self.condition_label,
            "value_category": self.value_category,
            "inspected_value_count": self.inspected_value_count,
            "skipped_method_unavailable_target_count": (
                self.skipped_method_unavailable_target_count
            ),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload


def require_finite_retained_signal(
    values: np.ndarray,
    *,
    electrode_names: Sequence[str],
    recording_id: object,
    condition_label: object,
) -> OutputIntegrityReceipt:
    """Reject a nonfinite retained time-domain value before spectral analysis."""

    data = np.asarray(values)
    names = tuple(str(value) for value in electrode_names)
    identity = str(recording_id or "UnknownRecording")
    condition = str(condition_label or "UnknownCondition")
    if data.ndim != 2 or data.shape[0] != len(names):
        raise OutputIntegrityError(
            "Retained EEG data do not match the retained electrode identity.",
            stage="retained_signal",
            recording_id=identity,
            condition_label=condition,
            value_category="retained_eeg",
        )
    finite = np.isfinite(data)
    if not finite.all():
        # Preserve the first C-order failure without allocating coordinates for
        # every invalid sample (potentially the entire recording).
        channel_index, sample_index = (
            int(value) for value in np.unravel_index(np.argmin(finite), data.shape)
        )
        electrode = names[channel_index]
        raise OutputIntegrityError(
            "A retained EEG value is NaN or infinite; the condition workbook "
            f"cannot be generated (recording={identity}, condition={condition}, "
            f"electrode={electrode}, sample_index={sample_index}).",
            stage="retained_signal",
            recording_id=identity,
            condition_label=condition,
            value_category="retained_eeg",
            electrode=electrode,
            value_index=(channel_index, sample_index),
        )
    return OutputIntegrityReceipt(
        stage="retained_signal",
        recording_id=identity,
        condition_label=condition,
        value_category="retained_eeg",
        inspected_value_count=int(data.size),
    )


def require_finite_computable_bca(
    values: np.ndarray,
    *,
    electrode_names: Sequence[str],
    target_availability: Sequence[object],
    recording_id: object,
    condition_label: object,
) -> OutputIntegrityReceipt:
    """Reject nonfinite BCA cells only where the method declares BCA available."""

    matrix = np.asarray(values)
    names = tuple(str(value) for value in electrode_names)
    targets = tuple(target_availability)
    identity = str(recording_id or "UnknownRecording")
    condition = str(condition_label or "UnknownCondition")
    if matrix.ndim != 2 or matrix.shape != (len(names), len(targets)):
        raise OutputIntegrityError(
            "The BCA matrix does not match its electrode and harmonic identities.",
            stage="computable_bca",
            recording_id=identity,
            condition_label=condition,
            value_category="bca",
        )

    inspected = 0
    skipped = 0
    for target_index, availability in enumerate(targets):
        is_available = bool(getattr(availability, "bca_available", False))
        if not is_available:
            skipped += 1
            continue
        column = matrix[:, target_index]
        finite = np.isfinite(column)
        if not finite.all():
            channel_index = int(np.argmin(finite))
            target = getattr(availability, "target", None)
            frequency = _frequency_text(getattr(target, "frequency_hz", "unknown"))
            electrode = names[channel_index]
            raise OutputIntegrityError(
                "A method-computable BCA value is NaN or infinite; the condition "
                f"workbook cannot be generated (recording={identity}, "
                f"condition={condition}, electrode={electrode}, "
                f"frequency_hz={frequency}).",
                stage="computable_bca",
                recording_id=identity,
                condition_label=condition,
                value_category="bca",
                electrode=electrode,
                frequency_hz=frequency,
                value_index=(channel_index, target_index),
            )
        inspected += int(column.size)

    return OutputIntegrityReceipt(
        stage="computable_bca",
        recording_id=identity,
        condition_label=condition,
        value_category="bca",
        inspected_value_count=inspected,
        skipped_method_unavailable_target_count=skipped,
    )


__all__ = [
    "OUTPUT_INTEGRITY_METHOD_VERSION",
    "OutputIntegrityError",
    "OutputIntegrityReceipt",
    "require_finite_computable_bca",
    "require_finite_retained_signal",
]

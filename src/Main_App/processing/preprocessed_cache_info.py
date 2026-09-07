"""Restore exact pre-FIF filter metadata only from verified cache evidence."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import math

import numpy as np

from Main_App.processing.spectral_eligibility import validate_applied_filter_snapshot


FILTER_INFO_VERSION = "preprocessed_fif_filter_info_v1"
_INFO_FIELDS = ("sfreq", "highpass", "lowpass")


def _fingerprint(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_filter_info(info: Mapping[str, object], settings: Mapping[str, object]) -> None:
    validate_applied_filter_snapshot(
        sampling_rate_hz=info["sfreq"],
        requested_high_pass_hz=settings.get("high_pass"),
        requested_low_pass_hz=settings.get("low_pass"),
        applied_high_pass_hz=info["highpass"],
        applied_low_pass_hz=info["lowpass"],
    )


def snapshot_preprocessed_filter_info(
    info: Mapping[str, object], settings: Mapping[str, object], *, cache_key: str,
) -> dict[str, object]:
    """Capture successfully applied edges before FIF narrows header precision."""
    values = {field: float(info[field]) for field in _INFO_FIELDS}
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("Preprocessed filter metadata must be finite.")
    _validate_filter_info(values, settings)
    payload = {
        "version": FILTER_INFO_VERSION,
        "cache_key": cache_key,
        "values": {field: value.hex() for field, value in values.items()},
    }
    return {**payload, "fingerprint": _fingerprint(payload)}


def restore_preprocessed_filter_info(
    raw, snapshot: Mapping[str, object], settings: Mapping[str, object], *, cache_key: str,
) -> None:
    """Verify original edges and their FIF encoding, then restore metadata only.

    FIF stores these Info fields as float32 even when samples use ``fmt='double'``.
    No tolerance is widened and no edge is inferred from requested settings.
    """
    payload = dict(snapshot)
    recorded = payload.pop("fingerprint", None)
    if (
        payload.get("version") != FILTER_INFO_VERSION
        or payload.get("cache_key") != cache_key
        or recorded != _fingerprint(payload)
    ):
        raise ValueError("Preprocessed exact filter metadata is missing or stale.")
    encoded = payload.get("values")
    if not isinstance(encoded, Mapping) or set(encoded) != set(_INFO_FIELDS):
        raise ValueError("Preprocessed exact filter metadata is incomplete.")
    values: dict[str, float] = {}
    for field in _INFO_FIELDS:
        text = encoded[field]
        if not isinstance(text, str):
            raise ValueError("Preprocessed exact filter metadata is invalid.")
        value = float.fromhex(text)
        if not math.isfinite(value) or value.hex() != text:
            raise ValueError("Preprocessed exact filter metadata is invalid.")
        observed = float(raw.info[field])
        serialized = float(np.float32(value))
        if not math.isfinite(observed) or observed != serialized:
            raise ValueError(f"Cached FIF {field} disagrees with its exact filter metadata.")
        values[field] = value
    _validate_filter_info(values, settings)
    with raw.info._unlock():
        for field, value in values.items():
            raw.info[field] = value


__all__ = ["restore_preprocessed_filter_info", "snapshot_preprocessed_filter_info"]

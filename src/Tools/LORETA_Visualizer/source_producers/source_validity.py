"""Explicit missing-source measurements and fixed-cohort summary support."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

SOURCE_VALIDITY_POLICY = "complete_valid_source_support_v1"
SOURCE_VALIDITY_VERSION = 1


def validated_source_values(
    values: Any,
    valid_source_mask: Any = None,
    *,
    invalid_count: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Validate finite observations and explicit NaN missingness without filling."""
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or not vector.size:
        raise ValueError("Source values must be a non-empty 1D array.")
    if valid_source_mask is None:
        if not np.all(np.isfinite(vector)) or (invalid_count is not None and invalid_count != 0):
            raise ValueError("Missing source measurements require an explicit validity mask.")
        valid = np.ones(vector.shape, dtype=bool)
    else:
        valid = np.asarray(valid_source_mask)
        if valid.dtype != np.dtype(bool) or valid.shape != vector.shape:
            raise ValueError("Source validity mask must be boolean and match the source values.")
        if not np.all(np.isfinite(vector[valid])) or not np.all(np.isnan(vector[~valid])):
            raise ValueError("Source values must be finite where valid and NaN exactly where invalid.")
    if invalid_count is not None:
        if isinstance(invalid_count, (bool, np.bool_)) or int(invalid_count) != invalid_count:
            raise ValueError("Invalid source count must be an integer.")
        if int(invalid_count) != int(np.count_nonzero(~valid)):
            raise ValueError("Invalid source count does not match the validity mask.")
    return vector.copy(), valid.copy()


def complete_valid_source_support(rows: Sequence[Any]) -> tuple[np.ndarray, np.ndarray]:
    """Return full participant arrays and their common support, retaining fixed N."""
    if not len(rows):
        raise ValueError("Source summaries require at least one participant map.")
    vectors, masks = [], []
    for row in rows:
        vector, mask = validated_source_values(
            row.values,
            getattr(row, "valid_source_mask", None),
            invalid_count=getattr(row, "zero_noise_sd_source_count", None),
        )
        vectors.append(vector)
        masks.append(mask)
    if len({len(vector) for vector in vectors}) != 1:
        raise ValueError("Participant source maps must share one source count.")
    support = np.logical_and.reduce(masks)
    if not np.any(support):
        raise ValueError("No source locations are valid for every participant in this cohort.")
    return np.vstack(vectors), support


def source_validity_metadata(
    valid_source_mask: Any,
    *,
    scope: str = "participant",
    participant_count: int | None = None,
) -> dict[str, Any]:
    """Describe missing locations without changing their geometry or indices."""
    valid = np.asarray(valid_source_mask)
    if valid.dtype != np.dtype(bool) or valid.ndim != 1 or not valid.size:
        raise ValueError("Source validity mask must be a non-empty boolean vector.")
    metadata = {
        "policy": SOURCE_VALIDITY_POLICY,
        "version": SOURCE_VALIDITY_VERSION,
        "source_count": int(valid.size),
        "valid_source_count": int(np.count_nonzero(valid)),
        "invalid_source_indices": np.flatnonzero(~valid).tolist(),
        "scope": scope,
    }
    if participant_count is not None:
        metadata["participant_count"] = int(participant_count)
    return metadata


def source_values_to_json(values: Any, valid_source_mask: Any = None) -> list[float | None]:
    """Encode unavailable measurements as JSON null, never as observed zeros."""
    vector, valid = validated_source_values(values, valid_source_mask)
    return [float(value) if present else None for value, present in zip(vector, valid)]

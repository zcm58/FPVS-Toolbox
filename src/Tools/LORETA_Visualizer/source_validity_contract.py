"""Validate declared missing source values without computing source statistics."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

SOURCE_VALIDITY_POLICY = "complete_valid_source_support_v1"


def declared_source_validity(values: np.ndarray, metadata: Mapping[str, Any]) -> np.ndarray:
    """Return support after checking the additive prepared-source validity record.

    Undeclared historical payloads must be finite. Declared missing values use
    NaN in memory and JSON null on disk, while retaining original source indices.
    """
    data = np.asarray(values, dtype=float).reshape(-1)
    record = metadata.get("source_validity")
    if record is None:
        if not np.all(np.isfinite(data)):
            raise ValueError("Source values must be finite without source_validity metadata.")
        return np.ones(len(data), dtype=bool)
    if not isinstance(record, Mapping):
        raise ValueError("source_validity must be an object.")
    if record.get("policy") != SOURCE_VALIDITY_POLICY or type(record.get("version")) is not int or record["version"] != 1:
        raise ValueError("Unsupported source_validity policy/version.")
    count = record.get("source_count")
    valid_count = record.get("valid_source_count")
    if type(count) is not int or count != len(data) or type(valid_count) is not int:
        raise ValueError("source_validity counts must match source values.")
    indices = record.get("invalid_source_indices")
    if not isinstance(indices, list) or any(type(index) is not int for index in indices):
        raise ValueError("source_validity invalid indices must be integers.")
    if len(set(indices)) != len(indices) or any(index < 0 or index >= count for index in indices):
        raise ValueError("source_validity invalid indices must be unique and in bounds.")
    valid = np.ones(count, dtype=bool)
    valid[indices] = False
    if valid_count != int(valid.sum()) or valid_count < 1:
        raise ValueError("source_validity must retain a matching nonempty valid support.")
    if record.get("scope") not in {"participant", "group_complete_case"}:
        raise ValueError("source_validity requires a supported scope.")
    if record.get("scope") == "group_complete_case":
        participants = record.get("participant_count")
        if type(participants) is not int or participants < 1:
            raise ValueError("Group source_validity requires a positive participant count.")
    if not np.all(np.isfinite(data[valid])) or not np.all(np.isnan(data[~valid])):
        raise ValueError("Source values must be finite on valid support and missing only at declared invalid indices.")
    return valid

"""Missing source measurements remain missing through prepared display paths."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from Tools.LORETA_Visualizer.cortical_paint import project_cortical_surface_payload
from Tools.LORETA_Visualizer.prepared_payload_importer import prepared_source_payload_example
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PreparedSourcePayloadValidationError,
    validate_prepared_source_payload_mapping,
)
from Tools.LORETA_Visualizer.source_payloads import (
    filter_source_payload_by_mask,
    make_source_payload,
)


def _raw_payload() -> dict:
    raw = prepared_source_payload_example()
    raw.update({
        "values": [3.0, None, 5.0],
        "points": [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0]],
        "source_model": "l2_mne_fsaverage_participant_zscore_mean",
        "kind": "surface_mesh",
        "faces": [[0, 1, 2]],
        "metadata": {
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_source_indices": [0, 2],
            "source_validity": {
                "policy": "complete_valid_source_support_v1", "version": 1,
                "source_count": 3, "valid_source_count": 2,
                "invalid_source_indices": [1], "scope": "group_complete_case",
                "participant_count": 4,
            },
        },
    })
    return raw


def test_null_requires_matching_explicit_validity() -> None:
    raw = _raw_payload()
    spec = validate_prepared_source_payload_mapping(raw)
    assert np.isnan(spec.values[1])
    assert spec.values[[0, 2]].tolist() == [3.0, 5.0]
    raw["metadata"].pop("source_validity")
    with pytest.raises(PreparedSourcePayloadValidationError, match="finite"):
        validate_prepared_source_payload_mapping(raw)


@pytest.mark.parametrize("mutation", ["index", "count", "finite_missing", "nan", "version", "all_missing"])
def test_rejects_inconsistent_or_nonstandard_missing_values(mutation: str) -> None:
    raw = _raw_payload()
    record = raw["metadata"]["source_validity"]
    if mutation == "index":
        record["invalid_source_indices"] = [3]
    elif mutation == "count":
        record["valid_source_count"] = 3
    elif mutation == "finite_missing":
        raw["values"][1] = 0.0
    elif mutation == "nan":
        raw["values"][1] = float("nan")
    elif mutation == "version":
        record["version"] = 2
    else:
        raw["values"] = [None, None, None]
        record.update(valid_source_count=0, invalid_source_indices=[0, 1, 2])
    with pytest.raises(PreparedSourcePayloadValidationError):
        validate_prepared_source_payload_mapping(raw)


@pytest.mark.parametrize("mask_enabled", [False, True])
def test_cortical_hole_stays_missing_with_statistical_mask_on_or_off(mask_enabled: bool) -> None:
    raw = _raw_payload()
    spec = validate_prepared_source_payload_mapping(raw)
    payload = make_source_payload(
        points=spec.points, values=spec.values, label=spec.label, kind=spec.kind,
        source_model=spec.source_model, faces=spec.faces, metadata=spec.metadata,
        normalize_values=False,
    )
    assert len(payload.points) == 3  # Original source and triangle indices survive.
    projection = project_cortical_surface_payload(
        payload.points, payload, use_cluster_mask=mask_enabled, neighbors=3,
    )
    assert projection.values[[0, 2]].tolist() == [3.0, 5.0]
    assert np.isnan(projection.values[1])
    assert (projection.source_value_min, projection.source_value_max) == (3.0, 5.0)
    original_metadata = copy.deepcopy(payload.metadata)
    filtered = filter_source_payload_by_mask(payload, np.ones(3, dtype=bool))
    assert filtered.values.tolist() == [3.0, 5.0]
    assert filtered.metadata["cluster_mask_source_indices"] == [0, 1]
    assert filtered.metadata["source_validity"]["source_count"] == 2
    assert payload.metadata == original_metadata

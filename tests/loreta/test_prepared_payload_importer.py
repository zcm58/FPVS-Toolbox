from __future__ import annotations

import json

import numpy as np
import pytest

from Tools.LORETA_Visualizer.prepared_payload_importer import (
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    PreparedSourcePayloadImportError,
    load_prepared_source_payload_json,
    prepared_source_payload_example,
    prepared_source_payload_from_mapping,
)
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_MESH
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    MeshDisplayTransform,
)


def test_prepared_source_payload_imports_display_space_json(tmp_path) -> None:
    payload_path = tmp_path / "prepared-source.json"
    raw_payload = prepared_source_payload_example()
    payload_path.write_text(json.dumps(raw_payload), encoding="utf-8")

    payload = load_prepared_source_payload_json(
        payload_path,
        display_transform=MeshDisplayTransform.identity(),
    )

    assert payload.label == "Example prepared source payload"
    assert payload.kind == SOURCE_KIND_VOLUME_MESH
    assert payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert payload.source_model == "prepared_source_payload"
    assert payload.metadata["source_file_name"] == "prepared-source.json"
    assert payload.metadata["source_file_format"] == PREPARED_SOURCE_PAYLOAD_FORMAT
    assert np.allclose(payload.points, np.asarray(raw_payload["points"], dtype=float))
    assert np.allclose(payload.values, np.asarray(raw_payload["values"], dtype=float))
    assert np.array_equal(payload.faces, np.asarray([3, 0, 1, 2], dtype=np.int64))


def test_prepared_source_payload_imports_fsaverage_like_native_coordinates() -> None:
    native_mesh_points = np.asarray(
        [
            [-60.0, -80.0, -35.0],
            [-55.0, 45.0, 55.0],
            [58.0, -78.0, -32.0],
            [56.0, 48.0, 52.0],
            [0.0, -18.0, 76.0],
            [0.0, -22.0, -52.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        native_mesh_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    raw_payload = {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": "Native fsaverage-like payload",
        "kind": SOURCE_KIND_VOLUME_MESH,
        "coordinate_space": COORDINATE_SPACE_FSAVERAGE,
        "source_model": "prepared_volume_grid",
        "points": [[-20.0, -62.0, 8.0], [0.0, -70.0, 12.0], [22.0, -61.0, 7.0]],
        "values": [0.25, 0.75, 1.0],
        "faces": [[0, 1, 2]],
        "metadata": {"condition": "fixture-condition"},
    }

    payload = prepared_source_payload_from_mapping(raw_payload, display_transform=transform)
    expected_points = transform.to_display_points(
        np.asarray(raw_payload["points"], dtype=float),
        coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )

    assert payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert np.allclose(payload.points, expected_points)
    assert np.allclose(transform.from_display_points(payload.points), np.asarray(raw_payload["points"], dtype=float))
    assert payload.metadata["condition"] == "fixture-condition"
    assert payload.metadata["source_space"] == COORDINATE_SPACE_FSAVERAGE


def test_prepared_source_payload_import_rejects_missing_format() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload.pop("format")

    with pytest.raises(PreparedSourcePayloadImportError, match="Unsupported prepared source payload format"):
        prepared_source_payload_from_mapping(raw_payload, display_transform=MeshDisplayTransform.identity())


def test_prepared_source_payload_import_rejects_mismatched_values() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload["values"] = [0.1, 0.2]

    with pytest.raises(PreparedSourcePayloadImportError, match="one value per point"):
        prepared_source_payload_from_mapping(raw_payload, display_transform=MeshDisplayTransform.identity())


def test_prepared_source_payload_import_requires_json_extension(tmp_path) -> None:
    payload_path = tmp_path / "prepared-source.txt"
    payload_path.write_text(json.dumps(prepared_source_payload_example()), encoding="utf-8")

    with pytest.raises(PreparedSourcePayloadImportError, match=".json extension"):
        load_prepared_source_payload_json(payload_path, display_transform=MeshDisplayTransform.identity())

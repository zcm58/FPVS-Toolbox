from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from Tools.LORETA_Visualizer.prepared_payload_importer import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    load_prepared_source_manifest_json,
    load_prepared_source_payload_json,
)
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    MeshDisplayTransform,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "src" / "Tools" / "LORETA_Visualizer" / "examples"

FSAVERAGE_LIKE_NATIVE_BOUNDS = np.asarray(
    [
        [-78.0, -105.0, -58.0],
        [-74.0, 72.0, 86.0],
        [78.0, -103.0, -56.0],
        [74.0, 74.0, 84.0],
        [0.0, -45.0, 96.0],
        [0.0, -38.0, -78.0],
    ],
    dtype=float,
)


def test_checked_in_prepared_source_payload_examples_load() -> None:
    payload_paths = sorted(EXAMPLES_DIR.glob("source_payload_v1_*_example.json"))

    assert payload_paths
    for payload_path in payload_paths:
        raw_payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert raw_payload["format"] == PREPARED_SOURCE_PAYLOAD_FORMAT
        assert len(raw_payload["points"]) == len(raw_payload["values"])
        _assert_triangle_rows_are_valid(raw_payload)

        payload = load_prepared_source_payload_json(
            payload_path,
            display_transform=_display_transform_for(raw_payload["coordinate_space"]),
        )

        assert payload.coordinate_space == COORDINATE_SPACE_DISPLAY
        assert payload.metadata["source_file_name"] == payload_path.name
        assert payload.metadata["source_file_format"] == PREPARED_SOURCE_PAYLOAD_FORMAT
        assert np.all(np.isfinite(payload.points))
        assert np.all(np.isfinite(payload.values))
        assert payload.faces is not None


def test_checked_in_fsaverage_example_transforms_to_display_space() -> None:
    payload_path = EXAMPLES_DIR / "source_payload_v1_fsaverage_native_example.json"
    raw_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    transform = _display_transform_for(raw_payload["coordinate_space"])

    payload = load_prepared_source_payload_json(payload_path, display_transform=transform)
    expected_points = transform.to_display_points(
        np.asarray(raw_payload["points"], dtype=float),
        coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )

    assert raw_payload["coordinate_space"] == COORDINATE_SPACE_FSAVERAGE
    assert np.allclose(payload.points, expected_points)
    assert np.allclose(payload.values, np.asarray(raw_payload["values"], dtype=float))
    assert payload.metadata["source_space"] == COORDINATE_SPACE_FSAVERAGE


def test_checked_in_prepared_source_manifest_example_loads_payloads() -> None:
    manifest_path = EXAMPLES_DIR / "source_manifest_v1_display_conditions_example.json"
    raw_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    entries = load_prepared_source_manifest_json(manifest_path)
    payloads = [
        load_prepared_source_payload_json(entry.payload_path, display_transform=MeshDisplayTransform.identity())
        for entry in entries
    ]

    assert raw_manifest["format"] == PREPARED_SOURCE_MANIFEST_FORMAT
    assert [entry.label for entry in entries] == ["Example occipital condition", "Example frontal condition"]
    assert [entry.condition_id for entry in entries] == [
        "manifest:1:example_occipital",
        "manifest:2:example_frontal",
    ]
    assert [payload.label for payload in payloads] == [
        "Example occipital source map",
        "Example frontal source map",
    ]
    assert all(entry.payload_path.parent == EXAMPLES_DIR for entry in entries)


def _display_transform_for(coordinate_space: str) -> MeshDisplayTransform:
    if coordinate_space == COORDINATE_SPACE_DISPLAY:
        return MeshDisplayTransform.identity()
    if coordinate_space == COORDINATE_SPACE_FSAVERAGE:
        return MeshDisplayTransform.from_native_points(
            FSAVERAGE_LIKE_NATIVE_BOUNDS,
            native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
        )
    raise AssertionError(f"Unexpected example coordinate space: {coordinate_space!r}")


def _assert_triangle_rows_are_valid(raw_payload: dict[str, object]) -> None:
    faces = np.asarray(raw_payload["faces"], dtype=np.int64)
    point_count = len(raw_payload["points"])

    assert faces.ndim == 2
    assert faces.shape[1] == 3
    assert np.all(faces >= 0)
    assert int(np.max(faces)) < point_count

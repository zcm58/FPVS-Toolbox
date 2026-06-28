from __future__ import annotations

import json

import numpy as np
import pytest

from Tools.LORETA_Visualizer import prepared_payload_importer
from Tools.LORETA_Visualizer.prepared_payload_importer import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    PreparedSourcePayloadImportError,
    load_prepared_source_manifest_json,
    load_prepared_source_payload_json,
    prepared_source_manifest_example,
    prepared_source_payload_example,
    prepared_source_manifest_from_mapping,
    prepared_source_payload_from_mapping,
)
from Tools.LORETA_Visualizer.source_payloads import SOURCE_KIND_VOLUME_MESH
from Tools.LORETA_Visualizer.transforms import (
    COORDINATE_SPACE_DISPLAY,
    COORDINATE_SPACE_FSAVERAGE,
    COORDINATE_SPACE_FSAVERAGE_VOLUME,
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


def test_prepared_source_payload_json_cache_reuses_unchanged_file(monkeypatch, tmp_path) -> None:
    payload_path = tmp_path / "prepared-source.json"
    raw_payload = prepared_source_payload_example()
    payload_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    with prepared_payload_importer._PREPARED_PAYLOAD_JSON_CACHE_LOCK:
        prepared_payload_importer._PREPARED_PAYLOAD_JSON_CACHE.clear()

    original_load = prepared_payload_importer.json.load
    load_calls = 0

    def counting_load(handle):
        nonlocal load_calls
        load_calls += 1
        return original_load(handle)

    monkeypatch.setattr(prepared_payload_importer.json, "load", counting_load)

    first = load_prepared_source_payload_json(
        payload_path,
        display_transform=MeshDisplayTransform.identity(),
    )
    first.metadata["caller_mutation"] = True
    second = load_prepared_source_payload_json(
        payload_path,
        display_transform=MeshDisplayTransform.identity(),
    )

    assert load_calls == 1
    assert second.label == first.label
    assert "caller_mutation" not in second.metadata

    updated_payload = dict(raw_payload)
    updated_payload["label"] = "Updated prepared source payload"
    updated_payload["metadata"] = {"changed": True}
    payload_path.write_text(json.dumps(updated_payload) + "\n", encoding="utf-8")

    third = load_prepared_source_payload_json(
        payload_path,
        display_transform=MeshDisplayTransform.identity(),
    )

    assert load_calls == 2
    assert third.label == "Updated prepared source payload"
    assert third.metadata["changed"] is True


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


def test_prepared_source_payload_imports_fsaverage_volume_with_surface_transform() -> None:
    surface_points = np.asarray(
        [
            [-60.0, -80.0, -35.0],
            [-55.0, 45.0, 55.0],
            [58.0, -78.0, -32.0],
            [56.0, 48.0, 52.0],
        ],
        dtype=float,
    )
    transform = MeshDisplayTransform.from_native_points(
        surface_points,
        native_coordinate_space=COORDINATE_SPACE_FSAVERAGE,
    )
    raw_payload = {
        "format": PREPARED_SOURCE_PAYLOAD_FORMAT,
        "label": "eLORETA volume payload",
        "kind": "volume_points",
        "coordinate_space": COORDINATE_SPACE_FSAVERAGE_VOLUME,
        "source_model": "eloreta_volume_participant_zscore_mean",
        "value_label": "source-space z-score",
        "points": [[-20.0, -62.0, 8.0], [0.0, -70.0, 12.0], [22.0, -61.0, 7.0]],
        "values": [0.25, 0.75, 1.0],
        "metadata": {"source_method": "eloreta_volume"},
    }

    payload = prepared_source_payload_from_mapping(raw_payload, display_transform=transform)

    assert payload.coordinate_space == COORDINATE_SPACE_DISPLAY
    assert np.allclose(
        payload.points,
        transform.to_display_points(
            np.asarray(raw_payload["points"], dtype=float),
            coordinate_space=COORDINATE_SPACE_FSAVERAGE_VOLUME,
        ),
    )
    assert payload.metadata["source_space"] == COORDINATE_SPACE_FSAVERAGE_VOLUME
    assert payload.metadata["source_method"] == "eloreta_volume"


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


def test_prepared_source_manifest_loads_relative_condition_payloads(tmp_path) -> None:
    payload_a = prepared_source_payload_example()
    payload_a["label"] = "Faces source"
    payload_b = prepared_source_payload_example()
    payload_b["label"] = "Objects source"
    payload_b["points"] = [[-0.1, 0.25, 0.1], [0.0, 0.3, 0.15], [0.1, 0.25, 0.1]]
    (tmp_path / "condition_a_source.json").write_text(json.dumps(payload_a), encoding="utf-8")
    (tmp_path / "condition_b_source.json").write_text(json.dumps(payload_b), encoding="utf-8")
    manifest = prepared_source_manifest_example()
    manifest_path = tmp_path / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    entries = load_prepared_source_manifest_json(manifest_path)

    assert len(entries) == 2
    assert entries[0].label == "Condition A"
    assert entries[0].condition_id == "manifest:1:condition_a"
    assert entries[0].payload_path == tmp_path / "condition_a_source.json"
    assert entries[1].payload_path == tmp_path / "condition_b_source.json"
    assert entries[0].metadata == {"group": "demo"}

    payloads = [
        load_prepared_source_payload_json(entry.payload_path, display_transform=MeshDisplayTransform.identity())
        for entry in entries
    ]
    assert [payload.label for payload in payloads] == ["Faces source", "Objects source"]


def test_prepared_source_manifest_rejects_path_escape(tmp_path) -> None:
    outside = tmp_path.parent / "outside_source.json"
    outside.write_text(json.dumps(prepared_source_payload_example()), encoding="utf-8")
    raw_manifest = {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "conditions": [
            {
                "id": "escape",
                "label": "Escape",
                "file": "../outside_source.json",
            }
        ],
    }

    with pytest.raises(PreparedSourcePayloadImportError, match="inside the manifest folder"):
        prepared_source_manifest_from_mapping(raw_manifest, manifest_path=tmp_path / "manifest.json")


def test_prepared_source_manifest_rejects_duplicate_condition_ids(tmp_path) -> None:
    (tmp_path / "source_a.json").write_text(json.dumps(prepared_source_payload_example()), encoding="utf-8")
    (tmp_path / "source_b.json").write_text(json.dumps(prepared_source_payload_example()), encoding="utf-8")
    raw_manifest = {
        "format": PREPARED_SOURCE_MANIFEST_FORMAT,
        "conditions": [
            {"id": "same", "label": "First", "file": "source_a.json"},
            {"id": "same", "label": "Second", "file": "source_b.json"},
        ],
    }

    with pytest.raises(PreparedSourcePayloadImportError, match="Duplicate"):
        prepared_source_manifest_from_mapping(raw_manifest, manifest_path=tmp_path / "manifest.json")

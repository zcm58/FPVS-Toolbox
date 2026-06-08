from __future__ import annotations

import json
from pathlib import Path

import pytest

from Tools.LORETA_Visualizer.prepared_payload_importer import (
    prepared_source_manifest_example,
    prepared_source_payload_example,
)
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    PREPARED_SOURCE_MANIFEST_FORMAT,
    PREPARED_SOURCE_MANIFEST_SCHEMA,
    PREPARED_SOURCE_PAYLOAD_FORMAT,
    PREPARED_SOURCE_PAYLOAD_SCHEMA,
    PreparedSourcePayloadValidationError,
    validate_prepared_source_manifest_json,
    validate_prepared_source_manifest_mapping,
    validate_prepared_source_payload_json,
    validate_prepared_source_payload_mapping,
)

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "src" / "Tools" / "LORETA_Visualizer" / "examples"


def test_payload_validator_accepts_checked_in_examples() -> None:
    payload_paths = sorted(EXAMPLES_DIR.glob("source_payload_v1_*_example.json"))

    assert payload_paths
    for payload_path in payload_paths:
        payload = validate_prepared_source_payload_json(payload_path)

        assert payload.coordinate_space
        assert len(payload.points) == len(payload.values)
        assert payload.faces is not None


def test_manifest_validator_accepts_checked_in_example_with_payload_files() -> None:
    manifest = validate_prepared_source_manifest_json(
        EXAMPLES_DIR / "source_manifest_v1_display_conditions_example.json",
        require_payload_files=True,
    )

    assert manifest.label == "Example prepared source-map condition set"
    assert [condition.raw_id for condition in manifest.conditions] == ["example_occipital", "example_frontal"]
    assert all(condition.payload_path and condition.payload_path.is_file() for condition in manifest.conditions)


def test_schema_descriptors_and_json_schema_files_match_format_constants() -> None:
    payload_schema = json.loads((EXAMPLES_DIR / "source_payload_v1.schema.json").read_text(encoding="utf-8"))
    manifest_schema = json.loads((EXAMPLES_DIR / "source_manifest_v1.schema.json").read_text(encoding="utf-8"))

    assert PREPARED_SOURCE_PAYLOAD_SCHEMA["format"] == PREPARED_SOURCE_PAYLOAD_FORMAT
    assert PREPARED_SOURCE_MANIFEST_SCHEMA["format"] == PREPARED_SOURCE_MANIFEST_FORMAT
    assert payload_schema["properties"]["format"]["const"] == PREPARED_SOURCE_PAYLOAD_FORMAT
    assert manifest_schema["properties"]["format"]["const"] == PREPARED_SOURCE_MANIFEST_FORMAT
    assert sorted(payload_schema["properties"]["kind"]["enum"]) == list(PREPARED_SOURCE_PAYLOAD_SCHEMA["supported_kinds"])


def test_payload_validator_rejects_mismatched_values() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload["values"] = [0.1, 0.2]

    with pytest.raises(PreparedSourcePayloadValidationError, match="one value per point"):
        validate_prepared_source_payload_mapping(raw_payload)


def test_payload_validator_rejects_unsupported_source_kind() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload["kind"] = "unsupported_inverse_output"

    with pytest.raises(PreparedSourcePayloadValidationError, match="kind"):
        validate_prepared_source_payload_mapping(raw_payload)


def test_payload_validator_rejects_faces_that_reference_missing_points() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload["faces"] = [[0, 1, 99]]

    with pytest.raises(PreparedSourcePayloadValidationError, match="existing points"):
        validate_prepared_source_payload_mapping(raw_payload)


def test_payload_validator_rejects_negative_face_indices() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload["faces"] = [[0, 1, -1]]

    with pytest.raises(PreparedSourcePayloadValidationError, match="negative"):
        validate_prepared_source_payload_mapping(raw_payload)


def test_payload_validator_rejects_nonfinite_values() -> None:
    raw_payload = prepared_source_payload_example()
    raw_payload["values"] = [0.1, float("nan"), 0.3]

    with pytest.raises(PreparedSourcePayloadValidationError, match="finite"):
        validate_prepared_source_payload_mapping(raw_payload)


def test_manifest_validator_rejects_path_escape_without_manifest_path() -> None:
    raw_manifest = prepared_source_manifest_example()
    raw_manifest["conditions"][0]["file"] = "../condition_a_source.json"

    with pytest.raises(PreparedSourcePayloadValidationError, match="inside the manifest folder"):
        validate_prepared_source_manifest_mapping(raw_manifest)


def test_manifest_validator_rejects_windows_absolute_paths() -> None:
    raw_manifest = prepared_source_manifest_example()
    raw_manifest["conditions"][0]["file"] = "C:\\temp\\condition_a_source.json"

    with pytest.raises(PreparedSourcePayloadValidationError, match="relative paths"):
        validate_prepared_source_manifest_mapping(raw_manifest)


def test_manifest_validator_rejects_missing_payload_file_when_required(tmp_path) -> None:
    raw_manifest = prepared_source_manifest_example()

    with pytest.raises(PreparedSourcePayloadValidationError, match="payload file is missing"):
        validate_prepared_source_manifest_mapping(
            raw_manifest,
            manifest_path=tmp_path / "source_manifest.json",
            require_payload_files=True,
        )

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

import pytest

import Main_App.processing.preflight_qc_cache as cache_module
from Main_App.processing.preflight_qc_cache import (
    PREFLIGHT_QC_CACHE_SCHEMA_VERSION,
    build_preflight_qc_cache_fingerprint,
    load_preflight_qc_cache,
    preflight_qc_cache_directory,
    preflight_qc_cache_path,
    save_preflight_qc_cache,
)


def _key_parts() -> dict[str, object]:
    return {
        "file_identity": {
            "resolved_path": "D:/study/raw/P01.bdf",
            "size_bytes": 123_456,
            "mtime_ns": 987_654_321,
        },
        "settings": {
            "low_pass_hz": 50.0,
            "stim_channel": "Status",
            "time_block_seconds": 10.0,
        },
        "method": {
            "name": "condition_aware_preflight_qc",
            "version": "v2",
        },
        "event_plan": [
            {
                "condition": "Faces",
                "occurrence": 1,
                "onset_sample": 2048,
                "completion_sample": 258_048,
            }
        ],
    }


def test_fingerprint_is_deterministic_for_equivalent_mapping_order() -> None:
    parts = _key_parts()
    reordered = {
        "file_identity": {
            "mtime_ns": 987_654_321,
            "size_bytes": 123_456,
            "resolved_path": "D:/study/raw/P01.bdf",
        },
        "settings": {
            "time_block_seconds": 10.0,
            "stim_channel": "Status",
            "low_pass_hz": 50.0,
        },
        "method": {
            "version": "v2",
            "name": "condition_aware_preflight_qc",
        },
        "event_plan": [
            {
                "completion_sample": 258_048,
                "onset_sample": 2048,
                "occurrence": 1,
                "condition": "Faces",
            }
        ],
    }

    first = build_preflight_qc_cache_fingerprint(**parts)
    second = build_preflight_qc_cache_fingerprint(**reordered)

    assert first == second
    assert len(first) == 64
    assert set(first) <= set("0123456789abcdef")


@pytest.mark.parametrize(
    ("part_name", "replacement"),
    [
        (
            "file_identity",
            {
                "resolved_path": "D:/study/raw/P01.bdf",
                "size_bytes": 123_457,
                "mtime_ns": 987_654_321,
            },
        ),
        (
            "settings",
            {
                "low_pass_hz": 100.0,
                "stim_channel": "Status",
                "time_block_seconds": 10.0,
            },
        ),
        (
            "method",
            {"name": "condition_aware_preflight_qc", "version": "v3"},
        ),
        (
            "event_plan",
            [
                {
                    "condition": "Faces",
                    "occurrence": 1,
                    "onset_sample": 4096,
                    "completion_sample": 258_048,
                }
            ],
        ),
    ],
)
def test_fingerprint_changes_with_each_input_category(
    part_name: str,
    replacement: object,
) -> None:
    baseline_parts = _key_parts()
    baseline = build_preflight_qc_cache_fingerprint(**baseline_parts)
    changed_parts = {**baseline_parts, part_name: replacement}

    assert build_preflight_qc_cache_fingerprint(**changed_parts) != baseline


def test_cache_path_is_project_local_and_read_does_not_create_it(tmp_path: Path) -> None:
    parts = _key_parts()
    expected_directory = tmp_path / ".fpvs_processing" / "preflight_qc" / "v2"

    path = preflight_qc_cache_path(tmp_path, **parts)

    assert path.parent == expected_directory
    assert path.suffix == ".json"
    assert not expected_directory.exists()
    assert load_preflight_qc_cache(tmp_path, **parts) is None
    assert not expected_directory.exists()


def test_cache_rejects_relative_project_root() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        preflight_qc_cache_directory(Path("relative-project"))


def test_cache_round_trip_uses_atomic_project_local_json(tmp_path: Path) -> None:
    parts = _key_parts()
    result = {
        "participant_id": "P01",
        "group_id": "control",
        "conditions": [{"condition": "Faces", "status": "pass"}],
    }

    path = save_preflight_qc_cache(tmp_path, result=result, **parts)

    assert path.parent == tmp_path / ".fpvs_processing" / "preflight_qc" / "v2"
    assert not list(path.parent.glob("*.tmp"))
    envelope = json.loads(path.read_text(encoding="utf-8"))
    assert envelope["schema_version"] == PREFLIGHT_QC_CACHE_SCHEMA_VERSION
    assert envelope["fingerprint"] == path.stem
    assert envelope["key"]["file_identity"] == parts["file_identity"]
    assert load_preflight_qc_cache(tmp_path, **parts) == result


def test_same_fingerprint_concurrent_writers_leave_one_valid_entry(
    tmp_path: Path,
) -> None:
    parts = _key_parts()
    result = {"participant_id": "P01", "status": "pass"}

    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(
            executor.map(
                lambda _index: save_preflight_qc_cache(
                    tmp_path,
                    result=result,
                    **parts,
                ),
                range(8),
            )
        )

    assert len(set(paths)) == 1
    assert list(paths[0].parent.glob("*.json")) == [paths[0]]
    assert not list(paths[0].parent.glob("*.tmp"))
    assert load_preflight_qc_cache(tmp_path, **parts) == result


def test_cache_returns_safe_miss_for_corrupt_json(tmp_path: Path) -> None:
    parts = _key_parts()
    path = preflight_qc_cache_path(tmp_path, **parts)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    assert load_preflight_qc_cache(tmp_path, **parts) is None


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(schema_version=999),
        lambda payload: payload.update(fingerprint="0" * 64),
        lambda payload: payload["key"]["settings"].update(low_pass_hz=100.0),
        lambda payload: payload.update(result=["not", "a", "mapping"]),
    ],
)
def test_cache_returns_safe_miss_for_invalid_envelope(
    tmp_path: Path,
    mutation,
) -> None:
    parts = _key_parts()
    path = save_preflight_qc_cache(tmp_path, result={"status": "pass"}, **parts)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    mutation(envelope)
    path.write_text(json.dumps(envelope), encoding="utf-8")

    assert load_preflight_qc_cache(tmp_path, **parts) is None


def test_atomic_replace_failure_removes_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    parts = _key_parts()

    def fail_replace(_source, _destination) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(cache_module.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replace failure"):
        save_preflight_qc_cache(tmp_path, result={"status": "pass"}, **parts)

    cache_directory = preflight_qc_cache_directory(tmp_path)
    assert not list(cache_directory.glob("*.tmp"))
    assert not list(cache_directory.glob("*.json"))


def test_non_json_cache_input_fails_before_project_directory_creation(
    tmp_path: Path,
) -> None:
    parts = _key_parts()
    parts["settings"] = {"unsupported": object()}

    with pytest.raises(TypeError):
        save_preflight_qc_cache(tmp_path, result={"status": "pass"}, **parts)

    assert not (tmp_path / ".fpvs_processing").exists()

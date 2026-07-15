from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    L2MNEHaukParticipantZScoreValues,
)
from Tools.LORETA_Visualizer.source_producers.source_psd_cache import (
    CACHE_STATUS_HIT,
    CACHE_STATUS_MISS_ARRAYS_INVALID,
    CACHE_STATUS_MISS_ARRAYS_SCHEMA,
    CACHE_STATUS_MISS_ARRAYS_UNREADABLE,
    CACHE_STATUS_MISS_ARRAY_CHECKSUM,
    CACHE_STATUS_MISS_KEY,
    CACHE_STATUS_MISS_METADATA_UNREADABLE,
    CACHE_STATUS_MISS_NOT_FOUND,
    CACHE_STATUS_MISS_PARTIAL,
    CACHE_STATUS_MISS_SCHEMA,
    SOURCE_PSD_CACHE_FORMAT,
    SOURCE_PSD_CACHE_RELATIVE_ROOT,
    SourcePsdCacheKeyInputs,
    SourcePsdParticipantResult,
    build_source_psd_cache_key,
    cleanup_source_psd_cache_temp_files,
    load_source_psd_cache_entry,
    source_psd_cache_root,
    store_source_psd_cache_entry,
)


def test_cache_key_is_canonical_and_tracks_all_scientific_inputs() -> None:
    common = {
        "derivative_checksum_sha256": "a" * 64,
        "method_metadata": {"lambda2": 1.0 / 9.0, "offsets": (-10, -2, 2, 10)},
        "frequency_metadata": {"n_times": 15360, "sfreq": 256.0},
    }
    first = build_source_psd_cache_key(
        **common,
        numerical_model_metadata={"spacing": "ico3", "mindist_mm": 5.0},
    )
    reordered = build_source_psd_cache_key(
        **common,
        numerical_model_metadata={"mindist_mm": 5.0, "spacing": "ico3"},
    )

    assert first == reordered
    assert len(first) == 64
    assert first != build_source_psd_cache_key(
        **common,
        numerical_model_metadata={"spacing": "ico4", "mindist_mm": 5.0},
    )
    assert first != build_source_psd_cache_key(
        **{**common, "derivative_checksum_sha256": "b" * 64},
        numerical_model_metadata={"spacing": "ico3", "mindist_mm": 5.0},
    )
    with pytest.raises(ValueError, match="NaN or infinity"):
        build_source_psd_cache_key(
            **common,
            numerical_model_metadata={"invalid": np.nan},
        )


def test_cache_root_requires_absolute_existing_project_and_stays_confined(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()

    assert source_psd_cache_root(project_root) == project_root / SOURCE_PSD_CACHE_RELATIVE_ROOT
    with pytest.raises(ValueError, match="absolute path"):
        source_psd_cache_root(Path("relative-project"))
    with pytest.raises(FileNotFoundError, match="Project root does not exist"):
        source_psd_cache_root(tmp_path / "Missing")


def test_cache_round_trip_reconstructs_participant_values_and_stores_only_compact_arrays(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    key_inputs = _key_inputs()
    participant = _participant_result()

    write_result = store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=participant,
    )
    lookup = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)

    assert write_result.paths.root == project_root / SOURCE_PSD_CACHE_RELATIVE_ROOT
    assert write_result.paths.arrays_path.is_file()
    assert write_result.paths.metadata_path.is_file()
    assert lookup.status == CACHE_STATUS_HIT
    assert lookup.hit
    assert lookup.result is not None
    assert lookup.result.participant_id == "P01"
    assert np.array_equal(lookup.result.values, participant.values)
    assert np.array_equal(lookup.result.target_source_values, participant.target_source_values)
    assert np.array_equal(lookup.result.noise_mean_values, participant.noise_mean_values)
    assert np.array_equal(lookup.result.noise_std_values, participant.noise_std_values)
    assert lookup.result.noise_offsets_used == participant.noise_offsets_used
    assert lookup.result.metadata == {"condition": "Color Response"}

    reconstructed = lookup.result.to_l2_mne_participant_zscore_values()
    assert isinstance(reconstructed, L2MNEHaukParticipantZScoreValues)
    assert reconstructed.participant_id == "P01"
    assert np.array_equal(reconstructed.values, participant.values)

    with np.load(write_result.paths.arrays_path, allow_pickle=False) as archive:
        assert set(archive.files) == {
            "values",
            "target_source_values",
            "noise_mean_values",
            "noise_std_values",
            "noise_offsets_used",
        }


def test_missing_partial_and_temp_files_are_cache_misses(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    key_inputs = _key_inputs()

    missing = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert missing.status == CACHE_STATUS_MISS_NOT_FOUND
    assert not missing.hit

    missing.paths.root.mkdir(parents=True)
    temp_path = missing.paths.root / f".{missing.cache_key}.orphan.npz.tmp"
    temp_path.write_bytes(b"partial")
    still_missing = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert still_missing.status == CACHE_STATUS_MISS_NOT_FOUND
    assert cleanup_source_psd_cache_temp_files(project_root) == 1
    assert not temp_path.exists()

    missing.paths.arrays_path.write_bytes(b"partial-final")
    partial = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert partial.status == CACHE_STATUS_MISS_PARTIAL


@pytest.mark.parametrize(
    ("field", "value", "expected_status"),
    [
        ("format", "wrong-schema", CACHE_STATUS_MISS_SCHEMA),
        ("cache_key", "0" * 64, CACHE_STATUS_MISS_KEY),
        ("key_payload", {"wrong": True}, CACHE_STATUS_MISS_KEY),
    ],
)
def test_metadata_schema_and_key_mismatches_are_cache_misses(
    tmp_path: Path,
    field: str,
    value: object,
    expected_status: str,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    key_inputs = _key_inputs()
    write_result = store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )
    metadata = _read_metadata(write_result.paths.metadata_path)
    metadata[field] = value
    _write_metadata(write_result.paths.metadata_path, metadata)

    lookup = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)

    assert lookup.status == expected_status
    assert not lookup.hit
    assert lookup.result is None


def test_unreadable_metadata_and_array_checksum_mismatch_are_cache_misses(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    key_inputs = _key_inputs()
    write_result = store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )
    write_result.paths.metadata_path.write_text("{not-json", encoding="utf-8")

    unreadable = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)

    assert unreadable.status == CACHE_STATUS_MISS_METADATA_UNREADABLE

    store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )
    with write_result.paths.arrays_path.open("ab") as stream:
        stream.write(b"tampered")
    checksum_miss = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert checksum_miss.status == CACHE_STATUS_MISS_ARRAY_CHECKSUM


def test_array_schema_shape_and_nonfinite_mismatches_are_cache_misses(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    key_inputs = _key_inputs()
    write_result = store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )

    write_result.paths.arrays_path.write_bytes(b"not-an-npz-archive")
    metadata = _read_metadata(write_result.paths.metadata_path)
    metadata["arrays_sha256"] = hashlib.sha256(write_result.paths.arrays_path.read_bytes()).hexdigest()
    _write_metadata(write_result.paths.metadata_path, metadata)
    unreadable_miss = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert unreadable_miss.status == CACHE_STATUS_MISS_ARRAYS_UNREADABLE

    store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )

    _rewrite_arrays_and_checksum(
        write_result.paths.arrays_path,
        write_result.paths.metadata_path,
        {
            "values": np.asarray([1.0, 2.0, 3.0]),
        },
    )
    schema_miss = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert schema_miss.status == CACHE_STATUS_MISS_ARRAYS_SCHEMA

    store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )
    arrays = _valid_array_payload()
    arrays["target_source_values"] = np.asarray([1.0, 2.0])
    _rewrite_arrays_and_checksum(
        write_result.paths.arrays_path,
        write_result.paths.metadata_path,
        arrays,
    )
    shape_miss = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert shape_miss.status == CACHE_STATUS_MISS_ARRAYS_INVALID

    store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=key_inputs,
        result=_participant_result(),
    )
    arrays = _valid_array_payload()
    arrays["values"] = np.asarray([1.0, np.nan, 3.0])
    _rewrite_arrays_and_checksum(
        write_result.paths.arrays_path,
        write_result.paths.metadata_path,
        arrays,
    )
    nonfinite_miss = load_source_psd_cache_entry(project_root=project_root, key_inputs=key_inputs)
    assert nonfinite_miss.status == CACHE_STATUS_MISS_ARRAYS_INVALID


def test_cache_metadata_identifies_format_and_integrity_checksum(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    write_result = store_source_psd_cache_entry(
        project_root=project_root,
        key_inputs=_key_inputs(),
        result=_participant_result(),
    )

    metadata = _read_metadata(write_result.paths.metadata_path)

    assert metadata["format"] == SOURCE_PSD_CACHE_FORMAT
    assert metadata["cache_key"] == write_result.cache_key
    assert metadata["arrays_file"] == write_result.paths.arrays_path.name
    assert metadata["arrays_sha256"] == hashlib.sha256(write_result.paths.arrays_path.read_bytes()).hexdigest()
    assert metadata["source_count"] == 3
    assert metadata["zero_noise_sd_source_count"] == 1


def _key_inputs() -> SourcePsdCacheKeyInputs:
    return SourcePsdCacheKeyInputs(
        derivative_checksum_sha256="a" * 64,
        numerical_model_metadata={
            "model": "fsaverage_biosemi64",
            "spacing": "ico3",
            "mne_version": "1.9.0",
        },
        method_metadata={
            "method": "MNE",
            "lambda2": 1.0 / 9.0,
            "noise_offsets": [*range(-10, -1), *range(2, 11)],
        },
        frequency_metadata={
            "sfreq": 256.0,
            "n_times": 12800,
            "selected_harmonics_hz": [1.2, 2.4, 3.6],
        },
    )


def _participant_result() -> SourcePsdParticipantResult:
    return SourcePsdParticipantResult(
        participant_id="P01",
        values=np.asarray([1.5, -0.5, 2.0]),
        target_source_values=np.asarray([3.0, 2.0, 4.0]),
        noise_mean_values=np.asarray([1.0, 2.5, 1.5]),
        noise_std_values=np.asarray([0.5, 0.25, 1.0]),
        noise_offsets_used=(*range(-10, -1), *range(2, 11)),
        zero_noise_sd_source_count=1,
        metadata={"condition": "Color Response"},
    )


def _valid_array_payload() -> dict[str, np.ndarray]:
    result = _participant_result()
    return {
        "values": result.values,
        "target_source_values": result.target_source_values,
        "noise_mean_values": result.noise_mean_values,
        "noise_std_values": result.noise_std_values,
        "noise_offsets_used": np.asarray(result.noise_offsets_used, dtype=np.int64),
    }


def _read_metadata(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _write_metadata(path: Path, metadata: dict[str, object]) -> None:
    path.write_text(json.dumps(metadata, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _rewrite_arrays_and_checksum(
    arrays_path: Path,
    metadata_path: Path,
    arrays: dict[str, np.ndarray],
) -> None:
    with arrays_path.open("wb") as stream:
        np.savez_compressed(stream, **arrays)
    metadata = _read_metadata(metadata_path)
    metadata["arrays_sha256"] = hashlib.sha256(arrays_path.read_bytes()).hexdigest()
    _write_metadata(metadata_path, metadata)

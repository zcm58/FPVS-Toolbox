from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers import source_psd_cache as cache_module
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
    source_psd_cache_scope,
    scientific_source_psd_method_metadata,
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


def test_cache_key_ignores_selection_provenance_but_keeps_numerical_inputs() -> None:
    method_metadata = {
        "method_id": "l2_mne_hauk_source_psd_cortical_normal_v1",
        "lambda2": 1.0 / 9.0,
        "custom_metadata": {
            "harmonic_selection": {
                "selected_harmonics_hz": [1.2, 2.4, 3.6],
                "selection_z_by_harmonic": {"1.2": 3.5, "2.4": 2.1, "3.6": 1.9},
                "selection_cache_source": "computed_this_run",
                "selection_cache_saved_at": "2026-07-16T10:00:00Z",
                "selection_cache_key": "first-selection-cache-key",
                "selection_fingerprint": "a" * 64,
            }
        },
    }
    recalculated_metadata = json.loads(json.dumps(method_metadata))
    recalculated_selection = recalculated_metadata["custom_metadata"][
        "harmonic_selection"
    ]
    recalculated_selection.update(
        {
            "selection_cache_source": "saved_processing_metadata",
            "selection_cache_saved_at": "2026-07-16T11:00:00Z",
            "selection_cache_key": "second-selection-cache-key",
            "selection_fingerprint": "b" * 64,
        }
    )

    common = {
        "derivative_checksum_sha256": "a" * 64,
        "numerical_model_metadata": {"spacing": "ico3"},
        "frequency_metadata": {"n_times": 15360, "sfreq": 256.0},
    }
    first = SourcePsdCacheKeyInputs(method_metadata=method_metadata, **common)
    recalculated = SourcePsdCacheKeyInputs(
        method_metadata=recalculated_metadata,
        **common,
    )

    assert first.cache_key == recalculated.cache_key
    cached_selection = first.method_metadata["custom_metadata"]["harmonic_selection"]
    assert set(cached_selection).isdisjoint(
        {
            "selection_cache_source",
            "selection_cache_saved_at",
            "selection_cache_key",
            "selection_fingerprint",
        }
    )
    assert (
        method_metadata["custom_metadata"]["harmonic_selection"][
            "selection_cache_source"
        ]
        == "computed_this_run"
    )
    assert scientific_source_psd_method_metadata(method_metadata) == first.method_metadata

    scientifically_changed = json.loads(json.dumps(recalculated_metadata))
    scientifically_changed["custom_metadata"]["harmonic_selection"][
        "selected_harmonics_hz"
    ] = [1.2, 2.4, 3.6, 4.8]
    changed = SourcePsdCacheKeyInputs(
        method_metadata=scientifically_changed,
        **common,
    )
    assert changed.cache_key != first.cache_key


def test_legacy_selection_fingerprint_keys_reuse_verified_arrays_without_writing(tmp_path):
    inputs = _selection_key_inputs()
    legacy_paths = _store_legacy_entry(tmp_path, inputs, selection_fingerprint="b" * 64)
    before = {path.name: path.read_bytes() for path in legacy_paths.root.iterdir()}

    lookup = load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs)

    assert lookup.hit
    assert lookup.cache_key == inputs.cache_key
    assert lookup.paths == legacy_paths
    np.testing.assert_array_equal(lookup.result.values, _participant_result().values)
    assert {path.name: path.read_bytes() for path in legacy_paths.root.iterdir()} == before


@pytest.mark.parametrize("changed", ["derivative", "model", "method", "bins", "harmonics"])
def test_legacy_cache_does_not_reuse_changed_numerical_inputs(tmp_path, changed):
    inputs = _selection_key_inputs()
    _store_legacy_entry(tmp_path, inputs)
    payload = inputs.canonical_payload()
    payload.pop("format")
    if changed == "derivative":
        payload["derivative_checksum_sha256"] = "c" * 64
    elif changed == "model":
        payload["numerical_model_metadata"]["spacing"] = "ico4"
    elif changed == "method":
        payload["method_metadata"]["lambda2"] = 0.25
    elif changed == "bins":
        payload["frequency_metadata"]["n_times"] = 25600
    else:
        payload["method_metadata"]["custom_metadata"]["harmonic_selection"][
            "selected_harmonics_hz"
        ] = [1.2]

    lookup = load_source_psd_cache_entry(
        project_root=tmp_path, key_inputs=SourcePsdCacheKeyInputs(**payload)
    )

    assert not lookup.hit


@pytest.mark.parametrize("tampered", ["metadata", "arrays"])
def test_legacy_hits_revalidate_metadata_and_arrays_in_same_scope(tmp_path, tampered):
    inputs = _selection_key_inputs()
    paths = _store_legacy_entry(tmp_path, inputs)
    with source_psd_cache_scope():
        assert load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs).hit
        if tampered == "metadata":
            metadata = _read_metadata(paths.metadata_path)
            metadata["key_payload"]["method_metadata"]["lambda2"] = 0.25
            _write_metadata(paths.metadata_path, metadata)
        else:
            paths.arrays_path.write_bytes(b"corrupt archive")
        assert not load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs).hit


def test_legacy_index_is_scoped_and_new_exact_writes_remain_visible(tmp_path, monkeypatch):
    inputs = _selection_key_inputs()
    _store_legacy_entry(tmp_path, inputs)
    real_build = cache_module._build_legacy_source_psd_index
    indexed_roots = []

    def track_build(root):
        indexed_roots.append(root)
        return real_build(root)

    monkeypatch.setattr(cache_module, "_build_legacy_source_psd_index", track_build)
    with source_psd_cache_scope():
        first = load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs)
        with source_psd_cache_scope():
            assert load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs).hit
        assert len(indexed_roots) == 1
        written = store_source_psd_cache_entry(
            project_root=tmp_path, key_inputs=inputs, result=_participant_result()
        )
        exact = load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs)
        assert exact.paths == written.paths
        assert exact.paths != first.paths
        assert len(indexed_roots) == 1
        written.paths.arrays_path.unlink()
        written.paths.metadata_path.unlink()
    with source_psd_cache_scope():
        assert load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs).hit
    assert len(indexed_roots) == 2


def test_corrupt_exact_entry_is_not_hidden_by_legacy_fallback(tmp_path):
    inputs = _selection_key_inputs()
    _store_legacy_entry(tmp_path, inputs)
    written = store_source_psd_cache_entry(
        project_root=tmp_path, key_inputs=inputs, result=_participant_result()
    )
    written.paths.arrays_path.write_bytes(b"corrupt current archive")

    lookup = load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs)

    assert lookup.status == CACHE_STATUS_MISS_ARRAY_CHECKSUM
    assert not lookup.hit


def test_legacy_index_never_reuses_another_projects_entries(tmp_path):
    first_root = tmp_path / "First"
    second_root = tmp_path / "Second"
    first_root.mkdir()
    second_root.mkdir()
    inputs = _selection_key_inputs()
    _store_legacy_entry(first_root, inputs)

    with source_psd_cache_scope():
        assert load_source_psd_cache_entry(project_root=first_root, key_inputs=inputs).hit
        assert not load_source_psd_cache_entry(project_root=second_root, key_inputs=inputs).hit


@pytest.mark.parametrize(
    "limit", ["_LEGACY_INDEX_MAX_FILES", "_LEGACY_INDEX_MAX_BYTES", "_LEGACY_METADATA_MAX_BYTES"]
)
def test_legacy_discovery_limits_fall_back_to_recalculation(tmp_path, monkeypatch, limit):
    inputs = _selection_key_inputs()
    _store_legacy_entry(tmp_path, inputs)
    monkeypatch.setattr(cache_module, limit, 0)

    assert not load_source_psd_cache_entry(project_root=tmp_path, key_inputs=inputs).hit


def _selection_key_inputs():
    payload = _key_inputs().canonical_payload()
    payload.pop("format")
    payload["method_metadata"]["custom_metadata"] = {
        "harmonic_selection": {
            "selected_harmonics_hz": [1.2, 2.4, 3.6],
            "selection_fingerprint": "a" * 64,
        }
    }
    return SourcePsdCacheKeyInputs(**payload)


def _store_legacy_entry(project_root, inputs, *, selection_fingerprint="a" * 64):
    written = store_source_psd_cache_entry(
        project_root=project_root, key_inputs=inputs, result=_participant_result()
    )
    metadata = _read_metadata(written.paths.metadata_path)
    metadata["key_payload"]["method_metadata"]["custom_metadata"]["harmonic_selection"][
        "selection_fingerprint"
    ] = selection_fingerprint
    legacy_key = hashlib.sha256(
        json.dumps(metadata["key_payload"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    paths = cache_module.source_psd_cache_paths(project_root, legacy_key)
    metadata["cache_key"] = legacy_key
    metadata["arrays_file"] = paths.arrays_path.name
    written.paths.arrays_path.replace(paths.arrays_path)
    written.paths.metadata_path.unlink()
    _write_metadata(paths.metadata_path, metadata)
    return paths


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

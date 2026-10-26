"""Focused, non-Qt numerical and publication contracts for the BIDS boundary."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path

import mne
import numpy as np
import pytest

from Main_App.io.bids_import import prepare_bids_recording, read_bids_recording
from Main_App.io.brain_products import close_brain_products_raw, read_brain_products_raw
from tests.bdf_factory import write_bdf
from tests.test_brain_products_reader import _with_captrak_header, _write_bvcdf, _write_bvrf

BP = {"hardware_platform": "brain_products", "hardware_confirmed": True}


def test_bdf_import_is_byte_exact_and_restores_annotations(tmp_path):
    values = [0, -1, 8388607, -8388608] + [7] * 246
    status = [0, 123, 123, 0] + [0] * 246
    source = write_bdf(tmp_path / "native.bdf", record_onsets=("0",),
                       annotations=((b"+0.1\x15" b"0.02\x14note\x14\x00",),),
                       signal_values={"Fz": [values], "Status": [status]})
    prepared = prepare_bids_recording(source, project_root=tmp_path)
    assert prepared.header_path.read_bytes() == source.read_bytes()
    assert prepared.conversion_seconds > 0
    assert prepared.identity_seconds > 0
    with mne.io.read_raw_bdf(source, preload=False, verbose=False) as old, read_bids_recording(prepared) as new:
        np.testing.assert_array_equal(old.get_data(), new.get_data())
        np.testing.assert_array_equal(old.annotations.onset, new.annotations.onset)
        np.testing.assert_array_equal(old.annotations.duration, new.annotations.duration)
        assert list(old.annotations.description) == list(new.annotations.description)
        assert old.annotations.orig_time == new.annotations.orig_time
        assert old.info["subject_info"] == new.info["subject_info"]
        assert not new.preload
    reused = prepare_bids_recording(source, project_root=tmp_path)
    assert reused.reused and reused.conversion_seconds == 0
    assert reused.header_path == prepared.header_path


@pytest.mark.parametrize("writer", [_write_bvcdf, _write_bvrf])
def test_brain_products_import_preserves_samples_and_all_marker_types(tmp_path, writer):
    source, _ = writer(tmp_path)
    prepared = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    with read_brain_products_raw(source) as old, read_bids_recording(prepared) as new:
        np.testing.assert_array_equal(old.get_data(), new.get_data())
        np.testing.assert_array_equal(old.annotations.onset, new.annotations.onset)
        assert list(old.annotations.description) == list(new.annotations.description)
        assert new.ch_names == old.ch_names
        assert not new.preload
        assert new._fpvs_brain_products_events.tolist() == [[0, 0, 1], [5, 0, 2]]
    if source.suffix == ".bvrh":
        assert prepared.representation == "bvrf_fif64_derivative"
        assert prepared.header_path.suffix == ".fif"
        assert (prepared.dataset_root / "dataset_description.json").is_file()


def test_bvrf_double_nonlinear_calibration_stays_bitwise_exact(tmp_path):
    source, _ = _write_bvrf(tmp_path, dtype="Double")
    header = json.loads(source.read_text())
    header["EEGModality"]["Channels"][0]["Coefficients"] = {"Num": [0.123456789, 2.234567891], "Denom": [1, 0.12345]}
    source.write_text(json.dumps(header))
    np.linspace(-0.123456789123, 12.345678912345, 20, dtype="<f8").tofile(source.with_suffix(".bvrd"))
    prepared = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    with read_brain_products_raw(source) as old, read_bids_recording(prepared) as new:
        np.testing.assert_array_equal(old.get_data(), new.get_data())


def test_bvrf_fiducials_and_native_metadata_survive_fif_precision_roundtrip(tmp_path):
    source, _ = _write_bvrf(tmp_path)
    _with_captrak_header(source)
    prepared = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    with read_brain_products_raw(source) as old, read_bids_recording(prepared) as new:
        for before, after in zip(old.info["dig"], new.info["dig"], strict=True):
            np.testing.assert_array_equal(before["r"], after["r"])
        assert old._fpvs_brain_products_header == new._fpvs_brain_products_header
        assert old._fpvs_brain_products_marker_rows == new._fpvs_brain_products_marker_rows


@pytest.mark.parametrize("writer", [_write_bvcdf, _write_bvrf])
def test_brain_products_preload_mapping_is_owned_and_releasable(tmp_path, writer):
    source, _ = writer(tmp_path)
    prepared = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    mmap = tmp_path / "samples.dat"
    raw = read_bids_recording(prepared, preload=str(mmap))
    try:
        assert isinstance(raw._data, np.memmap)
        assert raw.ch_names[-1] == "Status"
    finally:
        close_brain_products_raw(raw)
    mmap.unlink()


def test_companion_or_cached_payload_changes_cannot_reuse_old_import(tmp_path):
    source, _ = _write_bvcdf(tmp_path)
    first = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    first.header_path.with_suffix(".eeg").write_bytes(bytes(40))
    repaired = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    assert not repaired.reused
    assert repaired.header_path != first.header_path
    (tmp_path / "signal.eeg").write_bytes(bytes(40))
    changed = prepare_bids_recording(source, project_root=tmp_path, settings=BP)
    assert changed.source_identity != repaired.source_identity
    assert changed.header_path != repaired.header_path


def test_mne_bids_reader_upgrade_invalidates_import_cache(tmp_path, monkeypatch):
    import mne_bids

    source = write_bdf(tmp_path / "native.bdf", variant="BDF", record_onsets=("0",))
    first = prepare_bids_recording(source, project_root=tmp_path)
    monkeypatch.setattr(mne_bids, "__version__", "future-reader-version")
    upgraded = prepare_bids_recording(source, project_root=tmp_path)
    assert not upgraded.reused
    assert upgraded.header_path != first.header_path
    assert upgraded.source_identity == first.source_identity


def test_concurrent_imports_publish_complete_independent_datasets(tmp_path):
    source = write_bdf(tmp_path / "native.bdf", variant="BDF", record_onsets=("0",))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: prepare_bids_recording(source, project_root=tmp_path), range(2)))
    for prepared in results:
        assert prepared.header_path.read_bytes() == source.read_bytes()
        with read_bids_recording(prepared, extra_params={"include": ["Fz"]}) as raw:
            assert raw.ch_names == ["Fz"]


@pytest.mark.parametrize("failed_attempts", [1, 5])
def test_import_publication_recovers_from_brief_permission_locks(tmp_path, monkeypatch, failed_attempts):
    from Main_App.io import atomic_write as publication

    source = write_bdf(tmp_path / "native.bdf", variant="BDF", record_onsets=("0",))
    before = source.read_bytes()
    original_rename = publication.os.rename
    attempts = []
    delays = []

    def temporarily_denied(staging, target):
        attempts.append((staging, target))
        assert staging.parent == target.parent == tmp_path / ".fpvs_cache" / "bids-import"
        manifest = json.loads((staging / "import.json").read_text())
        assert manifest["outputs"]
        assert not target.exists()
        if len(attempts) <= failed_attempts:
            raise PermissionError("brief publication lock")
        original_rename(staging, target)

    monkeypatch.setattr(publication.os, "rename", temporarily_denied)
    monkeypatch.setattr(publication.time, "sleep", delays.append)
    prepared = prepare_bids_recording(source, project_root=tmp_path)
    assert len(attempts) == failed_attempts + 1
    assert len(set(attempts)) == 1
    assert delays == [0.01, 0.02, 0.05, 0.1, 0.1][:failed_attempts]
    assert source.read_bytes() == prepared.header_path.read_bytes() == before
    reused = prepare_bids_recording(source, project_root=tmp_path)
    assert reused.reused and reused.header_path == prepared.header_path
    assert not list(prepared.manifest_path.parent.parent.glob(".import-*"))


@pytest.mark.parametrize("failure", [PermissionError("persistent lock"), OSError("publication failed")])
def test_import_publication_failure_is_bounded_and_cleans_only_own_staging(tmp_path, monkeypatch, failure):
    from Main_App.io import atomic_write as publication

    source = write_bdf(tmp_path / "native.bdf", variant="BDF", record_onsets=("0",))
    before = source.read_bytes()
    cache = tmp_path / ".fpvs_cache" / "bids-import"
    preserved = cache / "independent-publication" / "payload"
    preserved.parent.mkdir(parents=True)
    preserved.write_bytes(b"another reader owns this")
    attempts = []
    delays = []

    def denied(staging, target):
        attempts.append((staging, target))
        assert (staging / "import.json").is_file()
        assert not target.exists()
        raise failure

    monkeypatch.setattr(publication.os, "rename", denied)
    monkeypatch.setattr(publication.time, "sleep", delays.append)
    with pytest.raises(type(failure)) as error:
        prepare_bids_recording(source, project_root=tmp_path)
    assert error.value is failure
    permission_failure = isinstance(failure, PermissionError)
    assert len(attempts) == (6 if permission_failure else 1)
    assert delays == ([0.01, 0.02, 0.05, 0.1, 0.1] if permission_failure else [])
    assert source.read_bytes() == before
    assert preserved.read_bytes() == b"another reader owns this"
    assert set(cache.iterdir()) == {preserved.parent}


def test_external_cache_link_is_rejected(tmp_path):
    source = write_bdf(tmp_path / "native.bdf", variant="BDF", record_onsets=("0",))
    project = tmp_path / "project"
    project.mkdir()
    try:
        (project / ".fpvs_cache").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not allow directory symlinks")
    with pytest.raises(ValueError, match="active project"):
        prepare_bids_recording(source, project_root=project)


@pytest.mark.skipif(os.name != "nt", reason="Windows extended-length path spelling")
def test_extended_windows_path_prefix_does_not_reject_contained_cache(tmp_path, monkeypatch):
    from Main_App.io.bids_import import _contained

    root = tmp_path.resolve()
    target = root / ".fpvs_cache" / "bids-import"
    extended = Path("\\\\?\\" + str(target))
    original = type(target).resolve
    monkeypatch.setattr(type(target), "resolve", lambda self, *args, **kwargs: extended if self == target else original(self, *args, **kwargs))
    assert _contained(target, root) == extended


def test_subset_preload_retains_new_disk_mapping(tmp_path):
    source = write_bdf(tmp_path / "native.bdf", variant="BDF", record_onsets=("0",), eeg_names=("Fz", "Cz"))
    prepared = prepare_bids_recording(source, project_root=tmp_path)
    mmap = tmp_path / "samples.dat"
    raw = read_bids_recording(prepared, preload=str(mmap), extra_params={"include": ["Cz", "Status"]})
    try:
        assert raw.ch_names == ["Cz", "Status"]
        assert isinstance(raw._data, np.memmap)
        assert raw._data._mmap is not None
        assert raw._data.shape == (2, 250)
    finally:
        close_brain_products_raw(raw)
    mmap.unlink()
    with pytest.raises(FileExistsError):
        read_bids_recording(prepared, preload=str(source))

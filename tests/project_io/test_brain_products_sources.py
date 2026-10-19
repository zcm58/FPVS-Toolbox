"""Project discovery and freshness of multi-file EEG recordings."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.io.file_filters import is_bdf_file, is_eeg_recording_file
from Main_App.io.recording_sources import companion_identity
from Main_App.processing.processing_controller import discover_raw_files, register_participants
from Main_App.processing.processing_ledger import raw_file_metadata
from Main_App.processing.preflight_qc import _preflight_file_identity
from Main_App.projects.hardware import confirm_hardware_selection
from Main_App.projects.project import Project
from Main_App.workers.process_runner import _preproc_cache_key, _preproc_cache_payload


pytestmark = pytest.mark.project_io

_INVALID_HARDWARE = [
    pytest.param(
        {"hardware_platform": "biosemi", "hardware_confirmed": False},
        "Confirm this project's EEG hardware", id="unconfirmed",
    ),
    pytest.param(
        {"hardware_platform": "unsupported", "hardware_confirmed": True},
        "Unsupported EEG hardware platform", id="unknown",
    ),
]


def _source(folder: Path) -> Path:
    folder.mkdir(exist_ok=True)
    header = folder / "P01.vhdr"
    header.write_text(
        "Brain Vision Data Exchange Header File Version 1.0\n"
        "[Common Infos]\nCodepage=UTF-8\nDataFile=P01.eeg\nMarkerFile=P01.vmrk\n"
        "DataFormat=BINARY\nDataOrientation=MULTIPLEXED\nNumberOfChannels=2\nSamplingInterval=1000\n"
        "[Binary Infos]\nBinaryFormat=INT_16\n[Channel Infos]\nCh1=Fz,,1,uV\nCh2=Cz,,1,uV\n"
    )
    header.with_suffix(".vmrk").write_text(
        "Brain Vision Data Exchange Marker File, Version 1.0\n"
        "[Common Infos]\nDataFile=P01.eeg\n[Marker Infos]\nMk1=Stimulus,S 1,1,1,0\n"
    )
    header.with_suffix(".eeg").write_bytes(bytes(40))
    return header


def test_discovery_registers_only_headers_and_reopens_project(tmp_path):
    raw = tmp_path / "raw"
    source = _source(raw)
    (raw / "._P02.vhdr").write_text("mac metadata")
    (raw / "nested").mkdir()
    (raw / "fake.vhdr").mkdir()
    root = tmp_path / "project"
    root.mkdir()
    project = Project.load(root)
    project.input_folder = raw
    project.preprocessing = confirm_hardware_selection(project.preprocessing, "brain_products", confirmed_change=True)
    project.save()
    files = discover_raw_files(project)
    assert [item.path for item in files] == [source.resolve()]
    register_participants(project, files)
    reopened = Project.load(root)
    assert reopened.preprocessing["hardware_platform"] == "brain_products"
    assert reopened.preprocessing["hardware_confirmed"] is True
    assert [item.path for item in discover_raw_files(reopened)] == [source.resolve()]
    manifest = json.loads((root / "project.json").read_text())
    assert len(manifest["participants"]) == 1


@pytest.mark.parametrize("suffix", [".eeg", ".vmrk"])
def test_companion_change_invalidates_all_processing_identities(tmp_path, suffix):
    source = _source(tmp_path)
    settings = confirm_hardware_selection({}, "brain_products", confirmed_change=True)

    def signatures():
        return (
            raw_file_metadata(source), _preflight_file_identity(source),
            _preproc_cache_key(_preproc_cache_payload(source, settings, mne_version="1.9.0")),
        )

    before = signatures()
    old_header = source.stat()
    companion = source.with_suffix(suffix)
    with companion.open("ab") as stream:
        stream.write(b"\n")
    after = signatures()
    assert source.stat().st_mtime_ns == old_header.st_mtime_ns
    assert all(first != second for first, second in zip(before, after, strict=True))


def test_legacy_signature_shape_and_entrypoint_filters_remain_explicit(tmp_path):
    source = tmp_path / "P01.bdf"
    source.write_bytes(b"legacy")
    assert companion_identity(source) == {}
    assert set(raw_file_metadata(source)) == {"raw_file", "raw_size", "raw_mtime_ns"}
    assert is_bdf_file(source)
    for name in ("P01.VHDR", "P01.BVRH", "P01.BDF"):
        assert is_eeg_recording_file(name)
    for name in ("._P01.vhdr", "P01.eeg", "P01.vmrk", "P01.bvrd", "P01.bvrm", "P01.bvri"):
        assert not is_eeg_recording_file(name)
    assert not is_bdf_file("P01.vhdr")


@pytest.mark.parametrize("settings,message", _INVALID_HARDWARE)
def test_lazy_bdf_loader_rejects_invalid_hardware_before_opening(tmp_path, monkeypatch, settings, message):
    from Main_App.io import load_utils

    inspect_header = Mock(side_effect=AssertionError("BDF must not be inspected"))
    reader = Mock(side_effect=AssertionError("BDF must not be opened"))
    monkeypatch.setattr(load_utils, "inspect_bdf_header", inspect_header)
    monkeypatch.setattr(load_utils, "_read_biosemi64_header_geometry", reader)
    with pytest.raises(ValueError, match=message):
        with load_utils.open_preflight_eeg_file(
            SimpleNamespace(log=lambda _: None), str(tmp_path / "P01.bdf"),
            acquisition_settings=settings,
        ):
            pytest.fail("An invalid hardware policy must not yield a recording")
    inspect_header.assert_not_called()
    reader.assert_not_called()


@pytest.mark.parametrize("settings,message", _INVALID_HARDWARE)
def test_preloading_bdf_loader_rejects_invalid_hardware_before_allocating(tmp_path, monkeypatch, settings, message):
    from Main_App.io import load_utils

    inspect_header = Mock(side_effect=AssertionError("BDF must not be inspected"))
    reader = Mock(side_effect=AssertionError("BDF must not be opened"))
    show_error = Mock()
    monkeypatch.setattr(load_utils, "inspect_bdf_header", inspect_header)
    monkeypatch.setattr(load_utils, "_read_biosemi64_header_geometry", reader)
    monkeypatch.setattr(load_utils.user_messages, "show_error", show_error)
    destination = tmp_path / "owned.dat"
    result = load_utils.load_eeg_file(
        SimpleNamespace(log=lambda _: None), str(tmp_path / "P01.bdf"),
        acquisition_settings=settings, preload_path=destination,
    )
    assert result is None
    assert message in show_error.call_args.args[1]
    assert not destination.exists()
    inspect_header.assert_not_called()
    reader.assert_not_called()


@pytest.mark.parametrize("settings,message", _INVALID_HARDWARE)
def test_worker_rejects_invalid_hardware_before_cache_lookup(tmp_path, monkeypatch, settings, message):
    from Main_App.io import load_utils
    from Main_App.workers import process_runner

    cache = Mock(side_effect=AssertionError("Cache must not be consulted"))
    loader = Mock(side_effect=AssertionError("Recording must not be opened"))
    monkeypatch.setattr(process_runner, "_load_preprocessed_cache", cache)
    monkeypatch.setattr(load_utils, "load_eeg_file", loader)
    result = process_runner._run_full_pipeline_for_file(
        tmp_path / "P01.bdf", settings, {"Faces": 21}, tmp_path, tmp_path,
    )
    assert result["status"] == "error"
    assert result["stage"] == "preflight"
    assert message in result["error"]
    cache.assert_not_called()
    loader.assert_not_called()


@pytest.mark.parametrize("invalid_settings", [
    {"channel_types": {"not_recorded": "misc"}},
    {"electrode_montage": "not_a_montage"},
], ids=["channel-role", "montage"])
def test_brainvision_validation_failure_closes_and_removes_owned_memmap(tmp_path, monkeypatch, invalid_settings):
    from Main_App.io import brain_products, hardware_loader

    source = _source(tmp_path)
    originals = {path: path.read_bytes() for path in (source, source.with_suffix(".eeg"), source.with_suffix(".vmrk"))}
    settings = confirm_hardware_selection({}, "brain_products", confirmed_change=True)
    settings.update(invalid_settings)
    real_reader = brain_products.read_brain_products_raw
    retained = {}

    def capture_real_raw(*args, **kwargs):
        raw = real_reader(*args, **kwargs)
        retained.update(raw=raw, mmap=raw._data._mmap)
        return raw

    monkeypatch.setattr(brain_products, "read_brain_products_raw", capture_real_raw)
    destination = tmp_path / "owned.dat"
    with pytest.raises(ValueError) as error:
        hardware_loader.open_brain_products_raw(
            SimpleNamespace(log=lambda _: None), source,
            settings=settings, preload=str(destination),
        )

    # Keep both Raw and traceback alive: garbage collection must not conceal a
    # leaked mapping, which would prevent file deletion on Windows.
    assert error.value is not None
    assert retained["mmap"].closed
    assert retained["raw"]._data is None
    assert not destination.exists()
    assert {path: path.read_bytes() for path in originals} == originals

from __future__ import annotations

import logging
import warnings
from types import SimpleNamespace

import mne
import numpy as np

import Main_App.Shared.load_utils as shared_loader
import Main_App.io.load_utils as loader
from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS


def _raw():
    names = [*BIOSEMI64_CHANNELS, "EXG1", "EXG2", "EXG3", "Status"]
    types = ["stim" if name == "Status" else "eeg" for name in names]
    return mne.io.RawArray(
        np.zeros((len(names), 8), dtype=float),
        mne.create_info(names, 512.0, types),
        verbose=False,
    )


def _app(logs=None):
    return SimpleNamespace(
        currentProject=SimpleNamespace(
            preprocessing={"ref_chan1": "EXG1", "ref_chan2": "EXG2"}
        ),
        settings=SimpleNamespace(get=lambda *args, **kwargs: "Status"),
        log=(logs.append if logs is not None else (lambda *args, **kwargs: None)),
    )


def test_load_eeg_file_suppresses_expected_channel_and_montage_warnings(monkeypatch, tmp_path):
    header_raw = _raw()
    loaded_raw = _raw()
    calls = []

    def _read(*args, **kwargs):
        calls.append(dict(kwargs))
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_loader, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_loader.mne.io, "read_raw_bdf", _read)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        raw = loader.load_eeg_file(_app(), str(tmp_path / "sample.bdf"))

    assert raw is loaded_raw
    assert caught == []


def test_load_eeg_file_treats_montage_error_as_technical_failure(monkeypatch, tmp_path):
    header_raw = _raw()
    loaded_raw = _raw()
    calls = []
    logs = []
    errors = []

    def _read(*args, **kwargs):
        calls.append(dict(kwargs))
        return header_raw if len(calls) == 1 else loaded_raw

    def _fail_montage(*args, **kwargs):
        raise RuntimeError("coordinate assignment failed")

    monkeypatch.setattr(shared_loader, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_loader.mne.io, "read_raw_bdf", _read)
    monkeypatch.setattr(loaded_raw, "set_montage", _fail_montage)
    monkeypatch.setattr(
        shared_loader.user_messages,
        "show_error",
        lambda title, message: errors.append((title, message)),
    )

    raw = loader.load_eeg_file(_app(logs), str(tmp_path / "sample.bdf"))

    assert raw is None
    assert any("coordinate assignment failed" in message for message in logs)
    assert errors and "coordinate assignment failed" in errors[0][1]


def test_load_eeg_file_logs_header_mismatch_with_exact_file(monkeypatch, tmp_path, caplog):
    header_raw = _raw()
    loaded_raw = _raw()
    bdf_path = tmp_path / "problem_sample.bdf"
    calls = []

    def _fake_read_raw_bdf(*args, **kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 2:
            warnings.warn(
                "Number of records from the header does not match the file size "
                "(perhaps the recording was not stopped before exiting). "
                "Inferring from the file size.",
                RuntimeWarning,
                stacklevel=2,
            )
        return header_raw if len(calls) == 1 else loaded_raw

    monkeypatch.setattr(shared_loader, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_loader.mne.io, "read_raw_bdf", _fake_read_raw_bdf)
    app = _app()
    app.log = lambda message: None

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with caplog.at_level(logging.WARNING, logger=shared_loader.__name__):
            raw = loader.load_eeg_file(app, str(bdf_path))

    assert raw is loaded_raw
    assert caught == []
    assert "problem_sample.bdf" in caplog.text
    assert str(bdf_path) in caplog.text
    assert "Number of records from the header does not match the file size" in caplog.text


def test_load_eeg_file_rejects_set_files(monkeypatch, tmp_path):
    warnings_seen = []
    monkeypatch.setattr(
        shared_loader.user_messages,
        "show_warning",
        lambda title, message: warnings_seen.append((title, message)),
    )

    app = SimpleNamespace(
        currentProject=SimpleNamespace(preprocessing={}),
        settings=SimpleNamespace(get=lambda *args, **kwargs: "Status"),
        log=lambda *args, **kwargs: None,
    )

    raw = loader.load_eeg_file(app, str(tmp_path / "sample.set"))

    assert raw is None
    assert warnings_seen == [
        ("Unsupported File", "Format '.set' not supported. Only '.bdf' is supported.")
    ]


def test_loader_compatibility_alias_uses_biosemi64():
    assert tuple(loader._cached_1010().ch_names) == BIOSEMI64_CHANNELS


def test_shared_loader_is_compatibility_wrapper():
    assert shared_loader.load_eeg_file is loader.load_eeg_file

from __future__ import annotations

import logging
import warnings
from types import SimpleNamespace

import Main_App.PySide6_App.Backend.loader as backend_loader
import Main_App.Shared.load_utils as shared_loader
import Main_App.io.load_utils as loader


class _FakeRaw:
    def __init__(self) -> None:
        self.ch_names = ["Cz", "EXG1", "EXG2", "EXG3", "Status"]
        self.info = {"sfreq": 512.0}

    def load_data(self) -> None:
        return None

    def set_channel_types(self, mapping):
        if mapping:
            warnings.warn(
                "The unit for channel(s) EXG3 has changed from V to NA.",
                RuntimeWarning,
                stacklevel=2,
            )

    def set_montage(self, montage, on_missing="warn", match_case=False, verbose=False):
        assert on_missing == "warn"


def test_load_eeg_file_suppresses_expected_channel_and_montage_warnings(monkeypatch, tmp_path):
    fake_raw = _FakeRaw()

    monkeypatch.setattr(shared_loader, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_loader, "_cached_1010", lambda: object())
    monkeypatch.setattr(
        shared_loader.mne.io,
        "read_raw_bdf",
        lambda *args, **kwargs: fake_raw,
    )

    app = SimpleNamespace(
        currentProject=SimpleNamespace(preprocessing={"ref_chan1": "EXG1", "ref_chan2": "EXG2"}),
        settings=SimpleNamespace(get=lambda *args, **kwargs: "Status"),
        log=lambda *args, **kwargs: None,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        raw = loader.load_eeg_file(app, str(tmp_path / "sample.bdf"))

    assert raw is fake_raw
    assert caught == []


def test_load_eeg_file_logs_header_mismatch_with_exact_file(monkeypatch, tmp_path, caplog):
    fake_raw = _FakeRaw()
    bdf_path = tmp_path / "problem_sample.bdf"

    def _fake_read_raw_bdf(*args, **kwargs):
        warnings.warn(
            "Number of records from the header does not match the file size "
            "(perhaps the recording was not stopped before exiting). "
            "Inferring from the file size.",
            RuntimeWarning,
            stacklevel=2,
        )
        return fake_raw

    monkeypatch.setattr(shared_loader, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(shared_loader, "_cached_1010", lambda: object())
    monkeypatch.setattr(shared_loader.mne.io, "read_raw_bdf", _fake_read_raw_bdf)

    app = SimpleNamespace(
        currentProject=SimpleNamespace(preprocessing={"ref_chan1": "EXG1", "ref_chan2": "EXG2"}),
        settings=SimpleNamespace(get=lambda *args, **kwargs: "Status"),
        log=lambda msg: None,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with caplog.at_level(logging.WARNING, logger=shared_loader.__name__):
            raw = loader.load_eeg_file(app, str(bdf_path))

    assert raw is fake_raw
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


def test_loader_uses_standard_1005_for_1010_coverage(monkeypatch):
    montage_calls = []

    def _fake_make_standard_montage(name):
        montage_calls.append(name)
        return object()

    shared_loader._cached_1010.cache_clear()
    monkeypatch.setattr(shared_loader.mne.channels, "make_standard_montage", _fake_make_standard_montage)

    try:
        assert loader._cached_1010() is not None
    finally:
        shared_loader._cached_1010.cache_clear()

    assert montage_calls == ["standard_1005"]


def test_backend_loader_is_compatibility_wrapper():
    assert backend_loader.load_eeg_file is loader.load_eeg_file


def test_shared_loader_is_compatibility_wrapper():
    assert shared_loader.load_eeg_file is loader.load_eeg_file

from __future__ import annotations

from types import SimpleNamespace

import Main_App.Shared.load_utils as load_utils


class _FakeRaw:
    def __init__(self) -> None:
        self.ch_names = ["Cz", "EXG1", "EXG2", "EXG3", "Status"]
        self.info = {"sfreq": 512.0}
        self.channel_type_calls = []
        self.montage_kwargs = None

    def load_data(self) -> None:
        return None

    def set_channel_types(self, mapping):
        self.channel_type_calls.append(mapping)

    def set_montage(self, montage, **kwargs):
        self.montage_kwargs = kwargs


def _app(logs: list[str]):
    return SimpleNamespace(
        currentProject=SimpleNamespace(
            preprocessing={
                "ref_chan1": "EXG1",
                "ref_chan2": "EXG2",
                "stim_channel": "Status",
            }
        ),
        settings=SimpleNamespace(get=lambda section, key, default=None: default),
        log=logs.append,
    )


def test_shared_load_eeg_file_preserves_bdf_channel_and_montage_contract(monkeypatch, tmp_path):
    fake_raw = _FakeRaw()
    captured = {}

    def _fake_read_raw_bdf(filepath, **kwargs):
        captured["filepath"] = filepath
        captured.update(kwargs)
        return fake_raw

    monkeypatch.setattr(load_utils, "_memmap_dir_for_pid", lambda: tmp_path)
    monkeypatch.setattr(load_utils, "_cached_1010", lambda: object())
    monkeypatch.setattr(load_utils.mne.io, "read_raw_bdf", _fake_read_raw_bdf)

    logs: list[str] = []
    path = tmp_path / "sample.bdf"

    raw = load_utils.load_eeg_file(_app(logs), str(path))

    assert raw is fake_raw
    assert captured["filepath"] == str(path)
    assert captured["preload"] == str(tmp_path / "sample_raw.dat")
    assert captured["stim_channel"] == "Status"
    assert fake_raw.channel_type_calls == [
        {"EXG3": "misc"},
        {"EXG1": "eeg", "EXG2": "eeg"},
        {"Status": "stim"},
    ]
    assert fake_raw.montage_kwargs == {
        "on_missing": "warn",
        "match_case": False,
        "verbose": False,
    }
    assert "BDF loaded successfully." in logs


def test_shared_load_eeg_file_unsupported_extension_warns_and_returns_none(monkeypatch, tmp_path):
    warnings = []
    monkeypatch.setattr(
        load_utils.user_messages,
        "show_warning",
        lambda title, message: warnings.append((title, message)),
    )

    logs: list[str] = []

    raw = load_utils.load_eeg_file(_app(logs), str(tmp_path / "sample.set"))

    assert raw is None
    assert warnings == [("Unsupported File", "Format '.set' not supported. Only '.bdf' is supported.")]


def test_shared_loader_uses_standard_1005_for_1010_coverage(monkeypatch):
    montage_calls = []

    def _fake_make_standard_montage(name):
        montage_calls.append(name)
        return object()

    load_utils._cached_1010.cache_clear()
    monkeypatch.setattr(load_utils.mne.channels, "make_standard_montage", _fake_make_standard_montage)

    try:
        assert load_utils._cached_1010() is not None
    finally:
        load_utils._cached_1010.cache_clear()

    assert montage_calls == ["standard_1005"]

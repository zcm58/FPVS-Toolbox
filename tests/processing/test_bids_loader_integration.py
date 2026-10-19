"""Focused ownership checks after a normalized recording reaches the loader."""

from types import SimpleNamespace

import numpy as np

from Main_App.io import bids_loader, load_utils
from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
from tests.processing.test_shared_load_utils import _write_sampling_bdf


def test_failed_biosemi_geometry_closes_and_removes_owned_preload(tmp_path, monkeypatch):
    source = tmp_path / "native.bdf"
    names = (*BIOSEMI64_CHANNELS, "EXG1", "EXG2", "Status")
    _write_sampling_bdf(source, labels=names, samples=(16,) * len(names))
    preload = tmp_path / "owned.dat"
    captured = []
    read = bids_loader.read_project_bids_raw

    def capture(*args, **kwargs):
        raw = read(*args, **kwargs)
        assert isinstance(raw._data, np.memmap)
        captured.append((raw, raw._data._mmap))
        return raw

    def fail_geometry(*args, **kwargs):
        raise ValueError("Invalid montage after import")

    monkeypatch.setattr(bids_loader, "read_project_bids_raw", capture)
    monkeypatch.setattr(load_utils, "_apply_preflight_channel_and_montage_contract", fail_geometry)
    monkeypatch.setattr(load_utils.user_messages, "show_error", lambda *_args, **_kwargs: None)
    host = SimpleNamespace(log=lambda *_args, **_kwargs: None)
    result = load_utils.load_eeg_file(
        host, str(source), preload_path=preload,
        acquisition_settings={"project_root": str(tmp_path)},
    )
    assert result is None
    assert len(captured) == 1
    raw, mapping = captured[0]
    assert raw._data is None
    assert mapping.closed
    assert not preload.exists()
    assert source.is_file()

from __future__ import annotations

import sys
import types
import importlib.util
from pathlib import Path

import numpy as np

# Minimal Qt stubs for importing Main_App package in test environment.
if "PySide6" not in sys.modules and importlib.util.find_spec("PySide6") is None:
    qtcore = types.ModuleType("PySide6.QtCore")

    class _QCoreApplication:
        @staticmethod
        def instance():
            return None

    class _QStandardPaths:
        AppDataLocation = 0

        @staticmethod
        def writableLocation(_loc):
            return "/tmp"

    qtcore.QCoreApplication = _QCoreApplication
    qtcore.QStandardPaths = _QStandardPaths
    pyside = types.ModuleType("PySide6")
    sys.modules["PySide6"] = pyside
    sys.modules["PySide6.QtCore"] = qtcore

if "mne" not in sys.modules and importlib.util.find_spec("mne") is None:
    sys.modules["mne"] = types.ModuleType("mne")

from Main_App.Performance import process_runner


class _FakeRaw:
    def __init__(self, sfreq: float, n_times: int, n_ch: int = 2) -> None:
        self.info = {"sfreq": sfreq}
        self.ch_names = [f"EEG{i}" for i in range(n_ch)]
        self.n_times = n_times
        self._data = np.arange(n_ch * n_times, dtype=float).reshape(n_ch, n_times)

    def get_data(self, start: int, stop: int):
        return self._data[:, start:stop]


class _FakeEpochsArray:
    def __init__(self, data, info, events, event_id, tmin, baseline, verbose):
        self._data = np.asarray(data)
        self.info = info
        self.events = np.asarray(events)
        self.event_id = event_id
        self.tmin = tmin
        self.metadata = None

    def __len__(self):
        return len(self.events)


class _FakeMne(types.SimpleNamespace):
    @staticmethod
    def set_log_level(_level):
        return None

    @staticmethod
    def find_events(raw_proc, stim_channel, shortest_event):
        return raw_proc._events

    @staticmethod
    def events_from_annotations(_raw_proc):
        return np.empty((0, 3), dtype=int), {}

    EpochsArray = _FakeEpochsArray


class _Capture:
    ctx = None


def _install_worker_stubs(monkeypatch, raw, capture):
    fake_loader = types.ModuleType("Main_App.io.load_utils")
    fake_loader.load_eeg_file = lambda _app, _path, ref_pair: raw
    monkeypatch.setitem(sys.modules, "Main_App.io.load_utils", fake_loader)

    fake_adapter = types.ModuleType("Main_App.PySide6_App.adapters.post_export_adapter")

    class LegacyCtx:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def run_post_export(ctx, _labels):
        capture.ctx = ctx
        return 1

    fake_adapter.LegacyCtx = LegacyCtx
    fake_adapter.run_post_export = run_post_export
    monkeypatch.setitem(sys.modules, "Main_App.PySide6_App.adapters.post_export_adapter", fake_adapter)

    monkeypatch.setattr(process_runner, "backend_preprocess", types.SimpleNamespace(
        begin_preproc_audit=lambda *_a, **_k: {"ok": True},
        perform_preprocessing=lambda raw_input, params, log_func, filename_for_log: (raw_input, 0),
        finalize_preproc_audit=lambda *args, **kwargs: ({"n_rejected": 0}, []),
    ))
    monkeypatch.setitem(sys.modules, "mne", _FakeMne())


def test_mp_worker_uses_onbin_crop_and_stamps_metadata(tmp_path, monkeypatch):
    raw = _FakeRaw(sfreq=256.0, n_times=5000)
    raw._events = np.array([
        [100, 0, 10],
        [200, 0, 55],
        [840, 0, 55],
        [1480, 0, 55],
        [2000, 0, 10],
        [2200, 0, 55],
        [2840, 0, 55],
        [3480, 0, 55],
    ], dtype=int)
    capture = _Capture()
    _install_worker_stubs(monkeypatch, raw, capture)

    result = process_runner._run_full_pipeline_for_file(
        file_path=Path("subject01.bdf"),
        settings={"epoch_start": -1.0, "epoch_end": 1.0, "stim_channel": "Status"},
        event_map={"odd": 10},
        save_folder=tmp_path,
        project_root=tmp_path,
    )

    assert result["status"] == "ok"
    epochs = capture.ctx.preprocessed_data["odd"][0]
    md = epochs.metadata

    assert md["crop_mode"].tolist() == ["55_onbin", "55_onbin"]
    assert int(md["N_step"].iloc[0]) == 640
    assert int(epochs._data.shape[2]) % 640 == 0
    assert md["N_mod_step"].tolist() == [0, 0]


def test_mp_worker_fallback_metadata_when_55_missing(tmp_path, monkeypatch):
    raw = _FakeRaw(sfreq=256.0, n_times=3000)
    raw._events = np.array([
        [1000, 0, 10],
    ], dtype=int)
    capture = _Capture()
    _install_worker_stubs(monkeypatch, raw, capture)

    result = process_runner._run_full_pipeline_for_file(
        file_path=Path("subject02.bdf"),
        settings={"epoch_start": -1.0, "epoch_end": 1.0, "stim_channel": "Status"},
        event_map={"odd": 10},
        save_folder=tmp_path,
        project_root=tmp_path,
    )

    assert result["status"] == "ok"
    md = capture.ctx.preprocessed_data["odd"][0].metadata
    assert md["crop_mode"].tolist() == ["fixed_epoch_fallback"]
    assert md["fallback_reason"].iloc[0]

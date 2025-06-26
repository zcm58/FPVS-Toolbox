import importlib.util
import os
import sys
import types
import pytest


if importlib.util.find_spec("numpy") is None:
    pytest.skip("numpy not available", allow_module_level=True)


def _import_runner(monkeypatch):
    dummy = types.SimpleNamespace()
    dummy.__version__ = "0"
    dummy.viz = types.SimpleNamespace(
        get_3d_backend=lambda: "pyvistaqt",
        set_3d_backend=lambda *a, **k: None,
    )
    dummy.combine_evoked = lambda *a, **k: None
    monkeypatch.setitem(sys.modules, "mne", dummy)
    monkeypatch.setitem(sys.modules, "mne.viz", dummy.viz)

    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "src",
        "Tools",
        "SourceLocalization",
        "runner.py",
    )
    spec = importlib.util.spec_from_file_location("runner", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DummyEvoked:
    def __init__(self):
        self.crop_calls = []

    def copy(self):
        new = DummyEvoked()
        new.crop_calls = self.crop_calls
        return new

    def filter(self, *a, **k):
        return self

    def crop(self, tmin=None, tmax=None):
        self.crop_calls.append((tmin, tmax))
        return self


class DummyEpochs:
    def copy(self):
        return self

    def filter(self, *a, **k):
        return self

    def apply_baseline(self, *a, **k):
        pass

    def average(self):
        return DummyEvoked()


def test_defaults_from_settings(monkeypatch):
    runner = _import_runner(monkeypatch)

    captured = {}

    def _dummy_prepare_forward(evoked, settings, log_func):
        captured["evoked"] = evoked
        raise RuntimeError("stop")

    def _dummy_threshold(stc, thr):
        captured["thr"] = thr
        return stc

    monkeypatch.setattr(runner, "_estimate_epochs_covariance", lambda *a, **k: None)
    monkeypatch.setattr(runner, "_prepare_forward", _dummy_prepare_forward)
    monkeypatch.setattr(runner, "_threshold_stc", _dummy_threshold)

    def fake_get(section, option, fallback=""):
        values = {
            "loreta_threshold": "0.5",
            "time_window_start_ms": "100",
            "time_window_end_ms": "200",
            "loreta_low_freq": "0.1",
            "loreta_high_freq": "40.0",
            "oddball_harmonics": "1,2,3",
            "loreta_snr": "3.0",
        }
        return values.get(option, fallback)

    monkeypatch.setattr(runner, "SettingsManager", lambda *a, **k: types.SimpleNamespace(get=fake_get))

    with pytest.raises(RuntimeError):
        runner.run_source_localization(None, "out", epochs=DummyEpochs())

    assert captured["thr"] == 0.5
    assert captured["evoked"].crop_calls == [(0.1, 0.2)]

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
        self.times = [0.0, 0.2]
        self.crop_calls = []

    def copy(self):
        new = DummyEvoked()
        new.times = self.times
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


def test_crop_respects_evoked_tmax(monkeypatch):
    runner = _import_runner(monkeypatch)
    monkeypatch.setattr(runner, "_estimate_epochs_covariance", lambda *a, **k: None)

    def fake_get(section, option, fallback=""):
        if option == "oddball_freq":
            return "1.0"
        return "0"

    monkeypatch.setattr(runner, "SettingsManager", lambda *a, **k: types.SimpleNamespace(get=fake_get))
    monkeypatch.setattr(runner.source_localization, "extract_cycles", lambda epochs, freq: [epochs])
    monkeypatch.setattr(runner.source_localization, "average_cycles", lambda cycles: DummyEvoked())
    monkeypatch.setattr(runner.source_localization, "reconstruct_harmonics", lambda ev, harm: ev)
    monkeypatch.setattr(runner, "combine_evoked", lambda evs, weights=None: evs[0])

    captured = {}

    def _dummy_prepare_forward(evoked, settings, log_func):
        captured["evoked"] = evoked
        raise RuntimeError("stop")

    monkeypatch.setattr(runner, "_prepare_forward", _dummy_prepare_forward)

    with pytest.raises(RuntimeError):
        runner.run_source_localization(
            None,
            "out",
            epochs=DummyEpochs(),
            oddball=True,
        )

    assert captured["evoked"].crop_calls == [(0.0, 0.2)]

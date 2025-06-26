import importlib.util
import os
import sys
import types
import pickle
import pytest

if importlib.util.find_spec("numpy") is None:
    pytest.skip("numpy not available", allow_module_level=True)

import numpy as np


class DummyStc:
    def __init__(self, data):
        self.data = np.array(data, dtype=float)

    def copy(self):
        return DummyStc(self.data.copy())

    def save(self, fname):
        for hemi in ("lh", "rh"):
            with open(f"{fname}-{hemi}.stc", "wb") as f:
                pickle.dump(self, f)


def _import_runner(monkeypatch):
    dummy = types.SimpleNamespace()
    dummy.__version__ = "0"
    dummy.viz = types.SimpleNamespace(
        get_3d_backend=lambda: "pyvistaqt",
        set_3d_backend=lambda *a, **k: None,
    )
    dummy.combine_evoked = lambda *a, **k: None

    def read_source_estimate(path):
        with open(path, "rb") as f:
            return pickle.load(f)

    dummy.read_source_estimate = read_source_estimate
    dummy.SourceEstimate = DummyStc

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
    calls = []

    def _dummy_morph(stc, subject, subjects_dir, smooth=5.0):
        calls.append((subject, subjects_dir, smooth))
        return stc

    monkeypatch.setattr(module.source_localization, "morph_to_fsaverage", _dummy_morph)
    module._morph_calls = calls
    return module


def test_average_stc_directory_two_files(tmp_path, monkeypatch):
    runner = _import_runner(monkeypatch)

    stc1 = DummyStc([[1]])
    stc2 = DummyStc([[2]])
    stc1.save(os.path.join(tmp_path, "sub1"))
    stc2.save(os.path.join(tmp_path, "sub2"))

    out = runner.average_stc_directory(
        str(tmp_path), output_basename="avg", log_func=lambda x: None
    )

    assert out == os.path.join(str(tmp_path), "avg")
    avg_files = sorted(p.name for p in tmp_path.glob("avg-*.stc"))
    assert avg_files == ["avg-lh.stc", "avg-rh.stc"]
    subjects = {call[0] for call in runner._morph_calls}
    assert subjects == {"sub1", "sub2"}
    assert all(call[2] == 5.0 for call in runner._morph_calls)


def test_average_stc_directory_infer_name(tmp_path, monkeypatch):
    runner = _import_runner(monkeypatch)

    stc = DummyStc([[1]])
    stc.save(os.path.join(tmp_path, "SC_P1_Green_Fruit_vs_Green_Veg"))
    stc.save(os.path.join(tmp_path, "SC_P2_Green_Fruit_vs_Green_Veg"))

    out = runner.average_stc_directory(str(tmp_path), log_func=lambda x: None)

    expected = os.path.join(
        str(tmp_path), "Average Green Fruit vs Green Veg Response"
    )
    assert out == expected
    avg_files = sorted(p.name for p in tmp_path.glob("Average*"))
    assert avg_files == [
        "Average Green Fruit vs Green Veg Response-lh.stc",
        "Average Green Fruit vs Green Veg Response-rh.stc",
    ]

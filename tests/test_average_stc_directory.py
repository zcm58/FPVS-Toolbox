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

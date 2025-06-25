import importlib.util
import os
import sys
import pytest


def _import_eloreta_runner():
    # skip tests if required deps are missing
    for mod in ('numpy', 'mne'):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not available", allow_module_level=True)
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'Tools', 'SourceLocalization', 'eloreta_runner.py')
    spec = importlib.util.spec_from_file_location('eloreta_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_threshold_absolute():
    module = _import_eloreta_runner()
    _threshold_stc = module._threshold_stc

    class DummyStc:
        def __init__(self, data):
            self.data = module.np.array(data, dtype=float)
        def copy(self):
            return DummyStc(self.data.copy())

    stc = DummyStc([[1, 2, -3], [0.5, -2.5, 0]])
    res = _threshold_stc(stc, 2.0)
    expected = module.np.array([[0, 2, -3], [0, -2.5, 0]])
    assert module.np.array_equal(res.data, expected)


def test_threshold_fraction():
    module = _import_eloreta_runner()
    _threshold_stc = module._threshold_stc

    class DummyStc:
        def __init__(self, data):
            self.data = module.np.array(data, dtype=float)
        def copy(self):
            return DummyStc(self.data.copy())

    stc = DummyStc([[1, -4, 2], [0, -2, 1]])
    res = _threshold_stc(stc, 0.5)
    expected = module.np.array([[0, -4, 2], [0, -2, 0]])
    assert module.np.array_equal(res.data, expected)

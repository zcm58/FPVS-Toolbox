import importlib.util
import os
import pytest


def _import_eloreta_runner():
    for mod in ('numpy', 'mne'):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not available", allow_module_level=True)
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'Tools', 'SourceLocalization', 'eloreta_runner.py')
    spec = importlib.util.spec_from_file_location('eloreta_runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_average_stc_files():
    module = _import_eloreta_runner()
    avg_func = getattr(module, 'average_stc_files', None)
    if avg_func is None:
        pytest.skip('average_stc_files not implemented')

    class DummyStc:
        def __init__(self, data):
            self.data = module.np.array(data, dtype=float)
        def copy(self):
            return DummyStc(self.data.copy())

    stc1 = DummyStc([[1, 2], [3, 4]])
    stc2 = DummyStc([[5, 6], [7, 8]])
    result = avg_func([stc1, stc2])
    expected = module.np.array([[3, 4], [5, 6]])
    assert module.np.allclose(result.data, expected)


def test_average_stc_files_normalized():
    module = _import_eloreta_runner()
    avg_func = getattr(module, 'average_stc_files', None)
    if avg_func is None:
        pytest.skip('average_stc_files not implemented')

    class DummyStc:
        def __init__(self, data):
            self.data = module.np.array(data, dtype=float)
        def copy(self):
            return DummyStc(self.data.copy())

    stc1 = DummyStc([[1, 2], [3, 4]])
    stc2 = DummyStc([[5, 6], [7, 8]])
    result = avg_func([stc1, stc2], normalize=True)
    expected = module.np.array([[0.4375, 0.625], [0.8125, 1.0]])
    assert module.np.allclose(result.data, expected)

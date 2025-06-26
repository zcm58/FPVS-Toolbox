import importlib.util
import os
import pytest


def _import_runner():
    for mod in ("numpy", "mne"):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not available", allow_module_level=True)
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'Tools', 'SourceLocalization', 'runner.py')
    spec = importlib.util.spec_from_file_location('runner', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_estimate_epochs_covariance_two_epochs():
    runner = _import_runner()
    func = runner._estimate_epochs_covariance
    data = runner.np.random.RandomState(0).randn(2, 3, 4)
    info = runner.mne.create_info(3, 1000.0, ch_types='eeg')
    epochs = runner.mne.EpochsArray(data, info, verbose=False)
    cov = func(epochs, log_func=lambda x: None)
    assert isinstance(cov, runner.mne.Covariance)

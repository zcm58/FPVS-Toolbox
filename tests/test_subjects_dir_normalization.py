import importlib
import importlib.util
import os
import types
from unittest import mock
import pytest


def _import_data_utils():
    path = os.path.join(os.path.dirname(__file__), '..', 'src', 'Tools', 'SourceLocalization', 'data_utils.py')
    spec = importlib.util.spec_from_file_location('data_utils', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_deps():
    for mod in ('numpy', 'mne'):
        if importlib.util.find_spec(mod) is None:
            pytest.skip(f"{mod} not available", allow_module_level=True)


def test_prepare_forward_trailing_slash(tmp_path):
    _check_deps()
    module = _import_data_utils()
    SettingsManager = importlib.import_module('Main_App.settings_manager').SettingsManager
    settings = SettingsManager()
    fs_dir = tmp_path / 'fsaverage'
    fs_dir.mkdir()
    settings.set('loreta', 'mri_path', str(fs_dir) + os.sep)

    dummy_evoked = types.SimpleNamespace(info={}, data=[], times=[])

    with mock.patch.object(module.mne, 'setup_source_space', return_value='src'), \
         mock.patch.object(module.mne, 'make_bem_model', return_value='model'), \
         mock.patch.object(module.mne, 'make_bem_solution', return_value='bem'), \
         mock.patch.object(module.mne, 'make_forward_solution', return_value='fwd'), \
         mock.patch.object(module.mne, 'write_forward_solution'), \
         mock.patch('os.path.isfile', return_value=False):
        _, _, subjects_dir = module._prepare_forward(dummy_evoked, settings, lambda x: None)

    assert subjects_dir == str(tmp_path)

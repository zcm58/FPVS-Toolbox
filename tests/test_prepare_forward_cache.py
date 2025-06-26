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


def test_prepare_forward_uses_cache(tmp_path):
    _check_deps()
    module = _import_data_utils()
    SettingsManager = importlib.import_module('Main_App.settings_manager').SettingsManager
    settings = SettingsManager()
    fs_dir = tmp_path / 'fsaverage'
    fs_dir.mkdir()
    settings.set('loreta', 'mri_path', str(fs_dir))

    cache_dir = fs_dir / 'fpvs_cache'
    cache_dir.mkdir()
    fwd_path = cache_dir / 'forward-fsaverage.fif'
    fwd_path.write_text('dummy')

    dummy_evoked = types.SimpleNamespace(info={}, data=[], times=[])

    with mock.patch.object(module.mne, 'read_forward_solution', return_value='fwd') as read_fwd, \
         mock.patch.object(module.mne, 'setup_source_space') as setup_src, \
         mock.patch.object(module.mne, 'make_bem_model') as make_bem_model, \
         mock.patch.object(module.mne, 'make_bem_solution') as make_bem_solution, \
         mock.patch.object(module.mne, 'make_forward_solution') as make_forward_solution:
        fwd, _, _ = module._prepare_forward(dummy_evoked, settings, lambda x: None)

    assert fwd == 'fwd'
    read_fwd.assert_called_once_with(str(fwd_path))
    setup_src.assert_not_called()
    make_bem_model.assert_not_called()
    make_bem_solution.assert_not_called()
    make_forward_solution.assert_not_called()

"""FIF file buffering changes only the underlying I/O buffer, never its bytes."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import warnings

import mne
import numpy as np
import pytest

from Main_App.io import buffered_fif as buffering


@pytest.fixture
def raw():
    data = np.random.default_rng(17).normal(0, 1e-6, (5, 2048))
    data[0, ::37] = -0.0
    data[-1] = 0
    data[-1, 30:38] = 17
    result = mne.io.RawArray(data, mne.create_info(
        ['Fp1', 'Fz', 'Cz', 'Pz', 'Status'], 256, ['eeg'] * 4 + ['stim']),
        first_samp=256, verbose=False)
    result.set_meas_date('2020-01-01T00:00:00Z')
    result.set_annotations(mne.Annotations([.25, 2], [.5, .25], ['note', 'BAD_segment']))
    return result


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _characterized(raw):
    try:
        adapter = buffering._BufferedSave()
    except (ValueError, AttributeError, ImportError):
        pytest.skip('Exact optional writer adapter requires the characterized MNE runtime')
    assert adapter.valid_for(raw)
    return adapter


@pytest.mark.parametrize('fmt', ['single', 'double', 'int', 'short'])
@pytest.mark.parametrize('options', [
    {}, {'tmin': .1, 'tmax': 6.75, 'buffer_size_sec': .37, 'picks': ['Cz', 'Fp1']},
    {'buffer_size_sec': .5, 'drop_small_buffer': True},
])
def test_all_raw_file_bytes_and_input_state_exact(tmp_path, raw, fmt, options):
    _characterized(raw)
    before = raw._data.tobytes()
    filename = tmp_path / 'signal_raw.fif'
    kwargs = dict(overwrite=True, fmt=fmt, verbose=False, **options)
    with warnings.catch_warnings(record=True) as native_warnings:
        warnings.simplefilter('always')
        native_paths = raw.save(filename, **kwargs)
    native_hash = _sha(filename)
    with warnings.catch_warnings(record=True) as candidate_warnings:
        warnings.simplefilter('always')
        candidate_paths = buffering.save_raw_fif(raw, filename, **kwargs)
    assert list(candidate_paths) == list(native_paths)
    assert _sha(filename) == native_hash
    assert raw._data.tobytes() == before
    assert [(type(w.message), str(w.message)) for w in candidate_warnings] == [
        (type(w.message), str(w.message)) for w in native_warnings]


@pytest.mark.parametrize('split_naming', ['neuromag', 'bids'])
def test_split_containers_paths_and_metadata_exact(tmp_path, raw, split_naming):
    _characterized(raw)
    # The native split-size reserve is 1 MiB. Multiple moderate blocks exceed
    # a 2 MiB split without changing either native block or file geometry.
    data = np.tile(raw._data, (1, 32))
    large = mne.io.RawArray(data, raw.info.copy(), verbose=False)
    large.set_annotations(raw.annotations.copy())
    filename = tmp_path / 'signal_raw.fif'
    kwargs = dict(overwrite=True, fmt='double', buffer_size_sec=1,
                  split_size='2MB', split_naming=split_naming, verbose=False)
    native_paths = large.save(filename, **kwargs)
    assert len(native_paths) > 1
    hashes = {Path(path).name: _sha(Path(path)) for path in native_paths}
    candidate_paths = buffering.save_raw_fif(large, filename, **kwargs)
    assert list(candidate_paths) == list(native_paths)
    assert {Path(path).name: _sha(Path(path)) for path in candidate_paths} == hashes
    restored = mne.io.read_raw_fif(candidate_paths[0], preload=True, verbose=False)
    assert restored._data.tobytes() == data.tobytes()


@pytest.mark.parametrize('kwargs', [{'fmt': 'unknown'}, {'picks': ['missing']}, {'split_size': '1KB'}])
def test_native_validation_errors_preserved(tmp_path, raw, kwargs):
    _characterized(raw)
    filename = tmp_path / 'signal_raw.fif'
    errors = []
    for save in (raw.save, lambda path, **opts: buffering.save_raw_fif(raw, path, **opts)):
        with pytest.raises(Exception) as error:
            save(filename, overwrite=True, verbose=False, **kwargs)
        errors.append((type(error.value), str(error.value)))
    assert errors[0] == errors[1]


def test_unknown_runtime_and_overrides_use_public_save(monkeypatch):
    calls = []
    raw = SimpleNamespace(save=lambda *args, **kwargs: calls.append((args, kwargs)) or 'native')
    monkeypatch.setattr(buffering, '_supported_runtime', lambda: False)
    monkeypatch.setattr(buffering, '_ADAPTER', None)
    assert buffering.save_raw_fif(raw, 'target_raw.fif', fmt='double') == 'native'
    assert calls == [(('target_raw.fif',), {'fmt': 'double'})]


@pytest.mark.parametrize('mutation', ['code', 'defaults', 'forwarding', 'open', 'builtins', 'shadow', 'closure'])
def test_changed_writer_invalidates_cached_adapter(monkeypatch, raw, mutation):
    adapter = _characterized(raw)
    function = adapter.functions['start_file']
    if mutation == 'code':
        monkeypatch.setattr(function, '__code__', (lambda fname, id_=None: None).__code__)
    elif mutation == 'defaults':
        monkeypatch.setattr(function, '__defaults__', ('changed',))
    elif mutation == 'forwarding':
        monkeypatch.setitem(adapter.functions['save_body'].__globals__, '_write_raw', lambda *a, **k: None)
    elif mutation == 'open':
        monkeypatch.setattr(buffering.builtins, 'open', lambda *a, **k: None)
    elif mutation == 'builtins':
        monkeypatch.setitem(function.__globals__, '__builtins__', dict(buffering.builtins.__dict__))
    elif mutation == 'shadow':
        monkeypatch.setitem(function.__globals__, 'open', lambda *a, **k: None)
    else:
        cell = adapter.functions['start_end_wrapper'].__closure__[0]
        monkeypatch.setattr(cell, 'cell_contents', lambda *a, **k: iter(()))
    assert not adapter.valid_for(raw)


def test_save_bound_to_different_raw_uses_its_public_method(monkeypatch, tmp_path, raw):
    adapter = _characterized(raw)
    other = raw.copy()
    other._data *= 2
    raw.save = other.save
    assert not adapter.valid_for(raw)
    monkeypatch.setattr(buffering, '_ADAPTER', adapter)
    path = tmp_path / 'other_raw.fif'
    other.save(path, fmt='double', overwrite=True, verbose=False)
    native_hash = _sha(path)
    buffering.save_raw_fif(raw, path, fmt='double', overwrite=True, verbose=False)
    assert _sha(path) == native_hash


@pytest.mark.parametrize('name', ['save_wrapper', 'save_body', 'write_raw', 'start_end_body', 'start_file'])
def test_rebound_builtins_before_construction_uses_original_function_binding(monkeypatch, raw, name):
    adapter = _characterized(raw)
    function = adapter.functions[name]
    original_binding = function.__builtins__
    replacement = dict(original_binding)
    monkeypatch.setitem(function.__globals__, '__builtins__', replacement)
    assert function.__builtins__ is original_binding
    with pytest.raises(ValueError, match='implementation|forwarding'):
        buffering._BufferedSave()


def test_optional_buffer_allocation_failure_uses_native_open(monkeypatch):
    calls = []
    result = object()

    def open_file(*args, **kwargs):
        calls.append((args, kwargs))
        if 'buffering' in kwargs:
            raise MemoryError('optional buffer unavailable')
        return result
    monkeypatch.setattr(buffering, '_OPEN', open_file)
    assert buffering._buffered_open('target_raw.fif', 'wb') is result
    assert calls == [(('target_raw.fif', 'wb'), {'buffering': 1_048_576}),
                     (('target_raw.fif', 'wb'), {})]


def test_nested_code_dependency_names_are_collected():
    namespace = {}
    exec('def body(items):\n    return tuple(nested_dependency(x) for x in items)', namespace)
    code = namespace['body'].__code__
    assert 'nested_dependency' not in code.co_names
    assert 'nested_dependency' in buffering._global_names(code)

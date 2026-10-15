"""Packed preloads preserve native bytes, warning fallback and Raw ownership."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from functools import partial, wraps
import pickle
import threading
import warnings
import weakref

import mne
import numpy as np
import pytest

from Main_App.io import bdf_preload as candidate


def _write(path, *, samples=(262144,) * 4, duration=128, records=1,
           date="01.01.24", physical=(-262144, 262143), digital=(-8388608, 8388607),
           filters=("",) * 4, patient="P0", labels=("Cz", "Pz", "EXG1", "Status")):
    def field(value, width):
        value = str(value).encode("ascii")
        assert len(value) <= width
        return value.ljust(width, b" ")
    fixed = bytearray(b" " * 256)
    for start, stop, value in ((8, 88, patient), (88, 168, "exact_probe"), (168, 176, date),
            (176, 184, "00.00.00"), (184, 192, 1280), (192, 236, "24BIT"),
            (236, 244, records), (244, 252, duration), (252, 256, 4)):
        fixed[start:stop] = field(value, stop - start)
    fixed[:8] = b"\xffBIOSEMI"
    values = [(labels, 16), (("",) * 4, 80), (("uV",) * 4, 8),
              ((physical[0],) * 4, 8), ((physical[1],) * 4, 8),
              ((digital[0],) * 4, 8), ((digital[1],) * 4, 8), (filters, 80),
              (samples, 8), (("",) * 4, 32)]
    with path.open("wb") as stream:
        stream.write(bytes(fixed) + b"".join(field(v, w) for row, w in values for v in row))
        for index, count in enumerate(samples):
            values = (np.arange(count, dtype="<u4") * np.uint32(19873 + 151 * index)) & np.uint32(0xffffff)
            stream.write(values.view(np.uint8).reshape(-1, 4)[:, :3].tobytes())
    return path


@pytest.fixture
def adapter(monkeypatch):
    try:
        result = candidate._PackedPreload()
    except (ValueError, AttributeError, ImportError):
        pytest.skip("Optional packed preload requires the characterized MNE/NumPy/CPython runtime")
    assert result.valid()
    monkeypatch.setattr(candidate, "_ADAPTER", result)
    return result


@pytest.fixture
def source(tmp_path):
    return _write(tmp_path / "ordinary.bdf")


def _selected(source, preload=True, include=None, stim_channel="Status", verbose=False):
    return candidate.select_bdf_preload_reader(source, preload=preload, stim_channel=stim_channel,
                                               include=include, verbose=verbose)


def _call(reader):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        raw = reader()
    return raw, [(str(w.message), w.category, w.filename, w.lineno) for w in caught]


def _metadata(raw):
    return pickle.dumps({key: value for key, value in vars(raw).items() if key != "_data"}, protocol=5)


def _close(raw):
    raw.close()
    mapping = getattr(raw._data, "_mmap", None)
    if mapping is not None:
        mapping.close()


@pytest.mark.parametrize("mode", ["ram", "memmap"])
def test_same_kwargs_every_byte_full_native_instance_state_and_immediate_release(source, tmp_path, adapter, mode):
    target = True if mode == "ram" else str(tmp_path / "identical.dat")
    values = []
    for reader in (lambda: mne.io.read_raw_bdf(source, preload=target, stim_channel="Status", include=None, verbose=False),
                   _selected(source, preload=target)):
        raw, observed = _call(reader)
        assert type(raw) is adapter.raw_class
        assert "_read_segment" not in vars(raw)
        values.append((raw._data.dtype.str, raw._data.shape, raw._data.strides, raw._data.tobytes(),
                       _metadata(raw), observed, sorted(vars(raw))))
        reference = weakref.ref(raw)
        _close(raw)
        del raw
        assert reference() is None
    assert values[0] == values[1]
    assert values[0][5] == []


def test_copy_deepcopy_pickle_and_later_native_lookup_remain_native(source, adapter, monkeypatch):
    raw = _selected(source)()
    native = mne.io.read_raw_bdf(source, preload=True, stim_channel="Status", include=None, verbose=False)
    original = adapter.base.BaseRaw._read_segment
    calls = []
    @wraps(original)
    def replacement(self, *args, **kwargs):
        calls.append(id(self))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(adapter.base.BaseRaw, "_read_segment", replacement)
    try:
        for operation in (copy.deepcopy, lambda value: value.copy(), lambda value: pickle.loads(pickle.dumps(value))):
            restored = operation(raw)
            native_restored = operation(native)
            try:
                assert type(restored) is type(raw)
                assert "_read_segment" not in vars(restored)
                assert restored._data.tobytes() == raw._data.tobytes()
                assert _metadata(restored) == _metadata(native_restored)
            finally:
                _close(restored)
                _close(native_restored)
        raw._read_segment(0, 32)
        assert calls == [id(raw)]
    finally:
        _close(raw)
        _close(native)


@pytest.mark.parametrize("options", [
    {"date": "99.99.99"}, {"records": 2}, {"digital": (0, 0)},
    {"physical": (0, 0)}, {"samples": (16, 32, 32, 32)},
    {"filters": ("HP: DC; LP: 417 Hz", "HP: 0.1; LP: 417 Hz", "", "No filtering")},
    {"patient": "P0 M 01-JAN-2000 Person"},
])
def test_warning_or_extended_header_routes_return_native_binding(tmp_path, adapter, options):
    options.setdefault("samples", (16,) * 4)
    source = _write(tmp_path / "unsupported.bdf", **options)
    selected = _selected(source)
    assert selected.func is mne.io.read_raw_bdf
    outcomes = []
    for reader in (partial(mne.io.read_raw_bdf, source, preload=True, stim_channel="Status", include=None, verbose=False), selected):
        try:
            raw, observed = _call(reader)
        except Exception as error:
            outcomes.append((type(error), str(error)))
        else:
            outcomes.append((_metadata(raw), raw._data.tobytes(), observed))
            _close(raw)
    assert outcomes[0] == outcomes[1]


@pytest.mark.parametrize("preload", [False, None, "relative.dat", np.bool_(True)])
def test_unsupported_preload_is_native_and_creates_no_map(source, adapter, preload):
    assert _selected(source, preload=preload).func is mne.io.read_raw_bdf


@pytest.mark.parametrize("include", [[], "Cz", ["Status", "Cz"], ["Cz", "Cz", "Status"], ["missing", "Status"]])
def test_invalid_or_unordered_include_is_native(source, adapter, include):
    assert _selected(source, include=include).func is mne.io.read_raw_bdf


def test_bound_include_does_not_change_after_selection(source, adapter):
    include = ["Cz", "Status"]
    selected = _selected(source, include=include)
    assert selected.func is adapter.public
    include[:] = ["Pz", "Status"]
    raw = selected()
    try:
        assert raw.ch_names == ["Cz", "Status"]
    finally:
        _close(raw)


@pytest.mark.parametrize("name", sorted(candidate._FINGERPRINTS))
def test_cached_native_code_mutation_falls_back_before_constructing(source, adapter, monkeypatch, name):
    function = adapter.functions[name]
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_name="changed_native_code"))
    assert _selected(source).func is mne.io.read_raw_bdf


def test_keyword_default_mutation_falls_back(source, adapter, monkeypatch):
    function = adapter.functions["public"]
    monkeypatch.setitem(function.__kwdefaults__, "verbose", "ERROR")
    assert _selected(source).func is mne.io.read_raw_bdf


def test_new_global_shadow_and_numpy_replacement_fall_back(source, adapter, monkeypatch):
    monkeypatch.setitem(adapter.functions["file_reader"].__globals__, "open", lambda *args: None)
    assert _selected(source).func is mne.io.read_raw_bdf
    monkeypatch.undo()
    monkeypatch.setattr(candidate, "_ADAPTER", adapter)
    monkeypatch.setattr(np, "fromfile", lambda *args, **kwargs: None)
    assert _selected(source).func is mne.io.read_raw_bdf


def test_unknown_runtime_and_custom_allocator_fall_back(source, adapter, monkeypatch):
    monkeypatch.setattr(candidate, "_supported_runtime", lambda: False)
    assert _selected(source).func is mne.io.read_raw_bdf
    monkeypatch.undo()
    monkeypatch.setattr(candidate, "_ADAPTER", adapter)
    # Replace the class binding rather than mutate native allocator slots;
    # restoring __new__ can itself change CPython constructor dispatch.
    class CustomAllocatedRaw(adapter.raw_class):
        def __new__(cls, *args, **kwargs):
            return object.__new__(cls)
    monkeypatch.setattr(adapter.edf, "RawEDF", CustomAllocatedRaw)
    assert _selected(source).func is mne.io.read_raw_bdf


@pytest.mark.parametrize("length", [0, 1, 2, 4, 5])
def test_truncation_error_cursor_and_result_bits_are_native(tmp_path, adapter, monkeypatch, length):
    monkeypatch.setattr(candidate, "_MIN_PACKED_SAMPLES", 1)
    source = tmp_path / "truncated.bin"
    source.write_bytes(bytes(range(length)))
    outcomes = []
    for operation in (adapter.functions["channel_reader"], adapter.read_channel):
        with source.open("rb") as stream:
            try:
                result = operation(stream, "bdf", 2, 3, "<u1")
                outcome = (result.dtype.str, result.shape, result.tobytes())
            except Exception as error:
                outcome = (type(error), str(error))
            outcomes.append((outcome, stream.tell()))
    assert outcomes[0] == outcomes[1]


def test_failed_speculative_allocation_releases_buffer_and_rewinds_before_native_retry(tmp_path, adapter, monkeypatch):
    monkeypatch.setattr(candidate, "_MIN_PACKED_SAMPLES", 1)
    source = tmp_path / "packed.bin"
    source.write_bytes(b"prefix" + b"\x01\x02\x83" * 32)
    original_fromfile = np.fromfile
    references = []
    def observed_fromfile(*args, **kwargs):
        result = original_fromfile(*args, **kwargs)
        references.append(weakref.ref(result))
        return result
    def allocation_failure(*args, **kwargs):
        raise MemoryError("Injected allocation failure")
    native = adapter.functions["channel_reader"]
    def retry(*args, **kwargs):
        assert references[0]() is None
        assert args[0].tell() == 6
        return native(*args, **kwargs)
    monkeypatch.setattr(np, "fromfile", observed_fromfile)
    monkeypatch.setattr(adapter, "empty", allocation_failure)
    adapter.functions["channel_reader"] = retry
    with source.open("rb") as stream:
        stream.seek(6)
        actual = adapter.read_channel(stream, "bdf", 32, 3, "<u1")
        actual_cursor = stream.tell()
    with source.open("rb") as stream:
        stream.seek(6)
        expected = native(stream, "bdf", 32, 3, "<u1")
        assert actual_cursor == stream.tell()
    assert actual.tobytes() == expected.tobytes()


def test_malformed_finite_duration_overflow_rate_is_rejected(tmp_path, adapter):
    source = _write(tmp_path / "overflow.bdf", samples=(16,) * 4, duration="1e-308")
    assert _selected(source).func is mne.io.read_raw_bdf


def test_prefilter_real_acquisition_pattern_uses_ephemeral_packed_route(tmp_path, adapter):
    source = _write(tmp_path / "acquisition.bdf", filters=("HP: DC; LP: 417 Hz",) * 3 + ("No filtering",))
    selected = _selected(source)
    assert selected.func is adapter.public
    raw, observed = _call(selected)
    try:
        assert observed == [] and "_read_segment" not in vars(raw)
    finally:
        _close(raw)


def test_large_native_preload_actually_uses_packed_decoder(source, adapter, monkeypatch):
    allocations = []
    original = adapter.empty
    def observed_empty(*args, **kwargs):
        allocations.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter, "empty", observed_empty)
    raw = _selected(source)()
    try:
        assert allocations == [sum((262144,) * 4)]
        assert "_read_segment" not in vars(raw)
    finally:
        _close(raw)


def test_constructor_failure_restores_binding_and_releases_partial_native_raw(source, adapter, monkeypatch):
    original = adapter.raw_class.__init__
    references = []
    def fail_constructor(raw, *args, **kwargs):
        references.append(weakref.ref(raw))
        raise RuntimeError("Injected constructor failure")
    monkeypatch.setattr(adapter.raw_class, "__init__", fail_constructor)
    with pytest.raises(RuntimeError, match="Injected constructor failure"):
        adapter.construct(source, preload=True, stim_channel="Status", verbose=False)
    assert references[0]() is None
    monkeypatch.setattr(adapter.raw_class, "__init__", original)


def test_changed_implementation_before_first_selection_rejects_pins(source, adapter, monkeypatch):
    function = adapter.functions["channel_reader"]
    monkeypatch.setattr(function, "__code__", function.__code__.replace(co_consts=(*function.__code__.co_consts, "changed")))
    monkeypatch.setattr(candidate, "_ADAPTER", None)
    assert _selected(source).func is mne.io.read_raw_bdf


def test_header_scaling_overflow_stays_native(tmp_path, adapter):
    source = _write(tmp_path / "scaling.bdf", samples=(16,) * 4,
                    physical=(0, "1e+308"), digital=(0, "1e-308"))
    assert _selected(source).func is mne.io.read_raw_bdf


@pytest.mark.parametrize("name", ["empty", "right_shift", "negative", "uint8", "int32"])
def test_preexisting_decoder_replacement_is_rejected_even_if_import_snapshot_matches(source, adapter, monkeypatch, name):
    original = getattr(np, name)
    def replacement(*args, **kwargs):
        return original(*args, **kwargs)
    monkeypatch.setattr(np, name, replacement)
    # Simulate an unknown binding already present when this module imported;
    # a self-consistent snapshot cannot establish native allocator semantics.
    monkeypatch.setitem(candidate._NATIVE_NUMPY, name, replacement)
    monkeypatch.setattr(candidate, "_ADAPTER", None)
    assert _selected(source).func is mne.io.read_raw_bdf


def test_preexisting_nested_constructor_warning_helper_uses_direct_native_location(source, adapter, monkeypatch):
    original = adapter.edf._check_stim_channel
    def changed_helper(*args, **kwargs):
        adapter.edf.warn("Injected nested constructor warning.")
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter.edf, "_check_stim_channel", changed_helper)
    monkeypatch.setattr(candidate, "_ADAPTER", None)
    selected = _selected(source)
    assert selected.func is mne.io.read_raw_bdf
    observations = []
    for reader in (partial(mne.io.read_raw_bdf, source, preload=True, stim_channel="Status", include=None, verbose=False), selected):
        raw, observed = _call(reader)
        try:
            observations.append((raw._data.tobytes(), _metadata(raw), observed))
            assert observed and observed[0][2] == __file__
        finally:
            _close(raw)
    assert observations[0] == observations[1]


def _lazy(source):
    return mne.io.read_raw_bdf(source, preload=False, stim_channel="Status", verbose=False)


def _lazy_data(raw, **kwargs):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        data = raw.get_data(verbose=False, **kwargs)
    return data, [(str(w.message), w.category, w.filename, w.lineno) for w in caught]


@pytest.mark.parametrize("limits", [(0, None), (0, 31), (719, 250000)])
def test_owned_lazy_one_call_every_byte_state_and_immediate_release(source, adapter, limits):
    native, raw = _lazy(source), _lazy(source)
    try:
        expected, expected_warnings = _lazy_data(native, start=limits[0], stop=limits[1])
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert admitted
            actual, observed = _lazy_data(raw, start=limits[0], stop=limits[1])
        assert type(raw) is type(native) is adapter.raw_class
        assert "_read_segment" not in vars(raw)
        assert (actual.dtype, actual.shape, actual.strides, actual.tobytes()) == (
            expected.dtype, expected.shape, expected.strides, expected.tobytes())
        assert observed == expected_warnings == []
        assert pickle.dumps(vars(raw), protocol=5) == pickle.dumps(vars(native), protocol=5)
    finally:
        raw.close()
        native.close()
    reference = weakref.ref(raw)
    del raw
    assert reference() is None


def test_owned_lazy_initial_stim_events_and_scoped_preflight_calls(source, adapter):
    from Main_App.processing.preflight_qc import _find_preflight_events, _read_condition_data

    # Exercise find_events' nonzero initial-stim branch in the ordinary domain.
    with source.open("r+b") as stream:
        stream.seek(1280 + 3 * 262144 * 3)
        stream.write(b"\x01\x00\x00")
    native, raw = _lazy(source), _lazy(source)
    try:
        expected = mne.find_events(native, stim_channel="Status", shortest_event=1, verbose=False)
        actual, origin = _find_preflight_events(raw, stim_channel="Status")
        assert origin == "stim" and actual.tobytes() == expected.tobytes()
        assert "_read_segment" not in vars(raw)
        data = _read_condition_data(raw, picks=(0, 1), start=719, stop=250000,
                                    io_semaphore=threading.BoundedSemaphore(1))
        assert data.tobytes() == native.get_data(picks=[0, 1], start=719, stop=250000, verbose=False).tobytes()
        assert pickle.dumps(vars(raw), protocol=5) == pickle.dumps(vars(native), protocol=5)
    finally:
        raw.close()
        native.close()


def test_owned_lazy_failure_restores_binding_and_later_native_lookup(source, adapter, monkeypatch):
    raw = _lazy(source)
    try:
        def fail(*args, **kwargs):
            raise RuntimeError("Injected lazy decode failure")
        monkeypatch.setattr(adapter, "empty", fail)
        with pytest.raises(RuntimeError, match="Injected lazy decode failure"):
            with candidate.owned_bdf_lazy_read(raw) as admitted:
                assert admitted
                _lazy_data(raw)
        assert "_read_segment" not in vars(raw)
        original = adapter.base.BaseRaw._read_segment
        calls = []
        @wraps(original)
        def changed(self, *args, **kwargs):
            calls.append(id(self))
            return original(self, *args, **kwargs)
        monkeypatch.setattr(adapter.base.BaseRaw, "_read_segment", changed)
        _lazy_data(raw, start=0, stop=31)
        assert calls == [id(raw)]
    finally:
        raw.close()


@pytest.mark.parametrize("method", ["get_data", "_getitem", "__getitem__", "_parse_get_set_params",
                                    "_handle_tmin_tmax", "_read_segment", "_read_segment_file"])
def test_owned_lazy_local_override_is_rejected_and_preserved(source, adapter, method):
    raw = _lazy(source)
    replacement = getattr(raw, method)
    setattr(raw, method, replacement)
    try:
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert not admitted
        assert vars(raw)[method] is replacement
    finally:
        raw.close()


def test_owned_lazy_different_raw_owners_are_independent(source, adapter):
    barrier = threading.Barrier(2)
    def read():
        raw = _lazy(source)
        try:
            with candidate.owned_bdf_lazy_read(raw) as admitted:
                assert admitted
                barrier.wait(timeout=10)
                data = raw.get_data(verbose=False)
            assert "_read_segment" not in vars(raw)
            return data.tobytes(), pickle.dumps(vars(raw), protocol=5)
        finally:
            raw.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: read(), range(2)))
    assert results[0] == results[1]


def test_owned_lazy_post_exit_copy_and_pickle_keep_native_ownership(source, adapter):
    native, raw = _lazy(source), _lazy(source)
    try:
        native.get_data(verbose=False)
        with candidate.owned_bdf_lazy_read(raw):
            raw.get_data(verbose=False)
        for operation in (copy.deepcopy, lambda value: value.copy(), lambda value: pickle.loads(pickle.dumps(value))):
            restored, native_restored = operation(raw), operation(native)
            try:
                assert type(restored) is adapter.raw_class and "_read_segment" not in vars(restored)
                assert pickle.dumps(vars(restored), protocol=5) == pickle.dumps(vars(native_restored), protocol=5)
                assert restored.get_data(start=0, stop=31, verbose=False).tobytes() == native_restored.get_data(
                    start=0, stop=31, verbose=False).tobytes()
            finally:
                restored.close()
                native_restored.close()
    finally:
        raw.close()
        native.close()


def test_owned_lazy_mixed_grid_warning_is_direct_native(tmp_path, adapter):
    source = _write(tmp_path / "mixed.bdf", samples=(131072, 262144, 262144, 262144))
    native, raw = _lazy(source), _lazy(source)
    try:
        expected, expected_warnings = _lazy_data(native, start=100000, stop=200000)
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
            actual, observed = _lazy_data(raw, start=100000, stop=200000)
        assert actual.tobytes() == expected.tobytes()
        assert observed == expected_warnings and expected_warnings
    finally:
        raw.close()
        native.close()


def test_owned_lazy_preexisting_nested_warning_uses_same_native_location(source, adapter, monkeypatch):
    native, raw = _lazy(source), _lazy(source)
    original = adapter.edf._read_ch
    def changed(*args, **kwargs):
        adapter.edf.warn("Injected nested lazy-read warning.")
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter.edf, "_read_ch", changed)
    monkeypatch.setattr(candidate, "_ADAPTER", None)
    try:
        expected, expected_warnings = _lazy_data(native, start=0, stop=31)
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
            actual, observed = _lazy_data(raw, start=0, stop=31)
        assert actual.tobytes() == expected.tobytes()
        assert observed == expected_warnings and observed[0][2] == __file__
    finally:
        raw.close()
        native.close()


def test_owned_lazy_negative_event_warning_override_stays_native(source, adapter):
    from types import MethodType

    native, raw = _lazy(source), _lazy(source)
    def data(self, item, return_times=True):
        return np.array([[-1., 0., -2., 0.]]), np.arange(4)
    # find_events uses raw[picks, :], whose native __getitem__ calls _getitem.
    native._getitem, raw._getitem = MethodType(data, native), MethodType(data, raw)
    def events(value):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = mne.find_events(value, stim_channel="Status", shortest_event=1, verbose=False)
        return result.tobytes(), [(str(w.message), w.category, w.filename, w.lineno) for w in caught]
    try:
        expected = events(native)
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
            actual = events(raw)
        assert actual == expected and expected[1]
    finally:
        raw.close()
        native.close()


@pytest.mark.parametrize("value", [None, object(), mne.io.RawArray(np.zeros((1, 8)), mne.create_info(["Cz"], 128), verbose=False)])
def test_owned_lazy_unknown_raw_is_noop(value, adapter):
    with candidate.owned_bdf_lazy_read(value) as admitted:
        assert not admitted


@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("name", ["get_data_wrapper", "get_data_body", "getitem", "getitem_entry",
                                  "parse_params", "handle_times", "find_events_wrapper", "find_events_body"])
def test_owned_lazy_changed_read_helper_is_rejected_before_binding(source, adapter, monkeypatch, initial, name):
    raw = _lazy(source)
    try:
        function = adapter.functions[name]
        monkeypatch.setattr(function, "__code__", function.__code__.replace(
            co_consts=(*function.__code__.co_consts, "changed_read_helper")))
        if initial:
            monkeypatch.setattr(candidate, "_ADAPTER", None)
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
    finally:
        raw.close()


def test_owned_lazy_preflight_annotation_fallback_sees_restored_native_binding(source, adapter, monkeypatch):
    from Main_App.processing.preflight_qc import _find_preflight_events

    raw = _lazy(source)
    def fail(*args, **kwargs):
        raise RuntimeError("Injected event-read failure")
    monkeypatch.setattr(adapter, "empty", fail)
    def annotations(value, *, verbose):
        assert value is raw and verbose is False and "_read_segment" not in vars(value)
        return np.array([[1, 0, 17]], dtype=np.int64), {"condition": 17}
    monkeypatch.setattr(mne, "events_from_annotations", annotations)
    try:
        events, origin = _find_preflight_events(raw, stim_channel="Status")
        assert origin == "annotations" and events.tolist() == [[1, 0, 17]]
        assert "_read_segment" not in vars(raw)
    finally:
        raw.close()


def test_owned_lazy_rejects_preloaded_raw(source, adapter):
    raw = _selected(source)()
    try:
        with candidate.owned_bdf_lazy_read(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
    finally:
        _close(raw)

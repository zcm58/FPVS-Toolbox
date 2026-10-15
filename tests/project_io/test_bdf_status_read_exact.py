"""Status-only unpacking preserves native public bytes, errors and ownership."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
import copy
from functools import wraps
import pickle
import threading
import weakref

import mne
import numpy as np
import pytest

from Main_App.io import bdf_preload as candidate
from test_bdf_preload_exact import _lazy, _lazy_data, _write


@pytest.fixture
def adapter(monkeypatch):
    try:
        result = candidate._PackedPreload()
    except (ValueError, AttributeError, ImportError):
        pytest.skip("Optional Status unpacking requires the characterized native runtime")
    assert result.valid()
    monkeypatch.setattr(candidate, "_ADAPTER", result)
    return result


@pytest.fixture
def source(tmp_path):
    return _write(tmp_path / "ordinary.bdf")


def _scope(raw):
    return candidate.owned_bdf_lazy_read(raw, stim_channel="Status", status_only=True)


def _data(raw, **kwargs):
    return _lazy_data(raw, picks=["Status"], **kwargs)


@pytest.mark.parametrize("limits", [(0, None), (0, 31), (719, 250000)])
def test_every_selected_byte_full_state_and_immediate_release(source, adapter, limits):
    outcomes = []
    for mode in ("native", "packed", "selected"):
        raw = _lazy(source)
        context = (_scope(raw) if mode == "selected" else candidate.owned_bdf_lazy_read(raw)
                   if mode == "packed" else nullcontext(False))
        try:
            with context as admitted:
                assert bool(admitted) == (mode != "native")
                values, seen = _data(raw, start=limits[0], stop=limits[1])
            assert type(raw) is adapter.raw_class and "_read_segment" not in vars(raw)
            outcomes.append((values.dtype.str, values.shape, values.strides, values.tobytes(),
                             pickle.dumps(vars(raw), protocol=5), seen))
        finally:
            raw.close()
        reference = weakref.ref(raw)
        del raw, context
        assert reference() is None
    assert outcomes[0] == outcomes[1] == outcomes[2]


def test_preflight_event_seam_uses_selected_decoder_and_initial_stim(source, adapter, monkeypatch):
    from Main_App.processing.preflight_qc import _find_preflight_events

    with source.open("r+b") as stream:
        stream.seek(1280 + 3 * 262144 * 3)
        stream.write(b"\x01\x00\x00")
    native, raw = _lazy(source), _lazy(source)
    original = adapter.empty
    allocations = []
    def empty(*args, **kwargs):
        allocations.append(args[0])
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter, "empty", empty)
    try:
        expected = mne.find_events(native, stim_channel="Status", shortest_event=1, verbose=False)
        actual, origin = _find_preflight_events(raw, stim_channel="Status")
        assert origin == "stim" and actual.tobytes() == expected.tobytes()
        assert allocations == [1048576]
        assert "_read_segment" not in vars(raw)
        assert pickle.dumps(vars(raw), protocol=5) == pickle.dumps(vars(native), protocol=5)
    finally:
        raw.close()
        native.close()


def test_other_channels_use_direct_native_without_unspecified_slots(source, adapter, monkeypatch):
    native, raw = _lazy(source), _lazy(source)
    def forbidden(*args, **kwargs):
        raise AssertionError("Selective decoder must not run for other picks")
    monkeypatch.setattr(candidate._StatusRead, "read_channel", forbidden)
    try:
        expected = native.get_data(picks=["Cz", "Status"], verbose=False)
        with _scope(raw) as admitted:
            assert admitted
            actual = raw.get_data(picks=["Cz", "Status"], verbose=False)
        assert actual.tobytes() == expected.tobytes()
        assert pickle.dumps(vars(raw), protocol=5) == pickle.dumps(vars(native), protocol=5)
    finally:
        raw.close()
        native.close()


@pytest.mark.parametrize("idx", [np.array([3]), [3], slice(3, 4, 2), slice(0, 1)])
def test_only_native_one_status_slice_admits_selected_file_reader(source, adapter, monkeypatch, idx):
    raw = _lazy(source)
    reader = candidate._StatusRead(adapter, (262144,) * 4, 3, 3)
    def forbidden(*args, **kwargs):
        raise AssertionError("Unsupported idx must use the direct native class reader")
    monkeypatch.setattr(reader, "class_reader", forbidden)
    try:
        expected, actual = np.empty((1, raw.n_times)), np.empty((1, raw.n_times))
        cals = np.ones((1, 1))
        stop = int(raw.n_times)  # Native BaseRaw converts before this private seam.
        adapter.functions["class_reader"](adapter.protector_class(raw), expected, idx, 0, 0, stop, cals, None)
        protector = reader.protector(raw)
        protector._read_segment_file(actual, idx, 0, 0, stop, cals, None)
        assert actual.tobytes() == expected.tobytes()
        assert "_read_segment_file" not in vars(protector)
    finally:
        reader.segment = reader.class_reader = None
        raw.close()


@pytest.mark.parametrize("length", [0, 1, 2, 3, 5, 6, 9, 12, 15, 18, 21])
def test_short_read_every_received_byte_error_and_cursor_are_native(tmp_path, adapter, monkeypatch, length):
    monkeypatch.setattr(candidate, "_MIN_PACKED_SAMPLES", 1)
    path = tmp_path / "partial.bin"
    path.write_bytes(b"prefix" + bytes(range(length)))
    reader = candidate._StatusRead(adapter, (1, 1, 1, 1), 3, 3)
    outcomes = []
    try:
        for operation in (adapter.functions["channel_reader"], reader.read_channel):
            with path.open("rb") as stream:
                stream.seek(6)
                try:
                    data = operation(stream, "bdf", 8, 3, "<u1")
                    result = (data.dtype.str, data.shape, data.tobytes())
                except Exception as error:
                    result = (type(error), str(error))
                outcomes.append((result, stream.tell()))
        assert outcomes[0] == outcomes[1]
    finally:
        reader.segment = reader.class_reader = None


@pytest.mark.parametrize("trim", [3, 6, 262144 * 3])
def test_truncation_after_header_admission_preserves_later_native_reshape(source, adapter, trim):
    original = source.read_bytes()
    header = bytearray(original[:1280])
    header[236:244] = b"2       "
    complete = bytes(header) + original[1280:] * 2
    outcomes = []
    for selected in (False, True):
        source.write_bytes(complete)
        raw = _lazy(source)
        try:
            try:
                with (_scope(raw) if selected else nullcontext(False)) as admitted:
                    assert bool(admitted) == selected
                    with source.open("r+b") as stream:
                        stream.truncate(len(complete) - trim)
                    values, seen = _data(raw)
                result = (values.dtype.str, values.shape, values.tobytes(), seen)
            except Exception as error:
                result = (type(error), str(error))
            assert "_read_segment" not in vars(raw)
            outcomes.append((result, pickle.dumps(vars(raw), protocol=5)))
        finally:
            raw.close()
    assert outcomes[0] == outcomes[1]


def test_allocation_failure_releases_buffer_and_rewinds_before_native_retry(tmp_path, adapter, monkeypatch):
    monkeypatch.setattr(candidate, "_MIN_PACKED_SAMPLES", 1)
    source = tmp_path / "allocation.bin"
    source.write_bytes(b"prefix" + b"\x01\x02\x83" * 8)
    reader = candidate._StatusRead(adapter, (1, 1, 1, 1), 3, 3)
    original_fromfile, native = np.fromfile, adapter.functions["channel_reader"]
    references = []
    def fromfile(*args, **kwargs):
        result = original_fromfile(*args, **kwargs)
        references.append(weakref.ref(result))
        return result
    def fail(*args, **kwargs):
        raise MemoryError("Injected selected allocation failure")
    def retry(*args, **kwargs):
        assert references[0]() is None and args[0].tell() == 6
        return native(*args, **kwargs)
    monkeypatch.setattr(np, "fromfile", fromfile)
    monkeypatch.setattr(reader, "empty", fail)
    monkeypatch.setitem(adapter.functions, "channel_reader", retry)
    try:
        with source.open("rb") as stream:
            stream.seek(6)
            actual = reader.read_channel(stream, "bdf", 8, 3, "<u1")
            assert stream.tell() == 30
        with source.open("rb") as stream:
            stream.seek(6)
            expected = native(stream, "bdf", 8, 3, "<u1")
        assert actual.tobytes() == expected.tobytes()
    finally:
        reader.segment = reader.class_reader = None


def test_failure_restores_binding_and_later_native_lookup(source, adapter, monkeypatch):
    raw = _lazy(source)
    try:
        def fail(*args, **kwargs):
            raise RuntimeError("Injected selected failure")
        monkeypatch.setattr(adapter, "empty", fail)
        with pytest.raises(RuntimeError, match="Injected selected failure"):
            with _scope(raw) as admitted:
                assert admitted
                _data(raw)
        assert "_read_segment" not in vars(raw)
        original = adapter.base.BaseRaw._read_segment
        calls = []
        @wraps(original)
        def changed(self, *args, **kwargs):
            calls.append(id(self))
            return original(self, *args, **kwargs)
        monkeypatch.setattr(adapter.base.BaseRaw, "_read_segment", changed)
        _data(raw, start=0, stop=31)
        assert calls == [id(raw)]
    finally:
        raw.close()


def test_different_raw_owners_have_independent_selection(source, adapter):
    barrier = threading.Barrier(2)
    def read():
        raw = _lazy(source)
        try:
            with _scope(raw) as admitted:
                assert admitted
                barrier.wait(timeout=10)
                values, seen = _data(raw)
            assert "_read_segment" not in vars(raw)
            return values.tobytes(), pickle.dumps(vars(raw), protocol=5), seen
        finally:
            raw.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: read(), range(2)))
    assert results[0] == results[1]


@pytest.mark.parametrize("field", ["_projector", "_comp"])
def test_projection_or_compensation_keeps_native_lookup(source, adapter, field):
    raw = _lazy(source)
    setattr(raw, field, np.eye(len(raw.ch_names)))
    try:
        with _scope(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
    finally:
        raw.close()


def test_unknown_native_warning_keeps_original_caller(source, adapter, monkeypatch):
    native, raw = _lazy(source), _lazy(source)
    original = adapter.edf._read_ch
    def changed(*args, **kwargs):
        adapter.edf.warn("Injected native Status-read warning.")
        return original(*args, **kwargs)
    monkeypatch.setattr(adapter.edf, "_read_ch", changed)
    try:
        expected, expected_warnings = _data(native, start=0, stop=31)
        with _scope(raw) as admitted:
            assert not admitted and "_read_segment" not in vars(raw)
            actual, seen = _data(raw, start=0, stop=31)
        assert actual.tobytes() == expected.tobytes()
        assert seen == expected_warnings and seen
    finally:
        raw.close()
        native.close()


def test_preloaded_or_local_override_raw_keeps_native_lookup(source, adapter):
    for preload in (False, True):
        raw = mne.io.read_raw_bdf(source, preload=preload, stim_channel="Status", verbose=False)
        if not preload:
            raw.get_data = raw.get_data
        try:
            with _scope(raw) as admitted:
                assert not admitted and "_read_segment" not in vars(raw)
        finally:
            raw.close()


def test_copy_pickle_and_private_reader_release_after_exit(source, adapter):
    native, raw = _lazy(source), _lazy(source)
    try:
        _data(native)
        with _scope(raw):
            factory = raw._read_segment.__func__.__globals__["_function_"].__globals__["_ReadSegmentFileProtector"]
            reader_reference = weakref.ref(factory.__self__)
            del factory
            _data(raw)
        assert reader_reference() is None
        for operation in (copy.deepcopy, lambda value: value.copy(), lambda value: pickle.loads(pickle.dumps(value))):
            restored, expected = operation(raw), operation(native)
            try:
                assert type(restored) is adapter.raw_class and "_read_segment" not in vars(restored)
                assert pickle.dumps(vars(restored), protocol=5) == pickle.dumps(vars(expected), protocol=5)
                assert _data(restored, start=0, stop=31)[0].tobytes() == _data(expected, start=0, stop=31)[0].tobytes()
            finally:
                restored.close()
                expected.close()
    finally:
        raw.close()
        native.close()

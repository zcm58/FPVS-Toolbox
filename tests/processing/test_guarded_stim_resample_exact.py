from __future__ import annotations

import importlib.util
from itertools import product
from types import MethodType
import warnings

import mne
import numpy as np
import pytest

from Main_App.processing import guarded_stim_resample as guarded

ORIGINAL_HELPER = mne.io.BaseRaw.resample.__wrapped__.__globals__["_resample_stim_channels"]


@pytest.fixture(autouse=True)
def clear_adapter():
    guarded._adapter.cache_clear()
    yield
    guarded._adapter.cache_clear()


def _capture(function, *args, **kwargs):
    with warnings.catch_warnings(record=True) as caught, np.errstate(all="warn"):
        warnings.simplefilter("always")
        try:
            value = function(*args, **kwargs)
            result = ("return", value.dtype.str, value.shape, value.tobytes())
        except (ValueError, FloatingPointError, ZeroDivisionError, OverflowError) as exc:
            result = ("raise", type(exc), str(exc))
    return result, tuple((item.category, str(item.message)) for item in caught)


@pytest.mark.parametrize("length", [0, 1, 2, 3, 4, 7, 8, 31, 32, 127, 128, 1001, 2048])
@pytest.mark.parametrize("channels", [1, 3])
@pytest.mark.parametrize("ratio", [(1, 2), (256., 512.), (2, 3), (1, 4), (1, 8), (256., 2048.),
                                   (1, 16), (1, 32), (2, 1), (1, 1), (1, 0), (0, 1)])
def test_generic_windows_match_original_outcome_and_all_bits(length, channels, ratio):
    values = np.random.default_rng(length).choice(
        [0., -0., 1., 17., 255., -2.], size=(channels, length),
    )
    before = values.tobytes()
    expected = _capture(ORIGINAL_HELPER, values, *ratio)
    actual = _capture(guarded._stim_windows_exact, values, *ratio, original=ORIGINAL_HELPER)

    assert actual == expected
    assert values.tobytes() == before


def test_every_short_first_nonzero_signed_zero_window_is_exact():
    for values in product([-0., 0., 1., 17.], repeat=4):
        data = np.asarray(values, dtype=np.float64)
        expected = ORIGINAL_HELPER(data, np.int64(2), 4)
        actual = guarded._stim_windows_exact(data, np.int64(2), 4, original=ORIGINAL_HELPER)
        assert actual.tobytes() == expected.tobytes()


@pytest.mark.parametrize("case", ["float32", "endian", "reverse", "fortran", "nan", "nan_payload", "infinity", "readonly", "scalar"])
@pytest.mark.parametrize("width", [2, 4, 8, 16])
def test_layouts_and_nonfinite_inputs_preserve_original_outcome(case, width):
    values = np.array([[0., -0., 17., 21., 0., 1., -0., 0.], [1., 2., 0., 3., 0., -0., 0., 2.]])
    if case == "float32":
        values = values.astype(np.float32)
    elif case == "endian":
        values = values.astype(">f8")
    elif case == "reverse":
        values = values[:, ::-1]
    elif case == "fortran":
        values = np.asfortranarray(values)
    elif case == "nan":
        values[0, 0] = np.nan
    elif case == "nan_payload":
        values.view(np.uint64)[0, 0] = 0x7FF0000000000017
    elif case == "infinity":
        values[0, 0] = np.inf
    elif case == "readonly":
        values.flags.writeable = False
    else:
        values = np.asarray(17.)
    before = values.tobytes()

    assert _capture(guarded._stim_windows_exact, values, 1, width, original=ORIGINAL_HELPER) == _capture(
        ORIGINAL_HELPER, values, 1, width,
    )
    assert values.tobytes() == before


def test_supported_ratio_does_not_invoke_original_helper():
    def unexpected(*_args):
        raise AssertionError("integer-ratio finite native data should use exact windows")

    actual = guarded._stim_windows_exact(np.array([-0., 0., 0., 17., 2., 21.]), 1, 2, original=unexpected)
    assert actual.tobytes() == np.array([-0., 17., 2.]).tobytes()


def test_optional_allocation_failure_retains_original(monkeypatch):
    data = np.array([0., 17., 21., 2.])
    expected = ORIGINAL_HELPER(data, 1, 2)

    def no_scratch(*_args):
        raise MemoryError("optional scratch unavailable")

    monkeypatch.setattr(guarded, "_select_integer_windows", no_scratch)
    assert guarded._stim_windows_exact(data, 1, 2, original=ORIGINAL_HELPER).tobytes() == expected.tobytes()


def _raw(length=8192, *, first_samp=13, sfreq=512.):
    data = np.random.default_rng(615).normal(scale=500e-6, size=(4, length))
    data[2:] = 0.
    for offset, code in ((20, 17.), (100, 1.), (101, 2.), (700, 21.), (1000, 17.)):
        if offset < length:
            data[2, offset] = code
            data[3, offset] = code + 1.
    return mne.io.RawArray(
        data, mne.create_info(["Fp1", "Pz", "Status", "Stim2"], sfreq, ["eeg", "eeg", "stim", "stim"]),
        first_samp=first_samp, verbose=False,
    )


def _bits_tree(value):
    if isinstance(value, np.ndarray):
        return (value.dtype.str, value.shape, value.tobytes())
    if isinstance(value, (float, np.floating)):
        return np.float64(value).tobytes()
    if isinstance(value, dict):
        return tuple((key, _bits_tree(item)) for key, item in value.items())
    if isinstance(value, (tuple, list)):
        return tuple(_bits_tree(item) for item in value)
    return value


def _public_snapshot(raw):
    return _bits_tree({
        "data": raw._data, "info": dict(raw.info), "times": raw.times,
        "first_samps": raw._first_samps, "last_samps": raw._last_samps,
        "lengths": raw._raw_lengths, "cropped_samp": raw._cropped_samp,
        "annotations": {
            "onset": raw.annotations.onset, "duration": raw.annotations.duration,
            "description": raw.annotations.description, "orig_time": raw.annotations.orig_time,
        },
    })


def _run_public(raw, target, *, optimized, **kwargs):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = guarded.resample_raw(raw, target, **kwargs) if optimized else raw.resample(target, **kwargs)
    events = result[1] if isinstance(result, tuple) else None
    return _public_snapshot(raw), _bits_tree(events), tuple((item.category, str(item.message)) for item in caught)


@pytest.mark.parametrize("length", [8192, 8193])
@pytest.mark.parametrize("target", [256., 128., 768.])
@pytest.mark.parametrize("events_supplied", [False, True])
def test_public_resample_full_arrays_info_offsets_events_and_warnings_are_exact(length, target, events_supplied):
    raw = _raw(length)
    raw.set_annotations(mne.Annotations([0.2], [0.05], ["audit"]), emit_warning=False)
    events = np.array([[33, 0, 17], [113, 0, 1], [713, 0, 21]], dtype=int)
    before = events.tobytes()
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}
    if events_supplied:
        kwargs["events"] = events

    expected = _run_public(raw.copy(), target, optimized=False, **kwargs)
    actual = _run_public(raw.copy(), target, optimized=True, **kwargs)

    assert actual == expected
    assert events.tobytes() == before


def test_public_multisegment_resampling_is_exact():
    raw = mne.concatenate_raws([_raw(2048, first_samp=0), _raw(2049, first_samp=700)])
    kwargs = {"npad": 0, "window": "boxcar", "verbose": False}
    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == _run_public(
        raw.copy(), 256., optimized=False, **kwargs,
    )


def test_public_event_loss_warning_remains_at_mne_boundary():
    raw = _raw(2048, first_samp=0)
    raw._data[2:] = 0.
    raw._data[2, 100:102] = 1.
    raw._data[2, 102:104] = 2.
    expected = _run_public(raw.copy(), 128., optimized=False, npad="auto", window="hann", verbose=False)
    actual = _run_public(raw.copy(), 128., optimized=True, npad="auto", window="hann", verbose=False)

    assert actual == expected
    assert any("event information to become unreliable" in message for _category, message in actual[2])


def test_public_lazy_raw_resampling_is_exact(tmp_path):
    path = tmp_path / "lazy_raw.fif"
    _raw(2048).save(path, overwrite=True, verbose=False)
    first = mne.io.read_raw_fif(path, preload=False, verbose=False)
    second = mne.io.read_raw_fif(path, preload=False, verbose=False)
    try:
        assert _run_public(first, 256., optimized=True, npad="auto", window="hann", verbose=False) == _run_public(
            second, 256., optimized=False, npad="auto", window="hann", verbose=False,
        )
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("construct_before_change", [False, True])
def test_unknown_stim_helper_uses_current_public_resample(monkeypatch, construct_before_change):
    if construct_before_change:
        assert guarded._adapter() is not None
    body = mne.io.BaseRaw.resample.__wrapped__
    original = body.__globals__["_resample_stim_channels"]
    calls = []

    def changed(data, up, down):
        calls.append(data.shape)
        return original(data, up, down) + 0.125

    monkeypatch.setitem(body.__globals__, "_resample_stim_channels", changed)
    raw = _raw(2048)
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}

    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == _run_public(
        raw.copy(), 256., optimized=False, **kwargs,
    )
    assert len(calls) == 2


@pytest.mark.parametrize("fallback", ["disabled", "unknown_runtime", "changed_numpy", "allocation"])
def test_adapter_fallback_forwards_original_public_behavior(monkeypatch, fallback):
    raw = _raw(2048)
    expected = _run_public(raw.copy(), 256., optimized=False, npad="auto", window="hann", verbose=False)
    kwargs = {}
    if fallback == "disabled":
        kwargs["use_exact_stim"] = False
    elif fallback == "unknown_runtime":
        monkeypatch.setattr(guarded, "_supported_runtime", lambda: False)
    elif fallback == "changed_numpy":
        native = np.isfinite
        monkeypatch.setattr(np, "isfinite", lambda *args, **kwargs: native(*args, **kwargs))
    else:
        def unavailable():
            raise MemoryError("optional adapter unavailable")
        monkeypatch.setattr(guarded, "_Adapter", unavailable)

    assert _run_public(raw.copy(), 256., optimized=True, npad="auto", window="hann", verbose=False, **kwargs) == expected


def test_custom_resample_override_is_called_without_adaptation():
    class CustomRaw:
        def resample(self, target, **kwargs):
            return target, kwargs

    assert guarded.resample_raw(CustomRaw(), 256., npad="auto", window="hann") == (
        256., {"npad": "auto", "window": "hann"},
    )


@pytest.mark.parametrize("construct_before_change", [False, True])
def test_shadowed_builtin_disables_isolated_adapter(monkeypatch, construct_before_change):
    adapter = guarded._adapter() if construct_before_change else None
    helper = mne.io.BaseRaw.resample.__wrapped__.__globals__["_resample_stim_channels"]
    monkeypatch.setitem(helper.__globals__, "float", lambda value: float(value))
    raw = _raw(2048)

    if adapter is not None:
        assert not adapter.valid_for(raw)
    else:
        assert guarded._adapter() is None


def test_new_absent_global_disables_isolated_adapter(monkeypatch):
    adapter = guarded._adapter()
    assert adapter is not None
    helper = adapter.functions["helper"]
    assert "nonzero" not in helper.__globals__
    monkeypatch.setitem(helper.__globals__, "nonzero", object())

    assert not adapter.valid_for(_raw(2048))


def test_changed_closure_cell_disables_isolated_adapter():
    adapter = guarded._adapter()
    assert adapter is not None

    def enclosing():
        state = object()

        def dependency():
            return state

        return dependency

    function = enclosing()
    adapter.dependencies.append((function, function.__code__, None, None, {}, {}, guarded._closure_values(function)))
    raw = _raw(2048)
    assert adapter.valid_for(raw)
    function.__closure__[0].cell_contents = object()

    assert not adapter.valid_for(raw)


def test_wrong_bound_self_retains_current_public_method():
    original_raw, expected_target = _raw(2048), _raw(4096)
    actual_raw, actual_target = original_raw.copy(), expected_target.copy()
    original_raw.resample = MethodType(mne.io.BaseRaw.resample, expected_target)
    actual_raw.resample = MethodType(mne.io.BaseRaw.resample, actual_target)
    adapter = guarded._adapter()
    assert adapter is not None and not adapter.valid_for(actual_raw)
    before = _public_snapshot(actual_raw)
    expected = original_raw.resample(256., npad="auto", window="hann", verbose=False)
    actual = guarded.resample_raw(actual_raw, 256., npad="auto", window="hann", verbose=False)

    assert actual is actual_target
    assert expected is expected_target
    assert _public_snapshot(actual_target) == _public_snapshot(expected_target)
    assert _public_snapshot(actual_raw) == before


@pytest.mark.parametrize("construct_before_change", [False, True])
def test_replaced_globals_builtin_mapping_retains_native_function_binding(monkeypatch, construct_before_change):
    adapter = guarded._adapter() if construct_before_change else None
    helper = mne.io.BaseRaw.resample.__wrapped__.__globals__["_resample_stim_channels"]
    native_builtins = helper.__builtins__
    replacement = dict(native_builtins, float=lambda value: 1.0)
    monkeypatch.setitem(helper.__globals__, "__builtins__", replacement)
    raw = _raw(2048)

    assert helper.__builtins__ is native_builtins
    if adapter is not None:
        assert not adapter.valid_for(raw)
    else:
        assert guarded._adapter() is None
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}
    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == _run_public(
        raw.copy(), 256., optimized=False, **kwargs,
    )


def test_changed_nested_generator_dependency_retains_current_public_method(monkeypatch):
    adapter = guarded._adapter()
    assert adapter is not None
    body = adapter.functions["body"]
    assert "_resamp_ratio_len" not in body.__code__.co_names
    assert "_resamp_ratio_len" in guarded._referenced_names(body.__code__)
    original = body.__globals__["_resamp_ratio_len"]
    calls = []

    def changed(up, down, length):
        calls.append((up, down, length))
        return original(up, down, length)

    monkeypatch.setitem(body.__globals__, "_resamp_ratio_len", changed)
    raw = _raw(2048)
    assert not adapter.valid_for(raw)
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}
    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == _run_public(
        raw.copy(), 256., optimized=False, **kwargs,
    )
    assert len(calls) == 2


@pytest.mark.parametrize("construct_before", [False, True])
def test_stateful_window_default_does_not_run_equality_during_admission(monkeypatch, construct_before):
    adapter = guarded._adapter() if construct_before else None
    calls = []

    class StatefulWindow:
        def __eq__(self, other):
            calls.append(other)
            return True

        def __call__(self, frequencies):
            return np.zeros_like(frequencies)

    monkeypatch.setitem(mne.io.BaseRaw.resample.__kwdefaults__, "window", StatefulWindow())
    raw = _raw(2048)
    if adapter is not None:
        assert not adapter.valid_for(raw)
    else:
        assert guarded._adapter() is None
    assert calls == []
    kwargs = {"npad": "auto", "verbose": False}
    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == _run_public(
        raw.copy(), 256., optimized=False, **kwargs,
    )


@pytest.mark.parametrize("construct_before", [False, True])
@pytest.mark.parametrize("name,value", [("axis", 0), ("ndmin", 1), ("trans1d", -1), ("matrix", False)])
def test_stateful_index_state_does_not_run_equality_during_admission(monkeypatch, construct_before, name, value):
    adapter = guarded._adapter() if construct_before else None
    calls = []

    class StatefulIndex:
        def __eq__(self, other):
            calls.append(other)
            return True

    monkeypatch.setattr(np.r_, name, StatefulIndex())
    if adapter is not None:
        assert not adapter.valid_for(_raw(2048))
    else:
        assert guarded._adapter() is None
    assert calls == []


def _isolated_adapter():
    spec = importlib.util.spec_from_file_location("independent_stim_guard", guarded.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_preimport_fake_atleast_2d_wrapped_metadata_retains_current_original_helper(monkeypatch):
    native = np.atleast_2d
    calls = []

    def changed(*arrays):
        calls.append(None)
        return native(*arrays) + .125

    changed.__wrapped__ = native.__wrapped__
    changed._implementation = native._implementation
    monkeypatch.setattr(np, "atleast_2d", changed)
    isolated = _isolated_adapter()
    assert isolated._adapter() is None
    data = np.array([0., 17., 21., 2.])
    actual = isolated._stim_windows_exact(data, 1, 2, original=ORIGINAL_HELPER)
    expected = ORIGINAL_HELPER(data, 1, 2)
    assert actual.tobytes() == expected.tobytes()
    assert len(calls) == 2


def test_preimport_where_hidden_callback_is_never_added_to_original_helper(monkeypatch):
    native = np.where
    calls = []

    def relevant_args(condition, x=None, y=None):
        calls.append(None)
        if condition.ndim == 2:
            condition[:] = False
        return (condition, x, y)

    replacement = np._core._multiarray_umath._ArrayFunctionDispatcher(relevant_args, native._implementation)
    replacement.__wrapped__ = native.__wrapped__
    monkeypatch.setattr(np, "where", replacement)
    isolated = _isolated_adapter()
    assert isolated._adapter() is not None
    data = np.array([[0., 17., 21., 21., 0., 2., -0., 0.]])
    actual = isolated._stim_windows_exact(data, 1, 2, original=ORIGINAL_HELPER)
    expected = ORIGINAL_HELPER(data, 1, 2)
    assert actual.tobytes() == expected.tobytes()
    assert calls == []


def test_hidden_atleast_2d_callback_runs_once_and_changed_prefix_values_are_used(monkeypatch):
    native = np.atleast_2d
    calls = []

    def relevant_args(*arrays):
        calls.append(None)
        arrays[0][..., 0] = 31.
        return arrays

    replacement = np._core._multiarray_umath._ArrayFunctionDispatcher(relevant_args, native._implementation)
    replacement.__wrapped__ = native.__wrapped__
    monkeypatch.setattr(np, "atleast_2d", replacement)
    isolated = _isolated_adapter()
    data = np.array([[0., 17., 21., 21., 0., 2., -0., 0.]])
    first, second = data.copy(), data.copy()
    actual = isolated._stim_windows_exact(first, 1, 2, original=ORIGINAL_HELPER)
    expected = ORIGINAL_HELPER(second, 1, 2)
    assert actual.tobytes() == expected.tobytes()
    assert first.tobytes() == second.tobytes()
    assert len(calls) == 2


def test_changed_window_setup_falls_back_with_prefix_arrays_without_repeating_calls(monkeypatch):
    native = np.minimum
    calls = []

    def changed(first, second):
        calls.append(None)
        result = native(first, second)
        result[1:] += 1
        return result

    monkeypatch.setattr(np, "minimum", changed)
    monkeypatch.setattr(np._core._multiarray_umath, "minimum", changed)
    isolated = _isolated_adapter()
    data = np.array([[0., 17., 21., 21., 0., 2., -0., 0.]])
    actual = isolated._stim_windows_exact(data, 1, 2, original=ORIGINAL_HELPER)
    expected = ORIGINAL_HELPER(data, 1, 2)
    assert actual.tobytes() == expected.tobytes()
    assert len(calls) == 2


def test_optional_mask_allocation_failure_does_not_repeat_original_prefix(monkeypatch):
    native = np.atleast_2d
    calls = []

    def relevant_args(*arrays):
        calls.append(None)
        return arrays

    replacement = np._core._multiarray_umath._ArrayFunctionDispatcher(relevant_args, native._implementation)
    replacement.__wrapped__ = native.__wrapped__
    monkeypatch.setattr(np, "atleast_2d", replacement)
    isolated = _isolated_adapter()

    def unavailable(*_args):
        raise MemoryError("optional masks unavailable")

    monkeypatch.setattr(isolated, "_select_integer_windows", unavailable)
    data = np.array([[0., 17., 21., 21., 0., 2., -0., 0.]])
    actual = isolated._stim_windows_exact(data, 1, 2, original=ORIGINAL_HELPER)
    expected = ORIGINAL_HELPER(data, 1, 2)
    assert actual.tobytes() == expected.tobytes()
    assert len(calls) == 2


@pytest.mark.parametrize("width", [2, 4, 8, 16])
def test_integer_width_uses_native_selection_and_allocates_values_before_commit(monkeypatch, width):
    calls = []
    native = guarded._select_integer_windows

    def observed(data, picks, actual_width):
        calls.append(actual_width)
        return native(data, picks, actual_width)

    monkeypatch.setattr(guarded, "_select_integer_windows", observed)
    data = np.random.default_rng(width).choice([0., -0., 1., 17., -2.], size=(3, width * 9))
    before = data.tobytes()
    actual = guarded._stim_windows_exact(data, 1, width, original=ORIGINAL_HELPER)
    expected = ORIGINAL_HELPER(data, 1, width)
    assert actual.tobytes() == expected.tobytes()
    assert data.tobytes() == before
    assert calls == [width]


@pytest.mark.parametrize("width", [2, 4, 8, 16])
def test_all_zero_signs_and_every_first_nonzero_position_are_exact(width):
    for signs in product([-0., 0.], repeat=min(width, 8)):
        row = np.resize(np.asarray(signs, dtype="f8"), width)
        expected = ORIGINAL_HELPER(row, 1, width)
        actual = guarded._stim_windows_exact(row, 1, width, original=ORIGINAL_HELPER)
        assert actual.tobytes() == expected.tobytes()
    codes = [1., -2., 17., 2**24 - 1., np.nextafter(0., 1.), np.finfo(float).max]
    for position, code in product(range(width), codes):
        row = np.full(width, -0.)
        row[position:] = 21.
        row[position] = code
        before = row.tobytes()
        expected = _capture(ORIGINAL_HELPER, row, 1, width)
        actual = _capture(guarded._stim_windows_exact, row, 1, width, original=ORIGINAL_HELPER)
        assert actual == expected
        assert row.tobytes() == before


@pytest.mark.parametrize("length", [4096, 4097, 65536, 65539])
@pytest.mark.parametrize("target", [512., 256., 128.])
@pytest.mark.parametrize("events_supplied", [False, True])
def test_real_rate_public_resample_full_arrays_info_events_and_warnings_are_exact(length, target, events_supplied):
    raw = _raw(length, sfreq=2048.)
    raw.set_annotations(mne.Annotations([.2], [.05], ["audit"]), emit_warning=False)
    events = np.array([[33, 0, 17], [113, 0, 1], [713, 0, 21]], dtype=int)
    before = events.tobytes()
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}
    if events_supplied:
        kwargs["events"] = events
    assert _run_public(raw.copy(), target, optimized=True, **kwargs) == _run_public(
        raw.copy(), target, optimized=False, **kwargs,
    )
    assert events.tobytes() == before


def test_eight_to_one_adapted_public_call_exercises_native_selection(monkeypatch):
    native = guarded._select_integer_windows
    calls = []

    def observed(data, picks, width):
        calls.append((data.shape, picks.size, width))
        return native(data, picks, width)

    monkeypatch.setattr(guarded, "_select_integer_windows", observed)
    raw = _raw(65536, sfreq=2048.)
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}
    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == _run_public(
        raw.copy(), 256., optimized=False, **kwargs,
    )
    assert calls == [((2, 65536), 8192, 8)]


@pytest.mark.parametrize("fail", [False, True])
def test_eight_to_one_all_optional_selected_rows_precede_output_commit(monkeypatch, fail):
    data = np.random.default_rng(191).choice([0., -0., 1., 17., 21.], size=(3, 256))
    expected = ORIGINAL_HELPER(data, 1, 8)
    before = data.tobytes()
    native_zeros = np.zeros
    native_selection = guarded._select_integer_windows
    destinations = []

    def observed_zeros(*args, **kwargs):
        output = native_zeros(*args, **kwargs)
        destinations.append(output)
        return output

    def observed_selection(values, picks, width):
        assert destinations[0].tobytes() == bytes(destinations[0].nbytes)
        first_row = values[0, picks]
        assert first_row.size == picks.size
        assert destinations[0].tobytes() == bytes(destinations[0].nbytes)
        if fail:
            raise MemoryError("optional second-row allocation unavailable")
        rows = native_selection(values, picks, width)
        assert destinations[0].tobytes() == bytes(destinations[0].nbytes)
        return rows

    # Deliberately expose the private output for the allocation-order check;
    # production admission rejects this changed public allocation operator.
    monkeypatch.setattr(guarded, "_numpy_dependencies_valid", lambda: True)
    monkeypatch.setattr(np, "zeros", observed_zeros)
    monkeypatch.setattr(guarded, "_select_integer_windows", observed_selection)
    actual = guarded._stim_windows_exact(data, 1, 8, original=ORIGINAL_HELPER)
    assert actual.tobytes() == expected.tobytes()
    assert data.tobytes() == before
    assert len(destinations) == 1


def test_eight_to_one_uses_no_new_public_argmax_or_where_dispatcher(monkeypatch):
    data = np.array([[0., 0., -0., 17., 21., 0., 2., -0.] * 4])
    expected = ORIGINAL_HELPER(data, 256., 2048.)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("no additional public dispatcher is allowed")

    monkeypatch.setattr(np, "argmax", unexpected)
    monkeypatch.setattr(np, "where", unexpected)
    monkeypatch.setattr(np, "take_along_axis", unexpected)
    actual = guarded._stim_windows_exact(data, 256., 2048., original=ORIGINAL_HELPER)
    assert actual.tobytes() == expected.tobytes()


def test_eight_to_one_unknown_current_helper_and_disabled_adapter_remain_exact(monkeypatch):
    body = mne.io.BaseRaw.resample.__wrapped__
    native = body.__globals__["_resample_stim_channels"]

    def changed(data, up, down):
        return native(data, up, down) + .125

    raw = _raw(4096, sfreq=2048.)
    kwargs = {"npad": "auto", "window": "hann", "verbose": False}
    monkeypatch.setitem(body.__globals__, "_resample_stim_channels", changed)
    expected = _run_public(raw.copy(), 256., optimized=False, **kwargs)
    assert _run_public(raw.copy(), 256., optimized=True, **kwargs) == expected
    assert _run_public(raw.copy(), 256., optimized=True, use_exact_stim=False, **kwargs) == expected

"""Exact characterization of the bounded, isolated MNE FIR adapter."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import struct
import threading
from types import SimpleNamespace
import warnings

import mne
import numpy as np
import pytest

from Main_App.processing import prepared_fir as fir
from Main_App.processing.prepared_raw_codec import encode_state, raw_state


FILTER = dict(
    method="fir", phase="zero-double", fir_window="hamming", fir_design="firwin",
    l_trans_bandwidth=1., h_trans_bandwidth=1., filter_length=425,
    skip_by_annotation="edge", verbose=False,
)


def _raw(*, samples=2048, layout="C", annotated=False):
    data = np.random.default_rng(77191).normal(size=(5, samples)) * 1e-6
    data[-1] = 0.
    data[-1, ::31] = 55.
    data = np.array(data, order=layout)
    raw = mne.io.RawArray(
        data, mne.create_info(["Fp1", "Fp2", "Oz", "EXG1", "Status"], 128.,
                             ["eeg", "eeg", "eeg", "eog", "stim"]),
        first_samp=37, verbose=False,
    )
    raw.info["bads"] = ["Oz"]
    if annotated:
        raw.set_annotations(mne.Annotations([2., 8.], [0., 0.], ["edge", "edge"]))
    return raw


def _exact_state(left, right):
    assert (left._data.dtype, left._data.shape, left._data.strides) == (
        right._data.dtype, right._data.shape, right._data.strides,
    )
    assert left._data.tobytes() == right._data.tobytes()
    left_arrays, right_arrays = {}, {}
    assert encode_state(raw_state(left), left_arrays) == encode_state(raw_state(right), right_arrays)
    assert left_arrays.keys() == right_arrays.keys()
    for name in left_arrays:
        a, b = left_arrays[name], right_arrays[name]
        assert (a.dtype, a.shape, a.strides) == (b.dtype, b.shape, b.strides)
        assert a.tobytes() == b.tobytes()


def _observed(call):
    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always")
        try:
            result, error = call(), None
        except Exception as exc:
            result, error = None, (type(exc), str(exc))
    return result, error, [(row.category, str(row.message)) for row in records]


def _require_adapter(cache):
    if not fir._supported_runtime():
        pytest.skip("The exact MNE/Python/NumPy implementation is not supported here")
    assert cache.adapter_available, "Pinned runtime must exercise the optimized adapter"


@pytest.mark.parametrize("layout,annotated", [("C", False), ("F", False), ("C", True)])
def test_cold_warm_filter_and_metadata_equal_public_mne(layout, annotated):
    source = _raw(layout=layout, annotated=annotated)
    expected = source.copy().filter(1., 20., **FILTER)
    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    original_filter = mne.filter.filter_data
    original_overlap = mne.filter._overlap_add_filter
    original_convolve = np.convolve
    original_raw_filter = mne.io.BaseRaw.filter
    with fir.prepared_fir_scope(cache):
        for _ in range(2):
            result = source.copy()
            returned = fir.filter_raw_with_prepared_fir(result, 1., 20., **FILTER)
            assert returned is result
            _exact_state(expected, result)
    assert cache.misses == 1 and cache.hits >= 1
    assert mne.filter.filter_data is original_filter
    assert mne.filter._overlap_add_filter is original_overlap
    assert np.convolve is original_convolve
    assert mne.io.BaseRaw.filter is original_raw_filter
    assert fir.current_prepared_fir_cache() is None


@pytest.mark.parametrize("case", ["short", "nonfinite", "zeros", "invalid_cutoff"])
def test_filter_warnings_errors_and_special_samples_equal_public_mne(case):
    source = _raw(samples=127 if case == "short" else 2048)
    if case == "nonfinite":
        source._data[0, 12] = np.inf
        source._data[1, 80] = np.nan
    elif case == "zeros":
        source._data[:3] = 0.
        source._data[0, ::2] = -0.
    upper = 80. if case == "invalid_cutoff" else 20.
    expected, expected_error, expected_warnings = _observed(
        lambda: source.copy().filter(1., upper, **FILTER)
    )
    cache = fir.PreparedFirCache()
    with fir.prepared_fir_scope(cache):
        for _ in range(2):
            result, error, found_warnings = _observed(
                lambda: fir.filter_raw_with_prepared_fir(source.copy(), 1., upper, **FILTER)
            )
            assert error == expected_error
            assert found_warnings == expected_warnings
            if result is not None:
                _exact_state(expected, result)


def test_changed_cutoff_rebuilds_kernel_and_metadata():
    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    with fir.prepared_fir_scope(cache):
        first = fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
        changed = fir.filter_raw_with_prepared_fir(_raw(), 1., 22., **FILTER)
    assert cache.misses == 2 and cache.hits == 0
    assert first._data.tobytes() != changed._data.tobytes()
    _exact_state(_raw().filter(1., 22., **FILTER), changed)


def test_changed_native_thread_count_rebuilds_exact_kernel():
    from threadpoolctl import threadpool_limits

    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    h = mne.filter.create_filter(
        None, 2048., .1, 50., filter_length=67585, method="fir", phase="zero-double",
        fir_window="hamming", fir_design="firwin", l_trans_bandwidth=.1,
        h_trans_bandwidth=.1, verbose=False,
    )
    with threadpool_limits(limits=1, user_api="blas"):
        one = cache._convolve(h, h[::-1])
    with threadpool_limits(limits=2, user_api="blas"):
        expected = np.convolve(h, h[::-1])
        actual = cache._convolve(h, h[::-1])
        assert actual.dtype == expected.dtype and actual.shape == expected.shape
        assert actual.strides == expected.strides and actual.tobytes() == expected.tobytes()
    assert cache.misses == 2 and cache.hits == 0
    # Some BLAS implementations produce the same bytes at both thread counts;
    # invalidation must still occur rather than assuming that equivalence.
    assert one.shape == expected.shape


def test_native_thread_state_change_during_convolution_prevents_admission(monkeypatch):
    cache = fir.PreparedFirCache()
    h = np.array([.2, .5, -.3])
    expected = np.convolve(h, h[::-1])
    state = [("before",)]
    monkeypatch.setattr(fir, "_native_threadpool_key", lambda: state[0])
    original = np.convolve

    def changing(*args, **kwargs):
        result = original(*args, **kwargs)
        state[0] = ("after",)
        return result

    monkeypatch.setattr(np, "convolve", changing)
    actual = cache._convolve(h, h[::-1])
    assert actual.tobytes() == expected.tobytes()
    assert cache.retained_bytes == 0


def test_uncharacterized_native_thread_state_uses_original(monkeypatch):
    cache = fir.PreparedFirCache()
    h = np.array([.2, .5, -.3])
    expected = np.convolve(h, h[::-1])
    # An otherwise valid pool belonging only to SciPy cannot account for the
    # NumPy convolution's native reduction state.
    scipy_pool = dict(user_api="blas", internal_api="openblas", num_threads=1,
        filepath=str(Path(np.__file__).resolve().parent.parent / "scipy.libs" / "libscipy_openblas.dll"),
        prefix="libscipy_openblas", version="0.3.29", threading_layer="pthreads", architecture="Haswell")
    monkeypatch.setattr(fir, "threadpoolctl", SimpleNamespace(threadpool_info=lambda: [scipy_pool]))
    assert cache._convolve(h, h[::-1]).tobytes() == expected.tobytes()
    assert cache.hits == cache.misses == cache.retained_bytes == 0


def test_native_thread_state_change_during_hit_detachment_uses_original(monkeypatch):
    cache = fir.PreparedFirCache()
    h = np.array([.2, .5, -.3])
    state = [("before",)]
    monkeypatch.setattr(fir, "_native_threadpool_key", lambda: state[0])
    expected = cache._convolve(h, h[::-1])
    frombuffer = np.frombuffer

    def changing(*args, **kwargs):
        result = frombuffer(*args, **kwargs)
        state[0] = ("after",)
        # Deliberately poison the optional detached hit; fallback must ignore it.
        return np.full(result.shape, 77.)

    monkeypatch.setattr(np, "frombuffer", changing)
    actual = cache._convolve(h, h[::-1])
    assert actual.tobytes() == expected.tobytes()


def test_no_scope_or_overridden_raw_filter_uses_caller_method():
    class RawDouble:
        def filter(self, *args, **kwargs):
            return args, kwargs

    raw = RawDouble()
    assert fir.filter_raw_with_prepared_fir(raw, 1., 20., **FILTER) == ((1., 20.), FILTER)
    with fir.prepared_fir_scope(fir.PreparedFirCache()):
        assert fir.filter_raw_with_prepared_fir(raw, 1., 20., **FILTER) == ((1., 20.), FILTER)


def test_runtime_or_dependency_replacement_falls_back_before_mutation(monkeypatch):
    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    called = []
    original = mne.filter.filter_data

    def replacement(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(mne.filter, "filter_data", replacement)
    with fir.prepared_fir_scope(cache):
        result = fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
    assert called and cache.hits == cache.misses == 0
    assert result.info["lowpass"] == 20.


def test_version_fallback_does_not_attempt_adapter(monkeypatch):
    monkeypatch.setattr(mne, "__version__", "future-unsupported")
    cache = fir.PreparedFirCache()
    with fir.prepared_fir_scope(cache):
        result = fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
    assert cache.hits == cache.misses == 0
    _exact_state(_raw().filter(1., 20., **FILTER), result)


@pytest.mark.parametrize("when", ["before", "after"])
def test_changed_mixin_defaults_use_public_forwarded_defaults(monkeypatch, when):
    if when == "after":
        cache = fir.PreparedFirCache()
        _require_adapter(cache)
    function = mne.filter.FilterMixin.filter
    monkeypatch.setattr(function, "__defaults__", ([0], *function.__defaults__[1:]))
    if when == "before":
        cache = fir.PreparedFirCache()
    expected = _raw().filter(1., 20., **FILTER)
    with fir.prepared_fir_scope(cache):
        actual = fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
    _exact_state(expected, actual)
    assert cache.hits == cache.misses == 0


def test_mutated_keyword_defaults_and_changed_native_operator_cannot_reuse(monkeypatch):
    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    with fir.prepared_fir_scope(cache):
        fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
        monkeypatch.setitem(mne.filter.filter_data.__kwdefaults__, "verbose", "error")
        assert not cache._adapter.valid_for(_raw())
        monkeypatch.undo()
        original = np._core.multiarray.correlate

        def changed(*args, **kwargs):
            return original(*args, **kwargs) * .75

        monkeypatch.setattr(np._core.multiarray, "correlate", changed)
        expected = _raw().filter(1., 20., **FILTER)
        actual = fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
    _exact_state(expected, actual)
    assert cache.hits == 0 and cache.misses == 1


def test_uncomparable_dependency_defaults_fall_back_before_filtering(monkeypatch):
    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    monkeypatch.setitem(mne.filter.filter_data.__kwdefaults__, "verbose", np.array([0, 1]))
    expected = _raw().filter(1., 20., **FILTER)
    with fir.prepared_fir_scope(cache):
        actual = fir.filter_raw_with_prepared_fir(_raw(), 1., 20., **FILTER)
    _exact_state(expected, actual)
    assert cache.hits == cache.misses == 0


def test_custom_mro_preserves_baseraw_super_filter_override():
    class AdditionalFilter(mne.filter.FilterMixin):
        def filter(self, *_args, **_kwargs):
            self.info["description"] = "custom filter"
            return self

    class CustomRaw(mne.io.RawArray, AdditionalFilter):
        pass

    source = _raw()
    raw = CustomRaw(source._data.copy(), source.info.copy(), verbose=False)
    assert raw.filter.__func__ is mne.io.BaseRaw.filter
    cache = fir.PreparedFirCache()
    with fir.prepared_fir_scope(cache):
        result = fir.filter_raw_with_prepared_fir(raw, 1., 20., **FILTER)
    assert result is raw and result.info["description"] == "custom filter"
    assert cache.hits == cache.misses == 0


def test_cache_only_allocation_failures_preserve_original_convolution(monkeypatch):
    h = np.array([.2, .5, -.3])
    expected = np.convolve(h, h[::-1])
    cache = fir.PreparedFirCache()

    def failed(*_args, **_kwargs):
        raise MemoryError("optional cache allocation")

    monkeypatch.setattr(cache, "_key", failed)
    assert cache._convolve(h, h[::-1]).tobytes() == expected.tobytes()
    monkeypatch.undo()
    cache._convolve(h, h[::-1])
    monkeypatch.setattr(np, "frombuffer", failed)
    assert cache._convolve(h, h[::-1]).tobytes() == expected.tobytes()
    monkeypatch.undo()
    monkeypatch.setattr(fir, "_Adapter", failed)
    assert not fir.PreparedFirCache().adapter_available


def test_nested_scope_restores_outer_and_exception_disposes_activation():
    outer, inner = fir.PreparedFirCache(), fir.PreparedFirCache()
    assert fir.current_prepared_fir_cache() is None
    with fir.prepared_fir_scope(outer):
        assert fir.current_prepared_fir_cache() is outer
        with pytest.raises(RuntimeError, match="cancelled"):
            with fir.prepared_fir_scope(inner):
                assert fir.current_prepared_fir_cache() is inner
                raise RuntimeError("cancelled")
        assert fir.current_prepared_fir_cache() is outer
    assert fir.current_prepared_fir_cache() is None


def test_coefficient_cache_preserves_bits_and_detaches_results():
    h = np.array([0., -0., .2, -.7, .9], dtype=np.float64)
    cache = fir.PreparedFirCache()
    expected = np.convolve(h, h[::-1])
    first = cache._convolve(h, h[::-1])
    first[:] = 100.
    second = cache._convolve(h.copy(), h[::-1].copy())
    assert second.dtype == expected.dtype and second.shape == expected.shape
    assert second.tobytes() == expected.tobytes()
    assert cache.misses == cache.hits == 1
    changed = h.copy()
    changed[1] = 0.
    assert struct.pack("d", h[1]) != struct.pack("d", changed[1])
    assert cache._convolve(changed, changed[::-1]).tobytes() == np.convolve(changed, changed[::-1]).tobytes()
    assert cache.misses == 2


@pytest.mark.parametrize("h", [
    np.array([1., np.nan, 2.]), np.array([1., np.inf, 2.]),
    np.array([1e300, 2., 3.]), np.array([1e-300, 2., 3.]),
    np.array([1., 2., 3.], dtype=np.float32),
    np.array([1., 2., 3.], dtype=">f8"),
    np.arange(10., dtype=np.float64)[::2],
])
def test_unfamiliar_or_unsafe_coefficients_use_original_convolve(h):
    cache = fir.PreparedFirCache()
    expected, error, expected_warnings = _observed(lambda: np.convolve(h, h[::-1]))
    for _ in range(2):
        actual, found_error, found_warnings = _observed(lambda: cache._convolve(h, h[::-1]))
        assert found_error == error and found_warnings == expected_warnings
        if actual is not None:
            assert actual.dtype == expected.dtype
            assert actual.tobytes() == expected.tobytes()
    assert cache.hits == cache.misses == 0


def test_byte_cap_clear_close_and_concurrent_detached_hits():
    h = np.array([.1, .2, -.3, .7])
    expected = np.convolve(h, h[::-1])
    tiny = fir.PreparedFirCache(max_bytes=1)
    assert tiny._convolve(h, h[::-1]).tobytes() == expected.tobytes()
    assert tiny.retained_bytes == 0
    cache = fir.PreparedFirCache(max_bytes=512)
    cache._convolve(h, h[::-1])
    with ThreadPoolExecutor(max_workers=4) as pool:
        outputs = list(pool.map(lambda _: cache._convolve(h, h[::-1]), range(12)))
    assert all(value.tobytes() == expected.tobytes() for value in outputs)
    assert all(not np.shares_memory(left, right) for left, right in zip(outputs, outputs[1:]))
    assert cache.retained_bytes <= 512
    cache.clear()
    assert cache.retained_bytes == 0
    cache.close()
    cache._convolve(h, h[::-1])
    assert cache.retained_bytes == 0


def test_clear_while_preparing_never_republishes_and_does_not_hold_lock(monkeypatch):
    original = np.convolve
    started, finish = threading.Event(), threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        assert finish.wait(3)
        return original(*args, **kwargs)

    cache = fir.PreparedFirCache()
    monkeypatch.setattr(np, "convolve", delayed)
    h = np.array([.2, -.1, .7])
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(cache._convolve, h, h[::-1])
        assert started.wait(3)
        cache.clear()
        assert cache.retained_bytes == 0
        finish.set()
        assert future.result().tobytes() == original(h, h[::-1]).tobytes()
    assert cache.retained_bytes == 0


def test_replaced_numpy_convolve_cannot_reuse_previous_operator(monkeypatch):
    original = np.convolve
    cache = fir.PreparedFirCache()
    h = np.array([.2, -.1, .7])
    cache._convolve(h, h[::-1])
    called = []

    def replacement(*args, **kwargs):
        called.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(np, "convolve", replacement)
    actual = cache._convolve(h, h[::-1])
    assert called and cache.hits == 0 and cache.misses == 2
    assert actual.tobytes() == original(h, h[::-1]).tobytes()


def test_worker_scope_reuses_only_its_owned_batch_cache_and_restores_on_failure(monkeypatch, tmp_path):
    from Main_App.Performance import process_runner

    cache = fir.PreparedFirCache()
    monkeypatch.setattr(process_runner, "_WORKER_FIR_CACHE", cache)
    monkeypatch.setattr(process_runner, "_with_current_condition_repairs", lambda settings, *_a, **_k: settings)
    monkeypatch.setattr(process_runner, "_condition_repair_sources_for_files", lambda *_: {})
    seen = []

    def pipeline(*_args):
        seen.append(fir.current_prepared_fir_cache())
        if len(seen) == 2:
            raise RuntimeError("cancelled")
        return {"status": "ok"}

    monkeypatch.setattr(process_runner, "_run_full_pipeline_for_file", pipeline)
    args = (tmp_path / "recording.bdf", {}, {}, tmp_path, tmp_path)
    assert process_runner._process_one_file(*args) == {"status": "ok"}
    with pytest.raises(RuntimeError, match="cancelled"):
        process_runner._process_one_file(*args)
    assert seen == [cache, cache]
    assert fir.current_prepared_fir_cache() is None


def test_worker_initialization_closes_previous_batch_and_registers_cleanup(monkeypatch, tmp_path):
    from Main_App.Performance import process_runner

    previous = fir.PreparedFirCache()
    h = np.array([.1, .3])
    previous._convolve(h, h[::-1])
    monkeypatch.setattr(process_runner, "_WORKER_FIR_CACHE", previous)
    monkeypatch.setattr(process_runner, "set_blas_threads_multiprocess", lambda: None)
    monkeypatch.setattr(process_runner.tempfile, "gettempdir", lambda: str(tmp_path))
    finalizers = []
    monkeypatch.setattr(process_runner.atexit, "register", finalizers.append)
    process_runner._worker_init()
    current = process_runner._WORKER_FIR_CACHE
    assert current is not previous and previous._closed
    assert previous.retained_bytes == 0
    assert current.close in finalizers
    current._convolve(h, h[::-1])
    for finalize in finalizers:
        finalize()
    assert current.retained_bytes == 0 and current._closed


def test_full_preprocessing_preserves_exact_state_scientific_params_and_logs(tmp_path):
    from Main_App.processing.preprocess import perform_preprocessing
    from tests.processing.test_preprocess_kurtosis_gate import _params, _raw as full_raw

    raw = full_raw()
    raw._data[-1, 0] = 1.
    raw._data[-1, 100:601:50] = 55.
    params = _params(tmp_path / "input.bdf")
    params.update(high_pass=.5, low_pass=30., downsample_rate=80.,
                  kurtosis_auto_interpolate_all=True, enable_kurtosis_checkpoint_cache=False)
    expected_params, expected_logs = deepcopy(params), []
    expected, expected_count = perform_preprocessing(raw.copy(), expected_params, expected_logs.append)
    assert expected is not None
    cache = fir.PreparedFirCache()
    _require_adapter(cache)
    with fir.prepared_fir_scope(cache):
        for _ in range(2):
            actual_params, actual_logs = deepcopy(params), []
            actual, count = perform_preprocessing(raw.copy(), actual_params, actual_logs.append)
            assert actual is not None
            _exact_state(expected, actual)
            assert count == expected_count
            left_arrays, right_arrays = {}, {}
            assert encode_state(expected_params, left_arrays) == encode_state(actual_params, right_arrays)
            assert left_arrays.keys() == right_arrays.keys()
            for key in left_arrays:
                assert left_arrays[key].dtype == right_arrays[key].dtype
                assert left_arrays[key].shape == right_arrays[key].shape
                assert left_arrays[key].tobytes() == right_arrays[key].tobytes()
            assert actual_logs == expected_logs
    assert cache.hits == cache.misses == 1

"""Bounded, exact zero-double FIR preparation for one processing-worker batch.

MNE has no public prepared-kernel hook. On the characterized runtime only, an
isolated copy of its existing filter call chain changes the NumPy lookup for
the coefficient convolution. No MNE function, class, module or NumPy global is
patched. Unknown implementations use the ordinary public Raw.filter method.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import update_wrapper
import hashlib
from pathlib import Path
import sys
from threading import Lock
from types import BuiltinFunctionType, CodeType, FunctionType
from typing import Iterator

import mne
import numpy as np

try:
    import threadpoolctl
except ImportError:  # The public numerical path does not need this cache probe.
    threadpoolctl = None


# Characterized CPython 3.13 / MNE 1.9.0 / NumPy 2.3.1. These portable code
# fingerprints omit paths and source locations, and work in frozen installs.
# A dependency upgrade must characterize the adapter again, not relax guards.
_CODE_FINGERPRINTS = {
    "raw_filter": "0038a7aae05abb5de79fe86e53446f0bb8bebd9c7ac9f3dd0119a54f25b25ec3",
    "mixin_wrapper": "a8b1e12169f9e4d418f3e8260baed5f2963703b8e4d4d2542d3804bb71aec719",
    "mixin_body": "ec636443ee3fba719978effa1ce4c33a6f8ecafe5cb8577ccfcbe97816bcf867",
    "data_wrapper": "f047ed14688d771426e8da019c11ca6b223ec0fd77224d64d1ca679c5d90baef",
    "data_body": "890d6fe04a0f6d6bd6a77825eb979d60eccb0578be97fd94392b417a9f274316",
    "overlap": "b9e163af9e28b9d0fa881d5155e5f25bf48023151ebf21957f8d46304de00dca",
    "numpy_convolve": "d9eeee14f7e50579ee0b4483c703c314f49a021aa750535e2a471c0030a0197f",
}
_RAW_DEFAULTS = (None, "auto", "auto", "auto", None, "fir", None, "zero",
                 "hamming", "firwin", ("edge", "bad_acq_skip"), "reflect_limited", None)
_MIXIN_DEFAULTS = (*_RAW_DEFAULTS[:-2], "edge")
_DATA_DEFAULTS = (None, "auto", "auto", "auto", None, "fir", None, True,
                  "zero", "hamming", "firwin", "reflect_limited")
_CALL_DEFAULTS = {
    "raw_filter": (_RAW_DEFAULTS, {}),
    "mixin_wrapper": (_MIXIN_DEFAULTS, {"verbose": None}),
    "mixin_body": (_MIXIN_DEFAULTS, {"verbose": None}),
    "data_wrapper": (_DATA_DEFAULTS, {"verbose": None}),
    "data_body": (_DATA_DEFAULTS, {"verbose": None}),
    "overlap": ((None, "zero", None, None, True, "reflect_limited"), {}),
    "numpy_convolve": (("full",), {}),
}
_ACTIVE_CACHE: ContextVar["PreparedFirCache | None"] = ContextVar("prepared_fir_cache", default=None)


def _supported_runtime() -> bool:
    return (sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 13)
            and mne.__version__ == "1.9.0" and np.__version__ == "2.3.1")


def _native_threadpool_key() -> tuple | None:
    """Describe the characterized native reduction configuration without changing it."""
    if threadpoolctl is None:
        return None
    try:
        pools = []
        numpy_pool_found = False
        numpy_libs = Path(np.__file__).resolve().parent.parent / "numpy.libs"
        for pool in threadpoolctl.threadpool_info():
            if pool.get("user_api") != "blas":
                continue
            if (pool.get("internal_api") != "openblas"
                    or pool.get("threading_layer") not in ("pthreads", "openmp")
                    or type(pool.get("num_threads")) is not int or pool["num_threads"] < 1):
                return None
            fields = tuple(pool.get(name) for name in (
                "filepath", "prefix", "internal_api", "version", "threading_layer", "architecture",
            ))
            if not all(type(value) is str and value for value in fields):
                return None
            if (pool["prefix"] == "libscipy_openblas"
                    and Path(pool["filepath"]).resolve().parent == numpy_libs):
                numpy_pool_found = True
            pools.append((*fields, pool["num_threads"]))
        # The characterized wheels load NumPy's OpenBLAS beside the numpy
        # package. A SciPy-only or unknown-layout listing cannot prove its state.
        return tuple(sorted(pools)) if numpy_pool_found else None
    except (AttributeError, KeyError, MemoryError, OSError, RuntimeError, TypeError, ValueError):
        return None


def _code_payload(code: CodeType) -> tuple:
    def constant(value):
        if isinstance(value, CodeType):
            return ("code", _code_payload(value))
        if type(value) is tuple:
            return ("tuple", tuple(constant(item) for item in value))
        if value is None or type(value) in (str, bytes, int, float, complex, bool):
            return (type(value).__name__, value)
        raise TypeError("Unsupported implementation constant")

    return (code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
            code.co_nlocals, code.co_stacksize, code.co_flags, code.co_code,
            tuple(constant(value) for value in code.co_consts), code.co_names,
            code.co_varnames, code.co_freevars, code.co_cellvars, code.co_exceptiontable)


def _fingerprint(function: FunctionType) -> str:
    return hashlib.sha256(repr(_code_payload(function.__code__)).encode()).hexdigest()


def _clone(function: FunctionType, **globals_overrides) -> FunctionType:
    namespace = {**function.__globals__, **globals_overrides}
    cloned = FunctionType(function.__code__, namespace, function.__name__,
                          function.__defaults__, function.__closure__)
    cloned.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    update_wrapper(cloned, function)
    return cloned


class _NumpyProxy:
    def __init__(self, cache: "PreparedFirCache") -> None:
        self.convolve = cache._convolve

    def __getattr__(self, name: str):
        return getattr(np, name)


class _Adapter:
    def __init__(self, cache: "PreparedFirCache") -> None:
        if not _supported_runtime():
            raise ValueError("Uncharacterized FIR runtime")
        mf = mne.filter
        functions = {
            "raw_filter": mne.io.BaseRaw.filter,
            "mixin_wrapper": mf.FilterMixin.filter,
            "mixin_body": mf.FilterMixin.filter.__wrapped__,
            "data_wrapper": mf.filter_data,
            "data_body": mf.filter_data.__wrapped__,
            "overlap": mf._overlap_add_filter,
            "numpy_convolve": np.convolve.__wrapped__,
        }
        for name, function in functions.items():
            if not isinstance(function, FunctionType) or _fingerprint(function) != _CODE_FINGERPRINTS[name]:
                raise ValueError("Uncharacterized FIR implementation")
            if (function.__defaults__, dict(function.__kwdefaults__ or {})) != _CALL_DEFAULTS[name]:
                raise ValueError("Uncharacterized FIR defaults")
        raw_function = functions["raw_filter"]
        if raw_function.__closure__[0].cell_contents is not mne.io.BaseRaw:
            raise ValueError("Uncharacterized Raw.filter forwarding")
        for name in ("mixin", "data"):
            wrapper, body = functions[name + "_wrapper"], functions[name + "_body"]
            if (wrapper.__globals__.get("_function_") is not body
                    or wrapper.__globals__.get("_use_log_level_") is not mne.utils.use_log_level):
                raise ValueError("Uncharacterized MNE verbosity wrapper")
        if (functions["mixin_body"].__globals__.get("filter_data") is not mf.filter_data
                or functions["data_body"].__globals__.get("_overlap_add_filter") is not mf._overlap_add_filter
                or functions["overlap"].__globals__.get("np") is not np):
            raise ValueError("Uncharacterized MNE filter globals")
        self.functions = functions
        self.convolve = np.convolve
        multiarray = functions["numpy_convolve"].__globals__.get("multiarray")
        self.correlate = np._core._multiarray_umath.correlate
        if (multiarray is not np._core.multiarray or multiarray.correlate is not self.correlate
                or not isinstance(self.correlate, BuiltinFunctionType)
                or self.correlate.__name__ != "correlate"):
            raise ValueError("Uncharacterized NumPy convolution operator")
        # Detect changes to code, defaults and every referenced global between
        # files. The snapshots retain references, never shared-module mutations.
        self.dependencies = [
            (function, function.__code__, function.__defaults__, dict(function.__kwdefaults__ or {}),
             {name: function.__globals__[name] for name in function.__code__.co_names
              if name in function.__globals__})
            for function in functions.values()
        ]
        overlap = _clone(functions["overlap"], np=_NumpyProxy(cache))
        data_body = _clone(functions["data_body"], _overlap_add_filter=overlap)
        data_wrapper = _clone(functions["data_wrapper"], _function_=data_body)
        mixin_body = _clone(functions["mixin_body"], filter_data=data_wrapper)
        self.filter = _clone(functions["mixin_wrapper"], _function_=mixin_body)

    def valid_for(self, raw) -> bool:
        # Optional compatibility checks must not introduce errors that the
        # public filter would avoid. This runs before any Raw data mutation.
        try:
            return self._valid_for(raw)
        except (AttributeError, IndexError, KeyError, MemoryError, TypeError, ValueError):
            return False

    def _valid_for(self, raw) -> bool:
        if (not _supported_runtime() or np.convolve is not self.convolve
                or np._core.multiarray.correlate is not self.correlate
                or np._core._multiarray_umath.correlate is not self.correlate
                or not isinstance(raw, mne.io.BaseRaw)
                or getattr(raw.filter, "__func__", None) is not self.functions["raw_filter"]
                or getattr(super(mne.io.BaseRaw, raw).filter, "__func__", None) is not self.functions["mixin_wrapper"]
                or mne.filter.FilterMixin.filter is not self.functions["mixin_wrapper"]
                or mne.filter.filter_data is not self.functions["data_wrapper"]
                or mne.filter._overlap_add_filter is not self.functions["overlap"]):
            return False
        for function, code, defaults, kwdefaults, namespace in self.dependencies:
            if (function.__code__ is not code or function.__defaults__ != defaults
                    or dict(function.__kwdefaults__ or {}) != kwdefaults
                    or any(function.__globals__.get(name) is not value for name, value in namespace.items())):
                return False
        return True


class PreparedFirCache:
    """One immutable kernel entry, with a byte cap and no retained EEG samples."""

    def __init__(self, *, max_bytes: int = 4 * 1024 * 1024) -> None:
        self.max_bytes = max(0, int(max_bytes))
        self.hits = 0
        self.misses = 0
        self._lock = Lock()
        self._entry = None
        self._generation = 0
        self._closed = False
        try:
            self._adapter = _Adapter(self)
        except (AttributeError, IndexError, KeyError, MemoryError, TypeError, ValueError):
            self._adapter = None

    @property
    def adapter_available(self) -> bool:
        return self._adapter is not None

    @property
    def retained_bytes(self) -> int:
        with self._lock:
            return 0 if self._entry is None else len(self._entry[0][-1]) + len(self._entry[1])

    def clear(self) -> None:
        with self._lock:
            self._entry = None
            self._generation += 1

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._entry = None
            self._generation += 1

    def _key(self, a, v, mode, original):
        # Only the normal bounded FIR coefficient case is cached. Unsafe values
        # preserve the original arithmetic, error state and warning behavior.
        if (type(mode) is not str or mode != "full" or type(a) is not np.ndarray or type(v) is not np.ndarray
                or a.ndim != 1 or v.shape != a.shape or a.size == 0
                or a.dtype != np.dtype(np.float64) or v.dtype != a.dtype
                or not a.flags.c_contiguous or not a.flags.aligned or (3 * a.nbytes - 8) > self.max_bytes
                or not np.isfinite(a).all()):
            return None
        magnitude = np.abs(a)
        if (np.any(magnitude > 1.) or np.any((magnitude > 0.) & (magnitude < 1e-100))):
            return None
        kernel = a.tobytes()
        if v.tobytes() != a[::-1].tobytes():
            return None
        native_threads = _native_threadpool_key()
        if native_threads is None:
            return None
        return (original, np._core.multiarray.correlate, native_threads,
                a.dtype.str, a.shape, a.strides, kernel)

    def _convolve(self, a, v, mode="full"):
        original = np.convolve
        try:
            key = self._key(a, v, mode, original)
        except MemoryError:
            key = None
        if key is None:
            return original(a, v, mode=mode)
        with self._lock:
            generation = self._generation
            enabled = not self._closed
            payload = self._entry[1] if enabled and self._entry is not None and self._entry[0] == key else None
            if payload is not None:
                self.hits += 1
            elif enabled:
                self.misses += 1
        if payload is not None:
            try:
                result = np.frombuffer(payload, dtype=np.float64).copy()
            except MemoryError:
                return original(a, v, mode=mode)
            if _native_threadpool_key() == key[2]:
                return result
            return original(a, v, mode=mode)
        result = original(a, v, mode=mode)
        if enabled:
            try:
                payload = result.tobytes()
            except MemoryError:
                return result
            # A worker owns its fixed native configuration for the batch. Also
            # reject observed reconfiguration between files or during this call.
            # Uncoordinated native configuration changes mid-call are not safe
            # worker behavior (a before/after probe cannot detect an ABA change).
            if _native_threadpool_key() != key[2]:
                return result
            with self._lock:
                if not self._closed and self._generation == generation:
                    self._entry = (key, payload)
        return result


def current_prepared_fir_cache() -> PreparedFirCache | None:
    return _ACTIVE_CACHE.get()


@contextmanager
def prepared_fir_scope(cache: PreparedFirCache | None) -> Iterator[None]:
    """Activate a worker-owned cache for one file; always restore the caller."""
    token = _ACTIVE_CACHE.set(cache)
    try:
        yield
    finally:
        _ACTIVE_CACHE.reset(token)


def filter_raw_with_prepared_fir(raw, l_freq, h_freq, **kwargs):
    """Use the unchanged Raw filter path or its guarded isolated equivalent."""
    cache = current_prepared_fir_cache()
    adapter = None if cache is None or cache._closed else cache._adapter
    if (adapter is None or kwargs.get("method", "fir") != "fir"
            or kwargs.get("phase", "zero") != "zero-double"
            or not adapter.valid_for(raw)):
        return raw.filter(l_freq, h_freq, **kwargs)
    # BaseRaw.filter is a fingerprinted argument-forwarding wrapper; its sole
    # differing default from FilterMixin.filter is reflect_limited padding.
    return adapter.filter(raw, l_freq, h_freq, **{"pad": "reflect_limited", **kwargs})

"""Exact, isolated acceleration of MNE's integer-ratio Status windows.

The characterized Raw.resample bodies remain unchanged apart from their local
stim-helper lookup. No MNE, NumPy, class or module global is patched.
"""

from __future__ import annotations

from functools import lru_cache
import sys
from types import BuiltinFunctionType, CodeType, FunctionType

import mne
import numpy as np

from Main_App.processing.prepared_fir import _clone, _fingerprint

_FINGERPRINTS = {
    "wrapper": "da9ffd8fdab508e56384264cc8fdda5db489bcca34627f05ecd0f31aec3eecff",
    "body": "622e552f9df0418286f686dea36f7473d21e7bdfd364b8651f3dea98a11c3e9e",
    "helper": "30ca78e96ea73eea29880c5b4b31c1eca14ecafa166034253be31585d1098146",
    "atleast_2d": "14c47ab012bda18f8af9aad06b1b73b5ef0f8d974c092d9b696f03512eb0f905",
    "r_getitem": "85844708a1feccb5f0859c88b26908fcfd468770e1008e4abdd1e35cfaae58a5",
}
_KWDEFAULTS = {
    "npad": "auto", "window": "auto", "stim_picks": None, "n_jobs": None,
    "events": None, "pad": "auto", "method": "fft", "verbose": None,
}
_NUMPY_NAMES = (
    "isfinite", "dtype", "float64", "ndarray", "ufunc", "atleast_2d", "zeros", "minimum", "arange", "r_",
    "array", "concatenate", "result_type", "ndim", "newaxis", "linspace", "asanyarray",
)
_NUMPY_OPERATIONS = {name: getattr(np, name) for name in _NUMPY_NAMES}
_ABSENT = object()


def _closure_values(function):
    return tuple(cell.cell_contents for cell in (function.__closure__ or ()))


def _referenced_names(code):
    names = set(code.co_names)
    for constant in code.co_consts:
        if isinstance(constant, CodeType):
            names.update(_referenced_names(constant))
    return names


def _supported_runtime() -> bool:
    return (
        sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 13)
        and mne.__version__ == "1.9.0" and np.__version__ == "2.3.1"
    )


def _numpy_dependencies_valid() -> bool:
    return (
        all(getattr(np, name, None) is operation for name, operation in _NUMPY_OPERATIONS.items())
        and type(np.atleast_2d) is np._core._multiarray_umath._ArrayFunctionDispatcher
        and np.atleast_2d._implementation is np.atleast_2d.__wrapped__
        and np.ndarray is np._core.multiarray.ndarray
        and np.dtype is np._core.multiarray.dtype and np.float64 is np.sctypeDict["float64"]
        and np.ufunc is type(np._core._multiarray_umath.isfinite)
        and np.isfinite is np._core._multiarray_umath.isfinite
        and type(np.isfinite) is np.ufunc and np.isfinite.__name__ == "isfinite"
        and "d->?" in np.isfinite.types
        and np.arange is np._core._multiarray_umath.arange
        and type(np.arange) is BuiltinFunctionType and np.arange.__name__ == "arange"
        and np.arange.__module__ == "numpy"
        and np.zeros is np._core._multiarray_umath.zeros
        and type(np.zeros) is BuiltinFunctionType and np.zeros.__name__ == "zeros"
        and np.zeros.__module__ == "numpy"
        and np.minimum is np._core._multiarray_umath.minimum
        and type(np.minimum) is np.ufunc and np.minimum.__name__ == "minimum"
        and "dd->d" in np.minimum.types
    )


def _kwdefaults_valid(function, expected):
    actual = function.__kwdefaults__
    if expected is None:
        return actual is None
    return (
        type(actual) is dict and len(actual) == len(expected)
        and all(type(key) is str for key in actual)
        and all(key in actual and type(actual[key]) is type(value) and actual[key] == value
                for key, value in expected.items())
    )


def _r_state_valid(expected):
    actual = tuple(getattr(np.r_, name) for name in ("axis", "ndmin", "trans1d", "matrix"))
    return all(type(left) is type(right) and left == right for left, right in zip(actual, expected))


def _select_integer_windows(stim_data, sample_picks, width):
    values = stim_data.reshape(stim_data.shape[0], sample_picks.size, width)
    # Boolean argmax is the first nonzero offset; an all-zero window gives
    # offset zero, retaining the first sample's sign. Use ndarray operations
    # so no new public NumPy dispatcher callback is introduced.
    offsets = (values != 0.0).argmax(axis=-1)
    selected = stim_data[:, sample_picks]
    for stim_num, stim in enumerate(stim_data):
        selected[stim_num] = stim[sample_picks + offsets[stim_num]]
    return selected


def _stim_windows_exact(stim_data, up, down, *, original):
    if not _supported_runtime() or not _numpy_dependencies_valid():
        return original(stim_data, up, down)
    # Keep the characterized helper's entire prefix and call order. Existing
    # NumPy dispatchers, conversions, allocations and window setup still run.
    stim_data = np.atleast_2d(stim_data)
    n_stim_channels, n_samples = stim_data.shape
    ratio = float(up) / down
    resampled_n_samples = int(round(n_samples * ratio))
    stim_resampled = np.zeros((n_stim_channels, resampled_n_samples))
    sample_picks = np.minimum(
        (np.arange(resampled_n_samples) / ratio).astype(int), n_samples - 1,
    )
    stop_picks = np.r_[sample_picks[1:], n_samples]
    windows = zip(sample_picks, stop_picks)
    try:
        width = None
        if _numpy_dependencies_valid() and type(ratio) in (float, np.float64):
            for supported_ratio, supported_width in ((.5, 2), (.25, 4), (.125, 8), (.0625, 16)):
                if ratio == supported_ratio:
                    width = supported_width
                    break
        if (
            width is not None
            and type(stim_data) is np.ndarray
            and stim_data.dtype == np.dtype(np.float64)
            and stim_data.flags.c_contiguous
            and n_samples > 0 and n_samples % width == 0
            and type(stim_resampled) is np.ndarray
            and stim_resampled.dtype == np.dtype(np.float64)
            and stim_resampled.shape == (n_stim_channels, n_samples // width)
            and stim_resampled.flags.writeable
            and type(sample_picks) is np.ndarray and type(stop_picks) is np.ndarray
            and sample_picks.dtype.kind == stop_picks.dtype.kind == "i"
            and sample_picks.dtype.itemsize == stop_picks.dtype.itemsize == 8
            and sample_picks.shape == stop_picks.shape == (n_samples // width,)
            and sample_picks[0] == 0 and sample_picks[-1] == n_samples - width
            and stop_picks[-1] == n_samples
            and (sample_picks[1:] != sample_picks[:-1] + width).nonzero()[0].size == 0
            and (stop_picks[:-1] != sample_picks[1:]).nonzero()[0].size == 0
            and (~np.isfinite(stim_data)).nonzero()[0].size == 0
        ):
            # Complete every optional mask/index/value allocation before the
            # first output write. Failure resumes the original loop below.
            selected = _select_integer_windows(stim_data, sample_picks, width)
            stim_resampled[...] = selected
            return stim_resampled
    except MemoryError:
        # Retain the existing prefix arrays when optional masks cannot allocate.
        pass
    for window_i, window in enumerate(windows):
        for stim_num, stim in enumerate(stim_data):
            nonzero = stim[window[0]:window[1]].nonzero()[0]
            if len(nonzero) > 0:
                val = stim[window[0] + nonzero[0]]
            else:
                val = stim[window[0]]
            stim_resampled[stim_num, window_i] = val
    return stim_resampled


class _Adapter:
    def __init__(self):
        if not _supported_runtime() or not _numpy_dependencies_valid():
            raise ValueError("Uncharacterized stim-resample runtime")
        wrapper = mne.io.BaseRaw.resample
        body = wrapper.__wrapped__
        helper = body.__globals__["_resample_stim_channels"]
        self.functions = {
            "wrapper": wrapper, "body": body, "helper": helper,
            "atleast_2d": np.atleast_2d._implementation, "r_getitem": type(np.r_).__getitem__,
        }
        for name, function in self.functions.items():
            if not isinstance(function, FunctionType) or _fingerprint(function) != _FINGERPRINTS[name]:
                raise ValueError("Uncharacterized stim-resample implementation")
            expected = _KWDEFAULTS if name in {"wrapper", "body"} else None
            if function.__defaults__ is not None or not _kwdefaults_valid(function, expected):
                raise ValueError("Uncharacterized stim-resample defaults")
        if (wrapper.__globals__.get("_function_") is not body
                or wrapper.__globals__.get("_use_log_level_") is not mne.utils.use_log_level
                or helper.__globals__.get("np") is not np):
            raise ValueError("Uncharacterized stim-resample forwarding")
        function_names = {
            function: _referenced_names(function.__code__)
            for function in self.functions.values()
        }
        for function in self.functions.values():
            if function.__globals__.get("__builtins__", _ABSENT) is not function.__builtins__:
                # FunctionType would otherwise bind a replacement mapping even
                # though the native function retains its original builtins.
                raise ValueError("Uncharacterized builtin binding")
            if any(
                name in function.__builtins__ and name in function.__globals__
                and function.__globals__[name] is not function.__builtins__[name]
                for name in function_names[function]
            ):
                raise ValueError("Uncharacterized shadowed builtin")
        self.builtin_bindings = [
            (function, function.__globals__["__builtins__"], function.__builtins__)
            for function in self.functions.values()
        ]
        self.dependencies = [
            (function, function.__code__, function.__defaults__,
             None if function.__kwdefaults__ is None else dict(function.__kwdefaults__),
             {name: function.__globals__.get(name, _ABSENT) for name in function_names[function]},
             {name: function.__builtins__[name] for name in function_names[function]
              if name in function.__builtins__}, _closure_values(function))
            for function in self.functions.values()
        ]
        self.module_dependencies = []
        for function in self.functions.values():
            for name in ("np", "_nx"):
                module = function.__globals__.get(name)
                if module is None:
                    continue
                for operation in _NUMPY_NAMES:
                    if operation in function_names[function] and hasattr(module, operation):
                        observed = getattr(module, operation)
                        if observed is not _NUMPY_OPERATIONS[operation]:
                            raise ValueError("Uncharacterized NumPy dependency")
                        self.module_dependencies.append((module, operation, observed))
        self.r_state = (0, 1, -1, False)
        if not _r_state_valid(self.r_state):
            raise ValueError("Uncharacterized NumPy index-construction state")

        def stim_helper(data, up, down):
            return _stim_windows_exact(data, up, down, original=helper)

        copied_body = _clone(body, _resample_stim_channels=stim_helper)
        self.resample = _clone(wrapper, _function_=copied_body)

    def valid_for(self, raw) -> bool:
        try:
            if (not _supported_runtime() or not _numpy_dependencies_valid()
                    or not isinstance(raw, mne.io.BaseRaw)
                    or getattr(raw.resample, "__func__", None) is not self.functions["wrapper"]
                    or getattr(raw.resample, "__self__", None) is not raw
                    or mne.io.BaseRaw.resample is not self.functions["wrapper"]
                    or not _r_state_valid(self.r_state)):
                return False
            for function, code, defaults, kwdefaults, namespace, builtins, closure in self.dependencies:
                if (function.__code__ is not code or function.__defaults__ is not defaults
                        or not _kwdefaults_valid(function, kwdefaults)
                        or any(function.__globals__.get(name, _ABSENT) is not value for name, value in namespace.items())
                        or any(function.__builtins__.get(name) is not value for name, value in builtins.items())
                        or any(left is not right for left, right in zip(_closure_values(function), closure))):
                    return False
            if any(
                function.__globals__.get("__builtins__", _ABSENT) is not binding
                or function.__builtins__ is not actual
                for function, binding, actual in self.builtin_bindings
            ):
                return False
            if any(getattr(module, name, None) is not value for module, name, value in self.module_dependencies):
                return False
            return True
        except (AttributeError, KeyError, MemoryError, TypeError, ValueError):
            return False


@lru_cache(maxsize=1)
def _adapter():
    try:
        return _Adapter()
    except (AttributeError, KeyError, MemoryError, TypeError, ValueError):
        return None


def resample_raw(raw, sfreq, *, use_exact_stim: bool = True, **kwargs):
    """Forward every public resampling argument with unchanged MNE semantics."""
    adapter = _adapter() if use_exact_stim else None
    if adapter is not None and adapter.valid_for(raw):
        return adapter.resample(raw, sfreq, **kwargs)
    return raw.resample(sfreq, **kwargs)

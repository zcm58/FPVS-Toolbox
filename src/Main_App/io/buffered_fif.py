"""Use larger file buffers without changing the characterized MNE FIF writer.

Isolated copies substitute only ``open(..., buffering=...)`` in the existing
save chain. MNE globals, FIF block sizes, split handling and numerical methods
are unchanged. Unknown implementations use the public Raw.save method.
"""

from __future__ import annotations

import builtins
from contextlib import contextmanager
from functools import update_wrapper
import hashlib
import importlib
import sys
from threading import Lock
from types import BuiltinFunctionType, CodeType, FunctionType

import mne

_BUFFER_BYTES = 1_048_576
_OPEN = builtins.open
_MISSING = object()
_LOCK = Lock()
_ADAPTER = None
_FINGERPRINTS = {
    "save_wrapper": "ba3c82f93dd083660c2866601d31e90fc05f8fa040944aafa0e7a83fa408be51",
    "save_body": "aa2f5a52d4569d6e86cc84b4f6b244d739de36e401c9a366c3e425f17f23fb26",
    "write_raw": "3f3f7d868a77bae196c6aac5cbb88c6705e22b83c7c27bfe6b42117bc211015e",
    "start_end_wrapper": "e89cb9c602722c8a19c6e4fc3f93e0e8db73eabdefb374fed67600a4a06b6d47",
    "start_end_body": "69db7e2b11bc614f40c941bc5fb89f87a8006c8363241de476ba43f35fb56d87",
    "start_file": "2cc05e747d79e6f3de7e41b0183c074e520f34bd37b0f216ac2be91a554eb042",
}
_SAVE_DEFAULTS = (None, 0, None, None, False, False, "single", False, "2GB", "neuromag", None)
_DEFAULTS = {
    "save_wrapper": _SAVE_DEFAULTS, "save_body": _SAVE_DEFAULTS,
    "write_raw": None, "start_end_wrapper": None,
    "start_end_body": (None,), "start_file": (None,),
}


def _supported_runtime():
    return (sys.implementation.name == "cpython"
            and sys.version_info[:2] == (3, 13) and mne.__version__ == "1.9.0")


def _code_payload(code):
    def constant(value):
        if isinstance(value, CodeType):
            return ("code", _code_payload(value))
        if type(value) is tuple:
            return ("tuple", tuple(constant(item) for item in value))
        if value is None or type(value) in (str, bytes, int, float, complex, bool):
            return (type(value).__name__, value)
        raise TypeError("Unsupported FIF writer implementation constant")
    return (code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
            code.co_nlocals, code.co_stacksize, code.co_flags, code.co_code,
            tuple(constant(value) for value in code.co_consts), code.co_names,
            code.co_varnames, code.co_freevars, code.co_cellvars, code.co_exceptiontable)


def _fingerprint(function):
    return hashlib.sha256(repr(_code_payload(function.__code__)).encode()).hexdigest()


def _global_names(code):
    names = set(code.co_names)
    for value in code.co_consts:
        if isinstance(value, CodeType):
            names.update(_global_names(value))
    return names


def _clone(function, **overrides):
    cloned = FunctionType(function.__code__, {**function.__globals__, **overrides},
                          function.__name__, function.__defaults__, function.__closure__)
    cloned.__kwdefaults__ = dict(function.__kwdefaults__ or {})
    update_wrapper(cloned, function)
    return cloned


def _buffered_open(path, mode="r", *args, **kwargs):
    if mode == "wb" and not args and "buffering" not in kwargs:
        try:
            return _OPEN(path, mode, buffering=_BUFFER_BYTES, **kwargs)
        except MemoryError:
            # No header/data has been written; keep the original small-buffer
            # route if the additional bounded allocation is unavailable.
            return _OPEN(path, mode, **kwargs)
    return _OPEN(path, mode, *args, **kwargs)


def _functions():
    raw_base = importlib.import_module("mne.io.base")
    fif_write = importlib.import_module("mne._fiff.write")
    return {
        "save_wrapper": raw_base.BaseRaw.save,
        "save_body": raw_base.BaseRaw.save.__wrapped__,
        "write_raw": raw_base._write_raw,
        "start_end_wrapper": fif_write.start_and_end_file,
        "start_end_body": fif_write.start_and_end_file.__wrapped__,
        "start_file": fif_write.start_file,
    }


class _BufferedSave:
    def __init__(self):
        if (not _supported_runtime() or builtins.open is not _OPEN
                or not isinstance(_OPEN, BuiltinFunctionType) or _OPEN.__name__ != "open"):
            raise ValueError("Uncharacterized FIF writer runtime")
        functions = _functions()
        for name, function in functions.items():
            if (not isinstance(function, FunctionType)
                    or _fingerprint(function) != _FINGERPRINTS[name]
                    or function.__defaults__ != _DEFAULTS[name]
                    or function.__kwdefaults__ not in (None, {})
                    or function.__globals__.get("__builtins__") is not function.__builtins__):
                raise ValueError("Uncharacterized FIF writer implementation")
        wrapper, body = functions["save_wrapper"], functions["save_body"]
        start_end, generator = functions["start_end_wrapper"], functions["start_end_body"]
        if (wrapper.__globals__.get("_function_") is not body
                or wrapper.__globals__.get("_use_log_level_") is not mne.utils.use_log_level
                or body.__globals__.get("_write_raw") is not functions["write_raw"]
                or functions["write_raw"].__globals__.get("start_and_end_file") is not start_end
                or len(start_end.__closure__ or ()) != 1
                or start_end.__closure__[0].cell_contents is not generator
                or generator.__globals__.get("start_file") is not functions["start_file"]
                or "open" in functions["start_file"].__globals__
                or functions["start_file"].__globals__.get("__builtins__") is not builtins.__dict__):
            raise ValueError("Uncharacterized FIF writer forwarding")
        self.functions = functions
        self.dependencies = [
            (function, function.__code__, function.__defaults__, dict(function.__kwdefaults__ or {}),
             {name: function.__globals__.get(name, _MISSING)
              for name in (*_global_names(function.__code__), "__builtins__")},
             tuple(cell.cell_contents for cell in (function.__closure__ or ())),
             function.__builtins__)
            for function in functions.values()
        ]
        start = _clone(functions["start_file"], open=_buffered_open)
        start_end_clone = contextmanager(_clone(generator, start_file=start))
        writer = _clone(functions["write_raw"], start_and_end_file=start_end_clone)
        save_body = _clone(body, _write_raw=writer)
        self.save = _clone(wrapper, _function_=save_body)

    def valid_for(self, raw):
        try:
            if (not _supported_runtime() or builtins.open is not _OPEN
                    or not isinstance(raw, mne.io.BaseRaw)
                    or getattr(raw.save, "__func__", None) is not self.functions["save_wrapper"]
                    or getattr(raw.save, "__self__", None) is not raw):
                return False
            current = _functions()
            if any(current[name] is not function for name, function in self.functions.items()):
                return False
            for function, code, defaults, kwdefaults, namespace, closure, builtins_binding in self.dependencies:
                if (function.__code__ is not code or function.__defaults__ != defaults
                        or dict(function.__kwdefaults__ or {}) != kwdefaults
                        or function.__builtins__ is not builtins_binding
                        or function.__globals__.get("__builtins__") is not builtins_binding
                        or any(function.__globals__.get(name, _MISSING) is not value for name, value in namespace.items())
                        or len(function.__closure__ or ()) != len(closure)
                        or any(cell.cell_contents is not value
                               for cell, value in zip(function.__closure__ or (), closure))):
                    return False
            return True
        except (AttributeError, ImportError, IndexError, KeyError, MemoryError, TypeError, ValueError):
            return False


def save_raw_fif(raw, filename, **kwargs):
    """Save through the same writer, with a bounded 1 MiB ordinary-file buffer."""
    global _ADAPTER
    try:
        with _LOCK:
            if _ADAPTER is None:
                _ADAPTER = _BufferedSave()
            adapter = _ADAPTER
        supported = adapter.valid_for(raw)
    except (AttributeError, ImportError, IndexError, KeyError, MemoryError, TypeError, ValueError):
        supported = False
    if supported:
        return adapter.save(raw, filename, **kwargs)
    return raw.save(filename, **kwargs)

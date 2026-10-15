"""Exact packed-BDF decoding during characterized, owned native reads.

Isolated function copies temporarily bind the native RawEDF instance while its
unchanged constructor preloads. No MNE global or class is patched; the binding
is removed before returning. A scoped lazy read likewise restores the owned Raw
before it escapes. Unsupported inputs use the native reader directly.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from functools import partial
import importlib
import io
import math
from pathlib import Path
import sys
from threading import Lock
from types import BuiltinFunctionType, FunctionType, MethodType

import mne
import numpy as np

from Main_App.io.buffered_fif import _clone, _fingerprint, _global_names

_MISSING = object()
_LOCK = Lock()
_ADAPTER = None
_MIN_PACKED_SAMPLES = 1_048_576
_FINGERPRINTS = {
    "public": "6221e14a6345e8c4dacae33beb0a815ccc4e07f5d725cd9414789de68a9211a2",
    "ctor_wrapper": "5ec47242db7d1cef993b6c24d8b44f791ea40acaeedce17223c42c9e5b9df9fb",
    "ctor_body": "49824b1ee20b8762453355cb5a07a48b096d807f67d77b7bd33be6dc44377e40",
    "segment_wrapper": "92c3f5979c76dbc57f093f7d429f26c5f8332c114ac35261319fd5b8e130f1cc",
    "segment_body": "c558c9e33326e9d7a129170e09b854c0a2f1a258bdb4d0443d010b0d7c0bdabd",
    "class_reader": "17e38d6f4e004a9ee8995f1a9b1de39ccdd8f9fa5e11eb740e97a6f6e5afc6df",
    "file_reader": "5e82c73527b840cc81934a73e405cee7f93753bac1e6c5772fb00c2bee0d55df",
    "channel_reader": "e19a073e7037f00c1f1d27261d32a39c0477edb19ff5744f00224bbb7ec677b3",
    "protector_ctor": "805750b77e8a3b523d7e643637ee8b01aa6974feb9a09a61613e284bc3d4855a",
    "protector_reader": "92d6a5b01958f97fb2c5d603bc41dd42c831b32dba48f9e2c8e9661e7c1291e3",
    "protector_filenames": "3feece5957784ce5e52049ee5dd8505aed8282f57554ea5f10cfae639ed2c4de",
    "header": "97069005dc91b262dd37dc1c128f638a981e67c5a62a1a1f7a502190337f8337",
    "edf_header": "48cac05d6931fd056df4662b5b7d4572f05395fe168ba4ad2be2b6123c650ccd",
    "get_info": "5424baaab643302956a15473308a6ade320207d3a76374d5a6a293da504f58f0",
    "prefilter": "78e460ad189de658730e44aaabc52013d1d4b53eae7499b26d4d5f877eb86ea8",
    "parse_prefilter": "2e21db53debc47f5d1875e5fa36940f43281ae81e457946be60cf1f2817304db",
    "block_limits": "fa47290bcedbe1e5dfda9a931fecdd356111b6af1765b4b6f5b8be4431965541",
    "multiply_calibration": "e9e4fb0b7f584351aaaee0a940b858f0652b74e6c0b4fe4fd5af58cb3686497c",
    "base_ctor_wrapper": "f9f8909aa9dd4049ecfdf8c420042f8a9e4a2fb2b40fc7b18c36d127d05d2282",
    "base_ctor_body": "4db5f5819c6a894bc1a97374b2c9781882e101b1479ede6e14f215c0cbd6a6e3",
    "base_preload": "b5f02e1643d84220384f943ccf2c87750ad0c59a10f69e725b7cb948cc3cd886",
    "check_stim": "9e3b01d1bbbddd3fe4266a323b920703dde2c29940cdc6e29344c78f7093af2d",
    "prefilter_float": "94060a51c0db26a1e56b8bae6403db93b9d4c332e01a28da41c30f543ba080db",
    "get_data_wrapper": "164e92745ff2e908beabeda9155225a9329dd15c4fd6818570a47cfdf7af958b",
    "get_data_body": "2895f07032a816327ad8df4c78440b23dc9584bf3f5fcfadc72f4efea905d402",
    "getitem": "40e568d780fa5ad53c3c8198e1ac12641183fa99cd79a309e81e9c7adb42756b",
    "getitem_entry": "213bddd1dad22783e941104b66ad8d1c3fc014609f3410469165cbba93c92de1",
    "parse_params": "2f28723f539d742060be0daea5814d546fccd5949225c21fd0ee3da3761fea03",
    "handle_times": "cf96fce27e0dce4001595fc4fe5f551c376fa43026864caef08202a26af3fa55",
    "find_events_wrapper": "78ecc1e149be984142083214d07678c184c65018edcf4bc893de419b111fe0e8",
    "find_events_body": "d2296a426e8f1aefe9f5fb6ccf501507c55f08428d9c58892b43117aa2952339",
}
_CTOR_DEFAULTS = (None, None, "auto", (), False, False, None, None, "utf8", False)
_DEFAULTS = {
    **dict.fromkeys(_FINGERPRINTS),
    "public": (None, None, "auto", (), False, None, False, None, "utf8", False),
    "ctor_wrapper": _CTOR_DEFAULTS, "ctor_body": _CTOR_DEFAULTS,
    "segment_wrapper": (0, None, None, None), "segment_body": (0, None, None, None),
    "channel_reader": (None,), "header": (None, False), "edf_header": (None, False),
    "get_info": (None, False),
    "base_ctor_wrapper": (False, (0,), None, None, (None,), "double", np.float64, 1.0, None),
    "base_ctor_body": (False, (0,), None, None, (None,), "double", np.float64, 1.0, None),
    "check_stim": (("EDF Annotations", "BDF Annotations"),),
    "get_data_wrapper": (None, 0, None, None, False, None),
    "get_data_body": (None, 0, None, None, False, None),
    "getitem": (True,),
    "find_events_wrapper": (None, "onset", "increasing", 0, 2, None, False, "and", False, None),
    "find_events_body": (None, "onset", "increasing", 0, 2, None, False, "and", False, None),
}
_VERBOSE_FUNCTIONS = {"public", "ctor_wrapper", "ctor_body", "segment_wrapper", "segment_body",
                      "base_ctor_wrapper", "base_ctor_body"}
_NATIVE_NUMPY = {name: getattr(np, name) for name in
                 ("fromfile", "empty", "right_shift", "negative", "uint8", "int32")}


def _supported_runtime():
    return (sys.implementation.name == "cpython" and sys.version_info[:2] == (3, 13)
            and sys.byteorder == "little" and mne.__version__ == "1.9.0"
            and np.__version__ == "2.3.1")


def _native_numpy_decoder():
    core = importlib.import_module("numpy._core.multiarray")
    umath = importlib.import_module("numpy._core.umath")
    return (np.fromfile is core.fromfile and isinstance(np.fromfile, BuiltinFunctionType)
            and np.fromfile.__name__ == "fromfile"
            and np.empty is core.empty and isinstance(np.empty, BuiltinFunctionType)
            and np.empty.__name__ == "empty"
            and np.right_shift is umath.right_shift and isinstance(np.right_shift, np.ufunc)
            and (np.right_shift.__name__, np.right_shift.nin, np.right_shift.nout) == ("right_shift", 2, 1)
            and np.negative is umath.negative and isinstance(np.negative, np.ufunc)
            and (np.negative.__name__, np.negative.nin, np.negative.nout) == ("negative", 1, 1)
            and np.uint8 is core.dtype("u1").type and np.int32 is core.dtype("<i4").type
            and np.float64 is core.dtype("<f8").type)


def _functions(edf, base):
    return {
        "public": edf.read_raw_bdf, "ctor_wrapper": edf.RawEDF.__init__,
        "ctor_body": edf.RawEDF.__init__.__wrapped__,
        "segment_wrapper": base.BaseRaw._read_segment,
        "segment_body": base.BaseRaw._read_segment.__wrapped__,
        "class_reader": edf.RawEDF._read_segment_file, "file_reader": edf._read_segment_file,
        "channel_reader": edf._read_ch, "protector_ctor": base._ReadSegmentFileProtector.__init__,
        "protector_reader": base._ReadSegmentFileProtector._read_segment_file,
        "protector_filenames": base._ReadSegmentFileProtector.filenames.fget,
        "header": edf._read_header, "edf_header": edf._read_edf_header, "get_info": edf._get_info,
        "prefilter": edf._set_prefilter, "parse_prefilter": edf._parse_prefilter_string,
        "block_limits": edf._blk_read_lims, "multiply_calibration": edf._mult_cal_one,
        "base_ctor_wrapper": base.BaseRaw.__init__, "base_ctor_body": base.BaseRaw.__init__.__wrapped__,
        "base_preload": base.BaseRaw._preload_data, "check_stim": edf._check_stim_channel,
        "prefilter_float": edf._prefilter_float,
        "get_data_wrapper": base.BaseRaw.get_data, "get_data_body": base.BaseRaw.get_data.__wrapped__,
        "getitem": base.BaseRaw._getitem, "parse_params": base.BaseRaw._parse_get_set_params,
        "getitem_entry": base.BaseRaw.__getitem__,
        "handle_times": base.BaseRaw._handle_tmin_tmax,
        "find_events_wrapper": mne.find_events, "find_events_body": mne.find_events.__wrapped__,
    }


def _warning_free_header(path, *, stim_channel, include):
    """Validate a bounded ordinary header without reading signal samples."""
    try:
        path = Path(path)
        if path.suffix.lower() != ".bdf":
            return False
        before = path.stat()
        with path.open("rb") as stream:
            fixed = stream.read(256)
            if len(fixed) != 256 or fixed[:8] != b"\xffBIOSEMI":
                return False
            channels, records = int(fixed[252:256]), int(fixed[236:244])
            header_bytes, duration = int(fixed[184:192]), float(fixed[244:252])
            if not (0 < channels <= 128 and records > 0 and math.isfinite(duration) and duration > 0
                    and header_bytes == (channels + 1) * 256):
                return False
            if (len(fixed[8:88].decode("latin1").rstrip().split(" ")) > 1
                    or len(fixed[88:168].decode("latin1").rstrip().split(" ")) == 5):
                return False
            datetime.strptime(fixed[168:176].decode("ascii"), "%d.%m.%y")
            datetime.strptime(fixed[176:184].decode("ascii"), "%H.%M.%S")
            variable = stream.read(channels * 256)
            if len(variable) != channels * 256:
                return False
        offset = 0

        def take(width):
            nonlocal offset
            values = [variable[offset + i * width:offset + (i + 1) * width]
                      .decode("latin1").strip() for i in range(channels)]
            offset += width * channels
            return values

        labels = take(16)
        if (any(not label or "annotations" in label.casefold() for label in labels)
                or len(set(labels)) != channels or stim_channel not in labels):
            return False
        if include is not None and (stim_channel not in include
                or [label for label in labels if label in include] != include):
            return False
        take(80)
        units = take(8)
        minimum, maximum, digital_minimum, digital_maximum = [list(map(float, take(8))) for _ in range(4)]
        for low, high, dlow, dhigh, unit in zip(minimum, maximum, digital_minimum, digital_maximum, units):
            if any(not math.isfinite(v) for v in (low, high, dlow, dhigh)):
                return False
            physical, digital = high - low, dhigh - dlow
            if not (math.isfinite(physical) and math.isfinite(digital) and physical != 0 and digital != 0):
                return False
            calibration = physical / digital
            scaled_minimum = dlow * calibration
            offset_value = low - scaled_minimum
            unit_scale = 1e-6 if unit in ("uV", "\u00b5V", "\u03bcV", "\x83\xcaV") else 1e-3 if unit == "mV" else 1.0
            if any(not math.isfinite(v) for v in (calibration, scaled_minimum, offset_value,
                                                 calibration * unit_scale, offset_value * unit_scale)):
                return False
        filters = take(80)
        if any(filters) and (stim_channel.casefold() != "status"
                or any(value != ("No filtering" if label == stim_channel else "HP: DC; LP: 417 Hz")
                       for label, value in zip(labels, filters))):
            return False
        samples = list(map(int, take(8)))
        if min(samples) <= 0 or len(set(samples)) != 1 or not math.isfinite(max(samples) / duration):
            return False
        expected = header_bytes + records * sum(samples) * 3
        after = path.stat()
        return (before.st_size == expected
                and (before.st_size, before.st_mtime_ns, before.st_ctime_ns, before.st_ino)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns, after.st_ino))
    except (OSError, OverflowError, UnicodeError, ValueError, ZeroDivisionError):
        return False


class _ProtectorRead:
    def __init__(self, protector, reader):
        self.protector, self.reader = protector, reader

    def __call__(self, *args, **kwargs):
        try:
            return self.reader(self.protector, *args, **kwargs)
        finally:
            del self.protector._read_segment_file


class _PackedPreload:
    def __init__(self):
        if not _supported_runtime() or not _native_numpy_decoder():
            raise ValueError("Uncharacterized BDF preload runtime")
        self.edf, self.base = importlib.import_module("mne.io.edf.edf"), importlib.import_module("mne.io.base")
        self.raw_class, self.protector_class = self.edf.RawEDF, self.base._ReadSegmentFileProtector
        functions = _functions(self.edf, self.base)
        for name, function in functions.items():
            kwdefaults = {"verbose": None} if name in _VERBOSE_FUNCTIONS else None
            if name in ("get_data_wrapper", "get_data_body"):
                kwdefaults = {"tmin": None, "tmax": None, "verbose": None}
            if (not isinstance(function, FunctionType) or _fingerprint(function) != _FINGERPRINTS[name]
                    or function.__defaults__ != _DEFAULTS[name] or function.__kwdefaults__ != kwdefaults
                    or function.__globals__.get("__builtins__") is not function.__builtins__):
                raise ValueError("Uncharacterized BDF preload implementation")
        if (mne.io.read_raw_bdf is not functions["public"] or self.raw_class.__new__ is not object.__new__
                or functions["ctor_wrapper"].__globals__.get("_function_") is not functions["ctor_body"]
                or len(functions["ctor_body"].__closure__ or ()) != 1
                or functions["ctor_body"].__closure__[0].cell_contents is not self.raw_class
                or functions["base_ctor_wrapper"].__globals__.get("_function_") is not functions["base_ctor_body"]
                or functions["segment_wrapper"].__globals__.get("_function_") is not functions["segment_body"]
                or functions["get_data_wrapper"].__globals__.get("_function_") is not functions["get_data_body"]
                or functions["find_events_wrapper"].__globals__.get("_function_") is not functions["find_events_body"]
                or functions["public"].__globals__.get("RawEDF") is not self.raw_class
                or functions["class_reader"].__globals__.get("_read_segment_file") is not functions["file_reader"]
                or functions["file_reader"].__globals__.get("_read_ch") is not functions["channel_reader"]
                or not isinstance(np.fromfile, BuiltinFunctionType) or np.fromfile.__name__ != "fromfile"
                or any(getattr(np, name) is not value for name, value in _NATIVE_NUMPY.items())):
            raise ValueError("Uncharacterized BDF preload forwarding")
        self.functions = functions
        self.dependencies = []
        for function in functions.values():
            names = _global_names(function.__code__)
            self.dependencies.append((function, function.__code__, function.__defaults__,
                None if function.__kwdefaults__ is None else dict(function.__kwdefaults__),
                {name: function.__globals__.get(name, _MISSING) for name in (*names, "__builtins__")},
                tuple(cell.cell_contents for cell in (function.__closure__ or ())), function.__builtins__,
                {name: function.__builtins__.get(name, _MISSING) for name in names}))
        numpy_names = set().union(*(_global_names(function.__code__) for function in functions.values()))
        self.numpy_bindings = {name: np.__dict__[name] for name in numpy_names if name in np.__dict__}
        file_reader = _clone(functions["file_reader"], _read_ch=self.read_channel)
        self.class_reader = _clone(functions["class_reader"], _read_segment_file=file_reader)
        body = _clone(functions["segment_body"], _ReadSegmentFileProtector=self.protector)
        self.segment = _clone(functions["segment_wrapper"], _function_=body)
        self.public = _clone(functions["public"], RawEDF=self.construct)
        self.empty = np.empty

    def valid(self):
        try:
            current = _functions(self.edf, self.base)
            if (not _supported_runtime() or not _native_numpy_decoder()
                    or mne.io.read_raw_bdf is not self.functions["public"]
                    or self.edf.RawEDF is not self.raw_class or self.raw_class.__new__ is not object.__new__
                    or self.base._ReadSegmentFileProtector is not self.protector_class
                    or any(current[name] is not function for name, function in self.functions.items())
                    or any(np.__dict__.get(name, _MISSING) is not value for name, value in self.numpy_bindings.items())
                    or np.geterr() != {"divide": "warn", "over": "warn", "under": "ignore", "invalid": "warn"}):
                return False
            for function, code, defaults, kwdefaults, namespace, closure, builtins_binding, builtin_names in self.dependencies:
                if (function.__code__ is not code or function.__defaults__ != defaults
                        or function.__kwdefaults__ != kwdefaults or function.__builtins__ is not builtins_binding
                        or any(function.__globals__.get(name, _MISSING) is not value for name, value in namespace.items())
                        or len(function.__closure__ or ()) != len(closure)
                        or any(cell.cell_contents is not value for cell, value in zip(function.__closure__ or (), closure))
                        or any(builtins_binding.get(name, _MISSING) is not value for name, value in builtin_names.items())):
                    return False
            return True
        except (AttributeError, ImportError, IndexError, KeyError, MemoryError, TypeError, ValueError):
            return False

    def construct(self, *args, **kwargs):
        raw = self.raw_class.__new__(self.raw_class)
        raw._read_segment = MethodType(self.segment, raw)
        try:
            self.raw_class.__init__(raw, *args, **kwargs)
        finally:
            del raw._read_segment
        return raw

    def protector(self, raw):
        protector = self.protector_class(raw)
        protector._read_segment_file = _ProtectorRead(protector, self.class_reader)
        return protector

    def read_channel(self, stream, subtype, count, dtype_byte, dtype=None):
        if (subtype != "bdf" or dtype_byte != 3 or type(count) not in (int, np.int64, np.int32)
                or count < _MIN_PACKED_SAMPLES or not isinstance(stream, (io.FileIO, io.BufferedReader))
                or not (dtype is np.uint8 or type(dtype) is str and dtype == "<u1")):
            return self.functions["channel_reader"](stream, subtype, count, dtype_byte, dtype)
        position = stream.tell()
        triples = output = octets = None
        try:
            triples = np.fromfile(stream, dtype=dtype, count=count * dtype_byte).reshape(-1, 3)
            output = self.empty(len(triples), dtype=np.int32)
            octets = output.view(np.uint8).reshape(-1, 4)
            octets[:, :3] = triples
            np.right_shift(octets[:, 2], 7, out=octets[:, 3])
            np.negative(octets[:, 3], out=octets[:, 3])
            return output
        except MemoryError:
            # Release speculative arrays before retrying the original decoder.
            triples = output = octets = None
            stream.seek(position)
            return self.functions["channel_reader"](stream, subtype, count, dtype_byte, dtype)


def _adapter():
    global _ADAPTER
    with _LOCK:
        if _ADAPTER is None:
            _ADAPTER = _PackedPreload()
        return _ADAPTER


class _StatusRead:
    """One owned Status read, retaining all physical bytes and native bodies."""

    def __init__(self, adapter, samples, reader_index, physical_index):
        self.adapter, self.samples = adapter, samples
        self.reader_index, self.physical_index = reader_index, physical_index
        self.width = sum(samples)
        self.low = sum(samples[:physical_index])
        self.high = self.low + samples[physical_index]
        self.empty = adapter.empty
        self.segment = self.class_reader = None
        try:
            file_reader = _clone(adapter.functions["file_reader"], _read_ch=self.read_channel)
            self.class_reader = _clone(adapter.functions["class_reader"], _read_segment_file=file_reader)
            body = _clone(adapter.functions["segment_body"], _ReadSegmentFileProtector=self.protector)
            self.segment = _clone(adapter.functions["segment_wrapper"], _function_=body)
        except BaseException:
            self.segment = self.class_reader = None
            raise

    def protector(self, raw):
        protector = self.adapter.protector_class(raw)
        protector._read_segment_file = _StatusDispatch(protector, self)
        return protector

    def read_channel(self, stream, subtype, count, dtype_byte, dtype=None):
        if (subtype != "bdf" or dtype_byte != 3 or type(count) not in (int, np.int64, np.int32)
                or count < _MIN_PACKED_SAMPLES or count % self.width
                or not isinstance(stream, (io.FileIO, io.BufferedReader))
                or not (dtype is np.uint8 or type(dtype) is str and dtype == "<u1")):
            return self.adapter.functions["channel_reader"](stream, subtype, count, dtype_byte, dtype)
        position = stream.tell()
        triples = output = octets = selected_triples = selected_octets = None
        try:
            triples = np.fromfile(stream, dtype=dtype, count=count * dtype_byte).reshape(-1, 3)
            output = self.empty(len(triples), dtype=np.int32)
            octets = output.view(np.uint8).reshape(-1, 4)
            if len(triples) == count:
                selected_triples = triples.reshape(-1, self.width, 3)[:, self.low:self.high, :]
                selected_octets = octets.reshape(-1, self.width, 4)[:, self.low:self.high, :]
            else:
                # A short read can change the native later record-row width.
                # Populate every received slot so that reshape/errors stay native.
                selected_triples, selected_octets = triples, octets
            selected_octets[..., :3] = selected_triples
            np.right_shift(selected_octets[..., 2], 7, out=selected_octets[..., 3])
            np.negative(selected_octets[..., 3], out=selected_octets[..., 3])
            return output
        except MemoryError:
            triples = output = octets = selected_triples = selected_octets = None
            stream.seek(position)
            return self.adapter.functions["channel_reader"](stream, subtype, count, dtype_byte, dtype)


class _StatusDispatch:
    def __init__(self, protector, reader):
        self.protector, self.reader = protector, reader

    def __call__(self, data, idx, fi, start, stop, cals, mult):
        try:
            extra = self.protector._raw_extras[fi]
            # Native _convert_slice produces this exact one-channel form.
            # Avoid additional NumPy helpers/bindings in selection admission.
            supported = (type(idx) is slice and idx.start == self.reader.reader_index
                and idx.stop == self.reader.reader_index + 1 and idx.step in (None, 1)
                and mult is None and data.shape[0] == 1
                and int(extra["sel"][idx.start]) == self.reader.physical_index
                and tuple(int(value) for value in extra["n_samps"]) == self.reader.samples
                and extra["subtype"] == "bdf" and extra["dtype_byte"] == 3
                and len(extra["tal_idx"]) == 0)
            reader = self.reader.class_reader if supported else self.reader.adapter.functions["class_reader"]
            return reader(self.protector, data, idx, fi, start, stop, cals, mult)
        finally:
            del self.protector._read_segment_file


@contextmanager
def owned_bdf_lazy_read(raw, *, stim_channel=None, status_only=False):
    """Scope one ordinary read on a fresh, exclusively owned native lazy Raw.

    The caller retains its native get_data/find_events call and I/O semaphore.
    This suspended context adds no active callback frame to native warnings;
    it does not provide persistent dispatch or support shared-Raw concurrency.
    """
    supported = False
    scoped = None
    try:
        adapter = _adapter()
        local_methods = ("get_data", "_getitem", "__getitem__", "_parse_get_set_params",
                         "_handle_tmin_tmax", "_read_segment", "_read_segment_file")
        supported = (type(status_only) is bool and adapter.valid()
            and type(raw) is adapter.raw_class and raw.preload is False
            and not any(name in vars(raw) for name in local_methods)
            and len(raw.filenames) == 1 and len(raw._raw_extras) == 1)
        if supported:
            extra = raw._raw_extras[0]
            supported = (extra["subtype"] == "bdf" and len(extra["tal_idx"]) == 0
                and len(extra["n_samps"]) > 0 and min(extra["n_samps"]) > 0
                and len(set(extra["n_samps"])) == 1)
        if supported:
            for method, name in (("get_data", "get_data_wrapper"), ("_getitem", "getitem"),
                    ("__getitem__", "getitem_entry"),
                    ("_parse_get_set_params", "parse_params"), ("_handle_tmin_tmax", "handle_times"),
                    ("_read_segment", "segment_wrapper"), ("_read_segment_file", "class_reader")):
                bound = getattr(raw, method)
                if (getattr(bound, "__func__", None) is not adapter.functions[name]
                        or getattr(bound, "__self__", None) is not raw):
                    supported = False
                    break
        if supported:
            if stim_channel is None:
                stimuli = [channel["ch_name"] for channel in raw.info["chs"] if channel["kind"] == 3]
                stim_channel = stimuli[0] if len(stimuli) == 1 else None
            supported = (type(stim_channel) is str and stim_channel in raw.ch_names
                and _warning_free_header(raw.filenames[0], stim_channel=stim_channel,
                                         include=list(raw.ch_names)))
        if supported and status_only:
            raw_index = raw.ch_names.index(stim_channel)
            reader_index = int(raw._read_picks[0][raw_index])
            physical_index = int(extra["sel"][reader_index])
            supported = (raw._projector is None and raw._comp is None
                         and reader_index in extra["stim_channel_idxs"])
            if supported:
                samples = tuple(int(value) for value in extra["n_samps"])
                scoped = _StatusRead(adapter, samples, reader_index, physical_index)
    except (AttributeError, ImportError, IndexError, KeyError, MemoryError, OSError, TypeError, ValueError):
        supported = False
    if not supported:
        yield False
        return
    raw._read_segment = MethodType(scoped.segment if scoped is not None else adapter.segment, raw)
    try:
        yield True
    finally:
        del raw._read_segment
        if scoped is not None:
            # Break private reader/function cycles before the Raw can escape.
            scoped.segment = scoped.class_reader = None


def select_bdf_preload_reader(filepath, *, preload, stim_channel, include, verbose=False):
    """Return one bound full-reader call; no extra Python frame on native fallback."""
    kwargs = {"preload": preload, "stim_channel": stim_channel, "include": include, "verbose": verbose}
    native = partial(mne.io.read_raw_bdf, filepath, **kwargs)
    if (not (preload is True or type(preload) is str and Path(preload).is_absolute())
            or type(stim_channel) is not str or not stim_channel or verbose is not False
            or include is not None and (type(include) is not list or not include
                or any(type(label) is not str for label in include) or len(set(include)) != len(include))):
        return native
    try:
        adapter = _adapter()
        if not adapter.valid() or not _warning_free_header(filepath, stim_channel=stim_channel, include=include):
            return native
    except (AttributeError, ImportError, IndexError, KeyError, MemoryError, OSError, TypeError, ValueError):
        return native
    # Freeze the exact validated include order while binding the invocation.
    kwargs["include"] = list(include) if include is not None else None
    return partial(adapter.public, filepath, **kwargs)

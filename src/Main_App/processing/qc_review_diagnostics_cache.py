"""Exact, display-only raw diagnostic reuse under the project preflight cache.

Raw loading and source verification remain scanner-owned. Admission binds the
current converted samples as well as the previously verified source bytes;
publication occurs only after the scanner's existing second source check.
No review receipt, annotation, interpolation or exclusion authority is stored.
"""

from collections.abc import Callable, Mapping, Sequence
import ast
from dataclasses import asdict, dataclass
import hashlib
import inspect
import json
import logging
from pathlib import Path
import re
import struct
import sys
from types import CodeType

import mne
import numpy as np
import scipy

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNEL_SET, canonical_biosemi64_head_coordinates,
    read_raw_biosemi64_geometry,
)
from Main_App.processing.preflight_qc_cache import (
    PREFLIGHT_QC_CACHE_METHOD_DIRECTORY, load_preflight_qc_cache, save_preflight_qc_cache,
)
from Main_App.processing.preflight_qc_reuse import decode_evidence, encode_evidence

logger = logging.getLogger(__name__)
RAW_DIAGNOSTICS_CACHE_VERSION = "raw_review_diagnostics_exact_v1"


@dataclass(frozen=True)
class RawDiagnosticsCacheKey:
    project_root: Path
    inputs: dict


def _cancel(callback: Callable[[], bool] | None) -> None:
    if callback and callback():
        raise InterruptedError("Raw diagnostic cache operation cancelled.")


def _sample_digest(data: np.ndarray, should_cancel) -> str:
    digest = hashlib.sha256()
    for row in data:
        for start in range(0, row.size, 131_072):
            _cancel(should_cancel)
            block = np.ascontiguousarray(row[start:start + 131_072])
            digest.update(memoryview(block).cast("B"))
    return digest.hexdigest()


def _code_constant(value):
    if isinstance(value, CodeType):
        return {"code": _code_structure(value)}
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if value is Ellipsis:
        return {"ellipsis": True}
    if isinstance(value, complex):
        return {"complex": [encode_evidence(value.real), encode_evidence(value.imag)]}
    if isinstance(value, tuple):
        return {"tuple": [_code_constant(item) for item in value]}
    if isinstance(value, frozenset):
        return {"frozenset": sorted((_code_constant(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))}
    return encode_evidence(value)


def _code_structure(code: CodeType) -> dict:
    # marshal includes mutable string-intern/reference flags in Python3.13.
    # Explicit public code fields keep the digest stable before/after calls and
    # across spawn. Source paths and debug line locations are not executable.
    return {
        "bytecode": code.co_code.hex(), "constants": [_code_constant(value) for value in code.co_consts],
        "names": list(code.co_names), "variables": list(code.co_varnames),
        "free_variables": list(code.co_freevars), "cell_variables": list(code.co_cellvars),
        "argcount": code.co_argcount, "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount, "locals": code.co_nlocals,
        "stacksize": code.co_stacksize, "flags": code.co_flags,
        "exception_table": getattr(code, "co_exceptiontable", b"").hex(),
    }


def _function_identity(function) -> dict | None:
    function = inspect.unwrap(function)
    if isinstance(function, type):
        function = inspect.unwrap(function.__init__)
    function = getattr(function, "py_func", function)
    code = getattr(function, "__code__", None)
    if not isinstance(code, CodeType):
        return None
    closure = []
    for cell in getattr(function, "__closure__", ()) or ():
        value = cell.cell_contents
        if isinstance(value, type):
            # MNE's normal __init__ uses the compiler's __class__ cell for
            # super(). Bind its class name; mutable arbitrary closures miss.
            closure.append({"class_module": value.__module__, "class_name": value.__qualname__})
        elif value is None or type(value) in (str, int, float, bool):
            closure.append(encode_evidence(value))
        else:
            return None
    return {
        "module": function.__module__, "name": function.__qualname__,
        "code_sha256": hashlib.sha256(json.dumps(_code_structure(code), sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "defaults": encode_evidence(getattr(function, "__defaults__", None)),
        "keyword_defaults": encode_evidence(getattr(function, "__kwdefaults__", None)),
        "closure": closure,
    }


def _implementation_identity() -> dict | None:
    """Admit only the characterized detector and actual loaded helper code."""
    try:
        from Main_App.processing import qc_review_diagnostics as diagnostics

        if not diagnostics._mne_runtime_unchanged():
            return None
        path = Path(diagnostics.__file__)
        if path.stat().st_size > 262_144:
            return None
        source = path.read_bytes()
        statements = ast.parse(source).body
        names = [node.name for node in statements if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        # All report-owned helpers are currently undecorated. A same-name wrapper
        # can alter output while exposing the original __wrapped__ code: miss.
        if any(getattr(diagnostics, name) is not inspect.unwrap(getattr(diagnostics, name)) for name in names):
            return None
        if (diagnostics.canonical_biosemi64_head_coordinates is not canonical_biosemi64_head_coordinates
                or set(diagnostics.BIOSEMI64_CHANNEL_SET) != set(BIOSEMI64_CHANNEL_SET)):
            return None
        functions = {name: _function_identity(getattr(diagnostics, name)) for name in names}
        geometry = _function_identity(diagnostics.canonical_biosemi64_head_coordinates)
        native = {name: _function_identity(function) for _owner, name, function, _code in diagnostics._MNE_DIAGNOSTIC_RUNTIME}
        if geometry is None or any(value is None for value in (*functions.values(), *native.values())):
            return None
        constants = {}
        for statement in statements:
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    if isinstance(target, ast.Name) and target.id not in {"_AMPLITUDE_DETECTOR", "_MNE_DIAGNOSTIC_RUNTIME"}:
                        constants[target.id] = _code_constant(getattr(diagnostics, target.id))
        return {"source_sha256": hashlib.sha256(source).hexdigest(), "functions": functions, "native": native,
                "constants": constants, "geometry_function": geometry, "scalp_channels": sorted(diagnostics.BIOSEMI64_CHANNEL_SET)}
    except (OSError, ImportError, AttributeError, TypeError, ValueError, SyntaxError, RuntimeError, RecursionError, MemoryError):
        return None


def build_raw_diagnostics_cache_key(
    raw, *, project_root: Path | str | None, source_identity: Mapping,
    participant_id: str, recording_id: str, occurrences: Sequence[Mapping],
    ref_channels: Sequence[str] = (), unusable_channels: Sequence[str] = (),
    settings=None, should_cancel: Callable[[], bool] | None = None,
) -> RawDiagnosticsCacheKey | None:
    """Return no key for unknown identities; callers then use the full math."""
    try:
        _cancel(should_cancel)
        from Main_App.processing import prepared_kurtosis_cache
        from Main_App.processing.qc_review_diagnostics import (
            QC_REVIEW_DIAGNOSTICS_VERSION, QCReviewDiagnosticSettings,
        )

        if project_root is None or not Path(project_root).is_absolute():
            return None
        root = Path(project_root).resolve()
        source = Path(source_identity["path"]).resolve()
        before = source.stat()
        sha256 = source_identity.get("sha256")
        if (not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or source_identity.get("size_bytes") != before.st_size):
            return None
        data = getattr(raw, "_data", None)
        if (not getattr(raw, "preload", False) or not isinstance(data, np.ndarray)
                or data.dtype != np.dtype(np.float64) or data.ndim != 2
                or data.shape != (len(raw.ch_names), raw.n_times)):
            return None
        # Reuse the prepared checkpoint owner's read-only native identity seam;
        # this cache never sets numerical thread limits or owns an EEG buffer.
        native = prepared_kurtosis_cache._native_execution_identity()
        if native is None:
            return None
        implementation = _implementation_identity()
        if implementation is None:
            return None
        geometry = read_raw_biosemi64_geometry(raw)
        if not isinstance(geometry, Mapping) or not geometry:
            return None
        config = settings if isinstance(settings, QCReviewDiagnosticSettings) else QCReviewDiagnosticSettings(**dict(settings or {}))
        names = tuple(raw.ch_names)
        scalp = [name for name in names if name in BIOSEMI64_CHANNEL_SET]
        coordinates = canonical_biosemi64_head_coordinates()
        source_file = {
            "resolved_path": str(source), "size": before.st_size,
            "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
            "content_sha256": sha256, "recording_id": recording_id,
        }
        inputs = {
            "file_identity": source_file,
            "settings": {
                "recording_scope": {"participant_id": participant_id, "recording_id": recording_id},
                "diagnostics": asdict(config), "reference_channels": list(ref_channels),
                "unusable_channels": list(unusable_channels),
                "geometry": dict(geometry),
                "positions": {name: coordinates[name] for name in scalp},
                "native_execution_identity": native,
            },
            "method": {
                "name": "condition_aware_preflight_qc", "version": PREFLIGHT_QC_CACHE_METHOD_DIRECTORY,
                "evidence_codec": "typed_float64_v1", "raw_diagnostics_cache_version": RAW_DIAGNOSTICS_CACHE_VERSION,
                "raw_diagnostics_version": QC_REVIEW_DIAGNOSTICS_VERSION,
                "python_version": list(sys.version_info[:3]), "mne_version": mne.__version__,
                "numpy_version": np.__version__, "scipy_version": scipy.__version__,
                "implementation_identity": implementation,
            },
            "event_plan": {
                "occurrences": [dict(occurrence) for occurrence in occurrences],
                "channels": list(names),
                "diagnostic_channels": [name for name in names if name in scalp or name in set(ref_channels)],
                "sfreq": float(raw.info["sfreq"]), "first_samp": int(raw.first_samp),
                "n_times": int(raw.n_times), "samples_dtype": data.dtype.str,
                "samples_shape": list(data.shape), "samples_strides": list(data.strides),
                "converted_samples_sha256": _sample_digest(data, should_cancel),
            },
        }
        after = source.stat()
        if any(getattr(before, name) != getattr(after, name) for name in ("st_size", "st_mtime_ns", "st_ctime_ns")):
            return None
        _cancel(should_cancel)
        # Validate key serialization now. Unknown metadata is an optional miss.
        snapshot = json.loads(json.dumps(inputs, allow_nan=False))
        return RawDiagnosticsCacheKey(root, snapshot)
    except InterruptedError:
        raise
    except (OSError, ImportError, AttributeError, KeyError, TypeError, ValueError, RuntimeError, MemoryError):
        logger.debug("raw_diagnostic_cache_identity_unavailable", exc_info=True)
        return None


def _mapping_order(value):
    if isinstance(value, Mapping):
        return {"keys": list(value), "children": [_mapping_order(item) for item in value.values()]}
    if isinstance(value, (tuple, list)):
        return [_mapping_order(item) for item in value]
    return None


def _restore_mapping_order(value, order):
    if isinstance(value, Mapping):
        if (not isinstance(order, dict) or set(order) != {"keys", "children"}
                or not isinstance(order["keys"], list) or not isinstance(order["children"], list)
                or len(order["keys"]) != len(value) or len(order["children"]) != len(value)
                or set(order["keys"]) != set(value)):
            raise ValueError("Invalid diagnostic mapping order")
        return {key: _restore_mapping_order(value[key], child) for key, child in zip(order["keys"], order["children"])}
    if isinstance(value, (tuple, list)):
        if not isinstance(order, list) or len(order) != len(value):
            raise ValueError("Invalid diagnostic sequence order")
        result = [_restore_mapping_order(item, child) for item, child in zip(value, order)]
        return tuple(result) if isinstance(value, tuple) else result
    if order is not None:
        raise ValueError("Invalid diagnostic scalar order")
    return value


def _valid_report(report) -> bool:
    from Main_App.processing.qc_review_diagnostics import QC_REVIEW_DIAGNOSTICS_VERSION

    if (not isinstance(report, dict) or report.get("version") != QC_REVIEW_DIAGNOSTICS_VERSION
            or report.get("authority") != "review_only" or report.get("mne_version") != mne.__version__
            or report.get("evaluation_scope") != "all_analyzed_occurrences"
            or report.get("signal_stage") != "loaded_raw_before_reference"):
        return False
    core = {key: value for key, value in report.items() if key != "fingerprint"}
    encoded = json.dumps(core, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()
    return report.get("fingerprint") == hashlib.sha256(encoded).hexdigest()


def _runtime_current(key: RawDiagnosticsCacheKey) -> bool:
    from Main_App.processing import prepared_kurtosis_cache

    method = key.inputs["method"]
    native = prepared_kurtosis_cache._native_execution_identity()
    return (
        native is not None
        and json.loads(json.dumps(native, allow_nan=False)) == key.inputs["settings"]["native_execution_identity"]
        and method["version"] == PREFLIGHT_QC_CACHE_METHOD_DIRECTORY
        and method["raw_diagnostics_cache_version"] == RAW_DIAGNOSTICS_CACHE_VERSION
        and method["python_version"] == list(sys.version_info[:3])
        and method["mne_version"] == mne.__version__
        and method["numpy_version"] == np.__version__
        and method["scipy_version"] == scipy.__version__
        and _implementation_identity() == method["implementation_identity"]
    )


def load_raw_diagnostics(key: RawDiagnosticsCacheKey | None, *, should_cancel=None) -> dict | None:
    """Return detached, fingerprint-valid evidence with original mapping order."""
    _cancel(should_cancel)
    if key is None:
        return None
    try:
        cached = load_preflight_qc_cache(key.project_root, namespace="raw_diagnostics", **key.inputs)
        if cached is None:
            return None
        if not _runtime_current(key):
            return None
        report = _restore_mapping_order(decode_evidence(cached["report"]), cached["mapping_order"])
        _cancel(should_cancel)
        return report if _valid_report(report) and _runtime_current(key) else None
    except InterruptedError:
        raise
    except (OSError, AttributeError, KeyError, TypeError, ValueError, RuntimeError, struct.error, RecursionError, MemoryError):
        logger.debug("raw_diagnostic_cache_miss", exc_info=True)
        return None


def save_raw_diagnostics(key: RawDiagnosticsCacheKey | None, report: dict, *, should_cancel=None) -> None:
    """Publish only after the caller verified unchanged source content again."""
    _cancel(should_cancel)
    if key is None:
        return
    try:
        if not _valid_report(report):
            return
        if not _runtime_current(key):
            return
        _cancel(should_cancel)
        save_preflight_qc_cache(key.project_root, namespace="raw_diagnostics", **key.inputs,
                               result={"report": encode_evidence(report), "mapping_order": _mapping_order(report)})
    except InterruptedError:
        raise
    except (OSError, AttributeError, KeyError, TypeError, ValueError, RuntimeError, struct.error, RecursionError, MemoryError):
        logger.debug("raw_diagnostic_cache_write_unavailable", exc_info=True)

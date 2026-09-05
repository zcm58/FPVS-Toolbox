"""Explicit, pickle-free encoding of the MNE state used at the QC boundary."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import date, datetime
from pathlib import Path
import struct

import mne
import numpy as np
from mne._fiff._digitization import DigPoint
from mne.utils._bunch import NamedInt

from Main_App.processing.kurtosis_qc import (
    KurtosisChannelEvidence, KurtosisOccurrenceScope, KurtosisQCEvidence,
    KurtosisReferenceDistribution, KurtosisScoringScope,
)

_RECORDS = {cls.__name__: cls for cls in (
    KurtosisChannelEvidence, KurtosisOccurrenceScope, KurtosisQCEvidence,
    KurtosisReferenceDistribution, KurtosisScoringScope,
)}


def encode_state(value, arrays: dict[str, np.ndarray]):
    """Encode only supported data types; unknown metadata disables caching."""

    if value is None or type(value) in (bool, int, str):
        return ["plain", value]
    if isinstance(value, NamedInt):
        return ["named_int", value._name, int(value)]
    if type(value) is float:
        return ["float64", struct.pack("!d", value).hex()]
    if isinstance(value, np.generic) and not value.dtype.hasobject:
        return ["numpy_scalar", value.dtype.str, value.tobytes().hex()]
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            raise ValueError("Object arrays are not supported by the prepared checkpoint.")
        key = f"array_{len(arrays)}"
        arrays[key] = value
        return ["array", key]
    if isinstance(value, datetime):
        return ["datetime", value.isoformat()]
    if isinstance(value, date):
        return ["date", value.isoformat()]
    if isinstance(value, Path):
        return ["path", str(value)]
    if isinstance(value, mne.Annotations):
        return ["annotations", encode_state({
            "onset": value.onset, "duration": value.duration,
            "description": value.description, "orig_time": value.orig_time,
            "ch_names": [tuple(names) for names in value.ch_names],
        }, arrays)]
    if is_dataclass(value) and type(value).__name__ in _RECORDS and type(value) is _RECORDS[type(value).__name__]:
        return ["record", type(value).__name__, encode_state({field.name: getattr(value, field.name) for field in fields(value)}, arrays)]
    if isinstance(value, dict):
        kind = "dict"
        for cls, name in ((mne.Info, "info"), (mne.Projection, "projection"), (mne.transforms.Transform, "transform"), (DigPoint, "dig_point")):
            if isinstance(value, cls):
                kind = name
                break
        return [kind, [[encode_state(key, arrays), encode_state(item, arrays)] for key, item in value.items()]]
    if isinstance(value, (tuple, list)):
        return ["tuple" if isinstance(value, tuple) else "list", [encode_state(item, arrays) for item in value]]
    raise ValueError(f"Unsupported prepared-checkpoint metadata: {type(value).__name__}.")


def decode_state(node, arrays):
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        raise ValueError("Invalid prepared-checkpoint metadata node.")
    kind = node[0]
    if kind == "plain" and len(node) == 2 and (node[1] is None or type(node[1]) in (bool, int, str)):
        return node[1]
    if kind == "float64" and len(node) == 2:
        return struct.unpack("!d", bytes.fromhex(node[1]))[0]
    if kind == "numpy_scalar" and len(node) == 3:
        dtype = np.dtype(node[1])
        if dtype.hasobject:
            raise ValueError("Object scalars are not supported.")
        return np.frombuffer(bytes.fromhex(node[2]), dtype=dtype, count=1)[0]
    if kind == "named_int" and len(node) == 3:
        return NamedInt(node[1], node[2])
    if kind == "array" and len(node) == 2:
        array = arrays[node[1]]
        if array.dtype.hasobject:
            raise ValueError("Prepared checkpoints cannot load object arrays.")
        return array
    if kind in {"datetime", "date", "path"} and len(node) == 2:
        return {"datetime": datetime.fromisoformat, "date": date.fromisoformat, "path": Path}[kind](node[1])
    if kind in {"tuple", "list"} and len(node) == 2:
        values = [decode_state(item, arrays) for item in node[1]]
        return tuple(values) if kind == "tuple" else values
    if kind == "record" and len(node) == 3 and node[1] in _RECORDS:
        return _RECORDS[node[1]](**decode_state(node[2], arrays))
    if kind == "annotations" and len(node) == 2:
        return mne.Annotations(**decode_state(node[1], arrays))
    if kind in {"dict", "info", "projection", "transform", "dig_point"} and len(node) == 2:
        value = {decode_state(key, arrays): decode_state(item, arrays) for key, item in node[1]}
        if kind == "info":
            return mne.Info(value)
        if kind == "projection":
            return mne.Projection(**value)
        if kind == "transform":
            return mne.transforms.Transform(value["from"], value["to"], value["trans"])
        if kind == "dig_point":
            return DigPoint(value)
        return value
    raise ValueError("Unsupported prepared-checkpoint metadata encoding.")


def raw_state(raw: mne.io.BaseRaw) -> dict:
    if not raw.preload or len(raw._first_samps) != 1:
        raise ValueError("Prepared checkpoints require one loaded recording segment.")
    return {
        "info": raw.info, "first_samp": int(raw.first_samp),
        "annotations": raw.annotations,
        "attributes": {
            key: value for key, value in vars(raw).items()
            if key.startswith("_fpvs_") or key in {"_orig_units", "_cals", "_projector", "_filenames", "orig_format"}
        },
    }


def restore_raw(data: np.ndarray, state: dict) -> mne.io.RawArray:
    if data.dtype != np.dtype(np.float64) or data.ndim != 2:
        raise ValueError("Prepared samples must be a float64 channel-by-sample matrix.")
    raw = mne.io.RawArray(data, state["info"], first_samp=state["first_samp"], copy="info", verbose=False)
    raw._annotations = state["annotations"]
    for key, value in state["attributes"].items():
        if not (key.startswith("_fpvs_") or key in {"_orig_units", "_cals", "_projector", "_filenames", "orig_format"}):
            raise ValueError("Unexpected prepared Raw attribute.")
        setattr(raw, key, value)
    return raw

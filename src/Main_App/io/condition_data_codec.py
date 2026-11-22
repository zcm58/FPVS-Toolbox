"""Pickle-free column encoding for compact numerical and audit tables."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

_MIXED_DTYPES = {
    "object", "string", "boolean", "Int8", "Int16", "Int32", "Int64",
    "UInt8", "UInt16", "UInt32", "UInt64", "Float32", "Float64",
}


def json_text(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _encode_scalar(value):
    if value is pd.NA:
        return ["missing"]
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or isinstance(value, (str, bool, int)):
        return ["value", value]
    if isinstance(value, float):
        # Hexadecimal text also preserves infinities, NaNs, and negative zero.
        return ["float", value.hex()]
    raise ValueError(f"Unsupported condition-table value: {type(value).__name__}.")


def _decode_scalar(text):
    value = json.loads(str(text))
    if not isinstance(value, list) or not value:
        raise ValueError("Invalid condition-table scalar.")
    if value == ["missing"]:
        return pd.NA
    if len(value) == 2 and value[0] == "value" and (
        value[1] is None or isinstance(value[1], (str, bool, int))
    ):
        return value[1]
    if len(value) == 2 and value[0] == "float" and isinstance(value[1], str):
        return float.fromhex(value[1])
    raise ValueError("Invalid condition-table scalar encoding.")


def _encode_text_and_object(series: pd.Series, codes: np.ndarray) -> list[str]:
    dictionary, positions = [], {}
    for index, value in enumerate(series):
        if type(value) is str:
            # Repeated audit labels only need a scalar record on first use.
            key = ("value", value, str)
            scalar = None
        else:
            scalar = _encode_scalar(value)
            key = (*scalar, type(scalar[-1]))
        position = positions.get(key)
        if position is None:
            position = len(dictionary)
            positions[key] = position
            dictionary.append(json_text(["value", value] if scalar is None else scalar))
        codes[index] = position
    return dictionary


def encode_column(series: pd.Series) -> tuple[np.ndarray, dict]:
    """Keep numerical arrays native; encode mixed audit cells explicitly."""

    dtype = series.dtype
    if isinstance(dtype, np.dtype) and dtype.kind in "biuf":
        values = series.to_numpy(copy=True)
        return values, {"encoding": "native", "dtype": dtype.str}
    dtype_name = str(dtype)
    if dtype_name not in _MIXED_DTYPES:
        raise ValueError(f"Unsupported condition-table column dtype: {dtype}.")
    codes = np.empty(len(series), dtype=np.int32)
    if dtype_name in {"object", "string"}:
        dictionary = _encode_text_and_object(series, codes)
    else:
        dictionary, positions = [], {}
        for index, value in enumerate(series):
            scalar = _encode_scalar(value)
            key = (*scalar, type(scalar[-1]))
            if key not in positions:
                positions[key] = len(dictionary)
                dictionary.append(json_text(scalar))
            codes[index] = positions[key]
    return codes, {"encoding": "dictionary_json", "dtype": dtype_name,
                   "dictionary": np.asarray(dictionary, dtype=np.str_)}


def validate_column_encoding(dtype: np.dtype, specification: dict) -> None:
    """Validate metadata without allocating pandas objects per column."""

    if not isinstance(specification, dict) or set(specification) != {"encoding", "dtype"}:
        raise ValueError("Invalid condition-table column specification.")
    target_dtype = specification["dtype"]
    if not isinstance(target_dtype, str):
        raise ValueError("Invalid condition-table dtype.")
    if specification["encoding"] == "native":
        expected = np.dtype(target_dtype)
        if expected.kind not in "biuf" or dtype != expected:
            raise ValueError("Invalid native condition-table column dtype.")
    elif specification["encoding"] == "dictionary_json":
        if target_dtype not in _MIXED_DTYPES or dtype != np.dtype(np.int32):
            raise ValueError("Invalid mixed condition-table column dtype.")
    else:
        raise ValueError("Unsupported condition-table column encoding.")


def decode_column(
    values: np.ndarray, specification: dict, rows: int, dictionary: np.ndarray | None = None,
    *, validate_only: bool = False,
) -> np.ndarray | pd.Series | None:
    if values.ndim != 1 or len(values) != rows:
        raise ValueError("Invalid condition-table column dimensions.")
    validate_column_encoding(values.dtype, specification)
    if specification["encoding"] == "native":
        return None if validate_only else values.copy()
    if dictionary is None or dictionary.dtype.kind != "U" or dictionary.ndim != 1:
        raise ValueError("Invalid condition-table value dictionary.")
    if len(values) and (values.min() < 0 or values.max() >= len(dictionary)):
        raise ValueError("Invalid condition-table dictionary code.")
    if validate_only and specification["dtype"] == "object":
        for value in dictionary:
            _decode_scalar(value)
        return None
    choices = np.asarray([_decode_scalar(value) for value in dictionary], dtype=object)
    restored = choices[values]
    return restored if specification["dtype"] == "object" else pd.Series(restored, dtype=specification["dtype"])

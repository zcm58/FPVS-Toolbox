"""Lossless, uncompressed compact metrics and audit tables beside workbooks.

Only a workbook's explicit ``Condition Data`` manifest selects a companion.
Historical workbooks and undeclared report sheets retain their XLSX readers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from time import perf_counter
from xml.etree.ElementTree import ParseError
import zipfile

import numpy as np
import pandas as pd

from Main_App.io import xlsx_selected_reader as _xlsx
from Main_App.io.condition_data_codec import decode_column, encode_column, json_text, validate_column_encoding

CONDITION_COMPANION_VERSION = "numpy_condition_companion_v1"
CONDITION_MANIFEST_SHEET = "Condition Data"
CONDITION_DATA_SHEET_NAMES = (
    "FFT Amplitude (uV)", "SNR", "Z Score", "BCA (uV)",
    "Spectral Eligibility", "Spectral Metric QC", "FFT and neighbors", "FFT Metadata",
)
_MAX_CACHED_COMPANIONS = 4
_MAX_CACHED_VERIFICATIONS = 256


class ConditionDataError(ValueError):
    """A declared condition companion is missing, invalid, or changed."""


@dataclass(frozen=True)
class _ConditionPayload:
    descriptor: dict
    specifications: dict[str, dict]
    columns: dict[str, dict[str, np.ndarray | pd.Series]]
    workbook_signature: object
    companion_signature: object


def _descriptor(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or value.get("version") != CONDITION_COMPANION_VERSION:
        raise ConditionDataError("Condition companion version is missing or unsupported.")
    if set(value) != {"version", "path", "size_bytes", "sha256", "sheets"}:
        raise ConditionDataError("Condition companion declaration has invalid fields.")
    name = value.get("path")
    if (
        not isinstance(name, str) or not name or name in {".", ".."}
        or any(char in name for char in ("/", "\\", ":", "\x00"))
        or Path(name).name != name or Path(name).suffix.lower() != ".npz"
    ):
        raise ConditionDataError("Condition companion path must be a local .npz basename.")
    size, digest, sheets = value.get("size_bytes"), value.get("sha256"), value.get("sheets")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise ConditionDataError("Condition companion size is invalid.")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ConditionDataError("Condition companion SHA-256 is invalid.")
    if (
        not isinstance(sheets, list) or not sheets
        or any(not isinstance(sheet, str) or sheet not in CONDITION_DATA_SHEET_NAMES for sheet in sheets)
        or len(set(sheets)) != len(sheets)
    ):
        raise ConditionDataError("Condition companion sheet declaration is invalid.")
    return {"version": CONDITION_COMPANION_VERSION, "path": name, "size_bytes": size,
            "sha256": digest, "sheets": list(sheets)}


def write_condition_companion(workbook_path: str | Path, frames: Mapping[str, pd.DataFrame]) -> dict:
    """Atomically publish already-calculated tables without numerical conversion.

    As with the previous index=False Excel export, row indices and DataFrame
    attrs are not persisted; FFT/audit metadata have explicit table columns.
    """

    workbook = Path(workbook_path)
    if not frames or any(name not in CONDITION_DATA_SHEET_NAMES for name in frames):
        raise ConditionDataError("Condition frames must contain supported compact metric or audit sheets.")
    sheets = [name for name in CONDITION_DATA_SHEET_NAMES if name in frames]
    arrays, specifications = {}, []
    for sheet_index, name in enumerate(sheets):
        frame = frames[name]
        columns = list(frame.columns)
        if not columns or any(not isinstance(column, str) or not column for column in columns) or len(set(columns)) != len(columns):
            raise ConditionDataError(f"{name} must have unique, nonempty string column names.")
        encodings, groups = [], {}
        for column_index, column in enumerate(columns):
            try:
                values, encoding = encode_column(frame[column])
            except (ValueError, TypeError) as exc:
                raise ConditionDataError(f"Cannot store {name}/{column}: {exc}") from exc
            # One native array per numerical dtype keeps compact reads from
            # opening a ZIP member separately for every harmonic column.
            group_key = (encoding["encoding"], values.dtype.str)
            if encoding["encoding"] == "dictionary_json":
                dictionary_key = f"sheet{sheet_index}_dictionary{column_index}"
                arrays[dictionary_key] = encoding["dictionary"]
                encoding["dictionary"] = dictionary_key
            if group_key not in groups:
                groups[group_key] = (f"sheet{sheet_index}_block{len(groups)}", [])
            block_key, block_columns = groups[group_key]
            encodings.append({**encoding, "array": block_key, "column": len(block_columns)})
            block_columns.append(values)
        for block_key, block_columns in groups.values():
            arrays[block_key] = np.column_stack(block_columns)
        specifications.append({"name": name, "columns": columns, "rows": len(frame), "encodings": encodings})
    arrays["metadata_json"] = np.asarray(json_text({
        "version": CONDITION_COMPANION_VERSION, "sheets": specifications,
    }), dtype=np.str_)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", prefix=f".{workbook.stem}.metrics.", suffix=".tmp", dir=workbook.parent, delete=False) as stream:
            temporary = Path(stream.name)
            np.savez(stream, **arrays)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        target = workbook.with_name(f"{workbook.stem}.metrics.{digest[:20]}.npz")
        descriptor = _descriptor({"version": CONDITION_COMPANION_VERSION, "path": target.name,
                                  "size_bytes": temporary.stat().st_size, "sha256": digest, "sheets": sheets})
        if target.exists():
            with target.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() != digest:
                    raise ConditionDataError("An existing immutable condition companion has changed.")
        else:
            os.replace(temporary, target)
            temporary = None
        return descriptor
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def condition_manifest_frame(descriptor: Mapping) -> pd.DataFrame:
    validated = _descriptor(descriptor)
    return pd.DataFrame({"Field": list(validated), "Value": [json_text(value) for value in validated.values()]})


def _read_manifest(workbook: Path) -> dict | None:
    signature = _xlsx._workbook_signature_or_none(workbook)
    cache = _xlsx._ACTIVE_XLSX_READ_CACHE.get()
    if cache is not None and signature is not None and signature in cache.condition_manifests:
        return deepcopy(cache.condition_manifests[signature])
    try:
        frame = _xlsx._read_xlsx_sheet_selected_columns_raw(
            workbook, sheet_name=CONDITION_MANIFEST_SHEET, required_columns=["Field", "Value"]
        )
    except ValueError as exc:
        if str(exc) == f"Worksheet named '{CONDITION_MANIFEST_SHEET}' not found":
            descriptor = None
        else:
            raise ConditionDataError(f"Invalid condition declaration in {workbook.name}: {exc}") from exc
    except (OSError, zipfile.BadZipFile, ParseError) as exc:
        raise ConditionDataError(f"Cannot read condition declaration in {workbook.name}: {exc}") from exc
    else:
        try:
            if frame["Field"].duplicated().any():
                raise ValueError("Repeated manifest fields.")
            decoded = {str(row["Field"]): json.loads(str(row["Value"])) for _, row in frame.iterrows()}
            size = decoded.get("size_bytes")
            if isinstance(size, float) and size.is_integer():
                decoded["size_bytes"] = int(size)
            descriptor = _descriptor(decoded)
        except (TypeError, ValueError, KeyError) as exc:
            raise ConditionDataError(f"Invalid condition declaration in {workbook.name}: {exc}") from exc
    if cache is not None and signature is not None and _xlsx._workbook_signature_or_none(workbook) == signature:
        cache.condition_manifests[signature] = deepcopy(descriptor)
    return descriptor


def _array_header(container, key: str) -> tuple[tuple, np.dtype]:
    with container.open(f"{key}.npy") as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise ConditionDataError("Unsupported condition array format version.")
    return shape, dtype


def _archive_schema(archive, container, identity: dict) -> dict[str, dict]:
    metadata_array = archive["metadata_json"]
    if metadata_array.dtype.kind != "U" or metadata_array.shape != ():
        raise ConditionDataError("Invalid condition archive metadata.")
    metadata = json.loads(str(metadata_array.item()))
    if not isinstance(metadata, dict) or metadata.get("version") != CONDITION_COMPANION_VERSION:
        raise ConditionDataError("Invalid condition archive version.")
    specifications = metadata.get("sheets")
    if not isinstance(specifications, list) or len(specifications) != len(identity["sheets"]):
        raise ConditionDataError("Condition archive disagrees with its workbook declaration.")
    sheets, expected_keys, used_columns = {}, {"metadata_json"}, {}
    for sheet_index, (name, specification) in enumerate(zip(identity["sheets"], specifications, strict=True)):
        if not isinstance(specification, dict) or specification.get("name") != name:
            raise ConditionDataError("Condition archive sheet identity is invalid.")
        columns, rows, encodings = specification.get("columns"), specification.get("rows"), specification.get("encodings")
        if (
            not isinstance(columns, list) or not columns
            or any(not isinstance(column, str) or not column for column in columns)
            or len(set(columns)) != len(columns)
            or isinstance(rows, bool) or not isinstance(rows, int) or rows < 0
            or not isinstance(encodings, list) or len(encodings) != len(columns)
        ):
            raise ConditionDataError(f"Invalid condition archive schema for {name}.")
        blocks = {}
        for column_index, (column, encoding) in enumerate(zip(columns, encodings, strict=True)):
            fields = {"encoding", "dtype", "array", "column"}
            if isinstance(encoding, dict) and encoding.get("encoding") == "dictionary_json":
                fields.add("dictionary")
            if not isinstance(encoding, dict) or set(encoding) != fields:
                raise ConditionDataError("Invalid condition archive column specification.")
            key, position = encoding["array"], encoding["column"]
            if (
                not isinstance(key, str) or re.fullmatch(rf"sheet{sheet_index}_block[0-9]+", key) is None
                or isinstance(position, bool) or not isinstance(position, int) or position < 0
            ):
                raise ConditionDataError("Invalid condition archive column location.")
            expected_keys.add(key)
            if key not in blocks:
                blocks[key] = _array_header(container, key)
                used_columns[key] = set()
            shape, dtype = blocks[key]
            if len(shape) != 2 or shape[0] != rows or position >= shape[1] or position in used_columns[key]:
                raise ConditionDataError("Invalid condition archive block dimensions or mapping.")
            used_columns[key].add(position)
            # Validate every dtype and encoding from small NPY headers, without
            # allocating or decoding unrelated metric/audit rows during reads.
            validate_column_encoding(dtype, {
                "encoding": encoding["encoding"], "dtype": encoding["dtype"],
            })
            if encoding["encoding"] == "dictionary_json":
                dictionary_key = encoding["dictionary"]
                if dictionary_key != f"sheet{sheet_index}_dictionary{column_index}":
                    raise ConditionDataError("Invalid condition archive dictionary location.")
                expected_keys.add(dictionary_key)
                dictionary_shape, dictionary_dtype = _array_header(container, dictionary_key)
                if len(dictionary_shape) != 1 or dictionary_dtype.kind != "U":
                    raise ConditionDataError("Invalid condition archive value dictionary.")
        if any(len(used_columns[key]) != header[0][1] for key, header in blocks.items()):
            raise ConditionDataError("Condition archive contains unused block columns.")
        sheets[name] = specification
    if set(archive.files) != expected_keys or len(archive.files) != len(expected_keys):
        raise ConditionDataError("Condition archive contains missing or unexpected arrays.")
    return sheets


def _companion_payload(workbook: Path, descriptor: Mapping) -> _ConditionPayload:
    identity = _descriptor(descriptor)
    parent = workbook.parent.resolve()
    path = parent / identity["path"]
    if path.resolve().parent != parent:
        raise ConditionDataError("Condition companion resolves outside its workbook directory.")
    workbook_signature = _xlsx._workbook_signature_or_none(workbook)
    signature = _xlsx._workbook_signature_or_none(path)
    if signature is None or signature.size_bytes != identity["size_bytes"]:
        raise ConditionDataError(f"Condition companion is missing or has changed: {path.name}")
    key = (workbook_signature, signature, json_text(identity))
    cache = _xlsx._ACTIVE_XLSX_READ_CACHE.get()
    if cache is not None and key in cache.condition_payloads:
        cache.condition_payloads.move_to_end(key)
        return cache.condition_payloads[key]
    if cache is not None and key in cache.condition_verified_schemas:
        # Reuse only a previously checksummed schema with unchanged workbook
        # and companion signatures. Requested columns still validate on read.
        cache.condition_verified_schemas.move_to_end(key)
        payload = _ConditionPayload(identity, cache.condition_verified_schemas[key], {}, workbook_signature, signature)
        cache.condition_payloads[key] = payload
        while len(cache.condition_payloads) > _MAX_CACHED_COMPANIONS:
            cache.condition_payloads.popitem(last=False)
        return payload
    try:
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != identity["sha256"]:
                raise ConditionDataError(f"Condition companion checksum does not match: {path.name}")
            stream.seek(0)
            with np.load(stream, allow_pickle=False) as archive, zipfile.ZipFile(stream) as container:
                specifications = _archive_schema(archive, container, identity)
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        if isinstance(exc, ConditionDataError):
            raise
        raise ConditionDataError(f"Cannot read condition companion {path.name}: {exc}") from exc
    if _xlsx._workbook_signature_or_none(path) != signature or _xlsx._workbook_signature_or_none(workbook) != workbook_signature:
        raise ConditionDataError("Condition data changed while it was being read; retry the operation.")
    payload = _ConditionPayload(identity, specifications, {}, workbook_signature, signature)
    if cache is not None:
        cache.condition_verified_schemas[key] = specifications
        cache.condition_verified_schemas.move_to_end(key)
        while len(cache.condition_verified_schemas) > _MAX_CACHED_VERIFICATIONS:
            cache.condition_verified_schemas.popitem(last=False)
        cache.condition_payloads[key] = payload
        while len(cache.condition_payloads) > _MAX_CACHED_COMPANIONS:
            cache.condition_payloads.popitem(last=False)
    return payload


def _payload_columns(workbook: Path, payload: _ConditionPayload, sheet_name: str, columns: Sequence[str]) -> pd.DataFrame:
    specification = payload.specifications[sheet_name]
    cached = payload.columns.setdefault(sheet_name, {})
    needed = [column for column in columns if column not in cached]
    path = workbook.parent.resolve() / payload.descriptor["path"]
    if needed:
        try:
            if _xlsx._workbook_signature_or_none(path) != payload.companion_signature:
                raise ConditionDataError("Condition data changed before its columns were read; retry the operation.")
            encodings = dict(zip(specification["columns"], specification["encodings"], strict=True))
            with path.open("rb") as stream, np.load(stream, allow_pickle=False) as archive:
                blocks, decoded = {}, {}
                for column in needed:
                    encoding = encodings[column]
                    key = encoding["array"]
                    if key not in blocks:
                        blocks[key] = archive[key]
                    dictionary = archive[encoding["dictionary"]] if "dictionary" in encoding else None
                    decoded[column] = decode_column(blocks[key][:, encoding["column"]], {
                        "encoding": encoding["encoding"], "dtype": encoding["dtype"],
                    }, specification["rows"], dictionary)
            if (
                _xlsx._workbook_signature_or_none(path) != payload.companion_signature
                or _xlsx._workbook_signature_or_none(workbook) != payload.workbook_signature
            ):
                raise ConditionDataError("Condition data changed while its columns were read; retry the operation.")
            cached.update(decoded)
        except (OSError, ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile) as exc:
            if isinstance(exc, ConditionDataError):
                raise
            raise ConditionDataError(f"Cannot read condition columns in {path.name}: {exc}") from exc
    return pd.DataFrame({column: cached[column] for column in columns}).copy(deep=True)


def validate_condition_companion(workbook_path: str | Path, descriptor: Mapping) -> dict:
    """Validate all stored cells, relative to the intended workbook directory."""

    workbook = Path(workbook_path)
    payload = _companion_payload(workbook, descriptor)
    for name, specification in payload.specifications.items():
        _payload_columns(workbook, payload, name, specification["columns"])
    return deepcopy(payload.descriptor)


def condition_companion_identity(workbook_path: str | Path) -> dict | None:
    workbook = Path(workbook_path)
    descriptor = _read_manifest(workbook)
    return None if descriptor is None else deepcopy(_companion_payload(workbook, descriptor).descriptor)


def declared_condition_companion(workbook_path: str | Path) -> dict | None:
    """Read a validated local declaration without opening its data archive.

    This supports cleanup of explicitly managed companions even after damage.
    Numerical consumers must use condition_companion_identity or a data reader.
    """

    return _read_manifest(Path(workbook_path))


def read_condition_sheet_header(workbook_path: str | Path, *, sheet_name: str) -> list[object]:
    workbook = Path(workbook_path)
    descriptor = _read_manifest(workbook)
    if descriptor is None or sheet_name not in descriptor["sheets"]:
        return _xlsx._read_xlsx_sheet_header_raw(workbook, sheet_name=sheet_name)
    return list(_companion_payload(workbook, descriptor).specifications[sheet_name]["columns"])


def read_condition_sheet_selected_columns(
    workbook_path: str | Path, *, sheet_name: str, required_columns: Sequence[str],
    require_all: bool = True, included_electrodes_upper: set[str] | None = None,
    electrode_column: str = "Electrode", timing_details: dict[str, float] | None = None,
) -> pd.DataFrame:
    started = perf_counter()
    workbook = Path(workbook_path)
    descriptor = _read_manifest(workbook)
    if descriptor is None or sheet_name not in descriptor["sheets"]:
        return _xlsx._read_xlsx_sheet_selected_columns_raw(
            workbook, sheet_name=sheet_name, required_columns=required_columns, require_all=require_all,
            included_electrodes_upper=included_electrodes_upper, electrode_column=electrode_column, timing_details=timing_details,
        )
    payload = _companion_payload(workbook, descriptor)
    available = payload.specifications[sheet_name]["columns"]
    requested = _xlsx._unique_requested_columns(required_columns)
    missing = [column for column in requested if column not in available]
    if require_all and missing:
        raise _xlsx.MissingXlsxColumnsError(sheet_name, missing)
    columns = [column for column in requested if column in available]
    read_columns = list(columns)
    if included_electrodes_upper is not None:
        if electrode_column not in available:
            raise _xlsx.MissingXlsxColumnsError(sheet_name, [electrode_column])
        if electrode_column not in read_columns:
            read_columns.append(electrode_column)
    frame = _payload_columns(workbook, payload, sheet_name, read_columns)
    if included_electrodes_upper is not None:
        mask = frame[electrode_column].astype(str).str.upper().str.strip().isin(included_electrodes_upper)
        frame = frame.loc[mask]
    result = frame.loc[:, columns].reset_index(drop=True).copy(deep=True) if columns else pd.DataFrame()
    _xlsx._add_timing_detail(timing_details, "condition_companion", started)
    return result


def read_condition_sheet(workbook_path: str | Path, *, sheet_name: str) -> pd.DataFrame:
    """Read stored metrics or mixed audit cells; legacy sheets use pandas."""

    workbook = Path(workbook_path)
    descriptor = _read_manifest(workbook)
    if descriptor is None or sheet_name not in descriptor["sheets"]:
        return pd.read_excel(workbook, sheet_name=sheet_name)
    payload = _companion_payload(workbook, descriptor)
    return _payload_columns(workbook, payload, sheet_name, payload.specifications[sheet_name]["columns"])


__all__ = [
    "CONDITION_COMPANION_VERSION", "CONDITION_MANIFEST_SHEET", "CONDITION_DATA_SHEET_NAMES", "ConditionDataError",
    "write_condition_companion", "condition_manifest_frame", "condition_companion_identity", "validate_condition_companion",
    "declared_condition_companion",
    "read_condition_sheet", "read_condition_sheet_header", "read_condition_sheet_selected_columns",
]

"""Lossless, uncompressed spectral arrays owned by a processed workbook.

Only a workbook's explicit ``Spectral Data`` declaration selects a companion.
Legacy workbooks continue using their physical spectral worksheets.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from time import perf_counter
from xml.etree.ElementTree import ParseError
import zipfile

import numpy as np
import pandas as pd

from Main_App.io import xlsx_selected_reader as _xlsx
from Main_App.io.companion_schema import (
    SPECTRAL_COMPANION_VERSION, SPECTRAL_SHEET_NAMES, SpectralDataError, spectral_descriptor as _descriptor,
)
from Main_App.io.numpy_companion import open_verified_schema

SPECTRAL_MANIFEST_SHEET = "Spectral Data"
_MAX_CACHED_COMPANIONS = 4
# Keep the metadata for a full multi-condition study across ordered passes.
_MAX_CACHED_VERIFICATIONS = 1536
_MAX_CACHED_HEADER_LABELS = 262_144


@dataclass(frozen=True)
class _SpectralPayload:
    descriptor: dict
    columns: dict[str, tuple[str, ...]]
    electrodes: dict[str, np.ndarray]
    values: dict[str, np.ndarray]
    metadata: dict
    workbook_signature: object
    companion_signature: object


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Spectral metadata cannot encode {type(value).__name__}.")


def _json_text(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, default=_json_default)


def _spectral_arrays(
    frames: Mapping[str, pd.DataFrame], sheets: list[str], metadata: Mapping | None,
) -> Iterator[tuple[str, np.ndarray]]:
    """Yield the ordered NPZ members and release each sheet before converting the next."""
    for index, name in enumerate(sheets):
        frame = frames[name]
        columns = [str(column) for column in frame.columns]
        if not columns or columns[0] != "Electrode" or len(set(columns)) != len(columns):
            raise SpectralDataError(f"{name} must have unique columns starting with Electrode.")
        if frame.empty or len(columns) < 2 or frame.iloc[:, 0].isna().any():
            raise SpectralDataError(f"{name} must contain electrode labels and spectral values.")
        electrodes = np.asarray(frame.iloc[:, 0].astype(str).tolist(), dtype=np.str_)
        if any(not label.strip() for label in electrodes) or len(set(electrodes)) != len(electrodes):
            raise SpectralDataError(f"{name} electrode labels must be nonempty and unique.")
        try:
            values = frame.iloc[:, 1:].to_numpy(dtype=np.float64, copy=True)
        except (TypeError, ValueError) as exc:
            raise SpectralDataError(f"{name} contains nonnumeric spectral values.") from exc
        if index == 0:
            fullfft_width = values.shape[1]
        yield f"sheet{index}_columns", np.asarray(columns, dtype=np.str_)
        yield f"sheet{index}_electrodes", electrodes
        yield f"sheet{index}_values", values
        del values
    details = dict(metadata or {})
    frequency_grid = details.pop("frequencies_hz", None)
    if frequency_grid is None and "sampling_frequency_hz" in details and "fft_sample_count" in details:
        frequency_grid = np.fft.rfftfreq(int(details["fft_sample_count"]), 1.0 / float(details["sampling_frequency_hz"]))
    if frequency_grid is not None:
        grid = np.asarray(frequency_grid, dtype=np.float64)
        if grid.ndim != 1 or len(grid) != fullfft_width or not np.isfinite(grid).all():
            raise SpectralDataError("Exact FullFFT frequencies do not match its spectral columns.")
    metadata_json = np.asarray(_json_text({
        "version": SPECTRAL_COMPANION_VERSION, "sheets": sheets, "metadata": details,
        "has_exact_fullfft_frequencies": frequency_grid is not None,
    }), dtype=np.str_)
    if frequency_grid is not None:
        yield "fullfft_frequencies_hz", grid
    yield "metadata_json", metadata_json


def write_spectral_companion(
    workbook_path: str | Path,
    frames: Mapping[str, pd.DataFrame],
    *,
    metadata: Mapping | None = None,
) -> dict:
    """Atomically publish immutable float64 arrays beside their workbook."""

    workbook = Path(workbook_path)
    if SPECTRAL_SHEET_NAMES[0] not in frames or any(name not in SPECTRAL_SHEET_NAMES for name in frames):
        raise SpectralDataError("Spectral frames must contain FullFFT and optionally FullSNR.")
    sheets = [name for name in SPECTRAL_SHEET_NAMES if name in frames]
    input_error = None

    def validated_arrays():
        nonlocal input_error
        try:
            yield from _spectral_arrays(frames, sheets, metadata)
        except Exception as exc:
            # A later ZIP close failure must not replace the original input error.
            input_error = exc
            raise

    arrays = validated_arrays()
    try:
        return _publish_spectral_archive(workbook, sheets, arrays)
    except Exception as exc:
        archive_error = exc
    if input_error is not None:
        raise input_error
    # A write can fail before validation finishes. Invalid inputs historically
    # take priority, even when the destination is unavailable or out of space.
    for _key, array in arrays:
        del array
    raise archive_error


def _publish_spectral_archive(workbook: Path, sheets: list[str], arrays: Iterator[tuple[str, np.ndarray]]) -> dict:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w+b", prefix=f".{workbook.stem}.spectra.", suffix=".tmp", dir=workbook.parent, delete=False) as stream:
            temporary = Path(stream.name)
            # Match np.savez's member order, NPY encoding and ZIP64 local headers.
            with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_STORED) as archive:
                for key, array in arrays:
                    with archive.open(f"{key}.npy", "w", force_zip64=True) as member:
                        np.lib.format.write_array(member, array, allow_pickle=False)
                    del array
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        target = workbook.with_name(f"{workbook.stem}.spectra.{digest[:20]}.npz")
        descriptor = _descriptor({"version": SPECTRAL_COMPANION_VERSION, "path": target.name,
                                  "size_bytes": temporary.stat().st_size, "sha256": digest, "sheets": sheets})
        if target.exists():
            with target.open("rb") as existing:
                if hashlib.file_digest(existing, "sha256").hexdigest() != digest:
                    raise SpectralDataError("An existing immutable spectral companion has changed.")
        else:
            os.replace(temporary, target)
            temporary = None
        return descriptor
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def spectral_manifest_frame(descriptor: Mapping) -> pd.DataFrame:
    """Return the small declaration to write as the ``Spectral Data`` sheet."""

    validated = _descriptor(descriptor)
    return pd.DataFrame({"Field": list(validated), "Value": [_json_text(value) for value in validated.values()]})


def _read_manifest(workbook: Path) -> dict | None:
    from Main_App.io.result_manifest import is_result_manifest, read_result_manifest

    if is_result_manifest(workbook):
        return read_result_manifest(workbook)["spectral_companion"]
    signature = _xlsx._workbook_signature_or_none(workbook)
    cache = _xlsx._ACTIVE_XLSX_READ_CACHE.get()
    if cache is not None and signature is not None and signature in cache.spectral_manifests:
        return deepcopy(cache.spectral_manifests[signature])
    try:
        frame = _xlsx._read_xlsx_sheet_selected_columns_raw(
            workbook, sheet_name=SPECTRAL_MANIFEST_SHEET, required_columns=["Field", "Value"]
        )
    except ValueError as exc:
        if str(exc) == f"Worksheet named '{SPECTRAL_MANIFEST_SHEET}' not found":
            descriptor = None
        else:
            raise SpectralDataError(f"Invalid spectral declaration in {workbook.name}: {exc}") from exc
    except (OSError, zipfile.BadZipFile, ParseError) as exc:
        raise SpectralDataError(f"Cannot read spectral declaration in {workbook.name}: {exc}") from exc
    else:
        try:
            if frame["Field"].duplicated().any():
                raise ValueError("Repeated manifest fields.")
            decoded = {str(row["Field"]): json.loads(str(row["Value"])) for _, row in frame.iterrows()}
            # The XML reader parses numeric-looking cells as floats, even when
            # the manifest writer supplied their JSON integer representation.
            size = decoded.get("size_bytes")
            if isinstance(size, float) and size.is_integer():
                decoded["size_bytes"] = int(size)
            descriptor = _descriptor(decoded)
        except (TypeError, ValueError, KeyError) as exc:
            raise SpectralDataError(f"Invalid spectral declaration in {workbook.name}: {exc}") from exc
    if cache is not None and signature is not None and _xlsx._workbook_signature_or_none(workbook) == signature:
        cache.spectral_manifests[signature] = deepcopy(descriptor)
    return descriptor


def _companion_location(workbook: Path, descriptor: Mapping) -> tuple:
    identity = _descriptor(descriptor)
    parent = workbook.parent.resolve()
    path = parent / identity["path"]
    if path.resolve().parent != parent:
        raise SpectralDataError("Spectral companion resolves outside its workbook directory.")
    workbook_signature = _xlsx._workbook_signature_or_none(workbook)
    signature = _xlsx._workbook_signature_or_none(path)
    if signature is None or signature.size_bytes != identity["size_bytes"]:
        raise SpectralDataError(f"Spectral companion is missing or has changed: {path.name}")
    key = (workbook_signature, signature, _json_text(identity))
    return identity, path, workbook_signature, signature, key


def _dense_shape(container: zipfile.ZipFile, key: str) -> tuple[int, ...]:
    """Validate a dense member's header and byte length without allocating it."""
    member = container.getinfo(f"{key}.npy")
    with container.open(member) as stream:
        version = np.lib.format.read_magic(stream)
        if version == (1, 0):
            shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
        elif version == (2, 0):
            shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
        else:
            raise SpectralDataError("Unsupported spectral array format version.")
        if (dtype != np.dtype(np.float64) or len(shape) != 2
                or member.file_size != stream.tell() + math.prod(shape) * dtype.itemsize):
            raise SpectralDataError("Invalid spectral array dimensions, type, or byte length.")
    return shape


def _companion_payload(workbook: Path, descriptor: Mapping) -> _SpectralPayload:
    identity, path, workbook_signature, signature, key = _companion_location(workbook, descriptor)
    cache = _xlsx._ACTIVE_XLSX_READ_CACHE.get()
    if cache is not None and key in cache.spectral_payloads:
        cache.spectral_payloads.move_to_end(key)
        return cache.spectral_payloads[key]
    try:
        with path.open("rb") as stream:
            with open_verified_schema(
                stream, identity,
                SpectralDataError(f"Spectral companion checksum does not match: {path.name}"),
            ) as (archive, previously_checked):
                manifest = json.loads(str(archive["metadata_json"].item()))
                if manifest.get("version") != SPECTRAL_COMPANION_VERSION or manifest.get("sheets") != identity["sheets"]:
                    raise SpectralDataError("Spectral archive disagrees with its workbook declaration.")
                columns, electrodes = {}, {}
                for index, name in enumerate(identity["sheets"]):
                    labels = archive[f"sheet{index}_columns"]
                    rows = archive[f"sheet{index}_electrodes"]
                    if not previously_checked:
                        shape = _dense_shape(archive.zip, f"sheet{index}_values")
                        if (labels.dtype.kind != "U" or rows.dtype.kind != "U" or labels.ndim != 1 or rows.ndim != 1
                                or len(labels) < 2 or labels[0] != "Electrode"
                                or shape != (len(rows), len(labels) - 1)):
                            raise SpectralDataError(f"Invalid spectral array dimensions or types for {name}.")
                    # Check the decoded labels we retain, avoiding a separate
                    # iteration that boxes every frequency as a NumPy scalar.
                    header = tuple(labels.tolist())
                    if not previously_checked and (
                        len(set(header)) != len(header) or len(set(rows.tolist())) != len(rows)
                    ):
                        raise SpectralDataError(f"Invalid spectral array dimensions or types for {name}.")
                    columns[name], electrodes[name] = header, rows
                    rows.setflags(write=False)
                metadata = manifest.get("metadata")
                if not isinstance(metadata, dict):
                    raise SpectralDataError("Invalid spectral metadata.")
                if manifest.get("has_exact_fullfft_frequencies"):
                    grid = archive["fullfft_frequencies_hz"]
                    if grid.dtype != np.dtype(np.float64) or grid.shape != (len(columns[SPECTRAL_SHEET_NAMES[0]]) - 1,) or not np.isfinite(grid).all():
                        raise SpectralDataError("Invalid exact FullFFT frequency grid.")
                    # Keep DataFrame attrs comparable by pandas concatenation;
                    # the authoritative NPZ grid remains exact float64 data.
                    metadata["frequencies_hz"] = grid.tolist()
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile) as exc:
        if isinstance(exc, SpectralDataError):
            raise
        raise SpectralDataError(f"Cannot read spectral companion {path.name}: {exc}") from exc
    if _xlsx._workbook_signature_or_none(path) != signature or _xlsx._workbook_signature_or_none(workbook) != workbook_signature:
        raise SpectralDataError("Spectral data changed while it was being read; retry the operation.")
    payload = _SpectralPayload(identity, columns, electrodes, {}, metadata, workbook_signature, signature)
    if cache is not None:
        # Repeated grids share immutable header tuples; keep no dense arrays in
        # the longer-lived verification cache after the four-payload LRU evicts.
        for name, header in columns.items():
            for verified in cache.spectral_verified_headers.values():
                if verified.get(name) == header:
                    columns[name] = verified[name]
                    break
        cache.spectral_verified_headers[key] = dict(columns)
        cache.spectral_verified_headers.move_to_end(key)
        while (
            len(cache.spectral_verified_headers) > _MAX_CACHED_VERIFICATIONS
            or sum({
                id(header): len(header)
                for verified in cache.spectral_verified_headers.values()
                for header in verified.values()
            }.values()) > _MAX_CACHED_HEADER_LABELS
        ):
            cache.spectral_verified_headers.popitem(last=False)
        cache.spectral_payloads[key] = payload
        while len(cache.spectral_payloads) > _MAX_CACHED_COMPANIONS:
            cache.spectral_payloads.popitem(last=False)
    return payload


def _sheet_values(workbook: Path, payload: _SpectralPayload, sheet_name: str) -> np.ndarray:
    """Load only the requested, already schema-validated dense sheet."""
    path = workbook.parent.resolve() / payload.descriptor["path"]

    def check_signatures() -> None:
        if (_xlsx._workbook_signature_or_none(path) != payload.companion_signature
                or _xlsx._workbook_signature_or_none(workbook) != payload.workbook_signature):
            raise SpectralDataError("Spectral data changed while it was being read; retry the operation.")

    check_signatures()
    if sheet_name not in payload.values:
        index = payload.descriptor["sheets"].index(sheet_name)
        try:
            with path.open("rb") as stream, np.load(stream, allow_pickle=False) as archive:
                data = archive[f"sheet{index}_values"]
            if data.dtype != np.dtype(np.float64) or data.shape != (
                len(payload.electrodes[sheet_name]), len(payload.columns[sheet_name]) - 1,
            ):
                raise SpectralDataError(f"Invalid spectral array dimensions or types for {sheet_name}.")
            check_signatures()
        except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile) as exc:
            if isinstance(exc, SpectralDataError):
                raise
            raise SpectralDataError(f"Cannot read spectral values in {path.name}: {exc}") from exc
        data.setflags(write=False)
        payload.values[sheet_name] = data
    return payload.values[sheet_name]


def _verified_headers(workbook: Path, descriptor: Mapping) -> dict[str, tuple[str, ...]]:
    # The key rechecks both current file signatures and the exact declaration.
    # Only a completed full checksum/schema/grid validation populates this map.
    _identity, _path, _workbook_signature, _signature, key = _companion_location(workbook, descriptor)
    cache = _xlsx._ACTIVE_XLSX_READ_CACHE.get()
    if cache is not None and key in cache.spectral_verified_headers:
        cache.spectral_verified_headers.move_to_end(key)
        return cache.spectral_verified_headers[key]
    return _companion_payload(workbook, descriptor).columns


def validate_spectral_companion(workbook_path: str | Path, descriptor: Mapping) -> dict:
    """Validate a declaration relative to the intended workbook directory."""

    return deepcopy(_companion_payload(Path(workbook_path), descriptor).descriptor)


def spectral_companion_identity(workbook_path: str | Path) -> dict | None:
    """Return validated identity; only undeclared legacy workbooks return None."""

    workbook = Path(workbook_path)
    return _identity_from_descriptor(workbook, _read_manifest(workbook))


def _identity_from_descriptor(workbook: Path, descriptor: dict | None) -> dict | None:
    if descriptor is None:
        return None
    _verified_headers(workbook, descriptor)
    return deepcopy(descriptor)


def read_spectral_sheet_header(workbook_path: str | Path, *, sheet_name: str = SPECTRAL_SHEET_NAMES[0]) -> list[object]:
    workbook = Path(workbook_path)
    descriptor = _read_manifest(workbook)
    if descriptor is None:
        return _xlsx._read_xlsx_sheet_header_raw(workbook, sheet_name=sheet_name)
    columns = _verified_headers(workbook, descriptor)
    if sheet_name not in columns:
        raise SpectralDataError(f"Spectral companion has no sheet named {sheet_name!r}.")
    return list(columns[sheet_name])


def read_spectral_sheet_selected_columns(
    workbook_path: str | Path,
    *,
    sheet_name: str = SPECTRAL_SHEET_NAMES[0],
    required_columns: Sequence[str],
    require_all: bool = True,
    included_electrodes_upper: set[str] | None = None,
    electrode_column: str = "Electrode",
    timing_details: dict[str, float] | None = None,
) -> pd.DataFrame:
    started = perf_counter()
    workbook = Path(workbook_path)
    descriptor = _read_manifest(workbook)
    if descriptor is None:
        return _xlsx._read_xlsx_sheet_selected_columns_raw(
            workbook, sheet_name=sheet_name, required_columns=required_columns, require_all=require_all,
            included_electrodes_upper=included_electrodes_upper, electrode_column=electrode_column, timing_details=timing_details,
        )
    payload = _companion_payload(workbook, descriptor)
    if sheet_name not in payload.columns:
        raise SpectralDataError(f"Spectral companion has no sheet named {sheet_name!r}.")
    columns = payload.columns[sheet_name]
    requested = _xlsx._unique_requested_columns(required_columns)
    rows = payload.electrodes[sheet_name]
    if included_electrodes_upper is None and tuple(requested) == columns:
        # Detach the complete float64 block once and keep each column contiguous.
        values = _sheet_values(workbook, payload, sheet_name)
        frame = pd.DataFrame(values.copy(order="F"), columns=columns[1:], copy=False)
        frame.insert(0, "Electrode", rows)
    else:
        positions = dict.fromkeys(requested, -1)
        for index, label in enumerate(columns):
            if label in positions:
                positions[label] = index
        missing = [column for column, index in positions.items() if index < 0]
        if require_all and missing:
            raise _xlsx.MissingXlsxColumnsError(sheet_name, missing)
        if included_electrodes_upper is not None and electrode_column != "Electrode":
            raise _xlsx.MissingXlsxColumnsError(sheet_name, [electrode_column])
        mask = slice(None) if included_electrodes_upper is None else np.asarray([
            str(label).upper().strip() in included_electrodes_upper for label in rows
        ])
        selected = [column for column, index in positions.items() if index >= 0]
        numeric = [column for column in selected if column != "Electrode"]
        if numeric:
            values = _sheet_values(workbook, payload, sheet_name)
            indices = [positions[column] - 1 for column in numeric]
            # Gather directly into the detached block pandas will return.
            if included_electrodes_upper is None:
                block = values.T[indices]
            else:
                block = values.T[np.ix_(indices, np.arange(len(rows))[mask])]
            frame = pd.DataFrame(block.T, columns=numeric, copy=False)
        else:
            frame = pd.DataFrame()
        if "Electrode" in selected:
            frame.insert(selected.index("Electrode"), "Electrode", rows[mask])
    frame.attrs["spectral_metadata"] = deepcopy(payload.metadata)
    _xlsx._add_timing_detail(timing_details, "spectral_companion", started)
    return frame


def read_spectral_sheet(workbook_path: str | Path, *, sheet_name: str = SPECTRAL_SHEET_NAMES[0]) -> pd.DataFrame:
    """Read the complete stored sheet without recomputing any spectral values."""

    if _xlsx._ACTIVE_XLSX_READ_CACHE.get() is None:
        with _xlsx.xlsx_read_cache_scope():
            return read_spectral_sheet(workbook_path, sheet_name=sheet_name)
    return read_spectral_sheet_selected_columns(
        workbook_path, sheet_name=sheet_name,
        required_columns=read_spectral_sheet_header(workbook_path, sheet_name=sheet_name),
    )


__all__ = [
    "SPECTRAL_COMPANION_VERSION", "SPECTRAL_MANIFEST_SHEET", "SPECTRAL_SHEET_NAMES", "SpectralDataError",
    "write_spectral_companion", "spectral_manifest_frame", "spectral_companion_identity", "validate_spectral_companion",
    "read_spectral_sheet", "read_spectral_sheet_header", "read_spectral_sheet_selected_columns",
]

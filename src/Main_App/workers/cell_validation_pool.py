"""Ordered, memory-bounded read-only validation; no scientific/cache authority.

Credits inspect only ordinary managed declaration/ZIP/NPY headers. Unsupported
inputs and exhausted parallel headroom retain native serial validation. Full
artifact checks remain owned by the supplied validator on every invocation.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextvars import Context
import json
import math
import os
from pathlib import Path
import struct
from typing import Any
import zipfile

import numpy as np
import psutil

from Main_App.io.result_manifest import RESULT_MANIFEST_VERSION, _validate_manifest
from Main_App.workers.mp_env import compute_effective_max_workers
from Main_App.workers.review_resource_budget import probe_memory_snapshot

_MIB = 1024**2
_BASE_CREDIT = 32 * _MIB
_MAX_MANIFEST = _MIB
_MAX_COMPANION = 64 * _MIB
_MAX_MEMBERS = 128
_MAX_MATERIALIZED = 8 * _MIB
_MAX_NPY_HEADER = 10_000


def _signature(path: Path) -> tuple:
    value = path.stat()
    return value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_dev, value.st_ino


def _metadata_bytes(path: Path, *, spectral: bool) -> int:
    """Bound central directory and materialized metadata before opening arrays."""
    before = _signature(path)
    if not 22 <= before[0] <= _MAX_COMPANION:
        raise ValueError("Uncharacterized companion size")
    with path.open("rb") as stream:
        stream.seek(-22, os.SEEK_END)
        tail = stream.read(22)
    marker, disk, start_disk, disk_count, count, size, offset, comment = struct.unpack("<4s4H2LH", tail)
    if (marker != b"PK\x05\x06" or disk or start_disk or comment or disk_count != count
            or not 0 < count <= _MAX_MEMBERS or size > _MIB or offset + size != before[0] - 22):
        raise ValueError("Uncharacterized ZIP directory")
    materialized = 0
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) != count or len({item.filename for item in members}) != count:
            raise ValueError("Uncharacterized ZIP members")
        for member in members:
            name = member.filename
            needed = name == "metadata_json.npy" or spectral and (
                name == "fullfft_frequencies_hz.npy"
                or name.endswith("_columns.npy") or name.endswith("_electrodes.npy")
            )
            if not needed:
                continue
            if not 0 < member.file_size <= _MAX_MATERIALIZED:
                raise ValueError("Unbounded metadata member")
            with archive.open(member) as stream:
                version = np.lib.format.read_magic(stream)
                if version == (1, 0):
                    shape, _, dtype = np.lib.format.read_array_header_1_0(stream, max_header_size=_MAX_NPY_HEADER)
                elif version == (2, 0):
                    shape, _, dtype = np.lib.format.read_array_header_2_0(stream, max_header_size=_MAX_NPY_HEADER)
                else:
                    raise ValueError("Uncharacterized NPY header")
                if (dtype.hasobject or any(type(n) is not int or n < 0 for n in shape)
                        or math.prod(shape) * dtype.itemsize + stream.tell() != member.file_size):
                    raise ValueError("Unbounded NPY metadata geometry")
            materialized += member.file_size
            if materialized > _MAX_MATERIALIZED:
                raise ValueError("Unbounded metadata workspace")
    if before != _signature(path):
        raise ValueError("Companion changed while budgeting")
    return materialized


def cell_validation_credit(workbook_path: str | Path) -> int | None:
    """Return a conservative metadata/hash credit, never an integrity receipt."""
    try:
        workbook = Path(workbook_path).resolve()
        before = _signature(workbook)
        if workbook.suffix.lower() != ".fpvs" or not 0 < before[0] <= _MAX_MANIFEST:
            return None
        with workbook.open("rb") as stream:
            data = stream.read(_MAX_MANIFEST + 1)
        if len(data) != before[0] or before != _signature(workbook):
            return None
        value = json.loads(data)
        if value.get("version") != RESULT_MANIFEST_VERSION:
            return None
        manifest = _validate_manifest(value)
        materialized = 0
        for key in ("spectral_companion", "condition_companion"):
            descriptor = manifest[key]
            if descriptor is None:
                continue
            path = workbook.parent / descriptor["path"]
            if path.resolve().parent != workbook.parent or path.stat().st_size != descriptor["size_bytes"]:
                return None
            materialized += _metadata_bytes(path, spectral=key == "spectral_companion")
        if before != _signature(workbook):
            return None
        # Headers/Unicode arrays, Python strings/JSON objects and detached
        # descriptors have materially greater overhead than their stored bytes.
        # Dense FFT/metric values are not read by native identity validation.
        return _BASE_CREDIT + 16 * materialized + 4 * len(data)
    except (AttributeError, MemoryError, OSError, OverflowError, TypeError, ValueError, KeyError,
            EOFError, struct.error, zipfile.BadZipFile):
        return None


def _usable_cpus() -> int:
    try:
        return max(1, len(psutil.Process().cpu_affinity()))
    except (AttributeError, OSError, TypeError, ValueError, psutil.Error):
        return max(1, os.cpu_count() or 1)


def _headroom(snapshot) -> int | None:
    if (type(snapshot.total_bytes) is not int or snapshot.total_bytes <= 0
            or type(snapshot.physical_available_bytes) is not int or snapshot.physical_available_bytes < 0):
        return None
    available = snapshot.physical_available_bytes
    if snapshot.commit_required:
        if type(snapshot.commit_available_bytes) is not int or snapshot.commit_available_bytes < 0:
            return None
        available = min(available, snapshot.commit_available_bytes)
    return max(0, available - max(1024**3, snapshot.total_bytes // 16))


def ordered_cell_validation(
    items: Sequence[Any], validator: Callable[[Any], Any],
    credit_for_item: Callable[[Any], int | None], *, max_workers: int,
) -> list[Any]:
    """Preserve canonical result/error order while admitting small read owners."""
    if len(items) < 2 or type(max_workers) is not int or max_workers <= 1:
        return [validator(item) for item in items]
    try:
        snapshot = probe_memory_snapshot()
        ceiling = min(len(items), compute_effective_max_workers(
            snapshot.total_bytes, _usable_cpus(), max_workers,
        ))
        if _headroom(snapshot) is None:
            ceiling = 1
    except (AttributeError, MemoryError, OSError, OverflowError, RuntimeError, TypeError, ValueError, psutil.Error):
        ceiling = 1
    if ceiling <= 1:
        return [Context().run(validator, item) for item in items]

    values: dict[int, Any] = {}
    failures: dict[int, BaseException] = {}
    futures: dict[Any, tuple[int, int]] = {}
    next_index = 0
    reserved = 0
    with ThreadPoolExecutor(max_workers=ceiling) as pool:
        while next_index < len(items) or futures:
            while next_index < len(items) and len(futures) < ceiling:
                if failures and next_index >= min(failures):
                    break
                try:
                    credit = credit_for_item(items[next_index])
                    headroom = _headroom(probe_memory_snapshot())
                except (AttributeError, MemoryError, OSError, OverflowError, RuntimeError, TypeError, ValueError, psutil.Error):
                    credit, headroom = None, None
                permitted = (type(credit) is int and credit > 0 and headroom is not None
                             and reserved + credit <= headroom)
                if not permitted:
                    if futures:
                        break  # Drain before an unsupported or pressured serial call.
                    values[next_index] = Context().run(validator, items[next_index])
                else:
                    future = pool.submit(Context().run, validator, items[next_index])
                    futures[future] = next_index, credit
                    reserved += credit
                next_index += 1
            if not futures:
                break  # Completed, or every earlier cell precedes the first failure.
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                index, credit = futures.pop(future)
                reserved -= credit
                try:
                    values[index] = future.result()
                except BaseException as error:
                    failures[index] = error
            if failures:
                first = min(failures)
                for future, (index, _) in futures.items():
                    if index > first:
                        future.cancel()
        if failures:
            raise failures[min(failures)]
    return [values[index] for index in range(len(items))]

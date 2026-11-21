"""Checksum a NumPy result archive before reading its declared arrays."""

from contextlib import contextmanager
import hashlib
from io import BytesIO
import os
from pathlib import Path
from typing import BinaryIO

import numpy as np

from Main_App.io.companion_schema import checked_schema


# A worker holds at most one such buffer during archive validation. Larger
# spectra retain the streaming checksum path regardless of cohort size.
_MAX_BUFFER_BYTES = 16 * 1024 * 1024


def validation_buffer_bytes(size_bytes: int, *, limit: int | None = None) -> int:
    """Size of the optional in-memory archive during this validation."""
    if limit is None:
        limit = _MAX_BUFFER_BYTES
    return size_bytes if 0 < size_bytes <= limit else 0


def _read_buffer(stream: BinaryIO, size_bytes: int, checksum_error: ValueError) -> BytesIO:
    contents = stream.read(size_bytes + 1)
    if len(contents) != size_bytes:
        raise checksum_error
    return BytesIO(contents)


@contextmanager
def open_verified_npz(stream: BinaryIO, size_bytes: int, expected_sha256: str, checksum_error: ValueError,
                      *, buffer_limit: int | None = None):
    """Parse admitted archives from the same file bytes that passed the checksum."""
    with open_verified_npz_with_buffer_status(
        stream, size_bytes, expected_sha256, checksum_error, buffer_limit,
    ) as (archive, _):
        yield archive


@contextmanager
def open_verified_schema(stream: BinaryIO, identity: dict, checksum_error: ValueError):
    """Expose a prior schema check only for freshly hashed, immutable input."""
    with open_verified_npz_with_buffer_status(
        stream, identity["size_bytes"], identity["sha256"], checksum_error,
    ) as (archive, immutable):
        with checked_schema(identity, immutable=immutable) as previously_checked:
            yield archive, previously_checked


@contextmanager
def open_verified_npz_with_buffer_status(
    stream: BinaryIO, size_bytes: int, expected_sha256: str, checksum_error: ValueError, buffer_limit: int | None = None,
):
    """Yield the validated NPZ and whether its reads use the verified memory snapshot."""
    source = stream
    try:
        if validation_buffer_bytes(size_bytes, limit=buffer_limit):
            try:
                source = _read_buffer(stream, size_bytes, checksum_error)
                digest = hashlib.file_digest(source, "sha256")
            except MemoryError:
                if source is not stream:
                    source.close()
                source = stream
                stream.seek(0)
        if source is stream:
            digest = hashlib.file_digest(stream, "sha256")
        if digest.hexdigest() != expected_sha256:
            raise checksum_error
        source.seek(0)
        with np.load(source, allow_pickle=False) as archive:
            yield archive, source is not stream
    finally:
        if source is not stream:
            source.close()


def open_replaceable_companion(path: Path) -> BinaryIO:
    """Read live bytes while another process can still rename or replace the file."""
    # An unbuffered handle cannot serve stale read-ahead across sheet boundaries.
    if os.name != "nt":
        return path.open("rb", buffering=0)

    def opener(name: str, flags: int) -> int:
        import _winapi
        import msvcrt

        # FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE. Ordinary
        # Python open() on Windows denies rename until the last reader closes.
        handle = _winapi.CreateFile(name, _winapi.GENERIC_READ, 7, 0, _winapi.OPEN_EXISTING, 0, 0)
        try:
            return msvcrt.open_osfhandle(handle, flags | os.O_BINARY)
        except BaseException:
            _winapi.CloseHandle(handle)
            raise

    return open(path, "rb", buffering=0, opener=opener)

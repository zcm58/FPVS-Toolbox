"""Checksum a NumPy result archive before reading its declared arrays."""

from contextlib import contextmanager
import hashlib
from io import BytesIO
import os
from pathlib import Path
from typing import BinaryIO

import numpy as np


# A worker holds at most one such buffer during archive validation. Larger
# spectra retain the streaming checksum path regardless of cohort size.
_MAX_BUFFER_BYTES = 16 * 1024 * 1024


def validation_buffer_bytes(size_bytes: int) -> int:
    """Size of the optional in-memory archive during this validation."""
    return size_bytes if 0 < size_bytes <= _MAX_BUFFER_BYTES else 0


def _read_buffer(stream: BinaryIO, size_bytes: int, checksum_error: ValueError) -> BytesIO:
    contents = stream.read(size_bytes + 1)
    if len(contents) != size_bytes:
        raise checksum_error
    return BytesIO(contents)


@contextmanager
def open_verified_npz(stream: BinaryIO, size_bytes: int, expected_sha256: str, checksum_error: ValueError):
    """Parse small archives from the same file bytes that passed the checksum."""
    source = stream
    try:
        if validation_buffer_bytes(size_bytes):
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
            yield archive
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

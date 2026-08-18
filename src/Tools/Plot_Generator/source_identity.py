"""Stable source-file identities for auditable SNR publication."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re


_HASH_CHUNK_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class SNRPublicationError(RuntimeError):
    """Raised when a complete SNR output run cannot be published."""


class SNRPublicationCancelled(SNRPublicationError):
    """Raised when cancellation is observed before atomic publication."""


@dataclass(frozen=True, slots=True)
class SourceFileIdentity:
    """Content hash plus the stable file metadata observed around hashing."""

    sha256: str
    size_bytes: int
    stat_signature: tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class SourceWorkbookSnapshot:
    """Immutable workbook bytes paired with their stable source identity."""

    content: bytes = field(repr=False)
    identity: SourceFileIdentity


def source_stat_signature(path: str | Path) -> tuple[int, int, int, int]:
    """Return metadata sufficient to detect ordinary concurrent file writes."""

    stat = Path(path).stat()
    return (
        int(stat.st_dev),
        int(stat.st_ino),
        int(stat.st_size),
        int(stat.st_mtime_ns),
    )


def sha256_file(
    path: Path,
    *,
    cancellation_checkpoint: Callable[[], bool] | None = None,
) -> str:
    """Return a true content SHA-256 with cooperative cancellation checks."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            if cancellation_checkpoint is not None and cancellation_checkpoint():
                raise SNRPublicationCancelled(
                    "SNR output publication was cancelled while hashing inputs."
                )
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def capture_stable_source_identity(
    path: str | Path,
    *,
    expected_stat_signature: tuple[int, int, int, int] | None = None,
    cancellation_checkpoint: Callable[[], bool] | None = None,
) -> SourceFileIdentity:
    """Hash a file only when it stayed unchanged since the optional checkpoint."""

    source = Path(path)
    before_hash = source_stat_signature(source)
    if (
        expected_stat_signature is not None
        and before_hash != expected_stat_signature
    ):
        raise SNRPublicationError(
            f"Source workbook changed while SNR data were being read: "
            f"{source.name}. Restart generation after workbook writes have finished."
        )
    digest = sha256_file(
        source,
        cancellation_checkpoint=cancellation_checkpoint,
    )
    after_hash = source_stat_signature(source)
    if after_hash != before_hash:
        raise SNRPublicationError(
            f"Source workbook changed while its SNR input fingerprint was being "
            f"captured: {source.name}. Restart generation after workbook writes "
            "have finished."
        )
    return SourceFileIdentity(
        sha256=digest,
        size_bytes=after_hash[2],
        stat_signature=after_hash,
    )


def capture_stable_source_snapshot(
    path: str | Path,
    *,
    cancellation_checkpoint: Callable[[], bool] | None = None,
) -> SourceWorkbookSnapshot:
    """Read and hash one stable, immutable copy of a source workbook."""

    source = Path(path)
    before_read = source_stat_signature(source)
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    with source.open("rb") as handle:
        while True:
            if cancellation_checkpoint is not None and cancellation_checkpoint():
                raise SNRPublicationCancelled(
                    "SNR output publication was cancelled while reading inputs."
                )
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            chunks.append(chunk)
            digest.update(chunk)
    after_read = source_stat_signature(source)
    if after_read != before_read:
        raise SNRPublicationError(
            f"Source workbook changed while SNR data were being read: "
            f"{source.name}. Restart generation after workbook writes have finished."
        )
    content = b"".join(chunks)
    return SourceWorkbookSnapshot(
        content=content,
        identity=SourceFileIdentity(
            sha256=digest.hexdigest(),
            size_bytes=after_read[2],
            stat_signature=after_read,
        ),
    )


def verify_source_snapshot_after_read(
    path: str | Path,
    *,
    snapshot: SourceWorkbookSnapshot,
    cancellation_checkpoint: Callable[[], bool] | None = None,
) -> SourceFileIdentity:
    """Require the live workbook to still equal the exact captured bytes.

    This intentionally compares bytes instead of calculating a second digest.
    The full comparison preserves detection of same-size edits whose mtime was
    restored while keeping hashing to the single snapshot-read pass.
    """

    source = Path(path)
    expected_signature = snapshot.identity.stat_signature
    if source_stat_signature(source) != expected_signature:
        raise SNRPublicationError(
            f"Source workbook changed while SNR data were being read: "
            f"{source.name}. Restart generation after workbook writes have finished."
        )

    content = memoryview(snapshot.content)
    offset = 0
    matches = True
    with source.open("rb") as handle:
        while True:
            if cancellation_checkpoint is not None and cancellation_checkpoint():
                raise SNRPublicationCancelled(
                    "SNR output publication was cancelled while verifying inputs."
                )
            chunk = handle.read(_HASH_CHUNK_BYTES)
            if not chunk:
                break
            end = offset + len(chunk)
            if end > len(content) or chunk != content[offset:end]:
                matches = False
                break
            offset = end

    if (
        not matches
        or offset != len(content)
        or source_stat_signature(source) != expected_signature
    ):
        raise SNRPublicationError(
            f"Source workbook changed while SNR data were being read: "
            f"{source.name}. Restart generation after workbook writes have finished."
        )
    return snapshot.identity


def verify_source_identity(
    path: str | Path,
    *,
    expected_sha256: object,
    expected_size_bytes: object,
    cancellation_checkpoint: Callable[[], bool] | None = None,
) -> SourceFileIdentity:
    """Verify that publication sees the exact bytes captured during reading."""

    source = Path(path)
    digest = str(expected_sha256 or "").casefold()
    if not _SHA256_RE.fullmatch(digest):
        raise SNRPublicationError(
            "A contributing SNR workbook is missing its stable read-time "
            "content fingerprint."
        )
    try:
        expected_size = int(expected_size_bytes)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SNRPublicationError(
            "A contributing SNR workbook is missing its stable read-time file size."
        ) from exc
    try:
        before_hash = source_stat_signature(source)
    except OSError as exc:
        raise SNRPublicationError(
            f"A contributing SNR workbook is no longer readable: {source.name}"
        ) from exc
    if before_hash[2] != expected_size:
        raise SNRPublicationError(
            f"A contributing SNR workbook changed after it was read: {source.name}"
        )
    try:
        current = capture_stable_source_identity(
            source,
            expected_stat_signature=before_hash,
            cancellation_checkpoint=cancellation_checkpoint,
        )
    except OSError as exc:
        raise SNRPublicationError(
            f"A contributing SNR workbook changed while its identity was being "
            f"verified: {source.name}"
        ) from exc
    if current.sha256 != digest:
        raise SNRPublicationError(
            f"A contributing SNR workbook changed after it was read: {source.name}"
        )
    return current


def verify_source_identity_after_read(
    path: str | Path,
    *,
    before_read: SourceFileIdentity,
    cancellation_checkpoint: Callable[[], bool] | None = None,
) -> SourceFileIdentity:
    """Require identical stable file bytes and metadata across a source read."""

    source = Path(path)
    after_read = capture_stable_source_identity(
        source,
        cancellation_checkpoint=cancellation_checkpoint,
    )
    if (
        after_read.sha256 != before_read.sha256
        or after_read.stat_signature != before_read.stat_signature
    ):
        raise SNRPublicationError(
            f"Source workbook changed while SNR data were being read: "
            f"{source.name}. Restart generation after workbook writes have finished."
        )
    return before_read


__all__ = [
    "SNRPublicationCancelled",
    "SNRPublicationError",
    "SourceFileIdentity",
    "SourceWorkbookSnapshot",
    "capture_stable_source_identity",
    "capture_stable_source_snapshot",
    "sha256_file",
    "source_stat_signature",
    "verify_source_identity",
    "verify_source_identity_after_read",
    "verify_source_snapshot_after_read",
]

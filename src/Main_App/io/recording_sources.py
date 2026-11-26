"""Identity of the complete on-disk source recording, including companions."""

from __future__ import annotations

import hashlib
from pathlib import Path


def recording_source_files(path: str | Path) -> tuple[Path, ...]:
    source = Path(path)
    if source.suffix.lower() in {".vhdr", ".bvrh"}:
        from Main_App.io.brain_products_files import source_files

        return tuple(source_files(source))
    return (source,)


def recording_content_identity(source: Path) -> tuple[dict, ...]:
    """Read each admitted source once and snapshot its content and file metadata."""
    rows = []
    for path in recording_source_files(source):
        path = path.resolve(strict=True)
        before = path.stat()
        with path.open("rb") as stream:
            fingerprint = hashlib.file_digest(stream, "sha256").hexdigest()
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise OSError("Recording changed while its import identity was calculated.")
        rows.append({"path": str(path), "size": after.st_size, "mtime_ns": after.st_mtime_ns,
                     "ctime_ns": after.st_ctime_ns, "sha256": fingerprint})
    return tuple(rows)


def source_hashes_by_file(identity: tuple[dict, ...]) -> dict[str, str]:
    return {row["path"]: row["sha256"] for row in identity}


def companion_identity(path: str | Path) -> dict[str, object]:
    """Extend existing BDF signatures only for multi-file recordings.

    Include the header as well, so callers can compare one detached snapshot.
    The native reader validates referenced companions before returning them.
    """
    if Path(path).suffix.lower() not in {".vhdr", ".bvrh"}:
        return {}
    rows = []
    for source in recording_source_files(path):
        stat = source.stat()
        rows.append({
            "path": str(source.resolve()), "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "ctime_ns": stat.st_ctime_ns,
        })
    return {"recording_sources": rows}

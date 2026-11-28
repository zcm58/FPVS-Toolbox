"""Identity of the complete on-disk source recording, including companions."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def bdf_change_identity(path: Path, info: os.stat_result) -> dict[str, int]:
    """Identify replaced/changed BDFs in roster review without reading signal samples."""
    identity = {"device": info.st_dev, "inode": info.st_ino, "ctime_ns": info.st_ctime_ns}
    if os.name != "nt":
        return identity
    # Python's Windows st_ctime_ns is the creation time. FileBasicInfo also
    # exposes the last metadata/content change, even when mtime is preserved.
    from contextlib import closing

    import ntsecuritycon
    import pywintypes
    import win32con
    import win32file
    import winerror

    sharing = win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE
    try:
        handle = win32file.CreateFile(str(path), ntsecuritycon.FILE_READ_ATTRIBUTES, sharing, None,
                                     win32con.OPEN_EXISTING, win32con.FILE_ATTRIBUTE_NORMAL, None)
        with closing(handle):
            change = win32file.GetFileInformationByHandleEx(handle, win32file.FileBasicInfo)["ChangeTime"]
            identity["windows_change_ms"] = round(change.timestamp() * 1000)
    except pywintypes.error as exc:
        if exc.winerror not in {winerror.ERROR_INVALID_FUNCTION, winerror.ERROR_INVALID_PARAMETER,
                                winerror.ERROR_NOT_SUPPORTED}:
            raise OSError(f"Cannot read BDF file identity for {path.name}: {exc}") from exc
    return identity


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

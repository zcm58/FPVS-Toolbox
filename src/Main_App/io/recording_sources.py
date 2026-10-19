"""Identity of the complete on-disk source recording, including companions."""

from __future__ import annotations

from pathlib import Path


def recording_source_files(path: str | Path) -> tuple[Path, ...]:
    source = Path(path)
    if source.suffix.lower() in {".vhdr", ".bvrh"}:
        from Main_App.io.brain_products import source_files

        return tuple(source_files(source))
    return (source,)


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

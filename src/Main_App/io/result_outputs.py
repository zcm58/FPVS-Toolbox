"""Lightweight completion snapshots for native and historical result outputs."""

from __future__ import annotations

from pathlib import Path

from Main_App.Shared.file_filters import EXCEL_OUTPUT_SUFFIXES, is_excel_workbook_file
from Main_App.io.result_manifest import RESULT_MANIFEST_SUFFIX


def result_output_paths(output_root: Path | str | None) -> list[Path]:
    """Find published result anchors, excluding companions and temporary files.

    This is an output-write check, not dataset discovery or readiness validation.
    Native manifests are published last; their NPZ companions alone do not count.
    """
    if not output_root:
        return []
    root = Path(output_root)
    if not root.is_dir():
        return []
    suffixes = (RESULT_MANIFEST_SUFFIX, *EXCEL_OUTPUT_SUFFIXES)
    return sorted(
        path.resolve()
        for path in root.rglob("*")
        if is_excel_workbook_file(path, suffixes=suffixes) and path.is_file()
    )


def result_output_snapshot(output_root: Path | str | None) -> dict[str, tuple[int, int]]:
    """Record anchor modification time and size to distinguish current-run writes."""
    snapshot: dict[str, tuple[int, int]] = {}
    for path in result_output_paths(output_root):
        try:
            stat_result = path.stat()
        except OSError:
            continue
        snapshot[str(path)] = (int(stat_result.st_mtime_ns), int(stat_result.st_size))
    return snapshot

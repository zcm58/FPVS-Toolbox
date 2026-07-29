"""Console-level policy for Stats workflow diagnostics."""

from __future__ import annotations


_MISSING_FILE_MARKERS = (
    "missing file",
    "file is missing",
    "file not found",
    "missing workbook",
)


def stats_ide_log_level(message: str, requested_level: str) -> str:
    """Return the console level for a Stats message.

    The in-app Run log remains complete. The default IDE console shows missing
    files and errors while routine workflow messages remain available at DEBUG.
    """

    level = str(requested_level or "info").strip().lower()
    if level in {"error", "critical"}:
        return level
    if level == "exception":
        return "error"
    lowered = str(message or "").casefold()
    if any(marker in lowered for marker in _MISSING_FILE_MARKERS):
        return "warning"
    return "debug"


__all__ = ["stats_ide_log_level"]

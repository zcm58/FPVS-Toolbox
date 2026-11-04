"""Compact presentation of persisted processing history without Qt."""

from __future__ import annotations

from datetime import tzinfo

from Main_App.processing.processing_history import ProcessingHistoryStatus


def format_processing_history(
    status: ProcessingHistoryStatus, *, tz: tzinfo | None = None,
) -> str:
    """Show a local completion time and the successful participant count."""
    if status.state == "missing":
        return "No completed processing run recorded"
    run = status.latest_completed_run
    if status.state != "completed" or run is None:
        return "Processing history unavailable"
    try:
        local_time = run.timestamp.astimezone(tz)
    except (OSError, OverflowError, ValueError):
        # Extreme saved dates can exceed the local timezone/platform range.
        local_time = run.timestamp
    timestamp = f"{local_time:%d %b} {local_time.year:04d}, {local_time:%H:%M %Z}".strip()
    count = run.participant_count
    participants = (
        "participant count unavailable" if count is None
        else f"{count} participant{'s' if count != 1 else ''}"
    )
    prefix = "Last recorded completion" if status.history_incomplete else "Last completed processing"
    suffix = " (history incomplete)" if status.history_incomplete else ""
    return f"{prefix}: {timestamp} · {participants}{suffix}"

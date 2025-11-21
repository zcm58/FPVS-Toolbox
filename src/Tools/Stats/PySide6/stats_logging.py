from __future__ import annotations

from datetime import datetime
from typing import Final

from .stats_core import PipelineId, StepId


LOG_TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


def format_log_line(message: str, *, level: str = "INFO") -> str:
    timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
    lvl = (level or "INFO").upper()
    return f"[{timestamp}] [{lvl}] {message}"


def format_section_header(title: str) -> str:
    return f"==== {title} ===="


def format_step_event(
    pipeline: PipelineId, step: StepId, *, event: str, message: str
) -> str:
    return f"[{pipeline.name}] {step.name}: {event} — {message}"


__all__ = [
    "format_log_line",
    "format_section_header",
    "format_step_event",
    "LOG_TIMESTAMP_FORMAT",
]

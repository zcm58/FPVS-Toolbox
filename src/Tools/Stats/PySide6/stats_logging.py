from __future__ import annotations

from datetime import datetime
from typing import Final


LOG_TIMESTAMP_FORMAT: Final[str] = "%Y-%m-%d %H:%M:%S"


def format_log_line(message: str, *, level: str = "INFO") -> str:
    timestamp = datetime.now().strftime(LOG_TIMESTAMP_FORMAT)
    lvl = (level or "INFO").upper()
    return f"[{timestamp}] [{lvl}] {message}"


def format_section_header(title: str) -> str:
    return f"==== {title} ===="


__all__ = ["format_log_line", "format_section_header", "LOG_TIMESTAMP_FORMAT"]

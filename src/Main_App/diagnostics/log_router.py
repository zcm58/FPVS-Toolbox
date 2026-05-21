"""Central runtime logging routes for IDE, GUI, and worker-replayed records."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from Main_App.Shared.settings_paths import app_logs_dir


_STANDARD_LOG_RECORD_KEYS = set(
    logging.LogRecord(
        name="",
        level=0,
        pathname="",
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    ).__dict__
) | {"message", "asctime"}


class _StructuredExtraFormatter(logging.Formatter):
    """Append structured ``extra`` fields to the standard app log line."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_LOG_RECORD_KEYS and not key.startswith("_")
        }
        if not extras:
            return message
        extra_text = " ".join(
            f"{key}={self._format_extra_value(extras[key])}"
            for key in sorted(extras)
        )
        return f"{message} {extra_text}"

    @staticmethod
    def _format_extra_value(value: Any) -> str:
        if isinstance(value, str):
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            if not value or any(char.isspace() for char in value) or "=" in value:
                return f'"{escaped}"'
            return escaped
        return str(value)


def _log_dir() -> Path:
    return app_logs_dir()


def configure_logging(debug: bool) -> None:
    """Configure root logging for IDE/console and the app log file."""
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    if getattr(root, "_fpvs_configured", False):
        root.setLevel(level)
        return
    root.setLevel(level)

    fmt = _StructuredExtraFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    try:
        fh = logging.FileHandler(_log_dir() / "fpvs_toolbox.log", encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    root._fpvs_configured = True  # type: ignore[attr-defined]


def backend_log_allowed(*, debug_enabled: bool, level: int) -> bool:
    """Return whether a GUI-originated message should also reach IDE logging."""
    return bool(debug_enabled) or level >= logging.WARNING


def emit_backend_log(
    log: logging.Logger,
    *,
    level: int,
    message: str,
    debug_enabled: bool = False,
) -> None:
    """Route a GUI-originated message to Python logging when policy allows it."""
    if backend_log_allowed(debug_enabled=debug_enabled, level=level):
        log.log(level, message)


def gui_log_line(message: str, *, when: datetime | None = None) -> str:
    """Format one visible main-app GUI log line."""
    timestamp = (when or datetime.now()).strftime("%H:%M:%S.%f")[:-3]
    return f"{timestamp} [GUI]: {message}"


def emit_gui_log(
    host: Any,
    log: logging.Logger,
    *,
    message: str,
    level: int = logging.INFO,
) -> None:
    """Append to the main GUI log and route selected messages to IDE logging."""
    formatted = gui_log_line(message)
    text_log = getattr(host, "text_log", None)
    if text_log is not None:
        text_log.append(formatted)

    try:
        debug_enabled = bool(host.settings.debug_enabled())
    except Exception:
        debug_enabled = False
    emit_backend_log(
        log,
        level=level,
        message=message,
        debug_enabled=debug_enabled,
    )


def log_worker_timing_record(
    log: logging.Logger,
    *,
    file_name: str,
    record: dict[str, object],
) -> None:
    """Replay one structured worker timing record through the parent logger."""
    if record.get("source") == "excel":
        log.info(
            "[EXCEL TIMING] file=%s stage=%s elapsed_ms=%s sheet=%r rows=%s cols=%s path=%r",
            file_name,
            record.get("stage"),
            record.get("elapsed_ms"),
            record.get("sheet"),
            record.get("rows"),
            record.get("cols"),
            record.get("path"),
        )
        return

    log.info(
        "[EXPORT TIMING] file=%s stage=%s elapsed_ms=%s pid=%r condition=%r "
        "object_index=%s path=%r extra=%r",
        file_name,
        record.get("stage"),
        record.get("elapsed_ms"),
        record.get("pid"),
        record.get("condition"),
        record.get("object_index"),
        record.get("path"),
        record.get("extra"),
    )


def replay_worker_timing_records(
    log: logging.Logger,
    *,
    result: dict[str, object],
) -> None:
    """Replay timing records returned from child worker processes in the parent."""
    records = result.get("export_timing_records")
    if not isinstance(records, list):
        return

    file_name = Path(str(result.get("file", "unknown"))).name
    for record in records:
        if isinstance(record, dict):
            log_worker_timing_record(log, file_name=file_name, record=record)

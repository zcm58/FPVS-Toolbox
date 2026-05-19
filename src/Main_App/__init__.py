"""Top-level package for the FPVS Toolbox."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from Main_App.Shared.settings_paths import app_logs_dir

# -----------------------------
# PySide6-native utilities
# -----------------------------

class _SettingsProxy:
    """Minimal settings facade for boot-time needs."""

    def debug_enabled(self) -> bool:
        # Env wins for easy override; else read the central SettingsManager.
        env = os.getenv("FPVS_DEBUG", "").strip().lower()
        if env in {"1", "true", "yes", "on"}:
            return True
        if env in {"0", "false", "no", "off"}:
            return False
        try:
            from Main_App.Shared.settings_manager import SettingsManager

            return SettingsManager().debug_enabled()
        except Exception:
            return False


def get_settings() -> _SettingsProxy:
    """Return a lightweight settings proxy for boot-time checks."""
    return _SettingsProxy()


def _log_dir() -> Path:
    return app_logs_dir()


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


def configure_logging(debug: bool) -> None:
    """Configure root logging without Legacy dependencies."""
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    # Prevent duplicate handlers on repeated configure calls.
    if getattr(root, "_fpvs_configured", False):
        root.setLevel(level)
        return
    root.setLevel(level)

    fmt = _StructuredExtraFormatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    # File handler
    try:
        fh = logging.FileHandler(_log_dir() / "fpvs_toolbox.log", encoding="utf-8")
        fh.setLevel(level)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass

    # Console handler (useful for --console builds)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    root._fpvs_configured = True  # type: ignore[attr-defined]


def install_messagebox_logger(debug: bool) -> None:
    """Optional UI error surface. No-op until a QApplication exists."""
    if not debug:
        return
    # Lightweight handler that emits to console only; keep UI decoupled here.
    # If you want QMessageBox on errors, wire it inside the PySide6 StatusBar or main window.


# Re-export Project API from the canonical project import surface.
from .projects import Project  # noqa: E402  (safe, no Legacy)

__all__ = [
    # PySide6-first exports
    "get_settings",
    "configure_logging",
    "install_messagebox_logger",
    "Project",
]

def SettingsManager(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    from Main_App.Shared.settings_manager import SettingsManager as _SharedSettingsManager

    return _SharedSettingsManager(*args, **kwargs)

def ProcessingMixin(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    from Main_App.Shared.processing_mixin import ProcessingMixin as _SharedProcessingMixin

    return _SharedProcessingMixin(*args, **kwargs)

def load_eeg_file(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    from Main_App.io.load_utils import load_eeg_file as _load_eeg_file

    return _load_eeg_file(*args, **kwargs)

def perform_preprocessing(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    from Main_App.processing.preprocess import (
        perform_preprocessing as _perform_preprocessing,
    )

    return _perform_preprocessing(*args, **kwargs)

def preprocess_raw(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    raise RuntimeError("Legacy preprocess_raw has been quarantined; use the PySide6 preprocessing path.")

def post_process(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    from Main_App.Shared.post_process import post_process as _shared_post_process

    return _shared_post_process(*args, **kwargs)

# Maintain active compatibility names in __all__ while Legacy_App is retired.
__all__ += [
    "SettingsManager",
    "ProcessingMixin",
    "load_eeg_file",
    "perform_preprocessing",
    "preprocess_raw",
    "post_process",
]

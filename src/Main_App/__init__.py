"""Top-level package for the FPVS Toolbox (PySide6-first, no Legacy on import).

This module exposes PySide6-safe utilities and lazy wrappers for Legacy UI so
that launching the PySide6 app never imports Main_App/Legacy_App/**.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

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


def configure_logging(debug: bool) -> None:
    """Configure root logging without Legacy dependencies."""
    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    # Prevent duplicate handlers on repeated configure calls.
    if getattr(root, "_fpvs_configured", False):
        root.setLevel(level)
        return
    root.setLevel(level)

    fmt = logging.Formatter(
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


# Re-export Project API from PySide6 backend
from .PySide6_App.Backend import Project  # noqa: E402  (safe, no Legacy)

__all__ = [
    # PySide6-first exports
    "get_settings",
    "configure_logging",
    "install_messagebox_logger",
    "Project",
]

# -------------------------------------------------
# Lazy wrappers for Legacy modules (CTk UI, etc.)
# These DO NOT import Legacy on module import.
# They only import when called explicitly.
# -------------------------------------------------

def _lazy_import(module: str, name: Optional[str] = None) -> Any:  # pragma: no cover
    mod = __import__(f"{__name__}.Legacy_App.{module}", fromlist=[name] if name else [])
    return getattr(mod, name) if name else mod

def SettingsManager(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    from Main_App.Shared.settings_manager import SettingsManager as _SharedSettingsManager

    return _SharedSettingsManager(*args, **kwargs)

def SettingsWindow(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    return _lazy_import("settings_window", "SettingsWindow")(*args, **kwargs)

def RelevantPublicationsWindow(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    return _lazy_import("relevant_publications_window", "RelevantPublicationsWindow")(*args, **kwargs)

def AppMenuBar(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    return _lazy_import("menu_bar", "AppMenuBar")(*args, **kwargs)

def SetupPanelManager(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    return _lazy_import("ui_setup_panels", "SetupPanelManager")(*args, **kwargs)

def EventMapManager(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
    return _lazy_import("ui_event_map_manager", "EventMapManager")(*args, **kwargs)

class EventMapMixin:  # pragma: no cover
    def __init_subclass__(cls, **kw: Any) -> None:
        raise RuntimeError("Legacy mixin not available at import; import explicitly from Legacy_App.event_map_utils")

class FileSelectionMixin:  # pragma: no cover
    def __init_subclass__(cls, **kw: Any) -> None:
        raise RuntimeError("Legacy mixin not available at import; import explicitly from Legacy_App.file_selection")

class EventDetectionMixin:  # pragma: no cover
    def __init_subclass__(cls, **kw: Any) -> None:
        raise RuntimeError("Legacy mixin not available at import; import explicitly from Legacy_App.event_detection")

class ValidationMixin:  # pragma: no cover
    def __init_subclass__(cls, **kw: Any) -> None:
        raise RuntimeError("Legacy ValidationMixin has been quarantined; use the PySide6 validation path.")

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

# Maintain legacy names in __all__ for external imports, but keep them lazy.
__all__ += [
    "SettingsManager",
    "SettingsWindow",
    "RelevantPublicationsWindow",
    "AppMenuBar",
    "SetupPanelManager",
    "EventMapManager",
    "EventMapMixin",
    "FileSelectionMixin",
    "EventDetectionMixin",
    "ValidationMixin",
    "ProcessingMixin",
    "load_eeg_file",
    "perform_preprocessing",
    "preprocess_raw",
    "post_process",
]

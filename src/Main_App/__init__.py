"""Top-level package for the FPVS Toolbox."""

from __future__ import annotations

import os
from typing import Any

from Main_App.diagnostics.log_router import (
    _StructuredExtraFormatter,  # noqa: F401 - compatibility re-export for tests/tools
    configure_logging,
)

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

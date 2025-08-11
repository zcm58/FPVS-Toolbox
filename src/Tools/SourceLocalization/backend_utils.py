""""Utilities for managing the MNE 3D backend."""

from __future__ import annotations

import os
import logging
import importlib
import mne

logger = logging.getLogger(__name__)


def _log_backend_imports() -> None:
    """Log backend import information when debug mode is enabled."""
    try:
        from Main_App import SettingsManager
    except Exception:
        return

    if not SettingsManager().debug_enabled():
        return

    for mod_name in ("pyvistaqt", "pyvista", "PySide6"):
        try:
            module = importlib.import_module(mod_name)
            version = getattr(module, "__version__", "unknown")
            path = getattr(module, "__file__", "built-in")
            logger.debug("Import OK: %s %s (%s)", mod_name, version, path)
        except Exception as err:  # pragma: no cover - optional
            logger.debug("Import failed: %s (%s)", mod_name, err)


def _ensure_pyvista_backend() -> None:
    """Force the MNE 3D backend to PyVista/PyVistaQt if possible."""
    if not hasattr(mne.viz, "set_3d_backend"):
        return

    _log_backend_imports()

    current = None
    if hasattr(mne.viz, "get_3d_backend"):
        try:
            current = mne.viz.get_3d_backend()
            logger.debug("Existing MNE 3D backend: %s", current)
        except Exception:
            current = None
    if current in {"pyvistaqt", "pyvista"}:
        return

    # Prefer Qt interactor when GUI is present
    for backend in ("pyvistaqt", "pyvista"):
        logger.debug("Attempting backend %s", backend)
        try:
            os.environ.setdefault("MNE_3D_BACKEND", backend)
            mne.viz.set_3d_backend(backend)
            if hasattr(mne.viz, "get_3d_backend"):
                logger.debug("Backend after set: %s", mne.viz.get_3d_backend())
        except Exception as err:  # pragma: no cover - optional
            logger.debug("Failed to set backend %s: %s", backend, err)
            continue
        if hasattr(mne.viz, "get_3d_backend") and mne.viz.get_3d_backend() == backend:
            logger.debug("Using 3D backend %s", backend)
            return

    msg = "PyVista backend ('pyvistaqt' or 'pyvista') is required"
    logger.error(msg)
    raise RuntimeError(msg)


def get_current_backend() -> str:
    """Return the currently active MNE 3D backend."""
    backend = None
    if hasattr(mne.viz, "get_3d_backend"):
        try:
            backend = mne.viz.get_3d_backend()
        except Exception:
            backend = None
    if not backend:
        backend = os.environ.get("MNE_3D_BACKEND", "")
    return str(backend).lower()


def is_pyvistaqt_backend() -> bool:
    """Check if the PyVistaQt backend is active."""
    return get_current_backend() == "pyvistaqt"


def is_pyvista_backend() -> bool:
    """Check if the non-Qt PyVista backend is active."""
    return get_current_backend() == "pyvista"

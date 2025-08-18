# SourceLocalization/backend_utils.py
"""Utilities for managing and querying the MNE 3D visualization backend.

Notes
-----
- Keeps behavior identical, only fixes a syntax error and adds small robustness.
- No UI code here; just logging + backend detection/selection helpers.
"""

from __future__ import annotations

import importlib
import logging
import os
from typing import Optional

import mne

logger = logging.getLogger(__name__)


def _log_backend_imports() -> None:
    """Log backend import information when debug mode is enabled."""
    try:
        from Main_App import SettingsManager  # type: ignore
    except Exception:
        return

    try:
        debug_enabled = SettingsManager().debug_enabled()
    except Exception:
        debug_enabled = False

    if not debug_enabled:
        return

    for mod_name in ("pyvistaqt", "pyvista", "PySide6"):
        try:
            module = importlib.import_module(mod_name)
            version = getattr(module, "__version__", "unknown")
            path = getattr(module, "__file__", "built-in")
            logger.debug("backend_import_ok", extra={"module": mod_name, "version": version, "path": path})
        except Exception as err:  # pragma: no cover - optional
            logger.debug("backend_import_fail", extra={"module": mod_name, "error": str(err)})


def _get_backend_from_mne() -> Optional[str]:
    """Safely get the backend from MNE if available."""
    backend: Optional[str] = None
    if hasattr(mne.viz, "get_3d_backend"):
        try:
            backend = mne.viz.get_3d_backend()
        except Exception:
            backend = None
    return backend


def _ensure_pyvista_backend() -> None:
    """Force the MNE 3D backend to PyVista/PyVistaQt if possible."""
    if not hasattr(mne.viz, "set_3d_backend"):
        return

    _log_backend_imports()

    current = _get_backend_from_mne()
    if current:
        logger.debug("mne_backend_current", extra={"backend": current})
    if current in {"pyvistaqt", "pyvista"}:
        return

    # Prefer Qt interactor when GUI is present
    for backend in ("pyvistaqt", "pyvista"):
        logger.debug("mne_backend_try_set", extra={"backend": backend})
        try:
            os.environ.setdefault("MNE_3D_BACKEND", backend)
            mne.viz.set_3d_backend(backend)
            after = _get_backend_from_mne()
            logger.debug("mne_backend_after_set", extra={"backend": after})
        except Exception as err:  # pragma: no cover - optional
            logger.debug("mne_backend_set_failed", extra={"backend": backend, "error": str(err)})
            continue
        if _get_backend_from_mne() == backend:
            logger.debug("mne_backend_in_use", extra={"backend": backend})
            return

    msg = "PyVista backend ('pyvistaqt' or 'pyvista') is required"
    logger.error("mne_backend_required", extra={"message": msg})
    raise RuntimeError(msg)


def get_current_backend() -> str:
    """Return the currently active MNE 3D backend (lowercase; '' if unknown)."""
    backend = _get_backend_from_mne()
    if not backend:
        backend = os.environ.get("MNE_3D_BACKEND", "") or ""
    return str(backend).lower()


def is_pyvistaqt_backend() -> bool:
    """Check if the PyVistaQt backend is active."""
    return get_current_backend() == "pyvistaqt"


def is_pyvista_backend() -> bool:
    """Check if the non-Qt PyVista backend is active."""
    return get_current_backend() == "pyvista"

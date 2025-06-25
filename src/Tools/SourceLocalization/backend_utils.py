"""Utilities for managing the MNE 3D backend."""

from __future__ import annotations

import os
import logging
import mne

logger = logging.getLogger(__name__)


def _ensure_pyvista_backend() -> None:
    """Force the MNE 3D backend to PyVista."""
    if not hasattr(mne.viz, "set_3d_backend"):
        return

    logger.debug("MNE_3D_BACKEND: %s", os.environ.get("MNE_3D_BACKEND"))
    logger.debug("QT_API: %s", os.environ.get("QT_API"))
    logger.debug("QT_QPA_PLATFORM: %s", os.environ.get("QT_QPA_PLATFORM"))
    current = None
    if hasattr(mne.viz, "get_3d_backend"):
        current = mne.viz.get_3d_backend()
        logger.debug("Existing MNE 3D backend: %s", current)
    if current in {"pyvistaqt", "pyvista"}:
        return

    for backend in ("pyvistaqt", "pyvista"):
        logger.debug("Attempting backend %s", backend)
        try:
            mne.viz.set_3d_backend(backend)
            os.environ["MNE_3D_BACKEND"] = backend
            if hasattr(mne.viz, "get_3d_backend"):
                logger.debug("Backend after set: %s", mne.viz.get_3d_backend())
        except Exception as err:  # pragma: no cover - optional
            logger.debug("Failed to set backend %s: %s", backend, err)
            continue
        if not hasattr(mne.viz, "get_3d_backend"):
            return
        if mne.viz.get_3d_backend() == backend:
            logger.debug("Using 3D backend %s", backend)
            return

    msg = "PyVista backend ('pyvistaqt' or 'pyvista') is required"
    logger.error(msg, exc_info=True)
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
    """Alias for :func:`is_pyvistaqt_backend`."""
    return is_pyvistaqt_backend()

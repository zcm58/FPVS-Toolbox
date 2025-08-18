from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Callable

import mne
import numpy as np
import pyvista as pv
from mne.datasets import fetch_fsaverage
from mne.surface import read_surface
from PySide6 import QtWidgets

from Main_App import SettingsManager
from Tools.SourceLocalization.data_utils import _resolve_subjects_dir
from Tools.SourceLocalization.logging_utils import get_pkg_logger

log = get_pkg_logger()
logger = logging.getLogger(__name__)


def _derive_title(path: str) -> str:
    name = os.path.basename(path)
    for suffix in ("-lh.stc", "-rh.stc", "-lh", "-rh"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return f"{name} Response"


def view_source_estimate_pyvista(
    stc: mne.BaseSourceEstimate,
    subjects_dir: str,
    time_idx: int,
    cortex_alpha: float,
    show_cortex: bool = True,
) -> pv.Plotter:
    """Plot source estimate heatmap with optional semi-transparent cortex."""
    log.debug("ENTER view_source_estimate_pyvista")
    subj = getattr(stc, "subject", None) or "fsaverage"
    surf_dir = Path(subjects_dir) / subj / "surf"

    verts_lh, faces_lh = read_surface(surf_dir / "lh.pial")
    verts_rh, faces_rh = read_surface(surf_dir / "rh.pial")

    def _fmt(f: np.ndarray) -> np.ndarray:
        # PyVista needs a leading count column (all triangles → 3)
        return np.hstack([np.full((f.shape[0], 1), 3), f]).astype(np.int64)

    mesh_lh = pv.PolyData(verts_lh, _fmt(faces_lh))
    mesh_rh = pv.PolyData(verts_rh, _fmt(faces_rh))

    pl = pv.Plotter(window_size=(900, 700))
    pl.set_background("white")
    try:
        pl.enable_depth_peeling()
    except Exception:
        pass  # backend/driver dependent

    if show_cortex:
        cortex_mesh = mesh_lh.copy().merge(mesh_rh)
        pl.add_mesh(cortex_mesh, color="lightgray", opacity=cortex_alpha, name="cortex")

    # Build heat layers
    h_lh = mesh_lh.copy()
    h_rh = mesh_rh.copy()
    h_lh.point_data["activation"] = np.full(h_lh.n_points, np.nan)
    h_rh.point_data["activation"] = np.full(h_rh.n_points, np.nan)

    # Fill current time frame
    scalar = stc.data
    if getattr(stc, "is_vector", False) or scalar.ndim == 3:
        scalar = np.linalg.norm(scalar, axis=-1)  # (n_verts, n_times)
    frame = np.abs(scalar[:, time_idx])
    n_lh = len(stc.vertices[0])
    arr_lh = np.full(h_lh.n_points, np.nan)
    arr_rh = np.full(h_rh.n_points, np.nan)
    arr_lh[stc.vertices[0]] = frame[:n_lh]
    arr_rh[stc.vertices[1]] = frame[n_lh:]

    h_lh.point_data["activation"] = arr_lh
    h_rh.point_data["activation"] = arr_rh

    vmax = float(np.nanmax(frame)) or 1.0
    clim = (0.0, vmax)

    pl.add_mesh(
        h_lh, scalars="activation", cmap="hot", nan_opacity=0.0, opacity=1.0, clim=clim, name="act_lh"
    )
    pl.add_mesh(
        h_rh, scalars="activation", cmap="hot", nan_opacity=0.0, opacity=1.0, clim=clim, name="act_rh"
    )
    pl.add_scalar_bar(title="|Source| Amplitude", n_colors=8)
    log.debug("EXIT view_source_estimate_pyvista")
    return pl


def view_source_estimate(
    stc_path: str,
    threshold: Optional[float] = None,
    alpha: Optional[float] = None,
    time_ms: Optional[float] = None,
    window_title: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
    show_cortex: Optional[bool] = None,
) -> pv.Plotter | None:
    """Load STC, apply threshold/alpha settings, then render via PyVista."""
    if log_func is None:
        log_func = log.info
    log.debug("ENTER view_source_estimate", extra={"path": stc_path})
    try:
        stc = mne.read_source_estimate(stc_path)

        settings = SettingsManager()
        debug = settings.debug_enabled()

        # Threshold (fraction of abs max or absolute)
        thr_val = threshold
        if thr_val is None:
            try:
                thr_val = float(settings.get("visualization", "threshold", fallback=0.0))
            except Exception:
                thr_val = 0.0
        if thr_val and thr_val > 0:
            if 0 < thr_val < 1:
                cutoff = float(thr_val) * float(np.abs(stc.data).max())
            else:
                cutoff = float(thr_val)
            stc = stc.copy()
            stc._data[np.abs(stc.data) < cutoff] = 0.0
            if debug:
                log.debug("Applied threshold cutoff=%.4e", cutoff)

        # Alpha & cortex visibility
        gui_alpha = 0.5
        try:
            gui_alpha = float(settings.get("visualization", "surface_opacity", fallback=0.5))
        except Exception:
            pass
        cortex_alpha = float(alpha) if alpha is not None else gui_alpha

        show_brain_mesh = settings.get("visualization", "show_brain_mesh", "True").lower() == "true"
        if show_cortex is not None:
            show_brain_mesh = bool(show_cortex)

        # Subjects dir
        mri_path = settings.get("loreta", "mri_path", fallback="")
        stored = Path(mri_path).resolve() if mri_path else None
        subjects_dir = str(_resolve_subjects_dir(stored, stc.subject or "fsaverage"))
        if not Path(subjects_dir).exists():
            subjects_dir = str(fetch_fsaverage(verbose=False).parent)

        # Time index
        if time_ms is None:
            try:
                time_ms = float(settings.get("visualization", "time_index_ms", "150"))
            except Exception:
                time_ms = 150.0
        time_idx = int(round((time_ms / 1000.0 - stc.tmin) / stc.tstep))
        time_idx = max(0, min(time_idx, stc.data.shape[1] - 1))

        pl = view_source_estimate_pyvista(
            stc, subjects_dir, time_idx, cortex_alpha, show_brain_mesh
        )
        kwargs = {"title": window_title or _derive_title(stc_path)}
        app = QtWidgets.QApplication.instance()
        has_app = app is not None
        if has_app:
            kwargs.update(
                {"interactive": False, "auto_close": False, "window_size": (900, 700)}
            )
            log.debug("pv_plotter_show", extra={"has_app": True, "blocking": False, **kwargs})
            pl.show(**kwargs)
        else:
            log.debug("pv_plotter_show", extra={"has_app": False, "blocking": True, **kwargs})
            pl.show(**kwargs)
        log.debug("EXIT view_source_estimate", extra={"path": stc_path})
        return pl

    except Exception as err:
        log_func(f"ERROR plotting STC: {err}")
        log.exception("view_source_estimate_failed", extra={"path": stc_path})
        log.debug("EXIT view_source_estimate", extra={"path": stc_path})
        return None

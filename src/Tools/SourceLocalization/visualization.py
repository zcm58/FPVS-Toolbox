# src/Tools/SourceLocalization/visualization.py
from __future__ import annotations
import os
import logging
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import pyvista as pv
import mne
from mne.surface import read_surface
from mne.datasets import fetch_fsaverage

from .data_utils import _resolve_subjects_dir
from Main_App import SettingsManager

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
        pass  # depth peeling is backend/driver dependent

    if show_cortex:
        cortex_mesh = mesh_lh.copy().merge(mesh_rh)
        pl.add_mesh(
            cortex_mesh,
            color="lightgray",
            opacity=cortex_alpha,
            ambient=1.0,
            diffuse=0.0,
            specular=0.0,
            name="cortex",
        )

    # Prepare activation (abs magnitude for sequential cmap)
    frame = np.abs(stc.data[:, time_idx])
    n_lh = len(stc.vertices[0])
    act_lh = np.full(mesh_lh.n_points, np.nan)
    act_rh = np.full(mesh_rh.n_points, np.nan)
    act_lh[stc.vertices[0]] = frame[:n_lh]
    act_rh[stc.vertices[1]] = frame[n_lh:]

    # Robust vmax across hemispheres (avoid object-array nanmax pitfall)
    vmax = max(
        float(np.nanmax(act_lh)) if np.any(~np.isnan(act_lh)) else 0.0,
        float(np.nanmax(act_rh)) if np.any(~np.isnan(act_rh)) else 0.0,
    )
    clim = (0.0, vmax if vmax > 0 else 1.0)

    h_lh = mesh_lh.copy()
    h_lh.point_data["activation"] = act_lh
    h_rh = mesh_rh.copy()
    h_rh.point_data["activation"] = act_rh

    # Slight offset to avoid z-fighting
    try:
        for h in (h_lh, h_rh):
            normals = h.point_normals  # triggers computation if missing
            h.points = h.points + normals * 1e-2
    except Exception:
        pass

    pl.add_mesh(
        h_lh,
        scalars="activation",
        cmap="hot",
        nan_opacity=0.0,
        opacity=1.0,
        clim=clim,
        name="act_lh",
    )
    pl.add_mesh(
        h_rh,
        scalars="activation",
        cmap="hot",
        nan_opacity=0.0,
        opacity=1.0,
        clim=clim,
        name="act_rh",
    )
    pl.add_scalar_bar(title="|Source| Amplitude", n_colors=8)
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
    """Load STC, apply threshold & alpha settings, then render via PyVista."""
    if log_func is None:
        log_func = logger.info
    try:
        stc = mne.read_source_estimate(stc_path)

        settings = SettingsManager()
        debug = settings.debug_enabled()

        # Threshold (fraction against abs max or absolute)
        thr_val = threshold
        if thr_val is None:
            try:
                thr_val = float(
                    settings.get("visualization", "threshold", fallback=0.0)
                )
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
                logger.debug("Applied threshold cutoff=%.4e", cutoff)

        # Alpha & cortex visibility
        gui_alpha = 0.5
        try:
            gui_alpha = float(
                settings.get("visualization", "surface_opacity", fallback=0.5)
            )
        except Exception:
            pass
        cortex_alpha = float(alpha) if alpha is not None else gui_alpha

        show_brain_mesh = (
            settings.get("visualization", "show_brain_mesh", "True").lower() == "true"
        )
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
        pl.show(title=window_title or _derive_title(stc_path))
        return pl

    except Exception as err:
        log_func(f"ERROR plotting STC: {err}")
        return None

# src/Tools/SourceLocalization/visualization.py
from __future__ import annotations
import os
import logging
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import pyvista as pv
from mne.surface import read_surface
from mne.datasets import fetch_fsaverage
from mne.source_estimate import _BaseSourceEstimate

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
    stc: _BaseSourceEstimate,
    subjects_dir: str,
    time_idx: int,
    cortex_alpha: float,
    show_cortex: bool = True,
) -> pv.Plotter:
    """Plot source estimate heatmap with optional semi-transparent cortex."""
    subj = getattr(stc, 'subject', None) or 'fsaverage'
    surf_dir = Path(subjects_dir) / subj / 'surf'

    verts_lh, faces_lh = read_surface(surf_dir / 'lh.pial')
    verts_rh, faces_rh = read_surface(surf_dir / 'rh.pial')

    def _fmt(f): return np.hstack([np.full((f.shape[0], 1), 3), f]).astype(np.int64)
    mesh_lh = pv.PolyData(verts_lh, _fmt(faces_lh))
    mesh_rh = pv.PolyData(verts_rh, _fmt(faces_rh))

    pl = pv.Plotter(window_size=(900, 700))
    pl.set_background('white')
    pl.enable_depth_peeling()

    if show_cortex:
        cortex_mesh = mesh_lh.copy().merge(mesh_rh)
        pl.add_mesh(
            cortex_mesh, color='lightgray', opacity=cortex_alpha,
            ambient=1.0, diffuse=0.0, specular=0.0, name='cortex'
        )

    # Prepare activation (abs magnitude for sequential cmap)
    data_frame = np.abs(stc.data[:, time_idx])
    n_lh = len(stc.vertices[0])
    act_lh = np.full(mesh_lh.n_points, np.nan)
    act_rh = np.full(mesh_rh.n_points, np.nan)
    act_lh[stc.vertices[0]] = data_frame[:n_lh]
    act_rh[stc.vertices[1]] = data_frame[n_lh:]

    vmax = float(np.nanmax([act_lh, act_rh]))
    clim = (0.0, vmax if vmax > 0 else 1.0)

    h_lh = mesh_lh.copy()
    h_lh.point_data['activation'] = act_lh
    h_rh = mesh_rh.copy()
    h_rh.point_data['activation'] = act_rh

    # Slight offset to avoid z-fighting
    for h in (h_lh, h_rh):
        normals = h.point_normals
        h.points = h.points + normals * 1e-2

    pl.add_mesh(h_lh, scalars='activation', cmap='hot', nan_opacity=0.0, opacity=1.0, clim=clim, name='act_lh')
    pl.add_mesh(h_rh, scalars='activation', cmap='hot', nan_opacity=0.0, opacity=1.0, clim=clim, name='act_rh')
    pl.add_scalar_bar(title='|Source| Amplitude', n_colors=8)
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
        import mne
        stc = mne.read_source_estimate(stc_path)

        settings = SettingsManager()
        debug = settings.debug_enabled()

        # Threshold (fraction against abs max or absolute)
        thr = threshold if threshold is not None else float(settings.get('visualization', 'threshold', fallback=0.0))
        if thr and thr > 0:
            if 0 < thr < 1:
                cutoff = thr * float(np.abs(stc.data).max())
            else:
                cutoff = float(thr)
            stc = stc.copy()
            mask = np.abs(stc.data) < cutoff
            stc._data[mask] = 0.0
            if debug:
                logger.debug("Applied threshold cutoff=%.4e", cutoff)

        # Alpha & cortex visibility
        gui_alpha = float(settings.get('visualization', 'surface_opacity', fallback=0.5))
        cortex_alpha = float(alpha) if alpha is not None else gui_alpha
        show_brain_mesh = settings.get('visualization', 'show_brain_mesh', 'True').lower() == 'true'
        if show_cortex is not None:
            show_brain_mesh = show_cortex

        # Subjects dir
        mri_path = settings.get('loreta', 'mri_path', fallback='')
        stored = Path(mri_path).resolve() if mri_path else None
        subjects_dir = str(_resolve_subjects_dir(stored, stc.subject or 'fsaverage'))
        if not Path(subjects_dir).exists():
            subjects_dir = str(fetch_fsaverage(verbose=False).parent)

        # Time index
        if time_ms is None:
            try:
                time_ms = float(settings.get('visualization', 'time_index_ms', '150'))
            except Exception:
                time_ms = 150.0
        time_idx = int(round((time_ms / 1000 - stc.tmin) / stc.tstep))
        time_idx = max(0, min(time_idx, stc.data.shape[1] - 1))

        pl = view_source_estimate_pyvista(
            stc, subjects_dir, time_idx, cortex_alpha, show_brain_mesh
        )
        pl.show(title=window_title or _derive_title(stc_path))
        return pl

    except Exception as err:
        log_func(f"ERROR plotting STC: {err}")
        return None

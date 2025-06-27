# src/Tools/SourceLocalization/visualization.py

from __future__ import annotations
import os
import logging
import traceback
from pathlib import Path
from typing import Optional, Callable

import numpy as np
import pyvista as pv
from mne.surface import read_surface
from mne.datasets import fetch_fsaverage
from mne.source_estimate import _BaseSourceEstimate
from tkinter import messagebox

from .data_utils import _resolve_subjects_dir
from Main_App.settings_manager import SettingsManager

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
    atlas_alpha: float,
) -> pv.Plotter:
    """Plot semi-transparent cortex and opaque activation spots in separate actors."""
    subj = getattr(stc, 'subject', None) or 'fsaverage'
    surf_dir = Path(subjects_dir) / subj / 'surf'

    # Load pial surfaces
    verts_lh, faces_lh = read_surface(surf_dir / 'lh.pial')
    verts_rh, faces_rh = read_surface(surf_dir / 'rh.pial')
    def _fmt(f): return np.hstack([np.full((f.shape[0],1),3), f]).astype(np.int64)
    mesh_lh = pv.PolyData(verts_lh, _fmt(faces_lh))
    mesh_rh = pv.PolyData(verts_rh, _fmt(faces_rh))

    # Create plotter and enable depth peeling
    pl = pv.Plotter(window_size=(800,600))
    pl.set_background('white')
    pl.enable_depth_peeling()

    # Combine hemispheres into one mesh
    cortex_mesh = mesh_lh.copy().merge(mesh_rh)
    pl.add_mesh(
        cortex_mesh,
        color='lightgray',
        opacity=cortex_alpha,
        ambient=1.0,
        diffuse=0.0,
        specular=0.0,
        name='cortex'
    )

    # Prepare activation data per hemisphere
    data = stc.data[:, time_idx]
    n_lh = len(stc.vertices[0])
    for hemi, mesh, verts in [('lh', mesh_lh, stc.vertices[0]),
                              ('rh', mesh_rh, stc.vertices[1])]:
        act = np.zeros(mesh.n_points)
        vals = data[:n_lh] if hemi == 'lh' else data[n_lh:]
        act[verts] = vals
        # Use NaN for zero so unmapped points are fully transparent
        act_mask = act == 0
        act[act_mask] = np.nan
        heatmap = mesh.copy()
        # Slightly offset points along normals to avoid z-fighting
        normals = heatmap.point_normals
        heatmap.points = heatmap.points + normals * 1e-2
        heatmap.point_data['activation'] = act
        if np.any(~act_mask):
            pl.add_mesh(
                heatmap,
                scalars='activation',
                cmap='hot',
                nan_opacity=0.0,
                opacity=1.0,
                name=f'act_{hemi}'
            )

    pl.add_scalar_bar(title='Source Amplitude', n_colors=8)

    # Debug actor properties
    try:
        actors = list(pl.renderer.actors.values())
        logger.debug(f"Total actors: {len(actors)}")
        for idx, actor in enumerate(actors):
            prop = actor.GetProperty()
            mapper = actor.GetMapper()
            vis = mapper.GetScalarVisibility() if mapper else False
            logger.debug(f"Actor[{idx}] opacity={prop.GetOpacity()}, scalarVis={vis}")
    except Exception:
        logger.exception("Actor introspection failed")

    return pl


def view_source_estimate(
    stc_path: str,
    threshold: Optional[float] = None,
    alpha: Optional[float] = None,
    window_title: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
) -> pv.Plotter | None:
    """Load STC, apply threshold & alpha settings, then render via PyVista."""
    if log_func is None:
        log_func = logger.info
    log_func(f"Visualizing STC: {os.path.basename(stc_path)} (α={alpha if alpha is not None else 'gui'})")
    try:
        import mne
        stc = mne.read_source_estimate(stc_path)

        # Threshold data
        settings = SettingsManager()
        thr = threshold if threshold is not None else settings.get('visualization', 'threshold', fallback=0.0)
        if thr > 0:
            stc = stc.copy()
            val = thr * float(stc.data.max()) if 0 < thr < 1 else thr
            stc.data[(stc.data < val) & (stc.data > -val)] = 0

        # Determine alpha
        gui_alpha = settings.get('visualization', 'surface_opacity', fallback=0.5)
        cortex_alpha = alpha if alpha is not None else gui_alpha

        # Resolve subjects_dir
        mri_path = settings.get('loreta', 'mri_path', fallback='')
        stored = Path(mri_path).resolve() if mri_path else None
        subjects_dir = str(_resolve_subjects_dir(stored, stc.subject or 'fsaverage'))
        if not Path(subjects_dir).exists():
            subjects_dir = str(fetch_fsaverage(verbose=False).parent)

        time_idx = settings.get('visualization', 'time_index', fallback=0)
        pl = view_source_estimate_pyvista(stc, subjects_dir, time_idx, cortex_alpha, cortex_alpha)
        pl.show(title=window_title or _derive_title(stc_path))
        return pl
    except Exception as err:
        log_func(f"ERROR plotting STC: {err}\n{traceback.format_exc()}")
        messagebox.showerror('Visualization Error', f"Could not generate 3D brain plot.\nError: {err}")
        return None

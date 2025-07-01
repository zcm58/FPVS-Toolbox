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
        atlas_alpha: float,  # This argument is not currently used but is kept for API consistency
) -> pv.Plotter:
    """Plot semi-transparent cortex and opaque activation spots in separate actors."""
    subj = getattr(stc, 'subject', None) or 'fsaverage'
    surf_dir = Path(subjects_dir) / subj / 'surf'

    # Load pial surfaces
    verts_lh, faces_lh = read_surface(surf_dir / 'lh.pial')
    verts_rh, faces_rh = read_surface(surf_dir / 'rh.pial')

    def _fmt(f):
        return np.hstack([np.full((f.shape[0], 1), 3), f]).astype(np.int64)

    mesh_lh = pv.PolyData(verts_lh, _fmt(faces_lh))
    mesh_rh = pv.PolyData(verts_rh, _fmt(faces_rh))

    # Create plotter and enable depth peeling
    pl = pv.Plotter(window_size=(800, 600), lighting='light_kit')
    pl.set_background('white')
    pl.enable_depth_peeling()

    # Combine hemispheres into one mesh for the cortex layer
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

    # Prepare and add activation overlay
    data = stc.data[:, time_idx]
    n_lh = len(stc.vertices[0])
    act_lh = np.zeros(mesh_lh.n_points)
    act_rh = np.zeros(mesh_rh.n_points)
    act_lh[stc.vertices[0]] = data[:n_lh]
    act_rh[stc.vertices[1]] = data[n_lh:]

    mask_lh = act_lh != 0
    mask_rh = act_rh != 0

    # Create separate meshes for the heatmap using the masks
    heatmap_lh = mesh_lh.extract_points(mask_lh)
    heatmap_rh = mesh_rh.extract_points(mask_rh)

    # Determine color limits for the heatmap
    clim = [float(data.min()), float(data.max())] if np.any(data) else [0, 1]

    if heatmap_lh.n_points > 0:
        heatmap_lh.point_data['activation'] = act_lh[mask_lh]
        pl.add_mesh(
            heatmap_lh, scalars='activation', cmap='hot', clim=clim,
            opacity=1.0, name='act_lh'
        )
    if heatmap_rh.n_points > 0:
        heatmap_rh.point_data['activation'] = act_rh[mask_rh]
        pl.add_mesh(
            heatmap_rh, scalars='activation', cmap='hot', clim=clim,
            opacity=1.0, name='act_rh'
        )

    pl.add_scalar_bar(title='Source Amplitude', n_colors=8)

    # --- THE FIX: ADD CAMERA CONTROLS HERE ---
    # This automatically adjusts the camera to fit all the meshes in the scene.
    pl.reset_camera()
    # You can then set a specific viewpoint for consistency.
    pl.camera_position = 'yz'  # Set a side view
    pl.camera.elevation = 15  # Tilt camera up slightly
    pl.camera.azimuth = 60  # Rotate camera
    pl.camera.zoom(1.4)  # Zoom in a bit
    # --- END OF FIX ---

    # Optional debug logging
    try:
        actors = list(pl.renderer.actors.values())
        logger.debug(f"Total actors: {len(actors)}")
    except Exception:
        logger.exception("Actor introspection failed")

    return pl


def view_source_estimate(
    stc_path: str,
    threshold: Optional[float] = None,
    alpha: Optional[float] = None,
    time_ms: Optional[float] = None,
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
        debug = SettingsManager().debug_enabled()
        if debug:
            logger.debug(
                "Loaded STC with %s vertices and %s time samples (tmin=%s, tstep=%s)",
                stc.data.shape[0], stc.data.shape[1], getattr(stc, 'tmin', 'n/a'), getattr(stc, 'tstep', 'n/a')
            )

        # Threshold data
        settings = SettingsManager()
        thr = threshold if threshold is not None else settings.get('visualization', 'threshold', fallback=0.0)
        if thr > 0:
            stc = stc.copy()
            val = thr * float(stc.data.max()) if 0 < thr < 1 else thr
            stc.data[(stc.data < val) & (stc.data > -val)] = 0
        if debug:
            logger.debug(
                "Threshold=%s (val=%s) -> non-zero count=%s",
                thr, 'n/a' if thr == 0 else val, np.count_nonzero(stc.data)
            )

        # Determine alpha
        gui_alpha = settings.get('visualization', 'surface_opacity', fallback=0.5)
        cortex_alpha = alpha if alpha is not None else gui_alpha

        # Resolve subjects_dir
        mri_path = settings.get('loreta', 'mri_path', fallback='')
        stored = Path(mri_path).resolve() if mri_path else None
        subjects_dir = str(_resolve_subjects_dir(stored, stc.subject or 'fsaverage'))
        if not Path(subjects_dir).exists():
            subjects_dir = str(fetch_fsaverage(verbose=False).parent)


        if time_ms is None:
            try:
                time_ms = float(settings.get('visualization', 'time_index_ms', '50'))
            except ValueError:
                time_ms = 50.0
        else:
            settings.set('visualization', 'time_index_ms', str(time_ms))
            settings.save()

        time_idx = int(round((time_ms / 1000 - stc.tmin) / stc.tstep))
        time_idx = max(0, min(time_idx, stc.data.shape[1] - 1))
        if debug:
            logger.debug(
                "Using time index %s of %s (time_ms=%s)", time_idx, stc.data.shape[1], time_ms
            )


        pl = view_source_estimate_pyvista(stc, subjects_dir, time_idx, cortex_alpha, cortex_alpha)
        pl.show(title=window_title or _derive_title(stc_path))
        return pl
    except Exception as err:
        log_func(f"ERROR plotting STC: {err}\n{traceback.format_exc()}")
        messagebox.showerror('Visualization Error', f"Could not generate 3D brain plot.\nError: {err}")
        return None

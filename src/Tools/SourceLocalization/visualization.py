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
    atlas_alpha: float,
    show_cortex: bool = True,
) -> pv.Plotter:
    """Plot source estimate heatmap with optional semi-transparent cortex.

    Parameters
    ----------
    show_cortex
        If ``True`` (default), render the anatomical cortex mesh. When ``False``
        only the activation heatmap will be displayed. Useful for debugging
        transparency issues.
    """
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
    if SettingsManager().debug_enabled():
        logger.debug(
            "Plotter created. time_idx=%s show_cortex=%s", time_idx, show_cortex
        )

    # Combine hemispheres into one mesh
    cortex_mesh = mesh_lh.copy().merge(mesh_rh)
    if show_cortex:
        pl.add_mesh(
            cortex_mesh,
            color='lightgray',
            opacity=cortex_alpha,
            ambient=1.0,
            diffuse=0.0,
            specular=0.0,
            name='cortex'
        )
    elif SettingsManager().debug_enabled():
        logger.debug('Cortex mesh rendering disabled')

    # Prepare activation data per hemisphere
    debug = SettingsManager().debug_enabled()
    data = stc.data[:, time_idx]
    n_lh = len(stc.vertices[0])
    if debug:
        logger.debug(
            "Time index %s data range: min=%s max=%s", time_idx, data.min(), data.max()
        )
    for hemi, mesh, verts in [('lh', mesh_lh, stc.vertices[0]),
                              ('rh', mesh_rh, stc.vertices[1])]:
        act = np.zeros(mesh.n_points)
        vals = data[:n_lh] if hemi == 'lh' else data[n_lh:]
        if debug:
            logger.debug(
                "%s verts: %s points, mesh points=%s", hemi, len(verts), mesh.n_points
            )
        act[verts] = vals
        # Use NaN for zero so unmapped points are fully transparent
        act_mask = act == 0
        act[act_mask] = np.nan
        if debug:
            # Log how many points contain activation values and how many are NaN
            # after applying the NaN mask so we can debug transparency issues.
            logger.debug(
                "%s activation non-zero=%s NaN=%s",
                hemi,
                np.count_nonzero(~act_mask),
                np.count_nonzero(np.isnan(act)),
            )
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
        elif debug:
            logger.debug("%s hemisphere has no activation", hemi)

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
    time_ms: Optional[float] = None,
    window_title: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
    show_cortex: Optional[bool] = None,
) -> pv.Plotter | None:
    """Load STC, apply threshold & alpha settings, then render via PyVista.

    Parameters
    ----------
    show_cortex
        Override the GUI setting controlling whether the anatomical mesh is
        displayed. ``None`` (default) uses the value from ``settings.ini``.
    """
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

        # Determine alpha and cortex visibility
        gui_alpha = settings.get('visualization', 'surface_opacity', fallback=0.5)
        cortex_alpha = alpha if alpha is not None else gui_alpha
        show_brain_mesh = settings.get('visualization', 'show_brain_mesh', 'True').lower() == 'true'
        if show_cortex is not None:
            show_brain_mesh = show_cortex
        if debug:
            logger.debug("show_brain_mesh=%s", show_brain_mesh)

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
            vals = stc.data[:, time_idx]
            logger.debug(
                "Activation range at idx %s: min=%.5f max=%.5f",
                time_idx,
                float(vals.min()),
                float(vals.max()),
            )


        pl = view_source_estimate_pyvista(
            stc,
            subjects_dir,
            time_idx,
            cortex_alpha,
            cortex_alpha,
            show_brain_mesh,
        )
        pl.show(title=window_title or _derive_title(stc_path))
        return pl
    except Exception as err:
        log_func(f"ERROR plotting STC: {err}\n{traceback.format_exc()}")
        messagebox.showerror('Visualization Error', f"Could not generate 3D brain plot.\nError: {err}")
        return None

"""Functions for opening and comparing source estimates."""

from __future__ import annotations

import os
import logging
import inspect
from pathlib import Path
from typing import Callable, Optional, Tuple

import mne
from Main_App.settings_manager import SettingsManager

from .backend_utils import _ensure_pyvista_backend, get_current_backend
from .brain_utils import (
    _set_brain_alpha,
    _set_brain_title,
    _set_colorbar_label,
)
from .data_utils import _threshold_stc, _default_template_location

logger = logging.getLogger(__name__)


def view_source_estimate(
    stc_path: str,
    threshold: Optional[float] = None,
    alpha: float = 0.5,
    window_title: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
    time: Optional[Tuple[float, float] | float] = None,
) -> mne.viz.Brain:
    """Open a saved :class:`mne.SourceEstimate` in an interactive viewer.

    Parameters
    ----------
    time : tuple | float | None
        Optional time window (``tmin``, ``tmax``) or single time point in
        seconds. When provided the source estimate is cropped and the viewer
        is opened with ``initial_time`` set to the midpoint of the range.
    """
    logger.debug(
        "view_source_estimate called with %s, threshold=%s, alpha=%s",
        stc_path,
        threshold,
        alpha,
    )
    stc_path = Path(stc_path)
    lh_file = stc_path.with_name(stc_path.name + "-lh.stc")
    rh_file = stc_path.with_name(stc_path.name + "-rh.stc")
    logger.debug("LH file exists: %s", lh_file.exists())
    logger.debug("RH file exists: %s", rh_file.exists())

    stc = mne.read_source_estimate(stc_path)
    logger.debug("Loaded STC with shape %s", stc.data.shape)
    if threshold:
        stc = _threshold_stc(stc, threshold)

    midpoint = None
    if time is not None:
        if isinstance(time, (tuple, list)):
            tmin, tmax = float(time[0]), float(time[1])
        else:
            tmin = tmax = float(time)
        midpoint = (tmin + tmax) / 2
        logger.debug("Cropping STC to %s-%s", tmin, tmax)
        stc = stc.copy().crop(tmin=tmin, tmax=tmax)

    settings = SettingsManager()
    stored_dir = settings.get("loreta", "mri_path", "")
    stored_dir_path: Path | None = None
    if stored_dir:
        stored_dir_path = Path(stored_dir).resolve()
    subject = "fsaverage"
    if stored_dir_path is not None and stored_dir_path.name == subject:
        subjects_dir_path = stored_dir_path.parent
    else:
        subjects_dir_path = stored_dir_path if stored_dir_path else _default_template_location().parent
    logger.debug("subjects_dir resolved to %s", subjects_dir_path)

    if log_func is None:
        log_func = logger.info

    _ensure_pyvista_backend()
    log_func(f"Using 3D backend: {get_current_backend()}")

    try:
        logger.debug(
            "Calling stc.plot in view_source_estimate subjects_dir=%s subject=%s",
            subjects_dir_path,
            subject,
        )
        logger.debug(
            "Backend before stc.plot: %s (MNE_3D_BACKEND=%s QT_API=%s QT_QPA_PLATFORM=%s)",
            mne.viz.get_3d_backend(),
            os.environ.get("MNE_3D_BACKEND"),
            os.environ.get("QT_API"),
            os.environ.get("QT_QPA_PLATFORM"),
        )
        plot_kwargs = dict(
            hemi="split",
            subjects_dir=str(subjects_dir_path),
            subject=subject,
            time_viewer=False,
        )
        if midpoint is not None:
            plot_kwargs.update(time_label=None, initial_time=midpoint)

        arg_name = None
        try:
            sig = inspect.signature(stc.plot)  # type: ignore[attr-defined]
            if "brain_alpha" in sig.parameters:
                arg_name = "brain_alpha"
            elif "initial_alpha" in sig.parameters:
                arg_name = "initial_alpha"
        except Exception:
            pass

        if arg_name:
            brain = stc.plot(**plot_kwargs, **{arg_name: alpha})
        else:
            brain = stc.plot(**plot_kwargs)
            _set_brain_alpha(brain, alpha)
        logger.debug("Brain alpha after plot: %s", getattr(brain, "alpha", "unknown"))
        logger.debug("stc.plot succeeded in view_source_estimate")
    except Exception as err:
        logger.warning(
            "hemi='split' failed: %s; backend=%s; falling back to default",
            err,
            mne.viz.get_3d_backend(),
        )
        plot_kwargs = dict(
            hemi="split",
            subjects_dir=str(subjects_dir_path),
            subject=subject,
            time_viewer=False,
        )
        if midpoint is not None:
            plot_kwargs.update(time_label=None, initial_time=midpoint)

        arg_name = None
        try:
            sig = inspect.signature(stc.plot)  # type: ignore[attr-defined]
            if "brain_alpha" in sig.parameters:
                arg_name = "brain_alpha"
            elif "initial_alpha" in sig.parameters:
                arg_name = "initial_alpha"
        except Exception:
            pass

        if arg_name:
            brain = stc.plot(**plot_kwargs, **{arg_name: alpha})
        else:
            brain = stc.plot(**plot_kwargs)
            _set_brain_alpha(brain, alpha)
        logger.debug("Brain alpha after fallback: %s", getattr(brain, "alpha", "unknown"))
        logger.debug("stc.plot succeeded on fallback in view_source_estimate")

    _set_brain_alpha(brain, alpha)
    logger.debug("Brain alpha set to %s", alpha)
    _set_brain_title(brain, window_title or stc_path.name)
    _set_colorbar_label(brain, "Source amplitude")
    try:
        labels = mne.read_labels_from_annot(
            subject, parc="aparc", subjects_dir=str(subjects_dir_path)
        )
        for label in labels:
            brain.add_label(label, borders=True)
    except Exception:
        pass

    return brain


def compare_source_estimates(
    stc_a: str,
    stc_b: str,
    threshold: Optional[float] = None,
    alpha: float = 0.5,
    window_title: str = "Compare STCs",
) -> Tuple[mne.viz.Brain, mne.viz.Brain]:
    """Open two :class:`mne.SourceEstimate` files side by side for comparison."""
    logger.debug(
        "compare_source_estimates called with %s and %s", stc_a, stc_b
    )

    brain_left = view_source_estimate(
        stc_a, threshold=threshold, alpha=alpha, window_title=window_title
    )
    brain_right = view_source_estimate(
        stc_b, threshold=threshold, alpha=alpha, window_title=window_title
    )

    try:
        left_win = brain_left._renderer.plotter.app_window  # type: ignore[attr-defined]
        right_win = brain_right._renderer.plotter.app_window  # type: ignore[attr-defined]
        geo = left_win.geometry()
        width = geo.width() // 2
        height = geo.height()
        left_win.resize(width, height)
        right_win.resize(width, height)
        right_win.move(left_win.x() + width, left_win.y())
    except Exception:
        logger.debug("Failed to arrange compare windows", exc_info=True)

    return brain_left, brain_right

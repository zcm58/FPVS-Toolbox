"""Functions for opening and comparing source estimates."""

from __future__ import annotations

import os
import logging
from typing import Callable, Optional, Tuple

import mne
from Main_App.settings_manager import SettingsManager

from .backend_utils import _ensure_pyvista_backend, get_current_backend
from .brain_utils import (
    _plot_with_alpha,
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
) -> mne.viz.Brain:
    """Open a saved :class:`mne.SourceEstimate` in an interactive viewer."""
    logger.debug(
        "view_source_estimate called with %s, threshold=%s, alpha=%s",
        stc_path,
        threshold,
        alpha,
    )
    lh_file = stc_path + "-lh.stc"
    rh_file = stc_path + "-rh.stc"
    logger.debug("LH file exists: %s", os.path.exists(lh_file))
    logger.debug("RH file exists: %s", os.path.exists(rh_file))

    stc = mne.read_source_estimate(stc_path)
    logger.debug("Loaded STC with shape %s", stc.data.shape)
    if threshold:
        stc = _threshold_stc(stc, threshold)

    settings = SettingsManager()
    stored_dir = settings.get("loreta", "mri_path", "")
    if stored_dir:
        stored_dir = os.path.normpath(stored_dir)
    subject = "fsaverage"
    if os.path.basename(stored_dir) == subject:
        subjects_dir = os.path.dirname(stored_dir)
    else:
        subjects_dir = (
            stored_dir if stored_dir else os.path.dirname(_default_template_location())
        )
    logger.debug("subjects_dir resolved to %s", subjects_dir)

    if log_func is None:
        log_func = logger.info

    _ensure_pyvista_backend()
    log_func(f"Using 3D backend: {get_current_backend()}")

    try:
        logger.debug(
            "Calling stc.plot in view_source_estimate subjects_dir=%s subject=%s",
            subjects_dir,
            subject,
        )
        logger.debug(
            "Backend before stc.plot: %s (MNE_3D_BACKEND=%s QT_API=%s QT_QPA_PLATFORM=%s)",
            mne.viz.get_3d_backend(),
            os.environ.get("MNE_3D_BACKEND"),
            os.environ.get("QT_API"),
            os.environ.get("QT_QPA_PLATFORM"),
        )
        brain = _plot_with_alpha(
            stc,
            hemi="split",
            subjects_dir=subjects_dir,
            subject=subject,
            alpha=alpha,
        )
        logger.debug("Brain alpha after plot: %s", getattr(brain, "alpha", "unknown"))
        logger.debug("stc.plot succeeded in view_source_estimate")
    except Exception as err:
        logger.warning(
            "hemi='split' failed: %s; backend=%s; falling back to default",
            err,
            mne.viz.get_3d_backend(),
        )
        brain = _plot_with_alpha(
            stc,
            hemi="split",
            subjects_dir=subjects_dir,
            subject=subject,
            alpha=alpha,
        )
        logger.debug("Brain alpha after fallback: %s", getattr(brain, "alpha", "unknown"))
        logger.debug("stc.plot succeeded on fallback in view_source_estimate")

    _set_brain_alpha(brain, alpha)
    logger.debug("Brain alpha set to %s", alpha)
    _set_brain_title(brain, window_title or os.path.basename(stc_path))
    _set_colorbar_label(brain, "Source amplitude")
    try:
        labels = mne.read_labels_from_annot(
            subject, parc="aparc", subjects_dir=subjects_dir
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

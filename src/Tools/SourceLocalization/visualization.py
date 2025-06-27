# src/Tools/SourceLocalization/visualization.py
"""Visualization utilities for the source localization module."""

from __future__ import annotations

import os
import logging
import inspect
import traceback
from pathlib import Path
from typing import Callable, Optional, Tuple

import mne
from tkinter import messagebox

# Assuming these helpers are in the same package/directory
from .backend_utils import _ensure_pyvista_backend, get_current_backend
from .brain_utils import _set_brain_title, _set_colorbar_label
from .data_utils import _resolve_subjects_dir

logger = logging.getLogger(__name__)


def _derive_title(path: str) -> str:
    """Create a clean window title from an STC filepath."""
    # This helper seems fine and is not related to the core error.
    name = os.path.basename(path)
    if name.endswith(("-lh.stc", "-rh.stc")):
        name = name[:-7]
    if name.endswith(("-lh", "-rh")):
        name = name[:-3]
    return f"{name} Response"


def view_source_estimate(
        stc_path: str,
        threshold: Optional[float] = None,
        alpha: float = 0.5,  # This is the transparency for the brain surface
        window_title: Optional[str] = None,
        log_func: Optional[Callable[[str], None]] = None,
) -> Optional[mne.viz.Brain]:
    """Open a saved :class:`~mne.SourceEstimate` in an interactive viewer."""

    if log_func is None:
        log_func = logger.info

    log_func(f"Visualizing STC: {os.path.basename(stc_path)} with brain alpha={alpha}")

    try:
        stc = mne.read_source_estimate(stc_path)
        log_func(f"Loaded STC with {len(stc.vertices[0]) + len(stc.vertices[1])} vertices.")

        if threshold:
            stc = stc.copy()
            if 0 < threshold < 1:
                thr_val = threshold * float(stc.data.max())
            else:
                thr_val = threshold
            stc.data[(stc.data < thr_val) & (stc.data > -thr_val)] = 0
            log_func(f"Applied threshold: {threshold}")

        from Main_App.settings_manager import SettingsManager

        settings = SettingsManager()
        stored_dir = settings.get("loreta", "mri_path", "")
        stored_path = Path(stored_dir).resolve() if stored_dir else None
        subject = "fsaverage"
        subjects_dir = str(_resolve_subjects_dir(stored_path, subject))

        log_func("Ensuring PyVista backend is active...")
        _ensure_pyvista_backend()
        log_func(f"Using 3D backend: {get_current_backend()}")

        # --- Final Plotting Call with try...except for version compatibility ---

        common_kwargs = {
            'surface': 'pial',
            'hemi': 'split',
            'subjects_dir': subjects_dir,
            'subject': subject,
            'time_viewer': False,
            'backend': 'pyvistaqt'
        }

        brain = None
        try:
            # TRY THE MODERN WAY FIRST (for MNE v0.23+)
            log_func(f"Attempting to plot using modern 'brain_alpha' parameter...")
            brain = stc.plot(
                brain_alpha=alpha,  # Set brain transparency
                alpha=1.0,  # Keep heatmap opaque
                **common_kwargs
            )
            log_func("Modern plotting method successful.")

        except TypeError as e:
            # If the modern way fails with a TypeError about 'brain_alpha'...
            if "unexpected keyword argument 'brain_alpha'" in str(e):
                log_func("Modern 'brain_alpha' not supported, falling back to older method.")
                try:
                    # TRY THE OLD WAY (for MNE < v0.23)
                    # In older versions, 'alpha' controlled the brain surface.
                    brain = stc.plot(
                        alpha=alpha,  # This now targets the brain surface
                        **common_kwargs
                    )
                    log_func("Legacy plotting method successful.")
                except Exception as e_old:
                    # If even the old way fails, log the error.
                    log_func(f"ERROR: Fallback plotting method also failed: {e_old}")
                    raise e_old  # Re-raise the error to be caught by the outer block
            else:
                # If it was a different TypeError, re-raise it.
                raise e

        if brain is None:
            raise RuntimeError("Brain object was not created after attempting all plotting methods.")

        # --- Post-Plot Adjustments ---
        _set_brain_title(brain, window_title or _derive_title(stc_path))
        _set_colorbar_label(brain, "Source amplitude")

        try:
            labels = mne.read_labels_from_annot(subject, parc="aparc", subjects_dir=subjects_dir)
            for label in labels:
                brain.add_label(label, borders=True)
            log_func("Added anatomical labels to brain plot.")
        except Exception as label_err:
            log_func(f"Could not add anatomical labels: {label_err}")

        return brain

    except Exception as err:
        log_func(f"ERROR: Failed to create source estimate plot: {err}\n{traceback.format_exc()}")
        messagebox.showerror("Visualization Error",
                             f"Could not generate the 3D plot.\nPlease check the logs for details.\n\nError: {err}")
        return None


def compare_source_estimates(
        stc_a: str,
        stc_b: str,
        threshold: Optional[float] = None,
        alpha: float = 0.5,
        window_title: Optional[str] = None,
) -> Optional[Tuple[mne.viz.Brain, mne.viz.Brain]]:  # Return type can be None
    """Open two :class:`~mne.SourceEstimate` files side by side for comparison."""

    # This function calls view_source_estimate, so the debug logic will apply here too.
    # ... (rest of the function as it was) ...
    logger.debug(
        "compare_source_estimates called with %s and %s", stc_a, stc_b
    )

    left_title = window_title or _derive_title(stc_a)
    right_title = window_title or _derive_title(stc_b)

    brain_left = view_source_estimate(
        stc_a, threshold=threshold, alpha=alpha, window_title=left_title
    )
    brain_right = view_source_estimate(
        stc_b, threshold=threshold, alpha=alpha, window_title=right_title
    )

    try:
        if brain_left and brain_right:
            left_win = brain_left._renderer.plotter.app_window
            right_win = brain_right._renderer.plotter.app_window
            geo = left_win.geometry()
            width = geo.width() // 2
            height = geo.height()
            left_win.resize(width, height)
            right_win.resize(width, height)
            right_win.move(left_win.x() + width, left_win.y())
    except Exception:
        logger.debug("Failed to auto-arrange compare windows", exc_info=True)

    # Return None if either brain failed to generate
    if not brain_left or not brain_right:
        return None
    return brain_left, brain_right
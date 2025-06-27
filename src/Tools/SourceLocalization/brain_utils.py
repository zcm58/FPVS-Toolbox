# src/Tools/SourceLocalization/brain_utils.py
"""Helper functions for manipulating mne.viz.Brain instances."""

from __future__ import annotations
import logging
import inspect
import mne

logger = logging.getLogger(__name__)


def _set_brain_title(brain: mne.viz.Brain, title: str) -> None:
    """Safely set the window title of a Brain viewer."""
    try:
        plotter = brain._renderer.plotter
        if hasattr(plotter, "app_window"):
            plotter.app_window.setWindowTitle(title)
    except Exception:
        logger.debug("Could not set brain title.", exc_info=True)


def _set_brain_alpha(brain: mne.viz.Brain, alpha: float) -> None:
    """Set the transparency of the brain surface meshes after plotting."""
    logger.debug("Attempting to set brain surface alpha to %s post-plot.", alpha)
    try:
        # This is the modern and direct way for PyVista-based backends
        brain.set_surface_opacity(alpha, 'both')
        logger.debug("Successfully used brain.set_surface_opacity(%s)", alpha)
    except Exception:
        logger.warning(
            "brain.set_surface_opacity() failed. Falling back to actor modification.",
            exc_info=True
        )
        # Fallback for older versions or different renderer states
        try:
            actors = []
            for hemi in ['lh', 'rh']:
                if hemi in brain._hemi_actors:
                    actors.append(brain._hemi_actors[hemi])

            if not actors:  # Try another internal attribute if the first fails
                for hemi_mesh in brain._surfaces.values():
                    actors.append(hemi_mesh['actor'])

            if not actors:
                logger.error("Could not find any brain surface actors to modify alpha.")
                return

            for actor in actors:
                actor.GetProperty().SetOpacity(alpha)

            brain._renderer.plotter.render()
            logger.debug("Successfully set opacity on %d actors and re-rendered.", len(actors))
        except Exception:
            logger.error("All methods to set brain alpha post-plot failed.", exc_info=True)


def _plot_with_alpha(
        stc: mne.BaseSourceEstimate,
        *,
        hemi: str,
        subjects_dir: str,
        subject: str,
        brain_alpha_val: float,  # Use a distinct name for clarity
) -> mne.viz.Brain:
    """
    Call stc.plot using the correct keyword argument for brain transparency.
    """
    plot_kwargs = dict(
        subject=subject,
        subjects_dir=subjects_dir,
        time_viewer=False,
        hemi=hemi,
        alpha=1.0,  # CRITICAL: Keep the activation heatmap fully opaque
        backend='pyvistaqt'  # Be explicit
    )

    arg_name_for_brain_alpha = None
    try:
        # Find the correct parameter name for brain transparency
        sig = inspect.signature(stc.plot)
        if "brain_alpha" in sig.parameters:
            arg_name_for_brain_alpha = "brain_alpha"
        elif "initial_alpha" in sig.parameters:  # For older MNE versions
            arg_name_for_brain_alpha = "initial_alpha"
    except Exception:
        logger.warning("Could not inspect stc.plot signature. Defaulting to 'brain_alpha'.")
        arg_name_for_brain_alpha = "brain_alpha"

    logger.debug("Plotting with brain transparency arg: '%s' = %s", arg_name_for_brain_alpha, brain_alpha_val)

    if arg_name_for_brain_alpha:
        plot_kwargs[arg_name_for_brain_alpha] = brain_alpha_val
        brain = stc.plot(**plot_kwargs)
    else:
        # Fallback if no transparency argument could be found
        logger.warning("No brain transparency argument found in stc.plot signature. Plotting without initial alpha.")
        brain = stc.plot(**plot_kwargs)
        _set_brain_alpha(brain, brain_alpha_val)  # Try to set it after plotting

    return brain


def _set_colorbar_label(brain: mne.viz.Brain, label: str) -> None:
    """Set the colorbar title in a robust way."""
    try:
        renderer = getattr(brain, "_renderer", None)
        cbar = None
        if renderer is not None:
            plotter = getattr(renderer, "plotter", None)
            cbar = getattr(plotter, "scalar_bar", None)
        if cbar is not None:
            if hasattr(cbar, "SetTitle"):
                cbar.SetTitle(label)
            elif hasattr(cbar, "title"):
                cbar.title = label
    except Exception:
        logger.debug("Failed to set colorbar label", exc_info=True)
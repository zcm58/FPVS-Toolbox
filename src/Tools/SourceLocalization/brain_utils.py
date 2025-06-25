"""Helper functions for manipulating :class:`mne.viz.Brain` instances."""

from __future__ import annotations

import logging
import inspect
import os
import mne

logger = logging.getLogger(__name__)


def _set_brain_title(brain: mne.viz.Brain, title: str) -> None:
    """Safely set the window title of a Brain viewer."""
    try:
        plotter = brain._renderer.plotter  # type: ignore[attr-defined]
        if hasattr(plotter, "app_window"):
            plotter.app_window.setWindowTitle(title)
    except Exception:
        pass


def _set_brain_alpha(brain: mne.viz.Brain, alpha: float) -> None:
    """Set the transparency of a Brain viewer in a version robust way."""
    logger.debug("_set_brain_alpha called with %s", alpha)
    success = False
    actor_count = 0
    try:
        if hasattr(brain, "set_alpha"):
            logger.debug("Using Brain.set_alpha")
            brain.set_alpha(alpha)  # type: ignore[call-arg]
            success = True
        elif hasattr(brain, "alpha"):
            logger.debug("Setting Brain.alpha attribute")
            setattr(brain, "alpha", alpha)
            success = True
    except Exception:
        logger.debug("Direct alpha methods failed", exc_info=True)

    if not success:
        try:
            actors = []
            actor_count = 0
            for hemi in getattr(brain, "_hemi_data", {}).values():
                mesh = getattr(hemi, "mesh", None)
                if mesh is not None and hasattr(mesh, "actor"):
                    actors.append(mesh.actor)
                for layer in getattr(hemi, "layers", {}).values():
                    actor = getattr(layer, "actor", None)
                    if actor is not None:
                        actors.append(actor)

            for hemi_layers in getattr(brain, "_layered_meshes", {}).values():
                for layer in hemi_layers.values():
                    actor = getattr(layer, "actor", None)
                    if actor is not None:
                        actors.append(actor)

            for overlay in getattr(brain, "_data", {}).values():
                if hasattr(overlay, "actor"):
                    actors.append(overlay.actor)
                elif isinstance(overlay, dict):
                    for item in overlay.values():
                        a = getattr(item, "actor", None)
                        if a is not None:
                            actors.append(a)
            for actor in getattr(brain, "_actors", {}).values():
                if hasattr(actor, "GetProperty"):
                    actors.append(actor)
                elif hasattr(actor, "actor"):
                    a = getattr(actor, "actor", None)
                    if a is not None:
                        actors.append(a)

            actor_count = len(actors)
            for actor in actors:
                try:
                    actor.GetProperty().SetOpacity(alpha)
                except Exception:
                    pass
            logger.debug("Opacity set on %d actors", actor_count)
            success = bool(actors)
        except Exception:
            logger.debug("Failed to set brain alpha via mesh actors", exc_info=True)

    try:
        renderer = getattr(brain, "_renderer", None)
        plotter = getattr(renderer, "plotter", None)
        if plotter is not None and hasattr(plotter, "render"):
            logger.debug("Triggering plotter.render()")
            plotter.render()
        elif renderer is not None and hasattr(renderer, "_update"):
            logger.debug("Triggering renderer._update()")
            renderer._update()
        logger.debug("Alpha update success: %s", success)
    except Exception:
        logger.debug("Plotter render failed", exc_info=True)

    logger.debug("_set_brain_alpha success=%s actors=%d", success, actor_count)


def _plot_with_alpha(
    stc: mne.BaseSourceEstimate,
    *,
    hemi: str,
    subjects_dir: str,
    subject: str,
    alpha: float,
) -> mne.viz.Brain:
    """Call :meth:`mne.SourceEstimate.plot` using whichever alpha argument works."""
    plot_kwargs = dict(
        subject=subject,
        subjects_dir=subjects_dir,
        time_viewer=False,
        hemi=hemi,
    )

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

    return brain


def _set_colorbar_label(brain: mne.viz.Brain, label: str) -> None:
    """Set the colorbar title in a robust way."""
    try:
        renderer = getattr(brain, "_renderer", None)
        cbar = None
        if renderer is not None:
            cbar = getattr(renderer, "scalar_bar", None)
            if cbar is None:
                plotter = getattr(renderer, "plotter", None)
                cbar = getattr(plotter, "scalar_bar", None)
        if cbar is not None:
            if hasattr(cbar, "SetTitle"):
                cbar.SetTitle(label)
            elif hasattr(cbar, "title"):
                cbar.title = label
    except Exception:
        logger.debug("Failed to set colorbar label", exc_info=True)


def _add_brain_labels(brain: mne.viz.Brain, left: str, right: str) -> None:
    """Add file name labels above each hemisphere view."""
    try:
        renderer = getattr(brain, "_renderer", None)
        if renderer is not None and hasattr(renderer, "subplot"):
            renderer.subplot(0, 0)
        brain.add_text(0.5, 0.95, left, name="lh_label", font_size=10)
        if renderer is not None and hasattr(renderer, "subplot"):
            renderer.subplot(0, 1)
        brain.add_text(0.5, 0.95, right, name="rh_label", font_size=10)
    except Exception:
        logger.debug("Failed to add hemisphere labels", exc_info=True)


def save_brain_screenshots(brain: mne.viz.Brain, output_dir: str) -> None:
    """Save standard view screenshots to ``output_dir``."""
    for view, name in [
        ("lat", "side"),
        ("rostral", "frontal"),
        ("dorsal", "top"),
    ]:
        brain.show_view(view)
        brain.save_image(os.path.join(output_dir, f"{name}.png"))
    brain.save_image(os.path.join(output_dir, "overview.png"))

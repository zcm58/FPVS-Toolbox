"""Visualization utilities for the source localization module."""

from __future__ import annotations

import os
import logging
import inspect
from typing import Callable, Optional, Tuple

import mne

logger = logging.getLogger(__name__)


def _ensure_pyvista_backend() -> None:
    """Force the MNE 3D backend to PyVista."""
    if not hasattr(mne.viz, "set_3d_backend"):
        return

    logger.debug("MNE_3D_BACKEND: %s", os.environ.get("MNE_3D_BACKEND"))
    logger.debug("QT_API: %s", os.environ.get("QT_API"))
    logger.debug("QT_QPA_PLATFORM: %s", os.environ.get("QT_QPA_PLATFORM"))
    current = None
    if hasattr(mne.viz, "get_3d_backend"):
        current = mne.viz.get_3d_backend()
        logger.debug("Existing MNE 3D backend: %s", current)
    if current in {"pyvistaqt", "pyvista"}:
        return

    for backend in ("pyvistaqt", "pyvista"):
        logger.debug("Attempting backend %s", backend)
        try:
            mne.viz.set_3d_backend(backend)
            os.environ["MNE_3D_BACKEND"] = backend
            if hasattr(mne.viz, "get_3d_backend"):
                logger.debug("Backend after set: %s", mne.viz.get_3d_backend())
        except Exception as err:  # pragma: no cover - optional
            logger.debug("Failed to set backend %s: %s", backend, err)
            continue
        if not hasattr(mne.viz, "get_3d_backend"):
            return
        if mne.viz.get_3d_backend() == backend:
            logger.debug("Using 3D backend %s", backend)
            return

    msg = "PyVista backend ('pyvistaqt' or 'pyvista') is required"
    logger.error(msg, exc_info=True)
    raise RuntimeError(msg)


def get_current_backend() -> str:
    """Return the currently active MNE 3D backend."""
    backend = None
    if hasattr(mne.viz, "get_3d_backend"):
        try:
            backend = mne.viz.get_3d_backend()
        except Exception:
            backend = None
    if not backend:
        backend = os.environ.get("MNE_3D_BACKEND", "")
    return str(backend).lower()


def is_pyvistaqt_backend() -> bool:
    """Check if the PyVistaQt backend is active."""
    return get_current_backend() == "pyvistaqt"


def is_pyvista_backend() -> bool:
    """Alias for :func:`is_pyvistaqt_backend`."""
    return is_pyvistaqt_backend()


def _set_brain_title(brain: mne.viz.Brain, title: str) -> None:
    """Safely set the window title of a Brain viewer."""
    try:
        plotter = brain._renderer.plotter  # type: ignore[attr-defined]
        if hasattr(plotter, "app_window"):
            plotter.app_window.setWindowTitle(title)
    except Exception:
        # Setting the title is best-effort only
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


def view_source_estimate(
    stc_path: str,
    threshold: Optional[float] = None,
    alpha: float = 0.5,
    window_title: Optional[str] = None,
    log_func: Optional[Callable[[str], None]] = None,
) -> mne.viz.Brain:
    """Open a saved :class:`~mne.SourceEstimate` in an interactive viewer."""

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
        stc = stc.copy()
        if 0 < threshold < 1:
            thr_val = threshold * float(stc.data.max())
        else:
            thr_val = threshold
        stc.data[(stc.data < thr_val) & (stc.data > -thr_val)] = 0

    from Main_App.settings_manager import SettingsManager

    settings = SettingsManager()
    stored_dir = settings.get("loreta", "mri_path", "")
    if stored_dir:
        stored_dir = os.path.normpath(stored_dir)
    subject = "fsaverage"
    if os.path.basename(stored_dir) == subject:
        subjects_dir = os.path.dirname(stored_dir)
    else:
        subjects_dir = (
            stored_dir if stored_dir else os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
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
        logger.debug(
            "Brain alpha after fallback: %s", getattr(brain, "alpha", "unknown")
        )
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
    """Open two :class:`~mne.SourceEstimate` files side by side for comparison."""

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

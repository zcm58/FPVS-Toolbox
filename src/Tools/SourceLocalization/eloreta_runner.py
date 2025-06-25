"""Backend routines for running eLORETA or sLORETA source localization."""

from __future__ import annotations

import os
import logging
import threading
import time
import importlib
from typing import Callable, Optional, Tuple, List

import numpy as np
import mne
from Main_App.settings_manager import SettingsManager
from . import source_localization

logger = logging.getLogger(__name__)

# Log versions and backend availability at import time for easier debugging
try:  # pragma: no cover - best effort environment logging
    logger.debug("MNE version: %s", mne.__version__)
    if hasattr(mne.viz, "get_3d_backend"):
        logger.debug("MNE 3D backend: %s", mne.viz.get_3d_backend())
except Exception as err:
    logger.debug("Failed to query MNE backend info: %s", err)

for mod in ("pyvista", "pyvistaqt"):
    spec = importlib.util.find_spec(mod)
    logger.debug("%s available: %s", mod, spec is not None)
    if spec is not None:
        try:
            module = importlib.import_module(mod)
            ver = getattr(module, "__version__", "unknown")
            logger.debug("%s version: %s", mod, ver)
        except Exception as err:  # pragma: no cover - optional
            logger.debug("%s version lookup failed: %s", mod, err)


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
    try:
        if hasattr(brain, "set_alpha"):
            logger.debug("Using Brain.set_alpha")
            brain.set_alpha(alpha)  # type: ignore[call-arg]
        else:

            logger.debug("Falling back to setting Brain.alpha attribute")

            setattr(brain, "alpha", alpha)
    except Exception:
        logger.debug("Direct alpha methods failed", exc_info=True)
        try:
            for hemi in getattr(brain, "_hemi_data", {}).values():
                mesh = getattr(hemi, "mesh", None)
                if mesh is not None and hasattr(mesh, "actor"):
                    mesh.actor.GetProperty().SetOpacity(alpha)
                for layer in getattr(hemi, "layers", {}).values():
                    actor = getattr(layer, "actor", None)
                    if actor is not None:
                        actor.GetProperty().SetOpacity(alpha)

            # PyVista backend stores additional actors in _layered_meshes
            for hemi_layers in getattr(brain, "_layered_meshes", {}).values():
                for layer in hemi_layers.values():
                    actor = getattr(layer, "actor", None)
                    if actor is not None:
                        actor.GetProperty().SetOpacity(alpha)
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
    except Exception:
        logger.debug("Plotter render failed", exc_info=True)


def _add_brain_labels(brain: mne.viz.Brain, left: str, right: str) -> None:
    """Add file name labels above each hemisphere view.

    Parameters
    ----------
    brain
        The :class:`~mne.viz.Brain` instance to annotate.
    left
        Label text for the left hemisphere view.
    right
        Label text for the right hemisphere view.
    """

    try:

        renderer = getattr(brain, "_renderer", None)

        # Add the left label in the left subplot
        if renderer is not None and hasattr(renderer, "subplot"):
            renderer.subplot(0, 0)
        brain.add_text(0.5, 0.95, left, name="lh_label", font_size=10)

        # Add the right label in the right subplot
        if renderer is not None and hasattr(renderer, "subplot"):
            renderer.subplot(0, 1)

        brain.add_text(0.5, 0.95, right, name="rh_label", font_size=10)
    except Exception:
        logger.debug("Failed to add hemisphere labels", exc_info=True)


def _load_data(fif_path: str) -> mne.Evoked:
    """Load epochs or evoked data and return an Evoked instance."""
    if fif_path.endswith("-epo.fif"):
        epochs = mne.read_epochs(fif_path, preload=True)
        return epochs.average()
    return mne.read_evokeds(fif_path, condition=0, baseline=(None, 0))


def _default_template_location() -> str:
    """Return the directory where the template MRI should reside."""
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..")
    )
    return os.path.join(base_dir, "fsaverage")


def _dir_size_mb(path: str) -> float:
    """Return the size of ``path`` in megabytes."""
    total = 0
    for root, _, files in os.walk(path):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                total += os.path.getsize(fpath)
            except OSError:
                pass
    return total / (1024 * 1024)


def _threshold_stc(stc: mne.SourceEstimate, thr: float) -> mne.SourceEstimate:
    """Return a copy of ``stc`` with values below ``thr`` zeroed.

    The threshold may be specified either as an absolute value or as a
    fraction between 0 and 1. If ``thr`` is between 0 and 1, it is treated as a
    fraction of the maximum absolute amplitude in ``stc``.
    """
    stc = stc.copy()
    if 0 < thr < 1:
        thr_val = thr * np.max(np.abs(stc.data))
    else:
        thr_val = thr
    stc.data[np.abs(stc.data) < thr_val] = 0
    return stc


def fetch_fsaverage_with_progress(
    subjects_dir: str, log_func: Callable[[str], None] = logger.info
) -> str:
    """Download ``fsaverage`` while logging progress to ``log_func``."""

    stop_event = threading.Event()

    def _report():
        dest = os.path.join(subjects_dir, "fsaverage")
        last = -1.0
        while not stop_event.is_set():
            if os.path.isdir(dest):
                size = _dir_size_mb(dest)
                if size != last:
                    log_func(f"Downloaded {size:.1f} MB...")
                    last = size
            time.sleep(1)

    thread = threading.Thread(target=_report, daemon=True)
    thread.start()
    try:
        path = mne.datasets.fetch_fsaverage(subjects_dir=subjects_dir, verbose=True)
    finally:
        stop_event.set()
        thread.join()

    log_func(f"Download complete. Total size: {_dir_size_mb(path):.1f} MB")
    return path


def _prepare_forward(
    evoked: mne.Evoked,
    settings: SettingsManager,
    log_func: Callable[[str], None],
) -> tuple[mne.Forward, str, str]:
    """Construct a forward model using MRI info from settings or fsaverage."""
    stored_dir = settings.get("loreta", "mri_path", "")
    subject = "fsaverage"

    log_func(f"Initial stored MRI directory: {stored_dir}")

    if not stored_dir or not os.path.isdir(stored_dir):
        log_func(
            "Default MRI template not found. Downloading 'fsaverage'. This may take a few minutes..."
        )

        install_parent = os.path.dirname(_default_template_location())
        log_func(f"Attempting download to: {install_parent}")
        try:
            fs_path = fetch_fsaverage_with_progress(install_parent, log_func)
        except Exception as err:
            log_func(
                f"Progress download failed ({err}). Falling back to mne.datasets.fetch_fsaverage"
            )
            fs_path = mne.datasets.fetch_fsaverage(
                subjects_dir=install_parent, verbose=True
            )
        # ``configparser.ConfigParser`` requires string values
        settings.set("loreta", "mri_path", str(fs_path))

        try:
            settings.save()
        except Exception:
            pass

        log_func(f"Template downloaded to: {fs_path}")

        stored_dir = fs_path
    else:
        log_func(f"Using existing MRI directory: {stored_dir}")

    if os.path.basename(stored_dir) == subject:
        subjects_dir = os.path.dirname(stored_dir)
        log_func(f"Parent directory for subjects set to: {subjects_dir}")
    else:
        subjects_dir = stored_dir
        log_func(f"Subjects directory resolved to: {subjects_dir}")

    surf_dir = os.path.join(subjects_dir, subject, "surf")
    log_func(f"Expecting surface files in: {surf_dir}")

    # Use fsaverage transformation if no custom trans file is specified
    trans = settings.get("paths", "trans_file", "fsaverage")
    log_func(f"Using trans file: {trans}")
    log_func(
        f"Building source space using subjects_dir={subjects_dir}, subject={subject}"
    )
    src = mne.setup_source_space(
        subject, spacing="oct6", subjects_dir=subjects_dir, add_dist=False
    )
    cache_dir = os.path.join(subjects_dir, "fpvs_cache")
    os.makedirs(cache_dir, exist_ok=True)
    fwd_file = os.path.join(cache_dir, f"forward-{subject}.fif")

    if os.path.isfile(fwd_file):
        log_func(f"Loading cached forward model from {fwd_file}")
        fwd = mne.read_forward_solution(fwd_file)
    else:
        log_func("Creating BEM model ...")
        model = mne.make_bem_model(subject=subject, subjects_dir=subjects_dir, ico=4)
        bem = mne.make_bem_solution(model)
        log_func("Computing forward solution ...")
        fwd = mne.make_forward_solution(
            evoked.info, trans=trans, src=src, bem=bem, eeg=True
        )
        mne.write_forward_solution(fwd_file, fwd, overwrite=True)
    return fwd, subject, subjects_dir


def run_source_localization(
    fif_path: str,
    output_dir: str,
    method: str = "eLORETA",
    threshold: Optional[float] = None,
    alpha: float = 0.4,


    low_freq: Optional[float] = None,
    high_freq: Optional[float] = None,
    harmonics: Optional[list[float]] = None,
    snr: Optional[float] = None,
    oddball: bool = False,

    hemi: str = "split",

    log_func: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    export_rois: bool = False,
    show_brain: bool = True,

) -> Tuple[str, Optional[mne.viz.Brain]]:
    """Run source localization on ``fif_path`` and save results to ``output_dir``.

    Parameters
    ----------
    alpha : float
        Initial transparency for the brain surface where ``1.0`` is opaque.
        Defaults to ``0.4`` (60% transparent).
    hemi : {"lh", "rh", "both", "split"}
        Which hemisphere(s) to display in the interactive viewer.
    export_rois : bool
        If ``True`` an additional CSV summarising ROI amplitudes is saved
        in ``output_dir``.
    show_brain : bool
        If ``True`` display the interactive brain window. When running in a
        background thread this should typically be ``False``.


    Returns
    -------
    Tuple[str, Optional[:class:`mne.viz.Brain`]]
        Path to the saved :class:`~mne.SourceEstimate` (without hemisphere
        suffix) and the interactive brain window (``None`` if ``show_brain`` is
        ``False``).
    """
    if log_func is None:
        log_func = logger.info

    logger.debug(
        "run_source_localization called with %s", {
            "fif_path": fif_path,
            "output_dir": output_dir,
            "method": method,
            "threshold": threshold,
            "alpha": alpha,
            "hemi": hemi,
            "low_freq": low_freq,
            "high_freq": high_freq,
            "harmonics": harmonics,
            "snr": snr,
            "oddball": oddball,
        },
    )
    logger.debug(
        "QT_API=%s QT_QPA_PLATFORM=%s",
        os.environ.get("QT_API"),
        os.environ.get("QT_QPA_PLATFORM"),
    )
    step = 0
    total = 7
    if progress_cb:
        progress_cb(0.0)
    log_func(f"Loading data from {fif_path}")
    settings = SettingsManager()
    if low_freq is None:
        try:
            low_freq = float(settings.get("loreta", "loreta_low_freq", "0.1"))
        except ValueError:
            low_freq = None
    if high_freq is None:
        try:
            high_freq = float(settings.get("loreta", "loreta_high_freq", "40.0"))
        except ValueError:
            high_freq = None

    default_low = float(settings.get("loreta", "loreta_low_freq", "0.1"))
    default_high = float(settings.get("loreta", "loreta_high_freq", "40.0"))
    if oddball and low_freq == default_low and high_freq == default_high:
        # avoid redundant filtering when using oddball pipeline
        low_freq = None
        high_freq = None
    if harmonics is None:
        harm_str = settings.get("loreta", "oddball_harmonics", "1,2,3")
        try:
            harmonics = [float(h) for h in harm_str.split(',') if h.strip()]
        except Exception:
            harmonics = []
    if snr is None:
        try:
            snr = float(settings.get("loreta", "loreta_snr", "3.0"))
        except ValueError:
            snr = 3.0
    oddball_freq = float(settings.get("analysis", "oddball_freq", "1.2"))

    if oddball and fif_path.endswith("-epo.fif"):
        log_func("Oddball mode enabled. Loading epochs ...")
        epochs = mne.read_epochs(fif_path, preload=True)
        log_func(f"Loaded {len(epochs)} epoch(s)")
        if low_freq or high_freq:
            epochs = epochs.copy().filter(l_freq=low_freq, h_freq=high_freq)
        cycle_epochs = source_localization.extract_cycles(epochs, oddball_freq)
        log_func(
            f"Extracted {len(cycle_epochs)} cycles of {1.0 / oddball_freq:.3f}s each"
        )
        evoked = source_localization.average_cycles(cycle_epochs)
        log_func("Averaged cycles into Evoked")
        harmonic_freqs = [h * oddball_freq for h in harmonics]
        if harmonic_freqs:
            log_func(
                "Reconstructing harmonics: "
                + ", ".join(f"{h:.2f}Hz" for h in harmonic_freqs)
            )
            evoked = source_localization.reconstruct_harmonics(evoked, harmonic_freqs)
    else:
        evoked = _load_data(fif_path)
        if low_freq or high_freq:
            evoked = evoked.copy().filter(l_freq=low_freq, h_freq=high_freq)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    log_func("Preparing forward model ...")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings, log_func)
    log_func(f"Forward model ready. subjects_dir={subjects_dir}, subject={subject}")
    step += 1
    if progress_cb:
        progress_cb(step / total)

    try:
        temp_epochs = mne.EpochsArray(
            evoked.data[np.newaxis, ...],
            evoked.info,
            tmin=evoked.times[0],
            verbose=False,
        )
        noise_cov = mne.compute_covariance(temp_epochs, tmax=0.0)
    except Exception as err:
        log_func(
            f"Noise covariance estimation failed ({err}). Using ad-hoc covariance."
        )
        noise_cov = mne.make_ad_hoc_cov(evoked.info)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    if oddball:
        inv = source_localization.build_inverse_operator(evoked, subjects_dir)
        step += 1
        if progress_cb:
            progress_cb(step / total)
        stc = source_localization.apply_sloreta(evoked, inv, snr)
    else:
        inv = mne.minimum_norm.make_inverse_operator(evoked.info, fwd, noise_cov)
        step += 1
        if progress_cb:
            progress_cb(step / total)

        method_lower = method.lower()
        if method_lower not in {"eloreta", "sloreta"}:
            raise ValueError("Method must be 'eLORETA' or 'sLORETA'")

        log_func(f"Applying {method_lower} ...")
        mne_method = "eLORETA" if method_lower == "eloreta" else "sLORETA"
        stc = mne.minimum_norm.apply_inverse(evoked, inv, method=mne_method)
    if threshold:
        stc = _threshold_stc(stc, threshold)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    os.makedirs(output_dir, exist_ok=True)
    stc_path = os.path.join(output_dir, "source")
    stc.save(stc_path)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    brain = None
    if show_brain:
        # Visualise in a separate Brain window
        logger.debug(
            "Plotting STC with subjects_dir=%s, subject=%s", subjects_dir, subject
        )

        try:
            logger.debug(
                "Calling stc.plot with hemi=%s subjects_dir=%s subject=%s",
                hemi,
                subjects_dir,
                subject,
            )
            brain = stc.plot(
                subject=subject,
                subjects_dir=subjects_dir,
                time_viewer=False,
                hemi=hemi,
            )
            logger.debug("stc.plot succeeded")
        except Exception as err:
            logger.warning(
                "hemi=%s failed: %s; falling back to default",
                hemi,
                err,
            )
            logger.debug("Retrying stc.plot with default hemisphere")
            brain = stc.plot(
                subject=subject,
                subjects_dir=subjects_dir,
                time_viewer=False,
            )
            logger.debug("stc.plot succeeded on retry")
        _set_brain_alpha(brain, alpha)
        logger.debug("Brain alpha set to %s", alpha)
        _set_brain_title(brain, os.path.basename(stc_path))
        try:
            labels = mne.read_labels_from_annot(
                subject, parc="aparc", subjects_dir=subjects_dir
            )
            for label in labels:
                brain.add_label(label, borders=True)
        except Exception:
            # If annotations aren't available just continue without borders
            pass


        for view, name in [
            ("lat", "side"),
            ("rostral", "frontal"),
            ("dorsal", "top"),
        ]:
            brain.show_view(view)
            brain.save_image(os.path.join(output_dir, f"{name}.png"))
        # Save the current view as an additional screenshot
        brain.save_image(os.path.join(output_dir, "overview.png"))
    if export_rois:
        try:
            roi_path = os.path.join(output_dir, "roi_values.csv")
            source_localization.export_roi_means(stc, subject, subjects_dir, roi_path)
            log_func(f"ROI values exported to {roi_path}")
        except Exception as err:
            log_func(f"ROI export failed: {err}")

    step += 1
    if progress_cb:
        progress_cb(step / total)

    log_func(f"Results saved to {output_dir}")
    if progress_cb:
        progress_cb(1.0)


    return stc_path, brain


def view_source_estimate(
    stc_path: str,
    threshold: Optional[float] = None,
    alpha: float = 0.4,
    window_title: Optional[str] = None,

) -> mne.viz.Brain:
    """Open a saved :class:`~mne.SourceEstimate` in an interactive viewer.

    Parameters
    ----------
    alpha : float
        Transparency for the brain surface where ``1.0`` is opaque.
        Defaults to ``0.4`` (60% transparent).

    hemi : {"lh", "rh", "both", "split"}
        Which hemisphere(s) to display in the interactive viewer.

    Notes
    -----
    When ``hemi`` is ``split`` the names of the ``*-lh.stc`` and ``*-rh.stc``
    files are displayed above the left and right hemispheres respectively.
    """

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
    subject = "fsaverage"
    if os.path.basename(stored_dir) == subject:
        subjects_dir = os.path.dirname(stored_dir)
    else:
        subjects_dir = (
            stored_dir if stored_dir else os.path.dirname(_default_template_location())
        )
    logger.debug("subjects_dir resolved to %s", subjects_dir)


    try:
        logger.debug(
            "Calling stc.plot in view_source_estimate subjects_dir=%s subject=%s",
            subjects_dir,
            subject,
        )
        brain = stc.plot(
            subject=subject,
            subjects_dir=subjects_dir,
            time_viewer=False,
            hemi="split",
        )
        logger.debug("stc.plot succeeded in view_source_estimate")
    except Exception as err:
        logger.warning("hemi='split' failed: %s; falling back to default", err)
        brain = stc.plot(
            subject=subject,
            subjects_dir=subjects_dir,
            time_viewer=False,
        )
        logger.debug("stc.plot succeeded on fallback in view_source_estimate")

    _set_brain_alpha(brain, alpha)
    logger.debug("Brain alpha set to %s", alpha)
    _set_brain_title(brain, window_title or os.path.basename(stc_path))
    try:
        labels = mne.read_labels_from_annot(
            subject, parc="aparc", subjects_dir=subjects_dir
        )
        for label in labels:
            brain.add_label(label, borders=True)
    except Exception:
        # If annotations aren't available just continue without borders
        pass
    _add_brain_labels(brain, os.path.basename(lh_file), os.path.basename(rh_file))

    return brain


def compare_source_estimates(
    stc_a: str,
    stc_b: str,
    threshold: Optional[float] = None,
    alpha: float = 0.4,
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

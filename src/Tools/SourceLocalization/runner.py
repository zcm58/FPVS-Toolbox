"""Backend routines for running eLORETA or sLORETA source localization."""

from __future__ import annotations

import os
import logging
import importlib
from typing import Callable, Optional, Tuple
from multiprocessing import Queue

# Force PyVistaQt backend before MNE is imported so the interactive viewer
# respects transparency updates.
if os.environ.get("MNE_3D_BACKEND", "").lower() != "pyvistaqt":
    os.environ["MNE_3D_BACKEND"] = "pyvistaqt"

import numpy as np
import mne
from mne import combine_evoked
from Main_App.settings_manager import SettingsManager
from . import source_localization
from .backend_utils import _ensure_pyvista_backend, get_current_backend
from .brain_utils import (
    _plot_with_alpha,
    _set_brain_alpha,
    _set_brain_title,
    save_brain_screenshots,
    _set_colorbar_label,
)
from .data_utils import (
    _load_data,
    _threshold_stc,
    _prepare_forward,
    _estimate_epochs_covariance,
)

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

logger.debug("NumPy version: %s", np.__version__)
logger.debug("source_localization module: %s", source_localization.__file__)

# Ensure we use the interactive PyVista backend if available so that
# transparency updates take effect at runtime.
try:  # pragma: no cover - best effort
    if (
        hasattr(mne.viz, "set_3d_backend")
        and hasattr(mne.viz, "get_3d_backend")
        and mne.viz.get_3d_backend() != "pyvistaqt"
    ):
        mne.viz.set_3d_backend("pyvistaqt", verbose=False)
        logger.debug("3D backend set to pyvistaqt")
except Exception as err:  # pragma: no cover - optional
    logger.debug("Failed to set 3D backend: %s", err)




def run_source_localization(
    fif_path: str | None,
    output_dir: str,
    *,
    epochs: mne.Epochs | None = None,
    method: str = "eLORETA",
    threshold: Optional[float] = None,
    alpha: float = 0.5,
    stc_basename: Optional[str] = None,


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
    stc_basename : str | None
        Base filename (without hemisphere suffix) for the saved ``.stc`` files.
        Defaults to ``"source"``.
    alpha : float
        Initial transparency for the brain surface where ``1.0`` is opaque.
        Defaults to ``0.5`` (50% transparent).
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
    if epochs is not None:
        log_func("Using in-memory epochs")
    else:
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

    noise_cov = None
    if epochs is not None:
        if oddball:
            if low_freq or high_freq:
                epochs = epochs.copy().filter(l_freq=low_freq, h_freq=high_freq)
            cycle_epochs = source_localization.extract_cycles(epochs, oddball_freq)
            log_func(
                f"Extracted {len(cycle_epochs)} cycles of {1.0 / oddball_freq:.3f}s each"
            )
            noise_cov = _estimate_epochs_covariance(cycle_epochs, log_func)
            evoked = source_localization.average_cycles(cycle_epochs)
            log_func("Averaged cycles into Evoked")
            harmonic_freqs = harmonics
            if harmonic_freqs:
                log_func(
                    "Reconstructing harmonics: "
                    + ", ".join(f"{h:.2f}Hz" for h in harmonic_freqs)
                )
                evoked = source_localization.reconstruct_harmonics(evoked, harmonic_freqs)
            evoked = evoked.copy().crop(tmin=0.0, tmax=1.0 / oddball_freq)
            evoked = combine_evoked([evoked], weights="equal")
        else:
            noise_cov = _estimate_epochs_covariance(epochs, log_func)
            evoked = epochs.average()
            if low_freq or high_freq:
                evoked = evoked.copy().filter(l_freq=low_freq, h_freq=high_freq)
    elif oddball and fif_path and fif_path.endswith("-epo.fif"):
        log_func("Oddball mode enabled. Loading epochs ...")
        epochs = mne.read_epochs(fif_path, preload=True)
        log_func(f"Loaded {len(epochs)} epoch(s)")
        if low_freq or high_freq:
            epochs = epochs.copy().filter(l_freq=low_freq, h_freq=high_freq)
        cycle_epochs = source_localization.extract_cycles(epochs, oddball_freq)
        log_func(
            f"Extracted {len(cycle_epochs)} cycles of {1.0 / oddball_freq:.3f}s each"
        )
        noise_cov = _estimate_epochs_covariance(cycle_epochs, log_func)
        evoked = source_localization.average_cycles(cycle_epochs)
        log_func("Averaged cycles into Evoked")
        harmonic_freqs = harmonics
        if harmonic_freqs:
            log_func(
                "Reconstructing harmonics: "
                + ", ".join(f"{h:.2f}Hz" for h in harmonic_freqs)
            )
            evoked = source_localization.reconstruct_harmonics(evoked, harmonic_freqs)
        evoked = evoked.copy().crop(tmin=0.0, tmax=1.0 / oddball_freq)
        evoked = combine_evoked([evoked], weights="equal")
    
    else:
        if fif_path is None:
            raise ValueError("fif_path must be provided if epochs is None")
        evoked = _load_data(fif_path)
        if low_freq or high_freq:
            evoked = evoked.copy().filter(l_freq=low_freq, h_freq=high_freq)
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

    log_func("Preparing forward model ...")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings, log_func)
    log_func(f"Forward model ready. subjects_dir={subjects_dir}, subject={subject}")
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
        inv = mne.minimum_norm.make_inverse_operator(
            evoked.info, fwd, noise_cov, reg=0.05
        )
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
    base_name = stc_basename or "source"
    stc_path = os.path.join(output_dir, base_name)
    stc.save(stc_path)
    step += 1
    if progress_cb:
        progress_cb(step / total)

    brain = None
    if show_brain:
        _ensure_pyvista_backend()
        log_func(f"Using 3D backend: {get_current_backend()}")
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
            logger.debug(
                "Backend before stc.plot: %s (MNE_3D_BACKEND=%s QT_API=%s QT_QPA_PLATFORM=%s)",
                mne.viz.get_3d_backend(),
                os.environ.get("MNE_3D_BACKEND"),
                os.environ.get("QT_API"),
                os.environ.get("QT_QPA_PLATFORM"),
            )
            brain = _plot_with_alpha(
                stc,
                hemi=hemi,
                subjects_dir=subjects_dir,
                subject=subject,
                alpha=alpha,

            )
            logger.debug(
                "Brain alpha after plot: %s", getattr(brain, "alpha", "unknown")

            )
            logger.debug("stc.plot succeeded")
        except Exception as err:
            logger.warning(
                "hemi=%s failed: %s; backend=%s; falling back to default",
                hemi,
                err,
                mne.viz.get_3d_backend(),
            )
            logger.debug("Retrying stc.plot with default hemisphere")
            brain = _plot_with_alpha(
                stc,
                hemi="split",
                subjects_dir=subjects_dir,
                subject=subject,
                alpha=alpha,

            )
            logger.debug(
                "Brain alpha after retry: %s", getattr(brain, "alpha", "unknown")

            )
            logger.debug("stc.plot succeeded on retry")
        _set_brain_alpha(brain, alpha)
        logger.debug("Brain alpha set to %s", alpha)
        _set_brain_title(brain, os.path.basename(stc_path))
        _set_colorbar_label(brain, "Source amplitude")
        try:
            labels = mne.read_labels_from_annot(
                subject, parc="aparc", subjects_dir=subjects_dir
            )
            for label in labels:
                brain.add_label(label, borders=True)
        except Exception:
            # If annotations aren't available just continue without borders
            pass


        save_brain_screenshots(brain, output_dir)
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


def average_stc_files(stcs: list) -> mne.SourceEstimate:
    """Return the element-wise mean of multiple :class:`mne.SourceEstimate` objects.

    Parameters
    ----------
    stcs : list of :class:`mne.SourceEstimate` or file paths
        Source estimates or paths to ``.stc`` files that should be averaged.

    Returns
    -------
    :class:`mne.SourceEstimate`
        A new source estimate containing the average data.
    """

    if not stcs:
        raise ValueError("No source estimates provided")

    loaded = []
    for stc in stcs:
        if isinstance(stc, str):
            loaded.append(mne.read_source_estimate(stc))
        else:
            loaded.append(stc)

    template = loaded[0].copy()
    sum_data = np.zeros_like(template.data)
    for stc in loaded:
        sum_data += stc.data
    template.data = sum_data / len(loaded)
    return template


def average_stc_directory(
    condition_dir: str,
    *,
    output_basename: str | None = None,
    log_func: Callable[[str], None] = logger.info,
    subjects_dir: str = "",
    smooth: float = 5.0,
) -> str:
    """Average all ``*-lh.stc`` and ``*-rh.stc`` files in ``condition_dir``.

    Two files named ``<basename>-lh.stc`` and ``<basename>-rh.stc`` will be
    created where ``<basename>`` is either ``output_basename`` or ``"Average
    <folder>"`` if ``output_basename`` is ``None``.

    Parameters
    ----------
    condition_dir : str
        Directory containing the individual participant ``.stc`` files.
    output_basename : str | None
        Base name for the saved averaged files. If ``None``, ``"Average <folder>"``
        is used where ``<folder>`` is the name of ``condition_dir``.
    log_func : callable
        Optional logging function.
    subjects_dir : str
        Directory containing the MRI subjects including ``fsaverage``.
    smooth : float
        Full width at half maximum (FWHM) in millimetres used when morphing
        individual STCs to ``fsaverage``.

    Returns
    -------
    str
        Path to the saved averaged ``.stc`` file (without hemisphere suffix).
    """

    stc_paths = [
        os.path.join(condition_dir, f)
        for f in os.listdir(condition_dir)
        if f.endswith("-lh.stc") or f.endswith("-rh.stc")
    ]
    if not stc_paths:
        raise FileNotFoundError("No STC files found in directory")

    groups: dict[str, list[mne.SourceEstimate]] = {"lh": [], "rh": []}
    for path in stc_paths:
        stc = mne.read_source_estimate(path)
        hemi = "lh" if path.endswith("-lh.stc") else "rh"
        subject = os.path.basename(path).rsplit("-", 1)[0]
        stc = source_localization.morph_to_fsaverage(
            stc,
            subject,
            subjects_dir,
            smooth=smooth,
        )
        groups[hemi].append(stc)

    base = output_basename or f"Average {os.path.basename(condition_dir)}"
    out_path = os.path.join(condition_dir, base)

    lh_stc = rh_stc = None
    if groups["lh"]:
        log_func(f"Averaging {len(groups['lh'])} LH files in {condition_dir}")
        lh_stc = average_stc_files(groups["lh"])
    if groups["rh"]:
        log_func(f"Averaging {len(groups['rh'])} RH files in {condition_dir}")
        rh_stc = average_stc_files(groups["rh"])

    if lh_stc is not None:
        lh_stc.save(out_path)
    if rh_stc is not None:
        rh_stc.save(out_path)

    return out_path


def average_conditions_dir(
    results_dir: str,
    *,
    log_func: Callable[[str], None] = logger.info,
    subjects_dir: str = "",
    smooth: float = 5.0,
) -> list[str]:
    """Average STC files in each subdirectory of ``results_dir``.

    Parameters
    ----------
    results_dir : str
        Directory containing condition subfolders with ``.stc`` files.
    log_func : callable
        Optional logging function.
    subjects_dir : str
        Directory containing the MRI subjects including ``fsaverage``.
    smooth : float
        FWHM in millimetres passed through to :func:`average_stc_directory`.

    Returns
    -------
    list[str]
        Paths to the saved averaged ``.stc`` files (without hemisphere suffix).
    """

    averaged = []
    for name in sorted(os.listdir(results_dir)):
        subdir = os.path.join(results_dir, name)
        if not os.path.isdir(subdir):
            continue
        try:
            path = average_stc_directory(
                subdir,
                log_func=log_func,
                subjects_dir=subjects_dir,
                smooth=smooth,
            )
        except Exception as err:  # pragma: no cover - best effort logging
            log_func(f"Skipping {subdir}: {err}")
        else:
            averaged.append(path)
    return averaged


def run_localization_worker(
    fif_path: str,
    output_dir: str,
    *,
    queue: Queue,
    **kwargs,
) -> Tuple[str, None]:
    """Run :func:`run_source_localization` in a separate process.

    Progress updates and log messages are placed onto ``queue`` as
    dictionaries with ``{"type": "progress", "value": float}`` or
    ``{"type": "log", "message": str}``.
    """

    def _log(msg: str) -> None:
        queue.put({"type": "log", "message": msg})

    def _progress(val: float) -> None:
        queue.put({"type": "progress", "value": val})

    return run_source_localization(
        fif_path,
        output_dir,
        log_func=_log,
        progress_cb=_progress,
        show_brain=False,
        **kwargs,
    )

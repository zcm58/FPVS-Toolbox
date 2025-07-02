"""Backend routines for running eLORETA or sLORETA source localization."""

from __future__ import annotations

import os
import logging
import importlib
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
import mne
from mne import combine_evoked
from Main_App.settings_manager import SettingsManager
from . import source_localization
from .backend_utils import _ensure_pyvista_backend, get_current_backend
from .brain_utils import (
    _plot_with_alpha,
    _set_brain_alpha,
)
from .data_utils import (
    _load_data,
    _threshold_stc,
    _prepare_forward,
    _estimate_epochs_covariance,
)
from .progress import update_progress
from .stc_utils import (
    average_stc_files,
    average_stc_directory,
    average_conditions_dir,
    average_conditions_to_fsaverage,
    morph_to_fsaverage,
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

    baseline: Optional[Tuple[Optional[float], Optional[float]]] = None,

    time_window: Optional[Tuple[float, float]] = None,

    hemi: str = "split",

    log_func: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    export_rois: bool = False,
    show_brain: bool = True,
    n_jobs: Optional[int] = None,

) -> Tuple[str, Optional[mne.viz.Brain]]:
    """Run source localization on ``fif_path`` and save results to ``output_dir``.

    Parameters
    ----------
    time_window
        Optional ``(tmin_ms, tmax_ms)`` pair specifying the time range of the
        evoked response to analyze **in milliseconds**. When provided, the
        evoked data will be cropped to this window after filtering, baselining
        and harmonic reconstruction but before computing the inverse solution.
    n_jobs
        Number of CPU cores to use for processing. If ``None`` (default) the
        value is read from the ``loreta`` section of ``settings.ini``.
    """
    if log_func is None:
        log_func = logger.info

    logger.debug(
        "run_source_localization called with %s",
        {
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
            "time_window": time_window,
        },
    )

    logger.debug(
        "QT_API=%s QT_QPA_PLATFORM=%s",
        os.environ.get("QT_API"),
        os.environ.get("QT_QPA_PLATFORM"),
    )
    step = 0
    total = 7

    update_progress(step, total, progress_cb)

    if epochs is not None:
        log_func("Using in-memory epochs")
    else:
        log_func(f"Loading data from {fif_path}")
    settings = SettingsManager()
    if n_jobs is None:
        try:
            n_jobs = int(settings.get("loreta", "n_jobs", "2"))
        except ValueError:
            n_jobs = 2
    if threshold is None:
        try:
            threshold = float(settings.get("loreta", "loreta_threshold", "0.0"))
        except ValueError:
            threshold = None
    if threshold is not None and threshold != 0.0:

        logger.info("Using threshold %s", threshold)
    else:
        logger.info("No threshold will be applied")

    if time_window is None:
        start_ms = settings.get("loreta", "time_window_start_ms", "")
        end_ms = settings.get("loreta", "time_window_end_ms", "")
        try:
            if start_ms and end_ms:
                time_window = (float(start_ms), float(end_ms))
        except ValueError:
            time_window = None
    if time_window is not None:
        time_window = (time_window[0] / 1000.0, time_window[1] / 1000.0)
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
        harm_str = settings.get(
            "loreta",
            "oddball_harmonics",
            "1.2,2.4,3.6,4.8,7.2,8.4,9.6,10.8",
        )
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

    if baseline is None:
        try:
            b_start = float(settings.get("loreta", "baseline_tmin", "0"))
            b_end = float(settings.get("loreta", "baseline_tmax", "0"))
            baseline = (b_start, b_end)
        except ValueError:
            baseline = None

    noise_cov = None
    if epochs is not None:
        if oddball:
            if low_freq or high_freq:
                epochs = epochs.copy().filter(
                    l_freq=low_freq, h_freq=high_freq, n_jobs=n_jobs
                )
            if baseline is not None:
                epochs.apply_baseline(baseline)

            # compute covariance before cropping away the baseline interval
            noise_cov = _estimate_epochs_covariance(
                epochs, log_func, baseline, n_jobs=n_jobs
            )

            cycle_epochs = source_localization.extract_cycles(epochs, oddball_freq)
            log_func(
                f"Extracted {len(cycle_epochs)} cycles of {1.0 / oddball_freq:.3f}s each"
            )

            evoked = source_localization.average_cycles(cycle_epochs)
            log_func("Averaged cycles into Evoked")
            harmonic_freqs = harmonics
            if harmonic_freqs:
                log_func(
                    "Reconstructing harmonics: "
                    + ", ".join(f"{h:.2f}Hz" for h in harmonic_freqs)
                )
                evoked = source_localization.reconstruct_harmonics(evoked, harmonic_freqs)

            tmax = min(evoked.times[-1], 1.0 / oddball_freq)
            evoked = evoked.copy().crop(tmin=0.0, tmax=tmax)
            if time_window is not None:
                tmin, tmax = time_window
                evoked = evoked.copy().crop(tmin=tmin, tmax=tmax)
            evoked = combine_evoked([evoked], weights="equal")
        else:
            noise_cov = _estimate_epochs_covariance(
                epochs, log_func, baseline, n_jobs=n_jobs
            )
            evoked = epochs.average()
            if low_freq or high_freq:
                evoked = evoked.copy().filter(
                    l_freq=low_freq, h_freq=high_freq, n_jobs=n_jobs
                )
            if time_window is not None:
                tmin, tmax = time_window
                evoked = evoked.copy().crop(tmin=tmin, tmax=tmax)
    elif oddball and fif_path and fif_path.endswith("-epo.fif"):
        log_func("Oddball mode enabled. Loading epochs ...")
        epochs = mne.read_epochs(fif_path, preload=True)
        log_func(f"Loaded {len(epochs)} epoch(s)")
        if low_freq or high_freq:
            epochs = epochs.copy().filter(
                l_freq=low_freq, h_freq=high_freq, n_jobs=n_jobs
            )
        if baseline is not None:
            epochs.apply_baseline(baseline)
        # estimate covariance before segmenting into cycles
        noise_cov = _estimate_epochs_covariance(
            epochs, log_func, baseline, n_jobs=n_jobs
        )

        cycle_epochs = source_localization.extract_cycles(epochs, oddball_freq)
        log_func(
            f"Extracted {len(cycle_epochs)} cycles of {1.0 / oddball_freq:.3f}s each"
        )
        evoked = source_localization.average_cycles(cycle_epochs)
        log_func("Averaged cycles into Evoked")
        harmonic_freqs = harmonics
        if harmonic_freqs:
            log_func(
                "Reconstructing harmonics: "
                + ", ".join(f"{h:.2f}Hz" for h in harmonic_freqs)
            )
            evoked = source_localization.reconstruct_harmonics(evoked, harmonic_freqs)
        tmax = min(evoked.times[-1], 1.0 / oddball_freq)
        evoked = evoked.copy().crop(tmin=0.0, tmax=tmax)
        if time_window is not None:
            tmin, tmax = time_window
            evoked = evoked.copy().crop(tmin=tmin, tmax=tmax)
        evoked = combine_evoked([evoked], weights="equal")

    else:
        if fif_path is None:
            raise ValueError("fif_path must be provided if epochs is None")
        evoked = _load_data(fif_path)
        if low_freq or high_freq:
            evoked = evoked.copy().filter(
                l_freq=low_freq, h_freq=high_freq, n_jobs=n_jobs
            )
        if time_window is not None:
            tmin, tmax = time_window
            evoked = evoked.copy().crop(tmin=tmin, tmax=tmax)
        try:
            temp_epochs = mne.EpochsArray(
                evoked.data[np.newaxis, ...],
                evoked.info,
                tmin=evoked.times[0],
                verbose=False,
            )
            noise_cov = mne.compute_covariance(
                temp_epochs, tmax=0.0, n_jobs=n_jobs
            )
        except Exception as err:
            log_func(
                f"Noise covariance estimation failed ({err}). Using ad-hoc covariance."
            )
            noise_cov = mne.make_ad_hoc_cov(evoked.info)
    step += 1

    update_progress(step, total, progress_cb)


    log_func("Preparing forward model ...")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings, log_func)
    log_func(f"Forward model ready. subjects_dir={subjects_dir}, subject={subject}")
    step += 1

    update_progress(step, total, progress_cb)


    if oddball:
        inv = source_localization.build_inverse_operator(evoked, subjects_dir)
        step += 1
        update_progress(step, total, progress_cb)

        stc = source_localization.apply_sloreta(evoked, inv, snr)
    else:
        inv = mne.minimum_norm.make_inverse_operator(
            evoked.info, fwd, noise_cov, reg=0.05
        )
        step += 1

        update_progress(step, total, progress_cb)


        method_lower = method.lower()
        if method_lower not in {"eloreta", "sloreta"}:
            raise ValueError("Method must be 'eLORETA' or 'sLORETA'")

        log_func(f"Applying {method_lower} ...")
        mne_method = "eLORETA" if method_lower == "eloreta" else "sLORETA"
        stc = mne.minimum_norm.apply_inverse(
            evoked, inv, method=mne_method, n_jobs=n_jobs
        )
    debug = SettingsManager().debug_enabled()
    if debug:
        logger.debug(
            "STC computed: shape=%s min=%.5f max=%.5f nnz=%s",
            stc.data.shape,
            np.min(stc.data),
            np.max(stc.data),
            np.count_nonzero(stc.data),
        )
    if threshold:
        if 0 < threshold < 1:
            thr_val = threshold * np.max(np.abs(stc.data))
        else:
            thr_val = threshold

        logger.info(
            "Applying threshold %s (cutoff %.5f)", threshold, thr_val
        )
        stc = _threshold_stc(stc, threshold)
        if debug:
            logger.debug(
                "Post-threshold STC: min=%.5f max=%.5f nnz=%s",
                np.min(stc.data),
                np.max(stc.data),
                np.count_nonzero(stc.data),
            )
    else:
        logger.info("Skipping thresholding step")

    step += 1

    update_progress(step, total, progress_cb)


    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = stc_basename or "source"
    stc_path = out_dir / base_name
    stc.save(str(stc_path))
    step += 1

    update_progress(step, total, progress_cb)


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
        try:
            plotter = brain._renderer.plotter
            if hasattr(plotter, "app_window"):
                plotter.app_window.setWindowTitle(stc_path.name)
        except Exception:
            logger.debug("Could not set brain title.", exc_info=True)
        try:
            renderer = getattr(brain, "_renderer", None)
            cbar = None
            if renderer is not None:
                plotter = getattr(renderer, "plotter", None)
                cbar = getattr(plotter, "scalar_bar", None)
            if cbar is not None:
                if hasattr(cbar, "SetTitle"):
                    cbar.SetTitle("Source amplitude")
                elif hasattr(cbar, "title"):
                    cbar.title = "Source amplitude"
        except Exception:
            logger.debug("Failed to set colorbar label", exc_info=True)
        try:
            labels = mne.read_labels_from_annot(
                subject, parc="aparc", subjects_dir=subjects_dir
            )
            for label in labels:
                brain.add_label(label, borders=True)
        except Exception:
            # If annotations aren't available just continue without borders
            pass

    if export_rois:
        try:
            roi_path = Path(output_dir) / "roi_values.csv"
            source_localization.export_roi_means(stc, subject, subjects_dir, str(roi_path))
            log_func(f"ROI values exported to {roi_path}")
        except Exception as err:
            log_func(f"ROI export failed: {err}")

    step += 1

    update_progress(step, total, progress_cb)

    log_func(f"Results saved to {output_dir}")
    update_progress(total, total, progress_cb)


    return str(stc_path), brain


__all__ = [
    "run_source_localization",
    "average_stc_files",
    "average_stc_directory",
    "average_conditions_dir",
    "average_conditions_to_fsaverage",
    "morph_to_fsaverage",
]


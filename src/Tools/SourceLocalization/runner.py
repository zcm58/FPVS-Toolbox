""""Backend routines for running eLORETA source localization (oddball only)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional, Tuple

import numpy as np
import mne
from mne import combine_evoked

from Main_App import SettingsManager
from .backend_utils import get_current_backend
from .data_utils import (
    _load_data,       # kept for completeness; we enforce epochs below
    _threshold_stc,
    _prepare_forward,
    _estimate_epochs_covariance,
)
from .progress import update_progress

logger = logging.getLogger(__name__)


def _parse_event_ids_from_settings(settings: SettingsManager) -> list[int]:
    # Try common keys
    raw = settings.get("analysis", "oddball_event_ids", "")
    if not raw:
        raw = settings.get("analysis", "oddball_codes", "")
    if not raw:
        return []
    out: list[int] = []
    for tok in str(raw).replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            pass
    return out


def run_source_localization(
    fif_path: str | None,
    output_dir: str,
    *,
    epochs: mne.Epochs | None = None,
    method: str = "eLORETA",
    threshold: Optional[float] = None,
    alpha: float = 0.5,                      # viewer-only; ignored here
    stc_basename: Optional[str] = None,
    low_freq: Optional[float] = None,        # ignored in oddball ERP path
    high_freq: Optional[float] = None,       # ignored in oddball ERP path
    harmonics: Optional[list[float]] = None, # not used (removed)
    snr: Optional[float] = None,
    oddball: bool = True,                    # enforced True
    baseline: Optional[Tuple[Optional[float], Optional[float]]] = None,
    time_window: Optional[Tuple[float, float]] = None,   # seconds (0..Tpost)
    hemi: str = "split",
    log_func: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    export_rois: bool = False,               # off by default
    show_brain: bool = False,                # processing-only
) -> Tuple[str, None]:
    """Run oddball eLORETA on epochs FIF and save a 10 ms STC movie."""

    if log_func is None:
        log_func = logger.info

    # Enforce oddball-only pipeline
    if not oddball:
        log_func("Non-oddball pipeline is no longer supported. Forcing oddball=True.")
        oddball = True

    total_steps = 7
    step = 0
    update_progress(step, total_steps, progress_cb)

    settings = SettingsManager()

    # threshold
    if threshold is None:
        try:
            threshold = float(settings.get("loreta", "loreta_threshold", "0.0"))
        except Exception:
            threshold = 0.0

    # SNR -> lambda2
    if snr is None:
        try:
            snr = float(settings.get("loreta", "loreta_snr", "3.0"))
        except Exception:
            snr = 3.0
    lambda2 = 1.0 / float(snr) ** 2

    # Post-stim window
    if time_window is None:
        # UI may pass ms in settings; otherwise use oddball_freq
        try:
            odd_f = float(settings.get("analysis", "oddball_freq", "1.2"))
        except Exception:
            odd_f = 1.2
        default_tpost = max(0.1, min(1.0, 1.0 / odd_f - 0.05))
        time_window = (0.0, default_tpost)
    tmin_sec, tmax_sec = time_window

    # Load epochs
    if epochs is None:
        if not fif_path or not fif_path.endswith("-epo.fif"):
            raise ValueError("Please provide an epochs FIF (-epo.fif) or in-memory epochs.")
        log_func(f"Loading epochs from {fif_path}")
        epochs = mne.read_epochs(fif_path, preload=True)

    # Event IDs
    event_ids = _parse_event_ids_from_settings(settings)
    if not event_ids:
        raise ValueError(
            "No oddball event IDs configured. Set analysis.oddball_event_ids in settings."
        )
    event_id_map = {str(e): e for e in event_ids}

    # Baseline window
    if baseline is None:
        try:
            b_start = float(settings.get("loreta", "baseline_tmin", "-0.2"))
            b_end = float(settings.get("loreta", "baseline_tmax", "0.0"))
            baseline = (b_start, b_end)
        except Exception:
            baseline = (-0.2, 0.0)

    # Select oddball epochs and average
    log_func(f"Selecting oddball events: {event_ids}")
    epochs_oddball = epochs[event_id_map]
    if baseline is not None:
        epochs_oddball.apply_baseline(baseline)

    # Ensure no overlap with next oddball (clamp by time_window tmax)
    evoked = epochs_oddball.average()
    evoked = evoked.copy().crop(tmin=tmin_sec, tmax=tmax_sec)
    evoked = combine_evoked([evoked], weights="equal")

    step += 1
    update_progress(step, total_steps, progress_cb)

    # Forward (cached fsaverage) + noise covariance from baseline of epochs
    log_func("Preparing forward model …")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings, log_func)
    log_func(f"Forward ready (subject={subject}, subjects_dir={subjects_dir})")

    step += 1
    update_progress(step, total_steps, progress_cb)

    log_func("Estimating noise covariance from oddball baseline …")
    noise_cov = _estimate_epochs_covariance(epochs_oddball, log_func, baseline)

    step += 1
    update_progress(step, total_steps, progress_cb)

    # Inverse: eLORETA (method string case per MNE)
    log_func("Building inverse operator (eLORETA)…")
    inv = mne.minimum_norm.make_inverse_operator(evoked.info, fwd, noise_cov)

    log_func(f"Applying eLORETA (lambda2={lambda2:.4f})…")
    stc = mne.minimum_norm.apply_inverse(evoked, inv, method="eLORETA", lambda2=lambda2)

    debug = settings.debug_enabled()
    if debug:
        logger.debug(
            "STC before resample/crop: tmin=%.4f, tstep=%.6f, n_times=%d, vmax=%.3e",
            float(stc.tmin), float(stc.tstep), stc.data.shape[1], float(np.abs(stc.data).max())
        )

    step += 1
    update_progress(step, total_steps, progress_cb)

    # Standardize movie: 10 ms steps; crop to 0..tmax_sec
    stc = stc.copy().resample(100)  # 100 Hz => 10 ms
    stc = stc.crop(0.0, tmax_sec)

    # Optional threshold (fraction or absolute) against abs(data)
    if threshold and threshold > 0:
        stc = _threshold_stc(stc, threshold)
        log_func(f"Threshold applied: {threshold}")

    if debug:
        logger.debug(
            "STC after resample/crop: tmin=%.4f, tstep=%.6f, n_times=%d, vmax=%.3e",
            float(stc.tmin), float(stc.tstep), stc.data.shape[1], float(np.abs(stc.data).max())
        )

    step += 1
    update_progress(step, total_steps, progress_cb)

    # Save artifacts
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = stc_basename or "eloreta_oddball_10ms"
    stc_path = out_dir / base_name
    stc.save(str(stc_path))

    # Manifest
    manifest = {
        "method": "eLORETA",
        "lambda2": lambda2,
        "snr": snr,
        "baseline": baseline,
        "time_window": [tmin_sec, tmax_sec],
        "tmin": float(stc.tmin),
        "tstep": float(stc.tstep),
        "n_times": int(stc.data.shape[1]),
        "n_epochs": int(len(epochs_oddball)),
        "subjects_dir": subjects_dir,
        "subject": subject,
        "vmax_abs": float(np.abs(stc.data).max()),
        "backend": get_current_backend(),
        "event_ids": event_ids,
    }
    with open(out_dir / f"{base_name}.manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    step += 1
    update_progress(step, total_steps, progress_cb)

    log_func(f"Saved STC to {stc_path}")
    update_progress(total_steps, total_steps, progress_cb)
    return str(stc_path), None


__all__ = ["run_source_localization"]

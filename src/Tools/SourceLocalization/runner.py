# Backend routines for running e/sLORETA/sLORETA (oddball-focused).
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional, Tuple, Sequence, List

import numpy as np
import mne
from mne import combine_evoked

from Main_App import SettingsManager
from .backend_utils import get_current_backend
from .data_utils import (
    _load_data,
    _threshold_stc,
    _prepare_forward,
    _estimate_epochs_covariance,
)
from .progress import update_progress

logger = logging.getLogger(__name__)


def _parse_event_ids_from_settings(settings: SettingsManager) -> List[int]:
    raw = settings.get("analysis", "oddball_event_ids", "")
    if not raw:
        raw = settings.get("analysis", "oddball_codes", "")
    out: List[int] = []
    for tok in str(raw).replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            pass
    return out


def _ms_to_sec_if_needed(t: Optional[float]) -> Optional[float]:
    if t is None:
        return None
    return (t / 1000.0) if t > 5 else t


def run_source_localization(
    fif_path: str | None,
    output_dir: str,
    *,
    epochs: mne.Epochs | None = None,
    method: str = "eLORETA",                    # "eLORETA" | "sLORETA"
    threshold: Optional[float] = None,          # 0..1 frac of |max| or absolute
    alpha: float = 0.5,                          # viewer-only
    stc_basename: Optional[str] = None,
    low_freq: Optional[float] = None,
    high_freq: Optional[float] = None,
    harmonics: Optional[Sequence[float]] = None,
    snr: Optional[float] = None,
    oddball: bool = True,
    baseline: Optional[Tuple[Optional[float], Optional[float]]] = None,
    time_window: Optional[Tuple[float, float]] = None,   # GUI passes ms
    hemi: str = "split",
    log_func: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    export_rois: bool = False,
    show_brain: bool = False,
    event_ids: Optional[Sequence[int]] = None,  # override settings
) -> Tuple[str, None]:
    """
    1) Load epochs; select oddball; baseline-correct
    2) Forward (fsaverage) + covariance
    3) Inverse (pick_ori='normal'), resample to 10 ms, crop
    4) Threshold → save STC (fsaverage)
    """
    if log_func is None:
        log_func = logger.info

    if not oddball:
        log_func("Non-oddball pipeline not supported here. Forcing oddball=True.")
        oddball = True

    total_steps = 7
    step = 0
    update_progress(step, total_steps, progress_cb)

    settings = SettingsManager()

    if threshold is None:
        try:
            threshold = float(settings.get("loreta", "loreta_threshold", "0.0"))
        except Exception:
            threshold = 0.0

    if snr is None:
        try:
            snr = float(settings.get("loreta", "loreta_snr", "3.0"))
        except Exception:
            snr = 3.0
    lambda2 = 1.0 / float(snr) ** 2

    if time_window is None:
        try:
            odd_f = float(settings.get("analysis", "oddball_freq", "1.2"))
        except Exception:
            odd_f = 1.2
        default_tpost = max(0.1, min(1.0, 1.0 / odd_f - 0.05))
        tmin_sec, tmax_sec = 0.0, default_tpost
    else:
        tmin_sec, tmax_sec = time_window
        tmin_sec = _ms_to_sec_if_needed(tmin_sec)
        tmax_sec = _ms_to_sec_if_needed(tmax_sec)

    # ---- Load epochs
    if epochs is None:
        if not fif_path or not fif_path.endswith("-epo.fif"):
            raise ValueError("Please provide an epochs FIF (-epo.fif) or in-memory epochs.")
        log_func(f"Loading epochs from {fif_path}")
        epochs = mne.read_epochs(fif_path, preload=True)

    # ---- Oddball IDs: override → settings → auto label match (contains 'oddball')
    ids = [int(x) for x in (event_ids or [])]
    if not ids:
        ids = _parse_event_ids_from_settings(settings)
    if not ids:
        labels = epochs.event_id or {}
        ids = [code for name, code in labels.items() if "oddball" in name.lower()]
        if ids:
            log_func(f"Auto-detected oddball labels → IDs: {ids}")
    if not ids:
        raise ValueError("No oddball event IDs configured. Set analysis.oddball_event_ids in settings or via dialog.")

    # ---- Robust selection (boolean mask on events column 2)
    ev_codes = epochs.events[:, 2]
    mask = np.isin(ev_codes, ids)
    if not np.any(mask):
        raise ValueError(f"No epochs match oddball IDs {ids}. Present codes: {sorted(set(ev_codes.tolist()))}")
    log_func(f"Selecting oddball events: {ids} (n={int(mask.sum())}/{len(ev_codes)})")
    epochs_oddball = epochs.copy()[mask]

    # ---- Baseline & average, crop to window
    if baseline is None:
        try:
            b_start = float(settings.get("loreta", "baseline_tmin", "-0.2"))
            b_end = float(settings.get("loreta", "baseline_tmax", "0.0"))
            baseline = (b_start, b_end)
        except Exception:
            baseline = (-0.2, 0.0)
    if baseline is not None:
        epochs_oddball.apply_baseline(baseline)

    evoked = epochs_oddball.average().copy().crop(tmin=float(tmin_sec), tmax=float(tmax_sec))
    evoked = combine_evoked([evoked], weights="equal")

    step += 1
    update_progress(step, total_steps, progress_cb)

    # ---- Forward + covariance
    log_func("Preparing forward model …")
    fwd, subject, subjects_dir = _prepare_forward(evoked, settings, log_func)
    log_func(f"Forward ready (subject={subject}, subjects_dir={subjects_dir})")

    step += 1
    update_progress(step, total_steps, progress_cb)

    log_func("Estimating noise covariance from oddball baseline …")
    noise_cov = _estimate_epochs_covariance(epochs_oddball, log_func, baseline)

    step += 1
    update_progress(step, total_steps, progress_cb)

    # ---- Inverse (e/sLORETA)
    method_str = str(method)
    log_func(f"Building inverse operator ({method_str}) …")
    inv = mne.minimum_norm.make_inverse_operator(
        evoked.info, fwd, noise_cov, loose=0.2, depth=0.8
    )

    log_func(f"Applying {method_str} (lambda2={lambda2:.4f}) …")
    stc = mne.minimum_norm.apply_inverse(
        evoked, inv, method=method_str, lambda2=lambda2, pick_ori="normal"
    )
    stc.subject = subject

    if settings.debug_enabled():
        logger.debug(
            "STC pre-resample: tmin=%.4f, tstep=%.6f, n_times=%d, vmax=%.3e",
            float(stc.tmin), float(stc.tstep), stc.data.shape[1], float(np.abs(stc.data).max())
        )

    step += 1
    update_progress(step, total_steps, progress_cb)

    # ---- Standardize to 10 ms frames and crop
    stc = stc.copy().resample(100)  # 10 ms steps
    stc = stc.crop(0.0, float(tmax_sec))

    # ---- Ensure fsaverage space
    if subject != "fsaverage":
        morph = mne.compute_source_morph(
            stc, subject_from=subject, subject_to="fsaverage", subjects_dir=subjects_dir
        )
        stc = morph.apply(stc)
        subject = "fsaverage"
    stc.subject = subject

    # ---- Threshold
    if threshold and threshold > 0:
        stc = _threshold_stc(stc, float(threshold))
        log_func(f"Threshold applied: {threshold}")

    if settings.debug_enabled():
        logger.debug(
            "STC post-crop: tmin=%.4f, tstep=%.6f, n_times=%d, vmax=%.3e",
            float(stc.tmin), float(stc.tstep), stc.data.shape[1], float(np.abs(stc.data).max())
        )

    step += 1
    update_progress(step, total_steps, progress_cb)

    # ---- Save
    out_dir = Path(output_dir); out_dir.mkdir(parents=True, exist_ok=True)
    base_name = stc_basename or "eloreta_oddball_10ms"
    stc_path = out_dir / base_name
    stc.save(str(stc_path), ftype="stc", overwrite=True)

    manifest = {
        "method": method_str,
        "lambda2": float(lambda2),
        "snr": float(snr),
        "baseline": [float(baseline[0]) if baseline and baseline[0] is not None else None,
                     float(baseline[1]) if baseline and baseline[1] is not None else None],
        "time_window_sec": [float(tmin_sec), float(tmax_sec)],
        "tmin": float(stc.tmin),
        "tstep": float(stc.tstep),
        "n_times": int(stc.data.shape[1]),
        "n_epochs": int(len(epochs_oddball)),
        "subjects_dir": str(subjects_dir),
        "subject": subject,
        "vmax_abs": float(np.abs(stc.data).max()),
        "backend": get_current_backend(),
        "event_ids": list(ids),
    }
    with open(out_dir / f"{base_name}.manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    step += 1
    update_progress(step, total_steps, progress_cb)

    log_func(f"Saved STC to {stc_path}")
    update_progress(total_steps, total_steps, progress_cb)
    return str(stc_path), None


__all__ = ["run_source_localization"]

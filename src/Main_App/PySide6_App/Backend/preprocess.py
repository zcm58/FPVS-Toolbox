# -*- coding: utf-8 -*-
"""
Qt-side preprocessor that exactly mirrors the legacy logic:
- EXG1/EXG2 kept as EEG (for mastoids); EXG3–EXG8 set to 'misc'
- Optional mastoid ref (if EXG1 & EXG2 present)
- Optional channel drop by index while preserving the stim channel
- Downsample ONLY if current sfreq > target (skip if equal; never upsample)
- FIR filter: filter_length=8449, l/h trans bandwidths=0.1 Hz, Hamming, zero-double
- Kurtosis-based bad detection with 10% trimmed stats, then interpolate if montage exists
- Final average reference over good EEG channels
Returns (raw, num_kurtosis_bads)
"""

from __future__ import annotations

import os
import traceback
from typing import Dict, Any, Callable, Optional, Tuple

import mne
import numpy as np
from scipy.stats import kurtosis

import config


def _basename_from_raw(raw) -> str:
    if getattr(raw, "filenames", None) and raw.filenames and raw.filenames[0]:
        return os.path.basename(raw.filenames[0])
    if getattr(raw, "filename", None):
        return os.path.basename(raw.filename)
    return "UnknownFile"


def perform_preprocessing(
    raw_input: mne.io.BaseRaw,
    params: Dict[str, Any],
    log_func: Callable[[str], None],
    filename_for_log: Optional[str] = None,
) -> Tuple[Optional[mne.io.BaseRaw], int]:
    raw = raw_input
    fname = filename_for_log or _basename_from_raw(raw)

    # Params (use same names as legacy)
    downsample_rate = params.get("downsample_rate")
    low_pass        = params.get("low_pass")       # e.g. 0.1
    high_pass       = params.get("high_pass")      # e.g. 40 or 50
    reject_thresh   = params.get("reject_thresh")
    ref1            = params.get("ref_channel1")
    ref2            = params.get("ref_channel2")
    max_keep        = params.get("max_idx_keep")
    stim_ch         = params.get("stim_channel", config.DEFAULT_STIM_CHANNEL)

    try:
        ch_names = list(raw.info["ch_names"])
        log_func(f"Preprocessing {len(ch_names)} chans from '{fname}'...")

        # EXG3–EXG8 should not be treated as EEG (avoids montage complaints)
        exg_misc = {f"EXG{i}": "misc" for i in range(3, 9)}
        present_misc = {k: v for k, v in exg_misc.items() if k in ch_names}
        if present_misc:
            try:
                raw.set_channel_types(present_misc, verbose=False)
            except Exception:
                pass  # non-fatal

        # Optional initial mastoid reference
        if ref1 and ref2 and ref1 in ch_names and ref2 in ch_names:
            try:
                log_func(f"Applying reference: Subtract average of {ref1} & {ref2} for {fname}...")
                raw.set_eeg_reference(ref_channels=[ref1, ref2], projection=False, verbose=False)
                log_func(f"Initial reference applied to {fname}.")
            except Exception as e:
                log_func(f"Warn: Initial reference failed for {fname}: {e}")
        else:
            log_func(
                f"Skip initial referencing for {fname} (Ref channels '{ref1}', '{ref2}' not found or not specified)."
            )

        # Optional channel drop by index, but always preserve stim channel if present
        before = list(raw.info["ch_names"])
        if max_keep is not None and 0 < max_keep < len(before):
            keep = before[:max_keep]
            if stim_ch in before and stim_ch not in keep:
                keep.append(stim_ch)
            drop = [c for c in before if c not in set(keep)]
            if drop:
                log_func(f"Attempting to drop {len(drop)} channels from {fname}...")
                raw.drop_channels(drop, on_missing="warn")
                log_func(f"{len(raw.ch_names)} channels remain in {fname} after drop operation.")
            else:
                log_func(f"No channels were ultimately selected to be dropped for {fname}.")
        else:
            log_func(
                f"Skip channel drop based on max_keep for {fname} (max_keep is None, 0, or >= num channels). "
                f"Current channels: {len(before)}"
            )

        # Downsample ONLY if current sfreq > target; skip if equal (never upsample)
        sf = float(raw.info["sfreq"])
        if downsample_rate:
            log_func(f"Downsample check for {fname}: Curr {sf:.1f}Hz, Tgt {downsample_rate}Hz.")
            try:
                ds = float(downsample_rate)
                if sf > ds:
                    raw.resample(ds, npad="auto", window="hann", n_jobs=1, verbose=False)
                    log_func(f"Resampled {fname} to {raw.info['sfreq']:.1f}Hz.")
                elif abs(sf - ds) < 1e-6:
                    log_func(f"Already at {downsample_rate}Hz; skipping resample for {fname}.")
                else:
                    log_func(f"Current rate {sf:.1f}Hz < target; no upsampling performed for {fname}.")
            except Exception as e:
                log_func(f"Warn: Resampling failed for {fname}: {e}")
        else:
            log_func(f"Skip downsample for {fname}.")

        # === EXACT legacy FIR settings ===
        # (Legacy uses variable names where l_freq=low_pass, h_freq=high_pass)
        l_freq = low_pass if (low_pass and low_pass > 0) else None
        h_freq = high_pass
        if l_freq or h_freq:
            try:
                low_trans_bw       = 0.1
                high_trans_bw      = 0.1
                filter_len_points  = 8449
                log_func(f"Filtering {fname} ({l_freq if l_freq else 'DC'}-{h_freq if h_freq else 'Nyq'}Hz) ...")
                raw.filter(
                    l_freq, h_freq,
                    method="fir",
                    phase="zero-double",
                    fir_window="hamming",
                    fir_design="firwin",
                    l_trans_bandwidth=low_trans_bw,
                    h_trans_bandwidth=high_trans_bw,
                    filter_length=filter_len_points,
                    skip_by_annotation="edge",
                    n_jobs=1,
                    verbose=False,
                )
                log_func(f"Filter OK for {fname}.")
            except Exception as e:
                log_func(f"Warn: Filter failed for {fname}: {e}")
        else:
            log_func(f"Skip filter for {fname}.")

        # Kurtosis bads (10% trimmed stats), then interpolate if possible
        num_kurtosis_bads = 0
        if reject_thresh:
            log_func(f"Kurtosis rejection for {fname} (Z > {reject_thresh})...")
            eeg_picks = mne.pick_types(
                raw.info, eeg=True,
                exclude=raw.info["bads"] + ([stim_ch] if stim_ch in raw.ch_names else [])
            )
            if len(eeg_picks) >= 2:
                data = raw.get_data(picks=eeg_picks)
                k = kurtosis(data, axis=1, fisher=True, bias=False)
                k = np.nan_to_num(k)

                n = len(k)
                trim = int(np.floor(n * 0.1))
                bad_auto = []
                if n - 2 * trim > 1:
                    k_sorted  = np.sort(k)
                    k_trimmed = k_sorted[trim:n - trim]
                    m_t, s_t  = float(np.mean(k_trimmed)), float(np.std(k_trimmed))
                    log_func(f"Trimmed Norm for {fname}: Mean={m_t:.3f}, Std={s_t:.3f} (N_trimmed={len(k_trimmed)})")
                    if s_t > 1e-9:
                        z = (k - m_t) / s_t
                        idx = np.where(np.abs(z) > reject_thresh)[0]
                        pick_names = [raw.info["ch_names"][i] for i in eeg_picks]
                        bad_auto = [pick_names[i] for i in idx]
                    else:
                        log_func(f"Kurtosis Trimmed Std Dev near zero for {fname}.")
                else:
                    log_func(f"Not enough data for Kurtosis trimmed stats in {fname} (N_k={n}).")

                if bad_auto:
                    log_func(f"Bad by Kurtosis for {fname}: {bad_auto}")
                else:
                    log_func(f"No channels bad by Kurtosis for {fname}.")

                new_bads = [b for b in bad_auto if b not in raw.info["bads"]]
                if new_bads:
                    raw.info["bads"].extend(new_bads)
                num_kurtosis_bads = len(new_bads)

                if raw.info["bads"]:
                    log_func(f"Interpolating bads in {fname}: {raw.info['bads']}")
                    if raw.get_montage():
                        try:
                            raw.interpolate_bads(reset_bads=True, mode="accurate", verbose=False)
                            log_func(f"Interpolation OK for {fname}.")
                        except Exception as e:
                            log_func(f"Warn: Interpolation failed for {fname}: {e}")
                    else:
                        log_func(f"Warn: No montage for {fname}, cannot interpolate. Bads remain: {raw.info['bads']}")
                else:
                    log_func(f"No bads to interpolate in {fname}.")
            else:
                log_func(f"Skip Kurtosis for {fname} ( < 2 good EEG channels).")
        else:
            log_func(f"Skip Kurtosis for {fname} (no threshold).")

        # Final average ref
        try:
            log_func(f"Applying average reference to {fname}...")
            eeg_picks_for_ref = mne.pick_types(raw.info, eeg=True, exclude=raw.info["bads"])
            if len(eeg_picks_for_ref) > 0:
                raw.set_eeg_reference(ref_channels="average", picks=eeg_picks_for_ref, projection=True, verbose=False)
                raw.apply_proj(verbose=False)
                log_func(f"Average reference applied to {fname}.")
            else:
                log_func(f"Skip average ref for {fname}: No good EEG channels.")
        except Exception as e:
            log_func(f"Warn: Average reference failed for {fname}: {e}")

        log_func(f"Preprocessing OK for {fname}. {len(raw.ch_names)} channels, {raw.info['sfreq']:.1f}Hz.")
        return raw, num_kurtosis_bads

    except Exception as e:
        log_func(f"!!! CRITICAL Preprocessing error for {fname}: {e}")
        log_func(f"Traceback: {traceback.format_exc()}")
        return None, 0

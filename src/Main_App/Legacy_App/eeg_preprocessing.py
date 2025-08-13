# src/Main_App/eeg_preprocessing.py
# -*- coding: utf-8 -*-
"""
Handles the EEG preprocessing pipeline for the FPVS Toolbox.
Adds a cached standard 10–20 montage factory to reduce RAM/CPU overhead
without changing the preprocessing order or behavior.
"""
from __future__ import annotations

import logging
import traceback
from functools import lru_cache
from typing import Any, Callable, Optional, Tuple

import mne
import numpy as np
from scipy.stats import kurtosis

logger = logging.getLogger(__name__)

__all__ = [
    "perform_preprocessing",
    "get_cached_standard_montage",
    "attach_cached_montage_if_missing",
]

# Import configuration with a graceful fallback when run standalone
try:
    import config
except ImportError:  # pragma: no cover - fallback for isolated execution
    class _DummyConfig:
        DEFAULT_STIM_CHANNEL = "Status"

    config = _DummyConfig()
    logger.warning(
        "Warning [eeg_preprocessing.py]: Could not import config. Using '%s'.",
        config.DEFAULT_STIM_CHANNEL,
    )


# -----------------------------------------------------------------------------
# Montage caching (no behavioral change to preprocessing; callers may use this)
# -----------------------------------------------------------------------------
@lru_cache(maxsize=8)
def get_cached_standard_montage(name: str = "standard_1020") -> Any:
    """
    Return a cached standard montage object (e.g., 'standard_1020').

    This avoids rebuilding/loading the montage repeatedly across workers/files.
    """
    mont = mne.channels.make_standard_montage(name)
    logger.debug("Montage cache: returning '%s' (cache size up to 8).", name)
    return mont


def attach_cached_montage_if_missing(
    raw: mne.io.BaseRaw,
    name: str = "standard_1020",
    on_missing: str = "warn",
) -> None:
    """
    Attach a cached montage to 'raw' only if none is present.
    DOES NOT change the existing preprocessing order; helper for callers.

    Note: Not invoked internally by 'perform_preprocessing' to preserve behavior.
    """
    try:
        if raw.get_montage() is None:
            raw.set_montage(get_cached_standard_montage(name), on_missing=on_missing, verbose=False)
            logger.debug("Cached montage '%s' attached to Raw (on_missing=%s).", name, on_missing)
    except Exception as e:
        logger.warning("Failed to attach cached montage '%s': %s", name, e)


def perform_preprocessing(
    raw_input: mne.io.BaseRaw,
    params: dict,
    log_func: Callable[[str], None],
    filename_for_log: str = "UnknownFile",
) -> Tuple[Optional[mne.io.BaseRaw], int]:
    """
    Applies preprocessing steps to the raw MNE object.

    Args:
        raw_input (mne.io.BaseRaw): The raw MNE data object to process (should be a copy).
        params (dict): Expected keys:
            'downsample_rate', 'low_pass', 'high_pass', 'reject_thresh',
            'ref_channel1', 'ref_channel2', 'max_idx_keep',
            'stim_channel' (optional).
        log_func (callable): Logger (e.g., app.log).
        filename_for_log (str): Filename for log context.

    Returns:
        tuple[mne.io.BaseRaw|None, int]: (processed raw, n_bad_by_kurtosis)
    """
    raw = raw_input
    downsample_rate = params.get('downsample_rate')
    low_pass = params.get('low_pass')          # LPF upper edge (e.g., 50.0)
    high_pass = params.get('high_pass')        # HPF lower edge (e.g., 0.1)
    reject_thresh = params.get('reject_thresh')
    ref1 = params.get('ref_channel1')
    ref2 = params.get('ref_channel2')
    max_keep = params.get('max_idx_keep')
    stim_ch = params.get('stim_channel', config.DEFAULT_STIM_CHANNEL)

    num_kurtosis_bads_identified = 0

    try:
        orig_ch_names = list(raw.info['ch_names'])
        log_func(f"Preprocessing {len(orig_ch_names)} chans from '{filename_for_log}'...")
        log_func(f"DEBUG [preprocess for {filename_for_log}]: Initial channel names ({len(orig_ch_names)}): {orig_ch_names}")
        log_func(f"DEBUG [preprocess for {filename_for_log}]: Expected stim_ch: '{stim_ch}', max_idx_keep: {max_keep}")
        if stim_ch not in orig_ch_names:
            log_func(f"DEBUG [preprocess for {filename_for_log}]: WARNING - Expected stim_ch '{stim_ch}' is NOT in initial channel list.")

        # 1) Initial reference (EXG1/EXG2)
        if ref1 and ref2 and ref1 in orig_ch_names and ref2 in orig_ch_names:
            try:
                log_func(f"Applying reference: Subtract average of {ref1} & {ref2} for {filename_for_log}...")
                raw.set_eeg_reference(ref_channels=[ref1, ref2], projection=False, verbose=False)
                log_func(f"Initial reference applied to {filename_for_log}.")
            except Exception as e:
                log_func(f"Warn: Initial reference failed for {filename_for_log}: {e}")
        else:
            log_func(f"Skip initial referencing for {filename_for_log} (Ref channels '{ref1}', '{ref2}' not found or not specified).")

        # 2) Drop EXG1/EXG2 now that referencing is applied (reduces work for filter)
        for ch in ("EXG1", "EXG2"):
            if ch in raw.ch_names:
                raw.drop_channels([ch])
                log_func(f"Dropped {ch} after referencing.")

        # 3) Optional channel limit (keeps stim if present)
        current_names_before_drop = list(raw.info['ch_names'])
        log_func(f"DEBUG [preprocess for {filename_for_log}]: Channel names BEFORE drop logic ({len(current_names_before_drop)}): {current_names_before_drop}")
        if max_keep is not None and 0 < max_keep < len(current_names_before_drop):
            channels_to_keep_by_index = current_names_before_drop[:max_keep]
            final_keep = list(channels_to_keep_by_index)
            if stim_ch in current_names_before_drop and stim_ch not in final_keep:
                final_keep.append(stim_ch)
                log_func(f"DEBUG [preprocess for {filename_for_log}]: Stim_ch '{stim_ch}' added to keep list.")
            unique_keep = set(final_keep)
            ordered_keep = [nm for nm in current_names_before_drop if nm in unique_keep]
            to_drop = [nm for nm in current_names_before_drop if nm not in ordered_keep]
            log_func(f"DEBUG [preprocess for {filename_for_log}]: Final KEEP ({len(ordered_keep)}): {ordered_keep}")
            log_func(f"DEBUG [preprocess for {filename_for_log}]: Final DROP ({len(to_drop)}): {to_drop}")
            if to_drop:
                log_func(f"Attempting to drop {len(to_drop)} channels from {filename_for_log}...")
                raw.drop_channels(to_drop, on_missing='warn')
                log_func(f"{len(raw.ch_names)} channels remain in {filename_for_log} after drop.")
                log_func(f"DEBUG [preprocess for {filename_for_log}]: Channel names AFTER drop: {list(raw.info['ch_names'])}")
            else:
                log_func(f"No channels selected to be dropped for {filename_for_log}.")
        else:
            log_func(f"Skip channel drop for {filename_for_log} (max_keep: {max_keep}). Current channels: {len(current_names_before_drop)}")

        # 4) FILTER @ native Fs (EEGLAB-like): high_pass = l_freq, low_pass = h_freq
        l_freq = high_pass if (high_pass is not None and high_pass > 0) else None  # HPF
        h_freq = low_pass if (low_pass is not None and low_pass > 0) else None     # LPF
        if l_freq is not None or h_freq is not None:
            try:
                # Use zero-phase Hamming FIR to match EEGLAB behavior closely
                log_func(f"Filtering {filename_for_log} ({l_freq if l_freq is not None else 'DC'}-{h_freq if h_freq is not None else 'Nyq'}Hz) ...")
                raw.filter(
                    l_freq=l_freq,
                    h_freq=h_freq,
                    picks='eeg',
                    method='fir',
                    phase='zero-double',
                    fir_window='hamming',
                    fir_design='firwin',
                    filter_length='auto',
                    l_trans_bandwidth=0.1 if l_freq else 'auto',
                    h_trans_bandwidth=0.1 if h_freq else 'auto',
                    skip_by_annotation='edge',
                    n_jobs=1,
                    verbose=False,
                )
                log_func(f"Filter OK for {filename_for_log}.")
            except Exception as e:
                log_func(f"Warn: Filter failed for {filename_for_log}: {e}")
        else:
            log_func(f"Skip filter for {filename_for_log}.")

        # 5) DOWNSAMPLE after filtering (alias-safe)
        if downsample_rate:
            sf = float(raw.info['sfreq'])
            log_func(f"Downsample check for {filename_for_log}: Curr {sf:.1f}Hz, Tgt {downsample_rate}Hz.")
            if sf > float(downsample_rate):
                try:
                    raw.resample(int(downsample_rate), n_jobs=1, npad="auto", window='hann', verbose=False)
                    log_func(f"Resampled {filename_for_log} to {raw.info['sfreq']:.1f}Hz.")
                except Exception as resample_err:
                    log_func(f"Warn: Resampling failed for {filename_for_log}: {resample_err}")
            else:
                log_func(f"No downsampling needed for {filename_for_log}.")
        else:
            log_func(f"Skip downsample for {filename_for_log}.")

        # 6) Kurtosis rejection & interpolation
        if reject_thresh:
            log_func(f"Kurtosis rejection for {filename_for_log} (Z > {reject_thresh})...")
            bad_k_auto = []
            eeg_picks = mne.pick_types(
                raw.info, eeg=True,
                exclude=raw.info['bads'] + ([stim_ch] if (stim_ch in raw.ch_names and raw.get_channel_types(picks=stim_ch)[0] != 'eeg') else [])
            )
            if len(eeg_picks) >= 2:
                data = raw.get_data(picks=eeg_picks)
                k_values = kurtosis(data, axis=1, fisher=True, bias=False)
                k_values = np.nan_to_num(k_values)
                proportion_to_cut = 0.1
                n_k = len(k_values)
                trim_count = int(np.floor(n_k * proportion_to_cut))
                if n_k - 2 * trim_count > 1:
                    k_sorted = np.sort(k_values)
                    k_trimmed = k_sorted[trim_count: n_k - trim_count]
                    m_trimmed, s_trimmed = np.mean(k_trimmed), np.std(k_trimmed)
                    log_func(f"Trimmed Norm for {filename_for_log}: Mean={m_trimmed:.3f}, Std={s_trimmed:.3f} (N_trimmed={len(k_trimmed)})")
                    if s_trimmed > 1e-9:
                        z_scores = (k_values - m_trimmed) / s_trimmed
                        bad_idx = np.where(np.abs(z_scores) > reject_thresh)[0]
                        ch_names_pick = [raw.info['ch_names'][i] for i in eeg_picks]
                        bad_k_auto = [ch_names_pick[i] for i in bad_idx]
                    else:
                        log_func(f"Kurtosis Trimmed Std Dev near zero for {filename_for_log}.")
                else:
                    log_func(f"Not enough data for Kurtosis trimmed stats in {filename_for_log} (N_k={n_k}).")
                num_kurtosis_bads_identified = len(bad_k_auto)
                if bad_k_auto:
                    log_func(f"Bad by Kurtosis for {filename_for_log}: {bad_k_auto} (Count: {num_kurtosis_bads_identified})")
                else:
                    log_func(f"No channels bad by Kurtosis for {filename_for_log}.")
            else:
                log_func(f"Skip Kurtosis for {filename_for_log} ( < 2 good EEG channels).")

            new_bads = [b for b in (bad_k_auto if reject_thresh else []) if b not in raw.info['bads']]
            if new_bads:
                raw.info['bads'].extend(new_bads)

            if raw.info['bads']:
                log_func(f"Interpolating bads in {filename_for_log}: {raw.info['bads']}")
                if raw.get_montage():
                    try:
                        raw.interpolate_bads(reset_bads=True, mode='accurate', verbose=False)
                        log_func(f"Interpolation OK for {filename_for_log}.")
                    except Exception as e:
                        log_func(f"Warn: Interpolation failed for {filename_for_log}: {e}")
                else:
                    log_func(f"Warn: No montage for {filename_for_log}, cannot interpolate. Bads remain: {raw.info['bads']}")
            else:
                log_func(f"No bads to interpolate in {filename_for_log}.")
        else:
            log_func(f"Skip Kurtosis for {filename_for_log} (no threshold).")

        # 7) Average reference (final)
        try:
            log_func(f"Applying average reference to {filename_for_log}...")
            eeg_picks_for_ref = mne.pick_types(raw.info, eeg=True, exclude=raw.info['bads'])
            if len(eeg_picks_for_ref) > 0:
                raw.set_eeg_reference(ref_channels='average', projection=True, verbose=False)
                raw.apply_proj(verbose=False)
                log_func(f"Average reference applied to {filename_for_log}.")
            else:
                log_func(f"Skip average ref for {filename_for_log}: No good EEG channels.")
        except Exception as e:
            log_func(f"Warn: Average reference failed for {filename_for_log}: {e}")

        log_func(f"Preprocessing OK for {filename_for_log}. {len(raw.ch_names)} channels, {raw.info['sfreq']:.1f}Hz.")
        final_ch_names = list(raw.info['ch_names'])
        log_func(f"DEBUG [preprocess for {filename_for_log}]: Final channel names before returning ({len(final_ch_names)}): {final_ch_names}")
        if stim_ch in final_ch_names:
            log_func(f"DEBUG [preprocess for {filename_for_log}]: Expected stim_ch '{stim_ch}' IS PRESENT at VERY END.")
        else:
            log_func(f"DEBUG [preprocess for {filename_for_log}]: CRITICAL! Expected stim_ch '{stim_ch}' IS NOT PRESENT at VERY END.")

        return raw, num_kurtosis_bads_identified

    except Exception as e:
        log_func(f"!!! CRITICAL Preprocessing error for {filename_for_log}: {e}")
        log_func(f"Traceback: {traceback.format_exc()}")
        return None, num_kurtosis_bads_identified

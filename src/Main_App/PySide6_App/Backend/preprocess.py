# -*- coding: utf-8 -*-
"""
Qt-side preprocessing that mirrors the legacy logic exactly.

Order (legacy parity):
1) Initial reference (user-selected pair; defaults set via settings UI)
2) Drop the selected reference pair channels
3) Optional channel limit (max_idx_keep; keep stim if needed)
4) Downsample (if requested)
5) FIR filter (legacy mapping and kernel)
6) Kurtosis-based rejection & interpolation
7) Final average reference

Returns (processed_raw_or_none, n_bad_by_kurtosis)
"""
from __future__ import annotations

import logging
import traceback
from typing import Callable, Optional, Tuple, Dict, Any, List

import mne
import numpy as np
from scipy.stats import kurtosis

from Main_App.PySide6_App.utils.audit import (
    start_preproc_audit,
    end_preproc_audit,
    compare_preproc,
)

logger = logging.getLogger(__name__)

__all__ = ["perform_preprocessing", "begin_preproc_audit", "finalize_preproc_audit"]

# Import configuration with a graceful fallback when run standalone
try:
    import config  # type: ignore
except Exception:  # pragma: no cover - fallback for isolated execution
    class _DummyConfig:
        DEFAULT_STIM_CHANNEL = "Status"

    config = _DummyConfig()
    logger.warning(
        "Warning [preprocess.py]: Could not import config. Using '%s'.",
        config.DEFAULT_STIM_CHANNEL,
    )


def begin_preproc_audit(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
    filename: str,
) -> Dict[str, Any]:
    """Capture baseline audit metadata before preprocessing mutates the Raw."""
    capture = start_preproc_audit(raw, params)
    capture["file"] = filename
    return capture


def finalize_preproc_audit(
    before: Dict[str, Any],
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
    filename: str,
    *,
    events_info: Optional[Dict[str, Any]] = None,
    fif_written: int = 0,
    n_rejected: int = 0,
) -> Tuple[Dict[str, Any], List[str]]:
    """Compute the post-state audit and log structured results."""
    after = end_preproc_audit(
        raw,
        params,
        filename=filename,
        events_info=events_info,
        fif_written=fif_written,
        n_rejected=n_rejected,
    )
    problems = compare_preproc(before, after, params, events_info=events_info)
    if problems:
        logger.warning(
            "preproc_audit_mismatch",
            extra={"file": filename, "problems": problems, "audit": after},
        )
    else:
        logger.info("preproc_audit", extra={"file": filename, "audit": after})
    return after, problems


def _coerce_refs_to_eeg_if_needed(raw: mne.io.BaseRaw, pair: tuple[str, str]) -> List[str]:
    """If selected ref channels are not typed as EEG, coerce them to EEG so MNE can reference them."""
    changed: List[str] = []
    try:
        ch_types = dict(zip(raw.ch_names, raw.get_channel_types()))
    except Exception:
        ch_types = {}
    to_flip: Dict[str, str] = {}
    for ch in pair:
        if ch in raw.ch_names and ch_types.get(ch) != "eeg":
            to_flip[ch] = "eeg"
    if to_flip:
        raw.set_channel_types(to_flip)
        changed = list(to_flip)
    return changed


def perform_preprocessing(
    raw_input: mne.io.BaseRaw,
    params: Dict[str, Any],
    log_func: Callable[[str], None],
    filename_for_log: str = "UnknownFile",
) -> Tuple[Optional[mne.io.BaseRaw], int]:
    """
    Apply preprocessing steps to the raw MNE object (legacy parity).

    Args:
        raw_input: Raw MNE data to process (modified in place).
        params: Expected keys:
            'downsample_rate', 'low_pass', 'high_pass', 'reject_thresh',
            'ref_channel1', 'ref_channel2', 'max_idx_keep', 'stim_channel' (optional).
            Note: defaults for ref_channel1/ref_channel2 come from the settings UI at runtime.
        log_func: Logger function (e.g., app.log).
        filename_for_log: For log context.

    Returns:
        (processed_raw_or_none, n_bad_by_kurtosis)
    """
    raw = raw_input

    # Runtime parameters (defaults are managed by Settings UI; fall back only if absent)
    downsample_rate = params.get("downsample_rate")
    low_pass = params.get("low_pass")          # legacy mapping: low_pass -> l_freq
    high_pass = params.get("high_pass")        # legacy mapping: high_pass -> h_freq
    reject_thresh = params.get("reject_thresh")
    ref1 = params.get("ref_channel1") or "EXG1"
    ref2 = params.get("ref_channel2") or "EXG2"
    max_keep = params.get("max_idx_keep")
    stim_ch = params.get("stim_channel", config.DEFAULT_STIM_CHANNEL)

    num_kurtosis_bads_identified = 0

    try:
        orig_ch_names = list(raw.info["ch_names"])
        orig_sfreq = float(raw.info["sfreq"])
        log_func(
            f"Preprocessing {len(orig_ch_names)} chans from '{filename_for_log}' "
            f"(sfreq={orig_sfreq:.3f} Hz)..."
        )
        print(
            f"[REF DEBUG] {filename_for_log}: "
            f"ref1={ref1!r} present1={ref1 in orig_ch_names}, "
            f"ref2={ref2!r} present2={ref2 in orig_ch_names}, "
            f"n_ch={len(orig_ch_names)}"
        )
        log_func(
            f"DEBUG [preprocess for {filename_for_log}]: Initial channel names "
            f"({len(orig_ch_names)}): {orig_ch_names}"
        )
        log_func(
            f"DEBUG [preprocess for {filename_for_log}]: Expected stim_ch: "
            f"'{stim_ch}', max_idx_keep: {max_keep}"
        )
        if stim_ch not in orig_ch_names:
            log_func(
                f"DEBUG [preprocess for {filename_for_log}]: WARNING - Expected stim_ch "
                f"'{stim_ch}' is NOT in initial channel list."
            )

        # 1) Initial reference (user-selected pair; e.g., EXG1/EXG2 or EXG3/EXG4)
        if ref1 and ref2 and ref1 in orig_ch_names and ref2 in orig_ch_names:
            try:
                coerced = _coerce_refs_to_eeg_if_needed(raw, (ref1, ref2))
                if coerced:
                    log_func(f"DEBUG: coerced {coerced} → EEG for referencing.")

                log_func(
                    f"Applying reference pair [{ref1}, {ref2}] on {filename_for_log}..."
                )
                raw.set_eeg_reference(
                    ref_channels=[ref1, ref2],
                    projection=False,
                    verbose=False,
                )

                # Mark explicit success in params so the audit layer can trust it
                params["_fpvs_initial_ref_ok"] = True
                params["_fpvs_initial_ref_pair"] = (ref1, ref2)

                # Debug: inspect MNE's own custom_ref flag after applying the pair
                try:
                    mne_custom = raw.info.get("custom_ref_applied", None)
                except Exception:
                    mne_custom = None
                print(
                    f"[REF APPLY] {filename_for_log}: "
                    f"mne_custom_ref={mne_custom} "
                    f"initial_ref_ok={params.get('_fpvs_initial_ref_ok', False)} "
                    f"pair=({ref1},{ref2})"
                )

                log_func(
                    f"AUDIT: custom_ref_applied=True pair=[{ref1},{ref2}]"
                )
            except Exception as e:
                log_func(
                    f"Warn: Initial reference failed for {filename_for_log}: {e}"
                )
        else:
            log_func(
                f"Skip initial referencing for {filename_for_log} "
                f"(Ref channels '{ref1}', '{ref2}' not found or not specified)."
            )

        # 2) Explicitly drop the selected reference channels after initial reference
        for ch in (ref1, ref2):
            if ch in raw.ch_names:
                raw.drop_channels([ch])
                log_func(f"Dropped {ch} after initial referencing.")

        # 3) Optional channel limit (keeps stim if present)
        current_names_before_drop = list(raw.info["ch_names"])
        log_func(
            f"DEBUG [preprocess for {filename_for_log}]: Channel names BEFORE drop logic "
            f"({len(current_names_before_drop)}): {current_names_before_drop}"
        )
        if max_keep is not None and 0 < max_keep < len(current_names_before_drop):
            channels_to_keep_by_index = current_names_before_drop[:max_keep]
            final_keep = list(channels_to_keep_by_index)
            if stim_ch in current_names_before_drop and stim_ch not in final_keep:
                final_keep.append(stim_ch)
                log_func(
                    f"DEBUG [preprocess for {filename_for_log}]: Stim_ch '{stim_ch}' "
                    f"added to keep list."
                )
            unique_keep = set(final_keep)
            ordered_keep = [
                nm for nm in current_names_before_drop if nm in unique_keep
            ]
            to_drop = [
                nm for nm in current_names_before_drop if nm not in ordered_keep
            ]
            log_func(
                f"DEBUG [preprocess for {filename_for_log}]: Final KEEP "
                f"({len(ordered_keep)}): {ordered_keep}"
            )
            log_func(
                f"DEBUG [preprocess for {filename_for_log}]: Final DROP "
                f"({len(to_drop)}): {to_drop}"
            )
            if to_drop:
                log_func(
                    f"Attempting to drop {len(to_drop)} channels from "
                    f"{filename_for_log}..."
                )
                raw.drop_channels(to_drop, on_missing="warn")
                log_func(
                    f"{len(raw.ch_names)} channels remain in "
                    f"{filename_for_log} after drop."
                )
                log_func(
                    f"DEBUG [preprocess for {filename_for_log}]: Channel names AFTER "
                    f"drop: {list(raw.info['ch_names'])}"
                )
            else:
                log_func(
                    f"No channels selected to be dropped for {filename_for_log}."
                )
        else:
            log_func(
                f"Skip channel drop for {filename_for_log} (max_keep: {max_keep}). "
                f"Current channels: {len(current_names_before_drop)}"
            )

        # 4) Downsample (legacy position: BEFORE filtering)
        if downsample_rate:
            sf = float(raw.info["sfreq"])
            log_func(
                f"Downsample check for {filename_for_log}: "
                f"Curr {sf:.3f} Hz, Tgt {downsample_rate} Hz."
            )
            if sf > downsample_rate:
                try:
                    raw.resample(
                        downsample_rate,
                        npad="auto",
                        window="hann",
                        verbose=False,
                    )
                    new_sf = float(raw.info["sfreq"])
                    log_func(
                        f"Resampled {filename_for_log} to {new_sf:.3f} Hz."
                    )
                    print(
                        f"[DS] {filename_for_log}: sfreq {sf:.3f} -> {new_sf:.3f}"
                    )
                except Exception as resample_err:
                    log_func(
                        f"Warn: Resampling failed for {filename_for_log}: "
                        f"{resample_err}"
                    )
                    print(
                        f"[DS] {filename_for_log}: RESAMPLE FAILED "
                        f"(sfreq={sf:.3f}, target={downsample_rate})"
                    )
            else:
                log_func(
                    f"No downsampling needed for {filename_for_log} "
                    f"(sfreq={sf:.3f}, target={downsample_rate})."
                )
                print(
                    f"[DS] {filename_for_log}: no resample "
                    f"(sfreq={sf:.3f}, target={downsample_rate})"
                )
        else:
            log_func(f"Skip downsample for {filename_for_log}.")
            print(f"[DS] {filename_for_log}: skip (no downsample_rate set)")

        # 5) FILTER at (possibly reduced) Fs
        # LEGACY MAPPING: low_pass -> l_freq, high_pass -> h_freq (intentionally inverted names)
        l_freq = low_pass if (low_pass and low_pass > 0) else None
        h_freq = high_pass
        if l_freq or h_freq:
            try:
                low_trans_bw, high_trans_bw, filter_len_points = 0.1, 0.1, 8449
                effective_l = l_freq if l_freq is not None else "DC"
                effective_h = h_freq if h_freq is not None else "Nyq"
                sf_current = float(raw.info["sfreq"])
                log_func(
                    f"Filtering {filename_for_log} "
                    f"({effective_l}-{effective_h} Hz) at sfreq={sf_current:.3f}..."
                )
                print(
                    f"[FILTER] {filename_for_log}: FIR bandpass "
                    f"l_freq={effective_l} h_freq={effective_h} "
                    f"sfreq={sf_current:.3f}"
                )
                raw.filter(
                    l_freq,
                    h_freq,
                    method="fir",
                    phase="zero-double",
                    fir_window="hamming",
                    fir_design="firwin",
                    l_trans_bandwidth=low_trans_bw,
                    h_trans_bandwidth=high_trans_bw,
                    filter_length=filter_len_points,
                    skip_by_annotation="edge",
                    verbose=False,
                )
                log_func(f"Filter OK for {filename_for_log}.")
            except Exception as e:
                log_func(
                    f"Warn: Filter failed for {filename_for_log}: {e}"
                )
                print(
                    f"[FILTER] {filename_for_log}: FAILED "
                    f"l_freq={l_freq} h_freq={h_freq}"
                )
        else:
            log_func(f"Skip filter for {filename_for_log}.")
            print(f"[FILTER] {filename_for_log}: skip (no l_freq/h_freq)")

        # 6) Kurtosis rejection & interpolation
        if reject_thresh:
            log_func(
                f"Kurtosis rejection for {filename_for_log} "
                f"(Z > {reject_thresh})..."
            )
            bad_k_auto: List[str] = []
            eeg_picks = mne.pick_types(
                raw.info,
                eeg=True,
                exclude=raw.info["bads"]
                + (
                    [stim_ch]
                    if (
                        stim_ch in raw.ch_names
                        and raw.get_channel_types(picks=stim_ch)[0] != "eeg"
                    )
                    else []
                ),
            )
            if len(eeg_picks) >= 2:
                data = raw.get_data(picks=eeg_picks)
                k_values = kurtosis(
                    data, axis=1, fisher=True, bias=False
                )
                k_values = np.nan_to_num(k_values)
                proportion_to_cut = 0.1
                n_k = len(k_values)
                trim_count = int(np.floor(n_k * proportion_to_cut))
                if n_k - 2 * trim_count > 1:
                    k_sorted = np.sort(k_values)
                    k_trimmed = k_sorted[trim_count : n_k - trim_count]
                    m_trimmed = float(np.mean(k_trimmed))
                    s_trimmed = float(np.std(k_trimmed))
                    log_func(
                        f"Trimmed Norm for {filename_for_log}: "
                        f"Mean={m_trimmed:.3f}, Std={s_trimmed:.3f} "
                        f"(N_trimmed={len(k_trimmed)})"
                    )
                    if s_trimmed > 1e-9:
                        z_scores = (k_values - m_trimmed) / s_trimmed
                        bad_idx = np.where(
                            np.abs(z_scores) > reject_thresh
                        )[0]
                        ch_names_pick = [
                            raw.info["ch_names"][i] for i in eeg_picks
                        ]
                        bad_k_auto = [ch_names_pick[i] for i in bad_idx]
                    else:
                        log_func(
                            f"Kurtosis Trimmed Std Dev near zero for "
                            f"{filename_for_log}."
                        )
                else:
                    log_func(
                        f"Not enough data for Kurtosis trimmed stats in "
                        f"{filename_for_log} (N_k={n_k})."
                    )
                num_kurtosis_bads_identified = len(bad_k_auto)
                if bad_k_auto:
                    log_func(
                        f"Bad by Kurtosis for {filename_for_log}: "
                        f"{bad_k_auto} "
                        f"(Count: {num_kurtosis_bads_identified})"
                    )
                else:
                    log_func(
                        f"No channels bad by Kurtosis for {filename_for_log}."
                    )
                print(
                    f"[KURTOSIS] {filename_for_log}: "
                    f"n_bad={num_kurtosis_bads_identified} "
                    f"bad_chs={bad_k_auto}"
                )
            else:
                log_func(
                    f"Skip Kurtosis for {filename_for_log} "
                    f"(< 2 good EEG channels; n_picks={len(eeg_picks)})."
                )
                print(
                    f"[KURTOSIS] {filename_for_log}: skip "
                    f"(n_eeg_picks={len(eeg_picks)})"
                )

            new_bads = [
                b
                for b in (bad_k_auto if reject_thresh else [])
                if b not in raw.info["bads"]
            ]
            if new_bads:
                raw.info["bads"].extend(new_bads)

            if raw.info["bads"] and raw.get_montage():
                try:
                    interp_targets = list(raw.info["bads"])
                    log_func(
                        f"Interpolating bads in {filename_for_log}: "
                        f"{interp_targets}"
                    )
                    print(
                        f"[INTERP] {filename_for_log}: "
                        f"interpolated_chs={interp_targets}"
                    )
                    raw.interpolate_bads(
                        reset_bads=True,
                        mode="accurate",
                        verbose=False,
                    )
                    log_func(f"Interpolation OK for {filename_for_log}.")
                except Exception as e:
                    log_func(
                        f"Warn: Interpolation failed for {filename_for_log}: {e}"
                    )
                    print(
                        f"[INTERP] {filename_for_log}: FAILED "
                        f"bads={raw.info.get('bads', [])}"
                    )
            elif raw.info["bads"]:
                log_func(
                    f"Warn: No montage for {filename_for_log}, "
                    f"cannot interpolate. Bads remain: {raw.info['bads']}"
                )
                print(
                    f"[INTERP] {filename_for_log}: no montage; "
                    f"bads={raw.info['bads']}"
                )
            else:
                log_func(f"No bads to interpolate in {filename_for_log}.")
                print(f"[INTERP] {filename_for_log}: no bads")
        else:
            log_func(
                f"Skip Kurtosis for {filename_for_log} (no threshold)."
            )
            print(f"[KURTOSIS] {filename_for_log}: skip (no threshold)")

        # 7) Average reference (final)
        try:
            log_func(f"Applying average reference to {filename_for_log}...")
            eeg_picks_for_ref = mne.pick_types(
                raw.info, eeg=True, exclude=raw.info["bads"]
            )
            if len(eeg_picks_for_ref) > 0:
                raw.set_eeg_reference(
                    ref_channels="average",
                    projection=True,
                    verbose=False,
                )
                raw.apply_proj(verbose=False)
                log_func(
                    f"Average reference applied to {filename_for_log}."
                )
            else:
                log_func(
                    f"Skip average ref for {filename_for_log}: "
                    f"No good EEG channels."
                )
        except Exception as e:
            log_func(
                f"Warn: Average reference failed for {filename_for_log}: {e}"
            )

        # Final reference state debug (after whole pipeline)
        try:
            mne_custom_final = raw.info.get("custom_ref_applied", None)
        except Exception:
            mne_custom_final = None
        print(
            f"[REF FINAL] {filename_for_log}: "
            f"mne_custom_ref={mne_custom_final} "
            f"fpvs_initial_custom_ref={raw.info.get('fpvs_initial_custom_ref', None)} "
            f"n_ch={len(raw.ch_names)} "
            f"bads={raw.info.get('bads', [])}"
        )

        log_func(
            f"Preprocessing OK for {filename_for_log}. "
            f"{len(raw.ch_names)} channels, {raw.info['sfreq']:.1f} Hz."
        )
        final_ch_names = list(raw.info["ch_names"])
        log_func(
            f"DEBUG [preprocess for {filename_for_log}]: Final channel names "
            f"before returning ({len(final_ch_names)}): {final_ch_names}"
        )
        if stim_ch in final_ch_names:
            log_func(
                f"DEBUG [preprocess for {filename_for_log}]: Expected stim_ch "
                f"'{stim_ch}' IS PRESENT at VERY END."
            )
        else:
            log_func(
                f"DEBUG [preprocess for {filename_for_log}]: CRITICAL! "
                f"Expected stim_ch '{stim_ch}' IS NOT PRESENT at VERY END."
            )

        return raw, num_kurtosis_bads_identified

    except Exception as e:
        log_func(
            f"!!! CRITICAL Preprocessing error for {filename_for_log}: {e}"
        )
        log_func(f"Traceback: {traceback.format_exc()}")
        return None, num_kurtosis_bads_identified

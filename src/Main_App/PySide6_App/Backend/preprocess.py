# -*- coding: utf-8 -*-
"""
Qt-side preprocessing module for the FPVS Toolbox.

This module provides the core preprocessing pipeline designed to mirror legacy
logic exactly. It handles data auditing, referencing, filtering, and
automated artifact rejection via kurtosis.

Pipeline Order (Legacy Parity):
    1. Initial reference (user-selected pair).
    2. Drop the selected reference pair channels.
    3. Optional channel limit (max_idx_keep; keeps stim if needed).
    4. Downsample (if requested).
    5. FIR filter (legacy mapping and kernel).
    6. Kurtosis-based rejection & interpolation.
    7. Final average reference.
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


def _build_preproc_fingerprint(params: Dict[str, Any]) -> str:
    hp = params.get("high_pass")
    lp = params.get("low_pass")
    ds = params.get("downsample_rate", params.get("downsample"))
    rz = params.get("reject_thresh")
    r1 = params.get("ref_channel1")
    r2 = params.get("ref_channel2")
    stim = params.get("stim_channel")
    return f"hp={hp}|lp={lp}|ds={ds}|rz={rz}|ref={r1},{r2}|stim={stim}"


def begin_preproc_audit(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
    filename: str,
) -> Dict[str, Any]:
    """
    Capture baseline audit metadata before preprocessing mutates the Raw object.

    This function records the state of the data (channel count, sampling frequency,
    etc.) so that post-processing changes can be verified for integrity.

    Args:
        raw: The MNE Raw object to audit.
        params: The dictionary of preprocessing parameters used for this run.
        filename: The name of the file being processed, used for logging context.

    Returns:
        A dictionary containing the initial state 'capture' and filename.
    """
    try:
        logger.debug(
            "begin_preproc_audit_start",
            extra={
                "file": filename,
                "sfreq": float(raw.info.get("sfreq", -1.0)),
                "n_channels": len(raw.info.get("ch_names", [])),
            },
        )
    except Exception:
        # Audit logging must not affect behavior
        logger.debug("begin_preproc_audit_start_logging_failed", extra={"file": filename})
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
    """
    Compute the post-state audit and log structured results.

    Compares the 'before' state with the 'after' state to identify any
    unintended processing side effects.

    Args:
        before: The state dictionary returned by `begin_preproc_audit`.
        raw: The MNE Raw object after preprocessing is complete.
        params: The dictionary of preprocessing parameters used.
        filename: The name of the file being processed.
        events_info: Optional metadata regarding EEG events/markers.
        fif_written: Boolean/int flag indicating if the file was saved to disk.
        n_rejected: Number of channels rejected during the kurtosis stage.

    Returns:
        A tuple containing:
            - after (Dict[str, Any]): The final state metadata.
            - problems (List[str]): A list of audit mismatches or warnings found.
    """
    try:
        logger.debug(
            "finalize_preproc_audit_start",
            extra={
                "file": filename,
                "events_info_present": events_info is not None,
                "fif_written": fif_written,
                "n_rejected": n_rejected,
            },
        )
    except Exception:
        logger.debug(
            "finalize_preproc_audit_start_logging_failed",
            extra={"file": filename},
        )

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
    """
    Ensure selected reference channels are typed as 'eeg'.

    MNE requires channels used in `set_eeg_reference` to be of type 'eeg'.
    If they are 'misc' or 'exg', this function coerces them.

    Args:
        raw: The MNE Raw object (modified in place).
        pair: A tuple of two channel names to check/coerce.

    Returns:
        A list of channel names whose types were actually changed.
    """
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
    Apply the full preprocessing pipeline to an MNE Raw object.

    This function performs referencing, channel selection, resampling,
    filtering, and artifact rejection in a fixed order to maintain
    compatibility with legacy FPVS analysis scripts.

    Args:
        raw_input: Raw MNE data to process. This object is modified in place.
        params: Configuration dictionary. Expected keys include:
            - 'downsample_rate' (int/float): Target Hz.
            - 'low_pass' (float): LPF cutoff in Hz.
            - 'high_pass' (float): HPF cutoff in Hz.
            - 'reject_thresh' (float): Z-score threshold for kurtosis rejection.
            - 'ref_channel1', 'ref_channel2' (str): Channels for initial reference.
            - 'max_idx_keep' (int): Number of EEG channels to retain.
            - 'stim_channel' (str, optional): The trigger/stim channel name.
        log_func: A callable (typically a UI log method) that accepts a string.
        filename_for_log: Filename string used for logging and console output.

    Returns:
        A tuple of (processed_raw, n_bad_channels).
        Returns (None, 0) if a critical error occurs.

    Raises:
        ValueError: If filter cutoffs are logically invalid (HPF >= LPF).
    """
    raw = raw_input
    fingerprint_in = _build_preproc_fingerprint(params)
    fingerprint_message = f"PREPROC_FINGERPRINT_PREPROCESS_IN {fingerprint_in}"
    log_func(fingerprint_message)
    logger.info(fingerprint_message)

    # Runtime parameters (defaults are managed by Settings UI; fall back only if absent)
    downsample_rate = params.get("downsample_rate")
    low_pass = params.get("low_pass")
    high_pass = params.get("high_pass")
    log_func(
        f"DEBUG [preprocess cutoffs {filename_for_log}]: "
        f"high_pass={high_pass!r} low_pass={low_pass!r}"
    )
    hp = float(high_pass) if high_pass is not None else None
    lp = float(low_pass) if low_pass is not None else None
    if hp is not None and lp is not None and hp >= lp:
        raise ValueError(
            f"Invalid filter cutoffs for {filename_for_log}: "
            f"high_pass (HPF) must be < low_pass (LPF). Got high_pass={hp}, "
            f"low_pass={lp}."
        )
    reject_thresh = params.get("reject_thresh")
    ref1 = params.get("ref_channel1") or "EXG1"
    ref2 = params.get("ref_channel2") or "EXG2"
    max_keep = params.get("max_idx_keep")
    stim_ch = params.get("stim_channel", config.DEFAULT_STIM_CHANNEL)

    num_kurtosis_bads_identified = 0

    try:
        # Module-level logger entry for high-level preprocessing start
        try:
            logger.info(
                "preprocess_start",
                extra={
                    "file": filename_for_log,
                    "downsample_rate": downsample_rate,
                    "low_pass": low_pass,
                    "high_pass": high_pass,
                    "reject_thresh": reject_thresh,
                    "max_idx_keep": max_keep,
                    "stim_ch": stim_ch,
                },
            )
        except Exception:
            logger.debug(
                "preprocess_start_logging_failed", extra={"file": filename_for_log}
            )

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
        try:
            logger.debug(
                "preprocess_stage_after_drop_refs",
                extra={
                    "file": filename_for_log,
                    "n_channels": len(raw.info.get("ch_names", [])),
                },
            )
        except Exception:
            logger.debug(
                "preprocess_stage_after_drop_refs_logging_failed",
                extra={"file": filename_for_log},
            )

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
        try:
            logger.debug(
                "preprocess_stage_after_channel_limit",
                extra={
                    "file": filename_for_log,
                    "n_channels": len(raw.info.get("ch_names", [])),
                },
            )
        except Exception:
            logger.debug(
                "preprocess_stage_after_channel_limit_logging_failed",
                extra={"file": filename_for_log},
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
        try:
            logger.debug(
                "preprocess_stage_after_downsample",
                extra={
                    "file": filename_for_log,
                    "sfreq": float(raw.info.get("sfreq", -1.0)),
                },
            )
        except Exception:
            logger.debug(
                "preprocess_stage_after_downsample_logging_failed",
                extra={"file": filename_for_log},
            )

        # 5) FILTER at (possibly reduced) Fs
        l_freq = hp if (hp is not None and hp > 0) else None
        h_freq = lp
        if l_freq or h_freq:
            try:
                low_trans_bw, high_trans_bw, filter_len_points = 0.1, 0.1, 8449
                effective_l = l_freq if l_freq is not None else "DC"
                effective_h = h_freq if h_freq is not None else "Nyq"
                sf_current = float(raw.info.get("sfreq", 0.0))
                snapshot_payload = (
                    f"file={filename_for_log} "
                    f"param_high_pass={high_pass!r} "
                    f"param_low_pass={low_pass!r} "
                    f"computed_l_freq={l_freq!r} "
                    f"computed_h_freq={h_freq!r} "
                    f"sfreq={sf_current}"
                )
                snapshot_message = f"FILTER_SNAPSHOT {snapshot_payload}"
                log_func(snapshot_message)
                logger.info(snapshot_message)
                print(f"[FILTER_SNAPSHOT] {snapshot_payload}")
                if h_freq is not None and h_freq > sf_current / 2.0:
                    nyquist_warning = (
                        "FILTER_NYQUIST_WARNING "
                        f"file={filename_for_log} "
                        f"computed_h_freq={h_freq!r} "
                        f"sfreq={sf_current}"
                    )
                    log_func(nyquist_warning)
                    logger.warning(nyquist_warning)
                fingerprint_before_filter = _build_preproc_fingerprint(params)
                if fingerprint_before_filter != fingerprint_in:
                    mutation_warning = (
                        "PREPROC_FINGERPRINT_MUTATION_WARNING "
                        f"file={filename_for_log} "
                        f"before={fingerprint_in} "
                        f"current={fingerprint_before_filter}"
                    )
                    log_func(mutation_warning)
                    logger.warning(mutation_warning)
                if l_freq is not None and h_freq is not None and l_freq >= h_freq:
                    range_warning = (
                        "FILTER_RANGE_WARNING "
                        f"file={filename_for_log} "
                        f"computed_l_freq={l_freq!r} "
                        f"computed_h_freq={h_freq!r}"
                    )
                    log_func(range_warning)
                    logger.warning(range_warning)
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
                applied_highpass = raw.info.get("highpass", None)
                applied_lowpass = raw.info.get("lowpass", None)
                applied_payload = (
                    f"file={filename_for_log} "
                    f"applied_highpass={applied_highpass!r} "
                    f"applied_lowpass={applied_lowpass!r} "
                    f"sfreq={sf_current}"
                )
                applied_message = f"FILTER_APPLIED {applied_payload}"
                log_func(applied_message)
                logger.info(applied_message)
                print(f"[FILTER_APPLIED] {applied_payload}")
                expected_highpass = l_freq if l_freq is not None else 0.0
                expected_lowpass = (
                    h_freq
                    if h_freq is not None
                    else float(raw.info.get("sfreq", 0.0)) / 2.0
                )
                tol = 1e-6
                mismatch = False
                if applied_highpass is None or applied_lowpass is None:
                    mismatch = True
                elif (
                    abs(applied_highpass - expected_highpass) > tol
                    or abs(applied_lowpass - expected_lowpass) > tol
                ):
                    mismatch = True
                if mismatch:
                    mismatch_warning = (
                        "FILTER_MISMATCH_WARNING "
                        f"file={filename_for_log} "
                        f"expected_highpass={expected_highpass!r} "
                        f"expected_lowpass={expected_lowpass!r} "
                        f"applied_highpass={applied_highpass!r} "
                        f"applied_lowpass={applied_lowpass!r}"
                    )
                    log_func(mismatch_warning)
                    logger.warning(mismatch_warning)
                log_func(
                    f"DEBUG [raw.info cutoffs {filename_for_log}]: "
                    f"highpass={raw.info.get('highpass')} "
                    f"lowpass={raw.info.get('lowpass')}"
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
        try:
            logger.debug(
                "preprocess_stage_after_filter",
                extra={
                    "file": filename_for_log,
                    "sfreq": float(raw.info.get("sfreq", -1.0)),
                },
            )
        except Exception:
            logger.debug(
                "preprocess_stage_after_filter_logging_failed",
                extra={"file": filename_for_log},
            )

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
        try:
            logger.debug(
                "preprocess_stage_after_kurtosis",
                extra={
                    "file": filename_for_log,
                    "n_bads": len(raw.info.get("bads", [])),
                },
            )
        except Exception:
            logger.debug(
                "preprocess_stage_after_kurtosis_logging_failed",
                extra={"file": filename_for_log},
            )

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

        try:
            logger.info(
                "preprocess_ok",
                extra={
                    "file": filename_for_log,
                    "n_channels": len(final_ch_names),
                    "sfreq": float(raw.info.get("sfreq", -1.0)),
                    "n_rejected": num_kurtosis_bads_identified,
                },
            )
        except Exception:
            logger.debug(
                "preprocess_ok_logging_failed",
                extra={"file": filename_for_log},
            )

        return raw, num_kurtosis_bads_identified

    except Exception as e:
        log_func(
            f"!!! CRITICAL Preprocessing error for {filename_for_log}: {e}"
        )
        log_func(f"Traceback: {traceback.format_exc()}")
        try:
            logger.error(
                "preprocess_error",
                extra={
                    "file": filename_for_log,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                },
            )
        except Exception:
            logger.debug(
                "preprocess_error_logging_failed",
                extra={"file": filename_for_log},
            )
        return None, num_kurtosis_bads_identified
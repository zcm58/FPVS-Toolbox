# -*- coding: utf-8 -*-
"""
Qt-side preprocessing module for the FPVS Toolbox.

This module provides the core preprocessing pipeline for active Main App runs.
It handles data auditing, referencing, filtering, and automated artifact
rejection via kurtosis.

Pipeline Order:
    1. Initial reference (user-selected pair).
    2. Drop the selected reference pair channels.
    3. Optional channel limit (max_idx_keep; keeps stim if needed).
    4. FIR filter (legacy mapping and kernel).
    5. Optional smart FFT multi-notch line-noise filter.
    6. Downsample (if requested).
    7. Kurtosis-based rejection & interpolation.
    8. Final average reference.
"""

from __future__ import annotations

import logging
from pathlib import Path
from time import perf_counter
import traceback
from typing import Callable, Optional, Tuple, Dict, Any, List, Sequence

import mne
import numpy as np

from Main_App.diagnostics.audit import (
    start_preproc_audit,
    end_preproc_audit,
    compare_preproc,
)
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    attach_raw_biosemi64_geometry,
    read_raw_biosemi64_geometry,
    validate_raw_biosemi64_geometry,
)
from Main_App.processing.fft_multinotch import (
    FFT_MULTINOTCH_COMPONENT_COUNT,
    FFT_MULTINOTCH_HALF_WIDTH_HZ,
    FFT_MULTINOTCH_METHOD_VERSION,
    apply_fft_multinotch,
)
from Main_App.processing.analysis_spans import (
    ANALYSIS_SPAN_PLAN_VERSION,
    AnalysisSpanPlanError,
    realize_target_analysis_span_plan,
    relative_spans_from_plan,
    validate_target_analysis_span_markers,
)
from Main_App.processing.kurtosis_qc import (
    build_kurtosis_decision_plan,
    evaluate_kurtosis_qc,
)
from Main_App.processing.prepared_kurtosis_cache import (
    checkpoint_identity, load_checkpoint, save_checkpoint,
)
from Main_App.processing.prepared_fir import filter_raw_with_prepared_fir
from Main_App.processing.condition_electrode_interpolation import (
    apply_condition_repairs,
    prepare_condition_repairs,
)

logger = logging.getLogger(__name__)

__all__ = [
    "perform_preprocessing",
    "prepare_kurtosis_review_evidence",
    "begin_preproc_audit",
    "finalize_preproc_audit",
]

PREPROCESSING_ORDER_VERSION = (
    "filter_then_optional_fft_multinotch_then_downsample_v2"
)

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
    line_noise_enabled = bool(params.get("line_noise_filter_enabled", True))
    line_noise_frequency = params.get("line_noise_frequency_hz", 60)
    electrode_montage = params.get("electrode_montage", "biosemi64")
    electrode_mapping_profile = params.get(
        "electrode_mapping_profile",
        "anatomical_labels",
    )
    source_span_plan = params.get("_fpvs_source_analysis_span_plan")
    source_span_fingerprint = (
        str(source_span_plan.get("fingerprint") or "")
        if isinstance(source_span_plan, dict)
        else ""
    )
    return (
        f"order={PREPROCESSING_ORDER_VERSION}|hp={hp}|lp={lp}|ds={ds}|"
        f"rz={rz}|ref={r1},{r2}|stim={stim}|"
        f"montage={electrode_montage}|mapping={electrode_mapping_profile}|"
        f"geometry={BIOSEMI64_GEOMETRY_VERSION},{BIOSEMI64_COORDINATE_FINGERPRINT}|"
        f"analysis_spans={ANALYSIS_SPAN_PLAN_VERSION},{source_span_fingerprint}|"
        f"fft_multinotch={line_noise_enabled},{line_noise_frequency},"
        f"{FFT_MULTINOTCH_METHOD_VERSION},{FFT_MULTINOTCH_HALF_WIDTH_HZ},"
        f"{FFT_MULTINOTCH_COMPONENT_COUNT}"
    )


def _realize_analysis_spans_for_raw(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
) -> dict[str, Any] | None:
    """Realize the validated source plan on the resident Raw sample grid."""

    source_plan = params.get("_fpvs_source_analysis_span_plan")
    required = bool(params.get("_fpvs_require_analysis_spans", False))
    if not isinstance(source_plan, dict):
        params.pop("_fpvs_realized_analysis_span_plan", None)
        params.pop("_fpvs_analysis_scoring_sample_count", None)
        if required:
            raise AnalysisSpanPlanError(
                "Processing requires a validated source analysis-span plan."
            )
        return None
    realized = realize_target_analysis_span_plan(
        source_plan,
        target_sfreq_hz=float(raw.info["sfreq"]),
        target_n_times=int(raw.n_times),
        target_first_samp=int(raw.first_samp),
    )
    source_sfreq = float(source_plan["source_grid"]["sfreq_hz"])
    if source_sfreq != float(raw.info["sfreq"]):
        # MNE restarts its stim sampling windows for each concatenated segment.
        # The file-level BDF pipeline supplies one segment; never approximate a
        # different acquisition layout with the single-recording mapping.
        if len(raw._first_samps) != 1:
            raise AnalysisSpanPlanError(
                "Exact v3 trigger alignment requires a single recording segment."
            )
        stim_channel = str(params.get("stim_channel") or config.DEFAULT_STIM_CHANNEL)
        if stim_channel not in raw.ch_names:
            raise AnalysisSpanPlanError(
                "Exact v3 trigger alignment after downsampling requires the "
                "recorded stimulus channel; annotation-only timing is unsupported."
            )
        events = mne.find_events(
            raw, stim_channel=stim_channel, shortest_event=1, verbose=False
        )
        validate_target_analysis_span_markers(realized, events)
    params["_fpvs_realized_analysis_span_plan"] = realized
    params["_fpvs_analysis_scoring_sample_count"] = int(
        realized["unique_sample_count"]
    )
    return realized


def _kurtosis_scoring_data(
    raw: mne.io.BaseRaw,
    *,
    picks: Any,
    params: Dict[str, Any],
) -> np.ndarray:
    """Read every retained target sample once for the existing statistic."""

    target_plan = params.get("_fpvs_realized_analysis_span_plan")
    if not isinstance(target_plan, dict):
        if params.get("_fpvs_require_analysis_spans", False):
            raise AnalysisSpanPlanError(
                "Kurtosis requires realized analyzed-interval coordinates."
            )
        return raw.get_data(picks=picks)
    spans = relative_spans_from_plan(target_plan)
    if not spans:
        raise AnalysisSpanPlanError("Kurtosis analysis-span union is empty.")
    return np.concatenate(
        [raw.get_data(picks=picks, start=start, stop=stop) for start, stop in spans],
        axis=1,
    )


def _kurtosis_filter_identity(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
) -> dict[str, object]:
    """Describe the exact filtering state presented to QC-16."""

    return {
        "method_version": "mne_fir_zero_double_hamming_firwin_plus_fft_multinotch_v1",
        "preprocessing_order_version": PREPROCESSING_ORDER_VERSION,
        "requested_high_pass_hz": params.get("high_pass"),
        "requested_low_pass_hz": params.get("low_pass"),
        "applied_high_pass_hz": float(raw.info.get("highpass", 0.0)),
        "applied_low_pass_hz": float(raw.info.get("lowpass", 0.0)),
        "line_noise_filter_enabled": bool(
            params.get("line_noise_filter_enabled", True)
        ),
        "line_noise_frequency_hz": params.get("line_noise_frequency_hz", 60),
        "fft_multinotch_method_version": FFT_MULTINOTCH_METHOD_VERSION,
        "fft_multinotch_half_width_hz": FFT_MULTINOTCH_HALF_WIDTH_HZ,
        "fft_multinotch_component_count": FFT_MULTINOTCH_COMPONENT_COUNT,
        "fft_multinotch_requested_centers_hz": list(
            params.get("_fpvs_fft_multinotch_requested_centers_hz", ())
        ),
        "fft_multinotch_applied_centers_hz": list(
            params.get("_fpvs_fft_multinotch_applied_centers_hz", ())
        ),
        "fft_multinotch_skipped_centers": list(
            params.get("_fpvs_fft_multinotch_skipped_centers", ())
        ),
    }


def _kurtosis_downsample_identity(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
    *,
    source_sfreq_hz: float,
) -> dict[str, object]:
    """Describe the versioned resampling state presented to QC-16."""

    requested = params.get("downsample_rate", params.get("downsample"))
    return {
        "method_version": "mne_raw_resample_hann_npad_auto_v1",
        "source_sfreq_hz": float(source_sfreq_hz),
        "requested_sfreq_hz": requested,
        "realized_sfreq_hz": float(raw.info["sfreq"]),
        "resampled": bool(float(raw.info["sfreq"]) != float(source_sfreq_hz)),
    }


def _kurtosis_review_scope(
    params: Dict[str, Any],
    *,
    filename_for_log: str,
) -> dict[str, object]:
    participant_id = str(params.get("_fpvs_participant_id") or "").strip()
    recording_id = str(params.get("_fpvs_recording_id") or participant_id).strip()
    source_path = str(
        params.get("_fpvs_source_file_path") or Path(filename_for_log).resolve()
    )
    return {
        "source_file_path": source_path,
        "participant_id": participant_id,
        "recording_id": recording_id,
        "session_id": params.get("_fpvs_session_id"),
        "session_label": params.get("_fpvs_session_label"),
    }


def _kurtosis_signal_preview(
    data: np.ndarray,
    channel_names: List[str],
    review_channels: tuple[str, ...],
    *,
    raw=None,
    params=None,
    checkpoint=None,
    evidence_fingerprint="",
) -> dict[str, object]:
    """Return a bounded signal preview for the GUI without altering evidence."""

    if data.shape[1] < 1:
        return {"unit": "uV", "sample_count": 0, "channels": {}}
    from Main_App.processing.qc_signal_view import (
        build_kurtosis_view_metadata, peak_preserving_values,
    )
    channel_index = {name: index for index, name in enumerate(channel_names)}
    boundaries = {0, int(data.shape[1])}
    plan = (params or {}).get("_fpvs_realized_analysis_span_plan") or {}
    pooled_offset = 0
    for start, stop in plan.get("unique_relative_spans", ()):
        boundaries.add(pooled_offset)
        for occurrence in plan.get("spans", ()):
            coordinates = occurrence.get("target_coordinates") or {}
            for key in ("start_relative_sample", "stop_relative_sample"):
                point = coordinates.get(key)
                if point is not None and start < point < stop:
                    boundaries.add(pooled_offset + int(point) - int(start))
        pooled_offset += int(stop) - int(start)
        boundaries.add(pooled_offset)
    boundaries = sorted(point for point in boundaries if 0 <= point <= data.shape[1])
    segments = tuple(zip(boundaries[:-1], boundaries[1:], strict=True))
    rows: dict[str, list[float | None]] = {}
    for channel in review_channels:
        row_index = channel_index.get(channel)
        if row_index is None:
            continue
        values = []
        # Complex projects use the inspectable viewer instead of silently
        # dropping occurrences to force the miniature into a fixed width.
        if len(segments) <= 128:
            for start, stop in segments:
                if values:
                    values.append(None)
                values.extend(peak_preserving_values(data[row_index, start:stop], bins=max(1, 128 // len(segments))))
        rows[channel] = [
            float(value * 1e6) if value is not None else None for value in values
        ]
    view = {}
    if raw is not None and params is not None:
        try:
            view = build_kurtosis_view_metadata(raw, params, checkpoint, evidence_fingerprint)
        except (OSError, ValueError, TypeError, KeyError):
            logger.debug("qc_signal_view_metadata_unavailable", exc_info=True)
    return {
        "unit": "uV",
        "sample_count": max((len(values) for values in rows.values()), default=0),
        "source_sample_count": int(data.shape[1]),
        "channels": rows,
        "signal_view": view,
        "preview_method": "temporal_bin_extrema_v1",
    }


def _freeze_retained_biosemi64_geometry(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
    *,
    stim_channel: str,
) -> dict[str, Any]:
    """Validate and freeze the retained scalp set after intentional drops."""

    loaded_identity = read_raw_biosemi64_geometry(raw)
    if loaded_identity is None:
        raise RuntimeError(
            "Preprocessing requires a Raw loaded through the validated BioSemi64 "
            "geometry boundary."
        )
    retained = tuple(
        channel for channel in BIOSEMI64_CHANNELS if channel in raw.ch_names
    )
    if not retained:
        raise RuntimeError("No canonical BioSemi64 scalp channels remain for preprocessing.")
    identity = attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile=loaded_identity.get("electrode_mapping_profile"),
        retained_channels=retained,
        stim_channel=stim_channel if stim_channel in raw.ch_names else None,
    )
    params["_fpvs_geometry"] = dict(identity)
    params["_fpvs_retained_scalp_channels"] = list(retained)
    params["_fpvs_retained_scalp_set_fingerprint"] = identity[
        "retained_scalp_set_fingerprint"
    ]
    return identity


def _interpolate_current_bads(
    raw: mne.io.BaseRaw,
    params: Dict[str, Any],
    log_func: Callable[[str], None],
    *,
    filename_for_log: str,
    description: str,
) -> None:
    """Interpolate current canonical scalp bads and record the actual outcome."""

    targets = list(dict.fromkeys(str(name) for name in raw.info.get("bads", [])))
    params["_fpvs_interpolation_requested_channels"] = list(targets)
    params["_fpvs_interpolated_channels"] = []
    params["_fpvs_interpolation_error"] = ""
    if not targets:
        params["_fpvs_interpolation_status"] = "not_needed"
        log_func(f"No bads to interpolate in {filename_for_log}.")
        return

    geometry = validate_raw_biosemi64_geometry(raw, require_runtime_identity=True)
    retained = set(geometry["retained_scalp_channels"])
    invalid_targets = [name for name in targets if name not in retained]
    if invalid_targets:
        message = (
            "Interpolation target(s) are outside the retained BioSemi64 scalp set: "
            + ", ".join(invalid_targets)
        )
        params["_fpvs_interpolation_status"] = "failed"
        params["_fpvs_interpolation_error"] = message
        raise RuntimeError(message)

    log_func(
        f"Interpolating {description} in {filename_for_log}: "
        f"{targets}"
    )
    try:
        raw.interpolate_bads(
            reset_bads=True,
            mode="accurate",
            verbose=False,
        )
    except Exception as exc:
        message = f"Interpolation failed for {filename_for_log}: {exc}"
        params["_fpvs_interpolation_status"] = "failed"
        params["_fpvs_interpolation_error"] = str(exc)
        log_func(f"Warn: {message}")
        raise RuntimeError(message) from exc

    remaining = [name for name in targets if name in raw.info.get("bads", [])]
    if remaining:
        message = (
            f"Interpolation did not clear target(s) for {filename_for_log}: "
            + ", ".join(remaining)
        )
        params["_fpvs_interpolation_status"] = "failed"
        params["_fpvs_interpolation_error"] = message
        raise RuntimeError(message)

    params["_fpvs_interpolation_status"] = "succeeded"
    params["_fpvs_interpolated_channels"] = list(targets)
    log_func(f"Interpolation OK for {filename_for_log}.")


def _scaled_filter_length(
    base_length: int,
    *,
    current_sfreq: float,
    downsample_rate: Any,
) -> int:
    """Preserve the historical filter duration when filtering before resample."""

    try:
        target_sfreq = float(downsample_rate)
    except (TypeError, ValueError):
        target_sfreq = 0.0
    if target_sfreq <= 0 or current_sfreq <= target_sfreq:
        return base_length

    scaled = int(round((base_length - 1) * (current_sfreq / target_sfreq))) + 1
    if scaled % 2 == 0:
        scaled += 1
    return max(base_length, scaled)


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
    # Ensure per-run audit keys do not leak across files when params is reused
    params.pop("_fpvs_initial_ref_ok", None)
    params.pop("_fpvs_initial_ref_pair", None)
    params.pop("_fpvs_kurtosis_bad_channels", None)
    params.pop("_fpvs_geometry", None)
    params.pop("_fpvs_retained_scalp_channels", None)
    params.pop("_fpvs_retained_scalp_set_fingerprint", None)
    params.pop("_fpvs_interpolation_requested_channels", None)
    params.pop("_fpvs_interpolated_channels", None)
    params.pop("_fpvs_interpolation_status", None)
    params.pop("_fpvs_interpolation_error", None)
    params.pop("_fpvs_fft_multinotch_requested_centers_hz", None)
    params.pop("_fpvs_fft_multinotch_applied_centers_hz", None)
    params.pop("_fpvs_fft_multinotch_skipped_centers", None)
    params.pop("_fpvs_realized_analysis_span_plan", None)
    params.pop("_fpvs_analysis_scoring_sample_count", None)

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
        logger.debug("preproc_audit", extra={"file": filename, "audit": after})
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


def prepare_kurtosis_review_evidence(
    raw_input: mne.io.BaseRaw,
    params: Dict[str, Any],
    log_func: Callable[[str], None],
    filename_for_log: str = "UnknownFile",
    *,
    direct_bad_channels: Sequence[str] = (),
    copy_raw: bool = True,
) -> dict[str, object]:
    """Run the shared preprocessing stages to the QC-16 review boundary.

    By default the input is preserved. An exclusive owner may pass
    ``copy_raw=False`` to avoid duplicating the full recording; that caller
    remains responsible for closing its modified Raw object.
    """

    working = raw_input.copy() if copy_raw else raw_input
    scan_params = dict(params)
    scan_params["_fpvs_stop_before_kurtosis_interpolation"] = True
    direct = [
        str(channel)
        for channel in direct_bad_channels
        if str(channel) in working.ch_names
    ]
    if direct:
        working.info["bads"] = list(
            dict.fromkeys([*working.info["bads"], *direct])
        )
    processed = None
    try:
        working.load_data()
        processed, _candidate_count = perform_preprocessing(
            working,
            scan_params,
            log_func,
            filename_for_log,
        )
        evidence = scan_params.get("_fpvs_kurtosis_qc_evidence")
        decision_plan = scan_params.get("_fpvs_kurtosis_decision_plan")
        if processed is None or not isinstance(evidence, dict):
            raise RuntimeError(
                f"Kurtosis review evidence could not be prepared for {filename_for_log}."
            )
        preview = scan_params.get("_fpvs_kurtosis_signal_preview")
        return {
            "evidence": dict(evidence),
            "decision_plan": (
                dict(decision_plan) if isinstance(decision_plan, dict) else None
            ),
            "signal_preview": dict(preview) if isinstance(preview, dict) else {},
        }
    finally:
        if processed is not None and processed is not working:
            processed.close()
        if copy_raw:
            try:
                working.close()
            except (AttributeError, OSError, RuntimeError, ValueError):
                pass


def _finish_preprocessing_at_kurtosis(
    raw, params, log_func, filename_for_log, *, orig_sfreq, geometry_identity,
    debug_enabled, checkpoint=None, cached_evidence=None,
):
    """Resume the same calculation/decision/repair stages after preparation."""

    reject_thresh = params.get("reject_thresh")
    stim_ch = params.get("stim_channel", config.DEFAULT_STIM_CHANNEL)
    num_kurtosis_bads_identified = 0
    # 7) Kurtosis rejection & interpolation
    params["_fpvs_kurtosis_bad_channels"] = []
    params["_fpvs_kurtosis_review_required_channels"] = []
    params["_fpvs_kurtosis_corroborated_channels"] = []
    params["_fpvs_kurtosis_user_approved_channels"] = []
    params["_fpvs_kurtosis_user_rejected_channels"] = []
    params.pop("_fpvs_kurtosis_qc_evidence", None)
    params.pop("_fpvs_kurtosis_decision_plan", None)
    params.pop("_fpvs_kurtosis_signal_preview", None)
    params["_fpvs_interpolated_channels"] = []
    params.pop("_fpvs_condition_interpolation_provenance", None)
    condition_repairs = None
    bad_k_auto: List[str] = []
    if reject_thresh:
        log_func(
            f"Kurtosis screening for {filename_for_log} "
            f"(Z > {reject_thresh})..."
        )
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
        realized_plan = params.get("_fpvs_realized_analysis_span_plan")
        if not isinstance(realized_plan, dict):
            params["_fpvs_kurtosis_qc_evidence"] = {
                "evaluation_status": "not_evaluated",
                "reason": "missing_analyzed_interval_context",
                "authority": "no_automatic_kurtosis_interpolation",
            }
            log_func(
                f"Kurtosis was not evaluated for {filename_for_log} because "
                "approved analyzed intervals were unavailable."
            )
        elif len(eeg_picks) >= 1:
            scoring_started = perf_counter()
            data = _kurtosis_scoring_data(
                raw,
                picks=eeg_picks,
                params=params,
            )
            ch_names_pick = [raw.info["ch_names"][i] for i in eeg_picks]
            calculation_started = perf_counter()
            evidence = cached_evidence if cached_evidence is not None else evaluate_kurtosis_qc(
                data,
                ch_names_pick,
                threshold=reject_thresh,
                realized_analysis_span_plan=realized_plan,
                filter_identity=_kurtosis_filter_identity(raw, params),
                downsample_identity=_kurtosis_downsample_identity(
                    raw,
                    params,
                    source_sfreq_hz=orig_sfreq,
                ),
                geometry_identity=geometry_identity,
            )
            logger.info(
                "kurtosis_scoring_timing file=%s data_ms=%.3f calculate_ms=%.3f "
                "channels=%d samples=%d",
                filename_for_log,
                (calculation_started - scoring_started) * 1_000.0,
                (perf_counter() - calculation_started) * 1_000.0,
                data.shape[0],
                data.shape[1],
            )
            if cached_evidence is None:
                save_checkpoint(checkpoint, raw, params, evidence, orig_sfreq)
            cancelled = params.get("_fpvs_kurtosis_checkpoint_should_cancel")
            if callable(cancelled) and cancelled():
                raise RuntimeError("Kurtosis preparation cancelled.")
            direct_bad_channels = {
                str(channel): "confirmed_upstream_bad_channel"
                for channel in raw.info.get("bads", [])
                if str(channel) in geometry_identity["retained_scalp_channels"]
            }
            raw_decisions = params.get("_fpvs_kurtosis_review_decisions")
            review_decisions = raw_decisions if isinstance(raw_decisions, dict) else None
            decision_plan = build_kurtosis_decision_plan(
                evidence,
                review_decisions=review_decisions,
                review_scope=_kurtosis_review_scope(
                    params,
                    filename_for_log=filename_for_log,
                ),
                direct_bad_channels=direct_bad_channels,
                kurtosis_auto_interpolate_all=params.get("kurtosis_auto_interpolate_all", False),
            )
            bad_k_auto = list(evidence.candidate_channels)
            num_kurtosis_bads_identified = len(bad_k_auto)
            params["_fpvs_kurtosis_bad_channels"] = list(bad_k_auto)
            params["_fpvs_kurtosis_qc_evidence"] = evidence.to_payload()
            params["_fpvs_kurtosis_decision_plan"] = decision_plan.to_payload()
            params["_fpvs_kurtosis_review_required_channels"] = list(
                decision_plan.pending_review_channels
            )
            params["_fpvs_kurtosis_corroborated_channels"] = list(
                decision_plan.corroborated_automatic_channels
            )
            params["_fpvs_kurtosis_user_approved_channels"] = list(
                decision_plan.user_approved_channels
            )
            params["_fpvs_kurtosis_user_rejected_channels"] = list(
                decision_plan.user_rejected_channels
            )
            params["_fpvs_kurtosis_signal_preview"] = _kurtosis_signal_preview(
                data,
                ch_names_pick,
                decision_plan.pending_review_channels,
                raw=raw,
                params=params,
                checkpoint=checkpoint,
                evidence_fingerprint=evidence.fingerprint,
            )
            log_func(
                f"Kurtosis evidence for {filename_for_log}: "
                f"candidates={list(decision_plan.candidate_channels)}, "
                f"review_required={list(decision_plan.pending_review_channels)}, "
                "automatic="
                f"{list(decision_plan.corroborated_automatic_channels)}."
            )
            if debug_enabled:
                logger.debug(
                    "kurtosis_candidates",
                    extra={"file": filename_for_log,
                           "n_bad": num_kurtosis_bads_identified,
                           "bad_channels": bad_k_auto},
                )
            if params.get("_fpvs_stop_before_kurtosis_interpolation", False):
                log_func(
                    f"Stopped before interpolation for {filename_for_log}; "
                    "kurtosis review evidence is ready for the GUI."
                )
                return raw, num_kurtosis_bads_identified
            if not decision_plan.ready_for_interpolation:
                reasons = ", ".join(decision_plan.blocking_reasons)
                raise RuntimeError(
                    "Kurtosis interpolation is blocked pending current GUI review "
                    f"or valid evidence for {filename_for_log}: {reasons}."
                )

            authorized = set(decision_plan.authorized_interpolation_channels)
            new_bads = [
                channel
                for channel in authorized
                if channel not in raw.info["bads"]
            ]
            if new_bads:
                raw.info["bads"].extend(new_bads)
        else:
            params["_fpvs_kurtosis_qc_evidence"] = {
                "evaluation_status": "not_evaluated",
                "reason": "all_retained_channels_already_confirmed_bad",
                "authority": "direct_bad_channels_only",
            }
            log_func(
                f"Skip Kurtosis for {filename_for_log} "
                f"(no unmarked EEG channels; n_picks={len(eeg_picks)})."
            )
            if debug_enabled:
                logger.debug(
                    "kurtosis_skipped_no_unmarked_eeg",
                    extra={"file": filename_for_log, "n_eeg_picks": len(eeg_picks)},
                )

        condition_repairs = prepare_condition_repairs(raw, params)
        _interpolate_current_bads(
            raw,
            params,
            log_func,
            filename_for_log=filename_for_log,
            description="bads",
        )
    else:
        log_func(
            f"Skip Kurtosis for {filename_for_log} (no threshold)."
        )
        if debug_enabled:
            logger.debug("kurtosis_skipped_no_threshold", extra={"file": filename_for_log})
        condition_repairs = prepare_condition_repairs(raw, params)
        _interpolate_current_bads(
            raw,
            params,
            log_func,
            filename_for_log=filename_for_log,
            description="pre-marked bads",
        )
    try:
        logger.debug(
            "preprocess_stage_after_kurtosis",
            extra={
                "file": filename_for_log,
                "n_bads": len(raw.info.get("bads", [])),
            },
        )
    except Exception:  # Diagnostic boundary: preserve continuation when logging metadata fails.
        logger.debug(
            "preprocess_stage_after_kurtosis_logging_failed",
            extra={"file": filename_for_log},
        )

    # 8) Average reference (final)
    average_reference_applied = False
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
            average_reference_applied = True
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

    if condition_repairs is not None:
        if not average_reference_applied:
            raise RuntimeError("Condition-local interpolation requires successful final average reference.")
        params["_fpvs_condition_interpolation_provenance"] = apply_condition_repairs(
            raw, condition_repairs,
        )
        log_func(f"Applied condition-local electrode repairs in the exact analyzed intervals for {filename_for_log}.")

    # Final reference state debug (after whole pipeline)
    try:
        mne_custom_final = raw.info.get("custom_ref_applied", None)
    except Exception:  # Diagnostic boundary: unavailable reference metadata has no processing authority.
        mne_custom_final = None
    if debug_enabled:
        logger.debug(
            "preprocess_final_reference_state",
            extra={"file": filename_for_log,
                   "mne_custom_ref": mne_custom_final,
                   "fpvs_initial_custom_ref": raw.info.get("fpvs_initial_custom_ref", None),
                   "n_channels": len(raw.ch_names), "bads": raw.info.get("bads", [])},
        )

    log_func(
        f"Preprocessing OK for {filename_for_log}. "
        f"{len(raw.ch_names)} channels, {raw.info['sfreq']:.1f} Hz."
    )
    if debug_enabled:
        final_ch_names = list(raw.info["ch_names"])
        log_func(
            f"DEBUG [preprocess for {filename_for_log}]: Final channel names "
            f"before returning ({len(final_ch_names)}): {final_ch_names}"
        )
    if stim_ch in raw.ch_names:
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
        logger.debug(
            "preprocess_ok",
            extra={
                "file": filename_for_log,
                "n_channels": len(raw.ch_names),
                "sfreq": float(raw.info.get("sfreq", -1.0)),
                "n_rejected": num_kurtosis_bads_identified,
            },
        )
    except Exception:  # Diagnostic boundary: preserve the completed result if audit logging fails.
        logger.debug(
            "preprocess_ok_logging_failed",
            extra={"file": filename_for_log},
        )

    return raw, num_kurtosis_bads_identified



def perform_preprocessing(
    raw_input: mne.io.BaseRaw,
    params: Dict[str, Any],
    log_func: Callable[[str], None],
    filename_for_log: str = "UnknownFile",
) -> Tuple[Optional[mne.io.BaseRaw], int]:
    """
    Apply the full preprocessing pipeline to an MNE Raw object.

    This function performs referencing, channel selection, filtering,
    resampling, and artifact rejection in a fixed order.

    Args:
        raw_input: Raw MNE data to process. This object is modified in place.
        params: Configuration dictionary. Expected keys include:
            - 'downsample_rate' (int/float): Target Hz.
            - 'low_pass' (float): LPF cutoff in Hz.
            - 'high_pass' (float): HPF cutoff in Hz.
            - 'line_noise_filter_enabled' (bool): Enable smart FFT multi-notch.
            - 'line_noise_frequency_hz' (int): Recording-site mains frequency,
              exactly 50 or 60 Hz. The fundamental plus two harmonics are
              considered.
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

    # Ensure per-run audit keys do not leak across files when params is reused
    params.pop("_fpvs_preprocessing_error", None)
    params.pop("_fpvs_initial_ref_ok", None)
    params.pop("_fpvs_initial_ref_pair", None)
    params.pop("_fpvs_fft_multinotch_requested_centers_hz", None)
    params.pop("_fpvs_fft_multinotch_applied_centers_hz", None)
    params.pop("_fpvs_fft_multinotch_skipped_centers", None)
    params.pop("_fpvs_realized_analysis_span_plan", None)
    params.pop("_fpvs_analysis_scoring_sample_count", None)

    debug_enabled = bool(params.get("debug_preproc", False)) or logger.isEnabledFor(logging.DEBUG)

    fingerprint_in = _build_preproc_fingerprint(params)
    fingerprint_message = f"PREPROC_FINGERPRINT_PREPROCESS_IN {fingerprint_in}"
    log_func(fingerprint_message)
    logger.debug(fingerprint_message)

    # Runtime parameters (defaults are managed by Settings UI; fall back only if absent)
    downsample_rate = params.get("downsample_rate")
    low_pass = params.get("low_pass")
    high_pass = params.get("high_pass")
    line_noise_filter_enabled = bool(
        params.get("line_noise_filter_enabled", True)
    )
    line_noise_frequency_raw = params.get("line_noise_frequency_hz", 60)
    if line_noise_filter_enabled:
        try:
            line_noise_frequency_hz = float(line_noise_frequency_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Line-noise frequency must be exactly 50 or 60 Hz."
            ) from exc
        if line_noise_frequency_hz not in {50.0, 60.0}:
            raise ValueError("Line-noise frequency must be exactly 50 or 60 Hz.")
    else:
        # The disabled path deliberately does not validate or touch EEG data.
        line_noise_frequency_hz = line_noise_frequency_raw
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
            logger.debug(
                "preprocess_start",
                extra={
                    "file": filename_for_log,
                    "downsample_rate": downsample_rate,
                    "low_pass": low_pass,
                    "high_pass": high_pass,
                    "reject_thresh": reject_thresh,
                    "max_idx_keep": max_keep,
                    "stim_ch": stim_ch,
                    "line_noise_filter_enabled": line_noise_filter_enabled,
                    "line_noise_frequency_hz": line_noise_frequency_hz,
                },
            )
        except Exception:
            logger.debug(
                "preprocess_start_logging_failed", extra={"file": filename_for_log}
            )

        checkpoint = checkpoint_identity(raw, params, fingerprint_in)
        checkpoint_cancel = params.get("_fpvs_kurtosis_checkpoint_should_cancel")
        cached = load_checkpoint(checkpoint, should_cancel=checkpoint_cancel)
        if callable(checkpoint_cancel) and checkpoint_cancel():
            raise RuntimeError("Kurtosis preparation cancelled.")
        if cached is not None:
            params.update(cached.params)
            params["_fpvs_kurtosis_checkpoint_status"] = "hit"
            log_func(f"Reusing exact prepared kurtosis checkpoint for {filename_for_log}.")
            return _finish_preprocessing_at_kurtosis(
                cached.raw, params, log_func, filename_for_log,
                orig_sfreq=cached.original_sfreq, geometry_identity=cached.params["_fpvs_geometry"],
                debug_enabled=debug_enabled, checkpoint=checkpoint, cached_evidence=cached.evidence,
            )
        params["_fpvs_kurtosis_checkpoint_status"] = "miss" if checkpoint is not None else "disabled"
        orig_ch_names = list(raw.info["ch_names"])
        orig_sfreq = float(raw.info["sfreq"])
        log_func(
            f"Preprocessing {len(orig_ch_names)} chans from '{filename_for_log}' "
            f"(sfreq={orig_sfreq:.3f} Hz)..."
        )
        if debug_enabled:
            print(
                f"[REF DEBUG] {filename_for_log}: "
                f"ref1={ref1!r} present1={ref1 in orig_ch_names}, "
                f"ref2={ref2!r} present2={ref2 in orig_ch_names}, "
                f"n_ch={len(orig_ch_names)}"
            )
        if debug_enabled:
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
                if debug_enabled:
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
                checkpoint = None
                log_func(
                    f"Warn: Initial reference failed for {filename_for_log}: {e}"
                )
        else:
            checkpoint = None
            log_func(
                f"Skip initial referencing for {filename_for_log} "
                f"(Ref channels '{ref1}', '{ref2}' not found or not specified)."
            )

        # 2) Explicitly drop the selected reference channels after initial reference
        refs_to_drop: List[str] = []
        for ch in (ref1, ref2):
            if ch in raw.ch_names and ch not in refs_to_drop:
                refs_to_drop.append(ch)
        if refs_to_drop:
            raw.drop_channels(refs_to_drop)
            for ch in refs_to_drop:
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
        if debug_enabled:
            log_func(
                f"DEBUG [preprocess for {filename_for_log}]: Channel names BEFORE drop logic "
                f"({len(current_names_before_drop)}): {current_names_before_drop}"
            )
        current_scalp_channels = [
            channel
            for channel in current_names_before_drop
            if channel in BIOSEMI64_CHANNELS
        ]
        if max_keep is not None and 0 < max_keep < len(current_scalp_channels):
            present_scalp = set(current_scalp_channels)
            canonical_scalp_order = [
                channel for channel in BIOSEMI64_CHANNELS if channel in present_scalp
            ]
            retained_scalp = set(canonical_scalp_order[:max_keep])
            final_keep = [
                channel
                for channel in current_names_before_drop
                if channel in retained_scalp or channel == stim_ch
            ]
            unique_keep = set(final_keep)

            if debug_enabled:
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
                drop_count = len(to_drop)
            else:
                keep_count = sum(
                    1 for nm in current_names_before_drop if nm in unique_keep
                )
                drop_count = len(current_names_before_drop) - keep_count

            if drop_count:
                log_func(
                    f"Attempting to drop {drop_count} channels from "
                    f"{filename_for_log}..."
                )
                raw.pick_channels(final_keep, ordered=False)
                log_func(
                    f"{len(raw.ch_names)} channels remain in "
                    f"{filename_for_log} after drop."
                )
                if debug_enabled:
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

        geometry_identity = _freeze_retained_biosemi64_geometry(
            raw,
            params,
            stim_channel=str(stim_ch),
        )
        logger.debug(
            "preprocess_geometry_frozen",
            extra={
                "file": filename_for_log,
                "montage_id": geometry_identity["montage_id"],
                "geometry_version": geometry_identity["geometry_version"],
                "retained_scalp_channel_count": geometry_identity[
                    "retained_scalp_channel_count"
                ],
                "retained_scalp_set_fingerprint": geometry_identity[
                    "retained_scalp_set_fingerprint"
                ],
            },
        )

        # 4) FILTER before downsampling
        l_freq = hp if (hp is not None and hp > 0) else None
        h_freq = lp
        filter_info_to_preserve: Dict[str, float] = {}
        effective_low_pass_for_notch: Optional[float] = None
        if l_freq or h_freq:
            try:
                low_trans_bw, high_trans_bw = 0.1, 0.1
                effective_l = l_freq if l_freq is not None else "DC"
                effective_h = h_freq if h_freq is not None else "Nyq"
                sf_current = float(raw.info.get("sfreq", 0.0))
                filter_len_points = _scaled_filter_length(
                    8449,
                    current_sfreq=sf_current,
                    downsample_rate=downsample_rate,
                )
                snapshot_payload = (
                    f"file={filename_for_log} "
                    f"param_high_pass={high_pass!r} "
                    f"param_low_pass={low_pass!r} "
                    f"computed_l_freq={l_freq!r} "
                    f"computed_h_freq={h_freq!r} "
                    f"sfreq={sf_current} "
                    f"filter_length={filter_len_points}"
                )
                snapshot_message = f"FILTER_SNAPSHOT {snapshot_payload}"
                log_func(snapshot_message)
                logger.debug(snapshot_message)
                if debug_enabled:
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
                if debug_enabled:
                    print(
                        f"[FILTER] {filename_for_log}: FIR bandpass "
                        f"l_freq={effective_l} h_freq={effective_h} "
                        f"sfreq={sf_current:.3f}"
                    )
                filter_raw_with_prepared_fir(
                    raw,
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
                if l_freq is not None and applied_highpass is not None:
                    filter_info_to_preserve["highpass"] = float(applied_highpass)
                if h_freq is not None and applied_lowpass is not None:
                    filter_info_to_preserve["lowpass"] = float(applied_lowpass)
                    effective_low_pass_for_notch = float(applied_lowpass)
                applied_payload = (
                    f"file={filename_for_log} "
                    f"applied_highpass={applied_highpass!r} "
                    f"applied_lowpass={applied_lowpass!r} "
                    f"sfreq={sf_current}"
                )
                applied_message = f"FILTER_APPLIED {applied_payload}"
                log_func(applied_message)
                logger.debug(applied_message)
                if debug_enabled:
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
                    checkpoint = None
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
                checkpoint = None
                log_func(
                    f"Warn: Filter failed for {filename_for_log}: {e}"
                )
                if debug_enabled:
                    print(
                        f"[FILTER] {filename_for_log}: FAILED "
                        f"l_freq={l_freq} h_freq={h_freq}"
                    )
        else:
            log_func(f"Skip filter for {filename_for_log}.")
            if debug_enabled:
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

        # 5) Optional smart FFT multi-notch after FIR and before downsampling
        if line_noise_filter_enabled:
            try:
                notch_result = apply_fft_multinotch(
                    raw,
                    fundamental_hz=line_noise_frequency_hz,
                    low_pass=effective_low_pass_for_notch,
                    stim_channel=stim_ch,
                    h_trans_bandwidth=0.1,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"FFT multi-notch failed for {filename_for_log}: {exc}"
                ) from exc

            requested_centers = list(notch_result.requested_centers_hz)
            applied_centers = list(notch_result.applied_centers_hz)
            skipped_centers = [
                {"center_hz": skipped.center_hz, "reason": skipped.reason}
                for skipped in notch_result.skipped_centers
            ]
            params["_fpvs_fft_multinotch_requested_centers_hz"] = requested_centers
            params["_fpvs_fft_multinotch_applied_centers_hz"] = applied_centers
            params["_fpvs_fft_multinotch_skipped_centers"] = skipped_centers

            requested_text = ",".join(f"{value:g}" for value in requested_centers)
            applied_text = ",".join(f"{value:g}" for value in applied_centers)
            skipped_text = ";".join(
                f"{entry['center_hz']:g}:{entry['reason']}"
                for entry in skipped_centers
            )
            if applied_centers:
                message = (
                    "FFT_MULTINOTCH_APPLIED "
                    f"file={filename_for_log} requested_hz={requested_text} "
                    f"applied_hz={applied_text} skipped={skipped_text or 'none'} "
                    f"half_width_hz={notch_result.half_width_hz:g} "
                    f"channel_count={len(notch_result.filtered_channels)} "
                    f"segments={notch_result.segment_count}"
                )
            else:
                message = (
                    "FFT_MULTINOTCH_SMART_SKIP "
                    f"file={filename_for_log} requested_hz={requested_text} "
                    f"skipped={skipped_text or 'none'}"
                )
            log_func(message)
            logger.debug(message)
            try:
                logger.debug(
                    "preprocess_stage_after_fft_multinotch",
                    extra={
                        "file": filename_for_log,
                        "requested_centers_hz": requested_centers,
                        "applied_centers_hz": applied_centers,
                        "skipped_centers": skipped_centers,
                        "sfreq": float(raw.info.get("sfreq", -1.0)),
                    },
                )
            except (TypeError, ValueError, RuntimeError):
                logger.debug(
                    "preprocess_stage_after_fft_multinotch_logging_failed",
                    extra={"file": filename_for_log},
                )
        else:
            log_func(f"Skip FFT multi-notch for {filename_for_log} (disabled).")

        # 6) Downsample after filtering
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
                    if filter_info_to_preserve:
                        try:
                            with raw.info._unlock():
                                for key, value in filter_info_to_preserve.items():
                                    raw.info[key] = value
                        except (AttributeError, RuntimeError, TypeError, ValueError):
                            checkpoint = None
                            logger.debug(
                                "preprocess_restore_filter_info_after_downsample_failed",
                                extra={"file": filename_for_log},
                                exc_info=True,
                            )
                    log_func(
                        f"Resampled {filename_for_log} to {new_sf:.3f} Hz."
                    )
                    if debug_enabled:
                        logger.debug(
                            "[DS] %s: sfreq %.3f -> %.3f",
                            filename_for_log,
                            sf,
                            new_sf,
                        )
                except Exception as resample_err:
                    checkpoint = None
                    log_func(
                        f"Warn: Resampling failed for {filename_for_log}: "
                        f"{resample_err}"
                    )
                    if debug_enabled:
                        logger.debug(
                            "[DS] %s: RESAMPLE FAILED (sfreq=%.3f, target=%s)",
                            filename_for_log,
                            sf,
                            downsample_rate,
                        )
            else:
                log_func(
                    f"No downsampling needed for {filename_for_log} "
                    f"(sfreq={sf:.3f}, target={downsample_rate})."
                )
                if debug_enabled:
                    logger.debug(
                        "[DS] %s: no resample (sfreq=%.3f, target=%s)",
                        filename_for_log,
                        sf,
                        downsample_rate,
                    )
        else:
            log_func(f"Skip downsample for {filename_for_log}.")
            if debug_enabled:
                logger.debug("[DS] %s: skip (no downsample_rate set)", filename_for_log)
        try:
            logger.debug(
                "preprocess_stage_after_downsample",
                extra={
                    "file": filename_for_log,
                    "sfreq": float(raw.info.get("sfreq", -1.0)),
                },
            )
        except (TypeError, ValueError, RuntimeError):
            logger.debug(
                "preprocess_stage_after_downsample_logging_failed",
                extra={"file": filename_for_log},
            )

        _realize_analysis_spans_for_raw(raw, params)

        return _finish_preprocessing_at_kurtosis(
            raw, params, log_func, filename_for_log, orig_sfreq=orig_sfreq,
            geometry_identity=geometry_identity, debug_enabled=debug_enabled,
            checkpoint=checkpoint,
        )

    except Exception as e:
        params["_fpvs_preprocessing_error"] = str(e)
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

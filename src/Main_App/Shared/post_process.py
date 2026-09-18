# post_process.py
import logging
import os
import hashlib
import json
import pandas as pd
import numpy as np
import traceback
import gc
import mne
import re
from contextvars import ContextVar
from fractions import Fraction
from pathlib import Path
from time import perf_counter
from config import DEFAULT_ELECTRODE_NAMES_64  # Ensure these are correct
from typing import List, Any, Dict
from Tools.Stats.analysis.full_snr import (
    compute_full_snr_from_amplitudes,
    compute_full_snr_prefix_from_amplitudes,
)
from Tools.Stats.analysis.noise_utils import (
    compute_qc14_standard_metrics,
)
from Main_App.Shared.fft_crop_utils import compute_onbin_N, compute_onbin_step
from Main_App.processing.fft_multinotch import (
    FFT_MULTINOTCH_HALF_WIDTH_HZ,
    FFT_MULTINOTCH_METHOD_VERSION,
)
from Main_App.processing.spectral_eligibility import (
    SpectralEligibilityError,
    SpectralEligibilityResult,
    resolve_spectral_eligibility,
)
from Main_App.processing.output_integrity import (
    OutputIntegrityError,
    require_finite_computable_bca,
    require_finite_retained_signal,
)
from Main_App.processing.condition_electrode_interpolation import condition_interpolation_export_provenance
from Main_App.projects.frequency_protocol import (
    FrequencyProtocol,
    normalize_frequency_protocol,
)
from Main_App.projects.grouping import (
    resolve_group_output_directory,
    resolve_output_directory,
)


from Main_App.Shared.post_process_excel import (
    build_fft_neighbors_rows,
    workbook_artifact_identity,
    write_results_workbook,
)


logger = logging.getLogger(__name__)
_EXPORT_TIMING_SINK: ContextVar[list[dict[str, object]] | None] = ContextVar(
    "_EXPORT_TIMING_SINK",
    default=None,
)
RECORDING_CONDITION_EXPORT_RECEIPT_VERSION = (
    "recording_condition_export_receipt_v1"
)


def _export_receipt_sink(app: Any) -> list[dict[str, object]]:
    sink = getattr(app, "export_receipts", None)
    if isinstance(sink, list):
        return sink
    sink = []
    setattr(app, "export_receipts", sink)
    return sink


def _run_identity_payload(app: Any, *, fallback_recording_id: str) -> dict[str, object]:
    settings = getattr(app, "settings", None)
    settings = settings if isinstance(settings, dict) else {}
    geometry = settings.get("_fpvs_geometry")
    source_spans = settings.get("_fpvs_source_analysis_span_plan")
    target_spans = settings.get("_fpvs_realized_analysis_span_plan")
    return {
        "run_id": str(settings.get("_fpvs_expected_plan_run_id") or ""),
        "processing_fingerprint": str(
            settings.get("_fpvs_processing_fingerprint") or ""
        ),
        "processing_fingerprint_version": str(
            settings.get("_fpvs_processing_fingerprint_version") or ""
        ),
        "recording_id": str(
            settings.get("_fpvs_recording_id") or fallback_recording_id
        ),
        "participant_id": str(
            settings.get("_fpvs_participant_id") or fallback_recording_id
        ),
        "session_id": str(settings.get("_fpvs_session_id") or ""),
        "geometry": dict(geometry) if isinstance(geometry, dict) else None,
        "source_analysis_span_plan_fingerprint": str(
            source_spans.get("fingerprint")
            if isinstance(source_spans, dict)
            else ""
        ),
        "target_analysis_span_plan_fingerprint": str(
            target_spans.get("fingerprint")
            if isinstance(target_spans, dict)
            else ""
        ),
    }


def _fingerprinted_export_receipt(
    payload: dict[str, object],
) -> dict[str, object]:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        **payload,
        "fingerprint": hashlib.sha256(canonical).hexdigest(),
    }


def _retained_occurrence_receipts(data_object: Any, object_index: int) -> list[dict[str, object]]:
    """Extract exact retained spans already carried by active Epochs metadata."""

    metadata = getattr(data_object, "metadata", None)
    if not isinstance(metadata, pd.DataFrame) or metadata.empty:
        return [
            {
                "status": "retained",
                "object_index": int(object_index),
                "occurrence_index": 1,
                "span_status": "legacy_unknown",
            }
        ]

    receipts: list[dict[str, object]] = []
    for row_position, (_, row) in enumerate(metadata.iterrows(), start=1):
        def _integer(name: str) -> int | None:
            value = row.get(name)
            if value is None or pd.isna(value):
                return None
            return int(value)

        receipts.append(
            {
                "status": "retained",
                "object_index": int(object_index),
                "occurrence_index": row_position,
                "span_status": (
                    "exact"
                    if row.get("approved_span_fingerprint")
                    else "legacy_unknown"
                ),
                "approved_span_fingerprint": str(
                    row.get("approved_span_fingerprint") or ""
                ),
                "marker_plan_fingerprint": str(
                    row.get("marker_plan_fingerprint") or ""
                ),
                "source_start_sample": _integer("source_start_sample"),
                "source_stop_sample": _integer("source_stop_sample"),
                "target_start_sample": _integer("target_start_sample"),
                "target_stop_sample": _integer("target_stop_sample"),
                "marker_disposition": str(row.get("marker_disposition") or ""),
            }
        )
    return receipts


def _blocked_export_receipt(
    app: Any,
    *,
    pid: str,
    condition_label: str,
    path: str | None,
    stage: str,
    reason: str,
    integrity_failure: dict[str, object] | None = None,
) -> dict[str, object]:
    """Record a current-run failure without treating an older file as output."""

    return _fingerprinted_export_receipt({
        "version": RECORDING_CONDITION_EXPORT_RECEIPT_VERSION,
        "status": "blocked",
        **_run_identity_payload(app, fallback_recording_id=pid),
        "condition_label": str(condition_label),
        "path": str(Path(path).resolve()) if path else None,
        "failure_stage": stage,
        "reason": str(reason),
        "integrity_failure": integrity_failure,
        "prior_artifact": workbook_artifact_identity(path) if path else None,
        "current_run_artifact": None,
    })


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _mean_epochs_float64(epoch_data: np.ndarray) -> np.ndarray:
    """Average epochs without copying a contiguous native-float64 array."""

    epoch_array = np.asarray(epoch_data)
    if epoch_array.dtype == np.dtype(np.float64) and (
        epoch_array.flags.c_contiguous or epoch_array.flags.f_contiguous
    ):
        averaging_data = epoch_array
    else:
        # Preserve the established copy/layout for strided and broadcast
        # arrays, whose reduction can otherwise differ at the final bit.
        averaging_data = epoch_array.astype(np.float64)
    return np.mean(averaging_data, axis=0)


def _eeg_pick_indices(data_object: Any, *, is_evoked: bool) -> np.ndarray:
    """Return the same ordered EEG picks used by ``copy().pick('eeg')``."""

    return mne.pick_types(
        data_object.info,
        meg=False,
        eeg=True,
        exclude=[] if is_evoked else "bads",
    )


def _can_batch_target_noise(
    amplitudes: np.ndarray,
    target_bin_indices: np.ndarray,
    *,
    window_size: int = 10,
) -> bool:
    """Return whether every target window can use the exact batch reduction."""

    amplitude_matrix = np.asarray(amplitudes)
    if (
        amplitude_matrix.dtype != np.dtype(np.float64)
        or not amplitude_matrix.flags.c_contiguous
    ):
        return False
    num_bins = amplitude_matrix.shape[1]
    for target_index in target_bin_indices:
        target = int(target_index)
        if target < 0:
            continue
        low = max(0, target - window_size)
        high = min(num_bins - 1, target + window_size)
        noise_indices = [
            index
            for index in range(low, high + 1)
            if index not in {target - 1, target, target + 1}
        ]
        if len(noise_indices) < 4:
            continue
        noise_values = amplitude_matrix[:, noise_indices]
        absolute_values = np.abs(noise_values)
        if (
            not np.all(np.isfinite(absolute_values))
            or not np.all(absolute_values >= 1e-100)
            or not np.all(absolute_values <= 1e100)
            or np.any(np.ptp(noise_values, axis=1) == 0.0)
        ):
            return False
    return True


def _create_output_subfolder(
    app: Any,
    parent_folder: str | os.PathLike[str],
    condition_folder: object,
    group_folder: object | None,
) -> str:
    """Create one strict condition/group export folder or raise."""

    output_path = resolve_output_directory(Path(parent_folder), condition_folder)
    if group_folder:
        output_path = resolve_group_output_directory(output_path, group_folder)
    try:
        os.makedirs(output_path, exist_ok=True)
    except OSError as exc:
        app.log(
            f"Error creating required output folder {output_path}: {exc}. "
            "Processing cannot continue."
        )
        raise
    return os.fspath(output_path)


def _log_export_timing(
    stage: str,
    started_at: float,
    *,
    pid: str | None = None,
    condition: str | None = None,
    object_index: int | None = None,
    path: str | None = None,
    extra: str | None = None,
) -> None:
    elapsed_ms = _elapsed_ms(started_at)
    record = {
        "source": "post_process",
        "stage": stage,
        "elapsed_ms": elapsed_ms,
        "pid": pid,
        "condition": condition,
        "object_index": object_index,
        "path": path,
        "extra": extra,
    }
    timing_sink = _EXPORT_TIMING_SINK.get()
    if timing_sink is not None:
        timing_sink.append(record)
    logger.debug(
        "[EXPORT TIMING] stage=%s elapsed_ms=%d pid=%r condition=%r object_index=%s path=%r extra=%r",
        stage,
        elapsed_ms,
        pid,
        condition,
        object_index,
        path,
        extra,
    )


def _read_analysis_setting(app: Any, option: str, default: float | str) -> Any:
    """Return analysis setting from SettingsManager-like objects or plain dict payloads."""
    settings = getattr(app, "settings", None)
    if settings is None:
        return default

    getter = getattr(settings, "get", None)
    if callable(getter):
        try:
            # SettingsManager signature: get(section, option, fallback)
            return getter("analysis", option, str(default))
        except TypeError:
            # dict-like getter may not accept 3 args
            pass
        except Exception:
            pass

    if isinstance(settings, dict):
        analysis_section = settings.get("analysis")
        if isinstance(analysis_section, dict) and option in analysis_section:
            return analysis_section.get(option, default)
        if option in settings:
            return settings.get(option, default)

    if hasattr(settings, option):
        try:
            return getattr(settings, option)
        except Exception:
            pass

    return default


def _read_analysis_float(app: Any, option: str, default: float) -> float:
    value = _read_analysis_setting(app, option, default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _resolve_frequency_protocol(app: Any) -> FrequencyProtocol:
    """Return the required immutable project protocol from the run snapshot."""

    settings = getattr(app, "settings", None)
    raw_protocol = settings.get("frequency_protocol") if isinstance(settings, dict) else None
    if raw_protocol is None and isinstance(settings, dict):
        analysis = settings.get("analysis")
        if isinstance(analysis, dict):
            raw_protocol = analysis.get("frequency_protocol")
    if raw_protocol is None:
        raise SpectralEligibilityError(
            "Post-processing requires the immutable project frequency protocol; "
            "global 1.2-Hz and BCA-ceiling fallbacks are retired."
        )
    protocol = normalize_frequency_protocol(raw_protocol)
    if not protocol.is_ready:
        raise SpectralEligibilityError(
            "Post-processing requires a ready project frequency protocol with an "
            "expected analyzed oddball-cycle count."
        )
    return protocol


def _applied_notch_centers(settings: Any) -> tuple[float, ...]:
    if not isinstance(settings, dict):
        raise SpectralEligibilityError(
            "Post-processing requires the immutable preprocessing settings snapshot."
        )
    if not bool(settings.get("line_noise_filter_enabled", True)):
        return ()
    if "_fpvs_fft_multinotch_applied_centers_hz" not in settings:
        raise SpectralEligibilityError(
            "Applied line-noise notch metadata is missing; affected spectral "
            "frequencies cannot be inferred from the requested setting."
        )
    raw_centers = settings.get("_fpvs_fft_multinotch_applied_centers_hz")
    if raw_centers in (None, ""):
        return ()
    if not isinstance(raw_centers, (list, tuple)):
        raise SpectralEligibilityError(
            "Applied line-noise notch centers must be a sequence."
        )
    return tuple(float(value) for value in raw_centers)


def _frequency_column_names(frequencies: np.ndarray) -> list[str]:
    """Use four-decimal labels when unique and expand only to avoid collisions."""

    numeric = [float(value) for value in frequencies]
    for places in range(4, 13):
        labels = [f"{value:.{places}f}_Hz" for value in numeric]
        if len(labels) == len(set(labels)):
            return labels
    raise ValueError(
        "The realized FFT grid cannot be represented by unique workbook frequency "
        "headers through 12 decimal places."
    )


def _resolve_condition_id(event_id_map: Dict[str, Any], condition_label: str) -> int | None:
    if not event_id_map:
        return None

    if condition_label in event_id_map:
        try:
            return int(event_id_map[condition_label])
        except Exception:
            return None

    def _normalize(lbl: str) -> str:
        return re.sub(r"^\d+\s*-\s*", "", str(lbl)).strip().lower()

    target = _normalize(condition_label)
    for label, value in event_id_map.items():
        if _normalize(label) == target:
            try:
                return int(value)
            except Exception:
                return None
    return None


def _load_events_for_file(raw_path: str, event_id_map: Dict[str, Any], stim_channel_name: str = "Status"):
    raw = mne.io.read_raw(raw_path, preload=False, verbose=False)
    try:
        events = np.array([])
        if len(raw.annotations) > 0 and event_id_map:
            mne_annots_event_id_map = {
                str(desc): int(val)
                for desc, val in event_id_map.items()
                if str(desc) in raw.annotations.description
            }
            if mne_annots_event_id_map:
                events, _ = mne.events_from_annotations(raw, event_id=mne_annots_event_id_map, verbose=False)
        if events.size == 0:
            events = mne.find_events(raw, stim_channel=stim_channel_name, consecutive=True, verbose=False)
        return events, int(raw.n_times)
    finally:
        raw.close()


def _attempt_legacy_55_onbin_crop(
    avg_data: np.ndarray,
    sfreq: float,
    data_idx: int,
    condition_id: int,
    onset_ids: list[int],
    global_events: np.ndarray,
    stream_end_sample: int,
    epoch_tmin_sec: float,
    oddball_rate_hz: Fraction,
    oddball_marker_code: int,
):
    num_channels, num_times = avg_data.shape
    samples_55 = []
    n55 = None
    first55_samp = None
    last55_samp = None
    n_step = None

    cond_starts = [int(row[0]) for row in global_events if int(row[2]) == condition_id]
    all_starts = sorted([int(row[0]) for row in global_events if int(row[2]) in onset_ids])
    if not cond_starts:
        raise ValueError("locked FFT crop unavailable: no_condition_starts")
    if not all_starts:
        raise ValueError("locked FFT crop unavailable: no_onset_starts")

    rep_idx = min(data_idx, len(cond_starts) - 1)
    block_start = cond_starts[rep_idx]
    block_end = next((s for s in all_starts if s > block_start), stream_end_sample)

    samples_55 = [
        int(row[0])
        for row in global_events
        if (
            block_start < int(row[0]) < block_end
            and int(row[2]) == oddball_marker_code
        )
    ]
    n55 = int(len(samples_55))
    first55_samp = int(samples_55[0]) if samples_55 else None
    last55_samp = int(samples_55[-1]) if samples_55 else None

    _, n_step, step_err = compute_onbin_step(
        fs=float(sfreq),
        f_oddball=oddball_rate_hz,
    )
    if step_err or n_step is None:
        raise ValueError(f"locked FFT crop unavailable: {step_err or 'step_error'}")
    if len(samples_55) < 2:
        reason = (
            f"no_{oddball_marker_code}_in_block"
            if len(samples_55) == 0
            else f"insufficient_{oddball_marker_code}"
        )
        raise ValueError(f"locked FFT crop unavailable: {reason}")

    available_samples = int(block_end - first55_samp)
    n_used = int(compute_onbin_N(available_samples=available_samples, N_step=n_step))
    data_start_sample = int(round(block_start + epoch_tmin_sec * sfreq))
    crop_start_idx = int(max(0, first55_samp - data_start_sample))
    max_available_from_epoch = int(max(0, num_times - crop_start_idx))
    n_used = int(compute_onbin_N(available_samples=min(n_used, max_available_from_epoch), N_step=n_step))

    if n_used < n_step:
        raise ValueError("locked FFT crop unavailable: too_short_for_step")

    cropped = avg_data[:, crop_start_idx:crop_start_idx + n_used]
    return cropped, "55_onbin", n55, first55_samp, last55_samp, n_step, ""

def post_process(app: Any, condition_labels_present: List[str]) -> None:
    """
    Calculates metrics (FFT, SNR, Z-score, BCA) and saves results to Excel.
    Handles single-file processing (FPVSApp) and per-participant averaged results (AdvancedAnalysis).

    This is pipeline-sensitive export code. Targeted refactor edits are allowed,
    but must not change metric calculation, processing order, output formats,
    filenames, sheet names, or export behavior.
    """
    post_started = perf_counter()
    export_timing_sink = getattr(app, "export_timing_records", None)
    export_receipts = _export_receipt_sink(app)
    _EXPORT_TIMING_SINK.set(
        export_timing_sink if isinstance(export_timing_sink, list) else None
    )
    app.log("--- Post-processing: Calculating Metrics & Saving Results ---")
    parent_folder = app.save_folder_path.get()
    logger.debug(
        "[EXPORT STAGE] post_process_start conditions=%d parent_folder=%r",
        len(condition_labels_present),
        parent_folder,
    )
    if not parent_folder or not os.path.isdir(parent_folder):
        app.log(f"Error: Invalid save folder: '{parent_folder}'")
        _log_export_timing(
            "post_process_invalid_save_folder",
            post_started,
            path=parent_folder,
        )
        return

    frequency_protocol = _resolve_frequency_protocol(app)
    if (
        frequency_protocol.oddball_rate_hz is None
        or frequency_protocol.presentation_rate_hz is None
        or frequency_protocol.oddball_marker_code is None
    ):
        raise SpectralEligibilityError(
            "The project frequency protocol is missing canonical rate or marker identity."
        )
    app.log(
        "Using the project FPVS protocol: "
        f"presentation={float(frequency_protocol.presentation_rate_hz):g} Hz, "
        f"oddball={float(frequency_protocol.oddball_rate_hz):g} Hz, "
        f"expected_cycles={frequency_protocol.expected_analyzed_oddball_cycles}."
    )

    # --- PID Determination ---
    pid = "UnknownPID"
    # For Advanced Analysis, 'pid_for_group' on the context now holds the participant_pid
    if hasattr(app, "pid_for_group") and app.pid_for_group:
        pid = app.pid_for_group  # This should be "P1", "P2", etc.
        app.log(f"Using PID from context: {pid}")
    elif app.data_paths:  # Fallback for original FPVSApp single-file processing
        try:
            first_file_path = app.data_paths[0]
            first_file_basename = os.path.basename(first_file_path)
            pid_base = os.path.splitext(first_file_basename)[0]
            pid_regex = r"\b(P\d+|Sub\d+|S\d+)\b"
            match = re.search(pid_regex, pid_base, re.IGNORECASE)
            if match:
                pid = match.group(1).upper()
            else:
                pid_cleaned = re.sub(
                    r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_fpvs|_raw|_preproc|_ica).*$",
                    "",
                    pid_base,
                    flags=re.IGNORECASE,
                )
                pid_cleaned = re.sub(r"[^a-zA-Z0-9]", "", pid_cleaned)
                pid = pid_cleaned if pid_cleaned else pid_base
            app.log(f"Extracted PID for single file processing: {pid}")
        except Exception as e:
            app.log(f"Warn: Could not extract PID from app.data_paths[0]: {e}")
    else:
        app.log("Warning: Could not determine PID. Using default 'UnknownPID'.")

    any_results_saved = False
    current_epochs_data_source = app.preprocessed_data
    event_cache: Dict[str, tuple[np.ndarray, int]] = {}

    for cond_label_from_keys in condition_labels_present:
        condition_started = perf_counter()
        data_list = current_epochs_data_source.get(cond_label_from_keys, [])
        if not data_list:
            app.log(f"\nSkipping post-processing for '{cond_label_from_keys}': No data found.")
            export_receipts.append(
                _blocked_export_receipt(
                    app,
                    pid=pid,
                    condition_label=cond_label_from_keys,
                    path=None,
                    stage="condition_input",
                    reason=(
                        "No retained data object reached post-processing. The "
                        "processing ledger must reconcile this with an explicit "
                        "excluded or unavailable occurrence outcome."
                    ),
                )
            )
            _log_export_timing(
                "condition_skip_no_data",
                condition_started,
                pid=pid,
                condition=cond_label_from_keys,
            )
            continue

        app.log(
            f"\nPost-processing '{cond_label_from_keys}' (PID: {pid}, {len(data_list)} data object(s))..."
        )
        logger.debug(
            "[EXPORT STAGE] condition_start pid=%r condition=%r objects=%d",
            pid,
            cond_label_from_keys,
            len(data_list),
        )

        # --- Output Naming Logic ---
        folder_name_base = ""
        filename_condition_part = ""
        excel_final_suffix = ".xlsx"  # Desired suffix for advanced outputs

        # Check if this is an output from the advanced analysis per-participant flow
        is_advanced_output = (
            hasattr(app, "group_name_for_output")
            and app.group_name_for_output
            and app.group_name_for_output == cond_label_from_keys
        )

        if is_advanced_output:
            # Use the recipe name (e.g., "Average A") from the context
            condition_recipe_name = app.group_name_for_output
            # Sanitize for folder and file: replace spaces with underscores, etc.
            sanitized_recipe_name = (
                condition_recipe_name.replace(" ", "_")
                .replace("/", "-")
                .replace("\\", "-")
                .strip()
            )
            sanitized_recipe_name = re.sub(
                r"^\d+\s*-\s*", "", sanitized_recipe_name
            )  # Remove "1 - " prefixes etc.

            folder_name_base = sanitized_recipe_name  # Subfolder e.g., "Average_A"
            filename_condition_part = sanitized_recipe_name  # File part e.g., "Average_A"
            # pid is already the participant_pid, e.g., "P1"
            excel_filename = f"{pid}_{filename_condition_part}{excel_final_suffix}"  # e.g., "P1_Average_A.xlsx"
        else:
            # Original FPVSApp single-file processing path
            raw_condition_label = cond_label_from_keys
            sanitized_condition_label = re.sub(
                r"^\d+\s*-\s*",
                "",
                raw_condition_label.replace("/", "-").replace("\\", "-").strip(),
            )

            folder_name_base = sanitized_condition_label
            filename_condition_part = sanitized_condition_label
            output_stem = pid
            settings = getattr(app, "settings", None)
            if isinstance(settings, dict):
                configured_stem = str(
                    settings.get("output_recording_stem") or ""
                ).strip()
                if configured_stem:
                    if (
                        configured_stem in {".", ".."}
                        or Path(configured_stem).name != configured_stem
                        or "/" in configured_stem
                        or "\\" in configured_stem
                    ):
                        raise ValueError(
                            "Repeated-session output identity must be one safe "
                            "filename component."
                        )
                    output_stem = configured_stem
            # Legacy projects keep the exact PID-based filename. Repeated-
            # session projects supply a canonical participant__session stem.
            excel_filename = (
                f"{output_stem}_{filename_condition_part}_Results.fpvs"
            )

        output_group_folder = None
        grouped_project = False
        settings = getattr(app, "settings", None)
        if isinstance(settings, dict):
            output_group_folder = settings.get("output_group_folder")
            grouped_project = bool(settings.get("_fpvs_grouped_project", False))
        if grouped_project and not output_group_folder:
            raise ValueError(
                "Grouped processing is missing its canonical output group folder."
            )

        output_subfolder_path = _create_output_subfolder(
            app,
            parent_folder,
            folder_name_base,
            output_group_folder,
        )

        full_excel_path = os.path.join(output_subfolder_path, excel_filename)
        app.log(f"Target results path for '{cond_label_from_keys}': {full_excel_path}")

        # --- Metrics Calculation (largely unchanged) ---
        accum = {"fft": None, "snr": None, "z": None, "bca": None}
        full_snr_accum = None
        full_snr_frequencies = None
        full_fft_accum = None
        fft_neighbors_rows: List[Dict[str, Any]] = []
        spectral_metric_qc_rows: List[Dict[str, Any]] = []
        condition_eligibility: SpectralEligibilityResult | None = None
        target_frequencies = np.asarray([], dtype=float)
        full_snr_max_frequency = 0.0
        valid_data_count = 0
        final_num_channels = 0
        final_electrode_names_ordered = []
        source_integrity_receipts: list[dict[str, object]] = []
        retained_occurrences: list[dict[str, object]] = []

        for data_idx, data_object in enumerate(data_list):  # Should be one Evoked for advanced
            is_evoked = isinstance(data_object, mne.Evoked)
            if not (hasattr(data_object, "info") and (is_evoked or hasattr(data_object, "get_data"))):
                app.log(
                    f"    Item {data_idx + 1} is not a valid MNE data object. Skipping."
                )
                continue
            app.log(
                f"  Processing data object {data_idx + 1}/{len(data_list)} for '{cond_label_from_keys}'..."
            )
            gc.collect()
            object_started = perf_counter()
            data_eeg = None
            try:
                if not is_evoked:  # Epochs
                    if not data_object.preload:
                        data_object.load_data()
                    if len(data_object.events) == 0:
                        app.log("    Epochs object 0 events. Skip.")
                        continue

                    # ...
                pick_started = perf_counter()
                eeg_pick_indices = None
                if is_evoked or isinstance(data_object, mne.BaseEpochs):
                    candidate_indices = _eeg_pick_indices(
                        data_object,
                        is_evoked=is_evoked,
                    )
                    if candidate_indices.size:
                        eeg_pick_indices = candidate_indices
                        current_ch_names_from_obj = [
                            data_object.ch_names[int(index)]
                            for index in eeg_pick_indices
                        ]
                    else:
                        # Preserve MNE's established exception/warning behavior
                        # for the unusual no-EEG/all-bad case.
                        data_eeg = data_object.copy().pick(
                            "eeg", exclude="bads" if not is_evoked else []
                        )
                        current_ch_names_from_obj = list(data_eeg.info["ch_names"])
                else:
                    # Custom MNE-like objects may implement pick semantics that
                    # cannot be reproduced safely from their Info structure.
                    data_eeg = data_object.copy().pick(
                        "eeg", exclude="bads" if not is_evoked else []
                    )
                    current_ch_names_from_obj = list(data_eeg.info["ch_names"])
                _log_export_timing(
                    "object_pick_eeg",
                    pick_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    object_index=data_idx + 1,
                )
                if not current_ch_names_from_obj:
                    app.log("    No good EEG channels. Skip.")
                    continue

                if is_evoked:
                    avg_data = (
                        data_object.data[eeg_pick_indices, :]
                        if data_eeg is None
                        else data_eeg.data
                    )
                else:  # Epochs
                    average_started = perf_counter()
                    ep_data = (
                        data_object.get_data(
                            picks=eeg_pick_indices,
                            copy=True,
                        )
                        if data_eeg is None
                        else data_eeg.get_data()
                    )
                    avg_data = _mean_epochs_float64(ep_data)
                    _log_export_timing(
                        "epochs_get_data_average",
                        average_started,
                        pid=pid,
                        condition=cond_label_from_keys,
                        object_index=data_idx + 1,
                    )
                num_channels, num_times = avg_data.shape
                # ...
                ordered_electrode_names_for_df = []

                if num_channels == len(DEFAULT_ELECTRODE_NAMES_64) and set(
                    current_ch_names_from_obj
                ) == set(DEFAULT_ELECTRODE_NAMES_64):
                    ordered_electrode_names_for_df = [
                        name
                        for name in DEFAULT_ELECTRODE_NAMES_64
                        if name in current_ch_names_from_obj
                    ]
                    name_to_idx_map = {
                        name: i for i, name in enumerate(current_ch_names_from_obj)
                    }
                    reorder_indices = [
                        name_to_idx_map[name] for name in ordered_electrode_names_for_df
                    ]
                    avg_data = avg_data[reorder_indices, :]
                    app.log(
                        f"    Standardized channel order to {len(ordered_electrode_names_for_df)} channels."
                    )
                elif num_channels == len(DEFAULT_ELECTRODE_NAMES_64):
                    app.log(
                        f"    Warn: Found {num_channels} channels, names don't match default. Using default order/names."
                    )
                    ordered_electrode_names_for_df = DEFAULT_ELECTRODE_NAMES_64
                else:
                    app.log(
                        f"    Warn: Found {num_channels} channels. Using actual names/order."
                    )
                    ordered_electrode_names_for_df = current_ch_names_from_obj

                if valid_data_count == 0:
                    final_num_channels = num_channels
                    final_electrode_names_ordered = ordered_electrode_names_for_df
                if (
                    num_channels != final_num_channels
                    or ordered_electrode_names_for_df != final_electrode_names_ordered
                ):
                    app.log("    Error: Channel mismatch. Skipping object.")
                    continue

                sfreq = (
                    data_object.info["sfreq"]
                    if data_eeg is None
                    else data_eeg.info["sfreq"]
                )

                crop_mode = "missing_locked_fft_crop"
                n55 = None
                first55_samp = None
                last55_samp = None
                n_step = None
                fallback_reason = "legacy_epoch_path"

                if is_evoked and app.data_paths:
                    crop_started = perf_counter()
                    validated_params = getattr(app, "validated_params", {}) or {}
                    event_id_map = validated_params.get("event_id_map", {})
                    condition_id = _resolve_condition_id(event_id_map, cond_label_from_keys)
                    onset_ids = sorted({int(v) for v in event_id_map.values() if str(v).isdigit()})
                    epoch_tmin_sec = float(data_object.times[0])
                    if condition_id is None:
                        fallback_reason = "missing_condition_id"
                    elif not onset_ids:
                        fallback_reason = "missing_onset_ids"
                    else:
                        try:
                            source_path = app.data_paths[0]
                            if source_path not in event_cache:
                                event_cache[source_path] = _load_events_for_file(raw_path=source_path, event_id_map=event_id_map)
                            global_events, stream_end_sample = event_cache[source_path]

                            avg_data, crop_mode, n55, first55_samp, last55_samp, n_step, fallback_reason = _attempt_legacy_55_onbin_crop(
                                avg_data=avg_data,
                                sfreq=float(sfreq),
                                data_idx=int(data_idx),
                                condition_id=int(condition_id),
                                onset_ids=onset_ids,
                                global_events=global_events,
                                stream_end_sample=int(stream_end_sample),
                                epoch_tmin_sec=float(epoch_tmin_sec),
                                oddball_rate_hz=frequency_protocol.oddball_rate_hz,
                                oddball_marker_code=int(
                                    frequency_protocol.oddball_marker_code
                                ),
                            )
                            num_channels, num_times = avg_data.shape
                        except Exception as crop_err:
                            app.log(f"    Warn: 55-based crop attempt failed in legacy path: {crop_err}")
                            fallback_reason = "crop_exception"
                    _log_export_timing(
                        "legacy_event_crop",
                        crop_started,
                        pid=pid,
                        condition=cond_label_from_keys,
                        object_index=data_idx + 1,
                        extra=f"crop_mode={crop_mode}",
                    )

                if not is_evoked and getattr(data_object, "metadata", None) is not None and not data_object.metadata.empty:
                    metadata_started = perf_counter()
                    md = data_object.metadata
                    crop_modes = [m for m in md.get("crop_mode", pd.Series(dtype=object)).dropna().astype(str).tolist() if m]
                    supported_crop_modes = {
                        "55_onbin",
                        "project_marker_plan_target_grid_v2",
                    }
                    unique_crop_modes = set(crop_modes)
                    if (
                        len(unique_crop_modes) == 1
                        and unique_crop_modes.issubset(supported_crop_modes)
                    ):
                        crop_mode = next(iter(unique_crop_modes))
                        fallback_reason = ""
                    elif crop_modes:
                        crop_mode = "non_55_onbin_metadata"
                        fallback_reasons = [
                            r
                            for r in md.get("fallback_reason", pd.Series(dtype=object)).fillna("").astype(str).tolist()
                            if r
                        ]
                        fallback_reason = "; ".join(sorted(set(fallback_reasons))) if fallback_reasons else "mixed_or_fallback_reps"

                    n55_vals = md.get("n55", pd.Series(dtype=float)).dropna().tolist()
                    if n55_vals:
                        n55 = int(min(n55_vals))

                    first_vals = md.get("first55_samp", pd.Series(dtype=float)).dropna().tolist()
                    if first_vals:
                        first55_samp = int(min(first_vals))

                    last_vals = md.get("last55_samp", pd.Series(dtype=float)).dropna().tolist()
                    if last_vals:
                        last55_samp = int(max(last_vals))

                    step_vals = md.get("N_step", pd.Series(dtype=float)).dropna().tolist()
                    if step_vals:
                        unique_steps = sorted({int(v) for v in step_vals})
                        if len(unique_steps) > 1:
                            raise ValueError(f"Inconsistent N_step values for {cond_label_from_keys}: {unique_steps}")
                        n_step = unique_steps[0]
                    _log_export_timing(
                        "epochs_metadata_crop",
                        metadata_started,
                        pid=pid,
                        condition=cond_label_from_keys,
                        object_index=data_idx + 1,
                        extra=f"crop_mode={crop_mode}",
                    )

                if crop_mode in {
                    "55_onbin",
                    "project_marker_plan_target_grid_v2",
                }:
                    if not n_step:
                        raise ValueError(f"Missing N_step for 55_onbin path in condition {cond_label_from_keys}")
                    if num_times % n_step != 0:
                        raise ValueError(
                            f"55_onbin data is not divisible by N_step in post_process: N={num_times}, N_step={n_step}"
                        )
                else:
                    raise ValueError(
                        "Locked FFT crop required before post-processing export: "
                        f"condition={cond_label_from_keys}, crop_mode={crop_mode}, "
                        f"fallback_reason={fallback_reason or 'unknown'}. "
                        "Fixed-epoch FFT fallback is disabled."
                    )

                source_integrity_receipts.append(
                    require_finite_retained_signal(
                        avg_data,
                        electrode_names=ordered_electrode_names_for_df,
                        recording_id=_run_identity_payload(
                            app,
                            fallback_recording_id=pid,
                        )["recording_id"],
                        condition_label=cond_label_from_keys,
                    ).to_payload()
                )

                avg_data_uv = avg_data * 1e6
                if data_idx == 0:
                    app.log(
                        f"    Scaling to uV. Max: {np.max(np.abs(avg_data_uv)):.2f} uV"
                    )

                num_fft_bins = num_times // 2 + 1
                fft_started = perf_counter()
                fft_frequencies = np.fft.rfftfreq(num_times, d=1.0 / sfreq)
                fft_full_spectrum = np.fft.fft(avg_data_uv, axis=1)
                fft_amplitudes = (
                    np.abs(fft_full_spectrum[:, :num_fft_bins]) / num_times * 2
                )
                _log_export_timing(
                    "fft_amplitudes",
                    fft_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    object_index=data_idx + 1,
                    extra=f"channels={num_channels} samples={num_times}",
                )

                run_settings = getattr(app, "settings", None)
                if not isinstance(run_settings, dict):
                    raise SpectralEligibilityError(
                        "Post-processing requires a dictionary run-settings snapshot."
                    )
                source_info = data_object.info if data_eeg is None else data_eeg.info
                object_eligibility = resolve_spectral_eligibility(
                    protocol=frequency_protocol,
                    sampling_rate_hz=sfreq,
                    analyzed_samples=num_times,
                    requested_high_pass_hz=run_settings.get("high_pass"),
                    requested_low_pass_hz=run_settings.get("low_pass"),
                    applied_high_pass_hz=source_info.get("highpass"),
                    applied_low_pass_hz=source_info.get("lowpass"),
                    applied_notch_centers_hz=_applied_notch_centers(run_settings),
                    notch_half_width_hz=FFT_MULTINOTCH_HALF_WIDTH_HZ,
                    notch_method_version=FFT_MULTINOTCH_METHOD_VERSION,
                )
                if not object_eligibility.targets:
                    raise SpectralEligibilityError(
                        "The applied filter/Nyquist range contains no project oddball "
                        "harmonic targets."
                    )
                if condition_eligibility is None:
                    condition_eligibility = object_eligibility
                    target_frequencies = np.asarray(
                        [
                            float(item.target.frequency_hz)
                            for item in object_eligibility.targets
                        ],
                        dtype=float,
                    )
                    full_snr_max_frequency = float(
                        object_eligibility.applied_filter.applied_low_pass_hz
                    )
                    app.log(
                        "    Canonical spectral eligibility: "
                        f"{len(object_eligibility.eligible_targets)} eligible of "
                        f"{len(object_eligibility.targets)} filter-reachable project "
                        f"harmonics; df={float(object_eligibility.bin_width_hz):.9g} Hz."
                    )
                elif object_eligibility.fingerprint != condition_eligibility.fingerprint:
                    raise SpectralEligibilityError(
                        "Multiple FFT inputs for one condition have different filter, "
                        "notch, grid, or harmonic eligibility. A partial average is not "
                        "permitted."
                    )

                source_file_name = os.path.basename(app.data_paths[0]) if app.data_paths else pid
                neighbors_started = perf_counter()
                fft_neighbors_rows.extend(
                    build_fft_neighbors_rows(
                        file_name=source_file_name,
                        condition_label=cond_label_from_keys,
                        condition_id=cond_label_from_keys,
                        repetition_index=str(data_idx + 1),
                        electrode_names=ordered_electrode_names_for_df,
                        fft_amplitudes=fft_amplitudes,
                        freqs=fft_frequencies,
                        fs=sfreq,
                        n_samples=num_times,
                        target_freq=float(frequency_protocol.oddball_rate_hz),
                        crop_mode=crop_mode,
                        n55=n55,
                        first55_samp=first55_samp,
                        last55_samp=last55_samp,
                        n_step=n_step,
                        fallback_reason=fallback_reason,
                    )
                )
                _log_export_timing(
                    "fft_neighbors_rows",
                    neighbors_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    object_index=data_idx + 1,
                    extra=f"rows={len(fft_neighbors_rows)}",
                )

                # Full-spectrum SNR uses the already-computed FFT amplitudes.
                full_snr_started = perf_counter()
                if len(data_list) == 1:
                    full_snr_max_freq = min(
                        full_snr_max_frequency,
                        float(fft_frequencies[-1]),
                    )
                    full_snr_grid = np.arange(
                        0.5,
                        full_snr_max_freq + 0.01,
                        0.01,
                    )
                    highest_full_snr_frequency = (
                        float(full_snr_grid[-1])
                        if len(full_snr_grid)
                        else 0.0
                    )
                    full_snr_bin_count = min(
                        len(fft_frequencies),
                        int(
                            np.searchsorted(
                                fft_frequencies,
                                highest_full_snr_frequency,
                                side="left",
                            )
                        )
                        + 1,
                    )
                    full_snr_matrix = compute_full_snr_prefix_from_amplitudes(
                        fft_amplitudes,
                        output_bin_count=full_snr_bin_count,
                    )
                    full_snr_frequencies = fft_frequencies[:full_snr_bin_count]
                else:
                    # Multiple objects can carry distinct sampling grids while
                    # retaining the same FFT matrix shape. Keep the established
                    # full-spectrum accumulation for that uncommon case.
                    full_snr_matrix = compute_full_snr_from_amplitudes(
                        fft_amplitudes
                    )
                    full_snr_frequencies = fft_frequencies
                _log_export_timing(
                    "full_snr_compute",
                    full_snr_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    object_index=data_idx + 1,
                    extra=f"channels={num_channels} bins={fft_amplitudes.shape[1]}",
                )

                num_target_freqs = len(target_frequencies)
                metrics_fft = np.full(
                    (final_num_channels, num_target_freqs),
                    np.nan,
                    dtype=float,
                )
                metrics_snr = np.full_like(metrics_fft, np.nan)
                metrics_z = np.full_like(metrics_fft, np.nan)
                metrics_bca = np.full_like(metrics_fft, np.nan)

                target_metrics_started = perf_counter()
                if condition_eligibility is None:
                    raise SpectralEligibilityError(
                        "Spectral eligibility was not resolved for this FFT input."
                    )
                eligibility_fingerprint = condition_eligibility.fingerprint
                for chan_idx in range(final_num_channels):
                    channel_amplitudes = fft_amplitudes[chan_idx, :]
                    for freq_idx, availability in enumerate(
                        condition_eligibility.targets
                    ):
                        metric_result = compute_qc14_standard_metrics(
                            channel_amplitudes,
                            target_idx=availability.target_bin_index,
                            candidate_bin_indices=(
                                availability.noise_candidate_bin_indices
                            ),
                            static_metrics_available=(
                                availability.standard_metrics_available
                            ),
                            static_reason_codes=availability.reason_codes,
                            target_amplitude_status=(
                                availability.target_amplitude_status
                            ),
                        )
                        if (
                            metric_result.target_amplitude is not None
                            and metric_result.target_amplitude_status != "unavailable"
                        ):
                            metrics_fft[chan_idx, freq_idx] = (
                                metric_result.target_amplitude
                            )
                        if metric_result.snr is not None:
                            metrics_snr[chan_idx, freq_idx] = metric_result.snr
                        if metric_result.local_z is not None:
                            metrics_z[chan_idx, freq_idx] = metric_result.local_z
                        if metric_result.bca is not None:
                            metrics_bca[chan_idx, freq_idx] = metric_result.bca
                        spectral_metric_qc_rows.append(
                            {
                                "Source File": source_file_name,
                                "Condition": cond_label_from_keys,
                                "FFT Input Index": data_idx + 1,
                                "Electrode": ordered_electrode_names_for_df[chan_idx],
                                "Eligibility Fingerprint": (
                                    eligibility_fingerprint
                                ),
                                "Oddball Harmonic Order": (
                                    availability.target.oddball_harmonic_order
                                ),
                                "Presentation Harmonic Order": (
                                    availability.target.presentation_harmonic_order
                                    if availability.target.presentation_harmonic_order
                                    is not None
                                    else ""
                                ),
                                "Target Frequency Exact (Hz)": (
                                    f"{availability.target.frequency_hz.numerator}/"
                                    f"{availability.target.frequency_hz.denominator}"
                                ),
                                "Target FFT Bin": availability.target_bin_index,
                                "Noise Candidate FFT Bins": ",".join(
                                    str(value)
                                    for value in metric_result.candidate_bin_indices
                                ),
                                "Noise Retained FFT Bins": ",".join(
                                    str(value)
                                    for value in metric_result.retained_bin_indices
                                ),
                                "Target Amplitude Status": (
                                    metric_result.target_amplitude_status
                                ),
                                "BCA Status": metric_result.bca_status,
                                "SNR Status": metric_result.snr_status,
                                "Local Z Status": metric_result.local_z_status,
                                "Noise Mean (uV)": metric_result.noise_mean,
                                "Noise Population SD (uV)": (
                                    metric_result.noise_population_sd
                                ),
                                "Reason Codes": ";".join(
                                    metric_result.reason_codes
                                ),
                            }
                        )
                _log_export_timing(
                    "target_metrics_loop",
                    target_metrics_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    object_index=data_idx + 1,
                    extra=f"channels={final_num_channels} targets={num_target_freqs}",
                )

                if accum["fft"] is None:
                    accum = {
                        "fft": metrics_fft,
                        "snr": metrics_snr,
                        "z": metrics_z,
                        "bca": metrics_bca,
                    }
                    full_snr_accum = full_snr_matrix
                    full_fft_accum = fft_amplitudes
                else:
                    accum["fft"] += metrics_fft
                    accum["snr"] += metrics_snr
                    accum["z"] += metrics_z
                    accum["bca"] += metrics_bca
                    full_snr_accum += full_snr_matrix
                    full_fft_accum += fft_amplitudes
                valid_data_count += 1
                retained_occurrences.extend(
                    _retained_occurrence_receipts(data_object, data_idx + 1)
                )
            except Exception as e:
                app.log(
                    f"!!! Error post-processing data object {data_idx + 1}: {e}\n{traceback.format_exc()}"
                )
                if isinstance(e, (SpectralEligibilityError, OutputIntegrityError)):
                    export_receipts.append(
                        _blocked_export_receipt(
                            app,
                            pid=pid,
                            condition_label=cond_label_from_keys,
                            path=full_excel_path,
                            stage=(
                                e.stage
                                if isinstance(e, OutputIntegrityError)
                                else "spectral_eligibility"
                            ),
                            reason=str(e),
                            integrity_failure=(
                                e.to_payload()
                                if isinstance(e, OutputIntegrityError)
                                else None
                            ),
                        )
                    )
                    raise
            finally:
                _log_export_timing(
                    "data_object_total",
                    object_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    object_index=data_idx + 1,
                )
                del data_eeg
                gc.collect()

        if valid_data_count > 0 and final_electrode_names_ordered:
            if condition_eligibility is None:
                raise SpectralEligibilityError(
                    "No canonical spectral eligibility result was retained for export."
                )
            dataframe_started = perf_counter()
            avg_metrics = {k: v / valid_data_count for k, v in accum.items()}
            try:
                bca_integrity_receipt = require_finite_computable_bca(
                    avg_metrics["bca"],
                    electrode_names=final_electrode_names_ordered,
                    target_availability=condition_eligibility.targets,
                    recording_id=_run_identity_payload(
                        app,
                        fallback_recording_id=pid,
                    )["recording_id"],
                    condition_label=cond_label_from_keys,
                ).to_payload()
            except OutputIntegrityError as integrity_error:
                export_receipts.append(
                    _blocked_export_receipt(
                        app,
                        pid=pid,
                        condition_label=cond_label_from_keys,
                        path=full_excel_path,
                        stage=integrity_error.stage,
                        reason=str(integrity_error),
                        integrity_failure=integrity_error.to_payload(),
                    )
                )
                app.log(
                    "!!! Technical output integrity failure: "
                    f"{integrity_error}"
                )
                raise
            freq_column_names = _frequency_column_names(target_frequencies)
            full_snr_avg = (
                full_snr_accum / valid_data_count if full_snr_accum is not None else None
            )
            full_fft_avg = (
                full_fft_accum / valid_data_count if full_fft_accum is not None else None
            )
            dataframes_to_save = {
                "FFT Amplitude (uV)": pd.DataFrame(
                    avg_metrics["fft"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
                "SNR": pd.DataFrame(
                    avg_metrics["snr"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
                "Z Score": pd.DataFrame(
                    avg_metrics["z"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
                "BCA (uV)": pd.DataFrame(
                    avg_metrics["bca"],
                    index=final_electrode_names_ordered,
                    columns=freq_column_names,
                ),
            }
            if full_snr_avg is not None and full_snr_frequencies is not None:
                full_snr_dataframe_started = perf_counter()
                max_freq = min(full_snr_max_frequency, float(fft_frequencies[-1]))
                freq_grid = np.arange(0.5, max_freq + 0.01, 0.01)

                interp_snr = np.zeros((full_snr_avg.shape[0], len(freq_grid)))
                for ch_idx in range(full_snr_avg.shape[0]):
                    interp_snr[ch_idx] = np.interp(
                        freq_grid,
                        full_snr_frequencies,
                        full_snr_avg[ch_idx],
                    )

                freq_cols_full = [f"{f:.4f}_Hz" for f in freq_grid]

                dataframes_to_save["FullSNR"] = pd.DataFrame(
                    interp_snr,
                    index=final_electrode_names_ordered,
                    columns=freq_cols_full,
                )
                _log_export_timing(
                    "full_snr_dataframe",
                    full_snr_dataframe_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    path=full_excel_path,
                    extra=f"channels={full_snr_avg.shape[0]} freqs={len(freq_grid)}",
                )
            if full_fft_avg is not None:
                full_fft_df = pd.DataFrame(
                    full_fft_avg,
                    index=final_electrode_names_ordered,
                    columns=_frequency_column_names(fft_frequencies),
                )
                dataframes_to_save["FullFFT Amplitude (uV)"] = full_fft_df
            for df_name_iter in dataframes_to_save:
                dataframes_to_save[df_name_iter].insert(
                    0, "Electrode", dataframes_to_save[df_name_iter].index
                )

            neighbor_columns = [
                "file_name",
                "condition_label",
                "condition_id",
                "repetition_index",
                "channel_or_roi",
                "target",
                "fs",
                "N",
                "T_sec",
                "df_hz",
                "k0",
                "f_bin_hz",
                "crop_mode",
                "n55",
                "first55_samp",
                "last55_samp",
                "N_step",
                "N_mod_step",
                "fallback_reason",
                *[f"amp_m{i}" for i in range(11, 0, -1)],
                *[f"amp_p{i}" for i in range(1, 12)],
                "warning",
            ]
            fft_neighbors_df = pd.DataFrame(fft_neighbors_rows)
            if fft_neighbors_df.empty:
                fft_neighbors_df = pd.DataFrame(columns=neighbor_columns)
            else:
                fft_neighbors_df = fft_neighbors_df.reindex(columns=neighbor_columns)
            spectral_eligibility_df = pd.DataFrame(
                condition_eligibility.to_rows()
            )
            spectral_metric_qc_df = pd.DataFrame(spectral_metric_qc_rows)
            _log_export_timing(
                "dataframes_to_save",
                dataframe_started,
                pid=pid,
                condition=cond_label_from_keys,
                path=full_excel_path,
                extra=(
                    f"sheets={len(dataframes_to_save)} "
                    f"neighbor_rows={len(fft_neighbors_df)} "
                    f"eligibility_rows={len(spectral_eligibility_df)} "
                    f"metric_qc_rows={len(spectral_metric_qc_df)}"
                ),
            )

            try:
                workbook_started = perf_counter()
                condition_repair = condition_interpolation_export_provenance(
                    getattr(app, "settings", {}) or {}, cond_label_from_keys,
                )
                workbook_write_receipt = write_results_workbook(
                    full_excel_path=full_excel_path,
                    dataframes_to_save=dataframes_to_save,
                    fft_neighbors_df=fft_neighbors_df,
                    spectral_eligibility_df=spectral_eligibility_df,
                    spectral_metric_qc_df=spectral_metric_qc_df,
                    timing_sink=export_timing_sink if isinstance(export_timing_sink, list) else None,
                    spectral_metadata={
                        "sampling_frequency_hz": float(sfreq),
                        "fft_sample_count": int(num_times),
                        "frequencies_hz": fft_frequencies.tolist(),
                        "condition_label": cond_label_from_keys,
                        "frequency_protocol": frequency_protocol.to_manifest(),
                        "spectral_eligibility_fingerprint": condition_eligibility.fingerprint,
                        "retained_occurrences": retained_occurrences,
                        "full_fft_units": "uV",
                        "full_snr_units": "ratio",
                        **({"condition_electrode_interpolation": condition_repair} if condition_repair else {}),
                    },
                )
                export_receipts.append(
                    _fingerprinted_export_receipt({
                        "version": RECORDING_CONDITION_EXPORT_RECEIPT_VERSION,
                        "status": "written",
                        **_run_identity_payload(
                            app,
                            fallback_recording_id=pid,
                        ),
                        "condition_label": cond_label_from_keys,
                        "path": str(Path(full_excel_path).resolve()),
                        "protocol_fingerprint": frequency_protocol.fingerprint,
                        "spectral_eligibility_fingerprint": (
                            condition_eligibility.fingerprint
                        ),
                        "expected_data_object_count": len(data_list),
                        "contributing_data_object_count": valid_data_count,
                        "retained_occurrence_count": len(retained_occurrences),
                        "retained_occurrences": retained_occurrences,
                        "finite_integrity": [
                            *source_integrity_receipts,
                            bca_integrity_receipt,
                        ],
                        "workbook_write": workbook_write_receipt,
                        **({"condition_electrode_interpolation": condition_repair} if condition_repair else {}),
                    })
                )
                _log_export_timing(
                    "workbook_write",
                    workbook_started,
                    pid=pid,
                    condition=cond_label_from_keys,
                    path=full_excel_path,
                )
                app.log(f"Successfully saved results: {excel_filename}")
                any_results_saved = True
            except Exception as write_err:
                if not (
                    export_receipts
                    and export_receipts[-1].get("condition_label")
                    == cond_label_from_keys
                    and export_receipts[-1].get("status") == "written"
                ):
                    export_receipts.append(
                        _blocked_export_receipt(
                            app,
                            pid=pid,
                            condition_label=cond_label_from_keys,
                            path=full_excel_path,
                            stage=(
                                write_err.stage
                                if isinstance(write_err, OutputIntegrityError)
                                else "workbook_write"
                            ),
                            reason=str(write_err),
                            integrity_failure=(
                                write_err.to_payload()
                                if isinstance(write_err, OutputIntegrityError)
                                else None
                            ),
                        )
                    )
                app.log(
                    f"!!! Error writing results file {full_excel_path}: {write_err}\n{traceback.format_exc()}"
                )
                raise
        else:
            app.log(
                f"No valid data to save for '{cond_label_from_keys}' (PID: {pid}). No results file generated."
            )
            export_receipts.append(
                _blocked_export_receipt(
                    app,
                    pid=pid,
                    condition_label=cond_label_from_keys,
                    path=full_excel_path,
                    stage="condition_input",
                    reason="No valid retained data object reached workbook export.",
                )
            )
        _log_export_timing(
            "condition_total",
            condition_started,
            pid=pid,
            condition=cond_label_from_keys,
            path=full_excel_path,
        )

    if not any_results_saved:
        app.log("Warning: Post-processing completed, but no Excel files were saved.")
    del current_epochs_data_source
    gc.collect()
    _log_export_timing("post_process_total", post_started, pid=pid, path=parent_folder)
    app.log("--- Post-processing finished. ---")

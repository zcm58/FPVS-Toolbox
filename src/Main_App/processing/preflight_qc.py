"""Preprocessing preflight QC scanning helpers."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
import gc
import logging
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

import mne
import numpy as np

from Main_App.io import load_utils
from Main_App.io.load_utils import BDF_RECORDING_NOT_STARTED_REASON, BdfPreflightInfo
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.preflight_qc_cache import (
    load_preflight_qc_cache,
    save_preflight_qc_cache,
)
from Main_App.processing.preflight_qc_plan import (
    PREFLIGHT_QC_BLOCK_DURATION_S,
    PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES,
    PREFLIGHT_QC_MAX_IO_READERS,
    PREFLIGHT_QC_MAX_SPECTRAL_WORKERS,
    PREFLIGHT_QC_MAX_WORKERS,
    PREFLIGHT_QC_METHOD_NAME,
    PREFLIGHT_QC_METHOD_VERSION,
    ConditionQcSpan,
    plan_preflight_qc_events,
    resolve_preflight_spectral_bounds,
)
from Main_App.processing.raw_channel_qc import (
    CONDITION_RAW_CHANNEL_QC_METHOD_VERSION,
    RAW_CHANNEL_QC_EXCLUSION_REASON,
    SCALP_CHANNELS,
    ConditionRawChannelQCBlock,
    ConditionRawChannelQCCancelled,
    combine_condition_raw_channel_qc_v2,
    evaluate_condition_raw_channel_qc_v2,
    evaluate_raw_channel_qc,
)
from Main_App.processing.raw_spectral_qc import (
    CONDITION_SPECTRAL_QC_METHOD_VERSION,
    ConditionSpectralQCCancelled,
    ConditionSpectralQCResult,
    ConditionSpectralQCThresholds,
    RawSpectralQCResult,
    evaluate_condition_spectral_qc_v2,
    evaluate_raw_spectral_qc,
)
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]
DetailProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class HeaderOnlyPreflight:
    """A BDF file that appears to contain only the BioSemi header."""

    path: Path
    participant_id: str
    info: BdfPreflightInfo
    group_id: str | None = None


@dataclass(frozen=True)
class PreflightQcFileResult:
    """Pre-processing QC result for one raw file."""

    path: Path
    participant_id: str
    load_error: str | None
    raw_channel_qc: Mapping[str, object] | None
    raw_spectral_qc: Mapping[str, object] | None
    group_id: str | None = None
    condition_qc: Mapping[str, object] | None = None

    @property
    def auto_removed_electrodes(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("channels_to_interpolate")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def high_amplitude_channels(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("high_amplitude_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def rare_burst_channels(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("rare_burst_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def spatial_outlier_channels(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("spatial_outlier_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def warning_rules(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("warning_rules")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def raw_qc_excluded(self) -> bool:
        payload = self.raw_channel_qc or {}
        return bool(payload.get("excluded"))

    @property
    def raw_qc_message(self) -> str:
        payload = self.raw_channel_qc or {}
        return str(payload.get("message") or "").strip()

    @property
    def raw_spectral_widespread(self) -> bool:
        payload = self.raw_spectral_qc or {}
        return bool(payload.get("widespread"))

    @property
    def raw_spectral_message(self) -> str:
        payload = self.raw_spectral_qc or {}
        return str(payload.get("message") or "").strip()

    @property
    def raw_spectral_flagged_channels(self) -> tuple[str, ...]:
        payload = self.raw_spectral_qc or {}
        values = payload.get("flagged_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())


@dataclass(frozen=True)
class PreflightQcScan:
    """Full preflight scan output for GUI review."""

    results: tuple[PreflightQcFileResult, ...]
    cancelled: bool = False

    @property
    def suggested_removed_electrodes(self) -> dict[str, list[str]]:
        suggestions: dict[str, list[str]] = {}
        for result in self.results:
            channels = list(
                dict.fromkeys(
                    [
                        *result.auto_removed_electrodes,
                        *result.high_amplitude_channels,
                        *result.rare_burst_channels,
                    ]
                )
            )
            if not channels:
                continue
            suggestions[result.participant_id] = channels
        return suggestions

    @property
    def hard_exclusion_candidates(self) -> tuple[PreflightQcFileResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.raw_qc_excluded or result.raw_spectral_widespread
        )

    @property
    def suspicious_results(self) -> tuple[PreflightQcFileResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.load_error
            or result.warning_rules
            or result.high_amplitude_channels
            or result.rare_burst_channels
            or result.spatial_outlier_channels
            or (
                result.raw_spectral_flagged_channels
                and not result.raw_spectral_widespread
            )
        )


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except (OSError, RuntimeError, ValueError):
        return str(path).casefold()


def scan_recording_not_started_files(
    raw_file_infos: Sequence[RawFileInfo],
) -> tuple[HeaderOnlyPreflight, ...]:
    """Return files whose BDF header says no recording data were written."""

    flagged: list[HeaderOnlyPreflight] = []
    for info in raw_file_infos:
        preflight = load_utils.inspect_bdf_header(info.path)
        if not preflight or not preflight.recording_not_started:
            continue
        flagged.append(
            HeaderOnlyPreflight(
                path=Path(info.path),
                participant_id=str(info.subject_id),
                info=preflight,
                group_id=str(info.group).strip() if info.group else None,
            )
        )
    return tuple(flagged)


def _auto_qc_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(settings)
    payload["auto_detect_removed_electrodes"] = True
    payload["removed_electrode_detection_mode"] = REMOVED_ELECTRODE_DETECTION_MODE_AUTO
    payload["_fpvs_manual_removed_electrodes"] = []
    return payload


class _LogShim:
    def log(self, message: str, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        logger.debug("preflight_qc_loader: %s", message)


def _load_raw_for_preflight(
    file_path: Path,
    settings: Mapping[str, Any],
) -> Any:
    ref_ch1, ref_ch2 = _configured_ref_pair(settings)
    return load_utils.load_eeg_file(
        _LogShim(),
        str(file_path),
        ref_pair=(str(ref_ch1), str(ref_ch2)),
        first_n_channels=64,
    )


def _raw_channel_payload(result: Any) -> dict[str, object]:
    payload = result.to_payload()
    payload["excluded"] = bool(result.excluded)
    payload["reason"] = result.reason or RAW_CHANNEL_QC_EXCLUSION_REASON
    payload["message"] = result.message
    return payload


class _PreflightQcCancelled(RuntimeError):
    """Internal cooperative-cancellation signal for one participant scan."""


def _configured_ref_pair(settings: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(
            settings.get("ref_channel1")
            or settings.get("ref_chan1")
            or settings.get("ref_ch1")
            or "EXG1"
        ),
        str(
            settings.get("ref_channel2")
            or settings.get("ref_chan2")
            or settings.get("ref_ch2")
            or "EXG2"
        ),
    )


def _configured_stim_channel(settings: Mapping[str, Any]) -> str:
    return str(settings.get("stim_channel") or settings.get("stim") or "Status")


def _find_preflight_events(raw: Any, *, stim_channel: str) -> tuple[np.ndarray, str]:
    try:
        events = mne.find_events(
            raw,
            stim_channel=stim_channel,
            shortest_event=1,
            verbose=False,
        )
        source = "stim"
    except (RuntimeError, ValueError):
        events, _event_ids = mne.events_from_annotations(raw, verbose=False)
        source = "annotations"
    events_array = np.asarray(events, dtype=np.int64)
    if events_array.size == 0:
        raise RuntimeError(
            f"No events found for preflight QC (source={source!r}, stim={stim_channel!r})."
        )
    return events_array, source


def _preflight_scalp_picks(
    raw: Any,
    *,
    settings: Mapping[str, Any],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    stim_channel = _configured_stim_channel(settings)
    ref_channels = set(_configured_ref_pair(settings))
    picks = tuple(
        index
        for index, channel in enumerate(getattr(raw, "ch_names", ()))
        if str(channel) in SCALP_CHANNELS
        and str(channel) != stim_channel
        and str(channel) not in ref_channels
    )
    names = tuple(str(raw.ch_names[index]) for index in picks)
    if not picks:
        raise RuntimeError("Preflight QC v2 found no scalp EEG channels.")
    return picks, names


def _read_condition_data(
    raw: Any,
    *,
    picks: Sequence[int],
    start: int,
    stop: int,
    io_semaphore: threading.BoundedSemaphore,
) -> np.ndarray:
    with io_semaphore:
        try:
            data = raw.get_data(
                picks=list(picks),
                start=int(start),
                stop=int(stop),
                verbose=False,
            )
        except TypeError:
            data = raw.get_data(
                picks=list(picks),
                start=int(start),
                stop=int(stop),
            )
    result = np.asarray(data, dtype=np.float64)
    expected_samples = int(stop) - int(start)
    if result.ndim != 2 or result.shape != (len(picks), expected_samples):
        raise RuntimeError(
            "Lazy BDF condition read returned an unexpected shape: "
            f"expected={(len(picks), expected_samples)}, actual={result.shape}."
        )
    return result


@contextmanager
def _condition_data_buffer(
    raw: Any,
    *,
    picks: Sequence[int],
    start: int,
    stop: int,
    sfreq: float,
    io_semaphore: threading.BoundedSemaphore,
    should_cancel: CancelCallback | None = None,
    progress_detail: DetailProgressCallback | None = None,
    detail_prefix: str = "",
) -> Iterator[tuple[np.ndarray, bool]]:
    """Yield one condition without ever materializing the full recording.

    Ordinary condition intervals remain in RAM and are read once. Unusually
    long intervals are copied, in the same ten-second chunks used by the
    time-domain QC, into a temporary condition-only float64 memmap. Both paths
    expose the same array values to the QC math; the disk-backed path only
    changes where the condition buffer lives.
    """

    sample_count = int(stop) - int(start)
    if sample_count <= 0:
        raise ValueError("Condition QC requires a positive sample interval.")
    shape = (len(picks), sample_count)
    required_bytes = int(np.prod(shape, dtype=np.int64)) * np.dtype(np.float64).itemsize
    if required_bytes <= PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES:
        yield (
            _read_condition_data(
                raw,
                picks=picks,
                start=start,
                stop=stop,
                io_semaphore=io_semaphore,
            ),
            False,
        )
        return

    chunk_samples = max(1, int(round(PREFLIGHT_QC_BLOCK_DURATION_S * sfreq)))
    chunk_count = (sample_count + chunk_samples - 1) // chunk_samples
    with tempfile.TemporaryDirectory(prefix="fpvs-preflight-qc-") as temp_dir:
        buffer_path = Path(temp_dir) / "condition-float64.dat"
        condition_buffer = np.memmap(
            buffer_path,
            dtype=np.float64,
            mode="w+",
            shape=shape,
        )
        try:
            for chunk_index, local_start in enumerate(
                range(0, sample_count, chunk_samples),
                start=1,
            ):
                if should_cancel is not None and should_cancel():
                    raise _PreflightQcCancelled()
                local_stop = min(sample_count, local_start + chunk_samples)
                if progress_detail:
                    prefix = f"{detail_prefix} · " if detail_prefix else ""
                    progress_detail(
                        f"{prefix}reading condition block "
                        f"{chunk_index}/{chunk_count} (disk-buffered)"
                    )
                chunk = _read_condition_data(
                    raw,
                    picks=picks,
                    start=int(start) + local_start,
                    stop=int(start) + local_stop,
                    io_semaphore=io_semaphore,
                )
                condition_buffer[:, local_start:local_stop] = chunk
                del chunk
            condition_buffer.flush()
            yield condition_buffer, True
        finally:
            try:
                condition_buffer.flush()
            finally:
                mmap_handle = getattr(condition_buffer, "_mmap", None)
                if mmap_handle is not None:
                    mmap_handle.close()


def _condition_blocks(
    data: np.ndarray,
    *,
    span: ConditionQcSpan,
    sfreq: float,
) -> tuple[ConditionRawChannelQCBlock, ...]:
    block_samples = max(1, int(round(PREFLIGHT_QC_BLOCK_DURATION_S * sfreq)))
    blocks: list[ConditionRawChannelQCBlock] = []
    for local_start in range(0, data.shape[1], block_samples):
        local_stop = min(data.shape[1], local_start + block_samples)
        absolute_start = int(span.time_start_sample) + local_start
        absolute_stop = int(span.time_start_sample) + local_stop
        blocks.append(
            ConditionRawChannelQCBlock(
                condition_id=span.condition_label,
                occurrence=int(span.repetition_index),
                start_sample=absolute_start,
                stop_sample=absolute_stop,
                data=data[:, local_start:local_stop],
                is_final=local_stop == data.shape[1],
            )
        )
    return tuple(blocks)


def _preflight_cache_settings(settings: Mapping[str, Any]) -> dict[str, object]:
    analysis = settings.get("analysis")
    analysis_payload = dict(analysis) if isinstance(analysis, Mapping) else {}
    keys = (
        "stim_channel",
        "ref_channel1",
        "ref_channel2",
        "max_bad_chans",
        "max_bad_channels",
        "max_bad_channels_alert_thresh",
        "removed_electrode_detection_mode",
        "auto_detect_removed_electrodes",
        "high_pass",
        "low_pass",
        "downsample",
        "downsample_rate",
        "epoch_end",
        "base_freq",
        "oddball_freq",
        "line_noise_filter_enabled",
        "line_noise_frequency_hz",
    )
    payload: dict[str, object] = {
        key: settings.get(key)
        for key in keys
        if settings.get(key) is not None
    }
    payload["analysis"] = analysis_payload
    payload["channel_subset_first_n"] = 64
    payload["reference_pair"] = list(_configured_ref_pair(settings))
    return payload


def _preflight_cache_method() -> dict[str, object]:
    return {
        "name": PREFLIGHT_QC_METHOD_NAME,
        "version": PREFLIGHT_QC_METHOD_VERSION,
        "raw_channel_method": CONDITION_RAW_CHANNEL_QC_METHOD_VERSION,
        "raw_spectral_method": CONDITION_SPECTRAL_QC_METHOD_VERSION,
        "condition_block_duration_s": PREFLIGHT_QC_BLOCK_DURATION_S,
        "numpy_version": str(np.__version__),
        "mne_version": str(mne.__version__),
    }


def _preflight_file_identity(file_path: Path) -> dict[str, object]:
    stat = file_path.stat()
    return {
        "resolved_path": str(file_path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _cached_preflight_result(
    cached: Mapping[str, Any],
    *,
    file_path: Path,
    participant_id: str,
    group_id: str | None,
    timings_ms: Mapping[str, float],
) -> PreflightQcFileResult | None:
    raw_channel_qc = cached.get("raw_channel_qc")
    raw_spectral_qc = cached.get("raw_spectral_qc")
    condition_qc = cached.get("condition_qc")
    if not isinstance(raw_channel_qc, Mapping) or not isinstance(
        raw_spectral_qc, Mapping
    ):
        return None
    condition_payload = dict(condition_qc) if isinstance(condition_qc, Mapping) else {}
    condition_payload["cache_status"] = "hit"
    condition_payload["timings_ms"] = dict(timings_ms)
    return PreflightQcFileResult(
        path=file_path,
        participant_id=participant_id,
        load_error=None,
        raw_channel_qc=dict(raw_channel_qc),
        raw_spectral_qc=dict(raw_spectral_qc),
        group_id=group_id,
        condition_qc=condition_payload,
    )


def _aggregate_condition_spectral_qc(
    results: Sequence[tuple[ConditionQcSpan, ConditionSpectralQCResult]],
    *,
    filename: str,
    skipped_spans: Sequence[ConditionQcSpan],
) -> dict[str, object]:
    flagged_channels: set[str] = set()
    unexpected_peaks: list[tuple[ConditionQcSpan, Any]] = []
    observed_widespread = False
    condition_payloads: list[dict[str, object]] = []
    for span, result in results:
        payload = result.to_payload()
        payload["condition_label"] = span.condition_label
        payload["condition_id"] = span.condition_id
        payload["repetition_index"] = span.repetition_index
        payload["start_sample"] = span.spectral_start_sample
        payload["stop_sample"] = span.spectral_stop_sample
        condition_payloads.append(payload)
        for peak in result.unexpected_off_harmonic_flags:
            flagged_channels.update(peak.channels)
            unexpected_peaks.append((span, peak))
            observed_widespread = observed_widespread or bool(peak.widespread)

    strongest = max(
        unexpected_peaks,
        key=lambda item: item[1].max_amplitude_uv,
        default=None,
    )
    if unexpected_peaks:
        message = (
            f"Condition-aware spectral QC flagged {len(unexpected_peaks)} unexpected "
            f"off-harmonic peak(s) in {filename} for review."
        )
    elif results:
        message = (
            f"Condition-aware spectral QC passed for {filename}: no unexpected "
            "off-harmonic condition peaks require review."
        )
    else:
        message = (
            f"Condition-aware spectral QC skipped for {filename}: no valid locked "
            "on-bin condition span was available."
        )

    return {
        "method_version": CONDITION_SPECTRAL_QC_METHOD_VERSION,
        "review_only": True,
        "evaluated": bool(results),
        # The compatibility key remains false so v2 review findings cannot enter
        # the legacy hard-exclusion confirmation path without calibration.
        "widespread": False,
        "observed_widespread_review": observed_widespread,
        "message": message,
        "n_channels": max((result.n_channels for _span, result in results), default=0),
        "flagged_channels": sorted(flagged_channels),
        "peak_frequency_hz": (
            float(strongest[1].frequency_hz) if strongest is not None else None
        ),
        "max_amplitude_uv": (
            float(strongest[1].max_amplitude_uv) if strongest is not None else 0.0
        ),
        "max_local_ratio": (
            float(strongest[1].max_local_ratio) if strongest is not None else 0.0
        ),
        "condition_results": condition_payloads,
        "skipped_condition_spans": [
            {
                "condition_label": span.condition_label,
                "condition_id": span.condition_id,
                "repetition_index": span.repetition_index,
                "reason": span.spectral_fallback_reason or "no_locked_onbin_span",
            }
            for span in skipped_spans
        ],
    }


def _preflight_worker_count(total: int, max_workers: int | None) -> int:
    if total <= 1:
        return 1
    try:
        requested = int(max_workers or 1)
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(total, requested, PREFLIGHT_QC_MAX_WORKERS))


def _scan_one_preflight_file_v2(
    info: RawFileInfo,
    qc_settings: Mapping[str, Any],
    *,
    project_root: Path,
    event_map: Mapping[str, int],
    io_semaphore: threading.BoundedSemaphore,
    spectral_semaphore: threading.BoundedSemaphore,
    progress_detail: DetailProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> PreflightQcFileResult | None:
    file_path = Path(info.path)
    participant_id = str(info.subject_id)
    group_id = str(info.group).strip() if info.group else None
    timings_ms: dict[str, float] = {}

    def _cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    def _record_timing(stage: str, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        timings_ms[stage] = elapsed_ms
        logger.info(
            "preflight_qc_timing file=%s participant_id=%s stage=%s elapsed_ms=%.3f",
            file_path.name,
            participant_id,
            stage,
            elapsed_ms,
        )

    if _cancelled():
        raise _PreflightQcCancelled()

    header_started = time.perf_counter()
    with io_semaphore:
        preflight = load_utils.inspect_bdf_header(file_path)
    _record_timing("header", header_started)
    if preflight and preflight.recording_not_started:
        return None

    if progress_detail:
        progress_detail(f"Planning {file_path.name} · reading Status events")

    raw_context = load_utils.open_preflight_eeg_file(
        _LogShim(),
        str(file_path),
        ref_pair=_configured_ref_pair(qc_settings),
        first_n_channels=64,
        stim_channel=_configured_stim_channel(qc_settings),
    )
    raw = None
    context_entered = False
    try:
        open_started = time.perf_counter()
        with io_semaphore:
            raw = raw_context.__enter__()
            context_entered = True
        _record_timing("lazy_open", open_started)
        if raw is None:
            raise RuntimeError("BDF lazy loader returned no raw data.")
        if _cancelled():
            raise _PreflightQcCancelled()

        event_started = time.perf_counter()
        with io_semaphore:
            events, event_source = _find_preflight_events(
                raw,
                stim_channel=_configured_stim_channel(qc_settings),
            )
        event_plan = plan_preflight_qc_events(
            events=events,
            event_map=event_map,
            sfreq=float(raw.info["sfreq"]),
            n_times=int(raw.n_times),
            epoch_end_s=float(qc_settings.get("epoch_end", 125.0)),
        )
        _record_timing("events_and_plan", event_started)
        if not event_plan.spans:
            raise RuntimeError("Preflight QC v2 planned no relevant condition intervals.")

        file_identity = _preflight_file_identity(file_path)
        cache_settings = _preflight_cache_settings(qc_settings)
        cache_method = _preflight_cache_method()
        event_plan_payload = event_plan.to_payload()
        cache_started = time.perf_counter()
        cached = load_preflight_qc_cache(
            project_root,
            file_identity=file_identity,
            settings=cache_settings,
            method=cache_method,
            event_plan=event_plan_payload,
        )
        _record_timing("cache_lookup", cache_started)
        if cached is not None:
            cached_result = _cached_preflight_result(
                cached,
                file_path=file_path,
                participant_id=participant_id,
                group_id=group_id,
                timings_ms=timings_ms,
            )
            if cached_result is not None:
                if progress_detail:
                    progress_detail(f"Cached {file_path.name} · condition QC reused")
                logger.info(
                    "preflight_qc_cache_hit file=%s participant_id=%s conditions=%d",
                    file_path.name,
                    participant_id,
                    len(event_plan.spans),
                )
                return cached_result

        picks, channel_names = _preflight_scalp_picks(raw, settings=qc_settings)
        sfreq = float(raw.info["sfreq"])
        lower_hz, upper_hz = resolve_preflight_spectral_bounds(
            qc_settings,
            source_sfreq=sfreq,
        )
        spectral_thresholds = ConditionSpectralQCThresholds(
            min_frequency_hz=max(
                ConditionSpectralQCThresholds.min_frequency_hz,
                float(lower_hz),
            )
        )

        channel_results = []
        spectral_results: list[
            tuple[ConditionQcSpan, ConditionSpectralQCResult]
        ] = []
        skipped_spectral_spans: list[ConditionQcSpan] = []
        samples_read = 0
        disk_buffered_condition_count = 0
        conditions_total = len(event_plan.spans)
        qc_started = time.perf_counter()
        for condition_index, span in enumerate(event_plan.spans, start=1):
            if _cancelled():
                raise _PreflightQcCancelled()
            detail_prefix = (
                f"Scanning {file_path.name} · {span.condition_label} "
                f"{condition_index}/{conditions_total}"
            )
            if progress_detail:
                progress_detail(f"{detail_prefix} · reading condition samples")

            with _condition_data_buffer(
                raw,
                picks=picks,
                start=span.time_start_sample,
                stop=span.time_stop_sample,
                sfreq=sfreq,
                io_semaphore=io_semaphore,
                should_cancel=should_cancel,
                progress_detail=progress_detail,
                detail_prefix=detail_prefix,
            ) as (condition_data, disk_buffered):
                blocks = None
                spectral_data = None
                try:
                    if disk_buffered:
                        disk_buffered_condition_count += 1
                    samples_read += int(condition_data.shape[1])
                    blocks = _condition_blocks(condition_data, span=span, sfreq=sfreq)
                    if progress_detail:
                        progress_detail(
                            f"{detail_prefix} · checking "
                            f"{len(blocks)} time-domain block(s)"
                        )
                    try:
                        channel_results.append(
                            evaluate_condition_raw_channel_qc_v2(
                                blocks,
                                channel_names,
                                qc_settings,
                                filename=file_path.name,
                                sfreq=sfreq,
                                block_duration_s=PREFLIGHT_QC_BLOCK_DURATION_S,
                                should_cancel=should_cancel,
                            )
                        )
                    except ConditionRawChannelQCCancelled as exc:
                        raise _PreflightQcCancelled() from exc

                    if (
                        span.spectral_start_sample is None
                        or span.spectral_stop_sample is None
                    ):
                        skipped_spectral_spans.append(span)
                    else:
                        relative_start = (
                            int(span.spectral_start_sample)
                            - int(span.time_start_sample)
                        )
                        relative_stop = (
                            int(span.spectral_stop_sample)
                            - int(span.time_start_sample)
                        )
                        spectral_data = condition_data[
                            :,
                            relative_start:relative_stop,
                        ]
                        if spectral_data.shape[1] != span.spectral_sample_count:
                            raise RuntimeError(
                                "Condition spectral crop did not match the shared planner: "
                                f"expected={span.spectral_sample_count}, "
                                f"actual={spectral_data.shape[1]}, "
                                f"condition={span.condition_label!r}."
                            )
                        if progress_detail:
                            progress_detail(
                                f"{detail_prefix} · checking exact on-bin spectrum"
                            )
                        try:
                            with spectral_semaphore:
                                spectral_result = evaluate_condition_spectral_qc_v2(
                                    spectral_data,
                                    sfreq=sfreq,
                                    settings=qc_settings,
                                    effective_upper_frequency_hz=upper_hz,
                                    channel_names=channel_names,
                                    condition_label=(
                                        f"{span.condition_label} repetition "
                                        f"{span.repetition_index + 1}"
                                    ),
                                    thresholds=spectral_thresholds,
                                    should_cancel=should_cancel,
                                )
                        except ConditionSpectralQCCancelled as exc:
                            raise _PreflightQcCancelled() from exc
                        spectral_results.append(
                            (
                                span,
                                spectral_result,
                            )
                        )
                finally:
                    spectral_data = None
                    blocks = None
                    del condition_data
        _record_timing("condition_qc", qc_started)
        if _cancelled():
            raise _PreflightQcCancelled()

        channel_result = combine_condition_raw_channel_qc_v2(
            channel_results,
            filename=file_path.name,
        )
        raw_channel_payload = channel_result.to_payload()
        raw_spectral_payload = _aggregate_condition_spectral_qc(
            spectral_results,
            filename=file_path.name,
            skipped_spans=skipped_spectral_spans,
        )
        condition_qc_payload: dict[str, object] = {
            "method_name": PREFLIGHT_QC_METHOD_NAME,
            "method_version": PREFLIGHT_QC_METHOD_VERSION,
            "review_only": True,
            "cache_status": "miss",
            "event_source": event_source,
            "event_plan": event_plan_payload,
            "condition_count": len(event_plan.spans),
            "samples_read_per_channel": samples_read,
            "recording_samples_per_channel": int(raw.n_times),
            "disk_buffered_condition_count": disk_buffered_condition_count,
            "spectral_lower_frequency_hz": lower_hz,
            "spectral_upper_frequency_hz": upper_hz,
            "timings_ms": dict(timings_ms),
            "hard_exclusion_policy": (
                "review_only_in_preflight_v2; established hard rules remain "
                "unchanged in the normal processing runner"
            ),
        }
        result = PreflightQcFileResult(
            path=file_path,
            participant_id=participant_id,
            load_error=None,
            raw_channel_qc=raw_channel_payload,
            raw_spectral_qc=raw_spectral_payload,
            group_id=group_id,
            condition_qc=condition_qc_payload,
        )

        if _cancelled():
            raise _PreflightQcCancelled()
        save_started = time.perf_counter()
        try:
            save_preflight_qc_cache(
                project_root,
                file_identity=file_identity,
                settings=cache_settings,
                method=cache_method,
                event_plan=event_plan_payload,
                result={
                    "raw_channel_qc": raw_channel_payload,
                    "raw_spectral_qc": raw_spectral_payload,
                    "condition_qc": condition_qc_payload,
                },
            )
        except (OSError, TypeError, ValueError):
            logger.exception(
                "preflight_qc_cache_save_failed file=%s participant_id=%s",
                file_path,
                participant_id,
            )
        _record_timing("cache_save", save_started)
        return result
    finally:
        if context_entered:
            close_started = time.perf_counter()
            with io_semaphore:
                raw_context.__exit__(None, None, None)
            _record_timing("lazy_close", close_started)


def _scan_one_preflight_file(
    info: RawFileInfo,
    qc_settings: Mapping[str, Any],
    *,
    project_root: Path | None = None,
    event_map: Mapping[str, int] | None = None,
    io_semaphore: threading.BoundedSemaphore | None = None,
    spectral_semaphore: threading.BoundedSemaphore | None = None,
    progress_detail: DetailProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> PreflightQcFileResult | None:
    file_path = Path(info.path)
    participant_id = str(info.subject_id)
    group_id = str(info.group).strip() if info.group else None
    if project_root is not None and event_map:
        try:
            return _scan_one_preflight_file_v2(
                info,
                qc_settings,
                project_root=Path(project_root),
                event_map=event_map,
                io_semaphore=(
                    io_semaphore
                    if io_semaphore is not None
                    else threading.BoundedSemaphore(PREFLIGHT_QC_MAX_IO_READERS)
                ),
                spectral_semaphore=(
                    spectral_semaphore
                    if spectral_semaphore is not None
                    else threading.BoundedSemaphore(
                        PREFLIGHT_QC_MAX_SPECTRAL_WORKERS
                    )
                ),
                progress_detail=progress_detail,
                should_cancel=should_cancel,
            )
        except _PreflightQcCancelled:
            raise
        except Exception as exc:
            logger.exception(
                "Condition-aware preflight QC failed for %s",
                file_path,
                extra={"participant_id": participant_id, "group_id": group_id},
            )
            return PreflightQcFileResult(
                path=file_path,
                participant_id=participant_id,
                load_error=str(exc),
                raw_channel_qc=None,
                raw_spectral_qc=None,
                group_id=group_id,
                condition_qc={
                    "method_name": PREFLIGHT_QC_METHOD_NAME,
                    "method_version": PREFLIGHT_QC_METHOD_VERSION,
                    "cache_status": "error",
                },
            )

    raw = None
    try:
        preflight = load_utils.inspect_bdf_header(file_path)
        if preflight and preflight.recording_not_started:
            return None
        raw = _load_raw_for_preflight(file_path, qc_settings)
        if raw is None:
            raise RuntimeError("BDF loader returned no raw data.")
        raw_result = evaluate_raw_channel_qc(
            raw,
            qc_settings,
            filename=file_path.name,
        )
        spectral_result: RawSpectralQCResult = evaluate_raw_spectral_qc(
            raw,
            qc_settings,
            filename=file_path.name,
        )
        return PreflightQcFileResult(
            path=file_path,
            participant_id=participant_id,
            load_error=None,
            raw_channel_qc=_raw_channel_payload(raw_result),
            raw_spectral_qc=spectral_result.to_payload(),
            group_id=group_id,
        )
    except Exception as exc:
        logger.exception(
            "Preflight QC failed for %s",
            file_path,
            extra={"participant_id": participant_id, "group_id": group_id},
        )
        return PreflightQcFileResult(
            path=file_path,
            participant_id=participant_id,
            load_error=str(exc),
            raw_channel_qc=None,
            raw_spectral_qc=None,
            group_id=group_id,
        )
    finally:
        raw = None
        gc.collect()


def _ordered_results(
    indexed_results: Mapping[int, PreflightQcFileResult | None],
) -> tuple[PreflightQcFileResult, ...]:
    return tuple(
        result
        for index, result in sorted(indexed_results.items())
        if result is not None
    )


def _scan_preprocessing_qc_serial(
    pending_infos: Sequence[RawFileInfo],
    qc_settings: Mapping[str, Any],
    *,
    project_root: Path | None,
    event_map: Mapping[str, int] | None,
    io_semaphore: threading.BoundedSemaphore,
    spectral_semaphore: threading.BoundedSemaphore,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> PreflightQcScan:
    total = len(pending_infos)
    indexed_results: dict[int, PreflightQcFileResult | None] = {}
    for index, info in enumerate(pending_infos, start=1):
        if should_cancel and should_cancel():
            return PreflightQcScan(
                results=_ordered_results(indexed_results),
                cancelled=True,
            )
        file_path = Path(info.path)
        if progress:
            progress(f"Planning {file_path.name}", index - 1, total)
        try:
            indexed_results[index] = _scan_one_preflight_file(
                info,
                qc_settings,
                project_root=project_root,
                event_map=event_map,
                io_semaphore=io_semaphore,
                spectral_semaphore=spectral_semaphore,
                progress_detail=(
                    (lambda message: progress(message, index - 1, total))
                    if progress
                    else None
                ),
                should_cancel=should_cancel,
            )
        except _PreflightQcCancelled:
            return PreflightQcScan(
                results=_ordered_results(indexed_results),
                cancelled=True,
            )
        if progress:
            progress(f"Finished {file_path.name}", index, total)
    return PreflightQcScan(results=_ordered_results(indexed_results), cancelled=False)


def _scan_preprocessing_qc_parallel(
    pending_infos: Sequence[RawFileInfo],
    qc_settings: Mapping[str, Any],
    *,
    max_workers: int,
    project_root: Path | None,
    event_map: Mapping[str, int] | None,
    io_semaphore: threading.BoundedSemaphore,
    spectral_semaphore: threading.BoundedSemaphore,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> PreflightQcScan:
    total = len(pending_infos)
    submitted = 0
    completed = 0
    indexed_results: dict[int, PreflightQcFileResult | None] = {}
    futures: dict[Future[PreflightQcFileResult | None], tuple[int, RawFileInfo]] = {}

    def _submit_next(executor: ThreadPoolExecutor) -> None:
        nonlocal submitted
        while submitted < total and len(futures) < max_workers:
            if should_cancel and should_cancel():
                return
            index = submitted + 1
            info = pending_infos[submitted]
            submitted += 1
            file_path = Path(info.path)
            if progress:
                progress(f"Planning {file_path.name}", completed, total)
            futures[
                executor.submit(
                    _scan_one_preflight_file,
                    info,
                    qc_settings,
                    project_root=project_root,
                    event_map=event_map,
                    io_semaphore=io_semaphore,
                    spectral_semaphore=spectral_semaphore,
                    progress_detail=(
                        (lambda message: progress(message, completed, total))
                        if progress
                        else None
                    ),
                    should_cancel=should_cancel,
                )
            ] = (
                index,
                info,
            )

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="fpvs_preflight_qc",
    ) as executor:
        _submit_next(executor)
        while futures:
            if should_cancel and should_cancel():
                for future in futures:
                    future.cancel()
                return PreflightQcScan(
                    results=_ordered_results(indexed_results),
                    cancelled=True,
                )

            done, _pending = wait(
                futures,
                timeout=0.1,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                continue

            for future in done:
                index, info = futures.pop(future)
                file_path = Path(info.path)
                if not future.cancelled():
                    try:
                        indexed_results[index] = future.result()
                    except _PreflightQcCancelled:
                        for pending_future in futures:
                            pending_future.cancel()
                        return PreflightQcScan(
                            results=_ordered_results(indexed_results),
                            cancelled=True,
                        )
                completed += 1
                if progress:
                    progress(f"Finished {file_path.name}", completed, total)
            _submit_next(executor)

    return PreflightQcScan(results=_ordered_results(indexed_results), cancelled=False)


def scan_preprocessing_qc(
    raw_file_infos: Sequence[RawFileInfo],
    settings: Mapping[str, Any],
    *,
    skip_paths: Sequence[Path] = (),
    max_workers: int | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    project_root: Path | None = None,
    event_map: Mapping[str, int] | None = None,
) -> PreflightQcScan:
    """Run deterministic preflight QC, using condition-aware v2 when scoped.

    The v2 path is opt-in and requires both an explicit project root and event
    map. Existing callers without either input retain the legacy scan behavior.
    """

    skip_keys = {_path_key(Path(path)) for path in skip_paths}
    pending_infos = [
        info for info in raw_file_infos if _path_key(Path(info.path)) not in skip_keys
    ]
    total = len(pending_infos)
    qc_settings = _auto_qc_settings(settings)
    resolved_event_map = (
        {str(label): int(code) for label, code in event_map.items()}
        if event_map
        else None
    )
    resolved_project_root = Path(project_root) if project_root is not None else None
    io_semaphore = threading.BoundedSemaphore(PREFLIGHT_QC_MAX_IO_READERS)
    spectral_semaphore = threading.BoundedSemaphore(
        PREFLIGHT_QC_MAX_SPECTRAL_WORKERS
    )
    worker_count = _preflight_worker_count(total, max_workers)
    if worker_count <= 1:
        return _scan_preprocessing_qc_serial(
            pending_infos,
            qc_settings,
            project_root=resolved_project_root,
            event_map=resolved_event_map,
            io_semaphore=io_semaphore,
            spectral_semaphore=spectral_semaphore,
            progress=progress,
            should_cancel=should_cancel,
        )
    return _scan_preprocessing_qc_parallel(
        pending_infos,
        qc_settings,
        max_workers=worker_count,
        project_root=resolved_project_root,
        event_map=resolved_event_map,
        io_semaphore=io_semaphore,
        spectral_semaphore=spectral_semaphore,
        progress=progress,
        should_cancel=should_cancel,
    )


__all__ = [
    "BDF_RECORDING_NOT_STARTED_REASON",
    "HeaderOnlyPreflight",
    "PreflightQcFileResult",
    "PreflightQcScan",
    "scan_preprocessing_qc",
    "scan_recording_not_started_files",
]

"""Preprocessing preflight QC scanning helpers."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import gc
import logging
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from Main_App.io import load_utils
from Main_App.io.load_utils import BDF_RECORDING_NOT_STARTED_REASON, BdfPreflightInfo
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.raw_channel_qc import RAW_CHANNEL_QC_EXCLUSION_REASON
from Main_App.processing.raw_channel_qc import evaluate_raw_channel_qc
from Main_App.processing.raw_spectral_qc import (
    RawSpectralQCResult,
    evaluate_raw_spectral_qc,
)
from Main_App.processing.removed_electrode_detection import (
    REMOVED_ELECTRODE_DETECTION_MODE_AUTO,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class HeaderOnlyPreflight:
    """A BDF file that appears to contain only the BioSemi header."""

    path: Path
    participant_id: str
    info: BdfPreflightInfo


@dataclass(frozen=True)
class PreflightQcFileResult:
    """Pre-processing QC result for one raw file."""

    path: Path
    participant_id: str
    load_error: str | None
    raw_channel_qc: Mapping[str, object] | None
    raw_spectral_qc: Mapping[str, object] | None

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
            if not result.auto_removed_electrodes:
                continue
            suggestions[result.participant_id] = list(result.auto_removed_electrodes)
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
    ref_ch1 = settings.get("ref_channel1") or settings.get("ref_ch1") or "EXG1"
    ref_ch2 = settings.get("ref_channel2") or settings.get("ref_ch2") or "EXG2"
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


def _preflight_worker_count(total: int, max_workers: int | None) -> int:
    if total <= 1:
        return 1
    try:
        requested = int(max_workers or 1)
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(total, requested))


def _scan_one_preflight_file(
    info: RawFileInfo,
    qc_settings: Mapping[str, Any],
) -> PreflightQcFileResult | None:
    file_path = Path(info.path)
    participant_id = str(info.subject_id)
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
        )
    except Exception as exc:
        logger.exception(
            "Preflight QC failed for %s",
            file_path,
            extra={"participant_id": participant_id},
        )
        return PreflightQcFileResult(
            path=file_path,
            participant_id=participant_id,
            load_error=str(exc),
            raw_channel_qc=None,
            raw_spectral_qc=None,
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
            progress(f"Scanning {file_path.name}", index - 1, total)
        indexed_results[index] = _scan_one_preflight_file(info, qc_settings)
        if progress:
            progress(f"Finished {file_path.name}", index, total)
    return PreflightQcScan(results=_ordered_results(indexed_results), cancelled=False)


def _scan_preprocessing_qc_parallel(
    pending_infos: Sequence[RawFileInfo],
    qc_settings: Mapping[str, Any],
    *,
    max_workers: int,
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
                progress(f"Scanning {file_path.name}", completed, total)
            futures[executor.submit(_scan_one_preflight_file, info, qc_settings)] = (
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
                    indexed_results[index] = future.result()
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
) -> PreflightQcScan:
    """Load each BDF lightly and run conservative pre-processing QC checks."""

    skip_keys = {_path_key(Path(path)) for path in skip_paths}
    pending_infos = [
        info for info in raw_file_infos if _path_key(Path(info.path)) not in skip_keys
    ]
    total = len(pending_infos)
    qc_settings = _auto_qc_settings(settings)
    worker_count = _preflight_worker_count(total, max_workers)
    if worker_count <= 1:
        return _scan_preprocessing_qc_serial(
            pending_infos,
            qc_settings,
            progress=progress,
            should_cancel=should_cancel,
        )
    return _scan_preprocessing_qc_parallel(
        pending_infos,
        qc_settings,
        max_workers=worker_count,
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

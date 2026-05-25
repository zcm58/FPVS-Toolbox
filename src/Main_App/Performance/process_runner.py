# -*- coding: utf-8 -*-
"""
Process-based per-file runner.

- Spawns one subprocess per EEG file (Windows-safe via "spawn").
- Caps BLAS to 1 thread per worker to avoid oversubscription.
- Uses the shared loader and canonical Main App preprocessing surface.
- Extracts events using the project's stim channel (e.g., "Status").
- Suppresses any worker GUI popups.
- Calls the existing post-export adapter (no Legacy edits).
- Adds RAM-aware backpressure: staged submissions + system memory soft-cap.
"""

from __future__ import annotations

import logging
import atexit
import hashlib
import json
import shutil
import tempfile
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from dataclasses import dataclass
from fractions import Fraction
from multiprocessing import Queue, get_context, Event
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import Main_App.processing.preprocess as backend_preprocess
from Main_App.diagnostics import log_router
from Main_App.Shared.fft_crop_utils import compute_fft_crop_from_events, compute_onbin_step

import numpy as np
import psutil  # soft memory cap
from .mp_env import set_blas_threads_multiprocess

logger = logging.getLogger(__name__)
ODDBALL_FREQ = Fraction(6, 5)
PREPROC_CACHE_VERSION = "preprocessed-raw-v1"
BDF_FIRST_N_CHANNELS = 64


@dataclass(frozen=True)
class RunParams:
    project_root: Path
    data_files: List[Path]
    settings: Dict[str, object]
    event_map: Dict[str, int]  # {label: code}
    save_folder: Path
    max_workers: Optional[int] = None
    # RAM backpressure (ratio of total system memory). None disables throttling.
    memory_soft_limit_ratio: Optional[float] = 0.85
    # How often to re-check memory when throttled
    memory_check_interval_s: float = 0.25


def _worker_init() -> None:
    """Configure per-process environment."""
    logger.info("[MP STAGE] worker_init_start pid=%d", os.getpid())
    set_blas_threads_multiprocess()

    # --- Memmap cleanup on worker exit ---
    from pathlib import Path as _Path
    base = _Path(tempfile.gettempdir()) / "fpvs_memmap"
    pid_dir = base / f"pid_{os.getpid()}"
    pid_dir.mkdir(parents=True, exist_ok=True)

    def _cleanup_pid_dir() -> None:
        try:
            shutil.rmtree(pid_dir, ignore_errors=True)  # remove memmaps for this worker
        except Exception:
            pass

    atexit.register(_cleanup_pid_dir)
    logger.info("[MP STAGE] worker_init_done pid=%d memmap_dir=%s", os.getpid(), pid_dir)


def _memmap_path_for_file(file_path: Path) -> Path:
    """Mirror the loader's deterministic per-PID memmap path for cleanup."""
    pid_dir = Path(tempfile.gettempdir()) / "fpvs_memmap" / f"pid_{os.getpid()}"
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir / (file_path.stem + "_raw.dat")


def _make_error_result(
    file_path: Path,
    stage: str,
    exc: Exception,
    start_time: Optional[float] = None,
) -> Dict[str, object]:
    """
    Build a structured error payload for a single-file run.
    """
    elapsed_ms: Optional[int] = None
    if start_time is not None:
        try:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        except Exception:
            elapsed_ms = None

    tb = traceback.format_exc()
    tb_lines = tb.strip().splitlines()
    traceback_head = "\n".join(tb_lines[:6])

    # Make the textual log message itself informative instead of just "file_processing_error",
    # so the IDE log shows file, stage, and error even if it ignores structured "extra".
    logger.error(
        "file_processing_error file=%s stage=%s error=%s elapsed_ms=%s",
        str(file_path),
        stage,
        str(exc),
        elapsed_ms,
        extra={
            "file": str(file_path),
            "stage": stage,
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
        },
    )

    payload: Dict[str, object] = {
        "status": "error",
        "file": str(file_path),
        "stage": stage,
        "error": str(exc),
        "trace": tb,
        "traceback_head": traceback_head,
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    return payload


def _build_fft_crop_file_logger(project_root: Path, file_path: Path) -> logging.Logger:
    """Create a per-file crop logger so child-process diagnostics are always persisted."""
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"fft_crop_{file_path.stem}_{os.getpid()}.log"

    logger_name = f"{__name__}.fft_crop.{file_path.stem}.{os.getpid()}"
    crop_logger = logging.getLogger(logger_name)
    crop_logger.setLevel(logging.INFO)
    crop_logger.propagate = False
    for handler in list(crop_logger.handlers):
        crop_logger.removeHandler(handler)

    handler = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    crop_logger.addHandler(handler)
    return crop_logger


def _close_worker_logger(target_logger: logging.Logger) -> None:
    for handler in list(target_logger.handlers):
        try:
            handler.flush()
            handler.close()
        finally:
            target_logger.removeHandler(handler)


def _preproc_cache_enabled(settings: Dict[str, object]) -> bool:
    value = settings.get("enable_preprocessed_cache", True)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _preproc_cache_payload(
    file_path: Path,
    settings: Dict[str, object],
    *,
    mne_version: str,
) -> Dict[str, object]:
    stat = file_path.stat()
    relevant_settings = {
        "high_pass": settings.get("high_pass"),
        "low_pass": settings.get("low_pass"),
        "downsample_rate": settings.get("downsample_rate", settings.get("downsample")),
        "reject_thresh": settings.get("reject_thresh"),
        "ref_channel1": settings.get("ref_channel1", settings.get("ref_ch1")),
        "ref_channel2": settings.get("ref_channel2", settings.get("ref_ch2")),
        "stim_channel": settings.get("stim_channel"),
        "max_idx_keep": settings.get("max_idx_keep"),
    }
    return {
        "version": PREPROC_CACHE_VERSION,
        "mne_version": mne_version,
        "source_path": str(file_path.resolve()),
        "source_size": int(stat.st_size),
        "source_mtime_ns": int(stat.st_mtime_ns),
        "loader_profile": {
            "bdf_first_n_channels": BDF_FIRST_N_CHANNELS,
            "ref_channels": [
                relevant_settings["ref_channel1"],
                relevant_settings["ref_channel2"],
            ],
            "stim_channel": relevant_settings["stim_channel"],
        },
        "preprocessing_settings": relevant_settings,
    }


def _preproc_cache_key(payload: Dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _preproc_cache_paths(project_root: Path, file_path: Path, cache_key: str) -> Tuple[Path, Path]:
    safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in file_path.stem)
    cache_dir = project_root / ".fpvs_cache" / "preprocessed"
    raw_path = cache_dir / f"{safe_stem}_{cache_key[:16]}_raw.fif"
    meta_path = cache_dir / f"{safe_stem}_{cache_key[:16]}.json"
    return raw_path, meta_path


def _raw_cache_path_for_meta(meta_path: Path) -> Path:
    return meta_path.with_name(f"{meta_path.stem}_raw.fif")


def _prune_stale_preprocessed_cache(
    *,
    cache_dir: Path,
    source_path: str,
    keep_meta_path: Path,
) -> int:
    if not cache_dir.exists():
        return 0

    pruned = 0
    for meta_path in cache_dir.glob("*.json"):
        if meta_path == keep_meta_path:
            continue
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(
                "preproc_cache_prune_skip_unreadable_meta meta=%s error=%s",
                meta_path,
                exc,
            )
            continue

        payload = metadata.get("payload")
        if not isinstance(payload, dict) or payload.get("source_path") != source_path:
            continue

        raw_path = _raw_cache_path_for_meta(meta_path)
        try:
            if raw_path.exists():
                raw_path.unlink()
            meta_path.unlink()
            pruned += 1
        except OSError as exc:
            logger.warning(
                "preproc_cache_prune_failed meta=%s raw=%s error=%s",
                meta_path,
                raw_path,
                exc,
            )
    return pruned


def _load_preprocessed_cache(
    *,
    file_path: Path,
    settings: Dict[str, object],
    project_root: Path,
    mne_module: Any,
) -> Tuple[Optional[Any], Optional[Dict[str, Any]], int, str]:
    if not _preproc_cache_enabled(settings):
        return None, None, 0, "disabled"

    payload = _preproc_cache_payload(
        file_path,
        settings,
        mne_version=str(getattr(mne_module, "__version__", "unknown")),
    )
    cache_key = _preproc_cache_key(payload)
    raw_path, meta_path = _preproc_cache_paths(project_root, file_path, cache_key)
    if not raw_path.exists() or not meta_path.exists():
        return None, None, 0, "miss"

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("cache_key") != cache_key or metadata.get("payload") != payload:
            return None, None, 0, "miss_metadata_mismatch"
        memmap_path = str(_memmap_path_for_file(raw_path))
        raw = mne_module.io.read_raw_fif(
            str(raw_path),
            preload=memmap_path,
            verbose=False,
        )
        audit_before = metadata.get("audit_before")
        if not isinstance(audit_before, dict):
            return None, None, 0, "miss_missing_audit"
        return raw, audit_before, int(metadata.get("n_rejected", 0)), "hit"
    except Exception as exc:
        logger.warning(
            "preproc_cache_read_failed file=%s cache=%s error=%s",
            file_path.name,
            raw_path,
            exc,
        )
        return None, None, 0, "read_error"


def _store_preprocessed_cache(
    *,
    raw: Any,
    file_path: Path,
    settings: Dict[str, object],
    project_root: Path,
    mne_module: Any,
    audit_before: Dict[str, Any],
    n_rejected: int,
) -> str:
    if not _preproc_cache_enabled(settings):
        return "disabled"

    payload = _preproc_cache_payload(
        file_path,
        settings,
        mne_version=str(getattr(mne_module, "__version__", "unknown")),
    )
    cache_key = _preproc_cache_key(payload)
    raw_path, meta_path = _preproc_cache_paths(project_root, file_path, cache_key)
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_meta_path = meta_path.with_suffix(".json.tmp")

    try:
        raw.save(str(raw_path), overwrite=True, verbose=False)
        metadata = {
            "cache_key": cache_key,
            "payload": payload,
            "audit_before": audit_before,
            "n_rejected": int(n_rejected),
        }
        tmp_meta_path.write_text(
            json.dumps(metadata, sort_keys=True, default=str),
            encoding="utf-8",
        )
        os.replace(tmp_meta_path, meta_path)
        pruned = _prune_stale_preprocessed_cache(
            cache_dir=raw_path.parent,
            source_path=str(file_path.resolve()),
            keep_meta_path=meta_path,
        )
        if pruned:
            logger.info(
                "preproc_cache_pruned file=%s count=%d",
                file_path.name,
                pruned,
            )
        return "stored"
    except Exception as exc:
        try:
            tmp_meta_path.unlink(missing_ok=True)  # type: ignore[arg-type]
        except OSError:
            pass
        logger.warning(
            "preproc_cache_write_failed file=%s cache=%s error=%s",
            file_path.name,
            raw_path,
            exc,
        )
        return "write_error"


def _build_epoch_data_from_spans(
    raw: Any,
    spans: List[Tuple[int, int]],
) -> Any:
    first_start, first_stop = spans[0]
    first_segment = raw.get_data(start=first_start, stop=first_stop)
    data = np.empty((len(spans),) + first_segment.shape, dtype=first_segment.dtype)
    data[0] = first_segment
    for idx, (start_samp, stop_samp) in enumerate(spans[1:], start=1):
        segment = raw.get_data(start=start_samp, stop=stop_samp)
        if segment.shape != first_segment.shape:
            raise ValueError(
                "Epoch segment shape mismatch: "
                f"expected {first_segment.shape}, got {segment.shape}"
            )
        data[idx] = segment
    return data


def _run_full_pipeline_for_file(
    file_path: Path,
    settings: Dict[str, object],
    event_map: Dict[str, int],
    save_folder: Path,
    project_root: Path,
) -> Dict[str, object]:
    """
    Canonical single-file pipeline using the PySide6 backend.

    Pipeline order (must not change):
      load → preproc audit (before) → preprocessing → events → epochs →
      post_export → preproc audit (after) → cleanup.
    """
    t0 = time.perf_counter()
    timings_ms: Dict[str, int] = {}
    cache_status = "not_checked"
    settings = dict(settings)
    output_group_by_file = settings.get("_fpvs_output_group_by_file")
    if isinstance(output_group_by_file, dict):
        group_folder = output_group_by_file.get(str(file_path.resolve()))
        if group_folder:
            settings["output_group_folder"] = str(group_folder)

    def _record_timing(section: str, started_at: float) -> None:
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        timings_ms[section] = elapsed_ms
        logger.info(
            "[TIMING] file=%s section=%s elapsed_ms=%d",
            file_path.name,
            section,
            elapsed_ms,
        )

    stage = "load"
    crop_logger = _build_fft_crop_file_logger(project_root=project_root, file_path=file_path)
    try:
        logger.info(
            "[PIPELINE START] file=%s stage=%s",
            file_path.name,
            stage,
        )
        crop_logger.info("file=%s stage=start", file_path.name)

        # Lazy imports (inside worker only)
        logger.info("[PIPELINE STAGE] file=%s stage=worker_imports_start", file_path.name)
        from Main_App.io.load_utils import load_eeg_file  # type: ignore
        from Main_App.exports.post_export_adapter import (  # type: ignore
            LegacyCtx,
            run_post_export,
        )
        import gc
        import mne  # type: ignore
        logger.info("[PIPELINE STAGE] file=%s stage=worker_imports_done", file_path.name)

        # Quiet noisy MNE INFO logs in worker processes (e.g., repeated
        # "Using data from preloaded Raw..." lines) while preserving
        # WARNING/ERROR messages.
        try:
            set_level = getattr(mne, "set_log_level", None)
            if callable(set_level):
                set_level("WARNING")
            else:
                from mne.utils import set_log_level as _set_log_level  # type: ignore
                _set_log_level("WARNING")
        except Exception:
            # If MNE changes its API, fail silently; core behavior is unaffected.
            pass

        # Minimal logger-compatible stub for loader
        class _App:
            def log(self, msg: str) -> None:  # pragma: no cover - informational
                logger.info(msg)

        # Resolve reference pair for loader so EXG policy keeps the right pair as EEG
        ref_ch1 = settings.get("ref_channel1") or settings.get("ref_ch1") or "EXG1"
        ref_ch2 = settings.get("ref_channel2") or settings.get("ref_ch2") or "EXG2"
        ref_pair = (str(ref_ch1), str(ref_ch2))

        # 1) Cache lookup, then load/preprocess only on misses.
        stage = "cache_lookup"
        logger.info("[PIPELINE STAGE] file=%s stage=cache_lookup_start", file_path.name)
        section_started = time.perf_counter()
        raw_proc, audit_before, n_rejected, cache_status = _load_preprocessed_cache(
            file_path=file_path,
            settings=settings,
            project_root=project_root,
            mne_module=mne,
        )
        _record_timing("cache_lookup", section_started)
        logger.info(
            "[PIPELINE] %s: preproc cache status=%s",
            file_path.name,
            cache_status,
        )
        logger.info(
            "[PIPELINE STAGE] file=%s stage=cache_lookup_done status=%s",
            file_path.name,
            cache_status,
        )

        if raw_proc is None:
            # 2) Load only the first 64 channels plus selected ref pair and stim.
            stage = "load"
            logger.info("[PIPELINE STAGE] file=%s stage=load_start", file_path.name)
            section_started = time.perf_counter()
            raw = load_eeg_file(
                _App(),
                str(file_path),
                ref_pair=ref_pair,
                first_n_channels=BDF_FIRST_N_CHANNELS,
            )
            _record_timing("load", section_started)
            if raw is None:
                raise RuntimeError("load_eeg_file returned None")
            logger.info("[PIPELINE STAGE] file=%s stage=load_done", file_path.name)

            sfreq = float(raw.info.get("sfreq", -1.0))
            n_ch = len(raw.ch_names)
            logger.info(
                "[PIPELINE] %s: load complete sfreq=%.3f n_channels=%d",
                file_path.name,
                sfreq,
                n_ch,
            )

            # 3) Preproc audit (before)
            stage = "preprocess"
            section_started = time.perf_counter()
            audit_before = backend_preprocess.begin_preproc_audit(
                raw,
                settings,
                file_path.name,
            )
            _record_timing("preproc_audit_before", section_started)
            logger.info(
                "[PIPELINE] %s: preproc audit_before complete",
                file_path.name,
            )

            # 4) Preprocessing via PySide6 backend (handles:
            #    initial EXG ref -> drop EXGs -> channel limit keeping stim ->
            #    downsample -> filter -> kurtosis/interp -> final avg ref)
            logger.info(
                "RUNNER_SETTINGS_SNAPSHOT file=%s high_pass=%r low_pass=%r downsample_rate=%r "
                "reject_thresh=%r ref=(%r,%r) stim=%r",
                Path(file_path).name if file_path else "UNKNOWN",
                settings.get("high_pass"),
                settings.get("low_pass"),
                settings.get("downsample_rate", settings.get("downsample")),
                settings.get("reject_thresh"),
                settings.get("ref_channel1"),
                settings.get("ref_channel2"),
                settings.get("stim_channel"),
                extra={
                    "source": "process_runner",
                    "file": file_path.name,
                    "high_pass": settings.get("high_pass"),
                    "low_pass": settings.get("low_pass"),
                    "downsample_rate": settings.get("downsample_rate"),
                    "downsample": settings.get("downsample"),
                    "reject_thresh": settings.get("reject_thresh"),
                    "ref_channel1": settings.get("ref_channel1"),
                    "ref_channel2": settings.get("ref_channel2"),
                    "stim_channel": settings.get("stim_channel"),
                },
            )
            logger.info(
                "RUNNER_PREPROC_PARAMS file=%s high_pass=%r low_pass=%r downsample_rate=%r "
                "reject_thresh=%r",
                Path(file_path).name,
                settings.get("high_pass"),
                settings.get("low_pass"),
                settings.get("downsample_rate", settings.get("downsample")),
                settings.get("reject_thresh"),
            )
            section_started = time.perf_counter()
            raw_proc, n_rejected = backend_preprocess.perform_preprocessing(
                raw_input=raw,
                params=settings,
                log_func=logger.info,
                filename_for_log=file_path.name,
            )
            _record_timing("preprocessing", section_started)
            if raw_proc is None:
                raise RuntimeError("perform_preprocessing returned None")

            sfreq_proc = float(raw_proc.info.get("sfreq", -1.0))
            n_ch_proc = len(raw_proc.ch_names)
            logger.info(
                "[PIPELINE] %s: preprocess complete n_rejected=%d sfreq=%.3f n_channels=%d",
                file_path.name,
                int(n_rejected),
                sfreq_proc,
                n_ch_proc,
            )

            section_started = time.perf_counter()
            cache_status = _store_preprocessed_cache(
                raw=raw_proc,
                file_path=file_path,
                settings=settings,
                project_root=project_root,
                mne_module=mne,
                audit_before=audit_before,
                n_rejected=int(n_rejected),
            )
            _record_timing("cache_store", section_started)
            logger.info(
                "[PIPELINE] %s: preproc cache store status=%s",
                file_path.name,
                cache_status,
            )

            # Free loader Raw ASAP
            del raw
            gc.collect()
        elif audit_before is None:
            raise RuntimeError("preprocessed cache hit missing audit metadata")

        # 4) Events — prefer explicit stim channel (BioSemi 'Status')
        stage = "events"
        section_started = time.perf_counter()
        stim = (
            settings.get("stim_channel")
            or settings.get("stim")
            or "Status"
        )
        events_source = "stim"
        try:
            # Use the configured stim channel when available
            events = mne.find_events(
                raw_proc,
                stim_channel=stim,
                shortest_event=1,
            )  # type: ignore[arg-type]
        except Exception:
            # Fallback to annotations if present
            events, _ = mne.events_from_annotations(raw_proc)
            events_source = "annotations"

        # If there are no events at all, this is a true failure.
        if events.size == 0:
            raise RuntimeError(
                f"No events found for {file_path.name} (source='{events_source}', stim='{stim}')"
            )

        events_info = {
            "stim_channel": stim,
            "n_events": int(len(events)),
            "source": events_source,
        }
        logger.info(
            "[PIPELINE] %s: events complete source=%s stim=%s n_events=%d",
            file_path.name,
            events_source,
            stim,
            events_info["n_events"],
        )
        _record_timing("events", section_started)

        # 5) Epochs per label/code (tolerant of missing runs)
        stage = "epochs"
        section_started = time.perf_counter()
        tmin = float(settings.get("epoch_start", -1.0))
        tmax = float(settings.get("epoch_end", 1.0))
        sfreq = float(raw_proc.info["sfreq"])
        _, n_step, step_err = compute_onbin_step(fs=sfreq, f_oddball=ODDBALL_FREQ)
        if step_err:
            crop_logger.warning("file=%s step_error=%s", file_path.name, step_err)

        # Which event codes are actually present in this recording?
        have_codes = {int(c) for c in events[:, 2].tolist()}
        onset_ids = set(int(v) for v in event_map.values())
        crop_results, _, run_warnings = compute_fft_crop_from_events(
            events=events,
            fs=sfreq,
            onset_ids=onset_ids,
            oddball_id=55,
            stream_end_sample=int(raw_proc.n_times),
        )
        for run_warning in run_warnings:
            crop_logger.warning("file=%s run_warning=%s", file_path.name, run_warning)

        epochs_dict: Dict[str, List[object]] = {}
        total_epochs = 0

        for label, code in event_map.items():
            code_int = int(code)

            if code_int not in have_codes:
                msg = (
                    f"[AUDIT WARNING] {file_path.name}: label='{label}' code={code_int} "
                    f"has 0 matching events; skipping epochs for this label."
                )
                logger.warning(msg)
                epochs_dict[label] = []
                continue

            rep_keys = sorted([k for k in crop_results if int(k[0]) == code_int], key=lambda x: x[1])
            rep_spans: List[Tuple[int, int]] = []
            rep_events: List[List[int]] = []
            rep_metadata: List[dict] = []

            n_common: Optional[int] = None
            fallback_rep_reasons = [
                f"rep={int(rep_key[1])}:{crop_results[rep_key].fallback_reason or 'unknown'}"
                for rep_key in rep_keys
                if crop_results[rep_key].fallback
            ]
            if n_step:
                rep_lengths = [crop_results[k].n_samples for k in rep_keys if not crop_results[k].fallback and crop_results[k].n_samples > 0]
                if rep_lengths:
                    n_common = (min(rep_lengths) // n_step) * n_step
                    if n_common <= 0:
                        n_common = None

            if not n_step:
                raise RuntimeError(
                    "Locked FFT crop required but no valid N_step is available "
                    f"for {file_path.name} condition={label}. "
                    "Fixed-epoch fallback is disabled for the normal processing pipeline."
                )
            if fallback_rep_reasons:
                raise RuntimeError(
                    "Locked FFT crop required but one or more repetitions could not be "
                    f"cropped on-bin for {file_path.name} condition={label}: "
                    f"{'; '.join(fallback_rep_reasons)}. "
                    "Fixed-epoch fallback is disabled for the normal processing pipeline."
                )
            if n_common is None:
                raise RuntimeError(
                    "Locked FFT crop required but no common on-bin epoch length could be "
                    f"computed for {file_path.name} condition={label}. "
                    "Fixed-epoch fallback is disabled for the normal processing pipeline."
                )
            if int(n_common) % int(n_step) != 0:
                raise RuntimeError(
                    "Locked FFT crop invariant failed before epoching: "
                    f"N_common={n_common}, N_step={n_step}, "
                    f"file={file_path.name}, condition={label}."
                )

            crop_logger.info(
                "file=%s condition=%s label_epoch_mode=55_onbin n_common=%d n_step=%s",
                file_path.name,
                label,
                int(n_common),
                n_step,
            )

            for rep_key in rep_keys:
                crop = crop_results[rep_key]
                fallback_reason = ""
                crop_mode = "55_onbin"
                first55_samp = crop.first55_sample
                last55_samp = crop.last55_sample
                n55 = int(crop.n55_dedup)
                n_rep = int(crop.n_samples)
                available_samples = int(crop.available_samples)

                if crop.fallback:
                    raise RuntimeError(
                        "Locked FFT crop required but a fallback repetition reached "
                        f"epoch building for {file_path.name} condition={label} "
                        f"rep={int(rep_key[1])}: {crop.fallback_reason or 'unknown'}."
                    )

                start_samp = int(crop.crop_start_sample)
                stop_samp = int(start_samp + n_common)

                expected_n = max(0, stop_samp - start_samp)

                if stop_samp <= start_samp:
                    raise RuntimeError(
                        "Locked FFT crop produced an empty segment: "
                        f"file={file_path.name}, condition={label}, rep={int(rep_key[1])}, "
                        f"start={start_samp}, stop={stop_samp}."
                    )

                n_used = expected_n
                n_mod_step = int(n_used % n_step)
                if n_mod_step != 0:
                    raise RuntimeError(
                        "Locked FFT crop invariant failed during epoching: "
                        f"N={n_used}, N_step={n_step}, N_mod_step={n_mod_step}, "
                        f"file={file_path.name}, condition={label}, rep={int(rep_key[1])}."
                    )
                df_hz = (sfreq / float(n_used)) if n_used > 0 else 0.0
                k0 = (1.2 * float(n_used) / sfreq) if n_used > 0 else 0.0
                f_bin_hz = (round(k0) * df_hz) if n_used > 0 else 0.0

                crop_logger.info(
                    (
                        "file=%s condition=%s rep=%d fs=%.6f N_step=%s n55=%d first55_samp=%s "
                        "last55_samp=%s available_samples=%d N_rep=%d N_common=%s N_common_mod_step=%s "
                        "df_hz=%.9f k0=%.9f f_bin_hz=%.9f crop_mode=%s fallback_reason=%s"
                    ),
                    file_path.name,
                    label,
                    int(rep_key[1]),
                    sfreq,
                    n_step,
                    n55,
                    first55_samp,
                    last55_samp,
                    available_samples,
                    n_rep,
                    n_common,
                    n_mod_step,
                    df_hz,
                    k0,
                    f_bin_hz,
                    crop_mode,
                    fallback_reason,
                )

                rep_spans.append((start_samp, stop_samp))
                rep_events.append([start_samp, 0, code_int])
                rep_metadata.append(
                    {
                        "crop_mode": crop_mode,
                        "n55": n55,
                        "first55_samp": first55_samp,
                        "last55_samp": last55_samp,
                        "N_step": int(n_step) if n_step else None,
                        "N_mod_step": n_mod_step if n_step else None,
                        "fallback_reason": fallback_reason,
                    }
                )

            n_ep = len(rep_spans)
            logger.info(
                "[AUDIT DEBUG] %s: label='%s' code=%s events_for_code=%d epochs_after_crop=%d",
                file_path.name,
                label,
                code_int,
                int((events[:, 2] == code_int).sum()),
                n_ep,
            )

            if n_ep == 0:
                msg = (
                    f"[AUDIT WARNING] {file_path.name}: label='{label}' code={code_int} "
                    f"produced 0 epochs after epoching; skipping this label."
                )
                logger.warning(msg)
                epochs_dict[label] = []
                continue

            import pandas as pd

            epoch_data = _build_epoch_data_from_spans(raw_proc, rep_spans)

            epochs = mne.EpochsArray(
                epoch_data,
                raw_proc.info.copy(),
                events=np.asarray(rep_events, dtype=int),
                event_id={label: code_int},
                tmin=0.0,
                baseline=None,
                verbose=False,
            )
            epochs.metadata = pd.DataFrame(rep_metadata)
            epochs_dict[label] = [epochs]
            total_epochs += n_ep

        # If no epochs at all were created for any label, this is a real failure
        if total_epochs == 0:
            raise RuntimeError(
                f"No epochs created for any configured labels in {file_path.name}. "
                f"Check event_map, epoch window (tmin={tmin}, tmax={tmax}), and triggers."
            )

        logger.info(
            "[PIPELINE] %s: epochs complete total_epochs=%d",
            file_path.name,
            total_epochs,
        )
        _record_timing("epochs", section_started)

        # 6) Post-export (delegates to Legacy post_process via adapter)
        stage = "export"
        section_started = time.perf_counter()
        export_timing_records: List[Dict[str, object]] = []
        ctx = LegacyCtx(
            preprocessed_data=epochs_dict,
            save_folder_path=SimpleNamespace(get=lambda: str(save_folder)),
            data_paths=[str(file_path)],
            settings=settings,
            log=logger.info,
            export_timing_records=export_timing_records,
        )
        fif_written = run_post_export(ctx, list(event_map.keys()))
        logger.info(
            "[PIPELINE] %s: export complete",
            file_path.name,
        )
        _record_timing("export", section_started)

        # 7) Preproc audit (after)
        stage = "audit"
        section_started = time.perf_counter()
        audit_after, problems = backend_preprocess.finalize_preproc_audit(
            audit_before,
            raw_proc,
            settings,
            file_path.name,
            events_info=events_info,
            fif_written=fif_written,
            n_rejected=n_rejected,
        )

        logger.info(
            "[PIPELINE] %s: audit complete n_rejected=%s problems=%s",
            file_path.name,
            audit_after.get("n_rejected"),
            problems,
        )
        _record_timing("preproc_audit_after", section_started)

        # Developer-only audit debug: summarize final preprocessing state when a
        # reference pair was requested in the settings. Uses the new audit payload
        # schema from backend_preprocess.finalize_preproc_audit.
        ref_expected = [
            ch
            for ch in (
                settings.get("ref_channel1"),
                settings.get("ref_channel2"),
            )
            if ch
        ]

        if ref_expected:
            fields = {
                "ref_expected": tuple(ref_expected),
                "ref_chans": audit_after.get("ref_chans"),
                "sfreq": audit_after.get("sfreq"),
                "lowpass": audit_after.get("lowpass"),
                "highpass": audit_after.get("highpass"),
                "n_channels": audit_after.get("n_channels"),
                "stim": audit_after.get("stim_channel"),
                "n_events": audit_after.get("n_events"),
                "n_rejected": audit_after.get("n_rejected"),
                "fif_written": audit_after.get("fif_written"),
            }

            parts = [f"file={file_path.name}"]
            parts.extend(
                f"{key}={value}"
                for key, value in fields.items()
                if value is not None
            )
            if problems:
                parts.append(f"problems={problems}")

            logger.info("[AUDIT DEBUG] %s", " ".join(parts))

        # Done with Raw/Epochs
        section_started = time.perf_counter()
        del raw_proc, epochs_dict
        gc.collect()

        # Attempt memmap cleanup for this file (safe if still open -> ignore)
        try:
            p = _memmap_path_for_file(file_path)
            if p.exists():
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
            pid_dir = p.parent
            try:
                pid_dir.rmdir()  # remove if empty
            except OSError:
                pass
        except Exception:
            pass
        _record_timing("cleanup", section_started)

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "[PIPELINE END] file=%s elapsed_ms=%d",
            file_path.name,
            elapsed_ms,
        )
        return {
            "status": "ok",
            "file": str(file_path),
            "stage": "done",
            "elapsed_ms": elapsed_ms,
            "audit": audit_after,
            "problems": problems,
            "events_info": events_info,
            "timings_ms": dict(timings_ms),
            "export_timing_records": export_timing_records,
            "preproc_cache_status": cache_status,
            "post_export_ok": True,
        }
    except Exception as e:  # pragma: no cover - worker error path
        crop_logger.exception("file=%s stage=%s worker_error=%s", file_path.name, stage, str(e))
        return _make_error_result(
            file_path=file_path,
            stage=stage,
            exc=e,
            start_time=t0,
        )
    finally:
        _close_worker_logger(crop_logger)



def _process_one_file(
    file_path: Path,
    settings: Dict[str, object],
    event_map: Dict[str, int],
    save_folder: Path,
    project_root: Path,
) -> Dict[str, object]:
    """
    Execute the processing steps for a single file using the PySide6 backend.

    This is the worker entry point used by multiprocessing. It delegates to
    _run_full_pipeline_for_file so the same pipeline can be reused by other callers.
    """
    return _run_full_pipeline_for_file(file_path, settings, event_map, save_folder, project_root)


def _log_export_timing_records(result: Dict[str, object]) -> None:
    log_router.replay_worker_timing_records(logger, result=result)


def _memory_ok(limit_ratio: Optional[float]) -> Tuple[bool, float]:
    """Return (is_ok, percent_used) for system memory usage."""
    vm = psutil.virtual_memory()
    if limit_ratio is None:
        return True, vm.percent
    return (vm.percent / 100.0) < float(limit_ratio), vm.percent


def _terminate_executor_workers(pool: Any) -> int:
    """Best-effort termination for active ProcessPoolExecutor child processes."""
    processes = getattr(pool, "_processes", None)
    if not processes:
        return 0

    terminated = 0
    for proc in list(processes.values()):
        if proc is None:
            continue
        try:
            if proc.is_alive():
                proc.terminate()
                terminated += 1
        except (OSError, RuntimeError, ValueError):
            logger.debug("process_pool_worker_terminate_failed", exc_info=True)

    for proc in list(processes.values()):
        if proc is None:
            continue
        try:
            proc.join(timeout=0.2)
            if proc.is_alive() and hasattr(proc, "kill"):
                proc.kill()
                proc.join(timeout=0.2)
        except (OSError, RuntimeError, ValueError):
            logger.debug("process_pool_worker_join_failed", exc_info=True)

    return terminated


def _scavenge_stale_memmaps() -> None:
    """Remove memmap PID folders for processes that are no longer alive."""
    try:
        from pathlib import Path as _Path
        import psutil as _psutil
        base = _Path(tempfile.gettempdir()) / "fpvs_memmap"
        if not base.exists():
            return
        for d in base.glob("pid_*"):
            try:
                pid = int(d.name.split("_", 1)[1])
            except Exception:
                continue
            if not _psutil.pid_exists(pid):
                shutil.rmtree(d, ignore_errors=True)
        try:
            base.rmdir()  # remove root if empty
        except OSError:
            pass
    except Exception:
        pass


def run_project_parallel(
    params: RunParams,
    progress_queue: Optional[Queue] = None,
    cancel_event: Optional[Event] = None,
) -> None:
    """
    Submit one process per file and report progress via an optional Queue.

    Queue messages:
      - {"type":"progress","completed":int,"total":int,"result":{...}}
      - {"type":"done","count":int,"cancelled":bool, ...}
    """
    files = list(params.data_files)
    if not files:
        if progress_queue:
            progress_queue.put({"type": "done", "count": 0, "cancelled": False})
        return

    maxw = params.max_workers or max(1, (os.cpu_count() or 2) - 1)
    ctx = get_context("spawn")

    completed = 0
    total = len(files)
    remaining = list(files)
    in_flight: Dict[object, Path] = {}
    peak_in_flight = 0
    max_memory_percent = 0.0
    memory_limit_ratio = getattr(params, "memory_soft_limit_ratio", None)
    memory_check_interval = getattr(params, "memory_check_interval_s", 0.25)
    run_started_at = time.perf_counter()

    # Batch-level stats for n_rejected (number of channels interpolated per file)
    total_rejected = 0
    files_with_audit = 0

    cancelled = False
    shutdown_wait = True
    interrupted_files: List[str] = []

    def _cancelled() -> bool:
        nonlocal cancelled
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
        return cancelled

    logger.info(
        "[MP STAGE] pool_create_start max_workers=%d files=%d",
        maxw,
        total,
    )
    pool = ProcessPoolExecutor(
        max_workers=maxw,
        mp_context=ctx,
        initializer=_worker_init,
    )
    logger.info("[MP STAGE] pool_created max_workers=%d", maxw)

    try:

        def _cancel_active_pool() -> None:
            nonlocal shutdown_wait, interrupted_files
            if not _cancelled():
                return

            interrupted = list(in_flight.values()) + list(remaining)
            interrupted_files = [str(file_path) for file_path in interrupted]
            for fut in list(in_flight.keys()):
                try:
                    fut.cancel()
                except RuntimeError:
                    logger.debug("process_pool_future_cancel_failed", exc_info=True)

            terminated = _terminate_executor_workers(pool)
            shutdown_wait = False
            remaining.clear()
            in_flight.clear()
            logger.info(
                "mp_run_cancel_terminated_workers interrupted_files=%d workers_terminated=%d",
                len(interrupted_files),
                terminated,
            )

        def _submit_next_available() -> bool:
            """Submit one file if capacity and (if enabled) memory is OK."""
            nonlocal remaining, peak_in_flight, max_memory_percent
            if not remaining or len(in_flight) >= maxw:
                return False
            if _cancelled():
                return False

            # Optional soft-cap on system RAM
            mem_ok, percent_used = _memory_ok(memory_limit_ratio)
            if percent_used > max_memory_percent:
                max_memory_percent = percent_used
            if not mem_ok:
                return False

            f = remaining.pop(0)
            logger.info(
                "[MP STAGE] submit_file_start file=%s in_flight=%d remaining=%d",
                f.name,
                len(in_flight),
                len(remaining),
            )
            fut = pool.submit(
                _process_one_file,
                f,
                params.settings,
                params.event_map,
                params.save_folder,
                params.project_root,
            )
            in_flight[fut] = f
            logger.info(
                "[MP STAGE] submit_file_done file=%s in_flight=%d remaining=%d",
                f.name,
                len(in_flight),
                len(remaining),
            )
            if len(in_flight) > peak_in_flight:
                peak_in_flight = len(in_flight)
            return True

        # Prime pool
        while len(in_flight) < maxw and remaining:
            if not _submit_next_available():
                break

        # Drain
        while in_flight or remaining:
            if not in_flight:
                if _cancelled():
                    _cancel_active_pool()
                    break
                if not _submit_next_available():
                    # Nothing could be submitted (likely due to cancellation).
                    if _cancelled() or not remaining:
                        if _cancelled():
                            _cancel_active_pool()
                        break
                    time.sleep(max(0.01, float(memory_check_interval)))
                continue

            done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED, timeout=0.5)
            if not done:
                if _cancelled():
                    _cancel_active_pool()
                    break
                _submit_next_available()
                continue

            for fut in done:
                f = in_flight.pop(fut, None)
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {
                        "status": "error",
                        "file": str(f) if f else "unknown",
                        "error": str(exc),
                    }

                # Accumulate per-file rejected-channel counts when available
                if isinstance(res, dict) and res.get("status") == "ok":
                    _log_export_timing_records(res)
                    audit = res.get("audit") or {}
                    if isinstance(audit, dict):
                        n_rejected = audit.get("n_rejected")
                        if isinstance(n_rejected, (int, float)):
                            total_rejected += int(n_rejected)
                            files_with_audit += 1

                completed += 1
                if progress_queue:
                    progress_queue.put(
                        {
                            "type": "progress",
                            "completed": completed,
                            "total": total,
                            "result": res,
                        }
                    )

            if _cancelled():
                _cancel_active_pool()
                break

            _submit_next_available()
    finally:
        try:
            pool.shutdown(wait=shutdown_wait, cancel_futures=True)
        except TypeError:
            pool.shutdown(wait=shutdown_wait)

    # Final cleanup: remove any stale memmaps in the %TEMP% folder from previous runs
    _scavenge_stale_memmaps()

    elapsed_seconds = time.perf_counter() - run_started_at
    logger.info(
        (
            "mp_run_summary num_files=%d completed=%d "
            "max_workers_param=%s max_workers_used=%d "
            "peak_in_flight=%d max_memory_percent=%.2f "
            "elapsed_seconds=%.3f cancelled=%s"
        ),
        total,
        completed,
        params.max_workers,
        maxw,
        peak_in_flight,
        max_memory_percent,
        elapsed_seconds,
        cancelled,
    )

    # Batch-level summary: average number of channels rejected per file.
    avg_rejected: Optional[float] = None
    if files_with_audit:
        avg_rejected = total_rejected / files_with_audit
        logger.info(
            "batch_summary average_rejected_channels_per_file=%.2f "
            "files_with_audit=%d total_rejected=%d",
            avg_rejected,
            files_with_audit,
            total_rejected,
        )

    if progress_queue:
        done_msg: Dict[str, object] = {
            "type": "done",
            "count": completed,
        }
        if cancelled:
            done_msg["cancelled"] = True
        else:
            done_msg["cancelled"] = False

        if avg_rejected is not None:
            done_msg.update(
                {
                    "avg_rejected": avg_rejected,
                    "total_rejected": total_rejected,
                    "files_with_audit": files_with_audit,
                }
            )
        if interrupted_files:
            done_msg["interrupted_files"] = interrupted_files
        progress_queue.put(done_msg)

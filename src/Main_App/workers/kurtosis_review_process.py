"""Spawned, resource-bounded preparation of recording-local QC-16 evidence.

This module owns scheduling only. The shared serial scanner owns validation,
diagnostics, preprocessing, checkpoints and Raw cleanup. No Raw object or GUI
callback crosses the process boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import logging
from multiprocessing import get_context
import os
from pathlib import Path
from queue import Empty, Full
from time import perf_counter
from typing import TYPE_CHECKING, Any

import psutil

from Main_App.workers.mp_env import compute_effective_max_workers

if TYPE_CHECKING:
    from Main_App.processing.kurtosis_review_scan import (
        CancelCallback,
        KurtosisReviewFileResult,
        KurtosisReviewScan,
        ProgressCallback,
    )

logger = logging.getLogger(__name__)
_WORKER_CANCEL: Any = None
_WORKER_MESSAGES: Any = None
_GIB = 1024**3


def review_process_worker_count(
    raw_file_infos: Sequence[Any], max_workers: int | None = None,
) -> int:
    """Share the main pool's CPU/RAM policy and reserve half available RAM.

    The largest concurrent source files determine the budget: packed BDFs can
    expand into float64 data plus filtering/resampling scratch. One job is the
    minimum fallback, as in the existing serial review route. Unlike threads,
    independent processes safely own memmaps for identically named sources.
    """
    if not raw_file_infos:
        return 0
    try:
        memory = psutil.virtual_memory()
        cap = min(len(raw_file_infos), compute_effective_max_workers(
            int(memory.total), os.cpu_count() or 1, max_workers,
        ))
        estimates = sorted(
            (max(_GIB, Path(info.path).stat().st_size * 24) for info in raw_file_infos),
            reverse=True,
        )
        budget = max(0, int(memory.available) // 2)
        used = 0
        fitted = 0
        for estimate in estimates[:cap]:
            if used + estimate > budget:
                break
            used += estimate
            fitted += 1
        return max(1, fitted)
    except (AttributeError, OSError, TypeError, ValueError):
        return 1


def _emit_worker_message(message: dict[str, Any]) -> None:
    """Best-effort diagnostics must never impede numerical work or shutdown."""
    if _WORKER_MESSAGES is None:
        return
    try:
        _WORKER_MESSAGES.put_nowait(message)
    except (Full, OSError, ValueError):
        pass


class _ReviewTimingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if "kurtosis_review_timing" in message or "kurtosis_scoring_timing" in message:
            _emit_worker_message({
                "type": "log", "name": record.name,
                "level": record.levelno, "message": message,
            })


def _review_worker_init(cancel_event: Any, progress_queue: Any) -> None:
    """Reuse stable numerical limits, bounded FIR cache and private memmaps."""
    global _WORKER_CANCEL, _WORKER_MESSAGES
    from Main_App.workers import process_runner

    _WORKER_CANCEL = cancel_event
    _WORKER_MESSAGES = progress_queue
    # Messages are informative; never wait for a feeder if its parent failed.
    progress_queue.cancel_join_thread()
    process_runner._worker_init()
    for name in ("Main_App.processing.kurtosis_review_scan", "Main_App.processing.preprocess"):
        target = logging.getLogger(name)
        target.setLevel(logging.INFO)
        target.addHandler(_ReviewTimingHandler())


def _run_one_review(
    info: Any, settings: dict[str, Any], event_map: dict[str, int],
    reviewed_event_plans_by_file: Mapping[str, Any] | None,
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None,
) -> KurtosisReviewScan:
    from Main_App.processing.kurtosis_review_scan import _scan_kurtosis_review_serial
    from Main_App.processing.prepared_fir import prepared_fir_scope
    from Main_App.workers import process_runner

    with prepared_fir_scope(process_runner._WORKER_FIR_CACHE):
        return _scan_kurtosis_review_serial(
            [info], settings, event_map=event_map,
            reviewed_event_plans_by_file=reviewed_event_plans_by_file,
            raw_channel_qc_by_recording=raw_channel_qc_by_recording,
            progress=lambda message, _done, _total: _emit_worker_message({
                "type": "progress", "message": message,
            }),
            should_cancel=_WORKER_CANCEL.is_set,
        )


def _failure_result(info: Any, exc: Exception) -> KurtosisReviewFileResult:
    from Main_App.processing.kurtosis_review_scan import _error_result, _identity

    return _error_result(_identity(info), exc)


def run_process_review(
    raw_file_infos: Sequence[Any], settings: Mapping[str, Any], *,
    event_map: Mapping[str, int],
    reviewed_event_plans_by_file: Mapping[str, Any] | None = None,
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None = None,
    max_workers: int | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    result_progress: Callable[[int, tuple[KurtosisReviewFileResult, ...]], None] | None = None,
) -> KurtosisReviewScan:
    """Prepare already-classified eligible recordings without widget access.

    Submission is bounded by the resource budget. Cancellation stops new work
    and waits cooperatively for active scanners to release their Raw objects.
    Completion callbacks run on this calling thread; returned results retain
    input order even when workers finish out of order.
    """
    from Main_App.processing.kurtosis_review_scan import KurtosisReviewScan

    infos = list(raw_file_infos)
    if not infos or (should_cancel is not None and should_cancel()):
        return KurtosisReviewScan((), cancelled=bool(infos))
    requested_workers = max_workers
    if requested_workers is None:
        configured_workers = settings.get("max_parallel_workers_override")
        if not isinstance(configured_workers, bool):
            try:
                configured_workers = int(configured_workers)
            except (TypeError, ValueError):
                configured_workers = 0
            if configured_workers > 0:
                requested_workers = configured_workers
    worker_count = review_process_worker_count(infos, requested_workers)
    child_settings = dict(settings)
    # This runtime callback is replaced by the child-owned cancellation event.
    child_settings.pop("_fpvs_kurtosis_checkpoint_should_cancel", None)
    context = get_context("spawn")
    cancel_event = context.Event()
    messages = context.Queue(maxsize=256)
    pool: Any = None
    futures: dict[Any, int] = {}
    indexed_results: dict[int, tuple[KurtosisReviewFileResult, ...]] = {}
    next_index = 0
    completed = 0
    started = perf_counter()
    cancelled = False
    logger.info("kurtosis_review_process_started files=%d max_workers=%d", len(infos), worker_count)

    def check_cancel() -> bool:
        nonlocal cancelled
        if should_cancel is not None and should_cancel():
            cancelled = True
            cancel_event.set()
        return cancelled

    def drain_messages() -> None:
        while True:
            try:
                message = messages.get_nowait()
            except Empty:
                return
            if message.get("type") == "progress" and progress is not None:
                progress(str(message["message"]), completed, len(infos))
            elif message.get("type") == "log":
                logging.getLogger(str(message["name"])).log(int(message["level"]), str(message["message"]))

    def accept(index: int, results: tuple[KurtosisReviewFileResult, ...]) -> None:
        nonlocal completed
        indexed_results[index] = results
        completed += len(results)
        if result_progress is not None and results:
            result_progress(index, results)
        if progress is not None and results:
            progress(f"Finished kurtosis review scan for {Path(infos[index].path).name}", completed, len(infos))

    def submit_available() -> None:
        nonlocal next_index
        while next_index < len(infos) and len(futures) < worker_count and not check_cancel():
            index = next_index
            next_index += 1
            try:
                future = pool.submit(
                    _run_one_review, infos[index], child_settings, dict(event_map),
                    reviewed_event_plans_by_file, raw_channel_qc_by_recording,
                )
            except Exception as exc:
                accept(index, (_failure_result(infos[index], exc),))
            else:
                futures[future] = index

    try:
        if progress is not None:
            progress(f"Preparing kurtosis evidence with {worker_count} process worker(s)", 0, len(infos))
        pool = ProcessPoolExecutor(
            max_workers=worker_count, mp_context=context,
            initializer=_review_worker_init, initargs=(cancel_event, messages),
        )
        submit_available()
        while futures:
            if check_cancel():
                for future in futures:
                    future.cancel()
            drain_messages()
            done, _pending = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                index = futures.pop(future)
                if future.cancelled():
                    continue
                try:
                    scan = future.result()
                except Exception as exc:
                    accept(index, (_failure_result(infos[index], exc),))
                else:
                    accept(index, scan.results)
                    if scan.cancelled:
                        cancelled = True
                        cancel_event.set()
            submit_available()
        drain_messages()
    except Exception:  # Pool/observer boundary: cancel active owners before re-raising any failure.
        cancel_event.set()
        for future in futures:
            future.cancel()
        raise
    finally:
        try:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
        finally:
            messages.close()
            messages.join_thread()
            logger.info(
                "kurtosis_review_process_finished files=%d completed=%d max_workers=%d elapsed_seconds=%.3f cancelled=%s",
                len(infos), completed, worker_count, perf_counter() - started, cancelled,
            )
    return KurtosisReviewScan(
        tuple(result for index in sorted(indexed_results) for result in indexed_results[index]),
        cancelled=cancelled,
    )


__all__ = ["review_process_worker_count", "run_process_review"]

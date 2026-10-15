"""Spawned, resource-bounded preparation of recording-local QC-16 evidence.

This module owns scheduling only. The shared serial scanner owns validation,
diagnostics, preprocessing, checkpoints and Raw cleanup. No Raw object or GUI
callback crosses the process boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
import logging
from multiprocessing import get_context
import os
from pathlib import Path
from queue import Empty, Full
from time import perf_counter
from typing import TYPE_CHECKING, Any

import psutil

from Main_App.workers.mp_env import compute_dynamic_worker_ceiling, compute_effective_max_workers
from Main_App.workers.review_resource_budget import (
    ReviewMemoryEstimate, ReviewMemoryProbeError, actual_scoring_bytes, estimate_review_memory,
    memory_admission_fits, probe_memory_snapshot, probe_owned_memory, read_review_geometry,
    single_review_capacity_bytes,
)

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
_WORKER_GRANT_EVENTS: Any = None
_WORKER_GRANT_STATUS: Any = None
_WORKER_CREDITS: tuple[int, ...] = ()
_WORKER_EXCLUSIVE: tuple[bool, ...] = ()
_GIB = 1024**3


@dataclass(frozen=True)
class _ReviewResourcePlan:
    max_workers: int
    budget_bytes: int
    credits: tuple[int, ...]
    estimates: tuple[ReviewMemoryEstimate | None, ...] = ()
    exclusive: tuple[bool, ...] = ()
    emergency_bytes: int = 0
    dynamic: bool = False


def _review_resource_plan(
    raw_file_infos: Sequence[Any], max_workers: int | None = None,
    *, settings: Mapping[str, Any] | None = None,
) -> _ReviewResourcePlan:
    """Use geometry credits for validated settings; retain the legacy fallback.

    The dynamic pool ceiling is independent of initial memory pressure. Its
    live admissions include idle-worker floors and one full-rate reserve.
    Calls without settings retain the previous source-size snapshot API.
    """
    if not raw_file_infos:
        return _ReviewResourcePlan(0, 0, ())
    try:
        memory = psutil.virtual_memory()
        cap = min(len(raw_file_infos), compute_effective_max_workers(
            int(memory.total), os.cpu_count() or 1, max_workers,
        ))
        budget = max(0, int(memory.available) // 2)
    except (AttributeError, OSError, OverflowError, RuntimeError, TypeError, ValueError, psutil.Error):
        return _ReviewResourcePlan(1, 0, (_GIB,) * len(raw_file_infos))
    credits = []
    estimates = []
    exclusive = []
    geometry_supported = True
    if settings is not None:
        from Main_App.processing.raw_channel_qc import (
            REMOVED_ELECTRODE_DETECTION_MODE_AUTO, normalize_removed_electrode_detection_mode,
        )
        raw_qc_enabled = True
        if "removed_electrode_detection_mode" in settings or "auto_detect_removed_electrodes" in settings:
            try:
                raw_qc_enabled = normalize_removed_electrode_detection_mode(
                    settings.get("removed_electrode_detection_mode"),
                    auto_detect_removed_electrodes=settings.get("auto_detect_removed_electrodes", False),
                ) == REMOVED_ELECTRODE_DETECTION_MODE_AUTO
            except (TypeError, ValueError):
                geometry_supported = False
    for info in raw_file_infos:
        estimate = None
        try:
            credit = max(_GIB, Path(info.path).stat().st_size * 24)
            if settings is not None and geometry_supported:
                geometry = read_review_geometry(Path(info.path), settings)
                if geometry is not None:
                    estimate = estimate_review_memory(
                        geometry, filter_enabled=bool(settings.get("high_pass") or settings.get("low_pass")),
                        notch_enabled=bool(settings.get("line_noise_filter_enabled")), raw_qc_enabled=raw_qc_enabled,
                    )
                    credit = estimate.healthy_bytes
        except (AttributeError, ImportError, OSError, OverflowError, RuntimeError, TypeError, ValueError):
            # An unavailable estimate cannot share its reservation with other
            # jobs. The ordinary scanner still reports its source-file error.
            credit = max(_GIB, budget + 1)
        credits.append(credit)
        estimates.append(estimate)
        exclusive.append(settings is not None and estimate is None)
    used = 0
    fitted = 0
    # The pool may process large jobs alone and small jobs together; its maximum
    # useful size is the largest affordable subset, not the largest-file subset.
    for credit in sorted(credits)[:cap]:
        if used + credit > budget:
            break
        used += credit
        fitted += 1
    if settings is None:
        return _ReviewResourcePlan(max(1, fitted), budget, tuple(credits))
    cap = min(len(raw_file_infos), compute_dynamic_worker_ceiling(max_workers))
    emergency = max((estimate.emergency_extra_bytes for estimate in estimates if estimate is not None), default=0)
    budget = max(0, int(memory.available) - max(_GIB, int(memory.total) // 16))
    return _ReviewResourcePlan(cap, budget, tuple(credits), tuple(estimates), tuple(exclusive), emergency, True)


def review_process_worker_count(
    raw_file_infos: Sequence[Any], max_workers: int | None = None,
    *, settings: Mapping[str, Any] | None = None,
) -> int:
    """Return the dynamic ceiling or the legacy unvalidated-size snapshot."""
    return _review_resource_plan(raw_file_infos, max_workers, settings=settings).max_workers


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
        if ("kurtosis_review_timing" in message or "kurtosis_scoring_timing" in message
                or "raw_review_diagnostics_cache" in message):
            _emit_worker_message({
                "type": "log", "name": record.name,
                "level": record.levelno, "message": message,
            })


def _review_worker_init(cancel_event: Any, progress_queue: Any,
                        grant_events=None, grant_status=None, credits=(), exclusive=()) -> None:
    """Reuse stable numerical limits, bounded FIR cache and private memmaps."""
    global _WORKER_CANCEL, _WORKER_MESSAGES, _WORKER_GRANT_EVENTS, _WORKER_GRANT_STATUS, _WORKER_CREDITS, _WORKER_EXCLUSIVE
    from Main_App.workers import process_runner

    _WORKER_CANCEL = cancel_event
    _WORKER_MESSAGES = progress_queue
    _WORKER_GRANT_EVENTS, _WORKER_GRANT_STATUS, _WORKER_CREDITS = grant_events, grant_status, credits
    _WORKER_EXCLUSIVE = exclusive
    # Messages are informative; never wait for a feeder if its parent failed.
    progress_queue.cancel_join_thread()
    process_runner._worker_init()
    for name in ("Main_App.processing.kurtosis_review_scan", "Main_App.processing.preprocess"):
        target = logging.getLogger(name)
        target.setLevel(logging.INFO)
        target.addHandler(_ReviewTimingHandler())


def _send_control_message(message: dict[str, Any]) -> None:
    """Safety requests cannot be discarded with best-effort progress logging."""
    while not _WORKER_CANCEL.is_set():
        try:
            _WORKER_MESSAGES.put(message, timeout=0.1)
            return
        except Full:
            continue
    raise InterruptedError("Preparation cancelled while requesting memory admission.")


def _request_scoring_admission(index: int, *shape) -> None:
    required = actual_scoring_bytes(*shape)
    if required <= _WORKER_CREDITS[index] and not _WORKER_EXCLUSIVE[index]:
        return
    process = psutil.Process()
    _send_control_message({"type": "memory_request", "job_index": index,
                           "required_bytes": required, "pid": process.pid, "created": process.create_time()})
    while not _WORKER_CANCEL.is_set():
        if _WORKER_GRANT_EVENTS[index].wait(0.1):
            if _WORKER_GRANT_STATUS[index] != 1:
                if _WORKER_GRANT_STATUS[index] == -2:
                    raise MemoryError(
                        f"Actual scoring memory ({required} bytes plus worker/host reserve) exceeds "
                        "physical host capacity. Use a larger-memory host or reduce the recording scope."
                    )
                raise MemoryError("Actual scoring geometry exceeds its safe preparation memory reservation.")
            return
    raise InterruptedError("Preparation cancelled while awaiting memory admission.")


def _run_one_review(
    info: Any, settings: dict[str, Any], event_map: dict[str, int],
    reviewed_event_plans_by_file: Mapping[str, Any] | None,
    raw_channel_qc_by_recording: Mapping[str, Mapping[str, object]] | None,
    job_index: int | None = None,
) -> KurtosisReviewScan:
    from Main_App.processing.kurtosis_review_scan import _scan_kurtosis_review_serial
    from Main_App.processing.prepared_fir import prepared_fir_scope
    from Main_App.workers import process_runner

    callback = None
    if job_index is not None and _WORKER_GRANT_EVENTS is not None:
        process = psutil.Process()
        _send_control_message({"type": "worker_started", "job_index": job_index,
                               "pid": process.pid, "created": process.create_time()})
        def callback(*shape):
            _request_scoring_admission(job_index, *shape)

    with prepared_fir_scope(process_runner._WORKER_FIR_CACHE):
        return _scan_kurtosis_review_serial(
            [info], settings, event_map=event_map,
            reviewed_event_plans_by_file=reviewed_event_plans_by_file,
            raw_channel_qc_by_recording=raw_channel_qc_by_recording,
            progress=lambda message, _done, _total: _emit_worker_message({
                "type": "progress", "message": message,
            }),
            should_cancel=_WORKER_CANCEL.is_set,
            **({"before_kurtosis_scoring": callback} if callback is not None else {}),
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

    Live first-fit submission reserves unallocated physical and committed
    memory from geometry, including one emergency full-rate scorer. Unknown
    sources retain the exclusive legacy fallback. Cancellation stops new work
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
    resource_plan = _review_resource_plan(infos, requested_workers, settings=settings)
    worker_ceiling = worker_count = resource_plan.max_workers
    geometry_admission = resource_plan.dynamic and (
        any(estimate is not None for estimate in resource_plan.estimates)
        or any(resource_plan.exclusive)
    )
    child_settings = dict(settings)
    # This runtime callback is replaced by the child-owned cancellation event.
    child_settings.pop("_fpvs_kurtosis_checkpoint_should_cancel", None)
    context = get_context("spawn")
    cancel_event = context.Event()
    messages = context.Queue(maxsize=256)
    grant_events = [context.Event() for _ in infos] if resource_plan.dynamic else None
    grant_status = context.Array("b", [0] * len(infos)) if resource_plan.dynamic else None
    pool: Any = None
    futures: dict[Any, int] = {}
    indexed_results: dict[int, tuple[KurtosisReviewFileResult, ...]] = {}
    pending_indices = list(range(len(infos)))
    reserved_credits = 0
    peak_reserved_credits = 0
    peak_in_flight = 0
    oversize_fallbacks = 0
    completed = 0
    started = perf_counter()
    cancelled = False
    known_workers: dict[int, tuple[float, int]] = {}
    active_credits: dict[int, int] = {}
    resource_requests: dict[int, dict] = {}
    emergency_owner: int | None = None
    solo_owner: int | None = None
    growth_drain = False
    memory_paused = False
    peak_pool_workers = 0
    pool_starts = 0
    logger.info(
        "kurtosis_review_process_started files=%d max_workers=%d memory_budget_bytes=%d "
        "dynamic_memory=%s emergency_reserve_bytes=%d",
        len(infos), worker_count, resource_plan.budget_bytes, resource_plan.dynamic, resource_plan.emergency_bytes,
    )

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
            elif message.get("type") in {"worker_started", "memory_request"}:
                index = message["job_index"]
                if index not in active_credits:
                    continue
                known_workers[int(message["pid"])] = (float(message["created"]), index)
                if message["type"] == "memory_request":
                    resource_requests[index] = message

    def memory_snapshot():
        try:
            snapshot = probe_memory_snapshot()
        except (AttributeError, OSError, OverflowError, RuntimeError, TypeError, ValueError, psutil.Error) as exc:
            raise ReviewMemoryProbeError("Live preparation memory availability could not be read.") from exc
        if snapshot.commit_required and snapshot.commit_available_bytes is None:
            raise ReviewMemoryProbeError("Windows commit headroom is unavailable; preparation admission stopped.")
        return snapshot

    def memory_wait(message: str | None) -> None:
        nonlocal memory_paused
        if message is None:
            if not memory_paused:
                return
            message = "Preparation memory is available; resuming evidence preparation."
            memory_paused = False
        elif memory_paused:
            return
        else:
            memory_paused = True
        logger.info("kurtosis_review_memory_pressure message=%s", message)
        if progress is not None:
            progress(message, completed, len(infos))

    def emergency_for(indices) -> int:
        if not geometry_admission:
            return resource_plan.emergency_bytes
        return max((
            resource_plan.emergency_bytes if resource_plan.estimates[index] is None
            else resource_plan.estimates[index].emergency_extra_bytes
            for index in indices if index != solo_owner
        ), default=0)

    def live_fits(candidate_credit=0, *, candidate_index=None, granting_index=None,
                  granting_credit=None, population=None, snapshot=None) -> bool:
        credits = dict(active_credits)
        if granting_index is not None:
            credits[granting_index] = granting_credit
        reserve_index = granting_index if granting_index is not None else emergency_owner
        borrowed_bytes = (
            max(0, credits[reserve_index] - resource_plan.credits[reserve_index])
            if reserve_index is not None else 0
        )
        indices = set(credits)
        if candidate_index is not None:
            indices.add(candidate_index)
        emergency_remaining = max(0, emergency_for(indices) - borrowed_bytes)
        active_owned, idle_owned = {}, []
        for pid, (created, index) in known_workers.items():
            owner = probe_owned_memory(pid, created)
            if index in credits:
                active_owned[index] = owner
            else:
                idle_owned.append(owner)
        snapshot = memory_snapshot() if snapshot is None else snapshot
        try:
            return memory_admission_fits(
                snapshot, active_credits=credits, active_owned=active_owned,
                # A completed future can precede its worker-start message on
                # the separate control queue. Keep all pool floors reserved
                # even before those persistent idle owners are identified.
                idle_owned=idle_owned, worker_count=worker_count if population is None else population,
                candidate_credit=candidate_credit,
                emergency_reserve=emergency_remaining,
            )
        except (AttributeError, OSError, OverflowError, RuntimeError, TypeError, ValueError, psutil.Error):
            return False

    def grant_waiting_requests() -> None:
        nonlocal emergency_owner, reserved_credits, peak_reserved_credits
        if check_cancel() or emergency_owner is not None:
            return
        for index, request in list(resource_requests.items()):
            required = request["required_bytes"]
            estimate = resource_plan.estimates[index] if resource_plan.estimates else None
            covered_extra = resource_plan.emergency_bytes if estimate is None else estimate.emergency_extra_bytes
            if (type(required) is not int or required <= 0
                    or (not resource_plan.exclusive[index]
                        and required > resource_plan.credits[index] + covered_extra)):
                grant_status[index] = -1
                grant_events[index].set()
                del resource_requests[index]
                logger.error("review_scoring_uncovered_geometry index=%d requested_bytes=%s", index, required)
                continue
            snapshot = memory_snapshot()
            if single_review_capacity_bytes(snapshot, required) > snapshot.total_bytes:
                grant_status[index] = -2
                grant_events[index].set()
                del resource_requests[index]
                logger.error("review_scoring_capacity_exceeded index=%d requested_bytes=%d total_bytes=%d",
                             index, required, snapshot.total_bytes)
                continue
            if not live_fits(granting_index=index, granting_credit=required, snapshot=snapshot):
                memory_wait("Waiting for preparation memory before actual scoring; free background RAM/commit or cancel.")
                continue
            emergency_owner = index
            reserved_credits += required - active_credits[index]
            active_credits[index] = required
            peak_reserved_credits = max(peak_reserved_credits, reserved_credits)
            grant_status[index] = 1
            grant_events[index].set()
            del resource_requests[index]
            memory_wait(None)
            logger.info("review_scoring_emergency_granted index=%d credit_bytes=%d", index, required)
            return

    def accept(index: int, results: tuple[KurtosisReviewFileResult, ...]) -> None:
        nonlocal completed
        indexed_results[index] = results
        completed += len(results)
        if result_progress is not None and results:
            result_progress(index, results)
        if progress is not None and results:
            progress(f"Finished kurtosis review scan for {Path(infos[index].path).name}", completed, len(infos))

    def start_pool(population: int) -> None:
        nonlocal pool, worker_count, peak_pool_workers, pool_starts
        worker_count = population
        pool = ProcessPoolExecutor(
            max_workers=worker_count, mp_context=context,
            initializer=_review_worker_init,
            initargs=(cancel_event, messages, grant_events, grant_status, resource_plan.credits, resource_plan.exclusive)
            if resource_plan.dynamic else (cancel_event, messages),
        )
        peak_pool_workers = max(peak_pool_workers, population)
        pool_starts += 1
        logger.info("kurtosis_review_pool_started max_workers=%d worker_ceiling=%d", population, worker_ceiling)

    def close_idle_pool() -> None:
        nonlocal pool
        if futures or active_credits:
            raise RuntimeError("A preparation pool can be resized only after all jobs release their owners.")
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
            pool = None
            drain_messages()
            known_workers.clear()

    def prepare_idle_pool() -> None:
        """Resize only a drained executor; all live populations keep their floors."""
        nonlocal solo_owner, growth_drain
        if futures or not pending_indices or not geometry_admission:
            return
        growth_drain = False
        solo_owner = None
        snapshot = memory_snapshot()
        for index in tuple(pending_indices):
            estimate = resource_plan.estimates[index]
            if estimate is not None and single_review_capacity_bytes(snapshot, estimate.healthy_bytes) > snapshot.total_bytes:
                pending_indices.remove(index)
                accept(index, (_failure_result(infos[index], MemoryError(
                    "Validated preparation memory plus one worker/host reserve exceeds physical host capacity; "
                    "use a larger-memory host or reduce the recording scope."
                )),))
        if not pending_indices:
            return

        def ordinary_fits(index, population):
            return (not resource_plan.exclusive[index]
                    and live_fits(resource_plan.credits[index], candidate_index=index,
                                  population=population, snapshot=snapshot))

        if pool is not None:
            if (worker_count < min(worker_ceiling, len(pending_indices))
                    and any(ordinary_fits(index, worker_count + 1) for index in pending_indices)):
                close_idle_pool()
                snapshot = memory_snapshot()
            elif any(ordinary_fits(index, worker_count) for index in pending_indices):
                return
            elif worker_count == 1:
                # Keep healthy work moving without reserving an unrequested
                # hypothetical full-rate allocation. This pool runs only solo.
                index = next((index for index in pending_indices
                              if live_fits(resource_plan.credits[index], snapshot=snapshot)), None)
                if index is not None:
                    solo_owner = index
                    return
                close_idle_pool()
                snapshot = memory_snapshot()
            else:
                close_idle_pool()
                snapshot = memory_snapshot()

        for population in range(worker_ceiling, 0, -1):
            if any(ordinary_fits(index, population) for index in pending_indices):
                start_pool(population)
                return
        # A healthy singleton can run even when hypothetical full-rate scoring
        # cannot currently fit. Its exact request precedes the larger allocation.
        index = next((index for index in pending_indices
                      if live_fits(resource_plan.credits[index], population=1, snapshot=snapshot)), None)
        if index is not None:
            solo_owner = index
            start_pool(1)
        else:
            # Uncharacterized sources retain the existing exclusive native
            # scanner fallback, never an oversized parallel population.
            index = next((index for index in pending_indices if resource_plan.exclusive[index]), None)
            if index is not None:
                solo_owner = index
                start_pool(1)
            else:
                memory_wait("Waiting for preparation memory; free background RAM/commit or cancel.")

    def submit_available() -> None:
        nonlocal reserved_credits, peak_reserved_credits, peak_in_flight, oversize_fallbacks, growth_drain
        if check_cancel():
            return
        prepare_idle_pool()
        if geometry_admission:
            grant_waiting_requests()
        if (not growth_drain and geometry_admission and futures and pool is not None
                and len(futures) < worker_count and not resource_requests
                and worker_count < min(worker_ceiling, len(pending_indices))
                and any(not resource_plan.exclusive[index]
                        and live_fits(resource_plan.credits[index], candidate_index=index,
                                      population=worker_count + 1)
                        for index in pending_indices)):
            growth_drain = True
            logger.info("kurtosis_review_pool_draining_for_growth current_workers=%d worker_ceiling=%d",
                        worker_count, worker_ceiling)
        if growth_drain:
            return
        while pending_indices and pool is not None and len(futures) < worker_count and not check_cancel():
            if resource_plan.dynamic:
                grant_waiting_requests()
                if (resource_requests or solo_owner in active_credits
                        or any(resource_plan.exclusive[i] for i in active_credits)):
                    return
                if solo_owner in pending_indices:
                    index = solo_owner
                    if (not resource_plan.exclusive[index]
                            and not live_fits(resource_plan.credits[index], candidate_index=index)):
                        memory_wait("Waiting for preparation memory; free background RAM/commit or cancel.")
                        return
                else:
                    index = next((candidate for candidate in pending_indices
                                  if not resource_plan.exclusive[candidate]
                                  and live_fits(resource_plan.credits[candidate], candidate_index=candidate)), None)
            else:
                index = next((candidate for candidate in pending_indices
                              if reserved_credits + resource_plan.credits[candidate] <= resource_plan.budget_bytes), None)
            if index is None:
                if futures:
                    return
                # Make progress on a single oversized or unstatable source,
                # preserving the existing constrained-host serial fallback.
                if resource_plan.dynamic and not resource_plan.exclusive[pending_indices[0]]:
                    return
                index = pending_indices[0]
            pending_indices.remove(index)
            memory_wait(None)
            credit = resource_plan.credits[index]
            try:
                future = pool.submit(
                    _run_one_review, infos[index], child_settings, dict(event_map),
                    reviewed_event_plans_by_file, raw_channel_qc_by_recording,
                    **({"job_index": index} if resource_plan.dynamic else {}),
                )
            except Exception as exc:
                accept(index, (_failure_result(infos[index], exc),))
            else:
                futures[future] = index
                active_credits[index] = credit
                reserved_credits += credit
                peak_reserved_credits = max(peak_reserved_credits, reserved_credits)
                peak_in_flight = max(peak_in_flight, len(futures))
                if credit > resource_plan.budget_bytes:
                    oversize_fallbacks += 1
                logger.debug(
                    "kurtosis_review_process_submitted index=%d in_flight=%d reserved_bytes=%d budget_bytes=%d",
                    index, len(futures), reserved_credits, resource_plan.budget_bytes,
                )

    try:
        if progress is not None:
            progress(f"Preparing kurtosis evidence with up to {worker_count} process worker(s)", 0, len(infos))
        if not geometry_admission:
            start_pool(worker_count)
        submit_available()
        while futures or pending_indices:
            if check_cancel():
                for future in futures:
                    future.cancel()
                if not futures:
                    break
            drain_messages()
            grant_waiting_requests()
            if not futures:
                cancel_event.wait(0.1)
            done, _pending = wait(futures, timeout=0.1, return_when=FIRST_COMPLETED)
            for future in done:
                index = futures.pop(future)
                reserved_credits -= active_credits.pop(index)
                resource_requests.pop(index, None)
                if emergency_owner == index:
                    emergency_owner = None
                if solo_owner == index:
                    solo_owner = None
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
                "kurtosis_review_process_finished files=%d completed=%d max_workers=%d elapsed_seconds=%.3f cancelled=%s "
                "memory_budget_bytes=%d peak_reserved_bytes=%d peak_in_flight=%d oversize_fallbacks=%d "
                "peak_pool_workers=%d pool_starts=%d",
                len(infos), completed, worker_ceiling, perf_counter() - started, cancelled,
                resource_plan.budget_bytes, peak_reserved_credits, peak_in_flight, oversize_fallbacks,
                peak_pool_workers, pool_starts,
            )
    return KurtosisReviewScan(
        tuple(result for index in sorted(indexed_results) for result in indexed_results[index]),
        cancelled=cancelled,
    )


__all__ = ["review_process_worker_count", "run_process_review"]

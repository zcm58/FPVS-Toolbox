"""Ordered per-derivative source inverses using reusable native MNE workers."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ProcessPoolExecutor, wait
from contextlib import ExitStack, contextmanager
from dataclasses import replace
import logging
from multiprocessing import get_context
import os
import pickle
from time import perf_counter

import psutil

from Main_App.workers.mp_env import compute_dynamic_worker_ceiling, project_worker_override
from Main_App.workers.review_resource_budget import probe_memory_snapshot
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import compute_hauk_source_psd
from Tools.LORETA_Visualizer.source_producers.model_diagnostics import summarize_recorded_data_rank
from Tools.LORETA_Visualizer.source_producers.native_psd_cells import CellOutcome, MethodContext, WorkerContext
from Tools.LORETA_Visualizer.source_producers.project_time_domain_inputs import load_project_time_domain_raw
from Tools.LORETA_Visualizer.source_producers.source_psd_cache import (
    CACHE_STATUS_HIT,
    CACHE_STATUS_MISS_NOT_FOUND,
    SourcePsdCacheKeyInputs,
    _load_prepared_source_psd_entry,
    store_source_psd_cache_entry,
)

logger = logging.getLogger(__name__)
_GIB = 1024**3
_native_geometry = None
_native_worker_context = None


def _compute(record, info, inverse, config, compute_source_psd_func=None, apply_inverse_func=None):
    with load_project_time_domain_raw(record) as raw:
        rank = summarize_recorded_data_rank(raw, expected_info=info)
        result = compute_hauk_source_psd(
            averaged_raw=raw, inverse_operator=inverse, config=config,
            compute_source_psd_func=compute_source_psd_func, apply_inverse_func=apply_inverse_func,
        )
    return rank, result


def _start_worker(info, inverse, config, parent_limits, launch_gate, log_level=None, cell_context=None):
    import mne
    import scipy.linalg  # noqa: F401 - register LAPACK/BLAS before restoring its thread count
    from threadpoolctl import ThreadpoolController

    global _native_geometry, _native_worker_context
    _native_geometry = info, inverse, config
    libraries = ThreadpoolController()
    for path, count in parent_limits:
        libraries.select(filepath=path).limit(limits=count)
    mne.set_log_level(log_level)
    _native_worker_context = WorkerContext(cell_context, info, inverse, config) if cell_context is not None else None
    if launch_gate is not None:
        launch_gate.wait(timeout=120)


def _native_cell(job):
    started = perf_counter()
    if _native_worker_context is None:
        result = _compute(job, *_native_geometry)
    else:
        record, may_read = job
        result = _native_worker_context.run(record, may_read, lambda: _compute(record, *_native_geometry))
    return os.getpid(), started, perf_counter(), result


def _batch_capacity(ceiling, records, sources, config, frequencies, model_bytes):
    if ceiling <= 1:
        return 1
    samples = max(record.n_times for record in records)
    channels = max(len(record.channel_names) for record in records)
    # Double-precision input, finite/rank checks, FFT and numerical LAPACK work.
    # Each admitted process owns a Python/MNE runtime, copied native model
    # matrices and IPC scratch in addition to the waveform workspaces.
    credit = _GIB + 3 * model_bytes + 256 * sources * channels + 128 * channels * samples
    if config.source_orientation_mode == "vector_norm":
        # Three complex inverse components, norms and intermediate arrays at
        # precisely the selected target/noise bins.
        credit += 256 * sources * len(frequencies["required_bin_indices"])
    else:
        # MNE's scalar Hann estimator transforms the complete one-sided
        # frequency grid before masking it. Include dot and PSD temporaries.
        credit += 64 * sources * (samples // 2 + 1)
    try:
        memory = probe_memory_snapshot()
    except (OSError, RuntimeError, ValueError, psutil.Error):
        return 1
    free = memory.physical_available_bytes
    if type(free) is not int or free < 0 or type(memory.total_bytes) is not int or memory.total_bytes <= 0:
        return 1
    if memory.commit_required:
        if type(memory.commit_available_bytes) is not int or memory.commit_available_bytes < 0:
            return 1
        free = min(free, memory.commit_available_bytes)
    free -= max(_GIB, memory.total_bytes // 16)
    return max(1, min(ceiling, free // credit))


def _model_size(info, inverse, config):
    # Protocol 5 exposes NumPy and sparse backing arrays without materializing
    # a second large model merely to estimate the cost of spawning a process.
    sizes = []

    def count_buffer(buffer):
        sizes.append(buffer.raw().nbytes)

    return len(pickle.dumps((info, inverse, config), protocol=5, buffer_callback=count_buffer)) + sum(sizes)


@contextmanager
def source_psd_cells(
    records, *, project, root, model, config, numerical_metadata, method_metadata,
    frequency_metadata, before_record, cancellation_callback=None, compute_source_psd_func=None, apply_inverse_func=None,
    native_model=False, completed_cell_callback=None,
):
    """Yield ordered results and report progress after the caller accepts each cell."""
    requested = project_worker_override(getattr(project, "preprocessing", None), getattr(project, "options", None))
    ceiling = compute_dynamic_worker_ceiling(requested)
    if compute_source_psd_func is not None or apply_inverse_func is not None:
        # Custom callables can be stateful and have no verified concurrent contract.
        ceiling = 1
    sources = len(model.forward_model.source_points)

    def iterate(resources):
        pool = None
        can_attest = native_model and compute_source_psd_func is None and apply_inverse_func is None
        cell_context = None
        serial_context = None
        used_processes = set()
        intervals = []
        model_size = None
        index = 0
        pool_ceiling = ceiling
        rows = deque()
        keys = set()
        futures = {}
        lookup_error = None
        total = len(records)
        if completed_cell_callback is not None:
            completed_cell_callback(0, total)
        while index < total:
            window = records[index:index + pool_ceiling]
            if len(window) > 1 and model_size is None:
                try:
                    model_size = _model_size(model.info, model.inverse_operator, config)
                except (AttributeError, TypeError, pickle.PicklingError):
                    # A supplied model can still run in its caller's process.
                    pool_ceiling = 1
                    window = window[:1]
            capacity = _batch_capacity(len(window), window, sources, config, frequency_metadata, model_size)
            misses = []
            if lookup_error is None:
                for record in window[len(rows):capacity]:
                    try:
                        key = SourcePsdCacheKeyInputs(
                            record.fif_sha256, numerical_metadata, method_metadata, frequency_metadata,
                        )
                        prepared = key._prepare()
                        digest = prepared.digest
                        if digest in keys:
                            break  # Commit the previous same-key result before looking up this record.
                        lookup = _load_prepared_source_psd_entry(project_root=root, prepared=prepared)
                    except Exception as error:
                        lookup_error = error
                        break
                    keys.add(digest)
                    rows.append((record, key, digest, lookup))
                    if not lookup.hit:
                        misses.append((digest, record, lookup))
            if not rows:
                before_record(index + 1, records[index])
                raise lookup_error

            launch_gate = None
            if misses and can_attest:
                cell_context = MethodContext.from_settings(root, numerical_metadata, method_metadata, frequency_metadata)
                can_attest = False
            if pool is None and len(misses) > 1:
                from threadpoolctl import threadpool_info

                context = get_context("spawn")
                if len(records) - index >= 2 * capacity and len(misses) == capacity:
                    # For a long cold run, admit the initial wave before allowing
                    # a fast first task to keep the Windows executor at one child.
                    launch_gate = context.Event()
                limits = [(lib["filepath"], lib["num_threads"]) for lib in threadpool_info()]
                pool = ProcessPoolExecutor(
                    max_workers=ceiling, mp_context=context, initializer=_start_worker,
                    initargs=(model.info, model.inverse_operator, config, limits, launch_gate,
                              logging.getLogger("mne").getEffectiveLevel(), cell_context),
                )
                resources.callback(pool.shutdown, wait=True, cancel_futures=True)
                logger.info("source_psd_workers_started ceiling=%d admitted=%d", ceiling, len(misses))
            if pool is not None and capacity > 1:
                try:
                    for digest, record, missed in misses:
                        if cancellation_callback is not None:
                            cancellation_callback()
                        job = record if cell_context is None else (record, missed.status == CACHE_STATUS_MISS_NOT_FOUND)
                        futures[digest] = pool.submit(_native_cell, job)
                finally:
                    if launch_gate is not None:
                        launch_gate.set()

            record, key, digest, lookup = rows.popleft()
            before_record(index + 1, record)
            result = None
            if not lookup.hit:
                future = futures.pop(digest, None)
                if future is None:
                    def calculate():
                        return _compute(record, model.info, model.inverse_operator, config,
                                        compute_source_psd_func, apply_inverse_func)

                    if cell_context is None:
                        result = calculate()
                    else:
                        if serial_context is None:
                            serial_context = WorkerContext(cell_context, model.info, model.inverse_operator, config)
                        result = serial_context.run(record, lookup.status == CACHE_STATUS_MISS_NOT_FOUND, calculate)
                else:
                    if cancellation_callback is not None:
                        while not future.done():
                            cancellation_callback()
                            wait((future,), timeout=0.2)
                    pid, start, finish, result = future.result()
                    used_processes.add(pid)
                    intervals.extend(((start, 1), (finish, -1)))
                if isinstance(result, CellOutcome):
                    if result.reused is not None:
                        store_source_psd_cache_entry(project_root=root, key_inputs=key, result=result.reused)
                        lookup = replace(lookup, status=CACHE_STATUS_HIT, result=result.reused,
                                         detail="Verified native participant cell")
                    elif result.native_key:
                        lookup = replace(lookup, native_cell_key=result.native_key)
                    result = result.computed
            yield record, key, lookup, result
            keys.remove(digest)
            index += 1
            if completed_cell_callback is not None:
                completed_cell_callback(index, total)
        if pool is not None:
            active = peak = 0
            for _, delta in sorted(intervals):
                active += delta
                peak = max(peak, active)
            logger.info("source_psd_workers_finished ceiling=%d processes_used=%d peak_overlapping_cells=%d",
                        ceiling, len(used_processes), peak)

    with ExitStack() as resources:
        yield iterate(resources)

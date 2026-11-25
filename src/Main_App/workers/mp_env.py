# -*- coding: utf-8 -*-
"""Helpers for configuring BLAS threading in different execution modes."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import os
import sys
from typing import Optional

import psutil

from Main_App.workers.linux_cgroup import cgroup_limits

# Legacy ceiling for callers without live memory admission.

GLOBAL_MAX_WORKERS = 20
_WINDOWS_PROCESS_POOL_MAX_WORKERS = 61
_worker_threadpool_limit = None


def project_worker_override(
    preprocessing: Mapping | None, options: Mapping | None = None,
) -> int | None:
    """Resolve the saved preprocessing limit, then the older project option."""
    preprocessing = preprocessing or {}
    value = next((preprocessing[key] for key in (
        "max_parallel_workers_override", "max_parallel_workers", "max_workers",
    ) if key in preprocessing), None)
    legacy = (options or {}).get("max_workers")
    for name, candidate in (("max_parallel_workers_override", value), ("max_workers", legacy)):
        if candidate is None:
            continue
        try:
            workers = int(candidate)
        except (TypeError, ValueError, OverflowError):
            logging.getLogger(__name__).warning("Invalid %s worker limit: %r", name, candidate)
            continue
        if workers > 0:
            return workers
    return None


def compute_dynamic_worker_ceiling(
    project_max_workers: int | None = None, *, cpu_count: int | None = None,
    total_ram_bytes: int | None = None,
) -> int:
    """Choose a worker ceiling from the RAM tier, available CPUs, and project setting.

    This is a population ceiling, not permission to start that many jobs. Each
    caller must separately admit work against fresh RAM and commit headroom.
    """
    # When both inputs are supplied the caller has already resolved the usable
    # CPU and RAM envelope (also useful for a deterministic policy preview).
    quota_cpus, quota_memory, _ = (
        cgroup_limits() if cpu_count is None or total_ram_bytes is None else (None, None, None)
    )
    if cpu_count is None:
        usable = []
        try:
            count = getattr(os, "process_cpu_count", os.cpu_count)()
            if type(count) is int and count > 0:
                usable.append(count)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            pass
        try:
            affinity = psutil.Process().cpu_affinity()
            if affinity:
                usable.append(len(affinity))
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError, psutil.Error):
            pass
        if usable:
            cpu_count = min(usable)
        else:
            try:
                cpu_count = os.cpu_count()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                cpu_count = 1
    available = cpu_count if type(cpu_count) is int and cpu_count > 0 else 1
    if quota_cpus is not None:
        available = min(available, quota_cpus)
    ceiling = max(1, available - 1)
    # ProcessPoolExecutor's documented Windows limit also bounds shared EEG
    # ceilings used by threads, so a later process stage can use the same value.
    if sys.platform == "win32":
        ceiling = min(ceiling, _WINDOWS_PROCESS_POOL_MAX_WORKERS)
    if total_ram_bytes is None:
        try:
            total_ram_bytes = int(psutil.virtual_memory().total)
        except (AttributeError, OSError, OverflowError, RuntimeError, TypeError, ValueError, psutil.Error):
            return 1
    if quota_memory is not None:
        total_ram_bytes = min(total_ram_bytes, quota_memory)
    if total_ram_bytes <= 0:
        return 1
    _, tier_cap, _ = get_ram_tier_recommendation(total_ram_bytes)
    if tier_cap == 1:
        return 1
    if project_max_workers is None or type(project_max_workers) is int and project_max_workers == 0:
        return min(ceiling, tier_cap) if tier_cap is not None else ceiling
    if type(project_max_workers) is not int or project_max_workers < 1:
        return 1
    return min(ceiling, project_max_workers)


def get_ram_tier_recommendation(total_ram_bytes: int) -> tuple[str, Optional[int], float]:
    """
    Return ``(tier_label, recommended_cap, total_ram_gib)`` from host RAM.

    The 8 GB tier always caps the pool at one. Other recommendations set the
    automatic ceiling. ``None`` means usable CPUs alone set the automatic ceiling.
    """

    total_ram_gib = total_ram_bytes / float(1024 ** 3) if total_ram_bytes > 0 else 0.0

    if total_ram_gib < 12.0:
        return "8GB", 1, total_ram_gib
    if total_ram_gib < 20.0:
        return "16GB", 4, total_ram_gib
    if total_ram_gib < 40.0:
        return "32GB", 4, total_ram_gib
    if total_ram_gib < 80.0:
        return "64GB", 7, total_ram_gib
    if total_ram_gib < 140.0:
        return "128GB", 16, total_ram_gib
    return "140GB+", None, total_ram_gib


def set_blas_threads_single_process() -> None:
    """Allow BLAS to use many threads in single-process mode."""
    cores = os.cpu_count() or 1
    os.environ.setdefault("MKL_NUM_THREADS", str(cores))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", str(cores))
    os.environ.setdefault("OMP_NUM_THREADS", str(cores))
    os.environ.setdefault("NUMEXPR_NUM_THREADS", str(max(1, cores // 2)))

def set_blas_threads_multiprocess() -> None:
    """Set limits for numerical libraries loaded later in a worker process."""
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"


def set_worker_thread_limits() -> None:
    """Limit already-loaded pools for the lifetime of a spawned worker only."""
    from threadpoolctl import threadpool_limits

    global _worker_threadpool_limit
    set_blas_threads_multiprocess()
    # Spawn imports the processing module (and NumPy/SciPy) before initializer.
    # Environment variables alone cannot reconfigure those existing pools.
    _worker_threadpool_limit = threadpool_limits(limits=1)
    numexpr = sys.modules.get("numexpr")
    if numexpr is not None:
        numexpr.set_num_threads(1)


def compute_effective_max_workers(
        total_ram_bytes: int,
        cpu_count: int,
        project_max_workers: Optional[int],
        allow_ram_cap_bypass: bool = False,
) -> int:
    """Return a worker count capped by CPU availability and RAM tiers."""

    cores = cpu_count if cpu_count and cpu_count > 0 else 1
    cpu_cap = max(1, cores - 1)
    _tier, ram_cap, _ram_gib = get_ram_tier_recommendation(total_ram_bytes)
    if ram_cap == 1:
        return 1

    if project_max_workers is not None and project_max_workers > 0:
        desired = project_max_workers
    else:
        desired = cpu_cap

    if ram_cap is None or allow_ram_cap_bypass:
        effective = min(desired, cpu_cap)
    else:
        effective = min(desired, cpu_cap, ram_cap)

    effective = min(effective, GLOBAL_MAX_WORKERS)

    return max(1, effective)

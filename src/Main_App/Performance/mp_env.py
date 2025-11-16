"""Helpers for configuring BLAS threading in different execution modes."""

from __future__ import annotations

import os
from typing import Optional


GLOBAL_MAX_WORKERS = 8


def set_blas_threads_single_process() -> None:
    """Allow BLAS to use many threads in single-process mode."""
    cores = os.cpu_count() or 1
    os.environ.setdefault("MKL_NUM_THREADS", str(cores))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", str(cores))
    os.environ.setdefault("OMP_NUM_THREADS", str(cores))
    os.environ.setdefault("NUMEXPR_NUM_THREADS", str(max(1, cores // 2)))


def set_blas_threads_multiprocess() -> None:
    """Restrict BLAS to one thread per worker process."""
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"


def compute_effective_max_workers(
    total_ram_bytes: int,
    cpu_count: int,
    project_max_workers: Optional[int],
) -> int:
    """Return a worker count capped by CPU availability and RAM tiers."""

    cores = cpu_count if cpu_count and cpu_count > 0 else 1
    cpu_cap = max(1, cores - 1)

    total_ram_gib = total_ram_bytes / float(1024 ** 3) if total_ram_bytes > 0 else 0.0
    ram_cap: Optional[int]
    if 14.0 <= total_ram_gib <= 18.0:
        ram_cap = 4
    elif 28.0 <= total_ram_gib <= 36.0:
        ram_cap = 5
    elif 56.0 <= total_ram_gib <= 72.0:
        ram_cap = 6
    else:
        ram_cap = None

    if project_max_workers is not None and project_max_workers > 0:
        desired = project_max_workers
    else:
        desired = cpu_cap

    if ram_cap is None:
        effective = min(desired, cpu_cap)
    else:
        effective = min(desired, cpu_cap, ram_cap)

    effective = min(effective, GLOBAL_MAX_WORKERS)

    return max(1, effective)


# -*- coding: utf-8 -*-
"""Helpers for configuring BLAS threading in different execution modes."""

from __future__ import annotations

import os
from typing import Optional

# Hard cap of 20 parallel workers on 128GB + workstations

GLOBAL_MAX_WORKERS = 20


def get_ram_tier_recommendation(total_ram_bytes: int) -> tuple[str, Optional[int], float]:
    """
    Return ``(tier_label, recommended_cap, total_ram_gib)`` from host RAM.

    ``recommended_cap`` is the hardcoded safety recommendation used for automatic
    worker selection. ``None`` means no RAM-tier cap applies.
    """

    total_ram_gib = total_ram_bytes / float(1024 ** 3) if total_ram_bytes > 0 else 0.0

    # Set your desired number of max parallel workers based on the amount of RAM
    if total_ram_gib < 12.0:
        return "8GB", 2, total_ram_gib
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
    """Restrict BLAS to one thread per worker process."""
    os.environ["MKL_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["NUMEXPR_NUM_THREADS"] = "1"


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

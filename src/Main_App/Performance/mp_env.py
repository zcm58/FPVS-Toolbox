# -*- coding: utf-8 -*-
"""Helpers for configuring BLAS threading in different execution modes."""

from __future__ import annotations

import os
from typing import Optional

# Increased from 8 to 16 to allow future-proofing for workstations (128GB+),
# while still preventing excessive Python process overhead.
GLOBAL_MAX_WORKERS = 16


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

    # CUMULATIVE LOGIC:
    # Uses '<' to ensure no gaps. Any system falls into the safest lower tier.

    if total_ram_gib < 12.0:
        # 8GB Tier (and below):
        # Windows/OS uses ~3GB. Leaving ~5GB. 2 workers is the safe max.
        ram_cap = 4
    elif total_ram_gib < 20.0:
        # 16GB Tier (covers 12GB-19GB): Your setting.
        ram_cap = 4
    elif total_ram_gib < 40.0:
        # 32GB Tier (covers 24GB-39GB): Your setting.
        ram_cap = 6
    elif total_ram_gib < 80.0:
        # 64GB Tier (covers 40GB-79GB): Your setting.
        ram_cap = 7
    elif total_ram_gib < 140.0:
        # 128GB Tier (covers 80GB-139GB):
        # With this much RAM, we can safely double the 64GB cap.
        ram_cap = 12
    else:
        # >140GB (e.g. 192GB, 256GB):
        # No strict RAM limit needed; fallback to CPU cap or Global limit.
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
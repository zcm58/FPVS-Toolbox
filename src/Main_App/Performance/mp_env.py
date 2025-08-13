from __future__ import annotations

"""Helpers for configuring BLAS threading in different execution modes."""

import os


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


"""Utilities for constraining BLAS thread usage during stats runs."""

from __future__ import annotations

from contextlib import contextmanager
import importlib.util

_tp_spec = importlib.util.find_spec("threadpoolctl")
if _tp_spec is not None:  # pragma: no cover - optional dependency at runtime
    from threadpoolctl import threadpool_limits
else:  # pragma: no cover - optional dependency at runtime
    threadpool_limits = None  # type: ignore[assignment]


@contextmanager
def single_threaded_blas():
    """Force BLAS to use a single thread within this context, if supported."""

    if threadpool_limits is None:
        yield
    else:
        with threadpool_limits(limits=1):
            yield


__all__ = ["single_threaded_blas"]

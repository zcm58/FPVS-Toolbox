"""Canonical Main App worker import surface."""

from __future__ import annotations

from typing import Any

__all__ = [
    "MpRunnerBridge",
    "PostProcessWorker",
    "RunParams",
    "run_project_parallel",
]


def __getattr__(name: str) -> Any:
    if name == "MpRunnerBridge":
        from Main_App.workers.mp_runner_bridge import MpRunnerBridge

        return MpRunnerBridge
    if name == "PostProcessWorker":
        from Main_App.workers.processing_worker import PostProcessWorker

        return PostProcessWorker
    if name in {"RunParams", "run_project_parallel"}:
        from Main_App.workers import process_runner

        return getattr(process_runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

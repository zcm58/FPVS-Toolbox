"""Canonical Main App worker import surface."""

from __future__ import annotations

from typing import Any

__all__ = [
    "MpRunnerBridge",
    "PostProcessWorker",
    "PostProcessingPipelineWorker",
    "ProcessingHarmonicSelectionWorker",
    "RunParams",
    "run_postprocessing_from_selection",
    "run_project_parallel",
]


def __getattr__(name: str) -> Any:
    if name == "MpRunnerBridge":
        from Main_App.workers.mp_runner_bridge import MpRunnerBridge

        return MpRunnerBridge
    if name == "PostProcessWorker":
        from Main_App.workers.processing_worker import PostProcessWorker

        return PostProcessWorker
    if name in {"PostProcessingPipelineWorker", "run_postprocessing_from_selection"}:
        from Main_App.workers import post_processing_pipeline_worker

        return getattr(post_processing_pipeline_worker, name)
    if name == "ProcessingHarmonicSelectionWorker":
        from Main_App.workers.harmonic_selection_worker import (
            ProcessingHarmonicSelectionWorker,
        )

        return ProcessingHarmonicSelectionWorker
    if name in {"RunParams", "run_project_parallel"}:
        from Main_App.workers import process_runner

        return getattr(process_runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

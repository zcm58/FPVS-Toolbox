"""Shared types and constants for the Stats tool (support layer)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Final

from Main_App.projects.project import STATS_SUBFOLDER_NAME


class PipelineId(Enum):
    """Represent the PipelineId part of the Stats tool."""
    SINGLE = auto()


class StepId(Enum):
    """Represent the StepId part of the Stats tool."""
    RM_ANOVA = auto()
    MIXED_MODEL = auto()
    INTERACTION_POSTHOCS = auto()
    HARMONIC_CHECK = auto()
    BASELINE_VS_ZERO = auto()


RESULTS_SUBFOLDER_NAME: Final[str] = STATS_SUBFOLDER_NAME

ANOVA_XLS: Final[str] = "RM-ANOVA Results.xlsx"
LMM_XLS: Final[str] = "Mixed Model Results.xlsx"
POSTHOC_XLS: Final[str] = "Posthoc Results.xlsx"
HARMONIC_XLS: Final[str] = "Harmonic Results.xlsx"
BASELINE_VS_ZERO_XLS: Final[str] = "Baseline vs Zero Tests.xlsx"


@dataclass
class PipelineStep:
    """Represent the PipelineStep part of the Stats tool."""
    id: StepId
    name: str
    worker_fn: Callable[..., Any]
    kwargs: dict
    handler: Callable[[dict], None]


__all__ = [
    "PipelineId",
    "StepId",
    "RESULTS_SUBFOLDER_NAME",
    "ANOVA_XLS",
    "LMM_XLS",
    "POSTHOC_XLS",
    "HARMONIC_XLS",
    "BASELINE_VS_ZERO_XLS",
    "PipelineStep",
]

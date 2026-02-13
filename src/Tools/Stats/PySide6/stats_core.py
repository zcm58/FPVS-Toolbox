"""Shared types and constants for the Stats tool (support layer)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Final

from Main_App.PySide6_App.Backend.project import STATS_SUBFOLDER_NAME


class PipelineId(Enum):
    """Represent the PipelineId part of the Stats PySide6 tool."""
    SINGLE = auto()
    BETWEEN = auto()


class StepId(Enum):
    """Represent the StepId part of the Stats PySide6 tool."""
    RM_ANOVA = auto()
    MIXED_MODEL = auto()
    INTERACTION_POSTHOCS = auto()
    BETWEEN_GROUP_ANOVA = auto()
    BETWEEN_GROUP_MIXED_MODEL = auto()
    GROUP_CONTRASTS = auto()
    HARMONIC_CHECK = auto()


RESULTS_SUBFOLDER_NAME: Final[str] = STATS_SUBFOLDER_NAME

ANOVA_XLS: Final[str] = "RM-ANOVA Results.xlsx"
LMM_XLS: Final[str] = "Mixed Model Results.xlsx"
POSTHOC_XLS: Final[str] = "Posthoc Results.xlsx"
HARMONIC_XLS: Final[str] = "Harmonic Results.xlsx"
ANOVA_BETWEEN_XLS: Final[str] = "Mixed ANOVA Between Groups.xlsx"
LMM_BETWEEN_XLS: Final[str] = "Mixed Model Between Groups.xlsx"
GROUP_CONTRAST_XLS: Final[str] = "Group Contrasts.xlsx"


@dataclass
class PipelineStep:
    """Represent the PipelineStep part of the Stats PySide6 tool."""
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
    "ANOVA_BETWEEN_XLS",
    "LMM_BETWEEN_XLS",
    "GROUP_CONTRAST_XLS",
    "PipelineStep",
]

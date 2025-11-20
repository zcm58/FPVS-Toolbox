from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Callable, Final

from Main_App.PySide6_App.Backend.project import STATS_SUBFOLDER_NAME


class PipelineId(Enum):
    SINGLE = auto()
    BETWEEN = auto()


class StepId(Enum):
    RM_ANOVA = auto()
    MIXED_MODEL = auto()
    INTERACTION_POSTHOCS = auto()
    BETWEEN_GROUP_ANOVA = auto()
    BETWEEN_GROUP_MIXED_MODEL = auto()
    GROUP_CONTRASTS = auto()
    HARMONIC_CHECK = auto()


RESULTS_SUBFOLDER_NAME: Final[str] = STATS_SUBFOLDER_NAME


@dataclass
class PipelineStep:
    id: StepId
    name: str
    worker_fn: Callable[..., Any]
    kwargs: dict
    handler: Callable[[dict], None]


__all__ = [
    "PipelineId",
    "StepId",
    "RESULTS_SUBFOLDER_NAME",
    "PipelineStep",
]

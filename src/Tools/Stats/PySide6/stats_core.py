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
    BASELINE_VS_ZERO = auto()


RESULTS_SUBFOLDER_NAME: Final[str] = STATS_SUBFOLDER_NAME

ANOVA_XLS: Final[str] = "RM-ANOVA Results.xlsx"
LMM_XLS: Final[str] = "Mixed Model Results.xlsx"
POSTHOC_XLS: Final[str] = "Posthoc Results.xlsx"
HARMONIC_XLS: Final[str] = "Harmonic Results.xlsx"
ANOVA_BETWEEN_XLS: Final[str] = "Mixed ANOVA Between Groups.xlsx"
LMM_BETWEEN_XLS: Final[str] = "Mixed Model Between Groups.xlsx"
GROUP_CONTRAST_XLS: Final[str] = "Group Contrasts.xlsx"
BASELINE_VS_ZERO_XLS: Final[str] = "Baseline vs Zero Tests.xlsx"
MULTIGROUP_MIXED_MODEL_SHEET: Final[str] = "Mixed Model"
MULTIGROUP_GROUP_CONTRAST_COLUMNS: Final[tuple[str, ...]] = (
    "ModelType",
    "ROI",
    "Condition",
    "GroupA",
    "GroupB",
    "Estimate",
    "SE",
    "TestStat",
    "DF",
    "P",
    "P_corrected",
    "Method",
)
MULTIGROUP_GROUP_CONTRAST_SHEET: Final[str] = "Pairwise_Contrasts"
MULTIGROUP_GROUP_CONTRAST_LEGACY_SHEETS: Final[tuple[str, ...]] = ("Post-hoc Results",)
MULTIGROUP_MISSINGNESS_XLS: Final[str] = "Missingness and Exclusions.xlsx"
MULTIGROUP_MISSINGNESS_SHEETS: Final[tuple[str, ...]] = (
    "MixedModel_MissingCells",
    "Summary",
)
MULTIGROUP_QC_CONTEXT_XLS: Final[str] = "QC_Context_ByGroup.xlsx"
MULTIGROUP_QC_CONTEXT_SHEETS: Final[tuple[str, ...]] = (
    "Summary",
    "DV_Distribution",
    "Subject_Level",
)


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
    "BASELINE_VS_ZERO_XLS",
    "MULTIGROUP_MIXED_MODEL_SHEET",
    "MULTIGROUP_GROUP_CONTRAST_COLUMNS",
    "MULTIGROUP_GROUP_CONTRAST_SHEET",
    "MULTIGROUP_GROUP_CONTRAST_LEGACY_SHEETS",
    "MULTIGROUP_MISSINGNESS_XLS",
    "MULTIGROUP_MISSINGNESS_SHEETS",
    "MULTIGROUP_QC_CONTEXT_XLS",
    "MULTIGROUP_QC_CONTEXT_SHEETS",
    "PipelineStep",
]

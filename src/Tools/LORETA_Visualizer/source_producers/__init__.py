"""Source-localization producer interfaces for prepared visualizer payloads.

Producer modules calculate source estimates from explicit source-ready inputs
and write prepared JSON payloads. They do not render, import GUI payloads, or
perform display-coordinate translation.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from Tools.LORETA_Visualizer.source_producers.contracts import (
    ProducedPayload,
    SourceProducerRunResult,
)

if TYPE_CHECKING:
    from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import (
        L2MNECorticalForwardModel,
        L2MNEFPVSCondition,
        L2MNEProducerConfig,
        build_l2_mne_cortical_surface_payload,
        compute_l2_mne_source_values,
        make_l2_mne_cortical_surface_beta_fixture,
        write_l2_mne_cortical_surface_fixture,
        write_l2_mne_cortical_surface_payloads,
    )
    from Tools.LORETA_Visualizer.source_producers.project_inputs import (
        ProjectConditionTopographySummary,
        ProjectSourceTopographyInputSet,
        build_l2_mne_conditions_from_project,
    )
    from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
        ProjectL2MNEExportResult,
        build_mne_fsaverage_l2_mne_forward_model,
        default_project_l2_mne_output_dir,
        write_project_l2_mne_cortical_surface_payloads,
    )

_L2_MNE_EXPORTS = {
    "L2MNECorticalForwardModel",
    "L2MNEFPVSCondition",
    "L2MNEProducerConfig",
    "build_l2_mne_cortical_surface_payload",
    "compute_l2_mne_source_values",
    "make_l2_mne_cortical_surface_beta_fixture",
    "write_l2_mne_cortical_surface_fixture",
    "write_l2_mne_cortical_surface_payloads",
}
_PROJECT_INPUT_EXPORTS = {
    "ProjectConditionTopographySummary",
    "ProjectSourceTopographyInputSet",
    "build_l2_mne_conditions_from_project",
}
_PROJECT_L2_MNE_EXPORTS = {
    "ProjectL2MNEExportResult",
    "build_mne_fsaverage_l2_mne_forward_model",
    "default_project_l2_mne_output_dir",
    "write_project_l2_mne_cortical_surface_payloads",
}

__all__ = [
    "L2MNECorticalForwardModel",
    "L2MNEFPVSCondition",
    "L2MNEProducerConfig",
    "ProducedPayload",
    "ProjectConditionTopographySummary",
    "ProjectL2MNEExportResult",
    "ProjectSourceTopographyInputSet",
    "SourceProducerRunResult",
    "build_mne_fsaverage_l2_mne_forward_model",
    "build_l2_mne_cortical_surface_payload",
    "build_l2_mne_conditions_from_project",
    "compute_l2_mne_source_values",
    "default_project_l2_mne_output_dir",
    "make_l2_mne_cortical_surface_beta_fixture",
    "write_project_l2_mne_cortical_surface_payloads",
    "write_l2_mne_cortical_surface_fixture",
    "write_l2_mne_cortical_surface_payloads",
]


def __getattr__(name: str) -> Any:
    """Lazily expose producer methods without importing calculation modules early."""
    if name in _L2_MNE_EXPORTS:
        l2_mne_cortical = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.l2_mne_cortical"
        )
        return getattr(l2_mne_cortical, name)
    if name in _PROJECT_INPUT_EXPORTS:
        project_inputs = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.project_inputs"
        )
        return getattr(project_inputs, name)
    if name in _PROJECT_L2_MNE_EXPORTS:
        project_l2_mne_export = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.project_l2_mne_export"
        )
        return getattr(project_l2_mne_export, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

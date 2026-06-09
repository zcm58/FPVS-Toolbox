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
    from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
        L2MNEHaukHarmonicBins,
        L2MNEHaukParticipantGroupCondition,
        L2MNEHaukParticipantSourceInput,
        L2MNEHaukParticipantZScoreValues,
        L2MNEHaukClusterPermutationResult,
        L2MNEHaukZScoreCondition,
        L2MNEHaukZScoreConfig,
        build_l2_mne_hauk_participant_zscore_summary_payload,
        build_l2_mne_hauk_zscore_surface_payload,
        compute_l2_mne_hauk_participant_zscore_source_values,
        compute_l2_mne_hauk_source_cluster_mask,
        compute_l2_mne_hauk_zscore_source_values,
        summarize_l2_mne_hauk_participant_zscores,
        write_l2_mne_hauk_participant_zscore_surface_payloads,
        write_l2_mne_hauk_zscore_surface_payloads,
    )
    from Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs import (
        ProjectFullFftBinPlan,
        ProjectParticipantSourceFrequencyBinInputSet,
        ProjectSourceFrequencyBinInputSet,
        build_l2_mne_hauk_participant_zscore_conditions_from_project,
        build_l2_mne_hauk_zscore_conditions_from_project,
    )
    from Tools.LORETA_Visualizer.source_producers.project_inputs import (
        ProjectConditionTopographySummary,
        ProjectSourceTopographyInputSet,
        build_l2_mne_conditions_from_project,
    )
    from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export import (
        PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST,
        PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST,
        ProjectL2MNEHaukZScoreExportResult,
        default_project_l2_mne_hauk_zscore_output_dir,
        write_project_l2_mne_hauk_zscore_group_first_payloads,
        write_project_l2_mne_hauk_zscore_payloads,
    )
    from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
        ProjectL2MNEExportResult,
        build_mne_fsaverage_l2_mne_forward_model,
        default_project_l2_mne_output_dir,
        write_project_l2_mne_cortical_surface_payloads,
    )
    from Tools.LORETA_Visualizer.source_producers.source_lateralization import (
        SOURCE_LATERALIZATION_SUMMARY_FORMAT,
        build_source_lateralization_rows,
        write_source_lateralization_summary_files,
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
_L2_MNE_HAUK_ZSCORE_EXPORTS = {
    "L2MNEHaukHarmonicBins",
    "L2MNEHaukParticipantGroupCondition",
    "L2MNEHaukParticipantSourceInput",
    "L2MNEHaukParticipantZScoreValues",
    "L2MNEHaukClusterPermutationResult",
    "L2MNEHaukZScoreCondition",
    "L2MNEHaukZScoreConfig",
    "build_l2_mne_hauk_participant_zscore_summary_payload",
    "build_l2_mne_hauk_zscore_surface_payload",
    "compute_l2_mne_hauk_participant_zscore_source_values",
    "compute_l2_mne_hauk_source_cluster_mask",
    "compute_l2_mne_hauk_zscore_source_values",
    "summarize_l2_mne_hauk_participant_zscores",
    "write_l2_mne_hauk_participant_zscore_surface_payloads",
    "write_l2_mne_hauk_zscore_surface_payloads",
}
_PROJECT_FULLFFT_INPUT_EXPORTS = {
    "ProjectFullFftBinPlan",
    "ProjectParticipantSourceFrequencyBinInputSet",
    "ProjectSourceFrequencyBinInputSet",
    "build_l2_mne_hauk_participant_zscore_conditions_from_project",
    "build_l2_mne_hauk_zscore_conditions_from_project",
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
_PROJECT_HAUK_ZSCORE_EXPORTS = {
    "PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST",
    "PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST",
    "ProjectL2MNEHaukZScoreExportResult",
    "default_project_l2_mne_hauk_zscore_output_dir",
    "write_project_l2_mne_hauk_zscore_group_first_payloads",
    "write_project_l2_mne_hauk_zscore_payloads",
}
_SOURCE_LATERALIZATION_EXPORTS = {
    "SOURCE_LATERALIZATION_SUMMARY_FORMAT",
    "build_source_lateralization_rows",
    "write_source_lateralization_summary_files",
}

__all__ = [
    "L2MNECorticalForwardModel",
    "L2MNEFPVSCondition",
    "L2MNEHaukHarmonicBins",
    "L2MNEHaukParticipantGroupCondition",
    "L2MNEHaukParticipantSourceInput",
    "L2MNEHaukParticipantZScoreValues",
    "L2MNEHaukClusterPermutationResult",
    "L2MNEHaukZScoreCondition",
    "L2MNEHaukZScoreConfig",
    "L2MNEProducerConfig",
    "PROJECT_HAUK_ZSCORE_MODEL_DEPRECATED_GROUP_FIRST",
    "PROJECT_HAUK_ZSCORE_MODEL_PARTICIPANT_FIRST",
    "ProducedPayload",
    "ProjectConditionTopographySummary",
    "ProjectFullFftBinPlan",
    "ProjectL2MNEHaukZScoreExportResult",
    "ProjectL2MNEExportResult",
    "ProjectParticipantSourceFrequencyBinInputSet",
    "ProjectSourceFrequencyBinInputSet",
    "ProjectSourceTopographyInputSet",
    "SOURCE_LATERALIZATION_SUMMARY_FORMAT",
    "SourceProducerRunResult",
    "build_l2_mne_hauk_participant_zscore_conditions_from_project",
    "build_l2_mne_hauk_participant_zscore_summary_payload",
    "build_l2_mne_hauk_zscore_conditions_from_project",
    "build_l2_mne_hauk_zscore_surface_payload",
    "build_mne_fsaverage_l2_mne_forward_model",
    "build_l2_mne_cortical_surface_payload",
    "build_l2_mne_conditions_from_project",
    "build_source_lateralization_rows",
    "compute_l2_mne_hauk_participant_zscore_source_values",
    "compute_l2_mne_hauk_source_cluster_mask",
    "compute_l2_mne_hauk_zscore_source_values",
    "compute_l2_mne_source_values",
    "default_project_l2_mne_hauk_zscore_output_dir",
    "default_project_l2_mne_output_dir",
    "make_l2_mne_cortical_surface_beta_fixture",
    "summarize_l2_mne_hauk_participant_zscores",
    "write_l2_mne_hauk_participant_zscore_surface_payloads",
    "write_l2_mne_hauk_zscore_surface_payloads",
    "write_project_l2_mne_hauk_zscore_group_first_payloads",
    "write_project_l2_mne_hauk_zscore_payloads",
    "write_project_l2_mne_cortical_surface_payloads",
    "write_l2_mne_cortical_surface_fixture",
    "write_l2_mne_cortical_surface_payloads",
    "write_source_lateralization_summary_files",
]


def __getattr__(name: str) -> Any:
    """Lazily expose producer methods without importing calculation modules early."""
    if name in _L2_MNE_EXPORTS:
        l2_mne_cortical = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.l2_mne_cortical"
        )
        return getattr(l2_mne_cortical, name)
    if name in _L2_MNE_HAUK_ZSCORE_EXPORTS:
        l2_mne_hauk_zscore = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore"
        )
        return getattr(l2_mne_hauk_zscore, name)
    if name in _PROJECT_FULLFFT_INPUT_EXPORTS:
        project_fullfft_inputs = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.project_fullfft_inputs"
        )
        return getattr(project_fullfft_inputs, name)
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
    if name in _PROJECT_HAUK_ZSCORE_EXPORTS:
        project_l2_mne_hauk_zscore_export = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_zscore_export"
        )
        return getattr(project_l2_mne_hauk_zscore_export, name)
    if name in _SOURCE_LATERALIZATION_EXPORTS:
        source_lateralization = importlib.import_module(
            "Tools.LORETA_Visualizer.source_producers.source_lateralization"
        )
        return getattr(source_lateralization, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

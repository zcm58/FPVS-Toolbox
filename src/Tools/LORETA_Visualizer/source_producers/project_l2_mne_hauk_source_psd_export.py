"""Project-level Option-1 Hauk-informed source-PSD export.

The exporter is a GUI-neutral orchestration layer.  It derives the exact
participant/condition set from the active project's processing ledger, loads
only committed signed time-domain derivatives, computes or restores compact
participant source-PSD z maps, and delegates group summaries and prepared JSON
publication to the existing participant-first Hauk writer.

No amplitude workbook is a fallback for this workflow.  Numerical source-PSD
and neighboring-bin behavior remains owned by :mod:`hauk_source_psd`.
"""

from __future__ import annotations


import hashlib
import json
import logging
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from Tools.LORETA_Visualizer.prepared_payload_validator import (
    validate_prepared_source_manifest_json,
)
from Tools.LORETA_Visualizer.source_producers.contracts import SourceProducerRunResult
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS,
    DEFAULT_HAUK_SOURCE_PSD_REQUIRED_NOISE_BIN_COUNT,
    DEFAULT_HAUK_SOURCE_PSD_RETAINED_NOISE_BIN_COUNT,
    HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID,
    HAUK_SOURCE_PSD_METHOD_ID,
    HAUK_SOURCE_PSD_METHOD_VERSION,
    SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
    SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
    ComputeSourcePsdCallable,
    HaukSourcePsdConfig,
    HaukSourcePsdResult,
    build_hauk_source_psd_frequency_plan,
    compute_hauk_source_psd,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.l2_mne_hauk_zscore import (
    DEFAULT_CLUSTER_ALPHA,
    DEFAULT_CLUSTER_FORMING_P_VALUE,
    DEFAULT_CLUSTER_PERMUTATION_COUNT,
    DEFAULT_CLUSTER_PERMUTATION_SEED,
    DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    L2MNEHaukParticipantZScoreValues,
    L2MNEHaukPrecomputedParticipantGroupCondition,
    L2MNEHaukZScoreConfig,
    write_l2_mne_hauk_precomputed_participant_zscore_surface_payloads,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    DEFAULT_MNE_FSAVERAGE_SPACING,
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
    MneFsaverageSourcePsdModel,
    build_mne_fsaverage_source_psd_model,
)
from Tools.LORETA_Visualizer.source_producers.project_time_domain_inputs import (
    ProjectTimeDomainInputRecord,
    ProjectTimeDomainInputSet,
    load_project_time_domain_inputs,
    load_project_time_domain_raw,
)
from Tools.LORETA_Visualizer.source_producers.source_psd_cache import (
    SourcePsdCacheKeyInputs,
    SourcePsdParticipantResult,
    load_source_psd_cache_entry,
    store_source_psd_cache_entry,
)
from Tools.LORETA_Visualizer.source_producers.source_validation_report import (
    write_project_source_validation_report,
)

from Tools.LORETA_Visualizer.source_producers.project_source_psd_inputs import (
    ProjectHaukSourcePsdInputError as ProjectL2MNEHaukSourcePsdExportError,
    SOURCE_PARTICIPANT_ELIGIBILITY_POLICY as SOURCE_PARTICIPANT_ELIGIBILITY_POLICY,
    SOURCE_SAMPLE_COUNT_SELECTION_POLICY as SOURCE_SAMPLE_COUNT_SELECTION_POLICY,
    ProjectHaukSourcePsdConditionSpec as ProjectHaukSourcePsdConditionSpec,
    ProjectHaukSourcePsdGroupSpec as ProjectHaukSourcePsdGroupSpec,
    ProjectHaukSourcePsdInputPlan as ProjectHaukSourcePsdInputPlan,
    ProjectSourceConditionOmission as ProjectSourceConditionOmission,
    ProjectSourceIneligibleParticipant as ProjectSourceIneligibleParticipant,
    _ConditionSpec as _ConditionSpec,
    _ProjectGroupSpec as _ProjectGroupSpec,
    _ProjectInputPlan as _ProjectInputPlan,
    _active_project_root as _active_project_root,
    _build_project_input_plan as _build_project_input_plan,
    _condition_group_provenance as _condition_group_provenance,
    _enrich_source_psd_provenance as _enrich_source_psd_provenance,
    _resolve_selected_harmonics as _resolve_selected_harmonics,
    active_project_hauk_source_psd_root as active_project_hauk_source_psd_root,
    build_project_hauk_source_psd_input_plan as build_project_hauk_source_psd_input_plan,
    enrich_project_hauk_source_psd_provenance as enrich_project_hauk_source_psd_provenance,
    log_project_source_condition_omission_summary as log_project_source_condition_omission_summary,
    reconcile_project_hauk_source_psd_sampling_contract as reconcile_project_hauk_source_psd_sampling_contract,
    resolve_project_hauk_source_psd_harmonics as resolve_project_hauk_source_psd_harmonics,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]

PROJECT_L2_MNE_HAUK_SOURCE_PSD_OUTPUT_FOLDER = "L2-MNE Hauk Source PSD Beta"
DEFAULT_PROJECT_HAUK_SOURCE_PSD_MANIFEST_NAME = "project_l2_mne_hauk_source_psd_manifest.json"


@dataclass(frozen=True)
class ProjectL2MNEHaukSourcePsdExportResult:
    """Prepared output and source-input diagnostics for one project run."""

    project_inputs: ProjectTimeDomainInputSet
    producer_result: SourceProducerRunResult
    forward_model: L2MNECorticalForwardModel
    method_id: str
    source_orientation_mode: str
    selected_harmonics_hz: tuple[float, ...]
    processing_fingerprint: str
    processing_fingerprint_version: str
    included_participants: tuple[str, ...]
    excluded_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]
    source_ineligible_participants: tuple[ProjectSourceIneligibleParticipant, ...]
    source_condition_omissions: tuple[ProjectSourceConditionOmission, ...]
    cache_hit_count: int
    cache_miss_count: int
    participant_sidecar_path: Path
    lateralization_summary_path: Path | None = None
    lateralization_summary_csv_path: Path | None = None
    validation_report_path: Path | None = None
    validation_report_markdown_path: Path | None = None

    @property
    def output_dir(self) -> Path:
        """Directory containing prepared payloads and their manifest."""

        return self.producer_result.output_dir

    @property
    def manifest_path(self) -> Path:
        """Renderer-importable prepared source manifest."""

        return self.producer_result.manifest_path


@dataclass(frozen=True)
class _ValidationBinPlan:
    frequency_resolution_hz: float
    noise_window_bins: int = 10
    excluded_offsets: tuple[int, ...] = (-1, 0, 1)
    candidate_noise_offsets: tuple[int, ...] = DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS
    min_noise_bins: int = DEFAULT_HAUK_SOURCE_PSD_REQUIRED_NOISE_BIN_COUNT
    required_candidate_noise_bin_count: int = DEFAULT_HAUK_SOURCE_PSD_REQUIRED_NOISE_BIN_COUNT
    retained_noise_bin_count_after_extreme_drop: int = DEFAULT_HAUK_SOURCE_PSD_RETAINED_NOISE_BIN_COUNT


@dataclass(frozen=True)
class _ValidationReportInputs:
    project_root: Path
    selected_harmonics_hz: tuple[float, ...]
    conditions: tuple[L2MNEHaukPrecomputedParticipantGroupCondition, ...]
    excluded_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]
    source_ineligible_participants: tuple[Mapping[str, Any], ...]
    source_condition_omissions: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[str, ...]
    bin_plan: _ValidationBinPlan
    participant_eligibility_policy: str = SOURCE_PARTICIPANT_ELIGIBILITY_POLICY
    sheet_name: str = "source-ready signed time-domain FIF"
    summaries: tuple["_ValidationConditionSummary", ...] = ()


@dataclass(frozen=True)
class _ValidationConditionSummary:
    condition: str
    input_file_count: int
    workbook_count: int
    included_subject_count: int
    included_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]


def default_project_l2_mne_hauk_source_psd_output_dir(project_root: str | Path) -> Path:
    """Return the canonical project-local Option-1 output directory."""

    root = Path(project_root).expanduser().resolve()
    return root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_L2_MNE_HAUK_SOURCE_PSD_OUTPUT_FOLDER


def write_project_l2_mne_hauk_source_psd_payloads(
    *,
    project: Any,
    project_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    include_flagged_subjects: bool = False,
    spacing: str = DEFAULT_MNE_FSAVERAGE_SPACING,
    allow_fetch_fsaverage: bool = False,
    source_psd_model: MneFsaverageSourcePsdModel | None = None,
    source_orientation_mode: str = SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
    selected_harmonics_hz: Sequence[float] | None = None,
    compute_source_psd_func: ComputeSourcePsdCallable | None = None,
    aggregations: Sequence[str] = DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    cluster_mask_enabled: bool = True,
    cluster_forming_p_value: float = DEFAULT_CLUSTER_FORMING_P_VALUE,
    cluster_alpha: float = DEFAULT_CLUSTER_ALPHA,
    cluster_permutation_count: int = DEFAULT_CLUSTER_PERMUTATION_COUNT,
    cluster_permutation_seed: int = DEFAULT_CLUSTER_PERMUTATION_SEED,
    progress_callback: ProgressCallback | None = None,
) -> ProjectL2MNEHaukSourcePsdExportResult:
    """Write time-domain-first participant and group source-PSD payloads.

    ``project`` is the canonical active project object.  ``project_root``, when
    supplied by a caller integration, must resolve to the same root.  The
    optional model, selected-harmonic sequence, and MNE PSD callable are narrow
    test seams; normal project runs derive harmonics from the saved processing
    selection and build the fsaverage BioSemi64 model.
    """

    root = _active_project_root(project, project_root=project_root)
    resolved_output = _project_output_dir(root, output_dir)
    _emit_progress(progress_callback, "Reading completed processing-ledger participants...")
    input_plan = _build_project_input_plan(
        project,
        root=root,
        include_flagged_subjects=include_flagged_subjects,
    )
    if input_plan.source_condition_omissions:
        omitted_participants = {item.participant_id for item in input_plan.source_condition_omissions}
        _emit_progress(
            progress_callback,
            (
                "Source cohort warning: using condition-specific cohorts; omitting "
                f"{len(input_plan.source_condition_omissions)} unavailable "
                "participant-condition input(s) across "
                f"{len(omitted_participants)} participant(s)."
            ),
        )
        log_project_source_condition_omission_summary(
            logger,
            event_name="project_l2_mne_hauk_source_condition_omission_summary",
            omissions=input_plan.source_condition_omissions,
        )
    if input_plan.source_ineligible_participants:
        skipped_ids = ", ".join(item.participant_id for item in input_plan.source_ineligible_participants)
        _emit_progress(
            progress_callback,
            (
                f"Source cohort warning: using {len(input_plan.participants)} eligible "
                f"participant(s); omitting {skipped_ids} from every source condition."
            ),
        )
        for item in input_plan.source_ineligible_participants:
            logger.warning(
                "project_l2_mne_hauk_source_participant_ineligible participant=%s reason=%s detail=%s",
                item.participant_id,
                item.reason_code,
                item.detail,
            )

    _emit_progress(progress_callback, "Validating signed source-ready time-domain derivatives...")
    project_inputs = load_project_time_domain_inputs(
        root,
        expected_inputs=input_plan.expected_inputs,
        expected_processing_fingerprint=input_plan.processing_fingerprint,
        expected_processing_fingerprint_version=input_plan.processing_fingerprint_version,
    )
    sampling_omission_count = len(project_inputs.sampling_contract_omissions)
    input_plan = reconcile_project_hauk_source_psd_sampling_contract(
        input_plan,
        project_inputs=project_inputs,
    )
    if sampling_omission_count:
        sampling_omissions = input_plan.source_condition_omissions[-sampling_omission_count:]
        _emit_progress(
            progress_callback,
            (
                "Source cohort warning: omitted "
                f"{sampling_omission_count} participant-condition derivative(s) "
                "that did not match the unique modal sample-count contract."
            ),
        )
        log_project_source_condition_omission_summary(
            logger,
            event_name="project_l2_mne_hauk_source_condition_omission_summary",
            omissions=sampling_omissions,
        )
    _emit_progress(
        progress_callback,
        (f"Validated {len(project_inputs.records)} participant-condition time-domain derivative(s)."),
    )

    harmonics, harmonic_metadata = _resolve_selected_harmonics(
        project,
        selected_harmonics_hz=selected_harmonics_hz,
        progress_callback=progress_callback,
    )
    selected_method_id = _source_psd_method_id_for_orientation_mode(source_orientation_mode)
    source_psd_config = HaukSourcePsdConfig(
        selected_harmonics_hz=harmonics,
        source_orientation_mode=source_orientation_mode,
        method_id=selected_method_id,
        metadata={
            "harmonic_selection": harmonic_metadata,
            "processing_fingerprint": input_plan.processing_fingerprint,
            "processing_fingerprint_version": input_plan.processing_fingerprint_version,
            "input_derivative_format": "fpvs-source-ready-time-domain-v1",
        },
    )
    frequency_plan = build_hauk_source_psd_frequency_plan(
        sfreq=project_inputs.sfreq_hz,
        n_times=project_inputs.n_times,
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        bin_position_tolerance=source_psd_config.bin_position_tolerance,
    )

    if source_psd_model is None:
        _emit_progress(
            progress_callback,
            f"Building fsaverage BioSemi64 L2-MNE source-PSD model ({spacing})...",
        )
        model = build_mne_fsaverage_source_psd_model(
            sfreq=project_inputs.sfreq_hz,
            channel_names=project_inputs.records[0].channel_names,
            spacing=spacing,
            allow_fetch_fsaverage=allow_fetch_fsaverage,
        )
    else:
        if not isinstance(source_psd_model, MneFsaverageSourcePsdModel):
            raise TypeError("source_psd_model must be MneFsaverageSourcePsdModel when supplied.")
        _emit_progress(progress_callback, "Using supplied fsaverage source-PSD model.")
        model = source_psd_model
    _validate_source_psd_model(model, project_inputs=project_inputs)
    _emit_progress(progress_callback, "Source-PSD inverse model is ready.")

    rows_by_condition: dict[str, list[L2MNEHaukParticipantZScoreValues]] = {
        condition.condition_id: [] for condition in input_plan.conditions
    }
    numerical_model_metadata = _numerical_model_cache_metadata(model)
    method_metadata = source_psd_config.to_metadata()
    frequency_metadata = frequency_plan.to_metadata()
    cache_hit_count = 0
    cache_miss_count = 0

    for index, record in enumerate(project_inputs.records, start=1):
        _emit_progress(
            progress_callback,
            (
                f"Computing source PSD {index}/{len(project_inputs.records)}: "
                f"{record.participant_id} / {record.condition_label}..."
            ),
        )
        key_inputs = SourcePsdCacheKeyInputs(
            derivative_checksum_sha256=record.fif_sha256,
            numerical_model_metadata=numerical_model_metadata,
            method_metadata=method_metadata,
            frequency_metadata=frequency_metadata,
        )
        lookup = load_source_psd_cache_entry(project_root=root, key_inputs=key_inputs)
        if lookup.hit:
            cache_hit_count += 1
            participant_values = _participant_values_from_cache(
                lookup.result,
                participant_id=record.participant_id,
                expected_source_count=len(model.forward_model.source_points),
            )
        else:
            cache_miss_count += 1
            with load_project_time_domain_raw(record) as raw:
                source_psd_result = compute_hauk_source_psd(
                    averaged_raw=raw,
                    inverse_operator=model.inverse_operator,
                    config=source_psd_config,
                    compute_source_psd_func=compute_source_psd_func,
                )
            participant_values = _participant_values_from_source_psd(
                source_psd_result,
                participant_id=record.participant_id,
                expected_source_count=len(model.forward_model.source_points),
            )
            cache_result = SourcePsdParticipantResult.from_l2_mne_participant_zscore_values(
                participant_values,
                metadata=_participant_cache_metadata(record, source_psd_result),
            )
            store_source_psd_cache_entry(
                project_root=root,
                key_inputs=key_inputs,
                result=cache_result,
            )
        rows_by_condition[record.condition_id].append(participant_values)

    prepared_conditions = _precomputed_conditions(
        input_plan,
        rows_by_condition=rows_by_condition,
    )
    output_config = L2MNEHaukZScoreConfig(
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        method_id=source_psd_config.method_id,
        lambda2=source_psd_config.lambda2,
        cluster_mask_enabled=cluster_mask_enabled,
        cluster_forming_p_value=cluster_forming_p_value,
        cluster_alpha=cluster_alpha,
        cluster_permutation_count=cluster_permutation_count,
        cluster_permutation_seed=cluster_permutation_seed,
        metadata={
            "project_integration": "option_1_time_domain_hauk_source_psd",
            "project_root_name": root.name,
            "source_map_model": "participant_first",
            "input_domain": "signed_repetition_averaged_eeg_time_series",
            "input_derivative_root": project_inputs.input_root.relative_to(root).as_posix(),
            "processing_fingerprint": input_plan.processing_fingerprint,
            "processing_fingerprint_version": input_plan.processing_fingerprint_version,
            "harmonic_selection": harmonic_metadata,
            "source_psd_method_metadata": method_metadata,
            "source_orientation_mode": source_psd_config.source_orientation_mode,
            "include_flagged_subjects": bool(include_flagged_subjects),
            "participant_eligibility_policy": SOURCE_PARTICIPANT_ELIGIBILITY_POLICY,
            "included_participants": list(input_plan.participants),
            "excluded_subjects": list(input_plan.participant_selection.excluded_subjects),
            "flagged_subjects": list(input_plan.participant_selection.flagged_subjects),
            "source_ineligible_participants": [
                item.to_metadata() for item in input_plan.source_ineligible_participants
            ],
            "source_condition_omissions": [item.to_metadata() for item in input_plan.source_condition_omissions],
            "source_sample_count_selection_policy": (
                SOURCE_SAMPLE_COUNT_SELECTION_POLICY
            ),
            "source_sample_count_n_times": project_inputs.n_times,
            "source_sample_count_omission_count": sampling_omission_count,
            "group_summary_policy": (
                "separate_canonical_project_groups" if input_plan.split_group_summaries else "single_project_cohort"
            ),
            "included_project_groups": [
                {
                    "group_id": group.group_id,
                    "group_label": group.label,
                    "group_folder": group.folder,
                    "participant_ids": list(group.participants),
                }
                for group in input_plan.groups
            ],
            "cache_hit_count": cache_hit_count,
            "cache_miss_count": cache_miss_count,
            "output_scope": "project-local",
            "option_2_complex_fourier": "deferred",
        },
    )

    _emit_progress(progress_callback, "Writing participant and group source-PSD payloads...")
    participant_result = write_l2_mne_hauk_precomputed_participant_zscore_surface_payloads(
        forward_model=model.forward_model,
        conditions=prepared_conditions,
        config=output_config,
        output_dir=resolved_output,
        manifest_name=DEFAULT_PROJECT_HAUK_SOURCE_PSD_MANIFEST_NAME,
        aggregations=aggregations,
        trim_fraction=trim_fraction,
        progress_callback=progress_callback,
    )
    _enrich_source_psd_provenance(
        manifest_path=participant_result.producer_result.manifest_path,
        participant_sidecar_path=participant_result.participant_sidecar_path,
        output_dir=participant_result.producer_result.output_dir,
        method_metadata=method_metadata,
        conditions=prepared_conditions,
        included_participants=input_plan.participants,
        excluded_subjects=input_plan.participant_selection.excluded_subjects,
        flagged_subjects=input_plan.participant_selection.flagged_subjects,
        source_ineligible_participants=input_plan.source_ineligible_participants,
        source_condition_omissions=input_plan.source_condition_omissions,
        source_sample_count_n_times=project_inputs.n_times,
        source_sample_count_omission_count=sampling_omission_count,
    )
    producer_result = SourceProducerRunResult(
        method_id=participant_result.producer_result.method_id,
        output_dir=participant_result.producer_result.output_dir,
        manifest_path=participant_result.producer_result.manifest_path,
        payloads=participant_result.producer_result.payloads,
        manifest_validation=validate_prepared_source_manifest_json(
            participant_result.producer_result.manifest_path,
            require_payload_files=True,
        ),
    )
    _emit_progress(progress_callback, "Writing project source-validation report...")
    validation_inputs = _ValidationReportInputs(
        project_root=root,
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        conditions=prepared_conditions,
        excluded_subjects=input_plan.participant_selection.excluded_subjects,
        flagged_subjects=input_plan.participant_selection.flagged_subjects,
        source_ineligible_participants=tuple(item.to_metadata() for item in input_plan.source_ineligible_participants),
        source_condition_omissions=tuple(item.to_metadata() for item in input_plan.source_condition_omissions),
        diagnostics=(
            f"validated_time_domain_derivatives={len(project_inputs.records)}",
            f"included_participants={len(input_plan.participants)}",
            f"source_ineligible_participants={len(input_plan.source_ineligible_participants)}",
            f"source_condition_omissions={len(input_plan.source_condition_omissions)}",
            "source_sample_count_selection_policy="
            + SOURCE_SAMPLE_COUNT_SELECTION_POLICY,
            f"source_sample_count_n_times={project_inputs.n_times}",
            f"source_sample_count_omissions={sampling_omission_count}",
            f"prepared_group_conditions={len(prepared_conditions)}",
            "group_summary_policy="
            + ("separate_canonical_project_groups" if input_plan.split_group_summaries else "single_project_cohort"),
            f"cache_hits={cache_hit_count}",
            f"cache_misses={cache_miss_count}",
        ),
        bin_plan=_ValidationBinPlan(
            frequency_resolution_hz=project_inputs.frequency_resolution_hz,
        ),
        summaries=tuple(
            _ValidationConditionSummary(
                condition=condition.label,
                input_file_count=len(condition.participant_values),
                workbook_count=0,
                included_subject_count=len(condition.participant_values),
                included_subjects=tuple(row.participant_id for row in condition.participant_values),
                flagged_subjects=tuple(
                    row.participant_id
                    for row in condition.participant_values
                    if row.participant_id in input_plan.participant_selection.flagged_subjects
                ),
            )
            for condition in prepared_conditions
        ),
    )
    validation_report = write_project_source_validation_report(
        output_dir=producer_result.output_dir,
        manifest_path=producer_result.manifest_path,
        payloads=producer_result.payloads,
        project_inputs=validation_inputs,
        export_model=source_psd_config.method_id,
        participant_sidecar_path=participant_result.participant_sidecar_path,
        lateralization_summary_path=participant_result.lateralization_summary_path,
        lateralization_summary_csv_path=participant_result.lateralization_summary_csv_path,
        forward_model_metadata=dict(model.forward_model.metadata),
    )
    result = ProjectL2MNEHaukSourcePsdExportResult(
        project_inputs=project_inputs,
        producer_result=producer_result,
        forward_model=model.forward_model,
        method_id=source_psd_config.method_id,
        source_orientation_mode=source_psd_config.source_orientation_mode,
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        processing_fingerprint=input_plan.processing_fingerprint,
        processing_fingerprint_version=input_plan.processing_fingerprint_version,
        included_participants=input_plan.participants,
        excluded_subjects=input_plan.participant_selection.excluded_subjects,
        flagged_subjects=input_plan.participant_selection.flagged_subjects,
        source_ineligible_participants=input_plan.source_ineligible_participants,
        source_condition_omissions=input_plan.source_condition_omissions,
        cache_hit_count=cache_hit_count,
        cache_miss_count=cache_miss_count,
        participant_sidecar_path=participant_result.participant_sidecar_path,
        lateralization_summary_path=participant_result.lateralization_summary_path,
        lateralization_summary_csv_path=participant_result.lateralization_summary_csv_path,
        validation_report_path=validation_report.json_path,
        validation_report_markdown_path=validation_report.markdown_path,
    )
    logger.info(
        "project_l2_mne_hauk_source_psd_payloads_written",
        extra={
            "project_root": str(root),
            "output_dir": str(result.output_dir),
            "manifest_path": str(result.manifest_path),
            "method_id": result.method_id,
            "source_orientation_mode": result.source_orientation_mode,
            "participant_count": len(result.included_participants),
            "source_ineligible_participant_count": len(result.source_ineligible_participants),
            "source_condition_omission_count": len(result.source_condition_omissions),
            "condition_count": len(prepared_conditions),
            "cache_hit_count": cache_hit_count,
            "cache_miss_count": cache_miss_count,
            "validation_report_path": str(result.validation_report_path),
        },
    )
    return result


def _project_output_dir(project_root: Path, output_dir: str | Path | None) -> Path:
    target = default_project_l2_mne_hauk_source_psd_output_dir(project_root) if output_dir is None else Path(output_dir)
    if not target.is_absolute():
        target = project_root / target
    resolved = target.expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("Project Hauk source-PSD output directory must stay inside the project root.") from exc
    if resolved == project_root:
        raise ValueError("Project Hauk source-PSD output directory cannot be the project root.")
    return resolved


def _validate_source_psd_model(
    model: MneFsaverageSourcePsdModel,
    *,
    project_inputs: ProjectTimeDomainInputSet,
) -> None:
    forward = model.forward_model
    expected_channels = project_inputs.records[0].channel_names
    if tuple(forward.channel_names) != expected_channels:
        raise ProjectL2MNEHaukSourcePsdExportError(
            "The fsaverage source-PSD model does not use the validated BioSemi64 channel order."
        )
    info_channels = tuple(str(name) for name in getattr(model.info, "ch_names", ()))
    if info_channels != expected_channels:
        raise ProjectL2MNEHaukSourcePsdExportError(
            "The native MNE inverse info does not match the validated time-domain channels."
        )
    try:
        model_sfreq = float(model.info["sfreq"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectL2MNEHaukSourcePsdExportError(
            "The native MNE inverse info has no valid sampling frequency."
        ) from exc
    if not math.isclose(model_sfreq, project_inputs.sfreq_hz, rel_tol=1e-9, abs_tol=1e-12):
        raise ProjectL2MNEHaukSourcePsdExportError(
            "The native MNE inverse sampling frequency does not match the time-domain inputs."
        )
    if model.inverse_operator is None:
        raise ProjectL2MNEHaukSourcePsdExportError("The source-PSD model has no native inverse operator.")


def _numerical_model_cache_metadata(model: MneFsaverageSourcePsdModel) -> dict[str, Any]:
    forward = model.forward_model
    return {
        "model_kind": "mne_fsaverage_biosemi64_l2_mne_source_psd",
        "model_label": forward.label,
        "coordinate_space": forward.coordinate_space,
        "channel_names": list(forward.channel_names),
        "source_count": int(len(forward.source_points)),
        "source_points_sha256": _array_sha256(forward.source_points),
        "faces_sha256": _array_sha256(forward.faces),
        "leadfield_sha256": _array_sha256(forward.leadfield),
        "source_vertex_ids": (
            None if forward.source_vertex_ids is None else [int(value) for value in forward.source_vertex_ids]
        ),
        "source_hemispheres": (
            None if forward.source_hemispheres is None else [str(value) for value in forward.source_hemispheres]
        ),
        "metadata": dict(model.metadata),
    }


def _array_sha256(values: Any) -> str:
    array = np.ascontiguousarray(np.asarray(values))
    descriptor = json.dumps(
        {"dtype": array.dtype.str, "shape": list(array.shape)},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(descriptor)
    digest.update(array.tobytes(order="C"))
    return digest.hexdigest()


def _participant_values_from_source_psd(
    result: HaukSourcePsdResult,
    *,
    participant_id: str,
    expected_source_count: int,
) -> L2MNEHaukParticipantZScoreValues:
    if result.source_count != expected_source_count:
        raise ProjectL2MNEHaukSourcePsdExportError(
            "MNE source-PSD output source count does not match the fsaverage forward model."
        )
    return L2MNEHaukParticipantZScoreValues(
        participant_id=participant_id,
        values=np.asarray(result.values, dtype=float),
        target_source_values=np.asarray(result.zscore.target_source_amplitudes, dtype=float),
        noise_mean_values=np.asarray(result.zscore.noise_mean_values, dtype=float),
        noise_std_values=np.asarray(result.zscore.noise_std_values, dtype=float),
        noise_offsets_used=DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS,
        zero_noise_sd_source_count=result.zscore.zero_noise_sd_source_count,
    )


def _participant_values_from_cache(
    cached: SourcePsdParticipantResult | None,
    *,
    participant_id: str,
    expected_source_count: int,
) -> L2MNEHaukParticipantZScoreValues:
    if cached is None or cached.source_count != expected_source_count:
        raise ProjectL2MNEHaukSourcePsdExportError("A source-PSD cache hit has an incompatible source count.")
    # Participant identity is supplied by the validated derivative record.  It
    # is intentionally not inferred from a content-addressed cache entry,
    # because identical derivatives may legitimately share a scientific key.
    return L2MNEHaukParticipantZScoreValues(
        participant_id=participant_id,
        values=cached.values.copy(),
        target_source_values=cached.target_source_values.copy(),
        noise_mean_values=cached.noise_mean_values.copy(),
        noise_std_values=cached.noise_std_values.copy(),
        noise_offsets_used=cached.noise_offsets_used,
        zero_noise_sd_source_count=cached.zero_noise_sd_source_count,
    )


def _participant_cache_metadata(
    record: ProjectTimeDomainInputRecord,
    result: HaukSourcePsdResult,
) -> dict[str, Any]:
    return {
        "participant_id": record.participant_id,
        "group_id": record.group_id,
        "condition_id": record.condition_id,
        "condition_label": record.condition_label,
        "method_id": result.config.method_id,
        "method_version": HAUK_SOURCE_PSD_METHOD_VERSION,
        "source_orientation_mode": result.config.source_orientation_mode,
        "source_psd_frequency_count": result.source_psd_frequency_count,
        "frequency_plan": result.frequency_plan.to_metadata(),
    }


def _source_psd_method_id_for_orientation_mode(
    source_orientation_mode: str,
) -> str:
    mode = str(source_orientation_mode).strip().casefold()
    if mode == SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL:
        return HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID
    if mode == SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM:
        return HAUK_SOURCE_PSD_METHOD_ID
    raise ValueError(f"Unsupported L2-MNE source orientation mode: {source_orientation_mode!r}.")


def _precomputed_conditions(
    plan: _ProjectInputPlan,
    *,
    rows_by_condition: Mapping[str, Sequence[L2MNEHaukParticipantZScoreValues]],
) -> tuple[L2MNEHaukPrecomputedParticipantGroupCondition, ...]:
    conditions: list[L2MNEHaukPrecomputedParticipantGroupCondition] = []
    for condition in plan.conditions:
        rows = tuple(rows_by_condition.get(condition.condition_id, ()))
        expected_participants = tuple(plan.participants_by_condition.get(condition.condition_id, ()))
        if len(rows) != len(expected_participants):
            raise ProjectL2MNEHaukSourcePsdExportError(
                f"Source-PSD participant set for {condition.label} is incomplete: "
                f"{len(rows)} of {len(expected_participants)} planned maps."
            )
        if tuple(row.participant_id for row in rows) != expected_participants:
            raise ProjectL2MNEHaukSourcePsdExportError(
                f"Source-PSD participant order for {condition.label} does not match the condition-specific ledger plan."
            )
        if not rows:
            continue
        if plan.split_group_summaries:
            rows_by_participant = {row.participant_id: row for row in rows}
            for group in plan.groups:
                group_rows = tuple(
                    rows_by_participant[participant]
                    for participant in group.participants
                    if participant in rows_by_participant
                )
                if not group_rows:
                    continue
                conditions.append(
                    _precomputed_group_condition(
                        plan,
                        condition=condition,
                        participant_values=group_rows,
                        group=group,
                        split_group_summaries=True,
                    )
                )
        else:
            group = plan.groups[0] if len(plan.groups) == 1 else None
            conditions.append(
                _precomputed_group_condition(
                    plan,
                    condition=condition,
                    participant_values=rows,
                    group=group,
                    split_group_summaries=False,
                )
            )
    if not conditions:
        raise ProjectL2MNEHaukSourcePsdExportError(
            "No source-PSD group-condition maps remain after applying condition-specific participant availability."
        )
    return tuple(conditions)


def _precomputed_group_condition(
    plan: _ProjectInputPlan,
    *,
    condition: _ConditionSpec,
    participant_values: tuple[L2MNEHaukParticipantZScoreValues, ...],
    group: _ProjectGroupSpec | None,
    split_group_summaries: bool,
) -> L2MNEHaukPrecomputedParticipantGroupCondition:
    participant_ids = tuple(row.participant_id for row in participant_values)
    if not participant_ids:
        raise ProjectL2MNEHaukSourcePsdExportError(
            f"Source-PSD group summary for {condition.label} has no participants."
        )
    prepared_condition_id = (
        f"{group.group_id}_{condition.condition_id}"
        if split_group_summaries and group is not None
        else condition.condition_id
    )
    prepared_label = (
        f"{group.label} - {condition.label}" if split_group_summaries and group is not None else condition.label
    )
    return L2MNEHaukPrecomputedParticipantGroupCondition(
        condition_id=prepared_condition_id,
        label=prepared_label,
        participant_values=participant_values,
        metadata={
            "source_input": "signed_time_domain_derivative",
            "processing_fingerprint": plan.processing_fingerprint,
            "canonical_condition_id": condition.condition_id,
            "canonical_condition_label": condition.label,
            "group_split_applied": split_group_summaries,
            "group_id": None if group is None else group.group_id,
            "group_label": None if group is None else group.label,
            "group_folder": None if group is None else group.folder,
            "participant_ids": list(participant_ids),
            "participant_group_ids": {
                participant: plan.group_id_by_participant.get(participant) for participant in participant_ids
            },
            "participant_group_folders": {
                participant: plan.group_folder_by_participant.get(participant) for participant in participant_ids
            },
        },
    )


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(str(message))


__all__ = [
    "DEFAULT_PROJECT_HAUK_SOURCE_PSD_MANIFEST_NAME",
    "PROJECT_L2_MNE_HAUK_SOURCE_PSD_OUTPUT_FOLDER",
    "SOURCE_PARTICIPANT_ELIGIBILITY_POLICY",
    "SOURCE_SAMPLE_COUNT_SELECTION_POLICY",
    "ProjectL2MNEHaukSourcePsdExportError",
    "ProjectL2MNEHaukSourcePsdExportResult",
    "ProjectHaukSourcePsdConditionSpec",
    "ProjectHaukSourcePsdGroupSpec",
    "ProjectHaukSourcePsdInputPlan",
    "ProjectSourceConditionOmission",
    "ProjectSourceIneligibleParticipant",
    "active_project_hauk_source_psd_root",
    "build_project_hauk_source_psd_input_plan",
    "default_project_l2_mne_hauk_source_psd_output_dir",
    "enrich_project_hauk_source_psd_provenance",
    "log_project_source_condition_omission_summary",
    "reconcile_project_hauk_source_psd_sampling_contract",
    "resolve_project_hauk_source_psd_harmonics",
    "write_project_l2_mne_hauk_source_psd_payloads",
]

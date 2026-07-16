"""Project-level time-domain eLORETA volume source-PSD export.

This calculation-side orchestrator consumes the same committed signed
participant/condition derivatives, complete-case cohort, saved oddball
harmonics, exact FFT-bin plan, and neighboring-bin z-score implementation as
the L2-MNE source-PSD workflow.  It applies those shared rules through an
independent fsaverage volume eLORETA inverse and publishes prepared
``volume_points`` payloads.  No FullFFT workbook or renderer API is used.
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
from Tools.LORETA_Visualizer.source_producers.eloreta_volume import (
    DEFAULT_CLUSTER_ALPHA,
    DEFAULT_CLUSTER_FORMING_P_VALUE,
    DEFAULT_CLUSTER_PERMUTATION_COUNT,
    DEFAULT_CLUSTER_PERMUTATION_SEED,
    DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    ELORETAVolumeForwardModel,
    ELORETAVolumeParticipantZScoreValues,
    ELORETAVolumePrecomputedParticipantGroupCondition,
    ELORETAVolumeZScoreConfig,
    METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
    write_eloreta_volume_precomputed_participant_zscore_payloads,
)
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    ApplyInverseCallable,
    DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
    DEFAULT_HAUK_SOURCE_PSD_NOISE_OFFSETS,
    HAUK_SOURCE_PSD_METHOD_VERSION,
    HaukSourcePsdConfig,
    HaukSourcePsdResult,
    SOURCE_ORIENTATION_MODE_VECTOR_NORM,
    build_hauk_source_psd_frequency_plan,
    compute_hauk_source_psd,
)
from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
    DEFAULT_MNE_FSAVERAGE_VOLUME_POS_MM,
    MneFsaverageELORETAVolumeSourcePsdModel,
    build_mne_fsaverage_eloreta_volume_source_psd_model,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    PROJECT_SOURCE_LOCALIZATION_FOLDER,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_source_psd_export import (
    SOURCE_PARTICIPANT_ELIGIBILITY_POLICY,
    ProjectHaukSourcePsdConditionSpec,
    ProjectHaukSourcePsdGroupSpec,
    ProjectHaukSourcePsdInputPlan,
    ProjectSourceIneligibleParticipant,
    active_project_hauk_source_psd_root,
    build_project_hauk_source_psd_input_plan,
    enrich_project_hauk_source_psd_provenance,
    resolve_project_hauk_source_psd_harmonics,
)
from Tools.LORETA_Visualizer.source_producers.project_time_domain_inputs import (
    ProjectTimeDomainInputRecord,
    ProjectTimeDomainInputSet,
    load_project_time_domain_inputs,
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

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str], None]

PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_OUTPUT_FOLDER = (
    "eLORETA Hauk Source PSD Beta"
)
DEFAULT_PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_MANIFEST_NAME = (
    "project_eloreta_volume_hauk_source_psd_manifest.json"
)
DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS: Mapping[str, Any] = {
    "eps": 1e-6,
    "max_iter": 20,
    "force_equal": False,
}


class ProjectELORETAVolumeHaukSourcePsdExportError(RuntimeError):
    """Raised when strict project time-domain eLORETA export cannot proceed."""


@dataclass(frozen=True)
class ProjectELORETAVolumeHaukSourcePsdExportResult:
    """Prepared eLORETA output plus its time-domain input diagnostics."""

    project_inputs: ProjectTimeDomainInputSet
    producer_result: SourceProducerRunResult
    forward_model: ELORETAVolumeForwardModel
    selected_harmonics_hz: tuple[float, ...]
    processing_fingerprint: str
    processing_fingerprint_version: str
    included_participants: tuple[str, ...]
    excluded_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]
    source_ineligible_participants: tuple[ProjectSourceIneligibleParticipant, ...]
    cache_hit_count: int
    cache_miss_count: int
    participant_sidecar_path: Path
    validation_report_path: Path | None = None
    validation_report_markdown_path: Path | None = None
    export_model: str = METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1

    @property
    def output_dir(self) -> Path:
        return self.producer_result.output_dir

    @property
    def manifest_path(self) -> Path:
        return self.producer_result.manifest_path


@dataclass(frozen=True)
class _ValidationBinPlan:
    frequency_resolution_hz: float
    noise_window_bins: int = 10
    excluded_offsets: tuple[int, ...] = (-1, 0, 1)
    min_noise_bins: int = 4


@dataclass(frozen=True)
class _ValidationConditionSummary:
    condition: str
    input_file_count: int
    workbook_count: int
    included_subject_count: int
    included_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]


@dataclass(frozen=True)
class _ValidationReportInputs:
    project_root: Path
    selected_harmonics_hz: tuple[float, ...]
    conditions: tuple[ELORETAVolumePrecomputedParticipantGroupCondition, ...]
    excluded_subjects: tuple[str, ...]
    flagged_subjects: tuple[str, ...]
    source_ineligible_participants: tuple[Mapping[str, Any], ...]
    diagnostics: tuple[str, ...]
    bin_plan: _ValidationBinPlan
    participant_eligibility_policy: str = SOURCE_PARTICIPANT_ELIGIBILITY_POLICY
    sheet_name: str = "source-ready signed time-domain FIF"
    summaries: tuple[_ValidationConditionSummary, ...] = ()


def default_project_eloreta_volume_hauk_source_psd_output_dir(
    project_root: str | Path,
) -> Path:
    """Return the canonical project-local time-domain eLORETA output folder."""

    root = Path(project_root).expanduser().resolve()
    return (
        root
        / PROJECT_SOURCE_LOCALIZATION_FOLDER
        / PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_OUTPUT_FOLDER
    )


def write_project_eloreta_volume_hauk_source_psd_payloads(
    *,
    project: Any,
    project_root: str | Path | None = None,
    output_dir: str | Path | None = None,
    include_flagged_subjects: bool = False,
    volume_pos_mm: float = DEFAULT_MNE_FSAVERAGE_VOLUME_POS_MM,
    allow_fetch_fsaverage: bool = False,
    source_psd_model: MneFsaverageELORETAVolumeSourcePsdModel | None = None,
    selected_harmonics_hz: Sequence[float] | None = None,
    lambda2: float = DEFAULT_HAUK_SOURCE_PSD_LAMBDA2,
    method_params: Mapping[str, Any] | None = None,
    apply_inverse_func: ApplyInverseCallable | None = None,
    aggregations: Sequence[str] = DEFAULT_PARTICIPANT_ZSCORE_AGGREGATIONS,
    trim_fraction: float = DEFAULT_PARTICIPANT_ZSCORE_TRIM_FRACTION,
    cluster_mask_enabled: bool = True,
    cluster_forming_p_value: float = DEFAULT_CLUSTER_FORMING_P_VALUE,
    cluster_alpha: float = DEFAULT_CLUSTER_ALPHA,
    cluster_permutation_count: int = DEFAULT_CLUSTER_PERMUTATION_COUNT,
    cluster_permutation_seed: int = DEFAULT_CLUSTER_PERMUTATION_SEED,
    progress_callback: ProgressCallback | None = None,
) -> ProjectELORETAVolumeHaukSourcePsdExportResult:
    """Build time-domain eLORETA participant and group volume maps."""

    root = active_project_hauk_source_psd_root(
        project,
        project_root=project_root,
    )
    resolved_output = _project_output_dir(root, output_dir)
    _emit_progress(progress_callback, "Reading completed processing-ledger participants...")
    input_plan = build_project_hauk_source_psd_input_plan(
        project,
        root=root,
        include_flagged_subjects=include_flagged_subjects,
    )
    _report_source_ineligible_participants(
        input_plan,
        progress_callback=progress_callback,
    )

    _emit_progress(
        progress_callback,
        "Validating signed source-ready time-domain derivatives for eLORETA...",
    )
    project_inputs = load_project_time_domain_inputs(
        root,
        expected_inputs=input_plan.expected_inputs,
        expected_processing_fingerprint=input_plan.processing_fingerprint,
        expected_processing_fingerprint_version=(
            input_plan.processing_fingerprint_version
        ),
    )
    _emit_progress(
        progress_callback,
        (
            f"Validated {len(project_inputs.records)} participant-condition "
            "time-domain derivative(s)."
        ),
    )

    harmonics, harmonic_metadata = resolve_project_hauk_source_psd_harmonics(
        project,
        selected_harmonics_hz=selected_harmonics_hz,
        progress_callback=progress_callback,
    )
    resolved_lambda2 = float(lambda2)
    if not math.isfinite(resolved_lambda2) or resolved_lambda2 <= 0.0:
        raise ValueError("eLORETA source-PSD lambda2 must be positive and finite.")
    requested_method_params = (
        None if method_params is None else dict(method_params)
    )

    if source_psd_model is None:
        resolved_method_params = dict(
            DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS
            if requested_method_params is None
            else requested_method_params
        )
        _emit_progress(
            progress_callback,
            (
                "Building and preparing the fsaverage BioSemi64 eLORETA "
                f"volume source-PSD model ({volume_pos_mm:g} mm)..."
            ),
        )
        model = build_mne_fsaverage_eloreta_volume_source_psd_model(
            sfreq=project_inputs.sfreq_hz,
            channel_names=project_inputs.records[0].channel_names,
            volume_pos_mm=volume_pos_mm,
            allow_fetch_fsaverage=allow_fetch_fsaverage,
            prepare_inverse=True,
            lambda2=resolved_lambda2,
            method_params=resolved_method_params,
        )
    else:
        if not isinstance(
            source_psd_model,
            MneFsaverageELORETAVolumeSourcePsdModel,
        ):
            raise TypeError(
                "source_psd_model must be "
                "MneFsaverageELORETAVolumeSourcePsdModel when supplied."
            )
        model = source_psd_model
        resolved_method_params = (
            dict(model.method_params)
            if requested_method_params is None
            else requested_method_params
        )
        _emit_progress(
            progress_callback,
            "Using supplied fsaverage eLORETA volume source-PSD model.",
        )
    _validate_source_psd_model(
        model,
        project_inputs=project_inputs,
        lambda2=resolved_lambda2,
        method_params=resolved_method_params,
    )
    _emit_progress(progress_callback, "eLORETA source-PSD inverse model is ready.")

    source_psd_config = HaukSourcePsdConfig(
        selected_harmonics_hz=harmonics,
        lambda2=resolved_lambda2,
        inverse_method="eLORETA",
        method_params=resolved_method_params,
        prepared=model.prepared,
        method_id=METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
        source_orientation_mode=SOURCE_ORIENTATION_MODE_VECTOR_NORM,
        metadata={
            "harmonic_selection": harmonic_metadata,
            "processing_fingerprint": input_plan.processing_fingerprint,
            "processing_fingerprint_version": (
                input_plan.processing_fingerprint_version
            ),
            "input_derivative_format": "fpvs-source-ready-time-domain-v1",
            "source_space": "fsaverage_volume",
        },
    )
    frequency_plan = build_hauk_source_psd_frequency_plan(
        sfreq=project_inputs.sfreq_hz,
        n_times=project_inputs.n_times,
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        bin_position_tolerance=source_psd_config.bin_position_tolerance,
    )

    rows_by_condition: dict[
        str,
        list[ELORETAVolumeParticipantZScoreValues],
    ] = {condition.condition_id: [] for condition in input_plan.conditions}
    numerical_model_metadata = _numerical_model_cache_metadata(model)
    method_metadata = source_psd_config.to_metadata()
    frequency_metadata = frequency_plan.to_metadata()
    cache_hit_count = 0
    cache_miss_count = 0
    source_count = len(model.forward_model.source_points)

    for index, loaded in enumerate(project_inputs.iter_loaded_raws(), start=1):
        record = loaded.record
        _emit_progress(
            progress_callback,
            (
                f"Computing eLORETA source PSD {index}/{len(project_inputs.records)}: "
                f"{record.participant_id} / {record.condition_label}..."
            ),
        )
        key_inputs = SourcePsdCacheKeyInputs(
            derivative_checksum_sha256=record.fif_sha256,
            numerical_model_metadata=numerical_model_metadata,
            method_metadata=method_metadata,
            frequency_metadata=frequency_metadata,
        )
        lookup = load_source_psd_cache_entry(
            project_root=root,
            key_inputs=key_inputs,
        )
        if lookup.hit:
            cache_hit_count += 1
            participant_values = _participant_values_from_cache(
                lookup.result,
                participant_id=record.participant_id,
                expected_source_count=source_count,
            )
        else:
            cache_miss_count += 1
            source_psd_result = compute_hauk_source_psd(
                averaged_raw=loaded.raw,
                inverse_operator=model.inverse_operator,
                config=source_psd_config,
                apply_inverse_func=apply_inverse_func,
            )
            participant_values = _participant_values_from_source_psd(
                source_psd_result,
                participant_id=record.participant_id,
                expected_source_count=source_count,
            )
            store_source_psd_cache_entry(
                project_root=root,
                key_inputs=key_inputs,
                result=_cache_result(
                    participant_values,
                    record=record,
                    source_psd_result=source_psd_result,
                ),
            )
        rows_by_condition[record.condition_id].append(participant_values)

    prepared_conditions = _precomputed_conditions(
        input_plan,
        rows_by_condition=rows_by_condition,
    )
    output_config = ELORETAVolumeZScoreConfig(
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        method_id=METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
        lambda2=source_psd_config.lambda2,
        eloreta_method_params=resolved_method_params,
        cluster_mask_enabled=cluster_mask_enabled,
        cluster_forming_p_value=cluster_forming_p_value,
        cluster_alpha=cluster_alpha,
        cluster_permutation_count=cluster_permutation_count,
        cluster_permutation_seed=cluster_permutation_seed,
        metadata={
            "project_integration": "time_domain_eloreta_hauk_source_psd",
            "project_root_name": root.name,
            "input_domain": "signed_repetition_averaged_eeg_time_series",
            "input_derivative_root": project_inputs.input_root.relative_to(root).as_posix(),
            "processing_fingerprint": input_plan.processing_fingerprint,
            "processing_fingerprint_version": (
                input_plan.processing_fingerprint_version
            ),
            "harmonic_selection": harmonic_metadata,
            "source_psd_method_metadata": method_metadata,
            "include_flagged_subjects": bool(include_flagged_subjects),
            "participant_eligibility_policy": SOURCE_PARTICIPANT_ELIGIBILITY_POLICY,
            "included_participants": list(input_plan.participants),
            "excluded_subjects": list(
                input_plan.participant_selection.excluded_subjects
            ),
            "flagged_subjects": list(
                input_plan.participant_selection.flagged_subjects
            ),
            "source_ineligible_participants": [
                item.to_metadata()
                for item in input_plan.source_ineligible_participants
            ],
            "group_summary_policy": (
                "separate_canonical_project_groups"
                if input_plan.split_group_summaries
                else "single_project_cohort"
            ),
            "cache_hit_count": cache_hit_count,
            "cache_miss_count": cache_miss_count,
            "output_scope": "project-local",
            "legacy_fullfft_fallback": "forbidden",
        },
    )

    _emit_progress(
        progress_callback,
        "Writing participant and group eLORETA volume source-PSD payloads...",
    )
    participant_result = (
        write_eloreta_volume_precomputed_participant_zscore_payloads(
            forward_model=model.forward_model,
            conditions=prepared_conditions,
            config=output_config,
            output_dir=resolved_output,
            manifest_name=(
                DEFAULT_PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_MANIFEST_NAME
            ),
            aggregations=aggregations,
            trim_fraction=trim_fraction,
            progress_callback=progress_callback,
        )
    )
    enrich_project_hauk_source_psd_provenance(
        manifest_path=participant_result.producer_result.manifest_path,
        participant_sidecar_path=participant_result.participant_sidecar_path,
        output_dir=participant_result.producer_result.output_dir,
        method_metadata=method_metadata,
        conditions=prepared_conditions,
        included_participants=input_plan.participants,
        excluded_subjects=input_plan.participant_selection.excluded_subjects,
        flagged_subjects=input_plan.participant_selection.flagged_subjects,
        source_ineligible_participants=input_plan.source_ineligible_participants,
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

    _emit_progress(progress_callback, "Writing eLORETA source-validation report...")
    validation_inputs = _ValidationReportInputs(
        project_root=root,
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        conditions=prepared_conditions,
        excluded_subjects=input_plan.participant_selection.excluded_subjects,
        flagged_subjects=input_plan.participant_selection.flagged_subjects,
        source_ineligible_participants=tuple(
            item.to_metadata()
            for item in input_plan.source_ineligible_participants
        ),
        diagnostics=(
            f"validated_time_domain_derivatives={len(project_inputs.records)}",
            f"included_participants={len(input_plan.participants)}",
            f"source_ineligible_participants={len(input_plan.source_ineligible_participants)}",
            f"prepared_group_conditions={len(prepared_conditions)}",
            f"cache_hits={cache_hit_count}",
            f"cache_misses={cache_miss_count}",
            "inverse_method=eLORETA",
            "legacy_fullfft_fallback=forbidden",
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
                included_subjects=tuple(
                    row.participant_id for row in condition.participant_values
                ),
                flagged_subjects=tuple(
                    row.participant_id
                    for row in condition.participant_values
                    if row.participant_id
                    in input_plan.participant_selection.flagged_subjects
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
        export_model=METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
        participant_sidecar_path=participant_result.participant_sidecar_path,
        lateralization_summary_path=None,
        lateralization_summary_csv_path=None,
        forward_model_metadata=dict(model.forward_model.metadata),
    )
    result = ProjectELORETAVolumeHaukSourcePsdExportResult(
        project_inputs=project_inputs,
        producer_result=producer_result,
        forward_model=model.forward_model,
        selected_harmonics_hz=source_psd_config.selected_harmonics_hz,
        processing_fingerprint=input_plan.processing_fingerprint,
        processing_fingerprint_version=input_plan.processing_fingerprint_version,
        included_participants=input_plan.participants,
        excluded_subjects=input_plan.participant_selection.excluded_subjects,
        flagged_subjects=input_plan.participant_selection.flagged_subjects,
        source_ineligible_participants=input_plan.source_ineligible_participants,
        cache_hit_count=cache_hit_count,
        cache_miss_count=cache_miss_count,
        participant_sidecar_path=participant_result.participant_sidecar_path,
        validation_report_path=validation_report.json_path,
        validation_report_markdown_path=validation_report.markdown_path,
    )
    logger.info(
        "project_eloreta_volume_hauk_source_psd_payloads_written",
        extra={
            "project_root": str(root),
            "output_dir": str(result.output_dir),
            "manifest_path": str(result.manifest_path),
            "participant_count": len(result.included_participants),
            "source_ineligible_participant_count": len(
                result.source_ineligible_participants
            ),
            "condition_count": len(prepared_conditions),
            "cache_hit_count": cache_hit_count,
            "cache_miss_count": cache_miss_count,
            "validation_report_path": str(result.validation_report_path),
        },
    )
    return result


def _project_output_dir(
    project_root: Path,
    output_dir: str | Path | None,
) -> Path:
    target = (
        default_project_eloreta_volume_hauk_source_psd_output_dir(project_root)
        if output_dir is None
        else Path(output_dir)
    )
    if not target.is_absolute():
        target = project_root / target
    resolved = target.expanduser().resolve()
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError(
            "Project eLORETA source-PSD output directory must stay inside the project root."
        ) from exc
    if resolved == project_root:
        raise ValueError(
            "Project eLORETA source-PSD output directory cannot be the project root."
        )
    return resolved


def _report_source_ineligible_participants(
    plan: ProjectHaukSourcePsdInputPlan,
    *,
    progress_callback: ProgressCallback | None,
) -> None:
    if not plan.source_ineligible_participants:
        return
    skipped_ids = ", ".join(
        item.participant_id for item in plan.source_ineligible_participants
    )
    _emit_progress(
        progress_callback,
        (
            f"Source cohort warning: using {len(plan.participants)} eligible "
            f"participant(s); omitting {skipped_ids} from every source condition."
        ),
    )
    for item in plan.source_ineligible_participants:
        logger.warning(
            "project_eloreta_hauk_source_participant_ineligible "
            "participant=%s reason=%s detail=%s",
            item.participant_id,
            item.reason_code,
            item.detail,
        )


def _validate_source_psd_model(
    model: MneFsaverageELORETAVolumeSourcePsdModel,
    *,
    project_inputs: ProjectTimeDomainInputSet,
    lambda2: float,
    method_params: Mapping[str, Any],
) -> None:
    expected_channels = project_inputs.records[0].channel_names
    if tuple(model.forward_model.channel_names) != expected_channels:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The eLORETA volume model does not use the validated BioSemi64 channel order."
        )
    info_channels = tuple(str(name) for name in getattr(model.info, "ch_names", ()))
    if info_channels != expected_channels:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The native eLORETA inverse Info does not match the time-domain channels."
        )
    try:
        model_sfreq = float(model.info["sfreq"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The native eLORETA inverse Info has no valid sampling frequency."
        ) from exc
    if not math.isclose(
        model_sfreq,
        project_inputs.sfreq_hz,
        rel_tol=1e-9,
        abs_tol=1e-12,
    ):
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The native eLORETA inverse sampling frequency does not match the time-domain inputs."
        )
    if model.inverse_operator is None:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The eLORETA source-PSD model has no native inverse operator."
        )
    if not math.isclose(model.lambda2, float(lambda2), rel_tol=1e-12, abs_tol=1e-15):
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The eLORETA source-PSD model lambda2 does not match the requested method."
        )
    if dict(model.method_params) != dict(method_params):
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "The eLORETA source-PSD model parameters do not match the requested method."
        )


def _numerical_model_cache_metadata(
    model: MneFsaverageELORETAVolumeSourcePsdModel,
) -> dict[str, Any]:
    forward = model.forward_model
    return {
        "model_kind": "mne_fsaverage_biosemi64_eloreta_volume_source_psd",
        "model_label": forward.label,
        "coordinate_space": forward.coordinate_space,
        "channel_names": list(forward.channel_names),
        "source_count": int(len(forward.source_points)),
        "source_points_sha256": _array_sha256(forward.source_points),
        "leadfield_sha256": _array_sha256(forward.leadfield),
        "source_indices": (
            None
            if forward.source_indices is None
            else [int(value) for value in forward.source_indices]
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
) -> ELORETAVolumeParticipantZScoreValues:
    if result.source_count != expected_source_count:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "MNE eLORETA source-PSD output source count does not match the volume model."
        )
    return ELORETAVolumeParticipantZScoreValues(
        participant_id=participant_id,
        values=np.asarray(result.values, dtype=float),
        target_source_values=np.asarray(
            result.zscore.target_source_amplitudes,
            dtype=float,
        ),
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
) -> ELORETAVolumeParticipantZScoreValues:
    if cached is None or cached.source_count != expected_source_count:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            "An eLORETA source-PSD cache hit has an incompatible source count."
        )
    return ELORETAVolumeParticipantZScoreValues(
        participant_id=participant_id,
        values=cached.values.copy(),
        target_source_values=cached.target_source_values.copy(),
        noise_mean_values=cached.noise_mean_values.copy(),
        noise_std_values=cached.noise_std_values.copy(),
        noise_offsets_used=cached.noise_offsets_used,
        zero_noise_sd_source_count=cached.zero_noise_sd_source_count,
    )


def _cache_result(
    values: ELORETAVolumeParticipantZScoreValues,
    *,
    record: ProjectTimeDomainInputRecord,
    source_psd_result: HaukSourcePsdResult,
) -> SourcePsdParticipantResult:
    return SourcePsdParticipantResult(
        participant_id=values.participant_id,
        values=values.values,
        target_source_values=values.target_source_values,
        noise_mean_values=values.noise_mean_values,
        noise_std_values=values.noise_std_values,
        noise_offsets_used=values.noise_offsets_used,
        zero_noise_sd_source_count=values.zero_noise_sd_source_count,
        metadata={
            "participant_id": record.participant_id,
            "group_id": record.group_id,
            "condition_id": record.condition_id,
            "condition_label": record.condition_label,
            "method_id": METHOD_ID_ELORETA_VOLUME_HAUK_SOURCE_PSD_VECTOR_NORM_V1,
            "method_version": HAUK_SOURCE_PSD_METHOD_VERSION,
            "inverse_method": "eLORETA",
            "source_psd_frequency_count": (
                source_psd_result.source_psd_frequency_count
            ),
            "frequency_plan": source_psd_result.frequency_plan.to_metadata(),
        },
    )


def _precomputed_conditions(
    plan: ProjectHaukSourcePsdInputPlan,
    *,
    rows_by_condition: Mapping[
        str,
        Sequence[ELORETAVolumeParticipantZScoreValues],
    ],
) -> tuple[ELORETAVolumePrecomputedParticipantGroupCondition, ...]:
    participant_count = len(plan.participants)
    conditions: list[ELORETAVolumePrecomputedParticipantGroupCondition] = []
    for condition in plan.conditions:
        rows = tuple(rows_by_condition.get(condition.condition_id, ()))
        if len(rows) != participant_count:
            raise ProjectELORETAVolumeHaukSourcePsdExportError(
                f"eLORETA source-PSD participant set for {condition.label} is incomplete: "
                f"{len(rows)} of {participant_count} maps."
            )
        if tuple(row.participant_id for row in rows) != plan.participants:
            raise ProjectELORETAVolumeHaukSourcePsdExportError(
                f"eLORETA source-PSD participant order for {condition.label} "
                "does not match the ledger plan."
            )
        if plan.split_group_summaries:
            rows_by_participant = {row.participant_id: row for row in rows}
            for group in plan.groups:
                group_rows = tuple(
                    rows_by_participant[participant]
                    for participant in group.participants
                )
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
    return tuple(conditions)


def _precomputed_group_condition(
    plan: ProjectHaukSourcePsdInputPlan,
    *,
    condition: ProjectHaukSourcePsdConditionSpec,
    participant_values: tuple[ELORETAVolumeParticipantZScoreValues, ...],
    group: ProjectHaukSourcePsdGroupSpec | None,
    split_group_summaries: bool,
) -> ELORETAVolumePrecomputedParticipantGroupCondition:
    participant_ids = tuple(row.participant_id for row in participant_values)
    if not participant_ids:
        raise ProjectELORETAVolumeHaukSourcePsdExportError(
            f"eLORETA source-PSD group summary for {condition.label} has no participants."
        )
    prepared_condition_id = (
        f"{group.group_id}_{condition.condition_id}"
        if split_group_summaries and group is not None
        else condition.condition_id
    )
    prepared_label = (
        f"{group.label} - {condition.label}"
        if split_group_summaries and group is not None
        else condition.label
    )
    return ELORETAVolumePrecomputedParticipantGroupCondition(
        condition_id=prepared_condition_id,
        label=prepared_label,
        participant_values=participant_values,
        sensor_value_unit="eLORETA source-PSD amplitude",
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
                participant: plan.group_id_by_participant.get(participant)
                for participant in participant_ids
            },
            "participant_group_folders": {
                participant: plan.group_folder_by_participant.get(participant)
                for participant in participant_ids
            },
        },
    )


def _emit_progress(
    progress_callback: ProgressCallback | None,
    message: str,
) -> None:
    if progress_callback is not None:
        progress_callback(str(message))


__all__ = [
    "DEFAULT_ELORETA_SOURCE_PSD_METHOD_PARAMS",
    "DEFAULT_PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_MANIFEST_NAME",
    "PROJECT_ELORETA_VOLUME_HAUK_SOURCE_PSD_OUTPUT_FOLDER",
    "ProjectELORETAVolumeHaukSourcePsdExportError",
    "ProjectELORETAVolumeHaukSourcePsdExportResult",
    "default_project_eloreta_volume_hauk_source_psd_output_dir",
    "write_project_eloreta_volume_hauk_source_psd_payloads",
]

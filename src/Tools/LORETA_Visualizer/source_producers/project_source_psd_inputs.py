"""GUI-neutral cohort, harmonic, and provenance planning shared by source-PSD methods."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

from Main_App.processing.harmonic_selection_qc import load_processing_harmonic_selection
from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION, load_ledger
from Main_App.projects import normalize_manual_excluded_participant_conditions
from Main_App.projects.grouping import GroupConfigurationError, ProjectGroupContext, project_group_context
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import HaukSourcePsdConfig
from Tools.LORETA_Visualizer.source_producers.project_inputs import (
    ProjectSourceParticipantSelection,
    project_source_participant_selection,
)
from Tools.LORETA_Visualizer.source_producers.project_time_domain_inputs import (
    ExpectedProjectTimeDomainInput,
    ProjectTimeDomainInputSet,
)

ProgressCallback = Callable[[str], None]
SOURCE_PARTICIPANT_ELIGIBILITY_POLICY = "available_case_by_group_condition_v1"
SOURCE_SAMPLE_COUNT_SELECTION_POLICY = "unique_participant_supported_modal_sample_count_v1"


def _emit_progress(progress_callback: ProgressCallback | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(str(message))


class ProjectHaukSourcePsdInputError(RuntimeError):
    """Raised when a strict project source-PSD export cannot proceed."""


@dataclass(frozen=True)
class ProjectSourceIneligibleParticipant:
    """One participant omitted from every source condition with provenance."""

    participant_id: str
    group_id: str | None
    reason_code: str
    detail: str
    missing_condition_labels: tuple[str, ...] = ()
    source_derivative_status: str = ""

    def to_metadata(self) -> dict[str, Any]:
        """Return the durable global source-cohort omission record."""

        return {
            "participant_id": self.participant_id,
            "group_id": self.group_id,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "missing_condition_labels": list(self.missing_condition_labels),
            "source_derivative_status": self.source_derivative_status,
            "scope": "all_source_conditions",
        }


@dataclass(frozen=True)
class ProjectSourceConditionOmission:
    """One unavailable participant-condition input omitted from source maps."""

    participant_id: str
    group_id: str | None
    condition_id: str
    condition_label: str
    reason_code: str
    detail: str
    source_derivative_status: str = ""
    sampling_contract: Mapping[str, Any] | None = None

    def to_metadata(self) -> dict[str, Any]:
        """Return the durable condition-specific omission record."""

        metadata: dict[str, Any] = {
            "participant_id": self.participant_id,
            "group_id": self.group_id,
            "condition_id": self.condition_id,
            "condition_label": self.condition_label,
            "reason_code": self.reason_code,
            "detail": self.detail,
            "source_derivative_status": self.source_derivative_status,
            "scope": "source_condition",
        }
        if self.sampling_contract is not None:
            metadata["sampling_contract"] = dict(self.sampling_contract)
        return metadata


@dataclass(frozen=True)
class _ConditionSpec:
    condition_id: str
    label: str


@dataclass(frozen=True)
class _ProjectGroupSpec:
    group_id: str
    label: str
    folder: str
    participants: tuple[str, ...]


@dataclass(frozen=True)
class _ProjectParticipantSpec:
    participant_id: str
    group_id: str | None
    group_folder: str | None
    condition_ids: tuple[str, ...]
    ledger_entry: Mapping[str, Any]


@dataclass(frozen=True)
class _ProjectInputPlan:
    expected_inputs: tuple[ExpectedProjectTimeDomainInput, ...]
    conditions: tuple[_ConditionSpec, ...]
    participants: tuple[str, ...]
    participants_by_condition: Mapping[str, tuple[str, ...]]
    group_id_by_participant: Mapping[str, str | None]
    group_folder_by_participant: Mapping[str, str | None]
    groups: tuple[_ProjectGroupSpec, ...]
    split_group_summaries: bool
    processing_fingerprint: str
    processing_fingerprint_version: str
    participant_selection: ProjectSourceParticipantSelection
    source_ineligible_participants: tuple[ProjectSourceIneligibleParticipant, ...]
    source_condition_omissions: tuple[ProjectSourceConditionOmission, ...]


def log_project_source_condition_omission_summary(
    target_logger: logging.Logger,
    *,
    event_name: str,
    omissions: Sequence[ProjectSourceConditionOmission],
) -> None:
    """Log one bounded warning plus debug-level per-omission provenance."""

    omission_rows = tuple(omissions)
    if not omission_rows:
        return
    reason_counts = Counter(item.reason_code for item in omission_rows)
    condition_counts = Counter(item.condition_label for item in omission_rows)
    target_logger.warning(
        "%s omission_count=%s participant_count=%s condition_count=%s reason_counts=%s condition_counts=%s "
        "details=source_validation_report",
        event_name,
        len(omission_rows),
        len({item.participant_id.casefold() for item in omission_rows}),
        len(condition_counts),
        json.dumps(dict(sorted(reason_counts.items())), separators=(",", ":")),
        json.dumps(dict(sorted(condition_counts.items())), separators=(",", ":")),
    )
    for item in omission_rows:
        target_logger.debug(
            "%s_detail participant=%s condition=%s reason=%s detail=%s",
            event_name,
            item.participant_id,
            item.condition_id,
            item.reason_code,
            item.detail,
        )


def _active_project_root(project: Any, *, project_root: str | Path | None) -> Path:
    if project is None or not hasattr(project, "project_root"):
        raise TypeError("An active project object with project_root is required.")
    root = Path(project.project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root}")
    if project_root is not None:
        supplied = Path(project_root).expanduser().resolve()
        if supplied != root:
            raise ValueError("project_root must match the active project's canonical project_root.")
    return root


def _build_project_input_plan(
    project: Any,
    *,
    root: Path,
    include_flagged_subjects: bool,
) -> _ProjectInputPlan:
    conditions = _project_conditions(project)
    group_context = project_group_context(project)
    selection = project_source_participant_selection(
        root,
        include_flagged_subjects=include_flagged_subjects,
        project_preprocessing=(
            getattr(project, "preprocessing", None)
            if isinstance(getattr(project, "preprocessing", None), Mapping)
            else None
        ),
    )
    canonical_excluded = {participant_id.casefold(): participant_id for participant_id in selection.excluded_subjects}
    excluded = set(canonical_excluded)
    project_preprocessing = getattr(project, "preprocessing", None)
    try:
        manual_condition_exclusions = normalize_manual_excluded_participant_conditions(
            project_preprocessing.get("manual_excluded_participant_conditions")
            if isinstance(project_preprocessing, Mapping)
            else None
        )
    except ValueError as exc:
        raise ProjectHaukSourcePsdInputError(f"Project participant-condition exclusions are invalid: {exc}") from exc
    manual_condition_exclusions_by_participant = {
        participant_id.casefold(): {label.casefold() for label in labels}
        for participant_id, labels in manual_condition_exclusions.items()
    }
    ledger = load_ledger(root)
    entries = ledger.get("entries")
    if not isinstance(entries, Mapping):
        raise ProjectHaukSourcePsdInputError(
            "The processing ledger has no usable participant entries. Reprocess the project."
        )

    included: list[_ProjectParticipantSpec] = []
    ledger_excluded: list[str] = []
    source_ineligible: list[ProjectSourceIneligibleParticipant] = []
    source_condition_omissions: list[ProjectSourceConditionOmission] = []
    for ledger_key, entry_value in sorted(entries.items(), key=lambda item: str(item[0]).casefold()):
        if not isinstance(entry_value, Mapping):
            continue
        participant_id = str(entry_value.get("participant_id") or ledger_key).strip()
        if not participant_id:
            continue
        if participant_id.casefold() in excluded:
            canonical_excluded[participant_id.casefold()] = participant_id
            continue
        status = str(entry_value.get("status") or "").strip().casefold()
        if status == "excluded":
            ledger_excluded.append(participant_id)
            continue
        if status != "completed":
            raise ProjectHaukSourcePsdInputError(
                f"Source participant {participant_id} is not completed "
                f"(processing-ledger status {status or 'missing'}). Reprocess the "
                "participant successfully or exclude it explicitly before source-map generation."
            )
        declared_participant = entry_value.get("participant_id")
        if declared_participant not in (None, "") and str(declared_participant).strip() != str(ledger_key).strip():
            raise ProjectHaukSourcePsdInputError(f"Processing-ledger participant identity mismatch for {ledger_key!r}.")
        ledger_group_id = _optional_text(entry_value.get("group_id"))
        try:
            group_id, group_folder = _canonical_participant_group(
                group_context,
                participant_id=participant_id,
                ledger_group_id=ledger_group_id,
            )
        except GroupConfigurationError as exc:
            raise ProjectHaukSourcePsdInputError(
                f"Processing-ledger group metadata is invalid for {participant_id}: {exc}"
            ) from exc
        missing_conditions = _canonical_missing_conditions(
            _string_sequence(entry_value.get("missing_condition_labels")),
            conditions=conditions,
            participant_id=participant_id,
        )
        missing_condition_labels = tuple(condition.label for condition in missing_conditions)
        manually_excluded_condition_labels = manual_condition_exclusions_by_participant.get(
            participant_id.casefold(),
            set(),
        )
        manually_excluded_conditions = tuple(
            condition for condition in conditions if condition.label.casefold() in manually_excluded_condition_labels
        )
        completeness = str(entry_value.get("condition_completeness") or "complete").casefold()
        source_derivative_status = str(entry_value.get("source_derivative_status") or "").strip()
        source_derivative_status_key = source_derivative_status.casefold()
        if completeness != "complete" and not missing_conditions:
            detail = (
                f"Condition completeness is {completeness!r}, but the processing "
                "ledger does not identify which canonical conditions are unavailable."
            )
            source_ineligible.append(
                ProjectSourceIneligibleParticipant(
                    participant_id=participant_id,
                    group_id=group_id,
                    reason_code="incomplete_condition_set",
                    detail=detail,
                    source_derivative_status=source_derivative_status,
                )
            )
            continue
        if len(missing_conditions) == len(conditions):
            detail = "Missing canonical condition output(s): " + ", ".join(missing_condition_labels)
            source_ineligible.append(
                ProjectSourceIneligibleParticipant(
                    participant_id=participant_id,
                    group_id=group_id,
                    reason_code="incomplete_condition_set",
                    detail=detail,
                    missing_condition_labels=missing_condition_labels,
                    source_derivative_status=source_derivative_status,
                )
            )
            continue
        unavailable_condition_ids = {
            condition.condition_id for condition in (*missing_conditions, *manually_excluded_conditions)
        }
        if len(unavailable_condition_ids) == len(conditions):
            unavailable_labels = tuple(
                condition.label for condition in conditions if condition.condition_id in unavailable_condition_ids
            )
            source_ineligible.append(
                ProjectSourceIneligibleParticipant(
                    participant_id=participant_id,
                    group_id=group_id,
                    reason_code="no_available_source_conditions",
                    detail=(
                        "No canonical source condition remains after processing-ledger "
                        "availability and saved project participant-condition exclusions."
                    ),
                    missing_condition_labels=unavailable_labels,
                    source_derivative_status=source_derivative_status,
                )
            )
            continue
        if source_derivative_status_key and source_derivative_status_key != "complete" and not missing_conditions:
            source_warning = str(entry_value.get("source_derivative_warning") or "").strip()
            detail = source_warning or (
                f"Source-ready time-domain derivative status is {source_derivative_status_key!r}, not complete."
            )
            source_ineligible.append(
                ProjectSourceIneligibleParticipant(
                    participant_id=participant_id,
                    group_id=group_id,
                    reason_code="source_derivative_incomplete",
                    detail=detail,
                    source_derivative_status=source_derivative_status_key,
                )
            )
            continue
        expected_outputs = entry_value.get("expected_outputs")
        if (
            not isinstance(expected_outputs, Sequence)
            or isinstance(expected_outputs, (str, bytes))
            or len(expected_outputs) != len(conditions)
        ):
            raise ProjectHaukSourcePsdInputError(
                f"Processing-ledger condition expectations for {participant_id} do not match the active project. "
                "Reprocess the project before source-map generation."
            )
        missing_condition_ids = {condition.condition_id for condition in missing_conditions}
        manual_condition_ids = {condition.condition_id for condition in manually_excluded_conditions}
        available_condition_ids = tuple(
            condition.condition_id
            for condition in conditions
            if condition.condition_id not in (missing_condition_ids | manual_condition_ids)
        )
        source_warning = str(entry_value.get("source_derivative_warning") or "").strip()
        for condition in missing_conditions:
            source_condition_omissions.append(
                ProjectSourceConditionOmission(
                    participant_id=participant_id,
                    group_id=group_id,
                    condition_id=condition.condition_id,
                    condition_label=condition.label,
                    reason_code="missing_canonical_condition_output",
                    detail=source_warning
                    or (f"Processing ledger reports no completed output for canonical condition {condition.label!r}."),
                    source_derivative_status=source_derivative_status,
                )
            )
        for condition in manually_excluded_conditions:
            if condition.condition_id in missing_condition_ids:
                continue
            source_condition_omissions.append(
                ProjectSourceConditionOmission(
                    participant_id=participant_id,
                    group_id=group_id,
                    condition_id=condition.condition_id,
                    condition_label=condition.label,
                    reason_code="excluded_participant_condition",
                    detail=("Excluded by the project's saved participant-condition QC decision."),
                    source_derivative_status=source_derivative_status,
                )
            )
        included.append(
            _ProjectParticipantSpec(
                participant_id=participant_id,
                group_id=group_id,
                group_folder=group_folder,
                condition_ids=available_condition_ids,
                ledger_entry=entry_value,
            )
        )

    if not included:
        skipped_detail = "; ".join(f"{item.participant_id}: {item.detail}" for item in source_ineligible)
        suffix = f" Source-ineligible participants: {skipped_detail}" if skipped_detail else ""
        raise ProjectHaukSourcePsdInputError(
            "No completed, source-eligible participants remain after project exclusions." + suffix
        )
    for participant_id in ledger_excluded:
        canonical_excluded[participant_id.casefold()] = participant_id
    selection = ProjectSourceParticipantSelection(
        excluded_subjects=tuple(sorted(canonical_excluded.values(), key=str.casefold)),
        flagged_subjects=selection.flagged_subjects,
    )

    fingerprints = {str(item.ledger_entry.get("processing_fingerprint") or "").strip() for item in included}
    versions = {str(item.ledger_entry.get("processing_fingerprint_version") or "").strip() for item in included}
    if "" in fingerprints or len(fingerprints) != 1:
        raise ProjectHaukSourcePsdInputError(
            "Completed source participants do not share one current processing fingerprint. "
            "Reprocess stale participants before source-map generation."
        )
    if versions != {PROCESSING_FINGERPRINT_VERSION}:
        raise ProjectHaukSourcePsdInputError(
            "Completed source participants do not use the current processing fingerprint version. "
            "Reprocess the project before source-map generation."
        )
    fingerprint = next(iter(fingerprints))
    version = next(iter(versions))

    expected: list[ExpectedProjectTimeDomainInput] = []
    group_lookup: dict[str, str | None] = {}
    group_folder_lookup: dict[str, str | None] = {}
    participants: list[str] = []
    participants_by_condition: dict[str, list[str]] = {condition.condition_id: [] for condition in conditions}
    conditions_by_id = {condition.condition_id: condition for condition in conditions}
    for item in included:
        participant_id = item.participant_id
        group_id = item.group_id
        group_folder = item.group_folder
        participants.append(participant_id)
        group_lookup[participant_id] = group_id
        group_folder_lookup[participant_id] = group_folder
        for condition_id in item.condition_ids:
            condition = conditions_by_id[condition_id]
            participants_by_condition[condition_id].append(participant_id)
            expected.append(
                ExpectedProjectTimeDomainInput(
                    participant_id=participant_id,
                    group_id=group_id,
                    group_folder=group_folder,
                    condition_id=condition.condition_id,
                    condition_label=condition.label,
                )
            )
    project_groups = tuple(
        _ProjectGroupSpec(
            group_id=group.group_id,
            label=group.label,
            folder=group.folder_name,
            participants=tuple(
                participant for participant in participants if group_lookup.get(participant) == group.group_id
            ),
        )
        for group in group_context.groups
        if any(group_lookup.get(participant) == group.group_id for participant in participants)
    )
    return _ProjectInputPlan(
        expected_inputs=tuple(expected),
        conditions=conditions,
        participants=tuple(participants),
        participants_by_condition={
            condition_id: tuple(condition_participants)
            for condition_id, condition_participants in participants_by_condition.items()
        },
        group_id_by_participant=dict(group_lookup),
        group_folder_by_participant=dict(group_folder_lookup),
        groups=project_groups,
        split_group_summaries=group_context.is_multi_group,
        processing_fingerprint=fingerprint,
        processing_fingerprint_version=version,
        participant_selection=selection,
        source_ineligible_participants=tuple(source_ineligible),
        source_condition_omissions=tuple(source_condition_omissions),
    )


def _project_conditions(project: Any) -> tuple[_ConditionSpec, ...]:
    event_map = getattr(project, "event_map", None)
    if not isinstance(event_map, Mapping) or not event_map:
        raise ProjectHaukSourcePsdInputError("The active project has no canonical condition/event mapping.")
    conditions: list[_ConditionSpec] = []
    seen_ids: set[str] = set()
    for raw_label, raw_event_id in event_map.items():
        label = str(raw_label).strip()
        if not label:
            raise ProjectHaukSourcePsdInputError("Project condition labels cannot be empty.")
        try:
            event_id = int(raw_event_id)
        except (TypeError, ValueError) as exc:
            raise ProjectHaukSourcePsdInputError(
                f"Project condition {label!r} has an invalid event ID: {raw_event_id!r}."
            ) from exc
        if event_id <= 0:
            raise ProjectHaukSourcePsdInputError(f"Project condition {label!r} must use a positive event ID.")
        condition_id = str(event_id)
        if condition_id in seen_ids:
            raise ProjectHaukSourcePsdInputError(
                f"Project conditions must use unique event IDs; duplicate {condition_id}."
            )
        seen_ids.add(condition_id)
        conditions.append(_ConditionSpec(condition_id=condition_id, label=label))
    return tuple(conditions)


def _canonical_missing_conditions(
    missing_condition_labels: Sequence[str],
    *,
    conditions: Sequence[_ConditionSpec],
    participant_id: str,
) -> tuple[_ConditionSpec, ...]:
    if not missing_condition_labels:
        return ()
    conditions_by_label: dict[str, _ConditionSpec] = {}
    for condition in conditions:
        key = condition.label.casefold()
        if key in conditions_by_label:
            raise ProjectHaukSourcePsdInputError(
                "Project condition labels must be unique when compared case-insensitively for source-map generation."
            )
        conditions_by_label[key] = condition
    unknown_labels = tuple(label for label in missing_condition_labels if label.casefold() not in conditions_by_label)
    if unknown_labels:
        raise ProjectHaukSourcePsdInputError(
            f"Processing-ledger missing-condition metadata for {participant_id} "
            "references unknown canonical condition label(s): "
            + ", ".join(unknown_labels)
            + ". Reprocess the participant before source-map generation."
        )
    missing_keys = {label.casefold() for label in missing_condition_labels}
    return tuple(condition for condition in conditions if condition.label.casefold() in missing_keys)


def _canonical_participant_group(
    context: ProjectGroupContext,
    *,
    participant_id: str,
    ledger_group_id: str | None,
) -> tuple[str | None, str | None]:
    if not context.has_group_metadata:
        if ledger_group_id is not None:
            raise GroupConfigurationError(f"ledger group_id {ledger_group_id!r} is present in an ungrouped project.")
        return None, None
    try:
        participant = context.participant(participant_id)
    except GroupConfigurationError as exc:
        raise GroupConfigurationError("a grouped source participant must be registered in project.json.") from exc
    if participant.group_id is None:
        raise GroupConfigurationError("a grouped source participant requires a canonical group_id in project.json.")
    if ledger_group_id != participant.group_id:
        raise GroupConfigurationError(
            f"ledger group_id {ledger_group_id!r} does not match canonical "
            f"project.json group_id {participant.group_id!r}."
        )
    group = context.group(participant.group_id)
    return group.group_id, group.folder_name


def _resolve_selected_harmonics(
    project: Any,
    *,
    selected_harmonics_hz: Sequence[float] | None,
    progress_callback: ProgressCallback | None,
) -> tuple[tuple[float, ...], dict[str, Any]]:
    if selected_harmonics_hz is not None:
        harmonics = HaukSourcePsdConfig(
            selected_harmonics_hz=tuple(float(value) for value in selected_harmonics_hz)
        ).selected_harmonics_hz
        return harmonics, {
            "source": "explicit_test_injection",
            "selected_harmonics_hz": list(harmonics),
            "exploratory": True,
        }

    _emit_progress(progress_callback, "Loading processing-time selected significant harmonics...")
    selection = load_processing_harmonic_selection(
        project,
        log_func=(
            (lambda message: _emit_progress(progress_callback, message)) if progress_callback is not None else None
        ),
    )
    metadata = dict(selection.to_metadata())
    selection_z_by_harmonic = metadata.get("selection_z_by_harmonic")
    if isinstance(selection_z_by_harmonic, Mapping):
        normalized_z_by_harmonic: dict[str, Any] = {}
        for frequency, z_score in selection_z_by_harmonic.items():
            frequency_key = str(frequency)
            if frequency_key in normalized_z_by_harmonic:
                raise ProjectHaukSourcePsdInputError(
                    "Saved harmonic-selection metadata contains ambiguous frequency keys."
                )
            normalized_z_by_harmonic[frequency_key] = z_score
        metadata["selection_z_by_harmonic"] = normalized_z_by_harmonic
    harmonics = HaukSourcePsdConfig(selected_harmonics_hz=tuple(selection.selected_harmonics_hz)).selected_harmonics_hz
    metadata["source"] = "saved_processing_harmonics"
    metadata["selected_harmonics_hz"] = list(harmonics)
    metadata["exploratory"] = False
    return harmonics, metadata


def _enrich_source_psd_provenance(
    *,
    manifest_path: Path,
    participant_sidecar_path: Path,
    output_dir: Path,
    method_metadata: Mapping[str, Any],
    conditions: Sequence[Any],
    included_participants: Sequence[str],
    excluded_subjects: Sequence[str],
    flagged_subjects: Sequence[str],
    source_ineligible_participants: Sequence[ProjectSourceIneligibleParticipant],
    source_condition_omissions: Sequence[ProjectSourceConditionOmission],
    source_sample_count_n_times: int,
    source_sample_count_omission_count: int,
) -> None:
    condition_provenance = {condition.condition_id: _condition_group_provenance(condition) for condition in conditions}
    split_group_summaries = any(
        bool(provenance.get("group_split_applied")) for provenance in condition_provenance.values()
    )
    provenance = {
        "source_psd_method": dict(method_metadata),
        "reference_publication_doi": method_metadata.get("reference_publication_doi"),
        "reference_code_repository": method_metadata.get("reference_code_repository"),
        "reference_method_relation": method_metadata.get("reference_method_relation"),
        "group_summary_policy": (
            "separate_canonical_project_groups" if split_group_summaries else "single_project_cohort"
        ),
        "participant_eligibility_policy": SOURCE_PARTICIPANT_ELIGIBILITY_POLICY,
        "included_participants": list(included_participants),
        "excluded_subjects": list(excluded_subjects),
        "flagged_subjects": list(flagged_subjects),
        "source_ineligible_participants": [item.to_metadata() for item in source_ineligible_participants],
        "source_condition_omissions": [item.to_metadata() for item in source_condition_omissions],
        "source_sample_count_selection_policy": (SOURCE_SAMPLE_COUNT_SELECTION_POLICY),
        "source_sample_count_n_times": int(source_sample_count_n_times),
        "source_sample_count_omission_count": int(source_sample_count_omission_count),
    }
    for path in (manifest_path, participant_sidecar_path):
        target = Path(path).resolve()
        output_root = Path(output_dir).resolve()
        try:
            target.relative_to(output_root)
        except ValueError as exc:
            raise ProjectHaukSourcePsdInputError(
                f"Refusing to enrich source provenance outside the output directory: {target}"
            ) from exc
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectHaukSourcePsdInputError(f"Unable to read generated source provenance file: {target}") from exc
        if not isinstance(payload, dict):
            raise ProjectHaukSourcePsdInputError(
                f"Generated source provenance file must contain a JSON object: {target}"
            )
        existing_metadata = payload.get("metadata")
        metadata = dict(existing_metadata) if isinstance(existing_metadata, Mapping) else {}
        metadata.update(provenance)
        payload["metadata"] = metadata
        condition_rows = payload.get("conditions")
        if isinstance(condition_rows, list):
            for row in condition_rows:
                if not isinstance(row, dict):
                    continue
                condition_id = str(row.get("condition_id") or row.get("id") or "")
                condition_metadata = _matching_condition_group_provenance(
                    condition_id,
                    condition_provenance=condition_provenance,
                )
                if condition_metadata is None:
                    continue
                row_metadata = row.get("metadata")
                merged_row_metadata = dict(row_metadata) if isinstance(row_metadata, Mapping) else {}
                merged_row_metadata["project_group"] = condition_metadata
                row["metadata"] = merged_row_metadata
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            _replace_file(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def _condition_group_provenance(
    condition: Any,
) -> dict[str, Any]:
    metadata = condition.metadata
    return {
        "group_id": metadata.get("group_id"),
        "group_label": metadata.get("group_label"),
        "group_folder": metadata.get("group_folder"),
        "group_split_applied": bool(metadata.get("group_split_applied")),
        "canonical_condition_id": metadata.get("canonical_condition_id"),
        "canonical_condition_label": metadata.get("canonical_condition_label"),
        "participant_ids": [row.participant_id for row in condition.participant_values],
    }


def _matching_condition_group_provenance(
    condition_id: str,
    *,
    condition_provenance: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    matches = [
        (prepared_id, provenance)
        for prepared_id, provenance in condition_provenance.items()
        if condition_id == prepared_id or condition_id.startswith(f"{prepared_id}_")
    ]
    if not matches:
        return None
    _prepared_id, provenance = max(matches, key=lambda item: len(item[0]))
    return dict(provenance)


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if not isinstance(value, Sequence):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _optional_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def _windows_filesystem_path(path: str | Path) -> str:
    """Return an absolute path suitable for long Windows filesystem calls."""

    value = os.path.abspath(os.fspath(path))
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    if re.match(r"^[A-Za-z]:[\\\\/]", value):
        return "\\\\?\\" + value
    return value


def _replace_file(source: str | Path, destination: str | Path) -> None:
    """Atomically replace a file, tolerating brief Windows scanner locks."""

    for attempt in range(5):  # noqa: PERF203 - replacement failures are transient on Windows.
        try:
            os.replace(
                _windows_filesystem_path(source),
                _windows_filesystem_path(destination),
            )
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def active_project_hauk_source_psd_root(
    project: Any,
    *,
    project_root: str | Path | None = None,
) -> Path:
    """Return the canonical active-project root shared by source-PSD methods."""

    return _active_project_root(project, project_root=project_root)


def build_project_hauk_source_psd_input_plan(
    project: Any,
    *,
    root: Path,
    include_flagged_subjects: bool,
) -> ProjectHaukSourcePsdInputPlan:
    """Build the shared available-case ledger/condition plan."""

    return _build_project_input_plan(
        project,
        root=root,
        include_flagged_subjects=include_flagged_subjects,
    )


def reconcile_project_hauk_source_psd_sampling_contract(
    plan: ProjectHaukSourcePsdInputPlan,
    *,
    project_inputs: ProjectTimeDomainInputSet,
) -> ProjectHaukSourcePsdInputPlan:
    """Apply central time-domain sampling omissions to the shared cohort plan."""

    omitted_records = tuple(project_inputs.sampling_contract_omissions)
    if not omitted_records:
        return plan

    omitted_keys = {record.key for record in omitted_records}
    expected_inputs = tuple(item for item in plan.expected_inputs if item.key not in omitted_keys)
    participants_by_condition = {
        condition_id: tuple(
            participant_id
            for participant_id in participant_ids
            if (
                plan.group_id_by_participant.get(participant_id),
                participant_id,
                condition_id,
            )
            not in omitted_keys
        )
        for condition_id, participant_ids in plan.participants_by_condition.items()
    }
    active_participants = {record.participant_id for record in project_inputs.records}
    participants = tuple(
        participant_id for participant_id in plan.participants if participant_id in active_participants
    )
    groups = tuple(
        replace(
            group,
            participants=tuple(
                participant_id for participant_id in group.participants if participant_id in active_participants
            ),
        )
        for group in plan.groups
        if any(participant_id in active_participants for participant_id in group.participants)
    )
    canonical_duration_sec = project_inputs.n_times / project_inputs.sfreq_hz
    sampling_omissions = tuple(
        ProjectSourceConditionOmission(
            participant_id=record.participant_id,
            group_id=record.group_id,
            condition_id=record.condition_id,
            condition_label=record.condition_label,
            reason_code="noncanonical_source_sample_count",
            detail=(
                "Source-ready derivative has "
                f"N={record.n_times} ({record.duration_sec:g} s, "
                f"df={record.frequency_resolution_hz:.12g} Hz), while the unique "
                f"modal source contract is N={project_inputs.n_times} "
                f"({canonical_duration_sec:g} s, "
                f"df={project_inputs.frequency_resolution_hz:.12g} Hz). "
                "This participant-condition was omitted so every retained source "
                "z-score uses the same exact FFT and neighboring-noise-bin contract."
            ),
            source_derivative_status="noncanonical_sample_count",
            sampling_contract={
                "selection_policy": SOURCE_SAMPLE_COUNT_SELECTION_POLICY,
                "actual": {
                    "n_times": record.n_times,
                    "duration_sec": record.duration_sec,
                    "frequency_resolution_hz": record.frequency_resolution_hz,
                },
                "canonical": {
                    "n_times": project_inputs.n_times,
                    "duration_sec": canonical_duration_sec,
                    "frequency_resolution_hz": project_inputs.frequency_resolution_hz,
                },
            },
        )
        for record in omitted_records
    )
    return replace(
        plan,
        expected_inputs=expected_inputs,
        participants=participants,
        participants_by_condition=participants_by_condition,
        group_id_by_participant={
            participant_id: group_id
            for participant_id, group_id in plan.group_id_by_participant.items()
            if participant_id in active_participants
        },
        group_folder_by_participant={
            participant_id: group_folder
            for participant_id, group_folder in plan.group_folder_by_participant.items()
            if participant_id in active_participants
        },
        groups=groups,
        source_condition_omissions=(
            *plan.source_condition_omissions,
            *sampling_omissions,
        ),
    )


def resolve_project_hauk_source_psd_harmonics(
    project: Any,
    *,
    selected_harmonics_hz: Sequence[float] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[tuple[float, ...], dict[str, Any]]:
    """Resolve the same saved oddball-harmonic selection for every inverse."""

    return _resolve_selected_harmonics(
        project,
        selected_harmonics_hz=selected_harmonics_hz,
        progress_callback=progress_callback,
    )


def enrich_project_hauk_source_psd_provenance(
    *,
    manifest_path: Path,
    participant_sidecar_path: Path,
    output_dir: Path,
    method_metadata: Mapping[str, Any],
    conditions: Sequence[Any],
    included_participants: Sequence[str],
    excluded_subjects: Sequence[str],
    flagged_subjects: Sequence[str],
    source_ineligible_participants: Sequence[ProjectSourceIneligibleParticipant],
    source_condition_omissions: Sequence[ProjectSourceConditionOmission],
    source_sample_count_n_times: int,
    source_sample_count_omission_count: int,
) -> None:
    """Add shared cohort/method provenance to a source-PSD manifest and sidecar."""

    _enrich_source_psd_provenance(
        manifest_path=manifest_path,
        participant_sidecar_path=participant_sidecar_path,
        output_dir=output_dir,
        method_metadata=method_metadata,
        conditions=conditions,
        included_participants=included_participants,
        excluded_subjects=excluded_subjects,
        flagged_subjects=flagged_subjects,
        source_ineligible_participants=source_ineligible_participants,
        source_condition_omissions=source_condition_omissions,
        source_sample_count_n_times=source_sample_count_n_times,
        source_sample_count_omission_count=source_sample_count_omission_count,
    )


ProjectHaukSourcePsdConditionSpec = _ConditionSpec
ProjectHaukSourcePsdGroupSpec = _ProjectGroupSpec
ProjectHaukSourcePsdInputPlan = _ProjectInputPlan

"""Project-wide frequency-domain QC and exclusion metadata helpers."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from Main_App.processing.frequency_qc_identity import (
    resolve_frequency_qc_recording_decisions,
)
from Main_App.projects import ProjectDatasetIndex, load_project_dataset_index
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recordings,
    normalize_preprocessing_settings,
)

logger = logging.getLogger(__name__)

QUALITY_CHECK_FOLDER = "Quality Check"
FREQUENCY_DOMAIN_QC_REPORT_NAME = "Frequency_Domain_QC_Review.txt"
FREQUENCY_DOMAIN_QC_METADATA_PATH = ("tools", "frequency_domain_qc")
FREQUENCY_DOMAIN_QC_SCHEMA_VERSION = 1
FREQUENCY_DOMAIN_QC_METHOD_VERSION = "summed_bca_plausibility_v1"
REPEATED_FREQUENCY_DOMAIN_QC_METHOD_VERSION = (
    "summed_bca_plausibility_recording_v1"
)

WARNING_REASON_UNUSUAL_VALUES = "Unusual frequency-domain values"
WARNING_REASON_NOISY_SPECTRUM = "Noisy spectrum"
WARNING_REASON_KNOWN_ACQUISITION = "Known acquisition issue"
WARNING_REASON_OTHER = "Other reviewed concern"
MANUAL_EXCLUSION_REASONS = (
    WARNING_REASON_UNUSUAL_VALUES,
    WARNING_REASON_NOISY_SPECTRUM,
    WARNING_REASON_KNOWN_ACQUISITION,
    WARNING_REASON_OTHER,
)


@dataclass(frozen=True)
class FrequencyDomainQcThresholds:
    warning_summed_bca_uv: float = 10.0
    strong_warning_summed_bca_uv: float = 50.0
    hard_electrode_summed_bca_uv: float = 250.0
    repeated_warning_cells: int = 5
    hard_participant_unique_electrodes: int = 10

    def to_manifest(self) -> dict[str, object]:
        return {
            "warning_summed_bca_uv": float(self.warning_summed_bca_uv),
            "strong_warning_summed_bca_uv": float(self.strong_warning_summed_bca_uv),
            "hard_electrode_summed_bca_uv": float(self.hard_electrode_summed_bca_uv),
            "repeated_warning_cells": int(self.repeated_warning_cells),
            "hard_participant_unique_electrodes": int(
                self.hard_participant_unique_electrodes
            ),
        }


DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS = FrequencyDomainQcThresholds()


@dataclass(frozen=True)
class FrequencyDomainExclusions:
    excluded_participants: frozenset[str]
    auto_excluded_participants: frozenset[str]
    manual_excluded_participants: frozenset[str]
    auto_excluded_electrodes_by_participant: dict[str, frozenset[str]]
    downstream_outputs_stale: bool
    excluded_recordings: frozenset[str] = frozenset()
    auto_excluded_recordings: frozenset[str] = frozenset()
    manual_excluded_recordings: frozenset[str] = frozenset()
    auto_excluded_electrodes_by_recording: dict[str, frozenset[str]] = field(
        default_factory=dict
    )


def run_frequency_domain_qc_review(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
    dataset_index: ProjectDatasetIndex | None = None,
) -> dict[str, object]:
    """Build a provisional summed-BCA QC report for the active project."""

    def _log(message: str) -> None:
        if log_func is not None:
            log_func(str(message))

    project_root = Path(project.project_root).resolve()
    thresholds = DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS
    from Main_App.processing.roi_settings import load_rois_from_settings

    if dataset_index is None:
        dataset_index = load_project_dataset_index(project_root)
    elif dataset_index.project_root.resolve() != project_root:
        raise ValueError(
            "The supplied dataset index belongs to a different project root."
        )
    conditions = list(dataset_index.conditions)
    repeated_session = dataset_index.is_repeated_session
    recording_assignments: dict[str, dict[str, object]] = {}
    if repeated_session:
        subjects = list(dataset_index.recording_ids)
        subject_data = dataset_index.recording_data(require_group_assignment=True)
        recording_assignments = _recording_assignments_from_index(dataset_index)
    else:
        subjects = list(dataset_index.participant_ids)
        subject_data = dataset_index.subject_data(require_group_assignment=True)
    subjects, subject_data = _filter_to_completed_subjects(
        project_root=project_root,
        subjects=subjects,
        subject_data=subject_data,
    )
    if repeated_session:
        subjects = _filter_preprocessing_manual_recording_exclusions(
            project,
            subjects,
            recording_assignments=recording_assignments,
        )
    else:
        subjects = _filter_preprocessing_manual_exclusions(project, subjects)
    subject_data = {
        subject: dict(subject_data.get(subject, {}))
        for subject in subjects
        if subject_data.get(subject)
    }
    ordered_conditions = _ordered_conditions(project, conditions)
    subject_data = _filter_subject_data(subject_data, ordered_conditions)
    subjects = [subject for subject in subjects if subject_data.get(subject)]
    if not subjects or not ordered_conditions:
        raise RuntimeError(
            "Frequency-domain QC could not find completed condition workbooks."
        )

    rois = load_rois_from_settings() or {}
    settings = _harmonic_selection_settings(project)
    selected_harmonics, provisional_metadata = _provisional_harmonics(
        project_root=project_root,
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        rois=rois,
        settings=settings,
        log_func=_log,
        recording_assignments=(recording_assignments if repeated_session else None),
        declared_session_ids=(
            tuple(session.session_id for session in dataset_index.ordered_sessions)
            if repeated_session
            else None
        ),
        participant_group_ids=(
            dataset_index.participant_group_id_map()
            if repeated_session
            else None
        ),
        declared_group_ids=(
            tuple(group.group_id for group in dataset_index.ordered_groups)
            if repeated_session
            else None
        ),
    )
    _log(
        "Frequency-domain QC is reviewing provisional summed BCA values "
        f"across {len(selected_harmonics)} harmonic(s)."
    )
    flags = _collect_summed_bca_flags(
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        selected_harmonics=selected_harmonics,
        thresholds=thresholds,
        log_func=_log,
        recording_assignments=(recording_assignments if repeated_session else None),
    )
    if repeated_session:
        summaries, auto_electrodes, auto_participants = _summarize_recording_flags(
            flags,
            thresholds,
        )
    else:
        summaries, auto_electrodes, auto_participants = _summarize_flags(
            flags,
            thresholds,
        )
    analysis_fingerprint = _analysis_fingerprint(
        project_root=project_root,
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        selected_harmonics=selected_harmonics,
        thresholds=thresholds,
        flags=flags,
        recording_assignments=(recording_assignments if repeated_session else None),
    )
    state = load_frequency_domain_qc_state(project_root)
    current_auto_electrodes = _auto_electrode_entries_from_state(state)
    current_auto_participants = _auto_participant_entries_from_state(state)
    current_manual = _manual_entries_from_state(state)
    current_auto_recording_electrodes = _auto_recording_electrode_entries_from_state(
        state
    )
    current_auto_recordings = _auto_recording_entries_from_state(state)
    current_manual_recordings = _manual_recording_entries_from_state(state)
    current_decision_fingerprint = _decision_fingerprint(
        analysis_fingerprint=analysis_fingerprint,
        auto_electrodes=current_auto_electrodes,
        auto_participants=current_auto_participants,
        manual_participants=current_manual,
        auto_recording_electrodes=(
            current_auto_recording_electrodes if repeated_session else None
        ),
        auto_recordings=(current_auto_recordings if repeated_session else None),
        manual_recordings=(current_manual_recordings if repeated_session else None),
    )
    last_review = state.get("last_review")
    reviewed_decision_fingerprint = ""
    if isinstance(last_review, Mapping):
        reviewed_decision_fingerprint = str(last_review.get("decision_fingerprint") or "")

    pause_subjects = [
        summary
        for summary in summaries
        if bool(summary.get("pause_review"))
    ]
    review_reused = bool(
        pause_subjects
        and reviewed_decision_fingerprint
        and reviewed_decision_fingerprint == current_decision_fingerprint
    )
    review_required = bool(pause_subjects and not review_reused)
    report: dict[str, object] = {
        "schema_version": FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
        "method_version": (
            REPEATED_FREQUENCY_DOMAIN_QC_METHOD_VERSION
            if repeated_session
            else FREQUENCY_DOMAIN_QC_METHOD_VERSION
        ),
        "project_root": str(project_root),
        "thresholds": thresholds.to_manifest(),
        "subjects": list(subjects),
        "conditions": list(ordered_conditions),
        "selected_harmonics_hz": list(selected_harmonics),
        "harmonic_policy": settings.name,
        "provisional_harmonic_metadata": provisional_metadata,
        "flags": flags,
        "participant_summaries": summaries,
        "auto_participant_electrode_exclusions": auto_electrodes,
        "auto_participant_exclusions": auto_participants,
        "manual_participant_exclusions": current_manual,
        "analysis_fingerprint": analysis_fingerprint,
        "current_decision_fingerprint": current_decision_fingerprint,
        "review_required": review_required,
        "review_reused": review_reused,
        "review_subject_count": len(pause_subjects),
        "generated_at": _now_utc_iso(),
    }
    if repeated_session:
        report.update(
            {
                "identity_scope": "recording",
                "subjects": sorted(
                    {
                        str(recording_assignments[recording_id]["participant_id"])
                        for recording_id in subjects
                    },
                    key=str.casefold,
                ),
                "recordings": list(subjects),
                "recording_assignments": [
                    dict(recording_assignments[recording_id])
                    for recording_id in subjects
                ],
                "recording_summaries": summaries,
                "participant_summaries": [],
                "auto_recording_electrode_exclusions": auto_electrodes,
                "auto_recording_exclusions": auto_participants,
                "manual_recording_exclusions": current_manual_recordings,
                "auto_participant_electrode_exclusions": current_auto_electrodes,
                "auto_participant_exclusions": current_auto_participants,
                "review_recording_count": len(pause_subjects),
            }
        )
    return report


def apply_frequency_domain_qc_decision(
    project_root: str | Path,
    report: Mapping[str, object],
    *,
    manual_participant_reasons: Mapping[str, str] | None = None,
    manual_recording_reasons: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Persist a reviewed QC decision and write the human-readable report."""

    resolved_recording_decisions = resolve_frequency_qc_recording_decisions(
        report,
        manual_recording_reasons,
    )
    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    now = _now_utc_iso()
    repeated_session = str(report.get("identity_scope") or "") == "recording"
    auto_electrodes = _normalize_auto_electrode_entries(
        report.get("auto_participant_electrode_exclusions")
    )
    auto_participants = _normalize_auto_participant_entries(
        report.get("auto_participant_exclusions")
    )
    auto_recording_electrodes = _normalize_auto_recording_electrode_entries(
        report.get("auto_recording_electrode_exclusions")
    )
    auto_recordings = _normalize_auto_recording_entries(
        report.get("auto_recording_exclusions")
    )
    existing_manual = _manual_entries_from_state(state)
    manual_by_pid = {entry["participant_id"]: dict(entry) for entry in existing_manual}
    for raw_pid, raw_reason in (manual_participant_reasons or {}).items():
        pid = _normalize_participant_id(raw_pid)
        if not pid:
            continue
        reason = str(raw_reason or WARNING_REASON_UNUSUAL_VALUES).strip()
        if reason not in MANUAL_EXCLUSION_REASONS:
            reason = WARNING_REASON_UNUSUAL_VALUES
        previous = manual_by_pid.get(pid, {})
        manual_by_pid[pid] = {
            "participant_id": pid,
            "reason": reason,
            "source": "manual_qc_review",
            "added_at": str(previous.get("added_at") or now),
            "updated_at": now,
        }
    manual_entries = sorted(manual_by_pid.values(), key=lambda item: item["participant_id"])
    existing_manual_recordings = _manual_recording_entries_from_state(state)
    manual_by_recording = {
        str(entry["recording_id"]).casefold(): dict(entry)
        for entry in existing_manual_recordings
    }
    for decision in resolved_recording_decisions:
        recording_id = str(decision.identity.recording_id)
        reason = str(decision.reason or WARNING_REASON_UNUSUAL_VALUES).strip()
        if reason not in MANUAL_EXCLUSION_REASONS:
            reason = WARNING_REASON_UNUSUAL_VALUES
        recording_key = recording_id.casefold()
        previous = manual_by_recording.get(recording_key, {})
        manual_by_recording[recording_key] = {
            "recording_id": recording_id,
            "participant_id": decision.identity.participant_id,
            "session_id": str(decision.identity.session_id or ""),
            "reason": reason,
            "source": "manual_qc_review",
            "added_at": str(previous.get("added_at") or now),
            "updated_at": now,
        }
    manual_recording_entries = sorted(
        manual_by_recording.values(),
        key=lambda item: str(item["recording_id"]).casefold(),
    )
    analysis_fingerprint = str(report.get("analysis_fingerprint") or "")
    decision_fingerprint = _decision_fingerprint(
        analysis_fingerprint=analysis_fingerprint,
        auto_electrodes=auto_electrodes,
        auto_participants=auto_participants,
        manual_participants=manual_entries,
        auto_recording_electrodes=(
            auto_recording_electrodes if repeated_session else None
        ),
        auto_recordings=(auto_recordings if repeated_session else None),
        manual_recordings=(manual_recording_entries if repeated_session else None),
    )
    report_path = _write_frequency_domain_qc_text_report(
        root,
        report=report,
        manual_participants=manual_entries,
        manual_recordings=manual_recording_entries,
        decision_fingerprint=decision_fingerprint,
        reviewed_at=now,
    )
    update: dict[str, object] = {
            "schema_version": FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
            "method_version": str(
                report.get("method_version") or FREQUENCY_DOMAIN_QC_METHOD_VERSION
            ),
            "thresholds": DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS.to_manifest(),
            "auto_participant_electrode_exclusions": auto_electrodes,
            "auto_participant_exclusions": auto_participants,
            "manual_participant_exclusions": manual_entries,
            "downstream_outputs_stale": True,
            "last_review": {
                "reviewed_at": now,
                "analysis_fingerprint": analysis_fingerprint,
                "decision_fingerprint": decision_fingerprint,
                "report_path": _manifest_safe_path(root, report_path),
                "review_subject_count": int(report.get("review_subject_count") or 0),
            },
        }
    if repeated_session:
        update.update(
            {
                "auto_recording_electrode_exclusions": auto_recording_electrodes,
                "auto_recording_exclusions": auto_recordings,
                "manual_recording_exclusions": manual_recording_entries,
            }
        )
        last_review = update.get("last_review")
        if isinstance(last_review, dict):
            last_review["review_recording_count"] = int(
                report.get("review_recording_count") or 0
            )
    state.update(update)
    _set_metadata_in_manifest(manifest, state)
    _write_manifest_if_changed(manifest_path, manifest)
    return state


def sync_frequency_domain_qc_automatic_state(
    project_root: str | Path,
    report: Mapping[str, object],
) -> dict[str, object]:
    """Refresh automatic QC exclusions from the current processed files."""

    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    repeated_session = str(report.get("identity_scope") or "") == "recording"
    previous_auto_electrodes = _auto_electrode_entries_from_state(state)
    previous_auto_participants = _auto_participant_entries_from_state(state)
    auto_electrodes = _normalize_auto_electrode_entries(
        report.get("auto_participant_electrode_exclusions")
    )
    auto_participants = _normalize_auto_participant_entries(
        report.get("auto_participant_exclusions")
    )
    previous_auto_recording_electrodes = (
        _auto_recording_electrode_entries_from_state(state)
    )
    previous_auto_recordings = _auto_recording_entries_from_state(state)
    auto_recording_electrodes = _normalize_auto_recording_electrode_entries(
        report.get("auto_recording_electrode_exclusions")
    )
    auto_recordings = _normalize_auto_recording_entries(
        report.get("auto_recording_exclusions")
    )
    if repeated_session:
        automatic_state_changed = (
            previous_auto_recording_electrodes != auto_recording_electrodes
            or previous_auto_recordings != auto_recordings
        )
    else:
        automatic_state_changed = (
            previous_auto_electrodes != auto_electrodes
            or previous_auto_participants != auto_participants
        )
    update: dict[str, object] = {
            "schema_version": FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
            "method_version": str(
                report.get("method_version") or FREQUENCY_DOMAIN_QC_METHOD_VERSION
            ),
            "thresholds": DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS.to_manifest(),
            "last_automatic_qc": {
                "reviewed_at": _now_utc_iso(),
                "analysis_fingerprint": str(report.get("analysis_fingerprint") or ""),
                "review_required": bool(report.get("review_required")),
                "review_reused": bool(report.get("review_reused")),
            },
        }
    if repeated_session:
        update.update(
            {
                "auto_recording_electrode_exclusions": auto_recording_electrodes,
                "auto_recording_exclusions": auto_recordings,
            }
        )
    else:
        update.update(
            {
                "auto_participant_electrode_exclusions": auto_electrodes,
                "auto_participant_exclusions": auto_participants,
            }
        )
    state.update(update)
    if automatic_state_changed:
        state["downstream_outputs_stale"] = True
        state["stale_reason"] = "Automatic frequency-domain QC exclusions changed."
        state["stale_at"] = _now_utc_iso()
        state.pop("last_review", None)
    _set_metadata_in_manifest(manifest, state)
    _write_manifest_if_changed(manifest_path, manifest)
    return state


def mark_frequency_domain_outputs_stale(
    project_root: str | Path,
    *,
    reason: str,
) -> None:
    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    state["downstream_outputs_stale"] = True
    state["stale_reason"] = str(reason)
    state["stale_at"] = _now_utc_iso()
    _set_metadata_in_manifest(manifest, state)
    _write_manifest_if_changed(manifest_path, manifest)


def mark_frequency_domain_outputs_current(project_root: str | Path) -> None:
    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    if not state:
        return
    state["downstream_outputs_stale"] = False
    state.pop("stale_reason", None)
    state["last_outputs_refreshed_at"] = _now_utc_iso()
    _set_metadata_in_manifest(manifest, state)
    _write_manifest_if_changed(manifest_path, manifest)


def is_frequency_domain_output_stale(project_root: str | Path | None) -> bool:
    if project_root in (None, ""):
        return False
    state = load_frequency_domain_qc_state(project_root)
    return bool(state.get("downstream_outputs_stale", False))


def load_frequency_domain_qc_state(project_root: str | Path | None) -> dict[str, object]:
    if project_root in (None, ""):
        return {}
    manifest = _read_manifest(Path(project_root).resolve() / "project.json")
    return _metadata_from_manifest(manifest)


def active_frequency_domain_exclusions(
    project_root: str | Path | None,
) -> FrequencyDomainExclusions:
    state = load_frequency_domain_qc_state(project_root)
    auto_participants = {
        _normalize_participant_id(entry.get("participant_id"))
        for entry in _iter_mapping_entries(state.get("auto_participant_exclusions"))
    }
    manual_participants = {
        _normalize_participant_id(entry.get("participant_id"))
        for entry in _iter_mapping_entries(state.get("manual_participant_exclusions"))
    }
    auto_participants = {pid for pid in auto_participants if pid}
    manual_participants = {pid for pid in manual_participants if pid}
    electrodes_by_pid: dict[str, set[str]] = defaultdict(set)
    for entry in _iter_mapping_entries(state.get("auto_participant_electrode_exclusions")):
        pid = _normalize_participant_id(entry.get("participant_id"))
        electrode = _normalize_electrode(entry.get("electrode"))
        if pid and electrode:
            electrodes_by_pid[pid].add(electrode)
    auto_recordings = {
        _normalize_recording_id(entry.get("recording_id"))
        for entry in _iter_mapping_entries(state.get("auto_recording_exclusions"))
    }
    manual_recordings = {
        _normalize_recording_id(entry.get("recording_id"))
        for entry in _iter_mapping_entries(state.get("manual_recording_exclusions"))
    }
    auto_recordings = {recording_id for recording_id in auto_recordings if recording_id}
    manual_recordings = {
        recording_id for recording_id in manual_recordings if recording_id
    }
    electrodes_by_recording: dict[str, set[str]] = defaultdict(set)
    for entry in _iter_mapping_entries(
        state.get("auto_recording_electrode_exclusions")
    ):
        recording_id = _normalize_recording_id(entry.get("recording_id"))
        electrode = _normalize_electrode(entry.get("electrode"))
        if recording_id and electrode:
            electrodes_by_recording[recording_id].add(electrode)
    return FrequencyDomainExclusions(
        excluded_participants=frozenset(auto_participants | manual_participants),
        auto_excluded_participants=frozenset(auto_participants),
        manual_excluded_participants=frozenset(manual_participants),
        auto_excluded_electrodes_by_participant={
            pid: frozenset(sorted(electrodes))
            for pid, electrodes in electrodes_by_pid.items()
        },
        downstream_outputs_stale=bool(state.get("downstream_outputs_stale", False)),
        excluded_recordings=frozenset(auto_recordings | manual_recordings),
        auto_excluded_recordings=frozenset(auto_recordings),
        manual_excluded_recordings=frozenset(manual_recordings),
        auto_excluded_electrodes_by_recording={
            recording_id: frozenset(sorted(electrodes))
            for recording_id, electrodes in electrodes_by_recording.items()
        },
    )


def filter_frequency_domain_subjects(
    project_root: str | Path | None,
    subjects: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
) -> tuple[list[str], dict[str, dict[str, str]], list[str]]:
    exclusions = active_frequency_domain_exclusions(project_root)
    excluded = {pid.upper() for pid in exclusions.excluded_participants}
    filtered_subjects = [str(pid) for pid in subjects if str(pid).upper() not in excluded]
    filtered_data = {
        pid: dict(subject_data.get(pid, {}))
        for pid in filtered_subjects
        if subject_data.get(pid)
    }
    removed = sorted(str(pid) for pid in subjects if str(pid).upper() in excluded)
    return filtered_subjects, filtered_data, removed


def filter_frequency_domain_recordings(
    project_root: str | Path | None,
    recording_ids: Sequence[str],
    recording_data: Mapping[str, Mapping[str, str]],
    *,
    recording_participant_ids: Mapping[str, str],
) -> tuple[list[str], dict[str, dict[str, str]], list[str]]:
    """Apply recording and participant exclusions without collapsing visits."""

    exclusions = active_frequency_domain_exclusions(project_root)
    excluded_recordings = {
        recording_id.casefold() for recording_id in exclusions.excluded_recordings
    }
    excluded_participants = {
        participant_id.casefold()
        for participant_id in exclusions.excluded_participants
    }
    participant_lookup = {
        str(recording_id).casefold(): str(participant_id)
        for recording_id, participant_id in recording_participant_ids.items()
    }
    filtered_recordings = [
        str(recording_id)
        for recording_id in recording_ids
        if str(recording_id).casefold() not in excluded_recordings
        and participant_lookup.get(str(recording_id).casefold(), "").casefold()
        not in excluded_participants
    ]
    filtered_data = {
        recording_id: dict(recording_data.get(recording_id, {}))
        for recording_id in filtered_recordings
        if recording_data.get(recording_id)
    }
    removed = sorted(
        str(recording_id)
        for recording_id in recording_ids
        if str(recording_id) not in filtered_recordings
    )
    return filtered_recordings, filtered_data, removed


def frequency_domain_excluded_electrodes_for_subject(
    project_root: str | Path | None,
    participant_id: object,
) -> frozenset[str]:
    exclusions = active_frequency_domain_exclusions(project_root)
    pid = _normalize_participant_id(participant_id)
    return exclusions.auto_excluded_electrodes_by_participant.get(pid, frozenset())


def frequency_domain_excluded_electrodes_for_recording(
    project_root: str | Path | None,
    recording_id: object,
) -> frozenset[str]:
    exclusions = active_frequency_domain_exclusions(project_root)
    normalized = _normalize_recording_id(recording_id)
    return exclusions.auto_excluded_electrodes_by_recording.get(
        normalized,
        frozenset(),
    )


def clear_manual_frequency_domain_participant_exclusions(
    project_root: str | Path,
    participant_ids: Iterable[object],
) -> list[str]:
    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    to_clear = {
        _normalize_participant_id(pid)
        for pid in participant_ids
        if _normalize_participant_id(pid)
    }
    if not to_clear:
        return []
    existing = _manual_entries_from_state(state)
    retained = [
        entry for entry in existing if entry.get("participant_id") not in to_clear
    ]
    cleared = sorted(
        entry["participant_id"]
        for entry in existing
        if entry.get("participant_id") in to_clear
    )
    if not cleared:
        return []
    state["manual_participant_exclusions"] = retained
    state["downstream_outputs_stale"] = True
    state["stale_reason"] = "Manual frequency-domain exclusions changed."
    state["stale_at"] = _now_utc_iso()
    state.pop("last_review", None)
    _set_metadata_in_manifest(manifest, state)
    _write_manifest_if_changed(manifest_path, manifest)
    return cleared


def clear_manual_frequency_domain_recording_exclusions(
    project_root: str | Path,
    recording_ids: Iterable[object],
) -> list[str]:
    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    to_clear = {
        _normalize_recording_id(recording_id)
        for recording_id in recording_ids
        if _normalize_recording_id(recording_id)
    }
    if not to_clear:
        return []
    existing = _manual_recording_entries_from_state(state)
    retained = [
        entry
        for entry in existing
        if str(entry.get("recording_id") or "").upper() not in to_clear
    ]
    cleared = sorted(
        str(entry["recording_id"])
        for entry in existing
        if str(entry.get("recording_id") or "").upper() in to_clear
    )
    if not cleared:
        return []
    state["manual_recording_exclusions"] = retained
    state["downstream_outputs_stale"] = True
    state["stale_reason"] = "Manual frequency-domain recording exclusions changed."
    state["stale_at"] = _now_utc_iso()
    state.pop("last_review", None)
    _set_metadata_in_manifest(manifest, state)
    _write_manifest_if_changed(manifest_path, manifest)
    return cleared


def thresholds_summary_lines() -> list[str]:
    thresholds = DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS
    return [
        f"Warning: abs(summed BCA) > {thresholds.warning_summed_bca_uv:g} uV",
        (
            "Repeated-warning review: "
            f"{thresholds.repeated_warning_cells} or more warning cells per participant"
        ),
        (
            "Strong warning: "
            f"abs(summed BCA) > {thresholds.strong_warning_summed_bca_uv:g} uV"
        ),
        (
            "Automatic electrode exclusion: "
            f"abs(summed BCA) > {thresholds.hard_electrode_summed_bca_uv:g} uV"
        ),
        (
            "Automatic participant exclusion: more than "
            f"{thresholds.hard_participant_unique_electrodes:g} unique hard-excluded electrodes"
        ),
    ]


def _provisional_harmonics(
    *,
    project_root: Path,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    rois: dict[str, list[str]],
    settings: Any,
    log_func: Callable[[str], None],
    recording_assignments: Mapping[str, Mapping[str, object]] | None = None,
    declared_session_ids: Sequence[str] | None = None,
    participant_group_ids: Mapping[str, str] | None = None,
    declared_group_ids: Sequence[str] | None = None,
) -> tuple[tuple[float, ...], dict[str, object]]:
    from Tools.Stats.analysis.dv_policy_fixed_predefined import (
        build_fixed_harmonic_selection,
    )
    from Tools.Stats.analysis.dv_policy_group_significant import (
        build_group_significant_harmonic_selection,
    )
    from Tools.Stats.analysis.dv_policy_settings import GROUP_SIGNIFICANT_POLICY_NAME

    if settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        selection = build_group_significant_harmonic_selection(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_frequency_hz=_analysis_base_frequency_hz(),
            rois=rois,
            log_func=log_func,
            settings=settings,
            max_freq=_analysis_bca_upper_limit_hz(),
            project_root=project_root,
            recording_assignments=recording_assignments,
            declared_session_ids=declared_session_ids,
            participant_group_ids=participant_group_ids,
            declared_group_ids=declared_group_ids,
        )
        return (
            tuple(round(float(freq), 4) for freq in selection.selected_harmonics_hz),
            selection.to_metadata(),
        )

    columns = _find_first_bca_columns(subjects, conditions, subject_data)
    if not columns:
        raise RuntimeError("Frequency-domain QC could not read BCA harmonic columns.")
    selection = build_fixed_harmonic_selection(
        requested_values=settings.fixed_harmonic_frequencies_hz,
        bca_columns=columns,
        base_frequency_hz=_analysis_base_frequency_hz(),
        auto_exclude_base_overlaps=settings.fixed_harmonic_auto_exclude_base,
        base_overlap_tolerance_hz=settings.fixed_harmonic_base_tolerance_hz,
        matching_tolerance_hz=settings.fixed_harmonic_matching_tolerance_hz,
        input_mode=settings.fixed_harmonic_input_mode,
        upper_harmonic_index=settings.fixed_harmonic_upper_harmonic_index,
        upper_frequency_hz=settings.fixed_harmonic_upper_frequency_hz,
    )
    return (
        tuple(round(float(freq), 4) for freq in selection.included_frequencies_hz),
        selection.to_metadata(),
    )


def _collect_summed_bca_flags(
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    selected_harmonics: Sequence[float],
    thresholds: FrequencyDomainQcThresholds,
    log_func: Callable[[str], None],
    recording_assignments: Mapping[str, Mapping[str, object]] | None = None,
) -> list[dict[str, object]]:
    from Main_App.io import (
        MissingXlsxColumnsError,
        read_xlsx_sheet_selected_columns,
    )

    columns = [f"{float(freq):.4f}_Hz" for freq in selected_harmonics]
    flags: list[dict[str, object]] = []
    for subject in subjects:
        for condition in conditions:
            file_path = subject_data.get(subject, {}).get(condition)
            if not file_path or not Path(file_path).exists():
                continue
            try:
                frame = read_xlsx_sheet_selected_columns(
                    file_path,
                    sheet_name="BCA (uV)",
                    required_columns=["Electrode", *columns],
                )
            except MissingXlsxColumnsError as exc:
                missing = [column for column in columns if column in exc.missing_columns]
                if missing:
                    raise RuntimeError(
                        "Frequency-domain QC requires exact selected BCA harmonic "
                        f"columns in every included workbook. Missing columns in {file_path}: "
                        f"{missing[:8]}"
                    ) from exc
                log_func(f"Frequency-domain QC could not read BCA sheet for {file_path}: {exc}")
                continue
            if "Electrode" not in frame.columns:
                log_func(f"Frequency-domain QC skipped {file_path}: missing Electrode column.")
                continue
            frame = frame.set_index("Electrode")
            frame.index = frame.index.astype(str).str.upper().str.strip()
            values = (
                frame[columns]
                .apply(pd.to_numeric, errors="coerce")
                .replace([np.inf, -np.inf], np.nan)
            )
            summed = values.sum(axis=1, min_count=1)
            for electrode, value in summed.items():
                if not np.isfinite(value):
                    continue
                abs_value = abs(float(value))
                if abs_value <= thresholds.warning_summed_bca_uv:
                    continue
                severity = "warning"
                if abs_value > thresholds.hard_electrode_summed_bca_uv:
                    severity = "hard"
                elif abs_value > thresholds.strong_warning_summed_bca_uv:
                    severity = "strong"
                flag: dict[str, object] = {
                        "participant_id": _normalize_participant_id(subject),
                        "condition": str(condition),
                        "electrode": _normalize_electrode(electrode),
                        "summed_bca_uv": float(value),
                        "abs_summed_bca_uv": float(abs_value),
                        "severity": severity,
                        "workbook_path": str(file_path),
                    }
                if recording_assignments is not None:
                    assignment = recording_assignments.get(subject, {})
                    flag.update(
                        {
                            "recording_id": _normalize_recording_id(subject),
                            "participant_id": _normalize_participant_id(
                                assignment.get("participant_id")
                            ),
                            "session_id": str(
                                assignment.get("session_id") or ""
                            ),
                            "visit_index": assignment.get("visit_index"),
                        }
                    )
                flags.append(flag)
    return sorted(
        flags,
        key=lambda item: (
            str(item.get("recording_id") or item.get("participant_id") or ""),
            -float(item.get("abs_summed_bca_uv") or 0.0),
            str(item.get("condition") or ""),
            str(item.get("electrode") or ""),
        ),
    )


def _summarize_flags(
    flags: Sequence[Mapping[str, object]],
    thresholds: FrequencyDomainQcThresholds,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    by_pid: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    hard_by_pid_electrode: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for flag in flags:
        pid = _normalize_participant_id(flag.get("participant_id"))
        electrode = _normalize_electrode(flag.get("electrode"))
        if not pid:
            continue
        by_pid[pid].append(flag)
        if str(flag.get("severity") or "") == "hard" and electrode:
            hard_by_pid_electrode[(pid, electrode)].append(flag)

    auto_electrodes: list[dict[str, object]] = []
    hard_electrodes_by_pid: dict[str, set[str]] = defaultdict(set)
    for (pid, electrode), entries in sorted(hard_by_pid_electrode.items()):
        hard_electrodes_by_pid[pid].add(electrode)
        max_entry = max(entries, key=lambda item: float(item.get("abs_summed_bca_uv") or 0.0))
        auto_electrodes.append(
            {
                "participant_id": pid,
                "electrode": electrode,
                "reason": "abs summed BCA exceeded hard electrode threshold",
                "threshold_uv": float(thresholds.hard_electrode_summed_bca_uv),
                "max_abs_summed_bca_uv": float(max_entry.get("abs_summed_bca_uv") or 0.0),
                "triggering_conditions": sorted(
                    {str(entry.get("condition") or "") for entry in entries if entry.get("condition")}
                ),
                "source": "automatic_frequency_domain_qc",
            }
        )

    auto_participants: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for pid, entries in sorted(by_pid.items()):
        warning_count = len(entries)
        strong_count = sum(1 for item in entries if str(item.get("severity") or "") in {"strong", "hard"})
        hard_electrode_count = len(hard_electrodes_by_pid.get(pid, set()))
        max_entry = max(entries, key=lambda item: float(item.get("abs_summed_bca_uv") or 0.0))
        auto_participant = hard_electrode_count > int(thresholds.hard_participant_unique_electrodes)
        if auto_participant:
            auto_participants.append(
                {
                    "participant_id": pid,
                    "reason": "more than 10 unique electrodes exceeded hard electrode threshold",
                    "hard_excluded_electrode_count": int(hard_electrode_count),
                    "source": "automatic_frequency_domain_qc",
                }
            )
        pause_reasons: list[str] = []
        if auto_participant:
            pause_reasons.append("automatic participant exclusion")
        if hard_electrode_count:
            pause_reasons.append("automatic electrode exclusion")
        if strong_count:
            pause_reasons.append("strong warning")
        if warning_count >= int(thresholds.repeated_warning_cells):
            pause_reasons.append("repeated warning pattern")
        summaries.append(
            {
                "participant_id": pid,
                "max_abs_summed_bca_uv": float(max_entry.get("abs_summed_bca_uv") or 0.0),
                "max_condition": str(max_entry.get("condition") or ""),
                "max_electrode": str(max_entry.get("electrode") or ""),
                "warning_cell_count": int(warning_count),
                "strong_or_hard_cell_count": int(strong_count),
                "hard_excluded_electrode_count": int(hard_electrode_count),
                "auto_participant_excluded": bool(auto_participant),
                "pause_review": bool(pause_reasons),
                "pause_reasons": pause_reasons,
            }
        )
    return summaries, auto_electrodes, auto_participants


def _summarize_recording_flags(
    flags: Sequence[Mapping[str, object]],
    thresholds: FrequencyDomainQcThresholds,
) -> tuple[list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Summarize repeated-session QC without promoting a visit to a person."""

    by_recording: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    hard_by_recording_electrode: dict[
        tuple[str, str], list[Mapping[str, object]]
    ] = defaultdict(list)
    for flag in flags:
        recording_id = _normalize_recording_id(flag.get("recording_id"))
        electrode = _normalize_electrode(flag.get("electrode"))
        if not recording_id:
            continue
        by_recording[recording_id].append(flag)
        if str(flag.get("severity") or "") == "hard" and electrode:
            hard_by_recording_electrode[(recording_id, electrode)].append(flag)

    auto_electrodes: list[dict[str, object]] = []
    hard_electrodes_by_recording: dict[str, set[str]] = defaultdict(set)
    for (recording_id, electrode), entries in sorted(
        hard_by_recording_electrode.items()
    ):
        hard_electrodes_by_recording[recording_id].add(electrode)
        max_entry = max(
            entries,
            key=lambda item: float(item.get("abs_summed_bca_uv") or 0.0),
        )
        auto_electrodes.append(
            {
                "recording_id": recording_id,
                "participant_id": _normalize_participant_id(
                    max_entry.get("participant_id")
                ),
                "session_id": str(max_entry.get("session_id") or ""),
                "visit_index": max_entry.get("visit_index"),
                "electrode": electrode,
                "reason": "abs summed BCA exceeded hard electrode threshold",
                "threshold_uv": float(thresholds.hard_electrode_summed_bca_uv),
                "max_abs_summed_bca_uv": float(
                    max_entry.get("abs_summed_bca_uv") or 0.0
                ),
                "triggering_conditions": sorted(
                    {
                        str(entry.get("condition") or "")
                        for entry in entries
                        if entry.get("condition")
                    }
                ),
                "source": "automatic_frequency_domain_qc",
            }
        )

    auto_recordings: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    for recording_id, entries in sorted(by_recording.items()):
        warning_count = len(entries)
        strong_count = sum(
            1
            for item in entries
            if str(item.get("severity") or "") in {"strong", "hard"}
        )
        hard_electrode_count = len(
            hard_electrodes_by_recording.get(recording_id, set())
        )
        max_entry = max(
            entries,
            key=lambda item: float(item.get("abs_summed_bca_uv") or 0.0),
        )
        auto_recording = hard_electrode_count > int(
            thresholds.hard_participant_unique_electrodes
        )
        identity = {
            "recording_id": recording_id,
            "participant_id": _normalize_participant_id(
                max_entry.get("participant_id")
            ),
            "session_id": str(max_entry.get("session_id") or ""),
            "visit_index": max_entry.get("visit_index"),
        }
        if auto_recording:
            auto_recordings.append(
                {
                    **identity,
                    "reason": (
                        "more than 10 unique electrodes exceeded hard electrode "
                        "threshold in this recording"
                    ),
                    "hard_excluded_electrode_count": int(hard_electrode_count),
                    "source": "automatic_frequency_domain_qc",
                }
            )
        pause_reasons: list[str] = []
        if auto_recording:
            pause_reasons.append("automatic recording exclusion")
        if hard_electrode_count:
            pause_reasons.append("automatic recording-electrode exclusion")
        if strong_count:
            pause_reasons.append("strong warning")
        if warning_count >= int(thresholds.repeated_warning_cells):
            pause_reasons.append("repeated warning pattern")
        summaries.append(
            {
                **identity,
                "max_abs_summed_bca_uv": float(
                    max_entry.get("abs_summed_bca_uv") or 0.0
                ),
                "max_condition": str(max_entry.get("condition") or ""),
                "max_electrode": str(max_entry.get("electrode") or ""),
                "warning_cell_count": int(warning_count),
                "strong_or_hard_cell_count": int(strong_count),
                "hard_excluded_electrode_count": int(hard_electrode_count),
                "auto_recording_excluded": bool(auto_recording),
                "pause_review": bool(pause_reasons),
                "pause_reasons": pause_reasons,
            }
        )
    return summaries, auto_electrodes, auto_recordings


def _analysis_fingerprint(
    *,
    project_root: Path,
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
    selected_harmonics: Sequence[float],
    thresholds: FrequencyDomainQcThresholds,
    flags: Sequence[Mapping[str, object]],
    recording_assignments: Mapping[str, Mapping[str, object]] | None = None,
) -> str:
    workbooks = []
    for subject in subjects:
        for condition in conditions:
            file_path = subject_data.get(subject, {}).get(condition)
            if not file_path:
                continue
            path = Path(file_path)
            try:
                stat = path.stat()
                size = int(stat.st_size)
                mtime = int(stat.st_mtime_ns)
            except OSError:
                size = None
                mtime = None
            workbook: dict[str, object] = {
                    "subject": str(subject),
                    "condition": str(condition),
                    "path": _manifest_safe_path(project_root, path),
                    "size_bytes": size,
                    "mtime_ns": mtime,
                }
            if recording_assignments is not None:
                assignment = recording_assignments.get(str(subject), {})
                workbook.update(
                    {
                        "recording_id": str(subject),
                        "participant_id": str(
                            assignment.get("participant_id") or ""
                        ),
                        "group_id": str(assignment.get("group_id") or ""),
                        "session_id": str(assignment.get("session_id") or ""),
                        "source_id": str(assignment.get("source_id") or ""),
                        "visit_index": assignment.get("visit_index"),
                        "days_from_baseline": assignment.get(
                            "days_from_baseline"
                        ),
                    }
                )
            workbooks.append(workbook)
    payload = {
        "method_version": (
            REPEATED_FREQUENCY_DOMAIN_QC_METHOD_VERSION
            if recording_assignments is not None
            else FREQUENCY_DOMAIN_QC_METHOD_VERSION
        ),
        "thresholds": thresholds.to_manifest(),
        "subjects": list(map(str, subjects)),
        "conditions": list(map(str, conditions)),
        "selected_harmonics_hz": [round(float(freq), 4) for freq in selected_harmonics],
        "workbooks": workbooks,
        "flags": [
            {
                "participant_id": _normalize_participant_id(flag.get("participant_id")),
                "condition": str(flag.get("condition") or ""),
                "electrode": _normalize_electrode(flag.get("electrode")),
                "abs_summed_bca_uv": round(float(flag.get("abs_summed_bca_uv") or 0.0), 6),
                "severity": str(flag.get("severity") or ""),
            }
            for flag in flags
        ],
    }
    if recording_assignments is not None:
        payload.update(
            {
                "identity_scope": "recording",
                "recording_assignments": [
                    {
                        "recording_id": str(recording_id),
                        **{
                            key: row.get(key)
                            for key in (
                                "participant_id",
                                "group_id",
                                "session_id",
                                "source_id",
                                "visit_index",
                                "days_from_baseline",
                            )
                        },
                    }
                    for recording_id, row in sorted(
                        recording_assignments.items(),
                        key=lambda item: str(item[0]).casefold(),
                    )
                    if recording_id in subjects
                ],
                "flags": [
                    {
                        "recording_id": _normalize_recording_id(
                            flag.get("recording_id")
                        ),
                        "participant_id": _normalize_participant_id(
                            flag.get("participant_id")
                        ),
                        "session_id": str(flag.get("session_id") or ""),
                        "condition": str(flag.get("condition") or ""),
                        "electrode": _normalize_electrode(flag.get("electrode")),
                        "abs_summed_bca_uv": round(
                            float(flag.get("abs_summed_bca_uv") or 0.0),
                            6,
                        ),
                        "severity": str(flag.get("severity") or ""),
                    }
                    for flag in flags
                ],
            }
        )
    return _hash_payload(payload)


def _decision_fingerprint(
    *,
    analysis_fingerprint: str,
    auto_electrodes: Sequence[Mapping[str, object]],
    auto_participants: Sequence[Mapping[str, object]],
    manual_participants: Sequence[Mapping[str, object]],
    auto_recording_electrodes: Sequence[Mapping[str, object]] | None = None,
    auto_recordings: Sequence[Mapping[str, object]] | None = None,
    manual_recordings: Sequence[Mapping[str, object]] | None = None,
) -> str:
    payload = {
        "analysis_fingerprint": str(analysis_fingerprint),
        "auto_electrodes": _json_safe(_normalize_auto_electrode_entries(auto_electrodes)),
        "auto_participants": _json_safe(_normalize_auto_participant_entries(auto_participants)),
        "manual_participants": _json_safe(_normalize_manual_entries(manual_participants)),
    }
    if (
        auto_recording_electrodes is not None
        or auto_recordings is not None
        or manual_recordings is not None
    ):
        payload.update(
            {
                "auto_recording_electrodes": _json_safe(
                    _normalize_auto_recording_electrode_entries(
                        auto_recording_electrodes
                    )
                ),
                "auto_recordings": _json_safe(
                    _normalize_auto_recording_entries(auto_recordings)
                ),
                "manual_recordings": _json_safe(
                    _normalize_manual_recording_entries(manual_recordings)
                ),
            }
        )
    return _hash_payload(payload)


def _write_frequency_domain_qc_text_report(
    project_root: Path,
    *,
    report: Mapping[str, object],
    manual_participants: Sequence[Mapping[str, object]],
    manual_recordings: Sequence[Mapping[str, object]],
    decision_fingerprint: str,
    reviewed_at: str,
) -> Path:
    qc_folder = project_root / QUALITY_CHECK_FOLDER
    qc_folder.mkdir(parents=True, exist_ok=True)
    path = qc_folder / FREQUENCY_DOMAIN_QC_REPORT_NAME
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), Mapping) else {}
    lines = [
        "Frequency-Domain QC Review",
        "",
        f"Reviewed at: {reviewed_at}",
        f"Decision fingerprint: {decision_fingerprint}",
        f"Project: {project_root}",
        "",
        "Thresholds",
        f"- Warning: abs(summed BCA) > {thresholds.get('warning_summed_bca_uv', 10)} uV",
        (
            "- Repeated warning review: "
            f"{thresholds.get('repeated_warning_cells', 5)} warning cells per participant"
        ),
        f"- Strong warning: abs(summed BCA) > {thresholds.get('strong_warning_summed_bca_uv', 50)} uV",
        (
            "- Automatic electrode exclusion: abs(summed BCA) > "
            f"{thresholds.get('hard_electrode_summed_bca_uv', 250)} uV"
        ),
        (
            "- Automatic participant exclusion: more than "
            f"{thresholds.get('hard_participant_unique_electrodes', 10)} unique hard-excluded electrodes"
        ),
        "",
        "Selected provisional harmonics",
        "- "
        + (
            ", ".join(f"{float(freq):g} Hz" for freq in report.get("selected_harmonics_hz", []) or [])
            or "None"
        ),
        "",
        "Automatic participant-electrode exclusions",
    ]
    auto_electrodes = _normalize_auto_electrode_entries(
        report.get("auto_participant_electrode_exclusions")
    )
    if auto_electrodes:
        for entry in auto_electrodes:
            conditions = ", ".join(entry.get("triggering_conditions", []) or [])
            lines.append(
                "- {participant_id} {electrode}: max abs summed BCA {value:.3f} uV"
                "{conditions}".format(
                    participant_id=entry["participant_id"],
                    electrode=entry["electrode"],
                    value=float(entry.get("max_abs_summed_bca_uv") or 0.0),
                    conditions=f" ({conditions})" if conditions else "",
                )
            )
    else:
        lines.append("- None")

    lines.extend(["", "Automatic participant exclusions"])
    auto_participants = _normalize_auto_participant_entries(
        report.get("auto_participant_exclusions")
    )
    if auto_participants:
        for entry in auto_participants:
            lines.append(
                "- {participant_id}: {count} hard-excluded electrodes".format(
                    participant_id=entry["participant_id"],
                    count=int(entry.get("hard_excluded_electrode_count") or 0),
                )
            )
    else:
        lines.append("- None")

    lines.extend(["", "Manual participant exclusions"])
    manual_entries = _normalize_manual_entries(manual_participants)
    if manual_entries:
        for entry in manual_entries:
            lines.append(f"- {entry['participant_id']}: {entry['reason']}")
    else:
        lines.append("- None")

    lines.extend(["", "Reviewed participant summary"])
    summaries = [
        item
        for item in _iter_mapping_entries(report.get("participant_summaries"))
        if item.get("pause_review")
    ]
    if summaries:
        for item in summaries:
            reasons = ", ".join(str(reason) for reason in item.get("pause_reasons", []) or [])
            lines.append(
                "- {pid}: max {value:.3f} uV at {condition}/{electrode}; "
                "{warnings} warning cells; {hard} hard electrodes; {reasons}".format(
                    pid=item.get("participant_id"),
                    value=float(item.get("max_abs_summed_bca_uv") or 0.0),
                    condition=item.get("max_condition") or "",
                    electrode=item.get("max_electrode") or "",
                    warnings=int(item.get("warning_cell_count") or 0),
                    hard=int(item.get("hard_excluded_electrode_count") or 0),
                    reasons=reasons,
                )
            )
    else:
        lines.append("- No participant required review.")
    if str(report.get("identity_scope") or "") == "recording":
        lines.extend(["", "Automatic recording-electrode exclusions"])
        recording_electrodes = _normalize_auto_recording_electrode_entries(
            report.get("auto_recording_electrode_exclusions")
        )
        if recording_electrodes:
            for entry in recording_electrodes:
                lines.append(
                    "- {recording_id} ({participant_id}, {session_id}) {electrode}: "
                    "max abs summed BCA {value:.3f} uV".format(
                        recording_id=entry["recording_id"],
                        participant_id=entry.get("participant_id") or "",
                        session_id=entry.get("session_id") or "",
                        electrode=entry["electrode"],
                        value=float(
                            entry.get("max_abs_summed_bca_uv") or 0.0
                        ),
                    )
                )
        else:
            lines.append("- None")
        lines.extend(["", "Automatic recording exclusions"])
        recording_exclusions = _normalize_auto_recording_entries(
            report.get("auto_recording_exclusions")
        )
        if recording_exclusions:
            for entry in recording_exclusions:
                lines.append(
                    "- {recording_id}: {count} hard-excluded electrodes".format(
                        recording_id=entry["recording_id"],
                        count=int(
                            entry.get("hard_excluded_electrode_count") or 0
                        ),
                    )
                )
        else:
            lines.append("- None")
        lines.extend(["", "Manual recording exclusions"])
        normalized_manual_recordings = _normalize_manual_recording_entries(
            manual_recordings
        )
        if normalized_manual_recordings:
            for entry in normalized_manual_recordings:
                lines.append(f"- {entry['recording_id']}: {entry['reason']}")
        else:
            lines.append("- None")
        lines.extend(["", "Reviewed recording summary"])
        recording_summaries = [
            item
            for item in _iter_mapping_entries(report.get("recording_summaries"))
            if item.get("pause_review")
        ]
        if recording_summaries:
            for item in recording_summaries:
                reasons = ", ".join(
                    str(reason) for reason in item.get("pause_reasons", []) or []
                )
                lines.append(
                    "- {recording_id} ({participant_id}, {session_id}): max "
                    "{value:.3f} uV at {condition}/{electrode}; {reasons}".format(
                        recording_id=item.get("recording_id") or "",
                        participant_id=item.get("participant_id") or "",
                        session_id=item.get("session_id") or "",
                        value=float(item.get("max_abs_summed_bca_uv") or 0.0),
                        condition=item.get("max_condition") or "",
                        electrode=item.get("max_electrode") or "",
                        reasons=reasons,
                    )
                )
        else:
            lines.append("- No recording required review.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _find_first_bca_columns(
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
) -> list[object]:
    from Main_App.io import read_xlsx_sheet_header

    for subject in subjects:
        for condition in conditions:
            file_path = subject_data.get(subject, {}).get(condition)
            if not file_path:
                continue
            try:
                return [
                    column
                    for column in read_xlsx_sheet_header(file_path, sheet_name="BCA (uV)")
                    if column != "Electrode"
                ]
            except Exception:
                logger.debug("frequency_domain_qc_bca_header_read_failed", exc_info=True)
    return []


def _harmonic_selection_settings(project: Any) -> Any:
    from Tools.Stats.analysis.dv_policy_settings import (
        GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        GROUP_SIGNIFICANT_POLICY_NAME,
        GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
        normalize_dv_policy,
    )

    raw_preprocessing: Mapping[str, object] = (
        getattr(project, "preprocessing", {}) or {}
    )
    project_root = getattr(project, "project_root", None)
    if project_root not in (None, ""):
        manifest_path = Path(project_root).resolve(strict=False) / "project.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, Mapping) and isinstance(
            manifest.get("preprocessing"), Mapping
        ):
            raw_preprocessing = manifest["preprocessing"]
    try:
        preprocessing = normalize_preprocessing_settings(raw_preprocessing)
    except ValueError:
        preprocessing = normalize_preprocessing_settings({})
    policy: dict[str, object] = {
        "name": preprocessing.get(
            "harmonic_selection_policy",
            GROUP_SIGNIFICANT_POLICY_NAME,
        ),
        "harmonic_selection_profile": raw_preprocessing.get(
            "harmonic_selection_profile"
        ),
        "harmonic_selection_profile_version": raw_preprocessing.get(
            "harmonic_selection_profile_version"
        ),
        "fixed_harmonic_frequencies_hz": preprocessing.get(
            "fixed_harmonic_frequencies_hz",
            "",
        ),
        "fixed_harmonic_input_mode": raw_preprocessing.get(
            "fixed_harmonic_input_mode"
        ),
        "fixed_harmonic_upper_harmonic_index": raw_preprocessing.get(
            "fixed_harmonic_upper_harmonic_index"
        ),
        "fixed_harmonic_upper_frequency_hz": raw_preprocessing.get(
            "fixed_harmonic_upper_frequency_hz"
        ),
        "fixed_harmonic_auto_exclude_base": preprocessing.get(
            "fixed_harmonic_auto_exclude_base",
            True,
        ),
        "group_significant_selection_electrodes": raw_preprocessing.get(
            "group_significant_selection_electrodes"
        ),
        "group_significant_summation_method": preprocessing.get(
            "group_significant_summation_method",
            GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
        ),
    }
    if "group_significant_electrode_scope" in raw_preprocessing:
        policy["group_significant_electrode_scope"] = raw_preprocessing[
            "group_significant_electrode_scope"
        ]
    elif raw_preprocessing.get("harmonic_selection_profile") in (None, ""):
        policy["group_significant_electrode_scope"] = preprocessing.get(
            "group_significant_electrode_scope",
            GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        )
    return normalize_dv_policy(policy)


def _filter_preprocessing_manual_exclusions(project: Any, subjects: list[str]) -> list[str]:
    preprocessing = getattr(project, "preprocessing", {}) or {}
    excluded = set(
        normalize_manual_excluded_participants(
            preprocessing.get("manual_excluded_participants", [])
        )
    )
    return [subject for subject in subjects if str(subject).upper() not in excluded]


def _filter_preprocessing_manual_recording_exclusions(
    project: Any,
    recording_ids: list[str],
    *,
    recording_assignments: Mapping[str, Mapping[str, object]],
) -> list[str]:
    preprocessing = getattr(project, "preprocessing", {}) or {}
    excluded_participants = {
        str(value).casefold()
        for value in normalize_manual_excluded_participants(
            preprocessing.get("manual_excluded_participants", [])
        )
    }
    excluded_recordings = {
        str(value).casefold()
        for value in normalize_manual_excluded_recordings(
            preprocessing.get("manual_excluded_recordings", [])
        )
    }
    return [
        recording_id
        for recording_id in recording_ids
        if recording_id.casefold() not in excluded_recordings
        and str(
            recording_assignments.get(recording_id, {}).get("participant_id") or ""
        ).casefold()
        not in excluded_participants
    ]


def _recording_assignments_from_index(
    dataset_index: ProjectDatasetIndex,
) -> dict[str, dict[str, object]]:
    assignments: dict[str, dict[str, object]] = {}
    group_by_participant = dataset_index.participant_group_id_map()
    for recording_id in dataset_index.recording_ids:
        recording = dataset_index.recordings.get(recording_id)
        if recording is None:
            raise RuntimeError(
                "Repeated-session frequency-domain QC is missing the canonical "
                f"recording assignment for {recording_id}."
            )
        session = dataset_index.sessions.get(recording.session_id)
        assignments[recording_id] = {
            "recording_id": recording_id,
            "participant_id": recording.participant_id,
            "group_id": group_by_participant.get(recording.participant_id, ""),
            "session_id": recording.session_id,
            "session_label": session.label if session is not None else recording.session_id,
            "source_id": recording.source_id,
            "visit_index": recording.visit_index,
            "days_from_baseline": recording.days_from_baseline,
        }
    return assignments


def _filter_to_completed_subjects(
    *,
    project_root: Path,
    subjects: list[str],
    subject_data: dict[str, dict[str, str]],
) -> tuple[list[str], dict[str, dict[str, str]]]:
    from Main_App.processing.processing_ledger import load_ledger

    try:
        ledger = load_ledger(project_root)
    except Exception:
        return subjects, subject_data
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if not isinstance(entries, Mapping):
        return subjects, subject_data
    completed = {
        str(pid).upper()
        for pid, entry in entries.items()
        if isinstance(entry, Mapping) and str(entry.get("status") or "") == "completed"
    }
    if not completed:
        return subjects, subject_data
    filtered_subjects = [subject for subject in subjects if subject.upper() in completed]
    return filtered_subjects, {
        subject: dict(subject_data.get(subject, {})) for subject in filtered_subjects
    }


def _ordered_conditions(project: Any, scanned_conditions: list[str]) -> list[str]:
    scanned = [str(condition) for condition in scanned_conditions]
    seen: set[str] = set()
    ordered: list[str] = []
    event_map = getattr(project, "event_map", {}) or {}
    if isinstance(event_map, Mapping):
        for condition in event_map.keys():
            text = str(condition)
            if text in scanned and text not in seen:
                ordered.append(text)
                seen.add(text)
    for condition in scanned:
        if condition not in seen:
            ordered.append(condition)
            seen.add(condition)
    return ordered


def _filter_subject_data(
    subject_data: dict[str, dict[str, str]],
    conditions: list[str],
) -> dict[str, dict[str, str]]:
    condition_set = set(conditions)
    return {
        subject: {
            condition: path
            for condition, path in (condition_map or {}).items()
            if condition in condition_set and Path(path).exists()
        }
        for subject, condition_map in subject_data.items()
    }


def _analysis_base_frequency_hz() -> float:
    from Main_App import SettingsManager

    try:
        return float(SettingsManager().get("analysis", "base_freq", "6.0"))
    except (TypeError, ValueError):
        return 6.0


def _analysis_bca_upper_limit_hz() -> float | None:
    from Main_App import SettingsManager

    try:
        value = float(SettingsManager().get("analysis", "bca_upper_limit", "16.8"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _metadata_from_manifest(manifest: Mapping[str, object] | None) -> dict[str, object]:
    current: Mapping[str, object] = manifest if isinstance(manifest, Mapping) else {}
    for key in FREQUENCY_DOMAIN_QC_METADATA_PATH:
        value = current.get(key)
        if not isinstance(value, Mapping):
            return {}
        current = value
    return dict(current)


def _set_metadata_in_manifest(manifest: dict[str, object], state: Mapping[str, object]) -> None:
    current: dict[str, object] = manifest
    for key in FREQUENCY_DOMAIN_QC_METADATA_PATH[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[FREQUENCY_DOMAIN_QC_METADATA_PATH[-1]] = _json_safe(dict(state))


def _read_manifest(manifest_path: Path) -> dict[str, object]:
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_manifest_if_changed(manifest_path: Path, manifest: Mapping[str, object]) -> None:
    new_payload = json.dumps(_json_safe(dict(manifest)), sort_keys=True, separators=(",", ":"))
    if manifest_path.exists():
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = {}
        current_payload = json.dumps(current, sort_keys=True, separators=(",", ":"))
        if current_payload == new_payload:
            return
    manifest_path.write_text(
        json.dumps(_json_safe(dict(manifest)), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _auto_electrode_entries_from_state(state: Mapping[str, object]) -> list[dict[str, object]]:
    return _normalize_auto_electrode_entries(state.get("auto_participant_electrode_exclusions"))


def _auto_participant_entries_from_state(state: Mapping[str, object]) -> list[dict[str, object]]:
    return _normalize_auto_participant_entries(state.get("auto_participant_exclusions"))


def _manual_entries_from_state(state: Mapping[str, object]) -> list[dict[str, object]]:
    return _normalize_manual_entries(state.get("manual_participant_exclusions"))


def _auto_recording_electrode_entries_from_state(
    state: Mapping[str, object],
) -> list[dict[str, object]]:
    return _normalize_auto_recording_electrode_entries(
        state.get("auto_recording_electrode_exclusions")
    )


def _auto_recording_entries_from_state(
    state: Mapping[str, object],
) -> list[dict[str, object]]:
    return _normalize_auto_recording_entries(state.get("auto_recording_exclusions"))


def _manual_recording_entries_from_state(
    state: Mapping[str, object],
) -> list[dict[str, object]]:
    return _normalize_manual_recording_entries(state.get("manual_recording_exclusions"))


def _normalize_auto_electrode_entries(value: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in _iter_mapping_entries(value):
        pid = _normalize_participant_id(item.get("participant_id"))
        electrode = _normalize_electrode(item.get("electrode"))
        if not pid or not electrode:
            continue
        conditions = sorted({str(condition) for condition in item.get("triggering_conditions", []) or []})
        entries.append(
            {
                "participant_id": pid,
                "electrode": electrode,
                "reason": str(item.get("reason") or "abs summed BCA exceeded hard electrode threshold"),
                "threshold_uv": float(item.get("threshold_uv") or DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS.hard_electrode_summed_bca_uv),
                "max_abs_summed_bca_uv": float(item.get("max_abs_summed_bca_uv") or 0.0),
                "triggering_conditions": conditions,
                "source": str(item.get("source") or "automatic_frequency_domain_qc"),
            }
        )
    return sorted(entries, key=lambda entry: (entry["participant_id"], entry["electrode"]))


def _normalize_auto_participant_entries(value: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in _iter_mapping_entries(value):
        pid = _normalize_participant_id(item.get("participant_id"))
        if not pid:
            continue
        entries.append(
            {
                "participant_id": pid,
                "reason": str(item.get("reason") or "more than 10 unique electrodes exceeded hard electrode threshold"),
                "hard_excluded_electrode_count": int(item.get("hard_excluded_electrode_count") or 0),
                "source": str(item.get("source") or "automatic_frequency_domain_qc"),
            }
        )
    return sorted(entries, key=lambda entry: entry["participant_id"])


def _normalize_manual_entries(value: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in _iter_mapping_entries(value):
        pid = _normalize_participant_id(item.get("participant_id"))
        if not pid:
            continue
        reason = str(item.get("reason") or WARNING_REASON_UNUSUAL_VALUES)
        if reason not in MANUAL_EXCLUSION_REASONS:
            reason = WARNING_REASON_UNUSUAL_VALUES
        entry = {
            "participant_id": pid,
            "reason": reason,
            "source": str(item.get("source") or "manual_qc_review"),
        }
        if item.get("added_at"):
            entry["added_at"] = str(item.get("added_at"))
        if item.get("updated_at"):
            entry["updated_at"] = str(item.get("updated_at"))
        entries.append(entry)
    return sorted(entries, key=lambda entry: entry["participant_id"])


def _normalize_auto_recording_electrode_entries(
    value: object,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in _iter_mapping_entries(value):
        recording_id = _normalize_recording_id(item.get("recording_id"))
        electrode = _normalize_electrode(item.get("electrode"))
        if not recording_id or not electrode:
            continue
        conditions = sorted(
            {
                str(condition)
                for condition in item.get("triggering_conditions", []) or []
            }
        )
        entries.append(
            {
                "recording_id": recording_id,
                "participant_id": _normalize_participant_id(
                    item.get("participant_id")
                ),
                "session_id": str(item.get("session_id") or ""),
                "visit_index": _optional_int(item.get("visit_index")),
                "electrode": electrode,
                "reason": str(
                    item.get("reason")
                    or "abs summed BCA exceeded hard electrode threshold"
                ),
                "threshold_uv": float(
                    item.get("threshold_uv")
                    or DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS.hard_electrode_summed_bca_uv
                ),
                "max_abs_summed_bca_uv": float(
                    item.get("max_abs_summed_bca_uv") or 0.0
                ),
                "triggering_conditions": conditions,
                "source": str(
                    item.get("source") or "automatic_frequency_domain_qc"
                ),
            }
        )
    return sorted(
        entries,
        key=lambda entry: (str(entry["recording_id"]), str(entry["electrode"])),
    )


def _normalize_auto_recording_entries(value: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in _iter_mapping_entries(value):
        recording_id = _normalize_recording_id(item.get("recording_id"))
        if not recording_id:
            continue
        entries.append(
            {
                "recording_id": recording_id,
                "participant_id": _normalize_participant_id(
                    item.get("participant_id")
                ),
                "session_id": str(item.get("session_id") or ""),
                "visit_index": _optional_int(item.get("visit_index")),
                "reason": str(
                    item.get("reason")
                    or (
                        "more than 10 unique electrodes exceeded hard electrode "
                        "threshold in this recording"
                    )
                ),
                "hard_excluded_electrode_count": int(
                    item.get("hard_excluded_electrode_count") or 0
                ),
                "source": str(
                    item.get("source") or "automatic_frequency_domain_qc"
                ),
            }
        )
    return sorted(entries, key=lambda entry: str(entry["recording_id"]))


def _normalize_manual_recording_entries(value: object) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in _iter_mapping_entries(value):
        recording_id = str(item.get("recording_id") or "").strip()
        if not recording_id:
            continue
        reason = str(item.get("reason") or WARNING_REASON_UNUSUAL_VALUES)
        if reason not in MANUAL_EXCLUSION_REASONS:
            reason = WARNING_REASON_UNUSUAL_VALUES
        entry: dict[str, object] = {
            "recording_id": recording_id,
            "participant_id": str(item.get("participant_id") or "").strip(),
            "session_id": str(item.get("session_id") or ""),
            "reason": reason,
            "source": str(item.get("source") or "manual_qc_review"),
        }
        if item.get("added_at"):
            entry["added_at"] = str(item.get("added_at"))
        if item.get("updated_at"):
            entry["updated_at"] = str(item.get("updated_at"))
        entries.append(entry)
    return sorted(entries, key=lambda entry: str(entry["recording_id"]).casefold())


def _iter_mapping_entries(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _normalize_participant_id(value: object) -> str:
    text = str(value or "").strip().upper()
    return text


def _normalize_recording_id(value: object) -> str:
    return str(value or "").strip().upper()


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _normalize_electrode(value: object) -> str:
    return str(value or "").strip().upper()


def _hash_payload(payload: Mapping[str, object]) -> str:
    normalized = json.dumps(_json_safe(dict(payload)), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float):
        if not np.isfinite(value):
            return None
        return float(value)
    return value


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _manifest_safe_path(project_root: Path, path: Path) -> str:
    try:
        root = project_root.resolve()
        resolved = Path(path).resolve(strict=False)
        if resolved == root or root in resolved.parents:
            return str(resolved.relative_to(root))
        return str(resolved)
    except OSError:
        return str(path)


__all__ = [
    "DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS",
    "FREQUENCY_DOMAIN_QC_REPORT_NAME",
    "MANUAL_EXCLUSION_REASONS",
    "FrequencyDomainExclusions",
    "FrequencyDomainQcThresholds",
    "REPEATED_FREQUENCY_DOMAIN_QC_METHOD_VERSION",
    "active_frequency_domain_exclusions",
    "apply_frequency_domain_qc_decision",
    "clear_manual_frequency_domain_participant_exclusions",
    "clear_manual_frequency_domain_recording_exclusions",
    "filter_frequency_domain_recordings",
    "filter_frequency_domain_subjects",
    "frequency_domain_excluded_electrodes_for_subject",
    "frequency_domain_excluded_electrodes_for_recording",
    "is_frequency_domain_output_stale",
    "load_frequency_domain_qc_state",
    "mark_frequency_domain_outputs_current",
    "mark_frequency_domain_outputs_stale",
    "run_frequency_domain_qc_review",
    "sync_frequency_domain_qc_automatic_state",
    "thresholds_summary_lines",
]

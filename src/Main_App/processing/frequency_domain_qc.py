"""Project-wide frequency-domain QC and exclusion metadata helpers."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from Main_App.projects import load_project_dataset_index
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participants,
    normalize_preprocessing_settings,
)

logger = logging.getLogger(__name__)

QUALITY_CHECK_FOLDER = "Quality Check"
FREQUENCY_DOMAIN_QC_REPORT_NAME = "Frequency_Domain_QC_Review.txt"
FREQUENCY_DOMAIN_QC_METADATA_PATH = ("tools", "frequency_domain_qc")
FREQUENCY_DOMAIN_QC_SCHEMA_VERSION = 1
FREQUENCY_DOMAIN_QC_METHOD_VERSION = "summed_bca_plausibility_v1"

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


def run_frequency_domain_qc_review(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Build a provisional summed-BCA QC report for the active project."""

    def _log(message: str) -> None:
        if log_func is not None:
            log_func(str(message))

    project_root = Path(project.project_root).resolve()
    thresholds = DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS
    from Tools.Stats.data.shared_rois import load_rois_from_settings

    dataset_index = load_project_dataset_index(project_root)
    subjects = list(dataset_index.participant_ids)
    conditions = list(dataset_index.conditions)
    subject_data = dataset_index.subject_data(require_group_assignment=True)
    subjects, subject_data = _filter_to_completed_subjects(
        project_root=project_root,
        subjects=subjects,
        subject_data=subject_data,
    )
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
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        rois=rois,
        settings=settings,
        log_func=_log,
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
    )
    summaries, auto_electrodes, auto_participants = _summarize_flags(flags, thresholds)
    analysis_fingerprint = _analysis_fingerprint(
        project_root=project_root,
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        selected_harmonics=selected_harmonics,
        thresholds=thresholds,
        flags=flags,
    )
    state = load_frequency_domain_qc_state(project_root)
    current_auto_electrodes = _auto_electrode_entries_from_state(state)
    current_auto_participants = _auto_participant_entries_from_state(state)
    current_manual = _manual_entries_from_state(state)
    current_decision_fingerprint = _decision_fingerprint(
        analysis_fingerprint=analysis_fingerprint,
        auto_electrodes=current_auto_electrodes,
        auto_participants=current_auto_participants,
        manual_participants=current_manual,
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
    report = {
        "schema_version": FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
        "method_version": FREQUENCY_DOMAIN_QC_METHOD_VERSION,
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
    return report


def apply_frequency_domain_qc_decision(
    project_root: str | Path,
    report: Mapping[str, object],
    *,
    manual_participant_reasons: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Persist a reviewed QC decision and write the human-readable report."""

    root = Path(project_root).resolve()
    manifest_path = root / "project.json"
    manifest = _read_manifest(manifest_path)
    state = _metadata_from_manifest(manifest)
    now = _now_utc_iso()
    auto_electrodes = _normalize_auto_electrode_entries(
        report.get("auto_participant_electrode_exclusions")
    )
    auto_participants = _normalize_auto_participant_entries(
        report.get("auto_participant_exclusions")
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
    analysis_fingerprint = str(report.get("analysis_fingerprint") or "")
    decision_fingerprint = _decision_fingerprint(
        analysis_fingerprint=analysis_fingerprint,
        auto_electrodes=auto_electrodes,
        auto_participants=auto_participants,
        manual_participants=manual_entries,
    )
    report_path = _write_frequency_domain_qc_text_report(
        root,
        report=report,
        manual_participants=manual_entries,
        decision_fingerprint=decision_fingerprint,
        reviewed_at=now,
    )
    state.update(
        {
            "schema_version": FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
            "method_version": FREQUENCY_DOMAIN_QC_METHOD_VERSION,
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
    )
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
    previous_auto_electrodes = _auto_electrode_entries_from_state(state)
    previous_auto_participants = _auto_participant_entries_from_state(state)
    auto_electrodes = _normalize_auto_electrode_entries(
        report.get("auto_participant_electrode_exclusions")
    )
    auto_participants = _normalize_auto_participant_entries(
        report.get("auto_participant_exclusions")
    )
    automatic_state_changed = (
        previous_auto_electrodes != auto_electrodes
        or previous_auto_participants != auto_participants
    )
    state.update(
        {
            "schema_version": FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
            "method_version": FREQUENCY_DOMAIN_QC_METHOD_VERSION,
            "thresholds": DEFAULT_FREQUENCY_DOMAIN_QC_THRESHOLDS.to_manifest(),
            "auto_participant_electrode_exclusions": auto_electrodes,
            "auto_participant_exclusions": auto_participants,
            "last_automatic_qc": {
                "reviewed_at": _now_utc_iso(),
                "analysis_fingerprint": str(report.get("analysis_fingerprint") or ""),
                "review_required": bool(report.get("review_required")),
                "review_reused": bool(report.get("review_reused")),
            },
        }
    )
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
    return FrequencyDomainExclusions(
        excluded_participants=frozenset(auto_participants | manual_participants),
        auto_excluded_participants=frozenset(auto_participants),
        manual_excluded_participants=frozenset(manual_participants),
        auto_excluded_electrodes_by_participant={
            pid: frozenset(sorted(electrodes))
            for pid, electrodes in electrodes_by_pid.items()
        },
        downstream_outputs_stale=bool(state.get("downstream_outputs_stale", False)),
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


def frequency_domain_excluded_electrodes_for_subject(
    project_root: str | Path | None,
    participant_id: object,
) -> frozenset[str]:
    exclusions = active_frequency_domain_exclusions(project_root)
    pid = _normalize_participant_id(participant_id)
    return exclusions.auto_excluded_electrodes_by_participant.get(pid, frozenset())


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
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    rois: dict[str, list[str]],
    settings: Any,
    log_func: Callable[[str], None],
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
            project_root=None,
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
) -> list[dict[str, object]]:
    from Tools.Stats.io.xlsx_selected_reader import (
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
                flags.append(
                    {
                        "participant_id": _normalize_participant_id(subject),
                        "condition": str(condition),
                        "electrode": _normalize_electrode(electrode),
                        "summed_bca_uv": float(value),
                        "abs_summed_bca_uv": float(abs_value),
                        "severity": severity,
                        "workbook_path": str(file_path),
                    }
                )
    return sorted(
        flags,
        key=lambda item: (
            str(item.get("participant_id") or ""),
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


def _analysis_fingerprint(
    *,
    project_root: Path,
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
    selected_harmonics: Sequence[float],
    thresholds: FrequencyDomainQcThresholds,
    flags: Sequence[Mapping[str, object]],
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
            workbooks.append(
                {
                    "subject": str(subject),
                    "condition": str(condition),
                    "path": _manifest_safe_path(project_root, path),
                    "size_bytes": size,
                    "mtime_ns": mtime,
                }
            )
    payload = {
        "method_version": FREQUENCY_DOMAIN_QC_METHOD_VERSION,
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
    return _hash_payload(payload)


def _decision_fingerprint(
    *,
    analysis_fingerprint: str,
    auto_electrodes: Sequence[Mapping[str, object]],
    auto_participants: Sequence[Mapping[str, object]],
    manual_participants: Sequence[Mapping[str, object]],
) -> str:
    payload = {
        "analysis_fingerprint": str(analysis_fingerprint),
        "auto_electrodes": _json_safe(_normalize_auto_electrode_entries(auto_electrodes)),
        "auto_participants": _json_safe(_normalize_auto_participant_entries(auto_participants)),
        "manual_participants": _json_safe(_normalize_manual_entries(manual_participants)),
    }
    return _hash_payload(payload)


def _write_frequency_domain_qc_text_report(
    project_root: Path,
    *,
    report: Mapping[str, object],
    manual_participants: Sequence[Mapping[str, object]],
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
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _find_first_bca_columns(
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
) -> list[object]:
    from Tools.Stats.io.xlsx_selected_reader import read_xlsx_sheet_header

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

    raw_preprocessing = getattr(project, "preprocessing", {}) or {}
    try:
        preprocessing = normalize_preprocessing_settings(raw_preprocessing)
    except ValueError:
        preprocessing = normalize_preprocessing_settings({})
    return normalize_dv_policy(
        {
            "name": preprocessing.get(
                "harmonic_selection_policy",
                GROUP_SIGNIFICANT_POLICY_NAME,
            ),
            "fixed_harmonic_frequencies_hz": preprocessing.get(
                "fixed_harmonic_frequencies_hz",
                "",
            ),
            "fixed_harmonic_auto_exclude_base": preprocessing.get(
                "fixed_harmonic_auto_exclude_base",
                True,
            ),
            "group_significant_electrode_scope": preprocessing.get(
                "group_significant_electrode_scope",
                GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
            ),
            "group_significant_summation_method": preprocessing.get(
                "group_significant_summation_method",
                GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
            ),
        }
    )


def _filter_preprocessing_manual_exclusions(project: Any, subjects: list[str]) -> list[str]:
    preprocessing = getattr(project, "preprocessing", {}) or {}
    excluded = set(
        normalize_manual_excluded_participants(
            preprocessing.get("manual_excluded_participants", [])
        )
    )
    return [subject for subject in subjects if str(subject).upper() not in excluded]


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


def _iter_mapping_entries(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _normalize_participant_id(value: object) -> str:
    text = str(value or "").strip().upper()
    return text


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
    "active_frequency_domain_exclusions",
    "apply_frequency_domain_qc_decision",
    "clear_manual_frequency_domain_participant_exclusions",
    "filter_frequency_domain_subjects",
    "frequency_domain_excluded_electrodes_for_subject",
    "is_frequency_domain_output_stale",
    "load_frequency_domain_qc_state",
    "mark_frequency_domain_outputs_current",
    "mark_frequency_domain_outputs_stale",
    "run_frequency_domain_qc_review",
    "sync_frequency_domain_qc_automatic_state",
    "thresholds_summary_lines",
]

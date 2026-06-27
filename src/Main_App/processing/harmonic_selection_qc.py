"""Processing-end harmonic-selection cache and QC export."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

from Main_App.processing.processing_ledger import load_ledger
from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
)
from Tools.Stats.analysis.dv_policy_settings import DVPolicySettings
from Tools.Stats.data.shared_rois import load_rois_from_settings
from Tools.Stats.data.stats_data_loader import scan_folder_simple
from Tools.Stats.io.harmonic_selection_export import (
    HARMONIC_SELECTION_QC_WORKBOOK_NAME,
    write_harmonic_selection_workbook,
)

QUALITY_CHECK_FOLDER = "Quality Check"


@dataclass(frozen=True)
class ProcessingHarmonicSelectionReport:
    workbook_path: Path
    selection_metadata: dict[str, object]
    messages: tuple[str, ...]


def run_processing_harmonic_selection_qc(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> ProcessingHarmonicSelectionReport:
    """Build and persist the project harmonic-selection cache after processing."""
    messages: list[str] = []

    def _log(message: str) -> None:
        messages.append(str(message))
        if log_func is not None:
            log_func(str(message))

    project_root = Path(project.project_root).resolve()
    subfolders = getattr(project, "subfolders", {}) or {}
    excel_root = Path(subfolders.get("excel") or (project_root / "1 - Excel Data Files"))
    subjects, conditions, subject_data = scan_folder_simple(str(excel_root))
    subjects, subject_data = _filter_to_completed_subjects(
        project_root=project_root,
        subjects=subjects,
        subject_data=subject_data,
    )
    ordered_conditions = _ordered_conditions(project, conditions)
    subject_data = _filter_subject_data(subject_data, ordered_conditions)
    subjects = [subject for subject in subjects if subject_data.get(subject)]
    if not subjects or not ordered_conditions:
        raise RuntimeError(
            "Harmonic selection QC could not find completed condition workbooks."
        )

    rois = load_rois_from_settings() or {}
    selection = build_group_significant_harmonic_selection(
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        base_frequency_hz=_analysis_base_frequency_hz(),
        rois=rois,
        log_func=_log,
        settings=DVPolicySettings(),
        max_freq=_analysis_bca_upper_limit_hz(),
        project_root=project_root,
    )
    metadata = selection.to_metadata()
    qc_folder = project_root / QUALITY_CHECK_FOLDER
    qc_folder.mkdir(parents=True, exist_ok=True)
    workbook_path = write_harmonic_selection_workbook(
        qc_folder / HARMONIC_SELECTION_QC_WORKBOOK_NAME,
        metadata,
    )
    return ProcessingHarmonicSelectionReport(
        workbook_path=workbook_path,
        selection_metadata=metadata,
        messages=tuple(messages),
    )


def _filter_to_completed_subjects(
    *,
    project_root: Path,
    subjects: list[str],
    subject_data: dict[str, dict[str, str]],
) -> tuple[list[str], dict[str, dict[str, str]]]:
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


__all__ = [
    "ProcessingHarmonicSelectionReport",
    "run_processing_harmonic_selection_qc",
]

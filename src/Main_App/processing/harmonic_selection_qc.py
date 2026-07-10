"""Processing-end harmonic-selection cache and QC export."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping

from Main_App.processing.processing_ledger import load_ledger
from Main_App.processing.frequency_domain_qc import filter_frequency_domain_subjects
from Tools.Stats.analysis.dv_policy_group_significant import (
    GroupSignificantHarmonicSelection,
    build_group_significant_harmonic_selection,
    group_significant_selection_from_metadata,
)
from Tools.Stats.analysis.dv_policies import prepare_summed_bca_data
from Tools.Stats.analysis.dv_policy_settings import (
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    GROUP_SIGNIFICANT_POLICY_NAME,
    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
    DVPolicySettings,
    normalize_dv_policy,
)
from Tools.Stats.data.shared_rois import load_rois_from_settings
from Tools.Stats.data.group_harmonic_cache import (
    build_group_harmonic_cache_request,
    lookup_cached_group_harmonic_selection,
)
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


@dataclass(frozen=True)
class ProcessingHarmonicSelectionInputs:
    """Project-wide inputs that define the processing-time harmonic selection."""

    project_root: Path
    subjects: tuple[str, ...]
    conditions: tuple[str, ...]
    subject_data: dict[str, dict[str, str]]
    rois: dict[str, list[str]]
    settings: DVPolicySettings
    base_frequency_hz: float
    max_frequency_hz: float | None


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

    inputs = _processing_harmonic_selection_inputs(project, log_func=_log)
    project_root = inputs.project_root
    subjects = list(inputs.subjects)
    ordered_conditions = list(inputs.conditions)
    subject_data = inputs.subject_data
    rois = inputs.rois
    settings = inputs.settings
    base_frequency_hz = inputs.base_frequency_hz
    max_frequency_hz = inputs.max_frequency_hz
    if settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        selection = build_group_significant_harmonic_selection(
            subjects=subjects,
            conditions=ordered_conditions,
            subject_data=subject_data,
            base_frequency_hz=base_frequency_hz,
            rois=rois,
            log_func=_log,
            settings=settings,
            max_freq=max_frequency_hz,
            project_root=project_root,
        )
        metadata = selection.to_metadata()
    else:
        dv_metadata: dict[str, object] = {}
        prepare_summed_bca_data(
            subjects=subjects,
            conditions=ordered_conditions,
            subject_data=subject_data,
            base_freq=base_frequency_hz,
            rois=rois,
            log_func=_log,
            dv_policy=_dv_policy_payload(settings),
            dv_metadata=dv_metadata,
            max_freq=max_frequency_hz,
            project_root=str(project_root),
        )
        fixed_metadata = dv_metadata.get("fixed_predefined_harmonics")
        if not isinstance(fixed_metadata, Mapping):
            raise RuntimeError("Harmonic selection QC could not build fixed harmonic metadata.")
        metadata = dict(fixed_metadata)
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


def load_processing_harmonic_selection(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> GroupSignificantHarmonicSelection:
    """Load the current processing-time significant harmonics without recalculating."""

    inputs = _processing_harmonic_selection_inputs(project, log_func=log_func)
    if inputs.settings.name != GROUP_SIGNIFICANT_POLICY_NAME:
        raise RuntimeError(
            "This project does not have a processing-time group-significant "
            "harmonic selection. Reprocess the project with the group-significant "
            "harmonic policy before using significant-harmonic downstream tools."
        )
    cache_request = build_group_harmonic_cache_request(
        project_root=inputs.project_root,
        subjects=inputs.subjects,
        conditions=inputs.conditions,
        subject_data=inputs.subject_data,
        base_frequency_hz=inputs.base_frequency_hz,
        max_freq_hz=inputs.max_frequency_hz,
        settings=inputs.settings,
        rois=inputs.rois,
    )
    lookup = lookup_cached_group_harmonic_selection(cache_request)
    if lookup.hit is None:
        raise RuntimeError(
            "No current processing-time significant-harmonic selection is available. "
            "Reprocess the project or use Settings to recalculate harmonic selection, "
            f"then try again. Details: {lookup.reason}"
        )
    try:
        selection = group_significant_selection_from_metadata(
            lookup.hit.selection_metadata,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "The saved processing-time significant-harmonic selection is invalid. "
            "Reprocess the project or recalculate harmonic selection in Settings."
        ) from exc
    loaded = replace(
        selection,
        selection_cache_source="saved_processing_metadata",
        selection_cache_saved_at=lookup.hit.saved_at,
        selection_cache_key=lookup.hit.cache_key,
    )
    if log_func is not None:
        log_func(
            "Loaded processing-time significant harmonics from project metadata: "
            + ", ".join(f"{freq:g} Hz" for freq in loaded.selected_harmonics_hz)
        )
    return loaded


def _processing_harmonic_selection_inputs(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> ProcessingHarmonicSelectionInputs:
    """Resolve the canonical project-wide inputs used during processing."""

    project_root = Path(project.project_root).resolve()
    subfolders = getattr(project, "subfolders", {}) or {}
    excel_root = _project_subfolder_path(
        project_root,
        subfolders.get("excel") if isinstance(subfolders, Mapping) else None,
        "1 - Excel Data Files",
    )
    subjects, conditions, subject_data = scan_folder_simple(str(excel_root))
    subjects, subject_data = _filter_to_completed_subjects(
        project_root=project_root,
        subjects=subjects,
        subject_data=subject_data,
    )
    ordered_conditions = _ordered_conditions(project, conditions)
    subject_data = _filter_subject_data(subject_data, ordered_conditions)
    subjects = [subject for subject in subjects if subject_data.get(subject)]
    subjects, subject_data, frequency_excluded = filter_frequency_domain_subjects(
        project_root,
        subjects,
        subject_data,
    )
    if frequency_excluded:
        message = (
            "Frequency-domain participant exclusions applied before final harmonic "
            "selection: " + ", ".join(frequency_excluded)
        )
        if log_func is not None:
            log_func(message)
    if not subjects or not ordered_conditions:
        raise RuntimeError(
            "Harmonic selection QC could not find completed condition workbooks."
        )

    rois = load_rois_from_settings() or {}
    settings = _harmonic_selection_settings(project)
    return ProcessingHarmonicSelectionInputs(
        project_root=project_root,
        subjects=tuple(subjects),
        conditions=tuple(ordered_conditions),
        subject_data=subject_data,
        rois={str(name): [str(channel) for channel in channels] for name, channels in rois.items()},
        settings=settings,
        base_frequency_hz=_analysis_base_frequency_hz(),
        max_frequency_hz=_analysis_bca_upper_limit_hz(),
    )


def _dv_policy_payload(settings: DVPolicySettings) -> dict[str, object]:
    return {
        "name": settings.name,
        "fixed_harmonic_frequencies_hz": settings.fixed_harmonic_frequencies_hz,
        "fixed_harmonic_auto_exclude_base": settings.fixed_harmonic_auto_exclude_base,
        "fixed_harmonic_base_tolerance_hz": settings.fixed_harmonic_base_tolerance_hz,
        "fixed_harmonic_matching_tolerance_hz": settings.fixed_harmonic_matching_tolerance_hz,
        "group_significant_z_threshold": settings.group_significant_z_threshold,
        "group_significant_electrode_scope": settings.group_significant_electrode_scope,
        "group_significant_summation_method": settings.group_significant_summation_method,
        "group_significant_oddball_frequency_hz": settings.group_significant_oddball_frequency_hz,
    }


def _harmonic_selection_settings(project: Any) -> DVPolicySettings:
    from Main_App.projects.preprocessing_settings import (
        normalize_preprocessing_settings,
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


def _project_subfolder_path(
    project_root: Path,
    configured: object,
    default_name: str,
) -> Path:
    raw_path = Path(str(configured or default_name))
    if raw_path.is_absolute():
        return raw_path
    return project_root / raw_path


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
    "ProcessingHarmonicSelectionInputs",
    "ProcessingHarmonicSelectionReport",
    "load_processing_harmonic_selection",
    "run_processing_harmonic_selection_qc",
]

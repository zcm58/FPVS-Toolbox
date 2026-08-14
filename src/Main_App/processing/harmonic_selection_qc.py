"""Processing-owned harmonic-selection persistence and QC export."""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from Main_App.projects import ProjectDatasetIndex, load_project_dataset_index
from Main_App.processing.processing_ledger import load_ledger
from Main_App.processing.frequency_domain_qc import filter_frequency_domain_subjects
from Tools.Stats.analysis.dv_policy_group_significant import (
    GroupSignificantHarmonicSelection,
    build_group_significant_harmonic_selection,
    group_significant_selection_from_metadata,
)
from Tools.Stats.analysis.dv_policy_fixed_predefined import (
    _prepare_fixed_predefined_bca_data,
)
from Tools.Stats.analysis.dv_policy_settings import (
    GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
    GROUP_SIGNIFICANT_POLICY_NAME,
    GROUP_SIGNIFICANT_SUMMATION_THROUGH_HIGHEST,
    DVPolicySettings,
    HARMONIC_PROFILE_FIXED_ID,
    normalize_dv_policy,
)
from Tools.Stats.analysis.canonical_harmonics import (
    compute_selection_fingerprint,
)
from Tools.Stats.data.shared_rois import load_rois_from_settings
from Tools.Stats.data.group_harmonic_cache import (
    GroupHarmonicCacheRequest,
    build_group_harmonic_cache_request,
    lookup_cached_group_harmonic_selection,
)
from Tools.Stats.io.harmonic_selection_export import (
    HARMONIC_SELECTION_QC_WORKBOOK_NAME,
    write_harmonic_selection_workbook,
)

QUALITY_CHECK_FOLDER = "Quality Check"
PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION = 1
PROCESSING_HARMONIC_SELECTION_MANIFEST_PATH = (
    "tools",
    "processing",
    "harmonic_selection",
)
_PROCESSING_HARMONIC_SELECTION_HISTORY_LIMIT = 12


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


@dataclass(frozen=True)
class PersistedFixedHarmonicSelection:
    """Fixed-profile selection rehydrated from canonical project metadata."""

    selection_metadata: dict[str, object]
    selection_cache_source: str = "saved_processing_metadata"
    selection_cache_saved_at: str | None = None
    selection_cache_key: str | None = None

    @property
    def selected_harmonics_hz(self) -> list[float]:
        return _metadata_frequency_list(
            self.selection_metadata.get("selected_harmonics_hz"),
            field="selected_harmonics_hz",
        )

    @property
    def included_frequencies_hz(self) -> list[float]:
        return self.selected_harmonics_hz

    @property
    def included_columns(self) -> list[str]:
        value = self.selection_metadata.get("selected_columns")
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise ValueError("Saved selected_columns must be a list of BCA columns.")
        columns = [str(column).strip() for column in value if str(column).strip()]
        if len(columns) != len(self.selected_harmonics_hz):
            raise ValueError(
                "Saved fixed harmonic frequencies and BCA columns have different lengths."
            )
        return columns

    @property
    def detected_significant_harmonics_hz(self) -> list[float]:
        return _metadata_frequency_list(
            self.selection_metadata.get("detected_significant_harmonics_hz", []),
            field="detected_significant_harmonics_hz",
            allow_empty=True,
        )

    @property
    def oddball_frequency_hz(self) -> float:
        value = float(self.selection_metadata.get("oddball_frequency_hz", 1.2))
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("Saved oddball frequency must be positive and finite.")
        return value

    def to_metadata(self) -> dict[str, object]:
        metadata = copy.deepcopy(self.selection_metadata)
        metadata.update(
            {
                "selection_cache_source": self.selection_cache_source,
                "selection_cache_saved_at": self.selection_cache_saved_at,
                "selection_cache_key": self.selection_cache_key,
            }
        )
        return metadata


def run_processing_harmonic_selection_qc(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
    dataset_index: ProjectDatasetIndex | None = None,
    force_recalculate: bool = False,
) -> ProcessingHarmonicSelectionReport:
    """Build and persist the project harmonic-selection cache after processing.

    ``force_recalculate`` bypasses reusable selections without deleting the
    durable entry first. The newly calculated selection replaces the current
    fingerprint only after the calculation and project-metadata write succeed.
    """
    messages: list[str] = []

    def _log(message: str) -> None:
        messages.append(str(message))
        if log_func is not None:
            log_func(str(message))

    if dataset_index is None:
        inputs = _processing_harmonic_selection_inputs(
            project,
            log_func=_log,
        )
    else:
        inputs = _processing_harmonic_selection_inputs(
            project,
            log_func=_log,
            dataset_index=dataset_index,
        )
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
            force_recalculate=force_recalculate,
        )
        if (
            force_recalculate
            and selection.selection_cache_source
            != "computed_this_run_saved_project_metadata"
        ):
            raise RuntimeError(
                "Harmonic selection was recalculated but the replacement could "
                "not be saved to project metadata. The previous saved selection "
                "was left unchanged."
            )
        metadata = selection.to_metadata()
        _require_persisted_group_harmonic_selection(inputs)
    else:
        dv_metadata: dict[str, object] = {}
        fixed_data = _prepare_fixed_predefined_bca_data(
            subjects=subjects,
            conditions=ordered_conditions,
            subject_data=subject_data,
            base_freq=base_frequency_hz,
            rois=rois,
            log_func=_log,
            settings=settings,
            dv_metadata=dv_metadata,
            project_root=project_root,
            use_accepted_processing_selection=False,
        )
        if fixed_data is None:
            raise RuntimeError("Harmonic selection QC could not build fixed harmonics.")
        fixed_metadata = dv_metadata.get("fixed_predefined_harmonics")
        if not isinstance(fixed_metadata, Mapping):
            raise RuntimeError("Harmonic selection QC could not build fixed harmonic metadata.")
        metadata = dict(fixed_metadata)
    metadata = _canonical_selection_metadata(inputs, metadata)
    qc_folder = project_root / QUALITY_CHECK_FOLDER
    qc_folder.mkdir(parents=True, exist_ok=True)
    workbook_path = write_harmonic_selection_workbook(
        qc_folder / HARMONIC_SELECTION_QC_WORKBOOK_NAME,
        metadata,
    )
    _persist_processing_harmonic_selection(inputs, metadata)
    return ProcessingHarmonicSelectionReport(
        workbook_path=workbook_path,
        selection_metadata=metadata,
        messages=tuple(messages),
    )


def _require_persisted_group_harmonic_selection(
    inputs: ProcessingHarmonicSelectionInputs,
) -> None:
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
    if lookup.hit is not None:
        return
    raise RuntimeError(
        "Harmonic selection was calculated but could not be saved to project "
        "metadata, so downstream tools cannot load it. Close other processes "
        "that may be writing project.json, then use Settings > Recalculate "
        f"Harmonics again. Details: {lookup.reason}"
    )


def _canonical_selection_metadata(
    inputs: ProcessingHarmonicSelectionInputs,
    metadata: Mapping[str, object],
) -> dict[str, object]:
    """Return one portable metadata payload shared by every policy profile."""

    canonical = copy.deepcopy(dict(metadata))
    canonical["harmonic_selection_profile"] = (
        inputs.settings.harmonic_selection_profile
    )
    canonical["harmonic_selection_profile_version"] = (
        inputs.settings.harmonic_selection_profile_version
    )
    request = _processing_cache_request(inputs)
    sources = request.fingerprint.get("source_workbooks")
    if isinstance(sources, list):
        # Cache request paths are rebased to the active project root. Reusing
        # this one source identity prevents fixed and adaptive profiles from
        # persisting machine-specific absolute paths.
        canonical["source_workbook_fingerprints"] = (
            _portable_source_workbook_fingerprints(sources)
        )
    canonical.pop("selection_fingerprint", None)
    canonical["selection_fingerprint"] = compute_selection_fingerprint(canonical)
    return canonical


def _processing_cache_request(
    inputs: ProcessingHarmonicSelectionInputs,
) -> GroupHarmonicCacheRequest:
    request = build_group_harmonic_cache_request(
        project_root=inputs.project_root,
        subjects=inputs.subjects,
        conditions=inputs.conditions,
        subject_data=inputs.subject_data,
        base_frequency_hz=inputs.base_frequency_hz,
        max_freq_hz=inputs.max_frequency_hz,
        settings=inputs.settings,
        rois=inputs.rois,
    )
    if request is None:
        raise RuntimeError(
            "Canonical harmonic selection requires a managed project.json manifest."
        )
    return request


def _processing_selection_input_fingerprint(
    inputs: ProcessingHarmonicSelectionInputs,
) -> str:
    request = _processing_cache_request(inputs)
    upstream_identity = copy.deepcopy(request.fingerprint)
    sources = upstream_identity.get("source_workbooks")
    if isinstance(sources, list):
        upstream_identity["source_workbooks"] = (
            _portable_source_workbook_fingerprints(sources)
        )
    return compute_selection_fingerprint(
        {
            "processing_harmonic_selection_schema_version": (
                PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION
            ),
            "upstream_input_identity": upstream_identity,
            "dv_policy": _dv_policy_payload(inputs.settings),
        }
    )


def _portable_source_workbook_fingerprints(
    sources: Sequence[object],
) -> list[dict[str, object]]:
    portable: list[dict[str, object]] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        row = copy.deepcopy(dict(source))
        row["path"] = str(row.get("path") or "").replace("\\", "/")
        portable.append(row)
    return portable


def _persist_processing_harmonic_selection(
    inputs: ProcessingHarmonicSelectionInputs,
    metadata: Mapping[str, object],
) -> str:
    """Atomically publish the canonical selection after QC export succeeds."""

    fingerprint = str(metadata.get("selection_fingerprint") or "").strip()
    if not fingerprint or fingerprint != compute_selection_fingerprint(metadata):
        raise RuntimeError(
            "Harmonic selection was calculated but its canonical fingerprint "
            "could not be validated, so it was not accepted for downstream use."
        )
    input_fingerprint = _processing_selection_input_fingerprint(inputs)
    saved_at = _now_utc_iso()
    active: dict[str, object] = {
        "schema_version": PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION,
        "saved_at": saved_at,
        "harmonic_selection_profile": inputs.settings.harmonic_selection_profile,
        "harmonic_selection_profile_version": (
            inputs.settings.harmonic_selection_profile_version
        ),
        "input_fingerprint": input_fingerprint,
        "selection_fingerprint": fingerprint,
        "selection_metadata": copy.deepcopy(dict(metadata)),
    }
    manifest_path = inputs.project_root / "project.json"
    manifest = _read_manifest_required(manifest_path)
    existing_state = _manifest_processing_harmonic_selection(manifest)
    history: list[object] = []
    if isinstance(existing_state, Mapping):
        raw_history = existing_state.get("history")
        if isinstance(raw_history, list):
            history = copy.deepcopy(raw_history)
        previous = existing_state.get("active")
        if (
            isinstance(previous, Mapping)
            and str(previous.get("selection_fingerprint") or "") != fingerprint
        ):
            history.append(copy.deepcopy(dict(previous)))
    state = {
        "schema_version": PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION,
        "active": active,
        "history": history[-_PROCESSING_HARMONIC_SELECTION_HISTORY_LIMIT:],
    }
    _set_manifest_processing_harmonic_selection(manifest, state)
    _write_manifest_atomic(manifest_path, manifest)

    persisted = _load_processing_harmonic_selection_record(inputs.project_root)
    if (
        persisted is None
        or str(persisted.get("selection_fingerprint") or "") != fingerprint
        or str(persisted.get("input_fingerprint") or "") != input_fingerprint
    ):
        raise RuntimeError(
            "Harmonic selection was calculated but could not be saved to project "
            "metadata, so downstream tools cannot load it. Close other processes "
            "that may be writing project.json, then use Settings > Recalculate "
            "Harmonics again."
        )
    return saved_at


def _migrate_legacy_group_harmonic_selection(
    inputs: ProcessingHarmonicSelectionInputs,
    *,
    log_func: Callable[[str], None] | None,
) -> GroupSignificantHarmonicSelection:
    """Promote a matching Stats group-cache entry to canonical processing state."""

    cache_request = _processing_cache_request(inputs)
    lookup = lookup_cached_group_harmonic_selection(cache_request)
    if lookup.hit is None:
        raise _missing_processing_selection_error(lookup.reason)
    try:
        selection = group_significant_selection_from_metadata(
            lookup.hit.selection_metadata,
        )
    except (TypeError, ValueError) as exc:
        raise _invalid_processing_selection_error(str(exc)) from exc
    metadata = _canonical_selection_metadata(inputs, selection.to_metadata())
    saved_at = _persist_processing_harmonic_selection(inputs, metadata)
    migrated = group_significant_selection_from_metadata(metadata)
    loaded = replace(
        migrated,
        selection_cache_source="saved_processing_metadata",
        selection_cache_saved_at=saved_at,
        selection_cache_key=cache_request.cache_key,
    )
    if log_func is not None:
        log_func(
            "Migrated matching Stats harmonic cache into canonical processing "
            "metadata: "
            + ", ".join(f"{freq:g} Hz" for freq in loaded.selected_harmonics_hz)
        )
    return loaded


def _missing_processing_selection_error(details: str) -> RuntimeError:
    return RuntimeError(
        "No current processing-time harmonic selection is available. Use "
        "Settings > Recalculate Harmonics in the current FPVS Toolbox version, "
        "then try again. EEG/FIF reprocessing is not required. Details: "
        + str(details)
    )


def _invalid_processing_selection_error(details: str) -> RuntimeError:
    return RuntimeError(
        "The saved processing-time harmonic selection is invalid. Use Settings "
        "> Recalculate Harmonics in the current FPVS Toolbox version; EEG/FIF "
        "reprocessing is not required. Details: "
        + str(details)
    )


def load_processing_harmonic_selection(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> GroupSignificantHarmonicSelection | PersistedFixedHarmonicSelection:
    """Load the current canonical processing selection without recalculating."""

    inputs = _processing_harmonic_selection_inputs(project, log_func=log_func)
    saved = _load_processing_harmonic_selection_record(inputs.project_root)
    if saved is None and inputs.settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        return _migrate_legacy_group_harmonic_selection(
            inputs,
            log_func=log_func,
        )
    if saved is None:
        raise _missing_processing_selection_error(
            "No canonical harmonic-selection record is saved for this project."
        )

    metadata = saved.get("selection_metadata")
    if not isinstance(metadata, Mapping):
        raise _invalid_processing_selection_error(
            "The saved record has no selection metadata."
        )
    profile_id = str(saved.get("harmonic_selection_profile") or "")
    profile_version = str(saved.get("harmonic_selection_profile_version") or "")
    if (
        profile_id != inputs.settings.harmonic_selection_profile
        or profile_version != inputs.settings.harmonic_selection_profile_version
    ):
        raise _missing_processing_selection_error(
            "The saved selection uses a different harmonic-selection profile "
            "or method version than the current project settings."
        )

    current_input_fingerprint = _processing_selection_input_fingerprint(inputs)
    saved_input_fingerprint = str(saved.get("input_fingerprint") or "")
    if not saved_input_fingerprint or saved_input_fingerprint != current_input_fingerprint:
        raise _missing_processing_selection_error(
            "The saved harmonic selection does not match the current cohort, "
            "workbooks, processing settings, or selection settings."
        )
    selection_fingerprint = str(saved.get("selection_fingerprint") or "")
    metadata_fingerprint = str(metadata.get("selection_fingerprint") or "")
    recomputed_fingerprint = compute_selection_fingerprint(metadata)
    if (
        not selection_fingerprint
        or selection_fingerprint != metadata_fingerprint
        or selection_fingerprint != recomputed_fingerprint
    ):
        raise _invalid_processing_selection_error(
            "The saved selection fingerprint does not match its metadata."
        )

    saved_at = str(saved.get("saved_at") or "") or None
    if inputs.settings.name != GROUP_SIGNIFICANT_POLICY_NAME:
        if profile_id != HARMONIC_PROFILE_FIXED_ID:
            raise _invalid_processing_selection_error(
                "A fixed policy was paired with a non-fixed method profile."
            )
        loaded_fixed = PersistedFixedHarmonicSelection(
            selection_metadata=copy.deepcopy(dict(metadata)),
            selection_cache_saved_at=saved_at,
            selection_cache_key=current_input_fingerprint,
        )
        # Validate required common fields before returning the object.
        _ = loaded_fixed.selected_harmonics_hz
        _ = loaded_fixed.included_columns
        if log_func is not None:
            log_func(
                "Loaded processing-time fixed harmonics from project metadata: "
                + ", ".join(
                    f"{freq:g} Hz" for freq in loaded_fixed.selected_harmonics_hz
                )
            )
        return loaded_fixed

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
    try:
        selection = group_significant_selection_from_metadata(
            dict(metadata),
        )
    except (TypeError, ValueError) as exc:
        raise _invalid_processing_selection_error(str(exc)) from exc
    loaded = replace(
        selection,
        selection_cache_source="saved_processing_metadata",
        selection_cache_saved_at=saved_at,
        selection_cache_key=(
            cache_request.cache_key
            if cache_request is not None
            else current_input_fingerprint
        ),
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
    dataset_index: ProjectDatasetIndex | None = None,
) -> ProcessingHarmonicSelectionInputs:
    """Resolve the canonical project-wide inputs used during processing."""

    project_root = Path(project.project_root).resolve()
    if dataset_index is None:
        dataset_index = load_project_dataset_index(project_root)
    elif dataset_index.project_root.resolve() != project_root:
        raise ValueError(
            "The supplied dataset index belongs to a different project root."
        )
    subjects = list(dataset_index.participant_ids)
    conditions = list(dataset_index.conditions)
    subject_data = dataset_index.subject_data(require_group_assignment=True)
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
        "harmonic_selection_profile": settings.harmonic_selection_profile,
        "harmonic_selection_profile_version": (
            settings.harmonic_selection_profile_version
        ),
        "fixed_harmonic_frequencies_hz": settings.fixed_harmonic_frequencies_hz,
        "fixed_harmonic_input_mode": settings.fixed_harmonic_input_mode,
        "fixed_harmonic_upper_harmonic_index": (
            settings.fixed_harmonic_upper_harmonic_index
        ),
        "fixed_harmonic_upper_frequency_hz": (
            settings.fixed_harmonic_upper_frequency_hz
        ),
        "fixed_harmonic_auto_exclude_base": settings.fixed_harmonic_auto_exclude_base,
        "fixed_harmonic_base_tolerance_hz": settings.fixed_harmonic_base_tolerance_hz,
        "fixed_harmonic_matching_tolerance_hz": settings.fixed_harmonic_matching_tolerance_hz,
        "group_significant_z_threshold": settings.group_significant_z_threshold,
        "group_significant_electrode_scope": settings.group_significant_electrode_scope,
        "group_significant_selection_electrodes": list(
            settings.group_significant_selection_electrodes
        ),
        "group_significant_summation_method": settings.group_significant_summation_method,
        "group_significant_oddball_frequency_hz": settings.group_significant_oddball_frequency_hz,
    }


def _harmonic_selection_settings(project: Any) -> DVPolicySettings:
    from Main_App.projects.preprocessing_settings import (
        normalize_preprocessing_settings,
    )

    raw_preprocessing = _persisted_preprocessing_settings(project)
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
    for optional_key in (
        "fixed_harmonic_base_tolerance_hz",
        "fixed_harmonic_matching_tolerance_hz",
        "group_significant_z_threshold",
    ):
        if raw_preprocessing.get(optional_key) not in (None, ""):
            policy[optional_key] = raw_preprocessing[optional_key]
    if "group_significant_electrode_scope" in raw_preprocessing:
        policy["group_significant_electrode_scope"] = raw_preprocessing[
            "group_significant_electrode_scope"
        ]
    elif raw_preprocessing.get("harmonic_selection_profile") in (None, ""):
        # Absence means exact Legacy, including its ROI-union selection scope.
        policy["group_significant_electrode_scope"] = preprocessing.get(
            "group_significant_electrode_scope",
            GROUP_SIGNIFICANT_ELECTRODE_SCOPE_ROI_UNION,
        )
    return normalize_dv_policy(policy)


def _persisted_preprocessing_settings(project: Any) -> dict[str, object]:
    """Read exact project settings without losing newly versioned keys."""

    project_root = getattr(project, "project_root", None)
    if project_root not in (None, ""):
        manifest_path = Path(project_root).resolve(strict=False) / "project.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, Mapping):
            preprocessing = manifest.get("preprocessing")
            if isinstance(preprocessing, Mapping):
                return copy.deepcopy(dict(preprocessing))
    fallback = getattr(project, "preprocessing", {}) or {}
    return copy.deepcopy(dict(fallback)) if isinstance(fallback, Mapping) else {}


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


def _load_processing_harmonic_selection_record(
    project_root: str | Path,
) -> dict[str, object] | None:
    manifest_path = Path(project_root).resolve(strict=False) / "project.json"
    if not manifest_path.is_file():
        return None
    manifest = _read_manifest_required(manifest_path)
    state = _manifest_processing_harmonic_selection(manifest)
    if state is None:
        return None
    active = state.get("active")
    if not isinstance(active, Mapping):
        raise _invalid_processing_selection_error(
            "The processing-owned project record has no active selection."
        )
    try:
        schema_version = int(active.get("schema_version"))
    except (TypeError, ValueError) as exc:
        raise _invalid_processing_selection_error(
            "The processing-owned project record has no valid schema version."
        ) from exc
    if schema_version != PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION:
        raise _invalid_processing_selection_error(
            "Unsupported processing harmonic-selection schema version "
            f"{schema_version}; expected "
            f"{PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION}."
        )
    return copy.deepcopy(dict(active))


def _manifest_processing_harmonic_selection(
    manifest: Mapping[str, object],
) -> Mapping[str, object] | None:
    current: object = manifest
    for key in PROCESSING_HARMONIC_SELECTION_MANIFEST_PATH:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current if isinstance(current, Mapping) else None


def _set_manifest_processing_harmonic_selection(
    manifest: dict[str, object],
    state: Mapping[str, object],
) -> None:
    node = manifest
    for key in PROCESSING_HARMONIC_SELECTION_MANIFEST_PATH[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[PROCESSING_HARMONIC_SELECTION_MANIFEST_PATH[-1]] = _json_safe(
        dict(state)
    )


def _read_manifest_required(manifest_path: Path) -> dict[str, object]:
    try:
        parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read the managed project manifest: {manifest_path}"
        ) from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("project.json must contain a JSON object.")
    return parsed


def _write_manifest_atomic(
    manifest_path: Path,
    manifest: Mapping[str, object],
) -> None:
    payload = json.dumps(
        _json_safe(dict(manifest)),
        indent=2,
        ensure_ascii=False,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{manifest_path.name}.harmonic-selection-",
        suffix=".tmp",
        dir=manifest_path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_manifest_with_retry(temporary_path, manifest_path)
    finally:
        try:
            temporary_path.unlink(missing_ok=True)
        except OSError:
            pass


def _replace_manifest_with_retry(
    temporary_path: Path,
    manifest_path: Path,
) -> None:
    for attempt, delay_seconds in enumerate(
        (0.0, 0.01, 0.02, 0.05, 0.1, 0.1),
        start=1,
    ):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            os.replace(temporary_path, manifest_path)
            return
        except PermissionError:
            if attempt == 6:
                raise


def _metadata_frequency_list(
    value: object,
    *,
    field: str,
    allow_empty: bool = False,
) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"Saved {field} must be a list of frequencies.")
    frequencies: list[float] = []
    for item in value:
        try:
            frequency = float(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Saved {field} contains a non-numeric value.") from exc
        if not math.isfinite(frequency) or frequency <= 0.0:
            raise ValueError(
                f"Saved {field} frequencies must be positive and finite."
            )
        frequencies.append(frequency)
    if not frequencies and not allow_empty:
        raise ValueError(f"Saved {field} cannot be empty.")
    return frequencies


def _json_safe(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _json_safe(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value) if math.isfinite(value) else None
    try:
        numeric = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)
    return float(numeric) if math.isfinite(numeric) else None


def _now_utc_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


__all__ = [
    "PROCESSING_HARMONIC_SELECTION_MANIFEST_PATH",
    "PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION",
    "PersistedFixedHarmonicSelection",
    "ProcessingHarmonicSelectionInputs",
    "ProcessingHarmonicSelectionReport",
    "load_processing_harmonic_selection",
    "run_processing_harmonic_selection_qc",
]

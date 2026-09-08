"""Processing-owned harmonic-selection persistence and QC export."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


from Main_App.projects import (
    ProjectDatasetIndex,
    normalize_frequency_protocol,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.processing.post_processing_context import (
    CACHE_MISS,
    cached_validation,
    capture_validation_files,
    remember_validation,
    validation_files_unchanged,
    validation_scope_active,
)
from Main_App.processing.frequency_domain_qc import (
    filter_frequency_domain_recordings,
    filter_frequency_domain_subjects,
)
from Main_App.processing.spectral_eligibility import (
    SPECTRAL_ELIGIBILITY_METHOD_VERSION,
    SpectralEligibilityError,
    intersect_eligible_harmonics,
    spectral_eligibility_from_rows,
)
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
from Main_App.processing.roi_settings import load_rois_from_settings
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
PROCESSING_HARMONIC_SELECTION_SCHEMA_VERSION = 2
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
    oddball_frequency_hz: float
    max_frequency_hz: float | None
    frequency_protocol_fingerprint: str = ""
    eligible_harmonic_orders: tuple[int, ...] = ()
    spectral_eligibility_fingerprint: str = ""
    spectral_eligibility_workbooks: tuple[tuple[str, str, str], ...] = ()
    recording_assignments: dict[str, dict[str, object]] = field(default_factory=dict)
    declared_session_ids: tuple[str, ...] = ()
    participant_group_ids: dict[str, str] = field(default_factory=dict)
    declared_group_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        oddball = float(self.oddball_frequency_hz)
        if not math.isfinite(oddball) or oddball <= 0.0:
            raise ValueError(
                "Processing harmonic selection requires an explicit positive "
                "canonical project oddball frequency."
            )
        object.__setattr__(self, "oddball_frequency_hz", oddball)

    @property
    def is_repeated_session(self) -> bool:
        return bool(self.recording_assignments)


def _inputs_are_repeated(inputs: object) -> bool:
    return bool(getattr(inputs, "recording_assignments", {}))


def _require_canonical_oddball_frequency(inputs: object) -> float:
    raw_value = getattr(inputs, "oddball_frequency_hz", None)
    try:
        value = float(raw_value)
    except (TypeError, ValueError, OverflowError) as error:
        raise RuntimeError(
            "Managed harmonic selection requires an explicit canonical project "
            "oddball frequency."
        ) from error
    if not math.isfinite(value) or value <= 0.0:
        raise RuntimeError(
            "Managed harmonic selection requires an explicit positive canonical "
            "project oddball frequency."
        )
    return value


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
        raw_value = self.selection_metadata.get("oddball_frequency_hz")
        if raw_value is None:
            raise ValueError("Saved harmonic selection lacks its project oddball frequency.")
        value = float(raw_value)
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
    from Main_App.processing.full_fft_provenance import (
        require_current_project_workbook_geometry,
    )

    require_current_project_workbook_geometry(
        project_root,
        dataset_index=dataset_index,
    )
    release_outcomes, release_coverage, release_receipt = (
        _current_final_release_context(project_root)
    )
    release_metadata = _final_release_metadata(
        release_outcomes,
        release_coverage,
        release_receipt,
    )
    subjects = list(inputs.subjects)
    ordered_conditions = list(inputs.conditions)
    subject_data = inputs.subject_data
    rois = inputs.rois
    settings = inputs.settings
    base_frequency_hz = inputs.base_frequency_hz
    max_frequency_hz = inputs.max_frequency_hz
    oddball_frequency_hz = _require_canonical_oddball_frequency(inputs)
    spectral_eligibility_fingerprint = str(
        getattr(inputs, "spectral_eligibility_fingerprint", "") or ""
    )
    eligible_harmonic_orders = (
        tuple(getattr(inputs, "eligible_harmonic_orders", ()) or ())
        if spectral_eligibility_fingerprint
        else None
    )
    if settings.name == GROUP_SIGNIFICANT_POLICY_NAME:
        expected_scalp_channels_by_subject_condition = {
            (cell.recording_id, cell.condition_label): tuple(
                cell.source_evidence.expected_scalp_channels
            )
            for cell in release_coverage.cells
            if cell.source_evidence is not None
            and not cell.downstream_cell_excluded
        }
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
            participant_group_ids=(
                inputs.participant_group_ids
                if _inputs_are_repeated(inputs)
                else None
            ),
            declared_group_ids=(
                inputs.declared_group_ids if _inputs_are_repeated(inputs) else None
            ),
            recording_assignments=(
                inputs.recording_assignments if _inputs_are_repeated(inputs) else None
            ),
            declared_session_ids=(
                inputs.declared_session_ids if _inputs_are_repeated(inputs) else None
            ),
            electrode_exclusions_by_subject_condition={
                (cell.recording_id, cell.condition_label): frozenset(
                    cell.whole_scalp_normalization.excluded_channels
                )
                for cell in release_coverage.cells
                if cell.source_evidence is not None
                and cell.whole_scalp_normalization is not None
            },
            expected_scalp_channels_by_subject_condition=(
                expected_scalp_channels_by_subject_condition or None
            ),
            oddball_frequency_hz=oddball_frequency_hz,
            eligible_harmonic_orders=eligible_harmonic_orders,
            spectral_eligibility_fingerprint=(
                spectral_eligibility_fingerprint or None
            ),
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
            oddball_frequency_hz=oddball_frequency_hz,
            eligible_harmonic_orders=eligible_harmonic_orders,
            final_roi_coverage=release_coverage,
        )
        if fixed_data is None:
            raise RuntimeError("Harmonic selection QC could not build fixed harmonics.")
        fixed_metadata = dv_metadata.get("fixed_predefined_harmonics")
        if not isinstance(fixed_metadata, Mapping):
            raise RuntimeError("Harmonic selection QC could not build fixed harmonic metadata.")
        metadata = dict(fixed_metadata)
    metadata = _canonical_selection_metadata(
        inputs,
        metadata,
        final_release_metadata=release_metadata,
    )
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
        recording_assignments=(
            inputs.recording_assignments if _inputs_are_repeated(inputs) else None
        ),
        declared_session_ids=(
            inputs.declared_session_ids if _inputs_are_repeated(inputs) else None
        ),
        oddball_frequency_hz=_require_canonical_oddball_frequency(inputs),
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
    *,
    final_release_metadata: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return one portable metadata payload shared by every policy profile."""

    canonical = copy.deepcopy(dict(metadata))
    release = dict(
        final_release_metadata
        if final_release_metadata is not None
        else _current_final_release_metadata(inputs.project_root)
    )
    canonical.update(release)
    canonical["harmonic_selection_profile"] = (
        inputs.settings.harmonic_selection_profile
    )
    canonical["harmonic_selection_profile_version"] = (
        inputs.settings.harmonic_selection_profile_version
    )
    canonical["oddball_frequency_hz"] = _require_canonical_oddball_frequency(
        inputs
    )
    spectral_fingerprint = str(
        getattr(inputs, "spectral_eligibility_fingerprint", "") or ""
    )
    if spectral_fingerprint:
        canonical.update(
            {
            "frequency_protocol_fingerprint": str(
                getattr(inputs, "frequency_protocol_fingerprint", "") or ""
            ),
            "eligible_harmonic_orders": list(
                getattr(inputs, "eligible_harmonic_orders", ()) or ()
            ),
            "spectral_eligibility_method_version": (
                SPECTRAL_ELIGIBILITY_METHOD_VERSION
            ),
            "spectral_eligibility_fingerprint": spectral_fingerprint,
            "spectral_eligibility_workbooks": [
                {
                    "subject": subject,
                    "condition": condition,
                    "eligibility_fingerprint": fingerprint,
                }
                for subject, condition, fingerprint in (
                    getattr(inputs, "spectral_eligibility_workbooks", ()) or ()
                )
            ],
            }
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
    if _inputs_are_repeated(inputs):
        canonical.update(
            {
                "selection_identity_level": "recording",
                "selection_recordings": list(inputs.subjects),
                "selection_subjects": list(
                    dict.fromkeys(
                        str(row.get("participant_id") or "")
                        for row in inputs.recording_assignments.values()
                        if str(row.get("participant_id") or "")
                    )
                ),
                "selection_conditions": list(inputs.conditions),
                "declared_session_ids": list(inputs.declared_session_ids),
                "declared_group_ids": list(inputs.declared_group_ids),
                "recording_assignments": [
                    dict(inputs.recording_assignments[recording_id])
                    for recording_id in inputs.subjects
                ],
                "applied_uniformly_across_sessions": True,
            }
        )
    # Share the manifest representation with workbook/export callers: numeric
    # mapping keys and nonfinite diagnostics must not change during persistence.
    canonical = {str(key): _json_safe(value) for key, value in canonical.items()}
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
        recording_assignments=(
            inputs.recording_assignments if _inputs_are_repeated(inputs) else None
        ),
        declared_session_ids=(
            inputs.declared_session_ids if _inputs_are_repeated(inputs) else None
        ),
        oddball_frequency_hz=_require_canonical_oddball_frequency(inputs),
    )
    if request is None:
        raise RuntimeError(
            "Canonical harmonic selection requires a managed project.json manifest."
        )
    return request


def _processing_selection_input_fingerprint(
    inputs: ProcessingHarmonicSelectionInputs,
    *,
    cache_request: GroupHarmonicCacheRequest | None = None,
) -> str:
    request = cache_request or _processing_cache_request(inputs)
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
            "frequency_protocol_fingerprint": str(
                getattr(inputs, "frequency_protocol_fingerprint", "") or ""
            ),
            "spectral_eligibility_fingerprint": (
                str(getattr(inputs, "spectral_eligibility_fingerprint", "") or "")
            ),
            "eligible_harmonic_orders": list(
                getattr(inputs, "eligible_harmonic_orders", ()) or ()
            ),
            "final_release": _current_final_release_metadata(inputs.project_root),
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

    if not validation_scope_active():
        return _load_processing_harmonic_selection_uncached(project, log_func=log_func)

    from Main_App.projects import load_project_dataset_index
    from Main_App.processing.processing_ledger import ledger_path

    root = Path(project.project_root).resolve()
    # Re-scan canonical identity even on a hit: new, omitted, or regrouped
    # sources must never disappear behind the run-scoped optimization.
    index = load_project_dataset_index(root)
    release = _current_final_release_context(root)
    cache_key = _selection_validation_key(project, index, release)
    cached = cached_validation("processing_selection", cache_key)
    if cached is not CACHE_MISS:
        selection, messages = cached
        if log_func is not None:
            for message in messages:
                log_func(message)
        return selection

    manifest_files = capture_validation_files([root / "project.json"], hash_contents=True)
    ledger_files = capture_validation_files([ledger_path(root)], hash_contents=True)
    source_files = _selection_validation_sources(index)
    messages: list[str] = []

    def _log(message: str) -> None:
        messages.append(message)
        if log_func is not None:
            log_func(message)

    selection = _load_processing_harmonic_selection_uncached(project, log_func=_log)
    # Publication/migration may change the manifest during an initial read.
    # Never store that mixed observation; the next call validates it afresh.
    if validation_files_unchanged(manifest_files):
        remember_validation(
            "processing_selection", cache_key, (selection, tuple(messages)),
            files=(*ledger_files, *source_files),
        )
    return selection


def _selection_validation_key(project: Any, index: ProjectDatasetIndex, release: tuple) -> str:
    from Main_App.processing.artifact_freshness import ARTIFACT_FRESHNESS_MANIFEST_PATH
    from Main_App.processing.roi_coverage import _dataset_index_identity_payload

    manifest = copy.deepcopy(dict(index.manifest or {}))
    # Only derived-artifact publication is irrelevant. Preserve every other
    # manifest value, including the exact accepted metadata and QC decisions.
    parents = []
    node = manifest
    for field_name in ARTIFACT_FRESHNESS_MANIFEST_PATH[:-1]:
        child = node.get(field_name)
        if not isinstance(child, dict):
            break
        parents.append((node, field_name))
        node = child
    else:
        node.pop(ARTIFACT_FRESHNESS_MANIFEST_PATH[-1], None)
        for parent, field_name in reversed(parents):
            if not parent[field_name]:
                parent.pop(field_name)
    identity = {
        "manifest": manifest,
        "dataset": _dataset_index_identity_payload(index),
        "rois": list((load_rois_from_settings() or {}).items()),
        "policy": _dv_policy_payload(_harmonic_selection_settings(project)),
        "protocol": _current_project_frequency_protocol(project, index.project_root).fingerprint,
        "conditions": _ordered_conditions(project, list(index.conditions)),
        "final_release_receipt_fingerprint": release[2].fingerprint,
    }
    return hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _selection_validation_sources(index: ProjectDatasetIndex) -> tuple:
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    paths = [record.path for record in index.workbooks]
    workbook_files = capture_validation_files(paths, hash_contents=True)
    companion_paths = []
    for path in paths:
        for reader in (condition_companion_identity, spectral_companion_identity):
            descriptor = reader(path)
            if descriptor is not None:
                companion_paths.append(path.parent / descriptor["path"])
    return (*workbook_files, *capture_validation_files(companion_paths))


def _load_processing_harmonic_selection_uncached(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> GroupSignificantHarmonicSelection | PersistedFixedHarmonicSelection:
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

    cache_request = _processing_cache_request(inputs)
    current_input_fingerprint = _processing_selection_input_fingerprint(
        inputs, cache_request=cache_request,
    )
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


def load_processing_harmonic_selection_metadata(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
) -> dict[str, object]:
    """Return the exact validated canonical metadata persisted for the project."""

    loaded = load_processing_harmonic_selection(project, log_func=log_func)
    project_root = Path(project.project_root).resolve()
    saved = _load_processing_harmonic_selection_record(project_root)
    metadata = saved.get("selection_metadata") if isinstance(saved, Mapping) else None
    if not isinstance(metadata, Mapping):
        raise _invalid_processing_selection_error(
            "The validated saved selection has no canonical metadata payload."
        )
    # Keep the loaded object live through validation above; return the durable
    # payload rather than its presentation-only cache-source annotations.
    _ = loaded
    return copy.deepcopy(dict(metadata))


def _processing_harmonic_selection_inputs(
    project: Any,
    *,
    log_func: Callable[[str], None] | None = None,
    dataset_index: ProjectDatasetIndex | None = None,
) -> ProcessingHarmonicSelectionInputs:
    """Resolve the canonical project-wide inputs used during processing."""

    project_root = Path(project.project_root).resolve()
    from Main_App.processing.roi_coverage import (
        require_canonical_released_dataset_index,
    )

    dataset_index = require_canonical_released_dataset_index(
        project_root,
        dataset_index,
    )
    conditions = list(dataset_index.conditions)
    repeated_session = dataset_index.is_repeated_session
    if repeated_session:
        subjects = list(dataset_index.recording_ids)
        subject_data = dataset_index.recording_data(require_group_assignment=True)
        recording_assignments = _recording_assignments_from_index(dataset_index)
        participant_group_ids = dataset_index.participant_group_id_map()
        declared_group_ids = tuple(
            group.group_id for group in dataset_index.ordered_groups
        )
        declared_session_ids = tuple(
            session.session_id for session in dataset_index.ordered_sessions
        )
    else:
        subjects = list(dataset_index.participant_ids)
        subject_data = dataset_index.subject_data(require_group_assignment=True)
        recording_assignments = {}
        participant_group_ids = {}
        declared_group_ids = ()
        declared_session_ids = ()
    subjects, subject_data = _filter_to_completed_subjects(
        project_root=project_root,
        subjects=subjects,
        subject_data=subject_data,
    )
    ordered_conditions = _ordered_conditions(project, conditions)
    subject_data = _filter_subject_data(subject_data, ordered_conditions)
    subjects = [subject for subject in subjects if subject_data.get(subject)]
    if repeated_session:
        subjects = _filter_manual_participant_exclusions_from_recordings(
            project,
            subjects,
            recording_assignments=recording_assignments,
        )
        subject_data = {
            recording_id: dict(subject_data.get(recording_id, {}))
            for recording_id in subjects
            if subject_data.get(recording_id)
        }
        subjects, subject_data, frequency_excluded = (
            filter_frequency_domain_recordings(
                project_root,
                subjects,
                subject_data,
                recording_participant_ids={
                    recording_id: str(row.get("participant_id") or "")
                    for recording_id, row in recording_assignments.items()
                },
            )
        )
    else:
        subjects, subject_data, frequency_excluded = filter_frequency_domain_subjects(
            project_root,
            subjects,
            subject_data,
        )
    if frequency_excluded:
        message = (
            "Frequency-domain "
            + ("recording" if repeated_session else "participant")
            + " exclusions applied before final harmonic "
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
    frequency_protocol = _current_project_frequency_protocol(project, project_root)
    if (
        not frequency_protocol.is_ready
        or frequency_protocol.presentation_rate_hz is None
        or frequency_protocol.oddball_rate_hz is None
    ):
        raise RuntimeError(
            "Harmonic selection requires a complete project frequency protocol. "
            "Confirm the presentation rate, oddball recurrence/rate, expected "
            "analyzed cycles, and marker code before processing."
        )
    (
        eligible_harmonic_orders,
        spectral_eligibility_fingerprint,
        spectral_eligibility_workbooks,
    ) = _project_spectral_eligibility_domain(
        protocol=frequency_protocol,
        subjects=subjects,
        conditions=ordered_conditions,
        subject_data=subject_data,
        log_func=log_func,
    )
    return ProcessingHarmonicSelectionInputs(
        project_root=project_root,
        subjects=tuple(subjects),
        conditions=tuple(ordered_conditions),
        subject_data=subject_data,
        rois={str(name): [str(channel) for channel in channels] for name, channels in rois.items()},
        settings=settings,
        base_frequency_hz=float(frequency_protocol.presentation_rate_hz),
        max_frequency_hz=None,
        oddball_frequency_hz=float(frequency_protocol.oddball_rate_hz),
        frequency_protocol_fingerprint=frequency_protocol.fingerprint,
        eligible_harmonic_orders=eligible_harmonic_orders,
        spectral_eligibility_fingerprint=spectral_eligibility_fingerprint,
        spectral_eligibility_workbooks=spectral_eligibility_workbooks,
        recording_assignments={
            recording_id: dict(recording_assignments[recording_id])
            for recording_id in subjects
            if recording_id in recording_assignments
        },
        declared_session_ids=declared_session_ids,
        participant_group_ids=participant_group_ids,
        declared_group_ids=declared_group_ids,
    )


def resolve_processing_harmonic_selection_inputs(
    project: Any,
    log_func: Callable[[str], None] | None = None,
    dataset_index: ProjectDatasetIndex | None = None,
) -> ProcessingHarmonicSelectionInputs:
    """Return the side-effect-free canonical inputs used by frequency review.

    Frequency review and final harmonic selection must resolve the same cohort,
    conditions, protocol, eligible harmonics, ROIs, and policy.  This public
    wrapper keeps that resolution in one processing-owned implementation.
    """

    return _processing_harmonic_selection_inputs(
        project,
        log_func=log_func,
        dataset_index=dataset_index,
    )


def _current_final_release_metadata(project_root: Path) -> dict[str, object]:
    """Require and describe the current reviewed QC-20/QC-21 release chain."""

    return _final_release_metadata(*_current_final_release_context(project_root))


def _current_final_release_context(project_root: Path) -> tuple[Any, Any, Any]:
    """Load the one processing-owned final-release chain."""

    from Main_App.processing.roi_coverage import require_project_final_release

    return require_project_final_release(project_root)


def _final_release_metadata(
    outcomes: Any,
    coverage: Any,
    receipt: Any,
) -> dict[str, object]:
    return {
        "recording_condition_outcome_fingerprint": outcomes.fingerprint,
        "roi_definition_fingerprint": coverage.roi_snapshot.fingerprint,
        "roi_coverage_fingerprint": coverage.fingerprint,
        "frequency_review_decision_fingerprint": coverage.decision_fingerprint,
        "final_release_receipt_fingerprint": receipt.fingerprint,
    }


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


def _recording_assignments_from_index(
    dataset_index: ProjectDatasetIndex,
) -> dict[str, dict[str, object]]:
    participant_groups = dataset_index.participant_group_id_map()
    assignments: dict[str, dict[str, object]] = {}
    for recording_id in dataset_index.recording_ids:
        recording = dataset_index.recordings.get(recording_id)
        if recording is None:
            raise RuntimeError(
                "Repeated-session harmonic selection is missing the canonical "
                f"recording assignment for {recording_id}."
            )
        assignments[recording_id] = {
            "recording_id": recording_id,
            "participant_id": recording.participant_id,
            "group_id": participant_groups.get(recording.participant_id, ""),
            "session_id": recording.session_id,
            "source_id": recording.source_id,
            "visit_index": recording.visit_index,
            "days_from_baseline": recording.days_from_baseline,
        }
    return assignments


def _filter_manual_participant_exclusions_from_recordings(
    project: Any,
    recording_ids: list[str],
    *,
    recording_assignments: Mapping[str, Mapping[str, object]],
) -> list[str]:
    from Main_App.projects.preprocessing_settings import (
        normalize_manual_excluded_participants,
    )

    preprocessing = _persisted_preprocessing_settings(project)
    excluded = {
        str(participant_id).casefold()
        for participant_id in normalize_manual_excluded_participants(
            preprocessing.get("manual_excluded_participants", [])
        )
    }
    return [
        recording_id
        for recording_id in recording_ids
        if str(
            recording_assignments.get(recording_id, {}).get("participant_id") or ""
        ).casefold()
        not in excluded
    ]


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


def _current_project_frequency_protocol(project: Any, project_root: Path):
    raw_protocol = getattr(project, "frequency_protocol", None)
    if raw_protocol is None:
        manifest = _read_manifest_required(project_root / "project.json")
        raw_protocol = manifest.get("frequency_protocol")
    if raw_protocol is None:
        raise RuntimeError(
            "Harmonic selection cannot infer project rates from application defaults. "
            "Confirm the project frequency protocol and regenerate its workbooks."
        )
    try:
        return normalize_frequency_protocol(raw_protocol)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "The project frequency protocol is invalid; correct it before harmonic "
            "selection."
        ) from exc


def _project_spectral_eligibility_domain(
    *,
    protocol: Any,
    subjects: Sequence[str],
    conditions: Sequence[str],
    subject_data: Mapping[str, Mapping[str, str]],
    log_func: Callable[[str], None] | None,
) -> tuple[tuple[int, ...], str, tuple[tuple[str, str, str], ...]]:
    results = []
    workbook_identities: list[tuple[str, str, str]] = []
    for subject in subjects:
        for condition in conditions:
            file_path = (subject_data.get(str(subject), {}) or {}).get(str(condition))
            if not file_path:
                continue
            path = Path(file_path)
            try:
                from Main_App.io.condition_data import read_condition_sheet

                frame = read_condition_sheet(path, sheet_name="Spectral Eligibility")
            except (OSError, ValueError) as exc:
                raise SpectralEligibilityError(
                    "A current Spectral Eligibility sheet is required in every "
                    f"included frequency-domain workbook ({path}). Regenerate the "
                    "workbook before harmonic selection."
                ) from exc
            try:
                result = spectral_eligibility_from_rows(
                    frame.to_dict(orient="records"),
                    protocol=protocol,
                )
            except SpectralEligibilityError as exc:
                raise SpectralEligibilityError(f"{path}: {exc}") from exc
            results.append(result)
            workbook_identities.append(
                (str(subject), str(condition), result.fingerprint)
            )

    if not results:
        raise SpectralEligibilityError(
            "Harmonic selection found no current Spectral Eligibility sheets. "
            "Regenerate the frequency-domain workbooks."
        )
    common_targets = intersect_eligible_harmonics(results)
    eligible_orders = tuple(
        int(target.oddball_harmonic_order) for target in common_targets
    )
    if not eligible_orders:
        raise SpectralEligibilityError(
            "No standard harmonic is technically eligible across the included "
            "workbooks. Review their filter, notch, Nyquist, and analyzed-cycle "
            "provenance."
        )

    ordered_identities = tuple(
        sorted(workbook_identities, key=lambda row: (row[0].casefold(), row[1].casefold()))
    )
    intersection_fingerprint = compute_selection_fingerprint(
        {
            "spectral_eligibility_method_version": (
                SPECTRAL_ELIGIBILITY_METHOD_VERSION
            ),
            "frequency_protocol_fingerprint": protocol.fingerprint,
            "eligible_harmonic_orders": list(eligible_orders),
            "workbooks": [
                {
                    "subject": subject,
                    "condition": condition,
                    "eligibility_fingerprint": fingerprint,
                }
                for subject, condition, fingerprint in ordered_identities
            ],
        }
    )
    if log_func is not None:
        log_func(
            "Canonical spectral eligibility intersection: "
            f"{len(eligible_orders)} harmonics across {len(results)} included "
            "recording-condition workbooks."
        )
    return eligible_orders, intersection_fingerprint, ordered_identities


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
    "load_processing_harmonic_selection_metadata",
    "resolve_processing_harmonic_selection_inputs",
    "run_processing_harmonic_selection_qc",
]

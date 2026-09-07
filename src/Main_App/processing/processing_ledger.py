"""Project-local processing ledger and incremental planning helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    biosemi64_geometry_identity,
)
from Main_App.io.result_manifest import (
    RESULT_MANIFEST_SUFFIX,
    resolve_result_path,
    result_manifest_path,
)
from Main_App.processing.interpolation_burden import build_interpolation_burden
from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUSES,
    INTERPOLATION_STATUS_LEGACY_UNKNOWN,
    INTERPOLATION_STATUS_SKIPPED,
    PROCESSING_STATUS_COMPLETED,
    PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS,
    PROCESSING_STATUS_EXCLUDED,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_PENDING,
    PreprocessingOutcomeError,
    build_preprocessing_outcome,
)
from Main_App.processing.recording_condition_outcomes import (
    RECORDING_CONDITION_OUTCOME_LEDGER_KEY,
    RECORDING_CONDITION_OUTCOME_VERSION,
    RecordingConditionOutcomeError,
    reconcile_recording_condition_outputs,
)

from Main_App.processing.fft_multinotch import (
    FFT_MULTINOTCH_COMPONENT_COUNT,
    FFT_MULTINOTCH_HALF_WIDTH_HZ,
    FFT_MULTINOTCH_METHOD_VERSION,
)
from Main_App.projects.frequency_protocol import (
    FrequencyProtocol,
    FrequencyProtocolError,
    normalize_frequency_protocol,
)

from Main_App.processing.expected_processing_ledger import (
    EXPECTED_CELL_ACTION_EXCLUDE_CONDITION as EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
    EXPECTED_CELL_ACTION_EXCLUDE_RECORDING as EXPECTED_CELL_ACTION_EXCLUDE_RECORDING,
    EXPECTED_CELL_ACTION_LEGACY_UNKNOWN as EXPECTED_CELL_ACTION_LEGACY_UNKNOWN,
    EXPECTED_CELL_ACTION_PROCESS as EXPECTED_CELL_ACTION_PROCESS,
    EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN as EXPECTED_PLANNING_STATE_LEGACY_UNKNOWN,
    EXPECTED_PLANNING_STATE_PLANNED as EXPECTED_PLANNING_STATE_PLANNED,
    EXPECTED_RECORDING_ACTION_EXCLUDE as EXPECTED_RECORDING_ACTION_EXCLUDE,
    EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN as EXPECTED_RECORDING_ACTION_LEGACY_UNKNOWN,
    EXPECTED_RECORDING_ACTION_PROCESS as EXPECTED_RECORDING_ACTION_PROCESS,
    EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY as EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY,
    EXPECTED_RECORDING_CONDITION_PLAN_VERSION as EXPECTED_RECORDING_CONDITION_PLAN_VERSION,
    EXPECTED_WORKBOOK_NOT_REQUIRED as EXPECTED_WORKBOOK_NOT_REQUIRED,
    EXPECTED_WORKBOOK_REQUIRED as EXPECTED_WORKBOOK_REQUIRED,
    EXPECTED_WORKBOOK_UNRESOLVED as EXPECTED_WORKBOOK_UNRESOLVED,
    ExpectedOccurrencePlan as ExpectedOccurrencePlan,
    ExpectedRecordingConditionCell as ExpectedRecordingConditionCell,
    ExpectedRecordingConditionPlan as ExpectedRecordingConditionPlan,
    ExpectedRecordingConditionPlanError as ExpectedRecordingConditionPlanError,
    ExpectedRecordingPlan as ExpectedRecordingPlan,
    build_expected_recording_condition_plan as build_expected_recording_condition_plan,
    load_expected_recording_condition_plan as load_expected_recording_condition_plan,
    save_expected_recording_condition_plan as save_expected_recording_condition_plan,
)
from Main_App.projects.grouping import (
    project_group_context,
    resolve_group_output_directory,
    resolve_output_directory,
)

if TYPE_CHECKING:
    from Main_App.processing.processing_controller import RawFileInfo

logger = logging.getLogger(__name__)

PROCESSING_STATE_DIR = ".fpvs_processing"
LEDGER_FILENAME = "processing_ledger.json"
RUNS_FILENAME = "processing_runs.jsonl"
PROCESSING_FINGERPRINT_VERSION = (
    "processing_fingerprint_v13_v3_trigger_alignment"
)
_GEOMETRY_INDEPENDENT_EXCLUSION_REASONS = frozenset(
    {
        "manual_participant_exclusion",
        "manual_recording_exclusion",
        "recording_not_started",
    }
)
_DOWNSTREAM_ONLY_PREPROCESSING_KEYS = frozenset(
    {
        "interpolation_burden_review_decisions",
        # These describe how a detector choice was obtained, not the signal
        # transformation. The effective mode remains fingerprinted separately.
        "removed_electrode_detection_choice_schema_version",
        "removed_electrode_detection_choice_status",
        "removed_electrode_detection_choice_source",
    }
)
_REPEATED_SESSION_PREPROCESSING_KEYS = frozenset(
    {
        "manual_removed_electrodes_by_recording",
        "manual_excluded_recordings",
        "manual_excluded_recording_conditions",
    }
)
_FINGERPRINT_V9_EPOCH_DEFAULTS = {
    "epoch_start_s": -1.0,
    "epoch_end_s": 125.0,
}
GENERATED_EXCEL_SUFFIXES = {".xls", ".xlsx", ".xlsm", ".xlsb", RESULT_MANIFEST_SUFFIX}
MISSING_EXPECTED_OUTPUTS_WARNING = "missing_expected_outputs"
NO_EXPECTED_OUTPUTS_FAILURE = "no_expected_outputs"
SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT = (
    Path("6 - Source Localization") / "Source-Ready Time Domain v1"
)
REMOVED_ELECTRODE_REVIEW_LIST_KEYS = (
    "removed_electrode_original_auto_flagged",
    "removed_electrode_accepted_auto_flagged",
    "removed_electrode_rejected_auto_flagged",
    "removed_electrode_manual_additions",
    "removed_electrode_final_confirmed_removed",
    "removed_electrode_manual_only_missed_by_auto",
    "removed_electrode_auto_manual_overlap",
)
REMOVED_ELECTRODE_REVIEW_SCALAR_KEYS = ("removed_electrode_agreement_status",)
REPROCESS_ALL_DOWNSTREAM_FOLDER_DEFAULTS = {
    "snr": "2 - SNR Plots",
    "stats": "3 - Statistical Analysis Results",
    "scalp_maps": "4 - Scalp Maps",
    "source_localization": "6 - Source Localization",
    "tables": "9 - Tables",
}
REPROCESS_ALL_QUALITY_CHECK_DELETE_PATTERNS = (
    "Processing_QC_Summary.xlsx",
    "Harmonic_Selection_Summary.xlsx",
    "SNR_Unexpected_Peaks*.xlsx",
    "SNR_Spectral_QC*.xlsx",
)
REPROCESS_ALL_QUALITY_CHECK_PRESERVE = {
    "Data_Quality_Check_Review_Flags.xlsx",
}


@dataclass(frozen=True)
class ProcessingInputState:
    info: RawFileInfo
    participant_id: str
    status: str
    reason: str
    expected_outputs: tuple[Path, ...]

    @property
    def processing_id(self) -> str:
        """Return the ledger key for this raw recording.

        Legacy projects intentionally keep their participant-keyed entries;
        repeated-session projects use the canonical recording ID so a second
        visit cannot overwrite the first.
        """

        return self.info.processing_id

    @property
    def should_run_incremental(self) -> bool:
        return self.status not in {"completed", "excluded"}


@dataclass(frozen=True)
class ProcessingPlan:
    states: tuple[ProcessingInputState, ...]
    fingerprint: str
    condition_labels: tuple[str, ...]
    choice: str = "incremental"
    geometry_identity: Mapping[str, object] = field(default_factory=dict)

    @property
    def completed_count(self) -> int:
        return sum(1 for state in self.states if state.status == "completed")

    @property
    def incremental_files(self) -> tuple[Path, ...]:
        return tuple(
            state.info.path for state in self.states if state.should_run_incremental
        )

    @property
    def all_files(self) -> tuple[Path, ...]:
        return tuple(state.info.path for state in self.states)

    @property
    def run_files(self) -> tuple[Path, ...]:
        if self.choice in {"reprocess_all", "reprocess_this_file"}:
            return self.all_files
        return self.incremental_files

    @property
    def stale_count(self) -> int:
        return sum(
            1
            for state in self.states
            if state.status in {"changed_settings", "changed_raw", "missing_outputs"}
        )

    @property
    def new_count(self) -> int:
        return sum(1 for state in self.states if state.status == "new")

    @property
    def excluded_count(self) -> int:
        return sum(1 for state in self.states if state.status == "excluded")


def processing_state_dir(project_root: Path) -> Path:
    return Path(project_root) / PROCESSING_STATE_DIR


def ledger_path(project_root: Path) -> Path:
    return processing_state_dir(project_root) / LEDGER_FILENAME


def runs_path(project_root: Path) -> Path:
    return processing_state_dir(project_root) / RUNS_FILENAME


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def _export_receipts_payload(
    source: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(source, Mapping):
        return []
    raw_receipts = source.get("export_receipts")
    if not isinstance(raw_receipts, Sequence) or isinstance(
        raw_receipts,
        (str, bytes),
    ):
        return []
    return [dict(item) for item in raw_receipts if isinstance(item, Mapping)]


def _removed_electrode_review_payload(source: Mapping[str, Any] | None) -> dict[str, object]:
    payload: dict[str, object] = {}
    source = source or {}
    for key in REMOVED_ELECTRODE_REVIEW_LIST_KEYS:
        payload[key] = _string_list(source.get(key))
    for key in REMOVED_ELECTRODE_REVIEW_SCALAR_KEYS:
        payload[key] = str(source.get(key) or "")
    return payload


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _raw_qc_extra_payload(source: Mapping[str, Any] | None) -> dict[str, object]:
    source = source or {}
    return {
        "raw_qc_rare_burst_channels": _string_list(
            source.get("raw_qc_rare_burst_channels", source.get("rare_burst_channels"))
        ),
        "raw_qc_baseline_median_std_uv": _float_or_none(
            source.get(
                "raw_qc_baseline_median_std_uv",
                source.get("raw_baseline_median_std_uv"),
            )
        ),
        "raw_qc_baseline_median_p2p_99_uv": _float_or_none(
            source.get(
                "raw_qc_baseline_median_p2p_99_uv",
                source.get("raw_baseline_median_p2p_99_uv"),
            )
        ),
        "raw_qc_baseline_warning": bool(
            source.get("raw_qc_baseline_warning", source.get("raw_baseline_warning"))
        ),
        "raw_qc_baseline_excluded": bool(
            source.get("raw_qc_baseline_excluded", source.get("raw_baseline_excluded"))
        ),
    }


def _interpolation_payload(source: Mapping[str, Any] | None) -> dict[str, object]:
    source = source or {}
    return {
        "interpolation_status": str(source.get("interpolation_status") or ""),
        "interpolation_requested_channels": _string_list(
            source.get("interpolation_requested_channels")
        ),
        "interpolation_error": str(source.get("interpolation_error") or ""),
        **({"condition_electrode_interpolation": dict(source["condition_electrode_interpolation"])}
           if isinstance(source.get("condition_electrode_interpolation"), Mapping) else {}),
    }


def _kurtosis_qc_payload(source: Mapping[str, Any] | None) -> dict[str, object]:
    """Preserve QC-16 evidence and authority separately from repair outcomes."""

    source = source or {}
    raw_evidence = source.get("kurtosis_qc_evidence")
    raw_decision_plan = source.get("kurtosis_decision_plan")
    candidates = _string_list(
        source.get("kurtosis_candidate_channels")
        or source.get("kurtosis_bad_channels")
    )
    return {
        "kurtosis_qc_evidence": (
            dict(raw_evidence) if isinstance(raw_evidence, Mapping) else {}
        ),
        "kurtosis_decision_plan": (
            dict(raw_decision_plan)
            if isinstance(raw_decision_plan, Mapping)
            else {}
        ),
        "kurtosis_candidate_channels": candidates,
        "kurtosis_review_required_channels": _string_list(
            source.get("kurtosis_review_required_channels")
        ),
        "kurtosis_corroborated_channels": _string_list(
            source.get("kurtosis_corroborated_channels")
        ),
        "kurtosis_user_approved_channels": _string_list(
            source.get("kurtosis_user_approved_channels")
        ),
        "kurtosis_user_rejected_channels": _string_list(
            source.get("kurtosis_user_rejected_channels")
        ),
    }


def _has_observed_geometry(source: Mapping[str, Any] | None) -> bool:
    if not isinstance(source, Mapping):
        return False
    if isinstance(source.get("geometry"), Mapping):
        return True
    audit = source.get("audit")
    return isinstance(audit, Mapping) and isinstance(audit.get("geometry"), Mapping)


def _preprocessing_evidence_payload(
    *,
    processing_status: str,
    processing_reason: str,
    missing_conditions: Sequence[object] = (),
    interpolation_source: Mapping[str, Any] | None,
    geometry_identity: Mapping[str, Any],
    geometry_was_observed: bool,
    excluded_before_preprocessing: bool = False,
) -> dict[str, object]:
    """Build versioned outcomes without inferring repair success from flags."""

    source = interpolation_source or {}
    raw_status = str(source.get("interpolation_status") or "").strip().casefold()
    requested = _string_list(source.get("interpolation_requested_channels"))
    successful = _string_list(source.get("interpolated_channels"))
    detail = str(
        source.get("interpolation_detail")
        or source.get("interpolation_error")
        or ""
    ).strip()

    if excluded_before_preprocessing and not raw_status:
        raw_status = INTERPOLATION_STATUS_SKIPPED
        requested = []
        successful = []
        detail = "Recording was excluded before interpolation."
    elif raw_status not in INTERPOLATION_STATUSES:
        raw_status = INTERPOLATION_STATUS_LEGACY_UNKNOWN
        requested = []
        successful = []
        detail = ""
    elif raw_status != "succeeded":
        # A target or detector flag is not evidence of a successful repair.
        successful = []

    try:
        outcome = build_preprocessing_outcome(
            processing_status=processing_status,
            processing_reason=processing_reason,
            missing_conditions=missing_conditions,
            interpolation_status=raw_status,
            interpolation_requested_channels=requested,
            interpolation_successful_channels=successful,
            interpolation_detail=detail,
        )
    except PreprocessingOutcomeError as exc:
        logger.warning(
            "preprocessing_outcome_provenance_invalid",
            extra={
                "processing_status": processing_status,
                "interpolation_status": raw_status,
                "error": str(exc),
            },
        )
        outcome = build_preprocessing_outcome(
            processing_status=processing_status,
            processing_reason=processing_reason,
            missing_conditions=missing_conditions,
            interpolation_status=INTERPOLATION_STATUS_LEGACY_UNKNOWN,
        )

    burden = build_interpolation_burden(
        outcome,
        geometry_identity if geometry_was_observed else None,
    )
    return {
        "preprocessing_outcome": outcome.to_payload(),
        "interpolation_burden": burden.to_payload(),
        **_kurtosis_qc_payload(source),
    }


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _resolved_path_strings(values: Sequence[Any]) -> set[str]:
    resolved: set[str] = set()
    for value in values:
        try:
            resolved.add(str(Path(str(value)).resolve()))
        except (OSError, TypeError, ValueError):
            continue
    return resolved


def _source_derivative_result_payload(result: Mapping[str, Any] | None) -> dict[str, object]:
    source = result or {}
    return {
        "source_derivative_status": str(source.get("source_derivative_status") or "").strip(),
        "source_derivative_manifest": str(source.get("source_derivative_manifest") or "").strip(),
        "source_derivative_outputs": _string_list(source.get("source_derivative_outputs")),
        "source_derivative_warning": str(source.get("source_derivative_warning") or "").strip(),
    }


def _source_derivative_root(project_root: Path) -> Path:
    root = Path(project_root).resolve()
    source_root = (root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT).resolve()
    if source_root == root or root not in source_root.parents:
        raise ValueError(
            "Refusing source-ready derivative access outside the project root: "
            f"{source_root}"
        )
    return source_root


def _resolve_source_derivative_path(project_root: Path, value: Any) -> Path:
    root = Path(project_root).resolve()
    source_root = _source_derivative_root(root)
    supplied = Path(str(value))
    target = (root / supplied).resolve() if not supplied.is_absolute() else supplied.resolve()
    if target == source_root or source_root not in target.parents:
        raise ValueError(
            "Refusing to touch source derivative path outside "
            f"{SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT}: {target}"
        )
    return target


def _recorded_source_derivative_paths(
    project_root: Path,
    entry: Mapping[str, Any] | None,
) -> tuple[Path, ...]:
    if not isinstance(entry, Mapping):
        return ()
    recorded = _string_list(entry.get("source_derivative_outputs"))
    manifest = str(entry.get("source_derivative_manifest") or "").strip()
    if manifest:
        recorded.append(manifest)
    paths: list[Path] = []
    seen: set[Path] = set()
    for value in recorded:
        target = _resolve_source_derivative_path(project_root, value)
        if target in seen:
            continue
        seen.add(target)
        paths.append(target)
    return tuple(paths)


def _source_derivative_reuse_problem(
    project_root: Path,
    entry: Mapping[str, Any],
) -> str | None:
    status = str(entry.get("source_derivative_status") or "").strip().casefold()
    if not status:
        # Compatibility for focused callers that predate the runner result fields.
        # Real entries from the v9 runner always carry an explicit status.
        return None
    if status != "complete":
        return f"Source-ready time-domain derivative status is {status!r}, not complete."

    manifest_value = str(entry.get("source_derivative_manifest") or "").strip()
    output_values = _string_list(entry.get("source_derivative_outputs"))
    if not manifest_value:
        return "Source-ready time-domain derivative manifest was not recorded."
    if not output_values:
        return "Source-ready time-domain derivative outputs were not recorded."
    try:
        manifest_path = _resolve_source_derivative_path(project_root, manifest_value)
        output_paths = tuple(
            _resolve_source_derivative_path(project_root, value) for value in output_values
        )
    except ValueError as exc:
        return str(exc)
    if not manifest_path.is_file():
        return f"Source-ready time-domain derivative manifest is missing: {manifest_path}"
    artifact_paths = {path for path in output_paths if path != manifest_path}
    if not artifact_paths:
        return "Source-ready time-domain derivative artifact outputs were not recorded."
    missing = [path for path in output_paths if not path.is_file()]
    if missing:
        return f"Source-ready time-domain derivative output is missing: {missing[0]}"
    return None


def _condition_companion_reuse_problem(
    entry: Mapping[str, Any], expected_outputs: Sequence[Path],
) -> str | None:
    """Require recorded arrays, resolving beside the current condition workbooks."""
    from Main_App.io.condition_data import condition_companion_identity
    from Main_App.io.spectral_data import spectral_companion_identity

    companion_readers = (
        ("spectral_companion", "Spectral", spectral_companion_identity),
        ("condition_companion", "Condition metrics", condition_companion_identity),
    )
    outputs = {path.name: path for path in expected_outputs}
    for receipt in _export_receipts_payload(entry):
        write = receipt.get("workbook_write")
        if not isinstance(write, Mapping) or not any(
            key in write for key, _label, _reader in companion_readers
        ):
            continue  # Legacy Excel-only completion receipts remain reusable.
        artifact = write.get("artifact")
        if not isinstance(artifact, Mapping):
            return "Condition companion workbook identity was not recorded."
        # Stored absolute paths may precede a project move, including another OS.
        name = str(artifact.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        workbook = outputs.get(name)
        if workbook is None:
            return "Condition companion does not match an expected condition workbook."
        for key, label, reader in companion_readers:
            if key not in write:
                continue
            try:
                if not isinstance(write[key], Mapping) or reader(workbook) != write[key]:
                    return f"{label} companion is missing or changed: {workbook.name}"
            except (OSError, ValueError):
                return f"{label} companion is missing, corrupt, or changed: {workbook.name}"
    return None


def _has_missing_condition_warning(entry: Mapping[str, Any]) -> bool:
    return (
        str(entry.get("completion_warning") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
        or str(entry.get("failure_reason") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
        or str(entry.get("condition_completeness") or "").casefold() == "partial"
    )


def _missing_outputs_are_recorded_condition_warning(
    entry: Mapping[str, Any],
    missing_outputs: Sequence[Any],
) -> bool:
    if not _has_missing_condition_warning(entry):
        return False
    current_missing = _resolved_path_strings(missing_outputs)
    recorded_missing = _resolved_path_strings(_string_list(entry.get("missing_outputs")))
    return not recorded_missing or current_missing.issubset(recorded_missing)


def _excel_root(project: Any) -> Path:
    project_root = Path(project.project_root)
    subfolders = getattr(project, "subfolders", {}) or {}
    excel_subfolder = subfolders.get("excel") if isinstance(subfolders, Mapping) else None
    if excel_subfolder:
        root = Path(excel_subfolder)
        return root if root.is_absolute() else project_root / root
    return project_root / "1 - Excel Data Files"


def _project_subfolder(project: Any, key: str, default_name: str) -> Path:
    project_root = Path(project.project_root)
    subfolders = getattr(project, "subfolders", {}) or {}
    configured = subfolders.get(key) if isinstance(subfolders, Mapping) else None
    path = Path(configured) if configured else project_root / default_name
    return path if path.is_absolute() else project_root / path


def _condition_folder_name(label: str) -> str:
    return re.sub(
        r"^\d+\s*-\s*",
        "",
        str(label).replace("/", "-").replace("\\", "-").strip(),
    )


def _group_folder_name(project: Any, group_id: str | None) -> str | None:
    context = project_group_context(project)
    if not group_id:
        if context.has_group_metadata:
            raise ValueError(
                "Grouped processing input is missing its canonical group_id."
            )
        return None
    return context.group(group_id).folder_name


def _expected_excel_paths(
    project: Any,
    info: RawFileInfo,
    condition_labels: Sequence[str],
) -> tuple[Path, ...]:
    root = _excel_root(project)
    group_folder = _group_folder_name(project, info.group)
    paths: list[Path] = []
    for label in condition_labels:
        condition_folder = _condition_folder_name(label)
        file_name = f"{info.output_stem}_{condition_folder}_Results.xlsx"
        output_folder = resolve_output_directory(root, condition_folder)
        if group_folder:
            output_folder = resolve_group_output_directory(output_folder, group_folder)
        paths.append(resolve_result_path(output_folder / file_name).resolve())
    return tuple(paths)


def _condition_labels_for_missing_outputs(
    plan: ProcessingPlan,
    state: ProcessingInputState,
    missing_outputs: Sequence[Any],
) -> list[str]:
    missing = _resolved_path_strings(missing_outputs)
    labels: list[str] = []
    for index, output_path in enumerate(state.expected_outputs):
        if str(output_path.resolve()) not in missing:
            continue
        if index < len(plan.condition_labels):
            labels.append(str(plan.condition_labels[index]))
        else:
            labels.append(output_path.parent.name)
    return labels


def raw_file_metadata(file_path: Path) -> dict[str, Any]:
    stat = Path(file_path).stat()
    return {
        "raw_file": str(Path(file_path).resolve()),
        "raw_size": int(stat.st_size),
        "raw_mtime_ns": int(stat.st_mtime_ns),
    }


def _recording_identity_payload(info: RawFileInfo) -> dict[str, Any]:
    """Return legacy-compatible participant identity plus optional visit data."""

    payload: dict[str, Any] = {"participant_id": info.subject_id}
    if info.recording_id:
        payload["recording_id"] = info.recording_id
    if info.session_id:
        payload["session_id"] = info.session_id
    if info.session_label:
        payload["session_label"] = info.session_label
    if info.visit_index is not None:
        payload["visit_index"] = int(info.visit_index)
    if info.source_id:
        payload["source_id"] = info.source_id
    if info.days_from_baseline is not None:
        payload["days_from_baseline"] = float(info.days_from_baseline)
    return payload


def _configured_geometry_identity(settings: Mapping[str, Any]) -> dict[str, object]:
    """Return the geometry expected from the current project processing inputs."""

    raw_limit = settings.get("max_idx_keep")
    if raw_limit is None:
        raw_limit = settings.get("max_chan_idx_keep")
    if raw_limit is None:
        channel_limit = len(BIOSEMI64_CHANNELS)
    elif isinstance(raw_limit, bool):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    else:
        try:
            channel_limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "BioSemi64 channel limit must be an integer from 1 through 64."
            ) from exc
        if isinstance(raw_limit, float) and not raw_limit.is_integer():
            raise ValueError(
                "BioSemi64 channel limit must be an integer from 1 through 64."
            )
    if not 1 <= channel_limit <= len(BIOSEMI64_CHANNELS):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    retained_channels = BIOSEMI64_CHANNELS[:channel_limit]
    return biosemi64_geometry_identity(
        electrode_mapping_profile=settings.get("electrode_mapping_profile"),
        retained_channels=retained_channels,
    )


def _result_geometry_identity(
    result: Mapping[str, Any] | None,
    fallback: Mapping[str, object],
    *,
    require_observed: bool = False,
) -> dict[str, object]:
    """Validate worker-observed geometry while preserving error records."""

    candidate = (result or {}).get("geometry")
    audit = (result or {}).get("audit")
    audit_candidate = audit.get("geometry") if isinstance(audit, Mapping) else None
    if candidate is None and isinstance(audit_candidate, Mapping):
        candidate = audit_candidate
    if not isinstance(candidate, Mapping):
        if require_observed:
            raise ValueError(
                "Successful processing result has no worker-observed BioSemi64 "
                "geometry identity."
            )
        return dict(fallback)
    retained = candidate.get("retained_scalp_channels")
    retained_channels = (
        [str(value) for value in retained]
        if isinstance(retained, Sequence) and not isinstance(retained, (str, bytes))
        else None
    )
    normalized = biosemi64_geometry_identity(
        electrode_mapping_profile=candidate.get("electrode_mapping_profile"),
        retained_channels=retained_channels,
    )
    if dict(candidate) != normalized:
        raise ValueError(
            "Processing worker returned a geometry identity that does not match "
            "the canonical BioSemi64 definition."
        )
    if isinstance(audit_candidate, Mapping) and dict(audit_candidate) != normalized:
        raise ValueError(
            "Processing worker result and audit disagree about the BioSemi64 "
            "geometry identity."
        )
    return normalized


def _ledger_geometry_matches(
    entry: Mapping[str, Any],
    expected: Mapping[str, object],
) -> bool:
    candidate = entry.get("geometry")
    return isinstance(candidate, Mapping) and dict(candidate) == dict(expected)


def _canonical_frequency_protocol_identity(
    project: Any,
    settings: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve one canonical project protocol without hashing object reprs."""

    candidates: list[tuple[str, FrequencyProtocol]] = []
    for source, raw_value in (
        ("processing settings", settings.get("frequency_protocol")),
        ("project", getattr(project, "frequency_protocol", None)),
    ):
        if raw_value is None:
            continue
        try:
            candidates.append((source, normalize_frequency_protocol(raw_value)))
        except FrequencyProtocolError as exc:
            raise ValueError(f"Invalid {source} frequency protocol: {exc}") from exc
    if not candidates:
        return None
    selected_source, selected = candidates[0]
    for source, candidate in candidates[1:]:
        if candidate.fingerprint != selected.fingerprint:
            raise ValueError(
                "Processing settings and project frequency protocols disagree: "
                f"{selected_source}={selected.fingerprint}, "
                f"{source}={candidate.fingerprint}."
            )
    return {
        "canonical_payload": selected.canonical_payload(),
        "fingerprint": selected.fingerprint,
    }


def build_processing_fingerprint(
    project: Any,
    settings: Mapping[str, Any],
    event_map: Mapping[str, int],
) -> str:
    project_preprocessing = getattr(project, "preprocessing", {}) or {}
    repeated_session_project = bool(
        getattr(project, "sessions", {})
        or getattr(project, "recording_sources", {})
        or getattr(project, "recordings", {})
    )
    fingerprint_settings = {
        key: value
        for key, value in settings.items()
        if key not in _DOWNSTREAM_ONLY_PREPROCESSING_KEYS
        and key != "frequency_protocol"
        # Repairs are governed by per-recording cache and condition receipts;
        # their addition must not obsolete unrelated recordings.
        and key not in {"condition_electrode_interpolation_requests", "_fpvs_condition_interpolation_requests", "_fpvs_condition_interpolation_provenance", "_fpvs_export_only_conditions", "_fpvs_condition_interpolation_run_snapshot"}
        and (
            repeated_session_project
            or key not in _REPEATED_SESSION_PREPROCESSING_KEYS
        )
    }
    compatibility = getattr(
        project,
        "processing_fingerprint_v9_compatibility",
        {},
    )
    compatibility_source = compatibility if isinstance(compatibility, Mapping) else {}
    replay_values: dict[str, float] = {}
    for runtime_key, canonical_key in (
        ("epoch_start", "epoch_start_s"),
        ("epoch_end", "epoch_end_s"),
    ):
        raw_value = compatibility_source.get(canonical_key)
        if raw_value in (None, ""):
            raw_value = project_preprocessing.get(canonical_key)
        if raw_value in (None, ""):
            raw_value = project_preprocessing.get(runtime_key)
        if raw_value in (None, ""):
            raw_value = _FINGERPRINT_V9_EPOCH_DEFAULTS[canonical_key]
        replay_values[canonical_key] = float(raw_value)
        if runtime_key in fingerprint_settings:
            continue
        fingerprint_settings[runtime_key] = replay_values[canonical_key]
    fingerprint_project_preprocessing = {
        key: value
        for key, value in project_preprocessing.items()
        if key not in _DOWNSTREAM_ONLY_PREPROCESSING_KEYS
        and (
            repeated_session_project
            or key not in _REPEATED_SESSION_PREPROCESSING_KEYS
        )
    }
    # Reconstruct only the retired fields in the temporary hash payload. Active
    # project preprocessing remains clean while existing v9 ledger/sidecar
    # identities retain their exact historical shape.
    fingerprint_project_preprocessing.update(
        {
            "epoch_start_s": replay_values["epoch_start_s"],
            "epoch_start": replay_values["epoch_start_s"],
            "epoch_end_s": replay_values["epoch_end_s"],
            "epoch_end": replay_values["epoch_end_s"],
        }
    )
    geometry_identity = _configured_geometry_identity(settings)
    frequency_protocol_identity = _canonical_frequency_protocol_identity(
        project,
        settings,
    )
    payload = {
        "version": PROCESSING_FINGERPRINT_VERSION,
        "geometry": geometry_identity,
        "frequency_protocol": frequency_protocol_identity,
        "settings": fingerprint_settings,
        "fft_multinotch": {
            "enabled": settings.get("line_noise_filter_enabled", True),
            "mains_frequency_hz": settings.get("line_noise_frequency_hz", 60),
            "method_version": FFT_MULTINOTCH_METHOD_VERSION,
            "half_width_hz": FFT_MULTINOTCH_HALF_WIDTH_HZ,
            "component_count": FFT_MULTINOTCH_COMPONENT_COUNT,
        },
        "event_map": {str(key): int(value) for key, value in event_map.items()},
        "project_preprocessing": fingerprint_project_preprocessing,
        "project_options": getattr(project, "options", {}) or {},
        "project_subfolders": getattr(project, "subfolders", {}) or {},
        "project_groups": getattr(project, "groups", {}) or {},
    }
    if repeated_session_project:
        payload["project_recording_design"] = {
            "sessions": getattr(project, "sessions", {}) or {},
            "recording_sources": getattr(project, "recording_sources", {}) or {},
            "recordings": getattr(project, "recordings", {}) or {},
        }
    encoded = _canonical_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_ledger(project_root: Path) -> dict[str, Any]:
    path = ledger_path(project_root)
    if not path.exists():
        return {"schema_version": 1, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("processing_ledger_unreadable", extra={"path": str(path)})
        return {"schema_version": 1, "entries": {}}
    if not isinstance(data, dict):
        return {"schema_version": 1, "entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        data["entries"] = {}
    data.setdefault("schema_version", 1)
    return data


def save_ledger(project_root: Path, ledger: Mapping[str, Any]) -> None:
    state_dir = processing_state_dir(project_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_path(project_root)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(ledger, indent=2, default=str), encoding="utf-8")
    _replace_ledger_with_retry(tmp_path, path)


def _replace_ledger_with_retry(temporary_path: Path, ledger_path: Path) -> None:
    """Tolerate brief Windows scanner/indexer locks around the ledger."""

    delays_s = (0.0, 0.01, 0.02, 0.05, 0.1, 0.1)
    for attempt, delay_s in enumerate(delays_s, start=1):
        if delay_s:
            time.sleep(delay_s)
        try:
            os.replace(temporary_path, ledger_path)
            return
        except PermissionError:
            if attempt == len(delays_s):
                raise


def append_run_log(project_root: Path, record: Mapping[str, Any]) -> None:
    state_dir = processing_state_dir(project_root)
    state_dir.mkdir(parents=True, exist_ok=True)
    payload = dict(record)
    payload.setdefault("timestamp", _now_iso())
    with runs_path(project_root).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def classify_processing_inputs(
    project: Any,
    files: Sequence[RawFileInfo],
    settings: Mapping[str, Any],
    event_map: Mapping[str, int],
) -> ProcessingPlan:
    condition_labels = tuple(str(label) for label in event_map.keys())
    fingerprint = build_processing_fingerprint(project, settings, event_map)
    geometry_identity = _configured_geometry_identity(settings)
    ledger = load_ledger(Path(project.project_root))
    entries = ledger.get("entries", {})
    if not isinstance(entries, Mapping):
        entries = {}

    states: list[ProcessingInputState] = []
    for info in files:
        participant_id = info.subject_id
        processing_id = info.processing_id
        expected_outputs = _expected_excel_paths(project, info, condition_labels)
        entry = entries.get(processing_id)
        raw_meta = raw_file_metadata(info.path)
        if not isinstance(entry, Mapping):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="new",
                    reason="No completed ledger entry exists.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        entry_status = str(entry.get("status") or "incomplete")
        if entry_status == "excluded":
            if (
                entry.get("raw_file") != raw_meta["raw_file"]
                or entry.get("raw_size") != raw_meta["raw_size"]
                or entry.get("raw_mtime_ns") != raw_meta["raw_mtime_ns"]
            ):
                states.append(
                    ProcessingInputState(
                        info=info,
                        participant_id=participant_id,
                        status="changed_raw",
                        reason="Previously excluded raw file changed.",
                        expected_outputs=expected_outputs,
                    )
                )
                continue

            exclusion_reason = str(entry.get("exclusion_reason") or "").strip().casefold()
            geometry_independent = (
                exclusion_reason in _GEOMETRY_INDEPENDENT_EXCLUSION_REASONS
            )
            if not geometry_independent:
                if (
                    entry.get("processing_fingerprint_version")
                    != PROCESSING_FINGERPRINT_VERSION
                ):
                    states.append(
                        ProcessingInputState(
                            info=info,
                            participant_id=participant_id,
                            status="changed_settings",
                            reason=(
                                "The prior automatic QC exclusion predates the current "
                                "processing and geometry contract."
                            ),
                            expected_outputs=expected_outputs,
                        )
                    )
                    continue
                if entry.get("processing_fingerprint") != fingerprint:
                    states.append(
                        ProcessingInputState(
                            info=info,
                            participant_id=participant_id,
                            status="changed_settings",
                            reason=(
                                "Project processing settings changed after the prior "
                                "automatic QC exclusion."
                            ),
                            expected_outputs=expected_outputs,
                        )
                    )
                    continue
                if not _ledger_geometry_matches(entry, geometry_identity):
                    states.append(
                        ProcessingInputState(
                            info=info,
                            participant_id=participant_id,
                            status="changed_settings",
                            reason=(
                                "The prior automatic QC exclusion has missing or stale "
                                "electrode geometry."
                            ),
                            expected_outputs=expected_outputs,
                        )
                    )
                    continue

            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="excluded",
                    reason=str(
                        entry.get("exclusion_message")
                        or entry.get("exclusion_reason")
                        or "Raw file was excluded from processing."
                    ),
                    expected_outputs=expected_outputs,
                )
            )
            continue

        present_outputs_now = [path for path in expected_outputs if path.exists()]
        missing_outputs_now = [path for path in expected_outputs if not path.exists()]
        legacy_partial_condition_entry = (
            entry_status == "failed"
            and bool(present_outputs_now)
            and bool(missing_outputs_now)
        )
        if (
            entry_status != "completed"
            and not _has_missing_condition_warning(entry)
            and not legacy_partial_condition_entry
        ):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="missing_outputs",
                    reason=f"Ledger entry is {entry_status}, not completed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if entry.get("processing_fingerprint_version") != PROCESSING_FINGERPRINT_VERSION:
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_settings",
                    reason="Processing fingerprint version changed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if entry.get("processing_fingerprint") != fingerprint:
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_settings",
                    reason="Project processing settings changed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if not _ledger_geometry_matches(entry, geometry_identity):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_settings",
                    reason="Electrode geometry identity changed or is missing.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        if (
            entry.get("raw_file") != raw_meta["raw_file"]
            or entry.get("raw_size") != raw_meta["raw_size"]
            or entry.get("raw_mtime_ns") != raw_meta["raw_mtime_ns"]
        ):
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="changed_raw",
                    reason="Raw file path, size, or mtime changed.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        source_derivative_problem = _source_derivative_reuse_problem(
            Path(project.project_root),
            entry,
        ) or _condition_companion_reuse_problem(entry, expected_outputs)
        if source_derivative_problem:
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="missing_outputs",
                    reason=source_derivative_problem,
                    expected_outputs=expected_outputs,
                )
            )
            continue

        missing_outputs = missing_outputs_now
        if missing_outputs:
            if (
                _missing_outputs_are_recorded_condition_warning(entry, missing_outputs)
                or legacy_partial_condition_entry
            ):
                states.append(
                    ProcessingInputState(
                        info=info,
                        participant_id=participant_id,
                        status="completed",
                        reason=(
                            "Available condition outputs are completed; missing "
                            "condition outputs are flagged in QC."
                        ),
                        expected_outputs=expected_outputs,
                    )
                )
                continue
            states.append(
                ProcessingInputState(
                    info=info,
                    participant_id=participant_id,
                    status="missing_outputs",
                    reason="Expected Excel output files are missing.",
                    expected_outputs=expected_outputs,
                )
            )
            continue

        states.append(
            ProcessingInputState(
                info=info,
                participant_id=participant_id,
                status="completed",
                reason="Ledger and expected Excel outputs match.",
                expected_outputs=expected_outputs,
            )
        )
    return ProcessingPlan(
        states=tuple(states),
        fingerprint=fingerprint,
        condition_labels=condition_labels,
        geometry_identity=geometry_identity,
    )


def with_processing_choice(plan: ProcessingPlan, choice: str) -> ProcessingPlan:
    # Reused historical recordings retain their XLSX identities. Once selected
    # for processing, freeze the native output route before the expected-cell
    # plan records it, including reprocessing an existing legacy recording.
    states = tuple(
        replace(
            state,
            expected_outputs=tuple(result_manifest_path(path) for path in state.expected_outputs),
        )
        if choice in {"reprocess_all", "reprocess_this_file"} or state.should_run_incremental
        else state
        for state in plan.states
    )
    return ProcessingPlan(
        states=states,
        fingerprint=plan.fingerprint,
        condition_labels=plan.condition_labels,
        choice=choice,
        geometry_identity=plan.geometry_identity,
    )


def _state_still_matches_ledger(
    project: Any,
    state: ProcessingInputState,
) -> bool:
    ledger = load_ledger(Path(project.project_root))
    entries = ledger.get("entries", {})
    if not isinstance(entries, Mapping):
        return False
    entry = entries.get(state.processing_id)
    if not isinstance(entry, Mapping):
        return False

    raw_meta = raw_file_metadata(state.info.path)
    if (
        entry.get("raw_file") != raw_meta["raw_file"]
        or entry.get("raw_size") != raw_meta["raw_size"]
        or entry.get("raw_mtime_ns") != raw_meta["raw_mtime_ns"]
    ):
        return False

    if state.status == "excluded":
        return str(entry.get("status") or "") == "excluded"

    if _source_derivative_reuse_problem(Path(project.project_root), entry):
        return False
    if _condition_companion_reuse_problem(entry, state.expected_outputs):
        return False

    present_outputs = [path for path in state.expected_outputs if path.exists()]
    missing_outputs = [path for path in state.expected_outputs if not path.exists()]
    if not missing_outputs:
        return bool(present_outputs)
    return _missing_outputs_are_recorded_condition_warning(entry, missing_outputs)


def carry_forward_pre_qc_completed_states(
    project: Any,
    pre_qc_plan: ProcessingPlan | None,
    current_plan: ProcessingPlan,
) -> ProcessingPlan:
    """Keep completed pre-QC states when QC metadata updates only new files.

    Preflight QC can add participant-specific manual removed-electrode or
    exclusion metadata before the final processing plan is built. Those project
    metadata additions should not force previously completed files back into an
    incremental run when their pre-QC ledger state was already reusable.
    """

    if pre_qc_plan is None:
        return current_plan

    pre_by_path: dict[Path, ProcessingInputState] = {}
    for state in pre_qc_plan.states:
        try:
            pre_by_path[state.info.path.resolve()] = state
        except (OSError, RuntimeError):
            pre_by_path[state.info.path] = state

    states: list[ProcessingInputState] = []
    changed = False
    for current in current_plan.states:
        try:
            key = current.info.path.resolve()
        except (OSError, RuntimeError):
            key = current.info.path
        pre_qc = pre_by_path.get(key)
        if (
            pre_qc is not None
            and pre_qc.status in {"completed", "excluded"}
            and current.status == "changed_settings"
            and pre_qc.participant_id == current.participant_id
            and _state_still_matches_ledger(project, current)
        ):
            states.append(
                ProcessingInputState(
                    info=current.info,
                    participant_id=current.participant_id,
                    status=pre_qc.status,
                    reason=pre_qc.reason,
                    expected_outputs=current.expected_outputs,
                )
            )
            changed = True
            continue
        states.append(current)

    if not changed:
        return current_plan
    return ProcessingPlan(
        states=tuple(states),
        fingerprint=current_plan.fingerprint,
        condition_labels=current_plan.condition_labels,
        choice=current_plan.choice,
        geometry_identity=current_plan.geometry_identity,
    )


def refresh_skipped_ledger_fingerprints(project: Any, plan: ProcessingPlan) -> int:
    """Refresh fingerprint metadata for skipped reusable files.

    This keeps durable incremental behavior after preflight QC adds metadata for
    new participants. The stored QC fields and output paths are left unchanged.
    """

    project_root = Path(project.project_root)
    ledger = load_ledger(project_root)
    entries = ledger.get("entries", {})
    if not isinstance(entries, dict):
        return 0

    run_files: set[Path] = set()
    for path in plan.run_files:
        try:
            run_files.add(path.resolve())
        except (OSError, RuntimeError):
            run_files.add(path)

    changed = 0
    for state in plan.states:
        if state.status not in {"completed", "excluded"}:
            continue
        try:
            state_path = state.info.path.resolve()
        except (OSError, RuntimeError):
            state_path = state.info.path
        if state_path in run_files:
            continue
        entry = entries.get(state.processing_id)
        if not isinstance(entry, dict):
            continue
        updates = {
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
            "expected_outputs": [str(path) for path in state.expected_outputs],
        }
        if any(entry.get(key) != value for key, value in updates.items()):
            entry.update(updates)
            changed += 1

    if changed:
        save_ledger(project_root, ledger)
    return changed


def output_group_folder_by_file(
    project: Any,
    files: Sequence[RawFileInfo],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for info in files:
        group_folder = _group_folder_name(project, info.group)
        if group_folder:
            mapping[str(info.path.resolve())] = group_folder
    return mapping


def _assert_under_excel_root(excel_root: Path, path: Path) -> Path:
    root = excel_root.resolve()
    target = path.resolve()
    if target == root or root in target.parents:
        return target
    raise ValueError(f"Refusing to delete unmanaged Excel output path: {target}")


def _assert_under_project_root(project_root: Path, path: Path, label: str) -> Path:
    root = project_root.resolve()
    target = path.resolve()
    if target == root or root in target.parents:
        return target
    raise ValueError(f"Refusing to delete unmanaged {label} output path: {target}")


def _delete_recorded_source_derivative_targets(
    project_root: Path,
    targets: Sequence[Path],
) -> list[Path]:
    source_root = _source_derivative_root(project_root)
    deleted: list[Path] = []
    touched_parents: set[Path] = set()
    for target in targets:
        validated = _resolve_source_derivative_path(project_root, target)
        if not validated.exists():
            continue
        if not validated.is_file():
            raise ValueError(f"Refusing to delete non-file source derivative artifact: {validated}")
        deleted.append(_delete_generated_file(validated, "source derivative"))
        touched_parents.add(validated.parent)
    for parent in sorted(touched_parents, key=lambda path: len(path.parts), reverse=True):
        _prune_empty_source_derivative_parents(source_root, parent)
    return deleted


def _prune_empty_source_derivative_parents(source_root: Path, start: Path) -> None:
    current = start
    while current != source_root and source_root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent
    try:
        source_root.rmdir()
    except OSError:
        pass


def _remove_empty_source_derivative_tree(project_root: Path) -> None:
    source_root = _source_derivative_root(project_root)
    if not source_root.exists():
        return
    directories = sorted(
        (path for path in source_root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            continue
    try:
        source_root.rmdir()
    except OSError:
        pass


def _is_managed_spectral_companion(path: Path) -> bool:
    return re.fullmatch(r".+\.spectra\.[0-9a-f]{20}\.npz", path.name) is not None


def _declared_condition_companions(root: Path, workbook: Path) -> tuple[Path, ...]:
    """Select declared metric artifacts without requiring their data to be intact."""
    from Main_App.io.condition_data import declared_condition_companion

    if not workbook.is_file():
        return ()
    try:
        descriptor = declared_condition_companion(workbook)
    except (OSError, ValueError):
        # Historical/non-XLSX files and invalid declarations cannot authorize
        # deleting any sibling. Unreferenced arrays are not guessed or reused.
        return ()
    if descriptor is None:
        return ()
    name = descriptor["path"]
    if name != f"{workbook.stem}.metrics.{descriptor['sha256'][:20]}.npz":
        raise ValueError(f"Refusing to delete an unexpected condition companion: {name}")
    target = _assert_under_excel_root(root, workbook.with_name(name))
    if target.parent != workbook.parent.resolve():
        raise ValueError(f"Condition companion resolves outside its workbook folder: {name}")
    return (target,) if target.is_file() else ()


def _workbook_companions(root: Path, workbook: Path) -> tuple[Path, ...]:
    """Find managed spectra and this workbook's explicitly declared metrics."""
    if not workbook.parent.is_dir():
        return ()
    prefix = f"{workbook.stem}.spectra."
    spectral = tuple(
        _assert_under_excel_root(root, path)
        for path in workbook.parent.iterdir()
        if path.is_file() and path.name.startswith(prefix)
        and _is_managed_spectral_companion(path)
    )
    return spectral + _declared_condition_companions(root, workbook)


def clean_managed_excel_root(project: Any) -> Path:
    root = _excel_root(project).resolve()
    project_root = Path(project.project_root).resolve()
    if root == project_root or root.parent == root:
        raise ValueError(f"Refusing to delete unsafe Excel output root: {root}")
    if root.exists():
        try:
            candidates = [
                path
                for path in root.rglob("*")
                if path.is_file() and (
                    path.suffix.lower() in GENERATED_EXCEL_SUFFIXES
                    or _is_managed_spectral_companion(path)
                )
            ]
            declared_metrics = [
                companion
                for path in candidates
                if path.suffix.lower() in GENERATED_EXCEL_SUFFIXES
                for companion in _declared_condition_companions(root, path)
            ]
            candidates = list(dict.fromkeys([*candidates, *declared_metrics]))
        except OSError as exc:
            raise RuntimeError(
                "Unable to scan the managed Excel output folder for cleanup. "
                f"Check OneDrive sync/permissions for: {root}. Original error: {exc}"
            ) from exc
        for path in candidates:
            path = _assert_under_excel_root(root, path)
            try:
                path.unlink()
            except PermissionError as exc:
                raise RuntimeError(
                    "Unable to remove an existing Excel output file. Close it in Excel "
                    f"and pause OneDrive sync if needed, then retry: {path}"
                ) from exc
            except OSError as exc:
                raise RuntimeError(
                    f"Unable to remove existing Excel output file: {path}. "
                    f"Original error: {exc}"
                ) from exc
    root.mkdir(parents=True, exist_ok=True)
    return root


def _delete_generated_file(path: Path, label: str) -> Path:
    try:
        path.unlink()
    except PermissionError as exc:
        raise RuntimeError(
            "Unable to remove an existing generated output file. Close it in Excel "
            f"or the program currently using it, then retry: {path}"
        ) from exc
    except OSError as exc:
        raise RuntimeError(
            f"Unable to remove existing {label} output file: {path}. "
            f"Original error: {exc}"
        ) from exc
    return path


def clean_downstream_outputs_for_reprocess_all(project: Any) -> list[Path]:
    """Remove derived outputs that become stale when every BDF is reprocessed."""

    project_root = Path(project.project_root).resolve()
    deleted: list[Path] = []
    seen_folders: set[Path] = set()
    for key, default_name in REPROCESS_ALL_DOWNSTREAM_FOLDER_DEFAULTS.items():
        folder = _assert_under_project_root(
            project_root,
            _project_subfolder(project, key, default_name),
            key,
        )
        if folder == project_root or folder in seen_folders or not folder.exists():
            continue
        seen_folders.add(folder)
        try:
            files = [path for path in folder.rglob("*") if path.is_file()]
        except OSError as exc:
            raise RuntimeError(
                "Unable to scan a managed downstream output folder for cleanup. "
                f"Check OneDrive sync/permissions for: {folder}. Original error: {exc}"
            ) from exc
        for path in files:
            deleted.append(_delete_generated_file(path, key))

    _remove_empty_source_derivative_tree(project_root)

    quality_root = _assert_under_project_root(
        project_root,
        project_root / "Quality Check",
        "quality check",
    )
    if not quality_root.exists():
        return deleted
    for pattern in REPROCESS_ALL_QUALITY_CHECK_DELETE_PATTERNS:
        for path in quality_root.glob(pattern):
            if not path.is_file() or path.name in REPROCESS_ALL_QUALITY_CHECK_PRESERVE:
                continue
            deleted.append(_delete_generated_file(path, "quality check"))
    return deleted


def _condition_cleanup_bundle(root: Path, expected_output: Path) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Collect both exact anchors and their declared arrays before deleting either."""

    anchors = tuple(dict.fromkeys(
        _assert_under_excel_root(root, path)
        for path in (expected_output.with_suffix(".xlsx"), result_manifest_path(expected_output))
    ))
    companions = tuple(dict.fromkeys(
        companion
        for anchor in anchors
        for companion in _workbook_companions(root, anchor)
    ))
    return anchors, companions


def clean_participant_outputs(project: Any, plan: ProcessingPlan) -> list[Path]:
    root = _excel_root(project).resolve()
    project_root = Path(project.project_root).resolve()
    ledger = load_ledger(project_root)
    entries = ledger.get("entries", {})
    if not isinstance(entries, Mapping):
        entries = {}
    deleted: list[Path] = []
    run_files = {path.resolve() for path in plan.run_files}
    derivative_targets: dict[str, tuple[Path, ...]] = {}
    for state in plan.states:
        if state.info.path.resolve() not in run_files:
            continue
        entry = entries.get(state.processing_id)
        derivative_targets[state.processing_id] = _recorded_source_derivative_paths(
            project_root,
            entry if isinstance(entry, Mapping) else None,
        )
    for state in plan.states:
        if state.info.path.resolve() not in run_files:
            continue
        for expected_output in state.expected_outputs:
            anchors, companions = _condition_cleanup_bundle(root, expected_output)
            for target in anchors:
                if target.exists():
                    target.unlink()
                    deleted.append(target)
            for companion in companions:
                deleted.append(_delete_generated_file(companion, "condition data companion"))
        deleted.extend(
            _delete_recorded_source_derivative_targets(
                project_root,
                derivative_targets.get(state.processing_id, ()),
            )
        )
    return deleted


def _remove_expected_outputs_for_state(
    project: Any,
    state: ProcessingInputState,
    entry: Mapping[str, Any] | None = None,
) -> list[str]:
    root = _excel_root(project).resolve()
    project_root = Path(project.project_root).resolve()
    derivative_targets = _recorded_source_derivative_paths(project_root, entry)
    removed: list[str] = []
    for expected_output in state.expected_outputs:
        anchors, companions = _condition_cleanup_bundle(root, expected_output)
        for target in anchors:
            if not target.exists():
                continue
            try:
                target.unlink()
            except OSError as exc:
                logger.warning(
                    "excluded_output_cleanup_failed",
                    extra={"path": str(target), "participant_id": state.participant_id, "error": str(exc)},
                )
                break
            removed.append(str(target))
        else:
            removed.extend(str(_delete_generated_file(path, "condition data companion")) for path in companions)
    removed.extend(
        str(path)
        for path in _delete_recorded_source_derivative_targets(
            project_root,
            derivative_targets,
        )
    )
    return removed


def _info_by_resolved_path(plan: ProcessingPlan) -> dict[Path, ProcessingInputState]:
    return {state.info.path.resolve(): state for state in plan.states}


def record_processing_results(
    project: Any,
    plan: ProcessingPlan,
    results: Sequence[Mapping[str, Any]],
    *,
    run_mode: str,
    user_choice: str,
    cancelled: bool,
) -> None:
    project_root = Path(project.project_root)
    ledger = load_ledger(project_root)
    entries = ledger.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        ledger["entries"] = entries

    states_by_path = _info_by_resolved_path(plan)
    successful_paths: set[Path] = set()
    partial_condition_paths: set[Path] = set()
    excluded_by_path: dict[Path, Mapping[str, Any]] = {}
    no_output_failures_by_path: dict[Path, dict[str, Any]] = {}
    results_by_path: dict[Path, Mapping[str, Any]] = {}
    for result in results:
        raw_path_value = result.get("file")
        if raw_path_value:
            results_by_path[Path(str(raw_path_value)).resolve()] = result
        if result.get("status") == "excluded":
            if raw_path_value:
                excluded_by_path[Path(str(raw_path_value)).resolve()] = result
            continue
        if result.get("status") != "ok":
            continue
        raw_path_value = result.get("file")
        if not raw_path_value:
            continue
        raw_path = Path(str(raw_path_value)).resolve()
        state = states_by_path.get(raw_path)
        if state is None:
            continue
        missing_outputs = [
            str(path) for path in state.expected_outputs if not path.exists()
        ]
        present_outputs = [
            str(path) for path in state.expected_outputs if path.exists()
        ]
        missing_condition_labels = _condition_labels_for_missing_outputs(
            plan,
            state,
            missing_outputs,
        )
        if missing_outputs and not present_outputs:
            no_output_failures_by_path[raw_path] = {
                "result": result,
                "missing_outputs": missing_outputs,
                "missing_condition_labels": missing_condition_labels,
            }
            continue
        if missing_outputs:
            partial_condition_paths.add(raw_path)
        successful_paths.add(raw_path)
        raw_meta = raw_file_metadata(state.info.path)
        audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
        geometry_identity = _result_geometry_identity(
            result,
            plan.geometry_identity,
            require_observed=True,
        )
        raw_qc_bad_channels = _string_list(audit.get("raw_qc_bad_channels"))
        raw_qc_low_variance_channels = _string_list(
            audit.get("raw_qc_low_variance_channels")
        )
        raw_qc_high_amplitude_channels = _string_list(
            audit.get("raw_qc_high_amplitude_channels")
        )
        raw_qc_spatial_outlier_channels = _string_list(
            audit.get("raw_qc_spatial_outlier_channels")
        )
        raw_qc_manual_removed_channels = _string_list(
            audit.get("raw_qc_manual_removed_channels")
        )
        raw_qc_warning_rules = _string_list(audit.get("raw_qc_warning_rules"))
        kurtosis_bad_channels = _string_list(audit.get("kurtosis_bad_channels"))
        interpolated_channels = _string_list(audit.get("interpolated_channels"))
        n_rejected = _int_or_default(audit.get("n_rejected"), len(kurtosis_bad_channels))
        preprocessing_evidence = _preprocessing_evidence_payload(
            processing_status=(
                PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS
                if missing_outputs
                else PROCESSING_STATUS_COMPLETED
            ),
            processing_reason="",
            missing_conditions=missing_condition_labels,
            interpolation_source=audit,
            geometry_identity=geometry_identity,
            geometry_was_observed=True,
        )
        entries[state.processing_id] = {
            **_recording_identity_payload(state.info),
            "group_id": state.info.group,
            **raw_meta,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
            "geometry": geometry_identity,
            "expected_outputs": [str(path) for path in state.expected_outputs],
            "export_receipts": _export_receipts_payload(result),
            "status": "completed",
            "completed_at": _now_iso(),
            "run_mode": run_mode,
            "raw_qc_bad_channels": raw_qc_bad_channels,
            "raw_qc_low_variance_channels": raw_qc_low_variance_channels,
            "raw_qc_high_amplitude_channels": raw_qc_high_amplitude_channels,
            "raw_qc_spatial_outlier_channels": raw_qc_spatial_outlier_channels,
            "raw_qc_manual_removed_channels": raw_qc_manual_removed_channels,
            "raw_qc_warning_rules": raw_qc_warning_rules,
            **_raw_qc_extra_payload(audit),
            **_removed_electrode_review_payload(audit),
            "kurtosis_bad_channels": kurtosis_bad_channels,
            "interpolated_channels": interpolated_channels,
            **_interpolation_payload(audit),
            **preprocessing_evidence,
            "n_rejected": n_rejected,
            "condition_completeness": "partial" if missing_outputs else "complete",
            "completion_warning": (
                MISSING_EXPECTED_OUTPUTS_WARNING if missing_outputs else None
            ),
            "missing_outputs": missing_outputs,
            "missing_condition_labels": missing_condition_labels,
            "present_outputs": present_outputs,
            **_source_derivative_result_payload(result),
        }

    run_files = {path.resolve() for path in plan.run_files}
    excluded_paths = set(excluded_by_path) & run_files
    for raw_path in sorted(run_files - successful_paths):
        state = states_by_path.get(raw_path)
        if state is None:
            continue
        excluded_result = excluded_by_path.get(raw_path)
        if excluded_result is not None:
            exclusion_reason = str(excluded_result.get("reason") or "excluded")
            geometry_independent = (
                exclusion_reason.strip().casefold()
                in _GEOMETRY_INDEPENDENT_EXCLUSION_REASONS
            )
            geometry_identity = _result_geometry_identity(
                excluded_result,
                plan.geometry_identity,
                require_observed=not geometry_independent,
            )
            previous_entry = entries.get(state.processing_id)
            removed_outputs = _remove_expected_outputs_for_state(
                project,
                state,
                previous_entry if isinstance(previous_entry, Mapping) else None,
            )
            qc_payload = (
                excluded_result.get("raw_channel_qc")
                if isinstance(excluded_result.get("raw_channel_qc"), Mapping)
                else {}
            )
            raw_qc_bad_channels = _string_list(qc_payload.get("bad_channels"))
            raw_qc_low_variance_channels = _string_list(
                qc_payload.get("low_variance_channels")
            )
            raw_qc_high_amplitude_channels = _string_list(
                qc_payload.get("high_amplitude_channels")
            )
            raw_qc_spatial_outlier_channels = _string_list(
                qc_payload.get("spatial_outlier_channels")
            )
            raw_qc_manual_removed_channels = _string_list(
                qc_payload.get("manual_removed_channels")
            )
            raw_qc_warning_rules = _string_list(qc_payload.get("warning_rules"))
            n_rejected = _int_or_default(
                qc_payload.get("n_bad_channels"),
                len(raw_qc_bad_channels),
            )
            preprocessing_evidence = _preprocessing_evidence_payload(
                processing_status=PROCESSING_STATUS_EXCLUDED,
                processing_reason=str(
                    excluded_result.get("message") or exclusion_reason
                ),
                interpolation_source=qc_payload,
                geometry_identity=geometry_identity,
                geometry_was_observed=_has_observed_geometry(excluded_result),
                excluded_before_preprocessing=True,
            )
            entries[state.processing_id] = {
                **_recording_identity_payload(state.info),
                "group_id": state.info.group,
                **raw_file_metadata(state.info.path),
                "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                "processing_fingerprint": plan.fingerprint,
                "geometry": geometry_identity,
                "expected_outputs": [str(path) for path in state.expected_outputs],
                "export_receipts": _export_receipts_payload(excluded_result),
                "status": "excluded",
                "completed_at": None,
                "run_mode": run_mode,
                "exclusion_reason": exclusion_reason,
                "exclusion_message": str(
                    excluded_result.get("message") or "Raw file was excluded from processing."
                ),
                "excluded_at": _now_iso(),
                "removed_outputs": removed_outputs,
                "raw_qc_bad_channels": raw_qc_bad_channels,
                "raw_qc_low_variance_channels": raw_qc_low_variance_channels,
                "raw_qc_high_amplitude_channels": raw_qc_high_amplitude_channels,
                "raw_qc_spatial_outlier_channels": raw_qc_spatial_outlier_channels,
                "raw_qc_manual_removed_channels": raw_qc_manual_removed_channels,
                "raw_qc_warning_rules": raw_qc_warning_rules,
                **_raw_qc_extra_payload(qc_payload),
                **_removed_electrode_review_payload(qc_payload),
                "kurtosis_bad_channels": [],
                "interpolated_channels": [],
                **_interpolation_payload(qc_payload),
                **preprocessing_evidence,
                "n_rejected": n_rejected,
                **_source_derivative_result_payload(excluded_result),
            }
            continue
        no_output_failure = no_output_failures_by_path.get(raw_path)
        if no_output_failure is not None:
            result = (
                no_output_failure.get("result")
                if isinstance(no_output_failure.get("result"), Mapping)
                else {}
            )
            audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
            raw_qc_bad_channels = _string_list(audit.get("raw_qc_bad_channels"))
            raw_qc_low_variance_channels = _string_list(
                audit.get("raw_qc_low_variance_channels")
            )
            raw_qc_high_amplitude_channels = _string_list(
                audit.get("raw_qc_high_amplitude_channels")
            )
            raw_qc_spatial_outlier_channels = _string_list(
                audit.get("raw_qc_spatial_outlier_channels")
            )
            raw_qc_manual_removed_channels = _string_list(
                audit.get("raw_qc_manual_removed_channels")
            )
            raw_qc_warning_rules = _string_list(audit.get("raw_qc_warning_rules"))
            kurtosis_bad_channels = _string_list(audit.get("kurtosis_bad_channels"))
            interpolated_channels = _string_list(audit.get("interpolated_channels"))
            n_rejected = _int_or_default(
                audit.get("n_rejected"),
                len(interpolated_channels) or len(kurtosis_bad_channels),
            )
            missing_outputs = [
                str(path) for path in no_output_failure.get("missing_outputs", [])
            ]
            missing_condition_labels = [
                str(label)
                for label in no_output_failure.get("missing_condition_labels", [])
            ]
            geometry_identity = _result_geometry_identity(
                result,
                plan.geometry_identity,
            )
            preprocessing_evidence = _preprocessing_evidence_payload(
                processing_status=PROCESSING_STATUS_FAILED,
                processing_reason=(
                    "Processing did not produce any expected condition workbooks."
                ),
                missing_conditions=missing_condition_labels,
                interpolation_source=audit,
                geometry_identity=geometry_identity,
                geometry_was_observed=_has_observed_geometry(result),
            )
            entries[state.processing_id] = {
                **_recording_identity_payload(state.info),
                "group_id": state.info.group,
                **raw_file_metadata(state.info.path),
                "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                "processing_fingerprint": plan.fingerprint,
                "geometry": geometry_identity,
                "expected_outputs": [str(path) for path in state.expected_outputs],
                "export_receipts": _export_receipts_payload(result),
                "status": "failed",
                "completed_at": None,
                "run_mode": run_mode,
                "failure_reason": NO_EXPECTED_OUTPUTS_FAILURE,
                "failure_message": (
                    "Processing did not produce any expected Excel condition outputs; "
                    "no condition-level workbooks are available for this participant."
                ),
                "missing_outputs": missing_outputs,
                "missing_condition_labels": missing_condition_labels,
                "removed_outputs": [],
                "raw_qc_bad_channels": raw_qc_bad_channels,
                "raw_qc_low_variance_channels": raw_qc_low_variance_channels,
                "raw_qc_high_amplitude_channels": raw_qc_high_amplitude_channels,
                "raw_qc_spatial_outlier_channels": raw_qc_spatial_outlier_channels,
                "raw_qc_manual_removed_channels": raw_qc_manual_removed_channels,
                "raw_qc_warning_rules": raw_qc_warning_rules,
                **_raw_qc_extra_payload(audit),
                **_removed_electrode_review_payload(audit),
                "kurtosis_bad_channels": kurtosis_bad_channels,
                "interpolated_channels": interpolated_channels,
                **_interpolation_payload(audit),
                **preprocessing_evidence,
                "n_rejected": n_rejected,
                **_source_derivative_result_payload(result),
            }
            continue
        previous_entry = entries.get(state.processing_id)
        removed_outputs = _remove_expected_outputs_for_state(
            project,
            state,
            previous_entry if isinstance(previous_entry, Mapping) else None,
        )
        failed_result = results_by_path.get(raw_path)
        failed_audit = (
            failed_result.get("audit")
            if isinstance(failed_result, Mapping)
            and isinstance(failed_result.get("audit"), Mapping)
            else {}
        )
        failed_provenance = dict(failed_result or {})
        failed_provenance.update(failed_audit)
        interpolated_channels = _string_list(
            failed_provenance.get("interpolated_channels")
        )
        geometry_identity = _result_geometry_identity(
            failed_result,
            plan.geometry_identity,
        )
        processing_status = (
            PROCESSING_STATUS_PENDING if cancelled else PROCESSING_STATUS_FAILED
        )
        processing_reason = "" if cancelled else str(
            (failed_result or {}).get("error") or "Processing did not complete."
        )
        preprocessing_evidence = _preprocessing_evidence_payload(
            processing_status=processing_status,
            processing_reason=processing_reason,
            interpolation_source=failed_provenance,
            geometry_identity=geometry_identity,
            geometry_was_observed=_has_observed_geometry(failed_result),
        )
        entries[state.processing_id] = {
            **_recording_identity_payload(state.info),
            "group_id": state.info.group,
            **raw_file_metadata(state.info.path),
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
            "geometry": geometry_identity,
            "expected_outputs": [str(path) for path in state.expected_outputs],
            "export_receipts": _export_receipts_payload(failed_result),
            "status": "incomplete" if cancelled else "failed",
            "completed_at": None,
            "run_mode": run_mode,
            "removed_outputs": removed_outputs,
            "raw_qc_bad_channels": [],
            "raw_qc_low_variance_channels": [],
            "raw_qc_high_amplitude_channels": [],
            "raw_qc_spatial_outlier_channels": [],
            "raw_qc_manual_removed_channels": [],
            "raw_qc_warning_rules": [],
            **_raw_qc_extra_payload({}),
            **_removed_electrode_review_payload({}),
            "kurtosis_bad_channels": [],
            "interpolated_channels": interpolated_channels,
            **_interpolation_payload(failed_provenance),
            **preprocessing_evidence,
            "n_rejected": 0,
            **_source_derivative_result_payload(failed_result),
        }

    recording_condition_outcome_payload: dict[str, Any] | None = None
    try:
        expected_plan = load_expected_recording_condition_plan(project_root)
        if expected_plan is not None:
            if expected_plan.processing_fingerprint != plan.fingerprint:
                raise RecordingConditionOutcomeError(
                    "The expected recording-condition plan belongs to a different "
                    "processing fingerprint."
                )
            current_export_receipts = [
                receipt
                for result in results
                for receipt in _export_receipts_payload(result)
            ]
            outcomes = reconcile_recording_condition_outputs(
                expected_plan,
                current_export_receipts,
            )
            recording_condition_outcome_payload = outcomes.to_payload()
            recording_condition_outcome_payload["reconciliation_status"] = (
                "complete"
            )
            ledger[RECORDING_CONDITION_OUTCOME_LEDGER_KEY] = (
                recording_condition_outcome_payload
            )
    except (ExpectedRecordingConditionPlanError, RecordingConditionOutcomeError) as exc:
        raw_expected = ledger.get(EXPECTED_RECORDING_CONDITION_PLAN_LEDGER_KEY)
        expected_run_id = (
            str(raw_expected.get("run_id") or "")
            if isinstance(raw_expected, Mapping)
            else ""
        )
        expected_fingerprint = (
            str(raw_expected.get("fingerprint") or "")
            if isinstance(raw_expected, Mapping)
            else ""
        )
        recording_condition_outcome_payload = {
            "version": RECORDING_CONDITION_OUTCOME_VERSION,
            "reconciliation_status": "blocked",
            "expected_plan_run_id": expected_run_id,
            "expected_plan_fingerprint": expected_fingerprint,
            "is_pre_review_ready": False,
            "status_counts": {"blocked": len(plan.states)},
            "cells": [],
            "reason": str(exc),
        }
        ledger[RECORDING_CONDITION_OUTCOME_LEDGER_KEY] = (
            recording_condition_outcome_payload
        )

    save_ledger(project_root, ledger)

    if (
        successful_paths
        and getattr(project, "groups", {})
        and not getattr(project, "groups_locked", False)
    ):
        project.groups_locked = True
        project.groups_locked_at = _now_iso()
        project.save()

    append_run_log(
        project_root,
        {
            "run_mode": run_mode,
            "user_choice": user_choice,
            "cancelled": cancelled,
            "total_files": len(plan.states),
            "run_files": len(plan.run_files),
            "completed_before": plan.completed_count,
            "new_files": plan.new_count,
            "stale_files": plan.stale_count,
            "successful_files": len(successful_paths),
            "excluded_files": len(excluded_paths),
            "failed_files": max(0, len(run_files - successful_paths - excluded_paths)),
            "condition_warning_files": len(partial_condition_paths),
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "processing_fingerprint": plan.fingerprint,
            "geometry": dict(plan.geometry_identity),
            "recording_condition_outcomes": recording_condition_outcome_payload,
        },
    )

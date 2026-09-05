"""Recording-level preprocessing QC report workbook export."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_AVAILABLE,
    INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT,
    InterpolationBurden,
    build_interpolation_burden,
    summarize_interpolation_burdens,
)
from Main_App.processing.preprocessing_outcome import (
    INTERPOLATION_STATUS_ATTEMPTED,
    INTERPOLATION_STATUS_FAILED,
    INTERPOLATION_STATUS_LEGACY_UNKNOWN,
    INTERPOLATION_STATUS_NOT_NEEDED,
    INTERPOLATION_STATUS_SKIPPED,
    INTERPOLATION_STATUS_SUCCEEDED,
    PROCESSING_STATUS_COMPLETED,
    PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS,
    PROCESSING_STATUS_EXCLUDED,
    PROCESSING_STATUS_FAILED,
    PROCESSING_STATUS_LEGACY_UNKNOWN,
    PROCESSING_STATUS_PENDING,
    normalize_preprocessing_outcome,
)
from Main_App.processing.processing_ledger import (
    MISSING_EXPECTED_OUTPUTS_WARNING,
    ProcessingInputState,
    ProcessingPlan,
    load_ledger,
)

QC_SUMMARY_FILENAME = "Processing_QC_Summary.xlsx"
QC_SUMMARY_SHEET = "Preprocessing QC"
INTERPOLATION_BURDEN_SUMMARY_SHEET = "Burden Summary"
QUALITY_CHECK_FOLDER = "Quality Check"
DATA_QUALITY_REVIEW_FLAGS_FILENAME = "Data_Quality_Check_Review_Flags.xlsx"
QC_SUMMARY_HEADERS = (
    "PID",
    "Manually Removed Electrodes",
    "Auto-Detected Removed Electrodes (Low SD)",
    "Preflight Auto-Flagged Removed Electrodes",
    "Accepted FPVS Auto-Flagged Electrodes",
    "Rejected FPVS Auto-Flagged Electrodes",
    "Manual Additions",
    "Final Confirmed Removed Electrodes",
    "Manually Confirmed Only (Auto Missed)",
    "Auto and Manual Removed Electrodes",
    "Auto/Manual Removed-Electrode Agreement",
    "Flagged Removed-Electrode Candidates (High Amplitude)",
    "Flagged Removed-Electrode Candidates (Rare Burst)",
    "Flagged Removed-Electrode Candidates (Spatial Consistency)",
    "Kurtosis QC Status",
    "Kurtosis Method",
    "Kurtosis Candidate Electrodes",
    "Kurtosis Review-Required Electrodes",
    "Kurtosis Corroborated Automatic Electrodes",
    "Kurtosis User-Approved Electrodes",
    "Kurtosis User-Rejected Electrodes",
    "Kurtosis Evidence Fingerprint",
    "Interpolation Requested Electrodes",
    "Successfully Interpolated Electrodes",
    "Successfully Interpolated Count",
    "Eligible Scalp Electrode Count",
    "Interpolation Burden (%)",
    "Interpolation Review (>5%)",
    "Interpolation Outcome",
    "Interpolation Detail",
    "Total Number of Electrodes removed/rejected",
    "Raw QC Warnings",
    "Raw Baseline Median STD (uV)",
    "Raw Baseline Median P2P99 (uV)",
    "Raw Baseline QC",
    "Missing Conditions",
    "Preprocessing Status",
    "Exclusion Reason",
)
RECORDING_QC_IDENTITY_HEADERS = (
    "PID",
    "Recording ID",
    "Session ID",
    "Session",
    "Visit Index",
    "Group ID",
)
_REVIEW_FLAG_PATTERNS = {
    "high_amplitude": re.compile(r"high-amplitude channel\(s\):\s*([^;]+)", re.IGNORECASE),
    "rare_burst": re.compile(r"rare-burst channel\(s\):\s*([^;]+)", re.IGNORECASE),
    "spatial_outlier": re.compile(r"spatially inconsistent channel\(s\):\s*([^;]+)", re.IGNORECASE),
    "warning_rules": re.compile(r"raw data warning rule\(s\):\s*([^;]+)", re.IGNORECASE),
}


def _quality_check_root(project: Any) -> Path:
    return Path(project.project_root) / QUALITY_CHECK_FOLDER


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, Sequence):
        return [str(item) for item in value if str(item).strip()]
    return []


def _int_or_default(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _result_by_path(results: Sequence[Mapping[str, Any]]) -> dict[Path, Mapping[str, Any]]:
    by_path: dict[Path, Mapping[str, Any]] = {}
    for result in results:
        raw_path_value = result.get("file")
        if raw_path_value:
            by_path[Path(str(raw_path_value)).resolve()] = result
    return by_path


def _channels_from_result(result: Mapping[str, Any] | None) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    interpolated = _string_list(audit.get("interpolated_channels"))
    return interpolated


def _raw_qc_channels_from_result(result: Mapping[str, Any] | None) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_bad_channels"))
        or _string_list(raw_qc.get("bad_channels"))
    )


def _raw_qc_low_variance_channels_from_result(
    result: Mapping[str, Any] | None,
) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_low_variance_channels"))
        or _string_list(raw_qc.get("low_variance_channels"))
    )


def _raw_qc_manual_removed_channels_from_result(
    result: Mapping[str, Any] | None,
) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_manual_removed_channels"))
        or _string_list(raw_qc.get("manual_removed_channels"))
    )


def _raw_qc_spatial_outlier_channels_from_result(
    result: Mapping[str, Any] | None,
) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_spatial_outlier_channels"))
        or _string_list(raw_qc.get("spatial_outlier_channels"))
    )


def _raw_qc_high_amplitude_channels_from_result(
    result: Mapping[str, Any] | None,
) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_high_amplitude_channels"))
        or _string_list(raw_qc.get("high_amplitude_channels"))
    )


def _raw_qc_rare_burst_channels_from_result(
    result: Mapping[str, Any] | None,
) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_rare_burst_channels"))
        or _string_list(raw_qc.get("rare_burst_channels"))
    )


def _raw_qc_warning_rules_from_result(result: Mapping[str, Any] | None) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return (
        _string_list(audit.get("raw_qc_warning_rules"))
        or _string_list(raw_qc.get("warning_rules"))
    )


def _raw_qc_scalar_from_result(
    result: Mapping[str, Any] | None,
    audit_key: str,
    raw_qc_key: str,
) -> Any:
    if not result:
        return None
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    value = audit.get(audit_key)
    if value not in (None, ""):
        return value
    return raw_qc.get(raw_qc_key)


def _review_list_from_result(
    result: Mapping[str, Any] | None,
    key: str,
) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return _string_list(audit.get(key)) or _string_list(raw_qc.get(key))


def _review_scalar_from_result(
    result: Mapping[str, Any] | None,
    key: str,
) -> str:
    if not result:
        return ""
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    value = audit.get(key) or raw_qc.get(key)
    return str(value or "").strip()


def _kurtosis_channels_from_result(result: Mapping[str, Any] | None) -> list[str]:
    if not result:
        return []
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    return _string_list(audit.get("kurtosis_bad_channels"))


def _kurtosis_report_fields(
    result: Mapping[str, Any] | None,
    entry: Mapping[str, Any],
    cache_entry: Mapping[str, Any],
) -> dict[str, object]:
    """Render QC-16 evidence and decisions without conflating them with repair."""

    audit = (
        result.get("audit")
        if result and isinstance(result.get("audit"), Mapping)
        else {}
    )

    def _channels(key: str, *, legacy_key: str | None = None) -> list[str]:
        for source in (audit, entry, cache_entry):
            values = _string_list(source.get(key))
            if values:
                return values
            if legacy_key:
                values = _string_list(source.get(legacy_key))
                if values:
                    return values
        return []

    evidence: Mapping[str, Any] = {}
    for source in (audit, entry, cache_entry):
        candidate = source.get("kurtosis_qc_evidence")
        if isinstance(candidate, Mapping):
            evidence = candidate
            break
    status = str(
        evidence.get("status")
        or evidence.get("evaluation_status")
        or ("legacy/not recorded" if _channels("kurtosis_bad_channels") else "not evaluated")
    ).strip()
    method = str(evidence.get("method_label") or evidence.get("method_version") or "").strip()
    fingerprint = str(evidence.get("fingerprint") or "").strip()
    decision_plan: Mapping[str, Any] = {}
    for source in (audit, entry, cache_entry):
        candidate = source.get("kurtosis_decision_plan")
        if isinstance(candidate, Mapping) and candidate:
            decision_plan = candidate
            break
    experimental_channels = [
        str(row.get("channel"))
        for row in decision_plan.get("channel_decisions", [])
        if isinstance(row, Mapping) and row.get("state") == "experimental_automatic"
    ]
    return {
        "Kurtosis QC Status": status or "not evaluated",
        "Kurtosis Method": method or "Not recorded",
        "Kurtosis Candidate Electrodes": _join_channels(
            _channels(
                "kurtosis_candidate_channels",
                legacy_key="kurtosis_bad_channels",
            )
        ),
        "Kurtosis Review-Required Electrodes": _join_channels(
            _channels("kurtosis_review_required_channels")
        ),
        "Kurtosis Corroborated Automatic Electrodes": _join_channels(
            _channels("kurtosis_corroborated_channels")
        ),
        "Kurtosis Experimental Automatic Electrodes": _join_channels(experimental_channels),
        "Kurtosis Experimental Auto-All Setting": (
            "Enabled" if decision_plan.get("kurtosis_auto_interpolate_all") is True
            else "Disabled" if "kurtosis_auto_interpolate_all" in decision_plan
            else "Not recorded"
        ),
        "Kurtosis User-Approved Electrodes": _join_channels(
            _channels("kurtosis_user_approved_channels")
        ),
        "Kurtosis User-Rejected Electrodes": _join_channels(
            _channels("kurtosis_user_rejected_channels")
        ),
        "Kurtosis Evidence Fingerprint": fingerprint or "Not recorded",
    }


def _join_channels(channels: Sequence[str]) -> str:
    return ", ".join(channels) if channels else "None"


def _split_review_items(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r",|;", text) if item.strip()]


def _unique_ordered(*groups: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for channel in group:
            if channel in seen:
                continue
            seen.add(channel)
            merged.append(channel)
    return merged


def _review_flags_by_identity(project: Any) -> dict[str, dict[str, list[str]]]:
    report_path = _quality_check_root(project) / DATA_QUALITY_REVIEW_FLAGS_FILENAME
    if not report_path.exists():
        return {}
    try:
        workbook = load_workbook(report_path, read_only=True, data_only=True)
    except OSError:
        return {}
    try:
        worksheet = workbook["Review Flags"] if "Review Flags" in workbook.sheetnames else workbook.active
        rows = worksheet.iter_rows(values_only=True)
        headers = [str(value or "").strip() for value in next(rows, ())]
        participant_index = next(
            (
                headers.index(header)
                for header in ("PID", "Participant")
                if header in headers
            ),
            None,
        )
        recording_index = next(
            (
                headers.index(header)
                for header in ("Recording", "Recording ID")
                if header in headers
            ),
            None,
        )
        if participant_index is None or "Flagged Item" not in headers:
            return {}
        item_index = headers.index("Flagged Item")
        by_identity: dict[str, dict[str, list[str]]] = {}
        for row in rows:
            if row is None:
                continue
            participant_id = str(row[participant_index] or "").strip()
            recording_id = (
                str(row[recording_index] or "").strip()
                if recording_index is not None and recording_index < len(row)
                else ""
            )
            item = str(row[item_index] or "").strip()
            identity = (
                recording_id
                if recording_id
                and recording_id.casefold() != "not registered"
                else participant_id
            )
            if not identity or not item:
                continue
            bucket = by_identity.setdefault(
                identity.casefold(),
                {
                    "high_amplitude": [],
                    "rare_burst": [],
                    "spatial_outlier": [],
                    "warning_rules": [],
                },
            )
            for key, pattern in _REVIEW_FLAG_PATTERNS.items():
                match = pattern.search(item)
                if match:
                    bucket[key] = _unique_ordered(
                        bucket[key],
                        _split_review_items(match.group(1)),
                    )
        return by_identity
    finally:
        workbook.close()


def _count_from_result(result: Mapping[str, Any] | None, fallback: int) -> int:
    if not result:
        return fallback
    audit = result.get("audit") if isinstance(result.get("audit"), Mapping) else {}
    raw_qc = result.get("raw_channel_qc") if isinstance(result.get("raw_channel_qc"), Mapping) else {}
    return max(
        _int_or_default(audit.get("n_rejected"), fallback),
        _int_or_default(raw_qc.get("n_bad_channels"), 0),
    )


def _entry_for_pid(ledger: Mapping[str, Any], pid: str) -> Mapping[str, Any]:
    entries = ledger.get("entries")
    if not isinstance(entries, Mapping):
        return {}
    entry = entries.get(pid)
    return entry if isinstance(entry, Mapping) else {}


def _has_missing_condition_warning(entry: Mapping[str, Any]) -> bool:
    return (
        str(entry.get("completion_warning") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
        or str(entry.get("failure_reason") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
        or str(entry.get("condition_completeness") or "").casefold() == "partial"
    )


def _exclusion_reason(
    entry: Mapping[str, Any],
    result: Mapping[str, Any] | None,
) -> str:
    if result and str(result.get("status") or "").casefold() == "excluded":
        return str(
            result.get("message")
            or result.get("reason")
            or "Raw file was excluded from processing."
        )
    status = str(entry.get("status") or "").casefold()
    if status == "excluded":
        return str(
            entry.get("exclusion_message")
            or entry.get("exclusion_reason")
            or "Raw file was excluded from processing."
        )
    if status == "failed":
        return str(entry.get("failure_message") or entry.get("failure_reason") or "")
    return ""


_PROCESSING_STATUS_LABELS = {
    PROCESSING_STATUS_COMPLETED: "Completed",
    PROCESSING_STATUS_COMPLETED_MISSING_CONDITIONS: (
        "Completed with missing conditions"
    ),
    PROCESSING_STATUS_EXCLUDED: "Excluded before preprocessing",
    PROCESSING_STATUS_FAILED: "Failed",
    PROCESSING_STATUS_PENDING: "Pending",
    PROCESSING_STATUS_LEGACY_UNKNOWN: "Not recorded (legacy result)",
}
_INTERPOLATION_STATUS_LABELS = {
    INTERPOLATION_STATUS_SUCCEEDED: "Succeeded",
    INTERPOLATION_STATUS_FAILED: "Failed",
    INTERPOLATION_STATUS_ATTEMPTED: "Attempted; outcome not confirmed",
    INTERPOLATION_STATUS_SKIPPED: "Skipped",
    INTERPOLATION_STATUS_NOT_NEEDED: "Not needed",
    INTERPOLATION_STATUS_LEGACY_UNKNOWN: "Not recorded",
}


def _interpolation_burden_for_entry(
    entry: Mapping[str, Any],
) -> InterpolationBurden:
    outcome = normalize_preprocessing_outcome(entry)
    geometry = entry.get("geometry")
    return build_interpolation_burden(
        outcome,
        geometry if isinstance(geometry, Mapping) else None,
    )


def _preprocessing_report_fields(entry: Mapping[str, Any]) -> dict[str, object]:
    outcome = normalize_preprocessing_outcome(entry)
    burden = _interpolation_burden_for_entry(entry)
    if outcome.interpolation_status == INTERPOLATION_STATUS_LEGACY_UNKNOWN:
        requested: object = "Not recorded"
        successful: object = "Not recorded"
    else:
        requested = _join_channels(list(outcome.interpolation_requested_channels))
        successful = _join_channels(list(outcome.interpolation_successful_channels))

    if burden.status == INTERPOLATION_BURDEN_AVAILABLE:
        burden_count: object = int(burden.numerator or 0)
        eligible_count: object = int(burden.denominator or 0)
        burden_percentage: object = float(burden.percentage or 0.0)
        review = "Review required" if burden.requires_review else "No review flag"
    else:
        burden_count = "Unavailable"
        eligible_count = "Unavailable"
        burden_percentage = "Unavailable"
        review = "Unavailable"

    return {
        "Interpolation Requested Electrodes": requested,
        "Successfully Interpolated Electrodes": successful,
        "Successfully Interpolated Count": burden_count,
        "Eligible Scalp Electrode Count": eligible_count,
        "Interpolation Burden (%)": burden_percentage,
        "Interpolation Review (>5%)": review,
        "Interpolation Outcome": _INTERPOLATION_STATUS_LABELS[
            outcome.interpolation_status
        ],
        "Interpolation Detail": outcome.interpolation_detail or "None",
        "Preprocessing Status": _PROCESSING_STATUS_LABELS[
            outcome.processing_status
        ],
    }


def _is_legacy_partial_condition_entry(
    state: ProcessingInputState,
    entry: Mapping[str, Any],
) -> bool:
    status = str(entry.get("status") or "").strip().casefold()
    return (
        status == "failed"
        and any(path.exists() for path in state.expected_outputs)
        and any(not path.exists() for path in state.expected_outputs)
    )


def _resolved_path_strings(values: Sequence[Any]) -> set[str]:
    resolved: set[str] = set()
    for value in values:
        try:
            resolved.add(str(Path(str(value)).resolve()))
        except (OSError, TypeError, ValueError):
            continue
    return resolved


def _missing_condition_labels(
    plan: ProcessingPlan,
    state: ProcessingInputState,
    entry: Mapping[str, Any],
) -> list[str]:
    labels = _string_list(entry.get("missing_condition_labels"))
    if labels:
        return labels

    missing_outputs = _string_list(entry.get("missing_outputs"))
    if not missing_outputs and (
        _has_missing_condition_warning(entry)
        or _is_legacy_partial_condition_entry(state, entry)
    ):
        missing_outputs = [str(path) for path in state.expected_outputs if not path.exists()]
    missing = _resolved_path_strings(missing_outputs)
    if not missing:
        return []

    derived: list[str] = []
    for index, output_path in enumerate(state.expected_outputs):
        if str(output_path.resolve()) not in missing:
            continue
        if index < len(plan.condition_labels):
            derived.append(str(plan.condition_labels[index]))
        else:
            derived.append(output_path.parent.name)
    return derived


_PreprocessedCacheIdentity = tuple[Path, int, int]
_PreprocessedCacheQcIndex = Mapping[
    _PreprocessedCacheIdentity,
    Mapping[str, Any],
]


def _cache_identity_for_entry(
    entry: Mapping[str, Any],
) -> _PreprocessedCacheIdentity | None:
    raw_file = entry.get("raw_file")
    if not raw_file:
        return None
    try:
        raw_path = Path(str(raw_file)).resolve()
        expected_size = int(entry.get("raw_size"))
        expected_mtime_ns = int(entry.get("raw_mtime_ns"))
    except (OSError, TypeError, ValueError):
        return None
    return raw_path, expected_size, expected_mtime_ns


def _preprocessed_cache_qc_index(project: Any) -> _PreprocessedCacheQcIndex:
    cache_dir = Path(project.project_root) / ".fpvs_cache" / "preprocessed"
    if not cache_dir.exists():
        return {}

    newest_by_identity: dict[
        _PreprocessedCacheIdentity,
        tuple[float, Mapping[str, Any]],
    ] = {}
    for meta_path in cache_dir.glob("*.json"):
        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, Mapping):
            continue
        payload = metadata.get("payload")
        if not isinstance(payload, Mapping):
            continue
        source_path = payload.get("source_path")
        try:
            raw_path = Path(str(source_path)).resolve()
        except (OSError, TypeError, ValueError):
            continue
        try:
            source_size = int(payload.get("source_size") or -1)
            source_mtime_ns = int(payload.get("source_mtime_ns") or -1)
        except (TypeError, ValueError):
            continue
        identity = (raw_path, source_size, source_mtime_ns)
        try:
            timestamp = meta_path.stat().st_mtime
        except OSError:
            timestamp = 0.0
        current = newest_by_identity.get(identity)
        if current is None or timestamp > current[0]:
            newest_by_identity[identity] = (timestamp, metadata)

    return {
        identity: metadata
        for identity, (_, metadata) in newest_by_identity.items()
    }


def _cache_qc_for_entry(
    cache_index: _PreprocessedCacheQcIndex,
    entry: Mapping[str, Any],
) -> Mapping[str, Any]:
    identity = _cache_identity_for_entry(entry)
    if identity is None:
        return {}
    return cache_index.get(identity, {})


def build_processing_qc_rows(
    project: Any,
    plan: ProcessingPlan,
    results: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Build participant rows from the final ledger plus current run details."""

    ledger = load_ledger(Path(project.project_root))
    results_by_path = _result_by_path(results)
    review_flags = _review_flags_by_identity(project)
    cache_index: _PreprocessedCacheQcIndex | None = None
    rows: list[dict[str, object]] = []
    for state in plan.states:
        review = review_flags.get(
            (state.info.recording_id or state.participant_id).casefold(),
        ) or review_flags.get(state.participant_id.casefold(), {})
        entry = _entry_for_pid(ledger, state.processing_id)
        if entry:
            if cache_index is None:
                cache_index = _preprocessed_cache_qc_index(project)
            cache_entry = _cache_qc_for_entry(cache_index, entry)
        else:
            cache_entry = {}
        result = results_by_path.get(state.info.path.resolve())
        raw_qc_low_variance_channels = _raw_qc_low_variance_channels_from_result(
            result
        ) or _string_list(
            entry.get("raw_qc_low_variance_channels")
        ) or _string_list(
            cache_entry.get("raw_qc_low_variance_channels")
        )
        raw_qc_manual_removed_channels = _raw_qc_manual_removed_channels_from_result(
            result
        ) or _string_list(
            entry.get("raw_qc_manual_removed_channels")
        ) or _string_list(
            cache_entry.get("raw_qc_manual_removed_channels")
        )
        removed_auto_flagged = _review_list_from_result(
            result,
            "removed_electrode_original_auto_flagged",
        ) or _string_list(
            entry.get("removed_electrode_original_auto_flagged")
        ) or _string_list(
            cache_entry.get("removed_electrode_original_auto_flagged")
        )
        removed_accepted_auto = _review_list_from_result(
            result,
            "removed_electrode_accepted_auto_flagged",
        ) or _string_list(
            entry.get("removed_electrode_accepted_auto_flagged")
        ) or _string_list(
            cache_entry.get("removed_electrode_accepted_auto_flagged")
        )
        removed_rejected_auto = _review_list_from_result(
            result,
            "removed_electrode_rejected_auto_flagged",
        ) or _string_list(
            entry.get("removed_electrode_rejected_auto_flagged")
        ) or _string_list(
            cache_entry.get("removed_electrode_rejected_auto_flagged")
        )
        removed_manual_additions = _review_list_from_result(
            result,
            "removed_electrode_manual_additions",
        ) or _string_list(
            entry.get("removed_electrode_manual_additions")
        ) or _string_list(
            cache_entry.get("removed_electrode_manual_additions")
        )
        removed_final_confirmed = _review_list_from_result(
            result,
            "removed_electrode_final_confirmed_removed",
        ) or _string_list(
            entry.get("removed_electrode_final_confirmed_removed")
        ) or _string_list(
            cache_entry.get("removed_electrode_final_confirmed_removed")
        )
        removed_manual_only = _review_list_from_result(
            result,
            "removed_electrode_manual_only_missed_by_auto",
        ) or _string_list(
            entry.get("removed_electrode_manual_only_missed_by_auto")
        ) or _string_list(
            cache_entry.get("removed_electrode_manual_only_missed_by_auto")
        )
        removed_overlap = _review_list_from_result(
            result,
            "removed_electrode_auto_manual_overlap",
        ) or _string_list(
            entry.get("removed_electrode_auto_manual_overlap")
        ) or _string_list(
            cache_entry.get("removed_electrode_auto_manual_overlap")
        )
        removed_agreement = _review_scalar_from_result(
            result,
            "removed_electrode_agreement_status",
        ) or str(
            entry.get("removed_electrode_agreement_status") or ""
        ).strip() or str(
            cache_entry.get("removed_electrode_agreement_status") or ""
        ).strip()
        raw_qc_high_amplitude_channels = _raw_qc_high_amplitude_channels_from_result(
            result
        ) or _string_list(
            entry.get("raw_qc_high_amplitude_channels")
        ) or _string_list(
            cache_entry.get("raw_qc_high_amplitude_channels")
        ) or _string_list(
            review.get("high_amplitude")
        )
        raw_qc_rare_burst_channels = _raw_qc_rare_burst_channels_from_result(
            result
        ) or _string_list(
            entry.get("raw_qc_rare_burst_channels")
        ) or _string_list(
            cache_entry.get("raw_qc_rare_burst_channels")
        ) or _string_list(
            review.get("rare_burst")
        )
        raw_qc_spatial_outlier_channels = _raw_qc_spatial_outlier_channels_from_result(
            result
        ) or _string_list(
            entry.get("raw_qc_spatial_outlier_channels")
        ) or _string_list(
            cache_entry.get("raw_qc_spatial_outlier_channels")
        ) or _string_list(
            review.get("spatial_outlier")
        )
        raw_qc_warning_rules = _raw_qc_warning_rules_from_result(result) or _string_list(
            entry.get("raw_qc_warning_rules")
        ) or _string_list(
            cache_entry.get("raw_qc_warning_rules")
        ) or _string_list(
            review.get("warning_rules")
        )
        baseline_median_std = _float_or_none(
            _raw_qc_scalar_from_result(
                result,
                "raw_qc_baseline_median_std_uv",
                "raw_baseline_median_std_uv",
            )
        )
        if baseline_median_std is None:
            baseline_median_std = _float_or_none(
                entry.get("raw_qc_baseline_median_std_uv")
            )
        if baseline_median_std is None:
            baseline_median_std = _float_or_none(
                cache_entry.get("raw_qc_baseline_median_std_uv")
            )
        baseline_median_p2p = _float_or_none(
            _raw_qc_scalar_from_result(
                result,
                "raw_qc_baseline_median_p2p_99_uv",
                "raw_baseline_median_p2p_99_uv",
            )
        )
        if baseline_median_p2p is None:
            baseline_median_p2p = _float_or_none(
                entry.get("raw_qc_baseline_median_p2p_99_uv")
            )
        if baseline_median_p2p is None:
            baseline_median_p2p = _float_or_none(
                cache_entry.get("raw_qc_baseline_median_p2p_99_uv")
            )
        baseline_excluded = bool(
            _raw_qc_scalar_from_result(
                result,
                "raw_qc_baseline_excluded",
                "raw_baseline_excluded",
            )
            or entry.get("raw_qc_baseline_excluded")
            or cache_entry.get("raw_qc_baseline_excluded")
        )
        baseline_warning = bool(
            _raw_qc_scalar_from_result(
                result,
                "raw_qc_baseline_warning",
                "raw_baseline_warning",
            )
            or entry.get("raw_qc_baseline_warning")
            or cache_entry.get("raw_qc_baseline_warning")
        )
        if baseline_excluded:
            baseline_status = "Excluded"
        elif baseline_warning:
            baseline_status = "Warning"
        elif baseline_median_std is not None or baseline_median_p2p is not None:
            baseline_status = "OK"
        else:
            baseline_status = "None"
        raw_qc_channels = _raw_qc_channels_from_result(result) or _string_list(
            entry.get("raw_qc_bad_channels")
        ) or _string_list(
            cache_entry.get("raw_qc_bad_channels")
        )
        if not raw_qc_channels:
            raw_qc_channels = _unique_ordered(
                raw_qc_manual_removed_channels,
                raw_qc_low_variance_channels,
                raw_qc_high_amplitude_channels,
                raw_qc_rare_burst_channels,
                raw_qc_spatial_outlier_channels,
            )
        if (
            raw_qc_channels
            and not raw_qc_low_variance_channels
            and not raw_qc_high_amplitude_channels
            and not raw_qc_rare_burst_channels
            and not raw_qc_spatial_outlier_channels
        ):
            manual_lookup = {
                channel.casefold() for channel in raw_qc_manual_removed_channels
            }
            raw_qc_low_variance_channels = [
                channel
                for channel in raw_qc_channels
                if channel.casefold() not in manual_lookup
            ]
        kurtosis_channels = _kurtosis_channels_from_result(result) or _string_list(
            entry.get("kurtosis_bad_channels")
        ) or _string_list(
            cache_entry.get("kurtosis_bad_channels")
        )
        kurtosis_report = _kurtosis_report_fields(result, entry, cache_entry)
        preprocessing_report = _preprocessing_report_fields(entry)
        missing_condition_labels = _missing_condition_labels(plan, state, entry)
        successful_count = preprocessing_report["Successfully Interpolated Count"]
        fallback_count = max(
            _int_or_default(entry.get("n_rejected"), 0),
            _int_or_default(cache_entry.get("n_rejected"), 0),
            successful_count if isinstance(successful_count, int) else 0,
            len(
                _unique_ordered(
                    raw_qc_channels,
                    raw_qc_manual_removed_channels,
                    kurtosis_channels,
                )
            ),
        )
        count = _count_from_result(
            result,
            fallback_count,
        )
        row: dict[str, object] = {
                "PID": state.participant_id,
                "Manually Removed Electrodes": _join_channels(
                    raw_qc_manual_removed_channels
                ),
                "Auto-Detected Removed Electrodes (Low SD)": _join_channels(
                    raw_qc_low_variance_channels
                ),
                "Preflight Auto-Flagged Removed Electrodes": _join_channels(
                    removed_auto_flagged
                ),
                "Accepted FPVS Auto-Flagged Electrodes": _join_channels(
                    removed_accepted_auto
                ),
                "Rejected FPVS Auto-Flagged Electrodes": _join_channels(
                    removed_rejected_auto
                ),
                "Manual Additions": _join_channels(removed_manual_additions),
                "Final Confirmed Removed Electrodes": _join_channels(
                    removed_final_confirmed
                ),
                "Manually Confirmed Only (Auto Missed)": _join_channels(
                    removed_manual_only
                ),
                "Auto and Manual Removed Electrodes": _join_channels(removed_overlap),
                "Auto/Manual Removed-Electrode Agreement": (
                    removed_agreement or "None"
                ),
                "Flagged Removed-Electrode Candidates (High Amplitude)": _join_channels(
                    raw_qc_high_amplitude_channels
                ),
                "Flagged Removed-Electrode Candidates (Rare Burst)": _join_channels(
                    raw_qc_rare_burst_channels
                ),
                "Flagged Removed-Electrode Candidates (Spatial Consistency)": _join_channels(
                    raw_qc_spatial_outlier_channels
                ),
                **kurtosis_report,
                **preprocessing_report,
                "Total Number of Electrodes removed/rejected": count,
                "Raw QC Warnings": _join_channels(raw_qc_warning_rules),
                "Raw Baseline Median STD (uV)": (
                    f"{baseline_median_std:.1f}"
                    if baseline_median_std is not None
                    else "None"
                ),
                "Raw Baseline Median P2P99 (uV)": (
                    f"{baseline_median_p2p:.1f}"
                    if baseline_median_p2p is not None
                    else "None"
                ),
                "Raw Baseline QC": baseline_status,
                "Missing Conditions": _join_channels(missing_condition_labels),
                "Exclusion Reason": _exclusion_reason(entry, result),
            }
        if state.info.recording_id:
            row = {
                "PID": state.participant_id,
                "Recording ID": state.info.recording_id,
                "Session ID": state.info.session_id or "",
                "Session": state.info.session_label or "",
                "Visit Index": state.info.visit_index or "",
                "Group ID": state.info.group or "",
                **{key: value for key, value in row.items() if key != "PID"},
            }
        rows.append(row)
    return rows


def _interpolation_burden_summary_rows(
    project: Any,
    plan: ProcessingPlan,
) -> list[tuple[str, object]]:
    ledger = load_ledger(Path(project.project_root))
    burdens = [
        _interpolation_burden_for_entry(
            _entry_for_pid(ledger, state.processing_id)
        )
        for state in plan.states
    ]
    summary = summarize_interpolation_burdens(burdens)
    cohort_ids = [state.processing_id for state in plan.states]
    if summary.mean_percentage is not None:
        assert summary.minimum_percentage is not None
        assert summary.maximum_percentage is not None
        mean_value: object = summary.mean_percentage
        range_value: object = (
            f"{summary.minimum_percentage:.6g} to "
            f"{summary.maximum_percentage:.6g}"
        )
    else:
        mean_value = "Unavailable"
        range_value = "Unavailable"
    return [
        ("Report", "Preprocessing QC Report"),
        ("Cohort unit", "Recording"),
        ("Cohort recording IDs", ", ".join(cohort_ids) or "None"),
        ("Processing fingerprint", plan.fingerprint),
        ("Recordings in preprocessing cohort", summary.recording_count),
        (
            "Recordings contributing to burden summary",
            summary.contributing_recording_count,
        ),
        (
            "Recordings with unavailable burden",
            summary.unavailable_recording_count,
        ),
        ("Mean interpolation burden (%)", mean_value),
        ("Interpolation burden range (%)", range_value),
        (
            f"Recordings above {INTERPOLATION_BURDEN_REVIEW_THRESHOLD_PERCENT:g}%",
            summary.recordings_above_threshold,
        ),
        (
            "Review rule",
            (
                "Strictly above 5% prompts manual review; it does not "
                "automatically exclude a recording."
            ),
        ),
    ]


def export_processing_qc_summary(
    project: Any,
    plan: ProcessingPlan,
    results: Sequence[Mapping[str, Any]],
) -> Path:
    """Write the preprocessing QC report under the project Quality Check folder."""

    rows = build_processing_qc_rows(project, plan, results)
    target = _quality_check_root(project).resolve() / QC_SUMMARY_FILENAME
    target.parent.mkdir(parents=True, exist_ok=True)

    workbook = Workbook()
    workbook.properties.title = "Preprocessing QC Report"
    worksheet = workbook.active
    repeated_session = any(row.get("Recording ID") for row in rows)
    headers = (
        RECORDING_QC_IDENTITY_HEADERS + QC_SUMMARY_HEADERS[1:]
        if repeated_session
        else QC_SUMMARY_HEADERS
    )
    worksheet.title = QC_SUMMARY_SHEET
    worksheet.append(list(headers))
    for row in rows:
        worksheet.append([row.get(header, "") for header in headers])

    center_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in worksheet.iter_rows():
        for cell in row:
            cell.alignment = center_alignment
    for cell in worksheet[1]:
        cell.font = Font(bold=True)

    if worksheet.max_row >= 1 and worksheet.max_column >= 1:
        worksheet.auto_filter.ref = worksheet.dimensions
    worksheet.freeze_panes = "A2"

    for column_index, column_cells in enumerate(worksheet.columns, start=1):
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        width = min(max(max_length + 2, 12), 80)
        worksheet.column_dimensions[get_column_letter(column_index)].width = width

    burden_sheet = workbook.create_sheet(INTERPOLATION_BURDEN_SUMMARY_SHEET)
    burden_sheet.append(["Metric", "Value"])
    for metric, value in _interpolation_burden_summary_rows(project, plan):
        burden_sheet.append([metric, value])
    burden_sheet.freeze_panes = "A2"
    burden_sheet.auto_filter.ref = burden_sheet.dimensions
    for cell in burden_sheet[1]:
        cell.font = Font(bold=True)
    for row in burden_sheet.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    burden_sheet.column_dimensions["A"].width = 48
    burden_sheet.column_dimensions["B"].width = 80

    workbook.save(target)
    return target


__all__ = [
    "DATA_QUALITY_REVIEW_FLAGS_FILENAME",
    "INTERPOLATION_BURDEN_SUMMARY_SHEET",
    "QC_SUMMARY_FILENAME",
    "QC_SUMMARY_HEADERS",
    "RECORDING_QC_IDENTITY_HEADERS",
    "QC_SUMMARY_SHEET",
    "QUALITY_CHECK_FOLDER",
    "build_processing_qc_rows",
    "export_processing_qc_summary",
]

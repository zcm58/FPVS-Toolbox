"""GUI-free source-workbook provenance builders for Scalp Maps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config
from Main_App.processing.frequency_domain_qc import (
    FREQUENCY_DOMAIN_QC_METHOD_VERSION,
    FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
    load_frequency_domain_qc_state,
)
from Tools.Publication_Maps.scalp_io import (
    BIOSEMI64_SENSOR_COUNT,
    InsufficientSensorCoverageError,
    MIN_RENDER_SENSOR_COUNT,
    align_render_values,
)

COHORT_SHEET = "Cohort"
SOURCE_FILES_SHEET = "Source_Files"
PROVENANCE_SHEET = "Provenance"
SENSOR_COVERAGE_SHEET = "Sensor_Coverage"


class SourceProvenanceError(RuntimeError):
    """Raised when an auditable project-relative source identity cannot be built."""


@dataclass(frozen=True)
class SourceWorkbookFrames:
    """Frames added to the exported Scalp Maps source workbook."""

    long_values: pd.DataFrame
    grand_average_values: pd.DataFrame
    cohort: pd.DataFrame
    source_files: pd.DataFrame
    provenance: pd.DataFrame
    sensor_coverage: pd.DataFrame


def build_source_workbook_frames(
    result: Any,
    request: Any,
    *,
    cancel_check: Callable[[], None] | None = None,
) -> SourceWorkbookFrames:
    """Build complete source-data frames without mutating the numerical result."""

    _checkpoint(cancel_check)
    long_values = _with_group_identity(result.long_values, request)
    grand_values = _with_group_identity(result.grand_average_values, request)
    long_values = _project_relative_workbook_paths(long_values, request)

    included = _included_cohort_rows(result, request, long_values)
    excluded = _excluded_cohort_rows(result, request)
    cohort_rows = [*included, *excluded]
    cohort = pd.DataFrame(
        cohort_rows,
        columns=(
            "group_id",
            "group_label",
            "group_folder",
            "participant_id",
            "condition",
            "disposition",
            "reason",
            "source_workbook",
        ),
    )
    if not cohort.empty:
        cohort = cohort.drop_duplicates().sort_values(
            ["group_id", "participant_id", "condition", "disposition"],
            kind="stable",
            na_position="last",
        )

    source_files = _source_file_frame(
        result,
        request,
        included_rows=included,
        cancel_check=cancel_check,
    )
    provenance = _provenance_frame(result, request, cohort)
    sensor_coverage = _sensor_coverage_frame(grand_values, request)
    _checkpoint(cancel_check)
    return SourceWorkbookFrames(
        long_values=long_values,
        grand_average_values=grand_values,
        cohort=cohort,
        source_files=source_files,
        provenance=provenance,
        sensor_coverage=sensor_coverage,
    )


def _with_group_identity(frame: pd.DataFrame, request: Any) -> pd.DataFrame:
    output = frame.copy()
    identity = {
        "group_id": _text(getattr(request, "group_id", None)),
        "group_label": _text(getattr(request, "group_label", None)),
        "group_folder": _text(getattr(request, "group_folder", None)),
    }
    for position, (column, value) in enumerate(identity.items()):
        if column not in output.columns:
            output.insert(min(position, len(output.columns)), column, value)
        elif value:
            missing = output[column].isna() | output[column].astype(str).str.strip().eq("")
            output.loc[missing, column] = value
    return output


def _project_relative_workbook_paths(frame: pd.DataFrame, request: Any) -> pd.DataFrame:
    if "workbook_path" not in frame.columns:
        return frame
    output = frame.copy()
    output["workbook_path"] = [
        _project_relative_identity(path, request)
        for path in output["workbook_path"]
    ]
    return output


def _included_cohort_rows(
    result: Any,
    request: Any,
    long_values: pd.DataFrame,
) -> list[dict[str, object]]:
    records = tuple(getattr(result, "included_workbooks", ()) or ())
    rows: list[dict[str, object]] = []
    if records:
        for record in records:
            rows.append(_cohort_row(record, request, disposition="included"))
        return rows

    required = {"subject_id", "condition", "workbook_path"}
    if not required.issubset(long_values.columns):
        return rows
    identity_columns = [
        column
        for column in (
            "group_id",
            "group_label",
            "group_folder",
            "subject_id",
            "condition",
            "workbook_path",
        )
        if column in long_values.columns
    ]
    for record in long_values[identity_columns].drop_duplicates().to_dict("records"):
        rows.append(
            {
                "group_id": _text(record.get("group_id")),
                "group_label": _text(record.get("group_label")),
                "group_folder": _text(record.get("group_folder")),
                "participant_id": _text(record.get("subject_id")),
                "condition": _text(record.get("condition")),
                "disposition": "included",
                "reason": "",
                "source_workbook": _text(record.get("workbook_path")),
            }
        )
    return rows


def _excluded_cohort_rows(result: Any, request: Any) -> list[dict[str, object]]:
    records = tuple(getattr(result, "excluded_cohort", ()) or ())
    return [
        _cohort_row(record, request, disposition="excluded")
        for record in records
    ]


def _cohort_row(
    record: Any,
    request: Any,
    *,
    disposition: str,
) -> dict[str, object]:
    data = _record_mapping(record)
    path = data.get("path") or data.get("workbook_path")
    source_workbook = (
        _project_relative_identity(path, request)
        if path not in (None, "")
        else ""
    )
    return {
        "group_id": _text(data.get("group_id") or getattr(request, "group_id", None)),
        "group_label": _text(
            data.get("group_label") or getattr(request, "group_label", None)
        ),
        "group_folder": _text(
            data.get("group_folder") or getattr(request, "group_folder", None)
        ),
        "participant_id": _text(
            data.get("participant_id") or data.get("subject_id")
        ),
        "condition": _text(data.get("condition")),
        "disposition": _text(data.get("disposition") or disposition),
        "reason": _text(data.get("reason") or data.get("exclusion_reason")),
        "source_workbook": source_workbook,
    }


def _source_file_frame(
    result: Any,
    request: Any,
    *,
    included_rows: Iterable[Mapping[str, object]],
    cancel_check: Callable[[], None] | None,
) -> pd.DataFrame:
    records = tuple(getattr(result, "included_workbooks", ()) or ())
    identities: dict[str, dict[str, object]] = {}
    if records:
        for record in records:
            data = _record_mapping(record)
            path = data.get("path") or data.get("workbook_path")
            if path in (None, ""):
                continue
            relative = _project_relative_identity(path, request)
            identities.setdefault(
                relative,
                {
                    "group_id": _text(
                        data.get("group_id") or getattr(request, "group_id", None)
                    ),
                    "group_label": _text(
                        data.get("group_label") or getattr(request, "group_label", None)
                    ),
                    "group_folder": _text(
                        data.get("group_folder")
                        or getattr(request, "group_folder", None)
                    ),
                    "participant_id": _text(
                        data.get("participant_id") or data.get("subject_id")
                    ),
                    "condition": _text(data.get("condition")),
                    "source_workbook": relative,
                    "_path": Path(path),
                    "_read_sha256": _text(
                        data.get("sha256") or data.get("content_sha256")
                    ),
                    "_read_size_bytes": data.get("size_bytes"),
                    "_read_mtime_ns": data.get("mtime_ns"),
                },
            )
    else:
        for row in included_rows:
            relative = _text(row.get("source_workbook"))
            if not relative:
                continue
            identities.setdefault(
                relative,
                {
                    "group_id": _text(row.get("group_id")),
                    "group_label": _text(row.get("group_label")),
                    "group_folder": _text(row.get("group_folder")),
                    "participant_id": _text(row.get("participant_id")),
                    "condition": _text(row.get("condition")),
                    "source_workbook": relative,
                    "_path": _source_root(request) / Path(relative),
                    "_read_sha256": "",
                    "_read_size_bytes": None,
                    "_read_mtime_ns": None,
                },
            )

    rows: list[dict[str, object]] = []
    for relative, identity in sorted(identities.items()):
        _checkpoint(cancel_check)
        path = Path(identity.pop("_path"))
        read_sha256 = _text(identity.pop("_read_sha256", "")).lower()
        read_size = identity.pop("_read_size_bytes", None)
        read_mtime_ns = identity.pop("_read_mtime_ns", None)
        try:
            stat, digest = _stable_file_fingerprint(
                path,
                cancel_check=cancel_check,
            )
            size = stat.st_size
        except OSError as exc:
            raise SourceProvenanceError(
                f"Could not fingerprint Scalp Maps source workbook {relative}: {exc}"
            ) from exc
        if read_size not in (None, "") and int(read_size) != int(size):
            raise SourceProvenanceError(
                "Scalp Maps source workbook changed after it was read: "
                f"{relative} (size {read_size} -> {size})."
            )
        if read_sha256 and read_sha256 != digest:
            raise SourceProvenanceError(
                "Scalp Maps source workbook changed after it was read: "
                f"{relative} (SHA-256 mismatch)."
            )
        if read_mtime_ns not in (None, "") and int(read_mtime_ns) != int(stat.st_mtime_ns):
            raise SourceProvenanceError(
                "Scalp Maps source workbook changed after it was read: "
                f"{relative} (modification time changed)."
            )
        rows.append(
            {
                **identity,
                "size_bytes": int(size),
                "sha256": digest,
                "mtime_ns": int(stat.st_mtime_ns),
                "fingerprint_boundary": (
                    "verified_against_read_snapshot"
                    if read_sha256
                    else "export_time_snapshot"
                ),
            }
        )
    return pd.DataFrame(
        rows,
        columns=(
            "group_id",
            "group_label",
            "group_folder",
            "participant_id",
            "condition",
            "source_workbook",
            "size_bytes",
            "sha256",
            "mtime_ns",
            "fingerprint_boundary",
        ),
    )


def _provenance_frame(result: Any, request: Any, cohort: pd.DataFrame) -> pd.DataFrame:
    included = cohort[cohort["disposition"].eq("included")] if not cohort.empty else cohort
    participant_n = (
        int(included["participant_id"].replace("", np.nan).nunique())
        if not included.empty
        else 0
    )
    selection_metadata = dict(getattr(result, "selection_metadata", {}) or {})
    provenance = dict(getattr(result, "provenance", {}) or {})
    qc_provenance = _frequency_domain_qc_provenance(request)
    result_qc_provenance = dict(getattr(result, "qc_provenance", {}) or {})
    qc_provenance.update(result_qc_provenance)
    if result_qc_provenance:
        qc_provenance["applied_snapshot_boundary"] = (
            "analysis_time_result_snapshot"
        )
    selection_fingerprint = getattr(result, "selection_fingerprint", None)
    if selection_fingerprint not in (None, ""):
        selection_metadata.setdefault("selection_fingerprint", selection_fingerprint)

    rows: list[dict[str, object]] = [
        {"key": "toolbox_version", "value": config.FPVS_TOOLBOX_VERSION},
        {"key": "group_id", "value": _text(getattr(request, "group_id", None))},
        {"key": "group_label", "value": _text(getattr(request, "group_label", None))},
        {"key": "group_folder", "value": _text(getattr(request, "group_folder", None))},
        {"key": "included_participant_n", "value": participant_n},
        {
            "key": "excluded_participant_condition_n",
            "value": int(cohort["disposition"].eq("excluded").sum()) if not cohort.empty else 0,
        },
        {
            "key": "excluded_participant_n",
            "value": (
                int(
                    cohort.loc[
                        cohort["disposition"].eq("excluded"),
                        "participant_id",
                    ]
                    .replace("", np.nan)
                    .nunique()
                )
                if not cohort.empty
                else 0
            ),
        },
        {
            "key": "frequency_domain_qc_method_version",
            "value": FREQUENCY_DOMAIN_QC_METHOD_VERSION,
        },
        {
            "key": "sensor_coverage_rule",
            "value": (
                f"At least {MIN_RENDER_SENSOR_COUNT} finite, non-collinear "
                "BioSemi64 sensors; missing sensors omitted, never zero-filled."
            ),
        },
    ]
    for prefix, mapping in (
        ("harmonic_selection", selection_metadata),
        ("qc", qc_provenance),
        ("run", provenance),
    ):
        for key, value in sorted(mapping.items(), key=lambda item: str(item[0])):
            rows.append(
                {
                    "key": f"{prefix}.{key}",
                    "value": _excel_value(value),
                }
            )
    return pd.DataFrame(rows, columns=("key", "value"))


def _sensor_coverage_frame(grand_values: pd.DataFrame, request: Any) -> pd.DataFrame:
    columns = (
        "group_id",
        "group_label",
        "condition",
        "metric",
        "map_label",
        "finite_sensor_count",
        "missing_sensor_count",
        "montage_sensor_count",
        "required_minimum",
        "coverage_sufficient",
        "coverage_reason",
    )
    required = {"condition", "metric", "map_label", "electrode", "render_value"}
    if grand_values.empty or not required.issubset(grand_values.columns):
        return pd.DataFrame(columns=columns)
    montage = grand_values
    if "is_montage_electrode" in montage.columns:
        montage = montage[montage["is_montage_electrode"].eq(True)]  # noqa: E712
    group_columns = ["condition", "metric", "map_label"]
    rows: list[dict[str, object]] = []
    for keys, group in montage.groupby(group_columns, dropna=False, sort=True):
        condition, metric, map_label = keys
        numeric = pd.to_numeric(group["render_value"], errors="coerce")
        finite_group = group.loc[np.isfinite(numeric)]
        finite_count = int(
            finite_group["electrode"].astype(str).str.upper().nunique()
        )
        try:
            align_render_values(group)
        except InsufficientSensorCoverageError as exc:
            coverage_sufficient = False
            coverage_reason = exc.reason
        else:
            coverage_sufficient = True
            coverage_reason = "finite, non-collinear montage sensors"
        rows.append(
            {
                "group_id": _text(getattr(request, "group_id", None)),
                "group_label": _text(getattr(request, "group_label", None)),
                "condition": condition,
                "metric": metric,
                "map_label": map_label,
                "finite_sensor_count": finite_count,
                "missing_sensor_count": BIOSEMI64_SENSOR_COUNT - finite_count,
                "montage_sensor_count": BIOSEMI64_SENSOR_COUNT,
                "required_minimum": MIN_RENDER_SENSOR_COUNT,
                "coverage_sufficient": coverage_sufficient,
                "coverage_reason": coverage_reason,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _project_relative_identity(path: object, request: Any) -> str:
    source = Path(str(path)).expanduser().resolve(strict=False)
    root = _source_root(request).expanduser().resolve(strict=False)
    try:
        relative = source.relative_to(root)
    except ValueError as exc:
        raise SourceProvenanceError(
            "Scalp Maps source workbook is outside the active project root: "
            f"{source}"
        ) from exc
    return relative.as_posix()


def _source_root(request: Any) -> Path:
    project_root = getattr(request, "project_root", None)
    return Path(project_root) if project_root not in (None, "") else Path(request.input_root)


def _sha256(
    path: Path,
    *,
    cancel_check: Callable[[], None] | None,
) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            _checkpoint(cancel_check)
            digest.update(chunk)
    return digest.hexdigest()


def _stable_file_fingerprint(
    path: Path,
    *,
    cancel_check: Callable[[], None] | None,
) -> tuple[Any, str]:
    """Hash one stable file snapshot and reject changes during hashing."""

    before = path.stat()
    digest = _sha256(path, cancel_check=cancel_check)
    after = path.stat()
    if (
        before.st_size != after.st_size
        or before.st_mtime_ns != after.st_mtime_ns
    ):
        raise SourceProvenanceError(
            "Scalp Maps source workbook changed while its export fingerprint "
            f"was calculated: {path.name}."
        )
    return after, digest


def _frequency_domain_qc_provenance(request: Any) -> dict[str, object]:
    """Return a compact fingerprinted snapshot of project QC decisions."""

    root = getattr(request, "project_root", None)
    state = load_frequency_domain_qc_state(root)
    auto_participants = _participant_ids(state.get("auto_participant_exclusions"))
    manual_participants = _participant_ids(state.get("manual_participant_exclusions"))
    electrode_exclusions = _participant_electrode_map(
        state.get("auto_participant_electrode_exclusions")
    )
    encoded_state = json.dumps(
        state,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    provenance: dict[str, object] = {
        "schema_version": state.get(
            "schema_version",
            FREQUENCY_DOMAIN_QC_SCHEMA_VERSION,
        ),
        "method_version": state.get(
            "method_version",
            FREQUENCY_DOMAIN_QC_METHOD_VERSION,
        ),
        "state_recorded": bool(state),
        "state_sha256": hashlib.sha256(encoded_state).hexdigest(),
        "applied_snapshot_boundary": "export_time_project_manifest_fallback",
        "excluded_participants": sorted(auto_participants | manual_participants),
        "auto_excluded_participants": sorted(auto_participants),
        "manual_excluded_participants": sorted(manual_participants),
        "manual_exclusion_reasons_by_participant": _participant_reason_map(
            state.get("manual_participant_exclusions")
        ),
        "auto_excluded_electrodes_by_participant": electrode_exclusions,
        "downstream_outputs_stale": bool(
            state.get("downstream_outputs_stale", False)
        ),
        "auto_participant_exclusion_n": _mapping_entry_count(
            state.get("auto_participant_exclusions")
        ),
        "manual_participant_exclusion_n": _mapping_entry_count(
            state.get("manual_participant_exclusions")
        ),
        "auto_participant_electrode_exclusion_n": _mapping_entry_count(
            state.get("auto_participant_electrode_exclusions")
        ),
    }
    for prefix, raw_review in (
        ("last_review", state.get("last_review")),
        ("last_automatic_qc", state.get("last_automatic_qc")),
    ):
        if not isinstance(raw_review, Mapping):
            continue
        for key in (
            "reviewed_at",
            "analysis_fingerprint",
            "decision_fingerprint",
            "review_subject_count",
            "review_required",
            "review_reused",
        ):
            if key in raw_review:
                provenance[f"{prefix}.{key}"] = raw_review[key]
    if isinstance(state.get("thresholds"), Mapping):
        provenance["thresholds"] = state["thresholds"]
    return provenance


def _mapping_entry_count(value: object) -> int:
    if isinstance(value, Mapping):
        return len(value)
    if isinstance(value, (list, tuple)):
        return len(value)
    return 0


def _mapping_entries(value: object) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        candidates = value.values()
    elif isinstance(value, (list, tuple)):
        candidates = value
    else:
        return []
    return [entry for entry in candidates if isinstance(entry, Mapping)]


def _participant_ids(value: object) -> set[str]:
    return {
        participant
        for entry in _mapping_entries(value)
        if (participant := _text(entry.get("participant_id")).strip())
    }


def _participant_reason_map(value: object) -> dict[str, str]:
    return {
        participant: _text(entry.get("reason"))
        for entry in _mapping_entries(value)
        if (participant := _text(entry.get("participant_id")).strip())
    }


def _participant_electrode_map(value: object) -> dict[str, list[str]]:
    mapped: dict[str, set[str]] = {}
    for entry in _mapping_entries(value):
        participant = _text(entry.get("participant_id")).strip()
        electrode = _text(entry.get("electrode")).strip()
        if participant and electrode:
            mapped.setdefault(participant, set()).add(electrode)
    return {
        participant: sorted(electrodes, key=str.casefold)
        for participant, electrodes in sorted(mapped.items())
    }


def _record_mapping(record: Any) -> dict[str, object]:
    if isinstance(record, Mapping):
        return dict(record)
    if is_dataclass(record):
        return asdict(record)
    names = (
        "participant_id",
        "subject_id",
        "condition",
        "group_id",
        "group_label",
        "group_folder",
        "path",
        "workbook_path",
        "disposition",
        "reason",
        "exclusion_reason",
        "sha256",
        "content_sha256",
        "size_bytes",
        "mtime_ns",
    )
    return {name: getattr(record, name) for name in names if hasattr(record, name)}


def _excel_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _checkpoint(cancel_check: Callable[[], None] | None) -> None:
    if cancel_check is not None:
        cancel_check()


__all__ = [
    "COHORT_SHEET",
    "PROVENANCE_SHEET",
    "SENSOR_COVERAGE_SHEET",
    "SOURCE_FILES_SHEET",
    "SourceProvenanceError",
    "SourceWorkbookFrames",
    "build_source_workbook_frames",
]

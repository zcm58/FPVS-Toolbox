"""QC-20 reconciliation of expected cells with current atomic export receipts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

from Main_App.processing.expected_processing_ledger import (
    EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
    EXPECTED_CELL_ACTION_EXCLUDE_RECORDING,
    EXPECTED_CELL_ACTION_PROCESS,
    EXPECTED_PLANNING_STATE_PLANNED,
    ExpectedRecordingConditionPlan,
)


RECORDING_CONDITION_OUTCOME_VERSION = "recording_condition_outcome_v1"
RECORDING_CONDITION_OUTCOME_LEDGER_KEY = "recording_condition_outcomes"
CELL_READY = "ready"
CELL_PARTIALLY_RETAINED = "partially_retained"
CELL_EXCLUDED = "excluded"
CELL_UNAVAILABLE = "unavailable"
CELL_BLOCKED = "blocked"
_CELL_STATES = frozenset(
    {
        CELL_READY,
        CELL_PARTIALLY_RETAINED,
        CELL_EXCLUDED,
        CELL_UNAVAILABLE,
        CELL_BLOCKED,
    }
)


class RecordingConditionOutcomeError(ValueError):
    """Raised when a QC-20 outcome or readiness assertion is invalid."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _artifact_identity(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": digest.hexdigest(),
    }


def _receipt_is_current(value: Mapping[str, Any]) -> bool:
    raw_fingerprint = str(value.get("fingerprint") or "")
    canonical = dict(value)
    canonical.pop("fingerprint", None)
    try:
        return bool(raw_fingerprint) and raw_fingerprint == _fingerprint(canonical)
    except (TypeError, ValueError):
        return False


def _integrity_receipt_is_current(value: Mapping[str, Any]) -> bool:
    raw_fingerprint = str(value.get("fingerprint") or "")
    canonical = dict(value)
    canonical.pop("fingerprint", None)
    try:
        return (
            value.get("status") == "passed"
            and bool(raw_fingerprint)
            and raw_fingerprint == _fingerprint(canonical)
        )
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class RecordingConditionCellOutcome:
    """Current outcome for one canonical expected recording-condition cell."""

    cell_id: str
    processing_id: str
    participant_id: str
    group_id: str | None
    condition_label: str
    condition_code: int
    status: str
    reason_codes: tuple[str, ...]
    planned_occurrence_count: int
    retained_occurrence_count: int
    excluded_occurrence_count: int
    unavailable_occurrence_count: int
    failed_or_unresolved_occurrence_count: int
    contributor_count: int
    expected_cell_fingerprint: str
    export_receipt: Mapping[str, Any] | None

    def __post_init__(self) -> None:
        if self.status not in _CELL_STATES:
            raise RecordingConditionOutcomeError(
                f"Unsupported recording-condition state {self.status!r}."
            )
        counts = (
            self.planned_occurrence_count,
            self.retained_occurrence_count,
            self.excluded_occurrence_count,
            self.unavailable_occurrence_count,
            self.failed_or_unresolved_occurrence_count,
            self.contributor_count,
        )
        if any(value < 0 for value in counts):
            raise RecordingConditionOutcomeError("QC-20 counts cannot be negative.")
        if (
            self.retained_occurrence_count
            + self.excluded_occurrence_count
            + self.unavailable_occurrence_count
            + self.failed_or_unresolved_occurrence_count
            != self.planned_occurrence_count
        ):
            raise RecordingConditionOutcomeError(
                "Occurrence outcomes do not account for the complete expected cell."
            )
        if self.status in {CELL_READY, CELL_PARTIALLY_RETAINED}:
            if self.export_receipt is None or self.contributor_count != 1:
                raise RecordingConditionOutcomeError(
                    "A contributing QC-20 cell requires one validated workbook receipt."
                )
        elif self.contributor_count:
            raise RecordingConditionOutcomeError(
                "A noncontributing QC-20 cell cannot claim a contributor."
            )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": RECORDING_CONDITION_OUTCOME_VERSION,
            "cell_id": self.cell_id,
            "processing_id": self.processing_id,
            "participant_id": self.participant_id,
            "group_id": self.group_id,
            "condition_label": self.condition_label,
            "condition_code": self.condition_code,
            "status": self.status,
            "reason_codes": list(self.reason_codes),
            "planned_occurrence_count": self.planned_occurrence_count,
            "retained_occurrence_count": self.retained_occurrence_count,
            "excluded_occurrence_count": self.excluded_occurrence_count,
            "unavailable_occurrence_count": self.unavailable_occurrence_count,
            "failed_or_unresolved_occurrence_count": (
                self.failed_or_unresolved_occurrence_count
            ),
            "contributor_count": self.contributor_count,
            "expected_cell_fingerprint": self.expected_cell_fingerprint,
            "export_receipt": (
                dict(self.export_receipt)
                if self.export_receipt is not None
                else None
            ),
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
    ) -> "RecordingConditionCellOutcome":
        if value.get("version") != RECORDING_CONDITION_OUTCOME_VERSION:
            raise RecordingConditionOutcomeError(
                "Recording-condition cell outcome version is stale."
            )
        raw_reasons = value.get("reason_codes")
        raw_receipt = value.get("export_receipt")
        if not isinstance(raw_reasons, Sequence) or isinstance(
            raw_reasons,
            (str, bytes),
        ):
            raise RecordingConditionOutcomeError(
                "Recording-condition reason codes must be a list."
            )
        if raw_receipt is not None and not isinstance(raw_receipt, Mapping):
            raise RecordingConditionOutcomeError(
                "Recording-condition export receipt must be an object."
            )
        try:
            result = cls(
                cell_id=str(value["cell_id"]),
                processing_id=str(value["processing_id"]),
                participant_id=str(value["participant_id"]),
                group_id=(
                    str(value["group_id"])
                    if value.get("group_id") is not None
                    else None
                ),
                condition_label=str(value["condition_label"]),
                condition_code=int(value["condition_code"]),
                status=str(value["status"]),
                reason_codes=tuple(str(item) for item in raw_reasons),
                planned_occurrence_count=int(value["planned_occurrence_count"]),
                retained_occurrence_count=int(value["retained_occurrence_count"]),
                excluded_occurrence_count=int(value["excluded_occurrence_count"]),
                unavailable_occurrence_count=int(
                    value["unavailable_occurrence_count"]
                ),
                failed_or_unresolved_occurrence_count=int(
                    value["failed_or_unresolved_occurrence_count"]
                ),
                contributor_count=int(value["contributor_count"]),
                expected_cell_fingerprint=str(
                    value["expected_cell_fingerprint"]
                ),
                export_receipt=(
                    dict(raw_receipt)
                    if isinstance(raw_receipt, Mapping)
                    else None
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordingConditionOutcomeError(
                "Recording-condition cell outcome is malformed."
            ) from exc
        if str(value.get("fingerprint") or "") != result.fingerprint:
            raise RecordingConditionOutcomeError(
                "Recording-condition cell outcome fingerprint is stale."
            )
        return result


@dataclass(frozen=True, slots=True)
class RecordingConditionOutcomeLedger:
    """One complete expected-plan reconciliation and its readiness state."""

    expected_plan_run_id: str
    expected_plan_fingerprint: str
    cells: tuple[RecordingConditionCellOutcome, ...]
    method_version: str = RECORDING_CONDITION_OUTCOME_VERSION

    @property
    def status_counts(self) -> dict[str, int]:
        counts = Counter(cell.status for cell in self.cells)
        return {status: int(counts.get(status, 0)) for status in sorted(_CELL_STATES)}

    @property
    def is_pre_review_ready(self) -> bool:
        return bool(self.cells) and not any(
            cell.status == CELL_BLOCKED for cell in self.cells
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "version": self.method_version,
            "expected_plan_run_id": self.expected_plan_run_id,
            "expected_plan_fingerprint": self.expected_plan_fingerprint,
            "is_pre_review_ready": self.is_pre_review_ready,
            "status_counts": self.status_counts,
            "cells": [cell.to_payload() for cell in self.cells],
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.canonical_payload())

    def to_payload(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload

    @classmethod
    def from_payload(
        cls,
        value: Mapping[str, Any],
    ) -> "RecordingConditionOutcomeLedger":
        if value.get("version") != RECORDING_CONDITION_OUTCOME_VERSION:
            raise RecordingConditionOutcomeError(
                "Recording-condition outcome ledger version is stale."
            )
        if value.get("reconciliation_status", "complete") != "complete":
            raise RecordingConditionOutcomeError(
                str(value.get("reason") or "Recording-condition reconciliation is blocked.")
            )
        raw_cells = value.get("cells")
        if not isinstance(raw_cells, Sequence) or isinstance(
            raw_cells,
            (str, bytes),
        ):
            raise RecordingConditionOutcomeError(
                "Recording-condition outcome cells must be a list."
            )
        try:
            result = cls(
                expected_plan_run_id=str(value["expected_plan_run_id"]),
                expected_plan_fingerprint=str(value["expected_plan_fingerprint"]),
                cells=tuple(
                    RecordingConditionCellOutcome.from_payload(item)
                    for item in raw_cells
                    if isinstance(item, Mapping)
                ),
                method_version=str(value["version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RecordingConditionOutcomeError(
                "Recording-condition outcome ledger is malformed."
            ) from exc
        if len(result.cells) != len(raw_cells):
            raise RecordingConditionOutcomeError(
                "Recording-condition outcome cell is malformed."
            )
        if value.get("status_counts") != result.status_counts:
            raise RecordingConditionOutcomeError(
                "Recording-condition outcome counts are stale."
            )
        if value.get("is_pre_review_ready") is not result.is_pre_review_ready:
            raise RecordingConditionOutcomeError(
                "Recording-condition readiness status is stale."
            )
        if str(value.get("fingerprint") or "") != result.fingerprint:
            raise RecordingConditionOutcomeError(
                "Recording-condition outcome ledger fingerprint is stale."
            )
        return result


def _blocked_cell(
    *,
    recording: object,
    cell: object,
    reasons: Sequence[str],
    receipt: Mapping[str, Any] | None = None,
) -> RecordingConditionCellOutcome:
    planned = int(getattr(cell, "planned_occurrence_count"))
    excluded = int(getattr(cell, "planned_excluded_occurrence_count"))
    unresolved = planned - excluded
    return RecordingConditionCellOutcome(
        cell_id=str(getattr(cell, "cell_id")),
        processing_id=str(getattr(recording, "processing_id")),
        participant_id=str(getattr(recording, "participant_id")),
        group_id=getattr(recording, "group_id"),
        condition_label=str(getattr(cell, "condition_label")),
        condition_code=int(getattr(cell, "condition_code")),
        status=CELL_BLOCKED,
        reason_codes=tuple(dict.fromkeys(str(reason) for reason in reasons)),
        planned_occurrence_count=planned,
        retained_occurrence_count=0,
        excluded_occurrence_count=excluded,
        unavailable_occurrence_count=0,
        failed_or_unresolved_occurrence_count=unresolved,
        contributor_count=0,
        expected_cell_fingerprint=str(getattr(cell, "fingerprint")),
        export_receipt=receipt,
    )


def _validate_written_receipt(
    *,
    plan: ExpectedRecordingConditionPlan,
    recording: object,
    cell: object,
    receipt: Mapping[str, Any],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not _receipt_is_current(receipt):
        reasons.append("export_receipt_fingerprint_mismatch")
    if receipt.get("version") != "recording_condition_export_receipt_v1":
        reasons.append("export_receipt_version_mismatch")
    expected_identity = {
        "run_id": plan.run_id,
        "processing_fingerprint": plan.processing_fingerprint,
        "processing_fingerprint_version": plan.processing_fingerprint_version,
        "recording_id": str(getattr(recording, "processing_id")),
        "condition_label": str(getattr(cell, "condition_label")),
        "protocol_fingerprint": plan.protocol_fingerprint,
    }
    for key, expected in expected_identity.items():
        if str(receipt.get(key) or "") != str(expected):
            reasons.append(f"{key}_mismatch")
    if receipt.get("geometry") != dict(plan.geometry_identity):
        reasons.append("geometry_identity_mismatch")

    expected_path = Path(str(getattr(cell, "expected_workbook"))).resolve()
    if str(receipt.get("path") or "") != str(expected_path):
        reasons.append("workbook_path_mismatch")
    workbook_write = receipt.get("workbook_write")
    if not isinstance(workbook_write, Mapping):
        reasons.append("workbook_write_receipt_missing")
    else:
        if workbook_write.get("version") != "workbook_write_receipt_v1":
            reasons.append("workbook_write_receipt_version_mismatch")
        if workbook_write.get("status") != "written":
            reasons.append("workbook_not_written")
        schema = workbook_write.get("schema_validation")
        if not isinstance(schema, Mapping) or schema.get("status") != "passed":
            reasons.append("workbook_schema_not_validated")
        recorded_artifact = workbook_write.get("artifact")
        actual_artifact = _artifact_identity(expected_path)
        if not isinstance(recorded_artifact, Mapping) or actual_artifact != dict(
            recorded_artifact
        ):
            reasons.append("workbook_artifact_not_current")
        companion = workbook_write.get("spectral_companion")
        if companion is not None:
            from Main_App.io.spectral_data import spectral_companion_identity

            try:
                actual_companion = spectral_companion_identity(expected_path)
                if not isinstance(companion, Mapping) or actual_companion != dict(companion):
                    reasons.append("spectral_companion_not_current")
            except (OSError, ValueError):
                reasons.append("spectral_companion_not_current")

    integrity = receipt.get("finite_integrity")
    if not isinstance(integrity, Sequence) or isinstance(integrity, (str, bytes)):
        reasons.append("finite_integrity_receipts_missing")
    else:
        valid_integrity = [
            item
            for item in integrity
            if isinstance(item, Mapping) and _integrity_receipt_is_current(item)
        ]
        if len(valid_integrity) != len(integrity):
            reasons.append("finite_integrity_receipt_invalid")
        if not any(item.get("value_category") == "bca" for item in valid_integrity):
            reasons.append("computable_bca_integrity_not_validated")
        if not any(
            item.get("value_category") == "retained_eeg"
            for item in valid_integrity
        ):
            reasons.append("retained_signal_integrity_not_validated")
    if not str(receipt.get("spectral_eligibility_fingerprint") or ""):
        reasons.append("spectral_eligibility_identity_missing")
    return tuple(dict.fromkeys(reasons))


def _reconcile_cell(
    *,
    plan: ExpectedRecordingConditionPlan,
    recording: object,
    cell: object,
    receipts: Sequence[Mapping[str, Any]],
) -> RecordingConditionCellOutcome:
    action = str(getattr(cell, "planned_cell_action"))
    planned = int(getattr(cell, "planned_occurrence_count"))
    planned_excluded = int(getattr(cell, "planned_excluded_occurrence_count"))
    expected_fingerprint = str(getattr(cell, "fingerprint"))
    common = {
        "cell_id": str(getattr(cell, "cell_id")),
        "processing_id": str(getattr(recording, "processing_id")),
        "participant_id": str(getattr(recording, "participant_id")),
        "group_id": getattr(recording, "group_id"),
        "condition_label": str(getattr(cell, "condition_label")),
        "condition_code": int(getattr(cell, "condition_code")),
        "planned_occurrence_count": planned,
        "expected_cell_fingerprint": expected_fingerprint,
    }
    if str(getattr(cell, "planning_state")) != EXPECTED_PLANNING_STATE_PLANNED:
        return _blocked_cell(
            recording=recording,
            cell=cell,
            reasons=("legacy_or_unresolved_expected_plan",),
        )
    if action in {
        EXPECTED_CELL_ACTION_EXCLUDE_CONDITION,
        EXPECTED_CELL_ACTION_EXCLUDE_RECORDING,
    }:
        return RecordingConditionCellOutcome(
            **common,
            status=CELL_EXCLUDED,
            reason_codes=("explicit_no_output_exclusion",),
            retained_occurrence_count=0,
            excluded_occurrence_count=planned,
            unavailable_occurrence_count=0,
            failed_or_unresolved_occurrence_count=0,
            contributor_count=0,
            export_receipt=None,
        )
    if action != EXPECTED_CELL_ACTION_PROCESS:
        return _blocked_cell(
            recording=recording,
            cell=cell,
            reasons=("unsupported_expected_cell_action",),
        )

    if planned and planned == planned_excluded:
        return RecordingConditionCellOutcome(
            **common,
            status=CELL_EXCLUDED,
            reason_codes=("explicit_occurrence_exclusions",),
            retained_occurrence_count=0,
            excluded_occurrence_count=planned,
            unavailable_occurrence_count=0,
            failed_or_unresolved_occurrence_count=0,
            contributor_count=0,
            export_receipt=None,
        )

    if len(receipts) != 1:
        return _blocked_cell(
            recording=recording,
            cell=cell,
            reasons=(
                "current_export_receipt_missing"
                if not receipts
                else "duplicate_current_export_receipts",
            ),
        )
    receipt = receipts[0]
    if receipt.get("status") == "unavailable":
        reason = str(receipt.get("reason") or "").strip()
        evidence = receipt.get("evidence")
        if (
            not _receipt_is_current(receipt)
            or not reason
            or not isinstance(evidence, Mapping)
        ):
            return _blocked_cell(
                recording=recording,
                cell=cell,
                reasons=("unavailable_receipt_invalid",),
                receipt=receipt,
            )
        return RecordingConditionCellOutcome(
            **common,
            status=CELL_UNAVAILABLE,
            reason_codes=(reason,),
            retained_occurrence_count=0,
            excluded_occurrence_count=planned_excluded,
            unavailable_occurrence_count=planned - planned_excluded,
            failed_or_unresolved_occurrence_count=0,
            contributor_count=0,
            export_receipt=receipt,
        )
    if receipt.get("status") != "written":
        return _blocked_cell(
            recording=recording,
            cell=cell,
            reasons=(
                str(receipt.get("failure_stage") or "current_export_blocked"),
            ),
            receipt=receipt,
        )

    receipt_problems = list(
        _validate_written_receipt(
            plan=plan,
            recording=recording,
            cell=cell,
            receipt=receipt,
        )
    )
    expected_occurrences = [
        occurrence
        for occurrence in getattr(cell, "occurrences")
        if bool(getattr(occurrence, "plans_workbook_contribution"))
    ]
    raw_retained = receipt.get("retained_occurrences")
    if not isinstance(raw_retained, Sequence) or isinstance(
        raw_retained,
        (str, bytes),
    ):
        receipt_problems.append("retained_occurrence_receipts_missing")
        retained_rows: list[Mapping[str, Any]] = []
    else:
        retained_rows = [
            row for row in raw_retained if isinstance(row, Mapping)
        ]
        if len(retained_rows) != len(raw_retained):
            receipt_problems.append("retained_occurrence_receipt_malformed")
    if int(receipt.get("retained_occurrence_count") or -1) != len(retained_rows):
        receipt_problems.append("retained_occurrence_count_mismatch")
    expected_spans = sorted(
        str(getattr(occurrence, "approved_span_fingerprint"))
        for occurrence in expected_occurrences
    )
    actual_spans = sorted(
        str(row.get("approved_span_fingerprint") or "")
        for row in retained_rows
    )
    if actual_spans != expected_spans:
        receipt_problems.append("retained_occurrence_identity_mismatch")
    if receipt_problems:
        return _blocked_cell(
            recording=recording,
            cell=cell,
            reasons=receipt_problems,
            receipt=receipt,
        )

    retained_count = len(expected_occurrences)
    return RecordingConditionCellOutcome(
        **common,
        status=(
            CELL_PARTIALLY_RETAINED if planned_excluded else CELL_READY
        ),
        reason_codes=(
            ("explicit_occurrence_exclusion",) if planned_excluded else ()
        ),
        retained_occurrence_count=retained_count,
        excluded_occurrence_count=planned_excluded,
        unavailable_occurrence_count=0,
        failed_or_unresolved_occurrence_count=0,
        contributor_count=1,
        export_receipt=receipt,
    )


def reconcile_recording_condition_outputs(
    expected_plan: ExpectedRecordingConditionPlan,
    export_receipts: Sequence[Mapping[str, Any]],
) -> RecordingConditionOutcomeLedger:
    """Account for every expected cell from current receipts and explicit plans."""

    by_cell: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for receipt in export_receipts:
        if not isinstance(receipt, Mapping):
            continue
        key = (
            str(receipt.get("recording_id") or "").casefold(),
            str(receipt.get("condition_label") or "").casefold(),
        )
        by_cell.setdefault(key, []).append(receipt)

    cells: list[RecordingConditionCellOutcome] = []
    expected_keys: set[tuple[str, str]] = set()
    for recording in expected_plan.recordings:
        for cell in recording.cells:
            key = (
                recording.processing_id.casefold(),
                cell.condition_label.casefold(),
            )
            expected_keys.add(key)
            cells.append(
                _reconcile_cell(
                    plan=expected_plan,
                    recording=recording,
                    cell=cell,
                    receipts=by_cell.get(key, ()),
                )
            )

    unexpected = sorted(set(by_cell).difference(expected_keys))
    if unexpected:
        raise RecordingConditionOutcomeError(
            "Export receipts contain recording-condition identities absent from "
            f"the current expected plan: {unexpected!r}."
        )
    return RecordingConditionOutcomeLedger(
        expected_plan_run_id=expected_plan.run_id,
        expected_plan_fingerprint=expected_plan.fingerprint,
        cells=tuple(cells),
    )


def require_pre_review_readiness(
    outcomes: RecordingConditionOutcomeLedger,
) -> None:
    """Block scientific review while any expected cell is unresolved."""

    blocked = [cell for cell in outcomes.cells if cell.status == CELL_BLOCKED]
    if blocked:
        details = []
        has_missing_input = False
        for cell in blocked:
            reason = ", ".join(cell.reason_codes)
            if "condition_input" in cell.reason_codes:
                has_missing_input = True
                if cell.planned_occurrence_count == 0:
                    reason = (
                        "no condition occurrence was planned and no retained "
                        "data reached export"
                    )
                else:
                    receipt = cell.export_receipt or {}
                    reason = str(
                        receipt.get("reason") or "No retained condition data reached export"
                    )
            details.append(f"{cell.processing_id}/{cell.condition_label}: {reason}")
        recovery = (
            " If a condition was intentionally absent or removed, record a "
            "participant-condition exclusion and rerun processing. Otherwise, "
            "check its condition-start triggers and the earlier processing log."
            if has_missing_input
            else ""
        )
        raise RecordingConditionOutcomeError(
            "Frequency review is blocked because current recording-condition "
            f"outputs are incomplete: {'; '.join(details).rstrip('.')}.{recovery}"
        )


def load_recording_condition_outcomes(
    ledger: Mapping[str, Any],
) -> RecordingConditionOutcomeLedger | None:
    """Load the current QC-20 result from an already-read processing ledger."""

    raw = ledger.get(RECORDING_CONDITION_OUTCOME_LEDGER_KEY)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise RecordingConditionOutcomeError(
            "Recording-condition outcome ledger payload must be an object."
        )
    return RecordingConditionOutcomeLedger.from_payload(raw)


__all__ = [
    "CELL_BLOCKED",
    "CELL_EXCLUDED",
    "CELL_PARTIALLY_RETAINED",
    "CELL_READY",
    "CELL_UNAVAILABLE",
    "RECORDING_CONDITION_OUTCOME_LEDGER_KEY",
    "RECORDING_CONDITION_OUTCOME_VERSION",
    "RecordingConditionCellOutcome",
    "RecordingConditionOutcomeError",
    "RecordingConditionOutcomeLedger",
    "reconcile_recording_condition_outputs",
    "load_recording_condition_outcomes",
    "require_pre_review_readiness",
]

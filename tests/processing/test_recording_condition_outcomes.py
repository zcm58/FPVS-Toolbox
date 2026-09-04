from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from Main_App.Shared.post_process import _fingerprinted_export_receipt
from Main_App.Shared.post_process_excel import write_results_workbook
from Main_App.processing.output_integrity import OutputIntegrityReceipt
from Main_App.processing.recording_condition_outcomes import (
    CELL_BLOCKED,
    CELL_EXCLUDED,
    CELL_PARTIALLY_RETAINED,
    CELL_READY,
    RecordingConditionOutcomeError,
    load_recording_condition_outcomes,
    reconcile_recording_condition_outputs,
    require_pre_review_readiness,
)


def _hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True)
class _Occurrence:
    approved_span_fingerprint: str
    plans_workbook_contribution: bool = True


@dataclass(frozen=True)
class _Cell:
    processing_id: str
    condition_label: str
    condition_code: int
    expected_workbook: str
    planned_cell_action: str = "process_condition"
    planning_state: str = "planned"
    occurrences: tuple[_Occurrence, ...] = ()
    fingerprint: str = "cell-fingerprint"

    @property
    def cell_id(self) -> str:
        return f"{self.processing_id}:{self.condition_code}"

    @property
    def planned_occurrence_count(self) -> int:
        return len(self.occurrences)

    @property
    def planned_excluded_occurrence_count(self) -> int:
        return sum(not item.plans_workbook_contribution for item in self.occurrences)


@dataclass(frozen=True)
class _Recording:
    processing_id: str
    participant_id: str
    group_id: str | None
    cells: tuple[_Cell, ...]


@dataclass(frozen=True)
class _Plan:
    run_id: str
    processing_fingerprint: str
    processing_fingerprint_version: str
    protocol_fingerprint: str
    geometry_identity: dict[str, object]
    recordings: tuple[_Recording, ...]
    fingerprint: str = "expected-plan-fingerprint"


def _expected(
    path: Path,
    *,
    occurrences: tuple[_Occurrence, ...] | None = None,
    action: str = "process_condition",
) -> _Plan:
    cell = _Cell(
        processing_id="P01__visit_1",
        condition_label="Faces",
        condition_code=1,
        expected_workbook=str(path.resolve()),
        planned_cell_action=action,
        occurrences=occurrences
        if occurrences is not None
        else (_Occurrence("a" * 64),),
    )
    return _Plan(
        run_id="run-123",
        processing_fingerprint="b" * 64,
        processing_fingerprint_version="processing-v1",
        protocol_fingerprint="c" * 64,
        geometry_identity={"geometry_identity_fingerprint": "d" * 64},
        recordings=(
            _Recording(
                processing_id="P01__visit_1",
                participant_id="P01",
                group_id="control",
                cells=(cell,),
            ),
        ),
    )


def _written_receipt(
    path: Path,
    plan: _Plan,
    *,
    retained: tuple[str, ...] = ("a" * 64,),
) -> dict[str, object]:
    workbook = write_results_workbook(
        str(path),
        {"BCA (uV)": pd.DataFrame({"Electrode": ["Oz"], "0.3000_Hz": [1.0]})},
    )
    source_integrity = OutputIntegrityReceipt(
        stage="retained_signal",
        recording_id="P01__visit_1",
        condition_label="Faces",
        value_category="retained_eeg",
        inspected_value_count=100,
    ).to_payload()
    bca_integrity = OutputIntegrityReceipt(
        stage="computable_bca",
        recording_id="P01__visit_1",
        condition_label="Faces",
        value_category="bca",
        inspected_value_count=1,
        skipped_method_unavailable_target_count=1,
    ).to_payload()
    return _fingerprinted_export_receipt(
        {
            "version": "recording_condition_export_receipt_v1",
            "status": "written",
            "run_id": plan.run_id,
            "processing_fingerprint": plan.processing_fingerprint,
            "processing_fingerprint_version": plan.processing_fingerprint_version,
            "recording_id": "P01__visit_1",
            "participant_id": "P01",
            "session_id": "visit_1",
            "geometry": dict(plan.geometry_identity),
            "source_analysis_span_plan_fingerprint": "source",
            "target_analysis_span_plan_fingerprint": "target",
            "condition_label": "Faces",
            "path": str(path.resolve()),
            "protocol_fingerprint": plan.protocol_fingerprint,
            "spectral_eligibility_fingerprint": "eligibility",
            "expected_data_object_count": 1,
            "contributing_data_object_count": 1,
            "retained_occurrence_count": len(retained),
            "retained_occurrences": [
                {
                    "status": "retained",
                    "approved_span_fingerprint": value,
                }
                for value in retained
            ],
            "finite_integrity": [source_integrity, bca_integrity],
            "workbook_write": workbook,
        }
    )


def test_complete_current_receipt_makes_cell_ready(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path)
    receipt = _written_receipt(path, plan)

    outcomes = reconcile_recording_condition_outputs(plan, [receipt])

    assert outcomes.is_pre_review_ready
    assert outcomes.status_counts[CELL_READY] == 1
    assert outcomes.cells[0].contributor_count == 1
    require_pre_review_readiness(outcomes)


def test_explicit_occurrence_exclusion_rolls_up_as_partially_retained(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(
        path,
        occurrences=(
            _Occurrence("a" * 64),
            _Occurrence("e" * 64, plans_workbook_contribution=False),
        ),
    )
    receipt = _written_receipt(path, plan)

    outcome = reconcile_recording_condition_outputs(plan, [receipt]).cells[0]

    assert outcome.status == CELL_PARTIALLY_RETAINED
    assert outcome.retained_occurrence_count == 1
    assert outcome.excluded_occurrence_count == 1
    assert outcome.failed_or_unresolved_occurrence_count == 0


def test_explicit_whole_cell_exclusion_needs_no_workbook(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path, action="exclude_condition")

    outcome = reconcile_recording_condition_outputs(plan, []).cells[0]

    assert outcome.status == CELL_EXCLUDED
    assert outcome.contributor_count == 0


def test_all_occurrences_explicitly_excluded_need_no_workbook(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(
        path,
        occurrences=(
            _Occurrence("a" * 64, plans_workbook_contribution=False),
            _Occurrence("e" * 64, plans_workbook_contribution=False),
        ),
    )

    outcome = reconcile_recording_condition_outputs(plan, []).cells[0]

    assert outcome.status == CELL_EXCLUDED
    assert outcome.excluded_occurrence_count == 2


def test_missing_receipt_blocks_pre_review(tmp_path):
    plan = _expected(tmp_path / "Faces.xlsx")

    outcomes = reconcile_recording_condition_outputs(plan, [])

    assert outcomes.cells[0].status == CELL_BLOCKED
    assert outcomes.cells[0].reason_codes == ("current_export_receipt_missing",)
    with pytest.raises(RecordingConditionOutcomeError, match="P01__visit_1/Faces"):
        require_pre_review_readiness(outcomes)


def test_changed_workbook_cannot_reuse_prior_write_receipt(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path)
    receipt = _written_receipt(path, plan)
    path.write_bytes(path.read_bytes() + b"externally edited")

    outcome = reconcile_recording_condition_outputs(plan, [receipt]).cells[0]

    assert outcome.status == CELL_BLOCKED
    assert "workbook_artifact_not_current" in outcome.reason_codes


def test_missing_retained_occurrence_cannot_make_partial_average_ready(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(
        path,
        occurrences=(_Occurrence("a" * 64), _Occurrence("e" * 64)),
    )
    receipt = _written_receipt(path, plan, retained=("a" * 64,))

    outcome = reconcile_recording_condition_outputs(plan, [receipt]).cells[0]

    assert outcome.status == CELL_BLOCKED
    assert "retained_occurrence_identity_mismatch" in outcome.reason_codes


def test_tampered_receipt_is_blocked(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path)
    receipt = _written_receipt(path, plan)
    receipt["condition_label"] = "Objects"
    receipt["condition_label"] = "Faces"
    receipt["run_id"] = "other-run"

    outcome = reconcile_recording_condition_outputs(plan, [receipt]).cells[0]

    assert outcome.status == CELL_BLOCKED
    assert "export_receipt_fingerprint_mismatch" in outcome.reason_codes
    assert "run_id_mismatch" in outcome.reason_codes


def test_outcome_payload_is_self_fingerprinted(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path)
    outcomes = reconcile_recording_condition_outputs(
        plan,
        [_written_receipt(path, plan)],
    )

    payload = outcomes.to_payload()
    fingerprint = payload.pop("fingerprint")
    assert fingerprint == _hash(payload)


def test_outcome_payload_round_trips_from_processing_ledger(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path)
    outcomes = reconcile_recording_condition_outputs(
        plan,
        [_written_receipt(path, plan)],
    )

    loaded = load_recording_condition_outcomes(
        {"recording_condition_outcomes": outcomes.to_payload()}
    )

    assert loaded == outcomes


def test_tampered_outcome_payload_is_rejected(tmp_path):
    path = tmp_path / "Faces.xlsx"
    plan = _expected(path)
    payload = reconcile_recording_condition_outputs(
        plan,
        [_written_receipt(path, plan)],
    ).to_payload()
    payload["is_pre_review_ready"] = False

    with pytest.raises(RecordingConditionOutcomeError, match="readiness"):
        load_recording_condition_outcomes(
            {"recording_condition_outcomes": payload}
        )


def test_blocked_reconciliation_envelope_cannot_be_loaded_as_ready():
    with pytest.raises(RecordingConditionOutcomeError, match="could not reconcile"):
        load_recording_condition_outcomes(
            {
                "recording_condition_outcomes": {
                    "version": "recording_condition_outcome_v1",
                    "reconciliation_status": "blocked",
                    "reason": "The current run could not reconcile receipts.",
                }
            }
        )

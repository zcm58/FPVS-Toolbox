from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Main_App.io import BIOSEMI64_CHANNELS, biosemi64_geometry_identity
from Main_App.processing.preprocessing_outcome import build_preprocessing_outcome
from Main_App.processing import frequency_domain_qc
from Main_App.processing.recording_condition_outcomes import (
    CELL_EXCLUDED,
    CELL_READY,
    RecordingConditionCellOutcome,
    RecordingConditionOutcomeLedger,
)
from Main_App.processing.roi_coverage import (
    ROI_COVERAGE_STAGE_FINAL,
    ROI_COVERAGE_STAGE_PRE_REVIEW,
    ROI_VALUE_AVAILABLE,
    ROI_VALUE_UNAVAILABLE,
    RoiCoverageGateError,
    build_final_roi_coverage,
    build_pre_review_roi_coverage,
    load_final_release_receipt,
    load_roi_coverage,
    record_final_release_readiness,
    require_current_final_release,
    require_final_release_readiness,
    require_project_final_release,
)
from Main_App.processing.processing_ledger import save_ledger
from Main_App.processing.roi_settings import build_roi_definition_snapshot


def _write_source(path: Path, *, missing_channel: str | None = None) -> None:
    channels = [channel for channel in BIOSEMI64_CHANNELS if channel != missing_channel]
    path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(
            {
                "Electrode": channels,
                "1.2000_Hz": [float(index + 1) for index in range(len(channels))],
                "2.4000_Hz": [float(index + 2) for index in range(len(channels))],
            }
        ).to_excel(writer, sheet_name="BCA (uV)", index=False)
        pd.DataFrame(
            {
                "Target Frequency (Hz)": [1.2, 2.4],
                "BCA Available": [True, True],
            }
        ).to_excel(writer, sheet_name="Spectral Eligibility", index=False)


def _cell(
    path: Path,
    *,
    recording: str = "P01__visit_1",
    participant: str = "P01",
    condition: str = "Faces",
    status: str = CELL_READY,
) -> RecordingConditionCellOutcome:
    contributing = status == CELL_READY
    artifact = None
    if contributing:
        stat = path.stat()
        artifact = {
            "path": str(path.resolve()),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return RecordingConditionCellOutcome(
        cell_id=f"{recording}:{condition}",
        processing_id=recording,
        participant_id=participant,
        group_id="control",
        condition_label=condition,
        condition_code=1,
        status=status,
        reason_codes=() if contributing else ("explicit_no_output_exclusion",),
        planned_occurrence_count=1,
        retained_occurrence_count=1 if contributing else 0,
        excluded_occurrence_count=0 if contributing else 1,
        unavailable_occurrence_count=0,
        failed_or_unresolved_occurrence_count=0,
        contributor_count=1 if contributing else 0,
        expected_cell_fingerprint="expected-cell",
        export_receipt=(
            {
                "path": str(path.resolve()),
                "geometry": biosemi64_geometry_identity(),
                "workbook_write": {"artifact": artifact},
            }
            if contributing
            else None
        ),
    )


def _outcomes(*cells: RecordingConditionCellOutcome) -> RecordingConditionOutcomeLedger:
    return RecordingConditionOutcomeLedger(
        expected_plan_run_id="run-1",
        expected_plan_fingerprint="expected-plan",
        cells=tuple(cells),
    )


def _processing_ledger(*recordings: str, interpolated: tuple[str, ...] = ()) -> dict:
    outcome = build_preprocessing_outcome(
        processing_status="completed",
        interpolation_status="succeeded" if interpolated else "not_needed",
        interpolation_requested_channels=interpolated,
        interpolation_successful_channels=interpolated,
    )
    return {
        "schema_version": 1,
        "entries": {
            recording: {"preprocessing_outcome": outcome.to_payload()}
            for recording in recordings
        },
    }


@dataclass(frozen=True)
class _Decisions:
    decision_fingerprint: str = "review-fingerprint"
    review_complete: bool = True
    excluded_participants: frozenset[str] = frozenset()
    excluded_recordings: frozenset[str] = frozenset()
    excluded_participant_conditions: dict = None  # type: ignore[assignment]
    excluded_recording_conditions: dict = None  # type: ignore[assignment]
    excluded_electrodes_by_participant_condition: dict = None  # type: ignore[assignment]
    excluded_electrodes_by_recording_condition: dict = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        for name in (
            "excluded_participant_conditions",
            "excluded_recording_conditions",
            "excluded_electrodes_by_participant_condition",
            "excluded_electrodes_by_recording_condition",
        ):
            if getattr(self, name) is None:
                object.__setattr__(self, name, {})

    def to_payload(self) -> dict[str, object]:
        return {
            "decision_fingerprint": self.decision_fingerprint,
            "review_complete": self.review_complete,
            "excluded_recordings": sorted(self.excluded_recordings),
            "excluded_participants": sorted(self.excluded_participants),
            "decision_count": sum(
                len(value)
                for value in (
                    self.excluded_participant_conditions,
                    self.excluded_recording_conditions,
                    self.excluded_electrodes_by_participant_condition,
                    self.excluded_electrodes_by_recording_condition,
                )
            ),
        }


def _snapshot():
    return build_roi_definition_snapshot(
        [("Posterior", ["Oz", "O1"]), ("Frontal", ["Fp1"])]
    )


def test_pre_review_persists_exact_source_and_interpolation_provenance(tmp_path):
    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    outcomes = _outcomes(_cell(source))

    coverage = build_pre_review_roi_coverage(
        SimpleNamespace(project_root=tmp_path),
        outcome_ledger=outcomes,
        processing_ledger=_processing_ledger(
            "P01__visit_1",
            interpolated=("Oz", "O1"),
        ),
        roi_snapshot=_snapshot(),
    )

    assert coverage.stage == ROI_COVERAGE_STAGE_PRE_REVIEW
    posterior = coverage.cells[0].roi_memberships[0]
    assert posterior.status == ROI_VALUE_AVAILABLE
    assert posterior.used_channels == ("Oz", "O1")
    assert posterior.interpolated_channels == ("Oz", "O1")
    assert posterior.all_members_interpolated_warning
    loaded = load_roi_coverage(tmp_path, stage=ROI_COVERAGE_STAGE_PRE_REVIEW)
    assert loaded == coverage


def test_final_coverage_invalidates_only_roi_with_excluded_member_and_all_normalized(
    tmp_path,
):
    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    outcomes = _outcomes(_cell(source))
    pre = build_pre_review_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        processing_ledger=_processing_ledger("P01__visit_1"),
        roi_snapshot=_snapshot(),
    )
    decisions = _Decisions(
        excluded_electrodes_by_recording_condition={
            ("P01__visit_1", "Faces"): frozenset({"Oz"})
        }
    )

    final = build_final_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        frequency_decisions=decisions,
        pre_review_coverage=pre,
    )

    by_roi = {row.roi_name: row for row in final.cells[0].roi_memberships}
    assert by_roi["Posterior"].status == ROI_VALUE_UNAVAILABLE
    assert by_roi["Posterior"].excluded_channels == ("Oz",)
    assert by_roi["Posterior"].used_channels == ()
    assert by_roi["Frontal"].status == ROI_VALUE_AVAILABLE
    assert by_roi["Frontal"].used_channels == ("Fp1",)
    assert final.cells[0].whole_scalp_normalization.status == ROI_VALUE_UNAVAILABLE
    assert final.cells[0].whole_scalp_normalization.used_channels == ()

    receipt = record_final_release_readiness(
        tmp_path,
        outcomes,
        final,
        expected_decision_fingerprint=decisions.decision_fingerprint,
    )
    assert receipt.status == "passed"
    assert load_roi_coverage(tmp_path, stage=ROI_COVERAGE_STAGE_FINAL) == final
    assert load_final_release_receipt(tmp_path) == receipt


def test_outside_roi_exclusion_preserves_complete_raw_roi(tmp_path):
    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    outcomes = _outcomes(_cell(source))
    pre = build_pre_review_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        processing_ledger=_processing_ledger("P01__visit_1"),
        roi_snapshot=_snapshot(),
        persist=False,
    )
    final = build_final_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        frequency_decisions=_Decisions(
            excluded_electrodes_by_recording_condition={
                ("P01__visit_1", "Faces"): frozenset({"Fp1"})
            }
        ),
        pre_review_coverage=pre,
        persist=False,
    )

    posterior = final.cells[0].roi_memberships[0]
    assert posterior.status == ROI_VALUE_AVAILABLE
    assert posterior.used_channels == ("Oz", "O1")
    assert final.cells[0].whole_scalp_normalization.status == ROI_VALUE_UNAVAILABLE


def test_no_output_cell_is_accounted_without_a_workbook(tmp_path):
    outcomes = _outcomes(
        _cell(tmp_path / "absent.xlsx", status=CELL_EXCLUDED),
    )

    pre = build_pre_review_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        processing_ledger={"entries": {}},
        roi_snapshot=_snapshot(),
        persist=False,
    )

    assert pre.cells[0].source_evidence is None
    assert pre.cells[0].roi_memberships == ()


def test_source_prevalidation_rejects_missing_retained_scalp_row(tmp_path):
    source = tmp_path / "Faces.xlsx"
    _write_source(source, missing_channel="Oz")
    outcomes = _outcomes(_cell(source))

    with pytest.raises(RoiCoverageGateError, match="missing retained scalp"):
        build_pre_review_roi_coverage(
            tmp_path,
            outcome_ledger=outcomes,
            processing_ledger=_processing_ledger("P01__visit_1"),
            roi_snapshot=_snapshot(),
            persist=False,
        )


def test_final_release_rejects_a_different_review_fingerprint(tmp_path):
    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    outcomes = _outcomes(_cell(source))
    pre = build_pre_review_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        processing_ledger=_processing_ledger("P01__visit_1"),
        roi_snapshot=_snapshot(),
        persist=False,
    )
    final = build_final_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        frequency_decisions=_Decisions(),
        pre_review_coverage=pre,
        persist=False,
    )

    with pytest.raises(RoiCoverageGateError, match="stale QC-03/QC-17"):
        require_final_release_readiness(
            outcomes,
            final,
            expected_decision_fingerprint="different-review",
        )


@pytest.mark.parametrize("artifact", ["workbook", "condition_companion", "spectral_companion"])
@pytest.mark.parametrize("failure", ["missing", "changed"])
def test_current_final_release_rejects_a_changed_source_workbook(tmp_path, artifact, failure):
    from Main_App.Shared.post_process_excel import write_results_workbook

    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    write_receipt = None
    if artifact != "workbook":
        frames = pd.read_excel(source, sheet_name=None)
        if artifact == "spectral_companion":
            frames["FullFFT Amplitude (uV)"] = pd.DataFrame({
                "Electrode": list(BIOSEMI64_CHANNELS),
                "0.0000_Hz": [1.0] * len(BIOSEMI64_CHANNELS),
            })
        write_receipt = write_results_workbook(str(source), frames)
    cell = _cell(source)
    if write_receipt is not None:
        cell.export_receipt["workbook_write"].update(write_receipt)
    outcomes = _outcomes(cell)
    save_ledger(
        tmp_path,
        {"recording_condition_outcomes": outcomes.to_payload()},
    )
    pre = build_pre_review_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        processing_ledger=_processing_ledger("P01__visit_1"),
        roi_snapshot=_snapshot(),
    )
    final = build_final_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        frequency_decisions=_Decisions(),
        pre_review_coverage=pre,
    )
    record_final_release_readiness(
        tmp_path,
        outcomes,
        final,
        expected_decision_fingerprint="review-fingerprint",
    )

    assert require_current_final_release(
        tmp_path,
        expected_decision_fingerprint="review-fingerprint",
    )[1] == final

    target = source if artifact == "workbook" else source.with_name(write_receipt[artifact]["path"])
    if failure == "missing":
        target.unlink()
    else:
        target.write_bytes(target.read_bytes() + b"changed after release")
    message = "workbook changed or is missing" if artifact == "workbook" else "data companion"
    with pytest.raises(RoiCoverageGateError, match=message):
        require_current_final_release(
            tmp_path,
            expected_decision_fingerprint="review-fingerprint",
        )


def test_project_final_release_rejects_changed_decision_payload_with_same_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "Faces.xlsx"
    _write_source(source)
    outcomes = _outcomes(_cell(source))
    save_ledger(
        tmp_path,
        {"recording_condition_outcomes": outcomes.to_payload()},
    )
    pre = build_pre_review_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        processing_ledger=_processing_ledger("P01__visit_1"),
        roi_snapshot=_snapshot(),
    )
    decisions = _Decisions()
    final = build_final_roi_coverage(
        tmp_path,
        outcome_ledger=outcomes,
        frequency_decisions=decisions,
        pre_review_coverage=pre,
    )
    record_final_release_readiness(
        tmp_path,
        outcomes,
        final,
        expected_decision_fingerprint=decisions.decision_fingerprint,
    )
    changed_payload = decisions.to_payload()
    changed_payload["decision_count"] = 1
    monkeypatch.setattr(
        frequency_domain_qc,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: SimpleNamespace(
            decision_fingerprint=decisions.decision_fingerprint,
            to_payload=lambda: changed_payload,
        ),
    )

    with pytest.raises(RoiCoverageGateError, match="decision evidence changed"):
        require_project_final_release(tmp_path)

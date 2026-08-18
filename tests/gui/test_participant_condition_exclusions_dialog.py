from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt

from Main_App.gui.participant_condition_exclusions_dialog import (
    ParticipantConditionExclusionsDialog,
)
from Main_App.processing.full_fft_grid_qc import (
    FullFftGridAudit,
    FullFftGridObservation,
)


def _observation(
    participant_id: str,
    condition: str,
    *,
    cycles: int,
    recording_id: str | None = None,
    session_id: str | None = None,
    session_label: str | None = None,
    visit_index: int | None = None,
) -> FullFftGridObservation:
    duration = cycles / 1.2
    return FullFftGridObservation(
        participant_id=participant_id,
        condition=condition,
        path=Path(f"{participant_id}_{condition}_Results.xlsx"),
        group_id="control",
        group_label="Control",
        oddball_cycles=cycles,
        duration_s=duration,
        bin_spacing_hz=1.0 / duration,
        frequency_column_count=cycles * 10,
        issue=None,
        already_excluded=False,
        recording_id=recording_id,
        session_id=session_id,
        session_label=session_label,
        visit_index=visit_index,
    )


def test_participant_condition_exclusions_dialog_prechecks_grid_mismatch(qtbot) -> None:
    audit = FullFftGridAudit(
        observations=(
            _observation("P1", "Faces", cycles=144),
            _observation("P2", "Faces", cycles=144),
            _observation("P4", "Negative Valence", cycles=21),
        ),
        reference_oddball_cycles=144,
        reference_support=2,
        reference_total=3,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert dialog.table.item(0, 6).checkState() == Qt.Unchecked
    assert dialog.table.item(1, 6).checkState() == Qt.Unchecked
    assert dialog.table.item(2, 6).checkState() == Qt.Checked
    assert dialog.excluded_participant_conditions() == {
        "P4": ["Negative Valence"]
    }


def test_participant_condition_exclusions_dialog_does_not_guess_tied_grid(
    qtbot,
) -> None:
    audit = FullFftGridAudit(
        observations=(
            _observation("P1", "Faces", cycles=144),
            _observation("P2", "Faces", cycles=21),
        ),
        reference_oddball_cycles=None,
        reference_support=1,
        reference_total=2,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert audit.has_unresolved_grid_conflict is True
    assert dialog.table.item(0, 6).checkState() == Qt.Unchecked
    assert dialog.table.item(1, 6).checkState() == Qt.Unchecked


def test_participant_condition_exclusions_dialog_preserves_unobserved_entries(
    qtbot,
) -> None:
    audit = FullFftGridAudit(
        observations=(_observation("P1", "Faces", cycles=144),),
        reference_oddball_cycles=None,
        reference_support=0,
        reference_total=1,
    )
    dialog = ParticipantConditionExclusionsDialog(
        audit,
        {
            "P1": ["Faces"],
            "P9": ["Negative Valence"],
        },
    )
    qtbot.addWidget(dialog)
    dialog.table.item(0, 6).setCheckState(Qt.Unchecked)

    assert dialog.excluded_participant_conditions() == {
        "P9": ["Negative Valence"]
    }


def test_recording_aware_condition_dialog_keeps_visit_scope_explicit(qtbot) -> None:
    observation = _observation(
        "P1",
        "Faces",
        cycles=21,
        recording_id="P1__follicular",
        session_id="follicular",
        session_label="Follicular",
        visit_index=2,
    )
    audit = FullFftGridAudit(
        observations=(observation,),
        reference_oddball_cycles=144,
        reference_support=2,
        reference_total=3,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert dialog.table.horizontalHeaderItem(1).text() == "Recording"
    assert dialog.table.horizontalHeaderItem(2).text() == "Session / phase-at-visit"
    assert dialog.table.item(0, 10).checkState() == Qt.Checked
    scope = dialog.table.cellWidget(0, 9)
    assert scope.currentData() == "recording"
    assert dialog.excluded_recording_conditions() == {
        "P1__follicular": ["Faces"]
    }
    assert dialog.excluded_participant_conditions() == {}

    scope.setCurrentIndex(scope.findData("participant"))
    assert dialog.excluded_recording_conditions() == {}
    assert dialog.excluded_participant_conditions() == {"P1": ["Faces"]}

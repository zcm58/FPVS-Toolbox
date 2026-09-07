from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel

from Main_App.gui.participant_condition_exclusions_dialog import (
    ParticipantConditionExclusionsDialog,
)
from Main_App.processing.full_fft_grid_qc import (
    FullFftGridAudit,
    FullFftGridObservation,
)
from Main_App.processing.missing_condition_outputs import MissingConditionOutput


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
        oddball_frequency_hz=1.2,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert dialog.table.item(0, dialog._exclude_column).checkState() == Qt.Unchecked
    assert dialog.table.item(1, dialog._exclude_column).checkState() == Qt.Unchecked
    assert dialog.table.item(2, dialog._exclude_column).checkState() == Qt.Checked
    assert dialog.view_combo.currentData() == "attention"
    assert dialog.table.isRowHidden(0)
    assert dialog.table.isRowHidden(1)
    assert not dialog.table.isRowHidden(2)
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
        oddball_frequency_hz=1.2,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert audit.has_unresolved_grid_conflict is True
    assert dialog.table.item(0, dialog._exclude_column).checkState() == Qt.Unchecked
    assert dialog.table.item(1, dialog._exclude_column).checkState() == Qt.Unchecked


def test_participant_condition_exclusions_dialog_preserves_unobserved_entries(
    qtbot,
) -> None:
    audit = FullFftGridAudit(
        observations=(_observation("P1", "Faces", cycles=144),),
        reference_oddball_cycles=None,
        reference_support=0,
        reference_total=1,
        oddball_frequency_hz=1.2,
    )
    dialog = ParticipantConditionExclusionsDialog(
        audit,
        {
            "P1": ["Faces"],
            "P9": ["Negative Valence"],
        },
    )
    qtbot.addWidget(dialog)
    dialog.table.item(0, dialog._exclude_column).setCheckState(Qt.Unchecked)

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
        oddball_frequency_hz=1.2,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert dialog.table.horizontalHeaderItem(0).text() == "Recording"
    assert dialog.table.columnCount() == 5
    assert dialog.table.item(0, dialog._exclude_column).checkState() == Qt.Checked
    scope = dialog._scope_controls[0]
    assert scope.currentData() == "recording"
    assert [scope.itemText(index) for index in range(scope.count())] == [
        "This recording", "Participant (all visits)"
    ]
    evidence = dialog.evidence_view.toPlainText()
    assert "P1__follicular" in evidence
    assert "Follicular" in evidence
    assert str(observation.path) in evidence
    assert dialog.excluded_recording_conditions() == {
        "P1__follicular": ["Faces"]
    }
    assert dialog.excluded_participant_conditions() == {}

    scope.setCurrentIndex(scope.findData("participant"))
    assert dialog.excluded_recording_conditions() == {}
    assert dialog.excluded_participant_conditions() == {"P1": ["Faces"]}


def test_missing_condition_stays_unchecked_and_explains_next_step(qtbot) -> None:
    missing = MissingConditionOutput(
        participant_id="P9",
        condition="Neutral Angry",
        group_id="control",
        group_label="Control",
        outcome_status="blocked",
    )
    audit = FullFftGridAudit(
        observations=(_observation("P1", "Faces", cycles=144),),
        reference_oddball_cycles=144,
        reference_support=1,
        reference_total=1,
        oddball_frequency_hz=1.2,
        missing_condition_outputs=(missing,),
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)

    assert dialog.view_combo.currentData() == "attention"
    assert not dialog.table.isRowHidden(0)
    assert dialog.table.isRowHidden(1)
    assert dialog.table.item(0, dialog._exclude_column).checkState() == Qt.Unchecked
    assert dialog.excluded_participant_conditions() == {}
    guidance = " ".join(
        [label.text() for label in dialog.findChildren(QLabel)]
        + [dialog.evidence_view.toPlainText()]
    ).casefold()
    assert "start marker" in guidance
    assert "rerun processing" in guidance
    assert "neutral angry" in dialog.evidence_view.toPlainText().casefold()


def test_search_and_views_preserve_hidden_checks_and_unobserved_exclusions(qtbot) -> None:
    audit = FullFftGridAudit(
        observations=(
            _observation("P1", "Faces", cycles=144),
            _observation("P4", "Negative Valence", cycles=21),
        ),
        reference_oddball_cycles=144,
        reference_support=1,
        reference_total=2,
        oddball_frequency_hz=1.2,
    )
    dialog = ParticipantConditionExclusionsDialog(
        audit, {"P9": ["Unavailable Condition"]}
    )
    qtbot.addWidget(dialog)
    dialog.view_combo.setCurrentIndex(dialog.view_combo.findData("all"))
    dialog.search_edit.setText("P1")
    assert not dialog.table.isRowHidden(0)
    assert dialog.table.isRowHidden(1)
    assert dialog.table.item(1, dialog._exclude_column).checkState() == Qt.Checked

    dialog.table.item(0, dialog._exclude_column).setCheckState(Qt.Checked)
    dialog.search_edit.clear()
    assert not dialog.table.isRowHidden(0)
    assert not dialog.table.isRowHidden(1)
    dialog.search_edit.setText("negative valence")
    assert dialog.table.isRowHidden(0)
    assert not dialog.table.isRowHidden(1)
    dialog.search_edit.clear()
    dialog.view_combo.setCurrentIndex(dialog.view_combo.findData("excluded"))
    dialog.table.item(0, dialog._exclude_column).setCheckState(Qt.Unchecked)
    dialog._filter_rows()
    assert dialog.table.isRowHidden(0)
    assert not dialog.table.isRowHidden(1)
    assert dialog.excluded_participant_conditions() == {
        "P4": ["Negative Valence"],
        "P9": ["Unavailable Condition"],
    }


def test_recording_scope_survives_search_and_cancel_does_not_edit_inputs(qtbot) -> None:
    observations = (
        _observation(
            "P1", "Faces", cycles=144, recording_id="P1__first",
            session_id="first", session_label="First phase", visit_index=1,
        ),
        _observation(
            "P1", "Faces", cycles=144, recording_id="P1__second",
            session_id="second", session_label="Second phase", visit_index=2,
        ),
    )
    audit = FullFftGridAudit(
        observations=observations,
        reference_oddball_cycles=144,
        reference_support=2,
        reference_total=2,
        oddball_frequency_hz=1.2,
    )
    participant_exclusions = {"P9": ["Faces"]}
    recording_exclusions = {"P1__first": ["Faces"], "P9__first": ["Faces"]}
    dialog = ParticipantConditionExclusionsDialog(
        audit, participant_exclusions,
        excluded_recording_conditions=recording_exclusions,
    )
    qtbot.addWidget(dialog)
    dialog.view_combo.setCurrentIndex(dialog.view_combo.findData("all"))
    dialog.table.selectRow(0)
    dialog._scope_controls[0].setCurrentIndex(
        dialog._scope_controls[0].findData("participant")
    )
    dialog.search_edit.setText("Second phase")
    assert dialog.table.isRowHidden(0)
    assert not dialog.table.isRowHidden(1)
    assert "Second phase" in dialog.evidence_view.toPlainText()
    assert dialog._scope_for_row(0) == "participant"
    assert dialog._scope_for_row(1) == "recording"
    assert dialog.excluded_participant_conditions() == {
        "P1": ["Faces"], "P9": ["Faces"]
    }
    assert dialog.excluded_recording_conditions() == {"P9__first": ["Faces"]}
    dialog.reject()
    assert dialog.result() == QDialog.Rejected
    assert participant_exclusions == {"P9": ["Faces"]}
    assert recording_exclusions == {
        "P1__first": ["Faces"], "P9__first": ["Faces"]
    }


@pytest.mark.parametrize("size", [(1280, 900), (1000, 650)])
def test_crop_review_compact_layout_fits_without_horizontal_scroll(qtbot, size) -> None:
    audit = FullFftGridAudit(
        observations=tuple(
            _observation(
                f"P{index}", "Neutral Angry", cycles=144,
                recording_id=f"P{index}__a_long_recording_identifier",
                session_label="A descriptive phase-at-visit label", visit_index=2,
            )
            for index in range(20)
        ),
        reference_oddball_cycles=144,
        reference_support=20,
        reference_total=20,
        oddball_frequency_hz=1.2,
    )
    dialog = ParticipantConditionExclusionsDialog(audit)
    qtbot.addWidget(dialog)
    dialog.resize(*size)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.table.viewport().width() > 0)

    assert dialog.view_combo.currentData() == "all"
    assert dialog.width() == size[0]
    assert dialog.height() == size[1]
    assert dialog.table.columnCount() == 5
    assert [dialog.table.horizontalHeaderItem(index).text() for index in range(5)] == [
        "Recording", "Condition", "FFT length", "Status", "Exclude"
    ]
    assert dialog.table.horizontalScrollBar().maximum() == 0
    assert dialog.table.horizontalHeader().length() <= dialog.table.viewport().width()
    assert all(dialog.table.rowHeight(row) == 32 for row in range(20))
    assert dialog.evidence_view.isVisible()
    assert dialog.decision_stack.isVisible()

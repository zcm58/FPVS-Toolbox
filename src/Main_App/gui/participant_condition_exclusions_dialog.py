"""Editor for participant-condition exclusions from downstream workbook analyses."""

from __future__ import annotations

from typing import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from Main_App.processing.full_fft_grid_qc import (
    FullFftGridAudit,
    FullFftGridObservation,
)
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
)

_SCOPE_RECORDING = "recording"
_SCOPE_PARTICIPANT = "participant"


class ParticipantConditionExclusionsDialog(QDialog):
    """Review FullFFT grids and choose downstream participant-condition omissions."""

    def __init__(
        self,
        audit: FullFftGridAudit,
        excluded_participant_conditions: Mapping[str, Sequence[str]] | None = None,
        parent=None,
        *,
        excluded_recording_conditions: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        super().__init__(parent)
        self._audit = audit
        self._observations = audit.observations
        self.setWindowTitle("Participant-Condition FFT Crop Exclusions")
        self.setObjectName("participant_condition_exclusions_dialog")
        self._recording_aware = any(
            observation.recording_id for observation in self._observations
        )
        self.resize(1180 if self._recording_aware else 1040, 620 if self._recording_aware else 560)

        existing = normalize_manual_excluded_participant_conditions(
            excluded_participant_conditions
        )
        self._existing = existing
        existing_recordings = normalize_manual_excluded_recording_conditions(
            excluded_recording_conditions
        )
        self._existing_recordings = existing_recordings
        existing_pairs = {
            (participant.casefold(), condition.casefold())
            for participant, conditions in existing.items()
            for condition in conditions
        }
        existing_recording_pairs = {
            (recording.casefold(), condition.casefold())
            for recording, conditions in existing_recordings.items()
            for condition in conditions
        }
        candidate_pairs = {
            observation.pair_key for observation in audit.review_candidates
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        reference_text = (
            f"The project reference is {audit.reference_duration_s:g} s "
            f"({audit.reference_oddball_cycles} oddball cycles), supported by "
            f"{audit.reference_support} of {audit.reference_total} active workbooks."
            if audit.reference_duration_s is not None
            and audit.reference_oddball_cycles is not None
            else (
                "No strict-majority FFT grid could be established. All grids are "
                "shown, and FPVS Toolbox will not guess which valid grid is expected."
            )
        )
        prompt = QLabel(
            (
                "Checked rows can omit only this recording-condition or the same "
                "participant-condition across all visits. Session/phase-at-visit "
                "and visit order remain distinct. Raw BDF files and generated "
                f"workbooks remain unchanged for audit. {reference_text}"
                if self._recording_aware
                else "Checked participant-condition pairs are omitted from shared downstream "
                "workbook analyses. Raw BDF files and generated workbooks remain unchanged "
                f"for audit. {reference_text}"
            ),
            self,
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        if self._recording_aware:
            headers = (
                "Participant",
                "Recording",
                "Session / phase-at-visit",
                "Visit",
                "Group",
                "Condition",
                "Usable FFT crop",
                "Grid status",
                "Source workbook",
                "Scope",
                "Exclude downstream",
            )
            self._scope_column = 9
            self._exclude_column = 10
        else:
            headers = (
                "PID",
                "Group",
                "Condition",
                "Usable FFT crop",
                "Grid status",
                "Source workbook",
                "Exclude downstream",
            )
            self._scope_column = None
            self._exclude_column = 6
        self.table = QTableWidget(len(self._observations), len(headers), self)
        self.table.setObjectName("participant_condition_exclusions_table")
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in range(len(headers)):
            header.setSectionResizeMode(
                column,
                QHeaderView.Stretch
                if (
                    column in {2, 4, 5}
                    if not self._recording_aware
                    else column in {2, 7, 8}
                )
                else QHeaderView.ResizeToContents,
            )

        for row, observation in enumerate(self._observations):
            if self._recording_aware:
                values = (
                    observation.participant_id,
                    observation.recording_id or "Not registered",
                    observation.session_label or observation.session_id or "—",
                    str(observation.visit_index or "—"),
                    observation.group_label or observation.group_id or "Ungrouped",
                    observation.condition,
                    _observed_grid_text(observation),
                    _grid_status_text(observation, audit),
                    observation.path.name,
                )
            else:
                values = (
                    observation.participant_id,
                    observation.group_label or observation.group_id or "Ungrouped",
                    observation.condition,
                    _observed_grid_text(observation),
                    _grid_status_text(observation, audit),
                    observation.path.name,
                )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
            exclude_item = QTableWidgetItem()
            exclude_item.setFlags(
                (exclude_item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable
            )
            participant_pair = observation.participant_pair_key
            recording_pair = observation.recording_pair_key
            should_check = participant_pair in existing_pairs or (
                recording_pair is not None
                and recording_pair in existing_recording_pairs
            ) or observation.pair_key in candidate_pairs
            exclude_item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
            self.table.setItem(row, self._exclude_column, exclude_item)
            if self._recording_aware and self._scope_column is not None:
                scope = QComboBox(self.table)
                scope.setObjectName(f"condition_exclusion_scope_{row}")
                scope.addItem("This recording", _SCOPE_RECORDING)
                scope.addItem("Participant (all visits)", _SCOPE_PARTICIPANT)
                selected_scope = (
                    _SCOPE_PARTICIPANT
                    if participant_pair in existing_pairs
                    else _SCOPE_RECORDING
                )
                scope.setCurrentIndex(max(0, scope.findData(selected_scope)))
                scope.setToolTip(
                    "Choose whether this condition exclusion applies only to the "
                    "listed recording or to the participant across all visits."
                )
                self.table.setCellWidget(row, self._scope_column, scope)

        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.setObjectName("participant_condition_exclusions_actions")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def excluded_participant_conditions(self) -> dict[str, list[str]]:
        observed_pairs = {
            observation.participant_pair_key for observation in self._observations
        }
        values: dict[str, list[str]] = {
            participant: [
                condition
                for condition in conditions
                if (participant.casefold(), condition.casefold())
                not in observed_pairs
            ]
            for participant, conditions in self._existing.items()
        }
        for row, observation in enumerate(self._observations):
            exclude_item = self.table.item(row, self._exclude_column)
            if (
                exclude_item is not None
                and exclude_item.checkState() == Qt.Checked
                and self._scope_for_row(row) == _SCOPE_PARTICIPANT
            ):
                values.setdefault(observation.participant_id, []).append(
                    observation.condition
                )
        return normalize_manual_excluded_participant_conditions(values)

    def excluded_recording_conditions(self) -> dict[str, list[str]]:
        """Return recording-scoped condition omissions from the review table."""

        observed_pairs = {
            pair
            for observation in self._observations
            if (pair := observation.recording_pair_key) is not None
        }
        values: dict[str, list[str]] = {
            recording: [
                condition
                for condition in conditions
                if (recording.casefold(), condition.casefold()) not in observed_pairs
            ]
            for recording, conditions in self._existing_recordings.items()
        }
        if not self._recording_aware:
            return normalize_manual_excluded_recording_conditions(values)
        for row, observation in enumerate(self._observations):
            exclude_item = self.table.item(row, self._exclude_column)
            if (
                observation.recording_id
                and exclude_item is not None
                and exclude_item.checkState() == Qt.Checked
                and self._scope_for_row(row) == _SCOPE_RECORDING
            ):
                values.setdefault(observation.recording_id, []).append(
                    observation.condition
                )
        return normalize_manual_excluded_recording_conditions(values)

    def _scope_for_row(self, row: int) -> str:
        if not self._recording_aware or self._scope_column is None:
            return _SCOPE_PARTICIPANT
        widget = self.table.cellWidget(row, self._scope_column)
        if isinstance(widget, QComboBox):
            return str(widget.currentData() or _SCOPE_RECORDING)
        return _SCOPE_RECORDING


def _observed_grid_text(observation: FullFftGridObservation) -> str:
    if observation.duration_s is None or observation.oddball_cycles is None:
        return "Unavailable"
    return (
        f"{observation.duration_s:g} s "
        f"({observation.oddball_cycles} oddball cycles)"
    )


def _grid_status_text(
    observation: FullFftGridObservation,
    audit: FullFftGridAudit,
) -> str:
    if observation.issue:
        return observation.issue
    if audit.reference_oddball_cycles is None:
        return "Valid grid; no strict-majority reference"
    if observation.oddball_cycles == audit.reference_oddball_cycles:
        return "Matches project reference"
    return "Different from project reference"


__all__ = ["ParticipantConditionExclusionsDialog"]

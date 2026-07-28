"""Editor for participant-condition exclusions from downstream workbook analyses."""

from __future__ import annotations

from typing import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
)


class ParticipantConditionExclusionsDialog(QDialog):
    """Review FullFFT grids and choose downstream participant-condition omissions."""

    def __init__(
        self,
        audit: FullFftGridAudit,
        excluded_participant_conditions: Mapping[str, Sequence[str]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._audit = audit
        self._observations = audit.observations
        self.setWindowTitle("Participant-Condition FFT Crop Exclusions")
        self.setObjectName("participant_condition_exclusions_dialog")
        self.resize(1040, 560)

        existing = normalize_manual_excluded_participant_conditions(
            excluded_participant_conditions
        )
        self._existing = existing
        existing_pairs = {
            (participant.casefold(), condition.casefold())
            for participant, conditions in existing.items()
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
            "Checked participant-condition pairs are omitted from shared downstream "
            "workbook analyses. Raw BDF files and generated workbooks remain unchanged "
            f"for audit. {reference_text}",
            self,
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        headers = (
            "PID",
            "Group",
            "Condition",
            "Usable FFT crop",
            "Grid status",
            "Source workbook",
            "Exclude downstream",
        )
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
                QHeaderView.Stretch if column in {2, 4, 5} else QHeaderView.ResizeToContents,
            )

        for row, observation in enumerate(self._observations):
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
            should_check = (
                observation.pair_key in existing_pairs
                or observation.pair_key in candidate_pairs
            )
            exclude_item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
            self.table.setItem(row, 6, exclude_item)

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
            observation.pair_key for observation in self._observations
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
            exclude_item = self.table.item(row, 6)
            if exclude_item is not None and exclude_item.checkState() == Qt.Checked:
                values.setdefault(observation.participant_id, []).append(
                    observation.condition
                )
        return normalize_manual_excluded_participant_conditions(values)


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

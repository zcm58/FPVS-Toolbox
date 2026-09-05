"""Analysis-only repeated-session recording exclusion editor."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QSignalBlocker, Qt, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    StatusBanner,
    SurfaceSize,
    make_action_button,
)

from .models import AnalysisRecordingExclusion, RecordingChoice


class RecordingExclusionsDialog(AppDialog):
    """Collect explicit project-specific exclusions with optional explanations."""

    def __init__(
        self,
        recordings: Sequence[RecordingChoice],
        exclusions: Sequence[AnalysisRecordingExclusion] = (),
        parent=None,
    ) -> None:
        super().__init__(
            "Repeated-Session Analysis Exclusions",
            parent,
            size=SurfaceSize(1040, 620, min_width=820, min_height=480),
        )
        self.setObjectName("free_harmonic_recording_exclusions_dialog")
        self._recordings = tuple(recordings)
        self._row_recording_ids: dict[int, str] = {}
        existing = {item.recording_id.casefold(): item for item in exclusions}

        note = StatusBanner(
            "These exclusions persist for this project's future Free Harmonic "
            "Clustering batches until changed. They do not change project QC, "
            "processing, or source files. Reasons are optional.",
            self,
            variant="info",
        )
        note.setObjectName("free_harmonic_exclusion_scope_note")
        note.setWordWrap(True)
        self.root_layout.addWidget(note)

        headers = (
            "Exclude",
            "Participant",
            "Recording",
            "Session / phase-at-visit",
            "Visit",
            "Group",
            "Reason (optional)",
        )
        self.table = QTableWidget(len(self._recordings), len(headers), self)
        self.table.setObjectName("free_harmonic_recording_exclusions_table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in range(len(headers)):
            mode = (
                QHeaderView.Stretch
                if column == len(headers) - 1
                else QHeaderView.ResizeToContents
            )
            header.setSectionResizeMode(column, mode)

        for row, recording in enumerate(self._recordings):
            previous = existing.get(recording.recording_id.casefold())
            include = QTableWidgetItem("")
            include.setFlags(
                (include.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable
            )
            include.setCheckState(Qt.Checked if previous is not None else Qt.Unchecked)
            self.table.setItem(row, 0, include)
            values = (
                recording.participant_id,
                recording.recording_id,
                recording.session_label,
                str(recording.visit_index),
                recording.group_label,
            )
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
            reason = QTableWidgetItem("" if previous is None else previous.reason)
            reason.setToolTip(
                "Optional explanation (for example, "
                "predeclared outlier or recording-specific artifact)."
            )
            self.table.setItem(row, 6, reason)
            self._row_recording_ids[row] = recording.recording_id

        self.root_layout.addWidget(self.table, 1)

        self.validation_status = StatusBanner(
            "No analysis-specific recording exclusions selected.",
            self,
            variant="info",
        )
        self.validation_status.setObjectName(
            "free_harmonic_exclusion_validation_status"
        )
        self.root_layout.addWidget(self.validation_status)

        self.clear_button = make_action_button(
            "Clear selections",
            compact=True,
            parent=self,
        )
        self.cancel_button = make_action_button(
            "Cancel",
            variant="tertiary",
            parent=self,
        )
        self.apply_button = make_action_button(
            "Use exclusions",
            variant="primary",
            parent=self,
        )
        self.clear_button.setObjectName("free_harmonic_exclusions_clear_button")
        self.cancel_button.setObjectName("free_harmonic_exclusions_cancel_button")
        self.apply_button.setObjectName("free_harmonic_exclusions_apply_button")
        actions = ActionRow(self, alignment=Qt.AlignLeft)
        actions.setObjectName("free_harmonic_exclusions_actions")
        actions.row_layout.insertWidget(0, self.clear_button)
        actions.row_layout.insertStretch(1, 1)
        actions.add_button(self.cancel_button)
        actions.add_button(self.apply_button)
        self.root_layout.addWidget(actions)

        self.table.itemChanged.connect(self._update_validation)
        self.clear_button.clicked.connect(self._clear_selections)
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._accept_if_valid)
        self._update_validation()

    def exclusions(self) -> tuple[AnalysisRecordingExclusion, ...]:
        """Return checked, valid exclusions in canonical table order."""

        exclusions: list[AnalysisRecordingExclusion] = []
        for row, recording_id in self._row_recording_ids.items():
            include = self.table.item(row, 0)
            if include is None or include.checkState() != Qt.Checked:
                continue
            reason_item = self.table.item(row, 6)
            reason = "" if reason_item is None else reason_item.text().strip()
            exclusions.append(AnalysisRecordingExclusion(recording_id, reason))
        return tuple(exclusions)

    def _validation_error(self) -> str | None:
        selected = 0
        for row in self._row_recording_ids:
            include = self.table.item(row, 0)
            if include is None or include.checkState() != Qt.Checked:
                continue
            selected += 1
        if selected == len(self._recordings) and selected:
            return "At least one recording must remain available for analysis."
        return None

    @Slot()
    def _update_validation(self) -> None:
        error = self._validation_error()
        if error:
            self.validation_status.set_variant("error")
            self.validation_status.set_text(error)
            self.apply_button.setEnabled(False)
            return
        selected = sum(
            1
            for row in self._row_recording_ids
            if self.table.item(row, 0) is not None
            and self.table.item(row, 0).checkState() == Qt.Checked
        )
        self.validation_status.set_variant("info")
        self.validation_status.set_text(
            "No analysis-specific recording exclusions selected."
            if selected == 0
            else f"{selected} recording exclusion(s) are ready for the batch audit."
        )
        self.apply_button.setEnabled(True)

    @Slot()
    def _clear_selections(self) -> None:
        with QSignalBlocker(self.table):
            for row in self._row_recording_ids:
                include = self.table.item(row, 0)
                reason = self.table.item(row, 6)
                if include is not None:
                    include.setCheckState(Qt.Unchecked)
                if reason is not None:
                    reason.setText("")
        self._update_validation()

    @Slot()
    def _accept_if_valid(self) -> None:
        self._update_validation()
        if self._validation_error() is None:
            self.accept()


__all__ = ["RecordingExclusionsDialog"]

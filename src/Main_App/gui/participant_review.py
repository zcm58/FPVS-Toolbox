"""Participant review dialog for processing manifest updates."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QComboBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from Main_App.gui.components import (
    AppDialog,
    SurfaceSize,
    make_action_button,
    make_action_row,
)
from Main_App.processing.processing_controller import ParticipantReviewRow


class ParticipantReviewDialog(AppDialog):
    """Modal review table shown before new participant metadata is saved."""

    def __init__(
        self,
        rows: Sequence[ParticipantReviewRow],
        parent: QWidget | None = None,
        *,
        additions_only: bool = False,
    ) -> None:
        repeated = any(row.recording_id for row in rows)
        super().__init__(
            "Add EEG Recordings" if additions_only else "Review Recordings" if repeated else "Review Participants",
            parent,
            size=SurfaceSize(
                width=1100 if repeated else 860,
                height=500 if repeated else 460,
                min_width=820 if repeated else 720,
                min_height=360,
            ),
        )
        self.rows = list(rows)
        self.repeated_session = repeated
        project = getattr(parent, "currentProject", None)
        maps = getattr(getattr(project, "frequency_protocol", None), "condition_trigger_maps", None)
        self._trigger_maps = maps if additions_only else None
        self._map_selectors = []

        if additions_only:
            source_text = (
                "Group and session come from each file's configured source folder. "
                if repeated else "Group comes from the project's configured raw folder. "
            )
            summary_text = (
                "New EEG recordings were found in this project's configured raw folders. "
                "Review the proposed assignments below. " + source_text
                + "Add Files and Continue saves these additions before planning processing. "
                "Existing analysis outputs will need processing to finish before reuse. "
                "Cancel leaves the project registry unchanged and stops this processing request."
            )
        else:
            summary_text = (
                "FPVS Toolbox found participant and session-recording assignments "
                "that need review before processing. Each recording remains linked "
                "to the same participant for paired analysis."
                if repeated
                else "FPVS Toolbox found participant assignments that need review "
                "before processing."
            )
        summary = QLabel(summary_text)
        summary.setWordWrap(True)
        summary.setObjectName("participant_review_summary")
        self.root_layout.addWidget(summary)

        headers = (
            [
                "Project ID",
                "Source study",
                "Original ID",
                "Group",
                "Session",
                "Visit",
                "Recording",
                "Raw File",
                "Status",
            ]
            if repeated
            else ["Project ID", "Source study", "Original ID", "Group", "Raw File", "Status"]
        )
        if self._trigger_maps is not None:
            headers.append("Source map")
        self.table = QTableWidget(len(self.rows), len(headers), self)
        self.table.setObjectName("participant_review_table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        for column in range(len(headers)):
            mode = (
                QHeaderView.Stretch
                if headers[column] == "Raw File"
                else QHeaderView.ResizeToContents
            )
            self.table.horizontalHeader().setSectionResizeMode(column, mode)

        for row_index, row in enumerate(self.rows):
            values = (
                (
                    row.participant_id,
                    getattr(row, "source_study_id", "") or "",
                    getattr(row, "source_participant_id", "") or "",
                    row.group_label,
                    row.session_label or row.session_id or "",
                    str(row.visit_index or ""),
                    row.recording_id or "",
                    str(row.raw_file),
                    row.status,
                )
                if repeated
                else (
                    row.participant_id,
                    getattr(row, "source_study_id", "") or "",
                    getattr(row, "source_participant_id", "") or "",
                    row.group_label,
                    str(row.raw_file),
                    row.status,
                )
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if additions_only and headers[col_index] == "Raw File":
                    item.setText(row.raw_file.name)
                elif additions_only and headers[col_index] == "Group":
                    item.setToolTip(f"{row.group_label} (group_id: {row.group_id})")
                elif additions_only and headers[col_index] == "Session":
                    item.setToolTip(f"{row.session_label or row.session_id} (session_id: {row.session_id})")
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, col_index, item)
            if self._trigger_maps is not None:
                selector = QComboBox(self.table)
                selector.addItem("Choose source map…", "")
                for profile in self._trigger_maps.profiles:
                    selector.addItem(profile.label, profile.profile_id)
                proposed = dict(self._trigger_maps.registration_group_defaults).get(row.group_id)
                if proposed:
                    selector.setCurrentIndex(selector.findData(proposed))
                self._map_selectors.append((row.recording_id or row.participant_id, selector))
                self.table.setCellWidget(row_index, len(headers) - 1, selector)
        self.root_layout.addWidget(self.table)

        self.continue_button = make_action_button(
            (
                "Add Files and Continue" if additions_only else
                "Register Participants and Recordings"
                if repeated
                else "Add Participants and Continue"
            ),
            variant="primary",
        )
        self.continue_button.setObjectName("participant_review_continue_button")
        self.cancel_button = make_action_button("Cancel", variant="secondary")
        self.cancel_button.setObjectName("participant_review_cancel_button")
        if additions_only:
            self.cancel_button.setDefault(True)
        self.root_layout.addWidget(
            make_action_row(
                (self.cancel_button, self.continue_button),
                parent=self,
            )
        )

        has_conflict = any("conflict" in row.status.casefold() for row in self.rows)
        self.continue_button.setEnabled(not has_conflict)
        for _recording_id, selector in self._map_selectors:
            selector.currentIndexChanged.connect(self._refresh_assignments)
        self._refresh_assignments()
        self.continue_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

    def _refresh_assignments(self):
        has_conflict = any("conflict" in row.status.casefold() for row in self.rows)
        assigned = all(selector.currentData() for _identity, selector in self._map_selectors)
        self.continue_button.setEnabled(not has_conflict and assigned)

    def trigger_map_assignments(self):
        return {identity: selector.currentData() for identity, selector in self._map_selectors}


def review_participants_for_processing(
    parent: QWidget | None,
    rows: Sequence[ParticipantReviewRow],
) -> bool:
    if not rows:
        return True
    dialog = ParticipantReviewDialog(rows, parent)
    return dialog.exec() == QDialog.Accepted


def review_recording_additions_for_processing(
    parent: QWidget | None,
    rows: Sequence[ParticipantReviewRow],
) -> bool:
    """Confirm proposed additions only; the caller owns revalidation and saving."""
    if not rows:
        return True
    dialog = ParticipantReviewDialog(rows, parent, additions_only=True)
    accepted = dialog.exec() == QDialog.Accepted
    if parent is not None:
        parent._reviewed_trigger_map_assignments = dialog.trigger_map_assignments() if accepted else {}
    return accepted

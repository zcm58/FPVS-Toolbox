"""Participant review dialog for processing manifest updates."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
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
    ) -> None:
        repeated = any(row.recording_id for row in rows)
        super().__init__(
            "Review Recordings" if repeated else "Review Participants",
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

        summary = QLabel(
            (
                "FPVS Toolbox found participant and session-recording assignments "
                "that need review before processing. Each recording remains linked "
                "to the same participant for paired analysis."
                if repeated
                else "FPVS Toolbox found participant assignments that need review "
                "before processing."
            )
        )
        summary.setWordWrap(True)
        self.root_layout.addWidget(summary)

        headers = (
            [
                "Participant",
                "Group",
                "Session",
                "Visit",
                "Recording",
                "Raw File",
                "Status",
            ]
            if repeated
            else ["Participant", "Group", "Raw File", "Status"]
        )
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
                    row.group_label,
                    str(row.raw_file),
                    row.status,
                )
            )
            for col_index, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row_index, col_index, item)
        self.root_layout.addWidget(self.table)

        self.continue_button = make_action_button(
            (
                "Register Participants and Recordings"
                if repeated
                else "Add Participants and Continue"
            ),
            variant="primary",
        )
        self.continue_button.setObjectName("participant_review_continue_button")
        self.cancel_button = make_action_button("Cancel", variant="secondary")
        self.cancel_button.setObjectName("participant_review_cancel_button")
        self.root_layout.addWidget(
            make_action_row(
                (self.cancel_button, self.continue_button),
                parent=self,
            )
        )

        has_conflict = any("conflict" in row.status.casefold() for row in self.rows)
        self.continue_button.setEnabled(not has_conflict)
        self.continue_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)


def review_participants_for_processing(
    parent: QWidget | None,
    rows: Sequence[ParticipantReviewRow],
) -> bool:
    if not rows:
        return True
    dialog = ParticipantReviewDialog(rows, parent)
    return dialog.exec() == QDialog.Accepted

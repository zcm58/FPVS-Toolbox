from __future__ import annotations

from typing import Sequence

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

from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participants,
    normalize_manual_excluded_recordings,
)
from Main_App.gui.recording_qc_identity import QcRecordingIdentity


class ManualParticipantExclusionsDialog(QDialog):
    """Modal editor for participant-level manual processing exclusions."""

    def __init__(
        self,
        participant_ids: Sequence[str],
        excluded_participants: Sequence[str] | None = None,
        parent=None,
        *,
        recording_rows: Sequence[QcRecordingIdentity] = (),
        excluded_recordings: Sequence[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual Participant Exclusions")
        self.setObjectName("manual_participant_exclusions_dialog")
        self._recording_rows = tuple(recording_rows)
        self._recording_mode = bool(self._recording_rows)
        self._participant_table_rows: dict[int, str] = {}
        self._recording_table_rows: dict[int, str] = {}

        excluded = normalize_manual_excluded_participants(excluded_participants)
        excluded_lookup = {pid.casefold() for pid in excluded}
        normalized_recordings = normalize_manual_excluded_recordings(
            excluded_recordings
        )
        self._existing_excluded_recordings = normalized_recordings
        excluded_recording_lookup = {
            recording_id.casefold() for recording_id in normalized_recordings
        }
        pids = _ordered_participant_ids(
            (*participant_ids, *(row.participant_id for row in self._recording_rows)),
            excluded,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        prompt = QLabel(
            (
                "Choose participant-wide exclusions for every visit or exclude only "
                "one recording. Missing declared visits are shown for coverage and "
                "cannot be selected. Raw BDF files are not modified."
                if self._recording_mode
                else "Select participants to exclude from processing. Raw BDF files are not modified."
            ),
            self,
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        if self._recording_mode:
            self.resize(1080, 560)
            headers = (
                "Participant",
                "Recording",
                "Session / phase-at-visit",
                "Visit",
                "Group",
                "Scope",
                "Exclude from processing",
            )
            row_count = len(pids) + len(self._recording_rows)
        else:
            self.resize(520, 420)
            headers = ("PID", "Exclude from processing")
            row_count = len(pids)
        self.table = QTableWidget(row_count, len(headers), self)
        self.table.setObjectName("manual_participant_exclusions_table")
        self.table.setHorizontalHeaderLabels(list(headers))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        for column in range(len(headers)):
            header.setSectionResizeMode(
                column,
                QHeaderView.Stretch
                if column == len(headers) - 1
                else QHeaderView.ResizeToContents,
            )

        if self._recording_mode:
            group_by_participant = {
                row.participant_id.casefold(): row.group_label
                for row in self._recording_rows
            }
            table_row = 0
            for pid in pids:
                _set_read_only_values(
                    self.table,
                    table_row,
                    (
                        pid,
                        "All recordings",
                        "All sessions",
                        "—",
                        group_by_participant.get(pid.casefold(), "Unknown"),
                        "Participant-wide (all visits)",
                    ),
                )
                self.table.setItem(
                    table_row,
                    6,
                    _check_item(pid.casefold() in excluded_lookup),
                )
                self._participant_table_rows[table_row] = pid
                table_row += 1

            for identity in self._recording_rows:
                recording_id = str(identity.recording_id or "").strip()
                _set_read_only_values(
                    self.table,
                    table_row,
                    (
                        identity.participant_id,
                        recording_id or identity.coverage_status,
                        identity.session_label or identity.session_id or "—",
                        str(identity.visit_index or "—"),
                        identity.group_label,
                        "Single recording" if recording_id else "Coverage only",
                    ),
                )
                exclude_item = _check_item(
                    bool(recording_id)
                    and recording_id.casefold() in excluded_recording_lookup
                )
                if not recording_id:
                    exclude_item.setFlags(exclude_item.flags() & ~Qt.ItemIsEnabled)
                    exclude_item.setToolTip(
                        "No recording is registered for this declared visit."
                    )
                self.table.setItem(table_row, 6, exclude_item)
                if recording_id:
                    self._recording_table_rows[table_row] = recording_id
                table_row += 1
        else:
            for row, pid in enumerate(pids):
                pid_item = QTableWidgetItem(pid)
                pid_item.setFlags(pid_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 0, pid_item)
                self.table.setItem(
                    row,
                    1,
                    _check_item(pid.casefold() in excluded_lookup),
                )

        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.setObjectName("manual_participant_exclusions_actions")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def excluded_participants(self) -> list[str]:
        """Return checked participant IDs from the table."""
        if self._recording_mode:
            values = [
                pid
                for row, pid in self._participant_table_rows.items()
                if self.table.item(row, 6) is not None
                and self.table.item(row, 6).checkState() == Qt.Checked
            ]
            return normalize_manual_excluded_participants(values)

        values: list[str] = []
        for row in range(self.table.rowCount()):
            pid_item = self.table.item(row, 0)
            exclude_item = self.table.item(row, 1)
            pid = pid_item.text().strip() if pid_item else ""
            if not pid or exclude_item is None:
                continue
            if exclude_item.checkState() == Qt.Checked:
                values.append(pid)
        return normalize_manual_excluded_participants(values)

    def excluded_recordings(self) -> list[str]:
        """Return checked recording IDs while preserving unseen saved entries."""

        if not self._recording_mode:
            return list(self._existing_excluded_recordings)
        visible = {
            recording_id.casefold() for recording_id in self._recording_table_rows.values()
        }
        values = [
            recording_id
            for recording_id in self._existing_excluded_recordings
            if recording_id.casefold() not in visible
        ]
        values.extend(
            recording_id
            for row, recording_id in self._recording_table_rows.items()
            if self.table.item(row, 6) is not None
            and self.table.item(row, 6).checkState() == Qt.Checked
        )
        return normalize_manual_excluded_recordings(values)


def _check_item(checked: bool) -> QTableWidgetItem:
    item = QTableWidgetItem("")
    item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
    return item


def _set_read_only_values(
    table: QTableWidget,
    row: int,
    values: Sequence[object],
) -> None:
    for column, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, column, item)


def _ordered_participant_ids(
    participant_ids: Sequence[str],
    excluded_participants: Sequence[str],
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for source in (participant_ids, excluded_participants):
        for raw_pid in source:
            pid = str(raw_pid or "").strip()
            if not pid:
                continue
            key = pid.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(pid)
    return sorted(ordered, key=_participant_sort_key)


def _participant_sort_key(value: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in value if not ch.isdigit()).casefold()
    digits = "".join(ch for ch in value if ch.isdigit())
    number = int(digits) if digits else -1
    return prefix, number, value.casefold()


__all__ = ["ManualParticipantExclusionsDialog"]

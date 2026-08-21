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

from Main_App.processing.removed_electrode_detection import (
    normalize_manual_removed_electrodes_map,
    parse_electrode_list,
)
from Main_App.gui.recording_qc_identity import (
    QcRecordingIdentity,
    ordered_participant_ids,
)


class ManualRemovedElectrodesDialog(QDialog):
    """Modal editor for participant-level manually removed electrode metadata."""

    def __init__(
        self,
        participant_ids: Sequence[str],
        manual_removed_electrodes: Mapping[str, Sequence[str]] | None = None,
        parent=None,
        *,
        prompt_text: str | None = None,
        accept_label: str | None = None,
        recording_rows: Sequence[QcRecordingIdentity] = (),
        manual_removed_electrodes_by_recording: Mapping[
            str, Sequence[str]
        ] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual Removed Electrodes")
        self.setObjectName("manual_removed_electrodes_dialog")
        self._recording_rows = tuple(recording_rows)
        self._recording_mode = bool(self._recording_rows)
        self._participant_table_rows: dict[int, str] = {}
        self._recording_table_rows: dict[int, str] = {}

        normalized = normalize_manual_removed_electrodes_map(
            dict(manual_removed_electrodes or {})
        )
        normalized_by_recording = normalize_manual_removed_electrodes_map(
            dict(manual_removed_electrodes_by_recording or {})
        )
        self._existing_by_recording = normalized_by_recording
        recording_participants = tuple(
            row.participant_id for row in self._recording_rows
        )
        pids = ordered_participant_ids(
            (*participant_ids, *recording_participants),
            normalized,
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        prompt = QLabel(
            prompt_text
            or (
                "Enter electrodes that were physically removed before recording. "
                "Participant-wide entries are fallbacks for every visit. Check a "
                "recording-specific override to replace that fallback for one recording."
                if self._recording_mode
                else "Enter electrodes that were physically removed before recording."
            ),
            self,
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        if self._recording_mode:
            self.resize(1120, 560)
            headers = (
                "Participant",
                "Recording",
                "Session / phase-at-visit",
                "Visit",
                "Group",
                "Scope",
                "Removed electrodes",
            )
            row_count = len(pids) + len(self._recording_rows)
        else:
            self.resize(620, 420)
            headers = ("PID", "Removed electrodes")
            row_count = len(pids)
        self.table = QTableWidget(row_count, len(headers), self)
        self.table.setObjectName("manual_removed_electrodes_table")
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
                values = (
                    pid,
                    "All recordings",
                    "All sessions",
                    "—",
                    group_by_participant.get(pid.casefold(), "Unknown"),
                    "Participant-wide fallback",
                )
                _set_read_only_values(self.table, table_row, values)
                electrodes = normalized.get(pid) or _casefold_lookup(normalized, pid)
                self.table.setItem(
                    table_row,
                    6,
                    QTableWidgetItem(", ".join(electrodes)),
                )
                self._participant_table_rows[table_row] = pid
                table_row += 1

            for identity in self._recording_rows:
                recording_id = str(identity.recording_id or "").strip()
                values = (
                    identity.participant_id,
                    recording_id or identity.coverage_status,
                    identity.session_label or identity.session_id or "—",
                    str(identity.visit_index or "—"),
                    identity.group_label,
                )
                _set_read_only_values(self.table, table_row, values)
                if not recording_id:
                    _set_read_only_values(
                        self.table,
                        table_row,
                        ("Coverage only", ""),
                        start_column=5,
                    )
                    for column in range(len(headers)):
                        item = self.table.item(table_row, column)
                        if item is not None:
                            item.setToolTip(
                                "This declared visit has no registered recording; "
                                "no recording-specific setting will be created."
                            )
                    table_row += 1
                    continue

                stored_key = _casefold_key(normalized_by_recording, recording_id)
                scope_item = QTableWidgetItem("Recording-specific override")
                scope_item.setFlags(
                    (scope_item.flags() | Qt.ItemIsUserCheckable)
                    & ~Qt.ItemIsEditable
                )
                scope_item.setCheckState(
                    Qt.Checked if stored_key is not None else Qt.Unchecked
                )
                scope_item.setToolTip(
                    "Checked: this value replaces the participant-wide fallback "
                    "for this recording. Unchecked: the fallback applies."
                )
                self.table.setItem(table_row, 5, scope_item)
                electrodes = (
                    normalized_by_recording.get(stored_key, [])
                    if stored_key is not None
                    else []
                )
                self.table.setItem(
                    table_row,
                    6,
                    QTableWidgetItem(", ".join(electrodes)),
                )
                self._recording_table_rows[table_row] = recording_id
                table_row += 1
        else:
            for row, pid in enumerate(pids):
                pid_item = QTableWidgetItem(pid)
                pid_item.setFlags(pid_item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, 0, pid_item)
                electrodes = normalized.get(pid) or _casefold_lookup(normalized, pid)
                self.table.setItem(row, 1, QTableWidgetItem(", ".join(electrodes)))

        self.table.resizeRowsToContents()
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.setObjectName("manual_removed_electrodes_actions")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        if accept_label:
            accept_button = buttons.button(QDialogButtonBox.Save)
            if accept_button is not None:
                accept_button.setText(accept_label)
        layout.addWidget(buttons)

    def manual_removed_electrodes(self) -> dict[str, list[str]]:
        """Return all PID entries from the editable table."""
        if self._recording_mode:
            values: dict[str, list[str]] = {}
            for row, pid in self._participant_table_rows.items():
                electrodes_item = self.table.item(row, 6)
                values[pid] = parse_electrode_list(
                    electrodes_item.text() if electrodes_item else ""
                )
            return normalize_manual_removed_electrodes_map(values)

        values: dict[str, list[str]] = {}
        for row in range(self.table.rowCount()):
            pid_item = self.table.item(row, 0)
            electrodes_item = self.table.item(row, 1)
            pid = pid_item.text().strip() if pid_item else ""
            if not pid:
                continue
            electrodes = parse_electrode_list(
                electrodes_item.text() if electrodes_item else ""
            )
            values[pid] = electrodes
        return values

    def manual_removed_electrodes_by_recording(self) -> dict[str, list[str]]:
        """Return explicit recording overrides while preserving unseen entries."""

        if not self._recording_mode:
            return dict(self._existing_by_recording)
        visible_keys = {
            recording_id.casefold() for recording_id in self._recording_table_rows.values()
        }
        values = {
            recording_id: list(electrodes)
            for recording_id, electrodes in self._existing_by_recording.items()
            if recording_id.casefold() not in visible_keys
        }
        for row, recording_id in self._recording_table_rows.items():
            scope_item = self.table.item(row, 5)
            if scope_item is None or scope_item.checkState() != Qt.Checked:
                continue
            electrodes_item = self.table.item(row, 6)
            values[recording_id] = parse_electrode_list(
                electrodes_item.text() if electrodes_item else ""
            )
        return normalize_manual_removed_electrodes_map(values)


def _casefold_lookup(
    values: Mapping[str, Sequence[str]],
    key: str,
) -> list[str]:
    key_folded = key.casefold()
    for candidate, electrodes in values.items():
        if candidate.casefold() == key_folded:
            return list(electrodes)
    return []


def _casefold_key(values: Mapping[str, object], key: str) -> str | None:
    folded = key.casefold()
    for candidate in values:
        if candidate.casefold() == folded:
            return candidate
    return None


def _set_read_only_values(
    table: QTableWidget,
    row: int,
    values: Sequence[object],
    *,
    start_column: int = 0,
) -> None:
    for offset, value in enumerate(values):
        item = QTableWidgetItem(str(value))
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        table.setItem(row, start_column + offset, item)


__all__ = ["ManualRemovedElectrodesDialog"]

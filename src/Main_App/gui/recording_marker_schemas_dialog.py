"""Explicit recording trigger-schema assignment with project-only draft state."""

from __future__ import annotations

from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QLineEdit, QTableWidget, QTableWidgetItem

from Main_App.gui.components import AppDialog, StatusBanner, SurfaceSize, make_action_button, make_action_row
from Main_App.projects import FrequencyProtocolError, validate_protocol_condition_codes
from .recording_marker_schemas import validate_recording_marker_assignments


class RecordingMarkerSchemasDialog(AppDialog):
    def __init__(self, identities, protocol, onset_codes, assignments=(), parent=None):
        super().__init__("Recording-specific trigger schemas", parent, size=SurfaceSize(1100, 680, min_width=840, min_height=460))
        self.setObjectName("recording_marker_schemas_dialog")
        self._identities = tuple(identities)
        self._protocol = protocol
        self._onsets = tuple(sorted({int(value) for value in onset_codes}))
        self._project_codes = tuple(protocol.condition_oddball_marker_codes) or tuple((code, protocol.oddball_marker_code) for code in self._onsets)
        self._saved = {str(recording_id).casefold(): tuple((int(onset), int(marker)) for onset, marker in codes) for recording_id, codes in assignments}
        registered = {row.recording_id.casefold() for row in self._identities}
        obsolete = set(self._saved) - registered
        self._note = "Choose each recording's trigger schema. New recordings stay unassigned until you choose. Changes are saved only when you save Settings."
        if obsolete:
            self._note += f" Applying removes {len(obsolete)} saved entries that are no longer registered."
        self.status = StatusBanner(self._note, self, variant="info")
        self.status.setWordWrap(True)
        self.root_layout.addWidget(self.status)
        self.table = QTableWidget(len(self._identities), 5, self)
        self.table.setObjectName("recording_marker_schemas_table")
        self.table.setHorizontalHeaderLabels(("Recording", "Participant / visit", "Trigger schema", "Shared marker", "Assigned oddball markers"))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        for column in range(5):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch if column in (1, 4) else QHeaderView.ResizeToContents)
        self._selectors = []
        self._shared_edits = []
        for row, identity in enumerate(self._identities):
            self.table.setItem(row, 0, QTableWidgetItem(identity.recording_id))
            self.table.setItem(row, 1, QTableWidgetItem(identity.label))
            selector = QComboBox(self.table)
            selector.addItem("Choose schema…", "unassigned")
            selector.addItem("Project condition markers", "project")
            selector.addItem("Shared marker", "shared")
            shared = QLineEdit(str(protocol.oddball_marker_code), self.table)
            shared.setMaximumWidth(90)
            saved = self._saved.get(identity.recording_id.casefold())
            if saved is not None:
                if saved == self._project_codes:
                    selector.setCurrentIndex(1)
                elif len({marker for _, marker in saved}) == 1 and {onset for onset, _ in saved} == set(self._onsets):
                    selector.setCurrentIndex(2)
                    shared.setText(str(saved[0][1]))
                else:
                    selector.addItem("Custom saved markers", "custom")
                    selector.setCurrentIndex(3)
            self._selectors.append(selector)
            self._shared_edits.append(shared)
            self.table.setCellWidget(row, 2, selector)
            self.table.setCellWidget(row, 3, shared)
            self.table.setItem(row, 4, QTableWidgetItem())
        self.root_layout.addWidget(self.table, 1)
        self.select_all_button = make_action_button("Select all", compact=True, parent=self)
        self.project_button = make_action_button("Selection: project markers", compact=True, parent=self)
        self.shared_button = make_action_button(f"Selection: shared {protocol.oddball_marker_code}", compact=True, parent=self)
        self.root_layout.addWidget(make_action_row((self.select_all_button, self.project_button, self.shared_button), parent=self))
        self.cancel_button = make_action_button("Cancel", parent=self)
        self.apply_button = make_action_button("Apply schemas", variant="primary", parent=self)
        self.root_layout.addWidget(make_action_row((self.cancel_button, self.apply_button), parent=self))
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self.accept)
        self.select_all_button.clicked.connect(self.table.selectAll)
        self.project_button.clicked.connect(lambda: self._assign_selected("project"))
        self.shared_button.clicked.connect(lambda: self._assign_selected("shared"))
        for selector, edit in zip(self._selectors, self._shared_edits, strict=True):
            selector.currentIndexChanged.connect(self._refresh)
            edit.textChanged.connect(self._refresh)
        self._refresh()

    def _assign_selected(self, schema):
        for index in self.table.selectionModel().selectedRows():
            row = index.row()
            if schema == "shared":
                self._shared_edits[row].setText(str(self._protocol.oddball_marker_code))
            self._selectors[row].setCurrentIndex(self._selectors[row].findData(schema))
        self._refresh()

    def _row_codes(self, row):
        schema = self._selectors[row].currentData()
        if schema == "project":
            return self._project_codes
        if schema == "shared":
            return tuple((onset, self._shared_edits[row].text()) for onset in self._onsets)
        if schema == "custom":
            return self._saved[self._identities[row].recording_id.casefold()]
        return ()

    def marker_codes(self):
        assignments = tuple((identity.recording_id, self._row_codes(row)) for row, identity in enumerate(self._identities) if self._selectors[row].currentData() != "unassigned")
        validate_recording_marker_assignments(self._identities, assignments)
        protocol = self._protocol.with_recording_oddball_marker_codes(assignments)
        validate_protocol_condition_codes(protocol, self._onsets)
        return protocol.recording_oddball_marker_codes

    def _refresh(self, *_args):
        for row in range(len(self._identities)):
            self._shared_edits[row].setEnabled(self._selectors[row].currentData() == "shared")
            self.table.item(row, 4).setText(", ".join(f"{onset} → {marker}" for onset, marker in self._row_codes(row)) or "Not assigned")
        try:
            self.marker_codes()
        except (FrequencyProtocolError, ValueError) as exc:
            self.status.set_variant("warning")
            self.status.set_text(self._note + "\n" + str(exc))
            self.apply_button.setEnabled(False)
        else:
            self.status.set_variant("info")
            self.status.set_text(self._note)
            self.apply_button.setEnabled(True)

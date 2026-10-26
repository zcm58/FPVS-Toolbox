"""Review source namespaces and project-unique identities before discovery."""

from __future__ import annotations

from copy import deepcopy
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHeaderView, QTableWidget, QTableWidgetItem

from Main_App.gui.components import AppDialog, StatusBanner, SurfaceSize, make_action_button, make_action_row
from Main_App.projects.raw_identity import propose_source_participant_id
from Main_App.projects import validate_group_folder_name


class SourceParticipantRegistrationDialog(AppDialog):
    """Return registration proposals; only the caller may publish the registry."""

    def __init__(self, proposals, parent=None, *, project=None, review=None):
        super().__init__("Source participants", parent, size=SurfaceSize(1100, 650, min_width=850, min_height=420))
        self.setObjectName("source_participant_registration_dialog")
        self._proposals = deepcopy(list(proposals))
        self._loading = True
        self._manual_ids = set()
        self._project = project
        self._review = review
        self._map_selectors = {}
        maps = getattr(getattr(project, "frequency_protocol", None), "condition_trigger_maps", None)
        self.status = StatusBanner("", self, variant="warning")
        self.root_layout.addWidget(self.status)
        headers = ["Project ID", "Source study", "Original ID", "Group", "Raw file"]
        if maps is not None:
            headers.append("Source map")
        self.table = QTableWidget(len(self._proposals), len(headers), self)
        self.table.setObjectName("source_participant_registration_table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for row, proposal in enumerate(self._proposals):
            values = (proposal.get("participant_id", ""), proposal.get("source_study_id", ""),
                      proposal.get("source_participant_id", ""), proposal.get("group_label", proposal.get("group_id", "")), str(proposal.get("raw_file", "")))
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setToolTip(str(value or ""))
                if column > 2 or proposal.get("existing", False):
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)
            if maps is not None:
                if proposal.get("existing"):
                    profile_id = dict(maps.recording_assignments).get(proposal.get("participant_id"), "")
                    profile_label = next((profile.label for profile in maps.profiles if profile.profile_id == profile_id), profile_id)
                    item = QTableWidgetItem(profile_label)
                    item.setToolTip(profile_id)
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, 5, item)
                else:
                    selector = QComboBox(self.table)
                    selector.addItem("Choose source map…", "")
                    for profile in maps.profiles:
                        selector.addItem(profile.label, profile.profile_id)
                    default = dict(maps.registration_group_defaults).get(proposal.get("group_id"))
                    if default:
                        selector.setCurrentIndex(selector.findData(default))
                    self._map_selectors[row] = selector
                    selector.currentIndexChanged.connect(lambda *_: self._refresh())
                    self.table.setCellWidget(row, 5, selector)
        self.root_layout.addWidget(self.table, 1)
        self.cancel_button = make_action_button("Cancel", parent=self)
        self.apply_button = make_action_button("Register participants", variant="primary", parent=self)
        self.apply_button.setObjectName("source_participant_registration_apply")
        self.root_layout.addWidget(make_action_row((self.cancel_button, self.apply_button), parent=self))
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._accept_validated)
        self.table.itemChanged.connect(self._changed)
        self._loading = False
        self._refresh()

    def _changed(self, item):
        if self._loading:
            return
        if item.column() == 0:
            self._manual_ids.add(item.row())
        self._refresh()

    def _refresh(self):
        self._loading = True
        try:
            for row, proposal in enumerate(self._proposals):
                if proposal.get("existing", False) or row in self._manual_ids:
                    continue
                source = self.table.item(row, 1).text().strip()
                original = self.table.item(row, 2).text().strip()
                if source and original:
                    self.table.item(row, 0).setText(propose_source_participant_id(source, original))
            self.registrations()
        except ValueError as exc:
            self.status.set_text(str(exc))
            self.status.show()
            self.apply_button.setEnabled(False)
        else:
            self.status.hide()
            self.apply_button.setEnabled(True)
        finally:
            self._loading = False

    def registrations(self):
        rows, canonical, source_people = [], set(), set()
        for row, proposal in enumerate(self._proposals):
            participant_id, source, original = (self.table.item(row, column).text().strip() for column in range(3))
            existing = proposal.get("existing", False)
            if not participant_id or (not existing and (not source or not original)):
                raise ValueError("Enter a source study, original ID and unique project ID for each recording.")
            # The same validation also checks filename-safe identity collisions.
            if not existing:
                propose_source_participant_id(source, original)
                validate_group_folder_name(participant_id)
            key = re.sub(r"[^A-Za-z0-9]", "", participant_id).casefold()
            if not key or key in canonical:
                raise ValueError(f"Project ID {participant_id!r} collides with another participant. Enter a distinct project ID.")
            pair = source.casefold(), original.casefold()
            if source and original and pair in source_people:
                raise ValueError(f"Source {source!r} contains more than one recording for {original!r}. Use the repeated-session registration workflow for visits.")
            canonical.add(key)
            if source and original:
                source_people.add(pair)
            rows.append({**proposal, "participant_id": participant_id, "source_study_id": source, "source_participant_id": original})
        if self._project is not None and self._review is not None:
            from Main_App.projects.source_registration import validate_source_registration_rows
            validate_source_registration_rows(self._project, self._review, rows, trigger_map_assignments=self.trigger_map_assignments())
        return rows

    def trigger_map_assignments(self):
        return {self.table.item(row, 0).text().strip(): selector.currentData() for row, selector in self._map_selectors.items()}

    def _accept_validated(self):
        self._refresh()
        if self.apply_button.isEnabled():
            self.accept()

"""One source trigger editor shared by Home and the detached Settings draft."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHeaderView, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from Main_App.gui.components import AppDialog, StatusBanner, SurfaceSize, make_action_button, make_action_row
from .trigger_maps_model import (
    trigger_map_changes, trigger_map_editor_payload, trigger_recording_rows,
    unused_identifier, validated_editor_maps,
)


class TriggerMapsDialog(AppDialog):
    """All edits remain in this dialog until its caller commits the result."""

    def __init__(self, project, parent=None, *, payload=None, apply_to_settings=False):
        super().__init__("Trigger maps", parent, size=SurfaceSize(1100, 720, min_width=850, min_height=560))
        self.setObjectName("trigger_maps_dialog")
        self.project = project
        self.payload = deepcopy(payload if payload is not None else trigger_map_editor_payload(project))
        self._baseline = deepcopy(self.payload)
        self._loading = False
        self._records = trigger_recording_rows(project)
        self._profile_id = None
        converting = project.frequency_protocol.condition_trigger_maps is None
        self.mode = QLabel("Use source maps" if converting else "Source maps", self)
        self.mode.setObjectName("trigger_maps_mode")
        self.root_layout.addWidget(self.mode)
        if converting:
            note = QLabel("Saving switches this project to source maps. Each recording keeps an explicit assignment; returning to the shared map is not supported.", self)
            note.setWordWrap(True)
            self.root_layout.addWidget(note)
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("trigger_maps_tabs")
        self.root_layout.addWidget(self.tabs, 1)
        self._build_assignments()
        self._build_conditions()
        review = QWidget(self)
        review_layout = QVBoxLayout(review)
        self.review_note = QLabel("Changes to conditions, markers or existing assignments require processing the project again.", review)
        self.review_note.setWordWrap(True)
        review_layout.addWidget(self.review_note)
        self.review_table = self._table(("Setting / recording", "Saved", "Proposed"), review)
        review_layout.addWidget(self.review_table, 1)
        self.tabs.addTab(review, "Review")
        self.status = StatusBanner("", self, variant="warning")
        self.status.setObjectName("trigger_maps_validation")
        self.root_layout.addWidget(self.status)
        self.cancel_button = make_action_button("Cancel", parent=self)
        self.apply_button = make_action_button("Apply to Settings" if apply_to_settings else "Save trigger maps", variant="primary", parent=self)
        self.apply_button.setObjectName("trigger_maps_apply")
        self.root_layout.addWidget(make_action_row((self.cancel_button, self.apply_button), parent=self))
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._accept_validated)
        self._load_profiles()
        self._refresh_assignments()
        self._validate()

    @staticmethod
    def _table(headers, parent):
        table = QTableWidget(0, len(headers), parent)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().hide()
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        return table

    @staticmethod
    def _item(value, *, editable=False):
        item = QTableWidgetItem(str(value if value is not None else ""))
        if not editable:
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _build_assignments(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        self.assignments = self._table(("Recording / Project ID", "Source study", "Original ID", "Group", "Raw file", "Source map"), page)
        self.assignments.setObjectName("trigger_map_assignments")
        self.assignments.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assignments.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.assignments, 2)
        row = QHBoxLayout()
        self.bulk_profile = QComboBox(page)
        self.bulk_button = make_action_button("Assign to selected recordings", compact=True, parent=page)
        self.bulk_button.clicked.connect(self._bulk_assign)
        select = make_action_button("Select all", compact=True, parent=page)
        select.clicked.connect(self.assignments.selectAll)
        row.addWidget(self.bulk_profile)
        row.addWidget(self.bulk_button)
        row.addWidget(select)
        row.addStretch(1)
        layout.addLayout(row)
        note = QLabel("Group defaults propose maps for future registration. Existing assignments change only through the recording table above.", page)
        note.setWordWrap(True)
        layout.addWidget(note)
        self.defaults = self._table(("Group", "Default for new recordings"), page)
        self.defaults.setObjectName("trigger_map_registration_defaults")
        self.defaults.setMaximumHeight(145)
        layout.addWidget(self.defaults, 1)
        self.tabs.addTab(page, "Assignments")

    def _build_conditions(self):
        page = QWidget(self)
        layout = QVBoxLayout(page)
        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Source map:", page))
        self.profile_combo = QComboBox(page)
        self.profile_combo.setObjectName("trigger_map_profile")
        self.profile_combo.currentIndexChanged.connect(self._select_profile)
        profile_row.addWidget(self.profile_combo, 1)
        self.profile_label = QLineEdit(page)
        self.profile_label.setPlaceholderText("Source map name")
        self.profile_label.textEdited.connect(self._edit_profile_label)
        profile_row.addWidget(self.profile_label, 1)
        add_profile = make_action_button("Add source map…", compact=True, parent=page)
        add_profile.clicked.connect(self._add_profile)
        profile_row.addWidget(add_profile)
        remove_profile = make_action_button("Remove source map", compact=True, parent=page)
        remove_profile.clicked.connect(self._remove_profile)
        profile_row.addWidget(remove_profile)
        layout.addLayout(profile_row)
        self.conditions = self._table(("Condition ID", "Condition", "Onset marker", "Oddball marker"), page)
        self.conditions.setObjectName("trigger_map_conditions")
        self.conditions.itemChanged.connect(self._edit_condition)
        layout.addWidget(self.conditions, 2)
        add_condition = make_action_button("Add condition…", compact=True, parent=page)
        add_condition.clicked.connect(self._add_condition)
        remove_condition = make_action_button("Remove selected condition", compact=True, parent=page)
        remove_condition.clicked.connect(self._remove_condition)
        layout.addWidget(make_action_row((add_condition, remove_condition), parent=page))
        layout.addWidget(QLabel("Recognized source conditions not analyzed", page))
        self.boundaries = self._table(("Onset marker", "Source condition label (optional)"), page)
        self.boundaries.setObjectName("trigger_map_boundaries")
        self.boundaries.itemChanged.connect(self._edit_boundaries)
        layout.addWidget(self.boundaries, 1)
        add_boundary = make_action_button("Add source boundary", compact=True, parent=page)
        add_boundary.clicked.connect(self._add_boundary)
        remove_boundary = make_action_button("Remove selected boundary", compact=True, parent=page)
        remove_boundary.clicked.connect(self._remove_boundary)
        layout.addWidget(make_action_row((add_boundary, remove_boundary), parent=page))
        self.tabs.addTab(page, "Condition maps")

    def _profile_choices(self, combo, selected=None, *, optional=False):
        combo.blockSignals(True)
        combo.clear()
        if optional:
            combo.addItem("Not assigned", "")
        for ident, profile in self.payload["profiles"].items():
            combo.addItem(profile.get("label") or ident, ident)
        index = combo.findData(selected)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _load_profiles(self):
        self._profile_choices(self.profile_combo, self._profile_id)
        self._profile_choices(self.bulk_profile)
        self._select_profile()

    def _refresh_assignments(self):
        self.assignments.setRowCount(len(self._records))
        self._assignment_combos = []
        for index, row in enumerate(self._records):
            for column, value in enumerate((row.recording_id, row.source_study, row.original_id, row.group_label, row.raw_file)):
                item = self._item(value)
                item.setToolTip(str(value))
                self.assignments.setItem(index, column, item)
            combo = QComboBox(self.assignments)
            self._profile_choices(combo, self.payload["recording_assignments"].get(row.recording_id), optional=True)
            combo.currentIndexChanged.connect(lambda _index, rid=row.recording_id, control=combo: self._assign(rid, control.currentData()))
            self.assignments.setCellWidget(index, 5, combo)
            self._assignment_combos.append(combo)
        groups = dict((row.group_id, row.group_label) for row in self._records if row.group_id)
        self.defaults.setRowCount(len(groups))
        for index, (ident, label) in enumerate(groups.items()):
            self.defaults.setItem(index, 0, self._item(label))
            combo = QComboBox(self.defaults)
            self._profile_choices(combo, self.payload["registration_group_defaults"].get(ident), optional=True)
            combo.currentIndexChanged.connect(lambda _index, gid=ident, control=combo: self._set_default(gid, control.currentData()))
            self.defaults.setCellWidget(index, 1, combo)

    def _assign(self, recording_id, profile_id):
        if profile_id:
            self.payload["recording_assignments"][recording_id] = profile_id
        else:
            self.payload["recording_assignments"].pop(recording_id, None)
        self._validate()

    def _set_default(self, group_id, profile_id):
        if profile_id:
            self.payload["registration_group_defaults"][group_id] = profile_id
        else:
            self.payload["registration_group_defaults"].pop(group_id, None)
        self._validate()

    def _bulk_assign(self):
        profile_id = self.bulk_profile.currentData()
        for index in self.assignments.selectionModel().selectedRows():
            combo = self._assignment_combos[index.row()]
            combo.setCurrentIndex(combo.findData(profile_id))

    def _select_profile(self, *_args):
        self._profile_id = self.profile_combo.currentData()
        profile = self.payload["profiles"].get(self._profile_id)
        if profile is None:
            return
        self._loading = True
        self.profile_label.setText(profile.get("label") or self._profile_id)
        self.conditions.setRowCount(len(self.payload["canonical_conditions"]))
        for row, (ident, condition) in enumerate(self.payload["canonical_conditions"].items()):
            codes = profile["conditions"].get(ident, {})
            for column, value in enumerate((ident, condition["label"], codes.get("onset_code", ""), codes.get("oddball_code", ""))):
                self.conditions.setItem(row, column, self._item(value, editable=column > 0))
        labels = profile.get("boundary_labels", {})
        self.boundaries.setRowCount(len(profile.get("boundary_only_onset_codes", [])))
        for row, code in enumerate(profile.get("boundary_only_onset_codes", [])):
            self.boundaries.setItem(row, 0, self._item(code, editable=True))
            self.boundaries.setItem(row, 1, self._item(labels.get(str(code), ""), editable=True))
        self._loading = False

    def _edit_profile_label(self, text):
        if self._profile_id:
            self.payload["profiles"][self._profile_id]["label"] = text.strip()
            self.profile_combo.setItemText(self.profile_combo.currentIndex(), text.strip() or self._profile_id)
            self._refresh_assignments()
            self._validate()

    def _add_profile(self):
        label, ok = QInputDialog.getText(self, "Add source map", "Source map name:")
        if not ok or not label.strip():
            return
        ident = unused_identifier(label, self.payload["profiles"])
        self.payload["profiles"][ident] = {"label": label.strip(), "conditions": {}, "boundary_only_onset_codes": []}
        self._profile_id = ident
        self._load_profiles()
        self._refresh_assignments()
        self._validate()

    def _add_condition(self):
        label, ok = QInputDialog.getText(self, "Add condition", "Condition name:")
        if not ok or not label.strip():
            return
        ident = unused_identifier(label, self.payload["canonical_conditions"])
        self.payload["canonical_conditions"][ident] = {"label": label.strip()}
        self._select_profile()
        self._validate()

    def _remove_profile(self):
        if len(self.payload["profiles"]) <= 1:
            self.status.set_text("Keep at least one source trigger map.")
            self.status.show()
            return
        if self._profile_id in self.payload["recording_assignments"].values():
            self.status.set_text("Assign this source map's recordings to another map before removing it.")
            self.status.show()
            return
        self.payload["profiles"].pop(self._profile_id)
        self.payload["registration_group_defaults"] = {
            key: value for key, value in self.payload["registration_group_defaults"].items() if value != self._profile_id
        }
        self._profile_id = None
        self._load_profiles()
        self._refresh_assignments()
        self._validate()

    def _remove_condition(self):
        row = self.conditions.currentRow()
        if row < 0:
            return
        ident = self.conditions.item(row, 0).text()
        removed = self.payload["canonical_conditions"].pop(ident)
        for profile in self.payload["profiles"].values():
            codes = profile["conditions"].pop(ident, {})
            onset = codes.get("onset_code")
            if onset not in (None, "") and onset not in profile["boundary_only_onset_codes"]:
                profile["boundary_only_onset_codes"].append(onset)
                profile.setdefault("boundary_labels", {})[str(onset)] = removed["label"]
        self._select_profile()
        self._validate()

    def _edit_condition(self, item):
        if self._loading or not self._profile_id:
            return
        row = item.row()
        ident = self.conditions.item(row, 0).text()
        self.payload["canonical_conditions"][ident]["label"] = self.conditions.item(row, 1).text().strip()
        self.payload["profiles"][self._profile_id]["conditions"][ident] = {
            "onset_code": self.conditions.item(row, 2).text().strip(),
            "oddball_code": self.conditions.item(row, 3).text().strip(),
        }
        self._validate()

    def _add_boundary(self):
        self._loading = True
        row = self.boundaries.rowCount()
        self.boundaries.insertRow(row)
        for column in range(2):
            self.boundaries.setItem(row, column, self._item("", editable=True))
        self._loading = False
        self._edit_boundaries()

    def _remove_boundary(self):
        row = self.boundaries.currentRow()
        if row >= 0:
            self.boundaries.removeRow(row)
            self._edit_boundaries()

    def _edit_boundaries(self, *_args):
        if self._loading or not self._profile_id:
            return
        profile = self.payload["profiles"][self._profile_id]
        codes, labels = [], {}
        for row in range(self.boundaries.rowCount()):
            code = self.boundaries.item(row, 0).text().strip()
            codes.append(code)
            label = self.boundaries.item(row, 1).text().strip()
            if label:
                labels[code] = label
        profile["boundary_only_onset_codes"], profile["boundary_labels"] = codes, labels
        self._validate()

    def maps(self):
        return validated_editor_maps(self.project, self.payload)

    def _validate(self):
        if not hasattr(self, "status"):
            return
        try:
            self.maps()
        except ValueError as exc:
            self.status.set_text(str(exc))
            self.status.show()
            self.apply_button.setEnabled(False)
        else:
            self.status.hide()
            self.apply_button.setEnabled(True)
        changes = trigger_map_changes(self._baseline, self.payload)
        self.review_table.setRowCount(len(changes))
        for row, values in enumerate(changes):
            for column, value in enumerate(values):
                self.review_table.setItem(row, column, self._item(value))

    def _accept_validated(self):
        self._validate()
        if self.apply_button.isEnabled():
            self.accept()

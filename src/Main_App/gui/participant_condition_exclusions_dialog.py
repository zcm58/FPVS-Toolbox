"""Editor for participant-condition exclusions from downstream workbook analyses."""

from __future__ import annotations

from typing import Mapping, Sequence

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    ActionRow, AppDialog, StatusBanner, SubsectionHeaderLabel, SurfaceSize,
    make_action_button,
)
from Main_App.gui.condition_exclusion_review_model import (
    evidence_text, needs_attention, reference_text, status_label,
)
from Main_App.processing.full_fft_grid_qc import FullFftGridAudit
from Main_App.processing.missing_condition_outputs import MissingConditionOutput
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
)

_SCOPE_RECORDING = "recording"
_SCOPE_PARTICIPANT = "participant"


class ParticipantConditionExclusionsDialog(AppDialog):
    """Review FullFFT grids and choose downstream participant-condition omissions."""

    def __init__(
        self,
        audit: FullFftGridAudit,
        excluded_participant_conditions: Mapping[str, Sequence[str]] | None = None,
        parent=None,
        *,
        excluded_recording_conditions: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        super().__init__(
            "Participant-Condition FFT Crop Exclusions", parent,
            size=SurfaceSize(1180, 760, min_width=1000, min_height=650),
        )
        self.setObjectName("participant_condition_exclusions_dialog")
        self._audit = audit
        self._observations = audit.review_rows
        self._recording_aware = any(row.recording_id for row in self._observations)
        self._existing = normalize_manual_excluded_participant_conditions(
            excluded_participant_conditions
        )
        self._existing_recordings = normalize_manual_excluded_recording_conditions(
            excluded_recording_conditions
        )
        self._scope_controls: dict[int, QComboBox] = {}
        self._exclude_column = 4
        self._attention = [needs_attention(row, audit) for row in self._observations]
        self._evidence = [evidence_text(row, audit) for row in self._observations]
        self._build_ui()
        self._populate_rows()
        self.table.currentCellChanged.connect(self._show_observation)
        self.table.itemChanged.connect(self._selection_changed)
        self.search_edit.textChanged.connect(self._filter_rows)
        self.view_combo.currentIndexChanged.connect(self._filter_rows)
        self._filter_rows()

    def _build_ui(self) -> None:
        layout = self.root_layout
        layout.addWidget(StatusBanner(
            "Review missing outputs or different FFT lengths. Check Exclude to omit "
            "that condition from downstream analysis; original files are kept.",
            self, variant="warning" if any(self._attention) else "info",
        ))
        reference = QLabel(reference_text(self._audit), self)
        reference.setObjectName("condition_exclusion_reference")
        reference.setWordWrap(True)
        layout.addWidget(reference)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        list_panel = QWidget(self.splitter)
        list_panel.setMinimumWidth(520)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(SubsectionHeaderLabel("Conditions", list_panel))
        filters = QHBoxLayout()
        self.view_combo = QComboBox(list_panel)
        self.view_combo.setObjectName("condition_exclusion_view")
        self.view_combo.setAccessibleName("Conditions to show")
        self.view_combo.addItem("Needs attention", "attention")
        self.view_combo.addItem("All conditions", "all")
        self.view_combo.addItem("Selected exclusions", "excluded")
        self.view_combo.setCurrentIndex(0 if any(self._attention) else 1)
        filters.addWidget(self.view_combo)
        self.search_edit = QLineEdit(list_panel)
        self.search_edit.setObjectName("condition_exclusion_search")
        self.search_edit.setPlaceholderText("Search participant, condition or details...")
        self.search_edit.setAccessibleName("Search conditions")
        self.search_edit.setClearButtonEnabled(True)
        filters.addWidget(self.search_edit, 1)
        list_layout.addLayout(filters)

        self.table = QTableWidget(len(self._observations), 5, list_panel)
        self.table.setObjectName("participant_condition_exclusions_table")
        self.table.setHorizontalHeaderLabels([
            "Recording" if self._recording_aware else "Participant",
            "Condition", "FFT length", "Status", "Exclude",
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideRight)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(32)
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(35)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column, width in ((0, 105), (2, 100), (3, 110), (4, 70)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.table.setColumnWidth(column, width)
        list_layout.addWidget(self.table, 1)
        self.summary_label = QLabel(list_panel)
        self.summary_label.setObjectName("condition_exclusion_summary")
        self.summary_label.setWordWrap(True)
        list_layout.addWidget(self.summary_label)

        detail_panel = QWidget(self.splitter)
        detail_panel.setMinimumWidth(330)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.addWidget(SubsectionHeaderLabel("Selected condition", detail_panel))
        self.evidence_view = QPlainTextEdit(detail_panel)
        self.evidence_view.setObjectName("condition_exclusion_evidence")
        self.evidence_view.setAccessibleName("Condition status, guidance and full details")
        self.evidence_view.setReadOnly(True)
        self.evidence_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        detail_layout.addWidget(self.evidence_view, 1)
        self.decision_stack = QStackedWidget(detail_panel)
        self.decision_stack.setObjectName("condition_exclusion_scope_stack")
        self.decision_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.decision_stack.setVisible(self._recording_aware)
        detail_layout.addWidget(self.decision_stack)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([650, 470])

        actions = ActionRow(self, alignment=Qt.AlignRight)
        actions.setObjectName("participant_condition_exclusions_actions")
        cancel = make_action_button("Cancel", variant="secondary", parent=actions)
        save = make_action_button("Save exclusions", variant="primary", parent=actions)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        actions.add_button(cancel)
        actions.add_button(save)
        layout.addWidget(actions)

    def _populate_rows(self) -> None:
        existing_pairs = {
            (participant.casefold(), condition.casefold())
            for participant, conditions in self._existing.items() for condition in conditions
        }
        existing_recording_pairs = {
            (recording.casefold(), condition.casefold())
            for recording, conditions in self._existing_recordings.items() for condition in conditions
        }
        candidate_pairs = {observation.pair_key for observation in self._audit.review_candidates}
        for row, observation in enumerate(self._observations):
            values = (
                observation.recording_id or "Not registered"
                if self._recording_aware else observation.participant_id,
                observation.condition,
                "--" if isinstance(observation, MissingConditionOutput)
                else (f"{observation.oddball_cycles} cycles"
                      if observation.oddball_cycles is not None else "Unavailable"),
                status_label(observation, self._audit),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                item.setToolTip(self._evidence[row] if column == 3 else value)
                self.table.setItem(row, column, item)
            exclude_item = QTableWidgetItem()
            exclude_item.setFlags(
                (exclude_item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable
            )
            participant_pair = observation.participant_pair_key
            recording_pair = observation.recording_pair_key
            should_check = participant_pair in existing_pairs or (
                recording_pair is not None and recording_pair in existing_recording_pairs
            ) or (
                not isinstance(observation, MissingConditionOutput)
                and observation.pair_key in candidate_pairs
            )
            exclude_item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
            exclude_item.setToolTip("Checked: omit this condition from downstream analysis.")
            self.table.setItem(row, self._exclude_column, exclude_item)
            if self._recording_aware:
                page = QWidget(self.decision_stack)
                page_layout = QVBoxLayout(page)
                page_layout.setContentsMargins(0, 4, 0, 0)
                label = QLabel("Exclusion scope", page)
                page_layout.addWidget(label)
                scope = QComboBox(page)
                scope.setObjectName(f"condition_exclusion_scope_{row}")
                scope.addItem("This recording", _SCOPE_RECORDING)
                scope.addItem("Participant (all visits)", _SCOPE_PARTICIPANT)
                selected_scope = _SCOPE_PARTICIPANT if participant_pair in existing_pairs else _SCOPE_RECORDING
                scope.setCurrentIndex(max(0, scope.findData(selected_scope)))
                scope.setToolTip("Apply to this recording, or this participant's condition across all visits.")
                label.setBuddy(scope)
                page_layout.addWidget(scope)
                self.decision_stack.addWidget(page)
                self._scope_controls[row] = scope

    def _show_observation(self, row: int, *_unused) -> None:
        if row < 0 or self.table.isRowHidden(row):
            self.evidence_view.setPlainText("No matching conditions. Change the view or clear the search.")
            self.decision_stack.setEnabled(False)
            return
        self.evidence_view.setPlainText(self._evidence[row])
        self.decision_stack.setCurrentIndex(row)
        self.decision_stack.setEnabled(True)

    def _selection_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == self._exclude_column:
            self._filter_rows()

    def _filter_rows(self, *_unused) -> None:
        terms = self.search_edit.text().casefold().split()
        view = self.view_combo.currentData()
        selected = shown = 0
        for row, evidence in enumerate(self._evidence):
            excluded = self.table.item(row, self._exclude_column).checkState() == Qt.Checked
            selected += int(excluded)
            matches_view = view == "all" or (view == "attention" and self._attention[row]) or (view == "excluded" and excluded)
            folded = evidence.casefold()
            visible = matches_view and all(term in folded for term in terms)
            self.table.setRowHidden(row, not visible)
            shown += int(visible)
        current = self.table.currentRow()
        if current < 0 or self.table.isRowHidden(current):
            current = next((row for row in range(len(self._observations)) if not self.table.isRowHidden(row)), -1)
            self.table.setCurrentCell(current, 0 if current >= 0 else -1)
        self._show_observation(current)
        total = len(self._observations)
        attention = sum(self._attention)
        self.summary_label.setText(
            f"{shown} of {total} shown | {attention} need review | {selected} selected for exclusion"
        )
        with QSignalBlocker(self.view_combo):
            self.view_combo.setItemText(0, f"Needs attention ({attention})")
            self.view_combo.setItemText(1, f"All conditions ({total})")
            self.view_combo.setItemText(2, f"Selected exclusions ({selected})")

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
        if not self._recording_aware:
            return _SCOPE_PARTICIPANT
        widget = self._scope_controls.get(row)
        if isinstance(widget, QComboBox):
            return str(widget.currentData() or _SCOPE_RECORDING)
        return _SCOPE_RECORDING


__all__ = ["ParticipantConditionExclusionsDialog"]

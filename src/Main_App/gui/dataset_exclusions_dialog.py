"""One explicit editor for whole-participant and whole-recording exclusions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPlainTextEdit, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from Main_App.gui.components import (
    ActionRow, AppDialog, StatusBanner, SubsectionHeaderLabel, SurfaceSize,
    make_action_button,
)
from Main_App.processing.dataset_exclusions import DatasetExclusionRow, DatasetExclusionsSnapshot
from Main_App.workers.dataset_exclusions import DatasetExclusionsWorker


SCOPE_LABELS = {
    "include": "Included",
    "skip_processing": "Skip processing entirely",
    "exclude_analysis": "Exclude from analysis after processing",
    "both": "Both processing and analysis exclusions (existing)",
}
_TABLE_SCOPES = {
    "include": "Included", "skip_processing": "Processing skipped",
    "exclude_analysis": "Analysis excluded", "both": "Both exclusions",
}


def effective_exclusion_scope(row, rows, scopes):
    """Show inherited participant exclusions without editing recording choices."""
    direct = scopes.get(row.identity, row.scope)
    inherited = "include"
    if row.recording_id:
        parent = next((item for item in rows if not item.recording_id
                       and item.participant_id.casefold() == row.participant_id.casefold()), None)
        if parent is not None:
            inherited = scopes.get(parent.identity, parent.scope)
    processing = any(scope in {"skip_processing", "both"} for scope in (direct, inherited))
    analysis = any(scope in {"exclude_analysis", "both"} for scope in (direct, inherited))
    return "both" if processing and analysis else (
        "skip_processing" if processing else "exclude_analysis" if analysis else "include"
    )


def changed_exclusion_inputs(rows, scopes, reasons):
    """Return only explicitly edited rows, including reason-only changes."""
    changes, changed_reasons = {}, {}
    for row in rows:
        scope = scopes.get(row.identity, row.scope)
        reason = reasons.get(row.identity, row.reason)
        if scope != row.scope or (scope != "include" and reason != row.reason):
            changes[row.identity] = scope
            changed_reasons[row.identity] = reason if scope != "include" else ""
    return changes, changed_reasons


def apply_scope_to_rows(rows, scopes, identities, scope):
    """Validate a bulk choice before changing any individual selection."""
    if scope not in {"include", "skip_processing", "exclude_analysis"}:
        raise ValueError("Choose Included, Skip processing, or Exclude from analysis.")
    selected = set(identities)
    targets = [row for row in rows if row.identity in selected]
    if scope == "exclude_analysis" and any(not row.has_processed_data for row in targets):
        raise ValueError(
            "Analysis exclusion needs existing processed data. Use Skip processing entirely "
            "for participants or recordings that have not been processed."
        )
    updated = dict(scopes)
    updated.update({row.identity: scope for row in targets})
    return updated


class DatasetExclusionsDialog(AppDialog):
    exclusions_changed = Signal(object)

    def __init__(self, project_root: str | Path, parent=None) -> None:
        super().__init__("Dataset Exclusions", parent, size=SurfaceSize(1100, 650, 1000, 600))
        self.setWindowModality(Qt.ApplicationModal)
        self.setObjectName("dataset_exclusions_dialog")
        self.project_root = Path(project_root)
        self.snapshot: DatasetExclusionsSnapshot | None = None
        self._scopes: dict[str, str] = {}
        self._reasons: dict[str, str] = {}
        self._worker: DatasetExclusionsWorker | None = None
        self._busy = False
        self._saving = False
        self._result: DatasetExclusionsSnapshot | None = None
        self._error = ""
        self._showing_selection = False
        self._build_ui()
        self._set_busy(True)
        QTimer.singleShot(0, self.reload)

    def _build_ui(self) -> None:
        self.status = StatusBanner(
            "Choose whether to include data, skip processing entirely, or exclude existing "
            "processed data from analysis. Apply saves immediately. Condition-specific "
            "exclusions remain in place and are shown in the selected row’s details.", self,
        )
        self.root_layout.addWidget(self.status)
        search_row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search participant, recording, group, scope or reason…")
        self.search.setObjectName("dataset_exclusions_search")
        self.search.textChanged.connect(self._filter_rows)
        search_row.addWidget(self.search, 1)
        self.reload_button = make_action_button("Reload", parent=self)
        self.reload_button.setToolTip("Reload saved entries and discard pending changes.")
        self.reload_button.clicked.connect(self.reload)
        search_row.addWidget(self.reload_button)
        self.root_layout.addLayout(search_row)
        self.condition_notice = QLabel(
            "Whole-participant and recording choices only. Condition-specific exclusions stay in place.", self,
        )
        self.condition_notice.setWordWrap(True)
        self.root_layout.addWidget(self.condition_notice)

        splitter = QSplitter(self)
        self.table = QTableWidget(0, 5, splitter)
        self.table.setObjectName("dataset_exclusions_table")
        self.table.setHorizontalHeaderLabels(["Participant", "Recording", "Group", "Processed data", "Effective scope"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show_selection)
        self.table.currentCellChanged.connect(self._show_selection)
        splitter.addWidget(self.table)
        details = QWidget(splitter)
        detail_layout = QVBoxLayout(details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_layout.addWidget(SubsectionHeaderLabel("Selected participant / recording", details))
        self.details = QPlainTextEdit(details)
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(90)
        detail_layout.addWidget(self.details, 1)
        detail_layout.addWidget(QLabel("Direct scope for this row", details))
        self.scope_combo = QComboBox(details)
        self.scope_combo.setObjectName("dataset_exclusions_scope")
        self.scope_combo.currentIndexChanged.connect(self._scope_changed)
        detail_layout.addWidget(self.scope_combo)
        detail_layout.addWidget(QLabel("Reason (optional)", details))
        self.reason_edit = QLineEdit(details)
        self.reason_edit.setObjectName("dataset_exclusions_reason")
        self.reason_edit.textEdited.connect(self._reason_changed)
        self.reason_edit.editingFinished.connect(self._filter_rows)
        detail_layout.addWidget(self.reason_edit)
        self.eligibility = QLabel(details)
        self.eligibility.setWordWrap(True)
        detail_layout.addWidget(self.eligibility)
        splitter.addWidget(details)
        splitter.setSizes([710, 350])
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        self.root_layout.addWidget(splitter, 1)

        bulk_row = QHBoxLayout()
        self.bulk_scope = QComboBox(self)
        self.bulk_scope.setObjectName("dataset_exclusions_bulk_scope")
        for scope in ("include", "skip_processing", "exclude_analysis"):
            self.bulk_scope.addItem(SCOPE_LABELS[scope], scope)
        bulk_row.addWidget(self.bulk_scope, 1)
        self.bulk_button = make_action_button("Apply to selected rows", parent=self)
        self.bulk_button.clicked.connect(self._apply_selected)
        bulk_row.addWidget(self.bulk_button)
        self.include_all_button = make_action_button("Include all participants and recordings", parent=self)
        self.include_all_button.clicked.connect(self._include_all)
        bulk_row.addWidget(self.include_all_button)
        self.root_layout.addLayout(bulk_row)

        actions = ActionRow(self)
        self.cancel_button = actions.add_button(make_action_button("Cancel", parent=actions))
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button = actions.add_button(make_action_button("Apply", variant="primary", parent=actions))
        self.apply_button.setObjectName("dataset_exclusions_apply")
        self.apply_button.clicked.connect(self._save)
        self.root_layout.addWidget(actions)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        ready = not busy and self.snapshot is not None
        for widget in (self.search, self.table, self.bulk_scope, self.bulk_button,
                       self.include_all_button, self.apply_button):
            widget.setEnabled(ready)
        self.cancel_button.setEnabled(not busy)
        self.reload_button.setEnabled(not busy)
        self.scope_combo.setEnabled(ready and self.table.currentRow() >= 0)
        self.reason_edit.setEnabled(ready and self.table.currentRow() >= 0)
        if ready:
            self._show_selection()

    @Slot()
    def reload(self) -> None:
        if self._worker is not None:
            return
        self._begin_worker(False)

    def _begin_worker(self, saving: bool) -> None:
        self._saving = saving
        self._result = None
        self._error = ""
        kwargs = {}
        if saving:
            changes, reasons = changed_exclusion_inputs(self.snapshot.rows, self._scopes, self._reasons)
            kwargs = {"snapshot": self.snapshot, "changes": changes, "reasons": reasons}
        self._set_busy(True)
        self.status.set_variant("info")
        self.status.set_text("Saving dataset exclusions…" if saving else "Loading dataset exclusions…")
        worker = DatasetExclusionsWorker(self.project_root, **kwargs)
        self._worker = worker
        worker.result_ready.connect(self._received_result)
        worker.failed.connect(self._received_error)
        worker.finished.connect(self._worker_finished)
        try:
            worker.start()
        except Exception as exc:
            self._error = str(exc)
            worker.deleteLater()
            self._worker_finished()

    @Slot(object)
    def _received_result(self, result) -> None:
        self._result = result

    @Slot(str)
    def _received_error(self, error: str) -> None:
        self._error = error

    @Slot()
    def _worker_finished(self) -> None:
        self._worker = None
        if self._error or self._result is None:
            self.status.set_variant("error")
            self.status.set_text(self._error or "Dataset exclusions could not be loaded or saved.")
            self._set_busy(False)
            return
        self.snapshot = self._result
        self._populate()
        self._set_busy(False)
        if self._saving:
            self.exclusions_changed.emit(self.snapshot)
            self.accept()

    def _populate(self) -> None:
        self._scopes = {row.identity: row.scope for row in self.snapshot.rows}
        self._reasons = {row.identity: row.reason for row in self.snapshot.rows}
        self.table.setRowCount(len(self.snapshot.rows))
        for index, row in enumerate(self.snapshot.rows):
            values = (row.participant_id, row.recording_id or "All recordings", row.group_label,
                      "Available" if row.has_processed_data else "Not available", _TABLE_SCOPES[row.scope])
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(index, column, item)
        self.status.set_variant("info")
        self.status.set_text(
            f"{len(self.snapshot.rows)} participant and recording entries. Changes save when you Apply. "
            "Participant exclusions also apply to their recordings. Condition-specific exclusions remain in place."
        )
        self._refresh_scope_cells()
        if self.snapshot.rows:
            self.table.selectRow(0)
        self._filter_rows()

    def _current(self) -> DatasetExclusionRow | None:
        index = self.table.currentRow()
        return self.snapshot.rows[index] if self.snapshot and 0 <= index < len(self.snapshot.rows) else None

    def _show_selection(self, *_args) -> None:
        row = self._current()
        selected = set(self._selected_ids())
        analysis_allowed = bool(selected) and all(
            item.has_processed_data for item in self.snapshot.rows
            if item.identity in selected
        ) if self.snapshot else False
        self.bulk_scope.model().item(2).setEnabled(analysis_allowed)
        self.bulk_scope.setToolTip(
            "Analysis exclusion requires processed data for every selected entry."
            if not analysis_allowed else "Choose a scope for the selected rows."
        )
        self._showing_selection = True
        self.scope_combo.clear()
        if row is None:
            self.details.clear()
            self.reason_edit.clear()
            self.scope_combo.setEnabled(False)
            self.reason_edit.setEnabled(False)
            self.eligibility.clear()
            self._showing_selection = False
            return
        self.details.setPlainText("\n".join([
            f"Participant: {row.participant_id}",
            f"Recording: {row.recording_id or 'All recordings for this participant'}",
            f"Group: {row.group_label}",
            f"Pending direct scope: {SCOPE_LABELS[self._scopes[row.identity]]}",
            "Effective scope: " + _TABLE_SCOPES[effective_exclusion_scope(row, self.snapshot.rows, self._scopes)],
            "Change the participant row to remove an inherited whole-participant exclusion."
            if row.recording_id else "This row applies to all recordings for this participant.",
            "", "Saved details (before pending edits):", f"Saved direct scope: {SCOPE_LABELS[row.scope]}",
            *(row.details or ()),
        ]))
        for scope in ("include", "skip_processing", "exclude_analysis"):
            self.scope_combo.addItem(SCOPE_LABELS[scope], scope)
            if scope == "exclude_analysis" and not row.has_processed_data:
                self.scope_combo.model().item(self.scope_combo.count() - 1).setEnabled(False)
        if row.scope == "both":
            self.scope_combo.addItem(SCOPE_LABELS["both"], "both")
            self.scope_combo.model().item(self.scope_combo.count() - 1).setEnabled(False)
        selected = self._scopes[row.identity]
        self.scope_combo.setCurrentIndex(self.scope_combo.findData(selected))
        self.scope_combo.setEnabled(not self._busy)
        self.reason_edit.setText(self._reasons[row.identity])
        self.reason_edit.setEnabled(not self._busy and selected != "include")
        self.eligibility.setText(
            "Analysis exclusion is available because this entry has processed data."
            if row.has_processed_data else
            "No processed data yet. Use Skip processing entirely to leave this entry out; "
            "analysis exclusion becomes available after processing."
        )
        self._showing_selection = False

    def _scope_changed(self, *_args) -> None:
        row = self._current()
        if self._showing_selection or row is None:
            return
        scope = self.scope_combo.currentData()
        self._scopes = apply_scope_to_rows(self.snapshot.rows, self._scopes, [row.identity], scope)
        self._refresh_scope_cells()
        self._filter_rows()

    def _reason_changed(self, text: str) -> None:
        row = self._current()
        if row is not None and not self._showing_selection:
            self._reasons[row.identity] = text

    def _refresh_scope_cells(self) -> None:
        for index, row in enumerate(self.snapshot.rows):
            item = self.table.item(index, 4)
            effective = effective_exclusion_scope(row, self.snapshot.rows, self._scopes)
            text = _TABLE_SCOPES[effective]
            item.setText(text)
            item.setToolTip(
                f"Effective scope: {text}. Direct scope: {SCOPE_LABELS[self._scopes[row.identity]]}. "
                "Participant-wide exclusions also apply to every recording."
            )

    def _selected_ids(self) -> list[str]:
        if self.snapshot is None:
            return []
        return [self.snapshot.rows[index.row()].identity
                for index in self.table.selectionModel().selectedRows()
                if not self.table.isRowHidden(index.row())]

    def _apply_selected(self) -> None:
        identities = self._selected_ids()
        if not identities:
            self.status.set_variant("warning")
            self.status.set_text("Select one or more rows before applying a shared scope.")
            return
        self._apply_bulk(identities, self.bulk_scope.currentData())

    def _include_all(self) -> None:
        self._apply_bulk([row.identity for row in self.snapshot.rows], "include")

    def _apply_bulk(self, identities, scope) -> None:
        try:
            self._scopes = apply_scope_to_rows(self.snapshot.rows, self._scopes, identities, scope)
        except ValueError as exc:
            self.status.set_variant("warning")
            self.status.set_text(str(exc))
            return
        self._refresh_scope_cells()
        self._filter_rows()
        self.status.set_variant("info")
        self.status.set_text(
            f"{len(identities)} entries set to {SCOPE_LABELS[scope]}. Apply saves these changes. "
            "Condition-specific exclusions remain in place."
        )

    def _filter_rows(self, *_args) -> None:
        if self.snapshot is None:
            return
        query = self.search.text().strip().casefold()
        for index, row in enumerate(self.snapshot.rows):
            text = " ".join((row.participant_id, row.recording_id, row.group_label,
                             SCOPE_LABELS[self._scopes[row.identity]],
                             _TABLE_SCOPES[effective_exclusion_scope(row, self.snapshot.rows, self._scopes)],
                             self._reasons[row.identity],
                             *row.details)).casefold()
            self.table.setRowHidden(index, bool(query and query not in text))
        current = self.table.currentRow()
        if current >= 0 and self.table.isRowHidden(current):
            self.table.clearSelection()
            first_visible = next((index for index in range(self.table.rowCount())
                                  if not self.table.isRowHidden(index)), -1)
            self.table.setCurrentCell(first_visible, 0)
        self._show_selection()

    def _save(self) -> None:
        if not self._busy and self.snapshot is not None:
            self._begin_worker(True)

    def reject(self) -> None:
        if not self._busy:
            super().reject()

    def accept(self) -> None:
        if not self._busy:
            super().accept()

    def closeEvent(self, event) -> None:
        if self._busy:
            event.ignore()
        else:
            super().closeEvent(event)

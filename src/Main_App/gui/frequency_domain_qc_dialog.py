"""Modal, recording-aware review for experimental summed-BCA findings."""

from __future__ import annotations

from collections.abc import Mapping
import re

from PySide6.QtCore import QPoint, QSignalBlocker, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTabBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    ColumnFilterMenu,
    StatusBanner,
    SubsectionHeaderLabel,
    SurfaceSize,
    make_action_button,
)
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION,
    DECISION_INTERPOLATE_CONDITION_ELECTRODE,
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    DECISION_RETAIN,
    SUMMED_BCA_SCREENING_BRIEF_TEXT,
    validate_frequency_domain_qc_review_decisions,
)
from Main_App.processing.frequency_qc_identity import frequency_qc_review_rows
from Main_App.gui.frequency_domain_qc_review_model import (
    can_interpolate_finding,
    electrode_group_key,
    electrode_groups,
    finding_section,
)

_CHOOSE_DECISION = ""
_DECISION_LABELS = {
    _CHOOSE_DECISION: "Choose a decision…",
    DECISION_RETAIN: "Retain this finding",
    DECISION_INTERPOLATE_CONDITION_ELECTRODE: "Interpolate electrode in this condition",
    DECISION_EXCLUDE_CONDITION: "Exclude this condition",
    DECISION_EXCLUDE_RECORDING: "Exclude this recording",
    DECISION_EXCLUDE_PARTICIPANT: "Exclude whole participant",
}


class _ReviewTableItem(QTableWidgetItem):
    def __init__(self, text: str, sort_key: tuple) -> None:
        super().__init__(text)
        self.sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _ReviewTableItem):
            return self.sort_key < other.sort_key
        return super().__lt__(other)


class FrequencyDomainQcReviewDialog(AppDialog):
    """Collect explicit choices without treating a BCA flag as an exclusion."""

    def __init__(
        self,
        report: Mapping[str, object],
        parent: QWidget | None = None,
        *,
        participant_groups: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(
            "Experimental Summed-BCA Review",
            parent,
            size=SurfaceSize(1180, 780, min_width=1000, min_height=650),
        )
        self._report = report
        self._interpolation_enabled = (
            report.get("condition_specific_interpolation_enabled") is True
        )
        self._identity_scope = str(
            report.get("identity_scope") or "participant"
        ).strip().casefold()
        self._group_membership_required = participant_groups is not None
        self._participant_groups = {
            str(participant_id).strip().casefold(): str(group_label).strip()
            for participant_id, group_label in (participant_groups or {}).items()
            if str(participant_id).strip() and str(group_label).strip()
        }
        self._decision_controls: dict[str, tuple[QComboBox, QLineEdit]] = {}
        self._artifact_controls: dict[str, QCheckBox] = {}
        self._findings = _review_findings(report)
        self._electrode_groups = electrode_groups(self._findings, self._identity_scope)
        self._bulk_snapshot: dict[int, tuple[str, str, bool]] = {}
        self._bulk_confirmation_key: tuple[str, str, str] | None = None
        self._evidence_texts: list[str] = []
        self._row_controls: list[tuple[QComboBox, QLineEdit]] = []
        self._column_filters: dict[int, set[str]] = {}
        self._sort_column: int | None = None
        self._sort_order = Qt.AscendingOrder
        self._column_menu: ColumnFilterMenu | None = None
        self._submitted_decisions: tuple[dict[str, object], ...] = ()
        self.setModal(True)
        self._build_ui()

    def review_decisions(self) -> tuple[dict[str, object], ...]:
        return tuple(dict(item) for item in self._submitted_decisions)

    def manual_participant_reasons(self) -> dict[str, str]:
        return {
            str(item.get("participant_id") or ""): str(item.get("reason") or "")
            for item in self._submitted_decisions
            if item.get("decision") == DECISION_EXCLUDE_PARTICIPANT
        }

    def manual_recording_reasons(self) -> dict[str, str]:
        return {
            str(item.get("recording_id") or ""): str(item.get("reason") or "")
            for item in self._submitted_decisions
            if item.get("decision") == DECISION_EXCLUDE_RECORDING
            and str(item.get("recording_id") or "")
        }

    def accept(self) -> None:
        raw = {
            fingerprint: {
                "decision": str(combo.currentData() or ""),
                "reason": reason.text().strip(),
            }
            for fingerprint, (combo, reason) in self._decision_controls.items()
        }
        for fingerprint, payload in raw.items():
            if payload["decision"] == DECISION_INTERPOLATE_CONDITION_ELECTRODE:
                confirmation = self._artifact_controls.get(fingerprint)
                payload["artifact_confirmed"] = bool(
                    confirmation is not None and confirmation.isChecked()
                )
        try:
            self._submitted_decisions = (
                validate_frequency_domain_qc_review_decisions(self._report, raw)
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Review Incomplete", str(exc))
            return
        super().accept()

    def _build_ui(self) -> None:
        layout = self.root_layout
        layout.addWidget(
            StatusBanner(
                "Experimental screening: a large response alone does not establish an artifact.",
                self,
                variant="warning",
            )
        )
        outcome_label = QLabel(_outcome_text(self._report), self)
        outcome_label.setObjectName("frequency_domain_qc_outcome_label")
        outcome_label.setWordWrap(True)
        outcome_label.setToolTip(
            "Condition-specific interpolation is "
            + ("enabled" if self._interpolation_enabled else "off")
            + ". Change this in Settings > Experimental > Electrodes. "
            "Confirmed repairs are applied to the signal before recalculating analysis."
        )
        layout.addWidget(outcome_label)

        technical_rows = _technical_context_rows(self._report)
        if technical_rows:
            technical_label = QLabel(
                f"{len(technical_rows)} cohort-context inputs unavailable — "
                "see Review context. These are not passes.",
                self,
            )
            technical_label.setObjectName("frequency_domain_qc_technical_status")
            technical_label.setWordWrap(True)
            layout.addWidget(technical_label)

        self.splitter = QSplitter(Qt.Horizontal, self)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)
        findings_panel = QWidget(self.splitter)
        findings_panel.setMinimumWidth(490)
        findings_layout = QVBoxLayout(findings_panel)
        findings_layout.setContentsMargins(0, 0, 0, 0)
        findings_layout.addWidget(SubsectionHeaderLabel("Findings", findings_panel))
        self.finding_sections = QTabBar(findings_panel)
        self.finding_sections.setObjectName("frequency_domain_qc_sections")
        self.finding_sections.setAccessibleName("Finding sections")
        self.finding_sections.setDrawBase(False)
        self.finding_sections.setExpanding(False)
        for section, label in (("electrode", "Individual electrodes"),
                               ("other", "Other findings")):
            count = sum(finding_section(item) == section for item in self._findings)
            if section == "other" and not count:
                continue
            tab = self.finding_sections.addTab(f"{label} ({count})")
            self.finding_sections.setTabData(tab, section)
        if not any(finding_section(item) == "electrode" for item in self._findings):
            section = finding_section(self._findings[0]) if self._findings else "electrode"
            self.finding_sections.setCurrentIndex(self._section_tab(section))
        findings_layout.addWidget(self.finding_sections)
        self.electrode_group_row = QWidget(findings_panel)
        group_layout = QHBoxLayout(self.electrode_group_row)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_label = QLabel("Electrode group", self.electrode_group_row)
        self.electrode_group_combo = QComboBox(self.electrode_group_row)
        self.electrode_group_combo.setObjectName("frequency_domain_qc_electrode_group")
        self.electrode_group_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.electrode_group_combo.setMinimumContentsLength(12)
        self.electrode_group_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.electrode_group_combo.addItem("All electrode flags", None)
        for key, indices in sorted(self._electrode_groups.items(),
                                   key=lambda entry: _natural_sort_key(self._electrode_group_label(entry[0]))):
            self.electrode_group_combo.addItem(
                f"{self._electrode_group_label(key)} — {len(indices)} flags", key
            )
        group_label.setBuddy(self.electrode_group_combo)
        group_layout.addWidget(group_label)
        group_layout.addWidget(self.electrode_group_combo, 1)
        findings_layout.addWidget(self.electrode_group_row)
        self.search_edit = QLineEdit(findings_panel)
        self.search_edit.setObjectName("frequency_domain_qc_search")
        self.search_edit.setPlaceholderText("Search participant, condition, electrode or evidence…")
        self.search_edit.setAccessibleName("Search frequency-domain findings")
        self.search_edit.setClearButtonEnabled(True)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_edit, 1)
        self.clear_filters_button = make_action_button(
            "Clear filters", variant="secondary", parent=findings_panel
        )
        self.clear_filters_button.setObjectName("frequency_domain_qc_clear_filters")
        self.clear_filters_button.setToolTip("Clear column filters and text search.")
        self.clear_filters_button.setEnabled(False)
        self.clear_filters_button.clicked.connect(self._clear_filters)
        search_row.addWidget(self.clear_filters_button)
        findings_layout.addLayout(search_row)

        self.details_table = QTableWidget(findings_panel)
        self.details_table.setObjectName("frequency_domain_qc_details_table")
        self.details_table.setColumnCount(5)
        identity_heading = (
            "Recording" if self._identity_scope == "recording" else "Participant"
        )
        self.details_table.setHorizontalHeaderLabels(
            [identity_heading, "Condition", "Electrode", "|Value|", "Decision"]
        )
        self.details_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.details_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.details_table.setWordWrap(False)
        self.details_table.setTextElideMode(Qt.ElideRight)
        self.details_table.setAlternatingRowColors(True)
        self.details_table.verticalHeader().hide()
        self.details_table.verticalHeader().setDefaultSectionSize(32)
        header = self.details_table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setHighlightSections(False)
        header.setToolTip("Click a column heading to sort or filter.")
        header.sectionClicked.connect(self._show_column_menu)
        header.setMinimumSectionSize(40)
        header.setStretchLastSection(False)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        # Bound the short columns; long labels stay available in the evidence pane.
        for column, width in ((0, 100), (2, 105), (3, 85), (4, 105)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self.details_table.setColumnWidth(column, width)
        findings_layout.addWidget(self.details_table, 1)
        self.progress_label = QLabel(findings_panel)
        self.progress_label.setObjectName("frequency_domain_qc_progress")
        self.progress_label.setWordWrap(True)
        findings_layout.addWidget(self.progress_label)

        detail_panel = QWidget(self.splitter)
        detail_panel.setMinimumWidth(360)
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        detail_layout.addWidget(SubsectionHeaderLabel("Review", detail_panel))
        self.detail_tabs = QTabWidget(detail_panel)
        self.detail_tabs.setObjectName("frequency_domain_qc_detail_tabs")
        self.evidence_view = QPlainTextEdit(self.detail_tabs)
        self.evidence_view.setObjectName("frequency_domain_qc_finding_evidence")
        self.evidence_view.setAccessibleName("Complete selected finding evidence")
        self.evidence_view.setReadOnly(True)
        self.evidence_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.detail_tabs.addTab(self.evidence_view, "Finding evidence")
        self.context_view = QPlainTextEdit(self.detail_tabs)
        self.context_view.setObjectName("frequency_domain_qc_review_context")
        self.context_view.setAccessibleName("Screening rules, participant summaries and unavailable inputs")
        self.context_view.setReadOnly(True)
        self.context_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.context_view.setPlainText(self._review_context_text(technical_rows))
        self.detail_tabs.addTab(self.context_view, "Review context")
        self._build_electrode_group_panel()
        detail_layout.addWidget(self.detail_tabs, 1)

        self.decision_stack = QStackedWidget(detail_panel)
        self.decision_stack.setObjectName("frequency_domain_qc_decision_stack")
        self.decision_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        detail_layout.addWidget(self.decision_stack)
        self.next_button = make_action_button(
            "Next undecided", variant="secondary", parent=detail_panel
        )
        self.next_button.setObjectName("frequency_domain_qc_next_undecided")
        self.next_button.setToolTip("Go to the next undecided finding; clear filters if it is hidden.")
        self.next_button.clicked.connect(self._select_next_undecided)
        detail_layout.addWidget(self.next_button)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([650, 470])

        self._populate_details_table()
        self._update_filter_headers()
        self.details_table.currentCellChanged.connect(self._show_finding)
        self.search_edit.textChanged.connect(self._filter_findings)
        self.finding_sections.currentChanged.connect(self._section_changed)
        self.electrode_group_combo.currentIndexChanged.connect(self._electrode_group_changed)
        self._section_changed()

        actions = ActionRow(self, alignment=Qt.AlignRight)
        actions.setObjectName("frequency_domain_qc_actions")
        cancel_btn = make_action_button("Cancel", variant="secondary", parent=actions)
        continue_btn = make_action_button(
            "Apply and Continue", variant="primary", parent=actions
        )
        cancel_btn.clicked.connect(self.reject)
        continue_btn.clicked.connect(self.accept)
        actions.add_button(cancel_btn)
        actions.add_button(continue_btn)
        layout.addWidget(actions)

    def _build_electrode_group_panel(self) -> None:
        self.bulk_panel = QWidget(self.detail_tabs)
        self.bulk_panel.setObjectName("frequency_domain_qc_electrode_group_panel")
        layout = QVBoxLayout(self.bulk_panel)
        layout.setContentsMargins(8, 8, 8, 8)
        self.bulk_scope_label = QLabel(self.bulk_panel)
        self.bulk_scope_label.setWordWrap(True)
        layout.addWidget(self.bulk_scope_label)
        self.bulk_scope_view = QPlainTextEdit(self.bulk_panel)
        self.bulk_scope_view.setReadOnly(True)
        self.bulk_scope_view.setAccessibleName("Electrode group and all affected conditions")
        self.bulk_scope_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        layout.addWidget(self.bulk_scope_view, 1)
        self.bulk_artifact_check = QCheckBox(
            "I confirmed an artifact in every listed condition.", self.bulk_panel,
        )
        self.bulk_artifact_check.setObjectName("frequency_domain_qc_bulk_artifact_confirmed")
        self.bulk_artifact_check.setVisible(self._interpolation_enabled)
        self.bulk_artifact_check.toggled.connect(self._update_bulk_group)
        layout.addWidget(self.bulk_artifact_check)
        actions = ActionRow(self.bulk_panel)
        self.bulk_retain_button = make_action_button("Retain all", variant="secondary", parent=actions)
        self.bulk_interpolate_button = make_action_button("Interpolate all", variant="secondary", parent=actions)
        self.bulk_retain_button.setObjectName("frequency_domain_qc_bulk_retain")
        self.bulk_interpolate_button.setObjectName("frequency_domain_qc_bulk_interpolate")
        self.bulk_interpolate_button.setVisible(self._interpolation_enabled)
        self.bulk_retain_button.clicked.connect(
            lambda: self._apply_electrode_group_decision(DECISION_RETAIN)
        )
        self.bulk_interpolate_button.clicked.connect(
            lambda: self._apply_electrode_group_decision(DECISION_INTERPOLATE_CONDITION_ELECTRODE)
        )
        actions.add_button(self.bulk_retain_button)
        actions.add_button(self.bulk_interpolate_button)
        self.bulk_undo_button = make_action_button(
            "Undo", variant="secondary", parent=actions
        )
        self.bulk_undo_button.setObjectName("frequency_domain_qc_bulk_undo")
        self.bulk_undo_button.setAccessibleName("Undo last group decision")
        self.bulk_undo_button.clicked.connect(self._undo_electrode_group_decision)
        actions.add_button(self.bulk_undo_button)
        layout.addWidget(actions)
        self.detail_tabs.addTab(self.bulk_panel, "Electrode group")

    def _section_tab(self, section: str) -> int:
        return next(index for index in range(self.finding_sections.count())
                    if self.finding_sections.tabData(index) == section)

    def _current_section(self) -> str:
        return str(self.finding_sections.tabData(self.finding_sections.currentIndex()))

    def _section_changed(self, _index: int = 0) -> None:
        section = self._current_section()
        self.electrode_group_row.setVisible(section == "electrode")
        self.details_table.horizontalHeaderItem(2).setText(
            {"electrode": "Electrode", "other": "Finding"}[section]
        )
        if self._column_menu is not None:
            self._column_menu.close()
        self._clear_filters()

    @staticmethod
    def _electrode_group_label(key: tuple[str, str, str]) -> str:
        participant, recording, electrode = key
        identity = f"{participant} / {recording}" if recording and recording != participant else participant
        return f"{identity} · {electrode}"

    def _electrode_group_changed(self, _index: int) -> None:
        self._filter_findings()
        if self._selected_electrode_group() is not None:
            self.detail_tabs.setCurrentWidget(self.bulk_panel)

    def _scope_matches(self, finding_index: int) -> bool:
        item = self._findings[finding_index]
        if finding_section(item) != self._current_section():
            return False
        key = self.electrode_group_combo.currentData()
        return (self._current_section() != "electrode" or key is None
                or electrode_group_key(item, self._identity_scope) == key)

    def _selected_electrode_group(self) -> tuple[str, str, str] | None:
        if self._current_section() != "electrode":
            return None
        key = self.electrode_group_combo.currentData()
        if key is not None:
            return key if key in self._electrode_groups else None
        row = self.details_table.currentRow()
        if row < 0 or self.details_table.isRowHidden(row):
            return None
        return electrode_group_key(self._findings[self._finding_index(row)], self._identity_scope)

    def _update_bulk_group(self) -> None:
        key = self._selected_electrode_group()
        if key != self._bulk_confirmation_key:
            self._bulk_confirmation_key = key
            with QSignalBlocker(self.bulk_artifact_check):
                self.bulk_artifact_check.setChecked(False)
        indices = self._electrode_groups.get(key, ())
        available = bool(indices)
        bulk_tab = self.detail_tabs.indexOf(self.bulk_panel)
        self.detail_tabs.setTabEnabled(bulk_tab, available)
        if not available and self.detail_tabs.currentIndex() == bulk_tab:
            self.detail_tabs.setCurrentIndex(0)
        self.bulk_scope_label.setText(
            f"Apply one decision to all {len(indices)} flags for this electrode."
            if available else "Select an individual electrode to review its flagged conditions together."
        )
        if key is not None:
            participant, recording, electrode = key
            conditions: dict[str, int] = {}
            for index in indices:
                condition = str(self._findings[index]["condition"])
                conditions[condition] = conditions.get(condition, 0) + 1
            lines = [f"Participant: {participant}", f"Recording: {recording or 'Single recording'}",
                     f"Electrode: {electrode}", "", f"{len(indices)} flags across {len(conditions)} conditions:"]
            lines.extend(f"{condition} — {count} flag(s)" for condition, count in conditions.items())
            lines.extend([
                "", "Includes flags hidden by filters. Existing decisions will be replaced; "
                "individual reasons are kept. You can still edit each finding before applying.",
            ])
            self.bulk_scope_view.setPlainText("\n".join(lines))
        else:
            self.bulk_scope_view.clear()
        self.bulk_retain_button.setEnabled(available)
        self.bulk_artifact_check.setEnabled(available)
        self.bulk_interpolate_button.setEnabled(
            available and self._interpolation_enabled and self.bulk_artifact_check.isChecked()
        )
        self.bulk_retain_button.setToolTip(f"Retain all {len(indices)} flags listed above.")
        self.bulk_interpolate_button.setToolTip(
            "Repair this electrode in each listed condition after artifact confirmation; "
            "recalculate the signal and derived results."
        )
        self.bulk_undo_button.setEnabled(bool(self._bulk_snapshot))

    def _invalidate_bulk_undo(self, _text: str = "") -> None:
        self._bulk_snapshot.clear()
        self.bulk_undo_button.setEnabled(False)

    def _apply_electrode_group_decision(self, decision: str) -> None:
        if decision not in {DECISION_RETAIN, DECISION_INTERPOLATE_CONDITION_ELECTRODE}:
            raise ValueError("Electrode groups support retain or condition-electrode interpolation only.")
        indices = self._electrode_groups.get(self._selected_electrode_group(), ())
        if not indices:
            return
        interpolate = decision == DECISION_INTERPOLATE_CONDITION_ELECTRODE
        if interpolate and not (
            self._interpolation_enabled and self.bulk_artifact_check.isChecked()
            and all(can_interpolate_finding(
                self._findings[index], self._identity_scope, self._interpolation_enabled,
            ) for index in indices)
        ):
            raise ValueError("Enable experimental interpolation and confirm artifacts before repair.")
        self._bulk_snapshot = {
            index: (str(self._row_controls[index][0].currentData() or ""),
                    self._row_controls[index][1].text(),
                    bool(self._artifact_controls.get(str(self._findings[index]["finding_fingerprint"]))
                         and self._artifact_controls[str(self._findings[index]["finding_fingerprint"])].isChecked()))
            for index in indices
        }
        for index in indices:
            combo, _reason = self._row_controls[index]
            with QSignalBlocker(combo):
                combo.setCurrentIndex(combo.findData(decision))
            confirmation = self._artifact_controls.get(str(self._findings[index]["finding_fingerprint"]))
            if confirmation is not None:
                with QSignalBlocker(confirmation):
                    confirmation.setChecked(interpolate)
            self._refresh_decision_cell(index)
        self.bulk_undo_button.setToolTip(
            "Undo decisions for " + self._electrode_group_label(self._selected_electrode_group())
        )
        self._refresh_decision_view()

    def _undo_electrode_group_decision(self) -> None:
        snapshot, self._bulk_snapshot = self._bulk_snapshot, {}
        for index, (decision, text, confirmed) in snapshot.items():
            combo, reason = self._row_controls[index]
            with QSignalBlocker(combo), QSignalBlocker(reason):
                combo.setCurrentIndex(combo.findData(decision))
                reason.setText(text)
            confirmation = self._artifact_controls.get(str(self._findings[index]["finding_fingerprint"]))
            if confirmation is not None:
                with QSignalBlocker(confirmation):
                    confirmation.setChecked(confirmed)
            self._refresh_decision_cell(index)
        self._refresh_decision_view()

    def _refresh_decision_view(self) -> None:
        if self._sort_column == 4:
            self._sort_findings(4, self._sort_order)
        else:
            self._filter_findings()

    def _review_context_text(self, technical_rows: list[Mapping[str, object]]) -> str:
        # This public adapter also validates canonical recording assignments.
        summaries = [
            row
            for row in frequency_qc_review_rows(self._report)
            if row.get("pause_review")
        ]
        lines = ["EXPERIMENTAL SCREENING", SUMMED_BCA_SCREENING_BRIEF_TEXT]
        lines.extend(["", "SCREENING RULES", _threshold_text(self._report)])
        if technical_rows:
            lines.extend([
                "", "UNAVAILABLE COHORT INPUTS",
                "These inputs were not treated as passes.",
                *(_technical_context_text(row) for row in technical_rows),
            ])
        lines.extend(["", "REVIEW SUMMARY", "Automatic action: None — review flag only"])
        for item in summaries:
            participant = str(item.get("participant_id") or "")
            recording = str(item.get("recording_id") or "")
            identity = participant
            if recording and recording != participant:
                identity += f" / {recording}"
            session = _session_text(item)
            if session:
                identity += f" / {session}"
            group = self._group_for_participant(participant)
            lines.append(f"{identity} · {group}: {_finding_text(item)}")
        return "\n".join(lines)

    def _populate_details_table(self) -> None:
        existing = {
            str(row.get("finding_fingerprint") or ""): row
            for row in [
                *_mapping_rows(self._report.get("review_decisions")),
                *_mapping_rows(self._report.get("review_prefill_decisions")),
            ]
        }
        self.details_table.setRowCount(len(self._findings))
        for row_index, item in enumerate(self._findings):
            fingerprint = str(item.get("finding_fingerprint") or "")
            signed_value, absolute_value = _value_texts(item)
            participant = str(item.get("participant_id") or "")
            recording = str(item.get("recording_id") or "")
            group = self._group_for_participant(participant)
            values = (
                recording if self._identity_scope == "recording" else participant,
                str(item.get("condition") or ""),
                str(item.get("electrode") or ""),
                absolute_value,
                "Undecided",
            )
            absolute = _absolute_value(item)
            for column, value in enumerate(values):
                sort_key = (
                    (absolute is None, absolute or 0.0)
                    if column == 3 else _natural_sort_key(value)
                )
                table_item = _ReviewTableItem(value, sort_key)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                table_item.setToolTip(value)
                if column == 0:
                    table_item.setData(Qt.UserRole, fingerprint)
                    table_item.setData(Qt.UserRole + 1, row_index)
                if column == 3:
                    table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.details_table.setItem(row_index, column, table_item)

            page = QWidget(self.decision_stack)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 4, 0, 0)
            decision_label = QLabel("Decision for this finding", page)
            page_layout.addWidget(decision_label)
            combo = QComboBox(page)
            combo.setObjectName(f"frequency_domain_qc_decision_{row_index}")
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            decision_label.setBuddy(combo)
            allowed = [_CHOOSE_DECISION, DECISION_RETAIN, DECISION_EXCLUDE_CONDITION]
            repair_allowed = can_interpolate_finding(
                item, self._identity_scope, self._interpolation_enabled,
            )
            if repair_allowed:
                allowed.insert(2, DECISION_INTERPOLATE_CONDITION_ELECTRODE)
            if self._identity_scope == "recording":
                allowed.append(DECISION_EXCLUDE_RECORDING)
            allowed.append(DECISION_EXCLUDE_PARTICIPANT)
            for decision in allowed:
                combo.addItem(_DECISION_LABELS[decision], decision)
            page_layout.addWidget(combo)
            if repair_allowed:
                confirmation = QCheckBox(
                    "I confirmed an artifact in this condition.", page,
                )
                confirmation.setObjectName(f"frequency_domain_qc_artifact_confirmed_{row_index}")
                confirmation.setToolTip(
                    "Confirm from the signal or independent artifact evidence. "
                    "A large summed-BCA response alone is insufficient."
                )
                confirmation.setVisible(False)
                confirmation.toggled.connect(self._invalidate_bulk_undo)
                page_layout.addWidget(confirmation)
                self._artifact_controls[fingerprint] = confirmation
            reason_label = QLabel("Reason (optional)", page)
            reason = QLineEdit(page)
            reason.setObjectName(f"frequency_domain_qc_reason_{row_index}")
            reason.setPlaceholderText("Optional reason")
            reason_label.setBuddy(reason)
            page_layout.addWidget(reason_label)
            page_layout.addWidget(reason)
            saved = existing.get(fingerprint)
            context = ""
            if saved is not None:
                prior_decision = str(saved.get("decision") or "")
                prior_reason = str(saved.get("reason") or "").strip()
                prior_label = _DECISION_LABELS.get(
                    prior_decision,
                    prior_decision.replace("_", " ") or "Unavailable",
                )
                context = f"Prior reviewed decision: {prior_label}."
                if prior_reason:
                    context += f" Prior reason: {prior_reason}"
                combo.setToolTip(context)
                reason.setToolTip(context)
            combo.currentIndexChanged.connect(
                lambda _index, row=row_index: self._decision_changed(row)
            )
            reason.textChanged.connect(self._invalidate_bulk_undo)
            reason.setEnabled(False)
            self.decision_stack.addWidget(page)
            self._decision_controls[fingerprint] = (combo, reason)
            self._row_controls.append((combo, reason))
            self._evidence_texts.append(
                _finding_evidence_text(item, group, signed_value, absolute_value, context)
            )

    def _show_finding(self, row: int, *_unused: int) -> None:
        self._update_bulk_group()
        if row < 0 or self.details_table.isRowHidden(row):
            self.evidence_view.setPlainText("No matching findings. Clear filters to show all findings.")
            self.decision_stack.setEnabled(False)
            return
        finding_index = self._finding_index(row)
        self.evidence_view.setPlainText(self._evidence_texts[finding_index])
        self.decision_stack.setCurrentIndex(finding_index)
        self.decision_stack.setEnabled(True)
        if self.detail_tabs.currentWidget() is not self.bulk_panel:
            self.detail_tabs.setCurrentIndex(0)

    def _decision_changed(self, row: int) -> None:
        self._invalidate_bulk_undo()
        confirmation = self._artifact_controls.get(str(self._findings[row]["finding_fingerprint"]))
        if confirmation is not None:
            with QSignalBlocker(confirmation):
                confirmation.setChecked(False)
        self._refresh_decision_cell(row)
        self._refresh_decision_view()

    def _refresh_decision_cell(self, row: int) -> None:
        combo, reason = self._row_controls[row]
        decision = str(combo.currentData() or "")
        reason.setEnabled(decision not in {_CHOOSE_DECISION, DECISION_RETAIN})
        confirmation = self._artifact_controls.get(str(self._findings[row]["finding_fingerprint"]))
        if confirmation is not None:
            confirmation.setVisible(decision == DECISION_INTERPOLATE_CONDITION_ELECTRODE)
        status = {
            _CHOOSE_DECISION: "Undecided",
            DECISION_RETAIN: "Retain",
            DECISION_INTERPOLATE_CONDITION_ELECTRODE: "Interpolate",
            DECISION_EXCLUDE_CONDITION: "Excl. condition",
            DECISION_EXCLUDE_RECORDING: "Excl. recording",
            DECISION_EXCLUDE_PARTICIPANT: "Excl. participant",
        }[decision]
        cell = self.details_table.item(self._table_row(row), 4)
        cell.sort_key = _natural_sort_key(status)
        cell.setText(status)
        cell.setToolTip(_DECISION_LABELS[decision])

    def _update_progress(self) -> None:
        decided = sum(bool(combo.currentData()) for combo, _ in self._row_controls)
        visible = sum(
            not self.details_table.isRowHidden(row) for row in range(len(self._findings))
        )
        text = f"{decided} of {len(self._findings)} decisions made"
        if visible != len(self._findings):
            text += f" · {visible} findings shown"
        self.progress_label.setText(text)
        self.next_button.setEnabled(decided < len(self._findings))

    def _finding_index(self, row: int) -> int:
        cell = self.details_table.item(row, 0)
        return int(cell.data(Qt.UserRole + 1)) if cell is not None else -1

    def _table_row(self, finding_index: int) -> int:
        return next(
            (row for row in range(self.details_table.rowCount())
             if self._finding_index(row) == finding_index), -1,
        )

    def _show_column_menu(self, column: int) -> None:
        header = self.details_table.horizontalHeader()
        # A header click toggles its native arrow even when it only opens a menu.
        # Keep the indicator tied to the sort that was actually applied.
        with QSignalBlocker(header):
            if self._sort_column is not None:
                header.setSortIndicator(self._sort_column, self._sort_order)
            header.setSortIndicatorShown(self._sort_column is not None)
        if self._column_menu is not None:
            self._column_menu.close()
            self._column_menu.deleteLater()
        cells = [self.details_table.item(row, column)
                 for row in range(self.details_table.rowCount())
                 if self._scope_matches(self._finding_index(row))]
        values = list(dict.fromkeys(cell.text() for cell in sorted(cells)))
        menu = ColumnFilterMenu(
            self.details_table.horizontalHeaderItem(column).text(),
            values, self._column_filters.get(column), numeric=column == 3, parent=self,
        )
        self._column_menu = menu
        menu.sort_requested.connect(lambda order: self._sort_findings(column, order))
        menu.filter_applied.connect(lambda selected: self._set_column_filter(column, selected))
        menu.popup(header.mapToGlobal(QPoint(header.sectionViewportPosition(column), header.height())))

    def _sort_findings(self, column: int, order: Qt.SortOrder) -> None:
        selected = self._finding_index(self.details_table.currentRow())
        self._sort_column, self._sort_order = column, order
        with QSignalBlocker(self.details_table):
            self.details_table.sortItems(column, order)
            if selected >= 0:
                self.details_table.setCurrentCell(self._table_row(selected), 0)
        self.details_table.horizontalHeader().setSortIndicator(column, order)
        self.details_table.horizontalHeader().setSortIndicatorShown(True)
        self._filter_findings()
        self._show_finding(self.details_table.currentRow())

    def _set_column_filter(self, column: int, selected: set[str] | None) -> None:
        all_values = {self.details_table.item(row, column).text()
                      for row in range(self.details_table.rowCount())
                      if self._scope_matches(self._finding_index(row))}
        if selected is None or selected == all_values:
            self._column_filters.pop(column, None)
        else:
            self._column_filters[column] = set(selected)
        self._filter_findings()

    def _clear_filters(self) -> None:
        self._column_filters.clear()
        with QSignalBlocker(self.search_edit):
            self.search_edit.clear()
        with QSignalBlocker(self.electrode_group_combo):
            self.electrode_group_combo.setCurrentIndex(0)
        self._filter_findings()

    def _update_filter_headers(self) -> None:
        for column in range(self.details_table.columnCount()):
            active = column in self._column_filters
            item = self.details_table.horizontalHeaderItem(column)
            item.setIcon(self.style().standardIcon(
                QStyle.SP_DialogApplyButton if active else QStyle.SP_ArrowDown
            ))
            item.setToolTip(
                ("Filter active. " if active else "") + "Click to sort or filter this column."
            )
        self.clear_filters_button.setEnabled(bool(
            self._column_filters or self.search_edit.text()
            or self.electrode_group_combo.currentData() is not None
        ))

    def _filter_findings(self, _text: str = "") -> None:
        terms = self.search_edit.text().casefold().split()
        for row in range(self.details_table.rowCount()):
            finding_index = self._finding_index(row)
            evidence = self._evidence_texts[finding_index]
            values = [self.details_table.item(row, column).text()
                      for column in range(self.details_table.columnCount())]
            self.details_table.setRowHidden(
                row, not (self._scope_matches(finding_index)
                          and _matches_filters(evidence, values, terms, self._column_filters))
            )
        current = self.details_table.currentRow()
        if current < 0 or self.details_table.isRowHidden(current):
            first = next(
                (row for row in range(len(self._findings))
                 if not self.details_table.isRowHidden(row)),
                -1,
            )
            if first >= 0:
                self.details_table.setCurrentCell(first, 0)
            else:
                self.details_table.setCurrentCell(-1, -1)
            self._show_finding(first)
        self._update_filter_headers()
        self._update_progress()
        self._update_bulk_group()

    def _select_next_undecided(self) -> None:
        count = len(self._findings)
        current = self.details_table.currentRow()
        for offset in range(1, count + 1):
            row = (current + offset) % count
            combo, _ = self._row_controls[self._finding_index(row)]
            if combo.currentData():
                continue
            if self.details_table.isRowHidden(row):
                section = finding_section(self._findings[self._finding_index(row)])
                self.finding_sections.setCurrentIndex(self._section_tab(section))
                self._clear_filters()
            self.details_table.setCurrentCell(row, 0)
            self._show_finding(row)
            self.details_table.scrollToItem(self.details_table.item(row, 0))
            combo.setFocus()
            return

    def _group_for_participant(self, participant_id: object) -> str:
        normalized = str(participant_id or "").strip()
        if not self._group_membership_required:
            return "Single group"
        group = self._participant_groups.get(normalized.casefold())
        if not group:
            raise ValueError(
                "Frequency-domain QC found participant "
                f"'{normalized}' without canonical project group membership."
            )
        return group


def _natural_sort_key(text: str) -> tuple:
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", text))


def _absolute_value(item: Mapping[str, object]) -> float | None:
    if item.get("finding_type") == "cohort_relative_summed_bca_context":
        value = item.get("value_uv")
        if value is None:
            value = item.get("abs_summed_bca_uv")
        return abs(float(value)) if value is not None else None
    return float(item.get("abs_summed_bca_uv") or abs(float(item.get("summed_bca_uv") or 0.0)))


def _matches_filters(evidence: str, values: list[str], terms: list[str],
                     filters: Mapping[int, set[str]]) -> bool:
    folded = evidence.casefold()
    return (all(term in folded for term in terms)
            and all(values[column] in allowed for column, allowed in filters.items()))


def _finding_evidence_text(
    item: Mapping[str, object],
    group: str,
    signed_value: str,
    absolute_value: str,
    prior_context: str,
) -> str:
    """Format existing evidence for a wrapped, copyable view without recomputing it."""
    fields = [
        ("Participant", item.get("participant_id")),
        ("Recording", item.get("recording_id")),
        ("Session / visit", _session_text(item)),
        ("Group", group),
        ("Condition", item.get("condition")),
        ("Electrode", item.get("electrode")),
        ("Finding", _finding_kind_text(item)),
        ("Signed value", signed_value),
        ("Absolute value", absolute_value),
        ("Band", item.get("band_crossed") or item.get("severity")),
        ("Harmonics", _harmonic_text(item)),
        ("Analysis window", _analysis_window_text(item)),
        ("Independent QC", _independent_qc_text(item)),
    ]
    text = "\n\n".join(f"{label}: {value or 'Unavailable'}" for label, value in fields)
    if prior_context:
        text += f"\n\n{prior_context}\nChoose a new decision for this review."
    return text


def _review_findings(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = report.get("review_findings")
    return [
        row for row in _mapping_rows(value if value is not None else report.get("flags"))
        if finding_section(row) is not None
    ]


def _technical_context_rows(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        row
        for row in _mapping_rows(report.get("cohort_relative_rows"))
        if str(row.get("status") or "") != "complete"
        and finding_section(row) is not None
    ]


def _outcome_text(report: Mapping[str, object]) -> str:
    findings = _review_findings(report)
    scope = str(report.get("identity_scope") or "participant")
    identities = {
        str(
            (
                row.get("recording_id")
                if scope == "recording"
                else row.get("participant_id")
            )
            or ""
        )
        for row in findings
    }
    identities.discard("")
    unit = "recording" if scope == "recording" else "participant"
    return (
        f"{_count_phrase(len(findings), 'finding')} across "
        f"{_count_phrase(len(identities), unit)} need an explicit decision. "
        "No electrode, condition, recording, or participant will be excluded automatically."
    )


def _finding_text(summary: Mapping[str, object]) -> str:
    max_value = float(summary.get("max_abs_summed_bca_uv") or 0.0)
    warning_count = int(summary.get("warning_cell_count") or 0)
    extreme_count = int(summary.get("extreme_electrode_count") or 0)
    parts = [f"max absolute value {max_value:.3f} uV"]
    if warning_count:
        parts.append(_count_phrase(warning_count, "flagged value"))
    if extreme_count:
        parts.append(_count_phrase(extreme_count, "extreme electrode"))
    return "; ".join(parts)


def _finding_kind_text(item: Mapping[str, object]) -> str:
    if item.get("finding_type") == "cohort_relative_summed_bca_context":
        return "Cohort-relative " + str(item.get("metric") or "context").replace(
            "_", " "
        )
    return "Absolute electrode summed BCA"


def _value_texts(item: Mapping[str, object]) -> tuple[str, str]:
    if item.get("finding_type") == "cohort_relative_summed_bca_context":
        raw_value = item.get("value_uv")
        if raw_value is None:
            raw_value = item.get("abs_summed_bca_uv")
        if raw_value is None:
            return "Unavailable", "Unavailable"
        value = float(raw_value)
        return f"{value:.3f} uV", f"{abs(value):.3f} uV"
    signed = float(item.get("summed_bca_uv") or 0.0)
    absolute = float(item.get("abs_summed_bca_uv") or abs(signed))
    return f"{signed:.3f} uV", f"{absolute:.3f} uV"


def _harmonic_text(item: Mapping[str, object]) -> str:
    values = item.get("selected_harmonics_hz") or []
    if not isinstance(values, (list, tuple)):
        return "Unavailable"
    if not values:
        return "0: None"
    return (
        f"{len(values)}: "
        + ", ".join(f"{float(value):g}" for value in values)
        + " Hz"
    )


def _analysis_window_text(item: Mapping[str, object]) -> str:
    cycles = item.get("expected_analyzed_oddball_cycles")
    duration = item.get("analyzed_duration_seconds")
    if cycles in (None, "") and duration in (None, ""):
        return "Unavailable"
    return f"{cycles} cycles / {float(duration):g} s"


def _independent_qc_text(item: Mapping[str, object]) -> str:
    evidence = item.get("independent_qc")
    if isinstance(evidence, (list, tuple)) and evidence:
        return "; ".join(str(value) for value in evidence)
    status = str(item.get("independent_qc_status") or "").strip()
    return status.replace("_", " ") or "Not available"


def _technical_context_text(item: Mapping[str, object]) -> str:
    identity = str(item.get("recording_id") or item.get("participant_id") or "")
    condition = str(item.get("condition") or "")
    electrode = str(item.get("electrode") or "")
    reasons = ", ".join(str(value) for value in item.get("reason_codes") or [])
    return f"{identity} / {condition} / {electrode}: {reasons or item.get('status') or 'unavailable'}"


def _session_text(item: Mapping[str, object]) -> str:
    label = str(item.get("session_label") or item.get("session_id") or "").strip()
    visit = item.get("visit_index")
    if visit not in (None, ""):
        suffix = f"visit {visit}"
        return f"{label} ({suffix})" if label else suffix
    return label


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else plural or singular + 's'}"


def _threshold_text(report: Mapping[str, object]) -> str:
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), Mapping) else {}
    return (
        "Experimental absolute-value review bands: warning above "
        f"{thresholds.get('warning_summed_bca_uv', 10)} uV; strong warning above "
        f"{thresholds.get('strong_warning_summed_bca_uv', 50)} uV; extreme review above "
        f"{thresholds.get('extreme_review_summed_bca_uv', 250)} uV. "
        "These are review limits and never automatic exclusions."
    )


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


__all__ = ["FrequencyDomainQcReviewDialog"]

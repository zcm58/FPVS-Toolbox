"""Modal, recording-aware review for experimental summed-BCA findings."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    StatusBanner,
    SubsectionHeaderLabel,
    SurfaceSize,
    make_action_button,
)
from Main_App.processing.frequency_domain_qc import (
    DECISION_EXCLUDE_CONDITION,
    DECISION_EXCLUDE_CONDITION_ELECTRODE,
    DECISION_EXCLUDE_PARTICIPANT,
    DECISION_EXCLUDE_RECORDING,
    DECISION_RETAIN,
    SUMMED_BCA_SCREENING_BRIEF_TEXT,
    validate_frequency_domain_qc_review_decisions,
)
from Main_App.processing.frequency_qc_identity import frequency_qc_review_rows

_CHOOSE_DECISION = ""
_DECISION_LABELS = {
    _CHOOSE_DECISION: "Choose a decision…",
    DECISION_RETAIN: "Retain this finding",
    DECISION_EXCLUDE_CONDITION_ELECTRODE: "Exclude electrode in this condition",
    DECISION_EXCLUDE_CONDITION: "Exclude this condition",
    DECISION_EXCLUDE_RECORDING: "Exclude this recording",
    DECISION_EXCLUDE_PARTICIPANT: "Exclude whole participant",
}


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
        self._findings = _review_findings(report)
        self._evidence_texts: list[str] = []
        self._row_controls: list[tuple[QComboBox, QLineEdit]] = []
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
                "Experimental screening: review unusually large summed-BCA responses.",
                self,
                variant="warning",
            )
        )
        outcome_label = QLabel(_outcome_text(self._report), self)
        outcome_label.setObjectName("frequency_domain_qc_outcome_label")
        outcome_label.setWordWrap(True)
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
        self.search_edit = QLineEdit(findings_panel)
        self.search_edit.setObjectName("frequency_domain_qc_search")
        self.search_edit.setPlaceholderText("Search participant, condition, electrode or evidence…")
        self.search_edit.setAccessibleName("Search frequency-domain findings")
        self.search_edit.setClearButtonEnabled(True)
        findings_layout.addWidget(self.search_edit)

        self.details_table = QTableWidget(findings_panel)
        self.details_table.setObjectName("frequency_domain_qc_details_table")
        self.details_table.setColumnCount(5)
        identity_heading = (
            "Recording" if self._identity_scope == "recording" else "Participant"
        )
        self.details_table.setHorizontalHeaderLabels(
            [identity_heading, "Condition", "Electrode / ROI", "|Value|", "Decision"]
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
        detail_layout.addWidget(SubsectionHeaderLabel("Selected finding", detail_panel))
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
        detail_layout.addWidget(self.detail_tabs, 1)

        self.decision_stack = QStackedWidget(detail_panel)
        self.decision_stack.setObjectName("frequency_domain_qc_decision_stack")
        self.decision_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        detail_layout.addWidget(self.decision_stack)
        self.next_button = make_action_button(
            "Next undecided", variant="secondary", parent=detail_panel
        )
        self.next_button.setObjectName("frequency_domain_qc_next_undecided")
        self.next_button.setToolTip("Go to the next undecided finding, including hidden search results.")
        self.next_button.clicked.connect(self._select_next_undecided)
        detail_layout.addWidget(self.next_button)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([650, 470])

        self._populate_details_table()
        self.details_table.currentCellChanged.connect(self._show_finding)
        self.search_edit.textChanged.connect(self._filter_findings)
        self._update_progress()
        if self._findings:
            self.details_table.setCurrentCell(0, 0)
            self._show_finding(0)
        else:
            self._show_finding(-1)

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
                str(item.get("electrode") or item.get("roi") or ""),
                absolute_value,
                "Undecided",
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                table_item.setToolTip(value)
                if column == 0:
                    table_item.setData(Qt.UserRole, fingerprint)
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
            if item.get("electrode"):
                allowed.insert(2, DECISION_EXCLUDE_CONDITION_ELECTRODE)
            if self._identity_scope == "recording":
                allowed.append(DECISION_EXCLUDE_RECORDING)
            allowed.append(DECISION_EXCLUDE_PARTICIPANT)
            for decision in allowed:
                combo.addItem(_DECISION_LABELS[decision], decision)
            page_layout.addWidget(combo)
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
            reason.setEnabled(False)
            self.decision_stack.addWidget(page)
            self._decision_controls[fingerprint] = (combo, reason)
            self._row_controls.append((combo, reason))
            self._evidence_texts.append(
                _finding_evidence_text(item, group, signed_value, absolute_value, context)
            )

    def _show_finding(self, row: int, *_unused: int) -> None:
        if row < 0 or self.details_table.isRowHidden(row):
            self.evidence_view.setPlainText("No matching findings. Clear the search to show all findings.")
            self.decision_stack.setEnabled(False)
            return
        self.evidence_view.setPlainText(self._evidence_texts[row])
        self.decision_stack.setCurrentIndex(row)
        self.decision_stack.setEnabled(True)
        self.detail_tabs.setCurrentIndex(0)

    def _decision_changed(self, row: int) -> None:
        combo, reason = self._row_controls[row]
        decision = str(combo.currentData() or "")
        reason.setEnabled(decision not in {_CHOOSE_DECISION, DECISION_RETAIN})
        status = {
            _CHOOSE_DECISION: "Undecided",
            DECISION_RETAIN: "Retain",
            DECISION_EXCLUDE_CONDITION_ELECTRODE: "Excl. electrode",
            DECISION_EXCLUDE_CONDITION: "Excl. condition",
            DECISION_EXCLUDE_RECORDING: "Excl. recording",
            DECISION_EXCLUDE_PARTICIPANT: "Excl. participant",
        }[decision]
        cell = self.details_table.item(row, 4)
        cell.setText(status)
        cell.setToolTip(_DECISION_LABELS[decision])
        self._update_progress()

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

    def _filter_findings(self, _text: str) -> None:
        terms = self.search_edit.text().casefold().split()
        for row, evidence in enumerate(self._evidence_texts):
            self.details_table.setRowHidden(
                row, not all(term in evidence.casefold() for term in terms)
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
        self._update_progress()

    def _select_next_undecided(self) -> None:
        count = len(self._findings)
        current = self.details_table.currentRow()
        for offset in range(1, count + 1):
            row = (current + offset) % count
            combo, _ = self._row_controls[row]
            if combo.currentData():
                continue
            if self.details_table.isRowHidden(row):
                self.search_edit.clear()
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
        ("Electrode / ROI", item.get("electrode") or item.get("roi")),
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
    return _mapping_rows(value if value is not None else report.get("flags"))


def _technical_context_rows(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        row
        for row in _mapping_rows(report.get("cohort_relative_rows"))
        if str(row.get("status") or "") != "complete"
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
    roi = str(item.get("roi") or "")
    reasons = ", ".join(str(value) for value in item.get("reason_codes") or [])
    return f"{identity} / {condition} / {roi}: {reasons or item.get('status') or 'unavailable'}"


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
    settings = report.get("screening_settings") if isinstance(report.get("screening_settings"), Mapping) else {}
    return (
        "Experimental absolute-value review bands: warning above "
        f"{thresholds.get('warning_summed_bca_uv', 10)} uV; strong warning above "
        f"{thresholds.get('strong_warning_summed_bca_uv', 50)} uV; extreme review above "
        f"{thresholds.get('extreme_review_summed_bca_uv', 250)} uV. "
        "Cohort-relative context uses median/MAD, scaled-IQR, and zero-spread "
        "fallbacks with warning/extreme robust scores "
        f"{settings.get('cohort_warning_robust_score', 6)}/"
        f"{settings.get('cohort_extreme_robust_score', 10)}. These are review "
        "limits and never automatic exclusions."
    )


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


__all__ = ["FrequencyDomainQcReviewDialog"]

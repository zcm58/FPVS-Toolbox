"""Modal, recording-aware review for experimental summed-BCA findings."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import ActionRow, StatusBanner, make_action_button
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


class FrequencyDomainQcReviewDialog(QDialog):
    """Collect explicit choices without treating a BCA flag as an exclusion."""

    def __init__(
        self,
        report: Mapping[str, object],
        parent: QWidget | None = None,
        *,
        participant_groups: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(parent)
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
        self._submitted_decisions: tuple[dict[str, object], ...] = ()
        self.setWindowTitle("Experimental Summed-BCA Review")
        self.setModal(True)
        self.setMinimumSize(1000, 650)
        self.resize(1220, 780)
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
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        layout.addWidget(
            StatusBanner(
                "Review each flagged frequency-domain finding before final harmonics are finalized.",
                self,
                variant="warning",
            )
        )
        explanation = QLabel(SUMMED_BCA_SCREENING_BRIEF_TEXT, self)
        explanation.setObjectName("frequency_domain_qc_experimental_explanation")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        outcome_label = QLabel(_outcome_text(self._report), self)
        outcome_label.setObjectName("frequency_domain_qc_outcome_label")
        outcome_label.setWordWrap(True)
        layout.addWidget(outcome_label)

        self.summary_table = QTableWidget(self)
        self.summary_table.setObjectName("frequency_domain_qc_summary_table")
        self.summary_table.setColumnCount(6)
        identity_heading = (
            "Recording" if self._identity_scope == "recording" else "Participant"
        )
        self.summary_table.setHorizontalHeaderLabels(
            [
                identity_heading,
                "Participant",
                "Session / visit",
                "Group",
                "Findings",
                "Automatic action",
            ]
        )
        self.summary_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.summary_table.setMaximumHeight(185)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.summary_table.horizontalHeader()
        for column in (0, 1, 2, 3):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.summary_table)
        self._populate_summary_table()

        review_label = QLabel("Decide Every Finding", self)
        review_label.setObjectName("frequency_domain_qc_review_label")
        layout.addWidget(review_label)
        self.details_table = QTableWidget(self)
        self.details_table.setObjectName("frequency_domain_qc_details_table")
        self.details_table.setColumnCount(14)
        self.details_table.setHorizontalHeaderLabels(
            [
                "Participant",
                "Recording",
                "Session / visit",
                "Condition",
                "Electrode / ROI",
                "Finding",
                "Signed value",
                "Absolute value",
                "Band",
                "Harmonics",
                "Analysis window",
                "Independent QC",
                "Decision",
                "Reason (optional)",
            ]
        )
        self.details_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.details_table.horizontalHeader()
        for column in range(12):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(12, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(13, QHeaderView.Stretch)
        layout.addWidget(self.details_table, 3)
        self._populate_details_table()

        technical_rows = _technical_context_rows(self._report)
        if technical_rows:
            technical_label = QLabel(
                f"{len(technical_rows)} cohort-context input(s) are unavailable. "
                "They were not silently treated as passes; review the recorded technical statuses.",
                self,
            )
            technical_label.setObjectName("frequency_domain_qc_technical_status")
            technical_label.setWordWrap(True)
            layout.addWidget(technical_label)
            technical_details = QPlainTextEdit(self)
            technical_details.setObjectName(
                "frequency_domain_qc_technical_status_details"
            )
            technical_details.setReadOnly(True)
            technical_details.setMaximumHeight(90)
            technical_details.setPlainText(
                "\n".join(_technical_context_text(row) for row in technical_rows)
            )
            layout.addWidget(technical_details)

        tools = QWidget(self)
        tools_layout = QHBoxLayout(tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_button = QToolButton(tools)
        self.rules_button.setText("Show screening rules")
        self.rules_button.setCheckable(True)
        self.rules_button.toggled.connect(self._toggle_rules)
        tools_layout.addWidget(self.rules_button)
        tools_layout.addStretch(1)
        layout.addWidget(tools)
        self.rules_label = QLabel(_threshold_text(self._report), self)
        self.rules_label.setObjectName("frequency_domain_qc_rules_label")
        self.rules_label.setWordWrap(True)
        self.rules_label.setVisible(False)
        layout.addWidget(self.rules_label)

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

    def _populate_summary_table(self) -> None:
        summaries = [
            row
            for row in frequency_qc_review_rows(self._report)
            if row.get("pause_review")
        ]
        self.summary_table.setRowCount(len(summaries))
        for row_index, item in enumerate(summaries):
            participant_id = str(item.get("participant_id") or "")
            recording_id = str(item.get("recording_id") or "")
            values = (
                recording_id or participant_id,
                participant_id,
                _session_text(item),
                self._group_for_participant(participant_id),
                _finding_text(item),
                "None — review flag only",
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                self.summary_table.setItem(row_index, column, table_item)
        self.summary_table.resizeRowsToContents()

    def _populate_details_table(self) -> None:
        findings = _review_findings(self._report)
        existing = {
            str(row.get("finding_fingerprint") or ""): row
            for row in [
                *_mapping_rows(self._report.get("review_decisions")),
                *_mapping_rows(self._report.get("review_prefill_decisions")),
            ]
        }
        self.details_table.setRowCount(len(findings))
        for row_index, item in enumerate(findings):
            fingerprint = str(item.get("finding_fingerprint") or "")
            signed_value, absolute_value = _value_texts(item)
            values = (
                str(item.get("participant_id") or ""),
                str(item.get("recording_id") or ""),
                _session_text(item),
                str(item.get("condition") or ""),
                str(item.get("electrode") or item.get("roi") or ""),
                _finding_kind_text(item),
                signed_value,
                absolute_value,
                str(item.get("band_crossed") or item.get("severity") or ""),
                _harmonic_text(item),
                _analysis_window_text(item),
                _independent_qc_text(item),
            )
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                if column in {6, 7}:
                    table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.details_table.setItem(row_index, column, table_item)

            combo = QComboBox(self.details_table)
            combo.setObjectName(f"frequency_domain_qc_decision_{row_index}")
            allowed = [_CHOOSE_DECISION, DECISION_RETAIN, DECISION_EXCLUDE_CONDITION]
            if item.get("electrode"):
                allowed.insert(2, DECISION_EXCLUDE_CONDITION_ELECTRODE)
            if self._identity_scope == "recording":
                allowed.append(DECISION_EXCLUDE_RECORDING)
            allowed.append(DECISION_EXCLUDE_PARTICIPANT)
            for decision in allowed:
                combo.addItem(_DECISION_LABELS[decision], decision)
            reason = QLineEdit(self.details_table)
            reason.setObjectName(f"frequency_domain_qc_reason_{row_index}")
            reason.setPlaceholderText("Optional reason")
            saved = existing.get(fingerprint)
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
                lambda _index, current=combo, edit=reason: edit.setEnabled(
                    str(current.currentData() or "")
                    not in {_CHOOSE_DECISION, DECISION_RETAIN}
                )
            )
            reason.setEnabled(
                str(combo.currentData() or "")
                not in {_CHOOSE_DECISION, DECISION_RETAIN}
            )
            self.details_table.setCellWidget(row_index, 12, combo)
            self.details_table.setCellWidget(row_index, 13, reason)
            self._decision_controls[fingerprint] = (combo, reason)
        self.details_table.resizeRowsToContents()

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

    def _toggle_rules(self, checked: bool) -> None:
        self.rules_label.setVisible(bool(checked))
        self.rules_button.setText(
            "Hide screening rules" if checked else "Show screening rules"
        )


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

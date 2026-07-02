"""Modal review dialog for project-wide frequency-domain QC flags."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import ActionRow, StatusBanner, make_action_button
from Main_App.processing.frequency_domain_qc import (
    MANUAL_EXCLUSION_REASONS,
    WARNING_REASON_UNUSUAL_VALUES,
)


class FrequencyDomainQcReviewDialog(QDialog):
    """Collect reviewed manual participant exclusions before post-processing resumes."""

    def __init__(
        self,
        report: Mapping[str, object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._report = report
        self._manual_controls: dict[str, tuple[QCheckBox, QComboBox]] = {}
        self.setWindowTitle("Frequency-Domain QC Review")
        self.setModal(True)
        self.resize(980, 680)
        self._build_ui()

    def manual_participant_reasons(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for participant_id, (checkbox, combo) in self._manual_controls.items():
            if checkbox.isEnabled() and checkbox.isChecked():
                out[participant_id] = str(combo.currentText() or WARNING_REASON_UNUSUAL_VALUES)
        return out

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        banner = StatusBanner(
            (
                "FPVS Toolbox found unusual frequency-domain values that need "
                "review before final harmonics are finalized."
            ),
            self,
            variant="warning",
        )
        layout.addWidget(banner)

        outcome_label = QLabel(_outcome_text(self._report), self)
        outcome_label.setObjectName("frequency_domain_qc_outcome_label")
        outcome_label.setWordWrap(True)
        layout.addWidget(outcome_label)

        summary_label = QLabel("Review Needed", self)
        summary_label.setObjectName("frequency_domain_qc_summary_label")
        layout.addWidget(summary_label)

        self.summary_table = QTableWidget(self)
        self.summary_table.setObjectName("frequency_domain_qc_summary_table")
        self.summary_table.setColumnCount(5)
        self.summary_table.setHorizontalHeaderLabels(
            [
                "Participant",
                "Finding",
                "Automatic action",
                "Exclude whole participant",
                "Reason",
            ]
        )
        self.summary_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.NoSelection)
        header = self.summary_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.summary_table, 2)
        self._populate_summary_table()

        rules_header = QWidget(self)
        rules_layout = QHBoxLayout(rules_header)
        rules_layout.setContentsMargins(0, 0, 0, 0)
        self.rules_button = QToolButton(rules_header)
        self.rules_button.setText("Show QC rules")
        self.rules_button.setCheckable(True)
        self.rules_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.rules_button.toggled.connect(self._toggle_rules)
        rules_layout.addWidget(self.rules_button)

        self.details_button = QToolButton(rules_header)
        self.details_button.setText("Show audit details")
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_button.toggled.connect(self._toggle_details)
        rules_layout.addWidget(self.details_button)
        rules_layout.addStretch(1)
        layout.addWidget(rules_header)

        self.rules_label = QLabel(_threshold_text(self._report), self)
        self.rules_label.setObjectName("frequency_domain_qc_rules_label")
        self.rules_label.setWordWrap(True)
        self.rules_label.setVisible(False)
        layout.addWidget(self.rules_label)

        self.details_table = QTableWidget(self)
        self.details_table.setObjectName("frequency_domain_qc_details_table")
        self.details_table.setColumnCount(5)
        self.details_table.setHorizontalHeaderLabels(
            ["Participant", "Condition", "Electrode", "Summed BCA", "Severity"]
        )
        self.details_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.details_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.details_table.setVisible(False)
        layout.addWidget(self.details_table, 2)
        self._populate_details_table()

        actions = ActionRow(self, alignment=Qt.AlignRight)
        actions.setObjectName("frequency_domain_qc_actions")
        cancel_btn = make_action_button("Cancel", variant="secondary", parent=actions)
        continue_btn = make_action_button(
            "Continue with reviewed exclusions",
            variant="primary",
            parent=actions,
        )
        cancel_btn.clicked.connect(self.reject)
        continue_btn.clicked.connect(self.accept)
        actions.add_button(cancel_btn)
        actions.add_button(continue_btn)
        layout.addWidget(actions)

    def _populate_summary_table(self) -> None:
        summaries = [
            item
            for item in _mapping_rows(self._report.get("participant_summaries"))
            if item.get("pause_review")
        ]
        manual_existing = {
            str(item.get("participant_id") or "")
            for item in _mapping_rows(self._report.get("manual_participant_exclusions"))
        }
        self.summary_table.setRowCount(len(summaries))
        for row, item in enumerate(summaries):
            participant_id = str(item.get("participant_id") or "")
            auto_participant = bool(item.get("auto_participant_excluded"))
            values = [
                participant_id,
                _finding_text(item),
                _automatic_action_text(item),
            ]
            for column, text in enumerate(values):
                table_item = QTableWidgetItem(text)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                self.summary_table.setItem(row, column, table_item)

            checkbox = QCheckBox(self.summary_table)
            checkbox.setChecked(auto_participant or participant_id in manual_existing)
            checkbox.setEnabled(not auto_participant)
            checkbox.setToolTip(
                "Automatic participant exclusions cannot be changed here."
                if auto_participant
                else "Optionally remove this whole participant from frequency-domain outputs."
            )
            self.summary_table.setCellWidget(row, 3, _centered_cell_widget(checkbox))

            combo = QComboBox(self.summary_table)
            combo.addItems(list(MANUAL_EXCLUSION_REASONS))
            combo.setCurrentText(WARNING_REASON_UNUSUAL_VALUES)
            combo.setEnabled(checkbox.isEnabled() and checkbox.isChecked())
            checkbox.toggled.connect(combo.setEnabled)
            self.summary_table.setCellWidget(row, 4, combo)
            self._manual_controls[participant_id] = (checkbox, combo)

        self.summary_table.resizeColumnsToContents()
        self.summary_table.resizeRowsToContents()

    def _populate_details_table(self) -> None:
        flags = _mapping_rows(self._report.get("flags"))
        self.details_table.setRowCount(len(flags))
        for row, item in enumerate(flags):
            values = [
                str(item.get("participant_id") or ""),
                str(item.get("condition") or ""),
                str(item.get("electrode") or ""),
                f"{float(item.get('summed_bca_uv') or 0.0):.3f}",
                str(item.get("severity") or ""),
            ]
            for column, text in enumerate(values):
                table_item = QTableWidgetItem(text)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                if column == 3:
                    table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.details_table.setItem(row, column, table_item)
        self.details_table.resizeColumnsToContents()
        self.details_table.resizeRowsToContents()

    def _toggle_rules(self, checked: bool) -> None:
        self.rules_label.setVisible(bool(checked))
        self.rules_button.setText("Hide QC rules" if checked else "Show QC rules")

    def _toggle_details(self, checked: bool) -> None:
        self.details_table.setVisible(bool(checked))
        self.details_button.setText("Hide audit details" if checked else "Show audit details")


def _outcome_text(report: Mapping[str, object]) -> str:
    summaries = [
        item
        for item in _mapping_rows(report.get("participant_summaries"))
        if item.get("pause_review")
    ]
    auto_electrodes = _mapping_rows(report.get("auto_participant_electrode_exclusions"))
    auto_participants = _mapping_rows(report.get("auto_participant_exclusions"))
    need_verb = "needs" if len(summaries) == 1 else "need"
    parts = [
        f"{_count_phrase(len(summaries), 'participant')} {need_verb} review.",
        (
            f"{_count_phrase(len(auto_electrodes), 'participant-electrode pair')} "
            "will be excluded automatically."
        ),
    ]
    if auto_participants:
        parts.append(
            f"{_count_phrase(len(auto_participants), 'participant')} "
            "will be removed automatically."
        )
    else:
        parts.append("No participant will be removed unless you choose that below.")
    parts.append(
        "Use the checkbox only when you want to remove the whole participant."
    )
    return " ".join(parts)


def _finding_text(summary: Mapping[str, object]) -> str:
    electrode = str(summary.get("max_electrode") or "").strip()
    condition = str(summary.get("max_condition") or "").strip()
    max_value = float(summary.get("max_abs_summed_bca_uv") or 0.0)
    warning_count = int(summary.get("warning_cell_count") or 0)
    hard_count = int(summary.get("hard_excluded_electrode_count") or 0)
    location = "/".join(part for part in (condition, electrode) if part)
    lead = f"Max abs summed BCA {max_value:.3f} uV"
    if location:
        lead += f" at {location}"
    details = []
    if hard_count:
        details.append(_count_phrase(hard_count, "hard electrode"))
    if warning_count:
        details.append(_count_phrase(warning_count, "warning cell"))
    return f"{lead}; {', '.join(details)}" if details else lead


def _automatic_action_text(summary: Mapping[str, object]) -> str:
    if bool(summary.get("auto_participant_excluded")):
        return "Exclude whole participant automatically"
    hard_count = int(summary.get("hard_excluded_electrode_count") or 0)
    if hard_count:
        return f"Exclude {_count_phrase(hard_count, 'participant-electrode pair')}; keep participant"
    reasons = [str(reason) for reason in summary.get("pause_reasons", []) or []]
    if reasons:
        return "Review only; no automatic exclusion"
    return "No automatic action"


def _count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    if count == 1:
        return f"1 {singular}"
    return f"{count} {plural or singular + 's'}"


def _threshold_text(report: Mapping[str, object]) -> str:
    thresholds = report.get("thresholds") if isinstance(report.get("thresholds"), Mapping) else {}
    return (
        "Thresholds: warning > "
        f"{thresholds.get('warning_summed_bca_uv', 10)} uV; strong warning > "
        f"{thresholds.get('strong_warning_summed_bca_uv', 50)} uV; automatic "
        f"electrode exclusion > {thresholds.get('hard_electrode_summed_bca_uv', 250)} uV; "
        "automatic participant exclusion when more than "
        f"{thresholds.get('hard_participant_unique_electrodes', 10)} unique electrodes are hard-excluded."
    )


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _centered_cell_widget(widget: QWidget) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addStretch(1)
    layout.addWidget(widget)
    layout.addStretch(1)
    return container


__all__ = ["FrequencyDomainQcReviewDialog"]

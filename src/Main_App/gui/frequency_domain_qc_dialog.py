"""Modal review dialog for project-wide frequency-domain QC flags."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
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
                "Review the flagged participants before FPVS Toolbox recalculates "
                "the final significant harmonic list. Automatic exclusions are "
                "required; manual participant exclusions are optional."
            ),
            self,
            variant="warning",
        )
        layout.addWidget(banner)

        threshold_label = QLabel(_threshold_text(self._report), self)
        threshold_label.setWordWrap(True)
        layout.addWidget(threshold_label)

        summary_label = QLabel("Participant Summary", self)
        summary_label.setObjectName("frequency_domain_qc_summary_label")
        layout.addWidget(summary_label)

        self.summary_table = QTableWidget(self)
        self.summary_table.setObjectName("frequency_domain_qc_summary_table")
        self.summary_table.setColumnCount(7)
        self.summary_table.setHorizontalHeaderLabels(
            [
                "Participant",
                "Reason",
                "Max abs uV",
                "Warning cells",
                "Hard electrodes",
                "Manual exclude",
                "Manual reason",
            ]
        )
        self.summary_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.setSelectionMode(QAbstractItemView.NoSelection)
        layout.addWidget(self.summary_table, 2)
        self._populate_summary_table()

        details_header = QWidget(self)
        details_layout = QHBoxLayout(details_header)
        details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_button = QToolButton(details_header)
        self.details_button.setText("Show flagged details")
        self.details_button.setCheckable(True)
        self.details_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.details_button.toggled.connect(self._toggle_details)
        details_layout.addWidget(self.details_button)
        details_layout.addStretch(1)
        layout.addWidget(details_header)

        self.details_table = QTableWidget(self)
        self.details_table.setObjectName("frequency_domain_qc_details_table")
        self.details_table.setColumnCount(6)
        self.details_table.setHorizontalHeaderLabels(
            ["Participant", "Condition", "Electrode", "Summed BCA", "Severity", "Workbook"]
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
            reasons = ", ".join(str(reason) for reason in item.get("pause_reasons", []) or [])
            values = [
                participant_id,
                reasons,
                f"{float(item.get('max_abs_summed_bca_uv') or 0.0):.3f}",
                str(int(item.get("warning_cell_count") or 0)),
                str(int(item.get("hard_excluded_electrode_count") or 0)),
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
                else "Exclude this participant from project-wide frequency-domain outputs."
            )
            self.summary_table.setCellWidget(row, 5, _centered_cell_widget(checkbox))

            combo = QComboBox(self.summary_table)
            combo.addItems(list(MANUAL_EXCLUSION_REASONS))
            combo.setCurrentText(WARNING_REASON_UNUSUAL_VALUES)
            combo.setEnabled(checkbox.isEnabled() and checkbox.isChecked())
            checkbox.toggled.connect(combo.setEnabled)
            self.summary_table.setCellWidget(row, 6, combo)
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
                str(item.get("workbook_path") or ""),
            ]
            for column, text in enumerate(values):
                table_item = QTableWidgetItem(text)
                table_item.setFlags(table_item.flags() & ~Qt.ItemIsEditable)
                if column == 3:
                    table_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.details_table.setItem(row, column, table_item)
        self.details_table.resizeColumnsToContents()
        self.details_table.resizeRowsToContents()

    def _toggle_details(self, checked: bool) -> None:
        self.details_table.setVisible(bool(checked))
        self.details_button.setText("Hide flagged details" if checked else "Show flagged details")


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

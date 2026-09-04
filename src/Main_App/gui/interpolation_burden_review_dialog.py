"""Modal review for current QC-07 interpolation-burden findings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    StatusBanner,
    SurfaceSize,
    make_action_button,
)
from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_DECISION_EXCLUDE,
    INTERPOLATION_BURDEN_DECISION_RETAIN,
    INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
    INTERPOLATION_BURDEN_SCOPE_RECORDING,
)
from Main_App.processing.interpolation_burden_review import (
    InterpolationBurdenReviewBatch,
    InterpolationBurdenReviewChoice,
    InterpolationBurdenReviewError,
)


class InterpolationBurdenReviewDialog(AppDialog):
    """Require an unambiguous decision and reason for every pending finding."""

    def __init__(
        self,
        batch: InterpolationBurdenReviewBatch,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Interpolation Burden Review",
            parent,
            size=SurfaceSize(1180, 650, min_width=900, min_height=520),
        )
        if not batch.items:
            raise ValueError("Interpolation-burden review has no pending findings.")
        self.setObjectName("interpolation_burden_review_dialog")
        self.setModal(True)
        self._batch = batch
        self._decision_controls: dict[str, QComboBox] = {}
        self._scope_controls: dict[str, QComboBox] = {}
        self._reason_controls: dict[str, QLineEdit] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        banner = StatusBanner(
            (
                f"{len(self._batch.items)} recording"
                f"{'s' if len(self._batch.items) != 1 else ''} exceeded the "
                "5% interpolation-burden review threshold. This threshold is a "
                "review prompt, not evidence that a recording is unusable."
            ),
            self,
            variant="warning",
        )
        banner.setObjectName("interpolation_burden_review_banner")
        self.root_layout.addWidget(banner)

        explanation = QLabel(
            (
                "Review the successfully interpolated electrode locations, choose "
                "Retain or Exclude, and record a reason for every row. No choice is "
                "selected automatically. Canceling or closing this dialog skips "
                "downstream post-processing."
            ),
            self,
        )
        explanation.setObjectName("interpolation_burden_review_explanation")
        explanation.setWordWrap(True)
        self.root_layout.addWidget(explanation)

        self.error_banner = StatusBanner("", self, variant="error")
        self.error_banner.setObjectName("interpolation_burden_review_error")
        self.error_banner.hide()
        self.root_layout.addWidget(self.error_banner)

        headers = [
            "Participant",
            "Recording",
            "Session / phase-at-visit",
            "Visit",
            "Burden",
            "Interpolated electrodes",
            "Evidence",
            "Decision",
        ]
        if self._batch.is_repeated_session:
            headers.append("Exclusion scope")
        headers.append("Reason")

        self.table = QTableWidget(len(self._batch.items), len(headers), self)
        self.table.setObjectName("interpolation_burden_review_table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        reason_column = len(headers) - 1
        header.setSectionResizeMode(reason_column, QHeaderView.ResizeMode.Stretch)

        for row, item in enumerate(self._batch.items):
            recording_text = item.recording_id or "Ordinary participant recording"
            session_text = item.session_label or item.session_id or "—"
            visit_text = str(item.visit_index) if item.visit_index is not None else "—"
            burden_text = (
                f"{item.finding.numerator}/{item.finding.denominator} "
                f"({item.finding.percentage:.2f}%)"
            )
            electrodes_text = ", ".join(
                item.finding.successfully_interpolated_channels
            )
            evidence_text = (
                "Changed — review again"
                if item.evidence_status == "stale"
                else "New finding"
            )
            for column, value in enumerate(
                (
                    item.participant_id,
                    recording_text,
                    session_text,
                    visit_text,
                    burden_text,
                    electrodes_text,
                    evidence_text,
                )
            ):
                table_item = QTableWidgetItem(value)
                table_item.setFlags(table_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                if column == 4:
                    table_item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(row, column, table_item)

            decision = QComboBox(self.table)
            decision.setObjectName(f"interpolation_burden_decision_{row}")
            decision.addItem("Choose Retain or Exclude…", "")
            decision.addItem("Retain", INTERPOLATION_BURDEN_DECISION_RETAIN)
            decision.addItem("Exclude", INTERPOLATION_BURDEN_DECISION_EXCLUDE)
            decision.setCurrentIndex(0)
            decision.currentIndexChanged.connect(self.error_banner.hide)
            self.table.setCellWidget(row, 7, decision)
            self._decision_controls[item.processing_id] = decision

            next_column = 8
            if self._batch.is_repeated_session:
                scope = QComboBox(self.table)
                scope.setObjectName(f"interpolation_burden_scope_{row}")
                # Recording is deliberately first and selected by default. A
                # participant-wide action remains a separate explicit choice.
                scope.addItem("This recording", INTERPOLATION_BURDEN_SCOPE_RECORDING)
                scope.addItem(
                    "Participant (all visits)",
                    INTERPOLATION_BURDEN_SCOPE_PARTICIPANT,
                )
                scope.setCurrentIndex(0)
                scope.currentIndexChanged.connect(self.error_banner.hide)
                self.table.setCellWidget(row, next_column, scope)
                self._scope_controls[item.processing_id] = scope
                next_column += 1

            reason = QLineEdit(self.table)
            reason.setObjectName(f"interpolation_burden_reason_{row}")
            reason.setPlaceholderText("Required review reason")
            reason.textChanged.connect(self.error_banner.hide)
            self.table.setCellWidget(row, next_column, reason)
            self._reason_controls[item.processing_id] = reason

        self.table.resizeRowsToContents()
        self.root_layout.addWidget(self.table, 1)

        actions = ActionRow(self)
        actions.setObjectName("interpolation_burden_review_actions")
        self.cancel_button = actions.add_button(
            make_action_button("Cancel", variant="secondary", parent=actions)
        )
        self.apply_button = actions.add_button(
            make_action_button("Apply decisions", variant="primary", parent=actions)
        )
        self.cancel_button.setObjectName("interpolation_burden_review_cancel")
        self.apply_button.setObjectName("interpolation_burden_review_apply")
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._validate_and_accept)
        self.root_layout.addWidget(actions)

    def choices(self) -> dict[str, InterpolationBurdenReviewChoice]:
        """Return all explicit choices or raise with a user-facing validation error."""

        choices: dict[str, InterpolationBurdenReviewChoice] = {}
        for item in self._batch.items:
            decision = str(
                self._decision_controls[item.processing_id].currentData() or ""
            )
            reason = self._reason_controls[item.processing_id].text().strip()
            scope = (
                str(self._scope_controls[item.processing_id].currentData())
                if self._batch.is_repeated_session
                else INTERPOLATION_BURDEN_SCOPE_PARTICIPANT
            )
            try:
                choices[item.processing_id] = InterpolationBurdenReviewChoice(
                    decision=decision,
                    reason=reason,
                    exclusion_scope=scope,
                )
            except InterpolationBurdenReviewError as exc:
                raise InterpolationBurdenReviewError(
                    f"{item.processing_id}: {exc}"
                ) from exc
        return choices

    def _validate_and_accept(self) -> None:
        try:
            self.choices()
        except InterpolationBurdenReviewError as exc:
            self.error_banner.set_text(str(exc))
            self.error_banner.show()
            return
        self.accept()


__all__ = ["InterpolationBurdenReviewDialog"]

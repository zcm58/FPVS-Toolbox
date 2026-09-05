"""Modal QC-16 review for recording-wide kurtosis channel findings."""

from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCloseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
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
from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    BORDER_COLOR,
    SURFACE_ALT_BG,
    TEXT_MUTED,
)
from Main_App.processing.kurtosis_qc import (
    KURTOSIS_DECISION_APPROVE,
    KURTOSIS_DECISION_REJECT,
    KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD,
    KurtosisQCError,
    build_kurtosis_review_decision,
    qualifies_for_experimental_kurtosis_auto,
)
from Main_App.processing.kurtosis_review_scan import (
    KURTOSIS_REVIEW_PENDING_STALE,
    KurtosisReviewDecisionReconciliation,
    KurtosisReviewItem,
    KurtosisReviewScan,
)


class KurtosisReviewDialogError(ValueError):
    """Raised when an incomplete scan or dialog cannot authorize continuation."""


class KurtosisSignalPreviewWidget(QWidget):
    """Small, presentation-only trace of bounded analyzed-signal evidence."""

    def __init__(
        self,
        values: tuple[float | None, ...],
        unit: str,
        source_sample_count: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("kurtosis_signal_preview")
        self.setMinimumSize(150, 52)
        self.setMaximumHeight(62)
        self.set_signal(values, unit, source_sample_count)

    def set_signal(
        self,
        values: tuple[float | None, ...],
        unit: str,
        source_sample_count: int,
    ) -> None:
        self._values = tuple(values)
        self._unit = str(unit or "uV")
        self._source_sample_count = max(0, int(source_sample_count))
        finite = [float(value) for value in self._values if value is not None]
        if finite:
            self.setToolTip(
                f"{len(self._values)} displayed samples from "
                f"{self._source_sample_count or len(self._values)} analyzed samples; "
                f"range {min(finite):.3g} to {max(finite):.3g} {self._unit}."
            )
        else:
            self.setToolTip("No finite signal preview was available.")
        self.update()

    def paintEvent(self, _event: object) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        bounds = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.fillRect(bounds, QColor(SURFACE_ALT_BG))
        painter.setPen(QPen(QColor(BORDER_COLOR), 1.0))
        painter.drawRoundedRect(bounds, 5.0, 5.0)

        finite = [float(value) for value in self._values if value is not None]
        if not finite:
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(bounds, Qt.AlignmentFlag.AlignCenter, "No finite preview")
            return

        plot = bounds.adjusted(6.0, 5.0, -6.0, -5.0)
        low = min(finite)
        high = max(finite)
        if math.isclose(low, high, rel_tol=0.0, abs_tol=1e-15):
            padding = max(abs(low) * 0.05, 1.0)
            low -= padding
            high += padding
        if low <= 0.0 <= high:
            zero_y = plot.bottom() - ((0.0 - low) / (high - low)) * plot.height()
            painter.setPen(QPen(QColor(BORDER_COLOR), 1.0, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(plot.left(), zero_y), QPointF(plot.right(), zero_y))

        denominator = max(1, len(self._values) - 1)
        segments: list[QPolygonF] = []
        current = QPolygonF()
        for index, value in enumerate(self._values):
            if value is None:
                if current.size() >= 2:
                    segments.append(current)
                current = QPolygonF()
                continue
            x = plot.left() + (index / denominator) * plot.width()
            y = plot.bottom() - ((float(value) - low) / (high - low)) * plot.height()
            current.append(QPointF(x, y))
        if current.size() >= 2:
            segments.append(current)
        painter.setPen(QPen(QColor(ACCENT_COLOR), 1.35))
        for segment in segments:
            painter.drawPolyline(segment)


def _read_only_item(text: str, *, right_aligned: bool = False) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
    if right_aligned:
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item


def _metric_text(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "Unavailable"
    return f"{value:+.3f}" if signed else f"{value:.3f}"


def _recording_text(item: KurtosisReviewItem) -> str:
    details = [item.recording_id]
    session = item.session_label or item.session_id
    if session:
        details.append(session)
    if item.visit_index is not None:
        details.append(f"visit {item.visit_index}")
    return " · ".join(details)


def _fixed_repair_scope_text(item: KurtosisReviewItem) -> str:
    conditions = ", ".join(item.analyzed_conditions)
    return f"Whole processed recording → {conditions}"


def _review_status_text(item: KurtosisReviewItem) -> str:
    if item.review_status == KURTOSIS_REVIEW_PENDING_STALE:
        return "Changed evidence — review again"
    return "New finding"


class KurtosisReviewDialog(AppDialog):
    """Review pending channels with an optional, auditable experimental rule."""

    def __init__(
        self,
        review: KurtosisReviewScan | KurtosisReviewDecisionReconciliation,
        parent: QWidget | None = None,
        *,
        reviewer_identity: str | None = None,
    ) -> None:
        if isinstance(review, KurtosisReviewDecisionReconciliation):
            scan = review.scan
            current_receipts = review.processing_decisions_by_recording
        else:
            scan = review
            current_receipts = {}
        if scan.cancelled:
            raise KurtosisReviewDialogError("The kurtosis evidence scan was cancelled; processing remains blocked.")
        if scan.errors:
            files = ", ".join(result.path.name for result in scan.errors)
            raise KurtosisReviewDialogError(f"Kurtosis evidence is incomplete for {files}; processing remains blocked.")
        if not scan.review_items:
            raise KurtosisReviewDialogError("There are no review-required kurtosis findings.")
        super().__init__(
            "Kurtosis Electrode Review",
            parent,
            size=SurfaceSize(1260, 720, min_width=980, min_height=560),
        )
        self.setObjectName("kurtosis_review_dialog")
        self.setModal(True)
        self._items = tuple(scan.review_items)
        self._current_receipts = deepcopy(current_receipts)
        self._reviewer_identity = str(reviewer_identity or "").strip() or None
        self._decision_controls: dict[tuple[str, str], QComboBox] = {}
        self._reason_controls: dict[tuple[str, str], QLineEdit] = {}
        self._invalid_reason: QLineEdit | None = None
        self._manual_indices: dict[int, int] = {}
        self._automatic_rows = frozenset(
            row for row, item in enumerate(self._items)
            if any(
                channel.get("channel") == item.channel
                and qualifies_for_experimental_kurtosis_auto(channel)
                for channel in item.evidence.get("channels", ())
            )
        )
        self._accepted_receipts: dict[str, dict[str, dict[str, object]]] | None = None
        self._validate_unique_items()
        self._build_ui()

    def _validate_unique_items(self) -> None:
        keys = [(item.recording_id.casefold(), item.channel.casefold()) for item in self._items]
        if len(keys) != len(set(keys)):
            raise KurtosisReviewDialogError("Kurtosis review contains duplicate recording-electrode findings.")

    def _build_ui(self) -> None:
        self.banner = StatusBanner("", self, variant="warning")
        self.banner.setObjectName("kurtosis_review_banner")
        self.root_layout.addWidget(self.banner)

        options = QHBoxLayout()
        self.auto_checkbox = QCheckBox(
            f"Experimental: auto-interpolate |normalized score| > {KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD:.1f}",
            self,
        )
        self.auto_checkbox.setObjectName("kurtosis_experimental_auto")
        self.auto_checkbox.setToolTip(
            "For pending findings in this review. Uses the absolute normalized score, "
            "not raw kurtosis. Turn off to review every finding manually. "
            "Applied automatic decisions are saved with their experimental policy."
        )
        self.auto_checkbox.setChecked(True)
        options.addWidget(self.auto_checkbox)
        options.addStretch(1)
        self.show_auto_checkbox = QCheckBox("Show automatic", self)
        self.show_auto_checkbox.setObjectName("kurtosis_show_automatic")
        options.addWidget(self.show_auto_checkbox)
        self.root_layout.addLayout(options)

        explanation = QLabel(
            "Interpolation repairs the electrode across the whole processed recording. "
            "Select a row for conditions and evidence. Manual decisions need a reason.",
            self,
        )
        explanation.setObjectName("kurtosis_review_fixed_repair_explanation")
        explanation.setWordWrap(True)
        self.root_layout.addWidget(explanation)

        self.error_banner = StatusBanner("", self, variant="error")
        self.error_banner.setObjectName("kurtosis_review_error")
        self.error_banner.hide()
        self.root_layout.addWidget(self.error_banner)

        headers = ["Recording", "Electrode", "|Score|", "Raw kurtosis", "Conditions", "Decision", "Reason"]
        self.table = QTableWidget(len(self._items), len(headers), self)
        self.table.setObjectName("kurtosis_review_table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((155, 75, 80, 100, 95, 165)):
            self.table.setColumnWidth(column, width)
        self.table.horizontalHeaderItem(2).setToolTip("Absolute normalized kurtosis score; the review gate uses this value.")
        self.table.setUpdatesEnabled(False)
        for row, item in enumerate(self._items):
            recording = _recording_text(item)
            if item.participant_id.casefold() != item.recording_id.casefold():
                recording = f"{item.participant_id} / {recording}"
            values = (
                recording,
                item.channel,
                _metric_text(abs(item.signed_normalized_score) if item.signed_normalized_score is not None else None),
                _metric_text(item.raw_kurtosis),
                str(len(item.analyzed_conditions)),
            )
            for column, text in enumerate(values):
                cell = _read_only_item(text, right_aligned=column in {2, 3, 4})
                cell.setToolTip(item.occurrence_summary if column == 4 else text)
                self.table.setItem(row, column, cell)

            decision = QComboBox(self.table)
            decision.setObjectName(f"kurtosis_review_decision_{row}")
            decision.addItem("Choose…", "")
            decision.addItem("Interpolate", KURTOSIS_DECISION_APPROVE)
            decision.addItem("Keep channel", KURTOSIS_DECISION_REJECT)
            decision.addItem("Auto interpolate", "experimental_auto")
            # The automatic label is display-only, never a manual choice.
            decision.model().item(3).setEnabled(False)
            decision.setCurrentIndex(0)
            decision.currentIndexChanged.connect(self._clear_error)
            decision.activated.connect(lambda _index, row=row: self.table.setCurrentCell(row, 0))
            self.table.setCellWidget(row, 5, decision)

            reason = QLineEdit(self.table)
            reason.setObjectName(f"kurtosis_review_reason_{row}")
            reason.setPlaceholderText("Review reason")
            reason.textChanged.connect(self._clear_error)
            self.table.setCellWidget(row, 6, reason)
            key = (item.recording_id.casefold(), item.channel.casefold())
            self._decision_controls[key] = decision
            self._reason_controls[key] = reason
        self.table.setUpdatesEnabled(True)
        self.root_layout.addWidget(self.table, 1)

        self.details = QPlainTextEdit(self)
        self.details.setObjectName("kurtosis_review_selected_evidence")
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(112)
        self.details.setPlaceholderText("Select an electrode to inspect its evidence.")
        self.root_layout.addWidget(self.details)
        self.preview = KurtosisSignalPreviewWidget((), "uV", 0, self)
        self.root_layout.addWidget(self.preview)
        self.table.currentCellChanged.connect(self._show_selected_evidence)
        self.auto_checkbox.toggled.connect(self._refresh_automatic_rows)
        self.show_auto_checkbox.toggled.connect(self._refresh_automatic_rows)

        actions = ActionRow(self)
        actions.setObjectName("kurtosis_review_actions")
        self.mark_all_button = actions.add_button(
            make_action_button("Interpolate all flagged", variant="secondary", parent=actions)
        )
        self.mark_all_button.setObjectName("kurtosis_review_interpolate_all")
        self.mark_all_button.setToolTip(
            "Select interpolation for all flagged electrodes with |normalized score| > 5 "
            "and fill the reason with 'User auto mark'. Then click Apply decisions."
        )
        self.mark_all_button.clicked.connect(self._mark_all_flagged)
        self.cancel_button = actions.add_button(make_action_button("Cancel", variant="secondary", parent=actions))
        self.apply_button = actions.add_button(
            make_action_button("Apply decisions", variant="primary", parent=actions)
        )
        self.cancel_button.setObjectName("kurtosis_review_cancel")
        self.apply_button.setObjectName("kurtosis_review_apply")
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._validate_and_accept)
        self.root_layout.addWidget(actions)
        self._refresh_automatic_rows()

    def _mark_all_flagged(self) -> None:
        # Make this explicit bulk choice (including hidden >10 rows) use the
        # requested reason instead of the experimental policy's generated reason.
        self.auto_checkbox.setChecked(False)
        for item in self._items:
            score = item.signed_normalized_score
            if score is None or not math.isfinite(score) or abs(score) <= 5.0:
                continue
            key = (item.recording_id.casefold(), item.channel.casefold())
            decision = self._decision_controls[key]
            decision.setCurrentIndex(decision.findData(KURTOSIS_DECISION_APPROVE))
            self._reason_controls[key].setText("User auto mark")

    def _refresh_automatic_rows(self, *_args: object) -> None:
        self._clear_error()
        enabled = self.auto_checkbox.isChecked()
        show_auto = self.show_auto_checkbox.isChecked()
        self.show_auto_checkbox.setEnabled(enabled and bool(self._automatic_rows))
        self.table.setUpdatesEnabled(False)
        for row in self._automatic_rows:
            item = self._items[row]
            key = (item.recording_id.casefold(), item.channel.casefold())
            decision = self._decision_controls[key]
            if enabled and row not in self._manual_indices:
                self._manual_indices[row] = decision.currentIndex()
                decision.setCurrentIndex(3)
            elif not enabled and row in self._manual_indices:
                decision.setCurrentIndex(self._manual_indices.pop(row))
            decision.setEnabled(not enabled)
            self._reason_controls[key].setEnabled(not enabled)
            self.table.setRowHidden(row, enabled and not show_auto)
        self.table.setUpdatesEnabled(True)
        automatic = len(self._automatic_rows) if enabled else 0
        manual = len(self._items) - automatic
        self.banner.set_text(f"{manual} need manual review · {automatic} selected for experimental automatic interpolation")
        current = self.table.currentRow()
        if current < 0 or self.table.isRowHidden(current):
            visible = next((row for row in range(len(self._items)) if not self.table.isRowHidden(row)), None)
            if visible is not None:
                self.table.setCurrentCell(visible, 0)
            else:
                self.table.setCurrentCell(-1, -1)
                self.details.setPlainText("All pending findings qualify for automatic interpolation. Apply decisions to continue, or turn off the experimental option to review them manually.")
                self.preview.hide()
        elif current >= 0:
            self._show_selected_evidence(current)

    def _show_selected_evidence(self, row: int, *_args: object) -> None:
        if row < 0:
            self.details.clear()
            self.preview.hide()
            return
        item = self._items[row]
        automatic = self.auto_checkbox.isChecked() and row in self._automatic_rows
        status = "Experimental automatic interpolation" if automatic else _review_status_text(item)
        self.details.setPlainText(
            f"{item.participant_id} / {_recording_text(item)} / {item.channel} — {status}\n"
            f"Signed normalized score: {_metric_text(item.signed_normalized_score, signed=True)}; "
            f"review threshold |z| > {item.threshold:g}; validity: {item.validity_reason or item.validity}\n"
            f"Analyzed occurrences: {item.occurrence_summary}\n"
            f"Repair scope: {_fixed_repair_scope_text(item)}\n"
            f"Approved corroborator: {item.corroborator_summary}\n"
            f"Other channel-health evidence: {item.display_only_channel_health_summary}"
        )
        self.preview.set_signal(item.signal_preview, item.signal_unit, item.signal_source_sample_count)
        self.preview.show()

    def _clear_error(self, *_args: object) -> None:
        self.error_banner.hide()
        if self._invalid_reason is not None:
            control = self._invalid_reason
            control.setProperty("invalid", False)
            control.style().unpolish(control)
            control.style().polish(control)
            self._invalid_reason = None

    def _build_receipts(self) -> dict[str, dict[str, dict[str, object]]]:
        receipts = deepcopy(self._current_receipts)
        for row, item in enumerate(self._items):
            key = (item.recording_id.casefold(), item.channel.casefold())
            automatic = self.auto_checkbox.isChecked() and row in self._automatic_rows
            decision = KURTOSIS_DECISION_APPROVE if automatic else str(self._decision_controls[key].currentData() or "")
            reason_control = self._reason_controls[key]
            reason = reason_control.text().strip()
            if automatic:
                reason = f"Experimental automatic interpolation: |normalized score| > {KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD:.1f}."
            if not decision:
                self.table.setCurrentCell(row, 5)
                self.table.scrollToItem(self.table.item(row, 0))
                raise KurtosisReviewDialogError(
                    f"{item.participant_id} / {item.recording_id} / {item.channel}: choose Interpolate or Keep channel."
                )
            if not reason:
                self.table.setCurrentCell(row, 6)
                self.table.scrollToItem(self.table.item(row, 0))
                self._invalid_reason = reason_control
                reason_control.setProperty("invalid", True)
                reason_control.style().unpolish(reason_control)
                reason_control.style().polish(reason_control)
                raise KurtosisReviewDialogError(
                    f"{item.participant_id} / {item.recording_id} / {item.channel}: enter a review reason."
                )
            try:
                receipt = build_kurtosis_review_decision(
                    item.evidence,
                    channel=item.channel,
                    decision=decision,
                    reason=reason,
                    review_scope=item.review_scope,
                    reviewer_identity=self._reviewer_identity,
                    experimental_auto=automatic,
                )
            except KurtosisQCError as exc:
                raise KurtosisReviewDialogError(
                    f"{item.participant_id} / {item.recording_id} / {item.channel}: {exc}"
                ) from exc
            receipts.setdefault(item.recording_id, {})[item.channel] = receipt.to_payload()
        return receipts

    def _validate_and_accept(self) -> None:
        try:
            receipts = self._build_receipts()
        except KurtosisReviewDialogError as exc:
            self.error_banner.set_text(str(exc))
            self.error_banner.show()
            return
        self._accepted_receipts = receipts
        self.accept()

    def review_decisions_by_recording(self) -> dict[str, dict[str, dict[str, object]]]:
        """Return receipts only after every row was validly accepted."""

        if self.result() != QDialog.DialogCode.Accepted or self._accepted_receipts is None:
            raise KurtosisReviewDialogError("Kurtosis review was not completed; downstream processing remains blocked.")
        return deepcopy(self._accepted_receipts)

    def reject(self) -> None:
        self._accepted_receipts = None
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._accepted_receipts = None
        super().closeEvent(event)


__all__ = [
    "KurtosisReviewDialog",
    "KurtosisReviewDialogError",
    "KurtosisSignalPreviewWidget",
]

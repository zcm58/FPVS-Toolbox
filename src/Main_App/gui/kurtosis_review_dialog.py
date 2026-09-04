"""Modal QC-16 review for recording-wide kurtosis channel findings."""

from __future__ import annotations

from copy import deepcopy
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCloseEvent, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
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
from Main_App.gui.style_tokens import (
    ACCENT_COLOR,
    BORDER_COLOR,
    SURFACE_ALT_BG,
    TEXT_MUTED,
)
from Main_App.processing.kurtosis_qc import (
    KURTOSIS_DECISION_APPROVE,
    KURTOSIS_DECISION_REJECT,
    KurtosisQCError,
    build_kurtosis_review_decision,
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
        self._values = tuple(values)
        self._unit = str(unit or "uV")
        self._source_sample_count = max(0, int(source_sample_count))
        self.setObjectName("kurtosis_signal_preview")
        self.setMinimumSize(150, 52)
        self.setMaximumHeight(62)
        finite = [float(value) for value in self._values if value is not None]
        if finite:
            self.setToolTip(
                f"{len(self._values)} displayed samples from "
                f"{self._source_sample_count or len(self._values)} analyzed samples; "
                f"range {min(finite):.3g} to {max(finite):.3g} {self._unit}."
            )
        else:
            self.setToolTip("No finite signal preview was available.")

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
    """Require an explicit approve or reject receipt for every pending channel."""

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
        self._accepted_receipts: dict[str, dict[str, dict[str, object]]] | None = None
        self._validate_unique_items()
        self._build_ui()

    def _validate_unique_items(self) -> None:
        keys = [(item.recording_id.casefold(), item.channel.casefold()) for item in self._items]
        if len(keys) != len(set(keys)):
            raise KurtosisReviewDialogError("Kurtosis review contains duplicate recording-electrode findings.")

    def _build_ui(self) -> None:
        banner = StatusBanner(
            (
                f"{len(self._items)} electrode finding"
                f"{'s' if len(self._items) != 1 else ''} crossed the kurtosis "
                "review gate without an approved independent corroborator. "
                "This is a screening result and requires your judgment."
            ),
            self,
            variant="warning",
        )
        banner.setObjectName("kurtosis_review_banner")
        self.root_layout.addWidget(banner)

        scopes: list[str] = []
        seen_scopes: set[tuple[str, str]] = set()
        for item in self._items:
            scope_key = (item.recording_id.casefold(), ",".join(item.analyzed_conditions).casefold())
            if scope_key in seen_scopes:
                continue
            seen_scopes.add(scope_key)
            scopes.append(f"{item.participant_id} / {item.recording_id}: " + ", ".join(item.analyzed_conditions))
        explanation = QLabel(
            (
                "Approve authorizes one fixed repair for the electrode across the "
                "whole processed recording. Every analyzed condition named here "
                "receives that repaired channel: "
                + "; ".join(scopes)
                + ". Reject leaves the electrode unrepaired. Choose a decision and "
                "enter a reason for every row. Canceling or closing this dialog "
                "blocks continuation."
            ),
            self,
        )
        explanation.setObjectName("kurtosis_review_fixed_repair_explanation")
        explanation.setWordWrap(True)
        self.root_layout.addWidget(explanation)

        self.error_banner = StatusBanner("", self, variant="error")
        self.error_banner.setObjectName("kurtosis_review_error")
        self.error_banner.hide()
        self.root_layout.addWidget(self.error_banner)

        headers = [
            "Participant",
            "Recording / session",
            "Electrode",
            "Review status",
            "Affected analyzed conditions / occurrences",
            "Raw kurtosis",
            "Signed normalized score",
            "Threshold |z| >",
            "Approved corroborator state",
            "Other channel-health results",
            "Compact signal evidence",
            "Fixed repair scope",
            "Decision",
            "Reason",
        ]
        self.table = QTableWidget(len(self._items), len(headers), self)
        self.table.setObjectName("kurtosis_review_table")
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        for column in (4, 8, 9, 11, 13):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)

        for row, item in enumerate(self._items):
            validity_detail = item.validity_reason or item.validity
            values = (
                item.participant_id,
                _recording_text(item),
                item.channel,
                _review_status_text(item),
                item.occurrence_summary,
                _metric_text(item.raw_kurtosis),
                _metric_text(item.signed_normalized_score, signed=True),
                f"{item.threshold:.3f}",
                item.corroborator_summary,
                item.display_only_channel_health_summary,
            )
            for column, text in enumerate(values):
                table_item = _read_only_item(
                    text,
                    right_aligned=column in {5, 6, 7},
                )
                if column in {5, 6} and validity_detail:
                    table_item.setToolTip(validity_detail)
                self.table.setItem(row, column, table_item)

            preview = KurtosisSignalPreviewWidget(
                item.signal_preview,
                item.signal_unit,
                item.signal_source_sample_count,
                self.table,
            )
            preview.setObjectName(f"kurtosis_signal_preview_{row}")
            self.table.setCellWidget(row, 10, preview)
            self.table.setItem(row, 11, _read_only_item(_fixed_repair_scope_text(item)))

            decision = QComboBox(self.table)
            decision.setObjectName(f"kurtosis_review_decision_{row}")
            decision.addItem("Choose Approve or Reject…", "")
            decision.addItem(
                "Approve whole-recording repair",
                KURTOSIS_DECISION_APPROVE,
            )
            decision.addItem("Reject repair", KURTOSIS_DECISION_REJECT)
            decision.setCurrentIndex(0)
            decision.currentIndexChanged.connect(self._clear_error)
            self.table.setCellWidget(row, 12, decision)

            reason = QLineEdit(self.table)
            reason.setObjectName(f"kurtosis_review_reason_{row}")
            reason.setPlaceholderText("Required review reason")
            reason.textChanged.connect(self._clear_error)
            self.table.setCellWidget(row, 13, reason)

            key = (item.recording_id.casefold(), item.channel.casefold())
            self._decision_controls[key] = decision
            self._reason_controls[key] = reason
            self.table.setRowHeight(row, 70)

        self.root_layout.addWidget(self.table, 1)

        actions = ActionRow(self)
        actions.setObjectName("kurtosis_review_actions")
        self.cancel_button = actions.add_button(make_action_button("Cancel", variant="secondary", parent=actions))
        self.apply_button = actions.add_button(
            make_action_button("Apply review decisions", variant="primary", parent=actions)
        )
        self.cancel_button.setObjectName("kurtosis_review_cancel")
        self.apply_button.setObjectName("kurtosis_review_apply")
        self.cancel_button.clicked.connect(self.reject)
        self.apply_button.clicked.connect(self._validate_and_accept)
        self.root_layout.addWidget(actions)

    def _clear_error(self, *_args: object) -> None:
        self.error_banner.hide()
        for control in self._reason_controls.values():
            if control.property("invalid"):
                control.setProperty("invalid", False)
                control.style().unpolish(control)
                control.style().polish(control)

    def _build_receipts(self) -> dict[str, dict[str, dict[str, object]]]:
        receipts = deepcopy(self._current_receipts)
        for item in self._items:
            key = (item.recording_id.casefold(), item.channel.casefold())
            decision = str(self._decision_controls[key].currentData() or "")
            reason_control = self._reason_controls[key]
            reason = reason_control.text().strip()
            if not decision:
                raise KurtosisReviewDialogError(
                    f"{item.participant_id} / {item.recording_id} / {item.channel}: choose Approve or Reject."
                )
            if not reason:
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

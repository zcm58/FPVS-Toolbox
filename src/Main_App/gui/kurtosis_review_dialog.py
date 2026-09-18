"""Modal QC-16 review for recording-wide kurtosis channel findings."""

from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path
from collections.abc import Mapping
from dataclasses import replace

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
    qualifies_for_experimental_kurtosis_auto_all,
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
        auto_interpolate_all: bool = False,
        project_root: Path | str | None = None,
        signal_params: Mapping[str, object] | None = None,
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
            size=SurfaceSize(1240, 820, min_width=1100, min_height=650),
        )
        self.setObjectName("kurtosis_review_dialog")
        self.setModal(True)
        self._items = tuple(scan.review_items)
        self._current_receipts = deepcopy(current_receipts)
        self._reviewer_identity = str(reviewer_identity or "").strip() or None
        self._auto_interpolate_all = bool(auto_interpolate_all)
        self._project_root = Path(project_root) if project_root is not None else None
        self._signal_params = dict(signal_params or {})
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
        self._all_flag_rows = frozenset(
            row for row, item in enumerate(self._items)
            if any(
                channel.get("channel") == item.channel
                and qualifies_for_experimental_kurtosis_auto_all(channel)
                for channel in item.evidence.get("channels", ())
            )
        )
        self._accepted_receipts: dict[str, dict[str, dict[str, object]]] | None = None
        self._validate_unique_items()
        self._bulk_undo: tuple[tuple[int, int, str], ...] = ()
        self._build_ui()

    def _validate_unique_items(self) -> None:
        keys = [(item.recording_id.casefold(), item.channel.casefold()) for item in self._items]
        if len(keys) != len(set(keys)):
            raise KurtosisReviewDialogError("Kurtosis review contains duplicate recording-electrode findings.")

    def _build_ui(self) -> None:
        self.banner = StatusBanner("", self, variant="warning")
        self.banner.setObjectName("kurtosis_review_banner")
        self.root_layout.addWidget(self.banner)

        self.auto_all_checkbox = QCheckBox(
            "Auto interpolate all kurtosis flags (experimental)", self,
        )
        self.auto_all_checkbox.setObjectName("kurtosis_auto_interpolate_all")
        self.auto_all_checkbox.setChecked(self._auto_interpolate_all)
        self.auto_all_checkbox.setToolTip(
            "Automatically interpolate valid flags above the configured absolute "
            "normalized-score threshold. Saved for this project when you apply "
            "decisions. Turn off for manual review; invalid statistics still need review."
        )
        self.root_layout.addWidget(self.auto_all_checkbox)
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
            "Select a row for conditions and evidence. Reasons are optional.",
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
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
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
            decision.currentIndexChanged.connect(self._refresh_action_scope)
            decision.activated.connect(self._discard_bulk_undo)
            decision.activated.connect(lambda _index, row=row: self.table.setCurrentCell(row, 0))
            self.table.setCellWidget(row, 5, decision)

            reason = QLineEdit(self.table)
            reason.setObjectName(f"kurtosis_review_reason_{row}")
            reason.setPlaceholderText("Reason (optional)")
            reason.textChanged.connect(self._clear_error)
            reason.textEdited.connect(self._discard_bulk_undo)
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
        self.auto_all_checkbox.toggled.connect(self._refresh_automatic_rows)
        self.show_auto_checkbox.toggled.connect(self._refresh_automatic_rows)
        self.auto_checkbox.clicked.connect(self._discard_bulk_undo)
        self.auto_all_checkbox.clicked.connect(self._discard_bulk_undo)

        review_actions = ActionRow(self, alignment=Qt.AlignmentFlag.AlignLeft)
        self.inspect_button = review_actions.add_button(
            make_action_button("Inspect signal", variant="secondary", parent=review_actions)
        )
        self.inspect_button.setObjectName("kurtosis_inspect_signal")
        self.inspect_button.clicked.connect(self._inspect_signal)
        self.support_button = review_actions.add_button(
            make_action_button("Repair support", variant="secondary", parent=review_actions)
        )
        self.support_button.setObjectName("kurtosis_repair_support")
        self.support_button.clicked.connect(self._inspect_repair_support)
        self.next_button = review_actions.add_button(
            make_action_button("Next undecided", variant="secondary", parent=review_actions)
        )
        self.next_button.setObjectName("kurtosis_next_undecided")
        self.next_button.clicked.connect(self._next_undecided)
        self.selected_decision = QComboBox(review_actions)
        self.selected_decision.setAccessibleName("Decision for selected undecided electrodes")
        self.selected_decision.addItem("Interpolate", KURTOSIS_DECISION_APPROVE)
        self.selected_decision.addItem("Keep channel", KURTOSIS_DECISION_REJECT)
        self.selected_decision.currentIndexChanged.connect(self._refresh_action_scope)
        review_actions.row_layout.addWidget(self.selected_decision)
        self.selected_button = review_actions.add_button(
            make_action_button("Apply to selected", variant="secondary", parent=review_actions)
        )
        self.selected_button.setObjectName("kurtosis_apply_selected_pending")
        self.selected_button.clicked.connect(self._apply_selected_pending)
        self.undo_button = review_actions.add_button(
            make_action_button("Undo bulk edit", variant="secondary", parent=review_actions)
        )
        self.undo_button.setObjectName("kurtosis_undo_bulk")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo_bulk_edit)
        self.root_layout.addWidget(review_actions)
        self.scope_label = QLabel(self)
        self.scope_label.setObjectName("kurtosis_action_scope")
        self.scope_label.setWordWrap(True)
        self.root_layout.addWidget(self.scope_label)
        self.table.itemSelectionChanged.connect(self._refresh_action_scope)

        actions = ActionRow(self)
        actions.setObjectName("kurtosis_review_actions")
        self.mark_all_button = actions.add_button(
            make_action_button("Interpolate all undecided", variant="secondary", parent=actions)
        )
        self.mark_all_button.setObjectName("kurtosis_review_interpolate_all")
        self.mark_all_button.setToolTip(
            "Select interpolation only for visible undecided manual flags above the "
            "configured threshold. Existing decisions, reasons and automatic policies "
            "are preserved. Undo is available before Apply decisions."
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
        self._refresh_action_scope()

    def _mark_all_flagged(self) -> None:
        self._apply_bulk_decision(self._pending_manual_rows(), KURTOSIS_DECISION_APPROVE)

    def _pending_manual_rows(self) -> tuple[int, ...]:
        automatic = self._selected_automatic_rows()
        return tuple(
            row for row, item in enumerate(self._items)
            if row not in automatic and not self.table.isRowHidden(row)
            and not self._decision_controls[
                (item.recording_id.casefold(), item.channel.casefold())
            ].currentData()
            and item.signed_normalized_score is not None
            and math.isfinite(item.signed_normalized_score)
            and abs(item.signed_normalized_score) > item.threshold
        )

    def _selected_pending_rows(self) -> tuple[int, ...]:
        selected = {index.row() for index in self.table.selectionModel().selectedRows()}
        return tuple(row for row in self._pending_manual_rows() if row in selected)

    def _apply_selected_pending(self) -> None:
        self._apply_bulk_decision(
            self._selected_pending_rows(), str(self.selected_decision.currentData())
        )

    def _apply_bulk_decision(self, rows: tuple[int, ...], decision_value: str) -> None:
        if not rows:
            return
        snapshots = []
        for row in rows:
            item = self._items[row]
            key = (item.recording_id.casefold(), item.channel.casefold())
            control = self._decision_controls[key]
            snapshots.append((row, control.currentIndex(), self._reason_controls[key].text()))
            control.setCurrentIndex(control.findData(decision_value))
        self._bulk_undo = tuple(snapshots)
        self.undo_button.setEnabled(True)
        self._refresh_action_scope()

    def _discard_bulk_undo(self, *_args: object) -> None:
        self._bulk_undo = ()
        self.undo_button.setEnabled(False)

    def _undo_bulk_edit(self) -> None:
        snapshots = self._bulk_undo
        self._bulk_undo = ()
        for row, index, reason in snapshots:
            item = self._items[row]
            key = (item.recording_id.casefold(), item.channel.casefold())
            self._decision_controls[key].setCurrentIndex(index)
            self._reason_controls[key].setText(reason)
        self.undo_button.setEnabled(False)
        self._refresh_action_scope()

    def _next_undecided(self) -> None:
        automatic = self._selected_automatic_rows()
        current = self.table.currentRow()
        rows = list(range(current + 1, len(self._items))) + list(range(current + 1))
        for row in rows:
            item = self._items[row]
            key = (item.recording_id.casefold(), item.channel.casefold())
            if row not in automatic and not self._decision_controls[key].currentData():
                self.table.setCurrentCell(row, 0)
                self.table.scrollToItem(self.table.item(row, 0))
                return

    def _refresh_action_scope(self, *_args: object) -> None:
        if not hasattr(self, "scope_label"):
            return
        rows = self._selected_pending_rows()
        recordings = {self._items[row].recording_id for row in rows}
        all_rows = self._pending_manual_rows()
        all_recordings = {self._items[row].recording_id for row in all_rows}
        self.selected_button.setEnabled(bool(rows))
        self.mark_all_button.setEnabled(bool(all_rows))
        self.scope_label.setText(
            f"Selected action: {len(rows)} undecided electrode(s) across "
            f"{len(recordings)} recording(s). All undecided: {len(all_rows)} electrode(s) "
            f"across {len(all_recordings)} recording(s). 0 hidden rows affected. "
            "Interpolation applies across every analyzed condition in each recording."
        )
        current = self.table.currentRow()
        self.inspect_button.setEnabled(current >= 0 and self._project_root is not None)
        self.support_button.setEnabled(current >= 0)

    def _inspect_repair_support(self) -> None:
        from Main_App.gui.qc_repair_support import RepairSupportDialog

        row = self.table.currentRow()
        if row < 0:
            return
        item = self._items[row]
        channels, repair_channels, unavailable_donors = self._repair_context(item)
        RepairSupportDialog(
            channels=channels, repair_channels=repair_channels, confirmed=False, parent=self,
            unusable_channels=unavailable_donors,
        ).exec()

    def _repair_context(self, item: KurtosisReviewItem) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Describe current/proposed repairs while withholding undecided donors."""
        channels = tuple(item.evidence.get("geometry_identity", {}).get("retained_scalp_channels", ()))
        repair_channels = set(getattr(item, "signal_view", {}).get("upstream_bad_channels", ()))
        current_channels = {candidate.channel for candidate in self._items
                            if candidate.recording_id == item.recording_id}
        for channel, receipt in self._current_receipts.get(item.recording_id, {}).items():
            if channel not in current_channels and receipt.get("decision") == KURTOSIS_DECISION_APPROVE:
                repair_channels.add(channel)
        automatic = self._selected_automatic_rows()
        unavailable_donors = set(repair_channels)
        for index, candidate in enumerate(self._items):
            if candidate.recording_id != item.recording_id:
                continue
            key = (candidate.recording_id.casefold(), candidate.channel.casefold())
            if index in automatic or self._decision_controls[key].currentData() == KURTOSIS_DECISION_APPROVE:
                repair_channels.add(candidate.channel)
            if not self._decision_controls[key].currentData():
                unavailable_donors.add(candidate.channel)
        # The current electrode is shown as a proposed repair while undecided.
        key = (item.recording_id.casefold(), item.channel.casefold())
        if not self._decision_controls[key].currentData():
            repair_channels.add(item.channel)
        unavailable_donors.update(repair_channels)
        return channels, tuple(sorted(repair_channels)), tuple(sorted(unavailable_donors))

    def _inspect_signal(self) -> None:
        # Reader/worker imports stay lazy; loading and diagnostics belong to the viewer worker.
        from Main_App.gui.qc_signal_viewer import QcSignalViewer
        from Main_App.processing.qc_signal_view import request_from_kurtosis_item

        row = self.table.currentRow()
        if row < 0 or self._project_root is None:
            return
        request = request_from_kurtosis_item(
            self._items[row], self._project_root, self._signal_params
        )
        _channels, _repairs, unavailable_donors = self._repair_context(self._items[row])
        request = replace(request, unusable_channels=unavailable_donors)
        QcSignalViewer(request, self).exec()

    def _selected_automatic_rows(self) -> frozenset[int]:
        if self.auto_all_checkbox.isChecked():
            return self._all_flag_rows
        return self._automatic_rows if self.auto_checkbox.isChecked() else frozenset()

    def _refresh_automatic_rows(self, *_args: object) -> None:
        self._clear_error()
        automatic_rows = self._selected_automatic_rows()
        self.auto_checkbox.setEnabled(not self.auto_all_checkbox.isChecked())
        show_auto = self.show_auto_checkbox.isChecked()
        self.show_auto_checkbox.setEnabled(bool(automatic_rows))
        self.table.setUpdatesEnabled(False)
        for row in self._all_flag_rows | self._automatic_rows:
            enabled = row in automatic_rows
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
        automatic = len(automatic_rows)
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
        self._refresh_action_scope()

    def _show_selected_evidence(self, row: int, *_args: object) -> None:
        if row < 0:
            self.details.clear()
            self.preview.hide()
            self._refresh_action_scope()
            return
        item = self._items[row]
        automatic = row in self._selected_automatic_rows()
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
        self._refresh_action_scope()

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
            automatic_all = self.auto_all_checkbox.isChecked() and row in self._all_flag_rows
            automatic = row in self._selected_automatic_rows()
            decision = KURTOSIS_DECISION_APPROVE if automatic else str(self._decision_controls[key].currentData() or "")
            reason_control = self._reason_controls[key]
            reason = reason_control.text().strip()
            if automatic_all:
                reason = "Experimental automatic interpolation of all valid kurtosis flags."
            elif automatic:
                reason = f"Experimental automatic interpolation: |normalized score| > {KURTOSIS_EXPERIMENTAL_AUTO_Z_THRESHOLD:.1f}."
            if not decision:
                self.table.setCurrentCell(row, 5)
                self.table.scrollToItem(self.table.item(row, 0))
                raise KurtosisReviewDialogError(
                    f"{item.participant_id} / {item.recording_id} / {item.channel}: choose Interpolate or Keep channel."
                )
            try:
                receipt = build_kurtosis_review_decision(
                    item.evidence,
                    channel=item.channel,
                    decision=decision,
                    reason=reason,
                    review_scope=item.review_scope,
                    reviewer_identity=self._reviewer_identity,
                    experimental_auto=automatic and not automatic_all,
                    experimental_auto_all=automatic_all,
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

    def auto_interpolate_all(self) -> bool:
        """Read the project preference after the user applies this review."""
        if self.result() != QDialog.DialogCode.Accepted:
            raise KurtosisReviewDialogError("Kurtosis review was not completed.")
        return self.auto_all_checkbox.isChecked()

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

"""Inspectable QC signal with exact recording times and bounded background I/O."""

from __future__ import annotations

from dataclasses import replace
import math

from PySide6.QtCore import QPointF, QRectF, QThread, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPlainTextEdit, QTabWidget,
    QVBoxLayout, QWidget,
)

from Main_App.gui.components import ActionRow, AppDialog, SurfaceSize, make_action_button
from Main_App.gui.style_tokens import ACCENT_COLOR, BORDER_COLOR, TEXT_MUTED
from Main_App.processing.qc_signal_view import QcSignalViewRequest, QcSignalViewResult
from Main_App.workers.qc_signal_view_worker import QcSignalViewWorker


class _EnvelopePlot(QWidget):
    time_selected = Signal(float)

    def __init__(self, parent=None, *, overview=False):
        super().__init__(parent)
        self._times = ()
        self._traces = ()
        self._overview = overview
        self.setMinimumHeight(90 if overview else 260)
        if overview:
            self.setMaximumHeight(100)
            self.setToolTip("Click to inspect this time. Each vertical line preserves its bin's full amplitude range.")

    def set_data(self, times, traces):
        self._times, self._traces = times, traces
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if self._overview and self._times:
            fraction = min(1.0, max(0.0, (event.position().x() - 105) / max(1, self.width() - 125)))
            self.time_selected.emit(self._times[0] + fraction * (self._times[-1] - self._times[0]))
        super().mousePressEvent(event)

    def paintEvent(self, _event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._times or not self._traces:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Load an interval to inspect its signal.")
            return
        finite = [abs(value) for trace in self._traces for values in (trace.minimum_uv, trace.maximum_uv)
                  for value in values if value is not None and math.isfinite(value)]
        scale = max(max(finite, default=1.0), 1e-9)
        row_height = max(45.0, (self.height() - 23) / len(self._traces))
        left, width = 105.0, max(1.0, self.width() - 125.0)
        time_span = max(1e-12, self._times[-1] - self._times[0])
        for row, trace in enumerate(self._traces):
            top = row * row_height
            mid = top + row_height / 2
            height = max(1.0, row_height / 2 - 13)
            painter.setPen(QColor(TEXT_MUTED))
            painter.drawText(QRectF(0, top, 100, row_height), Qt.TextFlag.TextWordWrap,
                             f"{trace.name}\n±{scale:.3g} µV")
            painter.setPen(QPen(QColor(BORDER_COLOR), 1.0))
            painter.drawLine(QPointF(left, mid), QPointF(left + width, mid))
            painter.setPen(QPen(QColor(ACCENT_COLOR), 1.1))
            previous = None
            for time, low, high in zip(self._times, trace.minimum_uv, trace.maximum_uv, strict=True):
                if low is None or high is None:
                    previous = None
                    continue
                x = left + (time - self._times[0]) / time_span * width
                lower, upper = QPointF(x, mid - low / scale * height), QPointF(x, mid - high / scale * height)
                painter.drawLine(lower, upper)
                center = QPointF(x, (lower.y() + upper.y()) / 2)
                if previous is not None:
                    painter.drawLine(previous, center)
                previous = center
        painter.setPen(QColor(TEXT_MUTED))
        painter.drawText(QRectF(left, self.height() - 21, width, 20), Qt.AlignmentFlag.AlignLeft,
                         f"{self._times[0]:.3f} s")
        painter.drawText(QRectF(left, self.height() - 21, width, 20), Qt.AlignmentFlag.AlignRight,
                         f"{self._times[-1]:.3f} s from recording start")


class QcSignalViewer(AppDialog):
    """Review-only viewer; closing during a read cancels without blocking Qt."""

    def __init__(self, request: QcSignalViewRequest, parent=None):
        super().__init__("Inspect QC Signal", parent, size=SurfaceSize(1140, 820, min_width=980, min_height=680))
        self.setObjectName("qc_signal_viewer")
        self._request = request
        self._thread = None
        self._worker = None
        self._close_pending = False
        self._result = None
        self._next_spatial = False
        self._build_ui()
        QTimer.singleShot(0, self._load)

    def _build_ui(self):
        self.context = QLabel(self._request.path.name, self)
        self.context.setWordWrap(True)
        self.root_layout.addWidget(self.context)
        selectors = QHBoxLayout()
        self.occurrence = QComboBox(self)
        self.occurrence.setObjectName("qc_signal_occurrence")
        self.occurrence.setMinimumWidth(230)
        self.channel = QComboBox(self)
        self.channel.setObjectName("qc_signal_channel")
        self.mode = QComboBox(self)
        self.mode.setObjectName("qc_signal_mode")
        for label, value in (
            ("Raw acquisition", "raw"), ("Intended initial reference", "initial_reference"),
            ("Reference comparison", "reference_comparison"), ("Prepared before interpolation", "prepared"),
        ):
            self.mode.addItem(label, value)
        self.mode.model().item(3).setEnabled(bool(self._request.prepared))
        self.mode.setCurrentIndex(self.mode.findData(self._request.mode))
        for label, widget in (("Occurrence", self.occurrence), ("Electrode", self.channel), ("Signal", self.mode)):
            selectors.addWidget(QLabel(label, self))
            selectors.addWidget(widget, 1)
        self.root_layout.addLayout(selectors)
        self.overview = _EnvelopePlot(self, overview=True)
        self.overview.setObjectName("qc_signal_overview")
        self.root_layout.addWidget(self.overview)
        navigation = QHBoxLayout()
        self.previous = make_action_button("Earlier", variant="secondary", parent=self)
        self.next = make_action_button("Later", variant="secondary", parent=self)
        self.start = QDoubleSpinBox(self)
        self.start.setDecimals(3)
        self.start.setRange(0, 1e9)
        self.start.setSuffix(" s")
        self.duration = QComboBox(self)
        for seconds in (1, 2, 5, 10, 30):
            self.duration.addItem(f"{seconds} s", float(seconds))
        self.duration.setCurrentIndex(2)
        self.refresh = make_action_button("Show interval", variant="secondary", parent=self)
        for widget in (self.previous, self.next, QLabel("Start", self), self.start,
                       QLabel("Window", self), self.duration, self.refresh):
            navigation.addWidget(widget)
        self.root_layout.addLayout(navigation)
        self.tabs = QTabWidget(self)
        trace_page = QWidget(self.tabs)
        trace_layout = QVBoxLayout(trace_page)
        self.plot = _EnvelopePlot(trace_page)
        self.plot.setObjectName("qc_signal_detail")
        trace_layout.addWidget(self.plot, 1)
        note = QLabel("All traces share the displayed µV scale. The overview preserves extrema; gaps between occurrences are never joined. "
                      "This inspection does not change data or approve a repair.", trace_page)
        note.setWordWrap(True)
        trace_layout.addWidget(note)
        self.tabs.addTab(trace_page, "Signal")
        diagnostics_page = QWidget(self.tabs)
        diagnostics_layout = QVBoxLayout(diagnostics_page)
        events_row = QHBoxLayout()
        self.event_selector = QComboBox(diagnostics_page)
        self.event_selector.setObjectName("qc_signal_diagnostic_event")
        self.event_jump = make_action_button("Go to event", variant="secondary", parent=diagnostics_page)
        self.event_jump.setObjectName("qc_signal_go_to_event")
        self.event_jump.clicked.connect(self._go_to_event)
        events_row.addWidget(self.event_selector, 1)
        events_row.addWidget(self.event_jump)
        diagnostics_layout.addLayout(events_row)
        self.spatial_button = make_action_button("Estimate spatial support", variant="secondary", parent=diagnostics_page)
        self.spatial_button.setObjectName("qc_signal_spatial_support")
        self.spatial_button.setToolTip("Optional MNE comparison: withhold known usable electrodes in this window. Descriptive errors do not approve a repair.")
        self.spatial_button.clicked.connect(self._estimate_spatial)
        diagnostics_layout.addWidget(self.spatial_button)
        self.diagnostics = QPlainTextEdit(diagnostics_page)
        self.diagnostics.setReadOnly(True)
        diagnostics_layout.addWidget(self.diagnostics, 1)
        self.tabs.addTab(diagnostics_page, "Review evidence")
        self.root_layout.addWidget(self.tabs, 1)
        self.status = QLabel("Loading signal…", self)
        self.status.setObjectName("qc_signal_status")
        self.status.setWordWrap(True)
        self.root_layout.addWidget(self.status)
        actions = ActionRow(self)
        self.close_button = actions.add_button(make_action_button("Close inspection", variant="secondary", parent=actions))
        self.close_button.clicked.connect(self.reject)
        self.root_layout.addWidget(actions)
        self.refresh.clicked.connect(self._load)
        self.previous.clicked.connect(lambda: self._move(-1))
        self.next.clicked.connect(lambda: self._move(1))
        self.overview.time_selected.connect(self._select_time)
        self.occurrence.currentIndexChanged.connect(self._change_occurrence)
        self.channel.currentIndexChanged.connect(self._change_selection)
        self.mode.currentIndexChanged.connect(self._change_selection)

    def _busy(self, busy):
        for widget in (self.occurrence, self.channel, self.mode, self.previous, self.next,
                       self.start, self.duration, self.refresh, self.overview, self.event_jump, self.spatial_button):
            widget.setEnabled(not busy)

    @Slot()
    def _change_selection(self, *_args):
        self._load()

    @Slot()
    def _change_occurrence(self, *_args):
        index = self.occurrence.currentIndex()
        if self._result and 0 <= index < len(self._result.spans):
            self.start.setValue(self._result.spans[index][0])
        self._load()

    def _move(self, direction):
        self.start.setValue(self.start.value() + direction * float(self.duration.currentData()))
        self._load()

    @Slot(float)
    def _select_time(self, seconds):
        self.start.setValue(seconds)
        self._load()

    @Slot()
    def _estimate_spatial(self):
        self._next_spatial = True
        self._load()

    @Slot()
    def _load(self):
        if self._thread is not None or self._close_pending:
            return
        request = replace(
            self._request, channel=self.channel.currentText() or self._request.channel,
            mode=str(self.mode.currentData()), occurrence_index=max(0, self.occurrence.currentIndex()),
            start_seconds=self.start.value() if self._result is not None else self._request.start_seconds,
            duration_seconds=float(self.duration.currentData()),
            spatial_holdout=self._next_spatial,
        )
        self._next_spatial = False
        thread = QThread(self)
        worker = QcSignalViewWorker(request)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        thread.started.connect(worker.run)
        worker.result.connect(self._loaded)
        worker.failed.connect(self._failed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._busy(True)
        self.plot.set_data((), ())
        self.overview.set_data((), ())
        self.diagnostics.clear()
        self.event_selector.clear()
        self.context.setText(f"{self._request.path.name} · loading {self.mode.currentText().lower()}")
        self.status.setText("Loading the selected interval…")
        try:
            thread.start()
        except (RuntimeError, OSError) as exc:
            self._thread = self._worker = None
            worker.deleteLater()
            thread.deleteLater()
            self._busy(False)
            self._failed(str(exc))

    @Slot(object)
    def _loaded(self, result: QcSignalViewResult):
        if self._close_pending:
            return
        self._result = result
        if result.verified_checkpoint:
            self._request = replace(self._request, verified_checkpoint=result.verified_checkpoint)
        self._request = replace(self._request, overview_cache=result.overview_cache)
        for combo, entries, selected in (
            (self.occurrence, result.span_labels, result.occurrence_index),
            (self.channel, result.available_channels, result.available_channels.index(result.channel)),
        ):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(list(entries))
            combo.setCurrentIndex(selected)
            combo.blockSignals(False)
        self.start.setValue(result.start_seconds)
        self.context.setText(f"{self._request.path.name} · {result.mode_label}")
        self.overview.set_data(result.overview_times, (result.overview,))
        self.plot.set_data(result.detail_times, result.traces)
        self.status.setText(f"Showing {result.start_seconds:.3f}–{result.stop_seconds:.3f} s from recording start. "
                            "Click the overview or use Earlier / Later to inspect another interval.")
        from Main_App.processing.qc_signal_view import format_signal_diagnostics
        self.diagnostics.setPlainText(format_signal_diagnostics(result.diagnostics))
        if result.spatial_support:
            support = result.spatial_support
            lines = ["\nSpatial comparison — descriptive, no pass/fail threshold.",
                     f"{support.get('window_start_seconds', 0):.3f}–{support.get('window_stop_seconds', 0):.3f} s · {support.get('signal_stage', '')}",
                     str(support.get("sampling", "")), f"Status: {str(support.get('status', '')).replace('_', ' ')}"]
            for row in support.get("channels", ()):
                if row.get("rmse_uv") is not None:
                    correlation = row.get("signed_correlation")
                    lines.append(f"{row['channel']}: {row.get('donor_count', 0)} donors; RMSE {row['rmse_uv']:.3g} µV; "
                                 f"signed correlation {correlation:.3f}" if correlation is not None else
                                 f"{row['channel']}: correlation unavailable for degenerate signal.")
                else:
                    lines.append(f"{row.get('channel', '')}: {row.get('reason', row.get('status', 'Unavailable'))}")
            lines.extend(str(value) for value in support.get("limitations", ()))
            self.diagnostics.appendPlainText("\n".join(lines))
        self.event_selector.clear()
        for event in result.diagnostics.get("localized_events", ()):
            self.event_selector.addItem(
                f"{event.get('channel', '')} · {str(event.get('kind', '')).replace('_', ' ')} · "
                f"{float(event.get('start_s', 0)):.3f}–{float(event.get('stop_s', 0)):.3f} s", dict(event),
            )
        self.event_selector.setEnabled(self.event_selector.count() > 0)

    @Slot()
    def _go_to_event(self):
        event = self.event_selector.currentData()
        if not event or self._result is None:
            return
        seconds = float(event["start_s"])
        spans = self._request.source_spans or self._result.spans
        occurrence = next((i for i, (start, stop) in enumerate(spans) if start <= seconds < stop), None)
        if occurrence is None:
            self.status.setText("This event lies outside the intervals available in this inspection.")
            return
        channel_index = self.channel.findText(str(event.get("channel", "")))
        reference_event = str(event.get("channel", "")).casefold() in {ref.casefold() for ref in self._result.reference_pair}
        if channel_index < 0 and not reference_event:
            self.status.setText("This event's channel is outside the retained channel selection.")
            return
        for combo in (self.mode, self.occurrence, self.channel):
            combo.blockSignals(True)
        self.mode.setCurrentIndex(self.mode.findData("reference_comparison" if reference_event else "raw"))
        self.occurrence.setCurrentIndex(occurrence)
        if channel_index >= 0:
            self.channel.setCurrentIndex(channel_index)
        for combo in (self.mode, self.occurrence, self.channel):
            combo.blockSignals(False)
        self.start.setValue(max(spans[occurrence][0], seconds - 0.5))
        self.tabs.setCurrentIndex(0)
        self._load()

    @Slot(str)
    def _failed(self, message):
        self.plot.set_data((), ())
        self.overview.set_data((), ())
        self.diagnostics.clear()
        self.event_selector.clear()
        self.context.setText(f"{self._request.path.name} · requested view unavailable")
        self.status.setText(f"Signal inspection unavailable: {message}")

    @Slot()
    def _thread_finished(self):
        self._thread = self._worker = None
        self._busy(False)
        self.event_jump.setEnabled(self.event_selector.count() > 0)
        if self._close_pending:
            super().reject()

    def reject(self):
        if self._worker is not None:
            self._close_pending = True
            self.status.setText("Closing inspection after the current read stops…")
            self._worker.cancel()
            return
        super().reject()

    def closeEvent(self, event):  # noqa: N802
        if self._worker is not None:
            self.reject()
            event.ignore()
            return
        super().closeEvent(event)


__all__ = ["QcSignalViewer"]

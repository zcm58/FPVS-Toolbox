"""Keep the processing shell visible while accepted QC decisions are saved."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Slot
from PySide6.QtWidgets import QMessageBox

from Main_App.gui import shell_status
from Main_App.workers.frequency_domain_qc_decision_worker import FrequencyDomainQcDecisionWorker


logger = logging.getLogger(__name__)


class _DecisionSaveBridge(QObject):
    """Receive the receipt on the GUI thread and resume after the save thread exits."""

    def __init__(
        self, host: Any, project: Any, thread: QThread, on_finished: Callable[[], None],
        *, provisional_cache: Any | None = None,
    ) -> None:
        super().__init__(host)
        self.host = host
        self.project = project
        self.save_thread = thread
        self.on_finished = on_finished
        self.provisional_cache = provisional_cache
        self.result: dict[str, object] | None = None
        button = getattr(host, "btn_start", None)
        self.button_state = (
            (button, button.isEnabled(), button.text(), button.toolTip())
            if button is not None else None
        )

    @Slot(dict)
    def receive_result(self, result: dict[str, object]) -> None:
        self.result = result

    @Slot()
    def complete(self) -> None:
        from Main_App.gui.processing_workflows import (
            _set_resume_post_processing_pending,
            _start_post_processing_pipeline_after_processing,
        )

        host = self.host
        if getattr(host, "_frequency_domain_qc_save_thread", None) is not self.save_thread:
            return
        host._frequency_domain_qc_save_thread = None
        host._frequency_domain_qc_save_worker = None
        host._frequency_domain_qc_save_bridge = None
        if self.button_state is not None:
            button, enabled, text, tooltip = self.button_state
            button.setText(text)
            button.setToolTip(tooltip)
            button.setEnabled(enabled)
        self.deleteLater()
        result = self.result or {
            "success": False,
            "error": "The QC decision save ended without a completion receipt.",
        }
        if result.get("success"):
            manifest = getattr(self.project, "manifest", None)
            tools = result.get("tools")
            if isinstance(manifest, dict) and isinstance(tools, dict):
                manifest["tools"] = tools
            host.log(
                "Frequency-domain QC review saved; resuming final harmonic selection.",
                level=logging.INFO,
            )
            if _start_post_processing_pipeline_after_processing(
                host, on_finished=self.on_finished, completed_phase_floor=1,
                provisional_cache=self.provisional_cache,
            ):
                return
            if self.provisional_cache is not None:
                self.provisional_cache.clear()
            self.on_finished()
            return

        if self.provisional_cache is not None:
            self.provisional_cache.clear()
        reason = str(result.get("error") or "The QC decisions could not be saved.")
        if result.get("stale_error"):
            reason += f"\nDownstream status could not be updated: {result['stale_error']}"
        host._post_processing_failure_reason = reason
        host.log(reason, level=logging.ERROR)
        QMessageBox.critical(host, "Frequency-Domain QC Error", reason)
        self.on_finished()
        _set_resume_post_processing_pending(host, True)


def save_frequency_domain_qc_review(
    host: Any,
    project: Any,
    report: Mapping[str, object],
    *,
    review_decisions: Sequence[Mapping[str, object]],
    manual_participant_reasons: Mapping[str, str],
    manual_recording_reasons: Mapping[str, str],
    on_finished: Callable[[], None],
    provisional_cache: Any | None = None,
) -> None:
    """Hand off only plain review data; never block the dialog-close callback on I/O."""
    if getattr(host, "_frequency_domain_qc_save_thread", None) is not None:
        return
    thread = QThread(host)
    worker = FrequencyDomainQcDecisionWorker(
        project.project_root,
        report,
        review_decisions=review_decisions,
        manual_participant_reasons=manual_participant_reasons,
        manual_recording_reasons=manual_recording_reasons,
    )
    worker.moveToThread(thread)
    bridge = _DecisionSaveBridge(
        host, project, thread, on_finished, provisional_cache=provisional_cache,
    )
    host._frequency_domain_qc_save_thread = thread
    host._frequency_domain_qc_save_worker = worker
    host._frequency_domain_qc_save_bridge = bridge
    thread.started.connect(worker.run)
    worker.finished.connect(bridge.receive_result)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(bridge.complete)
    thread.finished.connect(thread.deleteLater)

    shell_status.prepare_post_processing_activity(host, initial_progress_pct=20)
    host._busy_start()
    host._set_controls_enabled(False)
    button = getattr(host, "btn_start", None)
    if button is not None:
        button.setText("Saving QC…")
        button.setToolTip("QC decisions must finish saving before processing can continue.")
        button.setEnabled(False)
    host.processing_title_label.setText("Saving QC Decisions")
    host.processing_message_label.setText("Saving your review before processing continues.")
    # The user just closed our modal review. Return focus once at that handoff;
    # subsequent worker progress never raises or activates the window.
    window = host.window()
    if window.isMinimized():
        window.setWindowState(window.windowState() & ~Qt.WindowMinimized)
    window.show()
    window.raise_()
    window.activateWindow()
    try:
        thread.start()
    except Exception as exc:  # noqa: BLE001 - release controls if a thread cannot start
        logger.exception("frequency_domain_qc_save_thread_start_failed")
        worker.deleteLater()
        bridge.receive_result({"success": False, "error": f"QC decision saving could not start: {exc}"})
        bridge.complete()
        thread.deleteLater()

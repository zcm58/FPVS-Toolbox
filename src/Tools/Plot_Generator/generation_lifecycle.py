"""Cancellation, completion, and thread-lifecycle helpers for SNR plots."""
from __future__ import annotations

import logging

from PySide6.QtWidgets import QMessageBox

from Main_App.gui import shell_status
from Tools.Plot_Generator.generation_outcome import (
    format_completion_summary,
    format_no_plots_message,
    normalize_worker_outcome,
)
from Tools.Plot_Generator.spectral_qc_alerts import (
    build_spectral_qc_alert_message,
)


logger = logging.getLogger(__name__)


def update_workflow_status(owner, text: str, variant: str = "info") -> None:
    """Update the optional inline workflow status without assuming a full GUI."""

    banner = getattr(owner, "workflow_status", None)
    if banner is None:
        return
    banner.set_text(text)
    banner.set_variant(variant)
    banner.setAccessibleDescription(text)
    banner.show()


class PlotGeneratorLifecycleMixin:
    """Own cancellation and completion while a generation thread is active."""

    def _set_workflow_status(self, text: str, variant: str = "info") -> None:
        update_workflow_status(self, text, variant)

    def _set_generation_navigation_locked(self, locked: bool) -> None:
        """Keep embedded Main App navigation stable while a worker is active."""

        if locked:
            if getattr(self, "_snr_navigation_locked", False):
                return
            host = self.window()
            if host is self:
                return
            if getattr(host, "_processing_navigation_states", None):
                return
            shell_status._set_processing_navigation_locked(host, True)
            self._snr_navigation_locked = True
            return
        if not getattr(self, "_snr_navigation_locked", False):
            return
        host = self.window()
        if host is not self:
            shell_status._set_processing_navigation_locked(host, False)
        self._snr_navigation_locked = False

    def _cancel_generation(self) -> None:
        if self._worker is None and self._thread is None:
            return
        self._cancel_requested = True
        if self._worker is not None:
            try:
                self._worker.stop()
            except RuntimeError:
                logger.debug(
                    "SNR plot worker was already released while cancellation "
                    "was requested.",
                    exc_info=True,
                )
        self.cancel_btn.setEnabled(False)
        update_workflow_status(
            self,
            "Stopping SNR plot generation after the current operation...",
            "warning",
        )
        self._append_log(
            "Cancellation requested; waiting for the current plot operation to stop."
        )

    def has_active_generation(self) -> bool:
        """Return whether this page still owns an unfinished worker lifecycle."""

        return self._worker is not None or self._thread is not None

    def shutdown(self) -> bool:
        """Request cancellation and report whether destruction must be deferred."""

        if not self.has_active_generation():
            return False
        if not getattr(self, "_cancel_requested", False):
            self._cancel_generation()
        return True

    def _on_worker_finished(self, payload: dict) -> None:
        outcome = normalize_worker_outcome(payload)
        self._worker_outcome_received = True
        self._worker_reported_cancelled = outcome.cancelled
        self._generated_paths.extend(outcome.generated_paths)
        self._failed_items.extend(outcome.failed_items)
        self._warning_items.extend(outcome.warning_items)
        self._spectral_qc_flags.extend(outcome.spectral_qc_flags)
        if outcome.spectral_qc_flags:
            self._spectral_qc_analysis_identities.append(
                (
                    outcome.analysis_source_kind,
                    outcome.analysis_project_root,
                )
            )
        if (
            outcome.post_processing_required_reason
            and outcome.analysis_project_root
        ):
            self._post_processing_required_request = (
                outcome.post_processing_required_reason,
                outcome.analysis_project_root,
            )
        if outcome.spectral_qc_flags:
            self._append_log(
                "Unexpected SNR peak scan flagged "
                f"{len(outcome.spectral_qc_flags)} participant-electrode pair(s)."
            )
        logger.info(
            "SNR worker finished.",
            extra={
                "operation": "snr_plot_generate",
                "project_root": str(self._project_root) if self._project_root else None,
                "condition": payload.get("condition"),
                "generated_count": len(outcome.generated_paths),
                "spectral_qc_flag_count": len(outcome.spectral_qc_flags),
                "failed_count": len(outcome.failed_items),
                "warning_count": len(outcome.warning_items),
                "cancelled": outcome.cancelled,
            },
        )

    def _finish_all(self) -> None:
        self._set_generation_navigation_locked(False)
        self.gen_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._animate_progress_to(100)
        self.progress_bar.hide()
        self._total_conditions = 0
        self._current_condition = 0

        generated_count = len(self._generated_paths)
        failed_count = len(self._failed_items)
        warning_count = len(self._warning_items)
        spectral_qc_message = build_spectral_qc_alert_message(
            self._spectral_qc_flags,
        )
        late_cancel_after_commit = bool(
            getattr(self, "_late_cancel_after_commit", False)
        )

        if generated_count > 0:
            summary = format_completion_summary(
                generated_count=generated_count,
                warning_count=warning_count,
                failed_count=failed_count,
            )
            self._append_log(summary)
            needs_review = bool(
                failed_count
                or warning_count
                or spectral_qc_message
                or late_cancel_after_commit
            )
            if late_cancel_after_commit:
                status_suffix = " Cancellation arrived after these files were saved."
            elif spectral_qc_message:
                status_suffix = " Spectral QC findings need review."
            else:
                status_suffix = " Use Open Plot Folder to review the files."
            update_workflow_status(
                self,
                summary + status_suffix,
                "warning" if needs_review else "success",
            )
            if failed_count > 0 or warning_count > 0:
                logger.warning(
                    "SNR plot generation completed with warnings or partial failures.",
                    extra={
                        "operation": "snr_plot_generate",
                        "project_root": (
                            str(self._project_root) if self._project_root else None
                        ),
                        "generated_count": generated_count,
                        "failed_count": failed_count,
                        "warning_count": warning_count,
                    },
                )
            if spectral_qc_message:
                QMessageBox.warning(
                    self,
                    "Unexpected SNR Peaks",
                    spectral_qc_message,
                )
                self._offer_spectral_qc_participant_exclusions()
        else:
            no_plots_message = format_no_plots_message(warning_count=warning_count)
            self._append_log(no_plots_message)
            update_workflow_status(self, no_plots_message, "error")
            logger.warning(
                "SNR plot generation produced no plot files.",
                extra={
                    "operation": "snr_plot_generate",
                    "project_root": (
                        str(self._project_root) if self._project_root else None
                    ),
                    "failed_count": failed_count,
                    "warning_count": warning_count,
                },
            )

        post_processing_request = self._post_processing_required_request
        self._generated_paths.clear()
        self._failed_items.clear()
        self._warning_items.clear()
        self._spectral_qc_flags.clear()
        self._spectral_qc_analysis_identities.clear()
        self._post_processing_required_request = None
        self._gen_params = None
        self._cancel_requested = False
        self._worker_reported_cancelled = False
        self._worker_outcome_received = False
        self._late_cancel_after_commit = False
        if post_processing_request is not None:
            reason, project_root = post_processing_request
            self.post_processing_required.emit(
                "SNR Plots",
                reason,
                project_root,
            )

    def _finish_cancelled(self) -> None:
        """Release the UI only after the cancelled worker thread has exited."""

        if self._thread is not None or self._worker is not None:
            return
        self._conditions_queue.clear()
        self._total_conditions = 0
        self._current_condition = 0
        self.gen_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.progress_bar.hide()
        self._set_generation_navigation_locked(False)
        generated_count = len(self._generated_paths)
        if generated_count:
            message = (
                "Generation cancelled. "
                f"{generated_count} completed figure file(s) were kept."
            )
            self._append_log(message)
        else:
            message = "Generation cancelled. No new figure files were saved."
            self._append_log("Generation cancelled.")
        update_workflow_status(self, message, "warning")
        self._generated_paths.clear()
        self._failed_items.clear()
        self._warning_items.clear()
        self._spectral_qc_flags.clear()
        self._spectral_qc_analysis_identities.clear()
        self._post_processing_required_request = None
        self._gen_params = None
        self._cancel_requested = False
        self._worker_reported_cancelled = False
        self._worker_outcome_received = False
        self._late_cancel_after_commit = False

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        worker_cancelled = getattr(self, "_worker_reported_cancelled", False)
        outcome_received = getattr(self, "_worker_outcome_received", False)
        if worker_cancelled or (
            getattr(self, "_cancel_requested", False) and not outcome_received
        ):
            self._finish_cancelled()
            return
        if getattr(self, "_cancel_requested", False):
            self._conditions_queue.clear()
            self._late_cancel_after_commit = True
            self._append_log(
                "Cancellation arrived after a figure pair was already saved; "
                "the completed files were kept."
            )
            self._finish_all()
            return
        if self._post_processing_required_request is not None:
            self._conditions_queue.clear()
            self._finish_all()
            return
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()

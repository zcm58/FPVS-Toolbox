"""Run, status, and log workflow helpers for the Ratio Calculator GUI."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from Main_App.gui.components import show_error, show_info, show_warning

from .worker import RatioCalculatorWorker

logger = logging.getLogger(__name__)


class RatioRunWorkflowMixin:
    """GUI-only run lifecycle, status, and log behavior."""

    def _open_folder_from_edit(self, edit: QLineEdit) -> None:
        path_str = edit.text().strip()
        if not path_str:
            show_info(self, "Missing folder", "No folder has been set yet.")
            return
        path = Path(path_str)
        if not path.exists():
            show_warning(self, "Folder not found", f"Folder does not exist:\n{path}")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(path))
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as exc:
            show_warning(self, "Open failed", f"Failed to open folder:\n{exc}")

    def _set_status_message(self, message: str) -> None:
        if self._thread and self._thread.isRunning():
            return
        self.status_label.set_text(message)
        self._append_log(message)

    def _start_run(self) -> None:
        if self._thread and self._thread.isRunning():
            show_info(self, "Running", "Ratio calculations are already running.")
            return

        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        output_dir = self.output_edit.text().strip()
        label_a = self.label_a_edit.text().strip()
        label_b = self.label_b_edit.text().strip()
        run_label = self.run_label_edit.text().strip()

        if not all([input_a, input_b, output_dir, label_a, label_b, run_label]):
            show_warning(self, "Missing fields", "Fill out all required fields before running.")
            return

        if not self._active_roi_defs:
            message = "Cannot run: no valid ROIs are configured in Settings."
            self._set_status_message(message)
            logger.warning(
                "operation=start_run project_root=%s elapsed_ms=0 error=%s",
                self._project_root,
                message,
            )
            return

        ok_out, out_err = self._ensure_output_dir(output_dir)
        if not ok_out:
            show_warning(self, "Output folder error", out_err or "Output folder is not usable.")
            return

        if not self._paired_participants:
            show_warning(
                self,
                "Participants not loaded",
                "Participants are not loaded yet. Check the condition folders and try again.",
            )
            return

        self.progress.setValue(0)
        self.status_label.set_text("Running...")
        self.status_label.set_variant("info")
        self._log_text = ""
        self.open_output_btn.setEnabled(False)

        settings = self._settings_from_ui()
        manual_list = self._collect_manual_exclusions()
        manual_set = set(manual_list)
        paired_set = set(self._paired_participants)
        assert manual_set.issubset(paired_set)

        n_paired = len(self._paired_participants)
        n_excl = len(manual_set.intersection(paired_set))
        n_used = n_paired - n_excl
        if n_used == 0:
            msg = QMessageBox(self)
            msg.setWindowTitle("All participants excluded")
            msg.setText(
                "You excluded all paired participants. Group summaries and violin/box/mean overlays will be empty."
            )
            go_back_btn = msg.addButton("Go Back", QMessageBox.RejectRole)
            msg.addButton("Continue Anyway", QMessageBox.AcceptRole)
            msg.setDefaultButton(go_back_btn)
            msg.setIcon(QMessageBox.Warning)
            msg.exec()
            if msg.clickedButton() == go_back_btn:
                self.progress.setValue(0)
                self.status_label.set_text("Ready")
                return

        self._thread = QThread()
        self._worker = RatioCalculatorWorker(
            input_dir_a=input_a,
            condition_label_a=label_a,
            input_dir_b=input_b,
            condition_label_b=label_b,
            output_dir=output_dir,
            run_label=run_label,
            manual_exclude=manual_list,
            settings=settings,
            roi_defs=self._active_roi_defs,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.status.connect(self.status_label.set_text)
        self._worker.log.connect(self._append_log)
        self._worker.error.connect(self._handle_error)
        self._worker.finished.connect(self._handle_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _handle_error(self, message: str) -> None:
        self._append_log(message)
        self.status_label.set_text("Error")
        self.status_label.set_variant("error")
        show_error(self, "Ratio Calculator Error", message)
        self._update_run_state()

    def _handle_finished(self, output_dir: str, excel_path: str) -> None:
        self._output_dir = Path(output_dir)
        self._append_log(f"Excel saved to: {excel_path}")
        self.status_label.set_text("Complete")
        self.status_label.set_variant("success")
        self.progress.setValue(100)
        self.open_output_btn.setEnabled(True)
        self._show_completion_dialog()
        self._update_run_state()

    def _show_completion_dialog(self) -> None:
        if self._output_dir is None:
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Processing Complete")
        msg.setText("Aggregation finished successfully.")
        msg.setInformativeText("Would you like to open the output folder?")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setIcon(QMessageBox.Information)
        if msg.exec() == QMessageBox.Yes:
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(self._output_dir))
                else:
                    from PySide6.QtGui import QDesktopServices
                    from PySide6.QtCore import QUrl

                    QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
            except Exception as exc:
                self._append_log(f"Failed to open output folder: {exc}")

    def _open_output_folder(self) -> None:
        if self._output_dir is None:
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(self._output_dir))
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl

                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._output_dir)))
        except Exception as exc:
            self._append_log(f"Failed to open output folder: {exc}")

    def _copy_log(self) -> None:
        QApplication.clipboard().setText(self._log_text)

    def _append_log(self, message: str) -> None:
        self._log_text = f"{self._log_text}\n{message}" if self._log_text else message

    def _update_run_state(self) -> None:
        errors = self._validate_inputs()
        self._set_validation_errors(errors)
        required_fields = all(
            [
                self.input_a_edit.text().strip(),
                self.input_b_edit.text().strip(),
                self.output_edit.text().strip(),
                self.label_a_edit.text().strip(),
                self.label_b_edit.text().strip(),
                self.run_label_edit.text().strip(),
            ]
        )
        if required_fields and not self._paired_participants:
            self._maybe_autoload_participants()
            errors = self._validate_inputs()
            self._set_validation_errors(errors)
        self.run_btn.setEnabled(required_fields and not errors)
        self.input_a_open_btn.setEnabled(bool(self.input_a_edit.text().strip()))
        self.input_b_open_btn.setEnabled(bool(self.input_b_edit.text().strip()))
        self.output_open_btn.setEnabled(bool(self.output_edit.text().strip()))

    def _show_log_dialog(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Ratio Calculator Log")
        dialog.resize(760, 460)
        layout = QVBoxLayout(dialog)
        log_view = QTextEdit(dialog)
        log_view.setReadOnly(True)
        log_view.setProperty("logSurface", True)
        log_view.setPlainText(self._log_text)
        layout.addWidget(log_view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

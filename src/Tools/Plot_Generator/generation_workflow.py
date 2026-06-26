"""Generation workflow and worker wiring for the Plot Generator GUI."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from Main_App.gui.open_paths import open_path_in_file_manager
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participants,
)
from Tools.Plot_Generator.selection_state import ALL_CONDITIONS_OPTION
from Tools.Plot_Generator.spectral_qc_alerts import (
    build_spectral_qc_alert_message,
    whole_participant_exclusion_candidates,
)


logger = logging.getLogger(__name__)


def _worker_class():
    gui_module = sys.modules.get("Tools.Plot_Generator.gui")
    worker_cls = getattr(gui_module, "_Worker", None)
    if worker_cls is not None:
        return worker_cls
    from Tools.Plot_Generator.worker import _Worker

    return _Worker


def _thread_class():
    gui_module = sys.modules.get("Tools.Plot_Generator.gui")
    return getattr(gui_module, "QThread", QThread)


class PlotGeneratorWorkflowMixin:
    """QThread generation workflow helpers for PlotGeneratorWindow."""

    def _append_log(self, text: str) -> None:
        self.log.append(text)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _animate_progress_to(self, value: int) -> None:
        """Animate the progress bar smoothly to the target value."""
        self._progress_anim.stop()
        self._progress_anim.setStartValue(self.progress_bar.value())
        self._progress_anim.setEndValue(value)
        self._progress_anim.start()

    def _on_progress(self, msg: str, processed: int, total: int) -> None:
        if msg:
            self._append_log(msg)
        if total == 0:
            return

        if self._total_conditions:
            frac = (self._current_condition - 1) / self._total_conditions
            if total:
                frac += processed / total / self._total_conditions
            value = int(frac * 100)
        else:
            value = int(100 * processed / total) if total else 0
        self._animate_progress_to(value)

    def _cancel_generation(self) -> None:
        if self._worker:
            self._worker.stop()
        if self._thread:
            self._thread.quit()
        self._conditions_queue.clear()
        self._total_conditions = 0
        self._current_condition = 0
        self._spectral_qc_flags.clear()
        self._spectral_qc_report_paths.clear()
        self.cancel_btn.setEnabled(False)
        self.gen_btn.setEnabled(True)
        self._append_log("Generation cancelled.")

    def _start_next_condition(self) -> None:
        if not self._conditions_queue:
            self._finish_all()
            return
        params = self._gen_params
        if params is None:
            self._finish_all()
            return
        if len(params) == 6:
            folder, out_dir, x_min, x_max, y_min, y_max = params
            group_kwargs = {}
            legend_payload = self._legend_settings_payload()
        else:
            (
                folder,
                out_dir,
                x_min,
                x_max,
                y_min,
                y_max,
                group_kwargs,
                legend_payload,
            ) = params
        condition = self._conditions_queue.pop(0)
        self._current_condition += 1

        roi_payload = self._worker_roi_selection()
        if roi_payload is None:
            self._conditions_queue.clear()
            self._finish_all()
            return
        roi_map_for_worker, selected_roi = roi_payload
        self._append_log(
            f"Generating condition '{condition}' for ROI selection '{selected_roi}'."
        )

        cond_out = Path(out_dir)
        if self._all_conditions:
            cond_out = cond_out / f"{condition} Plots"
            title = condition
            self.title_edit.setText(title)
        else:
            title = self.title_edit.text()

        self._thread = _thread_class()()
        self._worker = _worker_class()(
            folder,
            condition,
            roi_map_for_worker,
            selected_roi,
            title,
            self.xlabel_edit.text(),
            self.ylabel_edit.text(),
            x_min,
            x_max,
            y_min,
            y_max,
            str(cond_out),
            self.stem_color,
            legend_custom_enabled=bool(legend_payload["custom_labels_enabled"]),
            legend_condition_a=str(legend_payload["condition_a_label"]),
            legend_condition_b=str(legend_payload["condition_b_label"]),
            legend_a_peaks=str(legend_payload["a_peaks_label"]),
            legend_b_peaks=str(legend_payload["b_peaks_label"]),
            project_root=(
                str(self._project_root) if self._project_root else None
            ),
            spectral_qc_enabled=self.spectral_qc_check.isChecked(),
            **group_kwargs,
        )
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._generation_finished)
        self._thread.start()

    def _on_worker_finished(self, payload: dict) -> None:
        generated = payload.get("generated_paths", [])
        qc_reports = payload.get("qc_report_paths", [])
        spectral_qc_flags = payload.get("spectral_qc_flags", [])
        failed = payload.get("failed_items", [])
        generated_paths = [
            str(path) for path in generated if isinstance(path, str) and path
        ]
        qc_report_paths = [
            str(path) for path in qc_reports if isinstance(path, str) and path
        ]
        flagged_electrodes = [
            dict(item) for item in spectral_qc_flags if isinstance(item, dict)
        ]
        failed_items = [
            {"item": str(item.get("item", "")), "error": str(item.get("error", ""))}
            for item in failed
            if isinstance(item, dict)
        ]
        self._generated_paths.extend(generated_paths)
        self._failed_items.extend(failed_items)
        self._spectral_qc_report_paths.extend(qc_report_paths)
        self._spectral_qc_flags.extend(flagged_electrodes)
        for path in qc_report_paths:
            self._append_log(f"Spectral QC report: {path}")
        if flagged_electrodes:
            self._append_log(
                f"Spectral QC flagged {len(flagged_electrodes)} participant-electrode pair(s)."
            )
        logger.info(
            "SNR worker finished.",
            extra={
                "operation": "snr_plot_generate",
                "project_root": str(self._project_root) if self._project_root else None,
                "condition": payload.get("condition"),
                "generated_count": len(generated_paths),
                "qc_report_count": len(qc_report_paths),
                "spectral_qc_flag_count": len(flagged_electrodes),
                "failed_count": len(failed_items),
            },
        )

    def _finish_all(self) -> None:
        self.gen_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self._animate_progress_to(100)
        self._total_conditions = 0
        self._current_condition = 0

        generated_count = len(self._generated_paths)
        failed_count = len(self._failed_items)
        spectral_qc_message = build_spectral_qc_alert_message(
            self._spectral_qc_flags,
            self._spectral_qc_report_paths,
        )

        if generated_count > 0:
            if failed_count > 0:
                msg = f"Generated {generated_count} plots; {failed_count} failed. See logs for details."
                self._append_log(msg)
                logger.warning(
                    "SNR plot generation completed with partial failures.",
                    extra={
                        "operation": "snr_plot_generate",
                        "project_root": str(self._project_root) if self._project_root else None,
                        "generated_count": generated_count,
                        "failed_count": failed_count,
                    },
                )
            if spectral_qc_message:
                QMessageBox.warning(
                    self,
                    "Spectral QC Flags",
                    spectral_qc_message,
                )
                self._offer_spectral_qc_participant_exclusions()
            resp = QMessageBox.question(
                self,
                "Finished",
                "Plots have been successfully generated. View plots?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if resp == QMessageBox.Yes:
                self._open_output_folder()
        else:
            self._append_log("No plots were generated. Please check the log for errors.")
            logger.warning(
                "SNR plot generation produced no plot files.",
                extra={
                    "operation": "snr_plot_generate",
                    "project_root": str(self._project_root) if self._project_root else None,
                    "failed_count": failed_count,
                },
            )

        self._generated_paths.clear()
        self._failed_items.clear()
        self._spectral_qc_flags.clear()
        self._spectral_qc_report_paths.clear()

    def _offer_spectral_qc_participant_exclusions(self) -> None:
        candidates = whole_participant_exclusion_candidates(self._spectral_qc_flags)
        if not candidates or self._project is None:
            return
        candidate_pids = [str(item["pid"]) for item in candidates if item.get("pid")]
        current = normalize_manual_excluded_participants(
            (self._project.preprocessing or {}).get("manual_excluded_participants", [])
        )
        current_lookup = {pid.casefold() for pid in current}
        new_pids = [
            pid for pid in candidate_pids if pid.casefold() not in current_lookup
        ]
        if not new_pids:
            return
        label = ", ".join(new_pids)
        prompt = (
            f"Exclude {label} from future processing?\n\n"
            "This updates the project's manual participant exclusion list. "
            "Raw BDF files are not altered. Reprocess the dataset for this "
            "change to affect the processed Excel files and future plots."
        )
        response = QMessageBox.question(
            self,
            "Exclude Participant From Dataset?",
            prompt,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if response != QMessageBox.Yes:
            return
        updated = normalize_manual_excluded_participants([*current, *new_pids])
        payload = dict(self._project.preprocessing or {})
        payload["manual_excluded_participants"] = updated
        try:
            self._project.update_preprocessing(payload)
            self._project.save()
        except Exception as exc:  # pragma: no cover - disk I/O error path
            logger.exception("Failed to save spectral QC participant exclusions.")
            QMessageBox.critical(
                self,
                "Project Save Error",
                f"Could not save participant exclusions: {exc}",
            )
            return
        self._append_log(
            "Added manual participant exclusion(s): " + ", ".join(new_pids)
        )
        QMessageBox.information(
            self,
            "Participant Exclusion Saved",
            (
                f"Added {label} to manual participant exclusions.\n\n"
                "Reprocess the dataset before relying on affected figures or analyses. "
                "The raw BDF files were not altered."
            ),
        )

    def _generate(self) -> None:
        log_context = {
            "operation": "snr_plot_generate",
            "project_root": str(self._project_root) if self._project_root else None,
            "compare_two_conditions": self.overlay_check.isChecked(),
            "custom_labels_enabled": self.legend_custom_check.isChecked(),
        }
        logger.info("SNR plot generation started.", extra=log_context)
        try:
            folder = self.folder_edit.text()
            if not folder:
                QMessageBox.critical(self, "Error", "Select a folder first.")
                return

            out_dir = self.out_edit.text()
            if not out_dir:
                QMessageBox.critical(self, "Error", "Select an output folder first.")
                return

            if not self.condition_combo.currentText():
                QMessageBox.critical(self, "Error", "No condition selected.")
                return
            try:
                x_min = self.xmin_spin.value()
                x_max = self.xmax_spin.value()
                y_min = self.ymin_spin.value()
                y_max = self.ymax_spin.value()
            except ValueError:
                QMessageBox.critical(self, "Error", "Invalid axis limits.")
                return

            overlay_groups = self._group_overlay_enabled()
            selected_groups = self._selected_groups() if overlay_groups else []
            if overlay_groups and not selected_groups:
                QMessageBox.warning(
                    self,
                    "Group Overlay",
                    "Select at least one group before plotting.",
                )
                self.gen_btn.setEnabled(True)
                self.cancel_btn.setEnabled(False)
                return
            if overlay_groups and not self._subject_groups_map:
                QMessageBox.warning(
                    self,
                    "Group Overlay",
                    "Group assignments were not found in project.json. "
                    "Process or register participants before using group overlays.",
                )
                self.gen_btn.setEnabled(True)
                self.cancel_btn.setEnabled(False)
                return
            group_kwargs = self._group_worker_kwargs(overlay_groups, selected_groups)
            legend_payload = self._legend_settings_payload()
            if self._project is not None:
                self._persist_project_plot_settings(include_paths=True)

            self.gen_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.log.clear()
            self._generated_paths.clear()
            self._failed_items.clear()
            self._spectral_qc_flags.clear()
            self._spectral_qc_report_paths.clear()
            self._animate_progress_to(0)
            if self.overlay_check.isChecked():
                cond_a = self.condition_combo.currentText()
                cond_b = self.condition_b_combo.currentText()
                if cond_a == cond_b:
                    QMessageBox.critical(self, "Error", "Select two different conditions.")
                    self.gen_btn.setEnabled(True)
                    self.cancel_btn.setEnabled(False)
                    return
                roi_payload = self._worker_roi_selection()
                if roi_payload is None:
                    self.gen_btn.setEnabled(True)
                    self.cancel_btn.setEnabled(False)
                    return
                roi_map_for_worker, selected_roi = roi_payload
                self._append_log(
                    f"Generating overlay '{cond_a}' vs '{cond_b}' for ROI selection '{selected_roi}'."
                )
                self._thread = _thread_class()()
                self._worker = _worker_class()(
                    folder,
                    cond_a,
                    roi_map_for_worker,
                    selected_roi,
                    self.title_edit.text(),
                    self.xlabel_edit.text(),
                    self.ylabel_edit.text(),
                    x_min,
                    x_max,
                    y_min,
                    y_max,
                    out_dir,
                    self.stem_color,
                    condition_b=cond_b,
                    stem_color_b=self.stem_color_b,
                    overlay=True,
                    legend_custom_enabled=bool(legend_payload["custom_labels_enabled"]),
                    legend_condition_a=str(legend_payload["condition_a_label"]),
                    legend_condition_b=str(legend_payload["condition_b_label"]),
                    legend_a_peaks=str(legend_payload["a_peaks_label"]),
                    legend_b_peaks=str(legend_payload["b_peaks_label"]),
                    project_root=(
                        str(self._project_root) if self._project_root else None
                    ),
                    spectral_qc_enabled=self.spectral_qc_check.isChecked(),
                    **group_kwargs,
                )
                self._worker.moveToThread(self._thread)
                self._thread.started.connect(self._worker.run)
                self._worker.progress.connect(self._on_progress)
                self._worker.finished.connect(self._on_worker_finished)
                self._worker.finished.connect(self._thread.quit)
                self._worker.finished.connect(self._worker.deleteLater)
                self._thread.finished.connect(self._thread.deleteLater)
                self._thread.finished.connect(self._finish_all)
                self._thread.start()
            else:
                self._all_conditions = (
                    self.condition_combo.currentText() == ALL_CONDITIONS_OPTION
                )
                if self._all_conditions:
                    self._conditions_queue = [
                        self.condition_combo.itemText(i)
                        for i in range(1, self.condition_combo.count())
                    ]
                else:
                    self._conditions_queue = [self.condition_combo.currentText()]
                self._total_conditions = len(self._conditions_queue)
                self._current_condition = 0
                if self._conditions_queue:
                    self._append_log(
                        "Queued conditions: " + ", ".join(self._conditions_queue)
                    )
                self._gen_params = (
                    folder,
                    out_dir,
                    x_min,
                    x_max,
                    y_min,
                    y_max,
                    group_kwargs.copy(),
                    legend_payload.copy(),
                )
                self._start_next_condition()
        except Exception as exc:
            self._append_log("SNR plot generation failed. See logs for details.")
            logger.error(
                "SNR plot generation failed.",
                exc_info=exc,
                extra=log_context,
            )
            self.gen_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            return

    def _open_output_folder(self) -> None:
        folder = self.out_edit.text()
        if not folder:
            return
        open_path_in_file_manager(folder)

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()

"""Generation workflow and worker wiring for the Plot Generator GUI."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QMessageBox

from Tools.Plot_Generator.selection_state import ALL_CONDITIONS_OPTION


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
            include_scalp = self.scalp_check.isChecked()
            scalp_min = self.scalp_min_spin.value()
            scalp_max = self.scalp_max_spin.value()
            scalp_title_a = self.scalp_title_a_edit.text().strip()
            scalp_title_b = self.scalp_title_b_edit.text().strip()
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
                include_scalp,
                scalp_min,
                scalp_max,
                scalp_title_a,
                scalp_title_b,
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
            include_scalp_maps=include_scalp,
            scalp_vmin=scalp_min,
            scalp_vmax=scalp_max,
            scalp_title_a_template=scalp_title_a,
            scalp_title_b_template=scalp_title_b,
            legend_custom_enabled=bool(legend_payload["custom_labels_enabled"]),
            legend_condition_a=str(legend_payload["condition_a_label"]),
            legend_condition_b=str(legend_payload["condition_b_label"]),
            legend_a_peaks=str(legend_payload["a_peaks_label"]),
            legend_b_peaks=str(legend_payload["b_peaks_label"]),
            project_root=(
                str(self._project_root) if self._project_root else None
            ),
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
        failed = payload.get("failed_items", [])
        generated_paths = [
            str(path) for path in generated if isinstance(path, str) and path
        ]
        failed_items = [
            {"item": str(item.get("item", "")), "error": str(item.get("error", ""))}
            for item in failed
            if isinstance(item, dict)
        ]
        self._generated_paths.extend(generated_paths)
        self._failed_items.extend(failed_items)
        logger.info(
            "SNR worker finished.",
            extra={
                "operation": "snr_plot_generate",
                "project_root": str(self._project_root) if self._project_root else None,
                "condition": payload.get("condition"),
                "generated_count": len(generated_paths),
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

            include_scalp = self.scalp_check.isChecked()
            scalp_min = self.scalp_min_spin.value()
            scalp_max = self.scalp_max_spin.value()

            if include_scalp:
                if not self.scalp_title_a_edit.text().strip():
                    QMessageBox.warning(
                        self,
                        "Scalp Title",
                        "Please enter a scalp title for Condition A.",
                    )
                    return
                if (
                    self.overlay_check.isChecked()
                    and not self.scalp_title_b_edit.text().strip()
                ):
                    QMessageBox.warning(
                        self,
                        "Scalp Title",
                        "Please enter a scalp title for Condition B.",
                    )
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
            group_kwargs = self._group_worker_kwargs(overlay_groups, selected_groups)
            legend_payload = self._legend_settings_payload()
            if self._project is not None:
                self._persist_project_plot_settings(include_paths=True)
            else:
                self._persist_scalp_settings(save=True)

            self.gen_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.log.clear()
            self._generated_paths.clear()
            self._failed_items.clear()
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
                    include_scalp_maps=include_scalp,
                    scalp_vmin=scalp_min,
                    scalp_vmax=scalp_max,
                    scalp_title_a_template=self.scalp_title_a_edit.text(),
                    scalp_title_b_template=self.scalp_title_b_edit.text(),
                    legend_custom_enabled=bool(legend_payload["custom_labels_enabled"]),
                    legend_condition_a=str(legend_payload["condition_a_label"]),
                    legend_condition_b=str(legend_payload["condition_b_label"]),
                    legend_a_peaks=str(legend_payload["a_peaks_label"]),
                    legend_b_peaks=str(legend_payload["b_peaks_label"]),
                    project_root=(
                        str(self._project_root) if self._project_root else None
                    ),
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
                    include_scalp,
                    scalp_min,
                    scalp_max,
                    self.scalp_title_a_edit.text(),
                    self.scalp_title_b_edit.text(),
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
        if sys.platform.startswith("win"):
            os.startfile(folder)
        elif sys.platform == "darwin":
            subprocess.call(["open", folder])
        else:
            subprocess.call(["xdg-open", folder])

    def _generation_finished(self) -> None:
        self._thread = None
        self._worker = None
        if self._conditions_queue:
            self._start_next_condition()
            return
        self._finish_all()

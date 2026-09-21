"""Background destination checks and GUI-only SNR replacement decisions."""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QMessageBox

from .export_plan import ExportChoices, inspect_destinations
from .render_naming import GROUP_OVERLAY_SUFFIX, SESSION_COMPARISON_SUFFIX
from .selection_state import ALL_CONDITIONS_OPTION

logger = logging.getLogger(__name__)


class ExportPreflightWorker(QObject):
    completed = Signal(object, str)

    def __init__(self, output_folder, identities):
        super().__init__()
        self.output_folder = output_folder
        self.identities = identities
        self._stopped = threading.Event()

    def stop(self):
        self._stopped.set()

    @Slot()
    def run(self):
        try:
            choices = inspect_destinations(self.output_folder, self.identities, self._stopped.is_set)
        except Exception as exc:
            logger.exception("Could not inspect SNR figure destinations.")
            self.completed.emit(None, str(exc))
        else:
            self.completed.emit(choices, "")


class PlotExportWorkflowMixin:
    """Freeze controls while inspecting and approving the exact figure names."""

    def _export_identities(self):
        selection = self._worker_roi_selection()
        if selection is None:
            return ()
        roi_map, _selected_roi = selection
        condition = self.condition_combo.currentText()
        overlay = self.overlay_check.isChecked()
        if overlay:
            titles = (self.title_edit.text() or f"{condition} vs {self.condition_b_combo.currentText()}",)
        elif condition == ALL_CONDITIONS_OPTION:
            titles = tuple(self.condition_combo.itemText(i) for i in range(1, self.condition_combo.count()))
        else:
            titles = (self.title_edit.text() or condition,)
        suffix = ""
        if self._session_comparison_active():
            suffix = SESSION_COMPARISON_SUFFIX
        elif self._group_overlay_enabled() and not overlay:
            suffix = GROUP_OVERLAY_SUFFIX
        return tuple((title, roi, suffix) for title in titles for roi in roi_map)

    def _begin_export_preflight(self):
        identities = self._export_identities()
        if not identities:
            return
        self._approved_export_plan = None
        self._pending_export_choices = None
        self._export_preflight_error = ""
        self._cancel_requested = False
        self._clear_generation_result_state()
        self._set_generation_navigation_locked(True)
        self.gen_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self._set_workflow_status("Checking figure destinations...", "info")
        self._thread = QThread()
        self._worker = ExportPreflightWorker(self.out_edit.text(), identities)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.completed.connect(self._on_export_preflight_completed)
        self._worker.completed.connect(self._thread.quit)
        self._worker.completed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._export_preflight_finished)
        self._thread.start()

    def _on_export_preflight_completed(self, choices, error):
        self._pending_export_choices = choices
        self._export_preflight_error = error

    def _choose_export_collision_action(self, choices: ExportChoices):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("SNR figures already exist")
        dialog.setIcon(QMessageBox.Warning)
        dialog.setText(
            f"{len(choices.collisions)} figure pair(s) have existing PNG or PDF files."
        )
        dialog.setInformativeText(
            "Keep both gives only these pairs a numbered name. Replace existing "
            "replaces only the listed pairs. Cancel leaves your files unchanged."
        )
        dialog.setDetailedText("\n".join(str(item.png_path.with_suffix("")) for item in choices.collisions))
        replace = dialog.addButton("Replace existing", QMessageBox.DestructiveRole)
        keep = dialog.addButton("Keep both", QMessageBox.AcceptRole)
        cancel = dialog.addButton(QMessageBox.Cancel)
        dialog.setDefaultButton(keep)
        dialog.setEscapeButton(cancel)
        dialog.exec()
        if dialog.clickedButton() is replace:
            return choices.replace
        if dialog.clickedButton() is keep:
            return choices.keep_both
        return None

    def _export_preflight_finished(self):
        self._thread = None
        self._worker = None
        self.progress_bar.setRange(0, 100)
        choices = self._pending_export_choices
        self._pending_export_choices = None
        if self._cancel_requested:
            self._finish_cancelled()
            return
        if self._export_preflight_error or choices is None:
            self.progress_bar.hide()
            self.cancel_btn.setEnabled(False)
            self._set_generation_navigation_locked(False)
            self._check_required()
            self._set_workflow_status(
                f"Could not check figure destinations: {self._export_preflight_error}", "error"
            )
            return
        plan = self._choose_export_collision_action(choices) if choices.collisions else choices.replace
        if plan is None:
            self._finish_cancelled()
            return
        self._approved_export_plan = plan
        self._generate()

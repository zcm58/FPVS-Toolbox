"""User action handlers and general StatsWindow view helpers."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowActionsMixin:
    def _set_status(self, txt: str) -> None:
        """Handle the set status step for the Stats workflow."""
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText(txt)
            self.lbl_status.setToolTip(txt)

    def _set_roi_status(self, txt: str) -> None:
        """Handle the set roi status step for the Stats workflow."""
        if hasattr(self, "lbl_rois"):
            self.lbl_rois.setText(txt)

    def _set_data_folder_path(self, path: str) -> None:
        """Handle the set data folder path step for the Stats workflow."""
        if hasattr(self, "le_folder"):
            self.le_folder.setText(path or "")
            if not path:
                self.le_folder.setToolTip(
                    "Selected folder that contains the FPVS result spreadsheets."
                )

    def _set_last_export_path(self, path: str | None) -> None:
        """Handle the set last export path step for the Stats workflow."""
        self._last_export_path = path or ""
        if hasattr(self, "export_path_label"):
            self.export_path_label.set_full_text(self._last_export_path)
        exists = bool(self._last_export_path and Path(self._last_export_path).exists())
        if hasattr(self, "export_open_btn"):
            self.export_open_btn.setEnabled(exists)
        if hasattr(self, "export_copy_btn"):
            self.export_copy_btn.setEnabled(bool(self._last_export_path))

    def _copy_text_to_clipboard(self, text: str, *, context: str) -> None:
        """Handle the copy text to clipboard step for the Stats workflow."""
        try:
            QGuiApplication.clipboard().setText(text or "")
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_clipboard_copy_failed",
                exc_info=True,
                extra={"context": context, "error": str(exc)},
            )
            self._set_status(f"Copy failed ({context}).")

    def _copy_summary_text(self) -> None:
        """Handle the copy summary text step for the Stats workflow."""
        text = self.summary_text.toPlainText()
        self._copy_text_to_clipboard(text, context="summary")

    def _copy_reporting_summary_text(self) -> None:
        """Handle the copy reporting summary text step for the Stats workflow."""
        text = self.reporting_summary_text.toPlainText() if hasattr(self, "reporting_summary_text") else ""
        self._copy_text_to_clipboard(text, context="reporting_summary")

    def _save_reporting_summary_text(self) -> None:
        """Handle the save reporting summary text step for the Stats workflow."""
        report_text = self.reporting_summary_text.toPlainText() if hasattr(self, "reporting_summary_text") else ""
        if not report_text.strip():
            self._set_status("No reporting summary available to save yet.")
            return
        default_path = build_default_report_path(self._project_path, datetime.now())
        default_path.parent.mkdir(parents=True, exist_ok=True)
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Reporting Summary",
            str(default_path),
            "Text Files (*.txt)",
        )
        if not target:
            self._set_status("Reporting summary save canceled.")
            return
        try:
            target_path = safe_project_path_join(self._project_path, Path(target).relative_to(self._project_path).as_posix())
        except Exception:
            self._set_status("Save canceled: selected path must be under the active project root.")
            return
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(report_text, encoding="utf-8")
            self._set_status(f"Reporting summary saved: {target_path}")
            self._set_last_export_path(str(target_path))
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_reporting_summary_save_failed",
                exc_info=True,
                extra={
                    "operation": "save_reporting_summary_dialog",
                    "project": self.project_title,
                    "path": str(target_path),
                    "elapsed_ms": 0,
                    "exception": str(exc),
                },
            )
            self._set_status("Failed to save reporting summary text.")

    def _copy_log_text(self) -> None:
        """Handle the copy log text step for the Stats workflow."""
        text = self.log_text.toPlainText()
        self._copy_text_to_clipboard(text, context="log")

    def _open_export_path(self) -> None:
        """Handle the open export path step for the Stats workflow."""
        path = self._last_export_path or ""
        if not path:
            self._set_status("No export path available yet.")
            return
        if not Path(path).exists():
            self._set_status(f"Export path not found: {path}")
            logger.error("stats_export_open_missing", extra={"path": path})
            return
        try:
            os.startfile(path)  # noqa: S606
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_export_open_failed",
                exc_info=True,
                extra={"path": path, "error": str(exc)},
            )
            self._set_status(f"Failed to open export path: {path}")

    def _copy_export_path(self) -> None:
        """Handle the copy export path step for the Stats workflow."""
        path = self._last_export_path or ""
        if not path:
            return
        self._copy_text_to_clipboard(path, context="export_path")

    def _clear_output_views(self) -> None:
        """Handle the clear output views step for the Stats workflow."""
        self.summary_text.clear()
        self.output_text.clear()

    def _set_detected_info(self, txt: str) -> None:
        """Route unknown worker messages to proper label."""
        lower_txt = txt.lower() if isinstance(txt, str) else str(txt).lower()
        if (" roi" in lower_txt) or lower_txt.startswith("using ") or lower_txt.startswith("rois"):
            self._set_roi_status(txt)
        else:
            self._set_status(txt)

    def _clear_conditions_layout(self) -> None:
        """Handle the clear conditions layout step for the Stats workflow."""
        layout = self.conditions_list_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate_conditions_panel(self, conditions: List[str]) -> None:
        """Handle the populate conditions panel step for the Stats workflow."""
        self._clear_conditions_layout()
        self._condition_checkboxes.clear()
        if not conditions:
            placeholder = QLabel("No conditions detected yet.")
            placeholder.setWordWrap(True)
            self.conditions_list_layout.addWidget(placeholder)
            self.selected_conditions = []
            return

        for condition in conditions:
            checkbox = QCheckBox(condition)
            checkbox.setChecked(True)
            checkbox.setToolTip(
                "Include this condition in the analysis."
            )
            checkbox.stateChanged.connect(self._on_condition_toggled)
            self.conditions_list_layout.addWidget(checkbox)
            self._condition_checkboxes[condition] = checkbox

        self.conditions_list_layout.addStretch(1)
        self._sync_selected_conditions()

    def _sync_selected_conditions(self) -> None:
        """Handle the sync selected conditions step for the Stats workflow."""
        self.selected_conditions = [
            name for name, checkbox in self._condition_checkboxes.items() if checkbox.isChecked()
        ]

    def _on_condition_toggled(self, _state: int) -> None:
        """Handle the on condition toggled step for the Stats workflow."""
        self._sync_selected_conditions()

    def _on_dv_variant_toggled(self, _state: int) -> None:
        """Handle the on dv variant toggled step for the Stats workflow."""
        self._sync_selected_dv_variants()

    def _select_all_conditions(self) -> None:
        """Handle the select all conditions step for the Stats workflow."""
        for checkbox in self._condition_checkboxes.values():
            checkbox.setChecked(True)
        self._sync_selected_conditions()

    def _select_no_conditions(self) -> None:
        """Handle the select no conditions step for the Stats workflow."""
        for checkbox in self._condition_checkboxes.values():
            checkbox.setChecked(False)
        self._sync_selected_conditions()

    def _get_selected_conditions(self) -> List[str]:
        """Handle the get selected conditions step for the Stats workflow."""
        if self._condition_checkboxes:
            return list(self.selected_conditions)
        return list(self.conditions)

    def on_analyze_single_group_clicked(self) -> None:
        """Handle the on analyze single group clicked step for the Stats workflow."""
        self._controller.run_single_group_analysis()

    def _open_advanced_dialog(self, title: str, actions: list[tuple[str, Callable[[], None], bool]]) -> None:
        """Handle the open advanced dialog step for the Stats workflow."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        for text, cb, enabled in actions:
            btn = make_action_button(text)
            btn.setEnabled(enabled)
            if text.lower().startswith("export"):
                btn.setToolTip("Export the results for this step to Excel.")
            btn.clicked.connect(cb)
            layout.addWidget(btn)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def on_single_advanced_clicked(self) -> None:
        """Handle the on single advanced clicked step for the Stats workflow."""
        actions = [
            ("Run RM-ANOVA", self.on_run_rm_anova, True),
            ("Run Mixed Model", self.on_run_mixed_model, True),
            ("Run Interaction/Post-hocs", self.on_run_interaction_posthocs, True),
            (
                "Export RM-ANOVA",
                self.on_export_rm_anova,
                isinstance(self.rm_anova_results_data, pd.DataFrame) and not self.rm_anova_results_data.empty,
            ),
            (
                "Export Mixed Model",
                self.on_export_mixed_model,
                isinstance(self.mixed_model_results_data, pd.DataFrame) and not self.mixed_model_results_data.empty,
            ),
            (
                "Export Post-hocs",
                self.on_export_posthoc,
                isinstance(self.posthoc_results_data, pd.DataFrame) and not self.posthoc_results_data.empty,
            ),
        ]
        self._open_advanced_dialog("Single Group – Advanced", actions)

    def _check_for_open_excel_files(self, folder_path: str) -> bool:
        """Best-effort check to avoid writing to open Excel files."""
        open_files = check_for_open_excel_files(folder_path)
        if open_files:
            file_list_str = "\n - ".join(open_files)
            error_message = (
                "The following Excel file(s) appear to be open:\n\n"
                f"<b> - {file_list_str}</b>\n\n"
                "Please close all Excel files in the data directory and try again."
            )
            QMessageBox.critical(self, "Open Excel File Detected", error_message)
            return True
        return False

    # ---- run buttons ----

    def on_run_rm_anova(self) -> None:
        """Handle the on run rm anova step for the Stats workflow."""
        self._clear_output_views()
        self.rm_anova_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_rm_anova_only()

    def on_run_mixed_model(self) -> None:
        """Handle the on run mixed model step for the Stats workflow."""
        self._clear_output_views()
        self.mixed_model_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_mixed_model_only()

    def on_run_interaction_posthocs(self) -> None:
        """Handle the on run interaction posthocs step for the Stats workflow."""
        self._clear_output_views()
        self.posthoc_results_data = None
        our = self._update_export_buttons  # keep line short
        our()
        self._controller.run_single_group_posthoc_only()

    # ---- exports ----

    def on_export_rm_anova(self) -> None:
        """Handle the on export rm anova step for the Stats workflow."""
        if not isinstance(self.rm_anova_results_data, pd.DataFrame) or self.rm_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run RM-ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova", self.rm_anova_results_data, out_dir)
            self._set_status(f"RM-ANOVA exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("RM-ANOVA export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_mixed_model(self) -> None:
        """Handle the on export mixed model step for the Stats workflow."""
        if not isinstance(self.mixed_model_results_data, pd.DataFrame) or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm", self.mixed_model_results_data, out_dir)
            self._set_status(f"Mixed Model results exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Mixed Model export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_export_posthoc(self) -> None:
        """Handle the on export posthoc step for the Stats workflow."""
        if not isinstance(self.posthoc_results_data, pd.DataFrame) or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Interaction Post-hocs first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("posthoc", self.posthoc_results_data, out_dir)
            self._set_status(f"Post-hoc results exported to: {out_dir}")
            self._set_last_export_path(out_dir)
        except Exception as e:
            import traceback
            logger.exception("Post-hoc export failed.")
            tb = traceback.format_exc()
            QMessageBox.critical(self, "Export Failed", f"{type(e).__name__}: {e}\n\n{tb}")

    def on_browse_folder(self) -> None:
        """Handle the on browse folder step for the Stats workflow."""
        start_dir = self.le_folder.text() or self.project_dir
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", start_dir)
        if folder:
            self._set_data_folder_path(folder)
            self._scan_button_clicked()

    def _scan_button_clicked(self) -> None:
        """Handle the scan button clicked step for the Stats workflow."""
        if not self._scan_guard.start():
            return
        try:
            self.refresh_rois()
            folder = self.le_folder.text()
            if not folder:
                QMessageBox.warning(self, "No Folder", "Please select a data folder first.")
                return
            try:
                scan_result = load_project_scan(folder)
                self.subjects = scan_result.subjects
                self.conditions = scan_result.conditions
                self._populate_conditions_panel(self.conditions)
                self.subject_data = scan_result.subject_data
                self._participants_map = dict(scan_result.participants_map)
                self._subject_group_map = map_subjects_to_groups(
                    self.subjects,
                    self._participants_map,
                )
                self._reconcile_manual_exclusions(self.subjects)
                self._set_status(
                    f"Scan complete: Found {len(scan_result.subjects)} subjects and {len(scan_result.conditions)} conditions."
                )
            except ScanError as e:
                self._set_status(f"Scan failed: {e}")
                QMessageBox.critical(self, "Scan Error", str(e))
        finally:
            self._scan_guard.done()

    def _preferred_stats_folder(self) -> Path:
        """Default Excel folder derived from the project manifest."""
        return resolve_project_subfolder(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            "excel",
            EXCEL_SUBFOLDER_NAME,
        )

    def _load_default_data_folder(self) -> None:
        """
        On open, auto-select the manifest-defined Excel folder (defaults to
        ``1 - Excel Data Files`` under the project root). If it doesn't exist,
        do nothing (user can Browse).
        """
        target = self._preferred_stats_folder()
        if target.exists() and target.is_dir():
            self._set_data_folder_path(str(target))
            self._scan_button_clicked()
        else:
            # Leave UI as-is; user will browse. Status hint only.
            self._set_status(
                f"Select the project's '{EXCEL_SUBFOLDER_NAME}' folder to begin."
            )

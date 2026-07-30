"""User action handlers and general StatsWindow view helpers."""
# ruff: noqa: F405

from __future__ import annotations

from html import escape

from Main_App.gui.open_paths import open_path_in_file_manager
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
        text = str(txt or "").strip()
        if hasattr(self, "roi_context_text"):
            self.roi_context_text.setHtml(self._format_roi_context_html(text))
            self.roi_context_text.setToolTip(text)
            self.roi_context_text.moveCursor(QTextCursor.Start)
            return
        if hasattr(self, "lbl_rois"):
            self.lbl_rois.setText(text)

    def _format_roi_context_html(self, txt: str) -> str:
        """Format ROI settings text for the compact Advanced-tab context panel."""
        text = str(txt or "").strip()
        if not text:
            return (
                "<p><b>ROI context unavailable.</b></p>"
                "<p>Load a project or refresh Settings to show the active ROI definitions.</p>"
            )
        if text == "No ROIs defined in Settings.":
            return (
                "<p><b>No ROIs are defined in Settings.</b></p>"
                "<p>Add ROI definitions in Settings before running ROI-based summaries.</p>"
            )
        if text.lower().startswith("using ") and "from Settings:" in text:
            summary, roi_names_text = text.split(":", 1)
            roi_names = [name.strip() for name in roi_names_text.split(",") if name.strip()]
            items = "".join(f"<li>{escape(name)}</li>" for name in roi_names)
            return (
                "<p><b>ROI definitions loaded from Settings.</b></p>"
                f"<p>{escape(summary.strip())}.</p>"
                f"<ul>{items}</ul>"
            )
        escaped_lines = "<br>".join(escape(line.strip()) for line in text.splitlines() if line.strip())
        return f"<p>{escaped_lines}</p>" if escaped_lines else "<p>No ROI context available.</p>"

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

    def _native_pipeline_id(self) -> PipelineId:
        """Return the manifest-locked native pipeline mode."""

        return (
            PipelineId.MULTI
            if bool(getattr(self, "_project_is_multi_group", False))
            else PipelineId.SINGLE
        )

    def _native_mode_value(self) -> str:
        return "multi" if self._native_pipeline_id() is PipelineId.MULTI else "single"

    def _combo_value(self, name: str, default: str) -> str:
        combo = getattr(self, name, None)
        if combo is None:
            return default
        current_data = getattr(combo, "currentData", None)
        value = current_data() if callable(current_data) else None
        if value is None:
            current_text = getattr(combo, "currentText", None)
            value = current_text() if callable(current_text) else None
        normalized = str(value or "").strip()
        return normalized or default

    def _checkbox_value(self, name: str, default: bool) -> bool:
        checkbox = getattr(self, name, None)
        checked = getattr(checkbox, "isChecked", None)
        return bool(checked()) if callable(checked) else bool(default)

    def _spin_value(self, name: str, default: int) -> int:
        control = getattr(self, name, None)
        value = getattr(control, "value", None)
        return int(value()) if callable(value) else int(default)

    def _initialize_native_analysis_controls(self) -> None:
        """Initialize mode-aware labels and defensively wire state refreshes."""

        for name, signal_name, callback in (
            (
                "dv_policy_combo",
                "currentTextChanged",
                self._sync_provenance_warning,
            ),
            (
                "group_pair_combo",
                "currentIndexChanged",
                self._refresh_analysis_design_summary,
            ),
        ):
            control = getattr(self, name, None)
            signal = getattr(control, signal_name, None)
            connect = getattr(signal, "connect", None)
            if callable(connect):
                connect(callback)
        self._populate_group_pair_combo()
        self._sync_analysis_mode_ui()
        self._sync_analysis_scope_ui()
        self._sync_analysis_profile_summary()
        self._sync_provenance_warning()
        self._refresh_analysis_design_summary()

    def _sync_analysis_mode_ui(self, *_args) -> None:
        """Update the locked project mode without offering a pooled override."""

        is_multi = self._native_pipeline_id() is PipelineId.MULTI
        mode_text = "Multi-Group" if is_multi else "Single Group"
        mode_value = getattr(self, "analysis_mode_value", None)
        if mode_value is not None:
            mode_value.setText(mode_text)
            mode_value.setToolTip(
                "Analysis mode is determined by canonical project metadata."
            )
        primary = getattr(self, "analyze_single_btn", None)
        if primary is not None:
            primary.setText("Run Standard Screening")
            primary.setToolTip(
                "Run the standard first-round FPVS screen for this "
                f"{'multi-group' if is_multi else 'single-group'} project. "
                "It tests positive responses and LMM response patterns; use a "
                "study-specific custom model for final confirmatory inference."
            )
        advanced = getattr(self, "single_advanced_btn", None)
        if advanced is not None:
            advanced.setToolTip(
                "Open actions appropriate to the active project analysis mode."
            )
        for name in ("group_pair_combo", "group_pair_label"):
            widget = getattr(self, name, None)
            set_visible = getattr(widget, "setVisible", None)
            if callable(set_visible):
                set_visible(is_multi)

    def _available_case_scope_selected(self) -> bool:
        """Return whether the user selected likelihood-based available cases."""

        return (
            self._combo_value("analysis_scope_combo", "available_case")
            == "available_case"
        )

    def _sync_analysis_scope_ui(self, *_args) -> None:
        """Keep scope-dependent controls and coverage language consistent."""

        available_case = self._available_case_scope_selected()
        was_available_case = bool(
            getattr(self, "_available_case_scope_active", False)
        )
        resampling = getattr(self, "resampling_sensitivity_checkbox", None)
        if resampling is not None:
            if available_case:
                if not was_available_case:
                    self._complete_core_resampling_checked = bool(
                        resampling.isChecked()
                    )
                resampling.setChecked(False)
                resampling.setEnabled(False)
                resampling.setToolTip(
                    "Max-|t| resampling requires complete participant-by-cell "
                    "coverage, so it is suppressed for the available-case LMM."
                )
            else:
                resampling.setEnabled(True)
                if was_available_case:
                    resampling.setChecked(
                        bool(
                            getattr(
                                self,
                                "_complete_core_resampling_checked",
                                True,
                            )
                        )
                    )
                resampling.setToolTip(
                    "Run the participant-level max-|t| resampling sensitivity. "
                    "This requires complete participant-by-cell coverage."
                )
        resample_count = getattr(self, "resample_count_spin", None)
        if resample_count is not None:
            resample_count.setEnabled(not available_case)
            resample_count.setToolTip(
                (
                    "Max-|t| resampling is unavailable for the available-case "
                    "LMM."
                )
                if available_case
                else (
                    "Requested Monte Carlo draws when exact participant-level "
                    "enumeration is not feasible."
                )
            )
        self._available_case_scope_active = available_case
        self._refresh_analysis_design_summary()

    def _block_complete_core_only_action(self, action_label: str) -> bool:
        """Block balanced/paired actions when available-case LMM is selected."""

        if not self._available_case_scope_selected():
            return False
        message = (
            f"{action_label} requires complete participant-by-condition coverage. "
            "Standard screening fits the primary LMM first and runs ANOVA "
            "compatibility automatically only when the declared grid is balanced."
        )
        self._set_status(message)
        self.append_log("Single", message, level="warning")
        return True

    def _sync_analysis_profile_summary(self, *_args) -> None:
        profile_label = getattr(self, "analysis_profile_value", None)
        if profile_label is not None:
            profile_label.setText("Standard FPVS Screening")
            profile_label.setToolTip(
                "A transparent first-round screen. Use a study-specific custom "
                "model for final confirmatory inference."
            )
        self._sync_provenance_warning()

    def _native_harmonic_provenance(self) -> str:
        if (
            getattr(self, "_dv_policy_name", GROUP_SIGNIFICANT_POLICY_NAME)
            == GROUP_SIGNIFICANT_POLICY_NAME
        ):
            return "same_sample_adaptive"
        if self._checkbox_value("independent_selection_attestation", False):
            return "independently_selected"
        return "user_fixed_unverified"

    def _sync_provenance_warning(self, *_args) -> None:
        """Keep fixed-list provenance controls consistent with the DV policy."""

        attestation = getattr(self, "independent_selection_attestation", None)
        fixed_policy = (
            getattr(self, "_dv_policy_name", GROUP_SIGNIFICANT_POLICY_NAME)
            == FIXED_PREDEFINED_POLICY_NAME
        )
        if attestation is not None:
            if not fixed_policy and attestation.isChecked():
                was_blocked = attestation.blockSignals(True)
                try:
                    attestation.setChecked(False)
                finally:
                    attestation.blockSignals(was_blocked)
            attestation.setEnabled(fixed_policy)

    def _apply_scanned_group_state(
        self,
        participant_group_ids: Mapping[object, object] | None,
    ) -> None:
        state = build_native_group_state(
            self.subjects,
            participant_group_ids,
            self._participants_map,
        )
        self._participant_group_id_map = dict(
            state.participant_group_id_map
        )
        self._subject_group_map = dict(state.subject_group_display_map)
        self._group_display_labels = dict(state.group_display_labels)
        self._group_participant_counts = dict(
            state.group_participant_counts
        )
        self._unassigned_group_participants = tuple(
            state.unassigned_participants
        )

    def _group_pair_label_text(self, group_id: str) -> str:
        display = self._group_display_labels.get(group_id, group_id)
        return (
            group_id
            if display.casefold() == group_id.casefold()
            else f"{display} [{group_id}]"
        )

    def _populate_group_pair_combo(self) -> None:
        combo = getattr(self, "group_pair_combo", None)
        if combo is None:
            return
        was_blocked = combo.blockSignals(True)
        try:
            combo.clear()
            pairs = canonical_group_pairs(
                tuple(self._group_participant_counts)
            )
            is_multi = self._native_pipeline_id() is PipelineId.MULTI
            if not is_multi:
                combo.addItem("Not applicable to a single-group project", None)
                combo.setEnabled(False)
                return
            if len(self._group_participant_counts) != 2 or len(pairs) != 1:
                combo.addItem(
                    "Standard screening requires exactly two canonical groups",
                    None,
                )
                combo.setEnabled(False)
                return
            pair = pairs[0]
            left, right = pair
            combo.addItem(
                (
                    f"{self._group_pair_label_text(left)} vs "
                    f"{self._group_pair_label_text(right)}"
                ),
                pair,
            )
            combo.setCurrentIndex(combo.findData(pair))
            combo.setEnabled(False)
        finally:
            combo.blockSignals(was_blocked)

    def _selected_group_pair(self) -> tuple[str, str] | None:
        combo = getattr(self, "group_pair_combo", None)
        if combo is not None:
            value = combo.currentData()
            if isinstance(value, (tuple, list)) and len(value) == 2:
                return str(value[0]), str(value[1])
        pairs = canonical_group_pairs(tuple(self._group_participant_counts))
        return pairs[0] if len(pairs) == 1 else None

    def _group_summary_text(self) -> str:
        if self._native_pipeline_id() is PipelineId.SINGLE:
            return f"Combined cohort: N={len(self.subjects)} scanned participants"
        if not self._group_participant_counts:
            return "No canonical project groups were resolved."
        pieces = [
            (
                f"{self._group_pair_label_text(group_id)}: "
                f"N={self._group_participant_counts[group_id]}"
            )
            for group_id in self._group_participant_counts
        ]
        if self._unassigned_group_participants:
            pieces.append(
                "Unassigned: "
                f"N={len(self._unassigned_group_participants)} "
                f"({', '.join(self._unassigned_group_participants)})"
            )
        return "; ".join(pieces)

    def update_analysis_design_summary(
        self,
        *,
        mode_text: str,
        profile_text: str,
        group_text: str,
        coverage_text: str,
    ) -> None:
        """Update mode/design labels without assuming the widgets exist."""

        for name, text in (
            ("analysis_mode_value", mode_text),
            ("analysis_profile_value", profile_text),
            ("analysis_group_value", group_text),
            ("analysis_coverage_value", coverage_text),
        ):
            label = getattr(self, name, None)
            if label is not None:
                label.setText(text)
                label.setToolTip(text)

    def _refresh_analysis_design_summary(self, *_args) -> None:
        selected_conditions = self._get_selected_conditions()
        self._preliminary_coverage = build_preliminary_workbook_coverage(
            self.subjects,
            selected_conditions,
            self.subject_data,
        )
        self.update_analysis_design_summary(
            mode_text=(
                "Multi-Group"
                if self._native_pipeline_id() is PipelineId.MULTI
                else "Single Group"
            ),
            profile_text="Standard FPVS Screening",
            group_text=self._group_summary_text(),
            coverage_text=format_preliminary_workbook_coverage(
                self._preliminary_coverage,
                analysis_scope="available_case",
            ),
        )
        self._sync_provenance_warning()

    def _native_analysis_state_snapshot(self) -> dict[str, object]:
        """Return plain state for prepared-analysis/pipeline configuration."""

        self._refresh_analysis_design_summary()
        return {
            "pipeline_id": self._native_pipeline_id(),
            "mode": self._native_mode_value(),
            "analysis_profile": "published_style_exploratory",
            "correction": "holm",
            "response_alternative": "greater",
            "analysis_scope": "available_case",
            "strict_omnibus_family": True,
            "harmonic_provenance": self._native_harmonic_provenance(),
            "independent_selection_attested": self._checkbox_value(
                "independent_selection_attestation",
                False,
            ),
            "canonical_group_ids": dict(self._participant_group_id_map),
            "participant_display_labels": dict(self._subject_group_map),
            "group_display_labels": dict(self._group_display_labels),
            "group_participant_counts": dict(
                self._group_participant_counts
            ),
            "unassigned_group_participants": list(
                self._unassigned_group_participants
            ),
            "selected_group_pair": self._selected_group_pair(),
            "selected_conditions": list(self._get_selected_conditions()),
            "preliminary_coverage": self._preliminary_coverage.to_dict(),
            "sensitivity": {
                "run_robust": self._checkbox_value(
                    "robust_sensitivity_checkbox",
                    True,
                ),
                "run_resampling": self._checkbox_value(
                    "resampling_sensitivity_checkbox",
                    True,
                ),
                "run_stability": self._checkbox_value(
                    "stability_sensitivity_checkbox",
                    True,
                ),
                "n_resamples": self._spin_value(
                    "resample_count_spin",
                    9_999,
                ),
            },
        }

    def _single_group_disabled_message(self) -> str:
        return (
            "This individual action belongs to the single-group pipeline. "
            "Use Run Standard Screening for this multi-group project."
        )

    def _is_single_group_analysis_disabled(self) -> bool:
        return bool(getattr(self, "_project_is_multi_group", False))

    def _update_single_group_analysis_availability(self, *, running: bool = False) -> None:
        """Keep the primary action enabled for the manifest-locked mode."""

        self._sync_analysis_mode_ui()
        for name in ("analyze_single_btn", "single_advanced_btn"):
            button = getattr(self, name, None)
            if button is None:
                continue
            button.setEnabled(not running)

    def _block_single_group_analysis_if_needed(self) -> bool:
        if not self._is_single_group_analysis_disabled():
            return False
        message = self._single_group_disabled_message()
        self._set_status(message)
        self.append_log("Single", message, level="warning")
        return True

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
            open_path_in_file_manager(path)
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
        text = str(txt or "")
        if self._is_roi_context_message(text):
            self._set_roi_status(txt)
        else:
            self._set_status(txt)

    def _is_roi_context_message(self, txt: str) -> bool:
        """Return True only for messages that describe active ROI settings."""
        normalized = " ".join(str(txt or "").lower().split())
        return (
            normalized.startswith("no rois defined")
            or normalized.startswith("rois loaded")
            or normalized.startswith("roi definitions")
            or (
                normalized.startswith("using ")
                and " roi" in normalized
                and "from settings" in normalized
            )
        )

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
        self._refresh_analysis_design_summary()

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
        """Compatibility slot for the now mode-aware primary action."""

        self._on_primary_analysis_clicked()

    def _on_primary_analysis_clicked(self) -> None:
        """Run the manifest-locked native single- or multi-group pipeline."""

        self._refresh_analysis_design_summary()
        if self._native_pipeline_id() is PipelineId.MULTI:
            if self._unassigned_group_participants:
                message = (
                    "Canonical group assignment is missing for: "
                    + ", ".join(self._unassigned_group_participants)
                )
                self._set_status(message)
                self.append_log("Multi-group", message, level="warning")
                return
            pairs = canonical_group_pairs(tuple(self._group_participant_counts))
            selected_pair = self._selected_group_pair()
            if len(self._group_participant_counts) != 2 or len(pairs) != 1:
                message = (
                    "Standard multi-group screening requires exactly two "
                    "canonical project groups. Use a study-specific custom "
                    "model for projects with a different group structure."
                )
                self._set_status(message)
                self.append_log("Multi-group", message, level="warning")
                return
            if selected_pair is None:
                message = (
                    "The two canonical screening groups could not be resolved. "
                    "Review project participant metadata, then re-scan."
                )
                self._set_status(message)
                self.append_log("Multi-group", message, level="warning")
                return
        self._clear_native_analysis_results()
        runner = getattr(self, "run_primary_analysis", None)
        if callable(runner):
            runner()
            return
        if self._native_pipeline_id() is PipelineId.MULTI:
            self._controller.run_multigroup_analysis()
        else:
            self._controller.run_single_group_analysis()

    def _on_cancel_analysis_clicked(self) -> None:
        """Delegate cancellation to the pipeline/controller implementation."""

        handler = getattr(self, "on_cancel_analysis_clicked", None)
        if callable(handler):
            handler()
            return
        controller = getattr(self, "_controller", None)
        cancel = getattr(controller, "cancel_pipeline", None)
        if callable(cancel):
            cancel(self._native_pipeline_id())

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
            elif "diagnostic only" in text.casefold():
                btn.setToolTip(
                    "Advanced diagnostic route only; this is not a replacement "
                    "for the full Standard FPVS Screening report."
                )
            btn.clicked.connect(cb)
            layout.addWidget(btn)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def on_single_advanced_clicked(self) -> None:
        """Open individual actions appropriate to the locked project mode."""

        if self._native_pipeline_id() is PipelineId.MULTI:
            self._open_advanced_dialog(
                "Standard FPVS Screening - Advanced",
                [
                    (
                        "Run Standard Screening",
                        self._on_primary_analysis_clicked,
                        True,
                    ),
                ],
            )
            return
        if self._block_single_group_analysis_if_needed():
            return
        actions = [
            (
                "Run Standard Screening",
                self._on_primary_analysis_clicked,
                True,
            ),
            ("Run LMM Diagnostic Only", self.on_run_mixed_model, True),
            (
                "Export ANOVA Compatibility",
                self.on_export_rm_anova,
                isinstance(self.rm_anova_results_data, pd.DataFrame) and not self.rm_anova_results_data.empty,
            ),
            (
                "Export LMM Diagnostic",
                self.on_export_mixed_model,
                isinstance(self.mixed_model_results_data, pd.DataFrame) and not self.mixed_model_results_data.empty,
            ),
        ]
        self._open_advanced_dialog(
            "Standard FPVS Screening - Advanced",
            actions,
        )

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
        if self._block_single_group_analysis_if_needed():
            return
        if self._block_complete_core_only_action("RM-ANOVA"):
            return
        self._clear_output_views()
        self.rm_anova_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_rm_anova_only()

    def on_run_mixed_model(self) -> None:
        """Handle the on run mixed model step for the Stats workflow."""
        if self._block_single_group_analysis_if_needed():
            return
        self._clear_output_views()
        self.mixed_model_results_data = None
        self._update_export_buttons()
        self._controller.run_single_group_mixed_model_only()

    def on_run_interaction_posthocs(self) -> None:
        """Handle the on run interaction posthocs step for the Stats workflow."""
        if self._block_single_group_analysis_if_needed():
            return
        if self._block_complete_core_only_action(
            "Interaction/post-hoc testing"
        ):
            return
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
                if scan_result.project_root is not None:
                    project_changed = (
                        Path(self._project_path).resolve()
                        != Path(scan_result.project_root).resolve()
                    )
                    if project_changed:
                        self.rebind_project_context(scan_result.project_root)
                    else:
                        self._invalidate_controller_context()
                        self._clear_native_analysis_results()
                    self._set_data_folder_path(folder)
                else:
                    self._invalidate_controller_context()
                    self._clear_native_analysis_results()
                self.subjects = scan_result.subjects
                self.conditions = scan_result.conditions
                self._populate_conditions_panel(self.conditions)
                self.subject_data = scan_result.subject_data
                self._participants_map = dict(scan_result.participants_map)
                self._project_is_multi_group = bool(scan_result.project_is_multi_group)
                self._apply_scanned_group_state(
                    scan_result.participant_group_ids,
                )
                self._populate_group_pair_combo()
                self._sync_analysis_mode_ui()
                self._update_single_group_analysis_availability()
                self._reconcile_manual_exclusions(self.subjects)
                self._refresh_analysis_design_summary()
                self._set_status(
                    "Scan complete: Found "
                    f"{len(scan_result.subjects)} subjects and "
                    f"{len(scan_result.conditions)} conditions. "
                    + (
                        "Review the preliminary complete-core coverage before "
                        "analysis."
                    )
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

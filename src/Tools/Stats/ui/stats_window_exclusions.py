"""DV policy, outlier, and manual exclusion helpers for StatsWindow."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowExclusionsMixin:
    def _get_dv_policy_payload(self) -> dict[str, object]:
        """Handle the get dv policy payload step for the Stats workflow."""
        _ok, oddball_freq = self._safe_settings_get("analysis", "oddball_freq", 1.2)
        return {
            "name": self._dv_policy_name,
            "fixed_harmonic_frequencies_hz": str(self._dv_fixed_harmonic_frequencies_hz),
            "fixed_harmonic_auto_exclude_base": bool(
                self._dv_fixed_harmonic_auto_exclude_base
            ),
            "oddball_frequency_hz": oddball_freq,
        }

    def get_dv_policy_snapshot(self) -> dict[str, object]:
        """Handle the get dv policy snapshot step for the Stats workflow."""
        return dict(self._get_dv_policy_payload())

    def _get_outlier_exclusion_payload(self) -> dict[str, object]:
        """Handle the get outlier exclusion payload step for the Stats workflow."""
        return {
            "enabled": True,
            "abs_limit": float(self._outlier_abs_limit),
        }

    def _get_qc_exclusion_payload(self) -> dict[str, object]:
        """Handle the get qc exclusion payload step for the Stats workflow."""
        return {
            "warn_threshold": float(self._qc_threshold_sumabs),
            "critical_threshold": float(self._qc_threshold_maxabs),
            "warn_abs_floor_sumabs": QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
            "critical_abs_floor_sumabs": QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
            "warn_abs_floor_maxabs": QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
            "critical_abs_floor_maxabs": QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
        }

    def _on_outlier_exclusion_toggled(self, state: int) -> None:
        """Handle the on outlier exclusion toggled step for the Stats workflow."""
        self._outlier_exclusion_enabled = True
        spinbox = getattr(self, "outlier_abs_limit_spin", None)
        if spinbox is not None:
            spinbox.setEnabled(True)

    def _on_outlier_abs_limit_changed(self, value: float) -> None:
        """Handle the on outlier abs limit changed step for the Stats workflow."""
        self._outlier_abs_limit = float(value)

    def _current_flagged_pid_map(self) -> dict[str, list[str]]:
        """Handle the current flagged pid map step for the Stats workflow."""
        report = None
        if self._active_pipeline is not None:
            report = self._pipeline_run_reports.get(self._active_pipeline)
        if report is None:
            for item in self._pipeline_run_reports.values():
                if item is not None:
                    report = item
                    break
        if report is None:
            return {}
        return collect_flagged_pid_map(report.qc_report, report.dv_report)

    def _current_flagged_details_map(self) -> dict[str, str]:
        """Handle the current flagged details map step for the Stats workflow."""
        report = None
        if self._active_pipeline is not None:
            report = self._pipeline_run_reports.get(self._active_pipeline)
        if report is None:
            for item in self._pipeline_run_reports.values():
                if item is not None:
                    report = item
                    break
        if report is None:
            return {}
        return build_flagged_details_map(report.qc_report, report.dv_report)

    def _update_manual_exclusion_summary_labels(self) -> None:
        """Update the inline manual exclusion summary text."""
        excluded = sorted(self.manual_excluded_pids)
        self.manual_excluded_pids = set(excluded)
        summary_label = getattr(self, "manual_exclusion_summary_label", None)
        if summary_label is not None:
            summary_label.setText(f"Excluded: {len(excluded)}")
        list_widget = getattr(self, "manual_exclusion_list", None)
        if list_widget is not None:
            if not excluded:
                display_text = "None"
                tooltip_text = "None"
            elif len(excluded) <= 3:
                display_text = ", ".join(excluded)
                tooltip_text = display_text
            else:
                display_text = ", ".join(excluded[:3]) + f" (+{len(excluded) - 3})"
                tooltip_text = ", ".join(excluded)
            list_widget.set_full_text(display_text)
            list_widget.setToolTip(tooltip_text)
        clear_btn = getattr(self, "manual_exclusion_clear_btn", None)
        if clear_btn is not None:
            clear_btn.setEnabled(bool(excluded))

    def _update_manual_exclusion_summary(self) -> None:
        """Handle the update manual exclusion summary step for the Stats workflow."""
        self._update_manual_exclusion_summary_labels()
        self._sync_manual_exclusion_candidates_list()

    def _sync_manual_exclusion_candidates_list(self) -> None:
        """Refresh the inline manual exclusion participant checklist."""
        list_widget = getattr(self, "manual_exclusion_candidates_list", None)
        if list_widget is None:
            return
        search_input = getattr(self, "manual_exclusion_search_input", None)
        filter_text = search_input.text() if search_input is not None else ""
        candidates = list(getattr(self, "_manual_exclusion_candidates", []))
        flagged_map = self._current_flagged_pid_map()
        flagged_details_map = self._current_flagged_details_map()
        self._updating_manual_exclusion_list = True
        try:
            list_widget.clear()
            if not candidates:
                item = QListWidgetItem("Load a data folder to list participants.")
                item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                list_widget.addItem(item)
            for pid in candidates:
                flags = flagged_map.get(pid, [])
                label_flags = [outlier_reason_label(flag) for flag in flags]
                suffix = f" (FLAGGED: {', '.join(label_flags)})" if label_flags else ""
                item = QListWidgetItem(f"{pid}{suffix}")
                item.setData(Qt.UserRole, pid)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if pid in self.manual_excluded_pids else Qt.Unchecked)
                tooltip = flagged_details_map.get(pid)
                if tooltip:
                    item.setToolTip(tooltip)
                list_widget.addItem(item)
        finally:
            self._updating_manual_exclusion_list = False
        self._filter_manual_exclusion_candidates(filter_text)
        select_all_btn = getattr(self, "manual_exclusion_select_all_btn", None)
        if select_all_btn is not None:
            select_all_btn.setEnabled(bool(candidates))
        search_input = getattr(self, "manual_exclusion_search_input", None)
        if search_input is not None:
            search_input.setEnabled(bool(candidates))
        self._update_manual_exclusion_summary_labels()

    def _filter_manual_exclusion_candidates(self, text: str) -> None:
        """Filter the inline manual exclusion checklist."""
        list_widget = getattr(self, "manual_exclusion_candidates_list", None)
        if list_widget is None:
            return
        filter_text = text.strip().lower()
        for idx in range(list_widget.count()):
            item = list_widget.item(idx)
            pid = item.data(Qt.UserRole)
            if pid is None:
                item.setHidden(False)
                continue
            item_text = item.text().lower()
            item.setHidden(bool(filter_text) and filter_text not in item_text)

    def _on_manual_exclusion_item_changed(self, item: QListWidgetItem) -> None:
        """Update manual exclusions from the inline checklist."""
        if getattr(self, "_updating_manual_exclusion_list", False):
            return
        pid = item.data(Qt.UserRole)
        if pid is None:
            return
        pid_text = str(pid)
        if item.checkState() == Qt.Checked:
            self.manual_excluded_pids.add(pid_text)
        else:
            self.manual_excluded_pids.discard(pid_text)
        self._update_manual_exclusion_summary_labels()

    def _select_all_manual_exclusions(self) -> None:
        """Mark every listed participant as manually excluded."""
        self.manual_excluded_pids = set(self._manual_exclusion_candidates)
        self._update_manual_exclusion_summary()

    def _reconcile_manual_exclusions(self, candidates: list[str]) -> None:
        """Handle the reconcile manual exclusions step for the Stats workflow."""
        self._manual_exclusion_candidates = list(candidates)
        self.manual_excluded_pids = {
            pid for pid in self.manual_excluded_pids if pid in self._manual_exclusion_candidates
        }
        self._update_manual_exclusion_summary()

    def _clear_manual_exclusions(self) -> None:
        """Handle the clear manual exclusions step for the Stats workflow."""
        self.manual_excluded_pids.clear()
        self._update_manual_exclusion_summary()

    def _open_manual_exclusion_dialog(self) -> None:
        """Show the inline manual exclusions section without opening a modal."""
        tabs = getattr(self, "setup_tabs", None)
        if tabs is not None:
            tabs.setCurrentIndex(0)
        search_input = getattr(self, "manual_exclusion_search_input", None)
        if search_input is not None:
            search_input.setFocus()

    def _set_fixed_predefined_controls_visible(self, visible: bool) -> None:
        widget = getattr(self, "fixed_predefined_controls", None)
        if widget is not None:
            widget.setVisible(visible)
        note = getattr(self, "group_significant_note", None)
        if note is not None:
            note.setVisible(not visible)

    def _clear_fixed_predefined_preview(self) -> None:
        table = getattr(self, "fixed_predefined_preview_table", None)
        if table is not None:
            table.setRowCount(0)

    def _update_fixed_predefined_preview_table(self, payload: dict[str, object]) -> None:
        table = getattr(self, "fixed_predefined_preview_table", None)
        if table is None:
            return
        rows = payload.get("selection_rows", []) if isinstance(payload, dict) else []
        if not isinstance(rows, list):
            rows = []
        table.setRowCount(len(rows))
        for row_idx, row_data in enumerate(rows):
            row = row_data if isinstance(row_data, dict) else {}
            values = [
                row.get("requested_frequency_hz", ""),
                row.get("matched_frequency_hz", ""),
                row.get("matched_column", ""),
                row.get("matched_bin_index", ""),
                "Yes" if row.get("included") else "No",
                row.get("exclusion_reason") or row.get("warning") or "Included",
            ]
            for col_idx, value in enumerate(values):
                if isinstance(value, float):
                    text = f"{value:g}"
                else:
                    text = "" if value is None else str(value)
                table.setItem(row_idx, col_idx, QTableWidgetItem(text))
        table.resizeColumnsToContents()

    def _on_preview_fixed_predefined_clicked(self) -> None:
        if not self.subject_data:
            self._set_status("Load project data before validating the harmonic list.")
            return
        got = self._get_analysis_settings()
        if not got:
            return
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_predefined_base_freq_label()

        self.fixed_predefined_preview_btn.setEnabled(False)
        self._set_status("Validating fixed harmonic list...")

        worker = StatsWorker(
            stats_worker_funcs.run_harmonics_preview,
            subjects=self.subjects,
            conditions=self._get_selected_conditions(),
            conditions_all=list(self.conditions),
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
            dv_policy=self._get_dv_policy_payload(),
            _op=f"{self._dv_policy_name} Preview",
        )

        try:
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(worker)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to track fixed-list preview worker")

        def _release():
            try:
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to release fixed-list preview worker")

        def _on_finished(payload: dict) -> None:
            try:
                self._update_fixed_predefined_preview_table(payload or {})
                included = payload.get("fixed_harmonic_included_frequencies_hz", [])
                count = len(included) if isinstance(included, list) else 0
                self._set_status(f"Fixed harmonic list validated: {count} included.")
            finally:
                self.fixed_predefined_preview_btn.setEnabled(True)
                _release()

        def _on_error(message: str) -> None:
            try:
                self.append_log("General", f"Fixed harmonic list error: {message}", level="error")
                self._set_status(message)
            finally:
                self.fixed_predefined_preview_btn.setEnabled(True)
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _update_fixed_predefined_base_freq_label(self) -> None:
        """Update the base-frequency label used by the fixed predefined policy."""
        fixed_label = getattr(self, "fixed_predefined_base_freq_value", None)
        if fixed_label is not None:
            fixed_label.setText(f"{self._current_base_freq:g} Hz")

    def _on_dv_policy_changed(self, text: str) -> None:
        """Handle the on dv policy changed step for the Stats workflow."""
        self._dv_policy_name = (
            GROUP_SIGNIFICANT_POLICY_NAME
            if text == GROUP_SIGNIFICANT_POLICY_NAME
            else FIXED_PREDEFINED_POLICY_NAME
        )
        self._set_fixed_predefined_controls_visible(
            self._dv_policy_name == FIXED_PREDEFINED_POLICY_NAME
        )
        self._clear_fixed_predefined_preview()

    def _on_fixed_predefined_freqs_changed(self, text: str) -> None:
        self._dv_fixed_harmonic_frequencies_hz = text
        self._clear_fixed_predefined_preview()

    def _on_fixed_predefined_exclude_base_changed(self, state: int) -> None:
        self._dv_fixed_harmonic_auto_exclude_base = state == Qt.Checked
        self._clear_fixed_predefined_preview()

    def _show_outlier_exclusion_dialog(self, pipeline_id: PipelineId) -> None:
        """Handle the show outlier exclusion dialog step for the Stats workflow."""
        dialog = self._build_flagged_participants_dialog(pipeline_id)
        if dialog is None:
            return
        dialog.exec()

    def _build_flagged_participants_dialog(self, pipeline_id: PipelineId) -> QDialog | None:
        """Handle the build flagged participants dialog step for the Stats workflow."""
        report = self._pipeline_run_reports.get(pipeline_id)
        if not isinstance(report, StatsRunReport):
            return None

        qc_report = report.qc_report
        dv_report = report.dv_report
        summary_df, details_df = build_flagged_participants_tables(qc_report, dv_report)
        dv_meta = self._pipeline_dv_metadata.get(pipeline_id, {})
        dv_display_name = dv_meta.get("dv_display_name") if isinstance(dv_meta, dict) else None
        dv_unit = dv_meta.get("dv_unit") if isinstance(dv_meta, dict) else None

        dialog = QDialog(self)
        dialog.setWindowTitle("Flagged Participants Report")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)

        flag_count_definition = (
            "Flag count = number of individual condition×ROI QC checks "
            "(and/or DV cells) that triggered for this participant."
        )
        summary_lines = [
            "QC scanned all conditions/ROIs in the project, independent of selections.",
            "Flagged Participants Summary",
            flag_count_definition,
            f"Manual exclusions: {len(self.manual_excluded_pids)}",
            f"Required exclusions (non-finite DV): {len(report.required_exclusions)}",
            f"QC flagged: {qc_report.summary.n_subjects_flagged if qc_report else 0}",
            f"DV flagged: {dv_report.summary.n_subjects_flagged if dv_report else 0}",
        ]
        if summary_df.empty:
            summary_lines.append("No participants were flagged.")
        summary_text = "\n".join(summary_lines)

        summary_box = QTextEdit()
        summary_box.setReadOnly(True)
        summary_box.setPlainText(summary_text)
        summary_box.setMinimumHeight(160)
        summary_box.setToolTip(
            "Summary of QC/DV flags and manual/required exclusions."
        )
        layout.addWidget(summary_box)

        display_rows: list[dict[str, object]] = []
        details_map: dict[str, str] = {}
        table: QTableWidget | None = None
        if not summary_df.empty:
            table = QTableWidget(summary_df.shape[0], 7)
            table.setHorizontalHeaderLabels(
                [
                    "Participant",
                    "Flag types",
                    "Flag count",
                    "Worst value",
                    "Condition",
                    "ROI",
                    "Explanation",
                ]
            )
            header = table.horizontalHeader()
            for idx in range(6):
                header.setSectionResizeMode(idx, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(6, QHeaderView.Stretch)
            header.setStretchLastSection(True)
            flag_count_header = table.horizontalHeaderItem(2)
            if flag_count_header is not None:
                flag_count_header.setToolTip(flag_count_definition)

            table.verticalHeader().setVisible(False)
            table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            table.setSelectionMode(QAbstractItemView.SingleSelection)
            table.setSelectionBehavior(QAbstractItemView.SelectRows)
            table.setWordWrap(False)
            table.setTextElideMode(Qt.ElideRight)
            table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            row_height = int(table.fontMetrics().height() * 1.6)
            table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
            table.verticalHeader().setDefaultSectionSize(row_height)

            details_map = {
                str(pid): "\n".join(
                    [
                        f"Flag types: {format_flag_types_display(group['flag_type'].tolist())}",
                        "",
                        "Violations:",
                        *[
                            f"- {format_flag_types_display([str(row['flag_type'])])}: "
                            f"{row['reason_text']}"
                            for _, row in group.iterrows()
                        ],
                    ]
                )
                for pid, group in details_df.groupby("participant_id", sort=True)
            }

            for row, (_, item) in enumerate(summary_df.iterrows()):
                participant_id = str(item["participant_id"])
                raw_flag_types = [flag.strip() for flag in str(item["flag_types"]).split(",") if flag]
                flag_types_display = format_flag_types_display(raw_flag_types)
                group = details_df[details_df["participant_id"] == participant_id]
                worst_flag_type = raw_flag_types[0] if raw_flag_types else None
                severity = "FLAG"
                if not group.empty:
                    match = group[
                        (group["condition"] == item["worst_condition"])
                        & (group["roi"] == item["worst_roi"])
                        & (group["metric_value"] == item["worst_value"])
                    ]
                    if match.empty:
                        match = group
                    worst_flag_type = str(match.iloc[0]["flag_type"])
                    severity = str(match.iloc[0]["severity"])

                worst_value = item["worst_value"]
                worst_value_float = float(worst_value) if pd.notna(worst_value) else float("nan")
                worst_text, worst_tooltip = format_worst_value_display(
                    worst_flag_type,
                    worst_value_float,
                    dv_display_name=dv_display_name if isinstance(dv_display_name, str) else None,
                    dv_unit=dv_unit if isinstance(dv_unit, str) else None,
                )
                summary_text = build_flagged_participant_summary(
                    severity=severity,
                    flag_type=worst_flag_type,
                    worst_text=worst_text,
                    n_flags=int(item["n_flags"]),
                )
                details_text = details_map.get(participant_id, str(item["reason_text"]))
                row_items = [
                    QTableWidgetItem(participant_id),
                    QTableWidgetItem(flag_types_display),
                    QTableWidgetItem(str(item["n_flags"])),
                    QTableWidgetItem(worst_text),
                    QTableWidgetItem(str(item["worst_condition"])),
                    QTableWidgetItem(str(item["worst_roi"])),
                    QTableWidgetItem(summary_text),
                ]
                row_items[1].setToolTip(flag_types_display)
                if worst_tooltip:
                    row_items[3].setToolTip(worst_tooltip)
                if details_text:
                    row_items[6].setToolTip(details_text)
                for col, cell in enumerate(row_items):
                    table.setItem(row, col, cell)

                display_rows.append(
                    {
                        "Participant": participant_id,
                        "Flag types": flag_types_display,
                        "Flag count": int(item["n_flags"]),
                        "Worst value": worst_text,
                        "Condition": str(item["worst_condition"]),
                        "ROI": str(item["worst_roi"]),
                        "Explanation": summary_text,
                    }
                )

            layout.addWidget(table)

            details_panel = QTextEdit()
            details_panel.setReadOnly(True)
            details_panel.setPlaceholderText("Select a participant to view full details.")
            details_panel.setMinimumHeight(140)
            layout.addWidget(details_panel)

            def _update_details() -> None:
                """Handle the update details step for the Stats workflow."""
                current = table.currentRow()
                if current < 0:
                    details_panel.clear()
                    details_panel.setPlaceholderText("Select a participant to view full details.")
                    return
                pid_item = table.item(current, 0)
                if pid_item is None:
                    return
                pid = str(pid_item.text())
                details_panel.setPlainText(details_map.get(pid, ""))

            table.itemSelectionChanged.connect(_update_details)
        else:
            layout.addWidget(QLabel("No participants were flagged."))

        button_row = QHBoxLayout()
        copy_summary_btn = make_action_button("Copy summary")
        copy_btn = make_action_button("Copy table")
        copy_details_btn = make_action_button("Copy details")
        edit_manual_btn = make_action_button("Edit manual exclusions", variant="primary")
        close_btn = make_action_button("Close", variant="tertiary")
        button_row.addStretch(1)
        button_row.addWidget(copy_summary_btn)
        button_row.addWidget(copy_btn)
        button_row.addWidget(copy_details_btn)
        button_row.addWidget(edit_manual_btn)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        def _copy_summary() -> None:
            """Handle the copy summary step for the Stats workflow."""
            if summary_text:
                QGuiApplication.clipboard().setText(summary_text)

        def _copy_table() -> None:
            """Handle the copy table step for the Stats workflow."""
            if not display_rows:
                return
            display_df = pd.DataFrame(
                display_rows,
                columns=[
                    "Participant",
                    "Flag types",
                    "Flag count",
                    "Worst value",
                    "Condition",
                    "ROI",
                    "Explanation",
                ],
            )
            QGuiApplication.clipboard().setText(display_df.to_csv(sep="\t", index=False))

        def _copy_details() -> None:
            """Handle the copy details step for the Stats workflow."""
            if not details_map or table is None:
                return
            current = table.currentRow()
            if current < 0:
                return
            pid_item = table.item(current, 0)
            if pid_item is None:
                return
            pid = str(pid_item.text())
            details_text = details_map.get(pid, "")
            if details_text:
                QGuiApplication.clipboard().setText(details_text)

        copy_summary_btn.clicked.connect(_copy_summary)
        copy_btn.clicked.connect(_copy_table)
        copy_details_btn.clicked.connect(_copy_details)
        copy_btn.setEnabled(bool(display_rows))
        copy_details_btn.setEnabled(bool(display_rows))
        def _show_inline_manual_exclusions() -> None:
            """Close this report and focus the inline manual exclusions editor."""
            dialog.accept()
            self._open_manual_exclusion_dialog()

        edit_manual_btn.clicked.connect(_show_inline_manual_exclusions)
        close_btn.clicked.connect(dialog.accept)

        return dialog

"""DV policy, outlier, and manual exclusion helpers for StatsWindow."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowExclusionsMixin:
    def _get_dv_policy_payload(self) -> dict[str, object]:
        """Handle the get dv policy payload step for the Stats workflow."""
        return {
            "name": self._dv_policy_name,
            "fixed_k": int(self._dv_fixed_k),
            "exclude_harmonic1": bool(self._dv_exclude_harmonic1),
            "exclude_base_harmonics": bool(self._dv_exclude_base_harmonics),
            "z_threshold": float(self._dv_group_mean_z_threshold),
            "empty_list_policy": str(self._dv_empty_list_policy),
        }

    def get_dv_policy_snapshot(self) -> dict[str, object]:
        """Handle the get dv policy snapshot step for the Stats workflow."""
        return dict(self._get_dv_policy_payload())

    def _sync_selected_dv_variants(self) -> None:
        """Handle the sync selected dv variants step for the Stats workflow."""
        self._dv_variants_selected = [
            name
            for name, checkbox in self._dv_variant_checkboxes.items()
            if checkbox.isChecked()
        ]

    def _get_selected_dv_variants(self) -> List[str]:
        """Handle the get selected dv variants step for the Stats workflow."""
        if self._dv_variant_checkboxes:
            return list(self._dv_variants_selected)
        return []

    def _get_dv_variant_payloads(self) -> list[dict[str, object]]:
        """Handle the get dv variant payloads step for the Stats workflow."""
        selected = self._get_selected_dv_variants()
        if not selected:
            return []
        base_payload = self._get_dv_policy_payload()
        payloads = []
        for name in selected:
            variant_payload = dict(base_payload)
            variant_payload["name"] = name
            payloads.append(variant_payload)
        return payloads

    def get_dv_variants_snapshot(self) -> list[str]:
        """Handle the get dv variants snapshot step for the Stats workflow."""
        return list(self._get_selected_dv_variants())

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

    def _update_manual_exclusion_summary(self) -> None:
        """Handle the update manual exclusion summary step for the Stats workflow."""
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
        """Handle the open manual exclusion dialog step for the Stats workflow."""
        dialog = ManualOutlierExclusionDialog(
            candidates=self._manual_exclusion_candidates,
            flagged_map=self._current_flagged_pid_map(),
            flagged_details_map=self._current_flagged_details_map(),
            preselected=self.manual_excluded_pids,
            parent=self,
        )

        def _apply_changes(selections: set[str]) -> None:
            """Handle the apply changes step for the Stats workflow."""
            self.manual_excluded_pids = set(selections)
            self._update_manual_exclusion_summary()

        dialog.manualExclusionsApplied.connect(_apply_changes)
        dialog.exec()

    def _set_fixed_k_controls_enabled(self, enabled: bool) -> None:
        """Handle the set fixed k controls enabled step for the Stats workflow."""
        widgets = [
            getattr(self, "fixed_k_spinbox", None),
            getattr(self, "fixed_k_exclude_h1", None),
            getattr(self, "fixed_k_exclude_base", None),
            getattr(self, "fixed_k_base_freq_value", None),
        ]
        for widget in widgets:
            if widget is not None:
                widget.setEnabled(enabled)
        container = getattr(self, "fixed_k_controls", None)
        if container is not None:
            container.setVisible(enabled)

    def _set_group_mean_controls_visible(self, visible: bool) -> None:
        """Handle the set group mean controls visible step for the Stats workflow."""
        widget = getattr(self, "group_mean_controls", None)
        if widget is not None:
            widget.setVisible(visible)
        preview_button = getattr(self, "group_mean_preview_btn", None)
        if preview_button is not None:
            preview_button.setVisible(visible)
        preview_table = getattr(self, "group_mean_preview_table", None)
        if preview_table is not None:
            preview_table.setVisible(visible)

    def _on_group_mean_z_threshold_changed(self, value: float) -> None:
        """Handle the on group mean z threshold changed step for the Stats workflow."""
        self._dv_group_mean_z_threshold = float(value)

    def _on_empty_list_policy_changed(self, text: str) -> None:
        """Handle the on empty list policy changed step for the Stats workflow."""
        self._dv_empty_list_policy = text

    def _clear_group_mean_preview(self) -> None:
        """Handle the clear group mean preview step for the Stats workflow."""
        table = getattr(self, "group_mean_preview_table", None)
        if table is None:
            return
        table.setRowCount(0)
        self._group_mean_preview_data = {}

    def _update_group_mean_preview_table(
        self,
        union_map: dict[str, list[float]],
        fallback_info: dict[str, dict[str, object]],
        stop_metadata: dict[str, dict[str, object]] | None = None,
    ) -> None:
        """Handle the update group mean preview table step for the Stats workflow."""
        table = getattr(self, "group_mean_preview_table", None)
        if table is None:
            return
        stop_metadata = stop_metadata or {}
        rois = sorted(union_map.keys())
        table.setRowCount(len(rois))
        for row, roi_name in enumerate(rois):
            harmonics = union_map.get(roi_name, [])
            fallback = fallback_info.get(roi_name, {})
            fallback_used = bool(fallback.get("fallback_used"))
            policy = fallback.get("policy", "")
            if fallback_used:
                fallback_text = str(policy)
            elif policy == EMPTY_LIST_SET_ZERO and not harmonics:
                fallback_text = "DV=0"
            else:
                fallback_text = "None"

            harmonic_text = ", ".join(f"{freq:g}" for freq in harmonics) or "—"
            count_text = str(len(harmonics))
            stop_meta = stop_metadata.get(roi_name, {})
            stop_reason = stop_meta.get("stop_reason") or "—"
            stop_fail = ", ".join(
                f"{freq:g}" for freq in stop_meta.get("fail_harmonics", []) or []
            ) or "—"

            table.setItem(row, 0, QTableWidgetItem(str(roi_name)))
            table.setItem(row, 1, QTableWidgetItem(harmonic_text))
            table.setItem(row, 2, QTableWidgetItem(count_text))
            table.setItem(row, 3, QTableWidgetItem(fallback_text))
            table.setItem(row, 4, QTableWidgetItem(str(stop_reason)))
            table.setItem(row, 5, QTableWidgetItem(stop_fail))

        table.resizeColumnsToContents()

    def _on_preview_group_mean_z_clicked(self) -> None:
        """Handle the on preview group mean z clicked step for the Stats workflow."""
        if self._dv_policy_name != ROSSION_POLICY_NAME:
            return
        if not self.subject_data:
            self._set_status("Load project data before previewing harmonic sets.")
            return
        self.refresh_rois()
        if not self.rois:
            self._set_status("Define at least one ROI before previewing.")
            return
        got = self._get_analysis_settings()
        if not got:
            return
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_k_base_freq_label()

        self.group_mean_preview_btn.setEnabled(False)
        self._set_status("Previewing harmonic sets…")

        worker = StatsWorker(
            stats_worker_funcs.run_harmonics_preview,
            subjects=self.subjects,
            conditions=self._get_selected_conditions(),
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
            logger.exception("Failed to track preview worker")

        def _release():
            """Handle the release step for the Stats workflow."""
            try:
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to release preview worker")

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats workflow."""
            try:
                self._group_mean_preview_data = payload or {}
                union_map = payload.get("union_harmonics_by_roi", {}) if isinstance(payload, dict) else {}
                fallback_info = payload.get("fallback_info_by_roi", {}) if isinstance(payload, dict) else {}
                stop_meta = payload.get("stop_metadata_by_roi", {}) if isinstance(payload, dict) else {}
                self._update_group_mean_preview_table(union_map, fallback_info, stop_meta)
                self._set_status("Preview updated.")
            finally:
                self.group_mean_preview_btn.setEnabled(True)
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats workflow."""
            try:
                self.append_log("General", f"Preview error: {message}", level="error")
                self._set_status(message)
            finally:
                self.group_mean_preview_btn.setEnabled(True)
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _update_fixed_k_base_freq_label(self) -> None:
        """Handle the update fixed k base freq label step for the Stats workflow."""
        label = getattr(self, "fixed_k_base_freq_value", None)
        if label is None:
            return
        label.setText(f"{self._current_base_freq:g} Hz")

    def _on_dv_policy_changed(self, text: str) -> None:
        """Handle the on dv policy changed step for the Stats workflow."""
        self._dv_policy_name = text
        self._set_fixed_k_controls_enabled(text == FIXED_K_POLICY_NAME)
        self._set_group_mean_controls_visible(text == ROSSION_POLICY_NAME)
        if text != ROSSION_POLICY_NAME:
            self._clear_group_mean_preview()

    def _on_fixed_k_changed(self, value: int) -> None:
        """Handle the on fixed k changed step for the Stats workflow."""
        self._dv_fixed_k = int(value)

    def _on_fixed_k_exclude_h1_changed(self, state: int) -> None:
        """Handle the on fixed k exclude h1 changed step for the Stats workflow."""
        self._dv_exclude_harmonic1 = state == Qt.Checked

    def _on_fixed_k_exclude_base_changed(self, state: int) -> None:
        """Handle the on fixed k exclude base changed step for the Stats workflow."""
        self._dv_exclude_base_harmonics = state == Qt.Checked

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
        edit_manual_btn.clicked.connect(self._open_manual_exclusion_dialog)
        close_btn.clicked.connect(dialog.accept)

        return dialog

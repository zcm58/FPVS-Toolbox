"""DV policy, outlier, and manual exclusion helpers for StatsWindow."""
# ruff: noqa: F405

from __future__ import annotations

from Tools.Stats.analysis.canonical_harmonics import (
    CanonicalHarmonicSelectionError,
    SharedHarmonicSelection,
    load_project_processing_harmonics,
)
from Tools.Stats.analysis.dv_policy_settings import (
    HARMONIC_SELECTION_PROFILES,
    dv_policy_payload_from_selection_metadata,
)
from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowExclusionsMixin:
    def _get_dv_policy_payload(self) -> dict[str, object]:
        """Return the processing-owned policy, never a Stats-local selection."""

        if self._project_manifest_path().is_file():
            selection = self._load_canonical_harmonic_selection()
            return self._apply_canonical_harmonic_selection(selection)
        # Preserve the lightweight projectless construction used by import and
        # GUI contract tests. Real projects always resolve the accepted
        # processing-owned selection above.
        return {
            "name": self._dv_policy_name,
            "fixed_harmonic_frequencies_hz": str(self._dv_fixed_harmonic_frequencies_hz),
            "fixed_harmonic_auto_exclude_base": bool(
                self._dv_fixed_harmonic_auto_exclude_base
            ),
        }

    def _project_manifest_path(self) -> Path:
        project_root = Path(getattr(self, "_project_path", self.project_dir))
        return project_root / "project.json"

    def _load_canonical_harmonic_selection(self) -> SharedHarmonicSelection:
        return load_project_processing_harmonics(
            project_root=getattr(self, "_project_path", self.project_dir),
            log_func=lambda message: logger.debug(
                "stats_canonical_harmonic_selection",
                extra={"selection_message": str(message)},
            ),
        )

    def _apply_canonical_harmonic_selection(
        self,
        selection: SharedHarmonicSelection,
    ) -> dict[str, object]:
        metadata = selection.metadata
        payload = dv_policy_payload_from_selection_metadata(metadata)
        self._canonical_harmonic_selection = selection
        self._dv_policy_name = str(payload["name"])
        self._dv_fixed_harmonic_frequencies_hz = str(
            payload.get(
                "fixed_harmonic_frequencies_hz",
                self._dv_fixed_harmonic_frequencies_hz,
            )
        )
        self._dv_fixed_harmonic_auto_exclude_base = bool(
            payload.get("fixed_harmonic_auto_exclude_base", True)
        )

        profile_id = str(metadata.get("harmonic_selection_profile") or "")
        profile = HARMONIC_SELECTION_PROFILES.get(profile_id)
        profile_label = str(
            metadata.get("harmonic_selection_profile_label")
            or (profile.label if profile is not None else profile_id)
            or "Accepted project method"
        )
        profile_version = str(
            metadata.get("harmonic_selection_profile_version")
            or (profile.version if profile is not None else "")
        )
        if profile_version:
            profile_label = f"{profile_label} (v{profile_version})"
        included = ", ".join(
            f"{frequency:g}" for frequency in selection.selected_harmonics_hz
        )
        fingerprint = str(metadata.get("selection_fingerprint") or "")

        profile_widget = getattr(self, "harmonic_profile_value", None)
        if profile_widget is not None:
            profile_widget.setText(profile_label)
        included_widget = getattr(self, "harmonic_included_value", None)
        if included_widget is not None:
            included_widget.setText(f"{included} Hz")
        note = getattr(self, "harmonic_selection_note", None)
        if note is not None:
            fingerprint_text = (
                f" Accepted fingerprint: {fingerprint[:12]}." if fingerprint else ""
            )
            note.setText(
                "Read-only accepted processing selection. Change or recalculate "
                "it in Settings > Harmonics."
                + fingerprint_text
            )
            note.setToolTip(str(metadata.get("methods_summary") or ""))
        sync_provenance = getattr(self, "_sync_provenance_warning", None)
        if callable(sync_provenance):
            sync_provenance()
        return payload

    def _refresh_canonical_harmonic_summary(self) -> bool:
        """Refresh the read-only profile and included-list summary."""

        if not self._project_manifest_path().is_file():
            self._canonical_harmonic_selection = None
            self._set_unavailable_harmonic_summary(
                "No project selection loaded",
                "Open a project to inspect its accepted harmonics.",
            )
            return False
        try:
            selection = self._load_canonical_harmonic_selection()
            self._apply_canonical_harmonic_selection(selection)
        except (CanonicalHarmonicSelectionError, ValueError) as exc:
            self._canonical_harmonic_selection = None
            self._set_unavailable_harmonic_summary(
                "No current accepted selection",
                f"{exc} Open Harmonic Settings to recalculate it.",
            )
            return False
        return True

    def _set_unavailable_harmonic_summary(self, profile: str, detail: str) -> None:
        profile_widget = getattr(self, "harmonic_profile_value", None)
        if profile_widget is not None:
            profile_widget.setText(profile)
        included_widget = getattr(self, "harmonic_included_value", None)
        if included_widget is not None:
            included_widget.setText("Unavailable")
        note = getattr(self, "harmonic_selection_note", None)
        if note is not None:
            note.setText(detail)
            note.setToolTip(detail)

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
        """Keep the worker call shape without retired ROI-screen settings."""
        return {}

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

    def on_recalculate_harmonics_clicked(self) -> None:
        """Open the canonical Settings workflow without deleting saved metadata."""

        host = self.parentWidget()
        open_settings = None
        while host is not None:
            candidate = getattr(host, "open_settings_window", None)
            if callable(candidate):
                open_settings = candidate
                break
            host = host.parentWidget()
        if not callable(open_settings):
            QMessageBox.information(
                self,
                "Recalculate Harmonics in Settings",
                (
                    "Open the main FPVS Toolbox Settings page, choose "
                    "Harmonics, then use Recalculate Harmonics. Standard "
                    "FPVS Screening does not recalculate or clear processing-"
                    "time harmonic metadata."
                ),
            )
            return

        message = (
            "Opened Settings > Harmonics. Use Recalculate Harmonics, then return "
            "to Standard FPVS Screening."
        )
        self.append_log("General", message)
        self._set_status(message)
        open_settings()

        settings_page = getattr(host, "_settings_page", None)
        settings_tabs = getattr(settings_page, "tabs", None)
        set_current_index = getattr(settings_tabs, "setCurrentIndex", None)
        if callable(set_current_index):
            set_current_index(
                int(getattr(settings_page, "_harmonic_tab_index", 0))
            )
        recalculate_button = getattr(
            settings_page,
            "recalculate_harmonics_button",
            None,
        )
        set_focus = getattr(recalculate_button, "setFocus", None)
        if callable(set_focus):
            set_focus()

    def _sync_parent_project_manifest_tools(self) -> None:
        """Keep embedded Project.manifest tools metadata aligned after Stats writes."""
        parent = self.parent()
        project = getattr(parent, "currentProject", None)
        manifest = getattr(project, "manifest", None)
        project_root = getattr(project, "project_root", None)
        if not isinstance(manifest, dict) or project_root in (None, ""):
            return
        manifest_path = Path(project_root) / "project.json"
        try:
            disk_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.debug("stats_project_manifest_tools_sync_skipped", exc_info=True)
            return
        tools = disk_manifest.get("tools") if isinstance(disk_manifest, dict) else None
        if isinstance(tools, dict):
            manifest["tools"] = tools

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
                    "Electrode / ROI",
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
                        "Electrode / ROI": str(item["worst_roi"]),
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
                    "Electrode / ROI",
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

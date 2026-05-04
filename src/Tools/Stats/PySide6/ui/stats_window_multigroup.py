"""Multi-group scan and fixed-harmonic helpers for StatsWindow."""
from __future__ import annotations

from Tools.Stats.PySide6.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowMultigroupMixin:
    def _warn_unknown_excel_files(self, subject_data: Dict[str, Dict[str, str]], manifest: dict | None) -> None:
        """Handle the warn unknown excel files step for the Stats PySide6 workflow."""
        if not subject_data:
            return
        participants_map, _examples, manifest_issues = normalize_multigroup_manifest_groups(manifest)
        if manifest_issues or not participants_map:
            return
        unknown_files: set[str] = set()
        for pid, cond_map in subject_data.items():
            if not isinstance(cond_map, dict):
                continue
            normalized_pid = normalize_multigroup_pid(pid)
            if normalized_pid is not None and normalized_pid.canonical_id in participants_map:
                continue
            for filepath in cond_map.values():
                try:
                    unknown_files.add(os.path.basename(filepath))
                except Exception:
                    continue
        if not unknown_files:
            return
        files_list = "\n".join(sorted(unknown_files))
        QMessageBox.warning(
            self,
            "Unrecognized Excel Files",
            (
                "Warning: The following Excel files are not recognized in this project's subject list:\n"
                f"{files_list}\n"
                "Please remove these files from the folder or update the project metadata."
            ),
        )

    def _between_subjects(self) -> list[str]:
        """Return canonical multigroup subjects for between-group actions only."""

        snapshot = self._between_subject_snapshot
        if self._multi_group_manifest and snapshot is not None:
            return list(snapshot.subjects)
        return list(self.subjects)

    def _between_subject_data(self) -> Dict[str, Dict[str, str]]:
        """Return canonical multigroup subject data for between-group actions only."""

        snapshot = self._between_subject_snapshot
        if self._multi_group_manifest and snapshot is not None:
            return dict(snapshot.subject_data)
        return dict(self.subject_data)

    def _between_subject_groups(self) -> dict[str, str | None]:
        """Return canonical multigroup group assignments for between-group actions only."""

        snapshot = self._between_subject_snapshot
        if self._multi_group_manifest and snapshot is not None:
            return dict(snapshot.subject_groups)
        return dict(self.subject_groups)

    def _between_manual_excluded_pids(self) -> list[str]:
        """Normalize manual exclusions to canonical multigroup IDs when needed."""

        if not self._multi_group_manifest:
            return sorted(self.manual_excluded_pids)

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_pid in sorted(self.manual_excluded_pids):
            pid_match = normalize_multigroup_pid(raw_pid)
            canonical_pid = pid_match.canonical_id if pid_match is not None else str(raw_pid)
            if canonical_pid in seen:
                continue
            normalized.append(canonical_pid)
            seen.add(canonical_pid)
        return normalized

    def _log_between_snapshot_messages(self) -> None:
        """Surface multigroup normalization messages without blocking the UI."""

        snapshot = self._between_subject_snapshot
        if snapshot is None:
            return
        for message in snapshot.warnings:
            self.append_log("Between", message, level="warning")
        for message in snapshot.errors:
            self.append_log("Between", message, level="error")

    def _start_multigroup_scan(self, excel_root: Path | None = None) -> None:
        """Handle the start multigroup scan step for the Stats PySide6 workflow."""
        if not self._multigroup_scan_guard.start():
            return
        excel_root = excel_root or Path(self.le_folder.text() or self._preferred_stats_folder())
        project_root = self._project_path

        self._set_status("Scanning multi-group readiness…")

        worker = StatsWorker(
            run_multigroup_scan_worker,
            project_root=project_root,
            excel_root=excel_root,
            _op="multigroup_scan",
        )

        try:
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(worker)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to track multigroup scan worker")

        def _release() -> None:
            """Handle the release step for the Stats PySide6 workflow."""
            try:
                if worker in self._active_workers:
                    self._active_workers.remove(worker)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to release multigroup scan worker")
            finally:
                self._multigroup_scan_guard.done()

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                result = payload.get("result") if isinstance(payload, dict) else None
                if isinstance(result, MultiGroupScanResult):
                    self._multigroup_scan_result = result
                    self._update_multigroup_summary(result)
                else:
                    self._set_status("Multi-group scan failed to return results.")
                    self.append_log("General", "Multi-group scan failed to return results.", level="error")
            finally:
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self._set_status(f"Multi-group scan error: {message}")
                self.append_log("General", f"Multi-group scan error: {message}", level="error")
            finally:
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _format_multigroup_issue(self, issue: ScanIssue) -> str:
        """Handle the format multigroup issue step for the Stats PySide6 workflow."""
        context_bits = []
        context = issue.context or {}
        for key in ("pid", "group", "path"):
            value = context.get(key)
            if value:
                context_bits.append(f"{key}={value}")
        extra = f" ({', '.join(context_bits)})" if context_bits else ""
        return f"[{issue.severity.upper()}] {issue.message}{extra}"

    def _render_multigroup_issues(self, issues: list[ScanIssue]) -> None:
        """Handle the render multigroup issues step for the Stats PySide6 workflow."""
        if not hasattr(self, "multi_group_issue_text"):
            return
        if not issues:
            self.multi_group_issue_text.setPlainText("No issues detected.")
            self.multi_group_issue_toggle_btn.setEnabled(False)
            return
        self.multi_group_issue_toggle_btn.setEnabled(len(issues) > self._multigroup_issue_preview_limit)
        if self._multigroup_issue_expanded or len(issues) <= self._multigroup_issue_preview_limit:
            visible_issues = issues
            self.multi_group_issue_toggle_btn.setText("Hide details")
        else:
            visible_issues = issues[: self._multigroup_issue_preview_limit]
            remaining = len(issues) - len(visible_issues)
            if remaining > 0:
                visible_issues = visible_issues + [
                    ScanIssue(
                        severity="warning",
                        message=f"... {remaining} more issue(s).",
                        context={},
                    )
                ]
            self.multi_group_issue_toggle_btn.setText("Show details")
        lines = [self._format_multigroup_issue(issue) for issue in visible_issues]
        self.multi_group_issue_text.setPlainText("\n".join(lines))

    def _toggle_multigroup_issue_details(self) -> None:
        """Handle the toggle multigroup issue details step for the Stats PySide6 workflow."""
        self._multigroup_issue_expanded = not self._multigroup_issue_expanded
        if self._multigroup_scan_result:
            self._render_multigroup_issues(self._multigroup_scan_result.issues)

    def _update_multigroup_summary(self, result: MultiGroupScanResult) -> None:
        """Handle the update multigroup summary step for the Stats PySide6 workflow."""
        if hasattr(self, "multi_group_ready_value"):
            status_text = "Ready" if result.multi_group_ready else "Not ready"
            self.multi_group_ready_value.setText(status_text)
            self.multi_group_ready_value.set_variant(
                "success" if result.multi_group_ready else "error"
            )
        if hasattr(self, "multi_group_discovered_value"):
            self.multi_group_discovered_value.setText(str(len(result.discovered_subjects)))
        if hasattr(self, "multi_group_assigned_value"):
            self.multi_group_assigned_value.setText(str(len(result.assigned_subjects)))
        if hasattr(self, "multi_group_groups_value"):
            self.multi_group_groups_value.setText(str(len(result.subject_groups)))
        if hasattr(self, "multi_group_unassigned_value"):
            self.multi_group_unassigned_value.setText(str(len(result.unassigned_subjects)))
        if hasattr(self, "compute_shared_harmonics_btn"):
            self.compute_shared_harmonics_btn.setEnabled(bool(result.multi_group_ready))
        if not result.multi_group_ready:
            self._shared_harmonics_payload = {}
            self._fixed_harmonic_dv_payload = {}
            self._between_missingness_payload = {}
        self._refresh_fixed_harmonic_ui_state()

        self._render_multigroup_issues(result.issues)

        blocking = [issue for issue in result.issues if issue.severity == "blocking"]
        if blocking:
            message = f"Multi-group scan found {len(blocking)} blocking issue(s)."
            self._set_status(message)
            self.append_log("General", message, level="warning")
        else:
            self._set_status("Multi-group scan complete.")
        for issue in result.issues:
            log_level = "error" if issue.severity == "blocking" else "warning"
            logger.log(
                logging.ERROR if log_level == "error" else logging.WARNING,
                "stats_multigroup_issue",
                extra={
                    "severity": issue.severity,
                    "issue_message": issue.message,
                    **(issue.context or {}),
                },
            )

    def _on_compute_shared_harmonics_clicked(self) -> None:
        """Handle the on compute shared harmonics clicked step for the Stats PySide6 workflow."""
        between_subject_data = self._between_subject_data()
        between_subjects = self._between_subjects()
        if not between_subject_data or not between_subjects:
            self._set_status("Load project data before computing shared harmonics.")
            return
        selected_conditions = self._get_selected_conditions()
        if not selected_conditions:
            self._set_status("Select at least one condition before computing shared harmonics.")
            return
        if not self.rois:
            self._set_status("Define at least one ROI before computing shared harmonics.")
            return
        if not self._multigroup_scan_result or not self._multigroup_scan_result.multi_group_ready:
            message = (
                "Shared harmonics are available only when multi-group scan status is Ready. "
                "Fix scan issues and rescan."
            )
            self._set_status(message)
            self.append_log("General", message, level="warning")
            return

        out_dir = self._ensure_results_dir()
        export_path = Path(out_dir) / "Shared Harmonics Summary.xlsx"
        self.compute_shared_harmonics_btn.setEnabled(False)

        worker = StatsWorker(
            stats_worker_funcs.run_shared_harmonics_worker,
            subjects=between_subjects,
            conditions=selected_conditions,
            subject_data=between_subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
            exclude_harmonic1=self._dv_exclude_harmonic1,
            project_path=self._project_path,
            export_path=export_path,
            _op="shared_harmonics",
        )

        self._active_workers.append(worker)

        def _release() -> None:
            """Handle the release step for the Stats PySide6 workflow."""
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            self.compute_shared_harmonics_btn.setEnabled(
                bool(self._multigroup_scan_result and self._multigroup_scan_result.multi_group_ready)
            )

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                result = payload if isinstance(payload, dict) else {}
                self._shared_harmonics_payload = result
                self._fixed_harmonic_dv_payload = {}
                harmonics_by_roi = result.get("harmonics_by_roi", {}) if isinstance(result, dict) else {}
                roi_count = len(harmonics_by_roi) if isinstance(harmonics_by_roi, dict) else 0
                total_harmonics = 0
                if isinstance(harmonics_by_roi, dict):
                    total_harmonics = sum(len(v or []) for v in harmonics_by_roi.values())
                conditions_used = result.get("conditions_used", []) if isinstance(result, dict) else []
                exclude_h1 = bool(result.get("exclude_harmonic1_applied", False))
                export_target = str(result.get("export_path", export_path))
                summary = (
                    "Shared harmonics complete: "
                    f"ROIs={roi_count}, total harmonics={total_harmonics}, "
                    f"exclude harmonic 1={exclude_h1}, "
                    f"conditions={', '.join(conditions_used) if conditions_used else 'None'}, "
                    f"export={export_target}"
                )
                self._set_status(summary)
                self.append_log("General", summary, level="info")
                self._set_last_export_path(export_target)
                self._refresh_fixed_harmonic_ui_state()
            finally:
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self._set_status(f"Shared harmonics error: {message}")
                self.append_log("General", f"Shared harmonics error: {message}", level="error")
                self._refresh_fixed_harmonic_ui_state()
            finally:
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _on_compute_fixed_harmonic_dv_clicked(self) -> None:
        """Handle the on compute fixed harmonic dv clicked step for the Stats PySide6 workflow."""
        harmonics_by_roi = self._shared_harmonics_payload.get("harmonics_by_roi", {})
        if not isinstance(harmonics_by_roi, dict) or not any((harmonics_by_roi.get(k) or []) for k in harmonics_by_roi):
            self._set_status("Compute shared harmonics before fixed-harmonic DV.")
            self._refresh_fixed_harmonic_ui_state()
            return

        selected_conditions = self._get_selected_conditions()
        if not selected_conditions:
            self._set_status("Select at least one condition before computing fixed-harmonic DV.")
            return

        self.compute_fixed_harmonic_dv_btn.setEnabled(False)
        worker = StatsWorker(
            stats_worker_funcs.run_fixed_harmonic_dv_worker,
            subjects=self._between_subjects(),
            conditions=selected_conditions,
            subject_data=self._between_subject_data(),
            rois=self.rois,
            harmonics_by_roi=harmonics_by_roi,
            _op="fixed_harmonic_dv",
        )

        self._active_workers.append(worker)

        def _release() -> None:
            """Handle the release step for the Stats PySide6 workflow."""
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            self._refresh_fixed_harmonic_ui_state()

        def _on_finished(payload: dict) -> None:
            """Handle the on finished step for the Stats PySide6 workflow."""
            try:
                result = payload if isinstance(payload, dict) else {}
                dv_table = result.get("dv_table")
                missing_rows = result.get("missing_harmonics", [])
                row_count = int(len(dv_table.index)) if isinstance(dv_table, pd.DataFrame) else 0
                summary = (
                    "Fixed-harmonic DV ready: "
                    f"rows={row_count}, missing entries={len(missing_rows)}, cache=self._fixed_harmonic_dv_payload"
                )
                self._fixed_harmonic_dv_payload = {
                    "summary": summary,
                    "dv_table": dv_table,
                    "missing_harmonics": missing_rows,
                    "dv_policy": result.get("dv_policy", {}),
                }
                self._set_status(summary)
                self.append_log("General", summary, level="info")
            finally:
                _release()

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats PySide6 workflow."""
            try:
                self._set_status(f"Fixed-harmonic DV error: {message}")
                self.append_log("General", f"Fixed-harmonic DV error: {message}", level="error")
            finally:
                _release()

        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(_on_error)
        worker.signals.finished.connect(_on_finished)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _known_group_labels(self) -> list[str]:
        """Handle the known group labels step for the Stats PySide6 workflow."""
        return sorted({g for g in self._between_subject_groups().values() if g})

    def _ensure_between_ready(self) -> bool:
        """Handle the ensure between ready step for the Stats PySide6 workflow."""
        snapshot = self._between_subject_snapshot if self._multi_group_manifest else None
        if snapshot is not None and snapshot.errors:
            message = f"Between-group analysis is blocked: {snapshot.errors[0]}"
            self._set_status(message)
            self.append_log("Between", message, level="warning")
            return False

        groups = self._known_group_labels()
        if len(groups) < 2:
            if self._multi_group_manifest and not groups:
                msg = (
                    "No valid group assignments are available for between-group analysis. "
                    "Assign participants to project groups and rescan."
                )
            else:
                msg = (
                    "Between-group analysis requires at least two groups with assigned subjects."
                )
            QMessageBox.information(
                self,
                "Need Multiple Groups",
                msg,
            )
            return False
        return True

    # --------- window focus / run state ---------

    def _refresh_between_missingness_summary(self) -> None:
        """Handle the refresh between missingness summary step for the Stats PySide6 workflow."""
        payload = self._between_missingness_payload
        if not isinstance(payload, dict):
            return
        mixed_subjects = 0
        if isinstance(self.between_mixed_model_results_data, pd.DataFrame) and not self.between_mixed_model_results_data.empty:
            subjects = payload.get("mixed_model_subjects")
            if isinstance(subjects, list):
                mixed_subjects = len(subjects)
        scan = self._multigroup_scan_result
        payload["summary"] = {
            "n_groups": len(self._known_group_labels()),
            "n_mixed_subjects": mixed_subjects or len(set(payload.get("mixed_model_subjects", []))),
            "n_discovered_subjects": len(scan.discovered_subjects) if scan else 0,
            "n_assigned_subjects": len(scan.assigned_subjects) if scan else 0,
        }

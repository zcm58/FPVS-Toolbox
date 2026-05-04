"""Pipeline, worker, and result-handler helpers for StatsWindow."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowPipelineMixin:
    def append_log(self, section: str, message: str, level: str = "info") -> None:
        """Handle the append log step for the Stats workflow."""
        line = format_log_line(f"[{section}] {message}", level=level)
        if hasattr(self, "output_text") and self.output_text is not None:
            self.output_text.appendPlainText(line)
            self.output_text.ensureCursorVisible()
        level_lower = (level or "info").lower()
        log_func = getattr(logger, level_lower, logger.info)
        log_func(line)

    def _section_label(self, pipeline: PipelineId | None) -> str:
        """Handle the section label step for the Stats workflow."""
        if pipeline is PipelineId.SINGLE:
            return "Single"
        if pipeline is PipelineId.BETWEEN:
            return "Between"
        return "General"

    def _log_pipeline_event(
        self,
        *,
        pipeline: PipelineId | None,
        step: StepId | None = None,
        event: str,
        extra: Optional[dict] = None,
    ) -> None:
        """Handle the log pipeline event step for the Stats workflow."""
        if pipeline is None:
            return
        payload = {"pipeline": pipeline.name.lower(), "event": event}
        if step:
            payload["step_id"] = step.name
        if extra:
            payload.update(extra)
        logger.info(format_section_header("stats_pipeline_event"), extra=payload)

    def _focus_self(self) -> None:
        """Handle the focus self step for the Stats workflow."""
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

    def _set_running(self, running: bool) -> None:
        """Handle the set running step for the Stats workflow."""
        buttons = [
            getattr(self, "analyze_single_btn", None),
            getattr(self, "single_advanced_btn", None),
            getattr(self, "analyze_between_btn", None),
            getattr(self, "between_advanced_btn", None),
            getattr(self, "lela_mode_btn", None),
            getattr(self, "btn_open_results", None),
            getattr(self, "compute_shared_harmonics_btn", None),
            getattr(self, "compute_fixed_harmonic_dv_btn", None),
        ]
        for b in buttons:
            if b:
                b.setEnabled(not running)
        if not running and hasattr(self, "compute_shared_harmonics_btn"):
            self.compute_shared_harmonics_btn.setEnabled(
                bool(self._multigroup_scan_result and self._multigroup_scan_result.multi_group_ready)
            )
            self._refresh_fixed_harmonic_ui_state()
        spinner = getattr(self, "spinner", None)
        if spinner:
            if running:
                spinner.show()
                spinner.start()
            else:
                spinner.stop()
                spinner.hide()

    def _begin_run(self) -> bool:
        """Handle the begin run step for the Stats workflow."""
        if not self._guard.start():
            return False
        self._set_running(True)
        self._focus_self()
        return True

    def _end_run(self) -> None:
        """Handle the end run step for the Stats workflow."""
        self._set_running(False)
        self._guard.done()
        self._focus_self()

    # --------- settings helpers ---------

    def _safe_settings_get(self, section: str, key: str, default) -> Tuple[bool, object]:
        """Handle the safe settings get step for the Stats workflow."""
        try:
            settings = SettingsManager()
            val = settings.get(section, key, default)
            return True, val
        except Exception as e:
            self._log_ui_error(f"settings_get:{section}/{key}", e)
            return False, default

    def _get_analysis_settings(self) -> Optional[Tuple[float, float]]:
        """Handle the get analysis settings step for the Stats workflow."""
        ok1, bf = self._safe_settings_get("analysis", "base_freq", 6.0)
        ok2, a = self._safe_settings_get("analysis", "alpha", 0.05)
        try:
            base_freq = float(bf)
            alpha = float(a)
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Invalid analysis settings: {e}")
            return None
        if not (ok1 and ok2):
            QMessageBox.critical(self, "Settings Error", "Could not load analysis settings.")
            return None
        return base_freq, alpha

    def _get_harmonic_settings(self) -> Optional[HarmonicConfig]:
        """Handle the get harmonic settings step for the Stats workflow."""
        ok_metric, metric = self._safe_settings_get("analysis", "harmonic_metric", "Z Score")
        ok_threshold, threshold = self._safe_settings_get("analysis", "harmonic_threshold", 1.64)
        try:
            threshold_val = float(threshold)
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", f"Invalid harmonic threshold: {exc}")
            return None

        if not (ok_metric and ok_threshold):
            QMessageBox.critical(self, "Settings Error", "Could not load harmonic settings.")
            return None

        metric_str = str(metric) if metric is not None else "Z Score"
        return HarmonicConfig(metric_str, threshold_val)

    def _get_qc_settings(self) -> Optional[tuple[float, float]]:
        """Handle the get qc settings step for the Stats workflow."""
        ok_warn, warn = self._safe_settings_get(
            "analysis", "qc_warn_threshold", self._qc_threshold_sumabs
        )
        if not ok_warn:
            ok_warn, warn = self._safe_settings_get(
                "analysis", "qc_threshold_sumabs", self._qc_threshold_sumabs
            )
        ok_critical, critical = self._safe_settings_get(
            "analysis", "qc_critical_threshold", self._qc_threshold_maxabs
        )
        if not ok_critical:
            ok_critical, critical = self._safe_settings_get(
                "analysis", "qc_threshold_maxabs", self._qc_threshold_maxabs
            )
        try:
            warn_val = float(warn)
            critical_val = float(critical)
        except Exception as exc:
            QMessageBox.critical(self, "Settings Error", f"Invalid QC thresholds: {exc}")
            return None
        if not (ok_warn and ok_critical):
            QMessageBox.critical(self, "Settings Error", "Could not load QC thresholds.")
            return None
        return warn_val, critical_val

    # --------- centralized pre-run guards ---------

    def _precheck(self, *, require_anova: bool = False, start_guard: bool = True) -> bool:
        """Handle the precheck step for the Stats workflow."""
        if self._check_for_open_excel_files(self.le_folder.text()):
            return False
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please select a valid data folder first.")
            return False
        selected_conditions = self._get_selected_conditions()
        if len(selected_conditions) < 2:
            message = "Select at least two conditions to run the analysis."
            self._set_status(message)
            self.append_log("General", message, level="warning")
            return False
        if self.subjects and set(self.subjects).issubset(self.manual_excluded_pids):
            message = "All participants are manually excluded. Clear exclusions to run analysis."
            self._set_status(message)
            self.append_log("General", message, level="warning")
            return False
        if require_anova and self.rm_anova_results_data is None:
            QMessageBox.warning(
                self,
                "Run ANOVA First",
                "Please run a successful RM-ANOVA before running post-hoc tests for the interaction.",
            )
            return False
        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return False
        got = self._get_analysis_settings()
        if not got:
            return False
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_k_base_freq_label()
        harmonic_cfg = self._get_harmonic_settings()
        if not harmonic_cfg:
            return False
        self._harmonic_config = harmonic_cfg
        qc_cfg = self._get_qc_settings()
        if not qc_cfg:
            return False
        self._qc_threshold_sumabs, self._qc_threshold_maxabs = qc_cfg
        if start_guard and not self._begin_run():
            return False
        return True

    # --------- exports plumbing ---------

    def _between_mixed_model_support_state(
        self,
        payload: dict | None = None,
    ) -> tuple[bool, str]:
        """Return whether the current multigroup LMM result is exportable/supported."""

        candidate_payload = payload if isinstance(payload, dict) else {}
        fit_status = candidate_payload.get("fit_status")
        if isinstance(fit_status, dict) and fit_status.get("supported") is False:
            return False, str(fit_status.get("message") or "Supported multigroup LMM blocked.")
        if str(candidate_payload.get("status", "")).strip().lower() == "blocked":
            blocked_message = candidate_payload.get("message") or candidate_payload.get("blocked_reason")
            return False, str(blocked_message or "Supported multigroup LMM blocked.")

        results_df = (
            candidate_payload.get("mixed_results_df")
            if isinstance(candidate_payload.get("mixed_results_df"), pd.DataFrame)
            else self.between_mixed_model_results_data
        )
        if not isinstance(results_df, pd.DataFrame) or results_df.empty:
            attrs = results_df.attrs if isinstance(results_df, pd.DataFrame) else {}
            message = attrs.get("lmm_fit_status_message") if isinstance(attrs, dict) else ""
            return False, str(message or "Run Between-Group Mixed Model first.")

        attrs = results_df.attrs if isinstance(results_df.attrs, dict) else {}
        if attrs.get("lmm_fit_supported") is False:
            return False, str(attrs.get("lmm_fit_status_message") or "Supported multigroup LMM blocked.")
        return True, ""

    def _can_export_between_mixed_model(self) -> bool:
        """Return whether a supported between-group LMM export is available."""

        supported, _message = self._between_mixed_model_support_state()
        return supported

    def _update_export_buttons(self) -> None:
        """Handle the update export buttons step for the Stats workflow."""
        def _maybe_enable(name: str, enabled: bool) -> None:
            """Handle the maybe enable step for the Stats workflow."""
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(enabled)

        _maybe_enable(
            "export_rm_anova_btn",
            isinstance(self.rm_anova_results_data, pd.DataFrame)
            and not self.rm_anova_results_data.empty,
        )
        _maybe_enable(
            "export_mixed_model_btn",
            isinstance(self.mixed_model_results_data, pd.DataFrame)
            and not self.mixed_model_results_data.empty,
        )
        _maybe_enable(
            "export_posthoc_btn",
            isinstance(self.posthoc_results_data, pd.DataFrame)
            and not self.posthoc_results_data.empty,
        )
        _maybe_enable(
            "export_between_anova_btn",
            False,
        )
        _maybe_enable(
            "export_between_mixed_btn",
            self._can_export_between_mixed_model(),
        )
        _maybe_enable(
            "export_group_contrasts_btn",
            isinstance(self.group_contrasts_results_data, pd.DataFrame)
            and not self.group_contrasts_results_data.empty,
        )
        fixed_payload = self._fixed_harmonic_dv_payload if isinstance(self._fixed_harmonic_dv_payload, dict) else {}
        fixed_table = fixed_payload.get("dv_table")
        _maybe_enable(
            "export_qc_context_btn",
            isinstance(fixed_table, pd.DataFrame) and not fixed_table.empty,
        )

    def _build_summary_frames(self, pipeline_id: PipelineId) -> StatsSummaryFrames:
        """Handle the build summary frames step for the Stats workflow."""
        return build_summary_frames_from_results(
            pipeline_id,
            single_posthoc=self.posthoc_results_data,
            rm_anova_results=self.rm_anova_results_data,
            mixed_model_results=self.mixed_model_results_data,
            between_contrasts=self.group_contrasts_results_data,
            between_anova_results=self.between_anova_results_data,
            between_mixed_model_results=self.between_mixed_model_results_data,
            harmonic_results=self._harmonic_results.get(pipeline_id),
        )

    def _render_summary(self, summary_text: str) -> None:
        """Handle the render summary step for the Stats workflow."""
        lines = (summary_text or "").splitlines()
        if not lines:
            self.summary_text.append("(No summary generated.)")
            self.summary_text.append("")
            return
        header = lines[0].strip()
        try:
            cursor = self.summary_text.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.summary_text.setTextCursor(cursor)
            if header:
                self.summary_text.insertHtml(f"<b>{header}</b><br>")
            for line in lines[1:]:
                self.summary_text.append(line)
            self.summary_text.append("")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to render summary text", exc_info=True)
            if header:
                self.summary_text.append(header)
            for line in lines[1:]:
                self.summary_text.append(line)
            self.summary_text.append("")

    def _collect_excluded_reasons(self, pipeline_id: PipelineId) -> dict[str, str]:
        """Handle the collect excluded reasons step for the Stats workflow."""
        report = self._pipeline_run_reports.get(pipeline_id)
        if not isinstance(report, StatsRunReport):
            return {}
        reasons: dict[str, str] = {}
        for pid in report.manual_excluded_pids:
            reasons[str(pid)] = "manual exclusion"
        if report.qc_report:
            for participant in report.qc_report.participants:
                reasons[str(participant.participant_id)] = "QC exclusion"
        if report.required_exclusions:
            for violation in report.required_exclusions:
                reasons[str(violation.participant_id)] = f"required DV exclusion ({violation.reason})"
        return reasons

    def _build_reporting_summary_payload(self, pipeline_id: PipelineId, elapsed_ms: int) -> dict[str, object]:
        """Handle the build reporting summary payload step for the Stats workflow."""
        selected_conditions = self._pipeline_conditions.get(pipeline_id, self._get_selected_conditions())
        selected_rois = sorted((self.rois or {}).keys())
        report = self._pipeline_run_reports.get(pipeline_id)
        included = report.final_modeled_pids if isinstance(report, StatsRunReport) else []
        total_participants = len(self.subjects) if pipeline_id is PipelineId.SINGLE else len(self._between_subjects())
        context = ReportingSummaryContext(
            project_name=self.project_title,
            project_root=self._project_path,
            pipeline_name=pipeline_id.name,
            generated_local=datetime.now().astimezone(),
            elapsed_ms=int(elapsed_ms),
            timezone_label=str(datetime.now().astimezone().tzinfo or "Local"),
            total_participants=total_participants,
            included_participants=list(included),
            excluded_reasons=self._collect_excluded_reasons(pipeline_id),
            selected_conditions=list(selected_conditions),
            selected_rois=selected_rois,
        )
        anova_df = self.rm_anova_results_data if pipeline_id is PipelineId.SINGLE else None
        lmm_df = self.mixed_model_results_data if pipeline_id is PipelineId.SINGLE else self.between_mixed_model_results_data
        posthoc_df = self.posthoc_results_data if pipeline_id is PipelineId.SINGLE else self.group_contrasts_results_data
        auto_export = bool(getattr(self, "reporting_summary_export_checkbox", None) and self.reporting_summary_export_checkbox.isChecked())
        return {
            "context": context,
            "anova_df": anova_df,
            "lmm_df": lmm_df,
            "posthoc_df": posthoc_df,
            "auto_export": auto_export,
        }

    def _start_reporting_summary_worker(self, pipeline_id: PipelineId, elapsed_ms: int) -> None:
        """Handle the start reporting summary worker step for the Stats workflow."""
        payload = self._build_reporting_summary_payload(pipeline_id, elapsed_ms)

        def _worker_fn(progress_emit, message_emit, *, worker_payload):
            """Handle the worker fn step for the Stats workflow."""
            del progress_emit, message_emit
            context = worker_payload["context"]
            text = build_reporting_summary(
                context,
                anova_df=worker_payload.get("anova_df"),
                lmm_df=worker_payload.get("lmm_df"),
                posthoc_df=worker_payload.get("posthoc_df"),
            )
            result = {"report_text": text}
            if worker_payload.get("auto_export"):
                target = build_default_report_path(context.project_root, context.generated_local)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
                result["report_path"] = str(target)
            return result

        worker = StatsWorker(_worker_fn, worker_payload=payload, _op="reporting_summary")

        def _on_finished(worker_result: dict) -> None:
            """Handle the on finished step for the Stats workflow."""
            report_path = worker_result.get("report_path") if isinstance(worker_result, dict) else None
            if report_path:
                self._set_last_export_path(str(report_path))
                self._set_status(f"Reporting summary exported: {report_path}")

        def _on_error(message: str) -> None:
            """Handle the on error step for the Stats workflow."""
            logger.error(
                "stats_reporting_summary_failed",
                extra={
                    "operation": "build_reporting_summary",
                    "project": self.project_title,
                    "path": "",
                    "elapsed_ms": int(elapsed_ms),
                    "exception": message,
                },
            )
            self._set_status("Reporting summary generation failed; statistics exports are still complete.")

        worker.signals.report_ready.connect(self._on_report_ready)
        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        self.pool.start(worker)

    @Slot(str)
    def _on_report_ready(self, report_text: str) -> None:
        """Handle the on report ready step for the Stats workflow."""
        self._reporting_summary_text = report_text or ""
        self.reporting_summary_text.setPlainText(self._reporting_summary_text)

    # --------- worker signal wiring ---------

    def _wire_and_start(self, worker: StatsWorker, finished_slot) -> None:
        """Handle the wire and start step for the Stats workflow."""
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(finished_slot)
        self.pool.start(worker)

    def set_busy(self, is_busy: bool) -> None:
        """Handle the set busy step for the Stats workflow."""
        try:
            self._set_running(is_busy)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_view_set_busy_error",
                exc_info=True,
                extra={"is_busy": is_busy, "error": str(exc)},
            )

    def start_step_worker(
            self,
            pipeline_id: PipelineId,
            step: PipelineStep,
            *,
            finished_cb,
            error_cb,
            message_cb=None,
    ) -> None:
        """Create and start a StatsWorker for a single pipeline step.

        Diagnostics:
          - Entry log with pipeline / step metadata.
          - Log when the worker is constructed and submitted to the pool.
          - Logs when the finished/error slots are entered, including payload type/keys.
          - Tracks workers in self._active_workers so signals can't be dropped by GC.
        """
        try:
            logger.info(
                "stats_view_start_step_worker_enter",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                    "step_name": getattr(step, "name", repr(step)),
                    "kwargs_keys": list(step.kwargs.keys()) if isinstance(step.kwargs, dict) else None,
                },
            )
        except Exception:
            logger.exception("stats_view_start_step_worker_log_enter_failed")

        self._log_pipeline_event(pipeline=pipeline_id, step=step.id, event="start")

        worker = StatsWorker(
            step.worker_fn,
            **step.kwargs,
            _op=step.name,
            _step_id=getattr(step.id, "name", str(step.id)),
        )

        try:
            logger.info(
                "stats_view_worker_created",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                    "worker_class": type(worker).__name__,
                },
            )
        except Exception:
            logger.exception("stats_view_worker_created_log_failed")

        # Track worker strongly so it cannot be garbage-collected while
        # signals are in-flight. This also gives us better diagnostics.
        try:
            if not hasattr(self, "_active_workers"):
                self._active_workers = []
            self._active_workers.append(worker)
            logger.info(
                "stats_view_worker_tracked",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                    "worker_id": id(worker),
                    "active_workers_len": len(self._active_workers),
                },
            )
        except Exception:
            logger.exception("stats_view_worker_tracked_log_failed")

        def _release_worker(w=worker, pid=pipeline_id, sid=step.id):
            """Remove the worker from the active set once it has finished/error'd."""
            try:
                active = getattr(self, "_active_workers", None)
                if active is not None and w in active:
                    active.remove(w)
                logger.info(
                    "stats_view_worker_released",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                        "worker_id": id(w),
                        "active_workers_len": len(active) if active is not None else -1,
                    },
                )
            except Exception:
                logger.exception(
                    "stats_view_worker_release_failed",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )

        def _on_finished(payload, pid=pipeline_id, sid=step.id):
            # This is the first place we know the Qt finished signal reached the view.
            """Handle the on finished step for the Stats workflow."""
            try:
                payload_type = type(payload).__name__
                payload_keys = list(payload.keys()) if isinstance(payload, dict) else None
            except Exception:
                payload_type = type(payload).__name__
                payload_keys = None

            logger.info(
                "stats_view_finished_slot_enter",
                extra={
                    "pipeline": getattr(pid, "name", str(pid)),
                    "step": getattr(sid, "name", str(sid)),
                    "payload_type": payload_type,
                    "payload_keys": payload_keys,
                    "is_harmonic_check": getattr(sid, "name", str(sid)) == "HARMONIC_CHECK",
                },
            )
            try:
                logger.info(
                    "stats_view_finished_before_controller",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )
                finished_cb(pid, sid, payload)
                logger.info(
                    "stats_view_finished_after_controller",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_view_finished_controller_exception",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                        "error": str(exc),
                    },
                )
                try:
                    section = self._section_label(pid)
                    self.append_log(
                        section,
                        f"ERROR handling results for {getattr(sid, 'name', sid)}: {exc}",
                        level="error",
                    )
                except Exception:
                    logger.exception("stats_view_finished_error_reporting_failed")
            finally:
                _release_worker()

        def _on_error(message: str, pid=pipeline_id, sid=step.id):
            """Handle the on error step for the Stats workflow."""
            logger.error(
                "stats_view_error_slot_enter",
                extra={
                    "pipeline": getattr(pid, "name", str(pid)),
                    "step": getattr(sid, "name", str(sid)),
                    "error_message": message,
                },
            )
            try:
                error_cb(pid, sid, message)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_view_error_slot_handler_error",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                        "error": str(exc),
                    },
                )
            finally:
                _release_worker()

        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        worker.signals.message.connect(self._on_worker_message)
        if message_cb:
            worker.signals.message.connect(message_cb)
        worker.signals.progress.connect(self._on_worker_progress)

        try:
            logger.info(
                "stats_view_start_worker_submit",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                },
            )
        except Exception:
            logger.exception("stats_view_start_worker_submit_log_failed")

        self.pool.start(worker)

        try:
            logger.info(
                "stats_view_start_step_worker_exit",
                extra={
                    "pipeline": getattr(pipeline_id, "name", str(pipeline_id)),
                    "step": getattr(step.id, "name", str(step.id)),
                },
            )
        except Exception:
            logger.exception("stats_view_start_step_worker_exit_log_failed")

    def ensure_results_dir(self) -> str:
        """Handle the ensure results dir step for the Stats workflow."""
        return self._ensure_results_dir()

    def prompt_phase_folder(self, title: str, start_dir: str | None = None) -> Optional[str]:
        """Handle the prompt phase folder step for the Stats workflow."""
        folder = QFileDialog.getExistingDirectory(self, title, start_dir or self.project_dir)
        return folder or None

    def get_analysis_settings_snapshot(self) -> tuple[float, float, dict, list[str]]:
        """Handle the get analysis settings snapshot step for the Stats workflow."""
        self.refresh_rois()
        got = self._get_analysis_settings()
        if not got:
            raise RuntimeError("Unable to load analysis settings.")
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_k_base_freq_label()
        return self._current_base_freq, self._current_alpha, self.rois, self._get_selected_conditions()

    def ensure_pipeline_ready(
        self, pipeline_id: PipelineId, *, require_anova: bool = False
    ) -> bool:
        """Handle the ensure pipeline ready step for the Stats workflow."""
        self._log_pipeline_event(pipeline=pipeline_id, event="start")
        if not self._precheck(require_anova=require_anova, start_guard=False):
            self._log_pipeline_event(
                pipeline=pipeline_id, event="end", extra={"reason": "precheck_failed"}
            )
            return False
        if pipeline_id is PipelineId.BETWEEN and not self._ensure_between_ready():
            self._log_pipeline_event(
                pipeline=pipeline_id, event="end", extra={"reason": "between_not_ready"}
            )
            return False
        if pipeline_id is PipelineId.BETWEEN:
            if not (self._multigroup_scan_result and self._multigroup_scan_result.multi_group_ready):
                message = "Between-group analysis is blocked: multi-group readiness is not satisfied."
                self._set_status(message)
                self.append_log("Between", message, level="warning")
                return False
            harmonics_by_roi = self._shared_harmonics_payload.get("harmonics_by_roi", {})
            has_shared = isinstance(harmonics_by_roi, dict) and any(
                (harmonics_by_roi.get(key) or []) for key in harmonics_by_roi
            )
            if not has_shared:
                message = "Between-group analysis is blocked: compute shared harmonics first."
                self._set_status(message)
                self.append_log("Between", message, level="warning")
                return False
            dv_table = self._fixed_harmonic_dv_payload.get("dv_table")
            if not isinstance(dv_table, pd.DataFrame) or dv_table.empty:
                message = "Between-group analysis is blocked: compute fixed-harmonic DV first."
                self._set_status(message)
                self.append_log("Between", message, level="warning")
                return False
        self._log_pipeline_event(pipeline=pipeline_id, event="end")
        return True

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None:
        """Handle the on pipeline started step for the Stats workflow."""
        self._pipeline_start_perf[pipeline_id] = time.perf_counter()
        self._active_pipeline = pipeline_id
        self._harmonic_results[pipeline_id] = []
        self._pipeline_conditions[pipeline_id] = self._get_selected_conditions()
        self._pipeline_dv_policy[pipeline_id] = self._get_dv_policy_payload()
        self._pipeline_base_freq[pipeline_id] = self._current_base_freq
        self._pipeline_dv_metadata[pipeline_id] = {}
        self._pipeline_dv_variants[pipeline_id] = self._get_selected_dv_variants()
        self._pipeline_dv_variant_payloads[pipeline_id] = {}
        self._pipeline_outlier_config[pipeline_id] = self._get_outlier_exclusion_payload()
        self._pipeline_qc_config[pipeline_id] = self._get_qc_exclusion_payload()
        self._pipeline_qc_state[pipeline_id] = {"report": None}
        self._pipeline_run_reports[pipeline_id] = None
        if pipeline_id is PipelineId.BETWEEN:
            self.between_anova_results_data = None
            self._between_missingness_payload = {}
            if isinstance(self._fixed_harmonic_dv_payload, dict):
                self._fixed_harmonic_dv_payload.pop("prepared_multigroup_dv_payload", None)
        label = self.single_status_lbl if pipeline_id is PipelineId.SINGLE else self.between_status_lbl
        if label:
            if hasattr(label, "set_variant"):
                label.set_variant("info")
            label.setText("Running…")
        btn = self.analyze_single_btn if pipeline_id is PipelineId.SINGLE else self.analyze_between_btn
        if btn:
            btn.setEnabled(False)
        self._focus_self()
        self._log_pipeline_event(pipeline=pipeline_id, event="started")

    def store_dv_variants_payload(
        self, pipeline_id: PipelineId, dv_variants: dict | None
    ) -> None:
        """Handle the store dv variants payload step for the Stats workflow."""
        if not isinstance(dv_variants, dict) or not dv_variants:
            return
        self._store_dv_variants(pipeline_id, {"dv_variants": dv_variants})

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
    ) -> None:
        """Handle the on analysis finished step for the Stats workflow."""
        logger.info(
            "stats_analysis_finished_enter",
            extra={
                "pipeline": pipeline_id.name,
                "success": success,
                "error_message": error_message or "",
                "exports_ran": bool(exports_ran),
            },
        )
        label = self.single_status_lbl if pipeline_id is PipelineId.SINGLE else self.between_status_lbl
        btn = self.analyze_single_btn if pipeline_id is PipelineId.SINGLE else self.analyze_between_btn
        try:
            if label:
                if success:
                    ts = datetime.now().strftime("%H:%M:%S")
                    if hasattr(label, "set_variant"):
                        label.set_variant("success")
                    label.setText(f"Last run OK at {ts}")
                else:
                    if hasattr(label, "set_variant"):
                        label.set_variant("error")
                    label.setText("Last run error (see log)")
            self._active_pipeline = None
            if success:
                elapsed_ms = int((time.perf_counter() - self._pipeline_start_perf.get(pipeline_id, time.perf_counter())) * 1000)
                section = self._section_label(pipeline_id)
                if exports_ran:
                    if pipeline_id is PipelineId.SINGLE:
                        self.append_log(section, "  • Results exported for Single Group Analysis")
                    elif pipeline_id is PipelineId.BETWEEN:
                        self.append_log(section, "  • Results exported for Between-Group Analysis")
                        summary = self._between_missingness_payload.get("summary") if isinstance(self._between_missingness_payload, dict) else None
                        export_path = self._between_missingness_payload.get("export_path") if isinstance(self._between_missingness_payload, dict) else None
                        if isinstance(summary, dict):
                            line = (
                                "Between-group complete: "
                                f"groups={summary.get('n_groups', 0)}, "
                                f"modeled subjects={summary.get('n_mixed_subjects', 0)}, "
                                f"missingness export={export_path or 'pending export'}"
                            )
                            self._set_status(line)
                            self.append_log(section, line, level="info")
                    stats_folder = Path(self._ensure_results_dir())
                    self._prompt_view_results(self._section_label(pipeline_id), stats_folder)
                else:
                    self.append_log(section, "  • Analysis completed", level="info")
                self._start_reporting_summary_worker(pipeline_id, elapsed_ms)
            elif error_message:
                if "blocked" in error_message.lower():
                    self._set_status(error_message)
                    self.append_log(self._section_label(pipeline_id), error_message, level="warning")
                else:
                    try:
                        QMessageBox.critical(self, "Analysis Error", error_message)
                    except Exception:  # noqa: BLE001
                        logger.exception("Failed to display error dialog", exc_info=True)
            self._show_outlier_exclusion_dialog(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "stats_view_on_finished_error",
                exc_info=True,
                extra={
                    "pipeline": pipeline_id.name,
                    "success": success,
                    "error_message": error_message,
                    "error": str(exc),
                },
            )
        finally:
            try:
                if btn:
                    btn.setEnabled(True)
            except Exception:  # noqa: BLE001
                logger.exception("stats_finish_button_enable_failed", exc_info=True)
            try:
                self._update_export_buttons()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_update_export_buttons_failed",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "error": str(exc)},
                )
            try:
                self._log_pipeline_event(
                    pipeline=pipeline_id, event="complete", extra={"success": success}
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_pipeline_event_log_failed",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "error": str(exc)},
                )

    def closeEvent(self, event):  # type: ignore[override]
        """Handle the closeEvent step for the Stats workflow."""
        logger.info(
            "stats_window_close_event",
            extra={
                "window_id": id(self),
                "project_dir": getattr(self, "project_dir", ""),
            },
        )
        super().closeEvent(event)

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        """Handle the build and render summary step for the Stats workflow."""
        cfg = SummaryConfig(
            alpha=0.05,
            min_effect=0.50,
            max_bullets=3,
            z_threshold=self._harmonic_config.threshold,
            p_col="p_fdr",
            effect_col="effect_size",
        )
        frames = self._build_summary_frames(pipeline_id)
        summary_text = build_summary_from_frames(frames, cfg)
        self._render_summary(summary_text)

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool:
        """Handle the export pipeline results step for the Stats workflow."""
        if pipeline_id is PipelineId.SINGLE:
            return self._export_single_pipeline()
        if pipeline_id is PipelineId.BETWEEN:
            return self._export_between_pipeline()
        return False

    def _build_harmonic_kwargs(self) -> dict:
        # [SAFETY UPDATE] Load fresh ROIs from settings to ensure thread receives
        # the most up-to-date map, preventing 0xC0000005 errors.
        """Handle the build harmonic kwargs step for the Stats workflow."""
        fresh_rois = load_rois_from_settings() or self.rois
        _, max_freq_raw = self._safe_settings_get("analysis", "bca_upper_limit", 16.8)
        try:
            max_freq = float(max_freq_raw)
        except Exception:
            max_freq = None
        manual_excluded = set(self.manual_excluded_pids)
        filtered_subjects = [pid for pid in self.subjects if pid not in manual_excluded]
        filtered_subject_data = {
            pid: data for pid, data in self.subject_data.items() if pid not in manual_excluded
        }

        return dict(
            subject_data=filtered_subject_data,
            subjects=filtered_subjects,
            conditions=self._get_selected_conditions(),
            selected_metric=self._harmonic_config.metric,
            mean_value_threshold=self._harmonic_config.threshold,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            max_freq=max_freq,
            rois=fresh_rois,  # <--- Using fresh_rois instead of potentially stale self.rois
        )

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]:
        """Handle the get step config step for the Stats workflow."""
        dv_variants_payload = self._get_dv_variant_payloads()
        outlier_payload = self._pipeline_outlier_config.get(
            pipeline_id, self._get_outlier_exclusion_payload()
        )
        qc_payload = self._pipeline_qc_config.get(pipeline_id, self._get_qc_exclusion_payload())
        qc_state = self._pipeline_qc_state.get(pipeline_id, {"report": None})
        if pipeline_id is PipelineId.SINGLE:
            if step_id is StepId.RM_ANOVA:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    rois_all=self.rois,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                if os.getenv("FPVS_RM_ANOVA_DIAG", "0").strip() == "1":
                    kwargs["results_dir"] = self._ensure_results_dir()
                def handler(payload):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_rm_anova_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.MIXED_MODEL:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                def handler(payload):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_mixed_model_results(payload, update_text=False)

                return kwargs, handler
            if step_id is StepId.INTERACTION_POSTHOCS:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=self.subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )
                def handler(payload):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_posthoc_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.BASELINE_VS_ZERO:
                kwargs = dict(
                    subjects=self.subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=sorted(self.manual_excluded_pids),
                )

                def handler(payload):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_baseline_vs_zero_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                kwargs = self._build_harmonic_kwargs()

                def handler(payload, *, pid=pipeline_id):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_harmonic_results(payload, pipeline_id=pid, update_text=True)

                return kwargs, handler
        if pipeline_id is PipelineId.BETWEEN:
            between_subjects = self._between_subjects()
            between_subject_data = self._between_subject_data()
            between_subject_groups = self._between_subject_groups()
            between_manual_excluded = self._between_manual_excluded_pids()
            fixed_dv_table = self._fixed_harmonic_dv_payload.get("dv_table")
            shared_multigroup_dv_payload = self._fixed_harmonic_dv_payload.setdefault(
                "prepared_multigroup_dv_payload", {}
            )
            selected_conditions = self._get_selected_conditions()
            if step_id is StepId.BETWEEN_GROUP_ANOVA:
                raise ValueError(
                    "Between-group ANOVA is paused and unavailable in the multigroup workflow."
                )
            if step_id is StepId.BETWEEN_GROUP_MIXED_MODEL:
                results_dir = self._ensure_results_dir()
                kwargs = dict(
                    subjects=between_subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=between_subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=between_subject_groups,
                    include_group=True,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=between_manual_excluded,
                    fixed_harmonic_dv_table=fixed_dv_table,
                    required_conditions=selected_conditions,
                    subject_to_group=between_subject_groups,
                    prepared_multigroup_dv_payload=shared_multigroup_dv_payload,
                    results_dir=results_dir,
                )
                def handler(payload):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_between_mixed_results(payload, update_text=False)
                    supported, support_message = self._between_mixed_model_support_state(payload)
                    if not supported:
                        raise RuntimeError(support_message)

                return kwargs, handler
            if step_id is StepId.GROUP_CONTRASTS:
                kwargs = dict(
                    subjects=between_subjects,
                    conditions=self._get_selected_conditions(),
                    conditions_all=self.conditions,
                    subject_data=between_subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    rois_all=self.rois,
                    subject_groups=between_subject_groups,
                    dv_policy=self._get_between_group_dv_policy_payload(),
                    dv_variants=dv_variants_payload,
                    outlier_exclusion_enabled=outlier_payload.get("enabled", True),
                    outlier_abs_limit=outlier_payload.get("abs_limit", 50.0),
                    qc_config=qc_payload,
                    qc_state=qc_state,
                    manual_excluded_pids=between_manual_excluded,
                    fixed_harmonic_dv_table=fixed_dv_table,
                    required_conditions=selected_conditions,
                    subject_to_group=between_subject_groups,
                    prepared_multigroup_dv_payload=shared_multigroup_dv_payload,
                )
                def handler(payload):
                    """Handle the handler step for the Stats workflow."""
                    self._apply_group_contrasts_results(payload, update_text=True)

                return kwargs, handler
            if step_id is StepId.HARMONIC_CHECK:
                raise ValueError(
                    "Harmonic Check is not part of the supported multigroup workflow in this phase."
                )
        raise ValueError(f"Unsupported step configuration for {pipeline_id} / {step_id}")

    def _prompt_view_results(self, section: str, stats_folder: Path) -> None:
        """Handle the prompt view results step for the Stats workflow."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Statistical Analysis Complete")
        msg.setText("Statistical analysis complete.\nView results?")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        reply = msg.exec()

        if reply == QMessageBox.Yes:
            if stats_folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(stats_folder)))
            else:
                self.append_log(section, f"Stats folder not found: {stats_folder}", "error")

    @Slot(int)
    def _on_worker_progress(self, val: int) -> None:
        """Handle the on worker progress step for the Stats workflow."""
        self._progress_updates.append(val)

    @Slot(str)
    def _on_worker_message(self, msg: str) -> None:
        """Handle the on worker message step for the Stats workflow."""
        text = msg or ""
        if (
            text.startswith("[BETWEEN DV CONTRACT]")
            and self._controller.is_running(PipelineId.BETWEEN)
        ):
            self.append_log("Between", text)
        self._set_detected_info(msg)

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        """Handle the on worker error step for the Stats workflow."""
        self.output_text.appendPlainText(f"Error: {msg}")
        section = "General"
        try:
            if self._controller.is_running(PipelineId.SINGLE):
                section = "Single"
            elif self._controller.is_running(PipelineId.BETWEEN):
                section = "Between"
        except Exception:
            section = "General"
        self.append_log(section, f"Worker error: {msg}", level="error")
        self._end_run()

    def _store_dv_metadata(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store dv metadata step for the Stats workflow."""
        dv_meta = payload.get("dv_metadata")
        if isinstance(dv_meta, dict) and dv_meta:
            self._pipeline_dv_metadata[pipeline_id] = dv_meta
        self._store_dv_variants(pipeline_id, payload)

    def _store_dv_variants(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store dv variants step for the Stats workflow."""
        dv_variants = payload.get("dv_variants")
        if not isinstance(dv_variants, dict) or not dv_variants:
            return
        self._pipeline_dv_variant_payloads[pipeline_id] = dv_variants
        selected = dv_variants.get("selected_variants")
        if isinstance(selected, list):
            self._pipeline_dv_variants[pipeline_id] = list(selected)
        errors = dv_variants.get("errors", [])
        if errors:
            section = self._section_label(pipeline_id)
            for err in errors:
                variant_name = err.get("variant", "Unknown")
                message = err.get("error", "Unknown error")
                self.append_log(
                    section,
                    f"DV variant {variant_name} failed: {message}",
                    level="warning",
                )

    def _store_run_report(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store run report step for the Stats workflow."""
        report = payload.get("run_report")
        if isinstance(report, StatsRunReport):
            self._pipeline_run_reports[pipeline_id] = report

    def store_run_report(self, pipeline_id: PipelineId, report: StatsRunReport) -> None:
        """Handle the store run report step for the Stats workflow."""
        if isinstance(report, StatsRunReport):
            self._pipeline_run_reports[pipeline_id] = report

    def _apply_rm_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply rm anova results step for the Stats workflow."""
        self.rm_anova_results_data = payload.get("anova_df_results")
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
        alpha = getattr(self, "_current_alpha", 0.05)
        output_text = payload.get("output_text", "")

        if (
            (self.rm_anova_results_data is None or self.rm_anova_results_data.empty)
            and isinstance(output_text, str)
            and output_text.strip()
        ):
            section = self._section_label(PipelineId.SINGLE)
            self.append_log(
                section,
                f"  • RM-ANOVA note: {output_text.strip()}",
                level="warning",
            )

        output_text = build_rm_anova_output(self.rm_anova_results_data, alpha)
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply between anova results step for the Stats workflow."""
        self.between_anova_results_data = payload.get("anova_df_results")
        self._store_dv_metadata(PipelineId.BETWEEN, payload)
        self._store_run_report(PipelineId.BETWEEN, payload)
        missingness = payload.get("missingness", {}) if isinstance(payload, dict) else {}
        if isinstance(missingness, dict):
            self._between_missingness_payload.update(missingness)
        alpha = getattr(self, "_current_alpha", 0.05)

        output_text = build_between_anova_output(self.between_anova_results_data, alpha)
        self._refresh_between_missingness_summary()
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_mixed_model_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply mixed model results step for the Stats workflow."""
        self.mixed_model_results_data = payload.get("mixed_results_df")
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_mixed_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply between mixed results step for the Stats workflow."""
        if not isinstance(payload, dict):
            raise ValueError("Mixed-model payload must be a dict.")
        if "mixed_results_df" not in payload:
            raise ValueError("Mixed-model payload missing 'mixed_results_df'.")

        self.between_mixed_model_results_data = payload.get("mixed_results_df")
        self._store_dv_metadata(PipelineId.BETWEEN, payload)
        self._store_run_report(PipelineId.BETWEEN, payload)
        missingness = payload.get("missingness", {}) if isinstance(payload, dict) else {}
        if isinstance(missingness, dict):
            self._between_missingness_payload.update(missingness)
        output_text = payload.get("output_text", "")
        self._refresh_between_missingness_summary()
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_posthoc_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply posthoc results step for the Stats workflow."""
        self.posthoc_results_data = payload.get("results_df")
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_baseline_vs_zero_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply baseline-vs-zero results step for the Stats workflow."""
        self.baseline_vs_zero_results_payload = payload
        self._store_run_report(PipelineId.SINGLE, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_group_contrasts_results(self, payload: dict, *, update_text: bool = True) -> str:
        """Handle the apply group contrasts results step for the Stats workflow."""
        self.group_contrasts_results_data = payload.get("results_df")
        self._store_dv_metadata(PipelineId.BETWEEN, payload)
        self._store_run_report(PipelineId.BETWEEN, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_harmonic_results(
        self, payload: dict, *, pipeline_id: PipelineId, update_text: bool = True
    ) -> str:
        """Handle the apply harmonic results step for the Stats workflow."""
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        if update_text:
            self.summary_text.append("Harmonic details were exported to Harmonic Results.xlsx.")
        self._harmonic_results[pipeline_id] = findings
        self.harmonic_check_results_data = findings
        self._update_export_buttons()
        return output_text

    @Slot(dict)
    def _on_rm_anova_finished(self, payload: dict) -> None:
        """Handle the on rm anova finished step for the Stats workflow."""
        self._apply_rm_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_anova_finished(self, payload: dict) -> None:
        """Handle the on between anova finished step for the Stats workflow."""
        self._apply_between_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        """Handle the on mixed model finished step for the Stats workflow."""
        self._apply_mixed_model_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_mixed_finished(self, payload: dict) -> None:
        """Handle the on between mixed finished step for the Stats workflow."""
        self._apply_between_mixed_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        """Handle the on posthoc finished step for the Stats workflow."""
        self._apply_posthoc_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_group_contrasts_finished(self, payload: dict) -> None:
        """Handle the on group contrasts finished step for the Stats workflow."""
        self._apply_group_contrasts_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_harmonic_finished(self, payload: dict) -> None:
        """Handle the on harmonic finished step for the Stats workflow."""
        pipeline_id = self._active_pipeline or PipelineId.SINGLE
        self._apply_harmonic_results(payload, pipeline_id=pipeline_id)
        self._end_run()

    @Slot(object)
    def _on_lela_mode_finished(self, stats_folder: Path | None = None) -> None:
        """Handle the on lela mode finished step for the Stats workflow."""
        try:
            section = self._section_label(PipelineId.BETWEEN)
            self.append_log(section, "[Between] Lela Mode: complete — see Cross-Phase LMM Analysis.xlsx")
            if stats_folder:
                self.append_log(section, f"  • Excel: {stats_folder}")
        finally:
            self._end_run()

    @Slot(str)
    def _on_lela_mode_error(self, message: str) -> None:
        """Handle the on lela mode error step for the Stats workflow."""
        try:
            section = self._section_label(PipelineId.BETWEEN)
            self.append_log(section, f"[Between] Lela Mode error: {message}", level="error")
        finally:
            self._end_run()

    # --------------------------- UI building ---------------------------

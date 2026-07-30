"""Pipeline, worker, and result-handler helpers for StatsWindow."""
# ruff: noqa: F405
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403
from Tools.Stats.analysis.prepared_analysis import AnalysisMode
from Tools.Stats.reporting.logging_policy import stats_ide_log_level
from Tools.Stats.ui.stats_window_error_messages import build_worker_error_guidance
from Tools.Stats.ui.inference_view_model import (
    NativeInferenceOptions,
    coerce_analysis_mode,
    infer_harmonic_provenance,
    overall_progress,
    phase_label,
    pipeline_steps_for_options,
)

logger = logging.getLogger(__name__)


class StatsWindowPipelineMixin:
    def append_log(self, section: str, message: str, level: str = "info") -> None:
        """Handle the append log step for the Stats workflow."""
        line = format_log_line(f"[{section}] {message}", level=level)
        if hasattr(self, "output_text") and self.output_text is not None:
            self.output_text.appendPlainText(line)
            self.output_text.ensureCursorVisible()
        ide_level = stats_ide_log_level(message, level)
        log_func = getattr(logger, ide_level, logger.debug)
        log_func(line)

    def _section_label(self, pipeline: PipelineId | None) -> str:
        """Handle the section label step for the Stats workflow."""
        if pipeline is PipelineId.SINGLE:
            return "Single"
        if pipeline is PipelineId.MULTI:
            return "Multi-group"
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
        logger.debug(format_section_header("stats_pipeline_event"), extra=payload)

    def _focus_self(self) -> None:
        """Handle the focus self step for the Stats workflow."""
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

    def _set_running(self, running: bool) -> None:
        """Handle the set running step for the Stats workflow."""
        self._update_single_group_analysis_availability(running=running)
        stats_ready_btn = getattr(self, "stats_ready_export_btn", None)
        if stats_ready_btn:
            stats_ready_btn.setEnabled(not running)
        spinner = getattr(self, "spinner", None)
        if spinner:
            if running:
                spinner.show()
                spinner.start()
            else:
                spinner.stop()
                spinner.hide()
        notice = getattr(self, "stats_processing_notice", None)
        animation = getattr(self, "stats_processing_animation", None)
        message = getattr(self, "stats_processing_message", None)
        if running and message is not None:
            if getattr(self, "_dv_policy_name", "") == GROUP_SIGNIFICANT_POLICY_NAME:
                message.setText(
                    "FPVS Toolbox is currently calculating an average FFT spectrum across "
                    "all electrodes and participants to determine which harmonics are "
                    "considered statistically significant. This could take a few minutes."
                )
            else:
                message.setText(
                    "FPVS Toolbox is currently building Summed BCA values and running "
                    "the selected statistical analyses. This could take a few minutes."
                )
        if notice is not None:
            notice.setVisible(running)
        if animation is not None:
            if running:
                animation.start()
            else:
                animation.stop()
        running_helper = getattr(self, "set_pipeline_running", None)
        if callable(running_helper):
            running_helper(running, cancellable=running)
        else:
            cancel_button = getattr(self, "cancel_analysis_btn", None)
            if cancel_button is not None:
                cancel_button.setVisible(running)
                cancel_button.setEnabled(running)

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

    def _native_control_value(
        self,
        *,
        control_name: str,
        default: object,
    ) -> object:
        """Read one Qt control while keeping widget objects out of worker config."""

        control = getattr(self, control_name, None)
        if control is None:
            return default
        current_data = getattr(control, "currentData", None)
        if callable(current_data):
            data = current_data()
            if data is not None and str(data).strip():
                return data
        current_text = getattr(control, "currentText", None)
        if callable(current_text):
            text = current_text()
            if str(text).strip():
                return text
        return default

    def _native_checkbox_value(self, name: str, *, default: bool) -> bool:
        control = getattr(self, name, None)
        getter = getattr(control, "isChecked", None)
        return bool(getter()) if callable(getter) else bool(default)

    def _native_spin_value(self, name: str, *, default: int) -> int:
        control = getattr(self, name, None)
        getter = getattr(control, "value", None)
        return int(getter()) if callable(getter) else int(default)

    def _native_state_snapshot(self, pipeline_id: PipelineId) -> dict[str, object]:
        """Freeze all UI-owned native settings before controller step creation."""

        snapshot_getter = getattr(self, "_native_analysis_state_snapshot", None)
        if callable(snapshot_getter):
            snapshot = dict(snapshot_getter())
        else:
            project_is_multigroup = bool(
                getattr(self, "_project_is_multi_group", False)
            )
            fallback_mode = (
                AnalysisMode.MULTI if project_is_multigroup else AnalysisMode.SINGLE
            )
            snapshot = {
                "pipeline_id": (
                    PipelineId.MULTI
                    if fallback_mode is AnalysisMode.MULTI
                    else PipelineId.SINGLE
                ),
                "mode": fallback_mode.value,
                "analysis_profile": "published_style_exploratory",
                "correction": "holm",
                "response_alternative": "greater",
                "analysis_scope": "available_case",
                "strict_omnibus_family": True,
                "independent_selection_attested": self._native_checkbox_value(
                    "independent_selection_attestation",
                    default=False,
                ),
                "canonical_group_ids": dict(
                    getattr(self, "_participant_group_id_map", {}) or {}
                ),
                "participant_display_labels": dict(
                    getattr(self, "_subject_group_map", {}) or {}
                ),
                "group_display_labels": dict(
                    getattr(self, "_group_display_labels", {}) or {}
                ),
                "selected_group_pair": self._coerce_group_pair(
                    self._native_control_value(
                        control_name="group_pair_combo",
                        default=None,
                    )
                ),
                "selected_conditions": list(self._get_selected_conditions()),
                "sensitivity": {
                    "run_robust": self._native_checkbox_value(
                        "robust_sensitivity_checkbox",
                        default=True,
                    ),
                    "run_resampling": self._native_checkbox_value(
                        "resampling_sensitivity_checkbox",
                        default=True,
                    ),
                    "run_stability": self._native_checkbox_value(
                        "stability_sensitivity_checkbox",
                        default=True,
                    ),
                    "n_resamples": self._native_spin_value(
                        "resample_count_spin",
                        default=10_000,
                    ),
                },
            }
        snapshot_pipeline = snapshot.get("pipeline_id")
        if snapshot_pipeline is not None and snapshot_pipeline is not pipeline_id:
            raise ValueError(
                "The analysis controls changed while the run was being prepared. "
                "Review the mode and run again."
            )
        mode = coerce_analysis_mode(
            snapshot.get("mode"),
            project_is_multigroup=bool(
                getattr(self, "_project_is_multi_group", False)
            ),
        )
        expected_mode = (
            AnalysisMode.MULTI
            if pipeline_id is PipelineId.MULTI
            else AnalysisMode.SINGLE
        )
        if mode is not expected_mode:
            raise ValueError(
                "The analysis control snapshot does not match the requested "
                f"{self._section_label(pipeline_id)} pipeline."
            )
        return snapshot

    def _canonical_group_ids_for_subjects(
        self,
        source: Mapping[object, object] | None = None,
    ) -> dict[str, str]:
        source = source or getattr(self, "_participant_group_id_map", {}) or {}
        by_key = {
            str(participant).strip().casefold(): str(group_id).strip()
            for participant, group_id in dict(source).items()
            if str(participant).strip() and str(group_id).strip()
        }
        return {
            str(participant): by_key[str(participant).strip().casefold()]
            for participant in self.subjects
            if str(participant).strip().casefold() in by_key
        }

    @staticmethod
    def _coerce_group_pair(value: object) -> tuple[str, str] | None:
        if isinstance(value, dict):
            value = value.get("group_pair") or value.get("ids")
        if isinstance(value, (tuple, list)) and len(value) == 2:
            pair = tuple(str(item).strip() for item in value)
            return pair if all(pair) else None
        text = str(value or "").strip()
        for separator in ("|", "::", " vs ", " versus "):
            if separator in text:
                parts = tuple(part.strip() for part in text.split(separator, 1))
                return parts if len(parts) == 2 and all(parts) else None
        return None

    def _selected_native_group_pair(
        self,
        canonical_group_ids: dict[str, str],
        raw_pair: object = None,
    ) -> tuple[str, str] | None:
        observed = tuple(
            sorted(
                {
                    str(group_id).strip()
                    for group_id in canonical_group_ids.values()
                    if str(group_id).strip()
                },
                key=str.casefold,
            )
        )
        if len(observed) != 2:
            raise ValueError(
                "Standard multi-group screening requires exactly two canonical "
                "groups in the selected participant cohort. Use a "
                "study-specific custom model for another group structure."
            )
        if raw_pair is None:
            raw_pair = self._native_control_value(
                control_name="group_pair_combo",
                default=None,
            )
        pair = self._coerce_group_pair(raw_pair)
        if pair is None:
            return (observed[0], observed[1])
        observed_by_key = {group.casefold(): group for group in observed}
        missing = [group for group in pair if group.casefold() not in observed_by_key]
        if missing:
            raise ValueError(
                "The selected group comparison is not available in the frozen "
                f"cohort: {', '.join(missing)}."
            )
        resolved = tuple(observed_by_key[group.casefold()] for group in pair)
        if resolved[0].casefold() == resolved[1].casefold():
            raise ValueError("Select two different canonical groups to compare.")
        return resolved

    def _build_native_options(
        self,
        pipeline_id: PipelineId,
    ) -> NativeInferenceOptions:
        snapshot = self._native_state_snapshot(pipeline_id)
        expected_mode = (
            AnalysisMode.MULTI
            if pipeline_id is PipelineId.MULTI
            else AnalysisMode.SINGLE
        )
        same_sample_adaptive = (
            getattr(self, "_dv_policy_name", "") == GROUP_SIGNIFICANT_POLICY_NAME
        )
        if same_sample_adaptive:
            provenance = infer_harmonic_provenance(
                independently_selected=False,
                same_sample_adaptive=True,
            )
        else:
            provenance = snapshot.get("harmonic_provenance")
            if not str(provenance or "").strip():
                provenance = infer_harmonic_provenance(
                    independently_selected=bool(
                        snapshot.get("independent_selection_attested", False)
                    ),
                    same_sample_adaptive=False,
                )
        canonical_group_ids = self._canonical_group_ids_for_subjects(
            snapshot.get("canonical_group_ids")  # type: ignore[arg-type]
        )
        if expected_mode is AnalysisMode.MULTI:
            assigned = {
                participant.strip().casefold()
                for participant in canonical_group_ids
            }
            missing_assignments = [
                str(participant)
                for participant in self.subjects
                if str(participant).strip().casefold() not in assigned
            ]
            if missing_assignments:
                raise ValueError(
                    "Canonical group assignment is missing for: "
                    + ", ".join(missing_assignments)
                    + ". Update project metadata, then re-scan."
                )
        group_pair = (
            self._selected_native_group_pair(
                canonical_group_ids,
                snapshot.get("selected_group_pair"),
            )
            if expected_mode is AnalysisMode.MULTI
            else None
        )
        sensitivity = snapshot.get("sensitivity")
        sensitivity = sensitivity if isinstance(sensitivity, Mapping) else {}
        options = NativeInferenceOptions(
            mode=expected_mode,
            profile="published_style_exploratory",
            correction="holm",
            alternative="greater",
            harmonic_provenance=provenance,
            alpha=self._current_alpha,
            analysis_scope="available_case",
            strict_omnibus_family=True,
            selected_group_pair=group_pair,
            run_robust=bool(sensitivity.get("run_robust", True)),
            run_resampling=bool(sensitivity.get("run_resampling", True)),
            run_stability=bool(sensitivity.get("run_stability", True)),
            n_resamples=int(sensitivity.get("n_resamples", 10_000)),
        )
        snapshots = getattr(self, "_native_state_by_pipeline", None)
        if not isinstance(snapshots, dict):
            snapshots = {}
            self._native_state_by_pipeline = snapshots
        snapshots[pipeline_id] = snapshot
        return options

    def _native_options_for(
        self,
        pipeline_id: PipelineId,
    ) -> NativeInferenceOptions:
        options_by_pipeline = getattr(self, "_native_options_by_pipeline", None)
        if not isinstance(options_by_pipeline, dict):
            options_by_pipeline = {}
            self._native_options_by_pipeline = options_by_pipeline
        options = options_by_pipeline.get(pipeline_id)
        if not isinstance(options, NativeInferenceOptions):
            options = self._build_native_options(pipeline_id)
            options_by_pipeline[pipeline_id] = options
        return options

    def _native_step_store(self) -> dict[PipelineId, dict[StepId, dict]]:
        store = getattr(self, "_native_step_payloads", None)
        if not isinstance(store, dict):
            store = {}
            self._native_step_payloads = store
        return store

    def _store_native_step_payload(
        self,
        pipeline_id: PipelineId,
        step_id: StepId,
        payload: dict,
    ) -> None:
        self._native_step_store().setdefault(pipeline_id, {})[step_id] = payload
        if pipeline_id is getattr(self, "_active_pipeline", None):
            result_payloads = getattr(self, "_native_result_payloads", None)
            if not isinstance(result_payloads, dict):
                result_payloads = {}
                self._native_result_payloads = result_payloads
            result_payloads[step_id] = payload
        if step_id is StepId.PREPARE_ANALYSIS:
            prepared = payload.get("prepared_payload")
            if prepared is not None:
                self._prepared_analysis_payload = prepared
        elif step_id is StepId.REPORT_BUNDLE:
            bundle = payload.get("report_bundle")
            if bundle is not None:
                self._native_report_bundle = bundle

    def run_primary_analysis(self) -> None:
        """Dispatch the primary action according to immutable project mode."""

        project_is_multigroup = bool(getattr(self, "_project_is_multi_group", False))
        mode = AnalysisMode.MULTI if project_is_multigroup else AnalysisMode.SINGLE
        if mode is AnalysisMode.MULTI:
            try:
                options = self._build_native_options(PipelineId.MULTI)
            except Exception as exc:  # noqa: BLE001
                self._set_status(str(exc))
                self.append_log("Multi-group", str(exc), level="warning")
                return
            step_ids = pipeline_steps_for_options(options)
            self._native_options_by_pipeline = {PipelineId.MULTI: options}
            self._controller.run_multigroup_analysis(step_ids=step_ids)
            return
        try:
            options = self._build_native_options(PipelineId.SINGLE)
        except Exception as exc:  # noqa: BLE001
            self._set_status(str(exc))
            self.append_log("Single", str(exc), level="warning")
            return
        self._native_options_by_pipeline = {PipelineId.SINGLE: options}
        self._controller.run_single_group_analysis(
            step_ids=pipeline_steps_for_options(options)
        )

    def on_cancel_analysis_clicked(self) -> None:
        """Request cooperative cancellation without releasing busy state early."""

        pipeline_id = getattr(self, "_active_pipeline", None)
        if not self._controller.cancel_pipeline(pipeline_id):
            return
        self._set_status("Cancellation requested; waiting for the active step.")
        cancel_button = getattr(self, "cancel_analysis_btn", None)
        if cancel_button is not None:
            cancel_button.setEnabled(False)

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
        self._update_fixed_predefined_base_freq_label()
        qc_cfg = self._get_qc_settings()
        if not qc_cfg:
            return False
        self._qc_threshold_sumabs, self._qc_threshold_maxabs = qc_cfg
        if start_guard and not self._begin_run():
            return False
        return True

    # --------- exports plumbing ---------

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

    def _build_summary_frames(self, pipeline_id: PipelineId) -> StatsSummaryFrames:
        """Handle the build summary frames step for the Stats workflow."""
        return build_summary_frames_from_results(
            pipeline_id,
            single_posthoc=self.posthoc_results_data,
            rm_anova_results=self.rm_anova_results_data,
            mixed_model_results=self.mixed_model_results_data,
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
        total_participants = len(self.subjects)
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
        lmm_df = self.mixed_model_results_data
        posthoc_df = self.posthoc_results_data
        auto_export = self._auto_export_reporting_summary_enabled()
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

        worker.signals.finished.connect(_on_finished)
        worker.signals.error.connect(_on_error)
        self.pool.start(worker)

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

    def _native_worker_is_current(
        self,
        pipeline_id: PipelineId,
        step_id: StepId,
        worker: StatsWorker,
    ) -> bool:
        """Return whether a signal belongs to the current project/run step."""

        return (
            getattr(self, "_active_pipeline", None) is pipeline_id
            and getattr(self, "_active_step_worker", None) is worker
            and getattr(self, "_active_step_context", None)
            == (pipeline_id, step_id, worker)
        )

    def _set_native_worker_progress(
        self,
        pipeline_id: PipelineId,
        step_id: StepId,
        step_percent: int | float,
    ) -> None:
        """Map worker-local progress to one stable pipeline progress value."""

        step_orders = getattr(self, "_native_step_order_by_pipeline", {})
        step_order = (
            tuple(step_orders.get(pipeline_id, ()))
            if isinstance(step_orders, Mapping)
            else ()
        )
        percent = overall_progress(
            pipeline_id,
            step_id,
            step_percent,
            step_order=step_order or None,
        )
        self._progress_updates.append(percent)
        setter = getattr(self, "set_pipeline_progress", None)
        if callable(setter):
            setter(phase_label(step_id), percent=percent)
            return
        phase_widget = getattr(self, "pipeline_phase_label", None)
        if phase_widget is not None:
            phase_widget.setText(phase_label(step_id))
        progress_widget = getattr(self, "pipeline_progress_bar", None)
        if progress_widget is not None:
            progress_widget.setRange(0, 100)
            progress_widget.setValue(percent)

    def cancel_active_worker(self, pipeline_id: PipelineId) -> None:
        """Suppress stale worker chatter after cooperative cancellation."""

        suppressed = getattr(self, "_suppressed_native_pipelines", None)
        if not isinstance(suppressed, set):
            suppressed = set()
            self._suppressed_native_pipelines = suppressed
        suppressed.add(pipeline_id)
        cancel_button = getattr(self, "cancel_analysis_btn", None)
        if cancel_button is not None:
            cancel_button.setEnabled(False)
        self._set_status(
            "Cancellation requested; waiting for the active statistical "
            "checkpoint."
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
            logger.debug(
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
        self._active_step_worker = worker
        self._active_step_context = (pipeline_id, step.id, worker)
        self._set_native_worker_progress(
            pipeline_id,
            step.id,
            0,
        )

        try:
            logger.debug(
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
            logger.debug(
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
                if getattr(self, "_active_step_worker", None) is w:
                    self._active_step_worker = None
                    self._active_step_context = None
                logger.debug(
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

            logger.debug(
                "stats_view_finished_slot_enter",
                extra={
                    "pipeline": getattr(pid, "name", str(pid)),
                    "step": getattr(sid, "name", str(sid)),
                    "payload_type": payload_type,
                    "payload_keys": payload_keys,
                },
            )
            try:
                if (
                    self._native_worker_is_current(pid, sid, worker)
                    and pid
                    not in getattr(
                        self,
                        "_suppressed_native_pipelines",
                        set(),
                    )
                    and isinstance(payload, dict)
                ):
                    self._store_native_step_payload(pid, sid, payload)
                logger.debug(
                    "stats_view_finished_before_controller",
                    extra={
                        "pipeline": getattr(pid, "name", str(pid)),
                        "step": getattr(sid, "name", str(sid)),
                    },
                )
                finished_cb(pid, sid, payload)
                self._sync_parent_project_manifest_tools()
                logger.debug(
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

        def _on_message(
            message: str,
            pid=pipeline_id,
            sid=step.id,
            current_worker=worker,
        ) -> None:
            if not self._native_worker_is_current(pid, sid, current_worker):
                return
            if pid in getattr(self, "_suppressed_native_pipelines", set()):
                return
            self._on_worker_message(message)
            if message_cb:
                message_cb(message)

        def _on_progress(
            value: int,
            pid=pipeline_id,
            sid=step.id,
            current_worker=worker,
        ) -> None:
            if not self._native_worker_is_current(pid, sid, current_worker):
                return
            if pid in getattr(self, "_suppressed_native_pipelines", set()):
                return
            self._set_native_worker_progress(pid, sid, value)

        worker.signals.message.connect(_on_message)
        worker.signals.progress.connect(_on_progress)

        try:
            logger.debug(
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
            logger.debug(
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

    def get_analysis_settings_snapshot(self) -> tuple[float, float, dict, list[str]]:
        """Handle the get analysis settings snapshot step for the Stats workflow."""
        self.refresh_rois()
        got = self._get_analysis_settings()
        if not got:
            raise RuntimeError("Unable to load analysis settings.")
        self._current_base_freq, self._current_alpha = got
        self._update_fixed_predefined_base_freq_label()
        return self._current_base_freq, self._current_alpha, self.rois, self._get_selected_conditions()

    def ensure_pipeline_ready(
        self, pipeline_id: PipelineId, *, require_anova: bool = False
    ) -> bool:
        """Handle the ensure pipeline ready step for the Stats workflow."""
        self._log_pipeline_event(pipeline=pipeline_id, event="start")
        project_is_multigroup = bool(getattr(self, "_project_is_multi_group", False))
        expected_pipeline = (
            PipelineId.MULTI if project_is_multigroup else PipelineId.SINGLE
        )
        if pipeline_id is not expected_pipeline:
            message = (
                "Analysis mode does not match the active project manifest. "
                f"This project requires {self._section_label(expected_pipeline)} mode."
            )
            self._set_status(message)
            self.append_log("General", message, level="warning")
            self._log_pipeline_event(
                pipeline=pipeline_id,
                event="end",
                extra={"reason": "analysis_mode_project_mismatch"},
            )
            return False
        if not self._precheck(require_anova=require_anova, start_guard=False):
            self._log_pipeline_event(
                pipeline=pipeline_id, event="end", extra={"reason": "precheck_failed"}
            )
            return False
        try:
            options = self._build_native_options(pipeline_id)
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            self._set_status(message)
            self.append_log(
                self._section_label(pipeline_id),
                message,
                level="warning",
            )
            self._log_pipeline_event(
                pipeline=pipeline_id,
                event="end",
                extra={"reason": "native_options_invalid"},
            )
            return False
        self._native_options_by_pipeline = {pipeline_id: options}
        self._log_pipeline_event(pipeline=pipeline_id, event="end")
        return True

    def on_pipeline_started(self, pipeline_id: PipelineId) -> None:
        """Reset run-local result/progress state for the native pipeline."""

        snapshot = getattr(self, "_native_state_by_pipeline", {}).get(
            pipeline_id,
            {},
        )
        self._pipeline_start_perf[pipeline_id] = time.perf_counter()
        self._active_pipeline = pipeline_id
        controller_states = getattr(self._controller, "_states", {})
        controller_state = (
            controller_states.get(pipeline_id)
            if isinstance(controller_states, Mapping)
            else None
        )
        actual_step_order = tuple(
            step.id
            for step in getattr(controller_state, "steps", ())
            if isinstance(getattr(step, "id", None), StepId)
        )
        step_orders = getattr(self, "_native_step_order_by_pipeline", None)
        if not isinstance(step_orders, dict):
            step_orders = {}
            self._native_step_order_by_pipeline = step_orders
        step_orders[pipeline_id] = actual_step_order
        self._pipeline_conditions[pipeline_id] = list(
            snapshot.get("selected_conditions")
            or self._get_selected_conditions()
        )
        self._pipeline_dv_policy[pipeline_id] = self._get_dv_policy_payload()
        self._pipeline_base_freq[pipeline_id] = self._current_base_freq
        self._pipeline_dv_metadata[pipeline_id] = {}
        self._pipeline_outlier_config[pipeline_id] = self._get_outlier_exclusion_payload()
        self._pipeline_qc_config[pipeline_id] = self._get_qc_exclusion_payload()
        self._pipeline_qc_state.setdefault(pipeline_id, {"report": None})
        self._pipeline_run_reports[pipeline_id] = None
        self._native_step_store()[pipeline_id] = {}
        self._native_result_payloads = {}
        self._prepared_analysis_payload = None
        self._native_report_bundle = None
        self._active_step_worker = None
        self._active_step_context = None
        suppressed = getattr(self, "_suppressed_native_pipelines", None)
        if not isinstance(suppressed, set):
            suppressed = set()
            self._suppressed_native_pipelines = suppressed
        suppressed.discard(pipeline_id)
        if hasattr(self.lbl_status, "set_variant"):
            self.lbl_status.set_variant("info")
        self._set_status(
            "Running Standard FPVS Screening "
            f"({self._section_label(pipeline_id).lower()})..."
        )
        running_setter = getattr(self, "set_pipeline_running", None)
        if callable(running_setter):
            running_setter(True, cancellable=True)
        progress_setter = getattr(self, "set_pipeline_progress", None)
        if callable(progress_setter):
            progress_setter("Preparing analysis", percent=0)
        else:
            phase_widget = getattr(self, "pipeline_phase_label", None)
            if phase_widget is not None:
                phase_widget.setText("Preparing analysis")
            progress_widget = getattr(self, "pipeline_progress_bar", None)
            if progress_widget is not None:
                progress_widget.setValue(0)
        self._focus_self()
        self._log_pipeline_event(pipeline=pipeline_id, event="started")

    def on_analysis_finished(
        self,
        pipeline_id: PipelineId,
        success: bool,
        error_message: Optional[str],
        *,
        exports_ran: bool,
        cancelled: bool = False,
    ) -> None:
        """Finalize native UI state without blocking dialogs or duplicate exports."""
        logger.debug(
            "stats_analysis_finished_enter",
            extra={
                "pipeline": pipeline_id.name,
                "success": success,
                "error_message": error_message or "",
                "exports_ran": bool(exports_ran),
                "cancelled": bool(cancelled),
            },
        )
        try:
            section = self._section_label(pipeline_id)
            report_payload = (
                self._native_step_store()
                .get(pipeline_id, {})
                .get(StepId.REPORT_BUNDLE, {})
            )
            export_path = str(report_payload.get("export_path") or "").strip()
            export_confirmed = bool(
                report_payload.get("exported")
                or report_payload.get("numeric_exported")
            )
            if exports_ran and export_confirmed and export_path:
                self._set_last_export_path(export_path)

            if cancelled:
                if hasattr(self.lbl_status, "set_variant"):
                    self.lbl_status.set_variant("warning")
                self._set_status(
                    "Standard FPVS Screening cancelled safely."
                )
                phase_text = "Cancelled"
                self.append_log(
                    section,
                    "Standard FPVS Screening was cancelled; partial results "
                    "were not reported.",
                    level="warning",
                )
            elif success:
                ts = datetime.now().strftime("%H:%M:%S")
                if hasattr(self.lbl_status, "set_variant"):
                    self.lbl_status.set_variant("success")
                if export_path:
                    self._set_status(
                        "Standard FPVS Screening complete at "
                        f"{ts}. Workbook: {export_path}"
                    )
                else:
                    self._set_status(
                        f"Standard FPVS Screening complete at {ts}."
                    )
                phase_text = "Complete"
                if exports_ran:
                    self.append_log(
                        section,
                        f"Detailed results workbook exported: {export_path}",
                    )
                else:
                    self.append_log(
                        section,
                        "Standard FPVS Screening completed.",
                    )
            else:
                if hasattr(self.lbl_status, "set_variant"):
                    self.lbl_status.set_variant(
                        "warning"
                        if error_message
                        and "blocked" in error_message.casefold()
                        else "error"
                    )
                phase_text = "Stopped"
                self._set_status(
                    error_message
                    or (
                        "Standard FPVS Screening stopped before a report "
                        "could be completed."
                    )
                )
                if error_message:
                    self.append_log(
                        section,
                        error_message,
                        level=(
                            "warning"
                            if "blocked" in error_message.casefold()
                            else "error"
                        ),
                    )

            progress_bar = getattr(self, "pipeline_progress_bar", None)
            progress_value = (
                int(progress_bar.value())
                if progress_bar is not None
                and callable(getattr(progress_bar, "value", None))
                else 0
            )
            running_setter = getattr(self, "set_pipeline_running", None)
            if callable(running_setter):
                running_setter(False, cancellable=False)
            progress_setter = getattr(self, "set_pipeline_progress", None)
            if callable(progress_setter):
                progress_setter(
                    phase_text,
                    percent=100 if success else progress_value,
                )
            else:
                phase_widget = getattr(self, "pipeline_phase_label", None)
                if phase_widget is not None:
                    phase_widget.setText(phase_text)
                if success and progress_bar is not None:
                    progress_bar.setValue(100)
            self._active_pipeline = None
            self._active_step_worker = None
            self._active_step_context = None
            suppressed = getattr(self, "_suppressed_native_pipelines", set())
            suppressed.discard(pipeline_id)
            if success:
                tabs = getattr(self, "results_tabs", None)
                if tabs is not None:
                    tabs.setCurrentIndex(0)
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
            step_orders = getattr(
                self,
                "_native_step_order_by_pipeline",
                None,
            )
            if isinstance(step_orders, dict):
                step_orders.pop(pipeline_id, None)
            try:
                self._update_single_group_analysis_availability()
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
                    pipeline=pipeline_id,
                    event="complete",
                    extra={
                        "success": success,
                        "cancelled": cancelled,
                        "exports_ran": exports_ran,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "stats_pipeline_event_log_failed",
                    exc_info=True,
                    extra={"pipeline": pipeline_id.name, "error": str(exc)},
                )

    def closeEvent(self, event):  # type: ignore[override]
        """Handle the closeEvent step for the Stats workflow."""
        logger.debug(
            "stats_window_close_event",
            extra={
                "window_id": id(self),
                "project_dir": getattr(self, "project_dir", ""),
            },
        )
        super().closeEvent(event)

    def build_and_render_summary(self, pipeline_id: PipelineId) -> None:
        """Render the report worker's plain-language result surface."""

        report_payload = (
            self._native_step_store()
            .get(pipeline_id, {})
            .get(StepId.REPORT_BUNDLE)
        )
        if isinstance(report_payload, dict):
            bundle = report_payload.get("report_bundle")
            at_a_glance = str(
                report_payload.get("report_text")
                or getattr(bundle, "at_a_glance", "")
                or ""
            ).strip()
            self.summary_text.setPlainText(
                at_a_glance
                or (
                    "Standard FPVS Screening completed, but no plain-language "
                    "summary was generated."
                )
            )
            if bundle is not None:
                self._native_report_bundle = bundle
            return

        # Compatibility fallback for legacy individual-step actions.
        cfg = SummaryConfig(
            alpha=0.05,
            min_effect=0.50,
            max_bullets=3,
            z_threshold=1.64,
            p_col="p_fdr",
            effect_col="effect_size",
        )
        frames = self._build_summary_frames(pipeline_id)
        summary_text = build_summary_from_frames(frames, cfg)
        self._render_summary(summary_text)

    def export_pipeline_results(self, pipeline_id: PipelineId) -> bool:
        """Return report-worker export truth; never export on the GUI thread."""

        report_payload = (
            self._native_step_store()
            .get(pipeline_id, {})
            .get(StepId.REPORT_BUNDLE, {})
        )
        return bool(
            report_payload.get("exported")
            or report_payload.get("numeric_exported")
        )

    def get_step_config(
        self, pipeline_id: PipelineId, step_id: StepId
    ) -> tuple[dict, Callable[[dict], None]]:
        """Build GUI-neutral kwargs and result handlers for one native step."""

        options = self._native_options_for(pipeline_id)
        run_spec = options.build_run_spec()
        snapshots = getattr(self, "_native_state_by_pipeline", {})
        snapshot = snapshots.get(pipeline_id, {})
        selected_conditions = list(
            snapshot.get("selected_conditions")
            or self._get_selected_conditions()
        )
        outlier_payload = self._pipeline_outlier_config.get(
            pipeline_id, self._get_outlier_exclusion_payload()
        )
        qc_payload = self._pipeline_qc_config.get(
            pipeline_id,
            self._get_qc_exclusion_payload(),
        )
        if step_id is StepId.PREPARE_ANALYSIS:
            qc_state = {"report": None}
            self._pipeline_qc_state[pipeline_id] = qc_state
        else:
            qc_state = self._pipeline_qc_state.get(
                pipeline_id,
                {"report": None},
            )
        dv_policy = self._pipeline_dv_policy.get(
            pipeline_id,
            self._get_dv_policy_payload(),
        )

        def store(payload: dict) -> None:
            self._store_native_step_payload(pipeline_id, step_id, payload)

        if step_id is StepId.PREPARE_ANALYSIS:
            canonical_group_ids = (
                self._canonical_group_ids_for_subjects(
                    snapshot.get("canonical_group_ids")  # type: ignore[arg-type]
                )
                if pipeline_id is PipelineId.MULTI
                else {}
            )
            participant_display_labels = dict(
                snapshot.get("participant_display_labels") or {}
            )
            group_display_labels = dict(
                snapshot.get("group_display_labels") or {}
            )
            settings = {
                "analysis_scope": options.analysis_scope,
                "analysis_profile": options.profile.value,
                "correction": options.correction.value,
                "response_alternative": options.alternative.value,
                "strict_omnibus_family": options.strict_omnibus_family,
                "sensitivity": options.sensitivity_config(),
                "preliminary_coverage": snapshot.get(
                    "preliminary_coverage",
                    {},
                ),
                "project_name": self.project_title,
            }
            kwargs = {
                "subjects": list(self.subjects),
                "conditions": selected_conditions,
                "conditions_all": list(self.conditions),
                "subject_data": self.subject_data,
                "base_freq": self._current_base_freq,
                "rois": self.rois,
                "rois_all": self.rois,
                "dv_policy": dv_policy,
                "outlier_exclusion_enabled": outlier_payload.get(
                    "enabled",
                    True,
                ),
                "outlier_abs_limit": outlier_payload.get("abs_limit", 50.0),
                "qc_config": qc_payload,
                "qc_state": qc_state,
                "manual_excluded_pids": sorted(self.manual_excluded_pids),
                "project_root": str(self._project_path),
                "mode": options.mode.value,
                "analysis_scope": options.analysis_scope,
                "run_spec": run_spec,
                "canonical_group_ids": canonical_group_ids,
                "group_display_labels": group_display_labels,
                "participant_display_labels": participant_display_labels,
                "selected_group_pair": options.selected_group_pair,
                "settings": settings,
            }
            return kwargs, store

        if step_id is StepId.RM_ANOVA:
            if options.analysis_scope == "available_case":
                raise ValueError(
                    "RM-ANOVA is not available for available-case data. "
                    "Use the mixed-model step."
                )

            def handle_rm_anova(payload: dict) -> None:
                store(payload)
                self._apply_rm_anova_results(payload, update_text=False)

            return {}, handle_rm_anova

        if step_id is StepId.MIXED_MODEL:
            def handle_mixed_model(payload: dict) -> None:
                store(payload)
                self._apply_mixed_model_results(payload, update_text=False)

            return {"alpha": options.alpha}, handle_mixed_model

        if step_id is StepId.INTERACTION_POSTHOCS:
            if options.analysis_scope == "available_case":
                raise ValueError(
                    "Paired interaction post-hocs are not available for "
                    "available-case data."
                )

            def handle_posthocs(payload: dict) -> None:
                store(payload)
                self._apply_posthoc_results(payload, update_text=False)

            return {
                "alpha": options.alpha,
                "correction": options.correction.value,
                "direction": "both",
                "followup_provenance": run_spec.followup_provenance.value,
                "enforce_omnibus_gate": options.strict_omnibus_family,
                "family_scope": (
                    "direction"
                    if options.strict_omnibus_family
                    else "stratum"
                ),
            }, handle_posthocs

        if step_id is StepId.BASELINE_VS_ZERO:
            def handle_baseline(payload: dict) -> None:
                store(payload)
                self._apply_baseline_vs_zero_results(
                    payload,
                    update_text=False,
                )

            return {
                "alpha": options.alpha,
                "alternative": options.alternative.value,
                "correction": options.correction.value,
                "correction_scope": "global",
            }, handle_baseline

        if step_id is StepId.MULTIGROUP_MODEL:
            return {
                "reference_group_id": options.selected_group_pair[0],
            }, store

        if step_id is StepId.GROUP_CELL_COMPARISONS:
            return {
                "group_pair": options.selected_group_pair,
                "correction": options.correction.value,
                "alpha": options.alpha,
            }, store

        if step_id is StepId.SENSITIVITIES:
            return {"config": options.sensitivity_config()}, store

        if step_id is StepId.REPORT_BUNDLE:
            mode_label = (
                "Multi-Group"
                if pipeline_id is PipelineId.MULTI
                else "Single-Group"
            )
            export_filename = (
                f"Native {mode_label} Available-Case LMM Results.xlsx"
                if options.analysis_scope == "available_case"
                else f"Native {mode_label} Inference Results.xlsx"
            )
            export_path = (
                Path(self._ensure_results_dir())
                / export_filename
            )

            def handle_report(payload: dict) -> None:
                store(payload)
                path = str(payload.get("export_path") or "").strip()
                if path and (
                    payload.get("exported")
                    or payload.get("numeric_exported")
                ):
                    self._set_last_export_path(path)

            return {
                "config": {
                    "mode": options.mode.value,
                    "alpha": options.alpha,
                    "analysis_scope": options.analysis_scope,
                    "analysis_profile": options.profile.value,
                    "correction": options.correction.value,
                    "project_name": self.project_title,
                },
                "export_path": export_path,
            }, handle_report
        raise ValueError(f"Unsupported step configuration for {pipeline_id} / {step_id}")

    def _prompt_view_results(self, section: str, stats_folder: Path) -> None:
        """Handle the prompt view results step for the Stats workflow."""
        msg = QMessageBox(self)
        msg.setWindowTitle("Standard FPVS Screening Complete")
        msg.setText("Standard FPVS Screening is complete.\nView results?")
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
        self._set_detected_info(msg)

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        """Handle the on worker error step for the Stats workflow."""
        guidance = build_worker_error_guidance(msg)
        display_msg = guidance.message if guidance is not None else msg
        self.output_text.appendPlainText(f"Error: {display_msg}")
        section = "General"
        try:
            if self._controller.is_running(PipelineId.SINGLE):
                section = "Single"
        except Exception:
            section = "General"
        self.append_log(section, f"Worker error: {display_msg}", level="error")
        if guidance is not None:
            self.append_log(section, f"Technical detail: {msg}", level="error")
            self._set_status(guidance.status)
            try:
                QMessageBox.critical(self, guidance.title, guidance.message)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to display guided worker error dialog", exc_info=True)
        self._end_run()

    def _store_dv_metadata(self, pipeline_id: PipelineId, payload: dict) -> None:
        """Handle the store dv metadata step for the Stats workflow."""
        dv_meta = payload.get("dv_metadata")
        if isinstance(dv_meta, dict) and dv_meta:
            self._pipeline_dv_metadata[pipeline_id] = dv_meta

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
        self._store_dv_metadata(PipelineId.SINGLE, payload)
        self._store_run_report(PipelineId.SINGLE, payload)
        output_text = payload.get("output_text", "")
        if update_text:
            self.summary_text.append(output_text)
        self._update_export_buttons()
        return output_text

    @Slot(dict)
    def _on_rm_anova_finished(self, payload: dict) -> None:
        """Handle the on rm anova finished step for the Stats workflow."""
        self._apply_rm_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        """Handle the on mixed model finished step for the Stats workflow."""
        self._apply_mixed_model_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        """Handle the on posthoc finished step for the Stats workflow."""
        self._apply_posthoc_results(payload)
        self._end_run()

    # --------------------------- UI building ---------------------------

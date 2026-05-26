"""Export helpers for StatsWindow."""
from __future__ import annotations

from Tools.Stats.ui.stats_window_support import *  # noqa: F403

logger = logging.getLogger(__name__)


class StatsWindowExportsMixin:
    def export_results(self, kind: str, data, out_dir: str) -> list[Path]:
        """Handle the export results step for the Stats workflow."""
        mapping = {
            "anova": (export_rm_anova_results_to_excel, ANOVA_XLS),
            "lmm": (export_mixed_model_results_to_excel, LMM_XLS),
            "posthoc": (export_posthoc_results_to_excel, POSTHOC_XLS),
            "baseline_vs_zero": (export_baseline_vs_zero_results_to_excel, BASELINE_VS_ZERO_XLS),
        }
        func, fname = mapping[kind]

        if data is None:
            return []

        if kind == "anova" and isinstance(data, pd.DataFrame):
            log_rm_anova_p_minima(data)

        path = safe_export_call(
            func,
            data,
            out_dir,
            fname,
            log_func=self._set_status,
        )
        if kind == "anova":
            apply_rm_anova_pvalue_number_formats(path)
        if kind == "lmm" and isinstance(data, pd.DataFrame):
            apply_lmm_number_formats_and_metadata(path, lmm_df=data)
        if kind == "baseline_vs_zero":
            apply_baseline_vs_zero_number_formats(path)
        return [path]

    def _write_dv_metadata(self, out_dir: str, pipeline_id: PipelineId) -> None:
        """Handle the write dv metadata step for the Stats workflow."""
        dv_policy = self._pipeline_dv_policy.get(pipeline_id, self._get_dv_policy_payload())
        conditions = self._pipeline_conditions.get(pipeline_id, self._get_selected_conditions())
        base_freq = self._pipeline_base_freq.get(pipeline_id, self._current_base_freq)
        dv_meta = self._pipeline_dv_metadata.get(pipeline_id, {})
        payload = {
            "policy_name": dv_meta.get("policy_name", GROUP_SIGNIFICANT_POLICY_NAME),
            "fixed_harmonic_frequencies_hz": dv_meta.get(
                "fixed_harmonic_frequencies_hz",
                dv_policy.get("fixed_harmonic_frequencies_hz", ""),
            ),
            "fixed_harmonic_auto_exclude_base": dv_meta.get(
                "fixed_harmonic_auto_exclude_base",
                dv_policy.get("fixed_harmonic_auto_exclude_base", True),
            ),
            "base_frequency_hz": base_freq,
            "selected_conditions": list(conditions),
        }
        fixed_meta = dv_meta.get("fixed_predefined_harmonics") if isinstance(dv_meta, dict) else None
        if isinstance(fixed_meta, dict):
            payload["fixed_predefined_harmonics"] = fixed_meta
        group_meta = dv_meta.get("group_significant_harmonics") if isinstance(dv_meta, dict) else None
        if isinstance(group_meta, dict):
            payload["group_significant_harmonics"] = group_meta
        try:
            out_path = Path(out_dir) / "dv_metadata.json"
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DV metadata export.")

        rossion_meta = dv_meta.get("rossion_method") if isinstance(dv_meta, dict) else None
        if (
            not isinstance(rossion_meta, dict)
            and not isinstance(fixed_meta, dict)
            and not isinstance(group_meta, dict)
        ):
            return
        if not isinstance(rossion_meta, dict):
            rossion_meta = {}

        try:
            summary_rows = [
                {"key": "Primary DV method", "value": payload["policy_name"]},
                {"key": "Base frequency (Hz)", "value": payload["base_frequency_hz"]},
                {"key": "Selected conditions", "value": ", ".join(payload["selected_conditions"])},
            ]
            if isinstance(fixed_meta, dict):
                included = fixed_meta.get("fixed_harmonic_included_frequencies_hz", [])
                summary_rows.extend(
                    [
                        {
                            "key": "Selection rule",
                            "value": fixed_meta.get(
                                "harmonic_policy_label",
                                "Fixed predefined harmonic list",
                            ),
                        },
                        {
                            "key": "Included harmonics (Hz)",
                            "value": ", ".join(f"{float(freq):g}" for freq in included),
                        },
                        {
                            "key": "SNR used for statistics",
                            "value": fixed_meta.get("snr_used_for_statistics", False),
                        },
                    ]
                )
            elif isinstance(group_meta, dict):
                included = group_meta.get("selected_harmonics_hz", [])
                summary_rows.extend(
                    [
                        {
                            "key": "Selection rule",
                            "value": group_meta.get(
                                "harmonic_policy_label",
                                "Group-level significant harmonics",
                            ),
                        },
                        {
                            "key": "Included harmonics (Hz)",
                            "value": ", ".join(f"{float(freq):g}" for freq in included),
                        },
                        {
                            "key": "Selection scope",
                            "value": group_meta.get("selection_scope", ""),
                        },
                        {
                            "key": "Z threshold",
                            "value": group_meta.get("z_threshold", ""),
                        },
                        {
                            "key": "SNR used for statistics",
                            "value": group_meta.get("snr_used_for_statistics", False),
                        },
                    ]
                )
            elif isinstance(rossion_meta, dict):
                summary_rows.append(
                    {
                        "key": "Selection rule",
                        "value": "All non-base oddball harmonics with z > threshold",
                    }
                )
            summary_df = pd.DataFrame(summary_rows)

            union_map = rossion_meta.get("union_harmonics_by_roi", {}) or {}
            fallback_info = rossion_meta.get("fallback_info_by_roi", {}) or {}
            stop_meta = rossion_meta.get("stop_metadata_by_roi", {}) or {}
            roi_rows = []
            for roi_name, harmonics in union_map.items():
                fallback = fallback_info.get(roi_name, {})
                stop_info = stop_meta.get(roi_name, {})
                roi_rows.append(
                    {
                        "roi": roi_name,
                        "union_harmonics_hz": ", ".join(f"{freq:g}" for freq in harmonics) or "—",
                        "harmonic_count": len(harmonics),
                        "empty_list_policy": fallback.get("policy", payload.get("empty_list_policy")),
                        "fallback_used": bool(fallback.get("fallback_used", False)),
                        "fallback_harmonics_hz": ", ".join(
                            f"{freq:g}" for freq in fallback.get("fallback_harmonics", [])
                        )
                        or "—",
                        "stop_reason": stop_info.get("stop_reason", "—"),
                        "stop_fail_harmonics_hz": ", ".join(
                            f"{freq:g}" for freq in stop_info.get("fail_harmonics", []) or []
                        )
                        or "—",
                        "n_scanned": stop_info.get("n_scanned", "—"),
                    }
                )
            if isinstance(fixed_meta, dict):
                roi_rows = [
                    row
                    for row in fixed_meta.get("selection_rows", []) or []
                    if isinstance(row, dict)
                ]
            if isinstance(group_meta, dict):
                roi_rows = [
                    row
                    for row in group_meta.get("selection_rows", []) or []
                    if isinstance(row, dict)
                ]
            roi_df = pd.DataFrame(roi_rows)
            mean_z_table = rossion_meta.get("mean_z_table")
            if isinstance(group_meta, dict):
                z_map = group_meta.get("selection_z_by_harmonic", {}) or {}
                if isinstance(z_map, dict):
                    mean_z_table = pd.DataFrame(
                        [
                            {"harmonic_hz": float(freq), "z_score": float(z_score)}
                            for freq, z_score in z_map.items()
                        ]
                    )

            dv_path = Path(out_dir) / "Summed BCA DV Definition.xlsx"
            with pd.ExcelWriter(dv_path, engine="openpyxl") as writer:
                summary_df.to_excel(writer, sheet_name="DV Definition", index=False)
                roi_df.to_excel(writer, sheet_name="ROI Harmonics", index=False)
                if isinstance(mean_z_table, pd.DataFrame):
                    mean_z_table.to_excel(writer, sheet_name="Mean Z Table", index=False)
            self._set_status(f"Exported DV definition to {dv_path}")
            self._set_last_export_path(str(dv_path))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DV definition export.")

    def _ensure_results_dir(self) -> str:
        """Handle the ensure results dir step for the Stats workflow."""
        target = ensure_results_dir(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            results_subfolder_name=STATS_SUBFOLDER_NAME,
        )
        return str(target)

    def on_export_stats_ready_clicked(self) -> None:
        """Write the optional workbook for external statistics packages."""
        if not self._precheck(start_guard=True):
            return

        try:
            out_dir = self._ensure_results_dir()
            output_path = Path(out_dir) / STATS_READY_WORKBOOK_NAME
            if output_path.exists():
                self.append_log(
                    "General",
                    "Existing stats-ready workbook will be replaced only if "
                    f"the new export succeeds: {output_path}",
                )
            _, max_freq_raw = self._safe_settings_get("analysis", "bca_upper_limit", None)
            max_freq = float(max_freq_raw) if max_freq_raw not in (None, "") else None
        except Exception as exc:  # noqa: BLE001
            self._end_run()
            logger.exception("stats_ready_export_prepare_failed", exc_info=True)
            QMessageBox.critical(self, "Stats-Ready Export Failed", str(exc))
            return

        worker = StatsWorker(
            stats_worker_funcs.run_stats_ready_export,
            subjects=list(self.subjects),
            conditions=self._get_selected_conditions(),
            conditions_all=list(self.conditions),
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
            dv_policy=self._get_dv_policy_payload(),
            group_map=getattr(self, "_subject_group_map", {}),
            output_path=str(output_path),
            manual_excluded_pids=sorted(self.manual_excluded_pids),
            max_freq=max_freq,
            _op="stats_ready_export",
        )
        self._track_stats_ready_worker(worker)
        self._wire_and_start(worker, self._on_stats_ready_export_finished)

    def _track_stats_ready_worker(self, worker: StatsWorker) -> None:
        """Keep the export worker alive until Qt emits its terminal signal."""
        if not hasattr(self, "_active_workers"):
            self._active_workers = []
        self._active_workers.append(worker)

        def _release(*_args, w=worker):
            try:
                if w in self._active_workers:
                    self._active_workers.remove(w)
            except Exception:  # noqa: BLE001
                logger.exception("stats_ready_worker_release_failed")

        worker.signals.finished.connect(_release)
        worker.signals.error.connect(_release)

    def _on_stats_ready_export_finished(self, payload: dict) -> None:
        """Handle completion of the optional external-statistics export."""
        path = payload.get("path") if isinstance(payload, dict) else ""
        row_count = payload.get("row_count") if isinstance(payload, dict) else None
        sheet_names = payload.get("sheet_names") if isinstance(payload, dict) else []
        if not path:
            self.append_log(
                "General",
                "Stats-ready workbook export finished without a file path.",
                level="error",
            )
            self._set_status("Stats-ready workbook export failed.")
            self._end_run()
            return

        self._set_last_export_path(str(path))
        self.append_log(
            "General",
            f"Stats-ready workbook exported: {path}",
        )
        if sheet_names:
            self.append_log(
                "General",
                "  Sheets: " + ", ".join(str(name) for name in sheet_names),
            )
        self._set_status(f"Stats-ready workbook exported ({row_count} rows): {path}")
        self._end_run()

    def _export_single_pipeline(self) -> bool:
        """Handle the export single pipeline step for the Stats workflow."""
        section = "Single"
        exports = [
            ("anova", self.rm_anova_results_data, "RM-ANOVA"),
            ("lmm", self.mixed_model_results_data, "Mixed Model"),
            ("posthoc", self.posthoc_results_data, "Interaction Post-hocs"),
            ("baseline_vs_zero", self.baseline_vs_zero_results_payload, "Baseline vs Zero"),
        ]
        out_dir = self._ensure_results_dir()

        try:
            paths: list[Path] = []

            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(
                        section,
                        f"  • Skipping export for {label} (no data)",
                        level="warning",
                    )
                    continue

                result_paths = self.export_results(kind, data_obj, out_dir)

                if not result_paths:
                    self.append_log(
                        section,
                        f"  • Export produced no files for {label}",
                        level="error",
                    )
                    return False

                paths.extend(result_paths)

            exclusion_paths = self._export_outlier_exclusions(PipelineId.SINGLE, out_dir)
            if exclusion_paths:
                paths.extend(exclusion_paths)

            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
                self._write_dv_metadata(out_dir, PipelineId.SINGLE)

            return True

        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    def _export_outlier_exclusions(self, pipeline_id: PipelineId, out_dir: str) -> list[Path]:
        """Handle the export outlier exclusions step for the Stats workflow."""
        report = self._pipeline_run_reports.get(pipeline_id)
        if not isinstance(report, StatsRunReport):
            return []
        paths: list[Path] = []
        flagged_path = Path(out_dir) / "Flagged Participants.xlsx"
        export_flagged_participants_report(
            flagged_path, report.qc_report, report.dv_report, self._set_status
        )
        paths.append(flagged_path)

        excluded_path = Path(out_dir) / "Excluded Participants.xlsx"
        export_excluded_participants_report(
            excluded_path,
            manual_excluded=report.manual_excluded_pids,
            required_exclusions=report.required_exclusions,
            log_func=self._set_status,
        )
        paths.append(excluded_path)
        return paths

    # --------- worker signal handlers ---------

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
            "harmonic": (export_harmonic_results_to_excel, HARMONIC_XLS),
            "baseline_vs_zero": (export_baseline_vs_zero_results_to_excel, BASELINE_VS_ZERO_XLS),
        }
        func, fname = mapping[kind]

        # Special handling for harmonic exports
        if kind == "harmonic":
            grouped = group_harmonic_results(data)
            has_rows = any(
                roi_entries
                for roi_data in grouped.values()
                for roi_entries in roi_data.values()
            )
            if not has_rows:
                self._set_status("No harmonic check results to export.")
                return []

            def _adapter(_ignored, *, save_path, log_func):
                """Handle the adapter step for the Stats workflow."""
                export_harmonic_results_to_excel(
                    grouped,
                    save_path,
                    log_func,
                    metric=self._harmonic_config.metric,
                )

            path = safe_export_call(
                _adapter,
                None,
                out_dir,
                fname,
                log_func=self._set_status,
            )
            return [path]

        # Non-harmonic exports: if there's no data, nothing to export
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
        dv_variants = self._pipeline_dv_variants.get(pipeline_id, [])
        payload = {
            "policy_name": dv_meta.get("policy_name", dv_policy.get("name", LEGACY_POLICY_NAME)),
            "fixed_k": dv_meta.get("fixed_k", dv_policy.get("fixed_k", 5)),
            "exclude_harmonic1": dv_meta.get("exclude_harmonic1", dv_policy.get("exclude_harmonic1", True)),
            "exclude_base_harmonics": dv_meta.get(
                "exclude_base_harmonics", dv_policy.get("exclude_base_harmonics", True)
            ),
            "z_threshold": dv_meta.get("z_threshold", dv_policy.get("z_threshold", 1.64)),
            "empty_list_policy": dv_meta.get(
                "empty_list_policy", dv_policy.get("empty_list_policy", EMPTY_LIST_FALLBACK_FIXED_K)
            ),
            "base_frequency_hz": base_freq,
            "selected_conditions": list(conditions),
            "variant_methods": list(dv_variants),
        }
        try:
            out_path = Path(out_dir) / "dv_metadata.json"
            out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("Failed to write DV metadata export.")

        rossion_meta = dv_meta.get("rossion_method") if isinstance(dv_meta, dict) else None
        if not isinstance(rossion_meta, dict):
            return

        try:
            summary_rows = [
                {"key": "Primary DV method", "value": payload["policy_name"]},
                {"key": "Base frequency (Hz)", "value": payload["base_frequency_hz"]},
                {"key": "Z threshold", "value": payload.get("z_threshold")},
                {"key": "Empty list policy", "value": payload.get("empty_list_policy")},
                {"key": "Selected conditions", "value": ", ".join(payload["selected_conditions"])},
                {
                    "key": "DV variants (exported)",
                    "value": ", ".join(payload.get("variant_methods", [])) or "None",
                },
            ]
            if isinstance(rossion_meta, dict):
                summary_rows.append(
                    {
                        "key": "Stop rule",
                        "value": "Stop after 2 consecutive non-significant harmonics",
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
            roi_df = pd.DataFrame(roi_rows)
            mean_z_table = rossion_meta.get("mean_z_table")

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

    def _open_results_folder(self) -> None:
        """Handle the open results folder step for the Stats workflow."""
        out_dir = self._ensure_results_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _export_single_pipeline(self) -> bool:
        """Handle the export single pipeline step for the Stats workflow."""
        section = "Single"
        exports = [
            ("anova", self.rm_anova_results_data, "RM-ANOVA"),
            ("lmm", self.mixed_model_results_data, "Mixed Model"),
            ("posthoc", self.posthoc_results_data, "Interaction Post-hocs"),
            ("baseline_vs_zero", self.baseline_vs_zero_results_payload, "Baseline vs Zero"),
            ("harmonic", self._harmonic_results.get(PipelineId.SINGLE), "Harmonic Check"),
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
                    # Only harmonic is allowed to “legitimately” export nothing
                    if kind == "harmonic":
                        self.append_log(
                            section,
                            f"  • Skipping export for {label} (no significant harmonics)",
                            level="warning",
                        )
                        continue

                    self.append_log(
                        section,
                        f"  • Export produced no files for {label}",
                        level="error",
                    )
                    return False

                paths.extend(result_paths)

            dv_variant_paths = self._export_dv_variants(PipelineId.SINGLE, out_dir)
            if dv_variant_paths:
                paths.extend(dv_variant_paths)

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

    def _export_dv_variants(self, pipeline_id: PipelineId, out_dir: str) -> list[Path]:
        """Handle the export dv variants step for the Stats workflow."""
        selected = self._pipeline_dv_variants.get(pipeline_id, [])
        if not selected:
            return []

        payload = self._pipeline_dv_variant_payloads.get(pipeline_id, {})
        if not payload:
            section = self._section_label(pipeline_id)
            self.append_log(
                section,
                "  • Skipping DV variants export (no variant payload).",
                level="warning",
            )
            return []

        primary_df = payload.get("primary_df")
        variant_dfs = payload.get("variant_dfs", {}) or {}
        summary_df = payload.get("summary_df")
        errors = payload.get("errors", []) or []
        primary_name = payload.get(
            "primary_name", self._pipeline_dv_policy.get(pipeline_id, {}).get("name", "")
        )

        if not isinstance(primary_df, pd.DataFrame):
            section = self._section_label(pipeline_id)
            self.append_log(
                section,
                "  • DV variants export skipped (primary DV table missing).",
                level="error",
            )
            return []

        save_path = Path(out_dir) / "DV Variants.xlsx"
        export_dv_variants_workbook(
            save_path=save_path,
            primary_name=str(primary_name),
            primary_df=primary_df,
            variant_dfs=variant_dfs,
            summary_df=summary_df if isinstance(summary_df, pd.DataFrame) else pd.DataFrame(),
            errors=errors if isinstance(errors, list) else [],
            log_func=self._set_status,
        )
        return [save_path]

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

"""GUI-side processing run workflow helpers."""

from __future__ import annotations

import logging
import os
import queue
from pathlib import Path
from typing import Any, Callable

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from Main_App.diagnostics.audit import format_audit_summary, write_audit_json
from Main_App.gui.post_export_workflows import excel_snapshot
from Main_App.io.load_utils import (
    BDF_RECORDING_NOT_STARTED_REASON,
    format_bdf_recording_not_started_message,
)
from Main_App.processing.processing_ledger import (
    MISSING_EXPECTED_OUTPUTS_WARNING,
    ProcessingPlan,
    classify_processing_inputs,
    clean_managed_excel_root,
    clean_participant_outputs,
    load_ledger,
    output_group_folder_by_file,
    record_processing_results,
    with_processing_choice,
)
from Main_App.processing.qc_summary_export import export_processing_qc_summary
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings
from Main_App.processing.raw_channel_qc import RAW_CHANNEL_QC_EXCLUSION_REASON
from Main_App.workers.mp_env import (
    compute_effective_max_workers,
    get_ram_tier_recommendation,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _format_timing_summary(result: dict) -> str | None:
    timings = result.get("timings_ms")
    if not isinstance(timings, dict) or not timings:
        return None

    file_value = result.get("file") or "unknown"
    file_name = Path(str(file_value)).name
    cache_status = result.get("preproc_cache_status")
    preferred_order = (
        "cache_lookup",
        "load",
        "preproc_audit_before",
        "preprocessing",
        "cache_store",
        "events",
        "epochs",
        "export",
        "preproc_audit_after",
        "cleanup",
    )
    parts: list[str] = []
    for key in preferred_order:
        value = timings.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{key}={int(value)}ms")

    for key, value in sorted(timings.items()):
        if key in preferred_order or not isinstance(value, (int, float)):
            continue
        parts.append(f"{key}={int(value)}ms")

    if not parts:
        return None

    cache_part = f" cache={cache_status}" if cache_status else ""
    return f"[TIMING] {file_name}{cache_part} " + " ".join(parts)


def _format_exclusion_reason(result: dict) -> str:
    reason = str(result.get("reason") or "excluded")
    if reason == BDF_RECORDING_NOT_STARTED_REASON:
        return "Recording was not started in BioSemi; the BDF is header-only/approximately 19 KB."

    qc_payload = result.get("raw_channel_qc")
    if reason == RAW_CHANNEL_QC_EXCLUSION_REASON and isinstance(qc_payload, dict):
        n_bad = qc_payload.get("n_bad_channels")
        n_channels = qc_payload.get("n_channels")
        left_bad = qc_payload.get("left_bad")
        left_total = qc_payload.get("left_total")
        right_bad = qc_payload.get("right_bad")
        right_total = qc_payload.get("right_total")
        midline_bad = qc_payload.get("midline_bad")
        midline_total = qc_payload.get("midline_total")
        rules = ", ".join(str(rule) for rule in qc_payload.get("triggered_rules", []) or [])
        rules_text = f" Triggered rule(s): {rules}." if rules else ""
        cluster_size = qc_payload.get("largest_bad_cluster_size")
        cluster_channels = ", ".join(
            str(channel)
            for channel in qc_payload.get("largest_bad_cluster_channels", []) or []
        )
        cluster_text = ""
        if cluster_size and cluster_channels:
            cluster_text = f" Largest cluster: {cluster_size} ({cluster_channels})."
        return (
            "Raw channel-health QC failed: "
            f"{n_bad}/{n_channels} scalp EEG channels were flat, very low amplitude, "
            "extreme high-amplitude outliers, or spatially inconsistent "
            f"(left {left_bad}/{left_total}, right {right_bad}/{right_total}, "
            f"midline {midline_bad}/{midline_total}).{cluster_text}{rules_text}"
        )

    message = str(result.get("message") or "").strip()
    return message or reason.replace("_", " ")


def _run_failed_results_from_ledger(host: Any, plan: ProcessingPlan) -> list[dict]:
    try:
        ledger = load_ledger(Path(host.currentProject.project_root))
    except (AttributeError, OSError, TypeError, ValueError):
        logger.exception("Failed to load processing ledger for failed-run summary.")
        return []
    entries = ledger.get("entries")
    if not isinstance(entries, dict):
        return []

    failed_results: list[dict] = []
    run_paths = {path.resolve() for path in plan.run_files}
    for state in plan.states:
        if state.info.path.resolve() not in run_paths:
            continue
        entry = entries.get(state.participant_id)
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "").casefold()
        if status not in {"failed", "incomplete"}:
            continue
        reason = str(entry.get("failure_reason") or status)
        message = str(
            entry.get("failure_message")
            or "Processing did not complete for this participant."
        )
        missing_outputs = entry.get("missing_outputs")
        if isinstance(missing_outputs, list) and missing_outputs:
            message = f"{message} Missing expected output(s): {len(missing_outputs)}."
        failed_results.append(
            {
                "status": status,
                "file": str(state.info.path),
                "reason": reason,
                "message": message,
            }
        )
    return failed_results


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list | tuple):
        return [str(item) for item in value if str(item).strip()]
    return []


def _run_condition_warning_results_from_ledger(host: Any, plan: ProcessingPlan) -> list[dict]:
    try:
        ledger = load_ledger(Path(host.currentProject.project_root))
    except (AttributeError, OSError, TypeError, ValueError):
        logger.exception("Failed to load processing ledger for condition-warning summary.")
        return []
    entries = ledger.get("entries")
    if not isinstance(entries, dict):
        return []

    warning_results: list[dict] = []
    for state in plan.states:
        entry = entries.get(state.participant_id)
        if not isinstance(entry, dict):
            continue
        has_warning = (
            str(entry.get("completion_warning") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
            or str(entry.get("failure_reason") or "") == MISSING_EXPECTED_OUTPUTS_WARNING
            or str(entry.get("condition_completeness") or "").casefold() == "partial"
        )
        if not has_warning:
            continue
        labels = _string_list(entry.get("missing_condition_labels"))
        missing_outputs = _string_list(entry.get("missing_outputs"))
        if labels:
            missing_text = ", ".join(labels)
        elif missing_outputs:
            missing_text = f"{len(missing_outputs)} expected condition output(s)"
        else:
            missing_text = "one or more expected condition outputs"
        warning_results.append(
            {
                "status": "condition_warning",
                "file": str(state.info.path),
                "reason": MISSING_EXPECTED_OUTPUTS_WARNING,
                "message": (
                    f"Missing condition output(s): {missing_text}. Available condition "
                    "outputs remain included in the processed dataset."
                ),
            }
        )
    return warning_results


def _build_condition_warning_popup_text(warning_results: list[dict]) -> tuple[str, str, str]:
    count = len(warning_results)
    lead = (
        f"{count} participant(s) are missing one or more expected condition outputs. "
        "They remain included for the condition data that were successfully processed. "
        "The raw BDF files were not altered."
    )
    reason_lines: list[str] = []
    for result in warning_results:
        file_value = result.get("file") or "unknown"
        file_name = Path(str(file_value)).name
        reason_lines.append(f"- {file_name}: {result.get('message')}")

    if len(reason_lines) <= 8:
        informative = "\n".join(reason_lines)
        detailed = ""
    else:
        informative = "\n".join(reason_lines[:8]) + f"\n...and {len(reason_lines) - 8} more."
        detailed = "\n".join(reason_lines)
    return lead, informative, detailed


def _show_condition_warning_popup(host: Any, warning_results: list[dict]) -> None:
    if not warning_results:
        return
    lead, informative, detailed = _build_condition_warning_popup_text(warning_results)
    box = QMessageBox(host)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Processing QC Warnings")
    box.setText(lead)
    box.setInformativeText(informative)
    if detailed:
        box.setDetailedText(detailed)
    box.exec()


def _build_exclusion_popup_text(excluded_results: list[dict]) -> tuple[str, str, str]:
    count = len(excluded_results)
    lead = (
        f"{count} raw file(s) were excluded or left incomplete during processing. "
        "The final dataset of processed files excludes these files. "
        "The raw BDF files were not altered."
    )
    reason_lines: list[str] = []
    for result in excluded_results:
        file_value = result.get("file") or "unknown"
        file_name = Path(str(file_value)).name
        reason_lines.append(f"- {file_name}: {_format_exclusion_reason(result)}")

    if len(reason_lines) <= 8:
        informative = "\n".join(reason_lines)
        detailed = ""
    else:
        informative = "\n".join(reason_lines[:8]) + f"\n...and {len(reason_lines) - 8} more."
        detailed = "\n".join(reason_lines)
    return lead, informative, detailed


def _show_exclusion_summary_popup(host: Any, excluded_results: list[dict]) -> None:
    if not excluded_results:
        return
    lead, informative, detailed = _build_exclusion_popup_text(excluded_results)
    box = QMessageBox(host)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Processing Exclusions")
    box.setText(lead)
    box.setInformativeText(informative)
    if detailed:
        box.setDetailedText(detailed)
    box.exec()


def _choose_processing_plan(
    host: Any,
    plan: ProcessingPlan,
    *,
    is_single_ui: bool,
) -> ProcessingPlan | None:
    if not plan.states:
        return plan

    has_prior_outputs = any(state.status != "new" for state in plan.states)
    has_settings_change = any(state.status == "changed_settings" for state in plan.states)

    if is_single_ui and len(plan.states) == 1 and plan.states[0].status == "completed":
        state = plan.states[0]
        message = (
            f"{state.participant_id} already has completed outputs for the "
            "current project settings."
        )
        box = QMessageBox(host)
        box.setWindowTitle("File Already Processed")
        box.setText(message)
        skip_button = box.addButton("Skip", QMessageBox.AcceptRole)
        reprocess_button = box.addButton("Reprocess This File", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.setDefaultButton(skip_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked == reprocess_button:
            return with_processing_choice(plan, "reprocess_this_file")
        return None

    if not has_prior_outputs:
        return plan

    total = len(plan.states)
    completed = plan.completed_count
    new_or_changed = len(plan.incremental_files)
    if is_single_ui:
        return with_processing_choice(plan, "incremental")

    if has_settings_change:
        detail = (
            "Processing settings changed since a previous run. Reprocessing all "
            "files is recommended because mixed settings can invalidate group "
            "comparisons."
        )
    else:
        detail = (
            "Incremental processing will run only files that are new, changed, "
            "incomplete, or missing expected Excel outputs."
        )

    box = QMessageBox(host)
    box.setWindowTitle("Choose Processing Scope")
    box.setText(
        "FPVS Toolbox found "
        f"{total} BDF file(s) in this project.\n\n"
        f"{completed} file(s) already have completed outputs.\n"
        f"{new_or_changed} file(s) need processing.\n\n"
        f"{detail}"
    )
    incremental_button = box.addButton(
        "Process New or Changed Only",
        QMessageBox.AcceptRole,
    )
    reprocess_button = box.addButton("Reprocess All Files", QMessageBox.DestructiveRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(reprocess_button if has_settings_change else incremental_button)
    box.exec()
    clicked = box.clickedButton()
    if clicked == reprocess_button:
        return with_processing_choice(plan, "reprocess_all")
    if clicked == incremental_button:
        return with_processing_choice(plan, "incremental")
    return None


def _prepare_excel_outputs_for_plan(host: Any, plan: ProcessingPlan) -> bool:
    if plan.choice == "reprocess_all":
        excel_root = Path(host.currentProject.subfolders["excel"])
        reply = QMessageBox.warning(
            host,
            "Reprocess All Files",
            "Reprocess All will delete and recreate generated Excel outputs inside:\n\n"
            f"{excel_root}\n\n"
            "Raw data and files outside this managed Excel folder will not be touched.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return False
        clean_managed_excel_root(host.currentProject)
        host.log(f"Cleared managed Excel output folder: {excel_root}")
        return True

    deleted = clean_participant_outputs(host.currentProject, plan)
    if deleted:
        host.log(f"Cleared {len(deleted)} stale participant Excel output file(s).")
    return True


def stop_processing(host: Any) -> None:
    """Cooperatively request cancellation for a process-mode run."""
    if not getattr(host, "_run_active", False):
        host.log("Stop requested but no processing run is active.", level=logging.INFO)
        return

    if host._cancel_requested:
        host.log("Cancellation already requested; ignoring Stop click.", level=logging.INFO)
        return

    mp = getattr(host, "_mp", None)
    if mp is None:
        QMessageBox.information(
            host,
            "Stop Processing",
            "Stopping an in-progress run requires the PySide6 process runner.\n"
            "This run will finish normally.",
        )
        host.log("Stop requested but no MpRunnerBridge instance is active.", level=logging.WARNING)
        return

    cancel_callable = getattr(mp, "cancel", None)
    if not callable(cancel_callable):
        host.log(
            "MpRunnerBridge.cancel() is unavailable; processing will finish normally.",
            level=logging.WARNING,
        )
        return

    host._cancel_requested = True
    if hasattr(host, "btn_start") and host.btn_start:
        try:
            host.btn_start.setText("Stopping…")
            host.btn_start.setEnabled(False)
        except Exception:
            pass

    host.log("Stop requested; attempting to cancel processing…", level=logging.INFO)
    try:
        cancel_callable()
    except Exception as exc:
        host._cancel_requested = False
        if hasattr(host, "btn_start") and host.btn_start:
            try:
                host.btn_start.setText("Stop Processing")
                host.btn_start.setEnabled(True)
            except Exception:
                pass
        host.log(
            f"Failed to request cancel from MpRunnerBridge: {exc}",
            level=logging.ERROR,
        )
        QMessageBox.warning(
            host,
            "Stop Processing",
            "Unable to halt processing automatically. Please allow the current run to finish.",
        )


def start_processing(host: Any, *, log: logging.Logger = logger) -> None:
    """
    Begin a processing run through the PySide6 process runner.

    Single-file runs use the same runner with one worker.
    """
    if not host._start_guard.start():
        QMessageBox.warning(host, "Busy", "Processing already started")
        return

    host._last_job_success = False
    host._cancel_requested = False
    host._run_active = False
    host._processing_plan = None
    host._processing_user_choice = None
    host._snr_tick = 0
    host._run_had_successful_export = False
    host._run_excel_output_root = (
        host.save_folder_path.get()
        if hasattr(host.save_folder_path, "get")
        else str(getattr(host, "save_folder_path", "") or "")
    )
    host._run_excel_snapshot_before = excel_snapshot(host._run_excel_output_root)

    if not host._processing_timer.isActive():
        host._processing_timer.start(host._POLL_INTERVAL_MS)

    try:
        if not getattr(host, "_n_jobs_ignored_logged", False):
            log.debug(
                "n_jobs is ignored in this version; using parallel_mode=%s",
                host.parallel_mode,
            )
            host._n_jobs_ignored_logged = True

        project_max_workers: int | None = None
        allow_ram_cap_bypass = False
        override_source = "none"
        if getattr(host, "currentProject", None):
            opts = getattr(host.currentProject, "options", {})
            host.parallel_mode = opts.get(
                "parallel_mode", getattr(host, "parallel_mode", "process")
            )

            normalized_preproc = normalize_preprocessing_settings(
                getattr(host.currentProject, "preprocessing", {})
            )
            raw_override = normalized_preproc.get("max_parallel_workers_override")
            if raw_override is not None:
                try:
                    override_value = int(raw_override)
                except (TypeError, ValueError):
                    log.warning(
                        "Preprocessing max_parallel_workers_override must be an integer; received %r",
                        raw_override,
                    )
                else:
                    if override_value > 0:
                        project_max_workers = override_value
                        allow_ram_cap_bypass = True
                        override_source = "preprocessing.max_parallel_workers_override"
                    else:
                        allow_ram_cap_bypass = False

            if project_max_workers is None:
                raw_override = opts.get("max_workers")
                if raw_override is not None:
                    try:
                        override_value = int(raw_override)
                    except (TypeError, ValueError):
                        log.warning(
                            "Project max_workers override must be an integer; received %r",
                            raw_override,
                        )
                    else:
                        if override_value > 0:
                            project_max_workers = override_value
                            override_source = "options.max_workers"
                        else:
                            log.warning(
                                "Project max_workers override must be positive; received %r",
                                raw_override,
                            )

        total_ram_bytes = psutil.virtual_memory().total
        cpu_count = os.cpu_count() or 1
        ram_tier, ram_cap, total_ram_gib = get_ram_tier_recommendation(total_ram_bytes)

        effective_max_workers = compute_effective_max_workers(
            total_ram_bytes=total_ram_bytes,
            cpu_count=cpu_count,
            project_max_workers=project_max_workers,
            allow_ram_cap_bypass=allow_ram_cap_bypass,
        )
        if (
            project_max_workers is not None
            and effective_max_workers != project_max_workers
        ):
            log.warning(
                "Clamped project max_workers from %s to %s (cpu_count=%s, ram_tier=%s, ram_cap=%s, ram_cap_bypass=%s)",
                project_max_workers,
                effective_max_workers,
                cpu_count,
                ram_tier,
                ram_cap if ram_cap is not None else "none",
                allow_ram_cap_bypass,
            )

        log.info(
            "Resolved max_workers=%s (cpu_count=%s, ram_gib=%.1f, ram_tier=%s, ram_cap=%s, project_override=%s, override_source=%s, ram_cap_bypass=%s)",
            effective_max_workers,
            cpu_count,
            total_ram_gib,
            ram_tier,
            ram_cap if ram_cap is not None else "none",
            project_max_workers,
            override_source,
            allow_ram_cap_bypass,
        )
        host.max_workers = effective_max_workers

        is_single_ui = False
        if hasattr(host, "file_mode"):
            try:
                is_single_ui = host.file_mode.get() == "Single"
            except Exception:
                is_single_ui = False
        if host.parallel_mode != "process" and not is_single_ui:
            log.info(
                "Routing parallel_mode=%r through PySide6 process runner.",
                host.parallel_mode,
            )

        if host._processing_timer.isActive():
            host._processing_timer.stop()

        if not host._validate_inputs():
            _reset_failed_start(host)
            return

        settings = host.validated_params.copy()
        event_map = settings.pop("event_id_map", {})
        raw_file_infos = list(getattr(host, "_processing_raw_file_infos", []) or [])
        plan = classify_processing_inputs(
            host.currentProject,
            raw_file_infos,
            settings,
            event_map,
        )
        chosen_plan = _choose_processing_plan(host, plan, is_single_ui=is_single_ui)
        if chosen_plan is None:
            _reset_failed_start(host)
            return
        if not chosen_plan.run_files:
            host.log("No new or changed files need processing.", level=logging.INFO)
            _reset_failed_start(host)
            return
        if not _prepare_excel_outputs_for_plan(host, chosen_plan):
            _reset_failed_start(host)
            return
        host._processing_plan = chosen_plan
        host._processing_run_mode = "Single" if is_single_ui else "Batch"
        host._processing_user_choice = chosen_plan.choice
        host.data_paths = [str(path) for path in chosen_plan.run_files]

        host._set_controls_enabled(False)
        if hasattr(host, "progress_bar"):
            host.progress_bar.setRange(0, 100)
            host.progress_bar.setValue(0)
        host._processed_count = 0
        host.busy = True

        from Main_App.workers.mp_runner_bridge import MpRunnerBridge

        project_root = Path(host.currentProject.project_root)
        save_folder = Path(host.save_folder_path.get())
        files = [Path(p) for p in host.data_paths]
        host._max_progress = len(files)
        if hasattr(host, "_prepare_processing_activity"):
            host._prepare_processing_activity(files)
        group_folder_by_file = output_group_folder_by_file(
            host.currentProject,
            raw_file_infos,
        )
        if group_folder_by_file:
            settings["_fpvs_output_group_by_file"] = group_folder_by_file
        if raw_file_infos:
            settings["_fpvs_participant_id_by_file"] = {
                str(info.path.resolve()): info.subject_id
                for info in raw_file_infos
            }

        host._mp = MpRunnerBridge(host)
        host._mp.validated_fingerprint = getattr(
            host, "_preproc_fingerprint_validated", None
        )

        def _handle_progress(pct: int) -> None:
            if hasattr(host, "_animate_progress_to"):
                host._animate_progress_to(pct / 100.0)
            else:
                host.progress_bar.setValue(int(pct))
            if hasattr(host, "_update_processing_progress"):
                host._update_processing_progress(int(pct))

        host._mp.progress.connect(_handle_progress)
        if hasattr(host._mp, "file_status") and hasattr(host, "_on_processing_file_status"):
            host._mp.file_status.connect(host._on_processing_file_status)
        host._mp.error.connect(host._on_processing_error)
        host._mp.finished.connect(host._on_processing_finished)

        host._mp.start(
            project_root=project_root,
            data_files=files,
            settings=settings,
            event_map=event_map,
            save_folder=save_folder,
            max_workers=1 if is_single_ui else host.max_workers,
        )
        host._run_active = True
        if hasattr(host, "_busy_start"):
            host._busy_start()
        if hasattr(host, "btn_start"):
            host.btn_start.setText("Stop Processing")
            host.btn_start.setEnabled(True)

    except Exception as exc:
        log.exception(exc)
        QMessageBox.critical(host, "Processing Error", str(exc))
        _reset_failed_start(host)


def _reset_failed_start(host: Any) -> None:
    try:
        if hasattr(host, "_busy_stop"):
            host._busy_stop()
    except Exception:
        pass
    host._run_active = False
    host._cancel_requested = False
    host._start_guard.end()
    if hasattr(host, "btn_start"):
        host.btn_start.setText("Start Processing")
        host._update_start_enabled()


def on_processing_finished(host: Any, payload: dict | None = None) -> None:
    results: list[dict] = []
    excluded_results: list[dict] = []
    cancelled = False
    interrupted_files: list[str] = []
    if isinstance(payload, dict):
        results = payload.get("results") or []
        excluded_results = payload.get("excluded") or []
        cancelled = bool(payload.get("cancelled", False))
        interrupted_files = [str(file_path) for file_path in payload.get("interrupted_files") or []]

    try:
        debug_on = host.settings.debug_enabled()
    except Exception:
        debug_on = False

    params_snapshot = dict(getattr(host, "validated_params", {}))
    audit_root: Path | None = None
    if debug_on and hasattr(host, "save_folder_path"):
        try:
            save_root = Path(host.save_folder_path.get()).resolve()
            audit_root = save_root.parent / "audit"
        except Exception:
            audit_root = None

    total_rejected = 0
    files_with_reject_info = 0

    for result in results:
        audit = result.get("audit") or {}
        problems = result.get("problems") or []
        line, is_warning = format_audit_summary(audit, problems)
        host.log(line, level=logging.WARNING if is_warning else logging.INFO)
        timing_line = _format_timing_summary(result)
        if timing_line:
            host.log(timing_line, level=logging.INFO)

        if debug_on and audit_root and audit:
            try:
                raw_file = audit.get("file") or result.get("file", "")
                basename = Path(raw_file).stem if raw_file else "unknown"
                write_audit_json(
                    audit_root,
                    basename=basename,
                    audit=audit,
                    params=params_snapshot,
                    problems=problems,
                )
            except Exception as exc:
                host.log(f"Audit JSON write failed: {exc}", level=logging.WARNING)

        n_rejected = audit.get("n_rejected")
        if isinstance(n_rejected, (int, float)):
            total_rejected += int(n_rejected)
            files_with_reject_info += 1

    if files_with_reject_info:
        avg_rejected = total_rejected / files_with_reject_info
        host.log(
            f"[AUDIT] Average number of channels rejected per file: "
            f"{avg_rejected:.2f} (n={files_with_reject_info}, total={total_rejected})"
        )

    if excluded_results:
        excluded_names = [
            Path(str(result.get("file") or "")).name
            for result in excluded_results
            if result.get("file")
        ]
        reasons = {str(result.get("reason") or "") for result in excluded_results}
        if reasons == {BDF_RECORDING_NOT_STARTED_REASON}:
            host.log(
                format_bdf_recording_not_started_message(excluded_names),
                level=logging.WARNING,
            )
        else:
            host.log(
                f"{len(excluded_results)} file(s) were excluded from processing and analysis. "
                "Check the processing log for details.",
                level=logging.WARNING,
            )
        for result in excluded_results:
            file_value = result.get("file") or "unknown"
            host.log(
                f"Excluded {Path(str(file_value)).name}: {_format_exclusion_reason(result)}",
                level=logging.WARNING,
            )

    plan = getattr(host, "_processing_plan", None)
    failed_run_results: list[dict] = []
    condition_warning_results: list[dict] = []
    if plan is not None:
        try:
            record_processing_results(
                host.currentProject,
                plan,
                [*results, *excluded_results],
                run_mode=str(getattr(host, "_processing_run_mode", "Batch")),
                user_choice=str(getattr(host, "_processing_user_choice", "incremental")),
                cancelled=cancelled,
            )
        except Exception as exc:
            logger.exception("Failed to update processing ledger.")
            host.log(f"Processing ledger update failed: {exc}", level=logging.WARNING)
        else:
            failed_run_results = _run_failed_results_from_ledger(host, plan)
            condition_warning_results = _run_condition_warning_results_from_ledger(
                host,
                plan,
            )
            if failed_run_results:
                host.log(
                    f"{len(failed_run_results)} file(s) did not produce a complete final "
                    "processed dataset and were excluded from downstream analysis.",
                    level=logging.WARNING,
                )
                for result in failed_run_results:
                    file_value = result.get("file") or "unknown"
                    host.log(
                        f"Incomplete {Path(str(file_value)).name}: {_format_exclusion_reason(result)}",
                        level=logging.WARNING,
                    )
            if condition_warning_results:
                host.log(
                    f"{len(condition_warning_results)} participant(s) are missing one or "
                    "more expected condition outputs. Available condition data remain "
                    "included in the processed dataset.",
                    level=logging.WARNING,
                )
                for result in condition_warning_results:
                    file_value = result.get("file") or "unknown"
                    host.log(
                        f"Condition warning {Path(str(file_value)).name}: "
                        f"{result.get('message')}",
                        level=logging.WARNING,
                    )
            try:
                qc_summary_path = export_processing_qc_summary(
                    host.currentProject,
                    plan,
                    [*results, *excluded_results],
                )
                host.log(f"Processing QC summary saved: {qc_summary_path}", level=logging.INFO)
            except Exception as exc:
                logger.exception("Failed to write processing QC summary workbook.")
                host.log(f"Processing QC summary export failed: {exc}", level=logging.WARNING)

    _show_exclusion_summary_popup(host, [*excluded_results, *failed_run_results])
    _show_condition_warning_popup(host, condition_warning_results)

    host._busy_stop()
    success = not cancelled
    host._finalize_processing(success, cancelled=cancelled)
    if success and not cancelled:
        try:
            from Main_App.gui.processing_snr_qc_workflow import (
                start_automatic_snr_qc_after_processing,
            )

            start_automatic_snr_qc_after_processing(host)
        except Exception as exc:
            logger.exception("Automatic SNR plot/QC launch failed.")
            host.log(
                f"Automatic SNR plot/QC could not start: {exc}",
                level=logging.WARNING,
            )
    if cancelled:
        host.log("Processing run cancelled by user.", level=logging.INFO)
        if interrupted_files:
            host.log(
                "Stopped before "
                f"{len(interrupted_files)} queued or active file(s) completed; "
                "rerun those files before using any partial outputs.",
                level=logging.WARNING,
            )


def on_processing_error(host: Any, message: str) -> None:
    """
    Process-mode error handler wired to MpRunnerBridge.error.

    If the user has already requested cancellation, treat the error as part of
    the cancelled run and do not show the GUI error dialog.
    """
    host._busy_stop()

    if getattr(host, "_cancel_requested", False):
        host.log(
            f"Processing error received after cancellation request; "
            f"suppressing dialog. Details: {message}",
            level=logging.INFO,
        )
        host._finalize_processing(False, cancelled=True)
        return

    QMessageBox.critical(host, "Processing Error", message)
    host._finalize_processing(False)


def periodic_queue_check(host: Any) -> None:
    if not host._run_active:
        return

    processed = 0
    while processed < 50:
        try:
            msg = host.gui_queue.get_nowait()
        except queue.Empty:
            break

        processed += 1
        msg_type = msg.get("type")
        if msg_type == "log":
            host.log(msg.get("message", ""))
        elif msg_type == "progress":
            host._processed_count = msg["value"]
            frac = msg["value"] / host._max_progress if host._max_progress else 0
            host._animate_progress_to(frac)
        elif msg_type == "post":
            fname = msg["file"]
            epochs_dict = msg["epochs_dict"]
            labels = msg["labels"]
            host._start_post_worker(fname, epochs_dict, labels)
        elif msg_type == "error":
            host.log("!!! THREAD ERROR: " + msg["message"])
            if tb := msg.get("traceback"):
                host.log(tb)
            host._finalize_processing(False)
            return
        elif msg_type == "done":
            if host._post_worker or host._post_backlog:
                host._pending_finalize = True
            else:
                host._finalize_processing(True)
            return

    delay = host._BURST_FOLLOWUP_MS if processed else host._IDLE_FOLLOWUP_MS
    QTimer.singleShot(delay, host._periodic_queue_check)


def finalize_processing(
    host: Any,
    *args: Any,
    parent_finalize: Callable[[bool], None],
    **kwargs: Any,
) -> None:
    """
    Common finalization hook for process and compatibility queue paths.

    Ensures flags, spinner, progress bar, and Start/Stop button state are reset.
    When ``cancelled=True`` is passed, completion/error dialogs are suppressed and
    the run is logged as user-cancelled rather than failed.
    """
    cancelled = bool(kwargs.pop("cancelled", False))

    success = True
    if args and isinstance(args[0], bool):
        success = args[0]
    if "success" in kwargs and isinstance(kwargs["success"], bool):
        success = kwargs["success"]
    if cancelled:
        success = False

    host._run_active = False
    try:
        host._start_guard.end()
    except Exception:
        pass

    try:
        host._busy_stop()
    except Exception:
        pass

    try:
        host._set_controls_enabled(True)
    except Exception as exc:
        host.log(
            f"_set_controls_enabled(True) failed during finalize: {exc}",
            level=logging.DEBUG,
        )

    if hasattr(host, "progress_bar"):
        try:
            host.progress_bar.setValue(0)
        except Exception:
            pass

    if hasattr(host, "btn_start"):
        try:
            host.btn_start.setText("Start Processing")
            host.btn_start.setEnabled(True)
            host._update_start_enabled()
        except Exception:
            pass

    test_suppress = bool(os.getenv("FPVS_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"))
    if success and not cancelled:
        host._refresh_run_excel_success_from_disk()

    if cancelled:
        host._suppress_completion_dialogs = True
        try:
            parent_finalize(success)
        finally:
            host._suppress_completion_dialogs = False
            host._cancel_requested = False
    else:
        try:
            if test_suppress:
                host._suppress_completion_dialogs = True
            parent_finalize(success)
        finally:
            if test_suppress:
                host._suppress_completion_dialogs = False
            host._cancel_requested = False


def on_start_stop_clicked(host: Any) -> None:
    """Handle Start/Stop button clicks with confirmation on stop."""
    if not getattr(host, "_run_active", False):
        host.start_processing()
        if getattr(host, "_run_active", False) and hasattr(host, "btn_start"):
            try:
                host.btn_start.setText("Stop Processing")
            except Exception:
                pass
        return

    if host._cancel_requested:
        host.log("Cancellation already requested; ignoring Stop click.", level=logging.INFO)
        return

    reply = QMessageBox.question(
        host,
        "Confirm Halt",
        "Data processing is still in progress. Are you sure you want to halt processing?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply == QMessageBox.No:
        return

    host.stop_processing()

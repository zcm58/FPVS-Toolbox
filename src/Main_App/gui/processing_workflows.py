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
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings
from Main_App.workers.mp_env import (
    compute_effective_max_workers,
    get_ram_tier_recommendation,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


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

        host._set_controls_enabled(False)
        if hasattr(host, "progress_bar"):
            host.progress_bar.setRange(0, 100)
            host.progress_bar.setValue(0)
        host._processed_count = 0
        host.busy = True

        from Main_App.workers.mp_runner_bridge import MpRunnerBridge

        project_root = Path(host.currentProject.project_root)
        save_folder = Path(host.save_folder_path.get())
        if is_single_ui:
            files = [Path(host.data_paths[0])]
        else:
            files = [Path(p) for p in host.data_paths]
        host._max_progress = len(files)
        settings = host.validated_params.copy()
        event_map = settings.pop("event_id_map", {})

        host._mp = MpRunnerBridge(host)
        host._mp.validated_fingerprint = getattr(
            host, "_preproc_fingerprint_validated", None
        )

        host._mp.progress.connect(
            lambda pct: (
                host._animate_progress_to(pct / 100.0)
                if hasattr(host, "_animate_progress_to")
                else host.progress_bar.setValue(int(pct))
            )
        )
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
    cancelled = False
    if isinstance(payload, dict):
        results = payload.get("results") or []
        cancelled = bool(payload.get("cancelled", False))

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

    host._busy_stop()
    success = not cancelled
    host._finalize_processing(success, cancelled=cancelled)
    if cancelled:
        host.log("Processing run cancelled by user.", level=logging.INFO)


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

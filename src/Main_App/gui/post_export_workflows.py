"""GUI-side post-processing export workflow helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread

from Main_App.Shared.file_filters import is_excel_output_file
from Main_App.workers.processing_worker import PostProcessWorker

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def excel_paths_in_output_root(output_root: Path | str | None) -> list[Path]:
    if not output_root:
        return []
    root = Path(output_root)
    if not root.is_dir():
        return []
    return sorted(p.resolve() for p in root.rglob("*.xls*") if is_excel_output_file(p))


def excel_snapshot(output_root: Path | str | None) -> dict[str, tuple[int, int]]:
    if not output_root:
        return {}
    root = Path(output_root)
    if not root.is_dir():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*.xls*"):
        if not is_excel_output_file(path):
            continue
        try:
            stat_result = path.stat()
        except OSError:
            continue
        snapshot[str(path.resolve())] = (
            int(stat_result.st_mtime_ns),
            int(stat_result.st_size),
        )
    return snapshot


def excel_snapshot_has_changes(
    before_snapshot: dict[str, tuple[int, int]],
    after_snapshot: dict[str, tuple[int, int]],
) -> bool:
    return any(
        path not in before_snapshot or signature != before_snapshot[path]
        for path, signature in after_snapshot.items()
    )


def should_show_no_excel_popup(
    generated_excel_paths: list[str],
    output_root: Path | str | None,
    existing_excel_paths: list[str] | None = None,
) -> bool:
    if generated_excel_paths:
        return False
    if existing_excel_paths:
        return False
    return len(excel_paths_in_output_root(output_root)) == 0


def on_post_finished(
    host: Any,
    payload: dict | None = None,
    *,
    log: logging.Logger = logger,
) -> None:
    if payload:
        for msg in payload.get("logs", []):
            host.log(msg)

        output_root = payload.get("output_root", "")
        generated_excel_paths = payload.get("generated_excel_paths", []) or []
        existing_excel_paths = payload.get("existing_excel_paths", []) or []

        log.info(
            "pipeline_excel_export",
            extra={
                "operation": "pipeline_excel_export",
                "project_root": str(getattr(getattr(host, "currentProject", None), "project_root", "")),
                "expected_output_dir": output_root,
                "export_reported_success": not bool(payload.get("error")),
                "generated_excel_count": len(generated_excel_paths),
                "glob_result_count": len(existing_excel_paths),
                "elapsed_ms": payload.get("elapsed_ms", 0),
            },
        )

        show_no_excel_popup = should_show_no_excel_popup(
            generated_excel_paths,
            output_root,
            existing_excel_paths,
        )
        current_export_succeeded = not show_no_excel_popup
        if current_export_succeeded:
            host._run_had_successful_export = True
        host._last_job_success = host._run_had_successful_export

        if not generated_excel_paths and not show_no_excel_popup:
            host.log(
                "Excel outputs already existed; no new files were written during this run.",
                level=logging.INFO,
            )

        if payload.get("error") and existing_excel_paths:
            host.log(
                "Excel export reported an error, but Excel outputs were found on disk.",
                level=logging.WARNING,
            )

    host._post_worker = None
    host._post_thread = None

    if host._post_backlog:
        next_file, next_epochs, next_labels = host._post_backlog.popleft()
        host._start_post_worker(next_file, next_epochs, next_labels)
        return

    if getattr(host, "_pending_finalize", False):
        host._pending_finalize = False
        host._finalize_processing(True)


def start_post_worker(host: Any, file_name: str, epochs_dict: dict, labels: list[str]) -> None:
    """Queue-aware launcher for post-processing jobs."""
    payload = (file_name, epochs_dict, labels)

    # If a worker is active, enqueue and return
    if host._post_thread and host._post_thread.isRunning():
        host._post_backlog.append(payload)
        base = os.path.basename(str(file_name))
        host.log(f"Queued post-processing for {base}")
        return

    save_folder = (
        host.save_folder_path.get()
        if hasattr(host.save_folder_path, "get")
        else host.save_folder_path
    )

    worker = PostProcessWorker(
        file_name,
        epochs_dict,
        labels,
        save_folder=save_folder,
        data_paths=[file_name],
        settings=getattr(host, "settings", None),
        logger=lambda m: host.gui_queue.put({"type": "log", "message": m}),
    )

    thread = QThread(host)
    worker.moveToThread(thread)
    worker.error.connect(host._on_worker_error)
    worker.finished.connect(host._on_post_finished)   # will drain backlog
    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    host._post_worker = worker
    host._post_thread = thread
    thread.start()


def on_worker_error(host: Any, message: str) -> None:
    host.log(message, level=logging.ERROR)


def refresh_run_excel_success_from_disk(host: Any) -> None:
    output_root = host._run_excel_output_root or (
        host.save_folder_path.get()
        if hasattr(host.save_folder_path, "get")
        else str(getattr(host, "save_folder_path", "") or "")
    )
    after_snapshot = excel_snapshot(output_root)
    if (
        not host._run_had_successful_export
        and excel_snapshot_has_changes(host._run_excel_snapshot_before, after_snapshot)
    ):
        host._run_had_successful_export = True
    host._last_job_success = host._run_had_successful_export


def export_with_post_process(
    host: Any,
    labels: list[str],
    post_process: Callable[[Any, list[str]], None],
    *,
    log: logging.Logger = logger,
) -> None:
    """
    Run shared post_process then classify whether Excel output was produced.

    Uses a snapshot of files with mtime_ns+size to detect writes/overwrites.
    If no deltas are detectable but the exporter did not report "no files saved"
    and Excel files still exist, treat as success to avoid false negatives on
    coarse timestamp filesystems.
    """
    excel_dir = host.save_folder_path.get() if hasattr(host.save_folder_path, "get") else ""
    if not excel_dir or not Path(excel_dir).is_dir():
        host.gui_queue.put({"type": "error", "message": f"Excel output folder not found:\n{excel_dir}"})
        host._last_job_success = False
        return

    out_path = Path(excel_dir)

    original_log = host.log
    legacy_reported_no_excel = False

    def queue_log(message: str, level: int = logging.INFO) -> None:
        nonlocal legacy_reported_no_excel
        if "no excel files were saved" in str(message).lower():
            legacy_reported_no_excel = True
        host.gui_queue.put({"type": "log", "message": message})
        log.log(level, message)

    host.log = queue_log

    pre_snapshot = excel_snapshot(out_path)

    try:
        post_process(host, labels)

        post_snapshot = excel_snapshot(out_path)
        created = len(set(post_snapshot) - set(pre_snapshot))
        overwritten = sum(
            1
            for path, post_sig in post_snapshot.items()
            if path in pre_snapshot and post_sig != pre_snapshot[path]
        )
        post_count = len(post_snapshot)

        if created > 0 or overwritten > 0:
            host._run_had_successful_export = True
            host._last_job_success = True
            host.gui_queue.put(
                {
                    "type": "log",
                    "message": (
                        f"Excel export completed ({created} new file(s), "
                        f"{overwritten} overwritten file(s))."
                    ),
                }
            )
        elif legacy_reported_no_excel or post_count == 0:
            host._last_job_success = host._run_had_successful_export
            host.gui_queue.put(
                {
                    "type": "log",
                    "message": "Post-process finished but no Excel outputs were detected.",
                }
            )
        else:
            host._run_had_successful_export = True
            host._last_job_success = True
            host.gui_queue.put(
                {
                    "type": "log",
                    "message": (
                        "Post-process finished with existing Excel outputs and no detectable "
                        "timestamp/size changes; treating export as successful."
                    ),
                }
            )
    except Exception as err:
        log.exception("Excel export failed")
        host._last_job_success = host._run_had_successful_export
        host.gui_queue.put({"type": "error", "message": str(err)})
    finally:
        host.log = original_log

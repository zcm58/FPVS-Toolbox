"""Project workflow helpers for the Main App GUI shell."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any, Callable

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from Main_App.processing.processing_controller import prepare_batch_files
from Main_App.processing.project_processing_cache import ProjectProcessingCacheUsage
from Main_App.gui.op_guard import OpGuard
from Main_App.gui import shell_status
from Main_App.projects.project_manager import (
    edit_project_settings as _edit_project_settings,
    loadProject as _load_project,
    new_project_from_fpvs_config as _new_project_from_fpvs_config,
    new_project as _new_project,
    openProjectPath as _open_project_path,
    open_existing_project as _open_existing_project,
)
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings
from Main_App.projects.grouping import project_group_context
from Main_App.workers.project_processing_cache_worker import (
    ProjectProcessingCacheResetWorker,
)

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

WINDOWS_FORBIDDEN_CONDITION_CHARS = set('<>:"/\\|?*')
WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT = '< > : " / \\ | ? *'
NEW_PROJECT_MANUAL = "manual"
NEW_PROJECT_FPVS_CONFIG = "fpvs_config"


def _illegal_condition_chars(label: str) -> list[str]:
    return sorted({ch for ch in label if ch in WINDOWS_FORBIDDEN_CONDITION_CHARS})


def _choose_new_project_source(host: Any) -> str | None:
    box = QMessageBox(host)
    box.setWindowTitle("New Project")
    box.setText("How would you like to create this project?")
    config_button = box.addButton("Import FPVS Studio Config", QMessageBox.AcceptRole)
    manual_button = box.addButton("Create Manually", QMessageBox.ActionRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.setDefaultButton(manual_button)
    box.exec()

    clicked = box.clickedButton()
    if clicked == config_button:
        return NEW_PROJECT_FPVS_CONFIG
    if clicked == manual_button:
        return NEW_PROJECT_MANUAL
    return None


def new_project(host: Any) -> None:
    choice = _choose_new_project_source(host)
    if choice == NEW_PROJECT_FPVS_CONFIG:
        new_project_from_fpvs_config(host)
        return
    if choice == NEW_PROJECT_MANUAL:
        _new_project(host)
        notify_project_ready(host)


def new_project_from_fpvs_config(host: Any) -> None:
    project = _new_project_from_fpvs_config(host, host)
    if project is not None:
        notify_project_ready(host)


def open_existing_project(host: Any) -> None:
    _open_existing_project(host, host)


def import_fpvs_config_project(host: Any) -> None:
    new_project_from_fpvs_config(host)


def open_project_path(host: Any, folder: str) -> None:
    _open_project_path(host, folder)
    notify_project_ready(host)


def edit_project_settings(host: Any) -> None:
    _edit_project_settings(host)
    sync_input_folder_display(host)
    host._update_start_enabled()


def _format_cache_size(total_bytes: int) -> str:
    size = float(max(0, total_bytes))
    for unit in ("bytes", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            if unit == "bytes":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(total_bytes)} bytes"


def _processing_cache_reset_is_busy(host: Any) -> bool:
    if bool(getattr(host, "_run_active", False)):
        return True
    start_guard = getattr(host, "_start_guard", None)
    is_active = getattr(start_guard, "is_active", None)
    if callable(is_active):
        try:
            if is_active():
                return True
        except (AttributeError, RuntimeError, TypeError):
            pass
    for attribute in (
        "_preflight_qc_thread",
        "_post_processing_pipeline_thread",
        "_settings_full_fft_grid_qc_thread",
        "_settings_harmonic_recalc_thread",
        "_project_processing_cache_thread",
    ):
        thread = getattr(host, attribute, None)
        is_running = getattr(thread, "isRunning", None)
        if not callable(is_running):
            continue
        try:
            if is_running():
                return True
        except RuntimeError:
            continue
    return False


def _set_processing_cache_reset_ui_locked(host: Any, locked: bool) -> None:
    action = getattr(host, "actionResetProjectProcessingCache", None)
    if action is not None:
        action.setEnabled(not locked)
        action.setText(
            "Resetting Project Processing Cache..."
            if locked
            else "Reset Project Processing Cache..."
        )
    shell_status._set_processing_navigation_locked(host, locked)
    workspace = getattr(host, "workspace_stack", None)
    if workspace is not None:
        if locked:
            host._project_processing_cache_workspace_was_enabled = (
                workspace.isEnabled()
            )
            workspace.setEnabled(False)
        else:
            workspace.setEnabled(
                bool(
                    getattr(
                        host,
                        "_project_processing_cache_workspace_was_enabled",
                        True,
                    )
                )
            )
            host._project_processing_cache_workspace_was_enabled = True
    set_controls_enabled = getattr(host, "_set_controls_enabled", None)
    if callable(set_controls_enabled):
        set_controls_enabled(not locked)
    start_button = getattr(host, "btn_start", None)
    if locked and start_button is not None:
        start_button.setEnabled(False)
    if not locked:
        update_start_enabled = getattr(host, "_update_start_enabled", None)
        if callable(update_start_enabled):
            update_start_enabled()


def _release_processing_cache_start_guard(host: Any) -> None:
    if not getattr(host, "_project_processing_cache_holds_start_guard", False):
        return
    host._project_processing_cache_holds_start_guard = False
    start_guard = getattr(host, "_start_guard", None)
    end = getattr(start_guard, "end", None)
    if callable(end):
        end()


def reset_project_processing_cache(host: Any) -> None:
    """Confirm and clear only active-project state that makes runs warm."""

    project = getattr(host, "currentProject", None)
    if project is None:
        QMessageBox.warning(
            host,
            "No Project",
            "Open or create a project before resetting its processing cache.",
        )
        return
    if _processing_cache_reset_is_busy(host):
        QMessageBox.warning(
            host,
            "Processing Is Active",
            "Wait for the current data-quality or processing run to finish before "
            "resetting the project cache.",
        )
        return

    response = QMessageBox.question(
        host,
        "Reset Project Processing Cache?",
        (
            "Resetting removes only:\n"
            "- cached Data Quality Check results\n"
            "- cached preprocessed EEG data\n"
            "- the incremental completion index and its derived QC provenance\n\n"
            "Raw BDF files, project settings, manual QC choices, current generated "
            "outputs, and processing run history are not deleted. The next Start "
            "Processing run will recheck every file and recompute from raw data. "
            "Once that run begins, normal processing will replace its participant "
            "output files. If that run is cancelled, the completion index remains "
            "empty until a later run rebuilds it.\n\n"
            "Make sure no other FPVS Toolbox window is processing this project.\n\n"
            "Continue?"
        ),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if response != QMessageBox.Yes:
        return

    start_guard = getattr(host, "_start_guard", None)
    acquire_start_guard = getattr(start_guard, "start", None)
    if not callable(acquire_start_guard) or not acquire_start_guard():
        QMessageBox.warning(
            host,
            "Processing Is Active",
            "Processing state changed before the cache reset could start. Wait for "
            "the current operation to finish and try again.",
        )
        return
    host._project_processing_cache_holds_start_guard = True

    project_root = project.project_root
    thread = QThread(host)
    worker = ProjectProcessingCacheResetWorker(project_root)
    worker.moveToThread(thread)
    host._project_processing_cache_thread = thread
    host._project_processing_cache_worker = worker
    _set_processing_cache_reset_ui_locked(host, True)
    log = getattr(host, "log", None)
    if callable(log):
        log("Resetting the active project's FPVS-managed processing cache...")

    thread.started.connect(worker.run)
    worker.finished.connect(thread.quit)
    worker.failed.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    worker.failed.connect(worker.deleteLater)
    worker.finished.connect(host._on_project_processing_cache_reset_finished)
    worker.failed.connect(host._on_project_processing_cache_reset_failed)
    thread.finished.connect(thread.deleteLater)
    thread.finished.connect(host._on_project_processing_cache_reset_thread_finished)
    try:
        thread.start()
    except RuntimeError as exc:
        host._project_processing_cache_thread = None
        host._project_processing_cache_worker = None
        _release_processing_cache_start_guard(host)
        worker.deleteLater()
        thread.deleteLater()
        _set_processing_cache_reset_ui_locked(host, False)
        logger.exception(
            "project_processing_cache_thread_start_failed root=%s",
            project_root,
        )
        QMessageBox.critical(
            host,
            "Cache Reset Failed",
            f"FPVS Toolbox could not start the cache-reset worker.\n\n{exc}",
        )


def on_project_processing_cache_reset_finished(
    host: Any,
    removed: ProjectProcessingCacheUsage,
) -> None:
    project = getattr(host, "currentProject", None)
    project_root = getattr(project, "project_root", "")
    if removed.is_empty:
        message = (
            "No FPVS-managed processing cache was present. The next run will "
            "already recheck every participant and preprocess from raw BDF data."
        )
        logger.info("project_processing_cache_already_empty root=%s", project_root)
        log = getattr(host, "log", None)
        if callable(log):
            log(message)
        QMessageBox.information(host, "Processing Cache Already Empty", message)
        return

    logger.info(
        "project_processing_cache_reset root=%s files=%d bytes=%d",
        project_root,
        removed.file_count,
        removed.total_bytes,
    )
    log_message = (
        "Reset project processing cache: "
        f"{removed.file_count} file(s), {_format_cache_size(removed.total_bytes)}. "
        "The next run will be cold for FPVS-managed data-quality, raw-preprocessing, "
        "and incremental-planning caches."
    )
    log = getattr(host, "log", None)
    if callable(log):
        log(log_message)
    QMessageBox.information(
        host,
        "Processing Cache Reset",
        (
            f"Removed {removed.file_count} managed cache file(s) "
            f"({_format_cache_size(removed.total_bytes)}).\n\n"
            "The next processing run will recheck every participant and preprocess "
            "from raw BDF data. Project settings, manual QC choices, current outputs, "
            "and run history were preserved."
        ),
    )


def on_project_processing_cache_reset_failed(host: Any, error: str) -> None:
    project = getattr(host, "currentProject", None)
    project_root = getattr(project, "project_root", "")
    logger.error(
        "project_processing_cache_reset_failed root=%s error=%s",
        project_root,
        error,
    )
    QMessageBox.critical(
        host,
        "Cache Reset Failed",
        (
            "FPVS Toolbox could not fully reset the processing cache. Some cache "
            "files may already have been removed; project data and outputs were not "
            "targeted. Close programs using the project and try again.\n\n"
            f"{error}"
        ),
    )


def on_project_processing_cache_reset_thread_finished(host: Any) -> None:
    host._project_processing_cache_thread = None
    host._project_processing_cache_worker = None
    _release_processing_cache_start_guard(host)
    _set_processing_cache_reset_ui_locked(host, False)


def on_project_ready(host: Any) -> None:
    if not getattr(host, "currentProject", None):
        return
    opts = getattr(host.currentProject, "options", {})
    host.parallel_mode = opts.get("parallel_mode", host.parallel_mode)
    sync_input_folder_display(host)
    update_select_button_text(host)
    if hasattr(host, "stacked"):
        host.stacked.setCurrentIndex(1)


def notify_project_ready(host: Any) -> None:
    callback = getattr(host, "_on_project_ready", None)
    if callable(callback):
        callback()
    else:
        on_project_ready(host)


def _retire_widget(widget: Any, *, workspace: Any, seen: set[int]) -> None:
    if widget is None:
        return
    widget_id = id(widget)
    if widget_id in seen:
        return
    seen.add(widget_id)

    if workspace is not None:
        remover = getattr(workspace, "removeWidget", None)
        if callable(remover):
            try:
                remover(widget)
            except RuntimeError:
                pass

    closer = getattr(widget, "close", None)
    if callable(closer):
        try:
            closer()
        except RuntimeError:
            pass

    deleter = getattr(widget, "deleteLater", None)
    if callable(deleter):
        try:
            deleter()
        except RuntimeError:
            pass


def reset_project_context_workspace(host: Any) -> None:
    """Discard project-bound embedded pages after the active project changes."""
    workspace = getattr(host, "workspace_stack", None)
    seen: set[int] = set()

    settings_dialog = getattr(host, "_settings_dialog", None)
    if settings_dialog is not None:
        reject = getattr(settings_dialog, "reject", None)
        if callable(reject):
            try:
                reject()
            except RuntimeError:
                pass
        _retire_widget(settings_dialog, workspace=None, seen=seen)
        host._settings_dialog = None

    for attr_name in (
        "_settings_page",
        "_stats_page",
        "_ratio_calculator_page",
        "_individual_detectability_page",
        "_plot_generator_page",
        "_publication_maps_page",
        "_loreta_visualizer_page",
        "_epoch_page",
        "_epoch_win",
    ):
        widget = getattr(host, attr_name, None)
        _retire_widget(widget, workspace=workspace, seen=seen)
        setattr(host, attr_name, None)

    show_home_page = getattr(host, "show_home_page", None)
    if callable(show_home_page):
        show_home_page()


def load_project(
    host: Any,
    project: Any,
    entry_adapter_factory: Callable[[QLineEdit], Any],
) -> None:
    _load_project(host, project)

    # Auto-populate data_paths from the project's registered raw source(s).
    # This scan must not mutate participant metadata; processing performs the
    # explicit review/register step.
    try:
        file_paths = prepare_batch_files(project)
    except Exception as exc:
        logger.exception("Project raw-file discovery failed during load.")
        QMessageBox.critical(host, "Project Data Error", str(exc))
        file_paths = []
    host.data_paths = [str(p) for p in file_paths]

    context = project_group_context(project)
    sync_input_folder_display(host)

    if host.data_paths:
        if context.has_group_metadata:
            host.log(
                "Project data folders set "
                f"({len(context.groups)} groups, {len(host.data_paths)} .bdf files)"
            )
        else:
            host.log(
                "Project data folder set: "
                f"{project.input_folder} ({len(host.data_paths)} .bdf files)"
            )
    else:
        if context.has_group_metadata:
            configured = "; ".join(
                f"{group.label}: {group.raw_input_folder}"
                for group in context.groups
            )
            host.log(
                "Warning: no .bdf files found in registered group folders: "
                f"{configured}",
                level=logging.WARNING,
            )
        else:
            host.log(
                "Warning: no .bdf files found in project input folder: "
                f"{project.input_folder}",
                level=logging.WARNING,
            )

    # Provide post_process with a .get() for the Excel output folder.
    excel_subfolder = project.subfolders.get("excel")
    if excel_subfolder:
        excel_dir = project.project_root / excel_subfolder
        excel_dir.mkdir(parents=True, exist_ok=True)
        host.save_folder_path = SimpleNamespace(get=lambda: str(excel_dir))
        host.log(f"Save folder path set: {host.save_folder_path.get()}")
    else:
        QMessageBox.warning(
            host,
            "Missing Excel Folder",
            "No 'excel' subfolder configured. Please update the project settings.",
        )
        host.log(
            "Project missing 'excel' subfolder; save folder path not set.",
            level=logging.WARNING,
        )
        host.save_folder_path = None

    # Build ephemeral entry adapters for legacy helpers that expect .get().
    def make_entry(value: str | float | int | None):
        edit = QLineEdit(str(value) if value is not None else "")
        return entry_adapter_factory(edit)

    p = normalize_preprocessing_settings(host.currentProject.preprocessing)
    host.low_pass_entry = make_entry(p.get("low_pass"))
    host.high_pass_entry = make_entry(p.get("high_pass"))
    host.downsample_entry = make_entry(p.get("downsample"))
    host.epoch_start_entry = make_entry(p.get("epoch_start_s"))
    host.epoch_end_entry = make_entry(p.get("epoch_end_s"))
    host.reject_thresh_entry = make_entry(p.get("rejection_z"))
    host.ref_channel1_entry = make_entry(p.get("ref_chan1"))
    host.ref_channel2_entry = make_entry(p.get("ref_chan2"))
    host.max_idx_keep_entry = make_entry(p.get("max_chan_idx_keep"))
    host.max_bad_channels_alert_entry = make_entry(p.get("max_bad_chans"))


def save_project_settings(host: Any) -> None:
    """Persist project options and event map. Non-blocking, idempotent."""
    if not getattr(host, "currentProject", None):
        QMessageBox.warning(host, "No Project", "Please open or create a project first.")
        return

    guard = getattr(host, "_save_guard", None)
    if guard is None:
        host._save_guard = OpGuard()
        guard = host._save_guard
    if not guard.start():
        QMessageBox.information(host, "Busy", "Save already in progress.")
        return

    try:
        try:
            host.clearFocus()
            QApplication.processEvents()
        except Exception:
            pass

        old_map: dict[str, int] = dict(getattr(host.currentProject, "event_map", {}) or {})
        old_opts: dict = dict(getattr(host.currentProject, "options", {}) or {})

        opts = getattr(host.currentProject, "options", {})
        if not isinstance(opts, dict):
            opts = {}
        opts["mode"] = (
            "single"
            if getattr(host, "rb_single", None) and host.rb_single.isChecked()
            else "batch"
        )
        host.currentProject.options = opts

        mapping: dict[str, int] = {}
        for row in getattr(host, "event_rows", []):
            edits = row.findChildren(QLineEdit)
            if len(edits) < 2:
                continue
            label_edit = edits[0]
            label = label_edit.text().strip()
            ident = edits[1].text().strip()
            if not label:
                continue
            illegal_chars = _illegal_condition_chars(label)
            if illegal_chars:
                bad = " ".join(illegal_chars)
                QMessageBox.warning(
                    host,
                    "Invalid Condition Name",
                    (
                        "Condition names cannot contain characters that are invalid for "
                        "Windows file/folder names.\n\n"
                        f"Condition: {label}\n"
                        f"Illegal character(s): {bad}\n\n"
                        "Please rename this condition using only allowed characters.\n"
                        f"Not allowed: {WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT}"
                    ),
                )
                try:
                    label_edit.setFocus()
                    label_edit.selectAll()
                except Exception:
                    pass
                return
            try:
                mapping[label] = int(ident)
            except Exception:
                # Ignore non-integer IDs silently to match prior behavior.
                continue

        if mapping == old_map and opts == old_opts:
            return

        host.currentProject.event_map = mapping
        host.currentProject.save()

        QMessageBox.information(host, "Project Saved", "All settings written to project.json.")
    except Exception as e:
        QMessageBox.critical(host, "Save Error", str(e))
    finally:
        try:
            guard.end()
        except Exception:
            pass


def sync_input_folder_display(host: Any) -> None:
    folder_text = ""
    tooltip = ""
    has_groups = False
    if getattr(host, "currentProject", None):
        context = project_group_context(host.currentProject)
        has_groups = context.has_group_metadata
        if has_groups:
            folder_text = f"{len(context.groups)} group raw-data folders configured"
            tooltip = "\n".join(
                f"{group.label}: {group.raw_input_folder}"
                for group in context.groups
            )
        else:
            folder_text = str(host.currentProject.input_folder)
            tooltip = folder_text
    line_edit = getattr(host, "le_input_folder", None)
    if isinstance(line_edit, QLineEdit):
        line_edit.setText(folder_text)
        line_edit.setToolTip(tooltip)
    button = getattr(host, "btn_select_input_folder", None)
    if button and hasattr(button, "setText"):
        button.setText(
            "Edit Group Folders..." if has_groups else "Select Data Folder..."
        )


def update_select_button_text(host: Any) -> None:
    """Ensure the file/folder select button(s) reflect the active mode."""
    try:
        mode = "Batch"
        if hasattr(host, "file_mode") and callable(getattr(host.file_mode, "get", None)):
            mode = host.file_mode.get()

        if mode == "Single":
            btn_file = getattr(host, "btn_select_input_file", None)
            if btn_file and hasattr(btn_file, "setText"):
                btn_file.setText("Select EEG File...")
            btn_generic = getattr(host, "btn_select_input", None)
            if btn_generic and hasattr(btn_generic, "setText"):
                btn_generic.setText("Select EEG File...")
        else:
            btn_folder = getattr(host, "btn_select_input_folder", None)
            if btn_folder and hasattr(btn_folder, "setText"):
                project = getattr(host, "currentProject", None)
                has_groups = (
                    project_group_context(project).has_group_metadata
                    if project is not None
                    else False
                )
                btn_folder.setText(
                    "Edit Group Folders..." if has_groups else "Select Data Folder..."
                )
            btn_generic = getattr(host, "btn_select_input", None)
            if btn_generic and hasattr(btn_generic, "setText"):
                btn_generic.setText("Select Data Folder...")
    except Exception as e:
        host.log(f"update_select_button_text failed: {e}", level=logging.WARNING)

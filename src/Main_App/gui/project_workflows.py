"""Project workflow helpers for the Main App GUI shell."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from Main_App.processing.processing_controller import prepare_batch_files
from Main_App.gui.op_guard import OpGuard
from Main_App.projects.project_manager import (
    edit_project_settings as _edit_project_settings,
    import_fpvs_config_project as _import_fpvs_config_project,
    loadProject as _load_project,
    new_project as _new_project,
    openProjectPath as _open_project_path,
    open_existing_project as _open_existing_project,
)
from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

WINDOWS_FORBIDDEN_CONDITION_CHARS = set('<>:"/\\|?*')
WINDOWS_FORBIDDEN_CONDITION_CHARS_TEXT = '< > : " / \\ | ? *'


def _illegal_condition_chars(label: str) -> list[str]:
    return sorted({ch for ch in label if ch in WINDOWS_FORBIDDEN_CONDITION_CHARS})


def new_project(host: Any) -> None:
    _new_project(host)
    notify_project_ready(host)


def open_existing_project(host: Any) -> None:
    _open_existing_project(host, host)


def import_fpvs_config_project(host: Any) -> None:
    project = _import_fpvs_config_project(host, host)
    if project is not None:
        notify_project_ready(host)


def open_project_path(host: Any, folder: str) -> None:
    _open_project_path(host, folder)
    notify_project_ready(host)


def edit_project_settings(host: Any) -> None:
    _edit_project_settings(host)
    sync_input_folder_display(host)
    host._update_start_enabled()


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
        "_image_resizer_page",
        "_ratio_calculator_page",
        "_individual_detectability_page",
        "_plot_generator_page",
        "_publication_maps_page",
        "_loreta_visualizer_page",
        "_publication_workflow_page",
        "_publication_report_page",
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
        QMessageBox.warning(host, "Project Data Warning", str(exc))
        file_paths = []
    host.data_paths = [str(p) for p in file_paths]

    groups = getattr(project, "groups", {}) or {}
    input_dir = Path(project.input_folder)
    sync_input_folder_display(host)

    if host.data_paths:
        if isinstance(groups, dict) and len(groups) >= 2:
            host.log(
                f"Project data folders set ({len(groups)} groups, {len(host.data_paths)} .bdf files)"
            )
        else:
            host.log(
                f"Project data folder set: {input_dir} ({len(host.data_paths)} .bdf files)"
            )
    else:
        host.log(
            f"Warning: no .bdf files found in project input folder(s): {input_dir}",
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
    if getattr(host, "currentProject", None):
        folder_text = str(host.currentProject.input_folder)
    line_edit = getattr(host, "le_input_folder", None)
    if isinstance(line_edit, QLineEdit):
        line_edit.setText(folder_text)


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
                btn_folder.setText("Select Data Folder...")
            btn_generic = getattr(host, "btn_select_input", None)
            if btn_generic and hasattr(btn_generic, "setText"):
                btn_generic.setText("Select Data Folder...")
    except Exception as e:
        host.log(f"update_select_button_text failed: {e}", level=logging.WARNING)

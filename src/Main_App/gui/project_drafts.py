"""Protect unsaved setup drafts at project replacement and application exit."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from Main_App.gui.event_map import condition_row_values


def _condition_snapshot(host):
    rows = tuple((label.strip(), ident.strip()) for label, ident in condition_row_values(host)
                 if label.strip() or ident.strip())
    single = getattr(host, "rb_single", None)
    return rows, "single" if single is not None and single.isChecked() else "batch"


def remember_saved_setup(host) -> None:
    host._condition_draft_baseline = _condition_snapshot(host)
    refresh_dirty_indicator(host)


def has_condition_changes(host) -> bool:
    project = getattr(host, "currentProject", None)
    if project is None:
        return False
    baseline = getattr(host, "_condition_draft_baseline", None)
    if baseline is None:
        baseline = (tuple((str(k), str(v)) for k, v in project.event_map.items()),
                    project.options.get("mode", "batch"))
    return _condition_snapshot(host) != baseline


def has_project_changes(host) -> bool:
    page = getattr(host, "_settings_page", None)
    checker = getattr(page, "has_unsaved_changes", None)
    return has_condition_changes(host) or bool(callable(checker) and checker())


def refresh_dirty_indicator(host) -> None:
    label = getattr(host, "project_draft_status", None)
    if label is not None:
        label.setText("Unsaved changes" if has_project_changes(host) else "")


def _save_work_is_active(host) -> bool:
    return bool(
        getattr(host, "_run_active", False)
        or getattr(host, "_settings_post_processing_activity_active", False)
        or getattr(host, "_settings_full_fft_grid_qc_thread", None) is not None
        or getattr(host, "_settings_harmonic_recalc_thread", None) is not None
    )


def confirm_project_draft_exit(host) -> bool:
    """Save must finish successfully before a draft may be replaced."""
    if not has_project_changes(host):
        return True
    choice = QMessageBox.question(
        host, "Unsaved Project Changes",
        "Save your setup changes before leaving this project?",
        QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
        QMessageBox.Cancel,
    )
    if choice == QMessageBox.Discard:
        return True
    if choice != QMessageBox.Save:
        return False
    # Validate conditions first so an invalid row cannot partially commit Settings.
    from Main_App.gui.event_map import validated_event_map
    if validated_event_map(host, focus_error=True) is None:
        host.show_home_page()
        validated_event_map(host, focus_error=True)
        return False
    page = getattr(host, "_settings_page", None)
    if page is not None and page.has_unsaved_changes():
        saved = page.save_pending_changes()
        work_active = _save_work_is_active(host)
        if not saved or work_active:
            if not work_active:
                host.open_settings_window()
            return False
    if has_condition_changes(host):
        from Main_App.gui.project_workflows import save_project_settings
        return save_project_settings(host)
    return True

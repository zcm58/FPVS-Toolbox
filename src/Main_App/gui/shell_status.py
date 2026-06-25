"""Shell-level logging, launch feedback, and processing activity helpers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from Main_App.diagnostics import log_router

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QTableWidgetItem,
    QToolBar,
    QWidget,
)


def init_launch_reveal_state(host: Any) -> None:
    host._launch_reveal_done = False
    host._launch_reveal_animation: QPropertyAnimation | None = None
    host._launch_reveal_effect: QGraphicsOpacityEffect | None = None
    host._launch_reveal_target: QWidget | None = None


def launch_reveal_widget(host: Any) -> QWidget | None:
    if not hasattr(host, "stacked"):
        return None
    if host.stacked.currentWidget() is getattr(host, "landing_page", None):
        return getattr(host, "landing_card", None)
    return getattr(host, "page1_container", None)


def start_launch_reveal(host: Any) -> None:
    target = host._launch_reveal_widget()
    if target is None or not target.isVisible():
        return

    effect = QGraphicsOpacityEffect(target)
    effect.setOpacity(0.0)
    target.setGraphicsEffect(effect)

    animation = QPropertyAnimation(effect, b"opacity", host)
    animation.setDuration(180)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.setEasingCurve(QEasingCurve.OutCubic)
    animation.finished.connect(host._finish_launch_reveal)

    host._launch_reveal_target = target
    host._launch_reveal_effect = effect
    host._launch_reveal_animation = animation
    animation.start()


def finish_launch_reveal(host: Any) -> None:
    if host._launch_reveal_target is not None:
        host._launch_reveal_target.setGraphicsEffect(None)
    host._launch_reveal_target = None
    host._launch_reveal_effect = None
    host._launch_reveal_animation = None


def emit_backend_log(host: Any, log: logging.Logger, level: int, message: str) -> None:
    """
    Emit to the Python logging backend only when:
      * Debug mode is enabled, or
      * Level is WARNING or higher.
    Prevents noisy INFO logs in the IDE/console during normal runs.
    """
    try:
        debug_on = host.settings.debug_enabled()
    except Exception:
        debug_on = False
    log_router.emit_backend_log(
        log,
        level=level,
        message=message,
        debug_enabled=debug_on,
    )


def log_message(host: Any, log: logging.Logger, message: str, level: int = logging.INFO) -> None:
    log_router.emit_gui_log(host, log, message=message, level=level)


def show_processing_started_notice(host: Any) -> None:
    """Compatibility shim; the embedded processing page is now the notice."""
    existing = getattr(host, "_processing_notice", None)
    if existing is not None:
        try:
            existing.close()
        except Exception:
            pass
        finally:
            host._processing_notice = None


def _processing_file_label(file_path: Any) -> str:
    try:
        return Path(file_path).name
    except TypeError:
        return str(file_path)


def _processing_file_keys(file_path: Any) -> tuple[str, str]:
    raw = str(file_path)
    return raw, _processing_file_label(file_path)


def _set_processing_summary(host: Any, pct: int | None = None) -> None:
    total = int(getattr(host, "_processing_file_total", 0) or 0)
    completed = len(getattr(host, "_processing_completed_file_keys", set()))
    excluded = len(getattr(host, "_processing_excluded_file_keys", set()))
    pct_text = f" ({pct}%)" if pct is not None else ""
    summary = f"{completed} of {total} files complete{pct_text}"
    if excluded:
        summary += f"; {excluded} excluded"
    label = getattr(host, "processing_summary_label", None)
    if label is not None:
        label.setText(summary)


def prepare_processing_activity(host: Any, files: list[Path]) -> None:
    table = getattr(host, "processing_files_table", None)
    if table is None:
        return

    host._processing_file_total = len(files)
    host._processing_completed_file_keys = set()
    host._processing_excluded_file_keys = set()
    host._processing_file_rows = {}
    host._processing_row_keys = {}

    table.setRowCount(len(files))
    for row, file_path in enumerate(files):
        raw_key, name_key = _processing_file_keys(file_path)
        host._processing_file_rows[raw_key] = row
        host._processing_file_rows.setdefault(name_key, row)
        host._processing_row_keys[row] = raw_key

        status_item = QTableWidgetItem("Queued")
        file_item = QTableWidgetItem(_processing_file_label(file_path))
        status_item.setTextAlignment(Qt.AlignCenter)
        file_item.setToolTip(raw_key)
        table.setItem(row, 0, status_item)
        table.setItem(row, 1, file_item)

    table.resizeRowsToContents()
    table.scrollToTop()
    _set_processing_summary(host, 0)
    current_label = getattr(host, "processing_current_file_label", None)
    if current_label is not None:
        current_label.setText("Latest file: Waiting for processing to begin")


def update_processing_progress(host: Any, pct: int) -> None:
    _set_processing_summary(host, max(0, min(100, int(pct))))


def update_processing_file_status(host: Any, result: dict[str, object]) -> None:
    table = getattr(host, "processing_files_table", None)
    if table is None:
        return

    file_value = result.get("file") or "unknown"
    raw_key, name_key = _processing_file_keys(file_value)
    rows = getattr(host, "_processing_file_rows", {})
    row = rows.get(raw_key, rows.get(name_key))
    if row is None:
        row = table.rowCount()
        table.insertRow(row)
        rows[raw_key] = row
        rows.setdefault(name_key, row)
        host._processing_file_rows = rows
        row_keys = getattr(host, "_processing_row_keys", {})
        row_keys[row] = raw_key
        host._processing_row_keys = row_keys
        table.setItem(row, 0, QTableWidgetItem("Queued"))
        table.setItem(row, 1, QTableWidgetItem(_processing_file_label(file_value)))

    status = str(result.get("status") or "").lower()
    if status == "ok":
        status_text = "Complete"
        completed = getattr(host, "_processing_completed_file_keys", set())
        row_key = getattr(host, "_processing_row_keys", {}).get(row, raw_key)
        completed.add(row_key)
        host._processing_completed_file_keys = completed
        latest = f"Latest file: Completed {_processing_file_label(file_value)}"
    elif status == "excluded":
        status_text = "Excluded"
        excluded = getattr(host, "_processing_excluded_file_keys", set())
        row_key = getattr(host, "_processing_row_keys", {}).get(row, raw_key)
        excluded.add(row_key)
        host._processing_excluded_file_keys = excluded
        latest = f"Latest file: Excluded {_processing_file_label(file_value)}"
    elif status == "error":
        stage = str(result.get("stage") or "unknown")
        status_text = "Failed"
        latest = f"Latest file: Failed {_processing_file_label(file_value)} at {stage}"
    else:
        status_text = "Updated"
        latest = f"Latest file: {_processing_file_label(file_value)}"

    status_item = table.item(row, 0)
    if status_item is None:
        status_item = QTableWidgetItem()
        table.setItem(row, 0, status_item)
    status_item.setText(status_text)
    status_item.setTextAlignment(Qt.AlignCenter)

    current_label = getattr(host, "processing_current_file_label", None)
    if current_label is not None:
        current_label.setText(latest)

    table.resizeRowsToContents()
    if status_item is not None:
        table.scrollToItem(status_item)
    _set_processing_summary(host)


def _remove_start_button_from_known_rows(host: Any) -> None:
    button = getattr(host, "btn_start", None)
    if button is None:
        return

    for layout in (
        getattr(getattr(host, "run_panel", None), "row_layout", None),
        getattr(host, "processing_action_layout", None),
    ):
        if layout is not None and layout.indexOf(button) >= 0:
            layout.removeWidget(button)


def _place_start_button(host: Any, target: str) -> None:
    button = getattr(host, "btn_start", None)
    if button is None:
        return

    _remove_start_button_from_known_rows(host)
    if target == "processing":
        slot = getattr(host, "processing_action_slot", None)
        layout = getattr(host, "processing_action_layout", None)
        if slot is not None and layout is not None:
            button.setParent(slot)
            layout.addWidget(button, 0, Qt.AlignCenter)
            button.show()
        return

    run_panel = getattr(host, "run_panel", None)
    layout = getattr(run_panel, "row_layout", None)
    if run_panel is not None and layout is not None:
        button.setParent(run_panel)
        layout.addWidget(button)
        button.show()


def _refresh_widget_style(widget: QWidget) -> None:
    try:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()
    except RuntimeError:
        pass


def _set_sidebar_processing_locked(sidebar: QWidget, locked: bool) -> None:
    sidebar.setProperty("processingLocked", locked)
    _refresh_widget_style(sidebar)
    for child in sidebar.findChildren(QWidget):
        if child.objectName() == "SidebarButton":
            setter = getattr(child, "set_processing_locked", None)
            if callable(setter):
                setter(locked)
            else:
                child.setProperty("processingLocked", locked)
                _refresh_widget_style(child)


def ensure_processing_navigation_unlocked(host: Any) -> None:
    sidebar = getattr(host, "sidebar", None)
    if sidebar is not None:
        sidebar.setEnabled(True)
        sidebar.setGraphicsEffect(None)
        _set_sidebar_processing_locked(sidebar, False)
    for widget in (getattr(host, "menuBar", lambda: None)(),):
        if widget is not None:
            try:
                widget.setEnabled(True)
            except RuntimeError:
                pass
    try:
        for toolbar in host.findChildren(QToolBar):
            toolbar.setEnabled(True)
    except RuntimeError:
        pass
    host._processing_navigation_states = []
    host._processing_sidebar_effect = None


def _set_processing_navigation_locked(host: Any, locked: bool) -> None:
    if locked:
        if getattr(host, "_processing_navigation_states", None):
            return
        widgets: list[QWidget] = []
        sidebar = getattr(host, "sidebar", None)
        if sidebar is not None:
            _set_sidebar_processing_locked(sidebar, True)
        try:
            widgets.append(host.menuBar())
        except Exception:
            pass
        try:
            widgets.extend(host.findChildren(QToolBar))
        except Exception:
            pass

        states: list[tuple[QWidget, bool]] = []
        for widget in widgets:
            try:
                states.append((widget, widget.isEnabled()))
                widget.setEnabled(False)
            except RuntimeError:
                continue
        host._processing_navigation_states = states
        return

    for widget, was_enabled in getattr(host, "_processing_navigation_states", []):
        try:
            widget.setEnabled(was_enabled)
        except RuntimeError:
            continue
    host._processing_navigation_states = []
    sidebar = getattr(host, "sidebar", None)
    if sidebar is not None:
        sidebar.setGraphicsEffect(None)
        _set_sidebar_processing_locked(sidebar, False)
    host._processing_sidebar_effect = None


def show_processing_page(host: Any) -> None:
    workspace = getattr(host, "workspace_stack", None)
    processing_page = getattr(host, "processing_page", None)
    if workspace is None or processing_page is None:
        return

    current = workspace.currentWidget()
    if current is not processing_page:
        host._processing_return_widget = current

    if hasattr(host, "stacked"):
        host.stacked.setCurrentIndex(1)
    _place_start_button(host, "processing")

    spinner = getattr(host, "processing_spinner", None)
    if spinner is not None:
        spinner.start()

    workspace.setCurrentWidget(processing_page)
    _set_processing_navigation_locked(host, True)
    host._processing_page_visible = True


def hide_processing_page(host: Any) -> None:
    spinner = getattr(host, "processing_spinner", None)
    if spinner is not None:
        spinner.stop()

    _set_processing_navigation_locked(host, False)
    _place_start_button(host, "home")

    workspace = getattr(host, "workspace_stack", None)
    processing_page = getattr(host, "processing_page", None)
    if workspace is not None and processing_page is not None:
        return_widget = getattr(host, "_processing_return_widget", None)
        if return_widget is None or return_widget is processing_page:
            return_widget = getattr(host, "homeWidget", None)
        try:
            if return_widget is not None and workspace.indexOf(return_widget) >= 0:
                workspace.setCurrentWidget(return_widget)
        except RuntimeError:
            home_widget = getattr(host, "homeWidget", None)
            if home_widget is not None and workspace.indexOf(home_widget) >= 0:
                workspace.setCurrentWidget(home_widget)

        if workspace.currentWidget() is getattr(host, "homeWidget", None):
            selector = getattr(host, "_set_sidebar_selection", None)
            if callable(selector):
                selector("btn_home")

    host._processing_return_widget = None
    host._processing_page_visible = False


def busy_start(host: Any) -> None:
    show_processing_page(host)


def busy_stop(host: Any) -> None:
    hide_processing_page(host)


def tick_busy(host: Any) -> None:
    spinner = getattr(host, "processing_spinner", None)
    if spinner is not None:
        spinner.update()

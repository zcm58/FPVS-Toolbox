"""Shell-level logging, launch feedback, and processing activity helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
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
    if debug_on or level >= logging.WARNING:
        log.log(level, message)


def log_message(host: Any, log: logging.Logger, message: str, level: int = logging.INFO) -> None:
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    formatted = f"{ts} [GUI]: {message}"
    if hasattr(host, "text_log") and host.text_log:
        host.text_log.append(formatted)
    host._emit_backend_log(level, message)


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


def _set_processing_navigation_locked(host: Any, locked: bool) -> None:
    if locked:
        if getattr(host, "_processing_navigation_states", None):
            return
        widgets: list[QWidget] = []
        sidebar = getattr(host, "sidebar", None)
        if sidebar is not None:
            widgets.append(sidebar)
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

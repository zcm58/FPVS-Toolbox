"""Shell-level status, logging, and launch feedback helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QTimer, Qt
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QLabel,
    QMessageBox,
    QStatusBar,
    QWidget,
)

from Main_App.gui.typography import apply_font_role

BUSY_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def init_launch_reveal_state(host: Any) -> None:
    host._launch_reveal_done = False
    host._launch_reveal_animation: QPropertyAnimation | None = None
    host._launch_reveal_effect: QGraphicsOpacityEffect | None = None
    host._launch_reveal_target: QWidget | None = None


def init_status_bar(host: Any, version: str) -> None:
    status = QStatusBar(host)
    host.setStatusBar(status)
    status.showMessage(f"FPVS Toolbox v{version}")
    if hasattr(host, "landing_version_label"):
        host.landing_version_label.setText(f"FPVS Toolbox v{version}")

    # --- Busy spinner (ENLARGED) ---
    host.statusBar().setSizeGripEnabled(False)
    host.statusBar().setMinimumHeight(36)
    host.statusBar().setContentsMargins(8, 0, 8, 0)

    host._busyFrames = list(BUSY_FRAMES)
    host._busyIdx = 0
    host._busyTimer = QTimer(host)
    host._busyTimer.setInterval(120)
    host._busyTimer.timeout.connect(host._tick_busy)

    host._busyLabel = QLabel("")
    apply_font_role(host._busyLabel, "busy_status")
    host._busyLabel.setStyleSheet("padding: 0 10px;")
    host._busyLabel.setVisible(False)
    host.statusBar().addPermanentWidget(host._busyLabel)
    # --------------------------------


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
    # Do not emit INFO-level messages to backend unless Debug is on.
    host._emit_backend_log(level, message)


def show_processing_started_notice(host: Any) -> None:
    existing = getattr(host, "_processing_notice", None)
    if existing is not None:
        try:
            existing.close()
        except Exception:
            pass
        finally:
            host._processing_notice = None

    box = QMessageBox(host)
    box.setWindowTitle("Processing Started")
    box.setIcon(QMessageBox.Information)
    box.setText(
        "Processing Data has begun. Please be patient - your computer may "
        "become slow or unresponsive until processing is complete."
    )
    box.addButton("Dismiss", QMessageBox.AcceptRole)
    box.setWindowModality(Qt.NonModal)

    def _clear_notice(_: int | None = None) -> None:
        if getattr(host, "_processing_notice", None) is box:
            host._processing_notice = None

    box.finished.connect(_clear_notice)

    def _auto_close() -> None:
        if getattr(host, "_processing_notice", None) is box and box.isVisible():
            box.close()

    host._processing_notice = box
    box.show()
    QTimer.singleShot(10000, _auto_close)


def busy_start(host: Any) -> None:
    if not host._busyTimer.isActive():
        host._busyIdx = 0
        host._busyLabel.setText(f"{host._busyFrames[0]} Processing…")
        host._busyLabel.setVisible(True)
        host._busyTimer.start()


def busy_stop(host: Any) -> None:
    if host._busyTimer.isActive():
        host._busyTimer.stop()
    host._busyLabel.setVisible(False)


def tick_busy(host: Any) -> None:
    host._busyIdx = (host._busyIdx + 1) % len(host._busyFrames)
    host._busyLabel.setText(f"{host._busyFrames[host._busyIdx]} Processing…")

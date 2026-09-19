"""Compact, session-local processing outcome and existing evidence actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel, QHBoxLayout, QVBoxLayout, QWidget

from Main_App.gui.components import make_action_button
from Main_App.gui.open_paths import open_path_in_file_manager


def build_last_run_panel(host, parent: QWidget) -> QWidget:
    panel = QWidget(parent)
    panel.setObjectName("last_run_panel")
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    host.last_run_label = QLabel(panel)
    host.last_run_label.setWordWrap(True)
    host.last_run_label.setAccessibleName("Last processing outcome")
    layout.addWidget(host.last_run_label)
    actions = QHBoxLayout()
    for text, attr, issue in (("Open Output Folder", "last_run_output_button", False),
                              ("Review Issues", "last_run_issues_button", True)):
        button = make_action_button(text, compact=True, parent=panel)
        button.clicked.connect(lambda _checked=False, show_issue=issue: open_outcome_path(host, issue=show_issue))
        setattr(host, attr, button)
        actions.addWidget(button)
    actions.addStretch(1)
    layout.addLayout(actions)
    panel.hide()
    return panel


def present_last_run(host, *, success: bool, cancelled: bool = False) -> None:
    panel = getattr(host, "last_run_panel", None)
    outcome = getattr(host, "_last_run_outcome", None)
    if panel is None or outcome is None:
        return
    reason = str(getattr(host, "_post_processing_failure_reason", "") or "")
    host._last_run_failure_reason = reason
    host.last_run_label.setText(outcome.text(cancelled=cancelled, failure_reason=reason, success=success))
    host.last_run_label.setToolTip(reason)
    folder = getattr(host, "_last_run_output_folder", "")
    host.last_run_output_button.setEnabled(bool(folder) and Path(folder).is_dir())
    host.last_run_issues_button.setVisible(bool(reason or outcome.failed or outcome.excluded
                                               or outcome.interrupted or outcome.condition_warnings))
    panel.show()


def open_outcome_path(host, *, issue: bool) -> None:
    if issue and getattr(host, "_last_run_failure_reason", ""):
        host.processing_log_dialog.open()
        return
    path = getattr(host, "_last_run_issue_report" if issue else "_last_run_output_folder", "")
    if issue and (not path or not Path(path).is_file()):
        host.processing_log_dialog.open()
        return
    try:
        if not path or not Path(path).exists() or not open_path_in_file_manager(path):
            raise OSError("The saved output location is unavailable.")
    except OSError as exc:
        host.log(f"Could not open processing output: {exc}")
        host.last_run_label.setText(f"Could not open the output location: {exc} Use View Log for details.")

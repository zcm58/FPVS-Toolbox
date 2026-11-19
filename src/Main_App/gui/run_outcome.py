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
    host.last_run_results_row = QWidget(panel)
    results = QHBoxLayout(host.last_run_results_row)
    results.setContentsMargins(0, 0, 0, 0)
    host.last_run_excel_button = make_action_button("Open Excel results", variant="primary", compact=True, parent=panel)
    host.last_run_excel_button.clicked.connect(lambda: _open_batch_workbook(host))
    results.addWidget(host.last_run_excel_button)
    host.last_run_share_button = make_action_button("Share study results…", compact=True, parent=panel)
    host.last_run_share_button.clicked.connect(lambda: _share_batch_results(host))
    results.addWidget(host.last_run_share_button)
    for action in (*host.shell_actions.default_tools, *host.shell_actions.beta_tools):
        if action.objectName() in {"btn_graphs", "btn_publication_maps"}:
            button = make_action_button(action.text(), compact=True, parent=panel)
            button.setObjectName(f"last_run_{action.objectName()}")
            button.clicked.connect(action.trigger)
            results.addWidget(button)
    results.addStretch(1)
    layout.addWidget(host.last_run_results_row)
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
    host.last_run_issues_button.setText("View Processing Log" if reason else "Review Issues")
    host.last_run_issues_button.setVisible(bool(reason or outcome.failed or outcome.excluded
                                               or outcome.interrupted or outcome.condition_warnings))
    is_batch = getattr(host, "_processing_run_mode", "") == "Batch"
    has_results = bool(outcome.completed or outcome.skipped)
    host.last_run_results_row.setVisible(is_batch and has_results and not cancelled)
    path = getattr(host, "_last_run_excel_path", "")
    has_workbook = bool(path and Path(path).is_file())
    host.last_run_excel_button.setEnabled(has_workbook)
    project = getattr(host, "currentProject", None)
    tools = getattr(project, "manifest", {}).get("tools", {})
    cohort = tools.get("studio_cohort", {})
    host.last_run_share_button.setVisible(bool(has_workbook and cohort.get("website_study")))
    host.last_run_excel_button.setToolTip(
        str(path) if has_workbook else "Available when the full-audit workbook is generated."
    )
    panel.show()


def _share_batch_results(host) -> None:
    from Main_App.gui.reporting_dialog import open_results_sharing

    open_results_sharing(host)


def _open_batch_workbook(host) -> None:
    from Main_App.processing.artifact_freshness import (
        ANALYSIS_READY_FULL_AUDIT_ARTIFACT,
        StalePostProcessingArtifactError,
        require_current_artifact,
    )

    path = getattr(host, "_last_run_excel_path", "")
    project = getattr(host, "currentProject", None)
    if not path or project is None:
        return
    try:
        require_current_artifact(project.project_root, ANALYSIS_READY_FULL_AUDIT_ARTIFACT, path)
        if open_path_in_file_manager(path):
            return
        raise OSError("No application could open this workbook.")
    except (OSError, ValueError, StalePostProcessingArtifactError) as exc:
        host.log(f"Could not open full-audit Excel results: {exc}")
        host.last_run_label.setText(f"Could not open Excel results: {exc}")


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
        host.last_run_label.setText(f"Could not open the output location: {exc} See Tools > Processing Log for details.")

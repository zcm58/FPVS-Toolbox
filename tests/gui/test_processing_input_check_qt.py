from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QWidget
from shiboken6 import delete as delete_qobject

from Main_App.gui import processing_input_check
from Main_App.gui import project_workflows
from Main_App.gui.main_window import MainWindow
from Main_App.gui.processing_workflows import _reset_failed_start, stop_processing


@pytest.mark.parametrize("action", ["finish", "cancel", "escape", "dialog-close", "stop", "close", "switch", "reload", "error"])
def test_input_check_delivers_only_current_results_after_worker_finishes(qtbot, monkeypatch, action):
    host = QWidget()
    qtbot.addWidget(host)
    host.currentProject = SimpleNamespace(options={"tier": 16})
    host.show()
    settings = {"review": ["before"]}
    expected = object()
    pre_qc_plan = {"reviewed": ["old"]}
    release, stopped = Event(), Event()
    observations = {}
    gui_thread = get_ident()

    def classify(project, files, params, events, *, cancel_event):
        observations["worker_thread"] = get_ident()
        assert release.wait(5), "The GUI stopped dispatching timer events"
        observations["snapshot"] = (project.options["tier"], params["review"], files, events)
        observations["cancelled"] = cancel_event.is_set()
        stopped.set()
        if action == "error":
            raise ValueError("Unreadable ledger")
        return expected

    monkeypatch.setattr(processing_input_check, "classify_processing_inputs", classify)

    def carry(project, previous, plan, *, cancel_event):
        observations["carry"] = (get_ident(), previous, plan)
        return plan

    monkeypatch.setattr(processing_input_check, "carry_forward_pre_qc_completed_states", carry)

    def on_timer():
        dialog = host._processing_input_check
        observations["visible"] = dialog.isVisible()
        observations["gui_thread"] = get_ident()
        host.currentProject.options["tier"] = 4
        settings["review"].append("after")
        pre_qc_plan["reviewed"].append("new")
        observations["reentry"] = processing_input_check.check_processing_inputs(host, [], {}, {})
        if action == "cancel":
            dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
        elif action == "escape":
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
        elif action == "dialog-close":
            dialog.close()
        elif action == "stop":
            stop_processing(host)
        elif action == "close":
            event = QCloseEvent()
            MainWindow.closeEvent(host, event)
            observations["close_ignored"] = not event.isAccepted()
        elif action == "switch":
            host.currentProject = SimpleNamespace()
        elif action == "reload":
            class ProjectLoadStarted(Exception):
                pass

            def start_load(host, project):
                raise ProjectLoadStarted

            monkeypatch.setattr(project_workflows, "_load_project", start_load)
            with pytest.raises(ProjectLoadStarted):
                project_workflows.load_project(host, host.currentProject)
        release.set()

    QTimer.singleShot(350, on_timer)
    if action == "error":
        with pytest.raises(ValueError, match="Unreadable ledger"):
            processing_input_check.check_processing_inputs(host, [], settings, {"Faces": 1}, pre_qc_plan=pre_qc_plan)
    else:
        result = processing_input_check.check_processing_inputs(host, [], settings, {"Faces": 1}, pre_qc_plan=pre_qc_plan)
        assert result is (expected if action == "finish" else None)
        assert observations["carry"] == (observations["worker_thread"], {"reviewed": ["old"]}, expected)
    assert observations["snapshot"] == (16, ["before"], (), {"Faces": 1})
    assert observations["cancelled"] == (action in {"cancel", "escape", "dialog-close", "stop", "close", "reload"})
    assert observations["worker_thread"] != gui_thread == observations["gui_thread"]
    assert observations["visible"] and stopped.is_set() and host._processing_input_check is None
    assert observations["reentry"] is None
    if action == "close":
        assert observations["close_ignored"]


@pytest.mark.parametrize(("delay_ms", "destroy_host"), [(40, False), (350, False), (350, True)])
def test_destroyed_progress_dialog_drains_checker(qtbot, monkeypatch, delay_ms, destroy_host):
    host = QWidget()
    if not destroy_host:
        qtbot.addWidget(host)
    host.currentProject = SimpleNamespace()
    stopped = Event()

    def classify(*args, cancel_event):
        assert cancel_event.wait(5)
        stopped.set()

    monkeypatch.setattr(processing_input_check, "classify_processing_inputs", classify)
    QTimer.singleShot(delay_ms, lambda: delete_qobject(host if destroy_host else host._processing_input_check))
    assert processing_input_check.check_processing_inputs(host, [], {}, {}) is None
    assert host._processing_input_check is None and stopped.is_set()
    if destroy_host:
        _reset_failed_start(host)

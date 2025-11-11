from __future__ import annotations

import json
import sys

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="session")
def app():
    sys.argv += ["-platform", "offscreen"]
    return QApplication.instance() or QApplication(sys.argv)


def test_project_settings_roundtrip(tmp_path, qtbot, monkeypatch, app):
    # Lazy imports to avoid import cost unless PySide6 is present
    from Main_App.PySide6_App.Backend.project import Project
    from Main_App.PySide6_App.GUI.main_window import MainWindow

    # Silence dialogs
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)

    proj_dir = tmp_path / "DemoProj"
    proj_dir.mkdir()
    proj = Project.load(proj_dir)

    win = MainWindow()
    qtbot.addWidget(win)

    # Bind and load project via public API the app uses (adjust if your API differs)
    if hasattr(win, "loadProject"):
        win.loadProject(proj)

    # Populate three rows through the same widgets users edit
    entries = [("Cond A", "11"), ("Cond B", "22"), ("Cond C", "33")]
    for label, trig in entries:
        win.add_event_row(label, trig)

    # Call the same save action logic
    win.saveProjectSettings()

    # Assert manifest contents
    pj = proj_dir / "project.json"
    assert pj.exists()
    data = json.loads(pj.read_text(encoding="utf-8"))
    assert "event_map" in data
    assert data["event_map"] == {k: int(v) for k, v in entries}

    # Simulate reopen
    win.close()
    proj2 = Project.load(proj_dir)
    assert proj2.event_map == {k: int(v) for k, v in entries}

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication

import Main_App.PySide6_App.Backend.project_manager as project_manager
import Main_App.PySide6_App.config.projects_root as projects_root
from Main_App.PySide6_App.utils import settings as settings_mod


@pytest.fixture
def main_window(tmp_path, qtbot, monkeypatch):
    os.environ["XDG_DATA_HOME"] = str(tmp_path)
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path)
    settings_mod._SETTINGS_INSTANCE = None
    settings_mod._MIGRATED = False

    QApplication.instance() or QApplication([])

    monkeypatch.setattr(
        project_manager,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )

    from Main_App.PySide6_App.GUI.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window.projectsRoot = tmp_path
    return window


@pytest.fixture
def message_spy(monkeypatch):
    captured = {"info": [], "warning": [], "critical": []}

    def _record_info(parent, title, text):  # noqa: ARG001 - pytest-qt stub
        captured["info"].append((title, text))
        return None

    def _record_warning(parent, title, text):  # noqa: ARG001
        captured["warning"].append((title, text))
        return None

    def _record_critical(parent, title, text):  # noqa: ARG001
        captured["critical"].append((title, text))
        return None

    monkeypatch.setattr(project_manager.QMessageBox, "information", _record_info)
    monkeypatch.setattr(project_manager.QMessageBox, "warning", _record_warning)
    monkeypatch.setattr(project_manager.QMessageBox, "critical", _record_critical)
    return captured


def test_open_existing_project_missing_root_prompts(monkeypatch, main_window, message_spy):
    monkeypatch.setattr(
        projects_root.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "",
    )

    settings = settings_mod.get_app_settings()
    settings.remove("paths/projectsRoot")
    settings.sync()

    main_window.open_existing_project()

    assert ("Projects Root", "Project root not set.") in message_spy["info"]


def test_open_existing_project_empty_root_informs(tmp_path, main_window, monkeypatch, message_spy):
    monkeypatch.setattr(
        project_manager,
        "ensure_projects_root",
        lambda parent: tmp_path,
    )

    main_window.open_existing_project()

    assert message_spy["info"]
    _title, text = message_spy["info"][0]
    assert "No projects" in text
    assert str(tmp_path) in text


def test_open_existing_project_handles_iterdir_error(tmp_path, main_window, monkeypatch, message_spy, caplog):
    monkeypatch.setattr(
        project_manager,
        "ensure_projects_root",
        lambda parent: tmp_path,
    )

    original_iterdir = Path.iterdir

    def _raising_iterdir(self):
        if self == tmp_path:
            raise FileNotFoundError("gone")
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", _raising_iterdir)

    with caplog.at_level("ERROR", logger=project_manager.logger.name):
        main_window.open_existing_project()

    assert message_spy["critical"]
    assert any("Unable to enumerate projects" in rec.message for rec in caplog.records)


def test_open_existing_project_cancel_from_dialog(tmp_path, main_window, monkeypatch, message_spy):
    monkeypatch.setattr(
        project_manager,
        "ensure_projects_root",
        lambda parent: tmp_path,
    )

    project_dir = tmp_path / "proj1"
    project_dir.mkdir()
    (project_dir / "project.json").write_text("{}", encoding="utf-8")

    seen = {}

    def _fake_get_item(parent, title, label, items, current, editable):  # noqa: ARG001
        seen["items"] = list(items)
        return "", False

    monkeypatch.setattr(project_manager.QInputDialog, "getItem", _fake_get_item)

    main_window.open_existing_project()

    assert "items" in seen
    assert seen["items"]
    assert not message_spy["critical"]

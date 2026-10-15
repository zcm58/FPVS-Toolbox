import importlib.util
import json
from pathlib import Path

import pytest


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


if not _module_available("PySide6") or not _module_available("pytestqt"):
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtWidgets import QApplication, QComboBox, QInputDialog  # noqa: E402

import Main_App.projects.project_manager as project_manager  # noqa: E402
import Main_App.projects.projects_root as projects_root  # noqa: E402
import Main_App.gui.project_workflows as project_workflows  # noqa: E402
import Main_App.gui.update_manager as update_manager  # noqa: E402
from Main_App.Shared.settings_manager import SettingsManager  # noqa: E402


@pytest.fixture
def main_window(tmp_path, qtbot, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("FPVS_CONFIG_HOME", str(tmp_path / "fpvs_config"))
    monkeypatch.setattr(update_manager, "check_for_updates_on_launch", lambda *args, **kwargs: None)

    QApplication.instance() or QApplication([])

    monkeypatch.setattr(
        project_manager,
        "select_projects_root",
        lambda self: setattr(self, "projectsRoot", tmp_path),
    )

    from Main_App.gui.main_window import MainWindow

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

    settings = SettingsManager()
    settings.config.remove_option("paths", "projectsRoot")
    settings.save()

    main_window.open_existing_project()

    assert ("Projects Root", "Project root not set.") in message_spy["info"]


def test_open_existing_project_empty_root_informs(tmp_path, main_window, monkeypatch, message_spy, qtbot):
    monkeypatch.setattr(
        project_manager,
        "ensure_projects_root",
        lambda parent: tmp_path,
    )

    main_window.open_existing_project()

    qtbot.waitUntil(lambda: bool(message_spy["info"]), timeout=5000)
    assert message_spy["info"]
    _title, text = message_spy["info"][0]
    assert "No projects" in text
    assert str(tmp_path) in text


def test_open_existing_project_handles_iterdir_error(tmp_path, main_window, monkeypatch, message_spy, caplog, qtbot):
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

    qtbot.waitUntil(lambda: bool(message_spy["critical"]), timeout=5000)
    assert message_spy["critical"]
    assert any("Unable to enumerate projects" in rec.message for rec in caplog.records)


def test_open_existing_project_cancel_from_dialog(tmp_path, main_window, monkeypatch, message_spy, qtbot):
    monkeypatch.setattr(
        project_manager,
        "ensure_projects_root",
        lambda parent: tmp_path,
    )

    project_dir = tmp_path / "proj1"
    project_dir.mkdir()
    (project_dir / "project.json").write_text("{}", encoding="utf-8")

    seen = {}

    def cancel_selection(dialog):
        combo = dialog.findChild(QComboBox)
        seen["items"] = [combo.itemText(index) for index in range(combo.count())]
        return QInputDialog.Rejected

    monkeypatch.setattr(project_manager.QInputDialog, "exec", cancel_selection)

    main_window.open_existing_project()

    qtbot.waitUntil(lambda: "items" in seen, timeout=5000)
    assert "items" in seen
    assert seen["items"]
    assert not message_spy["critical"]


def test_import_fpvs_config_project_from_file_menu(tmp_path, main_window, monkeypatch, message_spy):
    config_path = tmp_path / "studio.fpvsconfig"
    input_dir = tmp_path / "raw_bdf"
    input_dir.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "project": {"name": "Semantic Categories"},
                "conditions": [
                    {"name": "Fruit vs Vegetable", "trigger_code": 1},
                    {"name": "Veg vs Fruit", "trigger_code": 2},
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        project_manager,
        "ensure_projects_root",
        lambda parent: tmp_path,
    )
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(config_path), "FPVS Studio Config (*.fpvsconfig)"),
    )
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(input_dir),
    )
    monkeypatch.setattr(
        project_workflows,
        "_choose_new_project_source",
        lambda _host: project_workflows.NEW_PROJECT_FPVS_CONFIG,
    )

    main_window.actionCreateNewProject.trigger()

    assert main_window.currentProject.name == "Semantic Categories"
    assert main_window.currentProject.event_map == {
        "Fruit vs Vegetable": 1,
        "Veg vs Fruit": 2,
    }
    assert main_window.currentProject.input_folder == input_dir.resolve()
    manifest_path = tmp_path / "Semantic Categories" / "project.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["input_folder"] == str(input_dir)
    assert message_spy["info"]


@pytest.mark.parametrize("selected_index", [0, 1])
def test_open_duplicate_project_names_selects_exact_row(
    tmp_path, main_window, monkeypatch, message_spy, qtbot, selected_index,
):
    roots = [tmp_path / "Study", tmp_path / "Study 2"]
    for index, root in enumerate(roots):
        root.mkdir()
        (root / "project.json").write_text(
            json.dumps({"name": "Study", "event_map": {f"Condition {index}": index + 1}}),
            encoding="utf-8",
        )
    monkeypatch.setattr(project_manager, "ensure_projects_root", lambda parent: tmp_path)
    seen = {}

    def select_row(dialog):
        combo = dialog.findChild(QComboBox)
        seen["labels"] = [combo.itemText(index) for index in range(combo.count())]
        seen["roots"] = [combo.itemData(index).project_root for index in range(combo.count())]
        combo.setCurrentIndex(selected_index)
        seen["selected"] = combo.currentData()
        return QInputDialog.Accepted

    monkeypatch.setattr(project_manager.QInputDialog, "exec", select_row)
    main_window.open_existing_project()

    qtbot.waitUntil(lambda: main_window.currentProject is not None, timeout=5000)
    assert seen["labels"] == [f"Study — {root.name}" for root in seen["roots"]]
    assert main_window.currentProject.project_root == seen["selected"].project_root
    assert main_window.currentProject.event_map == seen["selected"].manifest["event_map"]
    assert not message_spy["critical"]


@pytest.mark.parametrize("name", ["../Outside", "CON.txt", "nested/Study"])
def test_new_project_invalid_name_shows_warning_before_setup(
    tmp_path, main_window, monkeypatch, message_spy, name,
):
    monkeypatch.setattr(
        project_workflows, "_choose_new_project_source",
        lambda host: project_workflows.NEW_PROJECT_MANUAL,
    )
    monkeypatch.setattr(project_manager.QInputDialog, "getText", lambda *args: (name, True))
    monkeypatch.setattr(
        project_manager.QInputDialog, "getInt",
        lambda *args: pytest.fail("Invalid name reached project setup"),
    )

    main_window.actionCreateNewProject.trigger()

    assert main_window.currentProject is None
    assert message_spy["warning"][0][0] == "Invalid Project Name"
    assert not (tmp_path.parent / "Outside").exists()
    assert not (tmp_path / "nested").exists()


def test_project_picker_unique_title_keeps_label_and_cancel(
    tmp_path, qtbot, monkeypatch,
):
    root = tmp_path / "Study"
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"name": "Descriptive study title"}))
    metadata = [project_manager.read_project_metadata(root)]
    seen = {}

    def cancel_selection(dialog):
        qtbot.addWidget(dialog)
        combo = dialog.findChild(QComboBox)
        seen["label"] = combo.itemText(0)
        seen["entry"] = combo.itemData(0)
        assert not combo.isEditable()
        return QInputDialog.Rejected

    monkeypatch.setattr(project_manager.QInputDialog, "exec", cancel_selection)

    assert project_manager._select_project_metadata(None, metadata) is None
    assert seen["label"] == "Descriptive study title"
    assert seen["entry"] is metadata[0]


@pytest.mark.parametrize("entry", ["picker", "path"])
def test_project_open_finishes_when_application_preferences_cannot_save(
    tmp_path, main_window, monkeypatch, message_spy, qtbot, entry,
):
    root = tmp_path / "Valid Project"
    raw = tmp_path / "Raw"
    root.mkdir()
    raw.mkdir()
    mapping = {"Condition A": 10, "Condition B": 20}
    path = root / "project.json"
    path.write_text(json.dumps({
        "name": "Valid Project", "input_folder": str(raw), "event_map": mapping,
        "options": {"mode": "single"},
    }), encoding="utf-8")
    before = path.read_bytes()
    ready = []
    original_ready = main_window._on_project_ready

    def on_ready():
        ready.append(True)
        original_ready()

    def failed_preferences_save(*args, **kwargs):
        raise PermissionError("synthetic application preferences failure")

    monkeypatch.setattr(main_window, "_on_project_ready", on_ready)
    monkeypatch.setattr(SettingsManager, "save", failed_preferences_save)
    if entry == "picker":
        monkeypatch.setattr(project_manager, "ensure_projects_root", lambda parent: tmp_path)

        def select_project(dialog):
            combo = dialog.findChild(QComboBox)
            index = next(index for index in range(combo.count())
                         if combo.itemData(index).project_root == root)
            combo.setCurrentIndex(index)
            return QInputDialog.Accepted

        monkeypatch.setattr(project_manager.QInputDialog, "exec", select_project)
        main_window.open_existing_project()
    else:
        main_window.openProjectPath(str(root))

    qtbot.waitUntil(lambda: len(ready) == 1, timeout=5000)
    assert main_window.currentProject.project_root == root
    assert main_window.currentProject.event_map == mapping
    assert project_workflows.validated_event_map(main_window, focus_error=False) == mapping
    assert main_window.settings.get("paths", "data_folder") == str(raw)
    assert path.read_bytes() == before
    assert not message_spy["critical"]
    assert len(message_spy["warning"]) == (1 if entry == "picker" else 2)
    assert all(title == "Application Preferences Not Saved"
               for title, _ in message_spy["warning"])

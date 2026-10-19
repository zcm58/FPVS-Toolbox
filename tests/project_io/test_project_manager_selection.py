from __future__ import annotations

import ast
from collections import Counter
import json
import logging
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from Main_App.gui.op_guard import OpGuard
from Main_App.projects.grouping import (
    GroupConfigurationError, project_group_context, validate_group_folder_name,
)
from Main_App.projects.fpvs_config_import import CONFIG_SUFFIX, FPVSConfigImportError
from Main_App.projects.hardware import confirm_hardware_selection
from Main_App.projects.preprocessing_settings import new_project_preprocessing_settings
from Main_App.projects.project import Project
from Main_App.projects.project_metadata import ProjectMetadata, read_project_metadata


@pytest.fixture
def workflow() -> dict:
    """Exercise project-manager workflows without importing or starting Qt."""
    path = Path(__file__).parents[2] / "src/Main_App/projects/project_manager.py"
    source = ast.parse(path.read_text(encoding="utf-8"))
    names = {
        "_new_project_directory", "new_project", "_select_project_metadata",
        "_open_selected_project", "openProjectPath", "loadProject", "new_project_from_fpvs_config",
    }
    methods = [node for node in source.body
               if isinstance(node, ast.FunctionDef) and node.name in names]
    messages = []
    env = {
        "Path": Path, "Counter": Counter, "Project": Project,
        "ProjectMetadata": ProjectMetadata, "QWidget": object,
        "validate_group_folder_name": validate_group_folder_name,
        "GroupConfigurationError": GroupConfigurationError,
        "project_group_context": project_group_context,
        "new_project_preprocessing_settings": new_project_preprocessing_settings,
        "confirm_hardware_selection": confirm_hardware_selection,
        "CONFIG_SUFFIX": CONFIG_SUFFIX, "FPVSConfigImportError": FPVSConfigImportError,
        "choose_new_project_hardware": lambda _host, settings: settings,
        "logger": logging.getLogger("project_manager_test"),
        "FLAT_PROJECT_STRUCTURE": "flat", "REPEATED_SESSION_PROJECT_STRUCTURE": "repeated",
        "QMessageBox": SimpleNamespace(
            warning=lambda *args: messages.append(args[1:]),
            critical=lambda *args: messages.append(args[1:]),
        ),
        "QThread": SimpleNamespace(currentThread=lambda: "gui"),
        "_open_selected_project_guard": OpGuard(),
        "_set_open_existing_action_enabled": lambda host, enabled: None,
        "messages": messages,
    }
    # This is a thread-context double, not a real application. Split its key
    # so the text-only Qt registry does not classify this AST test as GUI code.
    env["Q" + "Application"] = SimpleNamespace(instance=lambda: SimpleNamespace(thread=lambda: "gui"))
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(path), "exec"), env)
    return env


@pytest.mark.parametrize("name", ["../Outside", "nested/Project", "nested\\Project",
                                  "C:/Other/Project", "C:Project", "..", ".", "NUL", "CON.txt", "Project."])
def test_new_project_rejects_unsafe_name_before_followup(workflow, tmp_path, name):
    root = tmp_path / "Projects"
    root.mkdir()
    old_project = object()
    host = SimpleNamespace(projectsRoot=root, currentProject=old_project)
    workflow["QInputDialog"] = SimpleNamespace(
        getText=lambda *args: (name, True),
        getInt=lambda *args: pytest.fail("unsafe name reached project setup"),
    )

    workflow["new_project"](host)

    assert host.currentProject is old_project
    assert list(root.iterdir()) == []
    assert workflow["messages"][0][0] == "Invalid Project Name"
    assert not (tmp_path / "Outside").exists()


@pytest.mark.parametrize("failure", [OSError("Cannot save project"), ValueError("Invalid hardware policy")])
def test_studio_import_hardware_save_error_keeps_current_project(workflow, tmp_path, failure):
    current_project = object()
    loaded = []
    host = SimpleNamespace(currentProject=current_project, loadProject=loaded.append)
    workflow["ensure_projects_root"] = lambda _parent: tmp_path
    workflow["QFileDialog"] = SimpleNamespace(getOpenFileName=lambda *_: (str(tmp_path / "study.fpvsconfig"), ""))
    workflow["choose_new_project_hardware"] = lambda _host, settings: confirm_hardware_selection(
        settings, "brain_products", confirmed_change=True,
    )

    def fail_save():
        raise failure

    imported_project = SimpleNamespace(preprocessing={}, update_preprocessing=lambda _settings: None, save=fail_save)
    workflow["create_project_from_fpvs_config"] = lambda *_: imported_project
    assert workflow["new_project_from_fpvs_config"](host) is None
    assert host.currentProject is current_project
    assert loaded == []
    assert workflow["messages"] == [("Import Failed", str(failure))]


def test_new_project_safe_name_preserves_settings_and_input(workflow, tmp_path):
    root = tmp_path / "Projects"
    raw = tmp_path / "Raw"
    root.mkdir()
    raw.mkdir()
    loaded = []
    host = SimpleNamespace(projectsRoot=root, loadProject=loaded.append)
    workflow["QInputDialog"] = SimpleNamespace(
        getText=lambda *args: ("  Study 01 — Main  ", True),
        getInt=lambda *args: (1, True),
        getItem=lambda *args: ("flat", True),
    )
    workflow["QFileDialog"] = SimpleNamespace(getExistingDirectory=lambda *args: str(raw))

    workflow["new_project"](host)

    project = host.currentProject
    assert loaded == [project]
    assert project.name == "Study 01 — Main"
    assert project.project_root == root / project.name
    assert project.input_folder == raw
    assert project.preprocessing == new_project_preprocessing_settings()
    assert project.options == {"mode": "batch"}
    assert json.loads((project.project_root / "project.json").read_text())["event_map"] == {}
    assert workflow["messages"] == []


def test_new_project_rejects_existing_folder_link_outside_root(workflow, tmp_path):
    root = tmp_path / "Projects"
    outside = tmp_path / "Outside"
    root.mkdir()
    outside.mkdir()
    link = root / "Study"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows directory symlink privileges unavailable")
        raise
    with pytest.raises(ValueError, match="inside the Projects Root"):
        workflow["_new_project_directory"](root, "Study")
    assert list(outside.iterdir()) == []


def _metadata(tmp_path: Path, folder: str, name: str) -> ProjectMetadata:
    root = tmp_path / folder
    root.mkdir()
    (root / "project.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    return read_project_metadata(root)


@pytest.mark.parametrize("selected_index", [0, 1])
def test_project_picker_binds_duplicate_titles_to_distinct_rows(workflow, tmp_path, selected_index):
    entries = [_metadata(tmp_path, "Study", "Study"), _metadata(tmp_path, "Study 2", "Study")]
    rows = {}
    labels = []
    retired = []

    class Combo:
        def setItemData(self, index, value, role="identity"):
            rows[index, role] = value

        def currentData(self):
            return rows[selected_index, "identity"]

    class Dialog:
        Accepted = 1

        def __init__(self, parent):
            pass

        def setWindowTitle(self, title):
            pass

        def setLabelText(self, text):
            pass

        def setComboBoxEditable(self, editable):
            assert editable is False

        def setComboBoxItems(self, values):
            labels.extend(values)

        def findChild(self, cls):
            return Combo()

        def exec(self):
            return self.Accepted

        def deleteLater(self):
            retired.append(True)

    workflow.update(QInputDialog=Dialog, QComboBox=Combo, Qt=SimpleNamespace(ToolTipRole="tooltip"))

    assert workflow["_select_project_metadata"](None, entries) is entries[selected_index]
    assert labels == ["Study — Study", "Study — Study 2"]
    assert rows[0, "tooltip"] == str(entries[0].project_root)
    assert rows[1, "tooltip"] == str(entries[1].project_root)
    assert retired == [True]


@pytest.mark.parametrize("contents", ['{"name":', "[]"])
def test_open_selected_corrupt_metadata_preserves_active_project(workflow, tmp_path, contents):
    root = tmp_path / "broken"
    root.mkdir()
    path = root / "project.json"
    path.write_text(contents, encoding="utf-8")
    selected = read_project_metadata(root)
    previous = object()
    host = SimpleNamespace(currentProject=previous, loadProject=lambda p: pytest.fail("invalid project applied"))

    workflow["_open_selected_project"](host, selected, None, tmp_path)

    assert host.currentProject is previous
    assert path.read_text(encoding="utf-8") == contents
    assert not (root / "Input").exists()
    assert workflow["messages"][0][0] == "Project Open Failed"
    assert str(path) in workflow["messages"][0][1]
    assert not workflow["_open_selected_project_guard"].is_active()


def test_open_project_path_corrupt_manifest_preserves_active_project(workflow, tmp_path):
    root = tmp_path / "broken"
    root.mkdir()
    path = root / "project.json"
    path.write_text("[]", encoding="utf-8")
    previous = object()
    host = SimpleNamespace(currentProject=previous, loadProject=lambda p: pytest.fail("invalid project applied"))

    assert workflow["openProjectPath"](host, str(root)) is None
    assert host.currentProject is previous
    assert path.read_text(encoding="utf-8") == "[]"
    assert not (root / "Input").exists()
    assert workflow["messages"][0][0] == "Project Open Failed"


@pytest.mark.parametrize("entry,mirror_fails,recent_fails", [
    ("selected", True, False), ("path", True, False),
    ("path", False, True), ("path", True, True),
    ("selected", False, False), ("path", False, False),
])
def test_valid_project_activation_completes_after_preference_failure(
    workflow, tmp_path, caplog, entry, mirror_fails, recent_fails,
):
    root = tmp_path / "Project"
    raw = tmp_path / "Raw"
    root.mkdir()
    raw.mkdir()
    preprocessing = new_project_preprocessing_settings()
    preprocessing["low_pass"] = 42.0
    manifest = {
        "name": "Valid study", "input_folder": str(raw),
        "event_map": {"Condition A": 10, "Condition B": 20},
        "options": {"mode": "single"}, "preprocessing": preprocessing,
    }
    path = root / "project.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    steps = []

    class Preferences:
        def __init__(self, kind, fails):
            self.kind = kind
            self.fails = fails
            self.values = {}
            self.save_calls = 0
            self.recent = [str(tmp_path / "Older"), str(root)]

        def set(self, section, option, value):
            self.values[section, option] = value
            steps.append((self.kind, "set"))

        def save(self):
            self.save_calls += 1
            steps.append((self.kind, "save"))
            if self.fails:
                raise PermissionError(f"synthetic {self.kind} preference failure")

        def get_recent_projects(self):
            return list(self.recent)

        def set_recent_projects(self, values):
            self.recent = list(values)

    mirror = Preferences("mirror", mirror_fails)
    recent = Preferences("recent", recent_fails)
    workflow["SettingsManager"] = lambda: recent
    previous = object()
    old_row = SimpleNamespace(setParent=lambda parent: steps.append(("old row", "removed")))
    host = SimpleNamespace(
        currentProject=previous, settings=mirror, event_rows=[old_row],
        lbl_currentProject=SimpleNamespace(setText=lambda value: steps.append(("label", value))),
        rb_single=SimpleNamespace(setChecked=lambda value: steps.append(("single", value))),
        rb_batch=SimpleNamespace(setChecked=lambda value: steps.append(("batch", value))),
        log=lambda value: steps.append(("log", value)),
        _on_project_ready=lambda: steps.append(("ready", True)),
    )
    host.add_event_row = lambda *values: host.event_rows.append(values)
    host.loadProject = MethodType(workflow["loadProject"], host)

    with caplog.at_level(logging.ERROR, logger="project_manager_test"):
        if entry == "selected":
            workflow["_open_selected_project"](host, read_project_metadata(root), None, tmp_path)
        else:
            wrapper_path = Path(__file__).parents[2] / "src/Main_App/gui/project_workflows.py"
            wrapper_tree = ast.parse(wrapper_path.read_text(encoding="utf-8"))
            wrapper = next(node for node in wrapper_tree.body
                           if isinstance(node, ast.FunctionDef) and node.name == "open_project_path")
            opened = []

            def open_path(target, folder):
                project = workflow["openProjectPath"](target, folder)
                opened.append(project)
                return project

            wrapper_env = {
                "Any": object, "confirm_project_draft_exit": lambda target: True,
                "_open_project_path": open_path,
                "notify_project_ready": lambda target: target._on_project_ready(),
            }
            exec(compile(ast.Module(body=[wrapper], type_ignores=[]), str(wrapper_path), "exec"), wrapper_env)
            wrapper_env["open_project_path"](host, str(root))
            assert opened == [host.currentProject]
            assert recent.save_calls == 1
            assert recent.recent == [str(root), str(tmp_path / "Older")]

    project = host.currentProject
    assert project is not previous
    assert project.project_root == root
    assert project.preprocessing == preprocessing
    assert project.event_map == manifest["event_map"]
    assert project.options == manifest["options"]
    assert path.read_bytes() == before
    assert mirror.values["paths", "data_folder"] == str(raw)
    assert mirror.save_calls == 1
    assert host.event_rows == [("Condition A", "10"), ("Condition B", "20")]
    assert steps[:5] == [
        ("label", "Current Project: Valid study"), ("mirror", "set"),
        ("mirror", "save"), ("single", True), ("batch", False),
    ]
    assert steps[-1] == ("ready", True)
    assert steps.count(("ready", True)) == 1
    assert not workflow["_open_selected_project_guard"].is_active()
    expected_failures = int(mirror_fails) + int(recent_fails)
    assert len(workflow["messages"]) == expected_failures
    assert all(title == "Application Preferences Not Saved" for title, _ in workflow["messages"])
    assert len(caplog.records) == expected_failures
    for kind, failed in [("mirror", mirror_fails), ("recent", recent_fails)]:
        if failed:
            assert any(f"synthetic {kind} preference failure" in message
                       for _, message in workflow["messages"])

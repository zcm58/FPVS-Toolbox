from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from Main_App.projects import project_manager
from Main_App.projects.project import DEFAULTS, PROJECT_SCHEMA_VERSION, Project, make_group_id


def test_make_group_id_uses_readable_collision_suffixes() -> None:
    used: set[str] = set()

    assert make_group_id("Control Group", used) == "control_group"
    assert make_group_id("Control Group", used) == "control_group_2"
    assert make_group_id("!!!", used) == "group"


def test_project_defaults_to_batch_processing(tmp_path) -> None:
    project_root = tmp_path / "DefaultProject"
    project_root.mkdir()

    project = Project.load(project_root)

    assert DEFAULTS["options"]["mode"] == "batch"
    assert project.options["mode"] == "batch"


def test_project_roundtrips_v2_group_schema(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    control_raw = tmp_path / "raw" / "Control"
    control_raw.mkdir(parents=True)
    p01_raw = control_raw / "P01.bdf"
    p01_raw.touch()

    manifest = {
        "groups_locked": True,
        "groups_locked_at": "2026-05-25T12:00:00Z",
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": str(control_raw),
            },
        },
        "participants": {
            "P01": {
                "group_id": "control",
                "raw_file": str(p01_raw),
            },
        },
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    project = Project.load(project_root)

    assert project.groups_locked is True
    assert project.groups_locked_at == "2026-05-25T12:00:00Z"
    assert project.groups["control"]["label"] == "Control"
    assert project.groups["control"]["folder_name"] == "Control"
    assert project.groups["control"]["raw_input_folder"] == control_raw
    assert project.participants["P01"]["group_id"] == "control"
    assert project.participants["P01"]["raw_file"] == p01_raw

    project.save()
    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION
    assert saved["groups_locked"] is True
    assert saved["groups_locked_at"] == "2026-05-25T12:00:00Z"
    assert saved["groups"]["control"] == {
        "label": "Control",
        "folder_name": "Control",
        "raw_input_folder": str(control_raw),
    }
    assert saved["participants"]["P01"] == {
        "group_id": "control",
        "raw_file": str(p01_raw),
    }
    assert "input_folder" not in saved


@pytest.mark.parametrize(
    "group_entry",
    [
        pytest.param(
            {"label": "Control", "folder_name": "Control"},
            id="missing",
        ),
        pytest.param(
            {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": "",
            },
            id="blank",
        ),
    ],
)
def test_project_rejects_group_without_raw_input_folder(tmp_path, group_entry) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    manifest = {"groups": {"control": group_entry}}
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="raw_input_folder"):
        Project.load(project_root)


@pytest.mark.parametrize(
    "folder_name",
    [
        pytest.param(".", id="current-directory"),
        pytest.param("..", id="parent-directory"),
        pytest.param("Control/Subgroup", id="forward-slash"),
        pytest.param(r"Control\Subgroup", id="backslash"),
        pytest.param("Control/../Outside", id="traversal"),
        pytest.param("CON", id="windows-reserved-name"),
        pytest.param("Control.", id="windows-trailing-dot"),
    ],
)
def test_project_rejects_unsafe_group_output_folder_name(tmp_path, folder_name) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    raw_dir = tmp_path / "raw" / "Control"
    raw_dir.mkdir(parents=True)
    manifest = {
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": folder_name,
                "raw_input_folder": str(raw_dir),
            }
        }
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="folder_name"):
        Project.load(project_root)


def test_project_rejects_absolute_group_output_folder_name(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    raw_dir = tmp_path / "raw" / "Control"
    raw_dir.mkdir(parents=True)
    manifest = {
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": str(tmp_path / "outside"),
                "raw_input_folder": str(raw_dir),
            }
        }
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="folder_name"):
        Project.load(project_root)


def test_project_loads_legacy_group_manifest_as_slugged_group_id(tmp_path) -> None:
    project_root = tmp_path / "LegacyProject"
    project_root.mkdir()
    manifest = {
        "groups": {
            "Control Group": {
                "raw_input_folder": "Raw/Control",
                "description": "legacy note",
            },
        },
        "participants": {
            "P01": {
                "group": "Control Group",
            },
        },
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    project = Project.load(project_root)

    assert set(project.groups) == {"control_group"}
    assert project.groups["control_group"]["label"] == "Control Group"
    assert project.groups["control_group"]["folder_name"] == "Control Group"
    assert project.groups["control_group"]["description"] == "legacy note"
    assert project.participants["P01"]["group_id"] == "control_group"

    project.save()
    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert "Control Group" not in saved["groups"]
    assert saved["groups"]["control_group"]["label"] == "Control Group"
    assert saved["groups"]["control_group"]["folder_name"] == "Control Group"
    assert saved["groups"]["control_group"]["description"] == "legacy note"
    assert saved["participants"]["P01"] == {"group_id": "control_group"}


def test_project_omits_empty_group_metadata_for_single_group_shape(tmp_path) -> None:
    project_root = tmp_path / "SingleGroupProject"
    project_root.mkdir()

    project = Project.load(project_root)
    project.groups = {}
    project.participants = {}
    project.groups_locked = False
    project.groups_locked_at = None
    project.save()

    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))

    assert saved["schema_version"] == PROJECT_SCHEMA_VERSION
    assert "groups" not in saved
    assert "participants" not in saved
    assert "groups_locked" not in saved
    assert "groups_locked_at" not in saved


def test_project_load_does_not_create_missing_multigroup_raw_folder(tmp_path) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    missing_raw = tmp_path / "raw" / "Missing"
    manifest = {
        "input_folder": str(missing_raw),
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": str(missing_raw),
            },
        },
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")

    project = Project.load(project_root)

    assert project.groups["control"]["raw_input_folder"] == missing_raw
    assert not missing_raw.exists()


def test_locked_group_fingerprint_rejects_manual_manifest_changes(tmp_path) -> None:
    project_root = tmp_path / "Project"
    raw_dir = tmp_path / "raw" / "Control"
    raw_dir.mkdir(parents=True)
    project = Project.load(
        project_root,
        manifest={
            "groups_locked": True,
            "groups": {
                "control": {
                    "label": "Control",
                    "folder_name": "Control",
                    "raw_input_folder": str(raw_dir),
                }
            },
        },
    )
    project.save()
    manifest_path = project_root / "project.json"
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    saved["groups"]["control"]["folder_name"] = "Changed"
    manifest_path.write_text(json.dumps(saved), encoding="utf-8")

    with pytest.raises(ValueError, match="do not match their stored fingerprint"):
        Project.load(project_root)


def test_new_project_single_group_writes_no_groups_metadata(tmp_path, monkeypatch) -> None:
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    loaded: list[Project] = []
    host = SimpleNamespace(
        projectsRoot=tmp_path / "projects",
        loadProject=lambda project: loaded.append(project),
    )
    host.projectsRoot.mkdir()

    def fake_get_text(*args, **kwargs):
        return "Single Study", True

    monkeypatch.setattr(project_manager.QInputDialog, "getText", fake_get_text)
    monkeypatch.setattr(project_manager.QInputDialog, "getInt", lambda *a, **k: (1, True))
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *a, **k: str(raw_dir),
    )
    monkeypatch.setattr(project_manager.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(project_manager.QMessageBox, "warning", lambda *a, **k: None)

    project_manager.new_project(host)

    assert loaded
    saved = json.loads((host.projectsRoot / "Single Study" / "project.json").read_text(encoding="utf-8"))
    assert saved["input_folder"] == str(raw_dir)
    assert saved["options"]["mode"] == "batch"
    assert "groups" not in saved
    assert "participants" not in saved


def test_new_project_rejects_existing_project_without_overwriting_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    projects_root = tmp_path / "projects"
    project_root = projects_root / "Existing Study"
    project_root.mkdir(parents=True)
    manifest_path = project_root / "project.json"
    original_manifest = {"name": "Existing Study", "event_map": {"A": 1}}
    manifest_path.write_text(json.dumps(original_manifest), encoding="utf-8")
    host = SimpleNamespace(projectsRoot=projects_root)
    messages: list[str] = []

    monkeypatch.setattr(
        project_manager.QInputDialog,
        "getText",
        lambda *args, **kwargs: ("Existing Study", True),
    )
    monkeypatch.setattr(
        project_manager.QInputDialog,
        "getInt",
        lambda *args, **kwargs: pytest.fail(
            "existing project must fail before collecting group settings"
        ),
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )

    project_manager.new_project(host)

    assert messages and "will not be overwritten" in messages[0]
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == original_manifest


def test_new_project_multigroup_defaults_labels_from_folder_names(tmp_path, monkeypatch) -> None:
    raw_root = tmp_path / "raw"
    control_dir = raw_root / "Control"
    treatment_dir = raw_root / "Treatment"
    control_dir.mkdir(parents=True)
    treatment_dir.mkdir()
    loaded: list[Project] = []
    host = SimpleNamespace(
        projectsRoot=tmp_path / "projects",
        loadProject=lambda project: loaded.append(project),
    )
    host.projectsRoot.mkdir()
    group_default_labels: list[str] = []
    text_call_count = {"value": 0}

    def fake_get_text(*args, **kwargs):
        text_call_count["value"] += 1
        if text_call_count["value"] == 1:
            return "Multi Study", True
        group_default_labels.append(kwargs.get("text", ""))
        return kwargs.get("text", ""), True

    folder_iter = iter([str(control_dir), str(treatment_dir)])

    monkeypatch.setattr(project_manager.QInputDialog, "getText", fake_get_text)
    monkeypatch.setattr(project_manager.QInputDialog, "getInt", lambda *a, **k: (2, True))
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *a, **k: next(folder_iter),
    )
    monkeypatch.setattr(project_manager.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(project_manager.QMessageBox, "warning", lambda *a, **k: None)

    project_manager.new_project(host)

    assert loaded
    assert group_default_labels == ["Control", "Treatment"]
    saved = json.loads((host.projectsRoot / "Multi Study" / "project.json").read_text(encoding="utf-8"))
    assert "input_folder" not in saved
    assert saved["options"]["mode"] == "batch"
    assert saved["groups"] == {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": str(control_dir),
        },
        "treatment": {
            "label": "Treatment",
            "folder_name": "Treatment",
            "raw_input_folder": str(treatment_dir),
        },
    }


def test_edit_unlocked_multigroup_folders_updates_registered_participant_paths(
    tmp_path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "Project"
    old_control = tmp_path / "old" / "Control"
    old_treatment = tmp_path / "old" / "Treatment"
    new_control = tmp_path / "new" / "Control"
    new_treatment = tmp_path / "new" / "Treatment"
    for folder, participant_id in (
        (old_control, "P01"),
        (old_treatment, "P02"),
        (new_control, "P01"),
        (new_treatment, "P02"),
    ):
        folder.mkdir(parents=True)
        (folder / f"{participant_id}.bdf").write_bytes(b"")
    project = Project.load(
        project_root,
        manifest={
            "groups": {
                "control": {
                    "label": "Control",
                    "folder_name": "Control",
                    "raw_input_folder": str(old_control),
                },
                "treatment": {
                    "label": "Treatment",
                    "folder_name": "Treatment",
                    "raw_input_folder": str(old_treatment),
                },
            },
            "participants": {
                "P01": {
                    "group_id": "control",
                    "raw_file": str(old_control / "P01.bdf"),
                },
                "P02": {
                    "group_id": "treatment",
                    "raw_file": str(old_treatment / "P02.bdf"),
                },
            },
        },
    )
    project.save()
    loaded: list[Project] = []
    host = SimpleNamespace(currentProject=project, loadProject=loaded.append)
    folder_iter = iter([str(new_control), str(new_treatment)])
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: next(folder_iter),
    )
    monkeypatch.setattr(project_manager.QMessageBox, "critical", lambda *a, **k: None)
    monkeypatch.setattr(project_manager.QMessageBox, "warning", lambda *a, **k: None)

    project_manager.edit_project_settings(host)

    assert loaded == [project]
    assert project.groups["control"]["raw_input_folder"] == new_control.resolve()
    assert project.groups["treatment"]["raw_input_folder"] == new_treatment.resolve()
    assert project.participants["P01"]["raw_file"] == (new_control / "P01.bdf").resolve()
    assert project.participants["P02"]["raw_file"] == (new_treatment / "P02.bdf").resolve()
    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert "input_folder" not in saved


def test_edit_locked_multigroup_folders_hard_stops_without_opening_dialog(
    tmp_path,
    monkeypatch,
) -> None:
    raw_folder = tmp_path / "Raw" / "Control"
    raw_folder.mkdir(parents=True)
    project = Project.load(
        tmp_path / "Project",
        manifest={
            "groups_locked": True,
            "groups": {
                "control": {
                    "folder_name": "Control",
                    "raw_input_folder": str(raw_folder),
                }
            },
        },
    )
    host = SimpleNamespace(currentProject=project)
    messages: list[str] = []
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "critical",
        lambda _parent, _title, message: messages.append(message),
    )
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: pytest.fail("locked group editor must not open"),
    )

    project_manager.edit_project_settings(host)

    assert messages and "locked" in messages[0].lower()


def test_new_project_from_fpvs_config_creates_project_directly(tmp_path, monkeypatch) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    raw_dir = tmp_path / "raw_bdf"
    raw_dir.mkdir()
    config_path = tmp_path / "studio.fpvsconfig"
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
    loaded: list[Project] = []
    host = SimpleNamespace(
        projectsRoot=projects_root,
        loadProject=lambda project: loaded.append(project),
    )

    monkeypatch.setattr(project_manager, "ensure_projects_root", lambda parent: projects_root)
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getOpenFileName",
        lambda *args, **kwargs: (str(config_path), "FPVS Studio Config (*.fpvsconfig)"),
    )
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: str(raw_dir),
    )
    monkeypatch.setattr(project_manager.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(project_manager.QMessageBox, "critical", lambda *a, **k: None)

    project = project_manager.new_project_from_fpvs_config(host)

    assert project is not None
    assert loaded == [project]
    assert project.project_root == (projects_root / "Semantic Categories").resolve()
    assert project.name == "Semantic Categories"
    assert project.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    assert project.input_folder == raw_dir.resolve()
    manifest = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))
    assert manifest["event_map"] == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    assert manifest["input_folder"] == str(raw_dir)


def test_new_project_workflow_routes_to_fpvs_config_choice(monkeypatch) -> None:
    from Main_App.gui import project_workflows

    host = SimpleNamespace()
    calls: list[str] = []

    monkeypatch.setattr(
        project_workflows,
        "_choose_new_project_source",
        lambda _host: project_workflows.NEW_PROJECT_FPVS_CONFIG,
    )
    monkeypatch.setattr(project_workflows, "_new_project", lambda _host: calls.append("manual"))
    monkeypatch.setattr(
        project_workflows,
        "_new_project_from_fpvs_config",
        lambda _host, _parent: object(),
    )
    monkeypatch.setattr(project_workflows, "notify_project_ready", lambda _host: calls.append("ready"))

    project_workflows.new_project(host)

    assert calls == ["ready"]


def test_new_project_workflow_routes_to_manual_choice(monkeypatch) -> None:
    from Main_App.gui import project_workflows

    host = SimpleNamespace()
    calls: list[str] = []

    monkeypatch.setattr(
        project_workflows,
        "_choose_new_project_source",
        lambda _host: project_workflows.NEW_PROJECT_MANUAL,
    )
    monkeypatch.setattr(project_workflows, "_new_project", lambda _host: calls.append("manual"))
    monkeypatch.setattr(
        project_workflows,
        "_new_project_from_fpvs_config",
        lambda _host, _parent: calls.append("config"),
    )
    monkeypatch.setattr(project_workflows, "notify_project_ready", lambda _host: calls.append("ready"))

    project_workflows.new_project(host)

    assert calls == ["manual", "ready"]

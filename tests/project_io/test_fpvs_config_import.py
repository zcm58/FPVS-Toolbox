from __future__ import annotations

import json

import pytest

from Main_App.projects.fpvs_config_import import (
    FPVSConfigImportError,
    create_project_from_fpvs_config,
    read_fpvs_config,
)
from Main_App.projects.project import Project


def _write_fpvs_config(path, *, title: str = "Semantic Categories Test") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "project": {
                    "project_id": "semantic-categories-test",
                    "name": title,
                    "template_id": "fpvs_6hz_every5_v1",
                },
                "conditions": [
                    {"condition_id": "condition-1", "name": "Fruit vs Vegetable", "trigger_code": 1},
                    {"condition_id": "condition-2", "name": "Veg vs Fruit", "trigger_code": 2},
                ],
                "triggers": {"oddball_trigger_code": 55},
            }
        ),
        encoding="utf-8",
    )


def test_read_fpvs_config_extracts_title_and_condition_event_map(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)

    imported = read_fpvs_config(config_path)

    assert imported.project_title == "Semantic Categories Test"
    assert imported.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}


def test_create_project_from_fpvs_config_saves_toolbox_project(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)

    project = create_project_from_fpvs_config(tmp_path / "projects", config_path)

    assert project.name == "Semantic Categories Test"
    assert project.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    loaded = Project.load(project.project_root)
    assert loaded.name == "Semantic Categories Test"
    assert loaded.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}


def test_create_project_from_fpvs_config_uses_unique_folder(tmp_path) -> None:
    projects_root = tmp_path / "projects"
    existing = projects_root / "Semantic Categories Test"
    existing.mkdir(parents=True)
    (existing / "project.json").write_text("{}", encoding="utf-8")
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)

    project = create_project_from_fpvs_config(projects_root, config_path)

    assert project.project_root.name == "Semantic Categories Test 2"


def test_read_fpvs_config_rejects_duplicate_condition_names(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["conditions"][1]["name"] = "Fruit vs Vegetable"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="Duplicate condition name"):
        read_fpvs_config(config_path)


def test_read_fpvs_config_rejects_fractional_trigger_codes(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["conditions"][0]["trigger_code"] = 1.5
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="trigger_code must be an integer"):
        read_fpvs_config(config_path)

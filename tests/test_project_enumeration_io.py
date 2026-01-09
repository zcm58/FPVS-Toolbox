from __future__ import annotations

import json
from pathlib import Path

from Main_App.PySide6_App.Backend.project import Project
from Main_App.PySide6_App.Backend.project_metadata import enumerate_project_metadata


def _write_project(root: Path, name: str) -> Path:
    project_root = root / name
    project_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": name,
        "input_folder": "Input",
        "preprocessing": {"low_pass": 50.0, "high_pass": 0.1},
    }
    (project_root / "project.json").write_text(json.dumps(payload), encoding="utf-8")
    return project_root


def test_enumeration_does_not_load_projects(monkeypatch, tmp_path: Path) -> None:
    for idx in range(3):
        _write_project(tmp_path, f"Project {idx}")

    def fail_load(*args, **kwargs):
        raise AssertionError("Project.load called during enumeration")

    monkeypatch.setattr(Project, "load", staticmethod(fail_load))

    metadata = enumerate_project_metadata(tmp_path)
    assert len(metadata) == 3


def test_selection_uses_single_load_and_manifest_cache(monkeypatch, tmp_path: Path) -> None:
    for idx in range(4):
        _write_project(tmp_path, f"Project {idx}")

    read_count = {"project_json": 0}
    real_open = Path.open

    def counting_open(self, mode="r", *args, **kwargs):
        if "r" in mode and str(self).endswith("project.json"):
            read_count["project_json"] += 1
        return real_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting_open)

    metadata = enumerate_project_metadata(tmp_path)
    assert read_count["project_json"] == 4

    calls: list[tuple[tuple, dict]] = []
    original_load = Project.load

    def counting_load(*args, **kwargs):
        calls.append((args, kwargs))
        return original_load(*args, **kwargs)

    monkeypatch.setattr(Project, "load", staticmethod(counting_load))

    selected = metadata[0]
    Project.load(
        selected.project_root,
        manifest=selected.manifest,
        manifest_path=selected.manifest_path,
    )

    assert len(calls) == 1
    assert read_count["project_json"] == 4

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.projects import Project, resolve_active_project_root


def test_active_project_root_preserves_established_precedence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    provided = tmp_path / "provided"
    environment = tmp_path / "environment"
    project = tmp_path / "project"
    for root in (provided, environment, project):
        root.mkdir()
    monkeypatch.setenv("FPVS_PROJECT_ROOT", str(environment))
    current_project = SimpleNamespace(project_root=project)

    assert (
        resolve_active_project_root(provided, current_project=current_project)
        == provided
    )
    assert (
        resolve_active_project_root(
            tmp_path / "missing",
            current_project=current_project,
        )
        == environment
    )

    monkeypatch.setenv("FPVS_PROJECT_ROOT", str(tmp_path / "missing-environment"))
    assert (
        resolve_active_project_root(None, current_project=current_project) == project
    )


def test_active_project_root_returns_none_when_no_candidate_exists(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("FPVS_PROJECT_ROOT", raising=False)

    assert resolve_active_project_root(tmp_path / "missing") is None


@pytest.mark.parametrize("invalid_candidate", ["provided", "environment", "project"])
def test_active_project_root_skips_files_in_candidate_precedence(
    tmp_path: Path,
    monkeypatch,
    invalid_candidate: str,
) -> None:
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("retain file contents", encoding="utf-8")
    valid_root = tmp_path / "valid-project"
    valid_root.mkdir()
    monkeypatch.delenv("FPVS_PROJECT_ROOT", raising=False)

    if invalid_candidate == "provided":
        monkeypatch.setenv("FPVS_PROJECT_ROOT", str(valid_root))
        resolved = resolve_active_project_root(invalid_root)
        expected = valid_root
    elif invalid_candidate == "environment":
        monkeypatch.setenv("FPVS_PROJECT_ROOT", str(invalid_root))
        resolved = resolve_active_project_root(
            None, current_project=SimpleNamespace(project_root=valid_root),
        )
        expected = valid_root
    else:
        resolved = resolve_active_project_root(
            None, current_project=SimpleNamespace(project_root=invalid_root),
        )
        expected = None

    assert resolved == expected
    assert invalid_root.read_text(encoding="utf-8") == "retain file contents"


def test_copied_project_derives_root_from_manifest_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    copied = tmp_path / "copied"
    source.mkdir()
    (source / "project.json").write_text(
        json.dumps({"name": "Portable project"}),
        encoding="utf-8",
    )
    shutil.copytree(source, copied)

    project = Project.load(copied)
    project.save()
    saved_manifest = json.loads((copied / "project.json").read_text(encoding="utf-8"))

    assert project.project_root == copied.resolve()
    assert "project_root" not in project.manifest
    assert "project_root" not in saved_manifest

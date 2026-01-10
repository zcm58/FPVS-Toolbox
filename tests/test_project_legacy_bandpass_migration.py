from __future__ import annotations

import json
from pathlib import Path

import Main_App.PySide6_App.Backend.project as project_module
from Main_App.PySide6_App.Backend.project import Project


def _write_manifest(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_legacy_bandpass_migration_writes_once(monkeypatch, tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "LegacyProject"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    _write_manifest(
        manifest_path,
        {"preprocessing": {"low_pass": 0.1, "high_pass": 50.0}},
    )

    calls: list[Path] = []
    real_write = project_module._write_manifest_if_changed

    def counting_write(path: Path, data: dict) -> bool:
        calls.append(path)
        return real_write(path, data)

    monkeypatch.setattr(project_module, "_write_manifest_if_changed", counting_write)

    project = Project.load(project_root)
    assert project.preprocessing["low_pass"] == 50.0
    assert project.preprocessing["high_pass"] == 0.1

    updated = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated["preprocessing"]["low_pass"] == 50.0
    assert updated["preprocessing"]["high_pass"] == 0.1

    output = capsys.readouterr().out
    assert "Legacy preprocessing bandpass inverted" in output
    assert str(manifest_path) in output
    assert len(calls) == 1

    Project.load(project_root)
    output = capsys.readouterr().out
    assert "Legacy preprocessing bandpass inverted" not in output
    assert len(calls) == 1


def test_canonical_manifest_does_not_warn(tmp_path: Path, capsys) -> None:
    project_root = tmp_path / "CanonicalProject"
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    _write_manifest(
        manifest_path,
        {"preprocessing": {"low_pass": 50.0, "high_pass": 0.1}},
    )

    project = Project.load(project_root)
    assert project.preprocessing["low_pass"] == 50.0
    assert project.preprocessing["high_pass"] == 0.1

    output = capsys.readouterr().out
    assert "Legacy preprocessing bandpass inverted" not in output

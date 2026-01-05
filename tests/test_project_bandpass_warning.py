import json

import pytest

pytest.importorskip("PySide6")

from Main_App.PySide6_App.Backend.project import Project, _LEGACY_BANDPASS_WARNED


def test_legacy_bandpass_warns_once_per_project(tmp_path, capsys):
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(
        json.dumps({"preprocessing": {"low_pass": "0.1", "high_pass": "50.0"}}),
        encoding="utf-8",
    )

    previous = set(_LEGACY_BANDPASS_WARNED)
    _LEGACY_BANDPASS_WARNED.clear()

    try:
        project = Project.load(tmp_path)
        first = capsys.readouterr().out

        assert project.preprocessing["low_pass"] == 50.0
        assert project.preprocessing["high_pass"] == 0.1
        assert "Invalid preprocessing bandpass detected" in first

        Project.load(tmp_path)
        second = capsys.readouterr().out

        assert "Invalid preprocessing bandpass detected" not in second
    finally:
        _LEGACY_BANDPASS_WARNED.clear()
        _LEGACY_BANDPASS_WARNED.update(previous)

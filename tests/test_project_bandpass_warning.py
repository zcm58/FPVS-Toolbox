import json
import logging

import pytest

pytest.importorskip("PySide6")

from Main_App.projects.project import Project, _LEGACY_BANDPASS_WARNED


def test_legacy_bandpass_warns_once_per_project(tmp_path, caplog):
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text(
        json.dumps({"preprocessing": {"low_pass": "0.1", "high_pass": "50.0"}}),
        encoding="utf-8",
    )

    previous = set(_LEGACY_BANDPASS_WARNED)
    _LEGACY_BANDPASS_WARNED.clear()

    try:
        with caplog.at_level(logging.WARNING, logger="Main_App.projects.project"):
            project = Project.load(tmp_path)

        assert project.preprocessing["low_pass"] == 50.0
        assert project.preprocessing["high_pass"] == 0.1
        assert any(
            "legacy_preprocessing_bandpass_inverted" in rec.message
            and str(manifest_path) in getattr(rec, "manifest_path", "")
            for rec in caplog.records
        )

        caplog.clear()
        Project.load(tmp_path)

        assert not any(
            "legacy_preprocessing_bandpass_inverted" in rec.message
            for rec in caplog.records
        )
    finally:
        _LEGACY_BANDPASS_WARNED.clear()
        _LEGACY_BANDPASS_WARNED.update(previous)

from __future__ import annotations

import json

from Main_App.PySide6_App.Backend.project import (
    EXCEL_SUBFOLDER_NAME,
    SNR_SUBFOLDER_NAME,
    STATS_SUBFOLDER_NAME,
    Project,
)


def test_project_creates_flat_results_layout(tmp_path):
    proj_dir = tmp_path / "FlatProject"
    proj_dir.mkdir()

    project = Project.load(proj_dir)

    assert project.results_folder == proj_dir.resolve()
    assert project.subfolders["excel"] == (proj_dir / EXCEL_SUBFOLDER_NAME).resolve()
    assert project.subfolders["snr"] == (proj_dir / SNR_SUBFOLDER_NAME).resolve()
    assert project.subfolders["stats"] == (proj_dir / STATS_SUBFOLDER_NAME).resolve()
    for subdir in project.subfolders.values():
        assert subdir.exists()


def test_project_honors_legacy_results_folder(tmp_path):
    proj_dir = tmp_path / "LegacyProject"
    proj_dir.mkdir()
    legacy_manifest = {
        "results_folder": "Results",
        "subfolders": {
            "excel": EXCEL_SUBFOLDER_NAME,
            "snr": SNR_SUBFOLDER_NAME,
            "stats": STATS_SUBFOLDER_NAME,
        },
    }
    (proj_dir / "project.json").write_text(json.dumps(legacy_manifest))

    project = Project.load(proj_dir)

    legacy_root = (proj_dir / "Results").resolve()
    assert project.results_folder == legacy_root
    assert project.subfolders["excel"] == (legacy_root / EXCEL_SUBFOLDER_NAME).resolve()
    assert project.subfolders["snr"] == (legacy_root / SNR_SUBFOLDER_NAME).resolve()
    assert project.subfolders["stats"] == (legacy_root / STATS_SUBFOLDER_NAME).resolve()
    for subdir in project.subfolders.values():
        assert subdir.exists()

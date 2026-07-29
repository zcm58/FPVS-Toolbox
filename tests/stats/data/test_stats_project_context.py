from __future__ import annotations

import json
import logging

from Main_App.projects import DatasetDiagnostic
from Tools.Stats.data import stats_data_loader
from Tools.Stats.data.stats_data_loader import (
    find_project_manifest_for_excel_root,
    is_multi_group_project_config,
    load_project_scan,
    normalize_participants_map,
)
from Tools.Stats.reporting.logging_policy import stats_ide_log_level


def test_stats_ide_log_policy_keeps_only_missing_files_and_errors_visible():
    assert stats_ide_log_level("Prepare Analysis started", "info") == "debug"
    assert stats_ide_log_level("A routine QC exclusion", "warning") == "debug"
    assert stats_ide_log_level("Missing file for P1 / Faces", "info") == "warning"
    assert stats_ide_log_level("Analysis failed", "error") == "error"


def test_dataset_index_logging_demotes_intentional_exclusions(caplog, tmp_path):
    diagnostics = (
        DatasetDiagnostic(
            code="excluded_participant_condition",
            message="Excluded P1 / Faces by project QC decision.",
            paths=(tmp_path / "P1_Faces.xlsx",),
        ),
        DatasetDiagnostic(
            code="missing_excel_root",
            message="The Excel root is missing.",
            paths=(tmp_path / "1 - Excel Data Files",),
        ),
    )

    with caplog.at_level(logging.DEBUG, logger=stats_data_loader.__name__):
        stats_data_loader._log_dataset_index_diagnostics(diagnostics)

    levels_by_message = {
        record.getMessage(): record.levelno
        for record in caplog.records
        if record.name == stats_data_loader.__name__
    }
    excluded_message = next(
        message for message in levels_by_message if "excluded_participant_condition" in message
    )
    missing_message = next(
        message for message in levels_by_message if "missing_excel_root" in message
    )
    assert levels_by_message[excluded_message] == logging.DEBUG
    assert levels_by_message[missing_message] == logging.WARNING


def test_project_scan_returns_project_root_from_excel_folder(tmp_path):
    project_root = tmp_path / "Semantic Categories 3"
    excel_root = project_root / "1 - Excel Data Files"
    condition_dir = excel_root / "Faces"
    condition_dir.mkdir(parents=True)
    (condition_dir / "P1_Faces_Results.xlsx").write_text("", encoding="utf-8")
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Semantic Categories 3",
                "subfolders": {
                    "excel": "1 - Excel Data Files",
                    "stats": "3 - Statistical Analysis Results",
                },
            }
        ),
        encoding="utf-8",
    )

    scan = load_project_scan(str(excel_root))

    assert scan.project_root == project_root.resolve()
    assert scan.manifest["name"] == "Semantic Categories 3"
    assert scan.subjects == ["P1"]
    assert scan.conditions == ["Faces"]


def test_find_project_manifest_rejects_unrelated_parent_manifest(tmp_path):
    parent_project = tmp_path / "Parent Project"
    unrelated_excel = parent_project / "Other Folder" / "Nested Excel Files"
    unrelated_excel.mkdir(parents=True)
    (parent_project / "project.json").write_text(
        json.dumps(
            {
                "name": "Parent Project",
                "subfolders": {"excel": "1 - Excel Data Files"},
            }
        ),
        encoding="utf-8",
    )

    project_root, manifest = find_project_manifest_for_excel_root(unrelated_excel)

    assert project_root is None
    assert manifest is None


def test_stats_manifest_map_resolves_v2_group_ids_to_labels() -> None:
    manifest = {
        "groups": {
            "control": {
                "label": "Control Group",
                "folder_name": "Control",
            },
            "clinical": {
                "label": "Clinical Group",
                "folder_name": "Clinical",
            },
        },
        "participants": {
            "P01": {"group_id": "control"},
            "P02": {"group_id": "clinical"},
        },
    }

    assert normalize_participants_map(manifest) == {
        "P01": "Control Group",
        "P02": "Clinical Group",
    }


def test_multi_group_project_config_requires_two_or_more_groups() -> None:
    assert is_multi_group_project_config(None) is False
    assert is_multi_group_project_config({"groups": {}}) is False
    assert is_multi_group_project_config({"groups": {"only": {"label": "Only"}}}) is False
    assert is_multi_group_project_config(
        {
            "groups": {
                "control": {"label": "Control"},
                "clinical": {"label": "Clinical"},
            }
        }
    ) is True


def test_project_scan_marks_multi_group_manifest(tmp_path):
    project_root = tmp_path / "Grouped Project"
    excel_root = project_root / "1 - Excel Data Files"
    condition_dir = excel_root / "Faces" / "Control"
    condition_dir.mkdir(parents=True)
    (condition_dir / "P1_Faces_Results.xlsx").write_text("", encoding="utf-8")
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Grouped Project",
                "subfolders": {
                    "excel": "1 - Excel Data Files",
                    "stats": "3 - Statistical Analysis Results",
                },
                "groups": {
                    "control": {
                        "label": "Control",
                        "folder_name": "Control",
                        "raw_input_folder": "Raw/Control",
                    },
                    "clinical": {
                        "label": "Clinical",
                        "folder_name": "Clinical",
                        "raw_input_folder": "Raw/Clinical",
                    },
                },
                "participants": {"P1": {"group_id": "control"}},
            }
        ),
        encoding="utf-8",
    )

    scan = load_project_scan(str(excel_root))

    assert scan.project_is_multi_group is True
    assert scan.project_root == project_root.resolve()
    assert scan.subjects == ["P1"]
    assert scan.conditions == ["Faces"]
    assert scan.participants_map["P1"] == "Control"
    assert scan.participant_group_ids["P1"] == "control"

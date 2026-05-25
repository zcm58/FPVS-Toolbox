from __future__ import annotations

import json

from Tools.Stats.data.stats_data_loader import (
    find_project_manifest_for_excel_root,
    load_project_scan,
    normalize_participants_map,
)


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

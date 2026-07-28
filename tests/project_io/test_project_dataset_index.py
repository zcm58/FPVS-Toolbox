from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.projects import (
    DatasetIndexError,
    find_project_manifest_for_dataset_path,
    group_labels_from_manifest,
    infer_workbook_participant_id,
    is_multi_group_manifest,
    load_project_dataset_index,
    participant_group_label_map_from_manifest,
)


def _write_project(
    root: Path,
    *,
    groups: dict[str, tuple[str, str]],
    participants: dict[str, str],
) -> Path:
    raw_root = root / "Raw"
    group_payload: dict[str, dict[str, str]] = {}
    for group_id, (label, folder_name) in groups.items():
        raw_folder = raw_root / folder_name
        raw_folder.mkdir(parents=True, exist_ok=True)
        group_payload[group_id] = {
            "label": label,
            "folder_name": folder_name,
            "raw_input_folder": str(raw_folder),
        }
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": group_payload,
        "participants": {
            participant_id: {"group_id": group_id}
            for participant_id, group_id in participants.items()
        },
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return root / "1 - Excel Data Files"


def _workbook(excel_root: Path, condition: str, folder: str | None, name: str) -> Path:
    parent = excel_root / condition
    if folder is not None:
        parent /= folder
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / name
    path.write_text("fixture", encoding="utf-8")
    return path


def test_project_dataset_index_assigns_groups_only_from_project_manifest(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={
            "control": ("Control Group", "Control"),
            "clinical": ("Clinical Group", "Clinical"),
        },
        participants={"P01": "control", "P02": "clinical"},
    )
    control = _workbook(
        excel_root,
        "Condition A",
        "Control",
        "P01_Condition A_Results.xlsx",
    )
    clinical = _workbook(
        excel_root,
        "Condition A",
        "Clinical",
        "P02_Condition A_Results.xlsx",
    )

    index = load_project_dataset_index(project_root)

    assert index.is_multi_group is True
    assert index.conditions == ("Condition A",)
    assert [(row.participant_id, row.group_id, row.group_label, row.path) for row in index.workbooks] == [
        ("P02", "clinical", "Clinical Group", clinical),
        ("P01", "control", "Control Group", control),
    ]
    assert index.participant_group_id_map() == {
        "P01": "control",
        "P02": "clinical",
    }
    assert index.participant_group_label_map(uppercase_keys=True) == {
        "P01": "Control Group",
        "P02": "Clinical Group",
    }


def test_project_dataset_index_prefers_exact_known_participant_id(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"E2P2FINAL": "control"},
    )
    workbook = _workbook(
        excel_root,
        "Angry",
        "Control",
        "E2P2final_Angry_Results.xlsx",
    )

    index = load_project_dataset_index(project_root)

    assert index.workbooks[0].participant_id == "E2P2FINAL"
    assert index.workbooks[0].path == workbook


def test_project_dataset_index_reports_unassigned_workbook_without_folder_inference(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _workbook(excel_root, "Faces", "Control", "P99_Faces_Results.xlsx")

    index = load_project_dataset_index(project_root)

    assert index.workbooks[0].participant_id == "P99"
    assert index.workbooks[0].group_id is None
    assert {row.code for row in index.diagnostics} == {"unassigned_participant"}


def test_project_dataset_index_keeps_manifest_group_when_folder_mismatches(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={
            "control": ("Control", "Control"),
            "clinical": ("Clinical", "Clinical"),
        },
        participants={"P01": "control"},
    )
    _workbook(excel_root, "Faces", "Clinical", "P01_Faces_Results.xlsx")

    index = load_project_dataset_index(project_root)

    assert index.workbooks[0].group_id == "control"
    assert index.workbooks[0].observed_group_folder == "Clinical"
    assert {row.code for row in index.diagnostics} == {"group_folder_mismatch"}


def test_project_dataset_index_prefers_canonical_grouped_copy_over_stale_flat_copy(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    flat = _workbook(excel_root, "Faces", None, "P01_Faces_Results.xlsx")
    grouped = _workbook(excel_root, "Faces", "Control", "P01_Faces_Results.xlsx")
    flat.touch()

    index = load_project_dataset_index(project_root)

    assert index.workbooks[0].path == grouped
    duplicate = next(
        row
        for row in index.diagnostics
        if row.code == "duplicate_participant_condition_workbook"
    )
    assert set(duplicate.paths) == {flat, grouped}


def test_project_dataset_index_scopes_condition_and_group_folders(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    faces = _workbook(excel_root, "Faces", "Control", "P01_Faces_Results.xlsx")
    _workbook(excel_root, "Objects", "Control", "P01_Objects_Results.xlsx")

    condition_index = load_project_dataset_index(excel_root / "Faces")
    group_index = load_project_dataset_index(excel_root / "Faces" / "Control")

    assert condition_index.conditions == ("Faces",)
    assert group_index.conditions == ("Faces",)
    assert condition_index.workbooks[0].path == faces
    assert group_index.workbooks[0].path == faces


def test_project_dataset_index_adapters_and_selection_use_stable_ids(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={
            "control": ("Control", "Control"),
            "clinical": ("Clinical", "Clinical"),
        },
        participants={"P01": "control", "P02": "clinical"},
    )
    _workbook(excel_root, "Faces", "Control", "P01_Faces_Results.xlsx")
    clinical = _workbook(
        excel_root,
        "Faces",
        "Clinical",
        "P02_Faces_Results.xlsx",
    )

    index = load_project_dataset_index(project_root)

    selected = index.select(group_ids=("clinical",), conditions=("faces",))
    assert [row.path for row in selected] == [clinical]
    assert index.subject_data()["P02"]["Faces"] == str(clinical)


def test_shared_manifest_group_helpers_preserve_legacy_group_reads() -> None:
    manifest = {
        "groups": {
            "control": {"label": "Control Group", "folder_name": "Control"},
            "clinical": {"label": "Clinical Group", "folder_name": "Clinical"},
        },
        "participants": {
            "SCP7": {"group": "Control Group"},
            "P02": {"group_id": "clinical"},
        },
    }

    assert group_labels_from_manifest(manifest) == (
        "Clinical Group",
        "Control Group",
    )
    assert is_multi_group_manifest(manifest) is True
    assert participant_group_label_map_from_manifest(manifest) == {
        "SCP7": "Control Group",
        "P02": "Clinical Group",
        "P7": "Control Group",
    }


def test_shared_participant_inference_can_preserve_plot_legacy_fallback() -> None:
    assert (
        infer_workbook_participant_id(
            "E2P2final_Angry_Results.xlsx",
            known_participant_ids=("E2P2FINAL",),
        )
        == "E2P2FINAL"
    )
    assert infer_workbook_participant_id("=p17.xlsx") == "P17"
    assert (
        infer_workbook_participant_id(
            "control group.xlsx",
            fallback_to_stem=True,
        )
        == "CONTROL GROUP"
    )


def test_unmanaged_dataset_index_preserves_condition_folder_scanning(
    tmp_path: Path,
) -> None:
    workbook = _workbook(tmp_path, "CondA", None, "P01_data.xlsx")

    index = load_project_dataset_index(tmp_path)

    assert index.manifest is None
    assert index.conditions == ("CondA",)
    assert index.workbooks[0].participant_id == "P01"
    assert index.workbooks[0].path == workbook


def test_unmanaged_project_like_root_uses_conventional_excel_child(
    tmp_path: Path,
) -> None:
    excel_root = tmp_path / "Project" / "1 - Excel Data Files"
    workbook = _workbook(excel_root, "CondA", None, "P01_data.xlsx")

    index = load_project_dataset_index(tmp_path / "Project")

    assert index.excel_root == excel_root
    assert index.conditions == ("CondA",)
    assert index.workbooks[0].path == workbook


def test_missing_project_excel_root_is_read_only_and_diagnostic(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={},
        participants={},
    )
    excel_root.parent.mkdir(parents=True, exist_ok=True)

    index = load_project_dataset_index(project_root)

    assert not excel_root.exists()
    assert index.workbooks == ()
    assert [row.code for row in index.diagnostics] == ["missing_excel_root"]


def test_manifest_locator_rejects_unmanaged_project_sibling(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    _write_project(project_root, groups={}, participants={})
    backup = project_root / "10 - Excel Data Files Backup"
    backup.mkdir()

    owner, manifest = find_project_manifest_for_dataset_path(backup)

    assert owner is None
    assert manifest is None


def test_ambiguous_legacy_participant_alias_is_omitted_and_diagnosed(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={
            "control": ("Control", "Control"),
            "clinical": ("Clinical", "Clinical"),
        },
        participants={"SCP7": "control", "XP7": "clinical"},
    )
    _workbook(excel_root, "Faces", "Control", "SCP7_Faces_Results.xlsx")
    _workbook(excel_root, "Faces", "Clinical", "XP7_Faces_Results.xlsx")

    index = load_project_dataset_index(project_root)
    group_map = index.participant_group_label_map(include_legacy_aliases=True)

    assert group_map["SCP7"] == "Control"
    assert group_map["XP7"] == "Clinical"
    assert "P7" not in group_map
    assert "ambiguous_legacy_participant_alias" in {
        diagnostic.code for diagnostic in index.diagnostics
    }


def test_ambiguous_group_label_does_not_override_group_id_mapping() -> None:
    manifest = {
        "groups": {
            "control": {"label": "Shared", "folder_name": "Control"},
            "clinical": {"label": "Shared", "folder_name": "Clinical"},
        },
        "participants": {
            "P01": {"group_id": "control"},
            "P02": {"group": "Shared"},
        },
    }

    assert is_multi_group_manifest(manifest) is True
    assert participant_group_label_map_from_manifest(manifest) == {
        "P01": "Shared"
    }


def test_direct_grouped_workbook_beats_newer_deeply_nested_backup(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    direct = _workbook(
        excel_root,
        "Faces",
        "Control",
        "P01_Faces_Results.xlsx",
    )
    backup = (
        excel_root
        / "Faces"
        / "Control"
        / "Backup"
        / "P01_Faces_Results.xlsx"
    )
    backup.parent.mkdir(parents=True)
    backup.write_text("newer backup", encoding="utf-8")
    backup.touch()

    index = load_project_dataset_index(project_root)

    assert index.workbooks[0].path == direct
    assert "unexpected_workbook_nesting" in {
        diagnostic.code for diagnostic in index.diagnostics
    }


def test_managed_summary_name_cannot_replace_participant_workbook(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P02": "control"},
    )
    participant = _workbook(
        excel_root,
        "Faces",
        "Control",
        "P02_Faces_Results.xlsx",
    )
    summary = _workbook(
        excel_root,
        "Faces",
        "Control",
        "Group_P02_summary.xlsx",
    )
    summary.touch()

    index = load_project_dataset_index(project_root)

    assert [record.path for record in index.workbooks] == [participant]
    assert "unresolved_participant" in {
        diagnostic.code for diagnostic in index.diagnostics
    }


def test_managed_generated_name_retains_unregistered_participant_identity(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={
            "control": ("Control", "Control"),
            "patient": ("Patient", "Patient"),
        },
        participants={"P01": "control"},
    )
    workbook = _workbook(
        excel_root,
        "Condition A",
        "Control",
        "SCP3_Condition A_Results.xlsx",
    )

    index = load_project_dataset_index(project_root)

    assert [
        (record.participant_id, record.condition, record.group_id, record.path)
        for record in index.workbooks
    ] == [("SCP3", "Condition A", None, workbook)]
    assert "unassigned_participant" in {
        diagnostic.code for diagnostic in index.diagnostics
    }
    with pytest.raises(DatasetIndexError, match="SCP3"):
        index.require_group_assignments()
    with pytest.raises(DatasetIndexError, match="SCP3"):
        index.partition_by_group()

    direct = load_project_dataset_index(workbook)
    assert [
        (record.participant_id, record.condition, record.group_id, record.path)
        for record in direct.workbooks
    ] == [("SCP3", "Condition A", None, workbook)]


def test_strict_group_adapter_rejects_unregistered_workbook(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _workbook(excel_root, "Faces", "Control", "P99_Faces_Results.xlsx")

    index = load_project_dataset_index(project_root)

    with pytest.raises(DatasetIndexError, match="P99"):
        index.subject_data(require_group_assignment=True)
    with pytest.raises(DatasetIndexError, match="P99"):
        index.partition_by_group()
    assert "P99" in index.subject_data()


def test_strict_group_adapter_only_validates_indexed_participants(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={"control": ("Control", "Control")},
        participants={"P01": "control"},
    )
    _workbook(excel_root, "Faces", "Control", "P01_Faces_Results.xlsx")
    _workbook(excel_root, "Faces", "Control", "analysis_notes.xlsx")

    index = load_project_dataset_index(project_root)

    assert "unresolved_participant" in {
        diagnostic.code for diagnostic in index.diagnostics
    }
    assert tuple(index.subject_data(require_group_assignment=True)) == ("P01",)


def test_strict_group_selection_rejects_unknown_and_empty_groups(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={
            "control": ("Control", "Control"),
            "clinical": ("Clinical", "Clinical"),
        },
        participants={"P01": "control", "P02": "clinical"},
    )
    _workbook(excel_root, "Faces", "Control", "P01_Faces_Results.xlsx")
    index = load_project_dataset_index(project_root)

    with pytest.raises(DatasetIndexError, match="Unknown"):
        index.select(group_ids=("missing",), require_nonempty_groups=True)
    with pytest.raises(DatasetIndexError, match="clinical"):
        index.select(group_ids=("clinical",), require_nonempty_groups=True)


def test_ignored_folder_name_above_scan_root_does_not_hide_workbooks(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "LORETA Results" / "Project"
    excel_root = _write_project(
        project_root,
        groups={},
        participants={},
    )
    workbook = _workbook(excel_root, "Faces", None, "P01_Faces_Results.xlsx")

    index = load_project_dataset_index(project_root)

    assert [record.path for record in index.workbooks] == [workbook]


def test_workbook_file_scope_indexes_only_that_workbook(tmp_path: Path) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_project(
        project_root,
        groups={},
        participants={},
    )
    selected = _workbook(excel_root, "Faces", None, "P01_Faces_Results.xlsx")
    _workbook(excel_root, "Faces", None, "P02_Faces_Results.xlsx")

    index = load_project_dataset_index(selected)

    assert [record.path for record in index.workbooks] == [selected]


def test_project_file_scope_rejects_nonworkbooks_and_outside_excel(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    _write_project(project_root, groups={}, participants={})
    outside = project_root / "P01_Faces_Results.xlsx"
    outside.write_text("fixture", encoding="utf-8")

    with pytest.raises(DatasetIndexError, match="outside"):
        load_project_dataset_index(outside)
    with pytest.raises(DatasetIndexError, match=r"\.xlsx"):
        load_project_dataset_index(project_root / "project.json")


def test_project_directory_scope_rejects_siblings_outside_excel(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    _write_project(project_root, groups={}, participants={})
    stats_root = project_root / "3 - Statistical Analysis Results"
    stats_root.mkdir()
    _workbook(stats_root, "Exports", None, "P01_summary.xlsx")

    with pytest.raises(DatasetIndexError, match="outside"):
        load_project_dataset_index(stats_root)

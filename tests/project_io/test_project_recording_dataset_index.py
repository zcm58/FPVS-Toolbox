from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.projects import DatasetIndexError, load_project_dataset_index


def _write_repeated_project(project_root: Path) -> Path:
    manifest = {
        "schema_version": "2.2.0",
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {
            "birth_control": {
                "label": "Birth Control",
                "folder_name": "Birth Control",
                "raw_input_folder": "Raw/Birth Control",
            },
            "control": {
                "label": "No Birth Control",
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
        },
        "sessions": {
            "luteal": {"label": "Luteal (visit 1)", "visit_index": 1},
            "follicular": {"label": "Follicular (visit 2)", "visit_index": 2},
        },
        "recording_sources": {
            "bc_luteal": {
                "group_id": "birth_control",
                "session_id": "luteal",
                "raw_input_folder": "Raw/Birth Control/Luteal",
            },
            "bc_follicular": {
                "group_id": "birth_control",
                "session_id": "follicular",
                "raw_input_folder": "Raw/Birth Control/Follicular",
            },
            "control_luteal": {
                "group_id": "control",
                "session_id": "luteal",
                "raw_input_folder": "Raw/Control/Luteal",
            },
        },
        "participants": {
            "P01": {"group_id": "birth_control"},
            "P02": {"group_id": "control"},
        },
        "recordings": {
            "rec_p01_luteal": {
                "participant_id": "P01",
                "session_id": "luteal",
                "source_id": "bc_luteal",
                "raw_file": "Raw/Birth Control/Luteal/P01_BC_L.bdf",
                "visit_index": 1,
            },
            "rec_p01_follicular": {
                "participant_id": "P01",
                "session_id": "follicular",
                "source_id": "bc_follicular",
                "raw_file": "Raw/Birth Control/Follicular/P01_BC_F.bdf",
                "visit_index": 2,
            },
            "rec_p02_luteal": {
                "participant_id": "P02",
                "session_id": "luteal",
                "source_id": "control_luteal",
                "raw_file": "Raw/Control/Luteal/P02_C_L.bdf",
                "visit_index": 1,
            },
        },
    }
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return project_root / "1 - Excel Data Files"


def _workbook(
    excel_root: Path,
    *,
    condition: str,
    group_folder: str | None,
    recording_id: str,
) -> Path:
    parent = excel_root / condition
    if group_folder is not None:
        parent /= group_folder
    parent.mkdir(parents=True, exist_ok=True)
    path = parent / f"{recording_id}_{condition}_Results.xlsx"
    path.write_text("fixture", encoding="utf-8")
    return path


def test_repeated_dataset_index_keeps_two_sessions_for_one_participant(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_repeated_project(project_root)
    luteal = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_luteal",
    )
    follicular = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_follicular",
    )
    _workbook(
        excel_root,
        condition="Faces",
        group_folder="Control",
        recording_id="rec_p02_luteal",
    )

    index = load_project_dataset_index(project_root)

    assert index.is_repeated_session is True
    assert index.participant_ids == ("P01", "P02")
    assert index.recording_ids == (
        "rec_p01_follicular",
        "rec_p01_luteal",
        "rec_p02_luteal",
    )
    assert index.session_ids == ("luteal", "follicular")
    p01 = index.select(participant_ids=("P01",))
    assert [(row.recording_id, row.session_id, row.visit_index) for row in p01] == [
        ("rec_p01_luteal", "luteal", 1),
        ("rec_p01_follicular", "follicular", 2),
    ]
    assert [row.days_from_baseline for row in p01] == [None, None]
    assert {row.path for row in p01} == {luteal, follicular}
    assert [session.session_id for session, _records in index.partition_by_session() if session is not None] == [
        "luteal",
        "follicular",
    ]
    assert {row.recording_id for row in index.select(session_ids=("follicular",), visit_indices=(2,))} == {
        "rec_p01_follicular"
    }
    assert set(index.recording_data()) == {
        "rec_p01_luteal",
        "rec_p01_follicular",
        "rec_p02_luteal",
    }
    with pytest.raises(DatasetIndexError, match="cannot represent multiple recordings"):
        index.subject_data()
    assert len(index.partition_by_group_and_session()) == 4


def test_repeated_dataset_index_duplicate_key_is_recording_and_condition(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_repeated_project(project_root)
    canonical = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_luteal",
    )
    flat = _workbook(
        excel_root,
        condition="Faces",
        group_folder=None,
        recording_id="rec_p01_luteal",
    )
    follicular = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_follicular",
    )

    index = load_project_dataset_index(project_root)

    assert {row.path for row in index.workbooks} == {canonical, follicular}
    assert flat not in {row.path for row in index.workbooks}
    assert "duplicate_recording_condition_workbook" in {diagnostic.code for diagnostic in index.diagnostics}


def test_repeated_dataset_index_never_assigns_identity_from_observed_folder(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_repeated_project(project_root)
    misplaced = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Control",
        recording_id="rec_p01_luteal",
    )
    unknown = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_unknown",
    )

    index = load_project_dataset_index(project_root)

    assert len(index.workbooks) == 1
    record = index.workbooks[0]
    assert record.path == misplaced
    assert record.participant_id == "P01"
    assert record.group_id == "birth_control"
    assert record.session_id == "luteal"
    assert unknown not in {row.path for row in index.workbooks}
    assert {diagnostic.code for diagnostic in index.diagnostics}.issuperset(
        {"group_folder_mismatch", "unresolved_recording"}
    )
    with pytest.raises(DatasetIndexError, match="rec_p01_unknown"):
        index.require_recording_assignments()


def test_repeated_dataset_index_strict_session_and_recording_selection(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_repeated_project(project_root)
    _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_luteal",
    )
    index = load_project_dataset_index(project_root)

    with pytest.raises(DatasetIndexError, match="Unknown canonical.*session_id"):
        index.select(
            session_ids=("missing",),
            require_nonempty_sessions=True,
        )
    with pytest.raises(DatasetIndexError, match="rec_p01_follicular"):
        index.select(
            recording_ids=("rec_p01_follicular",),
            require_nonempty_recordings=True,
        )
    with pytest.raises(DatasetIndexError, match="birth_control/follicular"):
        index.partition_by_group_and_session(require_nonempty_cells=True)


def test_repeated_dataset_index_applies_recording_scoped_qc_exclusions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = _write_repeated_project(project_root)
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"] = {
        "manual_excluded_recordings": ["rec_p01_luteal"],
        "manual_excluded_recording_conditions": {
            "rec_p01_follicular": ["Objects"],
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    luteal = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_luteal",
    )
    follicular_faces = _workbook(
        excel_root,
        condition="Faces",
        group_folder="Birth Control",
        recording_id="rec_p01_follicular",
    )
    follicular_objects = _workbook(
        excel_root,
        condition="Objects",
        group_folder="Birth Control",
        recording_id="rec_p01_follicular",
    )

    index = load_project_dataset_index(project_root)

    assert {record.path for record in index.workbooks} == {follicular_faces}
    assert {record.path for record in index.excluded_workbooks} == {
        luteal,
        follicular_objects,
    }
    assert {diagnostic.code for diagnostic in index.diagnostics}.issuperset(
        {"excluded_recording", "excluded_recording_condition"}
    )


def test_legacy_dataset_index_recording_fields_default_to_none(tmp_path: Path) -> None:
    project_root = tmp_path / "Legacy"
    project_root.mkdir()
    raw_root = project_root / "Raw" / "Control"
    manifest = {
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": str(raw_root),
            }
        },
        "participants": {"P01": {"group_id": "control"}},
    }
    (project_root / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    workbook = project_root / "1 - Excel Data Files" / "Faces" / "Control"
    workbook.mkdir(parents=True)
    (workbook / "P01_Faces_Results.xlsx").write_text("fixture", encoding="utf-8")

    index = load_project_dataset_index(project_root)

    assert index.is_repeated_session is False
    assert len(index.workbooks) == 1
    record = index.workbooks[0]
    assert record.recording_id is None
    assert record.session_id is None
    assert record.session_label is None
    assert record.visit_index is None
    assert record.days_from_baseline is None
    assert index.recording_data() == index.subject_data()
    assert index.partition_by_session() == ((None, index.workbooks),)

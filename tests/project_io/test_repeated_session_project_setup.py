from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.projects import project_manager
from Main_App.projects.project import REPEATED_SESSION_PROJECT_SCHEMA_VERSION, Project


def _groups(tmp_path: Path) -> dict[str, dict[str, object]]:
    return {
        "birth_control": {
            "label": "Birth Control",
            "folder_name": "Birth Control",
            "raw_input_folder": tmp_path / "raw" / "Birth Control",
        },
        "no_birth_control": {
            "label": "No Birth Control",
            "folder_name": "No Birth Control",
            "raw_input_folder": tmp_path / "raw" / "No Birth Control",
        },
    }


def _sessions() -> dict[str, dict[str, object]]:
    # Deliberately supplied out of order: visit_index, not mapping order, is canonical.
    return {
        "follicular": {"label": "Follicular", "visit_index": 2},
        "luteal": {"label": "Luteal", "visit_index": 1},
    }


def _source_folders(tmp_path: Path) -> dict[tuple[str, str], Path]:
    return {
        ("birth_control", "luteal"): tmp_path / "raw" / "Birth Control" / "Luteal",
        ("birth_control", "follicular"): tmp_path
        / "raw"
        / "Birth Control"
        / "Follicular",
        ("no_birth_control", "luteal"): tmp_path
        / "raw"
        / "No Birth Control"
        / "Luteal",
        ("no_birth_control", "follicular"): tmp_path
        / "raw"
        / "No Birth Control"
        / "Follicular",
    }


def test_repeated_session_manifest_builder_emits_ordered_complete_design(
    tmp_path: Path,
) -> None:
    manifest = project_manager.build_repeated_session_project_manifest(
        project_root=tmp_path / "Project",
        project_name="Birth Control Study",
        groups=_groups(tmp_path),
        sessions=_sessions(),
        source_folders=_source_folders(tmp_path),
    )

    assert manifest["name"] == "Birth Control Study"
    assert manifest["options"] == {"mode": "batch"}
    assert list(manifest["sessions"]) == ["luteal", "follicular"]
    assert manifest["sessions"]["luteal"] == {
        "label": "Luteal",
        "visit_index": 1,
    }
    assert list(manifest["recording_sources"]) == [
        "birth_control__luteal",
        "birth_control__follicular",
        "no_birth_control__luteal",
        "no_birth_control__follicular",
    ]
    assert manifest["recording_sources"]["birth_control__follicular"] == {
        "group_id": "birth_control",
        "session_id": "follicular",
        "raw_input_folder": (
            tmp_path / "raw" / "Birth Control" / "Follicular"
        ).resolve(),
    }


def test_repeated_session_manifest_builder_rejects_incomplete_cells(
    tmp_path: Path,
) -> None:
    source_folders = _source_folders(tmp_path)
    source_folders.pop(("no_birth_control", "follicular"))

    with pytest.raises(
        project_manager.RepeatedSessionProjectSetupError,
        match="missing no_birth_control/follicular",
    ):
        project_manager.build_repeated_session_project_manifest(
            project_root=tmp_path / "Project",
            project_name="Birth Control Study",
            groups=_groups(tmp_path),
            sessions=_sessions(),
            source_folders=source_folders,
        )


def test_repeated_session_manifest_builder_rejects_reused_source_folder(
    tmp_path: Path,
) -> None:
    source_folders = _source_folders(tmp_path)
    source_folders[("no_birth_control", "follicular")] = source_folders[
        ("birth_control", "follicular")
    ]

    with pytest.raises(
        project_manager.RepeatedSessionProjectSetupError,
        match="same raw_input_folder",
    ):
        project_manager.build_repeated_session_project_manifest(
            project_root=tmp_path / "Project",
            project_name="Birth Control Study",
            groups=_groups(tmp_path),
            sessions=_sessions(),
            source_folders=source_folders,
        )


def test_repeated_session_manifest_builder_supports_arbitrary_session_count(
    tmp_path: Path,
) -> None:
    group_root = tmp_path / "raw" / "Cohort"
    sessions = {
        "follow_up": {"label": "Follow-up", "visit_index": 3},
        "baseline": {"label": "Baseline", "visit_index": 1},
        "midpoint": {"label": "Midpoint", "visit_index": 2},
    }

    manifest = project_manager.build_repeated_session_project_manifest(
        project_root=tmp_path / "Project",
        project_name="Three Visits",
        groups={
            "cohort": {
                "label": "Cohort",
                "folder_name": "Cohort",
                "raw_input_folder": group_root,
            }
        },
        sessions=sessions,
        source_folders={
            ("cohort", session_id): group_root / session_id
            for session_id in sessions
        },
    )

    assert list(manifest["sessions"]) == ["baseline", "midpoint", "follow_up"]
    assert len(manifest["recording_sources"]) == 3


def test_session_id_generation_is_stable_and_collision_safe() -> None:
    used: set[str] = set()

    assert project_manager.make_session_id("Luteal phase", used) == "luteal_phase"
    assert project_manager.make_session_id("Luteal phase", used) == "luteal_phase_2"
    assert project_manager.make_session_id("!!!", used) == "session"


def test_preflight_report_accepts_only_a_completely_empty_source_scaffold(
    tmp_path: Path,
) -> None:
    source_folders = _source_folders(tmp_path)
    for folder in source_folders.values():
        folder.mkdir(parents=True)
    manifest = project_manager.build_repeated_session_project_manifest(
        project_root=tmp_path / "Project",
        project_name="Empty Scaffold",
        groups=_groups(tmp_path),
        sessions=_sessions(),
        source_folders=source_folders,
    )
    context, group_tokens, session_tokens = project_manager._repeated_preflight_inputs(
        tmp_path / "Project",
        manifest,
    )

    report = project_manager.preflight_repeated_recording_sources(
        context,
        group_filename_tokens=group_tokens,
        session_filename_tokens=session_tokens,
    )
    completed = project_manager.apply_repeated_session_preflight_report(
        manifest,
        report,
    )

    assert report.is_blocked is True
    assert completed["participants"] == {}
    assert completed["recordings"] == {}


def test_new_project_dispatches_preflight_before_creating_v22_project(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_root = tmp_path / "raw"
    bc_root = raw_root / "Birth Control"
    no_bc_root = raw_root / "No Birth Control"
    bc_luteal = bc_root / "Luteal"
    bc_follicular = bc_root / "Follicular"
    no_bc_luteal = no_bc_root / "Luteal"
    no_bc_follicular = no_bc_root / "Follicular"
    for folder in (
        bc_luteal,
        bc_follicular,
        no_bc_luteal,
        no_bc_follicular,
    ):
        folder.mkdir(parents=True)
    (bc_luteal / "P01_BC_L.bdf").write_text("fixture", encoding="utf-8")
    (bc_follicular / "P01_BC_F.bdf").write_text("fixture", encoding="utf-8")
    (no_bc_luteal / "P02_CG_L.bdf").write_text("fixture", encoding="utf-8")
    (no_bc_follicular / "P02_CG_F.bdf").write_text("fixture", encoding="utf-8")

    loaded: list[Project] = []
    dispatched: dict[str, object] = {}
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    host = SimpleNamespace(
        projectsRoot=projects_root,
        loadProject=lambda project: loaded.append(project),
    )

    text_answers = iter(
        [
            "Birth Control Study",
            "Luteal",
            "Follicular",
            "Birth Control",
            "No Birth Control",
        ]
    )
    int_answers = iter([(2, True), (2, True)])
    folder_answers = iter(
        [
            str(bc_root),
            str(no_bc_root),
            str(bc_luteal),
            str(bc_follicular),
            str(no_bc_luteal),
            str(no_bc_follicular),
        ]
    )

    monkeypatch.setattr(
        project_manager.QInputDialog,
        "getText",
        lambda *args, **kwargs: (next(text_answers), True),
    )
    monkeypatch.setattr(
        project_manager.QInputDialog,
        "getInt",
        lambda *args, **kwargs: next(int_answers),
    )

    def fake_get_item(*args, **kwargs):
        assert "confounded with visit/order" in args[2]
        return project_manager.REPEATED_SESSION_PROJECT_STRUCTURE, True

    monkeypatch.setattr(project_manager.QInputDialog, "getItem", fake_get_item)
    monkeypatch.setattr(
        project_manager.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: next(folder_answers),
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "information",
        lambda *args, **kwargs: pytest.fail("unexpected information message"),
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "warning",
        lambda *args, **kwargs: pytest.fail("unexpected warning message"),
    )
    monkeypatch.setattr(
        project_manager.QMessageBox,
        "critical",
        lambda *args, **kwargs: pytest.fail("unexpected critical message"),
    )
    def fake_start_preflight(_host, **kwargs) -> bool:
        dispatched.update(kwargs)
        return True

    monkeypatch.setattr(
        project_manager,
        "_start_repeated_session_preflight",
        fake_start_preflight,
    )

    project_manager.new_project(host)

    assert loaded == []
    assert not (projects_root / "Birth Control Study").exists()
    assert dispatched["project_name"] == "Birth Control Study"
    manifest = dispatched["manifest"]
    assert isinstance(manifest, dict)
    assert "participants" not in manifest

    context, group_tokens, session_tokens = project_manager._repeated_preflight_inputs(
        dispatched["project_dir"],
        manifest,
    )
    report = project_manager.preflight_repeated_recording_sources(
        context,
        group_filename_tokens=group_tokens,
        session_filename_tokens=session_tokens,
    )
    completed_manifest = project_manager.apply_repeated_session_preflight_report(
        manifest,
        report,
    )
    project = project_manager._create_repeated_session_project(
        host,
        project_dir=dispatched["project_dir"],
        project_name=dispatched["project_name"],
        manifest=completed_manifest,
        use_existing_project_folder=dispatched["use_existing_project_folder"],
    )

    assert loaded == [project]
    assert list(project.sessions) == ["luteal", "follicular"]
    assert len(project.recording_sources) == 4
    saved = json.loads(
        (projects_root / "Birth Control Study" / "project.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved["schema_version"] == REPEATED_SESSION_PROJECT_SCHEMA_VERSION
    assert saved["sessions"] == {
        "luteal": {"label": "Luteal", "visit_index": 1},
        "follicular": {"label": "Follicular", "visit_index": 2},
    }
    assert saved["recording_sources"]["no_birth_control__follicular"] == {
        "group_id": "no_birth_control",
        "session_id": "follicular",
        "raw_input_folder": str(no_bc_follicular),
    }
    assert saved["participants"] == {
        "P01": {"group_id": "birth_control"},
        "P02": {"group_id": "no_birth_control"},
    }
    assert saved["recordings"]["P01__luteal"]["raw_file"] == str(
        bc_luteal / "P01_BC_L.bdf"
    )
    assert saved["recordings"]["P01__follicular"]["visit_index"] == 2

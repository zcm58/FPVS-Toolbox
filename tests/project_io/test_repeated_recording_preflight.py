from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.projects.raw_identity import infer_raw_participant_id
from Main_App.projects.recording_preflight import (
    RecordingPreflightCancelled,
    derive_filename_token_rules,
    preflight_repeated_recording_sources,
)
from Main_App.projects.recordings import project_recording_context


def _context(tmp_path: Path):
    raw = tmp_path / "raw"
    groups = {
        "birth_control": {
            "label": "Birth Control",
            "folder_name": "Birth Control",
            "raw_input_folder": raw / "Birth Control",
        },
        "control": {
            "label": "No Birth Control",
            "folder_name": "Control",
            "raw_input_folder": raw / "Control",
        },
    }
    sessions = {
        "luteal": {"label": "Luteal (visit 1)", "visit_index": 1},
        "follicular": {"label": "Follicular (visit 2)", "visit_index": 2},
    }
    sources = {
        f"{prefix}_{session}": {
            "group_id": group_id,
            "session_id": session,
            "raw_input_folder": raw / folder / session.title(),
        }
        for prefix, group_id, folder in (
            ("bc", "birth_control", "Birth Control"),
            ("cg", "control", "Control"),
        )
        for session in ("luteal", "follicular")
    }
    for info in sources.values():
        Path(info["raw_input_folder"]).mkdir(parents=True)
    project = SimpleNamespace(
        project_root=tmp_path / "Project",
        groups=groups,
        participants={},
        sessions=sessions,
        recording_sources=sources,
        recordings={},
    )
    return project_recording_context(project), sources


def _bdf(folder: Path, name: str) -> Path:
    path = folder / name
    path.write_text("fixture", encoding="utf-8")
    return path


def _token_rules():
    return {
        "group_filename_tokens": {
            "birth_control": ("BC",),
            "control": ("CG",),
        },
        "session_filename_tokens": {
            "luteal": ("L",),
            "follicular": ("F",),
        },
    }


def test_preflight_builds_recording_manifest_and_reports_missing_pair(
    tmp_path: Path,
) -> None:
    context, sources = _context(tmp_path)
    _bdf(Path(sources["bc_luteal"]["raw_input_folder"]), "P01_BC_L.bdf")
    _bdf(Path(sources["bc_follicular"]["raw_input_folder"]), "P01_BC_F.bdf")
    _bdf(Path(sources["cg_luteal"]["raw_input_folder"]), "P02_CG_L.bdf")
    _bdf(Path(sources["cg_follicular"]["raw_input_folder"]), "P03_CG_F.bdf")

    report = preflight_repeated_recording_sources(context, **_token_rules())

    assert report.is_blocked is False
    assert len(report.rows) == 4
    assert report.participant_ids == ("P01", "P02", "P03")
    assert report.n_complete_participants == 1
    assert {issue.code for issue in report.warnings} == {
        "incomplete_recording_pair"
    }
    assert report.participants_manifest() == {
        "P01": {"group_id": "birth_control"},
        "P02": {"group_id": "control"},
        "P03": {"group_id": "control"},
    }
    assert report.recordings_manifest()["P01__follicular"] == {
        "participant_id": "P01",
        "session_id": "follicular",
        "source_id": "bc_follicular",
        "raw_file": (
            Path(sources["bc_follicular"]["raw_input_folder"])
            / "P01_BC_F.bdf"
        ).resolve(),
        "visit_index": 2,
    }


def test_preflight_blocks_participant_group_drift_and_filename_cell_conflict(
    tmp_path: Path,
) -> None:
    context, sources = _context(tmp_path)
    _bdf(Path(sources["bc_luteal"]["raw_input_folder"]), "P17_BC_L.bdf")
    _bdf(Path(sources["cg_follicular"]["raw_input_folder"]), "P17_CG_F.bdf")
    _bdf(Path(sources["cg_luteal"]["raw_input_folder"]), "P22_CG_L.bdf")
    _bdf(Path(sources["cg_follicular"]["raw_input_folder"]), "P22_BC_F.bdf")
    # Ensure the fourth declared cell is nonempty so only identity findings block.
    _bdf(Path(sources["bc_follicular"]["raw_input_folder"]), "P01_BC_F.bdf")

    report = preflight_repeated_recording_sources(context, **_token_rules())

    assert report.is_blocked is True
    codes = {issue.code for issue in report.errors}
    assert "unstable_participant_group" in codes
    assert "filename_group_token_conflict" in codes
    assert "P17" in report.summary_text()
    with pytest.raises(ValueError, match="Blocked recording preflight"):
        report.recordings_manifest()


def test_preflight_blocks_duplicate_session_and_nested_bdf(tmp_path: Path) -> None:
    context, sources = _context(tmp_path)
    for source_id, info in sources.items():
        folder = Path(info["raw_input_folder"])
        group_token = "BC" if source_id.startswith("bc") else "CG"
        session_token = "L" if source_id.endswith("luteal") else "F"
        participant = "P01" if source_id.startswith("bc") else "P02"
        _bdf(folder, f"{participant}_{group_token}_{session_token}.bdf")
    _bdf(
        Path(sources["bc_luteal"]["raw_input_folder"]),
        "P01_BC_L_run2.bdf",
    )
    nested = Path(sources["cg_follicular"]["raw_input_folder"]) / "nested"
    nested.mkdir()
    _bdf(nested, "P04_CG_F.bdf")

    report = preflight_repeated_recording_sources(context, **_token_rules())

    codes = {issue.code for issue in report.errors}
    assert "duplicate_participant_session" in codes
    assert "duplicate_recording_id" in codes
    assert "nested_bdf_files" in codes


def test_raw_participant_identity_handles_phase_suffix_filenames() -> None:
    assert infer_raw_participant_id("P01_BC_F.bdf") == "P01"
    assert infer_raw_participant_id("sub12-control-l.bdf") == "SUB12"


def test_derived_filename_tokens_block_birth_control_source_conflict(
    tmp_path: Path,
) -> None:
    context, sources = _context(tmp_path)
    for source_id, info in sources.items():
        folder = Path(info["raw_input_folder"])
        participant = "P01" if source_id.startswith("bc") else "P02"
        group_token = "BC" if source_id.startswith("bc") else "CG"
        session_token = "L" if source_id.endswith("luteal") else "F"
        _bdf(folder, f"{participant}_{group_token}_{session_token}.bdf")
    _bdf(
        Path(sources["cg_follicular"]["raw_input_folder"]),
        "P22_BC_F.bdf",
    )
    group_rules = derive_filename_token_rules(
        {
            "birth_control": ("Birth Control Group",),
            "control": ("Control Group",),
        }
    )
    session_rules = derive_filename_token_rules(
        {
            "luteal": ("Luteal Phase",),
            "follicular": ("Follicular Phase",),
        }
    )

    report = preflight_repeated_recording_sources(
        context,
        group_filename_tokens=group_rules,
        session_filename_tokens=session_rules,
    )

    conflicts = [
        issue
        for issue in report.errors
        if issue.code == "filename_group_token_conflict"
    ]
    assert any("P22_BC_F.bdf" in issue.message for issue in conflicts)


def test_preflight_honors_cooperative_cancellation_during_folder_scan(
    tmp_path: Path,
) -> None:
    context, sources = _context(tmp_path)
    _bdf(Path(sources["bc_luteal"]["raw_input_folder"]), "P01_BC_L.bdf")
    checks = 0

    def cancel_requested() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(RecordingPreflightCancelled, match="was cancelled"):
        preflight_repeated_recording_sources(
            context,
            cancel_requested=cancel_requested,
        )

    assert checks >= 2

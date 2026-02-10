from __future__ import annotations

import json
from pathlib import Path

from Tools.Stats.PySide6.stats_multigroup_scan import extract_canonical_pid, scan_multigroup_readiness


def _write_manifest(project_root: Path, participants: dict, groups: dict) -> None:
    manifest = {
        "participants": participants,
        "groups": groups,
    }
    (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")


def _make_excel_file(folder: Path, filename: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text("placeholder", encoding="utf-8")


def test_pid_extraction_canonicalization() -> None:
    cases = {
        "P7": "P7",
        "P07": "P7",
        "p0010": "P10",
        "abcP12xyz": "P12",
    }
    for raw, expected in cases.items():
        pid, issues = extract_canonical_pid(raw)
        assert pid == expected
        assert not any(issue.severity == "blocking" for issue in issues)

    pid, issues = extract_canonical_pid("no-match-here")
    assert pid is None
    assert any(issue.severity == "blocking" for issue in issues)

    pid, issues = extract_canonical_pid("P7_P8")
    assert pid == "P7"
    assert any(issue.severity == "warning" for issue in issues)


def test_manifest_collision_detection(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    excel_root = project_root / "1 - Excel Data Files"
    excel_root.mkdir()
    (excel_root / "Condition A").mkdir()

    _write_manifest(
        project_root,
        participants={
            "P7": {"group": "Control"},
            "P07": {"group": "Control"},
        },
        groups={"Control": {}},
    )

    result = scan_multigroup_readiness(project_root, excel_root)
    assert any(issue.severity == "blocking" for issue in result.issues)


def test_readiness_with_unassigned_subjects(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    excel_root = project_root / "1 - Excel Data Files"
    condition = excel_root / "Condition A"

    _write_manifest(
        project_root,
        participants={
            "P1": {"group": "Control"},
            "P2": {"group": "Treatment"},
        },
        groups={"Control": {}, "Treatment": {}},
    )

    _make_excel_file(condition, "P1_results.xlsx")
    _make_excel_file(condition, "P2_results.xlsx")
    _make_excel_file(condition, "P3_results.xlsx")

    result = scan_multigroup_readiness(project_root, excel_root)
    assert result.multi_group_ready is True
    assert result.unassigned_subjects == ["P3"]


def test_folder_scan_maps_filenames(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    excel_root = project_root / "1 - Excel Data Files"
    condition = excel_root / "Condition A"

    _write_manifest(
        project_root,
        participants={
            "P7": {"group": "GroupA"},
            "P10": {"group": "GroupB"},
        },
        groups={"GroupA": {}, "GroupB": {}},
    )

    _make_excel_file(condition, "subject_p0010_results.xlsx")
    _make_excel_file(condition, "P07_results.xlsx")

    result = scan_multigroup_readiness(project_root, excel_root)
    assert result.discovered_subjects == ["P7", "P10"]

from __future__ import annotations

import json
from pathlib import Path

from Main_App.projects import repeated_session_tool_block_reason


def test_unmigrated_tool_gate_blocks_repeated_project(tmp_path: Path) -> None:
    project_root = tmp_path / "Repeated"
    project_root.mkdir()
    raw = project_root / "raw"
    manifest = {
        "groups": {
            "cohort": {
                "label": "Cohort",
                "folder_name": "Cohort",
                "raw_input_folder": str(raw),
            }
        },
        "sessions": {
            "visit_1": {"label": "Visit 1", "visit_index": 1},
            "visit_2": {"label": "Visit 2", "visit_index": 2},
        },
        "recording_sources": {
            "cohort_v1": {
                "group_id": "cohort",
                "session_id": "visit_1",
                "raw_input_folder": str(raw / "Visit 1"),
            },
            "cohort_v2": {
                "group_id": "cohort",
                "session_id": "visit_2",
                "raw_input_folder": str(raw / "Visit 2"),
            },
        },
    }
    (project_root / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    reason = repeated_session_tool_block_reason(
        project_root,
        tool_name="Ratio Calculator",
    )

    assert reason is not None
    assert "Ratio Calculator" in reason
    assert "prevents multiple visits" in reason


def test_unmigrated_tool_gate_allows_flat_or_unmanaged_roots(tmp_path: Path) -> None:
    flat = tmp_path / "Flat"
    flat.mkdir()
    (flat / "project.json").write_text(
        json.dumps({"participants": {"P01": {}}}),
        encoding="utf-8",
    )

    assert (
        repeated_session_tool_block_reason(flat, tool_name="Tool") is None
    )
    assert (
        repeated_session_tool_block_reason(
            tmp_path / "Unmanaged",
            tool_name="Tool",
        )
        is None
    )


def test_unmigrated_tool_gate_does_not_revalidate_legacy_flat_metadata(
    tmp_path: Path,
) -> None:
    flat = tmp_path / "LegacyFlat"
    flat.mkdir()
    (flat / "project.json").write_text(
        json.dumps({"groups": "legacy representation", "participants": []}),
        encoding="utf-8",
    )

    assert repeated_session_tool_block_reason(flat, tool_name="Tool") is None

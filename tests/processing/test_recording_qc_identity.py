from __future__ import annotations

from pathlib import Path

from Main_App.gui.recording_qc_identity import (
    build_recording_coverage_rows,
    ordered_participant_ids,
)
from Main_App.projects.grouping import GroupInfo, ParticipantInfo
from Main_App.projects.recordings import (
    ProjectRecordingContext,
    RecordingInfo,
    SessionInfo,
)


def test_recording_coverage_keeps_visits_separate_and_shows_missing_visit(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    context = ProjectRecordingContext(
        project_root=tmp_path,
        sessions=(
            SessionInfo("luteal", "Luteal", 1),
            SessionInfo("follicular", "Follicular", 2),
        ),
        sources=(),
        recordings=(
            RecordingInfo(
                "P01__luteal",
                "P01",
                "luteal",
                "bc_luteal",
                raw_root / "P01_luteal.bdf",
                1,
            ),
            RecordingInfo(
                "P01__follicular",
                "P01",
                "follicular",
                "bc_follicular",
                raw_root / "P01_follicular.bdf",
                2,
            ),
            RecordingInfo(
                "P02__luteal",
                "P02",
                "luteal",
                "control_luteal",
                raw_root / "P02_luteal.bdf",
                1,
            ),
        ),
        groups=(
            GroupInfo("bc", "Birth Control", "BC", raw_root / "bc"),
            GroupInfo("control", "No Birth Control", "Control", raw_root / "control"),
        ),
        participants=(
            ParticipantInfo("P01", "bc", None),
            ParticipantInfo("P02", "control", None),
        ),
    )

    rows = build_recording_coverage_rows(context)

    assert [
        (row.participant_id, row.recording_id, row.session_id, row.visit_index)
        for row in rows
    ] == [
        ("P01", "P01__luteal", "luteal", 1),
        ("P01", "P01__follicular", "follicular", 2),
        ("P02", "P02__luteal", "luteal", 1),
        ("P02", None, "follicular", 2),
    ]
    assert rows[-1].is_missing_visit is True
    assert rows[-1].coverage_status == "Missing / not registered"
    assert rows[-1].identity_id == "P02"
    assert rows[0].group_label == "Birth Control"


def test_legacy_context_has_no_recording_coverage_rows(tmp_path: Path) -> None:
    context = ProjectRecordingContext(
        project_root=tmp_path,
        sessions=(),
        sources=(),
        recordings=(),
    )

    assert build_recording_coverage_rows(context) == ()


def test_ordered_participant_ids_preserves_natural_order_and_first_spelling() -> None:
    assert ordered_participant_ids(
        ("P10", "p2", "", "NoDigits"),
        ("P2", "P01", "nodigits", "  "),
    ) == ["NoDigits", "P01", "p2", "P10"]

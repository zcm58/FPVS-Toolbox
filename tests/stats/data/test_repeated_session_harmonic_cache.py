from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook

from Tools.Stats.analysis.dv_policy_settings import (
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    normalize_dv_policy,
)
from Tools.Stats.data.group_harmonic_cache import (
    REPEATED_SESSION_POOLING_METHOD_VERSION,
    build_group_harmonic_cache_request,
)


def test_repeated_cache_fingerprints_recording_session_and_source_identity(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.2.0",
                "groups": {"treated": {"label": "Treated"}},
                "sessions": {
                    "visit_1": {"label": "Visit 1", "visit_index": 1},
                    "visit_2": {"label": "Visit 2", "visit_index": 2},
                },
                "participants": {"P1": {"group_id": "treated"}},
                "event_map": {"Faces": 1},
                "preprocessing": {
                    "harmonic_selection_profile": (
                        HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID
                    )
                },
            }
        ),
        encoding="utf-8",
    )
    workbook_1 = project_root / "rec_1_Faces_Results.xlsx"
    workbook_2 = project_root / "rec_2_Faces_Results.xlsx"
    for path, value in ((workbook_1, "one"), (workbook_2, "two")):
        workbook = Workbook()
        workbook.active.append([value])
        workbook.save(path)
        workbook.close()
    subject_data = {
        "rec_1": {"Faces": str(workbook_1)},
        "rec_2": {"Faces": str(workbook_2)},
    }
    assignments = {
        "rec_1": {
            "participant_id": "P1",
            "group_id": "treated",
            "session_id": "visit_1",
            "source_id": "treated_visit_1",
            "visit_index": 1,
            "days_from_baseline": 0.0,
        },
        "rec_2": {
            "participant_id": "P1",
            "group_id": "treated",
            "session_id": "visit_2",
            "source_id": "treated_visit_2",
            "visit_index": 2,
            "days_from_baseline": 14.0,
        },
    }
    settings = normalize_dv_policy(
        {"harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID}
    )

    request = build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=("rec_1", "rec_2"),
        conditions=("Faces",),
        subject_data=subject_data,
        base_frequency_hz=6.0,
        max_freq_hz=8.4,
        settings=settings,
        recording_assignments=assignments,
        declared_session_ids=("visit_1", "visit_2"),
    )

    assert request is not None
    inputs = request.fingerprint["selection_inputs"]
    assert inputs["identity_level"] == "recording"
    assert inputs["declared_session_ids"] == ["visit_1", "visit_2"]
    assert {row["recording_id"] for row in inputs["recording_assignments"]} == {
        "rec_1",
        "rec_2",
    }
    source_rows = request.fingerprint["source_workbooks"]
    assert {row["recording_id"] for row in source_rows} == {"rec_1", "rec_2"}
    assert {row["participant_id"] for row in source_rows} == {"P1"}
    assert {row["days_from_baseline"] for row in source_rows} == {0.0, 14.0}
    assert request.fingerprint["stats_settings"][
        "repeated_session_pooling_version"
    ] == REPEATED_SESSION_POOLING_METHOD_VERSION
    assert REPEATED_SESSION_POOLING_METHOD_VERSION in str(
        request.fingerprint["method_version"]
    )

    changed_assignments = {
        key: dict(value) for key, value in assignments.items()
    }
    changed_assignments["rec_2"]["source_id"] = "replacement_source"
    changed = build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=("rec_1", "rec_2"),
        conditions=("Faces",),
        subject_data=subject_data,
        base_frequency_hz=6.0,
        max_freq_hz=8.4,
        settings=settings,
        recording_assignments=changed_assignments,
        declared_session_ids=("visit_1", "visit_2"),
    )

    assert changed is not None
    assert changed.cache_key != request.cache_key

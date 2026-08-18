from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from Tools.Stats.analysis.dv_policy_group_significant import (
    build_group_significant_harmonic_selection,
    clear_group_significant_selection_cache,
)
from Tools.Stats.analysis.dv_policy_settings import (
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    normalize_dv_policy,
)
from Tools.Stats.data.group_harmonic_cache import (
    REPEATED_SESSION_POOLING_METHOD_VERSION,
)


def test_adaptive_selector_uses_one_recording_aware_list_across_all_sessions(
    tmp_path: Path,
) -> None:
    clear_group_significant_selection_cache()
    project_root = tmp_path / "Project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.2.0",
                "groups": {
                    "treated": {"label": "Treated"},
                    "control": {"label": "Control"},
                },
                "sessions": {
                    "visit_1": {"label": "Visit 1", "visit_index": 1},
                    "visit_2": {"label": "Visit 2", "visit_index": 2},
                },
                "participants": {
                    "P1": {"group_id": "treated"},
                    "P2": {"group_id": "control"},
                },
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
    assignments: dict[str, dict[str, object]] = {}
    subject_data: dict[str, dict[str, str]] = {}
    for participant_id, group_id in (("P1", "treated"), ("P2", "control")):
        for visit_index, session_id in ((1, "visit_1"), (2, "visit_2")):
            recording_id = f"{participant_id}__{session_id}"
            path = project_root / f"{recording_id}_Faces_Results.xlsx"
            _write_full_fft(path)
            subject_data[recording_id] = {"Faces": str(path)}
            assignments[recording_id] = {
                "participant_id": participant_id,
                "group_id": group_id,
                "session_id": session_id,
                "source_id": f"{group_id}_{session_id}",
                "visit_index": visit_index,
            }

    selection = build_group_significant_harmonic_selection(
        subjects=list(subject_data),
        conditions=["Faces"],
        subject_data=subject_data,
        base_frequency_hz=6.0,
        rois={},
        log_func=lambda _message: None,
        settings=normalize_dv_policy(
            {"harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID}
        ),
        max_freq=8.4,
        project_root=project_root,
        participant_group_ids={"P1": "treated", "P2": "control"},
        declared_group_ids=("treated", "control"),
        recording_assignments=assignments,
        declared_session_ids=("visit_1", "visit_2"),
    )
    metadata = selection.to_metadata()

    assert selection.declared_session_ids == ("visit_1", "visit_2")
    assert selection.analysis_condition_ids == (
        "visit_1::Faces",
        "visit_2::Faces",
    )
    assert selection.selection_subjects == ["P1", "P2"]
    assert len(selection.pooling_cells) == 4
    assert set(metadata["condition_z_by_harmonic"]) == {
        "visit_1::Faces",
        "visit_2::Faces",
    }
    assert metadata["pooling_method"] == REPEATED_SESSION_POOLING_METHOD_VERSION
    assert metadata["applied_uniformly_across_sessions"] is True
    assert {row["recording_id"] for row in metadata["recording_assignments"]} == set(
        subject_data
    )
    assert all(
        row["recording_id"] and row["session_id"] and row["participant_id"]
        for row in metadata["source_workbook_fingerprints"]
    )


def _write_full_fft(path: Path) -> None:
    frequencies = [round(0.3 * index, 4) for index in range(29)]
    amplitudes = [
        20.0 if frequency in {1.2, 3.6, 7.2} else (1.2 if index % 2 == 0 else 0.8)
        for index, frequency in enumerate(frequencies)
    ]
    frame = pd.DataFrame(
        {
            f"{frequency:.4f}_Hz": [amplitude, amplitude]
            for frequency, amplitude in zip(frequencies, amplitudes)
        },
        index=["O1", "O2"],
    )
    frame.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")

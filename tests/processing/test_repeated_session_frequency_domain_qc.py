from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from Main_App.processing.frequency_domain_qc import (
    WARNING_REASON_UNUSUAL_VALUES,
    active_frequency_domain_exclusions,
    apply_frequency_domain_qc_decision,
    filter_frequency_domain_recordings,
    frequency_domain_excluded_electrodes_for_recording,
    run_frequency_domain_qc_review,
)
from Main_App.projects import Project, load_project_dataset_index
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_NAME,
    HARMONIC_PROFILE_FIXED_ID,
)


def test_bad_visit_is_recording_scoped_and_paired_visit_remains_available(
    tmp_path: Path,
) -> None:
    project_root = _write_repeated_project(tmp_path / "Project")
    project = Project.load(project_root)

    report = run_frequency_domain_qc_review(project)

    assert report["identity_scope"] == "recording"
    assert report["auto_participant_exclusions"] == []
    assert report["auto_recording_exclusions"] == []
    assert report["auto_recording_electrode_exclusions"] == [
        {
            "recording_id": "P1__VISIT_1",
            "participant_id": "P1",
            "session_id": "visit_1",
            "visit_index": 1,
            "electrode": "O2",
            "reason": "abs summed BCA exceeded hard electrode threshold",
            "threshold_uv": 250.0,
            "max_abs_summed_bca_uv": 300.0,
            "triggering_conditions": ["Faces"],
            "source": "automatic_frequency_domain_qc",
        }
    ]

    apply_frequency_domain_qc_decision(
        project_root,
        report,
        manual_recording_reasons={
            "P1__visit_1": WARNING_REASON_UNUSUAL_VALUES,
        },
    )
    exclusions = active_frequency_domain_exclusions(project_root)

    assert exclusions.excluded_participants == frozenset()
    assert exclusions.manual_excluded_recordings == frozenset({"P1__VISIT_1"})
    assert exclusions.auto_excluded_electrodes_by_recording == {
        "P1__VISIT_1": frozenset({"O2"})
    }
    assert frequency_domain_excluded_electrodes_for_recording(
        project_root,
        "p1__visit_1",
    ) == frozenset({"O2"})

    index = load_project_dataset_index(project_root)
    recording_data = index.recording_data(require_group_assignment=True)
    kept, _data, removed = filter_frequency_domain_recordings(
        project_root,
        list(index.recording_ids),
        recording_data,
        recording_participant_ids={
            recording_id: recording.participant_id
            for recording_id, recording in index.recordings.items()
        },
    )
    assert "P1__visit_1" in removed
    assert "P1__visit_2" in kept


def _write_repeated_project(project_root: Path) -> Path:
    manifest = {
        "schema_version": "2.2.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Faces": 1},
        "preprocessing": {
            "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
            "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
            "harmonic_selection_profile_version": "1.0",
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
        },
        "groups": {
            "treated": {
                "label": "Treated",
                "folder_name": "Treated",
                "raw_input_folder": "Raw/Treated",
            },
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": "Raw/Control",
            },
        },
        "sessions": {
            "visit_1": {"label": "Visit 1", "visit_index": 1},
            "visit_2": {"label": "Visit 2", "visit_index": 2},
        },
        "recording_sources": {},
        "participants": {
            "P1": {"group_id": "treated"},
            "P2": {"group_id": "control"},
        },
        "recordings": {},
    }
    for group_id, participant_id in (("treated", "P1"), ("control", "P2")):
        for visit_index, session_id in ((1, "visit_1"), (2, "visit_2")):
            source_id = f"{group_id}_{session_id}"
            recording_id = f"{participant_id}__{session_id}"
            manifest["recording_sources"][source_id] = {
                "group_id": group_id,
                "session_id": session_id,
                "raw_input_folder": f"Raw/{group_id}/{session_id}",
            }
            manifest["recordings"][recording_id] = {
                "participant_id": participant_id,
                "session_id": session_id,
                "source_id": source_id,
                "raw_file": f"Raw/{group_id}/{session_id}/{participant_id}.bdf",
                "visit_index": visit_index,
            }
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    for _group_id, group_folder, participant_id in (
        ("treated", "Treated", "P1"),
        ("control", "Control", "P2"),
    ):
        for session_id in ("visit_1", "visit_2"):
            recording_id = f"{participant_id}__{session_id}"
            values = (
                {"O2": (150.0, 150.0), "PZ": (1.0, 1.0)}
                if recording_id == "P1__visit_1"
                else {"O2": (1.0, 1.0), "PZ": (1.0, 1.0)}
            )
            _write_bca_workbook(
                project_root
                / "1 - Excel Data Files"
                / "Faces"
                / group_folder
                / f"{recording_id}_Faces_Results.xlsx",
                values,
            )
    return project_root


def _write_bca_workbook(
    path: Path,
    electrode_values: dict[str, tuple[float, float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "Electrode": electrode,
                "1.2000_Hz": values[0],
                "2.4000_Hz": values[1],
            }
            for electrode, values in electrode_values.items()
        ]
    )
    with pd.ExcelWriter(path) as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)

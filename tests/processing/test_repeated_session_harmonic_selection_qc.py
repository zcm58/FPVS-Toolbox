from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Main_App.processing import full_fft_provenance, harmonic_selection_qc
from Main_App.projects import Project
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_NAME,
    HARMONIC_PROFILE_FIXED_ID,
)


@pytest.fixture(autouse=True)
def _current_workbook_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        lambda _root, *, dataset_index=None: {},
    )


def test_fixed_selection_fingerprints_every_recording_without_visit_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
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
            }
        },
        "sessions": {
            "visit_1": {"label": "Visit 1", "visit_index": 1},
            "visit_2": {"label": "Visit 2", "visit_index": 2},
        },
        "recording_sources": {
            "treated_visit_1": {
                "group_id": "treated",
                "session_id": "visit_1",
                "raw_input_folder": "Raw/Treated/visit_1",
            },
            "treated_visit_2": {
                "group_id": "treated",
                "session_id": "visit_2",
                "raw_input_folder": "Raw/Treated/visit_2",
            },
        },
        "participants": {"P1": {"group_id": "treated"}},
        "recordings": {
            "P1__visit_1": {
                "participant_id": "P1",
                "session_id": "visit_1",
                "source_id": "treated_visit_1",
                "raw_file": "Raw/Treated/visit_1/P1.bdf",
                "visit_index": 1,
            },
            "P1__visit_2": {
                "participant_id": "P1",
                "session_id": "visit_2",
                "source_id": "treated_visit_2",
                "raw_file": "Raw/Treated/visit_2/P1.bdf",
                "visit_index": 2,
            },
        },
    }
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for session_id in ("visit_1", "visit_2"):
        _write_bca(
            project_root
            / "1 - Excel Data Files"
            / "Faces"
            / "Treated"
            / f"P1__{session_id}_Faces_Results.xlsx"
        )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"]},
    )
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=12,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_current_project_frequency_protocol",
        lambda _project, _root: protocol,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_project_spectral_eligibility_domain",
        lambda **_kwargs: ((), "", ()),
    )
    cells = tuple(
        SimpleNamespace(
            recording_id=f"P1__{session_id}",
            participant_id="P1",
            condition_label="Faces",
            workbook_path=str(
                (
                    project_root
                    / "1 - Excel Data Files"
                    / "Faces"
                    / "Treated"
                    / f"P1__{session_id}_Faces_Results.xlsx"
                ).resolve()
            ),
            source_evidence=SimpleNamespace(
                expected_scalp_channels=("O1", "O2")
            ),
            downstream_cell_excluded=False,
            whole_scalp_normalization=SimpleNamespace(excluded_channels=()),
        )
        for session_id in ("visit_1", "visit_2")
    )
    coverage = SimpleNamespace(
        fingerprint="test-roi-coverage",
        decision_fingerprint="test-frequency-decisions",
        roi_snapshot=SimpleNamespace(
            fingerprint="test-roi-definition",
            rois=(
                SimpleNamespace(
                    name="Posterior",
                    electrodes=("O1", "O2"),
                ),
            ),
        ),
        cells=cells,
        cell_for=lambda identity, condition: next(
            (
                cell
                for cell in cells
                if cell.recording_id.casefold() == str(identity).casefold()
                and cell.condition_label.casefold() == str(condition).casefold()
            ),
            None,
        ),
    )
    release_context = (
        SimpleNamespace(fingerprint="test-outcomes"),
        coverage,
        SimpleNamespace(fingerprint="test-final-release"),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_current_final_release_context",
        lambda _root: release_context,
    )
    from Main_App.processing import roi_coverage

    monkeypatch.setattr(
        roi_coverage,
        "require_project_final_release",
        lambda _root: release_context,
    )
    project = Project.load(project_root)

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)
    loaded = harmonic_selection_qc.load_processing_harmonic_selection(project)

    metadata = report.selection_metadata
    assert metadata["selection_identity_level"] == "recording"
    assert metadata["selection_recordings"] == ["P1__visit_1", "P1__visit_2"]
    assert metadata["selection_subjects"] == ["P1"]
    assert metadata["declared_session_ids"] == ["visit_1", "visit_2"]
    sources = metadata["source_workbook_fingerprints"]
    assert len(sources) == 2
    assert {row["recording_id"] for row in sources} == {
        "P1__visit_1",
        "P1__visit_2",
    }
    assert loaded.to_metadata()["selection_fingerprint"] == metadata[
        "selection_fingerprint"
    ]


def _write_bca(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "Electrode": ["O1", "O2"],
            "1.2000_Hz": [1.0, 2.0],
            "2.4000_Hz": [0.5, 1.0],
        }
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="BCA (uV)", index=False)

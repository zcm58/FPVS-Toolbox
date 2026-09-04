from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from Main_App.processing import full_fft_provenance
from Main_App.processing.frequency_domain_qc import (
    FrequencyDomainCoverageDecisions,
)
from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceStaleError,
    REPEATED_FULL_FFT_PROVENANCE_METHOD_VERSION,
    validate_project_full_fft_provenance,
    write_project_full_fft_provenance,
)
from Main_App.io.eeg_geometry import biosemi64_geometry_identity
from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION
from Main_App.projects import FrequencyProtocol


def test_repeated_full_fft_provenance_keeps_recording_and_session_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )
    manifest = {
        "schema_version": "2.2.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
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
                "days_from_baseline": 0.0,
            },
            "P1__visit_2": {
                "participant_id": "P1",
                "session_id": "visit_2",
                "source_id": "treated_visit_2",
                "raw_file": "Raw/Treated/visit_2/P1.bdf",
                "visit_index": 2,
                "days_from_baseline": 14.0,
            },
        },
        "preprocessing": {},
        "frequency_protocol": protocol.to_manifest(),
    }
    project_root.mkdir()
    manifest_path = project_root / "project.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for session_id in ("visit_1", "visit_2"):
        path = (
            project_root
            / "1 - Excel Data Files"
            / "Faces"
            / "Treated"
            / f"P1__{session_id}_Faces_Results.xlsx"
        )
        _write_full_fft(path)
    ledger_path = project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    geometry = biosemi64_geometry_identity()
    ledger_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    f"P1__{session_id}": {
                        "participant_id": "P1",
                        "recording_id": f"P1__{session_id}",
                        "session_id": session_id,
                        "source_id": f"treated_{session_id}",
                        "visit_index": index,
                        "days_from_baseline": days,
                        "status": "completed",
                        "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
                        "processing_fingerprint": "fixture-processing-fingerprint",
                        "condition_completeness": "complete",
                        "geometry": geometry,
                    }
                    for session_id, index, days in (
                        ("visit_1", 1, 0.0),
                        ("visit_2", 2, 14.0),
                    )
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        full_fft_provenance,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: FrequencyDomainCoverageDecisions(
            decision_fingerprint="reviewed-frequency-qc-fixture",
            review_complete=True,
            excluded_participants=frozenset(),
            excluded_recordings=frozenset(),
            excluded_participant_conditions=frozenset(),
            excluded_recording_conditions=frozenset(),
            excluded_electrodes_by_participant_condition={},
            excluded_electrodes_by_recording_condition={},
            reviewed_decisions=(),
        ),
    )

    provenance = write_project_full_fft_provenance(
        project_root,
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
    )
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    metadata = saved["tools"]["processing"]["full_fft_provenance"]
    source_rows = metadata["source_workbooks"]

    assert provenance.method_version == REPEATED_FULL_FFT_PROVENANCE_METHOD_VERSION
    assert provenance.source_workbook_count == 2
    assert provenance.frequency_protocol_fingerprint == protocol.fingerprint
    assert {row["recording_id"] for row in source_rows} == {
        "P1__visit_1",
        "P1__visit_2",
    }
    assert {row["session_id"] for row in source_rows} == {"visit_1", "visit_2"}
    assert {row["source_id"] for row in source_rows} == {
        "treated_visit_1",
        "treated_visit_2",
    }
    assert {row["days_from_baseline"] for row in source_rows} == {0.0, 14.0}
    assert metadata["cohort_state"]["identity_scope"] == "recording"
    assert "completed_recordings" in metadata["cohort_state"]
    assert "completed_participants" not in metadata["cohort_state"]
    assert metadata["frequency_qc_state"] == {
        "authority": "reviewed_frequency_domain_qc",
        "review_complete": True,
        "decision_fingerprint": "reviewed-frequency-qc-fixture",
        "excluded_participants": [],
        "excluded_participant_conditions": [],
        "excluded_electrodes_by_participant_condition": [],
        "excluded_recordings": [],
        "excluded_recording_conditions": [],
        "excluded_electrodes_by_recording_condition": [],
    }

    monkeypatch.setattr(
        full_fft_provenance,
        "resolve_frequency_qc_coverage_decisions",
        lambda _root: FrequencyDomainCoverageDecisions(
            decision_fingerprint="reviewed-frequency-qc-fixture",
            review_complete=True,
            excluded_participants=frozenset(),
            excluded_recordings=frozenset(),
            excluded_participant_conditions=frozenset(),
            excluded_recording_conditions=frozenset(
                {("P1__visit_1", "Faces")}
            ),
            excluded_electrodes_by_participant_condition={},
            excluded_electrodes_by_recording_condition={},
            reviewed_decisions=(),
        ),
    )
    with pytest.raises(
        FullFftProvenanceStaleError,
        match="frequency-domain cohort/QC exclusions changed",
    ):
        validate_project_full_fft_provenance(
            project_root,
            base_frequency_hz=6.0,
            oddball_frequency_hz=1.2,
        )


def _write_full_fft(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "0.0000_Hz": [1.0],
            "0.3000_Hz": [1.0],
            "0.6000_Hz": [1.0],
            "0.9000_Hz": [1.0],
            "1.2000_Hz": [2.0],
            "1.5000_Hz": [1.0],
        },
        index=["O1"],
    )
    frame.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")

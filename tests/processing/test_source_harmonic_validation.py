from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

from Main_App.exports.post_process_excel import write_results_workbook
from Main_App.processing import raw_registration_state, roi_coverage
from Main_App.processing.processing_ledger import ledger_path
from Main_App.processing.recording_condition_outcomes import CELL_READY
from Main_App.processing.source_harmonic_validation import (
    SourceHarmonicValidation, current_source_harmonic_validation, source_harmonic_validation_scope,
)


def test_source_pair_limits_and_lifetime_are_specific_to_one_worker():
    project = SimpleNamespace(preprocessing={"max_parallel_workers": 3}, options={"max_workers": 1})
    assert current_source_harmonic_validation() is None
    with pytest.raises(RuntimeError, match="cancelled"):
        with source_harmonic_validation_scope(project):
            session = current_source_harmonic_validation()
            assert session.requested_workers == 3
            with source_harmonic_validation_scope():
                assert current_source_harmonic_validation() is not session
                assert current_source_harmonic_validation().requested_workers is None
            assert current_source_harmonic_validation() is session
            raise RuntimeError("cancelled")
    assert current_source_harmonic_validation() is None


@pytest.fixture
def released_study(tmp_path, monkeypatch):
    (tmp_path / "project.json").write_text(json.dumps({"participants": {"P1": {}}}))
    ledger = ledger_path(tmp_path)
    ledger.parent.mkdir(exist_ok=True)
    ledger.write_text("{}")
    anchor = tmp_path / "P1_Faces_Results.fpvs"
    written = write_results_workbook(str(anchor), {
        "FullFFT Amplitude (uV)": pd.DataFrame({"Electrode": ["Oz"], "0.0000_Hz": [2.0]}),
        "BCA (uV)": pd.DataFrame({"Electrode": ["Oz"], "0.3000_Hz": [0.5]}),
    })
    cell = SimpleNamespace(status=CELL_READY, export_receipt={"path": str(anchor), "workbook_write": written})
    release = (SimpleNamespace(cells=[cell]), SimpleNamespace(decision_fingerprint="accepted"), {"run": 1})
    validator = Mock(return_value=release)
    registration = Mock()
    monkeypatch.setattr(roi_coverage, "require_current_final_release", validator)
    monkeypatch.setattr(raw_registration_state, "require_registered_raw_processing_complete", registration)
    return release, validator, registration


def test_source_publication_only_reuses_detached_release_and_checks_registration(tmp_path, released_study):
    release, validator, registration = released_study
    session = SourceHarmonicValidation()
    first = session.current_release(tmp_path, expected_decision_fingerprint="accepted")
    first[2]["run"] = 25
    manifest = tmp_path / "project.json"
    project = json.loads(manifest.read_bytes())
    project["tools"] = {"post_processing": {"artifact_freshness": {"l2": {"status": "ready"}}}}
    manifest.write_text(json.dumps(project))

    second = session.current_release(tmp_path, expected_decision_fingerprint="accepted")

    assert second[2]["run"] == 1
    assert second[2] is not release[2]
    validator.assert_called_once_with(tmp_path, expected_decision_fingerprint="accepted")
    registration.assert_called_once_with(tmp_path)


@pytest.mark.parametrize("change", ["membership", "settings", "ledger", "interpolation", "decision"])
def test_source_pair_reopens_authoritative_validator_for_changed_inputs(tmp_path, released_study, change):
    _, validator, _ = released_study
    session = SourceHarmonicValidation()
    session.current_release(tmp_path, expected_decision_fingerprint="accepted")
    assert session.files is not None
    if change in ("membership", "settings"):
        manifest = tmp_path / "project.json"
        state = json.loads(manifest.read_bytes())
        if change == "membership":
            state["participants"]["P2"] = {}
        else:
            state["preprocessing"] = {"high_pass": 1.0}
        manifest.write_text(json.dumps(state))
    elif change == "ledger":
        ledger_path(tmp_path).write_text('{"changed":true}')
    elif change == "interpolation":
        (ledger_path(tmp_path).parent / "condition_interpolation_run.json").write_text("{}")
    decision = "revised" if change == "decision" else "accepted"
    validator.side_effect = ValueError("authoritative release changed")
    with pytest.raises(ValueError, match="authoritative release changed"):
        session.current_release(tmp_path, expected_decision_fingerprint=decision)
    assert validator.call_count == 2
    assert session.files is None


def test_source_pair_revalidates_mixed_native_and_historical_cells(tmp_path: Path, released_study):
    release, validator, _ = released_study
    release[0].cells.append(SimpleNamespace(
        status=CELL_READY, export_receipt={"path": str(tmp_path / "P2_Faces_Results.xlsx")},
    ))
    session = SourceHarmonicValidation()
    for _ in range(2):
        session.current_release(tmp_path, expected_decision_fingerprint="accepted")
        assert session.files is None
    assert validator.call_count == 2

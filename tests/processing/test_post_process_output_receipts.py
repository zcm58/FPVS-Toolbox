from __future__ import annotations

from types import SimpleNamespace

import mne
import numpy as np
import pandas as pd
import pytest

from Main_App.Shared.post_process import post_process
from Main_App.processing.output_integrity import OutputIntegrityError
from Main_App.projects.frequency_protocol import (
    EXPECTED_CYCLES_SOURCE_MANUAL,
    FrequencyProtocol,
)


def _protocol() -> FrequencyProtocol:
    return FrequencyProtocol.from_recurrence(
        3,
        10,
        expected_analyzed_oddball_cycles=36,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )


def _epochs(*, invalid: float | None = None) -> mne.EpochsArray:
    sampling_rate = 20.0
    sample_count = 2_400
    info = mne.create_info(["Oz"], sampling_rate, ["eeg"])
    with info._unlock():
        info["highpass"] = 0.1
        info["lowpass"] = 9.0
    values = np.random.default_rng(42).normal(
        size=(1, 1, sample_count)
    ) * 1e-6
    if invalid is not None:
        values[0, 0, 100] = invalid
    metadata = pd.DataFrame(
        {
            "crop_mode": ["project_marker_plan_target_grid_v2"],
            "n55": [36],
            "first55_samp": [0],
            "last55_samp": [sample_count - 1],
            "N_step": [200],
            "fallback_reason": [""],
            "approved_span_fingerprint": ["a" * 64],
            "marker_plan_fingerprint": ["b" * 64],
            "source_start_sample": [100],
            "source_stop_sample": [2_500],
            "target_start_sample": [100],
            "target_stop_sample": [2_500],
            "marker_disposition": ["complete"],
        }
    )
    return mne.EpochsArray(
        values,
        info,
        tmin=0.0,
        metadata=metadata,
        verbose=False,
    )


def _app(tmp_path, epochs: mne.EpochsArray):
    return SimpleNamespace(
        save_folder_path=SimpleNamespace(get=lambda: str(tmp_path)),
        settings={
            "frequency_protocol": _protocol(),
            "high_pass": 0.1,
            "low_pass": 9.0,
            "line_noise_filter_enabled": False,
            "_fpvs_recording_id": "P01__visit_1",
            "output_recording_stem": "P01__visit_1",
            "_fpvs_participant_id": "P01",
            "_fpvs_session_id": "visit_1",
            "_fpvs_expected_plan_run_id": "run-123",
            "_fpvs_processing_fingerprint": "c" * 64,
            "_fpvs_processing_fingerprint_version": "processing-v1",
        },
        preprocessed_data={"Faces": [epochs]},
        data_paths=[],
        log=lambda _message: None,
        export_receipts=[],
    )


def test_current_run_receipt_links_atomic_workbook_and_exact_span(tmp_path):
    app = _app(tmp_path, _epochs())

    post_process(app, ["Faces"])

    assert len(app.export_receipts) == 1
    receipt = app.export_receipts[0]
    assert receipt["version"] == "recording_condition_export_receipt_v1"
    assert receipt["status"] == "written"
    assert receipt["run_id"] == "run-123"
    assert receipt["recording_id"] == "P01__visit_1"
    assert receipt["condition_label"] == "Faces"
    assert receipt["retained_occurrence_count"] == 1
    assert receipt["retained_occurrences"][0]["span_status"] == "exact"
    assert receipt["workbook_write"]["schema_validation"]["status"] == "passed"
    assert receipt["workbook_write"]["artifact"]["sha256"]
    assert {item["value_category"] for item in receipt["finite_integrity"]} == {
        "retained_eeg",
        "bca",
    }


@pytest.mark.parametrize("invalid", [np.nan, np.inf, -np.inf])
def test_nonfinite_source_blocks_current_export_and_preserves_prior_workbook(
    tmp_path,
    invalid,
):
    destination = tmp_path / "Faces" / "P01__visit_1_Faces_Results.xlsx"
    destination.parent.mkdir(parents=True)
    prior_bytes = b"prior complete workbook placeholder"
    destination.write_bytes(prior_bytes)
    app = _app(tmp_path, _epochs(invalid=invalid))

    with pytest.raises(OutputIntegrityError, match="NaN or infinite"):
        post_process(app, ["Faces"])

    assert destination.read_bytes() == prior_bytes
    assert len(app.export_receipts) == 1
    receipt = app.export_receipts[0]
    assert receipt["status"] == "blocked"
    assert receipt["failure_stage"] == "retained_signal"
    assert receipt["current_run_artifact"] is None
    assert receipt["prior_artifact"]["sha256"]
    assert receipt["integrity_failure"]["electrode"] == "Oz"

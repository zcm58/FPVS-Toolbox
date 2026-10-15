from __future__ import annotations

from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.model_diagnostics import (
    summarize_inverse_model,
    summarize_time_domain_inputs,
)
from Tools.LORETA_Visualizer.source_producers.source_validation_report import (
    _cluster_inference_summary,
    _forward_model_summary,
)


def test_model_covariance_is_reported_without_claiming_participant_rank() -> None:
    info = mne.create_info(["Fz", "Cz", "Pz"], 100.0, "eeg")
    raw = mne.io.RawArray(np.zeros((3, 10)), info, verbose=False)
    raw.set_eeg_reference("average", projection=True, verbose=False)
    covariance = mne.make_ad_hoc_cov(raw.info, verbose=False)

    result = summarize_inverse_model(raw.info, {"noise_cov": covariance})

    assert result["channel_count"] == 3
    assert result["channel_names"] == ["Fz", "Cz", "Pz"]
    assert result["projections"][0]["description"] == "Average EEG reference"
    assert result["projections"][0]["active"] is False
    assert result["participant_data_rank_status"] == "not_measured"
    actual = covariance["data"]
    reported = result["model_noise_covariance"]
    assert reported["estimated_from_recorded_noise"] is False
    assert reported["diagonal"] is True
    assert reported["variance_min"] == pytest.approx(float(np.min(actual)), abs=0)
    assert reported["variance_max"] == pytest.approx(float(np.max(actual)), abs=0)
    assert "rank" not in reported


def test_absent_covariance_is_not_fabricated() -> None:
    info = mne.create_info(["Fz"], 100.0, "eeg")
    assert "model_noise_covariance" not in summarize_inverse_model(info, {})


@pytest.mark.parametrize("recorded", [False, True])
def test_input_report_preserves_interpolation_and_reference_provenance(recorded: bool) -> None:
    provenance = {"condition_electrode_interpolation": {"22": {"channels": ["Fz"]}}} if recorded else {}
    reference = {"custom_ref_applied": 0, "projections": [{"description": "Average EEG reference", "active": True}]}
    record = SimpleNamespace(
        participant_id="P01", group_id="control", condition_id="22", condition_label="Faces",
        channel_names=("Fz", "Cz"), bad_channels=(),
        sidecar={"reference": reference, "geometry": {"montage": "biosemi64"}, "processing": {"provenance": provenance}},
    )

    result = summarize_time_domain_inputs([record])[0]

    assert result["bad_channels"] == []
    assert result["reference"] == reference
    assert result["interpolation_provenance_status"] == ("recorded" if recorded else "not_recorded")
    assert result["condition_electrode_interpolation"] == provenance.get("condition_electrode_interpolation")
    assert result["participant_data_rank_status"] == "not_measured"


def test_report_retains_exact_permutation_and_model_assumptions() -> None:
    metadata = {
        "cluster_mask_algorithm_version": 2, "cluster_mask_participant_count": 5,
        "cluster_permutation_mode": "exact", "cluster_p_value_estimator": "exact_tail_proportion",
        "cluster_minimum_attainable_p": 1 / 32,
        "cluster_significant_clusters": [{"cluster_mass": 7.5, "p_value": 1 / 32}],
    }
    assert _cluster_inference_summary(metadata) == metadata
    assert _forward_model_summary({"noise_covariance": "mne_ad_hoc_diagonal_eeg", "average_reference_projection": True}) == {
        "noise_covariance": "mne_ad_hoc_diagonal_eeg", "average_reference_projection": True,
    }

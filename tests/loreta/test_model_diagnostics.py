from __future__ import annotations

from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.model_diagnostics import (
    summarize_inverse_model,
    summarize_time_domain_inputs,
    numerical_rank_summary,
    summarize_recorded_data_rank,
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
    assert reported["unprojected_numerical_rank"]["rank"] == 3
    assert reported["projected_numerical_rank"]["rank"] == 2


def test_absent_covariance_is_not_fabricated() -> None:
    info = mne.create_info(["Fz"], 100.0, "eeg")
    assert "model_noise_covariance" not in summarize_inverse_model(info, {})


def test_rank_diagnostic_measures_known_linear_dependence_and_zero_matrix():
    time = np.linspace(-1., 1., 100)
    matrix = np.vstack((time, time**2, 2*time + time**2))
    result = numerical_rank_summary(matrix)
    assert result["rank"] == 2
    assert result["full_rank"] is False
    assert result["absolute_tolerance"] > 0
    zero = numerical_rank_summary(np.zeros((3, 10)))
    assert zero["rank"] == 0
    assert zero["condition_number_on_retained_subspace"] is None


def test_derivative_rank_and_reference_diagnostic_never_mutates_samples():
    info = mne.create_info(["Fz", "Cz", "Pz"], 100., "eeg")
    data = np.random.default_rng(11).normal(size=(3, 100)) * 1e-6
    raw = mne.io.RawArray(data.copy(), info, verbose=False)
    raw.set_eeg_reference("average", projection=True, verbose=False)
    result = summarize_recorded_data_rank(raw, expected_info=raw.info)
    assert result["unprojected"]["rank"] == 3
    assert result["after_recorded_projectors"]["rank"] == 2
    assert result["participant_data_rank_status"] == "measured_source_ready_derivative"
    assert result["model_geometry_status"] == "incomplete_coordinates_unverified"
    np.testing.assert_array_equal(raw.get_data(), data)


def test_derivative_rank_rejects_ordered_channel_mismatch():
    info = mne.create_info(["Fz", "Cz"], 100., "eeg")
    raw = mne.io.RawArray(np.ones((2, 10)), info, verbose=False)
    other = mne.create_info(["Cz", "Fz"], 100., "eeg")
    with pytest.raises(ValueError, match="ordered inverse"):
        summarize_recorded_data_rank(raw, expected_info=other)


def test_applied_and_pending_average_reference_have_same_projector():
    info = mne.create_info(["Fz", "Cz", "Pz"], 100., "eeg")
    raw = mne.io.RawArray(np.random.default_rng(1).normal(size=(3, 100)), info, verbose=False)
    raw.set_eeg_reference("average", projection=True, verbose=False)
    expected = raw.info.copy()
    raw.apply_proj(verbose=False)
    result = summarize_recorded_data_rank(raw, expected_info=expected)
    assert result["model_reference_status"] == "matching_projection_operator"
    assert raw.info["projs"][0]["active"] is True


def test_derivative_rank_rejects_known_electrode_geometry_mismatch():
    info = mne.create_info(["Fz", "Cz"], 100., "eeg")
    info.set_montage(mne.channels.make_standard_montage("standard_1020"))
    raw = mne.io.RawArray(np.ones((2, 10)), info, verbose=False)
    other = info.copy()
    other["chs"][0]["loc"][0] += 0.001
    with pytest.raises(ValueError, match="electrode coordinates"):
        summarize_recorded_data_rank(raw, expected_info=other)


def test_derivative_rank_rejects_geometry_frame_mismatch_even_with_equal_coordinates():
    from mne.io.constants import FIFF

    info = mne.create_info(["Fz", "Cz"], 100., "eeg")
    info.set_montage(mne.channels.make_standard_montage("standard_1020"))
    raw = mne.io.RawArray(np.ones((2, 10)), info, verbose=False)
    other = info.copy()
    other["chs"][0]["coord_frame"] = FIFF.FIFFV_COORD_MRI
    with pytest.raises(ValueError, match="coordinate frames"):
        summarize_recorded_data_rank(raw, expected_info=other)


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

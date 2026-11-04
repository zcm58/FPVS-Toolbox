from __future__ import annotations

import numpy as np
import pytest

from Tools.LORETA_Visualizer.source_producers.native_spectral_reference import build_native_sphere_model
from Tools.LORETA_Visualizer.source_producers.source_spectral_diagnostics import (
    SpectralDiagnosticConfig, binomial_rejection_summary, run_spectral_diagnostic,
    synthetic_signed_cohort, stress_harmonics,
)


def test_zero_rejections_does_not_establish_five_percent_error_control():
    result = binomial_rejection_summary(0, 64)
    assert result["rate"] == 0
    assert result["binomial_95_percent_interval"][1] > .05
    assert binomial_rejection_summary(64, 64)["binomial_95_percent_interval"][1] == 1


def test_signed_cohorts_are_seeded_average_referenced_and_selection_is_explicit():
    config = SpectralDiagnosticConfig(participant_count=6, n_times=1000, sfreq=100., harmonics_hz=(2., 4.))
    model = build_native_sphere_model("MNE", sfreq=100.)
    first, metadata = synthetic_signed_cohort(model, config, scenario="correlated_null", replicate=0)
    second, _ = synthetic_signed_cohort(model, config, scenario="correlated_null", replicate=0)
    np.testing.assert_array_equal(first, second)
    assert np.min(first) < 0 < np.max(first)
    np.testing.assert_allclose(np.mean(first, axis=1), 0., atol=1e-20)
    assert metadata["injected_source_indices"] == []
    assert set(stress_harmonics(first, config)) <= set(config.harmonics_hz)


def test_native_bounded_experiment_does_not_qualify_inference():
    config = SpectralDiagnosticConfig(
        participant_count=6, null_replicates=2, signal_replicates=1,
        n_times=1000, sfreq=100., harmonics_hz=(2., 4.), permutation_count=64,
    )
    report = run_spectral_diagnostic(config, scenarios=("white_null", "high_signal"), methods=("MNE",))
    assert report["qualification"]["source_inference_confirmatory"] is False
    assert len(report["results"]) == 2
    assert report["results"][0]["any_cluster_rejection"]["replicates"] == 2
    assert report["results"][0]["source_count"] == 12
    assert report["results"][1]["mean_z_at_first_injected_source"][0] > 0


def test_checkpoint_resume_retains_completed_cohorts_and_checks_identity(tmp_path, monkeypatch):
    from Tools.LORETA_Visualizer.source_producers import source_spectral_diagnostics as diagnostic

    config = SpectralDiagnosticConfig(participant_count=6, null_replicates=2, n_times=1000, sfreq=100., harmonics_hz=(2., 4.), permutation_count=64)
    checkpoint = tmp_path / "checkpoint.json"
    first = run_spectral_diagnostic(config, scenarios=("white_null",), methods=("MNE",), checkpoint_path=checkpoint)

    def fail(*_args, **_kwargs):
        raise AssertionError("A completed cohort must not be recomputed.")

    monkeypatch.setattr(diagnostic, "_run_cohort", fail)
    resumed = run_spectral_diagnostic(config, scenarios=("white_null",), methods=("MNE",), checkpoint_path=checkpoint, resume=True)
    assert resumed["results"] == first["results"]
    with pytest.raises(ValueError, match="do not match"):
        run_spectral_diagnostic(config, scenarios=("correlated_null",), methods=("MNE",), checkpoint_path=checkpoint, resume=True)


@pytest.mark.parametrize("kwargs", [{"participant_count": 1}, {"null_replicates": 0}, {"model": "participant_mri"}])
def test_invalid_diagnostic_config_rejected(kwargs):
    with pytest.raises(ValueError):
        SpectralDiagnosticConfig(**kwargs)

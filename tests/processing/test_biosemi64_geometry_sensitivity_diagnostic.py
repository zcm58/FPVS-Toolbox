from __future__ import annotations

import csv
import json
import sys

import numpy as np
import pytest

from scripts.manual_diagnostics import run_biosemi64_geometry_sensitivity as diagnostic


def test_production_noise_helper_module_is_registered() -> None:
    module_name = diagnostic.compute_noise_stats_for_bin_channels.__module__

    assert module_name in sys.modules
    assert (
        sys.modules[module_name].compute_noise_stats_for_bin_channels
        is diagnostic.compute_noise_stats_for_bin_channels
    )


def test_synthetic_protocol_is_frozen_and_deterministic() -> None:
    first, first_sfreq, first_metadata = diagnostic.generate_synthetic_data()
    second, second_sfreq, second_metadata = diagnostic.generate_synthetic_data()

    assert diagnostic._canonical_montage_channels() == diagnostic.BIOSEMI64_CHANNELS
    assert len(diagnostic.BIOSEMI64_CHANNELS) == 64
    assert first.shape == (64, 10_240)
    assert np.array_equal(first, second)
    assert first_sfreq == second_sfreq == 256.0
    assert first_metadata == second_metadata
    assert dict(diagnostic.SYNTHETIC_BAD_CHANNEL_SCENARIOS) == {
        "zero_bad_control": (),
        "isolated_frontal": ("Fp1",),
        "isolated_temporal": ("T7",),
        "isolated_central": ("Cz",),
        "isolated_posterior": ("Oz",),
        "cluster_frontal": ("Fp1", "AF7", "AF3"),
        "cluster_temporal": ("FT7", "T7", "TP7"),
        "cluster_central": ("C3", "Cz", "C4"),
        "cluster_posterior": ("PO7", "Oz", "PO8"),
    }


def test_coordinate_audit_uses_finite_head_frame_positions() -> None:
    rows, sphere_identity = diagnostic.build_coordinate_rows()

    assert [row["channel"] for row in rows] == list(diagnostic.BIOSEMI64_CHANNELS)
    assert len(rows) == 64
    assert all(
        np.isfinite(
            [
                row["head_space_distance_mm"],
                row["fitted_sphere_angular_difference_deg"],
                row["fitted_sphere_radius_difference_mm"],
            ]
        ).all()
        for row in rows
    )
    assert max(row["head_space_distance_mm"] for row in rows) > 1.0
    assert set(sphere_identity) == {"standard_1005", "biosemi64"}


def test_zero_bad_control_proves_montage_alone_does_not_change_voltages() -> None:
    data, sfreq, _ = diagnostic.generate_synthetic_data()

    time_rows, _, difference_rows, decision_rows, summary = diagnostic.compare_scenario(
        data,
        sfreq=sfreq,
        scenario="zero_bad_control",
        bad_channels=(),
        observed_truth_is_valid=True,
    )

    assert all(row["standard_1005_vs_biosemi64_max_abs_uv"] == 0.0 for row in time_rows)
    assert all(row["fft_amplitude_absolute_difference_uv"] == 0.0 for row in difference_rows)
    assert all(row["bca_absolute_difference_uv"] == 0.0 for row in difference_rows)
    assert decision_rows == []
    assert all(stage["all_channel_max_abs_difference_uv"] == 0.0 for stage in summary["stages"].values())


def test_fixed_bad_channel_changes_only_through_interpolation_and_reference() -> None:
    data, sfreq, _ = diagnostic.generate_synthetic_data()

    time_rows, metric_rows, difference_rows, _, summary = diagnostic.compare_scenario(
        data,
        sfreq=sfreq,
        scenario="isolated_posterior",
        bad_channels=("Oz",),
        observed_truth_is_valid=True,
    )

    pre_reference_good_rows = [row for row in time_rows if row["stage"] == "interpolated" and row["channel"] != "Oz"]
    assert all(row["standard_1005_vs_biosemi64_max_abs_uv"] == 0.0 for row in pre_reference_good_rows)
    assert (
        next(row for row in time_rows if row["stage"] == "interpolated" and row["channel"] == "Oz")[
            "standard_1005_vs_biosemi64_max_abs_uv"
        ]
        > 0.0
    )
    assert any(
        row["stage"] == "average_referenced"
        and row["channel"] != "Oz"
        and row["standard_1005_vs_biosemi64_max_abs_uv"] > 0.0
        for row in time_rows
    )
    assert len(metric_rows) == 2 * 2 * 64 * len(diagnostic.TARGET_FREQUENCIES_HZ)
    assert any(row["fft_amplitude_absolute_difference_uv"] > 0.0 for row in difference_rows)
    assert summary["stages"]["interpolated"]["interpolated_channel_rms_difference_uv"] > 0.0


def test_output_bundle_is_machine_readable_and_records_empty_decision_table(
    tmp_path,
) -> None:
    data, sfreq, metadata = diagnostic.generate_synthetic_data()
    output_dir = tmp_path / "geometry-audit"

    summary = diagnostic.run_diagnostic(
        output_dir=output_dir,
        data_v=data,
        sfreq=sfreq,
        input_metadata=metadata,
        scenarios=(("zero_bad_control", ()),),
        observed_truth_is_valid=True,
    )

    loaded = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert loaded["scientific_results_sha256"] == summary["scientific_results_sha256"]
    assert loaded["overall"]["zero_bad_control_exactly_equal"] is True
    assert set(loaded["output_files_sha256"]) == {
        "coordinate_differences.csv",
        "target_metric_differences.csv",
        "target_metrics.csv",
        "threshold_decision_changes.csv",
        "time_domain_differences.csv",
    }
    with (output_dir / "threshold_decision_changes.csv").open(
        encoding="utf-8",
        newline="",
    ) as stream:
        assert list(csv.DictReader(stream)) == []


def test_direct_bdf_mode_requires_explicit_exact_bad_channel_names() -> None:
    assert diagnostic._parse_bad_channels("none") == ()
    assert diagnostic._parse_bad_channels("Fp1,Oz") == ("Fp1", "Oz")
    with pytest.raises(ValueError, match="exact canonical"):
        diagnostic._parse_bad_channels("A1")
    with pytest.raises(ValueError, match="Duplicate"):
        diagnostic._parse_bad_channels("Oz,Oz")


def test_fft_targets_must_resolve_to_exact_bins() -> None:
    assert diagnostic._validate_exact_target_bins(10_240, 256.0) == (
        48,
        96,
        144,
        192,
        288,
    )
    with pytest.raises(ValueError, match="not exact"):
        diagnostic._validate_exact_target_bins(10_239, 256.0)

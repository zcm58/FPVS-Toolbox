from __future__ import annotations

from Main_App.processing.raw_channel_qc import RawChannelQCConfig
from Main_App.processing.removed_electrode_detection import (
    DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION,
    REMOVED_ELECTRODE_DETECTION_INFO_TEXT,
    RemovedElectrodeDetectionCalibration,
    manual_removed_electrodes_for_pid,
    normalize_manual_removed_electrodes_map,
    normalize_removed_electrode_detection_mode,
    parse_electrode_list,
    is_high_amplitude_removed_channel,
    is_low_variance_removed_channel,
    removed_electrode_threshold_payload,
    spatial_predictability_outliers,
    spatial_predictability_threshold,
)


def test_default_calibration_feeds_raw_qc_config_defaults() -> None:
    calibration = DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION
    config = RawChannelQCConfig()

    assert config.low_std_uv == calibration.low_std_uv
    assert config.low_p2p_99_uv == calibration.low_p2p_99_uv
    assert config.high_std_uv_floor == calibration.high_std_uv_floor
    assert config.high_p2p_99_uv_floor == calibration.high_p2p_99_uv_floor
    assert config.min_bad_cluster_warning_size == 4
    assert config.min_bad_cluster_size == 6
    assert config.spatial_predictability_max_bad_corr == (
        calibration.spatial_predictability_max_bad_corr
    )
    assert config.sample_windows == calibration.sample_windows


def test_threshold_payload_exposes_calibration_values() -> None:
    calibration = RemovedElectrodeDetectionCalibration(
        low_std_uv=12.5,
        high_std_uv_floor=1500.0,
        min_bad_cluster_size=8,
        spatial_qc_enabled=False,
        sample_windows=9,
    )

    payload = removed_electrode_threshold_payload(calibration)

    assert payload["low_std_uv"] == 12.5
    assert payload["high_std_uv_floor"] == 1500.0
    assert payload["min_bad_cluster_size"] == 8
    assert payload["spatial_qc_enabled"] is False
    assert "neighbor_distance_factor" not in payload
    assert calibration.sample_windows == 9


def test_low_variance_detector_accepts_absolute_and_relative_profiles() -> None:
    calibration = DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION

    assert is_low_variance_removed_channel(
        std_uv=2.0,
        p2p_99_uv=20.0,
        median_std_uv=500.0,
        median_p2p_99_uv=2_000.0,
        calibration=calibration,
    )
    assert is_low_variance_removed_channel(
        std_uv=40.0,
        p2p_99_uv=200.0,
        median_std_uv=500.0,
        median_p2p_99_uv=2_000.0,
        calibration=calibration,
    )
    assert not is_low_variance_removed_channel(
        std_uv=90.0,
        p2p_99_uv=200.0,
        median_std_uv=500.0,
        median_p2p_99_uv=2_000.0,
        calibration=calibration,
    )


def test_high_amplitude_detector_requires_absolute_and_relative_evidence() -> None:
    calibration = DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION

    assert is_high_amplitude_removed_channel(
        std_uv=3_000.0,
        p2p_99_uv=15_000.0,
        median_std_uv=300.0,
        median_p2p_99_uv=1_000.0,
        calibration=calibration,
    )
    assert not is_high_amplitude_removed_channel(
        std_uv=2_100.0,
        p2p_99_uv=11_000.0,
        median_std_uv=1_000.0,
        median_p2p_99_uv=4_000.0,
        calibration=calibration,
    )
    assert not is_high_amplitude_removed_channel(
        std_uv=900.0,
        p2p_99_uv=9_000.0,
        median_std_uv=100.0,
        median_p2p_99_uv=800.0,
        calibration=calibration,
    )


def test_spatial_predictability_detector_is_conservative() -> None:
    calibration = DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION
    reference_scores = [0.80, 0.82, 0.79, 0.84, 0.81, 0.83]

    threshold = spatial_predictability_threshold(
        reference_scores,
        calibration=calibration,
        min_reference_count=6,
    )
    assert threshold == calibration.spatial_predictability_max_bad_corr

    scores = {
        **{f"G{index}": score for index, score in enumerate(reference_scores)},
        "FT7": 0.05,
        "P9": 0.30,
    }
    outliers = spatial_predictability_outliers(
        scores,
        excluded_channels=(),
        calibration=calibration,
        min_reference_count=6,
    )

    assert outliers == ("FT7",)


def test_info_text_documents_training_accuracy_tradeoff() -> None:
    assert "CMS/DRL error" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "over 99% specific" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "around 60%" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "99.7%" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT


def test_manual_removed_electrode_helpers_normalize_pid_and_channels() -> None:
    manual_map = normalize_manual_removed_electrodes_map(
        {
            "p1": "ft7, ft8, p9",
            "P13": ["oz", "POZ", "O2", "O2"],
            "P14": "",
        }
    )

    assert manual_map == {
        "p1": ["FT7", "FT8", "P9"],
        "P13": ["Oz", "POz", "O2"],
        "P14": [],
    }
    assert manual_removed_electrodes_for_pid(manual_map, "P1") == (
        "FT7",
        "FT8",
        "P9",
    )
    assert parse_electrode_list("P2; p9\nOZ") == ["P2", "P9", "Oz"]


def test_removed_electrode_detection_mode_normalization() -> None:
    assert normalize_removed_electrode_detection_mode("manual") == "manual"
    assert normalize_removed_electrode_detection_mode("off") == "off"
    assert normalize_removed_electrode_detection_mode("conservative auto") == "auto"
    assert (
        normalize_removed_electrode_detection_mode(
            None,
            auto_detect_removed_electrodes=False,
        )
        == "off"
    )

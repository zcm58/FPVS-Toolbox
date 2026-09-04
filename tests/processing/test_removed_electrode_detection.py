from __future__ import annotations

import json
from pathlib import Path

from Main_App.processing.raw_channel_qc import RawChannelQCConfig
from Main_App.processing.removed_electrode_detection import (
    DEFAULT_REMOVED_ELECTRODE_DETECTION_CALIBRATION,
    REMOVED_ELECTRODE_DETECTION_INFO_TEXT,
    RemovedElectrodeDetectionCalibration,
    build_removed_electrode_review_record,
    manual_removed_electrodes_are_enabled,
    manual_removed_electrodes_for_pid,
    manual_removed_electrodes_for_recording,
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
    assert "greater than 99% specificity" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "60% sensitivity" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "99.7%" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "positive predictive value" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "historical in-lab dataset" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "not independent validation" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT
    assert "reproducible rerun" in REMOVED_ELECTRODE_DETECTION_INFO_TEXT


def test_historical_estimates_have_an_explicit_pending_receipt() -> None:
    root = Path(__file__).resolve().parents[2]
    path = (
        root
        / "docs"
        / "agent"
        / "quality"
        / "removed-electrode-detection-calibration-pending-receipt.json"
    )
    receipt = json.loads(path.read_text(encoding="utf-8"))

    assert receipt["status"] == "pending_current_method_recalibration"
    assert receipt["reported_estimates"]["sensitivity"]["value_approximate"] == 0.6
    assert receipt["reported_estimates"]["positive_predictive_value"]["value_reported"] == 0.997
    assert receipt["reported_estimates"]["sensitivity"]["denominator"] is None
    assert receipt["missing_reproducibility_inputs"]
    assert "not a completed performance receipt" in receipt["interpretation"]


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


def test_manual_removed_electrode_switch_and_recording_override_are_authoritative() -> None:
    settings = {
        "removed_electrode_detection_mode": "auto",
        "manual_removed_electrodes_enabled": True,
        "manual_removed_electrodes": {"P12": ["P9"]},
        "manual_removed_electrodes_by_recording": {
            "P12__follicular": ["Oz"],
            "P12__luteal": [],
        },
    }

    assert manual_removed_electrodes_are_enabled(settings) is True
    assert manual_removed_electrodes_for_recording(
        settings,
        participant_id="p12",
        recording_id="p12__FOLLICULAR",
    ) == ("Oz",)
    assert manual_removed_electrodes_for_recording(
        settings,
        participant_id="P12",
        recording_id="P12__luteal",
    ) == ()
    assert manual_removed_electrodes_for_recording(
        settings,
        participant_id="P12",
        recording_id="P12__unknown",
    ) == ("P9",)

    disabled = {**settings, "manual_removed_electrodes_enabled": False}
    assert manual_removed_electrodes_are_enabled(disabled) is False
    assert manual_removed_electrodes_for_recording(
        disabled,
        participant_id="P12",
        recording_id="P12__follicular",
    ) == ()


def test_legacy_manual_mode_activates_maps_only_when_switch_is_missing() -> None:
    legacy = {
        "removed_electrode_detection_mode": "manual",
        "manual_removed_electrodes": {"P12": ["P9"]},
    }

    assert manual_removed_electrodes_are_enabled(legacy) is True
    assert manual_removed_electrodes_for_recording(
        legacy,
        participant_id="P12",
    ) == ("P9",)
    assert manual_removed_electrodes_are_enabled(
        {**legacy, "manual_removed_electrodes_enabled": False}
    ) is False


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


def test_removed_electrode_review_record_tracks_auto_miss() -> None:
    record = build_removed_electrode_review_record(
        original_auto_flagged=["FT7"],
        accepted_auto_flagged=["FT7"],
        manual_additions=["P9"],
    )

    assert record["original_auto_flagged"] == ["FT7"]
    assert record["accepted_auto_flagged"] == ["FT7"]
    assert record["rejected_auto_flagged"] == []
    assert record["manual_additions"] == ["P9"]
    assert record["final_confirmed_removed"] == ["FT7", "P9"]
    assert record["manual_only_missed_by_auto"] == ["P9"]
    assert record["auto_manual_overlap"] == ["FT7"]
    assert record["agreement_status"] == "partial"


def test_removed_electrode_review_record_tracks_rejected_auto_flag() -> None:
    record = build_removed_electrode_review_record(
        original_auto_flagged=["FT7", "P9"],
        accepted_auto_flagged=["FT7"],
        manual_additions=[],
    )

    assert record["accepted_auto_flagged"] == ["FT7"]
    assert record["rejected_auto_flagged"] == ["P9"]
    assert record["manual_additions"] == []
    assert record["final_confirmed_removed"] == ["FT7"]
    assert record["agreement_status"] == "partial"


def test_removed_electrode_review_record_handles_manual_only_case() -> None:
    record = build_removed_electrode_review_record(
        original_auto_flagged=[],
        accepted_auto_flagged=[],
        manual_additions=["P9"],
    )

    assert record["manual_additions"] == ["P9"]
    assert record["manual_only_missed_by_auto"] == ["P9"]
    assert record["agreement_status"] == "manual_only"

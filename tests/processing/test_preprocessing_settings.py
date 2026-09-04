import pytest

pytest.importorskip("PySide6")

from Main_App.projects.preprocessing_settings import (
    ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
    ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
    ELECTRODE_MONTAGE_BIOSEMI64,
    HARMONIC_SELECTION_PROFILE_VERSION,
    INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY,
    KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY,
    LEGACY_HARMONIC_SELECTION_PROFILE,
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    NEW_PROJECT_HARMONIC_SELECTION_PROFILE,
    PREPROCESSING_CANONICAL_KEYS,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF,
    REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED,
    REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY,
    is_participant_condition_excluded,
    is_recording_condition_excluded,
    new_project_preprocessing_settings,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
    normalize_preprocessing_settings,
)
from Main_App.processing.interpolation_burden import (
    INTERPOLATION_BURDEN_DECISION_EXCLUDE,
    InterpolationBurdenReviewFinding,
    build_interpolation_burden_review_decision,
)


_RETIRED_EPOCH_KEYS = {
    "epoch_start_s",
    "epoch_end_s",
    "epoch_start",
    "epoch_end",
}


def test_defaults_use_expected_bandpass():
    normalized = normalize_preprocessing_settings({})
    assert normalized["high_pass"] == 0.1
    assert normalized["low_pass"] == 50.0
    assert normalized["line_noise_filter_enabled"] is True
    assert normalized["line_noise_frequency_hz"] == 60
    assert normalized["electrode_montage"] == ELECTRODE_MONTAGE_BIOSEMI64
    assert (
        normalized["electrode_mapping_profile"]
        == ELECTRODE_MAPPING_PROFILE_ANATOMICAL
    )
    assert normalized["auto_detect_removed_electrodes"] is False
    assert normalized["removed_electrode_detection_mode"] == "off"
    assert normalized["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
    )
    assert normalized["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING
    )
    assert normalized["manual_removed_electrodes"] == {}
    assert normalized[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False
    assert normalized["manual_removed_electrodes_by_recording"] == {}
    assert normalized["manual_excluded_participants"] == []
    assert normalized["manual_excluded_recordings"] == []
    assert normalized["manual_excluded_participant_conditions"] == {}
    assert normalized["manual_excluded_recording_conditions"] == {}
    assert normalized[INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY] == {}
    assert normalized[KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY] == {}
    assert normalized["harmonic_selection_profile"] == LEGACY_HARMONIC_SELECTION_PROFILE
    assert normalized["harmonic_selection_profile_version"] == HARMONIC_SELECTION_PROFILE_VERSION
    assert _RETIRED_EPOCH_KEYS.isdisjoint(normalized)
    assert _RETIRED_EPOCH_KEYS.isdisjoint(PREPROCESSING_CANONICAL_KEYS)


def test_biosemi64_montage_and_mapping_profile_normalize_to_canonical_ids():
    normalized = normalize_preprocessing_settings(
        {
            "electrode_montage": " BioSemi64 ",
            "electrode_mapping_profile": " BIOSEMI64_1020_AB_V1 ",
        }
    )

    assert normalized["electrode_montage"] == ELECTRODE_MONTAGE_BIOSEMI64
    assert (
        normalized["electrode_mapping_profile"]
        == ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1
    )


@pytest.mark.parametrize("montage", ["standard_1005", "biosemi32", "custom", 64])
def test_unsupported_electrode_montage_is_rejected(montage):
    with pytest.raises(ValueError, match="Unsupported electrode montage|Invalid electrode montage"):
        normalize_preprocessing_settings({"electrode_montage": montage})


@pytest.mark.parametrize(
    "mapping_profile",
    ["a1_b32", "biosemi64_abc", "equiradial", "infer_from_order", 1],
)
def test_unsupported_electrode_mapping_profile_is_rejected(mapping_profile):
    with pytest.raises(
        ValueError,
        match="Unsupported electrode mapping profile|Invalid electrode mapping profile",
    ):
        normalize_preprocessing_settings(
            {"electrode_mapping_profile": mapping_profile}
        )


@pytest.mark.parametrize("channel_limit", [0, -1, 65])
def test_biosemi64_channel_limit_must_be_between_one_and_64(channel_limit):
    with pytest.raises(ValueError, match="between 1 and 64"):
        normalize_preprocessing_settings({"max_chan_idx_keep": channel_limit})


def test_new_projects_explicitly_use_publication_aligned_harmonic_profile():
    settings = new_project_preprocessing_settings()

    assert settings["removed_electrode_detection_mode"] == "off"
    assert settings["auto_detect_removed_electrodes"] is False
    assert settings[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False
    assert settings["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
    )
    assert settings["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF
    )
    assert settings["harmonic_selection_profile"] == NEW_PROJECT_HARMONIC_SELECTION_PROFILE
    assert settings["harmonic_selection_profile_version"] == HARMONIC_SELECTION_PROFILE_VERSION
    assert settings["group_significant_electrode_scope"] == "all_scalp_electrodes"
    assert settings["group_significant_summation_method"] == "two_consecutive_failures"
    assert settings["fixed_harmonic_input_mode"] == "frequency_list"


def test_harmonic_profile_inputs_normalize_to_manifest_safe_values():
    settings = normalize_preprocessing_settings(
        {
            "harmonic_selection_profile": "fixed_preregistered_domain",
            "harmonic_selection_profile_version": "1.0",
            "fixed_harmonic_input_mode": "upper_harmonic_index",
            "fixed_harmonic_upper_harmonic_index": "14",
            "fixed_harmonic_upper_frequency_hz": "16.8",
            "group_significant_selection_electrodes": "O1, Oz, O2",
        }
    )

    assert settings["harmonic_selection_profile"] == "fixed_preregistered_domain"
    assert settings["fixed_harmonic_upper_harmonic_index"] == 14
    assert settings["fixed_harmonic_upper_frequency_hz"] == 16.8
    assert settings["group_significant_selection_electrodes"] == "O1, Oz, O2"


def test_legacy_fixed_policy_name_migrates_to_fixed_profile():
    settings = normalize_preprocessing_settings(
        {"harmonic_selection_policy": "Fixed / predefined harmonic list"}
    )

    assert settings["harmonic_selection_profile"] == "fixed_preregistered_domain"
    assert settings["harmonic_selection_policy"] == (
        "Fixed / predefined harmonic list"
    )


def test_partial_nonlegacy_profile_defaults_to_all_scalp_scope():
    settings = normalize_preprocessing_settings(
        {"harmonic_selection_profile": "significant_only_exploratory"}
    )

    assert settings["group_significant_electrode_scope"] == "all_scalp_electrodes"


def test_retired_epoch_window_inputs_are_not_preprocessing_settings():
    normalized = normalize_preprocessing_settings(
        {
            "epoch_start_s": -0.5,
            "epoch_end_s": 95.0,
            "epoch_start": -0.25,
            "epoch_end": 110.0,
        }
    )

    assert _RETIRED_EPOCH_KEYS.isdisjoint(normalized)


def test_line_noise_settings_normalize_to_typed_values():
    normalized = normalize_preprocessing_settings(
        {
            "line_noise_filter_enabled": "false",
            "line_noise_frequency_hz": "50.0",
        }
    )

    assert normalized["line_noise_filter_enabled"] is False
    assert normalized["line_noise_frequency_hz"] == 50
    assert isinstance(normalized["line_noise_frequency_hz"], int)


@pytest.mark.parametrize("frequency", [0, 49, 50.5, 55, 61, "60 Hz"])
def test_line_noise_frequency_must_be_exactly_50_or_60(frequency):
    with pytest.raises(ValueError, match="exactly 50 or 60 Hz"):
        normalize_preprocessing_settings({"line_noise_frequency_hz": frequency})


def test_inverted_bandpass_raises():
    with pytest.raises(ValueError):
        normalize_preprocessing_settings({"low_pass": 0.1, "high_pass": 50.0})


def test_legacy_bandpass_can_be_interpreted():
    normalized = normalize_preprocessing_settings(
        {"low_pass": 0.1, "high_pass": 50.0},
        allow_legacy_inversion=True,
    )
    assert normalized["high_pass"] == 0.1
    assert normalized["low_pass"] == 50.0


def test_max_parallel_workers_override_aliases():
    normalized = normalize_preprocessing_settings({"max_parallel_workers": "6"})
    assert normalized["max_parallel_workers_override"] == 6
    assert normalized["max_workers"] == 6


def test_negative_max_parallel_workers_override_raises():
    with pytest.raises(ValueError):
        normalize_preprocessing_settings({"max_parallel_workers_override": -1})


def test_auto_detect_removed_electrodes_boolean_aliases():
    normalized = normalize_preprocessing_settings({"detect_removed_electrodes": "false"})
    assert normalized["auto_detect_removed_electrodes"] is False
    assert normalized["removed_electrode_detection_mode"] == "off"
    assert normalized["detect_removed_electrodes"] is False
    assert normalized["auto_mark_removed_electrodes"] is False


def test_legacy_manual_removed_electrodes_mode_becomes_independent_active_list():
    normalized = normalize_preprocessing_settings(
        {
            "auto_detect_removed_electrodes": True,
            "removed_electrode_detection_mode": "manual",
            "manual_removed_electrodes": {
                "p1": "ft7, P9, oz",
                "P2": ["POZ", "O2", "O2"],
            },
        }
    )

    assert normalized["auto_detect_removed_electrodes"] is False
    assert normalized["removed_electrode_detection_mode"] == "off"
    assert normalized[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is True
    assert normalized["manual_removed_electrodes"] == {
        "p1": ["FT7", "P9", "Oz"],
        "P2": ["POz", "O2"],
    }


def test_manual_excluded_participants_normalize_from_list_and_mapping():
    normalized = normalize_preprocessing_settings(
        {
            "manual_excluded_participants": ["P12", "p12", "P3"],
        }
    )
    assert normalized["manual_excluded_participants"] == ["P3", "P12"]

    normalized = normalize_preprocessing_settings(
        {
            "excluded_participants": {"P9": True, "P10": False, "P11": "yes"},
        }
    )
    assert normalized["manual_excluded_participants"] == ["P9", "P11"]


def test_manual_excluded_participant_conditions_normalize_case_insensitively():
    normalized = normalize_manual_excluded_participant_conditions(
        {
            "P12": ["Negative Valence", "faces"],
            "p12": ["Faces", "Neutral Happy"],
            "P3": "Angry Neutral; angry neutral",
        }
    )

    assert normalized == {
        "P3": ["Angry Neutral"],
        "P12": ["faces", "Negative Valence", "Neutral Happy"],
    }
    assert is_participant_condition_excluded(
        normalized,
        "p12",
        "NEGATIVE VALENCE",
    )
    assert not is_participant_condition_excluded(normalized, "P3", "Faces")


def test_manual_excluded_participant_conditions_accept_json_mapping():
    normalized = normalize_preprocessing_settings(
        {
            "participant_condition_exclusions": (
                '{"P4": ["Negative Valence"], "P1": ["Negative Valence"]}'
            )
        }
    )

    assert normalized["manual_excluded_participant_conditions"] == {
        "P1": ["Negative Valence"],
        "P4": ["Negative Valence"],
    }


def test_recording_scoped_qc_settings_normalize_without_changing_participant_scope():
    normalized = normalize_preprocessing_settings(
        {
            "manual_removed_electrodes": {"P01": ["P9"]},
            "manual_removed_electrodes_by_recording": {
                "P01__follicular": ["oz", "O2"],
            },
            "manual_excluded_participants": ["P09"],
            "manual_excluded_recordings": ["P01__luteal", "p01__luteal"],
            "manual_excluded_recording_conditions": {
                "P01__follicular": ["Faces", "faces", "Objects"],
            },
        }
    )

    assert normalized["manual_removed_electrodes"] == {"P01": ["P9"]}
    assert normalized["manual_removed_electrodes_by_recording"] == {
        "P01__follicular": ["Oz", "O2"],
    }
    assert normalized["manual_excluded_participants"] == ["P09"]
    assert normalized["manual_excluded_recordings"] == ["P01__luteal"]
    assert normalized["manual_excluded_recording_conditions"] == {
        "P01__follicular": ["Faces", "Objects"],
    }
    assert is_recording_condition_excluded(
        normalize_manual_excluded_recording_conditions(
            normalized["manual_excluded_recording_conditions"]
        ),
        "p01__FOLLICULAR",
        "faces",
    )


def _interpolation_burden_decision_payload() -> dict[str, object]:
    finding = InterpolationBurdenReviewFinding(
        recording_id="P01__luteal",
        burden_fingerprint="a" * 64,
        successfully_interpolated_channels=("Fp1", "Fp2", "AF7", "AF3"),
        numerator=4,
        denominator=64,
        percentage=6.25,
        message="Review this recording.",
    )
    return build_interpolation_burden_review_decision(
        finding,
        participant_id="P01",
        decision=INTERPOLATION_BURDEN_DECISION_EXCLUDE,
        reason="Four electrodes required interpolation.",
        reviewed_at_utc="2026-09-02T12:00:00Z",
    ).to_payload()


def test_interpolation_burden_review_decision_normalizes_and_preserves_audit():
    decision = _interpolation_burden_decision_payload()

    normalized = normalize_preprocessing_settings(
        {
            INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY: {
                "P01__luteal": decision,
            }
        }
    )

    assert normalized[INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY] == {
        "P01__luteal": decision,
    }


def test_interpolation_burden_review_decision_rejects_stale_fingerprint():
    decision = _interpolation_burden_decision_payload()
    decision["fingerprint"] = "b" * 64

    with pytest.raises(ValueError, match="fingerprint is stale"):
        normalize_preprocessing_settings(
            {
                INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY: {
                    "P01__luteal": decision,
                }
            }
        )


def test_interpolation_burden_review_decision_key_must_match_recording():
    decision = _interpolation_burden_decision_payload()

    with pytest.raises(ValueError, match="key does not match"):
        normalize_preprocessing_settings(
            {
                INTERPOLATION_BURDEN_REVIEW_DECISIONS_KEY: {
                    "P02__luteal": decision,
                }
            }
        )

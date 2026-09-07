from __future__ import annotations

import json

import pytest

from Main_App.projects import (
    EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION,
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED,
    REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED,
    REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY,
    RAW_SPECTRAL_SCREENING_BRIEF_TEXT,
    RAW_SPECTRAL_SCREENING_POLICY_VERSION,
    SUMMED_BCA_SCREENING_POLICY_VERSION,
    SUMMED_BCA_SCREENING_BRIEF_TEXT,
    ExperimentalQcSettings,
    ExperimentalQcSettingsError,
    RemovedElectrodeDetectionConfirmationRequired,
    RawSpectralScreeningSettings,
    SummedBcaScreeningSettings,
    normalize_experimental_qc_settings,
    normalize_preprocessing_settings,
    require_removed_electrode_detection_choice_ready,
)
from Main_App.projects.project import Project


pytestmark = pytest.mark.project_io


def _write_legacy_project(tmp_path, preprocessing=None) -> None:
    tmp_path.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": "Historical",
        "tools": {"processing": {"historical_artifact": "keep"}},
    }
    if preprocessing is not None:
        payload["preprocessing"] = preprocessing
    (tmp_path / "project.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_summed_bca_screening_defaults_are_versioned_and_review_only() -> None:
    settings = ExperimentalQcSettings()
    screening = settings.summed_bca_screening

    assert settings.schema_version == EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION
    assert screening.enabled is True
    assert screening.policy_version == SUMMED_BCA_SCREENING_POLICY_VERSION
    assert (
        screening.warning_summed_bca_uv,
        screening.strong_warning_summed_bca_uv,
        screening.extreme_review_summed_bca_uv,
    ) == (10.0, 50.0, 250.0)
    assert screening.concentrated_review_flagged_cells == 5
    assert screening.broad_extreme_review_unique_electrodes == 11
    assert (
        screening.cohort_warning_robust_score,
        screening.cohort_extreme_robust_score,
    ) == (6.0, 10.0)
    assert (
        screening.cohort_warning_sum_floor_uv,
        screening.cohort_extreme_sum_floor_uv,
    ) == (5.0, 10.0)
    assert (
        screening.cohort_warning_peak_floor_uv,
        screening.cohort_extreme_peak_floor_uv,
    ) == (1.0, 2.0)
    assert SUMMED_BCA_SCREENING_BRIEF_TEXT == (
        "Experimental summed-BCA screening flags unusually large frequency "
        "responses for review. These suggested limits come from FPVS Toolbox "
        "development experience and are not validated for every protocol. This "
        "check does not remove data by itself."
    )


def test_raw_spectral_screening_defaults_are_locked_on_and_review_only() -> None:
    screening = ExperimentalQcSettings().raw_spectral_screening

    assert screening == RawSpectralScreeningSettings()
    assert screening.enabled is True
    assert screening.policy_version == RAW_SPECTRAL_SCREENING_POLICY_VERSION
    assert screening.minimum_frequency_hz == 0.5
    assert screening.minimum_legacy_hann_spectrum_score == 250.0
    assert screening.minimum_local_mean_ratio == 25.0
    assert screening.minimum_local_standardized_score == 12.0
    assert screening.widespread_channel_fraction == 0.75
    assert screening.widespread_min_channels == 48
    assert screening.notch_half_width_hz == 0.5
    assert (
        screening.noise_window_bins,
        screening.noise_candidate_bins,
        screening.noise_retained_bins,
    ) == (12, 22, 20)
    assert RAW_SPECTRAL_SCREENING_BRIEF_TEXT == (
        "Experimental. Flags unusually large narrow-frequency signals in each "
        "analyzed condition for review. Thresholds are provisional, and this "
        "check never removes data automatically."
    )


def test_experimental_qc_settings_normalize_and_round_trip() -> None:
    original = normalize_experimental_qc_settings(
        {
            "schema_version": EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION,
            "summed_bca_screening": {
                "enabled": "false",
                "policy_version": SUMMED_BCA_SCREENING_POLICY_VERSION,
                "warning_summed_bca_uv": "12.5",
                "strong_warning_summed_bca_uv": 60,
                "extreme_review_summed_bca_uv": 300,
                "concentrated_review_flagged_cells": "6",
                "broad_extreme_review_unique_electrodes": 12.0,
                "cohort_warning_robust_score": 7,
                "cohort_extreme_robust_score": 11,
                "cohort_warning_sum_floor_uv": 6,
                "cohort_extreme_sum_floor_uv": 12,
                "cohort_warning_peak_floor_uv": 1.5,
                "cohort_extreme_peak_floor_uv": 3,
            },
            "raw_spectral_screening": {
                **RawSpectralScreeningSettings().to_manifest(),
                "enabled": "false",
            },
        }
    )

    assert original.summed_bca_screening.enabled is False
    assert original.summed_bca_screening.warning_summed_bca_uv == 12.5
    assert original.summed_bca_screening.concentrated_review_flagged_cells == 6
    assert original.raw_spectral_screening.enabled is False
    assert normalize_experimental_qc_settings(original.to_manifest()) == original


def test_experimental_qc_settings_reject_unknown_schema_or_policy_versions() -> None:
    with pytest.raises(ExperimentalQcSettingsError, match="schema version"):
        ExperimentalQcSettings(schema_version="99.0.0")
    with pytest.raises(ExperimentalQcSettingsError, match="policy version"):
        SummedBcaScreeningSettings(policy_version="99.0.0")
    with pytest.raises(ExperimentalQcSettingsError, match="policy version"):
        RawSpectralScreeningSettings(policy_version="99.0.0")


def test_legacy_experimental_qc_manifest_migrates_raw_spectral_screen_on() -> None:
    legacy = normalize_experimental_qc_settings(
        {
            "schema_version": "1.0.0",
            "summed_bca_screening": SummedBcaScreeningSettings().to_manifest(),
        }
    )

    assert legacy.schema_version == EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION
    assert legacy.raw_spectral_screening.enabled is True
    assert legacy.to_manifest()["raw_spectral_screening"] == (
        RawSpectralScreeningSettings().to_manifest()
    )


@pytest.mark.parametrize("version", ["1.0.0", "1.1.0", EXPERIMENTAL_QC_SETTINGS_SCHEMA_VERSION])
def test_condition_specific_interpolation_is_off_for_missing_and_legacy_settings(version):
    settings = normalize_experimental_qc_settings({"schema_version": version})
    assert settings.condition_specific_interpolation_enabled is False
    assert settings.to_manifest()["condition_specific_interpolation_enabled"] is False
    assert ExperimentalQcSettings().condition_specific_interpolation_enabled is False


@pytest.mark.parametrize("invalid", [None, "maybe", 2, [], {}])
def test_invalid_condition_specific_interpolation_setting_is_rejected(invalid):
    with pytest.raises(ExperimentalQcSettingsError, match="condition_specific_interpolation_enabled"):
        ExperimentalQcSettings(condition_specific_interpolation_enabled=invalid)


def test_condition_specific_interpolation_roundtrip_keeps_other_experimental_settings():
    original = ExperimentalQcSettings().with_raw_spectral_screening({"enabled": False})
    enabled = original.with_condition_specific_interpolation_enabled(True)
    assert enabled.condition_specific_interpolation_enabled is True
    assert original.condition_specific_interpolation_enabled is False
    assert enabled.summed_bca_screening == original.summed_bca_screening
    assert enabled.raw_spectral_screening == original.raw_spectral_screening
    assert normalize_experimental_qc_settings(enabled.to_manifest()) == enabled
    assert enabled.with_condition_specific_interpolation_enabled(False) == original


def test_raw_spectral_policy_rejects_unversioned_threshold_edits() -> None:
    payload = RawSpectralScreeningSettings().to_manifest()
    payload["minimum_local_mean_ratio"] = 24.0

    with pytest.raises(ExperimentalQcSettingsError, match="locked value"):
        RawSpectralScreeningSettings.from_manifest(payload)

    payload = RawSpectralScreeningSettings().to_manifest()
    payload["noise_window_bins"] = 12.5

    with pytest.raises(ExperimentalQcSettingsError, match="locked value"):
        RawSpectralScreeningSettings.from_manifest(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("warning_summed_bca_uv", 0),
        ("strong_warning_summed_bca_uv", float("inf")),
        ("extreme_review_summed_bca_uv", float("nan")),
        ("cohort_warning_robust_score", -1),
        ("cohort_extreme_sum_floor_uv", 0),
        ("cohort_warning_peak_floor_uv", True),
        ("concentrated_review_flagged_cells", 0),
        ("concentrated_review_flagged_cells", 5.5),
        ("broad_extreme_review_unique_electrodes", 65),
    ],
)
def test_summed_bca_screening_rejects_nonfinite_nonpositive_or_invalid_counts(
    field: str,
    value: object,
) -> None:
    payload = SummedBcaScreeningSettings().to_manifest()
    payload[field] = value

    with pytest.raises(ExperimentalQcSettingsError):
        SummedBcaScreeningSettings.from_manifest(payload)


@pytest.mark.parametrize(
    "updates",
    [
        {
            "warning_summed_bca_uv": 50,
            "strong_warning_summed_bca_uv": 50,
        },
        {
            "cohort_warning_robust_score": 10,
            "cohort_extreme_robust_score": 10,
        },
        {
            "cohort_warning_sum_floor_uv": 10,
            "cohort_extreme_sum_floor_uv": 5,
        },
        {
            "cohort_warning_peak_floor_uv": 3,
            "cohort_extreme_peak_floor_uv": 2,
        },
    ],
)
def test_summed_bca_screening_rejects_unordered_thresholds(
    updates: dict[str, object],
) -> None:
    payload = SummedBcaScreeningSettings().to_manifest()
    payload.update(updates)

    with pytest.raises(ExperimentalQcSettingsError, match="must|satisfy"):
        SummedBcaScreeningSettings.from_manifest(payload)


def test_existing_project_without_detector_choice_requires_confirmation(
    tmp_path,
) -> None:
    _write_legacy_project(
        tmp_path,
        preprocessing={"manual_removed_electrodes": {"P01": ["P9"]}},
    )

    project = Project.load(tmp_path)

    assert project.preprocessing["removed_electrode_detection_mode"] == "off"
    assert project.preprocessing["auto_detect_removed_electrodes"] is False
    assert project.preprocessing["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
    )
    assert project.preprocessing["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_MISSING
    )
    assert project.preprocessing["manual_removed_electrodes"] == {"P01": ["P9"]}
    assert project.preprocessing[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False
    with pytest.raises(RemovedElectrodeDetectionConfirmationRequired):
        require_removed_electrode_detection_choice_ready(project.preprocessing)

    project.save()
    saved = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert set(REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS).isdisjoint(
        saved["preprocessing"]
    )
    assert saved["preprocessing"]["manual_removed_electrodes"] == {"P01": ["P9"]}
    assert saved["tools"]["processing"]["historical_artifact"] == "keep"


def test_generic_settings_update_cannot_confirm_a_missing_legacy_choice(
    tmp_path,
) -> None:
    _write_legacy_project(tmp_path, preprocessing={"low_pass": 45})
    project = Project.load(tmp_path)

    # This mirrors a form that submits visible values but has no migration
    # metadata. It is an ordinary settings save, not the explicit choice action.
    submitted = {
        key: value
        for key, value in project.preprocessing.items()
        if key not in REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS
    }
    submitted.update(
        {
            "low_pass": 40,
            "removed_electrode_detection_mode": "off",
            "auto_detect_removed_electrodes": False,
        }
    )
    project.update_preprocessing(submitted)
    project.save()

    saved = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert saved["preprocessing"]["low_pass"] == 40.0
    assert set(REMOVED_ELECTRODE_DETECTION_CHOICE_CANONICAL_KEYS).isdisjoint(
        saved["preprocessing"]
    )


@pytest.mark.parametrize(
    ("alias", "value", "expected_mode"),
    [
        ("auto_detect_removed_electrodes", True, "auto"),
        ("detect_removed_electrodes", "false", "off"),
        ("auto_mark_removed_electrodes", 1, "auto"),
    ],
)
def test_legacy_detector_boolean_is_a_ready_saved_choice(
    alias: str,
    value: object,
    expected_mode: str,
) -> None:
    settings = normalize_preprocessing_settings({alias: value})

    assert settings["removed_electrode_detection_mode"] == expected_mode
    assert settings["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
    )
    assert settings["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN
    )
    assert require_removed_electrode_detection_choice_ready(settings) == expected_mode


def test_legacy_manual_mode_becomes_auto_off_with_manual_list_active() -> None:
    settings = normalize_preprocessing_settings(
        {
            "removed_electrode_detection_mode": "manual",
            "auto_detect_removed_electrodes": True,
            "manual_removed_electrodes": {"P02": ["FT7"]},
        }
    )

    assert settings["removed_electrode_detection_mode"] == "off"
    assert settings["auto_detect_removed_electrodes"] is False
    assert settings[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is True
    assert settings["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
    )
    assert settings["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE
    )
    assert settings["manual_removed_electrodes"] == {"P02": ["FT7"]}


@pytest.mark.parametrize("mode", ["auto", "off"])
def test_stored_manual_list_stays_dormant_without_explicit_activation(mode: str) -> None:
    settings = normalize_preprocessing_settings(
        {
            "removed_electrode_detection_mode": mode,
            "manual_removed_electrodes": {"P02": ["FT7"]},
        }
    )

    assert settings["removed_electrode_detection_mode"] == mode
    assert settings[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False
    assert settings["manual_removed_electrodes"] == {"P02": ["FT7"]}


def test_automatic_detector_and_manual_list_can_be_active_together() -> None:
    settings = normalize_preprocessing_settings(
        {
            "removed_electrode_detection_mode": "auto",
            MANUAL_REMOVED_ELECTRODES_ENABLED_KEY: True,
            "manual_removed_electrodes": {"P02": ["FT7"]},
        }
    )

    assert settings["removed_electrode_detection_mode"] == "auto"
    assert settings["auto_detect_removed_electrodes"] is True
    assert settings[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is True


def test_invalid_legacy_detector_value_is_safe_and_preserves_manual_maps() -> None:
    settings = normalize_preprocessing_settings(
        {
            "removed_electrode_detection_mode": "unknown-mode",
            "manual_removed_electrodes": {"P03": ["Oz"]},
        }
    )

    assert settings["removed_electrode_detection_mode"] == "off"
    assert settings["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED
    )
    assert settings["manual_removed_electrodes"] == {"P03": ["Oz"]}
    assert settings[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False


@pytest.mark.parametrize(
    (
        "detector_payload",
        "expected_mode",
        "expected_status",
        "expected_source",
    ),
    [
        (
            {
                "removed_electrode_detection_mode": "auto",
                "removed_electrode_detection_choice_status": "ready",
            },
            "auto",
            REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_SAVED_MODE,
        ),
        (
            {
                "auto_detect_removed_electrodes": "false",
                "removed_electrode_detection_choice_schema_version": "broken",
                "removed_electrode_detection_choice_status": "broken",
                "removed_electrode_detection_choice_source": "broken",
            },
            "off",
            REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_LEGACY_BOOLEAN,
        ),
        (
            {
                "removed_electrode_detection_mode": "unknown",
                "auto_detect_removed_electrodes": "unknown",
                "removed_electrode_detection_choice_schema_version": "broken",
                "removed_electrode_detection_choice_status": "ready",
                "removed_electrode_detection_choice_source": "broken",
            },
            "off",
            REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE,
        ),
        (
            {
                "removed_electrode_detection_mode": "auto",
                "removed_electrode_detection_choice_schema_version": "broken",
                "removed_electrode_detection_choice_status": "confirmation_required",
                "removed_electrode_detection_choice_source": "user_confirmed",
            },
            "off",
            REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_CONFIRMATION_REQUIRED,
            REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_INVALID_SAVED_VALUE,
        ),
    ],
)
def test_corrupt_detector_metadata_recovers_without_losing_other_settings(
    tmp_path,
    detector_payload: dict[str, object],
    expected_mode: str,
    expected_status: str,
    expected_source: str,
) -> None:
    _write_legacy_project(
        tmp_path,
        preprocessing={
            "low_pass": 42,
            "manual_removed_electrodes": {"P03": ["Oz"]},
            **detector_payload,
        },
    )

    project = Project.load(tmp_path)

    assert project.preprocessing["low_pass"] == 42.0
    assert project.preprocessing["manual_removed_electrodes"] == {"P03": ["Oz"]}
    assert project.preprocessing["removed_electrode_detection_mode"] == expected_mode
    assert (
        project.preprocessing["removed_electrode_detection_choice_status"]
        == expected_status
    )
    assert (
        project.preprocessing["removed_electrode_detection_choice_source"]
        == expected_source
    )

    project.save()
    reloaded = Project.load(tmp_path)
    assert reloaded.preprocessing["low_pass"] == 42.0
    assert reloaded.preprocessing["manual_removed_electrodes"] == {"P03": ["Oz"]}
    assert reloaded.preprocessing["removed_electrode_detection_mode"] == expected_mode
    assert (
        reloaded.preprocessing["removed_electrode_detection_choice_status"]
        == expected_status
    )
    assert (
        reloaded.preprocessing["removed_electrode_detection_choice_source"]
        == expected_source
    )


def test_new_project_has_explicit_off_choice_and_qc17_defaults(tmp_path) -> None:
    project_root = tmp_path / "New Project"

    project = Project.load(project_root)
    project.save()

    saved = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    assert saved["preprocessing"]["removed_electrode_detection_mode"] == "off"
    assert saved["preprocessing"]["auto_detect_removed_electrodes"] is False
    assert saved["preprocessing"][MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False
    assert saved["preprocessing"]["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
    )
    assert saved["preprocessing"]["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_NEW_PROJECT_DEFAULT_OFF
    )
    assert saved["experimental_qc"] == ExperimentalQcSettings().to_manifest()


def test_confirming_legacy_detector_choice_preserves_manual_maps(tmp_path) -> None:
    _write_legacy_project(
        tmp_path,
        preprocessing={"manual_removed_electrodes": {"P01": ["P9"]}},
    )
    project = Project.load(tmp_path)

    project.confirm_removed_electrode_detection_choice("auto")
    project.save()

    reloaded = Project.load(tmp_path)
    assert reloaded.preprocessing["removed_electrode_detection_mode"] == "auto"
    assert reloaded.preprocessing["removed_electrode_detection_choice_status"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_STATUS_READY
    )
    assert reloaded.preprocessing["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_USER_CONFIRMED
    )
    assert reloaded.preprocessing["manual_removed_electrodes"] == {"P01": ["P9"]}
    assert reloaded.preprocessing[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is False


def test_existing_project_defaults_qc17_on_and_custom_settings_round_trip(
    tmp_path,
) -> None:
    _write_legacy_project(tmp_path, preprocessing={"auto_detect_removed_electrodes": False})
    project = Project.load(tmp_path)
    assert project.experimental_qc_settings == ExperimentalQcSettings()

    custom_screening = SummedBcaScreeningSettings(
        enabled=False,
        warning_summed_bca_uv=12,
        strong_warning_summed_bca_uv=60,
        extreme_review_summed_bca_uv=300,
        concentrated_review_flagged_cells=6,
        broad_extreme_review_unique_electrodes=12,
        cohort_warning_robust_score=7,
        cohort_extreme_robust_score=11,
        cohort_warning_sum_floor_uv=6,
        cohort_extreme_sum_floor_uv=12,
        cohort_warning_peak_floor_uv=1.5,
        cohort_extreme_peak_floor_uv=3,
    )
    expected = project.experimental_qc_settings.with_summed_bca_screening(
        custom_screening
    ).with_condition_specific_interpolation_enabled(True)
    project.update_experimental_qc_settings(expected)
    project.save()

    saved = json.loads((tmp_path / "project.json").read_text(encoding="utf-8"))
    assert saved["experimental_qc"] == expected.to_manifest()
    assert Project.load(tmp_path).experimental_qc_settings == expected

import pytest

pytest.importorskip("PySide6")

from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings


def test_defaults_use_expected_bandpass():
    normalized = normalize_preprocessing_settings({})
    assert normalized["high_pass"] == 0.1
    assert normalized["low_pass"] == 50.0
    assert normalized["auto_detect_removed_electrodes"] is True
    assert normalized["removed_electrode_detection_mode"] == "auto"
    assert normalized["manual_removed_electrodes"] == {}
    assert normalized["manual_excluded_participants"] == []


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


def test_manual_removed_electrodes_mode_supersedes_auto_boolean():
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
    assert normalized["removed_electrode_detection_mode"] == "manual"
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

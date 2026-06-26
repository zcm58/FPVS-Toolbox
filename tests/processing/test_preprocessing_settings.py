import pytest

pytest.importorskip("PySide6")

from Main_App.projects.preprocessing_settings import normalize_preprocessing_settings


def test_defaults_use_expected_bandpass():
    normalized = normalize_preprocessing_settings({})
    assert normalized["high_pass"] == 0.1
    assert normalized["low_pass"] == 50.0
    assert normalized["auto_detect_removed_electrodes"] is True


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
    assert normalized["detect_removed_electrodes"] is False
    assert normalized["auto_mark_removed_electrodes"] is False

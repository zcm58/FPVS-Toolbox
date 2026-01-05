import pytest

pytest.importorskip("PySide6")

from Main_App.PySide6_App.Backend.preprocessing_settings import normalize_preprocessing_settings


def test_defaults_use_expected_bandpass():
    normalized = normalize_preprocessing_settings({})
    assert normalized["high_pass"] == 0.1
    assert normalized["low_pass"] == 50.0


def test_inverted_bandpass_raises():
    with pytest.raises(ValueError):
        normalize_preprocessing_settings({"low_pass": 0.1, "high_pass": 50.0})

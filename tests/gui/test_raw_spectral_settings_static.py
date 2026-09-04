from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_experimental_settings_exposes_project_raw_spectral_switch_and_help() -> None:
    source = _source("src/Main_App/gui/settings_panel.py")

    assert "Experimental Raw-Spectral Review" in source
    assert "settings_raw_spectral_screening_enabled" in source
    assert "RAW_SPECTRAL_SCREENING_BRIEF_TEXT" in source
    assert "compared with nearby FFT bins" in source
    assert "expected FPVS" in source
    assert "configured line-noise filter" in source
    assert "or unexpected" in source


def test_raw_spectral_advanced_values_are_locked_display_text() -> None:
    source = _source("src/Main_App/gui/settings_panel.py")

    assert "settings_raw_spectral_advanced_toggle" in source
    assert "settings_raw_spectral_advanced_values" in source
    assert "Legacy Hann-spectrum score" in source
    assert "Local standardized score" in source
    assert "Widespread label" in source
    assert "Noise neighborhood" in source
    assert "Notch match" in source
    assert "raw_spectral_advanced_value_labels: dict[str, QLabel]" in source


def test_processing_inputs_passes_project_owned_raw_spectral_record() -> None:
    source = _source("src/Main_App/gui/processing_inputs.py")

    assert "experimental_qc_settings.raw_spectral_screening" in source
    assert '"raw_spectral_screening": raw_spectral_screening.to_manifest()' in source


def test_settings_do_not_suggest_the_legacy_16_point_8_hz_limit() -> None:
    source = _source("src/Main_App/gui/settings_panel.py")

    assert 'setPlaceholderText("16.8")' not in source
    assert "Optional within project range" in source


def test_review_surface_names_scores_without_physical_uv_claim() -> None:
    source = _source("src/Main_App/gui/preprocessing_qc_workflow.py")

    assert "Legacy Hann-spectrum score" in source
    assert "local mean ratio" in source
    assert "local standardized score" in source
    assert 'f"{frequency:.3f} Hz / bin {fft_bin}' in source
    assert "widespread {widespread}" in source
    assert "threshold_policy_version" in source
    assert "required noise collision(s)" in source
    assert "target_below_experimental_screen_boundary" in source
    assert "was not evaluated" in source
    assert '"Experimental raw-spectral review: Not performed (disabled in "' in source
    assert '"project settings). No prior spectral flag is treated as current."' in source
    assert '"Experimental raw-spectral review: Not evaluated. "' in source
    assert "standard frequency metric is unavailable" in source
    assert "it has no current exclusion" in source

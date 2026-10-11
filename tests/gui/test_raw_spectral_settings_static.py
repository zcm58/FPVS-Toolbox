from __future__ import annotations

from pathlib import Path
import ast
from itertools import product
from types import SimpleNamespace

import pytest

from Main_App.projects import ExperimentalQcSettings, ExperimentalQcSettingsError, SummedBcaScreeningSettings


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


class _Check:
    def __init__(self, checked):
        self.checked = checked
        self.enabled = True

    def isChecked(self):
        return self.checked

    def setEnabled(self, enabled):
        self.enabled = enabled


class _Edit(_Check):
    def text(self):
        return str(self.checked)

    def setText(self, text):
        self.checked = text


def _experimental_panel(switches, *, has_project=True):
    tree = ast.parse(_source("src/Main_App/gui/settings_panel.py"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                 and node.name == "SettingsDialog")
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef)
               and node.name in {"_experimental_qc_settings_from_editor",
                                 "_refresh_experimental_qc_dependencies",
                                 "_experimental_qc_changes_after_processing"}]
    namespace = {"ExperimentalQcSettings": ExperimentalQcSettings,
                 "SummedBcaScreeningSettings": SummedBcaScreeningSettings}
    exec(compile(ast.Module(body=methods, type_ignores=[]), "settings-methods", "exec"), namespace)
    settings = ExperimentalQcSettings().with_condition_specific_interpolation_enabled(True)
    fields = (
        "raw_signal_screening_enabled", "kurtosis_screening_enabled",
        "interpolation_burden_review_enabled", "snr_spectral_screening_enabled",
        "stats_dv_screening_enabled", "raw_spectral_screening_enabled",
        "summed_bca_screening_enabled",
    )
    panel = SimpleNamespace(
        project=SimpleNamespace(experimental_qc_settings=settings) if has_project else None,
        _project_has_processed_outputs=lambda: True,
        condition_specific_interpolation_enabled_check=_Check(True),
        kurtosis_auto_interpolate_all_check=_Check(True),
        kurtosis_review_auto_interpolate_extreme_check=_Check(True),
        summed_bca_threshold_edits={
            key: _Edit(value)
            for key, value in settings.summed_bca_screening.to_manifest().items()
            if key not in {"enabled", "policy_version"}
        },
        **{f"{name}_check": _Check(value) for name, value in zip(fields, switches, strict=True)},
    )
    for method in methods:
        setattr(panel, method.name, namespace[method.name].__get__(panel))
    return panel, fields


@pytest.mark.parametrize("switches", product((False, True), repeat=7))
def test_settings_editor_saves_all_qc_combinations_and_only_gates_dependent_controls(switches):
    panel, fields = _experimental_panel(switches)
    panel._refresh_experimental_qc_dependencies()
    settings = panel._experimental_qc_settings_from_editor()

    assert tuple(getattr(settings, field) for field in fields[:5]) == switches[:5]
    assert settings.raw_spectral_screening.enabled is switches[5]
    assert settings.summed_bca_screening.enabled is switches[6]
    assert panel.kurtosis_auto_interpolate_all_check.enabled is switches[1]
    assert panel.kurtosis_review_auto_interpolate_extreme_check.enabled is switches[1]
    assert panel.condition_specific_interpolation_enabled_check.enabled is switches[6]
    assert settings.condition_specific_interpolation_enabled is True
    assert settings.kurtosis_review_auto_interpolate_extreme is True
    assert all(edit.enabled for edit in panel.summed_bca_threshold_edits.values())


def test_settings_dependency_controls_are_inactive_without_a_project():
    panel, _ = _experimental_panel((True,) * 7, has_project=False)
    panel._refresh_experimental_qc_dependencies()
    assert not panel.kurtosis_auto_interpolate_all_check.enabled
    assert not panel.kurtosis_review_auto_interpolate_extreme_check.enabled
    assert not panel.condition_specific_interpolation_enabled_check.enabled
    assert not any(edit.enabled for edit in panel.summed_bca_threshold_edits.values())


def test_disabled_summed_bca_screen_keeps_invalid_draft_editable_until_corrected():
    panel, _ = _experimental_panel((False,) * 7)
    edit = panel.summed_bca_threshold_edits["warning_summed_bca_uv"]
    edit.setText("invalid")
    panel._refresh_experimental_qc_dependencies()
    assert edit.enabled
    with pytest.raises(ExperimentalQcSettingsError, match="warning_summed_bca_uv"):
        panel._experimental_qc_settings_from_editor()
    edit.setText("12")
    saved = panel._experimental_qc_settings_from_editor()
    assert saved.summed_bca_screening.enabled is False
    assert saved.summed_bca_screening.warning_summed_bca_uv == 12


@pytest.mark.parametrize("disabled, expected", [
    (0, (True, False)), (1, (True, False)), (2, (False, True)),
    (3, (False, False)), (4, (False, False)), (5, (True, False)), (6, (False, True)),
])
def test_qc_settings_route_preprocessing_and_postprocessing_refresh_separately(disabled, expected):
    switches = [True] * 7
    switches[disabled] = False
    panel, _ = _experimental_panel(switches)
    settings = panel._experimental_qc_settings_from_editor()
    assert panel._experimental_qc_changes_after_processing(settings) == expected
    panel._project_has_processed_outputs = lambda: False
    assert panel._experimental_qc_changes_after_processing(settings) == (False, False)

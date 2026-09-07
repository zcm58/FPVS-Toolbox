"""Exercise ROI settings routing without importing or running Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest


SOURCE = (
    Path(__file__).resolve().parents[2] / "src/Main_App/gui/settings_panel.py"
)


def _method(name):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog"
    )
    method = next(node for node in owner.body if getattr(node, "name", None) == name)
    module = ast.Module(
        body=[ast.ImportFrom(
            module="__future__", names=[ast.alias(name="annotations")], level=0,
        ), method],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace[name]


def _panel():
    pairs = [("ROT", ["O2", "PO8"]), ("Test ROI", ["F8", "T8"])]
    panel = SimpleNamespace(
        project=object(),
        roi_editor=SimpleNamespace(get_pairs=Mock(return_value=pairs)),
        _project_protocol_signature=Mock(return_value=(6.0, 1.2, 144, 55)),
        _project_has_processed_outputs=Mock(return_value=True),
    )
    for name in (
        "_roi_settings_signature", "_frequency_analysis_settings_signature",
        "_frequency_analysis_settings_changed_after_processing",
        "_project_protocol_changed_after_processing",
    ):
        setattr(panel, name, _method(name).__get__(panel))
    panel._initial_frequency_analysis_signature = (
        panel._frequency_analysis_settings_signature()
    )
    return panel


@pytest.mark.parametrize("pairs", [
    [("ROT", ["O2", "PO8"])],  # deletion
    [("ROT", ["O2", "PO8"]), ("Renamed", ["F8", "T8"])],
    [("ROT", ["O2", "PO8"]), ("Test ROI", ["F8", "FT8"])],
    [("ROT", ["O2", "PO8"]), ("Test ROI", ["F8", "T8"]), ("New", ["O1"])],
])
def test_roi_edits_require_frequency_qc_but_not_raw_reprocessing(pairs):
    panel = _panel()
    assert not panel._frequency_analysis_settings_changed_after_processing()
    panel.roi_editor.get_pairs.return_value = pairs
    assert panel._frequency_analysis_settings_changed_after_processing()
    assert not panel._project_protocol_changed_after_processing()


def test_equivalent_roi_text_does_not_invalidate_and_protocol_change_still_does():
    panel = _panel()
    panel.roi_editor.get_pairs.return_value = [
        (" ROT ", ["o2", " po8 "]), ("Test ROI", ["f8", "t8"]),
    ]
    assert not panel._frequency_analysis_settings_changed_after_processing()
    panel._project_protocol_signature.return_value = (3.0, 0.3, 144, 55)
    assert panel._frequency_analysis_settings_changed_after_processing()
    assert panel._project_protocol_changed_after_processing()


def test_recalculate_after_roi_removal_resumes_qc_and_commits_saved_roi_edit():
    panel = _panel()
    panel.roi_editor.get_pairs.return_value = [("ROT", ["O2", "PO8"])]
    for name in (
        "_capture_harmonic_settings_rollback", "_clear_harmonic_settings_rollback",
        "_mark_frequency_analysis_outputs_stale", "_restore_harmonic_settings_after_cancel",
        "_resume_frequency_domain_post_processing", "_start_full_fft_grid_review",
    ):
        setattr(panel, name, Mock())
    panel._validated_preproc_payload = Mock(return_value={})
    panel._save_project_preprocessing_for_harmonic_recalculation = Mock(return_value=True)
    panel._save_analysis_inputs_for_harmonic_recalculation = Mock(return_value=True)

    _method("_on_recalculate_harmonics_clicked")(panel)

    panel._mark_frequency_analysis_outputs_stale.assert_called_once()
    panel._clear_harmonic_settings_rollback.assert_called_once()
    panel._resume_frequency_domain_post_processing.assert_called_once()
    panel._start_full_fft_grid_review.assert_not_called()
    panel._restore_harmonic_settings_after_cancel.assert_not_called()


def test_unchanged_rois_keep_the_harmonic_only_recalculation_path():
    panel = _panel()
    for name in (
        "_capture_harmonic_settings_rollback", "_clear_harmonic_settings_rollback",
        "_mark_frequency_analysis_outputs_stale", "_restore_harmonic_settings_after_cancel",
        "_resume_frequency_domain_post_processing",
    ):
        setattr(panel, name, Mock())
    panel._validated_preproc_payload = Mock(return_value={})
    panel._save_project_preprocessing_for_harmonic_recalculation = Mock(return_value=True)
    panel._save_analysis_inputs_for_harmonic_recalculation = Mock(return_value=True)
    panel._start_full_fft_grid_review = Mock(return_value=True)

    _method("_on_recalculate_harmonics_clicked")(panel)

    panel._start_full_fft_grid_review.assert_called_once_with(recalculate_after=True)
    panel._resume_frequency_domain_post_processing.assert_not_called()
    panel._mark_frequency_analysis_outputs_stale.assert_not_called()

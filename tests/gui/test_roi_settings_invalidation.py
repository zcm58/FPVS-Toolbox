"""Exercise ROI settings routing without importing or running Qt."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Main_App.Shared.roi_presets import ROI_MONTAGE_BIOSEMI64, default_roi_presets
from Main_App.Shared.settings_manager import SettingsManager
from Main_App.gui.roi_electrode_selector_state import BIOSEMI64_LABELS
from Main_App.gui.roi_visual_editor_state import ROIEditorCollection
from Tools.Stats.analysis.dv_policy_settings import normalize_dv_policy


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
    namespace = {"normalize_dv_policy": normalize_dv_policy}
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    return namespace[name]


DEFAULT_ROIS = [
    (preset.name, list(preset.electrodes))
    for preset in default_roi_presets(ROI_MONTAGE_BIOSEMI64)
]


def _visual_panel(tmp_path, saved_pairs):
    """Use actual persisted pairs, visual draft state, and constructor baselines."""

    settings_path = tmp_path / "settings.ini"
    manager = SettingsManager(str(settings_path))
    manager.set_roi_pairs(saved_pairs)
    manager.save()
    collection = ROIEditorCollection(BIOSEMI64_LABELS)
    collection.reset(manager.get_roi_pairs(), default_pairs=DEFAULT_ROIS)
    preprocessing = {
        "harmonic_selection_profile": "dzhelyova_poncet_two_consecutive_failures",
        "harmonic_selection_profile_version": "1.0",
        "group_significant_electrode_scope": "all_scalp_electrodes",
    }
    panel = SimpleNamespace(
        project=object(),
        manager=manager,
        roi_editor=collection,
        _project_preprocessing=Mock(return_value=preprocessing),
        _harmonic_policy_payload_from_preprocessing=lambda payload: payload,
        _project_protocol_signature=Mock(return_value=(6.0, 1.2, 144, 55)),
        _project_has_processed_outputs=Mock(return_value=True),
    )
    for name in (
        "_roi_settings_signature", "_harmonic_settings_signature_from_settings",
        "_harmonic_settings_signature_from_preprocessing",
        "_harmonic_settings_changed_after_processing",
        "_frequency_analysis_settings_signature",
        "_frequency_analysis_settings_changed_after_processing",
        "_project_protocol_changed_after_processing",
    ):
        setattr(panel, name, _method(name).__get__(panel))

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SettingsDialog"
    )
    build_ui = next(node for node in owner.body if getattr(node, "name", None) == "_build_ui")
    baseline_names = {
        "_initial_harmonic_settings_signature", "_initial_frequency_analysis_signature",
    }
    assignments = [
        node for node in build_ui.body
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Attribute) and target.attr in baseline_names
            for target in node.targets
        )
    ]
    assert len(assignments) == len(baseline_names)
    # Execute the production UI initialization assignments, so forgetting the raw
    # saved-pair override in either call cannot pass via a test-only baseline.
    module = ast.Module(body=assignments, type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), {"self": panel})
    return panel


@pytest.mark.parametrize("saved_pairs, changed", [
    (DEFAULT_ROIS, False),
    ([("Custom only", ["O1"])], True),
    ([("ROT", ["O2", "PO8"])], True),
    ([], True),
], ids=["complete-defaults", "custom-only", "missing-built-ins", "empty-saved-list"])
def test_visual_draft_injection_uses_raw_saved_constructor_baselines(
    tmp_path, saved_pairs, changed,
):
    panel = _visual_panel(tmp_path, saved_pairs)
    preprocessing = panel._project_preprocessing()
    raw_signature = panel._roi_settings_signature(saved_pairs)

    assert panel._initial_harmonic_settings_signature[-1] == raw_signature
    assert panel._initial_frequency_analysis_signature[1] == raw_signature
    assert panel._harmonic_settings_changed_after_processing(preprocessing) is changed
    assert panel._frequency_analysis_settings_changed_after_processing() is changed
    assert not panel._project_protocol_changed_after_processing()
    assert {"LOT", "ROT", "Central"} <= {
        name for name, _electrodes in panel.roi_editor.get_pairs()
    }
    assert panel.manager.get_roi_pairs() == saved_pairs
    assert SettingsManager(panel.manager.ini_path).get_roi_pairs() == saved_pairs


def test_empty_roi_override_is_distinct_from_the_current_visual_draft(tmp_path):
    panel = _visual_panel(tmp_path, [])
    preprocessing = panel._project_preprocessing()

    assert panel._roi_settings_signature([]) == ()
    assert panel._roi_settings_signature() == panel._roi_settings_signature(DEFAULT_ROIS)
    assert panel._harmonic_settings_signature_from_preprocessing(
        preprocessing, roi_pairs_override=[],
    ) != panel._harmonic_settings_signature_from_preprocessing(preprocessing)
    assert panel._frequency_analysis_settings_signature(
        roi_pairs_override=[],
    ) != panel._frequency_analysis_settings_signature()


@pytest.mark.parametrize("saved_pairs, requires_frequency_qc", [
    (DEFAULT_ROIS, False),
    ([("Custom only", ["O1"])], True),
    ([], True),
], ids=["complete-defaults", "custom-only", "empty-saved-list"])
def test_injected_visual_defaults_route_to_frequency_qc_before_harmonics(
    tmp_path, saved_pairs, requires_frequency_qc,
):
    panel = _visual_panel(tmp_path, saved_pairs)
    for name in (
        "_capture_harmonic_settings_rollback", "_clear_harmonic_settings_rollback",
        "_mark_frequency_analysis_outputs_stale", "_restore_harmonic_settings_after_cancel",
        "_resume_frequency_domain_post_processing",
    ):
        setattr(panel, name, Mock())
    panel._validated_preproc_payload = panel._project_preprocessing
    panel._save_project_preprocessing_for_harmonic_recalculation = Mock(return_value=True)
    panel._save_analysis_inputs_for_harmonic_recalculation = Mock(return_value=True)
    panel._start_full_fft_grid_review = Mock(return_value=True)

    _method("_on_recalculate_harmonics_clicked")(panel)

    if requires_frequency_qc:
        panel._mark_frequency_analysis_outputs_stale.assert_called_once()
        panel._resume_frequency_domain_post_processing.assert_called_once()
        panel._start_full_fft_grid_review.assert_not_called()
    else:
        panel._mark_frequency_analysis_outputs_stale.assert_not_called()
        panel._resume_frequency_domain_post_processing.assert_not_called()
        panel._start_full_fft_grid_review.assert_called_once_with(recalculate_after=True)
    panel._restore_harmonic_settings_after_cancel.assert_not_called()


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

"""Execute FHC loading/recovery state transitions without constructing Qt."""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Tools.Free_Harmonic_Clustering.gui.models import (
    GuiAnalysisDesign,
    GuiHarmonicMode,
    ProjectFrequencySnapshot,
)


SOURCE = Path(__file__).resolve().parents[2] / "src/Tools/Free_Harmonic_Clustering/gui/page.py"


class _Widget:
    def __init__(self, text=""):
        self.value = text
        self.visible = True
        self.enabled = True
        self.variant = ""

    def setText(self, value):
        self.value = str(value)

    set_text = setText
    setToolTip = setText

    def set_variant(self, value):
        self.variant = value

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def setVisible(self, value):
        self.visible = bool(value)

    def setEnabled(self, value):
        self.enabled = bool(value)

    def clear(self):
        self.value = ""

    def count(self):
        return 0


METHODS = {
    "_set_unavailable_plan", "_show_frequency_or_ready_status", "_show_error",
    "_begin_project_inspection", "refresh_project_context", "_apply_new_context",
    "_on_operation_failed", "_on_operation_cancelled", "_on_post_processing_required",
    "_update_buttons", "_clear_choice_controls",
}


def _page(tmp_path, *, snapshot=None, reason="Protocol metadata is missing base_freq."):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FreeHarmonicClusteringPage")
    methods = [node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name in METHODS]
    assert {node.name for node in methods} == METHODS
    for node in methods:
        node.decorator_list = []
    namespace = {
        "Path": Path, "logger": logging.getLogger(__name__),
        "_FREQUENCY_UNSET": object(), "ProjectFrequencySnapshot": ProjectFrequencySnapshot,
        "GuiHarmonicMode": GuiHarmonicMode, "GuiAnalysisDesign": GuiAnalysisDesign,
        "ProjectInspectionWorker": Mock(return_value=object()),
    }
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *methods], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(SOURCE), "exec"), namespace)
    page = SimpleNamespace(
        _project_root=tmp_path.resolve(), _frequency_snapshot=snapshot, _frequency_error=reason,
        _thread=None, _retired=False, _inspection_failed=False, _options=None,
        _active_stage="inspection", _updating_controls=False, _backend=object(),
        _pending_context=None, _pending_post_processing_reason=None,
        _analysis_plan_state_error="", _recording_exclusion_state_error="", _recording_exclusions=(),
        _clear_results=Mock(), _update_results_folder_button=Mock(),
        _start_operation=Mock(), _on_inspection_completed=Mock(), cancel_active_work=Mock(),
        _selected_harmonic_mode=lambda: GuiHarmonicMode.AUTOMATIC,
        _setup_error=lambda: "Project inputs are not available.",
        post_processing_required=SimpleNamespace(emit=Mock()),
        protocol_settings_required=SimpleNamespace(emit=Mock()),
    )
    for name in (
        "plan_context_label", "plan_summary_label", "condition_plan_row", "reference_condition_combo",
        "review_comparisons_button", "review_exclusions_button", "plan_exclusion_row", "exclusion_count_label", "family_correction_note",
        "workflow_status", "protocol_settings_button", "retry_loading_button", "run_analysis_button",
        "cancel_button", "workflow_actions", "design_combo", "harmonic_mode_combo", "design_stack",
        "plan_card", "fixed_highest_combo", "progress_bar", "paired_condition_a_combo",
        "paired_condition_b_combo", "paired_group_filter_combo", "independent_condition_combo",
        "independent_group_a_combo", "independent_group_b_combo",
    ):
        setattr(page, name, _Widget())
    page.family_checks = {name: _Widget() for name in ("between_groups", "between_conditions", "within_group_visits", "group_visit_change")}
    page.plan_context_label.value = "Loading project design..."
    page.plan_summary_label.value = "16 old comparisons"
    for method in methods:
        setattr(page, method.name, namespace[method.name].__get__(page))
    return page, namespace["ProjectInspectionWorker"]


def test_missing_protocol_has_a_reason_and_recovery_action_without_a_loading_worker(tmp_path):
    reason = "Protocol metadata is missing base_freq."
    page, worker = _page(tmp_path, reason=reason)
    page._begin_project_inspection()
    worker.assert_not_called()
    page._start_operation.assert_not_called()
    assert not page.plan_context_label.value.casefold().startswith("loading")
    assert reason in page.workflow_status.value
    assert page.plan_summary_label.value == ""
    assert not any(widget.visible for widget in page.family_checks.values())
    assert not page.condition_plan_row.visible
    assert not page.review_comparisons_button.visible
    assert page.protocol_settings_button.visible and page.protocol_settings_button.enabled
    assert not page.run_analysis_button.enabled
    assert not page.retry_loading_button.visible


def test_correcting_frequencies_in_same_project_starts_inspection(tmp_path):
    page, worker = _page(tmp_path)
    snapshot = ProjectFrequencySnapshot(1.2, 6.0)
    assert page.refresh_project_context(frequency_snapshot=snapshot)
    assert page._frequency_snapshot == snapshot
    assert not page._frequency_error
    worker.assert_called_once()
    assert page._start_operation.call_args.kwargs["stage"] == "inspection"
    page._clear_results.assert_called_once()


def test_updated_protocol_error_is_not_replaced_by_old_project_reason(tmp_path):
    page, worker = _page(tmp_path, reason="Old metadata problem.")
    reason = "The protocol was saved with an invalid oddball frequency."
    assert page.refresh_project_context(frequency_snapshot=None, frequency_error=reason)
    assert page._frequency_error == reason
    assert reason in page.workflow_status.value
    worker.assert_not_called()
    assert page.protocol_settings_button.visible


def test_invalid_frequency_values_stop_inspection_instead_of_guessing_defaults(tmp_path):
    page, worker = _page(tmp_path, snapshot=ProjectFrequencySnapshot(1.2, 6.0), reason=None)
    assert page.refresh_project_context(frequency_snapshot={"oddball_frequency_hz": 0, "base_frequency_hz": 6.0})
    assert page._frequency_snapshot is None
    assert "positive" in page.workflow_status.value.casefold()
    assert page.protocol_settings_button.visible
    assert not any(widget.visible for widget in page.family_checks.values())
    worker.assert_not_called()


@pytest.mark.parametrize("failure", ["failed", "cancelled"])
def test_interrupted_inspection_replaces_loading_state_and_offers_retry(tmp_path, failure):
    page, worker = _page(tmp_path, snapshot=ProjectFrequencySnapshot(1.2, 6.0), reason=None)
    if failure == "failed":
        page._on_operation_failed("The input workbook could not be read.")
        assert "workbook" in page.workflow_status.value
    else:
        page._on_operation_cancelled()
        assert "cancel" in page.workflow_status.value.casefold()
    page._update_buttons()
    assert page._inspection_failed
    assert not page.plan_context_label.value.casefold().startswith("loading")
    assert page.retry_loading_button.visible and page.retry_loading_button.enabled
    assert not page.protocol_settings_button.visible
    assert not page.run_analysis_button.enabled
    worker.assert_not_called()
    assert page.refresh_project_context()
    worker.assert_called_once()


def test_post_processing_handoff_does_not_leave_a_loading_design(tmp_path):
    page, worker = _page(tmp_path, snapshot=ProjectFrequencySnapshot(1.2, 6.0), reason=None)
    page._on_post_processing_required("FullFFT provenance needs rebuilding.")
    assert page._pending_post_processing_reason == "FullFFT provenance needs rebuilding."
    assert "post-processing" in page.plan_context_label.value.casefold()
    assert not any(widget.visible for widget in page.family_checks.values())
    worker.assert_not_called()


def test_changed_project_hides_old_comparisons_until_new_inspection_completes(tmp_path):
    page, worker = _page(tmp_path, snapshot=ProjectFrequencySnapshot(1.2, 6.0), reason=None)
    page._options = object()
    destination = tmp_path / "next project"
    assert page.refresh_project_context(project_root=destination)
    assert page._project_root == destination.resolve()
    assert page._options is None
    assert page.plan_summary_label.value == ""
    assert not any(widget.visible for widget in page.family_checks.values())
    worker.assert_called_once()
    assert worker.call_args.args[1] == destination.resolve()

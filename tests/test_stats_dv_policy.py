from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from Tools.Stats.PySide6.dv_policies import (  # noqa: E402
    EMPTY_LIST_FALLBACK_FIXED_K,
    FIXED_K_POLICY_NAME,
    GROUP_MEAN_Z_POLICY_NAME,
    LEGACY_POLICY_NAME,
)
from Tools.Stats.PySide6.stats_core import PipelineId, StepId  # noqa: E402
from Tools.Stats.PySide6.stats_controller import (  # noqa: E402
    BETWEEN_PIPELINE_STEPS,
    SINGLE_PIPELINE_STEPS,
)
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


def _setup_window_state(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["CondA", "CondB"]
    window.subject_data = {"S1": {"CondA": "a.xlsx", "CondB": "b.xlsx"}}
    window.rois = {"ROI1": ["Fz"]}


@pytest.mark.qt
def test_stats_dv_policy_defaults(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    assert window.dv_policy_combo.currentText() == LEGACY_POLICY_NAME
    assert window.get_dv_policy_snapshot()["name"] == LEGACY_POLICY_NAME


@pytest.mark.qt
def test_stats_dv_policy_fixed_k_snapshot_and_kwargs(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()
    _setup_window_state(window)

    window.dv_policy_combo.setCurrentText(FIXED_K_POLICY_NAME)
    window.fixed_k_spinbox.setValue(7)

    snapshot = window.get_dv_policy_snapshot()
    assert snapshot["name"] == FIXED_K_POLICY_NAME
    assert snapshot["fixed_k"] == 7

    kwargs, _handler = window.get_step_config(PipelineId.SINGLE, StepId.RM_ANOVA)
    assert kwargs["dv_policy"]["name"] == FIXED_K_POLICY_NAME
    assert kwargs["dv_policy"]["fixed_k"] == 7


@pytest.mark.qt
def test_stats_dv_policy_group_mean_z_defaults(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    window.dv_policy_combo.setCurrentText(GROUP_MEAN_Z_POLICY_NAME)
    snapshot = window.get_dv_policy_snapshot()

    assert snapshot["name"] == GROUP_MEAN_Z_POLICY_NAME
    assert snapshot["z_threshold"] == pytest.approx(1.64)
    assert snapshot["empty_list_policy"] == EMPTY_LIST_FALLBACK_FIXED_K


@pytest.mark.qt
def test_stats_dv_policy_does_not_change_step_queue(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()
    _setup_window_state(window)

    legacy_steps = window._controller._build_steps(PipelineId.SINGLE, SINGLE_PIPELINE_STEPS)
    legacy_ids = [step.id for step in legacy_steps]

    window.dv_policy_combo.setCurrentText(FIXED_K_POLICY_NAME)
    window.fixed_k_spinbox.setValue(9)

    fixed_steps = window._controller._build_steps(PipelineId.SINGLE, SINGLE_PIPELINE_STEPS)
    fixed_ids = [step.id for step in fixed_steps]

    assert legacy_ids == fixed_ids
    for legacy_step, fixed_step in zip(legacy_steps, fixed_steps):
        if "dv_policy" in legacy_step.kwargs:
            assert legacy_step.kwargs["dv_policy"]["name"] == LEGACY_POLICY_NAME
            assert fixed_step.kwargs["dv_policy"]["name"] == FIXED_K_POLICY_NAME

    window.dv_policy_combo.setCurrentText(LEGACY_POLICY_NAME)
    between_legacy = window._controller._build_steps(PipelineId.BETWEEN, BETWEEN_PIPELINE_STEPS)
    window.dv_policy_combo.setCurrentText(FIXED_K_POLICY_NAME)
    between_fixed = window._controller._build_steps(PipelineId.BETWEEN, BETWEEN_PIPELINE_STEPS)
    assert [step.id for step in between_legacy] == [step.id for step in between_fixed]

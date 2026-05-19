from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from Tools.Stats.analysis.dv_policies import (  # noqa: E402
    EMPTY_LIST_FALLBACK_FIXED_K,
    FIXED_K_POLICY_NAME,
    GROUP_MEAN_Z_POLICY_NAME,
    ROSSION_POLICY_NAME,
)
from Tools.Stats.common.stats_core import PipelineId, StepId  # noqa: E402
from Tools.Stats.controller.stats_controller import (  # noqa: E402
    SINGLE_PIPELINE_STEPS,
)
from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402


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

    assert window.dv_policy_combo.currentText() == ROSSION_POLICY_NAME
    assert window.get_dv_policy_snapshot()["name"] == ROSSION_POLICY_NAME


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

    default_steps = window._controller._build_steps(PipelineId.SINGLE, SINGLE_PIPELINE_STEPS)
    default_ids = [step.id for step in default_steps]
    default_policy_name = window.get_dv_policy_snapshot()["name"]

    window.dv_policy_combo.setCurrentText(FIXED_K_POLICY_NAME)
    window.fixed_k_spinbox.setValue(9)

    fixed_steps = window._controller._build_steps(PipelineId.SINGLE, SINGLE_PIPELINE_STEPS)
    fixed_ids = [step.id for step in fixed_steps]

    assert default_ids == fixed_ids
    for default_step, fixed_step in zip(default_steps, fixed_steps):
        if "dv_policy" in default_step.kwargs:
            assert default_step.kwargs["dv_policy"]["name"] == default_policy_name
            assert fixed_step.kwargs["dv_policy"]["name"] == FIXED_K_POLICY_NAME


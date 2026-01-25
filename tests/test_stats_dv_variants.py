from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QCheckBox  # noqa: E402

from Tools.Stats.PySide6.dv_policies import (  # noqa: E402
    FIXED_K_POLICY_NAME,
    GROUP_MEAN_Z_POLICY_NAME,
    LEGACY_POLICY_NAME,
)
from Tools.Stats.PySide6.stats_core import PipelineId, StepId  # noqa: E402
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow  # noqa: E402


def _setup_window_state(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["CondA", "CondB"]
    window.subject_data = {
        "S1": {"CondA": "a.xlsx", "CondB": "b.xlsx"},
        "S2": {"CondA": "c.xlsx", "CondB": "d.xlsx"},
    }
    window.rois = {"ROI1": ["Fz"]}


@pytest.mark.qt
def test_stats_dv_variants_ui_defaults(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    checkboxes = {box.text(): box for box in window.findChildren(QCheckBox)}
    assert checkboxes[FIXED_K_POLICY_NAME].isChecked() is False
    assert checkboxes[GROUP_MEAN_Z_POLICY_NAME].isChecked() is False
    assert window.get_dv_variants_snapshot() == []


@pytest.mark.qt
def test_stats_group_mean_option_visibility(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    window.dv_policy_combo.setCurrentText(GROUP_MEAN_Z_POLICY_NAME)
    assert window.group_mean_controls.isVisible() is True


@pytest.mark.qt
def test_stats_dv_variants_do_not_change_primary_snapshot(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()
    _setup_window_state(window)

    window.dv_policy_combo.setCurrentText(LEGACY_POLICY_NAME)
    baseline = window.get_dv_policy_snapshot()

    window._dv_variant_checkboxes[FIXED_K_POLICY_NAME].setChecked(True)
    assert window.get_dv_policy_snapshot() == baseline
    assert window.get_dv_variants_snapshot() == [FIXED_K_POLICY_NAME]


@pytest.mark.qt
def test_stats_dv_variants_do_not_change_primary_kwargs(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()
    _setup_window_state(window)

    window.dv_policy_combo.setCurrentText(LEGACY_POLICY_NAME)
    kwargs_a, _handler_a = window.get_step_config(PipelineId.SINGLE, StepId.RM_ANOVA)

    window._dv_variant_checkboxes[FIXED_K_POLICY_NAME].setChecked(True)
    kwargs_b, _handler_b = window.get_step_config(PipelineId.SINGLE, StepId.RM_ANOVA)

    assert kwargs_a["dv_policy"] == kwargs_b["dv_policy"]
    assert kwargs_a["dv_variants"] != kwargs_b["dv_variants"]

    kwargs_a_filtered = {k: v for k, v in kwargs_a.items() if k != "dv_variants"}
    kwargs_b_filtered = {k: v for k, v in kwargs_b.items() if k != "dv_variants"}
    assert kwargs_a_filtered == kwargs_b_filtered

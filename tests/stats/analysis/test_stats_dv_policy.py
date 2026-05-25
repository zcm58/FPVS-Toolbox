from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from Tools.Stats.analysis.dv_policies import (  # noqa: E402
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    normalize_dv_policy,
)
from Tools.Stats.common.stats_core import PipelineId, StepId  # noqa: E402
from Tools.Stats.controller.stats_controller import SINGLE_PIPELINE_STEPS  # noqa: E402
from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402


def _setup_window_state(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["CondA", "CondB"]
    window.subject_data = {"S1": {"CondA": "a.xlsx", "CondB": "b.xlsx"}}
    window.rois = {"ROI1": ["Fz"]}


@pytest.mark.qt
def test_stats_dv_policy_fixed_predefined_is_only_ui_option(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    assert window.dv_policy_combo.count() == 1
    assert window.dv_policy_combo.currentText() == FIXED_PREDEFINED_POLICY_NAME
    assert window.dv_policy_combo.isEnabled() is False
    assert window.get_dv_policy_snapshot()["name"] == FIXED_PREDEFINED_POLICY_NAME
    assert window.get_dv_policy_snapshot()["fixed_harmonic_frequencies_hz"] == (
        FIXED_PREDEFINED_DEFAULT_FREQUENCIES
    )


def test_normalize_dv_policy_coerces_deprecated_names_to_fixed_predefined():
    for old_name in [
        "Current (Legacy)",
        "Fixed-K harmonics",
        "Rossion Method (common group-level harmonics)",
        "Rossion Method (Significant-only; stop after 2 failures)",
    ]:
        settings = normalize_dv_policy(
            {
                "name": old_name,
                "fixed_harmonic_frequencies_hz": "1.2, 2.4",
                "fixed_harmonic_auto_exclude_base": False,
            }
        )
        assert settings.name == FIXED_PREDEFINED_POLICY_NAME
        assert settings.fixed_harmonic_frequencies_hz == "1.2, 2.4"
        assert settings.fixed_harmonic_auto_exclude_base is False


@pytest.mark.qt
def test_stats_dv_policy_does_not_change_step_queue(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()
    _setup_window_state(window)

    steps = window._controller._build_steps(PipelineId.SINGLE, SINGLE_PIPELINE_STEPS)
    ids = [step.id for step in steps]

    assert ids == [
        StepId.RM_ANOVA,
        StepId.MIXED_MODEL,
        StepId.INTERACTION_POSTHOCS,
        StepId.BASELINE_VS_ZERO,
    ]
    for step in steps:
        if "dv_policy" in step.kwargs:
            assert step.kwargs["dv_policy"]["name"] == FIXED_PREDEFINED_POLICY_NAME

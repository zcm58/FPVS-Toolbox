from __future__ import annotations

import pytest

pytest.importorskip("PySide6")
from Tools.Stats.analysis.dv_policies import (  # noqa: E402
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_NAME,
    LOCKED_ODDBALL_FREQUENCY_HZ,
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
def test_stats_dv_policy_group_significant_is_default(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    assert window.dv_policy_combo.count() == 2
    assert window.dv_policy_combo.currentText() == GROUP_SIGNIFICANT_POLICY_NAME
    assert window.dv_policy_combo.itemText(0) == GROUP_SIGNIFICANT_POLICY_NAME
    assert window.dv_policy_combo.itemText(1) == FIXED_PREDEFINED_POLICY_NAME
    assert window.dv_policy_combo.isEnabled() is True
    assert window.get_dv_policy_snapshot()["name"] == GROUP_SIGNIFICANT_POLICY_NAME
    assert window.get_dv_policy_snapshot()["fixed_harmonic_frequencies_hz"] == (
        FIXED_PREDEFINED_DEFAULT_FREQUENCIES
    )


def test_normalize_dv_policy_defaults_to_group_significant():
    settings = normalize_dv_policy(None)

    assert settings.name == GROUP_SIGNIFICANT_POLICY_NAME


def test_normalize_dv_policy_coerces_fixed_aliases_to_fixed_predefined():
    for old_name in [
        "Current (Legacy)",
        "Fixed-K harmonics",
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


def test_normalize_dv_policy_coerces_rossion_aliases_to_group_significant():
    for old_name in [
        "Rossion Method (common group-level harmonics)",
        "Rossion Method (Significant-only; stop after 2 failures)",
        "unknown future value",
    ]:
        settings = normalize_dv_policy({"name": old_name})

        assert settings.name == GROUP_SIGNIFICANT_POLICY_NAME


def test_normalize_dv_policy_accepts_group_significant_policy():
    settings = normalize_dv_policy(
        {"name": GROUP_SIGNIFICANT_POLICY_NAME, "oddball_frequency_hz": "6.0"}
    )

    assert settings.name == GROUP_SIGNIFICANT_POLICY_NAME
    assert settings.fixed_harmonic_frequencies_hz == FIXED_PREDEFINED_DEFAULT_FREQUENCIES
    assert settings.group_significant_oddball_frequency_hz == pytest.approx(
        LOCKED_ODDBALL_FREQUENCY_HZ
    )


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
            assert step.kwargs["dv_policy"]["name"] == GROUP_SIGNIFICANT_POLICY_NAME

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")
from Tools.Stats.analysis.dv_policies import (  # noqa: E402
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_NAME,
    LOCKED_ODDBALL_FREQUENCY_HZ,
    normalize_dv_policy,
)
from Tools.Stats.analysis.dv_policy_settings import HARMONIC_PROFILE_FIXED_ID  # noqa: E402
from Tools.Stats.common.stats_core import PipelineId  # noqa: E402
from Tools.Stats.controller.stats_controller import SINGLE_PIPELINE_STEPS  # noqa: E402
from Tools.Stats.ui import stats_window_exclusions  # noqa: E402
from Tools.Stats.ui.stats_window import StatsWindow  # noqa: E402


def _setup_window_state(window: StatsWindow) -> None:
    window.subjects = ["S1", "S2"]
    window.conditions = ["CondA", "CondB"]
    window.subject_data = {"S1": {"CondA": "a.xlsx", "CondB": "b.xlsx"}}
    window.rois = {"ROI1": ["Fz"]}


@pytest.mark.qt
def test_stats_dv_policy_is_read_only_and_projectless_compatible(qtbot):
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)
    window.show()

    assert not hasattr(window, "dv_policy_combo")
    assert not hasattr(window, "fixed_predefined_exclude_base")
    assert window.harmonic_profile_value.text() == "No project selection loaded"
    assert window.harmonic_included_value.text() == "Unavailable"
    assert window.get_dv_policy_snapshot()["name"] == GROUP_SIGNIFICANT_POLICY_NAME
    assert window.get_dv_policy_snapshot()["fixed_harmonic_frequencies_hz"] == (
        FIXED_PREDEFINED_DEFAULT_FREQUENCIES
    )


@pytest.mark.qt
def test_stats_payload_and_summary_follow_canonical_fixed_selection(
    qtbot,
    monkeypatch,
    tmp_path,
):
    (tmp_path / "project.json").write_text("{}", encoding="utf-8")
    selection = SimpleNamespace(
        selected_harmonics_hz=(1.2, 2.4, 3.6),
        metadata={
            "harmonic_policy": "fixed_predefined_harmonic_list",
            "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
            "harmonic_selection_profile_version": "1.0",
            "harmonic_selection_profile_label": "Fixed / preregistered harmonic domain",
            "fixed_harmonic_requested_frequencies_hz": [1.2, 2.4, 3.6, 6.0],
            "fixed_harmonic_input_mode": "frequency_list",
            "included_harmonics_hz": [1.2, 2.4, 3.6],
            "selection_fingerprint": "abcdef1234567890",
            "same_sample_adaptive": False,
        },
    )
    monkeypatch.setattr(
        stats_window_exclusions,
        "load_project_processing_harmonics",
        lambda **_kwargs: selection,
    )

    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)
    window.show()

    assert window.harmonic_profile_value.text() == (
        "Fixed / preregistered harmonic domain (v1.0)"
    )
    assert window.harmonic_included_value.text() == "1.2, 2.4, 3.6 Hz"
    assert "abcdef123456" in window.harmonic_selection_note.text()

    # Stale private compatibility values cannot override project-owned state.
    window._dv_policy_name = GROUP_SIGNIFICANT_POLICY_NAME
    window._dv_fixed_harmonic_frequencies_hz = "99"
    window._dv_fixed_harmonic_auto_exclude_base = False
    payload = window.get_dv_policy_snapshot()

    assert payload["name"] == FIXED_PREDEFINED_POLICY_NAME
    assert payload["harmonic_selection_profile"] == HARMONIC_PROFILE_FIXED_ID
    assert payload["fixed_harmonic_frequencies_hz"] == "1.2, 2.4, 3.6, 6"
    assert payload["fixed_harmonic_auto_exclude_base"] is True


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
        assert settings.fixed_harmonic_auto_exclude_base is True


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

    assert ids == list(SINGLE_PIPELINE_STEPS)
    for step in steps:
        if "dv_policy" in step.kwargs:
            assert step.kwargs["dv_policy"]["name"] == GROUP_SIGNIFICANT_POLICY_NAME

from __future__ import annotations

from Tools.Stats.PySide6.stats_core import PipelineId, StepId
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


def test_manual_exclusion_state_in_payload(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)

    window.subjects = ["P1", "P2", "P3"]
    window.subject_data = {
        "P1": {"A": "P1_A.xlsx"},
        "P2": {"A": "P2_A.xlsx"},
        "P3": {"A": "P3_A.xlsx"},
    }
    window.conditions = ["A", "B"]
    window._populate_conditions_panel(window.conditions)
    window.rois = {"ROI": ["Cz"]}
    window._current_base_freq = 6.0
    window._current_alpha = 0.05

    window._manual_excluded_pids = ["P2"]
    window._reconcile_manual_exclusions(window.subjects)

    assert "P2" in window.manual_exclusion_list.toPlainText()
    assert "Excluded: 1 participant" in window.manual_exclusion_summary_label.text()

    kwargs, _handler = window.get_step_config(PipelineId.SINGLE, StepId.RM_ANOVA)
    assert kwargs["manual_excluded_pids"] == ["P2"]

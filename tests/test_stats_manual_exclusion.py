from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt

from Tools.Stats.PySide6 import stats_workers
from Tools.Stats.PySide6.stats_core import PipelineId, StepId
from Tools.Stats.PySide6.stats_manual_exclusion_dialog import ManualOutlierExclusionDialog
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


def test_manual_exclusion_dialog_apply_emits_and_closes(qtbot) -> None:
    dialog = ManualOutlierExclusionDialog(
        candidates=["P1", "P2"],
        flagged_map={},
        preselected=set(),
    )
    qtbot.addWidget(dialog)

    dialog.list_widget.item(0).setCheckState(Qt.Checked)
    with qtbot.waitSignal(dialog.manualExclusionsApplied, timeout=1000) as blocker:
        qtbot.mouseClick(dialog.apply_button, Qt.LeftButton)

    assert blocker.args[0] == {"P1"}
    assert dialog.result() == dialog.Accepted


def test_manual_exclusion_state_in_payload(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)

    window.subjects = ["P1", "P2", "P3"]
    window.subject_data = {
        "P1": {"A": {"ROI": 1.0}},
        "P2": {"A": {"ROI": 1.0}},
        "P3": {"A": {"ROI": 1.0}},
    }
    window.conditions = ["A", "B"]
    window._populate_conditions_panel(window.conditions)
    window.rois = {"ROI": ["Cz"]}
    window._current_base_freq = 6.0
    window._current_alpha = 0.05

    window._reconcile_manual_exclusions(window.subjects)

    dialog = ManualOutlierExclusionDialog(
        candidates=window.subjects,
        flagged_map={},
        preselected=window.manual_excluded_pids,
        parent=window,
    )
    qtbot.addWidget(dialog)

    def _apply_changes(selections: set[str]) -> None:
        window.manual_excluded_pids = set(selections)
        window._update_manual_exclusion_summary()

    dialog.manualExclusionsApplied.connect(_apply_changes)
    dialog.list_widget.item(1).setCheckState(Qt.Checked)
    qtbot.mouseClick(dialog.apply_button, Qt.LeftButton)

    assert "P2" in window.manual_exclusion_list.toolTip()
    assert window.manual_exclusion_summary_label.text() == "Excluded: 1"

    kwargs, _handler = window.get_step_config(PipelineId.SINGLE, StepId.RM_ANOVA)
    assert kwargs["manual_excluded_pids"] == ["P2"]


def test_manual_exclusion_filters_before_dv_compute(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def _fake_prepare_summed_bca_data(*, subjects, subject_data, **_kwargs):
        seen["subjects"] = list(subjects)
        seen["subject_data"] = dict(subject_data)
        return {"P1": {"A": {"ROI": 1.0}}}

    def _fake_run_rm_anova(*_args, **_kwargs):
        return "ok", pd.DataFrame()

    monkeypatch.setattr(stats_workers, "prepare_summed_bca_data", _fake_prepare_summed_bca_data)
    monkeypatch.setattr(stats_workers, "analysis_run_rm_anova", _fake_run_rm_anova)

    stats_workers.run_rm_anova(
        progress_cb=lambda *_args: None,
        message_cb=lambda *_args: None,
        subjects=["P1", "P2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={
            "P1": {"A": {"ROI": 1.0}},
            "P2": {"A": {"ROI": 2.0}},
        },
        base_freq=6.0,
        rois={"ROI": ["Cz"]},
        rois_all={"ROI": ["Cz"]},
        manual_excluded_pids=["P2"],
    )

    assert seen["subjects"] == ["P1"]
    assert "P2" not in seen["subject_data"]

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt

from Tools.Stats.workers import stats_workers
from Tools.Stats.common.stats_core import PipelineId, StepId
from Tools.Stats.ui.stats_window import StatsWindow


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

    assert window.manual_exclusion_candidates_list.count() == 3
    window.setup_tabs.setCurrentIndex(1)
    window._open_manual_exclusion_dialog()
    assert window.setup_tabs.currentIndex() == 0

    window.manual_exclusion_candidates_list.item(1).setCheckState(Qt.Checked)

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

    def _skip_qc_screening(*, subjects, subject_data, **_kwargs):
        return list(subjects), subject_data, None

    monkeypatch.setattr(stats_workers, "prepare_summed_bca_data", _fake_prepare_summed_bca_data)
    monkeypatch.setattr(stats_workers, "analysis_run_rm_anova", _fake_run_rm_anova)
    monkeypatch.setattr(stats_workers, "_apply_qc_screening", _skip_qc_screening)

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

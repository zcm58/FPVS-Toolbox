from __future__ import annotations

from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThreadPool

from Tools.Stats.PySide6.stats_core import PipelineId, PipelineStep, StepId
from Tools.Stats.PySide6.stats_main_window import StatsWindow
from Tools.Stats.PySide6.stats_workers import run_lmm


def test_stats_window_error_slot_does_not_raise_keyerror(qtbot, monkeypatch, tmp_path: Path) -> None:
    window = StatsWindow(project_dir=str(tmp_path))
    qtbot.addWidget(window)

    monkeypatch.setattr(QThreadPool, "start", lambda self, worker: worker.run(), raising=False)

    def failing_worker(*_args, **_kwargs):
        raise RuntimeError("synthetic worker failure")

    error_messages: list[str] = []
    step = PipelineStep(
        id=StepId.RM_ANOVA,
        name="RM-ANOVA",
        worker_fn=failing_worker,
        kwargs={},
        handler=lambda _payload: None,
    )

    window.start_step_worker(
        PipelineId.SINGLE,
        step,
        finished_cb=lambda *_args: None,
        error_cb=lambda _pid, _sid, message: error_messages.append(message),
    )

    assert error_messages
    assert "synthetic worker failure" in error_messages[0]


def test_run_lmm_returns_blocked_payload_when_rows_drop_to_zero(tmp_path: Path) -> None:
    diagnostics: list[str] = []
    fixed_dv = pd.DataFrame(
        {
            "subject": ["S1", "S2"],
            "condition": ["A", "A"],
            "roi": ["ROI1", "ROI1"],
            "dv_value": [float("nan"), float("nan")],
            "group": ["G1", "G2"],
        }
    )

    payload = run_lmm(
        lambda _progress: None,
        diagnostics.append,
        subjects=["S1", "S2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
        subject_groups={"S1": "G1", "S2": "G2"},
        include_group=True,
        fixed_harmonic_dv_table=fixed_dv,
        required_conditions=["A"],
        subject_to_group={"S1": "G1", "S2": "G2"},
        results_dir=str(tmp_path),
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_stage"] in {"dropna_dependent_variable", "between_group_dv_mapping"}
    assert payload["mixed_results_df"].empty
    assert any("dependent_variable_column" in line for line in diagnostics)


def test_blocked_lmm_exports_diagnostics_workbook(tmp_path: Path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["S1", "S2"],
            "condition": ["A", "A"],
            "roi": ["ROI1", "ROI1"],
            "dv_value": [float("nan"), float("nan")],
            "group": ["G1", "G2"],
        }
    )

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        subjects=["S1", "S2"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
        subject_groups={"S1": "G1", "S2": "G2"},
        include_group=True,
        fixed_harmonic_dv_table=fixed_dv,
        required_conditions=["A"],
        subject_to_group={"S1": "G1", "S2": "G2"},
        results_dir=str(tmp_path),
    )

    workbook_path = Path(payload["diagnostics_workbook"])
    assert workbook_path.is_file()

    with pd.ExcelFile(workbook_path) as workbook:
        assert {"StageCounts", "ExcludedParticipants", "ModelInput_Columns", "ConditionSets", "KeyMatchStats", "FinalBeforeDropna", "RemainingRows_Sample"}.issubset(
            set(workbook.sheet_names)
        )

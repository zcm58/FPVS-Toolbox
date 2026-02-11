from __future__ import annotations

import pandas as pd

from Tools.Stats.PySide6 import stats_workers
from Tools.Stats.PySide6.stats_workers import run_lmm


def _base_kwargs(fixed_dv: pd.DataFrame, tmp_path):
    return {
        "subjects": ["S1", "S2"],
        "conditions": ["A"],
        "conditions_all": ["A"],
        "subject_data": {},
        "base_freq": 6.0,
        "alpha": 0.05,
        "rois": {"ROI1": ["O1"]},
        "rois_all": {"ROI1": ["O1"]},
        "subject_groups": {"S1": "G1", "S2": "G2"},
        "include_group": True,
        "fixed_harmonic_dv_table": fixed_dv,
        "required_conditions": ["A"],
        "subject_to_group": {"S1": "G1", "S2": "G2"},
        "results_dir": str(tmp_path),
    }


def test_between_group_lmm_blocks_with_pid_mismatch(tmp_path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["X1", "X2"],
            "condition": ["A", "A"],
            "roi": ["ROI1", "ROI1"],
            "dv_value": [1.0, 2.0],
            "group": ["G1", "G2"],
        }
    )

    payload = run_lmm(lambda _progress: None, lambda _msg: None, **_base_kwargs(fixed_dv, tmp_path))

    assert payload["status"] == "blocked"
    assert "PID mismatch" in payload["message"]
    assert payload["merge_match_stats"]["intersection_count"] == 0


def test_between_group_lmm_blocks_with_condition_mismatch(tmp_path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["S1", "S2"],
            "condition": ["B", "B"],
            "roi": ["ROI1", "ROI1"],
            "dv_value": [1.0, 2.0],
            "group": ["G1", "G2"],
        }
    )

    payload = run_lmm(lambda _progress: None, lambda _msg: None, **_base_kwargs(fixed_dv, tmp_path))

    assert payload["status"] == "blocked"
    assert "Selected conditions not found" in payload["message"]
    assert payload["merge_match_stats"]["intersection_count"] == 0


def test_between_group_lmm_merge_success_does_not_block(monkeypatch, tmp_path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["S1", "S2"],
            "condition": ["A", "A"],
            "roi": ["ROI1", "ROI1"],
            "dv_value": [1.0, 2.0],
            "group": ["G1", "G2"],
        }
    )

    monkeypatch.setattr(
        stats_workers,
        "run_mixed_effects_model",
        lambda **_kwargs: pd.DataFrame({"term": ["Intercept"], "pvalue": [0.1]}),
    )

    payload = run_lmm(lambda _progress: None, lambda _msg: None, **_base_kwargs(fixed_dv, tmp_path))

    assert payload.get("status") != "blocked"
    assert not payload["mixed_results_df"].empty

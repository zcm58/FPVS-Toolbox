from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.PySide6.stats_workers import run_lmm


def test_between_group_lmm_maps_dv_value_to_value_and_does_not_block(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["S1", "S1", "S2", "S2"],
            "condition": ["A", "B", "A", "B"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
            "group": ["G1", "G1", "G2", "G2"],
        }
    )

    captured: dict[str, object] = {}

    def _fake_mixed_effects_model(*, data, dv_col, group_col, fixed_effects):
        captured["dv_col"] = dv_col
        captured["data"] = data.copy()
        return pd.DataFrame({"Effect": ["condition"], "P-Value": [0.04]})

    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.run_mixed_effects_model", _fake_mixed_effects_model)

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        subjects=["S1", "S2"],
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
        subject_groups={"S1": "G1", "S2": "G2"},
        include_group=True,
        fixed_harmonic_dv_table=fixed_dv,
        required_conditions=["A", "B"],
        subject_to_group={"S1": "G1", "S2": "G2"},
    )

    assert payload.get("status") != "blocked"
    assert captured["dv_col"] == "value"
    model_input = captured["data"]
    assert model_input["value"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_between_group_lmm_blocks_when_all_candidate_dv_columns_are_nan(tmp_path: Path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["S1", "S2"],
            "condition": ["A", "A"],
            "roi": ["ROI1", "ROI1"],
            "dv_value": [float("nan"), float("nan")],
            "dv": [float("nan"), float("nan")],
            "SummedBCA": [float("nan"), float("nan")],
            "bca_sum": [float("nan"), float("nan")],
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

    assert payload["status"] == "blocked"
    assert payload["blocked_stage"] == "between_group_dv_mapping"
    assert "tried columns" in payload["message"]

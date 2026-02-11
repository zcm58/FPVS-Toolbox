from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.PySide6.stats_workers import LMM_DIAGNOSTIC_WORKBOOK, run_lmm


def _base_kwargs(results_dir: Path | None = None) -> dict:
    kwargs = {
        "subjects": ["P1", "P2"],
        "conditions": ["Face", "House"],
        "conditions_all": ["Face", "House"],
        "subject_data": {},
        "base_freq": 6.0,
        "alpha": 0.05,
        "rois": {"ROI1": ["O1"]},
        "rois_all": {"ROI1": ["O1"]},
        "subject_groups": {"P1": "G1", "P2": "G2"},
        "include_group": True,
        "required_conditions": ["Face", "House"],
        "subject_to_group": {"P1": "G1", "P2": "G2"},
    }
    if results_dir is not None:
        kwargs["results_dir"] = str(results_dir)
    return kwargs


def test_between_group_pid_mismatch_reports_precise_reason_and_writes_diagnostics(tmp_path: Path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P100", "P100", "P200", "P200"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        fixed_harmonic_dv_table=fixed_dv,
        **_base_kwargs(results_dir=tmp_path),
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "DV merge produced 0 matches: PID mismatch"

    workbook_path = tmp_path / LMM_DIAGNOSTIC_WORKBOOK
    assert workbook_path.is_file()
    with pd.ExcelFile(workbook_path) as workbook:
        assert {"StageCounts", "ConditionSets", "KeyMatchStats", "DVColumnAudit", "FinalBeforeDropna"}.issubset(
            set(workbook.sheet_names)
        )


def test_between_group_condition_mismatch_reports_precise_reason(tmp_path: Path) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2"],
            "condition": ["Car", "Chair", "Car", "Chair"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    payload = run_lmm(
        lambda _progress: None,
        lambda _msg: None,
        fixed_harmonic_dv_table=fixed_dv,
        **_base_kwargs(results_dir=tmp_path),
    )

    assert payload["status"] == "blocked"
    assert payload["blocked_reason"] == "DV merge produced 0 matches: condition mismatch"


def test_between_group_successful_merge_logs_non_nan_before_dropna_and_does_not_block(monkeypatch) -> None:
    fixed_dv = pd.DataFrame(
        {
            "subject": ["P1", "P1", "P2", "P2"],
            "condition": ["Face", "House", "Face", "House"],
            "roi": ["ROI1", "ROI1", "ROI1", "ROI1"],
            "dv_value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    logs: list[str] = []
    captured: dict[str, object] = {}

    def _fake_mixed_effects_model(*, data, dv_col, group_col, fixed_effects):
        captured["dv_col"] = dv_col
        captured["rows"] = len(data)
        return pd.DataFrame({"Effect": ["condition"], "P-Value": [0.04]})

    monkeypatch.setattr("Tools.Stats.PySide6.stats_workers.run_mixed_effects_model", _fake_mixed_effects_model)

    kwargs = _base_kwargs()
    kwargs["subjects"] = ["P1BCF", "P2CGL"]
    kwargs["subject_groups"] = {"P1BCF": "G1", "P2CGL": "G2"}
    kwargs["subject_to_group"] = {"P1BCF": "G1", "P2CGL": "G2"}

    payload = run_lmm(
        lambda _progress: None,
        logs.append,
        fixed_harmonic_dv_table=fixed_dv,
        **kwargs,
    )

    assert payload.get("status") != "blocked"
    assert captured["dv_col"] == "value"
    assert captured["rows"] == 4
    assert any("stage=after_merge_before_dropna" in line and "non_nan_count=4" in line for line in logs)

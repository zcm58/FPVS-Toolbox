from __future__ import annotations

import pandas as pd

from Tools.Stats.Legacy import excel_io
from Tools.Stats.PySide6.dv_policies import prepare_summed_bca_data
from Tools.Stats.PySide6.stats_qc_exclusion import (
    QC_REASON_MAXABS,
    QC_REASON_SUMABS,
    QcViolation,
    format_qc_violation,
    run_qc_exclusion,
)


def _make_bca_df(max_value: float) -> pd.DataFrame:
    data = {
        "1.2_Hz": [0.1, 0.1],
        "2.4_Hz": [0.1, 0.1],
        "3.6_Hz": [0.1, 0.1],
        "4.8_Hz": [0.1, 0.1],
        "7.2_Hz": [max_value, max_value],
    }
    df = pd.DataFrame(data, index=["O1", "O2"])
    df.index.name = "Electrode"
    return df


def test_qc_exclusion_independent_of_selected_conditions(monkeypatch) -> None:
    subject_data = {
        "P1": {"A": "P1_A.xlsx", "B": "P1_B.xlsx"},
        "P2": {"A": "P2_A.xlsx", "B": "P2_B.xlsx"},
        "P3": {"A": "P3_A.xlsx", "B": "P3_B.xlsx"},
    }
    conditions_all = ["A", "B"]
    rois = {"Occipital": ["O1", "O2"]}
    normal_df = _make_bca_df(0.1)
    extreme_df = _make_bca_df(1000.0)

    def _fake_read_excel(path, sheet_name, *, index_col=None, use_cache=True):
        _ = sheet_name, index_col, use_cache
        if "P3_B" in str(path):
            return extreme_df.copy()
        return normal_df.copy()

    monkeypatch.setattr(excel_io, "safe_read_excel", _fake_read_excel)

    report = run_qc_exclusion(
        subjects=list(subject_data.keys()),
        subject_data=subject_data,
        conditions_all=conditions_all,
        rois_all=rois,
        base_freq=6.0,
        log_func=None,
    )

    assert report.summary.n_subjects_flagged == 1
    assert any(
        QC_REASON_MAXABS in participant.reasons
        for participant in report.participants
        if participant.participant_id == "P3"
    )

    dv_data = prepare_summed_bca_data(
        subjects=list(subject_data.keys()),
        conditions=["A"],
        subject_data=subject_data,
        base_freq=6.0,
        log_func=lambda _m: None,
        rois=rois,
        dv_policy=None,
    )

    assert dv_data is not None
    assert set(dv_data.keys()) == set(subject_data.keys())
    assert set(dv_data["P1"].keys()) == {"A"}


def test_format_qc_violation_is_human_readable() -> None:
    violation = QcViolation(
        condition="CondA",
        roi="ROI1",
        metric=QC_REASON_SUMABS,
        severity="WARNING",
        value=12.34,
        robust_center=1.23,
        robust_spread=0.45,
        robust_score=7.89,
        threshold_used=6.0,
        abs_floor_used=5.0,
        trigger_harmonic_hz=12.0,
        roi_mean_bca_at_trigger=0.1234,
    )

    text = format_qc_violation(violation)

    assert "Unusually large total response" in text
    assert "Condition: CondA" in text
    assert "ROI: ROI1" in text
    assert "value: 12.3400" in text
    assert "Robust score: 7.890" in text
    assert "threshold 6.00" in text

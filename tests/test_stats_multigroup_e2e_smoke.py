from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.Legacy.group_contrasts import compute_group_contrasts
from Tools.Stats.PySide6.dv_policies import compute_fixed_harmonic_dv_table
from Tools.Stats.PySide6.stats_group_contrasts import normalize_group_contrasts_table
from Tools.Stats.PySide6.stats_missingness import compute_complete_case_subjects, compute_missingness
from Tools.Stats.PySide6.stats_workers import run_between_group_anova, run_lmm


def _write_bca_excel(path: Path, value_a: float, value_b: float) -> None:
    df = pd.DataFrame(
        {
            "1.2000_Hz": [value_a, value_a + 0.1],
            "2.4000_Hz": [value_b, value_b + 0.1],
            "3.6000_Hz": [999.0, 999.0],
        },
        index=["O1", "O2"],
    )
    df.index.name = "Electrode"
    with pd.ExcelWriter(path) as writer:
        df.to_excel(writer, sheet_name="BCA (uV)")


def _build_fixed_dv_payload(tmp_path: Path) -> tuple[pd.DataFrame, dict[str, str]]:
    groups = {
        "P1": "G1",
        "P2": "G1",
        "P3": "G1",
        "P4": "G2",
        "P5": "G2",
        "P6": "G2",
        "P7": "G3",
        "P8": "G3",
        "P9": "G3",
    }
    subject_data: dict[str, dict[str, str]] = {}
    for idx, pid in enumerate(groups, start=1):
        subject_data[pid] = {}
        for cond in ("A", "B"):
            if pid == "P3" and cond == "B":
                continue
            excel_path = tmp_path / f"{pid}_{cond}.xlsx"
            _write_bca_excel(excel_path, value_a=0.5 * idx, value_b=0.8 * idx)
            subject_data[pid][cond] = str(excel_path)

    payload = compute_fixed_harmonic_dv_table(
        subjects=list(groups.keys()),
        conditions=["A", "B"],
        subject_data=subject_data,
        rois={"ROI1": ["O1", "O2"]},
        harmonics_by_roi={"ROI1": [1.2, 2.4]},
        log_func=lambda _msg: None,
    )
    dv_df = payload["dv_df"].copy()
    dv_df["group"] = dv_df["subject"].map(groups)
    return dv_df, groups


def test_multigroup_end_to_end_smoke_with_fixed_dv(tmp_path: Path) -> None:
    dv_df, groups = _build_fixed_dv_payload(tmp_path)
    dv_df = dv_df.loc[~((dv_df["subject"] == "P3") & (dv_df["condition"] == "B"))].copy()

    missing = compute_missingness(dv_df, ["A", "B"], groups)
    assert any(row["Subject"] == "P3" and row["Condition"] == "B" for row in missing)

    included, excluded = compute_complete_case_subjects(dv_df, ["A", "B"], groups)
    assert "P3" not in included
    assert any(row["Subject"] == "P3" for row in excluded)

    mixed_payload = run_lmm(
        lambda _progress: None,
        lambda _message: None,
        subjects=sorted(groups),
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1", "O2"]},
        rois_all={"ROI1": ["O1", "O2"]},
        include_group=True,
        subject_groups=groups,
        subject_to_group=groups,
        fixed_harmonic_dv_table=dv_df,
        required_conditions=["A", "B"],
    )
    assert "mixed_results_df" in mixed_payload
    assert mixed_payload["missingness"]["mixed_model_subject_count"] >= 8

    anova_payload = run_between_group_anova(
        lambda _progress: None,
        lambda _message: None,
        subjects=sorted(groups),
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={},
        base_freq=6.0,
        rois={"ROI1": ["O1", "O2"]},
        rois_all={"ROI1": ["O1", "O2"]},
        subject_groups=groups,
        subject_to_group=groups,
        fixed_harmonic_dv_table=dv_df,
        required_conditions=["A", "B"],
    )
    assert any(row["Subject"] == "P3" for row in anova_payload["missingness"]["anova_excluded_subjects"])

    normalized = normalize_group_contrasts_table(
        compute_group_contrasts(
            dv_df.rename(columns={"dv_value": "value"}),
            subject_col="subject",
            group_col="group",
            condition_col="condition",
            roi_col="roi",
            dv_col="value",
        )
    )
    assert {"G1", "G2", "G3"}.issuperset(set(normalized["GroupA"]))
    assert len(normalized) >= 3


def test_single_group_fixed_dv_regression_schema_stable(tmp_path: Path) -> None:
    dv_df, groups = _build_fixed_dv_payload(tmp_path)
    single_df = dv_df[dv_df["subject"].isin(["P1", "P2", "P3"])].copy()

    payload = run_lmm(
        lambda _progress: None,
        lambda _message: None,
        subjects=["P1", "P2", "P3"],
        conditions=["A", "B"],
        conditions_all=["A", "B"],
        subject_data={},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1", "O2"]},
        rois_all={"ROI1": ["O1", "O2"]},
        include_group=False,
        subject_groups={pid: groups[pid] for pid in ["P1", "P2", "P3"]},
        fixed_harmonic_dv_table=single_df,
    )

    assert set(["subject", "condition", "roi", "dv_value"]).issubset(single_df.columns)
    assert "missingness" in payload
    assert payload["missingness"] == {}
    assert "mixed_results_df" in payload

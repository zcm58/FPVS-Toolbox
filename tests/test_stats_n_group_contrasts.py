from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.analysis.group_contrasts import compute_group_contrasts
from Tools.Stats.reporting.stats_export import export_mixed_model_results_to_excel
from Tools.Stats.common.stats_core import GROUP_CONTRAST_XLS, LMM_BETWEEN_XLS
from Tools.Stats.analysis.stats_group_contrasts import (
    PAIRWISE_CONTRAST_COLUMNS,
    export_group_contrasts_workbook,
    normalize_group_contrasts_table,
)
from Tools.Stats.reporting.summary_utils import SummaryConfig, build_summary_from_files


def _build_long_df(groups: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for condition in ("Cond1",):
        for roi in ("ROI1",):
            for group_idx, group in enumerate(groups):
                for subject_offset, value in enumerate((1.0 + group_idx, 2.0 + group_idx)):
                    rows.append(
                        {
                            "subject": f"{group}_S{subject_offset+1}",
                            "group": group,
                            "condition": condition,
                            "roi": roi,
                            "value": value,
                        }
                    )
    return pd.DataFrame(rows)


def test_n3_generates_all_pairs_stable_order_and_schema() -> None:
    data = _build_long_df(("A", "B", "C"))
    raw = compute_group_contrasts(
        data,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )

    normalized = normalize_group_contrasts_table(raw)

    assert len(normalized) == 3
    assert normalized.loc[:, "GroupA"].tolist() == ["A", "A", "B"]
    assert normalized.loc[:, "GroupB"].tolist() == ["B", "C", "C"]
    assert list(normalized.columns[: len(PAIRWISE_CONTRAST_COLUMNS)]) == list(PAIRWISE_CONTRAST_COLUMNS)


def test_correction_column_present_and_populated() -> None:
    data = _build_long_df(("A", "B", "C"))
    raw = compute_group_contrasts(
        data,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )

    normalized = normalize_group_contrasts_table(raw)

    assert "P_corrected" in normalized.columns
    assert normalized["P_corrected"].notna().all()
    assert (normalized["Method"] == "fdr_bh").all()


def test_two_group_case_matches_pre_phase_e_values() -> None:
    data = _build_long_df(("A", "B"))
    raw = compute_group_contrasts(
        data,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )
    normalized = normalize_group_contrasts_table(raw)

    assert len(normalized) == 1
    assert normalized.loc[0, "GroupA"] == raw.loc[0, "group_1"]
    assert normalized.loc[0, "GroupB"] == raw.loc[0, "group_2"]
    assert normalized.loc[0, "Estimate"] == raw.loc[0, "difference"]
    assert normalized.loc[0, "TestStat"] == raw.loc[0, "t_stat"]
    assert normalized.loc[0, "P"] == raw.loc[0, "p_value"]
    assert normalized.loc[0, "P_corrected"] == raw.loc[0, "p_fdr_bh"]


def test_export_uses_pairwise_contrasts_sheet(tmp_path: Path) -> None:
    data = _build_long_df(("A", "B", "C"))
    raw = compute_group_contrasts(
        data,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )
    save_path = tmp_path / "Group Contrasts.xlsx"

    export_group_contrasts_workbook(raw, save_path, log_func=lambda _msg: None)

    xls = pd.ExcelFile(save_path)
    assert "Pairwise_Contrasts" in xls.sheet_names
    exported = pd.read_excel(save_path, sheet_name="Pairwise_Contrasts")
    assert list(exported.columns[: len(PAIRWISE_CONTRAST_COLUMNS)]) == list(PAIRWISE_CONTRAST_COLUMNS)


def test_supported_between_export_roundtrip_builds_between_summary(tmp_path: Path) -> None:
    contrasts_df = pd.DataFrame(
        [
            {
                "condition": "Face",
                "roi": "Occipital",
                "group_1": "G1",
                "group_2": "G2",
                "difference": 0.6,
                "t_stat": 3.2,
                "p_value": 0.01,
                "effect_size": 0.8,
                "p_fdr_bh": 0.02,
            }
        ]
    )
    lmm_df = pd.DataFrame(
        {
            "Effect (raw)": ["Intercept"],
            "Estimate": [0.5],
            "P>|z|": [0.03],
        }
    )

    export_group_contrasts_workbook(contrasts_df, tmp_path / GROUP_CONTRAST_XLS, log_func=lambda _msg: None)
    export_mixed_model_results_to_excel(lmm_df, tmp_path / LMM_BETWEEN_XLS, log_func=lambda _msg: None)

    summary = build_summary_from_files(tmp_path, SummaryConfig())

    assert "RM-ANOVA:" not in summary
    assert "Group contrasts:" in summary
    assert "Occipital (Face): G1 > G2, p_adj = 0.020, d = 0.80." in summary
    assert "Overall response present" in summary


def test_supported_between_summary_reader_accepts_legacy_sheet_alias(tmp_path: Path) -> None:
    contrasts_df = normalize_group_contrasts_table(
        pd.DataFrame(
            [
                {
                    "condition": "Face",
                    "roi": "Occipital",
                    "group_1": "G1",
                    "group_2": "G2",
                    "difference": 0.6,
                    "t_stat": 3.2,
                    "p_value": 0.01,
                    "effect_size": 0.8,
                    "p_fdr_bh": 0.02,
                }
            ]
        )
    )
    lmm_df = pd.DataFrame(
        {
            "Effect (raw)": ["Intercept"],
            "Estimate": [0.5],
            "P>|z|": [0.03],
        }
    )

    with pd.ExcelWriter(tmp_path / GROUP_CONTRAST_XLS, engine="xlsxwriter") as writer:
        contrasts_df.to_excel(writer, sheet_name="Post-hoc Results", index=False)
    export_mixed_model_results_to_excel(lmm_df, tmp_path / LMM_BETWEEN_XLS, log_func=lambda _msg: None)

    summary = build_summary_from_files(tmp_path, SummaryConfig())

    assert "RM-ANOVA:" not in summary
    assert "Group contrasts:" in summary
    assert "Occipital (Face): G1 > G2, p_adj = 0.020, d = 0.80." in summary

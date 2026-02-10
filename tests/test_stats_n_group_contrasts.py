from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Stats.Legacy.group_contrasts import compute_group_contrasts
from Tools.Stats.PySide6.stats_group_contrasts import (
    PAIRWISE_CONTRAST_COLUMNS,
    export_group_contrasts_workbook,
    normalize_group_contrasts_table,
)


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

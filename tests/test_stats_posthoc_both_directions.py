import numpy as np
import pandas as pd
import importlib.util
from pathlib import Path


def _load_module(module_relpath: str, module_name: str):
    module_path = Path(__file__).resolve().parents[1] / "src" / Path(module_relpath)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Failed to load module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


POSTHOC_MODULE = _load_module("Tools/Stats/Legacy/posthoc_tests.py", "posthoc_tests")
EXPORT_MODULE = _load_module("Tools/Stats/Legacy/stats_export.py", "stats_export")
run_interaction_posthocs = POSTHOC_MODULE.run_interaction_posthocs
export_posthoc_results_to_excel = EXPORT_MODULE.export_posthoc_results_to_excel


def _synthetic_posthoc_df() -> pd.DataFrame:
    subjects = [f"S{i}" for i in range(1, 7)]
    conditions = ["C1", "C2"]
    rois = ["R1", "R2", "R3"]
    rows = []
    for subj_idx, subj in enumerate(subjects):
        for cond_idx, cond in enumerate(conditions):
            for roi_idx, roi in enumerate(rois):
                value = (
                    10.0
                    + cond_idx * 1.4
                    + roi_idx * 0.9
                    + (cond_idx * roi_idx * 0.5)
                    + subj_idx * 0.2
                )
                rows.append({"subject": subj, "condition": cond, "roi": roi, "value": value})
    return pd.DataFrame(rows)


def test_interaction_posthoc_default_runs_both_directions():
    df = _synthetic_posthoc_df()
    output_text, results_df = run_interaction_posthocs(
        data=df,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=0.05,
    )

    assert not results_df.empty
    assert {"Direction", "Stratum", "FactorAnalyzed"}.issubset(results_df.columns)
    assert {"condition_within_roi", "roi_within_condition"}.issubset(set(results_df["Direction"].dropna().unique()))
    assert not results_df.loc[results_df["Direction"] == "condition_within_roi"].empty
    assert not results_df.loc[results_df["Direction"] == "roi_within_condition"].empty

    assert "Simple effects: Condition within ROI" in output_text
    assert "Simple effects: ROI within Condition" in output_text
    assert "SUMMARY OF SIGNIFICANT FINDINGS" in output_text


def test_interaction_posthoc_single_direction_only_condition_within_roi():
    df = _synthetic_posthoc_df()
    _text, results_df = run_interaction_posthocs(
        data=df,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=0.05,
        direction="condition_within_roi",
    )

    assert not results_df.empty
    assert set(results_df["Direction"].dropna().unique()) == {"condition_within_roi"}


def test_interaction_posthoc_single_direction_only_roi_within_condition():
    df = _synthetic_posthoc_df()
    _text, results_df = run_interaction_posthocs(
        data=df,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=0.05,
        direction="roi_within_condition",
    )

    assert not results_df.empty
    assert set(results_df["Direction"].dropna().unique()) == {"roi_within_condition"}


def test_posthoc_export_writes_directional_and_combined_sheets(tmp_path):
    df = _synthetic_posthoc_df()
    _text, results_df = run_interaction_posthocs(
        data=df,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=0.05,
    )
    save_path = tmp_path / "Posthoc Results.xlsx"
    logs: list[str] = []

    export_posthoc_results_to_excel(results_df, save_path, logs.append)

    workbook = pd.ExcelFile(save_path)
    assert {
        "Posthoc_ConditionWithinROI",
        "Posthoc_ROIWithinCondition",
        "Combined",
    }.issubset(set(workbook.sheet_names))

    combined_df = pd.read_excel(save_path, sheet_name="Combined")
    assert {"Direction", "Stratum", "FactorAnalyzed"}.issubset(combined_df.columns)
    assert np.isin(["condition_within_roi", "roi_within_condition"], combined_df["Direction"].dropna().unique()).all()

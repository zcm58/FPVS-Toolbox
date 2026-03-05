import numpy as np
import pandas as pd
import pytest

from Tools.Stats.PySide6.baseline_vs_zero import run_baseline_vs_zero_tests
from Tools.Stats.PySide6.stats_controller import SINGLE_PIPELINE_STEPS, WORKER_FN_BY_STEP
from Tools.Stats.PySide6.stats_core import StepId


def _build_df() -> pd.DataFrame:
    rows = []
    subjects = ["S1", "S2", "S3"]
    for subject, base in zip(subjects, [0.6, 0.5, 0.7]):
        rows.append({"subject": subject, "condition": "A", "roi": "R1", "value": base})
        rows.append({"subject": subject, "condition": "B", "roi": "R1", "value": base - 0.8})
        rows.append({"subject": subject, "condition": "A", "roi": "R2", "value": base + 0.3})
        rows.append({"subject": subject, "condition": "B", "roi": "R2", "value": base + 0.1})
    return pd.DataFrame(rows)


def test_baseline_vs_zero_duplicate_keys_raise() -> None:
    df = _build_df()
    duplicated = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate rows detected"):
        run_baseline_vs_zero_tests(
            duplicated,
            dv_col="value",
            subject_col="subject",
            condition_col="condition",
            roi_col="roi",
        )


def test_baseline_vs_zero_correction_scope_outputs() -> None:
    df = _build_df()

    _, global_df = run_baseline_vs_zero_tests(
        df,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        correction_scope="global",
    )
    _, within_roi_df = run_baseline_vs_zero_tests(
        df,
        dv_col="value",
        subject_col="subject",
        condition_col="condition",
        roi_col="roi",
        correction_scope="within_roi",
    )

    for col in ["p_corr", "reject"]:
        assert col in global_df.columns
        assert col in within_roi_df.columns

    merged = global_df.merge(
        within_roi_df,
        on=["condition", "roi"],
        suffixes=("_global", "_within"),
    )
    assert not np.allclose(
        merged["p_corr_global"].to_numpy(dtype=float),
        merged["p_corr_within"].to_numpy(dtype=float),
        equal_nan=True,
    )


def test_single_pipeline_registers_baseline_vs_zero_step() -> None:
    assert StepId.BASELINE_VS_ZERO in SINGLE_PIPELINE_STEPS
    assert StepId.BASELINE_VS_ZERO in WORKER_FN_BY_STEP

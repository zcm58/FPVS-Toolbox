import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.baseline_vs_zero import run_baseline_vs_zero_tests
from Tools.Stats.analysis.dv_policy_settings import FIXED_PREDEFINED_POLICY_NAME
from Tools.Stats.controller.stats_controller import SINGLE_PIPELINE_STEPS, WORKER_FN_BY_STEP
from Tools.Stats.common.stats_core import StepId
from Tools.Stats.workers.stats_workers import run_baseline_vs_zero as run_baseline_worker


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


def test_single_pipeline_does_not_register_removed_harmonic_check() -> None:
    assert "HARMONIC_CHECK" not in StepId.__members__
    assert all(step.name != "HARMONIC_CHECK" for step in SINGLE_PIPELINE_STEPS)


def test_baseline_worker_reports_fixed_predefined_dv_metadata(monkeypatch) -> None:
    seen: dict[str, object] = {}

    monkeypatch.setattr("Tools.Stats.workers.stats_workers.set_rois", lambda _rois: None)
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._apply_qc_screening",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], None),
    )
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._apply_manual_exclusions",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"], []),
    )

    def _prepare_summed_bca_data(**kwargs):  # noqa: ANN003
        seen["dv_policy"] = kwargs["dv_policy"]
        kwargs["dv_metadata"].update(
            {
                "policy_name": FIXED_PREDEFINED_POLICY_NAME,
                "fixed_predefined_harmonics": {
                    "harmonic_policy": "fixed_predefined_harmonic_list",
                    "harmonic_policy_label": (
                        "Fixed predefined harmonic list applied uniformly across "
                        "participants, conditions, and ROIs"
                    ),
                    "fixed_harmonic_included_frequencies_hz": [1.2, 2.4, 3.6, 4.8, 7.2],
                    "snr_used_for_statistics": False,
                    "applied_uniformly_across_participants": True,
                    "applied_uniformly_across_conditions": True,
                    "applied_uniformly_across_rois": True,
                },
            }
        )
        return {
            "S1": {"A": {"ROI1": 0.4}},
            "S2": {"A": {"ROI1": 0.5}},
            "S3": {"A": {"ROI1": 0.6}},
        }

    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers.prepare_summed_bca_data",
        _prepare_summed_bca_data,
    )
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._apply_outlier_exclusion",
        lambda df, **kwargs: (df, None),
    )
    monkeypatch.setattr("Tools.Stats.workers.stats_workers.merge_exclusion_reports", lambda a, b: None)
    monkeypatch.setattr(
        "Tools.Stats.workers.stats_workers._extract_required_exclusions",
        lambda _report: [],
    )

    result = run_baseline_worker(
        lambda _progress: None,
        lambda _message: None,
        subjects=["S1", "S2", "S3"],
        conditions=["A"],
        conditions_all=["A"],
        subject_data={"S1": {"A": "unused"}, "S2": {"A": "unused"}, "S3": {"A": "unused"}},
        base_freq=6.0,
        alpha=0.05,
        rois={"ROI1": ["O1"]},
        rois_all={"ROI1": ["O1"]},
        dv_policy={
            "name": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4, 3.6, 4.8, 7.2",
        },
    )

    assert seen["dv_policy"]["name"] == FIXED_PREDEFINED_POLICY_NAME
    assert result["metadata"]["dv_policy_name"] == FIXED_PREDEFINED_POLICY_NAME
    assert result["metadata"]["selected_harmonics_hz"] == "1.2;2.4;3.6;4.8;7.2"
    assert result["metadata"]["snr_used_for_statistics"] is False
    assert result["dv_metadata"]["fixed_predefined_harmonics"][
        "applied_uniformly_across_conditions"
    ] is True

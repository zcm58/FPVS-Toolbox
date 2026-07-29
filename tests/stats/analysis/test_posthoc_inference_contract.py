from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.inference_contracts import FollowupProvenance
from Tools.Stats.analysis.posthoc_tests import (
    run_interaction_posthocs,
    run_planned_contrasts_category_vs_color,
    run_posthoc_pairwise_tests,
)


def _interaction_data() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    rng = np.random.default_rng(27)
    for subject_index in range(12):
        subject_shift = float(rng.normal(0.0, 0.25))
        for condition_index, condition in enumerate(("A", "B")):
            for roi_index, roi in enumerate(("R1", "R2", "R3")):
                rows.append(
                    {
                        "subject": f"S{subject_index + 1:02d}",
                        "condition": condition,
                        "roi": roi,
                        "value": (
                            subject_shift
                            + condition_index * (0.25 + roi_index * 0.15)
                            + roi_index * 0.1
                            + float(rng.normal(0.0, 0.35))
                        ),
                    }
                )
    return pd.DataFrame(rows)


def test_interaction_default_declares_one_cross_stratum_family_per_direction() -> None:
    _, result = run_interaction_posthocs(
        _interaction_data(),
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        direction="both",
    )

    condition_rows = result[result["Direction"] == "condition_within_roi"]
    roi_rows = result[result["Direction"] == "roi_within_condition"]
    assert condition_rows["family_id"].nunique() == 1
    assert condition_rows["family_size"].unique().tolist() == [3]
    assert roi_rows["family_id"].nunique() == 1
    assert roi_rows["family_size"].unique().tolist() == [6]

    expected_condition = multipletests(
        condition_rows["p_raw"].to_numpy(dtype=float),
        method="fdr_bh",
    )[1]
    expected_roi = multipletests(
        roi_rows["p_raw"].to_numpy(dtype=float),
        method="fdr_bh",
    )[1]
    np.testing.assert_allclose(condition_rows["p_adjusted"], expected_condition)
    np.testing.assert_allclose(roi_rows["p_adjusted"], expected_roi)
    np.testing.assert_allclose(result["p_fdr_bh"], result["p_adjusted"])
    assert result.attrs["family_scope"] == "direction"


def test_non_bh_correction_uses_generic_columns_without_bh_alias() -> None:
    _, result = run_interaction_posthocs(
        _interaction_data(),
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        correction="holm",
        direction="condition_within_roi",
    )

    assert {"p_raw", "p_adjusted", "reject_adjusted", "family_id"}.issubset(
        result.columns
    )
    assert "p_fdr_bh" not in result.columns
    assert set(result["adjustment_method"]) == {"holm"}
    assert result["Significant"].equals(result["reject_adjusted"])


def test_automatic_followup_is_explicitly_not_run_after_nonsignificant_omnibus() -> None:
    text, result = run_interaction_posthocs(
        _interaction_data(),
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        direction="both",
        followup_provenance=FollowupProvenance.OMNIBUS_TRIGGERED,
        omnibus_p_value=0.42,
    )

    assert len(result) == 2
    assert set(result["inference_status"]) == {"not_run"}
    assert set(result["status_code"]) == {"omnibus_not_significant"}
    assert set(result["followup_provenance"]) == {"omnibus_triggered"}
    assert result["p_raw"].isna().all()
    assert result["p_adjusted"].isna().all()
    assert not result["reject_adjusted"].any()
    assert "were not run" in text


def test_manual_exploratory_followup_may_run_after_nonsignificant_omnibus() -> None:
    _, result = run_interaction_posthocs(
        _interaction_data(),
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        direction="condition_within_roi",
        followup_provenance=FollowupProvenance.EXPLORATORY_MANUAL,
        omnibus_p_value=0.42,
    )

    assert not result.empty
    assert set(result["inference_status"]) == {"estimated"}
    assert set(result["followup_provenance"]) == {"exploratory_manual"}
    assert result.attrs["omnibus_gate_applied"] is False


def test_zero_difference_and_constant_nonzero_difference_do_not_emit_infinite_dz() -> None:
    zero = pd.DataFrame(
        {
            "subject": ["S1", "S2", "S3", "S4"],
            "condition": ["A", "A", "A", "A"],
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )
    zero = pd.concat(
        [
            zero,
            zero.assign(condition="B"),
        ],
        ignore_index=True,
    )
    _, zero_result = run_posthoc_pairwise_tests(
        zero,
        dv_col="value",
        factor_col="condition",
        subject_col="subject",
    )
    zero_row = zero_result.iloc[0]
    assert zero_row["status_code"] == "zero_variance_zero_difference"
    assert zero_row["cohens_dz"] == 0.0
    assert zero_row["ci95_low"] == 0.0
    assert zero_row["ci95_high"] == 0.0
    assert np.isnan(zero_row["p_raw"])

    nonzero = zero.copy()
    nonzero.loc[nonzero["condition"] == "B", "value"] -= 0.1
    _, nonzero_result = run_posthoc_pairwise_tests(
        nonzero,
        dv_col="value",
        factor_col="condition",
        subject_col="subject",
    )
    nonzero_row = nonzero_result.iloc[0]
    assert nonzero_row["status_code"] == "zero_variance_nonzero_difference"
    assert np.isnan(nonzero_row["cohens_dz"])
    assert nonzero_row["ci95_low"] == pytest.approx(0.1)
    assert nonzero_row["ci95_high"] == pytest.approx(0.1)
    assert not np.isinf(
        nonzero_result[["cohens_dz", "ci95_low", "ci95_high"]]
        .to_numpy(dtype=float)
    ).any()


def test_default_pairwise_keeps_legacy_bh_aliases_and_adds_provenance() -> None:
    data = _interaction_data()
    one_roi = data[data["roi"] == "R1"]

    _, result = run_posthoc_pairwise_tests(
        one_roi,
        dv_col="value",
        factor_col="condition",
        subject_col="subject",
    )

    assert {"p_value", "p_fdr_bh", "Significant"}.issubset(result.columns)
    np.testing.assert_allclose(result["p_value"], result["p_raw"])
    np.testing.assert_allclose(result["p_fdr_bh"], result["p_adjusted"])
    assert result["Significant"].equals(result["reject_adjusted"])
    assert set(result["followup_provenance"]) == {"exploratory_manual"}


def test_planned_contrast_uses_declared_family_and_preserves_p_corr_alias() -> None:
    rows: list[dict[str, object]] = []
    for index, subject in enumerate(("S1", "S2", "S3", "S4", "S5")):
        rows.extend(
            [
                {
                    "subject": subject,
                    "condition": "Category",
                    "roi": "R1",
                    "value": 1.0 + index * 0.20,
                },
                {
                    "subject": subject,
                    "condition": "Color 1",
                    "roi": "R1",
                    "value": 0.6 + index * 0.13,
                },
                {
                    "subject": subject,
                    "condition": "Color 2",
                    "roi": "R1",
                    "value": 0.7 + index * 0.12,
                },
            ]
        )

    _, result = run_planned_contrasts_category_vs_color(
        pd.DataFrame(rows),
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        category_condition="Category",
        color_conditions=("Color 1", "Color 2"),
    )

    assert len(result) == 1
    assert result.loc[0, "family_id"] == "planned_category_vs_color"
    assert result.loc[0, "adjustment_method"] == "holm"
    assert result.loc[0, "followup_provenance"] == "planned"
    assert result.loc[0, "p_corr"] == result.loc[0, "p_adjusted"]
    assert result.loc[0, "Significant"] == result.loc[0, "reject_adjusted"]
    assert "p_fdr_bh" not in result.columns

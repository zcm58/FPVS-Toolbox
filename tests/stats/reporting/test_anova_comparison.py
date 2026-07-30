from __future__ import annotations

import pandas as pd

from Tools.Stats.reporting.inference.anova_comparison import (
    build_anova_lmm_decision_comparison,
)
from Tools.Stats.reporting.inference_report import (
    build_native_inference_report,
)


def _inventory() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "test_id": "condition_roi_interaction",
                "role": "primary",
                "reportable": True,
                "significant": False,
            },
            {
                "test_id": "anova_compatibility::condition_roi_interaction",
                "role": "compatibility",
                "reportable": True,
                "significant": True,
            },
        ]
    )


def test_single_comparison_reports_decision_disagreement_without_validation() -> None:
    result = build_anova_lmm_decision_comparison("single", _inventory())

    assert len(result) == 1
    row = result.iloc[0]
    assert row["related_lmm_question"] == "condition_roi_interaction"
    assert row["anova_decision"] == "supported"
    assert row["lmm_decision"] == "not supported"
    assert row["decision_concordance"] == "different decisions"
    assert "does not validate" in row["interpretation"]


def test_multi_collapsed_response_cell_has_no_one_row_lmm_mapping() -> None:
    inventory = _inventory().iloc[[1]].copy()
    inventory.loc[:, "test_id"] = "anova_compatibility::response_cell"

    result = build_anova_lmm_decision_comparison("multi", inventory)

    assert result.loc[0, "related_lmm_question"] == "none"
    assert result.loc[0, "decision_concordance"] == (
        "no direct one-row comparison"
    )
    assert "no one-row counterpart" in result.loc[0, "relationship"]


def test_multi_compatibility_is_between_group_secondary_in_full_report() -> None:
    compatibility = pd.DataFrame(
        [
            {
                "test_id": "anova_compatibility::group",
                "effect_id": "group",
                "test_label": (
                    "Group x response-cell mixed-ANOVA compatibility check: Group"
                ),
                "test_method": (
                    "Group x response-cell mixed-ANOVA compatibility check"
                ),
                "estimand": "Broad response-surface omnibus F effect",
                "compatibility_scope": "between_group_response_surface",
                "compatibility_only": True,
                "inference_role": "compatibility",
                "headline_eligible": False,
                "reportable": True,
                "p_adjusted": 0.001,
                "reject_adjusted": True,
                "family_id": "anova_compatibility_effects",
                "adjustment_method": "holm",
            }
        ]
    )
    lmm = pd.DataFrame(
        [
            {
                "effect_id": "any_group_related",
                "effect_label": "Any group-related effect (joint block)",
                "inference_role": "primary",
                "headline_eligible": True,
                "reportable": True,
                "p_adjusted": 0.40,
                "reject_adjusted": False,
            }
        ]
    )

    bundle = build_native_inference_report(
        "multi",
        step_payloads={
            "Omnibus LRT": lmm,
            "ANOVA Compatibility": compatibility,
        },
    )
    row = bundle.test_inventory.loc[
        bundle.test_inventory["role"].eq("compatibility")
    ].iloc[0]

    assert row["section"] == "between_group"
    assert bool(row["headline_eligible"]) is False
    assert row["headline_reason"] == "anova_compatibility_is_secondary"
    assert "ANOVA-LMM Decision Comparison" in bundle.named_frames
    comparison = bundle.named_frames["ANOVA-LMM Decision Comparison"]
    assert comparison.loc[0, "decision_concordance"] == "different decisions"
    assert "no clear overall difference" in bundle.at_a_glance

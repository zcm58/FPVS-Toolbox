"""Descriptive decision comparison between ANOVA checks and primary LMM tests."""

from __future__ import annotations

import pandas as pd


_SINGLE_RELATIONSHIPS = {
    "condition": (
        "condition_related_block",
        "Related to the hierarchy-preserving LMM Condition block; the tests "
        "are not numerically identical.",
    ),
    "roi": (
        "roi_related_block",
        "Related to the hierarchy-preserving LMM ROI block; the tests are not "
        "numerically identical.",
    ),
    "condition_roi_interaction": (
        "condition_roi_interaction",
        "Closest compatibility counterpart to the LMM Condition x ROI "
        "interaction, with different estimation/reference assumptions.",
    ),
}
_MULTI_RELATIONSHIPS = {
    "group": (
        "any_group_related",
        "Related to the joint LMM group-related question, not a pure or "
        "numerically identical LMM group main-effect test.",
    ),
    "response_cell": (
        None,
        "The collapsed response-cell effect has no one-row counterpart in the "
        "factorial LMM.",
    ),
    "group_response_cell_interaction": (
        "any_group_related",
        "Related broadly to the joint LMM group-pattern question; it does not "
        "separate Group x Condition, Group x ROI, and the three-way term.",
    ),
}


def _decision(row: pd.Series | None) -> str:
    if row is None:
        return "not directly mapped"
    if not bool(row.get("reportable")) or pd.isna(row.get("significant")):
        return "not reportable"
    return "supported" if bool(row["significant"]) else "not supported"


def build_anova_lmm_decision_comparison(
    mode: str,
    inventory: pd.DataFrame,
) -> pd.DataFrame:
    """Compare corrected decisions descriptively, never as model validation."""

    columns = [
        "anova_effect",
        "anova_decision",
        "related_lmm_question",
        "lmm_decision",
        "decision_concordance",
        "relationship",
        "interpretation",
    ]
    if inventory.empty:
        return pd.DataFrame(columns=columns)
    compatibility = inventory.loc[
        inventory["role"].eq("compatibility")
        & inventory["test_id"].astype(str).str.startswith(
            "anova_compatibility::"
        )
    ]
    if compatibility.empty:
        return pd.DataFrame(columns=columns)
    relationships = (
        _SINGLE_RELATIONSHIPS if mode == "single" else _MULTI_RELATIONSHIPS
    )
    rows: list[dict[str, object]] = []
    for _, anova_row in compatibility.iterrows():
        effect = str(anova_row["test_id"]).split("::", maxsplit=1)[-1]
        target_id, relationship = relationships.get(
            effect,
            (
                None,
                "No prespecified LMM relationship was declared for this effect.",
            ),
        )
        lmm_row: pd.Series | None = None
        if target_id is not None:
            candidates = inventory.loc[
                inventory["test_id"].astype(str).eq(target_id)
                & ~inventory["role"].eq("compatibility")
            ]
            if not candidates.empty:
                lmm_row = candidates.iloc[0]
        anova_decision = _decision(anova_row)
        lmm_decision = _decision(lmm_row)
        concordance = (
            "no direct one-row comparison"
            if lmm_row is None
            else (
                "same decision"
                if anova_decision == lmm_decision
                else "different decisions"
            )
        )
        rows.append(
            {
                "anova_effect": effect,
                "anova_decision": anova_decision,
                "related_lmm_question": target_id or "none",
                "lmm_decision": lmm_decision,
                "decision_concordance": concordance,
                "relationship": relationship,
                "interpretation": (
                    "Decision agreement is descriptive compatibility evidence "
                    "only; ANOVA does not validate or replace the primary LMM."
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


__all__ = ["build_anova_lmm_decision_comparison"]

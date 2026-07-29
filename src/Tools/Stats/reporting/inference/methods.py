"""Correction-family and method-inventory reporting."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from Tools.Stats.reporting.inference.frames import first_nonmissing


def human_correction(value: object | None) -> str:
    """Return the correction actually exported, never a hard-coded default."""

    if value is None or bool(pd.isna(value)) or not str(value).strip():
        return "not specified"
    normalized = str(value).strip().casefold().replace("-", "_").replace(" ", "_")
    labels = {
        "holm": "Holm family-wise error correction",
        "fdr_bh": "Benjamini–Hochberg false-discovery-rate correction",
        "bh": "Benjamini–Hochberg false-discovery-rate correction",
        "none": "no multiplicity adjustment",
        "raw": "no multiplicity adjustment",
        "greenhouse_geisser": "Greenhouse–Geisser sphericity correction",
        "none_sphericity_met": "uncorrected p-value (sphericity met)",
        "none_two_level_effect": "uncorrected p-value (two-level effect)",
        "single_step_max_abs_t_fwer": (
            "single-step max-|t| family-wise error correction"
        ),
    }
    return labels.get(normalized, str(value).replace("_", " "))


def correction_family_frame(
    inventory: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Combine declared and observed family/correction metadata."""

    rows: list[dict[str, object]] = []
    for frame_name, frame in frames.items():
        if "correction families" not in frame_name.casefold():
            continue
        for _, row in frame.iterrows():
            rows.append(
                {
                    "family_id": first_nonmissing(row, ("family_id",)),
                    "family_label": first_nonmissing(row, ("family_label",)),
                    "adjustment_method": first_nonmissing(
                        row, ("adjustment_method",)
                    ),
                    "alpha": first_nonmissing(row, ("alpha",)),
                    "family_size": first_nonmissing(row, ("family_size",)),
                    "n_inventory_tests": pd.NA,
                    "source": frame_name,
                }
            )
    if not inventory.empty:
        family_rows = inventory[
            inventory["adjustment_method"].notna()
            | (
                inventory["family_id"].notna()
                & inventory["p_value_used"].notna()
            )
        ]
        group_columns = [
            "family_id",
            "family_label",
            "adjustment_method",
            "alpha",
        ]
        for keys, group in family_rows.groupby(
            group_columns,
            dropna=False,
            sort=True,
        ):
            family_id, family_label, method, family_alpha = keys
            family_sizes = pd.to_numeric(
                group["family_size"], errors="coerce"
            ).dropna()
            rows.append(
                {
                    "family_id": family_id,
                    "family_label": family_label,
                    "adjustment_method": method,
                    "alpha": family_alpha,
                    "family_size": (
                        int(family_sizes.max())
                        if not family_sizes.empty
                        else pd.NA
                    ),
                    "n_inventory_tests": len(group),
                    "source": "; ".join(
                        sorted(set(group["source_frame"].astype(str)))
                    ),
                }
            )
    result = pd.DataFrame(
        rows,
        columns=[
            "family_id",
            "family_label",
            "adjustment_method",
            "alpha",
            "family_size",
            "n_inventory_tests",
            "source",
        ],
    )
    if result.empty:
        return result
    return result.drop_duplicates(
        subset=["family_id", "family_label", "adjustment_method", "alpha"],
        keep="last",
    ).reset_index(drop=True)


def assumptions_for(method: str) -> str:
    """Describe the assumption set appropriate to the named method."""

    lowered = method.casefold()
    if "welch" in lowered:
        return (
            "independent participants between groups; finite observations; "
            "group variances may differ"
        )
    if "repeated" in lowered or "anova" in lowered:
        return (
            "independent participants; approximately normal within-subject "
            "contrasts; sphericity for effects with more than two levels"
        )
    if "mixed" in lowered or "likelihood" in lowered or "wald" in lowered:
        return (
            "correct fixed/random-effects structure; approximately normal "
            "conditional residuals; asymptotic reference distribution"
        )
    if "wilcoxon" in lowered or "friedman" in lowered:
        return "independent participants and an interpretable rank-based estimand"
    if "permutation" in lowered or "max-" in lowered:
        return "exchangeability under the tested null at the participant level"
    if "one-sample" in lowered or "response" in lowered or "trimmed" in lowered:
        return (
            "independent participants; the sampling distribution of the "
            "participant-level response estimate is adequately represented"
        )
    return "assumptions depend on the declared statistical method"


def methods_frame(inventory: pd.DataFrame) -> pd.DataFrame:
    """Build a deduplicated methods/assumptions/estimand table."""

    columns = [
        "section",
        "method",
        "purpose",
        "estimand",
        "alternative",
        "profile",
        "role",
        "followup_provenance",
        "n",
        "p_value_column",
        "adjustment_method",
        "family_id",
        "family_size",
        "formula",
        "assumptions",
        "assumption_status",
        "headline_eligible",
        "provenance",
    ]
    if inventory.empty:
        return pd.DataFrame(columns=columns)
    rows = []
    for _, row in inventory.iterrows():
        section = str(row["section"])
        purpose = {
            "response_detection": "test whether the summed response differs from zero",
            "within_subject": "test Condition/ROI variation within participants",
            "between_group": "test differences involving canonical groups",
        }.get(section, "declared inferential test")
        rows.append(
            {
                "section": section,
                "method": row["method"],
                "purpose": purpose,
                "estimand": row["estimand"],
                "alternative": row["alternative"],
                "profile": row["profile"],
                "role": row["role"],
                "followup_provenance": row["followup_provenance"],
                "n": row["n"],
                "p_value_column": row["p_value_column"],
                "adjustment_method": row["adjustment_method"],
                "family_id": row["family_id"],
                "family_size": row["family_size"],
                "formula": row["formula"],
                "assumptions": assumptions_for(str(row["method"])),
                "assumption_status": row["assumption_status"],
                "headline_eligible": row["headline_eligible"],
                "provenance": row["harmonic_provenance"],
            }
        )
    return pd.DataFrame(rows, columns=columns).drop_duplicates().reset_index(drop=True)


__all__ = [
    "correction_family_frame",
    "human_correction",
    "methods_frame",
]

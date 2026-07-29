"""Concise, non-expert summary for native Stats inference."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd


def _compact_result_labels(
    rows: pd.DataFrame,
    *,
    maximum: int = 2,
) -> str:
    """Name a small number of significant rows without recreating the inventory."""

    rendered = [
        str(row["test_label"])
        for _, row in rows.head(maximum).iterrows()
    ]
    remaining = len(rows) - len(rendered)
    if remaining > 0:
        rendered.append(f"{remaining} more")
    return "; ".join(rendered)


def _primary_question_line(
    inventory: pd.DataFrame,
    *,
    section: str,
    heading: str,
    positive_phrase: str,
    negative_phrase: str,
    unavailable_phrase: str,
) -> str:
    """Summarize one scientific question in one line."""

    section_rows = inventory[inventory["section"].eq(section)]
    if section_rows.empty:
        return f"- {heading}: {unavailable_phrase}."
    headline = section_rows[
        section_rows["headline_eligible"].eq(True)
        & section_rows["role"].eq("primary")
    ]
    eligible = headline[
        headline["reportable"].eq(True)
        & headline["p_value_used"].notna()
    ]
    if eligible.empty:
        return f"- {heading}: {unavailable_phrase}."
    significant = eligible[eligible["significant"].eq(True)]
    if significant.empty:
        return f"- {heading}: {negative_phrase}."
    details = _compact_result_labels(significant)
    if len(eligible) == 1:
        return f"- {heading}: {positive_phrase}: {details}."
    return (
        f"- {heading}: {positive_phrase} in {len(significant)} of "
        f"{len(eligible)} planned tests: {details}."
    )


def _between_group_lines(inventory: pd.DataFrame) -> list[str]:
    """Summarize the joint group test and the corrected cell-test family."""

    rows = inventory[
        inventory["section"].eq("between_group")
        & inventory["headline_eligible"].eq(True)
        & inventory["role"].eq("primary")
        & inventory["reportable"].eq(True)
        & inventory["p_value_used"].notna()
    ]
    if rows.empty:
        return [
            "- Groups: no primary conclusion was available."
        ]

    lines: list[str] = []
    labels = rows["test_label"].astype(str)
    joint = rows[
        labels.str.casefold().str.startswith("any group-related")
    ]
    if joint.empty:
        lines.append(
            "- Groups overall: no primary conclusion was available."
        )
    else:
        row = joint.iloc[0]
        conclusion = (
            "the primary analysis found evidence of an overall difference"
            if bool(row["significant"])
            else "no clear overall difference was found"
        )
        lines.append(f"- Groups overall: {conclusion}.")

    cell_rows = rows[rows["family_id"].astype(str).eq("group_core_cells")]
    if not cell_rows.empty:
        significant = cell_rows[cell_rows["significant"].eq(True)]
        if significant.empty:
            lines.append(
                "- Group differences by condition and brain region: none of "
                "the planned comparisons showed a clear difference."
            )
        else:
            lines.append(
                "- Group differences by condition and brain region: "
                f"{len(significant)} of {len(cell_rows)} planned comparisons "
                "showed evidence of a difference: "
                f"{_compact_result_labels(significant)}."
            )
    return lines


def _sensitivity_line(inventory: pd.DataFrame) -> str | None:
    """Collapse significant secondary checks into one plain-language caution."""

    rows = inventory[
        inventory["headline_eligible"].eq(True)
        & inventory["role"].eq("sensitivity")
        & inventory["reportable"].eq(True)
        & inventory["p_value_used"].notna()
    ]
    significant = rows[rows["significant"].eq(True)]
    if significant.empty:
        return None
    primary_significant = inventory[
        inventory["headline_eligible"].eq(True)
        & inventory["role"].eq("primary")
        & inventory["reportable"].eq(True)
        & inventory["significant"].eq(True)
    ]
    if primary_significant.empty:
        return (
            "- Secondary checks: some additional analyses suggested possible "
            "effects, but the primary analysis did not confirm them."
        )
    return (
        "- Secondary checks: some additional analyses also suggested possible "
        "effects, but these are not primary findings."
    )


def _item_count(value: object) -> int:
    return len(
        [
            item
            for item in str(value or "").split(";")
            if item.strip()
        ]
    )


def _concise_design_line(design: Mapping[str, object]) -> str | None:
    """Condense design coverage to one at-a-glance sentence."""

    frozen_n = design.get("n")
    if frozen_n is None:
        return None
    scope = str(design.get("analysis_scope") or "").strip().casefold()
    if scope == "available_case":
        contributing = design.get("n_contributing")
        observed = design.get("n_observed_rows")
        retained_count = _item_count(design.get("retained_conditions"))
        participant_text = (
            f"{contributing} of {frozen_n} participants"
            if contributing is not None
            else f"{frozen_n} participants"
        )
        observed_text = (
            ""
            if observed is None
            else f" contributed {observed} finite observations"
        )
        condition_text = (
            ""
            if not retained_count
            else f" across {retained_count} conditions"
        )
        return (
            f"Data: {participant_text}{observed_text}{condition_text} "
            "(available-case LMM; missing values were not filled in)."
        )

    complete_count = _item_count(design.get("complete_conditions"))
    excluded_count = _item_count(design.get("excluded_conditions"))
    condition_text = (
        ""
        if not complete_count
        else (
            f" and {complete_count} complete "
            f"{'condition' if complete_count == 1 else 'conditions'}"
        )
    )
    exclusion_text = (
        ""
        if not excluded_count
        else (
            f"; {excluded_count} incomplete "
            f"{'condition was' if excluded_count == 1 else 'conditions were'} "
            "excluded"
        )
    )
    return (
        f"Data: {frozen_n} participants{condition_text}"
        f"{exclusion_text}."
    )


def at_a_glance_text(
    mode: str,
    inventory: pd.DataFrame,
    limitations: pd.DataFrame,
    design: Mapping[str, object],
    export_path: str | Path | None = None,
) -> str:
    """Build a short interpretation for a non-expert reader."""

    mode_label = (
        "Single-group summary"
        if mode == "single"
        else "Group-comparison summary"
    )
    adaptive_harmonics = limitations["code"].eq(
        "adaptive_harmonic_selection"
    ).any()
    response_unavailable = (
        "no primary claim was made because the harmonics were selected "
        "from these same data"
        if adaptive_harmonics
        else "no primary conclusion was available"
    )
    lines = [mode_label, ""]
    lines.append(
        _primary_question_line(
            inventory,
            section="response_detection",
            heading="Response",
            positive_phrase=(
                "the primary analysis found evidence of a response"
            ),
            negative_phrase=(
                "the primary analysis did not find clear evidence of a response"
            ),
            unavailable_phrase=response_unavailable,
        )
    )
    lines.append(
        _primary_question_line(
            inventory,
            section="within_subject",
            heading="Conditions and brain regions",
            positive_phrase=(
                "the primary analysis found evidence that responses differed"
            ),
            negative_phrase=(
                "no clear differences were found in the primary analysis"
            ),
            unavailable_phrase="no primary conclusion was available",
        )
    )
    if mode != "single":
        lines.extend(_between_group_lines(inventory))
    sensitivity = _sensitivity_line(inventory)
    if sensitivity is not None:
        lines.append(sensitivity)

    design_line = _concise_design_line(design)
    if design_line is not None:
        lines.extend(["", design_line])

    lines.append("")
    if mode == "multi":
        significant_primary_group = inventory[
            inventory["section"].eq("between_group")
            & inventory["role"].eq("primary")
            & inventory["headline_eligible"].eq(True)
            & inventory["reportable"].eq(True)
            & inventory["significant"].eq(True)
        ]
        if significant_primary_group.empty:
            lines.append(
                "Note: not finding a clear group difference does not prove "
                "that the groups are identical."
            )
        lines.append(
            "Group findings describe associations, not causes or diagnoses."
        )
    else:
        lines.append(
            "Note: not finding a clear difference does not prove that no "
            "difference exists."
        )
    workbook_name = (
        "not yet saved"
        if export_path is None
        else Path(export_path).name
    )
    lines.append(f"Full statistical details: {workbook_name}.")
    return "\n".join(lines)


__all__ = ["at_a_glance_text"]

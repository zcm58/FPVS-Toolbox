"""Short, question-led summary for Standard FPVS Screening."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd


LMM_CONTRAST_METHOD = "LMM-derived model-estimated contrast"


def _compact_result_labels(
    rows: pd.DataFrame,
    *,
    maximum: int = 2,
) -> str:
    """Name a few supported rows without recreating the test inventory."""

    rendered = [
        str(row["test_label"])
        for _, row in rows.head(maximum).iterrows()
    ]
    remaining = len(rows) - len(rendered)
    if remaining > 0:
        rendered.append(f"{remaining} more")
    return "; ".join(rendered)


def _reportable_headline_rows(
    inventory: pd.DataFrame,
    *,
    section: str,
) -> pd.DataFrame:
    rows = inventory[inventory["section"].eq(section)]
    return rows[
        rows["headline_eligible"].eq(True)
        & rows["reportable"].eq(True)
        & rows["p_value_used"].notna()
        & ~rows["role"].eq("compatibility")
    ]


def _response_line(
    inventory: pd.DataFrame,
    *,
    adaptive_harmonics: bool,
    mode: str,
) -> str:
    """Summarize one-sided positive oddball-response evidence."""

    rows = _reportable_headline_rows(
        inventory,
        section="response_detection",
    )
    primary = rows[rows["role"].eq("primary")]
    if adaptive_harmonics:
        eligible = primary if not primary.empty else rows
        heading = (
            "Exploratory positive oddball response "
            "(harmonics selected from this sample)"
        )
    elif not primary.empty:
        eligible = primary
        heading = "Positive oddball response"
    else:
        exploratory = rows[rows["role"].eq("exploratory")]
        if exploratory.empty:
            eligible = primary
            heading = "Positive oddball response"
        else:
            eligible = exploratory
            heading = "Exploratory positive oddball response"

    if eligible.empty:
        if adaptive_harmonics:
            return (
                f"- {heading}: no usable response conclusion was available; "
                "the same-sample check remains exploratory."
            )
        return f"- {heading}: no primary conclusion was available."

    significant = eligible[eligible["significant"].eq(True)]
    cell_label = (
        "Group x Condition x ROI"
        if mode == "multi"
        else "Condition x ROI"
    )
    if significant.empty:
        return (
            f"- {heading}: no clear evidence was found in any of "
            f"{len(eligible)} {cell_label} tests."
        )
    return (
        f"- {heading}: evidence was found in {len(significant)} of "
        f"{len(eligible)} {cell_label} tests: "
        f"{_compact_result_labels(significant)}."
    )


def _primary_lmm_rows(inventory: pd.DataFrame) -> pd.DataFrame:
    """Select primary Condition/ROI likelihood-ratio model questions."""

    rows = _reportable_headline_rows(
        inventory,
        section="within_subject",
    )
    source = rows["source_frame"].astype(str).str.casefold()
    method = rows["method"].astype(str).str.casefold()
    return rows[
        rows["role"].eq("primary")
        & (
            source.str.contains("mixed model lrt", regex=False)
            | method.str.contains("likelihood-ratio", regex=False)
        )
        & ~rows["method"].astype(str).eq(LMM_CONTRAST_METHOD)
    ]


def _primary_lmm_line(lmm_rows: pd.DataFrame) -> str:
    if lmm_rows.empty:
        return (
            "- Condition/ROI pattern (primary LMM): no primary model "
            "conclusion was available."
        )
    significant = lmm_rows[lmm_rows["significant"].eq(True)]
    if significant.empty:
        return (
            "- Condition/ROI pattern (primary LMM): no clear evidence that "
            "responses varied across conditions or ROIs."
        )
    return (
        "- Condition/ROI pattern (primary LMM): evidence that responses "
        "varied across conditions and/or ROIs: "
        f"{_compact_result_labels(significant)}."
    )


def _interaction_is_supported(lmm_rows: pd.DataFrame) -> bool:
    labels = lmm_rows["test_label"].astype(str).str.casefold()
    interaction = (
        labels.str.contains("condition", regex=False)
        & labels.str.contains("roi", regex=False)
        & lmm_rows["p_value_source"].eq("multiplicity_adjusted")
        & lmm_rows["family_id"].astype(str).eq("omnibus_effects_strict")
        & (
            labels.str.contains("interaction", regex=False)
            | labels.str.contains("*", regex=False)
        )
    )
    return bool(
        lmm_rows.loc[interaction, "significant"].eq(True).any()
    )


def _interaction_explanation_line(
    inventory: pd.DataFrame,
    *,
    lmm_rows: pd.DataFrame,
) -> str | None:
    """Explain only a supported Condition x ROI interaction."""

    if not _interaction_is_supported(lmm_rows):
        return None
    rows = _reportable_headline_rows(
        inventory,
        section="within_subject",
    )
    contrasts = rows[
        rows["role"].eq("primary")
        & rows["method"].astype(str).eq(LMM_CONTRAST_METHOD)
        & rows["family_id"].astype(str).eq("planned_contrasts")
    ]
    if contrasts.empty:
        return None
    significant = contrasts[contrasts["significant"].eq(True)]
    heading = f"Interaction explanation ({LMM_CONTRAST_METHOD})"
    if significant.empty:
        return (
            f"- {heading}: the interaction was supported, but none of the "
            f"{len(contrasts)} planned comparisons clearly explained where "
            "the differences lay."
        )
    return (
        f"- {heading}: {len(significant)} of {len(contrasts)} planned "
        "comparisons helped explain the pattern: "
        f"{_compact_result_labels(significant)}."
    )


def _direct_group_cell_line(inventory: pd.DataFrame) -> str:
    rows = _reportable_headline_rows(
        inventory,
        section="between_group",
    )
    cells = rows[
        rows["role"].eq("primary")
        & rows["family_id"].astype(str).eq("group_core_cells")
        & rows["method"].astype(str).eq(LMM_CONTRAST_METHOD)
    ]
    heading = (
        "Direct Group A-B cell differences "
        f"({LMM_CONTRAST_METHOD})"
    )
    if cells.empty:
        return f"- {heading}: no primary cell comparison was available."
    significant = cells[cells["significant"].eq(True)]
    if significant.empty:
        return (
            f"- {heading}: none of the {len(cells)} planned Condition x ROI "
            "comparisons showed a clear difference."
        )
    return (
        f"- {heading}: {len(significant)} of {len(cells)} planned Condition x "
        "ROI comparisons showed a clear difference: "
        f"{_compact_result_labels(significant)}."
    )


def _joint_group_pattern_line(inventory: pd.DataFrame) -> str:
    rows = _reportable_headline_rows(
        inventory,
        section="between_group",
    )
    joint = rows[
        rows["role"].eq("primary")
        & rows["test_label"]
        .astype(str)
        .str.casefold()
        .str.startswith("any group-related")
    ]
    if joint.empty:
        return (
            "- Broader joint group pattern (primary LMM): no primary joint "
            "group conclusion was available."
        )
    if bool(joint.iloc[0]["significant"]):
        return (
            "- Broader joint group pattern (primary LMM): the joint test "
            "found evidence of a broader group-related response pattern."
        )
    return (
        "- Broader joint group pattern (primary LMM): the joint test found "
        "no clear overall difference."
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
    """Condense design coverage to one sentence."""

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
    """Answer the fixed Standard FPVS Screening questions concisely."""

    mode_label = (
        "single group"
        if mode == "single"
        else "two-group comparison"
    )
    limitation_codes = limitations.get(
        "code",
        pd.Series(dtype=object),
    )
    adaptive_harmonics = limitation_codes.eq(
        "adaptive_harmonic_selection"
    ).any()

    lines = [f"Standard FPVS Screening: {mode_label}", ""]
    lines.append(
        _response_line(
            inventory,
            adaptive_harmonics=adaptive_harmonics,
            mode=mode,
        )
    )
    lmm_rows = _primary_lmm_rows(inventory)
    lines.append(_primary_lmm_line(lmm_rows))
    interaction_line = _interaction_explanation_line(
        inventory,
        lmm_rows=lmm_rows,
    )
    if interaction_line is not None:
        lines.append(interaction_line)
    if mode != "single":
        lines.extend(
            [
                _direct_group_cell_line(inventory),
                _joint_group_pattern_line(inventory),
            ]
        )

    design_line = _concise_design_line(design)
    if design_line is not None:
        lines.extend(["", design_line])

    lines.extend(
        [
            "",
            (
                "Screening boundary: this is a first-round FPVS screen, not "
                "the final project-specific statistical model."
            ),
        ]
    )
    if mode == "multi":
        lines.append(
            "Caution: non-significant group results do not prove equivalence; "
            "group findings describe associations, not causes or diagnoses."
        )
    else:
        lines.append(
            "Caution: a non-significant result does not prove that a response "
            "or effect is absent."
        )
    workbook_name = (
        "not yet saved"
        if export_path is None
        else Path(export_path).name
    )
    lines.append(f"Full statistical details: {workbook_name}.")
    return "\n".join(lines)


__all__ = ["at_a_glance_text"]

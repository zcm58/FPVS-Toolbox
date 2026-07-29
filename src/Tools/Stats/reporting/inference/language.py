"""Non-expert findings language and detailed methods narrative."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from Tools.Stats.reporting.inference.bundle import (
    ADAPTIVE_HARMONIC_WARNING,
    METHOD_DEPENDENT_PHRASE,
)
from Tools.Stats.reporting.inference.frames import finite_float
from Tools.Stats.reporting.inference.methods import human_correction


def format_number(value: object, digits: int = 3) -> str:
    """Format finite statistics compactly without masking unavailable values."""

    number = finite_float(value)
    if number is None:
        return "not available"
    if abs(number) < 0.001 and number != 0.0:
        return f"{number:.2e}"
    return f"{number:.{digits}f}"


def correction_clause(row: pd.Series) -> str:
    """Describe the row's actual p-value/correction contract."""

    method = human_correction(row.get("adjustment_method"))
    family = row.get("family_id")
    p_column = str(row.get("p_value_column") or "").casefold()
    if p_column in {"p_adjusted", "p_adjusted_max_t"}:
        if family is not None and not bool(pd.isna(family)) and str(family).strip():
            return f"{method}, family {family}"
        return method
    if p_column == "p_reported":
        return method
    if str(row.get("p_value_source")) == "likelihood_ratio":
        return "asymptotic likelihood-ratio p-value"
    return "unadjusted p-value" if method == "not specified" else method


def estimate_clause(row: pd.Series) -> str:
    """Report estimate, interval, and effect size only when exported."""

    parts: list[str] = []
    estimate = finite_float(row.get("estimate"))
    low = finite_float(row.get("ci_low"))
    high = finite_float(row.get("ci_high"))
    if estimate is not None:
        parts.append(f"estimate={format_number(estimate)}")
    if low is not None and high is not None:
        parts.append(f"95% CI [{format_number(low)}, {format_number(high)}]")
    effect = finite_float(row.get("effect_size"))
    if effect is not None:
        label = row.get("effect_size_name") or "effect size"
        parts.append(f"{label}={format_number(effect)}")
    return "; ".join(parts)


def _role_prefix(row: pd.Series) -> str:
    role = str(row["role"])
    if role == "sensitivity":
        return "Sensitivity only — "
    if role == "exploratory":
        return "Exploratory — "
    return ""


def _detail_clause(row: pd.Series) -> str:
    detail = f" ({correction_clause(row)}; p={format_number(row['p_value_used'], 4)}"
    estimate = estimate_clause(row)
    if estimate:
        detail += f"; {estimate}"
    return detail + ")."


def _between_group_line(
    row: pd.Series,
    *,
    prefix: str,
    label: str,
    detail: str,
) -> str:
    if label.casefold().startswith("any group-related"):
        if bool(row["significant"]):
            core = "the joint block of all group-containing terms improved model fit"
        else:
            core = (
                "the joint block did not provide evidence that group-containing "
                "terms improved model fit"
            )
        return (
            f"{prefix}{label}: {core}{detail} This is a joint group-related "
            "test, not a pure group main-effect test."
        )
    direction = ""
    estimate = finite_float(row["estimate"])
    if " - " in label and estimate is not None:
        if estimate > 0:
            direction = " The signed estimate is positive in the stated A - B direction."
        elif estimate < 0:
            direction = " The signed estimate is negative in the stated A - B direction."
        else:
            direction = " The signed estimate is zero in the stated A - B direction."
    if bool(row["significant"]):
        return (
            f"{prefix}{label}: evidence of a between-group difference was found"
            f"{detail}{direction}"
        )
    return (
        f"{prefix}{label}: the analysis did not provide evidence of a "
        f"between-group difference{detail} This does not establish group "
        f"equivalence.{direction}"
    )


def finding_line(row: pd.Series) -> str:
    """Translate one inventory row without treating non-significance as no effect."""

    prefix = _role_prefix(row)
    label = str(row["test_label"])
    if not bool(row["reportable"]) or pd.isna(row["p_value_used"]):
        return (
            f"{prefix}{label}: no primary conclusion was drawn because the "
            f"test was {row['status']}."
        )
    detail = _detail_clause(row)
    significant = bool(row["significant"])
    if row["section"] == "response_detection":
        if significant:
            return f"{prefix}{label}: evidence of a response was found{detail}"
        return (
            f"{prefix}{label}: the analysis did not provide evidence of a "
            f"response{detail} This does not prove that the response is absent."
        )
    if row["section"] == "between_group":
        return _between_group_line(
            row,
            prefix=prefix,
            label=label,
            detail=detail,
        )
    if significant:
        return f"{prefix}{label}: evidence of a within-subject effect was found{detail}"
    return (
        f"{prefix}{label}: the analysis did not provide evidence of a "
        f"within-subject effect{detail} This does not prove that the effect is absent."
    )


def _design_note_lines(
    design: Mapping[str, object],
    *,
    bullets: bool,
) -> list[str]:
    """Describe complete-core or available-case coverage without ambiguity."""

    prefix = "- " if bullets else ""
    scope = str(design.get("analysis_scope") or "").strip().casefold()
    if scope != "available_case":
        lines: list[str] = []
        if design.get("n") is not None:
            lines.append(
                f"{prefix}The frozen analysis cohort contained "
                f"N={design['n']} participants."
            )
        complete = str(design.get("complete_conditions") or "").strip()
        if complete:
            lines.append(
                f"{prefix}Conditions retained for the shared analysis: {complete}."
            )
        excluded = str(design.get("excluded_conditions") or "").strip()
        if excluded:
            lines.append(
                f"{prefix}Conditions excluded for incomplete shared coverage: "
                f"{excluded}."
            )
        coverage_note = str(design.get("coverage_note") or "").strip()
        if coverage_note:
            lines.append(f"{prefix}{coverage_note}")
        return lines

    lines = [
        (
            f"{prefix}Analysis scope: available-case linear mixed model using "
            "finite observed rows only."
        )
    ]
    frozen_n = design.get("n")
    contributing_n = design.get("n_contributing")
    if frozen_n is not None and contributing_n is not None:
        lines.append(
            f"{prefix}The cohort was frozen at N={frozen_n}; "
            f"N={contributing_n} participant(s) contributed at least one "
            "finite retained observation."
        )
    elif frozen_n is not None:
        lines.append(
            f"{prefix}The frozen analysis cohort contained N={frozen_n} "
            "participants."
        )
    retained = str(design.get("retained_conditions") or "").strip()
    if retained:
        lines.append(
            f"{prefix}Conditions retained for available-case modeling: {retained}."
        )
    complete = str(design.get("complete_conditions") or "").strip()
    if complete:
        lines.append(
            f"{prefix}Fully complete conditions: {complete}."
        )
    partial = str(design.get("partial_conditions") or "").strip()
    if partial:
        lines.append(
            f"{prefix}Partially observed conditions retained in the model: "
            f"{partial}."
        )
    excluded = str(design.get("excluded_conditions") or "").strip()
    if excluded:
        lines.append(
            f"{prefix}Conditions excluded because a required fixed-effect cell "
            f"had no finite observation: {excluded}."
        )
    observed_rows = design.get("n_observed_rows")
    missing_retained = design.get("n_missing_retained")
    if observed_rows is not None:
        lines.append(
            f"{prefix}The model used {observed_rows} observed row(s)."
        )
    missing_text = (
        ""
        if missing_retained is None
        else f" ({missing_retained} retained cell(s) were missing or non-finite)"
    )
    lines.append(
        f"{prefix}No imputation was performed{missing_text}; a missing cell "
        "contributed no response value."
    )
    cell_n_note = str(design.get("cell_n_note") or "").strip()
    if cell_n_note:
        lines.append(f"{prefix}{cell_n_note}")
    lines.extend(
        [
            (
                f"{prefix}Repeated-measures ANOVA and paired post-hoc tests "
                "were intentionally omitted because they require complete "
                "within-participant cells."
            ),
            (
                f"{prefix}Available-case likelihood inference assumes the "
                "missingness is ignorable (missing at random, MAR) after "
                "conditioning on variables in the model."
            ),
            (
                f"{prefix}If exclusions still depend on an unobserved response "
                "after accounting for modeled variables (missing not at "
                "random, MNAR), estimates and p-values may be biased."
            ),
        ]
    )
    return lines


def at_a_glance_text(
    mode: str,
    inventory: pd.DataFrame,
    limitations: pd.DataFrame,
    design: Mapping[str, object],
    export_path: str | Path | None = None,
) -> str:
    """Build a three-question non-expert findings summary."""

    lines = [
        f"Analysis mode: {'single group' if mode == 'single' else 'multiple groups'}",
        "",
        "Response detection",
    ]
    for section, heading in (
        ("response_detection", None),
        ("within_subject", "Within-subject comparisons"),
        ("between_group", "Between-group comparisons"),
    ):
        if heading is not None:
            lines.extend(["", heading])
        all_section_rows = inventory[inventory["section"].eq(section)]
        section_rows = all_section_rows[
            all_section_rows["headline_eligible"].eq(True)
        ]
        if section == "between_group" and mode == "single":
            lines.append("- Not applicable in single-group mode.")
        elif section_rows.empty:
            if all_section_rows.empty:
                lines.append("- No result was available for this question.")
            else:
                lines.append(
                    "- Results are available in the detailed workbook, but no "
                    "adjusted/canonical result was eligible for a headline."
                )
        else:
            lines.extend(
                f"- {finding_line(row)}" for _, row in section_rows.iterrows()
            )
    lines.extend(["", "Design and interpretation notes"])
    lines.extend(_design_note_lines(design, bullets=True))
    if mode == "multi":
        lines.append(
            "- Between-group findings are associations in the analyzed sample; "
            "they do not establish causation or diagnostic validity."
        )
    if limitations["code"].eq("adaptive_harmonic_selection").any():
        lines.append(f"- {ADAPTIVE_HARMONIC_WARNING}")
    workbook_location = (
        "not yet selected"
        if export_path is None
        else str(Path(export_path))
    )
    lines.append(f"- Detailed workbook: {workbook_location}.")
    lines.append(
        f"- {METHOD_DEPENDENT_PHRASE} A finding describes evidence under the "
        "named test, correction, estimand, and assumptions."
    )
    return "\n".join(lines)


def _inventory_method_lines(inventory: pd.DataFrame) -> list[str]:
    if inventory.empty:
        return ["No inferential result rows were supplied."]
    lines = []
    for _, row in inventory.iterrows():
        details = [
            f"{row['test_label']} [{row['section']}; {row['role']}]",
            f"method={row['method']}",
            f"N={row['n']}" if pd.notna(row["n"]) else "N=not reported",
            f"status={row['status']}",
            f"p source={row['p_value_column'] or 'unavailable'}",
            f"correction={human_correction(row['adjustment_method'])}",
            f"headline eligibility={row['headline_eligible']}"
            f" ({row['headline_reason']})",
        ]
        if pd.notna(row["estimand"]):
            details.append(f"estimand={row['estimand']}")
        if pd.notna(row["alternative"]):
            details.append(f"alternative={row['alternative']}")
        if pd.notna(row["profile"]):
            details.append(f"profile={row['profile']}")
        if pd.notna(row["followup_provenance"]):
            details.append(
                f"follow-up provenance={row['followup_provenance']}"
            )
        if pd.notna(row["family_id"]):
            details.append(f"family={row['family_id']}")
        if pd.notna(row["family_size"]):
            details.append(f"family size={row['family_size']}")
        if pd.notna(row["assumption_status"]):
            details.append(f"assumption status={row['assumption_status']}")
        if pd.notna(row["canonical_reject"]):
            details.append(
                f"canonical reject={row['canonical_reject']}"
                f" ({row['reject_source']})"
            )
        if row["formula"]:
            details.append(f"formulae={row['formula']}")
        if pd.notna(row["estimate"]):
            details.append(estimate_clause(row))
        if pd.notna(row["harmonic_provenance"]):
            details.append(f"harmonic provenance={row['harmonic_provenance']}")
        lines.append("- " + "; ".join(item for item in details if item))
    return lines


def detailed_methods_text(
    mode: str,
    alpha: float,
    inventory: pd.DataFrame,
    methods: pd.DataFrame,
    limitations: pd.DataFrame,
    correction_families: pd.DataFrame,
    design: Mapping[str, object],
) -> str:
    """Build an auditable methods narrative with formulas, N, and caveats."""

    scope = str(design.get("analysis_scope") or "").strip().casefold()
    lines = [
        "Native inference methods and checks",
        "",
        (
            f"Mode: {'single group' if mode == 'single' else 'multiple groups'}; "
            f"nominal alpha={alpha:g}."
        ),
    ]
    if scope == "available_case":
        lines.append(
            "The QC/manual-eligible cohort was frozen before available "
            "observations were selected; no participant was silently removed "
            "to improve apparent condition coverage."
        )
    else:
        lines.append(
            "The QC/manual-eligible participant cohort was frozen before "
            "complete-condition intersection; incomplete conditions could be "
            "excluded, but participants were not silently dropped to recover "
            "conditions."
        )
    lines.extend(_design_note_lines(design, bullets=False))
    if design.get("n_groups") is not None:
        lines.append(f"Canonical groups represented: {design['n_groups']}.")
    lines.extend(["", "Test inventory", *_inventory_method_lines(inventory)])
    lines.extend(["", "Assumptions and estimands"])
    if methods.empty:
        lines.append("No methods were inventoried.")
    else:
        for _, row in methods.iterrows():
            lines.append(
                f"- {row['method']}: {row['purpose']}; assumptions: "
                f"{row['assumptions']}; role={row['role']}."
            )
    lines.extend(["", "Multiple-comparison and p-value decisions"])
    if correction_families.empty:
        lines.append(
            "No named multiplicity family was supplied; any unadjusted tests are "
            "identified as such in the inventory."
        )
    else:
        for _, row in correction_families.iterrows():
            family = row["family_id"] if pd.notna(row["family_id"]) else "unnamed"
            family_size = (
                f"; family size={row['family_size']}"
                if pd.notna(row.get("family_size"))
                else ""
            )
            lines.append(
                f"- family={family}: {human_correction(row['adjustment_method'])}; "
                f"alpha={row['alpha']}{family_size}."
            )
    lines.extend(["", "Limitations and provenance"])
    lines.extend(
        f"- [{row['severity']}] {row['message']}"
        for _, row in limitations.iterrows()
    )
    return "\n".join(lines)


__all__ = ["at_a_glance_text", "detailed_methods_text"]

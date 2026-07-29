"""Design-coverage summaries and explicit interpretation limitations."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from Tools.Stats.reporting.inference.bundle import (
    ADAPTIVE_HARMONIC_WARNING,
    METHOD_DEPENDENT_PHRASE,
)
from Tools.Stats.reporting.inference.frames import column, first_nonmissing


def design_summary(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, object]:
    """Summarize frozen N, group count, shared conditions, and coverage."""

    summary: dict[str, object] = {
        "n": None,
        "n_groups": None,
        "complete_conditions": "",
        "excluded_conditions": "",
        "coverage_note": "",
    }
    for name, frame in frames.items():
        lowered = name.casefold()
        if frame.empty:
            continue
        if "analysis design" in lowered or "run summary" in lowered:
            row = frame.iloc[0]
            summary["n"] = summary["n"] or first_nonmissing(
                row, ("n_frozen_participants", "n_participants", "N")
            )
            summary["complete_conditions"] = (
                summary["complete_conditions"]
                or first_nonmissing(row, ("complete_conditions",))
                or ""
            )
            summary["excluded_conditions"] = (
                summary["excluded_conditions"]
                or first_nonmissing(row, ("excluded_conditions",))
                or ""
            )
        if "group assignment" in lowered:
            group_col = column(frame, "group_id")
            if group_col:
                summary["n_groups"] = int(frame[group_col].dropna().nunique())
            participant_col = column(frame, "participant_id")
            if participant_col:
                summary["n"] = summary["n"] or int(
                    frame[participant_col].nunique()
                )
        if "coverage" in lowered:
            complete_col = column(frame, "cell_complete")
            if complete_col:
                complete = frame[complete_col].fillna(False).astype(bool)
                summary["coverage_note"] = (
                    f"{int(complete.sum())} of {len(frame)} requested "
                    "Condition × ROI coverage rows were complete."
                )
        if "prepared data" in lowered or "primary data" in lowered:
            subject_col = column(frame, "participant_id", "subject", "Subject")
            if subject_col:
                summary["n"] = summary["n"] or int(frame[subject_col].nunique())
            group_col = column(frame, "group_id", "group")
            if group_col:
                summary["n_groups"] = summary["n_groups"] or int(
                    frame[group_col].dropna().nunique()
                )
            condition_col = column(frame, "condition")
            if condition_col and not summary["complete_conditions"]:
                summary["complete_conditions"] = "; ".join(
                    map(str, pd.unique(frame[condition_col].dropna()))
                )
    return summary


def limitations_frame(
    inventory: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    design: Mapping[str, object],
) -> pd.DataFrame:
    """Build deduplicated caveats for provenance, estimability, and model fit."""

    rows: list[dict[str, str]] = []

    def add(severity: str, scope: str, code: str, message: str) -> None:
        record = {
            "severity": severity,
            "scope": scope,
            "code": code,
            "message": message,
        }
        if record not in rows:
            rows.append(record)

    provenances = {
        str(value).casefold()
        for value in inventory.get("harmonic_provenance", pd.Series(dtype=object))
        .dropna()
        .tolist()
    }
    if "same_sample_adaptive" in provenances:
        add(
            "warning",
            "response_detection",
            "adaptive_harmonic_selection",
            ADAPTIVE_HARMONIC_WARNING,
        )
    if "user_fixed_unverified" in provenances:
        add(
            "caution",
            "response_detection",
            "unverified_harmonic_provenance",
            "The harmonic list was user-fixed but its independence from this sample was not verified; response claims remain exploratory.",
        )
    if "unknown" in provenances:
        add(
            "caution",
            "response_detection",
            "unknown_harmonic_provenance",
            "Harmonic-selection provenance is unknown, so confirmatory response interpretation is not supported.",
        )
    excluded = str(design.get("excluded_conditions") or "").strip()
    if excluded:
        add(
            "information",
            "design",
            "excluded_incomplete_conditions",
            f"Conditions excluded before primary inference because complete frozen-cohort coverage was unavailable: {excluded}.",
        )
    if not inventory.empty:
        blocked = inventory[
            (~inventory["reportable"].eq(True))
            | inventory["p_value_used"].isna()
        ]
        if not blocked.empty:
            add(
                "warning",
                "inference",
                "non_estimable_or_failed_tests",
                f"{len(blocked)} inventory row(s) were non-estimable, blocked, or failed and were not used as primary findings.",
            )
        if inventory["role"].isin(["sensitivity", "exploratory"]).any():
            add(
                "information",
                "interpretation",
                "non_primary_analyses",
                "Exploratory and sensitivity analyses are labelled and are not promoted to primary conclusions.",
            )
        if (~inventory["headline_eligible"].eq(True)).any():
            add(
                "information",
                "interpretation",
                "detailed_only_inference_rows",
                "Raw-p-only, fixed-effect Wald, declaration-only, and other non-canonical rows remain in the detailed inventory but are excluded from the plain-language headline.",
            )
        if inventory["method"].astype(str).str.contains(
            "likelihood-ratio|mixed|Wald",
            case=False,
            regex=True,
        ).any():
            add(
                "caution",
                "model",
                "asymptotic_small_sample_reference",
                "Mixed-model Wald and likelihood-ratio p-values use asymptotic reference distributions and warrant caution in a small student sample.",
            )
    for name, frame in frames.items():
        if "diagnostic" in name.casefold() and column(
            frame, "test_method", "method"
        ):
            add(
                "information",
                "assumptions",
                "normality_is_diagnostic",
                "Normality tests are diagnostics only; their p-values do not automatically choose or switch the primary inferential method.",
            )
        status_col = column(frame, "status", "inference_status")
        if status_col and frame[status_col].astype(str).str.contains(
            "singular|failed|nonconverged",
            case=False,
            regex=True,
        ).any():
            add(
                "warning",
                "model",
                "model_fit_problem",
                "At least one model fit was singular, non-converged, or failed. Those rows are retained for audit but do not support a primary headline.",
            )
    add(
        "information",
        "interpretation",
        "method_dependent",
        f"{METHOD_DEPENDENT_PHRASE} Conclusions should be read with the named estimand, assumptions, correction family, and model status.",
    )
    return pd.DataFrame(
        rows,
        columns=["severity", "scope", "code", "message"],
    )


__all__ = ["design_summary", "limitations_frame"]

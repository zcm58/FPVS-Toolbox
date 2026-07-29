"""Design-coverage summaries and explicit interpretation limitations."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from Tools.Stats.reporting.inference.bundle import (
    ADAPTIVE_HARMONIC_WARNING,
    METHOD_DEPENDENT_PHRASE,
)
from Tools.Stats.reporting.inference.frames import (
    bool_value,
    column,
    first_nonmissing,
)


LimitationRows = list[dict[str, str]]


def _listed_values(value: object | None) -> tuple[str, ...]:
    """Normalize semicolon-delimited report metadata without reordering it."""

    if value is None or bool(pd.isna(value)):
        return ()
    return tuple(
        item.strip()
        for item in str(value).split(";")
        if item.strip()
    )


def _empty_summary() -> dict[str, object]:
    return {
        "n": None,
        "n_contributing": None,
        "default_n": None,
        "n_groups": None,
        "analysis_scope": None,
        "retained_conditions": "",
        "complete_conditions": "",
        "partial_conditions": "",
        "excluded_conditions": "",
        "n_observed_rows": None,
        "n_missing_retained": None,
        "cell_n_min": None,
        "cell_n_max": None,
        "cell_n_note": "",
        "no_imputation": None,
        "coverage_note": "",
        "_observed_conditions": (),
    }


def _update_design_metadata(
    summary: dict[str, object],
    name: str,
    frame: pd.DataFrame,
) -> bool:
    """Read explicit schema-v1/v2 design and run metadata."""

    lowered = name.casefold()
    is_design = "analysis design" in lowered
    if not (is_design or "run summary" in lowered or "run metadata" in lowered):
        return False
    row = frame.iloc[0]
    scope = first_nonmissing(row, ("analysis_scope",))
    if scope is not None:
        summary["analysis_scope"] = str(scope).strip().casefold()
    if "run metadata" in lowered:
        return False
    summary["n"] = summary["n"] or first_nonmissing(
        row, ("n_frozen_participants", "n_participants", "N")
    )
    summary["n_contributing"] = summary["n_contributing"] or first_nonmissing(
        row,
        ("n_contributing_participants", "n_analyzed_participants"),
    )
    for key in (
        "retained_conditions",
        "complete_conditions",
        "partial_conditions",
        "excluded_conditions",
    ):
        summary[key] = summary[key] or first_nonmissing(row, (key,)) or ""
    summary["n_observed_rows"] = summary["n_observed_rows"] or first_nonmissing(
        row, ("n_observed_rows", "n_primary_rows")
    )
    summary["n_missing_retained"] = (
        summary["n_missing_retained"]
        or first_nonmissing(
            row,
            (
                "n_missing_retained_observations",
                "n_missing_retained_cells",
            ),
        )
    )
    imputation = first_nonmissing(
        row, ("imputation_method", "missing_value_method")
    )
    if imputation is not None:
        summary["no_imputation"] = (
            str(imputation).strip().casefold()
            in {"none", "no_imputation", "observed_only"}
        )
    imputed = first_nonmissing(row, ("missing_values_imputed",))
    if imputed is not None:
        summary["no_imputation"] = not bool_value(imputed, default=False)
    return is_design


def _update_participant_summary(
    summary: dict[str, object],
    name: str,
    frame: pd.DataFrame,
) -> None:
    lowered = name.casefold()
    if "group assignment" in lowered:
        group_col = column(frame, "group_id")
        participant_col = column(frame, "participant_id")
        if group_col:
            summary["n_groups"] = int(frame[group_col].dropna().nunique())
        if participant_col:
            summary["n"] = summary["n"] or int(
                frame[participant_col].nunique()
            )
    if "participant coverage" not in lowered:
        return
    participant_col = column(frame, "participant_id")
    contributes_col = column(frame, "contributes_to_primary")
    if participant_col:
        summary["n"] = summary["n"] or int(frame[participant_col].nunique())
    if participant_col and contributes_col:
        contributes = frame[contributes_col].fillna(False).astype(bool)
        summary["n_contributing"] = int(
            frame.loc[contributes, participant_col].nunique()
        )


def _merge_cell_n_range(
    summary: dict[str, object],
    counts: pd.Series,
) -> None:
    finite_counts = pd.to_numeric(counts, errors="coerce").dropna()
    if finite_counts.empty:
        return
    observed_min = int(finite_counts.min())
    observed_max = int(finite_counts.max())
    current_min = summary["cell_n_min"]
    current_max = summary["cell_n_max"]
    summary["cell_n_min"] = (
        observed_min
        if current_min is None
        else min(int(current_min), observed_min)
    )
    summary["cell_n_max"] = (
        observed_max
        if current_max is None
        else max(int(current_max), observed_max)
    )


def _update_coverage_summary(
    summary: dict[str, object],
    name: str,
    frame: pd.DataFrame,
) -> None:
    lowered = name.casefold()
    if "missing observations" in lowered:
        retained_col = column(frame, "condition_retained")
        if retained_col:
            retained_missing = frame[retained_col].fillna(False).astype(bool)
            summary["n_missing_retained"] = int(retained_missing.sum())
    if "coverage" not in lowered:
        return
    complete_col = column(frame, "cell_complete")
    if complete_col:
        complete = frame[complete_col].fillna(False).astype(bool)
        summary["coverage_note"] = (
            f"{int(complete.sum())} of {len(frame)} requested "
            "Condition x ROI coverage rows were complete."
        )
    finite_col = column(frame, "n_finite_values")
    structural_col = column(frame, "structurally_observed")
    if finite_col:
        eligible = frame
        if structural_col:
            eligible = frame[frame[structural_col].fillna(False).astype(bool)]
        _merge_cell_n_range(summary, eligible[finite_col])


def _update_observation_summary(
    summary: dict[str, object],
    name: str,
    frame: pd.DataFrame,
) -> None:
    lowered = name.casefold()
    if "prepared data" in lowered or "primary data" in lowered:
        subject_col = column(frame, "participant_id", "subject", "Subject")
        condition_col = column(frame, "condition")
        group_col = column(frame, "group_id", "group")
        if subject_col:
            summary["n_contributing"] = summary["n_contributing"] or int(
                frame[subject_col].nunique()
            )
            summary["n_observed_rows"] = len(frame)
        if condition_col:
            summary["_observed_conditions"] = tuple(
                map(str, pd.unique(frame[condition_col].dropna()))
            )
        if group_col:
            summary["n_groups"] = summary["n_groups"] or int(
                frame[group_col].dropna().nunique()
            )
    group_columns = [
        column(frame, "n_group_a", "n_finite_group_a"),
        column(frame, "n_group_b", "n_finite_group_b"),
    ]
    group_counts = [
        pd.to_numeric(frame[item], errors="coerce")
        for item in group_columns
        if item is not None
    ]
    if group_counts:
        _merge_cell_n_range(
            summary,
            pd.concat(group_counts, ignore_index=True),
        )


def _finalize_summary(
    summary: dict[str, object],
    *,
    has_design_frame: bool,
) -> dict[str, object]:
    if summary["analysis_scope"] is None and has_design_frame:
        summary["analysis_scope"] = "complete_core"
    scope = str(summary["analysis_scope"] or "").strip().casefold()
    retained = _listed_values(summary["retained_conditions"])
    complete = _listed_values(summary["complete_conditions"])
    observed = tuple(summary.pop("_observed_conditions", ()))
    if not retained:
        retained = complete or observed
        summary["retained_conditions"] = "; ".join(retained)
    if not complete and scope != "available_case":
        complete = retained
        summary["complete_conditions"] = "; ".join(complete)
    if not summary["partial_conditions"] and retained:
        complete_keys = {item.casefold() for item in complete}
        summary["partial_conditions"] = "; ".join(
            item for item in retained if item.casefold() not in complete_keys
        )
    if scope == "available_case":
        summary["no_imputation"] = True
        summary["default_n"] = (
            summary["n_contributing"]
            if summary["n_contributing"] is not None
            else summary["n"]
        )
    else:
        summary["default_n"] = summary["n"]
    cell_min = summary["cell_n_min"]
    cell_max = summary["cell_n_max"]
    if cell_min is not None and cell_max is not None:
        if int(cell_min) == int(cell_max):
            summary["cell_n_note"] = (
                f"Each observed model/group cell contributed N={int(cell_min)}."
            )
        else:
            summary["cell_n_note"] = (
                "Observed model/group cell sample sizes varied from "
                f"N={int(cell_min)} to N={int(cell_max)}; exact Ns are "
                "reported per result row."
            )
    return summary


def design_summary(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, object]:
    """Summarize scope, frozen/contributing N, conditions, and coverage."""

    summary = _empty_summary()
    has_design_frame = False
    for name, frame in frames.items():
        if frame.empty:
            continue
        has_design_frame = (
            _update_design_metadata(summary, name, frame)
            or has_design_frame
        )
        _update_participant_summary(summary, name, frame)
        _update_coverage_summary(summary, name, frame)
        _update_observation_summary(summary, name, frame)
    return _finalize_summary(summary, has_design_frame=has_design_frame)


def _add_limitation(
    rows: LimitationRows,
    severity: str,
    scope: str,
    code: str,
    message: str,
) -> None:
    record = {
        "severity": severity,
        "scope": scope,
        "code": code,
        "message": message,
    }
    if record not in rows:
        rows.append(record)


def _add_harmonic_limitations(
    rows: LimitationRows,
    inventory: pd.DataFrame,
) -> None:
    provenances = {
        str(value).casefold()
        for value in inventory.get(
            "harmonic_provenance", pd.Series(dtype=object)
        )
        .dropna()
        .tolist()
    }
    if "same_sample_adaptive" in provenances:
        _add_limitation(
            rows,
            "warning",
            "response_detection",
            "adaptive_harmonic_selection",
            ADAPTIVE_HARMONIC_WARNING,
        )
    if "user_fixed_unverified" in provenances:
        _add_limitation(
            rows,
            "caution",
            "response_detection",
            "unverified_harmonic_provenance",
            "The harmonic list was user-fixed but its independence from this "
            "sample was not verified; response claims remain exploratory.",
        )
    if "unknown" in provenances:
        _add_limitation(
            rows,
            "caution",
            "response_detection",
            "unknown_harmonic_provenance",
            "Harmonic-selection provenance is unknown, so confirmatory "
            "response interpretation is not supported.",
        )


def _add_available_case_limitations(
    rows: LimitationRows,
    design: Mapping[str, object],
) -> None:
    entries = (
        (
            "information",
            "missing_data",
            "available_case_no_imputation",
            "The available-case analysis used finite observed rows only; "
            "missing participant-condition-ROI cells were not filled or imputed.",
        ),
        (
            "caution",
            "missing_data",
            "available_case_mar_assumption",
            "Likelihood-based available-case inference assumes missingness is "
            "ignorable (missing at random, MAR) after conditioning on the "
            "variables in the model.",
        ),
        (
            "warning",
            "missing_data",
            "available_case_mnar_bias",
            "If exclusions still depend on an unobserved response after "
            "accounting for modeled variables (missing not at random, MNAR), "
            "estimates and p-values may be biased.",
        ),
        (
            "information",
            "method",
            "balanced_methods_omitted",
            "Repeated-measures ANOVA and paired post-hoc tests were "
            "intentionally omitted because they require complete "
            "within-participant cells; the mixed model used the available "
            "observations instead.",
        ),
    )
    for entry in entries:
        _add_limitation(rows, *entry)
    if design.get("n") is not None and design.get("n_contributing") is not None:
        _add_limitation(
            rows,
            "information",
            "design",
            "frozen_vs_contributing_participants",
            f"The cohort was frozen at N={design['n']}, and "
            f"N={design['n_contributing']} participant(s) contributed at "
            "least one finite retained observation.",
        )
    cell_n_note = str(design.get("cell_n_note") or "").strip()
    if cell_n_note:
        _add_limitation(
            rows,
            "information",
            "design",
            "varying_cell_sample_sizes",
            cell_n_note,
        )


def _add_design_limitations(
    rows: LimitationRows,
    design: Mapping[str, object],
) -> None:
    scope = str(design.get("analysis_scope") or "").strip().casefold()
    excluded = str(design.get("excluded_conditions") or "").strip()
    if excluded and scope == "available_case":
        _add_limitation(
            rows,
            "information",
            "design",
            "excluded_structural_conditions",
            "Conditions excluded because at least one required fixed-effect "
            f"cell had no finite observation: {excluded}.",
        )
    elif excluded:
        _add_limitation(
            rows,
            "information",
            "design",
            "excluded_incomplete_conditions",
            "Conditions excluded before primary inference because complete "
            f"frozen-cohort coverage was unavailable: {excluded}.",
        )
    if scope == "available_case":
        _add_available_case_limitations(rows, design)


def _add_inventory_limitations(
    rows: LimitationRows,
    inventory: pd.DataFrame,
) -> None:
    if inventory.empty:
        return
    blocked = inventory[
        (~inventory["reportable"].eq(True)) | inventory["p_value_used"].isna()
    ]
    if not blocked.empty:
        _add_limitation(
            rows,
            "warning",
            "inference",
            "non_estimable_or_failed_tests",
            f"{len(blocked)} inventory row(s) were non-estimable, blocked, or "
            "failed and were not used as primary findings.",
        )
    if inventory["role"].isin(["sensitivity", "exploratory"]).any():
        _add_limitation(
            rows,
            "information",
            "interpretation",
            "non_primary_analyses",
            "Exploratory and sensitivity analyses are labelled and are not "
            "promoted to primary conclusions.",
        )
    if (~inventory["headline_eligible"].eq(True)).any():
        _add_limitation(
            rows,
            "information",
            "interpretation",
            "detailed_only_inference_rows",
            "Raw-p-only, fixed-effect Wald, declaration-only, and other "
            "non-canonical rows remain in the detailed inventory but are "
            "excluded from the plain-language headline.",
        )
    if inventory["method"].astype(str).str.contains(
        "likelihood-ratio|mixed|Wald",
        case=False,
        regex=True,
    ).any():
        _add_limitation(
            rows,
            "caution",
            "model",
            "asymptotic_small_sample_reference",
            "Mixed-model Wald and likelihood-ratio p-values use asymptotic "
            "reference distributions and warrant caution in a small student "
            "sample.",
        )


def _add_frame_limitations(
    rows: LimitationRows,
    frames: Mapping[str, pd.DataFrame],
) -> None:
    for name, frame in frames.items():
        if "diagnostic" in name.casefold() and column(
            frame, "test_method", "method"
        ):
            _add_limitation(
                rows,
                "information",
                "assumptions",
                "normality_is_diagnostic",
                "Normality tests are diagnostics only; their p-values do not "
                "automatically choose or switch the primary inferential method.",
            )
        status_col = column(frame, "status", "inference_status")
        if status_col and frame[status_col].astype(str).str.contains(
            "singular|failed|nonconverged",
            case=False,
            regex=True,
        ).any():
            _add_limitation(
                rows,
                "warning",
                "model",
                "model_fit_problem",
                "At least one model fit was singular, non-converged, or failed. "
                "Those rows are retained for audit but do not support a primary "
                "headline.",
            )


def limitations_frame(
    inventory: pd.DataFrame,
    frames: Mapping[str, pd.DataFrame],
    design: Mapping[str, object],
) -> pd.DataFrame:
    """Build deduplicated caveats for provenance, estimability, and model fit."""

    rows: LimitationRows = []
    _add_harmonic_limitations(rows, inventory)
    _add_design_limitations(rows, design)
    _add_inventory_limitations(rows, inventory)
    _add_frame_limitations(rows, frames)
    _add_limitation(
        rows,
        "information",
        "interpretation",
        "method_dependent",
        f"{METHOD_DEPENDENT_PHRASE} Conclusions should be read with the named "
        "estimand, assumptions, correction family, and model status.",
    )
    return pd.DataFrame(
        rows,
        columns=["severity", "scope", "code", "message"],
    )


__all__ = ["design_summary", "limitations_frame"]

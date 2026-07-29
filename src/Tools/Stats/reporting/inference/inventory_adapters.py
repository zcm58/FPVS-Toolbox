"""Schema adapters for heterogeneous statistical result frames."""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd

from Tools.Stats.reporting.inference.frames import (
    bool_value,
    finite_float,
    first_nonmissing,
    select_p_column,
)


NON_RESULT_NAME_TOKENS = (
    "metadata",
    "diagnostic",
    "coverage",
    "exclusion",
    "assignment",
    "attempt",
    "inventory",
    "method",
    "limitation",
    "run log",
    "primary data",
    "prepared data",
)
BLOCKING_STATUS_TOKENS = (
    "not_estimable",
    "not estimable",
    "not_run",
    "not run",
    "failed",
    "cancelled",
    "blocked",
    "nonconverged",
    "non-converged",
    "singular",
    "insufficient",
)


def frame_is_result(name: str, frame: pd.DataFrame) -> bool:
    """Return whether a frame contains inference rather than audit data."""

    lowered = name.casefold()
    if any(token in lowered for token in NON_RESULT_NAME_TOKENS):
        return False
    p_column, _ = select_p_column(frame)
    return p_column is not None


def section_for(name: str, frame: pd.DataFrame) -> str:
    """Map a result frame to a non-expert reporting question."""

    lowered = name.casefold()
    columns = {str(item).casefold() for item in frame.columns}
    if (
        {"group_a", "group_b"}.issubset(columns)
        or "contrast_sign" in columns
        or "marginal group" in lowered
        or "group cell" in lowered
        or (
            "effect_id" in columns
            and frame.get("effect_id", pd.Series(dtype=object))
            .astype(str)
            .str.contains("group", case=False)
            .any()
        )
    ):
        return "between_group"
    one_sample_statistic = (
        "statistic_name" in columns
        and frame["statistic_name"]
        .astype(str)
        .str.contains("one_sample", case=False)
        .any()
    )
    one_sample_analysis = (
        "analysis_kind" in columns
        and frame["analysis_kind"]
        .astype(str)
        .str.contains("one_sample", case=False)
        .any()
    )
    response_named = any(
        token in lowered
        for token in ("baseline", "response", "one sample", "one-sample")
    )
    if (
        "harmonic_provenance" in columns
        or response_named
        or one_sample_statistic
        or one_sample_analysis
    ) and {"condition", "roi"}.issubset(columns):
        return "response_detection"
    return "within_subject"


def role_for(name: str, row: pd.Series) -> str:
    """Resolve primary, exploratory, or sensitivity interpretation role."""

    value = first_nonmissing(
        row,
        (
            "inference_role",
            "interpretation_role",
            "role",
            "analysis_profile",
            "followup_provenance",
        ),
    )
    status = first_nonmissing(row, ("inference_status",)) or ""
    lowered = f"{name} {value or ''} {status}".casefold()
    if "sensitivity" in lowered or any(
        token in name.casefold()
        for token in ("robust", "resampling", "stability", "leave one out")
    ):
        return "sensitivity"
    if any(
        token in lowered
        for token in (
            "exploratory",
            "post_selection",
            "post-selection",
            "unverified",
            "unknown",
        )
    ):
        return "exploratory"
    return "primary"


def row_status(row: pd.Series) -> tuple[str, bool]:
    """Return an explicit status and reportability decision."""

    status_value = first_nonmissing(
        row,
        ("inference_status", "status", "status_code", "LRT Status"),
    )
    status = "estimated" if status_value is None else str(status_value)
    reportable_value = first_nonmissing(row, ("reportable",))
    reportable = bool_value(reportable_value, default=True)
    if any(token in status.casefold() for token in BLOCKING_STATUS_TOKENS):
        reportable = False
    return status, reportable


def label_for(section: str, row: pd.Series) -> str:
    """Construct a readable estimand/effect label."""

    condition = first_nonmissing(row, ("condition", "Condition"))
    roi = first_nonmissing(row, ("roi", "ROI"))
    if section == "between_group":
        contrast = first_nonmissing(row, ("contrast", "contrast_sign"))
        if contrast is None:
            group_a = first_nonmissing(row, ("group_a",))
            group_b = first_nonmissing(row, ("group_b",))
            if group_a is not None and group_b is not None:
                contrast = f"{group_a} - {group_b}"
        if contrast is None:
            reference = first_nonmissing(row, ("reference_group_id",))
            comparison = first_nonmissing(row, ("comparison_group_id",))
            if reference is not None and comparison is not None:
                contrast = f"{comparison} - {reference}"
        cell = " / ".join(
            str(value) for value in (condition, roi) if value is not None
        )
        if contrast is not None and cell:
            return f"{cell}: {contrast}"
        if contrast is not None:
            return str(contrast)
    level_a = first_nonmissing(row, ("Level_A", "level_a"))
    level_b = first_nonmissing(row, ("Level_B", "level_b"))
    stratum = first_nonmissing(row, ("Stratum", "stratum", "Slice", "slice"))
    if level_a is not None and level_b is not None:
        comparison = f"{level_a} - {level_b}"
        return f"{stratum}: {comparison}" if stratum is not None else comparison
    effect = first_nonmissing(
        row,
        (
            "test_label",
            "effect_label",
            "Effect",
            "Source",
            "effect",
            "term",
            "comparison",
        ),
    )
    if effect is not None:
        return str(effect)
    cell = " / ".join(
        str(value) for value in (condition, roi) if value is not None
    )
    return cell or "Unnamed test"


def method_for(name: str, row: pd.Series, p_source: str) -> str:
    """Infer a method label only when a result did not export one."""

    explicit = first_nonmissing(
        row,
        ("test_method", "method", "statistical_test", "inference_reference"),
    )
    if explicit is not None:
        return str(explicit)
    lowered = name.casefold()
    columns = {str(item).casefold() for item in row.index}
    if p_source == "canonical_reported":
        return "repeated-measures ANOVA"
    if p_source == "likelihood_ratio":
        return "ML likelihood-ratio test"
    if {"group_a", "group_b"}.issubset(columns):
        return "two-sided Welch independent-samples t-test"
    if "posthoc" in lowered or "post-hoc" in lowered:
        return "paired follow-up comparison"
    if "response" in lowered or "baseline" in lowered:
        return "one-sample response test"
    return name.replace("_", " ").strip().title()


def estimand_for(section: str, row: pd.Series) -> object:
    """Return an exported estimand or a conservative schema-derived label."""

    explicit = first_nonmissing(row, ("estimand",))
    if explicit is not None:
        return explicit
    if section == "response_detection":
        return "Condition x ROI arithmetic-mean response relative to zero"
    if section == "between_group":
        group_a = first_nonmissing(
            row, ("group_a", "comparison_group_id")
        )
        group_b = first_nonmissing(
            row, ("group_b", "reference_group_id")
        )
        if group_a is not None and group_b is not None:
            return f"Condition x ROI mean contrast: {group_a} minus {group_b}"
        return "hierarchy-preserving group-related model comparison"
    level_a = first_nonmissing(row, ("Level_A", "level_a"))
    level_b = first_nonmissing(row, ("Level_B", "level_b"))
    if level_a is not None and level_b is not None:
        return f"paired mean contrast: {level_a} minus {level_b}"
    return "arithmetic-mean within-participant Condition/ROI effect"


def estimate_fields(
    row: pd.Series,
) -> tuple[object | None, object | None, object | None]:
    """Extract a signed estimate and compatible confidence interval."""

    estimate = first_nonmissing(
        row,
        (
            "mean_difference_a_minus_b",
            "mean_difference",
            "mean_diff",
            "estimate",
            "mean",
            "coefficient",
            "Coef.",
        ),
    )
    low = first_nonmissing(
        row,
        (
            "ci_difference_low",
            "ci_mean_low",
            "ci_low",
            "CI Low",
            "ci_lower",
            "ci95_low",
        ),
    )
    high = first_nonmissing(
        row,
        (
            "ci_difference_high",
            "ci_mean_high",
            "ci_high",
            "CI High",
            "ci_upper",
            "ci95_high",
        ),
    )
    return estimate, low, high


def effect_size_fields(row: pd.Series) -> tuple[str, object | None]:
    """Extract one named effect size without conflating scales."""

    for item, label in (
        ("hedges_g", "Hedges g"),
        ("cohens_dz", "Cohen dz"),
        ("cohens_d", "Cohen d"),
        ("np2", "partial eta squared"),
        ("partial_eta_squared", "partial eta squared"),
        ("effect_size", "effect size"),
    ):
        value = first_nonmissing(row, (item,))
        if value is not None:
            return label, value
    return "", None


def n_for(row: pd.Series) -> object | None:
    """Extract total N, including paired and independent-group counts."""

    direct = first_nonmissing(
        row,
        (
            "N",
            "n",
            "N_Pairs",
            "n_pairs",
            "n_participants",
            "n_subjects",
            "n_frozen_participants",
            "effective_n",
            "n_effective",
            "n_finite",
        ),
    )
    if direct is not None:
        return direct
    group_a = finite_float(
        first_nonmissing(
            row,
            ("n_group_a", "n_finite_group_a", "effective_n_group_a"),
        )
    )
    group_b = finite_float(
        first_nonmissing(
            row,
            ("n_group_b", "n_finite_group_b", "effective_n_group_b"),
        )
    )
    if group_a is not None and group_b is not None:
        return int(group_a + group_b)
    return None


def run_defaults(
    frames: Mapping[str, pd.DataFrame],
) -> dict[str, object | None]:
    """Read run-wide profile/provenance defaults from explicit metadata."""

    defaults: dict[str, object | None] = {
        "profile": None,
        "harmonic_provenance": None,
        "alternative": None,
    }
    for frame_name, frame in frames.items():
        if frame.empty or "run metadata" not in frame_name.casefold():
            continue
        row = frame.iloc[0]
        defaults["profile"] = defaults["profile"] or first_nonmissing(
            row, ("profile", "analysis_profile")
        )
        defaults["harmonic_provenance"] = (
            defaults["harmonic_provenance"]
            or first_nonmissing(row, ("harmonic_provenance",))
        )
        defaults["alternative"] = defaults["alternative"] or first_nonmissing(
            row, ("response_alternative", "alternative")
        )
    return defaults


def canonical_reject(
    row: pd.Series,
    *,
    p_value: float | None,
    alpha: float,
    p_source: str,
) -> tuple[bool | None, str]:
    """Resolve the decision using the engine's inclusive alpha rule."""

    if p_value is None:
        return None, "unavailable"
    computed = bool(p_value <= alpha)
    candidates = (
        ("reject_adjusted",)
        if p_source == "multiplicity_adjusted"
        else ("reject_reported", "reject", "significant")
    )
    exported = first_nonmissing(row, candidates)
    if exported is None:
        return computed, "computed_from_selected_p_le_alpha"
    exported_bool = bool_value(exported, default=computed)
    if exported_bool == computed:
        return computed, "exported_and_validated"
    return computed, "recomputed_from_selected_p_le_alpha_export_mismatch"


def headline_contract(
    *,
    frame_name: str,
    p_source: str,
    row: pd.Series | None = None,
) -> tuple[bool, str]:
    """Return whether the p-value contract may enter visible findings."""

    lowered = frame_name.casefold()
    explicit = None
    analysis_scope = ""
    if row is not None:
        explicit = first_nonmissing(row, ("headline_eligible",))
        if explicit is not None and not bool_value(explicit, default=False):
            return False, "analysis_marked_detailed_only"
        scope_value = first_nonmissing(row, ("analysis_scope",))
        if scope_value is not None:
            analysis_scope = (
                str(scope_value).strip().casefold().replace("-", "_")
            )
    if "fixed effects" in lowered:
        return False, "fixed_effect_wald_estimates_are_detailed_only"
    if p_source == "wald":
        return False, "raw_wald_p_is_detailed_only"
    if (
        explicit is not None
        and bool_value(explicit, default=False)
        and analysis_scope == "available_case"
        and "mixed model" in lowered
        and "lrt" in lowered
        and p_source
        in {
            "likelihood_ratio",
            "multiplicity_adjusted",
            "canonical_reported",
        }
    ):
        return True, "available_case_lmm_lrt_marked_headline_eligible"
    if "mixed model" in lowered and "lrt" in lowered:
        return False, "single_mixed_model_lrt_is_secondary"
    if p_source in {"multiplicity_adjusted", "canonical_reported"}:
        return True, "canonical_adjusted_or_reported_p"
    if p_source == "likelihood_ratio" and (
        "omnibus" in lowered or "lrt" in lowered
    ):
        return True, "explicit_omnibus_likelihood_ratio_test"
    if p_source == "raw":
        return False, "raw_p_is_detailed_only"
    return False, "no_headline_safe_p_value"


__all__ = [
    "canonical_reject",
    "effect_size_fields",
    "estimand_for",
    "estimate_fields",
    "frame_is_result",
    "headline_contract",
    "label_for",
    "method_for",
    "n_for",
    "role_for",
    "row_status",
    "run_defaults",
    "section_for",
]

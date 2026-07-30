"""Balanced-design ANOVA checks that remain secondary to the primary LMM.

The compatibility routines pre-audit the complete *declared* analysis grid.
This prevents statistical backends from silently averaging duplicate cells or
listwise-deleting incomplete participants.  A failed eligibility check is a
normal skipped compatibility result; it never replaces or invalidates the LMM.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import f as f_distribution
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.repeated_m_anova import (
    resolve_rm_anova_inference,
    run_repeated_measures_anova,
)


ANOVA_COMPATIBILITY_FAMILY_ID = "anova_compatibility_effects"
ANOVA_COMPATIBILITY_FAMILY_LABEL = (
    "Balanced-design ANOVA compatibility effects"
)
SINGLE_ANALYSIS_LABEL = "Two-way repeated-measures ANOVA compatibility check"
MULTI_ANALYSIS_LABEL = (
    "Group x response-cell mixed-ANOVA compatibility check"
)
MULTI_LIMITATION = (
    "This broad Group x response-cell compatibility check does not decompose "
    "separate Group x Condition, Group x ROI, or Group x Condition x ROI terms."
)
PLANNED_ANOVA_EFFECTS = 3


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _declared_levels(
    values: Sequence[object],
    *,
    label: str,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a sequence of values, not text.")
    normalized = tuple(_text(value) for value in values)
    if not normalized or any(not value for value in normalized):
        raise ValueError(f"{label} must contain non-empty declared values.")
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{label} must not contain duplicate declared values.")
    return normalized


def _issue_preview(keys: Sequence[tuple[str, str, str]]) -> str:
    rendered = [
        " / ".join(key)
        for key in list(keys)[:5]
    ]
    if len(keys) > len(rendered):
        rendered.append(f"{len(keys) - len(rendered)} more")
    return "; ".join(rendered)


@dataclass(frozen=True, slots=True)
class ExactGridAudit:
    """Eligibility result for one declared participant-by-cell matrix."""

    eligible: bool
    status_code: str
    message: str
    n_expected_rows: int
    n_observed_rows: int
    n_participants: int
    n_conditions: int
    n_rois: int
    n_missing_cells: int = 0
    n_duplicate_cell_keys: int = 0
    n_nonfinite_rows: int = 0
    n_unexpected_rows: int = 0
    n_group_mismatches: int = 0
    equal_group_sizes: bool | None = None
    group_counts: tuple[tuple[str, int], ...] = ()

    def to_frame(self) -> pd.DataFrame:
        """Return one exportable audit row."""

        return pd.DataFrame(
            [
                {
                    "compatibility_status": (
                        "eligible" if self.eligible else "skipped"
                    ),
                    "status_code": self.status_code,
                    "message": self.message,
                    "exact_declared_grid": self.eligible,
                    "n_expected_rows": self.n_expected_rows,
                    "n_observed_rows": self.n_observed_rows,
                    "n_participants": self.n_participants,
                    "n_conditions": self.n_conditions,
                    "n_rois": self.n_rois,
                    "n_missing_cells": self.n_missing_cells,
                    "n_duplicate_cell_keys": self.n_duplicate_cell_keys,
                    "n_nonfinite_rows": self.n_nonfinite_rows,
                    "n_unexpected_rows": self.n_unexpected_rows,
                    "n_group_mismatches": self.n_group_mismatches,
                    "equal_group_sizes": self.equal_group_sizes,
                    "group_counts": "; ".join(
                        f"{group}={count}"
                        for group, count in self.group_counts
                    ),
                }
            ]
        )


@dataclass(frozen=True, slots=True)
class AnovaCompatibilityBundle:
    """Nonfatal ANOVA compatibility result and its audit material."""

    mode: str
    status: str
    status_code: str
    message: str
    audit: ExactGridAudit
    results: pd.DataFrame
    response_cell_map: pd.DataFrame

    @property
    def ran(self) -> bool:
        return self.status in {"completed", "partial"}

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return stable export frames without inventing skipped p-values."""

        frames: dict[str, pd.DataFrame] = {}
        if not self.results.empty:
            frames["ANOVA Compatibility"] = self.results.copy(deep=True)
        frames["ANOVA Compatibility Status"] = pd.DataFrame(
            [
                {
                    "mode": self.mode,
                    "compatibility_status": self.status,
                    "status_code": self.status_code,
                    "message": self.message,
                    "ran": self.ran,
                    "compatibility_only": True,
                    "inference_role": "compatibility",
                    "headline_eligible": False,
                }
            ]
        )
        frames["ANOVA Balance Audit"] = self.audit.to_frame()
        if not self.response_cell_map.empty:
            frames["ANOVA Response Cell Map"] = (
                self.response_cell_map.copy(deep=True)
            )
        return frames


@dataclass(frozen=True, slots=True)
class _PreparedGrid:
    audit: ExactGridAudit
    data: pd.DataFrame
    participants: tuple[str, ...]
    conditions: tuple[str, ...]
    rois: tuple[str, ...]
    group_ids: dict[str, str]


def _skipped_bundle(
    *,
    mode: str,
    audit: ExactGridAudit,
    status_code: str | None = None,
    message: str | None = None,
    response_cell_map: pd.DataFrame | None = None,
) -> AnovaCompatibilityBundle:
    return AnovaCompatibilityBundle(
        mode=mode,
        status="skipped",
        status_code=status_code or audit.status_code,
        message=message or audit.message,
        audit=audit,
        results=pd.DataFrame(),
        response_cell_map=(
            pd.DataFrame()
            if response_cell_map is None
            else response_cell_map.copy(deep=True)
        ),
    )


def _prepare_exact_grid(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    frozen_participants: Sequence[object],
    retained_conditions: Sequence[object],
    selected_rois: Sequence[object],
    group_col: str | None = None,
    canonical_group_ids: Mapping[object, object] | None = None,
    group_pair: Sequence[object] | None = None,
) -> _PreparedGrid:
    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    participants = _declared_levels(
        frozen_participants,
        label="frozen_participants",
    )
    conditions = _declared_levels(
        retained_conditions,
        label="retained_conditions",
    )
    rois = _declared_levels(selected_rois, label="selected_rois")
    required = [dv_col, subject_col, condition_col, roi_col]
    if group_col is not None:
        required.append(group_col)
    missing_columns = [column for column in required if column not in data.columns]
    if missing_columns:
        audit = ExactGridAudit(
            eligible=False,
            status_code="missing_required_columns",
            message=(
                "ANOVA compatibility was skipped because required prepared-data "
                f"columns were missing: {', '.join(missing_columns)}."
            ),
            n_expected_rows=len(participants) * len(conditions) * len(rois),
            n_observed_rows=len(data),
            n_participants=len(participants),
            n_conditions=len(conditions),
            n_rois=len(rois),
        )
        return _PreparedGrid(
            audit,
            pd.DataFrame(),
            participants,
            conditions,
            rois,
            {},
        )

    expected_keys = tuple(product(participants, conditions, rois))
    expected_set = set(expected_keys)
    normalized = data.copy(deep=True)
    normalized[subject_col] = normalized[subject_col].map(_text)
    normalized[condition_col] = normalized[condition_col].map(_text)
    normalized[roi_col] = normalized[roi_col].map(_text)
    normalized[dv_col] = pd.to_numeric(normalized[dv_col], errors="coerce")
    normalized["_anova_grid_key"] = list(
        zip(
            normalized[subject_col],
            normalized[condition_col],
            normalized[roi_col],
            strict=True,
        )
    )

    unexpected_mask = ~normalized["_anova_grid_key"].isin(expected_set)
    in_scope = normalized.loc[~unexpected_mask].copy()
    key_counts = in_scope["_anova_grid_key"].value_counts(dropna=False)
    observed_keys = set(key_counts.index.tolist())
    missing_keys = sorted(expected_set - observed_keys)
    duplicate_keys = sorted(
        key for key, count in key_counts.items() if int(count) != 1
    )
    nonfinite_mask = ~np.isfinite(in_scope[dv_col].to_numpy(dtype=float))

    group_ids: dict[str, str] = {}
    group_counts: tuple[tuple[str, int], ...] = ()
    equal_group_sizes: bool | None = None
    group_mismatch_count = 0
    group_issue = ""
    if group_col is not None:
        raw_assignments = canonical_group_ids or {}
        by_participant = {
            _text(participant): _text(group)
            for participant, group in raw_assignments.items()
            if _text(participant)
        }
        group_ids = {
            participant: by_participant.get(participant, "")
            for participant in participants
        }
        pair = (
            ()
            if group_pair is None
            else tuple(_text(group) for group in group_pair)
        )
        if len(pair) != 2 or any(not group for group in pair) or pair[0] == pair[1]:
            group_issue = (
                "ANOVA compatibility requires one explicit pair of two distinct "
                "canonical groups."
            )
        elif any(not group_ids[participant] for participant in participants):
            group_issue = (
                "ANOVA compatibility was skipped because at least one frozen "
                "participant lacked a canonical group assignment."
            )
        elif set(group_ids.values()) != set(pair):
            group_issue = (
                "ANOVA compatibility requires the selected pair to contain the "
                "two canonical groups represented by the frozen cohort."
            )
        else:
            counts = {
                group: sum(value == group for value in group_ids.values())
                for group in pair
            }
            group_counts = tuple((group, counts[group]) for group in pair)
            equal_group_sizes = len(set(counts.values())) == 1
            if min(counts.values()) < 2:
                group_issue = (
                    "ANOVA compatibility requires at least two frozen "
                    "participants in each canonical group."
                )
            elif not equal_group_sizes:
                group_issue = (
                    "The broad mixed-ANOVA compatibility check requires equal "
                    "frozen participant counts in the two groups."
                )
        normalized[group_col] = normalized[group_col].map(_text)
        expected_groups = normalized[subject_col].map(group_ids)
        mismatch = (
            ~unexpected_mask
            & (
                expected_groups.isna()
                | normalized[group_col].ne(expected_groups)
            )
        )
        group_mismatch_count = int(mismatch.sum())
        if group_mismatch_count and not group_issue:
            group_issue = (
                "Prepared rows did not consistently match the canonical group "
                "assignments."
            )

    issues: list[tuple[str, str]] = []
    if len(conditions) < 2 or len(rois) < 2:
        issues.append(
            (
                "requires_two_condition_and_roi_levels",
                "ANOVA compatibility requires at least two retained Conditions "
                "and two selected ROIs.",
            )
        )
    if len(participants) < 2:
        issues.append(
            (
                "requires_two_participants",
                "ANOVA compatibility requires at least two frozen participants.",
            )
        )
    if group_issue:
        issues.append(("group_balance_requirement_not_met", group_issue))
    if bool(unexpected_mask.any()):
        issues.append(
            (
                "unexpected_grid_rows",
                "Prepared data contained rows outside the declared participant "
                "x Condition x ROI grid.",
            )
        )
    if duplicate_keys:
        issues.append(
            (
                "duplicate_grid_cells",
                "Prepared data contained duplicate declared cells: "
                f"{_issue_preview(duplicate_keys)}.",
            )
        )
    if missing_keys:
        issues.append(
            (
                "missing_grid_cells",
                "The declared balanced grid was incomplete: "
                f"{_issue_preview(missing_keys)}.",
            )
        )
    if bool(nonfinite_mask.any()):
        issues.append(
            (
                "nonfinite_grid_cells",
                "The declared balanced grid contained missing or non-finite "
                "response values.",
            )
        )

    eligible = not issues
    status_code, message = (
        (
            "exact_declared_grid_complete",
            "The declared participant x Condition x ROI grid is complete, "
            "unique, and finite.",
        )
        if eligible
        else issues[0]
    )
    audit = ExactGridAudit(
        eligible=eligible,
        status_code=status_code,
        message=message,
        n_expected_rows=len(expected_keys),
        n_observed_rows=len(normalized),
        n_participants=len(participants),
        n_conditions=len(conditions),
        n_rois=len(rois),
        n_missing_cells=len(missing_keys),
        n_duplicate_cell_keys=len(duplicate_keys),
        n_nonfinite_rows=int(nonfinite_mask.sum()),
        n_unexpected_rows=int(unexpected_mask.sum()),
        n_group_mismatches=group_mismatch_count,
        equal_group_sizes=equal_group_sizes,
        group_counts=group_counts,
    )
    analysis_data = (
        in_scope.drop(columns=["_anova_grid_key"]).copy()
        if eligible
        else pd.DataFrame()
    )
    return _PreparedGrid(
        audit,
        analysis_data,
        participants,
        conditions,
        rois,
        group_ids,
    )


def _canonical_single_effect(value: object) -> str | None:
    token = (
        _text(value)
        .casefold()
        .replace("×", "*")
        .replace(":", "*")
        .replace("_", " ")
    )
    compact = " ".join(token.split())
    if compact in {"condition", "conditions"}:
        return "condition"
    if compact in {"roi", "rois"}:
        return "roi"
    if "condition" in compact and "roi" in compact:
        return "condition_roi_interaction"
    return None


def _canonical_multi_effect(value: object) -> str | None:
    token = _text(value).casefold().replace("-", "_").replace(" ", "_")
    if token in {"group", "between", "_compat_group_id"}:
        return "group"
    if token in {
        "response_cell",
        "response_cell_id",
        "within",
        "_response_cell_id",
    }:
        return "response_cell"
    if token in {
        "interaction",
        "group_*_response_cell",
        "group_response_cell",
        "group:response_cell",
    } or ("group" in token and "response" in token):
        return "group_response_cell_interaction"
    return None


def _planned_holm_correction(
    results: pd.DataFrame,
    *,
    alpha: float,
) -> pd.DataFrame:
    """Apply Holm using all three prespecified compatibility slots."""

    output = results.copy()
    raw = pd.to_numeric(output["p_reported"], errors="coerce").astype(float)
    finite = np.isfinite(raw.to_numpy(dtype=float))
    planned_values = raw.fillna(1.0).to_numpy(dtype=float)
    rejected, adjusted, _, _ = multipletests(
        planned_values,
        alpha=float(alpha),
        method="holm",
    )
    output["family_id"] = ANOVA_COMPATIBILITY_FAMILY_ID
    output["family_label"] = ANOVA_COMPATIBILITY_FAMILY_LABEL
    output["family_size"] = PLANNED_ANOVA_EFFECTS
    output["planned_family_size"] = PLANNED_ANOVA_EFFECTS
    output["tested_family_size"] = int(finite.sum())
    reportable = output["reportable"].fillna(False).astype(bool).to_numpy()
    output["reportable_family_size"] = int((finite & reportable).sum())
    output["adjustment_method"] = "holm"
    output["alpha"] = float(alpha)
    output["p_raw"] = raw.where(finite, np.nan)
    output["p_adjusted"] = np.where(finite, adjusted, np.nan)
    output["reject_adjusted"] = finite & reportable & rejected
    return output


def _complete_effect_rows(
    results: pd.DataFrame,
    *,
    effect_order: tuple[str, str, str],
    raw_effect_col: str,
    mapper: Callable[[object], str | None],
) -> pd.DataFrame:
    source = results.copy()
    source["_canonical_effect"] = source[raw_effect_col].map(mapper)
    source = source.loc[source["_canonical_effect"].notna()].copy()
    rows: list[pd.DataFrame] = []
    for effect in effect_order:
        matches = source.loc[source["_canonical_effect"].eq(effect)]
        if len(matches) == 1:
            rows.append(matches.iloc[[0]].copy())
            continue
        placeholder = {
            column: np.nan
            for column in source.columns
        }
        placeholder["_canonical_effect"] = effect
        placeholder[raw_effect_col] = effect
        placeholder["p_reported"] = np.nan
        placeholder["reportable"] = False
        placeholder["inference_status"] = "compatibility_effect_unavailable"
        rows.append(pd.DataFrame([placeholder]))
    return pd.concat(rows, ignore_index=True)


def _annotate_single_results(
    raw_results: pd.DataFrame,
    *,
    alpha: float,
) -> pd.DataFrame:
    completed = _complete_effect_rows(
        raw_results,
        effect_order=(
            "condition",
            "roi",
            "condition_roi_interaction",
        ),
        raw_effect_col="Effect",
        mapper=_canonical_single_effect,
    )
    completed["anova_inference_status"] = completed["inference_status"]
    completed["effect"] = completed["_canonical_effect"]
    completed["effect_id"] = completed["_canonical_effect"]
    completed["test_id"] = completed["_canonical_effect"].map(
        lambda effect: f"anova_compatibility::{effect}"
    )
    completed["analysis_label"] = SINGLE_ANALYSIS_LABEL
    completed["test_label"] = completed["effect"].map(
        {
            "condition": "ANOVA compatibility: Condition",
            "roi": "ANOVA compatibility: ROI",
            "condition_roi_interaction": (
                "ANOVA compatibility: Condition x ROI"
            ),
        }
    )
    completed["test_method"] = SINGLE_ANALYSIS_LABEL
    completed["estimand"] = (
        "Balanced-design within-participant omnibus F effect"
    )
    completed["alternative"] = "non-directional omnibus F test"
    completed["inference_role"] = "compatibility"
    completed["compatibility_only"] = True
    completed["headline_eligible"] = False
    completed["assumption_status"] = "exact declared grid; sphericity handled"
    completed["interpretation"] = (
        "Secondary compatibility evidence only; the primary LMM conclusion "
        "is unchanged."
    )
    reportable = completed["reportable"].fillna(False).astype(bool)
    completed["inference_status"] = np.where(
        reportable,
        "estimated_compatibility_only",
        "compatibility_p_unavailable",
    )
    completed = completed.drop(columns=["_canonical_effect"])
    return _planned_holm_correction(completed, alpha=alpha)


def _sphericity_flag(result: object) -> bool | None:
    for name in ("spher", "sphericity"):
        value = getattr(result, name, None)
        if isinstance(value, (bool, np.bool_)):
            return bool(value)
    if isinstance(result, tuple) and result:
        first = result[0]
        if isinstance(first, (bool, np.bool_)):
            return bool(first)
    return None


def _multi_cell_map(
    conditions: Sequence[str],
    rois: Sequence[str],
) -> pd.DataFrame:
    rows = []
    order = 0
    for condition in conditions:
        for roi in rois:
            order += 1
            rows.append(
                {
                    "response_cell_id": f"cell_{order:03d}",
                    "condition": condition,
                    "roi": roi,
                    "declared_order": order,
                }
            )
    return pd.DataFrame(rows)


def _tidy_mixed_anova(
    backend: pd.DataFrame,
    *,
    sphericity_met: bool | None,
) -> pd.DataFrame:
    source_col = "Source" if "Source" in backend.columns else "source"
    if source_col not in backend.columns:
        raise ValueError("Pingouin mixed_anova did not return a Source column.")
    renamed = backend.rename(
        columns={
            source_col: "Backend Effect",
            "F": "F Value",
            "DF1": "Num DF",
            "DF2": "Den DF",
            "p-unc": "Pr > F",
            "p-GG-corr": "Pr > F (GG)",
            "np2": "partial eta squared",
            "eps": "epsilon",
        }
    ).copy()
    required = ["F Value", "Num DF", "Den DF", "Pr > F"]
    missing = [column for column in required if column not in renamed.columns]
    if missing:
        raise ValueError(
            "Pingouin mixed_anova omitted required columns: "
            + ", ".join(missing)
        )
    for column in [
        "F Value",
        "Num DF",
        "Den DF",
        "Pr > F",
        "Pr > F (GG)",
        "partial eta squared",
        "epsilon",
    ]:
        if column not in renamed.columns:
            renamed[column] = np.nan
        renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
    renamed["_canonical_effect"] = renamed["Backend Effect"].map(
        _canonical_multi_effect
    )
    response_rows = renamed.loc[
        renamed["_canonical_effect"].eq("response_cell")
    ]
    epsilon = (
        float(response_rows.iloc[0]["epsilon"])
        if len(response_rows) == 1
        and np.isfinite(float(response_rows.iloc[0]["epsilon"]))
        else np.nan
    )
    p_gg_values: list[float] = []
    correction_sources: list[str] = []
    decisions = []
    for _, row in renamed.iterrows():
        effect = row["_canonical_effect"]
        p_gg = float(row["Pr > F (GG)"])
        correction_source = (
            "pingouin"
            if np.isfinite(p_gg)
            else "not_available"
        )
        if (
            effect in {"response_cell", "group_response_cell_interaction"}
            and not np.isfinite(p_gg)
            and np.isfinite(epsilon)
            and np.isfinite(float(row["F Value"]))
            and np.isfinite(float(row["Num DF"]))
            and np.isfinite(float(row["Den DF"]))
            and float(row["Num DF"]) > 1.0
        ):
            p_gg = float(
                f_distribution.sf(
                    float(row["F Value"]),
                    epsilon * float(row["Num DF"]),
                    epsilon * float(row["Den DF"]),
                )
            )
            correction_source = (
                "derived_from_response_cell_epsilon"
                if effect == "group_response_cell_interaction"
                else "derived_from_backend_epsilon"
            )
        p_gg_values.append(p_gg)
        correction_sources.append(correction_source)
        decisions.append(
            resolve_rm_anova_inference(
                p_uncorrected=row["Pr > F"],
                numerator_df=row["Num DF"],
                p_greenhouse_geisser=p_gg,
                sphericity_met=(
                    sphericity_met
                    if effect
                    in {
                        "response_cell",
                        "group_response_cell_interaction",
                    }
                    else None
                ),
            )
        )
    renamed["Pr > F (GG)"] = p_gg_values
    renamed["correction_source"] = correction_sources
    renamed["Sphericity (bool)"] = [
        (
            sphericity_met
            if effect
            in {"response_cell", "group_response_cell_interaction"}
            else pd.NA
        )
        for effect in renamed["_canonical_effect"]
    ]
    renamed["p_raw_or_uncorrected"] = [
        decision.p_raw_or_uncorrected for decision in decisions
    ]
    renamed["p_reported"] = [
        decision.p_reported for decision in decisions
    ]
    renamed["p_correction"] = [
        decision.p_correction for decision in decisions
    ]
    renamed["inference_status"] = [
        decision.inference_status for decision in decisions
    ]
    renamed["reportable"] = [
        decision.reportable for decision in decisions
    ]
    return renamed


def _annotate_multi_results(
    raw_results: pd.DataFrame,
    *,
    alpha: float,
    group_pair: tuple[str, str],
) -> pd.DataFrame:
    completed = _complete_effect_rows(
        raw_results,
        effect_order=(
            "group",
            "response_cell",
            "group_response_cell_interaction",
        ),
        raw_effect_col="Backend Effect",
        mapper=_canonical_multi_effect,
    )
    completed["anova_inference_status"] = completed["inference_status"]
    completed["effect"] = completed["_canonical_effect"]
    completed["effect_id"] = completed["_canonical_effect"]
    completed["Effect"] = completed["effect"].map(
        {
            "group": "Group",
            "response_cell": "response-cell",
            "group_response_cell_interaction": "Group x response-cell",
        }
    )
    completed["test_id"] = completed["effect"].map(
        lambda effect: f"anova_compatibility::{effect}"
    )
    completed["analysis_label"] = MULTI_ANALYSIS_LABEL
    completed["test_label"] = completed["Effect"].map(
        lambda effect: f"{MULTI_ANALYSIS_LABEL}: {effect}"
    )
    completed["test_method"] = MULTI_ANALYSIS_LABEL
    completed["estimand"] = (
        "Broad balanced-design response-surface omnibus F effect"
    )
    completed["alternative"] = "non-directional omnibus F test"
    completed["inference_role"] = "compatibility"
    completed["compatibility_only"] = True
    completed["compatibility_scope"] = "between_group_response_surface"
    completed["headline_eligible"] = False
    completed["selected_group_pair"] = f"{group_pair[0]} vs {group_pair[1]}"
    completed["assumption_status"] = (
        "exact declared grid; equal group sizes; sphericity handled"
    )
    completed["interpretation"] = MULTI_LIMITATION
    reportable = completed["reportable"].fillna(False).astype(bool)
    completed["inference_status"] = np.where(
        reportable,
        "estimated_compatibility_only",
        "compatibility_p_unavailable",
    )
    completed = completed.drop(columns=["_canonical_effect"])
    return _planned_holm_correction(completed, alpha=alpha)


def run_single_anova_compatibility(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    frozen_participants: Sequence[object],
    retained_conditions: Sequence[object],
    selected_rois: Sequence[object],
    alpha: float = 0.05,
    log_func: Callable[[str], None] | None = None,
) -> AnovaCompatibilityBundle:
    """Run a two-way RM-ANOVA only on an exact declared balanced grid."""

    prepared = _prepare_exact_grid(
        data,
        dv_col=dv_col,
        subject_col=subject_col,
        condition_col=condition_col,
        roi_col=roi_col,
        frozen_participants=frozen_participants,
        retained_conditions=retained_conditions,
        selected_rois=selected_rois,
    )
    if not prepared.audit.eligible:
        return _skipped_bundle(mode="single", audit=prepared.audit)
    try:
        raw = run_repeated_measures_anova(
            prepared.data,
            dv_col=dv_col,
            within_cols=[condition_col, roi_col],
            subject_col=subject_col,
            raw_df=prepared.data,
            log_func=log_func,
        )
        results = _annotate_single_results(raw, alpha=float(alpha))
    except Exception as exc:
        return _skipped_bundle(
            mode="single",
            audit=prepared.audit,
            status_code="single_anova_backend_unavailable",
            message=(
                "The balanced-design ANOVA compatibility check was skipped "
                f"because the supported backend was unavailable: "
                f"{type(exc).__name__}: {exc}"
            ),
        )
    complete = bool(results["reportable"].fillna(False).astype(bool).all())
    return AnovaCompatibilityBundle(
        mode="single",
        status="completed" if complete else "partial",
        status_code=(
            "single_anova_compatibility_completed"
            if complete
            else "single_anova_compatibility_partial"
        ),
        message=(
            "Balanced-data repeated-measures ANOVA compatibility check "
            + (
                "completed."
                if complete
                else "completed with at least one non-reportable effect."
            )
        ),
        audit=prepared.audit,
        results=results,
        response_cell_map=pd.DataFrame(),
    )


def run_multigroup_anova_compatibility(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    condition_col: str,
    roi_col: str,
    group_col: str,
    frozen_participants: Sequence[object],
    retained_conditions: Sequence[object],
    selected_rois: Sequence[object],
    canonical_group_ids: Mapping[object, object],
    group_pair: Sequence[object] | None = None,
    alpha: float = 0.05,
    log_func: Callable[[str], None] | None = None,
) -> AnovaCompatibilityBundle:
    """Run the broad balanced two-group response-cell mixed ANOVA."""

    prepared = _prepare_exact_grid(
        data,
        dv_col=dv_col,
        subject_col=subject_col,
        condition_col=condition_col,
        roi_col=roi_col,
        frozen_participants=frozen_participants,
        retained_conditions=retained_conditions,
        selected_rois=selected_rois,
        group_col=group_col,
        canonical_group_ids=canonical_group_ids,
        group_pair=group_pair,
    )
    cell_map = _multi_cell_map(prepared.conditions, prepared.rois)
    if not prepared.audit.eligible:
        return _skipped_bundle(
            mode="multi",
            audit=prepared.audit,
            response_cell_map=cell_map,
        )
    pair = tuple(_text(value) for value in (group_pair or ()))
    if len(pair) != 2:
        return _skipped_bundle(
            mode="multi",
            audit=prepared.audit,
            status_code="selected_group_pair_required",
            message="The two canonical groups were not supplied.",
            response_cell_map=cell_map,
        )
    id_by_cell = {
        (row.condition, row.roi): row.response_cell_id
        for row in cell_map.itertuples(index=False)
    }
    subject_ids = {
        participant: f"subject_{index:03d}"
        for index, participant in enumerate(prepared.participants, start=1)
    }
    backend_data = prepared.data.copy()
    backend_data["_compat_subject_id"] = backend_data[subject_col].map(
        subject_ids
    )
    backend_data["_compat_group_id"] = backend_data[subject_col].map(
        prepared.group_ids
    )
    backend_data["_response_cell_id"] = [
        id_by_cell[(condition, roi)]
        for condition, roi in zip(
            backend_data[condition_col],
            backend_data[roi_col],
            strict=True,
        )
    ]
    try:
        import pingouin as pg  # type: ignore

        raw = pg.mixed_anova(
            data=backend_data,
            dv=dv_col,
            within="_response_cell_id",
            subject="_compat_subject_id",
            between="_compat_group_id",
            correction=True,
            effsize="np2",
        )
        try:
            sphericity = _sphericity_flag(
                pg.sphericity(
                    data=backend_data,
                    dv=dv_col,
                    subject="_compat_subject_id",
                    within="_response_cell_id",
                )
            )
        except Exception:
            sphericity = None
        tidy = _tidy_mixed_anova(raw, sphericity_met=sphericity)
        results = _annotate_multi_results(
            tidy,
            alpha=float(alpha),
            group_pair=(pair[0], pair[1]),
        )
    except Exception as exc:
        if log_func is not None:
            log_func(
                "ANOVA compatibility backend unavailable: "
                f"{type(exc).__name__}: {exc}"
            )
        return _skipped_bundle(
            mode="multi",
            audit=prepared.audit,
            status_code="mixed_anova_backend_unavailable",
            message=(
                "The broad Group x response-cell compatibility check was "
                "skipped because Pingouin mixed_anova was unavailable: "
                f"{type(exc).__name__}: {exc}"
            ),
            response_cell_map=cell_map,
        )
    complete = bool(results["reportable"].fillna(False).astype(bool).all())
    return AnovaCompatibilityBundle(
        mode="multi",
        status="completed" if complete else "partial",
        status_code=(
            "multigroup_anova_compatibility_completed"
            if complete
            else "multigroup_anova_compatibility_partial"
        ),
        message=(
            f"{MULTI_ANALYSIS_LABEL} "
            + (
                "completed."
                if complete
                else "completed with at least one non-reportable effect."
            )
        ),
        audit=prepared.audit,
        results=results,
        response_cell_map=cell_map,
    )


__all__ = [
    "ANOVA_COMPATIBILITY_FAMILY_ID",
    "ANOVA_COMPATIBILITY_FAMILY_LABEL",
    "AnovaCompatibilityBundle",
    "ExactGridAudit",
    "MULTI_ANALYSIS_LABEL",
    "MULTI_LIMITATION",
    "SINGLE_ANALYSIS_LABEL",
    "run_multigroup_anova_compatibility",
    "run_single_anova_compatibility",
]

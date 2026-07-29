"""Estimated marginal contrasts from a fitted statsmodels mixed model.

The helpers in this module are deliberately GUI-neutral.  They evaluate
prespecified contrasts from the fixed-effect design and covariance of the
same fitted ``MixedLM`` result used for omnibus inference.  Prediction grids
are equal-weighted; they are never appended to the observed data and missing
dependent-variable values are never imputed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Literal

import numpy as np
import pandas as pd


CONTRAST_METHOD_LABEL = "LMM-derived model-estimated contrast"
WALD_METHOD_LABEL = "Asymptotic Wald z test (two-sided)"
CONTRAST_COLUMNS = (
    "contrast_id",
    "contrast_type",
    "comparison_level",
    "reference_level",
    "contrast_sign",
    "estimand",
    "condition",
    "roi",
    "group_a",
    "group_b",
    "estimate",
    "std_error",
    "ci_low",
    "ci_high",
    "z_value",
    "p_value_wald",
    "p_raw",
    "alternative",
    "confidence_level",
    "status",
    "reportable",
    "method_label",
    "inference_method",
    "coverage",
    "required_cell_count",
    "observed_cell_count",
    "n_comparison_observations",
    "n_reference_observations",
    "n_comparison_participants",
    "n_reference_participants",
    "missing_values_imputed",
    "structurally_missing_cells",
    "error",
)


@dataclass(frozen=True)
class LMMContrastSpec:
    """One comparison-minus-reference fixed-effect grid contrast."""

    contrast_id: str
    contrast_type: str
    comparison_grid: pd.DataFrame
    reference_grid: pd.DataFrame
    comparison_level: object
    reference_level: object
    contrast_sign: str
    estimand: str
    context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _FixedEffectState:
    design_info: object
    coefficients: np.ndarray
    covariance: np.ndarray


def _empty_contrasts() -> pd.DataFrame:
    return pd.DataFrame(columns=list(CONTRAST_COLUMNS))


def _as_levels(
    data: pd.DataFrame,
    column: str,
    requested: Sequence[object] | None,
) -> tuple[object, ...]:
    if column not in data.columns:
        raise ValueError(f"Contrast data are missing required column {column!r}.")
    if requested is not None:
        levels = tuple(requested)
    elif isinstance(data[column].dtype, pd.CategoricalDtype):
        levels = tuple(data[column].cat.categories.tolist())
    else:
        levels = tuple(pd.unique(data[column].dropna()))
    if not levels:
        raise ValueError(f"No levels were declared for {column!r}.")
    if any(pd.isna(level) for level in levels):
        raise ValueError(f"Levels for {column!r} cannot contain missing values.")
    if len(pd.Index(levels).unique()) != len(levels):
        raise ValueError(f"Levels for {column!r} must be unique.")
    return levels


def _as_pairs(
    levels: Sequence[object],
    requested: Sequence[tuple[object, object]] | None,
    *,
    factor_label: str,
) -> tuple[tuple[object, object], ...]:
    """Return ordered ``comparison, reference`` pairs."""

    level_tuple = tuple(levels)
    pairs = (
        tuple(requested)
        if requested is not None
        else tuple((first, second) for first, second in combinations(level_tuple, 2))
    )
    known = set(level_tuple)
    for pair in pairs:
        if len(pair) != 2:
            raise ValueError(
                f"Each {factor_label} contrast must contain comparison and reference."
            )
        comparison, reference = pair
        if comparison == reference:
            raise ValueError(f"{factor_label} contrast levels must be different.")
        if comparison not in known or reference not in known:
            raise ValueError(
                f"Unknown {factor_label} contrast {comparison!r} - {reference!r}."
            )
    return pairs


def _grid(**columns: Sequence[object]) -> pd.DataFrame:
    names = tuple(columns)
    values = tuple(tuple(columns[name]) for name in names)
    return pd.DataFrame.from_records(
        (dict(zip(names, row, strict=True)) for row in product(*values)),
        columns=list(names),
    )


def _fixed_effect_state(result: object) -> _FixedEffectState:
    try:
        design_info = getattr(getattr(getattr(result, "model"), "data"), "design_info")
        design_names = list(design_info.column_names)
        fixed_parameters = getattr(result, "fe_params")
        covariance_all = getattr(result, "cov_params")()
    except Exception as exc:
        raise ValueError(
            "A fitted statsmodels formula MixedLM result with fixed-effect "
            "design information and covariance is required."
        ) from exc

    if isinstance(fixed_parameters, pd.Series):
        missing_names = [name for name in design_names if name not in fixed_parameters.index]
        if missing_names:
            raise ValueError(
                "The fitted model is missing fixed-effect coefficients for "
                f"{missing_names}."
            )
        coefficients = fixed_parameters.loc[design_names].to_numpy(dtype=float)
    else:
        coefficients = np.asarray(fixed_parameters, dtype=float)
        if coefficients.shape != (len(design_names),):
            raise ValueError(
                "The fitted fixed-effect coefficient vector does not match its design."
            )

    if isinstance(covariance_all, pd.DataFrame):
        missing_covariance = [
            name
            for name in design_names
            if name not in covariance_all.index or name not in covariance_all.columns
        ]
        if missing_covariance:
            raise ValueError(
                "The fitted covariance is missing fixed-effect terms "
                f"{missing_covariance}."
            )
        covariance = covariance_all.loc[design_names, design_names].to_numpy(
            dtype=float
        )
    else:
        covariance = np.asarray(covariance_all, dtype=float)
        if covariance.ndim != 2 or min(covariance.shape) < len(design_names):
            raise ValueError(
                "The fitted covariance matrix does not cover all fixed effects."
            )
        covariance = covariance[: len(design_names), : len(design_names)]

    if not np.isfinite(coefficients).all() or not np.isfinite(covariance).all():
        raise ValueError("The fitted fixed-effect estimates or covariance are non-finite.")
    return _FixedEffectState(
        design_info=design_info,
        coefficients=coefficients,
        covariance=covariance,
    )


def _model_dv_column(result: object, requested: str | None) -> str:
    if requested:
        return requested
    endog_name = getattr(getattr(result, "model", None), "endog_names", None)
    if isinstance(endog_name, str) and endog_name:
        return endog_name
    raise ValueError(
        "dv_col is required when the fitted model does not expose one outcome name."
    )


def _finite_observations(
    data: pd.DataFrame,
    *,
    dv_col: str,
    required_columns: Iterable[str],
) -> pd.DataFrame:
    required = tuple(dict.fromkeys((dv_col, *required_columns)))
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise ValueError(f"Contrast data are missing required columns: {missing}.")
    finite = pd.to_numeric(data[dv_col], errors="coerce").replace(
        [np.inf, -np.inf], np.nan
    )
    mask = finite.notna() & data[list(required[1:])].notna().all(axis=1)
    return data.loc[mask].copy()


def _cell_mask(data: pd.DataFrame, row: pd.Series) -> pd.Series:
    mask = pd.Series(True, index=data.index, dtype=bool)
    for column, value in row.items():
        mask &= data[column].eq(value)
    return mask


def _grid_coverage(
    observed: pd.DataFrame,
    grid: pd.DataFrame,
    *,
    participant_col: str,
) -> tuple[int, int, list[dict[str, object]]]:
    observation_count = 0
    participants: set[object] = set()
    missing_cells: list[dict[str, object]] = []
    for _, cell in grid.drop_duplicates().iterrows():
        matched = observed.loc[_cell_mask(observed, cell)]
        if matched.empty:
            missing_cells.append(cell.to_dict())
            continue
        observation_count += len(matched)
        participants.update(matched[participant_col].dropna().tolist())
    return observation_count, len(participants), missing_cells


def _format_cells(cells: Sequence[dict[str, object]]) -> str:
    return "; ".join(
        ", ".join(f"{column}={value}" for column, value in cell.items())
        for cell in cells
    )


def _base_row(
    spec: LMMContrastSpec,
    *,
    ci_level: float,
    comparison_observations: int,
    reference_observations: int,
    comparison_participants: int,
    reference_participants: int,
    required_cell_count: int,
    observed_cell_count: int,
    missing_cells: Sequence[dict[str, object]],
) -> dict[str, object]:
    coverage = (
        f"comparison: {comparison_participants} participants/"
        f"{comparison_observations} observations; reference: "
        f"{reference_participants} participants/{reference_observations} "
        f"observations; {observed_cell_count}/{required_cell_count} required "
        "model cells observed; no imputation"
    )
    return {
        "contrast_id": spec.contrast_id,
        "contrast_type": spec.contrast_type,
        "comparison_level": spec.comparison_level,
        "reference_level": spec.reference_level,
        "contrast_sign": spec.contrast_sign,
        "estimand": spec.estimand,
        "condition": spec.context.get("condition", pd.NA),
        "roi": spec.context.get("roi", pd.NA),
        "group_a": spec.context.get("group_a", pd.NA),
        "group_b": spec.context.get("group_b", pd.NA),
        "estimate": np.nan,
        "std_error": np.nan,
        "ci_low": np.nan,
        "ci_high": np.nan,
        "z_value": np.nan,
        "p_value_wald": np.nan,
        "p_raw": np.nan,
        "alternative": "two-sided",
        "confidence_level": float(ci_level),
        "status": "not_estimable",
        "reportable": False,
        "method_label": CONTRAST_METHOD_LABEL,
        "inference_method": WALD_METHOD_LABEL,
        "coverage": coverage,
        "required_cell_count": required_cell_count,
        "observed_cell_count": observed_cell_count,
        "n_comparison_observations": comparison_observations,
        "n_reference_observations": reference_observations,
        "n_comparison_participants": comparison_participants,
        "n_reference_participants": reference_participants,
        "missing_values_imputed": False,
        "structurally_missing_cells": _format_cells(missing_cells),
        "error": "",
    }


def estimate_lmm_contrasts(
    result: object,
    observed_data: pd.DataFrame,
    specs: Sequence[LMMContrastSpec],
    *,
    participant_col: str = "participant_id",
    dv_col: str | None = None,
    ci_level: float = 0.95,
) -> pd.DataFrame:
    """Evaluate equal-weight grid contrasts from one fitted ``MixedLM`` result.

    A structurally missing prediction cell produces a non-estimable output row.
    Partially observed participant cells only reduce the exported coverage
    counts; they are not imputed and do not prevent otherwise estimable
    contrasts.
    """

    if not 0.0 < float(ci_level) < 1.0:
        raise ValueError("ci_level must be strictly between zero and one.")
    if participant_col not in observed_data.columns:
        raise ValueError(
            f"Contrast data are missing participant column {participant_col!r}."
        )
    if not specs:
        return _empty_contrasts()

    from patsy import build_design_matrices
    from scipy.stats import norm

    fixed = _fixed_effect_state(result)
    outcome = _model_dv_column(result, dv_col)
    required_grid_columns = tuple(
        dict.fromkeys(
            column
            for spec in specs
            for column in (
                *spec.comparison_grid.columns,
                *spec.reference_grid.columns,
            )
        )
    )
    observed = _finite_observations(
        observed_data,
        dv_col=outcome,
        required_columns=(*required_grid_columns, participant_col),
    )
    critical = float(norm.ppf(1.0 - (1.0 - float(ci_level)) / 2.0))
    rows: list[dict[str, object]] = []

    for spec in specs:
        comparison = spec.comparison_grid.copy()
        reference = spec.reference_grid.copy()
        if comparison.empty or reference.empty:
            raise ValueError(
                f"Contrast {spec.contrast_id!r} contains an empty prediction grid."
            )
        if set(comparison.columns) != set(reference.columns):
            raise ValueError(
                f"Contrast {spec.contrast_id!r} grids use different factors."
            )
        reference = reference.loc[:, comparison.columns]
        if (
            comparison.isna().any(axis=None)
            or reference.isna().any(axis=None)
            or comparison.duplicated().any()
            or reference.duplicated().any()
        ):
            raise ValueError(
                f"Contrast {spec.contrast_id!r} grids must contain unique, finite cells."
            )

        comp_n, comp_participants, comp_missing = _grid_coverage(
            observed,
            comparison,
            participant_col=participant_col,
        )
        ref_n, ref_participants, ref_missing = _grid_coverage(
            observed,
            reference,
            participant_col=participant_col,
        )
        all_required = pd.concat([comparison, reference], ignore_index=True).drop_duplicates()
        all_missing = comp_missing + [
            cell for cell in ref_missing if cell not in comp_missing
        ]
        row = _base_row(
            spec,
            ci_level=float(ci_level),
            comparison_observations=comp_n,
            reference_observations=ref_n,
            comparison_participants=comp_participants,
            reference_participants=ref_participants,
            required_cell_count=len(all_required),
            observed_cell_count=len(all_required) - len(all_missing),
            missing_cells=all_missing,
        )
        if all_missing:
            row["error"] = (
                "Required fixed-effect cells were not observed; the declared "
                "equal-weight estimand is structurally non-estimable."
            )
            rows.append(row)
            continue

        try:
            comparison_design = np.asarray(
                build_design_matrices([fixed.design_info], comparison)[0],
                dtype=float,
            )
            reference_design = np.asarray(
                build_design_matrices([fixed.design_info], reference)[0],
                dtype=float,
            )
            contrast = comparison_design.mean(axis=0) - reference_design.mean(axis=0)
            estimate = float(contrast @ fixed.coefficients)
            variance = float(contrast @ fixed.covariance @ contrast)
            tolerance = np.finfo(float).eps * max(
                1.0,
                float(np.linalg.norm(fixed.covariance, ord=np.inf)),
            )
            if variance < -tolerance or not np.isfinite(variance):
                raise ValueError(f"invalid contrast variance {variance}")
            standard_error = float(np.sqrt(max(0.0, variance)))
            if standard_error <= 0.0:
                raise ValueError("contrast standard error is zero")
            z_value = estimate / standard_error
            p_value = float(2.0 * norm.sf(abs(z_value)))
            row.update(
                {
                    "estimate": estimate,
                    "std_error": standard_error,
                    "ci_low": estimate - critical * standard_error,
                    "ci_high": estimate + critical * standard_error,
                    "z_value": z_value,
                    "p_value_wald": p_value,
                    "p_raw": p_value,
                    "status": "estimated",
                    "reportable": True,
                }
            )
        except Exception as exc:  # noqa: BLE001 - one failed contrast stays explicit
            row["status"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(row)

    return pd.DataFrame(rows).reindex(columns=list(CONTRAST_COLUMNS))


def estimate_condition_within_roi_contrasts(
    result: object,
    observed_data: pd.DataFrame,
    *,
    participant_col: str = "participant_id",
    dv_col: str | None = None,
    condition_col: str = "condition",
    roi_col: str = "roi",
    condition_levels: Sequence[object] | None = None,
    roi_levels: Sequence[object] | None = None,
    condition_pairs: Sequence[tuple[object, object]] | None = None,
    group_col: str | None = None,
    group_levels: Sequence[object] | None = None,
    ci_level: float = 0.95,
) -> pd.DataFrame:
    """Estimate Condition contrasts within each ROI, equally weighted over Group."""

    conditions = _as_levels(observed_data, condition_col, condition_levels)
    rois = _as_levels(observed_data, roi_col, roi_levels)
    pairs = _as_pairs(conditions, condition_pairs, factor_label="Condition")
    groups = (
        _as_levels(observed_data, group_col, group_levels)
        if group_col is not None
        else ()
    )
    specs: list[LMMContrastSpec] = []
    for roi in rois:
        for comparison, reference in pairs:
            fixed = {roi_col: (roi,)}
            if group_col is not None:
                fixed[group_col] = groups
            comparison_grid = _grid(
                **{condition_col: (comparison,), **fixed}
            )
            reference_grid = _grid(
                **{condition_col: (reference,), **fixed}
            )
            sign = f"{comparison} - {reference}"
            specs.append(
                LMMContrastSpec(
                    contrast_id=f"condition_within_roi::{roi}::{sign}",
                    contrast_type="condition_within_roi",
                    comparison_grid=comparison_grid,
                    reference_grid=reference_grid,
                    comparison_level=comparison,
                    reference_level=reference,
                    contrast_sign=sign,
                    estimand=(
                        "Equal-weight model-estimated Condition contrast "
                        f"within ROI {roi}: {sign}"
                    ),
                    context={"roi": roi},
                )
            )
    return estimate_lmm_contrasts(
        result,
        observed_data,
        specs,
        participant_col=participant_col,
        dv_col=dv_col,
        ci_level=ci_level,
    )


def estimate_roi_within_condition_contrasts(
    result: object,
    observed_data: pd.DataFrame,
    *,
    participant_col: str = "participant_id",
    dv_col: str | None = None,
    condition_col: str = "condition",
    roi_col: str = "roi",
    condition_levels: Sequence[object] | None = None,
    roi_levels: Sequence[object] | None = None,
    roi_pairs: Sequence[tuple[object, object]] | None = None,
    group_col: str | None = None,
    group_levels: Sequence[object] | None = None,
    ci_level: float = 0.95,
) -> pd.DataFrame:
    """Estimate ROI contrasts within each Condition, equally weighted over Group."""

    conditions = _as_levels(observed_data, condition_col, condition_levels)
    rois = _as_levels(observed_data, roi_col, roi_levels)
    pairs = _as_pairs(rois, roi_pairs, factor_label="ROI")
    groups = (
        _as_levels(observed_data, group_col, group_levels)
        if group_col is not None
        else ()
    )
    specs: list[LMMContrastSpec] = []
    for condition in conditions:
        for comparison, reference in pairs:
            fixed = {condition_col: (condition,)}
            if group_col is not None:
                fixed[group_col] = groups
            comparison_grid = _grid(**{roi_col: (comparison,), **fixed})
            reference_grid = _grid(**{roi_col: (reference,), **fixed})
            sign = f"{comparison} - {reference}"
            specs.append(
                LMMContrastSpec(
                    contrast_id=f"roi_within_condition::{condition}::{sign}",
                    contrast_type="roi_within_condition",
                    comparison_grid=comparison_grid,
                    reference_grid=reference_grid,
                    comparison_level=comparison,
                    reference_level=reference,
                    contrast_sign=sign,
                    estimand=(
                        "Equal-weight model-estimated ROI contrast within "
                        f"Condition {condition}: {sign}"
                    ),
                    context={"condition": condition},
                )
            )
    return estimate_lmm_contrasts(
        result,
        observed_data,
        specs,
        participant_col=participant_col,
        dv_col=dv_col,
        ci_level=ci_level,
    )


def estimate_group_cell_contrasts(
    result: object,
    observed_data: pd.DataFrame,
    *,
    group_a: object,
    group_b: object,
    participant_col: str = "participant_id",
    dv_col: str | None = None,
    group_col: str = "group_id",
    condition_col: str = "condition",
    roi_col: str = "roi",
    condition_levels: Sequence[object] | None = None,
    roi_levels: Sequence[object] | None = None,
    ci_level: float = 0.95,
) -> pd.DataFrame:
    """Estimate Group A minus Group B in every declared Condition x ROI cell."""

    groups = _as_levels(observed_data, group_col, (group_a, group_b))
    if groups[0] == groups[1]:
        raise ValueError("Group A and Group B must be different.")
    conditions = _as_levels(observed_data, condition_col, condition_levels)
    rois = _as_levels(observed_data, roi_col, roi_levels)
    sign = f"{group_a} - {group_b}"
    specs: list[LMMContrastSpec] = []
    for condition, roi in product(conditions, rois):
        comparison_grid = _grid(
            **{
                group_col: (group_a,),
                condition_col: (condition,),
                roi_col: (roi,),
            }
        )
        reference_grid = _grid(
            **{
                group_col: (group_b,),
                condition_col: (condition,),
                roi_col: (roi,),
            }
        )
        specs.append(
            LMMContrastSpec(
                contrast_id=f"group_cell::{condition}::{roi}::{sign}",
                contrast_type="group_within_condition_roi",
                comparison_grid=comparison_grid,
                reference_grid=reference_grid,
                comparison_level=group_a,
                reference_level=group_b,
                contrast_sign=sign,
                estimand=(
                    f"Model-estimated {sign} contrast within Condition "
                    f"{condition} and ROI {roi}"
                ),
                context={
                    "condition": condition,
                    "roi": roi,
                    "group_a": group_a,
                    "group_b": group_b,
                },
            )
        )
    return estimate_lmm_contrasts(
        result,
        observed_data,
        specs,
        participant_col=participant_col,
        dv_col=dv_col,
        ci_level=ci_level,
    )


def estimate_marginal_group_contrasts(
    result: object,
    observed_data: pd.DataFrame,
    *,
    group_a: object,
    group_b: object,
    by: Literal["overall", "condition", "roi"] = "overall",
    participant_col: str = "participant_id",
    dv_col: str | None = None,
    group_col: str = "group_id",
    condition_col: str = "condition",
    roi_col: str = "roi",
    condition_levels: Sequence[object] | None = None,
    roi_levels: Sequence[object] | None = None,
    ci_level: float = 0.95,
) -> pd.DataFrame:
    """Estimate an equal-weight Group A minus Group B marginal contrast."""

    if by not in {"overall", "condition", "roi"}:
        raise ValueError("by must be 'overall', 'condition', or 'roi'.")
    _as_levels(observed_data, group_col, (group_a, group_b))
    if group_a == group_b:
        raise ValueError("Group A and Group B must be different.")
    conditions = _as_levels(observed_data, condition_col, condition_levels)
    rois = _as_levels(observed_data, roi_col, roi_levels)
    sign = f"{group_a} - {group_b}"
    contexts: list[dict[str, object]]
    if by == "condition":
        contexts = [{"condition": condition} for condition in conditions]
    elif by == "roi":
        contexts = [{"roi": roi} for roi in rois]
    else:
        contexts = [{}]

    specs: list[LMMContrastSpec] = []
    for context in contexts:
        grid_conditions = (
            (context["condition"],) if "condition" in context else conditions
        )
        grid_rois = (context["roi"],) if "roi" in context else rois
        comparison_grid = _grid(
            **{
                group_col: (group_a,),
                condition_col: grid_conditions,
                roi_col: grid_rois,
            }
        )
        reference_grid = _grid(
            **{
                group_col: (group_b,),
                condition_col: grid_conditions,
                roi_col: grid_rois,
            }
        )
        qualifier = (
            f" within Condition {context['condition']}"
            if "condition" in context
            else (
                f" within ROI {context['roi']}"
                if "roi" in context
                else " across the declared Condition x ROI grid"
            )
        )
        context_id = (
            str(context.get("condition", context.get("roi", "overall")))
        )
        specs.append(
            LMMContrastSpec(
                contrast_id=f"group_marginal::{by}::{context_id}::{sign}",
                contrast_type=f"group_marginal_by_{by}",
                comparison_grid=comparison_grid,
                reference_grid=reference_grid,
                comparison_level=group_a,
                reference_level=group_b,
                contrast_sign=sign,
                estimand=f"Equal-weight model-estimated {sign} contrast{qualifier}",
                context={
                    **context,
                    "group_a": group_a,
                    "group_b": group_b,
                },
            )
        )
    return estimate_lmm_contrasts(
        result,
        observed_data,
        specs,
        participant_col=participant_col,
        dv_col=dv_col,
        ci_level=ci_level,
    )


__all__ = [
    "CONTRAST_METHOD_LABEL",
    "WALD_METHOD_LABEL",
    "LMMContrastSpec",
    "estimate_condition_within_roi_contrasts",
    "estimate_group_cell_contrasts",
    "estimate_lmm_contrasts",
    "estimate_marginal_group_contrasts",
    "estimate_roi_within_condition_contrasts",
]

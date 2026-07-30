"""GUI-neutral native multi-group mixed-model analysis."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
import warnings

import numpy as np
import pandas as pd

from Tools.Stats.common.blas_limits import single_threaded_blas


MULTIGROUP_MODEL_SCHEMA_VERSION = 2
ALLOWED_ANALYSIS_SCOPES = frozenset({"complete_core", "available_case"})
LRT_CAVEAT = (
    "Likelihood-ratio p-values use an asymptotic chi-square reference and can be "
    "anti-conservative in small samples."
)
UNKNOWN_GROUP_ID_LABELS = frozenset(
    {"unknown", "unassigned", "none", "nan", "missing"}
)


class MultigroupModelValidationError(ValueError):
    """Raised when observed data cannot identify the requested model."""

    def __init__(self, message: str, diagnostics: pd.DataFrame | None = None):
        super().__init__(message)
        self.diagnostics = (
            diagnostics.copy()
            if isinstance(diagnostics, pd.DataFrame)
            else pd.DataFrame()
        )


@dataclass(frozen=True)
class OmnibusComparison:
    """One hierarchy-preserving full-versus-reduced ML comparison."""

    effect_id: str
    effect_label: str
    interpretation: str
    full_formula: str
    reduced_formula: str


@dataclass(frozen=True)
class MultigroupModelBundle:
    """Explicit result frames for a native multi-group mixed model."""

    status: str
    estimates: pd.DataFrame
    omnibus: pd.DataFrame
    attempts: pd.DataFrame
    diagnostics: pd.DataFrame
    metadata: pd.DataFrame
    marginal_group_contrasts: pd.DataFrame
    fitted_model: object | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    @property
    def reportable(self) -> bool:
        """Return whether final REML estimates were successfully obtained."""

        return self.status in {"ok", "partial"}

    def to_frames(self) -> dict[str, pd.DataFrame]:
        """Return export-ready copies without relying on ``DataFrame.attrs``."""

        return {
            "Fixed Effects": self.estimates.copy(),
            "Omnibus LRT": self.omnibus.copy(),
            "Fit Attempts": self.attempts.copy(),
            "Diagnostics": self.diagnostics.copy(),
            "Model Metadata": self.metadata.copy(),
            "Marginal Group Contrasts": self.marginal_group_contrasts.copy(),
        }


@dataclass(frozen=True)
class _AcceptedFit:
    result: object
    optimizer: str
    re_formula: str


def _factor_term(column: str) -> str:
    return f"C({column}, Sum)"


def build_multigroup_omnibus_comparisons(
    *,
    dv_col: str = "value",
    group_col: str = "group_id",
    condition_col: str = "condition",
    roi_col: str = "roi",
) -> tuple[OmnibusComparison, ...]:
    """Return the exact hierarchy-preserving multi-group omnibus formulas."""

    for label, column in {
        "DV": dv_col,
        "group": group_col,
        "condition": condition_col,
        "ROI": roi_col,
    }.items():
        if not str(column).isidentifier():
            raise ValueError(
                f"{label} column {column!r} is not a formula-safe identifier."
            )

    group = _factor_term(group_col)
    condition = _factor_term(condition_col)
    roi = _factor_term(roi_col)
    full = f"{dv_col} ~ {group} * {condition} * {roi}"
    return (
        OmnibusComparison(
            effect_id="any_group_related",
            effect_label="Any group-related effect (joint block)",
            interpretation=(
                "Jointly tests every fixed-effect term containing group; this is "
                "not a pure group main-effect test."
            ),
            full_formula=full,
            reduced_formula=f"{dv_col} ~ {condition} * {roi}",
        ),
        OmnibusComparison(
            effect_id="group_condition_roi_interaction",
            effect_label="Group x Condition x ROI interaction",
            interpretation="Tests only the three-way Group x Condition x ROI term.",
            full_formula=full,
            reduced_formula=(
                f"{dv_col} ~ {group} * {condition} + "
                f"{group} * {roi} + {condition} * {roi}"
            ),
        ),
        OmnibusComparison(
            effect_id="group_condition_block",
            effect_label="Group x Condition-related block",
            interpretation=(
                "Tests Group x Condition and the three-way term jointly while "
                "retaining Group x ROI and Condition x ROI."
            ),
            full_formula=full,
            reduced_formula=f"{dv_col} ~ {group} * {roi} + {condition} * {roi}",
        ),
        OmnibusComparison(
            effect_id="group_roi_block",
            effect_label="Group x ROI-related block",
            interpretation=(
                "Tests Group x ROI and the three-way term jointly while retaining "
                "Group x Condition and Condition x ROI."
            ),
            full_formula=full,
            reduced_formula=(
                f"{dv_col} ~ {group} * {condition} + {condition} * {roi}"
            ),
        ),
    )


def _diagnostic_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["check_id", "status", "value", "threshold", "message"],
    )


def _validation_error(
    message: str,
    diagnostics: list[dict[str, object]],
) -> MultigroupModelValidationError:
    return MultigroupModelValidationError(message, _diagnostic_frame(diagnostics))


def _ordered_levels(series: pd.Series) -> tuple[object, ...]:
    return tuple(sorted(pd.unique(series).tolist(), key=lambda value: str(value).casefold()))


def _validate_model_data(
    data: pd.DataFrame,
    *,
    dv_col: str,
    participant_col: str,
    group_col: str,
    condition_col: str,
    roi_col: str,
    known_group_ids: Sequence[object] | None,
    full_formula: str,
    analysis_scope: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, tuple[object, ...]]]:
    diagnostics: list[dict[str, object]] = []
    scope = str(analysis_scope).strip().casefold().replace("-", "_")
    if scope not in ALLOWED_ANALYSIS_SCOPES:
        raise _validation_error(
            "analysis_scope must be 'complete_core' or 'available_case'.",
            diagnostics,
        )
    required = [dv_col, participant_col, group_col, condition_col, roi_col]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise _validation_error(
            f"Missing required multi-group model columns: {missing}.",
            diagnostics,
        )
    for column in required:
        if not str(column).isidentifier():
            raise _validation_error(
                f"Column {column!r} is not a formula-safe identifier.",
                diagnostics,
            )

    working = data.loc[:, required].copy().reset_index(drop=True)
    key_columns = [participant_col, condition_col, roi_col]
    missing_keys = working[key_columns + [group_col]].isna().any(axis=1)
    blank_keys = working[key_columns + [group_col]].apply(
        lambda column: column.map(
            lambda value: isinstance(value, str) and not value.strip()
        )
    ).any(axis=1)
    invalid_key_count = int((missing_keys | blank_keys).sum())
    diagnostics.append(
        {
            "check_id": "factor_ids_present",
            "status": "ok" if invalid_key_count == 0 else "failed",
            "value": invalid_key_count,
            "threshold": 0,
            "message": "Participant, canonical group, Condition, and ROI IDs must be present.",
        }
    )
    if invalid_key_count:
        raise _validation_error(
            "Missing or blank participant/factor IDs block multi-group modelling.",
            diagnostics,
        )

    duplicate_mask = working.duplicated(key_columns, keep=False)
    duplicate_count = int(duplicate_mask.sum())
    diagnostics.append(
        {
            "check_id": "participant_condition_roi_grain",
            "status": "ok" if duplicate_count == 0 else "failed",
            "value": duplicate_count,
            "threshold": 0,
            "message": "Exactly one row is required per participant x Condition x ROI.",
        }
    )
    if duplicate_count:
        examples = working.loc[duplicate_mask, key_columns].head(5).to_dict("records")
        raise _validation_error(
            "Duplicate participant x Condition x ROI rows block modelling. "
            f"Examples: {examples}",
            diagnostics,
        )

    numeric_dv = pd.to_numeric(working[dv_col], errors="coerce")
    finite_mask = np.isfinite(numeric_dv.to_numpy(dtype=float))
    nonfinite_count = int((~finite_mask).sum())
    diagnostics.append(
        {
            "check_id": "finite_dv",
            "status": "ok" if nonfinite_count == 0 else "failed",
            "value": nonfinite_count,
            "threshold": 0,
            "message": "Mixed-model rows require finite numeric DV values.",
        }
    )
    if nonfinite_count:
        raise _validation_error(
            "Non-finite or non-numeric DV values block mixed modelling.",
            diagnostics,
        )
    working[dv_col] = numeric_dv.astype(float)

    group_counts_by_participant = working.groupby(participant_col)[group_col].nunique()
    inconsistent_participants = group_counts_by_participant[
        group_counts_by_participant.ne(1)
    ]
    diagnostics.append(
        {
            "check_id": "canonical_group_assignment_unique",
            "status": "ok" if inconsistent_participants.empty else "failed",
            "value": int(len(inconsistent_participants)),
            "threshold": 0,
            "message": "Each participant must have one canonical group_id.",
        }
    )
    if not inconsistent_participants.empty:
        raise _validation_error(
            "A participant has more than one canonical group_id.",
            diagnostics,
        )

    levels = {
        "participants": _ordered_levels(working[participant_col]),
        "groups": _ordered_levels(working[group_col]),
        "conditions": _ordered_levels(working[condition_col]),
        "rois": _ordered_levels(working[roi_col]),
    }
    placeholder_groups = [
        group
        for group in levels["groups"]
        if str(group).strip().casefold() in UNKNOWN_GROUP_ID_LABELS
    ]
    diagnostics.append(
        {
            "check_id": "canonical_group_ids_resolved",
            "status": "ok" if not placeholder_groups else "failed",
            "value": "; ".join(map(str, placeholder_groups)),
            "threshold": "no unresolved placeholder IDs",
            "message": "Multi-group modelling requires resolved canonical group IDs.",
        }
    )
    if placeholder_groups:
        raise _validation_error(
            f"Unresolved canonical group_id values block modelling: {placeholder_groups}.",
            diagnostics,
        )
    if known_group_ids is not None:
        known = tuple(known_group_ids)
        unknown = [group for group in levels["groups"] if group not in set(known)]
        diagnostics.append(
            {
                "check_id": "canonical_group_ids_known",
                "status": "ok" if not unknown else "failed",
                "value": "; ".join(map(str, unknown)),
                "threshold": "no unknown IDs",
                "message": "Observed group IDs must belong to the canonical group registry.",
            }
        )
        if unknown:
            raise _validation_error(
                f"Unknown canonical group_id values block modelling: {unknown}.",
                diagnostics,
            )

    level_failures = {
        factor: len(levels[factor])
        for factor in ("groups", "conditions", "rois")
        if len(levels[factor]) < 2
    }
    diagnostics.append(
        {
            "check_id": "factor_levels_estimable",
            "status": "ok" if not level_failures else "failed",
            "value": str({key: len(levels[key]) for key in ("groups", "conditions", "rois")}),
            "threshold": "at least 2 levels per fixed factor",
            "message": "The requested three-factor model needs variation in every factor.",
        }
    )
    if level_failures:
        raise _validation_error(
            f"Insufficient factor levels for the full model: {level_failures}.",
            diagnostics,
        )

    participant_groups = working[[participant_col, group_col]].drop_duplicates()
    participants_per_group = participant_groups.groupby(group_col)[participant_col].nunique()
    too_small = participants_per_group[participants_per_group.lt(2)]
    diagnostics.append(
        {
            "check_id": "participants_per_group",
            "status": "ok" if too_small.empty else "failed",
            "value": str(participants_per_group.to_dict()),
            "threshold": "at least 2 participants per group",
            "message": "Between-group inference needs replication within every group.",
        }
    )
    if not too_small.empty:
        raise _validation_error(
            f"Groups with fewer than two participants block modelling: {too_small.to_dict()}.",
            diagnostics,
        )

    expected_per_participant = len(levels["conditions"]) * len(levels["rois"])
    observed_per_participant = working.groupby(participant_col).size()
    incomplete = observed_per_participant[observed_per_participant.ne(expected_per_participant)]
    expected_pairs = {
        (condition, roi)
        for condition in levels["conditions"]
        for roi in levels["rois"]
    }
    for participant, participant_rows in working.groupby(participant_col, sort=False):
        observed_pairs = set(
            participant_rows[[condition_col, roi_col]].itertuples(index=False, name=None)
        )
        if observed_pairs != expected_pairs:
            incomplete.loc[participant] = len(observed_pairs)
    diagnostics.append(
        {
            "check_id": "participant_cell_coverage",
            "status": (
                "ok"
                if incomplete.empty
                else (
                    "warning"
                    if scope == "available_case"
                    else "failed"
                )
            ),
            "value": int(len(incomplete)),
            "threshold": (
                "partial participant coverage allowed; all factorial cells observed"
                if scope == "available_case"
                else 0
            ),
            "message": (
                "Available-case rows are retained without imputation."
                if scope == "available_case" and not incomplete.empty
                else (
                    "Every participant must contribute every observed "
                    "Condition x ROI cell."
                )
            ),
        }
    )
    if scope == "complete_core" and not incomplete.empty:
        raise _validation_error(
            "Data are not a complete participant x Condition x ROI core; "
            "do not drop participants inside the model engine.",
            diagnostics,
        )

    structural_coverage = (
        working.groupby(
            [group_col, condition_col, roi_col],
            observed=False,
            dropna=False,
        )
        .size()
        .reindex(
            pd.MultiIndex.from_product(
                [
                    levels["groups"],
                    levels["conditions"],
                    levels["rois"],
                ],
                names=[group_col, condition_col, roi_col],
            ),
            fill_value=0,
        )
    )
    empty_structural_cells = structural_coverage[
        structural_coverage.eq(0)
    ]
    diagnostics.append(
        {
            "check_id": "factorial_cells_observed",
            "status": "ok" if empty_structural_cells.empty else "failed",
            "value": int(len(empty_structural_cells)),
            "threshold": 0,
            "message": (
                "Every Group x Condition x ROI fixed-effect cell must contain "
                "at least one finite observation."
            ),
        }
    )
    if not empty_structural_cells.empty:
        examples = list(empty_structural_cells.index[:5])
        raise _validation_error(
            "Structurally empty Group x Condition x ROI cells block the full "
            f"interaction model. Examples: {examples}",
            diagnostics,
        )

    for factor, column in (
        ("groups", group_col),
        ("conditions", condition_col),
        ("rois", roi_col),
    ):
        working[column] = pd.Categorical(
            working[column],
            categories=list(levels[factor]),
            ordered=True,
        )

    try:
        from patsy import dmatrices

        _, fixed_design = dmatrices(full_formula, working, return_type="dataframe")
    except Exception as exc:
        raise _validation_error(
            f"Could not build the fixed-effects design matrix: {exc}",
            diagnostics,
        ) from exc
    fixed_rank = int(np.linalg.matrix_rank(fixed_design.to_numpy(dtype=float)))
    fixed_columns = int(fixed_design.shape[1])
    residual_rows = int(len(working) - fixed_rank)
    rank_ok = fixed_rank == fixed_columns and residual_rows > 0
    diagnostics.append(
        {
            "check_id": "fixed_design_rank",
            "status": "ok" if rank_ok else "failed",
            "value": f"rank={fixed_rank}; columns={fixed_columns}; residual_rows={residual_rows}",
            "threshold": "full column rank and at least 1 residual row",
            "message": "The sum-coded fixed-effects design must be estimable.",
        }
    )
    if not rank_ok:
        raise _validation_error(
            "The fixed-effects design is rank deficient or saturated.",
            diagnostics,
        )

    diagnostics.extend(
        [
            {
                "check_id": "row_count",
                "status": "ok",
                "value": int(len(working)),
                "threshold": "",
                "message": (
                    "Available finite observed rows; missing cells were not imputed."
                    if scope == "available_case"
                    else "Complete-core analysis rows."
                ),
            },
            {
                "check_id": "participant_count",
                "status": "ok",
                "value": len(levels["participants"]),
                "threshold": "",
                "message": "Random-effect grouping units.",
            },
            {
                "check_id": "analysis_scope",
                "status": "ok",
                "value": scope,
                "threshold": "",
                "message": (
                    "Likelihood inference assumes missingness is ignorable "
                    "conditional on the modeled variables."
                    if scope == "available_case"
                    else "Balanced participant-first analysis scope."
                ),
            },
        ]
    )
    return working, _diagnostic_frame(diagnostics), levels


def _fit_mixedlm_once(
    *,
    data: pd.DataFrame,
    formula: str,
    participant_col: str,
    re_formula: str,
    reml: bool,
    optimizer: str,
    maxiter: int,
):
    import statsmodels.formula.api as smf

    model = smf.mixedlm(
        formula,
        data,
        groups=data[participant_col],
        re_formula=re_formula,
    )
    return model.fit(
        reml=reml,
        method=optimizer,
        maxiter=maxiter,
        full_output=True,
        disp=False,
    )


def _is_singular(result: object, tolerance: float) -> tuple[bool, str]:
    try:
        covariance = np.atleast_2d(np.asarray(getattr(result, "cov_re"), dtype=float))
        eigenvalues = np.linalg.eigvalsh(covariance)
    except Exception as exc:
        return True, f"random-effects covariance unavailable: {exc}"
    if not np.all(np.isfinite(eigenvalues)):
        return True, "random-effects covariance has non-finite eigenvalues"
    minimum = float(np.min(eigenvalues))
    return minimum <= tolerance, f"minimum random-effects eigenvalue={minimum:.6g}"


def _attempt_fit(
    *,
    data: pd.DataFrame,
    formula: str,
    participant_col: str,
    requested_re_formula: str,
    used_re_formula: str,
    reml: bool,
    optimizers: Sequence[str],
    maxiter: int,
    singularity_tolerance: float,
    stage: str,
    fallback_reason: str,
    attempt_rows: list[dict[str, object]],
) -> _AcceptedFit | None:
    for optimizer_index, optimizer in enumerate(optimizers):
        optimizer_reason = fallback_reason
        if optimizer_index:
            optimizer_reason = "; ".join(
                item
                for item in (fallback_reason, "previous optimizer was unacceptable")
                if item
            )
        caught_messages: tuple[str, ...] = ()
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = _fit_mixedlm_once(
                    data=data,
                    formula=formula,
                    participant_col=participant_col,
                    re_formula=used_re_formula,
                    reml=reml,
                    optimizer=str(optimizer),
                    maxiter=maxiter,
                )
            caught_messages = tuple(str(item.message) for item in caught)
            converged = bool(getattr(result, "converged", False))
            singular, singular_detail = _is_singular(result, singularity_tolerance)
            accepted = converged and not singular
            if accepted:
                status = "accepted"
            elif not converged and singular:
                status = "nonconverged_and_singular"
            elif not converged:
                status = "nonconverged"
            else:
                status = "singular"
            error = ""
        except Exception as exc:
            result = None
            converged = False
            singular = pd.NA
            singular_detail = ""
            accepted = False
            status = "error"
            error = f"{type(exc).__name__}: {exc}"

        attempt_rows.append(
            {
                "attempt_id": len(attempt_rows) + 1,
                "stage": stage,
                "method": "REML" if reml else "ML",
                "formula": formula,
                "requested_re_formula": requested_re_formula,
                "used_re_formula": used_re_formula,
                "optimizer": str(optimizer),
                "converged": converged,
                "singular": singular,
                "accepted": accepted,
                "fallback_reason": optimizer_reason,
                "status": status,
                "singularity_detail": singular_detail,
                "warnings": " | ".join(caught_messages),
                "error": error,
            }
        )
        if accepted and result is not None:
            return _AcceptedFit(
                result=result,
                optimizer=str(optimizer),
                re_formula=used_re_formula,
            )
    return None


def _fixed_effect_estimates(result: object, ci_level: float) -> pd.DataFrame:
    from scipy.stats import norm

    estimates = getattr(result, "fe_params")
    standard_errors = getattr(result, "bse_fe")
    if isinstance(estimates, pd.Series):
        terms = list(estimates.index)
        coefficients = estimates.to_numpy(dtype=float)
    else:
        coefficients = np.asarray(estimates, dtype=float)
        terms = list(getattr(getattr(result, "model", None), "exog_names", []))
    errors = np.asarray(standard_errors, dtype=float)
    if len(terms) != len(coefficients):
        terms = [f"fixed_effect_{index}" for index in range(len(coefficients))]
    z_values = coefficients / errors
    p_values = 2.0 * norm.sf(np.abs(z_values))
    critical = float(norm.ppf(1.0 - (1.0 - ci_level) / 2.0))
    return pd.DataFrame(
        {
            "term": terms,
            "estimate": coefficients,
            "std_error": errors,
            "z_value": z_values,
            "p_value_wald": p_values,
            "ci_low": coefficients - critical * errors,
            "ci_high": coefficients + critical * errors,
            "estimation_method": "REML",
            "inference_reference": "asymptotic Wald z",
            "status": "ok",
        }
    )


def _model_parameter_count(result: object) -> int:
    value = getattr(result, "df_modelwc", None)
    if value is not None and np.isfinite(float(value)):
        return int(value)
    return int(len(np.asarray(getattr(result, "params"))))


def _model_row_labels(result: object) -> tuple[object, ...] | None:
    """Return formula-model row labels when exposed by statsmodels."""

    try:
        labels = getattr(getattr(getattr(result, "model"), "data"), "row_labels")
    except (AttributeError, TypeError):
        return None
    if labels is None:
        return None
    try:
        return tuple(labels.tolist())
    except AttributeError:
        return tuple(labels)


def _failed_omnibus_row(
    comparison: OmnibusComparison,
    error: str,
) -> dict[str, object]:
    return {
        "effect_id": comparison.effect_id,
        "effect_label": comparison.effect_label,
        "interpretation": comparison.interpretation,
        "full_formula": comparison.full_formula,
        "reduced_formula": comparison.reduced_formula,
        "lr_statistic": np.nan,
        "df_difference": np.nan,
        "p_value_chi2": np.nan,
        "status": "failed",
        "reportable": False,
        "n_observations_full": np.nan,
        "n_observations_reduced": np.nan,
        "same_observed_rows": False,
        "row_identity_status": "not_checked",
        "error": error,
        "reference_distribution": "chi-square (asymptotic)",
        "caveat": LRT_CAVEAT,
    }


def _estimated_marginal_group_contrasts(
    *,
    result: object,
    working: pd.DataFrame,
    marginal_grid: pd.DataFrame | None,
    reference_group_id: object | None,
    group_col: str,
    condition_col: str,
    roi_col: str,
    levels: dict[str, tuple[object, ...]],
    ci_level: float,
) -> pd.DataFrame:
    """Average model-implied group contrasts over an explicit Condition x ROI grid."""

    if marginal_grid is None:
        return pd.DataFrame()
    required = [condition_col, roi_col]
    missing = [column for column in required if column not in marginal_grid.columns]
    if missing:
        raise MultigroupModelValidationError(
            f"Marginal contrast grid is missing columns: {missing}."
        )
    grid = marginal_grid.loc[:, required].copy()
    if grid.empty:
        raise MultigroupModelValidationError(
            "Marginal contrast grid must contain at least one Condition x ROI row."
        )
    if grid.isna().any(axis=None) or grid.duplicated(required).any():
        raise MultigroupModelValidationError(
            "Marginal contrast grid must contain unique, non-missing Condition x ROI rows."
        )
    observed_pairs = set(
        working[[condition_col, roi_col]].itertuples(index=False, name=None)
    )
    requested_pairs = set(grid.itertuples(index=False, name=None))
    unobserved = requested_pairs - observed_pairs
    if unobserved:
        raise MultigroupModelValidationError(
            f"Marginal contrast grid contains unobserved cells: {sorted(unobserved)}."
        )

    group_levels = levels["groups"]
    reference = group_levels[0] if reference_group_id is None else reference_group_id
    if reference not in group_levels:
        raise MultigroupModelValidationError(
            f"Reference group {reference!r} is not an observed canonical group_id."
        )

    try:
        from patsy import build_design_matrices
        from scipy.stats import norm

        design_info = getattr(getattr(result, "model"), "data").design_info
        fixed_parameters = getattr(result, "fe_params")
        fixed_names = (
            list(fixed_parameters.index)
            if isinstance(fixed_parameters, pd.Series)
            else list(design_info.column_names)
        )
        coefficients = np.asarray(fixed_parameters, dtype=float)
        covariance_all = getattr(result, "cov_params")()
        if isinstance(covariance_all, pd.DataFrame):
            covariance = covariance_all.loc[fixed_names, fixed_names].to_numpy(
                dtype=float
            )
        else:
            covariance = np.asarray(covariance_all, dtype=float)[
                : len(coefficients), : len(coefficients)
            ]
        critical = float(norm.ppf(1.0 - (1.0 - ci_level) / 2.0))
    except Exception as exc:
        return pd.DataFrame(
            [
                {
                    "reference_group_id": reference,
                    "comparison_group_id": pd.NA,
                    "contrast_sign": "comparison - reference",
                    "grid_cell_count": len(grid),
                    "estimate": np.nan,
                    "std_error": np.nan,
                    "z_value": np.nan,
                    "p_value_wald": np.nan,
                    "ci_low": np.nan,
                    "ci_high": np.nan,
                    "status": "failed",
                    "error": f"Could not prepare marginal contrasts: {exc}",
                }
            ]
        )

    rows: list[dict[str, object]] = []
    for comparison in group_levels:
        if comparison == reference:
            continue
        reference_grid = grid.assign(**{group_col: reference})
        comparison_grid = grid.assign(**{group_col: comparison})
        for frame in (reference_grid, comparison_grid):
            frame[group_col] = pd.Categorical(
                frame[group_col],
                categories=list(group_levels),
                ordered=True,
            )
            frame[condition_col] = pd.Categorical(
                frame[condition_col],
                categories=list(levels["conditions"]),
                ordered=True,
            )
            frame[roi_col] = pd.Categorical(
                frame[roi_col],
                categories=list(levels["rois"]),
                ordered=True,
            )
        try:
            reference_design = np.asarray(
                build_design_matrices([design_info], reference_grid)[0],
                dtype=float,
            )
            comparison_design = np.asarray(
                build_design_matrices([design_info], comparison_grid)[0],
                dtype=float,
            )
            contrast = comparison_design.mean(axis=0) - reference_design.mean(axis=0)
            estimate = float(contrast @ coefficients)
            variance = float(contrast @ covariance @ contrast)
            if not np.isfinite(variance) or variance < 0.0:
                raise ValueError(f"invalid contrast variance {variance}")
            standard_error = float(np.sqrt(variance))
            z_value = estimate / standard_error if standard_error > 0.0 else np.nan
            p_value = (
                float(2.0 * norm.sf(abs(z_value))) if np.isfinite(z_value) else np.nan
            )
            rows.append(
                {
                    "reference_group_id": reference,
                    "comparison_group_id": comparison,
                    "contrast_sign": f"{comparison} - {reference}",
                    "grid_cell_count": len(grid),
                    "grid_conditions": "; ".join(
                        map(str, pd.unique(grid[condition_col]))
                    ),
                    "grid_rois": "; ".join(map(str, pd.unique(grid[roi_col]))),
                    "estimate": estimate,
                    "std_error": standard_error,
                    "z_value": z_value,
                    "p_value_wald": p_value,
                    "ci_low": estimate - critical * standard_error,
                    "ci_high": estimate + critical * standard_error,
                    "status": "ok",
                    "error": "",
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "reference_group_id": reference,
                    "comparison_group_id": comparison,
                    "contrast_sign": f"{comparison} - {reference}",
                    "grid_cell_count": len(grid),
                    "estimate": np.nan,
                    "std_error": np.nan,
                    "z_value": np.nan,
                    "p_value_wald": np.nan,
                    "ci_low": np.nan,
                    "ci_high": np.nan,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return pd.DataFrame(rows)


def _metadata_frame(
    *,
    status: str,
    comparisons: tuple[OmnibusComparison, ...],
    requested_re_formula: str,
    used_re_formula: str,
    final_optimizer: str,
    levels: dict[str, tuple[object, ...]],
    marginal_grid: pd.DataFrame | None,
    reference_group_id: object | None,
    analysis_scope: str,
    n_observations: int,
    n_contributing_participants: int,
) -> pd.DataFrame:
    rows = [
        ("schema_version", MULTIGROUP_MODEL_SCHEMA_VERSION),
        ("status", status),
        ("analysis_scope", analysis_scope),
        ("n_observations", int(n_observations)),
        (
            "n_contributing_participants",
            int(n_contributing_participants),
        ),
        (
            "missing_data_handling",
            (
                "finite observed rows; no imputation; likelihood inference "
                "assumes missing at random conditional on modeled variables"
                if analysis_scope == "available_case"
                else "participant-first complete core"
            ),
        ),
        ("full_formula", comparisons[0].full_formula),
        ("fixed_contrasts", "Sum coding for Group, Condition, and ROI"),
        ("final_estimation", "REML"),
        ("omnibus_estimation", "ML full/reduced likelihood-ratio tests"),
        ("omnibus_reference", "chi-square (asymptotic)"),
        ("omnibus_caveat", LRT_CAVEAT),
        (
            "any_group_related_definition",
            "Joint block of all group-related terms; not a pure group main effect.",
        ),
        ("requested_re_formula", requested_re_formula),
        ("used_re_formula", used_re_formula),
        ("final_optimizer", final_optimizer),
        ("group_levels", "; ".join(map(str, levels["groups"]))),
        ("condition_levels", "; ".join(map(str, levels["conditions"]))),
        ("roi_levels", "; ".join(map(str, levels["rois"]))),
        (
            "marginal_group_contrasts",
            "not requested" if marginal_grid is None else "explicit Condition x ROI grid",
        ),
        (
            "marginal_reference_group",
            ""
            if marginal_grid is None
            else (
                levels["groups"][0]
                if reference_group_id is None
                else reference_group_id
            ),
        ),
    ]
    return pd.DataFrame(rows, columns=["field", "value"])


def _empty_metadata(
    status: str,
    full_formula: str,
    requested_re_formula: str,
    *,
    analysis_scope: str,
    n_observations: int,
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            ("schema_version", MULTIGROUP_MODEL_SCHEMA_VERSION),
            ("status", status),
            ("analysis_scope", analysis_scope),
            ("n_observations", int(n_observations)),
            ("full_formula", full_formula),
            ("requested_re_formula", requested_re_formula),
            ("omnibus_caveat", LRT_CAVEAT),
        ],
        columns=["field", "value"],
    )


def run_multigroup_mixed_model(
    data: pd.DataFrame,
    *,
    dv_col: str = "value",
    participant_col: str = "participant_id",
    group_col: str = "group_id",
    condition_col: str = "condition",
    roi_col: str = "roi",
    known_group_ids: Sequence[object] | None = None,
    random_slope_formula: str | None = None,
    optimizers: Sequence[str] = ("lbfgs", "powell"),
    maxiter: int = 1000,
    singularity_tolerance: float = 1e-10,
    ci_level: float = 0.95,
    marginal_grid: pd.DataFrame | None = None,
    reference_group_id: object | None = None,
    analysis_scope: str = "complete_core",
) -> MultigroupModelBundle:
    """Fit the native multi-group model and explicit omnibus LRTs."""

    if not optimizers:
        raise ValueError("At least one optimizer must be supplied.")
    if not 0.0 < float(ci_level) < 1.0:
        raise ValueError("ci_level must be strictly between 0 and 1.")

    comparisons = build_multigroup_omnibus_comparisons(
        dv_col=dv_col,
        group_col=group_col,
        condition_col=condition_col,
        roi_col=roi_col,
    )
    full_formula = comparisons[0].full_formula
    requested_re_formula = random_slope_formula or "1"
    scope = str(analysis_scope).strip().casefold().replace("-", "_")
    working, diagnostics, levels = _validate_model_data(
        data,
        dv_col=dv_col,
        participant_col=participant_col,
        group_col=group_col,
        condition_col=condition_col,
        roi_col=roi_col,
        known_group_ids=known_group_ids,
        full_formula=full_formula,
        analysis_scope=scope,
    )
    expected_row_labels = tuple(working.index.tolist())

    attempt_rows: list[dict[str, object]] = []
    with single_threaded_blas():
        if random_slope_formula:
            final_fit = _attempt_fit(
                data=working,
                formula=full_formula,
                participant_col=participant_col,
                requested_re_formula=requested_re_formula,
                used_re_formula=random_slope_formula,
                reml=True,
                optimizers=optimizers,
                maxiter=maxiter,
                singularity_tolerance=singularity_tolerance,
                stage="final_reml_random_slope",
                fallback_reason="",
                attempt_rows=attempt_rows,
            )
            if final_fit is None:
                final_fit = _attempt_fit(
                    data=working,
                    formula=full_formula,
                    participant_col=participant_col,
                    requested_re_formula=requested_re_formula,
                    used_re_formula="1",
                    reml=True,
                    optimizers=optimizers,
                    maxiter=maxiter,
                    singularity_tolerance=singularity_tolerance,
                    stage="final_reml_random_intercept_fallback",
                    fallback_reason=(
                        "requested random slopes did not converge or were singular"
                    ),
                    attempt_rows=attempt_rows,
                )
        else:
            final_fit = _attempt_fit(
                data=working,
                formula=full_formula,
                participant_col=participant_col,
                requested_re_formula="1",
                used_re_formula="1",
                reml=True,
                optimizers=optimizers,
                maxiter=maxiter,
                singularity_tolerance=singularity_tolerance,
                stage="final_reml_random_intercept",
                fallback_reason="",
                attempt_rows=attempt_rows,
            )

        if final_fit is None:
            omnibus = pd.DataFrame(
                [
                    _failed_omnibus_row(
                        comparison,
                        "Final REML full model failed; omnibus ML fits were not attempted.",
                    )
                    for comparison in comparisons
                ]
            )
            diagnostics = pd.concat(
                [
                    diagnostics,
                    _diagnostic_frame(
                        [
                            {
                                "check_id": "final_reml_fit",
                                "status": "failed",
                                "value": "",
                                "threshold": "converged and non-singular",
                                "message": "No acceptable random-effects fit was found.",
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
            return MultigroupModelBundle(
                status="failed",
                estimates=pd.DataFrame(),
                omnibus=omnibus,
                attempts=pd.DataFrame(attempt_rows),
                diagnostics=diagnostics,
                metadata=_empty_metadata(
                    "failed",
                    full_formula,
                    requested_re_formula,
                    analysis_scope=scope,
                    n_observations=len(working),
                ),
                marginal_group_contrasts=pd.DataFrame(),
                fitted_model=None,
            )

        final_labels = _model_row_labels(final_fit.result)
        if final_labels is not None:
            final_rows_match = final_labels == expected_row_labels
        else:
            final_rows_match = (
                int(getattr(final_fit.result, "nobs", len(working)))
                == len(working)
            )
        if not final_rows_match:
            raise RuntimeError(
                "The final REML model did not use the exact validated "
                "observed row set."
            )

        estimates = _fixed_effect_estimates(final_fit.result, float(ci_level))
        estimates["analysis_scope"] = scope
        estimates["n_observations"] = int(len(working))
        estimates["n_contributing_participants"] = int(
            len(levels["participants"])
        )
        formula_fits: dict[str, _AcceptedFit | None] = {}
        for formula_index, formula in enumerate(
            dict.fromkeys(
                [comparison.full_formula for comparison in comparisons]
                + [comparison.reduced_formula for comparison in comparisons]
            )
        ):
            formula_fits[formula] = _attempt_fit(
                data=working,
                formula=formula,
                participant_col=participant_col,
                requested_re_formula=requested_re_formula,
                used_re_formula=final_fit.re_formula,
                reml=False,
                optimizers=optimizers,
                maxiter=maxiter,
                singularity_tolerance=singularity_tolerance,
                stage=(
                    "omnibus_ml_full"
                    if formula == full_formula
                    else f"omnibus_ml_reduced_{formula_index}"
                ),
                fallback_reason=(
                    "using the random-effects structure accepted by the final REML fit"
                ),
                attempt_rows=attempt_rows,
            )

    from scipy.stats import chi2

    omnibus_rows: list[dict[str, object]] = []
    for comparison in comparisons:
        full_fit = formula_fits.get(comparison.full_formula)
        reduced_fit = formula_fits.get(comparison.reduced_formula)
        if full_fit is None:
            omnibus_rows.append(
                _failed_omnibus_row(comparison, "Full ML model failed.")
            )
            continue
        if reduced_fit is None:
            omnibus_rows.append(
                _failed_omnibus_row(comparison, "Reduced ML model failed.")
            )
            continue
        try:
            full_labels = _model_row_labels(full_fit.result)
            reduced_labels = _model_row_labels(reduced_fit.result)
            if full_labels is not None and reduced_labels is not None:
                same_rows = (
                    full_labels == expected_row_labels
                    and reduced_labels == expected_row_labels
                )
                row_identity_status = (
                    "exact_match" if same_rows else "mismatch"
                )
                n_full = len(full_labels)
                n_reduced = len(reduced_labels)
            else:
                n_full = int(
                    getattr(full_fit.result, "nobs", len(working))
                )
                n_reduced = int(
                    getattr(reduced_fit.result, "nobs", len(working))
                )
                same_rows = n_full == len(working) == n_reduced
                row_identity_status = (
                    "count_match_row_labels_unavailable"
                    if same_rows
                    else "count_mismatch"
                )
            if not same_rows:
                raise ValueError(
                    "full and reduced ML models did not use the exact same "
                    "validated observed rows"
                )
            lr_statistic = 2.0 * (
                float(getattr(full_fit.result, "llf"))
                - float(getattr(reduced_fit.result, "llf"))
            )
            df_difference = (
                _model_parameter_count(full_fit.result)
                - _model_parameter_count(reduced_fit.result)
            )
            if not np.isfinite(lr_statistic) or lr_statistic < -1e-8:
                raise ValueError(f"invalid likelihood-ratio statistic {lr_statistic}")
            if df_difference <= 0:
                raise ValueError(f"invalid model degrees-of-freedom difference {df_difference}")
            lr_statistic = max(0.0, float(lr_statistic))
            p_value = float(chi2.sf(lr_statistic, df_difference))
            omnibus_rows.append(
                {
                    "effect_id": comparison.effect_id,
                    "effect_label": comparison.effect_label,
                    "interpretation": comparison.interpretation,
                    "full_formula": comparison.full_formula,
                    "reduced_formula": comparison.reduced_formula,
                    "lr_statistic": lr_statistic,
                    "df_difference": df_difference,
                    "p_value_chi2": p_value,
                    "status": "ok",
                    "reportable": True,
                    "analysis_scope": scope,
                    "n_observations_full": n_full,
                    "n_observations_reduced": n_reduced,
                    "same_observed_rows": same_rows,
                    "row_identity_status": row_identity_status,
                    "error": "",
                    "reference_distribution": "chi-square (asymptotic)",
                    "caveat": LRT_CAVEAT,
                }
            )
        except Exception as exc:
            omnibus_rows.append(
                _failed_omnibus_row(
                    comparison,
                    f"{type(exc).__name__}: {exc}",
                )
            )

    omnibus = pd.DataFrame(omnibus_rows)
    omnibus["analysis_scope"] = scope
    status = "ok" if omnibus["reportable"].all() else "partial"
    diagnostics = pd.concat(
        [
            diagnostics,
            _diagnostic_frame(
                [
                    {
                        "check_id": "final_reml_fit",
                        "status": "ok",
                        "value": (
                            f"optimizer={final_fit.optimizer}; "
                            f"re_formula={final_fit.re_formula}"
                        ),
                        "threshold": "converged and non-singular",
                        "message": "Final fixed-effect estimates use REML.",
                    },
                    {
                        "check_id": "omnibus_lrt_fits",
                        "status": "ok" if status == "ok" else "warning",
                        "value": int(omnibus["reportable"].sum()),
                        "threshold": len(comparisons),
                        "message": LRT_CAVEAT,
                    },
                ]
            ),
        ],
        ignore_index=True,
    )
    metadata = _metadata_frame(
        status=status,
        comparisons=comparisons,
        requested_re_formula=requested_re_formula,
        used_re_formula=final_fit.re_formula,
        final_optimizer=final_fit.optimizer,
        levels=levels,
        marginal_grid=marginal_grid,
        reference_group_id=reference_group_id,
        analysis_scope=scope,
        n_observations=len(working),
        n_contributing_participants=len(levels["participants"]),
    )
    marginal_group_contrasts = _estimated_marginal_group_contrasts(
        result=final_fit.result,
        working=working,
        marginal_grid=marginal_grid,
        reference_group_id=reference_group_id,
        group_col=group_col,
        condition_col=condition_col,
        roi_col=roi_col,
        levels=levels,
        ci_level=float(ci_level),
    )
    return MultigroupModelBundle(
        status=status,
        estimates=estimates,
        omnibus=omnibus,
        attempts=pd.DataFrame(attempt_rows),
        diagnostics=diagnostics,
        metadata=metadata,
        marginal_group_contrasts=marginal_group_contrasts,
        fitted_model=final_fit.result,
    )

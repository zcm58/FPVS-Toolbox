# Tools/Stats/mixed_effects_model.py
# -*- coding: utf-8 -*-
"""
Linear Mixed-Effects (LMM) helper using statsmodels MixedLM.

Fixes/Improvements
------------------
- Applies sum-to-zero contrasts robustly (case-insensitive mapping; auto-applies
  to 'condition'/'roi' when reasonable).
- Supports random slopes for condition via re_formula (with graceful fallback to
  intercept-only if singular/convergence issues occur).
- Optional hierarchy-preserving Likelihood-Ratio Tests (LRTs) under ML for the
  Condition x ROI interaction and factor-related blocks.
- Detects near-singular random-effects covariance and annotates results.

Typical use
-----------
table = run_mixed_effects_model(
    data=df_long,
    dv_col="BCA_sum",
    group_col="Subject",
    fixed_effects=["condition * roi"],      # interactions allowed
    re_formula="~ C(condition, Sum)",       # random intercept + condition slopes (recommended)
    method="reml",                          # REML for estimates; ML used internally for LRTs
    contrast_map={"condition": "Sum", "roi": "Sum"},
    do_lrt=True                             # add LRT (ML) table alongside Wald table
)

Returns
-------
- By default: pandas.DataFrame (fixed effects Wald table).
- If `return_model=True`: (fixed_table_df, MixedLMResults).
- If `do_lrt=True`: attaches a `.attrs["lrt_table"]` DataFrame to the returned table.

Notes
-----
- With *fully within-subject* designs, prefer including at least random slopes
  for condition if data allow: re_formula="~ C(condition, Sum)".
- LRTs are done under ML (per nested model comparison requirements). Their
  chi-square reference is asymptotic and must be interpreted cautiously with
  small samples; final coefficients/SEs are typically reported from REML.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from Tools.Stats.common.blas_limits import single_threaded_blas

if TYPE_CHECKING:
    from statsmodels.regression.mixed_linear_model import MixedLMResults

logger = logging.getLogger(__name__)
ALLOWED_ANALYSIS_SCOPES = frozenset({"complete_core", "available_case"})


# ----------------------------- internals -------------------------------- #

@dataclass
class _FitResult:
    """Plain-language container for  FitResult behavior in this stats module."""
    table: pd.DataFrame
    model: "MixedLMResults"  # type: ignore[name-defined]
    used_re_formula: str
    singular: bool
    converged: bool


@dataclass(frozen=True)
class _LRTComparison:
    """One explicit full/reduced fixed-effect model comparison."""

    effect_id: str
    effect_label: str
    full_formula: str
    reduced_formula: str


def _extract_variables(term: str) -> List[str]:
    """Return variable names found within a fixed-effects term (rough parse)."""
    tokens = re.split(r"[\*\+:\s]+", term)
    vars_: List[str] = []
    for t in tokens:
        if not t or t in ("1", "0"):
            continue
        m = re.match(r"C\((?P<var>[A-Za-z0-9_]+)\s*,?\s*[A-Za-z0-9_]*\)", t)
        if m:
            vars_.append(m.group("var"))
        else:
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t):
                vars_.append(t)
    return sorted(set(vars_))


def _apply_contrasts_to_term(term: str, contrast_map: Dict[str, str]) -> str:
    """
    Replace bare variable names in a formula term with C(var, Contrast) if requested.
    Existing C(...) wraps are left unchanged. Mapping is case-insensitive.
    """
    out = term
    if not contrast_map:
        return out
    # Build case-insensitive mapping
    cmap = {k.lower(): v for k, v in contrast_map.items()}
    # Find all plausible variable tokens in the term
    vars_in_term = _extract_variables(term)
    for var in vars_in_term:
        key = var.lower()
        if key not in cmap:
            continue
        # skip if already wrapped
        if re.search(rf"C\(\s*{re.escape(var)}\s*,", out):
            continue
        # whole-word replace
        pattern = rf'(?<![A-Za-z0-9_]){re.escape(var)}(?![A-Za-z0-9_])'
        out = re.sub(pattern, f"C({var}, {cmap[key]})", out)
    return out


def _ensure_default_sum_contrasts(
    data: pd.DataFrame,
    terms: List[str],
    contrast_map: Optional[Dict[str, str]],
) -> Dict[str, str]:
    """
    If user didn't specify contrasts, auto-apply Sum to common within-subject factors
    'condition' and 'roi' (case-insensitive) when they appear in the model.
    """
    cmap = {k.lower(): v for k, v in (contrast_map or {}).items()}
    used_vars = sorted({v for t in terms for v in _extract_variables(t)})
    for candidate in ("condition", "roi"):
        if candidate in [v.lower() for v in used_vars] and candidate not in cmap:
            cmap[candidate] = "Sum"
    # restore original case where possible by scanning columns
    final_map: Dict[str, str] = {}
    cols_lower = {c.lower(): c for c in data.columns}
    for k_lower, v in cmap.items():
        final_map[cols_lower.get(k_lower, k_lower)] = v
    return final_map


def _z_crit(ci: float) -> float:
    """Critical z for two-sided CI."""
    try:
        from scipy.stats import norm  # type: ignore
        return float(norm.ppf(1 - (1 - ci) / 2.0))
    except Exception:
        return 1.96


def _clean_fixed_table(result, ci_level: float = 0.95) -> pd.DataFrame:
    """Build a tidy fixed-effects table from a MixedLMResults object."""
    fe = getattr(result, "fe_params", None)
    bse = getattr(result, "bse_fe", None)
    if fe is None or bse is None:
        raise RuntimeError("MixedLM result missing fe_params/bse_fe.")
    effects = pd.Index(fe.index, name="Effect")
    coef = pd.Series(np.asarray(fe), index=effects, name="Coef.")
    se = pd.Series(np.asarray(bse), index=effects, name="SE")
    zvals = pd.Series(coef.values / se.values, index=effects, name="Z")
    try:
        from scipy.stats import norm  # type: ignore
        pvals = pd.Series(2 * (1 - norm.cdf(np.abs(zvals.values))), index=effects, name="P>|z|")
    except Exception:
        # Fallback using error function
        from math import erf, sqrt
        pvals = pd.Series([2 * (1 - 0.5 * (1 + erf(abs(z) / sqrt(2)))) for z in zvals.values],
                          index=effects, name="P>|z|")
    zc = _z_crit(ci_level)
    ci_low = pd.Series(coef.values - zc * se.values, index=effects, name="CI Low")
    ci_high = pd.Series(coef.values + zc * se.values, index=effects, name="CI High")
    out = pd.concat([coef, se, zvals, pvals, ci_low, ci_high], axis=1).reset_index()
    out["Note"] = ""
    return out


def _fit_mixedlm(
    df: pd.DataFrame,
    formula: str,
    group_col: str,
    re_formula: str,
    reml_flag: bool,
) -> _FitResult:
    """Fit MixedLM with fallback optimizer and singularity check."""
    try:
        import statsmodels.formula.api as smf  # type: ignore
    except ImportError as e:
        raise ImportError("statsmodels is required. Install via `pip install statsmodels`.") from e

    model = smf.mixedlm(formula, df, groups=df[group_col], re_formula=re_formula or "1")
    # First try lbfgs
    try:
        result = model.fit(reml=reml_flag, method="lbfgs", maxiter=1000, full_output=True)
    except Exception as e1:
        logger.warning("lbfgs failed: %s; retry with powell", e1)
        result = model.fit(reml=reml_flag, method="powell", maxiter=1000, full_output=True)

    # Convergence/singularity diagnostics
    converged = bool(getattr(result, "converged", False))
    singular = False
    try:
        cov_re = np.asarray(result.cov_re)
        evals = np.linalg.eigvalsh(cov_re) if cov_re.size else np.array([1.0])
        singular = bool(np.min(evals) < 1e-10)
        if singular:
            logger.warning("Random-effects covariance near-singular. eigenvalues=%s", evals)
    except Exception:
        pass

    table = _clean_fixed_table(result)
    if not converged:
        table["Note"] = (table["Note"].mask(table["Note"].astype(bool), table["Note"] + "; ")
                         .fillna("") + "Model did not converge")
    if singular:
        table["Note"] = (table["Note"].mask(table["Note"].astype(bool), table["Note"] + "; ")
                         .fillna("") + "Random-effects covariance near-singular")
    return _FitResult(table=table, model=result, used_re_formula=re_formula or "1",
                      singular=singular, converged=converged)


def _build_formula(
    dv_col: str,
    fixed_effects: List[str],
    data: pd.DataFrame,
    contrast_map: Optional[Dict[str, str]],
) -> Tuple[str, List[str], Dict[str, str]]:
    """
    Apply (case-insensitive) contrasts to fixed terms and assemble formula string.
    Returns (formula_str, processed_terms, final_contrast_map).
    """
    # Ensure default Sum on condition/roi if present and not specified
    final_cmap = _ensure_default_sum_contrasts(data, fixed_effects, contrast_map)
    processed_terms = [_apply_contrasts_to_term(term, final_cmap) for term in fixed_effects]
    fixed_formula = " + ".join(processed_terms)
    formula = f"{dv_col} ~ {fixed_formula}"
    logger.info("MixedLM formula: %s", formula)
    return formula, processed_terms, final_cmap


def _mentions_variable(var: str, term: str) -> bool:
    """Return whether a formula term contains a bare or contrast-wrapped variable."""

    return bool(
        re.search(
            rf"(?i)(?<![A-Za-z0-9_]){re.escape(var)}(?![A-Za-z0-9_])",
            term,
        )
        or re.search(rf"(?i)C\(\s*{re.escape(var)}\s*,", term)
    )


def _factor_expression(processed_terms: List[str], variable: str) -> str | None:
    """Return the contrast-preserving expression used for a model factor."""

    wrapped = re.compile(
        rf"C\(\s*{re.escape(variable)}\s*,\s*[^)]+\)",
        flags=re.IGNORECASE,
    )
    bare = re.compile(
        rf"(?<![A-Za-z0-9_]){re.escape(variable)}(?![A-Za-z0-9_])",
        flags=re.IGNORECASE,
    )
    for term in processed_terms:
        match = wrapped.search(term)
        if match:
            return match.group(0)
    for term in processed_terms:
        match = bare.search(term)
        if match:
            return match.group(0)
    return None


def _unique_formula_terms(terms: List[str]) -> List[str]:
    """Return non-empty formula terms with case-insensitive stable deduplication."""

    output: List[str] = []
    seen: set[str] = set()
    for raw in terms:
        term = str(raw).strip()
        if not term:
            continue
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(term)
    return output


def _build_single_group_lrt_comparisons(
    dv_col: str,
    processed_terms: List[str],
) -> List[_LRTComparison]:
    """Build explicit hierarchy-preserving Condition/ROI ML comparisons."""

    condition = _factor_expression(processed_terms, "condition")
    roi = _factor_expression(processed_terms, "roi")
    if condition is None and roi is None:
        raise ValueError(
            "do_lrt=True requires a Condition and/or ROI fixed-effect factor."
        )

    unrelated = [
        term
        for term in processed_terms
        if not _mentions_variable("condition", term)
        and not _mentions_variable("roi", term)
    ]
    full_rhs = " + ".join(_unique_formula_terms(processed_terms)) or "1"
    full_formula = f"{dv_col} ~ {full_rhs}"
    comparisons: List[_LRTComparison] = []

    if condition is not None and roi is not None:
        reduced_interaction = _unique_formula_terms([*unrelated, condition, roi])
        comparisons.append(
            _LRTComparison(
                effect_id="condition_roi_interaction",
                effect_label="Condition x ROI interaction",
                full_formula=full_formula,
                reduced_formula=f"{dv_col} ~ {' + '.join(reduced_interaction) or '1'}",
            )
        )

    if condition is not None:
        reduced_condition = _unique_formula_terms(
            [*unrelated, *([roi] if roi is not None else [])]
        )
        comparisons.append(
            _LRTComparison(
                effect_id="condition_related_block",
                effect_label="Condition-related block",
                full_formula=full_formula,
                reduced_formula=f"{dv_col} ~ {' + '.join(reduced_condition) or '1'}",
            )
        )

    if roi is not None:
        reduced_roi = _unique_formula_terms(
            [*unrelated, *([condition] if condition is not None else [])]
        )
        comparisons.append(
            _LRTComparison(
                effect_id="roi_related_block",
                effect_label="ROI-related block",
                full_formula=full_formula,
                reduced_formula=f"{dv_col} ~ {' + '.join(reduced_roi) or '1'}",
            )
        )
    return comparisons


def _make_reduced_terms(processed_terms: List[str], drop: str) -> List[str]:
    """
    Create reduced fixed-effect terms by dropping:
      - 'interaction': removes ':' terms and replaces '*' with '+' (keeps main effects).
      - 'condition': removes any term involving 'condition' (case-insensitive).
      - 'roi': removes any term involving 'roi' (case-insensitive).
    """
    drop = drop.lower()
    terms = list(processed_terms)
    if drop == "interaction":
        # Replace '*' with '+' and drop ':' terms
        terms = [t.replace("*", "+") for t in terms]
        terms = [t for t in terms if ":" not in t]
        return terms

    if drop in ("condition", "roi"):
        kept: List[str] = []
        other = "roi" if drop == "condition" else "condition"
        other_expression = _factor_expression(terms, other)
        for term in terms:
            if not _mentions_variable(drop, term):
                kept.append(term)
            elif (
                other_expression is not None
                and _mentions_variable(other, term)
            ):
                kept.append(other_expression)
        return _unique_formula_terms(kept)
    raise ValueError(f"Unknown drop target: {drop}")


def _lrt(full_ml, reduced_ml) -> Tuple[float, int, float]:
    """Compute LR test stat, df, and p-value; returns (LR, df, p)."""
    LR = 2.0 * (full_ml.llf - reduced_ml.llf)
    df_diff = int(full_ml.df_modelwc - reduced_ml.df_modelwc)
    if df_diff <= 0:
        raise RuntimeError(
            "Likelihood-ratio comparison is not nested with positive degrees "
            f"of freedom (df difference={df_diff})."
        )
    if LR < -1e-7:
        raise RuntimeError(
            "Reduced model has a materially higher likelihood than the declared "
            f"full model (LR={LR:.6g})."
        )
    LR = max(float(LR), 0.0)
    try:
        from scipy.stats import chi2  # type: ignore
        p = float(chi2.sf(LR, df_diff))
    except Exception:
        # Fallback: simple exp(-x/2) approx for df>=1 is not correct; report NaN if SciPy missing
        p = np.nan
    return LR, df_diff, p


def _fit_for_lrt(
    df: pd.DataFrame,
    dv_col: str,
    group_col: str,
    processed_terms: List[str],
    re_formula: str,
) -> "MixedLMResults":  # type: ignore[name-defined]
    """Fit an ML model for a given set of processed fixed-effect terms."""
    fixed_formula = " + ".join(processed_terms) or "1"
    formula = f"{dv_col} ~ {fixed_formula}"
    return _fit_formula_for_lrt(df, formula, group_col, re_formula)


def _fit_formula_for_lrt(
    df: pd.DataFrame,
    formula: str,
    group_col: str,
    re_formula: str,
) -> "MixedLMResults":  # type: ignore[name-defined]
    """Fit one explicit ML formula, retaining an optimizer fallback."""

    try:
        import statsmodels.formula.api as smf  # type: ignore
    except ImportError as e:
        raise ImportError("statsmodels is required. Install via `pip install statsmodels`.") from e
    model = smf.mixedlm(formula, df, groups=df[group_col], re_formula=re_formula or "1")
    try:
        return model.fit(
            reml=False,
            method="lbfgs",
            maxiter=1000,
            full_output=True,
        )
    except Exception as first_error:
        logger.warning(
            "ML LRT fit with lbfgs failed for %s: %s; retrying powell",
            formula,
            first_error,
        )
        return model.fit(
            reml=False,
            method="powell",
            maxiter=1000,
            full_output=True,
        )


def _normalize_analysis_scope(value: object) -> str:
    """Return a supported missing-data analysis scope."""

    scope = str(value).strip().casefold().replace("-", "_")
    if scope not in ALLOWED_ANALYSIS_SCOPES:
        raise ValueError(
            "analysis_scope must be 'complete_core' or 'available_case'."
        )
    return scope


def _model_row_labels(result: object) -> tuple[object, ...] | None:
    """Return formula-model row labels when statsmodels exposes them."""

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


def _single_model_diagnostics(
    df: pd.DataFrame,
    *,
    dv_col: str,
    group_col: str,
    model_vars: list[str],
    formula: str,
    analysis_scope: str,
    cell_cols: tuple[str, str] | None,
) -> tuple[pd.DataFrame, int]:
    """Validate and summarize the participant-level fixed-effect design."""

    diagnostics: list[dict[str, object]] = []
    if df[group_col].nunique(dropna=True) < 2:
        raise ValueError("MixedLM requires at least two contributing participants.")

    factor_lookup = {column.casefold(): column for column in model_vars}
    if cell_cols is None:
        condition_col = factor_lookup.get("condition")
        roi_col = factor_lookup.get("roi")
    else:
        condition_col, roi_col = cell_cols
    missing_cell_count = 0
    if condition_col is not None and roi_col is not None:
        grain = [group_col, condition_col, roi_col]
        duplicate_count = int(df.duplicated(grain, keep=False).sum())
        if duplicate_count:
            raise ValueError(
                "Duplicate participant x Condition x ROI observations block "
                f"MixedLM fitting ({duplicate_count} duplicate rows)."
            )
        condition_levels = tuple(pd.unique(df[condition_col]))
        roi_levels = tuple(pd.unique(df[roi_col]))
        if len(condition_levels) < 2 or len(roi_levels) < 2:
            raise ValueError(
                "Condition x ROI MixedLM requires at least two observed levels "
                "of both Condition and ROI."
            )
        expected = {
            (participant, condition, roi)
            for participant in pd.unique(df[group_col])
            for condition in condition_levels
            for roi in roi_levels
        }
        observed = set(df[grain].itertuples(index=False, name=None))
        missing_cell_count = len(expected - observed)
        if analysis_scope == "complete_core" and missing_cell_count:
            raise ValueError(
                "Complete-core MixedLM requires every participant to contribute "
                "every observed Condition x ROI cell."
            )
        structural = (
            df.groupby([condition_col, roi_col], observed=False, dropna=False)
            .size()
            .reindex(
                pd.MultiIndex.from_product(
                    [condition_levels, roi_levels],
                    names=[condition_col, roi_col],
                ),
                fill_value=0,
            )
        )
        if bool(structural.eq(0).any()):
            raise ValueError(
                "A structurally empty Condition x ROI cell blocks the requested "
                "interaction model."
            )
        diagnostics.append(
            {
                "check_id": "participant_cell_coverage",
                "status": (
                    "warning"
                    if analysis_scope == "available_case" and missing_cell_count
                    else "ok"
                ),
                "value": missing_cell_count,
                "threshold": (
                    "partial participant coverage allowed; no structural empty cells"
                    if analysis_scope == "available_case"
                    else 0
                ),
                "message": (
                    "Missing participant cells are not imputed."
                    if missing_cell_count
                    else "Every contributing participant has complete cell coverage."
                ),
            }
        )

    try:
        from patsy import dmatrices

        _, fixed_design = dmatrices(formula, df, return_type="dataframe")
    except Exception as exc:
        raise ValueError(
            f"Could not build the MixedLM fixed-effects design: {exc}"
        ) from exc
    rank = int(np.linalg.matrix_rank(fixed_design.to_numpy(dtype=float)))
    columns = int(fixed_design.shape[1])
    residual_rows = int(len(df) - rank)
    if rank != columns or residual_rows <= 0:
        raise ValueError(
            "The MixedLM fixed-effects design is rank deficient or saturated "
            f"(rank={rank}, columns={columns}, residual rows={residual_rows})."
        )
    diagnostics.extend(
        [
            {
                "check_id": "fixed_design_rank",
                "status": "ok",
                "value": (
                    f"rank={rank}; columns={columns}; "
                    f"residual_rows={residual_rows}"
                ),
                "threshold": "full column rank and at least 1 residual row",
                "message": "The fixed-effect interaction is estimable.",
            },
            {
                "check_id": "observed_row_set",
                "status": "ok",
                "value": len(df),
                "threshold": "",
                "message": (
                    "All ML full/reduced comparisons must use these same "
                    "finite observed rows."
                ),
            },
            {
                "check_id": "contributing_participants",
                "status": "ok",
                "value": int(df[group_col].nunique()),
                "threshold": "at least 2",
                "message": "Random-intercept grouping units in the model.",
            },
        ]
    )
    return pd.DataFrame(diagnostics), missing_cell_count


# ------------------------------- API ----------------------------------- #

def run_mixed_effects_model(
    data: pd.DataFrame,
    dv_col: str,
    group_col: str,
    fixed_effects: List[str],
    re_formula: str = "1",
    method: str = "reml",
    contrast_map: Optional[Dict[str, str]] = None,
    ci_level: float = 0.95,
    return_model: bool = False,
    do_lrt: bool = False,
    analysis_scope: str = "complete_core",
    cell_cols: tuple[str, str] | None = None,
) -> pd.DataFrame | Tuple[pd.DataFrame, "MixedLMResults"]:
    """
    Run a linear mixed-effects model with robust contrasts, optional random slopes,
    singularity checks, and optional LRTs for key effects.

    Parameters
    ----------
    data : pd.DataFrame
        Long-format data containing all variables.
    dv_col : str
        Dependent variable (e.g., 'BCA_sum').
    group_col : str
        Grouping variable for random effects (e.g., 'Subject').
    fixed_effects : list of str
        Fixed-effect terms (e.g., ['condition * roi', 'sequence']).
    re_formula : str, optional
        Random-effects formula; e.g., '1' (default), or '~ C(condition, Sum)' for slopes.
    method : str, optional
        'reml' (default) or 'ml'. REML is used for the main fit; ML is used for LRTs.
    contrast_map : dict, optional
        Case-insensitive mapping, e.g. {'condition':'Sum','roi':'Sum'}.
        If omitted, Sum is auto-applied to 'condition'/'roi' when present.
    ci_level : float, optional
        Confidence level for Wald CIs (default 0.95).
    return_model : bool, optional
        If True, return (table, statsmodels MixedLMResults).
    do_lrt : bool, optional
        If True, compute LRTs (ML) for: interaction, condition, roi and attach as
        table.attrs["lrt_table"].
    analysis_scope : {"complete_core", "available_case"}, optional
        Missing-data contract. Available-case fitting keeps finite observed rows
        after verifying that the requested interaction remains estimable.
    cell_cols : tuple[str, str], optional
        Explicit (Condition, ROI) column names for coverage diagnostics when
        project columns do not use the conventional names.

    Returns
    -------
    pandas.DataFrame (or tuple with MixedLMResults if return_model=True)

    Raises
    ------
    ValueError : required columns missing or empty data after NA drop.
    RuntimeError: fitting failures.
    """
    # --- validate inputs ---
    scope = _normalize_analysis_scope(analysis_scope)
    if not isinstance(fixed_effects, (list, tuple)) or len(fixed_effects) == 0:
        raise ValueError("`fixed_effects` must be a non-empty list of formula terms.")
    required_cols = [dv_col, group_col]
    model_vars = sorted({v for term in fixed_effects for v in _extract_variables(term)})
    required_cols.extend(model_vars)
    missing = [c for c in required_cols if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in data for MixedLM: {missing}")
    if cell_cols is not None:
        if (
            len(cell_cols) != 2
            or cell_cols[0] == cell_cols[1]
            or any(column not in required_cols for column in cell_cols)
        ):
            raise ValueError(
                "cell_cols must contain distinct Condition and ROI model columns."
            )

    # Drop NA rows
    df = data.dropna(subset=required_cols).copy().reset_index(drop=True)
    if df.empty:
        raise ValueError("After dropping missing values, no data remain for MixedLM.")

    # --- build formula with robust contrasts ---
    formula, processed_terms, final_cmap = _build_formula(dv_col, fixed_effects, df, contrast_map)
    if scope == "available_case":
        model_diagnostics, missing_cell_count = _single_model_diagnostics(
            df,
            dv_col=dv_col,
            group_col=group_col,
            model_vars=model_vars,
            formula=formula,
            analysis_scope=scope,
            cell_cols=cell_cols,
        )
    else:
        missing_cell_count = 0
        model_diagnostics = pd.DataFrame(
            [
                {
                    "check_id": "analysis_scope",
                    "status": "ok",
                    "value": scope,
                    "threshold": "",
                    "message": "Prepared complete-core rows were requested.",
                },
                {
                    "check_id": "observed_row_set",
                    "status": "ok",
                    "value": len(df),
                    "threshold": "",
                    "message": "Finite rows supplied to the model.",
                },
                {
                    "check_id": "contributing_participants",
                    "status": "ok",
                    "value": int(df[group_col].nunique()),
                    "threshold": "",
                    "message": "Random-effect grouping units in the model.",
                },
            ]
        )
    expected_row_labels = tuple(df.index.tolist())

    # --- main fit (REML or ML as requested) ---
    reml_flag = (method or "reml").strip().lower() == "reml"

    with single_threaded_blas():
        # First attempt with requested re_formula
        fit = _fit_mixedlm(df, formula, group_col, re_formula, reml_flag)

        # If requested slopes are singular or fail to converge, back off to a
        # random intercept. The fallback remains visible in the result table.
        backed_off = False
        fallback_reason = ""
        if (fit.singular or not fit.converged) and re_formula.strip() != "1":
            fallback_reason = (
                "singular slopes"
                if fit.singular
                else "nonconverged random slopes"
            )
            logger.warning(
                "Falling back to random intercept only due to %s.",
                fallback_reason,
            )
            fit = _fit_mixedlm(df, formula, group_col, "1", reml_flag)
            backed_off = True

        final_row_labels = _model_row_labels(fit.model)
        if (
            final_row_labels is not None
            and final_row_labels != expected_row_labels
        ):
            raise RuntimeError(
                "The final MixedLM fit did not use the exact validated observed "
                "row set."
            )

        # Inject notes
        if backed_off:
            fit.table["Note"] = (fit.table["Note"].mask(fit.table["Note"].astype(bool), fit.table["Note"] + "; ")
                                 .fillna("") + f"Fell back to random intercept ({fallback_reason})")

        # --- optional LRTs under ML (nested models) ---
        if do_lrt:
            comparisons = _build_single_group_lrt_comparisons(
                dv_col,
                processed_terms,
            )
            full_models: dict[str, object] = {}
            lrt_rows: list[dict[str, object]] = []
            for comparison in comparisons:
                row: dict[str, object] = {
                    "effect_id": comparison.effect_id,
                    "Effect": comparison.effect_label,
                    "full_formula": comparison.full_formula,
                    "reduced_formula": comparison.reduced_formula,
                    "LR": np.nan,
                    "df": np.nan,
                    "p (chi2)": np.nan,
                    "p_value_chi2": np.nan,
                    "status": "failed",
                    "reportable": False,
                    "error": "",
                    "Used RE": fit.used_re_formula,
                    "method": "ML likelihood-ratio test",
                    "reference_distribution": "asymptotic chi-square",
                    "analysis_scope": scope,
                    "n_observations_full": np.nan,
                    "n_observations_reduced": np.nan,
                    "same_observed_rows": False,
                    "row_identity_status": "not_checked",
                }
                try:
                    full_ml = full_models.get(comparison.full_formula)
                    if full_ml is None:
                        full_ml = _fit_formula_for_lrt(
                            df,
                            comparison.full_formula,
                            group_col,
                            fit.used_re_formula,
                        )
                        full_models[comparison.full_formula] = full_ml
                    reduced_ml = _fit_formula_for_lrt(
                        df,
                        comparison.reduced_formula,
                        group_col,
                        fit.used_re_formula,
                    )
                    if not bool(getattr(full_ml, "converged", False)):
                        raise RuntimeError("Full ML model did not converge.")
                    if not bool(getattr(reduced_ml, "converged", False)):
                        raise RuntimeError("Reduced ML model did not converge.")
                    full_labels = _model_row_labels(full_ml)
                    reduced_labels = _model_row_labels(reduced_ml)
                    if full_labels is not None and reduced_labels is not None:
                        same_rows = (
                            full_labels == expected_row_labels
                            and reduced_labels == expected_row_labels
                        )
                        row_identity_status = (
                            "exact_match"
                            if same_rows
                            else "mismatch"
                        )
                        if not same_rows:
                            raise RuntimeError(
                                "Nested ML models did not use the exact same "
                                "validated observed rows."
                            )
                        n_full = len(full_labels)
                        n_reduced = len(reduced_labels)
                    else:
                        n_full = int(getattr(full_ml, "nobs", len(df)))
                        n_reduced = int(
                            getattr(reduced_ml, "nobs", len(df))
                        )
                        same_rows = n_full == len(df) == n_reduced
                        row_identity_status = (
                            "count_match_row_labels_unavailable"
                            if same_rows
                            else "count_mismatch"
                        )
                        if not same_rows:
                            raise RuntimeError(
                                "Nested ML model observation counts differ "
                                "from the validated row set."
                            )
                    lr_value, df_value, p_value = _lrt(full_ml, reduced_ml)
                    row.update(
                        {
                            "LR": lr_value,
                            "df": df_value,
                            "p (chi2)": p_value,
                            "p_value_chi2": p_value,
                            "status": "ok",
                            "reportable": True,
                            "n_observations_full": n_full,
                            "n_observations_reduced": n_reduced,
                            "same_observed_rows": same_rows,
                            "row_identity_status": row_identity_status,
                        }
                    )
                except Exception as exc:  # noqa: BLE001 - exported result row
                    row["error"] = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "LRT comparison failed for %s: %s",
                        comparison.effect_id,
                        exc,
                    )
                lrt_rows.append(row)

            lrt_table = pd.DataFrame(lrt_rows)
            failed_count = int(lrt_table["status"].ne("ok").sum())
            if failed_count == 0:
                lrt_status = "ok"
            elif failed_count == len(lrt_table):
                lrt_status = "failed"
            else:
                lrt_status = "partial_failure"
            # Keep the established attrs attachment for compatibility while
            # also surfacing status directly in the fixed-effect table.
            fit.table.attrs["lrt_table"] = lrt_table
            fit.table.attrs["model_diagnostics"] = model_diagnostics
            fit.table["LRT Status"] = lrt_status
            fit.table["LRT Note"] = (
                ""
                if failed_count == 0
                else (
                    f"{failed_count} of {len(lrt_table)} declared ML "
                    "comparisons failed; inspect the LRT table."
                )
            )

    # Final tidy table (Wald), with notes retained
    table = fit.table
    table.attrs["model_diagnostics"] = model_diagnostics
    table.attrs["analysis_scope"] = scope
    table.attrs["n_observations"] = int(len(df))
    table.attrs["n_contributing_participants"] = int(
        df[group_col].nunique()
    )
    table.attrs["n_missing_participant_cells"] = int(
        missing_cell_count
    )
    table["Analysis Scope"] = scope
    table["Observations"] = int(len(df))
    table["Contributing Participants"] = int(df[group_col].nunique())
    table["Missing Participant Cells"] = int(missing_cell_count)

    # Log basics
    try:
        logger.info(
            "MixedLM %s: converged=%s; RE=%s; cov_re singular=%s; llf=%.3f; AIC=%.3f; BIC=%.3f",
            "REML" if reml_flag else "ML",
            fit.converged,
            fit.used_re_formula,
            fit.singular,
            float(getattr(fit.model, "llf", np.nan)),
            float(getattr(fit.model, "aic", np.nan)),
            float(getattr(fit.model, "bic", np.nan)),
        )
        if hasattr(fit.model, "cov_re"):
            logger.info("Random-effects covariance (cov_re):\n%s", str(fit.model.cov_re))
    except Exception:
        pass

    if return_model:
        return table, fit.model
    return table

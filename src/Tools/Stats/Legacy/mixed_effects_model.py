# mixed_effects_model.py
# -*- coding: utf-8 -*-
"""
Helper to run a linear mixed-effects model (LME) with statsmodels MixedLM.

Key features
------------
- Flexible fixed-effects via formula terms (interactions allowed, e.g., "Condition * ROI + Sequence").
- Random-effects structure via `re_formula` (default random intercepts per Subject).
- Optional contrasts (e.g., sum-to-zero) injected inline using patsy-style `C(var, Sum)`.
- Clean, publication-ready fixed-effects table (Coef., SE, Z, p, CI).
- Convergence diagnostics surfaced in logs.

Typical use
-----------
df_out = run_mixed_effects_model(
    data=df_long,
    dv_col="BCA_sum",
    group_col="Subject",
    fixed_effects=["Condition * ROI", "Sequence"],  # adapt as needed
    re_formula="1",        # random intercepts
    method="reml",         # or "ml" if you need model comparisons
    contrast_map={"Condition": "Sum", "ROI": "Sum"}  # optional
)

Returns
-------
pandas.DataFrame with columns:
['Effect', 'Coef.', 'SE', 'Z', 'P>|z|', 'CI Low', 'CI High', 'Note']

Notes
-----
- Treat this LME as your *primary* inference (RM-ANOVA can be descriptive).
- If you set `contrast_map`, the function wraps variables in `C(var, <Contrast>)`
  inside the formula, e.g., `C(ROI, Sum)` for sum-to-zero coding.
"""

from __future__ import annotations

import logging
import re
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ----------------------------- internals -------------------------------- #

def _extract_variables(term: str) -> List[str]:
    """Return variable names found within a fixed-effects term (rough parse)."""
    # Split on interaction/addition operators; drop numbers and empty tokens.
    tokens = re.split(r"[\*\+:\s]+", term)
    vars_ = []
    for t in tokens:
        if not t or t in ("1", "0"):
            continue
        # If already wrapped like C(var, Contrast), pull out var
        m = re.match(r"C\((?P<var>[A-Za-z0-9_]+)\s*,?\s*[A-Za-z0-9_]*\)", t)
        if m:
            vars_.append(m.group("var"))
        else:
            # keep only plausible variable names
            if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", t):
                vars_.append(t)
    return sorted(set(vars_))


def _apply_contrasts_to_term(term: str, contrast_map: Dict[str, str]) -> str:
    """
    Replace bare variable names in a formula term with C(var, Contrast) if requested.
    If a variable is already wrapped in C(...), it is left unchanged.
    """
    out = term
    for var, contrast in (contrast_map or {}).items():
        # skip if already wrapped
        if re.search(rf"C\(\s*{re.escape(var)}\s*,", out):
            continue
        # word-boundary replace of var with C(var, Contrast)
        pattern = rf'(?<![A-Za-z0-9_]){re.escape(var)}(?![A-Za-z0-9_])'
        out = re.sub(pattern, f"C({var}, {contrast})", out)
    return out


def _z_crit(ci: float) -> float:
    """Critical z for two-sided CI; prefer scipy if available, else 1.96 for 95%."""
    try:
        from scipy.stats import norm  # type: ignore
        return float(norm.ppf(1 - (1 - ci) / 2.0))
    except Exception:
        # Fallback: exact only for 95%
        return 1.96 if abs(ci - 0.95) < 1e-6 else 1.96


def _clean_fixed_table(result, ci_level: float = 0.95) -> pd.DataFrame:
    """Build a tidy fixed-effects table from a MixedLMResults object."""
    fe = getattr(result, "fe_params", None)
    bse = getattr(result, "bse_fe", None)
    if fe is None or bse is None:
        raise RuntimeError("MixedLM result missing fixed-effects parameters (fe_params/bse_fe).")

    effects = pd.Index(fe.index, name="Effect")
    coef = pd.Series(np.asarray(fe), index=effects, name="Coef.")
    se = pd.Series(np.asarray(bse), index=effects, name="SE")
    zvals = pd.Series(coef.values / se.values, index=effects, name="Z")

    # p-values (two-sided normal approx)
    try:
        from scipy.stats import norm  # type: ignore
        pvals = pd.Series(2 * (1 - norm.cdf(np.abs(zvals.values))), index=effects, name="P>|z|")
    except Exception:
        # Normal approx without scipy
        def _p_from_z(z):
            # Approximation using error function; good enough for reporting
            from math import erf, sqrt
            return 2 * (1 - 0.5 * (1 + erf(abs(z) / np.sqrt(2))))
        pvals = pd.Series([_p_from_z(z) for z in zvals.values], index=effects, name="P>|z|")

    zc = _z_crit(ci_level)
    ci_low = pd.Series(coef.values - zc * se.values, index=effects, name="CI Low")
    ci_high = pd.Series(coef.values + zc * se.values, index=effects, name="CI High")

    out = pd.concat([coef, se, zvals, pvals, ci_low, ci_high], axis=1).reset_index()
    out["Note"] = ""
    return out


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
) -> pd.DataFrame | Tuple[pd.DataFrame, "MixedLMResults"]:
    """
    Run a linear mixed-effects model with detailed diagnostics and tidy output.

    Parameters
    ----------
    data : pd.DataFrame
        Long-format DataFrame containing all variables.
    dv_col : str
        Dependent variable column (e.g., 'BCA_sum').
    group_col : str
        Grouping variable for random effects (e.g., 'Subject').
    fixed_effects : list of str
        List of fixed-effect terms to be added linearly (e.g., ['Condition * ROI', 'Sequence']).
        Terms can include interactions using '*', or ':' as usual.
    re_formula : str, optional
        Random-effects formula (default '1' for random intercepts). Examples: '1', '~ROI'.
        NOTE: Random slopes may require adequate sample size to converge.
    method : str, optional
        'reml' (default) for parameter estimation; use 'ml' for model comparisons.
    contrast_map : dict, optional
        Map of variable -> contrast name to inject into the formula via C(var, Contrast).
        Example: {'Condition': 'Sum', 'ROI': 'Sum'} for sum-to-zero coding.
    ci_level : float, optional
        Confidence level for CIs over fixed effects (default 0.95).
    return_model : bool, optional
        If True, return (table, statsmodels MixedLMResults) for further inspection.

    Returns
    -------
    pandas.DataFrame  (or tuple with MixedLMResults if return_model=True)

    Raises
    ------
    ValueError : if required columns are missing or data becomes empty after NA drop.
    RuntimeError: if model fitting fails.
    """
    # --- imports (scoped to improve import-time performance) ---
    try:
        import statsmodels.formula.api as smf  # type: ignore
    except ImportError as e:
        raise ImportError(
            "statsmodels is required for mixed effects modeling. Install via `pip install statsmodels`."
        ) from e

    # --- validate inputs ---
    if not isinstance(fixed_effects, (list, tuple)) or len(fixed_effects) == 0:
        raise ValueError("`fixed_effects` must be a non-empty list of formula terms.")

    required_cols = [dv_col, group_col]
    # Try to infer variable names from fixed_effects to check presence
    model_vars = sorted({v for term in fixed_effects for v in _extract_variables(term)})
    required_cols.extend(model_vars)
    missing = [c for c in required_cols if c not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in data for MixedLM: {missing}")

    # Drop NA rows on required cols
    df = data.dropna(subset=required_cols).copy()
    if df.empty:
        raise ValueError("After dropping missing values, no data remain for MixedLM.")

    # --- build formula with optional contrasts ---
    try:
        # Apply requested contrasts inline (e.g., C(ROI, Sum))
        fixed_terms = [
            _apply_contrasts_to_term(term, contrast_map or {}) for term in fixed_effects
        ]
        fixed_formula = " + ".join(fixed_terms)
        formula = f"{dv_col} ~ {fixed_formula}"
        logger.info("MixedLM formula: %s", formula)
        logger.info("Random effects (re_formula): %s", re_formula)
    except Exception as e:
        raise RuntimeError(f"Failed to construct formula: {e}")

    # --- fit model ---
    reml_flag = (method or "reml").strip().lower() == "reml"
    try:
        model = smf.mixedlm(formula, df, groups=df[group_col], re_formula=re_formula)
        # More stable optimizer settings than defaults
        result = model.fit(reml=reml_flag, method="lbfgs", maxiter=500, full_output=True)
    except Exception as e:
        # Second attempt with a different optimizer if lbfgs fails early
        try:
            result = model.fit(reml=reml_flag, method="powell", maxiter=500, full_output=True)
        except Exception as e2:
            logger.error("MixedLM fitting failed. First error (lbfgs): %s", e)
            logger.error("MixedLM fitting failed. Second error (powell): %s", e2)
            raise RuntimeError(f"Failed to run mixed effects model: {e2}") from e

    # --- diagnostics ---
    try:
        converged = bool(getattr(result, "converged", False))
        mret = getattr(result, "mle_retvals", {}) or {}
        if not converged:
            logger.warning("MixedLM did NOT converge. Optimizer info: %s", mret)
        else:
            logger.info("MixedLM converged. Optimizer info: %s", mret)
        logger.info("LogLik=%.3f  AIC=%.3f  BIC=%.3f  Method=%s",
                    float(getattr(result, "llf", np.nan)),
                    float(getattr(result, "aic", np.nan)),
                    float(getattr(result, "bic", np.nan)),
                    "REML" if reml_flag else "ML")
        # Group variance (random intercept variance) summary is often informative
        if hasattr(result, "random_effects") and hasattr(result, "cov_re"):
            logger.info("Random-effects covariance (cov_re):\n%s", str(result.cov_re))
    except Exception:
        pass

    # --- fixed-effects table ---
    table = _clean_fixed_table(result, ci_level=ci_level)

    # Add convergence note on each row if not converged
    if not bool(getattr(result, "converged", False)):
        table["Note"] = table["Note"].mask(table["Note"].astype(bool), table["Note"] + "; ").fillna("") + "Model did not converge"

    if return_model:
        return table, result
    return table

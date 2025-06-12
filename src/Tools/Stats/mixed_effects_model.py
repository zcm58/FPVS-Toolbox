# mixed_effects_model.py
# -*- coding: utf-8 -*-
"""
Provides a helper function to run a linear mixed effects model using
statsmodels MixedLM on long-format data.
"""

import pandas as pd
import logging
import re

logger = logging.getLogger(__name__)


def _extract_variables(term: str) -> set:
    """Return variable names found within a fixed effects term."""
    return {v.strip() for v in re.split(r"[*:+]", term) if v.strip()}


def run_mixed_effects_model(data: pd.DataFrame, dv_col: str, group_col: str, fixed_effects: list):
    """Run a linear mixed effects model with detailed logging.

    Parameters
    ----------
    data : pd.DataFrame
        Long-format DataFrame containing all variables.
    dv_col : str
        Name of the dependent variable column.
    group_col : str
        Column specifying grouping variable for random intercepts (e.g., subject).
    fixed_effects : list of str
        Column names to include as fixed effects.

    Returns
    -------
    pd.DataFrame
        Table of fixed effect coefficients with p-values.
    
    Notes
    -----
    The function logs each step of the modeling process to aid new users in
    understanding what is happening under the hood.
    """
    logger.info(
        "Starting mixed effects model with dependent variable '%s' and grouping column '%s'.",
        dv_col,
        group_col,
    )

    try:
        import statsmodels.formula.api as smf
    except ImportError:
        raise ImportError(
            "statsmodels is required for mixed effects modeling. Please install it via `pip install statsmodels`."
        )

    parsed_vars = sorted({var for term in fixed_effects for var in _extract_variables(term)})
    required_cols = [dv_col, group_col] + parsed_vars
    logger.info("Checking for required columns: %s", required_cols)
    missing = [col for col in required_cols if col not in data.columns]
    if missing:
        logger.error("Missing required columns: %s", missing)
        raise ValueError(f"Missing required columns in data for MixedLM: {missing}")

    logger.info("Dropping rows with missing values in required columns.")
    before_drop = len(data)
    df = data.dropna(subset=required_cols)
    after_drop = len(df)
    logger.info("Rows before drop: %d, after drop: %d", before_drop, after_drop)
    if df.empty:
        raise ValueError("After dropping missing values, no data remain for MixedLM.")

    fixed_formula = " + ".join(fixed_effects)
    formula = f"{dv_col} ~ {fixed_formula}"
    logger.info("Model formula: %s", formula)

    try:
        logger.info("Fitting mixed effects model. This may take a moment...")
        model = smf.mixedlm(formula, df, groups=df[group_col])
        result = model.fit()
        logger.info("Model fitting complete.")

        logger.info("Extracting summary table of fixed effects.")
        summary_table = result.summary().tables[1]

        if hasattr(summary_table, "data"):
            logger.info("Summary returned as statsmodels SimpleTable object.")
            df_result = pd.DataFrame(summary_table.data[1:], columns=summary_table.data[0])
        elif isinstance(summary_table, pd.DataFrame):
            logger.info("Summary returned as pandas DataFrame.")
            # Preserve index which contains effect names
            df_result = summary_table.reset_index()
            if "Effect" not in df_result.columns:
                df_result = df_result.rename(columns={df_result.columns[0]: "Effect"})
        else:
            logger.info(
                "Summary format unexpected. Building table from model parameters and p-values."
            )
            df_result = pd.DataFrame({"Coef.": result.params, "P>|z|": result.pvalues})
            df_result.index.name = "Effect"
            df_result = df_result.reset_index()

        if df_result.columns[0] == "":
            logger.info("Renaming first column to 'Effect'.")
            df_result = df_result.rename(columns={"": "Effect"})

        logger.info("Interpreting fixed effects results for user-friendly output.")

        # Provide a basic interpretation of each effect for easier understanding
        for _, row in df_result.iterrows():
            effect = str(row.get("Effect", "")).strip()
            coef = row.get("Coef.", row.get("coef", ""))
            p_val = row.get("P>|z|", row.get("P>|t|", ""))

            if effect.lower().startswith("intercept"):
                explanation = (
                    "Intercept represents the expected value when all predictors "
                    "are at their reference level."
                )
            else:
                explanation = f"Effect of {effect} relative to the baseline level."

            try:
                p_val_float = float(p_val)
                significance = "significant" if p_val_float < 0.05 else "not significant"
                logger.info(
                    "%s Coef=%.3f, p=%s (%s)",
                    explanation,
                    float(coef) if coef != "" else float("nan"),
                    p_val,
                    significance,
                )
            except Exception:
                logger.info("%s Coef=%s, p=%s", explanation, coef, p_val)

        logger.info("Mixed effects model run successfully.")
        return df_result
    except Exception as e:
        logger.error("Failed to run mixed effects model: %s", e)
        raise RuntimeError(f"Failed to run mixed effects model: {e}")

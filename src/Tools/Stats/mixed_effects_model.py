# mixed_effects_model.py
# -*- coding: utf-8 -*-
"""
Provides a helper function to run a linear mixed effects model using
statsmodels MixedLM on long-format data.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)


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

    required_cols = [dv_col, group_col] + fixed_effects
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
            df_result = summary_table.reset_index(drop=True)
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

        logger.info("Mixed effects model run successfully.")
        return df_result
    except Exception as e:
        logger.error("Failed to run mixed effects model: %s", e)
        raise RuntimeError(f"Failed to run mixed effects model: {e}")

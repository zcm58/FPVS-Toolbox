# mixed_effects_model.py
# -*- coding: utf-8 -*-
"""
Provides a helper function to run a linear mixed effects model using
statsmodels MixedLM on long-format data.
"""

import pandas as pd


def run_mixed_effects_model(data: pd.DataFrame, dv_col: str, group_col: str, fixed_effects: list):
    """Run a linear mixed effects model.

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
    """
    try:
        import statsmodels.formula.api as smf
    except ImportError:
        raise ImportError(
            "statsmodels is required for mixed effects modeling. Please install it via `pip install statsmodels`."
        )

    required_cols = [dv_col, group_col] + fixed_effects
    missing = [col for col in required_cols if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in data for MixedLM: {missing}")

    df = data.dropna(subset=required_cols)
    if df.empty:
        raise ValueError("After dropping missing values, no data remain for MixedLM.")

    fixed_formula = " + ".join(fixed_effects)
    formula = f"{dv_col} ~ {fixed_formula}"

    try:
        model = smf.mixedlm(formula, df, groups=df[group_col])
        result = model.fit()

        summary_table = result.summary().tables[1]

        if hasattr(summary_table, "data"):
            # statsmodels SimpleTable object
            df_result = pd.DataFrame(summary_table.data[1:], columns=summary_table.data[0])
        elif isinstance(summary_table, pd.DataFrame):
            # Some versions return a DataFrame directly
            df_result = summary_table.reset_index(drop=True)
        else:
            # Fallback: construct from params and p-values
            df_result = pd.DataFrame({
                "Coef.": result.params,
                "P>|z|": result.pvalues
            })
            df_result.index.name = "Effect"
            df_result = df_result.reset_index()

        if df_result.columns[0] == "":
            df_result = df_result.rename(columns={"": "Effect"})

        return df_result
    except Exception as e:
        raise RuntimeError(f"Failed to run mixed effects model: {e}")

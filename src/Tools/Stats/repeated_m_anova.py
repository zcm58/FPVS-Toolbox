# repeated_m_anova.py
# -*- coding: utf-8 -*-
"""
Provides a function to run within-subject (repeated measures) ANOVA on long-format data.

Function:
    run_repeated_measures_anova(data, dv_col, within_cols, subject_col) -> pandas.DataFrame

Parameters:
    data (pd.DataFrame): Long-format DataFrame containing one row per observation.
    dv_col (str): Name of the dependent variable column.
    within_cols (list of str): Names of within-subject factors (e.g., ['condition', 'roi']).
    subject_col (str): Name of the subject identifier column.

Returns:
    pd.DataFrame: ANOVA table with F-values, degrees of freedom, and p-values.

Dependencies:
    pandas, statsmodels
"""
import pandas as pd

def run_repeated_measures_anova(data, dv_col, within_cols, subject_col):
    """
    Runs a repeated measures ANOVA using statsmodels AnovaRM.

    Args:
        data (pd.DataFrame): Long-format data with columns for subject, dependent variable, and within factors.
        dv_col (str): Name of the dependent variable column in `data`.
        within_cols (list of str): List of column names representing within-subject factors.
        subject_col (str): Name of the column identifying subjects.

    Returns:
        pd.DataFrame: ANOVA table with effects, F-statistics, degrees of freedom, and p-values.
    """
    try:
        from statsmodels.stats.anova import AnovaRM
    except ImportError:
        raise ImportError("statsmodels is required for repeated measures ANOVA. Please install it via `pip install statsmodels`.")

    # Validate inputs
    required_cols = [subject_col, dv_col] + within_cols
    missing = [col for col in required_cols if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns in data for ANOVA: {missing}")

    # Drop NA values in relevant columns
    df = data.dropna(subset=required_cols)
    if df.empty:
        raise ValueError("After dropping missing values, no data remain for ANOVA.")

    # Fit the repeated measures model
    try:
        # Statsmodels AnovaRM expects data in a DataFrame
        # subject: subject identifier
        # within: list of within-subject factor names
        aov = AnovaRM(data=df, depvar=dv_col, subject=subject_col, within=within_cols)
        res = aov.fit()

        # Extract ANOVA table
        table = res.anova_table.copy()
        # Reset index to bring factor names into a column
        table = table.reset_index().rename(columns={'index': 'Effect'})
        return table

    except Exception as e:
        # Catch any errors from statsmodels and re-raise with context
        raise RuntimeError(f"Failed to run repeated measures ANOVA: {e}")

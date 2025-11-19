"""Mixed ANOVA helpers that treat `group` as a between-subject factor."""
from __future__ import annotations

import logging
from typing import List

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _partial_eta_squared(F: float, df_num: float, df_den: float) -> float:
    """Compute partial eta squared, guarding against division-by-zero."""
    try:
        num = float(F) * float(df_num)
        den = num + float(df_den)
        return float(num / den) if den > 0 else np.nan
    except Exception:
        return np.nan


def _tidy_pingouin_table(pg_table: pd.DataFrame) -> pd.DataFrame:
    """Normalize Pingouin mixed_anova output."""
    df = pg_table.copy()
    colmap = {
        "Source": "Effect",
        "F": "F Value",
        "ddof1": "Num DF",
        "ddof2": "Den DF",
        "p-unc": "Pr > F",
        "np2": "partial eta squared",
    }
    df = df.rename(columns={k: v for k, v in colmap.items() if k in df.columns})
    if "partial eta squared" not in df.columns and {"F Value", "Num DF", "Den DF"}.issubset(df.columns):
        df["partial eta squared"] = df.apply(
            lambda r: _partial_eta_squared(r["F Value"], r["Num DF"], r["Den DF"]),
            axis=1,
        )
    cols = ["Effect", "F Value", "Num DF", "Den DF", "Pr > F", "partial eta squared"]
    cols = [c for c in cols if c in df.columns]
    return df[cols].reset_index(drop=True)


def _tidy_statsmodels_table(table: pd.DataFrame) -> pd.DataFrame:
    """Normalize statsmodels AnovaRM table."""
    rename_map = {
        "F Value": "F Value",
        "Num DF": "Num DF",
        "Den DF": "Den DF",
        "Pr > F": "Pr > F",
        "F": "F Value",
        "Num DF1": "Num DF",
        "Num DF2": "Den DF",
        "Pr(>F)": "Pr > F",
    }
    df = table.copy()
    if "Effect" not in df.columns:
        df = df.reset_index().rename(columns={"index": "Effect"})
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    required = {"Effect", "F Value", "Num DF", "Den DF", "Pr > F"}
    if not required.issubset(df.columns):
        raise RuntimeError(
            "Unexpected ANOVA table format; expected columns including "
            "Effect, F Value, Num DF, Den DF, Pr > F."
        )
    df["partial eta squared"] = df.apply(
        lambda r: _partial_eta_squared(r["F Value"], r["Num DF"], r["Den DF"]),
        axis=1,
    )
    cols = ["Effect", "F Value", "Num DF", "Den DF", "Pr > F", "partial eta squared"]
    return df[cols].reset_index(drop=True)


def run_mixed_group_anova(
    data: pd.DataFrame,
    *,
    dv_col: str,
    subject_col: str,
    within_cols: List[str],
    between_col: str,
) -> pd.DataFrame:
    """Run a mixed ANOVA with a between-subject group factor."""
    if not isinstance(data, pd.DataFrame):
        raise ValueError("`data` must be a pandas DataFrame.")
    if not within_cols:
        raise ValueError("At least one within-subject factor is required.")

    needed_cols = {dv_col, subject_col, between_col, *within_cols}
    missing = [col for col in needed_cols if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns for mixed ANOVA: {missing}")

    df = data.dropna(subset=list(needed_cols)).copy()
    if df.empty:
        raise ValueError("No rows remain for mixed ANOVA after dropping missing data.")

    if df[between_col].nunique() < 2:
        raise ValueError("Mixed ANOVA requires at least two groups with valid data.")

    for col in [subject_col, between_col, *within_cols]:
        df[col] = df[col].astype(str)

    try:
        import pingouin as pg  # type: ignore

        pg_table = pg.mixed_anova(
            dv=dv_col,
            within=within_cols,
            between=between_col,
            subject=subject_col,
            data=df,
            detailed=True,
        )
        return _tidy_pingouin_table(pg_table)
    except ImportError:
        logger.info("Pingouin not available; using statsmodels.AnovaRM for mixed ANOVA.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Pingouin mixed_anova failed (%s); falling back to statsmodels.", exc)

    try:
        from statsmodels.stats.anova import AnovaRM  # type: ignore
    except ImportError as exc:  # pragma: no cover - handled at runtime
        raise ImportError("statsmodels is required for the mixed ANOVA fallback.") from exc

    model = AnovaRM(
        df,
        depvar=dv_col,
        subject=subject_col,
        within=within_cols,
        between=[between_col],
    )
    res = model.fit()
    table = res.anova_table
    return _tidy_statsmodels_table(table)

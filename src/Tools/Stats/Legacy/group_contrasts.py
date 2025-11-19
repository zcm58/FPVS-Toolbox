"""Pairwise between-group contrasts for condition × ROI combinations."""
from __future__ import annotations

import itertools
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _cohen_d_independent(x1: np.ndarray, x2: np.ndarray) -> float:
    """Compute Cohen's d for independent groups."""
    n1, n2 = x1.size, x2.size
    if n1 < 2 or n2 < 2:
        return np.nan
    var1 = np.var(x1, ddof=1)
    var2 = np.var(x2, ddof=1)
    pooled = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    if pooled <= 0:
        return np.nan
    return float((np.mean(x1) - np.mean(x2)) / np.sqrt(pooled))


def compute_group_contrasts(
    data: pd.DataFrame,
    *,
    subject_col: str,
    group_col: str,
    condition_col: str,
    roi_col: str,
    dv_col: str,
) -> pd.DataFrame:
    """Return pairwise group contrasts per (condition, ROI)."""
    if not isinstance(data, pd.DataFrame):
        raise ValueError("`data` must be a pandas DataFrame.")
    required = {subject_col, group_col, condition_col, roi_col, dv_col}
    missing = [col for col in required if col not in data.columns]
    if missing:
        raise ValueError(f"Missing required columns for group contrasts: {missing}")

    df = data.dropna(subset=[group_col, dv_col]).copy()
    if df.empty:
        raise ValueError("No rows remain for group contrasts after dropping missing groups/values.")

    df[group_col] = df[group_col].astype(str)
    unique_groups = sorted(df[group_col].unique())
    if len(unique_groups) < 2:
        raise ValueError("At least two groups are required for pairwise contrasts.")

    combos = list(itertools.combinations(unique_groups, 2))
    rows = []
    try:
        from scipy import stats  # type: ignore
    except Exception as exc:  # pragma: no cover - SciPy required for Stats tool
        raise ImportError("scipy is required for group contrasts.") from exc

    for (cond, roi), chunk in df.groupby([condition_col, roi_col], dropna=False):
        cond_label = "Unknown" if cond is None else str(cond)
        roi_label = "Unknown" if roi is None else str(roi)
        for g1, g2 in combos:
            g1_vals = chunk.loc[chunk[group_col] == g1, dv_col].dropna().to_numpy(dtype=float)
            g2_vals = chunk.loc[chunk[group_col] == g2, dv_col].dropna().to_numpy(dtype=float)
            if g1_vals.size == 0 or g2_vals.size == 0:
                continue
            try:
                res = stats.ttest_ind(g1_vals, g2_vals, equal_var=False, nan_policy="omit")
                t_stat = float(res.statistic)
                p_val = float(res.pvalue)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ttest_ind failed for %s vs %s (%s)", g1, g2, exc)
                t_stat, p_val = np.nan, np.nan
            cohen_d = _cohen_d_independent(g1_vals, g2_vals)
            rows.append(
                {
                    "condition": cond_label,
                    "roi": roi_label,
                    "group_1": g1,
                    "group_2": g2,
                    "n_1": int(g1_vals.size),
                    "n_2": int(g2_vals.size),
                    "mean_1": float(np.mean(g1_vals)) if g1_vals.size else np.nan,
                    "mean_2": float(np.mean(g2_vals)) if g2_vals.size else np.nan,
                    "difference": float(np.mean(g1_vals) - np.mean(g2_vals))
                    if g1_vals.size and g2_vals.size
                    else np.nan,
                    "t_stat": t_stat,
                    "p_value": p_val,
                    "effect_size": cohen_d,
                }
            )
    return pd.DataFrame(rows)

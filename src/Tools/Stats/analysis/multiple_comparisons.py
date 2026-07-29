"""Named-family multiple-comparison adjustments for Stats result tables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from Tools.Stats.analysis.inference_contracts import CorrectionMethod, FamilySpec


FAMILY_METADATA_COLUMNS: tuple[str, ...] = (
    "family_id",
    "family_label",
    "family_size",
    "adjustment_method",
    "alpha",
    "p_raw",
    "p_adjusted",
    "reject_adjusted",
)


def apply_family_correction(
    results: pd.DataFrame,
    family: FamilySpec,
    *,
    p_col: str = "p_raw",
) -> pd.DataFrame:
    """Adjust all finite p-values in one declared family without dropping rows."""

    if not isinstance(results, pd.DataFrame):
        raise TypeError("results must be a pandas DataFrame.")
    if not isinstance(family, FamilySpec):
        raise TypeError("family must be a FamilySpec.")
    if p_col not in results.columns:
        raise ValueError(f"Missing raw p-value column: {p_col!r}.")

    out = results.copy()
    numeric_p = pd.to_numeric(out[p_col], errors="coerce").astype(float)
    finite_mask = pd.Series(
        np.isfinite(numeric_p.to_numpy(dtype=float)),
        index=out.index,
        dtype=bool,
    )
    out_of_range = finite_mask & ((numeric_p < 0.0) | (numeric_p > 1.0))
    if bool(out_of_range.any()):
        bad_values = numeric_p.loc[out_of_range].tolist()
        raise ValueError(f"Finite p-values must lie between 0 and 1; got {bad_values!r}.")

    raw_values = numeric_p.where(finite_mask, np.nan)
    adjusted = pd.Series(np.nan, index=out.index, dtype=float)
    rejected = pd.Series(False, index=out.index, dtype=bool)
    valid_values = raw_values.loc[finite_mask].to_numpy(dtype=float)

    if valid_values.size:
        if family.method is CorrectionMethod.NONE:
            adjusted_values = valid_values.copy()
            rejected_values = adjusted_values <= family.alpha
        else:
            rejected_values, adjusted_values, _, _ = multipletests(
                valid_values,
                alpha=family.alpha,
                method=family.method.value,
            )
        adjusted.loc[finite_mask] = np.asarray(adjusted_values, dtype=float)
        rejected.loc[finite_mask] = np.asarray(rejected_values, dtype=bool)

    out["family_id"] = family.family_id
    out["family_label"] = family.family_label
    out["family_size"] = int(valid_values.size)
    out["adjustment_method"] = family.method.value
    out["alpha"] = family.alpha
    out["p_raw"] = raw_values
    out["p_adjusted"] = adjusted
    out["reject_adjusted"] = rejected
    return out


def adjust_p_values(
    p_values: Iterable[object],
    family: FamilySpec,
) -> pd.DataFrame:
    """Return a correction table for a simple sequence of p-values."""

    return apply_family_correction(
        pd.DataFrame({"p_raw": list(p_values)}),
        family,
    )


def apply_declared_families(
    results: pd.DataFrame,
    families: Iterable[FamilySpec] | Mapping[str, FamilySpec],
    *,
    family_col: str = "family_id",
    p_col: str = "p_raw",
) -> pd.DataFrame:
    """Apply multiple named families while preserving original row order."""

    if not isinstance(results, pd.DataFrame):
        raise TypeError("results must be a pandas DataFrame.")
    if family_col not in results.columns:
        raise ValueError(f"Missing family identifier column: {family_col!r}.")
    if bool(results[family_col].isna().any()):
        raise ValueError("Every result row must declare a non-missing family ID.")
    if isinstance(families, Mapping):
        specs = tuple(families.values())
    else:
        specs = tuple(families)
    if not all(isinstance(spec, FamilySpec) for spec in specs):
        raise TypeError("families must contain FamilySpec instances.")

    by_id: dict[str, FamilySpec] = {}
    for spec in specs:
        key = spec.family_id.casefold()
        if key in by_id:
            raise ValueError(f"Duplicate FamilySpec ID: {spec.family_id!r}.")
        by_id[key] = spec

    requested_keys = results[family_col].dropna().astype(str).str.casefold()
    unknown = sorted(set(requested_keys) - set(by_id))
    if unknown:
        raise ValueError("No FamilySpec was provided for family ID(s): " + ", ".join(unknown))

    pieces: list[pd.DataFrame] = []
    for key, spec in by_id.items():
        mask = results[family_col].astype(str).str.casefold().eq(key)
        if not bool(mask.any()):
            continue
        piece = apply_family_correction(results.loc[mask], spec, p_col=p_col)
        piece["_family_original_order"] = np.flatnonzero(mask.to_numpy())
        pieces.append(piece)

    if not pieces:
        empty = results.copy()
        for column in FAMILY_METADATA_COLUMNS:
            if column not in empty.columns:
                empty[column] = pd.Series(index=empty.index, dtype=object)
        return empty

    out = pd.concat(pieces, axis=0)
    out = out.sort_values("_family_original_order", kind="stable")
    out = out.drop(columns=["_family_original_order"])
    out.index = results.index
    return out


__all__ = [
    "FAMILY_METADATA_COLUMNS",
    "adjust_p_values",
    "apply_declared_families",
    "apply_family_correction",
]

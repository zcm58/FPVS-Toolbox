"""Helpers for computing and exporting DV variant tables."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

import pandas as pd

from Tools.Stats.PySide6.dv_policies import (
    FIXED_K_POLICY_NAME,
    LEGACY_POLICY_NAME,
    ROSSION_POLICY_NAME,
    normalize_dv_policy,
    prepare_summed_bca_data,
)


DV_POLICY_SHORT_NAMES = {
    LEGACY_POLICY_NAME: "Legacy",
    FIXED_K_POLICY_NAME: "FixedK",
    ROSSION_POLICY_NAME: "Rossion",
}


@dataclass(frozen=True)
class DVVariantPayload:
    """Represent the DVVariantPayload part of the Stats PySide6 tool."""
    primary_name: str
    primary_df: pd.DataFrame
    variant_dfs: Dict[str, pd.DataFrame]
    summary_df: pd.DataFrame
    errors: List[dict]
    selected_variants: List[str]


def dv_policy_short_name(policy_name: str) -> str:
    """Handle the dv policy short name step for the Stats PySide6 workflow."""
    return DV_POLICY_SHORT_NAMES.get(policy_name, policy_name.replace(" ", ""))


def build_long_dv_table(
    all_subject_bca_data: Dict[str, Dict[str, Dict[str, float]]],
) -> pd.DataFrame:
    """Handle the build long dv table step for the Stats PySide6 workflow."""
    rows: List[dict] = []
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    rows.append(
                        {
                            "subject": pid,
                            "condition": cond_name,
                            "roi": roi_name,
                            "value": value,
                        }
                    )
    return pd.DataFrame(rows)


def build_dv_comparison_summary(
    dv_tables: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Handle the build dv comparison summary step for the Stats PySide6 workflow."""
    if not dv_tables:
        return pd.DataFrame()

    merged: Optional[pd.DataFrame] = None
    for name, df in dv_tables.items():
        if df is None or df.empty:
            continue
        short = dv_policy_short_name(name)
        stats = (
            df.groupby(["condition", "roi"], dropna=False)["value"]
            .agg(["count", "mean", "std"])
            .reset_index()
        )
        stats = stats.rename(
            columns={
                "count": f"N__{short}",
                "mean": f"mean__{short}",
                "std": f"sd__{short}",
            }
        )
        if merged is None:
            merged = stats
        else:
            merged = merged.merge(stats, on=["condition", "roi"], how="outer")

    return merged if merged is not None else pd.DataFrame()


def compute_dv_variants_payload(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    rois: Dict[str, List[str]],
    dv_policy: dict[str, object] | None,
    variant_policies: List[dict[str, object]],
    log_func: Callable[[str], None],
    primary_data: Optional[Dict[str, Dict[str, Dict[str, float]]]] = None,
) -> Optional[DVVariantPayload]:
    """Handle the compute dv variants payload step for the Stats PySide6 workflow."""
    if not variant_policies:
        return None

    primary_settings = normalize_dv_policy(dv_policy)
    primary_name = primary_settings.name

    if primary_data is None:
        primary_data = prepare_summed_bca_data(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            base_freq=base_freq,
            log_func=log_func,
            rois=rois,
            dv_policy=dv_policy,
        )
    if not primary_data:
        raise RuntimeError("Primary DV data preparation failed (empty).")

    primary_df = build_long_dv_table(primary_data)
    errors: List[dict] = []
    variant_dfs: Dict[str, pd.DataFrame] = {}
    selected_variants: List[str] = []

    for policy in variant_policies:
        settings = normalize_dv_policy(policy)
        name = settings.name
        selected_variants.append(name)
        if name == primary_name:
            log_func(
                f"Skipping DV variant {name} because it matches the primary DV method."
            )
            continue
        try:
            variant_data = prepare_summed_bca_data(
                subjects=subjects,
                conditions=conditions,
                subject_data=subject_data,
                base_freq=base_freq,
                log_func=log_func,
                rois=rois,
                dv_policy=policy,
            )
            if not variant_data:
                raise RuntimeError("Data preparation failed (empty).")
            variant_dfs[name] = build_long_dv_table(variant_data)
        except Exception as exc:  # noqa: BLE001
            errors.append({"variant": name, "error": str(exc)})

    all_tables = {primary_name: primary_df, **variant_dfs}
    summary_df = build_dv_comparison_summary(all_tables)

    return DVVariantPayload(
        primary_name=primary_name,
        primary_df=primary_df,
        variant_dfs=variant_dfs,
        summary_df=summary_df,
        errors=errors,
        selected_variants=selected_variants,
    )


def _sheet_name(prefix: str, policy_name: str) -> str:
    """Handle the sheet name step for the Stats PySide6 workflow."""
    short = dv_policy_short_name(policy_name)
    return f"{prefix}{short}"[:31]


def export_dv_variants_workbook(
    *,
    save_path: Path,
    primary_name: str,
    primary_df: pd.DataFrame,
    variant_dfs: Dict[str, pd.DataFrame],
    summary_df: pd.DataFrame,
    errors: List[dict],
    log_func: Callable[[str], None],
) -> None:
    """Handle the export dv variants workbook step for the Stats PySide6 workflow."""
    save_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(save_path, engine="openpyxl") as writer:
        primary_df.to_excel(
            writer,
            sheet_name=_sheet_name("DV__PRIMARY__", primary_name),
            index=False,
        )

        for name, df in variant_dfs.items():
            df.to_excel(
                writer,
                sheet_name=_sheet_name("DV__VAR__", name),
                index=False,
            )

        if summary_df is not None and not summary_df.empty:
            summary_df.to_excel(writer, sheet_name="DV Comparison Summary", index=False)
        else:
            pd.DataFrame().to_excel(
                writer, sheet_name="DV Comparison Summary", index=False
            )

        if errors:
            pd.DataFrame(errors).to_excel(
                writer, sheet_name="DV Variant Errors", index=False
            )
        else:
            pd.DataFrame(columns=["variant", "error"]).to_excel(
                writer, sheet_name="DV Variant Errors", index=False
            )

    log_func(f"Exported DV variants workbook to {save_path}")

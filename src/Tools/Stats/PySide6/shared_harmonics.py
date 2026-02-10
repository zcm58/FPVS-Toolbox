"""Shared (cross-group) harmonic selection helpers for Stats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment

from Tools.Stats.Legacy.excel_io import safe_read_excel
from Tools.Stats.Legacy.stats_analysis import (
    SUMMED_BCA_Z_SHEET_NAME,
    _match_freq_column,
)
from Tools.Stats.PySide6.group_harmonics import _build_harmonic_domain

SELECTION_RULE = "two_consecutive_z_gt_thresh"
DEFAULT_Z_THRESH = 1.64
POLICY_NAME = "VANDER_DONCK_POOLED_ROI_Z"
CONDITION_COMBINATION_RULE = "mean_across_conditions_then_two_consecutive"
_ALT_Z_SHEET_NAME = "Z Scores"


def _resolve_z_sheet_name(file_path: str) -> str | None:
    for candidate in (SUMMED_BCA_Z_SHEET_NAME, _ALT_Z_SHEET_NAME):
        try:
            safe_read_excel(file_path, sheet_name=candidate, index_col="Electrode")
            return candidate
        except Exception:  # noqa: BLE001
            continue
    return None


def _find_first_z_columns_with_fallback(
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    log_func: Callable[[str], None],
) -> tuple[pd.Index, str]:
    for pid in subjects:
        for condition in conditions:
            file_path = subject_data.get(pid, {}).get(condition)
            if not file_path:
                continue
            chosen_sheet = _resolve_z_sheet_name(file_path)
            if chosen_sheet is None:
                continue
            try:
                df_z = safe_read_excel(file_path, sheet_name=chosen_sheet, index_col="Electrode")
                return df_z.columns, chosen_sheet
            except Exception as exc:  # noqa: BLE001
                log_func(f"Failed to read Z columns from {file_path}: {exc}")
    return pd.Index([]), SUMMED_BCA_Z_SHEET_NAME


@dataclass(frozen=True)
class SharedHarmonicsResult:
    harmonics_by_roi: dict[str, list[float]]
    exclude_harmonic1_applied: bool
    z_thresh: float
    conditions_used: list[str]
    condition_harmonics_by_roi: dict[str, dict[str, list[float]]]
    strict_intersection_harmonics_by_roi: dict[str, list[float]]
    mean_z_by_condition: dict[str, pd.DataFrame]
    pooled_mean_z_table: pd.DataFrame
    z_sheet_used: str
    condition_combination_rule_used: str
    diagnostics: dict[str, object]


def _select_two_consecutive_significant(
    harmonic_freqs: list[float],
    mean_z_lookup: dict[float, float],
    *,
    z_threshold: float,
    stop_after_n_nonsig: int = 2,
) -> list[float]:
    selected: list[float] = []
    sig_run = 0
    nonsig_run = 0
    criterion_met = False

    for idx, freq in enumerate(harmonic_freqs):
        mean_z = float(mean_z_lookup.get(float(freq), np.nan))
        is_sig = bool(np.isfinite(mean_z) and mean_z > z_threshold)

        if is_sig:
            sig_run += 1
            nonsig_run = 0
            if not criterion_met:
                if sig_run >= 2:
                    criterion_met = True
                    prev_freq = float(harmonic_freqs[idx - 1])
                    if prev_freq not in selected:
                        selected.append(prev_freq)
                    selected.append(float(freq))
            else:
                selected.append(float(freq))
            continue

        sig_run = 0
        if not criterion_met:
            continue
        nonsig_run += 1
        if nonsig_run >= stop_after_n_nonsig:
            break

    return sorted(set(selected))


def _select_after_first_sig_until_two_nonsig(
    harmonic_freqs: list[float],
    mean_z_lookup: dict[float, float],
    *,
    z_threshold: float,
    stop_after_n_nonsig: int = 2,
) -> tuple[list[float], dict[str, object]]:
    """
    Audited alignment note:
    - Stats tool selector source of truth is `select_rossion_harmonics_by_roi`
      in `group_harmonics.py`.
    - Significance uses `np.isfinite(mean_z) and mean_z > z_threshold` (strictly `>`).
    - The scan ignores leading non-significant harmonics until the first significant
      harmonic is found.
    - After first significant harmonic, stop is triggered by two consecutive
      non-significant harmonics.
    - Non-finite values are treated as non-significant.

    This helper applies those same start/stop semantics for the between-group pooled
    ROI-Z path, while returning the full inclusion window (both significant and
    non-significant harmonics) and structured diagnostics.
    """
    selected: list[float] = []
    first_sig_index: int | None = None
    nonsig_run = 0
    stop_index: int | None = None

    max_z = float("nan")
    max_z_harmonic: float | None = None
    count_sig = 0

    for idx, freq in enumerate(harmonic_freqs):
        mean_z = float(mean_z_lookup.get(float(freq), np.nan))
        is_sig = bool(np.isfinite(mean_z) and mean_z > z_threshold)

        if np.isfinite(mean_z) and (not np.isfinite(max_z) or mean_z > max_z):
            max_z = mean_z
            max_z_harmonic = float(freq)

        if is_sig:
            count_sig += 1

        if first_sig_index is None:
            if not is_sig:
                continue
            first_sig_index = idx
            nonsig_run = 0
            selected.append(float(freq))
            continue

        selected.append(float(freq))
        if is_sig:
            nonsig_run = 0
        else:
            nonsig_run += 1
            if nonsig_run >= stop_after_n_nonsig:
                stop_index = idx
                break

    diagnostics = {
        "first_sig_index": (int(first_sig_index + 1) if first_sig_index is not None else "none"),
        "first_sig_harmonic": (
            float(harmonic_freqs[first_sig_index]) if first_sig_index is not None else None
        ),
        "maxZ": (float(max_z) if np.isfinite(max_z) else np.nan),
        "maxZ_harmonic": max_z_harmonic,
        "count_sig": int(count_sig),
        "stop_index": (int(stop_index + 1) if stop_index is not None else None),
        "stop_harmonic": (float(harmonic_freqs[stop_index]) if stop_index is not None else None),
    }
    return selected, diagnostics


def compute_shared_harmonics(
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    base_freq: float,
    rois: dict[str, list[str]],
    exclude_harmonic1: bool,
    z_threshold: float = DEFAULT_Z_THRESH,
    log_func: Callable[[str], None],
) -> SharedHarmonicsResult:
    if not conditions:
        raise RuntimeError("No selected conditions were provided.")

    columns, z_sheet_used = _find_first_z_columns_with_fallback(subjects, conditions, subject_data, log_func)
    harmonic_freqs = _build_harmonic_domain(
        columns,
        base_freq,
        log_func,
        exclude_harmonic1=exclude_harmonic1,
        trace_label="shared",
    )
    if not harmonic_freqs:
        raise RuntimeError(
            "Shared harmonics selection produced an empty harmonic domain. "
            "Verify Z-score sheets and base frequency."
        )

    condition_rows: list[dict[str, object]] = []
    diagnostics: dict[str, object] = {
        "candidate_harmonic_domain": [float(v) for v in harmonic_freqs],
        "exclude_harmonic1_applied": bool(exclude_harmonic1),
        "z_sheet_preference": SUMMED_BCA_Z_SHEET_NAME,
        "z_sheet_used": z_sheet_used,
        "roi_condition_coverage": {},
        "empty_reasons": [],
        "roi_selection_diagnostics": {},
    }

    for condition in conditions:
        for roi_name in rois.keys():
            diagnostics["roi_condition_coverage"].setdefault(str(roi_name), {})[str(condition)] = {
                "n_total_participants": 0,
                "n_with_any_finite": 0,
            }

    for condition in conditions:
        for roi_name, roi_channels in rois.items():
            per_harmonic_values: dict[float, list[float]] = {float(freq): [] for freq in harmonic_freqs}
            finite_participants = 0
            total_participants = 0

            for pid in subjects:
                file_path = subject_data.get(pid, {}).get(condition)
                if not file_path:
                    continue
                try:
                    try:
                        df_z = safe_read_excel(file_path, sheet_name=z_sheet_used, index_col="Electrode")
                    except Exception:
                        fallback = _resolve_z_sheet_name(file_path)
                        if fallback is None:
                            raise RuntimeError("No compatible Z sheet found")
                        df_z = safe_read_excel(file_path, sheet_name=fallback, index_col="Electrode")
                except Exception as exc:  # noqa: BLE001
                    log_func(f"Failed to read Z sheet from {file_path}: {exc}")
                    continue

                total_participants += 1
                df_z.index = df_z.index.astype(str).str.upper().str.strip()
                roi_chans = [
                    str(ch).strip().upper()
                    for ch in (roi_channels or [])
                    if str(ch).strip().upper() in df_z.index
                ]
                if not roi_chans:
                    continue

                has_any_finite = False
                for freq in harmonic_freqs:
                    col = _match_freq_column(df_z.columns, float(freq))
                    if not col:
                        continue
                    vals = pd.to_numeric(df_z.loc[roi_chans, col], errors="coerce")
                    mean_val = float(np.nanmean(vals.values)) if np.isfinite(vals.values).any() else np.nan
                    if np.isfinite(mean_val):
                        per_harmonic_values[float(freq)].append(mean_val)
                        has_any_finite = True
                if has_any_finite:
                    finite_participants += 1

            diagnostics["roi_condition_coverage"][str(roi_name)][str(condition)] = {
                "n_total_participants": int(total_participants),
                "n_with_any_finite": int(finite_participants),
            }
            if finite_participants == 0:
                diagnostics["empty_reasons"].append(
                    f"No finite pooled ROI Z values for ROI={roi_name}, condition={condition}."
                )

            for freq in harmonic_freqs:
                participants = per_harmonic_values[float(freq)]
                mean_val = float(np.nanmean(participants)) if participants else np.nan
                condition_rows.append(
                    {
                        "condition": str(condition),
                        "roi": str(roi_name),
                        "harmonic_hz": float(freq),
                        "mean_z": mean_val,
                        "n_participants": int(len(participants)),
                        "significant": bool(np.isfinite(mean_val) and mean_val > z_threshold),
                    }
                )

    mean_z_all = pd.DataFrame(condition_rows)
    mean_z_by_condition: dict[str, pd.DataFrame] = {}
    for condition in conditions:
        mean_z_by_condition[str(condition)] = mean_z_all[mean_z_all["condition"] == str(condition)].copy()

    pooled_mean_z_table = (
        mean_z_all.groupby(["roi", "harmonic_hz"], as_index=False)["mean_z"].mean()
        if not mean_z_all.empty
        else pd.DataFrame(columns=["roi", "harmonic_hz", "mean_z"])
    )

    pooled_lookup: dict[tuple[str, float], float] = {}
    if not pooled_mean_z_table.empty:
        for _, row in pooled_mean_z_table.iterrows():
            pooled_lookup[(str(row["roi"]), float(row["harmonic_hz"]))] = float(row["mean_z"])

    harmonics_by_roi: dict[str, list[float]] = {}
    for roi_name in rois.keys():
        z_lookup = {
            float(freq): float(pooled_lookup.get((str(roi_name), float(freq)), np.nan))
            for freq in harmonic_freqs
        }
        selected, roi_diag = _select_after_first_sig_until_two_nonsig(
            harmonic_freqs,
            z_lookup,
            z_threshold=z_threshold,
            stop_after_n_nonsig=2,
        )
        harmonics_by_roi[str(roi_name)] = selected
        diagnostics["roi_selection_diagnostics"][str(roi_name)] = roi_diag
        if roi_diag["first_sig_index"] == "none":
            diagnostics["empty_reasons"].append(
                f"No significant pooled ROI Z harmonics for ROI={roi_name}; selection window is empty."
            )

    condition_harmonics_by_roi: dict[str, dict[str, list[float]]] = {}
    for condition in conditions:
        cond_lookup: dict[tuple[str, float], float] = {}
        condition_df = mean_z_by_condition[str(condition)]
        for _, row in condition_df.iterrows():
            cond_lookup[(str(row["roi"]), float(row["harmonic_hz"]))] = float(row["mean_z"])
        condition_harmonics_by_roi[str(condition)] = {
            str(roi_name): _select_two_consecutive_significant(
                harmonic_freqs,
                {
                    float(freq): float(cond_lookup.get((str(roi_name), float(freq)), np.nan))
                    for freq in harmonic_freqs
                },
                z_threshold=z_threshold,
                stop_after_n_nonsig=2,
            )
            for roi_name in rois.keys()
        }

    strict_intersection_harmonics_by_roi = intersect_condition_harmonics(
        condition_harmonics_by_roi=condition_harmonics_by_roi,
        conditions=conditions,
        rois=rois.keys(),
    )

    for roi_name in rois.keys():
        if not harmonics_by_roi.get(str(roi_name), []):
            diagnostics["empty_reasons"].append(
                f"No harmonics selected for ROI={roi_name} using pooled condition mean rule."
            )

    return SharedHarmonicsResult(
        harmonics_by_roi=harmonics_by_roi,
        exclude_harmonic1_applied=bool(exclude_harmonic1),
        z_thresh=float(z_threshold),
        conditions_used=list(conditions),
        condition_harmonics_by_roi=condition_harmonics_by_roi,
        strict_intersection_harmonics_by_roi=strict_intersection_harmonics_by_roi,
        mean_z_by_condition=mean_z_by_condition,
        pooled_mean_z_table=pooled_mean_z_table,
        z_sheet_used=z_sheet_used,
        condition_combination_rule_used=CONDITION_COMBINATION_RULE,
        diagnostics=diagnostics,
    )


def intersect_condition_harmonics(
    *,
    condition_harmonics_by_roi: dict[str, dict[str, list[float]]],
    conditions: list[str],
    rois,
) -> dict[str, list[float]]:
    harmonics_by_roi: dict[str, list[float]] = {}
    for roi_name in rois:
        per_condition_sets = [
            set(condition_harmonics_by_roi.get(cond, {}).get(str(roi_name), []))
            for cond in conditions
        ]
        if not per_condition_sets:
            harmonics_by_roi[str(roi_name)] = []
            continue
        shared = set.intersection(*per_condition_sets) if per_condition_sets else set()
        harmonics_by_roi[str(roi_name)] = sorted(float(v) for v in shared)
    return harmonics_by_roi


def export_shared_harmonics_summary(
    *,
    export_path: Path,
    result: SharedHarmonicsResult,
    project_path: Path,
) -> Path:
    export_path.parent.mkdir(parents=True, exist_ok=True)

    config_df = pd.DataFrame(
        [
            {
                "exclude_harmonic1_applied": result.exclude_harmonic1_applied,
                "z_thresh": result.z_thresh,
                "selection_rule": SELECTION_RULE,
                "policy_name": POLICY_NAME,
                "z_sheet_used": result.z_sheet_used,
                "condition_combination_rule_used": result.condition_combination_rule_used,
                "pooling": "across groups",
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "project_path": str(project_path),
                "conditions_used": ", ".join(result.conditions_used),
            }
        ]
    )

    rows: list[dict[str, object]] = []
    for roi, freqs in result.harmonics_by_roi.items():
        if not freqs:
            rows.append({"ROI": roi, "Harmonic_Hz": np.nan, "Included": False, "Notes": "No shared harmonics"})
            continue
        for freq in freqs:
            rows.append({"ROI": roi, "Harmonic_Hz": float(freq), "Included": True, "Notes": ""})
    harmonics_df = pd.DataFrame(rows, columns=["ROI", "Harmonic_Hz", "Included", "Notes"])

    with pd.ExcelWriter(export_path, engine="openpyxl") as writer:
        config_df.to_excel(writer, sheet_name="Config", index=False)
        harmonics_df.to_excel(writer, sheet_name="HarmonicsByROI", index=False)

        for worksheet in writer.book.worksheets:
            for row in worksheet.iter_rows():
                for cell in row:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
            for col in worksheet.columns:
                max_len = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col)
                worksheet.column_dimensions[col[0].column_letter].width = max_len + 2

    return export_path


__all__ = [
    "DEFAULT_Z_THRESH",
    "SELECTION_RULE",
    "CONDITION_COMBINATION_RULE",
    "SharedHarmonicsResult",
    "compute_shared_harmonics",
    "export_shared_harmonics_summary",
    "intersect_condition_harmonics",
]

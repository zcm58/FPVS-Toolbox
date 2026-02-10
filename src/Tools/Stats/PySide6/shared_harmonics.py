"""Shared (cross-group) harmonic selection helpers for Stats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment

from Tools.Stats.PySide6.group_harmonics import build_rossion_harmonics_summary

SELECTION_RULE = "two_consecutive_z_gt_thresh"
DEFAULT_Z_THRESH = 1.64


@dataclass(frozen=True)
class SharedHarmonicsResult:
    harmonics_by_roi: dict[str, list[float]]
    exclude_harmonic1_applied: bool
    z_thresh: float
    conditions_used: list[str]
    condition_harmonics_by_roi: dict[str, dict[str, list[float]]]
    mean_z_by_condition: dict[str, pd.DataFrame]


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

    condition_harmonics_by_roi: dict[str, dict[str, list[float]]] = {}
    mean_z_by_condition: dict[str, pd.DataFrame] = {}

    for condition in conditions:
        summary = build_rossion_harmonics_summary(
            subjects=subjects,
            conditions=[condition],
            subject_data=subject_data,
            base_freq=base_freq,
            rois=rois,
            z_threshold=z_threshold,
            exclude_harmonic1=exclude_harmonic1,
            log_func=log_func,
        )
        mean_z_by_condition[condition] = summary.mean_z_table.copy()

        mean_lookup: dict[tuple[str, float], float] = {}
        if not summary.mean_z_table.empty:
            for _, row in summary.mean_z_table.iterrows():
                mean_lookup[(str(row["roi"]), float(row["harmonic_hz"]))] = float(row["mean_z"])

        roi_harmonics: dict[str, list[float]] = {}
        for roi_name in rois.keys():
            z_lookup = {
                float(freq): float(mean_lookup.get((str(roi_name), float(freq)), np.nan))
                for freq in summary.harmonic_freqs
            }
            roi_harmonics[str(roi_name)] = _select_two_consecutive_significant(
                summary.harmonic_freqs,
                z_lookup,
                z_threshold=z_threshold,
                stop_after_n_nonsig=2,
            )
        condition_harmonics_by_roi[condition] = roi_harmonics

    harmonics_by_roi = intersect_condition_harmonics(
        condition_harmonics_by_roi=condition_harmonics_by_roi,
        conditions=conditions,
        rois=rois.keys(),
    )

    return SharedHarmonicsResult(
        harmonics_by_roi=harmonics_by_roi,
        exclude_harmonic1_applied=bool(exclude_harmonic1),
        z_thresh=float(z_threshold),
        conditions_used=list(conditions),
        condition_harmonics_by_roi=condition_harmonics_by_roi,
        mean_z_by_condition=mean_z_by_condition,
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
    "SharedHarmonicsResult",
    "compute_shared_harmonics",
    "export_shared_harmonics_summary",
    "intersect_condition_harmonics",
]

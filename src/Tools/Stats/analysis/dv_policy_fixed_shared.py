"""Fixed harmonics-by-ROI DV policy helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from Tools.Stats.io.excel_io import safe_read_excel
from Tools.Stats.analysis.stats_analysis import _current_rois_map, _match_freq_column
from Tools.Stats.analysis.dv_policy_settings import (
    DVPolicySettings,
    FIXED_SHARED_POLICY_NAME,
)


def _normalize_harmonics_by_roi(
    harmonics_by_roi: dict[str, list[float]] | None,
    *,
    rois: dict[str, list[str]],
) -> dict[str, list[float]]:
    """Handle the normalize harmonics by roi step for the Stats workflow."""
    normalized: dict[str, list[float]] = {}
    source = harmonics_by_roi or {}
    for roi_name in rois.keys():
        raw_freqs = source.get(str(roi_name), [])
        cleaned = sorted({float(freq) for freq in (raw_freqs or [])})
        normalized[str(roi_name)] = cleaned
    return normalized


def _aggregate_bca_sum_harmonics_fixed(
    *,
    file_path: str,
    participant_id: str,
    condition: str,
    roi_name: str,
    log_func: Callable[[str], None],
    harmonic_freqs: list[float],
    rois: dict[str, list[str]],
    diag_meta: Optional[dict[str, object]] = None,
) -> tuple[float, list[float]]:
    """Handle the aggregate bca sum harmonics fixed step for the Stats workflow."""
    try:
        if diag_meta is not None:
            diag_meta.setdefault("source_file", file_path)
            diag_meta.setdefault("sheet", "BCA (uV)")
            diag_meta.setdefault("row_label", None)
            diag_meta.setdefault("col_label", None)
            diag_meta.setdefault("raw_cell", None)

        df_bca = safe_read_excel(file_path, sheet_name="BCA (uV)", index_col="Electrode")
        df_bca.index = df_bca.index.astype(str).str.upper().str.strip()

        roi_channels = [str(ch).strip().upper() for ch in rois.get(roi_name, [])]
        if not roi_channels:
            log_func(f"ROI {roi_name} not defined.")
            return np.nan, list(harmonic_freqs)

        roi_chans = [ch for ch in roi_channels if ch in df_bca.index]
        if not roi_chans:
            log_func(f"No overlapping BCA data for ROI {roi_name} in {file_path}.")
            return np.nan, list(harmonic_freqs)
        if diag_meta is not None:
            diag_meta["row_label"] = roi_chans

        df_bca_roi = df_bca.loc[roi_chans].dropna(how="all")
        if df_bca_roi.empty:
            log_func(f"No data for ROI {roi_name} in {file_path}.")
            return np.nan, list(harmonic_freqs)

        cols_to_sum: List[str] = []
        missing_hz: list[float] = []
        for freq_val in harmonic_freqs:
            col_bca = _match_freq_column(df_bca_roi.columns, freq_val)
            if col_bca:
                cols_to_sum.append(col_bca)
            else:
                missing_hz.append(float(freq_val))

        if missing_hz:
            warning_payload = {
                "subject": str(participant_id),
                "condition": str(condition),
                "roi": str(roi_name),
                "missing_hz": missing_hz,
                "file_path": str(file_path),
            }
            log_func(f"Fixed harmonic DV warning: {warning_payload}")
            return np.nan, missing_hz

        if not cols_to_sum:
            return np.nan, list(harmonic_freqs)

        if diag_meta is not None:
            diag_meta["col_label"] = cols_to_sum
            diag_meta["raw_cell"] = df_bca_roi[cols_to_sum].to_dict(orient="index")

        bca_block = (
            df_bca_roi[cols_to_sum]
            .apply(pd.to_numeric, errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
        )
        bca_vals = bca_block.sum(axis=1, min_count=1)
        bca_vals = pd.to_numeric(bca_vals, errors="coerce").replace([np.inf, -np.inf], np.nan)
        if not bca_vals.notna().any():
            return np.nan, []

        out = float(bca_vals.mean(skipna=True))
        return (out if np.isfinite(out) else np.nan), []
    except Exception as exc:  # noqa: BLE001
        log_func(f"Error aggregating fixed-harmonic BCA for {file_path}, ROI {roi_name}: {exc}")
        return np.nan, list(harmonic_freqs)


def _prepare_fixed_harmonics_by_roi_bca_data(
    *,
    subjects: List[str],
    conditions: List[str],
    subject_data: Dict[str, Dict[str, str]],
    base_freq: float,
    log_func: Callable[[str], None],
    rois: Optional[Dict[str, List[str]]] = None,
    harmonics_by_roi: Optional[dict[str, list[float]]] = None,
    provenance_map: Optional[dict[tuple[str, str, str], dict[str, object]]] = None,
    dv_metadata: Optional[dict[str, object]] = None,
    settings: Optional[DVPolicySettings] = None,
) -> Optional[Dict[str, Dict[str, Dict[str, float]]]]:
    """Handle the prepare fixed harmonics by roi bca data step for the Stats workflow."""
    if not subjects or not subject_data:
        log_func("No subject data. Scan folder first.")
        return None

    rois_map = rois if rois is not None else _current_rois_map()
    if not rois_map:
        log_func("No ROIs defined or available.")
        return None

    normalized_harmonics = _normalize_harmonics_by_roi(harmonics_by_roi, rois=rois_map)
    if not any(normalized_harmonics.values()):
        raise RuntimeError(
            "Fixed-harmonic DV policy requires harmonics_by_roi with at least one harmonic."
        )

    all_subject_data: Dict[str, Dict[str, Dict[str, float]]] = {}
    missing_records: list[dict[str, object]] = []
    for pid in subjects:
        all_subject_data[pid] = {}
        for cond_name in conditions:
            file_path = subject_data.get(pid, {}).get(cond_name)
            all_subject_data[pid].setdefault(cond_name, {})
            for roi_name in rois_map.keys():
                harmonics = normalized_harmonics.get(roi_name, [])
                sum_val = np.nan
                diag_meta: Optional[dict[str, object]] = None
                if provenance_map is not None:
                    diag_meta = {}
                missing_hz: list[float] = []
                if file_path and Path(file_path).exists():
                    sum_val, missing_hz = _aggregate_bca_sum_harmonics_fixed(
                        file_path=file_path,
                        participant_id=pid,
                        condition=cond_name,
                        roi_name=roi_name,
                        log_func=log_func,
                        harmonic_freqs=harmonics,
                        rois=rois_map,
                        diag_meta=diag_meta,
                    )
                else:
                    log_func(f"Missing file for {pid} {cond_name}: {file_path}")
                    missing_hz = list(harmonics)
                all_subject_data[pid][cond_name][roi_name] = sum_val
                if missing_hz:
                    missing_records.append(
                        {
                            "subject": str(pid),
                            "condition": str(cond_name),
                            "roi": str(roi_name),
                            "missing_hz": sorted(float(freq) for freq in missing_hz),
                            "file_path": str(file_path or ""),
                        }
                    )
                if provenance_map is not None:
                    provenance = {
                        "source_file": file_path,
                        "sheet": "BCA (uV)",
                        "row_label": None,
                        "col_label": None,
                        "raw_cell": None,
                        "missing_hz": sorted(float(freq) for freq in missing_hz),
                    }
                    if diag_meta:
                        provenance.update(diag_meta)
                    provenance_map[(pid, cond_name, roi_name)] = provenance

    if dv_metadata is not None:
        if settings is not None:
            dv_metadata.update(
                settings.to_metadata(
                    base_freq=float(base_freq),
                    selected_conditions=conditions,
                )
            )
        dv_metadata["harmonics_by_roi"] = normalized_harmonics
        dv_metadata["missing_harmonics"] = missing_records

    return all_subject_data


def compute_fixed_harmonic_dv_table(
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
    rois: dict[str, list[str]],
    harmonics_by_roi: dict[str, list[float]],
    log_func: Callable[[str], None],
) -> dict[str, object]:
    """Compute fixed-harmonic Summed BCA DV values without model execution."""

    metadata: dict[str, object] = {}
    nested = _prepare_fixed_harmonics_by_roi_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=0.0,
        log_func=log_func,
        rois=rois,
        harmonics_by_roi=harmonics_by_roi,
        dv_metadata=metadata,
        settings=DVPolicySettings(name=FIXED_SHARED_POLICY_NAME),
    )
    if nested is None:
        raise RuntimeError("Failed to compute fixed-harmonic DV table.")

    rows: list[dict[str, object]] = []
    for pid in subjects:
        for condition in conditions:
            roi_values = (nested.get(pid, {}) or {}).get(condition, {}) or {}
            for roi_name in rois.keys():
                rows.append(
                    {
                        "subject": str(pid),
                        "condition": str(condition),
                        "roi": str(roi_name),
                        "dv_value": roi_values.get(roi_name, np.nan),
                    }
                )

    dv_df = pd.DataFrame(rows, columns=["subject", "condition", "roi", "dv_value"])
    missing_records = metadata.get("missing_harmonics", [])
    return {
        "dv_df": dv_df,
        "nested": nested,
        "harmonics_by_roi": metadata.get("harmonics_by_roi", {}),
        "missing_harmonics": missing_records if isinstance(missing_records, list) else [],
    }

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .constants import ELECTRODE_COL, SHEET_BCA, SHEET_SNR, SHEET_Z
from .utils import (
    build_hz_to_col_map,
    fmt_hz_list,
    harmonic_col_to_hz,
    hz_key,
    parse_participant_id,
    safe_mean,
    safe_sum,
)


def compute_roi_harmonic_means(
    df: pd.DataFrame,
    roi_electrodes: list[str],
    harmonic_cols: list[str],
) -> dict[float, float]:
    roi_df = df[df[ELECTRODE_COL].isin(roi_electrodes)].copy()
    if roi_df.empty:
        raise ValueError(f"Target electrodes {roi_electrodes} not found in Excel data.")
    out: dict[float, float] = {}
    for col in harmonic_cols:
        hz = hz_key(harmonic_col_to_hz(col))
        vals = pd.to_numeric(roi_df[col], errors="raise").to_numpy(dtype=float)
        out[hz] = safe_mean(vals)
    return out


def read_participant_file(
    xlsx_path: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    try:
        df_snr = pd.read_excel(xlsx_path, sheet_name=SHEET_SNR)
        df_z = pd.read_excel(xlsx_path, sheet_name=SHEET_Z)
        df_bca = pd.read_excel(xlsx_path, sheet_name=SHEET_BCA)
    except ValueError as exc:
        raise ValueError(
            f"File '{xlsx_path.name}' is missing one or more required sheets: "
            f"{SHEET_SNR}, {SHEET_Z}, {SHEET_BCA}."
        ) from exc

    for sheet_name, df in [(SHEET_SNR, df_snr), (SHEET_Z, df_z), (SHEET_BCA, df_bca)]:
        if ELECTRODE_COL not in df.columns:
            raise ValueError(
                f"File '{xlsx_path.name}' sheet '{sheet_name}' is missing column '{ELECTRODE_COL}'."
            )
    harm_cols = [c for c in df_z.columns if c != ELECTRODE_COL]
    return df_snr, df_z, df_bca, harm_cols


def summarize_participant_file_sums(
    xlsx_path: Path,
    condition_label: str,
    expected_hz_keys: list[float],
    roi_defs: dict[str, list[str]],
) -> list[dict[str, Any]]:
    pid, pid_num = parse_participant_id(xlsx_path.name)
    df_snr, df_z, df_bca, harm_cols = read_participant_file(xlsx_path)

    hz_to_col = build_hz_to_col_map(harm_cols)

    missing = [hz for hz in expected_hz_keys if hz not in hz_to_col]
    if missing:
        raise ValueError(
            f"File '{xlsx_path.name}' is missing expected harmonic columns (Hz): "
            f"[{fmt_hz_list(missing)}]."
        )

    cols_in_order = [hz_to_col[hz] for hz in expected_hz_keys]

    rows: list[dict[str, Any]] = []
    for roi_name, electrodes in roi_defs.items():
        z_by_hz = compute_roi_harmonic_means(df_z, electrodes, cols_in_order)
        snr_by_hz = compute_roi_harmonic_means(df_snr, electrodes, cols_in_order)
        bca_by_hz = compute_roi_harmonic_means(df_bca, electrodes, cols_in_order)

        sum_z = safe_sum(np.array([z_by_hz[hz] for hz in expected_hz_keys], dtype=float))
        sum_snr = safe_sum(np.array([snr_by_hz[hz] for hz in expected_hz_keys], dtype=float))
        sum_bca = safe_sum(np.array([bca_by_hz[hz] for hz in expected_hz_keys], dtype=float))

        rows.append(
            {
                "condition_label": condition_label,
                "participant_id": pid,
                "participant_num": pid_num,
                "ROI": roi_name,
                "n_harmonics_summed": int(len(expected_hz_keys)),
                "summed_harmonics_hz": fmt_hz_list(expected_hz_keys),
                "sum_Z": sum_z,
                "sum_SNR": sum_snr,
                "sum_BCA_uV": sum_bca,
                "source_file": str(xlsx_path),
            }
        )

    return rows


def compute_ratio_rows_from_sums(
    df_part_all: pd.DataFrame,
    cond_a: str,
    cond_b: str,
) -> pd.DataFrame:
    needed = {"participant_id", "ROI", "condition_label", "sum_Z", "sum_SNR", "sum_BCA_uV"}
    missing = needed - set(df_part_all.columns)
    if missing:
        raise ValueError(f"df_part_all missing columns: {sorted(list(missing))}")

    a = df_part_all[df_part_all["condition_label"] == cond_a].copy()
    b = df_part_all[df_part_all["condition_label"] == cond_b].copy()

    key_cols = ["participant_id", "ROI"]
    a = a[key_cols + ["sum_Z", "sum_SNR", "sum_BCA_uV"]].rename(
        columns={
            "sum_Z": "sum_Z_A",
            "sum_SNR": "sum_SNR_A",
            "sum_BCA_uV": "sum_BCA_A_uV",
        }
    )
    b = b[key_cols + ["sum_Z", "sum_SNR", "sum_BCA_uV"]].rename(
        columns={
            "sum_Z": "sum_Z_B",
            "sum_SNR": "sum_SNR_B",
            "sum_BCA_uV": "sum_BCA_B_uV",
        }
    )

    merged = pd.merge(a, b, on=key_cols, how="inner")

    def safe_ratio(num: float, den: float) -> float:
        if not (np.isfinite(num) and np.isfinite(den)):
            return float("nan")
        if abs(den) <= 1e-12:
            return float("nan")
        return float(num / den)

    merged["ratio_Z"] = [
        safe_ratio(n, d) for n, d in zip(merged["sum_Z_A"].to_numpy(), merged["sum_Z_B"].to_numpy())
    ]
    merged["ratio_SNR"] = [
        safe_ratio(n, d)
        for n, d in zip(merged["sum_SNR_A"].to_numpy(), merged["sum_SNR_B"].to_numpy())
    ]
    merged["ratio_BCA"] = [
        safe_ratio(n, d)
        for n, d in zip(merged["sum_BCA_A_uV"].to_numpy(), merged["sum_BCA_B_uV"].to_numpy())
    ]

    def ratio_notes(rows: pd.DataFrame) -> list[str]:
        notes = []
        for row in rows.itertuples(index=False):
            row_notes = []
            if not np.isfinite(row.ratio_Z):
                row_notes.append("bad_ratio_Z")
            if not np.isfinite(row.ratio_SNR):
                row_notes.append("bad_ratio_SNR")
            if not np.isfinite(row.ratio_BCA):
                row_notes.append("bad_ratio_BCA")
            notes.append(",".join(row_notes) if row_notes else ""
            )
        return notes

    merged["ratio_notes"] = ratio_notes(merged)

    merged = merged.sort_values(["ROI", "participant_id"], kind="stable").reset_index(drop=True)
    return merged


def group_summary_sums(df_part: pd.DataFrame) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for (cond, roi), sub in df_part.groupby(["condition_label", "ROI"], sort=True):
        z = pd.to_numeric(sub["sum_Z"], errors="coerce").to_numpy(dtype=float)
        s = pd.to_numeric(sub["sum_SNR"], errors="coerce").to_numpy(dtype=float)
        b = pd.to_numeric(sub["sum_BCA_uV"], errors="coerce").to_numpy(dtype=float)
        out.append(
            {
                "condition_label": cond,
                "ROI": roi,
                "mean_sum_Z": float(np.nanmean(z)) if np.isfinite(z).any() else float("nan"),
                "median_sum_Z": float(np.nanmedian(z)) if np.isfinite(z).any() else float("nan"),
                "sd_sum_Z": float(np.nanstd(z, ddof=1)) if np.isfinite(z).sum() >= 2 else float("nan"),
                "sem_sum_Z": float(np.nanstd(z, ddof=1) / np.sqrt(np.isfinite(z).sum()))
                if np.isfinite(z).sum() >= 2
                else float("nan"),
                "mean_sum_SNR": float(np.nanmean(s)) if np.isfinite(s).any() else float("nan"),
                "median_sum_SNR": float(np.nanmedian(s)) if np.isfinite(s).any() else float("nan"),
                "sd_sum_SNR": float(np.nanstd(s, ddof=1)) if np.isfinite(s).sum() >= 2 else float("nan"),
                "sem_sum_SNR": float(np.nanstd(s, ddof=1) / np.sqrt(np.isfinite(s).sum()))
                if np.isfinite(s).sum() >= 2
                else float("nan"),
                "mean_sum_BCA_uV": float(np.nanmean(b)) if np.isfinite(b).any() else float("nan"),
                "median_sum_BCA_uV": float(np.nanmedian(b)) if np.isfinite(b).any() else float("nan"),
                "sd_sum_BCA_uV": float(np.nanstd(b, ddof=1)) if np.isfinite(b).sum() >= 2 else float("nan"),
                "sem_sum_BCA_uV": float(np.nanstd(b, ddof=1) / np.sqrt(np.isfinite(b).sum()))
                if np.isfinite(b).sum() >= 2
                else float("nan"),
            }
        )

    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values(["condition_label", "ROI"], kind="stable").reset_index(drop=True)


def group_summary_ratios(df_ratio: pd.DataFrame) -> pd.DataFrame:
    out: list[dict[str, Any]] = []
    for roi, sub in df_ratio.groupby("ROI", sort=True):
        rz = pd.to_numeric(sub["ratio_Z"], errors="coerce").to_numpy(dtype=float)
        rs = pd.to_numeric(sub["ratio_SNR"], errors="coerce").to_numpy(dtype=float)
        rb = pd.to_numeric(sub["ratio_BCA"], errors="coerce").to_numpy(dtype=float)
        out.append(
            {
                "ROI": roi,
                "mean_ratio_Z": float(np.nanmean(rz)) if np.isfinite(rz).any() else float("nan"),
                "median_ratio_Z": float(np.nanmedian(rz)) if np.isfinite(rz).any() else float("nan"),
                "sd_ratio_Z": float(np.nanstd(rz, ddof=1)) if np.isfinite(rz).sum() >= 2 else float("nan"),
                "sem_ratio_Z": float(np.nanstd(rz, ddof=1) / np.sqrt(np.isfinite(rz).sum()))
                if np.isfinite(rz).sum() >= 2
                else float("nan"),
                "mean_ratio_SNR": float(np.nanmean(rs)) if np.isfinite(rs).any() else float("nan"),
                "median_ratio_SNR": float(np.nanmedian(rs)) if np.isfinite(rs).any() else float("nan"),
                "sd_ratio_SNR": float(np.nanstd(rs, ddof=1)) if np.isfinite(rs).sum() >= 2 else float("nan"),
                "sem_ratio_SNR": float(np.nanstd(rs, ddof=1) / np.sqrt(np.isfinite(rs).sum()))
                if np.isfinite(rs).sum() >= 2
                else float("nan"),
                "mean_ratio_BCA": float(np.nanmean(rb)) if np.isfinite(rb).any() else float("nan"),
                "median_ratio_BCA": float(np.nanmedian(rb)) if np.isfinite(rb).any() else float("nan"),
                "sd_ratio_BCA": float(np.nanstd(rb, ddof=1)) if np.isfinite(rb).sum() >= 2 else float("nan"),
                "sem_ratio_BCA": float(np.nanstd(rb, ddof=1) / np.sqrt(np.isfinite(rb).sum()))
                if np.isfinite(rb).sum() >= 2
                else float("nan"),
            }
        )

    if not out:
        return pd.DataFrame()
    return pd.DataFrame(out).sort_values(["ROI"], kind="stable").reset_index(drop=True)

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional


NEIGHBOR_OFFSETS = [*range(-11, 0), *range(1, 12)]


def build_fft_neighbors_rows(
    *,
    file_name: str,
    condition_label: str,
    condition_id: str,
    repetition_index: str,
    electrode_names: List[str],
    fft_amplitudes: np.ndarray,
    freqs: np.ndarray,
    fs: float,
    n_samples: int,
    target_freq: float = 1.2,
) -> List[Dict[str, Any]]:
    """Build per-channel FFT neighbor rows (±11 bins, excluding center bin)."""
    rows: List[Dict[str, Any]] = []
    if len(freqs) == 0:
        return rows

    k0 = int(round(target_freq * n_samples / fs))
    if not (0 <= k0 < len(freqs)):
        k0 = int(np.argmin(np.abs(freqs - target_freq)))
    f_bin_hz = float(freqs[k0]) if 0 <= k0 < len(freqs) else np.nan

    for chan_idx, channel_name in enumerate(electrode_names):
        row: Dict[str, Any] = {
            "file_name": file_name,
            "condition_label": condition_label,
            "condition_id": condition_id,
            "repetition_index": repetition_index,
            "channel_or_roi": channel_name,
            "target": "1.2Hz",
            "fs": float(fs),
            "N": int(n_samples),
            "T_sec": float(n_samples / fs) if fs else np.nan,
            "df_hz": float(fs / n_samples) if n_samples else np.nan,
            "k0": int(k0),
            "f_bin_hz": f_bin_hz,
            "warning": "",
        }
        out_of_bounds = []
        for offset in NEIGHBOR_OFFSETS:
            col_name = f"amp_m{abs(offset)}" if offset < 0 else f"amp_p{offset}"
            neighbor_idx = k0 + offset
            if 0 <= neighbor_idx < len(freqs):
                row[col_name] = float(fft_amplitudes[chan_idx, neighbor_idx])
            else:
                row[col_name] = np.nan
                out_of_bounds.append(offset)
        if out_of_bounds:
            row["warning"] = (
                "neighbor bins out of range: "
                + ",".join(str(offset) for offset in out_of_bounds)
            )
        rows.append(row)
    return rows


def write_results_workbook(
    full_excel_path: str,
    dataframes_to_save: Dict[str, pd.DataFrame],
    fft_neighbors_df: Optional[pd.DataFrame] = None,
) -> None:
    """Write results workbook with consistent formatting and optional debug sheet."""
    with pd.ExcelWriter(full_excel_path, engine="xlsxwriter") as writer:
        workbook = writer.book
        center_fmt = workbook.add_format({"align": "center", "valign": "vcenter"})

        for sheet_name, df_to_write in dataframes_to_save.items():
            df_to_write.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)
            for col_idx, header_name in enumerate(df_to_write.columns):
                max_len = max(
                    len(str(header_name)),
                    df_to_write[header_name].astype(str).map(len).max()
                    if not df_to_write[header_name].empty
                    else 0,
                )
                worksheet.set_column(col_idx, col_idx, max_len + 4, center_fmt)

        if fft_neighbors_df is not None and not fft_neighbors_df.empty:
            sheet_name = "FFT and neighbors"
            fft_neighbors_df.to_excel(writer, sheet_name=sheet_name, index=False)
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes(1, 0)
            for col_idx, header_name in enumerate(fft_neighbors_df.columns):
                max_len = max(
                    len(str(header_name)),
                    fft_neighbors_df[header_name].astype(str).map(len).max()
                    if not fft_neighbors_df[header_name].empty
                    else 0,
                )
                worksheet.set_column(col_idx, col_idx, max_len + 4, center_fmt)

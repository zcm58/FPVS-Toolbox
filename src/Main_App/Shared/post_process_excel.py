import logging
from time import perf_counter
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)
NEIGHBOR_OFFSETS = [*range(-11, 0), *range(1, 12)]


def _elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _log_excel_timing(
    stage: str,
    started_at: float,
    *,
    path: str,
    sheet_name: str | None = None,
    rows: int | None = None,
    cols: int | None = None,
    timing_sink: list[dict[str, object]] | None = None,
) -> None:
    elapsed_ms = _elapsed_ms(started_at)
    record = {
        "source": "excel",
        "stage": stage,
        "elapsed_ms": elapsed_ms,
        "path": path,
        "sheet": sheet_name,
        "rows": rows,
        "cols": cols,
    }
    if timing_sink is not None:
        timing_sink.append(record)
    logger.info(
        "[EXCEL TIMING] stage=%s elapsed_ms=%d path=%r sheet=%r rows=%s cols=%s",
        stage,
        elapsed_ms,
        path,
        sheet_name,
        rows,
        cols,
    )


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
    crop_mode: str = "fixed_epoch_fallback",
    n55: Optional[int] = None,
    first55_samp: Optional[int] = None,
    last55_samp: Optional[int] = None,
    n_step: Optional[int] = None,
    fallback_reason: str = "",
) -> List[Dict[str, Any]]:
    """Build per-channel FFT neighbor rows (±11 bins, excluding center bin)."""
    rows: List[Dict[str, Any]] = []
    if len(freqs) == 0:
        return rows

    k0 = int(round(target_freq * n_samples / fs))
    if not (0 <= k0 < len(freqs)):
        k0 = int(np.argmin(np.abs(freqs - target_freq)))
    f_bin_hz = float(freqs[k0]) if 0 <= k0 < len(freqs) else np.nan
    n_mod_step = int(n_samples % n_step) if n_step else np.nan

    if crop_mode == "55_onbin" and n_step and n_mod_step != 0:
        raise ValueError(
            f"Invalid on-bin metadata for FFT neighbors row: N={n_samples}, N_step={n_step}, N_mod_step={n_mod_step}"
        )

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
            "crop_mode": crop_mode,
            "n55": int(n55) if n55 is not None else np.nan,
            "first55_samp": int(first55_samp) if first55_samp is not None else np.nan,
            "last55_samp": int(last55_samp) if last55_samp is not None else np.nan,
            "N_step": int(n_step) if n_step is not None else np.nan,
            "N_mod_step": n_mod_step,
            "fallback_reason": fallback_reason if crop_mode == "fixed_epoch_fallback" else "",
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
    timing_sink: list[dict[str, object]] | None = None,
) -> None:
    """Write results workbook with consistent formatting and optional debug sheet."""
    workbook_started = perf_counter()
    logger.info(
        "[EXCEL STAGE] workbook_write_start path=%r sheets=%d has_fft_neighbors=%s",
        full_excel_path,
        len(dataframes_to_save),
        bool(fft_neighbors_df is not None and not fft_neighbors_df.empty),
    )
    try:
        with pd.ExcelWriter(full_excel_path, engine="xlsxwriter") as writer:
            workbook = writer.book
            center_fmt = workbook.add_format({"align": "center", "valign": "vcenter"})

            for sheet_name, df_to_write in dataframes_to_save.items():
                sheet_started = perf_counter()
                write_started = perf_counter()
                df_to_write.to_excel(writer, sheet_name=sheet_name, index=False)
                _log_excel_timing(
                    "sheet_to_excel",
                    write_started,
                    path=full_excel_path,
                    sheet_name=sheet_name,
                    rows=len(df_to_write),
                    cols=len(df_to_write.columns),
                    timing_sink=timing_sink,
                )
                worksheet = writer.sheets[sheet_name]
                worksheet.freeze_panes(1, 0)
                widths_started = perf_counter()
                for col_idx, header_name in enumerate(df_to_write.columns):
                    max_len = max(
                        len(str(header_name)),
                        df_to_write[header_name].astype(str).map(len).max()
                        if not df_to_write[header_name].empty
                        else 0,
                    )
                    worksheet.set_column(col_idx, col_idx, max_len + 4, center_fmt)
                _log_excel_timing(
                    "sheet_column_widths",
                    widths_started,
                    path=full_excel_path,
                    sheet_name=sheet_name,
                    rows=len(df_to_write),
                    cols=len(df_to_write.columns),
                    timing_sink=timing_sink,
                )
                _log_excel_timing(
                    "sheet_total",
                    sheet_started,
                    path=full_excel_path,
                    sheet_name=sheet_name,
                    rows=len(df_to_write),
                    cols=len(df_to_write.columns),
                    timing_sink=timing_sink,
                )

            if fft_neighbors_df is not None and not fft_neighbors_df.empty:
                sheet_name = "FFT and neighbors"
                sheet_started = perf_counter()
                write_started = perf_counter()
                fft_neighbors_df.to_excel(writer, sheet_name=sheet_name, index=False)
                _log_excel_timing(
                    "sheet_to_excel",
                    write_started,
                    path=full_excel_path,
                    sheet_name=sheet_name,
                    rows=len(fft_neighbors_df),
                    cols=len(fft_neighbors_df.columns),
                    timing_sink=timing_sink,
                )
                worksheet = writer.sheets[sheet_name]
                worksheet.freeze_panes(1, 0)
                widths_started = perf_counter()
                for col_idx, header_name in enumerate(fft_neighbors_df.columns):
                    max_len = max(
                        len(str(header_name)),
                        fft_neighbors_df[header_name].astype(str).map(len).max()
                        if not fft_neighbors_df[header_name].empty
                        else 0,
                    )
                    worksheet.set_column(col_idx, col_idx, max_len + 4, center_fmt)
                _log_excel_timing(
                    "sheet_column_widths",
                    widths_started,
                    path=full_excel_path,
                    sheet_name=sheet_name,
                    rows=len(fft_neighbors_df),
                    cols=len(fft_neighbors_df.columns),
                    timing_sink=timing_sink,
                )
                _log_excel_timing(
                    "sheet_total",
                    sheet_started,
                    path=full_excel_path,
                    sheet_name=sheet_name,
                    rows=len(fft_neighbors_df),
                    cols=len(fft_neighbors_df.columns),
                    timing_sink=timing_sink,
                )
    finally:
        _log_excel_timing(
            "workbook_write_total",
            workbook_started,
            path=full_excel_path,
            timing_sink=timing_sink,
        )

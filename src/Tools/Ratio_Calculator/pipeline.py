from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from .compute import (
    compute_ratio_rows_from_sums,
    group_summary_ratios,
    group_summary_sums,
    summarize_participant_file_sums,
)
from .constants import RatioCalculatorSettings, ROI_DEFS_DEFAULT
from .excel_utils import apply_excel_qol
from .plots import PlotPanel, compute_stable_ylim, make_raincloud_figure, make_raincloud_figure_roi_x
from .utils import expected_oddball_harmonics, fmt_hz_list, is_excel_temp_lock_file, parse_participant_id


class RatioCalculatorResult:
    def __init__(self, output_dir: Path, excel_path: Path, log_lines: list[str]) -> None:
        self.output_dir = output_dir
        self.excel_path = excel_path
        self.log_lines = log_lines


def _sorted_pids(pids: Iterable[str]) -> list[str]:
    return sorted(list(pids), key=lambda s: int(s[1:]) if s[1:].isdigit() else 999999)


def run_ratio_calculator(
    input_dir_a: str,
    condition_label_a: str,
    input_dir_b: str,
    condition_label_b: str,
    output_dir: str,
    run_label: str,
    manual_exclude: Iterable[str],
    settings: RatioCalculatorSettings | None = None,
    roi_defs: dict[str, list[str]] | None = None,
    log: Callable[[str], None] | None = None,
) -> RatioCalculatorResult:
    settings = settings or RatioCalculatorSettings()
    roi_defs = roi_defs or ROI_DEFS_DEFAULT
    manual_list = list(manual_exclude)

    log_lines: list[str] = []

    def _log(message: str) -> None:
        if log:
            log(message)
        log_lines.append(message)

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    expected_hz = expected_oddball_harmonics(
        oddball_base_hz=settings.oddball_base_hz,
        up_to_hz=settings.sum_up_to_hz,
        excluded_hz=settings.excluded_freqs_hz,
    )

    _log("=" * 110)
    _log(f"RUN_LABEL: {run_label}")
    _log(f"Timestamp: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    _log(f"Output Dir:  {str(out_dir)}")
    _log("-" * 110)
    _log("PARAMETERS")
    _log(f"  CONDITION A: {condition_label_a}")
    _log(f"  CONDITION B: {condition_label_b}")
    _log(f"  ODDBALL_BASE_HZ: {settings.oddball_base_hz}")
    _log(f"  SUM_UP_TO_HZ: {settings.sum_up_to_hz}")
    _log(f"  EXCLUDED_FREQS_HZ: {sorted(list(settings.excluded_freqs_hz))}")
    _log(
        "  INCLUDED_ODDBALL_HARMONICS_HZ "
        f"(n={len(expected_hz)}): [{fmt_hz_list(expected_hz)}]"
    )
    _log(f"  ROIs: {list(roi_defs.keys())}")
    _log(f"  MANUAL_EXCLUDE: {manual_list}")
    _log("=" * 110)

    def index_folder(path: str, label: str) -> tuple[list[Path], dict[str, Path]]:
        all_files = sorted(Path(path).expanduser().glob("*.xlsx"))
        xlsx_files = [p for p in all_files if not is_excel_temp_lock_file(p.name)]
        _log(f"[{label}] Found {len(xlsx_files)} .xlsx files.")
        pid_to_path: dict[str, Path] = {}
        for file_path in xlsx_files:
            pid, _ = parse_participant_id(file_path.name)
            pid_to_path[pid] = file_path
        return xlsx_files, pid_to_path

    _, pid_map_a = index_folder(input_dir_a, condition_label_a)
    _, pid_map_b = index_folder(input_dir_b, condition_label_b)

    pids_a = _sorted_pids(pid_map_a.keys())
    pids_b = _sorted_pids(pid_map_b.keys())
    pids_paired = _sorted_pids(set(pids_a).intersection(set(pids_b)))

    _log("-" * 110)
    _log(f"Participants in {condition_label_a}: {len(pids_a)}")
    _log(f"Participants in {condition_label_b}: {len(pids_b)}")
    _log(f"Participants paired (present in BOTH folders): {len(pids_paired)}")
    _log("-" * 110)

    if not pids_paired:
        raise RuntimeError("No paired participants found between the two folders.")

    manual_set = set(manual_list)
    manual_in_paired = _sorted_pids([p for p in pids_paired if p in manual_set])
    manual_not_found = _sorted_pids([p for p in manual_list if p not in set(pids_paired)])

    _log("MANUAL EXCLUSION REPORT")
    _log(f"  Manual exclude list: {manual_list}")
    _log(f"  Found among paired:  {manual_in_paired}")
    _log(f"  Not found in paired: {manual_not_found}")
    _log("-" * 110)

    part_rows: list[dict[str, object]] = []
    for pid in pids_paired:
        part_rows.extend(
            summarize_participant_file_sums(pid_map_a[pid], condition_label_a, expected_hz, roi_defs)
        )
        part_rows.extend(
            summarize_participant_file_sums(pid_map_b[pid], condition_label_b, expected_hz, roi_defs)
        )

    df_part_all = pd.DataFrame(part_rows)
    df_part_all["is_manual_excluded"] = df_part_all["participant_id"].isin(manual_set)

    df_part_used = df_part_all[~df_part_all["is_manual_excluded"]].copy()

    _log(
        "Paired participants total: "
        f"{len(pids_paired)} | used after MANUAL exclusions: {df_part_used['participant_id'].nunique()}"
    )
    _log("-" * 110)

    df_ratio_all = compute_ratio_rows_from_sums(df_part_all, condition_label_a, condition_label_b)
    df_ratio_all["is_manual_excluded"] = df_ratio_all["participant_id"].isin(manual_set)

    df_ratio_used = df_ratio_all[~df_ratio_all["is_manual_excluded"]].copy()

    df_group_sums_used = group_summary_sums(df_part_used)
    df_group_ratios_used = group_summary_ratios(df_ratio_used)

    _log("GROUP SUMMARY (USED): SUMS by (condition x ROI) [mean / median / SD / SEM]")
    if df_group_sums_used.empty:
        _log("  (empty)")
    else:
        _log(df_group_sums_used.to_string(index=False))
    _log("-" * 110)

    _log("GROUP SUMMARY (USED): RATIOS by ROI [mean / median / SD / SEM]")
    if df_group_ratios_used.empty:
        _log("  (empty)")
    else:
        _log(df_group_ratios_used.to_string(index=False))
    _log("-" * 110)

    y_raw_z = settings.ylim_raw_sum_z
    y_raw_snr = settings.ylim_raw_sum_snr
    y_raw_bca = settings.ylim_raw_sum_bca
    y_ratio_z = settings.ylim_ratio_z
    y_ratio_snr = settings.ylim_ratio_snr
    y_ratio_bca = settings.ylim_ratio_bca

    if settings.use_stable_ylims:
        if y_raw_z is None:
            y_raw_z = compute_stable_ylim(pd.to_numeric(df_part_used["sum_Z"], errors="coerce").to_numpy(dtype=float))
        if y_raw_snr is None:
            y_raw_snr = compute_stable_ylim(
                pd.to_numeric(df_part_used["sum_SNR"], errors="coerce").to_numpy(dtype=float)
            )
        if y_raw_bca is None:
            y_raw_bca = compute_stable_ylim(
                pd.to_numeric(df_part_used["sum_BCA_uV"], errors="coerce").to_numpy(dtype=float)
            )

        if y_ratio_z is None:
            y_ratio_z = compute_stable_ylim(
                pd.to_numeric(df_ratio_used["ratio_Z"], errors="coerce").to_numpy(dtype=float),
                force_include=1.0,
            )
        if y_ratio_snr is None:
            y_ratio_snr = compute_stable_ylim(
                pd.to_numeric(df_ratio_used["ratio_SNR"], errors="coerce").to_numpy(dtype=float),
                force_include=1.0,
            )
        if y_ratio_bca is None:
            y_ratio_bca = compute_stable_ylim(
                pd.to_numeric(df_ratio_used["ratio_BCA"], errors="coerce").to_numpy(dtype=float),
                force_include=1.0,
            )

    df_group_sums_plot = df_group_sums_used.rename(columns={"mean_sum_Z": "mean", "sem_sum_Z": "sem"}).copy()
    make_raincloud_figure(
        df_part_all.rename(columns={"sum_Z": "val"}).copy(),
        df_group_sums_plot,
        PlotPanel(val_col="val", mean_col="mean", sem_col="sem", ylabel="SUM(Z) across oddball harmonics", ylim=y_raw_z),
        out_dir / f"Plot_{run_label}_RAW_SUM_Z",
        roi_defs,
        settings.palette_choice,
        run_label,
        settings.png_dpi,
        condition_label_a,
        condition_label_b,
        log_func=_log,
    )

    df_group_sums_plot = df_group_sums_used.rename(columns={"mean_sum_SNR": "mean", "sem_sum_SNR": "sem"}).copy()
    make_raincloud_figure(
        df_part_all.rename(columns={"sum_SNR": "val"}).copy(),
        df_group_sums_plot,
        PlotPanel(
            val_col="val", mean_col="mean", sem_col="sem", ylabel="SUM(SNR) across oddball harmonics", ylim=y_raw_snr
        ),
        out_dir / f"Plot_{run_label}_RAW_SUM_SNR",
        roi_defs,
        settings.palette_choice,
        run_label,
        settings.png_dpi,
        condition_label_a,
        condition_label_b,
        log_func=_log,
    )

    df_group_sums_plot = df_group_sums_used.rename(columns={"mean_sum_BCA_uV": "mean", "sem_sum_BCA_uV": "sem"}).copy()
    make_raincloud_figure(
        df_part_all.rename(columns={"sum_BCA_uV": "val"}).copy(),
        df_group_sums_plot,
        PlotPanel(
            val_col="val",
            mean_col="mean",
            sem_col="sem",
            ylabel="SUM(BCA) (µV) across oddball harmonics",
            ylim=y_raw_bca,
        ),
        out_dir / f"Plot_{run_label}_RAW_SUM_BCA",
        roi_defs,
        settings.palette_choice,
        run_label,
        settings.png_dpi,
        condition_label_a,
        condition_label_b,
        log_func=_log,
    )

    ratio_label = f"{condition_label_a} / {condition_label_b}"

    df_ratio_plot = df_ratio_all.copy()
    df_group_ratio_plot = df_group_ratios_used.copy()

    make_raincloud_figure_roi_x(
        df_ratio_plot.rename(columns={"ratio_Z": "val"}).copy(),
        df_group_ratio_plot.rename(columns={"mean_ratio_Z": "mean", "sem_ratio_Z": "sem"}).copy(),
        PlotPanel(
            val_col="val",
            mean_col="mean",
            sem_col="sem",
            ylabel="Ratio",
            hline_y=1.0,
            ylim=y_ratio_z,
            title=f"High-Level to Low-Level Ratio using Summed Z ({ratio_label})",
        ),
        out_dir / f"Plot_{run_label}_RATIO_Z",
        roi_defs,
        settings.palette_choice,
        run_label,
        settings.png_dpi,
        xlabel="ROI",
        log_func=_log,
    )

    make_raincloud_figure_roi_x(
        df_ratio_plot.rename(columns={"ratio_SNR": "val"}).copy(),
        df_group_ratio_plot.rename(columns={"mean_ratio_SNR": "mean", "sem_ratio_SNR": "sem"}).copy(),
        PlotPanel(
            val_col="val",
            mean_col="mean",
            sem_col="sem",
            ylabel="Ratio",
            hline_y=1.0,
            ylim=y_ratio_snr,
            title=f"High-Level to Low-Level Ratio using Summed SNR ({ratio_label})",
        ),
        out_dir / f"Plot_{run_label}_RATIO_SNR",
        roi_defs,
        settings.palette_choice,
        run_label,
        settings.png_dpi,
        xlabel="ROI",
        log_func=_log,
    )

    make_raincloud_figure_roi_x(
        df_ratio_plot.rename(columns={"ratio_BCA": "val"}).copy(),
        df_group_ratio_plot.rename(columns={"mean_ratio_BCA": "mean", "sem_ratio_BCA": "sem"}).copy(),
        PlotPanel(
            val_col="val",
            mean_col="mean",
            sem_col="sem",
            ylabel="Ratio",
            hline_y=1.0,
            ylim=y_ratio_bca,
            title=f"High-Level to Low-Level Ratio using Summed BCA ({ratio_label})",
        ),
        out_dir / f"Plot_{run_label}_RATIO_BCA",
        roi_defs,
        settings.palette_choice,
        run_label,
        settings.png_dpi,
        xlabel="ROI",
        log_func=_log,
    )

    out_xlsx = out_dir / f"Metrics_{run_label}.xlsx"

    params_df = pd.DataFrame(
        [
            {"key": "RUN_LABEL", "value": run_label},
            {"key": "CONDITION_LABEL_A", "value": condition_label_a},
            {"key": "CONDITION_LABEL_B", "value": condition_label_b},
            {"key": "ODDBALL_BASE_HZ", "value": settings.oddball_base_hz},
            {"key": "SUM_UP_TO_HZ", "value": settings.sum_up_to_hz},
            {"key": "EXCLUDED_FREQS_HZ", "value": str(sorted(list(settings.excluded_freqs_hz)))},
            {"key": "INCLUDED_ODDBALL_HARMONICS_HZ", "value": fmt_hz_list(expected_hz)},
            {"key": "N_INCLUDED_HARMONICS", "value": len(expected_hz)},
            {"key": "MANUAL_EXCLUDE", "value": str(manual_list)},
            {"key": "MANUAL_FOUND_IN_PAIRED", "value": str(manual_in_paired)},
            {"key": "MANUAL_NOT_FOUND_IN_PAIRED", "value": str(manual_not_found)},
            {"key": "USE_STABLE_YLIMS", "value": str(settings.use_stable_ylims)},
            {"key": "YLIM_RAW_SUM_Z", "value": str(y_raw_z)},
            {"key": "YLIM_RAW_SUM_SNR", "value": str(y_raw_snr)},
            {"key": "YLIM_RAW_SUM_BCA", "value": str(y_raw_bca)},
            {"key": "YLIM_RATIO_Z", "value": str(y_ratio_z)},
            {"key": "YLIM_RATIO_SNR", "value": str(y_ratio_snr)},
            {"key": "YLIM_RATIO_BCA", "value": str(y_ratio_bca)},
        ]
    )

    manual_excl_df = pd.DataFrame(
        [{"participant_id": pid, "found_in_paired": (pid in set(pids_paired))} for pid in manual_list]
    )

    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        params_df.to_excel(writer, sheet_name="Parameters", index=False)
        manual_excl_df.to_excel(writer, sheet_name="Manual_Exclusions", index=False)

        df_part_all.to_excel(writer, sheet_name="Participant_Sums_ALL", index=False)
        df_part_used.to_excel(writer, sheet_name="Participant_Sums_USED", index=False)

        df_ratio_all.to_excel(writer, sheet_name="Ratios_ALL", index=False)
        df_ratio_used.to_excel(writer, sheet_name="Ratios_USED", index=False)

        df_group_sums_used.to_excel(writer, sheet_name="Group_Sums_USED", index=False)
        df_group_ratios_used.to_excel(writer, sheet_name="Group_Ratios_USED", index=False)

        apply_excel_qol(writer)

    out_log = out_dir / f"Log_{run_label}.txt"
    out_log.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    _log("=" * 110)
    _log(f"Success! Outputs saved to: {out_dir}")
    _log(f"Excel: {out_xlsx.name}")
    _log(f"Log:   {out_log.name}")
    _log("=" * 110)

    return RatioCalculatorResult(out_dir, out_xlsx, log_lines)

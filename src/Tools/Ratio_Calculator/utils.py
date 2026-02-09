from __future__ import annotations

import math
import re
from typing import Iterable

import numpy as np

from .constants import EPS

PID_RE = re.compile(r"(P)(\d+)", re.IGNORECASE)


def parse_participant_id(filename: str) -> tuple[str, int]:
    match = PID_RE.search(filename)
    if not match:
        raise ValueError(f"Could not parse participant id from: {filename}")
    return f"P{match.group(2)}", int(match.group(2))


def harmonic_col_to_hz(col: str) -> float:
    value = str(col).strip()
    value = value.replace("HZ", "Hz").replace("hz", "Hz")
    value = value.replace("_Hz", "").replace("Hz", "")
    return float(value)


def hz_key(hz: float) -> float:
    return float(round(float(hz), 6))


def fmt_hz_list(hz_list: Iterable[float]) -> str:
    return ", ".join([f"{float(hz):g}" for hz in hz_list])


def safe_sum(values: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(values)))
    return float(np.nansum(values)) if n > 0 else float("nan")


def safe_mean(values: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(values)))
    return float(np.nanmean(values)) if n > 0 else float("nan")


def safe_median(values: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(values)))
    return float(np.nanmedian(values)) if n > 0 else float("nan")


def safe_sd(values: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(values)))
    return float(np.nanstd(values, ddof=1)) if n >= 2 else float("nan")


def safe_sem(values: np.ndarray) -> float:
    n = int(np.sum(~np.isnan(values)))
    return float(np.nanstd(values, ddof=1) / math.sqrt(n)) if n >= 2 else float("nan")


def validate_manual_exclude(pids: Iterable[str]) -> None:
    for pid in pids:
        if not isinstance(pid, str) or not re.fullmatch(r"P\d+", pid.strip()):
            raise ValueError(
                f"MANUAL_EXCLUDE contains invalid PID '{pid}'. "
                f"Require format like 'P17'."
            )


def expected_oddball_harmonics(
    oddball_base_hz: float,
    up_to_hz: float,
    excluded_hz: Iterable[float],
) -> list[float]:
    excluded = {hz_key(hz) for hz in excluded_hz}
    out: list[float] = []
    h = 1
    while True:
        hz = hz_key(oddball_base_hz * h)
        if hz > up_to_hz + EPS:
            break
        if hz not in excluded:
            out.append(hz)
        h += 1
    return out


def build_hz_to_col_map(harmonic_cols: Iterable[str]) -> dict[float, str]:
    out: dict[float, str] = {}
    for col in harmonic_cols:
        hz = hz_key(harmonic_col_to_hz(col))
        out[hz] = col
    return out


def is_excel_temp_lock_file(path_name: str) -> bool:
    return path_name.startswith("~$")

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import gcd
from typing import Dict, Iterable, Optional, Tuple

import numpy as np


@dataclass
class CropResult:
    crop_start_sample: int
    n_samples: int
    n55_raw: int
    n55_dedup: int
    cycles: int
    block_start_sample: int
    block_end_sample: int
    first55_sample: Optional[int] = None
    last55_sample: Optional[int] = None
    available_samples: int = 0
    dedup_dropped: int = 0
    missing_gap_count: int = 0
    fallback: bool = False
    fallback_reason: Optional[str] = None
    warnings: list[str] = field(default_factory=list)


ODDBALL_FREQ = Fraction(6, 5)


def compute_onbin_step(fs: float, f_oddball: Fraction = ODDBALL_FREQ) -> Tuple[Optional[int], Optional[int], Optional[str]]:
    fs_i = int(round(fs))
    if abs(fs - fs_i) >= 1e-6:
        return None, None, f"non_integer_fs:{fs}"
    den_fs = f_oddball.denominator * fs_i
    n_step = den_fs // gcd(f_oddball.numerator, den_fs)
    return fs_i, n_step, None


def compute_onbin_N(available_samples: int, N_step: int) -> int:
    if available_samples <= 0 or N_step <= 0:
        return 0
    return (available_samples // N_step) * N_step


def compute_fft_crop_from_events(
    events: np.ndarray,
    fs: float,
    onset_ids: Iterable[int],
    oddball_id: int = 55,
    stream_end_sample: Optional[int] = None,
) -> tuple[Dict[Tuple[int, int], CropResult], Optional[int], list[str]]:
    onset_set = {int(v) for v in onset_ids}
    results: Dict[Tuple[int, int], CropResult] = {}
    run_warnings: list[str] = []

    if events.size == 0:
        run_warnings.append("empty_events")
        return results, None, run_warnings

    _, n_step, step_err = compute_onbin_step(fs=fs)
    if step_err:
        run_warnings.append(step_err)

    expected_interval_samples = int(round(fs / 1.2))
    onset_events = [row for row in events if int(row[2]) in onset_set]
    if not onset_events:
        run_warnings.append("no_onsets")
        return results, n_step, run_warnings

    rep_counter: Dict[int, int] = {}
    for idx, onset_event in enumerate(onset_events):
        onset_sample = int(onset_event[0])
        cond_id = int(onset_event[2])
        rep_counter[cond_id] = rep_counter.get(cond_id, 0) + 1
        rep_index = rep_counter[cond_id] - 1
        next_block_start = int(onset_events[idx + 1][0]) if idx + 1 < len(onset_events) else int(stream_end_sample or events[-1][0] + 1)

        block_rows = [row for row in events if onset_sample <= int(row[0]) < next_block_start and int(row[2]) == oddball_id]
        raw_55 = [int(row[0]) for row in block_rows]
        dedup_55: list[int] = []
        dropped = 0
        missing_gaps = 0
        for sample in raw_55:
            if not dedup_55:
                dedup_55.append(sample)
                continue
            delta = sample - dedup_55[-1]
            if delta < 0.5 * expected_interval_samples:
                dropped += 1
                continue
            if delta > 1.5 * expected_interval_samples:
                missing_gaps += 1
            dedup_55.append(sample)

        fallback_reason: Optional[str] = None
        fallback = False
        first55 = dedup_55[0] if dedup_55 else None
        last55 = dedup_55[-1] if dedup_55 else None
        available = (last55 - first55) if first55 is not None and last55 is not None else 0

        if n_step is None:
            fallback = True
            fallback_reason = step_err
            n_samples = 0
            crop_start = onset_sample
        elif len(dedup_55) < 2:
            fallback = True
            fallback_reason = "insufficient_55"
            n_samples = 0
            crop_start = onset_sample
        else:
            n_samples = compute_onbin_N(available_samples=available, N_step=n_step)
            crop_start = first55
            if n_samples <= 0:
                fallback = True
                fallback_reason = "nonpositive_N"

        warnings: list[str] = []
        if missing_gaps:
            warnings.append(f"missing_55_gaps:{missing_gaps}")
        if dropped:
            warnings.append(f"dedup_dropped:{dropped}")

        results[(cond_id, rep_index)] = CropResult(
            crop_start_sample=crop_start,
            n_samples=n_samples,
            n55_raw=len(raw_55),
            n55_dedup=len(dedup_55),
            cycles=max(0, len(dedup_55) - 1),
            block_start_sample=onset_sample,
            block_end_sample=next_block_start,
            first55_sample=first55,
            last55_sample=last55,
            available_samples=available,
            dedup_dropped=dropped,
            missing_gap_count=missing_gaps,
            fallback=fallback,
            fallback_reason=fallback_reason,
            warnings=warnings,
        )
    return results, n_step, run_warnings

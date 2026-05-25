from __future__ import annotations

from collections.abc import Mapping
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
    oddball_id: Optional[int] = None


ODDBALL_FREQ = Fraction(6, 5)
CONDITION_SPECIFIC_ODDBALL_OFFSET = 50


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


def condition_specific_oddball_id(
    condition_id: int,
    *,
    offset: int = CONDITION_SPECIFIC_ODDBALL_OFFSET,
) -> int:
    return int(condition_id) + int(offset)


def resolve_oddball_ids_by_condition(
    events: np.ndarray,
    onset_ids: Iterable[int],
    *,
    default_oddball_id: int = 55,
    condition_specific_offset: int = CONDITION_SPECIFIC_ODDBALL_OFFSET,
    stream_end_sample: Optional[int] = None,
) -> dict[int, int]:
    """Resolve the oddball marker code to use for each condition onset code.

    Standard projects use a global oddball marker code of 55. Some older or
    task-specific projects encode oddballs as 50 + condition code, such as
    51, 52, 53, 54, and 55 for condition onset codes 1-5. This resolver makes
    that choice explicit per condition from the observed event stream.
    """
    onset_set = {int(v) for v in onset_ids}
    resolved = {condition_id: int(default_oddball_id) for condition_id in onset_set}
    if events.size == 0 or not onset_set:
        return resolved

    onset_events = [row for row in events if int(row[2]) in onset_set]
    for idx, onset_event in enumerate(onset_events):
        cond_id = int(onset_event[2])
        condition_oddball_id = condition_specific_oddball_id(
            cond_id,
            offset=condition_specific_offset,
        )
        if condition_oddball_id == int(default_oddball_id):
            resolved[cond_id] = int(default_oddball_id)
            continue

        onset_sample = int(onset_event[0])
        next_block_start = (
            int(onset_events[idx + 1][0])
            if idx + 1 < len(onset_events)
            else int(stream_end_sample or events[-1][0] + 1)
        )
        condition_specific_count = sum(
            1
            for row in events
            if onset_sample < int(row[0]) < next_block_start
            and int(row[2]) == condition_oddball_id
        )
        if condition_specific_count >= 2:
            resolved[cond_id] = condition_oddball_id
    return resolved


def _resolve_oddball_id_for_condition(
    oddball_id: int | Mapping[int, int],
    condition_id: int,
) -> int:
    if isinstance(oddball_id, Mapping):
        return int(oddball_id.get(int(condition_id), 55))
    return int(oddball_id)


def compute_fft_crop_from_events(
    events: np.ndarray,
    fs: float,
    onset_ids: Iterable[int],
    oddball_id: int | Mapping[int, int] = 55,
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

        block_oddball_id = _resolve_oddball_id_for_condition(oddball_id, cond_id)
        block_rows = [
            row
            for row in events
            if onset_sample < int(row[0]) < next_block_start
            and int(row[2]) == block_oddball_id
        ]
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
            fallback_reason = f"insufficient_{block_oddball_id}"
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
            oddball_id=block_oddball_id,
        )
    return results, n_step, run_warnings

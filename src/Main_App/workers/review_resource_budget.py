"""GUI-neutral preparation memory bounds and live admission probes.

These are conservative scheduling bounds for the pinned ordinary BDF route,
not a guarantee against arbitrary concurrent allocations by external programs.
No waveform arrays, global source caches or scientific decisions are retained.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
import logging
import math
import os
from pathlib import Path

import psutil

GIB = 1024**3
WORKER_FLOOR_BYTES = GIB
_MIB = 1024**2
logger = logging.getLogger(__name__)


class ReviewMemoryProbeError(RuntimeError):
    """Admission cannot proceed when required live memory evidence is absent."""


@dataclass(frozen=True)
class ReviewGeometry:
    loaded_channels: int
    retained_channels: int
    scored_channels: int
    source_n_times: int
    source_rate_hz: float
    target_rate_hz: float
    packed_record_bytes: int
    source_record_samples: int


@dataclass(frozen=True)
class ReviewMemoryEstimate:
    prefix_bytes: int
    healthy_qc_bytes: int
    fullrate_qc_bytes: int
    healthy_bytes: int
    emergency_extra_bytes: int
    components: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class ReviewMemorySnapshot:
    total_bytes: int
    physical_available_bytes: int
    commit_available_bytes: int | None = None
    commit_required: bool = False


@dataclass(frozen=True)
class OwnedMemory:
    uss_bytes: int | None = None
    private_commit_bytes: int | None = None


def _positive_int(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("A positive integer geometry dimension is required.")
    return value


def _power_two_ceiling(value: int) -> int:
    return 1 << (max(1, value) - 1).bit_length()


def estimate_review_memory(
    geometry: ReviewGeometry, *, filter_enabled: bool = True,
    notch_enabled: bool = False, raw_qc_enabled: bool = True,
    raw_union_samples: int | None = None,
) -> ReviewMemoryEstimate:
    """Bound load/reference/FIR/resample and both possible scoring rates.

    Initial scoring conservatively uses the entire target recording. AUTO raw
    QC additionally reserves its source-rate union and normalization scratch.
    Compiled-library, metadata and allocator overhead is reserved separately
    by the scheduler's worker floor rather than counted once per live array.
    """
    g = geometry
    for value in (g.loaded_channels, g.retained_channels, g.scored_channels,
                  g.source_n_times, g.packed_record_bytes, g.source_record_samples):
        _positive_int(value)
    if not g.loaded_channels >= g.retained_channels >= g.scored_channels:
        raise ValueError("Scored and retained channels must fit loaded geometry.")
    source_rate = float(g.source_rate_hz)
    target_rate = source_rate if g.target_rate_hz is None or g.target_rate_hz is False else float(g.target_rate_hz)
    if target_rate == 0 or target_rate >= source_rate:
        target_rate = source_rate
    if not all(math.isfinite(rate) and rate > 0 for rate in (source_rate, target_rate)):
        raise ValueError("Finite positive source and target rates are required.")
    n0 = g.source_n_times
    n2 = max(1, math.ceil(n0 * target_rate / source_rate))
    r0, r1, r2 = (8 * channels * samples for channels, samples in
                  ((g.loaded_channels, n0), (g.retained_channels, n0), (g.retained_channels, n2)))
    a2, a0 = 8 * g.scored_channels * n2, 8 * g.scored_channels * n0
    # The native reader's nominal 10-MiB batch is rounded up to whole records.
    packed_chunk = math.ceil(10 * _MIB / g.packed_record_bytes) * g.packed_record_bytes
    decoder = math.ceil(packed_chunk * 28 / 3) + 8 * g.loaded_channels * g.source_record_samples * math.ceil(
        10 * _MIB / g.packed_record_bytes)
    components = {"load": 2 * r0 + decoder,
                  "reference": 2 * r0 + 8 * n0,
                  "drop": r0 + r1}
    if filter_enabled or notch_enabled:
        h = 8449
        if source_rate > target_rate:
            h = max(h, int(round((h - 1) * source_rate / target_rate)) + 1)
            h += not h % 2
        # Includes zero-double coefficients and an upper FFT allocation bound;
        # this is deliberately not the optimizer's smaller chosen FFT size.
        e, hd = min(h, n0) - 1, 2 * h - 1
        f = _power_two_ceiling(max(2 * hd - 1, n0 + 2 * e))
        components["fir"] = r1 + 8 * (2 * (n0 + 2 * e) + max(5 * f, n0 + 3 * f)) + 4 * _MIB
    if source_rate != target_rate:
        p = _power_two_ceiling(n0 + 2 * min(n0 // 8, 100))
        q = max(1, math.ceil(p * target_rate / source_rate))
        components["resample"] = r1 + 2 * r2 + 32 * p + 8 * q
    if raw_qc_enabled:
        m0 = n0 if raw_union_samples is None else _positive_int(raw_union_samples)
        if m0 > n0:
            raise ValueError("Source union cannot exceed the recording.")
        a = 8 * g.scored_channels * m0
        # Span chunks plus concatenation, spatial normalization working arrays,
        # finite-mask and bounded donor/row scratch all remain possible here.
        components["raw_qc"] = r0 + 4 * a + math.ceil(a / 4) + 64 * _MIB + 64 * 8 * m0
    prefix = max(components.values())
    healthy, full = r2 + 6 * a2, r1 + 6 * a0
    components["checkpoint"] = r2 + a2 + 17 * _MIB
    # A warm checkpoint retains the original loaded input while restoring and
    # concatenating target scoring data; cached evidence skips SciPy entirely.
    components["warm_checkpoint"] = r0 + r2 + 2 * a2 + 17 * _MIB
    prefix = max(prefix, components["checkpoint"], components["warm_checkpoint"])
    h_credit = max(prefix, healthy)
    return ReviewMemoryEstimate(prefix, healthy, full, h_credit,
                                max(0, full - h_credit), tuple(components.items()))


def actual_scoring_bytes(
    raw_channels: int, raw_samples: int, scored_channels: int, union_samples: int,
    evidence_cached: bool = False, original_input_live_bytes: int = 0,
) -> int:
    for value in (raw_channels, raw_samples, scored_channels, union_samples):
        _positive_int(value)
    if scored_channels > raw_channels or union_samples > raw_samples:
        raise ValueError("Actual scoring shape exceeds its Raw geometry.")
    if type(original_input_live_bytes) is not int or original_input_live_bytes < 0:
        raise ValueError("Original live input bytes must be nonnegative.")
    r, a = 8 * raw_channels * raw_samples, 8 * scored_channels * union_samples
    return original_input_live_bytes + max(r + (2 if evidence_cached else 6) * a, r + a + 17 * _MIB)


def _windows_commit_available() -> int | None:
    """Get actual CommitLimit-CommitTotal, never pagefile-free bytes."""
    import ctypes
    from ctypes import wintypes

    class PerformanceInfo(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), *[(name, ctypes.c_size_t) for name in
                    ("CommitTotal", "CommitLimit", "CommitPeak", "PhysicalTotal",
                     "PhysicalAvailable", "SystemCache", "KernelTotal", "KernelPaged",
                     "KernelNonpaged", "PageSize")],
                    ("HandleCount", wintypes.DWORD), ("ProcessCount", wintypes.DWORD),
                    ("ThreadCount", wintypes.DWORD)]
    value = PerformanceInfo()
    value.cb = ctypes.sizeof(value)
    function = ctypes.WinDLL("psapi", use_last_error=True).GetPerformanceInfo
    function.argtypes = [ctypes.POINTER(PerformanceInfo), wintypes.DWORD]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(value), value.cb):
        return None
    return max(0, int(value.CommitLimit - value.CommitTotal) * int(value.PageSize))


def probe_memory_snapshot() -> ReviewMemorySnapshot:
    memory = psutil.virtual_memory()
    commit = None
    if os.name == "nt":
        try:
            commit = _windows_commit_available()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            logger.debug("review_commit_probe_unavailable", exc_info=True)
    return ReviewMemorySnapshot(int(memory.total), max(0, int(memory.available)), commit, os.name == "nt")


def probe_owned_memory(pid: int, created: float) -> OwnedMemory:
    """Only matching-process unique resident/private committed pages earn credit."""
    try:
        process = psutil.Process(pid)
        if process.create_time() != created:
            return OwnedMemory()
        info = process.memory_full_info()
        if process.create_time() != created:
            return OwnedMemory()
        return OwnedMemory(getattr(info, "uss", None), getattr(info, "private", None))
    except (OSError, RuntimeError, ValueError, psutil.Error):
        return OwnedMemory()


def _owned(value: int | None) -> int:
    return value if type(value) is int and value >= 0 else 0


def single_review_capacity_bytes(snapshot: ReviewMemorySnapshot, credit: int) -> int:
    """Include one runtime floor and host reserve in a validated job credit."""
    if type(credit) is not int or credit < 0:
        raise ValueError("Memory credit must be a nonnegative integer.")
    return credit + WORKER_FLOOR_BYTES + max(GIB, snapshot.total_bytes // 16)


def memory_admission_fits(
    snapshot: ReviewMemorySnapshot, *, active_credits: Mapping[int, int],
    active_owned: Mapping[int, OwnedMemory], idle_owned: Sequence[OwnedMemory],
    worker_count: int, candidate_credit: int = 0, emergency_reserve: int = 0,
    worker_floor_bytes: int = WORKER_FLOOR_BYTES, host_margin_bytes: int | None = None,
) -> bool:
    """Do not reserve already-owned pages twice or confuse commit with residence."""
    if worker_count < len(active_credits) or len(idle_owned) > worker_count - len(active_credits):
        raise ValueError("Owned workers exceed the reserved pool population.")
    for value in (*active_credits.values(), candidate_credit, emergency_reserve, worker_floor_bytes):
        if type(value) is not int or value < 0:
            raise ValueError("Memory credits must be nonnegative integers.")
    margin = max(GIB, snapshot.total_bytes // 16) if host_margin_bytes is None else host_margin_bytes
    if type(margin) is not int or margin < 0:
        raise ValueError("Host reserve must be a nonnegative byte count.")
    physical = commit = candidate_credit + emergency_reserve
    for index, credit in active_credits.items():
        owner = active_owned.get(index, OwnedMemory())
        physical += max(0, credit + worker_floor_bytes - _owned(owner.uss_bytes))
        commit += max(0, credit + worker_floor_bytes - _owned(owner.private_commit_bytes))
    missing_idle = worker_count - len(active_credits) - len(idle_owned)
    physical += missing_idle * worker_floor_bytes
    commit += missing_idle * worker_floor_bytes
    for owner in idle_owned:
        physical += max(0, worker_floor_bytes - _owned(owner.uss_bytes))
        commit += max(0, worker_floor_bytes - _owned(owner.private_commit_bytes))
    if physical > max(0, snapshot.physical_available_bytes - margin):
        return False
    if snapshot.commit_required and snapshot.commit_available_bytes is None:
        return False
    return snapshot.commit_available_bytes is None or commit <= max(0, snapshot.commit_available_bytes - margin)


def read_review_geometry(path: Path, settings: Mapping) -> ReviewGeometry | None:
    """Inspect bounded native metadata before import; unknown routes stay exclusive."""
    from Main_App.io import load_utils
    from Main_App.processing.kurtosis_review_scan import (
        _configured_channel_limit, _configured_reference_pair, _configured_stim_channel,
    )
    import mne

    if path.suffix.lower() != ".bdf" or mne.__version__ != "1.9.0":
        return None
    before = path.stat()
    header = load_utils.inspect_bdf_header(path)
    if header is None or not header.data_records or header.data_records < 0 or not header.record_duration:
        return None
    if not header.channel_count or header.channel_count > 4096 or header.header_bytes != (header.channel_count + 1) * 256:
        return None
    # MNE parses annotation payloads even with preload=False. Reject that route
    # from bounded metadata before constructing any lazy Raw.
    with path.open("rb") as stream:
        stream.seek(256)
        labels = stream.read(header.channel_count * 16)
    if len(labels) != header.channel_count * 16 or any(
        labels[index * 16:(index + 1) * 16].strip().lower() in {b"bdf annotations", b"edf annotations"}
        for index in range(header.channel_count)
    ):
        return None
    rate = load_utils.read_bdf_sampling_rate_hz(path, stim_channel=_configured_stim_channel(settings))
    refs, limit = _configured_reference_pair(settings), _configured_channel_limit(settings)

    class LoaderLog:
        def log(self, message, **_kwargs):
            logger.debug("review_budget_header %s", message)

    with load_utils.open_bdf_resource_header(
        LoaderLog(), str(path), ref_pair=refs, first_n_channels=limit,
        stim_channel=_configured_stim_channel(settings),
        electrode_mapping_profile=settings.get("electrode_mapping_profile"),
        electrode_montage="biosemi64",
        acquisition_settings=dict(settings),
    ) as raw:
        if raw is None or len(raw._raw_extras) != 1 or len(raw._raw_extras[0].get("tal_idx", [1])):
            return None
        record_samples_exact = rate * Fraction(str(header.record_duration))
        if record_samples_exact.denominator != 1 or raw.n_times != header.data_records * int(record_samples_exact):
            return None
        record_samples = int(record_samples_exact)
        native_samples = raw._raw_extras[0].get("n_samps")
        if native_samples is None or any(float(value) != record_samples for value in native_samples):
            return None
        channels = len(raw.ch_names)
        present = {name.casefold() for name in raw.ch_names}
        ref_names = {ref.strip().casefold() for ref in refs}
        if not ref_names or not ref_names.issubset(present):
            return None
        source_rate = float(raw.info["sfreq"])
        if not math.isfinite(source_rate) or source_rate <= 0:
            return None
        requested_target = settings.get("downsample_rate", settings.get("downsample", 256))
        target = source_rate if requested_target is None or requested_target is False else float(requested_target)
        if not target or target >= source_rate:
            target = source_rate
        retained = channels - len(ref_names)
        geometry = ReviewGeometry(channels, retained, min(64 if limit is None else limit, retained - 1),
                                  int(raw.n_times), source_rate, target,
                                  int(header.channel_count) * int(record_samples) * 3, int(record_samples))
    after = path.stat()
    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        return None
    return geometry

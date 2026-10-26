"""GUI-neutral admission credits for the ordinary per-recording EEG worker.

The native BDF/approved-span/FPVS-companion route is characterized here. Unknown
routes return ``None`` for exclusive native scheduling. These deliberately
generous credits include overlapping occurrence storage and both possible
sampling rates; they are not a promise against external allocations. Worker
runtime floors and current physical/commit availability remain scheduler-owned.
No waveform, scientific decision, or cross-run geometry cache is retained.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
import math
from pathlib import Path
import sys

from Main_App.workers.review_resource_budget import (
    ReviewGeometry,
    estimate_review_memory,
    read_review_geometry,
)

_MIB = 1024**2
_SUPPORTED_RUNTIME = ("cpython", (3, 13), "1.9.0", "2.3.1", "1.16.0", "2.3.0")


def _runtime_signature() -> tuple:
    import mne
    import numpy
    import pandas
    import scipy

    return (sys.implementation.name, sys.version_info[:2], mne.__version__,
            numpy.__version__, scipy.__version__, pandas.__version__)


def _supported_runtime() -> bool:
    return _runtime_signature() == _SUPPORTED_RUNTIME


def _notch_prefix_bytes(geometry: ReviewGeometry) -> int:
    """Whole-source smart-notch credit for the pinned scalar float64 route.

    Native fft_multinotch loops one channel/edge segment at a time. Masks for
    distinct segment lengths total at most N float64 elements. NumPy 2.3.1's
    scalar pocketfft path has no persistent plan cache or internal threads;
    Bluestein's smooth convolution extent fits nextPower2(2*N). The 1024-byte
    allowance per padded element exceeds its simultaneous N/M-sized plan,
    twiddle, construction, transform and Python expression temporaries.

    Primary pinned sources (NumPy's gitlink selects this pocketfft revision):
    https://github.com/numpy/numpy/blob/v2.3.1/numpy/fft/_pocketfft_umath.cpp
    https://github.com/mreineck/pocketfft/blob/33ae5dc94c9cdc7f1c78346504a85de87cadaa12/pocketfft_hdronly.h
    """
    samples = _positive_int(geometry.source_n_times)
    padded = 1 << (2 * samples - 1).bit_length()
    return 8 * geometry.loaded_channels * samples + 8 * samples + 1024 * padded


def _positive_int(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Processing geometry needs positive integer dimensions.")
    return value


def plain_metadata_bytes(value: object) -> int:
    """Credit primitive native metadata, rejecting executable/custom payloads.

    Account for container slots, Python strings, Unicode codecs and serialized
    copies. The caller additionally reserves multiple concurrent native copies.
    Limits describe the supported estimator domain, not a native data limit.
    """
    from Main_App.projects import FrequencyProtocol

    ancestors: set[int] = set()
    nodes = 0

    def visit(item: object, depth: int) -> int:
        nonlocal nodes
        nodes += 1
        if depth > 32 or nodes > 1_000_000:
            raise ValueError("Metadata is outside the characterized domain.")
        if item is None or type(item) is bool:
            return 64
        if type(item) is int:
            if item.bit_length() > 256:
                raise ValueError("Unbounded metadata integer.")
            return 128
        if type(item) is float:
            if not math.isfinite(item):
                raise ValueError("Non-finite metadata.")
            return 128
        if type(item) is str:
            if len(item) > _MIB:
                raise ValueError("Unbounded metadata string.")
            return 256 + 8 * len(item)
        if isinstance(item, Path):
            return visit(str(item), depth + 1)
        if type(item) is FrequencyProtocol:
            return visit(item.to_manifest(), depth + 1)
        if type(item) not in (dict, list, tuple, set, frozenset):
            raise ValueError("Custom processing metadata needs native scheduling.")
        identity = id(item)
        if identity in ancestors:
            raise ValueError("Cyclic processing metadata.")
        ancestors.add(identity)
        try:
            children = item.items() if type(item) is dict else ((None, child) for child in item)
            size = 256
            for key, child in children:
                size += 64 + (visit(key, depth + 1) if key is not None else 0) + visit(child, depth + 1)
                if size > 256 * _MIB:
                    raise ValueError("Metadata is outside the characterized domain.")
            return size
        finally:
            ancestors.remove(identity)

    return visit(value, 0)


@dataclass(frozen=True)
class ProcessingMemoryEstimate:
    healthy_bytes: int
    emergency_extra_bytes: int
    geometry: ReviewGeometry
    # One entry per occurrence, deliberately retaining overlap/multiplicity.
    source_spans: tuple[tuple[str, int, int], ...]
    oddball_rate_hz: float
    metadata_bytes: int
    repair_requested: bool
    components: tuple[tuple[str, int], ...] = ()

    @property
    def fullrate_bytes(self) -> int:
        """Maximum characterized credit, including the shared emergency loan."""
        return self.healthy_bytes + self.emergency_extra_bytes

    def _shape(self, channels: int, samples: int, sfreq: float) -> tuple[list[int], list[int]]:
        from Main_App.processing.analysis_spans import _v3_stim_window_index

        _positive_int(channels)
        _positive_int(samples)
        if type(sfreq) not in (int, float) or not math.isfinite(sfreq) or sfreq <= 0:
            raise ValueError("Processing sampling rate is not characterized.")
        g = self.geometry
        if channels != g.retained_channels or samples > g.source_n_times:
            raise ValueError("Processing Raw shape exceeds its captured geometry.")
        if float(sfreq) not in (g.source_rate_hz, g.target_rate_hz):
            raise ValueError("Processing rate differs from the source/target grids.")
        if float(sfreq) == g.source_rate_hz and samples != g.source_n_times:
            raise ValueError("The source-rate Raw must retain its captured length.")
        totals: dict[str, int] = {}
        lengths: list[int] = []
        for condition, start, duration in self.source_spans:
            length = Fraction(duration) * Fraction(str(sfreq)) / Fraction(str(g.source_rate_hz))
            if length.denominator != 1 or length <= 0:
                raise ValueError("Approved duration is not an integral target span.")
            mapped_start = _v3_stim_window_index(start, source_count=g.source_n_times, target_count=samples)
            if mapped_start + int(length) > samples:
                raise ValueError("Approved occurrence exceeds the actual Raw grid.")
            lengths.append(int(length))
            totals[condition] = totals.get(condition, 0) + int(length)
        if not lengths:
            raise ValueError("Processing needs approved occurrence spans.")
        return lengths, list(totals.values())

    def tail_bytes(self, channels: int, samples: int, sfreq: float) -> int:
        """Credit actual epochs, spectra, companions, audit and source-time export.

        No allocation or signal read occurs here. Native v3 window mapping checks
        the captured occurrence geometry; the worker still validates markers and
        the scientific span fingerprints through its unchanged native path.
        """
        lengths, condition_samples = self._shape(channels, samples, sfreq)
        eeg = self.geometry.scored_channels
        raw = 8 * channels * samples
        epochs = 8 * channels * sum(lengths)
        largest_condition = 8 * channels * max(condition_samples)
        largest_segment = 8 * channels * max(lengths)
        fft_samples = max(lengths)
        time = 8 * eeg * fft_samples
        spectrum = 8 * eeg * (fft_samples // 2 + 1)
        # Use Nyquist, not the requested filter, since native filter failures can
        # retain a wider applied domain. Native harmonic validation caps at 1e5.
        harmonics = math.ceil(float(sfreq) / (2 * self.oddball_rate_hz)) + 1
        if harmonics > 100_000:
            raise ValueError("Spectral domain is outside the characterized route.")
        metric = 8 * eeg * harmonics
        grid = math.ceil(float(sfreq) * 50) + 3  # native dense 0.01-Hz SNR grid
        dense = 8 * eeg * grid
        # Two conditions can have live locals during the next loop iteration.
        # Per-cell allowances cover metric-QC dictionaries/dataframes, Unicode
        # frequency labels, companion block encoding, and receipt serialization.
        objects = 2 * (16_384 * eeg * harmonics + 512 * (grid + fft_samples + eeg))
        metadata = self.metadata_bytes + objects
        epoch_build = raw + 4 * epochs + 3 * largest_segment + metadata
        export = (raw + epochs + 2 * largest_condition + 16 * time + 32 * spectrum
                  + 16 * metric + 8 * dense + metadata)
        source_export = raw + epochs + 2 * largest_condition + 4 * time + 64 * _MIB + metadata
        return max(epoch_build, export, source_export)

    def _repair_prefix_bytes(self, channels: int, samples: int, sfreq: float) -> int:
        if not self.repair_requested:
            return 0
        lengths, _conditions = self._shape(channels, samples, sfreq)
        g = self.geometry
        original = 8 * g.loaded_channels * g.source_n_times
        raw, scoring = 8 * channels * samples, 8 * g.scored_channels * samples
        # Native replacements accumulate for all requested occurrences. Include
        # all approved occurrences as an upper bound, even for a subset request.
        retained = 8 * g.scored_channels * sum(lengths)
        scratch = 8 * 6 * channels * max(lengths) + 64 * channels**2
        return original + raw + 6 * scoring + retained + scratch + self.metadata_bytes


def build_processing_estimate(
    path: Path, settings: Mapping, event_map: Mapping,
) -> ProcessingMemoryEstimate | None:
    """Bind a per-file credit to the existing header and reviewed native plan.

    RAM preload and disk-backed preload receive the same array extent credit;
    memory mapping is not an assurance that pages stay nonresident. Unknown
    metadata, geometries or plans choose exclusive native scheduling rather than
    a capacity error based on a loose estimate. Host availability is not cached.
    """
    try:
        from Main_App.workers.process_runner import (
            _preflight_event_plan_for_file,
            _project_frequency_protocol,
            _recording_id_for_file,
            _settings_for_file,
        )
        from Main_App.processing.analysis_spans import validate_source_analysis_span_context

        if not isinstance(path, Path) or type(settings) is not dict or type(event_map) is not dict:
            return None
        if not _supported_runtime():
            return None
        if len(event_map) > 256 or any(type(label) is not str or len(label.encode("utf-8")) > 256
                                       for label in event_map):
            return None
        metadata_size = plain_metadata_bytes((settings, event_map))
        file_settings = _settings_for_file(path, settings)
        if any(len(str(file_settings.get(key) or "").encode("utf-8")) > 256 for key in
               ("_fpvs_recording_id", "_fpvs_participant_id", "_fpvs_session_id", "output_recording_stem")):
            return None
        geometry = read_review_geometry(path, file_settings)
        if geometry is None:
            return None
        # This is the ordinary canonical scalp+stim route; other channel types
        # need their native exclusive path rather than inferred array geometry.
        if geometry.retained_channels != geometry.scored_channels + 1:
            return None
        protocol = _project_frequency_protocol(file_settings)
        source = validate_source_analysis_span_context(
            event_plan_payload=_preflight_event_plan_for_file(path, file_settings),
            event_map=event_map, protocol=protocol,
            recording_id=(_recording_id_for_file(path, file_settings)
                          or (file_settings.get("_fpvs_participant_id")
                              if protocol.condition_trigger_maps is not None else None)),
        )
        grid = source["source_grid"]
        if (grid["n_times"] != geometry.source_n_times or grid["first_samp"] != 0
                or grid["sfreq_hz"] != geometry.source_rate_hz):
            return None
        spans = tuple((str(span["condition_label"]),
                       int(span["source_coordinates"]["start_relative_sample"]),
                       int(span["source_coordinates"]["stop_relative_sample"])
                       - int(span["source_coordinates"]["start_relative_sample"]))
                      for span in source["spans"])
        # Each condition creates one EpochsArray and native result manifest.
        # Retained settings/plan trees, sidecars and IPC may coexist with these.
        # Source and target event arrays can remain in the worker frame through
        # exports. At most one stimulus transition per source sample is possible.
        event_arrays = 128 * geometry.source_n_times
        metadata = (64 * _MIB + event_arrays
                    + (16 + 8 * len({span[0] for span in spans})) * metadata_size)
        candidate = ProcessingMemoryEstimate(
            0, 0, geometry, spans, float(protocol.oddball_rate_hz), metadata,
            bool(file_settings.get("_fpvs_condition_interpolation_requests")),
        )
        g = geometry
        target_samples = max(1, math.ceil(g.source_n_times * g.target_rate_hz / g.source_rate_hz))
        target_tail = candidate.tail_bytes(g.retained_channels, target_samples, g.target_rate_hz)
        source_tail = candidate.tail_bytes(g.retained_channels, g.source_n_times, g.source_rate_hz)
        target_repairs = candidate._repair_prefix_bytes(g.retained_channels, target_samples, g.target_rate_hz)
        source_repairs = candidate._repair_prefix_bytes(g.retained_channels, g.source_n_times, g.source_rate_hz)
        review = estimate_review_memory(
            g, filter_enabled=True,
            notch_enabled=bool(file_settings.get("line_noise_filter_enabled", True)),
            # evaluate_raw_channel_qc always materializes its approved union;
            # AUTO controls extra spatial rules, not the common statistics.
            raw_qc_enabled=True,
            raw_union_samples=int(source["unique_sample_count"]),
        )
        # Event finding can inspect every source sample. Metadata already supplied
        # by preflight is counted above; this covers fresh event arrays/scratch.
        event_prefix = 8 * g.loaded_channels * g.source_n_times + metadata
        # Cache publication precedes the tail barrier. A restored checkpoint can
        # still retain the original loaded Raw here; include single-precision
        # FIF conversion/buffers and JSON copies before granting the next phase.
        original = 8 * g.loaded_channels * g.source_n_times
        target_cache = original + 4 * 8 * g.retained_channels * target_samples + metadata + 64 * _MIB
        source_cache = original + 4 * 8 * g.retained_channels * g.source_n_times + metadata + 64 * _MIB
        notch = (_notch_prefix_bytes(g) + metadata
                 if file_settings.get("line_noise_filter_enabled", True) else 0)
        healthy = max(review.healthy_bytes + metadata, target_tail, target_repairs,
                      event_prefix, target_cache, notch)
        full = max(healthy, review.fullrate_qc_bytes + metadata, source_tail, source_repairs, source_cache)
        components = (("review_prefix", review.healthy_bytes + metadata),
                      ("event_prefix", event_prefix), ("target_tail", target_tail),
                      ("source_tail", source_tail), ("target_repairs", target_repairs),
                      ("source_repairs", source_repairs), ("target_cache", target_cache),
                      ("source_cache", source_cache), ("fft_notch", notch), ("event_arrays", event_arrays),
                      ("metadata", metadata))
        return ProcessingMemoryEstimate(healthy, full - healthy, g, spans,
                                        candidate.oddball_rate_hz, metadata,
                                        candidate.repair_requested, components)
    except (AttributeError, ImportError, KeyError, OSError, OverflowError, RuntimeError, TypeError, ValueError):
        return None

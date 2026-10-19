"""Brain Products source reading and explicit stimulus-marker adaptation.

BVCDF calibration and annotations are read by the pinned MNE BrainVision
reader. BVRF uses the separately validated streaming adapter. Marker impulses
are an adapter channel; source annotations remain available without collapsing
Stimulus, Response, or segment markers onto the same numeric namespace.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from pathlib import Path
import re
import traceback

import mne
import numpy as np
from mne._fiff.utils import _mult_cal_one

from Main_App.io.brain_products_bvrf import RawBVRF, read_bvrf_header
from Main_App.io.brain_products_files import (
    BrainProductsFormatError,
    HEADER_EXTENSIONS,
    read_brainvision_header,
    source_files,
)


def read_sampling_rate(path: str | Path) -> float:
    """Read header sampling frequency without loading signal samples."""
    path = Path(path)
    if path.suffix.lower() == ".bvrh":
        return read_bvrf_header(path)["sfreq"]
    if path.suffix.lower() != ".vhdr":
        raise BrainProductsFormatError("Select a BrainVision .vhdr or .bvrh header.")
    try:
        interval = float(read_brainvision_header(path)["Common Infos"]["SamplingInterval"])
    except (KeyError, ValueError) as exc:
        raise BrainProductsFormatError("BrainVision SamplingInterval must be a positive number.") from exc
    if not np.isfinite(interval) or interval <= 0:
        raise BrainProductsFormatError("BrainVision SamplingInterval must be a positive number.")
    return 1e6 / interval


def validate_electrical_channel_units(raw: mne.io.BaseRaw, roles: Mapping[str, str] | None = None) -> None:
    """Role overrides cannot turn uncalibrated auxiliary values into EEG volts."""
    roles = roles or {}
    original = raw._orig_units or {}
    for name, kind in zip(raw.ch_names, raw.get_channel_types(), strict=True):
        if roles.get(name, kind) not in {"eeg", "eog", "ecg", "emg", "bio"}:
            continue
        if original.get(name) not in {"V", "mV", "µV", "μV", "uV", "nV"}:
            raise BrainProductsFormatError(
                f"Electrical channel {name!r} has unsupported source unit {original.get(name)!r}. "
                "Export it with an explicit voltage calibration before assigning an EEG/EOG/ECG/EMG role."
            )


def _event_codes(values: Iterable[int]) -> set[int]:
    result = set()
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or not 0 < value < 2**24:
            raise BrainProductsFormatError("Configured stimulus codes must be positive integers below 2^24.")
        result.add(int(value))
    if not result:
        raise BrainProductsFormatError("Configure at least one stimulus event code before processing.")
    return result


def _require_continuous_source(raw: mne.io.BaseRaw, path: Path) -> None:
    """Never filter across declared acquisition gaps or Analyze-export segments.

    Brain Products documents New Segment as a data-flow discontinuity, and
    Time 0 as a segmented-data marker. Reviewed interval exclusion is not yet
    an input to this adapter, so a marked bad interval also fails closed.
    """
    if path.suffix.lower() == ".vhdr":
        common = read_brainvision_header(path)["Common Infos"]
        if common.get("Averaged", "NO").upper() != "NO" or common.get("SegmentationType", "NOTSEGMENTED").upper() != "NOTSEGMENTED":
            raise BrainProductsFormatError("Use a continuous, unaveraged BrainVision recording for FPVS processing.")
    for onset, label in zip(raw.annotations.onset, raw.annotations.description):
        kind = str(label).split("/", 1)[0].strip().casefold()
        sample = int(np.rint((onset - raw.first_time) * raw.info["sfreq"]))
        if (kind == "new segment" and sample != 0) or kind in {
            "bad interval", "time 0", "data error", "discontinuity", "gap", "buffer overflow",
        }:
            raise BrainProductsFormatError(
                f"BrainVision declares {kind!r} at sample {sample}. "
                "Export a continuous, valid recording before FPVS processing; gaps cannot be joined silently."
            )


def decode_brain_products_events(raw: mne.io.BaseRaw, event_codes: Iterable[int] | None = None) -> np.ndarray:
    """Decode configured Stimulus/S markers only, retaining native sample indices.

    BrainVision type prefixes are mandatory: a Response/R1 is never condition
    S1. Simultaneous different selected events and adjacent identical impulses
    are rejected because a single Status channel cannot represent them faithfully.
    """
    wanted = _event_codes(event_codes) if event_codes is not None else None
    events = []
    occupied: dict[int, int] = {}
    for onset, description in zip(raw.annotations.onset, raw.annotations.description):
        match = re.fullmatch(r"Stimulus/S\s*(\d+)", str(description))
        if match is None:
            continue
        code = int(match.group(1))
        if wanted is not None and code not in wanted:
            continue
        if not 0 < code < 2**24:
            raise BrainProductsFormatError("Stimulus codes must be positive integers below 2^24.")
        sample = int(np.rint((onset - raw.first_time) * raw.info["sfreq"])) + raw.first_samp
        if sample < raw.first_samp or sample > raw.last_samp:
            raise BrainProductsFormatError("A selected stimulus marker lies outside the recording.")
        if sample in occupied:
            raise BrainProductsFormatError("Multiple selected stimulus markers occupy the same sample.")
        occupied[sample] = code
        events.append((sample, 0, code))
    events.sort()
    if not events:
        raise BrainProductsFormatError("No configured Stimulus/S event codes were found in this recording.")
    for previous, current in zip(events, events[1:]):
        if current[0] == previous[0] + 1 and current[2] == previous[2]:
            raise BrainProductsFormatError("Adjacent identical stimulus markers cannot form separate Status impulses.")
    return np.asarray(events, dtype=np.int64).reshape(-1, 3)


class _RawWithStatus(mne.io.BaseRaw):
    """Stream a canonical stimulus channel alongside a vendor-backed Raw."""

    def __init__(self, source: mne.io.BaseRaw, events: np.ndarray, status_channel: str, preload: bool | str):
        if status_channel in source.ch_names:
            raise BrainProductsFormatError(f"Recorded channel {status_channel!r} conflicts with the canonical stimulus channel.")
        info = source.info.copy()
        status = mne.create_info([status_channel], info["sfreq"], "stim")
        with info._unlock():
            info["chs"] = list(info["chs"]) + list(status["chs"])
            info._update_redundant()
        # Source.get_data already returns SI calibrated values.
        for channel in info["chs"]:
            channel["cal"], channel["range"] = 1.0, 1.0
        extras = {"source": source, "events": events}
        super().__init__(info, preload=preload, first_samps=[source.first_samp],
                         last_samps=[source.last_samp], filenames=[str(source.filenames[0])],
                         raw_extras=[extras], verbose=False)
        self.set_annotations(source.annotations.copy())
        self._fpvs_brain_products_events = events.copy()
        self._orig_units = dict(source._orig_units or {})
        for name in ("impedances", "_fpvs_brain_products_header", "_fpvs_brain_products_marker_rows"):
            if hasattr(source, name):
                setattr(self, name, getattr(source, name))

    def _read_segment_file(self, data, idx, fi, start, stop, cals, mult):
        extra = self._raw_extras[fi]
        source = extra["source"]
        block = np.zeros((len(source.ch_names) + 1, stop - start))
        block[:-1] = source.get_data(start=start - source.first_samp, stop=stop - source.first_samp)
        events = extra["events"]
        selected = events[(events[:, 0] >= start) & (events[:, 0] < stop)]
        block[-1, selected[:, 0] - start] = selected[:, 2]
        _mult_cal_one(data, block, idx, cals, mult)

    def close(self):
        for extra in self._raw_extras:
            extra["source"].close()
        return super().close()


def read_brain_products_raw(
    path: str | Path, *, preload: bool | str = False,
    event_codes: Iterable[int] | None = None, status_channel: str = "Status", synthesize_status: bool = True,
) -> mne.io.BaseRaw:
    """Read BrainVision samples in SI units, optionally adding canonical events.

    A string preload is a new caller-owned memory-map path. Reading never
    overwrites source or existing files. Use ``open_brain_products_recording``
    when the caller needs deterministic memory-map closure.
    """
    files = source_files(path)
    if not isinstance(preload, (bool, str)):
        raise TypeError("preload must be False, True, or a new memory-map filename.")
    if isinstance(preload, str):
        target = Path(preload)
        if target.exists() or target.resolve() in files:
            raise FileExistsError("Brain Products preload must use a new, non-source file.")
        if not target.parent.is_dir():
            raise FileNotFoundError("The preload memory-map parent directory does not exist.")
    path, raw = files[0], None
    try:
        reader_preload = False if synthesize_status else preload
        if path.suffix.lower() == ".vhdr":
            raw = mne.io.read_raw_brainvision(path, preload=reader_preload, verbose=False)
        else:
            raw = RawBVRF(path, preload=reader_preload)
        validate_electrical_channel_units(raw)
        if synthesize_status:
            _require_continuous_source(raw, path)
            events = decode_brain_products_events(raw, event_codes)
            raw = _RawWithStatus(raw, events, status_channel, preload)
        raw._fpvs_brain_products_source_files = tuple(str(file) for file in files)
        return raw
    except Exception as exc:
        # MNE construction can allocate a map before returning Raw. Drop those
        # completed frames so Windows can remove only this call's new scratch file.
        traceback.clear_frames(exc.__traceback__)
        if raw is not None:
            close_brain_products_raw(raw)
        if isinstance(preload, str):
            Path(preload).unlink(missing_ok=True)
        raise


def close_brain_products_raw(raw: mne.io.BaseRaw) -> None:
    """Release a reader and its preloaded map, including error tracebacks."""
    mmap = getattr(getattr(raw, "_data", None), "_mmap", None)
    if mmap is not None:
        raw._data = None
    try:
        raw.close()
    finally:
        if mmap is not None:
            mmap.close()


@contextmanager
def open_brain_products_recording(path: str | Path, **kwargs):
    """Own a reader lifetime, including closure of caller-provided memory maps."""
    raw = read_brain_products_raw(path, **kwargs)
    try:
        yield raw
    finally:
        close_brain_products_raw(raw)


__all__ = ["BrainProductsFormatError", "HEADER_EXTENSIONS", "source_files", "read_sampling_rate",
           "read_brain_products_raw", "decode_brain_products_events", "open_brain_products_recording",
           "validate_electrical_channel_units", "close_brain_products_raw"]

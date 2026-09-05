"""Lossless, non-executable cache payloads for preflight numerical evidence.

Only the explicitly listed evidence dataclasses can be restored. Marker review
decisions and approved plans are deliberately absent: callers rebuild authority
from current decisions and wrap reused evidence in the current exact span.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import logging
from pathlib import Path
import struct
from typing import Any

import numpy as np

from Main_App.processing.fft_multinotch import SkippedNotchCenter
from Main_App.processing.preflight_qc_cache import (
    load_preflight_qc_cache,
    save_preflight_qc_cache,
)
from Main_App.processing.raw_channel_qc import (
    ConditionRawChannelQCResult,
    RawChannelBlockMetrics,
    RawChannelConditionAggregate,
    RawChannelMetricSet,
    RawChannelTransientExtrema,
)
from Main_App.processing.raw_spectral_qc import (
    ConditionSpectralNotchCollision,
    ConditionSpectralPeak,
    ConditionSpectralQCResult,
)

logger = logging.getLogger(__name__)
_EVIDENCE_CLASSES = {
    cls.__name__: cls
    for cls in (
        ConditionRawChannelQCResult,
        RawChannelBlockMetrics,
        RawChannelConditionAggregate,
        RawChannelMetricSet,
        RawChannelTransientExtrema,
        ConditionSpectralQCResult,
        ConditionSpectralPeak,
        ConditionSpectralNotchCollision,
        SkippedNotchCenter,
    )
}


def encode_evidence(value: Any) -> Any:
    """Keep tuple types and every float64 bit, including NaN and signed zero."""

    if is_dataclass(value) and _EVIDENCE_CLASSES.get(type(value).__name__) is type(value):
        return {
            "dataclass": type(value).__name__,
            "fields": {field.name: encode_evidence(getattr(value, field.name)) for field in fields(value)},
        }
    if isinstance(value, (float, np.floating)):
        return {"float64": struct.pack(">d", float(value)).hex()}
    if isinstance(value, tuple):
        return {"tuple": [encode_evidence(item) for item in value]}
    if isinstance(value, list):
        return [encode_evidence(item) for item in value]
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("Evidence mapping keys must be strings")
        return {"mapping": {key: encode_evidence(item) for key, item in value.items()}}
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    if value is None or type(value) in (str, int, bool):
        return value
    raise TypeError(f"Unsupported preflight evidence type: {type(value).__name__}")


def decode_evidence(value: Any) -> Any:
    """Restore only allowlisted value types; never import or execute cache code."""

    if isinstance(value, list):
        return [decode_evidence(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {"float64"}:
            return struct.unpack(">d", bytes.fromhex(value["float64"]))[0]
        if set(value) == {"tuple"} and isinstance(value["tuple"], list):
            return tuple(decode_evidence(item) for item in value["tuple"])
        if set(value) == {"mapping"} and isinstance(value["mapping"], dict):
            return {key: decode_evidence(item) for key, item in value["mapping"].items()}
        if set(value) == {"dataclass", "fields"}:
            cls = _EVIDENCE_CLASSES[value["dataclass"]]
            values = value["fields"]
            if not isinstance(values, dict) or set(values) != {field.name for field in fields(cls)}:
                raise ValueError("Cached evidence fields do not match current dataclass")
            return cls(**{key: decode_evidence(item) for key, item in values.items()})
        raise ValueError("Invalid cached evidence type")
    if value is None or type(value) in (str, int, bool):
        return value
    raise ValueError("Invalid cached evidence scalar")


def load_occurrence_evidence(
    project_root: Path, **key: Any,
) -> tuple[ConditionRawChannelQCResult, ConditionSpectralQCResult | None] | None:
    cached = load_preflight_qc_cache(project_root, namespace="occurrences", **key)
    if cached is None:
        return None
    try:
        channel = decode_evidence(cached["raw_channel"])
        spectral = decode_evidence(cached["spectral"])
        if not isinstance(channel, ConditionRawChannelQCResult):
            return None
        if spectral is not None and not isinstance(spectral, ConditionSpectralQCResult):
            return None
        layout = key["event_plan"]
        span = layout["span"]
        if channel.channel_names != tuple(layout["channel_names"]) or len(channel.conditions) != 1:
            return None
        condition = channel.conditions[0]
        if (
            condition.condition_id != span["condition_label"]
            or condition.occurrence != span["repetition_index"]
            or condition.start_sample != span["time_start_sample"]
            or condition.stop_sample != span["time_stop_sample"]
        ):
            return None
        spectral_expected = span["spectral_start_sample"] is not None and span["spectral_stop_sample"] is not None
        if spectral_expected != (spectral is not None):
            return None
        if spectral is not None and (
            spectral.n_samples != span["spectral_stop_sample"] - span["spectral_start_sample"]
            or spectral.sfreq != layout["sfreq"]
            or spectral.scalp_channels != tuple(layout["channel_names"])
        ):
            return None
        return channel, spectral
    except (AttributeError, KeyError, TypeError, ValueError, struct.error, OverflowError, RecursionError):
        return None


def save_occurrence_evidence(
    project_root: Path,
    *,
    channel: ConditionRawChannelQCResult,
    spectral: ConditionSpectralQCResult | None,
    **key: Any,
) -> None:
    try:
        save_preflight_qc_cache(
            project_root,
            namespace="occurrences",
            result={"raw_channel": encode_evidence(channel), "spectral": encode_evidence(spectral)},
            **key,
        )
    except (OSError, TypeError, ValueError):
        logger.exception("preflight_occurrence_cache_save_failed")


def load_source_events(project_root: Path, **key: Any) -> tuple[np.ndarray, str] | None:
    cached = load_preflight_qc_cache(project_root, namespace="events", **key)
    if cached is None:
        return None
    rows = cached.get("events")
    source = cached.get("source")
    if not isinstance(source, str) or source not in {"stim", "annotations"} or not isinstance(rows, list) or not rows:
        return None
    if any(
        not isinstance(row, list) or len(row) != 3 or any(type(item) is not int for item in row)
        for row in rows
    ):
        return None
    try:
        events = np.asarray(rows, dtype=np.int64)
    except (TypeError, ValueError, OverflowError):
        return None
    layout = key["event_plan"]
    if (
        np.any(events[:, 0] < layout["first_samp"])
        or np.any(events[:, 0] >= layout["first_samp"] + layout["n_times"])
        or np.any(np.diff(events[:, 0]) < 0)
    ):
        return None
    return events, source


def save_source_events(
    project_root: Path, *, events: np.ndarray, source: str, **key: Any,
) -> None:
    try:
        save_preflight_qc_cache(
            project_root, namespace="events",
            result={"events": events.tolist(), "source": source}, **key,
        )
    except (OSError, TypeError, ValueError):
        logger.exception("preflight_source_events_cache_save_failed")

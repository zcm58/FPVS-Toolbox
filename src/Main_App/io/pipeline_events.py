"""Expose admitted native-grid markers without device decisions downstream."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

import numpy as np

from Main_App.io.recording_contract import RecordingContract
from Main_App.io.recording_events import (
    CanonicalEvents,
    RecordingEventError,
    decode_sample_status,
)


def canonical_recording_events(
    raw: Any, *, recording_contract: RecordingContract | None = None,
) -> np.ndarray | None:
    """Return admitted markers, or ``None`` for the historical edge path.

    An empty canonical sequence remains authoritative. Errors never trigger a
    fallback to edge detection or automatic annotation numbering. Attached
    coordinates describe one native sample grid and cannot survive resampling.
    """
    admitted = getattr(raw, "_fpvs_canonical_events", None)
    contract = recording_contract or getattr(raw, "_fpvs_recording_contract", None)
    if admitted is not None:
        native_sfreq = getattr(raw, "_fpvs_canonical_events_sfreq", None)
        if native_sfreq is None or float(native_sfreq) != float(raw.info["sfreq"]):
            raise RecordingEventError("Canonical markers require their original native sampling grid.")
        values = admitted.as_mne_events() if isinstance(admitted, CanonicalEvents) else admitted
        events = np.asarray(values)
        if events.ndim != 2 or events.shape[1] != 3 or events.dtype.kind not in "iu":
            raise RecordingEventError("Canonical markers must be an integer array with three columns.")
        if events.size and (
            np.any(events[:, 0] < raw.first_samp)
            or np.any(events[:, 0] >= raw.first_samp + raw.n_times)
            or np.any(events[1:, 0] <= events[:-1, 0])
            or np.any(events[:, 1] != 0)
            or np.any(events[:, 2] <= 0)
            or np.any(events > np.iinfo(np.int64).max)
        ):
            raise RecordingEventError("Canonical markers have invalid native samples or codes.")
        return events.astype(np.int64, copy=True)
    if contract is None or contract.event_encoding == "edge":
        return None
    if contract.event_encoding != "sample":
        raise RecordingEventError(f"Unsupported event encoding: {contract.event_encoding!r}.")
    if contract.stim_channel not in raw.ch_names:
        raise RecordingEventError("Sample-encoded markers require the admitted stimulus channel.")
    return decode_sample_status(
        raw.get_data(picks=[contract.stim_channel])[0],
        sfreq=float(raw.info["sfreq"]), first_samp=int(raw.first_samp),
        channel=contract.stim_channel,
    ).as_mne_events()


def _metadata_digest(payload: Mapping[str, Any], cache_key: str) -> str:
    return hashlib.sha256(json.dumps(
        {"cache_key": cache_key, "markers": payload}, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def snapshot_canonical_event_metadata(raw: Any, *, cache_key: str) -> dict[str, Any] | None:
    """Save only explicit canonical events; historical edge caches stay unchanged."""
    events = canonical_recording_events(raw)
    if events is None:
        return None
    payload = {
        "schema_version": 1, "sfreq": float(raw.info["sfreq"]),
        "first_samp": int(raw.first_samp), "n_times": int(raw.n_times),
        "events": events.tolist(),
    }
    return {**payload, "sha256": _metadata_digest(payload, cache_key)}


def restore_canonical_event_metadata(
    raw: Any, metadata: Mapping[str, Any] | None, *, cache_key: str,
) -> None:
    """Validate cached event evidence before restoring its native-grid authority."""
    contract = getattr(raw, "_fpvs_recording_contract", None)
    if metadata is None:
        if contract is not None and contract.event_encoding != "edge":
            raise RecordingEventError("Cached recording is missing canonical marker metadata.")
        return
    if not isinstance(metadata, Mapping):
        raise RecordingEventError("Cached canonical marker metadata is malformed.")
    payload = {key: value for key, value in metadata.items() if key != "sha256"}
    if (
        payload.get("schema_version") != 1
        or payload.get("sfreq") != float(raw.info["sfreq"])
        or payload.get("first_samp") != int(raw.first_samp)
        or payload.get("n_times") != int(raw.n_times)
        or metadata.get("sha256") != _metadata_digest(payload, cache_key)
    ):
        raise RecordingEventError("Cached canonical marker metadata does not match the recording.")
    events = np.asarray(payload.get("events"))
    if events.size == 0 and payload.get("events") == []:
        events = np.empty((0, 3), dtype=np.int64)
    raw._fpvs_canonical_events = events
    raw._fpvs_canonical_events_sfreq = payload["sfreq"]
    canonical_recording_events(raw)


__all__ = [
    "canonical_recording_events", "restore_canonical_event_metadata",
    "snapshot_canonical_event_metadata",
]

"""Explicit native-grid event decoding, independent of acquisition qualification.

Annotation onsets are seconds from the first recorded data sample, not UTC or
MNE annotation origins. Format adapters must resolve that origin before calling
this module. Decoding establishes marker identity, not wireless continuity or
physical stimulus timing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, ROUND_HALF_UP
import math
from numbers import Integral, Real
import re
from typing import Iterable, Literal, Mapping, Sequence

import numpy as np

STATUS_DECODER_ID = "unicorn_sample"
ANNOTATION_DECODER_ID = "explicit_annotations"
EVENT_DECODER_VERSION = "1.0"
NATIVE_SAMPLE_TOLERANCE = Decimal("0.0000001")
EventAuthority = Literal["status", "annotations", "reconcile"]


class RecordingEventError(ValueError):
    """Recorded event evidence cannot be represented without ambiguity or loss."""


@dataclass(frozen=True)
class RecordingAnnotation:
    source_id: str
    source_order: int
    onset_seconds: float
    duration_seconds: float
    text: str


@dataclass(frozen=True)
class CanonicalEvent:
    source_id: str
    source_order: int
    code: int
    sample: int
    source_channel: str | None
    annotation_text: str | None
    onset_seconds: float
    duration_seconds: float
    quantization_residual_seconds: float


@dataclass(frozen=True)
class CanonicalEvents:
    events: tuple[CanonicalEvent, ...]
    annotations: tuple[RecordingAnnotation, ...]
    decoder_id: str
    decoder_version: str
    authority: EventAuthority

    def as_mne_events(self) -> np.ndarray:
        """Return an independent integer (n, 3) view without edge detection."""

        return np.asarray(
            [(event.sample, 0, event.code) for event in self.events],
            dtype=np.int64,
        ).reshape((-1, 3))


def _finite_real(value: object, name: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise RecordingEventError(f"{name} must be a finite real number.")
    result = float(value)
    if not math.isfinite(result):
        raise RecordingEventError(f"{name} must be a finite real number.")
    return result


def _integer(value: object, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
        raise RecordingEventError(f"{name} must be an integer.")
    result = int(value)
    if minimum is not None and result < minimum:
        raise RecordingEventError(f"{name} must be at least {minimum}.")
    return result


def _code(value: object, name: str) -> int:
    result = _integer(value, name, minimum=1)
    if result > 255:
        raise RecordingEventError(f"{name} must be in the range 1..255.")
    return result


def _grid(sfreq: float, first_samp: int, n_samples: int) -> tuple[float, int, int]:
    rate = _finite_real(sfreq, "sfreq")
    if rate <= 0:
        raise RecordingEventError("sfreq must be positive.")
    origin = _integer(first_samp, "first_samp")
    count = _integer(n_samples, "n_samples", minimum=0)
    bounds = np.iinfo(np.int64)
    if origin < bounds.min or origin > bounds.max or origin + max(0, count - 1) > bounds.max:
        raise RecordingEventError("The native sample grid exceeds signed 64-bit event coordinates.")
    return rate, origin, count


def decode_sample_status(
    values: Sequence[float] | np.ndarray,
    *,
    sfreq: float,
    first_samp: int = 0,
    channel: str = "Status",
) -> CanonicalEvents:
    """Treat each nonzero sample as one marker, including equal adjacent codes.

    This is the explicitly selected Unicorn sample encoding. It must never
    replace BioSemi's level/edge semantics merely because a channel is Status.
    """

    if not isinstance(channel, str) or not channel.strip():
        raise RecordingEventError("Status source channel must be a nonempty name.")
    try:
        array = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise RecordingEventError("Status values must be a one-dimensional numeric array.") from exc
    if array.ndim != 1 or array.dtype.kind not in "iuf":
        raise RecordingEventError("Status values must be a one-dimensional numeric array.")
    rate, origin, _ = _grid(sfreq, first_samp, len(array))
    if not np.isfinite(array).all():
        raise RecordingEventError("Status values must be finite.")
    if np.any(array < 0) or np.any(array > 255):
        raise RecordingEventError("Status values must be zero or codes in the range 1..255.")
    if np.any(array != np.floor(array)):
        raise RecordingEventError("Status values must be integer codes.")
    events = tuple(
        CanonicalEvent(
            source_id=f"status:{channel}:{int(index)}",
            source_order=int(index),
            code=int(array[index]),
            sample=origin + int(index),
            source_channel=channel,
            annotation_text=None,
            onset_seconds=int(index) / rate,
            duration_seconds=0.0,
            quantization_residual_seconds=0.0,
        )
        for index in np.flatnonzero(array)
    )
    return CanonicalEvents(events, (), STATUS_DECODER_ID, EVENT_DECODER_VERSION, "status")


def _annotation_sample(
    annotation: RecordingAnnotation,
    *,
    rate: float,
    origin: int,
    count: int,
) -> tuple[int, float]:
    # Decimal text avoids manufacturing off-grid residuals from float products.
    onset = Decimal(str(annotation.onset_seconds))
    sample_position = onset * Decimal(str(rate))
    rounded = sample_position.to_integral_value(rounding=ROUND_HALF_UP)
    residual_samples = sample_position - rounded
    if abs(residual_samples) > NATIVE_SAMPLE_TOLERANCE:
        raise RecordingEventError(
            f"Annotation {annotation.source_id!r} is off the native sample grid; "
            "rounding or quantizing recorded marker times is not permitted."
        )
    relative_sample = int(rounded)
    if onset < 0 or not 0 <= relative_sample < count:
        raise RecordingEventError(f"Annotation {annotation.source_id!r} is outside the recording bounds.")
    end_sample = (onset + Decimal(str(annotation.duration_seconds))) * Decimal(str(rate))
    if end_sample - count > NATIVE_SAMPLE_TOLERANCE:
        raise RecordingEventError(f"Annotation {annotation.source_id!r} duration exceeds the recording bounds.")
    return origin + relative_sample, float(residual_samples / Decimal(str(rate)))


def decode_annotation_events(
    annotations: Iterable[RecordingAnnotation],
    *,
    sfreq: float,
    n_samples: int,
    first_samp: int = 0,
    numeric_codes: bool,
    named_codes: Mapping[str, int],
    marker_labels: tuple[str, ...] = (),
) -> CanonicalEvents:
    """Decode explicit protocol labels while retaining every source annotation.

    The numeric rule accepts whitespace-trimmed ASCII unsigned decimal labels
    with values 1..255. Other text is a note unless explicitly mapped or declared
    in marker_labels. Declared but unmapped marker labels require a decision.
    Exact named mappings take no implicit case-folding or alphabetical IDs.

    Half-up rounding identifies the candidate sample, but residuals exceeding
    1e-7 of a sample are rejected, including half-sample ties. This tolerance
    covers numeric representation only; true off-grid times are never snapped.
    """

    rate, origin, count = _grid(sfreq, first_samp, n_samples)
    if type(numeric_codes) is not bool:
        raise RecordingEventError("numeric_codes must be an explicit boolean.")
    if not isinstance(named_codes, Mapping):
        raise RecordingEventError("named_codes must be an explicit label-to-code mapping.")
    mapping: dict[str, int] = {}
    for label, code in named_codes.items():
        if not isinstance(label, str) or not label.strip():
            raise RecordingEventError("Named marker labels must be nonempty strings.")
        mapping[label] = _code(code, f"Code for annotation {label!r}")
    if isinstance(marker_labels, str) or any(not isinstance(label, str) or not label.strip() for label in marker_labels):
        raise RecordingEventError("marker_labels must contain nonempty strings.")
    declared_markers = set(marker_labels)
    retained = tuple(annotations)
    seen_ids: set[str] = set()
    previous_order = -1
    marker_samples: set[int] = set()
    events: list[CanonicalEvent] = []
    for annotation in retained:
        if not isinstance(annotation, RecordingAnnotation):
            raise RecordingEventError("Annotations must be RecordingAnnotation records.")
        if not isinstance(annotation.source_id, str) or not annotation.source_id.strip():
            raise RecordingEventError("Annotation source identity must be nonempty.")
        if annotation.source_id in seen_ids:
            raise RecordingEventError("Annotation source identities must be unique.")
        seen_ids.add(annotation.source_id)
        source_order = _integer(annotation.source_order, "Annotation source_order", minimum=0)
        if source_order <= previous_order:
            raise RecordingEventError("Annotations must retain strictly increasing source order.")
        previous_order = source_order
        _finite_real(annotation.onset_seconds, "Annotation onset_seconds")
        if _finite_real(annotation.duration_seconds, "Annotation duration_seconds") < 0:
            raise RecordingEventError("Annotation duration_seconds must be nonnegative.")
        if not isinstance(annotation.text, str):
            raise RecordingEventError("Annotation text must be a string.")
        label = annotation.text
        numeric_code = None
        if numeric_codes and re.fullmatch(r"[0-9]+", label.strip()):
            numeric_code = _code(int(label.strip()), f"Numeric annotation {label!r}")
        named_code = mapping.get(label)
        if named_code is not None and numeric_code is not None and named_code != numeric_code:
            raise RecordingEventError(f"Annotation {label!r} has conflicting numeric and named codes.")
        code = named_code if named_code is not None else numeric_code
        if code is None:
            if label in declared_markers:
                raise RecordingEventError(f"Marker annotation {label!r} has no explicit code mapping.")
            continue
        sample, residual = _annotation_sample(annotation, rate=rate, origin=origin, count=count)
        if sample in marker_samples:
            raise RecordingEventError("Annotation markers collide at one sample; source events cannot be collapsed.")
        marker_samples.add(sample)
        events.append(
            CanonicalEvent(
                source_id=annotation.source_id,
                source_order=source_order,
                code=code,
                sample=sample,
                source_channel=None,
                annotation_text=annotation.text,
                onset_seconds=annotation.onset_seconds,
                duration_seconds=annotation.duration_seconds,
                quantization_residual_seconds=residual,
            )
        )
    # BDF+ permits TALs outside the record containing their event. Keep source
    # order in the evidence while supplying chronological canonical events.
    events.sort(key=lambda event: event.sample)
    return CanonicalEvents(tuple(events), retained, ANNOTATION_DECODER_ID, EVENT_DECODER_VERSION, "annotations")


def reconcile_event_sources(
    status: CanonicalEvents | None,
    annotations: CanonicalEvents | None,
    *,
    authority: EventAuthority,
) -> CanonicalEvents:
    """Select declared authority and reject contradictory marker sequences.

    Explicit single-source authority permits the other source to contain only
    notes or be absent. Reconciliation requires both sources and full equality
    of ordered (sample, code) pairs. It emits one sequence, retaining original
    annotation records; it never concatenates or silently falls back.
    """

    if authority not in {"status", "annotations", "reconcile"}:
        raise RecordingEventError("Event authority must be status, annotations, or reconcile.")
    for source, expected_authority in ((status, "status"), (annotations, "annotations")):
        if source is not None and (
            not isinstance(source, CanonicalEvents) or source.authority != expected_authority
        ):
            raise RecordingEventError(f"The {expected_authority} input must be its original decoded event source.")
    if authority == "reconcile" and (status is None or annotations is None):
        raise RecordingEventError("Reconciliation requires both recorded event sources.")
    if status is not None and annotations is not None and (
        authority == "reconcile" or (status.events and annotations.events)
    ):
        status_pairs = tuple((event.sample, event.code) for event in status.events)
        annotation_pairs = tuple((event.sample, event.code) for event in annotations.events)
        if status_pairs != annotation_pairs:
            raise RecordingEventError("Status and annotation markers conflict in code, order, or native sample.")
    selected = annotations if authority == "annotations" else status
    if selected is None:
        raise RecordingEventError(f"The declared {authority} event source is absent; fallback is not permitted.")
    retained_annotations = annotations.annotations if annotations is not None else ()
    if authority == "reconcile":
        assert status is not None and annotations is not None
        return replace(
            selected,
            annotations=retained_annotations,
            decoder_id=f"{status.decoder_id}+{annotations.decoder_id}",
            decoder_version=f"{status.decoder_version}+{annotations.decoder_version}",
            authority=authority,
        )
    return replace(selected, annotations=retained_annotations, authority=authority)


__all__ = [
    "ANNOTATION_DECODER_ID", "CanonicalEvent", "CanonicalEvents", "EVENT_DECODER_VERSION",
    "EventAuthority", "RecordingAnnotation", "RecordingEventError", "STATUS_DECODER_ID",
    "decode_annotation_events", "decode_sample_status", "reconcile_event_sources",
]

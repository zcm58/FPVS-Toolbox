"""Pure repeated-session SNR aggregation and pairing helpers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import math


class RepeatedSessionSNRIdentityError(ValueError):
    """Raised when canonical recording/session identity is incomplete or unsafe."""


class RepeatedSessionSNRDataError(ValueError):
    """Raised when recording curves cannot be aggregated without guessing."""


@dataclass(frozen=True, slots=True)
class SessionSNRCell:
    """One group x session x ROI grand-average curve."""

    condition: str
    group_id: str
    group_label: str
    session_id: str
    session_label: str
    visit_index: int
    roi: str
    plotted_values: tuple[float | None, ...]
    participant_n_by_frequency: tuple[int, ...]
    participant_ids: tuple[str, ...]
    recording_ids: tuple[str, ...]

    @property
    def participant_n_roi(self) -> int:
        return len(self.participant_ids)


@dataclass(frozen=True, slots=True)
class PairedSessionDifferenceCurve:
    """Within-participant comparison-minus-reference SNR curve for one group."""

    condition: str
    group_id: str
    group_label: str
    reference_session_id: str
    reference_session_label: str
    comparison_session_id: str
    comparison_session_label: str
    roi: str
    plotted_values: tuple[float | None, ...]
    paired_n_by_frequency: tuple[int, ...]
    participant_ids: tuple[str, ...]

    @property
    def paired_n_roi(self) -> int:
        return len(self.participant_ids)


@dataclass(frozen=True, slots=True)
class SessionSNRAggregation:
    """Session-aware SNR cells and optional paired difference curves."""

    condition: str
    frequency_count: int
    group_ids: tuple[str, ...]
    session_ids: tuple[str, ...]
    cells: tuple[SessionSNRCell, ...]
    paired_differences: tuple[PairedSessionDifferenceCurve, ...]
    reference_session_id: str | None = None
    comparison_session_id: str | None = None

    def cell(self, group_id: str, session_id: str, roi: str) -> SessionSNRCell:
        """Return one exact cell or raise ``KeyError``."""

        key = (str(group_id).casefold(), str(session_id).casefold(), str(roi))
        for cell in self.cells:
            candidate = (
                cell.group_id.casefold(),
                cell.session_id.casefold(),
                cell.roi,
            )
            if candidate == key:
                return cell
        raise KeyError((group_id, session_id, roi))

    def paired_difference(
        self,
        group_id: str,
        roi: str,
    ) -> PairedSessionDifferenceCurve:
        """Return one group/ROI paired difference curve or raise ``KeyError``."""

        key = (str(group_id).casefold(), str(roi))
        for curve in self.paired_differences:
            if (curve.group_id.casefold(), curve.roi) == key:
                return curve
        raise KeyError((group_id, roi))


@dataclass(frozen=True, slots=True)
class _RecordingIdentity:
    participant_id: str
    recording_id: str
    condition: str
    group_id: str
    group_label: str
    session_id: str
    session_label: str
    visit_index: int


def _required_text(record: object, field: str) -> str:
    value = str(getattr(record, field, None) or "").strip()
    if value:
        return value
    path = getattr(record, "path", None)
    suffix = f" for {path}" if path is not None else ""
    raise RepeatedSessionSNRIdentityError(f"Repeated-session SNR requires canonical {field}{suffix}.")


def _required_visit_index(record: object) -> int:
    raw_value = getattr(record, "visit_index", None)
    if isinstance(raw_value, bool):
        raw_value = None
    try:
        numeric = float(raw_value)
    except (TypeError, ValueError):
        numeric = float("nan")
    if math.isfinite(numeric) and numeric >= 1 and numeric.is_integer():
        return int(numeric)
    path = getattr(record, "path", None)
    suffix = f" for {path}" if path is not None else ""
    raise RepeatedSessionSNRIdentityError(f"Repeated-session SNR requires a positive canonical visit_index{suffix}.")


def _normalize_identities(
    workbook_records: Iterable[object],
    *,
    condition: str,
) -> tuple[_RecordingIdentity, ...]:
    condition_key = str(condition).strip().casefold()
    if not condition_key:
        raise RepeatedSessionSNRIdentityError("Repeated-session SNR requires one task condition.")

    identities: list[_RecordingIdentity] = []
    for record in workbook_records:
        record_condition = str(getattr(record, "condition", "") or "").strip()
        if record_condition.casefold() != condition_key:
            continue
        group_id = _required_text(record, "group_id")
        identity = _RecordingIdentity(
            participant_id=_required_text(record, "participant_id"),
            recording_id=_required_text(record, "recording_id"),
            condition=record_condition,
            group_id=group_id,
            group_label=str(getattr(record, "group_label", None) or "").strip() or group_id,
            session_id=_required_text(record, "session_id"),
            session_label=_required_text(record, "session_label"),
            visit_index=_required_visit_index(record),
        )
        identities.append(identity)
    if not identities:
        raise RepeatedSessionSNRIdentityError(
            f"No canonical repeated-session workbooks matched condition {condition!r}."
        )

    recording_ids: dict[str, str] = {}
    participant_sessions: dict[tuple[str, str], str] = {}
    participant_groups: dict[str, str] = {}
    session_metadata: dict[str, tuple[str, int]] = {}
    visit_sessions: dict[int, str] = {}
    group_labels: dict[str, str] = {}
    canonical_spellings: dict[tuple[str, str], str] = {}
    for identity in identities:
        for noun, value in (
            ("participant_id", identity.participant_id),
            ("group_id", identity.group_id),
            ("session_id", identity.session_id),
        ):
            spelling_key = (noun, value.casefold())
            prior_spelling = canonical_spellings.setdefault(spelling_key, value)
            if prior_spelling != value:
                raise RepeatedSessionSNRIdentityError(f"Canonical {noun} {value!r} has inconsistent spelling.")
        recording_key = identity.recording_id.casefold()
        if recording_key in recording_ids:
            raise RepeatedSessionSNRIdentityError(
                "Repeated-session SNR received duplicate recording_id "
                f"{identity.recording_id!r} for condition {identity.condition!r}."
            )
        recording_ids[recording_key] = identity.recording_id

        participant_key = identity.participant_id.casefold()
        session_key = identity.session_id.casefold()
        participant_session_key = (participant_key, session_key)
        if participant_session_key in participant_sessions:
            raise RepeatedSessionSNRIdentityError(
                f"Participant {identity.participant_id!r} has more than one recording "
                f"for session {identity.session_id!r}."
            )
        participant_sessions[participant_session_key] = identity.recording_id

        prior_group = participant_groups.setdefault(participant_key, identity.group_id)
        if prior_group.casefold() != identity.group_id.casefold():
            raise RepeatedSessionSNRIdentityError(
                f"Participant {identity.participant_id!r} changes canonical group between sessions."
            )
        prior_session = session_metadata.setdefault(
            session_key,
            (identity.session_label, identity.visit_index),
        )
        if prior_session != (identity.session_label, identity.visit_index):
            raise RepeatedSessionSNRIdentityError(
                f"Session {identity.session_id!r} has inconsistent label or visit order."
            )
        prior_visit_session = visit_sessions.setdefault(
            identity.visit_index,
            session_key,
        )
        if prior_visit_session != session_key:
            raise RepeatedSessionSNRIdentityError("Distinct canonical sessions cannot share one visit_index.")
        prior_label = group_labels.setdefault(identity.group_id.casefold(), identity.group_label)
        if prior_label != identity.group_label:
            raise RepeatedSessionSNRIdentityError(f"Group {identity.group_id!r} has inconsistent display labels.")
    return tuple(identities)


def _number(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _normalized_curve(values: Sequence[object], *, width: int) -> tuple[float | None, ...]:
    if len(values) != width:
        raise RepeatedSessionSNRDataError("Repeated-session SNR curves must share one exact frequency grid.")
    return tuple(_number(value) for value in values)


def _mean_curve(
    rows: Sequence[Sequence[float | None]],
    *,
    width: int,
) -> tuple[tuple[float | None, ...], tuple[int, ...]]:
    means: list[float | None] = []
    counts: list[int] = []
    for index in range(width):
        finite = [float(row[index]) for row in rows if index < len(row) and row[index] is not None]
        counts.append(len(finite))
        means.append(sum(finite) / len(finite) if finite else None)
    return tuple(means), tuple(counts)


def _ordered_groups(identities: Sequence[_RecordingIdentity]) -> tuple[str, ...]:
    display: dict[str, str] = {}
    for identity in identities:
        display.setdefault(identity.group_id.casefold(), identity.group_id)
    return tuple(sorted(display.values(), key=str.casefold))


def _ordered_sessions(identities: Sequence[_RecordingIdentity]) -> tuple[str, ...]:
    metadata: dict[str, tuple[int, str]] = {}
    for identity in identities:
        metadata.setdefault(
            identity.session_id.casefold(),
            (identity.visit_index, identity.session_id),
        )
    return tuple(
        session_id
        for _visit, session_id in sorted(
            metadata.values(),
            key=lambda row: (row[0], row[1].casefold()),
        )
    )


def aggregate_repeated_session_snr(
    *,
    workbook_records: Iterable[object],
    curves_by_recording: Mapping[str, Mapping[str, Sequence[object]]],
    condition: str,
    roi_names: Iterable[str] | None = None,
    session_pair: tuple[str, str] | None = None,
) -> SessionSNRAggregation:
    """Aggregate recording curves by group/session and preserve participant pairing.

    ``curves_by_recording`` must be keyed by canonical ``recording_id``. The
    helper never parses a workbook path or filename for participant or session
    identity. Paired curves are comparison minus reference and are averaged
    only after each participant's difference has been calculated.
    """

    identities = _normalize_identities(workbook_records, condition=condition)
    identity_by_recording = {identity.recording_id.casefold(): identity for identity in identities}
    curve_lookup: dict[str, Mapping[str, Sequence[object]]] = {}
    for recording_id, values in curves_by_recording.items():
        recording_key = str(recording_id).strip().casefold()
        if not recording_key:
            continue
        if recording_key in curve_lookup:
            raise RepeatedSessionSNRDataError(f"Duplicate curve key for canonical recording_id {recording_id!r}.")
        curve_lookup[recording_key] = values

    resolved_rois = tuple(dict.fromkeys(str(roi).strip() for roi in (roi_names or ()) if str(roi).strip()))
    if not resolved_rois:
        resolved_rois = tuple(
            sorted(
                {
                    str(roi)
                    for recording_key, values in curve_lookup.items()
                    if recording_key in identity_by_recording
                    for roi in values
                    if str(roi).strip()
                },
                key=str.casefold,
            )
        )
    if not resolved_rois:
        raise RepeatedSessionSNRDataError("Repeated-session SNR received no canonical recording ROI curves.")

    width: int | None = None
    normalized: dict[str, dict[str, tuple[float | None, ...]]] = {}
    for recording_key, identity in identity_by_recording.items():
        values_by_roi = curve_lookup.get(recording_key, {})
        for roi in resolved_rois:
            raw_values = values_by_roi.get(roi)
            if raw_values is None or len(raw_values) == 0:
                continue
            if width is None:
                width = len(raw_values)
            normalized.setdefault(recording_key, {})[roi] = _normalized_curve(
                raw_values,
                width=width,
            )
    if width is None or width <= 0:
        raise RepeatedSessionSNRDataError("Repeated-session SNR received no non-empty recording curves.")

    group_ids = _ordered_groups(identities)
    session_ids = _ordered_sessions(identities)
    group_metadata = {
        identity.group_id.casefold(): (identity.group_id, identity.group_label) for identity in identities
    }
    session_metadata = {
        identity.session_id.casefold(): (
            identity.session_id,
            identity.session_label,
            identity.visit_index,
        )
        for identity in identities
    }

    cells: list[SessionSNRCell] = []
    for group_id in group_ids:
        for session_id in session_ids:
            matching = [
                identity
                for identity in identities
                if identity.group_id.casefold() == group_id.casefold()
                and identity.session_id.casefold() == session_id.casefold()
            ]
            for roi in resolved_rois:
                rows: list[tuple[float | None, ...]] = []
                participant_ids: list[str] = []
                recording_ids: list[str] = []
                for identity in matching:
                    row = normalized.get(identity.recording_id.casefold(), {}).get(roi)
                    if row is None or not any(value is not None for value in row):
                        continue
                    rows.append(row)
                    participant_ids.append(identity.participant_id)
                    recording_ids.append(identity.recording_id)
                values, counts = _mean_curve(rows, width=width)
                canonical_session = session_metadata[session_id.casefold()]
                cells.append(
                    SessionSNRCell(
                        condition=identities[0].condition,
                        group_id=group_metadata[group_id.casefold()][0],
                        group_label=group_metadata[group_id.casefold()][1],
                        session_id=canonical_session[0],
                        session_label=canonical_session[1],
                        visit_index=canonical_session[2],
                        roi=roi,
                        plotted_values=values,
                        participant_n_by_frequency=counts,
                        participant_ids=tuple(sorted(participant_ids, key=str.casefold)),
                        recording_ids=tuple(sorted(recording_ids, key=str.casefold)),
                    )
                )

    if session_pair is None and len(session_ids) == 2:
        session_pair = (session_ids[0], session_ids[1])
    paired: list[PairedSessionDifferenceCurve] = []
    reference_id: str | None = None
    comparison_id: str | None = None
    if session_pair is not None:
        requested = tuple(str(value).strip() for value in session_pair)
        if len(requested) != 2 or not all(requested):
            raise RepeatedSessionSNRIdentityError("session_pair must contain reference and comparison session IDs.")
        observed_by_key = {value.casefold(): value for value in session_ids}
        if any(value.casefold() not in observed_by_key for value in requested):
            raise RepeatedSessionSNRIdentityError(
                "session_pair contains a session outside the canonical workbook cohort."
            )
        reference_id = observed_by_key[requested[0].casefold()]
        comparison_id = observed_by_key[requested[1].casefold()]
        if reference_id.casefold() == comparison_id.casefold():
            raise RepeatedSessionSNRIdentityError("session_pair must contain two distinct session IDs.")
        reference_meta = session_metadata[reference_id.casefold()]
        comparison_meta = session_metadata[comparison_id.casefold()]

        by_participant_session = {
            (identity.participant_id.casefold(), identity.session_id.casefold()): identity for identity in identities
        }
        for group_id in group_ids:
            participants = sorted(
                {
                    identity.participant_id
                    for identity in identities
                    if identity.group_id.casefold() == group_id.casefold()
                },
                key=str.casefold,
            )
            for roi in resolved_rois:
                difference_rows: list[tuple[float | None, ...]] = []
                paired_participants: list[str] = []
                for participant_id in participants:
                    participant_key = participant_id.casefold()
                    reference = by_participant_session.get((participant_key, reference_id.casefold()))
                    comparison = by_participant_session.get((participant_key, comparison_id.casefold()))
                    if reference is None or comparison is None:
                        continue
                    reference_values = normalized.get(reference.recording_id.casefold(), {}).get(roi)
                    comparison_values = normalized.get(comparison.recording_id.casefold(), {}).get(roi)
                    if reference_values is None or comparison_values is None:
                        continue
                    differences = tuple(
                        (
                            comparison_value - reference_value
                            if comparison_value is not None and reference_value is not None
                            else None
                        )
                        for reference_value, comparison_value in zip(
                            reference_values,
                            comparison_values,
                            strict=True,
                        )
                    )
                    if not any(value is not None for value in differences):
                        continue
                    difference_rows.append(differences)
                    paired_participants.append(participant_id)
                values, counts = _mean_curve(difference_rows, width=width)
                paired.append(
                    PairedSessionDifferenceCurve(
                        condition=identities[0].condition,
                        group_id=group_metadata[group_id.casefold()][0],
                        group_label=group_metadata[group_id.casefold()][1],
                        reference_session_id=reference_meta[0],
                        reference_session_label=reference_meta[1],
                        comparison_session_id=comparison_meta[0],
                        comparison_session_label=comparison_meta[1],
                        roi=roi,
                        plotted_values=values,
                        paired_n_by_frequency=counts,
                        participant_ids=tuple(paired_participants),
                    )
                )

    return SessionSNRAggregation(
        condition=identities[0].condition,
        frequency_count=width,
        group_ids=group_ids,
        session_ids=session_ids,
        cells=tuple(cells),
        paired_differences=tuple(paired),
        reference_session_id=reference_id,
        comparison_session_id=comparison_id,
    )


__all__ = [
    "PairedSessionDifferenceCurve",
    "RepeatedSessionSNRDataError",
    "RepeatedSessionSNRIdentityError",
    "SessionSNRAggregation",
    "SessionSNRCell",
    "aggregate_repeated_session_snr",
]

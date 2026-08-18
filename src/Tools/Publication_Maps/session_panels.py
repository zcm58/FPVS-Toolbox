"""Pure repeated-session scalp-map aggregation and panel preparation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import math
from pathlib import Path

import numpy as np
import pandas as pd

from Tools.Publication_Maps.models import PublicationMetric


class RepeatedSessionMapIdentityError(ValueError):
    """Raised when canonical recording/session identity is incomplete or unsafe."""


class RepeatedSessionMapDataError(ValueError):
    """Raised when repeated-session map values cannot be aggregated safely."""


@dataclass(frozen=True, slots=True)
class SessionMapElectrodeValue:
    """One electrode value in a group x session panel."""

    electrode: str
    aggregate_value: float | None
    render_value: float | None
    valid_subject_count: int
    is_montage_electrode: bool


@dataclass(frozen=True, slots=True)
class SessionMapPanel:
    """One descriptive group x session scalp-map panel."""

    condition: str
    metric: PublicationMetric
    group_id: str
    group_label: str
    session_id: str
    session_label: str
    visit_index: int
    participant_ids: tuple[str, ...]
    recording_ids: tuple[str, ...]
    values: tuple[SessionMapElectrodeValue, ...]

    @property
    def participant_n(self) -> int:
        return len(self.participant_ids)


@dataclass(frozen=True, slots=True)
class PairedSessionMapElectrodeValue:
    """One electrode's mean within-participant session difference."""

    electrode: str
    aggregate_difference: float | None
    paired_subject_count: int
    is_montage_electrode: bool


@dataclass(frozen=True, slots=True)
class PairedSessionDifferenceMap:
    """Comparison-minus-reference map computed before participant averaging."""

    condition: str
    metric: PublicationMetric
    group_id: str
    group_label: str
    reference_session_id: str
    reference_session_label: str
    comparison_session_id: str
    comparison_session_label: str
    participant_ids: tuple[str, ...]
    values: tuple[PairedSessionMapElectrodeValue, ...]

    @property
    def paired_n(self) -> int:
        return len(self.participant_ids)


@dataclass(frozen=True, slots=True)
class SessionMapPanelSet:
    """A 2x2 group-by-session panel grid with shared color-scale inputs."""

    condition: str
    metric: PublicationMetric
    group_ids: tuple[str, str]
    session_ids: tuple[str, str]
    panels: tuple[SessionMapPanel, ...]
    common_vmin: float
    common_vmax: float
    paired_differences: tuple[PairedSessionDifferenceMap, ...]
    difference_vmin: float | None
    difference_vmax: float | None

    def panel(self, group_id: str, session_id: str) -> SessionMapPanel:
        """Return one exact group/session panel or raise ``KeyError``."""

        key = (str(group_id).casefold(), str(session_id).casefold())
        for panel in self.panels:
            if (panel.group_id.casefold(), panel.session_id.casefold()) == key:
                return panel
        raise KeyError((group_id, session_id))

    def paired_difference(self, group_id: str) -> PairedSessionDifferenceMap:
        """Return one group's paired difference map or raise ``KeyError``."""

        key = str(group_id).casefold()
        for panel in self.paired_differences:
            if panel.group_id.casefold() == key:
                return panel
        raise KeyError(group_id)


@dataclass(frozen=True, slots=True)
class _RecordingIdentity:
    path: Path
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
    raise RepeatedSessionMapIdentityError(f"Repeated-session Scalp Maps requires canonical {field}{suffix}.")


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
    raise RepeatedSessionMapIdentityError(
        f"Repeated-session Scalp Maps requires a positive canonical visit_index{suffix}."
    )


def _resolved_path(value: object) -> Path:
    try:
        return Path(value).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise RepeatedSessionMapIdentityError(
            "Repeated-session Scalp Maps received an invalid canonical workbook path."
        ) from exc


def _normalize_identities(
    workbook_records: Iterable[object],
    *,
    condition: str,
) -> tuple[_RecordingIdentity, ...]:
    condition_key = str(condition).strip().casefold()
    if not condition_key:
        raise RepeatedSessionMapIdentityError("Repeated-session Scalp Maps requires one task condition.")

    identities: list[_RecordingIdentity] = []
    for record in workbook_records:
        record_condition = str(getattr(record, "condition", "") or "").strip()
        if record_condition.casefold() != condition_key:
            continue
        group_id = _required_text(record, "group_id")
        identities.append(
            _RecordingIdentity(
                path=_resolved_path(getattr(record, "path", None)),
                participant_id=_required_text(record, "participant_id"),
                recording_id=_required_text(record, "recording_id"),
                condition=record_condition,
                group_id=group_id,
                group_label=str(getattr(record, "group_label", None) or "").strip() or group_id,
                session_id=_required_text(record, "session_id"),
                session_label=_required_text(record, "session_label"),
                visit_index=_required_visit_index(record),
            )
        )
    if not identities:
        raise RepeatedSessionMapIdentityError(
            f"No canonical repeated-session workbooks matched condition {condition!r}."
        )

    paths: set[Path] = set()
    recording_ids: set[str] = set()
    participant_sessions: set[tuple[str, str]] = set()
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
                raise RepeatedSessionMapIdentityError(f"Canonical {noun} {value!r} has inconsistent spelling.")
        if identity.path in paths:
            raise RepeatedSessionMapIdentityError(
                f"Canonical workbook path is assigned more than once: {identity.path}"
            )
        paths.add(identity.path)
        recording_key = identity.recording_id.casefold()
        if recording_key in recording_ids:
            raise RepeatedSessionMapIdentityError(
                f"Duplicate recording_id {identity.recording_id!r} for condition {identity.condition!r}."
            )
        recording_ids.add(recording_key)

        participant_key = identity.participant_id.casefold()
        participant_session = (participant_key, identity.session_id.casefold())
        if participant_session in participant_sessions:
            raise RepeatedSessionMapIdentityError(
                f"Participant {identity.participant_id!r} has more than one recording "
                f"for session {identity.session_id!r}."
            )
        participant_sessions.add(participant_session)
        prior_group = participant_groups.setdefault(participant_key, identity.group_id)
        if prior_group.casefold() != identity.group_id.casefold():
            raise RepeatedSessionMapIdentityError(
                f"Participant {identity.participant_id!r} changes canonical group between sessions."
            )
        prior_session = session_metadata.setdefault(
            identity.session_id.casefold(),
            (identity.session_label, identity.visit_index),
        )
        if prior_session != (identity.session_label, identity.visit_index):
            raise RepeatedSessionMapIdentityError(
                f"Session {identity.session_id!r} has inconsistent label or visit order."
            )
        prior_visit_session = visit_sessions.setdefault(
            identity.visit_index,
            identity.session_id.casefold(),
        )
        if prior_visit_session != identity.session_id.casefold():
            raise RepeatedSessionMapIdentityError("Distinct canonical sessions cannot share one visit_index.")
        prior_label = group_labels.setdefault(identity.group_id.casefold(), identity.group_label)
        if prior_label != identity.group_label:
            raise RepeatedSessionMapIdentityError(f"Group {identity.group_id!r} has inconsistent display labels.")
    return tuple(identities)


def _metric(value: PublicationMetric | str) -> PublicationMetric:
    try:
        return value if isinstance(value, PublicationMetric) else PublicationMetric(str(value))
    except ValueError as exc:
        raise RepeatedSessionMapDataError(f"Unsupported repeated-session scalp-map metric: {value!r}.") from exc


def _canonical_harmonics(values: Sequence[float]) -> tuple[float, ...]:
    harmonics: list[float] = []
    for raw_value in values:
        try:
            value = round(float(raw_value), 4)
        except (TypeError, ValueError) as exc:
            raise RepeatedSessionMapDataError("Repeated-session Scalp Maps received an invalid harmonic.") from exc
        if not math.isfinite(value):
            raise RepeatedSessionMapDataError("Repeated-session Scalp Maps received a non-finite harmonic.")
        harmonics.append(value)
    if not harmonics:
        raise RepeatedSessionMapDataError("Repeated-session Scalp Maps requires the canonical harmonic list.")
    if len(set(harmonics)) != len(harmonics):
        raise RepeatedSessionMapDataError("Repeated-session Scalp Maps requires unique canonical harmonics.")
    return tuple(harmonics)


def _exact_pair(
    requested: Sequence[str] | None,
    observed: Sequence[str],
    *,
    noun: str,
) -> tuple[str, str]:
    observed_by_key = {value.casefold(): value for value in observed}
    if requested is None:
        values = tuple(observed)
    else:
        values = tuple(str(value).strip() for value in requested if str(value).strip())
    if len(values) != 2 or len({value.casefold() for value in values}) != 2:
        raise RepeatedSessionMapIdentityError(f"A repeated-session 2x2 Scalp Maps view requires exactly two {noun}.")
    unknown = [value for value in values if value.casefold() not in observed_by_key]
    if unknown:
        raise RepeatedSessionMapIdentityError(f"Unknown canonical {noun.rstrip('s')}(s): {', '.join(unknown)}.")
    return (
        observed_by_key[values[0].casefold()],
        observed_by_key[values[1].casefold()],
    )


def _finite_mean(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    return float(finite.mean()) if len(finite) else float("nan")


def _finite_count(values: pd.Series) -> int:
    numeric = pd.to_numeric(values, errors="coerce")
    return int(np.isfinite(numeric).sum())


def _recording_metric_value(
    values: pd.Series,
    *,
    metric: PublicationMetric,
    harmonic_count: int,
) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric[np.isfinite(numeric)]
    if metric is PublicationMetric.Z_SCORE:
        if harmonic_count <= 0 or len(finite) != harmonic_count:
            return float("nan")
        return float(finite.sum() / np.sqrt(float(harmonic_count)))
    if not len(finite):
        return float("nan")
    if metric is PublicationMetric.BCA:
        return float(finite.sum())
    return float(finite.mean())


def _finite_or_none(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _identity_frame(
    long_values: pd.DataFrame,
    identities: Sequence[_RecordingIdentity],
    *,
    condition: str,
    metric: PublicationMetric,
    selected_harmonics_hz: tuple[float, ...],
) -> pd.DataFrame:
    required = {
        "condition",
        "workbook_path",
        "subject_id",
        "electrode",
        "metric",
        "harmonic_hz",
        "value",
    }
    missing = sorted(required - set(long_values.columns))
    if missing:
        raise RepeatedSessionMapDataError(
            "Repeated-session Scalp Maps input is missing column(s): " + ", ".join(missing)
        )
    selected = long_values.loc[
        long_values["condition"].astype(str).str.casefold().eq(condition.casefold())
        & long_values["metric"].astype(str).eq(metric.value)
    ].copy()
    if selected.empty:
        raise RepeatedSessionMapDataError(f"No {metric.display_name} rows matched condition {condition!r}.")
    harmonic_values = pd.to_numeric(selected["harmonic_hz"], errors="coerce").round(4)
    selected = selected.loc[harmonic_values.isin(selected_harmonics_hz)].copy()
    selected["harmonic_hz"] = harmonic_values.loc[selected.index]
    if selected.empty:
        raise RepeatedSessionMapDataError("No rows matched the exact canonical harmonic list.")

    by_path = {identity.path: identity for identity in identities}
    identity_rows: list[dict[str, object]] = []
    for row in selected.to_dict(orient="records"):
        path = _resolved_path(row.get("workbook_path"))
        identity = by_path.get(path)
        if identity is None:
            raise RepeatedSessionMapIdentityError(
                f"Scalp-map values contain a workbook without canonical repeated-session identity: {path}"
            )
        if str(row.get("subject_id") or "").strip().casefold() != identity.participant_id.casefold():
            raise RepeatedSessionMapIdentityError(
                f"Workbook participant identity does not match canonical recording {identity.recording_id!r}."
            )
        raw_group = row.get("group_id")
        if pd.notna(raw_group) and str(raw_group).strip():
            if str(raw_group).strip().casefold() != identity.group_id.casefold():
                raise RepeatedSessionMapIdentityError(
                    f"Workbook group identity does not match canonical recording {identity.recording_id!r}."
                )
        identity_rows.append(
            {
                **row,
                "recording_id": identity.recording_id,
                "participant_id": identity.participant_id,
                "group_id": identity.group_id,
                "group_label": identity.group_label,
                "session_id": identity.session_id,
                "session_label": identity.session_label,
                "visit_index": identity.visit_index,
            }
        )
    frame = pd.DataFrame(identity_rows)
    duplicate_columns = ["recording_id", "electrode", "harmonic_hz"]
    duplicates = frame.duplicated(duplicate_columns, keep=False)
    if duplicates.any():
        duplicate = frame.loc[duplicates, duplicate_columns].iloc[0].to_dict()
        raise RepeatedSessionMapDataError(
            f"Repeated-session Scalp Maps received duplicate recording/electrode/harmonic rows: {duplicate}."
        )
    if "is_montage_electrode" not in frame.columns:
        frame["is_montage_electrode"] = True
    return frame


def _recording_values(
    frame: pd.DataFrame,
    *,
    metric: PublicationMetric,
    harmonic_count: int,
) -> pd.DataFrame:
    keys = [
        "participant_id",
        "recording_id",
        "group_id",
        "group_label",
        "session_id",
        "session_label",
        "visit_index",
        "electrode",
        "is_montage_electrode",
    ]
    grouped = (
        frame.groupby(keys, dropna=False)["value"]
        .agg(
            lambda values: _recording_metric_value(
                values,
                metric=metric,
                harmonic_count=harmonic_count,
            )
        )
        .reset_index(name="recording_value")
    )
    return grouped


def _panel_values(
    recording_values: pd.DataFrame,
    *,
    metric: PublicationMetric,
    group_id: str,
    session_id: str,
) -> tuple[
    tuple[SessionMapElectrodeValue, ...],
    tuple[str, ...],
    tuple[str, ...],
]:
    selected = recording_values.loc[
        recording_values["group_id"].astype(str).str.casefold().eq(group_id.casefold())
        & recording_values["session_id"].astype(str).str.casefold().eq(session_id.casefold())
    ]
    participants = tuple(
        sorted(
            {
                str(row.participant_id)
                for row in selected.itertuples(index=False)
                if _finite_or_none(row.recording_value) is not None
            },
            key=str.casefold,
        )
    )
    recordings = tuple(
        sorted(
            {
                str(row.recording_id)
                for row in selected.itertuples(index=False)
                if _finite_or_none(row.recording_value) is not None
            },
            key=str.casefold,
        )
    )
    if selected.empty:
        return (), participants, recordings
    grouped = (
        selected.groupby(["electrode", "is_montage_electrode"], dropna=False)["recording_value"]
        .agg(aggregate_value=_finite_mean, valid_subject_count=_finite_count)
        .reset_index()
    )
    values: list[SessionMapElectrodeValue] = []
    for row in grouped.itertuples(index=False):
        aggregate = _finite_or_none(row.aggregate_value)
        render = max(0.0, aggregate) if aggregate is not None and metric is PublicationMetric.BCA else aggregate
        values.append(
            SessionMapElectrodeValue(
                electrode=str(row.electrode),
                aggregate_value=aggregate,
                render_value=render,
                valid_subject_count=int(row.valid_subject_count),
                is_montage_electrode=bool(row.is_montage_electrode),
            )
        )
    return tuple(values), participants, recordings


def _paired_difference_map(
    recording_values: pd.DataFrame,
    *,
    condition: str,
    metric: PublicationMetric,
    group_id: str,
    group_label: str,
    reference: tuple[str, str],
    comparison: tuple[str, str],
) -> PairedSessionDifferenceMap:
    selected = recording_values.loc[
        recording_values["group_id"].astype(str).str.casefold().eq(group_id.casefold())
        & recording_values["session_id"]
        .astype(str)
        .str.casefold()
        .isin({reference[0].casefold(), comparison[0].casefold()})
    ].copy()
    index_columns = ["participant_id", "electrode", "is_montage_electrode"]
    wide = selected.pivot(
        index=index_columns,
        columns="session_id",
        values="recording_value",
    )
    session_columns = {str(column).casefold(): column for column in wide.columns}
    if reference[0].casefold() not in session_columns:
        wide[reference[0]] = np.nan
        session_columns[reference[0].casefold()] = reference[0]
    if comparison[0].casefold() not in session_columns:
        wide[comparison[0]] = np.nan
        session_columns[comparison[0].casefold()] = comparison[0]
    reference_values = pd.to_numeric(wide[session_columns[reference[0].casefold()]], errors="coerce")
    comparison_values = pd.to_numeric(wide[session_columns[comparison[0].casefold()]], errors="coerce")
    wide["difference"] = comparison_values - reference_values
    differences = wide.reset_index()
    participants = tuple(
        sorted(
            {
                str(row.participant_id)
                for row in differences.itertuples(index=False)
                if _finite_or_none(row.difference) is not None
            },
            key=str.casefold,
        )
    )
    grouped = (
        differences.groupby(["electrode", "is_montage_electrode"], dropna=False)["difference"]
        .agg(aggregate_difference=_finite_mean, paired_subject_count=_finite_count)
        .reset_index()
    )
    values = tuple(
        PairedSessionMapElectrodeValue(
            electrode=str(row.electrode),
            aggregate_difference=_finite_or_none(row.aggregate_difference),
            paired_subject_count=int(row.paired_subject_count),
            is_montage_electrode=bool(row.is_montage_electrode),
        )
        for row in grouped.itertuples(index=False)
    )
    return PairedSessionDifferenceMap(
        condition=condition,
        metric=metric,
        group_id=group_id,
        group_label=group_label,
        reference_session_id=reference[0],
        reference_session_label=reference[1],
        comparison_session_id=comparison[0],
        comparison_session_label=comparison[1],
        participant_ids=participants,
        values=values,
    )


def build_repeated_session_map_panels(
    *,
    long_values: pd.DataFrame,
    workbook_records: Iterable[object],
    condition: str,
    metric: PublicationMetric | str,
    selected_harmonics_hz: Sequence[float],
    group_ids: Sequence[str] | None = None,
    session_ids: Sequence[str] | None = None,
) -> SessionMapPanelSet:
    """Build a canonical 2x2 group/session grid and paired session differences.

    Session identity is joined by the exact canonical workbook path carried by
    ``workbook_records``. No directory or filename token is interpreted as
    participant, group, recording, or session identity.
    """

    resolved_condition = str(condition).strip()
    identities = _normalize_identities(
        workbook_records,
        condition=resolved_condition,
    )
    resolved_metric = _metric(metric)
    canonical_harmonics = _canonical_harmonics(selected_harmonics_hz)
    harmonic_count = len(canonical_harmonics)

    group_metadata = {
        identity.group_id.casefold(): (identity.group_id, identity.group_label) for identity in identities
    }
    observed_groups = tuple(
        sorted(
            (value[0] for value in group_metadata.values()),
            key=str.casefold,
        )
    )
    session_metadata = {
        identity.session_id.casefold(): (
            identity.visit_index,
            identity.session_id,
            identity.session_label,
        )
        for identity in identities
    }
    observed_sessions = tuple(
        row[1]
        for row in sorted(
            session_metadata.values(),
            key=lambda value: (value[0], value[1].casefold()),
        )
    )
    selected_groups = _exact_pair(group_ids, observed_groups, noun="groups")
    selected_sessions = _exact_pair(session_ids, observed_sessions, noun="sessions")

    selected_group_keys = {value.casefold() for value in selected_groups}
    selected_session_keys = {value.casefold() for value in selected_sessions}
    frame = _identity_frame(
        long_values,
        identities,
        condition=resolved_condition,
        metric=resolved_metric,
        selected_harmonics_hz=canonical_harmonics,
    )
    frame = frame.loc[
        frame["group_id"].astype(str).str.casefold().isin(selected_group_keys)
        & frame["session_id"].astype(str).str.casefold().isin(selected_session_keys)
    ].copy()
    if frame.empty:
        raise RepeatedSessionMapDataError("No canonical values remained for the requested group/session grid.")
    expected_recordings = {
        identity.recording_id.casefold(): identity.recording_id
        for identity in identities
        if identity.group_id.casefold() in selected_group_keys
        and identity.session_id.casefold() in selected_session_keys
    }
    observed_recordings = {str(value).casefold() for value in frame["recording_id"].unique()}
    missing_recordings = sorted(
        (recording_id for key, recording_id in expected_recordings.items() if key not in observed_recordings),
        key=str.casefold,
    )
    if missing_recordings:
        raise RepeatedSessionMapDataError(
            "Canonical recording(s) have no exact selected-harmonic map rows: " + ", ".join(missing_recordings)
        )
    recording_values = _recording_values(
        frame,
        metric=resolved_metric,
        harmonic_count=harmonic_count,
    )

    panels: list[SessionMapPanel] = []
    for group_id in selected_groups:
        for session_id in selected_sessions:
            values, participants, recordings = _panel_values(
                recording_values,
                metric=resolved_metric,
                group_id=group_id,
                session_id=session_id,
            )
            session = session_metadata[session_id.casefold()]
            group = group_metadata[group_id.casefold()]
            panels.append(
                SessionMapPanel(
                    condition=resolved_condition,
                    metric=resolved_metric,
                    group_id=group[0],
                    group_label=group[1],
                    session_id=session[1],
                    session_label=session[2],
                    visit_index=session[0],
                    participant_ids=participants,
                    recording_ids=recordings,
                    values=values,
                )
            )
    finite_panel_values = [
        value.render_value for panel in panels for value in panel.values if value.render_value is not None
    ]
    if not finite_panel_values:
        raise RepeatedSessionMapDataError("The requested repeated-session panel grid has no finite map values.")
    common_vmin = min(finite_panel_values)
    common_vmax = max(finite_panel_values)

    reference_id, comparison_id = selected_sessions
    reference = session_metadata[reference_id.casefold()]
    comparison = session_metadata[comparison_id.casefold()]
    paired = tuple(
        _paired_difference_map(
            recording_values,
            condition=resolved_condition,
            metric=resolved_metric,
            group_id=group_metadata[group_id.casefold()][0],
            group_label=group_metadata[group_id.casefold()][1],
            reference=(reference[1], reference[2]),
            comparison=(comparison[1], comparison[2]),
        )
        for group_id in selected_groups
    )
    finite_differences = [
        value.aggregate_difference
        for difference in paired
        for value in difference.values
        if value.aggregate_difference is not None
    ]
    if finite_differences:
        limit = max(abs(value) for value in finite_differences)
        difference_vmin: float | None = -limit
        difference_vmax: float | None = limit
    else:
        difference_vmin = None
        difference_vmax = None

    return SessionMapPanelSet(
        condition=resolved_condition,
        metric=resolved_metric,
        group_ids=selected_groups,
        session_ids=selected_sessions,
        panels=tuple(panels),
        common_vmin=common_vmin,
        common_vmax=common_vmax,
        paired_differences=paired,
        difference_vmin=difference_vmin,
        difference_vmax=difference_vmax,
    )


__all__ = [
    "PairedSessionDifferenceMap",
    "PairedSessionMapElectrodeValue",
    "RepeatedSessionMapDataError",
    "RepeatedSessionMapIdentityError",
    "SessionMapElectrodeValue",
    "SessionMapPanel",
    "SessionMapPanelSet",
    "build_repeated_session_map_panels",
]

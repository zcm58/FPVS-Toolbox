"""Preprocessing preflight QC scanning helpers."""

from __future__ import annotations

from collections import Counter, defaultdict
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import logging
from pathlib import Path
import tempfile
import threading
import time
from typing import Any, Callable, Iterator, Mapping, Sequence

import mne
import numpy as np

from Main_App.io import load_utils
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNELS,
    biosemi64_geometry_identity,
)
from Main_App.io.load_utils import BDF_RECORDING_NOT_STARTED_REASON, BdfPreflightInfo
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.preflight_qc_cache import (
    load_preflight_qc_cache,
    save_preflight_qc_cache,
)
from Main_App.processing.preflight_qc_plan import (
    PREFLIGHT_QC_BLOCK_DURATION_S,
    PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES,
    PREFLIGHT_QC_MAX_IO_READERS,
    PREFLIGHT_QC_MAX_SPECTRAL_WORKERS,
    PREFLIGHT_QC_MAX_WORKERS,
    PREFLIGHT_QC_METHOD_NAME,
    PREFLIGHT_QC_METHOD_VERSION,
    PREFLIGHT_QC_TRANSIENT_TAIL_POLICY,
    PREFLIGHT_QC_TRANSIENT_WINDOW_DURATION_S,
    PREFLIGHT_QC_TRANSIENT_WINDOW_HOP_S,
    ConditionQcSpan,
    plan_preflight_qc_events,
    resolve_preflight_spectral_bounds,
)
from Main_App.processing.preflight_qc_reuse import (
    load_occurrence_evidence,
    load_source_events,
    save_occurrence_evidence,
    save_source_events,
)
from Main_App.processing.analysis_spans import (
    restrict_source_analysis_span_plan_by_condition,
)
from Main_App.processing.fft_multinotch import (
    FFT_MULTINOTCH_HALF_WIDTH_HZ,
    FFT_MULTINOTCH_METHOD_VERSION,
)
from Main_App.processing.removed_electrode_detection import (
    manual_removed_electrodes_for_recording,
)
from Main_App.projects.frequency_protocol import (
    FrequencyProtocolError,
    normalize_frequency_protocol,
)
from Main_App.projects.experimental_qc_settings import (
    RawSpectralScreeningSettings,
    normalize_raw_spectral_screening_settings,
)
from Main_App.projects.preprocessing_settings import (
    is_participant_condition_excluded,
    is_recording_condition_excluded,
    normalize_manual_excluded_participant_conditions,
    normalize_manual_excluded_recording_conditions,
)
from Main_App.processing.raw_channel_qc import (
    CONDITION_RAW_CHANNEL_QC_METHOD_VERSION,
    SCALP_CHANNELS,
    ConditionRawChannelQCBlock,
    ConditionRawChannelQCCancelled,
    RawChannelQCConfig,
    _config_from_settings as _raw_channel_config_from_settings,
    combine_condition_raw_channel_qc_v2,
    evaluate_condition_raw_channel_qc_v2,
)
from Main_App.processing.raw_spectral_qc import (
    CONDITION_SPECTRAL_QC_METHOD_VERSION,
    RAW_SPECTRAL_QC_DISABLED_STATUS,
    ConditionSpectralQCCancelled,
    ConditionSpectralQCResult,
    condition_spectral_thresholds_from_project_settings,
    evaluate_condition_spectral_qc_v2,
)
from Main_App.processing.spectral_eligibility import (
    SPECTRAL_ELIGIBILITY_METHOD_VERSION,
)
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


ProgressCallback = Callable[[str, int, int], None]
CancelCallback = Callable[[], bool]
DetailProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class HeaderOnlyPreflight:
    """A BDF file that appears to contain only the BioSemi header."""

    path: Path
    participant_id: str
    info: BdfPreflightInfo
    group_id: str | None = None
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None


@dataclass(frozen=True)
class PreflightQcFileResult:
    """Pre-processing QC result for one raw file."""

    path: Path
    participant_id: str
    load_error: str | None
    raw_channel_qc: Mapping[str, object] | None
    raw_spectral_qc: Mapping[str, object] | None
    group_id: str | None = None
    condition_qc: Mapping[str, object] | None = None
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None

    @property
    def identity_id(self) -> str:
        """Return the recording key, with the legacy participant fallback."""

        return self.recording_id or self.participant_id

    @property
    def auto_removed_electrodes(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("channels_to_interpolate")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        manual_values = payload.get("manual_removed_channels")
        manual_keys = {
            str(value).strip().casefold()
            for value in (
                manual_values
                if isinstance(manual_values, Sequence)
                and not isinstance(manual_values, str)
                else ()
            )
            if str(value).strip()
        }
        return tuple(
            str(value)
            for value in values
            if str(value).strip()
            and str(value).strip().casefold() not in manual_keys
        )

    @property
    def high_amplitude_channels(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("high_amplitude_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def rare_burst_channels(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("rare_burst_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def spatial_outlier_channels(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("spatial_outlier_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def warning_rules(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("warning_rules")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())

    @staticmethod
    def _mapping_rows(
        payload: Mapping[str, object] | None,
        key: str,
    ) -> tuple[Mapping[str, object], ...]:
        values = (payload or {}).get(key)
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(value for value in values if isinstance(value, Mapping))

    @property
    def review_rules(self) -> tuple[str, ...]:
        payload = self.raw_channel_qc or {}
        values = payload.get("review_rules")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return self.warning_rules
        return tuple(str(value) for value in values if str(value).strip())

    @property
    def candidate_burden_findings(self) -> tuple[Mapping[str, object], ...]:
        return self._mapping_rows(self.raw_channel_qc, "candidate_burden_findings")

    @property
    def raw_amplitude_review_findings(self) -> tuple[Mapping[str, object], ...]:
        return self._mapping_rows(self.raw_channel_qc, "raw_amplitude_review_findings")

    @property
    def occurrence_review_findings(self) -> tuple[Mapping[str, object], ...]:
        return self._mapping_rows(self.raw_channel_qc, "occurrence_review_findings")

    @property
    def transient_review_findings(self) -> tuple[Mapping[str, object], ...]:
        return self._mapping_rows(self.raw_channel_qc, "transient_review_findings")

    @property
    def occurrence_evaluation_scope(self) -> tuple[Mapping[str, object], ...]:
        return self._mapping_rows(self.raw_channel_qc, "occurrence_evaluation_scope")

    @property
    def experimental_detector_evaluated(self) -> bool:
        payload = self.raw_channel_qc or {}
        detector = payload.get("experimental_removed_electrode_detector")
        return bool(
            isinstance(detector, Mapping)
            and detector.get("evaluation_status") == "evaluated"
        )

    @property
    def raw_qc_decision_review_required(self) -> bool:
        severe_amplitude = any(
            str(finding.get("severity") or "") == "severe_review"
            for finding in self.raw_amplitude_review_findings
        )
        return severe_amplitude or bool(self.candidate_burden_findings)

    @property
    def raw_qc_excluded(self) -> bool:
        payload = self.raw_channel_qc or {}
        return bool(payload.get("excluded"))

    @property
    def raw_qc_message(self) -> str:
        payload = self.raw_channel_qc or {}
        return str(payload.get("message") or "").strip()

    @property
    def raw_spectral_widespread(self) -> bool:
        payload = self.raw_spectral_qc or {}
        return bool(payload.get("widespread"))

    @property
    def raw_spectral_message(self) -> str:
        payload = self.raw_spectral_qc or {}
        return str(payload.get("message") or "").strip()

    @property
    def raw_spectral_evaluation_status(self) -> str:
        payload = self.raw_spectral_qc or {}
        return str(payload.get("evaluation_status") or "").strip()

    @property
    def raw_spectral_review_rows(self) -> tuple[Mapping[str, object], ...]:
        payload = self.raw_spectral_qc or {}
        values = payload.get("review_rows")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(value for value in values if isinstance(value, Mapping))

    @property
    def raw_spectral_flagged_channels(self) -> tuple[str, ...]:
        payload = self.raw_spectral_qc or {}
        values = payload.get("flagged_channels")
        if not isinstance(values, Sequence) or isinstance(values, str):
            return ()
        return tuple(str(value) for value in values if str(value).strip())


@dataclass(frozen=True)
class PreflightQcScan:
    """Full preflight scan output for GUI review."""

    results: tuple[PreflightQcFileResult, ...]
    cancelled: bool = False
    project_grid_observations: tuple[
        "PreflightConditionCropObservation", ...
    ] = ()
    oddball_frequency_hz: float | None = None
    frequency_protocol_fingerprint: str = ""

    @property
    def suggested_removed_electrodes(self) -> dict[str, list[str]]:
        suggestions: dict[str, list[str]] = {}
        for result in self.results:
            channels = list(dict.fromkeys(result.auto_removed_electrodes))
            if not channels:
                continue
            suggestions[result.identity_id] = channels
        return suggestions

    @property
    def hard_exclusion_candidates(self) -> tuple[PreflightQcFileResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.raw_qc_excluded
            or result.raw_qc_decision_review_required
        )

    @property
    def suspicious_results(self) -> tuple[PreflightQcFileResult, ...]:
        return tuple(
            result
            for result in self.results
            if result.load_error
            or result.review_rules
            or result.high_amplitude_channels
            or result.rare_burst_channels
            or result.spatial_outlier_channels
            or result.candidate_burden_findings
            or result.raw_amplitude_review_findings
            or result.occurrence_review_findings
            or result.transient_review_findings
            or any(
                row.get("evaluation_status") == "not_evaluated"
                for row in result.occurrence_evaluation_scope
            )
            or not result.experimental_detector_evaluated
            or result.raw_spectral_flagged_channels
            or bool(result.raw_spectral_review_rows)
            or result.raw_spectral_evaluation_status
            in {"not_performed_disabled", "not_evaluated"}
        )


@dataclass(frozen=True, slots=True)
class PreflightConditionCropObservation:
    """One raw participant-condition's planned locked FFT crop grid."""

    path: Path
    participant_id: str
    group_id: str | None
    condition_label: str
    condition_id: int
    repetition_count: int
    oddball_cycles: int | None
    duration_s: float | None
    issue: str | None
    already_excluded: bool = False
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None

    @property
    def pair_key(self) -> tuple[str, str]:
        identity = self.recording_id or self.participant_id
        return identity.casefold(), self.condition_label.casefold()

    @property
    def participant_pair_key(self) -> tuple[str, str]:
        return self.participant_id.casefold(), self.condition_label.casefold()

    @property
    def recording_pair_key(self) -> tuple[str, str] | None:
        if not self.recording_id:
            return None
        return self.recording_id.casefold(), self.condition_label.casefold()


@dataclass(frozen=True, slots=True)
class PreflightConditionCropGridAudit:
    """Strict-majority crop reference and condition-level review candidates."""

    observations: tuple[PreflightConditionCropObservation, ...]
    reference_oddball_cycles: int | None
    reference_support: int
    reference_total: int
    oddball_frequency_hz: float | None = None
    frequency_protocol_fingerprint: str = ""

    @property
    def reference_duration_s(self) -> float | None:
        if (
            self.reference_oddball_cycles is None
            or self.oddball_frequency_hz is None
        ):
            return None
        return self.reference_oddball_cycles / self.oddball_frequency_hz

    @property
    def review_candidates(self) -> tuple[PreflightConditionCropObservation, ...]:
        if self.reference_oddball_cycles is None:
            valid_grids = {
                observation.oddball_cycles
                for observation in self.observations
                if not observation.already_excluded
                and observation.issue is None
                and observation.oddball_cycles is not None
            }
            unresolved_conflict = len(valid_grids) > 1
        else:
            unresolved_conflict = False
        return tuple(
            observation
            for observation in self.observations
            if not observation.already_excluded
            and (
                observation.issue is not None
                or unresolved_conflict
                or (
                    self.reference_oddball_cycles is not None
                    and observation.oddball_cycles
                    != self.reference_oddball_cycles
                )
            )
        )

    @property
    def recommended_exclusions(
        self,
    ) -> tuple[PreflightConditionCropObservation, ...]:
        """Return invalid rows and strict-majority mismatches safe to precheck."""

        return tuple(
            observation
            for observation in self.observations
            if not observation.already_excluded
            and (
                observation.issue is not None
                or (
                    self.reference_oddball_cycles is not None
                    and observation.oddball_cycles
                    != self.reference_oddball_cycles
                )
            )
        )

    @property
    def has_unresolved_grid_conflict(self) -> bool:
        return (
            self.reference_oddball_cycles is None
            and len(
                {
                    observation.oddball_cycles
                    for observation in self.observations
                    if not observation.already_excluded
                    and observation.issue is None
                    and observation.oddball_cycles is not None
                }
            )
            > 1
        )

    def is_compatible_with_exclusions(
        self,
        exclusions: Mapping[str, Sequence[str]],
        *,
        recording_exclusions: Mapping[str, Sequence[str]] | None = None,
    ) -> bool:
        excluded_pairs = {
            (str(participant).strip().casefold(), str(condition).strip().casefold())
            for participant, conditions in exclusions.items()
            for condition in conditions
            if str(participant).strip() and str(condition).strip()
        }
        excluded_recording_pairs = {
            (str(recording).strip().casefold(), str(condition).strip().casefold())
            for recording, conditions in (recording_exclusions or {}).items()
            for condition in conditions
            if str(recording).strip() and str(condition).strip()
        }
        active = tuple(
            observation
            for observation in self.observations
            if observation.participant_pair_key not in excluded_pairs
            and (
                observation.recording_pair_key is None
                or observation.recording_pair_key not in excluded_recording_pairs
            )
        )
        if not active or any(observation.issue is not None for observation in active):
            return False
        return (
            len(
                {
                    observation.oddball_cycles
                    for observation in active
                    if observation.oddball_cycles is not None
                }
            )
            == 1
        )


def build_preflight_condition_crop_grid_audit(
    scan: PreflightQcScan,
    *,
    excluded_participant_conditions: Mapping[str, Sequence[str]] | None = None,
    excluded_participants: Sequence[str] = (),
    excluded_recording_conditions: Mapping[str, Sequence[str]] | None = None,
    excluded_recordings: Sequence[str] = (),
) -> PreflightConditionCropGridAudit:
    """Compare valid raw crop plans without changing locked crop arithmetic."""

    excluded_participant_keys = {
        str(participant).strip().casefold()
        for participant in excluded_participants
        if str(participant).strip()
    }
    excluded_pair_keys = {
        (str(participant).strip().casefold(), str(condition).strip().casefold())
        for participant, conditions in (
            excluded_participant_conditions or {}
        ).items()
        for condition in conditions
        if str(participant).strip() and str(condition).strip()
    }
    excluded_recording_keys = {
        str(recording).strip().casefold()
        for recording in excluded_recordings
        if str(recording).strip()
    }
    excluded_recording_pair_keys = {
        (str(recording).strip().casefold(), str(condition).strip().casefold())
        for recording, conditions in (excluded_recording_conditions or {}).items()
        for condition in conditions
        if str(recording).strip() and str(condition).strip()
    }
    observations: list[PreflightConditionCropObservation] = []
    for result in scan.results:
        if result.participant_id.casefold() in excluded_participant_keys:
            continue
        if result.recording_id and result.recording_id.casefold() in excluded_recording_keys:
            continue
        observations.extend(
            _condition_crop_observations(
                result,
                oddball_frequency_hz=scan.oddball_frequency_hz,
                excluded_pair_keys=excluded_pair_keys,
                excluded_recording_pair_keys=excluded_recording_pair_keys,
            )
        )
    current_pairs = {observation.pair_key for observation in observations}
    for project_observation in scan.project_grid_observations:
        if (
            project_observation.participant_id.casefold()
            in excluded_participant_keys
            or (
                project_observation.recording_id is not None
                and project_observation.recording_id.casefold()
                in excluded_recording_keys
            )
            or project_observation.pair_key in current_pairs
        ):
            continue
        observations.append(
            PreflightConditionCropObservation(
                path=project_observation.path,
                participant_id=project_observation.participant_id,
                group_id=project_observation.group_id,
                condition_label=project_observation.condition_label,
                condition_id=project_observation.condition_id,
                repetition_count=project_observation.repetition_count,
                oddball_cycles=project_observation.oddball_cycles,
                duration_s=project_observation.duration_s,
                issue=project_observation.issue,
                already_excluded=(
                    project_observation.participant_pair_key in excluded_pair_keys
                    or (
                        project_observation.recording_pair_key is not None
                        and project_observation.recording_pair_key
                        in excluded_recording_pair_keys
                    )
                ),
                recording_id=project_observation.recording_id,
                session_id=project_observation.session_id,
                session_label=project_observation.session_label,
                visit_index=project_observation.visit_index,
            )
        )
    observations.sort(
        key=lambda observation: (
            str(observation.group_id or "").casefold(),
            observation.participant_id.casefold(),
            observation.visit_index or 0,
            str(observation.recording_id or "").casefold(),
            observation.condition_id,
            observation.condition_label.casefold(),
        )
    )

    active_cycles = [
        int(observation.oddball_cycles)
        for observation in observations
        if not observation.already_excluded
        and observation.issue is None
        and observation.oddball_cycles is not None
    ]
    total = len(active_cycles)
    reference: int | None = None
    support = 0
    if total >= 2:
        counts = Counter(active_cycles)
        candidate, support = counts.most_common(1)[0]
        if support >= 2 and support * 2 > total:
            reference = int(candidate)
    return PreflightConditionCropGridAudit(
        observations=tuple(observations),
        reference_oddball_cycles=reference,
        reference_support=int(support),
        reference_total=total,
        oddball_frequency_hz=scan.oddball_frequency_hz,
        frequency_protocol_fingerprint=scan.frequency_protocol_fingerprint,
    )


def _condition_crop_observations(
    result: PreflightQcFileResult,
    *,
    oddball_frequency_hz: float | None,
    excluded_pair_keys: set[tuple[str, str]],
    excluded_recording_pair_keys: set[tuple[str, str]],
) -> list[PreflightConditionCropObservation]:
    condition_qc = result.condition_qc or {}
    event_plan = condition_qc.get("event_plan")
    if not isinstance(event_plan, Mapping):
        return []
    spans = event_plan.get("spans")
    if not isinstance(spans, Sequence) or isinstance(spans, (str, bytes)):
        return []
    try:
        sfreq = float(event_plan.get("sfreq"))
    except (TypeError, ValueError):
        return []
    if not np.isfinite(sfreq) or sfreq <= 0.0:
        return []

    grouped: dict[tuple[int, str], list[Mapping[str, object]]] = defaultdict(list)
    for raw_span in spans:
        if not isinstance(raw_span, Mapping):
            continue
        try:
            condition_id = int(raw_span.get("condition_id"))
        except (TypeError, ValueError):
            continue
        condition_label = str(raw_span.get("condition_label") or "").strip()
        if not condition_label:
            condition_label = str(condition_id)
        grouped[(condition_id, condition_label)].append(raw_span)

    observations: list[PreflightConditionCropObservation] = []
    for (condition_id, condition_label), condition_spans in grouped.items():
        lengths: list[int] = []
        issue: str | None = None
        for span in condition_spans:
            fallback_reason = str(
                span.get("spectral_fallback_reason") or ""
            ).strip()
            if fallback_reason:
                issue = f"Locked FFT crop unavailable: {fallback_reason}."
                break
            try:
                start = int(span.get("spectral_start_sample"))
                stop = int(span.get("spectral_stop_sample"))
            except (TypeError, ValueError):
                issue = "Locked FFT crop bounds are missing."
                break
            if stop <= start:
                issue = "Locked FFT crop bounds are empty."
                break
            lengths.append(stop - start)

        cycles: int | None = None
        duration_s: float | None = None
        if issue is None:
            if oddball_frequency_hz is None:
                issue = "The project oddball frequency is unavailable."
            elif not lengths:
                issue = "No locked FFT crop was planned."
            elif len(set(lengths)) != 1:
                issue = "Condition repetitions do not share one FFT crop length."
            else:
                duration_s = lengths[0] / sfreq
                raw_cycles = oddball_frequency_hz * duration_s
                rounded_cycles = int(round(raw_cycles))
                if rounded_cycles <= 0 or abs(raw_cycles - rounded_cycles) > 1e-6:
                    issue = "The planned FFT crop is not exactly oddball-bin locked."
                    duration_s = None
                else:
                    cycles = rounded_cycles

        participant_pair_key = (
            result.participant_id.casefold(),
            condition_label.casefold(),
        )
        recording_pair_key = (
            (result.recording_id.casefold(), condition_label.casefold())
            if result.recording_id
            else None
        )
        observations.append(
            PreflightConditionCropObservation(
                path=result.path,
                participant_id=result.participant_id,
                group_id=result.group_id,
                condition_label=condition_label,
                condition_id=condition_id,
                repetition_count=len(condition_spans),
                oddball_cycles=cycles,
                duration_s=duration_s,
                issue=issue,
                already_excluded=(
                    participant_pair_key in excluded_pair_keys
                    or (
                        recording_pair_key is not None
                        and recording_pair_key in excluded_recording_pair_keys
                    )
                ),
                recording_id=result.recording_id,
                session_id=result.session_id,
                session_label=result.session_label,
                visit_index=result.visit_index,
            )
        )
    return observations

def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except (OSError, RuntimeError, ValueError):
        return str(path).casefold()


def scan_recording_not_started_files(
    raw_file_infos: Sequence[RawFileInfo],
) -> tuple[HeaderOnlyPreflight, ...]:
    """Return files whose BDF header says no recording data were written."""

    flagged: list[HeaderOnlyPreflight] = []
    for info in raw_file_infos:
        preflight = load_utils.inspect_bdf_header(info.path)
        if not preflight or not preflight.recording_not_started:
            continue
        flagged.append(
            HeaderOnlyPreflight(
                path=Path(info.path),
                participant_id=str(info.subject_id),
                info=preflight,
                group_id=str(info.group).strip() if info.group else None,
                recording_id=str(info.recording_id).strip() if info.recording_id else None,
                session_id=str(info.session_id).strip() if info.session_id else None,
                session_label=(
                    str(info.session_label).strip() if info.session_label else None
                ),
                visit_index=info.visit_index,
            )
        )
    return tuple(flagged)


class _LogShim:
    def log(self, message: str, *args: Any, **kwargs: Any) -> None:
        _ = args, kwargs
        logger.debug("preflight_qc_loader: %s", message)


def _load_raw_for_preflight(
    file_path: Path,
    settings: Mapping[str, Any],
) -> Any:
    ref_ch1, ref_ch2 = _configured_ref_pair(settings)
    return load_utils.load_eeg_file(
        _LogShim(),
        str(file_path),
        ref_pair=(str(ref_ch1), str(ref_ch2)),
        first_n_channels=_configured_biosemi64_channel_limit(settings),
        stim_channel=_configured_stim_channel(settings),
        electrode_mapping_profile=settings.get("electrode_mapping_profile"),
        electrode_montage=settings.get("electrode_montage"),
    )


class _PreflightQcCancelled(RuntimeError):
    """Internal cooperative-cancellation signal for one participant scan."""


def _configured_ref_pair(settings: Mapping[str, Any]) -> tuple[str, str]:
    return (
        str(
            settings.get("ref_channel1")
            or settings.get("ref_chan1")
            or settings.get("ref_ch1")
            or "EXG1"
        ),
        str(
            settings.get("ref_channel2")
            or settings.get("ref_chan2")
            or settings.get("ref_ch2")
            or "EXG2"
        ),
    )


def _configured_stim_channel(settings: Mapping[str, Any]) -> str:
    return str(settings.get("stim_channel") or settings.get("stim") or "Status")


def _find_preflight_events(raw: Any, *, stim_channel: str) -> tuple[np.ndarray, str]:
    try:
        events = mne.find_events(
            raw,
            stim_channel=stim_channel,
            shortest_event=1,
            verbose=False,
        )
        source = "stim"
    except (RuntimeError, ValueError):
        events, _event_ids = mne.events_from_annotations(raw, verbose=False)
        source = "annotations"
    events_array = np.asarray(events, dtype=np.int64)
    if events_array.size == 0:
        raise RuntimeError(
            f"No events found for preflight QC (source={source!r}, stim={stim_channel!r})."
        )
    return events_array, source


def _configured_biosemi64_channel_limit(settings: Mapping[str, Any]) -> int:
    """Resolve the project-owned canonical first-N scalp limit."""

    raw_limit = settings.get("max_idx_keep")
    if raw_limit is None:
        raw_limit = settings.get("max_chan_idx_keep")
    if raw_limit is None:
        return len(BIOSEMI64_CHANNELS)
    if isinstance(raw_limit, bool):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    try:
        channel_limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "BioSemi64 channel limit must be an integer from 1 through 64."
        ) from exc
    if isinstance(raw_limit, float) and not raw_limit.is_integer():
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    if not 1 <= channel_limit <= len(BIOSEMI64_CHANNELS):
        raise ValueError("BioSemi64 channel limit must be an integer from 1 through 64.")
    return channel_limit


def _preflight_scalp_picks(
    raw: Any,
    *,
    settings: Mapping[str, Any],
) -> tuple[tuple[int, ...], tuple[str, ...]]:
    stim_channel = _configured_stim_channel(settings)
    ref_channels = set(_configured_ref_pair(settings))
    retained_scalp = set(
        BIOSEMI64_CHANNELS[:_configured_biosemi64_channel_limit(settings)]
    )
    picks = tuple(
        index
        for index, channel in enumerate(getattr(raw, "ch_names", ()))
        if str(channel) in SCALP_CHANNELS
        and str(channel) in retained_scalp
        and str(channel) != stim_channel
        and str(channel) not in ref_channels
    )
    names = tuple(str(raw.ch_names[index]) for index in picks)
    if not picks:
        raise RuntimeError("Preflight QC v4 found no scalp EEG channels.")
    return picks, names


def _read_condition_data(
    raw: Any,
    *,
    picks: Sequence[int],
    start: int,
    stop: int,
    io_semaphore: threading.BoundedSemaphore,
) -> np.ndarray:
    with io_semaphore:
        try:
            data = raw.get_data(
                picks=list(picks),
                start=int(start),
                stop=int(stop),
                verbose=False,
            )
        except TypeError:
            data = raw.get_data(
                picks=list(picks),
                start=int(start),
                stop=int(stop),
            )
    result = np.asarray(data, dtype=np.float64)
    expected_samples = int(stop) - int(start)
    if result.ndim != 2 or result.shape != (len(picks), expected_samples):
        raise RuntimeError(
            "Lazy BDF condition read returned an unexpected shape: "
            f"expected={(len(picks), expected_samples)}, actual={result.shape}."
        )
    return result


@contextmanager
def _condition_data_buffer(
    raw: Any,
    *,
    picks: Sequence[int],
    start: int,
    stop: int,
    sfreq: float,
    io_semaphore: threading.BoundedSemaphore,
    should_cancel: CancelCallback | None = None,
    progress_detail: DetailProgressCallback | None = None,
    detail_prefix: str = "",
) -> Iterator[tuple[np.ndarray, bool]]:
    """Yield one condition without ever materializing the full recording.

    Ordinary condition intervals remain in RAM and are read once. Unusually
    long intervals are copied in bounded ten-second I/O chunks into a temporary
    condition-only float64 memmap. Diagnostic windowing is planned separately
    after the occurrence buffer is complete. Both paths
    expose the same array values to the QC math; the disk-backed path only
    changes where the condition buffer lives.
    """

    sample_count = int(stop) - int(start)
    if sample_count <= 0:
        raise ValueError("Condition QC requires a positive sample interval.")
    shape = (len(picks), sample_count)
    required_bytes = int(np.prod(shape, dtype=np.int64)) * np.dtype(np.float64).itemsize
    if required_bytes <= PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES:
        yield (
            _read_condition_data(
                raw,
                picks=picks,
                start=start,
                stop=stop,
                io_semaphore=io_semaphore,
            ),
            False,
        )
        return

    chunk_samples = max(1, int(round(PREFLIGHT_QC_BLOCK_DURATION_S * sfreq)))
    chunk_count = (sample_count + chunk_samples - 1) // chunk_samples
    with tempfile.TemporaryDirectory(prefix="fpvs-preflight-qc-") as temp_dir:
        buffer_path = Path(temp_dir) / "condition-float64.dat"
        condition_buffer = np.memmap(
            buffer_path,
            dtype=np.float64,
            mode="w+",
            shape=shape,
        )
        try:
            for chunk_index, local_start in enumerate(
                range(0, sample_count, chunk_samples),
                start=1,
            ):
                if should_cancel is not None and should_cancel():
                    raise _PreflightQcCancelled()
                local_stop = min(sample_count, local_start + chunk_samples)
                if progress_detail:
                    prefix = f"{detail_prefix} · " if detail_prefix else ""
                    progress_detail(
                        f"{prefix}reading condition block "
                        f"{chunk_index}/{chunk_count} (disk-buffered)"
                    )
                chunk = _read_condition_data(
                    raw,
                    picks=picks,
                    start=int(start) + local_start,
                    stop=int(start) + local_stop,
                    io_semaphore=io_semaphore,
                )
                condition_buffer[:, local_start:local_stop] = chunk
                del chunk
            condition_buffer.flush()
            yield condition_buffer, True
        finally:
            try:
                condition_buffer.flush()
            finally:
                mmap_handle = getattr(condition_buffer, "_mmap", None)
                if mmap_handle is not None:
                    mmap_handle.close()


def _condition_blocks(
    data: np.ndarray,
    *,
    span: ConditionQcSpan,
    sfreq: float,
) -> tuple[ConditionRawChannelQCBlock, ...]:
    bounds = _transient_window_bounds(data.shape[1], sfreq=sfreq)
    blocks: list[ConditionRawChannelQCBlock] = []
    for index, (local_start, local_stop, window_kind) in enumerate(bounds):
        absolute_start = int(span.time_start_sample) + local_start
        absolute_stop = int(span.time_start_sample) + local_stop
        blocks.append(
            ConditionRawChannelQCBlock(
                condition_id=span.condition_label,
                occurrence=int(span.repetition_index),
                start_sample=absolute_start,
                stop_sample=absolute_stop,
                data=data[:, local_start:local_stop],
                is_final=index == len(bounds) - 1,
                window_kind=window_kind,
            )
        )
    return tuple(blocks)


def _transient_window_bounds(
    sample_count: int,
    *,
    sfreq: float,
) -> tuple[tuple[int, int, str], ...]:
    """Plan bounded 5-second/50%-overlap diagnostic windows."""

    n_samples = int(sample_count)
    sample_rate = float(sfreq)
    if n_samples <= 0:
        raise ValueError("Transient QC requires a positive occurrence sample count.")
    if not np.isfinite(sample_rate) or sample_rate <= 0.0:
        raise ValueError("Transient QC requires a positive finite sampling rate.")
    window_samples = max(
        1,
        int(round(PREFLIGHT_QC_TRANSIENT_WINDOW_DURATION_S * sample_rate)),
    )
    hop_samples = max(
        1,
        int(round(PREFLIGHT_QC_TRANSIENT_WINDOW_HOP_S * sample_rate)),
    )
    hop_samples = min(hop_samples, window_samples)
    if n_samples < window_samples:
        return ((0, n_samples, "short"),)

    starts = list(range(0, n_samples - window_samples + 1, hop_samples))
    tail_start = n_samples - window_samples
    kinds = ["regular"] * len(starts)
    if starts[-1] != tail_start:
        starts.append(tail_start)
        kinds.append("tail_aligned")
    return tuple(
        (start, start + window_samples, kinds[index])
        for index, start in enumerate(starts)
    )


def _occurrence_evaluation_scope(
    event_plan: Any,
    *,
    evaluated_spans: Sequence[ConditionQcSpan] | None = None,
    excluded_condition_labels: Sequence[str] = (),
) -> list[dict[str, object]]:
    """Account for evaluated and intentionally unavailable marker occurrences."""

    evaluated = {
        (int(span.condition_id), int(span.repetition_index))
        for span in (
            event_plan.spans if evaluated_spans is None else evaluated_spans
        )
    }
    excluded_keys = {str(label).strip().casefold() for label in excluded_condition_labels}
    approved = {
        (
            int(item.get("condition_code", -1)),
            int(item.get("repetition_index", -1)),
        ): str(item.get("disposition") or "")
        for item in event_plan.approved_occurrences
        if isinstance(item, Mapping)
    }
    unresolved = {
        (
            int(item.get("condition_code", -1)),
            int(item.get("repetition_index", -1)),
        ): tuple(str(reason) for reason in item.get("review_reasons", ()))
        for item in event_plan.unresolved_occurrences
        if isinstance(item, Mapping)
    }
    marker_payload = event_plan.marker_integrity_plan
    occurrences = (
        marker_payload.get("occurrences", ())
        if isinstance(marker_payload, Mapping)
        else ()
    )
    rows: list[dict[str, object]] = []
    for occurrence in occurrences:
        if not isinstance(occurrence, Mapping):
            continue
        code = int(occurrence.get("condition_code", -1))
        repetition = int(occurrence.get("repetition_index", -1))
        key = (code, repetition)
        condition_label = str(occurrence.get("condition_label") or code)
        if condition_label.strip().casefold() in excluded_keys:
            status = "not_evaluated"
            reason = "condition_excluded_from_analysis"
        elif key in evaluated:
            status = "evaluated"
            reason = None
        elif key in unresolved:
            status = "not_evaluated"
            reasons = unresolved[key]
            reason = ", ".join(reasons) or "marker_review_required"
        elif approved.get(key) == "exclude_occurrence":
            status = "not_evaluated"
            reason = "excluded_after_marker_review"
        else:
            status = "not_evaluated"
            reason = "analysis_span_not_retained"
        rows.append(
            {
                "condition_label": condition_label,
                "condition_code": code,
                "occurrence": repetition,
                "occurrence_display": repetition + 1,
                "evaluation_status": status,
                "reason": reason,
                "marker_occurrence_fingerprint": str(
                    occurrence.get("fingerprint") or ""
                ),
            }
        )
    return rows


def _preflight_cache_settings(
    settings: Mapping[str, Any],
    *,
    participant_id: str | None = None,
    recording_id: str | None = None,
    condition_labels: Sequence[str] = (),
) -> dict[str, object]:
    analysis = settings.get("analysis")
    analysis_payload = dict(analysis) if isinstance(analysis, Mapping) else {}
    analysis_protocol = analysis_payload.get("frequency_protocol")
    if analysis_protocol is not None:
        analysis_payload["frequency_protocol"] = normalize_frequency_protocol(
            analysis_protocol
        ).to_manifest()
    keys = (
        "stim_channel",
        "ref_channel1",
        "ref_channel2",
        "max_bad_chans",
        "max_bad_channels",
        "max_bad_channels_alert_thresh",
        "removed_electrode_detection_mode",
        "auto_detect_removed_electrodes",
        "detect_removed_electrodes",
        "auto_mark_removed_electrodes",
        "manual_removed_electrodes_enabled",
        "removed_electrode_detection_choice_schema_version",
        "removed_electrode_detection_choice_status",
        "removed_electrode_detection_choice_source",
        "_fpvs_manual_removed_electrodes",
        "manual_removed_electrodes",
        "manual_removed_electrodes_by_recording",
        "manual_excluded_participant_conditions",
        "manual_excluded_recording_conditions",
        "high_pass",
        "low_pass",
        "downsample",
        "downsample_rate",
        "base_freq",
        "oddball_freq",
        "frequency_protocol_fingerprint",
        "line_noise_filter_enabled",
        "line_noise_frequency_hz",
        "max_chan_idx_keep",
        "max_idx_keep",
        "electrode_montage",
        "electrode_mapping_profile",
        "raw_spectral_screening",
    )
    payload: dict[str, object] = {
        key: settings.get(key)
        for key in keys
        if settings.get(key) is not None
    }
    raw_protocol = settings.get("frequency_protocol")
    if raw_protocol is not None:
        payload["frequency_protocol"] = normalize_frequency_protocol(
            raw_protocol
        ).to_manifest()
    payload["analysis"] = analysis_payload
    payload["channel_subset_first_n"] = _configured_biosemi64_channel_limit(
        settings
    )
    payload["reference_pair"] = list(_configured_ref_pair(settings))
    payload["resolved_stim_channel"] = _configured_stim_channel(settings)
    if participant_id is not None:
        # Global maps are authority/configuration inputs, but only this
        # recording's resolved values can change its numerical findings.
        for key in (
            "manual_removed_electrodes", "manual_removed_electrodes_by_recording",
            "manual_excluded_participant_conditions", "manual_excluded_recording_conditions",
        ):
            payload.pop(key, None)
        payload["_fpvs_manual_removed_electrodes"] = list(
            manual_removed_electrodes_for_recording(
                settings, participant_id=participant_id, recording_id=recording_id,
            )
        )
        payload["excluded_condition_labels"] = list(_excluded_condition_labels_for_scan(
            settings, participant_id=participant_id, recording_id=recording_id,
            condition_labels=condition_labels,
        ))
        payload["recording_scope"] = {
            "participant_id": participant_id, "recording_id": recording_id,
        }
    payload["raw_channel_config"] = asdict(_raw_channel_config_from_settings({
        **settings,
        "_fpvs_manual_removed_electrodes": payload.get("_fpvs_manual_removed_electrodes", ()),
    }))
    return payload


def preflight_file_settings_identity(
    settings: Mapping[str, Any], *, participant_id: str,
    recording_id: str | None = None, condition_labels: Sequence[str] = (),
) -> str:
    """Fingerprint only settings effective for this recording's preflight QC."""

    payload = _preflight_cache_settings(
        settings, participant_id=participant_id, recording_id=recording_id,
        condition_labels=condition_labels,
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _excluded_condition_labels_for_scan(
    settings: Mapping[str, Any],
    *,
    participant_id: str,
    recording_id: str | None,
    condition_labels: Sequence[str],
) -> tuple[str, ...]:
    """Resolve the final condition windows that must not influence signal QC."""

    participant_exclusions = normalize_manual_excluded_participant_conditions(
        settings.get("manual_excluded_participant_conditions")
    )
    recording_exclusions = normalize_manual_excluded_recording_conditions(
        settings.get("manual_excluded_recording_conditions")
    )
    return tuple(
        label
        for label in condition_labels
        if is_participant_condition_excluded(
            participant_exclusions,
            participant_id,
            label,
        )
        or (
            bool(recording_id)
            and is_recording_condition_excluded(
                recording_exclusions,
                str(recording_id),
                label,
            )
        )
    )


def _preflight_cache_method(
    settings: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    settings = settings or {}
    channel_limit = _configured_biosemi64_channel_limit(settings)
    return {
        "name": PREFLIGHT_QC_METHOD_NAME,
        "version": PREFLIGHT_QC_METHOD_VERSION,
        "raw_channel_method": CONDITION_RAW_CHANNEL_QC_METHOD_VERSION,
        "raw_channel_defaults": asdict(RawChannelQCConfig()),
        "raw_spectral_method": CONDITION_SPECTRAL_QC_METHOD_VERSION,
        "raw_spectral_notch_method": FFT_MULTINOTCH_METHOD_VERSION,
        "raw_spectral_notch_half_width_hz": FFT_MULTINOTCH_HALF_WIDTH_HZ,
        "raw_spectral_eligibility_method": SPECTRAL_ELIGIBILITY_METHOD_VERSION,
        "condition_io_chunk_duration_s": PREFLIGHT_QC_BLOCK_DURATION_S,
        "transient_window_duration_s": PREFLIGHT_QC_TRANSIENT_WINDOW_DURATION_S,
        "transient_window_hop_s": PREFLIGHT_QC_TRANSIENT_WINDOW_HOP_S,
        "transient_tail_policy": PREFLIGHT_QC_TRANSIENT_TAIL_POLICY,
        "transient_overlap_counting": "union_coverage_not_independent_events",
        "condition_completion_policy": "locked_fft_span_v1",
        "geometry": biosemi64_geometry_identity(
            electrode_mapping_profile=settings.get("electrode_mapping_profile"),
            retained_channels=BIOSEMI64_CHANNELS[:channel_limit],
        ),
        "numpy_version": str(np.__version__),
        "mne_version": str(mne.__version__),
    }


def _preflight_file_identity(
    file_path: Path,
    *,
    recording_id: str | None = None,
) -> dict[str, object]:
    stat = file_path.stat()
    payload: dict[str, object] = {
        "resolved_path": str(file_path.resolve()),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
    }
    if recording_id:
        payload["recording_id"] = recording_id
    return payload


def _cached_preflight_result(
    cached: Mapping[str, Any],
    *,
    file_path: Path,
    participant_id: str,
    group_id: str | None,
    timings_ms: Mapping[str, float],
    recording_id: str | None = None,
    session_id: str | None = None,
    session_label: str | None = None,
    visit_index: int | None = None,
) -> PreflightQcFileResult | None:
    raw_channel_qc = cached.get("raw_channel_qc")
    raw_spectral_qc = cached.get("raw_spectral_qc")
    condition_qc = cached.get("condition_qc")
    if not isinstance(raw_channel_qc, Mapping) or not isinstance(
        raw_spectral_qc, Mapping
    ):
        return None
    condition_payload = dict(condition_qc) if isinstance(condition_qc, Mapping) else {}
    condition_payload["cache_status"] = "hit"
    condition_payload["timings_ms"] = dict(timings_ms)
    condition_payload["samples_read_per_channel"] = 0
    condition_payload["disk_buffered_condition_count"] = 0
    condition_payload["occurrence_cache_hits"] = condition_payload.get("condition_count", 0)
    return PreflightQcFileResult(
        path=file_path,
        participant_id=participant_id,
        load_error=None,
        raw_channel_qc=dict(raw_channel_qc),
        raw_spectral_qc=dict(raw_spectral_qc),
        group_id=group_id,
        condition_qc=condition_payload,
        recording_id=recording_id,
        session_id=session_id,
        session_label=session_label,
        visit_index=visit_index,
    )


def _aggregate_condition_spectral_qc(
    results: Sequence[tuple[ConditionQcSpan, ConditionSpectralQCResult]],
    *,
    filename: str,
    skipped_spans: Sequence[ConditionQcSpan],
    screening_settings: RawSpectralScreeningSettings,
) -> dict[str, object]:
    flagged_channels: set[str] = set()
    unexpected_peaks: list[tuple[ConditionQcSpan, Any]] = []
    notch_collisions: list[tuple[ConditionQcSpan, Any]] = []
    observed_widespread = False
    condition_payloads: list[dict[str, object]] = []
    review_rows: list[dict[str, object]] = []
    for span, result in results:
        occurrence_evidence_payload = {
            "condition_label": span.condition_label,
            "condition_id": span.condition_id,
            "repetition_index": span.repetition_index,
            "spectral_start_sample": span.spectral_start_sample,
            "spectral_stop_sample": span.spectral_stop_sample,
            "marker_plan_fingerprint": span.marker_plan_fingerprint,
            "approved_span_fingerprint": span.approved_span_fingerprint,
            "marker_disposition": span.marker_disposition,
            "condition_evidence_fingerprint": result.evidence_fingerprint,
            "default_scientific_decision": "retain",
        }
        occurrence_evidence_fingerprint = hashlib.sha256(
            json.dumps(
                occurrence_evidence_payload,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        payload = result.to_payload()
        payload["condition_label"] = span.condition_label
        payload["condition_id"] = span.condition_id
        payload["repetition_index"] = span.repetition_index
        payload["occurrence_display"] = span.repetition_index + 1
        payload["start_sample"] = span.spectral_start_sample
        payload["stop_sample"] = span.spectral_stop_sample
        payload["marker_plan_fingerprint"] = span.marker_plan_fingerprint
        payload["approved_span_fingerprint"] = span.approved_span_fingerprint
        payload["marker_disposition"] = span.marker_disposition
        payload["occurrence_evidence_fingerprint"] = (
            occurrence_evidence_fingerprint
        )
        condition_payloads.append(payload)
        for peak in result.unexpected_off_harmonic_flags:
            flagged_channels.update(peak.channels)
            unexpected_peaks.append((span, peak))
            observed_widespread = observed_widespread or bool(peak.widespread)
            review_rows.append(
                {
                    "evidence_kind": "unexpected_narrow_frequency_signal",
                    "condition_label": span.condition_label,
                    "condition_id": span.condition_id,
                    "repetition_index": span.repetition_index,
                    "occurrence_display": span.repetition_index + 1,
                    "start_sample": span.spectral_start_sample,
                    "stop_sample": span.spectral_stop_sample,
                    "analyzed_duration_s": result.analyzed_duration_s,
                    "realized_oddball_cycles": result.realized_oddball_cycles,
                    "method_version": result.method_version,
                    "threshold_policy_version": result.threshold_policy_version,
                    "condition_evidence_fingerprint": result.evidence_fingerprint,
                    "evidence_fingerprint": occurrence_evidence_fingerprint,
                    "default_scientific_decision": "retain",
                    **peak.to_payload(),
                }
            )
        for collision in result.notch_collisions:
            notch_collisions.append((span, collision))
            review_rows.append(
                {
                    "evidence_kind": "configured_notch_fpvs_collision",
                    "condition_label": span.condition_label,
                    "condition_id": span.condition_id,
                    "repetition_index": span.repetition_index,
                    "occurrence_display": span.repetition_index + 1,
                    "start_sample": span.spectral_start_sample,
                    "stop_sample": span.spectral_stop_sample,
                    "analyzed_duration_s": result.analyzed_duration_s,
                    "realized_oddball_cycles": result.realized_oddball_cycles,
                    "method_version": result.method_version,
                    "threshold_policy_version": result.threshold_policy_version,
                    "condition_evidence_fingerprint": result.evidence_fingerprint,
                    "evidence_fingerprint": occurrence_evidence_fingerprint,
                    "default_scientific_decision": "retain_recording_condition",
                    **collision.to_payload(),
                }
            )
        for below_boundary in result.targets_below_screen_boundary:
            review_rows.append(
                {
                    "evidence_kind": "target_below_experimental_screen_boundary",
                    "condition_label": span.condition_label,
                    "condition_id": span.condition_id,
                    "repetition_index": span.repetition_index,
                    "occurrence_display": span.repetition_index + 1,
                    "start_sample": span.spectral_start_sample,
                    "stop_sample": span.spectral_stop_sample,
                    "analyzed_duration_s": result.analyzed_duration_s,
                    "realized_oddball_cycles": result.realized_oddball_cycles,
                    "method_version": result.method_version,
                    "threshold_policy_version": result.threshold_policy_version,
                    "condition_evidence_fingerprint": result.evidence_fingerprint,
                    "evidence_fingerprint": occurrence_evidence_fingerprint,
                    "default_scientific_decision": "retain",
                    **dict(below_boundary),
                }
            )

    strongest = max(
        unexpected_peaks,
        key=lambda item: item[1].max_legacy_hann_spectrum_score,
        default=None,
    )
    if not screening_settings.enabled:
        evaluation_status = RAW_SPECTRAL_QC_DISABLED_STATUS
        message = (
            f"Experimental raw-spectral review was not performed for {filename} "
            "because it is disabled in project settings."
        )
    elif unexpected_peaks:
        evaluation_status = "evaluated"
        message = (
            f"Experimental raw-spectral review flagged {len(unexpected_peaks)} "
            f"unexpected narrow-frequency signal(s) in {filename}."
        )
    elif notch_collisions:
        evaluation_status = "evaluated"
        message = (
            f"Experimental raw-spectral review found {len(notch_collisions)} "
            f"configured line-noise/FPVS collision(s) in {filename}."
        )
    elif any(result.evaluated for _span, result in results):
        evaluation_status = "evaluated"
        message = (
            f"Experimental raw-spectral review found no unexpected "
            f"narrow-frequency signals in {filename}."
        )
    else:
        evaluation_status = "not_evaluated"
        message = (
            f"Experimental raw-spectral review was not evaluated for {filename}: "
            "no valid locked on-bin condition span was available."
        )

    return {
        "method_version": CONDITION_SPECTRAL_QC_METHOD_VERSION,
        "threshold_policy_version": screening_settings.policy_version,
        "enabled": screening_settings.enabled,
        "evaluation_status": evaluation_status,
        "review_only": True,
        "evaluated": evaluation_status == "evaluated",
        "default_scientific_decision": "retain",
        "automatic_data_changes": False,
        # Compatibility remains false so experimental review findings cannot
        # enter the historical recording-exclusion path.
        "widespread": False,
        "observed_widespread_review": observed_widespread,
        "message": message,
        "n_channels": max((result.n_channels for _span, result in results), default=0),
        "flagged_channels": sorted(flagged_channels),
        "peak_frequency_hz": (
            float(strongest[1].frequency_hz) if strongest is not None else None
        ),
        "max_legacy_hann_spectrum_score": (
            float(strongest[1].max_legacy_hann_spectrum_score)
            if strongest is not None
            else 0.0
        ),
        "max_local_ratio": (
            float(strongest[1].max_local_ratio) if strongest is not None else 0.0
        ),
        "review_rows": review_rows,
        "notch_collision_count": len(notch_collisions),
        "unexpected_signal_count": len(unexpected_peaks),
        "effective_settings": screening_settings.to_manifest(),
        "method_specific_amplitude_label": "Legacy Hann-spectrum score",
        "condition_results": condition_payloads,
        "skipped_condition_spans": [
            {
                "condition_label": span.condition_label,
                "condition_id": span.condition_id,
                "repetition_index": span.repetition_index,
                "reason": span.spectral_fallback_reason or "no_locked_onbin_span",
            }
            for span in skipped_spans
        ],
    }


def _preflight_worker_count(total: int, max_workers: int | None) -> int:
    if total <= 1:
        return 1
    try:
        requested = int(max_workers or 1)
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(total, requested, PREFLIGHT_QC_MAX_WORKERS))


def _scan_one_preflight_file_v2(
    info: RawFileInfo,
    qc_settings: Mapping[str, Any],
    *,
    project_root: Path,
    event_map: Mapping[str, int],
    io_semaphore: threading.BoundedSemaphore,
    spectral_semaphore: threading.BoundedSemaphore,
    progress_detail: DetailProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> PreflightQcFileResult | None:
    file_path = Path(info.path)
    participant_id = str(info.subject_id)
    group_id = str(info.group).strip() if info.group else None
    recording_id = str(info.recording_id).strip() if info.recording_id else None
    session_id = str(info.session_id).strip() if info.session_id else None
    session_label = str(info.session_label).strip() if info.session_label else None
    visit_index = info.visit_index
    timings_ms: dict[str, float] = {}
    file_qc_settings = dict(qc_settings)
    raw_spectral_screening = normalize_raw_spectral_screening_settings(
        qc_settings.get("raw_spectral_screening")
    )
    file_qc_settings["raw_spectral_screening"] = (
        raw_spectral_screening.to_manifest()
    )
    file_qc_settings["_fpvs_manual_removed_electrodes"] = list(
        manual_removed_electrodes_for_recording(
            qc_settings,
            participant_id=participant_id,
            recording_id=recording_id,
        )
    )

    def _cancelled() -> bool:
        return bool(should_cancel and should_cancel())

    def _record_timing(stage: str, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        timings_ms[stage] = elapsed_ms
        logger.info(
            "preflight_qc_timing file=%s participant_id=%s stage=%s elapsed_ms=%.3f",
            file_path.name,
            participant_id,
            stage,
            elapsed_ms,
        )

    if _cancelled():
        raise _PreflightQcCancelled()

    header_started = time.perf_counter()
    with io_semaphore:
        preflight = load_utils.inspect_bdf_header(file_path)
    _record_timing("header", header_started)
    if preflight and preflight.recording_not_started:
        return None

    if progress_detail:
        progress_detail(f"Planning {file_path.name} · checking source events")

    file_identity = _preflight_file_identity(file_path, recording_id=recording_id)
    cache_settings = _preflight_cache_settings(
        file_qc_settings, participant_id=participant_id, recording_id=recording_id,
        condition_labels=tuple(str(label) for label in event_map),
    )
    cache_method = _preflight_cache_method(file_qc_settings)

    def _require_unchanged_source() -> None:
        if _preflight_file_identity(file_path, recording_id=recording_id) != file_identity:
            raise RuntimeError("The source recording changed during preflight QC; run QC again.")

    raw_context = load_utils.open_preflight_eeg_file(
        _LogShim(),
        str(file_path),
        ref_pair=_configured_ref_pair(qc_settings),
        first_n_channels=_configured_biosemi64_channel_limit(qc_settings),
        stim_channel=_configured_stim_channel(qc_settings),
        electrode_mapping_profile=qc_settings.get("electrode_mapping_profile"),
        electrode_montage=qc_settings.get("electrode_montage"),
    )
    raw = None
    context_entered = False
    try:
        open_started = time.perf_counter()
        with io_semaphore:
            raw = raw_context.__enter__()
            context_entered = True
        _record_timing("lazy_open", open_started)
        if raw is None:
            raise RuntimeError("BDF lazy loader returned no raw data.")
        if _cancelled():
            raise _PreflightQcCancelled()

        event_started = time.perf_counter()
        event_cache_key = {
            "file_identity": file_identity,
            "settings": {
                "stim_channel": _configured_stim_channel(qc_settings),
                "reference_pair": list(_configured_ref_pair(qc_settings)),
            },
            "method": {"event_extractor": "mne_shortest_1_annotation_fallback_v1", **cache_method},
            "event_plan": {
                "sfreq": float(raw.info["sfreq"]), "n_times": int(raw.n_times),
                "first_samp": int(raw.first_samp), "channel_names": list(raw.ch_names),
            },
        }
        cached_events = load_source_events(project_root, **event_cache_key)
        event_cache_status = "hit" if cached_events is not None else "miss"
        if cached_events is None:
            with io_semaphore:
                events, event_source = _find_preflight_events(
                    raw,
                    stim_channel=_configured_stim_channel(qc_settings),
                )
            if _cancelled():
                raise _PreflightQcCancelled()
            _require_unchanged_source()
            save_source_events(
                project_root, events=events, source=event_source, **event_cache_key,
            )
        else:
            events, event_source = cached_events
        raw_protocol = qc_settings.get("frequency_protocol")
        if raw_protocol is None:
            raise RuntimeError(
                "A confirmed project FPVS protocol is required before preflight QC."
            )
        try:
            frequency_protocol = normalize_frequency_protocol(raw_protocol)
        except FrequencyProtocolError as exc:
            raise RuntimeError(f"Invalid project FPVS protocol: {exc}") from exc
        raw_decisions_by_file = qc_settings.get(
            "_fpvs_marker_review_decisions_by_file"
        )
        marker_review_decisions = None
        if isinstance(raw_decisions_by_file, Mapping):
            path_candidates = (
                str(file_path),
                str(file_path.resolve()),
                file_path.name,
            )
            for path_candidate in path_candidates:
                candidate = raw_decisions_by_file.get(path_candidate)
                if isinstance(candidate, Mapping):
                    marker_review_decisions = candidate
                    break
        event_plan = plan_preflight_qc_events(
            events=events,
            event_map=event_map,
            sfreq=float(raw.info["sfreq"]),
            n_times=int(raw.n_times),
            first_samp=int(raw.first_samp),
            frequency_protocol=frequency_protocol,
            marker_review_decisions=marker_review_decisions,
            marker_review_scope={
                "source_file_path": str(file_path.resolve()),
                "participant_id": participant_id,
                "recording_id": recording_id,
                "session_id": session_id,
                "session_label": session_label,
            },
        )
        _record_timing("events_and_plan", event_started)
        if not event_plan.spans:
            if event_plan.unresolved_occurrences:
                return PreflightQcFileResult(
                    path=file_path,
                    participant_id=participant_id,
                    load_error=None,
                    raw_channel_qc=None,
                    raw_spectral_qc=None,
                    group_id=group_id,
                    condition_qc={
                        "method_name": PREFLIGHT_QC_METHOD_NAME,
                        "method_version": PREFLIGHT_QC_METHOD_VERSION,
                        "review_only": True,
                        "cache_status": "marker_review_required",
                        "event_source": event_source,
                        "event_plan": event_plan.to_payload(),
                        "condition_count": 0,
                        "marker_review_required": True,
                    },
                    recording_id=recording_id,
                    session_id=session_id,
                    session_label=session_label,
                    visit_index=visit_index,
                )
            raise RuntimeError("Preflight QC v4 planned no relevant condition intervals.")

        event_plan_payload = event_plan.to_payload()
        excluded_condition_labels = _excluded_condition_labels_for_scan(
            qc_settings,
            participant_id=participant_id,
            recording_id=recording_id,
            condition_labels=tuple(str(label) for label in event_map),
        )
        excluded_condition_keys = {
            label.casefold() for label in excluded_condition_labels
        }
        scored_spans = tuple(
            span
            for span in event_plan.spans
            if span.condition_label.casefold() not in excluded_condition_keys
        )
        raw_source_plan = event_plan_payload.get("source_analysis_span_plan")
        if not isinstance(raw_source_plan, Mapping):
            raise RuntimeError(
                "Preflight QC event plan has no canonical source analysis spans."
            )
        scored_source_plan = restrict_source_analysis_span_plan_by_condition(
            raw_source_plan,
            excluded_condition_labels=excluded_condition_labels,
            exclusion_scope={
                "participant_id": participant_id,
                "recording_id": recording_id,
            },
        )
        cache_started = time.perf_counter()
        cached = load_preflight_qc_cache(
            project_root,
            file_identity=file_identity,
            settings=cache_settings,
            method=cache_method,
            event_plan=event_plan_payload,
        )
        _record_timing("cache_lookup", cache_started)
        if cached is not None:
            cached_result = _cached_preflight_result(
                cached,
                file_path=file_path,
                participant_id=participant_id,
                group_id=group_id,
                timings_ms=timings_ms,
                recording_id=recording_id,
                session_id=session_id,
                session_label=session_label,
                visit_index=visit_index,
            )
            if cached_result is not None:
                if _cancelled():
                    raise _PreflightQcCancelled()
                _require_unchanged_source()
                cached_result.condition_qc["event_cache_status"] = event_cache_status
                if progress_detail:
                    progress_detail(f"Cached {file_path.name} · condition QC reused")
                logger.info(
                    "preflight_qc_cache_hit file=%s participant_id=%s conditions=%d",
                    file_path.name,
                    participant_id,
                    len(scored_spans),
                )
                return cached_result

        picks, channel_names = _preflight_scalp_picks(
            raw,
            settings=file_qc_settings,
        )
        sfreq = float(raw.info["sfreq"])
        lower_hz, upper_hz = resolve_preflight_spectral_bounds(
            qc_settings,
            source_sfreq=sfreq,
        )
        spectral_thresholds = condition_spectral_thresholds_from_project_settings(
            raw_spectral_screening
        )

        channel_results = []
        spectral_results: list[
            tuple[ConditionQcSpan, ConditionSpectralQCResult]
        ] = []
        skipped_spectral_spans: list[ConditionQcSpan] = []
        samples_read = 0
        disk_buffered_condition_count = 0
        conditions_total = len(scored_spans)
        occurrence_cache_hits = 0
        numerical_settings = {
            key: value for key, value in cache_settings.items()
            if key not in {"excluded_condition_labels", "recording_scope"}
        }
        stage_totals = dict.fromkeys(
            ("condition_read", "raw_channel_qc", "spectral_wait", "spectral_calculate", "occurrence_cache"),
            0.0,
        )

        def _add_stage(stage: str, started: float) -> None:
            stage_totals[stage] += (time.perf_counter() - started) * 1_000.0

        qc_started = time.perf_counter()
        for condition_index, span in enumerate(scored_spans, start=1):
            if _cancelled():
                raise _PreflightQcCancelled()
            detail_prefix = (
                f"Scanning {file_path.name} · {span.condition_label} "
                f"{condition_index}/{conditions_total}"
            )
            occurrence_key = {
                "file_identity": file_identity,
                "settings": numerical_settings,
                "method": {**cache_method, "evidence_codec": "typed_float64_v1"},
                "event_plan": {
                    "span": {
                        key: value for key, value in span.to_payload().items()
                        if key not in {
                            "marker_plan_fingerprint", "approved_span_fingerprint", "marker_disposition",
                        }
                    },
                    "sfreq": sfreq, "first_samp": event_plan.first_samp,
                    "channel_names": list(channel_names), "picks": list(picks),
                    "spectral_upper_hz": upper_hz,
                },
            }
            occurrence_started = time.perf_counter()
            evidence = load_occurrence_evidence(project_root, **occurrence_key)
            _add_stage("occurrence_cache", occurrence_started)
            if evidence is not None:
                cached_channel, cached_spectral = evidence
                channel_results.append(cached_channel)
                if cached_spectral is None:
                    skipped_spectral_spans.append(span)
                else:
                    spectral_results.append((span, cached_spectral))
                occurrence_cache_hits += 1
                if progress_detail:
                    progress_detail(f"{detail_prefix} · cached condition QC reused")
                continue
            if progress_detail:
                progress_detail(f"{detail_prefix} · reading condition samples")

            read_started = time.perf_counter()
            with _condition_data_buffer(
                raw,
                picks=picks,
                start=span.time_start_sample - event_plan.first_samp,
                stop=span.time_stop_sample - event_plan.first_samp,
                sfreq=sfreq,
                io_semaphore=io_semaphore,
                should_cancel=should_cancel,
                progress_detail=progress_detail,
                detail_prefix=detail_prefix,
            ) as (condition_data, disk_buffered):
                _add_stage("condition_read", read_started)
                blocks = None
                spectral_data = None
                spectral_result = None
                try:
                    if disk_buffered:
                        disk_buffered_condition_count += 1
                    samples_read += int(condition_data.shape[1])
                    raw_qc_started = time.perf_counter()
                    blocks = _condition_blocks(condition_data, span=span, sfreq=sfreq)
                    if progress_detail:
                        progress_detail(
                            f"{detail_prefix} · checking "
                            f"{len(blocks)} time-domain block(s)"
                        )
                    try:
                        channel_results.append(
                            evaluate_condition_raw_channel_qc_v2(
                                blocks,
                                channel_names,
                                file_qc_settings,
                                filename=file_path.name,
                                sfreq=sfreq,
                                block_duration_s=(
                                    PREFLIGHT_QC_TRANSIENT_WINDOW_DURATION_S
                                ),
                                window_hop_s=PREFLIGHT_QC_TRANSIENT_WINDOW_HOP_S,
                                should_cancel=should_cancel,
                            )
                        )
                    except ConditionRawChannelQCCancelled as exc:
                        raise _PreflightQcCancelled() from exc
                    _add_stage("raw_channel_qc", raw_qc_started)

                    if (
                        span.spectral_start_sample is None
                        or span.spectral_stop_sample is None
                    ):
                        skipped_spectral_spans.append(span)
                    else:
                        relative_start = (
                            int(span.spectral_start_sample)
                            - int(span.time_start_sample)
                        )
                        relative_stop = (
                            int(span.spectral_stop_sample)
                            - int(span.time_start_sample)
                        )
                        spectral_data = condition_data[
                            :,
                            relative_start:relative_stop,
                        ]
                        if spectral_data.shape[1] != span.spectral_sample_count:
                            raise RuntimeError(
                                "Condition spectral crop did not match the shared planner: "
                                f"expected={span.spectral_sample_count}, "
                                f"actual={spectral_data.shape[1]}, "
                                f"condition={span.condition_label!r}."
                            )
                        if progress_detail:
                            progress_detail(
                                f"{detail_prefix} · checking exact on-bin spectrum"
                            )
                        try:
                            spectral_wait_started = time.perf_counter()
                            with spectral_semaphore:
                                _add_stage("spectral_wait", spectral_wait_started)
                                spectral_calculate_started = time.perf_counter()
                                spectral_result = evaluate_condition_spectral_qc_v2(
                                    spectral_data,
                                    sfreq=sfreq,
                                    settings=file_qc_settings,
                                    effective_upper_frequency_hz=upper_hz,
                                    channel_names=channel_names,
                                    condition_label=(
                                        f"{span.condition_label} repetition "
                                        f"{span.repetition_index + 1}"
                                    ),
                                    thresholds=spectral_thresholds,
                                    should_cancel=should_cancel,
                                )
                                _add_stage("spectral_calculate", spectral_calculate_started)
                        except ConditionSpectralQCCancelled as exc:
                            raise _PreflightQcCancelled() from exc
                        spectral_results.append(
                            (
                                span,
                                spectral_result,
                            )
                        )
                finally:
                    spectral_data = None
                    blocks = None
                    del condition_data
            if _cancelled():
                raise _PreflightQcCancelled()
            _require_unchanged_source()
            occurrence_started = time.perf_counter()
            save_occurrence_evidence(
                project_root, channel=channel_results[-1], spectral=spectral_result,
                **occurrence_key,
            )
            _add_stage("occurrence_cache", occurrence_started)
        _record_timing("condition_qc", qc_started)
        for stage, elapsed_ms in stage_totals.items():
            timings_ms[stage] = elapsed_ms
            logger.info(
                "preflight_qc_timing file=%s participant_id=%s stage=%s elapsed_ms=%.3f",
                file_path.name, participant_id, stage, elapsed_ms,
            )
        if _cancelled():
            raise _PreflightQcCancelled()

        if channel_results:
            channel_result = combine_condition_raw_channel_qc_v2(
                channel_results,
                filename=file_path.name,
            )
            raw_channel_payload = channel_result.to_payload()
        else:
            raw_channel_payload = {
                "method_version": CONDITION_RAW_CHANNEL_QC_METHOD_VERSION,
                "review_only": True,
                "evaluation_status": "not_evaluated",
                "reason": "all_conditions_excluded_from_analysis",
                "message": (
                    f"Signal QC was not evaluated for {file_path.name} because "
                    "every project condition is explicitly excluded for this recording."
                ),
                "n_channels": len(channel_names),
                "n_conditions": 0,
                "n_blocks": 0,
                "n_samples": 0,
                "n_bad_channels": 0,
                "bad_channels": [],
                "channels_to_interpolate": [],
                "manual_removed_channels": [],
                "low_variance_channels": [],
                "high_amplitude_channels": [],
                "rare_burst_channels": [],
                "spatial_outlier_channels": [],
                "warning_rules": [],
                "review_rules": [],
                "candidate_sources": {},
                "candidate_burden_findings": [],
                "occurrence_review_findings": [],
                "transient_review_findings": [],
                "raw_amplitude_review_findings": [],
                "thresholds": {},
                "conditions": [],
            }
        raw_channel_payload["scoring_scope"] = "approved_analyzed_occurrences"
        raw_channel_payload["occurrence_evaluation_scope"] = (
            _occurrence_evaluation_scope(
                event_plan,
                evaluated_spans=scored_spans,
                excluded_condition_labels=excluded_condition_labels,
            )
        )
        raw_channel_payload["analysis_span_plan_fingerprint"] = str(
            scored_source_plan["fingerprint"]
        )
        thresholds = raw_channel_payload.get("thresholds")
        detector_evaluated = bool(
            isinstance(thresholds, Mapping)
            and thresholds.get("auto_detect_removed_electrodes")
        )
        raw_channel_payload["experimental_removed_electrode_detector"] = {
            "evaluation_status": (
                "evaluated" if detector_evaluated else "not_evaluated"
            ),
            "reason": None if detector_evaluated else "disabled_in_project_settings",
        }
        raw_spectral_payload = _aggregate_condition_spectral_qc(
            spectral_results,
            filename=file_path.name,
            skipped_spans=skipped_spectral_spans,
            screening_settings=raw_spectral_screening,
        )
        condition_qc_payload: dict[str, object] = {
            "method_name": PREFLIGHT_QC_METHOD_NAME,
            "method_version": PREFLIGHT_QC_METHOD_VERSION,
            "review_only": True,
            "cache_status": "miss",
            "event_source": event_source,
            "event_cache_status": event_cache_status,
            "occurrence_cache_hits": occurrence_cache_hits,
            "event_plan": event_plan_payload,
            "scored_source_analysis_span_plan": scored_source_plan,
            "excluded_condition_labels": list(excluded_condition_labels),
            "condition_count": len(scored_spans),
            "marker_review_required": bool(event_plan.unresolved_occurrences),
            "samples_read_per_channel": samples_read,
            "recording_samples_per_channel": int(raw.n_times),
            "disk_buffered_condition_count": disk_buffered_condition_count,
            "spectral_lower_frequency_hz": lower_hz,
            "spectral_upper_frequency_hz": upper_hz,
            "timings_ms": dict(timings_ms),
            "geometry": biosemi64_geometry_identity(
                electrode_mapping_profile=qc_settings.get(
                    "electrode_mapping_profile"
                ),
                retained_channels=channel_names,
            ),
            "hard_exclusion_policy": (
                "signal_amplitude_and_candidate_burden_are_review_only; "
                "technical_integrity_failures_remain_blocking"
            ),
        }
        result = PreflightQcFileResult(
            path=file_path,
            participant_id=participant_id,
            load_error=None,
            raw_channel_qc=raw_channel_payload,
            raw_spectral_qc=raw_spectral_payload,
            group_id=group_id,
            condition_qc=condition_qc_payload,
            recording_id=recording_id,
            session_id=session_id,
            session_label=session_label,
            visit_index=visit_index,
        )

        if _cancelled():
            raise _PreflightQcCancelled()
        save_started = time.perf_counter()
        _require_unchanged_source()
        try:
            save_preflight_qc_cache(
                project_root,
                file_identity=file_identity,
                settings=cache_settings,
                method=cache_method,
                event_plan=event_plan_payload,
                result={
                    "raw_channel_qc": raw_channel_payload,
                    "raw_spectral_qc": raw_spectral_payload,
                    "condition_qc": condition_qc_payload,
                },
            )
        except (OSError, TypeError, ValueError):
            logger.exception(
                "preflight_qc_cache_save_failed file=%s participant_id=%s",
                file_path,
                participant_id,
            )
        _record_timing("cache_save", save_started)
        return result
    finally:
        if context_entered:
            close_started = time.perf_counter()
            with io_semaphore:
                raw_context.__exit__(None, None, None)
            _record_timing("lazy_close", close_started)


def _scan_one_preflight_file(
    info: RawFileInfo,
    qc_settings: Mapping[str, Any],
    *,
    project_root: Path | None = None,
    event_map: Mapping[str, int] | None = None,
    io_semaphore: threading.BoundedSemaphore | None = None,
    spectral_semaphore: threading.BoundedSemaphore | None = None,
    progress_detail: DetailProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> PreflightQcFileResult | None:
    file_path = Path(info.path)
    participant_id = str(info.subject_id)
    group_id = str(info.group).strip() if info.group else None
    recording_id = str(info.recording_id).strip() if info.recording_id else None
    session_id = str(info.session_id).strip() if info.session_id else None
    session_label = str(info.session_label).strip() if info.session_label else None
    visit_index = info.visit_index
    if project_root is not None and event_map:
        try:
            return _scan_one_preflight_file_v2(
                info,
                qc_settings,
                project_root=Path(project_root),
                event_map=event_map,
                io_semaphore=(
                    io_semaphore
                    if io_semaphore is not None
                    else threading.BoundedSemaphore(PREFLIGHT_QC_MAX_IO_READERS)
                ),
                spectral_semaphore=(
                    spectral_semaphore
                    if spectral_semaphore is not None
                    else threading.BoundedSemaphore(
                        PREFLIGHT_QC_MAX_SPECTRAL_WORKERS
                    )
                ),
                progress_detail=progress_detail,
                should_cancel=should_cancel,
            )
        except _PreflightQcCancelled:
            raise
        except Exception as exc:
            logger.exception(
                "Condition-aware preflight QC failed for %s",
                file_path,
                extra={"participant_id": participant_id, "group_id": group_id},
            )
            return PreflightQcFileResult(
                path=file_path,
                participant_id=participant_id,
                load_error=str(exc),
                raw_channel_qc=None,
                raw_spectral_qc=None,
                group_id=group_id,
                condition_qc={
                    "method_name": PREFLIGHT_QC_METHOD_NAME,
                    "method_version": PREFLIGHT_QC_METHOD_VERSION,
                    "cache_status": "error",
                },
                recording_id=recording_id,
                session_id=session_id,
                session_label=session_label,
                visit_index=visit_index,
            )

    message = (
        "Signal-based preflight QC was not evaluated because an active project "
        "root and condition event map are required to define the analyzed intervals."
    )
    logger.warning(
        "preflight_qc_not_evaluated file=%s participant_id=%s reason=%s",
        file_path,
        participant_id,
        "missing_analyzed_interval_context",
    )
    return PreflightQcFileResult(
        path=file_path,
        participant_id=participant_id,
        load_error=None,
        raw_channel_qc=None,
        raw_spectral_qc=None,
        group_id=group_id,
        condition_qc={
            "method_name": PREFLIGHT_QC_METHOD_NAME,
            "method_version": PREFLIGHT_QC_METHOD_VERSION,
            "evaluation_status": "not_evaluated",
            "cache_status": "not_evaluated",
            "reason": "missing_analyzed_interval_context",
            "message": message,
        },
        recording_id=recording_id,
        session_id=session_id,
        session_label=session_label,
        visit_index=visit_index,
    )


def _ordered_results(
    indexed_results: Mapping[int, PreflightQcFileResult | None],
) -> tuple[PreflightQcFileResult, ...]:
    return tuple(
        result
        for index, result in sorted(indexed_results.items())
        if result is not None
    )


def _scan_preprocessing_qc_serial(
    pending_infos: Sequence[RawFileInfo],
    qc_settings: Mapping[str, Any],
    *,
    project_root: Path | None,
    event_map: Mapping[str, int] | None,
    io_semaphore: threading.BoundedSemaphore,
    spectral_semaphore: threading.BoundedSemaphore,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> PreflightQcScan:
    total = len(pending_infos)
    indexed_results: dict[int, PreflightQcFileResult | None] = {}
    for index, info in enumerate(pending_infos, start=1):
        if should_cancel and should_cancel():
            return PreflightQcScan(
                results=_ordered_results(indexed_results),
                cancelled=True,
            )
        file_path = Path(info.path)
        if progress:
            progress(f"Planning {file_path.name}", index - 1, total)
        try:
            indexed_results[index] = _scan_one_preflight_file(
                info,
                qc_settings,
                project_root=project_root,
                event_map=event_map,
                io_semaphore=io_semaphore,
                spectral_semaphore=spectral_semaphore,
                progress_detail=(
                    (lambda message: progress(message, index - 1, total))
                    if progress
                    else None
                ),
                should_cancel=should_cancel,
            )
        except _PreflightQcCancelled:
            return PreflightQcScan(
                results=_ordered_results(indexed_results),
                cancelled=True,
            )
        if progress:
            progress(f"Finished {file_path.name}", index, total)
    return PreflightQcScan(results=_ordered_results(indexed_results), cancelled=False)


def _scan_preprocessing_qc_parallel(
    pending_infos: Sequence[RawFileInfo],
    qc_settings: Mapping[str, Any],
    *,
    max_workers: int,
    project_root: Path | None,
    event_map: Mapping[str, int] | None,
    io_semaphore: threading.BoundedSemaphore,
    spectral_semaphore: threading.BoundedSemaphore,
    progress: ProgressCallback | None,
    should_cancel: CancelCallback | None,
) -> PreflightQcScan:
    total = len(pending_infos)
    submitted = 0
    completed = 0
    indexed_results: dict[int, PreflightQcFileResult | None] = {}
    futures: dict[Future[PreflightQcFileResult | None], tuple[int, RawFileInfo]] = {}

    def _submit_next(executor: ThreadPoolExecutor) -> None:
        nonlocal submitted
        while submitted < total and len(futures) < max_workers:
            if should_cancel and should_cancel():
                return
            index = submitted + 1
            info = pending_infos[submitted]
            submitted += 1
            file_path = Path(info.path)
            if progress:
                progress(f"Planning {file_path.name}", completed, total)
            futures[
                executor.submit(
                    _scan_one_preflight_file,
                    info,
                    qc_settings,
                    project_root=project_root,
                    event_map=event_map,
                    io_semaphore=io_semaphore,
                    spectral_semaphore=spectral_semaphore,
                    progress_detail=(
                        (lambda message: progress(message, completed, total))
                        if progress
                        else None
                    ),
                    should_cancel=should_cancel,
                )
            ] = (
                index,
                info,
            )

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="fpvs_preflight_qc",
    ) as executor:
        _submit_next(executor)
        while futures:
            if should_cancel and should_cancel():
                for future in futures:
                    future.cancel()
                return PreflightQcScan(
                    results=_ordered_results(indexed_results),
                    cancelled=True,
                )

            done, _pending = wait(
                futures,
                timeout=0.1,
                return_when=FIRST_COMPLETED,
            )
            if not done:
                continue

            for future in done:
                index, info = futures.pop(future)
                file_path = Path(info.path)
                if not future.cancelled():
                    try:
                        indexed_results[index] = future.result()
                    except _PreflightQcCancelled:
                        for pending_future in futures:
                            pending_future.cancel()
                        return PreflightQcScan(
                            results=_ordered_results(indexed_results),
                            cancelled=True,
                        )
                completed += 1
                if progress:
                    progress(f"Finished {file_path.name}", completed, total)
            _submit_next(executor)

    return PreflightQcScan(results=_ordered_results(indexed_results), cancelled=False)


def scan_preprocessing_qc(
    raw_file_infos: Sequence[RawFileInfo],
    settings: Mapping[str, Any],
    *,
    skip_paths: Sequence[Path] = (),
    max_workers: int | None = None,
    progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
    project_root: Path | None = None,
    event_map: Mapping[str, int] | None = None,
) -> PreflightQcScan:
    """Run analyzed-interval preflight QC or report that it was not evaluated.

    Signal-based QC requires both an explicit project root and condition event
    map. Callers without that context receive a planning result and no EEG
    samples are scored.
    """

    skip_keys = {_path_key(Path(path)) for path in skip_paths}
    pending_infos = [
        info for info in raw_file_infos if _path_key(Path(info.path)) not in skip_keys
    ]
    total = len(pending_infos)
    # The preflight review must observe the project's explicit detector mode.
    # In particular, an Off project must not acquire detector findings merely
    # because the scan runs before preprocessing.
    qc_settings = dict(settings)
    oddball_frequency_hz: float | None = None
    frequency_protocol_fingerprint = ""
    raw_protocol = qc_settings.get("frequency_protocol")
    if raw_protocol is not None:
        try:
            frequency_protocol = normalize_frequency_protocol(raw_protocol)
        except FrequencyProtocolError:
            frequency_protocol = None
        if frequency_protocol is not None:
            frequency_protocol_fingerprint = frequency_protocol.fingerprint
            if (
                frequency_protocol.is_ready
                and frequency_protocol.oddball_rate_hz is not None
            ):
                oddball_frequency_hz = float(frequency_protocol.oddball_rate_hz)
    resolved_event_map = (
        {str(label): int(code) for label, code in event_map.items()}
        if event_map
        else None
    )
    resolved_project_root = Path(project_root) if project_root is not None else None
    io_semaphore = threading.BoundedSemaphore(PREFLIGHT_QC_MAX_IO_READERS)
    spectral_semaphore = threading.BoundedSemaphore(
        PREFLIGHT_QC_MAX_SPECTRAL_WORKERS
    )
    worker_count = _preflight_worker_count(total, max_workers)
    if worker_count <= 1:
        scan = _scan_preprocessing_qc_serial(
            pending_infos,
            qc_settings,
            project_root=resolved_project_root,
            event_map=resolved_event_map,
            io_semaphore=io_semaphore,
            spectral_semaphore=spectral_semaphore,
            progress=progress,
            should_cancel=should_cancel,
        )
    else:
        scan = _scan_preprocessing_qc_parallel(
            pending_infos,
            qc_settings,
            max_workers=worker_count,
            project_root=resolved_project_root,
            event_map=resolved_event_map,
            io_semaphore=io_semaphore,
            spectral_semaphore=spectral_semaphore,
            progress=progress,
            should_cancel=should_cancel,
        )
    return replace(
        scan,
        oddball_frequency_hz=oddball_frequency_hz,
        frequency_protocol_fingerprint=frequency_protocol_fingerprint,
    )


__all__ = [
    "BDF_RECORDING_NOT_STARTED_REASON",
    "HeaderOnlyPreflight",
    "PreflightConditionCropGridAudit",
    "PreflightConditionCropObservation",
    "PreflightQcFileResult",
    "PreflightQcScan",
    "build_preflight_condition_crop_grid_audit",
    "preflight_file_settings_identity",
    "scan_preprocessing_qc",
    "scan_recording_not_started_files",
]

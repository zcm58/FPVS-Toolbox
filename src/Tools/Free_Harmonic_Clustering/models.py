"""Immutable public models for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import numpy as np


METHOD_VERSION = "hermann_free_harmonic_clustering_cleanroom_v2"
REPEATED_SESSION_BATCH_VERSION = "fhc_repeated_session_batch_v1"
SENSOR_ADJACENCY_VERSION = "biosemi64-fieldtrip-style-compressed-cleanroom-v1"


class FreeHarmonicError(RuntimeError):
    """Base error for the clean-room Free Harmonic Clustering backend."""


class FreeHarmonicInputError(FreeHarmonicError):
    """Raised when managed project inputs cannot form the requested cohort."""


class FreeHarmonicPreparationError(FreeHarmonicError):
    """Raised when spectral tensors violate the locked preparation contract."""


class NoHarmonicsSelectedError(FreeHarmonicPreparationError):
    """Structured paper-selector outcome when neither arm crosses threshold."""

    code = "NO_HARMONICS_SELECTED"

    def __init__(
        self,
        *,
        candidate_orders: object,
        candidate_harmonics_hz: object,
        arm_a_z: object,
        arm_b_z: object,
        z_threshold: float,
    ) -> None:
        arrays = tuple(
            np.array(value, dtype=dtype, copy=True, order="C")
            for value, dtype in (
                (candidate_orders, np.int64),
                (candidate_harmonics_hz, np.float64),
                (arm_a_z, np.float64),
                (arm_b_z, np.float64),
            )
        )
        if any(array.ndim != 1 for array in arrays) or len({array.size for array in arrays}) != 1:
            raise ValueError("No-harmonics diagnostic arrays must be aligned vectors.")
        for array in arrays:
            array.setflags(write=False)
        threshold = float(z_threshold)
        if not np.isfinite(threshold):
            raise ValueError("z_threshold must be finite.")
        (
            self.candidate_orders,
            self.candidate_harmonics_hz,
            self.arm_a_z,
            self.arm_b_z,
        ) = arrays
        self.z_threshold = threshold
        super().__init__(
            "No eligible non-base harmonic exceeded the strict grand-spectrum "
            f"z > {threshold:g} threshold in either arm."
        )


class FreeHarmonicCancelledError(FreeHarmonicError):
    """Raised at a safe boundary after a caller requests cancellation."""


class AnalysisDesign(str, Enum):
    """Supported whole-participant exchangeability designs."""

    INDEPENDENT_GROUPS = "independent_groups"
    PAIRED_CONDITIONS = "paired_conditions"


class RepeatedSessionContrastFamily(str, Enum):
    """Prespecified repeated-session scientific contrast families."""

    SESSION_AVERAGED_GROUPS = "session_averaged_groups"
    PAIRED_SESSIONS_WITHIN_GROUP = "paired_sessions_within_group"
    GROUP_SESSION_CHANGE = "group_session_change"


class RepeatedSessionTensorSemantics(str, Enum):
    """How repeated-session run tensors were derived before inference."""

    SESSION_AVERAGED_NORMALIZED_PROFILE = "session_averaged_candidate_snr_then_l2_normalized"
    SESSION_NORMALIZED_PAIRED_PROFILE = "each_session_snr_l2_normalized"
    NORMALIZED_SESSION_CHANGE = "l2_normalized_session_a_minus_l2_normalized_session_b"


class HarmonicSelectionMode(str, Enum):
    """Supported harmonic-domain selection policies."""

    AUTOMATIC = "automatic"
    FIXED_HIGHEST = "fixed_highest"


def _nonempty_text(value: object, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty.")
    return text


def _tuple_text(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _readonly_array(
    value: object,
    *,
    dtype: np.dtype | type,
    ndim: int | None = None,
    field_name: str,
) -> np.ndarray:
    array = np.array(value, dtype=dtype, copy=True, order="C")
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{field_name} must have {ndim} dimensions; got {array.ndim}.")
    array.setflags(write=False)
    return array


@dataclass(frozen=True, slots=True)
class FreeHarmonicMethodSpec:
    """Versioned scientific settings frozen into every prepared contrast."""

    method_version: str = METHOD_VERSION
    oddball_frequency_hz: float = 1.2
    base_frequency_hz: float = 6.0
    max_harmonic_hz: float = 48.0
    harmonic_selection_mode: HarmonicSelectionMode = HarmonicSelectionMode.AUTOMATIC
    fixed_highest_harmonic_order: int | None = None
    noise_half_width_hz: float = 0.1
    harmonic_z_threshold: float = 3.29
    harmonic_z_ddof: int = 1
    cluster_entry_alpha: float = 0.01
    cluster_alpha_per_tail: float = 0.025
    n_permutations: int = 10_000
    seed: int = 1729
    sensor_adjacency_version: str = SENSOR_ADJACENCY_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "method_version",
            _nonempty_text(self.method_version, field_name="method_version"),
        )
        object.__setattr__(
            self,
            "sensor_adjacency_version",
            _nonempty_text(
                self.sensor_adjacency_version,
                field_name="sensor_adjacency_version",
            ),
        )
        try:
            selection_mode = (
                self.harmonic_selection_mode
                if isinstance(
                    self.harmonic_selection_mode,
                    HarmonicSelectionMode,
                )
                else HarmonicSelectionMode(str(self.harmonic_selection_mode))
            )
        except ValueError as exc:
            raise ValueError("harmonic_selection_mode must be 'automatic' or 'fixed_highest'.") from exc
        object.__setattr__(
            self,
            "harmonic_selection_mode",
            selection_mode,
        )
        fixed_order = self.fixed_highest_harmonic_order
        if selection_mode is HarmonicSelectionMode.AUTOMATIC:
            if fixed_order is not None:
                raise ValueError("fixed_highest_harmonic_order must be omitted in automatic harmonic-selection mode.")
        else:
            if fixed_order is None or isinstance(fixed_order, bool) or int(fixed_order) < 1:
                raise ValueError("fixed_highest mode requires a positive integer fixed_highest_harmonic_order.")
            object.__setattr__(
                self,
                "fixed_highest_harmonic_order",
                int(fixed_order),
            )
        for field_name in (
            "oddball_frequency_hz",
            "base_frequency_hz",
            "max_harmonic_hz",
            "noise_half_width_hz",
            "harmonic_z_threshold",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive.")
            object.__setattr__(self, field_name, value)
        if self.max_harmonic_hz < self.oddball_frequency_hz:
            raise ValueError("max_harmonic_hz must include at least one oddball harmonic.")
        if isinstance(self.harmonic_z_ddof, bool) or int(self.harmonic_z_ddof) < 0:
            raise ValueError("harmonic_z_ddof must be a non-negative integer.")
        object.__setattr__(self, "harmonic_z_ddof", int(self.harmonic_z_ddof))
        for field_name in ("cluster_entry_alpha", "cluster_alpha_per_tail"):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or not 0.0 < value < 1.0:
                raise ValueError(f"{field_name} must be strictly between zero and one.")
            object.__setattr__(self, field_name, value)
        if isinstance(self.n_permutations, bool) or int(self.n_permutations) < 1:
            raise ValueError("n_permutations must be a positive integer.")
        if isinstance(self.seed, bool) or int(self.seed) < 0:
            raise ValueError("seed must be a non-negative integer.")
        object.__setattr__(self, "n_permutations", int(self.n_permutations))
        object.__setattr__(self, "seed", int(self.seed))


@dataclass(frozen=True, slots=True)
class ProjectContrastRequest:
    """One managed-project contrast and its ordered analysis arms."""

    project_root: Path
    design: AnalysisDesign
    condition_a: str
    condition_b: str | None = None
    group_ids: tuple[str, ...] = ()
    session_ids: tuple[str, ...] = ()
    contrast_family_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root))
        try:
            design = self.design if isinstance(self.design, AnalysisDesign) else AnalysisDesign(str(self.design))
        except ValueError as exc:
            raise ValueError(f"Unsupported analysis design: {self.design!r}.") from exc
        object.__setattr__(self, "design", design)
        condition_a = _nonempty_text(self.condition_a, field_name="condition_a")
        condition_b = (
            None if self.condition_b in (None, "") else _nonempty_text(self.condition_b, field_name="condition_b")
        )
        groups = _tuple_text(self.group_ids)
        sessions = _tuple_text(self.session_ids)
        if len({group.casefold() for group in groups}) != len(groups):
            raise ValueError("group_ids must contain distinct canonical group IDs.")
        if len({session.casefold() for session in sessions}) != len(sessions):
            raise ValueError("session_ids must contain distinct canonical session IDs.")
        family_id = (
            None
            if self.contrast_family_id in (None, "")
            else _nonempty_text(
                self.contrast_family_id,
                field_name="contrast_family_id",
            )
        )
        if sessions and len(sessions) != 2:
            raise ValueError("Repeated-session contrasts require two ordered session_ids.")
        if bool(sessions) != bool(family_id):
            raise ValueError("session_ids and contrast_family_id must be supplied together.")
        if design is AnalysisDesign.INDEPENDENT_GROUPS:
            if condition_b is not None:
                raise ValueError("independent_groups uses one condition; condition_b must be omitted.")
            if len(groups) != 2:
                raise ValueError("independent_groups requires two ordered canonical group_ids.")
        else:
            if condition_b is None:
                raise ValueError("paired_conditions requires condition_b.")
            if condition_a.casefold() == condition_b.casefold() and not sessions:
                raise ValueError("paired_conditions requires two distinct conditions.")
            if len(groups) > 1:
                raise ValueError("paired_conditions accepts at most one canonical group filter.")
            if sessions and len(groups) != 1:
                raise ValueError("Repeated paired-session contrasts require one canonical group filter.")
        object.__setattr__(self, "condition_a", condition_a)
        object.__setattr__(self, "condition_b", condition_b)
        object.__setattr__(self, "group_ids", groups)
        object.__setattr__(self, "session_ids", sessions)
        object.__setattr__(self, "contrast_family_id", family_id)


@dataclass(frozen=True, slots=True)
class RecordingExclusionRequest:
    """One explicit recording exclusion with an optional user explanation."""

    recording_id: str
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "recording_id", _nonempty_text(self.recording_id, field_name="recording_id")
        )
        object.__setattr__(self, "reason", str(self.reason or "").strip() or "No reason provided")


@dataclass(frozen=True, slots=True)
class RepeatedSessionBatchRequest:
    """One versioned, phase-balanced repeated-session FHC batch.

    ``group_ids`` are ordered A-minus-B. ``session_ids`` are likewise ordered
    A-minus-B and therefore encode the requested change direction explicitly
    (for example, Visit 2 minus Visit 1).
    """

    project_root: Path
    conditions: tuple[str, ...]
    group_ids: tuple[str, str]
    session_ids: tuple[str, str]
    recording_exclusions: tuple[RecordingExclusionRequest, ...] = ()
    batch_version: str = REPEATED_SESSION_BATCH_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root))
        conditions = _tuple_text(self.conditions)
        groups = _tuple_text(self.group_ids)
        sessions = _tuple_text(self.session_ids)
        if not conditions:
            raise ValueError("Repeated-session batches require conditions.")
        if len({value.casefold() for value in conditions}) != len(conditions):
            raise ValueError("conditions must contain distinct labels.")
        if len(groups) != 2 or len({value.casefold() for value in groups}) != 2:
            raise ValueError("Repeated-session batches require two ordered canonical group_ids.")
        if len(sessions) != 2 or len({value.casefold() for value in sessions}) != 2:
            raise ValueError("Repeated-session batches require two ordered canonical session_ids.")
        exclusions = tuple(self.recording_exclusions)
        if any(not isinstance(row, RecordingExclusionRequest) for row in exclusions):
            raise TypeError("recording_exclusions must contain RecordingExclusionRequest values.")
        if len({row.recording_id.casefold() for row in exclusions}) != len(exclusions):
            raise ValueError("recording_exclusions must be unique by recording_id.")
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "group_ids", groups)
        object.__setattr__(self, "session_ids", sessions)
        object.__setattr__(self, "recording_exclusions", exclusions)
        batch_version = _nonempty_text(
            self.batch_version,
            field_name="batch_version",
        )
        if batch_version != REPEATED_SESSION_BATCH_VERSION:
            raise ValueError(f"Unsupported repeated-session batch version {batch_version!r}.")
        object.__setattr__(self, "batch_version", batch_version)


@dataclass(frozen=True, slots=True)
class ProjectGroupOption:
    """One canonical managed-project group exposed for GUI selection."""

    group_id: str
    label: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "group_id",
            _nonempty_text(self.group_id, field_name="group_id"),
        )
        object.__setattr__(
            self,
            "label",
            _nonempty_text(self.label, field_name="label"),
        )


@dataclass(frozen=True, slots=True)
class ProjectSessionOption:
    """One canonical session exposed for repeated-session setup."""

    session_id: str
    label: str
    visit_index: int

    def __post_init__(self) -> None:
        for field_name in ("session_id", "label"):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        visit_index = int(self.visit_index)
        if isinstance(self.visit_index, bool) or visit_index < 1:
            raise ValueError("visit_index must be a positive integer.")
        object.__setattr__(self, "visit_index", visit_index)


@dataclass(frozen=True, slots=True)
class ProjectRecordingOption:
    """Canonical recording identity for analysis-only exclusion setup."""

    recording_id: str
    participant_id: str
    group_id: str
    group_label: str
    session_id: str
    session_label: str
    visit_index: int

    def __post_init__(self) -> None:
        for field_name in (
            "recording_id",
            "participant_id",
            "group_id",
            "group_label",
            "session_id",
            "session_label",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        visit_index = int(self.visit_index)
        if isinstance(self.visit_index, bool) or visit_index < 1:
            raise ValueError("visit_index must be a positive integer.")
        object.__setattr__(self, "visit_index", visit_index)


@dataclass(frozen=True, slots=True)
class ProjectAnalysisOptions:
    """Read-only project/header inspection for analysis setup.

    This model contains only canonical metadata and header-derived frequency
    availability.  Building it never reads amplitude cells or writes output.
    """

    project_root: Path
    conditions: tuple[str, ...]
    groups: tuple[ProjectGroupOption, ...]
    workbook_count: int
    representative_workbook_relative_path: str
    grid_compatible: bool
    grid_compatibility_verified: bool
    compatibility_message: str
    grid_fingerprint: str
    frequency_resolution_hz: float
    fft_upper_frequency_hz: float
    effective_harmonic_upper_frequency_hz: float
    eligible_orders: tuple[int, ...]
    eligible_harmonics_hz: tuple[float, ...]
    excluded_base_orders: tuple[int, ...]
    excluded_base_harmonics_hz: tuple[float, ...]
    incompatible_workbooks: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    sessions: tuple[ProjectSessionOption, ...] = ()
    recordings: tuple[ProjectRecordingOption, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root))
        conditions = _tuple_text(self.conditions)
        groups = tuple(self.groups)
        if not conditions:
            raise ValueError("ProjectAnalysisOptions requires conditions.")
        if any(not isinstance(group, ProjectGroupOption) for group in groups):
            raise TypeError("groups must contain ProjectGroupOption values.")
        if len({group.group_id.casefold() for group in groups}) != len(groups):
            raise ValueError("Project group IDs must be distinct.")
        count = int(self.workbook_count)
        if count < 1:
            raise ValueError("workbook_count must be positive.")
        for field_name in (
            "representative_workbook_relative_path",
            "compatibility_message",
            "grid_fingerprint",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "frequency_resolution_hz",
            "fft_upper_frequency_hz",
            "effective_harmonic_upper_frequency_hz",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value <= 0.0:
                raise ValueError(f"{field_name} must be finite and positive.")
            object.__setattr__(self, field_name, value)
        eligible_orders = tuple(int(value) for value in self.eligible_orders)
        eligible_hz = tuple(float(value) for value in self.eligible_harmonics_hz)
        excluded_orders = tuple(int(value) for value in self.excluded_base_orders)
        excluded_hz = tuple(float(value) for value in self.excluded_base_harmonics_hz)
        if not eligible_orders or len(eligible_orders) != len(eligible_hz):
            raise ValueError("Eligible harmonic orders/frequencies must align.")
        if len(excluded_orders) != len(excluded_hz):
            raise ValueError("Excluded base-overlap orders/frequencies must align.")
        if any(value < 1 for value in (*eligible_orders, *excluded_orders)):
            raise ValueError("Harmonic orders must be positive.")
        if any(not np.isfinite(value) or value <= 0.0 for value in (*eligible_hz, *excluded_hz)):
            raise ValueError("Harmonic frequencies must be finite and positive.")
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "workbook_count", count)
        object.__setattr__(self, "grid_compatible", bool(self.grid_compatible))
        object.__setattr__(
            self,
            "grid_compatibility_verified",
            bool(self.grid_compatibility_verified),
        )
        object.__setattr__(self, "eligible_orders", eligible_orders)
        object.__setattr__(self, "eligible_harmonics_hz", eligible_hz)
        object.__setattr__(self, "excluded_base_orders", excluded_orders)
        object.__setattr__(self, "excluded_base_harmonics_hz", excluded_hz)
        object.__setattr__(
            self,
            "incompatible_workbooks",
            _tuple_text(self.incompatible_workbooks),
        )
        object.__setattr__(self, "diagnostics", _tuple_text(self.diagnostics))
        sessions = tuple(self.sessions)
        recordings = tuple(self.recordings)
        if any(not isinstance(row, ProjectSessionOption) for row in sessions):
            raise TypeError("sessions must contain ProjectSessionOption values.")
        if any(not isinstance(row, ProjectRecordingOption) for row in recordings):
            raise TypeError("recordings must contain ProjectRecordingOption values.")
        if len({row.session_id.casefold() for row in sessions}) != len(sessions):
            raise ValueError("Project session IDs must be distinct.")
        if len({row.visit_index for row in sessions}) != len(sessions):
            raise ValueError("Project session visit indices must be distinct.")
        if len({row.recording_id.casefold() for row in recordings}) != len(recordings):
            raise ValueError("Project recording IDs must be distinct.")
        session_keys = {row.session_id.casefold() for row in sessions}
        group_keys = {row.group_id.casefold() for row in groups}
        if recordings and not sessions:
            raise ValueError("Recording options require canonical session options.")
        if any(row.session_id.casefold() not in session_keys for row in recordings):
            raise ValueError("Recording options reference an unknown session_id.")
        if any(row.group_id.casefold() not in group_keys for row in recordings):
            raise ValueError("Recording options reference an unknown group_id.")
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "recordings", recordings)


@dataclass(frozen=True, slots=True)
class FrequencyWindowPlan:
    """One common FullFFT grid and its deduplicated selected-column plan."""

    full_frequency_columns: tuple[str, ...]
    full_frequencies_hz: np.ndarray
    selected_frequency_columns: tuple[str, ...]
    selected_frequencies_hz: np.ndarray
    candidate_orders: np.ndarray
    candidate_harmonics_hz: np.ndarray
    excluded_base_orders: np.ndarray
    excluded_base_harmonics_hz: np.ndarray
    target_selected_indices: np.ndarray
    noise_selected_indices: np.ndarray
    frequency_resolution_hz: float
    grid_fingerprint: str
    selected_columns_fingerprint: str
    electrode_column: str = "Electrode"

    def __post_init__(self) -> None:
        full_columns = _tuple_text(self.full_frequency_columns)
        selected_columns = _tuple_text(self.selected_frequency_columns)
        if not full_columns or not selected_columns:
            raise ValueError("FrequencyWindowPlan requires frequency columns.")
        if len(set(full_columns)) != len(full_columns):
            raise ValueError("FullFFT frequency columns must be unique.")
        if len(set(selected_columns)) != len(selected_columns):
            raise ValueError("Selected FullFFT frequency columns must be unique.")
        full_frequencies = _readonly_array(
            self.full_frequencies_hz,
            dtype=np.float64,
            ndim=1,
            field_name="full_frequencies_hz",
        )
        selected_frequencies = _readonly_array(
            self.selected_frequencies_hz,
            dtype=np.float64,
            ndim=1,
            field_name="selected_frequencies_hz",
        )
        candidate_orders = _readonly_array(
            self.candidate_orders,
            dtype=np.int64,
            ndim=1,
            field_name="candidate_orders",
        )
        candidate_harmonics = _readonly_array(
            self.candidate_harmonics_hz,
            dtype=np.float64,
            ndim=1,
            field_name="candidate_harmonics_hz",
        )
        excluded_orders = _readonly_array(
            self.excluded_base_orders,
            dtype=np.int64,
            ndim=1,
            field_name="excluded_base_orders",
        )
        excluded_harmonics = _readonly_array(
            self.excluded_base_harmonics_hz,
            dtype=np.float64,
            ndim=1,
            field_name="excluded_base_harmonics_hz",
        )
        targets = _readonly_array(
            self.target_selected_indices,
            dtype=np.int64,
            ndim=1,
            field_name="target_selected_indices",
        )
        noise = _readonly_array(
            self.noise_selected_indices,
            dtype=np.int64,
            ndim=2,
            field_name="noise_selected_indices",
        )
        if len(full_columns) != full_frequencies.size:
            raise ValueError("FullFFT column/frequency counts do not match.")
        if len(selected_columns) != selected_frequencies.size:
            raise ValueError("Selected column/frequency counts do not match.")
        candidate_count = candidate_orders.size
        if not candidate_count:
            raise ValueError("FrequencyWindowPlan requires eligible harmonics.")
        if candidate_harmonics.size != candidate_count or targets.size != candidate_count:
            raise ValueError("Candidate harmonic arrays must have matching lengths.")
        if noise.shape[0] != candidate_count or noise.shape[1] < 2:
            raise ValueError("Every candidate requires at least two noise bins.")
        if np.any(targets < 0) or np.any(targets >= len(selected_columns)):
            raise ValueError("Target indices exceed the selected-column plan.")
        if np.any(noise < 0) or np.any(noise >= len(selected_columns)):
            raise ValueError("Noise indices exceed the selected-column plan.")
        resolution = float(self.frequency_resolution_hz)
        if not np.isfinite(resolution) or resolution <= 0.0:
            raise ValueError("frequency_resolution_hz must be finite and positive.")
        object.__setattr__(self, "full_frequency_columns", full_columns)
        object.__setattr__(self, "selected_frequency_columns", selected_columns)
        object.__setattr__(self, "full_frequencies_hz", full_frequencies)
        object.__setattr__(self, "selected_frequencies_hz", selected_frequencies)
        object.__setattr__(self, "candidate_orders", candidate_orders)
        object.__setattr__(self, "candidate_harmonics_hz", candidate_harmonics)
        object.__setattr__(self, "excluded_base_orders", excluded_orders)
        object.__setattr__(self, "excluded_base_harmonics_hz", excluded_harmonics)
        object.__setattr__(self, "target_selected_indices", targets)
        object.__setattr__(self, "noise_selected_indices", noise)
        object.__setattr__(self, "frequency_resolution_hz", resolution)
        object.__setattr__(
            self,
            "grid_fingerprint",
            _nonempty_text(self.grid_fingerprint, field_name="grid_fingerprint"),
        )
        object.__setattr__(
            self,
            "selected_columns_fingerprint",
            _nonempty_text(
                self.selected_columns_fingerprint,
                field_name="selected_columns_fingerprint",
            ),
        )
        object.__setattr__(
            self,
            "electrode_column",
            _nonempty_text(self.electrode_column, field_name="electrode_column"),
        )

    @property
    def required_columns(self) -> tuple[str, ...]:
        return (self.electrode_column, *self.selected_frequency_columns)

    @property
    def candidate_count(self) -> int:
        return int(self.candidate_orders.size)


@dataclass(frozen=True, slots=True)
class HarmonicSelection:
    """Grand-spectrum z audit and retained fill-through harmonic domain."""

    candidate_orders: np.ndarray
    candidate_harmonics_hz: np.ndarray
    arm_a_z: np.ndarray
    arm_b_z: np.ndarray
    detected_arm_a: np.ndarray
    detected_arm_b: np.ndarray
    selected_candidate_indices: np.ndarray
    selected_orders: np.ndarray
    selected_harmonics_hz: np.ndarray
    excluded_base_orders: np.ndarray
    excluded_base_harmonics_hz: np.ndarray
    z_threshold: float
    z_ddof: int
    highest_detected_order: int | None
    selection_mode: HarmonicSelectionMode = HarmonicSelectionMode.AUTOMATIC
    fixed_highest_harmonic_order: int | None = None

    def __post_init__(self) -> None:
        one_dimensional = {
            "candidate_orders": (self.candidate_orders, np.int64),
            "candidate_harmonics_hz": (self.candidate_harmonics_hz, np.float64),
            "arm_a_z": (self.arm_a_z, np.float64),
            "arm_b_z": (self.arm_b_z, np.float64),
            "detected_arm_a": (self.detected_arm_a, np.bool_),
            "detected_arm_b": (self.detected_arm_b, np.bool_),
            "selected_candidate_indices": (
                self.selected_candidate_indices,
                np.int64,
            ),
            "selected_orders": (self.selected_orders, np.int64),
            "selected_harmonics_hz": (self.selected_harmonics_hz, np.float64),
            "excluded_base_orders": (self.excluded_base_orders, np.int64),
            "excluded_base_harmonics_hz": (
                self.excluded_base_harmonics_hz,
                np.float64,
            ),
        }
        normalized: dict[str, np.ndarray] = {}
        for field_name, (value, dtype) in one_dimensional.items():
            normalized[field_name] = _readonly_array(
                value,
                dtype=dtype,
                ndim=1,
                field_name=field_name,
            )
        candidate_count = normalized["candidate_orders"].size
        for field_name in (
            "candidate_harmonics_hz",
            "arm_a_z",
            "arm_b_z",
            "detected_arm_a",
            "detected_arm_b",
        ):
            if normalized[field_name].size != candidate_count:
                raise ValueError(f"{field_name} must match the candidate count.")
        selected_indices = normalized["selected_candidate_indices"]
        if not selected_indices.size:
            raise ValueError("At least one harmonic must be retained.")
        if np.any(selected_indices < 0) or np.any(selected_indices >= candidate_count):
            raise ValueError("selected_candidate_indices exceed the candidate domain.")
        if (
            normalized["selected_orders"].size != selected_indices.size
            or normalized["selected_harmonics_hz"].size != selected_indices.size
        ):
            raise ValueError("Selected harmonic arrays must have matching lengths.")
        for field_name, value in normalized.items():
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "z_threshold", float(self.z_threshold))
        object.__setattr__(self, "z_ddof", int(self.z_ddof))
        try:
            selection_mode = (
                self.selection_mode
                if isinstance(self.selection_mode, HarmonicSelectionMode)
                else HarmonicSelectionMode(str(self.selection_mode))
            )
        except ValueError as exc:
            raise ValueError("Unsupported harmonic selection mode.") from exc
        highest_detected = self.highest_detected_order
        if highest_detected is not None:
            highest_detected = int(highest_detected)
            if highest_detected < 1:
                raise ValueError("highest_detected_order must be positive when set.")
        fixed_order = self.fixed_highest_harmonic_order
        if selection_mode is HarmonicSelectionMode.AUTOMATIC:
            if fixed_order is not None:
                raise ValueError("Automatic selection cannot record a fixed harmonic ceiling.")
        else:
            if fixed_order is None or int(fixed_order) < 1:
                raise ValueError("Fixed selection requires fixed_highest_harmonic_order.")
            fixed_order = int(fixed_order)
            if fixed_order != int(normalized["selected_orders"][-1]):
                raise ValueError("Fixed harmonic ceiling must equal the highest retained order.")
        object.__setattr__(self, "highest_detected_order", highest_detected)
        object.__setattr__(self, "selection_mode", selection_mode)
        object.__setattr__(self, "fixed_highest_harmonic_order", fixed_order)


@dataclass(frozen=True, slots=True)
class CohortWorkbook:
    """Provenance for one workbook consumed exactly once for amplitudes."""

    arm: str
    arm_label: str
    participant_id: str
    condition: str
    group_id: str | None
    group_label: str | None
    source_path: Path
    project_relative_path: str
    header_read_seconds: float
    amplitude_read_seconds: float
    recording_id: str | None = None
    session_id: str | None = None
    session_label: str | None = None
    visit_index: int | None = None

    def __post_init__(self) -> None:
        arm = str(self.arm).strip().casefold()
        if arm not in {"a", "b"}:
            raise ValueError("arm must be 'a' or 'b'.")
        object.__setattr__(self, "arm", arm)
        for field_name in (
            "arm_label",
            "participant_id",
            "condition",
            "project_relative_path",
        ):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(self, "source_path", Path(self.source_path))
        for field_name in ("header_read_seconds", "amplitude_read_seconds"):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{field_name} must be finite and non-negative.")
            object.__setattr__(self, field_name, value)
        repeated_values = tuple(
            None if value in (None, "") else str(value).strip()
            for value in (
                self.recording_id,
                self.session_id,
                self.session_label,
            )
        )
        if any(repeated_values) and not all(repeated_values):
            raise ValueError("Recording/session workbook identity must be supplied together.")
        visit_index = self.visit_index
        if all(repeated_values):
            if visit_index is None or isinstance(visit_index, bool) or int(visit_index) < 1:
                raise ValueError("Repeated-session workbooks require a positive visit_index.")
            visit_index = int(visit_index)
        elif visit_index is not None:
            raise ValueError("visit_index requires recording/session workbook identity.")
        object.__setattr__(self, "recording_id", repeated_values[0])
        object.__setattr__(self, "session_id", repeated_values[1])
        object.__setattr__(self, "session_label", repeated_values[2])
        object.__setattr__(self, "visit_index", visit_index)


@dataclass(frozen=True, slots=True)
class ParticipantConditionExclusion:
    """One canonical project-level participant-condition exclusion."""

    participant_id: str
    condition: str
    reason: str = "Project participant-condition exclusion"

    def __post_init__(self) -> None:
        for field_name in ("participant_id", "condition", "reason"):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )


@dataclass(frozen=True, slots=True)
class RepeatedSessionCohortAuditRow:
    """Complete-pair eligibility for one participant x condition cell."""

    participant_id: str
    group_id: str
    condition: str
    available_session_ids: tuple[str, ...]
    missing_session_ids: tuple[str, ...]
    recording_ids_by_session: tuple[tuple[str, str], ...] = ()
    excluded_recording_ids: tuple[str, ...] = ()
    excluded_session_ids: tuple[str, ...] = ()
    exclusion_reasons: tuple[str, ...] = ()
    included_complete_pair: bool = False

    def __post_init__(self) -> None:
        for field_name in ("participant_id", "group_id", "condition"):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        available = _tuple_text(self.available_session_ids)
        missing = _tuple_text(self.missing_session_ids)
        if set(value.casefold() for value in available).intersection(value.casefold() for value in missing):
            raise ValueError("Available and missing session IDs must not overlap.")
        recording_rows = tuple(
            (
                _nonempty_text(session_id, field_name="recording session_id"),
                _nonempty_text(recording_id, field_name="recording_id"),
            )
            for session_id, recording_id in self.recording_ids_by_session
        )
        if len({session.casefold() for session, _ in recording_rows}) != len(recording_rows):
            raise ValueError("recording_ids_by_session must be unique by session.")
        excluded_recordings = _tuple_text(self.excluded_recording_ids)
        excluded_sessions = _tuple_text(self.excluded_session_ids)
        reasons = _tuple_text(self.exclusion_reasons)
        if not (len(excluded_recordings) == len(excluded_sessions) == len(reasons)):
            raise ValueError("Excluded recording IDs, session IDs, and reasons must align.")
        included = bool(self.included_complete_pair)
        if included and missing:
            raise ValueError("A complete-pair audit row cannot have missing sessions.")
        object.__setattr__(self, "available_session_ids", available)
        object.__setattr__(self, "missing_session_ids", missing)
        object.__setattr__(self, "recording_ids_by_session", recording_rows)
        object.__setattr__(self, "excluded_recording_ids", excluded_recordings)
        object.__setattr__(self, "excluded_session_ids", excluded_sessions)
        object.__setattr__(self, "exclusion_reasons", reasons)
        object.__setattr__(self, "included_complete_pair", included)


@dataclass(frozen=True, slots=True)
class SharedHarmonicSelectionAudit:
    """Equal-cell automatic selector audit for one repeated-session batch."""

    cell_labels: tuple[str, ...]
    cell_group_ids: tuple[str, ...]
    cell_session_ids: tuple[str, ...]
    cell_conditions: tuple[str, ...]
    cell_participant_counts: tuple[int, ...]
    z_scores: np.ndarray
    detected: np.ndarray

    def __post_init__(self) -> None:
        labels = _tuple_text(self.cell_labels)
        groups = _tuple_text(self.cell_group_ids)
        sessions = _tuple_text(self.cell_session_ids)
        conditions = _tuple_text(self.cell_conditions)
        counts = tuple(int(value) for value in self.cell_participant_counts)
        cell_count = len(labels)
        if not cell_count or any(len(values) != cell_count for values in (groups, sessions, conditions, counts)):
            raise ValueError("Shared selector cell metadata must be aligned.")
        if any(value < 1 for value in counts):
            raise ValueError("Every shared selector cell must contain participants.")
        z_scores = _readonly_array(
            self.z_scores,
            dtype=np.float64,
            ndim=2,
            field_name="z_scores",
        )
        detected = _readonly_array(
            self.detected,
            dtype=np.bool_,
            ndim=2,
            field_name="detected",
        )
        if z_scores.shape != detected.shape or z_scores.shape[0] != cell_count:
            raise ValueError("Shared selector z/detection arrays must align to cells.")
        if not np.all(np.isfinite(z_scores)):
            raise ValueError("Shared selector z scores must be finite.")
        object.__setattr__(self, "cell_labels", labels)
        object.__setattr__(self, "cell_group_ids", groups)
        object.__setattr__(self, "cell_session_ids", sessions)
        object.__setattr__(self, "cell_conditions", conditions)
        object.__setattr__(self, "cell_participant_counts", counts)
        object.__setattr__(self, "z_scores", z_scores)
        object.__setattr__(self, "detected", detected)


@dataclass(frozen=True, slots=True)
class PreparationProvenance:
    """Run-level cohort, I/O, and preparation audit."""

    source_sheet: str
    grid_fingerprint: str
    selected_columns_fingerprint: str
    frequency_resolution_hz: float
    full_frequency_column_count: int
    selected_frequency_column_count: int
    workbook_count: int
    header_read_seconds: float
    amplitude_read_seconds: float
    numeric_preparation_seconds: float
    total_seconds: float
    reader_phase_seconds: tuple[tuple[str, float], ...] = ()
    ledger_filter_applied: bool = False
    completed_participants: tuple[str, ...] = ()
    ledger_excluded_participants: tuple[str, ...] = ()
    manual_excluded_participants: tuple[str, ...] = ()
    frequency_qc_excluded_participants: tuple[str, ...] = ()
    completed_recordings: tuple[str, ...] = ()
    ledger_excluded_recordings: tuple[str, ...] = ()
    frequency_qc_excluded_recordings: tuple[str, ...] = ()
    incomplete_pair_participants: tuple[str, ...] = ()
    participant_condition_exclusions: tuple[
        ParticipantConditionExclusion,
        ...,
    ] = ()
    dataset_diagnostics: tuple[str, ...] = ()
    full_fft_provenance_method_version: str = ""
    full_fft_source_fingerprint: str = ""
    full_fft_cohort_fingerprint: str = ""
    full_fft_frequency_qc_fingerprint: str = ""
    full_fft_processing_export_fingerprint: str = ""
    repeated_session_batch_version: str = ""
    shared_domain_fingerprint: str = ""
    request_recording_exclusions: tuple[RecordingExclusionRequest, ...] = ()
    repeated_session_cohort_audit: tuple[RepeatedSessionCohortAuditRow, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("source_sheet", "grid_fingerprint", "selected_columns_fingerprint"):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        for field_name in (
            "frequency_resolution_hz",
            "header_read_seconds",
            "amplitude_read_seconds",
            "numeric_preparation_seconds",
            "total_seconds",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{field_name} must be finite and non-negative.")
            object.__setattr__(self, field_name, value)
        for field_name in (
            "full_frequency_column_count",
            "selected_frequency_column_count",
            "workbook_count",
        ):
            value = int(getattr(self, field_name))
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative.")
            object.__setattr__(self, field_name, value)
        timing_rows = tuple((str(name), float(seconds)) for name, seconds in self.reader_phase_seconds)
        if any(not np.isfinite(seconds) or seconds < 0.0 for _, seconds in timing_rows):
            raise ValueError("reader_phase_seconds must be finite and non-negative.")
        object.__setattr__(self, "reader_phase_seconds", timing_rows)
        for field_name in (
            "completed_participants",
            "ledger_excluded_participants",
            "manual_excluded_participants",
            "frequency_qc_excluded_participants",
            "completed_recordings",
            "ledger_excluded_recordings",
            "frequency_qc_excluded_recordings",
            "incomplete_pair_participants",
            "dataset_diagnostics",
        ):
            object.__setattr__(self, field_name, _tuple_text(getattr(self, field_name)))
        condition_exclusions = tuple(self.participant_condition_exclusions)
        if any(not isinstance(row, ParticipantConditionExclusion) for row in condition_exclusions):
            raise TypeError("participant_condition_exclusions must contain ParticipantConditionExclusion values.")
        identities = {(row.participant_id.casefold(), row.condition.casefold()) for row in condition_exclusions}
        if len(identities) != len(condition_exclusions):
            raise ValueError("participant_condition_exclusions must be unique by participant and condition.")
        object.__setattr__(
            self,
            "participant_condition_exclusions",
            condition_exclusions,
        )
        neutral_fields = (
            "full_fft_provenance_method_version",
            "full_fft_source_fingerprint",
            "full_fft_cohort_fingerprint",
            "full_fft_frequency_qc_fingerprint",
            "full_fft_processing_export_fingerprint",
        )
        neutral_values = tuple(str(getattr(self, field_name) or "").strip() for field_name in neutral_fields)
        if any(neutral_values) and not all(neutral_values):
            raise ValueError("Neutral FullFFT provenance fields must be supplied together.")
        for field_name, value in zip(
            neutral_fields,
            neutral_values,
            strict=True,
        ):
            object.__setattr__(self, field_name, value)
        repeated_version = str(self.repeated_session_batch_version or "").strip()
        shared_fingerprint = str(self.shared_domain_fingerprint or "").strip()
        if bool(repeated_version) != bool(shared_fingerprint):
            raise ValueError("Repeated-session batch version and shared-domain fingerprint must be supplied together.")
        request_exclusions = tuple(self.request_recording_exclusions)
        cohort_audit = tuple(self.repeated_session_cohort_audit)
        if any(not isinstance(row, RecordingExclusionRequest) for row in request_exclusions):
            raise TypeError("request_recording_exclusions must contain RecordingExclusionRequest values.")
        if any(not isinstance(row, RepeatedSessionCohortAuditRow) for row in cohort_audit):
            raise TypeError("repeated_session_cohort_audit must contain RepeatedSessionCohortAuditRow values.")
        if (request_exclusions or cohort_audit) and not repeated_version:
            raise ValueError("Repeated-session exclusions/audit require a batch version.")
        object.__setattr__(self, "repeated_session_batch_version", repeated_version)
        object.__setattr__(self, "shared_domain_fingerprint", shared_fingerprint)
        object.__setattr__(
            self,
            "request_recording_exclusions",
            request_exclusions,
        )
        object.__setattr__(self, "repeated_session_cohort_audit", cohort_audit)


@dataclass(frozen=True, slots=True)
class PreparedContrast:
    """Complete normalized tensors at the public numerical boundary.

    ``values_a`` and ``values_b`` are participant x sensor x harmonic.
    Paired designs require identical participant ordering in both arms.
    """

    request: ProjectContrastRequest
    method: FreeHarmonicMethodSpec
    project_root: Path
    arm_a_label: str
    arm_b_label: str
    participant_ids_a: tuple[str, ...]
    participant_ids_b: tuple[str, ...]
    sensor_names: tuple[str, ...]
    harmonic_orders: np.ndarray
    harmonics_hz: np.ndarray
    snr_a: np.ndarray
    snr_b: np.ndarray
    values_a: np.ndarray
    values_b: np.ndarray
    selection: HarmonicSelection
    frequency_plan: FrequencyWindowPlan
    source_workbooks: tuple[CohortWorkbook, ...]
    provenance: PreparationProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.request, ProjectContrastRequest):
            raise TypeError("request must be a ProjectContrastRequest.")
        if not isinstance(self.method, FreeHarmonicMethodSpec):
            raise TypeError("method must be a FreeHarmonicMethodSpec.")
        if not isinstance(self.selection, HarmonicSelection):
            raise TypeError("selection must be a HarmonicSelection.")
        if not isinstance(self.frequency_plan, FrequencyWindowPlan):
            raise TypeError("frequency_plan must be a FrequencyWindowPlan.")
        if not isinstance(self.provenance, PreparationProvenance):
            raise TypeError("provenance must be PreparationProvenance.")
        if self.selection.selection_mode is not self.method.harmonic_selection_mode:
            raise ValueError("Prepared method and resolved harmonic selection modes must match.")
        if self.selection.fixed_highest_harmonic_order != self.method.fixed_highest_harmonic_order:
            raise ValueError("Prepared method and resolved fixed harmonic ceilings must match.")
        object.__setattr__(self, "project_root", Path(self.project_root))
        object.__setattr__(
            self,
            "arm_a_label",
            _nonempty_text(self.arm_a_label, field_name="arm_a_label"),
        )
        object.__setattr__(
            self,
            "arm_b_label",
            _nonempty_text(self.arm_b_label, field_name="arm_b_label"),
        )
        participants_a = _tuple_text(self.participant_ids_a)
        participants_b = _tuple_text(self.participant_ids_b)
        sensors = _tuple_text(self.sensor_names)
        if not participants_a or not participants_b:
            raise ValueError("Both contrast arms require participants.")
        if len(set(pid.casefold() for pid in participants_a)) != len(participants_a):
            raise ValueError("participant_ids_a must be unique.")
        if len(set(pid.casefold() for pid in participants_b)) != len(participants_b):
            raise ValueError("participant_ids_b must be unique.")
        if len(set(sensor.casefold() for sensor in sensors)) != len(sensors):
            raise ValueError("sensor_names must be unique.")
        orders = _readonly_array(
            self.harmonic_orders,
            dtype=np.int64,
            ndim=1,
            field_name="harmonic_orders",
        )
        harmonics = _readonly_array(
            self.harmonics_hz,
            dtype=np.float64,
            ndim=1,
            field_name="harmonics_hz",
        )
        values_a = _readonly_array(
            self.values_a,
            dtype=np.float64,
            ndim=3,
            field_name="values_a",
        )
        values_b = _readonly_array(
            self.values_b,
            dtype=np.float64,
            ndim=3,
            field_name="values_b",
        )
        snr_a = _readonly_array(
            self.snr_a,
            dtype=np.float64,
            ndim=3,
            field_name="snr_a",
        )
        snr_b = _readonly_array(
            self.snr_b,
            dtype=np.float64,
            ndim=3,
            field_name="snr_b",
        )
        if orders.size != harmonics.size or not harmonics.size:
            raise ValueError("Harmonic order/frequency arrays must match and be non-empty.")
        if not np.array_equal(orders, self.selection.selected_orders) or not np.array_equal(
            harmonics,
            self.selection.selected_harmonics_hz,
        ):
            raise ValueError("Prepared harmonic arrays must match the resolved harmonic selection.")
        expected_a = (len(participants_a), len(sensors), harmonics.size)
        expected_b = (len(participants_b), len(sensors), harmonics.size)
        if values_a.shape != expected_a:
            raise ValueError(f"values_a shape must be {expected_a}; got {values_a.shape}.")
        if values_b.shape != expected_b:
            raise ValueError(f"values_b shape must be {expected_b}; got {values_b.shape}.")
        if snr_a.shape != expected_a:
            raise ValueError(f"snr_a shape must be {expected_a}; got {snr_a.shape}.")
        if snr_b.shape != expected_b:
            raise ValueError(f"snr_b shape must be {expected_b}; got {snr_b.shape}.")
        if not all(np.all(np.isfinite(array)) for array in (snr_a, snr_b, values_a, values_b)):
            raise ValueError("Prepared SNR and normalized contrast tensors must be finite.")
        if self.request.design is AnalysisDesign.PAIRED_CONDITIONS and (
            tuple(pid.casefold() for pid in participants_a) != tuple(pid.casefold() for pid in participants_b)
        ):
            raise ValueError("Paired contrast participant IDs and ordering must match.")
        object.__setattr__(self, "participant_ids_a", participants_a)
        object.__setattr__(self, "participant_ids_b", participants_b)
        object.__setattr__(self, "sensor_names", sensors)
        object.__setattr__(self, "harmonic_orders", orders)
        object.__setattr__(self, "harmonics_hz", harmonics)
        object.__setattr__(self, "snr_a", snr_a)
        object.__setattr__(self, "snr_b", snr_b)
        object.__setattr__(self, "values_a", values_a)
        object.__setattr__(self, "values_b", values_b)
        object.__setattr__(self, "source_workbooks", tuple(self.source_workbooks))


@dataclass(frozen=True, slots=True)
class PreparedRepeatedSessionContrast:
    """One prepared condition/family member of a repeated-session batch."""

    family: RepeatedSessionContrastFamily
    family_id: str
    family_label: str
    condition: str
    tensor_semantics: RepeatedSessionTensorSemantics
    prepared: PreparedContrast
    group_id: str | None = None

    def __post_init__(self) -> None:
        try:
            family = (
                self.family
                if isinstance(self.family, RepeatedSessionContrastFamily)
                else RepeatedSessionContrastFamily(str(self.family))
            )
        except ValueError as exc:
            raise ValueError("Unsupported repeated-session contrast family.") from exc
        try:
            tensor_semantics = (
                self.tensor_semantics
                if isinstance(
                    self.tensor_semantics,
                    RepeatedSessionTensorSemantics,
                )
                else RepeatedSessionTensorSemantics(str(self.tensor_semantics))
            )
        except ValueError as exc:
            raise ValueError("Unsupported repeated-session tensor semantics.") from exc
        for field_name in ("family_id", "family_label", "condition"):
            object.__setattr__(
                self,
                field_name,
                _nonempty_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.prepared, PreparedContrast):
            raise TypeError("prepared must be a PreparedContrast.")
        group_id = None if self.group_id in (None, "") else str(self.group_id).strip()
        if family is RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP:
            if group_id is None:
                raise ValueError("Within-group session contrasts require group_id.")
            if self.prepared.request.design is not AnalysisDesign.PAIRED_CONDITIONS:
                raise ValueError("Within-group session contrasts must use paired inference.")
            expected_semantics = RepeatedSessionTensorSemantics.SESSION_NORMALIZED_PAIRED_PROFILE
        else:
            if group_id is not None:
                raise ValueError("Between-group repeated contrasts do not use group_id.")
            if self.prepared.request.design is not AnalysisDesign.INDEPENDENT_GROUPS:
                raise ValueError("Between-group repeated contrasts require independent inference.")
            expected_semantics = (
                RepeatedSessionTensorSemantics.NORMALIZED_SESSION_CHANGE
                if family is RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE
                else RepeatedSessionTensorSemantics.SESSION_AVERAGED_NORMALIZED_PROFILE
            )
        if tensor_semantics is not expected_semantics:
            raise ValueError("Repeated-session tensor semantics do not match the contrast family.")
        if self.prepared.request.contrast_family_id != self.family_id:
            raise ValueError("Prepared request family ID does not match its batch wrapper.")
        if self.prepared.request.condition_a.casefold() != self.condition.casefold():
            raise ValueError("Prepared request condition does not match its batch wrapper.")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "tensor_semantics", tensor_semantics)
        object.__setattr__(self, "group_id", group_id)


@dataclass(frozen=True, slots=True)
class PreparedRepeatedSessionBatch:
    """Prepared phase-balanced FHC tensors sharing one harmonic domain."""

    request: RepeatedSessionBatchRequest
    method: FreeHarmonicMethodSpec
    project_root: Path
    conditions: tuple[str, ...]
    groups: tuple[ProjectGroupOption, ...]
    sessions: tuple[ProjectSessionOption, ...]
    contrast_runs: tuple[PreparedRepeatedSessionContrast, ...]
    shared_selection: HarmonicSelection
    shared_selection_audit: SharedHarmonicSelectionAudit
    frequency_plan: FrequencyWindowPlan
    sensor_names: tuple[str, ...]
    shared_domain_fingerprint: str
    source_workbooks: tuple[CohortWorkbook, ...]
    cohort_audit: tuple[RepeatedSessionCohortAuditRow, ...]
    provenance: PreparationProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.request, RepeatedSessionBatchRequest):
            raise TypeError("request must be a RepeatedSessionBatchRequest.")
        if not isinstance(self.method, FreeHarmonicMethodSpec):
            raise TypeError("method must be a FreeHarmonicMethodSpec.")
        if not isinstance(self.shared_selection, HarmonicSelection):
            raise TypeError("shared_selection must be a HarmonicSelection.")
        if not isinstance(self.shared_selection_audit, SharedHarmonicSelectionAudit):
            raise TypeError("shared_selection_audit must be SharedHarmonicSelectionAudit.")
        if not isinstance(self.frequency_plan, FrequencyWindowPlan):
            raise TypeError("frequency_plan must be a FrequencyWindowPlan.")
        if not isinstance(self.provenance, PreparationProvenance):
            raise TypeError("provenance must be PreparationProvenance.")
        root = Path(self.project_root)
        conditions = _tuple_text(self.conditions)
        groups = tuple(self.groups)
        sessions = tuple(self.sessions)
        runs = tuple(self.contrast_runs)
        sensors = _tuple_text(self.sensor_names)
        source_workbooks = tuple(self.source_workbooks)
        audit = tuple(self.cohort_audit)
        if conditions != self.request.conditions:
            raise ValueError("Prepared batch conditions must match its request order.")
        if len(groups) != 2 or any(not isinstance(row, ProjectGroupOption) for row in groups):
            raise ValueError("Prepared batch requires two canonical groups.")
        if tuple(row.group_id.casefold() for row in groups) != tuple(
            value.casefold() for value in self.request.group_ids
        ):
            raise ValueError("Prepared batch groups must match its request order.")
        if len(sessions) != 2 or any(not isinstance(row, ProjectSessionOption) for row in sessions):
            raise ValueError("Prepared batch requires two canonical sessions.")
        if tuple(row.session_id.casefold() for row in sessions) != tuple(
            value.casefold() for value in self.request.session_ids
        ):
            raise ValueError("Prepared batch sessions must match its request order.")
        if len(runs) != len(conditions) * 4 or any(
            not isinstance(row, PreparedRepeatedSessionContrast) for row in runs
        ):
            raise ValueError("Prepared batch requires exactly four runs per condition.")
        expected_order: list[tuple[str, RepeatedSessionContrastFamily, str | None]] = []
        for condition in conditions:
            expected_order.extend(
                (
                    (
                        condition,
                        RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS,
                        None,
                    ),
                    (
                        condition,
                        RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP,
                        groups[0].group_id,
                    ),
                    (
                        condition,
                        RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP,
                        groups[1].group_id,
                    ),
                    (
                        condition,
                        RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE,
                        None,
                    ),
                )
            )
        observed_order = [(row.condition, row.family, row.group_id) for row in runs]
        if observed_order != expected_order:
            raise ValueError("Repeated-session contrast runs are not in stable condition/family order.")
        for row in runs:
            prepared = row.prepared
            if prepared.method != self.method:
                raise ValueError("All batch runs must use the shared method specification.")
            if prepared.frequency_plan.grid_fingerprint != self.frequency_plan.grid_fingerprint:
                raise ValueError("All batch runs must use the shared frequency plan.")
            if not np.array_equal(
                prepared.harmonic_orders,
                self.shared_selection.selected_orders,
            ):
                raise ValueError("All batch runs must use the shared harmonic domain.")
            if prepared.sensor_names != sensors:
                raise ValueError("All batch runs must use the shared sensor order.")
        fingerprint = _nonempty_text(
            self.shared_domain_fingerprint,
            field_name="shared_domain_fingerprint",
        )
        if fingerprint != self.provenance.shared_domain_fingerprint:
            raise ValueError("Batch/provenance shared-domain fingerprints must match.")
        if self.provenance.repeated_session_batch_version != self.request.batch_version:
            raise ValueError("Batch/provenance repeated-session versions must match.")
        if any(not isinstance(row, CohortWorkbook) for row in source_workbooks):
            raise TypeError("source_workbooks must contain CohortWorkbook values.")
        if any(not isinstance(row, RepeatedSessionCohortAuditRow) for row in audit):
            raise TypeError("cohort_audit must contain RepeatedSessionCohortAuditRow values.")
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "conditions", conditions)
        object.__setattr__(self, "groups", groups)
        object.__setattr__(self, "sessions", sessions)
        object.__setattr__(self, "contrast_runs", runs)
        object.__setattr__(self, "sensor_names", sensors)
        object.__setattr__(self, "shared_domain_fingerprint", fingerprint)
        object.__setattr__(self, "source_workbooks", source_workbooks)
        object.__setattr__(self, "cohort_audit", audit)


@dataclass(frozen=True, slots=True)
class ClusterRecord:
    """One cluster-level inference record."""

    cluster_id: int
    sign: str
    mass: float
    p_value: float
    conservative_p_value: float
    adjusted_two_sided_p_value: float
    tie_count: int
    p_ci_low: float
    p_ci_high: float
    confidence_interval_straddles_alpha: bool
    significant: bool
    node_indices: tuple[int, ...]
    sensor_indices: tuple[int, ...]
    harmonic_indices: tuple[int, ...]
    effect_size: float | None = None
    effect_size_kind: str | None = None

    def __post_init__(self) -> None:
        cluster_id = int(self.cluster_id)
        if cluster_id == 0:
            raise ValueError("cluster_id must be a non-zero signed integer.")
        sign = str(self.sign).strip().casefold()
        if sign not in {"positive", "negative"}:
            raise ValueError("sign must be 'positive' or 'negative'.")
        if (cluster_id > 0) != (sign == "positive"):
            raise ValueError("cluster_id sign must match the cluster sign.")
        mass = float(self.mass)
        if np.isnan(mass):
            raise ValueError("mass must not be NaN.")
        if (sign == "positive" and not mass > 0.0) or (sign == "negative" and not mass < 0.0):
            raise ValueError("mass sign must match the cluster sign.")
        for field_name in (
            "p_value",
            "conservative_p_value",
            "adjusted_two_sided_p_value",
            "p_ci_low",
            "p_ci_high",
        ):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{field_name} must be finite and between zero and one.")
            object.__setattr__(self, field_name, value)
        if self.p_ci_low > self.p_ci_high:
            raise ValueError("p_ci_low must not exceed p_ci_high.")
        tie_count = int(self.tie_count)
        if tie_count < 0:
            raise ValueError("tie_count must be non-negative.")
        node_indices = tuple(int(value) for value in self.node_indices)
        sensor_indices = tuple(int(value) for value in self.sensor_indices)
        harmonic_indices = tuple(int(value) for value in self.harmonic_indices)
        if not node_indices:
            raise ValueError("A cluster requires at least one node.")
        if not (len(node_indices) == len(sensor_indices) == len(harmonic_indices)):
            raise ValueError("node, sensor, and harmonic index tuples must have matching lengths.")
        if any(value < 0 for values in (node_indices, sensor_indices, harmonic_indices) for value in values):
            raise ValueError("Cluster indices must be non-negative.")
        effect_size = None if self.effect_size is None else float(self.effect_size)
        if effect_size is not None and not np.isfinite(effect_size):
            raise ValueError("effect_size must be finite when present.")
        effect_kind = (
            None
            if self.effect_size_kind in (None, "")
            else _nonempty_text(self.effect_size_kind, field_name="effect_size_kind")
        )
        if (effect_size is None) != (effect_kind is None):
            raise ValueError("effect_size and effect_size_kind must be present together.")
        object.__setattr__(self, "cluster_id", cluster_id)
        object.__setattr__(self, "sign", sign)
        object.__setattr__(self, "mass", mass)
        object.__setattr__(self, "tie_count", tie_count)
        object.__setattr__(self, "node_indices", node_indices)
        object.__setattr__(self, "sensor_indices", sensor_indices)
        object.__setattr__(self, "harmonic_indices", harmonic_indices)
        object.__setattr__(self, "effect_size", effect_size)
        object.__setattr__(self, "effect_size_kind", effect_kind)


@dataclass(frozen=True, slots=True)
class ClusterPermutationResult:
    """Numerical output from the permutation engine."""

    design: AnalysisDesign
    observed_t: np.ndarray
    cluster_labels: np.ndarray
    clusters: tuple[ClusterRecord, ...]
    null_positive_max_mass: np.ndarray
    null_negative_min_mass: np.ndarray
    permutations_evaluated: int
    degrees_of_freedom: int
    cluster_forming_threshold: float
    cluster_entry_alpha: float
    cluster_alpha_per_tail: float
    sensor_adjacency_version: str
    sensor_adjacency_fingerprint: str
    sensor_adjacency_edges: tuple[tuple[str, str], ...]
    rng_algorithm: str
    seed: int
    permutation_assignment_hash: str
    warnings: tuple[str, ...] = ()
    timing_seconds: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        try:
            design = self.design if isinstance(self.design, AnalysisDesign) else AnalysisDesign(str(self.design))
        except ValueError as exc:
            raise ValueError(f"Unsupported analysis design: {self.design!r}.") from exc
        observed = _readonly_array(
            self.observed_t,
            dtype=np.float64,
            ndim=2,
            field_name="observed_t",
        )
        labels = _readonly_array(
            self.cluster_labels,
            dtype=np.int64,
            ndim=2,
            field_name="cluster_labels",
        )
        if observed.shape != labels.shape:
            raise ValueError("observed_t and cluster_labels must have the same shape.")
        positive = _readonly_array(
            self.null_positive_max_mass,
            dtype=np.float64,
            ndim=1,
            field_name="null_positive_max_mass",
        )
        negative = _readonly_array(
            self.null_negative_min_mass,
            dtype=np.float64,
            ndim=1,
            field_name="null_negative_min_mass",
        )
        permutations = int(self.permutations_evaluated)
        if permutations < 1 or positive.size != permutations or negative.size != permutations:
            raise ValueError("Null distributions must match permutations_evaluated.")
        degrees_of_freedom = int(self.degrees_of_freedom)
        if degrees_of_freedom < 1:
            raise ValueError("degrees_of_freedom must be positive.")
        threshold = float(self.cluster_forming_threshold)
        if not np.isfinite(threshold) or threshold <= 0.0:
            raise ValueError("cluster_forming_threshold must be finite and positive.")
        for field_name in ("cluster_entry_alpha", "cluster_alpha_per_tail"):
            value = float(getattr(self, field_name))
            if not np.isfinite(value) or not 0.0 < value < 1.0:
                raise ValueError(f"{field_name} must be strictly between zero and one.")
            object.__setattr__(self, field_name, value)
        edges = tuple((str(left), str(right)) for left, right in self.sensor_adjacency_edges)
        if not edges or any(not left.strip() or not right.strip() for left, right in edges):
            raise ValueError("sensor_adjacency_edges must contain named sensor pairs.")
        warnings = _tuple_text(self.warnings)
        timings = tuple((str(name), float(seconds)) for name, seconds in self.timing_seconds)
        if any(not name.strip() or not np.isfinite(seconds) or seconds < 0.0 for name, seconds in timings):
            raise ValueError("timing_seconds must contain named non-negative timings.")
        object.__setattr__(self, "design", design)
        object.__setattr__(self, "observed_t", observed)
        object.__setattr__(self, "cluster_labels", labels)
        object.__setattr__(self, "null_positive_max_mass", positive)
        object.__setattr__(self, "null_negative_min_mass", negative)
        object.__setattr__(self, "clusters", tuple(self.clusters))
        object.__setattr__(self, "permutations_evaluated", permutations)
        object.__setattr__(self, "degrees_of_freedom", degrees_of_freedom)
        object.__setattr__(self, "cluster_forming_threshold", threshold)
        object.__setattr__(
            self,
            "sensor_adjacency_version",
            _nonempty_text(
                self.sensor_adjacency_version,
                field_name="sensor_adjacency_version",
            ),
        )
        object.__setattr__(
            self,
            "sensor_adjacency_fingerprint",
            _nonempty_text(
                self.sensor_adjacency_fingerprint,
                field_name="sensor_adjacency_fingerprint",
            ),
        )
        object.__setattr__(self, "sensor_adjacency_edges", edges)
        object.__setattr__(
            self,
            "rng_algorithm",
            _nonempty_text(self.rng_algorithm, field_name="rng_algorithm"),
        )
        object.__setattr__(self, "seed", int(self.seed))
        object.__setattr__(
            self,
            "permutation_assignment_hash",
            _nonempty_text(
                self.permutation_assignment_hash,
                field_name="permutation_assignment_hash",
            ),
        )
        object.__setattr__(self, "warnings", warnings)
        object.__setattr__(
            self,
            "timing_seconds",
            timings,
        )


@dataclass(frozen=True, slots=True)
class ExportArtifact:
    """One committed run artifact."""

    role: str
    path: Path
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ExportReceipt:
    """Atomic run-bundle publication receipt."""

    output_directory: Path
    manifest_path: Path
    artifacts: tuple[ExportArtifact, ...]


__all__ = [
    "AnalysisDesign",
    "ClusterPermutationResult",
    "ClusterRecord",
    "CohortWorkbook",
    "ExportArtifact",
    "ExportReceipt",
    "FreeHarmonicCancelledError",
    "FreeHarmonicError",
    "FreeHarmonicInputError",
    "FreeHarmonicMethodSpec",
    "FreeHarmonicPreparationError",
    "FrequencyWindowPlan",
    "HarmonicSelectionMode",
    "HarmonicSelection",
    "METHOD_VERSION",
    "NoHarmonicsSelectedError",
    "ParticipantConditionExclusion",
    "PreparationProvenance",
    "PreparedContrast",
    "PreparedRepeatedSessionBatch",
    "PreparedRepeatedSessionContrast",
    "ProjectAnalysisOptions",
    "ProjectContrastRequest",
    "ProjectGroupOption",
    "ProjectRecordingOption",
    "ProjectSessionOption",
    "REPEATED_SESSION_BATCH_VERSION",
    "RecordingExclusionRequest",
    "RepeatedSessionBatchRequest",
    "RepeatedSessionCohortAuditRow",
    "RepeatedSessionContrastFamily",
    "RepeatedSessionTensorSemantics",
    "SENSOR_ADJACENCY_VERSION",
    "SharedHarmonicSelectionAudit",
]

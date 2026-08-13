"""Immutable public models for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import numpy as np


METHOD_VERSION = "hermann_free_harmonic_clustering_cleanroom_v2"
SENSOR_ADJACENCY_VERSION = (
    "biosemi64-fieldtrip-style-compressed-cleanroom-v1"
)


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
        if any(array.ndim != 1 for array in arrays) or len(
            {array.size for array in arrays}
        ) != 1:
            raise ValueError(
                "No-harmonics diagnostic arrays must be aligned vectors."
            )
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
    harmonic_selection_mode: HarmonicSelectionMode = (
        HarmonicSelectionMode.AUTOMATIC
    )
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
            raise ValueError(
                "harmonic_selection_mode must be 'automatic' or "
                "'fixed_highest'."
            ) from exc
        object.__setattr__(
            self,
            "harmonic_selection_mode",
            selection_mode,
        )
        fixed_order = self.fixed_highest_harmonic_order
        if selection_mode is HarmonicSelectionMode.AUTOMATIC:
            if fixed_order is not None:
                raise ValueError(
                    "fixed_highest_harmonic_order must be omitted in automatic "
                    "harmonic-selection mode."
                )
        else:
            if (
                fixed_order is None
                or isinstance(fixed_order, bool)
                or int(fixed_order) < 1
            ):
                raise ValueError(
                    "fixed_highest mode requires a positive integer "
                    "fixed_highest_harmonic_order."
                )
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", Path(self.project_root))
        try:
            design = (
                self.design
                if isinstance(self.design, AnalysisDesign)
                else AnalysisDesign(str(self.design))
            )
        except ValueError as exc:
            raise ValueError(f"Unsupported analysis design: {self.design!r}.") from exc
        object.__setattr__(self, "design", design)
        condition_a = _nonempty_text(self.condition_a, field_name="condition_a")
        condition_b = (
            None
            if self.condition_b in (None, "")
            else _nonempty_text(self.condition_b, field_name="condition_b")
        )
        groups = _tuple_text(self.group_ids)
        if len({group.casefold() for group in groups}) != len(groups):
            raise ValueError("group_ids must contain distinct canonical group IDs.")
        if design is AnalysisDesign.INDEPENDENT_GROUPS:
            if condition_b is not None:
                raise ValueError(
                    "independent_groups uses one condition; condition_b must be omitted."
                )
            if len(groups) != 2:
                raise ValueError(
                    "independent_groups requires two ordered canonical group_ids."
                )
        else:
            if condition_b is None:
                raise ValueError("paired_conditions requires condition_b.")
            if condition_a.casefold() == condition_b.casefold():
                raise ValueError("paired_conditions requires two distinct conditions.")
            if len(groups) > 1:
                raise ValueError(
                    "paired_conditions accepts at most one canonical group filter."
                )
        object.__setattr__(self, "condition_a", condition_a)
        object.__setattr__(self, "condition_b", condition_b)
        object.__setattr__(self, "group_ids", groups)


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
        if normalized["selected_orders"].size != selected_indices.size or normalized[
            "selected_harmonics_hz"
        ].size != selected_indices.size:
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
                raise ValueError(
                    "Automatic selection cannot record a fixed harmonic ceiling."
                )
        else:
            if fixed_order is None or int(fixed_order) < 1:
                raise ValueError(
                    "Fixed selection requires fixed_highest_harmonic_order."
                )
            fixed_order = int(fixed_order)
            if fixed_order != int(normalized["selected_orders"][-1]):
                raise ValueError(
                    "Fixed harmonic ceiling must equal the highest retained order."
                )
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
    incomplete_pair_participants: tuple[str, ...] = ()
    participant_condition_exclusions: tuple[
        ParticipantConditionExclusion,
        ...,
    ] = ()
    dataset_diagnostics: tuple[str, ...] = ()

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
        timing_rows = tuple(
            (str(name), float(seconds)) for name, seconds in self.reader_phase_seconds
        )
        if any(not np.isfinite(seconds) or seconds < 0.0 for _, seconds in timing_rows):
            raise ValueError("reader_phase_seconds must be finite and non-negative.")
        object.__setattr__(self, "reader_phase_seconds", timing_rows)
        for field_name in (
            "completed_participants",
            "ledger_excluded_participants",
            "manual_excluded_participants",
            "frequency_qc_excluded_participants",
            "incomplete_pair_participants",
            "dataset_diagnostics",
        ):
            object.__setattr__(self, field_name, _tuple_text(getattr(self, field_name)))
        condition_exclusions = tuple(self.participant_condition_exclusions)
        if any(
            not isinstance(row, ParticipantConditionExclusion)
            for row in condition_exclusions
        ):
            raise TypeError(
                "participant_condition_exclusions must contain "
                "ParticipantConditionExclusion values."
            )
        identities = {
            (row.participant_id.casefold(), row.condition.casefold())
            for row in condition_exclusions
        }
        if len(identities) != len(condition_exclusions):
            raise ValueError(
                "participant_condition_exclusions must be unique by "
                "participant and condition."
            )
        object.__setattr__(
            self,
            "participant_condition_exclusions",
            condition_exclusions,
        )


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
            raise ValueError(
                "Prepared method and resolved harmonic selection modes must match."
            )
        if (
            self.selection.fixed_highest_harmonic_order
            != self.method.fixed_highest_harmonic_order
        ):
            raise ValueError(
                "Prepared method and resolved fixed harmonic ceilings must match."
            )
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
            raise ValueError(
                "Prepared harmonic arrays must match the resolved harmonic selection."
            )
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
        if not all(
            np.all(np.isfinite(array))
            for array in (snr_a, snr_b, values_a, values_b)
        ):
            raise ValueError("Prepared SNR and normalized contrast tensors must be finite.")
        if self.request.design is AnalysisDesign.PAIRED_CONDITIONS and (
            tuple(pid.casefold() for pid in participants_a)
            != tuple(pid.casefold() for pid in participants_b)
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
        if (sign == "positive" and not mass > 0.0) or (
            sign == "negative" and not mass < 0.0
        ):
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
        if not (
            len(node_indices) == len(sensor_indices) == len(harmonic_indices)
        ):
            raise ValueError(
                "node, sensor, and harmonic index tuples must have matching lengths."
            )
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
            design = (
                self.design
                if isinstance(self.design, AnalysisDesign)
                else AnalysisDesign(str(self.design))
            )
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
    "ProjectAnalysisOptions",
    "ProjectContrastRequest",
    "ProjectGroupOption",
    "SENSOR_ADJACENCY_VERSION",
]

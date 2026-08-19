"""Pure spectral preparation for Free Harmonic Clustering Analysis.

The functions in this module know nothing about projects, workbooks, or Qt.
They convert one validated FullFFT column grid into a compact read plan and
apply the paper-faithful SNR, harmonic-selection, and normalization rules.
"""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Sequence

import numpy as np

from .models import (
    FreeHarmonicMethodSpec,
    FreeHarmonicPreparationError,
    FrequencyWindowPlan,
    HarmonicSelection,
    HarmonicSelectionMode,
    NoHarmonicsSelectedError,
)


_FREQUENCY_COLUMN = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)_Hz$")
_ZERO_TOLERANCE_HZ = 5e-5
_TARGET_TOLERANCE_HZ = 5e-5
_GRID_TOLERANCE_HZ = 6e-5


def _fingerprint_columns(
    columns: Sequence[str],
    frequencies_hz: Sequence[float],
) -> str:
    digest = sha256()
    for column, frequency in zip(columns, frequencies_hz, strict=True):
        digest.update(str(column).encode("utf-8"))
        digest.update(b"\0")
        digest.update(float(frequency).hex().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _frequency_columns(header: Sequence[object]) -> tuple[tuple[str, ...], np.ndarray]:
    columns: list[str] = []
    frequencies: list[float] = []
    for value in header:
        column = str(value or "").strip()
        match = _FREQUENCY_COLUMN.fullmatch(column)
        if match is None:
            continue
        frequency = float(match.group(1))
        if not np.isfinite(frequency):
            raise FreeHarmonicPreparationError(f"FullFFT frequency column {column!r} is not finite.")
        columns.append(column)
        frequencies.append(frequency)
    if len(columns) < 2:
        raise FreeHarmonicPreparationError("No usable FullFFT frequency grid was found.")
    if len(set(columns)) != len(columns):
        raise FreeHarmonicPreparationError("FullFFT frequency column names must be unique.")
    values = np.ascontiguousarray(frequencies, dtype=np.float64)
    if np.any(np.diff(values) <= 0.0):
        raise FreeHarmonicPreparationError("FullFFT frequency columns must be strictly increasing.")
    return tuple(columns), values


def build_frequency_window_plan(
    header: Sequence[object],
    spec: FreeHarmonicMethodSpec,
    *,
    electrode_column: str = "Electrode",
) -> FrequencyWindowPlan:
    """Validate a FullFFT grid and plan one deduplicated selected-column read.

    The physical noise window is inclusive at ``target +/- 0.1 Hz`` (or the
    configured half-width).  The target bin and its immediately adjacent FFT
    bins are excluded.  All indices stored in the returned plan address the
    compact selected-column matrix rather than the original wide worksheet.
    """

    if not isinstance(spec, FreeHarmonicMethodSpec):
        raise TypeError("spec must be a FreeHarmonicMethodSpec.")
    header_names = tuple(str(value or "").strip() for value in header)
    if header_names.count(electrode_column) != 1:
        raise FreeHarmonicPreparationError(f"FullFFT requires exactly one {electrode_column!r} column.")
    full_columns, frequencies = _frequency_columns(header)
    if abs(float(frequencies[0])) > _ZERO_TOLERANCE_HZ:
        raise FreeHarmonicPreparationError("The FullFFT frequency grid must begin at 0 Hz.")

    oddball_hz = float(spec.oddball_frequency_hz)
    target_positions = np.flatnonzero(np.abs(frequencies - oddball_hz) <= _TARGET_TOLERANCE_HZ)
    if target_positions.size != 1 or int(target_positions[0]) <= 0:
        raise FreeHarmonicPreparationError("The FullFFT grid must contain exactly one oddball-frequency column.")
    oddball_bin = int(target_positions[0])
    resolution_hz = oddball_hz / oddball_bin
    expected = np.arange(frequencies.size, dtype=np.float64) * resolution_hz
    if np.any(np.abs(frequencies - expected) > _GRID_TOLERANCE_HZ):
        raise FreeHarmonicPreparationError("The FullFFT frequency columns are not one uniform zero-based grid.")

    maximum_order = int(np.floor((float(spec.max_harmonic_hz) + _GRID_TOLERANCE_HZ) / oddball_hz))
    all_orders = np.arange(1, maximum_order + 1, dtype=np.int64)
    all_harmonics = all_orders.astype(np.float64) * oddball_hz
    base_ratios = all_harmonics / float(spec.base_frequency_hz)
    base_overlap = np.isclose(
        base_ratios,
        np.rint(base_ratios),
        rtol=0.0,
        atol=1e-9,
    )
    candidate_orders = all_orders[~base_overlap]
    candidate_harmonics = all_harmonics[~base_overlap]
    excluded_orders = all_orders[base_overlap]
    excluded_harmonics = all_harmonics[base_overlap]
    if not candidate_orders.size:
        raise FreeHarmonicPreparationError("No non-base oddball harmonics remain in the requested range.")

    target_full_indices: list[int] = []
    noise_full_indices: list[np.ndarray] = []
    half_width_hz = float(spec.noise_half_width_hz)
    window_tolerance = max(_GRID_TOLERANCE_HZ, resolution_hz * 1e-6)
    for order, harmonic_hz in zip(
        candidate_orders,
        candidate_harmonics,
        strict=True,
    ):
        target_index = int(order) * oddball_bin
        lower_hz = float(harmonic_hz) - half_width_hz
        upper_hz = float(harmonic_hz) + half_width_hz
        if (
            target_index >= frequencies.size
            or abs(float(frequencies[target_index]) - float(harmonic_hz)) > _GRID_TOLERANCE_HZ
        ):
            raise FreeHarmonicPreparationError(f"FullFFT is missing the {float(harmonic_hz):g} Hz harmonic bin.")
        if lower_hz < float(frequencies[0]) - window_tolerance or upper_hz > float(frequencies[-1]) + window_tolerance:
            raise FreeHarmonicPreparationError(
                f"FullFFT does not contain the complete physical noise window for {float(harmonic_hz):g} Hz."
            )
        in_window = np.flatnonzero(
            (frequencies >= lower_hz - window_tolerance) & (frequencies <= upper_hz + window_tolerance)
        )
        excluded_adjacent = np.array(
            [target_index - 1, target_index, target_index + 1],
            dtype=np.int64,
        )
        noise_indices = np.setdiff1d(
            in_window,
            excluded_adjacent,
            assume_unique=True,
        )
        if noise_indices.size < 4:
            raise FreeHarmonicPreparationError(
                "The physical noise window requires at least four finite bins "
                "after excluding the target and adjacent bins at "
                f"{float(harmonic_hz):g} Hz."
            )
        target_full_indices.append(target_index)
        noise_full_indices.append(noise_indices)

    noise_counts = {int(indices.size) for indices in noise_full_indices}
    if len(noise_counts) != 1:
        details = ", ".join(str(value) for value in sorted(noise_counts))
        raise FreeHarmonicPreparationError(
            f"Eligible harmonics do not share one complete physical noise-window size (observed {details} bins)."
        )

    required_full_indices = np.unique(
        np.concatenate(
            [
                np.asarray(target_full_indices, dtype=np.int64),
                *noise_full_indices,
            ]
        )
    )
    selected_columns = tuple(full_columns[index] for index in required_full_indices)
    selected_frequencies = np.ascontiguousarray(frequencies[required_full_indices])
    compact_index = {int(full_index): compact for compact, full_index in enumerate(required_full_indices.tolist())}
    target_selected_indices = np.fromiter(
        (compact_index[index] for index in target_full_indices),
        dtype=np.int64,
        count=len(target_full_indices),
    )
    noise_selected_indices = np.ascontiguousarray(
        [[compact_index[int(index)] for index in indices] for indices in noise_full_indices],
        dtype=np.int64,
    )

    return FrequencyWindowPlan(
        full_frequency_columns=full_columns,
        full_frequencies_hz=frequencies,
        selected_frequency_columns=selected_columns,
        selected_frequencies_hz=selected_frequencies,
        candidate_orders=candidate_orders,
        candidate_harmonics_hz=candidate_harmonics,
        excluded_base_orders=excluded_orders,
        excluded_base_harmonics_hz=excluded_harmonics,
        target_selected_indices=target_selected_indices,
        noise_selected_indices=noise_selected_indices,
        frequency_resolution_hz=resolution_hz,
        grid_fingerprint=_fingerprint_columns(full_columns, frequencies),
        selected_columns_fingerprint=_fingerprint_columns(
            selected_columns,
            selected_frequencies,
        ),
        electrode_column=electrode_column,
    )


def build_available_frequency_window_plan(
    header: Sequence[object],
    *,
    oddball_frequency_hz: float,
    base_frequency_hz: float,
    noise_half_width_hz: float = 0.1,
    electrode_column: str = "Electrode",
) -> FrequencyWindowPlan:
    """Build the largest valid header-derived non-base harmonic plan.

    This is the read-only setup counterpart to :func:`build_frequency_window_plan`.
    Its ceiling comes from the actual FullFFT upper frequency after reserving a
    complete physical noise window; it never assumes the historical 48-Hz
    default.
    """

    _, frequencies = _frequency_columns(header)
    oddball_hz = float(oddball_frequency_hz)
    base_hz = float(base_frequency_hz)
    half_width_hz = float(noise_half_width_hz)
    for field_name, value in (
        ("oddball_frequency_hz", oddball_hz),
        ("base_frequency_hz", base_hz),
        ("noise_half_width_hz", half_width_hz),
    ):
        if not np.isfinite(value) or value <= 0.0:
            raise ValueError(f"{field_name} must be finite and positive.")
    usable_upper_hz = float(frequencies[-1]) - half_width_hz
    highest_order = int(np.floor((usable_upper_hz + _GRID_TOLERANCE_HZ) / oddball_hz))
    if highest_order < 1:
        raise FreeHarmonicPreparationError(
            "FullFFT does not contain one oddball harmonic with a complete physical noise window."
        )
    specification = FreeHarmonicMethodSpec(
        oddball_frequency_hz=oddball_hz,
        base_frequency_hz=base_hz,
        max_harmonic_hz=highest_order * oddball_hz,
        noise_half_width_hz=half_width_hz,
    )
    return build_frequency_window_plan(
        header,
        specification,
        electrode_column=electrode_column,
    )


def compute_participant_snr(
    selected_amplitudes: np.ndarray,
    plan: FrequencyWindowPlan,
) -> np.ndarray:
    """Return target/noise-mean SNR for every leading observation dimension."""

    amplitudes = np.asarray(selected_amplitudes, dtype=np.float64)
    if amplitudes.ndim < 1 or amplitudes.shape[-1] != len(plan.selected_frequency_columns):
        raise FreeHarmonicPreparationError("Selected amplitude tensor has the wrong frequency-axis length.")
    if not np.all(np.isfinite(amplitudes)):
        raise FreeHarmonicPreparationError("FullFFT amplitudes must be finite.")
    if np.any(amplitudes < 0.0):
        raise FreeHarmonicPreparationError("FullFFT amplitudes must be non-negative.")
    targets = np.take(amplitudes, plan.target_selected_indices, axis=-1)
    noise = np.take(amplitudes, plan.noise_selected_indices, axis=-1)
    noise_mean = np.mean(noise, axis=-1)
    if np.any(~np.isfinite(noise_mean)) or np.any(noise_mean <= 0.0):
        raise FreeHarmonicPreparationError("Every harmonic noise window must have a finite positive mean.")
    snr = targets / noise_mean
    if not np.all(np.isfinite(snr)):
        raise FreeHarmonicPreparationError("Participant SNR contains non-finite values.")
    return np.ascontiguousarray(snr, dtype=np.float64)


def compute_harmonic_z(
    grand_selected_amplitude: np.ndarray,
    plan: FrequencyWindowPlan,
    *,
    ddof: int = 1,
) -> np.ndarray:
    """Compute grand-spectrum z scores with sample noise SD by default."""

    amplitude = np.asarray(grand_selected_amplitude, dtype=np.float64)
    if amplitude.ndim != 1 or amplitude.size != len(plan.selected_frequency_columns):
        raise FreeHarmonicPreparationError("Grand amplitude spectrum must be one selected-frequency vector.")
    if not np.all(np.isfinite(amplitude)):
        raise FreeHarmonicPreparationError("Grand amplitude spectrum must be finite.")
    if np.any(amplitude < 0.0):
        raise FreeHarmonicPreparationError("Grand amplitude spectrum must be non-negative.")
    ddof = int(ddof)
    if ddof < 0 or plan.noise_selected_indices.shape[1] <= ddof:
        raise FreeHarmonicPreparationError("Noise-window ddof is not estimable.")
    targets = amplitude[plan.target_selected_indices]
    noise = amplitude[plan.noise_selected_indices]
    noise_mean = np.mean(noise, axis=-1)
    noise_sd = np.std(noise, axis=-1, ddof=ddof)
    if np.any(~np.isfinite(noise_sd)) or np.any(noise_sd <= 0.0):
        raise FreeHarmonicPreparationError("Every harmonic noise window must have finite non-zero sample variance.")
    z_scores = (targets - noise_mean) / noise_sd
    if not np.all(np.isfinite(z_scores)):
        raise FreeHarmonicPreparationError("Harmonic z scores contain non-finite values.")
    return np.ascontiguousarray(z_scores, dtype=np.float64)


def select_harmonics(
    grand_selected_amplitude_a: np.ndarray,
    grand_selected_amplitude_b: np.ndarray,
    plan: FrequencyWindowPlan,
    spec: FreeHarmonicMethodSpec,
) -> HarmonicSelection:
    """Resolve the declared harmonic domain and retain a complete fill-through.

    Automatic mode mirrors the Hermann-compatible observed-arm z rule.  Fixed
    mode still calculates the same z/detection audit, but its retained ceiling
    is the explicitly declared eligible non-base oddball order and is not
    conditional on crossing the z threshold.
    """

    z_a = compute_harmonic_z(
        grand_selected_amplitude_a,
        plan,
        ddof=spec.harmonic_z_ddof,
    )
    z_b = compute_harmonic_z(
        grand_selected_amplitude_b,
        plan,
        ddof=spec.harmonic_z_ddof,
    )
    detected_a = z_a > float(spec.harmonic_z_threshold)
    detected_b = z_b > float(spec.harmonic_z_threshold)
    return _selection_from_z(
        z_a,
        z_b,
        detected_a,
        detected_b,
        plan,
        spec,
    )


def _selection_from_z(
    z_a: np.ndarray,
    z_b: np.ndarray,
    detected_a: np.ndarray,
    detected_b: np.ndarray,
    plan: FrequencyWindowPlan,
    spec: FreeHarmonicMethodSpec,
) -> HarmonicSelection:
    """Resolve fill-through from already calculated arm-level selector z."""

    detected_either = detected_a | detected_b
    highest_detected_order = int(np.max(plan.candidate_orders[detected_either])) if np.any(detected_either) else None
    fixed_order: int | None = None
    if spec.harmonic_selection_mode is HarmonicSelectionMode.AUTOMATIC:
        if highest_detected_order is None:
            raise NoHarmonicsSelectedError(
                candidate_orders=plan.candidate_orders,
                candidate_harmonics_hz=plan.candidate_harmonics_hz,
                arm_a_z=z_a,
                arm_b_z=z_b,
                z_threshold=spec.harmonic_z_threshold,
            )
        selected_ceiling = highest_detected_order
    else:
        fixed_order = int(spec.fixed_highest_harmonic_order or 0)
        if not np.any(plan.candidate_orders == fixed_order):
            harmonic_hz = fixed_order * float(spec.oddball_frequency_hz)
            if np.any(plan.excluded_base_orders == fixed_order):
                detail = "it overlaps the base stimulation frequency"
            elif fixed_order > int(plan.candidate_orders[-1]):
                detail = "it exceeds the available planned FullFFT domain"
            else:
                detail = "it is not an eligible non-base oddball harmonic"
            raise FreeHarmonicPreparationError(
                f"fixed_highest_harmonic_order {fixed_order} ({harmonic_hz:g} Hz) is invalid because {detail}."
            )
        selected_ceiling = fixed_order
    selected_indices = np.flatnonzero(plan.candidate_orders <= selected_ceiling)
    return HarmonicSelection(
        candidate_orders=plan.candidate_orders,
        candidate_harmonics_hz=plan.candidate_harmonics_hz,
        arm_a_z=z_a,
        arm_b_z=z_b,
        detected_arm_a=detected_a,
        detected_arm_b=detected_b,
        selected_candidate_indices=selected_indices,
        selected_orders=plan.candidate_orders[selected_indices],
        selected_harmonics_hz=plan.candidate_harmonics_hz[selected_indices],
        excluded_base_orders=plan.excluded_base_orders,
        excluded_base_harmonics_hz=plan.excluded_base_harmonics_hz,
        z_threshold=spec.harmonic_z_threshold,
        z_ddof=spec.harmonic_z_ddof,
        highest_detected_order=highest_detected_order,
        selection_mode=spec.harmonic_selection_mode,
        fixed_highest_harmonic_order=fixed_order,
    )


def select_harmonics_across_cells(
    grand_selected_amplitudes: np.ndarray,
    plan: FrequencyWindowPlan,
    spec: FreeHarmonicMethodSpec,
) -> tuple[HarmonicSelection, np.ndarray, np.ndarray]:
    """Select one domain from equally weighted group x session x condition cells.

    Each row is one participant-mean cell spectrum. Selector z is calculated
    independently for every row; the retained ceiling is the highest eligible
    strict detection in any row. The returned cell-level z and detection arrays
    are immutable copies suitable for the batch audit.
    """

    spectra = np.asarray(grand_selected_amplitudes, dtype=np.float64)
    if spectra.ndim != 2 or spectra.shape[0] < 1 or spectra.shape[1] != len(plan.selected_frequency_columns):
        raise FreeHarmonicPreparationError("Shared selector spectra must be cell x selected frequency.")
    if not np.all(np.isfinite(spectra)) or np.any(spectra < 0.0):
        raise FreeHarmonicPreparationError("Shared selector cell spectra must be finite and non-negative.")
    cell_z = np.ascontiguousarray(
        [
            compute_harmonic_z(
                spectrum,
                plan,
                ddof=spec.harmonic_z_ddof,
            )
            for spectrum in spectra
        ],
        dtype=np.float64,
    )
    cell_detected = np.ascontiguousarray(
        cell_z > float(spec.harmonic_z_threshold),
        dtype=np.bool_,
    )
    # HarmonicSelection remains the common legacy-compatible domain object.
    # Its two audit arms are both the across-cell maximum and therefore must be
    # interpreted only through the explicit SharedHarmonicSelectionAudit.
    maximum_z = np.max(cell_z, axis=0)
    detected_any = np.any(cell_detected, axis=0)
    selection = _selection_from_z(
        maximum_z,
        maximum_z,
        detected_any,
        detected_any,
        plan,
        spec,
    )
    cell_z.setflags(write=False)
    cell_detected.setflags(write=False)
    return selection, cell_z, cell_detected


def select_snr_harmonics(
    participant_snr: np.ndarray,
    selection: HarmonicSelection,
) -> np.ndarray:
    """Slice participant SNR to the selected fill-through harmonic domain."""

    snr = np.asarray(participant_snr, dtype=np.float64)
    if snr.ndim != 3 or snr.shape[-1] != selection.candidate_orders.size:
        raise FreeHarmonicPreparationError("Participant SNR must be participant x sensor x candidate harmonic.")
    selected = np.take(snr, selection.selected_candidate_indices, axis=-1)
    if not np.all(np.isfinite(selected)):
        raise FreeHarmonicPreparationError("Selected participant SNR must be finite.")
    return np.ascontiguousarray(selected, dtype=np.float64)


def l2_normalize_snr(selected_snr: np.ndarray) -> np.ndarray:
    """L2-normalize each participant x condition sensor-by-harmonic matrix."""

    snr = np.asarray(selected_snr, dtype=np.float64)
    if snr.ndim != 3 or snr.shape[1] < 1 or snr.shape[2] < 1:
        raise FreeHarmonicPreparationError("Selected SNR must be participant x sensor x harmonic.")
    if not np.all(np.isfinite(snr)):
        raise FreeHarmonicPreparationError("Selected participant SNR must be finite.")
    norms = np.sqrt(np.sum(np.square(snr), axis=(1, 2), keepdims=True))
    if np.any(~np.isfinite(norms)) or np.any(norms <= 0.0):
        raise FreeHarmonicPreparationError(
            "Every participant-condition SNR matrix must have a finite non-zero L2 norm."
        )
    normalized = snr / norms
    return np.ascontiguousarray(normalized, dtype=np.float64)


__all__ = [
    "build_available_frequency_window_plan",
    "build_frequency_window_plan",
    "compute_harmonic_z",
    "compute_participant_snr",
    "l2_normalize_snr",
    "select_harmonics",
    "select_harmonics_across_cells",
    "select_snr_harmonics",
]

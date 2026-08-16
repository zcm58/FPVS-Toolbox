"""BioSemi64 alignment and source-frame helpers for publication scalp maps."""

from __future__ import annotations

from functools import lru_cache

import mne
import numpy as np
import pandas as pd

from Tools.Publication_Maps.models import Diagnostic


BIOSEMI64_SENSOR_COUNT = 64
# Four non-collinear points are the smallest stable 2-D interpolation set used
# by this tool.  Sparser inputs are source data, not defensible scalp maps.
MIN_RENDER_SENSOR_COUNT = 4


class InsufficientSensorCoverageError(ValueError):
    """Raised when finite montage values cannot support a scalp interpolation."""

    def __init__(
        self,
        *,
        finite_sensor_count: int,
        required_sensor_count: int = MIN_RENDER_SENSOR_COUNT,
        reason: str = "too few finite sensors",
    ) -> None:
        self.finite_sensor_count = int(finite_sensor_count)
        self.required_sensor_count = int(required_sensor_count)
        self.reason = str(reason)
        super().__init__(
            "Scalp-map rendering requires at least "
            f"{self.required_sensor_count} finite, non-collinear BioSemi64 "
            f"sensors; found {self.finite_sensor_count} ({self.reason})."
        )


def normalize_electrode_name(value: object) -> str:
    """Normalize workbook electrode labels for montage alignment."""

    if value is None:
        return ""
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and missing:
        return ""
    return str(value).strip().upper()


@lru_cache(maxsize=1)
def biosemi64_info() -> mne.io.Info:
    """Return a cached BioSemi64 info object for topomap rendering."""

    montage = mne.channels.make_standard_montage("biosemi64")
    info = mne.create_info(ch_names=montage.ch_names, sfreq=100, ch_types="eeg")
    info.set_montage(montage)
    return info


@lru_cache(maxsize=1)
def biosemi64_names_upper() -> frozenset[str]:
    """Return normalized BioSemi64 channel names."""

    return frozenset(name.upper() for name in biosemi64_info().ch_names)


def align_render_values(
    values: pd.DataFrame,
    *,
    value_column: str = "render_value",
) -> tuple[np.ndarray, mne.io.Info, int, list[Diagnostic]]:
    """Return only finite BioSemi64 values in montage order.

    Missing and non-finite sensors are omitted from both interpolation and
    color-limit calculation.  A deterministic minimum of four finite,
    non-collinear sensors is required; values are never replaced with zero.
    """

    info = biosemi64_info().copy()
    name_to_idx = {name.upper(): idx for idx, name in enumerate(info.ch_names)}
    data = np.full(len(info.ch_names), np.nan, dtype=float)
    diagnostics: list[Diagnostic] = []
    unmapped = 0
    nonfinite = 0
    for row in values.itertuples(index=False):
        electrode = normalize_electrode_name(getattr(row, "electrode"))
        idx = name_to_idx.get(electrode)
        if idx is None:
            unmapped += 1
            continue
        try:
            value = float(getattr(row, value_column))
        except (TypeError, ValueError):
            value = np.nan
        if np.isfinite(value):
            data[idx] = value
        else:
            nonfinite += 1
    missing_count = int(np.sum(np.isnan(data)))
    if unmapped:
        diagnostics.append(
            Diagnostic(
                level="warning",
                message="Workbook electrodes were not in the BioSemi64 montage.",
                detail=str(unmapped),
            )
        )
    if nonfinite:
        diagnostics.append(
            Diagnostic(
                level="warning",
                message="Non-finite montage values were omitted from scalp-map rendering.",
                detail=str(nonfinite),
            )
        )

    finite_indices = np.flatnonzero(np.isfinite(data))
    finite_count = int(len(finite_indices))
    if finite_count < MIN_RENDER_SENSOR_COUNT:
        raise InsufficientSensorCoverageError(finite_sensor_count=finite_count)

    selected_info = mne.pick_info(info, finite_indices.tolist(), copy=True)
    selected_data = data[finite_indices]
    positions = np.asarray(
        [channel["loc"][:2] for channel in selected_info["chs"]],
        dtype=float,
    )
    centered_positions = positions - np.mean(positions, axis=0, keepdims=True)
    if np.linalg.matrix_rank(centered_positions) < 2:
        raise InsufficientSensorCoverageError(
            finite_sensor_count=finite_count,
            reason="finite sensor positions are collinear",
        )

    if missing_count:
        diagnostics.append(
            Diagnostic(
                level="warning",
                message=("Missing BioSemi64 sensors were omitted from interpolation and color scaling."),
                detail=(f"finite={finite_count}; missing={missing_count}; required_minimum={MIN_RENDER_SENSOR_COUNT}"),
            )
        )
    return selected_data, selected_info, missing_count, diagnostics

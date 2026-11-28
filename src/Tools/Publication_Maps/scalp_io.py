"""Release-bound electrode geometry and source-frame alignment for scalp maps."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from functools import lru_cache
from typing import TYPE_CHECKING

import mne
import numpy as np
import pandas as pd

from Tools.Publication_Maps.models import Diagnostic, PublicationMapInputError, ScalpMapGeometry

if TYPE_CHECKING:
    from Tools.Publication_Maps.display_montage import DisplayMontage


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
            f"{self.required_sensor_count} finite, non-collinear "
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


def recorded_map_geometry(
    identity: Mapping[str, object], *, source_id: str, display_montage: DisplayMontage | None = None,
) -> ScalpMapGeometry:
    """Resolve one authenticated recording's own montage. Never infer geometry from its labels."""
    from Main_App.io.recorded_eeg_geometry import validate_recorded_geometry_identity

    if not isinstance(source_id, str) or not source_id.strip():
        raise PublicationMapInputError("Released electrode geometry is missing its recording identity.")
    raw = validate_recorded_geometry_identity(identity)
    names = tuple(sorted(raw["retained_scalp_channels"], key=str.casefold))
    coordinate_source = raw["coordinate_source"]
    positions = raw["channel_coordinates_m"]
    if raw["coordinate_frame"] != "head" or raw["geometry_status"] != "available":
        if display_montage is None:
            raise PublicationMapInputError(
                f"Recording {source_id!r} lacks complete electrode positions in head coordinates. "
                "Choose a matching display montage or reprocess with verified electrode positions."
            )
        template = {name.strip().casefold(): xyz for name, xyz in display_montage.positions}
        missing = [name for name in names if name.casefold() not in template]
        if missing:
            raise PublicationMapInputError(
                f"Display montage {display_montage.name!r} has no position for released electrode(s): "
                + ", ".join(missing)
            )
        positions = {name: template[name.casefold()] for name in names}
        coordinate_source = f"display_template:{display_montage.name}"
    elif coordinate_source not in {"recording", "explicit_project_template"}:
        raise PublicationMapInputError(f"Scalp Maps cannot place electrodes with coordinate source {coordinate_source!r}.")
    xyz = tuple(tuple(float(x) for x in positions[name]) for name in names)
    occupied = {}
    for name, position in zip(names, xyz, strict=True):
        if position in occupied:
            raise PublicationMapInputError(
                f"Recording {source_id!r} places {occupied[position]!r} and {name!r} at the same head position. "
                "Check the electrode labels and montage coordinates."
            )
        occupied[position] = name
    return ScalpMapGeometry(
        hardware_platform=raw["hardware_platform"], montage_id=raw["montage_id"],
        mapping_profile=raw["electrode_mapping_profile"], coordinate_source=coordinate_source,
        canonical_names=tuple(sorted(raw["canonical_scalp_channels"], key=str.casefold)),
        channel_names=names, reference_channels=tuple(sorted(raw.get("reference_only_channels", ()), key=str.casefold)),
        source_positions=((source_id.strip().casefold(), xyz),),
    )


def require_compatible_geometry(geometries: Iterable[ScalpMapGeometry | None]) -> ScalpMapGeometry | None:
    """Preserve each recording once so cohorts and repeated conditions use the same display layout."""
    items = tuple(geometries)
    if not items or all(item is None for item in items):
        return None  # Historical prepared frames and the canonical fixed BioSemi64 route.
    first = next(item for item in items if item is not None)
    layout = replace(first, source_positions=())
    recordings = {}
    for item in items:
        if item is None or replace(item, source_positions=()) != layout:
            raise PublicationMapInputError(
                "Scalp Maps cannot combine incompatible electrode montages, mappings, coordinate sources "
                "or scalp channel sets. Select recordings with a common montage."
            )
        for source, xyz in item.source_positions:
            if recordings.setdefault(source, xyz) != xyz:
                raise PublicationMapInputError(f"Conflicting released electrode positions for recording {source!r}.")
            if first.coordinate_source != "recording" and xyz != first.source_positions[0][1]:
                raise PublicationMapInputError("Scalp Maps found inconsistent coordinates for the selected template.")
    return replace(layout, source_positions=tuple(sorted(recordings.items())))


@lru_cache(maxsize=8)
def _montage_info(geometry: ScalpMapGeometry) -> mne.Info:
    # Source IDs are distinct and sorted. Repeated conditions and unequal
    # numbers of workbooks per participant do not repeat any recording's XYZ.
    sets = [xyz for _, xyz in geometry.source_positions]
    positions = np.mean(sets, axis=0) if geometry.coordinate_source == "recording" else np.asarray(sets[0])
    if len(np.unique(positions, axis=0)) != len(positions):
        raise PublicationMapInputError("The common scalp layout places multiple electrodes at one position.")
    info = mne.create_info(ch_names=list(geometry.channel_names), sfreq=100, ch_types="eeg")
    montage = mne.channels.make_dig_montage(ch_pos=dict(zip(geometry.channel_names, positions, strict=True)),
                                            coord_frame="head")
    info.set_montage(montage)
    return info


def align_render_values(
    values: pd.DataFrame,
    *,
    value_column: str = "render_value",
    geometry: ScalpMapGeometry | None = None,
) -> tuple[np.ndarray, mne.io.Info, int, list[Diagnostic]]:
    """Return only finite values in the released display montage's channel order.

    Missing and non-finite sensors are omitted from both interpolation and
    color-limit calculation.  A deterministic minimum of four finite,
    non-collinear sensors is required; values are never replaced with zero.
    """

    info = _montage_info(geometry) if geometry is not None else biosemi64_info()
    montage_label = geometry.montage_id if geometry is not None else "BioSemi64"
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
                message=f"Workbook electrodes were not in the {montage_label} montage.",
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
                message=f"Missing {montage_label} sensors were omitted from interpolation and color scaling.",
                detail=(f"finite={finite_count}; missing={missing_count}; required_minimum={MIN_RENDER_SENSOR_COUNT}"),
            )
        )
    return selected_data, selected_info, missing_count, diagnostics

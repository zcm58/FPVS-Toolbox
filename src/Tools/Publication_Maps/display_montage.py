"""Explicit display coordinates for EEG recordings that lack usable positions."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import mne
import numpy as np

from Main_App.projects.hardware import ACTICAP_GACS_64, ACTICAP_GACS_128, SUPPORTED_ELECTRODE_MONTAGES


_ACTICAP_WIRING = {
    key: (cap, site)
    for cap in (ACTICAP_GACS_64, ACTICAP_GACS_128)
    for key, site in ((cap, "Iz"), (f"{cap}:FCz", "FCz"))
}


def display_montage_choices() -> tuple[tuple[str, str], ...]:
    """Return selectable template IDs and their labels, including distinct actiCAP wirings."""
    labels = dict(SUPPORTED_ELECTRODE_MONTAGES)
    return (
        *((key, f"{labels[cap]} · {site} recorded") for key, (cap, site) in _ACTICAP_WIRING.items()),
        ("unicorn8", labels["unicorn8"]),
        *((name, name) for name in mne.channels.get_builtin_montages()),
    )


@dataclass(frozen=True, slots=True)
class DisplayMontage:
    """Electrode locations in the MNE head frame, in metres."""

    name: str
    positions: tuple[tuple[str, tuple[float, float, float]], ...]

    def __post_init__(self) -> None:
        labels = [label.strip().casefold() for label, _ in self.positions]
        xyz = np.asarray([point for _, point in self.positions], dtype=float)
        if not labels or not all(labels) or len(set(labels)) != len(labels):
            raise ValueError("Display montage electrode names must be nonempty and unique.")
        if xyz.shape != (len(labels), 3) or not np.isfinite(xyz).all():
            raise ValueError("Every display electrode needs three finite head coordinates.")
        distances = np.linalg.norm(xyz, axis=1)
        if np.any(distances == 0) or np.any(distances > 1):
            raise ValueError("Check the montage units. Electrode locations must be on the head in metres.")


def _from_dig(name: str, montage) -> DisplayMontage:
    positions = montage.get_positions()
    if positions["coord_frame"] != "head":
        if any(positions[landmark] is None for landmark in ("nasion", "lpa", "rpa")):
            raise ValueError("The montage needs head coordinates or nasion, left and right ear landmarks.")
        montage.apply_trans(mne.channels.compute_native_head_t(montage, on_missing="raise"))
        positions = montage.get_positions()
    return DisplayMontage(name, tuple((label, tuple(xyz)) for label, xyz in positions["ch_pos"].items()))


@lru_cache(maxsize=8)
def _builtin_display_montage(name: str) -> DisplayMontage:
    if name in _ACTICAP_WIRING:
        from Main_App.io.acticap_montages import make_acticap_montage

        cap, site = _ACTICAP_WIRING[name]
        return _from_dig(f"{cap}:{site}", make_acticap_montage(cap, recorded_fcz=site == "FCz"))
    if name == "unicorn8":
        from Main_App.io.acquisition_profiles import UNICORN_CHANNELS

        standard = dict(_builtin_display_montage("standard_1020").positions)
        return DisplayMontage(name, tuple((channel, standard[channel]) for channel in UNICORN_CHANNELS))
    return _from_dig(name, mne.channels.make_standard_montage(name))


def load_display_montage(source: DisplayMontage | str | Path | None) -> DisplayMontage | None:
    """Read an explicitly selected montage without changing recording or project settings."""
    if source is None or isinstance(source, DisplayMontage):
        return source
    if isinstance(source, str):
        return _builtin_display_montage(source)
    suffix = source.suffix.lower()
    if suffix == ".fif":
        return _from_dig(source.name, mne.channels.read_dig_fif(source, verbose=False))
    if suffix == ".bvct":
        # MNE 1.9 accesses the XML parser through the defusedxml package.
        from defusedxml import ElementTree

        try:
            digitization = mne.channels.read_dig_captrak(source)
        except (ElementTree.ParseError, AttributeError, KeyError, TypeError) as exc:
            raise ValueError("The CapTrak file needs electrodes and Nasion, LPA and RPA landmarks.") from exc
        return _from_dig(source.name, digitization)
    if suffix not in {".csv", ".tsv"}:
        raise ValueError("Choose a CSV, TSV, digitization FIF or CapTrak BVCT montage.")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        rows = csv.DictReader(stream, delimiter="\t" if suffix == ".tsv" else ",")
        headers = rows.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("The coordinate table contains a duplicate column.")
        if "electrode" not in headers:
            raise ValueError("The coordinate table needs an electrode column.")
        scales = [unit for unit in ("m", "mm") if all(f"{axis}_{unit}" in headers for axis in "xyz")]
        if len(scales) != 1:
            raise ValueError("Use one set of head coordinates: x_m, y_m, z_m or x_mm, y_mm, z_mm.")
        unit, = scales
        factor = 0.001 if unit == "mm" else 1.0
        points = []
        for row in rows:
            try:
                point = tuple(float(row[f"{axis}_{unit}"]) * factor for axis in "xyz")
                label = (row["electrode"] or "").strip()
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid head coordinates on line {rows.line_num} of {source.name}.") from exc
            points.append((label, point))
    return DisplayMontage(source.name, tuple(points))

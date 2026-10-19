"""Streaming BVRF 1.0 reader using MNE's existing Raw interface.

Format evidence: Brain Products BVRFHeader-1.0.0 schema and its published
``brain-products/bvrf_reader`` reference reader. Samples are zero-based,
little-endian, sample-interleaved; calibration is resolution, then rational
polynomial, then physical units. No amplifier or scalp layout is inferred.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import mne
import numpy as np
from mne._fiff.utils import _mult_cal_one

from Main_App.io.brain_products_files import BrainProductsFormatError, source_files


_DTYPES = {"Int16": "<i2", "Int32": "<i4", "Single": "<f4", "Double": "<f8"}
_VOLT_UNITS = {"V": 1.0, "mV": 1e-3, "µV": 1e-6, "μV": 1e-6, "uV": 1e-6, "nV": 1e-9}
_ELECTRICAL_TYPES = {"eeg", "eog", "ecg", "emg", "bio"}


def _number(value: object, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BrainProductsFormatError(f"BVRF {field} must be numeric.")
    result = float(value)
    if not np.isfinite(result) or positive and result <= 0:
        raise BrainProductsFormatError(f"BVRF {field} must be finite" + (" and positive." if positive else "."))
    return result


def _polynomial(value: object, default: tuple[float, ...]) -> tuple[float, ...]:
    if value is None:
        return default
    if not isinstance(value, list) or not value:
        raise BrainProductsFormatError("BVRF calibration coefficients must be nonempty numeric arrays.")
    return tuple(_number(item, "calibration coefficient") for item in value)


def read_bvrf_header(path: str | Path) -> dict:
    """Validate supported data semantics and retain the full original metadata."""
    with Path(path).open(encoding="utf-8-sig") as handle:
        header = json.load(handle)
    try:
        eeg = header["EEGModality"]
        formats = eeg["BVRFFiles"]
        for definition in (header["BVRF"], header["BVRFHeaderFile"], formats["DataFile"], formats["MarkerFile"]):
            if definition["Version"] != "1.0.0":
                raise BrainProductsFormatError("Only BVRF 1.0.0 data/header/marker versions are supported.")
        dtype = np.dtype(_DTYPES[formats["DataFile"]["NumericDataType"]])
        sfreq = _number(eeg["DataSpecific"]["SamplingFrequencyInHertz"], "sample rate", positive=True)
        channels = eeg["Channels"]
        if not isinstance(channels, list) or not channels:
            raise BrainProductsFormatError("BVRF requires at least one channel.")
        participant_ids = {channel.get("ParticipantId") for channel in channels} - {None, ""}
        participants = header.get("Participants") or []
        if len(participant_ids) > 1 or len(participants) > 1:
            raise BrainProductsFormatError(
                "Multi-participant BVRF requires separate participant exports before FPVS processing."
            )
        names, types, units, calibrations = [], [], [], []
        valid_types = set(mne.io.get_channel_type_constants())
        for channel in channels:
            name, unit, kind = channel["Name"], channel["Unit"], channel["Type"].lower()
            if not isinstance(name, str) or not name.strip() or "\t" in name:
                raise BrainProductsFormatError("BVRF channel names must be nonempty and contain no tabs.")
            if not isinstance(unit, str):
                raise BrainProductsFormatError("BVRF channel units must be text.")
            if kind in _ELECTRICAL_TYPES and unit not in _VOLT_UNITS:
                raise BrainProductsFormatError(f"BVRF electrical channel {name!r} has unsupported unit {unit!r}.")
            resolution = _number(channel["ResolutionPerBit"], f"resolution for {name}", positive=True)
            minus = (channel.get("Composition") or {}).get("Minus") or {}
            if kind == "eeg" and minus and minus.get("Section", "Electrodes") == "Electrodes":
                raise BrainProductsFormatError(
                    "Bipolar EEG derivations cannot be treated as common-reference scalp EEG. "
                    "Export the original referential EEG channels for FPVS processing."
                )
            coefficients = channel.get("Coefficients") or {}
            numerator = _polynomial(coefficients.get("Num"), (0.0, 1.0))
            denominator = _polynomial(coefficients.get("Denom"), (1.0,))
            if denominator[0] != 1.0:
                raise BrainProductsFormatError("BVRF rational calibration requires leading denominator 1.")
            names.append(name)
            types.append(kind if kind in valid_types else "misc")
            units.append(unit)
            calibrations.append((resolution, numerator, denominator, _VOLT_UNITS.get(unit, 1.0)))
        if len({name.casefold() for name in names}) != len(names):
            raise BrainProductsFormatError("BVRF channel names must be unique ignoring case.")
    except (KeyError, TypeError, AttributeError) as exc:
        raise BrainProductsFormatError(f"BVRF header is missing or has invalid required metadata: {exc}") from exc
    return {"original": header, "dtype": dtype, "sfreq": sfreq, "names": names,
            "types": types, "units": units, "calibrations": calibrations}


def _captrak_montage(header: dict) -> mne.channels.DigMontage | None:
    """Resolve electrode composition only when recorded fiducials define head space.

    MNI/Easycap coordinates and incomplete or unanchored CapTrak coordinates
    remain available in original metadata but are not relabeled as head space.
    """
    eeg = header["original"]["EEGModality"]
    system = eeg.get("CoordinateSystems") or {}
    if (system.get("EEGCoordinateSystem") != "CapTrak" or system.get("EEGCoordinateUnit") != "mm"
            or system.get("FiducialsCoordinateSystem") != "CapTrak"
            or system.get("FiducialsCoordinateUnit") != "mm"):
        return None
    fiducials = eeg.get("Fiducials") or []
    if len(fiducials) != 1:
        return None
    landmarks = fiducials[0].get("Coordinates") or {}
    if not {"Nasion", "LPA", "RPA"}.issubset(landmarks):
        return None
    electrodes = {item["Name"]: item.get("Coordinates") for item in eeg.get("Electrodes") or []}
    positions = {}
    for channel, kind in zip(eeg["Channels"], header["types"], strict=True):
        if kind != "eeg":
            continue
        plus = (channel.get("Composition") or {}).get("Plus") or {}
        coordinate = electrodes.get(plus.get("Name")) if plus.get("Section", "Electrodes") == "Electrodes" else None
        if coordinate is None:
            return None
        positions[channel["Name"]] = np.asarray(coordinate, dtype=float) * 1e-3
    if not positions:
        return None
    coordinates = [*positions.values(), *(np.asarray(landmarks[key], dtype=float) * 1e-3 for key in ("Nasion", "LPA", "RPA"))]
    if any(value.shape != (3,) or not np.isfinite(value).all() for value in coordinates):
        raise BrainProductsFormatError("BVRF CapTrak coordinates must contain three finite values.")
    nasion, lpa, rpa = coordinates[-3:]
    if np.linalg.norm(np.cross(rpa - lpa, nasion - lpa)) < 1e-8:
        raise BrainProductsFormatError("BVRF CapTrak fiducials must define a nondegenerate head coordinate frame.")
    montage = mne.channels.make_dig_montage(ch_pos=positions, nasion=nasion, lpa=lpa, rpa=rpa, coord_frame="unknown")
    return mne.channels.transform_to_head(montage)


def _markers(path: Path, n_samples: int, sfreq: float) -> tuple[mne.Annotations, tuple[dict, ...]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if not {"Sample", "Type", "Code", "Value"}.issubset(reader.fieldnames or ()):
            raise BrainProductsFormatError("BVRF markers require Sample, Type, Code and Value columns.")
        rows = tuple(dict(row) for row in reader)
    onsets, descriptions = [], []
    for row in rows:
        try:
            sample = int(row["Sample"])
        except (TypeError, ValueError) as exc:
            raise BrainProductsFormatError("BVRF marker Sample must be an integer.") from exc
        if sample < 0 or sample >= n_samples:
            raise BrainProductsFormatError("BVRF marker sample lies outside the recorded data.")
        if None in row or any(value is None for value in row.values()):
            raise BrainProductsFormatError("BVRF marker row does not match its column header.")
        label = row["Code"] + row["Value"]
        descriptions.append(f"{row['Type']}/{label}")
        onsets.append(sample / sfreq)
    return mne.Annotations(onsets, np.zeros(len(onsets)), descriptions), rows


class RawBVRF(mne.io.BaseRaw):
    """A single-participant BVRF recording with bounded streaming reads."""

    def __init__(self, path: str | Path, *, preload: bool | str = False):
        header_path, data_path, marker_path, *_ = source_files(path)
        header = read_bvrf_header(header_path)
        n_channels = len(header["names"])
        record_bytes = n_channels * header["dtype"].itemsize
        n_samples, remainder = divmod(data_path.stat().st_size, record_bytes)
        if not n_samples or remainder:
            raise BrainProductsFormatError("BVRF data is empty or ends with an incomplete sample frame.")
        annotations, rows = _markers(marker_path, n_samples, header["sfreq"])
        info = mne.create_info(header["names"], header["sfreq"], header["types"])
        montage = _captrak_montage(header)
        if montage is not None:
            info.set_montage(montage, on_missing="raise")
        super().__init__(info, preload=preload, first_samps=[0], last_samps=[n_samples - 1],
                         filenames=[str(data_path)], raw_extras=[header],
                         orig_units=dict(zip(header["names"], header["units"])), verbose=False)
        self.set_annotations(annotations)
        self._fpvs_brain_products_header = header["original"]
        self._fpvs_brain_products_marker_rows = rows

    def _read_segment_file(self, data, idx, fi, start, stop, cals, mult):
        header = self._raw_extras[fi]
        channels = len(header["names"])
        count = (stop - start) * channels
        with open(self.filenames[fi], "rb") as handle:
            handle.seek(start * channels * header["dtype"].itemsize)
            block = np.fromfile(handle, dtype=header["dtype"], count=count)
        if block.size != count:
            raise BrainProductsFormatError("BVRF data changed or was truncated while reading.")
        block = block.reshape(-1, channels).T.astype(float)
        for index, (resolution, numerator, denominator, scale) in enumerate(header["calibrations"]):
            physical = block[index] * resolution
            divisor = np.polynomial.polynomial.polyval(physical, denominator)
            if np.any(divisor == 0):
                raise BrainProductsFormatError("BVRF channel calibration has a zero denominator.")
            with np.errstate(over="ignore", invalid="ignore"):
                block[index] = np.polynomial.polynomial.polyval(physical, numerator) / divisor * scale
            if not np.all(np.isfinite(block[index])):
                raise BrainProductsFormatError("BVRF contains nonfinite data or invalid channel calibration.")
        _mult_cal_one(data, block, idx, cals, mult)

"""Declaration-only validation shared by native manifests and array readers."""

from collections.abc import Mapping
from pathlib import Path
import re

SPECTRAL_COMPANION_VERSION = "numpy_spectral_companion_v1"
SPECTRAL_SHEET_NAMES = ("FullFFT Amplitude (uV)", "FullSNR")
CONDITION_COMPANION_VERSION = "numpy_condition_companion_v1"
CONDITION_DATA_SHEET_NAMES = (
    "FFT Amplitude (uV)", "SNR", "Z Score", "BCA (uV)",
    "Spectral Eligibility", "Spectral Metric QC", "FFT and neighbors", "FFT Metadata",
)


class SpectralDataError(ValueError):
    """A declared spectral companion is missing, invalid, or changed."""

    # Keep the original public exception name in tracebacks and serialized data.
    __module__ = "Main_App.io.spectral_data"


class ConditionDataError(ValueError):
    """A declared condition companion is missing, invalid, or changed."""

    __module__ = "Main_App.io.condition_data"


def _file_fields(value: Mapping, kind: str, error: type[ValueError]) -> tuple:
    name = value.get("path")
    if (
        not isinstance(name, str) or not name or name in {".", ".."}
        or any(char in name for char in ("/", "\\", ":", "\x00"))
        or Path(name).name != name or Path(name).suffix.lower() != ".npz"
    ):
        raise error(f"{kind} companion path must be a local .npz basename.")
    size, digest, sheets = value.get("size_bytes"), value.get("sha256"), value.get("sheets")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise error(f"{kind} companion size is invalid.")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise error(f"{kind} companion SHA-256 is invalid.")
    return name, size, digest, sheets


def spectral_descriptor(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or value.get("version") != SPECTRAL_COMPANION_VERSION:
        raise SpectralDataError("Spectral companion version is missing or unsupported.")
    name, size, digest, sheets = _file_fields(value, "Spectral", SpectralDataError)
    if (
        not isinstance(sheets, list) or not sheets
        or any(not isinstance(sheet, str) for sheet in sheets)
        or sheets[0] != SPECTRAL_SHEET_NAMES[0]
        or len(set(sheets)) != len(sheets)
        or any(sheet not in SPECTRAL_SHEET_NAMES for sheet in sheets)
    ):
        raise SpectralDataError("Spectral companion sheet declaration is invalid.")
    return {"version": SPECTRAL_COMPANION_VERSION, "path": name, "size_bytes": size,
            "sha256": digest, "sheets": list(sheets)}


def condition_descriptor(value: Mapping) -> dict:
    if not isinstance(value, Mapping) or value.get("version") != CONDITION_COMPANION_VERSION:
        raise ConditionDataError("Condition companion version is missing or unsupported.")
    if set(value) != {"version", "path", "size_bytes", "sha256", "sheets"}:
        raise ConditionDataError("Condition companion declaration has invalid fields.")
    name, size, digest, sheets = _file_fields(value, "Condition", ConditionDataError)
    if (
        not isinstance(sheets, list) or not sheets
        or any(not isinstance(sheet, str) or sheet not in CONDITION_DATA_SHEET_NAMES for sheet in sheets)
        or len(set(sheets)) != len(sheets)
    ):
        raise ConditionDataError("Condition companion sheet declaration is invalid.")
    return {"version": CONDITION_COMPANION_VERSION, "path": name, "size_bytes": size,
            "sha256": digest, "sheets": list(sheets)}

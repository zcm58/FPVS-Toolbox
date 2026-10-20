"""Canonical project-aware EEG loader for the processing paths.

This module owns the loader behavior previously kept in legacy loaders. Keep load order, channel typing, memmap
paths, montage behavior, and return semantics aligned with the BDF loader
contract unless a future task explicitly changes the processing pipeline.
"""

from __future__ import annotations

import logging
import os
import re
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Sequence, Set, Tuple

import mne
import numpy as np

from Main_App.gui import user_messages
from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNEL_SET,
    BIOSEMI64_MONTAGE_ID,
    BioSemi64AcquisitionGeometry,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
    validate_biosemi64_acquisition_channels,
)

logger = logging.getLogger("Main_App.Shared.load_utils")
BDF_RECORDING_NOT_STARTED_REASON = "recording_not_started"


@dataclass(frozen=True)
class BdfPreflightInfo:
    """Header-level BDF metadata used before MNE opens large recordings."""

    file_size: int
    header_bytes: Optional[int]
    data_records: Optional[int]
    record_duration: Optional[float]
    channel_count: Optional[int]

    @property
    def data_bytes(self) -> Optional[int]:
        if self.header_bytes is None:
            return None
        return max(0, int(self.file_size) - int(self.header_bytes))

    @property
    def recording_not_started(self) -> bool:
        return (
            self.header_bytes is not None
            and self.data_records == 0
            and int(self.file_size) <= int(self.header_bytes)
        )


def _parse_bdf_int(raw: bytes) -> Optional[int]:
    text = raw.decode("ascii", errors="ignore").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _parse_bdf_float(raw: bytes) -> Optional[float]:
    text = raw.decode("ascii", errors="ignore").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def inspect_bdf_header(filepath: str | Path) -> Optional[BdfPreflightInfo]:
    """
    Read only the fixed BDF header.

    A BioSemi file created without clicking Record is a valid-looking BDF header
    with zero data records and no bytes after the declared header length.
    """
    path = Path(filepath)
    if path.suffix.lower() != ".bdf":
        return None
    try:
        file_size = path.stat().st_size
        with path.open("rb") as stream:
            fixed_header = stream.read(256)
    except OSError:
        return None

    if len(fixed_header) < 256:
        return BdfPreflightInfo(
            file_size=int(file_size),
            header_bytes=None,
            data_records=None,
            record_duration=None,
            channel_count=None,
        )

    return BdfPreflightInfo(
        file_size=int(file_size),
        header_bytes=_parse_bdf_int(fixed_header[184:192]),
        data_records=_parse_bdf_int(fixed_header[236:244]),
        record_duration=_parse_bdf_float(fixed_header[244:252]),
        channel_count=_parse_bdf_int(fixed_header[252:256]),
    )


def read_bdf_sampling_rate_hz(
    filepath: str | Path, *, stim_channel: str = "Status"
) -> Fraction:
    """Read an exact common data/stim sampling rate without reading signal samples.

    BDF signal-header fields are grouped by field, rather than by channel.
    Annotation channels have their own sample counts and do not define the EEG
    grid. Mixed data/stim rates fail instead of relying on reader resampling.
    File access errors propagate; malformed headers raise ``ValueError``.
    """
    if Path(filepath).suffix.lower() in {".vhdr", ".bvrh"}:
        from Main_App.io.brain_products import read_sampling_rate

        return Fraction(str(read_sampling_rate(filepath)))
    if not isinstance(stim_channel, str) or not stim_channel.strip():
        raise ValueError("A nonempty BDF stimulus channel is required.")

    def _text(value: bytes, field: str) -> str:
        try:
            return value.decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise ValueError(f"BDF {field} must contain ASCII text.") from exc

    def _integer(value: bytes, field: str) -> int:
        try:
            text = _text(value, field)
            if not re.fullmatch(r"[+-]?[0-9]+", text):
                raise ValueError("Not an integer field.")
            return int(text)
        except ValueError as exc:
            raise ValueError(f"BDF {field} must be an integer.") from exc

    with Path(filepath).open("rb") as stream:
        fixed = stream.read(256)
        if len(fixed) != 256:
            raise ValueError("BDF fixed header is truncated.")
        if fixed[:8] != b"\xffBIOSEMI":
            raise ValueError("BDF header must have the BioSemi identification code.")
        channels = _integer(fixed[252:256], "channel count")
        header_bytes = _integer(fixed[184:192], "header length")
        if channels <= 0 or header_bytes != (channels + 1) * 256:
            raise ValueError("BDF header length must match its positive channel count.")
        if _integer(fixed[236:244], "data record count") < -1:
            raise ValueError("BDF data record count must be -1 or nonnegative.")
        duration_text = _text(fixed[244:252], "record duration")
        try:
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", duration_text):
                raise ValueError("Record duration must be decimal.")
            duration = Fraction(duration_text)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError("BDF record duration must be a positive decimal.") from exc
        if duration <= 0:
            raise ValueError("BDF record duration must be a positive decimal.")
        signals = stream.read(channels * 256)
        if len(signals) != channels * 256:
            raise ValueError("BDF signal header is truncated.")

    data_rates: list[Fraction] = []
    stimulus_matches = 0
    for index in range(channels):
        label = _text(signals[index * 16 : (index + 1) * 16], "channel label")
        offset = channels * 216 + index * 8
        samples = _integer(signals[offset : offset + 8], "samples per data record")
        if not label or samples <= 0:
            raise ValueError("BDF channel labels and positive sample counts are required.")
        if label.casefold() in {"edf annotations", "bdf annotations"}:
            continue
        data_rates.append(Fraction(samples, 1) / duration)
        stimulus_matches += label.casefold() == stim_channel.strip().casefold()
    if stimulus_matches != 1:
        raise ValueError(f"BDF must contain exactly one {stim_channel!r} stimulus channel.")
    if len(set(data_rates)) != 1:
        raise ValueError("BDF data and stimulus channels must share one sampling rate.")
    return data_rates[0]


def is_bdf_recording_not_started(filepath: str | Path) -> bool:
    info = inspect_bdf_header(filepath)
    return bool(info and info.recording_not_started)


def _format_file_list(file_names: Sequence[str]) -> str:
    names = [Path(str(name)).name for name in file_names if str(name).strip()]
    if not names:
        return "the selected BDF file"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"


def format_bdf_recording_not_started_message(file_names: Sequence[str]) -> str:
    files = _format_file_list(file_names)
    if len([name for name in file_names if str(name).strip()]) == 1:
        return (
            f"File {files} was created, but the user did not click Record in BioSemi "
            "before the experiment began, so it was excluded from processing and analysis."
        )
    return (
        f"Files {files} were created, but the user did not click Record in BioSemi "
        "before the experiment began, so those files were excluded from processing and analysis."
    )


def _memmap_dir_for_pid() -> Path:
    """Private per-process memmap directory shared with worker cleanup."""
    from Main_App.io.memmap_paths import process_memmap_directory

    return process_memmap_directory()


_cached_1010 = cached_biosemi64_montage
_cached_1020 = _cached_1010  # temporary compatibility aliases for stale imports


def _resolve_ref_pair(app: Any) -> Tuple[str, str]:
    """Resolve the desired reference pair from project settings, app settings, or defaults."""
    try:
        p = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        p = {}

    def _s(section: str, key: str, default=None):
        try:
            return app.settings.get(section, key, default)
        except Exception:
            return default

    ref1 = p.get("ref_channel1") or p.get("ref_chan1") or _s("preprocessing", "ref_channel1") or "EXG1"
    ref2 = p.get("ref_channel2") or p.get("ref_chan2") or _s("preprocessing", "ref_channel2") or "EXG2"
    return str(ref1), str(ref2)


def _resolve_stim(app: Any) -> str:
    """Resolve the stim channel name. Defaults to 'Status'."""
    try:
        p = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        p = {}
    try:
        return p.get("stim_channel") or app.settings.get("stim", "channel", "Status") or "Status"
    except Exception:
        return "Status"


def _resolve_electrode_mapping_profile(app: Any) -> str:
    """Resolve the project-owned BioSemi64 channel-label mapping profile."""

    from Main_App.projects.preprocessing_settings import (
        ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
        normalize_electrode_mapping_profile,
    )

    try:
        preprocessing = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        preprocessing = {}
    return normalize_electrode_mapping_profile(
        preprocessing.get("electrode_mapping_profile", ELECTRODE_MAPPING_PROFILE_ANATOMICAL)
    )


def _resolve_electrode_montage(app: Any) -> str:
    """Resolve and validate the project-owned electrode montage identifier."""

    from Main_App.projects.preprocessing_settings import (
        ELECTRODE_MONTAGE_BIOSEMI64,
        normalize_electrode_montage,
    )

    if ELECTRODE_MONTAGE_BIOSEMI64 != BIOSEMI64_MONTAGE_ID:
        raise RuntimeError("Project and loader BioSemi64 montage identifiers disagree.")

    try:
        preprocessing = getattr(app.currentProject, "preprocessing", {}) or {}
    except Exception:
        preprocessing = {}
    montage_id = normalize_electrode_montage(preprocessing.get("electrode_montage"))
    if montage_id != BIOSEMI64_MONTAGE_ID:
        raise ValueError(f"Unsupported electrode montage {montage_id!r}.")
    return montage_id


def _normalize_electrode_montage(value: Any) -> str:
    from Main_App.projects.preprocessing_settings import (
        ELECTRODE_MONTAGE_BIOSEMI64,
        normalize_electrode_montage,
    )

    if ELECTRODE_MONTAGE_BIOSEMI64 != BIOSEMI64_MONTAGE_ID:
        raise RuntimeError("Project and loader BioSemi64 montage identifiers disagree.")

    montage_id = normalize_electrode_montage(value)
    if montage_id != BIOSEMI64_MONTAGE_ID:
        raise ValueError(f"Unsupported electrode montage {montage_id!r}.")
    return montage_id


def _normalize_electrode_mapping_profile(value: Any) -> str:
    """Normalize through the project contract without creating an import cycle."""

    from Main_App.projects.preprocessing_settings import (
        normalize_electrode_mapping_profile,
    )

    return normalize_electrode_mapping_profile(value)


def _map_present_case_insensitive(names: Iterable[str]) -> Dict[str, str]:
    """Build a case-insensitive lookup: UPPER -> actual name present."""
    return {n.upper(): n for n in names}


def _canon_present(raw_names: Iterable[str], candidates: Iterable[str]) -> Set[str]:
    """Return present candidates, matching case-insensitively but preserving actual casing."""
    lut = _map_present_case_insensitive(raw_names)
    out: Set[str] = set()
    for c in candidates:
        if not isinstance(c, str):
            continue
        k = c.upper()
        if k in lut:
            out.add(lut[k])
    return out


def _resolve_channel_subset(
    filepath: str,
    *,
    stim_name: str,
    ref_pair: Tuple[str, str],
    first_n_channels: Optional[int],
    electrode_mapping_profile: Any = None,
) -> Optional[list[str]]:
    """Validate the full header, then return a source-order reduced include list."""

    geometry = _read_biosemi64_header_geometry(
        filepath,
        stim_name=stim_name,
        ref_pair=ref_pair,
        electrode_mapping_profile=electrode_mapping_profile,
    )
    return geometry.included_source_names(first_n_channels)


def _read_biosemi64_header_geometry(
    filepath: str,
    *,
    stim_name: str,
    ref_pair: Tuple[str, str],
    electrode_mapping_profile: Any,
) -> BioSemi64AcquisitionGeometry:
    """Open only the BDF header and validate all acquisition identities."""

    base = os.path.basename(filepath)
    logger.debug(
        "[LOADER STAGE] file=%s stage=header_geometry_validation_start",
        base,
    )
    with mne.utils.use_log_level("WARNING"):
        header = mne.io.read_raw_bdf(
            filepath,
            preload=False,
            stim_channel=stim_name if stim_name else "Status",
            verbose=False,
        )
    try:
        geometry = validate_biosemi64_acquisition_channels(
            header.ch_names,
            ref_pair=ref_pair,
            stim_name=stim_name,
            electrode_mapping_profile=electrode_mapping_profile,
        )
    finally:
        try:
            header.close()
        except (AttributeError, RuntimeError, OSError, ValueError):
            pass

    logger.debug(
        "[LOADER STAGE] file=%s stage=header_geometry_validation_done total_channels=%d profile=%s",
        base,
        len(geometry.source_channel_names),
        geometry.electrode_mapping_profile,
    )
    return geometry


def _try_warning_log(app: Any, message: str) -> bool:
    """Route warning text to GUI logs when the caller supports log levels."""
    try:
        app.log(message, level=logging.WARNING)
        return True
    except TypeError:
        return False
    except Exception:
        return False


def _emit_reader_warnings(
    app: Any,
    filepath: str,
    caught_warnings: Iterable[warnings.WarningMessage],
) -> None:
    """Re-log file-reader warnings with explicit file context."""
    base = os.path.basename(filepath)
    for caught in caught_warnings:
        warning_text = str(caught.message).strip()
        if not warning_text:
            continue

        detailed = f"[LOADER WARNING] {base}: {warning_text} [path='{filepath}']"
        if "Number of records from the header does not match the file size" in warning_text:
            detailed += " MNE will infer the record count from the file size."

        if not _try_warning_log(app, detailed):
            logger.warning(detailed)


def _apply_preflight_channel_and_montage_contract(
    app: Any,
    raw: mne.io.BaseRaw,
    *,
    base: str,
    ref_pair: Tuple[str, str],
    stim_name: str,
    acquisition_geometry: BioSemi64AcquisitionGeometry,
    retained_scalp_channels: Sequence[str],
) -> dict[str, Any]:
    """Apply strict BioSemi64 names, roles, coordinates, and runtime identity."""

    logger.debug("[LOADER STAGE] file=%s stage=channel_identity_start", base)
    source_mapping = acquisition_geometry.source_to_canonical
    source_mapping_by_case = {
        source.casefold(): canonical for source, canonical in source_mapping.items()
    }
    rename_mapping = {
        name: source_mapping_by_case[name.casefold()]
        for name in raw.ch_names
        if name.casefold() in source_mapping_by_case
        and name != source_mapping_by_case[name.casefold()]
    }
    if rename_mapping:
        raw.rename_channels(rename_mapping)

    retained_set = set(retained_scalp_channels)
    actual_scalp = {name for name in raw.ch_names if name in BIOSEMI64_CHANNEL_SET}
    if actual_scalp != retained_set or len(actual_scalp) != len(retained_scalp_channels):
        raise ValueError(
            "Loaded BDF scalp channels do not match the full-header BioSemi64 validation."
        )

    present = _map_present_case_insensitive(raw.ch_names)
    resolved_refs: list[str] = []
    for reference in ref_pair:
        actual = present.get(str(reference).upper())
        if actual is None:
            raise ValueError(f"Loaded BDF is missing reference channel {reference!r}.")
        resolved_refs.append(actual)
    resolved_stim = present.get(str(stim_name).upper())
    if resolved_stim is None:
        raise ValueError(f"Loaded BDF is missing stimulation channel {stim_name!r}.")

    scalp_to_eeg = {name: "eeg" for name in raw.ch_names if name in retained_set}
    auxiliary_to_misc = {
        name: "misc"
        for name in raw.ch_names
        if name not in retained_set and name != resolved_stim
    }
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"The unit for channel\(s\) .* has changed from .* to .*\.",
            category=RuntimeWarning,
        )
        if auxiliary_to_misc:
            raw.set_channel_types(auxiliary_to_misc)
        if scalp_to_eeg:
            raw.set_channel_types(scalp_to_eeg)
        raw.set_channel_types({resolved_stim: "stim"})

    app.log("Applying canonical BioSemi ActiveTwo 64 montage...")
    logger.debug("[LOADER STAGE] file=%s stage=montage_apply_start", base)
    raw.set_montage(
        _cached_1010(),
        on_missing="raise",
        match_case=True,
        verbose=False,
    )

    # References remain signals through the initial mastoid reference, but
    # they are not scalp sensors and must never acquire template coordinates.
    for reference in resolved_refs:
        channel_index = raw.ch_names.index(reference)
        raw.info["chs"][channel_index]["loc"][:] = np.nan
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"The unit for channel\(s\) .* has changed from .* to .*\.",
            category=RuntimeWarning,
        )
        raw.set_channel_types({reference: "eeg" for reference in resolved_refs})

    identity = attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile=acquisition_geometry.electrode_mapping_profile,
        retained_channels=retained_scalp_channels,
        reference_channels=resolved_refs,
        stim_channel=resolved_stim,
    )
    logger.debug("[LOADER STAGE] file=%s stage=montage_apply_done", base)
    app.log(
        "BioSemi64 montage applied and validated "
        f"({len(retained_scalp_channels)} retained scalp channels)."
    )
    return identity


@contextmanager
def open_bdf_resource_header(
    app: Any,
    filepath: str,
    *,
    ref_pair: Tuple[str, str],
    first_n_channels: Optional[int],
    stim_channel: str,
    electrode_mapping_profile: Any = None,
    electrode_montage: str = BIOSEMI64_MONTAGE_ID,
    acquisition_settings: dict[str, Any] | None = None,
) -> Iterator[Optional[mne.io.BaseRaw]]:
    """Inspect bounded native metadata before admitting an import worker.

    This resource-planning exception never creates BIDS files or reads signal
    samples. Annotation-bearing files are rejected before MNE can scan their
    payload. Numerical preprocessing must use the normalized project loaders.
    """
    from Main_App.projects.hardware import require_hardware_ready

    require_hardware_ready(acquisition_settings, paths=(Path(filepath),))
    _normalize_electrode_montage(electrode_montage)
    header = inspect_bdf_header(filepath)
    if (Path(filepath).suffix.lower() != ".bdf" or header is None
            or not header.channel_count or not 0 < header.channel_count <= 4096
            or header.header_bytes != (header.channel_count + 1) * 256):
        yield None
        return
    with Path(filepath).open("rb") as stream:
        stream.seek(256)
        labels = stream.read(header.channel_count * 16)
    if len(labels) != header.channel_count * 16 or any(
        labels[index * 16:(index + 1) * 16].strip().lower() in {b"bdf annotations", b"edf annotations"}
        for index in range(header.channel_count)
    ):
        yield None
        return
    try:
        geometry = _read_biosemi64_header_geometry(
            filepath, stim_name=stim_channel, ref_pair=ref_pair,
            electrode_mapping_profile=electrode_mapping_profile,
        )
    except ValueError:
        yield None
        return
    raw = mne.io.read_raw_bdf(
        filepath, preload=False, stim_channel=stim_channel,
        include=geometry.included_source_names(first_n_channels), verbose=False,
    )
    try:
        try:
            _apply_preflight_channel_and_montage_contract(
                app, raw, base=Path(filepath).name, ref_pair=ref_pair,
                stim_name=stim_channel, acquisition_geometry=geometry,
                retained_scalp_channels=geometry.retained_scalp_names(first_n_channels),
            )
        except ValueError:
            yield None
            return
        yield raw
    finally:
        raw.close()


@contextmanager
def open_preflight_eeg_file(
    app: Any,
    filepath: str,
    ref_pair: Optional[Tuple[str, str]] = None,
    first_n_channels: Optional[int] = None,
    stim_channel: Optional[str] = None,
    electrode_mapping_profile: Optional[str] = None,
    electrode_montage: Optional[str] = None,
    acquisition_settings: dict[str, Any] | None = None,
) -> Iterator[Optional[mne.io.BaseRaw]]:
    """Open a BDF lazily for preflight QC and always close it on context exit.

    Unlike :func:`load_eeg_file`, this opt-in reader never calls ``load_data``
    and never creates a full-recording memmap. Callers must keep all lazy reads
    inside the returned context manager.
    """
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"[PREFLIGHT LAZY LOADER START] {base}: ext='{ext}'")

    from Main_App.io.hardware_loader import open_brain_products_raw, open_profiled_bdf_raw, project_acquisition_settings
    settings = project_acquisition_settings(app, acquisition_settings)
    from Main_App.projects.hardware import require_hardware_ready
    platform = require_hardware_ready(settings, paths=(Path(filepath),))
    if platform in {"brain_products", "biosemi_active_three", "unicorn"}:
        reader = open_brain_products_raw if platform == "brain_products" else open_profiled_bdf_raw
        raw = reader(
            app, filepath, settings=settings,
            stim_channel=str(stim_channel or settings.get("stim_channel") or "Status"),
        )
        try:
            yield raw
        finally:
            raw.close()
        return
    if ext != ".bdf":
        user_messages.show_warning(
            "Unsupported File",
            f"Format '{ext}' not supported. Only '.bdf' is supported.",
        )
        yield None
        return

    raw: Optional[mne.io.BaseRaw] = None
    try:
        stim_name = str(stim_channel or "").strip() or _resolve_stim(app)
        resolved_ref_pair = ref_pair or _resolve_ref_pair(app)
        resolved_montage = (
            _normalize_electrode_montage(electrode_montage)
            if electrode_montage is not None
            else _resolve_electrode_montage(app)
        )
        resolved_mapping_profile = (
            _normalize_electrode_mapping_profile(electrode_mapping_profile)
            if electrode_mapping_profile is not None
            else _resolve_electrode_mapping_profile(app)
        )
        app.log(
            f"[PREFLIGHT LAZY LOADER DEBUG] {base}: stim='{stim_name}' "
            f"ref_pair={resolved_ref_pair} montage='{resolved_montage}' "
            f"mapping_profile='{resolved_mapping_profile}'"
        )

        preflight = inspect_bdf_header(filepath)
        if preflight and preflight.recording_not_started:
            message = format_bdf_recording_not_started_message([base])
            detailed = (
                f"[LOADER EXCLUDED] {base}: {message} "
                f"(size={preflight.file_size} bytes, "
                f"header_bytes={preflight.header_bytes}, "
                f"data_records={preflight.data_records})"
            )
            if not _try_warning_log(app, detailed):
                app.log(detailed)
            logger.warning(
                "bdf_recording_not_started file=%s size=%d header_bytes=%s data_records=%s",
                filepath,
                preflight.file_size,
                preflight.header_bytes,
                preflight.data_records,
            )
        else:
            acquisition_geometry = _read_biosemi64_header_geometry(
                filepath,
                stim_name=stim_name,
                ref_pair=resolved_ref_pair,
                electrode_mapping_profile=resolved_mapping_profile,
            )
            retained_scalp_channels = acquisition_geometry.retained_scalp_names(
                first_n_channels
            )
            include_channels = acquisition_geometry.included_source_names(first_n_channels)
            if include_channels is not None:
                app.log(
                    f"[LOADER CHANNEL SUBSET] {base}: opening "
                    f"{len(include_channels)} channels lazily after validating all 64 scalp "
                    f"identities (first_n={first_n_channels}, refs={resolved_ref_pair}, "
                    f"stim='{stim_name}')"
                )

            with warnings.catch_warnings(record=True) as caught_read_warnings:
                warnings.simplefilter("always")
                with mne.utils.use_log_level("WARNING"):
                    logger.debug(
                        "[PREFLIGHT LAZY LOADER STAGE] file=%s stage=read_raw_bdf_start "
                        "selected_channels=%s",
                        base,
                        len(include_channels) if include_channels else "all",
                    )
                    from Main_App.io.bids_loader import read_project_bids_raw

                    raw = read_project_bids_raw(
                        app, filepath, settings=settings,
                        preload=False,
                        stim_channel=stim_name if stim_name else "Status",
                        include=include_channels,
                    )
                    logger.debug(
                        "[PREFLIGHT LAZY LOADER STAGE] file=%s stage=read_raw_bdf_done "
                        "channels=%d",
                        base,
                        len(raw.ch_names),
                    )
            _emit_reader_warnings(app, filepath, caught_read_warnings)

            if raw is None:
                raise ValueError("MNE load returned None.")

            app.log(
                f"Load OK: {len(raw.ch_names)} channels @ {raw.info['sfreq']:.1f} Hz."
            )
            _apply_preflight_channel_and_montage_contract(
                app,
                raw,
                base=base,
                ref_pair=resolved_ref_pair,
                stim_name=stim_name,
                acquisition_geometry=acquisition_geometry,
                retained_scalp_channels=retained_scalp_channels,
            )
            from Main_App.io.acquisition_metadata import attach_recording_contract
            attach_recording_contract(raw, settings)
            app.log(f"[PREFLIGHT LAZY LOADER READY] {base}")
    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        if raw is not None:
            try:
                raw.close()
            except (AttributeError, RuntimeError, OSError, ValueError):
                pass
            raw = None
        try:
            user_messages.show_error("Loading Error", f"Could not load: {base}\nError: {e}")
        except (RuntimeError, TypeError):
            pass

    if raw is None:
        yield None
        return

    try:
        yield raw
    finally:
        try:
            raw.close()
        except (AttributeError, RuntimeError, OSError, ValueError) as close_error:
            app.log(f"Warning: Could not close lazy BDF {base}: {close_error}")
        app.log(f"[PREFLIGHT LAZY LOADER CLOSED] {base}")


def load_eeg_file(
    app: Any,
    filepath: str,
    ref_pair: Optional[Tuple[str, str]] = None,
    first_n_channels: Optional[int] = None,
    stim_channel: Optional[str] = None,
    electrode_mapping_profile: Optional[str] = None,
    electrode_montage: Optional[str] = None,
    *,
    preload_path: str | Path | None = None,
    preload_in_memory: bool = False,
    acquisition_settings: dict[str, Any] | None = None,
) -> Optional[mne.io.BaseRaw]:
    """Load an EEG file and apply montage without resampling.

    A run-owned caller may supply a new absolute ``preload_path`` inside its
    private temporary directory. That caller owns the Raw and file cleanup.
    Existing destinations are never overwritten through this opt-in path.
    Experimental in-memory preloading creates no full-recording memmap.
    """
    if preload_in_memory and preload_path is not None:
        raise ValueError("RAM preloading cannot use a disk preload path.")
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"[LOADER START] {base}: ext='{ext}'")
    raw: Optional[mne.io.BaseRaw] = None
    try:
        from Main_App.io.hardware_loader import open_brain_products_raw, open_profiled_bdf_raw, project_acquisition_settings
        settings = project_acquisition_settings(app, acquisition_settings)
        from Main_App.projects.hardware import require_hardware_ready
        platform = require_hardware_ready(settings, paths=(Path(filepath),))
        if preload_in_memory:
            memmap_path = None
        elif preload_path is None:
            memmap_dir = _memmap_dir_for_pid()
            import uuid
            memmap_path = str(memmap_dir / (uuid.uuid4().hex + "_raw.dat"))
        else:
            destination = Path(preload_path)
            if not destination.is_absolute():
                raise ValueError("Run-owned EEG preload paths must be absolute.")
            # The shared BIDS reader exclusively reserves this destination
            # before preloading and owns cleanup if loading fails.
            memmap_path = str(destination)

        if platform in {"brain_products", "biosemi_active_three", "unicorn"}:
            reader = open_brain_products_raw if platform == "brain_products" else open_profiled_bdf_raw
            return reader(
                app, filepath, settings=settings,
                preload=True if preload_in_memory else memmap_path,
                stim_channel=str(stim_channel or settings.get("stim_channel") or "Status"),
            )
        stim_name = str(stim_channel or "").strip() or _resolve_stim(app)
        if not ref_pair:
            ref_pair = _resolve_ref_pair(app)
        resolved_montage = (
            _normalize_electrode_montage(electrode_montage)
            if electrode_montage is not None
            else _resolve_electrode_montage(app)
        )
        resolved_mapping_profile = (
            _normalize_electrode_mapping_profile(electrode_mapping_profile)
            if electrode_mapping_profile is not None
            else _resolve_electrode_mapping_profile(app)
        )

        app.log(
            f"[LOADER DEBUG] {base}: stim='{stim_name}' "
            f"ref_pair={ref_pair} montage='{resolved_montage}' "
            f"mapping_profile='{resolved_mapping_profile}' "
            f"preload_mode='{'ram' if preload_in_memory else 'disk'}' "
            f"memmap_path='{memmap_path}'"
        )

        if ext == ".bdf":
            preflight = inspect_bdf_header(filepath)
            if preflight and preflight.recording_not_started:
                message = format_bdf_recording_not_started_message([base])
                detailed = (
                    f"[LOADER EXCLUDED] {base}: {message} "
                    f"(size={preflight.file_size} bytes, "
                    f"header_bytes={preflight.header_bytes}, "
                    f"data_records={preflight.data_records})"
                )
                if not _try_warning_log(app, detailed):
                    app.log(detailed)
                logger.warning(
                    "bdf_recording_not_started file=%s size=%d header_bytes=%s data_records=%s",
                    filepath,
                    preflight.file_size,
                    preflight.header_bytes,
                    preflight.data_records,
                )
                return None

            acquisition_geometry = _read_biosemi64_header_geometry(
                filepath,
                stim_name=stim_name,
                ref_pair=ref_pair,
                electrode_mapping_profile=resolved_mapping_profile,
            )
            retained_scalp_channels = acquisition_geometry.retained_scalp_names(
                first_n_channels
            )
            include_channels = acquisition_geometry.included_source_names(first_n_channels)
            if include_channels is not None:
                app.log(
                    f"[LOADER CHANNEL SUBSET] {base}: loading "
                    f"{len(include_channels)} channels after validating all 64 scalp "
                    f"identities (first_n={first_n_channels}, refs={ref_pair}, "
                    f"stim='{stim_name}')"
                )
            with warnings.catch_warnings(record=True) as caught_read_warnings:
                warnings.simplefilter("always")
                with mne.utils.use_log_level("WARNING"):
                    logger.debug(
                        "[LOADER STAGE] file=%s stage=read_raw_bdf_start selected_channels=%s memmap_path=%s",
                        base,
                        len(include_channels) if include_channels else "all",
                        memmap_path,
                    )
                    from Main_App.io.bids_loader import read_project_bids_raw

                    raw = read_project_bids_raw(
                        app, filepath, settings=settings,
                        preload=True if preload_in_memory else memmap_path,
                        stim_channel=stim_name if stim_name else "Status",
                        include=include_channels,
                    )
                    logger.debug(
                        "[LOADER STAGE] file=%s stage=read_raw_bdf_done channels=%d",
                        base,
                        len(raw.ch_names),
                    )
            _emit_reader_warnings(app, filepath, caught_read_warnings)
            logger.debug("[LOADER STAGE] file=%s stage=load_data_start", base)
            raw.load_data()
            logger.debug("[LOADER STAGE] file=%s stage=load_data_done", base)
            app.log("BDF loaded successfully.")

        else:
            user_messages.show_warning(
                "Unsupported File",
                f"Format '{ext}' not supported. Only '.bdf' is supported.",
            )
            return None

        if raw is None:
            raise ValueError("MNE load returned None.")

        app.log(f"Load OK: {len(raw.ch_names)} channels @ {raw.info['sfreq']:.1f} Hz.")

        _apply_preflight_channel_and_montage_contract(
            app,
            raw,
            base=base,
            ref_pair=ref_pair,
            stim_name=stim_name,
            acquisition_geometry=acquisition_geometry,
            retained_scalp_channels=retained_scalp_channels,
        )
        from Main_App.io.acquisition_metadata import attach_recording_contract
        attach_recording_contract(raw, settings)

        app.log(f"[LOADER END] {base}")
        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        if raw is not None:
            try:
                from Main_App.io.brain_products import close_brain_products_raw
                close_brain_products_raw(raw)
                if memmap_path is not None:
                    Path(memmap_path).unlink(missing_ok=True)
            except (AttributeError, RuntimeError, OSError, ValueError):
                logger.warning("Failed to release EEG preload after loading error", exc_info=True)
        try:
            user_messages.show_error("Loading Error", f"Could not load: {base}\nError: {e}")
        except Exception:
            pass
        return None


# Additive inspection APIs remain separate from production BioSemi loading.
from Main_App.io.recording_inspection import inspect_eeg_recording  # noqa: E402
from Main_App.io.unicorn_raw import open_unicorn_recording_raw  # noqa: E402

# Generic admission names keep format interpretation at this upstream boundary.
RecordingPreflightInfo = BdfPreflightInfo
RECORDING_NOT_STARTED_REASON = BDF_RECORDING_NOT_STARTED_REASON
inspect_recording_header = inspect_bdf_header

__all__ = [
    "RecordingPreflightInfo",
    "RECORDING_NOT_STARTED_REASON",
    "inspect_recording_header",
    "BDF_RECORDING_NOT_STARTED_REASON",
    "BdfPreflightInfo",
    "_cached_1010",
    "_cached_1020",
    "_canon_present",
    "_emit_reader_warnings",
    "format_bdf_recording_not_started_message",
    "inspect_bdf_header",
    "inspect_eeg_recording",
    "read_bdf_sampling_rate_hz",
    "is_bdf_recording_not_started",
    "_map_present_case_insensitive",
    "_memmap_dir_for_pid",
    "_resolve_ref_pair",
    "_resolve_electrode_mapping_profile",
    "_resolve_electrode_montage",
    "_resolve_stim",
    "_try_warning_log",
    "load_eeg_file",
    "open_preflight_eeg_file",
    "open_bdf_resource_header",
    "open_unicorn_recording_raw",
]

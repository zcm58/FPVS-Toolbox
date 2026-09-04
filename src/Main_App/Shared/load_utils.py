"""BDF-only EEG loader for the shared processing path.

This module owns the loader behavior previously kept in legacy loaders. Keep load order, channel typing, memmap
paths, montage behavior, and return semantics aligned with the BDF loader
contract unless a future task explicitly changes the processing pipeline.
"""

from __future__ import annotations

import logging
import os
import tempfile
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional, Sequence, Set, Tuple

import mne
import numpy as np

from Main_App.Shared import user_messages
from Main_App.Shared.eeg_geometry import (
    BIOSEMI64_CHANNEL_SET,
    BIOSEMI64_MONTAGE_ID,
    BioSemi64AcquisitionGeometry,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
    validate_biosemi64_acquisition_channels,
)

logger = logging.getLogger(__name__)
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
    """Per-process memmap directory to avoid worker collisions."""
    d = Path(tempfile.gettempdir()) / "fpvs_memmap" / f"pid_{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


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
def open_preflight_eeg_file(
    app: Any,
    filepath: str,
    ref_pair: Optional[Tuple[str, str]] = None,
    first_n_channels: Optional[int] = None,
    stim_channel: Optional[str] = None,
    electrode_mapping_profile: Optional[str] = None,
    electrode_montage: Optional[str] = None,
) -> Iterator[Optional[mne.io.BaseRaw]]:
    """Open a BDF lazily for preflight QC and always close it on context exit.

    Unlike :func:`load_eeg_file`, this opt-in reader never calls ``load_data``
    and never creates a full-recording memmap. Callers must keep all lazy reads
    inside the returned context manager.
    """
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"[PREFLIGHT LAZY LOADER START] {base}: ext='{ext}'")

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
                    raw = mne.io.read_raw_bdf(
                        filepath,
                        preload=False,
                        stim_channel=stim_name if stim_name else "Status",
                        include=include_channels,
                        verbose=False,
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
) -> Optional[mne.io.BaseRaw]:
    """Load an EEG file with disk-backed memmap and apply montage without resampling."""
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"[LOADER START] {base}: ext='{ext}'")
    raw: Optional[mne.io.BaseRaw] = None
    try:
        memmap_dir = _memmap_dir_for_pid()
        memmap_path = str(memmap_dir / (Path(filepath).stem + "_raw.dat"))

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
                    raw = mne.io.read_raw_bdf(
                        filepath,
                        preload=memmap_path,
                        stim_channel=stim_name if stim_name else "Status",
                        include=include_channels,
                        verbose=False,
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

        app.log(f"[LOADER END] {base}")
        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        if raw is not None:
            try:
                raw.close()
            except (AttributeError, RuntimeError, OSError, ValueError):
                pass
        try:
            user_messages.show_error("Loading Error", f"Could not load: {base}\nError: {e}")
        except Exception:
            pass
        return None

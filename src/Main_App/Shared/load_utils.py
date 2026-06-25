"""BDF-only EEG loader for the shared processing path.

This module owns the loader behavior previously kept in legacy loaders. Keep load order, channel typing, memmap
paths, montage behavior, and return semantics aligned with the BDF loader
contract unless a future task explicitly changes the processing pipeline.
"""

from __future__ import annotations

import logging
import os
import ast
import re
import tempfile
import warnings
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence, Set, Tuple

import mne

from Main_App.Shared import user_messages

logger = logging.getLogger(__name__)
BDF_RECORDING_NOT_STARTED_REASON = "recording_not_started"
_MONTAGE_MISSING_RE = re.compile(
    r"The channels missing from the montage are:\s*\n\n(?P<channels>\[[^\]]*\])",
    re.MULTILINE,
)


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


@lru_cache(maxsize=1)
def _cached_1010() -> mne.channels.DigMontage:
    """Cached once per process to avoid repeated montage builds.

    MNE does not expose a builtin named ``standard_1010``; ``standard_1005`` is
    the denser standard montage that includes 10-10 positions.
    """
    return mne.channels.make_standard_montage("standard_1005")


_cached_1020 = _cached_1010  # temporary compatibility alias for stale imports


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
) -> Optional[list[str]]:
    """Return first-N channels plus ref/stim names, preserving file order."""
    if not first_n_channels or first_n_channels <= 0:
        return None

    base = os.path.basename(filepath)
    logger.info(
        "[LOADER STAGE] file=%s stage=header_read_start first_n_channels=%s",
        base,
        first_n_channels,
    )
    with mne.utils.use_log_level("WARNING"):
        header = mne.io.read_raw_bdf(
            filepath,
            preload=False,
            stim_channel=stim_name if stim_name else "Status",
            verbose=False,
        )
    try:
        names = list(header.ch_names)
    finally:
        try:
            header.close()
        except (AttributeError, RuntimeError, OSError, ValueError):
            pass

    keep_names = list(names[: int(first_n_channels)])
    present = _map_present_case_insensitive(names)
    for candidate in (*ref_pair, stim_name):
        if not candidate:
            continue
        actual = present.get(str(candidate).upper())
        if actual and actual not in keep_names:
            keep_names.append(actual)
    logger.info(
        "[LOADER STAGE] file=%s stage=header_read_done total_channels=%d selected_channels=%d",
        base,
        len(names),
        len(keep_names),
    )
    return keep_names


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


def _missing_montage_channels(message: str) -> Set[str]:
    """Extract channel names from MNE's missing-DigMontage warning."""
    match = _MONTAGE_MISSING_RE.search(message)
    if not match:
        return set()
    try:
        parsed = ast.literal_eval(match.group("channels"))
    except (SyntaxError, ValueError):
        return set()
    if not isinstance(parsed, list):
        return set()
    return {str(channel) for channel in parsed}


def _apply_montage_suppressing_expected_ref_warnings(
    raw: mne.io.BaseRaw,
    montage: mne.channels.DigMontage,
    *,
    expected_missing_refs: Set[str],
) -> None:
    """Apply montage while suppressing expected missing reference positions only."""
    with warnings.catch_warnings(record=True) as caught_montage_warnings:
        warnings.simplefilter("always")
        raw.set_montage(
            montage,
            on_missing="warn",
            match_case=False,
            verbose=False,
        )

    for caught in caught_montage_warnings:
        warning_text = str(caught.message)
        missing = _missing_montage_channels(warning_text)
        if missing and missing.issubset(expected_missing_refs):
            continue
        warnings.warn(
            caught.message,
            category=caught.category,
            stacklevel=2,
        )


def load_eeg_file(
    app: Any,
    filepath: str,
    ref_pair: Optional[Tuple[str, str]] = None,
    first_n_channels: Optional[int] = None,
) -> Optional[mne.io.BaseRaw]:
    """Load an EEG file with disk-backed memmap and apply montage without resampling."""
    ext = os.path.splitext(filepath)[1].lower()
    base = os.path.basename(filepath)
    app.log(f"[LOADER START] {base}: ext='{ext}'")
    try:
        memmap_dir = _memmap_dir_for_pid()
        memmap_path = str(memmap_dir / (Path(filepath).stem + "_raw.dat"))

        stim_name = _resolve_stim(app)
        if not ref_pair:
            ref_pair = _resolve_ref_pair(app)

        app.log(
            f"[LOADER DEBUG] {base}: stim='{stim_name}' "
            f"ref_pair={ref_pair} memmap_path='{memmap_path}'"
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

            include_channels = None
            if first_n_channels:
                try:
                    include_channels = _resolve_channel_subset(
                        filepath,
                        stim_name=stim_name,
                        ref_pair=ref_pair,
                        first_n_channels=first_n_channels,
                    )
                    app.log(
                        f"[LOADER CHANNEL SUBSET] {base}: loading "
                        f"{len(include_channels or [])} channels "
                        f"(first_n={first_n_channels}, refs={ref_pair}, stim='{stim_name}')"
                    )
                except Exception as subset_err:
                    app.log(
                        f"[LOADER CHANNEL SUBSET WARNING] {base}: failed to resolve "
                        f"first_n={first_n_channels}; falling back to full load: {subset_err}"
                    )
            with warnings.catch_warnings(record=True) as caught_read_warnings:
                warnings.simplefilter("always")
                with mne.utils.use_log_level("WARNING"):
                    logger.info(
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
                    logger.info(
                        "[LOADER STAGE] file=%s stage=read_raw_bdf_done channels=%d",
                        base,
                        len(raw.ch_names),
                    )
            _emit_reader_warnings(app, filepath, caught_read_warnings)
            logger.info("[LOADER STAGE] file=%s stage=load_data_start", base)
            raw.load_data()
            logger.info("[LOADER STAGE] file=%s stage=load_data_done", base)
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

        try:
            logger.info("[LOADER STAGE] file=%s stage=channel_typing_start", base)
            ref_keep = _canon_present(raw.ch_names, ref_pair or ())
            exg_labels = [f"EXG{i}" for i in range(1, 9)]
            exg_present = _canon_present(raw.ch_names, exg_labels)

            app.log(
                f"[LOADER DEBUG] {base}: exg_present={sorted(exg_present)} "
                f"ref_keep={sorted(ref_keep)}"
            )

            to_misc = {ch: "misc" for ch in exg_present if ch not in ref_keep}
            to_eeg = {ch: "eeg" for ch in ref_keep}

            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"The unit for channel\(s\) .* has changed from .* to .*\.",
                    category=RuntimeWarning,
                )
                if to_misc:
                    raw.set_channel_types(to_misc)
                if to_eeg:
                    raw.set_channel_types(to_eeg)
                if stim_name in raw.ch_names:
                    raw.set_channel_types({stim_name: "stim"})

            kept = sorted(ref_keep)
            demoted = sorted([ch for ch in exg_present if ch not in ref_keep])
            app.log(f"EXG policy A applied. Keep as EEG: {kept} | Demoted to misc: {demoted}")
            logger.info(
                "[LOADER STAGE] file=%s stage=channel_typing_done ref_keep=%s demoted=%s",
                base,
                kept,
                demoted,
            )
        except Exception as e:
            app.log(f"Warning: EXG/stim typing adjustment failed: {e}")

        app.log("Applying standard_1005 montage for 10-10 coverage...")
        try:
            logger.info("[LOADER STAGE] file=%s stage=montage_apply_start", base)
            _apply_montage_suppressing_expected_ref_warnings(
                raw,
                _cached_1010(),
                expected_missing_refs=ref_keep,
            )
            logger.info("[LOADER STAGE] file=%s stage=montage_apply_done", base)
            app.log("Montage applied.")
        except Exception as e:
            app.log(f"Warning: Montage error: {e}")

        app.log(f"[LOADER END] {base}")
        return raw

    except Exception as e:
        app.log(f"!!! Load Error {base}: {e}")
        try:
            user_messages.show_error("Loading Error", f"Could not load: {base}\nError: {e}")
        except Exception:
            pass
        return None

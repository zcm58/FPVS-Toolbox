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
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set, Tuple

import mne

from Main_App.Shared import user_messages

logger = logging.getLogger(__name__)


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


def load_eeg_file(
    app: Any,
    filepath: str,
    ref_pair: Optional[Tuple[str, str]] = None,
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
            with warnings.catch_warnings(record=True) as caught_read_warnings:
                warnings.simplefilter("always")
                with mne.utils.use_log_level("WARNING"):
                    raw = mne.io.read_raw_bdf(
                        filepath,
                        preload=memmap_path,
                        stim_channel=stim_name if stim_name else "Status",
                        verbose=False,
                    )
            _emit_reader_warnings(app, filepath, caught_read_warnings)
            raw.load_data()
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
        except Exception as e:
            app.log(f"Warning: EXG/stim typing adjustment failed: {e}")

        app.log("Applying standard_1005 montage for 10-10 coverage...")
        try:
            raw.set_montage(_cached_1010(), on_missing="warn", match_case=False, verbose=False)
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

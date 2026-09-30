"""Context-owned MNE reading for explicit Unicorn input, not a QC release.

MNE 1.9 cannot override a nonempty malformed BDF unit or lazily read a file-like
header overlay. A verified, temporary copy changes only the approved dimension
fields; stock MNE then performs the same calibration for every preload mode.
"""
from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import traceback
from typing import Literal

import mne

from Main_App.io.acquisition_profiles import resolve_acquisition_contract
from Main_App.io.recording_events import EventAuthority
from Main_App.io.recording_inspection import RecordingInspection, inspect_eeg_recording
from Main_App.io.unicorn_units import UnicornUnitError, require_unicorn_contract


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnicornRawRecording:
    raw: mne.io.BaseRaw
    inspection: RecordingInspection
    _reader_provenance_json: str

    @property
    def scientific_processing_allowed(self) -> bool:
        return False

    @property
    def reader_provenance(self) -> dict:
        """Detached source/adapter evidence, never a processing-cache identity."""
        return json.loads(self._reader_provenance_json)


def _reader_roles(inspection: RecordingInspection, status_channel: str) -> tuple[list[str], list[str]]:
    blocking = [issue.detail for issue in inspection.issues
                if issue.code not in {"unqualified_acquisition", "integration_pending"}]
    if blocking or inspection.eeg_unit_policy is None:
        raise UnicornUnitError("Unicorn Raw reading is blocked: " + "; ".join(blocking))
    eeg = {channel.source_label.casefold() for channel in inspection.eeg_unit_policy.channels}
    misc, stim = [], []
    for signal in inspection.source.header.signals:
        if signal.is_annotation:
            continue
        if Fraction(signal.samples_per_record) / Fraction(inspection.source.header.record_duration) != 250:
            raise UnicornUnitError("Every recorded signal must use the native 250 Hz grid; no MNE resampling is permitted.")
        name = signal.label.casefold()
        if name in eeg:
            continue
        if name == status_channel.casefold():
            stim.append(signal.label)
        elif name in {"cnt", "valid", "dt"}:
            misc.append(signal.label)
        else:
            raise UnicornUnitError(f"Unregistered Unicorn channel role: {signal.label!r}.")
    return misc, stim


def _scratch_parent(project_root: str | Path) -> Path:
    root = Path(project_root)
    if not root.is_absolute():
        raise ValueError("Unicorn reader requires the absolute active project root.")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The active project root must be an existing directory.")
    parent = root
    for name in (".fpvs_processing", "unicorn_reader"):
        parent = parent / name
        if parent.resolve() != parent:
            raise ValueError("Unicorn reader scratch directories must not be redirected.")
        parent.mkdir(exist_ok=True)
        if parent.resolve(strict=True) != parent or not parent.is_dir():
            raise ValueError("Unicorn reader scratch directories must not be redirected.")
    return parent


def _assert_owned_directory(directory: Path, parent: Path, identity: tuple[int, int]) -> None:
    if (parent.resolve(strict=True) != parent or directory.parent != parent
            or directory.resolve(strict=True) != directory
            or not directory.is_dir()):
        raise ValueError("Unicorn reader directory was redirected; refusing file access or cleanup.")
    current = directory.stat()
    if (current.st_dev, current.st_ino) != identity:
        raise ValueError("Unicorn reader directory was replaced; refusing file access or cleanup.")


def _copy_reader_source(
    path: Path, destination: Path, inspection: RecordingInspection,
) -> tuple[str, list[dict], tuple[int, int, int, int]]:
    """Bind copied bytes to inspection before changing any approved unit field."""
    digest = hashlib.sha256()
    before = path.stat()
    with path.open("rb") as source, destination.open("x+b") as target:
        opened = os.fstat(source.fileno())
        if ((opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
                != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)):
            raise UnicornUnitError("Unicorn source was replaced before reader preparation.")
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
            target.write(chunk)
        after = path.stat()
        if (digest.hexdigest() != inspection.source.file_sha256
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise UnicornUnitError("Unicorn source changed after inspection; refusing the reader copy.")
        target.flush()
        target.seek(0)
        if hashlib.file_digest(target, "sha256").hexdigest() != inspection.source.file_sha256:
            raise UnicornUnitError("The staged Unicorn copy does not match the inspected source.")
        policy = inspection.eeg_unit_policy
        corrected = {channel.source_label for channel in policy.channels if channel.recorder_label_correction}
        header = inspection.source.header
        patches = []
        for index, signal in enumerate(header.signals):
            if signal.label not in corrected:
                continue
            offset = 256 + 96 * len(header.signals) + 8 * index
            target.seek(offset)
            original = target.read(8)
            if original != b"?V      ":
                raise UnicornUnitError("Unicorn unit bytes do not match the verified Recorder header pattern.")
            target.seek(offset)
            target.write(b"uV      ")
            patches.append({"source_label": signal.label, "byte_offset": offset,
                            "original_unit": "?V", "reader_unit": "uV"})
        target.flush()
        target.seek(0)
        normalized_sha256 = hashlib.file_digest(target, "sha256").hexdigest()
        staged = os.fstat(target.fileno())
        identity = (staged.st_dev, staged.st_ino, staged.st_size, staged.st_mtime_ns)
    return normalized_sha256, patches, identity


def _close_raw(raw: mne.io.BaseRaw | None, mmap) -> None:
    try:
        if raw is not None:
            # Match the existing source-prefetch owner: Raw.close() does not
            # close its memmap, and its destructor must not unlink a reused path.
            if mmap is not None:
                raw._data = None
            raw.close()
    finally:
        if mmap is not None:
            mmap.close()


@contextmanager
def open_unicorn_recording_raw(
    path: str | Path, settings: Mapping, *, project_root: str | Path,
    event_authority: EventAuthority, preload: bool | Literal["memmap"] = False,
    numeric_annotations: bool = False, named_annotation_codes: Mapping[str, int] | None = None,
    marker_labels: tuple[str, ...] = (), status_channel: str = "Status",
) -> Iterator[UnicornRawRecording]:
    """Read corrected Unicorn EEG in volts using lazy, RAM or disk preload.

    Call from a worker: inspection, hashing and staging are file I/O. The active
    project root is mandatory; no source or other project's file is overwritten.
    Keep Raw use within this context (including any speculative disk preload).
    Original inspection/canonical events stay authoritative, not Raw.filenames
    or a fresh MNE find_events call. This does not enable scientific processing.
    """
    require_unicorn_contract(resolve_acquisition_contract(settings))
    if not (isinstance(preload, bool) or isinstance(preload, str) and preload == "memmap"):
        raise ValueError("Unicorn preload must be False, True, or 'memmap'.")
    path = Path(path).resolve(strict=True)
    inspection = inspect_eeg_recording(
        path, settings, event_authority=event_authority, numeric_annotations=numeric_annotations,
        named_annotation_codes=named_annotation_codes, marker_labels=marker_labels, status_channel=status_channel,
    )
    misc, stim = _reader_roles(inspection, status_channel)
    parent = _scratch_parent(project_root)
    directory = Path(tempfile.mkdtemp(prefix="reader-", dir=parent))
    stat = directory.stat()
    identity = (stat.st_dev, stat.st_ino)
    reader_path, mmap_path = directory / "reader.bdf", directory / "samples.dat"
    raw, mmap = None, None
    try:
        _assert_owned_directory(directory, parent, identity)
        normalized_sha256, patches, staged_identity = _copy_reader_source(path, reader_path, inspection)
        _assert_owned_directory(directory, parent, identity)
        staged = reader_path.stat()
        if (reader_path.resolve(strict=True) != reader_path
                or (staged.st_dev, staged.st_ino, staged.st_size, staged.st_mtime_ns) != staged_identity):
            raise UnicornUnitError("The staged Unicorn source was replaced before MNE could read it.")
        selected_preload = str(mmap_path) if preload == "memmap" else preload
        try:
            raw = mne.io.read_raw_bdf(
                reader_path, preload=selected_preload, stim_channel=stim or None,
                misc=misc, infer_types=False, verbose=False,
            )
        except Exception as exc:
            # Failed MNE construction can leave an allocated mmap in traceback
            # locals before Raw is returned. Release those references before
            # deleting our files on Windows; traceback locations remain intact.
            traceback.clear_frames(exc.__traceback__)
            raise
        mmap = getattr(getattr(raw, "_data", None), "_mmap", None)
        header = inspection.source.header
        expected_names = [signal.label for signal in header.signals if not signal.is_annotation]
        expected_samples = header.data_records * int(Fraction(header.record_duration) * 250)
        if (raw.ch_names != expected_names or raw.info["sfreq"] != 250 or raw.n_times != expected_samples
                or len(raw.get_channel_types(picks="eeg")) != 8):
            raise UnicornUnitError("MNE did not preserve the validated Unicorn channel/native-sample contract.")
        provenance = {
            "adapter": "unicorn_bdf_mne_reader", "version": "1.0", "mne_version": mne.__version__,
            "source_sha256": inspection.source.file_sha256, "reader_sha256": normalized_sha256,
            "inspection_fingerprint": inspection.inspection_fingerprint,
            "eeg_unit_policy": inspection.eeg_unit_policy.summary(), "header_patches": patches,
            "scientific_processing_allowed": False,
        }
        logger.info("unicorn_reader_opened source_sha256=%s unit_fields_corrected=%d preload=%s",
                    inspection.source.file_sha256, len(patches), preload)
        yield UnicornRawRecording(raw, inspection, json.dumps(provenance, sort_keys=True))
    finally:
        try:
            _close_raw(raw, mmap)
        finally:
            _assert_owned_directory(directory, parent, identity)
            # Remove only the two run-owned files, never recursively delete a
            # caller-selected tree or touch original recordings.
            reader_path.unlink(missing_ok=True)
            mmap_path.unlink(missing_ok=True)
            directory.rmdir()

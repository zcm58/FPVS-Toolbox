"""Project-local BIDS import boundary, without scientific preprocessing.

BDF payloads are copied byte-for-byte; BrainVision signal bytes are copied and
only companion links change. BVRF has no standard raw EEG-BIDS representation
that preserves arbitrary calibrated float64 samples, so it uses an explicitly
labeled FIF64 derivative. That exception is never advertised as raw EEG-BIDS.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
from time import perf_counter
import traceback
from typing import Any, Mapping
import uuid

import mne
import numpy as np

from Main_App.io.recording_sources import recording_source_files

logger = logging.getLogger(__name__)
IMPORT_VERSION = "bids_import_v1"
_BIDS_TYPES = {"eeg": "EEG", "eog": "EOG", "ecg": "ECG", "emg": "EMG", "stim": "TRIG"}
_SETTING_KEYS = ("hardware_platform", "hardware_confirmed", "hardware_selection_source",
                 "channel_types", "electrode_montage", "electrode_mapping_profile", "stim_channel")


@dataclass(frozen=True)
class BidsRecording:
    """An immutable publication of one imported recording, plus measured costs."""

    bids_path: Any
    dataset_root: Path
    manifest_path: Path
    source_identity: tuple[dict, ...]
    conversion_seconds: float
    identity_seconds: float
    reused: bool
    representation: str

    @property
    def header_path(self) -> Path:
        return Path(self.bids_path.fpath)


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _source_identity(source: Path) -> tuple[dict, ...]:
    rows = []
    for path in recording_source_files(source):
        path = path.resolve(strict=True)
        before = path.stat()
        digest = _digest(path)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise OSError("Recording changed while its import identity was calculated.")
        rows.append({"path": str(path), "size": after.st_size, "mtime_ns": after.st_mtime_ns,
                     "ctime_ns": after.st_ctime_ns, "sha256": digest})
    return tuple(rows)


def _contained(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    # On Windows, resolve() can retain the extended-length prefix while a
    # concurrent importer creates the previously missing parent directories.
    # Normalize that spelling for comparison only, after resolving junctions.
    def comparable(value: Path) -> Path:
        text = str(value)
        if os.name == "nt":
            if text.startswith("\\\\?\\UNC\\"):
                text = "\\\\" + text[8:]
            elif text.startswith("\\\\?\\") and len(text) > 6 and text[5] == ":":
                text = text[4:]
        return Path(text)

    target, parent = comparable(resolved), comparable(root)
    if not target.is_relative_to(parent) or target == parent:
        raise ValueError(f"BIDS import outputs must remain inside the active project root: {resolved!s} is outside {root!s}.")
    return resolved


def _tsv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _copy_brainvision(source: Path, target: Path) -> None:
    """Repair declared links without assuming companions share a basename."""
    header, data, markers = recording_source_files(source)
    shutil.copyfile(data, target.with_suffix(".eeg"))
    for original, destination in ((header, target), (markers, target.with_suffix(".vmrk"))):
        payload = original.read_bytes()
        codepage = re.search(rb"(?im)^Codepage\s*=\s*([^\r\n]+)", payload)
        encoding = codepage.group(1).decode("ascii").strip() if codepage else "utf-8-sig"
        if encoding.upper() == "ANSI":
            encoding = "cp1252"
        try:
            content = payload.decode(encoding)
        except UnicodeDecodeError:
            if codepage:
                raise
            encoding, content = "cp1252", payload.decode("cp1252")
        for key, suffix in (("DataFile", ".eeg"), ("MarkerFile", ".vmrk")):
            content = re.sub(rf"(?im)^(\s*{key}\s*=)[^\r\n]+",
                             lambda match: match[1] + target.with_suffix(suffix).name, content)
        destination.write_bytes(content.encode(encoding))


def _annotation_identity(raw: mne.io.BaseRaw) -> dict:
    return {"onset": raw.annotations.onset.tolist(), "duration": raw.annotations.duration.tolist(),
            "description": raw.annotations.description.tolist(),
            "orig_time": raw.annotations.orig_time.isoformat() if raw.annotations.orig_time else None}


def _source_subject(raw: mne.io.BaseRaw) -> dict | None:
    subject = raw.info.get("subject_info")
    if subject is None:
        return None
    return {key: value.isoformat() if isinstance(value, date) else value.item() if isinstance(value, np.generic) else value
            for key, value in subject.items()}


def _metadata(raw: mne.io.BaseRaw, target: Path, settings: Mapping, *, source: Path) -> dict:
    """Write source facts, never project preprocessing choices masquerading as acquisition."""
    from Main_App.projects.hardware import resolve_hardware

    hardware = resolve_hardware(settings)
    stem = target.name.removesuffix(target.suffix).removesuffix("_eeg")
    folder = target.parent
    types = raw.get_channel_types()
    units = raw._orig_units or {}
    roles = settings.get("channel_types") or {}
    if not isinstance(roles, Mapping) or any(name not in raw.ch_names for name in roles):
        raise ValueError("Channel type overrides must name recorded channels.")
    effective_types = [roles.get(name, kind) for name, kind in zip(raw.ch_names, types, strict=True)]
    rows = [{"name": name, "type": _BIDS_TYPES.get(kind, "MISC"),
             "units": units.get(name) or "n/a", "status": "bad" if name in raw.info["bads"] else "good"}
            for name, kind in zip(raw.ch_names, effective_types, strict=True)]
    _tsv(folder / f"{stem}_channels.tsv", ("name", "type", "units", "status"), rows)
    metadata = {
        "TaskName": "FPVS", "SamplingFrequency": raw.info["sfreq"],
        "EEGReference": "CMS" if hardware.platform == "biosemi" else "n/a",
        "PowerLineFrequency": raw.info.get("line_freq") or "n/a", "SoftwareFilters": "n/a",
        "HardwareFilters": "n/a", "RecordingDuration": raw.n_times / raw.info["sfreq"],
        "RecordingType": "continuous", "Manufacturer": {"biosemi": "BioSemi", "brain_products": "Brain Products"}[hardware.platform],
        "EEGChannelCount": effective_types.count("eeg"), "EOGChannelCount": effective_types.count("eog"),
        "ECGChannelCount": effective_types.count("ecg"), "EMGChannelCount": effective_types.count("emg"),
        "TriggerChannelCount": effective_types.count("stim"),
        "FPVSHardwareEvidence": hardware.source, "FPVSOriginalExtension": source.suffix.lower(),
    }
    _json(folder / f"{stem}_eeg.json", metadata)
    events = [{"onset": repr(float(onset - raw.first_time)), "duration": repr(float(duration)),
               "trial_type": str(label), "value": "n/a", "sample": int(round((onset - raw.first_time) * raw.info["sfreq"]))}
              for onset, duration, label in zip(raw.annotations.onset, raw.annotations.duration, raw.annotations.description, strict=True)]
    if source.suffix.lower() == ".bdf":
        stim = str(settings.get("stim_channel") or "Status")
        if stim in raw.ch_names:
            values = raw.get_data(picks=[stim])[0].astype(np.int64)
            changes = np.flatnonzero(np.r_[True, np.diff(values) != 0] & (values != 0))
            events.extend({"onset": repr(int(sample) / raw.info["sfreq"]), "duration": "0",
                           "trial_type": f"Status/{int(values[sample])}", "value": int(values[sample]), "sample": int(sample)}
                          for sample in changes)
    events.sort(key=lambda item: (item["sample"], item["trial_type"]))
    _tsv(folder / f"{stem}_events.tsv", ("onset", "duration", "trial_type", "value", "sample"), events)
    _json(folder / f"{stem}_events.json", {
        "trial_type": {"Description": "Original annotation description or unmasked Status-channel value."},
        "value": {"Description": "Unmasked recorded Status value; n/a for source annotations."},
        "sample": {"Description": "Zero-based sample relative to recording start."},
    })
    return {"annotations": _annotation_identity(raw), "channel_names": raw.ch_names,
            "channel_types": effective_types, "original_units": units,
            "sfreq": float(raw.info["sfreq"]), "n_times": int(raw.n_times),
            "subject_info": _source_subject(raw),
            "digitization": [{"kind": int(point["kind"]), "ident": int(point["ident"]),
                              "coord_frame": int(point["coord_frame"]), "r": point["r"].tolist()}
                             for point in raw.info["dig"]] if raw.info["dig"] is not None else None,
            "bvrf_header": getattr(raw, "_fpvs_brain_products_header", None),
            "bvrf_marker_rows": getattr(raw, "_fpvs_brain_products_marker_rows", None),
            "channel_locations": [{"loc": [float(value) if np.isfinite(value) else None for value in ch["loc"]],
                                   "coord_frame": int(ch["coord_frame"])} for ch in raw.info["chs"]]}


def _valid_publication(folder: Path, identity: tuple[dict, ...], key: str) -> dict | None:
    try:
        manifest = json.loads((folder / "import.json").read_text(encoding="utf-8"))
        if (manifest["version"] != IMPORT_VERSION or manifest["key"] != key
                or manifest["source_identity"] != list(identity)
                or not {"subject_info", "digitization", "bvrf_header", "bvrf_marker_rows"}.issubset(manifest["recording"])):
            return None
        for row in manifest["outputs"]:
            path = _contained(folder / row["path"], folder.resolve())
            if not path.is_file() or path.stat().st_size != row["size"] or _digest(path) != row["sha256"]:
                return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _descriptor(folder: Path, manifest: dict, *, conversion_seconds: float, identity_seconds: float, reused: bool) -> BidsRecording:
    from mne_bids import BIDSPath

    root = folder / "dataset"
    if manifest["representation"] == "bvrf_fif64_derivative":
        root /= "derivatives/fpvs-import"
    bids_path = BIDSPath(root=root, subject=manifest["subject"], task="fpvs", datatype="eeg",
                         suffix="eeg", extension=manifest["extension"], check=manifest["extension"] != ".fif")
    return BidsRecording(bids_path, root, folder / "import.json", tuple(manifest["source_identity"]),
                         conversion_seconds, identity_seconds, reused, manifest["representation"])


def prepare_bids_recording(source: str | Path, *, project_root: str | Path, settings: Mapping | None = None) -> BidsRecording:
    """Publish or reuse a content-verified project-local import, without editing sources.

    Independent concurrent importers publish unique directories; their completed
    results are interchangeable. No importer removes another reader's files.
    ``conversion_seconds`` excludes source hashing and cache validation, which
    are reported separately as ``identity_seconds``.
    """
    import mne_bids
    from Main_App.projects.hardware import require_hardware_ready

    started = perf_counter()
    source = Path(source).resolve(strict=True)
    settings = dict(settings or {})
    require_hardware_ready(settings, paths=(source,))
    if source.suffix.lower() not in {".bdf", ".vhdr", ".bvrh"}:
        raise ValueError("BIDS import supports BDF, BrainVision .vhdr and BVRF .bvrh recordings.")
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("BIDS import requires an active project directory.")
    cache = _contained(root / ".fpvs_cache" / "bids-import", root)
    cache.mkdir(parents=True, exist_ok=True)
    identity = _source_identity(source)
    key_payload = {"version": IMPORT_VERSION, "sources": identity,
                   "settings": {name: settings[name] for name in _SETTING_KEYS if name in settings},
                   "mne": mne.__version__, "mne_bids": mne_bids.__version__}
    key = hashlib.sha256(json.dumps(key_payload, sort_keys=True).encode()).hexdigest()
    for existing in sorted(cache.glob(f"{key[:24]}-*")):
        _contained(existing, root)
        manifest = _valid_publication(existing, identity, key)
        if manifest is not None:
            return _descriptor(existing, manifest, conversion_seconds=0.0,
                               identity_seconds=perf_counter() - started, reused=True)
    identity_seconds = perf_counter() - started
    conversion_started = perf_counter()
    subject = "fpvs" + key[:16]
    suffix = source.suffix.lower()
    representation = "bvrf_fif64_derivative" if suffix == ".bvrh" else "raw_eeg_bids"
    extension = ".fif" if suffix == ".bvrh" else suffix
    final = _contained(cache / f"{key[:24]}-{uuid.uuid4().hex[:8]}", root)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=cache) as temporary:
        staging = Path(temporary)
        dataset = staging / "dataset"
        dataset.mkdir()
        _json(dataset / "dataset_description.json", {"Name": "FPVS Toolbox recording import", "BIDSVersion": "1.9.0", "DatasetType": "raw"})
        raw_root = dataset
        if suffix == ".bvrh":
            raw_root = dataset / "derivatives" / "fpvs-import"
            raw_root.mkdir(parents=True)
            _json(raw_root / "dataset_description.json", {
                "Name": "FPVS lossless BVRF import", "BIDSVersion": "1.9.0", "DatasetType": "derivative",
                "GeneratedBy": [{"Name": "FPVS Toolbox", "Version": IMPORT_VERSION,
                                 "Description": "FIF64 preserves calibrated BVRF values; not a standard raw EEG-BIDS recording."}],
            })
            original = dataset / "sourcedata" / subject
            original.mkdir(parents=True)
            for row in identity:
                file = Path(row["path"])
                # BVRF companion names are required to share the original stem.
                shutil.copyfile(file, original / file.name)
        target = raw_root / f"sub-{subject}" / "eeg" / f"sub-{subject}_task-fpvs_eeg{extension}"
        target.parent.mkdir(parents=True)
        if suffix == ".bdf":
            raw = mne.io.read_raw_bdf(source, preload=False, stim_channel=str(settings.get("stim_channel") or "Status"), verbose=False)
        else:
            from Main_App.io.brain_products import read_brain_products_raw
            raw = read_brain_products_raw(source, preload=False, synthesize_status=False)
        try:
            metadata = _metadata(raw, target, settings, source=source)
            if suffix == ".bdf":
                shutil.copyfile(source, target)
            elif suffix == ".vhdr":
                _copy_brainvision(source, target)
            else:
                raw.save(target, fmt="double", overwrite=False, verbose=False)
            _tsv(raw_root / "participants.tsv", ("participant_id",), [{"participant_id": f"sub-{subject}"}])
        finally:
            raw.close()
        verification_started = perf_counter()
        if _source_identity(source) != identity:
            raise OSError("Source recording changed during BIDS import; no cache was published.")
        outputs = [{"path": str(file.relative_to(staging).as_posix()), "size": file.stat().st_size, "sha256": _digest(file)}
                   for file in sorted(staging.rglob("*")) if file.is_file()]
        verification_seconds = perf_counter() - verification_started
        manifest = {"version": IMPORT_VERSION, "key": key, "source_identity": list(identity),
                    "subject": subject, "extension": extension, "representation": representation,
                    "outputs": outputs, "recording": metadata}
        _json(staging / "import.json", manifest)
        os.rename(staging, final)
    elapsed = perf_counter() - conversion_started - verification_seconds
    identity_seconds += verification_seconds
    logger.info("BIDS import published source=%s representation=%s conversion_seconds=%.6f identity_seconds=%.6f",
                source.name, representation, elapsed, identity_seconds)
    return _descriptor(final, manifest, conversion_seconds=elapsed, identity_seconds=identity_seconds, reused=False)


def read_bids_recording(recording: BidsRecording, *, preload: bool | str = False,
                        extra_params: Mapping | None = None, stim_channel: str = "Status") -> mne.io.BaseRaw:
    """Read normalized storage and preserve original annotations/precision.

    BrainVision's canonical Status view is created here, before processing.
    Native annotation descriptions remain authoritative; events.tsv never
    silently changes the legacy pipeline's annotation rejection behavior.
    """
    from mne_bids import read_raw_bids

    manifest = json.loads(recording.manifest_path.read_text(encoding="utf-8"))
    metadata = manifest["recording"]
    params = dict(extra_params or {})
    include = params.pop("include", None)
    source_suffix = Path(recording.source_identity[0]["path"]).suffix.lower()
    if not isinstance(preload, (bool, str)):
        raise TypeError("preload must be False, True, or a new memory-map filename.")
    if isinstance(preload, str):
        target = Path(preload)
        if target.exists():
            raise FileExistsError("BIDS preload must use a new, non-source memory-map file.")
        if not target.parent.is_dir():
            raise FileNotFoundError("The memory-map parent directory does not exist.")
    # Select the requested subset while lazy; selecting an already loaded map
    # would allocate a second in-memory array and lose the disk-preload contract.
    if recording.representation == "bvrf_fif64_derivative":
        raw = mne.io.read_raw_fif(recording.header_path, preload=False, verbose=False)
    else:
        params["preload"] = False
        if source_suffix != ".bdf":
            params.pop("stim_channel", None)
        raw = read_raw_bids(recording.bids_path, extra_params=params, verbose=False)
    owns_preload = False
    try:
        if raw.ch_names != metadata["channel_names"] or raw.n_times != metadata["n_times"] or raw.info["sfreq"] != metadata["sfreq"]:
            raise ValueError("Imported recording does not match its validated channel/sample identity.")
        raw.set_channel_types(dict(zip(raw.ch_names, metadata["channel_types"], strict=True)), verbose=False)
        subject = metadata["subject_info"]
        if subject is not None:
            subject = dict(subject)
            if isinstance(subject.get("birthday"), str):
                subject["birthday"] = date.fromisoformat(subject["birthday"])
        raw.info["subject_info"] = subject
        from mne._fiff._digitization import DigPoint
        with raw.info._unlock():
            raw.info["dig"] = ([DigPoint({**point, "r": np.asarray(point["r"], dtype=float)})
                                for point in metadata["digitization"]]
                               if metadata["digitization"] is not None else None)
        for channel, location in zip(raw.info["chs"], metadata["channel_locations"], strict=True):
            channel["loc"][:] = [np.nan if value is None else value for value in location["loc"]]
            channel["coord_frame"] = location["coord_frame"]
        annotations = dict(metadata["annotations"])
        if annotations["orig_time"] is not None:
            annotations["orig_time"] = datetime.fromisoformat(annotations["orig_time"])
        raw.set_annotations(mne.Annotations(**annotations))
        raw._orig_units = dict(metadata["original_units"])
        if metadata["bvrf_header"] is not None:
            raw._fpvs_brain_products_header = metadata["bvrf_header"]
            raw._fpvs_brain_products_marker_rows = tuple(metadata["bvrf_marker_rows"])
        if source_suffix in {".vhdr", ".bvrh"}:
            from Main_App.io.brain_products import _RawWithStatus, _require_continuous_source, decode_brain_products_events
            _require_continuous_source(raw, Path(recording.source_identity[0]["path"]))
            events = decode_brain_products_events(raw)
            if isinstance(preload, str):
                os.close(os.open(preload, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600))
                owns_preload = True
            raw = _RawWithStatus(raw, events, stim_channel, preload)
            raw._fpvs_brain_products_source_files = tuple(row["path"] for row in recording.source_identity)
        if include is not None:
            raw.pick([name for name in raw.ch_names if name in include])
        if source_suffix == ".bdf" and preload is not False:
            if isinstance(preload, str):
                os.close(os.open(preload, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600))
                owns_preload = True
            raw._preload_data(preload)
        raw._fpvs_bids_import = {"version": IMPORT_VERSION, "representation": recording.representation,
                                "path": str(recording.header_path), "conversion_seconds": recording.conversion_seconds,
                                "identity_seconds": recording.identity_seconds, "reused": recording.reused}
        return raw
    except BaseException as exc:
        from Main_App.io.brain_products import close_brain_products_raw
        traceback.clear_frames(exc.__traceback__)
        close_brain_products_raw(raw)
        if owns_preload:
            Path(preload).unlink(missing_ok=True)
        raise

"""Project-local BIDS import boundary, without scientific preprocessing.

BDF sample bytes are preserved; reviewed mobile unit headers may be corrected
with the original retained in sourcedata. BrainVision signal bytes are copied and
only companion links change. BVRF has no standard raw EEG-BIDS representation
that preserves arbitrary calibrated float64 samples, so it uses an explicitly
labeled FIF64 derivative. That exception is never advertised as raw EEG-BIDS.
"""
from __future__ import annotations

import csv
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
from time import perf_counter
import traceback
from types import SimpleNamespace
from typing import Any, Mapping
import uuid

import mne
import numpy as np

from Main_App.io.atomic_write import rename_with_retry
from Main_App.io.recording_sources import recording_content_identity, source_hashes_by_file
from Main_App.io.safe_file import regular_file_info

logger = logging.getLogger(__name__)
IMPORT_VERSION = "bids_import_v1"
_BIDS_TYPES = {"eeg": "EEG", "eog": "EOG", "ecg": "ECG", "emg": "EMG", "stim": "TRIG"}
_SETTING_KEYS = ("hardware_platform", "hardware_confirmed", "hardware_selection_source",
                 "channel_types", "electrode_montage", "electrode_mapping_profile", "stim_channel",
                 "acquisition_profile", "recording_event_policy")


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
    import_key: str = ""
    studio_source_sha256_by_file: dict[str, str] | None = None

    @property
    def header_path(self) -> Path:
        return Path(self.bids_path.fpath)


def _json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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


def _copy_brainvision(identity: tuple[dict, ...], target: Path) -> None:
    """Repair declared links without assuming companions share a basename."""
    header, data, markers = (Path(row["path"]) for row in identity)
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


def _nonzero_status_transition_indices(values: np.ndarray) -> np.ndarray:
    # Equality of adjacent integer values is equivalent to zero difference,
    # including integer wraparound. Fill one reusable boolean mask directly.
    transitions = np.empty(values.shape, dtype=bool)
    transitions[:1] = True
    np.not_equal(values[1:], values[:-1], out=transitions[1:])
    np.logical_and(transitions, values, out=transitions)
    return np.flatnonzero(transitions)


def _metadata(raw: mne.io.BaseRaw, target: Path, settings: Mapping, *, source: Path,
              import_key: str = "") -> dict:
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
    if hardware.platform == "biosemi_active_three":
        roles = {**{name: "misc" for name in raw.ch_names if re.fullmatch(r"EXG\d+", name, re.IGNORECASE)}, **roles}
    effective_types = [roles.get(name, kind) for name, kind in zip(raw.ch_names, types, strict=True)]
    rows = [{"name": name, "type": _BIDS_TYPES.get(kind, "MISC"),
             "units": units.get(name) or "n/a", "status": "bad" if name in raw.info["bads"] else "good"}
            for name, kind in zip(raw.ch_names, effective_types, strict=True)]
    _tsv(folder / f"{stem}_channels.tsv", ("name", "type", "units", "status"), rows)
    metadata = {
        "TaskName": "FPVS", "SamplingFrequency": raw.info["sfreq"],
        "EEGReference": "CMS" if hardware.platform in {"biosemi", "biosemi_active_three"} else "n/a",
        "PowerLineFrequency": raw.info.get("line_freq") or "n/a", "SoftwareFilters": "n/a",
        "HardwareFilters": "n/a", "RecordingDuration": raw.n_times / raw.info["sfreq"],
        "RecordingType": "continuous", "Manufacturer": {
            "biosemi": "BioSemi", "biosemi_active_three": "BioSemi", "brain_products": "Brain Products", "unicorn": "g.tec",
        }[hardware.platform],
        "EEGChannelCount": effective_types.count("eeg"), "EOGChannelCount": effective_types.count("eog"),
        "ECGChannelCount": effective_types.count("ecg"), "EMGChannelCount": effective_types.count("emg"),
        "TriggerChannelCount": effective_types.count("stim"),
        "FPVSHardwareEvidence": hardware.source, "FPVSOriginalExtension": source.suffix.lower(),
    }
    _json(folder / f"{stem}_eeg.json", metadata)
    events = [{"onset": repr(float(onset - raw.first_time)), "duration": repr(float(duration)),
               "trial_type": str(label), "value": "n/a", "sample": int(round((onset - raw.first_time) * raw.info["sfreq"]))}
              for onset, duration, label in zip(raw.annotations.onset, raw.annotations.duration, raw.annotations.description, strict=True)]
    from Main_App.io.pipeline_events import canonical_recording_events, snapshot_canonical_event_metadata
    canonical = canonical_recording_events(raw)
    if canonical is not None:
        events.extend({"onset": repr(int(sample) / raw.info["sfreq"]), "duration": "0",
                       "trial_type": f"Event/{int(code)}", "value": int(code), "sample": int(sample)}
                      for sample, _, code in canonical)
    elif source.suffix.lower() == ".bdf":
        stim = str(settings.get("stim_channel") or "Status")
        if stim in raw.ch_names:
            from Main_App.io.recording_access import owned_recording_lazy_read

            with owned_recording_lazy_read(raw, stim_channel=stim, status_only=True,
                                           require_bounded_status=settings.get("_fpvs_preflight_bounded_status") is True):
                values = raw.get_data(picks=[stim])[0].astype(np.int64)
            changes = _nonzero_status_transition_indices(values)
            events.extend({"onset": repr(int(sample) / raw.info["sfreq"]), "duration": "0",
                           "trial_type": f"Status/{int(values[sample])}", "value": int(values[sample]), "sample": int(sample)}
                          for sample in changes)
            del values, changes
    events.sort(key=lambda item: (item["sample"], item["trial_type"]))
    _tsv(folder / f"{stem}_events.tsv", ("onset", "duration", "trial_type", "value", "sample"), events)
    _json(folder / f"{stem}_events.json", {
        "trial_type": {"Description": "Original annotation description or explicitly decoded canonical event." if canonical is not None else "Original annotation description or unmasked Status-channel value."},
        "value": {"Description": "Canonical code under the declared event policy; n/a for original annotation rows." if canonical is not None else "Unmasked recorded Status value; n/a for source annotations."},
        "sample": {"Description": "Zero-based sample relative to recording start."},
    })
    result = {"annotations": _annotation_identity(raw), "channel_names": raw.ch_names,
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
    if canonical is not None:
        evidence = snapshot_canonical_event_metadata(raw, cache_key=import_key)
        result["canonical_events"] = canonical.tolist()
        result["canonical_events_sfreq"] = float(raw.info["sfreq"])
        result["canonical_events_first_samp"] = int(raw.first_samp)
        result["canonical_events_schema_version"] = evidence["schema_version"]
        result["canonical_events_sha256"] = evidence["sha256"]
        result["mobile_import"] = raw._fpvs_mobile_import
    return result


def _restore_import_events(raw: Any, metadata: Mapping, *, import_key: str) -> np.ndarray:
    """Validate original serialized values before any integer coercion or use."""
    from Main_App.io.pipeline_events import canonical_recording_events, restore_canonical_event_metadata

    evidence = {
        "schema_version": metadata["canonical_events_schema_version"],
        "sfreq": metadata["canonical_events_sfreq"],
        "first_samp": metadata["canonical_events_first_samp"],
        "n_times": metadata["n_times"], "events": metadata["canonical_events"],
        "sha256": metadata["canonical_events_sha256"],
    }
    restore_canonical_event_metadata(raw, evidence, cache_key=import_key)
    return canonical_recording_events(raw)


def _publication_layout(source: Path, key: str) -> tuple[str, str, str, Path]:
    subject = "fpvs" + key[:16]
    if source.suffix.lower() == ".bvrh":
        return subject, "bvrf_fif64_derivative", ".fif", Path("dataset/derivatives/fpvs-import")
    return subject, "raw_eeg_bids", source.suffix.lower(), Path("dataset")


def _required_output_paths(
    identity: tuple[dict, ...], layout: tuple[str, str, str, Path], *, mobile: bool,
) -> set[str]:
    subject, _, extension, raw_root = layout
    stem = f"sub-{subject}_task-fpvs"
    eeg = raw_root / f"sub-{subject}" / "eeg"
    paths = {Path("dataset/dataset_description.json"), raw_root / "dataset_description.json",
             raw_root / "participants.tsv", eeg / f"{stem}_eeg{extension}"}
    paths.update(eeg / f"{stem}_{name}" for name in ("eeg.json", "channels.tsv", "events.tsv", "events.json"))
    if extension == ".vhdr":
        paths.update(eeg / f"{stem}_eeg{ext}" for ext in (".eeg", ".vmrk"))
    if mobile or extension == ".fif":
        paths.update(Path("dataset/sourcedata") / subject / Path(row["path"]).name for row in identity)
    return {path.as_posix() for path in paths}


def _verified_outputs(folder: Path, rows: list, required: set[str]) -> bool:
    """Match the receipt to every physical member, including optional FIF splits."""
    if not isinstance(rows, list):
        return False
    remaining = {row["path"]: row for row in rows}
    if len(remaining) != len(rows) or not required.issubset(remaining):
        return False
    directories = [folder]
    while directories:
        with os.scandir(directories.pop()) as entries:
            for entry in entries:
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    return False
                path = Path(entry.path)
                if stat.S_ISDIR(info.st_mode):
                    directories.append(path)
                    continue
                if not stat.S_ISREG(info.st_mode):
                    return False
                name = path.relative_to(folder).as_posix()
                if name == "import.json":
                    continue
                row = remaining.pop(name, None)
                if row is None or info.st_size != row["size"] or _digest(path) != row["sha256"]:
                    return False
    return not remaining


def _valid_publication(folder: Path, identity: tuple[dict, ...], key: str, *, mobile: bool = False) -> dict | None:
    try:
        receipt = folder / "import.json"
        if regular_file_info(receipt) is None:
            return None
        manifest = json.loads(receipt.read_text(encoding="utf-8"))
        if (manifest["version"] != IMPORT_VERSION or manifest["key"] != key
                or manifest["source_identity"] != list(identity)
                or not isinstance(manifest["recording"], dict)
                or not {"subject_info", "digitization", "bvrf_header", "bvrf_marker_rows"}.issubset(manifest["recording"])):
            return None
        metadata = manifest["recording"]
        if "mobile_import" in metadata or any(name.startswith("canonical_events") for name in metadata):
            probe = SimpleNamespace(
                info={"sfreq": metadata["sfreq"]}, n_times=metadata["n_times"],
                first_samp=metadata["canonical_events_first_samp"],
            )
            _restore_import_events(probe, metadata, import_key=key)
        if not identity:
            return None
        layout = _publication_layout(Path(identity[0]["path"]), key)
        if (manifest["subject"], manifest["representation"], manifest["extension"]) != layout[:3]:
            return None
        if not _verified_outputs(folder, manifest["outputs"], _required_output_paths(identity, layout, mobile=mobile)):
            return None
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _descriptor(folder: Path, manifest: dict, *, conversion_seconds: float, identity_seconds: float,
                reused: bool, studio_source_hashes: dict[str, str] | None = None) -> BidsRecording:
    from mne_bids import BIDSPath

    root = folder / "dataset"
    if manifest["representation"] == "bvrf_fif64_derivative":
        root /= "derivatives/fpvs-import"
    bids_path = BIDSPath(root=root, subject=manifest["subject"], task="fpvs", datatype="eeg",
                         suffix="eeg", extension=manifest["extension"], check=manifest["extension"] != ".fif")
    return BidsRecording(bids_path, root, folder / "import.json", tuple(manifest["source_identity"]),
                         conversion_seconds, identity_seconds, reused, manifest["representation"], manifest["key"],
                         studio_source_hashes)


def prepare_bids_recording(
    source: str | Path, *, project_root: str | Path, settings: Mapping | None = None,
    temporary_imports: ExitStack | None = None,
) -> BidsRecording:
    """Publish or reuse a content-verified project-local import, without editing sources.

    Independent concurrent importers publish unique directories; their completed
    results are interchangeable. No importer removes another reader's files.
    ``conversion_seconds`` excludes source hashing and cache validation, which
    are reported separately as ``identity_seconds``.
    With retention disabled, the caller owns the temporary import until its
    final sample read.
    """
    import mne_bids
    from Main_App.projects.hardware import require_hardware_ready

    started = perf_counter()
    selected = Path(source)
    source = selected.resolve(strict=True)
    if selected.suffix.lower() in {".vhdr", ".bvrh"} and not source.is_relative_to(selected.parent.resolve()):
        raise ValueError("Brain Products files must remain inside the recording folder.")
    settings = dict(settings or {})
    hardware = require_hardware_ready(settings, paths=(source,))
    if source.suffix.lower() not in {".bdf", ".vhdr", ".bvrh"}:
        raise ValueError("BIDS import supports BDF, BrainVision .vhdr and BVRF .bvrh recordings.")
    root = Path(project_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("BIDS import requires an active project directory.")
    retain = settings.get("enable_bids_import_cache", True) is not False
    if retain:
        publication_root = root
        cache = _contained(root / ".fpvs_cache" / "bids-import", root)
        cache.mkdir(parents=True, exist_ok=True)
    else:
        if temporary_imports is None:
            raise ValueError("A temporary BIDS import requires a recording lifetime owner.")
        from Main_App.io.memmap_paths import process_memmap_directory

        publication_root = process_memmap_directory()
        temporary = temporary_imports.enter_context(
            tempfile.TemporaryDirectory(prefix="bids-", dir=publication_root),
        )
        cache = _contained(Path(temporary), publication_root)
    identity = recording_content_identity(source)
    studio_source_hashes = None
    if source.suffix.lower() in {".vhdr", ".bvrh"}:
        from Main_App.projects.studio_recording_identity import (
            STUDIO_SOURCE_APPROVALS_KEY, read_project_studio_source_approvals, studio_source_approval,
        )

        approvals = settings.get(STUDIO_SOURCE_APPROVALS_KEY)
        if approvals is None:
            approvals = read_project_studio_source_approvals(root)
        approved = studio_source_approval(approvals, selected)
        if approved is not None:
            studio_source_hashes = source_hashes_by_file(identity)
            if studio_source_hashes != approved:
                raise ValueError("The recording differs from its Studio approval. Review the cohort again.")
    key_payload = {"version": IMPORT_VERSION, "sources": identity,
                   "settings": {name: settings[name] for name in _SETTING_KEYS if name in settings},
                   "mne": mne.__version__, "mne_bids": mne_bids.__version__}
    key = hashlib.sha256(json.dumps(key_payload, sort_keys=True).encode()).hexdigest()
    if retain:
        for existing in sorted(cache.glob(f"{key[:24]}-*")):
            _contained(existing, root)
            manifest = _valid_publication(existing, identity, key, mobile=hardware == "unicorn")
            if manifest is not None:
                return _descriptor(existing, manifest, conversion_seconds=0.0,
                                   identity_seconds=perf_counter() - started, reused=True, studio_source_hashes=studio_source_hashes)
    identity_seconds = perf_counter() - started
    conversion_started = perf_counter()
    suffix = source.suffix.lower()
    subject, representation, extension, relative_root = _publication_layout(source, key)
    final = _contained(cache / f"{key[:24]}-{uuid.uuid4().hex[:8]}", publication_root)
    with tempfile.TemporaryDirectory(prefix=".import-", dir=cache) as temporary:
        staging = Path(temporary)
        dataset = staging / "dataset"
        dataset.mkdir()
        _json(dataset / "dataset_description.json", {"Name": "FPVS Toolbox recording import", "BIDSVersion": "1.9.0", "DatasetType": "raw"})
        raw_root = staging / relative_root
        if suffix == ".bvrh":
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
        with ExitStack() as owners:
            if hardware == "unicorn":
                from Main_App.io.mobile_eeg import open_mobile_import_source
                raw = owners.enter_context(open_mobile_import_source(source, settings, project_root=root))
            elif suffix == ".bdf":
                raw = mne.io.read_raw_bdf(source, preload=False, stim_channel=str(settings.get("stim_channel") or "Status"), verbose=False)
                owners.callback(raw.close)
            else:
                from Main_App.io.brain_products import read_brain_products_raw
                if suffix == ".vhdr":
                    _copy_brainvision(identity, target)
                raw = read_brain_products_raw(target if suffix == ".vhdr" else source,
                                              preload=False, synthesize_status=False)
                owners.callback(raw.close)
            metadata = _metadata(raw, target, settings, source=source, import_key=key)
            if suffix == ".bdf":
                if hardware == "unicorn":
                    # Only reviewed physical-dimension header fields changed;
                    # packed samples stay exact and the original stays available.
                    shutil.copyfile(raw.filenames[0], target)
                    original = dataset / "sourcedata" / subject
                    original.mkdir(parents=True)
                    shutil.copyfile(source, original / source.name)
                else:
                    shutil.copyfile(source, target)
            elif suffix == ".bvrh":
                raw.save(target, fmt="double", overwrite=False, verbose=False)
            _tsv(raw_root / "participants.tsv", ("participant_id",), [{"participant_id": f"sub-{subject}"}])
        verification_started = perf_counter()
        if recording_content_identity(source) != identity:
            raise OSError("Source recording changed during BIDS import; no cache was published.")
        outputs = [{"path": str(file.relative_to(staging).as_posix()), "size": file.stat().st_size, "sha256": _digest(file)}
                   for file in sorted(staging.rglob("*")) if file.is_file()]
        verification_seconds = perf_counter() - verification_started
        manifest = {"version": IMPORT_VERSION, "key": key, "source_identity": list(identity),
                    "subject": subject, "extension": extension, "representation": representation,
                    "outputs": outputs, "recording": metadata}
        _json(staging / "import.json", manifest)
        rename_with_retry(staging, final)
    elapsed = perf_counter() - conversion_started - verification_seconds
    identity_seconds += verification_seconds
    logger.info("BIDS import published source=%s representation=%s conversion_seconds=%.6f identity_seconds=%.6f",
                source.name, representation, elapsed, identity_seconds)
    return _descriptor(final, manifest, conversion_seconds=elapsed, identity_seconds=identity_seconds,
                       reused=False, studio_source_hashes=studio_source_hashes)


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
            from Main_App.io.brain_products_files import source_files

            header = recording.header_path
            if source_files(header, native_paths=True) != (header, header.with_suffix(".eeg"), header.with_suffix(".vmrk")):
                raise ValueError("Imported BrainVision companions differ from the verified BIDS inventory.")
        elif "mobile_import" in metadata or "canonical_events" in metadata:
            params["stim_channel"] = [name for name, kind in zip(metadata["channel_names"], metadata["channel_types"], strict=True) if kind == "stim"] or None
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
        if "mobile_import" in metadata or "canonical_events" in metadata:
            events = _restore_import_events(raw, metadata, import_key=manifest["key"])
            present_stim = [name for name, kind in zip(raw.ch_names, raw.get_channel_types(), strict=True) if kind == "stim"]
            if present_stim and present_stim != [stim_channel]:
                if len(present_stim) != 1 or stim_channel in raw.ch_names:
                    raise ValueError("Ambiguous recorded stimulus channel identity.")
                raw.rename_channels({present_stim[0]: stim_channel})
            if stim_channel not in raw.ch_names:
                from Main_App.io.brain_products import _RawWithStatus
                raw = _RawWithStatus(raw, events, stim_channel, False)
            raw._fpvs_canonical_events = events
            raw._fpvs_canonical_events_sfreq = metadata["canonical_events_sfreq"]
            raw._fpvs_mobile_import = metadata["mobile_import"]
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

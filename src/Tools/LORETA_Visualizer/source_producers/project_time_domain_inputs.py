"""Validate and lazily load project source-ready time-domain derivatives.

The adapter is intentionally read-only.  Main App processing owns derivative
publication; source producers consume only participant commit manifests that
prove every requested participant/condition artifact was published.  Missing
or invalid derivatives never fall back to amplitude workbooks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import numpy as np

from config import DEFAULT_ELECTRODE_NAMES_64

PROJECT_SOURCE_LOCALIZATION_FOLDER = "6 - Source Localization"
PROJECT_TIME_DOMAIN_INPUT_FOLDER = "Source-Ready Time Domain v1"
PROJECT_TIME_DOMAIN_MANIFESTS_FOLDER = "manifests"

SOURCE_TIME_DOMAIN_SIDECAR_FORMAT = "fpvs-source-ready-time-domain-v1"
SOURCE_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT = (
    "fpvs-source-ready-time-domain-participant-manifest-v1"
)
SOURCE_TIME_DOMAIN_CROP_MODE = "55_onbin"
SOURCE_TIME_DOMAIN_AGGREGATION_DOMAIN = "time"
SOURCE_TIME_DOMAIN_AGGREGATION_METHOD = "arithmetic_mean"
SOURCE_TIME_DOMAIN_DATA_UNIT = "V"

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_CONDITION_ID_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*$")
_FLOAT_REL_TOL = 1e-9
_FLOAT_ABS_TOL = 1e-12


class ProjectTimeDomainInputError(RuntimeError):
    """Raised when project time-domain inputs are incomplete or incompatible."""


@dataclass(frozen=True)
class ExpectedProjectTimeDomainInput:
    """One canonical participant/condition input required by orchestration."""

    participant_id: str
    condition_id: str
    group_id: str | None = None
    condition_label: str | None = None
    group_folder: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "participant_id", _identity(self.participant_id, "participant_id"))
        object.__setattr__(self, "condition_id", _condition_id(self.condition_id))
        object.__setattr__(self, "group_id", _optional_identity(self.group_id, "group_id"))
        object.__setattr__(self, "condition_label", _optional_label(self.condition_label, "condition_label"))
        object.__setattr__(self, "group_folder", _optional_component(self.group_folder, "group_folder"))

    @property
    def key(self) -> tuple[str | None, str, str]:
        """Return the strict group/participant/condition identity key."""

        return (self.group_id, self.participant_id, self.condition_id)


@dataclass(frozen=True)
class ProjectTimeDomainInputRecord:
    """Validated metadata and paths for one participant/condition derivative."""

    participant_id: str
    condition_id: str
    condition_label: str
    group_id: str | None
    group_folder: str | None
    condition_folder: str
    manifest_path: Path
    fif_path: Path
    sidecar_path: Path
    fif_sha256: str
    sidecar_sha256: str
    processing_fingerprint: str
    processing_fingerprint_version: str
    sfreq_hz: float
    n_times: int
    duration_sec: float
    frequency_resolution_hz: float
    n_step: int
    n_mod_step: int
    repetition_count: int
    channel_names: tuple[str, ...]
    channel_types: tuple[str, ...]
    channel_units: tuple[str, ...]
    bad_channels: tuple[str, ...]
    reference_signature: tuple[object, ...]
    sidecar: Mapping[str, Any]

    @property
    def key(self) -> tuple[str | None, str, str]:
        """Return the strict group/participant/condition identity key."""

        return (self.group_id, self.participant_id, self.condition_id)


@dataclass(frozen=True)
class LoadedProjectTimeDomainRaw:
    """One validated record with its currently open, preloaded MNE Raw."""

    record: ProjectTimeDomainInputRecord
    raw: Any


@dataclass(frozen=True)
class ProjectTimeDomainInputSet:
    """Complete canonical project input set for one source-producer run."""

    project_root: Path
    input_root: Path
    records: tuple[ProjectTimeDomainInputRecord, ...]
    processing_fingerprint: str
    processing_fingerprint_version: str
    sfreq_hz: float
    n_times: int
    frequency_resolution_hz: float

    def iter_loaded_raws(self) -> Iterator[LoadedProjectTimeDomainRaw]:
        """Yield one preloaded Raw at a time and close it before loading the next."""

        for record in self.records:
            raw = _read_and_validate_raw(record, preload=True, require_finite=True)
            try:
                yield LoadedProjectTimeDomainRaw(record=record, raw=raw)
            finally:
                close = getattr(raw, "close", None)
                if callable(close):
                    close()


def default_project_time_domain_input_dir(project_root: str | Path) -> Path:
    """Return the canonical project-local source-ready derivative directory."""

    root = _project_root(project_root)
    return root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_TIME_DOMAIN_INPUT_FOLDER


def load_project_time_domain_inputs(
    project_root: str | Path,
    *,
    expected_inputs: Sequence[ExpectedProjectTimeDomainInput],
    expected_processing_fingerprint: str,
    expected_processing_fingerprint_version: str,
) -> ProjectTimeDomainInputSet:
    """Validate and return an exact enabled participant/condition input set.

    ``expected_inputs`` is mandatory so project discovery can never silently
    choose participants or conditions.  Extra committed derivatives may exist,
    but only the canonical requested keys are loaded.  Every requested key must
    resolve exactly once.
    """

    root = _project_root(project_root)
    input_root = root / PROJECT_SOURCE_LOCALIZATION_FOLDER / PROJECT_TIME_DOMAIN_INPUT_FOLDER
    manifests_root = input_root / PROJECT_TIME_DOMAIN_MANIFESTS_FOLDER
    expected = tuple(expected_inputs)
    if not expected:
        raise ProjectTimeDomainInputError(
            "Source-ready time-domain loading requires an explicit non-empty canonical "
            "participant/condition set."
        )
    expected_fingerprint = _identity(expected_processing_fingerprint, "expected_processing_fingerprint")
    expected_fingerprint_version = _identity(
        expected_processing_fingerprint_version,
        "expected_processing_fingerprint_version",
    )
    expected_by_key: dict[tuple[str | None, str, str], ExpectedProjectTimeDomainInput] = {}
    for item in expected:
        if not isinstance(item, ExpectedProjectTimeDomainInput):
            raise TypeError("expected_inputs must contain ExpectedProjectTimeDomainInput values.")
        if item.key in expected_by_key:
            raise ProjectTimeDomainInputError(f"Duplicate expected source-ready input: {_format_key(item.key)}.")
        expected_by_key[item.key] = item

    if not manifests_root.is_dir():
        raise ProjectTimeDomainInputError(_missing_derivative_message(manifests_root))

    expected_participants = {(item.group_id, item.participant_id) for item in expected}
    participant_manifests: dict[tuple[str | None, str], tuple[Path, Mapping[str, Any], str | None]] = {}
    for manifest_path in sorted(manifests_root.rglob("*.json"), key=lambda path: str(path).casefold()):
        safe_manifest = _require_existing_project_file(
            root,
            manifest_path,
            allowed_root=manifests_root,
            label="participant commit manifest",
        )
        raw_manifest = _read_json_object(safe_manifest, label="participant commit manifest")
        participant_id = _identity(raw_manifest.get("participant_id"), "manifest participant_id")
        group_id = _optional_identity(raw_manifest.get("group_id"), "manifest group_id")
        participant_key = (group_id, participant_id)
        if participant_key not in expected_participants:
            continue
        if participant_key in participant_manifests:
            prior = participant_manifests[participant_key][0]
            raise ProjectTimeDomainInputError(
                f"Multiple participant commit manifests match {participant_key}: {prior} and {safe_manifest}."
            )
        group_folder = _validate_manifest_location(
            safe_manifest,
            manifests_root=manifests_root,
            participant_id=participant_id,
            declared_group_folder=raw_manifest.get("group_folder"),
            grouped=group_id is not None,
        )
        participant_manifests[participant_key] = (safe_manifest, raw_manifest, group_folder)

    missing_participants = sorted(expected_participants - set(participant_manifests), key=str)
    if missing_participants:
        missing_text = ", ".join(_format_participant_key(key) for key in missing_participants)
        raise ProjectTimeDomainInputError(
            "Source-ready participant commit manifests are missing for: "
            f"{missing_text}. Reprocess those participants; amplitude workbooks are not a fallback."
        )

    records_by_key: dict[tuple[str | None, str, str], ProjectTimeDomainInputRecord] = {}
    for participant_key, (manifest_path, manifest, group_folder) in participant_manifests.items():
        _validate_format(
            manifest,
            expected=SOURCE_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT,
            label=f"participant commit manifest {manifest_path}",
        )
        if manifest.get("complete") is not True:
            raise ProjectTimeDomainInputError(
                f"Participant commit manifest is not complete and cannot be used: {manifest_path}."
            )
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ProjectTimeDomainInputError(f"Participant commit manifest has no artifacts: {manifest_path}.")
        seen_condition_ids: set[str] = set()
        for artifact_index, artifact_value in enumerate(artifacts):
            if not isinstance(artifact_value, Mapping):
                raise ProjectTimeDomainInputError(
                    f"Artifact {artifact_index} in {manifest_path} must be a JSON object."
                )
            condition_id = _condition_id(artifact_value.get("condition_id"))
            if condition_id in seen_condition_ids:
                raise ProjectTimeDomainInputError(
                    f"Participant commit manifest has duplicate condition_id {condition_id!r}: {manifest_path}."
                )
            seen_condition_ids.add(condition_id)
            key = (participant_key[0], participant_key[1], condition_id)
            expected_item = expected_by_key.get(key)
            if expected_item is None:
                continue
            record = _validate_artifact(
                root=root,
                input_root=input_root,
                manifest_path=manifest_path,
                group_folder=group_folder,
                artifact=artifact_value,
                expected=expected_item,
                expected_processing_fingerprint=expected_fingerprint,
                expected_processing_fingerprint_version=expected_fingerprint_version,
            )
            if key in records_by_key:
                raise ProjectTimeDomainInputError(f"Multiple artifacts match expected input {_format_key(key)}.")
            records_by_key[key] = record

    missing_keys = [item.key for item in expected if item.key not in records_by_key]
    if missing_keys:
        missing_text = ", ".join(_format_key(key) for key in missing_keys)
        raise ProjectTimeDomainInputError(
            "Source-ready time-domain derivatives are incomplete for: "
            f"{missing_text}. Reprocess the missing inputs; amplitude workbooks are not a fallback."
        )

    records = tuple(records_by_key[item.key] for item in expected)
    _validate_record_compatibility(records)
    for record in records:
        raw = _read_and_validate_raw(record, preload=False, require_finite=False)
        close = getattr(raw, "close", None)
        if callable(close):
            close()
    first = records[0]
    return ProjectTimeDomainInputSet(
        project_root=root,
        input_root=input_root,
        records=records,
        processing_fingerprint=expected_fingerprint,
        processing_fingerprint_version=expected_fingerprint_version,
        sfreq_hz=first.sfreq_hz,
        n_times=first.n_times,
        frequency_resolution_hz=first.frequency_resolution_hz,
    )


def _validate_artifact(
    *,
    root: Path,
    input_root: Path,
    manifest_path: Path,
    group_folder: str | None,
    artifact: Mapping[str, Any],
    expected: ExpectedProjectTimeDomainInput,
    expected_processing_fingerprint: str,
    expected_processing_fingerprint_version: str,
) -> ProjectTimeDomainInputRecord:
    if artifact.get("complete") is not True:
        raise ProjectTimeDomainInputError(
            f"Source-ready artifact is not committed as complete for {_format_key(expected.key)}."
        )
    condition_label = _identity(artifact.get("condition_label"), "artifact condition_label")
    if expected.condition_label is not None and condition_label != expected.condition_label:
        raise ProjectTimeDomainInputError(
            f"Condition label mismatch for {_format_key(expected.key)}: "
            f"{condition_label!r} != {expected.condition_label!r}."
        )
    if expected.group_folder is not None and group_folder != expected.group_folder:
        raise ProjectTimeDomainInputError(
            f"Group folder mismatch for {_format_key(expected.key)}: "
            f"{group_folder!r} != {expected.group_folder!r}."
        )

    fif_path = _resolve_project_relative_file(
        root,
        artifact.get("fif_path"),
        allowed_root=input_root,
        label="source-ready FIF",
    )
    sidecar_path = _resolve_project_relative_file(
        root,
        artifact.get("sidecar_path"),
        allowed_root=input_root,
        label="source-ready sidecar",
    )
    condition_folder = _validate_artifact_layout(
        fif_path,
        sidecar_path,
        input_root=input_root,
        participant_id=expected.participant_id,
        condition_id=expected.condition_id,
        group_folder=group_folder,
    )
    fif_sha256 = _sha256_value(artifact.get("fif_sha256"), "artifact fif_sha256")
    sidecar_sha256 = _sha256_value(artifact.get("sidecar_sha256"), "artifact sidecar_sha256")
    _verify_checksum(fif_path, fif_sha256, label="source-ready FIF")
    _verify_checksum(sidecar_path, sidecar_sha256, label="source-ready sidecar")

    sidecar = _read_json_object(sidecar_path, label="source-ready sidecar")
    _validate_format(sidecar, expected=SOURCE_TIME_DOMAIN_SIDECAR_FORMAT, label=f"sidecar {sidecar_path}")
    if sidecar.get("complete") is not True:
        raise ProjectTimeDomainInputError(f"Source-ready sidecar is not complete: {sidecar_path}.")
    _require_equal(sidecar, "participant_id", expected.participant_id, sidecar_path)
    _require_equal(sidecar, "condition_id", expected.condition_id, sidecar_path)
    _require_equal(sidecar, "condition_label", condition_label, sidecar_path)
    _require_equal(sidecar, "group_id", expected.group_id, sidecar_path)
    if _optional_component(sidecar.get("group_folder"), "sidecar group_folder") != group_folder:
        raise ProjectTimeDomainInputError(f"Sidecar group_folder does not match its commit manifest: {sidecar_path}.")
    if _project_relative_posix(root, fif_path) != _required_posix_relative(sidecar.get("fif_path"), "sidecar fif_path"):
        raise ProjectTimeDomainInputError(f"Sidecar fif_path does not match its committed artifact: {sidecar_path}.")
    if _sha256_value(sidecar.get("fif_sha256"), "sidecar fif_sha256") != fif_sha256:
        raise ProjectTimeDomainInputError(f"Sidecar FIF checksum does not match its commit manifest: {sidecar_path}.")

    processing = _mapping(sidecar.get("processing"), "sidecar processing")
    fingerprint = _identity(processing.get("fingerprint"), "sidecar processing fingerprint")
    fingerprint_version = _identity(
        processing.get("fingerprint_version"),
        "sidecar processing fingerprint_version",
    )
    if fingerprint != expected_processing_fingerprint or fingerprint_version != expected_processing_fingerprint_version:
        raise ProjectTimeDomainInputError(
            f"Stale source-ready derivative for {_format_key(expected.key)}: processing fingerprint "
            "does not match the current canonical processing plan. Reprocess this participant."
        )

    sampling = _mapping(sidecar.get("sampling"), "sidecar sampling")
    sfreq_hz = _positive_float(sampling.get("sfreq_hz"), "sampling sfreq_hz")
    n_times = _positive_int(sampling.get("n_times"), "sampling n_times")
    duration_sec = _positive_float(sampling.get("duration_sec"), "sampling duration_sec")
    frequency_resolution_hz = _positive_float(
        sampling.get("frequency_resolution_hz"),
        "sampling frequency_resolution_hz",
    )
    _require_close(duration_sec, n_times / sfreq_hz, "sampling duration_sec must equal N / sfreq")
    _require_close(
        frequency_resolution_hz,
        sfreq_hz / n_times,
        "sampling frequency_resolution_hz must equal sfreq / N",
    )

    channels = _mapping(sidecar.get("channels"), "sidecar channels")
    channel_names = _string_tuple(channels.get("names"), "channel names")
    channel_types = tuple(value.casefold() for value in _string_tuple(channels.get("types"), "channel types"))
    channel_units = _string_tuple(channels.get("units"), "channel units")
    bad_channels = _string_tuple(channels.get("bads"), "bad channels", allow_empty=True)
    channel_count = _positive_int(channels.get("count"), "channel count")
    if channels.get("eeg_only") is not True:
        raise ProjectTimeDomainInputError(f"Source-ready derivative must declare eeg_only=true: {sidecar_path}.")
    expected_channels = tuple(DEFAULT_ELECTRODE_NAMES_64)
    if channel_names != expected_channels:
        raise ProjectTimeDomainInputError(
            f"Source-ready EEG channel order is incompatible for {_format_key(expected.key)}; "
            "the exact Toolbox BioSemi64 order is required."
        )
    if channel_count != len(channel_names) or len(channel_types) != channel_count or len(channel_units) != channel_count:
        raise ProjectTimeDomainInputError(f"Source-ready channel metadata lengths do not agree: {sidecar_path}.")
    if any(value != "eeg" for value in channel_types):
        raise ProjectTimeDomainInputError(f"Source-ready derivative contains a non-EEG channel: {sidecar_path}.")
    if any(value != SOURCE_TIME_DOMAIN_DATA_UNIT for value in channel_units):
        raise ProjectTimeDomainInputError(f"Source-ready derivative channel units must all be volts: {sidecar_path}.")
    if bad_channels:
        raise ProjectTimeDomainInputError(
            f"Source-ready derivative retains bad EEG channels {bad_channels}; a complete interpolated BioSemi64 set is required."
        )

    aggregation = _mapping(sidecar.get("aggregation"), "sidecar aggregation")
    if aggregation.get("domain") != SOURCE_TIME_DOMAIN_AGGREGATION_DOMAIN:
        raise ProjectTimeDomainInputError(f"Source-ready derivative was not aggregated in the time domain: {sidecar_path}.")
    if aggregation.get("method") != SOURCE_TIME_DOMAIN_AGGREGATION_METHOD:
        raise ProjectTimeDomainInputError(f"Source-ready derivative must use arithmetic-mean aggregation: {sidecar_path}.")
    if aggregation.get("signed_values_preserved") is not True:
        raise ProjectTimeDomainInputError(f"Source-ready derivative does not preserve signed values: {sidecar_path}.")
    repetition_count = _positive_int(aggregation.get("repetition_count"), "aggregation repetition_count")

    crop = _mapping(sidecar.get("crop"), "sidecar crop")
    if crop.get("crop_mode") != SOURCE_TIME_DOMAIN_CROP_MODE:
        raise ProjectTimeDomainInputError(f"Source-ready derivative requires crop_mode=55_onbin: {sidecar_path}.")
    crop_n = _positive_int(crop.get("N"), "crop N")
    n_step = _positive_int(crop.get("N_step"), "crop N_step")
    n_mod_step = _nonnegative_int(crop.get("N_mod_step"), "crop N_mod_step")
    if crop_n != n_times or n_mod_step != 0 or n_times % n_step != 0:
        raise ProjectTimeDomainInputError(
            f"Source-ready on-bin crop contract is incompatible for {_format_key(expected.key)}: "
            f"N={crop_n}, N_step={n_step}, N_mod_step={n_mod_step}."
        )

    reference = _mapping(sidecar.get("reference"), "sidecar reference")
    reference_signature = _reference_signature(reference, sidecar_path)
    _mapping(sidecar.get("resolved_protocol"), "sidecar resolved_protocol")
    source_signature = sidecar.get("source_signature")
    if source_signature is not None and not isinstance(source_signature, Mapping):
        raise ProjectTimeDomainInputError(f"sidecar source_signature must be an object or null: {sidecar_path}.")

    return ProjectTimeDomainInputRecord(
        participant_id=expected.participant_id,
        condition_id=expected.condition_id,
        condition_label=condition_label,
        group_id=expected.group_id,
        group_folder=group_folder,
        condition_folder=condition_folder,
        manifest_path=manifest_path,
        fif_path=fif_path,
        sidecar_path=sidecar_path,
        fif_sha256=fif_sha256,
        sidecar_sha256=sidecar_sha256,
        processing_fingerprint=fingerprint,
        processing_fingerprint_version=fingerprint_version,
        sfreq_hz=sfreq_hz,
        n_times=n_times,
        duration_sec=duration_sec,
        frequency_resolution_hz=frequency_resolution_hz,
        n_step=n_step,
        n_mod_step=n_mod_step,
        repetition_count=repetition_count,
        channel_names=channel_names,
        channel_types=channel_types,
        channel_units=channel_units,
        bad_channels=bad_channels,
        reference_signature=reference_signature,
        sidecar=dict(sidecar),
    )


def _validate_record_compatibility(records: Sequence[ProjectTimeDomainInputRecord]) -> None:
    first = records[0]
    for record in records[1:]:
        if record.channel_names != first.channel_names or record.channel_types != first.channel_types:
            raise ProjectTimeDomainInputError("Source-ready derivatives do not share one ordered EEG channel contract.")
        if record.reference_signature != first.reference_signature:
            raise ProjectTimeDomainInputError("Source-ready derivatives do not share one compatible EEG reference state.")
        _require_close(record.sfreq_hz, first.sfreq_hz, "Source-ready sampling frequencies are incompatible")
        if record.n_times != first.n_times:
            raise ProjectTimeDomainInputError("Source-ready derivatives do not share the same exact sample count N.")
        _require_close(
            record.frequency_resolution_hz,
            first.frequency_resolution_hz,
            "Source-ready frequency resolutions are incompatible",
        )
        if record.n_step != first.n_step or record.n_mod_step != first.n_mod_step:
            raise ProjectTimeDomainInputError("Source-ready derivatives do not share one on-bin crop contract.")


def _read_and_validate_raw(
    record: ProjectTimeDomainInputRecord,
    *,
    preload: bool,
    require_finite: bool,
):  # noqa: ANN202
    validated = False
    try:
        import mne
        from mne.io.constants import FIFF
    except (ImportError, ModuleNotFoundError) as exc:
        raise ProjectTimeDomainInputError(f"MNE is required to load source-ready FIF inputs: {exc}") from exc
    try:
        raw = mne.io.read_raw_fif(record.fif_path, preload=preload, verbose=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ProjectTimeDomainInputError(f"Unable to read source-ready FIF {record.fif_path}: {exc}") from exc
    try:
        if tuple(raw.ch_names) != record.channel_names:
            raise ProjectTimeDomainInputError(f"FIF channel order does not match its sidecar: {record.fif_path}.")
        if tuple(raw.get_channel_types()) != record.channel_types:
            raise ProjectTimeDomainInputError(f"FIF channel types do not match its sidecar: {record.fif_path}.")
        if tuple(str(value) for value in raw.info.get("bads", ())) != record.bad_channels:
            raise ProjectTimeDomainInputError(f"FIF bad-channel state does not match its sidecar: {record.fif_path}.")
        _require_close(float(raw.info["sfreq"]), record.sfreq_hz, f"FIF sfreq mismatch: {record.fif_path}")
        if int(raw.n_times) != record.n_times:
            raise ProjectTimeDomainInputError(f"FIF sample count N does not match its sidecar: {record.fif_path}.")
        units = tuple(int(channel["unit"]) for channel in raw.info["chs"])
        if any(unit != int(FIFF.FIFF_UNIT_V) for unit in units):
            raise ProjectTimeDomainInputError(f"FIF EEG data are not stored with volt units: {record.fif_path}.")
        if not raw.info.get("dig"):
            raise ProjectTimeDomainInputError(f"FIF is missing its EEG montage/digitization state: {record.fif_path}.")
        actual_reference = _raw_reference_signature(raw)
        if actual_reference != record.reference_signature:
            raise ProjectTimeDomainInputError(f"FIF reference/projector state does not match its sidecar: {record.fif_path}.")
        if require_finite:
            data = raw.get_data()
            if data.shape != (len(record.channel_names), record.n_times) or not np.all(np.isfinite(data)):
                raise ProjectTimeDomainInputError(f"FIF contains non-finite or incorrectly shaped EEG data: {record.fif_path}.")
        validated = True
        return raw
    finally:
        if not validated:
            close = getattr(raw, "close", None)
            if callable(close):
                close()


def _reference_signature(reference: Mapping[str, Any], sidecar_path: Path) -> tuple[object, ...]:
    custom_ref_applied = _reference_flag(reference.get("custom_ref_applied"), "reference custom_ref_applied")
    projections = reference.get("projections")
    if not isinstance(projections, list):
        raise ProjectTimeDomainInputError(f"reference projections must be a list: {sidecar_path}.")
    normalized: list[tuple[str, bool, int | None]] = []
    for projection in projections:
        if not isinstance(projection, Mapping):
            raise ProjectTimeDomainInputError(f"reference projection entries must be objects: {sidecar_path}.")
        description = _identity(
            projection.get("description", projection.get("desc")),
            "reference projection description",
        )
        active = projection.get("active")
        if not isinstance(active, bool):
            raise ProjectTimeDomainInputError(f"reference projection active must be boolean: {sidecar_path}.")
        kind_value = projection.get("kind")
        if kind_value is not None and (isinstance(kind_value, bool) or not isinstance(kind_value, (int, np.integer))):
            raise ProjectTimeDomainInputError(f"reference projection kind must be an integer or null: {sidecar_path}.")
        kind = None if kind_value is None else int(kind_value)
        normalized.append((description, active, kind))
    if not any(
        description.casefold() == "average eeg reference" and active
        for description, active, _kind in normalized
    ):
        raise ProjectTimeDomainInputError(
            f"Source-ready derivative requires an applied Average EEG reference projection: {sidecar_path}."
        )
    return (custom_ref_applied, *tuple(normalized))


def _raw_reference_signature(raw) -> tuple[object, ...]:  # noqa: ANN001
    projections = tuple(
        (str(projection["desc"]), bool(projection["active"]), int(projection["kind"]))
        for projection in raw.info["projs"]
    )
    return (int(raw.info["custom_ref_applied"]), *projections)


def _validate_manifest_location(
    manifest_path: Path,
    *,
    manifests_root: Path,
    participant_id: str,
    declared_group_folder: object,
    grouped: bool,
) -> str | None:
    relative = manifest_path.relative_to(manifests_root)
    if len(relative.parts) not in {1, 2}:
        raise ProjectTimeDomainInputError(f"Participant manifest has an invalid grouped layout: {manifest_path}.")
    if relative.name != f"{participant_id}.json":
        raise ProjectTimeDomainInputError(
            f"Participant manifest filename must be {participant_id}.json: {manifest_path}."
        )
    path_group_folder = relative.parts[0] if len(relative.parts) == 2 else None
    declared = _optional_component(declared_group_folder, "manifest group_folder")
    if declared is not None and declared != path_group_folder:
        raise ProjectTimeDomainInputError(f"Manifest group_folder does not match its directory: {manifest_path}.")
    group_folder = declared or path_group_folder
    if grouped and group_folder is None:
        raise ProjectTimeDomainInputError(f"Grouped participant manifest is missing its group folder: {manifest_path}.")
    if not grouped and group_folder is not None:
        raise ProjectTimeDomainInputError(f"Ungrouped participant manifest is unexpectedly nested by group: {manifest_path}.")
    return group_folder


def _validate_artifact_layout(
    fif_path: Path,
    sidecar_path: Path,
    *,
    input_root: Path,
    participant_id: str,
    condition_id: str,
    group_folder: str | None,
) -> str:
    fif_relative = fif_path.relative_to(input_root)
    sidecar_relative = sidecar_path.relative_to(input_root)
    if fif_relative.parent != sidecar_relative.parent:
        raise ProjectTimeDomainInputError("Source-ready FIF and sidecar must share one condition/group folder.")
    expected_depth = 3 if group_folder is not None else 2
    if len(fif_relative.parts) != expected_depth:
        raise ProjectTimeDomainInputError(f"Source-ready artifact does not use condition-first/group-second layout: {fif_path}.")
    condition_folder = _component(fif_relative.parts[0], "condition folder")
    if group_folder is not None and fif_relative.parts[1] != group_folder:
        raise ProjectTimeDomainInputError(f"Source-ready artifact group folder does not match its manifest: {fif_path}.")
    if fif_path.name != f"{participant_id}_{condition_id}_avg_raw.fif":
        raise ProjectTimeDomainInputError(f"Source-ready FIF filename is not canonical for {participant_id}: {fif_path}.")
    if sidecar_path.name != f"{participant_id}_{condition_id}_avg_raw.json":
        raise ProjectTimeDomainInputError(f"Source-ready sidecar filename is not canonical for {participant_id}: {sidecar_path}.")
    return condition_folder


def _project_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project root does not exist: {root}")
    return root


def _resolve_project_relative_file(root: Path, value: object, *, allowed_root: Path, label: str) -> Path:
    relative = _required_posix_relative(value, f"{label} path")
    target = root.joinpath(*relative.parts).resolve()
    return _require_existing_project_file(root, target, allowed_root=allowed_root, label=label)


def _required_posix_relative(value: object, label: str) -> PurePosixPath:
    text = str(value).strip() if isinstance(value, str) else ""
    if not text:
        raise ProjectTimeDomainInputError(f"{label} must be a non-empty string.")
    if "\\" in text:
        raise ProjectTimeDomainInputError(f"{label} must use a project-relative POSIX path.")
    relative = PurePosixPath(text)
    if relative.is_absolute() or not relative.parts or any(part in {"", ".", ".."} or ":" in part for part in relative.parts):
        raise ProjectTimeDomainInputError(f"{label} must be a safe project-relative POSIX path: {text!r}.")
    return relative


def _require_existing_project_file(root: Path, path: Path, *, allowed_root: Path, label: str) -> Path:
    target = path.resolve()
    project_root = root.resolve()
    confined_root = allowed_root.resolve()
    try:
        target.relative_to(project_root)
        target.relative_to(confined_root)
    except ValueError as exc:
        raise ProjectTimeDomainInputError(f"Refusing to read {label} outside the project derivative root: {target}.") from exc
    if not target.is_file():
        raise ProjectTimeDomainInputError(f"Required {label} does not exist: {target}.")
    return target


def _project_relative_posix(root: Path, path: Path) -> PurePosixPath:
    return PurePosixPath(*path.resolve().relative_to(root.resolve()).parts)


def _read_json_object(path: Path, *, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProjectTimeDomainInputError(f"Unable to read {label} {path}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise ProjectTimeDomainInputError(f"{label} must contain one JSON object: {path}.")
    return payload


def _verify_checksum(path: Path, expected: str, *, label: str) -> None:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ProjectTimeDomainInputError(f"Unable to checksum {label} {path}: {exc}") from exc
    actual = digest.hexdigest()
    if actual != expected:
        raise ProjectTimeDomainInputError(
            f"{label} checksum mismatch for {path}; the derivative is stale, corrupt, or incompletely published."
        )


def _validate_format(payload: Mapping[str, Any], *, expected: str, label: str) -> None:
    if payload.get("format") != expected:
        raise ProjectTimeDomainInputError(
            f"Unsupported {label} format {payload.get('format')!r}; expected {expected!r}."
        )
    if payload.get("schema_version") != 1:
        raise ProjectTimeDomainInputError(
            f"Unsupported {label} schema version {payload.get('schema_version')!r}; expected 1."
        )


def _require_equal(payload: Mapping[str, Any], key: str, expected: object, path: Path) -> None:
    if payload.get(key) != expected:
        raise ProjectTimeDomainInputError(
            f"Sidecar {key} does not match its participant commit manifest: {path}."
        )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectTimeDomainInputError(f"{label} must be a JSON object.")
    return value


def _identity(value: object, label: str) -> str:
    text = str(value).strip() if isinstance(value, str) else ""
    if not text or any(char in text for char in "/\\\0"):
        raise ProjectTimeDomainInputError(f"{label} must be a non-empty safe string.")
    return text


def _optional_identity(value: object, label: str) -> str | None:
    if value in (None, ""):
        return None
    return _identity(value, label)


def _condition_id(value: object) -> str:
    condition_id = _identity(value, "condition_id")
    if _CONDITION_ID_PATTERN.fullmatch(condition_id) is None:
        raise ProjectTimeDomainInputError(
            f"condition_id must be a stable path-safe identifier, got {condition_id!r}."
        )
    return condition_id


def _component(value: object, label: str) -> str:
    text = _identity(value, label)
    if text in {".", ".."} or ":" in text:
        raise ProjectTimeDomainInputError(f"{label} must be a safe path component.")
    return text


def _optional_component(value: object, label: str) -> str | None:
    if value in (None, ""):
        return None
    return _component(value, label)


def _optional_label(value: object, label: str) -> str | None:
    if value in (None, ""):
        return None
    return _identity(value, label)


def _sha256_value(value: object, label: str) -> str:
    text = str(value).strip().casefold() if isinstance(value, str) else ""
    if _SHA256_PATTERN.fullmatch(text) is None:
        raise ProjectTimeDomainInputError(f"{label} must be a 64-character SHA-256 hex digest.")
    return text


def _positive_float(value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ProjectTimeDomainInputError(f"{label} must be a positive finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProjectTimeDomainInputError(f"{label} must be a positive finite number.") from exc
    if not math.isfinite(number) or number <= 0:
        raise ProjectTimeDomainInputError(f"{label} must be a positive finite number.")
    return number


def _positive_int(value: object, label: str) -> int:
    number = _nonnegative_int(value, label)
    if number <= 0:
        raise ProjectTimeDomainInputError(f"{label} must be positive.")
    return number


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
        raise ProjectTimeDomainInputError(f"{label} must be a non-negative integer.")
    number = int(value)
    if number < 0:
        raise ProjectTimeDomainInputError(f"{label} must be a non-negative integer.")
    return number


def _reference_flag(value: object, label: str) -> int:
    if isinstance(value, bool):
        return int(value)
    return _nonnegative_int(value, label)


def _string_tuple(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ProjectTimeDomainInputError(f"{label} must be a JSON list of strings.")
    result = tuple(_identity(item, label) for item in value)
    if not result and not allow_empty:
        raise ProjectTimeDomainInputError(f"{label} cannot be empty.")
    return result


def _require_close(actual: float, expected: float, label: str) -> None:
    if not math.isclose(float(actual), float(expected), rel_tol=_FLOAT_REL_TOL, abs_tol=_FLOAT_ABS_TOL):
        raise ProjectTimeDomainInputError(f"{label}: {actual!r} != {expected!r}.")


def _missing_derivative_message(manifests_root: Path) -> str:
    return (
        f"Source-ready time-domain participant manifests do not exist at {manifests_root}. "
        "Reprocess the project to create signed time-domain derivatives; amplitude workbooks are not a fallback."
    )


def _format_key(key: tuple[str | None, str, str]) -> str:
    group_id, participant_id, condition_id = key
    group_text = f"group={group_id}, " if group_id is not None else ""
    return f"{group_text}participant={participant_id}, condition={condition_id}"


def _format_participant_key(key: tuple[str | None, str]) -> str:
    group_id, participant_id = key
    return f"{group_id}/{participant_id}" if group_id is not None else participant_id


__all__ = [
    "ExpectedProjectTimeDomainInput",
    "LoadedProjectTimeDomainRaw",
    "PROJECT_TIME_DOMAIN_INPUT_FOLDER",
    "ProjectTimeDomainInputError",
    "ProjectTimeDomainInputRecord",
    "ProjectTimeDomainInputSet",
    "SOURCE_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT",
    "SOURCE_TIME_DOMAIN_SIDECAR_FORMAT",
    "default_project_time_domain_input_dir",
    "load_project_time_domain_inputs",
]

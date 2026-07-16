"""Write project-local, source-ready signed time-domain EEG derivatives.

The export is intentionally limited to preparing averaged MNE Raw FIF inputs.
It performs no FFT, magnitude, inverse, harmonic, or source-space calculation.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
import time
from typing import Any, Mapping, Sequence

import mne
import numpy as np


logger = logging.getLogger(__name__)

SOURCE_READY_TIME_DOMAIN_FORMAT = "fpvs-source-ready-time-domain-v1"
SOURCE_READY_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT = (
    "fpvs-source-ready-time-domain-participant-manifest-v1"
)
SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT = (
    Path("6 - Source Localization") / "Source-Ready Time Domain v1"
)
SOURCE_READY_TIME_DOMAIN_MANIFEST_FOLDER = "manifests"

_INVALID_WINDOWS_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass(frozen=True)
class SourceReadyTimeDomainArtifact:
    """One committed participant/condition derivative."""

    condition_id: str
    condition_label: str
    fif_path: Path
    sidecar_path: Path
    fif_sha256: str
    sidecar_sha256: str


@dataclass(frozen=True)
class SourceReadyTimeDomainExportResult:
    """Paths committed by one participant export."""

    participant_id: str
    group_id: str | None
    group_folder: str | None
    output_root: Path
    manifest_path: Path
    artifacts: tuple[SourceReadyTimeDomainArtifact, ...]


@dataclass(frozen=True)
class _ConditionPlan:
    condition_id: str
    condition_label: str
    condition_folder: str
    epochs: Any
    fif_path: Path
    sidecar_path: Path


def write_source_ready_time_domain_derivatives(
    *,
    project_root: str | Path,
    participant_id: str,
    condition_epochs: Mapping[str, Any],
    condition_ids: Mapping[str, str | int] | None = None,
    group_id: str | None = None,
    group_folder: str | None = None,
    crop_provenance_by_condition: Mapping[str, Mapping[str, Any]] | None = None,
    processing_provenance: Mapping[str, Any] | None = None,
    source_signature: Mapping[str, Any] | None = None,
    resolved_protocol_by_condition: Mapping[str, Mapping[str, Any] | None] | None = None,
) -> SourceReadyTimeDomainExportResult:
    """Write all source-ready conditions for one participant and commit last.

    ``condition_epochs`` accepts either an MNE Epochs object per condition or
    the active runner's one-item ``[Epochs]`` wrapper. The derivative is the
    arithmetic mean across repetitions in signed volts and contains EEG only.
    A participant manifest is written only after every FIF and JSON sidecar has
    been replaced successfully.
    """

    root = _active_project_root(project_root)
    participant = _path_component(participant_id, field="participant_id")
    normalized_group_id = _optional_identifier(group_id, field="group_id")
    normalized_group_folder = _optional_path_component(
        group_folder if group_folder is not None else normalized_group_id,
        field="group_folder",
    )
    if not condition_epochs:
        raise ValueError("condition_epochs must contain at least one condition")

    output_root = _project_path(root, *SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT.parts)
    plans = _condition_plans(
        root=root,
        output_root=output_root,
        participant_id=participant,
        group_folder=normalized_group_folder,
        condition_epochs=condition_epochs,
        condition_ids=condition_ids or {},
    )
    manifest_parts = [SOURCE_READY_TIME_DOMAIN_MANIFEST_FOLDER]
    if normalized_group_folder is not None:
        manifest_parts.append(normalized_group_folder)
    manifest_parts.append(f"{participant}.json")
    manifest_path = _project_path(output_root, *manifest_parts)

    crop_lookup = crop_provenance_by_condition or {}
    protocol_lookup = resolved_protocol_by_condition or {}
    processing = _json_value(dict(processing_provenance or {}))
    signature = _json_value(dict(source_signature or {})) if source_signature is not None else None
    written_paths: list[Path] = []
    artifacts: list[SourceReadyTimeDomainArtifact] = []
    committed = False

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.unlink(missing_ok=True)
    try:
        for plan in plans:
            plan.fif_path.parent.mkdir(parents=True, exist_ok=True)
            average_raw, repetition_count = _averaged_eeg_raw(plan.epochs)
            crop = _crop_payload(
                epochs=plan.epochs,
                explicit=crop_lookup.get(plan.condition_label),
                n_times=int(average_raw.n_times),
                sfreq_hz=float(average_raw.info["sfreq"]),
            )
            protocol = _resolved_protocol(protocol_lookup.get(plan.condition_label))
            _atomic_write_raw_fif(plan.fif_path, average_raw)
            written_paths.append(plan.fif_path)
            fif_sha256 = _sha256_file(plan.fif_path)

            sidecar = _sidecar_payload(
                root=root,
                plan=plan,
                raw=average_raw,
                repetition_count=repetition_count,
                participant_id=participant,
                group_id=normalized_group_id,
                group_folder=normalized_group_folder,
                fif_sha256=fif_sha256,
                crop=crop,
                processing=processing,
                source_signature=signature,
                resolved_protocol=protocol,
            )
            _atomic_write_json(plan.sidecar_path, sidecar)
            written_paths.append(plan.sidecar_path)
            sidecar_sha256 = _sha256_file(plan.sidecar_path)
            artifacts.append(
                SourceReadyTimeDomainArtifact(
                    condition_id=plan.condition_id,
                    condition_label=plan.condition_label,
                    fif_path=plan.fif_path,
                    sidecar_path=plan.sidecar_path,
                    fif_sha256=fif_sha256,
                    sidecar_sha256=sidecar_sha256,
                )
            )

        manifest = {
            "format": SOURCE_READY_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT,
            "schema_version": 1,
            "complete": True,
            "participant_id": participant,
            "group_id": normalized_group_id,
            "group_folder": normalized_group_folder,
            "artifact_count": len(artifacts),
            "artifacts": [
                {
                    "condition_id": artifact.condition_id,
                    "condition_label": artifact.condition_label,
                    "fif_path": _relative_project_path(root, artifact.fif_path),
                    "sidecar_path": _relative_project_path(root, artifact.sidecar_path),
                    "fif_sha256": artifact.fif_sha256,
                    "sidecar_sha256": artifact.sidecar_sha256,
                    "complete": True,
                }
                for artifact in artifacts
            ],
        }
        _atomic_write_json(manifest_path, manifest)
        committed = True
    finally:
        if not committed:
            manifest_path.unlink(missing_ok=True)
            for path in reversed(written_paths):
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logger.warning("source_time_domain_partial_cleanup_failed path=%s", path)

    logger.info(
        "source_ready_time_domain_exported participant=%s group=%s conditions=%d manifest=%s",
        participant,
        normalized_group_id,
        len(artifacts),
        manifest_path,
    )
    return SourceReadyTimeDomainExportResult(
        participant_id=participant,
        group_id=normalized_group_id,
        group_folder=normalized_group_folder,
        output_root=output_root,
        manifest_path=manifest_path,
        artifacts=tuple(artifacts),
    )


def _active_project_root(project_root: str | Path) -> Path:
    supplied = Path(project_root)
    if not supplied.is_absolute():
        raise ValueError("project_root must be an explicit absolute path")
    root = _canonical_resolved_path(supplied)
    if not root.is_dir():
        raise ValueError(f"project_root must be an existing directory: {root}")
    return root


def _condition_plans(
    *,
    root: Path,
    output_root: Path,
    participant_id: str,
    group_folder: str | None,
    condition_epochs: Mapping[str, Any],
    condition_ids: Mapping[str, str | int],
) -> tuple[_ConditionPlan, ...]:
    plans: list[_ConditionPlan] = []
    seen_ids: set[str] = set()
    seen_folders: set[str] = set()
    for condition_label, epochs_value in condition_epochs.items():
        label = str(condition_label).strip()
        condition_folder = _path_component(label, field="condition_label")
        condition_id = _stable_identifier(
            condition_ids.get(condition_label, condition_label),
            field=f"condition_id[{label}]",
        )
        if condition_id.casefold() in seen_ids:
            raise ValueError(f"condition_ids must remain unique after sanitizing: {condition_id}")
        if condition_folder.casefold() in seen_folders:
            raise ValueError(f"condition labels map to the same output folder: {condition_folder}")
        seen_ids.add(condition_id.casefold())
        seen_folders.add(condition_folder.casefold())
        epochs = _coerce_epochs(epochs_value, condition_label=label)
        folder_parts = [condition_folder]
        if group_folder is not None:
            folder_parts.append(group_folder)
        condition_dir = _project_path(output_root, *folder_parts)
        stem = f"{participant_id}_{condition_id}_avg"
        fif_path = _project_path(condition_dir, f"{stem}_raw.fif")
        sidecar_path = _project_path(condition_dir, f"{stem}_raw.json")
        plans.append(
            _ConditionPlan(
                condition_id=condition_id,
                condition_label=label,
                condition_folder=condition_folder,
                epochs=epochs,
                fif_path=fif_path,
                sidecar_path=sidecar_path,
            )
        )
    plans.sort(key=lambda plan: (plan.condition_id.casefold(), plan.condition_label.casefold()))
    for plan in plans:
        _relative_project_path(root, plan.fif_path)
        _relative_project_path(root, plan.sidecar_path)
    return tuple(plans)


def _coerce_epochs(value: Any, *, condition_label: str) -> Any:
    if hasattr(value, "get_data") and hasattr(value, "info"):
        return value
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        if len(value) != 1:
            raise ValueError(
                f"condition {condition_label!r} must contain exactly one Epochs object; got {len(value)}"
            )
        candidate = value[0]
        if hasattr(candidate, "get_data") and hasattr(candidate, "info"):
            return candidate
    raise TypeError(f"condition {condition_label!r} does not contain an MNE Epochs object")


def _averaged_eeg_raw(epochs: Any) -> tuple[Any, int]:
    eeg_picks = mne.pick_types(
        epochs.info,
        meg=False,
        eeg=True,
        stim=False,
        eog=False,
        ecg=False,
        misc=False,
        exclude=[],
    )
    if len(eeg_picks) == 0:
        raise ValueError("source-ready time-domain export requires at least one EEG channel")
    data = np.asarray(epochs.get_data(picks=eeg_picks, copy=True))
    if data.ndim != 3 or data.shape[0] == 0:
        raise ValueError(f"Epochs data must have shape (repetitions, EEG channels, samples); got {data.shape}")
    if data.shape[2] == 0:
        raise ValueError("source-ready time-domain export requires at least one time sample")
    if not np.isfinite(data).all():
        raise ValueError("source-ready time-domain Epochs contain non-finite values")
    averaged = np.mean(data, axis=0, dtype=np.float64)
    info = mne.pick_info(epochs.info.copy(), eeg_picks, copy=True)
    raw = mne.io.RawArray(averaged, info, first_samp=0, copy="auto", verbose=False)
    return raw, int(data.shape[0])


def _crop_payload(
    *,
    epochs: Any,
    explicit: Mapping[str, Any] | None,
    n_times: int,
    sfreq_hz: float,
) -> dict[str, Any]:
    provided = dict(explicit or {})
    records = _epochs_metadata_records(epochs)
    if records and "repetitions" not in provided:
        provided["repetitions"] = records

    supplied_n = provided.get("N", provided.get("n_times"))
    if supplied_n is not None and int(supplied_n) != n_times:
        raise ValueError(f"crop provenance N={supplied_n} does not match Epochs N={n_times}")
    supplied_sfreq = provided.get("sfreq_hz", provided.get("fs"))
    if supplied_sfreq is not None and not math.isclose(
        float(supplied_sfreq), sfreq_hz, rel_tol=0.0, abs_tol=1e-9
    ):
        raise ValueError(
            f"crop provenance sfreq={supplied_sfreq} does not match Epochs sfreq={sfreq_hz}"
        )

    crop_mode = provided.get("crop_mode", _uniform_record_value(records, "crop_mode"))
    n_step_value = provided.get("N_step", _uniform_record_value(records, "N_step"))
    n_step = int(n_step_value) if n_step_value is not None else None
    if n_step is not None and n_step <= 0:
        raise ValueError("crop provenance N_step must be positive when provided")
    computed_mod = n_times % n_step if n_step else None
    n_mod_value = provided.get("N_mod_step", _uniform_record_value(records, "N_mod_step"))
    n_mod_step = int(n_mod_value) if n_mod_value is not None else computed_mod
    if computed_mod is not None and n_mod_step != computed_mod:
        raise ValueError(
            f"crop provenance N_mod_step={n_mod_step} does not match N % N_step={computed_mod}"
        )
    return {
        "crop_mode": str(crop_mode) if crop_mode is not None else None,
        "N": n_times,
        "N_step": n_step,
        "N_mod_step": n_mod_step,
        "provenance": _json_value(provided),
    }


def _epochs_metadata_records(epochs: Any) -> list[dict[str, Any]]:
    metadata = getattr(epochs, "metadata", None)
    if metadata is None or getattr(metadata, "empty", True):
        return []
    records = metadata.to_dict(orient="records")
    return [_json_value(dict(record)) for record in records]


def _uniform_record_value(records: Sequence[Mapping[str, Any]], key: str) -> Any:
    values = [record.get(key) for record in records if record.get(key) is not None]
    if not values:
        return None
    first = values[0]
    return first if all(value == first for value in values[1:]) else None


def _resolved_protocol(value: Mapping[str, Any] | None) -> dict[str, Any]:
    protocol = dict(value or {})
    return {
        "presentation_rate_hz": _json_value(protocol.get("presentation_rate_hz")),
        "oddball_rate_hz": _json_value(protocol.get("oddball_rate_hz")),
        "contrast_modulation": _json_value(
            protocol.get("contrast_modulation", protocol.get("modulation"))
        ),
    }


def _sidecar_payload(
    *,
    root: Path,
    plan: _ConditionPlan,
    raw: Any,
    repetition_count: int,
    participant_id: str,
    group_id: str | None,
    group_folder: str | None,
    fif_sha256: str,
    crop: Mapping[str, Any],
    processing: Any,
    source_signature: Any,
    resolved_protocol: Mapping[str, Any],
) -> dict[str, Any]:
    sfreq_hz = float(raw.info["sfreq"])
    n_times = int(raw.n_times)
    channel_names = list(raw.ch_names)
    channel_types = list(raw.get_channel_types())
    processing_mapping = processing if isinstance(processing, Mapping) else {}
    return {
        "format": SOURCE_READY_TIME_DOMAIN_FORMAT,
        "schema_version": 1,
        "complete": True,
        "writer": {
            "mne_version": str(mne.__version__),
            "numpy_version": str(np.__version__),
        },
        "participant_id": participant_id,
        "group_id": group_id,
        "group_folder": group_folder,
        "condition_id": plan.condition_id,
        "condition_label": plan.condition_label,
        "fif_path": _relative_project_path(root, plan.fif_path),
        "fif_sha256": fif_sha256,
        "source_signature": source_signature,
        "processing": {
            "fingerprint": processing_mapping.get("processing_fingerprint"),
            "fingerprint_version": processing_mapping.get("processing_fingerprint_version"),
            "provenance": processing,
        },
        "sampling": {
            "sfreq_hz": sfreq_hz,
            "n_times": n_times,
            "duration_sec": n_times / sfreq_hz,
            "frequency_resolution_hz": sfreq_hz / n_times,
        },
        "channels": {
            "count": len(channel_names),
            "names": channel_names,
            "types": channel_types,
            "units": ["V"] * len(channel_names),
            "bads": [name for name in raw.info.get("bads", []) if name in channel_names],
            "eeg_only": all(channel_type == "eeg" for channel_type in channel_types),
        },
        "reference": {
            "custom_ref_applied": _json_value(raw.info.get("custom_ref_applied")),
            "projections": [_projection_payload(projection) for projection in raw.info.get("projs", [])],
        },
        "aggregation": {
            "domain": "time",
            "method": "arithmetic_mean",
            "repetition_count": repetition_count,
            "signed_values_preserved": True,
        },
        "crop": _json_value(dict(crop)),
        "resolved_protocol": _json_value(dict(resolved_protocol)),
    }


def _projection_payload(projection: Mapping[str, Any]) -> dict[str, Any]:
    kind = projection.get("kind")
    return {
        "description": str(projection.get("desc") or ""),
        "active": bool(projection.get("active", False)),
        "kind": int(kind) if kind is not None else None,
    }


def _atomic_write_raw_fif(destination: Path, raw: Any) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix="_raw.fif",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    temporary_path.unlink(missing_ok=True)
    try:
        raw.save(
            str(temporary_path),
            overwrite=True,
            proj=False,
            fmt="single",
            verbose=False,
        )
        with temporary_path.open("r+b") as stream:
            os.fsync(stream.fileno())
        _replace_file(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _atomic_write_json(destination: Path, payload: Mapping[str, Any]) -> None:
    serialized = json.dumps(
        _json_value(dict(payload)),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        _replace_file(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_path(root: Path, *parts: str) -> Path:
    canonical_root = _canonical_resolved_path(root)
    target = _canonical_resolved_path(canonical_root.joinpath(*parts))
    try:
        target.relative_to(canonical_root)
    except ValueError as exc:
        raise ValueError(f"Refusing source-ready output outside the project root: {target}") from exc
    return target


def _relative_project_path(root: Path, path: Path) -> str:
    canonical_root = _canonical_resolved_path(root)
    resolved = _canonical_resolved_path(path)
    try:
        return resolved.relative_to(canonical_root).as_posix()
    except ValueError as exc:
        raise ValueError(f"Refusing source-ready output outside the project root: {resolved}") from exc


def source_ready_project_relative_path(
    project_root: str | Path,
    path: str | Path,
) -> str:
    """Return a confined project-relative source-ready path.

    Windows may expose the same long path either as ``D:\\...`` or with the
    extended-length ``\\\\?\\D:\\...`` prefix. Both inputs are canonicalized
    before the structural containment check so equivalent path spellings do
    not create false outside-project failures.
    """

    return _relative_project_path(Path(project_root), Path(path))


def _canonical_resolved_path(path: str | Path) -> Path:
    """Resolve a path and normalize ordinary Windows extended namespaces."""

    resolved = Path(path).resolve()
    if os.name != "nt":
        return resolved
    value = os.fspath(resolved)
    extended_unc_prefix = "\\\\?\\UNC\\"
    extended_path_prefix = "\\\\?\\"
    if value.casefold().startswith(extended_unc_prefix.casefold()):
        value = "\\\\" + value[len(extended_unc_prefix) :]
    elif value.startswith(extended_path_prefix):
        ordinary_path = value[len(extended_path_prefix) :]
        if re.match(r"^[A-Za-z]:[\\\\/]", ordinary_path):
            value = ordinary_path
    return Path(value)


def _windows_filesystem_path(path: str | Path) -> str:
    """Return an absolute path suitable for long Windows filesystem calls."""

    value = os.path.abspath(os.fspath(path))
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    if re.match(r"^[A-Za-z]:[\\\\/]", value):
        return "\\\\?\\" + value
    return value


def _replace_file(source: str | Path, destination: str | Path) -> None:
    """Atomically replace a file, tolerating brief Windows scanner locks."""

    for attempt in range(5):  # noqa: PERF203 - replacement failures are transient on Windows.
        try:
            os.replace(
                _windows_filesystem_path(source),
                _windows_filesystem_path(destination),
            )
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def _path_component(value: Any, *, field: str) -> str:
    text = str(value).strip()
    if not text or text in {".", ".."}:
        raise ValueError(f"{field} must be a non-empty path component")
    if _INVALID_WINDOWS_COMPONENT.search(text) or text.endswith((".", " ")):
        raise ValueError(f"{field} contains characters that are unsafe in a project path: {text!r}")
    if text.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{field} is a reserved Windows path name: {text!r}")
    return text


def _optional_path_component(value: Any, *, field: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _path_component(value, field=field)


def _stable_identifier(value: Any, *, field: str) -> str:
    text = str(value).strip()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip(".-")
    return _path_component(text, field=field)


def _optional_identifier(value: Any, *, field: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return _stable_identifier(value, field=field)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.generic):
        return _json_value(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, np.ndarray):
        return [_json_value(item) for item in value.tolist()]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


__all__ = [
    "SOURCE_READY_TIME_DOMAIN_FORMAT",
    "SOURCE_READY_TIME_DOMAIN_MANIFEST_FOLDER",
    "SOURCE_READY_TIME_DOMAIN_PARTICIPANT_MANIFEST_FORMAT",
    "SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT",
    "SourceReadyTimeDomainArtifact",
    "SourceReadyTimeDomainExportResult",
    "source_ready_project_relative_path",
    "write_source_ready_time_domain_derivatives",
]

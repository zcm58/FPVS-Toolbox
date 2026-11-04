"""Transactional project source bundles and read-only current-result discovery.

Numerical writers serialize into a private sibling directory. The receipt binds
every published file to one build; only the short directory/freshness commit
holds the existing cross-process project-manifest lock.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import fields, is_dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from Main_App.processing.artifact_freshness import (
    canonical_artifact_path,
    load_artifact_freshness_registry,
    mark_artifact_current,
    preserve_artifact_for_rebuild,
    require_current_artifact,
)
from Main_App.processing.processing_ledger import load_ledger
from Main_App.projects import (
    normalize_manual_excluded_participant_conditions,
    project_group_context,
    project_manifest_transaction,
)
from Tools.LORETA_Visualizer.prepared_payload_validator import (
    validate_prepared_source_manifest_json,
    validate_prepared_source_payload_json,
)
from Tools.LORETA_Visualizer.source_producers.project_inputs import project_source_participant_selection

logger = logging.getLogger(__name__)
SOURCE_BUNDLE_RECEIPT = "source_build_receipt.json"
SOURCE_BUNDLE_FORMAT = "fpvs-source-build-v1"
SOURCE_ARTIFACT_MANIFESTS = {
    "l2_mne_source_psd": "project_l2_mne_hauk_source_psd_manifest.json",
    "eloreta_volume_source_psd": "project_eloreta_volume_hauk_source_psd_manifest.json",
}


def _inside(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        raise ValueError("Source bundle paths must stay below the active project root.")
    return resolved


def _digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _identity_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(encoded).hexdigest()


def source_project_cohort_snapshot(
    root: Path, *, include_flagged_subjects: bool, project: Any = None,
) -> dict[str, Any]:
    """Capture only source cohort inputs, excluding volatile artifact/UI state."""
    if project is None:
        manifest = json.loads((root / "project.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("Project manifest must contain an object.")
        project = SimpleNamespace(
            project_root=root, groups=manifest.get("groups", {}),
            participants=manifest.get("participants", {}), event_map=manifest.get("event_map", {}),
            preprocessing=manifest.get("preprocessing", {}),
        )
    context = project_group_context(project)
    preprocessing = getattr(project, "preprocessing", None) or {}
    selection = project_source_participant_selection(
        root, include_flagged_subjects=include_flagged_subjects, project_preprocessing=preprocessing,
    )
    ledger_keys = (
        "participant_id", "group_id", "status", "condition_completeness",
        "missing_condition_labels", "source_derivative_status", "source_derivative_warning",
        "expected_outputs", "processing_fingerprint", "processing_fingerprint_version",
    )
    return {
        "groups": [{"id": row.group_id, "label": row.label, "folder": row.folder_name} for row in context.groups],
        "participants": [{"id": row.participant_id, "group_id": row.group_id} for row in context.participants],
        "event_map": dict(getattr(project, "event_map", None) or {}),
        "include_flagged_subjects": bool(include_flagged_subjects),
        "excluded_subjects": list(selection.excluded_subjects),
        "flagged_subjects": list(selection.flagged_subjects),
        "manual_condition_exclusions": normalize_manual_excluded_participant_conditions(
            preprocessing.get("manual_excluded_participant_conditions")
        ),
        "ledger_eligibility": {
            str(key): {field: value.get(field) for field in ledger_keys}
            for key, value in load_ledger(root).get("entries", {}).items()
            if isinstance(value, Mapping)
        },
    }


def _validate_cohort_snapshot(root: Path, identity: Mapping[str, Any]) -> None:
    common = identity.get("common_inputs", {})
    if (root / "project.json").is_file():
        snapshot = common.get("cohort_snapshot")
        if not isinstance(snapshot, dict) or snapshot != source_project_cohort_snapshot(
            root, include_flagged_subjects=bool(snapshot.get("include_flagged_subjects", False)),
        ):
            raise ValueError("Project groups, condition availability, or QC exclusions changed; rebuild source maps.")


def _validate_input_files(root: Path, identity: Mapping[str, Any]) -> None:
    _validate_cohort_snapshot(root, identity)
    common = identity.get("common_inputs", {})
    for row in common.get("inputs", []):
        for key in ("fif", "sidecar", "participant_manifest"):
            if _digest(_inside(root, root / row[key])) != row[f"{key}_sha256"]:
                raise ValueError("A source-ready input changed after source calculation.")


def source_bundle_identity(
    *,
    project_inputs: Any,
    harmonic_metadata: Mapping[str, Any],
    include_flagged_subjects: bool,
    method_id: str,
    method_options: Mapping[str, Any],
    cohort_snapshot: Mapping[str, Any],
    build_batch_id: str | None = None,
) -> dict[str, Any]:
    """Describe validated inputs without recomputing any scientific quantities."""
    root = Path(project_inputs.project_root).resolve()
    records = [
        {
            "participant_id": row.participant_id,
            "condition_id": row.condition_id,
            "group_id": row.group_id,
            "fif": row.fif_path.relative_to(root).as_posix(),
            "fif_sha256": row.fif_sha256,
            "sidecar": row.sidecar_path.relative_to(root).as_posix(),
            "sidecar_sha256": row.sidecar_sha256,
            "participant_manifest": row.manifest_path.relative_to(root).as_posix(),
            "participant_manifest_sha256": _digest(row.manifest_path),
        }
        for row in project_inputs.records
    ]
    records.sort(key=lambda row: (str(row["group_id"]), row["condition_id"], row["participant_id"]))
    common = {
        "processing_fingerprint": project_inputs.processing_fingerprint,
        "processing_fingerprint_version": project_inputs.processing_fingerprint_version,
        "selected_harmonics_hz": list(harmonic_metadata["selected_harmonics_hz"]),
        "selection_fingerprint": harmonic_metadata.get("selection_fingerprint"),
        "sfreq_hz": project_inputs.sfreq_hz,
        "n_times": project_inputs.n_times,
        "include_flagged_subjects": bool(include_flagged_subjects),
        "cohort_snapshot": dict(cohort_snapshot),
        "inputs": records,
    }
    return {
        "run_id": uuid4().hex,
        "created_ns": time.time_ns(),
        "batch_id": build_batch_id or uuid4().hex,
        "method_id": method_id,
        "selection_fingerprint": harmonic_metadata.get("selection_fingerprint"),
        "common_inputs": common,
        "common_input_fingerprint": _identity_digest(common),
        "method_options": dict(method_options),
        "method_fingerprint": _identity_digest({"method_id": method_id, "options": method_options}),
    }


def _rebase_result(value: Any, stage: Path, target: Path) -> Any:
    if isinstance(value, Path):
        return target / value.relative_to(stage) if value.is_relative_to(stage) else value
    if is_dataclass(value):
        # Rebase only output contracts. Input/model arrays remain untouched.
        updates = {}
        for field in fields(value):
            item = getattr(value, field.name)
            if isinstance(item, Path) or field.name in {"producer_result", "payloads", "manifest_validation", "conditions"}:
                updates[field.name] = _rebase_result(item, stage, target)
        return replace(value, **updates)
    if isinstance(value, tuple):
        return tuple(_rebase_result(item, stage, target) for item in value)
    return value


def _rebase_text(value: str, stage: Path, target: Path) -> str:
    return value.replace(str(stage), str(target)).replace(stage.as_posix(), target.as_posix())


def _rebase_json(value: Any, stage: Path, target: Path) -> Any:
    if isinstance(value, str):
        return _rebase_text(value, stage, target)
    if isinstance(value, dict):
        return {key: _rebase_json(item, stage, target) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase_json(item, stage, target) for item in value]
    return value


class SourceBundlePublication:
    """One staged method build; call publish once after every writer succeeds."""

    def __init__(self, root: Path, target: Path, artifact_id: str, stage: Path) -> None:
        self.root = root
        self.target = target
        self.artifact_id = artifact_id
        self.output_dir = stage
        manifest = target / SOURCE_ARTIFACT_MANIFESTS[artifact_id]
        self.previous_manifest_digest = _digest(manifest) if manifest.is_file() else None

    def publish(
        self,
        result: Any,
        *,
        identity: Mapping[str, Any],
        cancellation_callback: Callable[[], None] | None = None,
    ) -> Any:
        stage = self.output_dir
        manifest = Path(result.manifest_path)
        # Reports include absolute output paths as well as relative file names.
        # Rewrite their structured strings before receipt hashing, never afterward.
        for path in stage.rglob("*"):
            _inside(stage, path)
            if path.is_file() and path.suffix.lower() == ".json":
                document = json.loads(path.read_text(encoding="utf-8"))
                path.write_text(
                    json.dumps(_rebase_json(document, stage, self.target), indent=2, allow_nan=False) + "\n",
                    encoding="utf-8",
                )
            elif path.is_file() and path.suffix.lower() in {".md", ".csv"}:
                path.write_text(_rebase_text(path.read_text(encoding="utf-8"), stage, self.target), encoding="utf-8")
        spec = validate_prepared_source_manifest_json(manifest, require_payload_files=True)
        for row in spec.conditions:
            validate_prepared_source_payload_json(row.payload_path)
        # Add run identity to the manifest; the receipt hashes its final bytes.
        document = json.loads(manifest.read_text(encoding="utf-8"))
        document.setdefault("metadata", {})["source_build"] = dict(identity)
        manifest.write_text(json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        entries = []
        for path in sorted(stage.rglob("*")):
            _inside(stage, path)
            if path.is_symlink():
                raise ValueError("Source bundles cannot contain symbolic links.")
            if path.is_file():
                entries.append({"file": path.relative_to(stage).as_posix(), "sha256": _digest(path)})
        receipt = {"format": SOURCE_BUNDLE_FORMAT, "manifest": manifest.name, **identity, "files": entries}
        (stage / SOURCE_BUNDLE_RECEIPT).write_text(
            json.dumps(receipt, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        validate_source_bundle(manifest)
        _validate_input_files(self.root, identity)
        if cancellation_callback is not None:
            cancellation_callback()
        with project_manifest_transaction(self.root / "project.json"):
            # Recheck small cohort/QC metadata after hashing and the final cancel
            # callback; derivative and payload hashing stays outside this lock.
            _validate_cohort_snapshot(self.root, identity)
            final_manifest = self.target / manifest.name
            previous = _digest(final_manifest) if final_manifest.is_file() else None
            if previous != self.previous_manifest_digest:
                raise RuntimeError("Source output changed during this build; rebuild from the latest project state.")
            fingerprint = str(identity.get("selection_fingerprint") or "")
            managed = (
                bool(fingerprint)
                and (self.root / "project.json").is_file()
                and self.target == canonical_artifact_path(self.root, self.artifact_id)
            )
            registry = load_artifact_freshness_registry(self.root)
            if managed and registry.selection_fingerprint != fingerprint:
                raise RuntimeError("The accepted harmonic selection changed during source generation.")
            if (self.root / "project.json").is_file():
                with preserve_artifact_for_rebuild(
                    self.root, self.artifact_id, self.target, registry.selection_fingerprint
                ) as archived:
                    stage.replace(self.target)
                    if managed:
                        mark_artifact_current(
                            self.root, self.artifact_id, self.target, fingerprint, archived_path=archived
                        )
            else:
                # Isolated API/test callers may not have a managed project manifest.
                backup = self.target.with_name(f".{self.target.name}.previous-{uuid4().hex}")
                had_previous = self.target.exists()
                if had_previous:
                    self.target.replace(backup)
                try:
                    stage.replace(self.target)
                except BaseException:
                    if had_previous:
                        backup.replace(self.target)
                    raise
                if had_previous:
                    shutil.rmtree(_inside(self.root, backup))
        return _rebase_result(result, stage, self.target)


@contextmanager
def stage_source_bundle(
    project_root: Path, output_dir: Path, artifact_id: str
) -> Iterator[SourceBundlePublication]:
    root = Path(project_root).resolve()
    target = _inside(root, Path(output_dir))
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)).resolve()
    try:
        yield SourceBundlePublication(root, target, artifact_id, stage)
    finally:
        if stage.exists():
            shutil.rmtree(_inside(root, stage))


def validate_source_bundle(manifest_path: Path) -> dict[str, Any]:
    """Verify a receipt and every final byte; callers use a worker for large bundles."""
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    receipt = json.loads((root / SOURCE_BUNDLE_RECEIPT).read_text(encoding="utf-8"))
    if (not isinstance(receipt, dict) or receipt.get("format") != SOURCE_BUNDLE_FORMAT
            or receipt.get("manifest") != manifest_path.name):
        raise ValueError("Source bundle receipt does not match its manifest.")
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Source bundle receipt has no files.")
    names = set()
    for entry in files:
        name = entry["file"]
        if not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("Source bundle file paths must be relative and contained.")
        if name in names:
            raise ValueError("Source bundle receipt contains duplicate files.")
        names.add(name)
        path = _inside(root, root / name)
        if _digest(path) != entry["sha256"]:
            raise ValueError(f"Source bundle checksum mismatch: {name}")
    if manifest_path.name not in names:
        raise ValueError("Source bundle receipt does not include its manifest.")
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("Source manifest must contain an object.")
    identity = document.get("metadata", {}).get("source_build", {})
    if not identity or any(identity.get(key) != receipt.get(key) for key in identity):
        raise ValueError("Source bundle identity differs between manifest and receipt.")
    if receipt.get("method_id") != document.get("metadata", {}).get("producer_method"):
        raise ValueError("Source bundle method differs from the prepared manifest.")
    for row in document.get("conditions", []):
        if row.get("file") not in names:
            raise ValueError("Source bundle receipt omits a prepared payload.")
    return receipt


def _current_source_bundle(project_root: Path, artifact_id: str) -> tuple[Path, dict[str, Any], str] | None:
    try:
        root = Path(project_root).resolve()
        target = canonical_artifact_path(root, artifact_id)
        manifest = target / SOURCE_ARTIFACT_MANIFESTS[artifact_id]
        receipt_path = target / SOURCE_BUNDLE_RECEIPT
        with project_manifest_transaction(root / "project.json"):
            record = require_current_artifact(root, artifact_id, target)
            receipt_digest = _digest(receipt_path)
        # Potentially large input/payload hashing never holds the manifest lock.
        receipt = validate_source_bundle(manifest)
        if receipt.get("selection_fingerprint") != record.built_from_selection_fingerprint:
            raise ValueError("Source bundle was built from a different harmonic selection.")
        _validate_input_files(root, receipt)
        with project_manifest_transaction(root / "project.json"):
            current = require_current_artifact(root, artifact_id, target)
            _validate_cohort_snapshot(root, receipt)
            if (current != record or _digest(receipt_path) != receipt_digest):
                raise ValueError("Source bundle changed while it was being verified.")
        return manifest, receipt, receipt_digest
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        logger.info("source_bundle_not_current artifact=%s reason=%s", artifact_id, exc)
        return None


def current_source_manifest(project_root: Path, artifact_id: str) -> Path | None:
    """Discover only verified managed output; explicit historical import is separate."""
    bundle = _current_source_bundle(project_root, artifact_id)
    return bundle[0] if bundle is not None else None


def current_source_manifest_paths(project_root: Path) -> tuple[Path, ...]:
    """Return a coherent latest batch, excluding previous unsuccessful siblings."""
    current = [
        bundle for artifact_id in SOURCE_ARTIFACT_MANIFESTS
        if (bundle := _current_source_bundle(project_root, artifact_id)) is not None
    ]
    if not current:
        return ()
    try:
        with project_manifest_transaction(Path(project_root).resolve() / "project.json"):
            # Do not combine snapshots if one method changed while checking its sibling.
            for path, receipt, digest in current:
                _validate_cohort_snapshot(Path(project_root).resolve(), receipt)
                if _digest(path.parent / SOURCE_BUNDLE_RECEIPT) != digest:
                    return ()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError):
        return ()
    newest = max(current, key=lambda item: int(item[1].get("created_ns", 0)))[1]
    return tuple(
        path for path, receipt, _digest_value in current
        if receipt.get("batch_id") == newest.get("batch_id")
        and receipt.get("common_input_fingerprint") == newest.get("common_input_fingerprint")
    )

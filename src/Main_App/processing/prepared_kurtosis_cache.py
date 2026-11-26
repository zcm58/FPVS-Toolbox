"""Project-owned exact checkpoints before interpolation and final reference.

The cache stores numerical state and evidence, never interpolation approval.
Unavailable, stale, or damaged artifacts are ordinary cache misses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from io import UnsupportedOperation
import json
import logging
import math
import os
from pathlib import Path
import tempfile
import re
from typing import BinaryIO, NamedTuple

import mne
import numpy as np
import scipy
from threadpoolctl import threadpool_info

from Main_App.io.numpy_companion import open_verified_npz_with_buffer_status
from Main_App.io.recorded_eeg_geometry import read_raw_eeg_geometry
from Main_App.processing.kurtosis_qc import (
    CURRENT_KURTOSIS_CORROBORATOR_REGISTRY, KURTOSIS_AUTHORITY_POLICY_VERSION,
    KURTOSIS_QC_METHOD_VERSION, KurtosisQCEvidence,
)
from Main_App.processing.prepared_raw_codec import decode_state, encode_state, raw_state, restore_raw
from Main_App.workers.review_resource_budget import admitted_checkpoint_snapshot

logger = logging.getLogger(__name__)
CHECKPOINT_VERSION = "prepared_kurtosis_float64_v2_native_threads"
_PREFIX_STATE_KEYS = (
    "_fpvs_initial_ref_ok", "_fpvs_initial_ref_pair",
    "_fpvs_fft_multinotch_requested_centers_hz", "_fpvs_fft_multinotch_applied_centers_hz",
    "_fpvs_fft_multinotch_skipped_centers", "_fpvs_realized_analysis_span_plan",
    "_fpvs_analysis_scoring_sample_count", "_fpvs_geometry",
    "_fpvs_retained_scalp_channels", "_fpvs_retained_scalp_set_fingerprint",
)


class _BidsImportDiagnostics(NamedTuple):
    identity_seconds: float
    conversion_seconds: float
    reused: bool


def _import_diagnostics(metadata: object) -> _BidsImportDiagnostics | None:
    # Only this producer schema declares the three fields as per-load diagnostics.
    if not isinstance(metadata, dict) or metadata.get("version") != "bids_import_v1":
        return None
    if not all(isinstance(metadata.get(key), str) and metadata[key] for key in ("representation", "path")):
        return None
    identity_seconds = metadata.get("identity_seconds")
    conversion_seconds = metadata.get("conversion_seconds")
    reused = metadata.get("reused")
    if type(reused) is not bool or not all(
        type(value) is float and math.isfinite(value) and value >= 0
        for value in (identity_seconds, conversion_seconds)
    ):
        return None
    return _BidsImportDiagnostics(identity_seconds, conversion_seconds, reused)


@dataclass(frozen=True)
class CheckpointIdentity:
    project_root: Path
    folder: Path
    source: Path
    source_stat: tuple[int, int, int]
    key: str
    source_sha256: str = ""
    bids_import_diagnostics: _BidsImportDiagnostics | None = field(default=None, compare=False, repr=False)
    temporary_bids_attributes: dict | None = field(default=None, compare=False, repr=False)
    samples_sha256: str = field(default="", compare=False, repr=False)


@dataclass(frozen=True)
class PreparedCheckpoint:
    raw: mne.io.BaseRaw
    params: dict
    evidence: KurtosisQCEvidence
    original_sfreq: float


def _stat(path: Path) -> tuple[int, int, int]:
    stat = path.stat()
    return int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_ctime_ns)


def _cancelled(params: dict) -> bool:
    callback = params.get("_fpvs_kurtosis_checkpoint_should_cancel")
    return bool(callback()) if callable(callback) else False


def _sample_digest(raw, params: dict) -> str:
    """Hash the actual loaded signal without another recording-sized copy."""
    data = raw._data
    if data.dtype != np.dtype(np.float64):
        raise ValueError("Prepared checkpoints require float64 source samples.")
    digest = hashlib.sha256()
    for channel in data:
        for start in range(0, channel.size, 131_072):
            if _cancelled(params):
                raise ValueError("Kurtosis preparation cancelled.")
            block = np.ascontiguousarray(channel[start:start + 131_072])
            digest.update(memoryview(block).cast("B"))
    return digest.hexdigest()


def _contained(identity: CheckpointIdentity) -> bool:
    return identity.folder.resolve().is_relative_to(identity.project_root)


def _native_execution_identity() -> tuple | None:
    """Bind exact prepared samples to the loaded BLAS reduction policy.

    The library thread count can change FIR coefficient bytes even when all
    scientific parameters agree. Inspect it without changing the caller's
    process-wide numerical configuration; unknown policies disable reuse.
    """
    try:
        pools = []
        for pool in threadpool_info():
            if pool.get("user_api") != "blas":
                continue
            threads = pool.get("num_threads")
            if type(threads) is not int or threads < 1:
                return None
            required = tuple(pool.get(key) for key in (
                "filepath", "prefix", "internal_api", "version",
            ))
            if not all(isinstance(value, str) and value for value in required):
                return None
            pools.append((*required, pool.get("threading_layer"),
                          pool.get("architecture"), threads))
        return tuple(sorted(pools, key=repr)) if pools else None
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        logger.debug("prepared_kurtosis_native_identity_unavailable", exc_info=True)
        return None


def checkpoint_identity(raw, params: dict, preprocessing_fingerprint: str) -> CheckpointIdentity | None:
    if not params.get("kurtosis_screening_enabled", True):
        return None
    if params.get("enable_kurtosis_checkpoint_cache", True) is not True:
        return None
    project_root = params.get("project_root")
    source_path = params.get("_fpvs_source_file_path")
    if not project_root or not source_path or not params.get("reject_thresh"):
        return None
    try:
        native_identity = _native_execution_identity()
        if native_identity is None:
            return None
        root, source = Path(project_root).resolve(), Path(source_path).resolve()
        before = _stat(source)
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if _stat(source) != before:
            return None
        source_id = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:24]
        folder = root / ".fpvs_cache" / "prepared_kurtosis" / source_id
        if not folder.resolve().is_relative_to(root):
            return None
        geometry = read_raw_eeg_geometry(raw)
        metadata_arrays = {}
        source_state = raw_state(raw)
        attributes = source_state["attributes"]
        bids_metadata = attributes.get("_fpvs_bids_import")
        diagnostics = _import_diagnostics(bids_metadata)
        temporary_bids_attributes = None
        if diagnostics is not None:
            # raw_state creates this attributes dictionary; the original Raw and
            # the full state saved in the checkpoint retain their load provenance.
            import_identity = {
                key: value for key, value in bids_metadata.items() if key not in diagnostics._fields
            }
            if bids_metadata.get("temporary") is True and bids_metadata.get("import_key"):
                # A new scratch path represents the same verified recording on
                # the next load. The import key and sample/source hashes still bind it.
                temporary_bids_attributes = {"_fpvs_bids_import": bids_metadata}
                if "_filenames" in attributes:
                    temporary_bids_attributes["_filenames"] = attributes.pop("_filenames")
                import_identity.pop("path", None)
                import_identity.pop("dataset_root", None)
            attributes["_fpvs_bids_import"] = import_identity
        metadata_state = encode_state({
            "raw": source_state,
            "max_idx_keep": params.get("max_idx_keep"),
            "source_plan": params.get("_fpvs_source_analysis_span_plan"),
            "require_analysis_spans": params.get("_fpvs_require_analysis_spans", False),
        }, metadata_arrays)
        metadata_identity = {
            "state": metadata_state,
            "arrays": {key: {"dtype": array.dtype.str, "shape": array.shape,
                              "sha256": hashlib.sha256(np.ascontiguousarray(array).tobytes()).hexdigest()}
                       for key, array in metadata_arrays.items()},
        }
        identity = {
            "version": CHECKPOINT_VERSION, "source_path": str(source), "source_stat": before,
            "source_sha256": digest, "mne_version": mne.__version__,
            "numpy_version": np.__version__, "scipy_version": scipy.__version__,
            "native_execution_identity": native_identity,
            "method_version": KURTOSIS_QC_METHOD_VERSION,
            "authority_version": KURTOSIS_AUTHORITY_POLICY_VERSION,
            "registry_fingerprint": CURRENT_KURTOSIS_CORROBORATOR_REGISTRY.fingerprint,
            "preprocessing": preprocessing_fingerprint,
            "channels": raw.ch_names, "source_sfreq": float(raw.info["sfreq"]),
            "source_samples": int(raw.n_times), "source_first_samp": int(raw.first_samp),
            "direct_bads": sorted(raw.info.get("bads", [])), "geometry": geometry,
            "source_metadata": metadata_identity,
            "current_samples_sha256": _sample_digest(raw, params),
        }
        if diagnostics is not None:
            # Keep unrecognized/incomplete provenance and older keys in separate namespaces.
            identity["bids_import_diagnostics_policy"] = "current_load_v1"
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return CheckpointIdentity(
            root, folder, source, before, hashlib.sha256(encoded).hexdigest(), digest,
            diagnostics, temporary_bids_attributes, identity["current_samples_sha256"],
        )
    except (OSError, ValueError, TypeError, RuntimeError):
        logger.debug("prepared_kurtosis_cache_identity_unavailable", exc_info=True)
        return None


class _CheckpointNeedsStreaming(Exception):
    """Retry the archived bytes with the original streaming validator."""


class _CheckpointChecksumMismatch(ValueError):
    """The pointer references other bytes."""


def _read_checkpoint(stream: BinaryIO, identity: CheckpointIdentity, size_bytes: int, digest: str, buffer_limit: int):
    before = os.fstat(stream.fileno()) if buffer_limit else None
    checksum_error = _CheckpointChecksumMismatch("Checkpoint checksum mismatch.")
    with open_verified_npz_with_buffer_status(
        stream, size_bytes, digest, checksum_error, buffer_limit,
    ) as (archive, buffered):
        # Historical compressed archives can expand beyond the admitted
        # scratch. Release the snapshot before running their normal decoder.
        if buffered and sum(member.file_size for member in archive.zip.infolist()) > size_bytes:
            raise _CheckpointNeedsStreaming
        metadata = json.loads(str(archive["metadata_json"].item()))
        if metadata["version"] != CHECKPOINT_VERSION or metadata["key"] != identity.key:
            return None
        state = decode_state(metadata["state"], archive)
        evidence = state["evidence"]
        if not isinstance(evidence, KurtosisQCEvidence) or evidence.fingerprint != metadata["evidence_fingerprint"]:
            return None
        samples = archive["samples"]
        if buffered and before is not None:
            after = os.fstat(stream.fileno())
            if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns,
            ):
                raise _CheckpointNeedsStreaming
        return restore_raw(samples, state["raw"]), state


def load_checkpoint(identity: CheckpointIdentity | None, *, should_cancel=None,
                    source_sample_bytes: int = 0, settings: dict | None = None) -> PreparedCheckpoint | None:
    if identity is None or (should_cancel and should_cancel()):
        return None
    raw = None
    try:
        if not _contained(identity):
            return None
        manifest_path = identity.folder / "latest.json"
        if manifest_path.resolve().parent != identity.folder.resolve():
            return None
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("version") != CHECKPOINT_VERSION or manifest.get("key") != identity.key:
            return None
        name, digest = manifest["path"], manifest["sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or name != f"{identity.key}.{digest[:20]}.npz":
            return None
        path = identity.folder / name
        if path.resolve().parent != identity.folder.resolve():
            return None
        size_bytes = path.stat().st_size
        if size_bytes != manifest["size_bytes"]:
            return None
        buffer_limit = admitted_checkpoint_snapshot(size_bytes, source_sample_bytes, settings)
        with path.open("rb") as stream:
            for limit in ((buffer_limit, 0) if buffer_limit else (0,)):
                try:
                    restored = _read_checkpoint(stream, identity, size_bytes, digest, limit)
                    break
                except (MemoryError, OSError, _CheckpointNeedsStreaming):
                    if not limit:
                        raise
                    stream.seek(0)
        if restored is None:
            return None
        raw, state = restored
        evidence = state["evidence"]
        if _stat(identity.source) != identity.source_stat or (should_cancel and should_cancel()):
            raw.close()
            return None
        if read_raw_eeg_geometry(raw) != state["params"]["_fpvs_geometry"]:
            raw.close()
            return None
        if evidence.scoring_scope.analysis_span_fingerprint != state["params"]["_fpvs_realized_analysis_span_plan"]["fingerprint"]:
            raw.close()
            return None
        if identity.bids_import_diagnostics is not None:
            recorded = getattr(raw, "_fpvs_bids_import", None)
            if _import_diagnostics(recorded) is None:
                raw.close()
                return None
            raw._fpvs_bids_import = {**recorded, **identity.bids_import_diagnostics._asdict()}
        if identity.temporary_bids_attributes is not None:
            for key, value in identity.temporary_bids_attributes.items():
                setattr(raw, key, value)
        return PreparedCheckpoint(raw, state["params"], evidence, state["original_sfreq"])
    except _CheckpointChecksumMismatch:
        return None
    except Exception:  # Optional cache boundary: any decoding failure must recompute normally.
        # Cache decoding must never convert a damaged/unsupported artifact into
        # processing failure or skip the ordinary scientific validation path.
        logger.debug("prepared_kurtosis_cache_miss", exc_info=True)
        if raw is not None:
            raw.close()
        return None


class _CheckpointArchiveWriter:
    """Hash the final ZIP bytes as they are written in order."""

    def __init__(self, stream: BinaryIO):
        self._stream = stream
        self._digest = hashlib.sha256()

    def write(self, data: bytes | bytearray | memoryview) -> int:
        block = memoryview(data)
        written = self._stream.write(block)
        if written != block.nbytes:
            raise OSError("Incomplete checkpoint archive write.")
        self._digest.update(block)
        return written

    def flush(self) -> None:
        self._stream.flush()

    def read(self, _size: int = -1) -> bytes:
        # NumPy recognizes a file-like object by its read method. Without
        # seek/tell, ZIP appends data descriptors instead of rewriting headers.
        raise UnsupportedOperation("Checkpoint archive writer is write-only.")

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def save_checkpoint(identity: CheckpointIdentity | None, raw, params: dict, evidence: KurtosisQCEvidence, original_sfreq: float) -> bool:
    if identity is None:
        return False
    temporary = None
    manifest_temporary = None
    unpublished_target = None
    try:
        if not _contained(identity) or _stat(identity.source) != identity.source_stat or _cancelled(params):
            return False
        if raw._data.dtype != np.dtype(np.float64):
            return False
        # The caller exclusively owns this loaded Raw until the synchronous
        # checkpoint write finishes; avoid a second recording-sized copy.
        arrays = {"samples": raw._data}
        state = encode_state({
            "raw": raw_state(raw), "evidence": evidence, "original_sfreq": original_sfreq,
            "params": {key: params[key] for key in _PREFIX_STATE_KEYS if key in params},
        }, arrays)
        arrays["metadata_json"] = np.asarray(json.dumps({
            "version": CHECKPOINT_VERSION, "key": identity.key,
            "evidence_fingerprint": evidence.fingerprint, "state": state,
        }, separators=(",", ":"), allow_nan=False))
        identity.folder.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="wb", dir=identity.folder, prefix=".pending-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            writer = _CheckpointArchiveWriter(stream)
            np.savez(writer, **arrays)
            stream.flush()
            os.fsync(stream.fileno())
            digest = writer.hexdigest()
        name = f"{identity.key}.{digest[:20]}.npz"
        target = identity.folder / name
        if not _contained(identity) or _cancelled(params):
            return False
        if not target.exists():
            unpublished_target = target
        os.replace(temporary, target)
        temporary = None
        manifest = {"version": CHECKPOINT_VERSION, "key": identity.key, "path": name,
                    "sha256": digest, "size_bytes": target.stat().st_size}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=identity.folder, prefix=".manifest-", suffix=".tmp", delete=False) as stream:
            manifest_temporary = Path(stream.name)
            json.dump(manifest, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        if _stat(identity.source) != identity.source_stat or _cancelled(params):
            return False
        os.replace(manifest_temporary, identity.folder / "latest.json")
        manifest_temporary = None
        unpublished_target = None
        # Retain only one complete checkpoint per source recording. Restrict
        # deletion to our generated 64hex.20hex.npz artifact names.
        for previous in identity.folder.glob("*.npz"):
            if previous != target and re.fullmatch(r"[0-9a-f]{64}\.[0-9a-f]{20}\.npz", previous.name):
                try:
                    previous.unlink(missing_ok=True)
                except OSError:
                    logger.debug("prepared_kurtosis_cache_retention_cleanup_failed", exc_info=True)
        return True
    except Exception:  # Optional cache boundary: publication failures must not fail EEG processing.
        logger.debug("prepared_kurtosis_cache_write_unavailable", exc_info=True)
        return False
    finally:
        if unpublished_target is not None:
            try:
                unpublished_target.unlink(missing_ok=True)
            except OSError:
                logger.debug("prepared_kurtosis_cache_unpublished_cleanup_failed", exc_info=True)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                logger.debug("prepared_kurtosis_cache_temporary_cleanup_failed", exc_info=True)
        if manifest_temporary is not None:
            try:
                manifest_temporary.unlink(missing_ok=True)
            except OSError:
                logger.debug("prepared_kurtosis_cache_manifest_cleanup_failed", exc_info=True)

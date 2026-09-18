"""Project-owned exact checkpoints before interpolation and final reference.

The cache stores numerical state and evidence, never interpolation approval.
Unavailable, stale, or damaged artifacts are ordinary cache misses.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import re

import mne
import numpy as np
import scipy

from Main_App.io.eeg_geometry import read_raw_biosemi64_geometry
from Main_App.processing.kurtosis_qc import (
    CURRENT_KURTOSIS_CORROBORATOR_REGISTRY, KURTOSIS_AUTHORITY_POLICY_VERSION,
    KURTOSIS_QC_METHOD_VERSION, KurtosisQCEvidence,
)
from Main_App.processing.prepared_raw_codec import decode_state, encode_state, raw_state, restore_raw

logger = logging.getLogger(__name__)
CHECKPOINT_VERSION = "prepared_kurtosis_float64_v1"
_PREFIX_STATE_KEYS = (
    "_fpvs_initial_ref_ok", "_fpvs_initial_ref_pair",
    "_fpvs_fft_multinotch_requested_centers_hz", "_fpvs_fft_multinotch_applied_centers_hz",
    "_fpvs_fft_multinotch_skipped_centers", "_fpvs_realized_analysis_span_plan",
    "_fpvs_analysis_scoring_sample_count", "_fpvs_geometry",
    "_fpvs_retained_scalp_channels", "_fpvs_retained_scalp_set_fingerprint",
)


@dataclass(frozen=True)
class CheckpointIdentity:
    project_root: Path
    folder: Path
    source: Path
    source_stat: tuple[int, int, int]
    key: str
    source_sha256: str = ""


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


def checkpoint_identity(raw, params: dict, preprocessing_fingerprint: str) -> CheckpointIdentity | None:
    if params.get("enable_kurtosis_checkpoint_cache", True) is not True:
        return None
    project_root = params.get("project_root")
    source_path = params.get("_fpvs_source_file_path")
    if not project_root or not source_path or not params.get("reject_thresh"):
        return None
    try:
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
        geometry = read_raw_biosemi64_geometry(raw)
        metadata_arrays = {}
        metadata_state = encode_state({
            "raw": raw_state(raw),
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
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return CheckpointIdentity(root, folder, source, before, hashlib.sha256(encoded).hexdigest(), digest)
    except (OSError, ValueError, TypeError, RuntimeError):
        logger.debug("prepared_kurtosis_cache_identity_unavailable", exc_info=True)
        return None


def load_checkpoint(identity: CheckpointIdentity | None, *, should_cancel=None) -> PreparedCheckpoint | None:
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
        if path.resolve().parent != identity.folder.resolve() or path.stat().st_size != manifest["size_bytes"]:
            return None
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
                return None
            stream.seek(0)
            with np.load(stream, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata_json"].item()))
                if metadata["version"] != CHECKPOINT_VERSION or metadata["key"] != identity.key:
                    return None
                state = decode_state(metadata["state"], archive)
                evidence = state["evidence"]
                if not isinstance(evidence, KurtosisQCEvidence) or evidence.fingerprint != metadata["evidence_fingerprint"]:
                    return None
                raw = restore_raw(archive["samples"], state["raw"])
        if _stat(identity.source) != identity.source_stat or (should_cancel and should_cancel()):
            raw.close()
            return None
        if read_raw_biosemi64_geometry(raw) != state["params"]["_fpvs_geometry"]:
            raw.close()
            return None
        if evidence.scoring_scope.analysis_span_fingerprint != state["params"]["_fpvs_realized_analysis_span_plan"]["fingerprint"]:
            raw.close()
            return None
        return PreparedCheckpoint(raw, state["params"], evidence, state["original_sfreq"])
    except Exception:  # Optional cache boundary: any decoding failure must recompute normally.
        # Cache decoding must never convert a damaged/unsupported artifact into
        # processing failure or skip the ordinary scientific validation path.
        logger.debug("prepared_kurtosis_cache_miss", exc_info=True)
        if raw is not None:
            raw.close()
        return None


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
        with tempfile.NamedTemporaryFile(mode="w+b", dir=identity.folder, prefix=".pending-", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            np.savez(stream, **arrays)
            stream.flush()
            os.fsync(stream.fileno())
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
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

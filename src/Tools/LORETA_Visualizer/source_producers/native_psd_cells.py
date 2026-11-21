"""Project-local secondary index for freshly computed, verified Hauk participant cells."""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

from Main_App.io.atomic_write import atomic_write
from Main_App.processing.preflight_qc_pruning import safe_cache_directory

from .native_cell_runtime import canonical_digest, collect_implementation_files, executing_runtime, model_digest
from .project_time_domain_inputs import input_file_identity
from .source_psd_cache import (
    SOURCE_PSD_CACHE_KEY_FORMAT,
    SourcePsdCacheKeyInputs,
    _load_source_psd_cache_paths,
    source_psd_cache_paths,
)

SCHEMA = "fpvs_native_hauk_cell_v1"
logger = logging.getLogger(__name__)
SUPPORTED_METHODS = {"l2_mne_hauk_source_psd_cortical_normal_v1", "eloreta_volume_hauk_source_psd_vector_norm_v1"}
SHA256 = re.compile(r"[0-9a-f]{64}")
UNAVAILABLE = (
    OSError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    ImportError,
    BufferError,
    OverflowError,
    RuntimeError,
    pickle.PickleError,
)
SELECTION_PROVENANCE = {
    "source_workbook_fingerprints",
    "selection_subjects",
    "declared_group_ids",
    "pooling_cells",
    "pooling_cell_sample_sizes",
    "pooling_cell_sample_counts",
    "selection_spectra_count",
    "selection_amplitude_summary",
    "selection_z_by_harmonic",
    "selection_rows",
    "condition_z_by_harmonic",
    "spectral_eligibility_fingerprint",
    "frequency_review_decision_fingerprint",
    "final_release_receipt_fingerprint",
    "recording_condition_outcome_fingerprint",
    "roi_coverage_fingerprint",
    "roi_definition_fingerprint",
    "selection_fingerprint",
    "selection_cache_saved_at",
    "selection_cache_key",
    "selection_cache_source",
    "spectral_eligibility_workbooks",
}
RECORD_FIELDS = (
    "participant_id",
    "condition_id",
    "condition_label",
    "group_id",
    "channel_names",
    "channel_types",
    "channel_units",
    "bad_channels",
    "reference_signature",
    "n_times",
    "sfreq_hz",
    "n_step",
    "n_mod_step",
    "repetition_count",
    "fif_sha256",
)


def projected_method(method, frequencies):
    if method.get("method_id") not in SUPPORTED_METHODS or method["method_version"] != "hauk_source_psd_v1":
        return None
    custom = dict(method["custom_metadata"])
    selection = custom["harmonic_selection"]
    harmonics = selection["selected_harmonics_hz"]
    if (
        selection["source"] != "saved_processing_harmonics"
        or not harmonics
        or harmonics != method["selected_harmonics_hz"]
        or harmonics != frequencies["selected_harmonics_hz"]
    ):
        return None
    custom["harmonic_selection"] = {k: v for k, v in selection.items() if k not in SELECTION_PROVENANCE}
    if custom.get("processing_fingerprint_version") == "processing_fingerprint_v13_v3_trigger_alignment":
        custom.pop("processing_fingerprint", None)
    return {**method, "custom_metadata": custom}


def base_digest(model, method, frequencies):
    projected = projected_method(method, frequencies)
    if projected is None:
        return None
    return canonical_digest([SCHEMA, SOURCE_PSD_CACHE_KEY_FORMAT, model, projected, frequencies])


def source_sidecar_digest(record):
    """Keep all signed derivative metadata except the known v13 release/location fields."""
    document = dict(record.sidecar)
    if document.get("format") != "fpvs-source-ready-time-domain-v1" or document.get("complete") is not True:
        raise ValueError("Unknown or incomplete source-ready sidecar")
    if document["fif_sha256"] != record.fif_sha256:
        raise ValueError("Source-ready sidecar checksum mismatch")
    processing = dict(document["processing"])
    if (
        processing.get("fingerprint_version") != "processing_fingerprint_v13_v3_trigger_alignment"
        or processing.get("fingerprint") != record.processing_fingerprint
    ):
        return canonical_digest(document)
    provenance = dict(processing["provenance"])
    if provenance.get("processing_fingerprint") != record.processing_fingerprint:
        return canonical_digest(document)
    provenance.pop("processing_fingerprint")
    processing.pop("fingerprint")
    document["processing"] = {**processing, "provenance": provenance}
    signature = document.get("source_signature")
    if (
        isinstance(signature, dict)
        and isinstance(signature.get("raw_file"), str)
        and type(signature.get("raw_mtime_ns")) is int
        and signature["raw_mtime_ns"] >= 0
    ):
        document["source_signature"] = {k: v for k, v in signature.items() if k not in {"raw_file", "raw_mtime_ns"}}
    return canonical_digest(document)


@dataclass(frozen=True)
class MethodContext:
    root: Path
    base: str
    configuration: str
    frequencies: dict
    source_count: int
    manifest: dict

    @classmethod
    def from_settings(cls, root, model, method, frequencies):
        try:
            base = base_digest(model, method, frequencies)
            if base:
                return cls(
                    Path(root),
                    base,
                    canonical_digest(projected_method(method, frequencies)),
                    frequencies,
                    int(model["source_count"]),
                    collect_implementation_files(),
                )
        except UNAVAILABLE:
            logger.debug("Native source cache configuration could not be verified", exc_info=True)
        return None


@dataclass
class CellOutcome:
    computed: object = None
    reused: object = None
    native_key: str = ""


class WorkerContext:
    def __init__(self, context, info, inverse, config):
        self.context = context
        self.model = None
        self.geometry = (info, inverse)
        self.checked_first_fresh_model = False
        if context is not None:
            try:
                actual = projected_method(config.to_metadata(), context.frequencies)
                if actual and canonical_digest(actual) == context.configuration:
                    self.model = model_digest(info, inverse)
            except UNAVAILABLE:
                logger.debug("Native source model could not be verified", exc_info=True)

    def proof(self, record, runtime):
        context = self.context
        if (
            not self.model
            or not runtime
            or input_file_identity(record.fif_path.stat()) != record.verified_fif_stat
            or record.n_times != context.frequencies["n_times"]
            or record.sfreq_hz != context.frequencies["sfreq"]
        ):
            return ""
        return canonical_digest(
            [
                context.base,
                self.model,
                runtime,
                {k: getattr(record, k) for k in RECORD_FIELDS},
                source_sidecar_digest(record),
            ]
        )

    def run(self, record, may_read, compute):
        try:
            runtime = executing_runtime(self.context.manifest) if self.model else None
            code = self.proof(record, runtime)
            if code and may_read:
                result = find_native(self.context, record, code)
                if result is not None and self.proof(record, runtime) == code:
                    return CellOutcome(reused=result)
        except UNAVAILABLE:
            logger.debug("Native source cell could not be verified before execution", exc_info=True)
            code = ""
        result = compute()
        if code:
            try:
                # These two built-in kernels consume a fixed privately owned native
                # geometry. Validate its first actual use as well as its initial
                # digest. All implementation bytes are part of the worker stamp.
                if not self.checked_first_fresh_model:
                    if model_digest(*self.geometry) != self.model:
                        self.model = None
                    self.checked_first_fresh_model = True
                if self.proof(record, executing_runtime(self.context.manifest)) != code:
                    code = ""
            except UNAVAILABLE:
                logger.debug("Native source cell could not be verified after execution", exc_info=True)
                code = ""
        return CellOutcome(computed=result, native_key=code)


def alias_path(root, code):
    if not SHA256.fullmatch(code):
        raise ValueError("Invalid native cell digest")
    namespace = root / ".fpvs_processing" / "source_psd_cache" / "native_cells_v1"
    if not safe_cache_directory(root, namespace):
        raise ValueError("Redirected native PSD cell index")
    path = namespace / (code + ".json")
    if path.is_symlink() or path.resolve(strict=False) != path:
        raise ValueError("Redirected native PSD cell receipt")
    return path


def complete_result(result, record, frequencies, expected_count, method):
    data = result.metadata
    rank = data["source_ready_data_rank"]
    method_field = "inverse_method" if method["method_id"] == "eloreta_volume_hauk_source_psd_vector_norm_v1" else "source_orientation_mode"
    # A new release-scoped field in a future producer must first be classified.
    # Restrict reuse to the two actual, per-cell v1 result schemas.
    fields = {"participant_id", "group_id", "condition_id", "condition_label", "method_id", "method_version",
              "source_ready_data_rank", "source_psd_frequency_count", "frequency_plan", method_field}
    return (
        result.source_count == expected_count
        and data.keys() == fields
        and data[method_field] == method[method_field]
        and data["participant_id"] == record.participant_id
        and result.participant_id == record.participant_id
        and data["group_id"] == record.group_id
        and data["condition_id"] == record.condition_id
        and data["condition_label"] == record.condition_label
        and data["frequency_plan"] == frequencies
        and data["method_id"] == method["method_id"]
        and data["method_version"] == method["method_version"]
        and tuple(frequencies["aligned_offsets"][1:]) == result.noise_offsets_used
        and type(data["source_psd_frequency_count"]) is int
        and data["source_psd_frequency_count"] > 0
        and rank["participant_data_rank_status"] == "measured_source_ready_derivative"
        and rank["channel_count"] == len(record.channel_names)
        and rank["sample_count"] == record.n_times
        and all(
            rank[name]["shape"] == [len(record.channel_names), record.n_times]
            and len(rank[name]["singular_values"]) == min(len(record.channel_names), record.n_times)
            for name in ("unprojected", "after_recorded_projectors")
        )
    )


def certify_fresh(root, code, written):
    """Bind the original store's exact metadata/array bytes without reopening either file."""
    if not code:
        return
    try:
        path = alias_path(Path(root), code)
        path.parent.mkdir(exist_ok=True, parents=True)
        payload = {
            "format": SCHEMA,
            "cell": code,
            "primary": written.cache_key,
            "metadata_sha256": written.metadata_sha256,
            "arrays_sha256": written.arrays_sha256,
        }
        with atomic_write(path, binary=True) as stream:
            stream.write(json.dumps({**payload, "checksum": canonical_digest(payload)}, separators=(",", ":")).encode())
    except UNAVAILABLE:
        pass


def find_native(context, record, code):
    """Read the immutable origin once and validate all six arrays and its exact measured rank."""
    try:
        path = alias_path(context.root, code)
        if not path.is_file() or path.stat().st_size > 2048:
            return None
        receipt = json.loads(path.read_bytes())
        checksum = receipt.pop("checksum")
        if checksum != canonical_digest(receipt) or receipt["format"] != SCHEMA or receipt["cell"] != code:
            return None
        paths = source_psd_cache_paths(context.root, receipt["primary"])
        raw = paths.metadata_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != receipt["metadata_sha256"]:
            return None
        origin = json.loads(raw)
        payload = dict(origin["key_payload"])
        if payload.pop("format") != SOURCE_PSD_CACHE_KEY_FORMAT:
            return None
        key = SourcePsdCacheKeyInputs(**payload)
        if (
            key.cache_key != receipt["primary"]
            or origin["arrays_sha256"] != receipt["arrays_sha256"]
            or key.derivative_checksum_sha256 != record.fif_sha256
            or base_digest(key.numerical_model_metadata, key.method_metadata, key.frequency_metadata) != context.base
        ):
            return None
        lookup = _load_source_psd_cache_paths(key, paths, cache_key=key.cache_key, metadata=origin)
        if lookup.hit and complete_result(
            lookup.result, record, context.frequencies, context.source_count, key.method_metadata
        ):
            return lookup.result
    except UNAVAILABLE:
        pass
    return None

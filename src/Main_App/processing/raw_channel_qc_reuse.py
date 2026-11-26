"""Run-scoped reuse of the built-in raw-channel detector across the QC review boundary."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Any

import mne
import numpy as np
import scipy
from mne.io import BaseRaw

from Main_App.io.acquisition_metadata import resolve_recording_contract
from Main_App.processing.analysis_spans import merge_relative_spans
from Main_App.processing.pipeline_plan import resolve_pipeline_plan
from Main_App.processing.prepared_kurtosis_cache import _native_execution_identity
from Main_App.processing.qc_signal_view import source_content_identity
from Main_App.processing.raw_channel_qc import (
    RAW_CHANNEL_QC_METHOD_VERSION,
    RawChannelQCConfig,
    RawChannelQCResult,
    _config_from_settings,
    _scalp_picks,
    _validate_spatial_geometry,
)


@dataclass(frozen=True, slots=True)
class RawChannelQCInputs:
    config: RawChannelQCConfig
    analysis_fingerprint: str
    spans: tuple[tuple[int, int], ...]
    channels: tuple[str, ...]
    channel_types: tuple[str, ...]
    bads: tuple[str, ...]
    positions_hex: str
    roles: tuple[str, str, str]
    geometry: str
    sampling_rate: float
    first_sample: int
    sample_count: int
    numeric_identity: tuple


@dataclass(frozen=True, slots=True)
class PreparedRawChannelQC:
    inputs: RawChannelQCInputs
    source_path: str
    source_size: int
    source_sha256: str
    samples_sha256: str
    result: RawChannelQCResult


def raw_channel_qc_inputs(
    raw: Any, settings: Mapping[str, Any], analysis_spans: Sequence[Sequence[int]],
) -> RawChannelQCInputs | None:
    """Capture the native detector's inputs before preprocessing can modify Raw."""
    try:
        if (
            not isinstance(raw, BaseRaw) or not raw.preload
            or getattr(raw.get_data, "__func__", None) is not BaseRaw.get_data
            or getattr(raw._getitem, "__func__", None) is not BaseRaw._getitem
            or type(raw._data) not in (np.ndarray, np.memmap)
            or raw._data.dtype != np.dtype(np.float64) or not raw._data.flags.c_contiguous
            or raw._data.shape != (len(raw.ch_names), raw.n_times)
        ):
            return None
        config = _config_from_settings(settings)
        if not config.auto_detect_removed_electrodes:
            return None
        plan = resolve_pipeline_plan(settings)
        if any(method.stage_id == "raw_screening" and method.implementation is not None for method in plan.methods):
            return None
        contract = resolve_recording_contract(settings, raw=raw)
        plan.validate_capabilities(contract)
        analysis_plan = settings.get("_fpvs_source_analysis_span_plan")
        analysis_fingerprint = analysis_plan.get("fingerprint") if isinstance(analysis_plan, Mapping) else None
        if not contract.spatial_qc_supported or not isinstance(analysis_fingerprint, str) or not analysis_fingerprint:
            return None
        refs = (
            str(settings.get("ref_channel1") or settings.get("ref_ch1") or ""),
            str(settings.get("ref_channel2") or settings.get("ref_ch2") or ""),
        )
        stim = str(settings.get("stim_channel") or "")
        channels = tuple(raw.ch_names)
        picks = _scalp_picks(raw, stim_channel=stim, ref_channels=refs)
        spans = merge_relative_spans(analysis_spans, n_times=int(raw.n_times))
        if not spans or len(picks) < config.min_channels_for_hard_qc:
            return None
        _validate_spatial_geometry(raw, [channels[index] for index in picks], settings)
        native = _native_execution_identity()
        if native is None:
            return None
        return RawChannelQCInputs(
            config=config, analysis_fingerprint=analysis_fingerprint, spans=spans,
            channels=channels, channel_types=tuple(raw.get_channel_types()),
            bads=tuple(raw.info["bads"]),
            positions_hex=np.asarray([raw.info["chs"][index]["loc"][:3] for index in picks]).tobytes().hex(),
            roles=(stim, *refs), geometry=contract.geometry_json,
            sampling_rate=float(raw.info["sfreq"]), first_sample=int(raw.first_samp),
            sample_count=int(raw.n_times),
            numeric_identity=(RAW_CHANNEL_QC_METHOD_VERSION, mne.__version__, np.__version__, scipy.__version__, native),
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError, RuntimeError):
        return None


def restore_raw_channel_qc(
    prepared: object, raw: Any, settings: Mapping[str, Any], file_path: Path,
    analysis_spans: Sequence[Sequence[int]],
) -> RawChannelQCResult | None:
    """Accept only this run's result for the same current file, scope and loaded samples."""
    if not isinstance(prepared, PreparedRawChannelQC):
        return None
    if raw_channel_qc_inputs(raw, settings, analysis_spans) != prepared.inputs:
        return None
    try:
        identity = source_content_identity(file_path)
        if (
            identity["path"] != prepared.source_path or identity["size_bytes"] != prepared.source_size
            or identity["sha256"] != prepared.source_sha256
        ):
            return None
        # The input guard requires C-ordered native float64. This is the same
        # byte sequence already hashed row by row when preparing a checkpoint.
        if hashlib.sha256(memoryview(raw._data).cast("B")).hexdigest() != prepared.samples_sha256:
            return None
    except (OSError, ValueError, TypeError, RuntimeError):
        return None
    return prepared.result

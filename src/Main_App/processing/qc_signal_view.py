"""Bounded, read-only signal views for QC; these displays authorize no repair."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
import hashlib
import json
import logging
from pathlib import Path
import struct
from types import SimpleNamespace
import zipfile

import numpy as np

logger = logging.getLogger(__name__)
_MODES = {"raw", "initial_reference", "prepared", "reference_comparison"}


def _reference_pair(params):
    return tuple(str(params.get(f"ref_channel{i}") or params.get(f"ref_chan{i}")
                     or params.get(f"ref_ch{i}") or f"EXG{i}") for i in (1, 2))


def _stim_channel(params):
    return str(params.get("stim_channel") or params.get("stim") or "Status")


@dataclass(frozen=True)
class QcSignalViewRequest:
    path: Path
    project_root: Path
    params: Mapping[str, object]
    channel: str = ""
    spans: tuple[tuple[float, float], ...] = ()
    span_labels: tuple[str, ...] = ()
    source_spans: tuple[tuple[float, float], ...] = ()
    prepared: Mapping[str, object] = field(default_factory=dict)
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    source_identity: Mapping[str, object] = field(default_factory=dict)
    verified_checkpoint: tuple[object, ...] = ()
    overview_cache: tuple[object, ...] = ()
    spatial_holdout: bool = False
    unusable_channels: tuple[str, ...] = ()
    mode: str = "initial_reference"
    occurrence_index: int = 0
    start_seconds: float | None = None
    duration_seconds: float = 5.0


@dataclass(frozen=True)
class QcSignalTrace:
    name: str
    minimum_uv: tuple[float | None, ...]
    maximum_uv: tuple[float | None, ...]


@dataclass(frozen=True)
class QcSignalViewResult:
    channel: str
    available_channels: tuple[str, ...]
    span_labels: tuple[str, ...]
    spans: tuple[tuple[float, float], ...]
    occurrence_index: int
    start_seconds: float
    stop_seconds: float
    overview_times: tuple[float, ...]
    overview: QcSignalTrace
    detail_times: tuple[float, ...]
    traces: tuple[QcSignalTrace, ...]
    mode_label: str
    reference_pair: tuple[str, str]
    diagnostics: Mapping[str, object] = field(default_factory=dict)
    verified_checkpoint: tuple[object, ...] = ()
    overview_cache: tuple[object, ...] = ()
    spatial_support: Mapping[str, object] = field(default_factory=dict)


def request_from_source(path, project_root, params, *, channel="", spans=(), span_labels=()):
    """Create an I/O-free request; coordinates are seconds from recording start."""
    keys = ("ref_channel1", "ref_channel2", "ref_chan1", "ref_chan2", "ref_ch1", "ref_ch2",
            "stim_channel", "stim", "electrode_mapping_profile", "electrode_montage",
            "first_n_channels", "max_idx_keep", "max_chan_idx_keep")
    loader_params = {key: deepcopy(params[key]) for key in keys if key in params}
    reference_requested = str(channel).casefold() in {ref.casefold() for ref in _reference_pair(loader_params)}
    return QcSignalViewRequest(
        Path(path), Path(project_root), loader_params, "" if reference_requested else str(channel),
        tuple((float(start), float(stop)) for start, stop in spans), tuple(span_labels),
        mode="reference_comparison" if reference_requested else "initial_reference",
    )


def request_from_kurtosis_item(item, project_root, params):
    view = dict(getattr(item, "signal_view", {}) or {})
    spans = view.get("spans", ())
    request = request_from_source(
        item.path, project_root, params, channel=item.channel,
        spans=[(span["start_seconds"], span["stop_seconds"]) for span in spans],
        span_labels=[str(span["label"]) for span in spans],
    )
    prepared = dict(view.get("prepared") or {})
    source_spans = tuple((span.get("source_start_seconds", span["start_seconds"]),
                          span.get("source_stop_seconds", span["stop_seconds"])) for span in spans)
    return replace(request, source_spans=source_spans, prepared=prepared,
                   diagnostics=dict(getattr(item, "review_diagnostics", {}) or {}),
                   source_identity=dict(view.get("source_identity") or {}),
                   unusable_channels=tuple(view.get("upstream_bad_channels") or ()),
                   mode="prepared" if prepared else "initial_reference")


def peak_preserving_values(values: np.ndarray, *, bins: int = 128) -> tuple[float | None, ...]:
    """Retain both extrema of every bin in temporal order, including impulses."""
    values = np.asarray(values, dtype=float).reshape(-1)
    if not values.size:
        return ()
    result: list[float | None] = []
    for block in np.array_split(values, min(max(1, bins), len(values))):
        finite = np.flatnonzero(np.isfinite(block))
        if not finite.size:
            result.append(None)
            continue
        low = int(finite[np.argmin(block[finite])])
        high = int(finite[np.argmax(block[finite])])
        for index in sorted({low, high}):
            result.append(float(block[index]))
    return tuple(result)


def build_kurtosis_view_metadata(raw, params, checkpoint, evidence_fingerprint):
    """Snapshot display coordinates/cache identity while preprocessing owns Raw."""
    plan = params.get("_fpvs_realized_analysis_span_plan") or {}
    sfreq = float(raw.info["sfreq"])
    source_rate = float((params.get("_fpvs_source_analysis_span_plan") or {}).get(
        "source_grid", {}).get("sfreq_hz", sfreq))
    spans = []
    for span in plan.get("spans", ()):
        coords = span["target_coordinates"]
        spans.append({
            "start_seconds": int(coords["start_relative_sample"]) / sfreq,
            "stop_seconds": int(coords["stop_relative_sample"]) / sfreq,
            "source_start_seconds": int(span["source_coordinates"]["start_relative_sample"]) / source_rate,
            "source_stop_seconds": int(span["source_coordinates"]["stop_relative_sample"]) / source_rate,
            "label": f"{span['condition_label']} · occurrence {int(span['repetition_index']) + 1}",
            "occurrence_key": span.get("occurrence_key", ""),
            "source_coordinates": dict(span.get("source_coordinates") or {}),
            "target_coordinates": dict(coords),
        })
    prepared = {}
    if checkpoint is not None:
        try:
            manifest = json.loads((checkpoint.folder / "latest.json").read_text(encoding="utf-8"))
            if manifest.get("key") == checkpoint.key:
                prepared = {
                    **manifest, "path": str(checkpoint.folder / manifest["path"]),
                    "source_path": str(checkpoint.source),
                    "source_stat": list(checkpoint.source_stat),
                    "evidence_fingerprint": evidence_fingerprint,
                    "channels": list(raw.ch_names), "sfreq": sfreq,
                    "n_times": int(raw.n_times),
                    "positions": {
                        channel: list(map(float, raw.info["chs"][i]["loc"][:3]))
                        for i, channel in enumerate(raw.ch_names)
                        if np.all(np.isfinite(raw.info["chs"][i]["loc"][:3]))
                    },
                }
        except (OSError, ValueError, KeyError, TypeError):
            logger.debug("qc_signal_view_checkpoint_unavailable", exc_info=True)
    source_identity = ({"path": str(checkpoint.source.resolve()), "size_bytes": checkpoint.source_stat[0],
                        "sha256": checkpoint.source_sha256}
                       if checkpoint is not None and getattr(checkpoint, "source_sha256", "") else {})
    return {"spans": spans, "prepared": prepared, "signal_stage": "prepared_pre_interpolation",
            "checkpoint_source_identity": source_identity,
            "upstream_bad_channels": list(raw.info.get("bads", []))}


def _cancel(should_cancel):
    if should_cancel and should_cancel():
        raise InterruptedError("Signal inspection cancelled.")


def _signature(path):
    stat = Path(path).stat()
    return (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def source_content_identity(path: Path, *, should_cancel=None) -> dict[str, object]:
    """Bind diagnostic evidence to source bytes, including same-timestamp edits."""
    path = Path(path).resolve()
    before = _signature(path)
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as stream:
        while block := stream.read(1024 * 1024):
            _cancel(should_cancel)
            digest.update(block)
    if _signature(path) != before:
        raise ValueError("Recording changed while its diagnostic identity was being checked.")
    return {"path": str(path), "size_bytes": before[0], "sha256": digest.hexdigest()}


def _verify_checkpoint_content(stream, expected_digest, should_cancel):
    stream.seek(0)
    digest = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        _cancel(should_cancel)
        digest.update(block)
    if digest.hexdigest() != expected_digest:
        raise ValueError("Prepared signal checkpoint failed its integrity check.")


@contextmanager
def _prepared_samples(request, should_cancel):
    """Read a verified uncompressed NPZ member through a read-only file mapping."""
    descriptor = request.prepared
    path = Path(str(descriptor["path"]))
    root = request.project_root.resolve()
    if not path.resolve().is_relative_to(root / ".fpvs_cache" / "prepared_kurtosis"):
        raise ValueError("Prepared preview is outside the active project's checkpoint cache.")
    if tuple(descriptor["source_stat"]) != _signature(request.path):
        raise ValueError("Recording changed since kurtosis evidence was prepared. Run QC again.")
    if descriptor.get("source_path") and Path(str(descriptor["source_path"])).resolve() != request.path.resolve():
        raise ValueError("Prepared signal belongs to a different recording.")
    before = _signature(path)
    verified = (str(path.resolve()), *before, descriptor["sha256"], descriptor["key"], descriptor["evidence_fingerprint"])
    with path.open("rb", buffering=0) as stream:
        # A Windows creation timestamp does not change on in-place writes, and
        # mtime can be restored. Never use file stats to skip content validation.
        _verify_checkpoint_content(stream, descriptor["sha256"], should_cancel)
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            metadata = np.load(archive.open("metadata_json.npy"), allow_pickle=False)
            metadata = json.loads(str(metadata.item()))
            if (metadata.get("key") != descriptor["key"]
                    or metadata.get("evidence_fingerprint") != descriptor["evidence_fingerprint"]):
                raise ValueError("Prepared signal does not match the reviewed evidence.")
            member = archive.getinfo("samples.npy")
            if member.compress_type != zipfile.ZIP_STORED:
                raise ValueError("Prepared signal is not available for bounded reading.")
            stream.seek(member.header_offset)
            header = stream.read(30)
            if header[:4] != b"PK\x03\x04":
                raise ValueError("Malformed prepared signal archive.")
            name_length, extra_length = struct.unpack_from("<HH", header, 26)
            stream.seek(member.header_offset + 30 + name_length + extra_length)
            version = np.lib.format.read_magic(stream)
            if version == (1, 0):
                shape, fortran, dtype = np.lib.format.read_array_header_1_0(stream)
            elif version == (2, 0):
                shape, fortran, dtype = np.lib.format.read_array_header_2_0(stream)
            else:
                raise ValueError("Unsupported prepared signal array version.")
            if dtype != np.dtype("float64") or fortran or shape != (
                len(descriptor["channels"]), int(descriptor["n_times"]),
            ):
                raise ValueError("Prepared signal dimensions do not match the review.")
            offset = stream.tell()
        samples = np.memmap(stream, mode="r", dtype=dtype, shape=shape, offset=offset)
        try:
            yield samples, verified
        finally:
            samples._mmap.close()
        # Bind the displayed samples to unchanged bytes throughout this read,
        # including in-place writes whose timestamps were restored.
        _verify_checkpoint_content(stream, descriptor["sha256"], should_cancel)
    if tuple(descriptor["source_stat"]) != _signature(request.path):
        raise ValueError("Recording changed while the signal was being inspected.")
    if _signature(path) != before:
        raise ValueError("Prepared checkpoint changed while its signal was being inspected.")


def _finite_tuple(array):
    return tuple(float(value) if np.isfinite(value) else None for value in array)


def envelope_from_reader(reader: Callable, *, start: int, stop: int, sfreq: float,
                         names: Sequence[str], bins: int = 640, should_cancel=None):
    """Compute exact per-bin extrema using bounded reads, never stride sampling."""
    if stop <= start or start < 0 or sfreq <= 0:
        raise ValueError("Signal view bounds are invalid.")
    edges = np.linspace(start, stop, min(int(bins), stop - start) + 1, dtype=np.int64)
    lows = np.full((len(names), len(edges) - 1), np.nan)
    highs = lows.copy()
    # One bounded sequential pass; never issue a BDF read per plotted pixel.
    for block_start in range(start, stop, 131072):
        _cancel(should_cancel)
        block_stop = min(stop, block_start + 131072)
        data = np.asarray(reader(block_start, block_stop), dtype=float)
        first_bin = max(0, int(np.searchsorted(edges, block_start, side="right")) - 1)
        last_bin = min(len(edges) - 1, int(np.searchsorted(edges, block_stop, side="left")))
        for column in range(first_bin, last_bin):
            left = max(int(edges[column]), block_start) - block_start
            right = min(int(edges[column + 1]), block_stop) - block_start
            for row in range(len(names)):
                block = data[row, left:right]
                finite = block[np.isfinite(block)]
                if finite.size:
                    lows[row, column] = np.fmin(lows[row, column], finite.min())
                    highs[row, column] = np.fmax(highs[row, column], finite.max())
    traces = tuple(QcSignalTrace(name, _finite_tuple(low * 1e6), _finite_tuple(high * 1e6))
                   for name, low, high in zip(names, lows, highs, strict=True))
    return tuple(float(value / sfreq) for value in (edges[:-1] + edges[1:] - 1) / 2), traces


def _nearby(channels, positions, channel, reference_pair):
    origin = np.asarray(positions.get(channel, ()), dtype=float)
    candidates = []
    if origin.shape == (3,) and np.all(np.isfinite(origin)) and np.linalg.norm(origin):
        for name in channels:
            if name == channel or name in reference_pair or name.upper().startswith("EXG"):
                continue
            point = np.asarray(positions.get(name, ()), dtype=float)
            if point.shape == (3,) and np.all(np.isfinite(point)) and np.linalg.norm(point):
                candidates.append((float(np.linalg.norm(point - origin)), name))
    return tuple([channel, *[name for _distance, name in sorted(candidates)[:3]]])


def _spatial_support(request, reader, channels, positions, reference_pair, start, stop, sfreq, should_cancel):
    if not request.spatial_holdout:
        return {}
    from Main_App.processing.qc_review_diagnostics import estimate_qc_spatial_support

    names = [name for name in channels if name in positions and name not in reference_pair
             and not name.upper().startswith("EXG") and np.linalg.norm(positions[name]) > 0
             and np.all(np.isfinite(positions[name]))]
    required = list(dict.fromkeys([*names, *[ref for ref in reference_pair if ref in channels]]))
    picks = [channels.index(name) for name in required]
    sample_indices = np.unique(np.linspace(start, stop - 1, min(4096, stop - start), dtype=int))
    blocks = []
    for block_start in range(start, stop, 32768):
        _cancel(should_cancel)
        block_stop = min(stop, block_start + 32768)
        chosen = sample_indices[(sample_indices >= block_start) & (sample_indices < block_stop)]
        if not chosen.size:
            continue
        values = reader(picks, block_start, block_stop)[:, chosen - block_start]
        scalp = values[:len(names)]
        if request.mode == "initial_reference":
            refs = values[[required.index(name) for name in reference_pair]]
            scalp = scalp - refs.mean(axis=0)
        blocks.append(scalp)
    sampled = np.concatenate(blocks, axis=1)
    result = estimate_qc_spatial_support(
        sampled, channels=names, positions=positions,
        unusable_channels=request.unusable_channels, should_cancel=should_cancel,
    )
    return {**result, "window_start_seconds": start / sfreq, "window_stop_seconds": stop / sfreq,
            "signal_stage": request.mode, "sample_count": len(sample_indices),
            "sampling": "Evenly sampled current window; spatial comparison only, not transient detection."}


def _read_view(request, reader, channels, sfreq, n_times, positions, reference_pair, should_cancel, *, source_signature=()):
    reference_pair = tuple(next((name for name in channels if name.casefold() == ref.casefold()), ref)
                           for ref in reference_pair)
    available = tuple(name for name in channels if name not in reference_pair and not name.upper().startswith("EXG")
                      and name.casefold() != _stim_channel(request.params).casefold())
    channel = next((name for name in available if name.casefold() == request.channel.casefold()), "") if request.channel else next(iter(available), "")
    if not channel:
        raise ValueError(f"Requested scalp electrode {request.channel!r} is outside this signal's retained selection."
                         if request.channel else "No scalp channels are available for signal inspection.")
    spans = (request.source_spans if request.mode != "prepared" and request.source_spans else request.spans)
    spans = spans or ((0.0, n_times / sfreq),)
    if any(not np.isfinite(start + stop) or start < 0 or stop <= start or stop > n_times / sfreq + 1 / sfreq
           for start, stop in spans):
        raise ValueError("Requested occurrence bounds do not match this recording.")
    index = min(max(0, request.occurrence_index), len(spans) - 1)
    labels = request.span_labels if len(request.span_labels) == len(spans) else tuple(
        f"Interval {i + 1} · {start:.3f}–{stop:.3f} s" for i, (start, stop) in enumerate(spans)
    )
    left_s, right_s = spans[index]
    left, right = max(0, round(left_s * sfreq)), min(n_times, round(right_s * sfreq))
    selected = _nearby(available, positions, channel, reference_pair)
    names = selected
    if request.mode == "reference_comparison":
        names = (f"{channel} · acquisition", f"{channel} · intended reference", *reference_pair,
                 f"{reference_pair[0]} − {reference_pair[1]}")
    indices = [channels.index(name) for name in dict.fromkeys((*selected, *reference_pair)) if name in channels]
    loaded_names = [channels[i] for i in indices]
    if request.mode in {"initial_reference", "reference_comparison"} and any(ref not in loaded_names for ref in reference_pair):
        raise ValueError("The configured reference pair is unavailable for this preview.")

    def transformed(start, stop):
        values = reader(indices, start, stop)
        scalp = values[[loaded_names.index(name) for name in selected]]
        if request.mode == "prepared" or request.mode == "raw":
            return scalp
        refs = values[[loaded_names.index(name) for name in reference_pair]]
        referenced = scalp - refs.mean(axis=0)
        if request.mode == "reference_comparison":
            return np.vstack((scalp[0], referenced[0], refs, refs[0] - refs[1]))
        return referenced

    overview_key = (source_signature, request.mode, channel, left, right, sfreq)
    if request.overview_cache and request.overview_cache[0] == overview_key:
        _key, overview_times, overview_trace = request.overview_cache
    else:
        overview_times, overview = envelope_from_reader(
            lambda start, stop: transformed(start, stop)[:1], start=left, stop=right,
            sfreq=sfreq, names=(names[0],), bins=320, should_cancel=should_cancel,
        )
        overview_trace = overview[0]
    duration = min(30.0, max(0.05, float(request.duration_seconds)), 250000 / sfreq)
    start_s = left_s if request.start_seconds is None else float(request.start_seconds)
    start_s = max(left_s, min(start_s, max(left_s, right_s - duration)))
    start, stop = max(left, round(start_s * sfreq)), min(right, round((start_s + duration) * sfreq))
    times, traces = envelope_from_reader(
        transformed, start=start, stop=max(start + 1, stop), sfreq=sfreq,
        names=names, bins=1000, should_cancel=should_cancel,
    )
    mode_label = {
        "raw": "Raw acquisition · no software reference or filtering",
        "initial_reference": f"Intended initial reference ({reference_pair[0]} + {reference_pair[1]}) / 2 · unfiltered",
        "reference_comparison": "Reference comparison · raw acquisition, intended reference, and recorded reference pair",
        "prepared": "Prepared signal · initial reference, filtering and downsampling; before interpolation/final average reference",
    }[request.mode]
    spatial_support = _spatial_support(request, reader, channels, positions, reference_pair,
                                       start, max(start + 1, stop), sfreq, should_cancel)
    return QcSignalViewResult(channel, available, labels, spans, index, start / sfreq, stop / sfreq,
                              overview_times, overview_trace, times, traces, mode_label, reference_pair,
                              overview_cache=(overview_key, overview_times, overview_trace), spatial_support=spatial_support)


def load_qc_signal_view(request: QcSignalViewRequest, *, should_cancel=None) -> QcSignalViewResult:
    """Load one independent diagnostic view; all source handles close on return."""
    if request.mode not in _MODES:
        raise ValueError("Unknown signal view mode.")
    ref_pair = _reference_pair(request.params)
    _cancel(should_cancel)
    expected_source = request.source_identity or request.diagnostics.get("source_identity", {})
    current_source = source_content_identity(request.path, should_cancel=should_cancel)
    if expected_source and current_source != expected_source:
        raise ValueError("Recording content changed since these QC findings were computed. Run QC again.")
    if request.diagnostics and not expected_source:
        # Legacy/unbound summaries cannot accompany freshly loaded source data.
        request = replace(request, diagnostics={})
    if request.mode == "prepared":
        with _prepared_samples(request, should_cancel) as (data, verified):
            descriptor = request.prepared
            result = _read_view(
                request, lambda picks, start, stop: np.array(data[picks, start:stop]),
                list(descriptor["channels"]), float(descriptor["sfreq"]), int(descriptor["n_times"]),
                descriptor.get("positions", {}), ref_pair, should_cancel, source_signature=verified,
            )
        if source_content_identity(request.path, should_cancel=should_cancel) != current_source:
            raise ValueError("Recording changed while the QC signal was being inspected.")
        return replace(result, diagnostics=request.diagnostics, verified_checkpoint=verified)
    from Main_App.io.load_utils import open_preflight_eeg_file

    before = _signature(request.path)
    if request.prepared and tuple(request.prepared.get("source_stat", ())) != before:
        raise ValueError("Recording changed since the current kurtosis review. Run QC again before inspecting its evidence.")
    limit = next((request.params[key] for key in ("first_n_channels", "max_idx_keep", "max_chan_idx_keep")
                  if request.params.get(key) is not None), 64)
    if isinstance(limit, bool) or (isinstance(limit, float) and not limit.is_integer()) or not 1 <= int(limit) <= 64:
        raise ValueError("Signal inspection requires the configured scalp channel limit (1–64).")
    host = SimpleNamespace(
        currentProject=SimpleNamespace(preprocessing=dict(request.params)),
        log=lambda message, **_kwargs: logger.debug("qc_signal_view_load message=%s", message),
    )
    with open_preflight_eeg_file(
        host, request.path, ref_pair=ref_pair, first_n_channels=int(limit),
        stim_channel=_stim_channel(request.params),
        electrode_mapping_profile=request.params.get("electrode_mapping_profile"),
        electrode_montage=str(request.params.get("electrode_montage") or "biosemi64"),
    ) as raw:
        if raw is None:
            raise ValueError("The recording could not be opened for signal inspection.")
        positions = {name: raw.info["chs"][i]["loc"][:3] for i, name in enumerate(raw.ch_names)}
        result = _read_view(request, lambda picks, start, stop: raw.get_data(picks=picks, start=start, stop=stop),
                            raw.ch_names, float(raw.info["sfreq"]), int(raw.n_times), positions,
                            ref_pair, should_cancel, source_signature=tuple(current_source.items()))
        if request.diagnostics:
            result = replace(result, diagnostics=request.diagnostics)
        else:
            try:
                from Main_App.processing.qc_review_diagnostics import build_qc_review_diagnostics

                names = tuple(dict.fromkeys((*_nearby(raw.ch_names, positions, result.channel, ref_pair), *ref_pair)))
                sfreq = float(raw.info["sfreq"])
                start, stop = round(result.start_seconds * sfreq), round(result.stop_seconds * sfreq)
                samples = raw.get_data(picks=list(names), start=start, stop=stop)
                diagnostics = build_qc_review_diagnostics(
                    samples, sfreq=sfreq, channels=names, positions=positions,
                    occurrences=[{"start_sample": 0, "stop_sample": stop - start,
                                  "condition_label": result.span_labels[result.occurrence_index], "occurrence": 1}],
                    signal_stage="raw_acquisition", sample_offset=int(raw.first_samp) + start,
                    source_first_samp=int(raw.first_samp), evaluation_scope="displayed_window",
                    diagnostic_channels=(result.channel,), should_cancel=should_cancel,
                )
                result = replace(result, diagnostics=diagnostics)
            except InterruptedError:
                raise
            except Exception:  # Diagnostic-only boundary: signal inspection remains usable.
                logger.debug("qc_signal_window_diagnostics_unavailable", exc_info=True)
    if _signature(request.path) != before:
        raise ValueError("Recording changed while its signal was being inspected.")
    if source_content_identity(request.path, should_cancel=should_cancel) != current_source:
        raise ValueError("Recording changed while the QC signal was being inspected.")
    return result


def format_signal_diagnostics(diagnostics: Mapping[str, object]) -> str:
    """Render review-only evidence without implying a validated artifact decision."""
    if not diagnostics:
        return "No additional diagnostic evidence is available. Signal inspection does not establish whether interpolation is appropriate."
    from Main_App.processing.qc_review_diagnostics import format_qc_review_diagnostics

    return format_qc_review_diagnostics(diagnostics)


__all__ = ["QcSignalViewRequest", "QcSignalViewResult", "QcSignalTrace", "request_from_source",
           "request_from_kurtosis_item", "load_qc_signal_view", "peak_preserving_values",
           "build_kurtosis_view_metadata", "envelope_from_reader", "format_signal_diagnostics",
           "source_content_identity"]

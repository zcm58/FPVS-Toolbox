"""Descriptive, review-only adapters for established MNE signal diagnostics.

No returned annotation, bad-channel suggestion, or spatial comparison is
applied to data or admitted to the kurtosis corroborator registry. Thresholds
are provisional diagnostic settings, not validated artifact probabilities.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from typing import Any

import mne
import numpy as np

from Main_App.io.eeg_geometry import (
    BIOSEMI64_CHANNEL_SET,
    canonical_biosemi64_head_coordinates,
)

QC_REVIEW_DIAGNOSTICS_VERSION = "mne_amplitude_review_shadow_v1"
_AUTHORITY = "review_only"


class QCReviewDiagnosticsCancelled(InterruptedError):
    """Raised between bounded diagnostic computations when cancelled."""


@dataclass(frozen=True)
class QCReviewDiagnosticSettings:
    flatline_min_duration_s: float = 0.5
    plateau_min_duration_s: float = 0.02
    plateau_min_deviation_uv: float = 100.0
    plateau_mad_multiplier: float = 8.0
    jump_min_step_uv: float = 100.0
    jump_mad_multiplier: float = 20.0
    minimum_robust_samples: int = 32
    summary_sample_limit: int = 4096
    chunk_samples: int = 65536
    max_events: int = 512
    neighbor_count: int = 6
    minimum_spatial_donors: int = 4
    enable_spatial_holdout: bool = False
    max_holdout_channels: int = 8

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if name == "enable_spatial_holdout":
                if not isinstance(value, bool):
                    raise ValueError("enable_spatial_holdout must be boolean.")
                continue
            if isinstance(value, bool) or not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"{name} must be positive and finite.")
        for name in ("minimum_robust_samples", "summary_sample_limit", "chunk_samples",
                     "max_events", "neighbor_count", "minimum_spatial_donors", "max_holdout_channels"):
            if not isinstance(getattr(self, name), int):
                raise ValueError(f"{name} must be an integer.")
        if not 2 <= self.chunk_samples <= 262144:
            raise ValueError("chunk_samples must be between 2 and 262144.")
        if not self.minimum_robust_samples <= self.summary_sample_limit <= 16384:
            raise ValueError("summary_sample_limit must cover the minimum and not exceed 16384.")
        if self.max_events > 4096 or self.max_holdout_channels > 64:
            raise ValueError("Diagnostic output and holdout limits exceed supported bounds.")


def _cancel(callback: Callable[[], bool] | None) -> None:
    if callback and callback():
        raise QCReviewDiagnosticsCancelled("Review diagnostics cancelled.")


def _settings(value) -> QCReviewDiagnosticSettings:
    return value if isinstance(value, QCReviewDiagnosticSettings) else QCReviewDiagnosticSettings(**dict(value or {}))


def _names(channels: Sequence[str]) -> tuple[str, ...]:
    names = tuple(str(item) for item in channels)
    if not names or len(names) > 256 or any(not name for name in names) or len(set(names)) != len(names):
        raise ValueError("Diagnostic channels must be 1–256 unique, nonempty names.")
    return names


def _positions(channels, positions):
    valid = {}
    for channel in channels:
        try:
            value = np.asarray(positions[channel], dtype=float)
        except (KeyError, TypeError, ValueError):
            continue
        if value.shape == (3,) and np.isfinite(value).all():
            valid[channel] = value
    return valid


def review_repair_topology(
    channels: Sequence[str],
    positions: Mapping[str, Sequence[float]],
    *,
    repair_channels: Sequence[str],
    unusable_channels: Sequence[str] = (),
    settings: QCReviewDiagnosticSettings | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Describe repaired-channel adjacency and usable local sensor support."""
    config, names = _settings(settings), _names(channels)
    repairs = tuple(name for name in names if name in set(repair_channels))
    unknown = sorted(set(repair_channels).difference(names))
    coordinates = _positions(names, positions)
    excluded = set(repairs).union(unusable_channels)
    neighbor_map, rows = {}, []
    for name in names:
        if name not in coordinates:
            continue
        nearby = sorted(
            ((other, float(np.linalg.norm(coordinates[name] - point)))
             for other, point in coordinates.items() if other != name),
            key=lambda item: (item[1], item[0]),
        )
        nearby = [(other, distance) for other, distance in nearby if distance > 0]
        neighbor_map[name] = [other for other, _distance in nearby[:config.neighbor_count]]
        if name in repairs:
            donors = [(other, distance) for other, distance in nearby if other not in excluded]
            rows.append({
                "channel": name,
                "usable_donors": [{"channel": other, "distance_m": distance}
                                  for other, distance in donors[:config.neighbor_count]],
                "excluded_neighbors": [other for other, _ in nearby[:config.neighbor_count] if other in excluded],
                "nearest_usable_donor_distance_m": donors[0][1] if donors else None,
                "available_donor_count": len(donors),
            })
    pending, components = set(repairs).intersection(coordinates), []
    while pending:
        component, stack = [], [min(pending)]
        while stack:
            name = stack.pop()
            if name not in pending:
                continue
            pending.remove(name)
            component.append(name)
            stack.extend(other for other in pending
                         if other in neighbor_map.get(name, ()) or name in neighbor_map.get(other, ()))
        components.append(sorted(component))
    missing = sorted(set(repairs).difference(coordinates))
    return {
        "status": "unavailable" if unknown or missing else "available",
        "authority": _AUTHORITY,
        "repair_channels": list(repairs), "unknown_channels": unknown,
        "missing_geometry_channels": missing, "components": components, "channels": rows,
        "adjacency_definition": f"undirected union of {config.neighbor_count} nearest sensor neighbors",
        "limitations": [
            "Adjacency and donor distances are descriptive, with no automatic risk cutoff.",
            "Nearest sensors shown here are not the spline weights or the complete MNE interpolation operator.",
            "Interpolation completion and channel counts do not establish biological reconstruction accuracy.",
        ],
    }


def _mne_segments(values, sfreq, peak):
    """Return untrimmed MNE consecutive-difference spans for one bounded row."""
    # Always a bounded plain ndarray: Raw.__del__ must not unlink a source mmap.
    scratch = np.array(values, dtype=np.float64, copy=True, subok=False)[None, :]
    raw = mne.io.RawArray(scratch, mne.create_info(["signal"], sfreq, "eeg"), copy="info", verbose=False)
    result = {"flat": [], "peak": []}
    try:
        for kind, threshold in (("flat", 0.0), ("peak", peak)):
            if threshold is None:
                continue
            annotations, bads = mne.preprocessing.annotate_amplitude(
                raw, **{kind: threshold}, bad_percent=100, min_duration=0,
                picks=[0], verbose=False,
            )
            result[kind] = [
                (int(round(onset * sfreq)), int(round((onset + duration) * sfreq)) + 1)
                for onset, duration in zip(annotations.onset, annotations.duration)
            ]
            # MNE returns a bad-channel name instead of annotations at exactly
            # 100%. On one channel this means all consecutive differences pass;
            # recover its observed support without applying that suggestion.
            if bads:
                differences = np.abs(np.diff(scratch[0]))
                all_match = (np.isfinite(differences).all()
                             and bool(np.all(differences <= threshold if kind == "flat" else differences >= threshold)))
                if all_match:
                    result[kind] = [(0, len(values))]
    finally:
        raw.close()
    return result


def _append_span(spans, start, stop):
    if spans and start < spans[-1][1]:
        spans[-1] = (spans[-1][0], max(stop, spans[-1][1]))
    else:
        spans.append((start, stop))


def _robust_summary(row, config):
    indexes = np.unique(np.linspace(0, len(row) - 1, min(len(row), config.summary_sample_limit), dtype=int))
    sampled = np.asarray(row[indexes], dtype=np.float64)
    finite = sampled[np.isfinite(sampled)]
    delta_indexes = indexes[indexes > 0]
    with np.errstate(over="ignore", invalid="ignore"):
        differences = np.abs(np.asarray(row[delta_indexes], dtype=np.float64) - row[delta_indexes - 1])
    differences = differences[np.isfinite(differences)]
    enough = len(finite) >= config.minimum_robust_samples and len(differences) >= config.minimum_robust_samples
    with np.errstate(over="ignore", invalid="ignore"):
        median = float(np.median(finite)) if len(finite) else None
        scale = float(1.4826 * np.median(np.abs(finite - median))) if len(finite) else None
        difference_median = float(np.median(differences)) if len(differences) else None
        difference_mad = (float(1.4826 * np.median(np.abs(differences - difference_median)))
                          if len(differences) else None)
    median = median if median is not None and math.isfinite(median) else None
    scale = scale if scale is not None and math.isfinite(scale) else None
    difference_mad = difference_mad if difference_mad is not None and math.isfinite(difference_mad) else None
    valid_jump = enough and difference_mad is not None and difference_mad > 0
    peak = max(config.jump_min_step_uv * 1e-6,
               difference_median + config.jump_mad_multiplier * difference_mad) if valid_jump else None
    if peak is not None and not math.isfinite(peak * 1e6):
        peak, valid_jump = None, False
    return median, scale, peak, {
        "robust_sample_count": len(finite), "robust_summary_sampling": "bounded evenly spaced samples and adjacent differences",
        "jump_threshold_uv": peak * 1e6 if peak is not None else None,
        "jump_scale_status": "available" if valid_jump else "insufficient_or_degenerate",
    }


def _channel_patterns(row, sfreq, config, should_cancel):
    median, scale, peak, summary = _robust_summary(row, config)
    spans = {"flat": [], "peak": []}
    nonfinite, minimum, maximum = 0, math.inf, -math.inf
    localization_truncated = False
    digest = hashlib.sha256()
    for start in range(0, len(row), config.chunk_samples):
        _cancel(should_cancel)
        stop = min(len(row), start + config.chunk_samples)
        block = np.asarray(row[start:stop])
        digest.update(memoryview(np.ascontiguousarray(block)).cast("B"))
        finite = block[np.isfinite(block)]
        nonfinite += len(block) - len(finite)
        if len(finite):
            minimum, maximum = min(minimum, float(finite.min())), max(maximum, float(finite.max()))
        read_start = max(0, start - 1)
        if stop - read_start < 2:
            continue
        detected = _mne_segments(row[read_start:stop], sfreq, peak)
        for kind in spans:
            for left, right in detected[kind]:
                if len(spans[kind]) < config.max_events or (spans[kind] and read_start + left < spans[kind][-1][1]):
                    _append_span(spans[kind], read_start + left, read_start + right)
                else:
                    localization_truncated = True
    summary.update(nonfinite_sample_count=nonfinite, sample_count=len(row), input_sample_sha256=digest.hexdigest())
    summary["localization_truncated"] = localization_truncated
    summary["status"] = "unavailable" if nonfinite == len(row) else "partially_evaluated" if nonfinite or peak is None else "evaluated"
    events = []
    for start, stop in spans["flat"]:
        duration = (stop - start - 1) / sfreq
        if stop - start - 1 >= max(1, round(config.flatline_min_duration_s * sfreq)):
            events.append(("exact_flatline", start, stop, {"pattern_duration_s": duration}))
        value = float(row[start])
        if (stop - start - 1 >= max(1, round(config.plateau_min_duration_s * sfreq))
                and median is not None and scale is not None and scale > 0
                and math.isfinite(value * 1e6)
                and value in (minimum, maximum)
                and abs(value - median) >= max(config.plateau_min_deviation_uv * 1e-6, config.plateau_mad_multiplier * scale)):
            events.append(("candidate_clipping_plateau", start, stop,
                           {"pattern_duration_s": duration, "plateau_value_uv": value * 1e6}))
    events.extend(("abrupt_jump", start, stop,
                   {"pattern_duration_s": (stop - start - 1) / sfreq, "jump_threshold_uv": peak * 1e6})
                  for start, stop in spans["peak"])
    summary["pattern_summaries"] = {}
    for kind in ("exact_flatline", "candidate_clipping_plateau", "abrupt_jump"):
        rows = [event for event in events if event[0] == kind]
        summary["pattern_summaries"][kind] = {
            "observed_event_count": len(rows), "event_count_is_lower_bound": localization_truncated,
            "observed_pattern_duration_s": (None if localization_truncated else sum(row[3]["pattern_duration_s"] for row in rows)),
            "duration_interpretation": "Observed difference-pattern support in this occurrence; not artifact duration or clean coverage.",
        }
    return events, summary


def _occurrence_rows(occurrences, sample_count):
    rows = []
    for index, occurrence in enumerate(occurrences):
        start, stop = occurrence["start_sample"], occurrence["stop_sample"]
        if isinstance(start, bool) or isinstance(stop, bool) or int(start) != start or int(stop) != stop:
            raise ValueError("Occurrence bounds must be integer sample coordinates.")
        start, stop = int(start), int(stop)
        if not 0 <= start < stop <= sample_count:
            raise ValueError("Occurrence bounds lie outside the supplied signal.")
        rows.append({"start_sample": start, "stop_sample": stop,
                     "condition_label": str(occurrence.get("condition_label", occurrence.get("condition_id", "Unspecified"))),
                     "occurrence": int(occurrence.get("occurrence", occurrence.get("repetition_index", index))),
                     "occurrence_key": str(occurrence.get("occurrence_key", index))})
    if len({row["occurrence_key"] for row in rows}) != len(rows):
        raise ValueError("Occurrence keys must be unique.")
    return rows


def _spatial_holdout(data, names, positions, occurrence, excluded, config, should_cancel):
    if not config.enable_spatial_holdout:
        return {"status": "not_requested", "channels": [], "authority": _AUTHORITY}
    coordinates = _positions(names, positions)
    scalp = [name for name in names if name in coordinates]
    usable = [name for name in scalp if name not in excluded]
    if len(usable) - 1 < config.minimum_spatial_donors:
        return {"status": "insufficient_usable_donors", "channels": [], "authority": _AUTHORITY}
    start, stop = occurrence["start_sample"], occurrence["stop_sample"]
    indexes = np.unique(np.linspace(start, stop - 1, min(stop - start, config.summary_sample_limit), dtype=int))
    sampled = np.vstack([np.asarray(data[names.index(name), indexes], dtype=np.float64) for name in scalp])
    usable_indexes = [scalp.index(name) for name in usable]
    finite = np.isfinite(sampled[usable_indexes]).all(axis=0)
    sampled = sampled[:, finite]
    if sampled.shape[1] < config.minimum_robust_samples:
        return {"status": "insufficient_finite_samples", "channels": [], "authority": _AUTHORITY}
    montage = mne.channels.make_dig_montage(ch_pos={name: coordinates[name] for name in scalp}, coord_frame="head")
    results = []
    for target in usable[:config.max_holdout_channels]:
        _cancel(should_cancel)
        observed = sampled[scalp.index(target)].copy()
        scratch = mne.io.RawArray(sampled.copy(), mne.create_info(scalp, 1.0, "eeg"), verbose=False)
        try:
            scratch.set_montage(montage, verbose=False)
            scratch.info["bads"] = [name for name in scalp if name in excluded or name == target]
            scratch.interpolate_bads(reset_bads=False, mode="accurate", origin="auto", verbose=False)
            predicted = scratch._data[scalp.index(target)]
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                scale = float(np.std(observed))
                rmse = float(np.sqrt(np.mean((observed - predicted) ** 2)))
                corr = (float(np.corrcoef(observed, predicted)[0, 1])
                        if scale > 0 and float(np.std(predicted)) > 0 else None)
            if not math.isfinite(scale) or not math.isfinite(rmse * 1e6):
                results.append({"channel": target, "status": "unavailable", "reason": "Nonfinite spatial comparison."})
                continue
            results.append({"channel": target, "status": "available" if scale > 0 else "degenerate_observed_signal",
                            "rmse_uv": rmse * 1e6, "rmse_over_observed_sd": rmse / scale if scale > 0 else None,
                            "signed_correlation": corr if corr is None or math.isfinite(corr) else None,
                            "sample_count": len(observed), "donor_count": len(usable) - 1})
        except (ValueError, RuntimeError, np.linalg.LinAlgError) as error:
            results.append({"channel": target, "status": "unavailable", "reason": str(error)})
        finally:
            scratch.close()
    return {"status": "evaluated", "method": "MNE Raw.interpolate_bads EEG spline; target withheld",
            "channels": results, "authority": _AUTHORITY,
            "tested_channel_count": len(results), "usable_channel_count": len(usable),
            "limitations": ["Known usable electrodes are withheld for comparison; damaged-electrode truth is unknown.",
                            "These descriptive errors have no calibrated pass/fail threshold and do not authorize repair.",
                            "Evenly sampled values assess spatial interpolation, not continuous-time artifact detection."]}


def estimate_qc_spatial_support(
    data_volts: np.ndarray,
    *,
    channels: Sequence[str],
    positions: Mapping[str, Sequence[float]],
    start_sample: int = 0,
    stop_sample: int | None = None,
    unusable_channels: Sequence[str] = (),
    settings: QCReviewDiagnosticSettings | Mapping[str, Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Estimate spatial support on demand without re-running temporal detectors.

    Bounds index only the supplied array. Callers must label the array's signal
    stage and recording coverage; this function makes no recording-wide claim.
    """
    config, names = replace(_settings(settings), enable_spatial_holdout=True), _names(channels)
    data = np.asarray(data_volts)
    if data.ndim != 2 or data.shape[0] != len(names) or not np.issubdtype(data.dtype, np.floating):
        raise ValueError("data_volts must be a floating channel-by-sample array.")
    occurrence = _occurrence_rows([{"start_sample": start_sample,
                                    "stop_sample": data.shape[1] if stop_sample is None else stop_sample}], data.shape[1])[0]
    _cancel(should_cancel)
    report = _spatial_holdout(data, names, positions, occurrence, set(unusable_channels), config, should_cancel)
    report.update(start_sample=occurrence["start_sample"], stop_sample=occurrence["stop_sample"],
                  mne_version=mne.__version__, eligible_kurtosis_corroborator=False,
                  coverage="Supplied samples only; no whole-recording or damaged-electrode reconstruction conclusion.",
                  tested_channel_selection="First usable positioned channels in supplied order, bounded by max_holdout_channels.")
    lines = [report["coverage"], "MNE EEG spline comparison with each tested usable electrode withheld.",
             "Provisional review evidence; no calibrated pass/fail threshold or repair approval."]
    rows = report.get("channels", ())
    if not rows:
        lines.append(f"Spatial comparison unavailable: {report['status'].replace('_', ' ')}.")
    for row in rows:
        if row["status"] == "available":
            lines.append(f"{row['channel']}: RMSE {row['rmse_uv']:.3f} µV; RMSE/observed SD {row['rmse_over_observed_sd']:.3f}; "
                         f"{row['donor_count']} usable donors; {row['sample_count']} sampled values.")
        else:
            lines.append(f"{row['channel']}: {row['status'].replace('_', ' ')}.")
    lines.append(report["tested_channel_selection"])
    report["summary"] = "\n".join(lines)
    return report


def build_qc_review_diagnostics(
    data_volts: np.ndarray,
    *,
    sfreq: float,
    channels: Sequence[str],
    occurrences: Sequence[Mapping[str, Any]],
    positions: Mapping[str, Sequence[float]],
    signal_stage: str,
    proposed_repair_channels: Sequence[str] = (),
    confirmed_repaired_channels: Sequence[str] = (),
    unusable_channels: Sequence[str] = (),
    diagnostic_channels: Sequence[str] | None = None,
    sample_offset: int = 0,
    source_first_samp: int = 0,
    evaluation_scope: str = "supplied_occurrences",
    settings: QCReviewDiagnosticSettings | Mapping[str, Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Describe supplied occurrences without mutating arrays or granting authority.

    Occurrence bounds index ``data_volts``. ``sample_offset`` is the absolute
    source sample at data index zero; subtract ``source_first_samp`` to express
    event seconds on the recording-relative clock.
    """
    config, names = _settings(settings), _names(channels)
    data = np.asarray(data_volts)
    if data.ndim != 2 or data.shape[0] != len(names) or not np.issubdtype(data.dtype, np.floating):
        raise ValueError("data_volts must be a floating channel-by-sample array.")
    if (not math.isfinite(float(sfreq)) or sfreq <= 0
            or int(sample_offset) != sample_offset or int(source_first_samp) != source_first_samp):
        raise ValueError("A finite positive sampling rate and integer sample offset are required.")
    if evaluation_scope not in {"displayed_window", "supplied_occurrences", "all_analyzed_occurrences"}:
        raise ValueError("Unknown diagnostic evaluation scope.")
    selected = names if diagnostic_channels is None else _names(diagnostic_channels)
    if not set(selected).issubset(names):
        raise ValueError("Requested diagnostic channel is absent from supplied data.")
    spans = _occurrence_rows(occurrences, data.shape[1])
    events, summaries, holdouts = [], [], []
    omitted = 0
    excluded = set(unusable_channels).union(proposed_repair_channels, confirmed_repaired_channels)
    for occurrence in spans:
        for channel in selected:
            _cancel(should_cancel)
            start, stop = occurrence["start_sample"], occurrence["stop_sample"]
            local_events, summary = _channel_patterns(data[names.index(channel), start:stop], sfreq, config, should_cancel)
            summary.update(channel=channel, **occurrence)
            kinds = sorted({kind for kind, *_ in local_events})
            summary["observed_pattern_types"] = kinds
            summaries.append(summary)
            for kind, left, right, metrics in local_events:
                if len(events) >= config.max_events:
                    omitted += 1
                    continue
                first, last = sample_offset + start + left, sample_offset + start + right
                events.append({
                    "kind": kind, "channel": channel, **occurrence,
                    "start_sample": first, "stop_sample": last,
                    "start_s": (first - source_first_samp) / sfreq, "stop_s": (last - source_first_samp) / sfreq,
                    **metrics, "authority": _AUTHORITY,
                    "left_boundary_censored": left == 0, "right_boundary_censored": right == stop - start,
                    "interpretation": ("Repeated extreme plateau candidate; ADC saturation is not established."
                                       if kind == "candidate_clipping_plateau" else
                                       "Consecutive-difference transition support; not the duration of an ensuing artifact."
                                       if kind == "abrupt_jump" else
                                       "Observed exact equality interval; cause and repair need remain unknown."),
                })
        _cancel(should_cancel)
        holdouts.append({**occurrence, **_spatial_holdout(data, names, positions, occurrence, excluded, config, should_cancel)})
    shadow_channels = []
    for channel in selected:
        rows = [row for row in summaries if row["channel"] == channel]
        common = set(rows[0]["observed_pattern_types"]) if rows else set()
        for row in rows[1:]:
            common.intersection_update(row["observed_pattern_types"])
        scope_supported = (evaluation_scope == "all_analyzed_occurrences" and bool(rows)
                           and all(not row["nonfinite_sample_count"] and not row["localization_truncated"] for row in rows))
        shadow_channels.append({"channel": channel, "evaluated_occurrence_count": len(rows),
                                "same_pattern_in_every_supplied_occurrence": sorted(common),
                                "recording_scope_supported": scope_supported,
                                "persistence_status": ("insufficient_repeated_occurrences" if len(rows) < 2 else
                                                       "incomplete_scope" if not scope_supported else
                                                       "same_pattern_recurs" if common else "no_pattern_in_every_occurrence"),
                                "pattern_occurrence_counts": {
                                    kind: sum(kind in row["observed_pattern_types"] for row in rows)
                                    for kind in ("exact_flatline", "candidate_clipping_plateau", "abrupt_jump")
                                },
                                "whole_recording_repair_supported": False})
    report = {
        "version": QC_REVIEW_DIAGNOSTICS_VERSION, "mne_version": mne.__version__,
        "authority": _AUTHORITY, "calibration_status": "provisional_settings_synthetic_verification_only",
        "evaluation_scope": evaluation_scope, "signal_stage": str(signal_stage),
        "sfreq": float(sfreq), "sample_offset": int(sample_offset), "source_first_samp": int(source_first_samp),
        "event_time_origin": "recording_start", "event_sample_coordinates": "absolute_source_samples",
        "settings": asdict(config),
        "channels": list(selected), "occurrence_count": len(spans), "localized_events": events,
        "events_omitted_by_display_limit": omitted, "channel_summaries": summaries,
        "shadow_evidence": {"authority": _AUTHORITY, "eligible_kurtosis_corroborator": False,
                            "channels": shadow_channels, "spatial_holdouts": holdouts,
                            "evidence_relationship": "Pattern, amplitude, and spatial summaries are related evidence, not independent votes."},
        "repair_topology": {
            "proposed": review_repair_topology(names, positions, repair_channels=proposed_repair_channels, unusable_channels=excluded, settings=config),
            "confirmed": review_repair_topology(names, positions, repair_channels=confirmed_repaired_channels, unusable_channels=excluded, settings=config),
        },
        "limitations": [
            "MNE detectors are reused; these threshold choices have not been validated as artifact classifiers in representative recordings.",
            "Observed signal-pattern intervals are not validated artifact duration, and overlapping pattern types are not independent detections.",
            "Persistence means recurrence somewhere in every supplied occurrence, not continuous failure throughout those occurrences.",
            "Only raw acquisition samples can support acquisition-level flatline or clipping interpretation; preprocessing can change these patterns.",
            "No annotation, bad channel, interpolation decision, exclusion, or corroborator approval is applied.",
        ],
    }
    report["fingerprint"] = hashlib.sha256(json.dumps(report, sort_keys=True, allow_nan=False, separators=(",", ":")).encode()).hexdigest()
    return report


def format_qc_review_diagnostics(report: Mapping[str, Any], *, channel: str | None = None) -> str:
    """Format bounded, readable review evidence without raw implementation payloads."""
    scope = {
        "displayed_window": "Displayed raw window only; no whole-recording conclusion.",
        "supplied_occurrences": "Supplied occurrences only; coverage of the complete recording is not established.",
        "all_analyzed_occurrences": "All supplied analyzed occurrences; intervals outside analysis are not assessed.",
    }.get(str(report.get("evaluation_scope")), "Diagnostic coverage is unavailable.")
    events = [event for event in report.get("localized_events", ()) if channel is None or event.get("channel") == channel]
    lines = [scope, "Provisional review cues; no interpolation or exclusion is authorized.",
             f"{len(events)} displayed signal pattern(s); {report.get('occurrence_count', 0)} occurrence(s) supplied."]
    labels = {"exact_flatline": "Exact flatline", "candidate_clipping_plateau": "Candidate clipping plateau", "abrupt_jump": "Abrupt transition"}
    for event in events[:12]:
        lines.append(
            f"{event['channel']}: {labels.get(event['kind'], event['kind'])}, "
            f"{float(event['start_s']):.3f}–{float(event['stop_s']):.3f} s "
            f"({event.get('condition_label', 'Unspecified')}, occurrence {int(event.get('occurrence', 0)) + 1})."
        )
    if len(events) > 12 or report.get("events_omitted_by_display_limit"):
        lines.append("Additional patterns are omitted from this summary; listed events do not establish full clean coverage.")
    if not events:
        lines.append("No displayed pattern met these settings; this is not a clean-data classification.")
    for row in report.get("shadow_evidence", {}).get("channels", ()):
        if channel is not None and row.get("channel") != channel:
            continue
        kinds = row.get("same_pattern_in_every_supplied_occurrence", ())
        if kinds and row.get("persistence_status") == "same_pattern_recurs":
            lines.append(f"{row['channel']}: {', '.join(labels.get(kind, kind) for kind in kinds)} recurred somewhere in every analyzed occurrence; continuous failure is not established.")
    summaries = [row for row in report.get("channel_summaries", ()) if channel is None or row.get("channel") == channel]
    if any(row.get("nonfinite_sample_count") or row.get("jump_scale_status") != "available" or row.get("localization_truncated") for row in summaries):
        lines.append("Some evidence is unavailable or incomplete because of nonfinite data, insufficient/degenerate scale, or output limits.")
    lines.extend(["Pattern duration describes observed sample behavior, not validated artifact duration.",
                  "An extreme repeated plateau does not prove ADC saturation; related patterns are not independent votes."])
    return "\n".join(lines)


def build_raw_qc_review_diagnostics(
    raw,
    *,
    occurrences: Sequence[Mapping[str, Any]],
    ref_channels: Sequence[str] = (),
    unusable_channels: Sequence[str] = (),
    settings: QCReviewDiagnosticSettings | Mapping[str, Any] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Adapt an already-loaded source Raw without an all-channel sample copy."""
    if not getattr(raw, "preload", False):
        raise ValueError("Full-scope review diagnostics require an already-loaded source Raw.")
    channels = tuple(raw.ch_names)
    scalp = [name for name in channels if name in BIOSEMI64_CHANNEL_SET]
    selected = [name for name in channels if name in scalp or name in set(ref_channels)]
    coordinates = canonical_biosemi64_head_coordinates()
    positions = {name: coordinates[name] for name in scalp}
    return build_qc_review_diagnostics(
        raw._data, sfreq=float(raw.info["sfreq"]), channels=channels,
        diagnostic_channels=selected, occurrences=occurrences, positions=positions,
        signal_stage="loaded_raw_before_reference", evaluation_scope="all_analyzed_occurrences",
        sample_offset=int(raw.first_samp), source_first_samp=int(raw.first_samp), unusable_channels=unusable_channels,
        settings=settings, should_cancel=should_cancel,
    )

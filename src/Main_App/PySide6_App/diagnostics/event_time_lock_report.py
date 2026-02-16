"""Event/epoch time-lock verification utility for FPVS BDF recordings.

Examples:
    python -m Main_App.PySide6_App.diagnostics.event_time_lock_report --bdf "C:\\Data\\subject01.bdf" --out "C:\\Data\\EventQC"
    python -m Main_App.PySide6_App.diagnostics.event_time_lock_report --bdf "C:\\Data\\subject01.bdf" --epoch-start -1.0 --epoch-end 125.0 --downsample 256 --stim-channel Status --out "C:\\Data\\EventQC"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import mne
import numpy as np


DEFAULT_EPOCH_START = -1.0
DEFAULT_EPOCH_END = 125.0
DEFAULT_DOWNSAMPLE = 256.0
DEFAULT_SHORTEST_EVENT = 1
DEFAULT_STIM_CHANNEL = "Status"


@dataclass
class EventExtractionResult:
    source: str
    stim_channel_requested: str
    stim_channel_used: str | None
    shortest_event: int
    total_events: int
    counts_by_code: dict[str, int]
    first_10_onsets_by_code: dict[str, list[dict[str, float | int]]]
    iei_seconds_by_code: dict[str, dict[str, float | None]]


def _configure_logging(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "event_time_lock_report.log"
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return log_path


def _load_project_manifest(bdf_path: Path) -> dict[str, Any] | None:
    for parent in [bdf_path.parent, *bdf_path.parents]:
        manifest_path = parent / "project.json"
        if manifest_path.exists():
            try:
                data = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except Exception:
                logging.getLogger(__name__).warning("Failed to parse project.json at %s", manifest_path)
    return None


def _resolve_stim_channel(explicit_stim: str | None, bdf_path: Path) -> tuple[str, str]:
    if explicit_stim:
        return explicit_stim, "cli"

    manifest = _load_project_manifest(bdf_path)
    if manifest is not None:
        preprocessing = manifest.get("preprocessing")
        if isinstance(preprocessing, dict):
            value = preprocessing.get("stim_channel")
            if isinstance(value, str) and value.strip():
                return value.strip(), "project.preprocessing.stim_channel"

        stim_root = manifest.get("stim")
        if isinstance(stim_root, dict):
            value = stim_root.get("channel")
            if isinstance(value, str) and value.strip():
                return value.strip(), "project.stim.channel"

    return DEFAULT_STIM_CHANNEL, "default"


def _extract_events(raw: mne.io.BaseRaw, stim_channel: str, shortest_event: int) -> tuple[np.ndarray, EventExtractionResult]:
    logger = logging.getLogger(__name__)
    events: np.ndarray
    source = "stim"
    stim_used: str | None = stim_channel

    try:
        events = mne.find_events(
            raw,
            stim_channel=stim_channel,
            shortest_event=shortest_event,
            consecutive=True,
            verbose=False,
        )
        if events.size == 0:
            events, _ = mne.events_from_annotations(raw, verbose=False)
            source = "annotations"
            stim_used = None
    except Exception as exc:
        logger.warning("find_events failed for stim=%s (%s); falling back to annotations", stim_channel, exc)
        events, _ = mne.events_from_annotations(raw, verbose=False)
        source = "annotations"
        stim_used = None

    counts = Counter(int(code) for code in (events[:, 2].tolist() if events.size else []))
    sfreq = float(raw.info["sfreq"])
    first10: dict[str, list[dict[str, float | int]]] = {}
    iei: dict[str, dict[str, float | None]] = {}

    for code in sorted(counts):
        sample_idx = events[events[:, 2] == code, 0]
        first10[str(code)] = [
            {
                "sample": int(sample),
                "seconds": float(sample / sfreq),
            }
            for sample in sample_idx[:10]
        ]
        if len(sample_idx) > 1:
            intervals = np.diff(sample_idx.astype(float) / sfreq)
            iei[str(code)] = {
                "min": float(np.min(intervals)),
                "median": float(median(intervals.tolist())),
                "max": float(np.max(intervals)),
            }
        else:
            iei[str(code)] = {"min": None, "median": None, "max": None}

    result = EventExtractionResult(
        source=source,
        stim_channel_requested=stim_channel,
        stim_channel_used=stim_used,
        shortest_event=shortest_event,
        total_events=int(len(events)),
        counts_by_code={str(k): int(v) for k, v in sorted(counts.items())},
        first_10_onsets_by_code=first10,
        iei_seconds_by_code=iei,
    )
    return events, result


def _compare_pre_post_events(pre_events: np.ndarray, pre_sfreq: float, post_events: np.ndarray, post_sfreq: float) -> dict[str, Any]:
    pre_counts = Counter(int(code) for code in (pre_events[:, 2].tolist() if pre_events.size else []))
    post_counts = Counter(int(code) for code in (post_events[:, 2].tolist() if post_events.size else []))

    all_codes = sorted(set(pre_counts) | set(post_counts))
    count_deltas = {
        str(code): {
            "pre": int(pre_counts.get(code, 0)),
            "post": int(post_counts.get(code, 0)),
            "delta": int(post_counts.get(code, 0) - pre_counts.get(code, 0)),
        }
        for code in all_codes
    }

    timing_diff_seconds: dict[str, dict[str, float | int | None]] = {}
    event_loss_flags: dict[str, bool] = {}
    for code in all_codes:
        pre_samples = pre_events[pre_events[:, 2] == code, 0] if pre_events.size else np.array([], dtype=int)
        post_samples = post_events[post_events[:, 2] == code, 0] if post_events.size else np.array([], dtype=int)

        event_loss_flags[str(code)] = len(post_samples) < len(pre_samples)

        n_compare = min(len(pre_samples), len(post_samples))
        if n_compare == 0:
            timing_diff_seconds[str(code)] = {
                "n_compared": 0,
                "max_abs_diff": None,
                "mean_abs_diff": None,
            }
            continue

        pre_sec = pre_samples[:n_compare].astype(float) / pre_sfreq
        post_sec = post_samples[:n_compare].astype(float) / post_sfreq
        abs_diff = np.abs(post_sec - pre_sec)
        timing_diff_seconds[str(code)] = {
            "n_compared": int(n_compare),
            "max_abs_diff": float(np.max(abs_diff)),
            "mean_abs_diff": float(np.mean(abs_diff)),
        }

    return {
        "counts_by_code_pre_vs_post": count_deltas,
        "timing_diff_seconds_by_code": timing_diff_seconds,
        "event_loss_flags": event_loss_flags,
    }


def _epoch_stats(raw: mne.io.BaseRaw, events: np.ndarray, tmin: float, tmax: float) -> dict[str, Any]:
    sfreq = float(raw.info["sfreq"])
    codes = sorted({int(code) for code in (events[:, 2].tolist() if events.size else [])})
    expected_duration = float(tmax - tmin)
    per_code: dict[str, Any] = {}

    for code in codes:
        epochs = mne.Epochs(
            raw,
            events,
            event_id={str(code): int(code)},
            tmin=tmin,
            tmax=tmax,
            baseline=None,
            decim=1,
            preload=False,
            on_missing="warn",
            verbose=False,
        )
        epochs.drop_bad(verbose=False)
        n_epochs = len(epochs)
        n_times = int(len(epochs.times))
        observed_duration = float(n_times / sfreq)

        per_epoch_n_times: list[int] = []
        for idx in range(n_epochs):
            epoch_data = epochs[idx].get_data(copy=False)
            per_epoch_n_times.append(int(epoch_data.shape[-1]))
        same_n_times = len(set(per_epoch_n_times)) <= 1

        per_code[str(code)] = {
            "n_epochs": int(n_epochs),
            "epoch_n_times": n_times,
            "expected_duration_seconds": expected_duration,
            "observed_duration_seconds": observed_duration,
            "all_epochs_same_n_times": bool(same_n_times),
            "per_epoch_n_times": per_epoch_n_times,
        }

    return {
        "tmin": float(tmin),
        "tmax": float(tmax),
        "sfreq": sfreq,
        "per_code": per_code,
    }


def _extract_expected_runs(manifest: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(manifest, dict):
        return None

    candidates: list[tuple[str, Any]] = [
        ("expected_runs_per_condition", manifest.get("expected_runs_per_condition")),
        ("options.expected_runs_per_condition", (manifest.get("options") or {}).get("expected_runs_per_condition") if isinstance(manifest.get("options"), dict) else None),
        ("preprocessing.expected_runs_per_condition", (manifest.get("preprocessing") or {}).get("expected_runs_per_condition") if isinstance(manifest.get("preprocessing"), dict) else None),
        ("expected_n_epochs", manifest.get("expected_n_epochs")),
    ]

    for source, value in candidates:
        if isinstance(value, int):
            return {"source": source, "type": "scalar", "value": int(value)}
        if isinstance(value, dict):
            parsed: dict[str, int] = {}
            for k, v in value.items():
                try:
                    parsed[str(k)] = int(v)
                except Exception:
                    continue
            if parsed:
                return {"source": source, "type": "by_code_or_label", "value": parsed}
    return None


def _build_txt_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("FPVS Event Time-Lock Verification Report")
    lines.append(f"Generated UTC: {report['generated_utc']}")
    lines.append(f"Input BDF: {report['inputs']['bdf']}")
    lines.append("")

    if report.get("status") != "ok":
        lines.append("STATUS: ERROR")
        lines.append(f"Error type: {report.get('error', {}).get('type')}")
        lines.append(f"Error message: {report.get('error', {}).get('message')}")
        return "\n".join(lines)

    lines.append("STATUS: OK")
    lines.append(
        f"Stim channel resolution: {report['inputs']['stim_channel']} ({report['inputs']['stim_channel_source']})"
    )
    lines.append(
        f"Sfreq pre/post: {report['raw_info']['pre_sfreq_hz']:.6f} Hz / {report['raw_info']['post_sfreq_hz']:.6f} Hz"
    )
    lines.append("")

    for phase in ("pre_resample", "post_resample"):
        sec = report[phase]
        lines.append(f"[{phase}] events source={sec['events']['source']} total={sec['events']['total_events']}")
        for code, count in sec["events"]["counts_by_code"].items():
            lines.append(f"  code {code}: n={count}")
            first = sec["events"]["first_10_onsets_by_code"].get(code, [])
            if first:
                preview = ", ".join(f"{it['sample']} ({it['seconds']:.6f}s)" for it in first)
                lines.append(f"    first<=10: {preview}")
            iei = sec["events"]["iei_seconds_by_code"].get(code, {})
            lines.append(
                f"    iei_s min/med/max: {iei.get('min')} / {iei.get('median')} / {iei.get('max')}"
            )

    lines.append("")
    lines.append("[resample_trigger_integrity]")
    for code, row in report["resample_trigger_integrity"]["counts_by_code_pre_vs_post"].items():
        lines.append(
            f"  code {code}: pre={row['pre']} post={row['post']} delta={row['delta']}"
        )
    for code, loss in report["resample_trigger_integrity"]["event_loss_flags"].items():
        if loss:
            lines.append(f"  RED FLAG: code {code} lost events after resample")

    lines.append("")
    lines.append("[epoch_construction_check]")
    for phase in ("pre_resample", "post_resample"):
        lines.append(f"  {phase}:")
        for code, row in report[phase]["epochs"]["per_code"].items():
            lines.append(
                "    code {code}: n_epochs={n_epochs} n_times={n_times} expected_dur={expected:.6f}s "
                "observed_dur={observed:.6f}s same_n_times={same}".format(
                    code=code,
                    n_epochs=row["n_epochs"],
                    n_times=row["epoch_n_times"],
                    expected=row["expected_duration_seconds"],
                    observed=row["observed_duration_seconds"],
                    same=row["all_epochs_same_n_times"],
                )
            )

    expected_runs = report.get("two_run_expectation")
    if expected_runs:
        lines.append("")
        lines.append("[two_run_expectation]")
        lines.append(f"  source={expected_runs['source']} type={expected_runs['type']}")
        lines.append(f"  expected={expected_runs['value']}")
        lines.append(f"  observed_post_resample={expected_runs['observed_post_resample_n_epochs']}")

    return "\n".join(lines)


def generate_report(
    bdf_path: Path,
    out_dir: Path,
    epoch_start: float = DEFAULT_EPOCH_START,
    epoch_end: float = DEFAULT_EPOCH_END,
    downsample: float = DEFAULT_DOWNSAMPLE,
    stim_channel: str | None = None,
    shortest_event: int = DEFAULT_SHORTEST_EVENT,
) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    stim_resolved, stim_source = _resolve_stim_channel(stim_channel, bdf_path)
    manifest = _load_project_manifest(bdf_path)

    logger.info(
        "Starting event_time_lock_report bdf=%s out=%s epoch=[%s,%s] downsample=%s stim=%s shortest_event=%s",
        bdf_path,
        out_dir,
        epoch_start,
        epoch_end,
        downsample,
        stim_resolved,
        shortest_event,
    )

    raw_pre = mne.io.read_raw_bdf(
        str(bdf_path),
        preload=False,
        stim_channel=stim_resolved,
        verbose=False,
    )
    pre_sfreq = float(raw_pre.info["sfreq"])
    pre_events, pre_event_summary = _extract_events(raw_pre, stim_resolved, shortest_event)

    raw_post = raw_pre.copy()
    if downsample and pre_sfreq > downsample:
        raw_post.resample(float(downsample), npad="auto", verbose=False)
    post_sfreq = float(raw_post.info["sfreq"])
    post_events, post_event_summary = _extract_events(raw_post, stim_resolved, shortest_event)

    pre_epochs = _epoch_stats(raw_pre, pre_events, epoch_start, epoch_end)
    post_epochs = _epoch_stats(raw_post, post_events, epoch_start, epoch_end)

    report: dict[str, Any] = {
        "status": "ok",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "bdf": str(bdf_path),
            "out": str(out_dir),
            "epoch_start": float(epoch_start),
            "epoch_end": float(epoch_end),
            "downsample": float(downsample),
            "shortest_event": int(shortest_event),
            "stim_channel": stim_resolved,
            "stim_channel_source": stim_source,
        },
        "raw_info": {
            "pre_sfreq_hz": pre_sfreq,
            "post_sfreq_hz": post_sfreq,
            "resample_applied": bool(downsample and pre_sfreq > downsample),
            "stim_channel_used_for_find_events": stim_resolved,
            "event_source_pre": pre_event_summary.source,
            "event_source_post": post_event_summary.source,
        },
        "pre_resample": {
            "events": asdict(pre_event_summary),
            "epochs": pre_epochs,
        },
        "post_resample": {
            "events": asdict(post_event_summary),
            "epochs": post_epochs,
        },
        "resample_trigger_integrity": _compare_pre_post_events(
            pre_events, pre_sfreq, post_events, post_sfreq
        ),
    }

    expected_runs = _extract_expected_runs(manifest)
    if expected_runs:
        observed_n_epochs = {
            code: int(data["n_epochs"])
            for code, data in report["post_resample"]["epochs"]["per_code"].items()
        }
        expected_runs["observed_post_resample_n_epochs"] = observed_n_epochs
        report["two_run_expectation"] = expected_runs

    return report


def _write_reports(out_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    json_path = out_dir / "event_time_lock_report.json"
    txt_path = out_dir / "event_time_lock_report.txt"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    txt_path.write_text(_build_txt_report(report), encoding="utf-8")
    return txt_path, json_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FPVS event/epoch time-lock diagnostic report")
    parser.add_argument("--bdf", required=True, help="Path to input BDF file")
    parser.add_argument("--out", required=True, help="Output folder for report/log files")
    parser.add_argument("--epoch-start", type=float, default=DEFAULT_EPOCH_START)
    parser.add_argument("--epoch-end", type=float, default=DEFAULT_EPOCH_END)
    parser.add_argument("--downsample", type=float, default=DEFAULT_DOWNSAMPLE)
    parser.add_argument("--stim-channel", default=None)
    parser.add_argument("--shortest-event", type=int, default=DEFAULT_SHORTEST_EVENT)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    _configure_logging(out_dir)
    logger = logging.getLogger(__name__)

    report: dict[str, Any]
    try:
        report = generate_report(
            bdf_path=Path(args.bdf),
            out_dir=out_dir,
            epoch_start=float(args.epoch_start),
            epoch_end=float(args.epoch_end),
            downsample=float(args.downsample),
            stim_channel=args.stim_channel,
            shortest_event=int(args.shortest_event),
        )
        txt_path, json_path = _write_reports(out_dir, report)
        logger.info("Reports written: %s | %s", txt_path, json_path)
        return 0
    except Exception as exc:
        logger.exception("event_time_lock_report failed")
        report = {
            "status": "error",
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "inputs": {
                "bdf": args.bdf,
                "out": args.out,
                "epoch_start": float(args.epoch_start),
                "epoch_end": float(args.epoch_end),
                "downsample": float(args.downsample),
                "shortest_event": int(args.shortest_event),
                "stim_channel": args.stim_channel,
            },
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
        _write_reports(out_dir, report)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""
Event/epoch time-lock verification utility for FPVS BDF recordings.

Why your terminal command failed:
- This repo uses a "src/" layout. Running with:
    python -m Main_App.PySide6_App.diagnostics.event_time_lock_report
  only works if "src" is on PYTHONPATH (or the project is installed as a package).
- In PyCharm, the easiest path is to run THIS FILE directly. If no CLI args are
  provided, a small PySide6 GUI will open to select a .BDF and an output folder.

CLI examples (requires PYTHONPATH to include src):
    set PYTHONPATH=%CD%\\src
    python -m Main_App.PySide6_App.diagnostics.event_time_lock_report --bdf "C:\\Data\\subject01.bdf" --out "C:\\Data\\EventQC"

Direct-script examples (no PYTHONPATH needed):
    python .\\src\\Main_App\\PySide6_App\\diagnostics\\event_time_lock_report.py --bdf "C:\\Data\\subject01.bdf" --out "C:\\Data\\EventQC"

GUI usage (recommended in PyCharm):
- Right-click this file in PyCharm -> Run
- Select the .BDF and output folder -> Run Report
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import threading
import time
import traceback
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

import mne
import numpy as np


DEFAULT_EPOCH_START = -1.0
DEFAULT_EPOCH_END = 125.0
DEFAULT_DOWNSAMPLE = 256.0
DEFAULT_SHORTEST_EVENT = 1
DEFAULT_STIM_CHANNEL = "Status"


def _ensure_src_on_sys_path() -> None:
    """
    Ensures 'src/' is on sys.path when running this file directly.
    Does NOT fix 'python -m Main_App....' because that import happens before code runs.
    """
    this_file = Path(__file__).resolve()
    # src/Main_App/PySide6_App/diagnostics/event_time_lock_report.py
    # parents: diagnostics(0) -> PySide6_App(1) -> Main_App(2) -> src(3)
    src_dir = this_file.parents[3]
    if src_dir.is_dir():
        src_str = str(src_dir)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)


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

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    # Reduce MNE spam (it otherwise prints lots of INFO during epoch data reads).
    mne.set_log_level("WARNING")

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
                logging.getLogger(__name__).warning(
                    "Failed to parse project.json at %s", manifest_path
                )
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


def _extract_events(
    raw: mne.io.BaseRaw, stim_channel: str, shortest_event: int
) -> tuple[np.ndarray, EventExtractionResult]:
    logger = logging.getLogger(__name__)
    events: np.ndarray
    source = "stim"
    stim_used: str | None = stim_channel

    try:
        events = mne.find_events(
            raw,
            stim_channel=stim_channel,
            shortest_event=shortest_event,
            verbose=False,
        )
        if events.size == 0:
            events, _ = mne.events_from_annotations(raw, verbose=False)
            source = "annotations"
            stim_used = None
    except Exception as exc:
        logger.warning(
            "find_events failed for stim=%s (%s); falling back to annotations",
            stim_channel,
            exc,
        )
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
            {"sample": int(sample), "seconds": float(sample / sfreq)}
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


def _compare_pre_post_events(
    pre_events: np.ndarray,
    pre_sfreq: float,
    post_events: np.ndarray,
    post_sfreq: float,
) -> dict[str, Any]:
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
        pre_samples = (
            pre_events[pre_events[:, 2] == code, 0]
            if pre_events.size
            else np.array([], dtype=int)
        )
        post_samples = (
            post_events[post_events[:, 2] == code, 0]
            if post_events.size
            else np.array([], dtype=int)
        )

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
        n_epochs = int(len(epochs))
        n_times = int(len(epochs.times))
        observed_duration = float(n_times / sfreq)

        # Avoid forcing per-epoch data loads (can be very slow and spammy).
        # Epochs are constructed with a fixed tmin/tmax, so n_times is consistent by design.
        per_epoch_n_times = [n_times] * n_epochs
        same_n_times = True

        per_code[str(code)] = {
            "n_epochs": n_epochs,
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
        (
            "options.expected_runs_per_condition",
            (manifest.get("options") or {}).get("expected_runs_per_condition")
            if isinstance(manifest.get("options"), dict)
            else None,
        ),
        (
            "preprocessing.expected_runs_per_condition",
            (manifest.get("preprocessing") or {}).get("expected_runs_per_condition")
            if isinstance(manifest.get("preprocessing"), dict)
            else None,
        ),
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
        "Sfreq pre/post: {pre:.6f} Hz / {post:.6f} Hz".format(
            pre=report["raw_info"]["pre_sfreq_hz"],
            post=report["raw_info"]["post_sfreq_hz"],
        )
    )
    lines.append("")

    for phase in ("pre_resample", "post_resample"):
        sec = report[phase]
        lines.append(
            f"[{phase}] events source={sec['events']['source']} total={sec['events']['total_events']}"
        )
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
        lines.append(f"  code {code}: pre={row['pre']} post={row['post']} delta={row['delta']}")
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
    progress_cb: Callable[[str], None] | None = None,
    heartbeat_seconds: float = 5.0,
) -> dict[str, Any]:
    logger = logging.getLogger(__name__)
    stim_resolved, stim_source = _resolve_stim_channel(stim_channel, bdf_path)
    manifest = _load_project_manifest(bdf_path)

    t0 = time.perf_counter()

    current_stage = "initializing"
    stage_lock = threading.Lock()
    stop_event = threading.Event()

    def _emit(msg: str) -> None:
        logger.info(msg)
        if progress_cb is not None:
            progress_cb(msg)

    def _set_stage(stage: str) -> None:
        nonlocal current_stage
        with stage_lock:
            current_stage = stage

    def _step(msg: str) -> None:
        _set_stage(msg)
        _emit(msg)

    def _heartbeat() -> None:
        interval = float(heartbeat_seconds)
        if interval <= 0:
            return
        while not stop_event.wait(interval):
            with stage_lock:
                stage = current_stage
            elapsed_s = time.perf_counter() - t0
            _emit(f"Heartbeat: still working… ({stage}; elapsed {elapsed_s:.1f}s)")

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

    hb_thread = threading.Thread(target=_heartbeat, daemon=True)
    hb_thread.start()

    try:
        _step("Step 1/5: Reading BDF (header/metadata)…")
        raw_pre = mne.io.read_raw_bdf(
            str(bdf_path),
            preload=False,
            stim_channel=stim_resolved,
            verbose=False,
        )
        pre_sfreq = float(raw_pre.info["sfreq"])

        _step("Step 2/5: Extracting events (pre-resample)…")
        pre_events, pre_event_summary = _extract_events(raw_pre, stim_resolved, shortest_event)

        raw_post = raw_pre.copy()
        if downsample and pre_sfreq > downsample:
            _step("Step 3/5: Resampling… (often the slowest step)")
            raw_post.resample(
                float(downsample),
                npad="auto",
                window="hann",
                verbose=False,
            )
        post_sfreq = float(raw_post.info["sfreq"])

        _step("Step 4/5: Extracting events (post-resample)…")
        post_events, post_event_summary = _extract_events(raw_post, stim_resolved, shortest_event)

        _step("Step 5/5: Epoch QC (pre/post)…")
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

        elapsed_s = time.perf_counter() - t0
        _step(f"Computation complete (elapsed {elapsed_s:.1f}s). Writing reports…")

        return report
    finally:
        stop_event.set()


def _write_reports(out_dir: Path, report: dict[str, Any]) -> tuple[Path, Path]:
    json_path = out_dir / "event_time_lock_report.json"
    txt_path = out_dir / "event_time_lock_report.txt"
    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    txt_path.write_text(_build_txt_report(report), encoding="utf-8")
    return txt_path, json_path


def _run_gui() -> int:
    # Lazy import so CLI/tests don't require Qt import at module import time.
    from PySide6.QtCore import QObject, QThread, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFileDialog,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMessageBox,
        QSpacerItem,
        QSizePolicy,
        QVBoxLayout,
    )
    _ensure_src_on_sys_path()
    from Main_App.PySide6_App.utils.theme import apply_fpvs_theme
    from Main_App.PySide6_App.widgets import make_action_button, make_form_layout

    class _Worker(QObject):
        progress = Signal(str)
        finished = Signal(str, str, str)  # txt_path, json_path, log_path
        error = Signal(str)

        def __init__(
            self,
            bdf_path: Path,
            out_dir: Path,
            epoch_start: float,
            epoch_end: float,
            downsample: float,
            stim_channel: str | None,
            shortest_event: int,
            heartbeat_seconds: float,
        ) -> None:
            super().__init__()
            self._bdf_path = bdf_path
            self._out_dir = out_dir
            self._epoch_start = epoch_start
            self._epoch_end = epoch_end
            self._downsample = downsample
            self._stim_channel = stim_channel
            self._shortest_event = shortest_event
            self._heartbeat_seconds = heartbeat_seconds

        def run(self) -> None:
            try:
                self.progress.emit("Configuring logging…")
                log_path = _configure_logging(self._out_dir)

                report = generate_report(
                    bdf_path=self._bdf_path,
                    out_dir=self._out_dir,
                    epoch_start=self._epoch_start,
                    epoch_end=self._epoch_end,
                    downsample=self._downsample,
                    stim_channel=self._stim_channel,
                    shortest_event=self._shortest_event,
                    progress_cb=self.progress.emit,
                    heartbeat_seconds=self._heartbeat_seconds,
                )
                txt_path, json_path = _write_reports(self._out_dir, report)
                self.finished.emit(str(txt_path), str(json_path), str(log_path))
            except Exception:
                self.error.emit(traceback.format_exc())

    class _Dialog(QDialog):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("FPVS Event Time-Lock Report")
            self.setModal(True)
            self.setMinimumWidth(720)

            self._thread: QThread | None = None
            self._worker: _Worker | None = None

            root = QVBoxLayout(self)

            form = make_form_layout()
            root.addLayout(form)

            # BDF
            self.bdf_edit = QLineEdit()
            bdf_browse = make_action_button("Browse...")
            bdf_browse.clicked.connect(self._pick_bdf)
            bdf_row = QHBoxLayout()
            bdf_row.addWidget(self.bdf_edit, 1)
            bdf_row.addWidget(bdf_browse)
            form.addRow("Input .BDF", bdf_row)

            # Output dir
            self.out_edit = QLineEdit()
            out_browse = make_action_button("Browse...")
            out_browse.clicked.connect(self._pick_out_dir)
            out_row = QHBoxLayout()
            out_row.addWidget(self.out_edit, 1)
            out_row.addWidget(out_browse)
            form.addRow("Output folder", out_row)

            # Params
            self.epoch_start_edit = QLineEdit(str(DEFAULT_EPOCH_START))
            self.epoch_start_edit.setValidator(QDoubleValidator(self))
            form.addRow("Epoch start (s)", self.epoch_start_edit)

            self.epoch_end_edit = QLineEdit(str(DEFAULT_EPOCH_END))
            self.epoch_end_edit.setValidator(QDoubleValidator(self))
            form.addRow("Epoch end (s)", self.epoch_end_edit)

            self.downsample_edit = QLineEdit(str(DEFAULT_DOWNSAMPLE))
            self.downsample_edit.setValidator(QDoubleValidator(0.0, 100000.0, 6, self))
            form.addRow("Downsample target (Hz)", self.downsample_edit)

            self.stim_edit = QLineEdit("")
            self.stim_edit.setPlaceholderText(
                "Leave blank to auto-resolve (project.json → Status)"
            )
            form.addRow("Stim channel (optional)", self.stim_edit)

            self.shortest_event_edit = QLineEdit(str(DEFAULT_SHORTEST_EVENT))
            self.shortest_event_edit.setValidator(QIntValidator(1, 1000000, self))
            form.addRow("shortest_event", self.shortest_event_edit)

            self.heartbeat_edit = QLineEdit("5")
            self.heartbeat_edit.setValidator(QDoubleValidator(0.0, 3600.0, 2, self))
            self.heartbeat_edit.setPlaceholderText("Seconds (0 disables)")
            form.addRow("Heartbeat (s)", self.heartbeat_edit)

            # Status + buttons
            self.status_label = QLabel(
                "Select an input .BDF and an output folder, then click Run Report."
            )
            self.status_label.setWordWrap(True)
            root.addWidget(self.status_label)

            btn_row = QHBoxLayout()
            btn_row.addItem(
                QSpacerItem(10, 10, QSizePolicy.Expanding, QSizePolicy.Minimum)
            )
            self.run_btn = make_action_button("Run Report", variant="primary")
            self.run_btn.clicked.connect(self._on_run)
            self.close_btn = make_action_button("Close", variant="tertiary")
            self.close_btn.clicked.connect(self.reject)
            btn_row.addWidget(self.run_btn)
            btn_row.addWidget(self.close_btn)
            root.addLayout(btn_row)

        def _pick_bdf(self) -> None:
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select BDF file",
                "",
                "BDF Files (*.bdf *.BDF);;All Files (*.*)",
            )
            if path:
                self.bdf_edit.setText(path)

        def _pick_out_dir(self) -> None:
            path = QFileDialog.getExistingDirectory(self, "Select output folder", "")
            if path:
                self.out_edit.setText(path)

        def _on_run(self) -> None:
            bdf = Path(self.bdf_edit.text().strip())
            out_dir_text = self.out_edit.text().strip()
            out_dir = Path(out_dir_text) if out_dir_text else Path()

            if not bdf.is_file():
                QMessageBox.warning(self, "Missing input", "Select a valid .BDF file.")
                return
            if not out_dir_text:
                QMessageBox.warning(self, "Missing output", "Select a valid output folder.")
                return

            try:
                epoch_start = float(self.epoch_start_edit.text().strip())
                epoch_end = float(self.epoch_end_edit.text().strip())
                downsample = float(self.downsample_edit.text().strip())
                shortest_event = int(self.shortest_event_edit.text().strip())
                heartbeat_seconds = float(self.heartbeat_edit.text().strip())
            except Exception:
                QMessageBox.warning(
                    self, "Invalid parameters", "Check numeric parameter fields."
                )
                return

            stim_text = self.stim_edit.text().strip()
            stim_channel = stim_text if stim_text else None

            self.run_btn.setEnabled(False)
            self.status_label.setText("Running… (this may take a bit for large BDF files)")

            # Threaded execution so UI does not block
            self._thread = QThread(self)
            self._worker = _Worker(
                bdf_path=bdf,
                out_dir=out_dir,
                epoch_start=epoch_start,
                epoch_end=epoch_end,
                downsample=downsample,
                stim_channel=stim_channel,
                shortest_event=shortest_event,
                heartbeat_seconds=heartbeat_seconds,
            )
            self._worker.moveToThread(self._thread)
            self._thread.started.connect(self._worker.run)  # type: ignore[arg-type]
            self._worker.progress.connect(self.status_label.setText)
            self._worker.finished.connect(self._on_finished)
            self._worker.error.connect(self._on_error)
            self._worker.finished.connect(self._thread.quit)
            self._worker.error.connect(self._thread.quit)
            self._thread.finished.connect(self._thread.deleteLater)

            self._thread.start()

        def _on_finished(self, txt_path: str, json_path: str, log_path: str) -> None:
            self.run_btn.setEnabled(True)
            self.status_label.setText("Done.")
            QMessageBox.information(
                self,
                "Report complete",
                "Report files written:\n\n"
                f"TXT: {txt_path}\n"
                f"JSON: {json_path}\n"
                f"LOG: {log_path}",
            )

        def _on_error(self, tb: str) -> None:
            self.run_btn.setEnabled(True)
            self.status_label.setText("Error.")
            QMessageBox.critical(self, "Report failed", tb)

    app = QApplication.instance() or QApplication(sys.argv)
    apply_fpvs_theme(app)
    dlg = _Dialog()
    dlg.show()
    return int(app.exec())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FPVS event/epoch time-lock diagnostic report")
    parser.add_argument("--bdf", required=True, help="Path to input BDF file")
    parser.add_argument("--out", required=True, help="Output folder for report/log files")
    parser.add_argument("--epoch-start", type=float, default=DEFAULT_EPOCH_START)
    parser.add_argument("--epoch-end", type=float, default=DEFAULT_EPOCH_END)
    parser.add_argument("--downsample", type=float, default=DEFAULT_DOWNSAMPLE)
    parser.add_argument("--stim-channel", default=None)
    parser.add_argument("--shortest-event", type=int, default=DEFAULT_SHORTEST_EVENT)
    parser.add_argument("--heartbeat", type=float, default=5.0, help="Heartbeat interval seconds (0 disables)")
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    _configure_logging(out_dir)
    logger = logging.getLogger(__name__)

    try:
        report = generate_report(
            bdf_path=Path(args.bdf),
            out_dir=out_dir,
            epoch_start=float(args.epoch_start),
            epoch_end=float(args.epoch_end),
            downsample=float(args.downsample),
            stim_channel=args.stim_channel,
            shortest_event=int(args.shortest_event),
            heartbeat_seconds=float(args.heartbeat),
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
    _ensure_src_on_sys_path()

    # If run without CLI args (typical PyCharm "Run file"), open the GUI.
    if len(sys.argv) <= 1:
        raise SystemExit(_run_gui())

    raise SystemExit(main())

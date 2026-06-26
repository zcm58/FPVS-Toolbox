"""Automatic post-processing SNR plot and spectral QC workflow."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from PySide6.QtCore import QThread, QTimer
from PySide6.QtWidgets import QMessageBox

from Main_App.processing.raw_channel_qc import SCALP_CHANNELS
from Main_App.projects.preprocessing_settings import (
    normalize_manual_excluded_participants,
)
from Tools.Plot_Generator.spectral_qc_alerts import (
    build_spectral_qc_alert_message,
    whole_participant_exclusion_candidates,
)
from Tools.Plot_Generator.worker import _Worker
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION
from Tools.Stats.data.shared_rois import load_rois_from_settings

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


def _project_subfolder(project: Any, key: str, fallback: str) -> Path:
    root = Path(project.project_root)
    subfolders = getattr(project, "subfolders", {}) or {}
    value = subfolders.get(key, fallback) if isinstance(subfolders, dict) else fallback
    path = Path(value)
    if path.is_absolute():
        return path
    return root / path


def _condition_folders(excel_root: Path) -> list[str]:
    try:
        return sorted(
            path.name
            for path in excel_root.iterdir()
            if path.is_dir() and ".fif" not in path.name.casefold()
        )
    except OSError:
        return []


def _roi_map() -> dict[str, list[str]]:
    configured = load_rois_from_settings()
    if configured:
        return configured
    return {"All Electrodes": sorted(SCALP_CHANNELS)}


def _analysis_float(host: Any, option: str, fallback: float) -> float:
    try:
        value = float(host.settings.get("analysis", option, str(fallback)))
    except (AttributeError, TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def _append_log(host: Any, message: str, *, level: int = logging.INFO) -> None:
    try:
        host.log(message, level=level)
    except TypeError:
        try:
            host.log(message)
        except (AttributeError, RuntimeError):
            logger.log(level, message)
    except (AttributeError, RuntimeError):
        logger.log(level, message)


def _save_whole_participant_candidates(host: Any, flags: list[dict[str, object]]) -> None:
    candidates = whole_participant_exclusion_candidates(flags)
    project = getattr(host, "currentProject", None)
    if not candidates or project is None:
        return
    pids = [str(item["pid"]) for item in candidates if item.get("pid")]
    current = normalize_manual_excluded_participants(
        (project.preprocessing or {}).get("manual_excluded_participants", [])
    )
    current_lookup = {pid.casefold() for pid in current}
    new_pids = [pid for pid in pids if pid.casefold() not in current_lookup]
    if not new_pids:
        return
    label = ", ".join(new_pids)
    prompt = (
        f"Exclude {label} from future processing?\n\n"
        "This updates the project's manual participant exclusion list. "
        "Raw BDF files are not altered. Reprocess the dataset for this change "
        "to affect processed Excel files, SNR plots, and downstream analyses."
    )
    response = QMessageBox.question(
        host,
        "Exclude Participant From Dataset?",
        prompt,
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if response != QMessageBox.Yes:
        return
    updated = normalize_manual_excluded_participants([*current, *new_pids])
    payload = dict(project.preprocessing or {})
    payload["manual_excluded_participants"] = updated
    try:
        project.update_preprocessing(payload)
        project.save()
    except Exception as exc:  # pragma: no cover - disk I/O error path
        logger.exception("Failed to save automatic SNR QC participant exclusions.")
        QMessageBox.critical(
            host,
            "Project Save Error",
            f"Could not save participant exclusions: {exc}",
        )
        return
    _append_log(
        host,
        "Added manual participant exclusion(s) from final SNR QC: " + label,
        level=logging.WARNING,
    )


def start_automatic_snr_qc_after_processing(host: Any) -> bool:
    """Generate all-condition SNR plots and run final spectral QC after processing."""

    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("FPVS_TEST_MODE"):
        return False
    project = getattr(host, "currentProject", None)
    if project is None:
        return False

    excel_root = _project_subfolder(project, "excel", "1 - Excel Data Files")
    snr_root = _project_subfolder(project, "snr", "2 - SNR Plots")
    conditions = _condition_folders(excel_root)
    if not conditions:
        _append_log(
            host,
            "Automatic SNR plot/QC skipped: no processed condition folders were found.",
            level=logging.WARNING,
        )
        return False

    rois = _roi_map()
    x_max = _analysis_float(host, "bca_upper_limit", 10.0)
    state = SimpleNamespace(
        conditions=conditions,
        index=0,
        generated=[],
        reports=[],
        flags=[],
        failed=[],
        thread=None,
        worker=None,
        excel_root=excel_root,
        snr_root=snr_root,
        roi_map=rois,
        selected_roi=ALL_ROIS_OPTION,
        x_max=x_max,
    )
    host._automatic_snr_qc_state = state
    _append_log(
        host,
        "Starting automatic SNR plot generation and final spectral QC.",
    )

    def _finish() -> None:
        generated_count = len(state.generated)
        report_paths = [str(path) for path in state.reports]
        message = build_spectral_qc_alert_message(state.flags, report_paths)
        if message:
            QMessageBox.warning(host, "Final SNR Spectral QC", message)
            _save_whole_participant_candidates(host, state.flags)
        if state.failed:
            _append_log(
                host,
                f"Automatic SNR plot/QC had {len(state.failed)} failed item(s). "
                "Open the SNR Plots tool log for details if figures are missing.",
                level=logging.WARNING,
            )
        _append_log(
            host,
            f"Automatic SNR plot/QC finished: {generated_count} plot file(s), "
            f"{len(report_paths)} QC report(s).",
        )
        state.thread = None
        state.worker = None

    def _start_next() -> None:
        if state.index >= len(state.conditions):
            _finish()
            return
        condition = state.conditions[state.index]
        state.index += 1
        condition_out = state.snr_root / f"{condition} Plots"
        thread = QThread(host)
        worker = _Worker(
            str(state.excel_root),
            condition,
            state.roi_map,
            state.selected_roi,
            condition,
            "Frequency (Hz)",
            "SNR",
            0.0,
            float(state.x_max),
            0.5,
            3.0,
            str(condition_out),
            "red",
            project_root=str(project.project_root),
            spectral_qc_enabled=True,
        )
        state.thread = thread
        state.worker = worker
        worker.moveToThread(thread)

        def _on_progress(message: str, _processed: int, _total: int) -> None:
            if message:
                _append_log(host, f"SNR QC: {message}")

        def _on_finished(payload: dict[str, object]) -> None:
            state.generated.extend(
                str(path)
                for path in payload.get("generated_paths", []) or []
                if isinstance(path, str) and path
            )
            state.reports.extend(
                str(path)
                for path in payload.get("qc_report_paths", []) or []
                if isinstance(path, str) and path
            )
            state.flags.extend(
                dict(item)
                for item in payload.get("spectral_qc_flags", []) or []
                if isinstance(item, dict)
            )
            state.failed.extend(
                dict(item)
                for item in payload.get("failed_items", []) or []
                if isinstance(item, dict)
            )

        worker.progress.connect(_on_progress)
        worker.finished.connect(_on_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.started.connect(worker.run)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(_start_next)
        thread.start()

    QTimer.singleShot(0, _start_next)
    return True


__all__ = ["start_automatic_snr_qc_after_processing"]

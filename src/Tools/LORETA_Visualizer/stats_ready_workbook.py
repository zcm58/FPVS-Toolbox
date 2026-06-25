"""Stats-ready workbook generation helpers for the LORETA Visualizer."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from Main_App import SettingsManager
from Main_App.projects.project import STATS_SUBFOLDER_NAME
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    GROUP_SIGNIFICANT_POLICY_NAME,
)
from Tools.Stats.data.shared_rois import load_rois_from_settings
from Tools.Stats.data.stats_data_loader import (
    map_subjects_to_groups,
    normalize_participants_map,
    scan_folder_simple,
)
from Tools.Stats.io.stats_ready_export import STATS_READY_WORKBOOK_NAME, prepare_stats_ready_export


@dataclass(frozen=True)
class LoretaStatsReadyExportResult:
    """Summary of a Stats-ready workbook generated from the LORETA workflow."""

    workbook_path: Path
    row_count: int
    sheet_names: tuple[str, ...]
    subject_count: int
    condition_count: int


def default_loreta_stats_ready_workbook_path(project_root: str | Path) -> Path:
    """Return the workbook path currently required by LORETA project source-map producers."""

    return Path(project_root) / STATS_SUBFOLDER_NAME / STATS_READY_WORKBOOK_NAME


def stats_ready_workbook_exists(project_root: str | Path) -> bool:
    """Return whether the LORETA prerequisite Stats-ready workbook already exists."""

    return default_loreta_stats_ready_workbook_path(project_root).is_file()


def write_loreta_stats_ready_workbook(
    project_root: str | Path,
    *,
    log_callback: Callable[[str], None] | None = None,
) -> LoretaStatsReadyExportResult:
    """Generate the Stats-ready workbook needed before project source-map visualization."""

    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Project folder does not exist: {root}")

    log = log_callback or (lambda _message: None)
    log("Scanning processed project workbooks for the LORETA summary report...")
    subjects, conditions, subject_data = scan_folder_simple(str(root))
    if not subjects or not conditions:
        raise RuntimeError(
            "No processed participant workbooks were found. Process the project data before generating the "
            "LORETA summary report."
        )

    manager = SettingsManager()
    rois = load_rois_from_settings(manager)
    if not rois:
        raise RuntimeError("No ROI definitions were found in Settings. Add at least one ROI before generating the report.")

    base_freq = _settings_float(manager, "analysis", "base_freq", default=6.0)
    max_freq = _settings_float(manager, "analysis", "bca_upper_limit", default=None)
    manifest = _load_project_manifest(root)
    group_map = map_subjects_to_groups(subjects, normalize_participants_map(manifest))
    workbook_path = default_loreta_stats_ready_workbook_path(root)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)

    export = prepare_stats_ready_export(
        subjects=list(subjects),
        conditions=list(conditions),
        subject_data=subject_data,
        base_freq=base_freq,
        rois=rois,
        dv_policy={
            "name": GROUP_SIGNIFICANT_POLICY_NAME,
            "fixed_harmonic_frequencies_hz": FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
            "fixed_harmonic_auto_exclude_base": True,
        },
        group_map=group_map,
        log_func=log,
        save_path=workbook_path,
        max_freq=max_freq,
        selection_conditions=list(conditions),
        project_root=str(root),
    )
    if export.workbook_path is None:
        raise RuntimeError("Stats-ready workbook generation finished without writing a workbook.")

    return LoretaStatsReadyExportResult(
        workbook_path=Path(export.workbook_path),
        row_count=int(export.row_count),
        sheet_names=tuple(str(name) for name in export.frames.keys()),
        subject_count=len(subjects),
        condition_count=len(conditions),
    )


def _load_project_manifest(project_root: Path) -> dict | None:
    manifest_path = project_root / "project.json"
    if not manifest_path.is_file():
        return None
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _settings_float(
    manager: SettingsManager,
    section: str,
    option: str,
    *,
    default: float | None,
) -> float | None:
    fallback = "" if default is None else str(default)
    raw_value = manager.get(section, option, fallback)
    if raw_value in (None, ""):
        return default
    value = float(raw_value)
    if value <= 0:
        return default
    return value

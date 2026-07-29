"""Shared imports for the internal StatsWindow mixin modules.

This module exists to keep the split Stats window modules
mechanical and behavior-preserving. New code should prefer direct imports.
"""
# ruff: noqa: F401

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
from datetime import datetime
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QAbstractItemView,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSplitter,
    QSpinBox,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# Qt imports proof: QAction from PySide6.QtGui
from Main_App import SettingsManager
from Main_App.projects.project import (
    EXCEL_SUBFOLDER_NAME,
    STATS_SUBFOLDER_NAME,
)
from Main_App.gui.op_guard import OpGuard
from Main_App.gui.components import (
    ActionRow,
    BrainPulseWidget,
    BusySpinner,
    SectionCard,
    SubsectionHeaderLabel,
    SurfaceSize,
    StatusBanner,
    configure_window_surface,
    make_action_button,
    make_form_layout,
)
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION, set_rois
from Tools.Stats.reporting.stats_export import (
    export_mixed_model_results_to_excel,
    export_posthoc_results_to_excel,
    export_rm_anova_results_to_excel,
)
from Tools.Stats.data.shared_rois import apply_rois_to_modules, load_rois_from_settings
from Tools.Stats.controller.stats_controller import StatsController
from Tools.Stats.common.stats_core import (
    ANOVA_XLS,
    BASELINE_VS_ZERO_XLS,
    LMM_XLS,
    PipelineId,
    PipelineStep,
    POSTHOC_XLS,
    RESULTS_SUBFOLDER_NAME,
    StepId,
)
from Tools.Stats.data.stats_data_loader import (
    check_for_open_excel_files,
    ensure_results_dir,
    is_multi_group_project_config,
    map_subjects_to_groups,
    ScanError,
    auto_detect_project_dir,
    load_manifest_data,
    load_project_scan,
    safe_export_call,
    resolve_project_subfolder,
)
from Tools.Stats.io.stats_ready_export import STATS_READY_WORKBOOK_NAME
from Tools.Stats.reporting.stats_logging import format_log_line, format_section_header
from Tools.Stats.analysis.baseline_vs_zero import export_baseline_vs_zero_results_to_excel
from Tools.Stats.reporting.stats_export_formatting import (
    apply_baseline_vs_zero_number_formats,
    apply_lmm_number_formats_and_metadata,
    apply_rm_anova_pvalue_number_formats,
    log_rm_anova_p_minima,
)
from Tools.Stats.workers.stats_workers import StatsWorker
from Tools.Stats.workers import stats_workers as stats_worker_funcs
from Tools.Stats.analysis.dv_policies import (
    FIXED_PREDEFINED_DEFAULT_FREQUENCIES,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_NAME,
)
from Tools.Stats.qc.stats_outlier_exclusion import (
    build_flagged_details_map,
    build_flagged_participant_summary,
    collect_flagged_pid_map,
    build_flagged_participants_tables,
    export_excluded_participants_report,
    export_flagged_participants_report,
    format_flag_types_display,
    format_worst_value_display,
    outlier_reason_label,
)
from Tools.Stats.qc.stats_qc_exclusion import (
    QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
    QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
    QC_DEFAULT_CRITICAL_THRESHOLD,
    QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
    QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
    QC_DEFAULT_WARN_THRESHOLD,
)
from Tools.Stats.reporting.stats_run_report import StatsRunReport
from Tools.Stats.reporting.summary import (
    StatsSummaryFrames,
    SummaryConfig,
    build_rm_anova_output,
    build_summary_from_frames,
    build_summary_frames_from_results,
)
from Tools.Stats.reporting.reporting_summary import (
    ReportingSummaryContext,
    build_default_report_path,
    build_reporting_summary,
)
from Tools.Stats.widgets.elided_label import ElidedPathLabel

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers


_UNKNOWN_GROUP_IDS = frozenset(
    {"", "none", "nan", "unknown", "unassigned", "not assigned"}
)


@dataclass(frozen=True)
class NativeGroupState:
    """Canonical and display-only group state for the scanned cohort."""

    participant_group_id_map: dict[str, str]
    subject_group_display_map: dict[str, str | None]
    group_display_labels: dict[str, str]
    group_participant_counts: dict[str, int]
    unassigned_participants: tuple[str, ...]


@dataclass(frozen=True)
class PreliminaryWorkbookCoverage:
    """Workbook-presence preview before QC/manual exclusions and DV audit."""

    participants: tuple[str, ...]
    selected_conditions: tuple[str, ...]
    complete_conditions: tuple[str, ...]
    incomplete_conditions: tuple[str, ...]
    missing_by_condition: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, object]:
        return {
            "is_preliminary": True,
            "participants": list(self.participants),
            "n_participants": len(self.participants),
            "selected_conditions": list(self.selected_conditions),
            "complete_conditions": list(self.complete_conditions),
            "incomplete_conditions": list(self.incomplete_conditions),
            "missing_by_condition": {
                condition: list(participants)
                for condition, participants in self.missing_by_condition.items()
            },
        }


def _casefold_text_map(values: Mapping[object, object] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in (values or {}).items():
        key_text = str(key).strip()
        if not key_text or value is None:
            continue
        value_text = str(value).strip()
        if value_text:
            normalized[key_text.casefold()] = value_text
    return normalized


def build_native_group_state(
    subjects: Sequence[object],
    participant_group_ids: Mapping[object, object] | None,
    participant_display_labels: Mapping[object, object] | None,
) -> NativeGroupState:
    """Build group state without inferring canonical IDs from display labels."""

    canonical_lookup = _casefold_text_map(participant_group_ids)
    display_lookup = _casefold_text_map(participant_display_labels)
    canonical_by_subject: dict[str, str] = {}
    display_by_subject: dict[str, str | None] = {}
    group_labels: dict[str, str] = {}
    group_counts: dict[str, int] = {}
    unassigned: list[str] = []
    seen_subjects: set[str] = set()

    for raw_subject in subjects:
        subject = str(raw_subject).strip()
        subject_key = subject.casefold()
        if not subject or subject_key in seen_subjects:
            continue
        seen_subjects.add(subject_key)
        display_label = display_lookup.get(subject_key)
        display_by_subject[subject] = display_label
        group_id = canonical_lookup.get(subject_key, "")
        if group_id.casefold() in _UNKNOWN_GROUP_IDS:
            unassigned.append(subject)
            continue
        canonical_by_subject[subject] = group_id
        group_counts[group_id] = group_counts.get(group_id, 0) + 1
        group_labels.setdefault(group_id, display_label or group_id)

    ordered_group_ids = sorted(group_counts, key=str.casefold)
    return NativeGroupState(
        participant_group_id_map=canonical_by_subject,
        subject_group_display_map=display_by_subject,
        group_display_labels={
            group_id: group_labels[group_id] for group_id in ordered_group_ids
        },
        group_participant_counts={
            group_id: group_counts[group_id] for group_id in ordered_group_ids
        },
        unassigned_participants=tuple(unassigned),
    )


def canonical_group_pairs(
    group_ids: Sequence[object],
) -> tuple[tuple[str, str], ...]:
    """Return stable unique two-group combinations in canonical-ID order."""

    unique_by_key: dict[str, str] = {}
    for raw_group_id in group_ids:
        group_id = str(raw_group_id).strip()
        group_key = group_id.casefold()
        if group_key in _UNKNOWN_GROUP_IDS:
            continue
        unique_by_key.setdefault(group_key, group_id)
    unique = sorted(unique_by_key.values(), key=str.casefold)
    return tuple(
        (left, right)
        for left_index, left in enumerate(unique)
        for right in unique[left_index + 1 :]
    )


def build_preliminary_workbook_coverage(
    subjects: Sequence[object],
    selected_conditions: Sequence[object],
    subject_data: Mapping[object, object] | None,
) -> PreliminaryWorkbookCoverage:
    """Describe condition coverage while retaining every scanned participant."""

    participant_ids = tuple(
        dict.fromkeys(
            str(subject).strip()
            for subject in subjects
            if str(subject).strip()
        )
    )
    conditions = tuple(
        dict.fromkeys(
            str(condition).strip()
            for condition in selected_conditions
            if str(condition).strip()
        )
    )
    subject_lookup = {
        str(subject).strip().casefold(): values
        for subject, values in (subject_data or {}).items()
        if str(subject).strip()
    }
    missing_by_condition: dict[str, tuple[str, ...]] = {}
    complete: list[str] = []
    incomplete: list[str] = []

    for condition in conditions:
        condition_key = condition.casefold()
        missing: list[str] = []
        for participant in participant_ids:
            raw_conditions = subject_lookup.get(participant.casefold())
            if not isinstance(raw_conditions, Mapping):
                missing.append(participant)
                continue
            condition_lookup = {
                str(name).strip().casefold(): path
                for name, path in raw_conditions.items()
            }
            supplied_path = condition_lookup.get(condition_key)
            supplied = supplied_path is not None and bool(
                str(supplied_path).strip()
            )
            if not supplied:
                missing.append(participant)
        missing_by_condition[condition] = tuple(missing)
        if participant_ids and not missing:
            complete.append(condition)
        else:
            incomplete.append(condition)

    return PreliminaryWorkbookCoverage(
        participants=participant_ids,
        selected_conditions=conditions,
        complete_conditions=tuple(complete),
        incomplete_conditions=tuple(incomplete),
        missing_by_condition=missing_by_condition,
    )


def format_preliminary_workbook_coverage(
    coverage: PreliminaryWorkbookCoverage,
    *,
    analysis_scope: str = "complete_core",
) -> str:
    """Return a concise, explicitly preliminary scope-aware coverage preview."""

    scope = str(analysis_scope or "").strip().casefold().replace("-", "_")
    if not coverage.participants:
        return (
            "Preliminary workbook coverage: scan a project before evaluating "
            "condition completeness."
        )
    if not coverage.selected_conditions:
        return (
            "Preliminary workbook coverage: no conditions are selected. "
            f"All {len(coverage.participants)} scanned participants remain in "
            "the preview."
        )
    if coverage.incomplete_conditions:
        details = "; ".join(
            (
                f"{condition} missing for "
                + ", ".join(coverage.missing_by_condition[condition])
            )
            for condition in coverage.incomplete_conditions
        )
        return (
            "Preliminary workbook coverage (before QC/manual exclusions): "
            f"{len(coverage.complete_conditions)}/"
            f"{len(coverage.selected_conditions)} selected conditions are "
            f"supplied by all {len(coverage.participants)} scanned participants. "
            f"Incomplete: {details}. "
            + (
                "Available observations from incomplete conditions are retained "
                "for the available-case LMM when the fixed-effect design remains "
                "estimable. Exact usable rows are determined after QC and manual "
                "exclusions; this preview does not remove participants."
                if scope == "available_case"
                else (
                    "Incomplete conditions are excluded from the primary "
                    "complete-core analysis; this preview does not remove "
                    "participants."
                )
            )
        )
    return (
        "Preliminary workbook coverage (before QC/manual exclusions): all "
        f"{len(coverage.selected_conditions)} selected conditions are supplied "
        f"by all {len(coverage.participants)} scanned participants. This preview "
        "does not remove participants."
    )

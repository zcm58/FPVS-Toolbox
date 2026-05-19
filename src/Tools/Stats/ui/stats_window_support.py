"""Shared imports for the internal StatsWindow mixin modules.

This module exists to keep the split Stats window modules
mechanical and behavior-preserving. New code should prefer direct imports.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

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
    BusySpinner,
    SectionCard,
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
    export_significance_results_to_excel as export_harmonic_results_to_excel,
)
from Tools.Stats.data.shared_rois import apply_rois_to_modules, load_rois_from_settings
from Tools.Stats.controller.stats_controller import StatsController
from Tools.Stats.common.stats_core import (
    ANOVA_XLS,
    BASELINE_VS_ZERO_XLS,
    HARMONIC_XLS,
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
    group_harmonic_results,
    ScanError,
    auto_detect_project_dir,
    load_manifest_data,
    load_project_scan,
    safe_export_call,
    resolve_project_subfolder,
)
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
    EMPTY_LIST_ERROR,
    EMPTY_LIST_FALLBACK_FIXED_K,
    EMPTY_LIST_SET_ZERO,
    FIXED_K_POLICY_NAME,
    LEGACY_POLICY_NAME,
    ROSSION_POLICY_NAME,
)
from Tools.Stats.analysis.dv_variants import export_dv_variants_workbook
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
    safe_project_path_join,
)
from Tools.Stats.widgets.elided_label import ElidedPathLabel
from Tools.Stats.common.stats_window_types import HarmonicConfig

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers

# src/Tools/Stats/PySide6/stats_ui_pyside6.py
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable, Optional, Tuple, Dict, List, Callable

import numpy as np
import pandas as pd
from PySide6.QtCore import Qt, QTimer, QThreadPool, Slot, QUrl, QTime
from PySide6.QtGui import QAction, QDesktopServices, QFontMetrics
from PySide6.QtWidgets import (
    QFileDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QComboBox,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Qt imports proof: QAction from PySide6.QtGui
from Main_App import SettingsManager
from Main_App.PySide6_App.Backend.project import (
    EXCEL_SUBFOLDER_NAME,
    STATS_SUBFOLDER_NAME,
)
from Main_App.PySide6_App.utils.op_guard import OpGuard
from Main_App.PySide6_App.widgets.busy_spinner import BusySpinner
from Tools.Stats.Legacy.interpretation_helpers import generate_lme_summary
from Tools.Stats.Legacy.group_contrasts import compute_group_contrasts
from Tools.Stats.Legacy.mixed_effects_model import run_mixed_effects_model
from Tools.Stats.Legacy.mixed_group_anova import run_mixed_group_anova
from Tools.Stats.Legacy.posthoc_tests import run_interaction_posthocs
from Tools.Stats.Legacy.stats_analysis import (
    ALL_ROIS_OPTION,
    prepare_all_subject_summed_bca_data,
    run_rm_anova as analysis_run_rm_anova,
    run_harmonic_check as run_harmonic_check_new,
    set_rois,
)
from Tools.Stats.Legacy.stats_export import (
    export_mixed_model_results_to_excel,
    export_posthoc_results_to_excel,
    export_rm_anova_results_to_excel,
    export_significance_results_to_excel as export_harmonic_results_to_excel,
)
from Tools.Stats.Legacy.stats_helpers import load_rois_from_settings, apply_rois_to_modules
from Tools.Stats.PySide6.stats_file_scanner_pyside6 import ScanError, scan_folder_simple
from Tools.Stats.PySide6.stats_worker import StatsWorker

logger = logging.getLogger(__name__)
_unused_qaction = QAction  # keep import alive for Qt resource checkers

# --------------------------- constants ---------------------------
ANOVA_XLS = "RM-ANOVA Results.xlsx"
LMM_XLS = "Mixed Model Results.xlsx"
POSTHOC_XLS = "Posthoc Results.xlsx"
HARMONIC_XLS = "Harmonic Results.xlsx"
ANOVA_BETWEEN_XLS = "Mixed ANOVA Between Groups.xlsx"
LMM_BETWEEN_XLS = "Mixed Model Between Groups.xlsx"
GROUP_CONTRAST_XLS = "Group Contrasts.xlsx"


@dataclass
class PipelineStep:
    name: str
    worker_fn: Callable
    kwargs: dict
    handler: Callable[[dict], None]


@dataclass
class SectionRunState:
    name: str
    status_label: QLabel | None = None
    button: QPushButton | None = None
    running: bool = False
    start_ts: float = 0.0
    steps: list[PipelineStep] = field(default_factory=list)
    failed: bool = False

# --------------------------- helpers ---------------------------

def _auto_detect_project_dir() -> str:
    """Walk upward to find a folder containing project.json."""
    path = Path.cwd()
    while not (path / "project.json").is_file():
        if path.parent == path:
            return str(Path.cwd())
        path = path.parent
    return str(path)


def _first_present(d: dict, keys: Iterable[str], default=None):
    for k in keys:
        if k in d:
            return d[k]
    return default


def _load_manifest_data(project_root: Path, cfg: dict | None = None) -> tuple[str | None, dict[str, str]]:
    if cfg is None:
        manifest = project_root / "project.json"
        if not manifest.is_file():
            return None, {}
        try:
            cfg = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            return None, {}
    results_folder = cfg.get("results_folder")
    if not isinstance(results_folder, str):
        results_folder = None
    subfolders = cfg.get("subfolders", {})
    if not isinstance(subfolders, dict):
        subfolders = {}
    normalized: dict[str, str] = {}
    for key, value in subfolders.items():
        if isinstance(value, str):
            normalized[key] = value
    return results_folder, normalized


def _resolve_results_root(project_root: Path, results_folder: str | None) -> Path:
    if results_folder:
        base = Path(results_folder)
        if not base.is_absolute():
            base = project_root / base
    else:
        base = project_root
    return base.resolve()


def _resolve_project_subfolder(
    project_root: Path,
    results_folder: str | None,
    subfolders: dict[str, str],
    key: str,
    default_name: str,
) -> Path:
    name = subfolders.get(key, default_name)
    candidate = Path(name)
    if candidate.is_absolute():
        return candidate.resolve()
    return (_resolve_results_root(project_root, results_folder) / candidate).resolve()


# --------------------------- manifest helpers ---------------------------

def _load_project_manifest_for_excel_root(excel_root: Path) -> dict | None:
    """Walk upward from an Excel folder to locate and load project.json."""
    try:
        current = excel_root.resolve()
    except Exception:
        current = excel_root
    for candidate in (current, *current.parents):
        manifest = candidate / "project.json"
        if manifest.is_file():
            try:
                cfg = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to load manifest %s: %s", manifest, exc)
                return None
            try:
                results_folder, subfolders = _load_manifest_data(candidate, cfg)
                expected_excel = _resolve_project_subfolder(
                    candidate,
                    results_folder,
                    subfolders,
                    "excel",
                    EXCEL_SUBFOLDER_NAME,
                )
                expected_resolved = expected_excel.resolve()
            except Exception:
                expected_resolved = None
            if expected_resolved is not None:
                allowed = {current, *current.parents}
                if expected_resolved not in allowed:
                    continue
            return cfg
    return None


def _normalize_participants_map(manifest: dict | None) -> dict[str, str]:
    """Return {SUBJECT_ID -> group_name} using upper-case participant IDs."""
    if not isinstance(manifest, dict):
        return {}
    participants = manifest.get("participants", {})
    if not isinstance(participants, dict):
        return {}
    normalized: dict[str, str] = {}
    for pid, info in participants.items():
        if not isinstance(pid, str) or not pid.strip():
            continue
        if not isinstance(info, dict):
            continue
        group = info.get("group")
        if not isinstance(group, str) or not group.strip():
            continue
        normalized[pid.strip().upper()] = group.strip()
    return normalized


def _map_subjects_to_groups(subjects: Iterable[str], participants_map: dict[str, str]) -> dict[str, str | None]:
    return {pid: participants_map.get(pid.upper()) for pid in subjects}


def _has_multi_groups(manifest: dict | None) -> bool:
    if not isinstance(manifest, dict):
        return False
    groups = manifest.get("groups")
    return isinstance(groups, dict) and bool(groups)


def _long_format_from_bca(
    all_subject_bca_data: Dict[str, Dict[str, Dict[str, float]]],
    subject_groups: dict[str, str | None] | None = None,
) -> pd.DataFrame:
    """Return a tidy dataframe for downstream models.

    ``group`` is optional here; single-group projects simply omit it so legacy
    workflows continue untouched. When present it is passed through to between
    group ANOVA/LMM builders.
    """
    rows = []
    groups = subject_groups or {}
    for pid, cond_data in all_subject_bca_data.items():
        for cond_name, roi_data in cond_data.items():
            for roi_name, value in roi_data.items():
                if not pd.isna(value):
                    rows.append(
                        {
                            "subject": pid,
                            "condition": cond_name,
                            "roi": roi_name,
                            "value": value,
                            "group": groups.get(pid),
                        }
                    )
    return pd.DataFrame(rows)


# --------------------------- worker functions ---------------------------

def _rm_anova_calc(progress_cb, message_cb, *, subjects, conditions, subject_data, base_freq, rois):
    set_rois(rois)
    message_cb("Preparing data for Summed BCA RM-ANOVA…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")
    message_cb("Running RM-ANOVA…")
    _, anova_df_results = analysis_run_rm_anova(all_subject_bca_data, message_cb)
    return {"anova_df_results": anova_df_results}


def _between_group_anova_calc(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    rois,
    subject_groups: dict[str, str | None] | None = None,
):
    set_rois(rois)
    message_cb("Preparing data for Between-Group RM-ANOVA…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    before = len(df_long)
    df_long = df_long.dropna(subset=["group"])
    dropped = before - len(df_long)
    if dropped:
        message_cb(f"Dropped {dropped} rows without group assignments for mixed ANOVA.")
    if df_long.empty:
        raise RuntimeError("No rows with valid group assignments for mixed ANOVA.")

    df_long["group"] = df_long["group"].astype(str)
    if df_long["group"].nunique() < 2:
        raise RuntimeError("Mixed ANOVA requires at least two groups with valid data.")

    message_cb("Running Between-Group RM-ANOVA…")
    results = run_mixed_group_anova(
        df_long,
        dv_col="value",
        subject_col="subject",
        within_cols=["condition", "roi"],
        between_col="group",
    )
    return {"anova_df_results": results}


def _lmm_calc(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    alpha,
    rois,
    subject_groups: dict[str, str | None] | None = None,
    include_group: bool = False,
):
    set_rois(rois)
    prep_label = "Mixed Effects Model" if not include_group else "Between-Group Mixed Model"
    message_cb(f"Preparing data for {prep_label}…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    if df_long.empty:
        raise RuntimeError("No valid rows for mixed model after filtering NaNs.")

    dropped = 0
    group_levels: list[str] = []
    if include_group:
        before = len(df_long)
        df_long = df_long.dropna(subset=["group"])
        dropped = before - len(df_long)
        df_long["group"] = df_long["group"].astype(str)
        group_levels = sorted(df_long["group"].unique())
        if dropped:
            message_cb(
                f"Dropped {dropped} rows without group assignments for between-group model."
            )
        if len(group_levels) < 2:
            raise RuntimeError(
                "Between-group mixed model requires at least two groups with valid data."
            )

    message_cb("Running Mixed Effects Model…")

    fixed_effects = ["condition * roi"]
    if include_group:
        fixed_effects = ["group * condition * roi"]

    mixed_results_df = run_mixed_effects_model(
        data=df_long,
        dv_col="value",
        group_col="subject",
        fixed_effects=fixed_effects,
    )

    output_text = "============================================================\n"
    if include_group:
        output_text += "       Between-Group Mixed-Effects Model Results\n"
    else:
        output_text += "       Linear Mixed-Effects Model Results\n"
    output_text += "       Analysis conducted on: Summed BCA Data\n"
    output_text += "============================================================\n\n"
    if include_group:
        output_text += (
            "Group was modeled as a between-subject factor interacting with condition\n"
            "and ROI. Only subjects with known group assignments were included.\n\n"
        )
    else:
        output_text += (
            "This model accounts for repeated observations from each subject by including\n"
            "a random intercept. Fixed effects assess how conditions and ROIs influence\n"
            "Summed BCA values, including their interaction.\n\n"
        )
    if mixed_results_df is not None and not mixed_results_df.empty:
        output_text += "--------------------------------------------\n"
        output_text += "                 FIXED EFFECTS TABLE\n"
        output_text += "--------------------------------------------\n"
        output_text += mixed_results_df.to_string(index=False) + "\n"
        output_text += generate_lme_summary(mixed_results_df, alpha=alpha)
    else:
        output_text += "Mixed effects model returned no rows.\n"

    return {"mixed_results_df": mixed_results_df, "output_text": output_text}


def _posthoc_calc(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    alpha,
    rois,
    subject_groups: dict[str, str | None] | None = None,
):
    set_rois(rois)
    message_cb("Preparing data for Interaction Post-hoc tests…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    if df_long.empty:
        raise RuntimeError("No valid rows for post-hoc tests after filtering NaNs.")

    message_cb("Running post-hoc tests…")
    output_text, results_df = run_interaction_posthocs(
        data=df_long,
        dv_col="value",
        roi_col="roi",
        condition_col="condition",
        subject_col="subject",
        alpha=alpha,
    )
    return {"results_df": results_df, "output_text": output_text}


def _group_contrasts_calc(
    progress_cb,
    message_cb,
    *,
    subjects,
    conditions,
    subject_data,
    base_freq,
    alpha,
    rois,
    subject_groups: dict[str, str | None] | None = None,
):
    set_rois(rois)
    _ = alpha  # placeholder for future alpha-dependent formatting
    message_cb("Preparing data for Between-Group Contrasts…")
    all_subject_bca_data = prepare_all_subject_summed_bca_data(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=base_freq,
        log_func=message_cb,
    )
    if not all_subject_bca_data:
        raise RuntimeError("Data preparation failed (empty).")

    df_long = _long_format_from_bca(all_subject_bca_data, subject_groups)
    df_long = df_long.dropna(subset=["group"])
    if df_long.empty:
        raise RuntimeError("No rows with group assignments to compute contrasts.")
    df_long["group"] = df_long["group"].astype(str)
    if df_long["group"].nunique() < 2:
        raise RuntimeError("Group contrasts require at least two groups with data.")

    message_cb("Running Between-Group Contrasts…")
    results_df = compute_group_contrasts(
        df_long,
        subject_col="subject",
        group_col="group",
        condition_col="condition",
        roi_col="roi",
        dv_col="value",
    )
    # Build an informative textual summary for the GUI
    import math

    n_rows = int(len(results_df))
    conditions = sorted(results_df["condition"].dropna().unique().tolist())
    rois = sorted(results_df["roi"].dropna().unique().tolist())
    n_conditions = len(conditions)
    n_rois = len(rois)

    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("       Between-Group Pairwise Contrasts")
    lines.append("=" * 60)
    lines.append("")
    lines.append(
        f"Computed {n_rows} pairwise group contrasts across "
        f"{n_conditions} conditions and {n_rois} ROIs."
    )
    lines.append(
        "Each row reports Welch's t-test (unequal variances) and Cohen's d for the"
    )
    lines.append(
        "difference between the specified groups within a condition \u00d7 ROI."
    )

    # Prepare a small preview table for the text area
    preview = results_df.copy()
    sort_cols = [c for c in ["condition", "roi", "group_1", "group_2"] if c in preview.columns]
    if sort_cols:
        preview = preview.sort_values(sort_cols)

    preview_cols = [
        "condition",
        "roi",
        "group_1",
        "group_2",
        "mean_1",
        "mean_2",
        "difference",
        "t_stat",
        "p_value",
        "effect_size",
    ]
    preview_cols = [c for c in preview_cols if c in preview.columns]
    preview = preview[preview_cols]

    max_rows = 10
    shown_rows = min(max_rows, n_rows)

    lines.append("")
    lines.append("--------------------------------------------")
    lines.append("         PREVIEW OF CONTRASTS TABLE")
    lines.append(f"         (first {shown_rows} of {n_rows} rows)")
    lines.append("--------------------------------------------")

    for _, row in preview.head(max_rows).iterrows():
        # Defensive formatting in case of missing columns / NaNs
        cond = row.get("condition", "")
        roi = row.get("roi", "")
        g1 = row.get("group_1", "")
        g2 = row.get("group_2", "")
        t_stat = row.get("t_stat", math.nan)
        p_val = row.get("p_value", math.nan)
        d_val = row.get("effect_size", math.nan)
        try:
            t_str = f"{float(t_stat):.3f}"
        except Exception:
            t_str = str(t_stat)
        try:
            p_str = f"{float(p_val):.4f}"
        except Exception:
            p_str = str(p_val)
        try:
            d_str = f"{float(d_val):.3f}"
        except Exception:
            d_str = str(d_val)

        lines.append(
            f"{cond} | {roi} | {g1} vs {g2} | "
            f"t={t_str}, p={p_str}, d={d_str}"
        )

    # Highlight any significant contrasts
    lines.append("")
    lines.append("--------------------------------------------")
    lines.append("            KEY FINDINGS")
    lines.append("--------------------------------------------")

    use_fdr = "p_fdr_bh" in results_df.columns and "sig_fdr_0_05" in results_df.columns

    if use_fdr:
        sig_df = results_df[results_df["sig_fdr_0_05"]].copy()
        if sig_df.empty:
            lines.append(
                "No pairwise group contrasts survived FDR correction (q = 0.05, "
                "Benjamini–Hochberg)."
            )
        else:
            lines.append(
                "Significant pairwise group contrasts after FDR correction "
                "(q = 0.05, Benjamini–Hochberg):"
            )
            sig_df = sig_df.sort_values("p_fdr_bh")
            for _, row in sig_df.head(10).iterrows():
                cond = row.get("condition", "")
                roi = row.get("roi", "")
                g1 = row.get("group_1", "")
                g2 = row.get("group_2", "")
                p_fdr = row.get("p_fdr_bh", math.nan)
                d_val = row.get("effect_size", math.nan)
                try:
                    p_fdr_str = f"{float(p_fdr):.4f}"
                except Exception:
                    p_fdr_str = str(p_fdr)
                try:
                    d_str = f"{float(d_val):.3f}"
                except Exception:
                    d_str = str(d_val)

                lines.append(
                    f"- {cond} @ {roi}: {g1} vs {g2} "
                    f"(FDR p={p_fdr_str}, d={d_str})"
                )
            if len(sig_df) > 10:
                lines.append(f"... and {len(sig_df) - 10} more.")
    else:
        sig_mask = ("p_value" in results_df.columns) & results_df["p_value"].notna()
        sig_df = results_df[sig_mask & (results_df["p_value"] < 0.05)]

        if sig_df.empty:
            lines.append("No pairwise group contrasts reached p < 0.05.")
        else:
            lines.append("Significant pairwise group contrasts (p < 0.05):")
            sig_df = sig_df.sort_values("p_value")
            for _, row in sig_df.head(10).iterrows():
                cond = row.get("condition", "")
                roi = row.get("roi", "")
                g1 = row.get("group_1", "")
                g2 = row.get("group_2", "")
                t_stat = row.get("t_stat", math.nan)
                p_val = row.get("p_value", math.nan)
                d_val = row.get("effect_size", math.nan)
                try:
                    t_str = f"{float(t_stat):.3f}"
                except Exception:
                    t_str = str(t_stat)
                try:
                    p_str = f"{float(p_val):.4f}"
                except Exception:
                    p_str = str(p_val)
                try:
                    d_str = f"{float(d_val):.3f}"
                except Exception:
                    d_str = str(d_val)

                lines.append(
                    f"- {cond} @ {roi}: {g1} vs {g2} "
                    f"(t={t_str}, p={p_str}, d={d_str})"
                )
            if len(sig_df) > 10:
                lines.append(f"... and {len(sig_df) - 10} more.")

    lines.append("--------------------------------------------")
    lines.append(
        "Refer to the exported 'Group Contrasts' table for full details on all"
    )
    lines.append("condition \u00d7 ROI combinations.")
    lines.append("--------------------------------------------")

    output_text = "\n".join(lines)

    return {
        "results_df": results_df,
        "output_text": output_text,
    }


def _harmonic_calc(
    progress_cb,
    message_cb,
    *,
    subject_data,
    subjects,
    conditions,
    selected_metric,
    mean_value_threshold,
    base_freq,
    alpha,
    rois,
):
    set_rois(rois)
    tail = "greater" if selected_metric in ("Z Score", "SNR") else "two-sided"
    message_cb("Running harmonic check…")
    output_text, findings = run_harmonic_check_new(
        subject_data=subject_data,
        subjects=subjects,
        conditions=conditions,
        selected_metric=selected_metric,
        mean_value_threshold=mean_value_threshold,
        base_freq=base_freq,
        log_func=message_cb,
        max_freq=None,
        correction_method="holm",
        tail=tail,
        min_subjects=3,
        do_wilcoxon_sensitivity=True,
    )
    return {"output_text": output_text, "findings": findings}


# --------------------------- main window ---------------------------

class StatsWindow(QMainWindow):
    """PySide6 window wrapping the legacy FPVS Statistical Analysis Tool."""

    def __init__(self, parent: Optional[QMainWindow] = None, project_dir: Optional[str] = None):
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, "currentProject", None)
            self.project_dir = (
                str(proj.project_root) if proj and hasattr(proj, "project_root") else _auto_detect_project_dir()
            )

        self._project_path = Path(self.project_dir).resolve()
        self._results_folder_hint: str | None = None
        self._subfolder_hints: dict[str, str] = {}

        config_path = self._project_path / "project.json"
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            self.project_title = cfg.get("name", cfg.get("title", os.path.basename(self.project_dir)))
            self._results_folder_hint, self._subfolder_hints = _load_manifest_data(self._project_path, cfg)
        except Exception:
            self.project_title = os.path.basename(self.project_dir)

        super().__init__(parent)
        self.setWindowFlags(self.windowFlags() | Qt.Window)
        self.setWindowTitle("FPVS Statistical Analysis Tool")

        self._guard = OpGuard()
        if not hasattr(self._guard, "done"):
            self._guard.done = self._guard.end  # type: ignore[attr-defined]
        self.pool = QThreadPool.globalInstance()
        self._focus_calls = 0

        self.setMinimumSize(900, 600)
        self.resize(1000, 750)

        # re-entrancy guard for scan
        self._scan_guard = OpGuard()
        if not hasattr(self._scan_guard, "done"):
            self._scan_guard.done = self._scan_guard.end  # type: ignore[attr-defined]

        # --- state ---
        self.subject_data: Dict = {}
        self.subject_groups: Dict[str, str | None] = {}
        self.subjects: List[str] = []
        self.conditions: List[str] = []
        self._multi_group_manifest: bool = False
        self.rm_anova_results_data: Optional[pd.DataFrame] = None
        self.mixed_model_results_data: Optional[pd.DataFrame] = None
        self.between_anova_results_data: Optional[pd.DataFrame] = None
        self.between_mixed_model_results_data: Optional[pd.DataFrame] = None
        self.group_contrasts_results_data: Optional[pd.DataFrame] = None
        self.posthoc_results_data: Optional[pd.DataFrame] = None
        self.harmonic_check_results_data: List[dict] = []
        self.rois: Dict[str, List[str]] = {}
        self._harmonic_metric: str = ""
        self._current_base_freq: float = 6.0
        self._current_alpha: float = 0.05
        self.single_section_state = SectionRunState("Single Group Analysis")
        self.between_section_state = SectionRunState("Between-Group Analysis")

        # --- legacy UI proxies ---
        self.stats_data_folder_var = SimpleNamespace(get=lambda: self.le_folder.text() if hasattr(self, "le_folder") else "",
                                                     set=lambda v: self.le_folder.setText(v) if hasattr(self, "le_folder") else None)
        self.detected_info_var = SimpleNamespace(set=lambda t: self._set_status(t))
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)

        # UI
        self._init_ui()
        self.results_textbox = self.output_text

        self.single_section_state.status_label = self.single_status_lbl
        self.single_section_state.button = self.analyze_single_btn
        self.between_section_state.status_label = self.between_status_lbl
        self.between_section_state.button = self.analyze_between_btn

        self.refresh_rois()
        QTimer.singleShot(100, self._load_default_data_folder)

        self._progress_updates: List[int] = []

    # --------- ROI + status helpers ---------

    def refresh_rois(self) -> None:
        fresh = load_rois_from_settings() or {}
        try:
            set_rois({})
        except Exception:
            pass
        apply_rois_to_modules(fresh)
        set_rois(fresh)
        self.rois = fresh
        self._update_roi_label()

    def _update_roi_label(self) -> None:
        names = list(self.rois.keys())
        txt = "Using {} ROI{} from Settings: {}".format(
            len(names), "" if len(names) == 1 else "s", ", ".join(names)
        ) if names else "No ROIs defined in Settings."
        self._set_roi_status(txt)

    def _set_status(self, txt: str) -> None:
        if hasattr(self, "lbl_status"):
            self.lbl_status.setText(txt)

    def _set_roi_status(self, txt: str) -> None:
        if hasattr(self, "lbl_rois"):
            self.lbl_rois.setText(txt)

    def _set_detected_info(self, txt: str) -> None:
        """Route unknown worker messages to proper label."""
        lower_txt = txt.lower() if isinstance(txt, str) else str(txt).lower()
        if (" roi" in lower_txt) or lower_txt.startswith("using ") or lower_txt.startswith("rois"):
            self._set_roi_status(txt)
        else:
            self._set_status(txt)

    def append_log(self, section: str, message: str, level: str = "info") -> None:
        ts = QTime.currentTime().toString("HH:mm:ss")
        prefix = f"[{ts}] [{section}] "
        line = f"{prefix}{message}"
        if hasattr(self, "output_text") and self.output_text is not None:
            self.output_text.appendPlainText(line)
            self.output_text.ensureCursorVisible()
        level_lower = (level or "info").lower()
        log_func = getattr(logger, level_lower, logger.info)
        log_func(f"[{section}] {message}")

    def _section_label(self, state: SectionRunState | None) -> str:
        if state is self.single_section_state:
            return "Single"
        if state is self.between_section_state:
            return "Between"
        return "General"

    def _warn_unknown_excel_files(self, subject_data: Dict[str, Dict[str, str]], participants_map: dict[str, str]) -> None:
        if not subject_data:
            return
        unknown_files: set[str] = set()
        for pid, cond_map in subject_data.items():
            if not isinstance(cond_map, dict):
                continue
            if pid.upper() in participants_map:
                continue
            for filepath in cond_map.values():
                try:
                    unknown_files.add(os.path.basename(filepath))
                except Exception:
                    continue
        if not unknown_files:
            return
        files_list = "\n".join(sorted(unknown_files))
        QMessageBox.warning(
            self,
            "Unrecognized Excel Files",
            (
                "Warning: The following Excel files are not recognized in this project's subject list:\n"
                f"{files_list}\n"
                "Please remove these files from the folder or update the project metadata."
            ),
        )

    def _known_group_labels(self) -> list[str]:
        return sorted({g for g in (self.subject_groups or {}).values() if g})

    def _ensure_between_ready(self) -> bool:
        groups = self._known_group_labels()
        if len(groups) < 2:
            if self._multi_group_manifest and not groups:
                msg = (
                    "No valid group assignments are available for between-group analysis. "
                    "Assign participants to project groups and rescan."
                )
            else:
                msg = (
                    "Between-group analysis requires at least two groups with assigned subjects."
                )
            QMessageBox.information(
                self,
                "Need Multiple Groups",
                msg,
            )
            return False
        return True

    # --------- window focus / run state ---------

    def _focus_self(self) -> None:
        self._focus_calls += 1
        self.raise_()
        self.activateWindow()

    def _set_running(self, running: bool) -> None:
        buttons = [
            getattr(self, "analyze_single_btn", None),
            getattr(self, "single_advanced_btn", None),
            getattr(self, "run_harm_btn", None),
            getattr(self, "export_harm_btn", None),
            getattr(self, "analyze_between_btn", None),
            getattr(self, "between_advanced_btn", None),
            getattr(self, "btn_open_results", None),
        ]
        for b in buttons:
            if b:
                b.setEnabled(not running)
        if running:
            self.spinner.show()
            self.spinner.start()
        else:
            self.spinner.stop()
            self.spinner.hide()

    def _begin_run(self) -> bool:
        if not self._guard.start():
            return False
        self._set_running(True)
        self._focus_self()
        return True

    def _end_run(self) -> None:
        self._set_running(False)
        self._guard.done()
        self._focus_self()

    # --------- settings helpers ---------

    def _safe_settings_get(self, section: str, key: str, default) -> Tuple[bool, object]:
        try:
            settings = SettingsManager()
            val = settings.get(section, key, default)
            return True, val
        except Exception as e:
            self._log_ui_error(f"settings_get:{section}/{key}", e)
            return False, default

    def _get_analysis_settings(self) -> Optional[Tuple[float, float]]:
        ok1, bf = self._safe_settings_get("analysis", "base_freq", 6.0)
        ok2, a = self._safe_settings_get("analysis", "alpha", 0.05)
        try:
            base_freq = float(bf)
            alpha = float(a)
        except Exception as e:
            QMessageBox.critical(self, "Settings Error", f"Invalid analysis settings: {e}")
            return None
        if not (ok1 and ok2):
            QMessageBox.critical(self, "Settings Error", "Could not load analysis settings.")
            return None
        return base_freq, alpha

    # --------- centralized pre-run guards ---------

    def _precheck(self, *, require_anova: bool = False, start_guard: bool = True) -> bool:
        if self._check_for_open_excel_files(self.le_folder.text()):
            return False
        if not self.subject_data:
            QMessageBox.warning(self, "No Data", "Please select a valid data folder first.")
            return False
        if require_anova and self.rm_anova_results_data is None:
            QMessageBox.warning(
                self,
                "Run ANOVA First",
                "Please run a successful RM-ANOVA before running post-hoc tests for the interaction.",
            )
            return False
        self.refresh_rois()
        if not self.rois:
            QMessageBox.warning(self, "No ROIs", "Define at least one ROI in Settings before running stats.")
            return False
        got = self._get_analysis_settings()
        if not got:
            return False
        self._current_base_freq, self._current_alpha = got
        if start_guard and not self._begin_run():
            return False
        return True

    # --------- exports plumbing ---------

    def _group_harmonic(self, data) -> dict:
        """list[dict] -> {condition: {roi: [records]}}"""
        if isinstance(data, dict):
            return data
        grouped: dict[str, dict[str, list[dict]]] = {}
        for rec in data or []:
            if not isinstance(rec, dict):
                continue
            cond = rec.get("Condition") or rec.get("condition") or "Unknown"
            roi = rec.get("ROI") or rec.get("roi") or "Unknown"
            grouped.setdefault(cond, {}).setdefault(roi, []).append(rec)
        return grouped

    def _safe_export_call(self, func, data_obj, out_dir: str, base_name: str) -> None:
        os.makedirs(out_dir, exist_ok=True)
        fname = base_name if base_name.lower().endswith(".xlsx") else f"{base_name}.xlsx"
        save_path = os.path.join(out_dir, fname)
        try:
            func(
                data_obj,
                save_path=save_path,
                log_func=self._set_status,
            )
            return
        except TypeError:
            func(data_obj, out_dir, log_func=self._set_status)

    def export_results(self, kind: str, data, out_dir: str) -> None:
        mapping = {
            "anova": (export_rm_anova_results_to_excel, ANOVA_XLS),
            "lmm": (export_mixed_model_results_to_excel, LMM_XLS),
            "posthoc": (export_posthoc_results_to_excel, POSTHOC_XLS),
            "harmonic": (export_harmonic_results_to_excel, HARMONIC_XLS),
            "anova_between": (export_rm_anova_results_to_excel, ANOVA_BETWEEN_XLS),
            "lmm_between": (export_mixed_model_results_to_excel, LMM_BETWEEN_XLS),
            "group_contrasts": (export_posthoc_results_to_excel, GROUP_CONTRAST_XLS),
        }
        func, fname = mapping[kind]
        if kind == "harmonic":
            grouped = self._group_harmonic(data)

            def _adapter(_ignored, *, save_path, log_func):
                export_harmonic_results_to_excel(
                    grouped,
                    save_path,
                    log_func,
                    metric=(self._harmonic_metric or ""),
                )

            self._safe_export_call(_adapter, None, out_dir, fname)
            return

        self._safe_export_call(func, data, out_dir, fname)

    def _ensure_results_dir(self) -> str:
        target = _resolve_project_subfolder(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            "stats",
            STATS_SUBFOLDER_NAME,
        )
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    def _open_results_folder(self) -> None:
        out_dir = self._ensure_results_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(out_dir))

    def _update_export_buttons(self) -> None:
        def _maybe_enable(name: str, enabled: bool) -> None:
            btn = getattr(self, name, None)
            if btn:
                btn.setEnabled(enabled)

        _maybe_enable(
            "export_rm_anova_btn",
            isinstance(self.rm_anova_results_data, pd.DataFrame)
            and not self.rm_anova_results_data.empty,
        )
        _maybe_enable(
            "export_mixed_model_btn",
            isinstance(self.mixed_model_results_data, pd.DataFrame)
            and not self.mixed_model_results_data.empty,
        )
        _maybe_enable(
            "export_posthoc_btn",
            isinstance(self.posthoc_results_data, pd.DataFrame)
            and not self.posthoc_results_data.empty,
        )
        _maybe_enable("export_harm_btn", bool(self.harmonic_check_results_data))
        _maybe_enable(
            "export_between_anova_btn",
            isinstance(self.between_anova_results_data, pd.DataFrame)
            and not self.between_anova_results_data.empty,
        )
        _maybe_enable(
            "export_between_mixed_btn",
            isinstance(self.between_mixed_model_results_data, pd.DataFrame)
            and not self.between_mixed_model_results_data.empty,
        )
        _maybe_enable(
            "export_group_contrasts_btn",
            isinstance(self.group_contrasts_results_data, pd.DataFrame)
            and not self.group_contrasts_results_data.empty,
        )

    # --------- worker signal wiring ---------

    def _wire_and_start(self, worker: StatsWorker, finished_slot) -> None:
        worker.signals.progress.connect(self._on_worker_progress)
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.error.connect(self._on_worker_error)
        worker.signals.finished.connect(finished_slot)
        self.pool.start(worker)

    def _any_section_running(self) -> bool:
        return bool(self.single_section_state.running or self.between_section_state.running)

    def _start_section(self, state: SectionRunState, *, status_label: QLabel | None) -> None:
        state.running = True
        state.failed = False
        state.start_ts = time.perf_counter()
        if state.button:
            state.button.setEnabled(False)
        if status_label:
            status_label.setText("Running…")
        self._set_running(True)
        self._focus_self()

    def _finish_section(self, state: SectionRunState, success: bool) -> None:
        state.running = False
        state.steps = []
        label = state.status_label
        if label:
            if success:
                ts = datetime.now().strftime("%H:%M:%S")
                label.setText(f"Last run OK at {ts}")
            else:
                label.setText("Last run error (see log)")
        if state.button:
            state.button.setEnabled(True)
        if not self._any_section_running():
            self._set_running(False)

    def _run_next_pipeline_step(self, state: SectionRunState) -> None:
        if not state.steps:
            return
        step = state.steps.pop(0)
        section = self._section_label(state)
        self.append_log(section, f"  • Starting {step.name}…")
        worker = StatsWorker(step.worker_fn, **step.kwargs)
        worker.signals.finished.connect(
            lambda payload, s=state, st=step: self._pipeline_step_finished(s, st, payload)
        )
        worker.signals.error.connect(lambda msg, s=state, st=step: self._pipeline_step_error(s, st, msg))
        worker.signals.message.connect(self._on_worker_message)
        worker.signals.progress.connect(self._on_worker_progress)
        self.pool.start(worker)

    def _pipeline_step_finished(self, state: SectionRunState, step: PipelineStep, payload: dict) -> None:
        try:
            step.handler(payload)
        except Exception as exc:  # noqa: BLE001
            section = self._section_label(state)
            self.append_log(section, f"  • ERROR in {step.name}: {exc}", level="error")
            state.failed = True
            self._finish_section(state, False)
            return

        section = self._section_label(state)
        self.append_log(section, f"  • {step.name} completed")
        if state.steps:
            self._run_next_pipeline_step(state)
        else:
            self._complete_pipeline(state)

    def _pipeline_step_error(self, state: SectionRunState, step: PipelineStep, msg: str) -> None:
        section = self._section_label(state)
        self.append_log(section, f"  • ERROR in {step.name}: {msg}", level="error")
        state.failed = True
        self.append_log(section, "  • Remaining steps skipped due to previous error", level="warning")
        self._finish_section(state, False)

    def _complete_pipeline(self, state: SectionRunState) -> None:
        elapsed = time.perf_counter() - state.start_ts if state.start_ts else 0.0
        if state.failed:
            section = self._section_label(state)
            self.append_log(
                section,
                f"{state.name} finished with errors (elapsed {elapsed:.1f} s)",
                level="warning",
            )
            self._finish_section(state, False)
            return

        if state is self.single_section_state:
            exported = self._export_single_pipeline()
        elif state is self.between_section_state:
            exported = self._export_between_pipeline()
        else:
            exported = True

        if not exported:
            self._finish_section(state, False)
            return

        section = self._section_label(state)
        stats_folder = Path(self._ensure_results_dir())
        if state is self.single_section_state:
            self.append_log(section, "  • Results exported for Single Group Analysis")
            self._prompt_view_results(section, stats_folder)
        elif state is self.between_section_state:
            self.append_log(section, "  • Results exported for Between-Group Analysis")
            self._prompt_view_results(section, stats_folder)

        self.append_log(section, f"{state.name} finished in {elapsed:.1f} s")
        self._finish_section(state, True)

    def _prompt_view_results(self, section: str, stats_folder: Path) -> None:
        msg = QMessageBox(self)
        msg.setWindowTitle("Statistical Analysis Complete")
        msg.setText("Statistical analysis complete.\nView results?")
        msg.setIcon(QMessageBox.Information)
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        reply = msg.exec()

        if reply == QMessageBox.Yes:
            if stats_folder.is_dir():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(stats_folder)))
            else:
                self.append_log(section, f"Stats folder not found: {stats_folder}", "error")

    def _export_single_pipeline(self) -> bool:
        section = "Single"
        exports = [
            ("anova", self.rm_anova_results_data, "RM-ANOVA"),
            ("lmm", self.mixed_model_results_data, "Mixed Model"),
            ("posthoc", self.posthoc_results_data, "Interaction Post-hocs"),
        ]
        out_dir = self._ensure_results_dir()
        try:
            paths: list[str] = []
            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(section, f"  • Skipping export for {label} (no data)", level="warning")
                    return False
                self.export_results(kind, data_obj, out_dir)
                fname = {
                    "anova": ANOVA_XLS,
                    "lmm": LMM_XLS,
                    "posthoc": POSTHOC_XLS,
                }.get(kind, "results.xlsx")
                paths.append(os.path.join(out_dir, fname))
            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
            return True
        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    def _export_between_pipeline(self) -> bool:
        section = "Between"
        exports = [
            ("anova_between", self.between_anova_results_data, "Between-Group ANOVA"),
            ("lmm_between", self.between_mixed_model_results_data, "Between-Group Mixed Model"),
            ("group_contrasts", self.group_contrasts_results_data, "Group Contrasts"),
        ]
        out_dir = self._ensure_results_dir()
        try:
            paths: list[str] = []
            for kind, data_obj, label in exports:
                if data_obj is None:
                    self.append_log(section, f"  • Skipping export for {label} (no data)", level="warning")
                    return False
                self.export_results(kind, data_obj, out_dir)
                fname = {
                    "anova_between": ANOVA_BETWEEN_XLS,
                    "lmm_between": LMM_BETWEEN_XLS,
                    "group_contrasts": GROUP_CONTRAST_XLS,
                }.get(kind, "results.xlsx")
                paths.append(os.path.join(out_dir, fname))
            if paths:
                self.append_log(section, "  • Results exported to:")
                for p in paths:
                    self.append_log(section, f"      {p}")
            return True
        except Exception as exc:  # noqa: BLE001
            self.append_log(section, f"  • Export failed: {exc}", level="error")
            return False

    # --------- worker signal handlers ---------

    @Slot(int)
    def _on_worker_progress(self, val: int) -> None:
        self._progress_updates.append(val)

    @Slot(str)
    def _on_worker_message(self, msg: str) -> None:
        self._set_detected_info(msg)

    @Slot(str)
    def _on_worker_error(self, msg: str) -> None:
        self.output_text.appendPlainText(f"Error: {msg}")
        section = (
            "Single"
            if self.single_section_state.running
            else "Between"
            if self.between_section_state.running
            else "General"
        )
        self.append_log(section, f"Worker error: {msg}", level="error")
        self._end_run()

    def _format_rm_anova_summary(self, df: pd.DataFrame, alpha: float) -> str:
        out = []
        p_candidates = ["Pr > F", "p-value", "p_value", "p", "P", "pvalue"]
        eff_candidates = ["Effect", "Source", "Factor", "Term"]
        p_col = next((c for c in p_candidates if c in df.columns), None)
        eff_col = next((c for c in eff_candidates if c in df.columns), None)

        if p_col is None:
            out.append("No interpretable effects were found in the ANOVA table.")
            return "\n".join(out)

        for idx, row in df.iterrows():
            effect_source = row.get(eff_col, idx) if eff_col is not None else idx
            effect_name = str(effect_source).strip()
            effect_lower = effect_name.lower()
            effect_compact = effect_lower.replace(" ", "").replace("×", "x")
            p_raw = row.get(p_col, np.nan)
            try:
                p_val = float(p_raw)
            except Exception:
                p_val = np.nan

            if (
                "group" in effect_lower
                and "condition" in effect_lower
                and "roi" in effect_lower
            ):
                tag = "group by condition by ROI interaction"
            elif "group" in effect_lower and "condition" in effect_lower:
                tag = "group-by-condition interaction"
            elif "group" in effect_lower and "roi" in effect_lower:
                tag = "group-by-ROI interaction"
            elif effect_lower.startswith("group") or effect_lower == "group":
                tag = "difference between groups"
            elif effect_compact in {
                "condition*roi",
                "condition:roi",
                "conditionxroi",
                "roi*condition",
                "roi:condition",
                "roixcondition",
            }:
                tag = "condition-by-ROI interaction"
            elif "condition" == effect_lower or effect_lower.startswith("conditions"):
                tag = "difference between conditions"
            elif effect_lower == "roi" or "region" in effect_lower:
                tag = "difference between ROIs"
            else:
                continue

            if np.isfinite(p_val) and p_val < alpha:
                out.append(f"  - Significant {tag} (p = {p_val:.4g}).")
            elif np.isfinite(p_val):
                out.append(f"  - No significant {tag} (p = {p_val:.4g}).")
            else:
                out.append(f"  - {tag.capitalize()}: p-value unavailable.")
        if not out:
            out.append("No interpretable effects were found in the ANOVA table.")
        return "\n".join(out)

    def _apply_rm_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.rm_anova_results_data = payload.get("anova_df_results")
        alpha = getattr(self, "_current_alpha", 0.05)

        output_text = "============================================================\n"
        output_text += "       Repeated Measures ANOVA (RM-ANOVA) Results\n"
        output_text += "       Analysis conducted on: Summed BCA Data\n"
        output_text += "============================================================\n\n"
        output_text += (
            "This test examines the overall effects of your experimental conditions (e.g., different stimuli),\n"
            "the different brain regions (ROIs) you analyzed, and whether the\n"
            "effect of the conditions changes depending on the brain region (interaction effect).\n\n"
        )

        anova_df_results = self.rm_anova_results_data
        if isinstance(anova_df_results, pd.DataFrame) and not anova_df_results.empty:
            output_text += self._format_rm_anova_summary(anova_df_results, alpha) + "\n"
            output_text += "--------------------------------------------\n"
            output_text += "NOTE: For detailed reporting and post-hoc tests, refer to the tables above.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "RM-ANOVA returned no results.\n"

        if update_text:
            self.output_text.appendPlainText(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_anova_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.between_anova_results_data = payload.get("anova_df_results")
        alpha = getattr(self, "_current_alpha", 0.05)
        output_text = "============================================================\n"
        output_text += "       Between-Group Mixed ANOVA Results\n"
        output_text += "============================================================\n\n"
        output_text += (
            "Group was treated as a between-subject factor with Condition and ROI as\n"
            "within-subject factors. Only subjects with known group assignments were\n"
            "included in this analysis.\n\n"
        )
        anova_df_results = self.between_anova_results_data
        if isinstance(anova_df_results, pd.DataFrame) and not anova_df_results.empty:
            output_text += self._format_rm_anova_summary(anova_df_results, alpha) + "\n"
            output_text += "--------------------------------------------\n"
            output_text += "Refer to the exported table for all Group main and interaction effects.\n"
            output_text += "--------------------------------------------\n"
        else:
            output_text += "Between-group ANOVA returned no results.\n"

        if update_text:
            self.output_text.appendPlainText(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_mixed_model_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.mixed_model_results_data = payload.get("mixed_results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.appendPlainText(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_between_mixed_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.between_mixed_model_results_data = payload.get("mixed_results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.appendPlainText(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_posthoc_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.posthoc_results_data = payload.get("results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.appendPlainText(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_group_contrasts_results(self, payload: dict, *, update_text: bool = True) -> str:
        self.group_contrasts_results_data = payload.get("results_df")
        output_text = payload.get("output_text", "")
        if update_text:
            self.output_text.appendPlainText(output_text)
        self._update_export_buttons()
        return output_text

    def _apply_harmonic_results(self, payload: dict, *, update_text: bool = True) -> str:
        output_text = payload.get("output_text") or ""
        findings = payload.get("findings") or []
        if update_text:
            self.output_text.appendPlainText(
                output_text.strip() or "(Harmonic check returned empty text. See logs for details.)"
            )
        self.harmonic_check_results_data = findings
        self._update_export_buttons()
        return output_text

    @Slot(dict)
    def _on_rm_anova_finished(self, payload: dict) -> None:
        self._apply_rm_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_anova_finished(self, payload: dict) -> None:
        self._apply_between_anova_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_mixed_model_finished(self, payload: dict) -> None:
        self._apply_mixed_model_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_between_mixed_finished(self, payload: dict) -> None:
        self._apply_between_mixed_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_posthoc_finished(self, payload: dict) -> None:
        self._apply_posthoc_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_group_contrasts_finished(self, payload: dict) -> None:
        self._apply_group_contrasts_results(payload)
        self._end_run()

    @Slot(dict)
    def _on_harmonic_finished(self, payload: dict) -> None:
        self._apply_harmonic_results(payload)
        self._end_run()

    # --------------------------- UI building ---------------------------

    def _init_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # folder row
        folder_row = QHBoxLayout()
        folder_row.setSpacing(5)
        self.le_folder = QLineEdit()
        self.le_folder.setReadOnly(True)
        btn_browse = QPushButton("Browse…")
        btn_browse.clicked.connect(self.on_browse_folder)
        folder_row.addWidget(QLabel("Data Folder:"))
        folder_row.addWidget(self.le_folder, 1)
        folder_row.addWidget(btn_browse)
        main_layout.addLayout(folder_row)

        # open results (scan button removed)
        tools_row = QHBoxLayout()
        self.btn_open_results = QPushButton("Open Results Folder")
        self.btn_open_results.clicked.connect(self._open_results_folder)
        # widen a bit to pad text
        fm = QFontMetrics(self.btn_open_results.font())
        self.btn_open_results.setMinimumWidth(fm.horizontalAdvance(self.btn_open_results.text()) + 24)
        tools_row.addWidget(self.btn_open_results)
        self.info_button = QPushButton("Analysis Info")
        self.info_button.clicked.connect(self.on_show_analysis_info)
        tools_row.addWidget(self.info_button)
        tools_row.addStretch(1)
        main_layout.addLayout(tools_row)

        # status + ROI labels
        self.lbl_status = QLabel("Select a folder containing FPVS results.")
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_layout.addWidget(self.lbl_status)

        self.lbl_rois = QLabel("")
        self.lbl_rois.setWordWrap(True)
        self.lbl_rois.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        main_layout.addWidget(self.lbl_rois)

        # spinner
        prog_row = QHBoxLayout()
        self.spinner = BusySpinner()
        self.spinner.setFixedSize(18, 18)
        self.spinner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.spinner.hide()
        prog_row.addWidget(self.spinner, alignment=Qt.AlignLeft)
        prog_row.addStretch(1)
        main_layout.addLayout(prog_row)

        sections_layout = QHBoxLayout()
        sections_layout.setSpacing(10)

        # single group section
        single_group_box = QGroupBox("Single Group Analysis")
        single_group_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        single_layout = QVBoxLayout(single_group_box)

        settings_box = QGroupBox("Detection / Harmonic Settings")
        settings_layout = QFormLayout(settings_box)
        settings_layout.setLabelAlignment(Qt.AlignLeft)

        metric_row = QHBoxLayout()
        self.cb_metric = QComboBox()
        self.cb_metric.addItems(["Z Score", "SNR", "Amplitude"])
        metric_row.addWidget(self.cb_metric)
        metric_row.addStretch(1)
        settings_layout.addRow(QLabel("Metric:"), metric_row)

        threshold_row = QHBoxLayout()
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.0, 10.0)
        self.threshold_spin.setSingleStep(0.01)
        self.threshold_spin.setValue(1.64)
        threshold_row.addWidget(self.threshold_spin)
        threshold_row.addStretch(1)
        settings_layout.addRow(QLabel("Mean Threshold:"), threshold_row)

        harm_row = QHBoxLayout()
        self.run_harm_btn = QPushButton("Run Harmonic Check")
        self.run_harm_btn.clicked.connect(self.on_run_harmonic_check)
        self.run_harm_btn.setShortcut("Ctrl+H")
        harm_row.addWidget(self.run_harm_btn)

        self.export_harm_btn = QPushButton("Export Harmonic Results")
        self.export_harm_btn.clicked.connect(self.on_export_harmonic)
        self.export_harm_btn.setShortcut("Ctrl+Shift+H")
        harm_row.addWidget(self.export_harm_btn)
        harm_row.addStretch(1)
        settings_layout.addRow(QLabel("Harmonic Tools:"), harm_row)

        single_layout.addWidget(settings_box)

        single_action_row = QHBoxLayout()
        single_action_row.addStretch(1)
        self.analyze_single_btn = QPushButton("Analyze Single Group")
        self.analyze_single_btn.clicked.connect(self.on_analyze_single_group_clicked)
        single_action_row.addWidget(self.analyze_single_btn)

        self.single_advanced_btn = QPushButton("Advanced…")
        self.single_advanced_btn.clicked.connect(self.on_single_advanced_clicked)
        single_action_row.addWidget(self.single_advanced_btn)
        single_action_row.addStretch(1)
        single_layout.addLayout(single_action_row)

        self.single_status_lbl = QLabel("Idle")
        self.single_status_lbl.setWordWrap(True)
        single_layout.addWidget(self.single_status_lbl)

        # between-group section
        between_box = QGroupBox("Between-Group Analysis")
        between_box.setSizePolicy(QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed))
        between_layout = QVBoxLayout(between_box)

        between_action_row = QHBoxLayout()
        between_action_row.addStretch(1)
        self.analyze_between_btn = QPushButton("Analyze Group Differences")
        self.analyze_between_btn.clicked.connect(self.on_analyze_between_groups_clicked)
        between_action_row.addWidget(self.analyze_between_btn)

        self.between_advanced_btn = QPushButton("Advanced…")
        self.between_advanced_btn.clicked.connect(self.on_between_advanced_clicked)
        between_action_row.addWidget(self.between_advanced_btn)
        between_action_row.addStretch(1)
        between_layout.addLayout(between_action_row)

        self.between_status_lbl = QLabel("Idle")
        self.between_status_lbl.setWordWrap(True)
        between_layout.addWidget(self.between_status_lbl)

        sections_layout.addWidget(single_group_box)
        sections_layout.addWidget(between_box)
        main_layout.addLayout(sections_layout)

        # output pane
        self.output_text = QPlainTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setPlaceholderText("Analysis output")
        self.output_text.setMinimumHeight(140)
        main_layout.addWidget(self.output_text, 1)

        main_layout.setStretch(0, 0)  # folder row
        main_layout.setStretch(1, 0)  # tools row
        main_layout.setStretch(2, 0)  # status label
        main_layout.setStretch(3, 0)  # ROI label
        main_layout.setStretch(4, 0)  # spinner row
        main_layout.setStretch(5, 0)  # analysis sections row
        main_layout.setStretch(6, 1)  # unified output pane

        # initialize export buttons
        self._update_export_buttons()

    # --------------------------- actions ---------------------------

    def on_analyze_single_group_clicked(self) -> None:
        if self.single_section_state.running:
            self.append_log("Single", f"{self.single_section_state.name} already running; new request ignored.")
            return
        if not self._precheck(start_guard=False):
            return
        summary = f"{len(self.subjects)} subjects, {len(self.conditions)} conditions"
        self.append_log("Single", f"{self.single_section_state.name} started ({summary})")
        steps = [
            PipelineStep(
                "RM-ANOVA",
                _rm_anova_calc,
                dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                ),
                lambda payload: self._apply_rm_anova_results(payload, update_text=False),
            ),
            PipelineStep(
                "Mixed Model",
                _lmm_calc,
                dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                ),
                lambda payload: self._apply_mixed_model_results(payload, update_text=False),
            ),
            PipelineStep(
                "Interaction Post-hocs",
                _posthoc_calc,
                dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                ),
                lambda payload: self._apply_posthoc_results(payload, update_text=True),
            ),
        ]
        self.single_section_state.steps = steps
        self._start_section(self.single_section_state, status_label=self.single_status_lbl)
        self._run_next_pipeline_step(self.single_section_state)

    def on_analyze_between_groups_clicked(self) -> None:
        if self.between_section_state.running:
            self.append_log("Between", f"{self.between_section_state.name} already running; new request ignored.")
            return
        if not self._precheck(start_guard=False):
            return
        if not self._ensure_between_ready():
            return
        summary = f"{len(self.subjects)} subjects, {len(self.conditions)} conditions"
        self.append_log("Between", f"{self.between_section_state.name} started ({summary})")
        steps = [
            PipelineStep(
                "Between-Group ANOVA",
                _between_group_anova_calc,
                dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                ),
                lambda payload: self._apply_between_anova_results(payload, update_text=False),
            ),
            PipelineStep(
                "Between-Group Mixed Model",
                _lmm_calc,
                dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                    include_group=True,
                ),
                lambda payload: self._apply_between_mixed_results(payload, update_text=False),
            ),
            PipelineStep(
                "Group Contrasts",
                _group_contrasts_calc,
                dict(
                    subjects=self.subjects,
                    conditions=self.conditions,
                    subject_data=self.subject_data,
                    base_freq=self._current_base_freq,
                    alpha=self._current_alpha,
                    rois=self.rois,
                    subject_groups=self.subject_groups,
                ),
                lambda payload: self._apply_group_contrasts_results(payload, update_text=True),
            ),
        ]
        self.between_section_state.steps = steps
        self._start_section(self.between_section_state, status_label=self.between_status_lbl)
        self._run_next_pipeline_step(self.between_section_state)

    def _open_advanced_dialog(self, title: str, actions: list[tuple[str, Callable[[], None], bool]]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        for text, cb, enabled in actions:
            btn = QPushButton(text)
            btn.setEnabled(enabled)
            btn.clicked.connect(cb)
            layout.addWidget(btn)
        layout.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def on_single_advanced_clicked(self) -> None:
        actions = [
            ("Run RM-ANOVA", self.on_run_rm_anova, True),
            ("Run Mixed Model", self.on_run_mixed_model, True),
            ("Run Interaction/Post-hocs", self.on_run_interaction_posthocs, True),
            (
                "Export RM-ANOVA",
                self.on_export_rm_anova,
                isinstance(self.rm_anova_results_data, pd.DataFrame) and not self.rm_anova_results_data.empty,
            ),
            (
                "Export Mixed Model",
                self.on_export_mixed_model,
                isinstance(self.mixed_model_results_data, pd.DataFrame) and not self.mixed_model_results_data.empty,
            ),
            (
                "Export Post-hocs",
                self.on_export_posthoc,
                isinstance(self.posthoc_results_data, pd.DataFrame) and not self.posthoc_results_data.empty,
            ),
        ]
        self._open_advanced_dialog("Single Group – Advanced", actions)

    def on_between_advanced_clicked(self) -> None:
        actions = [
            ("Run Between-Group ANOVA", self.on_run_between_anova, True),
            ("Run Between-Group Mixed Model", self.on_run_between_mixed_model, True),
            ("Run Group Contrasts", self.on_run_group_contrasts, True),
            (
                "Export Between-Group ANOVA",
                self.on_export_between_anova,
                isinstance(self.between_anova_results_data, pd.DataFrame)
                and not self.between_anova_results_data.empty,
            ),
            (
                "Export Between-Group Mixed Model",
                self.on_export_between_mixed,
                isinstance(self.between_mixed_model_results_data, pd.DataFrame)
                and not self.between_mixed_model_results_data.empty,
            ),
            (
                "Export Group Contrasts",
                self.on_export_group_contrasts,
                isinstance(self.group_contrasts_results_data, pd.DataFrame)
                and not self.group_contrasts_results_data.empty,
            ),
        ]
        self._open_advanced_dialog("Between-Group – Advanced", actions)

    def on_show_analysis_info(self) -> None:
        """
        Show a brief summary of the statistical methods used in the Stats tool.
        This is read-only and does not modify any data or settings.
        """
        text = (
            "FPVS Toolbox – Statistical Pipeline Overview\n\n"
            "Data analyzed\n"
            "• All analyses use the summed baseline-corrected oddball amplitude "
            "(Summed BCA) per subject × condition × ROI.\n\n"
            "Single-group analyses\n"
            "• RM-ANOVA: Repeated-measures ANOVA with within-subject factors "
            "condition and ROI. When available, Pingouin's rm_anova is used and "
            "both uncorrected and Greenhouse–Geisser/Huynh–Feldt corrected p-values "
            "are reported; otherwise statsmodels' AnovaRM is used (uncorrected p-values).\n"
            "• Post-hoc tests: Paired t-tests between conditions, run separately within "
            "each ROI. P-values are corrected for multiple comparisons using the "
            "Benjamini–Hochberg false discovery rate (FDR) procedure; exports include "
            "raw p and FDR-adjusted p (p_fdr_bh) plus effect sizes.\n"
            "• Mixed model: Linear mixed-effects model with a random intercept for each "
            "subject and fixed effects for condition, ROI, and their interaction. No "
            "additional multiple-comparison correction is applied to these coefficients.\n\n"
            "Multi-group analyses\n"
            "• Between-group ANOVA: Mixed ANOVA with group as a between-subject factor "
            "and condition as a within-subject factor on Summed BCA (ROI collapsed). "
            "Pingouin's mixed_anova is used when available.\n"
            "• Between-group mixed model: Linear mixed-effects model on Summed BCA with "
            "fixed effects for group, condition, ROI, and their interactions, plus a "
            "random intercept per subject.\n"
            "• Group contrasts: Pairwise group comparisons (Welch's t-tests) computed "
            "separately for each condition × ROI. P-values are corrected for multiple "
            "comparisons using Benjamini–Hochberg FDR, and effect sizes (Cohen's d) "
            "are reported.\n\n"
            "General notes\n"
            "• Unless otherwise noted, the default alpha level is 0.05.\n"
            "• Excel exports in the '3 - Statistical Analysis Results' folder contain "
            "the full tables for all analyses, including raw and corrected p-values.\n"
        )

        QMessageBox.information(
            self,
            "FPVS Toolbox – Analysis Info",
            text,
        )

    def _check_for_open_excel_files(self, folder_path: str) -> bool:
        """Best-effort check to avoid writing to open Excel files."""
        if not folder_path or not os.path.isdir(folder_path):
            return False
        open_files = []
        for name in os.listdir(folder_path):
            if name.lower().endswith((".xlsx", ".xls")):
                fpath = os.path.join(folder_path, name)
                try:
                    os.rename(fpath, fpath)
                except OSError:
                    open_files.append(name)
        if open_files:
            file_list_str = "\n - ".join(open_files)
            error_message = (
                "The following Excel file(s) appear to be open:\n\n"
                f"<b> - {file_list_str}</b>\n\n"
                "Please close all Excel files in the data directory and try again."
            )
            QMessageBox.critical(self, "Open Excel File Detected", error_message)
            return True
        return False

    # ---- run buttons ----

    def on_run_rm_anova(self) -> None:
        if not self._precheck():
            return
        self.output_text.clear()
        self.rm_anova_results_data = None
        self._update_export_buttons()

        worker = StatsWorker(
            _rm_anova_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
        )
        self._wire_and_start(worker, self._on_rm_anova_finished)

    def on_run_mixed_model(self) -> None:
        if not self._precheck():
            return
        self.output_text.clear()
        self.mixed_model_results_data = None
        self._update_export_buttons()

        worker = StatsWorker(
            _lmm_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            rois=self.rois,
            subject_groups=self.subject_groups,
        )
        self._wire_and_start(worker, self._on_mixed_model_finished)

    def on_run_between_anova(self) -> None:
        if not self._precheck():
            return
        if not self._ensure_between_ready():
            self._end_run()
            return
        self.output_text.clear()
        self.between_anova_results_data = None
        self._update_export_buttons()

        worker = StatsWorker(
            _between_group_anova_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            rois=self.rois,
            subject_groups=self.subject_groups,
        )
        self._wire_and_start(worker, self._on_between_anova_finished)

    def on_run_between_mixed_model(self) -> None:
        if not self._precheck():
            return
        if not self._ensure_between_ready():
            self._end_run()
            return
        self.output_text.clear()
        self.between_mixed_model_results_data = None
        self._update_export_buttons()

        worker = StatsWorker(
            _lmm_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            rois=self.rois,
            subject_groups=self.subject_groups,
            include_group=True,
        )
        self._wire_and_start(worker, self._on_between_mixed_finished)

    def on_run_group_contrasts(self) -> None:
        if not self._precheck():
            return
        if not self._ensure_between_ready():
            self._end_run()
            return
        self.output_text.clear()
        self.group_contrasts_results_data = None
        self._update_export_buttons()

        worker = StatsWorker(
            _group_contrasts_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            rois=self.rois,
            subject_groups=self.subject_groups,
        )
        self._wire_and_start(worker, self._on_group_contrasts_finished)

    def on_run_interaction_posthocs(self) -> None:
        if not self._precheck(require_anova=True):
            return
        self.output_text.clear()
        self.posthoc_results_data = None
        our = self._update_export_buttons  # keep line short
        our()

        worker = StatsWorker(
            _posthoc_calc,
            subjects=self.subjects,
            conditions=self.conditions,
            subject_data=self.subject_data,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            rois=self.rois,
            subject_groups=self.subject_groups,
        )
        self._wire_and_start(worker, self._on_posthoc_finished)

    def on_run_harmonic_check(self) -> None:
        if not self._precheck():
            return
        if not (self.subject_data and self.subjects and self.conditions):
            QMessageBox.warning(self, "Data Error", "No subject data found. Please select a valid data folder first.")
            self._end_run()
            return
        selected_metric = self.cb_metric.currentText()
        mean_value_threshold = float(self.threshold_spin.value())

        self._harmonic_metric = selected_metric  # for legacy exporter

        self.output_text.clear()
        self.harmonic_check_results_data = []
        self._update_export_buttons()

        worker = StatsWorker(
            _harmonic_calc,
            subject_data=self.subject_data,
            subjects=self.subjects,
            conditions=self.conditions,
            selected_metric=selected_metric,
            mean_value_threshold=mean_value_threshold,
            base_freq=self._current_base_freq,
            alpha=self._current_alpha,
            rois=self.rois,
        )
        self._wire_and_start(worker, self._on_harmonic_finished)

    # ---- exports ----

    def on_export_rm_anova(self) -> None:
        if not isinstance(self.rm_anova_results_data, pd.DataFrame) or self.rm_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run RM-ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova", self.rm_anova_results_data, out_dir)
            self._set_status(f"RM-ANOVA exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_mixed_model(self) -> None:
        if not isinstance(self.mixed_model_results_data, pd.DataFrame) or self.mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm", self.mixed_model_results_data, out_dir)
            self._set_status(f"Mixed Model results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_between_anova(self) -> None:
        if not isinstance(self.between_anova_results_data, pd.DataFrame) or self.between_anova_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group ANOVA first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("anova_between", self.between_anova_results_data, out_dir)
            self._set_status(f"Between-group ANOVA exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_between_mixed(self) -> None:
        if not isinstance(self.between_mixed_model_results_data, pd.DataFrame) or self.between_mixed_model_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Between-Group Mixed Model first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("lmm_between", self.between_mixed_model_results_data, out_dir)
            self._set_status(f"Between-group Mixed Model exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_posthoc(self) -> None:
        if not isinstance(self.posthoc_results_data, pd.DataFrame) or self.posthoc_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Interaction Post-hocs first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("posthoc", self.posthoc_results_data, out_dir)
            self._set_status(f"Post-hoc results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_group_contrasts(self) -> None:
        if not isinstance(self.group_contrasts_results_data, pd.DataFrame) or self.group_contrasts_results_data.empty:
            QMessageBox.information(self, "No Results", "Run Group Contrasts first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("group_contrasts", self.group_contrasts_results_data, out_dir)
            self._set_status(f"Group contrasts exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    def on_export_harmonic(self) -> None:
        if not self.harmonic_check_results_data:
            QMessageBox.information(self, "No Results", "Run Harmonic Check first.")
            return
        out_dir = self._ensure_results_dir()
        try:
            self.export_results("harmonic", self.harmonic_check_results_data, out_dir)
            self._set_status(f"Harmonic check results exported to: {out_dir}")
        except Exception as e:
            QMessageBox.critical(self, "Export Failed", str(e))

    # ---- folder & scan ----

    def on_browse_folder(self) -> None:
        start_dir = self.le_folder.text() or self.project_dir
        folder = QFileDialog.getExistingDirectory(self, "Select Data Folder", start_dir)
        if folder:
            self.le_folder.setText(folder)
            self._scan_button_clicked()

    def _scan_button_clicked(self) -> None:
        if not self._scan_guard.start():
            return
        try:
            self.refresh_rois()
            folder = self.le_folder.text()
            if not folder:
                QMessageBox.warning(self, "No Folder", "Please select a data folder first.")
                return
            try:
                self.subject_groups = {}
                self._multi_group_manifest = False
                subjects, conditions, data = scan_folder_simple(folder)
                manifest = _load_project_manifest_for_excel_root(Path(folder))
                participants_map = _normalize_participants_map(manifest)
                subject_groups = _map_subjects_to_groups(subjects, participants_map)
                has_multi_groups = _has_multi_groups(manifest)
                self._multi_group_manifest = has_multi_groups

                if has_multi_groups:
                    self._warn_unknown_excel_files(data, participants_map)

                self.subjects = subjects
                self.conditions = conditions
                self.subject_data = data
                self.subject_groups = subject_groups
                self._set_status(
                    f"Scan complete: Found {len(subjects)} subjects and {len(conditions)} conditions."
                )
            except ScanError as e:
                self._set_status(f"Scan failed: {e}")
                QMessageBox.critical(self, "Scan Error", str(e))
        finally:
            self._scan_guard.done()



    def _preferred_stats_folder(self) -> Path:
        """Default Excel folder derived from the project manifest."""
        return _resolve_project_subfolder(
            self._project_path,
            self._results_folder_hint,
            self._subfolder_hints,
            "excel",
            EXCEL_SUBFOLDER_NAME,
        )

    def _load_default_data_folder(self) -> None:
        """
        On open, auto-select the manifest-defined Excel folder (defaults to
        ``1 - Excel Data Files`` under the project root). If it doesn't exist,
        do nothing (user can Browse).
        """
        target = self._preferred_stats_folder()
        if target.exists() and target.is_dir():
            self.le_folder.setText(str(target))
            self._scan_button_clicked()
        else:
            # Leave UI as-is; user will browse. Status hint only.
            self._set_status(
                f"Select the project's '{EXCEL_SUBFOLDER_NAME}' folder to begin."
            )



"""Root class for the Stats tool window.

StatsWindow keeps the import and construction surface stable while the
implementation is split across focused internal mixin modules.
"""

from __future__ import annotations

from Tools.Stats.common.stats_window_types import HarmonicConfig
from Tools.Stats.ui.stats_window_support import *  # noqa: F403
from Tools.Stats.ui.stats_window_actions import StatsWindowActionsMixin
from Tools.Stats.ui.stats_window_exclusions import StatsWindowExclusionsMixin
from Tools.Stats.ui.stats_window_exports import StatsWindowExportsMixin
from Tools.Stats.ui.stats_window_pipeline import StatsWindowPipelineMixin
from Tools.Stats.ui.stats_window_ui import StatsWindowUiMixin

logger = logging.getLogger(__name__)


class StatsWindow(
    StatsWindowActionsMixin,
    StatsWindowExclusionsMixin,
    StatsWindowExportsMixin,
    StatsWindowPipelineMixin,
    StatsWindowUiMixin,
    QMainWindow,
):
    """PySide6 window wrapping the FPVS Statistical Analysis Tool."""

    def __init__(
        self,
        parent: Optional[QMainWindow] = None,
        project_dir: Optional[str] = None,
    ):
        """Set up this object so it is ready to be used by the Stats tool."""
        if project_dir and os.path.isdir(project_dir):
            self.project_dir = project_dir
        else:
            proj = getattr(parent, "currentProject", None)
            self.project_dir = (
                str(proj.project_root) if proj and hasattr(proj, "project_root") else auto_detect_project_dir()
            )

        self._project_path = Path(self.project_dir).resolve()
        self._results_folder_hint: str | None = None
        self._subfolder_hints: dict[str, str] = {}
        self.project_title = os.path.basename(self.project_dir)
        self._load_project_context_from_root(self._project_path)

        super().__init__(parent)
        self.setWindowTitle("FPVS Statistical Analysis Tool")
        logger.info(
            "stats_window_init",
            extra={
                "window_id": id(self),
                "project_dir": self.project_dir,
            },
        )

        self._guard = OpGuard()
        if not hasattr(self._guard, "done"):
            self._guard.done = self._guard.end  # type: ignore[attr-defined]
        self.pool = QThreadPool.globalInstance()
        self._focus_calls = 0
        # Strong references to active StatsWorker instances to avoid any
        # lifetime / GC edge cases that could drop Qt signals.
        self._active_workers: list[StatsWorker] = []

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        configure_window_surface(self)

        # re-entrancy guard for scan
        self._scan_guard = OpGuard()
        if not hasattr(self._scan_guard, "done"):
            self._scan_guard.done = self._scan_guard.end  # type: ignore[attr-defined]
        # --- state ---
        self.subject_data: Dict = {}
        self.subjects: List[str] = []
        self.conditions: List[str] = []
        self.selected_conditions: List[str] = []
        self._participants_map: dict[str, str] = {}
        self._subject_group_map: dict[str, str | None] = {}
        self.rm_anova_results_data: Optional[pd.DataFrame] = None
        self.mixed_model_results_data: Optional[pd.DataFrame] = None
        self.posthoc_results_data: Optional[pd.DataFrame] = None
        self.baseline_vs_zero_results_payload: Optional[dict] = None
        self.harmonic_check_results_data: List[dict] = []
        self._harmonic_results: dict[PipelineId, list[dict]] = {
            PipelineId.SINGLE: [],
        }
        self.rois: Dict[str, List[str]] = {}
        self._harmonic_config: HarmonicConfig = HarmonicConfig("Z Score", 1.64)
        self._current_base_freq: float = 6.0
        self._current_alpha: float = 0.05
        self._active_pipeline: PipelineId | None = None
        self._condition_checkboxes: dict[str, QCheckBox] = {}
        self._dv_policy_name: str = ROSSION_POLICY_NAME
        self._dv_fixed_k: int = 5
        self._dv_exclude_harmonic1: bool = False
        self._dv_exclude_base_harmonics: bool = True
        self._dv_group_mean_z_threshold: float = 1.64
        self._dv_empty_list_policy: str = EMPTY_LIST_ERROR
        self._dv_variant_checkboxes: dict[str, QCheckBox] = {}
        self._dv_variants_selected: List[str] = []
        self._outlier_exclusion_enabled: bool = True
        self._outlier_abs_limit: float = 50.0
        self.manual_excluded_pids: set[str] = set()
        self._manual_exclusion_candidates: List[str] = []
        self._pipeline_conditions: dict[PipelineId, list[str]] = {}
        self._pipeline_dv_policy: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_base_freq: dict[PipelineId, float] = {}
        self._pipeline_dv_metadata: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_dv_variants: dict[PipelineId, list[str]] = {}
        self._pipeline_dv_variant_payloads: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_outlier_config: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_qc_config: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_qc_state: dict[PipelineId, dict[str, object]] = {}
        self._pipeline_run_reports: dict[PipelineId, StatsRunReport | None] = {}
        self._group_mean_preview_data: dict[str, object] = {}
        self._qc_threshold_sumabs: float = QC_DEFAULT_WARN_THRESHOLD
        self._qc_threshold_maxabs: float = QC_DEFAULT_CRITICAL_THRESHOLD
        self._last_export_path: str | None = None
        self._reporting_summary_text: str = ""
        self._pipeline_start_perf: dict[PipelineId, float] = {}

        # --- legacy UI proxies ---
        self.stats_data_folder_var = SimpleNamespace(
            get=lambda: self.le_folder.text() if hasattr(self, "le_folder") else "",
            set=lambda v: self._set_data_folder_path(v) if hasattr(self, "le_folder") else None,
        )
        self.detected_info_var = SimpleNamespace(set=lambda t: self._set_status(t))
        self.roi_var = SimpleNamespace(get=lambda: ALL_ROIS_OPTION, set=lambda v: None)
        self.alpha_var = SimpleNamespace(get=lambda: "0.05", set=lambda v: None)

        # UI
        self._init_ui()
        self.results_textbox = self.summary_text
        self._update_manual_exclusion_summary()

        self.refresh_rois()
        QTimer.singleShot(100, self._load_default_data_folder)

        self._progress_updates: List[int] = []

        # controller
        self._controller = StatsController(view=self)

    def _load_project_context_from_root(self, project_root: Path) -> None:
        """Refresh Stats output-path metadata from a project root."""
        self._project_path = Path(project_root).resolve()
        self.project_dir = str(self._project_path)
        self._results_folder_hint = None
        self._subfolder_hints = {}
        config_path = self._project_path / "project.json"
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            self.project_title = cfg.get("name", cfg.get("title", os.path.basename(self.project_dir)))
            self._results_folder_hint, self._subfolder_hints = load_manifest_data(self._project_path, cfg)
        except Exception:
            self.project_title = os.path.basename(self.project_dir)

    def rebind_project_context(
        self,
        project_root: str | Path,
        *,
        clear_last_export: bool = True,
        reload_default_folder: bool = False,
    ) -> None:
        """Update project-owned output paths after the host project changes."""
        new_root = Path(project_root).resolve()
        old_root = getattr(self, "_project_path", None)
        if old_root is not None and Path(old_root).resolve() == new_root:
            return
        self._load_project_context_from_root(new_root)
        self._clear_project_bound_stats_state()
        if clear_last_export:
            self._set_last_export_path(None)
        if reload_default_folder:
            self._load_default_data_folder()
        logger.info(
            "stats_window_project_context_rebound",
            extra={
                "window_id": id(self),
                "project_dir": self.project_dir,
            },
        )

    def _clear_project_bound_stats_state(self) -> None:
        """Clear scanned inputs and results that belong to the previous project."""
        self.subject_data = {}
        self.subjects = []
        self.conditions = []
        self.selected_conditions = []
        self._participants_map = {}
        self._subject_group_map = {}
        self.manual_excluded_pids.clear()
        self._manual_exclusion_candidates = []
        self.rm_anova_results_data = None
        self.mixed_model_results_data = None
        self.posthoc_results_data = None
        self.baseline_vs_zero_results_payload = None
        self.harmonic_check_results_data = []
        self._harmonic_results = {PipelineId.SINGLE: []}
        self._active_pipeline = None
        self._group_mean_preview_data = {}
        self._pipeline_conditions.clear()
        self._pipeline_dv_policy.clear()
        self._pipeline_base_freq.clear()
        self._pipeline_dv_metadata.clear()
        self._pipeline_dv_variants.clear()
        self._pipeline_dv_variant_payloads.clear()
        self._pipeline_outlier_config.clear()
        self._pipeline_qc_config.clear()
        self._pipeline_qc_state.clear()
        self._pipeline_run_reports.clear()
        if hasattr(self, "conditions_list_layout"):
            self._populate_conditions_panel([])
        if hasattr(self, "summary_text"):
            self.summary_text.clear()
        if hasattr(self, "output_text"):
            self.output_text.clear()
        if hasattr(self, "le_folder"):
            self._set_data_folder_path("")
        if hasattr(self, "_update_manual_exclusion_summary"):
            self._update_manual_exclusion_summary()
        if hasattr(self, "_update_export_buttons"):
            self._update_export_buttons()

    # --------- ROI + status helpers ---------

    def refresh_rois(self) -> None:
        """Handle the refresh rois step for the Stats workflow."""
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
        """Handle the update roi label step for the Stats workflow."""
        names = list(self.rois.keys())
        txt = "Using {} ROI{} from Settings: {}".format(
            len(names), "" if len(names) == 1 else "s", ", ".join(names)
        ) if names else "No ROIs defined in Settings."
        self._set_roi_status(txt)


__all__ = ["HarmonicConfig", "StatsWindow"]

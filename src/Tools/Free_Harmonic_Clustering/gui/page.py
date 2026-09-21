"""Embedded PySide6 page for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import logging

from PySide6.QtCore import QSize, QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from Main_App.gui.components import (
    SectionCard,
    StatusBanner,
    apply_font_role,
    make_action_button,
    make_action_row,
    make_form_layout,
    make_info_button,
    show_tool_info,
)
from Tools.Free_Harmonic_Clustering.tool_info import (
    FREE_HARMONIC_CLUSTERING_TOOL_INFO,
    HARMONIC_SELECTION_TOOL_INFO,
)

from .backend_adapter import FreeHarmonicBackend, FreeHarmonicBackendAdapter
from ..analysis_plan import AnalysisFamily, build_analysis_plan
from ..models import FreeHarmonicInputError
from .analysis_plan_state import (
    AnalysisPlanPreferences, AnalysisPlanStateError,
    load_analysis_plan_preferences, save_analysis_plan_preferences,
)
from .exclusion_state import (
    ExclusionStateError,
    load_project_recording_exclusions,
    save_project_recording_exclusions,
)
from .models import (
    AnalysisRecordingExclusion,
    AnalysisSetup,
    AnalysisWorkerOutcome,
    GuiAnalysisDesign,
    GuiHarmonicMode,
    ProjectAnalysisOptions,
    ProjectFrequencySnapshot,
    PlannedAnalysisSetup,
    PlannedAnalysisWorkerOutcome,
    RepeatedBatchSetup,
    RepeatedBatchWorkerOutcome,
    RunOutcome,
)
from .operation_registry import (
    register_active_operation,
    release_active_operation,
)
from .recording_exclusions_dialog import RecordingExclusionsDialog
from .workers import (
    AnalysisWorker,
    ProjectInspectionWorker,
    PlannedAnalysisWorker,
    RepeatedSessionBatchWorker,
)


logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from ..reporting import RepeatedSessionReportRow
    from ..visualization import ClusterMapData
    from .cluster_map_view import ClusterMapView

_FREQUENCY_UNSET = object()


def _frequency_text(value: float) -> str:
    return f"{float(value):g} Hz"


class _CurrentPageStackedWidget(QStackedWidget):
    """Size a progressive setup stack to its visible page only."""

    def sizeHint(self) -> QSize:  # noqa: N802
        current = self.currentWidget()
        return super().sizeHint() if current is None else current.sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        current = self.currentWidget()
        return super().minimumSizeHint() if current is None else current.minimumSizeHint()


class FreeHarmonicClusteringPage(QWidget):
    """Project-bound, source-immutable analysis workspace page."""

    post_processing_required = Signal(str, str, str)
    protocol_settings_required = Signal()

    def __init__(
        self,
        project_root: str | Path,
        frequency_snapshot: ProjectFrequencySnapshot | Mapping[str, object] | None,
        *,
        frequency_error: str | None = None,
        backend: FreeHarmonicBackend | None = None,
        auto_discover: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("free_harmonic_clustering_page")
        self.setWindowTitle("Free Harmonic Clustering Analysis")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._backend = backend or FreeHarmonicBackendAdapter()
        self._project_root = Path(project_root).expanduser().resolve(strict=False)
        self._frequency_snapshot: ProjectFrequencySnapshot | None = None
        self._frequency_error: str | None = str(frequency_error) if frequency_error else None
        try:
            if frequency_snapshot is not None:
                self._frequency_snapshot = ProjectFrequencySnapshot.coerce(
                    frequency_snapshot
                )
        except (TypeError, ValueError, OverflowError) as exc:
            self._frequency_error = str(exc)

        self._options: ProjectAnalysisOptions | None = None
        self._recording_exclusions: tuple[AnalysisRecordingExclusion, ...] = ()
        self._has_result = False
        self._batch_report_rows: tuple[RepeatedSessionReportRow, ...] = ()
        self._batch_summary_text = ""
        self.map_view: ClusterMapView | None = None
        self._thread: QThread | None = None
        self._worker: object | None = None
        self._completion_callback: Callable[[object], None] | None = None
        self._active_stage: str | None = None
        self._pending_context: tuple[Path, ProjectFrequencySnapshot | None, str | None] | None = None
        self._pending_post_processing_reason: str | None = None
        self._updating_controls = False
        self._retired = False
        self._inspection_failed = False
        self._analysis_plan_state_error = ""
        self._recording_exclusion_state_error = ""

        self._build_ui()
        self._connect_signals()
        self._reset_session_views()
        self._update_results_folder_button()

        if auto_discover:
            QTimer.singleShot(0, self._begin_project_inspection)
        else:
            self._show_frequency_or_ready_status()

    @property
    def project_root(self) -> Path:
        """Active managed project root used by Main App page reuse checks."""

        return self._project_root

    @property
    def frequency_snapshot(self) -> ProjectFrequencySnapshot | None:
        """Read-only frequency snapshot associated with the current session."""

        return self._frequency_snapshot

    @property
    def has_active_work(self) -> bool:
        """Whether an operation thread still owns live project work."""

        return self._thread is not None

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(12)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 20, 24, 0)
        header_layout.setSpacing(8)
        heading_text = QWidget(header)
        heading_layout = QVBoxLayout(heading_text)
        heading_layout.setContentsMargins(0, 0, 0, 0)
        heading_layout.setSpacing(3)
        title = QLabel("Free Harmonic Clustering Analysis", heading_text)
        title.setProperty("toolTitle", True)
        apply_font_role(title, "tool_title")
        heading_layout.addWidget(title)
        header_layout.addWidget(heading_text, 1)
        self.about_button = make_info_button(
            parent=header,
            tooltip="About this analysis",
            object_name="free_harmonic_about_button",
            size=22,
        )
        header_layout.addWidget(self.about_button, 0, Qt.AlignTop)
        root_layout.addWidget(header)

        self.workspace = QWidget(self)
        self.workspace.setObjectName("free_harmonic_workspace")
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)
        self.setup_panel = QWidget(self.workspace)
        self.setup_panel.setObjectName("free_harmonic_setup_panel")
        self.setup_panel.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Maximum,
        )
        self.results_panel = QWidget(self.workspace)
        self.results_panel.setObjectName("free_harmonic_results_panel")
        workspace_layout.addWidget(self.setup_panel, 0)
        workspace_layout.addStretch(1)
        self.result_tabs = QTabWidget(self)
        self.result_tabs.setObjectName("free_harmonic_result_tabs")
        self.result_tabs.addTab(self.workspace, "Setup")
        self.result_tabs.addTab(self.results_panel, "Results")
        self.result_tabs.setTabEnabled(1, False)
        self.map_panel = QWidget(self.result_tabs)
        self.map_panel.setObjectName("free_harmonic_map_panel")
        self.map_layout = QVBoxLayout(self.map_panel)
        self.map_layout.setContentsMargins(24, 8, 24, 8)
        self.result_tabs.addTab(self.map_panel, "Cluster maps")
        self.result_tabs.setTabEnabled(2, False)
        root_layout.addWidget(self.result_tabs, 1)

        self._build_setup_panel()
        self._build_results_panel()
        self._build_workflow_footer(root_layout)

    def _build_setup_panel(self) -> None:
        content = self.setup_panel
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(14)

        cards_layout = QHBoxLayout()
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.setSpacing(14)
        layout.addLayout(cards_layout)

        self.comparison_card = SectionCard(
            "Comparison",
            content,
            object_name="free_harmonic_comparison_card",
        )
        self.comparison_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        cards_layout.addWidget(self.comparison_card, 3)
        comparison_form = make_form_layout()
        self.comparison_card.content_layout.addLayout(comparison_form)

        self.design_combo = QComboBox(self.comparison_card.content)
        self.design_combo.setObjectName("free_harmonic_design_combo")
        self.design_combo.addItem(
            "Paired Conditions",
            GuiAnalysisDesign.PAIRED_CONDITIONS.value,
        )
        self.design_combo.addItem(
            "Independent Groups",
            GuiAnalysisDesign.INDEPENDENT_GROUPS.value,
        )
        comparison_form.addRow("Analysis mode:", self.design_combo)

        self.design_stack = _CurrentPageStackedWidget(self.comparison_card.content)
        self.design_stack.setObjectName("free_harmonic_design_stack")
        self.design_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        comparison_form.addRow(self.design_stack)
        paired_panel = QWidget(self.design_stack)
        paired_form = make_form_layout()
        paired_panel.setLayout(paired_form)
        self.paired_condition_a_combo = QComboBox(paired_panel)
        self.paired_condition_a_combo.setObjectName(
            "free_harmonic_paired_condition_a"
        )
        paired_form.addRow("Condition A:", self.paired_condition_a_combo)
        self.paired_condition_b_combo = QComboBox(paired_panel)
        self.paired_condition_b_combo.setObjectName(
            "free_harmonic_paired_condition_b"
        )
        paired_form.addRow("Condition B:", self.paired_condition_b_combo)
        self.paired_group_filter_combo = QComboBox(paired_panel)
        self.paired_group_filter_combo.setObjectName(
            "free_harmonic_paired_group_filter"
        )
        paired_form.addRow("Group filter:", self.paired_group_filter_combo)
        self.design_stack.addWidget(paired_panel)

        independent_panel = QWidget(self.design_stack)
        independent_form = make_form_layout()
        independent_panel.setLayout(independent_form)
        self.independent_condition_combo = QComboBox(independent_panel)
        self.independent_condition_combo.setObjectName(
            "free_harmonic_independent_condition"
        )
        independent_form.addRow("Condition:", self.independent_condition_combo)
        self.independent_group_a_combo = QComboBox(independent_panel)
        self.independent_group_a_combo.setObjectName(
            "free_harmonic_independent_group_a"
        )
        independent_form.addRow("Group A:", self.independent_group_a_combo)
        self.independent_group_b_combo = QComboBox(independent_panel)
        self.independent_group_b_combo.setObjectName(
            "free_harmonic_independent_group_b"
        )
        independent_form.addRow("Group B:", self.independent_group_b_combo)
        self.design_stack.addWidget(independent_panel)

        repeated_panel = QWidget(self.design_stack)
        repeated_form = make_form_layout()
        repeated_panel.setLayout(repeated_form)
        self.repeated_groups_value = QLabel("Loading...", repeated_panel)
        self.repeated_groups_value.setObjectName("free_harmonic_repeated_groups")
        self.repeated_groups_value.setWordWrap(True)
        repeated_form.addRow("Stable groups:", self.repeated_groups_value)
        self.review_exclusions_button = make_action_button(
            "Review recording exclusions...",
            compact=True,
            parent=repeated_panel,
        )
        self.review_exclusions_button.setObjectName(
            "free_harmonic_review_recording_exclusions"
        )
        self.exclusion_count_label = QLabel(
            "No analysis-specific exclusions.",
            repeated_panel,
        )
        self.exclusion_count_label.setObjectName(
            "free_harmonic_recording_exclusion_count"
        )
        self.exclusion_count_label.setWordWrap(True)
        exclusion_row = QWidget(repeated_panel)
        exclusion_layout = QHBoxLayout(exclusion_row)
        exclusion_layout.setContentsMargins(0, 0, 0, 0)
        exclusion_layout.setSpacing(8)
        exclusion_layout.addWidget(self.review_exclusions_button)
        exclusion_layout.addWidget(self.exclusion_count_label, 1)
        repeated_form.addRow("Run exclusions:", exclusion_row)
        self.design_stack.addWidget(repeated_panel)

        for combo in (
            self.design_combo,
            self.paired_condition_a_combo,
            self.paired_condition_b_combo,
            self.paired_group_filter_combo,
            self.independent_condition_combo,
            self.independent_group_a_combo,
            self.independent_group_b_combo,
        ):
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(24)

        self.direction_label = QLabel(
            "Contrast: A - B",
            self.comparison_card.content,
        )
        self.direction_label.setObjectName("free_harmonic_direction_label")
        self.direction_label.setWordWrap(True)
        self.direction_label.setProperty("caption", True)
        comparison_form.addRow(self.direction_label)

        self.harmonics_card = SectionCard(
            "Harmonics",
            content,
            object_name="free_harmonic_harmonics_card",
        )
        self.harmonics_card.set_compact()
        cards_layout.addWidget(self.harmonics_card, 2, Qt.AlignTop)
        harmonics_form = make_form_layout()
        self.harmonics_card.content_layout.addLayout(harmonics_form)

        self.harmonic_mode_combo = QComboBox(self.harmonics_card.content)
        self.harmonic_mode_combo.setObjectName("free_harmonic_mode_combo")
        self.harmonic_mode_combo.addItem(
            "Hermann automatic selection",
            GuiHarmonicMode.AUTOMATIC.value,
        )
        self.harmonic_mode_combo.addItem(
            "Fixed harmonic list",
            GuiHarmonicMode.FIXED_HIGHEST.value,
        )
        harmonics_form.addRow("Harmonic domain:", self.harmonic_mode_combo)

        fixed_row = QWidget(self.harmonics_card.content)
        fixed_layout = QHBoxLayout(fixed_row)
        fixed_layout.setContentsMargins(0, 0, 0, 0)
        fixed_layout.setSpacing(6)
        self.fixed_highest_combo = QComboBox(fixed_row)
        self.fixed_highest_combo.setObjectName("free_harmonic_fixed_highest_combo")
        fixed_layout.addWidget(self.fixed_highest_combo, 1)
        self.harmonic_info_button = make_info_button(
            parent=fixed_row,
            tooltip="How harmonic fill-through works",
            object_name="free_harmonic_selection_info_button",
        )
        fixed_layout.addWidget(self.harmonic_info_button)
        self.fixed_highest_label = QLabel(
            "Highest harmonic:",
            self.harmonics_card.content,
        )
        harmonics_form.addRow(self.fixed_highest_label, fixed_row)

        for combo in (
            self.harmonic_mode_combo,
            self.fixed_highest_combo,
        ):
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            combo.setSizeAdjustPolicy(
                QComboBox.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(24)

        aligned_fields = (
            (comparison_form, self.design_combo),
            (paired_form, self.paired_condition_a_combo),
            (paired_form, self.paired_condition_b_combo),
            (paired_form, self.paired_group_filter_combo),
            (independent_form, self.independent_condition_combo),
            (independent_form, self.independent_group_a_combo),
            (independent_form, self.independent_group_b_combo),
            (repeated_form, self.repeated_groups_value),
            (repeated_form, exclusion_row),
            (harmonics_form, self.harmonic_mode_combo),
            (harmonics_form, fixed_row),
        )
        for form_layout, field in aligned_fields:
            label = form_layout.labelForField(field)
            if label is not None:
                label.setFixedWidth(120)

        # Historical single-contrast controls remain for v1 integration adapters;
        # new runs use one explicit family plan on the visible setup surface.
        self.comparison_card.hide()
        self.plan_card = SectionCard("Analysis families", content, object_name="free_harmonic_plan_card")
        cards_layout.insertWidget(0, self.plan_card, 3)
        self.plan_context_label = QLabel("Loading project design...", self.plan_card.content)
        self.plan_context_label.setWordWrap(True)
        self.plan_card.content_layout.addWidget(self.plan_context_label)
        self.family_checks = {}
        family_labels = {
            AnalysisFamily.BETWEEN_GROUPS: "Between-group differences",
            AnalysisFamily.BETWEEN_CONDITIONS: "Between-condition differences",
            AnalysisFamily.WITHIN_GROUP_VISITS: "Within-group visit changes",
            AnalysisFamily.GROUP_VISIT_CHANGE: "Between-group differences in visit change",
        }
        for family, label in family_labels.items():
            check = QCheckBox(label, self.plan_card.content)
            check.setObjectName(f"free_harmonic_family_{family.value}")
            self.family_checks[family] = check
            self.plan_card.content_layout.addWidget(check)
        self.condition_plan_row = QWidget(self.plan_card.content)
        condition_form = make_form_layout()
        self.condition_plan_row.setLayout(condition_form)
        self.condition_mode_combo = QComboBox(self.condition_plan_row)
        self.condition_mode_combo.setObjectName("free_harmonic_condition_comparisons")
        self.condition_mode_combo.addItem("Compare each condition with a reference", "reference")
        self.condition_mode_combo.addItem("All pairs of conditions", "all_pairs")
        condition_form.addRow("Condition tests:", self.condition_mode_combo)
        self.reference_condition_combo = QComboBox(self.condition_plan_row)
        self.reference_condition_combo.setObjectName("free_harmonic_reference_condition")
        self.reference_condition_label = QLabel("Reference:", self.condition_plan_row)
        condition_form.addRow(self.reference_condition_label, self.reference_condition_combo)
        self.plan_card.content_layout.addWidget(self.condition_plan_row)
        self.plan_summary_label = QLabel("Choose the questions to include in this analysis.", self.plan_card.content)
        self.plan_summary_label.setObjectName("free_harmonic_plan_summary")
        self.plan_summary_label.setWordWrap(True)
        self.plan_card.content_layout.addWidget(self.plan_summary_label)
        self.review_comparisons_button = make_action_button("Review comparisons...", compact=True, parent=self.plan_card.content)
        self.review_comparisons_button.setObjectName("free_harmonic_review_comparisons")
        self.plan_card.content_layout.addWidget(self.review_comparisons_button, 0, Qt.AlignLeft)
        repeated_form.removeWidget(exclusion_row)
        self.plan_exclusion_row = exclusion_row
        self.plan_card.content_layout.addWidget(exclusion_row)
        self.family_correction_note = QLabel(
            "Each selected family is corrected with Holm at .05. Both groups' visit changes share one family. "
            "Exploratory findings remain available in Results.", self.plan_card.content,
        )
        self.family_correction_note.setWordWrap(True)
        self.family_correction_note.setProperty("caption", True)
        self.plan_card.content_layout.addWidget(self.family_correction_note)

    def _build_workflow_footer(self, root_layout: QVBoxLayout) -> None:
        footer = QWidget(self)
        footer.setObjectName("free_harmonic_workflow_footer")
        footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(24, 0, 24, 20)
        footer_layout.setSpacing(6)
        self.workflow_status = StatusBanner(
            "Loading project inputs...",
            footer,
            variant="info",
        )
        self.workflow_status.setObjectName("free_harmonic_workflow_status")
        self.fix_setup_button = make_action_button("Fix setup", compact=True, parent=self.workflow_status)
        self.fix_setup_button.setObjectName("free_harmonic_fix_setup")
        self.fix_setup_button.clicked.connect(self._focus_setup_issue)
        self.fix_setup_button.hide()
        self.workflow_status.banner_layout.addWidget(self.fix_setup_button)
        footer_layout.addWidget(self.workflow_status)
        self.progress_bar = QProgressBar(footer)
        self.progress_bar.setObjectName("free_harmonic_progress_bar")
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        footer_layout.addWidget(self.progress_bar)
        self.run_analysis_button = make_action_button(
            "Run Free Harmonic Clustering Analysis",
            variant="primary",
            parent=footer,
        )
        self.run_analysis_button.setObjectName("free_harmonic_run_analysis_button")
        self.cancel_button = make_action_button(
            "Cancel",
            variant="tertiary",
            parent=footer,
        )
        self.cancel_button.setObjectName("free_harmonic_cancel_button")
        self.open_results_button = make_action_button(
            "Open Results Folder",
            variant="secondary",
            parent=footer,
        )
        self.open_results_button.setObjectName("free_harmonic_open_results_button")
        self.protocol_settings_button = make_action_button(
            "Open Protocol Settings", variant="primary", parent=footer,
        )
        self.protocol_settings_button.setObjectName("free_harmonic_protocol_settings_button")
        self.retry_loading_button = make_action_button(
            "Retry loading", variant="secondary", parent=footer,
        )
        self.retry_loading_button.setObjectName("free_harmonic_retry_loading_button")
        action_height = max(
            self.open_results_button.sizeHint().height(),
            self.run_analysis_button.sizeHint().height(),
        )
        self.open_results_button.setFixedHeight(action_height)
        self.run_analysis_button.setFixedHeight(action_height)
        self.workflow_actions = make_action_row(
            (
                self.open_results_button,
                self.protocol_settings_button,
                self.retry_loading_button,
                self.cancel_button,
                self.run_analysis_button,
            ),
            parent=footer,
        )
        self.workflow_actions.setObjectName("free_harmonic_workflow_actions")
        footer_layout.addWidget(self.workflow_actions)
        root_layout.addWidget(footer)

    def _build_results_panel(self) -> None:
        layout = QVBoxLayout(self.results_panel)
        layout.setContentsMargins(24, 0, 24, 16)
        layout.setSpacing(14)
        results_card = SectionCard(
            "Results",
            self.results_panel,
            object_name="free_harmonic_results_card",
        )
        results_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(results_card, 1)
        self.result_status = StatusBanner(
            "No result has been run.",
            results_card.content,
            variant="info",
        )
        self.result_status.setObjectName("free_harmonic_result_status")
        self.result_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        results_card.content_layout.addWidget(self.result_status)
        self.significant_table = self._new_result_table(
            results_card.content,
            "free_harmonic_significant_table",
            (
                "Direction",
                "Electrodes",
                "Harmonics",
                "Cluster mass",
                "Cluster p",
            ),
        )
        self.significant_table.setMinimumHeight(160)
        self.significant_table.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.significant_table.hide()
        results_card.content_layout.addWidget(self.significant_table, 1)
        self.batch_table = self._new_result_table(
            results_card.content,
            "free_harmonic_repeated_batch_table",
            (
                "Analysis family",
                "Comparison",
                "Family Holm p",
                "Interpretation",
            ),
        )
        self.batch_table.setMinimumHeight(220)
        self.batch_table.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.batch_table.hide()
        self.batch_table.horizontalHeaderItem(2).setToolTip(
            "The primary result: Holm correction across every planned comparison in this family."
        )
        self.batch_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.batch_table.setColumnWidth(0, 220)
        self.batch_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.batch_table.horizontalHeader().setStretchLastSection(False)
        self.batch_table.horizontalHeaderItem(2).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        results_card.content_layout.addWidget(self.batch_table, 1)
        self.result_view_label = QLabel("Result view:", results_card.content)
        self.result_view_combo = QComboBox(results_card.content)
        self.result_view_combo.setObjectName("free_harmonic_result_view")
        self.result_view_combo.addItem("All comparisons", "all")
        self.result_view_combo.addItem("Pass family Holm", "confirmed")
        self.result_view_combo.addItem("Exploratory findings", "exploratory")
        self.result_view_combo.setToolTip(
            "Exploratory findings have nominal global p < .05 and family Holm "
            "p > .05. Changing this view does not change the analysis or correction."
        )
        self.result_view_label.setBuddy(self.result_view_combo)
        self.view_details_button = make_action_button(
            "View details", variant="secondary", parent=results_card.content,
        )
        self.view_details_button.setObjectName("free_harmonic_view_details_button")
        self.view_details_button.setToolTip(
            "Read the selected comparison's interpretation, cluster details, and correction status."
        )
        for widget in (
            self.result_view_label, self.result_view_combo, self.view_details_button,
        ):
            widget.hide()
        self.view_maps_button = make_action_button(
            "View cluster maps", variant="secondary", parent=results_card.content,
        )
        self.view_maps_button.setObjectName("free_harmonic_view_maps_button")
        self.view_maps_button.setToolTip(
            "Show harmonic difference maps for the selected cluster or contrast."
        )
        result_actions = make_action_row(
            (self.view_details_button, self.view_maps_button),
            parent=results_card.content,
        )
        result_actions.row_layout.insertWidget(0, self.result_view_label)
        result_actions.row_layout.insertWidget(1, self.result_view_combo)
        result_actions.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # Keep view controls directly above the expanding result viewport.
        results_card.content_layout.insertWidget(1, result_actions)
        # Only absorb spare space when neither result table is visible.
        results_card.content_layout.addStretch(0)
        self.results_panel.hide()

    @staticmethod
    def _new_result_table(
        parent: QWidget,
        object_name: str,
        headers: tuple[str, ...],
    ) -> QTableWidget:
        table = QTableWidget(0, len(headers), parent)
        table.setObjectName(object_name)
        table.setHorizontalHeaderLabels(headers)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        table.setTextElideMode(Qt.ElideRight)
        table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Rows must not be sized against the hidden tab's provisional widths.
        # Full labels remain available through tooltips and result details.
        rows = table.verticalHeader()
        rows.setVisible(False)
        rows.setSectionResizeMode(QHeaderView.Fixed)
        row_height = max(32, table.fontMetrics().height() + 12)
        rows.setMinimumSectionSize(row_height)
        rows.setDefaultSectionSize(row_height)
        header = table.horizontalHeader()
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setStretchLastSection(True)
        for column in range(len(headers)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        return table

    def _connect_signals(self) -> None:
        self.about_button.clicked.connect(
            lambda: show_tool_info(self, FREE_HARMONIC_CLUSTERING_TOOL_INFO)
        )
        self.harmonic_info_button.clicked.connect(
            lambda: show_tool_info(self, HARMONIC_SELECTION_TOOL_INFO)
        )
        self.design_combo.currentIndexChanged.connect(self._on_design_changed)
        self.harmonic_mode_combo.currentIndexChanged.connect(
            self._on_harmonic_mode_changed
        )
        self.paired_condition_a_combo.currentIndexChanged.connect(
            self._on_paired_condition_a_changed
        )
        self.paired_condition_b_combo.currentIndexChanged.connect(
            self._on_paired_condition_b_changed
        )
        for combo in (
            self.paired_group_filter_combo,
            self.independent_condition_combo,
            self.independent_group_a_combo,
            self.independent_group_b_combo,
            self.fixed_highest_combo,
        ):
            combo.currentIndexChanged.connect(self._on_setup_changed)
        self.run_analysis_button.clicked.connect(self._run_analysis)
        self.protocol_settings_button.clicked.connect(
            lambda _checked=False: self.protocol_settings_required.emit()
        )
        self.retry_loading_button.clicked.connect(self._begin_project_inspection)
        self.review_exclusions_button.clicked.connect(
            self._review_recording_exclusions
        )
        self.cancel_button.clicked.connect(self.cancel_active_work)
        self.open_results_button.clicked.connect(self._open_results_folder)
        self.view_maps_button.clicked.connect(self._open_cluster_maps)
        self.significant_table.cellDoubleClicked.connect(self._open_cluster_maps)
        self.batch_table.cellDoubleClicked.connect(self._open_cluster_maps)
        self.result_view_combo.currentIndexChanged.connect(self._refresh_batch_table)
        self.batch_table.itemSelectionChanged.connect(self._update_result_actions)
        self.view_details_button.clicked.connect(self._open_result_details)
        for check in self.family_checks.values():
            check.toggled.connect(self._on_plan_choices_changed)
        self.condition_mode_combo.currentIndexChanged.connect(self._on_plan_choices_changed)
        self.reference_condition_combo.currentIndexChanged.connect(self._on_plan_choices_changed)
        self.review_comparisons_button.clicked.connect(self._review_analysis_plan)

    # ---------------------------------------------------------- project state
    def refresh_project_context(
        self,
        project_root: str | Path | None = None,
        frequency_snapshot: ProjectFrequencySnapshot | Mapping[str, object] | None | object = _FREQUENCY_UNSET,
        frequency_error: str | None = None,
    ) -> bool:
        """Refresh changed project/frequency inputs; identical context is a no-op."""

        if self._retired:
            return False
        root = (
            self._project_root
            if project_root is None
            else Path(project_root).expanduser().resolve(strict=False)
        )
        snapshot = self._frequency_snapshot
        resolved_error: str | None = None
        if frequency_snapshot is _FREQUENCY_UNSET:
            resolved_error = frequency_error or self._frequency_error
        elif frequency_snapshot is None:
            snapshot = None
            resolved_error = frequency_error or "Confirm this project's protocol in Settings > Protocol before loading FHC."
        else:
            try:
                snapshot = ProjectFrequencySnapshot.coerce(frequency_snapshot)
            except (TypeError, ValueError, OverflowError) as exc:
                snapshot = None
                resolved_error = frequency_error or str(exc)

        if (
            root == self._project_root
            and snapshot == self._frequency_snapshot
            and resolved_error == self._frequency_error
        ):
            if self._inspection_failed and self._thread is None:
                self._begin_project_inspection()
                return True
            return False

        context = (root, snapshot, resolved_error)
        if self._thread is not None:
            self._pending_context = context
            self.cancel_active_work()
            return True
        self._apply_new_context(*context)
        return True

    def refresh_inputs(
        self,
        project_root: str | Path | None = None,
        frequency_snapshot: ProjectFrequencySnapshot | Mapping[str, object] | None | object = _FREQUENCY_UNSET,
    ) -> bool:
        """Compatibility alias used by embedded-tool integration."""

        return self.refresh_project_context(project_root, frequency_snapshot)

    def _apply_new_context(
        self,
        root: Path,
        snapshot: ProjectFrequencySnapshot | None,
        frequency_error: str | None,
    ) -> None:
        self._project_root = root
        self._frequency_snapshot = snapshot
        self._frequency_error = frequency_error
        self._options = None
        self._analysis_plan_state_error = ""
        self._recording_exclusion_state_error = ""
        self._recording_exclusions = ()
        self._inspection_failed = False
        self._pending_post_processing_reason = None
        self._clear_results()
        self._clear_choice_controls()
        self._set_unavailable_plan("Preparing to load project design...")
        self._update_results_folder_button()
        self._begin_project_inspection()

    def _begin_project_inspection(self) -> None:
        if self._retired or self._thread is not None:
            return
        if self._frequency_snapshot is None:
            self._show_frequency_or_ready_status()
            self._update_buttons()
            return
        self._inspection_failed = False
        self._set_unavailable_plan("Loading project design...")
        worker = ProjectInspectionWorker(
            self._backend,
            self._project_root,
            self._frequency_snapshot,
        )
        self._start_operation(
            worker,
            stage="inspection",
            message="Loading canonical project choices and FullFFT availability...",
            on_completed=self._on_inspection_completed,
        )

    def _on_inspection_completed(self, value: object) -> None:
        if not isinstance(value, ProjectAnalysisOptions):
            self._show_error("Project inspection returned an invalid result.")
            return
        if value.project_root != self._project_root:
            self._show_error("Project inspection returned a different project root.")
            return
        self._options = value
        self._inspection_failed = False
        self._load_recording_exclusions(value)
        self._populate_choice_controls(value)
        self._populate_analysis_plan(value)
        if not value.grid_compatible:
            self.workflow_status.set_variant("error")
            self.workflow_status.set_text(value.compatibility_message)
        elif value.is_repeated_session and len(value.sessions) != 2:
            self.workflow_status.set_variant("error")
            self.workflow_status.set_text(
                "Repeated-session analysis requires two ordered visits."
            )
        elif self._analysis_plan_state_error:
            self._show_error(self._analysis_plan_state_error)
        elif self._recording_exclusion_state_error:
            self._show_error(self._recording_exclusion_state_error)
        else:
            self.workflow_status.hide()
        self._update_buttons()

    def _populate_choice_controls(self, options: ProjectAnalysisOptions) -> None:
        self._updating_controls = True
        try:
            self._clear_choice_controls()
            self._configure_design_choices(options)
            for condition in options.conditions:
                self.paired_condition_a_combo.addItem(condition, condition)
                self.paired_condition_b_combo.addItem(condition, condition)
                self.independent_condition_combo.addItem(condition, condition)
            if self.paired_condition_b_combo.count() > 1:
                self.paired_condition_b_combo.setCurrentIndex(1)
            self.paired_group_filter_combo.addItem(
                "All eligible participants",
                None,
            )
            for group in options.groups:
                label = f"{group.label} ({group.group_id})"
                self.paired_group_filter_combo.addItem(label, group.group_id)
                self.independent_group_a_combo.addItem(label, group.group_id)
                self.independent_group_b_combo.addItem(label, group.group_id)
            if self.independent_group_b_combo.count() > 1:
                self.independent_group_b_combo.setCurrentIndex(1)
            for order, frequency in zip(
                options.eligible_orders,
                options.eligible_harmonics_hz,
                strict=True,
            ):
                self.fixed_highest_combo.addItem(
                    f"H{order} ({_frequency_text(frequency)})",
                    order,
                )
            if self.fixed_highest_combo.count():
                self.fixed_highest_combo.setCurrentIndex(
                    self.fixed_highest_combo.count() - 1
                )
            self._populate_repeated_session_summary(options)
        finally:
            self._updating_controls = False
        self._on_design_changed()
        self._on_harmonic_mode_changed()

    def _configure_design_choices(self, options: ProjectAnalysisOptions) -> None:
        blocked = self.design_combo.blockSignals(True)
        try:
            self.design_combo.clear()
            if options.is_repeated_session:
                self.design_combo.addItem(
                    "Full Repeated-Session Batch",
                    GuiAnalysisDesign.REPEATED_SESSION_BATCH.value,
                )
            else:
                self.design_combo.addItem(
                    "Paired Conditions",
                    GuiAnalysisDesign.PAIRED_CONDITIONS.value,
                )
                self.design_combo.addItem(
                    "Independent Groups",
                    GuiAnalysisDesign.INDEPENDENT_GROUPS.value,
                )
        finally:
            self.design_combo.blockSignals(blocked)

    def _populate_repeated_session_summary(
        self,
        options: ProjectAnalysisOptions,
    ) -> None:
        if not options.is_repeated_session:
            self.repeated_groups_value.setText("Not a repeated-session project.")
            self._update_exclusion_count_label()
            return
        self.repeated_groups_value.setText(
            " vs ".join(f"{group.label} [{group.group_id}]" for group in options.groups)
        )
        self._update_exclusion_count_label()

    def _clear_choice_controls(self) -> None:
        was_updating = self._updating_controls
        self._updating_controls = True
        try:
            for combo in (
                self.paired_condition_a_combo,
                self.paired_condition_b_combo,
                self.paired_group_filter_combo,
                self.independent_condition_combo,
                self.independent_group_a_combo,
                self.independent_group_b_combo,
                self.fixed_highest_combo,
            ):
                combo.clear()
        finally:
            self._updating_controls = was_updating

    def _update_exclusion_count_label(self) -> None:
        count = len(self._recording_exclusions)
        self.exclusion_count_label.setText(
            "No analysis-specific exclusions."
            if count == 0
            else f"{count} recording exclusion(s), with audit reasons."
        )

    def _populate_analysis_plan(self, options: ProjectAnalysisOptions) -> None:
        """Offer only scientific questions supported by the inspected design."""

        self._updating_controls = True
        try:
            self.review_comparisons_button.show()
            self.plan_exclusion_row.show()
            self.review_exclusions_button.show()
            self.exclusion_count_label.show()
            self.family_correction_note.show()
            self.reference_condition_combo.clear()
            for condition in options.conditions:
                self.reference_condition_combo.addItem(condition, condition)
            between = len(options.groups) >= 2
            repeated = options.is_repeated_session and len(options.sessions) == 2
            applicable = {
                AnalysisFamily.BETWEEN_GROUPS: between,
                AnalysisFamily.BETWEEN_CONDITIONS: len(options.conditions) >= 2,
                AnalysisFamily.WITHIN_GROUP_VISITS: repeated,
                AnalysisFamily.GROUP_VISIT_CHANGE: between and repeated,
            }
            defaults = {family for family, available in applicable.items() if available and family is not AnalysisFamily.BETWEEN_CONDITIONS}
            if not defaults and applicable[AnalysisFamily.BETWEEN_CONDITIONS]:
                defaults.add(AnalysisFamily.BETWEEN_CONDITIONS)
            saved = None
            self._analysis_plan_state_error = ""
            try:
                saved = load_analysis_plan_preferences(self._results_parent())
                if saved and any(not applicable[AnalysisFamily(value)] for value in saved.families):
                    raise AnalysisPlanStateError("Saved families no longer match this project. Review and choose the analysis families again.")
                if saved and saved.condition_mode == "reference" and AnalysisFamily.BETWEEN_CONDITIONS.value in saved.families and saved.reference_condition not in options.conditions:
                    raise AnalysisPlanStateError("The saved reference condition is unavailable. Choose the reference condition again.")
            except AnalysisPlanStateError as exc:
                self._analysis_plan_state_error = str(exc)
                saved = None
            selected = defaults if saved is None else {AnalysisFamily(value) for value in saved.families}
            for family, check in self.family_checks.items():
                check.setVisible(applicable[family])
                check.setChecked(family in selected)
            default_all_pairs = not between and not repeated
            self.condition_mode_combo.setCurrentIndex(
                (1 if default_all_pairs else 0) if saved is None
                else (0 if saved.condition_mode == "reference" else 1)
            )
            if saved is not None:
                index = self.reference_condition_combo.findData(saved.reference_condition)
                if index >= 0:
                    self.reference_condition_combo.setCurrentIndex(index)
            group_text = ", ".join(group.label for group in options.groups) or "All participants"
            visits = ""
            if repeated:
                visits = f" Visit change: {options.sessions[0].label} − {options.sessions[1].label}."
            self.plan_context_label.setText(f"{group_text} · {len(options.conditions)} conditions.{visits}")
            self.family_correction_note.setText(
                "Holm correction applies within each selected family at .05. "
                + ("All groups' visit changes share one family. " if repeated else "")
                + "Exploratory findings remain available in Results."
            )
        finally:
            self._updating_controls = False
        self._update_plan_summary()

    def _plan_preferences(self) -> AnalysisPlanPreferences:
        return AnalysisPlanPreferences(
            families=tuple(family.value for family, check in self.family_checks.items() if check.isChecked()),
            condition_mode=str(self.condition_mode_combo.currentData()),
            reference_condition=str(self.reference_condition_combo.currentData() or ""),
        )

    def _current_analysis_plan(self):
        if self._options is None:
            raise ValueError("Project inputs have not been loaded.")
        from ..models import RecordingExclusionRequest

        options = self._options
        preferences = self._plan_preferences()
        pairs = ()
        if AnalysisFamily.BETWEEN_CONDITIONS.value in preferences.families and preferences.condition_mode == "reference":
            if preferences.reference_condition not in options.conditions:
                raise ValueError("Choose the reference condition.")
            pairs = tuple((condition, preferences.reference_condition) for condition in options.conditions if condition != preferences.reference_condition)
        return build_analysis_plan(
            self._project_root,
            group_ids=tuple(group.group_id for group in options.groups),
            conditions=options.conditions,
            session_ids=tuple(session.session_id for session in options.sessions) if options.is_repeated_session else (),
            families=preferences.families,
            condition_pairs=pairs,
            recording_exclusions=tuple(RecordingExclusionRequest(item.recording_id, item.reason) for item in self._recording_exclusions),
            project_options=options,
        )

    def _current_planned_setup(self) -> PlannedAnalysisSetup:
        if self._analysis_plan_state_error:
            raise ValueError(self._analysis_plan_state_error)
        if self._recording_exclusion_state_error:
            raise ValueError(self._recording_exclusion_state_error)
        harmonic_mode, fixed_order, maximum = self._current_harmonic_domain()
        return PlannedAnalysisSetup(self._current_analysis_plan(), harmonic_mode, fixed_order, maximum)

    @Slot()
    def _on_plan_choices_changed(self) -> None:
        if self._updating_controls:
            return
        self._analysis_plan_state_error = ""
        self._on_setup_changed()

    def _update_plan_summary(self) -> None:
        selected = self.family_checks[AnalysisFamily.BETWEEN_CONDITIONS].isChecked()
        self.condition_plan_row.setVisible(selected)
        reference = selected and self.condition_mode_combo.currentData() == "reference"
        self.reference_condition_combo.setVisible(reference)
        self.reference_condition_label.setVisible(reference)
        if self._options is None:
            return
        try:
            plan = self._current_analysis_plan()
        except (ValueError, FreeHarmonicInputError) as exc:
            self.plan_summary_label.setText(str(exc))
            self.review_comparisons_button.setEnabled(False)
            return
        counts = {}
        for row in plan.comparisons:
            counts[row.family_label] = counts.get(row.family_label, 0) + 1
        self.plan_summary_label.setText(
            f"{len(plan.comparisons)} planned comparisons in {len(counts)} {'family' if len(counts) == 1 else 'families'}:\n"
            + "\n".join(f"{label}: {count}" for label, count in counts.items())
        )
        self.review_comparisons_button.setEnabled(self._thread is None)

    @Slot()
    def _review_analysis_plan(self) -> None:
        try:
            plan = self._current_analysis_plan()
        except (ValueError, FreeHarmonicInputError) as exc:
            self._show_error(str(exc))
            return
        from .analysis_plan_dialog import AnalysisPlanDialog

        dialog = AnalysisPlanDialog(plan, self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    # ------------------------------------------------------------- interaction
    def _selected_design(self) -> GuiAnalysisDesign | None:
        value = self.design_combo.currentData()
        if not isinstance(value, str):
            return None
        try:
            return GuiAnalysisDesign(value)
        except ValueError:
            return None

    def _selected_harmonic_mode(self) -> GuiHarmonicMode | None:
        value = self.harmonic_mode_combo.currentData()
        if not isinstance(value, str):
            return None
        try:
            return GuiHarmonicMode(value)
        except ValueError:
            return None

    @Slot()
    def _on_design_changed(self) -> None:
        design = self._selected_design()
        stack_index = {
            GuiAnalysisDesign.PAIRED_CONDITIONS: 0,
            GuiAnalysisDesign.INDEPENDENT_GROUPS: 1,
            GuiAnalysisDesign.REPEATED_SESSION_BATCH: 2,
        }.get(design, 0)
        self.design_stack.setCurrentIndex(stack_index)
        self.design_stack.updateGeometry()
        self._on_setup_changed()

    @Slot()
    def _on_harmonic_mode_changed(self) -> None:
        fixed = self._selected_harmonic_mode() is GuiHarmonicMode.FIXED_HIGHEST
        self.fixed_highest_label.setVisible(fixed)
        self.fixed_highest_combo.parentWidget().setVisible(fixed)
        self.fixed_highest_combo.setEnabled(
            fixed and self._options is not None and self.fixed_highest_combo.count() > 0
        )
        self._on_setup_changed()

    @Slot()
    def _on_setup_changed(self) -> None:
        if self._updating_controls:
            return
        if self._has_result:
            self._clear_results()
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(
                "Setup changed. Run the analysis again to use the new choices."
            )
        self._update_direction_label()
        self._update_plan_summary()
        self._update_buttons()

    @Slot()
    def _on_paired_condition_a_changed(self) -> None:
        self._keep_paired_conditions_distinct(
            self.paired_condition_a_combo,
            self.paired_condition_b_combo,
        )
        self._on_setup_changed()

    @Slot()
    def _on_paired_condition_b_changed(self) -> None:
        self._keep_paired_conditions_distinct(
            self.paired_condition_b_combo,
            self.paired_condition_a_combo,
        )
        self._on_setup_changed()

    def _keep_paired_conditions_distinct(
        self,
        changed_combo: QComboBox,
        other_combo: QComboBox,
    ) -> None:
        if self._updating_controls:
            return
        selected = changed_combo.currentData()
        other_selected = other_combo.currentData()
        if (
            selected is None
            or other_selected is None
            or str(selected).casefold() != str(other_selected).casefold()
        ):
            return
        selected_key = str(selected).casefold()
        for index in range(other_combo.count()):
            candidate = other_combo.itemData(index)
            if candidate is None or str(candidate).casefold() == selected_key:
                continue
            signals_were_blocked = other_combo.blockSignals(True)
            try:
                other_combo.setCurrentIndex(index)
            finally:
                other_combo.blockSignals(signals_were_blocked)
            return

    def _update_direction_label(self) -> None:
        design = self._selected_design()
        self.direction_label.setVisible(
            design is not GuiAnalysisDesign.REPEATED_SESSION_BATCH
        )
        if design is GuiAnalysisDesign.PAIRED_CONDITIONS:
            arm_a = self.paired_condition_a_combo.currentText() or "Condition A"
            arm_b = self.paired_condition_b_combo.currentText() or "Condition B"
        elif design is GuiAnalysisDesign.REPEATED_SESSION_BATCH:
            return
        else:
            arm_a = self.independent_group_a_combo.currentText() or "Group A"
            arm_b = self.independent_group_b_combo.currentText() or "Group B"
        self.direction_label.setText(
            f"Contrast: {arm_a} - {arm_b}; positive clusters indicate {arm_a} > {arm_b}."
        )

    def _load_recording_exclusions(self, options: ProjectAnalysisOptions) -> None:
        self._recording_exclusion_state_error = ""
        try:
            self._recording_exclusions = load_project_recording_exclusions(
                self._results_parent(),
                tuple(recording.recording_id for recording in options.recordings),
            )
        except ExclusionStateError as exc:
            self._recording_exclusions = ()
            self._recording_exclusion_state_error = "Saved recording exclusions could not be loaded. Review recording exclusions before running this plan."
            logger.warning(
                "fhc_recording_exclusions_load_failed",
                extra={"project_root": str(self._project_root), "error": str(exc)},
            )

    def _current_setup(self) -> AnalysisSetup:
        if self._options is None or self._frequency_snapshot is None:
            raise ValueError("Project inputs have not been loaded.")
        design = self._selected_design()
        if design is None:
            raise ValueError("Choose an analysis mode.")
        if design is GuiAnalysisDesign.PAIRED_CONDITIONS:
            condition_a = str(self.paired_condition_a_combo.currentData() or "")
            condition_b = str(self.paired_condition_b_combo.currentData() or "")
            group_filter = self.paired_group_filter_combo.currentData()
            group_ids = () if group_filter is None else (str(group_filter),)
            if not condition_a or not condition_b or condition_a.casefold() == condition_b.casefold():
                raise ValueError("Paired analysis requires two different conditions.")
        else:
            condition_a = str(self.independent_condition_combo.currentData() or "")
            condition_b = None
            group_a = str(self.independent_group_a_combo.currentData() or "")
            group_b = str(self.independent_group_b_combo.currentData() or "")
            group_ids = (group_a, group_b)
            if not condition_a:
                raise ValueError("Independent-groups analysis requires one condition.")
            if not group_a or not group_b or group_a.casefold() == group_b.casefold():
                raise ValueError("Independent analysis requires two different groups.")

        harmonic_mode, fixed_order, maximum = self._current_harmonic_domain()
        return AnalysisSetup(
            design=design,
            condition_a=condition_a,
            condition_b=condition_b,
            group_ids=group_ids,
            harmonic_mode=harmonic_mode,
            fixed_highest_harmonic_order=fixed_order,
            max_harmonic_hz=maximum,
        )

    def _current_repeated_batch_setup(self) -> RepeatedBatchSetup:
        if self._options is None or self._frequency_snapshot is None:
            raise ValueError("Project inputs have not been loaded.")
        if not self._options.is_repeated_session:
            raise ValueError("The active project is not a repeated-session project.")
        if len(self._options.groups) != 2 or len(self._options.sessions) != 2:
            raise ValueError(
                "The full repeated-session batch requires exactly two stable "
                "groups and two ordered sessions."
            )
        if not self._options.conditions:
            raise ValueError("The repeated-session project has no conditions.")
        harmonic_mode, fixed_order, maximum = self._current_harmonic_domain()
        known_recordings = {
            recording.recording_id.casefold() for recording in self._options.recordings
        }
        unknown = tuple(
            item.recording_id
            for item in self._recording_exclusions
            if item.recording_id.casefold() not in known_recordings
        )
        if unknown:
            raise ValueError(
                "Analysis exclusions no longer match the project: " + ", ".join(unknown)
            )
        return RepeatedBatchSetup(
            harmonic_mode=harmonic_mode,
            fixed_highest_harmonic_order=fixed_order,
            max_harmonic_hz=maximum,
            recording_exclusions=self._recording_exclusions,
        )

    def _current_harmonic_domain(self) -> tuple[GuiHarmonicMode, int | None, float]:
        harmonic_mode = self._selected_harmonic_mode()
        if harmonic_mode is None:
            raise ValueError("Choose a harmonic-domain mode.")
        fixed_order = None
        if harmonic_mode is GuiHarmonicMode.FIXED_HIGHEST:
            value = self.fixed_highest_combo.currentData()
            if value is None:
                raise ValueError("Choose the highest included harmonic.")
            fixed_order = int(value)
        maximum = self._frequency_snapshot.max_harmonic_hz
        if maximum is None:
            maximum = self._options.effective_harmonic_upper_hz
        if maximum is None and self._options.eligible_harmonics_hz:
            maximum = self._options.eligible_harmonics_hz[-1]
        if maximum is None:
            raise ValueError("No eligible harmonics are available on the FullFFT grid.")
        return harmonic_mode, fixed_order, float(maximum)

    def _setup_error(self) -> str | None:
        if self._retired:
            return "This project-bound page has been retired."
        if self._frequency_snapshot is None:
            return self._frequency_error or "Confirm the project protocol in Settings > Protocol."
        if self._options is None:
            return "Project inputs could not be loaded. Retry loading after resolving the issue." if self._inspection_failed else "Project inputs are still loading."
        if not self._options.grid_compatible:
            return self._options.compatibility_message or "FullFFT grid is incompatible."
        if not self._options.eligible_orders:
            return "No eligible non-base oddball harmonics are available on the FullFFT grid."
        try:
            self._current_planned_setup()
        except (ValueError, FreeHarmonicInputError) as exc:
            return str(exc)
        return None

    @Slot()
    def _run_analysis(self) -> None:
        error = self._setup_error()
        if error:
            self._show_error(error)
            return
        assert self._options is not None
        assert self._frequency_snapshot is not None
        setup = self._current_planned_setup()
        try:
            save_analysis_plan_preferences(self._results_parent(), self._plan_preferences())
        except AnalysisPlanStateError as exc:
            self._show_error(str(exc))
            return
        self._clear_results()
        worker = PlannedAnalysisWorker(self._backend, self._frequency_snapshot, setup)
        self._start_operation(
            worker, stage="analysis_plan",
            message="Checking eligible participants for the frozen analysis plan...",
            on_completed=self._on_planned_analysis_completed,
        )

    def _run_legacy_analysis(self) -> None:
        """Retained v1 route for historical integration callers."""

        if self._selected_design() is GuiAnalysisDesign.REPEATED_SESSION_BATCH:
            setup = self._current_repeated_batch_setup()
            self._clear_results()
            worker = RepeatedSessionBatchWorker(
                self._backend,
                self._project_root,
                self._frequency_snapshot,
                self._options,
                setup,
            )
            self._start_operation(
                worker,
                stage="repeated_session_batch",
                message=(
                    "Preparing the shared participant x electrode x harmonic "
                    "domain for all repeated-session contrasts..."
                ),
                on_completed=self._on_repeated_batch_completed,
            )
            return
        setup = self._current_setup()
        self._clear_results()
        worker = AnalysisWorker(
            self._backend,
            self._project_root,
            self._frequency_snapshot,
            self._options,
            setup,
        )
        self._start_operation(
            worker,
            stage="analysis",
            message="Preparing participant x electrode x harmonic data...",
            on_completed=self._on_analysis_completed,
        )

    def _on_planned_analysis_completed(self, value: object) -> None:
        if not isinstance(value, PlannedAnalysisWorkerOutcome):
            self._show_error("The family analysis returned an invalid result.")
            return
        from ..planned_reporting import build_analysis_plan_report

        self._populate_family_report(build_analysis_plan_report(value.run.result))
        self._set_cluster_maps(value.maps)
        self._show_completed_results(value.map_warning)

    def _on_analysis_completed(self, value: object) -> None:
        if not isinstance(value, AnalysisWorkerOutcome) or not isinstance(
            value.run_outcome,
            RunOutcome,
        ):
            self._show_error("Analysis returned an invalid result.")
            return
        self._populate_results(value.prepared, value.run_outcome)
        self._set_cluster_maps(value.maps)
        self._show_completed_results(value.map_warning)

    def _on_repeated_batch_completed(self, value: object) -> None:
        if not isinstance(value, RepeatedBatchWorkerOutcome):
            self._show_error("Repeated-session batch returned an invalid result.")
            return
        self._populate_repeated_batch_results(value.run)
        self._set_cluster_maps(value.maps)
        self._show_completed_results(value.map_warning)

    def _set_cluster_maps(self, maps: tuple[ClusterMapData, ...]) -> None:
        """Keep only compact descriptive maps after the worker releases tensors."""

        if maps:
            if self.map_view is None:
                from .cluster_map_view import ClusterMapView

                self.map_view = ClusterMapView(self.map_panel)
                self.map_layout.addWidget(self.map_view)
            self.map_view.set_maps(maps)
        elif self.map_view is not None:
            self.map_view.clear()
        self.result_tabs.setTabEnabled(2, bool(maps))
        self._update_result_actions()

    @Slot()
    def _open_cluster_maps(self, *_args: object) -> None:
        if self.map_view is None or not self.result_tabs.isTabEnabled(2):
            return
        if not self.batch_table.isHidden():
            row = self._selected_report_row()
            if row is None:
                return
            self.map_view.select_run(row.run_index)
        else:
            item = self.significant_table.item(self.significant_table.currentRow(), 0)
            if item is not None:
                cluster_id = item.data(Qt.UserRole)
                if cluster_id is not None:
                    self.map_view.select_cluster(int(cluster_id))
        self.result_tabs.setCurrentIndex(2)

    def _selected_report_row(self) -> RepeatedSessionReportRow | None:
        item = self.batch_table.item(self.batch_table.currentRow(), 0)
        if item is None:
            return None
        run_index = item.data(Qt.UserRole)
        return next(
            (row for row in self._batch_report_rows if row.run_index == run_index),
            None,
        )

    @Slot()
    def _update_result_actions(self) -> None:
        has_selection = self._selected_report_row() is not None
        self.view_details_button.setEnabled(has_selection)
        self.view_maps_button.setEnabled(
            self.result_tabs.isTabEnabled(2)
            and (self.batch_table.isHidden() or has_selection)
        )

    @Slot()
    def _open_result_details(self) -> None:
        row = self._selected_report_row()
        if row is None:
            return
        from .result_details_dialog import ResultDetailsDialog

        dialog = ResultDetailsDialog(
            row,
            self,
            maps_available=self.result_tabs.isTabEnabled(2),
        )
        dialog.maps_requested.connect(self._open_repeated_result_map)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    @Slot(int)
    def _open_repeated_result_map(self, run_index: int) -> None:
        if (
            self.map_view is not None
            and self.result_tabs.isTabEnabled(2)
            and any(row.run_index == run_index for row in self._batch_report_rows)
        ):
            self.map_view.select_run(run_index)
            self.result_tabs.setCurrentIndex(2)

    def _show_completed_results(self, map_warning: str = "") -> None:
        """Reveal display-only results without retaining worker analysis arrays."""

        self._has_result = True
        self.results_panel.show()
        self.result_tabs.setTabEnabled(1, True)
        self.result_tabs.setCurrentIndex(1)
        self._update_results_folder_button()
        self.workflow_status.hide()
        if map_warning:
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(map_warning)
            self.workflow_status.show()
        self._update_buttons()

    @Slot()
    def _review_recording_exclusions(self) -> None:
        options = self._options
        if (
            options is None
            or self._thread is not None
        ):
            return
        if not options.recordings:
            self._show_error(
                "No canonical recording identities are available for exclusion review."
            )
            return
        dialog = RecordingExclusionsDialog(
            options.recordings,
            self._recording_exclusions,
            self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        exclusions = dialog.exclusions()
        if exclusions == self._recording_exclusions and not self._recording_exclusion_state_error:
            return
        self._recording_exclusions = exclusions
        self._recording_exclusion_state_error = ""
        self._update_exclusion_count_label()
        self._on_setup_changed()
        try:
            save_project_recording_exclusions(
                self._results_parent(),
                self._recording_exclusions,
            )
        except ExclusionStateError as exc:
            logger.exception(
                "fhc_recording_exclusions_save_failed",
                extra={"project_root": str(self._project_root)},
            )
            self._show_error(
                "The exclusions are active for this session but could not be saved "
                f"for the project. {exc}"
            )
        else:
            self._update_results_folder_button()

    # -------------------------------------------------------------- workers
    def _start_operation(
        self,
        worker: object,
        *,
        stage: str,
        message: str,
        on_completed: Callable[[object], None],
    ) -> None:
        if self._thread is not None or self._retired:
            return
        thread = QThread()
        thread.setObjectName(f"free_harmonic_{stage}_thread")
        worker.moveToThread(thread)  # type: ignore[attr-defined]
        thread.started.connect(worker.run)  # type: ignore[attr-defined]
        worker.progress.connect(self._on_operation_progress)  # type: ignore[attr-defined]
        worker.completed.connect(self._on_operation_completed)  # type: ignore[attr-defined]
        worker.failed.connect(self._on_operation_failed)  # type: ignore[attr-defined]
        worker.post_processing_required.connect(  # type: ignore[attr-defined]
            self._on_post_processing_required
        )
        worker.cancelled.connect(self._on_operation_cancelled)  # type: ignore[attr-defined]
        worker.finished.connect(thread.quit)  # type: ignore[attr-defined]
        worker.finished.connect(worker.deleteLater)  # type: ignore[attr-defined]
        thread.finished.connect(self._on_operation_thread_finished)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda thread=thread: release_active_operation(thread)
        )
        register_active_operation(thread, worker)
        self._thread = thread
        self._worker = worker
        self._completion_callback = on_completed
        self._active_stage = stage
        self._pending_post_processing_reason = None
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
        self.workflow_status.show()
        self.workflow_status.set_variant("info")
        self.workflow_status.set_text(message)
        self._update_buttons()
        thread.start()

    @Slot(int, int, str)
    def _on_operation_progress(self, completed: int, total: int, message: str) -> None:
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(max(0, min(completed, total)))
        else:
            self.progress_bar.setRange(0, 0)
        if message:
            self.workflow_status.set_text(message)

    @Slot(object)
    def _on_operation_completed(self, value: object) -> None:
        callback = self._completion_callback
        if callback is not None and not self._retired:
            callback(value)

    @Slot(str)
    def _on_operation_failed(self, message: str) -> None:
        if not self._retired:
            if self._active_stage == "inspection":
                self._inspection_failed = True
                self._options = None
                self._set_unavailable_plan("Project inputs could not be loaded.")
            self._show_error(message or "The analysis operation failed.")

    @Slot(str)
    def _on_post_processing_required(self, reason: str) -> None:
        if self._retired:
            return
        self._inspection_failed = True
        self._options = None
        self._clear_results()
        self._clear_choice_controls()
        self._set_unavailable_plan("Post-processing is required before loading analysis families.")
        self._pending_post_processing_reason = str(reason)
        self.workflow_status.hide()
        logger.warning(
            "free_harmonic_post_processing_rebuild_requested",
            extra={
                "project_root": str(self._project_root),
                "reason": str(reason),
            },
        )

    @Slot()
    def _on_operation_cancelled(self) -> None:
        if not self._retired:
            if self._active_stage == "inspection":
                self._inspection_failed = True
                self._options = None
                self._set_unavailable_plan("Project input loading was cancelled.")
            self.workflow_status.show()
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(
                "Operation cancelled. No completed result bundle was created."
            )

    @Slot()
    def _on_operation_thread_finished(self) -> None:
        finished_stage = self._active_stage or "unknown"
        post_processing_reason = self._pending_post_processing_reason
        self._pending_post_processing_reason = None
        logger.info(
            "free_harmonic_gui_operation_thread_finished",
            extra={
                "stage": finished_stage,
                "project_root": str(self._project_root),
            },
        )
        self._thread = None
        self._worker = None
        self._completion_callback = None
        self._active_stage = None
        if self._retired:
            self.progress_bar.hide()
            return
        if self._pending_context is not None:
            self.progress_bar.hide()
            context = self._pending_context
            self._pending_context = None
            self._apply_new_context(*context)
            return
        if post_processing_reason:
            self.progress_bar.hide()
            self._update_buttons()
            self.post_processing_required.emit(
                "Free Harmonic Clustering Analysis",
                post_processing_reason,
                str(self._project_root),
            )
            return
        self.progress_bar.hide()
        self._update_buttons()

    @Slot()
    def cancel_active_work(self) -> None:
        """Request cancellation without blocking the GUI thread."""

        worker = self._worker
        if worker is not None and hasattr(worker, "cancel"):
            worker.cancel()
            if not self._retired:
                self.workflow_status.set_variant("warning")
                self.workflow_status.set_text("Cancellation requested...")
                self.cancel_button.setEnabled(False)

    def shutdown(self) -> None:
        """Retire the page and let a cancelling worker finish safely."""

        if self._retired:
            return
        self._retired = True
        self._pending_context = None
        self._pending_post_processing_reason = None
        self.cancel_active_work()
        self.setEnabled(False)

    def closeEvent(self, event: Any) -> None:  # noqa: N802, ANN401
        self.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ summaries
    def _populate_results(self, prepared: object, outcome: RunOutcome) -> None:
        self._batch_report_rows = ()
        self._batch_summary_text = ""
        self.result_view_combo.setCurrentIndex(0)
        for widget in (
            self.result_view_label, self.result_view_combo, self.view_details_button,
        ):
            widget.hide()
        self.batch_table.hide()
        self.batch_table.setRowCount(0)
        result = outcome.result
        clusters = self._sorted_clusters(result)
        significant = tuple(
            cluster
            for cluster in clusters
            if bool(getattr(cluster, "significant", False))
        )
        unstable = any(
            bool(getattr(cluster, "confidence_interval_straddles_alpha", False))
            for cluster in clusters
        )
        caution = (
            " At least one result is close to the decision threshold; "
            "interpret it cautiously."
            if unstable
            else ""
        )
        if significant:
            self.result_status.set_variant("warning" if unstable else "success")
            cluster_word = "cluster" if len(significant) == 1 else "clusters"
            self.result_status.set_text(
                f"{len(significant)} significant {cluster_word} found." + caution
            )
            self.significant_table.show()
            self._fill_significant_table(prepared, significant)
        else:
            self.significant_table.hide()
            self.significant_table.setRowCount(0)
            self.result_status.set_variant("warning" if unstable else "info")
            self.result_status.set_text(
                "No significant clusters were found." + caution
            )

    def _populate_repeated_batch_results(self, run: object) -> None:
        from ..reporting import build_repeated_session_report

        self.significant_table.hide()
        self.significant_table.setRowCount(0)
        report = build_repeated_session_report(getattr(run, "result", run))
        self._populate_family_report(report)

    def _populate_family_report(self, report: object) -> None:
        self.significant_table.hide()
        self.significant_table.setRowCount(0)
        self._batch_report_rows = report.rows
        within_family_significant = sum(row.holm_family_p <= 0.05 for row in report.rows)
        self._batch_summary_text = (
            f"{len(report.rows)} comparisons: {within_family_significant} pass family Holm. "
            f"{report.exploratory_count} exploratory "
            f"{'finding' if report.exploratory_count == 1 else 'findings'} "
            "(nominal global p < .05, family Holm p > .05)."
        )
        self.result_status.set_variant("success" if within_family_significant else "info")
        self.result_view_combo.setCurrentIndex(0)
        for widget in (
            self.result_view_label, self.result_view_combo, self.view_details_button,
        ):
            widget.show()
        self.batch_table.show()
        self._refresh_batch_table()

    @Slot()
    def _refresh_batch_table(self) -> None:
        """Filter completed display rows without retaining or rerunning inference."""

        previous = self._selected_report_row()
        exploratory = self.result_view_combo.currentData() == "exploratory"
        confirmed = self.result_view_combo.currentData() == "confirmed"
        rows = tuple(
            row for row in self._batch_report_rows
            if (not exploratory or row.is_exploratory) and (not confirmed or row.holm_family_p <= 0.05)
        )
        self.batch_table.setRowCount(0)
        self.batch_table.setRowCount(len(rows))
        selected_row = 0
        for row_index, row in enumerate(rows):
            values = (
                row.family_label,
                row.comparison_label or row.condition,
                f"{row.holm_family_p:.4f}",
                "Passes family Holm" if row.holm_family_p <= 0.05 else "Exploratory" if row.is_exploratory else "Does not pass",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.run_index)
                item.setToolTip(value)
                if column == 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    item.setToolTip(f"Stored family Holm p = {row.holm_family_p:.8g}; classification uses the unrounded value. Global and full-plan p values are in View details.")
                self.batch_table.setItem(row_index, column, item)
            if previous is not None and row.run_index == previous.run_index:
                selected_row = row_index
        if rows:
            self.batch_table.selectRow(selected_row)
        empty_note = (
            " No comparisons match this view."
            if not rows
            else ""
        )
        self.result_status.set_text(self._batch_summary_text + empty_note)
        self._update_result_actions()

    @staticmethod
    def _sorted_clusters(result: object) -> tuple[object, ...]:
        clusters = tuple(getattr(result, "clusters", ()))
        return tuple(
            sorted(
                clusters,
                key=lambda cluster: (
                    not bool(getattr(cluster, "significant", False)),
                    float(getattr(cluster, "p_value", 1.0)),
                    -abs(float(getattr(cluster, "mass", 0.0))),
                ),
            )
        )

    def _cluster_display(self, prepared: object, cluster: object) -> dict[str, str]:
        sensor_names = tuple(getattr(prepared, "sensor_names", ()))
        orders = tuple(int(value) for value in getattr(prepared, "harmonic_orders", ()))
        frequencies = tuple(float(value) for value in getattr(prepared, "harmonics_hz", ()))
        sensor_indices = tuple(dict.fromkeys(int(value) for value in getattr(cluster, "sensor_indices", ())))
        harmonic_indices = tuple(dict.fromkeys(int(value) for value in getattr(cluster, "harmonic_indices", ())))
        sensors = ", ".join(sensor_names[index] for index in sensor_indices)
        harmonics = ", ".join(
            f"H{orders[index]} ({_frequency_text(frequencies[index])})"
            for index in harmonic_indices
        )
        sign = str(getattr(cluster, "sign", ""))
        arm_a = str(getattr(prepared, "arm_a_label", "A"))
        arm_b = str(getattr(prepared, "arm_b_label", "B"))
        direction = f"{arm_a} > {arm_b}" if sign == "positive" else f"{arm_b} > {arm_a}"
        return {
            "direction": direction,
            "sensors": sensors,
            "harmonics": harmonics,
            "mass": f"{float(getattr(cluster, 'mass', 0.0)):.4f}",
            "raw_p": f"{float(getattr(cluster, 'p_value', 1.0)):.4f}",
        }

    def _fill_significant_table(
        self,
        prepared: object,
        clusters: tuple[object, ...],
    ) -> None:
        self.significant_table.setRowCount(len(clusters))
        for row, cluster in enumerate(clusters):
            display = self._cluster_display(prepared, cluster)
            for column, key in enumerate(("direction", "sensors", "harmonics", "mass", "raw_p")):
                item = QTableWidgetItem(display[key])
                item.setData(Qt.UserRole, getattr(cluster, "cluster_id", None))
                item.setToolTip(display[key])
                self.significant_table.setItem(row, column, item)

    # -------------------------------------------------------------- utilities
    def _reset_session_views(self) -> None:
        self._clear_results()
        self._set_unavailable_plan("Ready to load project design.")
        self.design_stack.setCurrentIndex(0)
        self.fixed_highest_label.hide()
        self.fixed_highest_combo.parentWidget().hide()
        self._update_buttons()

    def _clear_results(self) -> None:
        self._has_result = False
        self._batch_report_rows = ()
        self._batch_summary_text = ""
        self.result_view_combo.setCurrentIndex(0)
        for widget in (
            self.result_view_label, self.result_view_combo, self.view_details_button,
        ):
            widget.hide()
        self.result_tabs.setCurrentIndex(0)
        self.result_tabs.setTabEnabled(1, False)
        self._set_cluster_maps(())
        self.significant_table.setRowCount(0)
        self.significant_table.hide()
        self.batch_table.setRowCount(0)
        self.batch_table.hide()
        self.result_status.set_variant("info")
        self.result_status.set_text("No result has been run.")
        self.results_panel.hide()

    def _show_frequency_or_ready_status(self) -> None:
        self.workflow_status.show()
        if self._frequency_snapshot is None:
            self._set_unavailable_plan("The project protocol needs confirmation before analysis families can load.")
            self.workflow_status.set_variant("error")
            self.workflow_status.set_text(
                self._frequency_error or "Confirm this project's stimulation frequencies, expected cycle count, "
                "and oddball marker in Settings > Protocol, then return to FHC."
            )
        else:
            self._set_unavailable_plan("Ready to load project design.")
            self.workflow_status.set_variant("info")
            self.workflow_status.set_text("Ready to load project inputs.")
        self._update_buttons()

    def _set_unavailable_plan(self, message: str) -> None:
        """Do not display stale choices or a loading claim when inspection stops."""
        self.plan_context_label.setText(message)
        self.plan_summary_label.setText("")
        for check in self.family_checks.values():
            check.hide()
        for widget in (
            self.condition_plan_row, self.review_comparisons_button,
            self.plan_exclusion_row, self.review_exclusions_button,
            self.exclusion_count_label, self.family_correction_note,
        ):
            widget.hide()

    def _show_error(self, message: str) -> None:
        if self._active_stage == "inspection" and self._options is None:
            self._inspection_failed = True
            self._set_unavailable_plan("Project inputs could not be loaded.")
        self.workflow_status.show()
        self.workflow_status.set_variant("error")
        self.workflow_status.set_text(str(message))
        self._update_buttons()

    def _update_buttons(self) -> None:
        busy = self._thread is not None
        error = self._setup_error()
        target = None
        if error and self._options is not None:
            if "different groups" in error:
                target = self.independent_group_b_combo
            elif "different conditions" in error:
                target = self.paired_condition_b_combo
            elif self._selected_harmonic_mode() is GuiHarmonicMode.FIXED_HIGHEST:
                target = self.fixed_highest_combo
        self._setup_issue_target = target
        self.fix_setup_button.setVisible(not busy and target is not None)
        if not busy and error and not self._inspection_failed:
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(error)
            self.workflow_status.setAccessibleDescription(error)
            self.workflow_status.show()
            self._setup_hint_active = True
        elif not busy and not error and getattr(self, "_setup_hint_active", False):
            self.workflow_status.hide()
            self._setup_hint_active = False
        self.run_analysis_button.setEnabled(not busy and error is None)
        self.run_analysis_button.setToolTip(error or "Run the selected comparisons using the frozen family plan.")
        self.run_analysis_button.setVisible(not busy)
        missing_protocol = self._frequency_snapshot is None
        self.protocol_settings_button.setVisible(not busy and missing_protocol)
        self.protocol_settings_button.setEnabled(not busy and not self._retired)
        self.retry_loading_button.setVisible(not busy and self._inspection_failed and not missing_protocol)
        self.retry_loading_button.setEnabled(not busy and not self._retired)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.workflow_actions.setVisible(True)
        repeated_project = bool(
            self._options is not None and self._options.is_repeated_session
        )
        self.design_combo.setEnabled(
            not busy and self._options is not None and not repeated_project
        )
        self.harmonic_mode_combo.setEnabled(not busy and self._options is not None)
        self.design_stack.setEnabled(not busy and self._options is not None)
        self.plan_card.setEnabled(not busy and self._options is not None)
        self.review_exclusions_button.setEnabled(
            not busy
            and self._options is not None
            and bool(self._options.recordings)
        )
        fixed = self._selected_harmonic_mode() is GuiHarmonicMode.FIXED_HIGHEST
        self.fixed_highest_combo.setEnabled(
            not busy and fixed and self._options is not None and self.fixed_highest_combo.count() > 0
        )

    def _focus_setup_issue(self) -> None:
        target = getattr(self, "_setup_issue_target", None)
        if target is not None and target.isEnabled():
            target.setFocus()

    def _results_parent(self) -> Path:
        return self._backend.results_parent(self._project_root)

    def _update_results_folder_button(self) -> None:
        try:
            exists = self._results_parent().is_dir()
        except OSError:
            exists = False
        self.open_results_button.setEnabled(exists)

    @Slot()
    def _open_results_folder(self) -> None:
        parent = self._results_parent()
        if not parent.is_dir():
            self.open_results_button.setEnabled(False)
            self.workflow_status.show()
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(
                "No Free Harmonic Clustering results folder exists yet."
            )
            self.result_status.set_variant("warning")
            self.result_status.set_text(
                "No Free Harmonic Clustering results folder exists yet."
            )
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))


# Kept as a direct GUI-subpackage alias for Main App integration only. The
# headless Tools.Free_Harmonic_Clustering package root does not re-export it.
FreeHarmonicClusteringWindow = FreeHarmonicClusteringPage


__all__ = ["FreeHarmonicClusteringPage", "FreeHarmonicClusteringWindow"]

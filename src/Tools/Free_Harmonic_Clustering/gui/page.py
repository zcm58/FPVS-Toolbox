"""Embedded PySide6 page for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import logging

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
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
from .models import (
    AnalysisSetup,
    GuiAnalysisDesign,
    GuiHarmonicMode,
    ProjectAnalysisOptions,
    ProjectFrequencySnapshot,
    RunOutcome,
)
from .operation_registry import (
    register_active_operation,
    release_active_operation,
)
from .workers import PermutationWorker, PreparationWorker, ProjectInspectionWorker


logger = logging.getLogger(__name__)

_FREQUENCY_UNSET = object()


def _frequency_text(value: float) -> str:
    return f"{float(value):g} Hz"


def _join_or_none(values: object, *, limit: int | None = None) -> str:
    items = tuple(str(value) for value in values or ())
    if limit is not None and len(items) > limit:
        visible = ", ".join(items[:limit])
        return f"{visible}, ... (+{len(items) - limit} more)"
    return ", ".join(items) if items else "None"


class FreeHarmonicClusteringPage(QWidget):
    """Project-bound, source-immutable analysis workspace page."""

    def __init__(
        self,
        project_root: str | Path,
        frequency_snapshot: ProjectFrequencySnapshot | Mapping[str, object] | None,
        *,
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
        self._frequency_error: str | None = None
        try:
            if frequency_snapshot is not None:
                self._frequency_snapshot = ProjectFrequencySnapshot.coerce(
                    frequency_snapshot
                )
        except (TypeError, ValueError, OverflowError) as exc:
            self._frequency_error = str(exc)

        self._options: ProjectAnalysisOptions | None = None
        self._prepared: object | None = None
        self._run_outcome: RunOutcome | None = None
        self._thread: QThread | None = None
        self._worker: object | None = None
        self._completion_callback: Callable[[object], None] | None = None
        self._active_stage: str | None = None
        self._pending_context: tuple[Path, ProjectFrequencySnapshot | None, str | None] | None = None
        self._updating_controls = False
        self._retired = False
        self._inspection_failed = False

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
        eyebrow = QLabel("BETA ANALYSIS TOOL", heading_text)
        eyebrow.setProperty("eyebrow", True)
        heading_layout.addWidget(eyebrow)
        title = QLabel("Free Harmonic Clustering Analysis", heading_text)
        title.setProperty("toolTitle", True)
        apply_font_role(title, "tool_title")
        heading_layout.addWidget(title)
        subtitle = QLabel(
            "Compare one ordered two-level contrast while preserving the "
            "electrode x harmonic response structure.",
            heading_text,
        )
        subtitle.setWordWrap(True)
        heading_layout.addWidget(subtitle)
        header_layout.addWidget(heading_text, 1)
        self.about_button = make_info_button(
            parent=header,
            tooltip="About this analysis",
            object_name="free_harmonic_about_button",
            size=22,
        )
        header_layout.addWidget(self.about_button, 0, Qt.AlignTop)
        root_layout.addWidget(header)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("free_harmonic_main_tabs")
        self.setup_tab = QWidget(self.tabs)
        self.setup_tab.setObjectName("free_harmonic_setup_tab")
        self.review_tab = QWidget(self.tabs)
        self.review_tab.setObjectName("free_harmonic_review_tab")
        self.results_tab = QWidget(self.tabs)
        self.results_tab.setObjectName("free_harmonic_results_tab")
        self.tabs.addTab(self.setup_tab, "1. Setup")
        self.tabs.addTab(self.review_tab, "2. Review and Run")
        self.tabs.addTab(self.results_tab, "3. Results")
        self.tabs.setTabEnabled(self.tabs.indexOf(self.review_tab), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.results_tab), False)
        root_layout.addWidget(self.tabs, 1)

        self._build_setup_tab()
        self._build_review_tab()
        self._build_results_tab()
        self._build_workflow_footer(root_layout)

    def _build_setup_tab(self) -> None:
        content = self.setup_tab
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(14)

        setup_card = SectionCard(
            "Analysis setup",
            content,
            object_name="free_harmonic_setup_card",
        )
        layout.addWidget(setup_card, 1)
        form = make_form_layout()
        setup_card.content_layout.addLayout(form)

        self.design_combo = QComboBox(setup_card.content)
        self.design_combo.setObjectName("free_harmonic_design_combo")
        self.design_combo.addItem(
            "Paired Conditions",
            GuiAnalysisDesign.PAIRED_CONDITIONS.value,
        )
        self.design_combo.addItem(
            "Independent Groups",
            GuiAnalysisDesign.INDEPENDENT_GROUPS.value,
        )
        form.addRow("Analysis mode:", self.design_combo)

        self.design_stack = QStackedWidget(setup_card.content)
        self.design_stack.setObjectName("free_harmonic_design_stack")
        self.design_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        form.addRow(self.design_stack)
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

        self.direction_label = QLabel("Contrast: A - B", setup_card.content)
        self.direction_label.setObjectName("free_harmonic_direction_label")
        self.direction_label.setWordWrap(True)
        self.direction_label.setProperty("caption", True)
        form.addRow(self.direction_label)

        self.harmonic_mode_combo = QComboBox(setup_card.content)
        self.harmonic_mode_combo.setObjectName("free_harmonic_mode_combo")
        self.harmonic_mode_combo.addItem(
            "Hermann automatic selection",
            GuiHarmonicMode.AUTOMATIC.value,
        )
        self.harmonic_mode_combo.addItem(
            "Fixed harmonic list",
            GuiHarmonicMode.FIXED_HIGHEST.value,
        )
        form.addRow("Harmonic domain:", self.harmonic_mode_combo)

        fixed_row = QWidget(setup_card.content)
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
        self.fixed_highest_label = QLabel("Highest included harmonic:", setup_card.content)
        form.addRow(self.fixed_highest_label, fixed_row)

    def _build_review_tab(self) -> None:
        layout = QGridLayout(self.review_tab)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(14)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 1)

        cohort_card = SectionCard(
            "Contrast and cohort",
            self.review_tab,
            object_name="free_harmonic_preparation_card",
        )
        layout.addWidget(cohort_card, 0, 0)
        cohort_form = make_form_layout()
        cohort_card.content_layout.addLayout(cohort_form)
        self.review_design_label = QLabel("Not prepared", cohort_card.content)
        self.review_direction_label = QLabel("Not prepared", cohort_card.content)
        self.review_cohort_label = QLabel("Not prepared", cohort_card.content)
        self.review_participants_label = QLabel("Not prepared", cohort_card.content)
        self.review_exclusions_label = QLabel("Not prepared", cohort_card.content)
        cohort_form.addRow("Design:", self.review_design_label)
        cohort_form.addRow("Direction:", self.review_direction_label)
        cohort_form.addRow("Cohort:", self.review_cohort_label)
        cohort_form.addRow("Included IDs:", self.review_participants_label)
        cohort_form.addRow("Excluded/incomplete:", self.review_exclusions_label)

        inputs_card = SectionCard(
            "Harmonics and inputs",
            self.review_tab,
            object_name="free_harmonic_inputs_review_card",
        )
        layout.addWidget(inputs_card, 0, 1)
        inputs_form = make_form_layout()
        inputs_card.content_layout.addLayout(inputs_form)
        self.review_harmonics_label = QLabel("Not prepared", inputs_card.content)
        self.review_selection_audit_label = QLabel("Not prepared", inputs_card.content)
        self.review_source_coverage_label = QLabel("Not prepared", inputs_card.content)
        self.review_shape_label = QLabel("Not prepared", inputs_card.content)
        inputs_form.addRow("Harmonics:", self.review_harmonics_label)
        inputs_form.addRow("Selection audit:", self.review_selection_audit_label)
        inputs_form.addRow("Source coverage:", self.review_source_coverage_label)
        inputs_form.addRow("Data shape:", self.review_shape_label)

        for widget in (
            self.review_design_label,
            self.review_direction_label,
            self.review_cohort_label,
            self.review_participants_label,
            self.review_exclusions_label,
            self.review_harmonics_label,
            self.review_selection_audit_label,
            self.review_source_coverage_label,
            self.review_shape_label,
        ):
            widget.setWordWrap(True)

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
        footer_layout.addWidget(self.workflow_status)
        self.progress_bar = QProgressBar(footer)
        self.progress_bar.setObjectName("free_harmonic_progress_bar")
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        footer_layout.addWidget(self.progress_bar)
        self.prepare_button = make_action_button(
            "Prepare Analysis",
            variant="primary",
            parent=footer,
        )
        self.prepare_button.setObjectName("free_harmonic_prepare_button")
        self.run_button = make_action_button(
            "Run Permutations",
            variant="primary",
            parent=footer,
        )
        self.run_button.setObjectName("free_harmonic_run_button")
        self.cancel_button = make_action_button(
            "Cancel",
            variant="tertiary",
            parent=footer,
        )
        self.cancel_button.setObjectName("free_harmonic_cancel_button")
        self.setup_open_results_button = make_action_button(
            "Open Results Folder",
            variant="secondary",
            parent=footer,
        )
        self.setup_open_results_button.setObjectName(
            "free_harmonic_setup_open_results_button"
        )
        self.workflow_actions = make_action_row(
            (
                self.setup_open_results_button,
                self.cancel_button,
                self.prepare_button,
                self.run_button,
            ),
            parent=footer,
        )
        self.workflow_actions.setObjectName("free_harmonic_workflow_actions")
        footer_layout.addWidget(self.workflow_actions)
        root_layout.addWidget(footer)

    def _build_results_tab(self) -> None:
        layout = QVBoxLayout(self.results_tab)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(14)
        run_summary = QWidget(self.results_tab)
        run_summary.setObjectName("free_harmonic_current_run_card")
        run_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        run_layout = QVBoxLayout(run_summary)
        run_layout.setContentsMargins(0, 0, 0, 0)
        run_layout.setSpacing(6)
        layout.addWidget(run_summary)
        self.result_status = StatusBanner(
            "Results appear after a successful permutation run.",
            run_summary,
            variant="info",
        )
        self.result_status.setObjectName("free_harmonic_result_status")
        run_layout.addWidget(self.result_status)
        summary_row = QHBoxLayout()
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.setSpacing(12)
        self.result_run_summary = QLabel("No current-session result.", run_summary)
        self.result_run_summary.setObjectName("free_harmonic_result_run_summary")
        self.result_run_summary.setWordWrap(True)
        summary_row.addWidget(self.result_run_summary, 1)
        self.open_results_button = make_action_button(
            "Open Results Folder",
            variant="secondary",
            parent=run_summary,
        )
        self.open_results_button.setObjectName("free_harmonic_open_results_button")
        summary_row.addWidget(self.open_results_button, 0, Qt.AlignBottom)
        run_layout.addLayout(summary_row)

        self.results_tabs = QTabWidget(self.results_tab)
        self.results_tabs.setObjectName("free_harmonic_results_tabs")
        self.results_tabs.setDocumentMode(True)
        self.significant_results_tab = QWidget(self.results_tabs)
        self.significant_results_tab.setObjectName(
            "free_harmonic_significant_results_tab"
        )
        self.all_clusters_tab = QWidget(self.results_tabs)
        self.all_clusters_tab.setObjectName("free_harmonic_all_clusters_tab")
        self.results_tabs.addTab(self.significant_results_tab, "Significant")
        self.results_tabs.addTab(self.all_clusters_tab, "All clusters")
        layout.addWidget(self.results_tabs, 1)

        significant_layout = QVBoxLayout(self.significant_results_tab)
        significant_layout.setContentsMargins(0, 12, 0, 0)
        significant_card = SectionCard(
            "Significant Results",
            self.significant_results_tab,
            object_name="free_harmonic_significant_card",
        )
        significant_layout.addWidget(significant_card, 1)
        self.significant_status = StatusBanner(
            "No result has been run.",
            significant_card.content,
            variant="info",
        )
        self.significant_status.setObjectName("free_harmonic_significant_status")
        significant_card.content_layout.addWidget(self.significant_status)
        self.significant_table = self._new_result_table(
            significant_card.content,
            "free_harmonic_significant_table",
            ("Direction", "Electrodes", "Harmonics", "Mass", "Raw tail p"),
        )
        self.significant_table.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.significant_table.hide()
        significant_card.content_layout.addWidget(self.significant_table)

        all_layout = QVBoxLayout(self.all_clusters_tab)
        all_layout.setContentsMargins(0, 12, 0, 0)
        all_card = SectionCard(
            "All clusters",
            self.all_clusters_tab,
            object_name="free_harmonic_all_clusters_card",
        )
        all_layout.addWidget(all_card, 1)
        self.significant_only_check = QCheckBox("Significant only", all_card)
        self.significant_only_check.setObjectName("free_harmonic_significant_only")
        all_card.header.add_action_widget(self.significant_only_check)
        self.all_clusters_table = self._new_result_table(
            all_card.content,
            "free_harmonic_all_clusters_table",
            (
                "Cluster",
                "Direction",
                "Electrodes",
                "Harmonics",
                "Mass",
                "Raw tail p",
                "Doubled p",
                "Monte Carlo interval",
                "Effect size",
                "Significant",
            ),
        )
        self.all_clusters_table.setMinimumHeight(160)
        self.all_clusters_table.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        all_card.content_layout.addWidget(self.all_clusters_table)

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
        table.verticalHeader().setVisible(False)
        header = table.horizontalHeader()
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
        self.prepare_button.clicked.connect(self._prepare_analysis)
        self.run_button.clicked.connect(self._run_permutations)
        self.cancel_button.clicked.connect(self.cancel_active_work)
        self.setup_open_results_button.clicked.connect(self._open_results_folder)
        self.open_results_button.clicked.connect(self._open_results_folder)
        self.significant_only_check.toggled.connect(self._apply_cluster_filter)
        self.tabs.currentChanged.connect(self._update_action_visibility)

    # ---------------------------------------------------------- project state
    def refresh_project_context(
        self,
        project_root: str | Path | None = None,
        frequency_snapshot: ProjectFrequencySnapshot | Mapping[str, object] | None | object = _FREQUENCY_UNSET,
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
        frequency_error: str | None = None
        if frequency_snapshot is _FREQUENCY_UNSET:
            frequency_error = self._frequency_error
        elif frequency_snapshot is None:
            snapshot = None
            frequency_error = "Frequency settings are missing or invalid."
        else:
            try:
                snapshot = ProjectFrequencySnapshot.coerce(frequency_snapshot)
            except (TypeError, ValueError, OverflowError) as exc:
                snapshot = None
                frequency_error = str(exc)

        if (
            root == self._project_root
            and snapshot == self._frequency_snapshot
            and frequency_error == self._frequency_error
        ):
            if self._inspection_failed and self._thread is None:
                self._begin_project_inspection()
                return True
            return False

        context = (root, snapshot, frequency_error)
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
        self._inspection_failed = False
        self._clear_prepared_and_results()
        self._clear_choice_controls()
        self._update_results_folder_button()
        self._begin_project_inspection()

    def _begin_project_inspection(self) -> None:
        if self._retired or self._thread is not None:
            return
        if self._frequency_snapshot is None:
            self._show_frequency_or_ready_status()
            self._update_buttons()
            return
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
        self._populate_choice_controls(value)
        if not value.grid_compatible:
            self.workflow_status.set_variant("error")
            self.workflow_status.set_text(value.compatibility_message)
        elif value.diagnostics:
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(
                "Project inputs loaded with dataset diagnostics. Select Prepare "
                "Analysis, then review Excluded/incomplete in 2. Review and Run "
                "before starting permutations."
            )
        else:
            self.workflow_status.set_variant("info")
            self.workflow_status.set_text(
                "Project inputs loaded. Select Prepare Analysis to verify the "
                "cohort and open 2. Review and Run."
            )
        self._update_buttons()

    def _populate_choice_controls(self, options: ProjectAnalysisOptions) -> None:
        self._updating_controls = True
        try:
            self._clear_choice_controls()
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
        finally:
            self._updating_controls = False
        self._on_design_changed()
        self._on_harmonic_mode_changed()

    def _clear_choice_controls(self) -> None:
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
            self._updating_controls = False

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
        paired = design is GuiAnalysisDesign.PAIRED_CONDITIONS
        self.design_stack.setCurrentIndex(0 if paired else 1)
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
        if self._prepared is not None or self._run_outcome is not None:
            self._clear_prepared_and_results()
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(
                "Setup changed. Prepare the analysis again before running permutations."
            )
        self._update_direction_label()
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
        if design is GuiAnalysisDesign.PAIRED_CONDITIONS:
            arm_a = self.paired_condition_a_combo.currentText() or "Condition A"
            arm_b = self.paired_condition_b_combo.currentText() or "Condition B"
        else:
            arm_a = self.independent_group_a_combo.currentText() or "Group A"
            arm_b = self.independent_group_b_combo.currentText() or "Group B"
        self.direction_label.setText(
            f"Contrast: {arm_a} - {arm_b}; positive clusters indicate {arm_a} > {arm_b}."
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
        return AnalysisSetup(
            design=design,
            condition_a=condition_a,
            condition_b=condition_b,
            group_ids=group_ids,
            harmonic_mode=harmonic_mode,
            fixed_highest_harmonic_order=fixed_order,
            max_harmonic_hz=float(maximum),
        )

    def _setup_error(self) -> str | None:
        if self._retired:
            return "This project-bound page has been retired."
        if self._frequency_snapshot is None:
            return "Open Project Settings and provide valid base and oddball frequencies."
        if self._options is None:
            return "Project inputs are still loading."
        if not self._options.grid_compatible:
            return self._options.compatibility_message or "FullFFT grid is incompatible."
        if not self._options.eligible_orders:
            return "No eligible non-base oddball harmonics are available on the FullFFT grid."
        try:
            self._current_setup()
        except ValueError as exc:
            return str(exc)
        return None

    @Slot()
    def _prepare_analysis(self) -> None:
        error = self._setup_error()
        if error:
            self._show_error(error)
            return
        assert self._options is not None
        assert self._frequency_snapshot is not None
        setup = self._current_setup()
        self._clear_prepared_and_results()
        worker = PreparationWorker(
            self._backend,
            self._project_root,
            self._frequency_snapshot,
            self._options,
            setup,
        )
        self._start_operation(
            worker,
            stage="preparation",
            message="Preparing participant x electrode x harmonic data...",
            on_completed=self._on_preparation_completed,
        )

    def _on_preparation_completed(self, prepared: object) -> None:
        self._prepared = prepared
        self._populate_preparation_review(prepared)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.review_tab), True)
        self.tabs.setCurrentWidget(self.review_tab)
        self.workflow_status.set_variant("success")
        self.workflow_status.set_text(
            "Preparation complete. Review the frozen cohort and harmonics, then "
            "run permutations. Workbooks will not be read again."
        )
        self._update_buttons()

    @Slot()
    def _run_permutations(self) -> None:
        if self._prepared is None:
            self._show_error("Prepare the analysis before running permutations.")
            return
        worker = PermutationWorker(self._backend, self._prepared)
        self._start_operation(
            worker,
            stage="permutations",
            message="Running whole-participant cluster permutations...",
            on_completed=self._on_run_completed,
        )

    def _on_run_completed(self, value: object) -> None:
        if not isinstance(value, RunOutcome):
            self._show_error("Permutation analysis returned an invalid result.")
            return
        self._run_outcome = value
        self._populate_results(value)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.results_tab), True)
        self.tabs.setCurrentWidget(self.results_tab)
        self.results_tabs.setCurrentWidget(self.significant_results_tab)
        self._update_results_folder_button()
        self.workflow_status.set_variant("success")
        self.workflow_status.set_text(
            "Analysis complete. The current-session result and exported workbook "
            "are ready."
        )
        self._update_buttons()

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
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.show()
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
            self._show_error(message or "The analysis operation failed.")

    @Slot()
    def _on_operation_cancelled(self) -> None:
        if not self._retired:
            if self._active_stage == "inspection":
                self._inspection_failed = True
            self.workflow_status.set_variant("warning")
            self.workflow_status.set_text(
                "Operation cancelled. No completed result bundle was created."
            )

    @Slot()
    def _on_operation_thread_finished(self) -> None:
        finished_stage = self._active_stage or "unknown"
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
        self.progress_bar.hide()
        if self._retired:
            return
        if self._pending_context is not None:
            context = self._pending_context
            self._pending_context = None
            self._apply_new_context(*context)
            return
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
        self.cancel_active_work()
        self.setEnabled(False)

    def closeEvent(self, event: Any) -> None:  # noqa: N802, ANN401
        self.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ summaries
    def _populate_preparation_review(self, prepared: object) -> None:
        request = getattr(prepared, "request")
        design_value = str(getattr(getattr(request, "design", ""), "value", getattr(request, "design", "")))
        design = (
            "Paired Conditions"
            if design_value == GuiAnalysisDesign.PAIRED_CONDITIONS.value
            else "Independent Groups"
        )
        arm_a = str(getattr(prepared, "arm_a_label", "A"))
        arm_b = str(getattr(prepared, "arm_b_label", "B"))
        participants_a = tuple(getattr(prepared, "participant_ids_a", ()))
        participants_b = tuple(getattr(prepared, "participant_ids_b", ()))
        sensors = tuple(getattr(prepared, "sensor_names", ()))
        orders = tuple(int(value) for value in getattr(prepared, "harmonic_orders", ()))
        frequencies = tuple(float(value) for value in getattr(prepared, "harmonics_hz", ()))
        provenance = getattr(prepared, "provenance", None)

        self.review_design_label.setText(design)
        self.review_direction_label.setText(
            f"{arm_a} - {arm_b}; positive clusters indicate {arm_a} > {arm_b}."
        )
        if design_value == GuiAnalysisDesign.PAIRED_CONDITIONS.value:
            cohort = f"{len(participants_a)} complete paired participants"
            included = _join_or_none(participants_a, limit=8)
            included_full = _join_or_none(participants_a)
            shape = f"{len(participants_a)} participants x {len(sensors)} electrodes x {len(orders)} harmonics"
        else:
            cohort = f"{arm_a}: n = {len(participants_a)}; {arm_b}: n = {len(participants_b)}"
            included = (
                f"{arm_a}: {_join_or_none(participants_a, limit=6)}\n"
                f"{arm_b}: {_join_or_none(participants_b, limit=6)}"
            )
            included_full = (
                f"{arm_a}: {_join_or_none(participants_a)}\n"
                f"{arm_b}: {_join_or_none(participants_b)}"
            )
            shape = (
                f"{len(participants_a)} + {len(participants_b)} participants; "
                f"{len(sensors)} electrodes x {len(orders)} harmonics per participant"
            )
        self.review_cohort_label.setText(cohort)
        self.review_participants_label.setText(included)
        self.review_participants_label.setToolTip(
            included_full if included_full != included else ""
        )
        exclusions = []
        full_exclusions = []
        for label, field_name in (
            ("ledger", "ledger_excluded_participants"),
            ("manual", "manual_excluded_participants"),
            ("frequency QC", "frequency_qc_excluded_participants"),
            ("incomplete pairs", "incomplete_pair_participants"),
        ):
            values = tuple(getattr(provenance, field_name, ())) if provenance else ()
            if values:
                visible_values = (
                    _join_or_none(values)
                    if len(values) <= 3
                    else f"{len(values)} participants"
                )
                exclusions.append(f"{label}: {visible_values}")
                full_exclusions.append(f"{label}: {_join_or_none(values)}")
        participant_condition_exclusions = (
            tuple(getattr(provenance, "participant_condition_exclusions", ()))
            if provenance
            else ()
        )
        if participant_condition_exclusions:
            records = tuple(
                f"{getattr(record, 'participant_id', '?')} / "
                f"{getattr(record, 'condition', '?')} "
                f"({getattr(record, 'reason', 'excluded')})"
                for record in participant_condition_exclusions
            )
            visible_records = (
                _join_or_none(records)
                if len(records) <= 2
                else f"{len(records)} records"
            )
            exclusions.append(f"participant-condition: {visible_records}")
            full_exclusions.append(
                f"participant-condition: {_join_or_none(records)}"
            )
        self.review_exclusions_label.setText("; ".join(exclusions) or "None")
        full_exclusions_text = "; ".join(full_exclusions) or "None"
        self.review_exclusions_label.setToolTip(
            full_exclusions_text
            if full_exclusions_text != self.review_exclusions_label.text()
            else ""
        )
        harmonic_items = tuple(
            f"H{order} ({_frequency_text(frequency)})"
            for order, frequency in zip(orders, frequencies, strict=True)
        )
        mode = getattr(getattr(prepared, "method", None), "harmonic_selection_mode", "automatic")
        mode_text = str(getattr(mode, "value", mode)).replace("_", " ")
        harmonic_text = f"{_join_or_none(harmonic_items, limit=8)} ({mode_text} domain)"
        full_harmonic_text = f"{_join_or_none(harmonic_items)} ({mode_text} domain)"
        self.review_harmonics_label.setText(harmonic_text)
        self.review_harmonics_label.setToolTip(
            full_harmonic_text if full_harmonic_text != harmonic_text else ""
        )
        selection_audit = self._selection_audit_text(prepared, limit=6)
        full_selection_audit = self._selection_audit_text(prepared)
        self.review_selection_audit_label.setText(selection_audit)
        self.review_selection_audit_label.setToolTip(
            full_selection_audit if full_selection_audit != selection_audit else ""
        )
        workbook_count = int(getattr(provenance, "workbook_count", 0)) if provenance else 0
        source_sheet = str(getattr(provenance, "source_sheet", "FullFFT Amplitude (uV)"))
        selected_columns = int(
            getattr(provenance, "selected_frequency_column_count", 0)
        ) if provenance else 0
        self.review_source_coverage_label.setText(
            f"{workbook_count} managed workbook(s), {source_sheet}; "
            f"{selected_columns} deduplicated frequency columns."
        )
        self.review_shape_label.setText(shape)

    @staticmethod
    def _selection_audit_text(
        prepared: object,
        *,
        limit: int | None = None,
    ) -> str:
        selection = getattr(prepared, "selection", None)
        if selection is None:
            return "Unavailable"
        orders = tuple(int(value) for value in getattr(selection, "candidate_orders", ()))
        arm_a_z = tuple(float(value) for value in getattr(selection, "arm_a_z", ()))
        arm_b_z = tuple(float(value) for value in getattr(selection, "arm_b_z", ()))
        detected_a = tuple(bool(value) for value in getattr(selection, "detected_arm_a", ()))
        detected_b = tuple(bool(value) for value in getattr(selection, "detected_arm_b", ()))

        def detected_text(z_values: tuple[float, ...], flags: tuple[bool, ...]) -> str:
            rows = [
                f"H{order} (z={z_value:.2f})"
                for order, z_value, detected in zip(
                    orders,
                    z_values,
                    flags,
                    strict=False,
                )
                if detected
            ]
            return _join_or_none(rows, limit=limit) if rows else "none"

        method = getattr(prepared, "method", None)
        mode = getattr(method, "harmonic_selection_mode", "automatic")
        mode_value = str(getattr(mode, "value", mode))
        if mode_value == GuiHarmonicMode.FIXED_HIGHEST.value:
            ceiling = getattr(method, "fixed_highest_harmonic_order", None)
            return (
                f"Fixed ceiling H{ceiling}; z values are audit-only. "
                f"Automatic-threshold detections -- A: {detected_text(arm_a_z, detected_a)}; "
                f"B: {detected_text(arm_b_z, detected_b)}."
            )
        threshold = float(getattr(selection, "z_threshold", 3.29))
        highest = getattr(selection, "highest_detected_order", None)
        return (
            f"Strict z > {threshold:g}; A: {detected_text(arm_a_z, detected_a)}; "
            f"B: {detected_text(arm_b_z, detected_b)}; highest detected: H{highest}."
        )

    def _populate_results(self, outcome: RunOutcome) -> None:
        result = outcome.result
        clusters = self._sorted_clusters(result)
        significant = tuple(cluster for cluster in clusters if bool(getattr(cluster, "significant", False)))
        unstable = any(
            bool(getattr(cluster, "confidence_interval_straddles_alpha", False))
            for cluster in clusters
        )
        if significant:
            self.significant_status.set_variant("warning" if unstable else "success")
            self.significant_status.set_text(
                f"{len(significant)} cluster(s) met the Hermann-compatible "
                "per-direction threshold (raw tail p <= .025)."
                + (
                    " At least one Monte Carlo interval crosses .025; the "
                    "decision is unstable and more permutations are recommended."
                    if unstable
                    else ""
                )
            )
            self.significant_table.show()
            self._fill_significant_table(significant)
            self.result_status.set_variant("warning" if unstable else "success")
            self.result_status.set_text(
                "Significant clusters are listed first by ascending raw tail p."
                + (
                    " A Monte Carlo interval crosses the decision threshold; "
                    "more permutations are recommended."
                    if unstable
                    else ""
                )
            )
        else:
            self.significant_status.set_variant("warning" if unstable else "info")
            self.significant_status.set_text(
                "No clusters met the Hermann-compatible cluster-level threshold."
                + (
                    " A Monte Carlo interval crosses .025; the decision is "
                    "unstable and more permutations are recommended."
                    if unstable
                    else ""
                )
            )
            self.significant_table.hide()
            self.significant_table.setRowCount(0)
            self.result_status.set_variant("warning" if unstable else "info")
            self.result_status.set_text(
                "Analysis completed with no significant clusters."
                + (
                    " A Monte Carlo interval crosses the decision threshold; "
                    "more permutations are recommended."
                    if unstable
                    else ""
                )
            )
        self._fill_all_clusters_table(clusters)
        permutations = int(getattr(result, "permutations_evaluated", 0))
        degrees = int(getattr(result, "degrees_of_freedom", 0))
        threshold = float(getattr(result, "cluster_forming_threshold", float("nan")))
        seed = int(getattr(result, "seed", 0))
        output = Path(getattr(outcome.receipt, "output_directory", ""))
        self.result_run_summary.setText(
            f"Permutations: {permutations:,}; df = {degrees}; cluster-forming "
            f"|t| threshold = {threshold:.4g}; seed = {seed}.\n"
            f"Exported run: {output.name or 'completed result bundle'}"
        )
        self.result_run_summary.setToolTip(str(output))

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

    def _cluster_display(self, cluster: object) -> dict[str, str]:
        assert self._prepared is not None
        sensor_names = tuple(getattr(self._prepared, "sensor_names", ()))
        orders = tuple(int(value) for value in getattr(self._prepared, "harmonic_orders", ()))
        frequencies = tuple(float(value) for value in getattr(self._prepared, "harmonics_hz", ()))
        sensor_indices = tuple(dict.fromkeys(int(value) for value in getattr(cluster, "sensor_indices", ())))
        harmonic_indices = tuple(dict.fromkeys(int(value) for value in getattr(cluster, "harmonic_indices", ())))
        sensors = ", ".join(sensor_names[index] for index in sensor_indices)
        harmonics = ", ".join(
            f"H{orders[index]} ({_frequency_text(frequencies[index])})"
            for index in harmonic_indices
        )
        sign = str(getattr(cluster, "sign", ""))
        arm_a = str(getattr(self._prepared, "arm_a_label", "A"))
        arm_b = str(getattr(self._prepared, "arm_b_label", "B"))
        direction = f"{arm_a} > {arm_b}" if sign == "positive" else f"{arm_b} > {arm_a}"
        effect = getattr(cluster, "effect_size", None)
        effect_kind = getattr(cluster, "effect_size_kind", None)
        return {
            "cluster": str(getattr(cluster, "cluster_id", "")),
            "direction": direction,
            "sensors": sensors,
            "harmonics": harmonics,
            "mass": f"{float(getattr(cluster, 'mass', 0.0)):.4f}",
            "raw_p": f"{float(getattr(cluster, 'p_value', 1.0)):.4f}",
            "doubled_p": f"{float(getattr(cluster, 'adjusted_two_sided_p_value', 1.0)):.4f}",
            "interval": (
                f"[{float(getattr(cluster, 'p_ci_low', 0.0)):.4f}, "
                f"{float(getattr(cluster, 'p_ci_high', 1.0)):.4f}]"
            ),
            "effect": "" if effect is None else f"{str(effect_kind or 'effect')} = {float(effect):.3f}",
            "significant": "Yes" if bool(getattr(cluster, "significant", False)) else "No",
        }

    def _fill_significant_table(self, clusters: tuple[object, ...]) -> None:
        self.significant_table.setRowCount(len(clusters))
        for row, cluster in enumerate(clusters):
            display = self._cluster_display(cluster)
            for column, key in enumerate(("direction", "sensors", "harmonics", "mass", "raw_p")):
                self.significant_table.setItem(row, column, QTableWidgetItem(display[key]))

    def _fill_all_clusters_table(self, clusters: tuple[object, ...]) -> None:
        self.all_clusters_table.setRowCount(len(clusters))
        keys = (
            "cluster",
            "direction",
            "sensors",
            "harmonics",
            "mass",
            "raw_p",
            "doubled_p",
            "interval",
            "effect",
            "significant",
        )
        for row, cluster in enumerate(clusters):
            display = self._cluster_display(cluster)
            significant = bool(getattr(cluster, "significant", False))
            for column, key in enumerate(keys):
                item = QTableWidgetItem(display[key])
                item.setData(Qt.UserRole, significant)
                if significant:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                self.all_clusters_table.setItem(row, column, item)
        self._apply_cluster_filter()

    @Slot()
    def _apply_cluster_filter(self) -> None:
        significant_only = self.significant_only_check.isChecked()
        for row in range(self.all_clusters_table.rowCount()):
            item = self.all_clusters_table.item(row, 0)
            significant = bool(item.data(Qt.UserRole)) if item is not None else False
            self.all_clusters_table.setRowHidden(
                row,
                significant_only and not significant,
            )

    # -------------------------------------------------------------- utilities
    def _reset_session_views(self) -> None:
        self._clear_prepared_and_results()
        self.design_stack.setCurrentIndex(0)
        self.fixed_highest_label.hide()
        self.fixed_highest_combo.parentWidget().hide()
        self._update_buttons()

    def _clear_prepared_and_results(self) -> None:
        self._prepared = None
        self._run_outcome = None
        for label in (
            self.review_design_label,
            self.review_direction_label,
            self.review_cohort_label,
            self.review_participants_label,
            self.review_exclusions_label,
            self.review_harmonics_label,
            self.review_selection_audit_label,
            self.review_source_coverage_label,
            self.review_shape_label,
        ):
            label.setText("Not prepared")
            label.setToolTip("")
        self.significant_table.setRowCount(0)
        self.significant_table.hide()
        self.all_clusters_table.setRowCount(0)
        self.significant_only_check.setChecked(False)
        self.result_run_summary.setText("No current-session result.")
        self.result_run_summary.setToolTip("")
        self.result_status.set_variant("info")
        self.result_status.set_text("Results appear after a successful permutation run.")
        self.significant_status.set_variant("info")
        self.significant_status.set_text("No result has been run.")
        self.tabs.setTabEnabled(self.tabs.indexOf(self.review_tab), False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.results_tab), False)
        self.results_tabs.setCurrentWidget(self.significant_results_tab)
        if self.tabs.currentWidget() is not self.setup_tab:
            self.tabs.setCurrentWidget(self.setup_tab)

    def _show_frequency_or_ready_status(self) -> None:
        if self._frequency_snapshot is None:
            detail = f" ({self._frequency_error})" if self._frequency_error else ""
            self.workflow_status.set_variant("error")
            self.workflow_status.set_text(
                "Free Harmonic Clustering requires valid base and oddball "
                f"frequencies from Project Settings{detail}"
            )
        else:
            self.workflow_status.set_variant("info")
            self.workflow_status.set_text("Ready to load project inputs.")

    def _show_error(self, message: str) -> None:
        self.workflow_status.set_variant("error")
        self.workflow_status.set_text(str(message))

    @Slot(int)
    def _update_action_visibility(self, _index: int = -1) -> None:
        current = self.tabs.currentWidget()
        busy = self._thread is not None
        self.prepare_button.setVisible(current is self.setup_tab and not busy)
        self.run_button.setVisible(current is self.review_tab and not busy)
        self.setup_open_results_button.setVisible(current is not self.results_tab)
        self.workflow_actions.setVisible(current is not self.results_tab or busy)

    def _update_buttons(self) -> None:
        busy = self._thread is not None
        error = self._setup_error()
        self.prepare_button.setEnabled(not busy and error is None)
        self.run_button.setEnabled(not busy and self._prepared is not None)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.design_combo.setEnabled(not busy and self._options is not None)
        self.harmonic_mode_combo.setEnabled(not busy and self._options is not None)
        self.design_stack.setEnabled(not busy and self._options is not None)
        fixed = self._selected_harmonic_mode() is GuiHarmonicMode.FIXED_HIGHEST
        self.fixed_highest_combo.setEnabled(
            not busy and fixed and self._options is not None and self.fixed_highest_combo.count() > 0
        )
        self._update_action_visibility()

    def _results_parent(self) -> Path:
        return self._backend.results_parent(self._project_root)

    def _update_results_folder_button(self) -> None:
        try:
            exists = self._results_parent().is_dir()
        except OSError:
            exists = False
        self.open_results_button.setEnabled(exists)
        self.setup_open_results_button.setEnabled(exists)

    @Slot()
    def _open_results_folder(self) -> None:
        parent = self._results_parent()
        if not parent.is_dir():
            self.open_results_button.setEnabled(False)
            self.setup_open_results_button.setEnabled(False)
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

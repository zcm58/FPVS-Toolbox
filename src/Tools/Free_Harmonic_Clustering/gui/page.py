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
    QScrollArea,
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


def _join_or_none(values: object) -> str:
    items = tuple(str(value) for value in values or ())
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

        self.beta_banner = StatusBanner(
            "Beta: this clean-room implementation mirrors the published "
            "Hermann et al. method where the available information permits.",
            self,
            variant="warning",
        )
        self.beta_banner.setObjectName("free_harmonic_beta_banner")
        beta_wrapper = QWidget(self)
        beta_layout = QVBoxLayout(beta_wrapper)
        beta_layout.setContentsMargins(24, 0, 24, 0)
        beta_layout.addWidget(self.beta_banner)
        root_layout.addWidget(beta_wrapper)

        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("free_harmonic_main_tabs")
        self.setup_tab = QWidget(self.tabs)
        self.setup_tab.setObjectName("free_harmonic_setup_tab")
        self.results_tab = QWidget(self.tabs)
        self.results_tab.setObjectName("free_harmonic_results_tab")
        self.tabs.addTab(self.setup_tab, "Setup & Preparation")
        self.tabs.addTab(self.results_tab, "Results")
        self.tabs.setTabEnabled(1, False)
        root_layout.addWidget(self.tabs, 1)

        self._build_setup_tab()
        self._build_results_tab()

    def _flat_scroll_page(self, parent: QWidget, object_name: str) -> tuple[QWidget, QVBoxLayout]:
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(parent)
        scroll.setObjectName(object_name)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(scroll)
        content = QWidget(scroll)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 16, 24, 24)
        content_layout.setSpacing(14)
        scroll.setWidget(content)
        return content, content_layout

    def _build_setup_tab(self) -> None:
        content, layout = self._flat_scroll_page(
            self.setup_tab,
            "free_harmonic_setup_scroll",
        )
        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(14)
        top_grid.setVerticalSpacing(14)
        top_grid.setColumnStretch(0, 3)
        top_grid.setColumnStretch(1, 2)
        layout.addLayout(top_grid)

        setup_card = SectionCard(
            "Analysis setup",
            content,
            object_name="free_harmonic_setup_card",
        )
        top_grid.addWidget(setup_card, 0, 0)
        form = make_form_layout()
        setup_card.content_layout.addLayout(form)

        self.design_combo = QComboBox(setup_card.content)
        self.design_combo.setObjectName("free_harmonic_design_combo")
        self.design_combo.addItem(
            "Paired Conditions",
            GuiAnalysisDesign.PAIRED_CONDITIONS,
        )
        self.design_combo.addItem(
            "Independent Groups",
            GuiAnalysisDesign.INDEPENDENT_GROUPS,
        )
        form.addRow("Analysis mode:", self.design_combo)

        self.design_stack = QStackedWidget(setup_card.content)
        self.design_stack.setObjectName("free_harmonic_design_stack")
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

        self.swap_button = make_action_button(
            "Swap A/B",
            variant="secondary",
            compact=True,
            parent=setup_card.content,
        )
        self.swap_button.setObjectName("free_harmonic_swap_button")
        form.addRow("Contrast order:", self.swap_button)

        self.direction_label = QLabel("Contrast: A - B", setup_card.content)
        self.direction_label.setObjectName("free_harmonic_direction_label")
        self.direction_label.setWordWrap(True)
        self.direction_label.setProperty("caption", True)
        form.addRow(self.direction_label)

        self.harmonic_mode_combo = QComboBox(setup_card.content)
        self.harmonic_mode_combo.setObjectName("free_harmonic_mode_combo")
        self.harmonic_mode_combo.addItem(
            "Hermann automatic selection",
            GuiHarmonicMode.AUTOMATIC,
        )
        self.harmonic_mode_combo.addItem(
            "Fixed harmonic list",
            GuiHarmonicMode.FIXED_HIGHEST,
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

        self.discovery_note = QLabel(
            "Project choices are loaded from canonical metadata and the actual "
            "FullFFT header.",
            setup_card.content,
        )
        self.discovery_note.setObjectName("free_harmonic_discovery_note")
        self.discovery_note.setWordWrap(True)
        self.discovery_note.setProperty("caption", True)
        form.addRow(self.discovery_note)

        profile_card = SectionCard(
            "Hermann-compatible profile",
            content,
            object_name="free_harmonic_profile_card",
        )
        top_grid.addWidget(profile_card, 0, 1)
        profile = QLabel(
            "Read-only method settings\n\n"
            "10,000 permutations\n"
            "Grand-spectrum z > 3.29\n"
            "+/-0.1 Hz noise window\n"
            "Participant/arm L2 normalization\n"
            "Two-sided node-entry alpha = .01\n"
            "Per-direction cluster alpha = .025\n"
            "Complete within-sensor harmonic adjacency\n"
            "197-edge FieldTrip-style BioSemi64 graph\n"
            "Deterministic, recorded random seed",
            profile_card.content,
        )
        profile.setObjectName("free_harmonic_profile_summary")
        profile.setWordWrap(True)
        profile_card.content_layout.addWidget(profile)
        profile_note = QLabel(
            "The method profile is fixed in v1. Full settings and limitations "
            "are recorded in every completed result bundle.",
            profile_card.content,
        )
        profile_note.setWordWrap(True)
        profile_note.setProperty("caption", True)
        profile_card.content_layout.addWidget(profile_note)
        profile_card.content_layout.addStretch(1)

        review_card = SectionCard(
            "Preparation review",
            content,
            object_name="free_harmonic_preparation_card",
        )
        layout.addWidget(review_card)
        review_form = make_form_layout()
        review_card.content_layout.addLayout(review_form)
        self.review_design_label = QLabel("Not prepared", review_card.content)
        self.review_direction_label = QLabel("Not prepared", review_card.content)
        self.review_cohort_label = QLabel("Not prepared", review_card.content)
        self.review_participants_label = QLabel("Not prepared", review_card.content)
        self.review_exclusions_label = QLabel("Not prepared", review_card.content)
        self.review_harmonics_label = QLabel("Not prepared", review_card.content)
        self.review_selection_audit_label = QLabel("Not prepared", review_card.content)
        self.review_frequency_domain_label = QLabel("Not prepared", review_card.content)
        self.review_source_coverage_label = QLabel("Not prepared", review_card.content)
        self.review_shape_label = QLabel("Not prepared", review_card.content)
        for widget in (
            self.review_direction_label,
            self.review_cohort_label,
            self.review_participants_label,
            self.review_exclusions_label,
            self.review_harmonics_label,
            self.review_selection_audit_label,
            self.review_frequency_domain_label,
            self.review_source_coverage_label,
            self.review_shape_label,
        ):
            widget.setWordWrap(True)
        review_form.addRow("Design:", self.review_design_label)
        review_form.addRow("Direction:", self.review_direction_label)
        review_form.addRow("Cohort:", self.review_cohort_label)
        review_form.addRow("Included IDs:", self.review_participants_label)
        review_form.addRow("Excluded/incomplete:", self.review_exclusions_label)
        review_form.addRow("Harmonics:", self.review_harmonics_label)
        review_form.addRow("Selection audit:", self.review_selection_audit_label)
        review_form.addRow("Frequency domain:", self.review_frequency_domain_label)
        review_form.addRow("Source coverage:", self.review_source_coverage_label)
        review_form.addRow("Data shape:", self.review_shape_label)

        workflow_card = SectionCard(
            "Run analysis",
            content,
            object_name="free_harmonic_workflow_card",
        )
        layout.addWidget(workflow_card)
        self.workflow_status = StatusBanner(
            "Loading project inputs...",
            workflow_card.content,
            variant="info",
        )
        self.workflow_status.setObjectName("free_harmonic_workflow_status")
        workflow_card.content_layout.addWidget(self.workflow_status)
        self.progress_bar = QProgressBar(workflow_card.content)
        self.progress_bar.setObjectName("free_harmonic_progress_bar")
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        workflow_card.content_layout.addWidget(self.progress_bar)
        self.prepare_button = make_action_button(
            "Prepare Analysis",
            variant="primary",
            parent=workflow_card.content,
        )
        self.prepare_button.setObjectName("free_harmonic_prepare_button")
        self.run_button = make_action_button(
            "Run Permutations",
            variant="primary",
            parent=workflow_card.content,
        )
        self.run_button.setObjectName("free_harmonic_run_button")
        self.cancel_button = make_action_button(
            "Cancel",
            variant="tertiary",
            parent=workflow_card.content,
        )
        self.cancel_button.setObjectName("free_harmonic_cancel_button")
        self.setup_open_results_button = make_action_button(
            "Open Results Folder",
            variant="secondary",
            parent=workflow_card.content,
        )
        self.setup_open_results_button.setObjectName(
            "free_harmonic_setup_open_results_button"
        )
        actions = make_action_row(
            (
                self.setup_open_results_button,
                self.cancel_button,
                self.prepare_button,
                self.run_button,
            ),
            parent=workflow_card.content,
        )
        workflow_card.content_layout.addWidget(actions)
        layout.addStretch(1)

    def _build_results_tab(self) -> None:
        content, layout = self._flat_scroll_page(
            self.results_tab,
            "free_harmonic_results_scroll",
        )
        run_card = SectionCard(
            "Current run",
            content,
            object_name="free_harmonic_current_run_card",
        )
        layout.addWidget(run_card)
        self.result_status = StatusBanner(
            "Results appear after a successful permutation run.",
            run_card.content,
            variant="info",
        )
        self.result_status.setObjectName("free_harmonic_result_status")
        run_card.content_layout.addWidget(self.result_status)
        self.result_run_summary = QLabel("No current-session result.", run_card.content)
        self.result_run_summary.setObjectName("free_harmonic_result_run_summary")
        self.result_run_summary.setWordWrap(True)
        run_card.content_layout.addWidget(self.result_run_summary)
        self.open_results_button = make_action_button(
            "Open Results Folder",
            variant="secondary",
            parent=run_card.content,
        )
        self.open_results_button.setObjectName("free_harmonic_open_results_button")
        run_card.content_layout.addWidget(
            make_action_row((self.open_results_button,), parent=run_card.content)
        )

        significant_card = SectionCard(
            "Significant Results",
            content,
            object_name="free_harmonic_significant_card",
        )
        layout.addWidget(significant_card)
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
        self.significant_table.hide()
        significant_card.content_layout.addWidget(self.significant_table)

        all_card = SectionCard(
            "All clusters",
            content,
            object_name="free_harmonic_all_clusters_card",
        )
        layout.addWidget(all_card)
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
        self.all_clusters_table.setMinimumHeight(240)
        all_card.content_layout.addWidget(self.all_clusters_table)
        layout.addStretch(1)

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
        for combo in (
            self.paired_condition_a_combo,
            self.paired_condition_b_combo,
            self.paired_group_filter_combo,
            self.independent_condition_combo,
            self.independent_group_a_combo,
            self.independent_group_b_combo,
            self.fixed_highest_combo,
        ):
            combo.currentIndexChanged.connect(self._on_setup_changed)
        self.swap_button.clicked.connect(self._swap_a_b)
        self.prepare_button.clicked.connect(self._prepare_analysis)
        self.run_button.clicked.connect(self._run_permutations)
        self.cancel_button.clicked.connect(self.cancel_active_work)
        self.setup_open_results_button.clicked.connect(self._open_results_folder)
        self.open_results_button.clicked.connect(self._open_results_folder)
        self.significant_only_check.toggled.connect(self._apply_cluster_filter)

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
                "Project inputs loaded with dataset diagnostics. Review exclusions "
                "in the preparation summary before running."
            )
        else:
            self.workflow_status.set_variant("info")
            self.workflow_status.set_text(
                "Project inputs loaded. Exact selected-cohort grid compatibility "
                "will be validated during Prepare Analysis."
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
            excluded = ", ".join(
                f"H{order} ({_frequency_text(frequency)})"
                for order, frequency in zip(
                    options.excluded_base_orders,
                    options.excluded_base_harmonics_hz,
                    strict=True,
                )
            )
            upper = (
                "unknown"
                if options.fft_upper_hz is None
                else _frequency_text(options.fft_upper_hz)
            )
            note = f"FullFFT upper frequency: {upper}."
            if excluded:
                note += f" Base-rate overlaps excluded: {excluded}."
            self.discovery_note.setText(note)
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
    @Slot()
    def _on_design_changed(self) -> None:
        design = self.design_combo.currentData()
        paired = design is GuiAnalysisDesign.PAIRED_CONDITIONS
        self.design_stack.setCurrentIndex(0 if paired else 1)
        self._on_setup_changed()

    @Slot()
    def _on_harmonic_mode_changed(self) -> None:
        fixed = self.harmonic_mode_combo.currentData() is GuiHarmonicMode.FIXED_HIGHEST
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

    def _update_direction_label(self) -> None:
        design = self.design_combo.currentData()
        if design is GuiAnalysisDesign.PAIRED_CONDITIONS:
            arm_a = self.paired_condition_a_combo.currentText() or "Condition A"
            arm_b = self.paired_condition_b_combo.currentText() or "Condition B"
        else:
            arm_a = self.independent_group_a_combo.currentText() or "Group A"
            arm_b = self.independent_group_b_combo.currentText() or "Group B"
        self.direction_label.setText(
            f"Contrast: {arm_a} - {arm_b}; positive clusters indicate {arm_a} > {arm_b}."
        )

    @Slot()
    def _swap_a_b(self) -> None:
        if self.design_combo.currentData() is GuiAnalysisDesign.PAIRED_CONDITIONS:
            left = self.paired_condition_a_combo.currentIndex()
            right = self.paired_condition_b_combo.currentIndex()
            self.paired_condition_a_combo.setCurrentIndex(right)
            self.paired_condition_b_combo.setCurrentIndex(left)
        else:
            left = self.independent_group_a_combo.currentIndex()
            right = self.independent_group_b_combo.currentIndex()
            self.independent_group_a_combo.setCurrentIndex(right)
            self.independent_group_b_combo.setCurrentIndex(left)
        self._on_setup_changed()

    def _current_setup(self) -> AnalysisSetup:
        if self._options is None or self._frequency_snapshot is None:
            raise ValueError("Project inputs have not been loaded.")
        design = self.design_combo.currentData()
        if not isinstance(design, GuiAnalysisDesign):
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

        harmonic_mode = self.harmonic_mode_combo.currentData()
        if not isinstance(harmonic_mode, GuiHarmonicMode):
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
        self.tabs.setTabEnabled(1, True)
        self.tabs.setCurrentWidget(self.results_tab)
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
            included = _join_or_none(participants_a)
            shape = f"{len(participants_a)} participants x {len(sensors)} electrodes x {len(orders)} harmonics"
        else:
            cohort = f"{arm_a}: n = {len(participants_a)}; {arm_b}: n = {len(participants_b)}"
            included = (
                f"{arm_a}: {_join_or_none(participants_a)}\n"
                f"{arm_b}: {_join_or_none(participants_b)}"
            )
            shape = (
                f"{len(participants_a)} + {len(participants_b)} participants; "
                f"{len(sensors)} electrodes x {len(orders)} harmonics per participant"
            )
        self.review_cohort_label.setText(cohort)
        self.review_participants_label.setText(included)
        exclusions = []
        for label, field_name in (
            ("ledger", "ledger_excluded_participants"),
            ("manual", "manual_excluded_participants"),
            ("frequency QC", "frequency_qc_excluded_participants"),
            ("incomplete pairs", "incomplete_pair_participants"),
        ):
            values = tuple(getattr(provenance, field_name, ())) if provenance else ()
            if values:
                exclusions.append(f"{label}: {', '.join(map(str, values))}")
        participant_condition_exclusions = (
            tuple(getattr(provenance, "participant_condition_exclusions", ()))
            if provenance
            else ()
        )
        if participant_condition_exclusions:
            formatted = ", ".join(
                f"{getattr(record, 'participant_id', '?')} / "
                f"{getattr(record, 'condition', '?')} "
                f"({getattr(record, 'reason', 'excluded')})"
                for record in participant_condition_exclusions
            )
            exclusions.append(f"participant-condition: {formatted}")
        self.review_exclusions_label.setText("; ".join(exclusions) or "None")
        harmonic_text = ", ".join(
            f"H{order} ({_frequency_text(frequency)})"
            for order, frequency in zip(orders, frequencies, strict=True)
        )
        mode = getattr(getattr(prepared, "method", None), "harmonic_selection_mode", "automatic")
        mode_text = str(getattr(mode, "value", mode)).replace("_", " ")
        self.review_harmonics_label.setText(
            f"{harmonic_text or 'None'} ({mode_text} domain)"
        )
        self.review_selection_audit_label.setText(
            self._selection_audit_text(prepared)
        )
        frequency_plan = getattr(prepared, "frequency_plan", None)
        excluded_orders = tuple(
            int(value)
            for value in getattr(frequency_plan, "excluded_base_orders", ())
        )
        excluded_hz = tuple(
            float(value)
            for value in getattr(
                frequency_plan,
                "excluded_base_harmonics_hz",
                (),
            )
        )
        excluded_text = ", ".join(
            f"H{order} ({_frequency_text(frequency)})"
            for order, frequency in zip(
                excluded_orders,
                excluded_hz,
                strict=True,
            )
        )
        resolution = getattr(frequency_plan, "frequency_resolution_hz", None)
        self.review_frequency_domain_label.setText(
            f"Base-rate overlaps excluded: {excluded_text or 'none'}; "
            f"FullFFT resolution: "
            f"{'unknown' if resolution is None else _frequency_text(float(resolution))}."
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
    def _selection_audit_text(prepared: object) -> str:
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
            return ", ".join(rows) or "none"

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
            f"Exported run: {output}"
        )

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
            self.review_frequency_domain_label,
            self.review_source_coverage_label,
            self.review_shape_label,
        ):
            label.setText("Not prepared")
        self.significant_table.setRowCount(0)
        self.significant_table.hide()
        self.all_clusters_table.setRowCount(0)
        self.significant_only_check.setChecked(False)
        self.result_run_summary.setText("No current-session result.")
        self.result_status.set_variant("info")
        self.result_status.set_text("Results appear after a successful permutation run.")
        self.significant_status.set_variant("info")
        self.significant_status.set_text("No result has been run.")
        self.tabs.setTabEnabled(1, False)
        if self.tabs.currentWidget() is self.results_tab:
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
        self.swap_button.setEnabled(not busy and self._options is not None)
        fixed = self.harmonic_mode_combo.currentData() is GuiHarmonicMode.FIXED_HIGHEST
        self.fixed_highest_combo.setEnabled(
            not busy and fixed and self._options is not None and self.fixed_highest_combo.count() > 0
        )

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

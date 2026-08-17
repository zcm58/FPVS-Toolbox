"""Embedded PySide6 page for Free Harmonic Clustering Analysis."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import logging

from PySide6.QtCore import QThread, QTimer, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QStackedWidget,
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


class FreeHarmonicClusteringPage(QWidget):
    """Project-bound, source-immutable analysis workspace page."""

    post_processing_required = Signal(str, str, str)

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
        self._continue_to_permutations = False
        self._pending_context: tuple[Path, ProjectFrequencySnapshot | None, str | None] | None = None
        self._pending_post_processing_reason: str | None = None
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
        workspace_layout.addWidget(self.results_panel, 1)
        root_layout.addWidget(self.workspace, 1)

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
        cards_layout.addWidget(self.comparison_card, 1)
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

        self.design_stack = QStackedWidget(self.comparison_card.content)
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
        self.harmonics_card.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Preferred,
        )
        cards_layout.addWidget(self.harmonics_card, 1)
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
            (harmonics_form, self.harmonic_mode_combo),
            (harmonics_form, fixed_row),
        )
        for form_layout, field in aligned_fields:
            label = form_layout.labelForField(field)
            if label is not None:
                label.setFixedWidth(120)

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
        self.run_analysis_button = make_action_button(
            "Run Analysis",
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
        self.workflow_actions = make_action_row(
            (
                self.open_results_button,
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
        results_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(results_card)
        layout.addStretch(1)
        self.result_status = StatusBanner(
            "No result has been run.",
            results_card.content,
            variant="info",
        )
        self.result_status.setObjectName("free_harmonic_result_status")
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
            QSizePolicy.Preferred,
        )
        self.significant_table.hide()
        results_card.content_layout.addWidget(self.significant_table)
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
        self.run_analysis_button.clicked.connect(self._run_analysis)
        self.cancel_button.clicked.connect(self.cancel_active_work)
        self.open_results_button.clicked.connect(self._open_results_folder)

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
        self._pending_post_processing_reason = None
        self._continue_to_permutations = False
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
                "Project inputs loaded with dataset diagnostics. Select Run "
                "Analysis to continue. Exact cohort and input details will be "
                "recorded in the completed results workbook."
            )
        else:
            self.workflow_status.set_variant("info")
            self.workflow_status.set_text(
                "Project inputs loaded. Select Run Analysis once to complete the "
                "analysis and show the results below."
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
                "Setup changed. Run the analysis again to use the new choices."
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
    def _run_analysis(self) -> None:
        error = self._setup_error()
        if error:
            self._show_error(error)
            return
        assert self._options is not None
        assert self._frequency_snapshot is not None
        setup = self._current_setup()
        self._clear_prepared_and_results()
        self._continue_to_permutations = True
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
        self.workflow_status.set_variant("success")
        self.workflow_status.set_text(
            "Preparation complete. Starting cluster permutations..."
        )
        self._update_buttons()

    @Slot()
    def _run_permutations(self) -> None:
        if self._prepared is None:
            self._show_error("Run the analysis to prepare data before permutations.")
            return
        worker = PermutationWorker(self._backend, self._prepared)
        self._start_operation(
            worker,
            stage="permutations",
            message="Running whole-participant cluster permutations...",
            on_completed=self._on_run_completed,
        )

    def _on_run_completed(self, value: object) -> None:
        self._continue_to_permutations = False
        if not isinstance(value, RunOutcome):
            self._show_error("Permutation analysis returned an invalid result.")
            return
        self._run_outcome = value
        self._populate_results(value)
        self.results_panel.show()
        self._update_results_folder_button()
        self.workflow_status.hide()
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
        self._continue_to_permutations = False
        if not self._retired:
            if self._active_stage == "inspection":
                self._inspection_failed = True
            self._show_error(message or "The analysis operation failed.")

    @Slot(str)
    def _on_post_processing_required(self, reason: str) -> None:
        if self._retired:
            return
        self._continue_to_permutations = False
        self._inspection_failed = True
        self._options = None
        self._clear_prepared_and_results()
        self._clear_choice_controls()
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
        self._continue_to_permutations = False
        if not self._retired:
            if self._active_stage == "inspection":
                self._inspection_failed = True
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
            self._continue_to_permutations = False
            self.progress_bar.hide()
            return
        if self._pending_context is not None:
            self._continue_to_permutations = False
            self.progress_bar.hide()
            context = self._pending_context
            self._pending_context = None
            self._apply_new_context(*context)
            return
        if post_processing_reason:
            self._continue_to_permutations = False
            self.progress_bar.hide()
            self._update_buttons()
            self.post_processing_required.emit(
                "Free Harmonic Clustering Analysis",
                post_processing_reason,
                str(self._project_root),
            )
            return
        if (
            finished_stage == "preparation"
            and self._continue_to_permutations
            and self._prepared is not None
        ):
            self._continue_to_permutations = False
            self._run_permutations()
            return
        self._continue_to_permutations = False
        self.progress_bar.hide()
        self._update_buttons()

    @Slot()
    def cancel_active_work(self) -> None:
        """Request cancellation without blocking the GUI thread."""

        worker = self._worker
        if worker is not None and hasattr(worker, "cancel"):
            if self._active_stage == "preparation":
                self._continue_to_permutations = False
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
        self._continue_to_permutations = False
        self._pending_context = None
        self._pending_post_processing_reason = None
        self.cancel_active_work()
        self.setEnabled(False)

    def closeEvent(self, event: Any) -> None:  # noqa: N802, ANN401
        self.shutdown()
        super().closeEvent(event)

    # ------------------------------------------------------------ summaries
    def _populate_results(self, outcome: RunOutcome) -> None:
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
        if significant:
            self.result_status.set_variant("warning" if unstable else "success")
            cluster_word = "cluster" if len(significant) == 1 else "clusters"
            self.result_status.set_text(
                f"{len(significant)} significant {cluster_word} found."
                + (
                    " At least one result is close to the decision threshold; "
                    "interpret it cautiously."
                    if unstable
                    else ""
                )
            )
            self.significant_table.show()
            self._fill_significant_table(significant)
        else:
            self.significant_table.hide()
            self.significant_table.setRowCount(0)
            self.result_status.set_variant("warning" if unstable else "info")
            self.result_status.set_text(
                "No significant clusters were found."
                + (
                    " At least one result is close to the decision threshold; "
                    "interpret it cautiously."
                    if unstable
                    else ""
                )
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
        return {
            "direction": direction,
            "sensors": sensors,
            "harmonics": harmonics,
            "mass": f"{float(getattr(cluster, 'mass', 0.0)):.4f}",
            "raw_p": f"{float(getattr(cluster, 'p_value', 1.0)):.4f}",
        }

    def _fill_significant_table(self, clusters: tuple[object, ...]) -> None:
        self.significant_table.setRowCount(len(clusters))
        for row, cluster in enumerate(clusters):
            display = self._cluster_display(cluster)
            for column, key in enumerate(("direction", "sensors", "harmonics", "mass", "raw_p")):
                self.significant_table.setItem(row, column, QTableWidgetItem(display[key]))

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
        self.significant_table.setRowCount(0)
        self.significant_table.hide()
        self.result_status.set_variant("info")
        self.result_status.set_text("No result has been run.")
        self.results_panel.hide()

    def _show_frequency_or_ready_status(self) -> None:
        self.workflow_status.show()
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
        self.workflow_status.show()
        self.workflow_status.set_variant("error")
        self.workflow_status.set_text(str(message))

    def _update_buttons(self) -> None:
        busy = self._thread is not None
        error = self._setup_error()
        self.run_analysis_button.setEnabled(not busy and error is None)
        self.run_analysis_button.setVisible(not busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(busy)
        self.workflow_actions.setVisible(True)
        self.design_combo.setEnabled(not busy and self._options is not None)
        self.harmonic_mode_combo.setEnabled(not busy and self._options is not None)
        self.design_stack.setEnabled(not busy and self._options is not None)
        fixed = self._selected_harmonic_mode() is GuiHarmonicMode.FIXED_HIGHEST
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

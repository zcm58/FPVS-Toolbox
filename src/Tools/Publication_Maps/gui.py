"""Embedded PySide6 page for publication scalp maps."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStyle,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import config
from Main_App import SettingsManager
from Main_App.gui.components import (
    ActionRow,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    SubsectionHeaderLabel,
    SurfaceSize,
    configure_window_surface,
    confirm,
    make_action_button,
    make_form_layout,
    make_info_button,
    show_error,
    show_tool_info,
)
from Main_App.projects import GroupInfo, ProjectDatasetIndex, load_project_dataset_index
from Tools.Publication_Maps.generation_outcome import (
    PublicationMapsOutcomeStatus,
    PublicationMapsWorkerOutcome,
)
from Tools.Publication_Maps.models import (
    ColorBounds,
    DEFAULT_BCA_HIGH_COLOR,
    DEFAULT_BCA_LOW_COLOR,
    DEFAULT_Z_SCORE_THRESHOLD,
    PublicationMapRequest,
    PublicationMetric,
)
from Tools.Publication_Maps.output_contract import validate_output_root
from Tools.Publication_Maps.session_controls import (
    PublicationSessionControlError,
    PublicationSessionState,
    SESSION_MODE_COMPARISON,
    SESSION_MODE_CONDITION,
    publication_session_state,
)
from Tools.Publication_Maps.tool_info import SCALP_MAPS_TOOL_INFO
from Tools.Publication_Maps.worker import PublicationMapsWorker

logger = logging.getLogger(__name__)

SCALP_MAPS_OUTPUT_FOLDER = "4 - Scalp Maps"
SCALP_MAPS_TOP_ROW_MIN_HEIGHT = 340
SCALP_MAPS_BOTTOM_ROW_MIN_HEIGHT = 240
ALL_GROUPS_VALUE = "__all_canonical_groups__"
ALL_GROUPS_LABEL = "All groups (separate outputs)"
ALL_GROUPS_COMPARISON_LABEL = "All groups (comparison)"
ALL_GROUPS_TOOLTIP = (
    "Choose one canonical project group, or generate a separate output set "
    "for every group."
)
ALL_GROUPS_COMPARISON_TOOLTIP = (
    "Both canonical groups are selected for one descriptive comparison-only output."
)


class PublicationMapsWindow(QWidget):
    """Embedded tool page for Stats-selected publication scalp maps."""

    post_processing_required = Signal(str, str, str)
    generation_idle = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        project_root: str | None = None,
        *,
        embedded: bool = True,
    ) -> None:
        super().__init__(parent)
        surface_size = SurfaceSize(width=1100, height=760)
        if not embedded:
            surface_size = SurfaceSize(width=1100, height=760, min_width=980)
        configure_window_surface(
            self,
            title="Scalp Maps",
            size=surface_size,
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._project_root = self._resolve_project_root(project_root)
        self._last_dir: Optional[Path] = None
        self._thread: QThread | None = None
        self._worker: PublicationMapsWorker | None = None
        self._busy = False
        self._host_navigation_locked = False
        self._last_generated_figure_count = 0
        self._pending_outcome: PublicationMapsWorkerOutcome | None = None
        self._cancel_requested = False
        self._settings_fallback: SettingsManager | None = None
        self.bca_low_color = DEFAULT_BCA_LOW_COLOR
        self.bca_high_color = DEFAULT_BCA_HIGH_COLOR
        self._dataset_index: ProjectDatasetIndex | None = None
        self._conditions: tuple[str, ...] = ()
        self._condition_counts: dict[str, int] = {}
        self._session_state = PublicationSessionState(repeated=False)
        self._session_control_error = ""
        self._session_controls_initialized = False
        self._last_run_was_session_grid = False

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(8, 8, 8, 8)
        outer_layout.setSpacing(8)
        outer_layout.addWidget(self._build_input_group(), 0)

        self.workflow_tabs = QTabWidget(self)
        self.workflow_tabs.setObjectName("publication_maps_workflow_tabs")
        selection_page = QWidget(self.workflow_tabs)
        selection_layout = QGridLayout(selection_page)
        selection_layout.setContentsMargins(0, 8, 0, 0)
        selection_layout.setHorizontalSpacing(8)
        selection_layout.addWidget(self._build_conditions_group(), 0, 0)
        selection_layout.addWidget(self._build_settings_group(), 0, 1)
        selection_layout.setColumnStretch(0, 1)
        selection_layout.setColumnStretch(1, 1)

        output_page = QWidget(self.workflow_tabs)
        output_layout = QGridLayout(output_page)
        output_layout.setContentsMargins(0, 8, 0, 0)
        output_layout.setHorizontalSpacing(8)
        output_layout.addWidget(self._build_output_group(), 0, 0)
        output_layout.addWidget(self._build_run_group(), 0, 1)
        output_layout.setColumnStretch(0, 1)
        output_layout.setColumnStretch(1, 1)

        self.workflow_tabs.addTab(selection_page, "Data & Maps")
        self.workflow_tabs.addTab(output_page, "Output & Run")
        outer_layout.addWidget(self.workflow_tabs, 1)

        self._apply_button_icons()
        self._set_default_paths()
        self._refresh_conditions()
        self._update_run_state()

    def _resolve_project_root(self, provided_root: str | None) -> Path | None:
        if provided_root:
            root = Path(provided_root)
            if root.exists():
                return root
        env_root = os.environ.get("FPVS_PROJECT_ROOT")
        if env_root:
            root = Path(env_root)
            if root.exists():
                return root
        proj = getattr(self.parent(), "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
            if root.exists():
                return root
        return None

    def _build_input_group(self) -> SectionCard:
        group = SectionCard("Input data", object_name="publication_maps_input")
        self.scalp_maps_info_btn = make_info_button(
            parent=group,
            tooltip="About Scalp Maps",
            object_name="scalp_maps_tool_info_btn",
        )
        self.scalp_maps_info_btn.clicked.connect(
            lambda: show_tool_info(self, SCALP_MAPS_TOOL_INFO)
        )
        group.header.add_action_widget(self.scalp_maps_info_btn)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        form = make_form_layout()

        self.input_root_row = PathPickerRow(
            "Browse...",
            group,
            placeholder="Select Excel root folder",
        )
        self.input_root_row.setObjectName("publication_maps_input_root_row")
        self.input_root_edit = self.input_root_row.line_edit
        self.input_root_btn = self.input_root_row.button
        self.input_root_btn.clicked.connect(self._browse_input_root)
        self.input_root_edit.textChanged.connect(self._on_input_root_changed)
        if self._project_root is not None:
            managed_input_tooltip = (
                "Scalp Maps uses the active project's configured Excel root. "
                "Change that folder in Project Settings."
            )
            self.input_root_edit.setReadOnly(True)
            self.input_root_edit.setToolTip(managed_input_tooltip)
            self.input_root_btn.setEnabled(False)
            self.input_root_btn.setToolTip(managed_input_tooltip)

        self.group_combo = QComboBox(group)
        self.group_combo.setObjectName("publication_maps_group_combo")
        self.group_combo.setToolTip(ALL_GROUPS_TOOLTIP)
        self.group_combo.currentIndexChanged.connect(
            lambda _index: self._on_group_selection_changed()
        )

        self.refresh_btn = make_action_button("Refresh project data", compact=True, parent=group)
        self.refresh_btn.clicked.connect(self._refresh_conditions)

        form.addRow("Excel root folder:", self.input_root_row)
        form.addRow("Group:", self.group_combo)
        form.addRow("", self.refresh_btn)
        group.content_layout.addLayout(form)
        return group

    def _build_conditions_group(self) -> SectionCard:
        group = SectionCard("Conditions", object_name="publication_maps_conditions")
        group.setMinimumHeight(SCALP_MAPS_TOP_ROW_MIN_HEIGHT)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.conditions_list = QListWidget(group)
        self.conditions_list.setMinimumHeight(140)
        self.conditions_list.setMaximumHeight(220)
        self.conditions_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.conditions_list.itemChanged.connect(self._on_condition_item_changed)
        self.conditions_summary = QLabel("Selected conditions: 0 | Total files: 0")
        self.conditions_summary.setProperty("caption", True)

        buttons = ActionRow(group, alignment=Qt.AlignLeft, spacing=6)
        self.select_all_btn = make_action_button("Select all", compact=True, parent=group)
        self.select_none_btn = make_action_button("Select none", compact=True, parent=group)
        self.select_all_btn.clicked.connect(lambda: self._set_all_conditions(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_conditions(False))
        buttons.add_button(self.select_all_btn)
        buttons.add_button(self.select_none_btn)

        self.session_controls_widget = QWidget(group)
        self.session_controls_widget.setObjectName(
            "publication_maps_session_controls"
        )
        session_layout = QGridLayout(self.session_controls_widget)
        session_layout.setContentsMargins(0, 0, 0, 0)
        session_layout.setHorizontalSpacing(8)
        session_layout.setVerticalSpacing(5)
        self.session_dimension_combo = QComboBox(self.session_controls_widget)
        self.session_dimension_combo.setAccessibleName(
            "Scalp Maps comparison dimension"
        )
        self.session_dimension_combo.addItem(
            "Condition (one session)", SESSION_MODE_CONDITION
        )
        self.session_dimension_combo.addItem(
            "Session comparison", SESSION_MODE_COMPARISON
        )
        self.session_dimension_combo.currentIndexChanged.connect(
            self._on_session_mode_changed
        )
        session_layout.addWidget(QLabel("Compare:"), 0, 0)
        session_layout.addWidget(self.session_dimension_combo, 0, 1, 1, 3)

        self.single_session_label = QLabel("Session:")
        self.single_session_combo = QComboBox(self.session_controls_widget)
        self.single_session_combo.setAccessibleName(
            "Session for condition scalp maps"
        )
        self.single_session_combo.currentIndexChanged.connect(
            lambda _index: self._update_run_state()
        )
        session_layout.addWidget(self.single_session_label, 1, 0)
        session_layout.addWidget(self.single_session_combo, 1, 1, 1, 3)

        self.reference_session_label = QLabel("Reference:")
        self.reference_session_combo = QComboBox(self.session_controls_widget)
        self.reference_session_combo.setAccessibleName("Reference session")
        self.reference_session_combo.currentIndexChanged.connect(
            lambda _index: self._update_run_state()
        )
        self.comparison_session_label = QLabel("Comparison:")
        self.comparison_session_combo = QComboBox(self.session_controls_widget)
        self.comparison_session_combo.setAccessibleName("Comparison session")
        self.comparison_session_combo.currentIndexChanged.connect(
            lambda _index: self._update_run_state()
        )
        session_layout.addWidget(self.reference_session_label, 2, 0)
        session_layout.addWidget(self.reference_session_combo, 2, 1)
        session_layout.addWidget(self.comparison_session_label, 2, 2)
        session_layout.addWidget(self.comparison_session_combo, 2, 3)
        self.session_difference_check = QCheckBox(
            "Add paired within-participant difference row",
            self.session_controls_widget,
        )
        self.session_difference_check.setChecked(True)
        session_layout.addWidget(self.session_difference_check, 3, 0, 1, 4)
        self.session_caveat_label = QLabel(self.session_controls_widget)
        self.session_caveat_label.setObjectName(
            "publication_maps_session_order_caveat"
        )
        self.session_caveat_label.setProperty("caption", True)
        self.session_caveat_label.setWordWrap(True)
        session_layout.addWidget(self.session_caveat_label, 4, 0, 1, 4)
        session_layout.setColumnStretch(1, 1)
        session_layout.setColumnStretch(3, 1)
        self.session_controls_widget.hide()

        group.content_layout.addWidget(self.session_controls_widget)
        group.content_layout.addWidget(self.conditions_list)
        group.content_layout.addWidget(buttons)
        group.content_layout.addWidget(self.conditions_summary)
        return group

    def _build_settings_group(self) -> SectionCard:
        group = SectionCard("", object_name="publication_maps_settings")
        group.header.hide()
        group.setMinimumHeight(SCALP_MAPS_TOP_ROW_MIN_HEIGHT)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form = make_form_layout()

        self.metric_bca_check = QCheckBox("BCA", group)
        self.metric_bca_check.setChecked(True)
        self.metric_bca_check.setToolTip("Export BCA scalp maps.")
        self.metric_bca_check.toggled.connect(
            lambda _checked: self._on_metric_selection_changed()
        )
        self.metric_snr_check = QCheckBox("SNR", group)
        self.metric_snr_check.setChecked(True)
        self.metric_snr_check.setToolTip("Export SNR scalp maps.")
        self.metric_snr_check.toggled.connect(
            lambda _checked: self._on_metric_selection_changed()
        )
        self.metric_z_check = QCheckBox("Z-score", group)
        self.metric_z_check.setChecked(True)
        self.metric_z_check.setToolTip("Export z-score scalp maps.")
        self.metric_z_check.toggled.connect(
            lambda _checked: self._on_metric_selection_changed()
        )

        self.color_low_btn = QPushButton(group)
        self.color_low_btn.setFixedSize(20, 20)
        self.color_low_btn.setToolTip("Low value color")
        self.color_low_btn.clicked.connect(lambda: self._choose_bca_color("low"))

        self.color_high_btn = QPushButton(group)
        self.color_high_btn.setFixedSize(20, 20)
        self.color_high_btn.setToolTip("High value color")
        self.color_high_btn.clicked.connect(lambda: self._choose_bca_color("high"))

        self.fixed_bca_range_check = QCheckBox("Use fixed BCA range", group)
        self.fixed_bca_range_check.setToolTip(
            "When checked, every BCA scalp map uses the same colorbar range."
        )
        self.fixed_bca_range_check.setChecked(True)
        self.fixed_bca_range_check.stateChanged.connect(
            lambda _state: self._toggle_metric_range_controls()
        )

        self.bca_vmin_spin = QDoubleSpinBox(group)
        self.bca_vmin_spin.setDecimals(3)
        self.bca_vmin_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.bca_vmin_spin.setSingleStep(0.1)
        self.bca_vmin_spin.setSuffix(" BCA")
        self.bca_vmin_spin.setValue(0.0)

        self.bca_vmax_spin = QDoubleSpinBox(group)
        self.bca_vmax_spin.setDecimals(3)
        self.bca_vmax_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.bca_vmax_spin.setSingleStep(0.1)
        self.bca_vmax_spin.setSuffix(" BCA")
        self.bca_vmax_spin.setValue(0.4)

        self.fixed_snr_range_check = QCheckBox("Use fixed SNR range", group)
        self.fixed_snr_range_check.setToolTip(
            "When checked, every SNR scalp map uses the same colorbar range."
        )
        self.fixed_snr_range_check.setChecked(True)
        self.fixed_snr_range_check.stateChanged.connect(
            lambda _state: self._toggle_metric_range_controls()
        )

        self.snr_vmin_spin = QDoubleSpinBox(group)
        self.snr_vmin_spin.setDecimals(3)
        self.snr_vmin_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.snr_vmin_spin.setSingleStep(0.1)
        self.snr_vmin_spin.setSuffix(" SNR")
        self.snr_vmin_spin.setValue(1.0)

        self.snr_vmax_spin = QDoubleSpinBox(group)
        self.snr_vmax_spin.setDecimals(3)
        self.snr_vmax_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.snr_vmax_spin.setSingleStep(0.1)
        self.snr_vmax_spin.setSuffix(" SNR")
        self.snr_vmax_spin.setValue(1.5)

        self.z_threshold_spin = QDoubleSpinBox(group)
        self.z_threshold_spin.setDecimals(3)
        self.z_threshold_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.z_threshold_spin.setSingleStep(0.01)
        self.z_threshold_spin.setSuffix(" z")
        self.z_threshold_spin.setValue(DEFAULT_Z_SCORE_THRESHOLD)
        self.z_threshold_spin.setToolTip(
            "Z scores below this threshold render as white; the upper limit auto-scales."
        )

        color_row = QWidget(group)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(8)
        color_layout.addWidget(QLabel("Low", color_row))
        color_layout.addWidget(self.color_low_btn)
        color_layout.addSpacing(8)
        color_layout.addWidget(QLabel("High", color_row))
        color_layout.addWidget(self.color_high_btn)
        color_layout.addStretch(1)

        metrics_row = QWidget(group)
        metrics_layout = QHBoxLayout(metrics_row)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(12)
        metrics_layout.addWidget(self.metric_bca_check)
        metrics_layout.addWidget(self.metric_snr_check)
        metrics_layout.addWidget(self.metric_z_check)
        metrics_layout.addStretch(1)

        range_row = self._build_range_control_grid(
            group,
            lower_spin=self.bca_vmin_spin,
            upper_spin=self.bca_vmax_spin,
        )
        snr_range_row = self._build_range_control_grid(
            group,
            lower_spin=self.snr_vmin_spin,
            upper_spin=self.snr_vmax_spin,
        )

        form.addRow("Metrics:", metrics_row)
        form.addRow("Color scale:", color_row)
        form.addRow("", self.fixed_bca_range_check)
        form.addRow("BCA range:", range_row)
        form.addRow("", self.fixed_snr_range_check)
        form.addRow("SNR range:", snr_range_row)
        form.addRow("Z threshold:", self.z_threshold_spin)
        group.content_layout.addLayout(form)
        self._apply_bca_color_button_styles()
        self._toggle_metric_range_controls()
        return group

    def _build_range_control_grid(
        self,
        parent: QWidget,
        *,
        lower_spin: QDoubleSpinBox,
        upper_spin: QDoubleSpinBox,
    ) -> QWidget:
        row = QWidget(parent)
        layout = QGridLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)
        for spin in (lower_spin, upper_spin):
            spin.setMinimumWidth(132)
            spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout.addWidget(QLabel("Lower", row), 0, 0)
        layout.addWidget(lower_spin, 0, 1)
        layout.addWidget(QLabel("Upper", row), 1, 0)
        layout.addWidget(upper_spin, 1, 1)
        layout.setColumnStretch(1, 1)
        return row

    def _build_output_group(self) -> SectionCard:
        group = SectionCard("Output", object_name="publication_maps_output")
        group.setMinimumHeight(SCALP_MAPS_BOTTOM_ROW_MIN_HEIGHT)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        form = make_form_layout()

        self.output_root_row = PathPickerRow(
            "Browse...",
            group,
            placeholder="Select output folder",
        )
        self.output_root_row.setObjectName("publication_maps_output_root_row")
        self.output_root_edit = self.output_root_row.line_edit
        self.output_root_btn = self.output_root_row.button
        self.output_root_btn.clicked.connect(self._browse_output_root)
        self.output_root_edit.textChanged.connect(self._on_output_root_changed)
        self.open_output_btn = make_action_button("Open", compact=True, parent=group)
        self.open_output_btn.clicked.connect(self._open_output_folder)
        self.output_root_row.row_layout.insertWidget(1, self.open_output_btn)
        form.addRow("Output folder:", self.output_root_row)
        group.content_layout.addLayout(form)

        self.export_png_check = QCheckBox("PNG (600 DPI)", group)
        self.export_png_check.setChecked(True)
        self.export_png_check.setEnabled(False)
        self.export_pdf_check = QCheckBox("PDF (600 DPI)", group)
        self.export_pdf_check.setChecked(True)
        self.export_pdf_check.setEnabled(False)
        self.paired_figures_check = QCheckBox("Export paired condition figure only", group)
        self.paired_figures_check.setToolTip(
            "When at least two conditions are selected, export only the paired side-by-side scalp-map figure."
        )
        self.paired_figures_check.toggled.connect(self._on_paired_figures_toggled)

        self.paired_conditions_widget = QWidget(group)
        paired_layout = QVBoxLayout(self.paired_conditions_widget)
        paired_layout.setContentsMargins(0, 0, 0, 0)
        paired_layout.setSpacing(8)

        self.paired_condition_a_combo = QComboBox(self.paired_conditions_widget)
        self.paired_condition_a_combo.setToolTip("Select the first condition for the paired scalp-map figure.")
        self.paired_condition_a_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.paired_condition_a_combo.currentTextChanged.connect(lambda _text: self._update_run_state())

        self.paired_condition_b_combo = QComboBox(self.paired_conditions_widget)
        self.paired_condition_b_combo.setToolTip("Select the second condition for the paired scalp-map figure.")
        self.paired_condition_b_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.paired_condition_b_combo.currentTextChanged.connect(lambda _text: self._update_run_state())

        paired_a_container = QWidget(self.paired_conditions_widget)
        paired_a_layout = QVBoxLayout(paired_a_container)
        paired_a_layout.setContentsMargins(0, 0, 0, 0)
        paired_a_layout.setSpacing(4)
        paired_a_layout.addWidget(SubsectionHeaderLabel("Condition A", paired_a_container))
        paired_a_layout.addWidget(self.paired_condition_a_combo)

        paired_b_container = QWidget(self.paired_conditions_widget)
        paired_b_layout = QVBoxLayout(paired_b_container)
        paired_b_layout.setContentsMargins(0, 0, 0, 0)
        paired_b_layout.setSpacing(4)
        paired_b_layout.addWidget(SubsectionHeaderLabel("Condition B", paired_b_container))
        paired_b_layout.addWidget(self.paired_condition_b_combo)

        paired_selectors = QHBoxLayout()
        paired_selectors.setContentsMargins(0, 0, 0, 0)
        paired_selectors.setSpacing(8)
        paired_selectors.addWidget(paired_a_container, 1)
        paired_selectors.addWidget(paired_b_container, 1)
        paired_layout.addLayout(paired_selectors)

        self.group_comparison_check = QCheckBox(
            "Export two-group comparison figure only",
            group,
        )
        self.group_comparison_check.setObjectName(
            "publication_maps_group_comparison_check"
        )
        self.group_comparison_check.setToolTip(
            "Available when All groups is selected, the project has exactly two "
            "canonical groups, and exactly one condition with active workbooks in "
            "both groups is checked. Exports a descriptive side-by-side figure "
            "only; this is not a statistical test or difference map, and values "
            "are never pooled."
        )
        self.group_comparison_check.toggled.connect(
            self._on_group_comparison_toggled
        )

        self.group_comparison_hint = QLabel(
            "For projects with exactly two canonical groups, choose All groups "
            "and one condition represented in both groups. This mode exports only "
            "the descriptive comparison figure.",
            group,
        )
        self.group_comparison_hint.setObjectName(
            "publication_maps_group_comparison_hint"
        )
        self.group_comparison_hint.setProperty("caption", True)
        self.group_comparison_hint.setWordWrap(True)

        self.group_comparison_widget = QWidget(group)
        self.group_comparison_widget.setObjectName(
            "publication_maps_group_comparison_groups"
        )
        comparison_groups_layout = QHBoxLayout(self.group_comparison_widget)
        comparison_groups_layout.setContentsMargins(0, 0, 0, 0)
        comparison_groups_layout.setSpacing(8)

        comparison_a_container = QWidget(self.group_comparison_widget)
        comparison_a_layout = QVBoxLayout(comparison_a_container)
        comparison_a_layout.setContentsMargins(0, 0, 0, 0)
        comparison_a_layout.setSpacing(4)
        comparison_a_layout.addWidget(
            SubsectionHeaderLabel("Group A", comparison_a_container)
        )
        self.group_comparison_a_label = QLabel("—", comparison_a_container)
        self.group_comparison_a_label.setObjectName(
            "publication_maps_group_comparison_a_label"
        )
        comparison_a_layout.addWidget(self.group_comparison_a_label)

        comparison_b_container = QWidget(self.group_comparison_widget)
        comparison_b_layout = QVBoxLayout(comparison_b_container)
        comparison_b_layout.setContentsMargins(0, 0, 0, 0)
        comparison_b_layout.setSpacing(4)
        comparison_b_layout.addWidget(
            SubsectionHeaderLabel("Group B", comparison_b_container)
        )
        self.group_comparison_b_label = QLabel("—", comparison_b_container)
        self.group_comparison_b_label.setObjectName(
            "publication_maps_group_comparison_b_label"
        )
        comparison_b_layout.addWidget(self.group_comparison_b_label)

        comparison_groups_layout.addWidget(comparison_a_container, 1)
        comparison_groups_layout.addWidget(comparison_b_container, 1)

        formats = ActionRow(group, alignment=Qt.AlignLeft, spacing=12)
        formats.row_layout.addWidget(self.export_png_check)
        formats.row_layout.addWidget(self.export_pdf_check)
        group.content_layout.addWidget(formats)
        group.content_layout.addWidget(self.paired_figures_check)
        group.content_layout.addWidget(self.paired_conditions_widget)
        group.content_layout.addWidget(self.group_comparison_check)
        group.content_layout.addWidget(self.group_comparison_hint)
        group.content_layout.addWidget(self.group_comparison_widget)
        self.paired_figures_check.setChecked(True)
        self.paired_conditions_widget.setVisible(False)
        self.group_comparison_check.setEnabled(False)
        self.group_comparison_widget.setVisible(False)
        return group

    def _build_run_group(self) -> SectionCard:
        group = SectionCard("Run", object_name="publication_maps_run")
        group.setMinimumHeight(SCALP_MAPS_BOTTOM_ROW_MIN_HEIGHT)
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.progress = QProgressBar(group)
        self.progress.setValue(0)
        self.status_label = StatusBanner("Ready.", group)
        self.status_label.setObjectName("publication_maps_status")
        self.run_btn = make_action_button("Run", variant="primary", parent=group)
        self.cancel_btn = make_action_button("Cancel", compact=True, parent=group)
        self.cancel_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._start_run)
        self.cancel_btn.clicked.connect(self._cancel_run)

        row = ActionRow(group, alignment=Qt.AlignLeft)
        row.add_button(self.run_btn)
        row.add_button(self.cancel_btn)
        row.row_layout.addWidget(self.progress, 1)

        self.log_box = QPlainTextEdit(group)
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(100)
        self.log_box.setProperty("logSurface", True)

        group.content_layout.addWidget(self.status_label)
        group.content_layout.addWidget(row)
        group.content_layout.addWidget(self.log_box)
        return group

    def _apply_button_icons(self) -> None:
        style = QApplication.instance().style()
        self.input_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.refresh_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.output_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.open_output_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.run_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.cancel_btn.setIcon(style.standardIcon(QStyle.SP_BrowserStop))

    def _set_default_paths(self) -> None:
        excel_root = self._default_excel_root()
        if excel_root:
            self.input_root_edit.setText(str(excel_root))
        output_root = self._default_output_root()
        if output_root:
            self.output_root_edit.setText(str(output_root))

    def _default_excel_root(self) -> Path | None:
        if not self._project_root:
            return None
        proj = getattr(self._embedded_host(), "currentProject", None)
        subfolders = getattr(proj, "subfolders", {}) if proj is not None else {}
        excel = subfolders.get("excel") if isinstance(subfolders, dict) else None
        if excel:
            path = Path(excel)
            return path if path.is_absolute() else self._project_root / path
        candidate = self._project_root / "1 - Excel Data Files"
        return candidate

    def _default_output_root(self) -> Path | None:
        if not self._project_root:
            return None
        proj = getattr(self._embedded_host(), "currentProject", None)
        results_root = getattr(proj, "results_folder", self._project_root)
        results = Path(results_root)
        if not results.is_absolute():
            results = self._project_root / results
        return results / SCALP_MAPS_OUTPUT_FOLDER

    def _browse_input_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Excel root folder",
            str(self._default_browse_dir()),
        )
        if folder:
            self.input_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._refresh_conditions()

    def _browse_output_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select output folder",
            str(self._default_browse_dir()),
        )
        if folder:
            self.output_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._update_run_state()

    def _default_browse_dir(self) -> Path:
        if self._last_dir and self._last_dir.exists():
            return self._last_dir
        excel_root = self._default_excel_root()
        if excel_root and excel_root.exists():
            return excel_root
        return self._project_root or Path.home()

    def _on_input_root_changed(self, _text: str) -> None:
        self._dataset_index = None
        self._refresh_session_controls(None)
        self._conditions = ()
        self._condition_counts = {}
        self.group_combo.blockSignals(True)
        try:
            self.group_combo.clear()
            self.group_combo.addItem("Refresh to load groups", None)
        finally:
            self.group_combo.blockSignals(False)
            self._sync_group_comparison_labels()
            self._update_all_groups_display_label()
        self.conditions_list.clear()
        self.status_label.set_text(
            "Project data path changed. Refresh project data before running."
        )
        self.status_label.set_variant("info")
        self._update_run_state()

    def _refresh_conditions(self) -> None:
        root_text = self.input_root_edit.text().strip()
        if not root_text:
            self._dataset_index = None
            self._refresh_session_controls(None)
            self._conditions = ()
            self._condition_counts = {}
            self._populate_group_combo()
            self.conditions_list.clear()
            self.status_label.set_text("Select the active project's Excel folder.")
            self.status_label.set_variant("info")
            self._update_run_state()
            return

        try:
            dataset_index = load_project_dataset_index(Path(root_text))
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning(
                "Unable to load the Scalp Maps project dataset index.",
                exc_info=exc,
                extra={
                    "operation": "publication_maps_dataset_index",
                    "input_root": root_text,
                },
            )
            self._dataset_index = None
            self._refresh_session_controls(None, error=str(exc))
            self._conditions = ()
            self._condition_counts = {}
            self._populate_group_combo()
            self.conditions_list.clear()
            self.status_label.set_text(f"Project data could not be loaded: {exc}")
            self.status_label.set_variant("error")
            self._update_run_state()
            return

        active_project_mismatch = False
        if self._project_root is not None:
            try:
                requested_root = Path(root_text).resolve(strict=False)
                active_project_mismatch = (
                    dataset_index.manifest is None
                    or dataset_index.project_root.resolve(strict=False)
                    != self._project_root.resolve(strict=False)
                    or requested_root
                    != dataset_index.excel_root.resolve(strict=False)
                )
            except (OSError, RuntimeError, TypeError, ValueError):
                active_project_mismatch = True
        if active_project_mismatch:
            self._dataset_index = None
            self._refresh_session_controls(
                None,
                error=(
                    "Choose the active project's configured Excel folder."
                ),
            )
            self._conditions = ()
            self._condition_counts = {}
            self._populate_group_combo()
            self.conditions_list.clear()
            self.status_label.set_text(
                "Choose the active project's configured Excel folder. "
                "Unmanaged data and folders from another project cannot be "
                "used while a project is loaded."
            )
            self.status_label.set_variant("error")
            self._update_run_state()
            return

        self._dataset_index = dataset_index
        self._populate_group_combo()
        self._refresh_session_controls(dataset_index)
        self._populate_conditions_from_index()
        self._set_ready_status()
        self._update_run_state()

    def _refresh_session_controls(
        self,
        dataset_index: ProjectDatasetIndex | None,
        *,
        error: str = "",
    ) -> None:
        """Bind session selectors only to canonical project metadata."""

        state = PublicationSessionState(repeated=False)
        if dataset_index is not None:
            try:
                state = publication_session_state(dataset_index)
            except PublicationSessionControlError as exc:
                error = str(exc)
        self._session_state = state
        self._session_control_error = error
        if not hasattr(self, "session_controls_widget"):
            return
        prior_mode = self.session_dimension_combo.currentData()
        prior_single = self.single_session_combo.currentData()
        prior_reference = self.reference_session_combo.currentData()
        prior_comparison = self.comparison_session_combo.currentData()
        combos = (
            self.single_session_combo,
            self.reference_session_combo,
            self.comparison_session_combo,
        )
        self.session_dimension_combo.blockSignals(True)
        for combo in combos:
            combo.blockSignals(True)
        try:
            for combo in combos:
                combo.clear()
                for session in state.sessions:
                    combo.addItem(session.display_label, session.session_id)
            mode = (
                str(prior_mode)
                if prior_mode in {SESSION_MODE_CONDITION, SESSION_MODE_COMPARISON}
                else state.default_mode
            )
            if state.repeated and not self._session_controls_initialized:
                mode = state.default_mode
            mode_index = self.session_dimension_combo.findData(mode)
            self.session_dimension_combo.setCurrentIndex(max(0, mode_index))
            for combo, prior, fallback in (
                (self.single_session_combo, prior_single, 0),
                (self.reference_session_combo, prior_reference, 0),
                (self.comparison_session_combo, prior_comparison, 1),
            ):
                index = combo.findData(prior)
                combo.setCurrentIndex(
                    index if index >= 0 else min(fallback, combo.count() - 1)
                )
        finally:
            self.session_dimension_combo.blockSignals(False)
            for combo in combos:
                combo.blockSignals(False)
        self._session_controls_initialized = (
            self._session_controls_initialized or state.repeated
        )
        self.session_controls_widget.setVisible(state.repeated or bool(error))
        self.session_caveat_label.setText(error or state.caveat)
        self._on_session_mode_changed()

    def _session_mode(self) -> str:
        return str(
            self.session_dimension_combo.currentData() or SESSION_MODE_CONDITION
        )

    def _session_comparison_active(self) -> bool:
        return bool(
            self._session_state.repeated
            and self._session_mode() == SESSION_MODE_COMPARISON
        )

    def _selected_session_ids(self) -> tuple[str, ...]:
        return self._session_state.selected_ids(
            mode=self._session_mode(),
            single_session_id=str(self.single_session_combo.currentData() or ""),
            reference_session_id=str(
                self.reference_session_combo.currentData() or ""
            ),
            comparison_session_id=str(
                self.comparison_session_combo.currentData() or ""
            ),
        )

    def _on_session_mode_changed(self, _index: int | None = None) -> None:
        repeated = self._session_state.repeated
        comparison = self._session_comparison_active()
        self.single_session_label.setVisible(repeated and not comparison)
        self.single_session_combo.setVisible(repeated and not comparison)
        for widget in (
            self.reference_session_label,
            self.reference_session_combo,
            self.comparison_session_label,
            self.comparison_session_combo,
            self.session_difference_check,
        ):
            widget.setVisible(repeated and comparison)
        if comparison:
            all_index = self.group_combo.findData(ALL_GROUPS_VALUE)
            if all_index >= 0:
                self.group_combo.blockSignals(True)
                self.group_combo.setCurrentIndex(all_index)
                self.group_combo.blockSignals(False)
            if self.paired_figures_check.isChecked():
                self.paired_figures_check.setChecked(False)
            if self.group_comparison_check.isChecked():
                self.group_comparison_check.setChecked(False)
            self._enforce_single_session_condition()
        self.group_combo.setEnabled(not comparison and not self._busy)
        self._update_paired_controls_state()
        self._update_group_comparison_controls_state()
        if self._dataset_index is not None:
            self._populate_conditions_from_index()
            self._set_ready_status()
        self._update_run_state()

    def _enforce_single_session_condition(self) -> None:
        if not self._session_comparison_active() or self.conditions_list.count() == 0:
            return
        selected = [
            index
            for index in range(self.conditions_list.count())
            if self.conditions_list.item(index).checkState() == Qt.Checked
        ]
        keep = selected[-1] if selected else 0
        self.conditions_list.blockSignals(True)
        try:
            for index in range(self.conditions_list.count()):
                self.conditions_list.item(index).setCheckState(
                    Qt.Checked if index == keep else Qt.Unchecked
                )
        finally:
            self.conditions_list.blockSignals(False)

    def _on_condition_item_changed(self, item: QListWidgetItem) -> None:
        if self._session_comparison_active() and item.checkState() == Qt.Checked:
            self.conditions_list.blockSignals(True)
            try:
                for index in range(self.conditions_list.count()):
                    other = self.conditions_list.item(index)
                    if other is not item:
                        other.setCheckState(Qt.Unchecked)
            finally:
                self.conditions_list.blockSignals(False)
        self._update_run_state()

    def _session_selection_valid(self) -> bool:
        if self._session_control_error:
            return False
        if not self._session_state.repeated:
            return True
        try:
            session_ids = self._selected_session_ids()
        except PublicationSessionControlError:
            return False
        if not self._session_comparison_active():
            return len(session_ids) == 1
        dataset_index = self._dataset_index
        selected_conditions = self._selected_conditions()
        if (
            dataset_index is None
            or len(dataset_index.ordered_groups) != 2
            or len(selected_conditions) != 1
            or len(session_ids) != 2
        ):
            return False
        records = dataset_index.select(
            conditions=selected_conditions,
            group_ids=tuple(group.group_id for group in dataset_index.ordered_groups),
            session_ids=session_ids,
        )
        cells = {
            (str(record.group_id).casefold(), str(record.session_id).casefold())
            for record in records
        }
        return all(
            (group.group_id.casefold(), session_id.casefold()) in cells
            for group in dataset_index.ordered_groups
            for session_id in session_ids
        )

    def _set_ready_status(self) -> None:
        output_root_error = self._output_root_validation_error()
        if output_root_error is not None:
            self.status_label.set_text(output_root_error)
            self.status_label.set_variant("error")
            return
        if self._session_control_error:
            self.status_label.set_text(self._session_control_error)
            self.status_label.set_variant("error")
            return
        if self._session_state.repeated and not self._session_selection_valid():
            self.status_label.set_text(
                "Choose a valid canonical session selection. Session grids require "
                "one condition and data in every group × session cell."
            )
            self.status_label.set_variant("warning")
            return
        if self._session_comparison_active() and self._session_selection_valid():
            sessions = self._selected_session_ids()
            labels = {
                session.session_id: session.display_label
                for session in self._session_state.sessions
            }
            condition = self._selected_conditions()[0]
            self.status_label.set_text(
                f"Session grid ready for {condition}: {labels[sessions[0]]} vs "
                f"{labels[sessions[1]]}. Participant and paired N will be shown; "
                "interpret the fixed-order difference descriptively."
            )
            self.status_label.set_variant("info")
            return
        if (
            hasattr(self, "group_comparison_check")
            and self.group_comparison_check.isChecked()
            and self._group_comparison_valid()
        ):
            condition = self._selected_conditions()[0]
            self.status_label.set_text(
                f"Two-group comparison ready for {condition}: "
                f"{self.group_comparison_a_label.text()} vs "
                f"{self.group_comparison_b_label.text()}. Only the descriptive "
                "comparison figure will be generated."
            )
            self.status_label.set_variant("info")
            return
        workbook_count = len(self._scoped_records())
        group_count = len(self._request_groups())
        self.status_label.set_text(
            f"Ready: {workbook_count} indexed workbook(s) across "
            f"{group_count} output group(s)."
        )
        self.status_label.set_variant("info")

    def _populate_group_combo(self) -> None:
        previous = self.group_combo.currentData()
        dataset_index = self._dataset_index
        self.group_combo.blockSignals(True)
        try:
            self.group_combo.clear()
            if dataset_index is None:
                self.group_combo.addItem("No project data loaded", None)
                return
            groups = dataset_index.ordered_groups
            if not groups:
                self.group_combo.addItem("Ungrouped dataset", None)
                return
            label_counts: dict[str, int] = {}
            for group in groups:
                key = group.label.casefold()
                label_counts[key] = label_counts.get(key, 0) + 1
            if len(groups) > 1:
                self.group_combo.addItem(ALL_GROUPS_LABEL, ALL_GROUPS_VALUE)
            for group in groups:
                display = group.label
                if label_counts[group.label.casefold()] > 1:
                    display = f"{group.label} ({group.group_id})"
                self.group_combo.addItem(display, group.group_id)
            previous_index = self.group_combo.findData(previous)
            self.group_combo.setCurrentIndex(
                previous_index if previous_index >= 0 else 0
            )
        finally:
            self.group_combo.blockSignals(False)
            self._sync_group_comparison_labels()
            self._update_all_groups_display_label()

    def _on_group_selection_changed(self) -> None:
        if self._dataset_index is None:
            self._update_run_state()
            return
        if self._session_comparison_active():
            all_index = self.group_combo.findData(ALL_GROUPS_VALUE)
            if all_index >= 0 and self.group_combo.currentIndex() != all_index:
                self.group_combo.setCurrentIndex(all_index)
                return
        self._populate_conditions_from_index()
        self._set_ready_status()
        self._update_run_state()

    def _request_groups(self) -> tuple[GroupInfo | None, ...]:
        dataset_index = self._dataset_index
        if dataset_index is None:
            return ()
        groups = dataset_index.ordered_groups
        if not groups:
            return (None,)
        selected = self.group_combo.currentData()
        if selected == ALL_GROUPS_VALUE:
            return groups
        group = dataset_index.groups.get(str(selected))
        return (group,) if group is not None else ()

    def _scoped_records(self) -> tuple[object, ...]:
        dataset_index = self._dataset_index
        if dataset_index is None:
            return ()
        groups = self._request_groups()
        group_ids = tuple(group.group_id for group in groups if group is not None)
        try:
            session_ids = self._selected_session_ids()
        except PublicationSessionControlError:
            session_ids = ()
        if group_ids:
            return dataset_index.select(
                group_ids=group_ids,
                session_ids=session_ids or None,
            )
        return dataset_index.select(session_ids=session_ids or None)

    def _populate_conditions_from_index(self) -> None:
        previously_checked = set(self._selected_conditions())
        had_conditions = self.conditions_list.count() > 0
        counts: dict[str, int] = {}
        for record in self._scoped_records():
            condition = str(record.condition)
            counts[condition] = counts.get(condition, 0) + 1
        self._conditions = tuple(sorted(counts, key=str.casefold))
        self._condition_counts = counts
        self.conditions_list.blockSignals(True)
        try:
            self.conditions_list.clear()
            for condition in self._conditions:
                item = QListWidgetItem(f"{condition} ({counts[condition]})")
                item.setData(Qt.UserRole, condition)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.Checked
                    if not had_conditions or condition in previously_checked
                    else Qt.Unchecked
                )
                self.conditions_list.addItem(item)
        finally:
            self.conditions_list.blockSignals(False)
        self._enforce_single_session_condition()
        if (
            not had_conditions
            and not self._session_comparison_active()
            and len(self._selected_conditions()) >= 2
        ):
            # Construction briefly has no indexed conditions and disables the
            # paired default. Restore it when the first canonical cohort loads.
            self.paired_figures_check.setChecked(True)
        self._sync_paired_condition_selectors()
        self._update_condition_summary()

    def _set_all_conditions(self, checked: bool) -> None:
        self.conditions_list.blockSignals(True)
        try:
            for index in range(self.conditions_list.count()):
                item = self.conditions_list.item(index)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        finally:
            self.conditions_list.blockSignals(False)
        self._enforce_single_session_condition()
        self._sync_paired_condition_selectors()
        self._update_condition_summary()
        self._update_run_state()

    def _selected_conditions(self) -> tuple[str, ...]:
        selected: list[str] = []
        for index in range(self.conditions_list.count()):
            item = self.conditions_list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(str(item.data(Qt.UserRole)))
        return tuple(selected)

    def _selected_metrics(self) -> tuple[PublicationMetric, ...]:
        selected: list[PublicationMetric] = []
        if self.metric_bca_check.isChecked():
            selected.append(PublicationMetric.BCA)
        if self.metric_snr_check.isChecked():
            selected.append(PublicationMetric.SNR)
        if self.metric_z_check.isChecked():
            selected.append(PublicationMetric.Z_SCORE)
        return tuple(selected)

    def _update_condition_summary(self) -> None:
        selected_conditions = self._selected_conditions()
        total_files = sum(
            self._condition_counts.get(condition, 0)
            for condition in selected_conditions
        )
        self.conditions_summary.setText(
            f"Selected conditions: {len(selected_conditions)} | "
            f"Indexed workbooks: {total_files}"
        )
        if hasattr(self, "paired_figures_check"):
            self._sync_paired_condition_selectors(selected_conditions)
            if (
                self._session_comparison_active()
                or len(selected_conditions) < 2
            ) and self.paired_figures_check.isChecked():
                self.paired_figures_check.setChecked(False)
            self.paired_figures_check.setEnabled(
                not self._session_comparison_active()
                and len(selected_conditions) >= 2
                and not self._busy
            )
            self._update_paired_controls_state()
        if hasattr(self, "group_comparison_check"):
            self._update_group_comparison_controls_state()

    def _update_run_state(self) -> None:
        self._refresh_analysis_setting_labels()
        self._update_condition_summary()
        ready = bool(self.input_root_edit.text().strip())
        ready = ready and bool(self.output_root_edit.text().strip())
        ready = ready and self._dataset_index is not None
        ready = ready and bool(self._request_groups())
        ready = ready and bool(self._selected_conditions())
        ready = ready and bool(self._selected_metrics())
        ready = ready and self._paired_conditions_valid()
        ready = ready and self._group_comparison_valid()
        ready = ready and self._session_selection_valid()
        ready = ready and self._output_root_validation_error() is None
        self.run_btn.setEnabled(ready and self._thread is None and not self._busy)

    def _on_output_root_changed(self, _text: str) -> None:
        validation_error = self._output_root_validation_error()
        if validation_error is not None:
            self.status_label.set_text(validation_error)
            self.status_label.set_variant("error")
        elif self._dataset_index is not None:
            self._set_ready_status()
        self._update_run_state()

    def _output_root_validation_error(self) -> str | None:
        input_text = self.input_root_edit.text().strip()
        output_text = self.output_root_edit.text().strip()
        if not input_text or not output_text:
            return None
        request = PublicationMapRequest(
            input_root=Path(input_text),
            output_root=Path(output_text),
            conditions=(),
        )
        try:
            validate_output_root(request)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            return str(exc)
        return None

    def _sync_paired_condition_selectors(
        self,
        selected_conditions: tuple[str, ...] | None = None,
    ) -> None:
        if not hasattr(self, "paired_condition_a_combo"):
            return
        if selected_conditions is None:
            selected_conditions = self._selected_conditions()

        previous_a = self.paired_condition_a_combo.currentText()
        previous_b = self.paired_condition_b_combo.currentText()
        self.paired_condition_a_combo.blockSignals(True)
        self.paired_condition_b_combo.blockSignals(True)
        try:
            self.paired_condition_a_combo.clear()
            self.paired_condition_b_combo.clear()
            self.paired_condition_a_combo.addItems(selected_conditions)
            self.paired_condition_b_combo.addItems(selected_conditions)
            if previous_a in selected_conditions:
                self.paired_condition_a_combo.setCurrentText(previous_a)
            elif selected_conditions:
                self.paired_condition_a_combo.setCurrentIndex(0)
            if previous_b in selected_conditions and previous_b != self.paired_condition_a_combo.currentText():
                self.paired_condition_b_combo.setCurrentText(previous_b)
            elif len(selected_conditions) > 1:
                default_b = 1 if self.paired_condition_a_combo.currentIndex() == 0 else 0
                self.paired_condition_b_combo.setCurrentIndex(default_b)
            elif selected_conditions:
                self.paired_condition_b_combo.setCurrentIndex(0)
        finally:
            self.paired_condition_a_combo.blockSignals(False)
            self.paired_condition_b_combo.blockSignals(False)

    def _update_paired_controls_state(self) -> None:
        if not hasattr(self, "paired_conditions_widget"):
            return
        selected_count = len(self._selected_conditions())
        checked = self.paired_figures_check.isChecked()
        enabled = checked and selected_count >= 2 and not self._busy
        self.paired_conditions_widget.setVisible(
            checked and not self._session_comparison_active()
        )
        self.paired_condition_a_combo.setEnabled(enabled)
        self.paired_condition_b_combo.setEnabled(enabled)

    def _on_paired_figures_toggled(self, checked: bool) -> None:
        if checked and self._session_comparison_active():
            self.paired_figures_check.setChecked(False)
            return
        if checked and self.group_comparison_check.isChecked():
            self.group_comparison_check.setChecked(False)
        self._update_paired_controls_state()
        self._update_group_comparison_controls_state()
        if hasattr(self, "run_btn"):
            self._update_run_state()

    def _sync_group_comparison_labels(self) -> None:
        if not hasattr(self, "group_comparison_a_label"):
            return
        groups = (
            self._dataset_index.ordered_groups
            if self._dataset_index is not None
            else ()
        )
        if len(groups) != 2:
            for label in (
                self.group_comparison_a_label,
                self.group_comparison_b_label,
            ):
                label.setText("—")
                label.setToolTip("")
            return

        label_counts: dict[str, int] = {}
        for group in groups:
            key = group.label.casefold()
            label_counts[key] = label_counts.get(key, 0) + 1
        for label_widget, group in zip(
            (
                self.group_comparison_a_label,
                self.group_comparison_b_label,
            ),
            groups,
        ):
            display = group.label
            if label_counts[group.label.casefold()] > 1:
                display = f"{group.label} ({group.group_id})"
            label_widget.setText(display)
            label_widget.setToolTip(f"Canonical group ID: {group.group_id}")

    def _update_all_groups_display_label(self) -> None:
        if not hasattr(self, "group_combo"):
            return
        all_groups_index = self.group_combo.findData(ALL_GROUPS_VALUE)
        if all_groups_index < 0:
            self.group_combo.setToolTip(ALL_GROUPS_TOOLTIP)
            return
        comparison_enabled = bool(
            hasattr(self, "group_comparison_check")
            and self.group_comparison_check.isChecked()
        )
        self.group_combo.setItemText(
            all_groups_index,
            (
                ALL_GROUPS_COMPARISON_LABEL
                if comparison_enabled
                else ALL_GROUPS_LABEL
            ),
        )
        self.group_combo.setToolTip(
            ALL_GROUPS_COMPARISON_TOOLTIP
            if comparison_enabled
            else ALL_GROUPS_TOOLTIP
        )

    def _group_comparison_available(self) -> bool:
        if self._dataset_index is None:
            return False
        if self._session_comparison_active():
            return False
        return bool(
            len(self._dataset_index.ordered_groups) == 2
            and self.group_combo.currentData() == ALL_GROUPS_VALUE
            and len(self._selected_conditions()) == 1
            and self._selected_condition_covers_comparison_groups()
            and not self.paired_figures_check.isChecked()
        )

    def _selected_condition_covers_comparison_groups(self) -> bool:
        dataset_index = self._dataset_index
        selected_conditions = self._selected_conditions()
        if dataset_index is None or len(selected_conditions) != 1:
            return False
        groups = dataset_index.ordered_groups
        if len(groups) != 2:
            return False
        condition = selected_conditions[0]
        return all(
            bool(
                dataset_index.select(
                    conditions=(condition,),
                    group_ids=(group.group_id,),
                )
            )
            for group in groups
        )

    def _update_group_comparison_controls_state(self) -> None:
        if not hasattr(self, "group_comparison_check"):
            return
        self._sync_group_comparison_labels()
        available = self._group_comparison_available()
        if self.group_comparison_check.isChecked() and not available:
            self.group_comparison_check.setChecked(False)
        checked = self.group_comparison_check.isChecked()
        self.group_comparison_check.setEnabled(available and not self._busy)
        self.group_comparison_widget.setVisible(checked)

    def _on_group_comparison_toggled(self, checked: bool) -> None:
        if checked and not self._group_comparison_available():
            self.group_comparison_check.setChecked(False)
            return
        if checked and self.paired_figures_check.isChecked():
            self.paired_figures_check.setChecked(False)
        self._update_all_groups_display_label()
        self.group_comparison_widget.setVisible(checked)
        if self._dataset_index is not None:
            self._set_ready_status()
        self._update_paired_controls_state()
        self._update_run_state()

    def _group_comparison_valid(self) -> bool:
        if not hasattr(self, "group_comparison_check"):
            return True
        if not self.group_comparison_check.isChecked():
            return True
        groups = self._request_groups()
        group_ids = tuple(
            group.group_id for group in groups if group is not None
        )
        return bool(
            self._group_comparison_available()
            and len(groups) == 2
            and len(group_ids) == 2
            and len(set(group_id.casefold() for group_id in group_ids)) == 2
        )

    def _selected_paired_conditions(self) -> tuple[str, ...]:
        if not hasattr(self, "paired_condition_a_combo"):
            return ()
        first = self.paired_condition_a_combo.currentText().strip()
        second = self.paired_condition_b_combo.currentText().strip()
        if first and second:
            return (first, second)
        return ()

    def _paired_conditions_valid(self) -> bool:
        if not hasattr(self, "paired_figures_check") or not self.paired_figures_check.isChecked():
            return True
        first, second = (*self._selected_paired_conditions(), "", "")[:2]
        selected = set(self._selected_conditions())
        return bool(first and second and first != second and first in selected and second in selected)

    def _settings_manager(self):
        host = self._embedded_host()
        manager = getattr(host, "settings", None)
        if manager is not None and hasattr(manager, "get"):
            return manager
        parent = self.parent()
        manager = getattr(parent, "settings", None)
        if manager is not None and hasattr(manager, "get"):
            return manager
        if self._settings_fallback is None:
            self._settings_fallback = SettingsManager()
        return self._settings_fallback

    def _analysis_setting_float(self, key: str, fallback: float) -> float:
        manager = self._settings_manager()
        try:
            return float(manager.get("analysis", key, str(fallback)))
        except (TypeError, ValueError):
            return float(fallback)

    def _analysis_base_frequency_hz(self) -> float:
        return self._analysis_setting_float("base_freq", 6.0)

    def _analysis_bca_upper_limit_hz(self) -> float:
        return self._analysis_setting_float(
            "bca_upper_limit",
            float(config.DEFAULT_BCA_UPPER_LIMIT),
        )

    def _refresh_analysis_setting_labels(self) -> None:
        if not hasattr(self, "base_freq_value"):
            return
        self.base_freq_value.setText(f"{self._analysis_base_frequency_hz():g} Hz")
        self.bca_limit_value.setText(f"{self._analysis_bca_upper_limit_hz():g} Hz")

    def _apply_bca_color_button_styles(self) -> None:
        self.color_low_btn.setStyleSheet(f"background-color: {self.bca_low_color};")
        self.color_high_btn.setStyleSheet(f"background-color: {self.bca_high_color};")

    def _choose_bca_color(self, which: str) -> None:
        init = self.bca_low_color if which == "low" else self.bca_high_color
        color = QColorDialog.getColor(QColor(init), self)
        if not color.isValid():
            return
        if which == "low":
            self.bca_low_color = color.name()
        else:
            self.bca_high_color = color.name()
        self._apply_bca_color_button_styles()

    def _on_metric_selection_changed(self) -> None:
        self._toggle_metric_range_controls()
        self._update_run_state()

    def _toggle_metric_range_controls(self) -> None:
        bca_selected = self.metric_bca_check.isChecked()
        snr_selected = self.metric_snr_check.isChecked()
        z_selected = self.metric_z_check.isChecked()
        bca_fixed_enabled = bca_selected and not self._busy
        snr_fixed_enabled = snr_selected and not self._busy
        self.fixed_bca_range_check.setEnabled(bca_fixed_enabled)
        self.fixed_snr_range_check.setEnabled(snr_fixed_enabled)
        self.bca_vmin_spin.setEnabled(
            bca_fixed_enabled and self.fixed_bca_range_check.isChecked()
        )
        self.bca_vmax_spin.setEnabled(
            bca_fixed_enabled and self.fixed_bca_range_check.isChecked()
        )
        self.snr_vmin_spin.setEnabled(
            snr_fixed_enabled and self.fixed_snr_range_check.isChecked()
        )
        self.snr_vmax_spin.setEnabled(
            snr_fixed_enabled and self.fixed_snr_range_check.isChecked()
        )
        self.z_threshold_spin.setEnabled(z_selected and not self._busy)

    def _fixed_bca_range_is_valid(self) -> bool:
        return float(self.bca_vmax_spin.value()) > float(self.bca_vmin_spin.value())

    def _fixed_snr_range_is_valid(self) -> bool:
        return float(self.snr_vmax_spin.value()) > float(self.snr_vmin_spin.value())

    def _lockable_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.input_root_row,
            self.group_combo,
            self.refresh_btn,
            self.conditions_list,
            self.select_all_btn,
            self.select_none_btn,
            self.metric_bca_check,
            self.metric_snr_check,
            self.metric_z_check,
            self.color_low_btn,
            self.color_high_btn,
            self.fixed_bca_range_check,
            self.bca_vmin_spin,
            self.bca_vmax_spin,
            self.fixed_snr_range_check,
            self.snr_vmin_spin,
            self.snr_vmax_spin,
            self.z_threshold_spin,
            self.output_root_row,
            self.paired_figures_check,
            self.paired_condition_a_combo,
            self.paired_condition_b_combo,
            self.group_comparison_check,
            self.session_dimension_combo,
            self.single_session_combo,
            self.reference_session_combo,
            self.comparison_session_combo,
            self.session_difference_check,
        )

    def _embedded_host(self) -> QWidget | None:
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "sidebar") and callable(getattr(parent, "menuBar", None)):
                return parent
            parent = parent.parent()
        return None

    def _set_host_navigation_locked(self, locked: bool) -> None:
        if locked == self._host_navigation_locked:
            return

        host = self._embedded_host()
        if host is None:
            self._host_navigation_locked = False
            return

        from Main_App.gui.shell_status import _set_processing_navigation_locked

        if locked:
            if getattr(host, "_processing_navigation_states", None):
                self._host_navigation_locked = False
                return
            _set_processing_navigation_locked(host, True)
            self._host_navigation_locked = True
            return

        if self._host_navigation_locked:
            _set_processing_navigation_locked(host, False)
        self._host_navigation_locked = False

    def _set_busy_state(self, busy: bool) -> None:
        self._busy = busy
        self.setProperty("publicationMapsBusy", busy)
        self._set_host_navigation_locked(busy)
        for widget in self._lockable_widgets():
            widget.setEnabled(not busy)

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(busy)
        self._toggle_metric_range_controls()
        self._update_paired_controls_state()
        self._update_group_comparison_controls_state()
        if self._session_comparison_active():
            self.group_combo.setEnabled(False)

        if not busy:
            self._update_run_state()

    def _collect_requests(self) -> tuple[PublicationMapRequest, ...]:
        self._refresh_analysis_setting_labels()
        metrics = self._selected_metrics()
        color_bounds: dict[PublicationMetric, ColorBounds] = {}
        if PublicationMetric.BCA in metrics:
            use_fixed_bca_range = self.fixed_bca_range_check.isChecked()
            color_bounds[PublicationMetric.BCA] = ColorBounds(
                auto_scale=not use_fixed_bca_range,
                vmin=float(self.bca_vmin_spin.value()) if use_fixed_bca_range else None,
                vmax=float(self.bca_vmax_spin.value()) if use_fixed_bca_range else None,
                low_color=self.bca_low_color,
                high_color=self.bca_high_color,
            )
        if PublicationMetric.SNR in metrics:
            use_fixed_snr_range = self.fixed_snr_range_check.isChecked()
            color_bounds[PublicationMetric.SNR] = ColorBounds(
                auto_scale=not use_fixed_snr_range,
                vmin=float(self.snr_vmin_spin.value()) if use_fixed_snr_range else None,
                vmax=float(self.snr_vmax_spin.value()) if use_fixed_snr_range else None,
                low_color=self.bca_low_color,
                high_color=self.bca_high_color,
            )
        if PublicationMetric.Z_SCORE in metrics:
            color_bounds[PublicationMetric.Z_SCORE] = ColorBounds(
                auto_scale=True,
                vmin=float(self.z_threshold_spin.value()),
                vmax=None,
                low_color=self.bca_low_color,
                high_color=self.bca_high_color,
            )
        selected_conditions = self._selected_conditions()
        selected_session_ids = self._selected_session_ids()
        session_grid_enabled = self._session_comparison_active()
        paired_enabled = (
            self.paired_figures_check.isChecked()
            and len(selected_conditions) >= 2
            and self._paired_conditions_valid()
        )
        comparison_enabled = (
            self.group_comparison_check.isChecked()
            and self._group_comparison_valid()
        )
        groups = self._request_groups()
        comparison_group_ids = (
            tuple(
                group.group_id
                for group in groups
                if group is not None
            )
            if comparison_enabled
            else ()
        )
        return tuple(
            PublicationMapRequest(
                input_root=Path(self.input_root_edit.text().strip()),
                output_root=Path(self.output_root_edit.text().strip()),
                conditions=selected_conditions,
                metrics=metrics,
                color_bounds=color_bounds,
                export_png=True,
                export_pdf=True,
                export_paired_figures=paired_enabled,
                paired_conditions=(
                    self._selected_paired_conditions() if paired_enabled else ()
                ),
                export_group_comparison_figure=comparison_enabled,
                group_comparison_ids=comparison_group_ids,
                project_root=self._project_root,
                group_id=None if group is None else group.group_id,
                group_label=None if group is None else group.label,
                group_folder=None if group is None else group.folder_name,
                session_ids=selected_session_ids,
                export_session_grid_figure=session_grid_enabled,
                session_comparison_ids=(
                    selected_session_ids if session_grid_enabled else ()
                ),
                export_paired_session_difference=(
                    session_grid_enabled
                    and self.session_difference_check.isChecked()
                ),
            )
            for group in groups
        )

    def _start_run(self) -> None:
        if self.has_active_generation():
            return
        if not self._selected_conditions():
            self._show_validation_error("Select at least one condition.")
            return
        selected_metrics = self._selected_metrics()
        if not selected_metrics:
            self._show_validation_error("Select at least one metric.")
            return
        if (
            PublicationMetric.BCA in selected_metrics
            and self.fixed_bca_range_check.isChecked()
            and not self._fixed_bca_range_is_valid()
        ):
            self._show_validation_error(
                "The upper BCA range limit must be greater than the lower limit.",
            )
            return
        if (
            PublicationMetric.SNR in selected_metrics
            and self.fixed_snr_range_check.isChecked()
            and not self._fixed_snr_range_is_valid()
        ):
            self._show_validation_error(
                "The upper SNR range limit must be greater than the lower limit.",
            )
            return
        if self.paired_figures_check.isChecked() and not self._paired_conditions_valid():
            self._show_validation_error(
                "Select two different checked conditions for the paired scalp-map figure.",
            )
            return
        if (
            self.group_comparison_check.isChecked()
            and not self._group_comparison_valid()
        ):
            self._show_validation_error(
                "A two-group comparison requires All groups, exactly two canonical "
                "groups, and exactly one checked condition with active workbooks "
                "in both groups."
            )
            return
        if not self._session_selection_valid():
            message = self._session_control_error or (
                "Session comparison requires one condition, two distinct canonical "
                "sessions, exactly two stable groups, and data in every group × session cell."
            )
            self._show_validation_error(message)
            return
        requests = self._collect_requests()
        if not requests:
            self._show_validation_error(
                "Refresh project data and select a canonical group before running."
            )
            return
        output_root_error = self._output_root_validation_error()
        if output_root_error is not None:
            self._show_validation_error(output_root_error)
            return
        self._last_generated_figure_count = 0
        self._pending_outcome = None
        self._cancel_requested = False
        self._last_run_was_session_grid = self._session_comparison_active()
        self.log_box.clear()
        self.progress.setValue(0)
        start_label = (
            "repeated-session grid"
            if self._last_run_was_session_grid
            else "group-scoped generation"
        )
        self.status_label.set_text(
            f"Starting {start_label} ({len(requests)} request(s))..."
        )
        self.status_label.set_variant("info")

        self._thread = QThread()
        self._worker = PublicationMapsWorker(requests)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.message.connect(self._append_log)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.finished.connect(self._thread.deleteLater)
        self._set_busy_state(True)
        self._thread.start()

    def _cancel_run(self) -> None:
        if not self.has_active_generation() or self._cancel_requested:
            return
        self._cancel_requested = True
        if self._worker is not None:
            try:
                self._worker.cancel()
            except RuntimeError:
                logger.debug(
                    "Scalp Maps worker was released during cancellation.",
                    exc_info=True,
                )
        self.cancel_btn.setEnabled(False)
        self.status_label.set_variant("warning")
        self._append_log(
            "Cancellation requested; waiting for the active worker to stop."
        )

    def has_active_generation(self) -> bool:
        """Return whether this page still owns an unfinished worker lifecycle."""

        return self._worker is not None or self._thread is not None

    def shutdown(self) -> bool:
        """Request cancellation and report whether destruction must be deferred."""

        if not self.has_active_generation():
            return False
        self._cancel_run()
        return True

    def _show_validation_error(self, message: str) -> None:
        self.status_label.set_text(message)
        self.status_label.set_variant("error")
        self._append_log(message, update_status=False)

    def _append_log(self, message: str, *, update_status: bool = True) -> None:
        self.log_box.appendPlainText(message)
        if update_status:
            self.status_label.set_text(message)

    def _on_worker_finished(self, outcome: object) -> None:
        if isinstance(outcome, PublicationMapsWorkerOutcome):
            self._pending_outcome = outcome
            return
        self._pending_outcome = PublicationMapsWorkerOutcome.error(
            "Scalp Maps returned an invalid worker outcome."
        )

    def _cleanup_worker(self) -> None:
        worker = self._worker
        outcome = self._pending_outcome
        if outcome is None and worker is not None:
            candidate = getattr(worker, "outcome", None)
            if isinstance(candidate, PublicationMapsWorkerOutcome):
                outcome = candidate
        self._worker = None
        self._thread = None
        self._pending_outcome = None
        self._set_busy_state(False)
        if outcome is None:
            outcome = PublicationMapsWorkerOutcome.error(
                "The Scalp Maps worker exited without a terminal outcome."
            )
        self._handle_worker_outcome(outcome)
        self._last_run_was_session_grid = False
        self._cancel_requested = False
        self._last_generated_figure_count = 0
        self.generation_idle.emit()

    def _handle_worker_outcome(
        self,
        outcome: PublicationMapsWorkerOutcome,
    ) -> None:
        if outcome.status is PublicationMapsOutcomeStatus.CANCELLED:
            self.status_label.set_text("Generation cancelled. No new output was published.")
            self.status_label.set_variant("warning")
            self._append_log(
                "Generation cancelled. No new output was published.",
                update_status=False,
            )
            return
        if outcome.status is PublicationMapsOutcomeStatus.POST_PROCESSING_REQUIRED:
            reason = outcome.message or "Saved post-processing outputs are missing or stale."
            self.status_label.set_text(
                "Post-processing is required before scalp maps can be generated."
            )
            self.status_label.set_variant("warning")
            self._append_log(
                f"Post-processing required: {reason}",
                update_status=False,
            )
            if outcome.project_root:
                self.post_processing_required.emit(
                    "Scalp Maps",
                    reason,
                    outcome.project_root,
                )
            else:
                show_error(
                    self,
                    "Scalp Maps error",
                    "Load the affected project before rerunning post-processing.",
                )
            return
        if outcome.status is PublicationMapsOutcomeStatus.ERROR:
            message = outcome.message or "Scalp-map generation failed."
            self.status_label.set_text(message)
            self.status_label.set_variant("error")
            self._append_log(message, update_status=False)
            show_error(self, "Scalp Maps error", message)
            return

        for result in outcome.results:
            group_label = getattr(result, "group_label", None)
            group_prefix = f"[{group_label}] " if group_label else ""
            for diagnostic in getattr(result, "diagnostics", []):
                detail = f" ({diagnostic.detail})" if diagnostic.detail else ""
                prefix = f"[{diagnostic.level}]"
                location = " ".join(
                    part
                    for part in (diagnostic.condition, diagnostic.workbook)
                    if part
                )
                self._append_log(
                    f"{group_prefix}{prefix} {location} "
                    f"{diagnostic.message}{detail}".strip(),
                    update_status=False,
                )
            figure_paths = list(getattr(result, "figure_paths", []))
            self._last_generated_figure_count += len(figure_paths)
            for path in figure_paths:
                self._append_log(
                    f"{group_prefix}Figure: {path}",
                    update_status=False,
                )

        batch_figure_paths = tuple(
            getattr(outcome, "batch_figure_paths", ()) or ()
        )
        self._last_generated_figure_count += len(batch_figure_paths)
        for path in batch_figure_paths:
            self._append_log(
                (
                    f"Session-grid figure: {path}"
                    if self._last_run_was_session_grid
                    else f"Comparison figure: {path}"
                ),
                update_status=False,
            )

        self.progress.setValue(100)
        if self._last_generated_figure_count <= 0:
            message = "Scalp Maps completed without publishing any figure files."
            self.status_label.set_text(message)
            self.status_label.set_variant("error")
            self._append_log(message, update_status=False)
            show_error(self, "Scalp Maps error", message)
            return
        group_count = len(outcome.results)
        if batch_figure_paths and self._last_run_was_session_grid:
            self.status_label.set_text(
                f"Complete: {self._last_generated_figure_count} repeated-session "
                f"figure file(s) with participant N and paired N for "
                f"{group_count} canonical groups."
            )
        elif batch_figure_paths:
            self.status_label.set_text(
                f"Complete: {self._last_generated_figure_count} comparison figure "
                f"file(s) for {group_count} canonical groups."
            )
        else:
            self.status_label.set_text(
                f"Complete: {self._last_generated_figure_count} figure file(s) "
                f"for {group_count} group output(s)."
            )
        self.status_label.set_variant("success")
        self._prompt_open_output_folder()

    def _prompt_open_output_folder(self) -> None:
        if confirm(
            self,
            "Finished",
            "Plots have been successfully generated. View plots?",
        ):
            self._open_output_folder()

    def _open_output_folder(self) -> None:
        path = self.output_root_edit.text().strip()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

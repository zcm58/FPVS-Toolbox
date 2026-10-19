"""Optional QC and beta-tool controls for Settings.

Builders populate the existing SettingsDialog and connect its workflow methods.
The dialog retains draft validation, persistence, and background-work ownership.
"""

from __future__ import annotations

from Main_App.gui import settings_experimental_preprocessing_page

from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QHBoxLayout,
    QTabWidget,
    QGridLayout,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
)
from Main_App.gui.components import (
    SectionCard,
    SubsectionHeaderLabel,
)
from Main_App.gui.components import make_info_button
from Main_App.projects import (
    ExperimentalQcSettings,
    SUMMED_BCA_SCREENING_BRIEF_TEXT,
)
from Main_App.projects.preprocessing_settings import (
    PREPROCESSING_DEFAULTS,
    normalize_preprocessing_settings,
)


def build_experimental_page(self, tabs: QTabWidget) -> QWidget:
    tab = QWidget()
    tab.setObjectName("settings_experimental_tab")
    layout = QVBoxLayout(tab)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    self._add_experimental_info_row(
        layout, tab,
        "Optional checks for this project. New projects start with QC off.",
        "About experimental QC",
        "Turn each check on or off independently. Related repair options stay "
        "with the check they need. Turning a check off keeps saved choices and "
        "accepted repairs. Basic checks for valid data, stimulus timing, complete "
        "outputs, and required electrodes still run so results remain usable.",
        "settings_experimental_qc_info",
    )

    # Keep preprocessing and post-processing checks in separate flat pages.
    self.experimental_tabs = QTabWidget(tab)
    self.experimental_tabs.setObjectName("settings_experimental_sections")
    self.experimental_tabs.setDocumentMode(True)
    self.experimental_tabs.tabBar().setDrawBase(False)
    layout.addWidget(self.experimental_tabs, 1)

    self.preprocessing_qc_tabs = QTabWidget(tab)
    self.preprocessing_qc_tabs.setObjectName("settings_preprocessing_qc_sections")
    self.preprocessing_qc_tabs.setDocumentMode(True)
    self.preprocessing_qc_tabs.tabBar().setDrawBase(False)
    self.experimental_tabs.addTab(self.preprocessing_qc_tabs, "Preprocessing QC")

    signals_page = QWidget()
    signals_page.setObjectName("settings_experimental_signals_page")
    signals_layout = QVBoxLayout(signals_page)
    signals_layout.setContentsMargins(0, 12, 0, 0)
    signals_layout.setSpacing(10)
    self.preprocessing_qc_tabs.addTab(signals_page, "Signals")

    electrodes_page = QWidget()
    electrodes_page.setObjectName("settings_experimental_electrodes_page")
    electrodes_layout = QVBoxLayout(electrodes_page)
    electrodes_layout.setContentsMargins(0, 12, 0, 0)
    electrodes_layout.setSpacing(10)
    self.preprocessing_qc_tabs.addTab(electrodes_page, "Electrodes")

    raw_spectral_page = QWidget()
    raw_spectral_page.setObjectName("settings_experimental_raw_spectral_page")
    raw_spectral_layout = QVBoxLayout(raw_spectral_page)
    raw_spectral_layout.setContentsMargins(0, 12, 0, 0)
    raw_spectral_layout.setSpacing(10)
    self.preprocessing_qc_tabs.addTab(raw_spectral_page, "Raw-Spectral Review")

    self.postprocessing_qc_tabs = QTabWidget(tab)
    self.postprocessing_qc_tabs.setObjectName("settings_postprocessing_qc_sections")
    self.postprocessing_qc_tabs.setDocumentMode(True)
    self.postprocessing_qc_tabs.tabBar().setDrawBase(False)
    self._experimental_summed_bca_tab_index = self.experimental_tabs.addTab(
        self.postprocessing_qc_tabs, "Post-processing QC"
    )
    results_page = QWidget()
    results_page.setObjectName("settings_experimental_results_page")
    results_layout = QVBoxLayout(results_page)
    results_layout.setContentsMargins(0, 12, 0, 0)
    results_layout.setSpacing(10)
    self.postprocessing_qc_tabs.addTab(results_page, "Results")

    summed_bca_page = QWidget()
    summed_bca_page.setObjectName("settings_experimental_summed_bca_page")
    summed_bca_layout = QVBoxLayout(summed_bca_page)
    summed_bca_layout.setContentsMargins(0, 12, 0, 0)
    summed_bca_layout.setSpacing(10)
    self.postprocessing_qc_tabs.addTab(summed_bca_page, "Summed-BCA Screening")

    if self.project is not None:
        qc_preproc = self._project_preprocessing()
        experimental_settings = self.project.experimental_qc_settings
    else:
        qc_preproc = normalize_preprocessing_settings(
            {
                **PREPROCESSING_DEFAULTS,
                "removed_electrode_detection_choice_schema_version": "1.0.0",
                "removed_electrode_detection_choice_status": "ready",
                "removed_electrode_detection_choice_source": (
                    "new_project_default_off"
                ),
            }
        )
        experimental_settings = ExperimentalQcSettings.for_new_project()

    performance_page = QWidget()
    performance_page.setObjectName("settings_experimental_performance_page")
    performance_layout = QVBoxLayout(performance_page)
    performance_layout.setContentsMargins(0, 12, 0, 0)
    performance_layout.setSpacing(10)
    ram_card = SectionCard(
        "RAM Preloading", performance_page,
        object_name="settings_experimental_ram_preload_card",
    )
    self._add_settings_scope(
        ram_card.content_layout,
        "Current project only. Off by default."
        if self.project is not None else "Open a project to edit RAM preloading.",
    )
    self.experimental_ram_preload_check = QCheckBox(
        "Preload BDF recordings into RAM", ram_card,
    )
    self.experimental_ram_preload_check.setObjectName("experimental_ram_preload_check")
    self.experimental_ram_preload_check.setToolTip(
        "Use memory instead of temporary disk files when loading raw BDFs "
        "for QC and processing. QC prefetch uses at most 25% of available "
        "memory. Large recordings and parallel workers can exhaust RAM."
    )
    self.experimental_ram_preload_check.setChecked(
        bool(qc_preproc.get("experimental_ram_preload", False))
    )
    self.experimental_ram_preload_check.setEnabled(self.project is not None)
    ram_card.content_layout.addWidget(self.experimental_ram_preload_check)
    performance_layout.addWidget(ram_card)
    performance_layout.addStretch(1)
    self.experimental_tabs.addTab(performance_page, "Performance")
    self._init_beta_tools_page(self.experimental_tabs)

    settings_experimental_preprocessing_page.build_signal_review(
        self, signals_page, signals_layout, qc_preproc, experimental_settings,
    )

    settings_experimental_preprocessing_page.build_removed_electrode_review(
        self, electrodes_page, electrodes_layout, qc_preproc,
    )

    settings_experimental_preprocessing_page.build_raw_spectral_review(
        self, raw_spectral_page, raw_spectral_layout, experimental_settings,
    )

    post_review_card = SectionCard(
        "Experimental Result Review", results_page,
        object_name="settings_experimental_result_review_card",
    )
    for field_name, label, title, description in (
        (
            "interpolation_burden_review_enabled", "Review the number of repaired electrodes",
            "Interpolation burden review",
            "Flags recordings where more than 5% of scalp electrodes were repaired. "
            "This is a prompt to inspect the recording; it does not undo repairs.",
        ),
        (
            "snr_spectral_screening_enabled", "Flag unexpected peaks in SNR Plots",
            "SNR peak screening",
            "Marks unexpected frequency peaks in SNR plots for closer inspection. "
            "It does not change the plotted data or exclude participants.",
        ),
        (
            "stats_dv_screening_enabled", "Flag unusual values in Stats",
            "Stats value screening",
            "Flags unusually large analysis values using the limit set in Stats. "
            "It does not exclude finite values automatically; unusable values "
            "are always checked.",
        ),
    ):
        control = QCheckBox(label, post_review_card)
        control.setObjectName(f"settings_{field_name}")
        control.setChecked(getattr(experimental_settings, field_name))
        setattr(self, f"{field_name}_check", control)
        self._add_experimental_info_row(
            post_review_card.content_layout, post_review_card, control,
            title, description, f"settings_{field_name}_info",
        )
    results_layout.addWidget(post_review_card)
    results_layout.addStretch(1)

    screening = experimental_settings.summed_bca_screening
    summed_bca_card = SectionCard(
        "Experimental Summed-BCA Screening",
        summed_bca_page,
        object_name="settings_experimental_summed_bca_card",
    )
    self.summed_bca_explanation_label = QLabel(
        SUMMED_BCA_SCREENING_BRIEF_TEXT,
        summed_bca_card,
    )
    self.summed_bca_explanation_label.setObjectName(
        "settings_experimental_summed_bca_explanation"
    )
    self.summed_bca_explanation_label.setWordWrap(True)
    summed_bca_card.content_layout.addWidget(
        self.summed_bca_explanation_label
    )

    self.summed_bca_screening_enabled_check = QCheckBox(
        "Enable experimental summed-BCA screening",
        summed_bca_card,
    )
    self.summed_bca_screening_enabled_check.setObjectName(
        "settings_summed_bca_screening_enabled"
    )
    self.summed_bca_screening_enabled_check.setChecked(screening.enabled)
    self._add_experimental_info_row(
        summed_bca_card.content_layout, summed_bca_card,
        self.summed_bca_screening_enabled_check, "Summed-BCA screening",
        "Flags unusually large frequency responses after processing. You can "
        "retain or exclude affected data after review. The limits are experimental "
        "and may not suit every study. Condition-specific repairs below require this check.",
        "settings_summed_bca_screening_info",
    )

    absolute_header = SubsectionHeaderLabel(
        "Saved limits — used when screening is on",
        summed_bca_card,
    )
    summed_bca_card.content_layout.addWidget(absolute_header)
    absolute_grid = QGridLayout()
    absolute_specs = (
        (
            "warning_summed_bca_uv",
            "Warning above (uV):",
            screening.warning_summed_bca_uv,
        ),
        (
            "strong_warning_summed_bca_uv",
            "Strong warning above (uV):",
            screening.strong_warning_summed_bca_uv,
        ),
        (
            "extreme_review_summed_bca_uv",
            "Extreme review above (uV):",
            screening.extreme_review_summed_bca_uv,
        ),
        (
            "concentrated_review_flagged_cells",
            "Concentrated review cells:",
            screening.concentrated_review_flagged_cells,
        ),
        (
            "broad_extreme_review_unique_electrodes",
            "Broad review electrodes:",
            screening.broad_extreme_review_unique_electrodes,
        ),
    )
    self.summed_bca_threshold_edits: dict[str, QLineEdit] = {}
    self._add_experimental_threshold_grid(
        absolute_grid,
        absolute_specs,
        summed_bca_card,
    )
    summed_bca_card.content_layout.addLayout(absolute_grid)

    self.condition_specific_interpolation_enabled_check = QCheckBox(
        "Allow repairs in the reviewed condition only", summed_bca_card,
    )
    self.condition_specific_interpolation_enabled_check.setObjectName(
        "settings_condition_specific_interpolation_enabled"
    )
    self.condition_specific_interpolation_enabled_check.setChecked(
        experimental_settings.condition_specific_interpolation_enabled
    )
    self._add_experimental_info_row(
        summed_bca_card.content_layout, summed_bca_card,
        self.condition_specific_interpolation_enabled_check,
        "Condition-specific electrode repairs",
        "After you confirm an artifact during summed-BCA review, repair the "
        "electrode in that condition and recalculate its results. A large response "
        "alone is not evidence of an artifact. Turning this off keeps accepted repairs.",
        "settings_condition_specific_interpolation_info",
    )

    summed_bca_layout.addWidget(summed_bca_card)
    summed_bca_layout.addStretch(1)

    project_controls_enabled = self.project is not None
    for control in (
        self.raw_signal_screening_enabled_check,
        self.kurtosis_screening_enabled_check,
        self.interpolation_burden_review_enabled_check,
        self.snr_spectral_screening_enabled_check,
        self.stats_dv_screening_enabled_check,
        self.kurtosis_auto_interpolate_all_check,
        self.kurtosis_review_auto_interpolate_extreme_check,
        self.condition_specific_interpolation_enabled_check,
        self.removed_electrode_detection_mode_combo,
        self.removed_electrode_detection_info_button,
        self.manual_removed_electrodes_enabled_check,
        self.manual_removed_electrodes_button,
        self.raw_spectral_screening_enabled_check,
        self.summed_bca_screening_enabled_check,
        *self.summed_bca_threshold_edits.values(),
    ):
        control.setEnabled(project_controls_enabled)
    self.kurtosis_screening_enabled_check.toggled.connect(self._refresh_experimental_qc_dependencies)
    self.summed_bca_screening_enabled_check.toggled.connect(self._refresh_experimental_qc_dependencies)
    self._refresh_experimental_qc_dependencies()
    if not project_controls_enabled:
        self.removed_electrode_detection_status.set_variant("info")
        self.removed_electrode_detection_status.set_text(
            "Open a project to edit its experimental QC settings."
        )
        self.removed_electrode_detection_status.setVisible(True)

    tabs.addTab(tab, "Experimental")
    return tab


def add_experimental_info_row(
    self, layout: QVBoxLayout, parent: QWidget, content: QWidget | str,
    title: str, description: str, object_name: str,
) -> None:
    row = QWidget(parent)
    row_layout = QHBoxLayout(row)
    row_layout.setContentsMargins(0, 0, 0, 0)
    row_layout.setSpacing(8)
    if isinstance(content, str):
        content = QLabel(content, row)
        content.setWordWrap(True)
    row_layout.addWidget(content, 1)
    info = make_info_button(
        parent=row, object_name=object_name, tooltip=f"About {title.lower()}", size=16,
    )
    info.clicked.connect(lambda: QMessageBox.information(self, title, description))
    row_layout.addWidget(info)
    layout.addWidget(row)


def build_beta_tools_page(self, tabs: QTabWidget) -> None:
    page = QWidget()
    page.setObjectName("settings_experimental_beta_tools_page")
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 12, 0, 0)
    layout.setSpacing(10)
    card = SectionCard(
        "Beta Tools", page, object_name="settings_experimental_beta_tools_card",
    )
    self._add_settings_scope(
        card.content_layout,
        "Application-wide. Show the optional Beta Tools section in the sidebar.",
    )
    self.beta_tools_check = QCheckBox("Enable Beta Tools", card)
    self.beta_tools_check.setObjectName("settings_enable_beta_tools")
    self.beta_tools_check.setChecked(self.manager.beta_tools_enabled())
    card.content_layout.addWidget(self.beta_tools_check)
    self._add_settings_scope(
        card.content_layout,
        "Save, then close and reopen FPVS Toolbox to update tool visibility. "
        "Beta tools may change as they are developed.",
    )
    layout.addWidget(card)
    layout.addStretch(1)
    tabs.addTab(page, "Beta Tools")


def add_experimental_threshold_grid(
    self,
    grid: QGridLayout,
    specs: tuple[tuple[str, str, object], ...],
    parent: QWidget,
) -> None:
    grid.setHorizontalSpacing(16)
    grid.setVerticalSpacing(8)
    for index, (field_name, label_text, value) in enumerate(specs):
        row = index // 2
        column = (index % 2) * 2
        edit = QLineEdit(parent)
        edit.setObjectName(f"settings_summed_bca_{field_name}")
        edit.setText(str(value))
        edit.setMaximumWidth(120)
        edit.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        label = QLabel(label_text, parent)
        label.setWordWrap(True)
        label.setBuddy(edit)
        grid.addWidget(label, row, column)
        grid.addWidget(edit, row, column + 1)
        self.summed_bca_threshold_edits[field_name] = edit
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 1)

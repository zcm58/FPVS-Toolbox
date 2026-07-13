"""Embedded PySide6 page for the standalone sensitivity calculator."""

from __future__ import annotations

import math
import secrets

from PySide6.QtCore import QSize, Qt, QThread
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
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
from Tools.Sensitivity_Analysis.calculator import (
    SensitivityResult,
    calculate_paired_ttest_sensitivity,
    calculate_rm_anova_sensitivity,
)
from Tools.Sensitivity_Analysis.lmm_simulation import (
    LmmSensitivityConfig,
    LmmSensitivityResult,
    validate_lmm_config,
)
from Tools.Sensitivity_Analysis.tool_info import SENSITIVITY_ANALYSIS_TOOL_INFO
from Tools.Sensitivity_Analysis.worker import LmmSensitivityWorker


def _new_lmm_seed() -> int:
    """Return an operating-system-randomized seed accepted by the LMM backend."""

    return secrets.randbelow(2_147_483_648)


class _RequiredIntegerSpinBox(QSpinBox):
    """Required integer input with a native empty-state placeholder."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.lineEdit().setPlaceholderText("Enter value")

    def textFromValue(self, value: int) -> str:
        if value == self.minimum():
            return ""
        return super().textFromValue(value)


class _ResultSummary(QWidget):
    """Compact, theme-driven presentation for the primary sensitivity result."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("statusVariant", "info")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(2)

        self.metric_label = QLabel("NOT YET CALCULATED", self)
        self.metric_label.setProperty("eyebrow", True)
        layout.addWidget(self.metric_label)

        self.value_label = QLabel("—", self)
        self.value_label.setProperty("resultValue", True)
        apply_font_role(self.value_label, "result_value")
        layout.addWidget(self.value_label)

        self.context_label = QLabel(
            "Set the assumptions, then select Calculate.",
            self,
        )
        self.context_label.setWordWrap(True)
        layout.addWidget(self.context_label)
        self._text = "Set the assumptions and select Calculate."

    def text(self) -> str:
        return self._text

    def set_placeholder(self) -> None:
        self._text = "Set the assumptions and select Calculate."
        self.metric_label.setText("NOT YET CALCULATED")
        self.value_label.setText("—")
        self.context_label.setText("Set the assumptions, then select Calculate.")
        self.set_variant("info")

    def set_result(self, metric: str, value: float) -> None:
        formatted_value = f"{value:.2f}"
        self._text = f"{metric} = {formatted_value}"
        self.metric_label.setText(metric.upper())
        self.value_label.setText(formatted_value)
        self.context_label.setText("Minimum detectable standardized effect")
        self.set_variant("info")

    def set_variant(self, variant: str) -> None:
        self.setProperty("statusVariant", variant)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class _CurrentPageStack(QStackedWidget):
    """Size a stack from its visible page instead of its tallest hidden page."""

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method
        current = self.currentWidget()
        return current.sizeHint() if current is not None else super().sizeHint()

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt virtual method
        current = self.currentWidget()
        if current is not None:
            return current.minimumSizeHint()
        return super().minimumSizeHint()


class SensitivityAnalysisWindow(QWidget):
    """Input-only sensitivity analysis page embedded in the Main App."""

    PAIRED_TEST = 0
    RM_ANOVA = 1
    LMM_SIMULATION = 2
    CONDITION_EFFECT = 0
    ROI_EFFECT = 1
    OMNIBUS_CELLS = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sensitivity Analysis")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._lmm_thread: QThread | None = None
        self._lmm_worker: LmmSensitivityWorker | None = None
        self._lmm_seed = _new_lmm_seed()
        self._build_ui()
        self._connect_signals()
        self.reset_defaults()

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea(self)
        scroll.setObjectName("sensitivity_scroll_area")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        root_layout.addWidget(scroll)

        page = QWidget(scroll)
        page.setObjectName("sensitivity_page_content")
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        scroll.setWidget(page)

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(24, 22, 24, 24)
        page_layout.setSpacing(14)

        header = QWidget(page)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)

        eyebrow = QLabel("STUDY PLANNING", header)
        eyebrow.setObjectName("sensitivity_eyebrow")
        eyebrow.setProperty("eyebrow", True)
        header_layout.addWidget(eyebrow)

        title = QLabel("Sensitivity Analysis", header)
        title.setObjectName("sensitivity_title")
        title.setProperty("toolTitle", True)
        apply_font_role(title, "tool_title")
        header_layout.addWidget(title)

        subtitle = QLabel(
            "Estimate the smallest standardized effect a study can detect from "
            "its planned sample size, power, alpha, and design assumptions.",
            header,
        )
        subtitle.setObjectName("sensitivity_subtitle")
        subtitle.setWordWrap(True)
        header_layout.addWidget(subtitle)
        page_layout.addWidget(header)

        sections = QGridLayout()
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setHorizontalSpacing(16)
        sections.setVerticalSpacing(16)
        sections.setColumnStretch(0, 1)
        sections.setColumnStretch(1, 1)
        page_layout.addLayout(sections)

        inputs_card = SectionCard(
            "Study assumptions",
            page,
            object_name="sensitivity_inputs_card",
        )
        inputs_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.tool_info_button = make_info_button(
            parent=inputs_card,
            tooltip="About Sensitivity Analysis",
            object_name="sensitivity_analysis_tool_info_btn",
        )
        self.tool_info_button.clicked.connect(
            lambda: show_tool_info(self, SENSITIVITY_ANALYSIS_TOOL_INFO)
        )
        inputs_card.header.add_action_widget(self.tool_info_button)
        sections.addWidget(inputs_card, 0, 0)
        self._build_inputs(inputs_card)

        results_card = SectionCard(
            "Sensitivity result",
            page,
            object_name="sensitivity_results_card",
        )
        results_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        sections.addWidget(results_card, 0, 1)
        self._build_results(results_card)

        self.disclaimer = StatusBanner(
            "Cohen's conventional small, medium, and large benchmarks are only "
            "descriptive reference points. They do not establish theoretical, "
            "clinical, or practical importance.",
            page,
            variant="warning",
        )
        self.disclaimer.setObjectName("sensitivity_disclaimer")
        page_layout.addWidget(self.disclaimer)
        page_layout.addStretch(1)

    def _build_inputs(self, card: SectionCard) -> None:
        common_form = make_form_layout()
        card.content_layout.addLayout(common_form)

        self.analysis_combo = QComboBox(card.content)
        self.analysis_combo.setObjectName("sensitivity_analysis_type")
        self.analysis_combo.addItems(
            [
                "Paired / one-sample t-test",
                "Repeated-measures ANOVA",
                "Linear mixed model (simulation)",
            ]
        )
        self.analysis_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.analysis_combo.setMinimumContentsLength(20)
        self._expand_input(self.analysis_combo)
        common_form.addRow("Analysis:", self.analysis_combo)

        self.sample_size_spin = QSpinBox(card.content)
        self.sample_size_spin.setObjectName("sensitivity_sample_size")
        self.sample_size_spin.setRange(3, 100_000)
        self.sample_size_spin.setToolTip(
            "Participants expected to contribute the complete observations "
            "required by the selected analysis, after exclusions."
        )
        self._expand_input(self.sample_size_spin)
        self.sample_size_label = QLabel("Analyzable participants (N):", card.content)
        common_form.addRow(self.sample_size_label, self.sample_size_spin)

        self.power_spin = QDoubleSpinBox(card.content)
        self.power_spin.setObjectName("sensitivity_power")
        self.power_spin.setDecimals(2)
        self.power_spin.setSingleStep(0.05)
        self.power_spin.setRange(0.50, 0.99)
        self.power_spin.setToolTip("Target probability of detecting the effect.")
        self._expand_input(self.power_spin)
        common_form.addRow("Desired power:", self.power_spin)

        self.alpha_spin = QDoubleSpinBox(card.content)
        self.alpha_spin.setObjectName("sensitivity_alpha")
        self.alpha_spin.setDecimals(3)
        self.alpha_spin.setSingleStep(0.01)
        self.alpha_spin.setRange(0.001, 0.250)
        self.alpha_spin.setToolTip("Type I error rate for the planned test.")
        self._expand_input(self.alpha_spin)
        common_form.addRow("Alpha:", self.alpha_spin)

        self.design_stack = _CurrentPageStack(card.content)
        self.design_stack.setObjectName("sensitivity_design_stack")
        self.design_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.content_layout.addWidget(self.design_stack)

        paired_panel = QWidget(self.design_stack)
        paired_form = make_form_layout()
        paired_panel.setLayout(paired_form)
        self.alternative_combo = QComboBox(paired_panel)
        self.alternative_combo.setObjectName("sensitivity_alternative")
        self.alternative_combo.addItems(["Two-sided", "One-sided (directional)"])
        self._expand_input(self.alternative_combo)
        paired_form.addRow("Alternative:", self.alternative_combo)
        self.design_stack.addWidget(paired_panel)

        rm_panel = QWidget(self.design_stack)
        rm_form = make_form_layout()
        rm_panel.setLayout(rm_form)

        self.effect_target_combo = QComboBox(rm_panel)
        self.effect_target_combo.setObjectName("sensitivity_effect_target")
        self.effect_target_combo.addItems(
            [
                "Condition effect",
                "ROI effect",
                "Omnibus condition × ROI cells",
            ]
        )
        self.effect_target_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.effect_target_combo.setMinimumContentsLength(22)
        self._expand_input(self.effect_target_combo)
        rm_form.addRow("Effect evaluated:", self.effect_target_combo)

        self.conditions_spin = QSpinBox(rm_panel)
        self.conditions_spin.setObjectName("sensitivity_conditions")
        self.conditions_spin.setRange(1, 100)
        self._expand_input(self.conditions_spin)
        rm_form.addRow("Number of conditions:", self.conditions_spin)

        self.rois_spin = QSpinBox(rm_panel)
        self.rois_spin.setObjectName("sensitivity_rois")
        self.rois_spin.setRange(1, 100)
        self._expand_input(self.rois_spin)
        rm_form.addRow("Number of ROIs:", self.rois_spin)

        self.measurements_spin = QSpinBox(rm_panel)
        self.measurements_spin.setObjectName("sensitivity_measurements")
        self.measurements_spin.setRange(1, 10_000)
        self.measurements_spin.setReadOnly(True)
        self.measurements_spin.setButtonSymbols(QSpinBox.NoButtons)
        self.measurements_spin.setToolTip(
            "Calculated from the condition count, ROI count, and effect evaluated."
        )
        self._expand_input(self.measurements_spin)
        rm_form.addRow("Derived measurements:", self.measurements_spin)

        self.measurement_explanation = QLabel("", rm_panel)
        self.measurement_explanation.setObjectName("sensitivity_measurement_explanation")
        self.measurement_explanation.setProperty("caption", True)
        self.measurement_explanation.setWordWrap(True)
        rm_form.addRow(self.measurement_explanation)

        self.correlation_spin = QDoubleSpinBox(rm_panel)
        self.correlation_spin.setObjectName("sensitivity_correlation")
        self.correlation_spin.setDecimals(2)
        self.correlation_spin.setSingleStep(0.05)
        self.correlation_spin.setRange(-0.99, 0.99)
        self._expand_input(self.correlation_spin)
        rm_form.addRow("Average correlation:", self.correlation_spin)

        self.epsilon_spin = QDoubleSpinBox(rm_panel)
        self.epsilon_spin.setObjectName("sensitivity_epsilon")
        self.epsilon_spin.setDecimals(2)
        self.epsilon_spin.setSingleStep(0.05)
        self.epsilon_spin.setRange(0.01, 1.00)
        self._expand_input(self.epsilon_spin)
        rm_form.addRow("Nonsphericity epsilon:", self.epsilon_spin)
        self.design_stack.addWidget(rm_panel)

        lmm_panel = QWidget(self.design_stack)
        lmm_layout = QVBoxLayout(lmm_panel)
        lmm_layout.setContentsMargins(0, 0, 0, 0)
        lmm_layout.setSpacing(8)

        self.lmm_tabs = QTabWidget(lmm_panel)
        self.lmm_tabs.setObjectName("sensitivity_lmm_tabs")
        self.lmm_tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lmm_layout.addWidget(self.lmm_tabs)

        self.lmm_design_panel = QWidget(self.lmm_tabs)
        self.lmm_design_panel.setObjectName("sensitivity_lmm_design_panel")
        lmm_design_form = make_form_layout()
        self.lmm_design_panel.setLayout(lmm_design_form)

        self.lmm_advanced_panel = QWidget(self.lmm_tabs)
        self.lmm_advanced_panel.setObjectName("sensitivity_lmm_advanced_panel")
        lmm_advanced_form = make_form_layout()
        self.lmm_advanced_panel.setLayout(lmm_advanced_form)

        self.lmm_tabs.addTab(self.lmm_design_panel, "Design")
        self.lmm_tabs.addTab(self.lmm_advanced_panel, "Advanced")

        self.lmm_sample_size_spin = _RequiredIntegerSpinBox(self.lmm_design_panel)
        self.lmm_sample_size_spin.setObjectName("sensitivity_lmm_sample_size")
        self.lmm_sample_size_spin.setRange(0, 100_000)
        self.lmm_sample_size_spin.setToolTip(
            "Complete, analyzable participants expected after exclusions."
        )
        self._expand_input(self.lmm_sample_size_spin)
        lmm_design_form.addRow(
            "Analyzable participants (N):",
            self.lmm_sample_size_spin,
        )

        self.lmm_target_combo = QComboBox(self.lmm_design_panel)
        self.lmm_target_combo.setObjectName("sensitivity_lmm_target")
        self.lmm_target_combo.addItems(
            [
                "Condition effect (two-level contrast)",
                "ROI effect (two-level contrast)",
                "Condition × ROI interaction (2 × 2 contrast)",
            ]
        )
        self.lmm_target_combo.setSizeAdjustPolicy(
            QComboBox.AdjustToMinimumContentsLengthWithIcon
        )
        self.lmm_target_combo.setMinimumContentsLength(24)
        self._expand_input(self.lmm_target_combo)
        lmm_design_form.addRow("Effect simulated:", self.lmm_target_combo)

        self.lmm_conditions_spin = _RequiredIntegerSpinBox(self.lmm_design_panel)
        self.lmm_conditions_spin.setObjectName("sensitivity_lmm_conditions")
        self.lmm_conditions_spin.setRange(0, 20)
        self._expand_input(self.lmm_conditions_spin)
        lmm_design_form.addRow("Number of conditions:", self.lmm_conditions_spin)

        self.lmm_rois_spin = _RequiredIntegerSpinBox(self.lmm_design_panel)
        self.lmm_rois_spin.setObjectName("sensitivity_lmm_rois")
        self.lmm_rois_spin.setRange(0, 20)
        self._expand_input(self.lmm_rois_spin)
        lmm_design_form.addRow("Number of ROIs:", self.lmm_rois_spin)

        advanced_note = QLabel(
            "Most studies can retain these defaults. Correlation is the "
            "participant random-intercept ICC; for the supported within-participant "
            "contrasts in residual-SD units, it usually has little effect on power.",
            self.lmm_advanced_panel,
        )
        advanced_note.setObjectName("sensitivity_lmm_advanced_note")
        advanced_note.setProperty("caption", True)
        advanced_note.setWordWrap(True)
        lmm_advanced_form.addRow(advanced_note)

        self.lmm_correlation_spin = QDoubleSpinBox(self.lmm_advanced_panel)
        self.lmm_correlation_spin.setObjectName("sensitivity_lmm_correlation")
        self.lmm_correlation_spin.setDecimals(2)
        self.lmm_correlation_spin.setSingleStep(0.05)
        self.lmm_correlation_spin.setRange(0.00, 0.94)
        self.lmm_correlation_spin.setToolTip(
            "Random-intercept intraclass correlation across condition × ROI "
            "observations. The 0.50 default is a neutral assumption, not an "
            "FPVS-derived estimate."
        )
        self._expand_input(self.lmm_correlation_spin)
        lmm_advanced_form.addRow(
            "Random-intercept correlation:",
            self.lmm_correlation_spin,
        )

        self.lmm_simulations_spin = QSpinBox(self.lmm_advanced_panel)
        self.lmm_simulations_spin.setObjectName("sensitivity_lmm_simulations")
        self.lmm_simulations_spin.setRange(100, 50_000)
        self.lmm_simulations_spin.setSingleStep(1_000)
        self.lmm_simulations_spin.setToolTip(
            "Independent confirmation simulations. The 10,000-study default "
            "provides a high-precision Monte Carlo power estimate."
        )
        self._expand_input(self.lmm_simulations_spin)
        lmm_advanced_form.addRow("Final simulations:", self.lmm_simulations_spin)

        lmm_design_form.activate()
        lmm_advanced_form.activate()
        equal_tab_height = max(
            self.lmm_design_panel.sizeHint().height(),
            self.lmm_advanced_panel.sizeHint().height(),
        )
        self.lmm_design_panel.setMinimumHeight(equal_tab_height)
        self.lmm_advanced_panel.setMinimumHeight(equal_tab_height)

        lmm_scope = QLabel(
            "Model: value ~ condition × ROI + participant random intercept. "
            "The simulation can take a minute or longer.",
            lmm_panel,
        )
        lmm_scope.setObjectName("sensitivity_lmm_scope")
        lmm_scope.setProperty("caption", True)
        lmm_scope.setWordWrap(True)
        lmm_layout.addWidget(lmm_scope)
        self.design_stack.addWidget(lmm_panel)

        self.assumption_guidance = StatusBanner("", card.content, variant="info")
        self.assumption_guidance.setObjectName("sensitivity_assumption_guidance")
        self.assumption_guidance.hide()
        card.content_layout.addWidget(self.assumption_guidance)

        self.validation_banner = StatusBanner("", card.content, variant="error")
        self.validation_banner.setObjectName("sensitivity_validation")
        self.validation_banner.hide()
        card.content_layout.addWidget(self.validation_banner)

        self.calculate_button = make_action_button(
            "Calculate", variant="primary", parent=card.content
        )
        self.calculate_button.setObjectName("sensitivity_calculate")
        self.reset_button = make_action_button(
            "Reset Defaults", variant="secondary", parent=card.content
        )
        self.reset_button.setObjectName("sensitivity_reset")
        self.cancel_button = make_action_button(
            "Cancel", variant="secondary", parent=card.content
        )
        self.cancel_button.setObjectName("sensitivity_cancel")
        self.cancel_button.hide()
        actions = make_action_row(
            [self.reset_button, self.cancel_button, self.calculate_button],
            parent=card.content,
        )
        card.content_layout.addWidget(actions)

    @staticmethod
    def _expand_input(widget: QWidget) -> None:
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def _build_results(self, card: SectionCard) -> None:
        intro = QLabel(
            "The smallest effect detectable with the selected power and design "
            "assumptions.",
            card.content,
        )
        intro.setWordWrap(True)
        card.content_layout.addWidget(intro)

        self.simulation_status = StatusBanner("", card.content, variant="info")
        self.simulation_status.setObjectName("sensitivity_simulation_status")
        self.simulation_status.hide()
        card.content_layout.addWidget(self.simulation_status)

        self.result_banner = _ResultSummary(card.content)
        self.result_banner.setObjectName("sensitivity_result")
        card.content_layout.addWidget(self.result_banner)

        self.magnitude_label = QLabel("Conventional magnitude: —", card.content)
        self.magnitude_label.setObjectName("sensitivity_magnitude")
        apply_font_role(self.magnitude_label, "update_title")
        self.magnitude_label.setWordWrap(True)
        card.content_layout.addWidget(self.magnitude_label)

        self.equivalent_label = QLabel("", card.content)
        self.equivalent_label.setObjectName("sensitivity_equivalent")
        self.equivalent_label.setWordWrap(True)
        self.equivalent_label.hide()
        card.content_layout.addWidget(self.equivalent_label)

        self.plain_language_label = QLabel(
            "An interpretation will appear after calculation.",
            card.content,
        )
        self.plain_language_label.setObjectName("sensitivity_plain_language_result")
        self.plain_language_label.setWordWrap(True)
        card.content_layout.addWidget(self.plain_language_label)

        assumptions_heading = QLabel("ASSUMPTIONS USED", card.content)
        assumptions_heading.setProperty("eyebrow", True)
        card.content_layout.addWidget(assumptions_heading)

        self.assumption_summary_label = QLabel(
            "Current assumptions will appear after calculation.",
            card.content,
        )
        self.assumption_summary_label.setObjectName("sensitivity_assumption_summary")
        self.assumption_summary_label.setProperty("caption", True)
        self.assumption_summary_label.setWordWrap(True)
        card.content_layout.addWidget(self.assumption_summary_label)

        reporting_heading = QLabel("REPORTING SUMMARY", card.content)
        reporting_heading.setProperty("eyebrow", True)
        card.content_layout.addWidget(reporting_heading)

        self.reporting_label = QLabel(
            "A reporting-ready summary will appear after calculation.",
            card.content,
        )
        self.reporting_label.setObjectName("sensitivity_reporting_text")
        self.reporting_label.setWordWrap(True)
        self.reporting_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.content_layout.addWidget(self.reporting_label)

        benchmark_heading = QLabel("INTERPRETATION GUIDE", card.content)
        benchmark_heading.setProperty("eyebrow", True)
        card.content_layout.addWidget(benchmark_heading)

        self.benchmark_label = QLabel("", card.content)
        self.benchmark_label.setObjectName("sensitivity_benchmarks")
        self.benchmark_label.setWordWrap(True)
        card.content_layout.addWidget(self.benchmark_label)

    def _connect_signals(self) -> None:
        self.analysis_combo.currentIndexChanged.connect(self._set_analysis_type)
        self.sample_size_spin.valueChanged.connect(self._on_assumptions_changed)
        self.power_spin.valueChanged.connect(self._on_assumptions_changed)
        self.alpha_spin.valueChanged.connect(self._on_assumptions_changed)
        self.alternative_combo.currentIndexChanged.connect(
            self._on_alternative_changed
        )
        self.effect_target_combo.currentIndexChanged.connect(
            self._update_derived_measurements
        )
        self.conditions_spin.valueChanged.connect(self._update_derived_measurements)
        self.rois_spin.valueChanged.connect(self._update_derived_measurements)
        self.correlation_spin.valueChanged.connect(self._on_assumptions_changed)
        self.epsilon_spin.valueChanged.connect(self._on_assumptions_changed)
        self.lmm_target_combo.currentIndexChanged.connect(
            self._on_lmm_assumptions_changed
        )
        self.lmm_sample_size_spin.valueChanged.connect(
            self._on_lmm_assumptions_changed
        )
        self.lmm_conditions_spin.valueChanged.connect(
            self._on_lmm_assumptions_changed
        )
        self.lmm_rois_spin.valueChanged.connect(self._on_lmm_assumptions_changed)
        self.lmm_correlation_spin.valueChanged.connect(
            self._on_lmm_assumptions_changed
        )
        self.lmm_simulations_spin.valueChanged.connect(
            self._on_lmm_assumptions_changed
        )
        self.calculate_button.clicked.connect(self.calculate)
        self.cancel_button.clicked.connect(self._cancel_lmm_simulation)
        self.reset_button.clicked.connect(self.reset_defaults)

    def _on_assumptions_changed(self) -> None:
        self._clear_result()

    def _on_alternative_changed(self) -> None:
        self._update_assumption_guidance()
        self._clear_result()

    def _on_lmm_assumptions_changed(self) -> None:
        self._update_assumption_guidance()
        self._clear_result()

    def _update_derived_measurements(self) -> None:
        conditions = self.conditions_spin.value()
        rois = self.rois_spin.value()
        target = self.effect_target_combo.currentIndex()
        if target == self.CONDITION_EFFECT:
            measurements = conditions
            explanation = (
                f"One value per condition for each participant: {conditions} "
                "repeated measurements. ROIs are assumed averaged or otherwise "
                "outside this one-way effect."
            )
        elif target == self.ROI_EFFECT:
            measurements = rois
            explanation = (
                f"One value per ROI for each participant: {rois} repeated "
                "measurements. Conditions are assumed averaged or otherwise "
                "outside this one-way effect."
            )
        else:
            measurements = conditions * rois
            explanation = (
                f"{conditions} conditions × {rois} ROIs = {measurements} cell means. "
                "This is an omnibus one-way approximation, not interaction power."
            )
        self.measurements_spin.setValue(measurements)
        self.measurement_explanation.setText(explanation)
        self._update_repeated_measure_bounds(measurements)
        self._update_assumption_guidance()
        self.design_stack.currentWidget().updateGeometry()
        self.design_stack.updateGeometry()
        self._clear_result()

    def _update_repeated_measure_bounds(self, measurements: int) -> None:
        if measurements < 2:
            self.correlation_spin.setMinimum(-0.99)
            self.epsilon_spin.setMinimum(0.01)
            self.correlation_spin.setToolTip(
                "Select an effect with at least two measurements first."
            )
            self.epsilon_spin.setToolTip(
                "Select an effect with at least two measurements first."
            )
            return

        correlation_bound = -1 / (measurements - 1)
        correlation_minimum = (math.floor(correlation_bound * 100) + 1) / 100
        epsilon_bound = 1 / (measurements - 1)
        epsilon_minimum = math.ceil(epsilon_bound * 100) / 100
        self.correlation_spin.setMinimum(max(-0.99, correlation_minimum))
        self.epsilon_spin.setMinimum(max(0.01, epsilon_minimum))
        self.correlation_spin.setToolTip(
            f"Valid interface range for {measurements} measurements: "
            f"{max(-0.99, correlation_minimum):.2f} to 0.99."
        )
        self.epsilon_spin.setToolTip(
            f"Valid range for {measurements} measurements: "
            f"{epsilon_minimum:.2f} to 1.00."
        )

    def _update_assumption_guidance(self) -> None:
        analysis = self.analysis_combo.currentIndex()
        is_rm_anova = analysis == self.RM_ANOVA
        is_lmm = analysis == self.LMM_SIMULATION
        measurements = self.measurements_spin.value()
        if is_rm_anova and measurements < 2:
            self.assumption_guidance.set_variant("error")
            self.assumption_guidance.set_text(
                "The selected effect needs at least two repeated measurements. "
                "Increase the relevant condition or ROI count."
            )
            self.assumption_guidance.show()
            self.calculate_button.setEnabled(False)
            return

        if is_lmm and (
            self.lmm_sample_size_spin.value() < 3
            or self.lmm_conditions_spin.value() < 2
            or self.lmm_rois_spin.value() < 2
        ):
            self.assumption_guidance.set_variant("error")
            self.assumption_guidance.set_text(
                "Enter at least 3 analyzable participants, 2 conditions, and 2 ROIs "
                "before running the mixed-model simulation."
            )
            self.assumption_guidance.show()
            self.calculate_button.setEnabled(False)
            return

        self.calculate_button.setEnabled(True)
        if (
            is_rm_anova
            and self.effect_target_combo.currentIndex() == self.OMNIBUS_CELLS
        ):
            self.assumption_guidance.set_variant("warning")
            self.assumption_guidance.set_text(
                "The omnibus option tests whether any cell means differ. It "
                "does not isolate condition, ROI, or interaction power."
            )
            self.assumption_guidance.show()
        elif analysis == self.PAIRED_TEST and self.alternative_combo.currentIndex() == 1:
            self.assumption_guidance.set_variant("warning")
            self.assumption_guidance.set_text(
                "Use a one-sided test only for a directional hypothesis chosen "
                "before examining the data. An effect in the opposite direction "
                "would not count as support for that test."
            )
            self.assumption_guidance.show()
        elif is_lmm:
            self.assumption_guidance.set_variant("info")
            self.assumption_guidance.set_text(
                "Idealized design sensitivity estimates a minimum standardized "
                "contrast and reports Monte Carlo uncertainty and fit diagnostics."
            )
            self.assumption_guidance.show()
        else:
            self.assumption_guidance.hide()

    def _set_analysis_type(self, index: int) -> None:
        is_lmm = index == self.LMM_SIMULATION
        self.sample_size_label.setVisible(not is_lmm)
        self.sample_size_spin.setVisible(not is_lmm)
        self.design_stack.setCurrentIndex(index)
        self.design_stack.updateGeometry()
        self._update_assumption_guidance()
        if index == self.PAIRED_TEST:
            self.benchmark_label.setText(
                "Conventional d benchmarks: 0.20 small, 0.50 medium, 0.80 large."
            )
            self.calculate_button.setText("Calculate")
        elif index == self.RM_ANOVA:
            self.benchmark_label.setText(
                "Conventional f benchmarks: 0.10 small, 0.25 medium, 0.40 large."
            )
            self.calculate_button.setText("Calculate")
        else:
            self.benchmark_label.setText(
                "The standardized contrast is expressed in residual-SD units. "
                "No universal small, medium, or large benchmarks are applied."
            )
            self.calculate_button.setText("Run Simulation")
        self._clear_result()

    def reset_defaults(self) -> None:
        self.analysis_combo.setCurrentIndex(self.PAIRED_TEST)
        self.sample_size_spin.setValue(24)
        self.power_spin.setValue(0.80)
        self.alpha_spin.setValue(0.05)
        self.alternative_combo.setCurrentIndex(0)
        self.conditions_spin.setValue(2)
        self.rois_spin.setValue(1)
        self.effect_target_combo.setCurrentIndex(self.CONDITION_EFFECT)
        self._update_derived_measurements()
        self.correlation_spin.setValue(0.50)
        self.epsilon_spin.setValue(1.00)
        self.lmm_tabs.setCurrentIndex(0)
        self.lmm_target_combo.setCurrentIndex(0)
        self.lmm_sample_size_spin.setValue(0)
        self.lmm_conditions_spin.setValue(0)
        self.lmm_rois_spin.setValue(0)
        self.lmm_correlation_spin.setValue(0.50)
        self.lmm_simulations_spin.setValue(10_000)
        self._set_analysis_type(self.PAIRED_TEST)

    def refresh_lmm_seed(self) -> None:
        """Generate a new hidden seed when the embedded tool is opened again."""

        if self._lmm_thread is not None:
            return
        self._lmm_seed = _new_lmm_seed()
        self.lmm_tabs.setCurrentIndex(0)
        self.lmm_sample_size_spin.setValue(0)
        self.lmm_conditions_spin.setValue(0)
        self.lmm_rois_spin.setValue(0)
        self._clear_result()

    def _clear_result(self) -> None:
        self.validation_banner.hide()
        self.result_banner.set_placeholder()
        if self.analysis_combo.currentIndex() == self.LMM_SIMULATION:
            self.magnitude_label.setText(
                "Effect scale: standardized contrast in residual-SD units"
            )
        else:
            self.magnitude_label.setText("Conventional magnitude: —")
        self.equivalent_label.clear()
        self.equivalent_label.hide()
        self.reporting_label.setText(
            "A reporting-ready summary will appear after calculation."
        )
        self.plain_language_label.setText(
            "An interpretation will appear after calculation."
        )
        self.assumption_summary_label.setText(
            "Current assumptions will appear after calculation."
        )
        if self._lmm_thread is None:
            self.simulation_status.hide()

    def calculate(self) -> None:
        if self.analysis_combo.currentIndex() == self.LMM_SIMULATION:
            self._start_lmm_simulation()
            return
        try:
            if self.analysis_combo.currentIndex() == self.PAIRED_TEST:
                result = calculate_paired_ttest_sensitivity(
                    sample_size=self.sample_size_spin.value(),
                    power=self.power_spin.value(),
                    alpha=self.alpha_spin.value(),
                    alternative=(
                        "two-sided" if self.alternative_combo.currentIndex() == 0 else "larger"
                    ),
                )
            else:
                result = calculate_rm_anova_sensitivity(
                    sample_size=self.sample_size_spin.value(),
                    measurements=self.measurements_spin.value(),
                    power=self.power_spin.value(),
                    alpha=self.alpha_spin.value(),
                    correlation=self.correlation_spin.value(),
                    epsilon=self.epsilon_spin.value(),
                )
        except (ValueError, RuntimeError) as exc:
            self._clear_result()
            self.validation_banner.set_text(str(exc))
            self.validation_banner.show()
            return

        self.validation_banner.hide()
        self._show_result(result)

    def _lmm_config(self) -> LmmSensitivityConfig:
        targets = ("condition", "roi", "interaction")
        return LmmSensitivityConfig(
            sample_size=self.lmm_sample_size_spin.value(),
            conditions=self.lmm_conditions_spin.value(),
            rois=self.lmm_rois_spin.value(),
            target=targets[self.lmm_target_combo.currentIndex()],
            power=self.power_spin.value(),
            alpha=self.alpha_spin.value(),
            correlation=self.lmm_correlation_spin.value(),
            simulations=self.lmm_simulations_spin.value(),
            seed=self._lmm_seed,
        )

    def _start_lmm_simulation(self) -> None:
        if self._lmm_thread is not None:
            return
        config = self._lmm_config()
        try:
            validate_lmm_config(config)
        except ValueError as exc:
            self._clear_result()
            self.validation_banner.set_text(str(exc))
            self.validation_banner.show()
            return

        self._clear_result()
        self.validation_banner.hide()
        self.simulation_status.set_variant("info")
        self.simulation_status.set_text("Preparing mixed-model simulation...")
        self.simulation_status.show()
        self._set_simulation_controls_enabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.show()

        thread = QThread(self)
        worker = LmmSensitivityWorker(config)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_lmm_progress)
        worker.completed.connect(self._on_lmm_completed)
        worker.failed.connect(self._on_lmm_failed)
        worker.cancelled.connect(self._on_lmm_cancelled)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(self._on_lmm_finished)
        thread.finished.connect(thread.deleteLater)
        self._lmm_thread = thread
        self._lmm_worker = worker
        thread.start()

    def _set_simulation_controls_enabled(self, enabled: bool) -> None:
        controls = (
            self.analysis_combo,
            self.sample_size_spin,
            self.power_spin,
            self.alpha_spin,
            self.alternative_combo,
            self.effect_target_combo,
            self.conditions_spin,
            self.rois_spin,
            self.correlation_spin,
            self.epsilon_spin,
            self.lmm_target_combo,
            self.lmm_sample_size_spin,
            self.lmm_conditions_spin,
            self.lmm_rois_spin,
            self.lmm_correlation_spin,
            self.lmm_simulations_spin,
            self.reset_button,
        )
        for control in controls:
            control.setEnabled(enabled)
        self.calculate_button.setEnabled(enabled)

    def _cancel_lmm_simulation(self) -> None:
        if self._lmm_worker is None:
            return
        self._lmm_worker.cancel()
        self.cancel_button.setEnabled(False)
        self.simulation_status.set_variant("info")
        self.simulation_status.set_text("Cancelling after the current model fit...")

    def _on_lmm_progress(self, percent: int, message: str) -> None:
        self.simulation_status.set_variant("info")
        self.simulation_status.set_text(f"{message} — {percent}%")
        self.simulation_status.show()

    def _on_lmm_completed(self, result: LmmSensitivityResult) -> None:
        self._show_lmm_result(result)
        if not result.target_power_met:
            self.simulation_status.set_variant("warning")
            self.simulation_status.set_text(
                "Independent confirmation remained below the requested power. "
                "Treat this effect estimate as unresolved. Close and reopen "
                "Sensitivity Analysis to generate a new simulation seed."
            )
            self.simulation_status.show()
        elif result.failed_fits or result.singular_fits:
            self.simulation_status.set_variant("warning")
            self.simulation_status.set_text(
                f"Fit diagnostics: {result.failed_fits} failed and "
                f"{result.singular_fits} singular final fits out of "
                f"{result.simulations}."
            )
            self.simulation_status.show()
        else:
            self.simulation_status.hide()

    def _on_lmm_failed(self, message: str) -> None:
        self._clear_result()
        self.simulation_status.set_variant("error")
        self.simulation_status.set_text(message)
        self.simulation_status.show()

    def _on_lmm_cancelled(self) -> None:
        self._clear_result()
        self.simulation_status.set_variant("info")
        self.simulation_status.set_text("Mixed-model simulation cancelled.")
        self.simulation_status.show()

    def _on_lmm_finished(self) -> None:
        self._lmm_thread = None
        self._lmm_worker = None
        self._set_simulation_controls_enabled(True)
        self.cancel_button.hide()
        self._update_assumption_guidance()

    def shutdown(self, timeout_ms: int = 3_000) -> None:
        """Request simulation cancellation and briefly join the worker on app exit."""

        worker = self._lmm_worker
        thread = self._lmm_thread
        if worker is None or thread is None:
            return
        worker.cancel()
        thread.quit()
        thread.wait(timeout_ms)

    def _show_lmm_result(self, result: LmmSensitivityResult) -> None:
        target_labels = {
            "condition": "condition contrast",
            "roi": "ROI contrast",
            "interaction": "condition × ROI difference-in-differences",
        }
        target_label = target_labels[result.target]
        self.result_banner.set_result("Standardized contrast", result.effect_size)
        self.magnitude_label.setText(
            f"Simulated effect: {target_label} in residual-SD units"
        )
        self.equivalent_label.setText(
            f"Estimated power: {result.estimated_power:.1%} "
            f"(95% Monte Carlo interval {result.power_ci_low:.1%}–"
            f"{result.power_ci_high:.1%})"
        )
        self.equivalent_label.show()
        self.plain_language_label.setText(
            f"The simulation estimated that a standardized {target_label} of "
            f"approximately {result.effect_size:.2f} corresponds to the requested "
            f"power under this model. At that value, {result.estimated_power:.1%} "
            f"of {result.simulations} simulated studies produced a significant "
            "omnibus Wald test. The final simulations were independent of the "
            "adaptive effect search. This estimates design sensitivity; it does "
            "not validate the fit of a model to observed data."
        )
        self.assumption_summary_label.setText(
            f"{self.lmm_sample_size_spin.value()} analyzable participants · "
            f"{self.lmm_conditions_spin.value()} conditions · "
            f"{self.lmm_rois_spin.value()} ROIs · {target_label} · random-intercept "
            f"correlation = {self.lmm_correlation_spin.value():.2f} · "
            f"alpha = {self.alpha_spin.value():g} · "
            f"target power = {self.power_spin.value():.0%} · "
            f"seed = {result.seed}"
        )
        self.reporting_label.setText(
            f"A simulation-based sensitivity analysis using {result.simulations} "
            "independent confirmation replicates of a random-intercept linear "
            "mixed model estimated a "
            f"minimum standardized {target_label} of approximately "
            f"{result.effect_size:.2f} for {self.power_spin.value():.0%} power at "
            f"alpha = {self.alpha_spin.value():g}. Final simulated power was "
            f"{result.estimated_power:.1%} (95% Monte Carlo interval "
            f"{result.power_ci_low:.1%}–{result.power_ci_high:.1%}); "
            f"{result.successful_fits}/{result.simulations} final models converged. "
            f"The adaptive search used {result.search_simulations} model fits, "
            f"finished with a {result.search_effect_low:.3f} to "
            f"{result.search_effect_high:.3f} effect bracket, and ran on "
            f"{result.workers_used} worker process(es)."
        )

    def _show_result(self, result: SensitivityResult) -> None:
        self.result_banner.set_result(result.effect_metric, result.effect_size)
        self.magnitude_label.setText(
            f"Conventional magnitude: {result.magnitude}"
        )
        if result.equivalent_eta_squared is not None:
            self.equivalent_label.setText(
                f"Equivalent eta-squared: {result.equivalent_eta_squared:.3f}"
            )
            self.equivalent_label.show()
        else:
            self.equivalent_label.clear()
            self.equivalent_label.hide()
        self.plain_language_label.setText(self._plain_language_result(result))
        self.assumption_summary_label.setText(self._assumption_summary())
        self.reporting_label.setText(result.reporting_text)

    def _plain_language_result(self, result: SensitivityResult) -> str:
        sample_size = self.sample_size_spin.value()
        power = self.power_spin.value()
        alpha = self.alpha_spin.value()
        return (
            f"With {sample_size} analyzable participants, this model reaches "
            f"{power:.0%} power at approximately {result.effect_metric} = "
            f"{result.effect_size:.2f} with alpha = {alpha:g}. If the true "
            f"effect were {result.effect_size:.2f}, repeating the same study "
            "many times under these assumptions would be expected to produce "
            f"a statistically significant result about {power:.0%} of the "
            f"time. If the true effect were smaller than {result.effect_size:.2f}, "
            f"that percentage would be below {power:.0%}, but detection would "
            "still be possible. A non-significant result would not prove that "
            "no effect exists."
        )

    def _assumption_summary(self) -> str:
        common = (
            f"{self.sample_size_spin.value()} analyzable participants · "
            f"{self.power_spin.value():.0%} power · alpha = "
            f"{self.alpha_spin.value():g}"
        )
        if self.analysis_combo.currentIndex() == self.PAIRED_TEST:
            sidedness = (
                "two-sided"
                if self.alternative_combo.currentIndex() == 0
                else "one-sided"
            )
            return f"{common} · {sidedness} paired/one-sample t-test"

        target = self.effect_target_combo.currentText().lower()
        return (
            f"{common} · {self.conditions_spin.value()} conditions · "
            f"{self.rois_spin.value()} ROIs · {target} · "
            f"{self.measurements_spin.value()} repeated measurements · "
            f"average r = {self.correlation_spin.value():.2f} · epsilon = "
            f"{self.epsilon_spin.value():.2f}"
        )

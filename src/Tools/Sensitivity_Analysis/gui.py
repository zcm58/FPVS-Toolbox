"""Embedded PySide6 page for the standalone sensitivity calculator."""

from __future__ import annotations

import math

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
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
from Tools.Sensitivity_Analysis.tool_info import SENSITIVITY_ANALYSIS_TOOL_INFO


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
    CONDITION_EFFECT = 0
    ROI_EFFECT = 1
    OMNIBUS_CELLS = 2

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sensitivity Analysis")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
            ["Paired / one-sample t-test", "Repeated-measures ANOVA"]
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
        common_form.addRow("Analyzable participants (N):", self.sample_size_spin)

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
        actions = make_action_row(
            [self.reset_button, self.calculate_button], parent=card.content
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
            "A plain-language interpretation will appear after calculation.",
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
        self.calculate_button.clicked.connect(self.calculate)
        self.reset_button.clicked.connect(self.reset_defaults)

    def _on_assumptions_changed(self) -> None:
        self._clear_result()

    def _on_alternative_changed(self) -> None:
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
        is_rm_anova = self.analysis_combo.currentIndex() == self.RM_ANOVA
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
        elif not is_rm_anova and self.alternative_combo.currentIndex() == 1:
            self.assumption_guidance.set_variant("warning")
            self.assumption_guidance.set_text(
                "Use a one-sided test only for a directional hypothesis chosen "
                "before examining the data. An effect in the opposite direction "
                "would not count as support for that test."
            )
            self.assumption_guidance.show()
        else:
            self.assumption_guidance.hide()

    def _set_analysis_type(self, index: int) -> None:
        self.design_stack.setCurrentIndex(index)
        self.design_stack.updateGeometry()
        self._update_assumption_guidance()
        if index == self.PAIRED_TEST:
            self.benchmark_label.setText(
                "Conventional d benchmarks: 0.20 small, 0.50 medium, 0.80 large."
            )
        else:
            self.benchmark_label.setText(
                "Conventional f benchmarks: 0.10 small, 0.25 medium, 0.40 large."
            )
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
        self._set_analysis_type(self.PAIRED_TEST)

    def _clear_result(self) -> None:
        self.validation_banner.hide()
        self.result_banner.set_placeholder()
        self.magnitude_label.setText("Conventional magnitude: —")
        self.equivalent_label.clear()
        self.equivalent_label.hide()
        self.reporting_label.setText(
            "A reporting-ready summary will appear after calculation."
        )
        self.plain_language_label.setText(
            "A plain-language interpretation will appear after calculation."
        )
        self.assumption_summary_label.setText(
            "Current assumptions will appear after calculation."
        )

    def calculate(self) -> None:
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
            f"{result.effect_size:.2f} with alpha = {alpha:g}. Effects smaller "
            f"than {result.effect_size:.2f} have less than {power:.0%} power "
            "under these assumptions; they are not ruled out."
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

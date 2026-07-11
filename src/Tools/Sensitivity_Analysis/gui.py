"""Embedded PySide6 page for the standalone sensitivity calculator."""

from __future__ import annotations

from PySide6.QtCore import Qt
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
)
from Tools.Sensitivity_Analysis.calculator import (
    SensitivityResult,
    calculate_paired_ttest_sensitivity,
    calculate_rm_anova_sensitivity,
)


class SensitivityAnalysisWindow(QWidget):
    """Input-only sensitivity analysis page embedded in the Main App."""

    PAIRED_TEST = 0
    RM_ANOVA = 1

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
        page_layout.setSpacing(16)

        title = QLabel("Sensitivity Analysis", page)
        title.setObjectName("sensitivity_title")
        apply_font_role(title, "project_title")
        page_layout.addWidget(title)

        subtitle = QLabel(
            "Estimate the smallest standardized effect a study can detect from "
            "its planned sample size, power, alpha, and design assumptions.",
            page,
        )
        subtitle.setObjectName("sensitivity_subtitle")
        subtitle.setWordWrap(True)
        page_layout.addWidget(subtitle)

        sections = QGridLayout()
        sections.setContentsMargins(0, 0, 0, 0)
        sections.setHorizontalSpacing(16)
        sections.setVerticalSpacing(16)
        sections.setColumnStretch(0, 1)
        sections.setColumnStretch(1, 1)
        page_layout.addLayout(sections, 1)

        inputs_card = SectionCard(
            "Analysis assumptions",
            page,
            object_name="sensitivity_inputs_card",
        )
        inputs_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        sections.addWidget(inputs_card, 0, 0)
        self._build_inputs(inputs_card)

        results_card = SectionCard(
            "Detectable effect",
            page,
            object_name="sensitivity_results_card",
        )
        results_card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        common_form.addRow("Analysis:", self.analysis_combo)

        self.sample_size_spin = QSpinBox(card.content)
        self.sample_size_spin.setObjectName("sensitivity_sample_size")
        self.sample_size_spin.setRange(3, 100_000)
        common_form.addRow("Sample size (N):", self.sample_size_spin)

        self.power_spin = QDoubleSpinBox(card.content)
        self.power_spin.setObjectName("sensitivity_power")
        self.power_spin.setDecimals(2)
        self.power_spin.setSingleStep(0.05)
        self.power_spin.setRange(0.50, 0.99)
        common_form.addRow("Desired power:", self.power_spin)

        self.alpha_spin = QDoubleSpinBox(card.content)
        self.alpha_spin.setObjectName("sensitivity_alpha")
        self.alpha_spin.setDecimals(3)
        self.alpha_spin.setSingleStep(0.01)
        self.alpha_spin.setRange(0.001, 0.250)
        common_form.addRow("Alpha:", self.alpha_spin)

        self.design_stack = QStackedWidget(card.content)
        self.design_stack.setObjectName("sensitivity_design_stack")
        self.design_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        card.content_layout.addWidget(self.design_stack)

        paired_panel = QWidget(self.design_stack)
        paired_form = make_form_layout()
        paired_panel.setLayout(paired_form)
        self.alternative_combo = QComboBox(paired_panel)
        self.alternative_combo.setObjectName("sensitivity_alternative")
        self.alternative_combo.addItems(["Two-sided", "One-sided (directional)"])
        paired_form.addRow("Alternative:", self.alternative_combo)
        self.design_stack.addWidget(paired_panel)

        rm_panel = QWidget(self.design_stack)
        rm_form = make_form_layout()
        rm_panel.setLayout(rm_form)
        self.measurements_spin = QSpinBox(rm_panel)
        self.measurements_spin.setObjectName("sensitivity_measurements")
        self.measurements_spin.setRange(2, 100)
        rm_form.addRow("Repeated measurements:", self.measurements_spin)

        self.correlation_spin = QDoubleSpinBox(rm_panel)
        self.correlation_spin.setObjectName("sensitivity_correlation")
        self.correlation_spin.setDecimals(2)
        self.correlation_spin.setSingleStep(0.05)
        self.correlation_spin.setRange(-0.99, 0.99)
        rm_form.addRow("Average correlation:", self.correlation_spin)

        self.epsilon_spin = QDoubleSpinBox(rm_panel)
        self.epsilon_spin.setObjectName("sensitivity_epsilon")
        self.epsilon_spin.setDecimals(2)
        self.epsilon_spin.setSingleStep(0.05)
        self.epsilon_spin.setRange(0.01, 1.00)
        rm_form.addRow("Nonsphericity epsilon:", self.epsilon_spin)
        self.design_stack.addWidget(rm_panel)

        card.content_layout.addStretch(1)
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

    def _build_results(self, card: SectionCard) -> None:
        intro = QLabel(
            "The result is the minimum effect expected to reach the selected "
            "power under these assumptions.",
            card.content,
        )
        intro.setWordWrap(True)
        card.content_layout.addWidget(intro)

        self.result_banner = StatusBanner(
            "Set the assumptions and select Calculate.",
            card.content,
            variant="info",
        )
        self.result_banner.setObjectName("sensitivity_result")
        apply_font_role(self.result_banner.label, "project_title")
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

        self.reporting_label = QLabel("", card.content)
        self.reporting_label.setObjectName("sensitivity_reporting_text")
        self.reporting_label.setWordWrap(True)
        self.reporting_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card.content_layout.addWidget(self.reporting_label)

        card.content_layout.addStretch(1)
        self.benchmark_label = QLabel("", card.content)
        self.benchmark_label.setObjectName("sensitivity_benchmarks")
        self.benchmark_label.setWordWrap(True)
        card.content_layout.addWidget(self.benchmark_label)

    def _connect_signals(self) -> None:
        self.analysis_combo.currentIndexChanged.connect(self._set_analysis_type)
        self.calculate_button.clicked.connect(self.calculate)
        self.reset_button.clicked.connect(self.reset_defaults)

    def _set_analysis_type(self, index: int) -> None:
        self.design_stack.setCurrentIndex(index)
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
        self.measurements_spin.setValue(2)
        self.correlation_spin.setValue(0.50)
        self.epsilon_spin.setValue(1.00)
        self._set_analysis_type(self.PAIRED_TEST)

    def _clear_result(self) -> None:
        self.validation_banner.hide()
        self.result_banner.set_variant("info")
        self.result_banner.set_text("Set the assumptions and select Calculate.")
        self.magnitude_label.setText("Conventional magnitude: —")
        self.equivalent_label.clear()
        self.equivalent_label.hide()
        self.reporting_label.clear()

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
            self.validation_banner.set_text(str(exc))
            self.validation_banner.show()
            return

        self.validation_banner.hide()
        self._show_result(result)

    def _show_result(self, result: SensitivityResult) -> None:
        self.result_banner.set_variant("success")
        self.result_banner.set_text(
            f"{result.effect_metric} = {result.effect_size:.2f}"
        )
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
        self.reporting_label.setText(result.reporting_text)

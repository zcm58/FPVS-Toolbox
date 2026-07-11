from __future__ import annotations

import importlib.util

import pytest

if importlib.util.find_spec("PySide6") is None or importlib.util.find_spec("pytestqt") is None:
    pytest.skip("PySide6 or pytest-qt not available", allow_module_level=True)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea

from Main_App.gui.components import SectionCard, ToolInfoDialog
from Tools.Sensitivity_Analysis.gui import SensitivityAnalysisWindow
from Tools.Sensitivity_Analysis.lmm_simulation import (
    LmmSensitivityConfig,
    LmmSensitivityResult,
)
from Tools.Sensitivity_Analysis.tool_info import SENSITIVITY_ANALYSIS_TOOL_INFO
from Tools.Sensitivity_Analysis.worker import LmmSensitivityWorker


def _build_page(qtbot) -> SensitivityAnalysisWindow:
    page = SensitivityAnalysisWindow()
    qtbot.addWidget(page)
    page.resize(900, 700)
    page.show()
    qtbot.wait(30)
    return page


def test_defaults_and_paired_result_are_visible(qtbot) -> None:
    page = _build_page(qtbot)

    assert page.sample_size_spin.value() == 24
    assert page.power_spin.value() == pytest.approx(0.80)
    assert page.alpha_spin.value() == pytest.approx(0.05)
    assert page.design_stack.currentIndex() == page.PAIRED_TEST

    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)

    assert page.result_banner.text() == "Cohen's dz = 0.60"
    assert page.result_banner.metric_label.text() == "COHEN'S DZ"
    assert page.result_banner.value_label.text() == "0.60"
    assert page.result_banner.property("statusVariant") == "info"
    assert page.magnitude_label.text() == "Conventional magnitude: Medium"
    assert "this model reaches 80% power" in page.plain_language_label.text()
    assert "repeating the same study many times" in page.plain_language_label.text()
    assert "about 80% of the time" in page.plain_language_label.text()
    assert "would not prove that no effect exists" in page.plain_language_label.text()
    assert "24 analyzable participants" in page.assumption_summary_label.text()
    assert "two-sided paired/one-sample t-test" in page.assumption_summary_label.text()
    assert page.reporting_label.isVisibleTo(page)
    assert not page.equivalent_label.isVisibleTo(page)

    page.sample_size_spin.setValue(30)

    assert page.result_banner.text() == "Set the assumptions and select Calculate."
    assert "will appear after calculation" in page.plain_language_label.text()


def test_rm_anova_result_and_reset(qtbot) -> None:
    page = _build_page(qtbot)

    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    assert page.conditions_spin.value() == 2
    assert page.rois_spin.value() == 1
    assert page.effect_target_combo.currentIndex() == page.CONDITION_EFFECT
    assert page.measurements_spin.value() == 2
    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)

    assert page.design_stack.currentIndex() == page.RM_ANOVA
    assert page.result_banner.text() == "Cohen's f = 0.30"
    assert page.result_banner.metric_label.text() == "COHEN'S F"
    assert page.result_banner.value_label.text() == "0.30"
    assert page.magnitude_label.text() == "Conventional magnitude: Medium"
    assert page.equivalent_label.text() == "Equivalent eta-squared: 0.082"
    assert page.equivalent_label.isVisibleTo(page)
    assert "2 repeated measurements" in page.assumption_summary_label.text()

    qtbot.mouseClick(page.reset_button, Qt.LeftButton)

    assert page.analysis_combo.currentIndex() == page.PAIRED_TEST
    assert page.sample_size_spin.value() == 24
    assert page.result_banner.text() == "Set the assumptions and select Calculate."


def test_fpvs_design_inputs_derive_repeated_measurements(qtbot) -> None:
    page = _build_page(qtbot)
    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    page.conditions_spin.setValue(4)
    page.rois_spin.setValue(3)

    page.effect_target_combo.setCurrentIndex(page.CONDITION_EFFECT)
    assert page.measurements_spin.value() == 4
    assert "ROIs are assumed averaged" in page.measurement_explanation.text()

    page.effect_target_combo.setCurrentIndex(page.ROI_EFFECT)
    assert page.measurements_spin.value() == 3
    assert "Conditions are assumed averaged" in page.measurement_explanation.text()

    page.effect_target_combo.setCurrentIndex(page.OMNIBUS_CELLS)
    assert page.measurements_spin.value() == 12
    assert "not interaction power" in page.measurement_explanation.text()
    assert page.assumption_guidance.property("statusVariant") == "warning"
    assert "does not isolate condition, ROI, or interaction power" in (
        page.assumption_guidance.text()
    )


def test_invalid_measurement_count_and_dynamic_bounds_are_explained(qtbot) -> None:
    page = _build_page(qtbot)
    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    assert page.epsilon_spin.minimum() == pytest.approx(1.00)
    page.conditions_spin.setValue(1)

    assert page.measurements_spin.value() == 1
    assert not page.calculate_button.isEnabled()
    assert page.assumption_guidance.property("statusVariant") == "error"
    assert "at least two repeated measurements" in page.assumption_guidance.text()

    page.conditions_spin.setValue(4)

    assert page.calculate_button.isEnabled()
    assert page.epsilon_spin.minimum() == pytest.approx(0.34)
    assert page.correlation_spin.minimum() == pytest.approx(-0.33)

    page.conditions_spin.setValue(12)

    assert page.epsilon_spin.minimum() == pytest.approx(0.10)
    assert page.correlation_spin.minimum() == pytest.approx(-0.09)


def test_result_affecting_inputs_clear_stale_output(qtbot) -> None:
    page = _build_page(qtbot)
    paired_changes = (
        lambda: page.sample_size_spin.setValue(30),
        lambda: page.power_spin.setValue(0.85),
        lambda: page.alpha_spin.setValue(0.04),
        lambda: page.alternative_combo.setCurrentIndex(1),
    )
    for change in paired_changes:
        page.reset_defaults()
        page.calculate()
        change()
        assert page.result_banner.text() == (
            "Set the assumptions and select Calculate."
        )

    rm_changes = (
        (lambda: None, lambda: page.correlation_spin.setValue(0.60)),
        (
            lambda: page.conditions_spin.setValue(3),
            lambda: page.epsilon_spin.setValue(0.75),
        ),
        (lambda: None, lambda: page.conditions_spin.setValue(3)),
        (
            lambda: None,
            lambda: page.effect_target_combo.setCurrentIndex(page.OMNIBUS_CELLS),
        ),
    )
    for setup, change in rm_changes:
        page.reset_defaults()
        page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
        setup()
        page.calculate()
        change()
        assert page.result_banner.text() == (
            "Set the assumptions and select Calculate."
        )


def test_one_sided_choice_shows_directional_warning(qtbot) -> None:
    page = _build_page(qtbot)
    page.alternative_combo.setCurrentIndex(1)

    assert page.calculate_button.isEnabled()
    assert page.assumption_guidance.property("statusVariant") == "warning"
    assert "before examining the data" in page.assumption_guidance.text()
    assert "opposite direction" in page.assumption_guidance.text()

    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)

    assert page.assumption_guidance.isVisibleTo(page)
    assert page.result_banner.text() != "Set the assumptions and select Calculate."


def test_calculation_error_clears_previous_result(qtbot) -> None:
    page = _build_page(qtbot)
    page.analysis_combo.setCurrentIndex(page.RM_ANOVA)
    qtbot.mouseClick(page.calculate_button, Qt.LeftButton)
    assert page.result_banner.text() == "Cohen's f = 0.30"

    page.measurements_spin.setValue(1)
    page.calculate()

    assert page.validation_banner.isVisibleTo(page)
    assert "at least 2" in page.validation_banner.text()
    assert page.result_banner.text() == "Set the assumptions and select Calculate."
    assert "will appear after calculation" in page.reporting_label.text()


def test_info_dialog_explains_repeated_measurement_derivation(qtbot) -> None:
    page = _build_page(qtbot)
    dialog = ToolInfoDialog(SENSITIVITY_ANALYSIS_TOOL_INFO, page)
    qtbot.addWidget(dialog)
    text = "\n".join(browser.toPlainText() for browser in dialog.browsers)

    assert page.tool_info_button.toolTip() == "About Sensitivity Analysis"
    assert dialog.tab_widget is not None
    assert dialog.tab_widget.count() == 6
    assert dialog.tab_widget.tabText(0) == "Quick Guide"
    assert dialog.tab_widget.tabText(1) == "FPVS Design"
    assert dialog.tab_widget.tabText(3) == "Mixed Models"
    assert dialog.tab_widget.tabText(5) == "Methods"
    assert dialog.minimumWidth() == 600
    assert "Sample size (N) is the number of participants" in text
    assert "repeated measurements = conditions × ROIs" in text
    assert "does not isolate the condition effect" in text
    assert "Green and MacLeod (2016)" in text
    assert "10.1111/2041-210X.12504" in text


def test_lmm_mode_exposes_supported_model_and_validation(qtbot) -> None:
    page = _build_page(qtbot)
    page.analysis_combo.setCurrentIndex(page.LMM_SIMULATION)

    assert page.design_stack.currentIndex() == page.LMM_SIMULATION
    assert page.calculate_button.text() == "Run Simulation"
    assert page.lmm_conditions_spin.value() == 2
    assert page.lmm_rois_spin.value() == 2
    assert page.lmm_correlation_spin.value() == pytest.approx(0.50)
    assert page.lmm_simulations_spin.value() == 400
    assert page.lmm_seed_spin.value() == 2026
    assert page.calculate_button.isEnabled()
    assert "Monte Carlo" in page.assumption_guidance.text()

    page.lmm_rois_spin.setValue(1)

    assert not page.calculate_button.isEnabled()
    assert page.assumption_guidance.property("statusVariant") == "error"
    assert "at least two conditions and two ROIs" in page.assumption_guidance.text()


def test_lmm_result_reports_simulation_uncertainty_without_cohen_labels(qtbot) -> None:
    page = _build_page(qtbot)
    page.analysis_combo.setCurrentIndex(page.LMM_SIMULATION)
    result = LmmSensitivityResult(
        effect_size=0.72,
        estimated_power=0.805,
        power_ci_low=0.765,
        power_ci_high=0.840,
        simulations=400,
        successful_fits=390,
        failed_fits=10,
        singular_fits=4,
        target="interaction",
        seed=2026,
    )

    page._show_lmm_result(result)

    assert page.result_banner.text() == "Standardized contrast = 0.72"
    assert page.result_banner.property("statusVariant") == "info"
    assert "residual-SD units" in page.magnitude_label.text()
    assert "80.5%" in page.equivalent_label.text()
    assert "Monte Carlo interval" in page.equivalent_label.text()
    assert "not uncertainty about the real study effect" in (
        page.plain_language_label.text()
    )
    assert "seed = 2026" in page.assumption_summary_label.text()
    assert "390/400 final models converged" in page.reporting_label.text()
    assert "No universal small, medium, or large benchmarks" in (
        page.benchmark_label.text()
    )


def test_lmm_worker_emits_progress_and_completion(qtbot) -> None:
    config = LmmSensitivityConfig(
        sample_size=24,
        conditions=2,
        rois=2,
        target="condition",
        simulations=100,
    )
    expected = LmmSensitivityResult(
        effect_size=0.50,
        estimated_power=0.80,
        power_ci_low=0.71,
        power_ci_high=0.87,
        simulations=100,
        successful_fits=100,
        failed_fits=0,
        singular_fits=0,
        target="condition",
        seed=2026,
    )

    def fake_runner(config, *, progress, should_cancel):
        assert config.sample_size == 24
        assert not should_cancel()
        progress(50, "Testing")
        return expected

    worker = LmmSensitivityWorker(config, runner=fake_runner)
    progress_events = []
    completed = []
    worker.progress.connect(lambda percent, text: progress_events.append((percent, text)))
    worker.completed.connect(completed.append)

    with qtbot.waitSignal(worker.finished):
        worker.run()

    assert progress_events == [(50, "Testing")]
    assert completed == [expected]


def test_embedded_surface_has_no_horizontal_clipping(qtbot) -> None:
    page = _build_page(qtbot)
    scroll = page.findChild(QScrollArea, "sensitivity_scroll_area")
    inputs = page.findChild(SectionCard, "sensitivity_inputs_card")
    results = page.findChild(SectionCard, "sensitivity_results_card")

    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert scroll.widget().width() <= scroll.viewport().width()
    assert inputs is not None and inputs.width() >= 350
    assert results is not None and results.width() >= 350
    assert inputs.geometry().right() < scroll.widget().width()
    assert results.geometry().right() < scroll.widget().width()
    assert inputs.minimumSizeHint().height() <= inputs.height()
    assert results.minimumSizeHint().height() <= results.height()
    assert page.calculate_button.isVisibleTo(page)
    assert page.reset_button.isVisibleTo(page)
    assert page.disclaimer.isVisibleTo(page)
